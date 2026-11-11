"""v0.7.0 whiplash_listen with synthetic audio: numpy-made kicks, hats and sines, analysed directly and through a
fake input stream against a running engine. Skips cleanly without numpy. sounddevice is never imported: every
capture goes through a fake backend, so CI needs no audio device. Nothing here says how the Digitakt II sounds."""
import json
import threading
import time

import pytest

np = pytest.importorskip("numpy")

from whiplash import ccmap, engine, listen, patterns, tools  # noqa: E402
from test_whiplash import FakePort, call, make_engine  # noqa: E402
from test_live import wait_bar  # noqa: E402
from test_v051 import _jitter  # noqa: E402

SR = 48000
P = patterns.PATTERNS
BAR = engine.TICKS_PER_BAR


# ---- synthetic audio --------------------------------------------------------------------------------

def kick(amp=0.6):
    t = np.arange(int(0.2 * SR)) / SR
    fade = np.minimum(1.0, (t[-1] - t) / 0.03)  # no click where the sample ends
    return amp * np.sin(2 * np.pi * 55 * t) * np.exp(-t / 0.06) * fade


def hat(amp=0.2, seed=0):
    n = int(0.04 * SR)
    noise = np.random.default_rng(seed).normal(0, amp, n) * np.exp(-np.arange(n) / SR / 0.01)
    return np.diff(noise, prepend=0.0)


def place(buf, sound, at):
    i = int(round(at * SR))
    if 0 <= i < len(buf):
        buf[i:i + len(sound)] += sound[:len(buf) - i]


def beat(bpm=120, bars=2, latency=0.008, swing=50, kicks=True, hats=True, bass=0.0, render_hats=True):
    """A kick on every beat (track 1), a hat on every off 16th (track 4), optional sustained 55 Hz bass.
    -> (stereo audio, sent [(time, track, note)], grid, seconds); window starts at time 0."""
    bar = 240.0 / bpm
    secs = bars * bar
    n = int((secs + listen.LATENCY_MARGIN) * SR)
    x = np.zeros(n)
    sent = []
    step = bar / 16
    delay = (swing / 100.0 - 0.5) * 2 * step
    for b in range(bars):
        for s in range(16):
            at = b * bar + s * step
            if kicks and s % 4 == 0:
                sent.append((at, 1, 60))
                place(x, kick(), at + latency)
            if hats and s % 2:
                at += delay
                sent.append((at, 4, 60))
                if render_hats:
                    place(x, hat(seed=b * 16 + s), at + latency)
    if bass:
        t = np.arange(n) / SR
        x += bass * np.sin(2 * np.pi * 55 * t)
    return np.stack([x, x], axis=1), sent, [i * bar for i in range(bars + 1)], secs


ROLES = {1: "kick", 4: "closed_hat"}


def analyse(audio, sent=(), grid=None, secs=None, roles=ROLES):
    secs = secs if secs is not None else len(audio) / SR
    return listen.analyse(np, audio, SR, 0.0, secs, grid, sent, roles)


# ---- loudness, peak, clipping, bands ------------------------------------------------------------------

def sine(freq, amp=1.0, seconds=2.0, channels=(1, 1)):
    t = np.arange(int(seconds * SR)) / SR
    s = amp * np.sin(2 * np.pi * freq * t)
    return np.stack([s * c for c in channels], axis=1)


def test_lufs_ish_matches_the_bs1770_reference_points():
    # BS.1770: a 0 dBFS 997 Hz sine in one channel reads -3.01 LKFS; in both, 0.
    assert analyse(sine(997, channels=(1, 0)))["loudness"]["lufs_ish"] == pytest.approx(-3.0, abs=0.3)
    assert analyse(sine(997))["loudness"]["lufs_ish"] == pytest.approx(0.0, abs=0.3)
    assert analyse(sine(997, amp=0.1))["loudness"]["lufs_ish"] == pytest.approx(-20.0, abs=0.3)
    # K-weighting: a 40 Hz sine reads quieter than a 1 kHz one at the same level, a 6 kHz one louder
    low = analyse(sine(40, amp=0.1))["loudness"]["lufs_ish"]
    high = analyse(sine(6000, amp=0.1))["loudness"]["lufs_ish"]
    assert low < -20.5 and high > -19.5


