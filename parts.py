"""Written parts behind whiplash_write_part: pure parsing, no MIDI, no engine state.

A written part replaces one track's line in the working pattern. build() validates everything
and returns a Part whose bars use the working hit shape of mutate.working():
(step, note, velocity, length_steps, offset_ticks). The engine plays a written part's length as
the exact note-off time (no GATE factor). See docs/digitakt-ii/reference.md §5.2 for when the unit
actually ends a sound on note-off, and §6.1 for note 60 = native pitch and the 16-84 range.

Notes are named in Elektron octave numbering (0 = C0, C5 = MIDI 60), given as MIDI numbers, or,
when a key is given, as scale degrees ("1 3 5 b7"; accidentals move the degree by a semitone).
"""
import re
from dataclasses import dataclass

from . import patterns

STEPS = patterns.STEPS
LOOP_BARS = patterns.BARS
BAR_CHOICES = (1, 2, 4)  # the loop is 4 bars, so a part repeats evenly
LENGTH_MIN, LENGTH_MAX = 0.25, 16.0  # in 16th-note steps
DEFAULT_LENGTH = 1.0
DEFAULT_VELOCITY = 100
ACCENT, UNACCENTED = 120, 90  # velocity: "accent" puts 120 on the beats (steps 0, 4, 8, 12), 90 elsewhere
MAX_NOTES = 64

RHYTHMS = {
    "four_on_floor": "x...x...x...x...",
    "offbeat_8ths": "..x...x...x...x.",
    "8ths": "x.x.x.x.x.x.x.x.",
    "16ths": "xxxxxxxxxxxxxxxx",
    "off_16ths": ".x.x.x.x.x.x.x.x",
    "syncopated": "x..x..x...x..x..",
    "half_time": "x.......x.......",
}
LOCK_RHYTHMS = {"on_kick": 1}  # copies track 1's hits at call time, like lock_to: 1
RHYTHM_ALIASES = {
    "four_on_the_floor": "four_on_floor", "4otf": "four_on_floor", "4_on_the_floor": "four_on_floor",
    "quarters": "four_on_floor", "offbeat": "offbeat_8ths", "offbeats": "offbeat_8ths", "eighths": "8ths",
    "sixteenths": "16ths", "offbeat_16ths": "off_16ths", "halftime": "half_time", "kick": "on_kick",
    "lock_to_kick": "on_kick",
}

SCALES = {
    "major": (0, 2, 4, 5, 7, 9, 11), "minor": (0, 2, 3, 5, 7, 8, 10),
    "dorian": (0, 2, 3, 5, 7, 9, 10), "phrygian": (0, 1, 3, 5, 7, 8, 10), "lydian": (0, 2, 4, 6, 7, 9, 11),
    "mixolydian": (0, 2, 4, 5, 7, 9, 10), "locrian": (0, 1, 3, 5, 6, 8, 10),
    "harmonic_minor": (0, 2, 3, 5, 7, 8, 11), "melodic_minor": (0, 2, 3, 5, 7, 9, 11),
    "major_pentatonic": (0, 2, 4, 7, 9), "minor_pentatonic": (0, 3, 5, 7, 10),
    "blues": (0, 3, 5, 6, 7, 10), "chromatic": tuple(range(12)),
}
SCALE_ALIASES = {"ionian": "major", "aeolian": "minor", "natural_minor": "minor", "pentatonic": "minor_pentatonic"}
PITCH_CLASS = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
_NAME = re.compile(r"^([A-Ga-g])([#b♯♭]*)(-?\d+)$")
_KEY = re.compile(r"^([A-Ga-g])([#b♯♭]*)(-?\d+)?\s*(m|min|minor|maj|major)?$")
_DEGREE = re.compile(r"^([#b♯♭]*)(\d+)$")
RESTS = {".", "-", "_", "r", "rest"}


class PartError(ValueError):
    pass


