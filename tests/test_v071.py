"""v0.7.1 whiplash_scan_kit: packaging, the refusals (no numpy needed), the classifier on synthetic numpy sounds,
and the scan end to end through a fake input stream that plays a sound per MIDI channel when the port sends a note.
Fake ports and fake audio only: nothing here says how the Digitakt II sounds. The numpy tests skip without numpy;
sounddevice is never imported."""
import json
import threading
import time
import tomllib
from pathlib import Path

import mido
import pytest
import yaml

import whiplash
from whiplash import ccmap, engine, listen, patterns, scan, schemas, tools
from test_whiplash import FakePort, call, make_engine, tool_engine  # noqa: F401  (fixture)
from test_live import wait_bar

ROOT = Path(whiplash.__path__[0])
P = patterns.PATTERNS
SR = 48000


def assert_notes_only(port):
    """The scan sends note-on/off and nothing else: no CC (so no slot or sample change), no clock or Start."""
    for m in port.messages:
        assert m.type in ("note_on", "note_off"), m
        assert m.note == scan.NOTE


# ---- packaging and refusals (no numpy) ------------------------------------------------------------------------

def test_changelog_keeps_0_7_1():  # v0.8.0 pins the version number in test_v080.py
    releases = [h for h in (ROOT / "CHANGELOG.md").read_text().split("\n## ")[1:] if not h.startswith("Unreleased")]
    assert any(r.startswith("0.7.1") for r in releases)


def test_scan_kit_is_listed_after_listen_everywhere():
    for manifest in (yaml.safe_load(open(ROOT / "plugin.yaml"))["provides_tools"],
                     yaml.safe_load(open(ROOT / "docs" / "catalog-entry.yaml"))["capabilities"]["provides_tools"],
                     list(schemas.SCHEMAS), list(tools.HANDLERS)):
        assert manifest.index("whiplash_scan_kit") == manifest.index("whiplash_listen") + 1
    d = schemas.SCHEMAS["whiplash_scan_kit"]["description"]
    assert "Never applies" in d and "whiplash_label_tracks" in d and "their yes" in d
    skill = (ROOT / "skills" / "digitakt" / "SKILL.md").read_text()
    assert "whiplash_scan_kit" in skill and "apply_with" in skill
    assert "whiplash_scan_kit" in (ROOT / "README.md").read_text()


@pytest.mark.parametrize("bad", ["1", 5, [0], [17], [1.5], [True], ["x"], {"1": 2}])
def test_bad_tracks_are_refused(bad):
    with pytest.raises(scan.ScanError, match="track"):
        scan.check_tracks(bad)


def test_tracks_default_to_all_sixteen_in_order():
    assert scan.check_tracks(None) == list(range(1, 17))
    assert scan.check_tracks([9, "3", 3.0, 9]) == [9, 3]


@pytest.mark.parametrize("transport,hint", [(True, "MIDI Start"), (False, "clock only")])
def test_refused_while_a_beat_plays_and_the_beat_is_untouched(transport, hint):
    eng, port = make_engine()
    try:
        eng.play(P["techno"], bpm=240, send_transport=transport)
        wait_bar(eng, 1)
        before = eng.status()["bar"]
        with pytest.raises(scan.ScanError, match=f"needs the beat stopped.*{hint}.*whiplash_stop"):
            scan.scan(eng, backend=object())  # refused before the audio backend is even looked at
        assert eng.playing() and eng.status()["bar"] >= before
        assert eng.last_scan is None
    finally:
        eng.shutdown()


def test_the_tool_refuses_cleanly_while_playing(tool_engine):  # noqa: F811
    eng, port = tool_engine()
    call("whiplash_play_pattern", genre="techno", bpm=240)
    wait_bar(eng, 1)
    out = call("whiplash_scan_kit")
    assert out["success"] is False and "needs the beat stopped" in out["error"]
    assert eng.playing()
    bad = call("whiplash_scan_kit", tracks=[0])
    assert bad["success"] is False and "track" in bad["error"]


