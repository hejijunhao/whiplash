# Whiplash ontology v1: spec

Status:
- **Spec only, for Phil's review.** Branch `docs/ontology-spec`, cut from `main` at `3f4f883` (v0.8.0 merged, PR #23; visualiser timeline, PR #24).
- No code, tests, tool or version changes come with it.
- Nothing here has been tested on a real Digitakt II. Every claim marked **HW** is a check for Phil's Air, not a result.

Inputs:
- Phil's DeepSeek V4 sessions. With a weaker model, the beats still come out slightly simplistic.
- The diagnosis we agree on: today the model has to invent theory and groove on every bar, so a weaker model falls back on four on the floor plus a root note.
- Every module named below, read on `main` at `3f4f883`.

**Goal (the demo sentence):** "Deep house groove B, energy 3, the late-night progression, an octave-pump bass: three calls, and it doesn't sound like a preset."

**Principle.** Tools take musical intent, for example:
- "darker"
- "more tension"
- "lift the energy"
- "deep house groove B, energy 3"
- "build to drop in 16 bars"

The plugin then does the theory and the timing, deterministically, from in-repo tables. The model's job shrinks to picking and combining named things. It no longer places 16 steps by hand.

## 0. Constraints (every layer, every phase)

- **Never sent:**
  - SysEx or program change (`Engine.send()` refuses them; the allow-list stays as it is).
  - Project, pattern, kit, preset or +Drive writes, and no file transfer.
- **Never touched:** Digitakt slots 1-3.
- **Never read or written:** the unit's internal patterns. Nothing here reads anything from the unit except what v0.8.0's `whiplash_play_along` already hears.
- **Clock-safe and bar-quantised.** No new clock path and no new sequencer thread.
  - Everything compiles, in the tool thread, into what the engine already schedules: a working pattern (`Engine._work`), a progression (`Engine._prog`), queued switches (`_queued`), timed actions (`_timed`: ramps, mixes, kind `call`), fills (`_fills`), drops (`_drops`), mutes, and arrangement sections (`_arr`).
  - At the bar line the sequencer does only cheap lookups and small list work, of the kind `harmony.apply()` already does (at most 64 hits per track per bar).
  - Each new per-bar cost is named in its layer below.
- **`ccmap.BLOCKED_CCS` / `BLOCKED_NRPNS` stay blocked.** No layer needs a new CC. Filters, levels and pan use `filter_freq` (CC 74), `track_level` (CC 95) and `pan` (CC 90), which are already in use.
- **No new hard dependency.**
  - Libraries are Python tables in new pure modules at the repo root (the root is the package), like `patterns.py` today.
  - Not YAML: PyYAML isn't a dependency (`plugin.yaml` lists only mido and python-rtmidi), and the stdlib can't read it.
  - Nothing new is imported by the sequencer that it doesn't already import.
- **Native register (v0.5, [reference](../digitakt-ii/reference.md) §6.1).**
  - Note 60 is the sample's own pitch, and every note stays in 16-84.
  - A melodic line's median stays no more than `patterns.NATIVE_FLOOR` (7) below 60.
  - One voice per audio track is assumed (§6.4, Q12).
- **Tests use fake and virtual ports only:**
  - `make_engine()` and `call()` from `tests/test_whiplash.py`
  - `bar_events()`, `pretend_playing()` and `wait_bar()` from `tests/test_live.py`
  - `FakeInput` from `tests/test_v080.py`
- **Hardware checks go to Phil** as a checklist (§7). The build PRs add them to `docs/testing/hardware-checklist.md` and `reference.md` §15.3 (Q32 on), as earlier versions did.
- **`main` stays demo-safe.** Part A of the hardware checklist is unchanged, `scripts/rehearse_demo.py` prints `RESULT: PASS`, and nothing new runs unless a new argument or tool is used. Every library pick is opt-in, so today's calls play exactly as before.

## 1. Shared pieces (all layers)

### 1.1 Names and lookup: `library.py` (new, pure)

- **One naming scheme for every table:** `<genre or family>.<name>`. Examples: `deephouse.late_night` (progression), `deephouse.B` (groove), `hat.offbeat_shuffle` (lane), `bass.octave_pump` (phrase), `snare.roll` (fill), `club_long` (form), `build` (move).
- **`library.resolve(kind, text)`** accepts what a model is likely to type:
  - case-insensitive
  - spaces, `-` or `_`
  - a missing genre prefix when it is unambiguous
  - "deep house groove b"

  An unknown name raises with the closest matches (`difflib`, as `patterns.resolve()` does) and the hint `see whiplash_list_library(kind: "groove")`.
- **Names are never schema enums.** Enumerating hundreds of names would blow the tool-description budget (§1.3). They are validated in code instead, and listed by `whiplash_list_library`.
- **Every entry carries `tags`** (genre, mood, energy and so on) and a one-line `about`, so the model can choose by meaning.

### 1.2 `whiplash_list_library` (new tool)

```
whiplash_list_library(kind: "progression"|"groove"|"lane"|"phrase"|"fill"|"form"|"move", genre?, tag?)
-> {kind, entries: [{name, about, tags, ...kind-specific: chords | energy_levels | role | bars}], more: n}
```
- At most 40 entries per call, sorted by name. `genre` and `tag` filter the list.
- It is read-only, works with nothing playing, and never touches the engine.
- **Failure hints:**
  - an unknown kind lists the kinds
  - an empty filter says which genres and tags exist
- **Description** (about 120 characters): "List named progressions, grooves, lanes, phrases, fills, forms and moves (with tags) to use by name in other tools."

### 1.3 Tool-description budget

Today the tool descriptions total 4,033 of the 4,100-character cap. The caps are pinned in `tests/test_v053.py::test_description_size_budget`: tools 4,100, params 9,300, JSON 22,000 bytes, and at most 400 per tool. The tool count is pinned in `tests/test_whiplash.py::test_every_tool_is_namespaced` (25) and in `tests/test_v04.py::test_tools_in_manifest_order`.

This spec adds **four tools** and extends five existing ones:

| New tool | Layer |
| --- | --- |
| `whiplash_list_library` | shared |
| `whiplash_set_key` | 1 |
| `whiplash_perform` | 4 |
| `whiplash_review` | 5 |

Extended tools:
- `whiplash_play_pattern`: `groove`, `energy`
- `whiplash_set_progression`: `name`, `intent`
- `whiplash_write_part`: `groove`, `phrase`, `density`, `seed`, `register`, `out_of_key`
- `whiplash_arrange`: `form`, plus section keys `energy`, `fill_every`, `enter`
- `whiplash_mutate`: a `fill` name

Proposed caps once all phases ship:
- tools 4,800 (+700)
- params 10,800 (+1,500)
- JSON 26,000 bytes
- 29 tools

Each phase raises only what it uses. The alternative, folding `set_key` into `set_progression` and `list_library` into `list_params`, saves about 250 characters but gives a weak model a less obvious verb: open question Q-S1.

