"""Groove library (v0.9.0, ontology O1a): drum lanes, grooves with five energy levels, velocity curves, ghost notes,
microtiming and named fills. Pure tables plus a compiler; no MIDI, no engine state.

- A Lane is one drum role's part: 1, 2 or 4 bars of 16 cells (x hit, X accent, g ghost, . rest), a velocity curve
  (a name in VELOCITY_CURVES, or 16 ints), optional microtiming (16 offsets in clock ticks, -3..+3) and a gate.
- A Groove is a drum kit's feel at energy 1-5. Each level lists its full set of slots ({slot: lane}), where a slot
  is a drum role ("perc2" is a second perc lane). Classic grooves are today's hand-written patterns: at energy 3
  they *are* the registered pattern; their other levels use "@" (the pattern's own track for that role) or
  "@+<lane>" (that track plus the lane's hits on steps it doesn't already play), and carry no microtiming.
- compile() turns a groove and an energy level into an ordinary patterns.Pattern, in the tool thread. The
  sequencer plays its per-hit offsets as it plays humanize's (t0 + offset * tick), so nothing in the clock changes.

Microtiming. One clock tick is 60 / (BPM x 24) s, about 20 ms at 122 BPM, and one 16th step is 6 ticks. A step's
notes are queued at that step's tick, so a negative offset can't play in place: the compiler moves it to the
previous step at offset 6 + micro, plus the swing difference between the two steps at the groove's own swing (the
sequencer delays odd steps by (swing - 0.5) * 2 steps). On step 0 it is clamped to 0 and reported. Whether these
offsets are audible above USB jitter is HW O-1 (docs/executing/ontology-v1-spec.md §8).
"""
import random
from dataclasses import dataclass, field, replace

from . import kitmap, patterns

STEPS = patterns.STEPS
TICKS_PER_STEP = 6  # engine.TICKS_PER_STEP (24 PPQN / 4); kept here so this module stays free of the engine
GHOST_VEL = (28, 40)  # Q-G4: a g cell's velocity range. If ghosts vanish under VELOCITY TO VOL, raise to (40, 55).
ACCENT_BOOST = 15  # an X cell plays its curve value + 15 (capped at 127)
MICRO_MAX = 3.0
ENERGY_LEVELS = (1, 2, 3, 4, 5)
DRUM_ROLES = frozenset({"kick", "snare", "rim", "clap", "closed hat", "open hat", "cymbal", "perc"})
# Default track for a lane role, in the layout patterns.py uses. perc goes to 8 only where the genre puts perc.
DEFAULT_TRACKS = {"kick": 1, "snare": 2, "rim": 2, "clap": 3, "closed hat": 4, "open hat": 5, "perc": 8}

VELOCITY_CURVES = {
    "flat": tuple(100 for _ in range(STEPS)),
    "beats": tuple(120 if s % 4 == 0 else 90 for s in range(STEPS)),  # as parts.ACCENT / UNACCENTED
    "offbeat_lift": tuple(104 if s % 4 == 2 else 88 if s % 4 == 0 else 72 for s in range(STEPS)),
    "shuffle": tuple(84 if s % 4 == 2 else 62 if s % 2 == 0 else 44 for s in range(STEPS)),  # the techhouse hats
    "deep_hat": tuple(58 if s % 4 == 0 else 40 if s % 2 else 48 for s in range(STEPS)),  # the deep house hats
    "crescendo": tuple(56 + 4 * s for s in range(STEPS)),
    "ghosted": tuple(100 for _ in range(STEPS)),  # accents at 115 (X), g cells in GHOST_VEL
    "soft": tuple(96 if s % 4 == 0 else 80 for s in range(STEPS)),  # rounded transients (tropical, research §7)
}


class GrooveError(ValueError):
    pass


@dataclass(frozen=True)
class Lane:
    name: str  # "hat.offbeat_shuffle"
    role: str  # a drum role (DRUM_ROLES)
    grid: tuple  # 1, 2 or 4 bars of 16 cells
    velocity: object  # a curve name or 16 ints 1-127
    micro: tuple = ()  # 16 offsets in clock ticks, -3..+3; () = none
    gate: float = 1
    tags: frozenset = frozenset()
    source: str = ""
    about: str = ""

    @property
    def velocities(self):
        return VELOCITY_CURVES[self.velocity] if isinstance(self.velocity, str) else tuple(self.velocity)

    @property
    def curve(self):
        return self.velocity if isinstance(self.velocity, str) else "custom"


