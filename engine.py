"""Thread-safe MIDI sequencer for the Digitakt II.

mido is imported lazily so Hermes can load the plugin (register()) instantly.
Nothing here ever sends SysEx or program changes: Engine.send() refuses them.
"""
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


class WhiplashError(Exception):
    pass


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
        self._opener = opener  # test hook: callable(port_name|None) -> (port, label, virtual)
        self._port = None
        self.port_name = None
        self.virtual = False
        self._thread = None
        self._stop = threading.Event()
        self.pattern = None
        self.bpm = 120.0
        self.swing = 0.5
        self.muted = set()
        self.bars_total = None
        self.bar = 0
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
                return self.port_name
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
            if target and not (port == VIRTUAL_NAME):
                self._port, self.port_name, self.virtual = mido.open_output(target), target, False
            elif allow_virtual:
                self._port = mido.open_output(VIRTUAL_NAME, virtual=True)
                self.port_name, self.virtual = VIRTUAL_NAME, True
                log.info("No Digitakt found; opened virtual output %r", VIRTUAL_NAME)
            else:
                raise WhiplashError(
                    "Elektron Digitakt II not found over USB MIDI. Check the cable, power, and "
                    f"SETTINGS > MIDI CONFIG > PORT CONFIG (USB). Outputs seen: {outputs or 'none'}")
            return self.port_name

    def _close_port(self):
        if self._port is not None:
            try:
                self._port.close()
            except Exception:
                log.exception("closing port")
        self._port = None

    def send(self, msg):
        if msg.type not in ALLOWED_TYPES:
            raise WhiplashError(f"refusing to send {msg.type} (Whiplash never sends SysEx/program changes)")
        with self._lock:
            if self._port is None:
                raise WhiplashError("no MIDI port open")
            self._port.send(msg)
            self.sent_count += 1

    # ---- transport -----------------------------------------------------
    def playing(self):
        return self._thread is not None and self._thread.is_alive()

    def play(self, pattern, bpm=None, bars=None, port=None, send_clock=True):
        self.stop()
        self.ensure_port(port)
        with self._lock:
            self.pattern = pattern
            self.bpm = float(bpm or pattern.bpm)
            self.swing = pattern.swing
            self.bars_total = bars
            self.bar = 0
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, args=(send_clock,), name="whiplash-seq", daemon=True)
            self._thread.start()

    def stop(self):
        thread = self._thread
        self._stop.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2)
        self._thread = None
        if self._port is not None:
            self._panic()

    def _panic(self):
        mido = __import__("mido")
        with self._lock:
            for ch, note in list(self._sounding):
                self.send(mido.Message("note_off", channel=ch, note=note))
            self._sounding.clear()
            for ch in range(8):
                self.send(mido.Message("control_change", channel=ch, control=123, value=0))
            self.send(mido.Message("stop"))

    def set_tempo(self, bpm):
        bpm = float(bpm)
        if not 30 <= bpm <= 300:
            raise WhiplashError("bpm must be 30-300")
        with self._lock:
            self.bpm = bpm

    def set_mute(self, track, muted):
        with self._lock:
            (self.muted.add if muted else self.muted.discard)(track)

    def _run(self, send_clock):
        mido = __import__("mido")
        pending = []  # heap of (time, seq, msg)
        seq = 0
        next_tick = time.perf_counter() + 0.01
        tick = 0
        try:
            self.send(mido.Message("start"))
            while not self._stop.is_set():
                with self._lock:
                    tick_len = 60.0 / self.bpm / 24
                    swing, pattern, muted = self.swing, self.pattern, set(self.muted)
                step_abs, sub = divmod(tick, TICKS_PER_STEP)
                bar_idx, step = divmod(step_abs, patterns.STEPS)
                if sub == 0 and step == 0:
                    if self.bars_total and bar_idx >= self.bars_total:
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
                    if now >= next_tick or self._stop.is_set():
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
        except Exception:
            log.exception("sequencer thread crashed")
        finally:
            try:
                self._panic()
            except Exception:
                log.exception("panic failed")

    def _note(self, mido, ch, note, vel):
        if vel:
            self.send(mido.Message("note_on", channel=ch, note=note, velocity=vel))
            self._sounding.add((ch, note))
        else:
            self.send(mido.Message("note_off", channel=ch, note=note))
            self._sounding.discard((ch, note))

    # ---- parameters ----------------------------------------------------
    def set_param(self, track, value, param=None, cc=None, nrpn=None):
        mido = __import__("mido")
        if not 1 <= int(track) <= 16:
            raise WhiplashError("track must be 1-16")
        ch = int(track) - 1
        value = int(value)
        if param:
            key = str(param).strip().lower().replace(" ", "_").replace("-", "_")
            if key not in ccmap.PARAMS:
                raise WhiplashError(f"unknown param {param!r}; known: {sorted(ccmap.PARAMS)}")
            cc, _, vmax = ccmap.PARAMS[key]
            if not 0 <= value <= vmax:
                raise WhiplashError(f"{key} value must be 0-{vmax}")
        if nrpn is not None:
            msb, lsb = (int(x) for x in nrpn)
            if (msb, lsb) in ccmap.BLOCKED_NRPNS:
                raise WhiplashError("that NRPN changes sample assignment and is blocked")
            if not 0 <= value <= 16383:
                raise WhiplashError("NRPN value must be 0-16383")
            hi, lo = (value >> 7, value & 127) if value > 127 else (value, 0)
            for control, v in ((99, msb), (98, lsb), (6, hi), (38, lo)):
                self.send(mido.Message("control_change", channel=ch, control=control, value=v))
            return {"track": int(track), "nrpn": [msb, lsb], "value": value}
        if cc is None:
            raise WhiplashError("give param, cc or nrpn")
        cc = int(cc)
        if not 0 <= cc <= 119 or cc in ccmap.BLOCKED_CCS:
            raise WhiplashError(f"CC {cc} is not allowed (0-119, excluding sample select / NRPN / bank CCs)")
        if not 0 <= value <= 127:
            raise WhiplashError("CC value must be 0-127")
        self.send(mido.Message("control_change", channel=ch, control=cc, value=value))
        return {"track": int(track), "cc": cc, "value": value}

    def status(self):
        with self._lock:
            return {
                "playing": self.playing(), "port": self.port_name, "virtual": self.virtual,
                "pattern": self.pattern.name if self.pattern else None, "bpm": self.bpm,
                "bar": self.bar, "bars": self.bars_total, "muted": sorted(self.muted),
                "messages_sent": self.sent_count,
            }
