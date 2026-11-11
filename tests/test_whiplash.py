import json
import threading
import time
import tomllib
import types

import mido
import pytest

import whiplash
from whiplash import engine, patterns, tools


class FakePort:
    def __init__(self, fail_after=None):
        self.messages = []
        self.lock = threading.Lock()
        self.closed = False
        self.fail_after = fail_after  # raise on every send once this many messages went out

    def send(self, msg):
        with self.lock:
            if self.fail_after is not None and len(self.messages) >= self.fail_after:
                raise OSError("device unplugged")
            self.messages.append(msg)

    def close(self):
        self.closed = True

    def count(self, kind, **attrs):
        return sum(m.type == kind and all(getattr(m, k) == v for k, v in attrs.items()) for m in self.messages)


def make_engine(port=None, virtual=False):
    port = port or FakePort()
    return engine.Engine(opener=lambda name: (port, name or "Fake", virtual)), port


@pytest.fixture
def fake():
    eng, port = make_engine()
    yield eng, port
    port.fail_after = None
    eng.shutdown()


@pytest.fixture
def tool_engine(monkeypatch):
    """Point the tool handlers at an engine backed by a fake port."""
    def install(virtual=False):
        eng, port = make_engine(virtual=virtual)
        monkeypatch.setattr(tools, "ENGINE", eng)
        installed.append(eng)
        return eng, port
    installed = []
    yield install
    for eng in installed:
        eng.shutdown()


def call(name, **params):
    return json.loads(tools.HANDLERS[name](params))


class Ctx:
    def __init__(self):
        self.tools = {}

    def register_tool(self, name, toolset, schema, handler, **kw):
        assert schema["name"] == name and "description" in schema and schema["parameters"]["type"] == "object"
        self.tools[name] = handler


# ---- plugin surface ------------------------------------------------------

def test_register_is_fast_and_lazy():
    ctx = Ctx()
    t = time.perf_counter()
    whiplash.register(ctx)
    assert time.perf_counter() - t < 0.5
    assert set(ctx.tools) == set(tools.HANDLERS)
    assert tools.ENGINE._port is None  # no MIDI opened at load


def test_every_tool_is_namespaced():
    assert len(tools.HANDLERS) == 20  # v0.6.2: whiplash_mix
    assert all(name.startswith("whiplash_") for name in tools.HANDLERS)


def test_manifest_lists_every_tool_and_declares_deps():
    import yaml
    root = whiplash.__path__[0]
    manifest = yaml.safe_load(open(root + "/plugin.yaml"))
    project = tomllib.load(open(root + "/pyproject.toml", "rb"))["project"]
    assert manifest["name"] == "whiplash"
    assert set(manifest["provides_tools"]) == set(tools.HANDLERS)
    assert manifest["requires_hermes"].startswith(">=")
    assert manifest["version"] == project["version"]
    # Hermes reads either file; they must agree, and every dependency needs a floor and a ceiling.
    assert manifest["python_dependencies"] == project["dependencies"]
    assert all(">=" in dep and "<" in dep for dep in project["dependencies"])


@pytest.mark.parametrize("name", sorted(patterns.PATTERNS))
def test_patterns_valid(name):
    p = patterns.PATTERNS[name]
    assert set(p.bars) == set(range(1, 9))
    for track, bars in p.bars.items():
        assert len(bars) == patterns.BARS
        for bar in bars:
            for step, note, vel, gate in bar:
                assert 0 <= step < 16 and 16 <= note <= 84 and 1 <= vel <= 127 and gate >= 1


def test_resolve_genre_mood_and_errors():
    assert patterns.resolve("deep house").name == "deephouse"
    assert patterns.resolve(mood="dark").name == "techno"
    assert patterns.resolve(mood="chill").bpm == 86
    with pytest.raises(ValueError):
        patterns.resolve("polka")


# ---- sequencer -----------------------------------------------------------

