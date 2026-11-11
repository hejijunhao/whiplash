"""Session kit map: what the user says each track and sample slot holds, and patterns routed onto it.

Whiplash can't read the unit (sample names need SysEx, which is blocked), so the map comes from
chat: whiplash_label_tracks(tracks={"7": "tuned cymbal"}, slots={"11": "synth"}). It lives in
memory only: it survives whiplash_stop and pattern switches, and is cleared by reset or a gateway
restart.

route() is pure and cheap (dicts over at most 16 tracks x 4 bars), so the sequencer may call it at
a bar line. Each generated part goes, in order of preference:
  1. to a labelled track with the same role (kick part -> the track labelled kick),
  2. to a labelled track with a close role (rim <-> snare, chord -> pad, stab -> lead),
  3. to its default track, if the user hasn't labelled that track as something else,
and is dropped otherwise. Labelled tracks that get no part stay silent until whiplash_write_part.
A track labelled cymbal or fx is never matched to a chord, bass or other melodic part.
"""
import re
from dataclasses import replace

ROLES = ("kick", "snare", "rim", "clap", "closed hat", "open hat", "cymbal", "perc", "bass", "pad", "stab",
         "chord", "lead", "fx", "other")
MELODIC = frozenset({"bass", "pad", "stab", "chord", "lead"})
LABEL_MAX = 60
SLOT_MAX = 127

# Free text -> role. First match wins, so the specific phrases come before the general ones
# ("bass drum" before "bass", "open hat" before "hat").
_KEYWORDS = (
    ("kick", r"kick|kik|bass ?drum|bd"),
    ("open hat", r"open ?(hi[- ]?)?hats?|oh"),
    ("closed hat", r"(closed ?)?(hi[- ]?)?hats?|hh|ch|hihats?"),
    ("cymbal", r"cymbals?|ride|crash|china|splash"),
    ("snare", r"snares?|sd"),
    ("rim", r"rims?(hot)?|sticks?"),
    ("clap", r"claps?|handclaps?|snaps?"),
    ("perc", r"perc(ussion)?|toms?|congas?|bongos?|shakers?|cowbell|clave|tambourine|blocks?"),
    ("bass", r"bass(line)?|sub|808|reese"),
    ("pad", r"pads?|drones?|atmos(phere)?|strings?"),
    ("stab", r"stabs?"),
    ("chord", r"chords?|harmony|keys|piano|organ|minor chord|major chord"),
    ("lead", r"leads?|synths?|melody|arp|pluck|chop|bells?|vox|vocals?"),
    ("fx", r"fx|sfx|noise|riser|sweep|impact|effects?"),
)
_COMPILED = [(role, re.compile(rf"(?<![a-z0-9])({pattern})(?![a-z0-9])")) for role, pattern in _KEYWORDS]
# second choice for a generated role when no track carries the exact one
CLOSE = {"rim": ("snare",), "snare": ("rim",), "chord": ("pad", "stab"), "pad": ("chord",),
         "stab": ("lead", "chord"), "lead": ("stab",), "open hat": ("cymbal",)}


class KitError(ValueError):
    pass


def classify(text):
    """Free text -> one of ROLES ('other' when nothing matches)."""
    word = " ".join(str(text).strip().lower().replace("_", " ").split())
    if word in ROLES:
        return word
    for role, rx in _COMPILED:
        if rx.search(word):
            return role
    return "other"


def _label(value, what):
    if not isinstance(value, str):
        raise KitError(f"{what} must be text, e.g. 'pad' or 'dirty bass', got {value!r}")
    text = " ".join(value.split())
    if len(text) > LABEL_MAX:
        raise KitError(f"{what} is longer than {LABEL_MAX} characters")
    if any(ord(c) < 32 for c in value.replace("\n", " ").replace("\t", " ")):
        raise KitError(f"{what} has control characters")
    return text


def _key(raw, low, high, what):
    try:
        number = int(str(raw).strip())
    except (TypeError, ValueError):
        number = None
    if isinstance(raw, bool) or number is None or not low <= number <= high:
        raise KitError(f"{what} must be {low}-{high}, got {raw!r}")
    return number