@dataclass(frozen=True)
class Groove:
    name: str  # "deephouse.shuffle"
    aliases: tuple  # ("deephouse.A",) for the classic grooves only
    genre: str
    swing: float
    levels: dict  # energy -> {slot: lane name | "@" | "@+lane"}
    fills: dict = field(default_factory=dict)  # role -> fill name played on fill: true
    tags: frozenset = frozenset()
    source: str = ""
    about: str = ""

    @property
    def classic(self):
        return bool(self.aliases)


def slot_role(slot):
    """'perc2' -> 'perc': a level's slot names a drum role, with a digit for a second lane of that role."""
    return slot.rstrip("0123456789")


def _v(value, **steps):
    """16 velocities: value everywhere, or per-step overrides given as s<step>=velocity."""
    out = [value] * STEPS
    for key, vel in steps.items():
        out[int(key[1:])] = vel
    return tuple(out)


def _m(value, steps):
    """16 micro offsets: value on the given steps, 0 elsewhere."""
    return tuple(float(value) if s in steps else 0.0 for s in range(STEPS))


ODD = tuple(range(1, STEPS, 2))
OFF_8THS = (2, 6, 10, 14)
ALL = tuple(range(STEPS))


def _lane(name, role, grid, velocity, source, about, micro=(), gate=1, tags=()):
    grid = (grid,) if isinstance(grid, str) else tuple(grid)
    return Lane(name, role, grid, velocity, tuple(micro), gate, frozenset(tags), source, about)


LANES = {lane.name: lane for lane in (
    _lane("kick.four_floor", "kick", "x...x...x...x...", _v(120), "all genres", "Four on the floor"),
    _lane("kick.last_offbeat", "kick", "x...x...x...x.x.", _v(120, s14=96), "§2 Attack",
          "Four on the floor plus the last off-beat 16th (step 14)"),
    _lane("kick.ghost_mid", "kick", "x...x..gx...x...", _v(120), "§2 Attack",
          "Four on the floor plus a ghost kick on step 7"),
    _lane("kick.ghost_7", "kick", ".......g........", _v(120), "§2 Attack",
          "Helper: the ghost kick alone, laid over a classic kick at energy 5", tags={"helper"}),
    _lane("clap.2_4", "clap", "....x.......x...", _v(104), "all genres", "Clap on 2 and 4"),
    _lane("clap.2_4_ghosted", "clap", "....x..g....x..g", "ghosted", "§1 SONAA (10-20 ms late)",
          "Clap on 2 and 4, laid back, with ghosts on 7 and 15", micro=_m(0.75, (4, 12))),
    _lane("clap.jacked", "clap", "....x.......x..x", _v(104, s15=84), "§2 Attack (late or jacked clap)",
          "Late clap on 2 and 4 plus the last 16th: the jack", micro=_m(0.5, (4, 12, 15))),
    _lane("clap.ghosts", "clap", ".......g.......g", "ghosted", "§2, §3 (ghosts are mandatory)",
          "Helper: clap ghosts on 7 and 15, laid over a classic clap at energy 4", tags={"helper"}),
    _lane("snare.2_4", "snare", "....x.......x...", _v(96), "§3 TPS (layered clap/snare)",
          "Snare on 2 and 4, layered under the clap"),
    _lane("rim.bossa", "rim", "x..x..x...x..x..", _v(70), "by ear", "Syncopated 3-3-4-3-3 rim"),
    _lane("rim.syncopated", "rim", "...x..x....x....", _v(72), "§2 Attack (syncopated rim or cowbell)",
          "Rim on 3, 6 and 11"),
    _lane("rim.syncopated_busy", "rim", "...x..x....x..x.", _v(72), "§2 Attack",
          "Helper: rim on 3, 6, 11 and 14, the energy 5 form of rim.syncopated", tags={"helper"}),
    _lane("hat.closed_8ths", "closed hat", "x.x.x.x.x.x.x.x.", "deep_hat", "§1 TPS (8ths, not 16ths)",
          "Closed 8ths, off-beat 8ths a touch late", micro=_m(0.25, OFF_8THS)),
    _lane("hat.closed_16ths", "closed hat", "xxxxxxxxxxxxxxxx", "shuffle", "§2, §8", "Closed 16ths, shuffle accents"),
    _lane("hat.offbeat_shuffle", "closed hat", "xgxgxgxgxgxgxgxg", "deep_hat", "§1 SONAA, BeatKey (54-60%)",
          "16ths with ghosted odd steps, odd steps late", micro=_m(0.25, ODD)),
    _lane("hat.push_16ths", "closed hat", "xxXxxxXxxxXxxxXx", "shuffle", "§3 Mix Elite (hits just before the beat)",
          "Accented 16ths pushed just ahead of the grid", micro=_m(-0.25, ALL)),
    _lane("hat.offbeat_open", "open hat", "..x...x...x...x.", _v(84), "all genres", "Open hat on the off-beats"),
    _lane("perc.shaker_16", "perc", "xgxgxgxgxgxgxgxg", _v(64), "§1, §7", "Ghosted shaker 16ths, a touch late",
          micro=_m(0.25, ALL)),
    _lane("perc.conga_offbeats", "perc", "..x...x...x...x.", _v(70), "§1, §6 Attack", "Soft congas on the off-beats",
          micro=_m(0.5, OFF_8THS)),
    _lane("perc.rolling", "perc", "...x..x....x..x.", _v(76), "§5 Schunk", "Perc between the kicks (3, 6, 11, 14)"),
    _lane("perc.woodblock", "perc", ".......X.......X", _v(90), "§3 TPS", "Woodblock accents on 7 and 15"),
)}


