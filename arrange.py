"""Song arrangement (v0.6.1): sections on bar lines, built from Whiplash's existing primitives.

v0.6.2: a section can end on a transition into the next (transition.py) and recall a mix on its first bar.

Pure: parsing, validation and presets only, no MIDI and no engine state. The engine schedules each section
at its first bar line with the primitives it already has (mutes, drops, fills, ramps, a progression swap), so
there is no new clock path: the sequencer only looks up "does a section start at this bar?" in a dict.

A section names the tracks that play (others are muted by Whiplash, never with the unit's CC 94 mute), and
optionally ramps started on its first bar, a fill on its last bar, tracks that sit out its last bar (drop), and
a chord progression. Tracks are numbers 1-16 or group words resolved at the section's first bar from the roles
playing then (the kit map label, else the pattern's role), so an arrangement survives a pattern switch.
"""
from dataclasses import dataclass

from . import kitmap, transition

SECTIONS_MAX = 16
SECTION_BARS_MAX = 64
TOTAL_BARS_MAX = 512
NAME_MAX = 24
RAMPS_MAX = 8
SECONDS_MIN, SECONDS_MAX, SECONDS_DEFAULT = 30, 600, 75
PRESETS = ("club", "short_demo")
DRUM_ROLES = frozenset({"kick", "snare", "rim", "clap", "closed hat", "open hat", "cymbal", "perc"})
GROUPS = {
    "all": None,  # every track playing
    "drums": DRUM_ROLES,
    "hats": frozenset({"closed hat", "open hat", "cymbal"}),
    "perc": frozenset({"snare", "rim", "clap", "perc"}),
    "music": frozenset({"pad", "stab", "chord", "lead", "fx", "other"}),
    **{role: frozenset({role}) for role in kitmap.ROLES if role not in ("perc",)},
}
SECTION_KEYS = ("name", "bars", "tracks", "mute", "drop", "fill", "chords", "bars_per_chord", "ramps", "transition",
                "transition_bars", "filter_from", "mix")
RAMP_KEYS = ("track", "param", "to", "from", "bars", "curve")
CLEAR_CHORDS = {"none", "off", "clear", "stop"}
# The build's rising filter: low-pass cutoff from nearly closed to fully open. It leaves filter_freq at 127.
BUILD_FROM, BUILD_TO = 20, 127


class ArrangeError(ValueError):
    pass


@dataclass(frozen=True)
class RampSpec:
    track: object  # int 1-16 or a group word
    param: str
    to: object
    start: object  # None: the last value Whiplash sent, looked up at the section's first bar
    bars: object  # None: the section's length
    curve: str


@dataclass(frozen=True)
class Section:
    name: str
    bars: int
    tracks: object  # tuple of track specs, or None = every track playing
    mute: tuple
    drop: tuple  # tracks that sit out the section's last bar
    fill: object  # None, "default" (the drum tracks playing) or a tuple of track specs
    chords: object  # None (keep), "clear", or a tuple of chord symbols
    bars_per_chord: object
    ramps: tuple
    transition: object = None  # v0.6.2: None or a transition.KINDS name, run over the section's last bars
    transition_bars: int = 0
    filter_from: object = None
    mix: object = None  # v0.6.2: a mix snapshot or preset name recalled on the section's first bar


def _whole(value, low, high, what):
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float("nan")
    if isinstance(value, bool) or not (low <= number <= high and number == int(number)):
        raise ArrangeError(f"{what} must be a whole number {low}-{high}, got {value!r}")
    return int(number)


def spec(value, what):
    """One track spec: a track number 1-16 or a group word."""
    if isinstance(value, str) and not value.strip().isdigit():
        word = " ".join(value.strip().lower().replace("_", " ").split())
        word = {"hat": "hats", "hihats": "hats", "kicks": "kick", "synths": "music", "melodic": "music",
                "everything": "all", "bassline": "bass"}.get(word, word)
        if word not in GROUPS:
            raise ArrangeError(f"{what}: {value!r} is not a track or group; use 1-16 or one of "
                               f"{', '.join(sorted(GROUPS))}")
        return word
    return _whole(value, 1, 16, what)


def specs(value, what):
    if value in (None, [], ""):
        return ()
    items = value if isinstance(value, (list, tuple)) else [value]
    out = []
    for item in items:
        s = spec(item, what)
        if s not in out:
            out.append(s)
    return tuple(out)