def check_tracks(tracks):
    """{"7": "tuned cymbal", "5": {"role": "pad", "label": "warm pad"}, "3": null} -> {7: (role, label) | None}."""
    if tracks in (None, {}):
        return {}
    if not isinstance(tracks, dict):
        raise KitError('tracks must map track to what it holds, e.g. {"7": "cymbal", "5": "pad"}')
    out = {}
    for raw, value in tracks.items():
        track = _key(raw, 1, 16, "track")
        if value in (None, ""):
            out[track] = None  # remove this track's label
            continue
        if isinstance(value, dict):
            unknown = set(value) - {"role", "label"}
            if unknown:
                raise KitError(f"track {track}: unknown key(s) {sorted(unknown)}; use role and/or label")
            label = _label(value.get("label") or value.get("role") or "", f"label for track {track}")
            role = value.get("role")
            if role not in (None, ""):
                role = " ".join(str(role).strip().lower().split())
                if role not in ROLES:
                    raise KitError(f"track {track}: role must be one of {', '.join(ROLES)}, got {value['role']!r}")
            else:
                role = classify(label)
            if not label:
                raise KitError(f"track {track}: give a role or a label")
        else:
            label = _label(value, f"label for track {track}")
            role = classify(label)
        out[track] = (role, label)
    return out


def check_slots(slots):
    """{"11": "synth Phil likes", "9": null} -> {11: label | None}."""
    if slots in (None, {}):
        return {}
    if not isinstance(slots, dict):
        raise KitError('slots must map slot number to a label, e.g. {"11": "warm synth"}')
    return {_key(raw, 0, SLOT_MAX, "slot"): (None if value in (None, "") else _label(value, f"label for slot {raw}"))
            for raw, value in slots.items()}


def merged(current, changes):
    """Apply {key: value | None} changes to a {key: value} map; None removes."""
    out = dict(current)
    for key, value in changes.items():
        if value is None:
            out.pop(key, None)
        else:
            out[key] = value
    return out


def generated_role(role_text):
    return classify(role_text) if role_text else "other"


def plan(pattern, tracks):
    """Routing for pattern over the labelled tracks {track: (role, label)}.

    Returns {"moves": {source track: target track}, "dropped": {source: generated role}, "silent": [labelled
    tracks that get no part]}. With no labels every part stays on its own track.
    """
    sources = sorted(t for t, bars in pattern.bars.items() if any(bars))
    if not tracks:
        return {"moves": {t: t for t in sources}, "dropped": {}, "silent": []}
    roles = {t: generated_role(pattern.roles.get(t)) for t in sources}
    free = dict(sorted(tracks.items()))  # labelled tracks not yet given a part
    moves, dropped = {}, {}

    def take(source, wanted):
        for target, (role, _) in free.items():
            if role in wanted:
                del free[target]
                moves[source] = target
                return True
        return False

    pending = [s for s in sources if not take(s, {roles[s]})]
    pending = [s for s in pending if not take(s, set(CLOSE.get(roles[s], ())))]
    for source in pending:
        if source not in tracks and source not in moves.values():
            moves[source] = source  # unlabelled default track: assume the pattern's layout there
        else:
            dropped[source] = pattern.roles.get(source) or roles[source]
    return {"moves": moves, "dropped": dropped, "silent": sorted(free)}


def route(pattern, tracks):
    """pattern with its parts moved onto the labelled tracks (same name, bpm, swing)."""
    if not tracks:
        return pattern
    moves = plan(pattern, tracks)["moves"]
    bars = {target: pattern.bars[source] for source, target in moves.items()}
    shifts = {moves[s]: v for s, v in pattern.shifts.items() if s in moves}
    roles = {target: pattern.roles.get(source) for source, target in moves.items()}
    for track, (_, label) in tracks.items():
        roles[track] = label
    return replace(pattern, bars=bars, shifts=shifts, roles=roles)


def describe(pattern, tracks):
    """What the routing does, for tool results: {"6": "bass part (from track 6)", ...}."""
    if pattern is None:
        return None
    info = plan(pattern, tracks)
    out = {"parts": {str(target): f"{pattern.roles.get(source) or 'part'} (pattern track {source})"
                     for source, target in sorted(info["moves"].items(), key=lambda m: m[1])}}
    if info["dropped"]:
        out["dropped"] = {str(s): r for s, r in sorted(info["dropped"].items())}
    if info["silent"]:
        out["silent_until_written"] = info["silent"]
    return out