### 1.4 The skill

`skills/digitakt/SKILL.md` gets:
- a "Named things first" fast path: list, pick, combine
- one worked example per layer
- a diagnostics row per new failure

The descriptions stay short, and the skill stays the single reference, as now.

---

## 2. Layer 1: Harmony

### 2.1 What exists, and the gap

**Exists (`harmony.py`, v0.6.0):**
- `Key` (pitch class plus a scale from `parts.SCALES`: 13 scales and modes, including dorian, phrygian, lydian, mixolydian, harmonic and melodic minor, pentatonics and blues).
- Roman-numeral and chord-name parsing, with shapes in `SHAPES`: triads, 7ths, sus, add9, power.
- `voice()` with voicings `close` (voice-led), `root`, `open` and `power`, near native pitch: median at least 53, notes 41-79.
- `in_key()` moves a pattern's melodic tracks by scale degree, and `snap()` snaps a note to the scale.
- Track modes `chords`, `stack`, `root`, `snap` and `off`, picked by role through `ROLE_MODES` (chord, pad and stab → chords; bass → root; lead → snap). Drum, cymbal and fx tracks are refused.
- `apply()` reshapes each bar's hits at the bar line.
- `whiplash_set_progression` (chords, `bars_per_chord`, voicing, key, scale, per-track overrides, clear) and `key` on `whiplash_play_pattern`. Each pattern has a home key in `patterns.HOME_KEYS`.

**Gap:**
1. **No named, tagged progressions.** The model has to know that deep house likes i7–iv7 or i–VI–III–VII with 9ths.
2. **No 9th or 11th shapes,** and no voicing that sounds like a min9 on the two or three one-voice chord tracks a kit has.
3. **No intent.** "Darker" and "more tension" have to be translated into theory by the model.
4. **Written parts and explicit notes can play out of key.** `whiplash_write_part(notes: ["C#5"])` in A minor plays C#. Only generated melodic tracks follow the key.
5. **Changing the key on its own takes a queued `whiplash_play_pattern` or a `set_progression(key)`.** There is no plain key verb.

### 2.2 Data model: `progressions.py` (new, pure tables) and small additions to `harmony.py`

- **New shapes** in `harmony.SHAPES`:
  - `min9` (0 3 7 10 14), `maj9` (0 4 7 11 14), `9` (0 4 7 10 14), `min11` (0 3 7 10 14 17), `6` (0 4 7 9), `m6` (0 3 7 9), `7sus4` (0 5 7 10)
  - their suffixes in `ROMAN_SUFFIX` (`9`, `maj9`, `11`, `6`, `7sus4`, with the existing upper and lower case rule) and `NAME_SUFFIX` (`m9`, `maj9`, `9`, `m11`, `6`, `m6`, `7sus4`)
- **New voicing `shell`:** for an extended chord, the 3rd, 7th and 9th, or the 3rd, 7th and 5th without a 9th. It leaves the root to the bass.
  - Three chord tracks in `chords` mode then sound a min9 without a root, a common deep house sound (by ear, unverified).
  - It is voice-led like `close`, with the same bounds (`CHORD_LOW` 53 median, 41-79).
- **Progression entries:**

```python
@dataclass(frozen=True)
class Prog:
    name: str            # "deephouse.late_night"
    chords: str          # Roman numerals in the key, e.g. "i9 VImaj7 IIImaj7 VII7"
    bars_per_chord: int  # default for this progression
    voicing: str         # close | root | open | power | shell
    scale: str           # the scale it is written for ("minor", "dorian", ...); the key root comes from the session
    tags: frozenset      # genre, mood words (dark, warm, melancholic, hopeful, hypnotic, tense, dreamy)
    brightness: int      # -2 (darkest) .. +2, for intents
    tension: int         # 0 (static vamp) .. 3 (dominant pull)
    about: str
```

- **Deep house first.** These are starting points by ear, for Phil to correct:

| name | chords (A minor shown) | per chord | tags |
| --- | --- | --- | --- |
| `deephouse.late_night` | i9 VImaj7 IIImaj7 VII (Am9 Fmaj7 Cmaj7 G) | 2 | warm, melancholic |
| `deephouse.two_step` | i7 iv7 (Am7 Dm7) | 2 | hypnotic, classic |
| `deephouse.dorian_lift` | i7 IV9 in dorian (Am7 D9) | 2 | hopeful, soulful |
| `deephouse.minor_vamp` | i9 (Am9, one chord) | 4 | hypnotic, minimal |
| `deephouse.turnaround` | i7 VImaj7 iv7 v7 | 1 | groovy, moving |
| `deephouse.tension_turn` | i7 VImaj7 iv7 V7 (E7: harmonic-minor V) | 1 | tense, dramatic |

  `soul`, `techhouse`, `techno` and `breaks` follow, with three to five each. Techno favours one-chord and two-chord vamps, phrygian ii, and `power` voicings.
