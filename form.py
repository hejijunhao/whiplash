"""The arrangement grammar (v0.9.3, ontology O4): section types, energy, breakdown styles, forms and moves.

Pure: tables and compile only, no MIDI and no engine state. Everything here compiles, in the tool thread, into the
ordinary section dicts that arrange.sections() validates and the engine already runs (_arrange_step,
_enter_section), so there is no new clock path.

- A section type (intro, groove, build, breakdown, drop, outro) is a template of section keys plus an energy level.
  A section's own keys win over its type's.
- Energy 1-5 sets the groove level when a groove with levels plays, the groups that play when a section names no
  tracks, and (only when opted in: energy_filter) a music-filter target.
- A breakdown plays in its genre's style (BREAKDOWNS): which elements go, or a filter on the low end.
- A form is a list of `type bars` items ("intro 16, groove 16, build 8, drop 16") or a library name (FORMS).
- A move (build, drop, breakdown, slam) is a short arrangement that ends with then: "continue".

Sources are sections of docs/research/genre-conventions.md, or "by ear".
"""
import re
from dataclasses import dataclass, field

from . import arrange

ENERGY_MIN, ENERGY_MAX = 1, 5
RISING = "rising"
# Groups that play at each energy when a section names neither tracks nor mute (3-5: everything).
ENERGY_GROUPS = {1: ["kick", "hats"], 2: ["kick", "hats", "perc", "bass"], 3: None, 4: None, 5: None}
# The opt-in music filter (Q-A1): filter_freq on the music group per level (by ear). The unit's default cutoff is 127.
ENERGY_FILTER = {1: 48, 2: 72, 3: 100, 4: 116, 5: 127}
FILTER_DEFAULT = 127
FILTER_BARS = 4  # a non-build section reaches its level's cutoff over its first bars
RISING_LEVELS = (2, 3, 4)  # a rising section steps 2 -> 3 -> 4 over its thirds
THIN_AMOUNT, THIN_BARS = 0.3, 8  # the outro: hats' density -0.3 over its last 8 bars
LOW_END_TO, LOW_END_BARS = 40, 2  # filter_low_end / filter_bass: the bass cutoff closes to 40 over 2 bars
BARS_UNIT = 8  # DJs count in 8, 16 and 32: a section of another length warns (never refused)
THEN = ("stop", "loop", "continue")
CRASH = "cymbal.crash"
DROP_MIX = "drop mix"

SECTION_TYPES = {
    "intro": {"energy": 1, "bars": 16, "tracks": ["kick", "hats"], "fill_every": 8},
    "groove": {"energy": 3, "bars": 16, "fill_every": 8},
    "build": {"energy": RISING, "bars": 8, "tracks": ["kick", "hats", "perc", "music"], "drop": ["kick"],
              "fill": "snare.roll", "enter": {"hats": -4}},
    "breakdown": {"energy": 2, "bars": 16},  # plus the genre's breakdown style
    "drop": {"energy": 5, "bars": 16, "fill_every": 8},
    "outro": {"energy": 1, "bars": 16, "tracks": ["kick", "hats", "perc"], "_thin": True},
}
TYPE_ALIASES = {"break": "breakdown", "buildup": "build", "build up": "build", "main": "groove", "body": "groove",
                "chorus": "drop", "verse": "groove", "intro": "intro", "outro": "outro", "ending": "outro"}

