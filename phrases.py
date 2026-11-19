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
ARP_TONES = ("R", "3", "5", "7", "oct")  # arp.chord_seeded: each hit picks one (a 7th on a triad plays its nearest)
HOOK_TONES = ("R", "3", "5", "9", "oct")  # lead.pentatonic_hook: the major pentatonic over a major chord
MOTIF_CHORD_STEPS = (2, 4, 7)  # melody.motif's beats: the 3rd, 5th and octave as scale steps above the root
SHIFT_STEPS = (6, 7, 10, 11)  # stab.single's bar 4: where the stab moves
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
    variation: str = "none"  # none | seeded (bar 4 re-picks its passing tones) | shift (bar 4's hit moves) |
    #                          arp (every hit picks a chord tone) | hook (a seeded 2-bar hook) | motif (A A A+1 answer)
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
       tags=("bass", "techno", "minimal", "driving", "hypnotic"), order=(2, 6, 10, 14, 3, 7, 11, 15), density=0.5),
    _p("stab.offbeat", "stab", "..x...x...x...x.", ("chord",), "mid", (1,), (100, 88, 88, 88),
       "§2 MusicRadar, Attack",
       "Off-beat chord stabs, never on the kick's downbeat; each stab track plays its own chord tone",
       tags=("stab", "house", "techhouse", "techno", "piano"), order=(6, 14, 2, 10)),
    # O3 (v0.9.2): progressive house, melodic techno, minimal, tropical house, and the on-request leads.
    _p("bass.root_follow", "bass", "x.......x.......", ("R",), "low", (7,), (100, 90), "§4 BeatKey",
       "Long roots on 1 and 3 that follow each chord change", tags=("bass", "progressivehouse", "patient")),
    _p("bass.rolling_16", "bass", ".xxx.xXx.xxx.xxx", ("R", "R", "R", "R", "5", "R", "R", "R", "R", "R", "R", "R"),
       "low", (1,), (92, 80, 84, 92, 96, 84, 92, 80, 84, 92, 80, 84), "§8 NI",
       "Rolling 16ths off the kick steps on the root, one accented 5th; moves when the chord moves",
       tags=("bass", "melodictechno", "rolling", "driving"),
       order=(2, 6, 10, 14, 3, 7, 11, 15, 1, 5, 9, 13)),
    _p("bass.stab_sparse", "bass", ("...x............", "...x.......x...."), ("R", "R", "oct"), "low", (1,),
       (100, 96, 88), "§6 TPS", "One or two short notes a bar: the root on 3, its octave on 11 every second bar",
       tags=("bass", "minimal", "sparse")),
    _p("bass.round_sub", "bass", "x.......x..x....", ("R",), "low", (3, 3, 1), (104, 96, 84), "§7 Melodigging",
       "A round sub: roots on 1 and 3 with a short decay; density 1 adds the root on 11",
       tags=("bass", "tropicalhouse", "soft"), order=(0, 8, 11), density=0.67),
    _p("bass.descending_walk", "bass", "x...............", ("R", "step-1", "step-2", "step-3"), "low", (16,),
       (100,), "§4 BeatKey (the Prydz-like Am-Am/G-Fmaj7-E7 bass)",
       "Four held bass notes walking down the scale under a held tonic: A G F E in A minor",
       tags=("bass", "progressivehouse", "prydz-like")),
    _p("bass.walking", "bass", "x...x...x...x...", ("R", "step+1", "3", "approach"), "low", (3,),
       (100, 88, 92, 84), "by ear", "Walking quarters: root, a step up, the 3rd, then a step into the next chord",
       tags=("bass", "walking", "jazzy"), variation="seeded"),
    _p("stab.single", "stab", "......x.........", ("chord",), "mid", (1,), (100,), "§6 Brizm (a single stab)",
       "One short chord stab a bar on step 6; bar 4's stab moves to a seeded step",
       tags=("stab", "minimal", "sparse"), variation="shift"),
    _p("pad.hold", "pad", "x...............", ("chord",), "mid", (harmony.PAD_GATE,), (harmony.PAD_VELOCITY,),
       "existing (harmony.pad_line)", "One chord tone held for the whole bar per chord track: the existing pad, named",
       tags=("pad", "deephouse", "melodictechno", "tropicalhouse", "progressivehouse", "warm")),
    _p("arp.chord_up", "lead", "xxxxxxxxxxxxxxxx", ("R", "3", "5", "oct"), "mid", (1,), (96, 72, 80, 72), "by ear",
       "Chord tones rising on 16ths, root to octave", tags=("arp", "lead"), on_request=True),
    _p("arp.chord_updown", "lead", "xxxxxxxxxxxxxxxx", ("R", "3", "5", "oct", "5", "3"), "mid", (1,),
       (96, 72, 80, 88, 80, 72), "by ear", "Chord tones up and down on 16ths", tags=("arp", "lead"), on_request=True),
    _p("arp.chord_seeded", "lead", "x.x.x.x.x.x.x.x.", ("R",), "mid", (1,), (96, 76, 84, 76), "by ear",
       "8ths of chord tones in a seeded order, new each bar", tags=("arp", "lead"), variation="arp",
       on_request=True),
    _p("lead.stutter", "lead", "xx.xxx.xxx.xxx.x", ("5",), "mid", (0.5,), (100, 70, 90), "§8 NI (short stutter notes)",
       "A short repeated chord tone on 16ths (x x . x), following the chords", tags=("lead", "melodictechno"),
       on_request=True),
    _p("lead.pentatonic_hook", "lead", ("x..x..x...x.x...", "x.x...x..x......"), ("R",), "mid",
       (2, 1, 2, 1, 2, 2, 1, 2, 2), (100, 84, 92, 84, 96, 100, 84, 92, 80), "§7 Melodigging, Splice",
       "A seeded 2-bar hook of R, 3, 5, 9 and the octave of each chord (pentatonic over a major chord), repeated",
       tags=("lead", "tropicalhouse", "hook"), variation="hook", on_request=True),
    _p("melody.motif", "lead", "x.x.x.x.x.x.x.x.", ("R",), "mid", (2, 1), (100, 80, 92, 80), "by ear",
       "A seeded one-bar motif, repeated, sequenced up a step, then answered, ending on the root",
       tags=("lead", "melody", "motif"), variation="motif", on_request=True),
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


