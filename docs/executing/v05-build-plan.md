# Whiplash v0.5 build plan

Status: **plan only, waiting for Phil's review**. Nothing here is implemented yet.

- **Branch:** `feat/v05`, cut from `main` at `aab2687` (v0.4 merged).
- **Input:** Phil's live Hermes test on the Air, Nov 11 2026, about 00:05-00:20 PT, and the queued kit-map note of Nov 10 23:51 PT.
- **Deadline:** hackathon submission Nov 11, 2 PM PT. The plan was written at about 00:25 PT.

## 0. What v0.4 proved on hardware

- **CC 19 `sample_slot` works.** Phil heard the slots switch: 5 and 7 sound alike, and slot 11 is a synth he likes. Hermes used `whiplash_select_sample` correctly once the gateway had reloaded the plugin.
- **Updating needs a gateway restart.** The `hermes` CLI attaches to the background gateway (launchd), so a plugin update needs `hermes gateway restart`; a new chat is not enough. Hermes' own plugin docs agree: the gateway "discovers plugins once for the whole process", and an auto-update leaves "a running session [keeping] the code it already imported". This goes into a README "Updating" section (item 6).

## 1. Priorities at a glance

**P0 is split in two:** P0a is small and must land for the demo; P0b is the melody tool, and goes in only if it is hardware-checked in time.

| Pri | Item | Feedback # | Size |
| --- | --- | --- | --- |
| **P0a** | 1. Native-pitch register, `transpose`, and pitch shown in results | 1 | S-M, ~2 h |
| **P0a** | 5. Richer `whiplash_status` per track, and honest "assumed roles" | 7, 8 | S, ~1 h |
| **P0a** | 6. Bundled `whiplash:digitakt` skill, plus README "Updating" | 6 | S, ~1 h |
| **P0a** | 4a. `amp_mode` named param, and guidance on note length | 4 | XS, ~0.5 h |
| **P0b** | 2/3/4b. `whiplash_write_part`: notes, rhythm presets, lock-to-kick, note lengths, back to generated | 2, 3, 4 | M-L, ~4-5 h |
| P1 | 7. Kit map from chat labels (track roles + slot labels), and patterns that follow it | 5 | M, ~3-4 h |
| P1 | 8. One call to start and configure tracks (`tracks` on `whiplash_play_pattern`) | 7 | S-M, ~2 h |
| P1 | 9. `techhouse` genre and genre aliases | 8 | S, ~1 h |
| P1 | 10. Shorter tool descriptions | 7 | S, ~1 h |
| P2 | 11. Pause and resume (MIDI Stop/Continue) | 8 | S, ~1-2 h |
| P2 | 12. `whiplash_scan_kit` (audio classification over Digitakt USB audio) | 5 | L, 1-2 days, and needs Phil's OK |
| P2 | 13. Keeping the kit map across gateway restarts | 5 | S, but needs Phil's OK on a file write |
| — | Reading sample names from the unit | 5 | **Out:** needs SysEx, which is blocked |

P0a totals about 4.5 h and P0b about 4-5 h. From 00:25 PT, that leaves enough time for Phil's review in the morning and a hardware check on the Air before 2 PM. If time runs short, ship P0a only, and move P0b to the first P1 slot.

## 2. Sources

Every Digitakt II MIDI claim below cites one of these. Anything marked **HW** needs a check on the Air.