# Breakdown styles (Q-A3): what the breakdown section does, by genre.
BREAKDOWNS = {
    "kick_bass_out": {"mute": ["kick", "bass"]},
    "kick_drop": {"mute": ["kick"]},
    "filter_low_end": {"tracks": "all", "_style": "filter_low_end"},
    "filter_bass": {"tracks": "all", "_style": "filter_low_end"},
    "reduce_drums": {"tracks": "all", "energy": 1, "_style": "reduce_drums"},
    "subtract_one": {"tracks": "all", "_style": "subtract_one"},
}
BREAKDOWN_ABOUT = {
    "kick_bass_out": "kick and bass out; chords and hats stay",
    "kick_drop": "kick out; the bass stays",
    "filter_low_end": f"the bass filter closes to {LOW_END_TO} over {LOW_END_BARS} bars, reopening on the next section",
    "filter_bass": f"the bass filter closes to {LOW_END_TO} over {LOW_END_BARS} bars, reopening on the next section",
    "reduce_drums": "the groove drops to energy 1; hook and chords stay",
    "subtract_one": "the busiest non-kick element sits out the section",
}
DEFAULT_BREAKDOWN = "filter_bass"  # soul, breaks and any genre without a record


class FormError(ValueError):
    pass


@dataclass(frozen=True)
class Form:
    name: str
    genre: str | None  # a genres record name, the shared "minimal", or None (any genre)
    sections: tuple  # of dicts: {"type", "bars", ...keys that override the type}
    energy_filter: bool = False
    fill_every: object = "type"  # "type" keeps each type's; an int replaces it; None removes it
    fill: object = None  # a fill name for the sections that fill every N bars
    preset: str | None = None  # club, short_demo: plays exactly that arrange preset
    tags: frozenset = frozenset()
    source: str = ""
    about: str = ""


@dataclass(frozen=True)
class Move:
    name: str
    bars: int | None  # the default length; None: bars doesn't apply
    tags: frozenset = frozenset()
    source: str = ""
    about: str = ""
    aliases: tuple = field(default_factory=tuple)


def _s(kind, bars, **over):
    return {"type": kind, "bars": bars, **over}


FORMS = {f.name: f for f in (
    Form("deephouse_dj", "deephouse",
         (_s("intro", 32), _s("groove", 32), _s("breakdown", 16), _s("groove", 32), _s("outro", 32)),
         fill_every=16, tags=frozenset({"deephouse", "dj", "long"}), source="§1 BeatKey, TPS",
         about="A DJ-friendly deep house track: long intro and outro, something changes every 16 bars"),
    Form("house_jack", "house",
         (_s("intro", 16), _s("groove", 32), _s("breakdown", 16), _s("groove", 32), _s("outro", 16)),
         fill_every=8, fill="perc.tom_run", tags=frozenset({"house", "chicago", "jacking"}), source="§2 SONAA",
         about="Classic house: a tom run every 8 bars, a short breakdown, little else"),
    Form("techhouse_dj", "techhouse",
         (_s("intro", 32), _s("build", 16), _s("drop", 32), _s("breakdown", 16), _s("build", 8), _s("drop", 32),
          _s("outro", 32)),
         fill_every=8, tags=frozenset({"techhouse", "dj"}), source="§3 Mix Elite, Abletonic",
         about="Tech house for DJs: fills every 8, the kick out on the last bar of each build"),
    Form("techno_plateau", "techno",
         (_s("intro", 32), _s("build", 16), _s("groove", 32, mute=["perc"]), _s("breakdown", 16),
          _s("groove", 32, enter={"perc": 17}), _s("outro", 32)),
         fill_every=16, tags=frozenset({"techno", "hypnotic", "plateau"}), source="§5 TrackSensei, Schunk",
         about="Techno plateaus: one new element enters in the second groove, fills every 16"),
    Form("progressive_journey", "progressivehouse",
         (_s("intro", 32), _s("build", 16), _s("groove", 32), _s("breakdown", 32), _s("build", 16), _s("drop", 32),
          _s("outro", 32)),
         energy_filter=True, fill_every=8, tags=frozenset({"progressivehouse", "journey", "filter"}),
         source="§4 BeatKey, WMDM, Myloops",
         about="A progressive journey: the filter is the performance; the bar before each drop nearly empty"),
    Form("melodic_journey", "melodictechno",
         (_s("intro", 32, tracks=["kick", "bass"]), _s("breakdown", 16), _s("build", 8), _s("drop", 32),
          _s("breakdown", 16), _s("drop", 32), _s("outro", 16)),
         energy_filter=True, fill_every=None, tags=frozenset({"melodictechno", "journey", "cinematic", "filter"}),
         source="§8 NI, Soundtrap",
         about="Melodic techno: a filtered kick-and-bass intro, the drop previewed filtered, space before each drop"),
    Form("minimal_long", "minimal",
         (_s("intro", 32), _s("groove", 64, enter={"rim": 17, "clap": 33}, exit={"open hat": 49}),
          _s("breakdown", 16), _s("groove", 64, exit={"rim": 17, "clap": 49}, enter={"open hat": 33}),
          _s("outro", 32)),
         fill_every=None, tags=frozenset({"minimal", "minimal.house", "minimal.techno", "long", "hypnotic"}),
         source="§6 Schunk, TPS, Brizm",
         about="Minimal: long grooves where the change is one element entering or leaving every 16 bars; no fills"),
    Form("tropical_song", "tropicalhouse",
         (_s("intro", 16), _s("groove", 16, energy=2), _s("breakdown", 8), _s("drop", 16, energy=4),
          _s("groove", 16), _s("breakdown", 8), _s("drop", 16, energy=4), _s("outro", 16)),
         fill_every=8, tags=frozenset({"tropicalhouse", "song", "pop"}), source="§7 Splice, Melodigging",
         about="Tropical house as a song: verse, pre-chorus lift, a hook-led drop at energy 4, not a festival drop"),
    Form("club", None, (), preset="club", tags=frozenset({"any", "preset"}), source="existing (v0.6.1)",
         about="The v0.6.1 club preset: intro 16, build 8, drop 16, break 8, drop 16, outro 16"),
    Form("short_demo", None, (), preset="short_demo", tags=frozenset({"any", "preset"}), source="existing (v0.6.1)",
         about="The v0.6.1 short demo preset: about 75 seconds at the current tempo"),
)}

