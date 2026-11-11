"""v0.8.0 play along: MIDI input from the unit, decoded moves, call-and-response replies, the session recording.

Pure helpers only: no engine state, no locks. The engine owns the reader thread (engine.Engine.open_input) and
calls these. mido is imported lazily (through engine._mido) only when the input opens.

What the unit sends, and when (docs/digitakt-ii/reference.md §7.2, manual 14.4 p. 77-79): only with SETTINGS >
MIDI CONFIG > PORT CONFIG OUTPUT TO including USB, ENCODER DEST / TRIG KEY DEST at INT+EXT, on the track's own
channel when OUTPUT CH is the track channel (else the AUTO channel), as CC or NRPN per PARAM OUTPUT. None of this
is hardware-verified yet (§15.3 Q25-30).

Received messages are never re-sent: the reader only reads them. SysEx, program change, clock and transport from
the unit are ignored and counted.
"""
import collections
import statistics
import time

from . import ccmap, harmony, patterns

MODES = ("echo", "answer", "harmonize")
DEFAULT_MODE = "answer"
MOVES_MAX = 32  # last user moves kept (status shows the last MOVES_SHOWN)
MOVES_SHOWN = 8
YIELDS_MAX = 16
PHRASE_MAX = 16  # notes per reply: one per 16th step of one bar
PHRASE_BUFFER = 64  # notes heard and not yet answered
GRABS_MAX = 256  # user grabs of a ramped knob waiting for the sequencer's next tick
REC_MAX = 65536  # recorded events (about 15 minutes of a busy beat); the oldest drop first
UNDO_MAX = 16
ECHO_WINDOW = 0.06  # s: an incoming CC/note equal to what Whiplash sent this recently is its own echo
READ_BATCH = 64  # messages per reader batch before it yields the GIL
READ_IDLE = 0.001  # s the reader sleeps when nothing is pending
READ_YIELD = 0.0002  # s the reader sleeps between batches under a flood
QUIET_HINT_AFTER = 10.0  # s with the input open and nothing heard -> status carries SEND_HINT
REG_LOW = patterns.NATIVE - patterns.NATIVE_FLOOR  # 53: a reply's median never sits lower (v0.5 register)
REG_HIGH = patterns.NATIVE + 12  # 72: nor more than an octave above native pitch
NRPN_CCS = {99, 98, 6, 38, 101, 100}
NRPN_TO_PARAM = {p.nrpn: p for p in ccmap.PARAMS.values() if p.nrpn}
# Addresses where the manual and midi.guide disagree (reference §8.3; ccmap docstring): a move decoded through one
# of these may name the wrong param, so it is marked unsure.
UNSURE_NRPNS = frozenset({(1, 108), (1, 101), (1, 110), (1, 100), (1, 26), (1, 23), (1, 24), (1, 25), (1, 51),
                          (1, 52)})

SEND_SETUP = ("On the Digitakt: SETTINGS > MIDI CONFIG > PORT CONFIG: OUTPUT TO = USB (or MIDI+USB), ENCODER DEST "
              "and TRIG KEY DEST = INT+EXT, OUTPUT CH = the track channel (not AUTO, so moves name their track), "
              "PARAM OUTPUT = CC. Keep INPUT FROM = USB and RECEIVE NOTES / RECEIVE CC/NRPN on for Whiplash's own "
              "beat. (Manual 14.4, p. 77-79; confirm the exact names on the unit.)")
SEND_HINT = ("Nothing heard from the unit yet. Turn a knob or play a note; if still nothing, its send settings are "
             "probably off. " + SEND_SETUP)
NO_INPUT = ("Elektron Digitakt II MIDI input not found. Check the USB cable and power, and that USB CONFIG is USB "
            "MIDI or USB AUDIO/MIDI. " + SEND_SETUP)


class JamError(ValueError):
    pass


# ---- input port ------------------------------------------------------------------------------------------------

def find_input(names, virtual_name):
    """The first input whose name contains 'digitakt', never Whiplash's own virtual port. None if there is none."""
    for name in names:
        if name != virtual_name and not name.startswith(virtual_name + ":") and "digitakt" in name.lower():
            return name
    return None


