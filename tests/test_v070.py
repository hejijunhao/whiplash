"""v0.7.0 without numpy: packaging (optional [listen] extra, import without it), input-device discovery, and the
safety rails (ramp cap, ramp CC rate cap, loudness guard). Fake ports only; nothing here says how the Digitakt II
sounds. The audio analysis and the capture path are in test_v070_listen.py, which needs numpy."""
import json
import os
import subprocess
import sys
import tomllib
from pathlib import Path

import mido
import pytest
import yaml

import whiplash
from whiplash import ccmap, engine, listen, patterns, schemas, tools
from test_whiplash import call, make_engine, tool_engine  # noqa: F401  (fixture)
from test_live import pretend_playing

P = patterns.PATTERNS
ROOT = Path(whiplash.__path__[0])
LEVEL, DRIVE, VOLUME, FILTER = 95, 57, 89, 74
CLIPPED = {"loudness": {"clipping": True, "lufs_ish": -6.0, "peak_dbfs": 0.0}, "bars": 2, "silent": False}
CLEAN = {"loudness": {"clipping": False, "lufs_ish": -12.0, "peak_dbfs": -3.0}, "bars": 2, "silent": False}


@pytest.fixture
def fake():
    eng, port = make_engine()
    yield eng, port
    eng.shutdown()


def assert_safe(port):
    for m in port.messages:
        assert m.type in engine.ALLOWED_TYPES, m
        if m.type == "control_change":
            assert m.control not in ccmap.BLOCKED_CCS, m


def ccs(port, control=None):
    return [m for m in port.messages if m.type == "control_change" and (control is None or m.control == control)]


# ---- version, manifests, packaging --------------------------------------------------------------

def test_version_is_0_7_0():
    assert whiplash.__version__ == "0.7.0"
    assert yaml.safe_load(open(ROOT / "plugin.yaml"))["version"] == "0.7.0"
    assert yaml.safe_load(open(ROOT / "docs" / "catalog-entry.yaml"))["version"] == "0.7.0"
    assert tomllib.load(open(ROOT / "pyproject.toml", "rb"))["project"]["version"] == "0.7.0"
    releases = [h for h in (ROOT / "CHANGELOG.md").read_text().split("\n## ")[1:] if not h.startswith("Unreleased")]
    assert releases[0].startswith("0.7.0")


def test_listen_is_listed_after_status_everywhere():
    for manifest in (yaml.safe_load(open(ROOT / "plugin.yaml"))["provides_tools"],
                     yaml.safe_load(open(ROOT / "docs" / "catalog-entry.yaml"))["capabilities"]["provides_tools"],
                     list(schemas.SCHEMAS), list(tools.HANDLERS)):
        assert manifest.index("whiplash_listen") == manifest.index("whiplash_status") + 1
    skill = (ROOT / "skills" / "digitakt" / "SKILL.md").read_text()
    assert "whiplash_listen" in skill and "force" in skill and "USB AUDIO/MIDI" in skill
    readme = (ROOT / "README.md").read_text()
    assert "whiplash_listen" in readme and "[listen]" in readme


def test_listen_deps_are_an_optional_extra_only():
    project = tomllib.load(open(ROOT / "pyproject.toml", "rb"))["project"]
    deps = " ".join(project["dependencies"])
    assert "numpy" not in deps and "sounddevice" not in deps  # the plugin itself needs neither
    extra = project["optional-dependencies"]["listen"]
    assert {d.split(">")[0] for d in extra} == {"numpy", "sounddevice"}
    assert all(">=" in d and "<" in d for d in extra)
    manifest = yaml.safe_load(open(ROOT / "plugin.yaml"))
    assert manifest["python_dependencies"] == project["dependencies"]