def _g(name, genre, swing, levels, source, about, fills=None, aliases=(), tags=()):
    return Groove(name, tuple(aliases), genre, swing, {e: dict(lv) for e, lv in levels.items()}, dict(fills or {}),
                  frozenset({genre, *tags}), source, about)


def _classic(genre, swing, layout, about):
    """A classic groove from today's pattern: energy 3 is the pattern itself (layout lists its drum roles)."""
    base = {"kick": "@", "open hat": "@"}
    two = {**base, "clap": "@", "closed hat": "@"}
    three = {**two, **{role: "@" for role in layout}}
    four = {**three, "clap": "@+clap.ghosts"}
    five = {**four, "kick": "@+kick.ghost_7"}
    return _g(f"{genre}.classic", genre, swing, {1: base, 2: two, 3: three, 4: four, 5: five}, "existing pattern",
              about, aliases=(f"{genre}.A",), tags={"classic"})


GROOVES = {g.name: g for g in (
    _classic("deephouse", 0.55, ("rim",), "Today's deep house pattern (the demo's beat)"),
    _g("deephouse.shuffle", "deephouse", 0.56, {
        1: {"kick": "kick.four_floor", "open hat": "hat.offbeat_open"},
        2: {"kick": "kick.four_floor", "open hat": "hat.offbeat_open", "clap": "clap.2_4_ghosted",
            "closed hat": "hat.closed_8ths"},
        3: {"kick": "kick.four_floor", "open hat": "hat.offbeat_open", "clap": "clap.2_4_ghosted",
            "closed hat": "hat.closed_8ths", "perc": "perc.conga_offbeats"},
        4: {"kick": "kick.four_floor", "open hat": "hat.offbeat_open", "clap": "clap.2_4_ghosted",
            "closed hat": "hat.offbeat_shuffle", "perc": "perc.conga_offbeats"},
        5: {"kick": "kick.ghost_mid", "open hat": "hat.offbeat_open", "clap": "clap.2_4_ghosted",
            "closed hat": "hat.offbeat_shuffle", "perc": "perc.conga_offbeats"},
    }, "§1", "Swung 8th hats, a late ghosted clap and soft congas", fills={"clap": "snare.roll"},
        tags={"shuffle", "warm"}),
    _g("house.jack", "house", 0.52, {
        1: {"kick": "kick.four_floor", "open hat": "hat.offbeat_open"},
        2: {"kick": "kick.four_floor", "open hat": "hat.offbeat_open", "clap": "clap.2_4",
            "closed hat": "hat.closed_16ths"},
        3: {"kick": "kick.four_floor", "open hat": "hat.offbeat_open", "clap": "clap.jacked",
            "closed hat": "hat.closed_16ths", "rim": "rim.syncopated"},
        4: {"kick": "kick.ghost_mid", "open hat": "hat.offbeat_open", "clap": "clap.jacked",
            "closed hat": "hat.closed_16ths", "rim": "rim.syncopated"},
        5: {"kick": "kick.ghost_mid", "open hat": "hat.offbeat_open", "clap": "clap.jacked",
            "closed hat": "hat.closed_16ths", "rim": "rim.syncopated_busy"},
    }, "§2 Attack, SONAA", "Jacking 4/4: late jacked clap, 16th hats, syncopated rim",
        fills={"perc": "perc.tom_run"}, tags={"jacking", "chicago"}),
    _g("house.eighths", "house", 0.50, {
        1: {"kick": "kick.four_floor", "open hat": "hat.offbeat_open"},
        2: {"kick": "kick.four_floor", "open hat": "hat.offbeat_open", "clap": "clap.2_4",
            "closed hat": "hat.closed_8ths"},
        3: {"kick": "kick.last_offbeat", "open hat": "hat.offbeat_open", "clap": "clap.2_4",
            "closed hat": "hat.closed_8ths", "rim": "rim.syncopated"},
        4: {"kick": "kick.last_offbeat", "open hat": "hat.offbeat_open", "clap": "clap.jacked",
            "closed hat": "hat.closed_8ths", "rim": "rim.syncopated"},
        5: {"kick": "kick.last_offbeat", "open hat": "hat.offbeat_open", "clap": "clap.jacked",
            "closed hat": "hat.closed_8ths", "rim": "rim.syncopated_busy"},
    }, "§2 Attack", "Straight 8th hats, a kick on the last off-beat", fills={"perc": "perc.tom_run"},
        tags={"chicago"}),
    _classic("techhouse", 0.56, ("rim", "perc"), "Today's tech house pattern"),
    _g("techhouse.rolling", "techhouse", 0.53, {
        1: {"kick": "kick.four_floor", "open hat": "hat.offbeat_open"},
        2: {"kick": "kick.four_floor", "open hat": "hat.offbeat_open", "clap": "clap.2_4",
            "closed hat": "hat.push_16ths"},
        3: {"kick": "kick.four_floor", "open hat": "hat.offbeat_open", "clap": "clap.2_4", "snare": "snare.2_4",
            "closed hat": "hat.push_16ths", "perc": "perc.shaker_16"},
        4: {"kick": "kick.ghost_mid", "open hat": "hat.offbeat_open", "clap": "clap.2_4", "snare": "snare.2_4",
            "closed hat": "hat.push_16ths", "perc": "perc.shaker_16"},
        5: {"kick": "kick.ghost_mid", "open hat": "hat.offbeat_open", "clap": "clap.2_4", "snare": "snare.2_4",
            "closed hat": "hat.push_16ths", "perc": "perc.shaker_16", "perc2": "perc.woodblock"},
    }, "§3 Mix Elite, TPS", "Pushed 16th hats, layered clap and snare, a shaker",
        fills={"kick": "kick.sit_out"}, tags={"rolling"}),
    _classic("techno", 0.50, ("rim", "perc"), "Today's techno pattern"),
    _g("techno.rolling", "techno", 0.50, {
        1: {"kick": "kick.four_floor", "open hat": "hat.offbeat_open"},
        2: {"kick": "kick.four_floor", "open hat": "hat.offbeat_open", "perc": "perc.rolling"},
        3: {"kick": "kick.four_floor", "open hat": "hat.offbeat_open", "perc": "perc.rolling", "clap": "clap.2_4"},
        4: {"kick": "kick.four_floor", "open hat": "hat.offbeat_open", "perc": "perc.rolling", "clap": "clap.2_4",
            "closed hat": "hat.closed_16ths"},
        5: {"kick": "kick.ghost_mid", "open hat": "hat.offbeat_open", "perc": "perc.rolling", "clap": "clap.2_4",
            "closed hat": "hat.closed_16ths", "rim": "rim.syncopated"},
    }, "§5 Schunk, Beatportal", "Kick-led: off-beat hats and rolling perc, the clap from energy 3",
        fills={"kick": "kick.sit_out"}, tags={"rolling", "hypnotic"}),
)}
ALIASES = {alias: g.name for g in GROOVES.values() for alias in g.aliases}
CLASSIC = {g.genre: g.name for g in GROOVES.values() if g.classic}  # genre -> its classic groove