def test_gating_ignores_silence():
    # Ungated, a second of -20 LUFS and a second of silence reads -23; the gates drop the silent blocks (the
    # blocks straddling the edge still count, as on a BS.1770 meter).
    audio = np.concatenate([sine(997, amp=0.1, seconds=1.0), np.zeros((SR, 2))])
    assert analyse(audio)["loudness"]["lufs_ish"] == pytest.approx(-20.0, abs=1.0)
    assert analyse(audio)["loudness"]["lufs_ish"] > -21.5


def test_peak_and_clipping():
    out = analyse(sine(220, amp=0.5))
    assert out["loudness"]["peak_dbfs"] == pytest.approx(-6.0, abs=0.1)
    assert out["loudness"]["clipping"] is False and out["loudness"]["headroom_db"] == pytest.approx(6.0, abs=0.1)
    hot = np.clip(sine(220, amp=1.4), -1.0, 1.0)
    out = analyse(hot)
    assert out["loudness"]["clipping"] is True and out["loudness"]["clipped_samples"] > 1000
    assert any("clipping" in n and "force=true" in n for n in out["notes"])
    near = analyse(sine(220, amp=0.95))
    assert near["loudness"]["clipping"] is False and any("headroom" in n for n in near["notes"])


@pytest.mark.parametrize("freq,band", [(60, "low"), (300, "low_mid"), (2000, "mid"), (8000, "high")])
def test_band_balance(freq, band):
    bands = analyse(sine(freq, amp=0.3))["bands"]
    assert bands[band]["pct"] > 90, bands
    assert bands[band]["db"] > -0.5
    assert sum(b["pct"] for b in bands.values()) == pytest.approx(100, abs=0.5)


def test_silence_flag_and_its_note():
    out = analyse(np.zeros((SR * 2, 2)), sent=[(0.1, 1, 60)])
    assert out["silent"] is True and out["loudness"]["lufs_ish"] is None and out["bands"] is None
    assert any("USB OUT = MAIN" in n for n in out["notes"])
    assert analyse(np.full((SR, 2), 1e-4))["silent"] is True  # -80 dBFS hiss is silence
    assert analyse(sine(440, amp=0.01))["silent"] is False  # -40 dBFS is not


# ---- timing ----------------------------------------------------------------------------------------

@pytest.mark.parametrize("latency", [0.004, 0.012, 0.025])
def test_kick_offsets_measure_the_round_trip(latency):
    audio, sent, grid, secs = beat(latency=latency)
    out = analyse(audio, sent, grid, secs)
    k = out["kick"]
    assert k["sent"] == 8 and k["heard"] == 8 and k["missed"] == 0
    assert k["median_offset_ms"] == pytest.approx(latency * 1000, abs=1.5)
    assert k["spread_ms"] <= 2.0 and len(k["offsets_ms"]) == 8


def test_kick_timing_spread_shows_jitter():
    audio, sent, grid, secs = beat(kicks=False, hats=False)
    late = [0.008, 0.008, 0.030, 0.008, 0.008, 0.008, 0.008, 0.008]
    for i, extra in enumerate(late):
        at = i * 0.5
        sent.append((at, 1, 60))
        place(audio[:, 0], kick(), at + extra)
        place(audio[:, 1], kick(), at + extra)
    k = analyse(audio, sorted(sent), grid, secs)["kick"]
    assert k["median_offset_ms"] == pytest.approx(8, abs=1.5) and k["spread_ms"] == pytest.approx(22, abs=3)