BLOCKER = r"""
import importlib.abc, importlib.util, json, sys
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in ("numpy", "sounddevice"):
            raise ImportError(f"blocked {name}")
        return None
sys.meta_path.insert(0, Block())
root = sys.argv[1]
spec = importlib.util.spec_from_file_location("whiplash", root + "/__init__.py", submodule_search_locations=[root])
mod = importlib.util.module_from_spec(spec); sys.modules["whiplash"] = mod; spec.loader.exec_module(mod)
names = []
class Ctx:
    def register_tool(self, name, **kw): names.append(name)
mod.register(Ctx())
from whiplash import listen, tools
out = {"tools": names, "numpy_loaded": "numpy" in sys.modules, "available": listen.available(),
       "listen": json.loads(tools.HANDLERS["whiplash_listen"]({})),
       "bad_bars": json.loads(tools.HANDLERS["whiplash_listen"]({"bars": 99})),
       "params": json.loads(tools.HANDLERS["whiplash_list_params"]({}))["success"]}
print(json.dumps(out))
"""


def test_plugin_imports_and_runs_without_numpy_or_sounddevice():
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    done = subprocess.run([sys.executable, "-c", BLOCKER, str(ROOT)], capture_output=True, text=True, env=env,
                          timeout=60)
    assert done.returncode == 0, done.stderr
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert "whiplash_listen" in out["tools"] and len(out["tools"]) == len(schemas.SCHEMAS)
    assert out["numpy_loaded"] is False
    assert out["listen"]["success"] is False
    assert "numpy" in out["listen"]["error"] and "pip install" in out["listen"]["error"]
    assert "Every other Whiplash tool works" in out["listen"]["error"]
    assert out["bad_bars"]["success"] is False and "bars must be 1-8" in out["bad_bars"]["error"]
    assert out["params"] is True


def test_importing_whiplash_does_not_import_numpy():
    code = ("import sys; sys.path.insert(0, 'tests'); import conftest; "
            "from whiplash import tools, listen, engine; print('numpy' in sys.modules, 'sounddevice' in sys.modules)")
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=ROOT, timeout=60)
    assert done.stdout.split() == ["False", "False"], done.stderr


# ---- device discovery ---------------------------------------------------------------------------

DEVICES = [
    {"name": "MacBook Pro Microphone", "max_input_channels": 1, "max_output_channels": 0, "default_samplerate": 48000.0},
    {"name": "MacBook Pro Speakers", "max_input_channels": 0, "max_output_channels": 2, "default_samplerate": 48000.0},
    {"name": "Digitakt II", "max_input_channels": 2, "max_output_channels": 2, "default_samplerate": 48000.0},
    {"name": "Scarlett 2i2 USB", "max_input_channels": 2, "max_output_channels": 2, "default_samplerate": 44100.0},
]


def test_find_input_picks_the_digitakt_by_name():
    assert listen.find_input(DEVICES) == (2, "Digitakt II", 2, 48000.0)
    linux = [{"name": "HDA Intel PCH: ALC257 Analog (hw:0,0)", "max_input_channels": 2},
             {"name": "Digitakt II: USB Audio (hw:2,0)", "max_input_channels": 2, "default_samplerate": 48000}]
    assert listen.find_input(linux)[1] == "Digitakt II: USB Audio (hw:2,0)"


def test_find_input_override_by_name_or_index():
    assert listen.find_input(DEVICES, "scarlett")[1] == "Scarlett 2i2 USB"
    assert listen.find_input(DEVICES, "3")[0] == 3
    with pytest.raises(listen.ListenError, match="no audio input with index 1"):
        listen.find_input(DEVICES, "1")  # the speakers have no input
    with pytest.raises(listen.ListenError, match="no audio input matches 'motu'"):
        listen.find_input(DEVICES, "motu")


def test_find_input_never_falls_back_to_another_input():
    mics = [DEVICES[0], DEVICES[1]]
    with pytest.raises(listen.ListenError) as err:
        listen.find_input(mics)
    msg = str(err.value)
    assert "no Digitakt II audio input" in msg and "MacBook Pro Microphone" in msg
    assert "USB AUDIO/MIDI" in msg and "Microphone" in msg and "WHIPLASH_AUDIO_INPUT" in msg


@pytest.mark.parametrize("bars", [0, 9, -1, 1.5, "two", True])
def test_bad_bars_are_refused(bars):
    with pytest.raises(listen.ListenError, match="bars"):
        listen.check_bars(bars)
    assert listen.check_bars(None) == 2 and listen.check_bars(8) == 8