# ---- fills ------------------------------------------------------------------

@dataclass(frozen=True)
class Fill:
    name: str
    roles: frozenset  # the drum roles it plays on when no tracks are named
    about: str
    source: str
    fallback: str = None  # a fill played instead when no track has one of its roles


FILLS = {f.name: f for f in (
    Fill("kick.sit_out", frozenset({"kick"}), "The kick sits out the last beat (v0.6.1 shape)", "existing"),
    Fill("snare.roll", frozenset({"snare", "rim"}), "A crescendo roll through the second half (v0.6.1)", "existing"),
    Fill("clap.push", frozenset({"clap", "perc"}), "Claps pushing into the one: 12, 14, 15 (v0.6.1)", "existing"),
    Fill("hat.ratchet", frozenset({"closed hat"}), "32nd ratchets on the last beat (v0.6.1)", "existing"),
    Fill("open.clear", frozenset({"open hat", "cymbal"}), "Open hat out of the roll's way (v0.6.1)", "existing"),
    Fill("snare.flam_roll", frozenset({"snare", "rim"}), "A roll of flams (a quiet grace hit before each)", "by ear"),
    Fill("kick.double", frozenset({"kick"}), "Extra kicks on 14 and 15 into the one", "by ear"),
    Fill("hat.open_choke", frozenset({"open hat"}), "Long open hat on 12, choked short on 14", "by ear"),
    Fill("perc.tom_run", frozenset({"perc"}), "A falling tom run (notes 60, 57, 53) on a perc track",
         "§2 (simple tom rolls every 8)", fallback="snare.roll"),
)}


