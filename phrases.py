"""Phrase generators (v0.9.0, ontology O1b): bass and stab lines written from the chords. Pure tables and builders.

A phrase is a grid of hits with a tone per hit (R, 5, oct, chord, ...: harmony.parse_tone). build() turns it into a
written part whose notes are harmony.Rel values: each plays the note it resolves to against the chord it was
written for, and the engine re-resolves it at the bar line against the chord playing (harmony.apply mode phrase),
so the line follows any progression and key change from then on.

With no progression playing, a phrase follows a fallback (fallback()): the genre's default progression when its
record has one (classic house: house.piano_stab), else the key's tonic triad. Fallbacks are prepared in the tool
thread; the bar line only looks them up (cached()).

Every phrase's line goes through the v0.5 rule: median at or above 53, notes in 16-84 (reference.md §6.1).
"""
import statistics
from dataclasses import dataclass

from . import harmony, mutate, parts, patterns, progressions

DEFAULT_ORDER = (0, 8, 4, 12, 2, 10, 6, 14, 1, 9, 5, 13, 3, 11, 7, 15)  # beat strength: kept first as density falls
SEED_TONES = ("5", "oct", "3")  # what a seeded phrase's turnaround bar picks its passing tones from
ROLES = ("bass", "lead", "stab", "chord", "pad")
REGISTERS = tuple(harmony.REGISTER_FLOORS)
SEED_MAX_CHARS = 40


class PhraseError(ValueError):
    pass


@dataclass(frozen=True)
class Phrase:
    name: str
    role: str  # bass | lead | stab | chord | pad (kitmap.MELODIC)
    grid: tuple  # 1, 2 or 4 bars of 16 cells: x hit, X accent, . rest
    tones: tuple  # per grid hit, cycled: "R", "R+12", "5", "chord", "approach", "step-1", ...
    register: str  # low | mid | high: the floor of the window the chord root lands in (harmony.REGISTER_FLOORS)
    length: tuple  # steps per grid hit, cycled
    velocity: tuple  # 1-127 per grid hit, cycled
    variation: str = "none"  # none | seeded (the 4th bar re-picks its passing tones from the seed)
    on_request: bool = False  # True: never a genre default (leads, Q-P3)
    order: tuple = DEFAULT_ORDER  # steps, most important first: which hits stay as density falls
    density: float = 1.0  # the default density
    tags: frozenset = frozenset()
    source: str = ""
    about: str = ""

    @property
    def chordal(self):
        return any(harmony.parse_tone(t)[0] == "chord" for t in self.tones)


def _p(name, role, grid, tones, register, length, velocity, source, about, tags=(), **kw):
    return Phrase(name, role, tuple([grid] if isinstance(grid, str) else grid), tuple(tones), register,
                  tuple(length), tuple(velocity), tags=frozenset(tags), source=source, about=about, **kw)


PHRASES = {p.name: p for p in (
    _p("bass.rolling_deep", "bass", "x..x..x.x..x..x.", ("R", "R", "5", "R", "oct", "5"), "low",
       (3, 1, 2, 3, 1, 2), (100, 80, 84, 96, 80, 84), "§1 BeatKey, TPS, SONAA",
       "Rolling deep house bass: sustained roots with the 5th and octave passing; bar 4 varies with the seed",
       tags=("bass", "deephouse", "rolling", "warm"), variation="seeded"),
    _p("bass.octave_pump", "bass", "x.x.x.x.x.x.x.x.", ("R", "oct"), "low", (1,), (108, 96), "§2 SONAA",
       "The Chicago octave bounce: the root on each beat, its octave on each off-beat 8th",
       tags=("bass", "house", "chicago", "jacking")),
    _p("bass.bouncy", "bass", "..xx..x...xx..x.", ("R", "R", "R", "R", "oct", "R"), "low", (1,),
       (108, 84, 108, 108, 84, 108), "§3 Mix Elite, TPS",
       "Short bouncy tech house bass around the off-beats, an octave jump on 11",
       tags=("bass", "techhouse", "bouncy", "funky")),
    _p("bass.offbeat", "bass", "..xx..xx..xx..xx", ("R",), "low", (1,), (100, 80), "§5 Schunk, §6 Brizm",
       "Off-beat root bass; density 1 adds the rolling 16th after each off-beat",
       tags=("bass", "techno", "driving", "hypnotic"), order=(2, 6, 10, 14, 3, 7, 11, 15), density=0.5),
    _p("stab.offbeat", "stab", "..x...x...x...x.", ("chord",), "mid", (1,), (100, 88, 88, 88),
       "§2 MusicRadar, Attack",
       "Off-beat chord stabs, never on the kick's downbeat; each stab track plays its own chord tone",
       tags=("stab", "house", "techhouse", "techno", "piano"), order=(6, 14, 2, 10)),
)}


# ---- validation -------------------------------------------------------------

def check_density(value, phrase):
    if value in (None, ""):
        return phrase.density
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float("nan")
    if isinstance(value, bool) or not 0 < number <= 1:
        raise PhraseError(f"density must be above 0 and at most 1 (1 = every hit of the phrase), got {value!r}")
    return number