def _ramp(raw, where):
    if not isinstance(raw, dict):
        raise ArrangeError(f"{where}: each ramp is an object like {{track: 'music', param: 'filter_freq', to: 127}}")
    unknown = sorted(set(raw) - set(RAMP_KEYS))
    if unknown:
        raise ArrangeError(f"{where}: unknown ramp key(s) {unknown}; use {', '.join(RAMP_KEYS)}")
    for key in ("track", "param", "to"):
        if raw.get(key) in (None, ""):
            raise ArrangeError(f"{where}: a ramp needs {key}")
    bars = raw.get("bars")
    if bars is not None:
        bars = _whole(bars, 1, SECTION_BARS_MAX, f"{where} ramp bars")
    curve = str(raw.get("curve") or "linear").strip().lower()
    return RampSpec(spec(raw["track"], f"{where} ramp track"), str(raw["param"]), raw["to"], raw.get("from"),
                    bars, curve)


def section(raw, i):
    """Validate one section dict -> Section. Param values and chords are checked by the engine."""
    where = f"section {i + 1}"
    if not isinstance(raw, dict):
        raise ArrangeError(f"{where}: give an object like {{name: 'intro', bars: 8, tracks: ['kick', 'hats']}}")
    unknown = sorted(set(raw) - set(SECTION_KEYS))
    if unknown:
        raise ArrangeError(f"{where}: unknown key(s) {unknown}; use {', '.join(SECTION_KEYS)}")
    name = raw.get("name") or f"section {i + 1}"
    if not isinstance(name, str) or len(name.strip()) > NAME_MAX or any(ord(c) < 32 for c in name):
        raise ArrangeError(f"{where}: name must be text up to {NAME_MAX} characters")
    name = " ".join(name.split())
    where = f"section {i + 1} ({name})"
    if raw.get("bars") is None:
        raise ArrangeError(f"{where}: give bars, e.g. 8")
    bars = _whole(raw["bars"], 1, SECTION_BARS_MAX, f"{where} bars")
    tracks = None if raw.get("tracks") in (None, "", "all", ["all"]) else specs(raw["tracks"], f"{where} tracks")
    mute = specs(raw.get("mute"), f"{where} mute")
    if tracks is not None and mute:
        raise ArrangeError(f"{where}: give tracks (what plays) or mute (what doesn't), not both")
    drop = specs(raw.get("drop"), f"{where} drop")
    fill = raw.get("fill")
    if fill in (None, False, "", [], "false", "no"):
        fill = None
    elif fill is True or (isinstance(fill, str) and fill.strip().lower() in ("true", "yes", "default", "drums")):
        fill = "default"
    else:
        fill = specs(fill, f"{where} fill")
    chords = raw.get("chords")
    if chords in (None, "", []):
        chords = None
    elif isinstance(chords, str) and chords.strip().lower() in CLEAR_CHORDS:
        chords = "clear"
    elif isinstance(chords, (str, list, tuple)):
        chords = tuple(chords) if isinstance(chords, (list, tuple)) else chords
    else:
        raise ArrangeError(f"{where}: chords must be text like 'i VI III VII', a list, or 'none'")
    per_chord = raw.get("bars_per_chord")
    if per_chord is not None and chords in (None, "clear"):
        raise ArrangeError(f"{where}: bars_per_chord needs chords")
    ramps = raw.get("ramps") or []
    if not isinstance(ramps, list) or len(ramps) > RAMPS_MAX:
        raise ArrangeError(f"{where}: ramps must be a list of up to {RAMPS_MAX}")
    try:
        kind = transition.kind(raw.get("transition"))
        tx_bars = transition.bars(kind, raw.get("transition_bars"))
        tx_from = transition.filter_from(kind, raw.get("filter_from"))
    except transition.TransitionError as exc:
        raise ArrangeError(f"{where}: {exc}") from None
    if tx_bars > bars:
        raise ArrangeError(f"{where}: transition_bars ({tx_bars}) can't be longer than the section ({bars} bars)")
    mix = raw.get("mix")
    if mix in (None, ""):
        mix = None
    elif not isinstance(mix, str) or len(mix.strip()) > NAME_MAX:
        raise ArrangeError(f"{where}: mix must be a saved mix name or a mix preset")
    else:
        mix = " ".join(mix.strip().lower().split())
    return Section(name, bars, tracks, mute, drop, fill, chords, per_chord,
                   tuple(_ramp(r, where) for r in ramps), None if kind == "cut" else kind, tx_bars, tx_from, mix)