# ---- compile ----------------------------------------------------------------

def parse_cells(text):
    """'x..g X...' -> [(step, kind)] with kind 'x', 'X' or 'g'. Raises GrooveError."""
    cells = [c for c in text if c not in " |"]
    if len(cells) != STEPS or any(c not in "xXg.-" for c in cells):
        raise GrooveError(f"lane bar must be 16 cells of x, X, g or ., got {text!r}")
    return [(s, c) for s, c in enumerate(cells) if c in "xXg"]


def ghost_velocity(name, bar, step):
    low, high = GHOST_VEL
    return random.Random(f"ghost:{name}:{bar}:{step}").randint(low, high)


def swing_ticks(step, swing):
    """How late the sequencer plays a step at this swing, in ticks (odd steps only)."""
    return (swing - 0.5) * 2 * TICKS_PER_STEP if step % 2 else 0.0


def lane_bars(lane, swing=0.5, note=patterns.DRUM, notes=None):
    """One lane -> (4 bars of working hits (step, note, velocity, gate, offset_ticks), clamped steps).

    notes: an optional list cycled over the hits (a pitched perc); default the drum note 60.
    """
    vels = lane.velocities
    out, clamped, n = [], [], 0
    for bar in range(patterns.BARS):
        hits = []
        for step, kind in parse_cells(lane.grid[bar % len(lane.grid)]):
            if kind == "g":
                vel = ghost_velocity(lane.name, bar, step)
            elif kind == "X":
                vel = min(127, vels[step] + ACCENT_BOOST)
            else:
                vel = vels[step]
            micro = lane.micro[step] if lane.micro else 0.0
            pitch = notes[n % len(notes)] if notes else note
            n += 1
            if micro >= 0:
                hits.append((step, pitch, vel, lane.gate, float(micro)))
            elif step == 0:
                hits.append((0, pitch, vel, lane.gate, 0.0))
                if bar == 0:
                    clamped.append(lane.name)
            else:
                prev = step - 1
                offset = TICKS_PER_STEP + micro + swing_ticks(step, swing) - swing_ticks(prev, swing)
                hits.append((prev, pitch, vel, lane.gate, round(offset, 6)))
        out.append(sorted(hits, key=lambda h: (h[0], h[4])))
    return out, clamped


def _merge(own, extra):
    """A hand-written track's bars (4-field hits) plus a lane's hits on steps that bar doesn't play yet."""
    out = []
    for bar, add in zip(own, extra):
        used = {h[0] for h in bar}
        merged = list(bar) + [h for h in add if h[0] not in used]
        out.append(sorted(merged, key=lambda h: (h[0], h[4] if len(h) > 4 else 0.0)))
    return out


def drum_tracks(pattern):
    """{track: drum role} for the pattern's drum tracks (note 60 lines with a drum role)."""
    out = {}
    for track, bars in pattern.bars.items():
        role = kitmap.generated_role(pattern.roles.get(track))
        if role in DRUM_ROLES and not patterns.is_melodic(bars):
            out[track] = role
    return out