def test_play_bars_sends_clock_transport_notes(fake):
    eng, port = fake
    eng.play(patterns.PATTERNS["techno"], bpm=300, bars=1)
    eng._thread.join(timeout=5)
    types_ = [m.type for m in port.messages]
    assert types_[0] == "start" and types_[-1] == "stop"
    assert types_.count("clock") == 96  # 1 bar = 16 steps * 6 ticks
    assert port.count("note_on", channel=0) == 4
    assert {m.channel for m in port.messages if m.type == "note_on"} <= set(range(8))
    assert port.count("note_on") == port.count("note_off") and not eng._sounding
    assert port.count("sysex") == 0


def test_tempo_and_stop_live(fake):
    eng, port = fake
    eng.play(patterns.PATTERNS["deephouse"], bpm=240)
    time.sleep(0.2)
    eng.set_tempo(200)
    assert eng.bpm == 200
    assert eng.stop()["was_playing"] is True
    assert not eng.playing()
    tail = port.messages[-9:]
    assert [m.control for m in tail[:8]] == [123] * 8 and tail[-1].type == "stop"


@pytest.mark.parametrize("bpm", [-120, 0, 29.9, 300.1, 1e9, float("nan"), float("inf"), "fast"])
def test_play_rejects_bad_bpm_without_touching_the_beat(fake, bpm):
    eng, port = fake
    eng.play(patterns.PATTERNS["techno"], bpm=120)
    with pytest.raises(engine.WhiplashError, match="30-300"):
        eng.play(patterns.PATTERNS["soul"], bpm=bpm)
    assert eng.playing() and eng.pattern.name == "techno" and eng.bpm == 120
    assert port.count("stop") == 0  # the running beat was not interrupted


def test_negative_bpm_cannot_flood_the_port(tool_engine):
    eng, port = tool_engine()
    out = call("whiplash_play_pattern", genre="techno", bpm=-120)
    assert out["success"] is False and "30-300" in out["error"]
    time.sleep(0.1)
    assert not eng.playing() and port.messages == []


@pytest.mark.parametrize("bars", [0, -1, 1.5, 513, "many"])
def test_play_rejects_bad_bars(fake, bars):
    eng, _ = fake
    with pytest.raises(engine.WhiplashError, match="bars"):
        eng.play(patterns.PATTERNS["techno"], bars=bars)
    assert not eng.playing()


def test_stop_sends_exactly_one_panic(fake):
    eng, port = fake
    eng.play(patterns.PATTERNS["techno"], bpm=120)
    time.sleep(0.15)
    eng.stop()
    assert port.count("stop") == 1
    assert port.count("control_change", control=123) == 8


def test_natural_end_then_new_play_never_doubles_the_panic(fake):
    eng, port = fake
    eng.play(patterns.PATTERNS["techno"], bpm=300, bars=1)
    eng._thread.join(timeout=5)
    assert port.count("stop") == 1  # the run silenced the port itself
    eng.play(patterns.PATTERNS["soul"], bpm=300, bars=1)
    eng._thread.join(timeout=5)
    assert port.count("start") == 2
    assert port.count("stop") == 2  # v0.6.1: no idle panic before the new start (the first run silenced it), one at its end


def test_stop_when_idle_is_a_panic_button(fake):
    eng, port = fake
    eng.ensure_port()
    assert eng.stop() == {"was_playing": False, "mutes_cleared": [], "ramps_cancelled": []}
    assert port.count("stop") == 1 and port.count("control_change", control=123) == 8


def test_concurrent_play_calls_leave_one_sequencer(fake):
    eng, port = fake
    names = sorted(patterns.PATTERNS)
    workers = [threading.Thread(target=eng.play, args=(patterns.PATTERNS[names[i % 4]],), kwargs={"bpm": 200})
               for i in range(12)]
    for w in workers:
        w.start()
    for w in workers:
        w.join(timeout=10)
    time.sleep(0.1)
    alive = [t for t in threading.enumerate() if t.name == "whiplash-seq" and t.is_alive()]
    assert len(alive) == 1 and eng.playing()
    eng.stop()
    assert port.count("start") == 1  # the first call started; the rest queued live switches
    assert port.count("stop") == 1  # and no Stop at any of the queued switches
    assert not [t for t in threading.enumerate() if t.name == "whiplash-seq" and t.is_alive()]