@dataclass(frozen=True)
class Part:
    bars: list  # LOOP_BARS bars of (step, note, velocity, length_steps, 0.0), already expanded to the loop
    source: str  # how the hits were placed: rhythm name, "grid", "steps", "hits" or "lock_to N"
    bars_written: int  # 1, 2 or 4: the part repeats every bars_written bars
    unused_notes: int = 0  # notes that did not fit in 4 bars of hits
    key: str = None


def _accidental(text):
    return sum(1 if c in "#♯" else -1 for c in text)


def note_number(text):
    """'C5' -> 60, 'D#5' -> 63, 'Eb4' -> 51 (Elektron numbering: 0 = C0). Raises PartError."""
    m = _NAME.match(str(text).strip())
    if not m:
        raise PartError(f"can't read note {text!r}: use a name like C5, D#5 or Eb4 (C5 = MIDI 60), or a MIDI number")
    letter, acc, octave = m.groups()
    return int(octave) * 12 + PITCH_CLASS[letter.upper()] + _accidental(acc)


def parse_key(key, scale=None):
    """('A', 'minor') -> (57, (0, 2, 3, ...), 'A4 minor'). Root defaults to the octave nearest note 60."""
    m = _KEY.match(str(key).strip())
    if not m:
        raise PartError(f"can't read key {key!r}: use a root like C, F#, Bb, Am or A3 (Elektron octaves, C5 = 60)")
    letter, acc, octave, quality = m.groups()
    pc = (PITCH_CLASS[letter.upper()] + _accidental(acc)) % 12
    if octave is not None:
        root = int(octave) * 12 + PITCH_CLASS[letter.upper()] + _accidental(acc)
    else:
        root = 48 + pc if 48 + pc >= 54 else 60 + pc  # nearest to 60: F#4 (54) .. F5 (65)
    if scale in (None, ""):
        scale = "minor" if quality and quality.startswith("m") and not quality.startswith("maj") else "major"
    name = str(scale).strip().lower().replace(" ", "_").replace("-", "_")
    name = SCALE_ALIASES.get(name, name)
    if name not in SCALES:
        raise PartError(f"unknown scale {scale!r}; scales: {', '.join(SCALES)}")
    if not patterns.NOTE_MIN <= root <= patterns.NOTE_MAX:
        raise PartError(f"key root {key!r} is MIDI {root}, outside {patterns.NOTE_MIN}-{patterns.NOTE_MAX}")
    return root, SCALES[name], f"{patterns.note_name(root)} {name}"


def degree_note(text, root, scale):
    """'1' -> root, '5' -> fifth, 'b7' -> flattened seventh, '8' -> octave. Raises PartError."""
    m = _DEGREE.match(str(text).strip())
    if not m or int(m.group(2)) < 1:
        raise PartError(f"can't read scale degree {text!r}: use 1-21, optionally with b or # (e.g. b7)")
    index = int(m.group(2)) - 1
    octave, step = divmod(index, len(scale))
    return root + 12 * octave + scale[step] + _accidental(m.group(1))


def _split(notes):
    if isinstance(notes, str):
        return [t for t in re.split(r"[\s,]+", notes.strip()) if t]
    if isinstance(notes, (list, tuple)):
        return list(notes)
    return [notes]


