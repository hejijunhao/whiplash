"""Taste guardrails (v0.9.0, ontology O1b): what changed lately, and too-repetitive or too-busy hints. Pure; no MIDI.

Feedback only (Q-T1): nothing here changes the beat. The engine keeps two bounded logs (Engine.bar_digest, one
append per bar by the sequencer; Engine.changes, appended by the tool wrapper); everything below runs in the tool
thread on copies of them.

What counts as change (Q-T4, the same for every genre): a scheduled change landing, a user knob move, any bar on
which a ramp runs, and an arrangement section starting. "Repetitive" is genre-relative (Q-T2): the thresholds are
the genre records' `taste` (research §1, §2, §3, §5); soul and breaks take the spec's default.
"""
import statistics

from . import genres, grooves, kitmap

DIGEST_BARS = 64
WINDOW = 8  # bars a metric looks back over by default
REVIEW_MIN, REVIEW_MAX = 4, 32
VEL_BUCKET = 8  # fingerprints compare velocity in buckets of 8
DEFAULT = {"unchanged_bars": 16, "busy_drums": 6}  # soul, breaks (spec §7.2)
NAMES = {"deephouse": "deep house", "house": "classic house", "techhouse": "tech house", "techno": "techno"}
HATS = frozenset({"closed hat", "open hat"})
# Named next steps per genre, each a library entry (a lane, a fill, a phrase): hints name moves, never rewrite.
SUGGEST = {
    "deephouse": {"lane": "perc.conga_offbeats", "fill": "snare.roll", "phrase": "bass.rolling_deep"},
    "house": {"lane": "rim.syncopated", "fill": "snare.roll", "phrase": "stab.offbeat"},
    "techhouse": {"lane": "perc.woodblock", "fill": "kick.sit_out", "phrase": "bass.bouncy"},
    "techno": {"lane": "perc.rolling", "fill": "kick.sit_out", "phrase": "bass.offbeat"},
}
FALLBACK_SUGGEST = {"lane": "perc.conga_offbeats", "fill": "snare.roll"}


def thresholds(genre):
    record = genres.GENRES.get(genre)
    return dict(record.taste) if record is not None else dict(DEFAULT)


def name_of(genre):
    return NAMES.get(genre, genre or "this beat")


def _hits(events, muted):
    """[(step, track, note, velocity)] that sound in a bar: muted tracks don't."""
    return [(step, t, int(n), v) for step, evs in sorted(events.items()) for t, n, v, *_ in evs if t not in muted]


def fingerprint(events, muted=frozenset()):
    """One bar, comparable across bars: per track, (step, note, velocity // 8) of every hit that sounds."""
    return frozenset((t, s, n, v // VEL_BUCKET) for s, t, n, v in _hits(events, muted))


def change_bars(digest, changes, moves):
    """Bars on which something counted as change (Q-T4)."""
    bars = {c[0] for c in changes} | {m[0] for m in moves}
    bars |= {d[0] for d in digest if d[6]}  # a ramp ran on this bar
    for prev, cur in zip(digest, digest[1:]):
        if cur[3] != prev[3] and cur[3] is not None:  # an arrangement section started
            bars.add(cur[0])
    return bars


def unchanged_for(digest, changes, moves):
    """Bars played after the last change (all of them when nothing counted as change)."""
    if not digest:
        return 0
    last = digest[-1][0]
    past = [b for b in change_bars(digest, changes, moves) if b <= last]
    return last - max(past) if past else last - digest[0][0] + 1


def cycles_repeated(prints):
    """How many times in a row the latest 4-bar block repeats the block before it (0: it doesn't)."""
    blocks = [tuple(prints[i - 4:i]) for i in range(len(prints), 3, -4)]
    count = 0
    for older in blocks[1:]:
        if older != blocks[0]:
            break
        count += 1
    return count


def metrics(digest, changes, moves, roles, window=WINDOW):
    """Compact repetition, busyness and feel numbers over the last `window` bars of the digest.

    digest: Engine.bar_digest entries; changes: (bar, tool, summary); moves: (bar, what) user moves;
    roles: {track: role} (harmony.role_of).
    """
    if not digest:
        return None
    win = list(digest)[-window:]
    prints = [fingerprint(d[2], d[5]) for d in digest]
    chords = [d[4] for d in digest]
    static = 0
    for chord in reversed(chords):
        if chord != chords[-1]:
            break
        static += 1
    bars = [_hits(d[2], d[5]) for d in win]
    per_track = {}
    drums, voices, collisions, hats = set(), 0, [], []
    for hits in bars:
        steps = {}
        kick_steps = {s for s, t, *_ in hits if roles.get(t) == "kick"}
        collisions.append(sum(1 for s, t, *_ in hits if roles.get(t) == "bass" and s in kick_steps))
        hats.append(sum(1 for _, t, *_ in hits if roles.get(t) in HATS))
        for s, t, n, v in hits:
            per_track.setdefault(t, []).append((n, v))
            steps[s] = steps.get(s, 0) + 1
            if roles.get(t) in grooves.DRUM_ROLES:
                drums.add(t)
        voices = max([voices, *steps.values()])
    n = len(win)
    busy = {t: statistics.median(x[0] for x in hits) for t, hits in per_track.items()
            if roles.get(t) in kitmap.MELODIC and len(hits) / n >= 4}
    crowded = [[a, b] for a in sorted(busy) for b in sorted(busy) if a < b and abs(busy[a] - busy[b]) <= 2]
    return {
        "bars": n,
        "unchanged_for_bars": unchanged_for(digest, changes, moves),
        "cycles_repeated": cycles_repeated(prints),
        "chord_static_bars": static,
        "distinct_bars": len(set(prints[-window:])),
        "notes_per_bar": round(sum(len(h) for h in bars) / n, 1),
        "notes_per_bar_by_track": {str(t): round(len(h) / n, 1) for t, h in sorted(per_track.items())},
        "drum_elements": len(drums),
        "max_voices_per_step": voices,
        "low_collisions": round(sum(collisions) / n, 1),
        "hat_density": round(sum(hats) / n, 1),
        "register_crowding": crowded,
        "velocity_spread": {str(t): round(statistics.pstdev(x[1] for x in h), 1)
                            for t, h in sorted(per_track.items()) if len(h) > 1},
    }


def hints(m, genre, energy=None):
    """{hint id: one sentence} for each threshold m crosses; each names next steps from the libraries."""
    if not m:
        return {}
    limits, name = thresholds(genre), name_of(genre)
    out = {}
    if m["unchanged_for_bars"] >= limits["unchanged_bars"]:
        s = SUGGEST.get(genre, FALLBACK_SUGGEST)
        energy_move = ("whiplash_mutate(action: 'energy', amount: 'up')" if energy is not None and energy < 5 else
                       "whiplash_mutate(action: 'energy', amount: 'down')" if energy is not None else
                       "whiplash_mutate(action: 'energy', amount: 'up') with a groove playing")
        extra = f", or write_part with phrase {s['phrase']}" if s.get("phrase") else ""
        out["repetition"] = (f"{m['unchanged_for_bars']} bars unchanged in {name} (it wants a change every "
                             f"{limits['unchanged_bars']}): try {energy_move}, fill '{s['fill']}', or write_part with "
                             f"groove {s['lane']}{extra}.")
    if m["drum_elements"] > limits["busy_drums"]:
        out["busy"] = (f"Busy for {name}: {m['drum_elements']} drum elements ({name} holds {limits['busy_drums']}): "
                       "mute one, or whiplash_mutate(action: 'energy', amount: 'down').")
    return out
