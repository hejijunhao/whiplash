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

from . import ccmap, harmony, kitmap, mutate, parts, patterns

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
AMP_MODE_CC = ccmap.PARAMS["amp_mode"].cc
SLOT_CC = ccmap.PARAMS["sample_slot"].cc
HOLD_CC = ccmap.PARAMS["amp_hold"].cc
HOLD_NOTE = 127  # amp_hold 127 = HOLD NOTE, a mode switch (manual 11.7 p. 56; midi.guide): never reached by clamp or ramp
HOLD_NOTE_INFO = {"hold": "NOTE", "meaning": "HOLD = NOTE (AHD mode): the hold lasts from note-on to note-off, so "
                                            "note length is audible",
                  "warning": "this changes the track's sound in the unit's kit until it is reloaded; tell the user"}
HOLD_RAMP_NOTE = ("amp_hold ramps stop at 126: 127 is HOLD = NOTE, a mode switch, not the top of the range. Set it "
                  "with whiplash_set_param amp_hold 'note' if the user wants it.")
ALL_NOTES_OFF = 123
LOW_CHANNELS = frozenset(range(8))  # channels 1-8 always get All Notes Off on panic
_NOT_PARAMS = {123, 6, 38, 98, 99}  # All Notes Off and NRPN data entry: never shown as a track's last_cc
KIT_NOTE = ("Track roles marked (assumed) are the pattern's layout, not what the unit holds: ask the user what each "
            "track plays and record it with whiplash_label_tracks. slot, tune and last_cc are the last values "
            "Whiplash sent (it can't read the unit; null = not sent yet).")
KIT_LABELLED_NOTE = ("Roles without (assumed) come from the user's labels (whiplash_label_tracks); generated parts "
                     "follow them. Whiplash can't read the unit, so the labels are only as right as the user's "
                     "description. slot, tune and last_cc are the last values Whiplash sent (null = not sent yet).")
SETUP_KEYS = ("slot", "tune", "transpose", "mute")
PITCH_NOTE = ("pitch: MIDI note 60 plays a sample at its own pitch, if tune is 64 and the preset's OCTAVE (FUNC+FLTR "
              "> TRACK) is unchanged. semitones_from_native = note - 60 + (tune - 64), using the tune Whiplash last "
              "sent (null = not sent, counted as 64); Whiplash can't see the OCTAVE setting or an LFO on tune. "
              "Names use Elektron octaves (0 = C0, C5 = MIDI 60). A line far below native sounds stretched or "
              "grainy: raise it with whiplash_transpose (or tune) before touching the envelope.")
LENGTH_NOTE = ("length_audible: length sets the exact MIDI note-off, but the Digitakt only ends a sound on note-off "
               "when the track's AMP MODE is ADSR (amp_mode 1, CC 87) or, in AHD, HOLD is NOTE (amp_hold 127, CC 80). "
               "With a fixed HOLD (0-126) every hit sounds the same length, and a long DECAY still rings after "
               "note-off. Whiplash can't read the unit's envelope: ask the user, or pass envelope: 'note' to set "
               "HOLD = NOTE on this track (it changes the kit's sound until reloaded; tell the user).")
HIGH_TRACK_NOTE = ("Tracks 9-16 play on MIDI channels 9-16. If the unit's AUTO CHANNEL or FX CONTROL CH is set to "
                   "this channel (SETTINGS > MIDI CONFIG > CHANNELS), these notes and CCs also reach the active "
                   "track or the send FX. Ask the user to check.")
ENVELOPES = {"note"}
CURRENT_KEY = {"current", "session", "playing"}  # write_part key: use the key the beat is playing in
POLY_NOTE = ("chords mode plays one chord tone per hit, and each chord track starts on a different tone, so it works "
             "on a track that plays one note at a time. The manual gives the Digitakt II 16 audio voices for 16 "
             "tracks and documents chords only on MIDI tracks, so a stacked chord on an audio track probably "
             "sounds only one note (not yet checked on hardware). Use stack only for a MIDI track or a polyphonic "
             "target.")
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


def check_flag(value, what):
    if value in (None, "", False):
        return False
    if value is True or (isinstance(value, str) and value.strip().lower() in ("true", "1", "yes")):
        return True
    if isinstance(value, str) and value.strip().lower() in ("false", "0", "no"):
        return False
    raise WhiplashError(f"{what} must be true or false, got {value!r}")


def _is_hold_note(value):
    """amp_hold's explicit HOLD = NOTE request: the word 'note' or exactly 127."""
    if isinstance(value, str) and value.strip().lower() == "note":
        return True
    return not isinstance(value, bool) and _number(value) == HOLD_NOTE


def check_envelope(value):
    if value in (None, "") or (isinstance(value, str) and value.strip().lower() in ("keep", "none")):
        return None
    word = str(value).strip().lower()
    if word not in ENVELOPES:
        raise WhiplashError(f"envelope must be 'note' (sends amp_hold 127 = HOLD NOTE, CC 80) or omitted, got {value!r}")
    return word


