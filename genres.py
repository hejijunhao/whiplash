"""Genre records (v0.9.0, ontology O1a): each genre's defaults for the groove and harmony layers. Pure tables.

- The hand-written genres (deephouse, techhouse, techno) keep their tables in patterns.py exactly as written; their
  records only name defaults and recommendations for the new layers.
- New genres are compiled, not hand-written: compile(record) builds a patterns.Pattern from the record's default
  groove at energy 3 plus its melodic lines, and registers it in patterns.PATTERNS under the record's name. Classic
  house (`house`) is the first. Everything downstream (kitmap.route, harmony.in_key, fills, density, arrangement)
  sees an ordinary Pattern.

A compiled genre's bass and chord tracks are its record's phrases (O1b, phrases.py), built against its default
progression: classic house plays `bass.octave_pump` and `stab.offbeat` over house.piano_stab. Their notes are
harmony.Rel values, so a later set_progression or key change moves them (harmony.apply mode phrase).
"""
from dataclasses import dataclass, field

from . import grooves, harmony, kitmap, patterns, phrases


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
          {"progression": "techhouse.one_note", "bass": "bass.bouncy", "chords": "stab.offbeat",
           "chords_density": 0.25}),
    Genre("techno", "techno", 130, 0.50, (5, "minor"), "techno.classic", None, "hand", None,
          _roles("techno"), "kick_drop", "techno_plateau", {"unchanged_bars": 64, "busy_drums": 6},
          frozenset({"techno", "dark", "driving", "hypnotic", "peak time"}),
          "130 BPM, kick-led, one chord or a dark two-chord vamp, off-beat bass, plateaus", "§5",
          {"progression": "techno.pedal", "bass": "bass.offbeat", "chords": "stab.offbeat",
           "chords_density": 0.25}),
    # O3 (v0.9.2): compiled from their tables, like classic house.
    Genre("progressivehouse", "progressive", 124, 0.50, (9, "minor"), "progressivehouse.functional",
          "progressivehouse.circle", "bass.root_follow", "stab.offbeat",
          {1: "kick", 2: "rim", 3: "clap", 4: "closed hat", 5: "open hat", 6: "bass", 7: "chord stab",
           8: "chord stab"},
          "kick_bass_out", "progressive_journey", {"unchanged_bars": 16, "busy_drums": 5},
          frozenset({"progressivehouse", "journey", "lush", "patient"}),
          "124 BPM, lush 7th/sus chords, long filtered builds, drumless breakdowns", "§4",
          {"breakdown_chords": "pad.hold"}),
    Genre("melodictechno", "melodic", 124, 0.50, (9, "minor"), "melodictechno.stripped", "melodictechno.cinematic",
          "bass.rolling_16", "pad.hold",
          {1: "kick", 2: "rim", 3: "clap", 4: "closed hat", 5: "open hat", 6: "bass", 7: "pad", 8: "perc"},
          "kick_bass_out", "melodic_journey", {"unchanged_bars": 16, "busy_drums": 6},
          frozenset({"melodictechno", "cinematic", "emotional", "dark"}),
          "124 BPM, cinematic minor chords every two bars, rolling 16th bass, stutter leads", "§8",
          {"lead": "lead.stutter"}),
    Genre("minimal.house", "minimal", 126, 0.57, (9, "minor"), "minimal.house_shuffle", None, "bass.stab_sparse",
          "stab.single",
          {1: "kick", 2: "rim", 3: "clap", 4: "closed hat", 5: "open hat", 6: "bass", 7: "stab", 8: "perc"},
          "subtract_one", "minimal_long", {"unchanged_bars": 64, "busy_drums": 4},
          frozenset({"minimal", "sparse", "hypnotic"}),
          "126 BPM, 3-4 drum elements, space, microtiming, one change per phrase, little harmony", "§6",
          {"progression": "minimal.stab_m7"}),
    Genre("minimal.techno", "minimal", 128, 0.53, (9, "minor"), "minimal.techno_kick", None, "bass.offbeat", None,
          {1: "kick", 2: "rim", 3: "clap", 4: "closed hat", 5: "open hat", 6: "bass", 8: "perc"},
          "subtract_one", "minimal_long", {"unchanged_bars": 64, "busy_drums": 4},
          frozenset({"minimal", "sparse", "hypnotic", "techno"}),
          "128 BPM, kick-led, 3-4 drum elements, a polymetric perc, no chords", "§6",
          {"progression": "minimal.fifth"}),
    Genre("tropicalhouse", "tropical", 108, 0.53, (0, "major"), "tropicalhouse.soft", "tropicalhouse.pop",
          "bass.round_sub", "pad.hold",
          {1: "kick", 2: "rim", 3: "clap", 4: "closed hat", 5: "open hat", 6: "bass", 7: "pad", 8: "bongo"},
          "reduce_drums", "tropical_song", {"unchanged_bars": 16, "busy_drums": 5},
          frozenset({"tropicalhouse", "sunny", "summer", "beach", "bright"}),
          "108 BPM, major pop harmony, soft drums, shakers and mallets, hooks instead of big drops", "§7",
          {"lead": "lead.pentatonic_hook"}),
)}

def melodic_lines(record):
    """{track: 4 bars of 4-field hits} for a compiled genre's bass and chord tracks: its phrases, built against its
    default progression (or the home key's tonic), with harmony.Rel notes so they follow later chords."""
    prog = phrases.fallback(record.progression, harmony.Key(*record.key))
    lines = {}
    bass_track = next(t for t, r in sorted(record.roles.items()) if kitmap.generated_role(r) == "bass")
    bars, _ = phrases.build(phrases.PHRASES[record.bass], prog)
    lines[bass_track] = [[h[:4] for h in bar] for bar in bars]
    if record.chords:
        chord_tracks = [t for t, r in sorted(record.roles.items())
                        if kitmap.generated_role(r) in ("stab", "chord", "pad")]
        for rank, track in enumerate(chord_tracks):
            bars, _ = phrases.build(phrases.PHRASES[record.chords], prog, rank=rank)
            lines[track] = [[h[:4] for h in bar] for bar in bars]
    return lines


def compile(record):
    """A compiled genre -> its registered Pattern: the default groove at energy 3 over its phrase lines."""
    melodic = melodic_lines(record)
    # The whole layout goes in (drum roles too), so a perc lane lands on the genre's perc track (track 8).
    base = patterns.Pattern(record.name, record.bpm, record.swing, dict(record.roles), melodic, key=record.key)
    groove = grooves.GROOVES[record.groove]
    pattern, _ = grooves.compile(groove, 3, base, name=record.name)
    return patterns.Pattern(record.name, record.bpm, record.swing, {**record.roles, **pattern.roles},
                            pattern.bars, key=record.key, genre=record.name)


COMPILED = ("house", "progressivehouse", "melodictechno", "minimal.house", "minimal.techno", "tropicalhouse")
for _name in COMPILED:
    _record = GENRES[_name]
    patterns.RAW[_name] = compile(_record)
    patterns.HOME_KEYS[_name] = _record.key
    patterns.PATTERNS[_name] = patterns.register(patterns.RAW[_name])


def of(pattern):
    """The Genre record for a pattern (by its family), or None (soul, breaks)."""
    return GENRES.get(pattern.family) if pattern is not None else None