def parse_note(value, key=None):
    """One note entry -> MIDI number, or None for a rest. key = (root, scale) makes numbers degrees."""
    if isinstance(value, bool):
        raise PartError(f"can't read note {value!r}")
    if isinstance(value, str) and value.strip().lower() in RESTS:
        return None
    if key is not None and isinstance(value, (int, float, str)) and _DEGREE.match(str(value).strip()):
        if isinstance(value, float) and value != int(value):
            raise PartError(f"scale degree must be whole, got {value!r}")
        note = degree_note(str(int(value)) if isinstance(value, (int, float)) else value, *key)
    elif isinstance(value, (int, float)) or (isinstance(value, str) and re.fullmatch(r"\d+", value.strip())):
        number = float(value)
        if number != int(number):
            raise PartError(f"MIDI note must be a whole number, got {value!r}")
        note = int(number)
    elif isinstance(value, str):
        note = note_number(value)
    else:
        raise PartError(f"can't read note {value!r}")
    if not patterns.NOTE_MIN <= note <= patterns.NOTE_MAX:
        raise PartError(f"note {value!r} is MIDI {note}, outside {patterns.NOTE_MIN}-{patterns.NOTE_MAX} "
                        f"({patterns.note_name(patterns.NOTE_MIN)}-{patterns.note_name(patterns.NOTE_MAX)}, the "
                        "manual's documented chromatic range)")
    return note


def parse_notes(notes, key=None):
    items = _split(notes)
    if not items:
        raise PartError("notes is empty: give at least one note, e.g. ['C5', 'D#5', 'G5']")
    if len(items) > MAX_NOTES:
        raise PartError(f"at most {MAX_NOTES} notes, got {len(items)}")
    out = [parse_note(v, key) for v in items]
    if all(n is None for n in out):
        raise PartError("notes has only rests")
    return out


def check_length(value, what="length"):
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float("nan")
    if isinstance(value, bool) or not LENGTH_MIN <= number <= LENGTH_MAX:  # NaN fails too
        raise PartError(f"{what} must be {LENGTH_MIN:g}-{LENGTH_MAX:g} steps (1 = a 16th, 4 = a beat), got {value!r}")
    return number


def check_velocity(value, what="velocity"):
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float("nan")
    if isinstance(value, bool) or not (1 <= number <= 127 and number == int(number)):
        raise PartError(f"{what} must be a whole number 1-127, got {value!r}")
    return int(number)


def _cycle_values(value, check, what):
    """A single value or a list cycled over the hits -> list of checked values."""
    items = list(value) if isinstance(value, (list, tuple)) else [value]
    if not items or len(items) > MAX_NOTES:
        raise PartError(f"{what} list must have 1-{MAX_NOTES} entries")
    return [check(v, what) for v in items]


def check_step(value):
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float("nan")
    if isinstance(value, bool) or not (0 <= number < STEPS and number == int(number)):
        raise PartError(f"step must be a whole number 0-15 (0 = the downbeat, 4 = beat 2), got {value!r}")
    return int(number)


def parse_grid_bar(text):
    """'x..x ..x. ...' -> [(step, accent)]. x or o = hit, X = accented hit, . or - = rest; spaces and | ignored."""
    if not isinstance(text, str):
        raise PartError(f"each grid bar must be a string like 'x...x...x...x...', got {text!r}")
    cells = [c for c in text if c not in " |"]
    if len(cells) != STEPS or any(c not in "xXo.-_" for c in cells):
        raise PartError(f"grid bar must be 16 cells of x (hit), X (accent) or . (rest), got {text!r}")
    return [(s, c == "X") for s, c in enumerate(cells) if c in "xXo"]


def _rhythm(name):
    key = str(name).strip().lower().replace("-", "_").replace(" ", "_")
    key = RHYTHM_ALIASES.get(key, key)
    if key in RHYTHMS or key in LOCK_RHYTHMS:
        return key
    raise PartError(f"unknown rhythm {name!r}; rhythms: {', '.join([*RHYTHMS, *LOCK_RHYTHMS])}")


def rhythm_names():
    return [*RHYTHMS, *LOCK_RHYTHMS]