MOVES = {m.name: m for m in (
    Move("build", 8, frozenset({"build", "drop"}), "spec §6.2; research shared norms",
         "A build of N bars (default 8): hats in for the last 4, kick out and a snare roll on the last bar, then a "
         "16-bar drop at energy 5, then the beat keeps playing", ("build up", "buildup", "build to the drop")),
    Move("drop", 16, frozenset({"drop"}), "spec §6.2",
         "All in on the next bar at energy 5 for N bars (default 16), the 'drop mix' if saved, a crash on a "
         "labelled cymbal, then the beat keeps playing", ("all in", "slam it")),
    Move("breakdown", 16, frozenset({"breakdown"}), "spec §6.2; research §1-8",
         "A breakdown of N bars (default 16) in the genre's style, then the beat keeps playing", ("break",)),
    Move("slam", None, frozenset({"drop", "stop"}), "spec §6.2",
         "One bar of everything dropped except fx, then all in with a fill, then the beat keeps playing",
         ("stop and drop", "silence")),
)}


def _word(value):
    return " ".join(str(value).strip().lower().replace("_", " ").replace("-", " ").split())


def section_type(value):
    word = _word(value)
    word = TYPE_ALIASES.get(word, word)
    if word not in SECTION_TYPES:
        raise FormError(f"unknown section type {value!r}; use one of {', '.join(SECTION_TYPES)}")
    return word


def move_name(value):
    word = _word(value)
    for m in MOVES.values():
        if word == m.name or word in m.aliases:
            return m.name
    raise FormError(f"unknown move {value!r}; use one of {', '.join(MOVES)}")


def check_then(value, default):
    if value in (None, ""):
        return default
    word = _word(value)
    if word not in THEN:
        raise FormError(f"then must be one of {', '.join(THEN)}, got {value!r}")
    return word