def test_scan_without_numpy_gives_the_install_hint(tmp_path):
    import subprocess
    import sys
    code = f"""
import sys, json, importlib.abc
class Block(importlib.abc.MetaPathFinder):
    def find_spec(self, name, path, target=None):
        if name.split('.')[0] in ('numpy', 'sounddevice'):
            raise ImportError('blocked ' + name)
sys.meta_path.insert(0, Block())
sys.path.insert(0, {str(ROOT.parent)!r})
from whiplash import tools
print(json.dumps(json.loads(tools.HANDLERS['whiplash_scan_kit']({{}}))))
"""
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60, cwd=tmp_path)
    assert out.returncode == 0, out.stderr
    result = json.loads(out.stdout.strip().splitlines()[-1])
    assert result["success"] is False and "numpy" in result["error"] and "pip install" in result["error"]


def test_scan_notes_stop_after_a_stop(tmp_path):
    eng, port = make_engine()
    try:
        _, _, _, stops = eng.scan_state()
        eng.ensure_port()
        eng.scan_note(3, True, stops)
        assert port.count("note_on", channel=2, note=60, velocity=scan.VELOCITY) == 1
        eng.stop()  # whiplash_stop mid-scan: its panic ends the note, and the scan can't send another
        assert port.count("note_off", channel=2, note=60) == 1
        with pytest.raises(engine.WhiplashError, match="kit scan stopped"):
            eng.scan_note(4, True, stops)
        assert port.count("note_on", channel=3) == 0
    finally:
        eng.shutdown()


# ---- synthetic sounds (numpy) ---------------------------------------------------------------------------------

def _np():
    return pytest.importorskip("numpy")


def sounds(window=0.9):
    np = _np()
    rng = np.random.default_rng(1)

    def t(s):
        return np.arange(int(s * SR)) / SR

    def band(noise, lo, hi):
        X = np.fft.rfft(noise)
        f = np.fft.rfftfreq(len(noise), 1 / SR)
        X[(f < lo) | (f > hi)] = 0
        return np.fft.irfft(X, len(noise))

    def decay(s, tau):
        return np.exp(-t(s) / tau)

    def fit(x):
        y = np.zeros(int(window * SR))
        y[:min(len(x), len(y))] = x[:len(y)]
        return y

    def saw(f, s):
        return 2 * ((t(s) * f) % 1) - 1

    sweep = np.cumsum(50 + 100 * np.exp(-t(0.4) / 0.03)) / SR
    return {
        "kick": fit(0.8 * np.sin(2 * np.pi * sweep) * decay(0.4, 0.07)),
        "snare/clap": fit(0.2 * band(rng.normal(0, 1, int(0.3 * SR)), 800, 6000) * decay(0.3, 0.05)
                          + 0.2 * np.sin(2 * np.pi * 190 * t(0.3)) * decay(0.3, 0.02)),
        "hat": fit(0.4 * band(rng.normal(0, 1, int(0.1 * SR)), 6000, 20000) * decay(0.1, 0.012)),
        "open hat": fit(0.3 * band(rng.normal(0, 1, int(0.6 * SR)), 6000, 20000) * decay(0.6, 0.12)),
        "perc": fit(0.6 * np.sin(2 * np.pi * 420 * t(0.3)) * decay(0.3, 0.05)),
        "bass": 0.5 * saw(55, window) * np.minimum(1, t(window) / 0.005),
        "pad/chord": 0.3 * saw(220, window) * np.minimum(1, t(window) / 0.2),
        "lead/stab": 0.3 * np.sign(np.sin(2 * np.pi * 440 * t(window))) * np.minimum(1, t(window) / 0.003),
        "stab": fit(0.4 * saw(330, 0.5) * decay(0.5, 0.15)),
        "fx": 0.2 * band(rng.normal(0, 1, int(window * SR)), 300, 8000) * np.minimum(1, t(window) / 0.3),
        "silent": np.zeros(int(window * SR)),
    }


EXPECTED = {"kick": ("kick", "kick"), "snare/clap": ("snare/clap", "snare"), "hat": ("hat", "closed hat"),
            "open hat": ("hat", "open hat"), "perc": ("perc", "perc"), "bass": ("bass", "bass"),
            "pad/chord": ("pad/chord", "pad"), "lead/stab": ("lead/stab", "lead"), "stab": ("lead/stab", "stab"),
            "fx": ("fx", "fx")}


