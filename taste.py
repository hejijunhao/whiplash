"""Taste guardrails (v0.9.0, ontology O1b): what changed lately, and too-repetitive or too-busy hints. Pure; no MIDI.

Feedback only (Q-T1): nothing here changes the beat. The engine keeps two bounded logs (Engine.bar_digest, one
append per bar by the sequencer; Engine.changes, appended by the tool wrapper); everything below runs in the tool
thread on copies of them.

What counts as change (Q-T4, the same for every genre): a scheduled change landing, a user knob move, any bar on
which a ramp runs, and an arrangement section starting. "Repetitive" is genre-relative (Q-T2): the thresholds are
the genre records' `taste` (research §1-8); soul and breaks take the spec's default.
"""
import statistics

from . import genres, grooves, kitmap

DIGEST_BARS = 64
LISTEN_BARS = 32  # v0.9.4 (O5): a review uses the last whiplash_listen only while it is under this many bars old
WINDOW = 8  # bars a metric looks back over by default
REVIEW_MIN, REVIEW_MAX = 4, 32
VEL_BUCKET = 8  # fingerprints compare velocity in buckets of 8
DEFAULT = {"unchanged_bars": 16, "busy_drums": 6}  # soul, breaks (spec §7.2)
NAMES = {"deephouse": "deep house", "house": "classic house", "techhouse": "tech house", "techno": "techno",
         "progressivehouse": "progressive house", "melodictechno": "melodic techno", "minimal.house": "minimal house",
         "minimal.techno": "minimal techno", "tropicalhouse": "tropical house"}
HATS = frozenset({"closed hat", "open hat"})
# Named next steps per genre, each a library entry (a lane, a fill, a phrase): hints name moves, never rewrite.
SUGGEST = {
    "deephouse": {"lane": "perc.conga_offbeats", "fill": "snare.roll", "phrase": "bass.rolling_deep"},
    "house": {"lane": "rim.syncopated", "fill": "snare.roll", "phrase": "stab.offbeat"},
    "techhouse": {"lane": "perc.woodblock", "fill": "kick.sit_out", "phrase": "bass.bouncy"},
    "techno": {"lane": "perc.rolling", "fill": "kick.sit_out", "phrase": "bass.offbeat"},
    "progressivehouse": {"lane": "perc.shaker_16", "fill": "snare.roll", "phrase": "pad.hold"},
    "melodictechno": {"lane": "hat.offbeat_open", "fill": "snare.roll", "phrase": "lead.stutter"},
    "minimal.house": {"lane": "perc.poly3", "fill": "hat.open_choke", "phrase": "stab.single"},
    "minimal.techno": {"lane": "perc.conga_offbeats", "fill": "kick.sit_out", "phrase": "bass.stab_sparse"},
    "tropicalhouse": {"lane": "perc.bongo", "fill": "snare.roll", "phrase": "lead.pentatonic_hook"},
}
FALLBACK_SUGGEST = {"lane": "perc.conga_offbeats", "fill": "snare.roll"}
# v0.9.4 (O5): genres where automation is the change (research §1 deep house "if filter or perc evolve", §4, §5,
# §6, §8), so a slow filter sweep is offered too. Ramps count as change (Q-T4), so the hint and the counter agree.
SWEEP = frozenset({"deephouse", "progressivehouse", "melodictechno", "techno", "minimal.house", "minimal.techno"})
SWEEP_CALL = "a slow filter_freq sweep on a chord or bass track (whiplash_ramp_param, bars: 8)"
MASKING_PHRASE = "bass.offbeat"  # spec §7.2: the off-beat bass leaves the kick's steps alone


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
        if cur[3] != prev[3]:  # an arrangement section started, or the arrangement ended (then: continue)
            bars.add(cur[0])
    bars |= {b for b, _ in mute_changes(digest)}  # audit: an enter/exit, or the arrangement's mutes lifting
    return bars


def mute_changes(digest):
    """[(bar, 'tracks 4 in, 5 out')] where the set of muted tracks changed from one bar to the next (an arrangement
    enter or exit, a section's mutes, the end of an arrangement, or a mute). Pure; reads the digest only."""
    out = []
    for prev, cur in zip(digest, digest[1:]):
        if cur[5] != prev[5]:
            back, gone = sorted(prev[5] - cur[5]), sorted(cur[5] - prev[5])
            words = ([f"track{'s' if len(back) > 1 else ''} {', '.join(map(str, back))} in"] if back else []) + \
                    ([f"track{'s' if len(gone) > 1 else ''} {', '.join(map(str, gone))} out"] if gone else [])
            out.append((cur[0], ", ".join(words)))
    return out


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
    counts = {t: len(h) for t, h in per_track.items()}
    # v0.9.4 (O5): the tracks a hint names. Busiest: most hits in the window, the lower track on a tie.
    others = [t for t in drums if roles.get(t) != "kick"]
    basses = [t for t in per_track if roles.get(t) == "bass"]
    return {
        "bars": n,
        "unchanged_for_bars": unchanged_for(digest, changes, moves),
        "cycles_repeated": cycles_repeated(prints),
        "chord_static_bars": static,
        "distinct_bars": len(set(prints[-window:])),
        "notes_per_bar": round(sum(len(h) for h in bars) / n, 1),
        "notes_per_bar_by_track": {str(t): round(len(h) / n, 1) for t, h in sorted(per_track.items())},
        "drum_elements": len(drums),
        "busiest_drum": min(others, key=lambda t: (-counts[t], t)) if others else None,
        "bass_track": min(basses, key=lambda t: (-counts[t], t)) if basses else None,
        "max_voices_per_step": voices,
        "low_collisions": round(sum(collisions) / n, 1),
        "hat_density": round(sum(hats) / n, 1),
        "register_crowding": crowded,
        "velocity_spread": {str(t): round(statistics.pstdev(x[1] for x in h), 1)
                            for t, h in sorted(per_track.items()) if len(h) > 1},
    }


