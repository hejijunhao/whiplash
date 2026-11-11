"""v0.7.1 whiplash_scan_kit: play each track once, alone, hear it over USB audio, and PROPOSE kit-map labels.

What it does, with the beat stopped:
1. Opens the Digitakt's USB audio input through the v0.7.0 capture path (listen.py), and checks that the unit is quiet
   before any note goes out. If it isn't, the unit's own pattern is probably running (the v0.4 overlap), so the scan
   refuses and sends nothing.
2. Plays one note per track 1-16 in turn: MIDI note 60 (the sample's own pitch, reference.md §6.1) on the track's
   own channel, velocity 100, held for GATE. The next note waits until the last one has faded (at most
   TAIL_WAIT more), so tails don't overlap.
3. After the last tail, analyses each hit in the tool call's thread, never the sequencer's, yielding the GIL between
   tracks. The features are spectral centroid, decay, pitchedness (autocorrelation) and low-end share. Each hit
   gets a label (kick, snare/clap, hat, perc, bass, pad/chord, lead/stab, fx, silent, unknown) and a confidence.
4. Returns the proposal and `apply_with`, the exact whiplash_label_tracks arguments. **It never applies them.** The
   agent shows the user, and calls whiplash_label_tracks only after the user says yes.

What it sends: note-on and note-off on the scanned tracks' channels, nothing else. No CC, no clock, no Start, no
program change, no SysEx; it never selects a sample or a slot. whiplash_stop or a fresh play aborts it before its next
note (Engine.scan_note). It shares the listen's one-at-a-time lock.

numpy and sounddevice are the same optional extra as whiplash_listen, imported only inside a scan.
"""
import math
import os
import time

from . import listen as _listen
from .engine import HIGH_TRACK_NOTE, WhiplashError
from .listen import ListenError, _yield

NOTE, VELOCITY = 60, 100
GATE = 0.25  # s each note is held before its note-off
WINDOW = 1.0  # s from one note-on to the next, at least
TAIL_WAIT = 1.0  # s the next note may wait on top of WINDOW for the last one to fade
LEAD = 0.4  # s captured before the first note: the unit has to be quiet here
PRE = 0.12  # s before the next note where a hit's analysis window ends
PRE_CHECK = 0.04  # s just before each note checked for sound it can't have made (the scan waited for quiet there)
QUIET_DBFS = -50.0  # below this the unit counts as quiet (a tail has faded)
HIT_SILENT_DBFS = -55.0  # a hit whose peak stays below this was not heard
UNKNOWN_BELOW = 0.3  # confidence under this = "unknown" (the best guess stays in the result)
LABELS = ("kick", "snare/clap", "hat", "perc", "bass", "pad/chord", "lead/stab", "fx")
FEATURES = ("centroid_hz", "decay_ms", "hold_ms", "pitched", "low_pct", "peak_dbfs")

CONFIRM = ("PROPOSAL ONLY, nothing applied. Show the user the labels (and the unsure ones), and call "
           "whiplash_label_tracks with apply_with.tracks only after they say yes, with their corrections.")
NOTE_TEXT = ("One note 60 per track on its own channel, alone; nothing else was sent. Labels are guesses from one hit "
             "on the USB OUT pair (normally MAIN, effects included): a retuned, filtered or LFO'd preset can fool them, "
             "and a sample is often more than one thing. Not hardware-verified yet.")
SILENT_HINT = ("silent: muted on the unit, level 0, an empty slot, its MIDI channel changed or OFF, or USB OUT isn't "
               "MAIN")
PATTERN_HINT = ("probably the unit's own pattern (Play pressed on the unit, or a MIDI Start from elsewhere: the v0.4 "
                "overlap) or something on its inputs. Stop the unit's sequencer and scan again")


class ScanError(ListenError):
    pass


def check_tracks(tracks):
    """None -> 1-16; else a list of distinct tracks 1-16, in the order given."""
    if tracks in (None, [], ()):
        return list(range(1, 17))
    if not isinstance(tracks, (list, tuple)):
        raise ScanError(f"tracks must be a list of track numbers 1-16, got {tracks!r}")
    out = []
    for raw in tracks:
        if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
            raise ScanError(f"track must be 1-16, got {raw!r}")
        try:
            number = float(str(raw).strip())
        except ValueError:
            raise ScanError(f"track must be 1-16, got {raw!r}") from None
        if number != int(number) or not 1 <= number <= 16:
            raise ScanError(f"track must be 1-16, got {raw!r}")
        if int(number) not in out:
            out.append(int(number))
    return out


