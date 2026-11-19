# Whiplash ontology O2 build plan (v0.9.1)

Status:
- **Plan for O2**, the third phase of [ontology-v1-spec.md](ontology-v1-spec.md) §9: harmony intents and keys. Branch `feat/ontology-o2`, cut from `main` at `7d6da5d` (O1b merged, PR #27).
- O2 ships as **v0.9.1**.
- Nothing here has been tested on a real Digitakt II. Every **HW** item in §6 is a check for Phil's Air, not a result.

Inputs:
- **Spec:** [ontology-v1-spec.md](ontology-v1-spec.md). This plan's scope is §9's O2 row. The layer section is §3 (harmony: §3.2 intents, key lock, auto-follow; §3.3 tools; §3.4 scheduler; §3.5 tests), plus §5.5's key-change line, §8 and §10 (Q-H2, Q-H3).
- **O1a / O1b:** [ontology-o1a-build-plan.md](ontology-o1a-build-plan.md) (key lock, `set_progression(name)`, the shell rule), [ontology-o1b-build-plan.md](ontology-o1b-build-plan.md) (phrases, the fallback progressions, taste).
- **Device reference:** [reference.md](../digitakt-ii/reference.md) §6.1 (note 60, native pitch, 16-84), §6.4 (one voice per audio track).

**Goal of O2 (the demo sentences):** "darker" turns A minor into A phrygian on the next bar, and says which other kinds of darker it could have done. "Make it brighter, but with the filters" opens the melodic tracks' cutoff a step, never past where it was. "More tension" puts a dominant 7th at the end of the loop, then a 9th, then a bass pedal; "release" brings the exact progression back. "Change key to F minor" moves everything melodic on the next bar, chords and phrases included. And a written melody can follow the chords with `follow: true`.

**Constraints** (spec §0, unchanged):
- No SysEx, program change, project, pattern, kit or +Drive writes. Slots 1-3 are never touched. `BLOCKED_CCS` / `BLOCKED_NRPNS` stay blocked. The only CC O2 sends is `filter_freq` (CC 74, already in use), and only for `how: "timbral"`, only on melodic tracks.
- Clock-safe. Every intent and key change is parsed, voiced and routed in the tool thread. At the bar line the engine only assigns what was prepared (key, progression, routed pattern, transposes), sends at most one CC per melodic track (timbral), and rebuilds working lines as a relabel does. The `pedal` mode is one `nearest()` per hit, like `root`.
- **Drums are never pitch-corrected.** Intents, key changes, `pedal` and `follow` touch only bass, lead, chord, pad and stab tracks; `follow` and the timbral step are refused or skipped on drum, cymbal and fx tracks.
- **Demo-safe:** nothing changes unless an O2 argument is given. `set_progression(chords | name)` and every pre-0.9.1 call play bit for bit as before (equivalence tests).

## 1. Scope

| # | Item | Spec | Size |
| --- | --- | --- | --- |
| 1 | `harmony.mode_shift` (a chord moved degree by degree into another mode), the mode ladder (`lydian → major → mixolydian → dorian → minor → phrygian`), `harmony.transpose_chord`, `harmony.thin` | §3.2 | S |
| 2 | Track mode `pedal`: the key's tonic under every chord, per hit, in the hit's own octave | §3.2, §3.4 | S |
| 3 | `progressions.INTENTS` and the pure intent planners: library swap by `brightness` and shared tags, mode step, tension steps, release | §3.2 | M |
| 4 | `set_progression(intent, how)`: `darker` / `brighter` with `harmonic` (default), `timbral`, `register`, alone or combined; `tension`, `release`; results name what was applied and the other options | §3.2, §3.3 | M |
| 5 | Key-only `set_progression(key, scale)`: changes the key from the next bar (it used to error "give chords"); Roman progressions re-voiced, chord names shifted | §3.3, §3.4 | M |
| 6 | `set_progression(lock: true \| false)`: key lock on or off for the session | §3.2 | S |
| 7 | `write_part(follow: true \| mode)`: a written melodic part follows the progression (`snap` by default) and the key | §3.2 | S |
| 8 | `whiplash_undo` restores intents and key changes: progression, key, the CC values sent, the lead register | §3.2 | S |
| 9 | Skill, README, CHANGELOG, roadmap, budget pins, hardware checklist and reference §15.3 | §1.6, §9 | S |

**Not in O2:** the other four genres, their progressions and phrases (O3); forms and moves (O4); listen data in reviews (O5); slash chords (§11).

## 2. Engine shape

- **One pending slot, `Engine._harmony_next`,** like O1a's `_energy_next`: `{at, key, prog, routed, transpose, ccs, ...}` prepared in the tool thread, applied in `_bar_boundary` before the relabel check. The spec (§3.4) describes this as a timed action of kind `call`; a slot is the same thing at the same bar line, and lets two calls in one bar compose (a second `darker` builds on the pending one instead of on what still sounds). The bar line does assignments, at most one CC per melodic track, and the relabel path's rebuild.
- **A plain `set_progression(chords | name | clear)` replaces a pending intent** and says so (`replaced_pending`). A queued pattern switch landing first just means the prepared routing is redone at the bar line (`_routed` is the cheap relabel path).
- **`whiplash_undo`** gains kind `harmony`: it restores key, progression, tension state, the lead transposes and the `filter_freq` values Whiplash sent before the step, at the next bar line.
- **Lock** is a session setting (`Engine.key_lock`, default on). It survives `whiplash_stop`, like the kit map, because "turn key lock off" is a preference, not a beat.

## 3. Design notes and decisions

Researchable questions were decided here from the spec and the research brief; the PR lists them.

1. **`harmonic` darker / brighter.**
   - With a library progression playing: swap to the same genre's entry (by name prefix) with the next lower (darker) or higher (brighter) `brightness`; ties go to the most shared tags, then the name. It starts on the next bar, like `set_progression(name)`.
   - With a hand-written progression, no progression, or a library entry already at its genre's floor or ceiling: step the mode one rung down (or up) the ladder `lydian → major → mixolydian → dorian → minor → phrygian`. The session key changes mode on the same root, so the pattern's melodic lines move by degree (`harmony.in_key`), and every chord moves degree by degree (`harmony.mode_shift`: in A minor → A phrygian, G7 becomes Gm7, Em becomes Edim, Am7 and Dm7 stay). Each chord keeps its place in the loop.
   - Phrygian is the floor and lydian the ceiling (locrian is never chosen). At the floor `darker` changes nothing and says so (`unchanged: true`). A scale off the ladder (harmonic or melodic minor, pentatonics, blues, chromatic) refuses the mode step with the other two options as the hint.
   - The spec's "lower the voicing register" is the `register` option's job; `harmonic` changes qualities and modes only, so the three options stay separable and each undo is exact.
2. **`timbral`.** One step of 16 on `filter_freq` (CC 74), on the melodic tracks playing (bass, lead, chord, pad, stab by role), at the next bar line. `darker` never goes below 24; `brighter` opens by the same step but never past each track's value before the first `darker` (`Engine._timbral_base`), so a `brighter` with no earlier timbral `darker` changes nothing and says so. Whiplash never guesses a cutoff, as `filter_swap` doesn't (v0.6.2): a melodic track whose `filter_freq` it never sent is skipped and named (`skipped`), and if no melodic track has a known cutoff the call is refused, with the fix (`whiplash_set_param` `filter_freq` first, or `how: "harmonic"`). Drum, cymbal and fx channels are never sent anything.
3. **`register`.** `darker` drops each lead track an octave (a −12 transpose on top of any the user set, skipped if a note would fall below 41) and thins the progression's highs (the top voice of each chord of three or more notes drops out). `brighter` undoes exactly what an earlier `register` darker did, and otherwise changes nothing and says so.
4. **`tension`, one step per call** (deterministic):
   1. the last chord becomes the key's dominant 7th (root a 5th above the tonic, major 3rd: `V7`, as harmonic minor gives it);
   2. it becomes a dominant 9th (`V9`);
   3. the bass takes mode `pedal` (the key's tonic under every chord).
   A further call says "already at full tension". With no progression playing, step 1 builds the tonic vamp with a dominant turnaround (`i i i V7`, a bar each), so there is a chord to pull.
5. **`release`** brings back the exact progression (or none) that played before the first `tension` and turns the pedal off. Nothing to release: "no tension to release; the progression is unchanged". A plain `set_progression` in between forgets the tension.
6. **Key-only `set_progression`.** `key` and/or `scale` without `chords`, `name` or `intent`. `scale` alone keeps the root. The new key lands on the next bar: the pattern re-keyed (`_routed(raw, key)`), a Roman-numeral or library progression re-parsed and re-voiced in the new key (a library entry through `progressions.key_for`), a chord-name progression shifted by the same interval as the pattern (−6..+5) and moved degree by degree when the scale changes. Phrases follow by construction (their fallback is warmed for the new key). `"already in A minor"` when nothing would change.
7. **`pedal`** is also a mode `set_progression(tracks)` may ask for. A bass phrase under the pedal keeps its octave bounce (each hit takes the tonic nearest its own note).
8. **`follow`.** `true` gives the written part mode `snap`; a mode name (`snap`, `root`, `chords`, `pedal`) picks another. With no progression it follows the key (and a genre's fallback progression, as phrases do). Refused on a drum, cymbal or fx track, with a lane (`groove`), with `out_of_key`, and with `phrase: ... follow: false` (a phrase always follows).
9. **Lock off** (`set_progression(lock: false)`) stops `write_part` snapping explicit notes; `lock` combines with any call, or stands alone. Results carry `lock`.
10. **Intents need a beat:** "start a beat first". `how` with `tension` or `release` errors "how is for darker or brighter". `chords`, `name` and `intent` are mutually exclusive; `intent` takes no `key`, `scale`, `bars_per_chord`, `voicing` or `tracks`.

## 4. Tools and budget

| Tool | Gains |
| --- | --- |
| `whiplash_set_progression` | `intent` (darker, brighter, tension, release), `how` (harmonic, timbral, register, or a list), `lock`; key-only calls; mode `pedal` in `tracks` |
| `whiplash_write_part` | `follow` (true, or a mode) |
| `whiplash_undo` | reverts intents and key changes |

Caps (`tests/test_v053.py::test_description_size_budget`) rise only as far as O2 uses (measured: tools 4,300, params 10,140, JSON 23,921 bytes): tools 4,250 → **4,300**, params 10,000 → **10,150**, JSON 23,600 → **23,950** bytes. All stay inside the spec's final targets (tools 4,350, params 10,300, JSON 24,000 bytes). 26 tools, unchanged.

## 5. Tests (fake and virtual ports only)

New `tests/test_v091.py`:
- **Pure:** `mode_shift` on every library progression in all 12 keys, both directions of the ladder (notes 41-79, median ≥ 53); A minor → A phrygian turns G7 into Gm7; the ladder ends at phrygian and lydian; library swap picks by brightness and tags, deterministically; tension steps; `pedal` mode plays the tonic per hit.
- **Intents (engine, `pretend_playing`):** `darker` from A minor goes to A phrygian on the next bar and is idempotent at the floor (the result says so); with no `how` it applies `harmonic`, sends no `filter_freq` and reports `applied: ["harmonic"]` and `other_options: ["timbral", "register"]`; `how: "timbral"` sends `filter_freq` only on melodic channels; `how: ["harmonic", "register"]` changes the mode and moves the lead down an octave within 41-79; `whiplash_undo` after each restores the progression, the CC values and the lead register; `brighter` after a timbral `darker` never opens past the earlier value; `tension` ×3 then `release` brings the exact previous progression back; every result names what it did; a library swap from `deephouse.gospel`.
- **Key-only:** `set_progression(key: "Fm")` lands exactly on the next bar line; drum notes unchanged; the bass median stays ≥ 53; a Roman progression is re-voiced and a named one shifted; `bass.octave_pump` (O1b) moves with it; "already in A minor"; a bad key echoes the parser.
- **Lock and follow:** `lock: false` lets C#5 through in A minor and `lock: true` snaps it again; `follow: true` makes a written line snap to each chord's key and follow a key change; refusals (`follow` on a kick, with `out_of_key`, with a lane) change nothing.
- **Refusals:** `intent` with nothing playing, `how` with `tension`, `chords` with `intent`, `release` with nothing to release: nothing changes (`status` before and after equal).
- **Equivalence:** the five hand-written genres and house play the same `bar_events` with and without the O2 code paths when no O2 argument is used.
- **Clock:** a bar-line cost check with `pedal` and a pending intent.
- **Budget** pins updated; the rehearsal stays `RESULT: PASS`.

## 6. Phil's hardware checks (O2)

From spec §8 (O-4, O-5 still open from O1) plus O2's own. They go into `docs/testing/hardware-checklist.md` Part O and `reference.md` §15.3 as open questions. No result is claimed.

| # | Check | Listen for |
| --- | --- | --- |
| HW O-9 | Deep house with `deephouse.gospel`, then "darker" (harmonic), "darker" again, then "brighter" | the chords and bass move on the one; the second darker swaps or steps the mode audibly; brighter comes back |
| HW O-10 | "darker, with the filters" (`how: "timbral"`), twice, then "brighter" twice | the melodic tracks close a step each time on the bar, drums untouched; brighter never opens past where it started |
| HW O-11 | "more tension" three times, then "release" | a dominant pull at the loop's end, then a 9th, then the bass pedal; release lands back on the old loop |
| HW O-12 | "change key to F minor" over Chicago house | everything melodic moves on the next bar, nothing stuck or doubled, drums unchanged |

## 7. Order and merging

One PR against `main`, merge commit only; Deck merges. O3 is cut from `main` after this merges.
