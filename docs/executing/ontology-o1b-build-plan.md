# Whiplash ontology O1b build plan (v0.9.0, part 2 of 2)

Status:
- **Plan for O1b**, the second phase of [ontology-v1-spec.md](ontology-v1-spec.md) §9: the phrase and taste layers for the four O1 genres (deep house, classic house, tech house, techno). Branch `feat/ontology-o1b`, cut from `main` at `c21e4e8` (O1a merged, PR #26).
- O1a and O1b together make up **v0.9.0**. The version stays 0.9.0; this PR adds to the 0.9.0 changelog section.
- Nothing here has been tested on a real Digitakt II. Every **HW** item in §6 is a check for Phil's Air, not a result.

Inputs:
- **Spec:** [ontology-v1-spec.md](ontology-v1-spec.md). This plan's scope is §9's O1b row. The layer sections are §5 (phrases), §7 (taste), §8 (hardware checks) and §10 (decisions Q-P1..Q-P4, Q-T1..Q-T4).
- **O1a:** [ontology-o1a-build-plan.md](ontology-o1a-build-plan.md), whose design note 1 (house's baked lines) this phase replaces.
- **Research:** [genre-conventions.md](../research/genre-conventions.md) §1, §2, §3, §5 for the phrases and the thresholds.
- **Device reference:** [reference.md](../digitakt-ii/reference.md) §6.1 (note 60, native pitch, 16-84), §6.4 (one voice per audio track).

**Goal of O1b (the demo sentence, completed):** "Chicago house" plays the octave-bounce bass and the off-beat stabs as phrases, so `set_progression(name: "house.uplift")` moves both with the chords. `write_part(track: 6, phrase: "bass.rolling_deep")` writes a deep house bass that follows whatever progression plays. And after 8 unchanged bars of tech house, the next tool result says so, with named next moves, while changing nothing.

**Constraints** (spec §0, unchanged):
- No SysEx, program change, project, pattern, kit or +Drive writes. Slots 1-3 are never touched. `BLOCKED_CCS` / `BLOCKED_NRPNS` stay blocked; O1b sends no new CC at all.
- Clock-safe. The new bar-line work is the `phrase` branch of `harmony.apply` (per hit: one interval lookup and a little arithmetic) and one `bar_digest.append` per bar. Everything else (phrase building, fallback progressions, metrics, hints) runs in the tool thread.
- **Demo-safe:** no hand-written genre has a phrase, so every pre-0.9 call plays bit for bit as before (equivalence tests). Drums are never pitch-corrected: phrases are refused on drum, cymbal and fx tracks, and taste never sends anything.

## 1. Scope

| # | Item | Spec | Size |
| --- | --- | --- | --- |
| 1 | `harmony.Rel`: a chord-relative note (an `int` subclass with `tone`, `octave`, `floor`), and `harmony.resolve` | §5.2 | S |
| 2 | `harmony.apply` mode `phrase`; `harmony.modes` gives a track whose line carries `Rel` notes mode `phrase` (also when no progression plays); chord-tone phrase tracks rank with the chord tracks (shell rule, pads) | §5.2, §5.4 | M |
| 3 | `phrases.py`: the `Phrase` record and the five O1b phrases `bass.rolling_deep`, `bass.octave_pump`, `bass.bouncy`, `bass.offbeat`, `stab.offbeat`; density by rank, seeded variation, register, the v0.5 rule | §5.2.1 | M |
| 4 | `write_part(phrase, density, seed, register)` and `phrase: "genre"` | §5.3 | M |
| 5 | House compiled from its phrases (`bass.octave_pump`, `stab.offbeat`) instead of O1a's baked lines | §1.2, §5.3 | S |
| 6 | `library` kind `phrase` (resolve and list) | §1.1, §1.3 | S |
| 7 | `Engine.bar_digest`, `Engine.changes`; `taste.py` (metrics, per-genre thresholds, hints) | §7.2 | M |
| 8 | `whiplash_status(review: 4-32)`, `status.taste`, `taste_hint` on musical tool results | §7.3 | M |
| 9 | Skill, README, CHANGELOG, roadmap, budget pins, hardware checklist and reference §15.3 | §1.6, §9 | S |

**Not in O1b:** intents, key-only `set_progression`, `lock`, `pedal`, `follow: true` (O2); the other phrases (`bass.root_follow` .. `melody.motif`, `pad.hold`) and the other four genres and their thresholds (O3); forms, moves, `enter`/`exit` (O4); listen data in reviews and threshold tuning (O5).

## 2. New modules (pure, at the repo root)

- **`phrases.py`.** The `Phrase` record of spec §5.2 (plus `density`, the default density, and per-hit `length`), the five phrases, `build()` and the fallback progressions (§3, note 4).
- **`taste.py`.** Fingerprints, `metrics()`, per-genre thresholds (`Genre.taste`, plus the spec's soul/breaks default of 16 bars / 6 drums) and `hints()`, which only name moves, lanes, fills and phrases that exist in the libraries.

## 3. Design notes and decisions

Researchable questions were decided here from the spec and the research brief; the PR lists them.

1. **`Rel` arithmetic keeps the type.** `Rel + n` is a `Rel` with the same tone, octave and register floor and the value moved by `n`, so `patterns.register`, `harmony.in_key` and `snap` keep a phrase a phrase. Hashing and equality are the integer's. `apply()` always returns plain ints, and the engine's transpose runs after it, so a `Rel` never reaches the port.
2. **Resolution.** The chord root lands in the register window `[floor, floor + 11]` (low 53, mid 60, high 67; an anchor note `n` gives `n - 5`), so a bass line's median stays at or above 53 by construction. Tones are offsets from that root: `R`, `3`, `5`, `7`, `9`, `oct` (R+12), `chord` (the voiced chord tone for the track's rank, as `chords` mode plays it), `step±n` (scale steps from the root) and `approach` (the scale step below the next chord's root). A tone the chord lacks (a 7th on a triad) falls to the nearest chord tone. `+12`/`-12` suffixes move a tone by an octave. Notes stay in 16-84.
3. **Which tracks follow.** A track whose line carries `Rel` notes gets mode `phrase`, written or generated, unless `set_progression(tracks)` names another mode for it. No hand-written table has a `Rel`, so every pre-0.9 track keeps its old mode. Chord-tone phrase tracks rank with `chords` tracks, so the shell rule counts them and a pad track carries the colour tones.
4. **With no progression playing,** phrase tracks resolve against a fallback progression prepared in the tool thread: the genre's default progression (house: `house.piano_stab`, aligned to the pattern's 4-bar loop), else the key's tonic triad. The bar line only does a dict lookup for it; a miss (a key that landed at a bar line before any tool call prepared it) plays the `Rel`s' own values, which were resolved against the same thing. So "Chicago house" alone plays i–III–♭II–i, and a phrase written over deep house follows its key. The spec's "7th for a 7th-flavoured generator" doesn't arise in O1b's five phrases (none uses a 7th); a triad it is.
5. **House compiled from phrases.** `genres.compile` builds tracks 6-8 with `phrases.build` against `house.piano_stab`. The notes are exactly O1a's baked lines (tested), now as `Rel`s that follow a later progression.
6. **The O1b phrases.**

   | Phrase | Steps (tones) | Length, velocity | Default density | Variation |
   | --- | --- | --- | --- | --- |
   | `bass.rolling_deep` | 0 R, 3 R, 6 5, 8 R, 11 oct, 14 5 | 3/1/2/3/1/2 steps; 104 on the beats, 84 between | 1 | seeded: bar 4 re-picks its passing tones (5, oct, 3) from the seed |
   | `bass.octave_pump` | R on 0 4 8 12, oct on 2 6 10 14 | 1; 108 / 96 | 1 | none |
   | `bass.bouncy` | 2 3 6 10 11 14: R R R R oct R | 1; 108, 84 on 3 and 11 | 1 | none |
   | `bass.offbeat` | R on 2 6 10 14 (rank first), 3 7 11 15 | 1; 100 / 80 | 0.5 (density 1 adds the rolling 16ths) | none |
   | `stab.offbeat` | `chord` on 2 6 10 14 (rank 6 14 2 10) | 1; 100 on 2, 88 elsewhere | 1 (`phrase: "genre"` on tech house and techno: 0.25) | none |

   `seed` only changes a `seeded` phrase; the result says so otherwise.
7. **`write_part(phrase)` refuses** `notes` ("phrase brings its own notes; drop notes, or use rhythm + notes"), any placement, `key`, `scale`, `length`, `velocity`, `bars` and `out_of_key`. Phrases are in key by construction, so key lock has nothing to snap.
8. **`phrase: "genre"`** takes the playing genre's record: `bass` for a bass track, `chords` for a chord, stab or pad track; for a hand-written genre, its `recommends`. A recommendation that arrives in O3 (deep house's `pad.hold`) or a lead (Q-P3) is refused with that reason. soul and breaks have no record and say so.
9. **What counts as change** (Q-T4): a `changes` entry landing, a user move (mapped to its bar through `bar_log`), a bar on which a ramp is running, and an arrangement section starting. `changes` is fed in one place, the tool wrapper, for every successful musical tool call while a beat plays, with the bar the result says it lands on.
10. **`unchanged_for_bars`** counts bars played after the last change. Fingerprints are per bar: `(track, step, note, velocity // 8)` over unmuted tracks. `cycles_repeated` counts identical 4-bar blocks back from the latest.
11. **Hints in O1b:** repetition (`unchanged_for_bars` at or past the genre's threshold) and busyness (more drum elements than `busy_drums`). The bass/kick masking hint needs listen data and arrives with O5; O1b reports `low_collisions` as a metric only. `listen` in a review is `null` until O5.
12. **`taste_hint`** rides on a musical tool's result only when a hint fires that didn't fire at the previous musical result. It fires again only after it has stopped firing. The digest is cleared by a fresh start; with nothing playing, a review covers the last run.

## 4. Tools and budget

| Tool | Gains |
| --- | --- |
| `whiplash_write_part` | `phrase` (a library name or `"genre"`), `density`, `seed`, `register`; result `phrase`, `follows`, `now`, `register`, `density` |
| `whiplash_status` | `review` (4-32): the compact review instead of the full status; the full status gains `taste` |
| every musical tool | `taste_hint`, one line, only when a threshold newly fires |
| `whiplash_list_library` | kind `phrase` lists entries (it was empty until now) |

Caps (`tests/test_v053.py::test_description_size_budget`), raised only as far as O1b uses (measured: tools 4,248, params 9,951, JSON 23,472 bytes): tools stay at **4,250**, params 9,900 → **10,000**, JSON 23,500 → **23,600** bytes. All inside the spec's final targets (4,350 / 10,300 / 24,000). 26 tools, unchanged.

## 5. Tests (fake and virtual ports only)

New `tests/test_v090_o1b.py`:
- **Rel:** arithmetic keeps tone and floor, hashing and equality are the int's; `register` and `in_key` keep `Rel`s.
- **Resolution:** every O1b phrase against every library progression in all 12 keys: median ≥ 53, notes in 16-84; a seeded line is identical across runs; `approach` lands one scale step from the next root; a 7th on a triad falls to a chord tone; density 0.25 keeps the top-ranked quarter; no `on_request` phrase is a genre default.
- **Engine:** `write_part(track: 6, phrase: "bass.octave_pump")` then `set_progression(name: "house.uplift")`: track 6 plays root and octave of A, F, C, G at two bars each (`bar_events`); `whiplash_undo` brings the previous line back; a `thicken` ghost keeps a `Rel` and resolves; `play_pattern(genre: "chicago")` plays the octave pump on 6 and the stabs on 7-8 with no further call, identical to O1a's notes, and follows `house.uplift` once set; `phrase: "genre"` per genre; refusals (kick-labelled track, `notes`, an O3 recommendation, a lead) change nothing (`status` before and after equal).
- **Equivalence:** the five hand-written genres play the same `bar_events` on bars 0-3 as before, with and without a progression.
- **Taste, pure:** fingerprints are stable; a density or chord change resets `cycles_repeated`; thresholds fire at tech house 8, deep house 32, techno 64 and not one bar earlier; a running ramp resets `unchanged_for_bars`; every hint names only library entries that resolve.
- **Taste, engine:** 10 bars of tech house with no calls give `unchanged_for_bars` ≥ 8 and the repetition hint; 10 bars of deep house give none; `mutate energy up` shows under `changed` at its bar; a `FakeInput` knob move shows as `by: "user"`; `taste_hint` appears once and not on the next result; `status(review)` sends nothing and never opens the input; a short run shrinks the window and says so; nothing played says so.
- **Budget** pins updated; the rehearsal stays `RESULT: PASS`; a bar-line cost check with phrases and a progression running.

## 6. Phil's hardware checks (O1b)

From spec §8. They go into `docs/testing/hardware-checklist.md` Part O and `reference.md` §15.3 as open questions. No result is claimed.

| # | Check | Listen for |
| --- | --- | --- |
| HW O-3 | "Chicago house" (track 6, 123 BPM), then "house uplift progression" | clean root and octave retriggers near native pitch; the bass and stabs move with the chords on the bar |
| HW O-3b | `write_part(track: 6, phrase: "bass.rolling_deep")` over deep house, then "deep house gospel progression" | a rolling bass near native pitch that follows the chords |
| HW O-8 | Let tech house run 16 bars, then "how's it sounding?" | Hermes quotes the review (unchanged bars, a named next move) and changes nothing by itself |

## 7. Order and merging

One PR against `main`, merge commit only; Deck merges. O2 is cut from `main` after this merges.