@pytest.mark.parametrize("name", list(EXPECTED))
def test_each_label_class_from_a_synthetic_hit(name):
    np = _np()
    sound = sounds()[name]
    stereo = np.stack([sound, sound], axis=1)
    f = scan.hit_features(np, stereo, SR)
    out = scan.classify(f)
    label, role = EXPECTED[name]
    assert out["label"] == label, (f, scan.scores(f))
    assert out.get("role", out["label"]) == role
    assert out["confidence"] >= 0.5, (f, scan.scores(f))
    assert not f["extra_hits"]


def test_silence_and_a_whisper_are_silent():
    np = _np()
    for audio in (np.zeros((SR, 2)), np.full((SR, 2), 1e-4)):
        f = scan.hit_features(np, audio, SR)
        assert f["silent"] is True and scan.classify(f)["label"] == "silent"


def test_features_describe_the_sound():
    np = _np()
    s = sounds()
    kick = scan.hit_features(np, s["kick"], SR)
    hat = scan.hit_features(np, s["hat"], SR)
    bass = scan.hit_features(np, s["bass"], SR)
    noise = scan.hit_features(np, s["fx"], SR)
    assert kick["low_pct"] > 90 and kick["centroid_hz"] < 150 and 80 < kick["decay_ms"] < 400
    assert hat["centroid_hz"] > 8000 and hat["pitched"] < 0.3 and hat["decay_ms"] < 80
    assert bass["sustained"] and bass["pitched"] > 0.7 and bass["f0_hz"] == pytest.approx(55, abs=3)
    assert noise["pitched"] < 0.3 and noise["attack_ms"] > 100


def test_a_second_hit_inside_the_window_is_noticed():
    np = _np()
    s = sounds()
    two = s["kick"].copy()
    two[int(0.5 * SR):] += s["kick"][:len(two) - int(0.5 * SR)]
    assert scan.hit_features(np, two, SR)["extra_hits"] is True


