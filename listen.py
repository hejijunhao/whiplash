"""v0.7.0 listening loop: capture the Digitakt II's USB audio for N bars and reduce it to a few numbers.

numpy and sounddevice are an optional extra (`whiplash[listen]`). They are imported only inside a listen, so
the plugin loads, and every other tool works, without them; whiplash_listen then says how to install them.

Clock safety:
- The sequencer thread does two cheap things for a listen: it appends (bar, time) to Engine.bar_log once per bar,
  and, only while a listen is armed, appends (time, channel, note, velocity) to Engine.note_log per note-on.
  Both are deque appends with no lock.
- Capture runs in PortAudio's callback thread (copies each block, nothing else). Waiting and analysis run in the
  tool call's own thread, never in the sequencer, and never hold Engine._lock beyond copying a few values.
- Analysis works in small numpy batches and yields the GIL between them (_yield), so a listen doesn't jitter
  the clock. tests/test_v070_listen.py measures that.

What comes back is compact features only, never audio: loudness (gated, K-weighted: "LUFS-ish"), peak and
clipping, four-band balance, onsets against Whiplash's grid, kick offsets against the kicks Whiplash sent, a
low-end masking hint, per-track "seems silent" hints and a silence flag. All of it describes the single USB OUT
pair (normally MAIN), so per-track numbers are inferences from timing, not per-track audio.
"""
import math
import os
import threading
import time

from .engine import WhiplashError

ENV_DEVICE = "WHIPLASH_AUDIO_INPUT"  # input device name (substring) or index; overrides the Digitakt search
DEVICE_HINTS = ("digitakt",)
BARS_DEFAULT, BARS_MAX = 2, 8
SECONDS_MAX = 24.0  # one listen never captures more than this, whatever the tempo
LATENCY_MARGIN = 0.15  # s captured after the window: MIDI out -> unit -> USB audio back in
START_MARGIN = 0.25  # s: the next bar line has to be at least this far away, else the listen starts a bar later
STALL = 1.0  # s without an audio block = the input went away (unplugged, permission revoked)
BLOCK = 1024  # frames per callback block
BANDS = (("low", 20.0, 150.0), ("low_mid", 150.0, 600.0), ("mid", 600.0, 4000.0), ("high", 4000.0, 20000.0))
KICK_HZ = 150.0  # the kick's band for detection and the masking check
CLIP_LEVEL = 0.999  # |sample| at or above this counts as full scale
CLIP_SAMPLES = 3  # this many full-scale samples = clipping
SILENT_DBFS = -60.0  # a window whose peak stays below this is silent
ON_GRID_MS = 10.0
KICK_MATCH = (-0.02, 0.10)  # s around a sent kick where its audio onset may land
HEARD_MATCH = (-0.015, 0.035)  # s around a sent note (after latency) where a heard onset counts
SOLO_GAP = 0.04  # s: a note with no other track's note-on this close is a "solo hit"
MASK_DB = 3.0  # kick windows less than this much louder (low band) than the rest = masking
OFFSETS_SHOWN = 16

INSTALL_HINT = ("whiplash_listen needs numpy and sounddevice (PortAudio). Install them into the Python that runs "
                "Hermes (pip install 'numpy>=1.24' 'sounddevice>=0.4.6', or Whiplash's [listen] extra; on Linux also "
                "libportaudio2), then restart the gateway. Every other Whiplash tool works without them.")
PERMISSION_HINT = ("On macOS, allow microphone access for the app that runs Hermes (System Settings > Privacy & "
                   "Security > Microphone), then restart it.")
USB_HINT = ("On the Digitakt II set USB CONFIG to USB AUDIO/MIDI (manual 14.8.1, p. 83) and USB OUT to MAIN "
            "(AUDIO ROUTING, p. 81); MIDI keeps working in that mode. Or set WHIPLASH_AUDIO_INPUT to another input "
            "that records the unit.")
NOTE = ("Numbers describe the unit's USB OUT pair (normally MAIN), captured over USB, never stored or sent "
        "anywhere. Kick offsets include the MIDI-to-audio round trip, so a steady few ms is latency; the spread "
        "is the timing. Per-track hints come from note timing, not per-track audio. Not hardware-verified yet.")

_BUSY = threading.Lock()  # one listen at a time