- **Intent tables** (`progressions.INTENTS`, pure). Each intent is a deterministic transform of the session's (key, progression):
  - **`darker`:** one step down the brightness ladder: lydian → major → mixolydian → dorian → minor → phrygian. Phrygian is the floor, and locrian is never chosen. The same root and the same numerals are re-voiced in the new mode.
    - Alternatively, the same-genre library progression with the next lower `brightness` and the most shared tags.
    - The rule: with a library progression playing, prefer a library swap; with a hand-written one, shift the mode.
  - **`brighter`:** the reverse.
  - **`tension`:** `tension` +1:
    - turn the last chord into its dominant (V7 from harmonic minor; the home tables already lean on G♯ in A minor)
    - or add sus4 or 9 to the last chord
    - or turn on a bass pedal (new track mode `pedal`: the key's tonic under every chord)
  - **`release`:** back to the progression that was playing before the first `tension`, ending on i or I. The pedal is off.
  - Each intent result names what it did, e.g. `{"intent": "darker", "did": "A minor -> A phrygian", "chords": [...]}`.
- **Key lock** (`harmony.lock`, engine state). With a key set (`Engine.effective_key()`), every explicit melodic note snaps to the scale with `harmony.snap()`. That covers `whiplash_write_part` `notes` and `hits` on non-drum roles, and v0.8.0 follow replies, which already snap.
  - The result lists `snapped: [{"from": "C#5", "to": "C5"}]`.
  - `out_of_key: true` on `write_part` opts out, for a deliberate chromatic note.
  - Drum roles (note 60) are never touched.
- **Auto-follow for written parts** (new): `write_part(..., follow: true)` gives a written melodic part a mode (`snap` by default), so it follows the progression like a generated line. Today written parts play as written unless `set_progression(tracks)` names them. Layer 3's phrases follow by default.

### 2.3 Tools

- **`whiplash_set_progression`** gains:
  - `name: "deephouse.late_night"`: chords, `bars_per_chord` and voicing come from the library. Given arguments override them.
  - `intent: "darker" | "brighter" | "tension" | "release"`
  - `chords`, `name` and `intent` are mutually exclusive.
  - **Failure hints:**
    - unknown name: the closest matches, and `whiplash_list_library(kind: "progression", genre: ...)`
    - `intent` with nothing playing: "start a beat first"
    - `release` with nothing to release: "no tension to release; the progression is unchanged"
- **`whiplash_set_key(key, scale?, lock?)`** (new): the key from the next bar line.
  - It moves the melodic tracks (`in_key`), re-voices a Roman-numeral progression in the new key, and shifts a chord-name progression by the same interval.
  - `lock` (default true) turns key lock on or off.
  - Result: `{key, from, lands_at_bar, progression: [...], lock}`.
  - Description, about 150 characters: "Change the key from the next bar: melodic tracks and the progression move; drums never do. lock (default true) snaps written notes to the key."
  - **Failure hints:** a bad key echoes `parts.parse_key`'s message; a key equal to the current one gives "already in A minor".

### 2.4 Scheduler and tracks

- **Library and intent picks** compile into the same `harmony.Progression` that `set_progression` builds now: parsed and voiced in the tool thread, starting on the next bar (`Progression.start`).
  - The sequencer still does only `prog.index(bar)` plus `harmony.apply()`.
  - The new `pedal` mode is one `nearest()` call per hit, the same as `root`.
- **`set_key`** is a timed action of kind `call` (as `whiplash_undo` does) at the next bar line. It sets `Engine._key` and swaps in a routed pattern prepared in the tool thread.
  - A new shared helper, `_routed(self._raw_pattern, key)`, prepares the routed pattern.
  - It also swaps in a progression re-voiced in the tool thread.
  - The bar line therefore does assignments only, with no voicing and no routing.
- **Roles decide who follows, through `ROLE_MODES` and the kit map, unchanged:**
  - chord, pad and stab tracks (kit roles, or the generated roles on tracks 7-8) take `chords` across one-voice tracks
  - bass takes `root` (or `pedal`)
  - lead takes `snap`
  - drums, cymbal and fx never follow
- **Tracks 9-16** follow only when labelled, as now.

### 2.5 Test plan (fake ports only)

- **Library integrity** (pure):
  - every `Prog` parses in all 12 keys and in its scale
  - every voicing stays within 41-79 with median 53 or more
  - names are unique and resolvable through `library.resolve`
  - tags come from a fixed vocabulary
- **Shapes:** `parse_chord("i9", Am)` is `(9, (0, 3, 7, 10, 14))`, `Am9` and `Fmaj9` read correctly, and `shell` on Am9 gives C, G, B (3rd, 7th, 9th) near 60.
- **Intents:**
  - `darker` from A minor goes to A phrygian, and is idempotent at the floor (the result says so)
  - `tension` then `release` brings the exact previous progression back
  - every result lists what it did
- **Key lock:** `write_part(track: 7, notes: ["C#5"])` in A minor plays C5 (`bar_events`) and reports `snapped`. With `out_of_key: true` it plays C#5. A kick part's note 60 is never moved.
- **`set_key`:** with `pretend_playing`, the key changes exactly on the next bar line. Drum notes are unchanged, the bass median stays 53 or more, and a Roman-numeral progression is re-voiced.
- **Clock safety:** a jitter check (`scripts/clock_jitter.py --calls`) shows no added lateness at the bar line with a library progression and `pedal` running.
- **Budget tests** updated to the phase's caps.

### 2.6 Open questions for Phil (harmony)

- **Q-H1.** Are the six deep house progressions right by ear, and which are missing?
- **Q-H2.** Key lock on by default once a key is set (proposed), or opt-in?
- **Q-H3.** `darker` as a mode shift (A minor → A phrygian) versus a filter close (layer 4): should `darker` do both by default?
- **Q-H4.** `shell` as the default voicing for library 9th chords on audio tracks (proposed), or `close`?

---

## 3. Layer 2: Groove library

### 3.1 What exists, and the gap

**Exists:**
- `patterns.py`: five genre patterns of 4 × 16 steps, with per-step velocity lambdas (the deep house hat 58/48/40, the techhouse shuffle 84/62/44) and a swing per pattern (0.50-0.58).
- `parts.RHYTHMS`: seven named rhythms (`four_on_floor`, `offbeat_8ths`, ...).
- `mutate.py`:
  - role-based fills (`FILL_SHAPES`: kick sits out, snare roll, clap push, 32nd hat ratchets)
  - density through `thin` and `thicken`, ranked and seeded
  - `humanize`: at most ±16 velocity and ±0.25 tick
- The working hit `(step, note, velocity, gate_steps, offset_ticks)` already carries a per-hit timing offset, which the sequencer plays as `t0 + offset * tick_len` (`Engine._run`).
- Swing is global: every odd 16th of every track moves by `(swing - 0.5) * 2 * sixteenth`.

**Gap:**
1. A genre is **one fixed drum layer.** There are no alternatives (groove A or B), no energy levels, and no per-role lanes to mix.
2. **Velocity shapes are lambdas inside the patterns.** They aren't named or reusable.
3. **Microtiming is only random** (humanize). No laid-back clap, no early hat.
4. **One fill per role.** No fill variants.

### 3.2 Data model: `grooves.py` (new, pure tables)

```python
@dataclass(frozen=True)
class Lane:                # one role's part, reusable across grooves
    name: str              # "hat.offbeat_shuffle"
    role: str              # a kitmap.ROLES drum role: kick, snare, rim, clap, closed hat, open hat, cymbal, perc
    grid: tuple            # 1, 2 or 4 bars of 16 cells: x hit, X accent, g ghost, . rest (parts.parse_grid_bar + g)
    velocity: object       # a curve name (VELOCITY_CURVES) or 16 ints 1-127
    micro: tuple = ()      # 16 offsets in clock ticks, -3..+3 (0 = on the grid); () = none
    gate: float = 1        # steps
    tags: frozenset = frozenset()
    about: str = ""

@dataclass(frozen=True)
class Groove:              # a drum kit's feel at five energy levels
    name: str              # "deephouse.B"
    genre: str             # a patterns.PATTERNS name, for the melodic tracks and the home key
    swing: float           # 0.50-0.62, becomes Pattern.swing
    levels: dict           # energy 1..5 -> {role: lane name}; each level lists its full set (not deltas)
    fills: dict            # role -> fill name (FILLS), default the v0.6.1 shapes
    bpm: tuple             # suggested range, for about only (never changes the tempo by itself)
    tags: frozenset
    about: str
```

- **Velocity curves** (`VELOCITY_CURVES`), named from what the patterns already do:
  - `flat`
  - `beats` (120 on 0/4/8/12, 90 between, as `parts.ACCENT`)
  - `offbeat_lift`
  - `shuffle` (the techhouse 84/62/44)
  - `deep_hat` (the deep house 58/48/40)
  - `crescendo` (rises over the bar)
  - `ghosted`: an accent at 100-115, `g` cells at 28-40
- **Microtiming:**
  - One clock tick is 60 / (BPM × 24) s: about 20.5 ms at 122 BPM. So the useful offsets are fractions of a tick: a laid-back clap at +0.5 (about 10 ms), a pushed hat at −0.25.
  - **Positive offsets play as they do today.**
  - **Negative offsets** can't be played in place: a step's notes are queued at that step's tick, so a negative offset would sound late, at the tick. The lane compiler therefore moves a negative offset to the previous step with offset `6 + micro`, inside the same bar. On step 0 it is clamped to 0 and reported (`pushed_downbeat_clamped`).
  - This is data work in the tool thread. The sequencer doesn't change.
- **Per-lane swing:** hats swinging more than the kick is expressed as `micro` on odd steps, on top of the global swing. No per-track swing goes into the sequencer.
- **Fills** (`FILLS`):
  - the five existing shapes from `mutate.fill`, named `kick.sit_out`, `snare.roll`, `clap.push`, `hat.ratchet` and `open.clear` (perc reuses `clap.push` and cymbal `open.clear`, as `FILL_SHAPES` does today)
  - new: `snare.flam_roll`, `kick.double` (14 and 15), `hat.open_choke`, `perc.tom_run`
  - `perc.tom_run` uses notes 60, 57 and 53 on one perc track, inside the v0.5 floor. It is pitched, so it only plays on a perc track whose line is note 60.
- **Deep house first.** Starting points by ear:
  - **`deephouse.A`** is today's deep house drum layer as levels 3-4. It is the reference, so `groove: "A", energy: 3` sounds like today's pattern.
  - **`deephouse.B`:**
    - level 1: `kick.four_floor` and `hat.offbeat_open`
    - level 2: adds `hat.shuffle_16` (`deep_hat`, `micro` +0.25 on odd steps)
    - level 3: adds `clap.2_4_ghosted` (`micro` +0.5 on the clap) and `rim.bossa`
    - level 4: adds `perc.shaker_16`, and raises the hat accents
    - level 5: adds a doubled clap and `open.every_and`
    - `cymbal` lanes play only on a labelled cymbal track.
  - Then `techhouse.A`/`B`, `techno.A`/`B`, `soul.A` and `breaks.A`.

### 3.3 Tools

- **`whiplash_play_pattern`** gains:
  - `groove: "B"` or `"deephouse.B"`. A bare letter takes the genre's groove.
  - `energy: 1-5` (default 3).
  - With a beat playing, either one queues a switch on the next bar line, as genre does now.
  - The result adds:
    - `groove: {name, energy, lanes: {role: lane}, swing}`
    - `unplaced`: roles with no track, see §3.4
- **`whiplash_mutate(action: "energy", amount: 1-5 | "up" | "down")`:** the same groove at another level, from the next bar. This could instead be part of `whiplash_perform` (layer 4): open question Q-G3.
- **`whiplash_write_part`** gains `groove: "hat.offbeat_shuffle"` as a sixth placement, exclusive with `rhythm`, `grid`, `steps`, `hits` and `lock_to`.
  - It brings its own velocities and microtiming, and notes default to 60.
  - The result adds `{lane, micro, velocity_curve}`.
- **`whiplash_mutate(action: "fill", fill: "snare.flam_roll")`** gets named fills. Arrangement sections accept a name for `fill` too.
- **Failure hints:**
  - unknown groove or lane: closest matches, and `whiplash_list_library(kind: "groove", genre: ...)`
  - `energy` without a groove: "energy needs a groove; try groove: 'A'"
  - a lane's role on a melodic track: refused as fills are ("lane clap.2_4_ghosted is a clap part; track 6 is labelled bass")

### 3.4 Scheduler and tracks

- **A groove plus an energy level compiles, in the tool thread, into an ordinary `patterns.Pattern`.** It keeps the genre's melodic tracks and takes the groove's drum lanes, with `swing` from the groove, `key` from `HOME_KEYS` and `name` like `deephouse+B@3`. Everything downstream is unchanged:
  - `patterns.register`, `harmony.in_key`, `kitmap.route` (lanes go to labelled tracks by role, with the same preferences and `CLOSE` fallbacks)
  - density, fills, the progression, `whiplash_arrange` group words
- **Default tracks for lane roles** follow the existing layout: kick 1, snare or rim 2, clap 3, closed hat 4, open hat 5, perc 8 (where the genre puts it).
  - A lane role with no default and no labelled track, such as a shaker on a kit without a perc label, isn't played. It is reported under `unplaced`, like kitmap's `dropped`, never silently.
  - Tracks 9-16 get lanes only when labelled, as now.
- **Written parts win their track,** as now (`kitmap.plan` "replaced").
- **Energy change:** the new pattern is prepared in the tool thread and swapped in at the bar line through the `_reroute` path (`Engine._reroute`, which keeps swing, humanize and density), not the switch path, which resets mutations.
  - Mutes, ramps, written parts, the progression and the arrangement carry over.
  - The per-bar cost is the same as a relabel today.
- **Microtiming** uses the existing `offset_ticks`. `humanize` adds on top, as now.

### 3.5 Test plan

- **Library integrity:**
  - every lane's grid parses (16 cells, 1/2/4 bars), velocities are 1-127 and micro is −3..+3
  - every groove level names known lanes
  - every role is a `kitmap.ROLES` drum role
  - levels 1-5 exist and get busier: hits per bar don't decrease
- **Equivalence:** `deephouse.A` at energy 3 yields the same drum events as today's `deephouse` (`bar_events` on bars 0-3). This guards the demo.
- **Micro:** `clap.2_4_ghosted` plays with offset +0.5 tick, and a −0.25 offset on step 6 lands on step 5 at offset 5.75. Check note-on times with `pretend_playing` and a recording port.
- **Routing:** with `label_tracks({"9": "kick"})` the kick lane plays on 9 only, and a shaker lane with no perc track shows in `unplaced`.
- **Energy change:** lands on the next bar line, keeps humanize, density and mutes, and sends no extra Stop or Start.
- **Fills:** each named fill on its role, and refused on a melodic line, as `mutate.fill` is.
- **Rehearsal:** the default `scripts/rehearse_demo.py` run is unchanged (no groove argument) and prints `RESULT: PASS`.

### 3.6 Open questions for Phil (groove)

- **Q-G1.** Groove names: letters (A, B) per genre, or descriptive names (`deephouse.shuffle`)? Letters match the brief's "groove B", and names describe themselves.
- **Q-G2.** Is a +0.5 tick laid-back clap audible and pleasant on the unit (**HW**)? Is −0.25 on hats worth the compile trick?
- **Q-G3.** Is energy a `mutate` action, a `perform` move, or both?
- **Q-G4.** Ghost notes at velocity 28-40: does the kit's VELOCITY TO VOL make them audible (**HW**, reference Q6)?

---

## 4. Layer 3: Phrase generators

### 4.1 What exists, and the gap

**Exists:**
- `parts.build` writes a line from a rhythm and notes (names, MIDI numbers, or scale degrees with a key), into the working hit shape.
- `harmony.apply` modes reshape any line per bar against the chord: `root` (a whole bass line on the chord root), `snap` and `chords`.
- `jam.reply` (v0.8.0) turns a phrase into an echo, answer or harmony, in key and register (`jam.fit_register`: median 53-72).

**Gap:** nothing writes a musical line from the chords. A bass in `root` mode plays one pitch per bar on the pattern's rhythm, so the line is the root note. A model asked for "a walking bass" or "an arp" has to compute every note against every chord, and can't follow a progression it didn't write.

### 4.2 Data model: `phrases.py` (new, pure) and `harmony.Rel`

- **Chord-relative notes.** A phrase's hits carry a `harmony.Rel` instead of a plain note number:
  - It is a small `int` subclass with `.tone` (`R`, `3`, `5`, `7`, `9`, `oct`, `step+1`, `step-1`, `approach`) and `.octave` (−1..+2).
  - Its integer value is the note it plays against the key's tonic chord. So anything that doesn't know about it still sees a sensible note in 16-84: `mutate.fill`'s melodic check, `mutate.thicken`'s ghost copy (which keeps the object), the view, status.
  - The engine's transpose (`clamp_note(note + shift)`) runs after `apply()`, so it is never applied to a `Rel`.
- **A new `harmony.apply` mode, `phrase`.** For each hit it resolves `Rel` against the chord playing: chord-tone index into the voiced chord, then `harmony.nearest(pc, anchor)` around the phrase's register anchor.
  - A missing tone (a 7th on a triad) falls to the nearest chord tone.
  - `approach` needs the next chord: one more `prog.index(bar + 1)` lookup.
  - With no progression it resolves against the key's tonic chord (a triad, or a 7th for a 7th-flavoured generator).
  - This is per-hit lookup work, like `chords` and `root`, at most 64 hits per track per bar.
- **Generators:**

```python
@dataclass(frozen=True)
class Phrase:
    name: str            # "bass.octave_pump"
    role: str            # bass | lead | stab | chord | pad (kitmap.MELODIC)
    grid: tuple          # 1, 2 or 4 bars of 16 cells (x, X, g as in lanes)
    tones: tuple         # per hit, cycled: "R", "R+12", "5", "b7", "approach", "step+1", ...
    order: tuple         # 16 step ranks: which hits go first as density falls
    register: str        # low (anchor 53-57) | mid (60-64) | high (67-72)
    length: float        # steps
    velocity: object     # curve name or ints, as lanes
    variation: str       # none | seeded (rng picks tones per bar) | motif (A A' B A'' over 4 bars)
    tags: frozenset
    about: str
```

- **The v1 set, deep house first:**
  - `bass.offbeat`: R on the "and" of each beat (steps 2/6/10/14), a ghost on 3.
  - `bass.octave_pump`: 8ths alternating R and R+12.
  - `bass.root_fifth`: R on 0 and 8, 5 on 4 and 12, with the bounce variant on offbeats.
  - `bass.walking`: quarters R, step, 3 or 5, approach.
  - `bass.rolling`: the techhouse shape: 16ths on 2/3/6/10/11/14, with R, R, 5, R, b7.
  - `arp.chord_up`, `arp.chord_updown`, `arp.chord_seeded`: chord tones on 16ths or 8ths, 1-2 octaves.
  - `stab.offbeat`: chord tone per hit on the offbeats, for chord tracks.
  - `melody.motif`: a seeded one-bar motif of chord tones on 0/4/8/12 and scale steps between. Bar 2 repeats it, bar 3 sequences it up a step, and bar 4 answers it and ends on R, borrowing `jam.reply`'s `answer` idea.
  - `pad.hold`: the existing `harmony.pad_line`, named.
- **Controls:**
  - `seed`: any int or word, through `mutate.rng(seed, "phrase", name, bar)`. It is deterministic across runs, as mutate is.
  - `density`: 0-1, keeping the top hits by `order`. 1 means every hit in the grid.
  - `register`: low, mid or high, or an anchor note. The final line goes through the v0.5 rule (median 53 or more, notes in 16-84), as `patterns.register` and `jam.fit_register` do.
  - A one-voice audio track plays an arp one note at a time, which is what an arp is.

### 4.3 Tools

- **`whiplash_write_part`** gains `phrase: "bass.octave_pump"`, with `density`, `seed` and `register`.
  - `phrase` is exclusive with the placements and with `notes`. It supplies both.
  - The result is a `parts.Part` in every respect: kit-map routing ("written parts win"), `whiplash_undo`, `whiplash_stop` clearing it, transpose, density, fills (melodic lines are left alone) and drops all work unchanged.
  - The part's track gets mode `phrase` in `Engine._prog_modes`, also when no progression plays, so it follows `set_progression` and `set_key` from then on.
  - The result adds `{phrase, follows: "progression" | "key", now: <the bar as it sounds on the current chord>, register}`.
  - **Failure hints:**
    - unknown phrase: closest matches, and `whiplash_list_library(kind: "phrase", tag: "bass")`
    - a phrase on a drum, cymbal or fx track: refused, as `set_progression` refuses
    - `phrase` together with `notes`: "phrase brings its own notes; drop notes, or use rhythm + notes"
- **Alternative:** a separate `whiplash_play_phrase` tool, which is clearer for a weak model but adds about 200 characters (Q-P1).

### 4.4 Scheduler and tracks

- **The phrase is built in the tool thread,** like any written part (`Engine._parts`, then `_rebuild`).
- **At the bar line the only new work is the `phrase` branch of `harmony.apply`:** per hit, one lookup into the voiced chord and one `nearest()`.
- **Roles:** bass phrases go to a bass-role track (labelled, else track 6), arps and melodies to a lead track, and stab or pad phrases to chord tracks (with ranks, as `chords` mode does).
- **Tracks 9-16** take phrases when named explicitly (`track: 10`). `channel_note` is passed on as now.

### 4.5 Test plan

- **Pure:**
  - `Rel` arithmetic and hashing
  - `phrase` mode resolution against every library progression in all keys: medians at 53 or more, every note in 16-84, a seeded line identical across runs
  - `approach` lands one step from the next root
  - density 0.25 keeps the four highest-ranked hits
- **Engine:**
  - `write_part(track: 6, phrase: "bass.octave_pump")` and then `set_progression(name: "deephouse.late_night")`: track 6's notes on each bar are the chord's root and octave (`bar_events`, with A, F, C and G roots in A minor at 2 bars each)
  - `set_key("Fm")` moves them
  - `whiplash_undo` brings the previous line back on the bar
  - a `thicken` ghost on a phrase keeps a `Rel` and resolves
- **Refusals:** a phrase on a kick-labelled track. Nothing changes (`status` before and after are equal).

### 4.6 Open questions for Phil (phrases)

- **Q-P1.** `phrase` on `whiplash_write_part` (proposed), or a separate `whiplash_play_phrase` tool?
- **Q-P2.** Should a phrase on the generated bass track replace the genre's bass line by default (yes, as any written part does), or layer on another track?
- **Q-P3.** `melody.motif`: is a seeded motif welcome, or should leads stay hand-written by the model plus key lock?
- **Q-P4.** Octave pump at 122 BPM on one audio track: is the R → R+12 retrigger clean, or does the AMP envelope smear it (**HW**, related to §5.2 and Q9)?

---

## 5. Layer 4: Arrangement grammar

### 5.1 What exists, and the gap

**Exists:**
- **`arrange.py` (v0.6.1-2):**
  - sections: name, bars, tracks or mute (group words), drop, fill on the last bar, chords, ramps, transition, `transition_bars`, `filter_from`, mix
  - presets `club` and `short_demo`, with the build's rising filter as `_build_ramp`
  - `resolve()` maps group words onto the roles playing at each section's first bar
  - the engine schedules sections through `_arrange_step` and `_enter_section`, with no new clock path
- **`transition.py`:** `cut`, `filter_swap`, `drop_swap` and `riser`, from existing ramps, drops and fills.
- **The roadmap's later theme:** "Macros and performance moves: build-up, breakdown and slam as one-call presets."

**Gap:**
1. A section lists its tracks and ramps by hand. **There is no section type with defaults** (what a breakdown is) **and no energy level.**
2. **Fills happen only on a section's last bar.** There's no "a fill on the last bar of every 8".
3. **Tracks can't enter mid-section** ("hats in at bar 16").
4. **No one-call intent while a beat plays** ("build to the drop in 16 bars").
5. **An arrangement either stops or loops at its end.** There's no "then keep playing".

### 5.2 Data model: `form.py` (new, pure; compiles into `arrange` sections)

- **Section types** (`SECTION_TYPES`), each a template of existing section keys plus `energy`:

| type | energy | default bars | what plays | built from |
| --- | --- | --- | --- | --- |
| `intro` | 1 | 16 | kick, hats | fill_every 8 |
| `groove` | 3 | 16 | all | fill_every 8 |
| `build` | rising 2→4 | 8 | kick, hats, perc, music | `_build_ramp` (music filter 20→127, exp), kick drop on the last bar, `snare.roll` fill, `enter: {hats: -4}` (16th hats for the last 4 bars) |
| `breakdown` | 2 | 8 | hats, perc, music | bass `filter_freq` closes to 40 over 2 bars and reopens at the next section (a `filter_swap`-style close and reopen, owner `arr`) |
| `drop` | 5 | 16 | all | fill_every 8, optional `mix` |
| `outro` | 1 | 16 | kick, hats, perc | thins out: density −0.3 on hats in the last 8 |

- **Energy** (`ENERGY`), 1-5. Each level sets:
  - the groove level (layer 2), when a groove plays
  - the groups that play, when the section gives no `tracks`
  - an optional music-filter target, **opt-in** (`energy_filter: true`), because a ramp leaves the kit's cutoff changed until it is reloaded, as the build already does
- **Form strings:** `"intro 16, groove 16, build 8, drop 16, breakdown 8, drop 16, outro 16"`, or a library name (`club_long`, `deephouse_dj`, `build_drop`). They compile to an `arrange.sections()` list. Each `type bars` item takes its type's defaults, and later keys override them.
- **New section keys,** validated in `arrange.section`:
  - `energy` (1-5, or `"rising"`)
  - `fill_every` (N bars, with the fill on the last bar of each N)
  - `enter` / `exit`: `{group: bar}`, a bar within the section; negative counts from its end
  - `fill` accepts a fill name (layer 2)
- **New arrangement option `then: "stop" | "loop" | "continue"`:**
  - `stop` is the default: today's `loop: false`.
  - `loop` is today's `loop: true`.
  - `continue` ends the arrangement like `clear: true` (unmute what it muted) and keeps the beat playing.
- **Moves** (`MOVES`) for `whiplash_perform`. Each compiles to a short arrangement with `then: "continue"`, or to existing calls:

| move | compiles to |
| --- | --- |
| `build` (bars N, default 8) | a `build` section of N bars, then the drop below |
| `drop` | all in on the next bar (energy 5, `mix` recall if a "drop mix" is saved), crash on a labelled cymbal |
| `breakdown` (N) | a `breakdown` section of N bars |
| `lift` / `cool` | energy +1 / −1 from the next bar (layer 2 swap) |
| `slam` | one bar of everything dropped except fx, then all in with a fill |
| `darker` / `brighter` / `tension` / `release` | layer 1 intent, plus (darker only) music filter −20 over 2 bars when Whiplash knows the cutoff |
| `fill` | a named fill on the next bar (`whiplash_mutate fill`) |

- **"Build to drop in 16 bars"** = `whiplash_perform(move: "build", bars: 16)`. It compiles to:
  - build: 16 bars, music filter 20→127 exp over 16, `enter: {hats: -4}`, a kick drop on bar 16, a `snare.roll` fill on bar 16
  - then a drop of 16 bars at energy 5 with `fill_every: 8`
  - `then: "continue"`

### 5.3 Tools

- **`whiplash_arrange`** gains:
  - `form`, a string or a library name, exclusive with `sections` and `preset`
  - `then`
  - the section keys `energy`, `fill_every`, `enter` and `exit`

  The `club` and `short_demo` presets are unchanged.
  - **Failure hints:**
    - unknown section type: lists the types
    - `enter` past the section's end: "bar 20 is outside build (8 bars)"
    - a form over `TOTAL_BARS_MAX` (512): says the total
- **`whiplash_perform(move, bars?, fill?)`** (new):
  - Result: `{move, lands_at_bar, sections: [...as whiplash_arrange], then, replaced_arrangement?}`.
  - With an arrangement already running, the move replaces it from the next bar (`replaced_arrangement` names it). `whiplash_undo` brings it back, because arrangements are already undoable (v0.8.0).
  - Description, about 200 characters: "One-call performance move from the next bar: build (to a drop in bars), drop, breakdown, lift, cool, slam, darker, brighter, tension, release, fill. The plugin schedules mutes, ramps, fills and chords."
  - **Failure hints:**
    - nothing playing: "start a beat first"
    - `lift` at energy 5: "already at energy 5; try drop or slam"
    - `darker` filter with no known cutoff: does the harmony part, and says so, rather than refusing

### 5.4 Scheduler and tracks

- **Forms, types and moves compile in the tool thread** into the `arrange.Section` tuple that `_arrange_step` and `_enter_section` already run. Ramps, fills, drops, mutes, mixes and progressions are all scheduled as now (owner `arr`).
- **New per-bar work** in `_arrange_step`, for the running section only:
  - one modulo for `fill_every`
  - one dict lookup for `enter` / `exit` (unmute or mute a resolved group at that bar)
  - `then: "continue"` runs the existing clear path instead of returning `None` (stop)
- **Group words resolve from roles at each section's first bar,** as now (`arrange.resolve`), so forms survive relabels and pattern switches.

### 5.5 Test plan

- **Pure:**
  - every form in the library compiles to valid sections (`arrange.sections` accepts them)
  - `"intro 16, build 8, drop 16"` gives the expected `tracks`, `ramps`, `drop` and `fill` per section
  - `perform("build", 16)` produces the sections above
- **Engine (`pretend_playing` at 4x):**
  - `fill_every: 8` fills bars 8 and 16 of a 16-bar section and no others
  - `enter: {hats: -4}` unmutes the hats exactly at bar 13 of 16
  - `then: "continue"` keeps the beat running after the last section, with every arrangement mute lifted and no MIDI Stop sent
  - `whiplash_perform` while an arrangement runs, then `whiplash_undo`: the old arrangement resumes in the right section
- **Rehearsal:** `--v061` still passes, and the presets play bar for bar as before.

### 5.6 Open questions for Phil (arrangement)

- **Q-A1.** Should energy move the music filter by default (opt-in proposed, because the cutoff stays changed until the kit reloads)?
- **Q-A2.** `perform` while an arrangement runs: should it replace the arrangement (proposed, undoable), queue after the current section, or be refused?
- **Q-A3.** Breakdown default: close the bass filter (proposed), or drop the bass?
- **Q-A4.** Is `then: "continue"` the right default for moves (proposed), and should forms default to `stop` as arrangements do today?

---

## 6. Layer 5: Taste guardrails

### 6.1 What exists, and the gap

**Exists:**
- `whiplash_status`: pattern, key, chords, section, mutations, ramps, per-track state, `play_along.user_moves` (the user's last 8 moves), `undo` (the last four undoable changes).
- `whiplash_listen` (v0.7.0): loudness, bands, onsets, masking, silent tracks.
- The v0.8.0 recording (`jam.Recording`, only while play-along is on).
- `Engine.bar_log`: bar times. `Engine.bar_hits`: the current bar's events only.
- `view.ACTIONS`: recent tool calls, for the visualiser.

**Gap:**
1. **Nothing says what changed recently, or for how long nothing has.** The model has to remember its own calls.
2. **Nothing flags "too repetitive" or "too busy".** A weak model loops the same four bars for minutes, or stacks 16th hats, a rolling bass and an arp until it is mush.

### 6.2 Data model: `taste.py` (new, pure) and two bounded engine logs

- **`Engine.bar_digest`:** a `deque(maxlen=64)`. At each bar line the sequencer appends one tuple: `(bar, at, events, section name, chord symbol, frozenset(muted))`.
  - `events` is the dict `_bar_boundary` just built. It is kept by reference, not copied.
  - This is one append per bar with no computation, like `bar_log` today. Fingerprints and metrics are computed in the tool thread only.
- **`Engine.changes`:** a `deque(maxlen=64)` of `(lands_at_bar, tool, summary)`, appended by tool handlers under `_lock` when they schedule a change. Examples: `"set_progression deephouse.late_night"`, `"energy 3 -> 4"`, `"write_part 6 bass.octave_pump"`.
  - User moves (v0.8.0 `user_moves`) are merged in at read time, mapped to bars through `bar_log`.
- **Metrics** (`taste.metrics(bars, changes, moves, last_listen, genre)`, pure), over a window of 8 bars by default:
  - **Repetition:**
    - `unchanged_for_bars`: bars since anything in `changes` or `user_moves` landed
    - `cycles_repeated`: identical 4-bar fingerprints in a row, where a fingerprint is per track, per bar, over (step, note, velocity in 8-step buckets)
    - `chord_static_bars`
    - `distinct_bars`
  - **Busyness:**
    - `notes_per_bar` (and per track)
    - `max_voices_per_step`
    - `active_tracks`
    - `low_collisions`: bass hits on kick steps per bar
    - `hat_density`: hat hits per 16 steps
    - `register_crowding`: two busy melodic tracks with medians within 2 semitones
  - **Feel:**
    - `velocity_spread` per track (standard deviation; near 0 means machine-flat)
    - `swing` and `humanize` now
  - **Heard** (when a `whiplash_listen` result is under 32 bars old): `masking`, `clipping`, `bands.low`. Never captured anew.
- **Thresholds per genre** (`taste.THRESHOLDS`, data), starting values by ear:
  - deep house: `cycles_repeated` 4 (16 bars), `notes_per_bar` 72, `max_voices_per_step` 6
  - techno: 8 cycles, since hypnotic is the point, and 64 notes
  - a default for the rest
- **Hints:** each fired threshold gives one sentence plus named next steps from the libraries, never a rewrite:
  - "16 bars unchanged: try `whiplash_perform(move: 'lift')`, a fill, or `set_progression(intent: 'tension')`."
  - "Busy: 14 hats per bar, a rolling bass and an arp on 16ths: thin the hats (`whiplash_mutate density -0.3`) or energy −1."
  - "Bass hits 4 kick steps per bar and the last listen heard masking: try `bass.offbeat`."

### 6.3 Tools

- **`whiplash_review(bars?: 4-32, default 8)`** (new), small on purpose for weaker models:
  - Result: `{window: [from, to], changed: [{bar, what, by: "you" | "user"}], unchanged_for_bars, section, energy, chords, metrics: {...compact}, hints: [...], listen: {...} | null}`.
  - Description, about 150 characters: "What changed in the last bars and whether it is too repetitive or too busy, with named next moves. Feedback only: changes nothing."
- **`whiplash_status`** gains `taste: {unchanged_for_bars, hint}`, one line only.
- Musical tool results gain `taste_hint` **only when a threshold newly fires** since the last result that carried one. That keeps results short.
- **Failure hints:**
  - nothing playing: a review of the last run, if one was recorded since the last stop, else "nothing has played since the last stop"
  - fewer bars played than asked: the window shrinks, and the result says so

### 6.4 Scheduler and tracks

- **The only sequencer change is one append per bar** (`bar_digest`), the same order of cost as `bar_log.append`. Everything else runs in the tool thread on copies taken under `_lock`.
- **Nothing in this layer sends MIDI or changes the playing beat.** Hints are for the model.

### 6.5 Test plan

- **Pure:** fingerprints are stable, and a density change or a chord change resets `cycles_repeated`. Thresholds fire at the boundary values. Hints only name moves and phrases that exist in the libraries (checked against `library.resolve`).
- **Engine:**
  - `pretend_playing` for 20 bars with no calls: `whiplash_review` reports `unchanged_for_bars` ≥ 16 and the repetition hint (deep house)
  - after `whiplash_perform(move: "lift")` the next review lists it under `changed` at its bar
  - a `FakeInput` knob move (v0.8.0) shows as `by: "user"`
- **No side effects:** `whiplash_review` sends nothing (the fake port's message count doesn't change), takes `_lock` only briefly, and never opens the input or the audio device.

### 6.6 Open questions for Phil (taste)

- **Q-T1.** Feedback only (proposed), or may a later version act on a hint by itself (an "autopilot" with a hard opt-in)? This spec never rewrites the playing pattern.
- **Q-T2.** Are 16 unchanged bars "repetitive" for deep house, and 32 for techno?
- **Q-T3.** Should `taste_hint` ride on tool results (proposed, only when new), or appear only in `whiplash_review` and `whiplash_status`?
- **Q-T4.** Should the review count the user's knob moves as change? Proposed yes: the user is performing, so don't nag.

---

## 7. Phil's hardware checks (for the build PRs, not results)

| # | Prompt or action | Listen or look for | Layer |
| --- | --- | --- | --- |
| HW O-1 | "Deep house, groove B, energy 3." | Hats shuffle, the clap sits slightly behind the beat, and ghost hits are audible (or not, under VELOCITY TO VOL). Note which. | 2 |
| HW O-2 | "Energy 5", then "energy 1". | Each lands on the one, with no stuck notes and no Stop or Start. | 2 |
| HW O-3 | "Play the late-night progression with shell voicings on tracks 7 and 8." | It sounds like Am9, Fmaj7, ... across the two tracks (Q12, Q13). | 1 |
| HW O-4 | "Octave-pump bass on track 6." Then "go to F minor." | Clean R and R+12 retriggers near native pitch, and the bass follows the chords and the key on the bar. | 3, 1 |
| HW O-5 | "Build to the drop in 16 bars." | The filter rises over 16 bars, the hats come in for the last 4, the kick sits out bar 16 with a snare roll, everything lands on the one, and the beat keeps going. | 4 |
| HW O-6 | "Darker." | A minor turns phrygian (B♭ appears), and the music filter closes a little where Whiplash knows the cutoff. | 1, 4 |
| HW O-7 | Let it run 32 bars, then "how's it sounding?" | Hermes quotes `whiplash_review` (unchanged bars, a named next move) and changes nothing by itself. | 5 |
| HW O-8 | A −0.25-tick hat push (layer 2 compile trick) at 122 BPM. | Is it audibly earlier, or is it inside USB jitter (clock-jitter.md)? | 2 |

## 8. Phased build order

The plugin versions are a proposal (Q-S2). The roadmap's v0.9 is the multi-device studio. Phases O1-O5 are cut from `main` in order, one PR each, with merge commits only, and Phil merges.

| Phase | Contents | Size | Depends on |
| --- | --- | --- | --- |
| **O1: v1 slice, deep house end to end** | `library.py` + `whiplash_list_library`; layer 1: 9th shapes, `shell`, six deep house progressions, `set_progression(name)`, key lock with `out_of_key`; layer 2: `grooves.py` with `deephouse.A`/`B`, five energy levels, named curves and fills, `play_pattern(groove, energy)`, `write_part(groove)`, `mutate energy`, microtiming including the negative-offset compile; layer 3: `harmony.Rel` + mode `phrase`, `bass.offbeat`, `bass.octave_pump`, `bass.root_fifth`, `arp.chord_up` via `write_part(phrase)`; layer 5: `bar_digest`, `changes`, `whiplash_review` with the repetition and busy hints | L (3-4 days) | v0.6 harmony, v0.5.1 parts, v0.8.0 undo |
| O2: harmony intents and keys | `whiplash_set_key`, intents (`darker`, `brighter`, `tension`, `release`), `pedal` mode, `follow: true` on written parts, progression libraries for the other four genres | M | O1 |
| O3: grooves and phrases for every genre | grooves `techhouse`, `techno`, `soul`, `breaks`; phrases `bass.walking`, `bass.rolling`, the arps, `stab.offbeat`, `melody.motif`, `pad.hold` | M | O1 |
| O4: arrangement grammar | `form.py`: section types, energy per section, `fill_every`, `enter`/`exit`, `then`, forms library, `whiplash_perform` and its moves | M-L | O1 (energy), O2 (intent moves) |
| O5: taste, complete | genre thresholds, `taste_hint` on results, listen integration, user moves in the review, `status.taste` | S-M | O1, O4 (energy and section in reviews) |

**Why this v1 slice.** It removes the three places where a weak model improvises today:
- the drum feel: groove and energy
- the chords: a named progression
- the bass: a phrase that follows the chords

It also gives the model one feedback call. That is enough for the demo sentence on deep house alone. It adds two tools (`list_library`, `review`) and extends three, so its budget step is small: tools about 4,400, params about 10,000.

**Each phase** keeps existing calls bit-identical (equivalence tests, as `deephouse.A` in §3.5), updates the skill, README, CHANGELOG, roadmap and budget pins, and lists its HW checks.

## 9. Open questions for Phil (all)

**Scope and shape:**
- **Q-S1.** Four new tools (`list_library`, `set_key`, `perform`, `review`) and budget caps of 4,800 / 10,800 / 26,000. Or fold `set_key` into `set_progression` and `list_library` into `list_params` to save about 250 characters?
- **Q-S2.** Version numbers: does the ontology become v0.9 (moving multi-device to v0.10), or v0.8.x?
- **Q-S3.** Python tables in-repo (proposed), or should a later phase also read a user library (JSON) from `~/.hermes/whiplash/`? That would be a file read outside the plugin.

**Harmony:**
- **Q-H1.** Are the six deep house progressions right by ear, and which are missing?
- **Q-H2.** Key lock on by default once a key is set?
- **Q-H3.** Should `darker` do both a mode shift and a filter close by default?
- **Q-H4.** `shell` as the default voicing for 9th chords on audio tracks?

**Groove:**
- **Q-G1.** Groove names: letters or descriptive names?
- **Q-G2.** +0.5-tick clap and −0.25-tick hat: audible and worth it (**HW**)?
- **Q-G3.** Is energy a `mutate` action, a `perform` move, or both?
- **Q-G4.** Ghost velocity 28-40 vs VELOCITY TO VOL (**HW**, Q6)?

**Phrases:**
- **Q-P1.** `phrase` on `write_part`, or a separate tool?
- **Q-P2.** Does a phrase replace the genre's bass line by default?
- **Q-P3.** A seeded `melody.motif`, or keep leads hand-written?
- **Q-P4.** Octave-pump retrigger on one audio track (**HW**)?

**Arrangement:**
- **Q-A1.** Energy moving the music filter: opt-in?
- **Q-A2.** `perform` during an arrangement: replace (undoable), queue, or refuse?
- **Q-A3.** Breakdown: close the bass filter, or drop the bass?
- **Q-A4.** `then: "continue"` as the default for moves, `stop` for forms?

**Taste:**
- **Q-T1.** Feedback only, or an opt-in autopilot later?
- **Q-T2.** 16 bars for deep house and 32 for techno as "repetitive"?
- **Q-T3.** Should `taste_hint` ride on tool results?
- **Q-T4.** Do the user's knob moves count as change?