def refusal(transport):
    """Why a scan can't run while a beat plays."""
    if transport:
        return ("whiplash_scan_kit needs the beat stopped: Whiplash is playing with MIDI Start, so the unit's own "
                "pattern runs too and would sound in every solo hit. Call whiplash_stop (it sends MIDI Stop), then "
                "scan; restart the beat afterwards.")
    return ("whiplash_scan_kit needs the beat stopped: Whiplash's beat (clock only) would sound under every solo hit. "
            "Call whiplash_stop, then scan; restart the beat afterwards.")


# ---- the scan --------------------------------------------------------------------------------------------------

def scan(engine, tracks=None, device=None, backend=None, window=None):
    """whiplash_scan_kit. backend is a test hook (sounddevice's query_devices and InputStream); window overrides
    WINDOW (tests). Validates everything, and checks that the unit is quiet, before the first note."""
    order = check_tracks(tracks)
    window = WINDOW if window is None else float(window)
    playing, transport, muted, stops = engine.scan_state()
    if playing:
        raise ScanError(refusal(transport))
    np = _listen.numpy_or_error()
    sd = backend if backend is not None else _listen.sounddevice_or_error()
    if not _listen._BUSY.acquire(blocking=False):
        raise ScanError("a listen or kit scan is already running; wait for its result")
    try:
        return _scan(engine, order, muted, stops, device, np, sd, window)
    finally:
        _listen._BUSY.release()


def _level_db(np, rec, sr, seconds=0.05):
    """Peak dBFS of the last `seconds` of captured audio (tool thread; reads the recorder's list)."""
    need, got, parts = int(seconds * sr), 0, []
    for block in reversed(rec.blocks[-16:]):
        parts.append(block[3])
        got += len(block[3])
        if got >= need:
            break
    if not parts:
        return -120.0
    peak = max(float(np.abs(p).max()) if p.size else 0.0 for p in parts)
    return 20.0 * math.log10(peak) if peak > 0 else -120.0


def _wait(rec, name, until, opened):
    """Sleep until perf time `until`, raising if the input stops delivering audio."""
    while True:
        now = time.perf_counter()
        if now >= until:
            return
        if now - max(rec.last, opened) > _listen.STALL:
            raise ScanError(f"audio input {name!r} stopped delivering audio mid-scan (unplugged, or permission "
                            f"revoked?). The scan stopped; nothing else changed. {_listen.USB_HINT}")
        time.sleep(min(0.01, until - now))


def _note(engine, track, on, stops):
    """A scan note-on/off; a stop, a fresh play or a lost MIDI port becomes a clean ScanError."""
    try:
        engine.scan_note(track, on, stops, NOTE, VELOCITY)
    except WhiplashError as exc:
        raise ScanError(f"{exc}; the tracks heard so far are discarded, scan again") from None
    except Exception as exc:
        raise ScanError(f"the MIDI port failed mid-scan ({type(exc).__name__}: {exc}): unplugged? Nothing else "
                        "changed; reconnect and scan again.") from None