_K_SHELF = ((1.53512485958697, -2.69169618940638, 1.19839281085285), (1.0, -1.69065929318241, 0.73248077421585))
_K_HIGHPASS = ((1.0, -2.0, 1.0), (1.0, -1.99004745483398, 0.99007225036621))  # ITU-R BS.1770 K-weighting, 48 kHz


class ListenError(WhiplashError):
    pass


def _yield():
    time.sleep(0)  # hand the GIL to the sequencer thread if it is waiting for it


# ---- optional dependencies -----------------------------------------------------------------------------------

def numpy_or_error():
    try:
        import numpy
    except ImportError:
        raise ListenError("numpy is not installed. " + INSTALL_HINT) from None
    return numpy


def sounddevice_or_error():
    try:
        import sounddevice
    except ImportError:
        raise ListenError("sounddevice is not installed. " + INSTALL_HINT) from None
    except OSError as exc:  # the module is there but the PortAudio library isn't
        raise ListenError(f"sounddevice can't load PortAudio ({exc}). " + INSTALL_HINT) from None
    return sounddevice


def available():
    """{"numpy": bool, "sounddevice": bool} without importing either (for status)."""
    import importlib.util
    out = {}
    for name in ("numpy", "sounddevice"):
        try:
            out[name] = importlib.util.find_spec(name) is not None
        except (ImportError, ValueError):
            out[name] = False
    return out


# ---- device discovery ----------------------------------------------------------------------------------------

def inputs(devices):
    """[(index, name, channels, samplerate)] for every device with an input."""
    out = []
    for i, dev in enumerate(devices):
        channels = int(dev.get("max_input_channels") or 0)
        if channels > 0:
            out.append((int(dev.get("index", i)), str(dev.get("name", "")), channels,
                        float(dev.get("default_samplerate") or 48000.0)))
    return out


def find_input(devices, want=None):
    """Pick the capture device: `want` (index or name substring, from the call or WHIPLASH_AUDIO_INPUT), else the
    first input whose name says Digitakt. Never falls back to another input (a laptop mic would analyse the room).
    -> (index, name, channels, samplerate)"""
    found = inputs(devices)
    names = [name for _, name, _, _ in found][:12]
    want = None if want is None else str(want).strip()
    if want:
        if want.isdigit():
            for item in found:
                if item[0] == int(want):
                    return item
            raise ListenError(f"no audio input with index {want}; inputs: {names or 'none'}")
        for item in found:
            if want.lower() in item[1].lower():
                return item
        raise ListenError(f"no audio input matches {want!r}; inputs: {names or 'none'}")
    for item in found:
        if any(h in item[1].lower() for h in DEVICE_HINTS):
            return item
    raise ListenError(f"no Digitakt II audio input found (inputs: {names or 'none'}). {USB_HINT} {PERMISSION_HINT}")


def check_bars(bars):
    if bars is None:
        return BARS_DEFAULT
    if isinstance(bars, bool) or not isinstance(bars, (int, float)) or bars != int(bars):
        raise ListenError(f"bars must be a whole number 1-{BARS_MAX}, got {bars!r}")
    bars = int(bars)
    if not 1 <= bars <= BARS_MAX:
        raise ListenError(f"bars must be 1-{BARS_MAX}, got {bars}")
    return bars


# ---- capture -------------------------------------------------------------------------------------------------

class Recorder:
    """The PortAudio callback: copies each block with its timestamps, nothing else."""

    def __init__(self):
        self.blocks = []  # (adc_time, arrival perf_counter, frames, array)
        self.flags = set()
        self.last = time.perf_counter()

    def callback(self, indata, frames, time_info, status):
        now = time.perf_counter()
        adc = getattr(time_info, "inputBufferAdcTime", 0.0) or 0.0
        self.blocks.append((adc, now, frames, indata.copy()))
        self.last = now
        if status:
            self.flags.add(str(status).strip())


def assemble(np, blocks, sr, offset, latency):
    """Blocks -> (audio frames x channels, perf_counter time of sample 0).

    Each block's first-sample time is its ADC time on the perf_counter clock (offset maps PortAudio's stream clock
    onto it), or, when the backend gives no ADC time, its arrival time minus its length and the input latency. The
    window start is the median over blocks of (block time - samples before it / sr), which ignores callback jitter.
    """
    audio = np.concatenate([b[3] for b in blocks], axis=0).astype(np.float32, copy=False)
    if audio.ndim == 1:
        audio = audio[:, None]
    before = np.cumsum([0] + [b[2] for b in blocks[:-1]]) / float(sr)
    if offset is not None and all(b[0] > 0 for b in blocks):
        firsts = np.array([b[0] for b in blocks]) + offset
    else:
        firsts = np.array([b[1] - b[2] / float(sr) - latency for b in blocks])
    return audio, float(np.median(firsts - before))