# ---- rail 1: ramps at once ----------------------------------------------------------------------

def test_user_ramps_stop_at_the_cap(fake):
    eng, port = fake
    pretend_playing(eng, P["techno"])
    params = ["filter_freq", "level", "pan"]
    n = 0
    for track in range(1, 17):
        for param in params:
            eng.ramp(track, 100, param=param, start=10, bars=4)
            n += 1
    assert n == engine.MAX_RAMPS == len(eng._ramps)
    before = len(port.messages)
    with pytest.raises(engine.WhiplashError, match="48 ramps are already running"):
        eng.ramp(1, 50, param="delay_send", start=0, bars=1)
    assert len(port.messages) == before and eng.rails["ramps_refused"] == 1
    out = eng.ramp(1, 20, param="filter_freq", start=90, bars=1)  # replacing a running one is fine
    assert out["replaced"] and len(eng._ramps) == engine.MAX_RAMPS


def test_scheduled_ramps_past_the_cap_do_not_start(fake):
    eng, port = fake
    pretend_playing(eng, P["techno"])
    for track in range(1, 17):
        for param in ("filter_freq", "level", "pan"):
            eng.ramp(track, 100, param=param, start=10, bars=4)
    with eng._lock:
        assert eng._start_ramp(mido, 1, 84, "delay_send", 0, 100, 96, "linear", owner="mix") is None
    assert eng.rails["ramps_refused"] == 1 and len(eng._ramps) == engine.MAX_RAMPS
    with eng._lock:
        status = eng.safety_status()
    assert status["ramps_running"] == 48 and status["max_ramps"] == 48 and status["ramps_refused"] == 1


def test_a_mix_ramp_past_the_cap_is_refused_before_anything_changes(fake):
    eng, port = fake
    pretend_playing(eng, P["techno"])
    for track in range(1, 17):
        eng.set_param(track, 100, param="level")
        eng.set_param(track, 64, param="pan")
        eng.ramp(track, 100, param="filter_freq", start=10, bars=4)
        eng.ramp(track, 90, param="delay_send", start=10, bars=4)  # 32 ramps running
    before = len(port.messages)
    with pytest.raises(engine.WhiplashError, match="more than 48 ramps"):
        eng.mix(levels={str(t): 80 for t in range(1, 17)}, pan={str(t): 30 for t in range(1, 17)}, bars=2)
    assert len(port.messages) == before and not eng._timed


# ---- rail 2: ramp CC rate ----------------------------------------------------------------------

def test_cc_budget_follows_the_tempo():
    eng, _ = make_engine()
    for bpm, budget in ((30, 16), (120, 16), (240, 10), (300, 8)):
        eng.bpm = bpm
        assert eng.cc_budget() == budget
        assert budget * engine.PPQN * bpm / 60.0 <= engine.CC_RATE_MAX  # never more than 1000 ramp CCs a second
    eng.shutdown()


def test_ramp_ccs_per_tick_are_capped_and_every_ramp_still_lands(fake):
    eng, port = fake
    pretend_playing(eng, P["techno"])
    eng.bpm = 300  # budget 8 per tick
    for track in range(1, 17):
        for param, to in (("filter_freq", 127), ("level", 120), ("pan", 0)):
            eng.ramp(track, to, param=param, start=1 if param != "pan" else 127, beats=0.25)  # 6 ticks: a flood
    base = len(ccs(port))
    per_tick = []
    for _ in range(40):
        n = len(ccs(port))
        eng._advance_ramps(mido)
        per_tick.append(len(ccs(port)) - n)
    assert max(per_tick) <= 8 and eng.rails["cc_deferred"] > 0
    assert not eng._ramps  # deferred ramps finished later instead of being dropped
    for track in range(1, 17):  # and each landed on its exact end value
        assert eng._cc_values[(track - 1, FILTER)] == 127
        assert eng._cc_values[(track - 1, LEVEL)] == 120
        assert eng._cc_values[(track - 1, 90)] == 0
    assert len(ccs(port)) - base <= 40 * 8
    assert_safe(port)


