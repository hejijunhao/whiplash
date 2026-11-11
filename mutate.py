"""Pure pattern transforms behind whiplash_mutate.

Patterns stay immutable: the engine derives a working copy with working(), and these
functions return new lists. A working hit is (step, note, velocity, gate_steps, offset_ticks).
Every random choice comes from random.Random seeded with a string, so results are
deterministic for a given seed (and across Python runs).
"""
import random
import statistics

from . import patterns

DRUM_TRACKS = (1, 2, 3, 4, 5)
DENSITY_WORDS = {"thin": -0.5, "thicken": 0.5, "normal": 0.0}
HUMANIZE_VEL = 16  # max velocity change at amount 1
HUMANIZE_TICKS = 0.25  # max timing offset at amount 1, in MIDI clock ticks (~5 ms at 120 BPM)


def rng(seed, *parts):
    return random.Random(":".join(str(p) for p in (seed, *parts)))


def working(pattern):
    """Working copy of a Pattern: track -> [bar0 hits, bar1, ...] with offset 0."""
    return {track: [[(s, n, v, g, 0.0) for s, n, v, g in bar] for bar in bars]
            for track, bars in pattern.bars.items()}


def _score(hit):
    step, _, vel, _, _ = hit
    return vel + (40 if step % 4 == 0 else 20 if step % 2 == 0 else 0)


def thin(hits, amount, r):
    """Drop the weakest hits (low velocity, off the beat). Keeps at least one hit.

    The ranking is fixed per (seed, track, bar), so a stronger thin drops a superset.
    """
    if len(hits) <= 1 or amount <= 0:
        return list(hits)
    ranked = sorted(hits, key=lambda h: (_score(h), r.random()))
    drop = min(len(hits) - 1, round(amount * len(hits)))
    dropped = set(ranked[:drop])
    return [h for h in hits if h not in dropped]


def thicken(hits, amount, r):
    """Add ghost notes on empty 16ths, offbeats first, at low velocity, in the bar's own notes."""
    if not hits or amount <= 0:
        return list(hits)
    used = {h[0] for h in hits}
    groups = ([s for s in range(1, patterns.STEPS, 2)], [s for s in range(2, patterns.STEPS, 4)],
              [s for s in range(0, patterns.STEPS, 4)])
    order = []
    for group in groups:
        free = [s for s in group if s not in used]
        r.shuffle(free)
        order += free
    add = round(amount * len(order))
    ghost = max(12, int(statistics.median(h[2] for h in hits) * 0.4))
    out = list(hits)
    for step in order[:add]:
        before = [h for h in hits if h[0] < step] or hits
        out.append((step, before[-1][1], ghost, 1, 0.0))
    return sorted(out)


def density(bars, amount, seed, track):
    """Apply a density amount (-1 thinnest .. 0 original .. +1 busiest) to one track's bars."""
    fn = thin if amount < 0 else thicken
    return [fn(bar, abs(amount), rng(seed, "density", track, i)) for i, bar in enumerate(bars)]


def fill(track, hits):
    """A one-bar fill for a drum track (1 kick, 2 snare/rim, 3 clap, 4 closed hat, 5 open hat)."""
    note = hits[0][1] if hits else patterns.DRUM
    early = [h for h in hits if h[0] < 12]
    if track == 1:  # kick sits out the last beat: tension before the one
        return early
    if track == 2:  # snare roll through the second half, crescendo
        roll = [(s, note, 40 + (s - 8) * 11, 1, 0.0) for s in range(8, 16)]
        return [h for h in hits if h[0] < 8] + roll
    if track == 3:
        return early + [(12, note, 90, 1, 0.0), (14, note, 102, 1, 0.0), (15, note, 115, 1, 0.0)]
    if track == 4:  # 32nd-note ratchets on the last beat
        rat = [(s, note, 50 + (s - 12) * 16 + half * 8, 0.5, half * 3.0) for s in range(12, 16) for half in (0, 1)]
        return early + rat
    if track == 5:  # open hat out of the way of the roll
        return early
    return list(hits)


def humanize(vel, offset, amount, r):
    """Jitter one hit. Offsets are per hit against the grid, so timing never drifts."""
    vel = max(1, min(127, round(vel + r.uniform(-1, 1) * amount * HUMANIZE_VEL)))
    return vel, offset + r.uniform(-1, 1) * amount * HUMANIZE_TICKS
