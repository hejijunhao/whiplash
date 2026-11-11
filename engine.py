"""Thread-safe MIDI sequencer for the Digitakt II.

mido is imported lazily so Hermes can load the plugin (register()) instantly.
Nothing here ever sends SysEx or program changes: Engine.send() refuses them.

Two locks: _transport serialises play/stop/shutdown (it is held while joining
the sequencer thread), _lock guards state and the port (the sequencer thread
takes it for every send). The sequencer thread never takes _transport and never
enumerates ports, so tool calls can't stall the clock.

Everything musical is timed off the sequencer's own MIDI clock: a live pattern
switch lands on the next bar line, drops and fills are bar-scheduled, and ramps
advance one step per clock tick.

Transport: by default a run sends MIDI Start, clock, and Stop. Start also starts the Digitakt's
own sequencer, so trigs stored in the pattern selected on the unit play on top of Whiplash.
send_transport=False (or WHIPLASH_SEND_TRANSPORT=0) sends clock only, and then never sends Stop
either, so Whiplash can't halt a pattern someone runs on the unit.
"""
import atexit
import collections
import os
import heapq
import logging
import threading
import time
from dataclasses import dataclass

from . import ccmap, mutate, patterns

log = logging.getLogger("whiplash")

DEVICE_HINTS = ("digitakt",)
VIRTUAL_NAME = "Whiplash"
PPQN = 24
TICKS_PER_STEP = 6  # 24 PPQN MIDI clock, 16th-note steps
TICKS_PER_BAR = TICKS_PER_STEP * patterns.STEPS
GATE = 0.8
ALLOWED_TYPES = {"note_on", "note_off", "control_change", "clock", "start", "stop", "continue"}
BPM_MIN, BPM_MAX = 30, 300
BARS_MAX = 512
RAMP_BEATS_MAX, RAMP_BARS_MAX = 512, 128
DROP_BARS_MAX = 32
TRANSPOSE_MAX = 48  # semitones either way (4 octaves); notes still clamp to the 16-84 chromatic range
TUNE_CC = ccmap.PARAMS["tune"].cc
SLOT_CC = ccmap.PARAMS["sample_slot"].cc
_NOT_PARAMS = {123, 6, 38, 98, 99}  # All Notes Off and NRPN data entry: never shown as a track's last_cc
KIT_NOTE = ("Track roles are the pattern's assumed layout, not what the unit holds: ask the user what each track "
            "plays. slot, tune and last_cc are the last values Whiplash sent (it can't read the unit; null = not "
            "sent yet).")
PITCH_NOTE = ("pitch: MIDI note 60 plays a sample at its own pitch (tune 64). semitones_from_native = note - 60 + "
              "(tune - 64), using the tune Whiplash last sent (null = not sent, counted as 64). Names use Elektron "
              "octaves (C5 = MIDI 60). A line far below native sounds stretched or grainy: raise it with "
              "whiplash_transpose (or tune) before touching the envelope.")
SWING_MIN, SWING_MAX = 50, 80
JOIN_TIMEOUT = 2.0
HOTPLUG_INTERVAL = 2.0  # seconds between port enumerations while on the virtual port
MUTE_CC = ccmap.MUTE_CC
TRANSPORT_ENV = "WHIPLASH_SEND_TRANSPORT"
_FALSE = {"0", "false", "no", "off", "clock_only", "clock-only"}
_TRUE = {"1", "true", "yes", "on", ""}
CURVES = {
    "linear": lambda p: p,
    "exp": lambda p: p ** 3,  # ease-in: slow start, fast finish (the classic filter sweep)
    "log": lambda p: 1 - (1 - p) ** 3,  # ease-out: fast start, settles gently
}


class WhiplashError(Exception):
    pass


def default_send_transport():
    """WHIPLASH_SEND_TRANSPORT default: unset/1/true -> send Start/Stop; 0/false/clock_only -> clock only."""
    raw = os.environ.get(TRANSPORT_ENV)
    if raw is None:
        return True
    value = raw.strip().lower()
    if value in _FALSE:
        return False
    if value not in _TRUE:
        log.warning("ignoring %s=%r (use 1 or 0); sending transport", TRANSPORT_ENV, raw)
    return True


def check_send_transport(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str) and value.strip().lower() in _FALSE | (_TRUE - {""}):
        return value.strip().lower() not in _FALSE
    raise WhiplashError(f"send_transport must be true or false, got {value!r}")


def transport_mode(send_transport):
    return "start_stop" if send_transport else "clock_only"


def _number(value):
    try:
        out = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return out


def check_bpm(bpm):
    value = _number(bpm)
    if not BPM_MIN <= value <= BPM_MAX:  # also rejects NaN
        raise WhiplashError(f"bpm must be {BPM_MIN}-{BPM_MAX}, got {bpm!r}")
    return value


def check_whole(value, low, high, what, hint=""):
    number = _number(value)
    if not (low <= number <= high and number == int(number)):  # NaN / inf fail the range test first
        raise WhiplashError(f"{what} must be a whole number {low}-{high}{hint}, got {value!r}")
    return int(number)


def check_bars(bars):
    if bars is None:
        return None
    return check_whole(bars, 1, BARS_MAX, "bars", " (omit it to loop)")


def check_track(track, high=16):
    try:
        value = int(track)
    except (TypeError, ValueError):
        value = 0
    if not 1 <= value <= high or isinstance(track, bool):
        raise WhiplashError(f"track must be 1-{high}, got {track!r}")
    return value