def _stream_offset(stream):
    try:
        clock = float(stream.time)
    except Exception:
        return None
    return time.perf_counter() - clock if clock > 0 else None


def _bar_times(engine, first, n, bar_len, expected):
    """Bar start times for bars first..first+n (n+1 lines) from the sequencer's bar log, else extrapolated."""
    logged = dict(list(engine.bar_log))
    times, last = [], None
    for i in range(n + 1):
        t = logged.get(first + i)
        if t is None:
            t = (last + bar_len) if last is not None else expected + i * bar_len
        times.append(t)
        last = t
    return times


def listen(engine, bars=None, device=None, backend=None):
    """whiplash_listen: capture `bars` bars from the next bar line (or now, when nothing plays) and analyse them.

    Validates and opens the input before arming anything; the beat is never touched. backend is a test hook with
    sounddevice's query_devices() and InputStream(...)."""
    n = check_bars(bars)
    np = numpy_or_error()
    sd = backend if backend is not None else sounddevice_or_error()
    if not _BUSY.acquire(blocking=False):
        raise ListenError("a listen is already running; wait for its result")
    try:
        return _listen(engine, n, device, np, sd)
    finally:
        _BUSY.release()


def _listen(engine, n, device, np, sd):
    try:
        devices = list(sd.query_devices())
    except Exception as exc:
        raise ListenError(f"can't list audio inputs ({type(exc).__name__}: {exc}). {PERMISSION_HINT}") from None
    want = device if device not in (None, "") else os.environ.get(ENV_DEVICE) or None
    index, name, channels, sr = find_input(devices, want)
    channels = min(2, channels)
    playing, bpm = engine.listen_clock()
    bar_len = 240.0 / bpm
    seconds = n * bar_len
    if seconds > SECONDS_MAX:
        raise ListenError(f"{n} bars at {bpm:g} BPM is {seconds:.1f} s; one listen captures at most "
                          f"{SECONDS_MAX:g} s, so ask for fewer bars")
    rec = Recorder()
    stream = None
    try:
        stream = sd.InputStream(device=index, channels=channels, samplerate=sr, dtype="float32", blocksize=BLOCK,
                                callback=rec.callback)
        stream.start()
    except Exception as exc:
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass
        raise ListenError(f"can't open audio input {name!r} ({type(exc).__name__}: {exc}). {PERMISSION_HINT} "
                          f"{USB_HINT}") from None
    offset = _stream_offset(stream)
    latency = getattr(stream, "latency", 0.0) or 0.0
    latency = float(latency[0] if isinstance(latency, (tuple, list)) else latency)
    engine.arm_listen()
    first_bar = None
    stopped_mid = False
    try:
        if playing:
            first_bar, start = engine.next_bar_line(START_MARGIN)
            if first_bar is None:  # stopped between the checks
                playing, start = False, time.perf_counter() + 0.05
        else:
            start = time.perf_counter() + 0.05
        deadline = start + seconds + LATENCY_MARGIN
        opened = time.perf_counter()
        while True:
            now = time.perf_counter()
            if now >= deadline:
                break
            if now - max(rec.last, opened) > STALL:
                raise ListenError(f"audio input {name!r} stopped delivering audio mid-listen (unplugged, or "
                                  f"permission revoked?). The beat keeps playing. {USB_HINT}")
            if playing and not stopped_mid and not engine.playing():
                stopped_mid = True
            time.sleep(min(0.02, deadline - now))
    finally:
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass
        notes = engine.disarm_listen()
    if not rec.blocks:
        raise ListenError(f"no audio arrived from {name!r}. {PERMISSION_HINT} {USB_HINT}")
    audio, t0 = assemble(np, rec.blocks, sr, offset, latency)
    rec.blocks = []
    lo = int(round((start - t0) * sr))
    hi = int(round((start + seconds + LATENCY_MARGIN - t0) * sr))
    if lo < 0 or hi > len(audio) + int(0.05 * sr):
        raise ListenError(f"the audio from {name!r} doesn't cover the window (input started late or dropped "
                          "blocks); try again")
    audio = audio[lo:hi]
    _yield()
    end = start + seconds
    grid = _bar_times(engine, first_bar, n, bar_len, start) if playing else None
    sent = [(t, ch + 1, note) for t, ch, note, _ in notes if start - 0.01 <= t < end]
    roles = engine.listen_roles()
    features = analyse(np, audio, sr, start, seconds, grid, sent, roles)
    out = {"device": name, "sample_rate": int(sr), "channels": channels, "bars": n, "bpm": bpm,
           "seconds": round(seconds, 2), "playing": playing, **features}
    if playing:
        out["from_bar"] = first_bar
    if stopped_mid:
        out["notes"].insert(0, "the beat stopped during the listen; the numbers cover what played")
    if rec.flags:
        out["input_status"] = sorted(rec.flags)[:4]
    out["note"] = NOTE
    engine.record_listen(out)
    return out