def test_onsets_on_a_straight_grid():
    audio, sent, grid, secs = beat(latency=0.010)
    ons = analyse(audio, sent, grid, secs)["onsets"]
    assert ons["count"] == 24 and ons["per_bar"] == 12.0  # 4 kicks + 8 hats a bar
    assert ons["median_abs_offset_ms"] <= 2.0 and ons["on_grid_pct"] == 100
    assert ons["latency_corrected_ms"] == pytest.approx(10, abs=1.5)
    assert abs(ons["offbeat_delay_ms"]) <= 2.0 and ons["swing_estimate"] == 50


@pytest.mark.parametrize("swing", [58, 66, 70])
def test_swing_is_noticed(swing):
    audio, sent, grid, secs = beat(swing=swing)
    ons = analyse(audio, sent, grid, secs)["onsets"]
    step_ms = 125.0
    assert ons["offbeat_delay_ms"] == pytest.approx((swing / 100 - 0.5) * 2 * step_ms, abs=2.0)
    assert ons["swing_estimate"] == pytest.approx(swing, abs=2)
    assert ons["on_grid_pct"] < 100


# ---- low end, tracks, unexpected audio ---------------------------------------------------------------

def test_bass_masking_the_kick():
    clean = analyse(*beat()[:3], secs=beat()[3])
    assert clean["low_end"]["masking"] is False and clean["low_end"]["kick_over_rest_db"] > 6
    audio, sent, grid, secs = beat(bass=0.5)
    muddy = analyse(audio, sent, grid, secs)
    assert muddy["low_end"]["masking"] is True and muddy["low_end"]["kick_over_rest_db"] < 3
    assert any("masking the kick" in n for n in muddy["notes"])


def test_a_track_that_sent_notes_but_was_not_heard():
    audio, sent, grid, secs = beat(render_hats=False)
    out = analyse(audio, sent, grid, secs)
    assert out["tracks"]["4"]["seems_silent"] is True and out["tracks"]["4"]["heard"] == 0
    assert out["tracks"]["1"]["seems_silent"] is False and out["tracks"]["1"]["heard"] == 8
    assert any("[4]" in n and "nothing was heard" in n for n in out["notes"])
    heard = analyse(*beat()[:3], secs=beat()[3])["tracks"]
    assert heard["4"]["seems_silent"] is False and heard["4"]["heard"] == 16


def test_audio_while_whiplash_sent_nothing():
    audio, _, grid, secs = beat()
    out = analyse(audio, [], grid, secs)
    assert out["unexpected_audio"] is True and out["kick"] is None and out["tracks"] is None
    assert any("unit's own pattern" in n for n in out["notes"])


def test_result_is_compact_and_holds_no_audio():
    audio, sent, grid, secs = beat(bars=8, bpm=120)
    out = analyse(audio, sent, grid, secs)
    text = json.dumps(out)
    assert len(text) < 3000

    def longest(node):
        if isinstance(node, dict):
            return max([longest(v) for v in node.values()] or [0])
        if isinstance(node, list):
            return max([len(node)] + [longest(v) for v in node])
        return 0
    assert longest(out) <= listen.OFFSETS_SHOWN


# ---- capture through a fake input stream, against a running engine -------------------------------------

class NotePort(FakePort):
    """Records when each note-on and clock went out, so the fake input can 'play' them back as audio."""

    def __init__(self):
        super().__init__()
        self.note_times = []
        self.clock_times = []

    def send(self, msg):
        now = time.perf_counter()
        if msg.type == "note_on" and msg.velocity:
            self.note_times.append((now, msg.channel))
        elif msg.type == "clock":
            self.clock_times.append(now)
        super().send(msg)


class TimeInfo:
    def __init__(self, adc):
        self.inputBufferAdcTime = adc