def _analyse_sequence(names, window=0.9, before=None, fade_out=True):
    """Lay the named sounds end to end like a scan would capture them -> analyse()'s result."""
    np = _np()
    s = sounds(window)
    lead = int(scan.LEAD * SR)
    audio = np.zeros(lead + len(names) * int(window * SR) + SR // 2)
    if before is not None:
        audio[:len(before)] += before
    hits = []
    n = int((window - 0.08) * SR) if fade_out else int(window * SR)
    fade = np.minimum(1.0, (n - np.arange(n)) / (0.02 * SR)) if fade_out else 1.0  # the scan waits for quiet
    for i, name in enumerate(names):
        at = scan.LEAD + i * window
        k = int(round((at + 0.006) * SR))  # 6 ms of round trip
        audio[k:k + n] += s[name][:n] * fade
        hits.append((i + 1, at))
    times = [t for _, t in hits] + [scan.LEAD + len(names) * window]
    return scan.analyse(np, np.stack([audio, audio], axis=1), SR, 0.0, hits, times, window,
                        lead=(0.05, scan.LEAD - 0.01))


def test_a_whole_kit_proposal_and_apply_with():
    names = ["kick", "snare/clap", "hat", "open hat", "perc", "bass", "pad/chord", "lead/stab", "fx", "silent"]
    out = _analyse_sequence(names)
    got = {int(t): p["label"] for t, p in out["proposed"].items()}
    assert got == {i + 1: EXPECTED.get(n, (n,))[0] for i, n in enumerate(names)}
    apply = out["apply_with"]
    assert apply["tool"] == "whiplash_label_tracks"
    assert apply["tracks"] == {"1": "kick", "2": "snare", "3": "closed hat", "4": "open hat", "5": "perc",
                               "6": "bass", "7": "pad", "8": "lead", "9": "fx"}  # silent track 10 left out
    from whiplash import kitmap
    assert all(kitmap.classify(v) == v for v in apply["tracks"].values())  # every one is a kit-map role as is
    assert any("[10]" in n and "silent" in n for n in out["notes"])
    assert "unexpected_audio" not in out and "flags" not in out
    assert out["features_keys"] == list(scan.FEATURES) and len(out["features"]["1"]) == len(scan.FEATURES)


def test_sound_before_the_first_note_flags_the_units_own_pattern():
    np = _np()
    s = sounds()
    groove = np.zeros(int(scan.LEAD * SR))
    groove[int(0.1 * SR):int(0.1 * SR) + len(s["hat"])] += s["hat"][:len(groove) - int(0.1 * SR)]
    out = _analyse_sequence(["kick", "hat"], before=groove)
    assert out["unexpected_audio"] is True
    assert any("unit's own pattern" in n and "v0.4" in n for n in out["notes"])


def test_stray_hits_during_solos_lower_the_confidence_and_flag_the_pattern():
    np = _np()
    s = sounds()
    clean = _analyse_sequence(["kick", "perc", "bass"])
    window = 0.9
    lead = int(scan.LEAD * SR)
    extra = np.zeros(lead + 3 * int(window * SR) + SR // 2)
    for i in range(2):  # a hat 0.5 s into the kick's and the perc's windows, which no scan note played
        k = lead + i * int(window * SR) + int(0.5 * SR)
        extra[k:k + len(s["hat"])] += 2.0 * s["hat"]
    names = ["kick", "perc", "bass"]
    out = _analyse_sequence(names, before=extra)
    assert out["unexpected_audio"] is True
    assert out["flags"]["1"] == ["other_hits"] and out["flags"]["2"] == ["other_hits"]
    for t in ("1", "2"):
        assert out["proposed"][t]["confidence"] < clean["proposed"][t]["confidence"]


def test_a_tail_ringing_into_the_next_hit_is_a_tail_not_the_pattern():
    out = _analyse_sequence(["bass", "kick"], fade_out=False)  # TAIL_WAIT ran out: the bass still rings
    assert out["flags"]["2"] == ["tail_overlap"]
    assert "unexpected_audio" not in out
    assert any("tail_overlap" in n for n in out["notes"])


def test_analysis_yields_between_tracks(monkeypatch):
    calls = []
    monkeypatch.setattr(scan, "_yield", lambda: calls.append(1))
    _analyse_sequence(["kick", "hat", "bass", "pad/chord"])
    assert len(calls) >= 4


# ---- end to end through a fake input --------------------------------------------------------------------------

class SoundPort(FakePort):
    """Records when each note-on went out, per channel."""

    def __init__(self, fail_after=None):
        super().__init__(fail_after)
        self.note_times = []

    def send(self, msg):
        now = time.perf_counter()
        super().send(msg)
        if msg.type == "note_on" and msg.velocity:
            self.note_times.append((now, msg.channel))


class TimeInfo:
    def __init__(self, adc):
        self.inputBufferAdcTime = adc


class KitStream:
    """sounddevice.InputStream look-alike: real-time blocks from its own thread, each holding the kit's sound for
    every note-on the port sent on that channel, `latency` later (plus `ambient`, the unit's own pattern)."""

    def __init__(self, backend, device, channels, samplerate, dtype, blocksize, callback):
        self.b, self.sr, self.channels, self.cb, self.n = backend, int(samplerate), channels, callback, blocksize
        self.stop_event, self.thread, self.latency = threading.Event(), None, 0.003
        backend.opened.append(self)

    @property
    def time(self):
        return time.perf_counter()

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        np = _np()
        t = time.perf_counter()
        dur = self.n / self.sr
        sent = 0
        while not self.stop_event.is_set():
            if self.b.stall_after is not None and sent >= self.b.stall_after:
                time.sleep(0.01)
                continue
            while time.perf_counter() < t + dur and not self.stop_event.is_set():
                time.sleep(0.002)
            block = np.zeros(self.n)
            events = [(at + self.b.latency, self.b.kit.get(ch + 1)) for at, ch in list(self.b.port.note_times)]
            if self.b.ambient is not None:
                events += [(t0 + k * 0.25, self.b.ambient) for t0 in [self.b.t0] for k in range(400)]
            for start, sound in events:
                if sound is None or not (start < t + dur and start + len(sound) / self.sr > t):
                    continue
                i = int(round((start - t) * self.sr))
                a, b = max(0, i), min(self.n, i + len(sound))
                if a < b:
                    block[a:b] += sound[a - i:b - i]
            self.cb(np.stack([block] * self.channels, axis=1).astype(np.float32), self.n, TimeInfo(t), None)
            sent += 1
            t += dur

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)

    def close(self):
        pass


class KitBackend:
    def __init__(self, port, kit, stall_after=None, ambient=None, latency=0.008):
        self.port, self.kit, self.stall_after, self.ambient, self.latency = port, kit, stall_after, ambient, latency
        self.t0 = time.perf_counter()
        self.devices = [{"name": "MacBook Pro Microphone", "max_input_channels": 1, "default_samplerate": 48000.0},
                        {"name": "Digitakt II", "max_input_channels": 2, "default_samplerate": 48000.0}]
        self.opened = []

    def query_devices(self):
        return self.devices

    def InputStream(self, **kw):  # noqa: N802  (sounddevice's name)
        return KitStream(self, **kw)


WINDOW = 0.6


@pytest.fixture
def kit():
    s = sounds(WINDOW)
    # pad and fx ring past the window on purpose: the scan waits for them to fade (TAIL_WAIT) before the next note
    return {1: s["kick"], 2: s["snare/clap"], 3: s["hat"], 5: s["bass"][:int(0.4 * SR)] * _fade(0.4),
            6: s["perc"], 9: s["lead/stab"][:int(0.5 * SR)] * _fade(0.5)}


def _fade(seconds):
    np = _np()
    n = int(seconds * SR)
    return np.minimum(1.0, (n - np.arange(n)) / (0.02 * SR))


@pytest.fixture
def stopped():
    port = SoundPort()
    eng, _ = make_engine(port)
    yield eng, port
    eng.shutdown()


def test_scan_end_to_end_proposes_and_never_applies(stopped, kit):
    eng, port = stopped
    eng.label_tracks(tracks={"5": "dirty bass"})
    before = eng.kit()
    tracks = [1, 2, 3, 4, 5, 6, 9]
    out = scan.scan(eng, tracks=tracks, backend=KitBackend(port, kit), window=WINDOW)
    assert out["device"] == "Digitakt II" and out["tracks_scanned"] == tracks
    labels = {int(t): p["label"] for t, p in out["proposed"].items()}
    assert labels == {1: "kick", 2: "snare/clap", 3: "hat", 4: "silent", 5: "bass", 6: "perc", 9: "lead/stab"}, out
    assert out["applied"] is False and "only after they say yes" in out["confirm"]
    assert out["current_labels"] == {"5": "dirty bass"}
    assert "channel_note" in out  # track 9 is on channel 9
    assert eng.kit() == before  # NEVER applied: the kit map is exactly what the user said
    assert eng.last_scan["applied"] is False and eng.last_scan["proposed"] == out["proposed"]
    # one note 60 per track, on its own channel, alone, in order, spaced by at least the window; nothing else
    assert_notes_only(port)
    ons = [(t, ch) for t, ch in port.note_times]
    assert [ch + 1 for _, ch in ons] == tracks
    assert all(b[0] - a[0] >= WINDOW - 0.005 for a, b in zip(ons, ons[1:]))
    assert port.count("note_off") == len(tracks) and not eng._sounding
    assert not eng.playing() and len(json.dumps(out)) < 4000


def test_applying_is_a_separate_explicit_call(tool_engine, monkeypatch, kit):  # noqa: F811
    port = SoundPort()
    eng, _ = make_engine(port)
    monkeypatch.setattr(tools, "ENGINE", eng)
    try:
        monkeypatch.setattr(listen, "sounddevice_or_error", lambda: KitBackend(port, kit))
        monkeypatch.setattr(scan, "WINDOW", WINDOW)
        out = call("whiplash_scan_kit", tracks=[1, 3])
        assert out["success"] is True and out["applied"] is False
        assert call("whiplash_status")["kit"]["tracks"] == {}  # nothing applied by the scan
        applied = call("whiplash_label_tracks", tracks=out["apply_with"]["tracks"])  # the user said yes
        assert applied["success"] is True
        assert call("whiplash_status")["kit"]["tracks"] == {"1": {"role": "kick", "label": "kick"},
                                                             "3": {"role": "closed hat", "label": "closed hat"}}
    finally:
        eng.shutdown()


def test_muted_tracks_are_skipped(stopped, kit):
    eng, port = stopped
    eng.muted.add(2)  # a Whiplash mute (a beat stopped mid-arrangement keeps none, but respect any that exist)
    out = scan.scan(eng, tracks=[1, 2], backend=KitBackend(port, kit), window=WINDOW)
    assert out["tracks_scanned"] == [1] and out["skipped_muted"] == [2]
    assert port.count("note_on", channel=1) == 0


def test_the_units_own_pattern_playing_refuses_before_any_note(stopped, kit):
    eng, port = stopped
    backend = KitBackend(port, kit, ambient=kit[3])  # a hat every 250 ms from the unit's own sequencer
    with pytest.raises(scan.ScanError, match="already making sound.*own pattern.*v0.4.*Nothing was sent"):
        scan.scan(eng, backend=backend, window=WINDOW)
    assert port.count("note_on") == 0


def test_audio_unplugged_mid_scan_errors_cleanly(stopped, kit):
    eng, port = stopped
    backend = KitBackend(port, kit, stall_after=int((scan.LEAD + 0.9) * SR / listen.BLOCK))
    with pytest.raises(scan.ScanError, match="stopped delivering audio mid-scan"):
        scan.scan(eng, backend=backend, window=WINDOW)
    assert 1 <= port.count("note_on") < 16
    assert port.count("note_on") == port.count("note_off") and not eng._sounding  # nothing left hanging
    assert eng.last_scan is None
    assert not listen._BUSY.locked()


def test_midi_unplugged_mid_scan_errors_cleanly(kit):
    port = SoundPort(fail_after=3)  # note-on, note-off, note-on, then the cable is gone
    eng, _ = make_engine(port)
    try:
        with pytest.raises(scan.ScanError, match="MIDI port failed mid-scan"):
            scan.scan(eng, backend=KitBackend(port, kit), window=WINDOW)
        assert eng.port_lost == "Fake" and not listen._BUSY.locked()
    finally:
        port.fail_after = None
        eng.shutdown()


def test_stop_mid_scan_aborts_it(stopped, kit):
    eng, port = stopped
    result = {}

    def run():
        try:
            scan.scan(eng, backend=KitBackend(port, kit), window=WINDOW)
        except scan.ScanError as exc:
            result["error"] = str(exc)

    th = threading.Thread(target=run)
    th.start()
    deadline = time.monotonic() + 10
    while port.count("note_on") < 2 and time.monotonic() < deadline:
        time.sleep(0.01)
    eng.stop()
    th.join(timeout=20)
    assert "kit scan stopped" in result.get("error", "")
    assert port.count("note_on") <= 3 and not eng._sounding


def test_no_digitakt_on_midi_refuses(kit):
    port = SoundPort()
    eng, _ = make_engine(port, virtual=True)
    try:
        with pytest.raises(scan.ScanError, match="virtual port"):
            scan.scan(eng, backend=KitBackend(port, kit), window=WINDOW)
        assert port.count("note_on") == 0
    finally:
        eng.shutdown()


def test_no_digitakt_audio_input_refuses_without_a_note(stopped, kit):
    eng, port = stopped
    backend = KitBackend(port, kit)
    backend.devices = [{"name": "MacBook Pro Microphone", "max_input_channels": 1}]
    with pytest.raises(listen.ListenError, match="no Digitakt II audio input"):
        scan.scan(eng, backend=backend, window=WINDOW)
    assert backend.opened == [] and port.count("note_on") == 0


def test_one_listen_or_scan_at_a_time(stopped, kit):
    eng, port = stopped
    assert listen._BUSY.acquire(blocking=False)
    try:
        with pytest.raises(scan.ScanError, match="already running"):
            scan.scan(eng, backend=KitBackend(port, kit), window=WINDOW)
    finally:
        listen._BUSY.release()


def test_a_scan_leaves_the_next_beat_alone(stopped, kit):
    """After a scan the beat starts exactly as before: the clock-jitter tests and Part A are unaffected because
    the scan only ever runs with the sequencer stopped and never touches its state."""
    eng, port = stopped
    scan.scan(eng, tracks=[1], backend=KitBackend(port, kit), window=WINDOW)
    n = len(port.messages)
    eng.play(P["techno"], bpm=240)
    wait_bar(eng, 1)
    eng.stop()
    later = port.messages[n:]
    assert later[0].type == "start"  # no stray panic or note before the new run's Start
    for m in later:
        assert m.type in engine.ALLOWED_TYPES
        if m.type == "control_change":
            assert m.control not in ccmap.BLOCKED_CCS
    with pytest.raises(engine.WhiplashError):
        eng.send(mido.Message("sysex", data=[1]))
    with pytest.raises(engine.WhiplashError):
        eng.send(mido.Message("program_change", program=1))