def open_input(mido, virtual_name):
    """Open the Digitakt's MIDI input. -> (port, name). Raises JamError with the setup hint; never another input."""
    names = mido.get_input_names()
    target = find_input(names, virtual_name)
    if target is None:
        raise JamError(f"{NO_INPUT} Inputs seen: {names or 'none'}")
    return mido.open_input(target), target


# ---- decoding --------------------------------------------------------------------------------------------------

class Decoder:
    """Turns incoming messages into moves. One instance per open input, fed from the reader thread only.

    -> None (ignored, or part of an NRPN still being assembled), or a dict:
       {"kind": "cc", "track", "cc", "param", "value", "via": "cc" | "nrpn", ["nrpn", "unsure"]}
       {"kind": "note", "track", "note", "velocity"}  (velocity 0 = note-off)
    """

    def __init__(self):
        self._nrpn = {}  # channel -> [msb, lsb]
        self.ignored = collections.Counter()

    def feed(self, msg):
        kind = msg.type
        if kind in ("note_on", "note_off"):
            vel = msg.velocity if kind == "note_on" else 0
            return {"kind": "note", "track": msg.channel + 1, "note": msg.note, "velocity": vel}
        if kind != "control_change":
            self.ignored[kind] += 1  # sysex, program_change, clock, start/stop, pitchwheel, aftertouch...
            return None
        ch, control, value = msg.channel, msg.control, msg.value
        if control in NRPN_CCS:
            return self._nrpn_part(ch, control, value)
        spec = ccmap.BY_CC.get(control)
        return {"kind": "cc", "track": ch + 1, "cc": control, "param": spec.name if spec else f"cc {control}",
                "value": value, "via": "cc"}

    def _nrpn_part(self, ch, control, value):
        state = self._nrpn.setdefault(ch, [None, None])
        if control == 99:
            state[0], state[1] = value, None
        elif control == 98:
            state[1] = value
        elif control in (101, 100):  # RPN: not a parameter move
            state[0] = state[1] = None
        elif control == 6 and None not in state:
            address = tuple(state)
            spec = NRPN_TO_PARAM.get(address)
            out = {"kind": "cc", "track": ch + 1, "cc": spec.cc if spec else None,
                   "param": spec.name if spec else f"nrpn {address[0]}:{address[1]}", "value": value,
                   "via": "nrpn", "nrpn": list(address)}
            if address in UNSURE_NRPNS:
                out["unsure"] = True
            return out
        return None  # CC 38 (data LSB) only refines the value already reported


def said(move):
    first = move.get("from")
    change = f"{first} -> {move['value']}" if first is not None and first != move["value"] else f"{move['value']}"
    return f"track {move['track']} {move['param']} {change}"


# ---- call and response -----------------------------------------------------------------------------------------

def check_mode(mode):
    if mode in (None, ""):
        return DEFAULT_MODE
    word = str(mode).strip().lower()
    if word not in MODES:
        raise JamError(f"mode must be one of {', '.join(MODES)}, got {mode!r}")
    return word


def quantize(notes, bar_start, step_len):
    """[(time, note, velocity)] heard in the bar starting at bar_start -> [(step, note, velocity)], one per step
    (the first played wins), at most PHRASE_MAX. Notes outside steps 0-15 are dropped."""
    out = {}
    for t, note, vel in notes:
        step = int(round((t - bar_start) / step_len))
        if 0 <= step < patterns.STEPS and step not in out:
            out[step] = (step, note, vel)
    return [out[s] for s in sorted(out)][:PHRASE_MAX]


def _scale(key):
    return (key.pc, key.steps) if key is not None else (0, tuple(range(12)))


def degree(note, key):
    """The note's index in the key's scale, counted from the tonic below MIDI 0 (snapped into the key first)."""
    pc, steps = _scale(key)
    if key is not None:
        note = harmony.snap(note, key)
    octave, rel = divmod(note - pc, 12)
    return octave * len(steps) + steps.index(rel)