class FakeStream:
    """sounddevice.InputStream look-alike: delivers BLOCK-frame blocks in real time from its own thread. Each
    block holds a kick for every channel-1 note-on the port sent, `latency` later. Its clock is perf_counter."""

    def __init__(self, backend, device, channels, samplerate, dtype, blocksize, callback):
        self.backend, self.sr, self.channels, self.cb, self.n = backend, int(samplerate), channels, callback, blocksize
        self.stop_event = threading.Event()
        self.thread = None
        self.latency = 0.003
        backend.opened.append(self)

    @property
    def time(self):
        return time.perf_counter()

    def start(self):
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        t = time.perf_counter()
        dur = self.n / self.sr
        k = kick(self.backend.amp)
        sent = 0
        while not self.stop_event.is_set():
            if self.backend.stall_after is not None and sent >= self.backend.stall_after:
                time.sleep(0.01)
                continue
            while time.perf_counter() < t + dur and not self.stop_event.is_set():
                time.sleep(0.002)
            block = np.zeros(self.n)
            for at, ch in list(self.backend.port.note_times):
                if ch != 0:
                    continue
                start = at + self.backend.latency
                if start < t + dur and start + len(k) / self.sr > t:
                    i = int(round((start - t) * self.sr))
                    a, b = max(0, i), min(self.n, i + len(k))
                    if a < b:
                        block[a:b] += k[a - i:b - i]
            if self.backend.clip:
                block = np.clip(block * 3.0, -1.0, 1.0)
            data = np.stack([block] * self.channels, axis=1).astype(np.float32)
            self.cb(data, self.n, TimeInfo(t), None)
            sent += 1
            t += dur

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=2)

    def close(self):
        pass


class FakeBackend:
    def __init__(self, port, devices=None, latency=0.010, stall_after=None, clip=False, amp=0.6):
        self.port, self.latency, self.stall_after, self.clip, self.amp = port, latency, stall_after, clip, amp
        self.devices = devices if devices is not None else [
            {"name": "MacBook Pro Microphone", "max_input_channels": 1, "default_samplerate": 48000.0},
            {"name": "Digitakt II", "max_input_channels": 2, "default_samplerate": 48000.0}]
        self.opened = []

    def query_devices(self):
        return self.devices

    def InputStream(self, **kw):  # noqa: N802  (sounddevice's name)
        return FakeStream(self, **kw)


@pytest.fixture
def running():
    port = NotePort()
    eng, _ = make_engine(port)
    yield eng, port
    eng.shutdown()


def test_listen_end_to_end_with_a_fake_input(running):
    eng, port = running
    eng.play(P["techno"], bpm=240)
    wait_bar(eng, 1)
    backend = FakeBackend(port, latency=0.010)
    out = listen.listen(eng, bars=2, backend=backend)
    assert eng.playing()  # the beat never noticed
    assert out["device"] == "Digitakt II" and out["playing"] is True and out["bars"] == 2
    assert out["seconds"] == 2.0 and out["from_bar"] >= 2
    k = out["kick"]
    assert k["sent"] == 8 and k["heard"] == 8
    assert k["median_offset_ms"] == pytest.approx(10, abs=3) and k["spread_ms"] <= 4
    # Grid offsets here also measure how late this machine's sequencer sent each note against its tick (a stalled
    # macOS CI runner: ~5-8 ms); the exact grid maths is pinned by the synthetic tests above.
    assert out["onsets"]["per_bar"] == 4.0 and out["onsets"]["median_abs_offset_ms"] <= 15
    assert out["tracks"]["1"]["seems_silent"] is not True  # kicks land with other tracks: no solo hits to judge
    assert out["tracks"]["4"]["seems_silent"] is True  # the fake input only plays kicks, so the hats are missing
    assert out["note"] == listen.NOTE and len(json.dumps(out)) < 4000
    assert eng.note_log is None  # disarmed
    assert eng.status()["listen"]["clipping"] is False


def test_listen_does_not_jitter_the_clock(running):
    eng, port = running
    eng.play(P["techno"], bpm=240)
    wait_bar(eng, 3)
    base_end = len(port.clock_times)
    backend = FakeBackend(port)
    begin = len(port.clock_times)
    out = listen.listen(eng, bars=2, backend=backend)
    end = len(port.clock_times)
    wait_bar(eng, eng.bar + 1)
    eng.stop()
    assert out["kick"]["heard"] == 8
    t = port.clock_times
    base, busy = t[BAR:base_end], t[begin:end]
    assert len(busy) >= 2 * BAR  # the capture window and the analysis after it
    assert _jitter(busy) <= max(_jitter(base) * 2, _jitter(base) + 0.003), (_jitter(base), _jitter(busy))
    for m in port.messages:
        assert m.type in engine.ALLOWED_TYPES
        if m.type == "control_change":
            assert m.control not in ccmap.BLOCKED_CCS