# ---- mutes ---------------------------------------------------------------

def test_mute_silences_a_track_live(fake):
    eng, port = fake
    eng.play(patterns.PATTERNS["deephouse"], bpm=300)
    eng.set_mute(1, True)
    time.sleep(0.1)
    before = port.count("note_on", channel=0)
    time.sleep(0.5)
    assert port.count("note_on", channel=0) == before
    assert port.count("note_on", channel=3) > 0


def test_mutes_reset_on_stop_and_fresh_start(fake):
    eng, port = fake
    eng.play(patterns.PATTERNS["techno"], bpm=300)
    eng.set_mute(1, True)
    eng.set_mute(4, True)
    assert eng.stop()["mutes_cleared"] == [1, 4]
    assert eng.muted == set()
    port.messages.clear()
    eng.play(patterns.PATTERNS["techno"], bpm=300, bars=1)
    eng._thread.join(timeout=5)
    assert port.count("note_on", channel=0) == 4  # the kick is back

    eng.set_mute(2, True)  # muted after a natural end: a fresh start still clears it
    assert eng.play(patterns.PATTERNS["soul"], bpm=300)["mutes_cleared"] == [2]
    assert eng.status()["muted"] == []


def test_hardware_mutes_are_released_not_orphaned(fake):
    eng, port = fake
    eng.play(patterns.PATTERNS["techno"], bpm=300)
    eng.set_mute(2, True, hardware=True)
    assert port.count("control_change", control=94, value=1, channel=1) == 1
    assert eng.status()["hardware_muted"] == [2]
    eng.set_mute(2, False)  # no hardware flag: Whiplash still releases the mute it set
    assert port.count("control_change", control=94, value=0, channel=1) == 1
    eng.set_mute(3, True, hardware=True)
    eng.set_param(5, 1, param="mute")  # a unit mute set through set_param is tracked too
    assert eng.stop()["mutes_cleared"] == [3, 5]
    assert port.count("control_change", control=94, value=0, channel=2) == 1
    assert port.count("control_change", control=94, value=0, channel=4) == 1
    assert eng.status()["hardware_muted"] == []


# ---- parameters ----------------------------------------------------------

def test_set_param_cc_and_blocks(fake):
    eng, port = fake
    eng.ensure_port()
    assert eng.set_param(1, 64, param="filter cutoff")["cc"] == 74
    eng.set_param(2, 100, param="resonance")
    assert port.messages[-1].channel == 1 and port.messages[-1].control == 75
    sent = len(port.messages)
    for bad in (dict(cc=19), dict(cc=24), dict(cc=0), dict(nrpn=[1, 3]), dict(nrpn=[1, 8]), dict(nrpn=[1, 9]),
                dict(param="sample_bank"), dict(param="sample", value=200),
                dict(cc=74, value=200), dict(nrpn=[1, 200]), dict(nrpn=[1]), dict(),
                dict(param="cutoff", cc=74), dict(cc=74, nrpn=[1, 20]), dict(cc=74, track=17)):
        kwargs = {"value": 1, "track": 1, **bad}
        with pytest.raises(engine.WhiplashError):
            eng.set_param(kwargs.pop("track"), kwargs.pop("value"), **kwargs)
    assert len(port.messages) == sent  # nothing partial reached the port


@pytest.mark.parametrize("value", [0, 1, 100, 127, 128, 200, 5000, 8192, 16383])
def test_nrpn_is_always_14_bit(fake, value):
    eng, port = fake
    eng.ensure_port()
    out = eng.set_param(3, value, nrpn=[1, 20])
    last = port.messages[-4:]
    assert [m.control for m in last] == [99, 98, 6, 38] and {m.channel for m in last} == {2}
    assert [m.value for m in last] == [1, 20, value >> 7, value & 127]
    assert last[2].value * 128 + last[3].value == value  # round-trips, so it is monotonic
    assert (out["data_msb"], out["data_lsb"]) == (value >> 7, value & 127)


def test_nrpn_rejects_out_of_range(fake):
    eng, _ = fake
    eng.ensure_port()
    for value in (-1, 16384):
        with pytest.raises(engine.WhiplashError, match="0-16383"):
            eng.set_param(1, value, nrpn=[1, 20])


