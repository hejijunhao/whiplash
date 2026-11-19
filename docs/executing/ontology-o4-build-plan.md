# Whiplash ontology O4 build plan (v0.9.3)

Status:
- **Plan for O4**, the fifth phase of [ontology-v1-spec.md](ontology-v1-spec.md) §9: the arrangement grammar. Branch `feat/ontology-o4`, cut from `main` at `08e67cc` (O3 merged, PR #29).
- O4 ships as **v0.9.3**.
- Nothing here has been tested on a real Digitakt II. Every **HW** item in §6 is a check for Phil's Air, not a result.

Inputs:
- **Spec:** [ontology-v1-spec.md](ontology-v1-spec.md). This plan's scope is §9's O4 row. The tables are §6.2 (section types, breakdown styles, energy, forms, moves), §6.3 (tools), §6.4 (scheduler) and §6.5 (tests), plus §2.1 (each genre's `breakdown` and `form`), §8 (HW O-6, O-7) and §10 (Q-A1 to Q-A4).
- **Earlier phases:** [ontology-o1a-build-plan.md](ontology-o1a-build-plan.md) (grooves, energy, named fills), [ontology-o3-build-plan.md](ontology-o3-build-plan.md) (the records name their `breakdown` and `form`, which O4 reads).
- **Existing arrangement:** `arrange.py` (v0.6.1 sections, presets), `transition.py` (v0.6.2), `engine._arrange_step` / `_enter_section`, v0.8.0 arrangement undo.
- **Research:** [genre-conventions.md](../research/genre-conventions.md) §1-8 (arrangement rows) and the shared norms (DJs count in 8, 16 and 32).

**Goal of O4 (the demo sentence):** "Build to the drop in 16 bars" is one call, `whiplash_arrange(move: "build", bars: 16)`: the hats come in for the last 4 bars, the kick sits out bar 16 under a snare roll, the drop lands on the one at energy 5, and the beat keeps playing. "Play it as a tech house DJ track" is `whiplash_arrange(form: "techhouse_dj")`, with each genre's own breakdown.

**Constraints** (spec §0, unchanged):
- No SysEx, program change, project, pattern, kit or +Drive writes. Slots 1-3 are never touched. `BLOCKED_CCS` / `BLOCKED_NRPNS` stay blocked. O4 sends no new kind of message: the only CC is `filter_freq` (CC 74), already used by the v0.6.1 build and the v0.6.2 transitions.
- Clock-safe. Forms, types and moves compile in the tool thread into the `arrange.Section` tuple the engine already runs; every groove level a section needs is compiled in the tool thread before anything changes. The bar line gains only lookups (below).
- **Drums are never pitch-corrected.** Nothing in O4 changes a note's pitch.
- **Demo-safe:** `sections`, `preset: "club"`, `preset: "short_demo"` and `loop` play bar for bar as before (pinned); the default `scripts/rehearse_demo.py` run stays `RESULT: PASS`.

## 1. Scope

| # | Item | Spec | Size |
| --- | --- | --- | --- |
| 1 | `form.py` (new, pure): section types (`intro`, `groove`, `build`, `breakdown`, `drop`, `outro`) with their defaults, `ENERGY` (groups per level, the opt-in music-filter targets), breakdown styles, form strings, the eight forms, moves, and the compile into `arrange` section dicts | §6.2 | M |
| 2 | New section keys in `arrange.section`: `energy` (1-5 or `rising`), `fill_every`, `enter` / `exit`, a fill name for `fill`, and `type` (a section type's defaults, its own keys win) | §6.2 | S |
| 3 | `then: "stop" | "loop" | "continue"` (forms default `stop`, moves `continue`; `loop` stays as `then: "loop"`) | §6.2 | S |
| 4 | Engine: energy per section through the `_reroute` path, `fill_every`, `enter`/`exit`, breakdown styles, `continue`, the outro thinning, a crash on a labelled cymbal for the drop | §6.4 | M |
| 5 | `whiplash_arrange(form)`, `whiplash_arrange(move, bars)`, `then`; moves replace a running arrangement from the next bar and are undoable | §6.3 | S |
| 6 | `whiplash_list_library(kind: "form" | "move")` lists them (they were "arrive in O4" until now) | §1.3 | S |
| 7 | Skill, README, CHANGELOG, roadmap, budget pins, hardware checklist and reference §15.1 / §15.3 | §1.6, §9 | S |

**Not in O4:** listen data in reviews and threshold tuning (O5); slash chords (§11).

## 2. Engine shape

- **Compile in the tool thread.** `form.compile(...)` turns a form string, a library form or a move into a list of ordinary section dicts, which `arrange.sections()` validates as before. `Engine.arrange` resolves each section (`_arrange_section`) and, when any section names an energy, compiles every groove level it needs with `grooves.compile` before taking the lock, exactly as `set_energy` does.
- **Per-bar work** in `_arrange_step`, for the running section only:
  - one dict lookup into the section's bar events (`enter`, `exit`, a `rising` energy step, the outro thinning), built at the section's first bar
  - one modulo for `fill_every`
  - `then: "continue"` runs the clear path (unmute what the arrangement muted, reopen closed cutoffs) instead of stopping
- **Energy per section** swaps in the precompiled level and calls `_reroute()` at the bar line: the same path and cost as `mutate energy` and a relabel today (keeps swing, humanize, density, mutes, written parts, the progression). It applies only while the groove it was compiled for still plays; after a switch to another genre the section skips it and status lists it under `skipped_ramps`' sibling `skipped`.
- **`continue` and energy.** The beat goes back to the energy it had before the arrangement started (precompiled too), so a `breakdown` move ends back in the groove instead of stuck at energy 2. A build move's drop plays its 16 bars at energy 5, then the groove returns to where it was.
- **Breakdown styles** resolve at the section's first bar from the roles playing, like group words:
  - `kick_bass_out`: kick and bass muted.
  - `kick_drop`: kick muted, bass stays.
  - `filter_low_end` / `filter_bass`: the bass track's `filter_freq` closes to 40 over 2 bars from the value Whiplash last sent (else the unit's default, 127, reference §5), and reopens on the next section's one through the existing `_restore` / `_reopen` path that `filter_swap` uses. The result and status say when 127 was assumed.
  - `reduce_drums`: energy 1 when a groove with levels plays; otherwise snare, rim, clap and perc are muted.
  - `subtract_one`: the busiest non-kick drum track (most hits in the bar) is muted for the section.
- **Fills.** `fill_every: N` plays the section's fill (a name, the named tracks, or the drums' own fills) on the last bar of every N. A named fill uses `schedule_fill`'s rules (its roles, `perc.tom_run` falls back to `snare.roll`).
- **The drop's crash** is a new named fill `cymbal.crash` (a long hit on step 1 on a labelled cymbal track). It plays even when the cymbal track has no line of its own; without a cymbal label it is skipped and the result says so.

## 3. Design notes and decisions

Researchable questions decided here from the spec and the research brief; the PR lists them.

1. **Energy → groups** (when a section gives no `tracks` and its type gives none): 1 kick and hats; 2 kick, hats, perc and bass; 3-5 everything. A groove with levels also moves to that level.
2. **`rising` energy** (the build, 2→4) steps 2 at the first bar, 3 at a third of the way, 4 at two thirds (an 8-bar build: bars 1, 3 and 6; 16 bars: 1, 6 and 11).
3. **Energy filter** (Q-A1, opt-in, on by default only in `progressive_journey` and `melodic_journey`, and in moves for those two genres): the music group's `filter_freq` moves to a per-level target (1: 48, 2: 72, 3: 100, 4: 116, 5: 127, **by ear**) over the section's first 4 bars, from the previous section's target (the first section from 127, the unit's default); a build uses the v0.6.1 build ramp, 20→127 exp, over the whole section. `energy_filter: true|false` overrides it on a form call.
4. **Enter and exit.** `enter: {hats: -4}` mutes that group when the section starts and unmutes it at the 4th bar from the end (bar 13 of 16); a positive bar counts from the section's start (1 = its first bar). `exit` mutes it from that bar. A group in `enter` plays from then on even if `tracks` didn't list it.
5. **The outro's thinning** ("density −0.3 on hats in the last 8"): the hats' density drops by 0.3 for the outro's last 8 bars (or its second half when shorter) and is restored on the next section, on `clear`, `continue`, undo and stop.
6. **The slam move:** bar 1 everything but fx sits out, bar 2 everything comes back with a fill on that bar, then `continue`. `bars` is refused for slam.
7. **The drop move:** a `drop` section of `bars` (default 16) at energy 5, `fill_every: 8`, the saved mix `drop mix` recalled if one exists, a crash on a labelled cymbal, then `continue`.
8. **The progressive journey's "last beat before each drop nearly empty":** the build before a drop drops kick and bass on its last bar (the build type drops only the kick). **The melodic journey's** builds drop the kick on their last bar (the build default), and its intro is kick and bass with the energy filter (spec row).
9. **The progressive breakdown pad** (`recommends.breakdown_chords: pad.hold`) is not swapped in automatically: a hidden rewrite of the chord tracks would surprise the model, and written parts win their track. A breakdown section's plan names the call instead.
10. **Warnings, not refusals:** a form or move section whose length isn't a multiple of 8 compiles and the result carries `warnings`.
11. **Form arguments:** `form` takes a library name (`techno_plateau`, or a genre word: "techno" picks its record's form) or a string (`"intro 16, build 8, drop 16"`). `club` and `short_demo` are listed as forms too and play exactly their presets.

## 4. Tools and budget

No new tool. `whiplash_arrange` gains `form`, `move`, `bars`, `then` and `energy_filter`, and its section items gain `type`, `energy`, `fill_every`, `enter` and `exit` (`fill` accepts a name). To stay near the spec's final caps (tools 4,350, params 10,300, JSON 24,000 bytes) the new properties carry short descriptions and the skill holds the detail. The measured totals and the caps that move are in the PR and in `tests/test_v053.py::test_description_size_budget`. 26 tools, unchanged.

## 5. Tests (fake and virtual ports only)

New `tests/test_v093.py`:
- **Pure:** every library form compiles to sections `arrange.sections` accepts, each section a multiple of 8 and within 64 / 16 / 512; `"intro 16, build 8, drop 16"` gives the expected tracks, ramps, drop and fill; a 12-bar section warns and compiles; `move: "build", bars: 16` gives the build and drop of spec §6.2, with the filter ramp only for progressive house and melodic techno; each breakdown style compiles to what its row says; unknown types and moves list the known ones; `enter` past the end is refused with "bar 20 is outside build (8 bars)"; a form over 512 bars says the total.
- **Engine (`pretend_playing`):** `fill_every: 8` fills bars 8 and 16 of a 16-bar section and no others; `enter: {hats: -4}` unmutes the hats exactly at bar 13 of 16; `then: "continue"` keeps the beat after the last section with every arrangement mute lifted and no Stop sent; a move while an arrangement runs, then `whiplash_undo`: the old one resumes in the right section; a techno breakdown mutes the kick and keeps the bass; a tech house one sends `filter_freq` on the bass track only and reopens it; minimal subtracts its busiest element; tropical drops to energy 1; section energy lands through `_reroute` on the section's bar and the energy before comes back on `continue`; a crash plays on a labelled cymbal.
- **Library:** `list_library(kind: "form")` and `"move"` list them, and `resolve` reads "tech house dj" and "techno".
- **Equivalence:** `club` and `short_demo` and plain `sections` play bar for bar as before (events and mutes); `loop: true` is `then: "loop"`.
- **Budget** pins updated; the rehearsal stays `RESULT: PASS` (`--v061` too).

## 6. Phil's hardware checks (O4)

From spec §8 (HW O-6, O-7) plus O4's own. They go into `docs/testing/hardware-checklist.md` Part O (O18-O20) and `reference.md` §15.1 #42 and §15.3 as open questions. No result is claimed.

| # | Check | Listen for |
| --- | --- | --- |
| HW O-7 (checklist O18) | "Build to the drop in 16 bars" (`arrange move: build, bars: 16`) on deep house, then on progressive house | hats in for the last 4 bars, the kick sits out bar 16 with a snare roll, everything lands on the one at energy 5, and the beat keeps going; on progressive the music filter opens over the 16 bars |
| HW O-6 (checklist O19) | Energy per section: `arrange(form: "intro 8, groove 8, drop 8, outro 8")` on tech house | each section's energy lands on the one, with no stuck notes and no Stop or Start; the outro's hats thin in its last bars |
| Checklist O20 | A breakdown move in techno, tech house, minimal and tropical | techno: the kick drops, the bass stays; tech house: the bass closes over 2 bars and reopens on the next one; minimal: one element drops out; tropical: the drums thin to energy 1, chords stay |

## 7. Order and merging

One PR against `main`, merge commit only; Deck merges. O5 is cut from `main` after this merges.