def from_degree(index, key):
    pc, steps = _scale(key)
    octave, i = divmod(index, len(steps))
    return pc + 12 * octave + steps[i]


def fit_register(notes):
    """Shift by whole octaves until the median sits in REG_LOW..REG_HIGH, then fold each note into 16-84."""
    if not notes:
        return notes
    median = statistics.median(notes)
    shift = 0
    while median + shift < REG_LOW:
        shift += 12
    while median + shift > REG_HIGH:
        shift -= 12
    return [fold(n + shift) for n in notes]


def fold(note):
    while note < patterns.NOTE_MIN:
        note += 12
    while note > patterns.NOTE_MAX:
        note -= 12
    return note


def reply(mode, phrase, key):
    """The answer to a quantized phrase [(step, note, velocity)] -> [(step, note, velocity)], same rhythm.

    echo: the phrase snapped into the key. answer: its contour mirrored around the first note by scale degree,
    ending on the nearest tonic. harmonize: a diatonic third above each note. All in the native register."""
    if not phrase:
        return []
    degrees = [degree(n, key) for _, n, _ in phrase]
    if mode == "echo":
        notes = [from_degree(d, key) for d in degrees]
    elif mode == "harmonize":
        notes = [from_degree(d + 2, key) for d in degrees]
    else:
        first = degrees[0]
        mirrored = [first - (d - first) for d in degrees]
        size = len(_scale(key)[1])
        last = mirrored[-1]
        mirrored[-1] = size * round(last / size)  # resolve on the nearest tonic
        notes = [from_degree(d, key) for d in mirrored]
    notes = fit_register(notes)
    return [(step, note, max(1, min(127, vel))) for (step, _, vel), note in zip(phrase, notes)]


# ---- session recording -----------------------------------------------------------------------------------------

class Recording:
    """A bounded ring buffer of (direction, tick, time, type, channel, a, b) events.

    direction: "out" (sent by Whiplash), "in" (heard from the unit) or "mark" (pattern, section, tempo at a bar
    line). tick: Whiplash's clock tick (float, from Engine.clock_ref), or None when nothing plays. Deque appends are
    atomic, so the sequencer (under Engine._lock) and the reader thread (no engine lock) both append. Counters are
    per writer, so neither races the other.
    """

    def __init__(self, maxlen=REC_MAX):
        self.events = collections.deque(maxlen=maxlen)
        self.maxlen = maxlen
        self.sent = 0  # written under Engine._lock only
        self.received = 0  # written by the reader thread only
        self.marks = 0  # written under Engine._lock only
        self.started = time.time()
        self.bpm = None  # the tempo last marked (the sequencer marks each change at the bar line)

    @staticmethod
    def tick(ref, now):
        if ref is None:
            return None
        tick, at, length = ref
        return round(tick + (now - at) / length, 2)

    def out(self, msg, ref, now):
        self.events.append(("out", self.tick(ref, now), now, msg.type, msg.channel, *_data(msg)))
        self.sent += 1

    def heard(self, msg, ref, now):
        self.events.append(("in", self.tick(ref, now), now, msg.type, msg.channel, *_data(msg)))
        self.received += 1

    def mark(self, kind, value, ref, now):
        self.events.append(("mark", self.tick(ref, now), now, kind, None, value, None))
        self.marks += 1

    def snapshot(self):
        """A copy of the events, oldest first. Retries if a writer appended mid-copy."""
        for _ in range(20):
            try:
                return list(self.events)
            except RuntimeError:  # deque mutated during iteration
                time.sleep(0)
        return list(self.events)

    def summary(self):
        total = self.sent + self.received + self.marks
        return {"events": len(self.events), "sent": self.sent, "received": self.received, "marks": self.marks,
                "dropped": max(0, total - len(self.events)), "max": self.maxlen,
                "since_s": round(time.time() - self.started, 1), "in_memory_only": True}


def _data(msg):
    if msg.type in ("note_on", "note_off"):
        return msg.note, getattr(msg, "velocity", 0)
    return msg.control, msg.value
