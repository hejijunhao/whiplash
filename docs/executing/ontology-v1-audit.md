# Whiplash ontology v1: post-O5 audit

Status:
- **Audit of the whole v0.9 ontology** (O1a to O5, PRs #26-#31, v0.9.0-v0.9.4) against [ontology-v1-spec.md](ontology-v1-spec.md), reviewed as one system rather than phase by phase.
- Branch `feat/ontology-audit`, cut from `main` at `2378e21` (O5 merged, PR #31). The fixes ship in the same branch as **v0.9.5**.
- **Nothing here has been tested on a real Digitakt II.** The test suite runs on fake and virtual ports only. The hardware checks for all of v0.9 are merged into one session: [v0.9-hardware-checklist.md](../testing/v0.9-hardware-checklist.md).

**Method:**
- Every module the spec names was read on `main` at `2378e21`, along with the five build-plan deviations, the docs and the tests.
- Behavioural findings were reproduced on fake ports before being fixed, and each fix has a regression test in `tests/test_audit.py`.
- A deviation recorded in a build plan, and in the CHANGELOG, is **not** a finding. §5 lists those that were checked.
- The demo-safe promise was checked against the code as it was **before** v0.9: `3f4f883`, the commit the spec was cut from (§1).

**Result in one line:**
- The libraries match the spec almost exactly, and safety holds.
- The existing calls are bit-identical, now proven against a frozen pre-v0.9 snapshot rather than against themselves.
- Ten behavioural findings, all fixed: three in the arrangement grammar (a refusal, a leaked drop, a filter left closed), two in taste that dropped feedback, and five smaller gaps.
- The docs had drifted in a dozen places.

## 1. Safety and the demo-safe promise (spec §0)

| Check | Result |
| --- | --- |
| No SysEx or program change | Holds. `engine.ALLOWED_TYPES` and `Engine.send()` are unchanged since before O1a. |
| `ccmap.BLOCKED_CCS` / `BLOCKED_NRPNS` | Holds. `ccmap.py` is unchanged since `3f4f883`. |
| No new CC | Holds. The only CC the ontology sends is `filter_freq` (CC 74: the timbral steps, the breakdown low-end filter, the energy filter, and the v0.9.5 reopen), plus `track_level`/`pan` through the existing `whiplash_mix`. |
| No writes to the unit; slots 1-3 untouched | Holds. Nothing in the ontology can address a project or slot without SysEx or program change, and both are refused. |
| Drums never pitch-corrected | Holds. Key lock, `in_key`, intents, `follow`, `phrase` and `pedal` all skip or refuse drum, cymbal and fx roles. The timbral step reaches melodic tracks only, now also pinned with labelled cymbal and fx tracks (`tests/test_audit.py`). |
| Clock thread | Holds. The per-bar additions are a digest append, one modulo, dict pops, and `harmony.apply`'s `phrase`/`pedal` lookups. The v0.9.5 fixes add no per-bar work: the reopen is a ramp start at the bar line where an arrangement ends, the same cost as a filter_swap reopen. |
| Validate before touching the beat | Holds. Every O1-O5 handler validates and compiles before it takes the lock to schedule. |
| **Existing calls bit-identical** | Holds, but **was not really tested** (finding A1). Fixed: digests of what deephouse, techhouse, techno, soul and breaks play were taken on `3f4f883` and match today's output. |

## 2. Findings

Severity: **bug** (wrong behaviour), **gap** (the spec says otherwise), **cosmetic**. Every row is fixed in this branch unless it says otherwise.

### 2.1 Cross-layer and arrangement (spec §6)

| # | Finding | Spec | Severity | Fix |
| --- | --- | --- | --- | --- |
| B1 | **A short section was refused instead of warned.** `intro`, `groove` and `drop` carry `fill_every: 8`, and the build carries `enter: {hats: -4}`. Below 8 (or 4) bars, `arrange.section` refused a key the user never gave: `whiplash_arrange(move: "drop", bars: 4)` returned "fill_every (8) is longer than the section (4 bars)", and `move: "build", bars: 2` returned "enter: bar -4 is outside build". | §6.2, Q-A4: "a warning, never a refusal" | bug | `form.expand`: a type's own `fill_every` or `enter` that doesn't fit the section adapts. The fill falls on its last bar; the hats play from the start. A value the caller gives is still validated. |
| B2 | **A replacing move still played the old section's last-bar drop and fill.** `_cancel_owner` cancels only transition-owned items; the section's drop and fill were scheduled without an owner. Club preset into a breakdown move: the build's kick sit-out and fill landed inside the breakdown. | §6.3, Q-A2: "replaces it from the next bar" | bug (pre-existing v0.6.1 behaviour, now meeting the new replace semantics) | The arrangement records the drop and fill its running section scheduled. A replacing arrangement withdraws those that haven't landed. The user's own drops stay, and undo reschedules them with the old arrangement. |
| B3 | **`then: "continue"` left the energy filter closed.** Energy-filter ramps are plain ramps with no restore, so after a progressive or melodic form ending in an outro, the music kept playing at cutoff 48 indefinitely. The `filter_note` also claimed the ramp ends at 127. | §6.2 ("continue ends like clear"); O4 plan §2 ("reopens closed cutoffs") | gap | `Engine._end_arrangement` (continue, clear, undo) ramps the music cutoffs the energy filter closed back to 127 over one bar, as a filter_swap reopen does. `then: "stop"` is unchanged: the run stops and the note says the cutoff stays. The filter note is reworded. |

### 2.2 Taste (spec §7)

| # | Finding | Spec | Severity | Fix |
| --- | --- | --- | --- | --- |
| B4 | **A second hint that fired together with another was lost.** `new_taste_hint` showed the first new hint but marked every new one as delivered, so (for example) a clipping hint firing alongside the repetition hint never reached the model. | §7.3, Q-T3; O5 plan §3.6 | bug | Only the hint shown counts as delivered; the next one rides the next musical result. |
| B5 | **An arrangement's `enter`/`exit`, and its end, didn't count as change.** Only a new section name did. Tech house with hats entering at bar 9 still reported 13 unchanged bars at bar 14. This mattered most in `minimal_long`, where entries and exits *are* the change. | §7.2, Q-T4 ("an arrangement enter/exit") | gap | `taste.mute_changes` reads the muted set the digest already keeps per bar (no new per-bar work), and `change_bars` counts it. The review's `changed` lists `tracks 4 in` or `track 8 out`, and `the arrangement ended`. |
| B6 | The change log read as raw arguments (`mutate action=energy amount=up`). | §7.2 examples (`energy 3 -> 4`, `write_part 6 bass.octave_pump`) | cosmetic | `tools.change_summary` uses the spec's words for energy, phrases and lanes, named progressions and intents, and falls back to the arguments. |

### 2.3 Grooves, harmony, phrases (spec §3-§5)

| # | Finding | Spec | Severity | Fix |
| --- | --- | --- | --- | --- |
| A2 | **A bare `groove: "A"` failed from a cold start**, although the energy error says "try groove: 'A'". With nothing playing there was no genre to resolve the letter against. | §4.2, §4.3 | bug | `tools.groove_pattern` uses the pattern being started (deephouse by default) as the hint when nothing plays. |
| A3 | `mutate(action: "energy")` dropped `pushed_downbeat_clamped`. `play_pattern` and `write_part(groove)` report it. | §4.2 ("clamped to 0 and reported") | gap | Reported on the energy result and kept on the groove state. |
| A4 | **bII was spelled A#** in A minor (`house.piano_stab` showed Am C A# Am), because names followed the key's sharp/flat spelling even for a flat numeral. | §1.1, §3.2.1 ("bII in A minor is B♭") | cosmetic (names only; the notes are identical) | An explicit accidental on a numeral spells the name: `bII` → Bb, `#iii7` → C#m7. A numeral with no accidental spells as before. This also changes v0.6's `bVII` in C major from "A#" to "Bb" in results: display only, and the MIDI is bit-identical. |
| A5 | The unknown-phrase hint pointed at the whole phrase list. | §5.3 (`whiplash_list_library(kind: "phrase", tag: "bass")`) | cosmetic | The hint adds the track's role as the tag. |

### 2.4 Tests (spec §3.5, §4.5, §5.5, §6.5, §7.5)

| # | Finding | Severity | Fix |
| --- | --- | --- | --- |
| A1 | **The demo-safe equivalence tests were tautological.** `test_v090.py` asserts `compiled is P[genre]` and plays the same object twice; `test_v092.py` compares the table with `patterns.register(RAW[genre])`. An edit to `patterns.py` would pass them all. The only frozen pin, `test_v093.py`'s digests, was taken at v0.9.2 and covers arrangements only. | gap | `tests/test_audit.py` pins digests taken on `3f4f883`, the pre-v0.9 code: 8 bars of `bar_events` for each of the five old genres; the same through their `classic` grooves at energy 3; and the tool path `whiplash_play_pattern(genre)`, with and without `key: "Fm"`. All match today. |
| C1 | **Duplicate names were never checked.** The library tables are dict comprehensions, so a second entry with the same name silently overwrites the first. Only per-genre counts for progressions caught it, indirectly. | gap | A test counts the entries written in each table's source (including `GROOVES.update`) against the dict: lanes, grooves, fills, phrases, progressions, forms, moves and genres. |
| C2 | Partial coverage: timbral never tested with labelled cymbal or fx tracks; undo after `tension` untested; the scale-mismatch key report tested on the engine only with `house.mixed_shuffle`; `hat.open_choke` never played on the engine. | weak | One test each in `tests/test_audit.py`. |
| C3 | `scripts/clock_jitter.py --calls` never sets a library progression or `pedal`, so spec §3.5's jitter check is covered only by `test_v091`'s per-bar cost bound (under 4 ms with a pedal running). | weak | **Not changed.** The cost bound is the deterministic check, and the jitter script measures the laptop. Recorded here. |
| C4 | The micro note-on timing test runs only with strict timing (skipped on CI), and checks only the clap. | weak | **Not changed.** The offsets are pinned exactly in the pattern tests; wall-clock checks stay report-only on CI by design (`tests/conftest.py`). |
| C5 | `test_rehearsal.py::test_the_v06_progression_rehearses_clean` failed once in a local run with three reviewers loading the machine, and passed alone and in two full runs after. | flaky (timing) | **Not changed.** It is a wall-clock rehearsal; CI already treats such bounds as report-only. Watch it. |

### 2.5 Docs (spec §1.6, §9: "updates the skill, README, CHANGELOG, roadmap")

| # | Finding | Fix |
| --- | --- | --- |
| D1 | The spec's Status header still said "Spec only … O1a is ready to start", "Branch `docs/ontology-spec`", "No code … come with it". | Status now says it is implemented in v0.9.0-v0.9.5, and points to the plans, this audit and the checklist. |
| D2 | Spec §1.4 gave today's budget as 4,033 of 4,100 with 25 tools, and the proposed JSON cap as 24,000. The shipped pin is 24,650 (O4, explained in the CHANGELOG but not in the spec). | A "shipped" note with the pinned caps (4,350 / 10,200 / 24,650, 26 tools). |
| D3 | Spec §4.2.1 says `rim.bossa` is a "syncopated 3-3-2". The lane is 3-3-4-3-3 over 16 (steps 0, 3, 6, 10, 13), the bossa clave, and no groove uses it. | **Decision: keep the lane** (the shape matches its name). The spec row now says so. |
| D4 | `hardware-checklist.md` said it covers "everything merged up to v0.7.1" and expected "v0.7.1, 22 tools". Part O's title still said "O1a + O1b … v0.9.0" though it runs to O21, and its results table had no rows for Q32-Q52. | Header, setup line and title updated. The results table gains the Part O rows and points to the v0.9 session. (The header now also says v0.8.0's play along, reference Q26-Q31, has no checklist part: outside v0.9, noted only.) |
| D5 | `CHANGELOG.md`'s "Unreleased" section listed work that had already shipped before 0.9.0 (the visualiser timeline, the clock-jitter work, the `--v06`/`--v061` rehearsals, checklist Parts P/R/V/W). | Renamed to say what it is: docs and tooling merged alongside v0.8.0-v0.9.0. A 0.9.5 entry lists the audit's fixes. |
| D6 | README: the named fills left out `cymbal.crash`; checklist O21 wasn't mentioned; the `whiplash_arrange` row left out `energy_filter`; the O1b test bullet was out of order. | Fixed, and the test count updated. |
| D7 | The skill's diagnostics table had no row for eight v0.9 failures: `groove X belongs to Y`, `already at energy 5/1`, `follow is for melodic parts`, `X has no genre phrases`, `give chords or name, not both`, slam's `bars is for build, drop and breakdown`, `can't both enter and exit`, and a move with nothing playing. | Rows added (spec §1.6: "a diagnostics row per new failure"). |
| D8 | Roadmap: "More genres: minimal, …" was stale after O3. Unlike v0.6-v0.8, v0.9 had no "none of it has been tested on hardware" line. | Both fixed; the audit and the checklist are linked. |
| D9 | `plugin.yaml`'s description and `docs/catalog-entry.yaml` didn't mention the ontology (only the tool list was updated). | One sentence each. |
| D10 | `docs/catalog-pr.md` still says "Version 0.5.0" and "12 tools". | **Not changed.** It is the text of the original catalog PR, a historical record. |

## 3. Spec gaps kept, with the reason

These differ from the spec in small ways that don't change what plays wrongly. They are recorded rather than changed:
- **`phrases.fallback` uses the tonic triad.** Spec §5.2 says "or a 7th for a 7th-flavoured generator". With no progression playing, a `7` tone (from `arp.chord_seeded`, say) falls to the nearest chord tone, as the spec's own missing-tone rule says. Making the fallback chord depend on the phrase would change O1b-O3 lines that are already pinned, for no audible gain over the triad.
- **`harmony.Rel` allows octave −2** (spec §5.2 says −1..+2). Every phrase in the library uses −1..+2, and the register rule clamps the result anyway.
- **Energy changes are not undoable** (`whiplash_undo` restores parts, arrangements and harmony). The spec never asks for it, and "energy down" is the undo.
- **`_taste_inputs` walks the 64 digest bars under `_lock`** to collect track ids. That's a little more than "copies only", but it runs in the tool thread, never the sequencer, and is bounded at 64 bars × 16 steps.
- **Internal section keys** (`_style`, `_thin`, `_crash`) are accepted in user `sections` that also carry `type` or `energy`. That is harmless: they only select behaviour the type already allows.

## 4. What was checked and found correct

- **§1 library and genres.**
  - `library.resolve` handles case, separators, a missing prefix, natural phrases, letter aliases, ambiguity and closest matches.
  - `whiplash_list_library` has the 8 kinds, the 40-row cap, and the unknown-kind and empty-filter hints.
  - There are 26 tools, with every §1.5 alias and mood (`house` still deep house, `peak time` techno, `minimal` minimal.house) and both required CHANGELOG lines.
  - All nine `Genre` records match §2.1 on BPM, swing, key, groove, progression, bass, chords, breakdown, form and taste thresholds.
- **§3 harmony.**
  - All 28 progressions match §3.2.1 on numerals, bars per chord, scale and voicing, and parse in all 12 keys.
  - The new shapes and suffixes are in place, and the shell rule holds (2 chord tracks shell, 4 close, a pad carries the 9th).
  - The scale-mismatch rule and its key report work.
  - Intents work: darker to phrygian, `applied`, `other_options`, no CC for harmonic, timbral melodic-only, the brighter ceiling, the three tension steps, and release.
  - Key-only changes work, as do key lock and `out_of_key`.
- **§4 grooves.**
  - Every lane's steps and micro match §4.2.1, and every groove's energy-3 lanes and swing match §4.2.2.
  - Hits per bar never fall with energy, and no level passes its genre's busy cap.
  - Classic grooves have no micro, and `GHOST_VEL` is 28-40.
  - Soul and breaks have one level with the spec's message.
  - The fills work, including the `perc.tom_run` fallback, and energy changes go through `_reroute`.
- **§5 phrases.**
  - Every phrase's grid, tones and gates match §5.2.1, and only leads, arps and the motif are `on_request`.
  - `phrase: "genre"` and its refusals work.
  - Chicago house plays its phrases with no further call, the octave pump follows `house.uplift`, and the descending walk plays A G F E.
- **§6 arrangement.**
  - Section types and breakdown styles match the tables.
  - All eight forms compile within 64 / 16 / 512 bars, and the energy filter is on only for the progressive and melodic journeys.
  - Rising steps, enter/exit offsets, the `then` defaults, move results and undo of a replaced arrangement all work.
- **§7 taste.**
  - The thresholds table matches Q-T2.
  - Every hint names real calls and resolvable entries, and `heard()` enforces same run, recorded while playing, and under 32 bars.
  - The last-run review and the shrinking window work.
  - A review sends nothing and opens nothing.
- **Budget.** Measured 4,322 / 10,170 / 24,625 against the pins 4,350 / 10,200 / 24,650.

## 5. Build-plan deviations confirmed as documented (not findings)

- **The negative-micro compile is swing-aware:** `6 + micro` plus the swing difference (O1a plan #5).
- **Key lock leaves unlabelled `other` tracks alone** (O1a plan #14, CHANGELOG).
- **`timbral` won't guess a cutoff Whiplash never sent** (O2 plan step 2).
- **Lane substitutions:** `techhouse.rolling`'s energy 5 uses a second perc slot (`perc2`), reported `unplaced` on an unlabelled kit (O1a plan #4). `minimal.house_shuffle` plays its `hat.open_choke` fill on the perc track, and tropical uses its own `kick.soft` lane (O3 plan #3, #4).
- **Thresholds are not tuned yet:** no session results exist (O5 plan §3.5). [v0.9-hardware-checklist.md](../testing/v0.9-hardware-checklist.md) L2 is where they come from.

## 6. Hardware

One consolidated session for Phil's Air: [docs/testing/v0.9-hardware-checklist.md](../testing/v0.9-hardware-checklist.md).
- It merges Part O (O1-O21), spec §8 HW O-1 to O-8, the O2 plan's HW O-9 to O-12, and reference §15.3 Q32-Q52.
- It reorders them genre by genre and adds checks for the v0.9.5 changes: M3 (a replacing move leaves no stray drop), M4 (the energy filter reopens after `continue`; new reference Q53) and M5 (a short build plays with a warning).
- Nothing in it is a result.
