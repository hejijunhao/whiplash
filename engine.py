"""Thread-safe MIDI sequencer for the Digitakt II.

mido is imported lazily so Hermes can load the plugin (register()) instantly.
Nothing here ever sends SysEx or program changes: Engine.send() refuses them.

Two locks: _transport serialises play/stop/shutdown (it is held while joining
the sequencer thread), _lock guards state and the port (the sequencer thread
takes it for every send). The sequencer thread never takes _transport.
"""
import atexit
import heapq
import logging
import threading
import time

from . import ccmap, patterns

log = logging.getLogger("whiplash")

DEVICE_HINTS = ("digitakt",)
VIRTUAL_NAME = "Whiplash"
TICKS_PER_STEP = 6  # 24 PPQN MIDI clock
GATE = 0.8
ALLOWED_TYPES = {"note_on", "note_off", "control_change", "clock", "start", "stop", "continue"}
BPM_MIN, BPM_MAX = 30, 300
BARS_MAX = 512
JOIN_TIMEOUT = 2.0
MUTE_CC = ccmap.PARAMS["mute"][0]


class WhiplashError(Exception):
    pass


def check_bpm(bpm):
    try:
        value = float(bpm)
    except (TypeError, ValueError):
        value = float("nan")
    if not BPM_MIN <= value <= BPM_MAX:  # also rejects NaN
        raise WhiplashError(f"bpm must be {BPM_MIN}-{BPM_MAX}, got {bpm!r}")
    return value


def check_bars(bars):
    if bars is None:
        return None
    try:
        value = float(bars)
        whole = value == int(value)
    except (TypeError, ValueError, OverflowError):  # not a number, NaN, or infinite
        value, whole = 0.0, False
    if not whole or not 1 <= value <= BARS_MAX:
        raise WhiplashError(f"bars must be a whole number 1-{BARS_MAX} (omit it to loop), got {bars!r}")
    return int(value)


def check_track(track):
    try:
        value = int(track)
    except (TypeError, ValueError):
        value = 0
    if not 1 <= value <= 16:
        raise WhiplashError(f"track must be 1-16, got {track!r}")
    return value


def _mido():
    try:
        import mido
        mido.set_backend("mido.backends.rtmidi", load=True)
        return mido
    except Exception as exc:  # ImportError or missing rtmidi backend
        raise WhiplashError(
            f"MIDI backend unavailable ({exc}). Install with: pip install mido python-rtmidi") from exc


def list_ports():
    mido = _mido()
    return {"outputs": mido.get_output_names(), "inputs": mido.get_input_names()}


def find_device(names):
    for name in names:
        if any(h in name.lower() for h in DEVICE_HINTS):
            return name
    return None


