import json
import threading
import time

import mido
import pytest

import whiplash
from whiplash import ccmap, engine, patterns, tools


class FakePort:
    def __init__(self):
        self.messages = []
        self.lock = threading.Lock()

    def send(self, msg):
        with self.lock:
            self.messages.append(msg)

    def close(self):
        pass


@pytest.fixture
def fake():
    port = FakePort()
    eng = engine.Engine(opener=lambda name: (port, name or "Fake", True))
    yield eng, port
    eng.stop()


class Ctx:
    def __init__(self):
        self.tools = {}

    def register_tool(self, name, toolset, schema, handler, **kw):
        assert schema["name"] == name and "description" in schema and schema["parameters"]["type"] == "object"
        self.tools[name] = handler


def test_register_is_fast_and_lazy():
    ctx = Ctx()
    t = time.perf_counter()
    whiplash.register(ctx)
    assert time.perf_counter() - t < 0.5
    assert set(ctx.tools) == set(tools.HANDLERS)
    assert tools.ENGINE._port is None  # no MIDI opened at load


def test_manifest_lists_every_tool():
    import yaml
    manifest = yaml.safe_load(open(whiplash.__path__[0] + "/plugin.yaml"))
    assert manifest["name"] == "whiplash"
    assert set(manifest["provides_tools"]) == set(tools.HANDLERS)


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


def test_play_bars_sends_clock_transport_notes(fake):
    eng, port = fake
    eng.play(patterns.PATTERNS["techno"], bpm=300, bars=1)
    eng._thread.join(timeout=5)
    types = [m.type for m in port.messages]
    assert types[0] == "start" and "stop" in types
    assert types.count("clock") == 96  # 1 bar = 16 steps * 6 ticks
    kicks = [m for m in port.messages if m.type == "note_on" and m.channel == 0]
    assert len(kicks) == 4
    channels = {m.channel for m in port.messages if m.type == "note_on"}
    assert channels <= set(range(8))
    ons = sum(m.type == "note_on" for m in port.messages)
    offs = sum(m.type == "note_off" for m in port.messages)
    assert ons == offs and not eng._sounding
    assert not any(m.type == "sysex" for m in port.messages)


def test_mute_tempo_stop_live(fake):
    eng, port = fake
    eng.set_mute(1, True)
    eng.play(patterns.PATTERNS["deephouse"], bpm=240)
    time.sleep(0.3)
    eng.set_tempo(200)
    assert eng.bpm == 200
    eng.stop()
    assert not eng.playing()
    assert not any(m.type == "note_on" and m.channel == 0 for m in port.messages)
    tail = port.messages[-9:]
    assert [m.control for m in tail[:8]] == [123] * 8 and tail[-1].type == "stop"


def test_set_param_cc_nrpn_and_blocks(fake):
    eng, port = fake
    eng.ensure_port()
    assert eng.set_param(1, 64, param="filter cutoff")["cc"] == 74
    eng.set_param(2, 100, param="resonance")
    assert port.messages[-1].channel == 1 and port.messages[-1].control == 75
    eng.set_param(3, 5000, nrpn=[1, 20])
    assert [m.control for m in port.messages[-4:]] == [99, 98, 6, 38]
    assert [m.value for m in port.messages[-4:]] == [1, 20, 5000 >> 7, 5000 & 127]
    for bad in (dict(cc=19), dict(cc=24), dict(cc=0), dict(nrpn=[1, 3]), dict(param="sample"), dict(cc=74, value=200)):
        kwargs = {"value": 1, **bad}
        with pytest.raises(engine.WhiplashError):
            eng.set_param(1, kwargs.pop("value"), **kwargs)


def test_refuses_sysex_and_program_change(fake):
    eng, _ = fake
    eng.ensure_port()
    for msg in (mido.Message("sysex", data=[0, 32, 60]), mido.Message("program_change", program=1)):
        with pytest.raises(engine.WhiplashError):
            eng.send(msg)


def test_missing_device_clear_error(monkeypatch):
    monkeypatch.setattr(mido, "get_output_names", lambda: ["IAC Driver Bus 1"])
    with pytest.raises(engine.WhiplashError, match="Digitakt II not found"):
        engine.Engine().ensure_port(allow_virtual=False)
    with pytest.raises(engine.WhiplashError, match="not found"):
        engine.Engine().ensure_port(port="Nope")


def test_tool_errors_are_json():
    out = json.loads(tools.set_tempo({"bpm": 9999}))
    assert out["success"] is False and "30-300" in out["error"]
    out = json.loads(tools.play_pattern({"genre": "polka"}))
    assert out["success"] is False


def test_virtual_port_end_to_end():
    """Real rtmidi: the plugin opens virtual 'Whiplash', a listener receives the beat."""
    if "Whiplash" in mido.get_input_names():
        pytest.skip("a Whiplash port already exists")
    try:
        out = json.loads(tools.play_pattern({"genre": "deephouse", "bpm": 240, "bars": 1, "port": "Whiplash"}))
        assert out["success"], out
        assert out["virtual"] and out["port"] == "Whiplash"
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
        tools.stop({})
        tools.ENGINE._close_port()
