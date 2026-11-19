"""Genre records (v0.9.0, ontology O1a): each genre's defaults for the groove and harmony layers. Pure tables.

- The hand-written genres (deephouse, techhouse, techno) keep their tables in patterns.py exactly as written; their
  records only name defaults and recommendations for the new layers.
- New genres are compiled, not hand-written: compile(record) builds a patterns.Pattern from the record's default
  groove at energy 3 plus its melodic lines, and registers it in patterns.PATTERNS under the record's name. Classic
  house (`house`) is the first. Everything downstream (kitmap.route, harmony.in_key, fills, density, arrangement)
  sees an ordinary Pattern.

House's bass and stabs are baked into plain notes against its default progression in O1a: the octave bounce
(the root on each beat, the octave on each off-beat 8th) and one chord tone per stab track on the off-beats. The
O1b phrase generators (`bass.octave_pump`, `stab.offbeat`) replace the baked lines and make them follow a later
progression; until then a later progression moves the house bass through harmony's `root` mode, as for every genre.
"""
from dataclasses import dataclass, field

from . import grooves, harmony, kitmap, patterns, progressions


@dataclass(frozen=True)
class Genre:
    name: str
    family: str
    bpm: float
    swing: float
    key: tuple  # (pitch class, scale): the home key, as patterns.HOME_KEYS
    groove: str  # default groove
    progression: str | None  # default progression (None: hand chords, or none)
    bass: str  # default bass phrase (O1b); "hand" = the hand-written bass plays
    chords: str | None  # default chord-track phrase (O1b)
    roles: dict  # track -> role, the patterns.py layout
    breakdown: str  # breakdown style (O4)
    form: str  # default form (O4)
    taste: dict  # {"unchanged_bars": n, "busy_drums": n} (O1b uses unchanged_bars; busy_drums caps every groove)
    tags: frozenset = frozenset()
    about: str = ""
    source: str = ""
    recommends: dict = field(default_factory=dict)  # what list_library suggests for a hand-written genre


def _roles(name):
    return dict(patterns.RAW[name].roles)


GENRES = {g.name: g for g in (
    Genre("deephouse", "house", 122, 0.55, (9, "minor"), "deephouse.classic", None, "hand", None,
          _roles("deephouse"), "kick_bass_out", "deephouse_dj", {"unchanged_bars": 32, "busy_drums": 5},
          frozenset({"deephouse", "warm", "late night"}),
          "122 BPM, warm m7/m9 vamps, swung 8th hats, late clap, rolling bass, slow entries", "§1",
          {"progression": "deephouse.two_chord", "bass": "bass.rolling_deep", "chords": "pad.hold"}),
    Genre("house", "house", 123, 0.52, (9, "minor"), "house.jack", "house.piano_stab", "bass.octave_pump",
          "stab.offbeat", {1: "kick", 2: "rim", 3: "clap", 4: "closed hat", 5: "open hat", 6: "bass",
                           7: "piano stab", 8: "piano stab"},
          "filter_bass", "house_jack", {"unchanged_bars": 32, "busy_drums": 5},
          frozenset({"house", "chicago", "jacking", "classic"}),
          "Classic/Chicago house: 123 BPM, jacking 4/4, late clap, off-beat piano stabs, octave-bounce bass", "§2"),
    Genre("techhouse", "house", 126, 0.56, (9, "minor"), "techhouse.classic", None, "hand", None,
          _roles("techhouse"), "filter_low_end", "techhouse_dj", {"unchanged_bars": 8, "busy_drums": 7},
          frozenset({"techhouse", "bouncy", "funky", "rolling"}),
          "126 BPM, every-16th hats pushed early, short bouncy bass, change something every 8 bars", "§3",
          {"progression": "techhouse.one_note", "bass": "bass.bouncy", "chords": "stab.offbeat"}),
    Genre("techno", "techno", 130, 0.50, (5, "minor"), "techno.classic", None, "hand", None,
          _roles("techno"), "kick_drop", "techno_plateau", {"unchanged_bars": 64, "busy_drums": 6},
          frozenset({"techno", "dark", "driving", "hypnotic", "peak time"}),
          "130 BPM, kick-led, one chord or a dark two-chord vamp, off-beat bass, plateaus", "§5",
          {"progression": "techno.pedal", "bass": "bass.offbeat", "chords": "stab.offbeat"}),
)}

BASS_ANCHOR = 55  # the baked house bass's roots sit nearest this (low register, at or above the v0.5 floor)
STAB_STEPS = (2, 6, 10, 14)  # off-beat stabs, never on the kick's downbeat (research §2)
PUMP_BEATS, PUMP_OFFBEATS = (0, 4, 8, 12), (2, 6, 10, 14)


def _chords(record):
    prog = progressions.PROGRESSIONS[record.progression]
    session = harmony.Key(*record.key)
    key, _ = progressions.key_for(prog, session)
    chords = harmony.parse_chords(prog.chords, key)
    per_bar = [chords[(b // prog.bars_per_chord) % len(chords)] for b in range(patterns.BARS)]
    voiced = harmony.voice(chords, "close")
    voiced_bar = [voiced[(b // prog.bars_per_chord) % len(chords)] for b in range(patterns.BARS)]
    return per_bar, voiced_bar


def melodic_lines(record):
    """{track: 4 bars of 4-field hits} for a compiled genre's bass and chord tracks (O1a: baked lines)."""
    per_bar, voiced = _chords(record)
    bass = []
    for chord in per_bar:
        root = harmony.nearest(chord.root, BASS_ANCHOR)
        bass.append([(s, root, 108, 1) for s in PUMP_BEATS] + [(s, root + 12, 96, 1) for s in PUMP_OFFBEATS])
    lines = {6: [sorted(bar) for bar in bass]}
    stab_tracks = [t for t, r in sorted(record.roles.items()) if kitmap.generated_role(r) in ("stab", "chord", "pad")]
    for rank, track in enumerate(stab_tracks):
        lines[track] = [[(s, notes[::-1][rank % len(notes)], 100 if s == 2 else 88, 1) for s in STAB_STEPS]
                        for notes in voiced]
    return lines


def compile(record):
    """A compiled genre -> its registered Pattern: the default groove at energy 3 over the baked melodic lines."""
    melodic = melodic_lines(record)
    base = patterns.Pattern(record.name, record.bpm, record.swing,
                            {t: r for t, r in record.roles.items() if t in melodic}, melodic, key=record.key)
    groove = grooves.GROOVES[record.groove]
    pattern, _ = grooves.compile(groove, 3, base, name=record.name)
    return patterns.Pattern(record.name, record.bpm, record.swing, {**record.roles, **pattern.roles},
                            pattern.bars, key=record.key, genre=record.name)


COMPILED = ("house",)
for _name in COMPILED:
    _record = GENRES[_name]
    patterns.RAW[_name] = compile(_record)
    patterns.HOME_KEYS[_name] = _record.key
    patterns.PATTERNS[_name] = patterns.register(patterns.RAW[_name])


def of(pattern):
    """The Genre record for a pattern (by its family), or None (soul, breaks)."""
    return GENRES.get(pattern.family) if pattern is not None else None