def check_register(value, phrase):
    """-> the floor of the window the chord root lands in (low 53, mid 60, high 67; an anchor note n gives n - 5)."""
    if value in (None, ""):
        return harmony.REGISTER_FLOORS[phrase.register]
    if isinstance(value, str) and value.strip().lower() in harmony.REGISTER_FLOORS:
        return harmony.REGISTER_FLOORS[value.strip().lower()]
    try:
        note = parts.parse_note(value)
    except parts.PartError:
        note = None
    if note is None or isinstance(value, bool):
        raise PhraseError(f"register must be low, mid, high or an anchor note like 'A3' or 57, got {value!r}")
    return max(patterns.NOTE_MIN, note - 5)


def check_seed(value):
    if value in (None, ""):
        return 0
    if isinstance(value, bool) or not isinstance(value, (int, str)) or len(str(value)) > SEED_MAX_CHARS:
        raise PhraseError(f"seed must be a whole number or a short word, got {value!r}")
    return value


# ---- building ---------------------------------------------------------------

def _rank(phrase, step):
    return phrase.order.index(step) if step in phrase.order else len(phrase.order) + step


def shape(phrase, density=None, seed=0):
    """4 bars of [(step, tone, octave, velocity, length)]: the phrase before any chord, density applied."""
    density = phrase.density if density is None else density
    out = []
    for bar in range(patterns.BARS):
        cells = parts.parse_grid_bar(phrase.grid[bar % len(phrase.grid)])
        hits = []
        for i, (step, accent) in enumerate(cells):
            tone = phrase.tones[i % len(phrase.tones)]
            if phrase.variation == "seeded" and bar == patterns.BARS - 1 and tone not in ("R",):
                tone = mutate.rng(seed, "phrase", phrase.name, bar, step).choice(SEED_TONES)
            tone, octave = harmony.parse_tone(tone)
            vel = min(127, phrase.velocity[i % len(phrase.velocity)] + (15 if accent else 0))
            hits.append((step, tone, octave, vel, phrase.length[i % len(phrase.length)]))
        keep = max(1, round(density * len(hits)))
        kept = sorted(hits, key=lambda h: _rank(phrase, h[0]))[:keep]
        out.append(sorted(kept))
    return out


def loop_chords(prog):
    """Per loop bar of a progression starting at bar 0: (Chord, voiced notes, next chord's root)."""
    out = []
    for bar in range(patterns.BARS):
        i, j = prog.index(bar), prog.index(bar + 1)
        out.append((prog.chords[i], prog.voicings[i], prog.chords[j].root))
    return out


def build(phrase, prog, density=None, seed=0, floor=None, rank=0):
    """-> (4 bars of working hits (step, Rel, velocity, length, 0.0), floor used).

    Each Rel's value is the note it plays against prog (a fallback() or the progression playing), bar for bar.
    The v0.5 rule: if the line's median falls below 53, the register window moves up an octave.
    """
    floor = harmony.REGISTER_FLOORS[phrase.register] if floor is None else floor
    chords = loop_chords(prog)
    lines = shape(phrase, density, seed)
    for _ in range(3):
        bars = []
        for (chord, notes, nxt), bar in zip(chords, lines):
            hits = []
            for step, tone, octave, vel, length in bar:
                rel = harmony.Rel(0, tone, octave, floor)
                note = harmony.resolve(rel, chord, notes, prog.key, rank, nxt)
                hits.append((step, harmony.Rel(note, tone, octave, floor), vel, length, 0.0))
            bars.append(hits)
        played = [int(h[1]) for bar in bars for h in bar]
        if not played or statistics.median(played) >= harmony.CHORD_LOW or floor + 12 > patterns.NOTE_MAX - 12:
            return bars, floor
        floor += 12
    return bars, floor


# ---- fallbacks: what a phrase follows with no progression playing ----------------

_FALLBACK = {}


def fallback(progression, key):
    """The progression phrase tracks follow when none is set (tool thread; prepared once and cached).

    progression: the genre record's default progression name (classic house), or None for the key's tonic triad.
    key: the session's harmony.Key. Starts at bar 0 of the pattern's loop, close-voiced.
    """
    cache_key = (progression, tuple(key))
    prog = _FALLBACK.get(cache_key)
    if prog is None:
        if progression is not None:
            entry = progressions.PROGRESSIONS[progression]
            prog_key, _ = progressions.key_for(entry, key)
            chords = harmony.parse_chords(entry.chords, prog_key)
            per = entry.bars_per_chord
        else:
            prog_key = harmony.Key(*key)
            minor = 3 in prog_key.steps and 4 not in prog_key.steps
            chords = [harmony.parse_chord("i" if minor else "I", prog_key)]
            per = 1
        prog = harmony.Progression(tuple(chords), harmony.voice(chords, "close"), per, "close", prog_key, 0,
                                   library=progression)
        _FALLBACK[cache_key] = prog
    return prog


def cached(progression, key):
    """fallback() for the bar line: a dict lookup only; None if the tool thread hasn't prepared it."""
    return _FALLBACK.get((progression, tuple(key))) if key is not None else None


def describe(phrase):
    return {"role": phrase.role, "bars": len(phrase.grid), "grid": list(phrase.grid), "tones": list(phrase.tones),
            "register": phrase.register, "density": phrase.density, "variation": phrase.variation,
            "on_request": phrase.on_request}