def _scan(engine, order, muted, stops, device, np, sd, window):
    try:
        devices = list(sd.query_devices())
    except Exception as exc:
        raise ScanError(f"can't list audio inputs ({type(exc).__name__}: {exc}). {_listen.PERMISSION_HINT}") from None
    want = device if device not in (None, "") else os.environ.get(_listen.ENV_DEVICE) or None
    index, name, channels, sr = _listen.find_input(devices, want)
    channels = min(2, channels)
    engine.ensure_port()
    if engine.virtual:
        raise ScanError("no Digitakt II on MIDI: the scan's notes would go to the silent virtual port. Connect the "
                        "unit over USB (whiplash_list_midi_ports), then scan.")
    skipped = [t for t in order if t in muted]
    order = [t for t in order if t not in muted]
    if not order:
        raise ScanError(f"every track asked for is muted in Whiplash ({skipped}); unmute them or pick others")
    rec = _listen.Recorder()
    stream = None
    try:
        stream = sd.InputStream(device=index, channels=channels, samplerate=sr, dtype="float32",
                                blocksize=_listen.BLOCK, callback=rec.callback)
        stream.start()
    except Exception as exc:
        if stream is not None:
            try:
                stream.close()
            except Exception:
                pass
        raise ScanError(f"can't open audio input {name!r} ({type(exc).__name__}: {exc}). "
                        f"{_listen.PERMISSION_HINT} {_listen.USB_HINT}") from None
    offset = _listen._stream_offset(stream)
    latency = getattr(stream, "latency", 0.0) or 0.0
    latency = float(latency[0] if isinstance(latency, (tuple, list)) else latency)
    opened = time.perf_counter()
    hits, waited, sounding = [], 0.0, None
    try:
        _wait(rec, name, opened + LEAD, opened)
        if not rec.blocks:
            raise ScanError(f"no audio arrived from {name!r}. {_listen.PERMISSION_HINT} {_listen.USB_HINT}")
        if _level_db(np, rec, sr, LEAD * 0.75) > QUIET_DBFS:
            raise ScanError("the unit is already making sound before any scan note: " + PATTERN_HINT + ". Nothing "
                            "was sent.")
        lead_end = time.perf_counter()
        for i, track in enumerate(order):
            if i:
                _wait(rec, name, hits[-1][1] + window, opened)
                fade_by = time.perf_counter() + TAIL_WAIT
                while _level_db(np, rec, sr) > QUIET_DBFS and time.perf_counter() < fade_by:
                    _wait(rec, name, time.perf_counter() + 0.02, opened)
                waited = max(waited, time.perf_counter() - hits[-1][1] - window)
            _note(engine, track, True, stops)
            sounding = track
            hits.append((track, time.perf_counter()))
            _wait(rec, name, hits[-1][1] + GATE, opened)
            _note(engine, track, False, stops)
            sounding = None
        _wait(rec, name, hits[-1][1] + window, opened)
        fade_by = time.perf_counter() + TAIL_WAIT
        while _level_db(np, rec, sr) > QUIET_DBFS and time.perf_counter() < fade_by:
            _wait(rec, name, time.perf_counter() + 0.02, opened)
        end = time.perf_counter() + _listen.LATENCY_MARGIN
        _wait(rec, name, end, opened)
    finally:
        if sounding is not None:
            try:
                engine.scan_note(sounding, False, stops, NOTE)
            except Exception:
                pass  # the port is gone; the next tool call reopens it and stop's panic covers the rest
        try:
            stream.stop()
            stream.close()
        except Exception:
            pass
    audio, t0 = _listen.assemble(np, rec.blocks, sr, offset, latency)
    rec.blocks = []
    _yield()
    lo = int(round((opened - t0) * sr))
    if lo < -int(0.05 * sr) or int(round((end - t0) * sr)) > len(audio) + int(0.05 * sr):
        raise ScanError(f"the audio from {name!r} doesn't cover the scan (input started late or dropped blocks); "
                        "scan again")
    times = [t for _, t in hits] + [end - _listen.LATENCY_MARGIN * 0.5]
    out = analyse(np, audio, sr, t0, hits, times, window, lead=(opened + 0.05, lead_end))
    out = {"device": name, "sample_rate": int(sr), "tracks_scanned": [t for t, _ in hits], **out}
    if skipped:
        out["skipped_muted"] = skipped
    if waited > 0.05:
        out["notes"].append(f"some tails rang past {window:g} s, so the next note waited up to {waited:.1f} s more")
    if any(t > 8 for t, _ in hits):
        out["channel_note"] = HIGH_TRACK_NOTE
    current = {t: e["label"] for t, e in engine.kit()["tracks"].items() if t in out["proposed"]}
    if current:
        out["current_labels"] = current
    out["applied"] = False
    out["confirm"] = CONFIRM
    out["note"] = NOTE_TEXT
    engine.record_scan({"at": time.time(), "proposed": out["proposed"], "applied": False})
    return out


# ---- analysis ------------------------------------------------------------------------------------------------