def test_refuses_sysex_and_program_change(fake):
    eng, _ = fake
    eng.ensure_port()
    for msg in (mido.Message("sysex", data=[0, 32, 60]), mido.Message("program_change", program=1)):
        with pytest.raises(engine.WhiplashError):
            eng.send(msg)


# ---- ports, fallback, faults, exit ---------------------------------------

def test_missing_device_clear_error(monkeypatch):
    backend = types.SimpleNamespace(get_output_names=lambda: ["IAC Driver Bus 1"])
    monkeypatch.setattr(engine, "_mido", lambda: backend)
    with pytest.raises(engine.WhiplashError, match="Digitakt II not found"):
        engine.Engine().ensure_port(allow_virtual=False)
    with pytest.raises(engine.WhiplashError, match="not found"):
        engine.Engine().ensure_port(port="Nope")


def test_real_port_selection_and_fallback_flag(monkeypatch):
    opened = []

    def open_output(name, virtual=False):
        opened.append((name, virtual))
        return FakePort()

    backend = types.SimpleNamespace(get_output_names=lambda: outputs, open_output=open_output)
    monkeypatch.setattr(engine, "_mido", lambda: backend)
    monkeypatch.setattr(engine.atexit, "register", lambda fn: fn)

    outputs = ["IAC Driver Bus 1", "Elektron Digitakt II"]
    eng = engine.Engine()
    assert eng.ensure_port() == "Elektron Digitakt II" and not eng.virtual and not eng.fallback

    outputs = ["IAC Driver Bus 1"]
    eng = engine.Engine()
    assert eng.ensure_port() == "Whiplash" and eng.virtual and eng.fallback  # nothing found: fallback
    outputs = ["IAC Driver Bus 1", "Elektron Digitakt II"]
    assert eng.ensure_port("Elektron Digitakt II") == "Elektron Digitakt II" and not eng.fallback

    eng = engine.Engine()
    assert eng.ensure_port("Whiplash") == "Whiplash" and eng.virtual and not eng.fallback  # asked for it
    assert opened == [("Elektron Digitakt II", False), ("Whiplash", True),
                      ("Elektron Digitakt II", False), ("Whiplash", True)]


def test_virtual_fallback_warns_on_every_tool_result(tool_engine):
    eng, _ = tool_engine(virtual=True)
    out = call("whiplash_play_pattern", genre="techno", bpm=300)
    assert out["success"] and out["virtual"] is True
    assert "NO DIGITAKT DETECTED" in out["warning"] and "whiplash_list_midi_ports" in out["warning"]
    for name, params in (("whiplash_set_param", dict(track=1, param="cutoff", value=10)),
                         ("whiplash_mute_track", dict(track=1)), ("whiplash_set_tempo", dict(bpm=140)),
                         ("whiplash_set_tempo", dict(bpm=9999)),  # errors carry it too
                         ("whiplash_status", {}), ("whiplash_stop", {})):
        assert "NO DIGITAKT DETECTED" in call(name, **params)["warning"], name
    assert call("whiplash_status")["fallback"] is True


def test_no_warning_on_a_real_port(tool_engine):
    tool_engine(virtual=False)
    out = call("whiplash_play_pattern", genre="techno", bpm=300)
    assert out["success"] and "warning" not in out
    assert "warning" not in call("whiplash_status")


def test_list_ports_warns_when_no_digitakt(monkeypatch):
    monkeypatch.setattr(engine, "list_ports", lambda: {"outputs": ["IAC Driver Bus 1"], "inputs": []})
    out = call("whiplash_list_midi_ports")
    assert out["digitakt"] is None and "No Digitakt II found" in out["warning"]
    monkeypatch.setattr(engine, "list_ports", lambda: {"outputs": ["Elektron Digitakt II"], "inputs": []})
    out = call("whiplash_list_midi_ports")
    assert out["digitakt"] == "Elektron Digitakt II" and "warning" not in out


