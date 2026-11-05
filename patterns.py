"""Genre patterns for Digitakt II tracks 1-8 (MIDI channels 1-8).

Each pattern is 4 bars of 16 steps. A hit is (step, note, velocity, gate_steps).
Deep house and soul are ported from Phil's ~/digitakt-deephouse and
~/digitakt-soul-beat scripts; techno and breaks are new.
"""
from dataclasses import dataclass, field

DRUM = 60  # note 60 plays a sample at its original pitch
STEPS = 16
BARS = 4


@dataclass(frozen=True)
class Pattern:
    name: str
    bpm: float
    swing: float  # 0.50 straight, like the unit's SWING 50-80%
    roles: dict
    bars: dict = field(default_factory=dict)  # track -> [bar0 hits, bar1, bar2, bar3]


def _grid(pattern, velocity, note=DRUM, gate=1):
    vel = velocity if callable(velocity) else (lambda step: velocity)
    return [(s, note, vel(s), gate) for s, c in enumerate(pattern) if c == "x"]


def _same(hits):
    return [list(hits) for _ in range(BARS)]


def _lines(lines, velocity, gate):
    return [[(s, n, velocity, gate) for s, n in sorted(bar.items())] for bar in lines]


def _deep_house():
    chord_steps = [(0, 3, 6, 10)] * 3 + [(0, 3, 6, 10, 14)]
    low, high = [57, 62, 57, 59], [60, 65, 65, 64]
    rim = ["...x......x.....", "...x......x..x..", "...x......x.....", "...x.....x...x.x"]
    bass = [{3: 57, 6: 57, 10: 57, 14: 60}, {3: 62, 6: 62, 10: 62, 14: 65},
            {3: 53, 6: 53, 10: 53, 14: 57}, {3: 52, 6: 52, 10: 56, 14: 59}]
    hat_vel = lambda s: 58 if s % 4 == 0 else 40 if s % 2 else 48
    return Pattern("deephouse", 122, 0.55, {
        1: "kick", 2: "rim", 3: "clap", 4: "closed hat", 5: "open hat",
        6: "bass", 7: "minor chord", 8: "major chord"}, {
        1: _same(_grid("x...x...x...x...", 118)),
        2: [_grid(r, 58) for r in rim],
        3: _same(_grid("....x.......x...", 92)),
        4: _same(_grid("x.xxx.xxx.xxx.xx", hat_vel)),
        5: _same(_grid("..x...x...x...x.", 78)),
        6: _lines(bass, 104, 2),
        7: [[(s, low[b], 90 if s == 0 else 78, 2) for s in chord_steps[b]] for b in range(BARS)],
        8: [[(s, high[b], 90 if s == 0 else 78, 2) for s in chord_steps[b]] for b in range(BARS)],
    })


def _soul():
    chop = [{0: 72, 3: 72, 6: 69, 10: 67, 12: 69}, {0: 74, 3: 72, 6: 69, 10: 65, 14: 69},
            {0: 72, 3: 69, 6: 65, 10: 67, 12: 69}, {0: 71, 3: 68, 6: 71, 10: 74, 14: 71}]
    harmony = [{0: 64, 6: 64, 10: 60}, {0: 65, 6: 65, 10: 62},
               {0: 65, 6: 60, 10: 64}, {0: 68, 6: 64, 10: 68}]
    bass = [{0: 45, 6: 45, 10: 45}, {0: 50, 6: 50, 11: 48}, {0: 41, 6: 41, 10: 41}, {0: 40, 6: 40, 11: 44}]
    kick = ["x.....x...x.....", "x.....x...x..x..", "x.....x...x.....", "x.....x..x..x..."]
    return Pattern("soul", 86, 0.58, {
        1: "kick", 2: "snare", 3: "clap", 4: "closed hat", 5: "open hat",
        6: "bass", 7: "chop", 8: "harmony"}, {
        1: [_grid(k, 122) for k in kick],
        2: _same(_grid("....x.......x...", 118)),
        3: _same(_grid("............x...", 96)),
        4: _same(_grid("x.x.x.x.x.x.x.xx", lambda s: 92 if s % 4 == 0 else 62)),
        5: [[], [], [], _grid("..............x.", 90)],
        6: _lines(bass, 115, 4),
        7: _lines(chop, 112, 3),
        8: _lines(harmony, 88, 3),
    })


