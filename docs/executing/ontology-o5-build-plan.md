# Whiplash ontology O5 build plan (v0.9.4)

Status:
- **Plan for O5**, the last phase of [ontology-v1-spec.md](ontology-v1-spec.md) §9: taste polish. Branch `feat/ontology-o5`, cut from `main` at `6692a28` (O4 merged, PR #30).
- O5 ships as **v0.9.4**.
- Nothing here has been tested on a real Digitakt II. Every **HW** item in §6 is a check for Phil's Air, not a result.

Inputs:
- **Spec:** [ontology-v1-spec.md](ontology-v1-spec.md). This plan's scope is §9's O5 row ("listen data in reviews, threshold tuning from Phil's sessions, hint wording"), with §7.2 (the **Heard** metrics, the thresholds, the hint examples), §7.3 (the review shape, `taste_hint`), §7.5 (tests), §8 (HW O-8) and §10 (Q-T1 to Q-T4).
- **Earlier phases:** [ontology-o1b-build-plan.md](ontology-o1b-build-plan.md) (the taste layer: `taste.py`, `bar_digest`, `changes`, `status(review)`, `taste_hint`), [ontology-o4-build-plan.md](ontology-o4-build-plan.md) (sections, which count as change).
- **Existing listening:** `listen.py` (v0.7.0): `analyse()` gives `loudness.clipping`, `bands.low.pct` and `low_end.masking`; `listen.summary()` is what `Engine.last_listen` keeps for status and the loudness guard.

**Goal of O5 (the demo sentence):** "How's it sounding?" after a `whiplash_listen` gets a review that also says what was *heard*: "Bass hits 4 kick steps per bar and the last listen heard the kick masked: try `whiplash_write_part(track: 6, phrase: 'bass.offbeat')`, or lower the bass with `whiplash_mix`." Every hint is one sentence that a weak model can turn straight into a call.

**Constraints** (spec §0, unchanged):
- No SysEx, program change, project, pattern, kit or +Drive writes. Slots 1-3 are never touched. `BLOCKED_CCS` / `BLOCKED_NRPNS` stay blocked. O5 sends **nothing**: it only reads what Whiplash already keeps.
- Clock-safe. No sequencer change at all: the listen data is kept by the tool thread that ran the listen, and the review reads it in the tool thread.
- **Never captured anew** (spec §7.2): a review never opens the audio device or the MIDI input. It only reads the last `whiplash_listen`.
- Feedback only (Q-T1): nothing in O5 changes the playing beat.
- **Demo-safe:** no musical call changes; the default `scripts/rehearse_demo.py` run stays `RESULT: PASS`.

## 1. Scope

| # | Item | Spec | Size |
| --- | --- | --- | --- |
| 1 | `listen.summary()` also keeps `masking`, `kick_over_rest_db` and `low_pct` (the low band's share); `Engine.record_listen` stamps the bar it was recorded on and the run it belongs to | §7.2 Heard | S |
| 2 | `whiplash_status(review)`: `listen` is filled from the last listen when it was taken while playing, in this run, and is under 32 bars old (`taste.LISTEN_BARS`); otherwise `null`, with a `listen_note` saying why when a listen exists | §7.2, §7.3 | S |
| 3 | Heard hints in `taste.hints`: `masking` (worded with the bass-on-kick count when there is one) and `clipping`. They also ride `taste_hint` once, like the others | §7.2 hints | S |
| 4 | Hint wording: every hint is one sentence in the same shape, every next step a real call in tool syntax, every named thing a library entry; energy only where the groove has levels; a filter sweep where automation is the arrangement; the busy hint names the track to mute | §7.2 hints | S |
| 5 | Threshold tuning: see §3.5. The table is pinned by a test so a tuned value is one deliberate edit | §7.2, Q-T2 | S |
| 6 | Version v0.9.4, skill, README, CHANGELOG, roadmap, hardware checklist and reference §15.1 / §15.3 | §1.6, §9 | S |

**Not in O5:** an autopilot (Q-T1, §11); a low-band hint (see §3.3); any new tool or schema property.

## 2. Engine shape

- **Recording.** `Engine.record_listen(result)` already runs in the listen's tool thread. It now also stores `bar` (`Engine.bar` when the listen was playing, else `None`) and `run` (a counter bumped on every fresh start, where `bar_digest` is cleared). Both are internal: `listen_status()` leaves them out, as it leaves out `at`.
- **Reading.** `Engine._taste_inputs()` copies `last_listen` under `_lock` with the rest. `taste.heard(listen, digest, run)` (pure) decides whether it applies and returns the compact `listen` block or a reason it doesn't.
- **No new per-bar work.** The sequencer is untouched.

## 3. Design notes and decisions

Researchable questions decided here from the spec; the PR lists them.

1. **"Under 32 bars old"** is counted in bars on Whiplash's clock: the last digest bar minus the bar the listen was recorded on. A listen taken while stopped, or during an earlier run (another beat), never applies: it heard something else. One taken 32 or more bars ago is reported as stale (`listen_note: "the last listen is 40 bars old; whiplash_listen again for heard checks"`).
2. **The review's `listen` block:** `{bars_ago, clipping, masking, kick_over_rest_db, low_pct, lufs_ish, peak_dbfs}`. `masking` and `kick_over_rest_db` are `null` when the listen couldn't judge the low end (fewer than two kicks heard); `low_pct` is `null` for a silent listen.
3. **Heard hints.**
   - `masking` fires when the listen heard the kick masked. With bass hits on kick steps (`low_collisions` ≥ 1) it says how many per bar and suggests an off-beat bass phrase (`bass.offbeat`) on the bass track, or lowering the bass with `whiplash_mix`; without collisions it suggests the mix only (the clash is in the samples' tails, not the steps).
   - `clipping` fires when the listen heard clipping: lower a level with `whiplash_mix`, then listen again (the loudness guard refuses raises until a listen shows none).
   - **No low-band hint.** The spec lists `bands.low` as a heard metric, not a hint, and no source gives a per-genre low-band share; a number by ear would be a guess on Phil's monitors. The review reports `low_pct` for the model to read, and the hint can come once Phil's sessions give a range.
4. **Hint wording** (one shape for every hint: what, against which limit, then "try" and two to four calls):
   - Repetition: `"8 bars unchanged in tech house, which wants a change every 8: try whiplash_mutate(action: 'energy', amount: 'up'), whiplash_mutate(action: 'fill', fill: 'kick.sit_out'), whiplash_write_part(groove: 'perc.woodblock') on a free track, or whiplash_write_part(phrase: 'bass.bouncy')."`
   - The energy step is offered only when the groove playing has levels: `up` below 5, `down` at 5, `whiplash_play_pattern(groove: '<genre's default groove>', energy: 4)` when no groove is set yet, and for `soul` and `breaks` (one level) `whiplash_mutate(action: 'density', amount: 'thicken')` instead.
   - **A filter sweep** (`whiplash_ramp_param` on a chord or bass track's `filter_freq`) is offered in the genres where the research says automation is the change: deep house (§1, "if filter or perc evolve"), progressive house (§4), melodic techno (§8), techno (§5) and both minimal presets (§6). Ramps already count as change (Q-T4), so the hint and the counter agree.
   - Busy: `"Busy for minimal house: 6 drum elements, and minimal house holds 4: try whiplash_mute_track(track: 8), the busiest drum after the kick, or whiplash_mutate(action: 'energy', amount: 'down')."` The track is the non-kick drum track with the most hits in the window (`metrics.busiest_drum`). The energy step follows the same levels rule.
5. **Threshold tuning.** The spec's O5 row says "threshold tuning from Phil's sessions". **No session results are recorded yet:** checklist O9 (HW O-8) and every other Part O check are untested in `reference.md` §15.3 (Q39). So the §7.2 numbers stay exactly as they are (tech house 8; tropical, progressive and melodic 16; deep house and house 32; techno and minimal 64; busy caps 4-7), and the PR says so. What O5 adds is a test that pins the whole table per genre, so a value tuned after Phil's session is a deliberate one-line change in `genres.py` that the test diff shows. The 32-bar listen age is one constant too.
6. **`taste_hint` with heard hints.** A heard hint fires once on the next musical result after the listen, like the others. `whiplash_listen` itself is not a musical call and already carries its own `notes`, so it doesn't repeat them.

## 4. Tools and budget

No new tool and no schema change: `whiplash_status(review)` keeps its description ("review: N bars of what changed, plus too-repetitive or too-busy hints. Feedback only."); the skill documents the `listen` block. The budget caps in `tests/test_v053.py::test_description_size_budget` don't move. 26 tools, unchanged.

## 5. Tests (fake and virtual ports only)

New `tests/test_v094.py`:
- **Pure:** `summary()` keeps masking, `kick_over_rest_db` and `low_pct` (and `null`s for a silent or kick-less listen); `taste.heard` applies a listen under 32 bars old, reports 32 or more as stale, and ignores one taken while stopped or in another run; the `masking` hint fires only with heard masking, names the collision count when there is one and suggests `bass.offbeat`; the `clipping` hint fires only with heard clipping; every hint in every genre names only calls that exist (`schemas.SCHEMAS`) and entries `library.resolve` finds; soul and breaks never get an energy step; the filter sweep appears exactly for the six genres; the busy hint names the busiest non-kick drum track; the threshold table is pinned per genre.
- **Engine (`pretend_playing`):** a listen recorded at bar 3 appears in `status(review: 8)` at bar 9 with `bars_ago` 6 and its masking hint; 32 bars later it is gone with a `listen_note`; after a fresh start it no longer applies; the review sends nothing and never opens the audio device or the input; a heard hint rides `taste_hint` once; `status` still hides the internal `bar` and `run`.
- **Unchanged:** the O1b taste tests keep passing with the new wording (updated where they pinned old text); the rehearsal stays `RESULT: PASS`.

## 6. Phil's hardware checks (O5)

From spec §8 (HW O-8, extended to the heard data). They go into `docs/testing/hardware-checklist.md` Part O (O21) and `reference.md` §15.1 #43 and §15.3 (Q52) as open questions. No result is claimed.

| # | Check | Listen for |
| --- | --- | --- |
| HW O-8 (checklist O21) | "Play tech house", "listen for 2 bars", then "how's it sounding?" with the bass level up; then again with the bass down | the review quotes what the listen heard (masked kick or not, clipping or not, the low band's share), the hint names a real next move (`bass.offbeat`, a lower bass level), and Hermes changes nothing by itself |
| Checklist O21, part 2 | Thresholds by ear: does 8 bars feel like the moment tech house needs a change, 32 for deep house, 64 for techno and minimal? | the numbers to tune, per genre, recorded in `reference.md` with the date |

## 7. Order and merging

One PR against `main`, merge commit only; Deck merges. O5 closes the ontology v1 build.