def analyse(np, audio, sr, t0, hits, times, window, lead=None):
    """Classify each hit. audio: frames x channels, sample 0 at perf time t0; hits: [(track, note-on time)];
    times: the note-on times plus an end time; lead: (start, end) of the quiet check before the first note."""
    audio = np.asarray(audio, dtype=np.float64)
    if audio.ndim == 1:
        audio = audio[:, None]

    def cut(a, b):
        i, j = max(0, int(round((a - t0) * sr))), max(0, int(round((b - t0) * sr)))
        return audio[i:j]

    proposed, features, flags, apply = {}, {}, {}, {}
    notes = []
    prev_rang = False
    for k, (track, at) in enumerate(hits):
        seg = cut(at, times[k + 1] - PRE)
        pre = cut(at - PRE_CHECK, at)
        f = hit_features(np, seg, sr)
        mine = []
        pre_db = _peak_db(np, pre)
        if pre_db > QUIET_DBFS:
            mine.append("tail_overlap" if prev_rang else "sound_before")
        if f.get("extra_hits"):
            mine.append("other_hits")
        label = classify(f)
        if mine:
            label["confidence"] = round(label["confidence"] * 0.5, 2)
            if label["label"] not in ("silent", "unknown") and label["confidence"] < UNKNOWN_BELOW:
                label = {"label": "unknown", "confidence": label["confidence"], "guess": label["label"]}
            flags[str(track)] = mine
        proposed[str(track)] = label
        features[str(track)] = [f.get(name) for name in FEATURES]
        if label.get("role"):
            apply[str(track)] = label["role"]
        elif label["label"] in LABELS:
            apply[str(track)] = label["label"]
        prev_rang = bool(f.get("sustained"))
        _yield()
    out = {"proposed": proposed, "features_keys": list(FEATURES), "features": features,
           "apply_with": {"tool": "whiplash_label_tracks", "tracks": apply}}
    silent = [int(t) for t, p in proposed.items() if p["label"] == "silent"]
    unsure = [int(t) for t, p in proposed.items() if p["label"] == "unknown"]
    if silent:
        notes.append(f"track(s) {silent} {SILENT_HINT}. Left out of apply_with.")
    if unsure:
        notes.append(f"track(s) {unsure}: no confident label (see guess); ask the user. Left out of apply_with.")
    stray = sorted(int(t) for t, fl in flags.items() if "sound_before" in fl or "other_hits" in fl)
    if lead is not None and _peak_db(np, cut(*lead)) > QUIET_DBFS:
        stray = sorted(set(stray) | {0})
    if flags:
        out["flags"] = flags
    if len(stray) >= 2 or 0 in stray:
        out["unexpected_audio"] = True
        notes.append(f"sound that no scan note made, around track(s) {[t for t in stray if t] or 'before the first'}: "
                     f"{PATTERN_HINT}. Treat these labels as unreliable.")
    elif stray:
        notes.append(f"track {stray[0]}: sound before or after its hit that it didn't make (an LFO, a retrig, or the "
                     "unit's own pattern); confidence halved")
    if any("tail_overlap" in fl for fl in flags.values()):
        notes.append("a long tail still rang into the next hit (tail_overlap); confidence halved there")
    out["notes"] = notes
    return out


def _peak_db(np, seg):
    if seg is None or not len(seg):
        return -120.0
    peak = float(np.abs(seg).max())
    return 20.0 * math.log10(peak) if peak > 0 else -120.0


