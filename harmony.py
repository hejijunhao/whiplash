"""Keys, scales and chord progressions (v0.6.0): pure parsing and voicing, no MIDI, no engine state.

- A Key is (pitch class, scale name). Each generated pattern has a home key (patterns.HOME_KEYS); in_key()
  moves its melodic tracks into another key by scale degree, then re-applies the native register.
- A progression is a list of chords, given as Roman numerals in the key ("i VI III VII", "ii7 V7 Imaj7",
  "bVII") or as chord names ("Am F C G"). voice() turns each chord into note numbers near native pitch
  (note 60, reference.md §6.1), voice-led from one chord to the next.
- apply() reshapes one track's hits for the chord now playing. It runs in the sequencer thread at the bar
  line, so it only does lookups and small list work (at most 64 hits per track per bar).

Track modes:
  chords  one chord tone per hit, cycling down the voicing; each chord track starts on a different tone,
          so three chord tracks hitting together sound the whole chord. Safe on a monophonic track.
  stack   every chord tone on every hit (for a polyphonic target: a MIDI track, or an audio track if the
          unit layers notes; the manual implies an audio track is one voice, reference.md §6.4).
  root    every hit plays the chord root, in the octave nearest the line's own register.
  snap    every note moves to the nearest note of the key's scale (ties go down).
  off     the track plays its line unchanged.
"""
import re
import statistics
from dataclasses import dataclass, field, replace
from typing import NamedTuple

from . import kitmap, parts, patterns

CENTER = 62  # voicings sit just above native pitch (60)
CHORD_LOW = patterns.NATIVE - patterns.NATIVE_FLOOR  # 53: a voicing's median never goes below the v0.5 floor
CHORD_BOTTOM = CHORD_LOW - 12  # 41: the lowest note an open voicing may reach
CHORD_HIGH = 79
MAX_CHORDS = 16
BARS_PER_CHORD_MAX = 16
VOICINGS = ("close", "root", "open", "power")
MODES = ("chords", "stack", "root", "snap", "off")
ROLE_MODES = {"chord": "chords", "pad": "chords", "stab": "chords", "bass": "root", "lead": "snap"}
NEVER = frozenset({"kick", "snare", "rim", "clap", "closed hat", "open hat", "cymbal", "perc", "fx"})
PAD_VELOCITY, PAD_GATE = 90, 16  # a chord track with no line holds one chord tone per bar
SHARP_NAMES = patterns.NOTE_NAMES
FLAT_NAMES = ("C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B")
_FLAT_MAJORS = frozenset({5, 10, 3, 8, 1, 6})  # F Bb Eb Ab Db Gb
_SPLIT = re.compile(r"[\s,|\-–—]+")
_ROMAN = re.compile(r"^([b#♭♯]?)(vii|iii|vi|iv|ii|v|i|VII|III|VI|IV|II|V|I)(.*)$")
_NAME = re.compile(r"^([A-Ga-g])([#b♯♭]?)(.*)$")
DEGREES = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7}

# chord shapes in semitones above the root
SHAPES = {"maj": (0, 4, 7), "min": (0, 3, 7), "dim": (0, 3, 6), "aug": (0, 4, 8), "sus2": (0, 2, 7),
          "sus4": (0, 5, 7), "7": (0, 4, 7, 10), "min7": (0, 3, 7, 10), "maj7": (0, 4, 7, 11),
          "minmaj7": (0, 3, 7, 11), "dim7": (0, 3, 6, 9), "m7b5": (0, 3, 6, 10), "add9": (0, 4, 7, 14),
          "madd9": (0, 3, 7, 14), "5": (0, 7)}
SHAPE_SUFFIX = {"maj": "", "min": "m", "dim": "dim", "aug": "aug", "sus2": "sus2", "sus4": "sus4", "7": "7",
                "min7": "m7", "maj7": "maj7", "minmaj7": "m(maj7)", "dim7": "dim7", "m7b5": "m7b5", "add9": "add9",
                "madd9": "madd9", "5": "5"}