def _target(role, slot, base, kit, taken):
    """Which pattern track a lane slot is written on, or None (unplaced).

    A slot's first lane goes to the default track for its role (DEFAULT_TRACKS) when the genre doesn't use that
    track for something melodic (perc only where the genre has perc there); kitmap.route then moves it onto a
    labelled track as usual. Otherwise it goes to a labelled track with that role, or a close one. A second lane
    of a role ("perc2") needs a second labelled track.
    """
    if slot == role:
        default = DEFAULT_TRACKS.get(role)
        if default is not None and default not in taken:
            held = kitmap.generated_role(base.roles.get(default)) if default in base.roles else None
            if (held is None or held in DRUM_ROLES) and (role != "perc" or held == "perc"):
                return default
    wanted = {role, *kitmap.CLOSE.get(role, ())}
    labelled = [t for t, (r, _) in sorted(kit.items()) if r in wanted]
    if slot != role:
        labelled = labelled[1:]
    free = [t for t in labelled if t not in taken]
    return free[0] if free else None


def level(groove, energy):
    if energy not in groove.levels:
        raise GrooveError(f"{groove.name} has no energy {energy}; levels: {sorted(groove.levels)}")
    return groove.levels[energy]


def compile(groove, energy, base, kit=None, name=None):
    """(Pattern, info) for groove at energy over base (the genre's pattern: its melodic tracks, key, bpm).

    info: {"lanes": {slot: lane}, "unplaced": {slot: lane}, "tracks": {slot: track}, "clamped": [...]}.
    A classic groove at energy 3 returns base itself, so it plays today's pattern bit for bit.
    """
    kit = kit or {}
    slots = level(groove, energy)
    info = {"lanes": dict(slots), "unplaced": {}, "tracks": {}, "clamped": []}
    if groove.classic and energy == 3:
        info["tracks"] = {slot: t for t, r in drum_tracks(base).items() for slot in slots if slot_role(slot) == r}
        return base, info
    own = drum_tracks(base)
    bars = {t: b for t, b in base.bars.items() if t not in own}
    roles = {t: r for t, r in base.roles.items() if t not in own}
    taken = set(bars)
    for slot, ref in slots.items():
        role = slot_role(slot)
        if ref.startswith("@"):
            track = next((t for t, r in own.items() if r == role), None)
            if track is None:
                info["unplaced"][slot] = ref
                continue
            track_bars = base.bars[track]
            if ref.startswith("@+"):
                extra, clamped = lane_bars(LANES[ref[2:]], groove.swing)
                track_bars = _merge(track_bars, extra)
                info["clamped"] += clamped
            bars[track], roles[track] = track_bars, base.roles[track]
            taken.add(track)
            info["tracks"][slot] = track
            continue
        lane = LANES[ref]
        track = _target(role, slot, base, kit, taken)
        if track is None:
            info["unplaced"][slot] = ref
            continue
        lane_hits, clamped = lane_bars(lane, groove.swing)
        bars[track], roles[track] = lane_hits, role
        taken.add(track)
        info["tracks"][slot] = track
        info["clamped"] += clamped
    short = groove.name.split(".", 1)[1]
    pattern = replace(base, name=name or f"{groove.genre}+{short}@{energy}", swing=groove.swing,
                      roles=dict(sorted(roles.items())), bars=dict(sorted(bars.items())),
                      shifts={t: s for t, s in base.shifts.items() if t in bars}, genre=groove.genre)
    return pattern, info


def hits_per_level(groove, base):
    """{energy: drum hits over the 4-bar loop} with every slot placed (two labelled perc tracks): integrity test."""
    kit = {11: ("perc", "perc"), 12: ("perc", "perc two")}
    out = {}
    for energy in groove.levels:
        pattern, info = compile(groove, energy, base, kit)
        out[energy] = sum(len(bar) for t in info["tracks"].values() for bar in pattern.bars.get(t, []))
    return out


def describe_lane(lane):
    micro = sorted({m for m in lane.micro if m}) if lane.micro else []
    return {"name": lane.name, "role": lane.role, "bars": len(lane.grid), "grid": list(lane.grid),
            "velocity_curve": lane.curve, "micro": micro, "about": lane.about}