def hit_features(np, seg, sr):
    """Features of one hit (frames x channels or mono): peak, onset latency, attack, decay to -20 dB, whether it
    still sounds at the end, spectral centroid and low-end share over its first 250 ms, pitchedness (peak of the
    normalised autocorrelation for 40 Hz-1 kHz) and its f0, and whether the envelope rose again (another hit)."""
    seg = np.asarray(seg, dtype=np.float64)
    peak_db = round(_peak_db(np, seg), 1)
    out = {"peak_dbfs": peak_db}
    if peak_db < HIT_SILENT_DBFS:
        out["silent"] = True
        return out
    x = seg.mean(axis=1) if seg.ndim == 2 else seg
    a = np.abs(x)
    onset = int(np.argmax(a >= 0.1 * a.max()))
    hop = max(1, int(round(0.005 * sr)))
    m = (len(x) - onset) // hop
    if m < 4:
        out["silent"] = True
        return out
    # RMS over 30 ms (so a 55 Hz cycle doesn't ripple it), every 5 ms from the onset
    span = int(0.03 * sr)
    sq = np.concatenate([[0.0], np.cumsum(x[onset:] ** 2)])
    idx = np.arange(m) * hop
    ends = np.minimum(idx + span, len(sq) - 1)
    env = np.sqrt((sq[ends] - sq[idx]) / np.maximum(1, ends - idx)) + 1e-12
    pk = int(np.argmax(env))
    env_db = 20.0 * np.log10(env / env[pk])
    after = env_db[pk:]
    last = pk + int(np.nonzero(after > -20.0)[0][-1])
    out["onset_ms"] = round(onset * 1000.0 / sr, 1)
    out["attack_ms"] = int(np.argmax(env_db > -3.0)) * 5  # to within 3 dB of the peak
    out["decay_ms"] = (last - pk) * 5
    out["hold_ms"] = int(np.argmax(np.concatenate([after, [-99.0]]) < -6.0)) * 5  # until 6 dB down: held or not
    out["sustained"] = bool((m - 1 - last) * 5 < 60)  # still within 20 dB of its peak at the end of the window
    # another hit inside this one's window: the envelope climbs 12 dB above its running minimum, past 60 ms
    run_min = np.minimum.accumulate(after)
    rise = (after - run_min > 12.0) & (after > -26.0) & (np.arange(len(after)) > 12)
    out["extra_hits"] = bool(rise.any())
    n = max(256, min(len(x) - onset, int(0.25 * sr)))
    chunk = x[onset:onset + n]
    chunk = np.pad(chunk, (0, n - len(chunk)))
    power = np.abs(np.fft.rfft(chunk * np.hanning(n))) ** 2
    freqs = np.fft.rfftfreq(n, 1.0 / sr)
    band = freqs > 20.0
    total = float(power[band].sum()) or 1e-20
    out["centroid_hz"] = int(round(float((freqs[band] * power[band]).sum()) / total))
    out["low_pct"] = round(100.0 * float(power[band & (freqs < _listen.KICK_HZ)].sum()) / total, 1)
    size = 4096 if sr <= 50000 else 8192
    start = onset + max(int(0.02 * sr), pk * hop - size // 2)
    frame = x[start:start + size]
    frame = np.pad(frame, (0, size - len(frame))) - (frame.mean() if len(frame) else 0.0)
    spec = np.abs(np.fft.rfft(frame, 2 * size)) ** 2
    ac = np.fft.irfft(spec)[:size]
    pitched, f0 = 0.0, None
    if ac[0] > 0:
        lo, hi = int(sr / 1000.0), min(int(sr / 40.0), size // 2)
        norm = ac[lo:hi] / ac[0] * (size / (size - np.arange(lo, hi)))
        best = float(norm.max())
        pitched = max(0.0, min(1.0, best))
        first = int(np.argmax(norm >= 0.9 * best))
        f0 = int(round(sr / (lo + first)))
    out["pitched"] = round(pitched, 2)
    out["f0_hz"] = f0 if pitched >= 0.5 else None
    return out


def _up(x, a, b):
    """0 at a, 1 at b, linear between (a > b falls instead)."""
    t = (x - a) / (b - a)
    return min(1.0, max(0.0, t))


def scores(f):
    """{label: 0-1} for one hit's features."""
    c, d, p, low, attack = f["centroid_hz"], f["decay_ms"], f["pitched"], f["low_pct"], f["attack_ms"]
    sustained, hold = f["sustained"], f["hold_ms"]
    rich = c / f["f0_hz"] if f.get("f0_hz") else 1.0  # centroid over f0: ~1 for a sine-like tom, 3+ for a saw
    long_ = 1.0 if sustained else _up(d, 300, 800)
    noisy, pitched = _up(p, 0.6, 0.3), _up(p, 0.3, 0.6)
    low_heavy, not_low = _up(low, 30, 60), _up(low, 50, 25)

    def shorter(a, b):
        return 0.0 if sustained else _up(d, a, b)

    return {
        "kick": low_heavy * _up(c, 600, 250) * shorter(900, 450) * _up(hold, 250, 120),
        "bass": low_heavy * pitched * max(long_, _up(hold, 120, 250)),
        "snare/clap": noisy * _up(c, 700, 1500) * _up(c, 7000, 4500) * shorter(800, 450),
        "hat": noisy * _up(c, 3500, 6000) * _up(low, 15, 3) * shorter(1500, 900),
        "perc": pitched * _up(c, 150, 300) * _up(c, 5000, 3000) * not_low * shorter(600, 300) * (0.5 + 0.5 * _up(rich, 3.0, 1.3)),
        "pad/chord": pitched * not_low * long_ * (0.4 + 0.6 * _up(attack, 15, 80)),
        "lead/stab": pitched * not_low * _up(attack, 80, 20) * (1.0 if sustained else _up(d, 100, 250))
                      * (0.5 + 0.5 * _up(rich, 1.2, 2.2)),
        "fx": noisy * long_,
    }


def classify(f):
    """One hit's features -> {"label", "role" (kit-map role, when it differs), "confidence"} (or "guess")."""
    if f.get("silent"):
        return {"label": "silent", "confidence": 1.0 if f["peak_dbfs"] < HIT_SILENT_DBFS - 10 else 0.7}
    s = scores(f)
    ranked = sorted(s.items(), key=lambda kv: -kv[1])
    (best, top), (_, second) = ranked[0], ranked[1]
    confidence = round(top * top / (top + second), 2) if top > 0 else 0.0
    if confidence < UNKNOWN_BELOW:
        return {"label": "unknown", "confidence": confidence, "guess": best}
    out = {"label": best, "confidence": confidence}
    role = {"snare/clap": "snare", "pad/chord": "pad", "hat": "closed hat" if f["decay_ms"] < 180 else "open hat",
            "lead/stab": "lead" if f["sustained"] or f["decay_ms"] >= 500 else "stab"}.get(best)
    if role:
        out["role"] = role
    return out