def test_listen_while_stopped_has_no_grid(running):
    eng, port = running
    eng.bpm = 240
    out = listen.listen(eng, bars=1, backend=FakeBackend(port))
    assert out["playing"] is False and "from_bar" not in out
    assert out["silent"] is True and out["kick"] is None and out["onsets"] is None


def test_an_input_that_goes_away_errors_cleanly_and_the_beat_plays_on(running):
    eng, port = running
    eng.play(P["techno"], bpm=240)
    wait_bar(eng, 1)
    with pytest.raises(listen.ListenError, match="stopped delivering audio mid-listen.*beat keeps playing"):
        listen.listen(eng, bars=2, backend=FakeBackend(port, stall_after=5))
    assert eng.playing() and eng.note_log is None
    bar = eng.bar
    wait_bar(eng, bar + 1)  # the clock kept going


def test_no_digitakt_input_refuses_without_capturing(running):
    eng, port = running
    backend = FakeBackend(port, devices=[{"name": "MacBook Pro Microphone", "max_input_channels": 1}])
    with pytest.raises(listen.ListenError, match="no Digitakt II audio input.*USB AUDIO/MIDI"):
        listen.listen(eng, backend=backend)
    assert backend.opened == []  # the laptop mic was never opened


def test_device_override_from_the_environment(running, monkeypatch):
    eng, port = running
    backend = FakeBackend(port, devices=[{"name": "Scarlett 2i2", "max_input_channels": 2,
                                          "default_samplerate": 48000.0}])
    with pytest.raises(listen.ListenError, match="no Digitakt"):
        listen.listen(eng, bars=1, backend=backend)
    monkeypatch.setenv(listen.ENV_DEVICE, "scarlett")
    assert listen.listen(eng, bars=1, backend=backend)["device"] == "Scarlett 2i2"


def test_too_long_a_listen_is_refused(running):
    eng, port = running
    eng.bpm = 60
    with pytest.raises(listen.ListenError, match="at most 24 s"):
        listen.listen(eng, bars=8, backend=FakeBackend(port))


def test_one_listen_at_a_time(running):
    eng, port = running
    assert listen._BUSY.acquire(blocking=False)
    try:
        with pytest.raises(listen.ListenError, match="already running"):
            listen.listen(eng, bars=1, backend=FakeBackend(port))
    finally:
        listen._BUSY.release()


def test_the_tool_round_trip_and_the_guard_it_arms(monkeypatch):
    port = NotePort()
    eng, _ = make_engine(port)
    monkeypatch.setattr(tools, "ENGINE", eng)
    try:
        backend = FakeBackend(port, clip=True, amp=0.9)
        monkeypatch.setattr(listen, "sounddevice_or_error", lambda: backend)
        call("whiplash_play_pattern", genre="techno", bpm=240)
        wait_bar(eng, 1)
        call("whiplash_set_param", track=1, param="level", value=100)
        out = call("whiplash_listen", bars=1)
        assert out["success"] is True and out["loudness"]["clipping"] is True
        refused = call("whiplash_set_param", track=1, param="level", value=110)
        assert refused["success"] is False and "loudness guard" in refused["error"]
        assert call("whiplash_set_param", track=1, param="level", value=80)["success"] is True
        assert call("whiplash_status")["safety"]["loudness_guard"] is True
        backend.clip, backend.amp = False, 0.5
        assert call("whiplash_listen", bars=1)["loudness"]["clipping"] is False
        assert call("whiplash_set_param", track=1, param="level", value=110)["success"] is True
        bad = call("whiplash_listen", bars=12)
        assert bad["success"] is False and "bars must be 1-8" in bad["error"]
    finally:
        eng.shutdown()
