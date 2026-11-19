# Whiplash ontology O3 build plan (v0.9.2)

Status:
- **Plan for O3**, the fourth phase of [ontology-v1-spec.md](ontology-v1-spec.md) §9: the other four genres. Branch `feat/ontology-o3`, cut from `main` at `f67252b` (O2 merged, PR #28).
- O3 ships as **v0.9.2**.
- Nothing here has been tested on a real Digitakt II. Every **HW** item in §6 is a check for Phil's Air, not a result.

Inputs:
- **Spec:** [ontology-v1-spec.md](ontology-v1-spec.md). This plan's scope is §9's O3 row. The tables are §2.1 (genre records), §3.2.1 (progressions), §4.2.1 (lanes marked O3), §4.2.2 (grooves marked O3), §5.2.1 (phrases marked O3) and §1.5 (aliases and moods marked O3), plus §7.2 (thresholds), §8 and §10 (Q-P3, Q-alias-minimal).
- **Earlier phases:** [ontology-o1a-build-plan.md](ontology-o1a-build-plan.md) (records, the compile path, grooves), [ontology-o1b-build-plan.md](ontology-o1b-build-plan.md) (phrases, fallbacks, taste), [ontology-o2-build-plan.md](ontology-o2-build-plan.md) (intents and keys).
- **Research:** [genre-conventions.md](../research/genre-conventions.md) §4 (progressive house), §6 (minimal), §7 (tropical house), §8 (melodic techno).
- **Device reference:** [reference.md](../digitakt-ii/reference.md) §6.1 (note 60, native pitch, 16-84), §6.4 (one voice per audio track).

**Goal of O3 (the demo sentences):** "progressive house" plays a functional 124 BPM groove with off-beat 7th and sus stabs over a circular Am7–Dm7–Gsus4–Cmaj7 and a root bass that follows it. "Melodic techno" plays stripped drums, a rolling 16th bass and a held cinematic pad. "Minimal" plays four drum elements, space, a sparse bass and a single stab. "Tropical house" plays soft drums with shaker and bongos at 108 BPM over a bright C major pop loop with a round sub. Each comes from `play_pattern` alone, and each has five energy levels. A model can also ask for an arp, a stutter lead, a pentatonic hook or a motif by name.

**Constraints** (spec §0, unchanged):
- No SysEx, program change, project, pattern, kit or +Drive writes. Slots 1-3 are never touched. `BLOCKED_CCS` / `BLOCKED_NRPNS` stay blocked. O3 sends no new kind of message: the new genres are ordinary patterns.
- Clock-safe. Records, grooves and phrase lines all compile at import or in the tool thread into a `patterns.Pattern` or a written part. The sequencer gains no work: the new phrases resolve through the existing `phrase` branch of `harmony.apply`.
- **Drums are never pitch-corrected.** New lanes play note 60, and new phrases are refused on drum, cymbal and fx tracks as before.
- **Demo-safe:** every pre-0.9.2 call plays bit for bit as before (equivalence tests). The five hand-written genres and classic house compile exactly as they did; the only new behaviour on an old genre is that `soul` and `breaks` now report a one-level `classic` groove.

## 1. Scope

| # | Item | Spec | Size |
| --- | --- | --- | --- |
| 1 | `genres.py` records for `progressivehouse`, `melodictechno`, `minimal.house`, `minimal.techno` and `tropicalhouse`, compiled like classic house | §1.2, §2.1 | S |
| 2 | Progressions: progressive house (4), melodic techno (2), minimal (3), tropical house (2), with brightness and tension for O2's intents | §3.2.1 | S |
| 3 | Lanes marked O3: `clap.every_other_bar`, `rim.on_3`, `rim.sparse_2_4`, `perc.poly3` (the 3-against-4 approximation), `perc.bongo`, `hat.shaker_16`, plus the helper lanes the new levels need | §4.2.1 | S |
| 4 | Grooves marked O3, five energy levels each, within each genre's `busy_drums` cap: `progressivehouse.functional`, `melodictechno.stripped`, `minimal.house_shuffle`, `minimal.techno_kick`, `tropicalhouse.soft`; and one-level `soul.classic` / `breaks.classic` | §4.2.2 | M |
| 5 | Phrases: `bass.root_follow`, `bass.rolling_16`, `bass.stab_sparse`, `bass.round_sub`, `bass.descending_walk`, `bass.walking`, `stab.single`, `pad.hold`, `arp.chord_up`, `arp.chord_updown`, `arp.chord_seeded`, `lead.stutter`, `lead.pentatonic_hook`, `melody.motif` (leads on request only) | §5.2.1 | M |
| 6 | Aliases and moods marked O3 (`progressive`, `melodic techno`, `tropical`, bare `minimal` → `minimal.house`, `journey`, `cinematic`, `sunny`, `sparse`, ...) and their library genre words | §1.5 | S |
| 7 | Taste thresholds and named suggestions for the new genres | §7.2 | S |
| 8 | Skill, README, CHANGELOG, roadmap, budget pins, hardware checklist and reference §15.3 | §1.6, §9 | S |

**Not in O3:** forms, section types, breakdown styles and moves (O4: the records name their `breakdown` and `form`, which O4 reads); listen data in reviews (O5); slash chords (§11).

## 2. Engine shape

- **No engine change for the new genres.** A compiled genre lands in `patterns.PATTERNS` under its record's name, so `play_pattern`, `kitmap.route`, `harmony.in_key`, fills, density, phrases' fallbacks, intents and key changes see an ordinary pattern, as they do for classic house.
- **`genres.compile` hands the groove compiler the record's whole layout** (drum roles included), so a perc lane lands on track 8 where the genre puts perc. Classic house compiles bit for bit as before (pinned).
- **Phrase tones count across the loop** instead of restarting each bar, so a 4-bar walk (`bass.descending_walk`: R, step−1, step−2, step−3) or a 2-bar line can name a tone per hit. Every O1b phrase has a whole number of tone cycles per bar, so their lines are unchanged (pinned).
- **New phrase variations** in `phrases.shape`, all seeded through `mutate.rng` and deterministic: `shift` (a chordal phrase's bar 4 moves its hit to a seeded step: `stab.single`), `arp` (every hit picks a chord tone: `arp.chord_seeded`), `hook` (a seeded 2-bar hook repeated: `lead.pentatonic_hook`) and `motif` (A, A, A up a step, an answer ending on R: `melody.motif`). They are data work in the tool thread.
- **`soul.classic` / `breaks.classic`** are one-level grooves (energy 3 is today's pattern). `mutate energy` on them refuses: "soul.classic has one energy level (3); pick a genre with levels", and nothing changes.

## 3. Design notes and decisions

Researchable questions decided here from the spec and the research brief; the PR lists them.

1. **Track layouts** (the patterns.py layout, spec §2.1): progressive house 7-8 chord stabs; melodic techno 7 pad, 8 perc; minimal house 7 stab, 8 perc; minimal techno 8 perc and no chord track (its record has no chord phrase); tropical house 7 pad, 8 perc (bongos). Track 4 carries tropical's shaker (`hat.shaker_16`, a closed-hat lane, research §7).
2. **Energy levels** follow the spec's shared meaning, adapted where a genre has no hats at its core: minimal house's level 1 is the kick plus its off-beat conga (the conga is its "hat", research §6). Levels add hits before elements, and no level passes the genre's `busy_drums` cap (minimal 4, progressive and tropical 5, melodic 6). Levels 4-5 use small helper lanes (tagged `helper`), as O1a's did.
3. **Minimal house's fill** `hat.open_choke` plays on its perc track (it has no open hat at any level): a long hit then a choked one, the shape the research describes for minimal (space, one change per phrase).
4. **Tropical's soft kick** is its own lane, `kick.soft` (four on the floor with the `soft` curve), since a lane carries one velocity curve.
5. **Progressive house's breakdown pad.** The record's chord phrase is `stab.offbeat` (the groove); `pad.hold` is recommended for breakdowns (`recommends.breakdown_chords`), which O4's breakdown style uses.
6. **`progressivehouse.descending`** names `bass.descending_walk`. `set_progression(name)` doesn't rewrite the bass by itself (written parts win their track, and a hidden rewrite would surprise the model); its result recommends the call: `write_part(track: 6, phrase: "bass.descending_walk")`.
7. **Brightness and tension** for the new progressions (by ear, for O2's swap): progressive circle 0/1, long_two −1/1, phrygian_turn −2/3, descending −1/1; melodic cinematic 0/1, held_vamp −1/0; minimal stab_m7 −1/0, stab_sus2 0/0, fifth −1/0; tropical pop +2/1, pop_minor +1/1.
8. **Lead phrases** (Q-P3) are `on_request`: never a record default, and `write_part(phrase: "genre")` on a lead track still says leads stay model-written, naming the lead phrases it can ask for.
9. **`lead.pentatonic_hook`** resolves chord-relative like every phrase: its tones are R, 3, 5, 9 and the octave of each chord, which is the major pentatonic over a major chord and stays consonant over the others (key lock keeps it in key). It is seeded over 2 bars and repeats, so it reads as a hook.
10. **`melody.motif`** is written in scale steps from each chord's root: chord tones (0, 2, 4, 7 steps) on 0/4/8/12 and passing steps between, seeded; bar 2 repeats it, bar 3 sequences it up a step, bar 4 answers it (the first half, then down to R), as `jam.reply`'s answer does.
11. **`perc.poly3`** hits every 3rd step over the 64-cell loop, so it repeats every 4 bars (bar 4 matches bar 1): the spec's approximation of 3 against 4.
12. **Energy on a plain compiled genre.** `play_pattern(genre: "progressive")` with no `groove` plays the record's default groove at energy 3, so `mutate energy` works from it (O1a asked for a `groove` on classic house; that refusal becomes a success, and nothing that played before changes).
13. **Library names for minimal.** The two presets share the `minimal` prefix (`minimal.house_shuffle`, `minimal.stab_m7`). `library.resolve` reads "minimal house shuffle" and "minimal shuffle"; `list_library(genre: "minimal techno")` lists the shared minimal progressions and phrases plus that preset's grooves.

## 4. Tools and budget

No new tool and no new argument. `whiplash_play_pattern`'s `genre` enum gains the five new ids. To stay inside the spec's final targets (tools 4,350, params 10,300, JSON 24,000 bytes) with room for O4, its mood description lists one mood per genre instead of all of them (an unknown mood's error still lists every one), and `whiplash_mix`'s preset enum keeps the pre-O3 presets (the new genres' presets come through `auto`). Measured: tools 4,300, params 10,049, JSON 23,919 bytes, all under the O2 caps, so the caps (`tests/test_v053.py::test_description_size_budget`) don't move. 26 tools, unchanged.

## 5. Tests (fake and virtual ports only)

New `tests/test_v092.py`:
- **Records:** each new genre's record matches spec §2.1 (bpm, swing, key, groove, progression, bass, chords, breakdown, form, taste); each compiles to a registered pattern with its groove's drums at energy 3 and its phrases on the bass and chord tracks; native register holds (melodic medians ≥ 53, notes 16-84).
- **Progressions:** every new entry parses in all 12 keys and voices in 41-79 with median ≥ 53; spec chord names in the home key (`progressivehouse.circle` = Am7 Dm7 Gsus4 Cmaj7, `tropicalhouse.pop` = Cmaj7 G Am7 Fmaj7 in C major, ...); tags from the vocabulary; every `bass` names a phrase.
- **Lanes and grooves:** O3 lanes parse; `perc.poly3` hits every 3rd cell over 64; each new groove's levels name known lanes, get busier and stay within the cap; `soul.classic` / `breaks.classic` at energy 3 are today's patterns, and energy on them refuses with nothing changed.
- **Phrases:** every phrase resolves against every library progression in all keys (medians ≥ 53, notes 16-84), seeded lines identical across runs; `bass.descending_walk` over `progressivehouse.descending` in A minor plays A, G, F, E on bars 1-4; `pad.hold` matches `harmony.pad_line`'s timing; no `on_request` phrase is a genre default; `phrase: "genre"` on a lead refuses; the O1b phrases build exactly as before.
- **Engine:** `play_pattern(genre: "progressive")`, `"melodic techno"`, `"minimal"`, `"minimal techno"` and `"tropical"` each play their record's lines (`bar_events`); a set_progression and a key change move the phrase lines; `write_part(phrase: "arp.chord_up")` follows the chords.
- **Aliases:** bare `"minimal"` is `minimal.house`; each O3 alias and mood resolves; `"house"` is still deep house.
- **Taste:** each new genre's threshold fires at its value; hints name library entries.
- **Equivalence:** the five hand-written genres and classic house play the same `bar_events` as before; the O1b phrases' lines are unchanged.
- **Budget** pins updated; the rehearsal stays `RESULT: PASS`.

## 6. Phil's hardware checks (O3)

From spec §8 (O-5 for the O3 progressions) plus O3's own. They go into `docs/testing/hardware-checklist.md` Part O (O14-O17) and `reference.md` §15.1 #41 and §15.3 (Q44-48) as open questions. No result is claimed.

| # | Check | Listen for |
| --- | --- | --- |
| HW O-5, second half (checklist O14) | By ear: the progressive, melodic techno, minimal and tropical progressions (§3.2.1) | each loop sounds like its genre on Phil's kit; list the ones to drop or revoice |
| Checklist O15 | "progressive house", then energy 1 to 5 | functional 124 BPM drums, off-beat stabs over the circle, the bass follows each chord; each level lands on the one |
| Checklist O16 | "melodic techno", then `write_part(lead track, phrase: "lead.stutter")` | stripped drums, rolling 16th bass, a held pad; the stutter follows the chords and retriggers cleanly |
| Checklist O17 | "minimal", "minimal techno", then "tropical house" | four elements at most, space, the clap every other bar, the poly perc against the kick; tropical soft drums, shaker and bongos at 108, a bright C major pad, round sub |

## 7. Order and merging

One PR against `main`, merge commit only; Deck merges. O4 is cut from `main` after this merges.