def placement(rhythm=None, grid=None, steps=None, hits=None, lock_to=None):
    """Exactly one way to place hits -> (kind, value). Rhythm 'on_kick' becomes lock_to 1."""
    given = [k for k, v in (("rhythm", rhythm), ("grid", grid), ("steps", steps), ("hits", hits),
                            ("lock_to", lock_to)) if v not in (None, "", [])]
    if len(given) != 1:
        raise PartError("give exactly one of rhythm, grid, steps, hits or lock_to to place the notes "
                        f"(got {', '.join(given) or 'none'})")
    if given == ["rhythm"]:
        name = _rhythm(rhythm)
        if name in LOCK_RHYTHMS:
            return "lock_to", LOCK_RHYTHMS[name]
        return "rhythm", name
    kind = given[0]
    return kind, {"grid": grid, "steps": steps, "hits": hits, "lock_to": lock_to}[kind]


def _slots(kind, value, source_bars):
    """Hit slots before notes: list per bar of [(step, accent, overrides)]; and how many bars that pattern spans."""
    if kind == "rhythm":
        return [[(s, False, {}) for s, _ in parse_grid_bar(RHYTHMS[value])]], 1
    if kind == "grid":
        bars = [value] if isinstance(value, str) else list(value) if isinstance(value, (list, tuple)) else None
        if not bars or len(bars) > LOOP_BARS:
            raise PartError("grid must be one 16-cell bar like 'x...x...x...x...', or a list of up to 4 bars")
        return [[(s, a, {}) for s, a in parse_grid_bar(b)] for b in bars], len(bars)
    if kind == "steps":
        items = list(value) if isinstance(value, (list, tuple)) else [value]
        nested = items and all(isinstance(i, (list, tuple)) for i in items)
        bars = items if nested else [items]
        if not bars or len(bars) > LOOP_BARS:
            raise PartError("steps must be a list of steps 0-15 (one bar), or a list of up to 4 such lists")
        out = []
        for bar in bars:
            if isinstance(bar, (list, tuple)) and any(isinstance(s, (list, tuple, dict)) for s in bar):
                raise PartError("steps must be numbers 0-15 (or one list of them per bar)")
            out.append([(s, False, {}) for s in sorted({check_step(s) for s in bar})])
        return out, len(bars)
    if kind == "hits":
        if not isinstance(value, (list, tuple)) or not value or len(value) > STEPS * LOOP_BARS:
            raise PartError(f"hits must be a list of 1-{STEPS * LOOP_BARS} objects like "
                            "{'step': 0, 'note': 'C5', 'length': 2, 'velocity': 110, 'bar': 1}")
        bars = [dict() for _ in range(LOOP_BARS)]
        for hit in value:
            if not isinstance(hit, dict) or "step" not in hit:
                raise PartError(f"each hit needs a step, e.g. {{'step': 0, 'note': 'C5'}}, got {hit!r}")
            unknown = set(hit) - {"step", "note", "length", "velocity", "bar"}
            if unknown:
                raise PartError(f"unknown hit field(s) {sorted(unknown)}; use step, note, length, velocity, bar")
            step = check_step(hit["step"])
            bar = hit.get("bar", 1)
            try:
                bar_n = float(bar)
            except (TypeError, ValueError):
                bar_n = float("nan")
            if isinstance(bar, bool) or not (1 <= bar_n <= LOOP_BARS and bar_n == int(bar_n)):
                raise PartError(f"hit bar must be 1-{LOOP_BARS} (1 = the first bar of the loop), got {bar!r}")
            over = {k: hit[k] for k in ("note", "length", "velocity") if hit.get(k) is not None}
            bars[int(bar_n) - 1][step] = over  # a later hit on the same step replaces an earlier one
        span = max(i + 1 for i, b in enumerate(bars) if b)
        return [[(s, False, o) for s, o in sorted(b.items())] for b in bars[:span]], span
    # lock_to: the source track's current hits, all 4 bars, taken at call time
    return [[(s, False, {}) for s in sorted({h[0] for h in bar})] for bar in source_bars], LOOP_BARS