def check_transpose(value, what="transpose"):
    """Semitones for one track: a whole number within +-TRANSPOSE_MAX."""
    return check_whole(value, -TRANSPOSE_MAX, TRANSPOSE_MAX, what, " semitones")


def check_transpose_map(transpose):
    """{"6": -12, "7": 5} -> {6: -12, 7: 5}. None or {} -> {}."""
    if transpose in (None, {}):
        return {}
    if not isinstance(transpose, dict):
        raise WhiplashError('transpose must map track to semitones, e.g. {"6": -12, "7": 5}')
    return {check_track(t): check_transpose(v, f"transpose for track {t}") for t, v in transpose.items()}


def clamp_note(note):
    return min(patterns.NOTE_MAX, max(patterns.NOTE_MIN, note))


def check_tracks(tracks, high=8):
    if tracks is None or tracks == []:
        raise WhiplashError("give tracks, e.g. [1] or [1, 6]")
    items = tracks if isinstance(tracks, (list, tuple)) else [tracks]
    return sorted({check_track(t, high) for t in items})


def _mido():
    try:
        import mido
        mido.set_backend("mido.backends.rtmidi", load=True)
        return mido
    except Exception as exc:  # ImportError or missing rtmidi backend
        hint = "pip install mido python-rtmidi"
        if "libasound" in str(exc):
            hint = "install the ALSA runtime (e.g. apt install libasound2) for python-rtmidi"
        raise WhiplashError(f"MIDI backend unavailable ({exc}). Fix: {hint}") from exc


def list_ports():
    mido = _mido()
    return {"outputs": mido.get_output_names(), "inputs": mido.get_input_names()}


def find_device(names):
    for name in names:
        if name != VIRTUAL_NAME and any(h in name.lower() for h in DEVICE_HINTS):
            return name
    return None


@dataclass
class Ramp:
    id: str
    track: int
    cc: int
    label: str
    start: int
    end: int
    total: int  # clock ticks
    curve: str
    elapsed: int = 0
    last: int = None

    def progress(self):
        return min(1.0, self.elapsed / self.total)

    def value(self):
        return round(self.start + (self.end - self.start) * CURVES[self.curve](self.progress()))

    def summary(self):
        return {"id": self.id, "track": self.track, "param": self.label, "cc": self.cc, "from": self.start,
                "to": self.end, "current": self.last, "curve": self.curve, "progress": round(self.progress(), 3),
                "remaining_beats": round((self.total - self.elapsed) / PPQN, 2)}