def heard(listen, digest, run):
    """The review's `listen` block from Engine.last_listen -> (block or None, note or None). Pure.

    It applies only when the listen was taken while playing, in this run (`run`, bumped on every fresh start), and
    is under LISTEN_BARS bars old on Whiplash's clock (spec §7.2: never captured anew). A listen taken while
    stopped or in an earlier run heard something else, so it is ignored, with a note saying why."""
    if not listen:
        return None, None
    if listen.get("_bar") is None or listen.get("_run") != run or not digest:
        return None, "the last listen was of another run or taken while stopped; whiplash_listen again for heard checks"
    ago = max(0, digest[-1][0] - listen["_bar"])
    if ago >= LISTEN_BARS:
        return None, (f"the last listen is {ago} bars old (reviews use one under {LISTEN_BARS}); "
                      "whiplash_listen again for heard checks")
    return {"bars_ago": ago, "clipping": bool(listen.get("clipping")), "masking": listen.get("masking"),
            "kick_over_rest_db": listen.get("kick_over_rest_db"), "low_pct": listen.get("low_pct"),
            "lufs_ish": listen.get("lufs_ish"), "peak_dbfs": listen.get("peak_dbfs")}, None


def _energy_step(genre, energy, levels, direction):
    """A call that moves the energy, or None when the groove has one level (soul, breaks)."""
    if levels is not None and levels <= 1:
        return None
    record = genres.GENRES.get(genre)
    if energy is None:  # no groove known: start the genre's own one a level up (it queues on the next bar)
        if record is None:
            return None
        return f"whiplash_play_pattern(groove: '{record.groove}', energy: {4 if direction == 'up' else 2})"
    if direction == "up" and energy >= 5 or direction == "down" and energy <= 1:
        direction = "down" if direction == "up" else "up"
    return f"whiplash_mutate(action: 'energy', amount: '{direction}')"


def _try(calls):
    calls = [c for c in calls if c]
    return calls[0] if len(calls) == 1 else ", ".join(calls[:-1]) + ", or " + calls[-1]


def hints(m, genre, energy=None, heard=None, levels=None):
    """{hint id: one sentence} for each threshold m crosses; each names next steps from the libraries.

    One shape for every hint (v0.9.4, O5): what fired, against which limit, then "try" and two to four calls in
    tool syntax. energy: the groove's level now (None: no groove); levels: how many levels it has (soul and breaks
    have one, so they never get an energy step); heard: the review's `listen` block (taste.heard) or None."""
    if not m:
        return {}
    limits, name = thresholds(genre), name_of(genre)
    out = {}
    if m["unchanged_for_bars"] >= limits["unchanged_bars"]:
        s = SUGGEST.get(genre, FALLBACK_SUGGEST)
        calls = [_energy_step(genre, energy, levels, "up") or "whiplash_mutate(action: 'density', amount: 'thicken')",
                 f"whiplash_mutate(action: 'fill', fill: '{s['fill']}')",
                 f"whiplash_write_part(groove: '{s['lane']}') on a free track"]
        if s.get("phrase"):
            calls.append(f"whiplash_write_part(phrase: '{s['phrase']}')")
        if genre in SWEEP:
            calls[-1:] = [SWEEP_CALL]  # keep it to four: the sweep replaces the phrase where automation is the change
        out["repetition"] = (f"{m['unchanged_for_bars']} bars unchanged in {name}, which wants a change every "
                             f"{limits['unchanged_bars']}: try {_try(calls)}.")
    if m["drum_elements"] > limits["busy_drums"]:
        busiest = m.get("busiest_drum")
        calls = [f"whiplash_mute_track(track: {busiest}), the busiest drum after the kick" if busiest else
                 "whiplash_mute_track on one drum track", _energy_step(genre, energy, levels, "down")]
        out["busy"] = (f"Busy for {name}: {m['drum_elements']} drum elements, and {name} holds "
                       f"{limits['busy_drums']}: try {_try(calls)}.")
    if heard and heard.get("masking"):
        bass = m.get("bass_track")
        where = f"track: {bass}, " if bass else ""
        mix = "lower the bass with whiplash_mix(levels: {'bass': 95})"
        if m["low_collisions"] > 0:
            out["masking"] = (f"Bass hits {m['low_collisions']:g} kick steps per bar and the last listen heard the "
                              f"kick masked: try whiplash_write_part({where}phrase: '{MASKING_PHRASE}'), or {mix}.")
        else:
            out["masking"] = ("The last listen heard the kick masked in the low end, though the bass avoids the kick "
                              f"steps: try {mix}, or a shorter bass sample on the unit.")
    if heard and heard.get("clipping"):
        out["clipping"] = ("The last listen heard clipping: try lowering the loudest track with whiplash_mix, then "
                           "whiplash_listen again (level raises are refused until a listen shows none).")
    return out