def check_key(key, scale=None):
    """play_pattern / set_progression key -> harmony.Key, or None when no key is given."""
    if key in (None, ""):
        if scale not in (None, ""):
            raise WhiplashError("scale needs a key, e.g. key: 'A', scale: 'minor'")
        return None
    try:
        return harmony.parse_key(key, scale)
    except harmony.HarmonyError as exc:
        raise WhiplashError(str(exc)) from None


def check_setup(tracks):
    """play_pattern's tracks: {"6": {"slot": 9, "tune": 64, "transpose": -12, "mute": false}} -> {6: {...}}.

    Validates everything; slot is a whole 0-127 and tune clamps into its named range like whiplash_set_param.
    """
    if tracks in (None, {}):
        return {}
    if not isinstance(tracks, dict):
        raise WhiplashError('tracks must map track to settings, e.g. {"6": {"slot": 9, "transpose": 12}}')
    out = {}
    for raw, entry in tracks.items():
        track = check_track(raw)
        if not isinstance(entry, dict):
            raise WhiplashError(f'track {raw}: give an object like {{"slot": 9, "tune": 64}}, got {entry!r}')
        unknown = sorted(set(entry) - set(SETUP_KEYS))
        if unknown:
            raise WhiplashError(f"track {track}: unknown setting(s) {unknown}; use {', '.join(SETUP_KEYS)}")
        setup = {}
        if entry.get("slot") is not None:
            setup["slot"] = check_whole(entry["slot"], 0, 127, f"slot for track {track}")
        if entry.get("tune") is not None:
            spec = ccmap.PARAMS["tune"]
            tune = check_whole(entry["tune"], 0, 127, f"tune for track {track}", " (64 = no shift)")
            setup["tune"] = min(spec.max, max(spec.min, tune))
            if setup["tune"] != tune:
                setup["tune_clamped"] = True
        if entry.get("transpose") is not None:
            setup["transpose"] = check_transpose(entry["transpose"], f"transpose for track {track}")
        if entry.get("mute") is not None:
            setup["mute"] = check_flag(entry["mute"], f"mute for track {track}")
        if setup:
            out[track] = setup
    return out