def test_no_change_under_the_budget(fake):
    """A single filter sweep (the demo's A4) sends exactly what it did before v0.7.0: one CC per value change."""
    eng, port = fake
    pretend_playing(eng, P["techno"])
    eng.ramp(4, 127, param="filter_freq", start=20, bars=1)
    for _ in range(engine.TICKS_PER_BAR):
        eng._advance_ramps(mido)
    values = [m.value for m in ccs(port, FILTER)]
    assert values[0] == 20 and values[-1] == 127 and values == sorted(set(values))
    assert eng.rails["cc_deferred"] == 0


# ---- rail 3: loudness guard --------------------------------------------------------------------

def test_guard_is_off_until_a_listen_hears_clipping(fake):
    eng, port = fake
    eng.ensure_port()
    eng.set_param(6, 90, param="level")
    assert eng.set_param(6, 120, param="level")["value"] == 120  # no listen yet
    eng.record_listen(CLEAN)
    assert eng.set_param(6, 127, param="level")["value"] == 127
    with eng._lock:
        assert eng.safety_status()["loudness_guard"] is False


@pytest.mark.parametrize("param", ["level", "track_level", "drive", "overdrive", "volume"])
def test_guard_refuses_increases_after_clipping(fake, param):
    eng, port = fake
    eng.ensure_port()
    eng.set_param(6, 90, param=param)
    eng.record_listen(CLIPPED)
    before = len(port.messages)
    with pytest.raises(engine.WhiplashError, match="loudness guard.*heard clipping.*force=true"):
        eng.set_param(6, 100, param=param)
    assert len(port.messages) == before and eng.rails["guard_refusals"] == 1
    assert eng.set_param(6, 70, param=param)["value"] == 70  # down is always fine
    assert "guard" not in eng.set_param(6, 70, param=param)  # so is the same value


def test_guard_refuses_an_unknown_base_and_raw_cc(fake):
    eng, port = fake
    eng.ensure_port()
    eng.record_listen(CLIPPED)
    with pytest.raises(engine.WhiplashError, match=r"track_level on track 3 \(unknown -> 60\)"):
        eng.set_param(3, 60, param="level")  # Whiplash never sent it: could be a raise
    with pytest.raises(engine.WhiplashError, match="overdrive"):
        eng.set_param(3, 60, cc=DRIVE)
    assert eng.set_param(3, 127, param="filter_freq")["value"] == 127  # not a loudness param
    assert eng.set_param(3, 127, param="reverb_send")["value"] == 127


def test_force_goes_past_the_guard_and_says_so(fake):
    eng, port = fake
    eng.ensure_port()
    eng.set_param(6, 90, param="level")
    eng.record_listen(CLIPPED)
    out = eng.set_param(6, 110, param="level", force=True)
    assert out["value"] == 110 and "loudness guard" in out["guard"] and eng.rails["guard_forced"] == 1
    assert ccs(port, LEVEL)[-1].value == 110
    with pytest.raises(engine.WhiplashError, match="force must be true or false"):
        eng.set_param(6, 120, param="level", force="maybe")


def test_guard_on_ramps(fake):
    eng, port = fake
    pretend_playing(eng, P["techno"])
    eng.set_param(6, 90, param="level")
    eng.record_listen(CLIPPED)
    with pytest.raises(engine.WhiplashError, match="loudness guard"):
        eng.ramp(6, 120, param="level", bars=2)
    with pytest.raises(engine.WhiplashError, match="loudness guard"):
        eng.ramp(6, 100, param="drive", start=0, bars=2)
    assert not eng._ramps
    assert eng.ramp(6, 40, param="level", bars=2)["to"] == 40  # a fade down is fine
    assert eng.ramp(6, 120, param="level", bars=2, force=True)["guard"]