def breakdown_style(genre):
    """The breakdown style of a genre record (None: the default for soul, breaks and unknown genres)."""
    return genre.breakdown if genre is not None and genre.breakdown in BREAKDOWNS else DEFAULT_BREAKDOWN


def energy_filter_on(genre):
    """Whether a genre's own form turns the music filter on (progressive house and melodic techno)."""
    f = FORMS.get(genre.form) if genre is not None else None
    return bool(f and f.energy_filter)


def parse(text):
    """'intro 16, groove 16, build 8' -> [{"type", "bars"}]. A bare type takes its default bars."""
    items = [p.strip() for p in re.split(r"[,;\n]+", str(text)) if p.strip()]
    if not items:
        raise FormError("a form string lists sections like 'intro 16, groove 16, build 8, drop 16'")
    out = []
    for item in items:
        m = re.fullmatch(r"(.+?)(?:\s+(\d+)(?:\s*bars?)?)?", item.strip().lower())
        kind = section_type(m.group(1))
        bars = int(m.group(2)) if m.group(2) else SECTION_TYPES[kind]["bars"]
        out.append({"type": kind, "bars": bars})
    if len(out) > arrange.SECTIONS_MAX:
        raise FormError(f"at most {arrange.SECTIONS_MAX} sections, got {len(out)}")
    total = sum(s["bars"] for s in out)
    if total > arrange.TOTAL_BARS_MAX:
        raise FormError(f"the form adds up to {total} bars; at most {arrange.TOTAL_BARS_MAX}")
    return out


def check_energy(value, where="energy"):
    """1-5 or "rising" -> int or RISING. Raises FormError."""
    if isinstance(value, str) and _word(value) in (RISING, "rise", "up"):
        return RISING
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float("nan")
    if isinstance(value, bool) or not (ENERGY_MIN <= number <= ENERGY_MAX and number == int(number)):
        raise FormError(f"{where}: energy must be {ENERGY_MIN}-{ENERGY_MAX} or 'rising', got {value!r}")
    return int(number)


def rising_steps(bars):
    """{offset in the section: level} for a rising section: 2 at the start, 3 at a third, 4 at two thirds."""
    if bars < len(RISING_LEVELS):
        return {0: RISING_LEVELS[0]}
    return {round(i * bars / len(RISING_LEVELS)): lvl for i, lvl in enumerate(RISING_LEVELS)}