def setup_ccs(setup):
    """[(track, cc, value)] for the slot and tune settings, slot first (a new sample, then its tune)."""
    out = []
    for track, entry in sorted(setup.items()):
        if "slot" in entry:
            out.append((track, SLOT_CC, entry["slot"]))
        if "tune" in entry:
            out.append((track, TUNE_CC, entry["tune"]))
    return out


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
        self.pattern = None  # the playing pattern, routed onto the kit map
        self._raw_pattern = None  # the same pattern as generated, before routing
        self._kit_tracks = {}  # track -> (role, label) from whiplash_label_tracks; survives stop and switches
        self._kit_slots = {}  # slot -> label
        self._kit_dirty = False  # labels changed while playing: re-route at the next bar line
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
        self._note_channels = set()  # channels with a note-on since the last panic (adds 9-16 to All Notes Off)
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
        self._parts = {}  # track -> parts.Part written with whiplash_write_part; merged into _work by _load
        self._bar_exact = frozenset()  # tracks whose lengths are exact note-offs in the bar being built
        self._key = None  # harmony.Key set by play_pattern(key) or a progression; None = each pattern's home key
        self._prog = None  # harmony.Progression; carries across switches, cleared by stop
        self._prog_modes, self._prog_ranks, self._prog_pads = {}, {}, frozenset()
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

    def play(self, pattern, bpm=None, bars=None, port=None, send_clock=True, send_transport=None, transpose=None,
             tracks=None, key=None, scale=None):
        """Start a pattern, or queue a live switch to it at the next bar line.

        send_transport: True sends MIDI Start/Stop around the clock, False sends clock only,
        None keeps the running mode (or uses the WHIPLASH_SEND_TRANSPORT default on a fresh start).
        Returns {"mode": "queued", "switch_at_bar", "replaced_queued"} when a pattern is already
        playing on the same port in the same transport mode (clock keeps running; mutes and ramps
        carry over), else {"mode": "started", "was_playing", "mutes_cleared", "ramps_cancelled"}.
        Both carry "send_transport".
        key/scale move the pattern's melodic tracks into that key (harmony.in_key) from the first bar, or from
        the switch bar; without one, a key set earlier in the run (or a progression's) still applies.
        transpose ({track: semitones}) applies from the first bar of a fresh start, or from the switch
        bar of a queued one, merged into the transposes already carried.
        tracks ({track: {slot, tune, transpose, mute}}) sets each track up in the same call: the slot and
        tune CCs go out just before the first bar (fresh start) or at the switch bar (queued), and the
        mutes land with them.
        """
        bpm = check_bpm(pattern.bpm if bpm is None else bpm)  # validate before touching the running beat
        bars = check_bars(bars)
        send_transport = check_send_transport(send_transport)
        transpose = check_transpose_map(transpose)
        setup = check_setup(tracks)
        for track, entry in setup.items():
            if "transpose" in entry:
                if transpose.get(track, entry["transpose"]) != entry["transpose"]:
                    raise WhiplashError(f"track {track}: transpose given twice with different values "
                                        f"({transpose[track]} and {entry['transpose']})")
                transpose[track] = entry["transpose"]
        ccs = setup_ccs(setup)
        mutes = {t: e["mute"] for t, e in setup.items() if "mute" in e}
        keyspec = check_key(key, scale)
        with self._transport:
            same_mode = send_transport is None or send_transport == self.send_transport
            if (self.playing() and self._port is not None and (port is None or port == self.port_name)
                    and same_mode):
                with self._lock:
                    self._check_transpose_targets(transpose, pattern, carried=set(self._parts))
                    replaced = self._queued["pattern"].name if self._queued else None
                    at = self.bar + 1
                    self._queued = {"pattern": pattern, "bpm": bpm, "bars": bars, "at": at, "transpose": transpose,
                                    "ccs": ccs, "mutes": mutes, "key": keyspec}
                out = {"mode": "queued", "switch_at_bar": at, "replaced_queued": replaced,
                       "send_transport": self.send_transport}
                return {**out, "setup": setup} if setup else out
            self._check_transpose_targets(transpose, pattern, carried=set())  # a fresh start clears written parts
            if send_transport is None:
                send_transport = default_send_transport()
            stopped = self.stop()  # stops in the old mode (no Stop if the old run was clock-only)
            self.ensure_port(port)
            with self._lock:
                self.send_transport = send_transport
                self._key = keyspec
                self._load(pattern, bpm, bars, start_bar=0)
                self._transpose = {t: v for t, v in transpose.items() if v}
                self._apply_setup(ccs, mutes)  # before the thread starts: before MIDI Start and the first note
                self.bar = 0
                self.last_error = None
                self._stop, self._done = threading.Event(), threading.Event()
                self._thread = threading.Thread(
                    target=self._run, args=(send_clock, send_transport, self._stop, self._done),
                    name="whiplash-seq", daemon=True)
                self._thread.start()
            out = {"mode": "started", "send_transport": send_transport, **stopped}
            return {**out, "setup": setup} if setup else out

    def _apply_setup(self, ccs, mutes):
        """Send play_pattern's per-track slot/tune CCs and set its mutes (caller holds _lock).

        A sent CC replaces a running ramp on the same track and CC, as whiplash_set_param does. Unmuting
        also releases a unit mute Whiplash set (CC 94 = 0), as whiplash_unmute_track does.
        """
        mido = __import__("mido") if ccs or mutes else None
        for track, control, value in ccs:
            self._ramps.pop((track, control), None)
            self._cc(mido, track - 1, control, value)
        for track, muted in mutes.items():
            if muted:
                self.muted.add(track)
            else:
                self.muted.discard(track)
                if track in self.hw_muted:
                    self._cc(mido, track - 1, MUTE_CC, 0)
                    self.hw_muted.discard(track)

    def _load(self, pattern, bpm, bars, start_bar):
        """Make pattern current (caller holds _lock). Resets mutations, keeps mutes, ramps, drops.

        pattern is the generated one; it plays routed onto the kit map (kitmap.route).
        """
        self._raw_pattern = pattern
        self.pattern = self._routed(pattern)
        self._kit_dirty = False
        self.bpm = bpm
        self.swing = pattern.swing
        self.bars_total = bars
        self.pattern_start = start_bar
        self._density, self.humanize = {}, 0.0
        self._work = mutate.working(self.pattern)
        for track, part in self._parts.items():  # written parts carry across switches and mutate reset
            self._work[track] = [list(bar) for bar in part.bars]
        self._refresh_harmony()

    def _routed(self, pattern, key=None):
        """pattern in the session key (or key), routed onto the kit map. Cheap: safe at a bar line."""
        return kitmap.route(harmony.in_key(pattern, key or self._key), self._kit_tracks)

    def _refresh_harmony(self):
        """Recompute which tracks follow the progression and how (caller holds _lock)."""
        if self._prog is None:
            self._prog_modes, self._prog_ranks, self._prog_pads = {}, {}, frozenset()
            return
        self._prog_modes, self._prog_ranks, self._prog_pads = harmony.modes(
            self.pattern, self._kit_tracks, self._prog.overrides, set(self._parts), self._work)

    def effective_key(self):
        """The key the beat plays in: the session key, else the playing pattern's home key."""
        if self._key is not None:
            return self._key
        return harmony.key_of(self._raw_pattern.key) if self._raw_pattern is not None else None

    def key_name(self):
        key = self.effective_key()
        return key.name if key else None

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
                    self._parts = {}
                    self._key, self._prog = None, None
                    if self._raw_pattern is not None:
                        self._load(self._raw_pattern, self.bpm, self.bars_total, 0)
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
            # channels 1-8 always (the generated pattern's tracks), plus any channel 9-16 that played a
            # note since the last panic (written parts): no CC 123 on channels Whiplash never played
            for ch in sorted(LOW_CHANNELS | self._note_channels):
                self._cc(mido, ch, ALL_NOTES_OFF, 0)
            self._note_channels.clear()
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
            if queued.get("key") is not None:
                self._key = queued["key"]
            self._load(queued["pattern"], queued["bpm"], queued["bars"], start_bar=bar_n)
            self._set_transposes(queued.get("transpose") or {})
            self._apply_setup(queued.get("ccs") or (), queued.get("mutes") or {})  # before this bar's notes
            log.info("whiplash: switched to %s at bar %d", queued["pattern"].name, bar_n)
        if self._kit_dirty:
            self._reroute()
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
        self._bar_exact = frozenset(self._parts)
        idx = (bar_n - self.pattern_start) % patterns.BARS
        r = mutate.rng(self.seed, "humanize", bar_n) if self.humanize else None
        prog = self._prog if self._prog is not None and bar_n >= self._prog.start else None
        if prog is not None:
            chord_i = prog.index(bar_n)
            chord_notes, chord_root = prog.voicings[chord_i], prog.chords[chord_i].root
        events = collections.defaultdict(list)
        lines = list(self._work.items())
        if prog is not None:  # chord tracks with no line of their own hold one tone per bar
            lines += [(t, None) for t in sorted(self._prog_pads)]
        for track, bars in lines:
            drop = self._drops.get(track)
            if drop and drop[0] <= bar_n:
                continue
            if bars is None:
                hits = harmony.pad_line()
            else:
                hits = mutate.fill(track, bars[idx]) if track in fills else bars[idx]
            if prog is not None and track in self._prog_modes:
                hits = harmony.apply(self._prog_modes[track], hits, chord_notes, chord_root, prog.key,
                                     self._prog_ranks.get(track, 0))
            shift = self._transpose.get(track, 0)
            for step, note, vel, gate, offset in hits:
                if r is not None:
                    vel, offset = mutate.humanize(vel, offset, self.humanize, r)
                if shift:
                    note = clamp_note(note + shift)
                events[step].append((track, note, vel, gate, offset))
        return events

    def _reroute(self):
        """Labels changed while playing (caller holds _lock): route the same pattern onto the new map.

        Unlike a switch this keeps swing, humanize and per-track density.
        """
        old = set(self._work)
        self.pattern = self._routed(self._raw_pattern)
        self._kit_dirty = False
        for track in old | set(self.pattern.bars) | set(self._parts):
            self._rebuild(track)
        self._refresh_harmony()

    @staticmethod
    def _silent_tracks(tracks, pattern, carried):
        """The tracks that would play nothing: no notes in pattern and no written part carried."""
        work = mutate.working(pattern) if pattern is not None else {}
        return sorted(t for t in tracks if t not in carried and not any(work.get(t) or []))

    def _check_transpose_targets(self, transpose, pattern, carried):
        """Refuse a non-zero transpose on a track that would play nothing (it would silently do nothing)."""
        silent = self._silent_tracks([t for t, v in transpose.items() if v],
                                     kitmap.route(pattern, self._kit_tracks), carried)
        if silent:
            raise WhiplashError(f"track(s) {silent} play nothing in {pattern.name}, so transpose would do nothing. "
                                "Tracks 9-16 only play a written part: start the pattern, write one with "
                                "whiplash_write_part, then use whiplash_transpose")

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
        exact = frozenset()  # tracks playing written parts: length is the exact note-off, no GATE factor
        last_off = {}  # (ch, note) -> (time, seq) of the latest note-off scheduled for it
        stale = set()  # seqs of note-offs superseded by a retrigger of the same note
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
                        exact = self._bar_exact
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
                        prev = last_off.get((ch, note))
                        if prev is not None and prev[0] > on:
                            # the same note retriggers before its earlier note-off: end it just before the
                            # new note-on instead, so the old note-off can't cut the new note short
                            stale.add(prev[1])
                            heapq.heappush(pending, (on - 1e-4, seq, ch, note, 0)); seq += 1
                        heapq.heappush(pending, (on, seq, ch, note, vel)); seq += 1
                        off = on + gate * sixteenth * (1.0 if track in exact else GATE) - 1e-4
                        heapq.heappush(pending, (off, seq, ch, note, 0))
                        last_off[(ch, note)] = (off, seq); seq += 1
                # wait for the tick, flushing note events on time
                while True:
                    now = time.perf_counter()
                    while pending and pending[0][0] <= now:
                        _, s, ch, note, vel = heapq.heappop(pending)
                        if s in stale:
                            stale.discard(s)
                            continue
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
            for _, s, ch, note, vel in sorted(pending):
                if vel == 0 and s not in stale and (ch, note) in self._sounding:
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
            self._note_channels.add(ch)
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
        hold_note = number == HOLD_CC and _is_hold_note(value)
        if hold_note:  # the one explicit, labelled path to HOLD = NOTE: exactly 127 or 'note'
            value, clamped = HOLD_NOTE, False
        else:
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
        if hold_note:
            out.update(HOLD_NOTE_INFO)
        return out

    def ramp(self, track, to, param=None, cc=None, start=None, beats=None, bars=None, curve="linear"):
        """Ramp a CC from start to `to` over beats or bars, advanced on the sequencer clock."""
        track = check_track(track)
        number, spec = self._target(param, cc)
        if spec is not None and spec.discrete:
            raise WhiplashError(f"{spec.name} is a switch; use whiplash_set_param")
        to, to_clamped = self._value(to, spec, "to")
        if number == HOLD_CC and to >= HOLD_NOTE:  # raw cc 80 (named amp_hold already stops at 126)
            to, to_clamped = HOLD_NOTE - 1, True  # a ramp never ends on HOLD = NOTE
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
                if number == HOLD_CC and start >= HOLD_NOTE:
                    start, from_clamped = HOLD_NOTE - 1, True
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
        if number == HOLD_CC and (to_clamped or from_clamped):
            out["hold_note"] = HOLD_RAMP_NOTE
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
        tracks = check_tracks(tracks, high=16)
        with self._lock:
            self._require_playing()
            empty = [t for t in tracks if not any(self._base(t) or [])]
            if empty:
                raise WhiplashError(f"track(s) {empty} play nothing to thin or thicken")
            for track in tracks:
                self._density[track] = amount
                self._rebuild(track)
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
        tracks = check_tracks(tracks, high=16)
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
            self._load(self._raw_pattern, self.bpm, self.bars_total, self.pattern_start)
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
            if value:
                carried = set(self._parts)
                silent = self._silent_tracks([track], self.pattern, carried)
                queued = self._queued
                if silent and queued:  # it may play in the pattern that is about to switch in
                    silent = self._silent_tracks(silent, kitmap.route(queued["pattern"], self._kit_tracks), carried)
                if silent:
                    raise WhiplashError(f"track {track} plays nothing right now, so transpose would do nothing. "
                                        + ("Tracks 9-16 only play a written part: " if track > 8 else "")
                                        + "write one with whiplash_write_part first, then transpose it")
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

    # ---- written parts -------------------------------------------------
    def _base(self, track):
        """A track's line before density (caller holds _lock): its written part, else the pattern's."""
        part = self._parts.get(track)
        if part is not None:
            return [list(bar) for bar in part.bars]
        if self.pattern is None:
            return None
        return mutate.working(self.pattern).get(track)

    def _rebuild(self, track):
        """Recompute one track's working line from its base and density (caller holds _lock)."""
        base = self._base(track)
        if base is None:
            self._work.pop(track, None)
        elif self._density.get(track):
            self._work[track] = mutate.density(base, self._density[track], self.seed, track)
        else:
            self._work[track] = base

    def _length_note(self, track):
        ch = track - 1
        hold, mode = self._cc_values.get((ch, ccmap.PARAMS["amp_hold"].cc)), self._cc_values.get((ch, AMP_MODE_CC))
        if mode == 1:
            return "Whiplash last sent amp_mode 1 (ADSR) on this track, so length and release should shape it. " + LENGTH_NOTE
        if hold == HOLD_NOTE:
            return "Whiplash last sent amp_hold 127 (NOTE) on this track, so length should be audible. " + LENGTH_NOTE
        return LENGTH_NOTE

    def write_part(self, track, rhythm=None, grid=None, steps=None, hits=None, lock_to=None, notes=None, key=None,
                   scale=None, length=None, velocity=None, bars=None, reset=False, envelope=None):
        """Write a track's line from the next bar line: where the hits go, and what notes they play.

        Exactly one of rhythm / grid / steps / hits / lock_to places the hits. lock_to (and rhythm
        'on_kick' = lock_to 1) copies the source track's hits as they are now; it does not follow later
        changes. The part replaces the generated line in the working pattern, so mutes, drops, fills,
        density and humanize still apply; it carries across pattern switches and whiplash_mutate reset,
        and reset: true or whiplash_stop clears it. Everything is validated before anything changes.
        envelope 'note' sends one CC 80 = 127 (HOLD = NOTE) on the track, only when asked.
        """
        track = check_track(track)
        reset = check_flag(reset, "reset")
        envelope = check_envelope(envelope)
        if reset:
            extra = [k for k, v in (("rhythm", rhythm), ("grid", grid), ("steps", steps), ("hits", hits),
                                    ("lock_to", lock_to), ("notes", notes), ("key", key), ("scale", scale),
                                    ("length", length), ("velocity", velocity), ("bars", bars),
                                    ("envelope", envelope)) if v not in (None, "", [])]
            if extra:
                raise WhiplashError(f"reset: true takes only track (got {', '.join(extra)})")
            with self._lock:
                self._require_playing()
                had = self._parts.pop(track, None)
                self._rebuild(track)
                self._refresh_harmony()
                return {"track": track, "reset": True, "was_written": had is not None,
                        "part": "generated" if any(self._work.get(track) or []) else None,
                        "applies": "next bar", "at_bar": self.bar + 1}
        try:
            kind, value = parts.placement(rhythm, grid, steps, hits, lock_to)
            source = None
            if kind == "lock_to":
                source = check_track(value)
                if source == track:
                    raise WhiplashError("lock_to must name another track (e.g. 1 for the kick)")
            with self._lock:
                self._require_playing()
                source_bars = self._base(source) if source else None
                if isinstance(key, str) and key.strip().lower() in CURRENT_KEY:
                    playing = self.effective_key()
                    if playing is None:
                        raise WhiplashError("no key is playing yet: give one, e.g. key: 'Am'")
                    if scale in (None, ""):
                        scale = playing.scale
                    key = harmony.pc_name(playing.pc, playing.flats)
            part = parts.build(kind, source if source else value, notes=notes, key=key, scale=scale, length=length,
                               velocity=velocity, bars=bars, source_bars=source_bars)
        except parts.PartError as exc:
            raise WhiplashError(str(exc)) from None
        sent = None
        if envelope == "note":  # opt-in, after validation: exactly one CC 80 = 127 on this track
            self.ensure_port()
            sent = self.set_param(track, "note", param="amp_hold")
        with self._lock:
            self._require_playing()
            replaced = track in self._parts
            self._parts[track] = part
            self._rebuild(track)
            self._refresh_harmony()
            transpose = self._transpose.get(track, 0)
            out = {"track": track, "part": "written", "placed_by": part.source, "bars": part.bars_written,
                   "repeats": f"every {part.bars_written} bar(s) across the 4-bar loop",
                   "applies": "next bar", "at_bar": self.bar + 1, "replaced_written": replaced,
                   "written": parts.describe(part), "transpose": transpose,
                   "pitch": self._pitch(track, part.bars, transpose, None),
                   "length_audible": self._length_note(track)}
            if part.key:
                out["key"] = part.key
            if source:
                out["locked_to"] = {"track": source, "follows_live": False,
                                    "note": "copied the source's hits now; later density, fills or edits on it "
                                            "are not followed"}
            if part.unused_notes:
                out["unused_notes"] = part.unused_notes
                out["note"] = (f"{part.unused_notes} note(s) did not fit in 4 bars of hits and won't play; "
                               "add hits or give fewer notes")
            if transpose:
                out["transpose_note"] = (f"track {track} is transposed {transpose:+d} semitones, which still "
                                         "applies on top of these notes (whiplash_transpose 0 to remove it)")
            if self._density.get(track):
                out["density"] = self._density[track]
            if self._prog is not None:
                mode = self._prog_modes.get(track)
                out["progression"] = (f"follows the progression ({mode}): named in whiplash_set_progression tracks"
                                      if mode else "plays as written; the progression doesn't change it (name the "
                                      "track in whiplash_set_progression tracks to make it follow)")
            if self._queued:
                out["carries_into"] = (f"the queued switch to {self._queued['pattern'].name} at bar "
                                       f"{self._queued['at']}")
        if sent is not None:
            out["envelope"] = {"amp_hold": sent["value"], "cc": sent["cc"], **HOLD_NOTE_INFO}
        if track > 8:
            out["channel_note"] = HIGH_TRACK_NOTE
        return out

    # ---- keys and progressions ----------------------------------------
    def set_progression(self, chords=None, bars_per_chord=None, voicing=None, key=None, scale=None, tracks=None,
                        clear=False):
        """Play a chord progression from the next bar line: chord tracks voice it, bass follows the roots.

        chords are Roman numerals in the key ("i VI III VII") or names ("Am F C G"). The key is the one given,
        else the one the beat plays in; giving a new one also moves the pattern into it at the same bar.
        Each chord lasts bars_per_chord bars and the progression loops. Roles pick each track's mode
        (harmony.modes); tracks overrides them, but never on a drum, cymbal or fx track. It carries across
        pattern switches; clear: true or whiplash_stop ends it. Validated before anything changes.
        """
        clear = check_flag(clear, "clear")
        if clear:
            extra = [k for k, v in (("chords", chords), ("bars_per_chord", bars_per_chord), ("voicing", voicing),
                                    ("key", key), ("scale", scale), ("tracks", tracks)) if v not in (None, "", [], {})]
            if extra:
                raise WhiplashError(f"clear: true takes nothing else (got {', '.join(extra)})")
            with self._lock:
                self._require_playing()
                had = self._prog
                self._prog = None
                self._refresh_harmony()
                return {"cleared": had is not None, "applies": "next bar", "at_bar": self.bar + 1, "key": self.key_name()}
        if chords in (None, "", []):
            raise WhiplashError("give chords, e.g. ['i', 'VI', 'III', 'VII'] or 'Am F C G' (or clear: true)")
        try:
            symbols = harmony.split_chords(chords)
            per_chord = harmony.check_bars_per_chord(bars_per_chord)
            voicing = harmony.check_voicing(voicing)
            overrides = harmony.check_modes(tracks)
        except harmony.HarmonyError as exc:
            raise WhiplashError(str(exc)) from None
        keyspec = check_key(key, scale)
        with self._lock:  # read only; parsing, voicing and re-keying happen outside the lock the clock needs
            self._require_playing()
            prog_key = keyspec or self.effective_key() or harmony.Key(0, "major")
            raw = self._raw_pattern
        try:
            resolved = [harmony.parse_chord(sym, prog_key) for sym in symbols]
        except harmony.HarmonyError as exc:
            raise WhiplashError(str(exc)) from None
        voicings = harmony.voice(resolved, voicing)
        routed = self._routed(raw, prog_key) if raw is not None else None
        with self._lock:
            self._require_playing()
            if self._raw_pattern is not raw:  # a switch landed meanwhile: route what plays now
                routed = self._routed(self._raw_pattern, prog_key)
            bad = harmony.refused(overrides, routed, self._kit_tracks)
            if bad:
                names = ", ".join(f"{t} ({r})" for t, r in sorted(bad.items()))
                raise WhiplashError(f"track(s) {names} hold drums, cymbal or fx: Whiplash never puts chords or bass "
                                    "notes there. Pick a pad, chord, stab, bass or lead track, or relabel it with "
                                    "whiplash_label_tracks")
            at = self.bar + 1
            replaced = self._prog is not None
            prog = harmony.Progression(tuple(resolved), voicings, per_chord, voicing, prog_key, at, overrides)
            key_changed = prog_key != self.effective_key()
            self._key, self._prog = prog_key, prog
            if key_changed:
                self._kit_dirty = True  # re-key the pattern at the same bar line the progression starts on
                self.pattern = routed  # so the modes below see the routing that bar will use
            self._refresh_harmony()
            out = {"progression": harmony.describe(prog), "key": prog_key.name, "bars_per_chord": per_chord,
                   "voicing": voicing, "loop_bars": prog.length, "applies": "next bar", "starts_at_bar": at,
                   "replaced": replaced, "tracks": self._prog_summary(),
                   "polyphony_note": POLY_NOTE}
            if key_changed:
                out["key_changed"] = "the pattern's melodic tracks move into this key at the same bar"
            if not any(m in ("chords", "stack") for m in self._prog_modes.values()):
                out["note"] = ("no track plays the chords: label a pad, chord or stab track (whiplash_label_tracks) or "
                               'pass tracks, e.g. {"7": "chords"}')
            written = sorted(t for t in self._parts if t not in self._prog_modes)
            if written:
                out["written_unchanged"] = written
            if self._queued:
                out["carries_into"] = f"the queued switch to {self._queued['pattern'].name} at bar {self._queued['at']}"
            return out

    def _prog_summary(self):
        """{track: mode} for the tracks following the progression (caller holds _lock)."""
        return {str(t): m for t, m in sorted(self._prog_modes.items())}

    def progression_status(self):
        """The progression for whiplash_status (caller holds _lock), or None."""
        prog = self._prog
        if prog is None:
            return None
        out = {"chords": [c.symbol for c in prog.chords], "names": [c.name for c in prog.chords],
               "key": prog.key.name, "bars_per_chord": prog.bars_per_chord, "voicing": prog.voicing,
               "loop_bars": prog.length, "starts_at_bar": prog.start, "tracks": self._prog_summary(),
               "voicings": harmony.describe(prog)}
        if self.bar >= prog.start:
            i = prog.index(self.bar)
            into = (self.bar - prog.start) % prog.bars_per_chord
            out["now"] = {"chord": prog.chords[i].symbol, "name": prog.chords[i].name, "index": i,
                          "next_change_at_bar": self.bar + prog.bars_per_chord - into}
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
            if current:
                work = self._work
            else:  # a queued pattern: routed onto the kit map, and written parts carry into it
                pattern = self._routed(pattern, (self._queued or {}).get("key"))
                work = mutate.working(pattern)
                work.update({t: part.bars for t, part in self._parts.items()})
            transpose = dict(self._transpose) if transpose is None else transpose
            last = collections.defaultdict(dict)
            for (ch, control), value in self._cc_values.items():
                if control not in _NOT_PARAMS:
                    spec = ccmap.BY_CC.get(control)
                    last[ch + 1][spec.name if spec else f"cc {control}"] = value
            roles = pattern.roles if pattern is not None else {}
            in_use = {t for t, bars in work.items() if any(bars)} | set(last) | set(transpose)
            in_use |= self.muted | self.hw_muted | set(self._kit_tracks)
            if current:
                in_use |= set(self._prog_modes)
            out = {}
            for track in sorted(in_use):
                label = self._kit_tracks.get(track)
                role = roles.get(track)
                cc = last.get(track, {})
                slot = cc.get("sample_slot")
                out[str(track)] = {
                    "role": label[1] if label else f"{role} (assumed)" if role else None,
                    "slot": slot, "tune": cc.get("tune"),
                    "transpose": transpose.get(track, 0),
                    "pitch": self._pitch(track, work.get(track), transpose.get(track, 0),
                                         None if track in self._parts else pattern),
                    "muted": track in self.muted or track in self.hw_muted,
                    "part": ("written" if track in self._parts else
                             "generated" if work.get(track) and any(work[track]) else None),
                    "last_cc": {k: v for k, v in cc.items() if k not in ("sample_slot", "tune")},
                }
                if label:
                    out[str(track)]["kit_role"] = label[0]
                if current and track in self._prog_modes:
                    out[str(track)]["progression"] = self._prog_modes[track]
                if slot is not None and slot in self._kit_slots:
                    out[str(track)]["slot_label"] = self._kit_slots[slot]
            return out

    # ---- kit map -------------------------------------------------------
    def kit(self):
        """The session kit map as JSON-friendly dicts."""
        with self._lock:
            return {"tracks": {str(t): {"role": r, "label": l} for t, (r, l) in sorted(self._kit_tracks.items())},
                    "slots": {str(s): l for s, l in sorted(self._kit_slots.items())}}

    def slot_label(self, slot):
        with self._lock:
            return self._kit_slots.get(slot)

    def label_tracks(self, tracks=None, slots=None, reset=False):
        """Record what the user says each track and slot holds. Merges; a null/empty label removes one.

        Generated parts follow the map from the next bar line (or the next start). Validated before
        anything changes. The map survives whiplash_stop and pattern switches; reset: true clears it
        first (labels given in the same call are then applied to the empty map).
        """
        reset = check_flag(reset, "reset")
        try:
            track_changes = kitmap.check_tracks(tracks)
            slot_changes = kitmap.check_slots(slots)
        except kitmap.KitError as exc:
            raise WhiplashError(str(exc)) from None
        if not (reset or track_changes or slot_changes):
            raise WhiplashError('give tracks (e.g. {"7": "cymbal", "5": "pad"}), slots (e.g. {"11": "synth"}) '
                                "or reset: true")
        with self._lock:
            base_tracks = {} if reset else self._kit_tracks
            base_slots = {} if reset else self._kit_slots
            self._kit_tracks = kitmap.merged(base_tracks, track_changes)
            self._kit_slots = kitmap.merged(base_slots, slot_changes)
            playing = self.playing() and self._raw_pattern is not None
            if playing:
                self._kit_dirty = True  # the sequencer re-routes at the next bar line
            elif self._raw_pattern is not None:
                self._reroute()  # nothing is clocking: route now so status shows it
            out = {"kit": self.kit(), "reset": reset,
                   "applies": "next bar" if playing else "next whiplash_play_pattern"}
            if playing:
                out["at_bar"] = self.bar + 1
            if self._raw_pattern is not None:
                out["routing"] = kitmap.describe(self._raw_pattern, self._kit_tracks)
                out["routing"]["pattern"] = self._raw_pattern.name
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
                            "key": (queued.get("key") or self._key or harmony.key_of(queued["pattern"].key)).name,
                            "transpose": {str(t): v for t, v in sorted((queued.get("transpose") or {}).items())}}
                           if queued else None),
                "transpose": {str(t): v for t, v in sorted(self._transpose.items())},
                "key": self.key_name(), "key_source": ("set" if self._key is not None else
                                                       "pattern" if self._raw_pattern is not None else None),
                "progression": self.progression_status(),
                "parts": {str(t): {"placed_by": p.source, "bars": p.bars_written} for t, p in sorted(self._parts.items())},
                "tracks": self.tracks_summary(), "roles_assumed": not self._kit_tracks,
                "kit_note": KIT_LABELLED_NOTE if self._kit_tracks else KIT_NOTE, "kit": self.kit(),
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
                "queued": ({**self._queued, "pattern": self._routed(self._queued["pattern"], self._queued.get("key"))}
                           if self._queued else None),
                "muted": set(self.muted), "hw_muted": set(self.hw_muted),
                "kit_tracks": dict(self._kit_tracks), "kit_slots": dict(self._kit_slots),
                "ramps": [r.summary() for r in sorted(self._ramps.values(), key=lambda r: int(r.id[1:]))],
                "density": dict(self._density), "humanize": self.humanize, "work": dict(self._work),
                "drops": dict(self._drops), "fills": {b: set(t) for b, t in self._fills.items()},
                "transpose": dict(self._transpose), "parts": set(self._parts),
                "cc_values": dict(self._cc_values), "messages_sent": self.sent_count,
                "position": self.position, "bar_hits": self.bar_hits,
                "transport_mode": transport_mode(self.transport_on()),
                "harmony": (self._key, self.effective_key(), self._prog, dict(self._prog_modes), dict(self._prog_ranks), self._prog_pads),
            }