def _motif_degrees(seed, name):
    """melody.motif's one-bar motif in scale steps from the chord root: chord tones (0, 2, 4, 7 steps) on the beats,
    a passing step between, seeded. -> [8 degrees on steps 0, 2, ..., 14]."""
    rng = mutate.rng(seed, "phrase", name, "motif")
    beats = [0] + [rng.choice(MOTIF_CHORD_STEPS) for _ in range(3)]
    out = []
    for i, d in enumerate(beats):
        nxt = beats[i + 1] if i + 1 < len(beats) else 0
        out += [d, d + (1 if nxt > d else -1 if nxt < d else rng.choice((1, -1)))]
    return out


def _degree_tone(d):
    """A motif degree (scale steps from the chord root) as a tone: 0 R, 7 oct, 1-6 step+n, 8-13 step+n up an octave,
    negative step-n."""
    if d == 0:
        return "R"
    if d == 7:
        return "oct"
    if 0 < d < 7:
        return f"step+{d}"
    if d > 7:
        return f"step+{d - 7}+12"
    return f"step{d}" if d >= -7 else "R-12"


def _motif_bar(degrees, bar):
    """A, A, A up a step, then the answer: the motif's first half, then stepping down to R."""
    if bar < 2:
        return degrees
    if bar == 2:
        return [d + 1 for d in degrees]
    half = degrees[:4]
    tail = sorted({max(0, half[-1] - 2), max(0, half[-1] - 4)}, reverse=True)
    return half + (tail + [0, 0, 0, 0])[:4]


def _tones(phrase, seed, bar, n, steps):
    """The tones for one bar's grid hits on steps (n: the hit index across the loop so far)."""
    v = phrase.variation
    if v == "motif":
        motif = [_degree_tone(d) for d in _motif_bar(_motif_degrees(seed, phrase.name), bar)]
        return [motif[i % len(motif)] for i in range(len(steps))]
    out = []
    for i, step in enumerate(steps):
        tone = phrase.tones[(n + i) % len(phrase.tones)]
        if v == "seeded" and bar == patterns.BARS - 1 and tone not in ("R",):
            tone = mutate.rng(seed, "phrase", phrase.name, bar, step).choice(SEED_TONES)
        elif v == "arp":
            tone = mutate.rng(seed, "phrase", phrase.name, bar, step).choice(ARP_TONES)
        elif v == "hook":
            tone = mutate.rng(seed, "phrase", phrase.name, bar % 2, step).choice(HOOK_TONES)
        out.append(tone)
    return out


def shape(phrase, density=None, seed=0):
    """4 bars of [(step, tone, octave, velocity, length)]: the phrase before any chord, density applied.

    Tones, velocities and lengths cycle across the loop's hits (a 4-bar walk names one tone per bar); every phrase
    whose bar holds a whole number of cycles plays the same tones in every bar.
    """
    density = phrase.density if density is None else density
    out, n = [], 0
    for bar in range(patterns.BARS):
        cells = parts.parse_grid_bar(phrase.grid[bar % len(phrase.grid)])
        if phrase.variation == "shift" and bar == patterns.BARS - 1 and cells:
            step = mutate.rng(seed, "phrase", phrase.name, bar).choice(SHIFT_STEPS)
            cells = [(step, cells[0][1])]
        tones = _tones(phrase, seed, bar, n, [c[0] for c in cells])
        hits = []
        for i, (step, accent) in enumerate(cells):
            tone, octave = harmony.parse_tone(tones[i])
            vel = min(127, phrase.velocity[(n + i) % len(phrase.velocity)] + (15 if accent else 0))
            hits.append((step, tone, octave, vel, phrase.length[(n + i) % len(phrase.length)]))
        n += len(cells)
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