def expand(raw, genre=None, energy_filter=False, form=None, names=None):
    """Section dicts that may carry `type` (and energy) -> plain arrange section dicts. Pure.

    genre: the playing genre's record (its breakdown style), or None. energy_filter: add the music-filter ramps.
    form: the Form whose fill_every / fill override the types'. A dict without type or energy comes back unchanged,
    so pre-0.9.3 sections play exactly as before. Returns (sections, warnings)."""
    if not isinstance(raw, list):
        raise FormError("give sections as a list")
    out, warnings, counts = [], [], {}
    filt = FILTER_DEFAULT
    style = breakdown_style(genre)
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            out.append(item)  # arrange.sections() reports it
            continue
        sec = dict(item)
        kind = sec.pop("type", None)
        if kind is not None:
            kind = section_type(kind)
            base = {k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v)
                    for k, v in SECTION_TYPES[kind].items()}
            if kind == "breakdown":
                base.update(BREAKDOWNS[style])
            if form is not None and "fill_every" in base:
                if form.fill_every is None:
                    base.pop("fill_every")
                elif form.fill_every != "type":
                    base["fill_every"] = form.fill_every
                if form.fill and "fill_every" in base:
                    base["fill"] = form.fill
            if sec.get("tracks") is not None or sec.get("mute") is not None:
                base.pop("tracks", None)
                base.pop("mute", None)
            merged = {**base, **sec}
            bars = merged.get("bars")
            if isinstance(bars, int) and not isinstance(bars, bool) and bars > 0:
                # audit: a short section warns, never refuses (Q-A4). A type's own fill_every or enter that doesn't
                # fit fits itself to the section (a fill on its last bar; hats in from the start); given keys don't.
                if "fill_every" not in sec and isinstance(merged.get("fill_every"), int) and \
                        merged["fill_every"] > bars:
                    merged["fill_every"] = bars
                if "enter" not in sec and isinstance(merged.get("enter"), dict):
                    fits = {g: off for g, off in merged["enter"].items()
                            if isinstance(off, int) and (1 <= off <= bars or -bars < off < 0)}
                    if fits:
                        merged["enter"] = fits
                    else:
                        merged.pop("enter")
            if "name" not in sec:
                counts[kind] = counts.get(kind, 0) + 1
                merged["name"] = kind if counts[kind] == 1 else f"{kind} {counts[kind]}"
            if kind == "build" and i + 1 < len(raw) and isinstance(raw[i + 1], dict) and \
                    raw[i + 1].get("type") == "drop" and form is not None and form.name == "progressive_journey":
                merged["drop"] = ["kick", "bass"]  # the bar before each drop nearly empty (research §4)
            sec = merged
        energy = sec.get("energy")
        if energy is not None:
            energy = sec["energy"] = check_energy(energy, f"section {i + 1}")
            if energy != RISING and "tracks" not in sec and "mute" not in sec and ENERGY_GROUPS[energy] is not None:
                sec["tracks"] = list(ENERGY_GROUPS[energy])
        if energy_filter and energy is not None:
            ramps = list(sec.get("ramps") or [])
            if energy == RISING:
                ramps.append({"track": "music", "param": "filter_freq", "from": arrange.BUILD_FROM,
                              "to": arrange.BUILD_TO, "bars": sec["bars"], "curve": "exp"})
                filt = arrange.BUILD_TO
            elif isinstance(energy, int) and energy in ENERGY_FILTER and ENERGY_FILTER[energy] != filt:
                ramps.append({"track": "music", "param": "filter_freq", "from": filt, "to": ENERGY_FILTER[energy],
                              "bars": min(FILTER_BARS, sec["bars"]) if isinstance(sec.get("bars"), int) else 1})
                filt = ENERGY_FILTER[energy]
            if ramps:
                sec["ramps"] = ramps
        if kind is not None or energy is not None:
            bars = sec.get("bars")
            if isinstance(bars, int) and bars % BARS_UNIT:
                warnings.append(f"{sec.get('name') or f'section {i + 1}'} is {bars} bars: DJs count in 8, 16 "
                                "and 32 (it plays anyway)")
        out.append(sec)
    return out, warnings


def form_sections(form):
    """A library Form -> its section dicts (with type)."""
    return [dict(s) for s in form.sections]


def move_sections(name, bars, genre=None, drop_mix=False):
    """A move -> (section dicts with type, energy_filter). Raises FormError on a bad bars."""
    move = MOVES[move_name(name)]
    if move.bars is None:
        if bars not in (None, ""):
            raise FormError(f"{move.name} is two bars long; bars is for build, drop and breakdown")
        n = None
    elif bars in (None, ""):
        n = move.bars
    else:
        try:
            n = arrange._whole(bars, 1, arrange.SECTION_BARS_MAX, "bars")
        except arrange.ArrangeError as exc:
            raise FormError(str(exc)) from None
    filt = energy_filter_on(genre)
    drop = {"type": "drop", "bars": 16, "_crash": True}
    if drop_mix:
        drop["mix"] = DROP_MIX
    if move.name == "build":
        return [{"type": "build", "bars": n}, drop], filt
    if move.name == "drop":
        return [{**drop, "bars": n}], filt
    if move.name == "breakdown":  # the filter only moves in a build (it would stay closed after continue)
        return [{"type": "breakdown", "bars": n}], False
    return [{"name": "slam", "bars": 1, "tracks": ["fx"]},
            {"name": "all in", "bars": 1, "tracks": "all", "fill": True}], False