def test_sequencer_fault_is_reported_in_status(fake):
    eng, port = fake
    port.fail_after = 40
    eng.play(patterns.PATTERNS["techno"], bpm=300)
    eng._thread.join(timeout=5)
    status = eng.status()
    assert status["playing"] is False
    assert status["last_error"].startswith("sequencer stopped: OSError: device unplugged")
    port.fail_after = None
    eng.play(patterns.PATTERNS["techno"], bpm=300)  # a clean start clears it
    assert eng.status()["last_error"] is None and eng.playing()


def test_exit_hook_silences_and_closes(monkeypatch):
    hooks = []
    monkeypatch.setattr(engine.atexit, "register", hooks.append)
    eng, port = make_engine()
    assert hooks == []  # nothing registered until a port is opened
    eng.play(patterns.PATTERNS["deephouse"], bpm=300)
    eng.ensure_port()
    assert hooks == [eng.shutdown]  # registered once
    eng.set_mute(2, True, hardware=True)
    time.sleep(0.1)
    hooks[0]()  # what the interpreter runs on exit
    assert not eng.playing() and port.closed and eng._port is None
    assert port.count("stop") == 1 and port.count("control_change", control=123) == 8
    assert port.count("note_on") == port.count("note_off")
    assert port.messages[-1].dict()["control"] == 94 and port.messages[-1].value == 0  # unit mute released
    eng.shutdown()  # idempotent, never raises


def test_exit_hook_never_raises_on_a_dead_port():
    eng, port = make_engine()
    eng.play(patterns.PATTERNS["techno"], bpm=300)
    time.sleep(0.05)
    port.fail_after = 0
    eng.shutdown()
    assert not eng.playing() and port.closed


# ---- tool layer ----------------------------------------------------------

def test_tool_errors_are_json(tool_engine):
    tool_engine()
    out = call("whiplash_set_tempo", bpm=9999)
    assert out["success"] is False and "30-300" in out["error"]
    assert call("whiplash_play_pattern", genre="polka")["success"] is False
    assert "missing required argument 'track'" in call("whiplash_mute_track")["error"]
    assert "track must be 1-16" in call("whiplash_mute_track", track=99)["error"]


def test_tool_play_stop_report_mutes(tool_engine):
    tool_engine()
    out = call("whiplash_play_pattern", genre="techno", bpm=300)
    assert out["mode"] == "started" and out["mutes_cleared"] == []
    assert call("whiplash_mute_track", track=1)["all_muted"] == [1]
    out = call("whiplash_play_pattern", mood="chill")  # live switch: queued, mute carried
    assert out["mode"] == "queued" and out["next"] == "soul" and out["playing"] == "techno"
    assert out["muted_carried"] == [1] and out["switch_at_bar"] >= 1 and out["bpm_at_switch"] == 86
    call("whiplash_mute_track", track=6, hardware=True)
    out = call("whiplash_stop")
    assert out == {"success": True, "stopped": True, "was_playing": True, "mutes_cleared": [1, 6],
                   "ramps_cancelled": []}


def test_virtual_port_end_to_end():
    """Real rtmidi: the plugin opens virtual 'Whiplash', a listener receives the beat."""
    try:
        names = engine.list_ports()["inputs"]
    except Exception as exc:  # no rtmidi backend or no system MIDI (e.g. ALSA sequencer) here
        pytest.skip(f"no usable MIDI backend: {exc}")
    if "Whiplash" in names:
        pytest.skip("a Whiplash port already exists")
    try:
        out = call("whiplash_play_pattern", genre="deephouse", bpm=240, bars=1, port="Whiplash")
        if not out["success"] and "NotImplementedError" in out["error"]:
            pytest.skip("this platform has no virtual MIDI ports")
        assert out["success"], out
        assert out["virtual"] and out["port"] == "Whiplash" and "warning" not in out
        time.sleep(0.05)
        received = []
        with mido.open_input("Whiplash") as inport:
            tools.ENGINE._thread.join(timeout=5)
            time.sleep(0.2)
            received = list(inport.iter_pending())
        assert any(m.type == "note_on" for m in received)
        assert any(m.type == "clock" for m in received)
        assert received[-1].type == "stop"
    finally:
        tools.ENGINE.shutdown()
