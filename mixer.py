"""Mix levels (v0.6.2): track LEVEL and PAN per track, genre presets, named snapshots.

Pure: validation, presets and snapshot names only, no MIDI and no engine state. The engine sends TRACK LEVEL
(CC 95, `track_level`) and PAN (CC 90, `pan`) on each track's own channel, from the next bar line, instantly or
ramped over `bars` bars on its clock ([M] Appendix B, B.1 and B.5, p. 109-110; docs/digitakt-ii/reference.md).
Both CCs are in ccmap and neither is blocked. Track LEVEL is the post-FX fader, so a mix never touches the
sound itself.

Keys are track numbers 1-16 or the group words whiplash_arrange uses (kick, hats, bass, music, ...), resolved
from the roles playing when the call is made. Presets give each role a level; tracks whose role a preset
doesn't name keep theirs.
"""
from . import arrange

SNAPSHOTS_MAX = 16
NAME_MAX = 24
MIX_BARS_MAX = 32
PAN_WORDS = {"hard left": 0, "left": 32, "slightly left": 48, "center": 64, "centre": 64, "middle": 64,
             "slightly right": 80, "right": 96, "hard right": 127}
_BASE = {"kick": 115, "bass": 105, "snare": 100, "rim": 92, "clap": 100, "closed hat": 90, "open hat": 88,
         "cymbal": 86, "perc": 92, "pad": 95, "chord": 95, "stab": 98, "lead": 98, "fx": 85, "other": 95}
PRESETS = {
    "flat": {role: 100 for role in _BASE},
    "techno": {**_BASE, "kick": 120, "bass": 108, "closed hat": 92, "pad": 90, "chord": 90},
    "techhouse": {**_BASE, "kick": 118, "bass": 112, "clap": 102, "perc": 96},
    "deephouse": {**_BASE, "kick": 112, "bass": 108, "rim": 88, "chord": 100, "pad": 100},
    "breaks": {**_BASE, "kick": 110, "snare": 112, "closed hat": 94, "bass": 106},
    "soul": {**_BASE, "kick": 106, "snare": 108, "closed hat": 86, "bass": 104, "chord": 102, "pad": 102},
}
PRESET_WORDS = {"auto": None, "genre": None, "current": None, "default": None, "reset": "flat", "unity": "flat"}


class MixError(ValueError):
    pass


def _whole(value, low, high, what):
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float("nan")
    if isinstance(value, bool) or not (low <= number <= high and number == int(number)):
        raise MixError(f"{what} must be a whole number {low}-{high}, got {value!r}")
    return int(number)


def level(value, what):
    return _whole(value, 0, 127, what)


def pan(value, what):
    if isinstance(value, str) and not value.strip().lstrip("-").isdigit():
        word = " ".join(value.strip().lower().replace("_", " ").replace("-", " ").split())
        if word not in PAN_WORDS:
            raise MixError(f"{what}: {value!r} is not a pan; give 0-127 (64 = centre) or one of "
                           f"{', '.join(PAN_WORDS)}")
        return PAN_WORDS[word]
    return _whole(value, 0, 127, what + " (0 = hard left, 64 = centre, 127 = hard right)")


def values(raw, what, check):
    """{"1": 110, "bass": 95} -> [(track spec, value)] in the given order. None or {} -> []."""
    if raw in (None, {}):
        return []
    if not isinstance(raw, dict):
        raise MixError(f'{what} must map a track or group to a value, e.g. {{"1": 110, "bass": 95}}')
    out = []
    for key, value in raw.items():
        spec = arrange.spec(key, f"{what} track")
        out.append((spec, check(value, f"{what} for {key}")))
    return out


def bars(value):
    if value in (None, "", 0):
        return 0
    return _whole(value, 0, MIX_BARS_MAX, "mix bars")


def name(value, what="save_as"):
    if not isinstance(value, str) or not value.strip():
        raise MixError(f"{what} must be a name, e.g. 'drop mix'")
    word = " ".join(value.strip().lower().split())
    if len(word) > NAME_MAX or any(ord(c) < 32 for c in word):
        raise MixError(f"{what} must be text up to {NAME_MAX} characters")
    return word


def preset(value, genre):
    """A preset word -> (name, {role: level}). 'auto' (and friends) picks the genre playing, else flat."""
    word = str(value).strip().lower().replace("-", "").replace("_", "").replace(" ", "")
    word = {"techhouse": "techhouse", "deephouse": "deephouse", "house": "deephouse", "hiphop": "soul",
            "breakbeat": "breaks", "dnb": "breaks"}.get(word, word)
    if word in PRESET_WORDS:
        word = PRESET_WORDS[word] or (genre if genre in PRESETS else "flat")
    if word not in PRESETS:
        raise MixError(f"preset must be one of {', '.join(PRESETS)} or auto (the genre playing), got {value!r}")
    return word, PRESETS[word]