def test_guard_on_mix_levels_but_not_pan(fake):
    eng, port = fake
    pretend_playing(eng, P["techno"])
    for t in (1, 6):
        eng.set_param(t, 100, param="level")
    eng.record_listen(CLIPPED)
    with pytest.raises(engine.WhiplashError, match="track 6"):
        eng.mix(levels={"1": 90, "6": 110})
    assert not eng._timed  # nothing scheduled, nothing sent
    out = eng.mix(levels={"1": 90, "6": 95}, pan={"hats": "left"})
    assert out["applies"] == "next bar" and "guard" not in out
    with pytest.raises(engine.WhiplashError, match="loudness guard"):
        eng.mix(preset="flat")  # flat = 100 everywhere: raises tracks Whiplash never set
    assert eng.mix(levels={"6": 110}, force=True)["guard"]


def test_a_clean_listen_lifts_the_guard(fake):
    eng, port = fake
    eng.ensure_port()
    eng.set_param(6, 90, param="level")
    eng.record_listen(CLIPPED)
    with pytest.raises(engine.WhiplashError):
        eng.set_param(6, 100, param="level")
    eng.record_listen(CLEAN)
    assert eng.set_param(6, 100, param="level")["value"] == 100


def test_status_shows_the_rails_and_the_last_listen(fake):
    eng, port = fake
    status = eng.status()
    assert status["listen"] is None
    assert status["safety"]["max_ramps"] == 48 and status["safety"]["cc_rate_max"] == 1000
    assert status["safety"]["loudness_guard"] is False
    eng.record_listen(CLIPPED)
    status = eng.status()
    assert status["safety"]["loudness_guard"] is True
    assert status["listen"]["clipping"] is True and status["listen"]["lufs_ish"] == -6.0
    assert status["listen"]["age_s"] >= 0 and "at" not in status["listen"]


def test_tools_pass_force(tool_engine):
    eng, port = tool_engine()
    call("whiplash_set_param", track=6, param="level", value=90)
    eng.record_listen(CLIPPED)
    out = call("whiplash_set_param", track=6, param="level", value=110)
    assert out["success"] is False and "loudness guard" in out["error"]
    out = call("whiplash_set_param", track=6, param="level", value=110, force=True)
    assert out["success"] is True and out["guard"]
    out = call("whiplash_mix", levels={"6": 120})
    assert out["success"] is False and "loudness guard" in out["error"]
    assert call("whiplash_mix", levels={"6": 120}, force=True)["success"] is True
    out = call("whiplash_ramp_param", track=6, param="level", to=127, bars=1)
    assert out["success"] is False  # nothing playing: refused before the guard, as before


def test_schemas_carry_listen_and_force():
    s = schemas.SCHEMAS
    for name in ("whiplash_set_param", "whiplash_ramp_param", "whiplash_mix"):
        assert s[name]["parameters"]["properties"]["force"]["type"] == "boolean"
    props = s["whiplash_listen"]["parameters"]["properties"]
    assert props["bars"]["maximum"] == listen.BARS_MAX == 8 and "device" in props
    d = s["whiplash_listen"]["description"]
    assert "never audio" in d and "USB AUDIO/MIDI" in d and "whiplash:digitakt" in d


def test_panic_and_the_allow_list_are_untouched(fake):
    eng, port = fake
    assert engine.ALLOWED_TYPES == {"note_on", "note_off", "control_change", "clock", "start", "stop", "continue"}
    for bad in (mido.Message("sysex", data=[1, 2]), mido.Message("program_change", program=3)):
        with pytest.raises(engine.WhiplashError):
            eng.send(bad)
    assert {0, 32, 24, 6, 38, 98, 99, 100, 101} <= ccmap.BLOCKED_CCS


# ---- virtual clock: the schedule itself, free of runner stalls ------------------------------------------------
# Wall-clock jitter bounds are local-only on CI (conftest.STRICT_TIMING). These pin what they stand for
# deterministically: on a virtual clock, where sleep advances time exactly, every clock tick and note goes out at
# its scheduled time, a queued tempo lands exactly on the switch bar, and neither an armed listen nor a saturated
# CC budget moves anything.

import threading  # noqa: E402
import time  # noqa: E402