class Engine:
    def __init__(self, opener=None, lister=None):
        self._lock = threading.RLock()
        self._transport = threading.RLock()
        self._opener = opener  # test hook: callable(port_name|None) -> (port, label, virtual)
        self._lister = lister if lister is not None else ((lambda: []) if opener else None)  # test hook
        self._port = None
        self._exit_hooked = False
        self.port_name = None
        self.virtual = False
        self.fallback = False  # True when the virtual port was opened because no Digitakt was found
        self.port_lost = None  # name of a port that failed mid-send (unplugged); reopened on next call
        self._hp_checked = float("-inf")
        self._hp_device = None
        self._thread = None
        self._stop = None  # per-run stop Event
        self._done = None  # per-run Event, set once the run has silenced the port itself
        self.pattern = None
        self.bpm = 120.0
        self.swing = 0.5
        self.muted = set()
        self.hw_muted = set()  # tracks whose mute Whiplash also set on the unit (CC 94)
        self.bars_total = None
        self.bar = 0  # bars since transport start
        self.pattern_start = 0  # bar where the current pattern took over
        self._queued = None  # pending live switch: {pattern, bpm, bars, at}
        self.last_error = None
        self._sounding = set()  # (channel, note)
        self._cc_values = {}  # (channel, cc) -> last value sent
        self._ramps = {}  # (track, cc) -> Ramp
        self._ramp_seq = 0
        self.seed = 0
        self._density = {}  # track -> amount
        self.humanize = 0.0
        self._work = {}  # working copy of the pattern (density applied)
        self._drops = {}  # track -> (first bar, end bar exclusive)
        self._transpose = {}  # track -> semitones, applied to note numbers at the bar line
        self._fills = {}  # bar -> set(tracks)
        self.sent_count = 0
        self.send_transport = None  # transport mode of the current/last run; None = env default
        # Published by the sequencer thread for the live view, read without any lock: each is
        # replaced by a single attribute assignment (atomic in CPython) and never mutated after.
        self.position = None  # (bar, step, perf_counter time the step's tick is due)
        self.bar_fills = (None, frozenset())
        self.bar_hits = None  # (bar, {step: [(track, note, vel, gate, offset)]}, fill tracks) for the bar now playing

    # ---- port handling -------------------------------------------------
    def ensure_port(self, port=None, allow_virtual=True):
        with self._lock:
            if self._port is not None and (port is None or port == self.port_name):
                return self.port_name
            self._close_port()
            if self._opener:
                self._port, self.port_name, self.virtual = self._opener(port)
            else:
                self._open(port, allow_virtual)
            self.fallback = bool(self.virtual and port != VIRTUAL_NAME)
            self.port_lost = None
            self._hp_checked, self._hp_device = float("-inf"), None
            if self.fallback:
                log.warning("No Digitakt found; MIDI goes to virtual output %r (hardware is silent)", VIRTUAL_NAME)
            if not self._exit_hooked:  # silence the unit and close the port when the host process exits
                atexit.register(self.shutdown)
                self._exit_hooked = True
            return self.port_name

    def _open(self, port, allow_virtual):
        mido = _mido()
        outputs = mido.get_output_names()
        if port == VIRTUAL_NAME and port not in outputs:
            target = None  # explicit request for the virtual port
        elif port:
            if port not in outputs:
                raise WhiplashError(f"MIDI output {port!r} not found. Available: {outputs or 'none'}")
            target = port
        else:
            target = find_device(outputs)
        if target:
            self._port, self.port_name, self.virtual = mido.open_output(target), target, False
        elif allow_virtual:
            self._port = mido.open_output(VIRTUAL_NAME, virtual=True)
            self.port_name, self.virtual = VIRTUAL_NAME, True
        else:
            raise WhiplashError(
                "Elektron Digitakt II not found over USB MIDI. Check the cable, power, and "
                f"SETTINGS > MIDI CONFIG > PORT CONFIG (USB). Outputs seen: {outputs or 'none'}")

    def _close_port(self):
        if self._port is not None:
            try:
                self._port.close()
            except Exception:
                log.exception("closing port")
        self._port, self.port_name, self.virtual, self.fallback = None, None, False, False
        self._cc_values.clear()  # values sent to one device say nothing about the next

    def check_hotplug(self):
        """While on the virtual port, return a Digitakt output that has appeared, else None.

        Enumerates ports at most every HOTPLUG_INTERVAL seconds, outside _lock, never raises.
        Notify only: Whiplash never moves the beat by itself.
        """
        if not self.virtual:
            return None
        now = time.monotonic()
        if now - self._hp_checked >= HOTPLUG_INTERVAL:
            self._hp_checked = now
            try:
                names = self._lister() if self._lister else _mido().get_output_names()
            except Exception:
                names = []
            self._hp_device = find_device(names)
        return self._hp_device

    def send(self, msg):
        if msg.type not in ALLOWED_TYPES:
            raise WhiplashError(f"refusing to send {msg.type} (Whiplash never sends SysEx/program changes)")
        with self._lock:
            if self._port is None:
                raise WhiplashError("no MIDI port open")
            try:
                self._port.send(msg)
            except Exception:
                # The device went away (USB unplugged). Drop the port so the next tool call
                # re-detects and reopens it instead of writing into a dead handle.
                lost = self.port_name
                self._close_port()
                self.port_lost = lost
                raise
            self.sent_count += 1

    def _cc(self, mido, ch, control, value):
        self.send(mido.Message("control_change", channel=ch, control=control, value=value))
        self._cc_values[(ch, control)] = value

    def _record(self, where, exc):
        with self._lock:
            if self.last_error is None:  # keep the first failure; later ones are usually fallout
                self.last_error = f"{where}: {type(exc).__name__}: {exc}"

    # ---- transport -----------------------------------------------------
    def playing(self):
        thread = self._thread
        return thread is not None and thread.is_alive()

    def transport_on(self):
        return default_send_transport() if self.send_transport is None else self.send_transport

    def play(self, pattern, bpm=None, bars=None, port=None, send_clock=True, send_transport=None, transpose=None):
        """Start a pattern, or queue a live switch to it at the next bar line.

        send_transport: True sends MIDI Start/Stop around the clock, False sends clock only,
        None keeps the running mode (or uses the WHIPLASH_SEND_TRANSPORT default on a fresh start).
        Returns {"mode": "queued", "switch_at_bar", "replaced_queued"} when a pattern is already
        playing on the same port in the same transport mode (clock keeps running; mutes and ramps
        carry over), else {"mode": "started", "was_playing", "mutes_cleared", "ramps_cancelled"}.
        Both carry "send_transport".
        transpose ({track: semitones}) applies from the first bar of a fresh start, or from the switch
        bar of a queued one, merged into the transposes already carried.
        """
        bpm = check_bpm(pattern.bpm if bpm is None else bpm)  # validate before touching the running beat
        bars = check_bars(bars)
        send_transport = check_send_transport(send_transport)
        transpose = check_transpose_map(transpose)
        with self._transport:
            same_mode = send_transport is None or send_transport == self.send_transport
            if (self.playing() and self._port is not None and (port is None or port == self.port_name)
                    and same_mode):
                with self._lock:
                    replaced = self._queued["pattern"].name if self._queued else None
                    at = self.bar + 1
                    self._queued = {"pattern": pattern, "bpm": bpm, "bars": bars, "at": at, "transpose": transpose}
                return {"mode": "queued", "switch_at_bar": at, "replaced_queued": replaced,
                        "send_transport": self.send_transport}
            if send_transport is None:
                send_transport = default_send_transport()
            stopped = self.stop()  # stops in the old mode (no Stop if the old run was clock-only)
            self.ensure_port(port)
            with self._lock:
                self.send_transport = send_transport
                self._load(pattern, bpm, bars, start_bar=0)
                self._transpose = {t: v for t, v in transpose.items() if v}
                self.bar = 0
                self.last_error = None
                self._stop, self._done = threading.Event(), threading.Event()
                self._thread = threading.Thread(
                    target=self._run, args=(send_clock, send_transport, self._stop, self._done),
                    name="whiplash-seq", daemon=True)
                self._thread.start()
            return {"mode": "started", "send_transport": send_transport, **stopped}

    def _load(self, pattern, bpm, bars, start_bar):
        """Make pattern current (caller holds _lock). Resets mutations, keeps mutes, ramps, drops."""
        self.pattern = pattern
        self.bpm = bpm
        self.swing = pattern.swing
        self.bars_total = bars
        self.pattern_start = start_bar
        self._density, self.humanize = {}, 0.0
        self._work = mutate.working(pattern)

    def stop(self):
        """Stop the sequencer, silence the port once, and reset mutes, ramps and mutations."""
        with self._transport:
            thread, stop, done = self._thread, self._stop, self._done
            self._thread = self._stop = self._done = None
            with self._lock:  # snapshot before the thread's own exit clears them
                ramps = sorted((r.id for r in self._ramps.values()), key=lambda i: int(i[1:]))
            was_playing = thread is not None and thread.is_alive()
            if stop is not None:
                stop.set()
            if was_playing and thread is not threading.current_thread():
                thread.join(timeout=JOIN_TIMEOUT)
            try:
                # A run that was just stopped silences the port itself on the way out; only
                # send the panic here when that did not happen (idle, or the thread is stuck).
                if self._port is not None and not (was_playing and done.is_set()):
                    self._panic()
            except Exception as exc:
                self._record("stop", exc)
                raise
            finally:
                with self._lock:
                    self._ramps.clear()
                    self._queued = None
                    self._drops, self._fills = {}, {}
                    self._transpose = {}
                    if self.pattern is not None:
                        self._load(self.pattern, self.bpm, self.bars_total, 0)
                cleared = self._clear_mutes()
            return {"was_playing": was_playing, "mutes_cleared": cleared, "ramps_cancelled": ramps}

    def shutdown(self):
        """Exit hook: stop, silence, release hardware mutes, close the port. Never raises."""
        try:
            self.stop()
        except Exception:
            log.exception("whiplash shutdown: stop failed")
        with self._lock:
            self._close_port()

    def _panic(self):
        mido = __import__("mido")
        with self._lock:
            for ch, note in list(self._sounding):
                self.send(mido.Message("note_off", channel=ch, note=note))
            self._sounding.clear()
            for ch in range(8):
                self._cc(mido, ch, 123, 0)
            if self.transport_on():  # clock-only runs never sent Start, so they never send Stop
                self.send(mido.Message("stop"))

    def set_tempo(self, bpm):
        bpm = check_bpm(bpm)
        with self._lock:
            self.bpm = bpm

    def set_mute(self, track, muted, hardware=False):
        """Mute/unmute a track. hardware=True also sets the unit's own track mute (CC 94).

        Unmuting always releases a hardware mute that Whiplash set, so the two never drift.
        """
        track = check_track(track)
        with self._lock:
            (self.muted.add if muted else self.muted.discard)(track)
            release = not muted and track in self.hw_muted
        if hardware or release:
            mido = __import__("mido")
            self.ensure_port()
            self._cc(mido, track - 1, MUTE_CC, 1 if muted else 0)
            with self._lock:
                (self.hw_muted.add if muted else self.hw_muted.discard)(track)

    def _clear_mutes(self):
        with self._lock:
            cleared, hardware = sorted(self.muted | self.hw_muted), sorted(self.hw_muted)
            self.muted, self.hw_muted = set(), set()
            if hardware and self._port is not None:
                mido = __import__("mido")
                for track in hardware:
                    try:
                        self._cc(mido, track - 1, MUTE_CC, 0)
                    except Exception as exc:
                        log.exception("releasing hardware mute on track %d", track)
                        self._record("unmute", exc)
        return cleared

    # ---- sequencer thread ----------------------------------------------
    def _bar_boundary(self, bar_n):
        """At the top of bar_n (caller holds _lock): switch, end check, build the bar's events.

        Returns None when the run should end, else {step: [(track, note, vel, gate, offset_ticks)]}.
        """
        queued = self._queued
        if queued and bar_n >= queued["at"]:
            self._queued = None
            self._load(queued["pattern"], queued["bpm"], queued["bars"], start_bar=bar_n)
            self._set_transposes(queued.get("transpose") or {})
            log.info("whiplash: switched to %s at bar %d", queued["pattern"].name, bar_n)
        if self.bars_total and bar_n - self.pattern_start >= self.bars_total:
            return None
        self.bar = bar_n
        for track, (_, end) in list(self._drops.items()):
            if end <= bar_n:
                del self._drops[track]  # auto-return
        for old in [b for b in self._fills if b < bar_n]:
            del self._fills[old]
        fills = self._fills.pop(bar_n, set())
        self.bar_fills = (bar_n, frozenset(fills))
        idx = (bar_n - self.pattern_start) % patterns.BARS
        r = mutate.rng(self.seed, "humanize", bar_n) if self.humanize else None
        events = collections.defaultdict(list)
        for track, bars in self._work.items():
            drop = self._drops.get(track)
            if drop and drop[0] <= bar_n:
                continue
            hits = mutate.fill(track, bars[idx]) if track in fills else bars[idx]
            shift = self._transpose.get(track, 0)
            for step, note, vel, gate, offset in hits:
                if r is not None:
                    vel, offset = mutate.humanize(vel, offset, self.humanize, r)
                if shift:
                    note = clamp_note(note + shift)
                events[step].append((track, note, vel, gate, offset))
        return events

    def _set_transposes(self, transpose):
        """Merge {track: semitones} into the live transposes (caller holds _lock); 0 removes one."""
        for track, semitones in transpose.items():
            if semitones:
                self._transpose[track] = semitones
            else:
                self._transpose.pop(track, None)

    def _run(self, send_clock, send_transport, stop, done):
        mido = __import__("mido")
        pending = []  # heap of (time, seq, ch, note, vel)
        seq = 0
        next_tick = time.perf_counter() + 0.01
        tick = 0
        events = {}
        try:
            if send_transport:
                self.send(mido.Message("start"))
            while not stop.is_set():
                step_abs, sub = divmod(tick, TICKS_PER_STEP)
                bar_n, step = divmod(step_abs, patterns.STEPS)
                with self._lock:
                    if sub == 0 and step == 0:
                        events = self._bar_boundary(bar_n)
                        if events is None:
                            break
                        self.bar_hits = (bar_n, events, self.bar_fills[1])
                    tick_len = 60.0 / self.bpm / PPQN
                    swing, muted = self.swing, set(self.muted)
                if sub == 0:
                    self.position = (bar_n, step, next_tick)  # for the view; one assignment, no lock
                    sixteenth = tick_len * TICKS_PER_STEP
                    t0 = next_tick + ((swing - 0.5) * 2 * sixteenth if step % 2 else 0)
                    for track, note, vel, gate, offset in events.get(step, ()):
                        if track in muted:
                            continue
                        ch, on = track - 1, t0 + offset * tick_len
                        heapq.heappush(pending, (on, seq, ch, note, vel)); seq += 1
                        heapq.heappush(pending, (on + gate * sixteenth * GATE - 1e-4, seq, ch, note, 0)); seq += 1
                # wait for the tick, flushing note events on time
                while True:
                    now = time.perf_counter()
                    while pending and pending[0][0] <= now:
                        _, _, ch, note, vel = heapq.heappop(pending)
                        self._note(mido, ch, note, vel)
                    if now >= next_tick or stop.is_set():
                        break
                    wake = min(next_tick, pending[0][0]) if pending else next_tick
                    time.sleep(max(0.0, min(wake - now, 0.002)))
                if send_clock:
                    self.send(mido.Message("clock"))
                self._advance_ramps(mido)
                tick += 1
                next_tick += tick_len
            # flush note-offs for notes still sounding (pending note-ons are simply dropped)
            for _, _, ch, note, vel in sorted(pending):
                if vel == 0 and (ch, note) in self._sounding:
                    self._note(mido, ch, note, 0)
        except Exception as exc:
            log.exception("sequencer thread crashed")
            self._record("sequencer stopped", exc)
        finally:
            self.position = self.bar_hits = None
            with self._lock:
                self._ramps.clear()  # ramps are clocked by this thread; they can't outlive it
                self._queued = None
            try:
                self._panic()
                done.set()
            except Exception as exc:
                log.exception("panic failed")
                self._record("panic", exc)

    def _note(self, mido, ch, note, vel):
        if vel:
            self.send(mido.Message("note_on", channel=ch, note=note, velocity=vel))
            self._sounding.add((ch, note))
        else:
            self.send(mido.Message("note_off", channel=ch, note=note))
            self._sounding.discard((ch, note))

    def _advance_ramps(self, mido):
        with self._lock:
            for key, ramp in list(self._ramps.items()):
                ramp.elapsed += 1
                value = ramp.value()
                if value != ramp.last:  # only on integer changes: no CC floods
                    self._cc(mido, ramp.track - 1, ramp.cc, value)
                    ramp.last = value
                if ramp.elapsed >= ramp.total:
                    del self._ramps[key]

    # ---- parameters ----------------------------------------------------
    def _target(self, param, cc):
        """Resolve exactly one of param / cc to (cc, Param or None)."""
        given = [k for k, v in (("param", param), ("cc", cc)) if v not in (None, "")]
        if len(given) != 1:
            raise WhiplashError(f"give exactly one of param or cc (got {', '.join(given) or 'none'})")
        if param not in (None, ""):
            try:
                spec = ccmap.lookup(param)
            except ValueError as exc:
                raise WhiplashError(str(exc)) from None
            return spec.cc, spec
        number = check_whole(cc, 0, 119, "cc")
        if number in ccmap.BLOCKED_CCS:
            raise WhiplashError(f"CC {number} is blocked (sample bank select, bank select, or NRPN/data entry)")
        if number in ccmap.NAMED_ONLY_CCS:
            name = ccmap.NAMED_ONLY_CCS[number]
            raise WhiplashError(f"CC {number} is only sent as the named param: use param={name!r} "
                                "(or whiplash_select_sample)")
        return number, None

    @staticmethod
    def _value(value, spec, what="value"):
        """Validate a 7-bit value for a CC target; clamp into a named param's range. -> (value, clamped)"""
        number = check_whole(value, 0, 127, what)
        if spec is None:
            return number, False
        if number < spec.min or number > spec.max:
            if spec.discrete:
                raise WhiplashError(f"{spec.name} {what} must be {spec.min}-{spec.max}, got {value!r}")
            return min(spec.max, max(spec.min, number)), True
        return number, False

    def set_param(self, track, value, param=None, cc=None, nrpn=None):
        """Send one parameter change. Exactly one of param / cc / nrpn selects the target.

        param and cc take a 7-bit value (0-127); named params clamp into their own range
        (e.g. tune 4-124). nrpn takes the full 14-bit value (0-16383), always split as
        MSB = value >> 7, LSB = value & 127. Cancels a running ramp on the same track/CC.
        """
        mido = __import__("mido")
        track = check_track(track)
        ch = track - 1
        given = [k for k, v in (("param", param), ("cc", cc), ("nrpn", nrpn)) if v not in (None, "")]
        if len(given) != 1:
            raise WhiplashError(f"give exactly one of param, cc or nrpn (got {', '.join(given) or 'none'})")
        if given == ["nrpn"]:
            try:
                msb, lsb = (int(x) for x in nrpn)
            except (TypeError, ValueError):
                raise WhiplashError("nrpn must be [msb, lsb]") from None
            if not (0 <= msb <= 127 and 0 <= lsb <= 127):
                raise WhiplashError("nrpn msb and lsb must each be 0-127")
            if (msb, lsb) in ccmap.BLOCKED_NRPNS:
                raise WhiplashError("that NRPN changes sample assignment and is blocked; use param='sample_slot' "
                                    "(or whiplash_select_sample) to pick a slot in the current bank")
            value = check_whole(value, 0, 16383, "NRPN value", " (14-bit; a 7-bit amount v is v * 128)")
            hi, lo = value >> 7, value & 0x7F
            with self._lock:  # keep the four CCs together on the wire
                for control, v in ((99, msb), (98, lsb), (6, hi), (38, lo)):
                    self._cc(mido, ch, control, v)
            return {"track": track, "nrpn": [msb, lsb], "value": value, "data_msb": hi, "data_lsb": lo}
        number, spec = self._target(param, cc)
        value, clamped = self._value(value, spec)
        with self._lock:
            ramp = self._ramps.pop((track, number), None)
            self._cc(mido, ch, number, value)
            if number == MUTE_CC:  # track unit mutes set this way too, so stop/exit releases them
                (self.hw_muted.add if value else self.hw_muted.discard)(track)
        out = {"track": track, "cc": number, "value": value}
        if spec is not None:
            out["param"] = spec.name
        if clamped:
            out["clamped"] = True
        if ramp is not None:
            out["cancelled_ramp"] = ramp.id
        return out

    def ramp(self, track, to, param=None, cc=None, start=None, beats=None, bars=None, curve="linear"):
        """Ramp a CC from start to `to` over beats or bars, advanced on the sequencer clock."""
        track = check_track(track)
        number, spec = self._target(param, cc)
        if spec is not None and spec.discrete:
            raise WhiplashError(f"{spec.name} is a switch; use whiplash_set_param")
        to, to_clamped = self._value(to, spec, "to")
        lengths = [k for k, v in (("beats", beats), ("bars", bars)) if v is not None]
        if len(lengths) != 1:
            raise WhiplashError("give exactly one of beats or bars")
        if beats is not None:
            amount = _number(beats)
            if not 0 < amount <= RAMP_BEATS_MAX:
                raise WhiplashError(f"beats must be above 0 and at most {RAMP_BEATS_MAX}, got {beats!r}")
            ticks = amount * PPQN
        else:
            amount = _number(bars)
            if not 0 < amount <= RAMP_BARS_MAX:
                raise WhiplashError(f"bars must be above 0 and at most {RAMP_BARS_MAX}, got {bars!r}")
            ticks = amount * TICKS_PER_BAR
        curve = str(curve or "linear").strip().lower()
        if curve not in CURVES:
            raise WhiplashError(f"curve must be one of {', '.join(CURVES)}, got {curve!r}")
        ch = track - 1
        label = spec.name if spec else f"cc {number}"
        mido = __import__("mido")
        with self._lock:
            if not self.playing():
                raise WhiplashError("ramps run on the sequencer clock: start a pattern with whiplash_play_pattern "
                                    "first, or use whiplash_set_param for an instant change")
            if start is None:
                start = self._cc_values.get((ch, number))
                if start is None:
                    raise WhiplashError(f"give 'from': Whiplash hasn't sent {label} on track {track} yet, so it "
                                        "doesn't know where to start")
                from_clamped = False
            else:
                start, from_clamped = self._value(start, spec, "from")
            replaced = self._ramps.pop((track, number), None)
            self._ramp_seq += 1
            ramp = Ramp(f"r{self._ramp_seq}", track, number, label, start, to, max(1, round(ticks)), curve)
            if self._cc_values.get((ch, number)) != start:
                self._cc(mido, ch, number, start)
            ramp.last = start
            self._ramps[(track, number)] = ramp
        out = {"ramp_id": ramp.id, **ramp.summary()}
        if replaced is not None:
            out["replaced"] = replaced.id
        if to_clamped or from_clamped:
            out["clamped"] = True
        return out

    def cancel_ramps(self, which):
        """Cancel one ramp by id, or all with "all". The parameter stays where the ramp left it."""
        with self._lock:
            if str(which).strip().lower() == "all":
                ids = sorted(r.id for r in self._ramps.values())
                self._ramps.clear()
                return ids
            for key, ramp in list(self._ramps.items()):
                if ramp.id == which:
                    del self._ramps[key]
                    return [ramp.id]
            active = sorted(r.id for r in self._ramps.values())
        raise WhiplashError(f"no active ramp {which!r}; active: {active or 'none'}")

    def ramps(self):
        with self._lock:
            return [r.summary() for r in sorted(self._ramps.values(), key=lambda r: int(r.id[1:]))]

    # ---- live mutations ------------------------------------------------
    def _require_playing(self):
        if not self.playing():
            raise WhiplashError("nothing is playing: start a pattern with whiplash_play_pattern first")

    def mutate_density(self, tracks, amount):
        if isinstance(amount, str):
            word = amount.strip().lower()
            if word not in mutate.DENSITY_WORDS:
                raise WhiplashError(f"amount must be -1..1 or one of {', '.join(mutate.DENSITY_WORDS)}")
            amount = mutate.DENSITY_WORDS[word]
        amount = _number(amount)
        if not -1 <= amount <= 1:
            raise WhiplashError("density amount must be -1 (thinnest) .. 0 (original) .. 1 (busiest)")
        tracks = check_tracks(tracks)
        with self._lock:
            self._require_playing()
            for track in tracks:
                pristine = mutate.working(self.pattern)[track]
                self._density[track] = amount
                self._work[track] = mutate.density(pristine, amount, self.seed, track)
            return {"density": {str(t): a for t, a in sorted(self._density.items())}, "applies": "next bar"}

    def mutate_swing(self, amount):
        value = _number(amount)
        if not SWING_MIN <= value <= SWING_MAX:
            raise WhiplashError(f"swing must be {SWING_MIN}-{SWING_MAX} (percent, like the unit's SWING)")
        with self._lock:
            self._require_playing()
            self.swing = value / 100
            return {"swing": value, "applies": "next step"}

    def mutate_humanize(self, amount):
        value = _number(amount)
        if not 0 <= value <= 1:
            raise WhiplashError("humanize amount must be 0 (off) to 1 (loosest)")
        with self._lock:
            self._require_playing()
            self.humanize = value
            return {"humanize": value, "applies": "next bar",
                    "max_velocity_change": round(value * mutate.HUMANIZE_VEL),
                    "max_timing_ticks": round(value * mutate.HUMANIZE_TICKS, 3)}

    def schedule_fill(self, tracks=None):
        tracks = check_tracks(tracks if tracks is not None else list(mutate.DRUM_TRACKS), high=8)
        if any(t not in mutate.DRUM_TRACKS for t in tracks):
            raise WhiplashError("fills work on drum tracks 1-5 (kick, snare/rim, clap, closed hat, open hat)")
        with self._lock:
            self._require_playing()
            at = self.bar + 1
            self._fills.setdefault(at, set()).update(tracks)
            return {"fill_at_bar": at, "tracks": tracks}

    def schedule_drop(self, tracks, bars, fill=False):
        tracks = check_tracks(tracks)
        bars = check_whole(bars, 1, DROP_BARS_MAX, "drop bars")
        with self._lock:
            self._require_playing()
            first = self.bar + 1
            end = first + bars
            for track in tracks:
                self._drops[track] = (first, end)
            out = {"dropped": tracks, "from_bar": first, "returns_at_bar": end}
            if fill:
                fill_tracks = [t for t in mutate.DRUM_TRACKS if t not in tracks]
                if fill_tracks:
                    self._fills.setdefault(end - 1, set()).update(fill_tracks)
                    out.update(fill_at_bar=end - 1, fill_tracks=fill_tracks)
            return out

    def reset_mutations(self):
        with self._lock:
            self._require_playing()
            self._drops, self._fills = {}, {}
            self._load(self.pattern, self.bpm, self.bars_total, self.pattern_start)
            return {"reset": True, "swing": round(self.swing * 100), "applies": "next bar"}

    def set_transpose(self, track, semitones=None, octaves=None):
        """Transpose one track's notes from the next bar line. Absolute: 0 puts it back.

        Carries across live pattern switches like mutes; whiplash_stop and a fresh start reset it.
        """
        track = check_track(track)
        given = [k for k, v in (("semitones", semitones), ("octaves", octaves)) if v not in (None, "")]
        if len(given) != 1:
            raise WhiplashError(f"give exactly one of semitones or octaves (got {', '.join(given) or 'none'})")
        if octaves not in (None, ""):
            octs = check_whole(octaves, -TRANSPOSE_MAX // 12, TRANSPOSE_MAX // 12, "octaves")
            value = octs * 12
        else:
            value = check_transpose(semitones, "semitones")
        with self._lock:
            if not self.playing():
                raise WhiplashError("nothing is playing: start a pattern first, or pass transpose to "
                                    'whiplash_play_pattern (e.g. {"6": 12})')
            previous = self._transpose.get(track, 0)
            self._set_transposes({track: value})
            out = {"track": track, "transpose": value, "previous": previous, "applies": "next bar",
                   "at_bar": self.bar + 1, "all": {str(t): v for t, v in sorted(self._transpose.items())}}
            pitch = self._pitch(track, self._work.get(track), value, self.pattern)
            if pitch:
                out["pitch"] = pitch
            if self._queued:
                out["note"] = (f"carries into the queued switch to {self._queued['pattern'].name} at bar "
                               f"{self._queued['at']}")
            return out

    def _pitch(self, track, bars, transpose, pattern):
        """Pitch summary for one track (caller holds _lock), or None for an unpitched drum part."""
        tune = self._cc_values.get((track - 1, TUNE_CC))
        if not bars or not any(bars):
            return None
        if not (patterns.is_melodic(bars) or transpose or tune is not None):
            return None
        raw = [n + transpose for n in patterns.notes_of(bars)]
        low, high = clamp_note(min(raw)), clamp_note(max(raw))
        offset = (tune - 64) if tune is not None else 0
        out = {"low": low, "high": high, "low_name": patterns.note_name(low), "high_name": patterns.note_name(high),
               "semitones_from_native": [low - patterns.NATIVE + offset, high - patterns.NATIVE + offset],
               "transpose": transpose, "tune": tune}
        shift = pattern.shifts.get(track) if pattern is not None else None
        if shift:
            out["register_shift"] = shift
        if min(raw) < patterns.NOTE_MIN or max(raw) > patterns.NOTE_MAX:
            out["clamped"] = True
        return out

    def tracks_summary(self, pattern=None, transpose=None):
        """Per-track summary for status and play results. pattern/transpose default to what is playing."""
        with self._lock:
            current = pattern is None
            pattern = self.pattern if current else pattern
            work = self._work if current else mutate.working(pattern)
            transpose = dict(self._transpose) if transpose is None else transpose
            last = collections.defaultdict(dict)
            for (ch, control), value in self._cc_values.items():
                if control not in _NOT_PARAMS:
                    spec = ccmap.BY_CC.get(control)
                    last[ch + 1][spec.name if spec else f"cc {control}"] = value
            roles = pattern.roles if pattern is not None else {}
            in_use = {t for t, bars in work.items() if any(bars)} | set(last) | set(transpose)
            in_use |= self.muted | self.hw_muted
            out = {}
            for track in sorted(in_use):
                role = roles.get(track)
                cc = last.get(track, {})
                out[str(track)] = {
                    "role": f"{role} (assumed)" if role else None,
                    "slot": cc.get("sample_slot"), "tune": cc.get("tune"),
                    "transpose": transpose.get(track, 0),
                    "pitch": self._pitch(track, work.get(track), transpose.get(track, 0), pattern),
                    "muted": track in self.muted or track in self.hw_muted,
                    "part": "generated" if work.get(track) and any(work[track]) else None,
                    "last_cc": {k: v for k, v in cc.items() if k not in ("sample_slot", "tune")},
                }
            return out

    def mutations(self):
        with self._lock:
            return {"density": {str(t): a for t, a in sorted(self._density.items())},
                    "swing": round(self.swing * 100, 1), "humanize": self.humanize,
                    "drops": {str(t): {"from_bar": a, "returns_at_bar": b} for t, (a, b) in sorted(self._drops.items())},
                    "fills_at_bars": {str(b): sorted(ts) for b, ts in sorted(self._fills.items())}}

    def status(self):
        with self._lock:
            queued = self._queued
            return {
                "playing": self.playing(), "port": self.port_name, "virtual": self.virtual,
                "fallback": self.fallback, "port_lost": self.port_lost,
                "send_transport": self.transport_on(), "transport_mode": transport_mode(self.transport_on()),
                "pattern": self.pattern.name if self.pattern else None, "bpm": self.bpm,
                "bar": self.bar, "pattern_bar": self.bar - self.pattern_start, "bars": self.bars_total,
                "queued": ({"pattern": queued["pattern"].name, "bpm": queued["bpm"], "switch_at_bar": queued["at"],
                            "transpose": {str(t): v for t, v in sorted((queued.get("transpose") or {}).items())}}
                           if queued else None),
                "transpose": {str(t): v for t, v in sorted(self._transpose.items())},
                "tracks": self.tracks_summary(), "roles_assumed": True, "kit_note": KIT_NOTE,
                "pitch_note": PITCH_NOTE,
                "muted": sorted(self.muted), "hardware_muted": sorted(self.hw_muted),
                "ramps": [r.summary() for r in sorted(self._ramps.values(), key=lambda r: int(r.id[1:]))],
                "mutations": self.mutations(),
                "last_error": self.last_error, "messages_sent": self.sent_count,
            }

    def view_state(self):
        """Raw copies of everything the live view shows. Holds _lock only to copy references.

        Read-only: never sends, never waits on the sequencer. The pattern, working bars and ramp
        summaries are immutable or rebuilt on change, so shallow copies are safe outside the lock.
        """
        with self._lock:
            return {
                "playing": self.playing(), "port": self.port_name, "virtual": self.virtual,
                "fallback": self.fallback, "port_lost": self.port_lost, "last_error": self.last_error,
                "pattern": self.pattern, "bpm": self.bpm, "swing": self.swing, "bar": self.bar,
                "pattern_start": self.pattern_start, "bars": self.bars_total,
                "queued": dict(self._queued) if self._queued else None,
                "muted": set(self.muted), "hw_muted": set(self.hw_muted),
                "ramps": [r.summary() for r in sorted(self._ramps.values(), key=lambda r: int(r.id[1:]))],
                "density": dict(self._density), "humanize": self.humanize, "work": dict(self._work),
                "drops": dict(self._drops), "fills": {b: set(t) for b, t in self._fills.items()},
                "transpose": dict(self._transpose),
                "cc_values": dict(self._cc_values), "messages_sent": self.sent_count,
                "position": self.position, "bar_hits": self.bar_hits,
                "transport_mode": transport_mode(self.transport_on()),
            }