# Roman numeral suffix -> (shape for an upper-case numeral, shape for a lower-case one)
ROMAN_SUFFIX = {"": ("maj", "min"), "7": ("7", "min7"), "maj7": ("maj7", "minmaj7"), "M7": ("maj7", "minmaj7"),
                "Δ": ("maj7", "minmaj7"), "Δ7": ("maj7", "minmaj7"), "°": ("dim", "dim"), "o": ("dim", "dim"),
                "dim": ("dim", "dim"), "°7": ("dim7", "dim7"), "o7": ("dim7", "dim7"), "dim7": ("dim7", "dim7"),
                "ø": ("m7b5", "m7b5"), "ø7": ("m7b5", "m7b5"), "m7b5": ("m7b5", "m7b5"), "+": ("aug", "aug"),
                "aug": ("aug", "aug"), "sus": ("sus4", "sus4"), "sus2": ("sus2", "sus2"), "sus4": ("sus4", "sus4"),
                "add9": ("add9", "madd9"), "5": ("5", "5")}
NAME_SUFFIX = {"": "maj", "maj": "maj", "M": "maj", "m": "min", "min": "min", "7": "7", "m7": "min7",
               "min7": "min7", "maj7": "maj7", "M7": "maj7", "Δ": "maj7", "Δ7": "maj7", "mmaj7": "minmaj7",
               "m(maj7)": "minmaj7", "dim": "dim", "°": "dim", "o": "dim", "dim7": "dim7", "°7": "dim7", "o7": "dim7",
               "m7b5": "m7b5", "ø": "m7b5", "ø7": "m7b5", "aug": "aug", "+": "aug", "sus": "sus4", "sus2": "sus2",
               "sus4": "sus4", "add9": "add9", "madd9": "madd9", "5": "5"}


class HarmonyError(ValueError):
    pass


class Key(NamedTuple):
    pc: int  # 0 = C
    scale: str  # a name in parts.SCALES

    @property
    def steps(self):
        return parts.SCALES[self.scale]

    @property
    def flats(self):
        steps = self.steps
        relative_major = (self.pc + 3) % 12 if 3 in steps and 4 not in steps else self.pc
        return relative_major in _FLAT_MAJORS

    @property
    def name(self):
        return f"{pc_name(self.pc, self.flats)} {self.scale}"


@dataclass(frozen=True)
class Chord:
    symbol: str  # as the user wrote it, e.g. "i", "bVII", "Am7"
    root: int  # pitch class
    shape: tuple
    name: str  # e.g. "Am", "F", "Gsus4"