class Engine:
    def __init__(self, opener=None):
        self._lock = threading.RLock()
        self._transport = threading.RLock()
        self._opener = opener  # test hook: callable(port_name|None) -> (port, label, virtual)
        self._port = None
        self._exit_hooked = False
        self.port_name = None
        self.virtual = False
        self.fallback = False  # True when the virtual port was opened because no Digitakt was found
        self._thread = None
        self._stop = None  # per-run stop Event
        self._done = None  # per-run Event, set once the run has silenced the port itself
        self.pattern = None
        self.bpm = 120.0
        self.swing = 0.5
        self.muted = set()
        self.hw_muted = set()  # tracks whose mute Whiplash also set on the unit (CC 94)
        self.bars_total = None
        self.bar = 0
        self.last_error = None
        self._sounding = set()  # (channel, note)
        self.sent_count = 0

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

    def send(self, msg):
        if msg.type not in ALLOWED_TYPES:
            raise WhiplashError(f"refusing to send {msg.type} (Whiplash never sends SysEx/program changes)")
        with self._lock:
            if self._port is None:
                raise WhiplashError("no MIDI port open")
            self._port.send(msg)
            self.sent_count += 1

    def _cc(self, mido, ch, control, value):
        self.send(mido.Message("control_change", channel=ch, control=control, value=value))

    def _record(self, where, exc):
        with self._lock:
            if self.last_error is None:  # keep the first failure; later ones are usually fallout
                self.last_error = f"{where}: {type(exc).__name__}: {exc}"

    # ---- transport -----------------------------------------------------
    def playing(self):
        thread = self._thread
        return thread is not None and thread.is_alive()

    def play(self, pattern, bpm=None, bars=None, port=None, send_clock=True):
        """Start a pattern, replacing whatever is playing. Returns what stop() reported."""
        bpm = check_bpm(pattern.bpm if bpm is None else bpm)  # validate before touching the running beat
        bars = check_bars(bars)
        with self._transport:
            stopped = self.stop()
            self.ensure_port(port)
            with self._lock:
                self.pattern = pattern
                self.bpm = bpm
                self.swing = pattern.swing
                self.bars_total = bars
                self.bar = 0
                self.last_error = None
                self._stop, self._done = threading.Event(), threading.Event()
                self._thread = threading.Thread(
                    target=self._run, args=(send_clock, bars, self._stop, self._done),
                    name="whiplash-seq", daemon=True)
                self._thread.start()
            return stopped

    def stop(self):
        """Stop the sequencer, silence the port once, and reset mutes."""
        with self._transport:
            thread, stop, done = self._thread, self._stop, self._done
            self._thread = self._stop = self._done = None
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
                cleared = self._clear_mutes()
            return {"was_playing": was_playing, "mutes_cleared": cleared}

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

    def _run(self, send_clock, bars_total, stop, done):
        mido = __import__("mido")
        pending = []  # heap of (time, seq, ch, note, vel)
        seq = 0
        next_tick = time.perf_counter() + 0.01
        tick = 0
        try:
            self.send(mido.Message("start"))
            while not stop.is_set():
                with self._lock:
                    tick_len = 60.0 / self.bpm / 24
                    swing, pattern, muted = self.swing, self.pattern, set(self.muted)
                step_abs, sub = divmod(tick, TICKS_PER_STEP)
                bar_idx, step = divmod(step_abs, patterns.STEPS)
                if sub == 0 and step == 0:
                    if bars_total and bar_idx >= bars_total:
                        break
                    self.bar = bar_idx
                if sub == 0:
                    sixteenth = tick_len * TICKS_PER_STEP
                    t0 = next_tick + ((swing - 0.5) * 2 * sixteenth if step % 2 else 0)
                    for track, bars in pattern.bars.items():
                        if track in muted:
                            continue
                        for s, note, vel, gate in bars[bar_idx % patterns.BARS]:
                            if s == step:
                                ch = track - 1
                                heapq.heappush(pending, (t0, seq, ch, note, vel)); seq += 1
                                heapq.heappush(pending, (t0 + gate * sixteenth * GATE - 1e-4, seq, ch, note, 0)); seq += 1
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
                tick += 1
                next_tick += tick_len
            # flush note-offs that are still pending
            for _, _, ch, note, vel in sorted(pending):
                if vel == 0:
                    self._note(mido, ch, note, 0)
        except Exception as exc:
            log.exception("sequencer thread crashed")
            self._record("sequencer stopped", exc)
        finally:
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

    # ---- parameters ----------------------------------------------------
    def set_param(self, track, value, param=None, cc=None, nrpn=None):
        """Send one parameter change. Exactly one of param / cc / nrpn selects the target.

        param and cc take a 7-bit value (0-127). nrpn takes the full 14-bit value
        (0-16383), always split as MSB = value >> 7, LSB = value & 127.
        """
        mido = __import__("mido")
        track = check_track(track)
        ch = track - 1
        try:
            value = int(value)
        except (TypeError, ValueError):
            raise WhiplashError(f"value must be a whole number, got {value!r}") from None
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
                raise WhiplashError("that NRPN changes sample assignment and is blocked")
            if not 0 <= value <= 16383:
                raise WhiplashError("NRPN value must be 0-16383 (14-bit; a 7-bit amount v is v * 128)")
            hi, lo = value >> 7, value & 0x7F
            with self._lock:  # keep the four CCs together on the wire
                for control, v in ((99, msb), (98, lsb), (6, hi), (38, lo)):
                    self._cc(mido, ch, control, v)
            return {"track": track, "nrpn": [msb, lsb], "value": value, "data_msb": hi, "data_lsb": lo}
        if given == ["param"]:
            key = str(param).strip().lower().replace(" ", "_").replace("-", "_")
            if key not in ccmap.PARAMS:
                raise WhiplashError(f"unknown param {param!r}; known: {sorted(ccmap.PARAMS)}")
            cc, _, vmax = ccmap.PARAMS[key]
            if not 0 <= value <= vmax:
                raise WhiplashError(f"{key} value must be 0-{vmax}")
        try:
            cc = int(cc)
        except (TypeError, ValueError):
            raise WhiplashError(f"cc must be a whole number, got {cc!r}") from None
        if not 0 <= cc <= 119 or cc in ccmap.BLOCKED_CCS:
            raise WhiplashError(f"CC {cc} is not allowed (0-119, excluding sample select / NRPN / bank CCs)")
        if not 0 <= value <= 127:
            raise WhiplashError("CC value must be 0-127")
        self._cc(mido, ch, cc, value)
        if cc == MUTE_CC:  # track unit mutes set this way too, so stop/exit releases them
            with self._lock:
                (self.hw_muted.add if value else self.hw_muted.discard)(track)
        return {"track": track, "cc": cc, "value": value}

    def status(self):
        with self._lock:
            return {
                "playing": self.playing(), "port": self.port_name, "virtual": self.virtual,
                "fallback": self.fallback,
                "pattern": self.pattern.name if self.pattern else None, "bpm": self.bpm,
                "bar": self.bar, "bars": self.bars_total, "muted": sorted(self.muted),
                "hardware_muted": sorted(self.hw_muted), "last_error": self.last_error,
                "messages_sent": self.sent_count,
            }