def sections(raw):
    """Validate the sections list -> tuple of Section."""
    if not isinstance(raw, list) or not raw:
        raise ArrangeError("give sections, e.g. [{name: 'intro', bars: 8, tracks: ['kick', 'hats']}, ...], "
                           f"or a preset ({', '.join(PRESETS)})")
    if len(raw) > SECTIONS_MAX:
        raise ArrangeError(f"at most {SECTIONS_MAX} sections, got {len(raw)}")
    out = tuple(section(s, i) for i, s in enumerate(raw))
    total = sum(s.bars for s in out)
    if total > TOTAL_BARS_MAX:
        raise ArrangeError(f"the sections add up to {total} bars; at most {TOTAL_BARS_MAX}")
    return out


def _build_ramp(bars):
    return [{"track": "music", "param": "filter_freq", "from": BUILD_FROM, "to": BUILD_TO, "bars": bars,
             "curve": "exp"}]


def club():
    """intro 16 / build 8 / drop 16 / break 8 / drop 16 / outro 16 (80 bars)."""
    return [
        {"name": "intro", "bars": 16, "tracks": ["kick", "hats"], "fill": True},
        {"name": "build", "bars": 8, "tracks": ["kick", "hats", "perc", "music"], "ramps": _build_ramp(8),
         "drop": ["kick"], "fill": True},
        {"name": "drop", "bars": 16, "tracks": "all", "fill": True},
        {"name": "break", "bars": 8, "tracks": ["hats", "perc", "music"], "fill": True},
        {"name": "drop 2", "bars": 16, "tracks": "all", "fill": True},
        {"name": "outro", "bars": 16, "tracks": ["kick", "hats", "perc"]},
    ]


def demo_bars(bpm, seconds=SECONDS_DEFAULT):
    """Total bars for a short_demo of about `seconds` at bpm: whole 4-bar phrases, at least 16 bars."""
    return max(16, round(seconds * bpm / 240 / 4) * 4)


def short_demo(bpm, seconds=SECONDS_DEFAULT):
    """intro 4 / build 4 / drop / (break 4 / drop) / outro 4, about `seconds` long at bpm (default 75 s)."""
    total = demo_bars(bpm, seconds)
    middle = total - 12
    head = [{"name": "intro", "bars": 4, "tracks": ["kick", "hats"], "fill": True},
            {"name": "build", "bars": 4, "tracks": ["kick", "hats", "perc", "music"], "ramps": _build_ramp(4),
             "drop": ["kick"], "fill": True}]
    tail = [{"name": "outro", "bars": 4, "tracks": ["kick", "hats", "perc"]}]
    if middle >= 24:  # room for a break: drop, break 4, drop
        first = (middle - 4) // 8 * 4
        body = [{"name": "drop", "bars": first, "tracks": "all", "fill": True},
                {"name": "break", "bars": 4, "tracks": ["hats", "perc", "music"], "fill": True},
                {"name": "drop 2", "bars": middle - 4 - first, "tracks": "all", "fill": True}]
    else:
        body = [{"name": "drop", "bars": middle, "tracks": "all", "fill": True}]
    return head + body + tail


def preset(name, bpm, seconds=None):
    word = str(name).strip().lower().replace("-", "_").replace(" ", "_")
    if word not in PRESETS:
        raise ArrangeError(f"preset must be one of {', '.join(PRESETS)}, got {name!r}")
    if seconds is not None and word != "short_demo":
        raise ArrangeError("seconds only applies to the short_demo preset")
    if word == "club":
        return word, club()
    seconds = SECONDS_DEFAULT if seconds is None else _whole(seconds, SECONDS_MIN, SECONDS_MAX, "seconds")
    return word, short_demo(bpm, seconds)


def resolve(specs_, roles):
    """Track specs -> set of tracks, given {track: role} for the tracks playing now. None means all of them."""
    if specs_ is None:
        return set(roles)
    out = set()
    for s in specs_:
        if isinstance(s, int):
            out.add(s)
        elif GROUPS[s] is None:
            out |= set(roles)
        else:
            out |= {t for t, r in roles.items() if r in GROUPS[s]}
    return out