@dataclass(frozen=True)
class Progression:
    chords: tuple
    voicings: tuple  # per chord: the voiced notes, low to high
    bars_per_chord: int
    voicing: str
    key: Key
    start: int  # absolute bar where the first chord lands
    overrides: dict = field(default_factory=dict)  # track -> mode the user asked for

    @property
    def length(self):
        return len(self.chords) * self.bars_per_chord

    def index(self, bar):
        return ((bar - self.start) // self.bars_per_chord) % len(self.chords)


def pc_name(pc, flats=False):
    return (FLAT_NAMES if flats else SHARP_NAMES)[pc % 12]


def note_label(note, flats=False):
    return f"{pc_name(note, flats)}{note // 12}"


def _accidental(text):
    return sum(1 if c in "#♯" else -1 for c in text)


def _scale_name(steps):
    return next(name for name, s in parts.SCALES.items() if s == steps)


def parse_key(key, scale=None):
    """'Am' -> Key(9, 'minor'); ('F#', 'dorian') -> Key(6, 'dorian'). Raises HarmonyError."""
    if not isinstance(key, str) or not key.strip():
        raise HarmonyError(f"key must be a root like 'A', 'F#', 'Bb' or 'Am', got {key!r}")
    try:
        root, steps, _ = parts.parse_key(key.strip(), scale)
    except parts.PartError as exc:
        raise HarmonyError(str(exc)) from None
    return Key(root % 12, _scale_name(steps))


def key_of(pattern_key):
    """A Pattern's key tuple -> Key, or None."""
    return Key(*pattern_key) if pattern_key else None


def _seven(key):
    """The 7-note scale Roman numerals count in: the key's own, else its major or minor parent."""
    if len(key.steps) == 7:
        return key.steps
    return parts.SCALES["minor" if 3 in key.steps and 4 not in key.steps else "major"]


def split_chords(chords):
    if isinstance(chords, str):
        items = [t for t in _SPLIT.split(chords.strip()) if t]
    elif isinstance(chords, (list, tuple)):
        items = list(chords)
    else:
        raise HarmonyError("chords must be a list like ['i', 'VI', 'III', 'VII'] or a string 'Am F C G'")
    if not items:
        raise HarmonyError("chords is empty: give 1-16 chords, e.g. ['i', 'VI', 'III', 'VII']")
    if len(items) > MAX_CHORDS:
        raise HarmonyError(f"at most {MAX_CHORDS} chords, got {len(items)}")
    for item in items:
        if not isinstance(item, str) or not item.strip():
            raise HarmonyError(f"each chord must be text like 'VI' or 'Am', got {item!r}")
    return [i.strip() for i in items]


def parse_chord(symbol, key):
    """One chord symbol -> Chord. Roman numerals need key (a Key); chord names don't. Raises HarmonyError."""
    m = _ROMAN.match(symbol)
    if m:
        acc, numeral, suffix = m.groups()
        if suffix not in ROMAN_SUFFIX:
            raise HarmonyError(f"can't read chord {symbol!r}: after the numeral use one of "
                               "7, maj7, dim (°), dim7, ø, aug (+), sus2, sus4, add9, 5")
        upper = numeral.isupper()
        shape = ROMAN_SUFFIX[suffix][0 if upper else 1]
        steps = _seven(key)
        root = (key.pc + steps[DEGREES[numeral.lower()] - 1] + _accidental(acc)) % 12
        return Chord(symbol, root, SHAPES[shape], pc_name(root, key.flats) + SHAPE_SUFFIX[shape])
    m = _NAME.match(symbol)
    if m and m.group(3) in NAME_SUFFIX:
        letter, acc, suffix = m.groups()
        root = (parts.PITCH_CLASS[letter.upper()] + _accidental(acc)) % 12
        shape = NAME_SUFFIX[suffix]
        flats = "b" in acc or "♭" in acc or (not acc and key.flats)
        return Chord(symbol, root, SHAPES[shape], pc_name(root, flats) + SHAPE_SUFFIX[shape])
    raise HarmonyError(f"can't read chord {symbol!r}: use Roman numerals in the key (i, VI, III, VII, ii7, V7, "
                       "bVII; upper case = major, lower = minor) or names (Am, F, C, G7, Bbmaj7)")


def parse_chords(chords, key):
    return [parse_chord(s, key) for s in split_chords(chords)]


def check_bars_per_chord(value):
    if value in (None, ""):
        return 1
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float("nan")
    if isinstance(value, bool) or not (1 <= number <= BARS_PER_CHORD_MAX and number == int(number)):
        raise HarmonyError(f"bars_per_chord must be a whole number 1-{BARS_PER_CHORD_MAX}, got {value!r}")
    return int(number)


def check_voicing(value):
    if value in (None, ""):
        return "close"
    word = str(value).strip().lower()
    if word not in VOICINGS:
        raise HarmonyError(f"voicing must be one of {', '.join(VOICINGS)}, got {value!r}")
    return word


def check_modes(tracks):
    """{"7": "chords", "6": "root"} -> {7: 'chords', 6: 'root'}. Syntax only; roles are checked by the engine."""
    if tracks in (None, {}):
        return {}
    if not isinstance(tracks, dict):
        raise HarmonyError('tracks must map track to a mode, e.g. {"7": "chords", "6": "root"}')
    out = {}
    for raw, mode in tracks.items():
        try:
            track = int(str(raw).strip())
        except (TypeError, ValueError):
            track = 0
        if isinstance(raw, bool) or not 1 <= track <= 16:
            raise HarmonyError(f"track must be 1-16, got {raw!r}")
        word = str(mode).strip().lower() if isinstance(mode, str) else None
        if word not in MODES:
            raise HarmonyError(f"track {track}: mode must be one of {', '.join(MODES)}, got {mode!r}")
        out[track] = word
    return out


# ---- voicing ---------------------------------------------------------------

def _shapes(chord, voicing):
    """[(lowest note's pitch class, offsets from it)] the voicing may use."""
    iv = chord.shape
    if voicing == "power":
        fifth = iv[2] if len(iv) > 2 else iv[-1]
        return [(chord.root, (0, fifth, 12))]
    if voicing == "root":
        return [(chord.root, iv)]
    if voicing == "open":
        if len(iv) < 3:
            return [(chord.root, (0, iv[-1], 12))]
        return [(chord.root, (0, iv[2], iv[1] + 12, *[x + 12 for x in iv[3:]]))]
    pcs = sorted({x % 12 for x in iv})  # close: every inversion, stacked inside an octave
    out = []
    for r in range(len(pcs)):
        rotated = pcs[r:] + [p + 12 for p in pcs[:r]]
        out.append(((chord.root + pcs[r]) % 12, tuple(p - pcs[r] for p in rotated)))
    return out


def _candidates(chord, voicing, floor, low, high):
    """Voicings with every note in low..high and the median at or above floor."""
    out = []
    for bass_pc, offsets in _shapes(chord, voicing):
        for base in range(patterns.NOTE_MIN, patterns.NOTE_MAX + 1):
            if base % 12 != bass_pc:
                continue
            notes = tuple(base + o for o in offsets)
            if low <= notes[0] and notes[-1] <= high and statistics.median(notes) >= floor:
                out.append(notes)
    return out


def _voice_one(chord, voicing, prev):
    cands = (_candidates(chord, voicing, CHORD_LOW, CHORD_BOTTOM, CHORD_HIGH)
             or _candidates(chord, voicing, 0, patterns.NOTE_MIN, patterns.NOTE_MAX))

    def centre(notes):
        return abs(statistics.median(notes) - CENTER)

    def score(notes):
        if prev is None or voicing != "close":
            return (centre(notes), notes)
        if len(notes) == len(prev):
            move = sum(abs(a - b) for a, b in zip(notes, prev))
        else:
            move = abs(statistics.mean(notes) - statistics.mean(prev)) * len(notes)
        return (move + 0.25 * centre(notes), notes)
    return min(cands, key=score)


def voice(chords, voicing="close"):
    """Chords -> one tuple of notes per chord, low to high, near native pitch; close voicings are voice-led."""
    out, prev = [], None
    for chord in chords:
        notes = _voice_one(chord, voicing, prev)
        out.append(notes)
        prev = notes
    return tuple(out)


# ---- keys and snapping -----------------------------------------------------

def snap(note, key):
    """Nearest note of the key's scale inside 16-84 (ties go down)."""
    steps = key.steps
    for d in range(0, 12):
        for cand in (note - d, note + d):
            if patterns.NOTE_MIN <= cand <= patterns.NOTE_MAX and (cand - key.pc) % 12 in steps:
                return cand
    return min(patterns.NOTE_MAX, max(patterns.NOTE_MIN, note))


def nearest(pc, anchor):
    """The note with pitch class pc nearest anchor (ties go down), kept inside 16-84."""
    below = anchor - ((anchor - pc) % 12)
    note = below if anchor - below <= below + 12 - anchor else below + 12
    while note < patterns.NOTE_MIN:
        note += 12
    while note > patterns.NOTE_MAX:
        note -= 12
    return note


def remap(note, home, key, shift):
    """Move one note from home key to key by scale degree; a note outside the home scale keeps its offset."""
    rel = (note - home.pc) % 12
    tonic = note - rel + shift
    hs, ks = home.steps, key.steps
    if len(hs) == len(ks):
        below = max(i for i, s in enumerate(hs) if s <= rel)
        out = tonic + ks[below] + (rel - hs[below])
    else:
        out = snap(note + shift, key)
    return min(patterns.NOTE_MAX, max(patterns.NOTE_MIN, out))


def in_key(pattern, key):
    """pattern with its melodic tracks moved into key (drum tracks untouched), register re-applied.

    The move is the smallest one (-6..+5 semitones) between the tonics, then degree by degree, so
    A minor -> F minor moves the bass down 4 and A minor -> C major turns the minor third into a major one.
    """
    home = key_of(pattern.key)
    if key is None or home is None or tuple(key) == tuple(home):
        return pattern
    shift = ((key.pc - home.pc + 6) % 12) - 6
    bars = {}
    for track, track_bars in pattern.bars.items():
        if not patterns.is_melodic(track_bars):
            bars[track] = track_bars
            continue
        bars[track] = [[(s, remap(n, home, key, shift), v, g) for s, n, v, g in bar] for bar in track_bars]
    lifted = patterns.register(replace(pattern, bars=bars, key=tuple(key)))
    shifts = {t: pattern.shifts.get(t, 0) + s for t, s in lifted.shifts.items()}
    return replace(lifted, shifts={t: s for t, s in shifts.items() if s})


# ---- tracks ----------------------------------------------------------------

def role_of(track, pattern, kit_tracks):
    """A track's role: the user's label, else the routed pattern's role, else 'other'."""
    if track in kit_tracks:
        return kit_tracks[track][0]
    role = pattern.roles.get(track) if pattern is not None else None
    return kitmap.generated_role(role) if role else "other"


def refused(overrides, pattern, kit_tracks):
    """{track: role} for overrides that would put notes on a drum, cymbal or fx track."""
    return {t: role_of(t, pattern, kit_tracks) for t, mode in overrides.items()
            if mode != "off" and role_of(t, pattern, kit_tracks) in NEVER}


def modes(pattern, kit_tracks, overrides, written, work):
    """-> (modes {track: mode}, ranks {track: chord-track rank}, pad tracks).

    Roles pick the default (chord/pad/stab -> chords, bass -> root, lead -> snap; drums, cymbal, fx and
    other never change). Written parts play as written unless the user named the track. A chord or stack
    track with no line at all gets a held tone per bar (pads).
    """
    tracks = set(pattern.bars if pattern is not None else ()) | set(kit_tracks) | set(overrides)
    out = {}
    for track in sorted(tracks):
        if track in overrides:
            mode = overrides[track]
        elif track in written:
            continue
        else:
            mode = ROLE_MODES.get(role_of(track, pattern, kit_tracks))
        if mode and mode != "off":
            out[track] = mode
    chord_tracks = [t for t, m in sorted(out.items()) if m == "chords"]
    ranks = {t: i for i, t in enumerate(chord_tracks)}
    pads = frozenset(t for t, m in out.items() if m in ("chords", "stack") and not any(work.get(t) or []))
    return out, ranks, pads


def pad_line():
    """One held hit per bar, for a chord track with no line of its own (working hit shape)."""
    return [(0, patterns.NATIVE, PAD_VELOCITY, PAD_GATE, 0.0)]


def apply(mode, hits, notes, root, key, rank):
    """One bar of one track's hits (working shape) reshaped for the chord now playing.

    notes: the chord's voiced notes (low to high); root: its pitch class; key: the progression's Key.
    """
    if not hits:
        return hits
    if mode == "stack":
        return [(s, n, v, g, o) for s, _, v, g, o in hits for n in notes]
    if mode == "chords":
        down = notes[::-1]  # the top voice first: the most audible line
        return [(s, down[(rank + i) % len(down)], v, g, o) for i, (s, _, v, g, o) in enumerate(hits)]
    if mode == "root":
        anchor = statistics.median(h[1] for h in hits)
        note = nearest(root, round(anchor))
        return [(s, note, v, g, o) for s, _, v, g, o in hits]
    if mode == "snap":
        return [(s, snap(n, key), v, g, o) for s, n, v, g, o in hits]
    return hits


def describe(prog):
    """The progression for tool results."""
    flats = prog.key.flats
    return [{"chord": c.symbol, "name": c.name, "notes": list(v), "note_names": [note_label(n, flats) for n in v]}
            for c, v in zip(prog.chords, prog.voicings)]