def _techno():
    return Pattern("techno", 130, 0.50, {
        1: "kick", 2: "rim", 3: "clap", 4: "closed hat", 5: "open hat",
        6: "bass", 7: "stab", 8: "perc"}, {
        1: _same(_grid("x...x...x...x...", 124)),
        2: [_grid("......x.......x.", 64), _grid("......x....x..x.", 64)] * 2,
        3: _same(_grid("....x.......x...", 100)),
        4: _same(_grid("xxxxxxxxxxxxxxxx", lambda s: 70 if s % 2 else 44)),
        5: _same(_grid("..x...x...x...x.", 84)),
        6: _same([(s, 41, 100, 1) for s in (2, 3, 6, 7, 10, 11, 14, 15)]),
        7: [[(3, 53, 96, 1), (11, 53, 80, 1)], [(3, 53, 96, 1)], [(3, 56, 96, 1), (11, 56, 80, 1)], [(3, 51, 96, 1), (13, 51, 90, 1)]],
        8: _same(_grid("...x..x....x..x.", 70)),
    })


def _breaks():
    kick = ["x.........x.....", "x.........x..x..", "x.x.......x.....", "x.........x...x."]
    snare = ["....x.......x...", "....x.......x..x", "....x.......x...", "....x..x.x..x.xx"]
    return Pattern("breaks", 132, 0.54, {
        1: "kick", 2: "snare", 3: "clap", 4: "closed hat", 5: "open hat",
        6: "bass", 7: "stab", 8: "pad"}, {
        1: [_grid(k, 120) for k in kick],
        2: [_grid(s, lambda st: 112 if st in (4, 12) else 70) for s in snare],
        3: _same(_grid("............x...", 84)),
        4: _same(_grid("x.x.x.x.x.x.x.x.", lambda s: 80 if s % 4 == 0 else 56)),
        5: _same(_grid("..............x.", 80)),
        6: _lines([{0: 43, 10: 43}, {0: 46, 10: 46, 14: 48}, {0: 41, 10: 41}, {0: 43, 7: 43, 10: 46}], 108, 3),
        7: _same([(6, 67, 90, 1), (14, 67, 74, 1)]),
        8: _lines([{0: 55}, {0: 58}, {0: 53}, {0: 55}], 70, 16),
    })


PATTERNS = {p.name: p for p in (_deep_house(), _soul(), _techno(), _breaks())}

ALIASES = {
    "deep house": "deephouse", "deep-house": "deephouse", "house": "deephouse",
    "soul chop": "soul", "hiphop": "soul", "hip hop": "soul", "boom bap": "soul",
    "breakbeat": "breaks", "dnb": "breaks",
}
MOODS = {
    "groovy": "deephouse", "warm": "deephouse", "late night": "deephouse",
    "chill": "soul", "mellow": "soul", "nostalgic": "soul", "sad": "soul",
    "dark": "techno", "driving": "techno", "hypnotic": "techno", "intense": "techno",
    "energetic": "breaks", "playful": "breaks", "hyped": "breaks", "happy": "breaks",
}


def resolve(genre=None, mood=None):
    """Return a Pattern for a genre name/alias or mood word. Raises ValueError."""
    for word in (genre, mood):
        if not word:
            continue
        key = str(word).strip().lower()
        key = ALIASES.get(key, MOODS.get(key, key))
        if key in PATTERNS:
            return PATTERNS[key]
        raise ValueError(f"unknown genre/mood {word!r}; genres: {sorted(PATTERNS)}, moods: {sorted(MOODS)}")
    return PATTERNS["deephouse"]