class VirtualTime:
    """Stands in for the time module inside engine.py: perf_counter is virtual and sleep advances it exactly
    (pacing itself with a short real sleep so other threads get a turn). Everything else is the real module."""

    def __init__(self):
        self.t = 1000.0
        self.lock = threading.Lock()

    def perf_counter(self):
        with self.lock:
            return self.t

    def sleep(self, seconds):
        with self.lock:
            self.t += max(0.0, seconds)
        time.sleep(0.0002 if seconds > 0 else 0)

    def __getattr__(self, name):
        return getattr(time, name)


class VirtualPort:
    def __init__(self, clock):
        self.clock, self.sent = clock, []

    def send(self, msg):
        self.sent.append((self.clock.perf_counter(), msg))

    def close(self):
        pass


def _real_wait(cond, timeout=60.0):
    end = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < end, "virtual-clock run stalled"
        time.sleep(0.005)


def test_virtual_clock_schedule_is_exact_through_a_tempo_switch_with_a_listen_armed(monkeypatch):
    vt = VirtualTime()
    monkeypatch.setattr(engine, "time", vt)
    port = VirtualPort(vt)
    eng = engine.Engine(opener=lambda name: (port, "Fake", False))
    try:
        eng.arm_listen()  # the sequencer logs every note-on while armed
        eng.play(P["techno"], bpm=122)
        _real_wait(lambda: eng.bar >= 2)
        for track in range(1, 17):  # saturate the per-tick CC budget for a beat
            for param in ("filter_freq", "level", "pan"):
                eng.ramp(track, 127, param=param, start=0, beats=1)
        out = eng.play(P["techno"], bpm=126, bars=3)
        at = out["switch_at_bar"]
        _real_wait(lambda: not eng.playing())
        notes = eng.disarm_listen()
        bars = dict(eng.bar_log)
    finally:
        eng.shutdown()
    assert eng.rails["cc_deferred"] > 0  # the budget really was saturated
    clocks = [t for t, m in port.sent if m.type == "clock"]
    assert len(clocks) >= (at + 3) * engine.TICKS_PER_BAR - 1
    old, new = 60.0 / 122 / engine.PPQN, 60.0 / 126 / engine.PPQN
    switch_tick = at * engine.TICKS_PER_BAR
    gaps = [b - a for a, b in zip(clocks, clocks[1:])]
    assert max(abs(g - old) for g in gaps[:switch_tick]) < 1e-6  # every tick on time: no jitter at all
    assert max(abs(g - new) for g in gaps[switch_tick:]) < 1e-6  # the new tempo from exactly the switch bar
    assert abs(bars[at] - bars[at - 1] - 96 * old) < 1e-6 and abs(bars[at + 1] - bars[at] - 96 * new) < 1e-6
    # every note-on went out exactly on its step (techno: swing 50 here is not assumed; even steps only)
    checked = 0
    for t, ch, note, vel in notes:
        bar = max(b for b, start in bars.items() if start <= t + 1e-9)
        step_len = (bars[bar + 1] - bars[bar]) / 16 if bar + 1 in bars else 6 * (new if bar >= at else old)
        pos = (t - bars[bar]) / step_len
        if round(pos) % 2 == 0:
            assert abs(pos - round(pos)) < 1e-6, (bar, pos)
            checked += 1
    assert checked > 50
    assert all(m.type in engine.ALLOWED_TYPES for _, m in port.sent)


def test_listen_analysis_yields_the_gil_in_small_batches(monkeypatch):
    """The deterministic half of the listen jitter test: the analysis never runs long without yielding, so the
    sequencer thread can take the GIL back. Counted on 8 bars of noise (the largest listen at 120 BPM)."""
    np = pytest.importorskip("numpy")
    calls = []
    monkeypatch.setattr(listen, "_yield", lambda: calls.append(1))
    sr, secs = 48000, 16.0
    audio = np.random.default_rng(0).normal(0, 0.1, (int(secs * sr), 2))
    listen.analyse(np, audio, sr, 0.0, secs, [i * 2.0 for i in range(9)], [(0.0, 1, 60)], {1: "kick"})
    # at least one yield per ~0.25 s of audio processed by each stage
    assert len(calls) >= 4 * secs, len(calls)