- **[M]** *Elektron Digitakt II User Manual*, OS 1.15A ([PDF](https://www.elektron.se/wp-content/uploads/2025/07/Digitakt-2-User-Manual_ENG_OS1.15A_250708.pdf)), with page numbers. This is the same edition v0.4 verified against.
- **[G]** [midi.guide Digitakt II](https://midi.guide/d/elektron/digitakt-ii/), last updated Oct 12 2026.
- **[H]** hermes-agent source, `hermes_cli/plugins_content.py` at `60f8163`, and the Hermes docs: [plugins](https://hermes-agent.nousresearch.com/docs/user-guide/features/plugins) and [skills](https://hermes-agent.nousresearch.com/docs/user-guide/features/skills).

---

## Item 1 (P0a): generated lines repitch samples far below native

**Problem.** Phil asked for "a techno beat ... sample 9 as the dirty bass line". After several turns it "still sounds terrible like stretched out and kind of grainy and distorted. Not at all like sample 11 does when i hit it". Hermes spent about 5 turns on the amp envelope and density before trying tune +12 (CC 16 = 76), which fixed it.

**Root cause.** Every melodic part is written well below the note that plays a sample at its own pitch, so every note pitches the sample down.

What the manual says:

- **[M] 8.4 MIDI NOTES, p. 25:** "MIDI note numbers 16–84, that corresponds to notes E2–C7 (C5, MIDI note 60, being middle C) will trigger the preset of the active track in it's chromatic variations (as if played by the [TRIG] keys in KEYBOARD mode)". Notes 0-15 trigger tracks 1-16 on the auto channel.
- **[M] 8.5.1 KEYBOARD MODE, p. 25:** the playable range is C0-G10.

What the code assumes:

- `patterns.DRUM = 60` is "original pitch". v0.1-v0.4 drums sounded right on the unit, which is consistent with that.
- Tune is centred at 64 = no shift, range 4-124 = ±60 semitones ([M] B.3 p. 109, and [G] "Tune 16 [4-124] Centered").

Where the current parts sit relative to note 60 (from `patterns.py`):

| Genre | Part | Notes | Offset from 60 (semitones) |
| --- | --- | --- | --- |
| techno | bass | 41 | **−19** |
| techno | stab | 51-56 | −9 to −4 |
| breaks | bass | 41-48 | **−19 to −12** |
| breaks | pad | 53-58 | |
| soul | bass | 40-50 | **−20 to −10** |
| deephouse | bass | 52-65 | −8 to +5 (fine) |
| deephouse | chords | 57-65 | (fine) |

Phil's fix lifted the techno bass to an effective −7 semitones. A sliced or "dirty" bass sample is usually recorded at its own low pitch already, so pitching it down another octave and a half stretches it.

**HW check 1.** On a track channel with TUNE = 64:

1. Send notes 48, 60 and 72 and compare them by ear with pressing the track's [TRIG] key. 60 should match exactly. This confirms that note 60 is native pitch on per-track channels, not only on the auto channel.
2. Repeat with KB mode off. Sending notes must not change the KB octave setting.

**Proposed change.**

1. **Native register by default.** Each generated melodic part is shifted by whole octaves at load time, so that its median note sits within ±6 semitones of 60. The intervals are kept, so the musical line is unchanged; only the register moves.
   - The techno bass moves from 41 to 53 (−7). Soul and breaks bass move up an octave. Deephouse stays put.
   - It is done in `patterns.py`, as a `register()` step applied to melodic tracks, so the old note tables stay readable.
2. **`transpose` per track.**
   - On `whiplash_play_pattern`: `transpose: {"6": -12, "7": 5}`, in semitones.
   - New tool `whiplash_transpose(track, semitones | octaves)`: bar-quantized, carries across switches like mutes, and resets on stop.
   - It is applied to the note number at event-build time (`_bar_boundary`), clamped to 16-84, the [M] 8.4 chromatic range.
   - Drums (note 60 parts) are never transposed unless `transpose` names that track explicitly.
3. **Pitch shown in results.** `whiplash_play_pattern`, `whiplash_status` and `whiplash_transpose` return, per melodic track:

   ```json
   "pitch": {"6": {"low": 53, "high": 53, "semitones_from_native": [-7, -7], "transpose": 0, "tune": 64}}
   ```

   - When Whiplash has sent CC 16 for that track, the effective offset includes `(tune - 64)`.
   - Note names follow Elektron's convention (C5 = 60, [M] p. 25), labelled as such, because standard MIDI calls 60 C4. Raw numbers are always included.

**Tests.**

- No generated melodic part has a median more than 6 semitones from 60.
- Transpose shifts the notes on the wire, clamps to 16-84, lands on the bar, carries over a switch, and resets on stop.
- Drums are untouched.
- The `pitch` block is right, including a tune CC that Whiplash sent.
- The view's hit tuple `(track, note, vel, gate, offset)` keeps its shape.

**Risk.** Changing the default register changes how the deephouse demo sounds. That's unlikely, since deephouse already sits near 60, but it is part of HW check 1.

---

## Item 2/3/4b (P0b): note, melody and rhythm authoring

**Problem.**

- **Melody:** "can u play different notes for each one so its a melody". Hermes answered "Whiplash can't author a melody, use KB mode".
- **Rhythm:** "they feel more like 16ths instead of 4/4s on the bassdrum". Only `density` existed, so Hermes thinned the line and gave up.
- **Note length:** "right now it plays non-stop", "still droney", "plucks might be too short".

**Root cause.** These are missing tools, not hardware limits. Whiplash already sends notes with exact note-off timing on each track's channel, but the agent can only pick a whole generated pattern.

**Proposed tool:** `whiplash_write_part`.

```text
whiplash_write_part(
  track: 1-16,
  # pick ONE way to say where the hits go:
  rhythm: "four_on_floor" | "on_kick" | "offbeat_8ths" | "8ths" | "16ths" | "syncopated" | "half_time" | "off_16ths",
  grid: "x..x..x.x..x..x." (16 chars, one bar, or a list of up to 4 bars),
  hits: [{step: 0-15, note?, length?, velocity?, bar?}],
  lock_to: <track>              # copy that track's current hits (e.g. 1 = "lock to kick")
  # what to play on those hits:
  notes: ["C5", "D#5", 63, ...]  # cycled over the hits; names in Elektron octave numbering, or MIDI numbers
  key?, scale?                   # optional helper: notes may be scale degrees ("1 3 5 b7")
  length: steps (0.25-16, default 1) # note-off timing; 1 = a 16th
  velocity: 1-127 or "accent" pattern,
  bars: 1-4 (shorter parts repeat across the 4-bar loop),
  reset: true                    # back to the generated part
)
```

**Behaviour.**

- The part replaces that track's line in the working pattern from the next bar line, so mutes, drops, fills, density and humanize all still apply.
- It is stored as `Engine._parts[track]` and merged in `_load`, so `whiplash_mutate reset` doesn't erase it.
- **Decision for Phil:** whether written parts survive a live pattern switch and `whiplash_stop`. I recommend they carry over switches and are cleared by `reset: true` or `whiplash_stop`, the same as mutes. They are the user's composition, but stop has always meant "back to clean".
- `on_kick` and `lock_to` copy the source track's base hits when the call is made. Following the source live, as density or fills change, is a P1 follow-up.
- Tracks 9-16 are allowed, because Phil's kit may hold pads or synths there. `whiplash_mutate` currently caps tracks at 1-8, so it is raised to 16 along with this.
- The result echoes the notes as step positions with numbers and names, plus the `pitch` block from item 1.

**Length and the amp envelope (4b).** The length sets the MIDI note-off time exactly, with no 0.8 `GATE` factor for written parts. But the Digitakt only ends a sound on note-off in two cases:

- **AMP MODE = ADSR:** CC 87; [M] B.5 p. 110 "Mode 87, NRPN 1:40"; [G] "Amp: Mode 87 [0-1] 0: AHD; 1: ADSR".
- **HOLD = NOTE in AHD mode:** [M] 11.7 AMP PAGE, p. 56: "Fixed Hold time values (0–126) ... the envelope ignores Note Off events ... Setting HOLD to NOTE means the hold phase will be determined by Note On and Note Off events". [G] gives "Amp: Hold Time 80 ... 127: Note".

So the write_part result includes `length_audible: "only if the track's AMP MODE is ADSR or HOLD is NOTE"`. An opt-in `envelope: "note"` argument sends CC 80 = 127 (HOLD = NOTE) on that track. It never changes the envelope silently.

**Tests.**

- Each way of placing hits gives the expected steps.
- Notes cycle over the hits.
- Note names and degrees parse into the expected numbers.
- Note-off lands at `length` × sixteenth on the timeline.
- The part lands on the bar and survives `mutate reset`.
- `reset: true` restores the generated part.
- Density, drop, fill and mute still apply to a written part.
- `lock_to` copies the kick.
- Bad input (track, notes, grid, length) leaves the beat alone.
- `envelope: "note"` sends exactly one CC 80 = 127.
- Clock jitter is unchanged with 8 written parts.

**HW checks.**

- **HW 2.** With AHD and a fixed hold, length changes nothing. With HOLD = NOTE (CC 80 = 127), length shortens the note. With ADSR (CC 87 = 1), length plus release shapes it. This confirms that CC 80 = 127 shows as NOTE on the unit.
- **HW 3.** A melody written on track 6 using Phil's slot 9 "dirty bass", then slot 11 "synth": it should sound like playing them in KB mode.

---

## Item 4a (P0a): `amp_mode` named param

**Problem.** Hermes could only change the amp envelope, and didn't know that note length depends on the envelope mode.

**Change.**

- Add `amp_mode` (CC 87, 0 = AHD, 1 = ADSR, a discrete switch) to the amp group in `ccmap.py`. The CC numbers agree in [M] B.5 p. 110 and [G].
- Document that `amp_hold` at 127 means NOTE ([G]; [M] p. 56 says fixed values are 0-126).
- The NRPN 1:40 is kept as documentation only, as before.

**Tests:** the param map test gains `amp_mode: 87`, and the param rejects values 2 and up and can't be ramped. **HW check:** part of HW 2.

---

## Item 5 (P0a): richer per-track status and honest roles

**Problem.**

- **Latency:** each turn took 5-40 s, with many `tool_describe` and `skill_view` round trips before acting.
- **Roles:** Hermes described the "deephouse" track roles even though Phil's kit is laid out differently. In project 6, tracks 7-8 held tuned cymbals, not chords.

**Change.** `whiplash_status` gains a `tracks` block, one entry per track in use:

```json
"tracks": {"6": {"role": "bass (assumed)", "slot": 9, "tune": 76, "transpose": 0, "pitch": {...},
                 "muted": false, "part": "generated", "last_cc": {"filter_freq": 40}}}
```

- **`slot`** is the last `sample_slot` Whiplash sent. Whiplash can't read the unit, so it is `null` until then, and labelled "last sent".
- **`role`** comes from the pattern, marked "(assumed)" until the kit map (item 7) confirms it.
- **`whiplash_play_pattern`** results show the same `tracks` summary.
- **A `kit_note`** says: "track roles are the pattern's assumed layout; ask the user what each track holds, or use whiplash_label_tracks" (the latter once item 7 lands).

**Tests:** the shape of the block, "last sent" semantics, and "(assumed)" until a label is set.

---

## Item 6 (P0a): agent guidance ships with the plugin

**Problem.** Hermes auto-created a local `whiplash-digitakt` skill and keeps patching it with stale claims, for example "can't switch samples".

**Finding [H].** Hermes plugins can bundle skills.

- `ctx.register_skill(name, path, description="", frontmatter=None)` registers a read-only skill, resolvable as `"<plugin>:<name>"` via `skill_view()`. It is listed in `<available_skills>` while the plugin is enabled.
- It is "not copied into `~/.hermes/skills/`"; `path` is the SKILL.md file.
- Plugin skills are namespaced and "never collide" with local skills. So Phil's stale local `whiplash-digitakt` skill keeps showing up separately until he deletes it, which is a manual step for Phil.

**Change.**

- Add `skills/digitakt/SKILL.md`, registered in `register()` as `whiplash:digitakt`. It is guarded with `hasattr(ctx, "register_skill")`, so Hermes builds without the API still load the tools; `requires_hermes` stays `>=0.19`.
- **Skill contents:** about one screen.
  - Pitch and register: note 60 is native pitch; use `transpose` or `tune` before touching the envelope.
  - Sample select: what slots are and aren't, and asking for labels.
  - Transport overlap, empty pattern and clock only.
  - Note length versus AMP MODE and HOLD.
  - Writing parts and rhythm presets.
  - A diagnostics checklist: "sounds stretched or grainy" means check `pitch` first; "plays non-stop" means check the envelope mode; "unexpected drums" means the unit's own pattern.
  - What Whiplash can never do: SysEx, sample names, loading files.
- The tool descriptions point to it: "see skill whiplash:digitakt".
- README gains an **"Updating"** section: after `hermes plugins update` (or a `git pull` of a symlinked checkout), run **`hermes gateway restart`**. Also remove any old local `whiplash-digitakt` skill from `~/.hermes/skills/`.

**Tests:**

- `register()` calls `register_skill` with an existing SKILL.md when the ctx has the API, and is skipped cleanly when it doesn't.
- The SKILL.md frontmatter parses, with `name` and `description`.
- The skill text doesn't contain known stale claims such as "can't switch samples".

**HW / Hermes check (on the Air):**

- `hermes gateway restart`, then `/plugins` shows whiplash.
- `skills_list` shows `whiplash:digitakt`, and `skill_view("whiplash:digitakt")` works.
- Phil's Air runs Hermes v0.23.1 (from the visualiser decision). Confirm `register_skill` exists there.

---

## Item 7 (P1): kit map from chat labels

This is the queued "kit map before beats" idea, now in scope.

**Problem.** Whiplash assumes a fixed layout (1 kick, 2 rim, 3 clap, 4 closed hat, 5 open hat, 6 bass, 7-8 chords) whatever is loaded. In project 6, the "chords" were tuned cymbals.

**Identification options, as the queue note ranked them:**

1. **Audio analysis** (item 12): P2.
2. **User labels in chat:** this item.
3. **Sample names from the unit:** needs SysEx, which is **blocked** without Phil's explicit OK. It is not planned.

**Change.**

- New tool `whiplash_label_tracks(tracks: {"5": "pad", "7": "cymbal"}, slots: {"11": "synth Phil likes"})`. It holds an in-memory session kit map:
  - track → role, from a fixed vocabulary (kick, snare, rim, clap, closed hat, open hat, perc, bass, pad, stab, chord, lead, fx, other) plus free text
  - slot → label
- **Patterns follow the map.** At load, each generated role is routed to the track labelled with that role, using a role → track remap applied in `_bar_boundary`.
  - Generated parts for roles nobody has are dropped. Labelled tracks with no generated part stay silent until `whiplash_write_part`.
  - Melodic roles (bass, pad, chord, stab, lead) use the item 1 register.
  - Unpitched roles labelled "cymbal" or "fx" never get chord lines.
- **The map shows up in results:** status `tracks[].role` and `slot_label`, and the `whiplash_select_sample` result echoes the slot's label.
- **Lifetime:** the map survives stop and pattern switches. It is cleared only by `whiplash_label_tracks(reset: true)` or a gateway restart (persistence is item 13).

**Tests:**

- Routing: a kick labelled on track 9 receives the kick part.
- Unlabelled roles fall back to the default layout.
- A cymbal track gets no chord part.
- Slot labels echo back.
- The view's lane roles are correct (see the overlap section).

**HW check:** label Phil's project 6 tracks, play techno, and confirm no tuned-cymbal chords.

---

## Item 8 (P1): start and configure tracks in one call

**Problem:** turn latency. The agent starts a pattern, then makes 3-6 calls (slot, tune, transpose, mute) to fit it to the kit.

**Change:**

- `whiplash_play_pattern` accepts `tracks: {"6": {"slot": 9, "transpose": -12, "tune": 64, "mute": false}}`.
- Slot and tune CCs are sent just before the first bar (on a fresh start) or at the switch bar (when queued), so the sound change lands with the pattern.
- Everything is validated before anything is sent, as with every other tool.

**Tests:**

- Each CC goes out once, before the first note-on of its track, on a fresh start and at the switch bar when queued.
- A bad track entry rejects the whole call untouched.

---

## Item 9 (P1): `techhouse` genre and aliases

- **Problem:** "tech house" isn't a genre. `patterns.resolve` raises, and Hermes then picked something else.
- **Change:** add a `techhouse` pattern at 126 BPM (four-on-the-floor, offbeat open hat, shuffled 16th hats, rolling off-beat bass in the native register, sparse stab), plus aliases `tech house` and `tech-house`.
- **Unknown genres:** the error lists the closest matches.
- **Tests:** the pattern shape, the register rule from item 1, and the aliases.

---

## Item 10 (P1): shorter tool descriptions

- **Problem:** descriptions run to about 100 words each, and Hermes `tool_describe`s before acting.
- **Change:** cut each description to a 1-2 sentence "when to use", and move the detail into the skill (item 6).
- **Measure:** total schema characters before and after, plus round trips per turn in one Air session. The second is a soft metric (**HW**).
- **Tests:** schemas stay well formed, and a size budget test caps total description length.

---

## Item 11 (P2): pause and resume

- **Problem:** there is only stop, which resets everything.
- **Change:** `whiplash_pause` freezes the clock at a step, sends MIDI Stop, and keeps mutes, ramps and parts. `whiplash_resume` sends MIDI Continue and resumes from that step.
  - MIDI Continue is already in the send allow-list (`engine.ALLOWED_TYPES`).
  - Clock-only mode sends neither Stop nor Continue.
- **Tests:** pause leaves the state intact, resume continues at the same step, and clock-only sends no transport.
- **HW check:** [M] p. 77 documents only that TRANSPORT RECEIVE "responds to MIDI transport messages". Whether the Digitakt II resumes mid-pattern on Continue, or restarts, is not stated, so it needs checking on the unit.

---

## Item 12 (P2): `whiplash_scan_kit` (audio classification)

**Idea.** Solo-trigger each track in turn, capture the Digitakt II's USB audio, and classify each sound by:

- spectral centroid
- decay time
- pitchedness
- low-end energy

**Unit facts.**

- The Digitakt II is a class-compliant USB audio device ([M] 6.7 p. 20).
- USB audio needs **USB CONFIG = USB AUDIO/MIDI** ([M] 14.8.1 p. 83). The other modes are OVERBRIDGE and USB MIDI: "Selecting one mode disables the other two modes".
- **USB OUT** can route MAIN, or single tracks (`L:T1–16/R:T1–16`, [M] 14.6.4 p. 81). Main is enough if the other tracks are silent.

**What it needs, and why it is P2.**

- **A new audio dependency:** `sounddevice`, which needs PortAudio, and `numpy`. This is new, and the catalog disclosures would change.
- **macOS microphone permission** for the Hermes process.
- **Or** reuse the visualiser's browser audio capture, which already asks for the Digitakt's USB input, posting features back to the local view server. That couples the scan to `feat/visualiser`.
- Both routes need Phil's OK. The second is lighter on dependencies.

**Safety.** The scan sends notes only, so no SysEx and no writes. Transport must be stopped, or clock-only, so that the unit's own pattern doesn't bleed in.

**HW checks:** a clean capture per track, and how accurate the classifier is on project 6.

---

## Item 13 (P2): keeping the kit map

- **What:** save the kit map per project (Phil names the project, for example "project 6"), so it survives `hermes gateway restart`.
- **Needs Phil's OK:** this is the first file Whiplash would write, under `~/.hermes/whiplash/kitmap.json`. The catalog disclosure currently says "no file reads or writes outside the plugin directory".

---

## Not planned

- **Sample names from the unit:** SysEx, blocked.
- **Writing to Digitakt project slots 1-3, or any project:** not planned.
- **Sample bank select (CC 24):** stays blocked.
- **The sample NRPNs (1:3, 1:8, 1:9):** stay blocked.
- **Program change:** stays blocked.

## Overlap with `feat/visualiser`

Read-only check of `origin/feat/visualiser` at `1d49d8c`, which is based on v0.3 (`11eb6dd`) and not yet merged with v0.4.

| File | Visualiser changes | v0.5 changes | Risk |
| --- | --- | --- | --- |
| `engine.py` | `position`, `bar_fills`, `bar_hits` published from `_bar_boundary`/`_run`; `view_state()` reads `_work`, `pattern`, `_queued`, ramps, `_cc_values` | `_bar_boundary` (transpose, role remap, `_parts`), `__init__` fields, `status()` | **High.** Same functions. v0.5 must keep the hit tuple `(track, note, vel, gate, offset)` and the `_work` shape `{track: [bar0..bar3 hits]}`, and should add `_parts`, `_transpose` and the kit map to `view_state()` after merge |
| `view.py` (visualiser only) | Lane role from `pattern.roles`; `melodic` = notes other than `patterns.DRUM`; lanes from `_work` | Roles become kit-map driven (item 7); written parts (item 2) | **Medium.** After both merge, `view.py` should take roles from a new `Engine.track_roles()` |
| `tools.py` | Wrapper calls `view.record_action`; `open_view`/`close_view` in `HANDLERS` | New tools in `HANDLERS`; play_pattern result fields | Medium: textual conflicts in `HANDLERS` and the wrapper |
| `schemas.py`, `plugin.yaml` `provides_tools` | `whiplash_open_view`/`close_view`; `provides_hooks` | `whiplash_transpose`, `write_part`, `label_tracks` | Medium: list order; the sync test catches mistakes |
| `__init__.py` `register()` | `chat.register_hooks(ctx)` | `ctx.register_skill(...)` | Low: adjacent lines |
| README, CHANGELOG, `docs/catalog-*`, `tests/test_whiplash.py` (tool count) | Yes | Yes | Low, but certain conflicts |

**Merge order I recommend:**

1. Merge `main` (v0.4) into `feat/visualiser`, with a merge commit, then merge the visualiser.
2. Then merge `main` into `feat/v05` before its PR leaves draft.
3. If the demo needs v0.5 P0a first, the reverse also works. The visualiser agent then merges main.

Either way, merge commits only, no rebases of pushed branches. Every new engine state that the view should show goes through `view_state()` in one follow-up commit.

## Summary of HW checks (on Phil's Air only)

| # | Check | Item |
| --- | --- | --- |
| HW 1 | Note 60 = native pitch on a track channel at TUNE 64; 48 and 72 are an octave down and up | 1 |
| HW 2 | Note length audible only with HOLD = NOTE (CC 80 = 127) or ADSR (CC 87 = 1) | 2, 4 |
| HW 3 | Written melody on slot 9 and slot 11 sounds like KB mode | 2 |
| HW 4 | `whiplash:digitakt` skill listed and viewable on Hermes v0.23.1 after `hermes gateway restart` | 6 |
| HW 5 | Kit labels route techno onto project 6 without cymbal chords | 7 |
| HW 6 | Continue resumes mid-pattern (P2) | 11 |
| HW 7 | USB audio capture per track (P2) | 12 |

Constraints throughout:

- No SysEx and no project writes.
- Never touch Digitakt slots 1-3.
- Every change stays bar-quantized and clock-safe.
- The sequencer thread never takes `_transport` and never enumerates ports.
- The v0.4 blocks stay: CC 24, sample NRPNs, raw CC 19, MIDI bank select, program change.

## Decisions for Phil

1. **P0 scope:** P0a only, or P0a plus P0b (`write_part`) before 2 PM?
2. **Written parts:** carry over pattern switches and reset on `whiplash_stop` (my recommendation), or survive stop too?
3. **Default register shift:** OK for it to change the generated techno, soul and breaks basslines, so they sound an octave or so higher than before?
4. **Kit scan route** (P2): a Python audio dependency (`sounddevice`, `numpy`), or the visualiser's browser capture?
5. **Kit-map persistence** (P2): OK to write `~/.hermes/whiplash/kitmap.json`?