# ---- analysis ------------------------------------------------------------------------------------------------

def _db(np, x, floor=-120.0):
    return float(max(floor, 10.0 * math.log10(x))) if x > 0 else floor


def _k_gain(np, freqs):
    """|H|^2 of the BS.1770 K-weighting at freqs (Hz), using the 48 kHz coefficients."""
    z = np.exp(-1j * 2.0 * np.pi * freqs / 48000.0)
    out = np.ones(len(freqs))
    for b, a in (_K_SHELF, _K_HIGHPASS):
        out *= np.abs((b[0] + b[1] * z + b[2] * z * z) / (a[0] + a[1] * z + a[2] * z * z)) ** 2
    return out


def loudness(np, audio, sr):
    """Gated, K-weighted loudness in the spirit of BS.1770 ("LUFS-ish") -> (lufs or None, band powers by Hz).

    The signal is cut into 100 ms sub-blocks; each sub-block is K-weighted in the frequency domain (Parseval), so
    400 ms blocks with 75 % overlap are sums of four sub-blocks. Absolute gate -70, relative gate -10. Sub-block
    FFTs are circular, hence "-ish": within about a dB of a meter on music. Also returns the mono power spectrum
    summed over the sub-blocks, for the band balance."""
    sub = max(1, int(round(0.1 * sr)))
    count = len(audio) // sub
    freqs = np.fft.rfftfreq(sub, 1.0 / sr)
    gain = _k_gain(np, freqs)
    weights = np.full(len(freqs), 2.0)
    weights[0] = 1.0
    if sub % 2 == 0:
        weights[-1] = 1.0
    energies = np.zeros(count)
    spectrum = np.zeros(len(freqs))
    batch = 8
    for i in range(0, count, batch):
        k = min(batch, count - i)
        chunk = audio[i * sub:(i + k) * sub].reshape(k, sub, audio.shape[1])
        X = np.fft.rfft(chunk, axis=1)
        power = np.abs(X) ** 2  # k x bins x channels
        energies[i:i + k] = (power * (gain * weights)[None, :, None]).sum(axis=(1, 2)) / (sub * sub)
        mono = np.abs(X.mean(axis=2)) ** 2
        spectrum += (mono * weights[None, :]).sum(axis=0)
        _yield()
    if count < 4:
        blocks = np.array([energies.mean()]) if count else np.array([0.0])
    else:
        blocks = (energies[:-3] + energies[1:-2] + energies[2:-1] + energies[3:]) / 4.0
    with np.errstate(divide="ignore"):
        lk = -0.691 + 10.0 * np.log10(blocks)
    kept = blocks[lk > -70.0]
    if not len(kept):
        return None, freqs, spectrum
    rel = -0.691 + 10.0 * math.log10(kept.mean()) - 10.0
    kept = blocks[lk > max(-70.0, rel)]
    return round(-0.691 + 10.0 * math.log10(kept.mean()), 1), freqs, spectrum


def bands(np, freqs, spectrum):
    """Four-band balance: each band's share of the 20 Hz-20 kHz energy, in % and dB."""
    total = float(spectrum[(freqs >= BANDS[0][1]) & (freqs < BANDS[-1][2])].sum())
    out = {}
    for name, lo, hi in BANDS:
        e = float(spectrum[(freqs >= lo) & (freqs < hi)].sum())
        out[name] = {"pct": round(100.0 * e / total, 1) if total > 0 else 0.0,
                     "db": round(_db(np, e / total), 1) if total > 0 else None}
    return out