def build(kind, value, notes=None, key=None, scale=None, length=None, velocity=None, bars=None,
          source_bars=None, default_note=None):
    """Validate and build a Part. Raises PartError on any bad input; never touches the engine.

    source_bars: the lock_to source track's bars (working hit shape) when kind == 'lock_to'.
    default_note: what plays when no notes are given (the drum note 60, the sample's own pitch).
    """
    keyspec = None
    key_name = None
    if key not in (None, ""):
        root, steps_, key_name = parse_key(key, scale)
        keyspec = (root, steps_)
    elif scale not in (None, ""):
        raise PartError("scale needs a key, e.g. key: 'A', scale: 'minor'")
    note_list = parse_notes(notes, keyspec) if notes not in (None, "", []) else None
    lengths = _cycle_values(DEFAULT_LENGTH if length in (None, "") else length, check_length, "length")
    accent = isinstance(velocity, str) and velocity.strip().lower() == "accent"
    if accent or velocity in (None, ""):
        velocities = None
    else:
        velocities = _cycle_values(velocity, check_velocity, "velocity")
    if kind == "lock_to" and not (source_bars and any(source_bars)):
        raise PartError("the lock_to track has no hits to copy")
    slots, span = _slots(kind, value, source_bars)
    if not any(slots):
        raise PartError("that places no hits: put at least one x in the grid or one step")
    if bars in (None, ""):
        bars_n = None
    else:
        try:
            bars_n = float(bars)
        except (TypeError, ValueError):
            bars_n = float("nan")
        if isinstance(bars, bool) or bars_n not in BAR_CHOICES:
            raise PartError(f"bars must be 1, 2 or 4 (the loop is 4 bars, so the part repeats evenly), got {bars!r}")
        bars_n = int(bars_n)
        if bars_n < span:
            raise PartError(f"bars is {bars_n} but the hits span {span} bars")
    if bars_n is None:  # the shortest even span that plays every note at least once
        bars_n = next((b for b in BAR_CHOICES if b >= span), LOOP_BARS)
        if note_list:
            while bars_n < LOOP_BARS and _count(slots, bars_n) < len(note_list):
                bars_n *= 2
    laid = [slots[i % len(slots)] for i in range(bars_n)]  # a 3-bar grid plays bars 1, 2, 3, 1
    out, n = [], 0
    for bar in laid:
        hits = []
        for step, accented, over in bar:
            if "note" in over:
                note = parse_note(over["note"], keyspec)
            elif note_list:
                note = note_list[n % len(note_list)]
            else:
                note = patterns.DRUM if default_note is None else default_note
            hit_len = check_length(over["length"]) if "length" in over else lengths[n % len(lengths)]
            if "velocity" in over:
                vel = check_velocity(over["velocity"])
            elif velocities:
                vel = velocities[n % len(velocities)]
            elif accent or accented:
                vel = ACCENT if (accented or step % 4 == 0) else UNACCENTED
            else:
                vel = DEFAULT_VELOCITY
            n += 1
            if note is not None:  # a rest still uses up its hit
                hits.append((step, note, vel, hit_len, 0.0))
        out.append(hits)
    if not any(out):
        raise PartError("every hit landed on a rest")
    unused = max(0, len(note_list) - n) if note_list else 0
    loop = [out[i % bars_n] for i in range(LOOP_BARS)]
    source = kind if kind != "rhythm" else value
    if kind == "lock_to":
        source = f"lock_to {value}"
    return Part(bars=loop, source=source, bars_written=bars_n, unused_notes=unused, key=key_name)


def _count(slots, bars_n):
    return sum(len(slots[i % len(slots)]) for i in range(bars_n))


def describe(part):
    """Echo of the written bars: steps with numbers and names, plus a grid line per bar."""
    out = []
    for i, bar in enumerate(part.bars[:part.bars_written]):
        cells = ["."] * STEPS
        for s, *_ in bar:
            cells[s] = "x"
        out.append({"bar": i + 1, "grid": "".join(cells),
                    "hits": [{"step": s, "note": n, "name": patterns.note_name(n), "length": ln, "velocity": v}
                             for s, n, v, ln, _ in bar]})
    return out
