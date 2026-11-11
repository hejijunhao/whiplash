# Whiplash v0.6 build plan

Status: **v0.6.0 shipped in this PR** (item 1: keys, scales, chord progressions). v0.6.1 (arrangement, plus the v0.5.3 fill follow-up) and v0.6.2 (transitions and mix levels) are not started. Nothing in v0.6 has been tested on a real Digitakt II yet; the hardware checks below are for Phil's Air.

- **Branch:** `feat/v06-keys`, cut from `main` at `caf2209` (v0.5.3 merged, PR #12).
- **Input:** the v0.6 section of [roadmap.md](roadmap.md), the open v0.5.3 follow-up in [reference.md](../digitakt-ii/reference.md) §15.1 #26, and Phil's instruction of Nov 11 2026 to keep building toward 1.0. Phil was asleep, so the orchestrator took the scope decisions listed in §5 on his behalf. Each one can be reverted.
- **Goal of v0.6 (the demo sentence):** "Hermes plays a whole track: intro, build, drop, outro, in key."

## 1. Priorities at a glance

v0.6 ships as three PRs, each with its own demo, in dependency order.

| PR | Item | Size | Depends on |
| --- | --- | --- | --- |
| **v0.6.0** | 1. Keys and scales on `whiplash_play_pattern` and `whiplash_write_part`; `whiplash_set_progression` | M, ~1 day | v0.5 register, `write_part`, kit map |
| v0.6.1 | 2. `whiplash_arrange`: sections on bar lines, presets `club` and `short_demo` | M-L, 1.5-2 days | v0.6.0 (sections can change chords), existing switch/drop/fill/ramp |
| v0.6.1 | 3. Fills follow the kit map (the v0.5.3 follow-up: drum parts moved off tracks 1-5 lose their fills) | S, ~2 h | v0.5.3 kit map |
| v0.6.2 | 4. DJ-style transitions on a queued switch: `cut`, `filter_swap`, `drop_swap`, `riser` | M, ~1 day | v0.6.1 sections (a section change can carry a transition) |
| v0.6.2 | 5. `whiplash_mix`: track level (CC 95) and pan (CC 90) in one call, named mix snapshots | S, ~half a day | none; sections recall snapshots after v0.6.1 |
| later | 6. More genres (minimal, breaks variants, dub techno) | S each | v0.6.0 home keys |

Item 6 stays out of the three PRs. Each new genre needs a home key and must pass the register test, so it is cheap to add after v0.6.0, one PR per genre.

## 2. Sources

- **[M]** *Elektron Digitakt II User Manual*, OS 1.17 (see [docs/digitakt-ii/README.md](../digitakt-ii/README.md) for the link and hash), with page numbers.
- **[G]** [midi.guide Digitakt II](https://midi.guide/d/elektron/digitakt-ii/).
- **[R]** [docs/digitakt-ii/reference.md](../digitakt-ii/reference.md), the canonical device reference. v0.6.0 adds §6.4 (voices per track), §15.1 #28-29 and §15.3 Q12-13.

Every claim marked **HW** needs a check on the unit.

---

## Item 1 (v0.6.0): keys, scales and chord progressions

**Problem.**

- **No key.** Each genre is hard-wired to one key: deep house, soul and tech house in A minor, techno in F minor, breaks in G minor. "Play techno in A minor" can only be approximated with per-track transposes, which move the drums' note-60 hits too if the agent isn't careful, and don't change the scale.
- **No harmony over time.** Chord tracks loop the same 4-bar line forever. "i-VI-III-VII, two bars each" means writing four parts by hand, which the 4-bar loop can't even hold when the progression is 8 bars long.
- **Bass and lead don't follow.** A written chord change leaves the bass on its old root.

**Constraint found while planning (source [M], recorded in [R] §6.4).** The manual gives the Digitakt II **16 stereo audio voices** for its 16 tracks (p. 15), and documents chords of up to four notes **only for MIDI tracks** (p. 17; GRID and LIVE RECORDING, p. 42-43; the MIDI machine's NOT2-NOT4, p. 101-102). Nothing describes an audio track sounding more than one note at a time. So a 3-note chord sent on one audio track's channel probably sounds as one note. This changes the design: a chord has to be spread across tracks or hits, not stacked on one channel. This is an interpretation, so it is HW (Q12).

**Change.**

1. **`key` and `scale` on `whiplash_play_pattern`.**
   - Every pattern gets a home key (`patterns.HOME_KEYS`). `harmony.in_key()` moves the melodic tracks there by scale degree. It takes the smallest tonic move (−6..+5 semitones), maps each note to the same degree of the new scale, and keeps a note outside the home scale (deep house's G#) as the same offset from its neighbouring degree. Then `patterns.register()` runs again, so the v0.5 register rule still holds. Drum tracks (note 60 only) are never touched.
   - The key applies from the first bar of a fresh start, or at the switch bar of a queued switch. Once set, it stays for the rest of the run: a later switch without `key` plays the new pattern in the same key. `whiplash_stop` resets it, like transposes.
   - Results and `whiplash_status` show `key` (and `key_source`: `set` or `pattern`); `queued.key` shows the key the queued pattern will play in.
2. **`whiplash_write_part` scale degrees.** Degrees with `key`/`scale` already shipped in v0.5.1. v0.6.0 adds `key: "current"`, which uses the key the beat plays in, so a melody written after "play it in F minor" doesn't have to repeat the key.
3. **`whiplash_set_progression(chords, bars_per_chord, voicing, key, scale, tracks, clear)`.**
   - `chords`: Roman numerals in the key (`"i VI III VII"`, `"ii7 V7 Imaj7"`, `"bVII"`; upper case = major, lower = minor; suffixes 7, maj7, dim/°, dim7, ø, aug/+, sus2, sus4, add9, 5), or chord names (`"Am F C G7"`). A list, or one string split on spaces, commas, dashes (including en dashes) and bars. 1-16 chords.
   - `bars_per_chord` 1-16 (default 1). The progression loops, and it is counted from its own start bar, so an 8-bar progression plays across the 4-bar pattern loop correctly.
   - `voicing`: `close` (default: every inversion considered, the one that moves least from the previous chord, nudged toward note 62), `root`, `open` (root, fifth, third and seventh an octave up), `power` (root, fifth, octave). Every voicing's median stays at or above 53, the v0.5 register floor, and every note stays in 16-84.
   - **Bar-quantized:** it starts on the next bar line. The bar already playing is never changed. A new `key` moves the pattern into that key at the same bar.
   - **Track modes, picked from roles** (the kit map label, else the routed pattern's role): chord, pad and stab tracks → `chords`; bass → `root`; lead → `snap`. Kick, snare, rim, clap, hats, cymbal, perc, fx and unknown roles → never changed.
     - `chords`: one chord tone per hit, walking down the voicing, and each chord track starts on a different tone. Two or three chord tracks hitting together sound the chord across tracks, and one chord track plays a voice-led line of chord tones. This works on a one-voice track.
     - `stack`: every tone on every hit. Opt-in only (MIDI-machine tracks, or if Q12 shows audio tracks layering).
     - `root`: each hit plays the chord root, in the octave nearest the line's own median, so the v0.5 register is kept.
     - `snap`: each note moves to the nearest scale note (ties go down).
   - `tracks` overrides a mode per track (`{"9": "chords", "6": "off"}`). It is **refused on any drum, cymbal or fx track**, so chords never land on a cymbal, whatever the request.
   - A chord or pad track with no line at all (a labelled pad that got no generated part) holds one chord tone per bar.
   - **Written parts play as written** unless `tracks` names them. The result lists them under `written_unchanged`.
   - Transpose, mutes, drops, fills, density and humanize still apply on top. The progression carries across pattern switches and `whiplash_mutate reset`. `clear: true` or `whiplash_stop` ends it.
   - Everything is validated before anything changes. Nothing is sent when the call is made: chords are note numbers rewritten at the bar line. No CC, no SysEx, no program change, and the unit's own KB SCALE / ROOT NOTE are not touched.
4. **Status.** `whiplash_status` gains `key`, `key_source` and `progression`: the chords and names, key, bars per chord, voicing, loop length, start bar, `now` (current chord and the bar of the next change), the per-track modes and every voiced chord with note names. `tracks[n].progression` gives each track's mode.
5. **Clock safety.** All parsing and voicing happen in the tool call. At the bar line the sequencer only looks up the chord for that bar and rewrites at most 64 hits per track (`harmony.apply`). Re-keying a pattern at a bar line costs about as much as the v0.5.3 kit-map reroute (dicts over at most 16 tracks × 4 bars).

**Tests** (`tests/test_v060.py`, plus small updates to the tool-count, manifest-order and description-budget tests):

- Key parsing and naming (flats in flat keys), bad keys refused.
- Every pattern's lines fit its home key (G# allowed as the leading tone).
- `in_key` for every genre into five keys: same rhythm and hit count, in-scale notes stay in scale, register floor kept, drums untouched. Degree mapping examples (A minor → C major turns C into E).
- Snap (tie down, stays in 16-84) and nearest-root.
- `play_pattern(key=...)` on the wire: the bass plays the new root, the kick stays on 60. A queued switch keeps the session key, a queued `key` lands at the switch, and stop resets it. A bad key changes nothing and sends no CC.
- Chord parsing: numerals in major and minor keys, accidentals, suffixes, names; splitting on dashes; bad input refused.
- Every voicing holds exactly the chord's pitch classes (power: root and fifth), stays in range, and has its median at 53-70. Close voicings move less than root position.
- Progression: lands on the next bar, changes every `bars_per_chord` bars, loops. The bass plays the roots, chord tracks only chord tones, one per hit, with different tones on different tracks. `stack` sends whole chords. Drums are unchanged, and the lead snaps to the scale.
- Kit labels: a pad on track 9 gets `chords`, a cymbal gets nothing, and overrides on a cymbal or kick are refused. `off` works. A chord track with no line holds a tone per bar.
- Written parts are unchanged unless named. The progression carries across a switch and `mutate reset`, `clear` and stop end it, and transpose applies on top.
- The status block: `now`, next change, per-track mode. The tool round trip, and schemas within the description budget.
- Bad input of every kind (numerals, bars_per_chord, voicing, modes, tracks, key, `clear` with other args) leaves the progression, key and port untouched.
- **Clock jitter unchanged** with a 6-chord open-voiced progression, two stacked 16th-note chord tracks, a `chords` track and a `snap` track (same p95 bound as v0.5.1's 8-written-parts test).

**HW checks** (Phil's Air; see the PR for the exact prompts):

- HW 6.0-1: deep house in A minor, i-VI-III-VII, two bars per chord, pads on track 7. The chord changes every 2 bars, on the one. Track 6 plays the roots. Nothing sounds out of key against a held A minor note in KB mode.
- HW 6.0-2 (Q12): `tracks: {"7": "stack"}`. How many notes of the chord does one audio track sound?
- HW 6.0-3 (Q13): with chord tracks 7 and 8 in `chords` mode, does each hit sound like the chord across both tracks?
- HW 6.0-4: label track 7 as a cymbal, then ask for chords on it. Hermes refuses, and the cymbal keeps playing what it played.
- HW 6.0-5: "Play techno in A minor". The bass moves from F to A, the drums sound unchanged, and there is no stretched or grainy bass (the register check).

**Risks.**

- If Q12 shows audio tracks *do* layer notes, `chords` is thinner than it could be. Then `stack` becomes the default for chord tracks, a one-line change in `harmony.ROLE_MODES`.
- A chord track's sample is usually pitched (a pad or chord sample). A pad sample that already holds a full chord gets one note per hit, so each chord tone plays the whole sampled chord transposed. That is the "chord sample" style, and the user can say `off`.

---

## Item 2 (v0.6.1): arrangement

**Problem.** The demo sentence needs an intro, build, drop and outro. Today Hermes would have to time every drop, fill, ramp and switch itself, turn by turn, and turns take 5-40 s.

**Change.**

- `whiplash_arrange(sections: [{name, bars, tracks, mutes, chords, ramps, fill, transition}], loop: false)`. Each section is a set of active tracks (others muted), optional ramps, an optional fill on its last bar, and optionally its own progression (item 1).
- It schedules existing primitives on bar lines: mutes and unmutes, `schedule_drop`, `schedule_fill`, ramps started at the section's first bar, and a progression swap. There is no new clock path. The sequencer gains one per-bar check: "does a section start here?", a dict lookup.
- Presets: `club` (intro 16 / build 8 / drop 16 / break 8 / drop 16 / outro 16) and `short_demo` (60-90 s at the genre's tempo).
- Status shows the current section, the bars left in it, and the next section. `whiplash_stop` or `arrange(clear: true)` ends it. With `loop: false` the last section ends the run cleanly (stop on its last bar line).
- Validated in full before anything is scheduled.

**Tests:** sections land on their bar lines. Mutes and unmutes happen at section boundaries only. Ramps start on the section's first bar. The preset bar counts are exact. Status shows section, bars left and next. A bad section changes nothing. Clock jitter is unchanged.

**HW check:** "Make it a 90-second track: intro, build, drop, outro." Tracks enter in sections, the build has a rising filter, the drop lands on the one, and the outro thins out and stops cleanly.

## Item 3 (v0.6.1): fills follow the kit map (v0.5.3 follow-up)

**Problem.** `mutate.fill()` and `schedule_fill` are keyed to tracks 1-5 (kick, snare, clap, closed hat, open hat). Since v0.5.3, a kick labelled on track 9 receives the kick part but no fill, and `whiplash_mutate fill` refuses tracks above 8 ([R] §15.1 #26). Arrangement sections end on fills, so this has to be fixed in the same PR.

**Change.** Fill shapes are chosen by role, not track number. `mutate.fill(role, hits)` takes the routed role (kick, snare/rim, clap, closed hat, open hat; cymbal gets the open-hat shape, perc gets the clap push). `schedule_fill(tracks)` defaults to every track whose role is a drum role, and accepts tracks 1-16. A non-drum track is refused.

**Tests:** a kick labelled on track 9 gets the kick fill. The default fill covers the routed drum tracks. Fills on a melodic track are refused. With no labels, the existing fill tests pass unchanged.

**HW check:** label the kick on track 9 and ask for a fill. Track 9 sits out the last beat.

## Item 4 (v0.6.2): DJ-style transitions

**Change.** A queued switch, or a section change, takes `transition: "cut" | "filter_swap" | "drop_swap" | "riser"` and `transition_bars` (1-8, default 4).

- `cut`: today's behaviour.
- `filter_swap`: ramps the outgoing tracks' filter cutoff down over N bars, switches on the one, then ramps the incoming cutoff back to where it was. It uses the existing ramps, and only the last value sent is known (the same rule as ramps: give `from` when Whiplash hasn't sent the cutoff yet).
- `drop_swap`: drops the low end (bass and kick) for the last bar, then switches.
- `riser`: a fill plus a rising ramp on a user-labelled fx or riser track, if one is labelled.

Everything is built from ramps, drops and fills, so there is no new clock path.

**Tests:** each transition's CCs and drops land on the right bars. The switch still lands on the one, with no Stop/Start. The ramps are cancelled cleanly if the user stops.

**HW check:** "Switch to breaks with a filter swap over 4 bars." The outgoing highs close over 4 bars, and breaks lands on the one with no click.

## Item 5 (v0.6.2): mix levels

**Change.** `whiplash_mix(levels: {"1": 110, "6": 95}, pan: {"4": 40}, save_as, recall)`. Level is CC 95 (TRACK LEVEL) and pan is CC 90, per track ([M] Appendix B, B.1 and B.5, p. 109-110; [G]; already in `ccmap` as `track_level` (alias `level`) and `pan`). All CCs go out in one call. Named snapshots ("drop mix") hold the last values Whiplash sent, and `recall` sends exactly the stored values (sections can recall them after v0.6.1). A level change replaces a running ramp on the same param, like `set_param`.

**Tests:** one CC per change, snapshot round trip, recall sends only what differs from the last value sent, and bad input sends nothing.

**HW check:** "Bring the bass down a bit and pan the hats left." Track 6's LEVEL moves on the unit's screen, the hats move left, and nothing else changes. "Save this as the drop mix, then go back to it after the break": the levels snap back exactly.

---

## 3. Summary of HW checks (on Phil's Air only)

| # | Check | Item |
| --- | --- | --- |
| HW 6.0-1 | i-VI-III-VII in A minor, 2 bars per chord: chord changes on the one, bass on the roots, nothing out of key | 1 |
| HW 6.0-2 | One audio track, 3 stacked notes: how many sound? ([R] §15.3 Q12) | 1 |
| HW 6.0-3 | Two chord tracks in `chords` mode sound the chord across tracks (Q13) | 1 |
| HW 6.0-4 | A cymbal-labelled track never gets chords | 1 |
| HW 6.0-5 | "Techno in A minor": bass moves to A, drums unchanged, register fine | 1 |
| HW 6.1-1 | 90-second arrangement: sections, build, drop on the one, clean outro | 2 |
| HW 6.1-2 | Fill on a kick labelled on track 9 | 3 |
| HW 6.2-1 | Filter swap over 4 bars, no click | 4 |
| HW 6.2-2 | Level and pan land on the right tracks; snapshot recall is exact | 5 |

Constraints throughout:

- No SysEx, no program change, no project/pattern/kit writes, and never touch Digitakt slots 1-3.
- The blocked CCs stay blocked (bank select, CC 24, NRPN data, sample NRPNs).
- Every change is bar-quantized and timed on Whiplash's clock. The sequencer thread never enumerates ports or takes `_transport`.
- Bad input never changes the beat.
- A jitter test for every sequencer change.

## 4. Order and merging

Merge order: v0.6.0 → v0.6.1 → v0.6.2. Each PR is cut from `main` after the previous one merges, uses merge commits only, and Phil merges. The visualiser (`view.py`, `view.html`) isn't touched in v0.6.0. Showing the key, chord and section in the view is a follow-up for the visualiser agent, through `view_state()`.

## 5. Decisions taken for v0.6.0 (on Phil's behalf; each is reversible)

1. **Chord tracks default to one chord tone per hit (`chords`), not stacked chords.** Why: [M] p. 15 and p. 17 imply one voice per audio track. `stack` is opt-in, and Q12 decides whether to flip the default.
2. **Written parts are not changed by a progression unless named in `tracks`.** Why: a written part is something the user asked for note by note.
3. **The session key sticks across switches until stop**, like transposes. A progression sets it too.
4. **Drum, cymbal, perc and fx tracks can never follow a progression,** even when asked explicitly. This matches the v0.5.3 rule that a cymbal never gets a melodic line.
5. **`set_progression` needs a pattern playing**, like `write_part` and `transpose`. There is no `progression` argument on `play_pattern` yet, so it is two calls. This keeps the tool descriptions inside the budget.
6. **Tool-description budget:** the per-tool and total tool-description caps stay (≤400 and ≤3000 characters). The params and JSON caps go up by about 700 characters and 1.5 KB for the new tool.