def envelopes(np, mono, sr, cutoff=KICK_HZ):
    """Amplitude envelopes at 1 ms resolution: full band and below `cutoff` (analytic signal, overlap-save)."""
    n = len(mono)
    size, pad = 16384, 2048
    hop = size - 2 * pad
    freqs = np.fft.fftfreq(size, 1.0 / sr)
    h_full = np.zeros(size)
    h_full[0] = 1.0
    h_full[1:size // 2] = 2.0
    h_full[size // 2] = 1.0
    h_low = h_full * (np.abs(freqs) <= cutoff)
    padded = np.concatenate([np.zeros(pad), mono, np.zeros(size)])
    full, low = np.zeros(n), np.zeros(n)
    for start in range(0, n, hop):
        X = np.fft.fft(padded[start:start + size])
        keep = min(hop, n - start)
        full[start:start + keep] = np.abs(np.fft.ifft(X * h_full))[pad:pad + keep]
        low[start:start + keep] = np.abs(np.fft.ifft(X * h_low))[pad:pad + keep]
        _yield()
    ms = max(1, int(round(sr / 1000.0)))
    m = n // ms
    return full[:m * ms].reshape(m, ms).mean(axis=1), low[:m * ms].reshape(m, ms).mean(axis=1)


def _flux(np, mono, sr, cutoff=None):
    """Spectral flux (log magnitude, positive differences) at a 5 ms hop -> (flux, hop seconds); frame i is
    centred at i * hop."""
    n_fft = 1024 if sr <= 50000 else 2048
    hop = max(1, int(round(sr * 0.005)))
    padded = np.concatenate([np.zeros(n_fft // 2), mono, np.zeros(n_fft // 2)])
    starts = np.arange(0, len(mono), hop)
    window = np.hanning(n_fft)
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    pick = (freqs <= cutoff) & (freqs > 20.0) if cutoff else (freqs > 20.0)
    from numpy.lib.stride_tricks import sliding_window_view
    view = sliding_window_view(padded, n_fft)
    mags = []
    for i in range(0, len(starts), 128):
        frames = view[starts[i:i + 128]] * window
        mags.append(np.log1p(1000.0 * np.abs(np.fft.rfft(frames, axis=1))[:, pick]))
        _yield()
    mag = np.concatenate(mags, axis=0)
    flux = np.zeros(len(starts))
    flux[1:] = np.maximum(0.0, np.diff(mag, axis=0)).sum(axis=1)
    return flux, hop / float(sr)


def _peaks(np, flux, hop_s, min_gap=0.03):
    """Frame indices of onset peaks: local maxima above a moving median plus a floor."""
    if len(flux) < 3 or flux.max() <= 0:
        return []
    from numpy.lib.stride_tricks import sliding_window_view
    w = max(1, int(round(0.1 / hop_s)))
    med = np.median(sliding_window_view(np.pad(flux, w, mode="edge"), 2 * w + 1), axis=1)
    thr = 1.5 * med + 0.1 * float(np.percentile(flux, 99.5))
    left = np.concatenate([[0.0], flux[:-1]])
    right = np.concatenate([flux[1:], [0.0]])
    cand = np.nonzero((flux > thr) & (flux >= left) & (flux > right))[0]
    gap = max(1, int(round(min_gap / hop_s)))
    out = []
    for i in cand:  # few hundred at most
        if out and i - out[-1] < gap:
            if flux[i] > flux[out[-1]]:
                out[-1] = i
            continue
        out.append(int(i))
    return out


def _refine(np, env, t_ms, before=30, after=40):
    """Onset time (ms) near t_ms: where the envelope first reaches half way from its preceding minimum to the
    local peak."""
    a, b = max(0, int(t_ms) - before), min(len(env), int(t_ms) + after)
    seg = env[a:b]
    if len(seg) < 3:
        return float(t_ms)
    top = int(np.argmax(seg))
    low = int(np.argmin(seg[:top + 1]))
    base, peak = seg[low], seg[top]
    if peak <= base:
        return float(t_ms)
    idx = low + int(np.argmax(seg[low:top + 1] >= base + 0.5 * (peak - base)))
    return float(a + idx)


def onsets(np, mono, sr, env, cutoff=None):
    """Onset times in seconds from the window start."""
    flux, hop_s = _flux(np, mono, sr, cutoff)
    found = [_refine(np, env, i * hop_s * 1000.0) / 1000.0 for i in _peaks(np, flux, hop_s)]
    _yield()
    return sorted(set(round(t, 4) for t in found))


def _grid_offset(grid, t):
    """(step index from the first bar line, offset in s) of time t against the straight 16th grid."""
    import bisect
    b = min(max(0, bisect.bisect_right(grid, t) - 1), len(grid) - 2)
    step_len = (grid[b + 1] - grid[b]) / 16.0
    step = int(round((t - grid[b]) / step_len))
    return b * 16 + step, t - (grid[b] + step * step_len)


def _median(values):
    s = sorted(values)
    if not s:
        return None
    mid = len(s) // 2
    return s[mid] if len(s) % 2 else (s[mid - 1] + s[mid]) / 2.0


def _nearest(times, t, lo, hi):
    """The time in sorted `times` closest to t within [t+lo, t+hi], or None."""
    import bisect
    i = bisect.bisect_left(times, t + lo)
    best = None
    while i < len(times) and times[i] <= t + hi:
        if best is None or abs(times[i] - t) < abs(best - t):
            best = times[i]
        i += 1
    return best


def analyse(np, audio, sr, start, seconds, grid=None, sent=(), roles=None):
    """Features of a captured window. audio: frames x channels float, its first sample at perf time `start`;
    grid: bar line times (perf) covering the window, or None; sent: [(time, track, note)] note-ons Whiplash sent;
    roles: {track: role}. Times in the result are ms."""
    roles = roles or {}
    audio = np.asarray(audio, dtype=np.float64)
    if audio.ndim == 1:
        audio = audio[:, None]
    notes = []
    peak = float(np.abs(audio).max()) if audio.size else 0.0
    clipped = int((np.abs(audio) >= CLIP_LEVEL).sum())
    lufs, freqs, spectrum = loudness(np, audio, sr)
    rms = float(np.sqrt(np.mean(audio ** 2))) if audio.size else 0.0
    peak_db = round(20.0 * math.log10(peak), 1) if peak > 0 else -120.0
    silent = peak_db < SILENT_DBFS
    out = {"loudness": {"lufs_ish": lufs, "rms_dbfs": round(20.0 * math.log10(rms), 1) if rms > 0 else -120.0,
                        "peak_dbfs": peak_db, "headroom_db": round(-peak_db, 1),
                        "clipping": clipped >= CLIP_SAMPLES, "clipped_samples": clipped},
           "silent": silent}
    if clipped >= CLIP_SAMPLES:
        notes.append(f"clipping: {clipped} samples at full scale. Level/overdrive increases are refused until a "
                     "listen shows none (force=true if the user insists)")
    elif peak_db > -1.0:
        notes.append(f"peak {peak_db} dBFS: under 1 dB of headroom")
    out["bands"] = bands(np, freqs, spectrum) if not silent else None
    sent = sorted(sent)
    if silent:
        out.update(onsets=None, kick=None, low_end=None, tracks=None)
        notes.append("silent: nothing came back on the input. " + (
            "Whiplash sent notes, so check USB OUT = MAIN, the unit's levels, and that this input is the "
            "Digitakt" if sent else "nothing played either"))
        out["notes"] = notes
        return out
    mono = audio.mean(axis=1)
    env_full, env_low = envelopes(np, mono, sr)
    hits = onsets(np, mono, sr, env_full)
    lows = onsets(np, mono, sr, env_low, cutoff=KICK_HZ)
    abs_hits = [start + t for t in hits if t < seconds]
    abs_lows = [start + t for t in lows]
    # kick: each kick Whiplash sent, matched to a low-band onset just after it
    kick_tracks = {t for t, r in roles.items() if r == "kick"}
    kicks = [t for t, track, _ in sent if track in kick_tracks]
    kick_offsets, kick_hits = [], []
    for t in kicks:
        hit = _nearest(abs_lows, t, *KICK_MATCH)
        if hit is not None:
            kick_offsets.append((hit - t) * 1000.0)
            kick_hits.append(hit)
    latency = _median(kick_offsets)
    if kicks:
        out["kick"] = {"sent": len(kicks), "heard": len(kick_offsets), "missed": len(kicks) - len(kick_offsets),
                       "median_offset_ms": round(latency, 1) if latency is not None else None,
                       "spread_ms": round(max(kick_offsets) - min(kick_offsets), 1) if kick_offsets else None,
                       "offsets_ms": [round(x, 1) for x in kick_offsets[:OFFSETS_SHOWN]]}
        if not kick_offsets:
            notes.append("no kick heard where Whiplash sent kicks: is the kick track muted or quiet on the unit?")
    else:
        out["kick"] = None
    if latency is None and sent:  # no kick: estimate latency from any onset after any sent note
        offs = [(h - t) * 1000.0 for t, _, _ in sent for h in [_nearest(abs_hits, t, *KICK_MATCH)] if h is not None]
        latency = _median(offs)
    lat = (latency or 0.0) / 1000.0
    # onsets against the grid
    ons = {"count": len(abs_hits), "per_bar": None}
    if grid:
        bars_n = len(grid) - 1
        ons["per_bar"] = round(len(abs_hits) / bars_n, 1)
        placed = [_grid_offset(grid, h - lat) for h in abs_hits]
        offs = [o * 1000.0 for _, o in placed]
        if offs:
            mags = [abs(o) for o in offs]
            ons["median_abs_offset_ms"] = round(_median(mags), 1)
            ons["max_abs_offset_ms"] = round(max(mags), 1)
            ons["on_grid_pct"] = round(100.0 * sum(m <= ON_GRID_MS for m in mags) / len(mags))
            odd = [o for (s, _), o in zip(placed, offs) if s % 2]
            even = [o for (s, _), o in zip(placed, offs) if not s % 2]
            if len(odd) >= 3 and even:
                delay = _median(odd) - _median(even)
                step_ms = (grid[1] - grid[0]) * 1000.0 / 16.0
                ons["offbeat_delay_ms"] = round(delay, 1)
                ons["swing_estimate"] = round(min(80.0, max(50.0, 50.0 + 50.0 * delay / step_ms)))
        ons["latency_corrected_ms"] = round(latency, 1) if latency is not None else None
    out["onsets"] = ons
    # low end: does the kick stand out of the low band, or is something sitting on it?
    out["low_end"] = None
    if len(kick_offsets) >= 2:
        power = env_low ** 2
        mask = np.zeros(len(power), dtype=bool)
        for t in kick_hits:
            a = int(round((t - start) * 1000.0))
            mask[max(0, a):max(0, a + 80)] = True
        if mask.any() and (~mask).any():
            ratio = _db(np, float(power[mask].mean()) / max(float(power[~mask].mean()), 1e-20))
            out["low_end"] = {"kick_over_rest_db": round(ratio, 1), "masking": ratio < MASK_DB}
            if ratio < MASK_DB:
                notes.append(f"the low band is only {ratio:.1f} dB louder on the kicks than between them: something "
                             "(usually the bass) may be masking the kick")
    # per track: did solo hits come back as onsets?
    tracks = {}
    every = sorted(set(abs_hits) | set(abs_lows))
    for track in sorted({tr for _, tr, _ in sent}):
        mine = [t for t, tr, _ in sent if tr == track]
        others = sorted(t for t, tr, _ in sent if tr != track)
        solo = [t for t in mine if _nearest(others, t, -SOLO_GAP, SOLO_GAP) is None]
        heard = sum(_nearest(every, t + lat, *HEARD_MATCH) is not None for t in solo)
        tracks[str(track)] = {"notes": len(mine), "solo_hits": len(solo), "heard": heard,
                              "seems_silent": (heard == 0) if len(solo) >= 2 else None}
    out["tracks"] = tracks or None
    quiet = [int(t) for t, e in tracks.items() if e["seems_silent"]]
    if quiet:
        notes.append(f"track(s) {quiet} sent notes but nothing was heard on their solo hits: muted, level 0, or an "
                     "empty sample slot on the unit?")
    if not sent and len(abs_hits) >= 2:
        out["unexpected_audio"] = True
        notes.append("onsets while Whiplash sent no notes: probably the unit's own pattern (MIDI Start runs it), "
                     "or something on the inputs")
    out["notes"] = notes
    return out


def summary(result):
    """The part of a listen kept for status and the loudness guard."""
    loud = result.get("loudness") or {}
    return {"at": time.time(), "bars": result.get("bars"), "lufs_ish": loud.get("lufs_ish"),
            "peak_dbfs": loud.get("peak_dbfs"), "clipping": bool(loud.get("clipping")),
            "silent": bool(result.get("silent"))}


