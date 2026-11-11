# Changelog

## Unreleased

Added
- **Offline demo rehearsal** (`scripts/rehearse_demo.py`). Runs the hackathon demo's tool calls (checklist Part A, A1-A9) through the real handlers and engine against a recording port, at real or accelerated clock, with no Digitakt or rtmidi. Writes a Standard MIDI File of everything sent (one track per channel, markers for steps, Start/Stop and bars), a per-step report (tracks sounded, CCs, bar landing, warnings) and every tool result. It fails (exit 1) on SysEx, program change, a blocked CC, a hanging note, clock jitter past the test suite's bound, or any Part A expectation the MIDI can show. `tests/test_rehearsal.py` runs it at 4x in CI. Linked from README and the demo script. Not a hardware test.

## 0.6.2

The third and last v0.6 PR: DJ-style transitions (item 4 of [docs/executing/v06-build-plan.md](docs/executing/v06-build-plan.md)) and mix levels (item 5). 20 tools. Nothing here has been tested on a real Digitakt II yet. The demo path (hardware checklist Part A) is unchanged: the arrange presets carry no transition or mix, and `scripts/rehearse_demo.py` still passes it.

Added
- **Transitions on a queued switch:** `whiplash_play_pattern(transition, transition_bars, filter_from)` while something plays. The transition runs from the next bar line over `transition_bars` (1-8) and the switch lands on the bar after it, with no Stop/Start (`transition.py`).
  - `cut`: the plain next-bar switch.
  - `filter_swap` (default 4 bars): every outgoing track except kick and bass ramps `filter_freq` (CC 74) down to 30, the switch lands on the one, then each cutoff ramps back to where it was over one bar. The start is the cutoff Whiplash last sent, else `filter_from`; with neither, the call is refused before anything changes.
  - `drop_swap` (default 1 bar): kick and bass sit out the last bar(s) and come back with the switch.
  - `riser` (default 4 bars): fx-labelled tracks (riser, sweep, noise) ramp `filter_freq` 20 → 127 (exp), and the drums fill the last bar. With no fx label it is the fill only, and the result says so.
  - Results carry `transition` (kind, bars, `starts_at_bar`, what it does, the tracks it touches, notes), status carries `queued.transition`. Replacing a queued switch cancels its transition (`replaced_transition`) and anything it closed reopens at the new switch. A fresh start ignores it (`transition_note`).
- **Transitions between arrangement sections:** a section's `transition` (+ `transition_bars`, `filter_from`) runs over its last bars into the next section. A cutoff Whiplash never sent is skipped and listed in `skipped_ramps`. `arrange(clear: true)` cancels a section transition in progress and reopens its cutoffs.
- **`whiplash_mix(levels, pan, preset, bars, save_as, recall)`.** TRACK LEVEL (CC 95) and PAN (CC 90) per track or group word, from the next bar line, or ramped over `bars` (1-32) on the clock (`mixer.py`).
  - Only values that differ from the last one sent go out, one CC per change. A track with no known value jumps on the bar line instead of ramping (`jumps`). A mix change replaces a running ramp on the same param.
  - Pan takes 0-127 or words (`left`, `hard right`, ...).
  - Presets set levels by role: `techno`, `techhouse`, `deephouse`, `breaks`, `soul`, `flat`, and `auto` (the genre playing). They never touch pan.
  - `save_as` stores the mix as it will be after the call; `recall` sends it back exactly. Saved mixes survive `whiplash_stop`. With nothing playing the CCs go out at once (no ramp).
  - Status carries `mix` (levels and pan last sent, saved names). An arrangement section's `mix` recalls a saved mix or a preset on its first bar.
- `whiplash_stop` mid-transition puts each closed cutoff back with one CC after the panic, and says so (`cutoff_restored`).

Changed
- **One timed-action path** in the sequencer: `_timed` holds ramp starts and mix CCs keyed by bar, run at that bar line with a dict lookup. Ramps carry an `owner`, so a transition can be cancelled without touching the user's own ramps. No new thread, no new lock, no port enumeration in the clock thread.
- `arrange.py` drops the "transitions come in v0.6.2" refusal: `transition`, `transition_bars`, `filter_from` and `mix` are section keys. The `club` and `short_demo` presets are unchanged.
- Tool descriptions were trimmed again (`whiplash_list_params`, `whiplash_ramp_param`, `whiplash_stop`) to fit `whiplash_mix` inside the unchanged 3,000-character total and 400-character per-tool caps. The params and JSON budgets rise to 7,800 characters and 19,000 bytes.
- Version 0.6.2 in `pyproject.toml`, `plugin.yaml`, `docs/catalog-entry.yaml` and `__init__.py`. `whiplash_mix` is added to `provides_tools` in both manifests, after `whiplash_arrange`. The skill gains Transitions and Mix sections and diagnostics rows.
- Reference: new §15.1 #32-33 and §15.3 Q15-17.

Not touched: `docs/testing/hardware-checklist.md`, `docs/demo/`, `scripts/`, `view.py`, `view.html` (owned by the visualiser agent). The PR lists the new hardware checks.

## 0.6.1

The second v0.6 PR: arrangement (item 2 of [docs/executing/v06-build-plan.md](docs/executing/v06-build-plan.md)), fills that follow the kit map (item 3, the open v0.5.3 follow-up), and the review follow-ups from PRs #15 and #16. 19 tools. Nothing here has been tested on a real Digitakt II yet. The demo path (hardware checklist Part A) is unchanged, and `scripts/rehearse_demo.py` still passes it.

Added
- **`whiplash_arrange(sections | preset, seconds, loop, clear)`.** It plays the beat as a song from the next bar line.
  - **Sections:** name, `bars` (1-64), `tracks` that play (others are muted by Whiplash, never with CC 94) or `mute`, `ramps` started on the first bar, `fill` and `drop` on the last bar, and `chords` (+ `bars_per_chord`) to swap the progression. Up to 16 sections and 512 bars.
  - **Group words:** tracks are numbers or groups (`all`, `drums`, `kick`, `hats`, `perc`, `bass`, `music`, any kit role). Each section resolves them again at its first bar, so an arrangement follows a switch or relabel.
  - **Presets:**
    - `club` is intro 16 / build 8 / drop 16 / break 8 / drop 16 / outro 16.
    - `short_demo` is intro, build, drop (with a break when it is long enough) and outro, about 75 s at the current tempo (`seconds` 30-600), in 4-bar phrases.
    - The build's filter rises 20 → 127 on the music tracks while the kick sits out its last bar. Every section but the outro ends on a fill.
  - **Ending:** with `loop: false` (the default) the run stops cleanly on the bar line after the last section. `clear: true` ends the arrangement and unmutes what it muted. `whiplash_stop` ends it too.
  - **No new clock path:** it schedules existing mutes, drops, fills, ramps and progressions. The sequencer only looks up "does a section start here?" once per bar. Everything is validated before anything is scheduled.
  - **Status:** `arrangement` gives the sections, `current` (section, `bars_left`, `next`, `next_at_bar`), `skipped_ramps` and `muted_by_arrangement`. A queued play result carries `arrangement_carried`.
- **`routing` on every `whiplash_play_pattern` result** (fresh start and queued switch) and in `whiplash_status`. When the kit map routes a generated part onto tracks 9-16, or `tracks` setup names one, the result carries `channel_note` and `tracks_9_16` (also on `whiplash_label_tracks`).
- **`routing.vacated`** reports an unlabelled default track that a label emptied (labelling 7-8 "tuned cymbal" moves the open hat off track 5), with a `vacated_note` for the user. This only reports it. Whether it should happen is an open design question for Phil (reference §15.1 #26).
- `whiplash.__version__`.

Changed
- **Fills follow the kit map** (`mutate.fill(role, hits)`, `schedule_fill`). A kick labelled on track 9 gets the kick fill. Cymbal gets the open-hat shape and perc the clap push. A fill with no tracks covers every kick, snare/rim, clap and hat track playing, and cymbal and perc only fill when named. Tracks 1-16 are accepted, and melodic tracks are refused. With no labels the fills are exactly as before.
- **Written parts in routing.** A track playing a written part is never a routing target. The generated part goes to the next matching label, or `routing.replaced_by_written` (and `replaces_generated` on the write_part result) reports it. Before, a routed bass under a written part was silently lost. Writing or resetting a part re-routes at once.
- **Relabelling while playing moves transpose and density with the part** (`follows_part` in the result). A part routed nowhere drops its settings instead of leaving them for the next part on that track.
- **Queued play results show their own setup:** `tracks` include the switch's slot, tune (also in `pitch`), transpose and mutes, marked `setup_at_switch`, and `muted_at_switch` lists the mutes after the switch.
- **No second panic before a fresh start.** A fresh `whiplash_play_pattern` after a stop sent All Notes Off and MIDI Stop again just before MIDI Start. The last run had already sent them, so the call now skips it, unless a note is still sounding. `whiplash_stop` is still a full panic when idle. Reference §15.1 #31.
- `length_audible` no longer repeats its own key (`"length_audible: ..."`).
- Tool descriptions were trimmed to fit `whiplash_arrange` inside the unchanged 3,000-character total and 400-character per-tool caps, keeping every pinned caveat. The params and JSON budgets rise to 7,400 characters and 17,500 bytes.
- The wording in `plugin.yaml`, `docs/catalog-entry.yaml` and the skill is refreshed. Generated beats are no longer described as "tracks 1-8", fills no longer as "tracks 1-5", and the skill gains an Arrangement section plus diagnostics rows.
- Version 0.6.1 in `pyproject.toml`, `plugin.yaml`, `docs/catalog-entry.yaml` and `__init__.py`. `whiplash_arrange` is added to `provides_tools` in both manifests, after `whiplash_set_progression`.
- Reference: §15.1 #26 updated, new #30-31, new §15.3 Q14, and notes in §9 and §10.

Not touched: `docs/testing/hardware-checklist.md`, `docs/demo/`, `scripts/`, `view.py`, `view.html` (owned by the visualiser agent). The PR lists the new hardware checks. Checklist A3/A7 still say "play results carry no `routing` field", which is now stale.

## 0.6.0

The first v0.6 PR: keys, scales and chord progressions (item 1 of [docs/executing/v06-build-plan.md](docs/executing/v06-build-plan.md)), plus the v0.6 plan itself. 18 tools. Nothing here has been tested on a real Digitakt II yet.

Added
- **`key` and `scale` on `whiplash_play_pattern`.** The pattern's bass, chords and stabs move into that key from the first bar, or at the switch bar when queued. Drum tracks never move.
  - Each genre has a home key (`patterns.HOME_KEYS`): deep house, soul and tech house in A minor, techno in F minor, breaks in G minor.
  - `harmony.in_key` takes the smallest tonic move (−6..+5 semitones) and maps each note degree by degree, so A minor to C major turns C into E. Notes outside the home scale (deep house's G#) keep their offset. The v0.5 native register is re-applied afterwards.
  - Once set, the key stays for later switches until `whiplash_stop`. Results show `key`. Status shows `key`, `key_source` (`set` or `pattern`) and `queued.key`.
- **`whiplash_set_progression(chords, bars_per_chord, voicing, key, scale, tracks, clear)`.** It loops a chord progression from the next bar line.
  - **Chords** are Roman numerals in the key (`"i VI III VII"`, `"ii7 V7 Imaj7"`, `bVII`, `ii°`, `sus4`, `add9`; upper case = major) or names (`"Am F C G7"`). Lists or strings work, split on spaces, commas, dashes and en dashes.
  - **Timing.** Each chord lasts `bars_per_chord` bars (1-16), counted from the progression's own start, so an 8-bar progression plays correctly over the 4-bar loop.
  - **Voicings:** `close` (voice-led), `root`, `open`, `power`. Every voicing's median sits at or above note 53, the v0.5 register floor.
  - **Modes by role,** from the kit map label or else the pattern's role:
    - chord/pad/stab tracks → `chords`: one chord tone per hit, each chord track on a different tone.
    - bass → `root`: the chord root in the line's own register.
    - lead → `snap`: nearest scale note.
    - Drum, hat, perc, cymbal and fx tracks never change. A `tracks` override on them is refused. `stack` (whole chords on one track) and `off` are opt-in.
  - A chord track with no line (a labelled pad with no generated part) holds one chord tone per bar.
  - Written parts play as written unless named in `tracks`.
  - Transpose, mutes, drops, fills, density and humanize apply on top. The progression carries across switches and `mutate reset`; `clear: true` or `whiplash_stop` ends it.
  - Validated before anything changes. Nothing is sent by the call itself, and no CC is ever involved.
- **`key: "current"` on `whiplash_write_part`** writes scale degrees in the key the beat plays in.
- **Status:** `progression` with the chords, names, key, voicing, loop length, start bar, `now` (the chord playing and `next_change_at_bar`), every voiced chord with note names, and the per-track modes. `tracks[n].progression` gives each track's mode. A queued play result carries `progression_carried`.
- **The v0.6 build plan,** `docs/executing/v06-build-plan.md`. v0.6 is split into v0.6.0 (this PR), v0.6.1 (arrangement, plus fills that follow the kit map, the open v0.5.3 follow-up) and v0.6.2 (DJ-style transitions and mix levels). Each item has its problem, change, tests and HW check, and the plan lists the decisions taken on Phil's behalf.

Changed
- **Chords spread over tracks and hits, not stacked on one channel.** The OS 1.17 manual gives the unit 16 audio voices for 16 tracks (p. 15) and documents chords only on MIDI tracks (p. 17, p. 42-43). An audio track therefore probably plays one note at a time. Recorded as reference §6.4 with HW questions §15.3 Q12-13, and §15.1 #28-29.
- The skill gains a "Keys and chord progressions" section and diagnostics rows. The status description mentions key and progression.
- The description budget test allows the new tool: params ≤ 7,200 characters and JSON ≤ 16,000 bytes. The per-tool (400) and total tool-description (3,000) caps are unchanged.
- Version 0.6.0 in `pyproject.toml`, `plugin.yaml` and `docs/catalog-entry.yaml`. `whiplash_set_progression` is added to `provides_tools` in both manifests, after `whiplash_write_part`.

Open decisions (plan recommendations taken, see the plan's §5)
- `chords` (one tone per hit) is the default over `stack` until reference Q12 is checked on hardware.
- The session key sticks across switches until stop.
- `set_progression` needs a pattern playing. There is no `progression` argument on `play_pattern` yet.

### Also in 0.6.0: visualiser catch-up (PR #13), v0.5.3 hardware checklist and demo script (PR #15)

The visualiser catches up with v0.5.x. Mostly the page and `view.py`. The only engine change is one read-only line: `Engine.view_state()` also copies the slot labels (`kit_slots`). There are no tool or schema changes, and the view still sends nothing. Not tested on a real Digitakt II or in a live Hermes session yet.

Also here: the v0.5.3 hardware checklist and the hackathon demo script, plus two small fixes from the v0.5.3 review (`mutate.fill`, `kitmap` role spelling). Neither touches the engine, tools or schemas.

Added
- **Written parts on the rack.** A track playing a `whiplash_write_part` part gets a `WR` tag, and its 16-step strip becomes a small piano roll: each note at its pitch, as long as its `length` in steps. A `LEN` tag gives the length (or range). It is dashed when Whiplash has sent neither `amp_mode` 1 nor `amp_hold` 127 on that track, since the unit may then not end the sound on note-off (reference §5.2). The module flashes inverted when a part lands.
- **Transpose and range.** A `TRN +12` tag on transposed tracks, and the note range (e.g. `C5-G5`) under the note readout, both including the live transpose. Bars other than the sequencer's current one now carry their notes and lengths, so the note readout and roll stay right across the loop.
- **Amp envelope.** `HLD NOTE`, `ADSR` or `AHD` tags show what Whiplash last sent on CC 80 / CC 87 (not what the kit is set to).
- **Kit map labels** (v0.5.3 `whiplash_label_tracks`). A labelled track shows the user's label as its role in white, with the vocabulary role in the tooltip. Assumed roles stay gray. The `SMP` tag carries the slot's label. A labelled track with no part routed to it still gets a module, tagged `NO PART` until a part is written.
- **Tracks 9-16** get their own row under 1-8 when they play, headed `TRK 9-16 · CHECK AUTO / FX CONTROL CH`, so 1-8 never reflow. (They can carry written parts or, through the kit map, generated ones.)
- **Hardware checklist for v0.5.3** (`docs/testing/hardware-checklist.md`). The 10-minute smoke test is now the demo path: label the kit, one-call start with a slot, filter sweep, a written melody on the silent cymbal track, drop with fill, switch to tech house, status, stop. New checks cover the kit map (classification, merge, bad labels, re-routing on the bar, lifetime, reset), `tracks` setup on fresh and queued starts (§15.3 Q10-11), tech house and its aliases, turn latency, and the v0.5 visualiser (labels, `SMP` labels, `NO PART`, piano roll, `TRN`/`LEN`/`HLD NOTE`, the 9-16 row). Sections are re-lettered; the open-question table maps every check. Still not verified on a unit.
- **Hackathon demo script** (`docs/demo/hackathon-demo.md`): a 3-minute stage run with setup, the prompts in order, what the audience hears and sees, fallback prompts and recovery. Linked from README.
- Snapshot lane fields: `written`, `transpose`, `pitch` (`low`/`high` + names or `null`), `length` (`[min, max]` steps for written parts, else `null`) and `amp` (`{mode, hold_note}` or `null`), `kit` (`{role, label}` or `null`) and `slot_label`. `loop` hits are now `[step, velocity, note, length]` (was `[step, velocity]`).

Fixed
- **Fills on routed melodic parts** (`mutate.fill`). Fills are keyed by track number, so a bass the kit map routed onto track 2 got the snare roll in bass notes (and one on track 1 lost its last beat, on 4 got ratchets). A fill now leaves any line with notes other than 60 unchanged. Drum fills are as before. Reference §15.1 #26 says so.
- **Explicit kit roles** accept underscores and any case (`{"role": "Closed_Hat"}`), like free text already did.
- The visualiser's 9-16 row is headed `TRK 9-16 · CHECK AUTO / FX CONTROL CH`: the kit map can route generated parts there too, so "written parts" was wrong. README fixed the same way, and its default-roles and close-role lists now match `patterns.py` and `kitmap.CLOSE`.
- The view named notes in scientific numbering (60 = C4), one octave off from Whiplash's Elektron numbering (60 = C5) used by `whiplash_write_part`, status and the reference. It now uses `patterns.note_name`.

## 0.5.3

The v0.5 plan's P1 batch (items 7-10), answering Phil's live Hermes feedback from Nov 11 2026: wrong track roles for his kit, 5-40 s turns with many `tool_describe` round trips, and no tech house. 17 tools. Nothing here has been tested on a real Digitakt II yet.

Added
- **Kit map: `whiplash_label_tracks`** (plan item 7). It records what the user says each track holds (`tracks: {"7": "tuned cymbal", "5": "pad"}`) and what slots hold (`slots: {"11": "synth Phil likes"}`).
  - **Vocabulary.** Free text is matched to one of kick, snare, rim, clap, closed hat, open hat, cymbal, perc, bass, pad, stab, chord, lead, fx, other. Explicit `{role, label}` also works. `null` removes a label; calls merge.
  - **Patterns follow the map** (`kitmap.route`). Each generated part goes:
    1. to the track labelled with its role,
    2. else to a close role (rim/snare, chord to pad, stab to lead, open hat to cymbal),
    3. else to its default track, unless the user labelled that track as something else,
    4. else it is dropped.

    Cymbal and fx tracks never get a melodic part. Labelled tracks with nothing routed stay silent until `whiplash_write_part`. Parts keep the native register.
  - **When it applies.** While playing, a change re-routes at the next bar line and keeps swing, humanize and density. Otherwise it applies at the next start.
  - **Lifetime.** The map survives `whiplash_stop` and pattern switches. `reset: true` or a gateway restart clears it. It lives in memory only: no file and no MIDI.
  - **Results.** `whiplash_status` and play results show the label as `tracks[n].role` (no "(assumed)") with `kit_role`, `slot_label` for a labelled slot, `kit`, and `roles_assumed: false` once anything is labelled. `whiplash_select_sample`, `whiplash_set_param` `sample_slot` and the play `setup` echo carry `slot_label`. The label result has `routing` (`parts`, `dropped`, `silent_until_written`). The visualiser's lanes use the labels.
  - Validated before anything changes. Whiplash still never reads sample names (that needs SysEx).
- **One-call start: `tracks` on `whiplash_play_pattern`** (item 8). For example `{"6": {"slot": 9, "tune": 64, "transpose": -12, "mute": false}}`.
  - Slot (CC 19) and tune (CC 16) go out once each, slot first. On a fresh start they are sent before MIDI Start and the first note. When the call is queued they are sent at the switch bar, before that bar's notes, together with the mutes.
  - A setup CC replaces a running ramp on the same param.
  - `transpose` merges with the top-level `transpose`, and conflicting values are refused.
  - The whole call is validated first, so a bad entry changes nothing.
  - The result echoes `setup` with when it applied and the slot labels.
- **`techhouse` genre** (item 9) at 126 BPM with 56% swing. It has four on the floor, an offbeat open hat, 16th hats with three-level accents, a rolling off-beat bass around A4 (never on the kick, register unchanged), a sparse stab and perc.
  - Aliases `tech house`, `tech-house` and `tech_house`. Spacing and case are ignored.
  - Moods `funky`, `bouncy`, `rolling` and `peak time`.
  - An unknown genre's error lists the closest matches.

Changed
- **Shorter tool descriptions** (item 10). Tool descriptions went from 7,302 to about 2,700 characters, even with one more tool. All descriptions, params included, went from 11,357 to about 6,300. The full schema JSON went from 18,108 to about 13,900 bytes.
  - The detail moved into the `whiplash:digitakt` skill.
  - The safety caveats stay in the descriptions: pass on `overlap_warning` and the virtual-port warning, HOLD = NOTE and `envelope: "note"` only when the user agrees, `length_audible`, can't list samples, stop as panic, and the read-only view.
  - A test caps the total size, and the size of each tool's description.
- The skill gains a "fast path" (label, then start with `tracks` in one call), the kit map rules, and the material moved out of the tool descriptions: switch behaviour, mutate actions, ramps, stop and the virtual port. The "roles are assumptions" section is replaced.
- `kit_note` points the agent at `whiplash_label_tracks`.
- Version 0.5.3 in `pyproject.toml`, `plugin.yaml` and `docs/catalog-entry.yaml`. `whiplash_label_tracks` is added to `provides_tools` in both manifests.
- Reference §15.1 #26-27 and §15.3 Q10-11 cover the kit map and setup timing.

Open decisions (plan recommendations taken)
- The kit map lives in memory only. Persistence (item 13, `~/.hermes/whiplash/kitmap.json`) still needs Phil's OK.
- No sample names from the unit (SysEx stays blocked).
- `cymbal` is added to the plan's vocabulary, because the plan's own cymbal rule and Phil's kit need it.

## 0.5.2

Review follow-ups from the v0.5.0 review (PR #10): three fixes, each with tests. Still 16 tools. Nothing here has been tested on a real Digitakt II yet.

Fixed
- **Transpose on tracks 9-16.** `whiplash_transpose` and `play_pattern(transpose=...)` used to return success on a track that plays nothing, such as 9-16 without a written part, and then do nothing. Transpose applies to any track that plays, including written parts on 9-16. A non-zero transpose on a track with no notes (in the current pattern, the queued one, or a carried written part) is now refused with an error that says to write the part first. It is validated before anything changes. `0` is always accepted.
- **All Notes Off on 9-16.** Stop, panic and the run's own exit sent CC 123 only on channels 1-8, but written parts can play on 9-16. CC 123 now also goes to every channel 9-16 that played a note since the last panic, and to no other. Channels 1-8 still get it every time, as before. The clock thread only adds the channel to a set when it sends a note-on.
- **`amp_hold` can't slip into HOLD = NOTE.** On CC 80, 127 is not the longest hold: it switches HOLD to NOTE (manual 11.7 p. 56; midi.guide), and this was the top of a clamped, rampable range. The fix:
  - Named `amp_hold` now has range 0-126.
  - Every ramp on CC 80 (named or raw `cc: 80`) stops at 126 and says why in `hold_note`.
  - `whiplash_set_param` sends 127 only for `value: "note"` or exactly 127, and labels the result `hold: "NOTE"` with a warning to tell the user.
  - `write_part` `envelope: "note"` uses the same path, and its result carries the same label.
  - Values above 127 were already refused as non-7-bit. The skill, README, schemas and reference (§5.2, §8.0, §15.1 #25) say so.

Changed
- README: the test count is checked by a test now. Also corrected "HOLD = NOTE (the usual default)": that is only the midi.guide default (reference §15.3 Q6). The CHANNELS setup now says to keep AUTO/FX CONTROL CH off any channel 9-16 you write parts on.
- The view keeps `amp_hold` knob travel at 0-127, so an explicit NOTE shows at the top.
- Version 0.5.2 in `pyproject.toml`, `plugin.yaml` and `docs/catalog-entry.yaml`.

### Also in 0.5.2: hardware test plan and v0.5.0 review (PR #10)

Added
- `docs/testing/hardware-checklist.md`: one ordered hardware session for a real Digitakt II. It starts with a 10-minute smoke test, which covers the demo plus one written melody. Then it covers:
  - the v0.5.0 pitch register, status, skill and `amp_mode`,
  - v0.4 sample select and transport modes,
  - v0.3 live control,
  - the reference fixes,
  - the visualiser restyle,
  - v0.5.1 `whiplash_write_part` (melody, rhythm presets, lock to kick, length vs HOLD/MODE, retrigger, tracks 9-16),
  - the v0.5.2 fixes for the review findings (transpose on 9-16, All Notes Off on the 9-16 channels in use, `amp_hold` 127 only when explicit),
  - and hot-plug.

  Each check has the setup, the prompt to type, what to expect, and pass/fail boxes. The checks map to the reference's open hardware questions (§15.3). It is linked from README and CLAUDE.md.

Fixed (docs)
- Reference §8.1 Amp table: `amp_mode` is shipped (it said "planned").
- v0.5 build plan status: P0a shipped in v0.5.0, and P0b shipped in v0.5.1.

## 0.5.1

Written parts: Hermes can now write melodies, basslines and rhythms itself, the three asks from the Nov 11 2026 Digitakt II session that v0.5.0 left open ("play different notes so it's a melody", "4/4 on the bass drum, not 16ths", "plays non-stop"). 16 tools. Nothing here has been tested on a real Digitakt II yet.

Added
- `whiplash_write_part(track 1-16, ...)` replaces one track's line in the working pattern from the next bar line:
  - **Placement**, one of: `rhythm` presets (`four_on_floor`, `on_kick`, `offbeat_8ths`, `8ths`, `16ths`, `off_16ths`, `syncopated`, `half_time`), `grid` step masks (16 cells per bar, `X` = accent, up to 4 bars), `steps`, `hits` (`{step, note, length, velocity, bar}`) or `lock_to` (copies another track's hits at call time; `on_kick` = `lock_to: 1`; live follow is P1).
  - **Notes** cycle over the hits: Elektron names (C5 = 60), MIDI numbers 16-84, `.` rests, or scale degrees with `key`/`scale` (13 scales). The result echoes each bar as a grid with note numbers and names, plus the `pitch` block.
  - **`length`** in 16th steps (0.25-16, a list cycles) is sent as the exact MIDI note-off, with no 0.8 `GATE` factor. **`velocity`** 1-127, a list, or `accent`. **`bars`** 1, 2 or 4 (default: the shortest that plays every note).
  - **`length_audible`** in every result: the unit only ends a sound on note-off with AMP MODE = ADSR or HOLD = NOTE (manual 11.7 p. 56, B.5 p. 110; midi.guide; reference §5.2). It says so more confidently when Whiplash itself last sent `amp_hold` 127 or `amp_mode` 1.
  - **`envelope: "note"`** (opt-in) sends exactly one CC 80 = 127 (HOLD = NOTE) on the track, after validation. The envelope is never changed silently.
  - Mutes, drops, fills, density, humanize and transpose still apply to a written part. It carries across live pattern switches and `whiplash_mutate reset`; `reset: true` or `whiplash_stop` clears it (the same lifetime as mutes and transposes).
  - Bad input (track, placement, notes, grid, length, velocity, bars, envelope) raises before anything changes: no part, no CC.
  - On tracks 9-16 the result warns that the unit's AUTO CHANNEL or FX CONTROL CH may share the channel (reference §7.4).
- `whiplash_status` gains `parts`, and `tracks[n].part` is `written` for a written part.
- The bundled `whiplash:digitakt` skill teaches `whiplash_write_part`: that Hermes can write melodies and rhythms, how to place hits, write lines around C5, read `length_audible`, and make length audible with `envelope: "note"` or ADSR.

Changed
- `whiplash_mutate` `density` and `drop` accept tracks 1-16 (was 1-8). Density on a track with no notes is rejected.
- The sequencer ends a held note just before the same note retriggers on the same channel, instead of letting the earlier note-off cut the new note short. Generated parts never overlapped this way, so they sound the same.
- New module `parts.py`: pure parsing and building of written parts, no MIDI.

### Also in 0.5.1: visualiser pixel-art rack restyle (PR #8)

Changed
- `whiplash_open_view` page (`view.html`) restyled as a flat, strict-grayscale pixel-art hardware rack, per [docs/executing/viz-style-brief.md](docs/executing/viz-style-brief.md). It is still one self-contained file with no new dependencies, fonts or CDNs, and the tool contracts are unchanged.
  - **Track modules:** a trig LED and note readout fire on each scheduled hit. The LVL fader and FLT/RES/DEC knobs show the last values sent, plus a fourth knob for any other param. Ramping knobs turn toward a target tick. Each module has a 16-step pixel strip and a mute bat toggle. A mute dims the module, and a drop or fill starting flashes it inverted.
  - **Tape transport:** the reels turn in proportion to the BPM and stop with the transport. It also has a REC LED, a bitmap BPM, bar and loop position, the queued switch and the port status.
  - **Master OUT:** the VU needle follows an envelope derived from the scheduled hits and track levels, clearly labelled as not real audio. It follows the real input's RMS after CONNECT AUDIO.
  - **Hub:** dotted rings pulse on kicks and bar downbeats.
  - **Cables:** white bezier patch cables run from each track OUT to its master IN. A hit shakes the cable, and a muted or dropped track's cable goes dashed. `R` toggles the cables (it was runway tilt). The spectrum and scope panels are gone.
- View snapshot param rows carry `max` from `ccmap`, so knob travel matches each param's range.

Added
- Tests: the page has no external URLs, its palette is strict grayscale, every state field the page reads exists in a real frame, and param `max` follows `ccmap`.
- `docs/executing/viz-style-brief.md` (the design brief) and a roadmap entry under visualiser evolution.

## 0.5.0

Fixes from the second live session on a Digitakt II (Nov 11 2026): generated basslines no longer repitch samples far below their own pitch, results say where each line sits, and the agent guidance ships with the plugin. 15 tools.

Added
- **Native-pitch register.** Note 60 (C5, Elektron numbering) plays a sample at its own pitch while TUNE is 64 and the preset OCTAVE is unchanged (reference.md §6.1; manual p. 25, p. 38). `patterns.register()` lifts each generated melodic part by whole octaves at load time until its median is no more than 7 semitones below 60, keeping the intervals. The techno bass moves from 41 to 53 (the -7 that tune +12 fixed by ear), the soul and breaks basslines move up an octave, deep house is unchanged, and drums are never moved. The note tables stay as written in `patterns.RAW`.
- `whiplash_transpose(track, semitones | octaves)`: absolute, ±48 semitones, from the next bar line, clamped to 16-84 (the manual's documented chromatic range; the track-channel range is undocumented). Carries across pattern switches like mutes; `whiplash_stop` and a fresh start reset it.
- `transpose` on `whiplash_play_pattern` (`{"6": -12}`): from the first bar of a fresh start, or from the switch bar of a queued one.
- `pitch` per melodic, transposed or tuned track: low/high notes with Elektron names, `semitones_from_native` (including `tune - 64` when Whiplash sent CC 16), `transpose`, `tune` and `register_shift`.
- `tracks` in `whiplash_status` and in `whiplash_play_pattern` results: role marked `(assumed)`, last sample `slot` and `tune` Whiplash sent (`null` until sent), `transpose`, `pitch`, mute, `part` and `last_cc`, plus `roles_assumed`, `kit_note` and `pitch_note`. A queued result describes the next pattern with the transposes it will play with.
- `amp_mode` named param: CC 87, 0 = AHD, 1 = ADSR, a switch (manual B.5 p. 110; midi.guide). `amp_hold` documents 127 = NOTE (manual 11.7 p. 56; midi.guide). 38 named params.
- Bundled skill `whiplash:digitakt` (`skills/digitakt/SKILL.md`), registered with `ctx.register_skill` when the Hermes build has it; older builds still load the tools. Tool descriptions point to it.
- README "Updating" section: run `hermes gateway restart` after updating, and delete any stale local `whiplash-digitakt` skill.

- The reference's named-param table gains `amp_mode`, and its §15.1 audit marks items 3, 15 and 22 as handled in v0.5.0. `pitch_note`, the skill and the README now carry the reference's caveats: the preset OCTAVE and an LFO on tune are invisible to Whiplash, SLICE = NOTE picks slices, HOLD = NOTE is the usual default, and Logic calls note 60 C3.

Not in this release (next, v0.5.1): `whiplash_write_part` (notes, rhythm presets, lock-to-kick, note lengths).

### Also in 0.5.0: the Digitakt II device reference (PR #6)

Added
- `docs/digitakt-ii/reference.md`: a detailed device reference with manual page numbers, cross-checked against midi.guide (CSV of 2026-10-12). It covers:
  - the data model (project, pattern, kit, preset, pool, +Drive),
  - machines and their knob CCs,
  - how incoming notes map to pitch,
  - channels (track, AUTO, FX CONTROL) and their CC collisions,
  - the full CC/NRPN map with 16 discrepancies listed,
  - transport and clock, mutes, p-locks, LFOs, and USB audio and Overbridge,
  - an "Implications for Whiplash" audit of 22 code assumptions.

  It is the canonical device reference.
- `docs/digitakt-ii/README.md` and `fetch-manual.sh`. They give the link, edition and SHA-256 of the official OS 1.17 manual, and download it locally with a hash check. The PDF isn't committed: its imprint forbids reproduction without written authorization.
- `CLAUDE.md`: agent notes. They point at the reference and restate the safety rules (no SysEx, no program change, no writes to the unit, blocked CCs stay blocked).
- `tests/test_reference.py`: checks the reference's named-param table against `ccmap.py`, the `loop_pos` range on the wire, and that the safety blocks are unchanged.

Fixed
- `loop_pos` (CC 22) range is now 0-120, not 0-127, matching midi.guide's Oneshot Loop Pos and the sibling `sample_start`/`sample_length`. Values above 120 clamp, with `clamped: true`. The description now says the knob is machine dependent (Bars on Werp, Stretch and Repitch; Grid on Grid).
- `lfo3_speed` documents its NRPN (1:58; the manual and midi.guide agree). It is documentation only and still never sent.

Changed
- README:
  - Setup now says to keep AUTO CHANNEL and FX CONTROL CH off channels 1-8.
  - Note 60 = original pitch now carries its two caveats: TUNE centred and preset OCTAVE unchanged.
  - Note lengths depend on AMP HOLD = NOTE or ADSR.
  - Safety says parameter edits stay in the active pattern's kit until reloaded.
  - It links the reference.

### Also in 0.5.0: the live visualiser (merged from `feat/visualiser`)

Added
- `whiplash_open_view` / `whiplash_close_view`: a live, read-only web page served on `127.0.0.1` and opened in the default browser. It shows:
  - **Tracks:** one lane per track in use, with the current bar's notes on a tilted runway grid, a playhead, a 4-bar minimap, mutes, drops, fills, density, param values and animated ramps.
  - **Transport:** a large BPM readout, the bar, pattern, queued switch and port status.
  - **Analyser:** spectrum, scope and L/R meters from the Digitakt's USB audio via `getUserMedia`, or an honestly labelled MIDI fallback.
  - **Conversation:** the live Hermes conversation, streamed word by word, with tool calls behind a toggle.
  - **Log:** recent Whiplash actions.
- Hermes conversation hooks: `pre_llm_call`, `on_stream_start`/`delta`/`end`, `pre_tool_call`, `post_tool_call` and `post_llm_call`. They keep in-memory observers only, return `None` and ignore subagent sessions. Without hook support, the view falls back to a read-only poll of `~/.hermes/state.db`.
- The engine publishes the playhead (`position`) and the current bar's hits (`bar_hits`) from the clock thread by plain assignment, and `view_state()` gives a lock-short copy of the state for the view.
- `docs/visualiser-design.md`: the approved design.
- The page shows the v0.4 transport mode (`START/STOP` or `CLOCK ONLY`) and each track's last selected sample slot.
- CI also runs on `feat/visualiser`.

## 0.4.0

Two fixes from the first live session on a Digitakt II: tracks can now switch to another sample already in the project, and the beat can run on clock alone so the unit's own pattern doesn't layer in. 12 tools.

Added
- `whiplash_select_sample(track, slot)` and the named param `sample_slot` (aliases `sample`, `smp`, `slot`): sends Sample Slot Select, CC 19, slot 0-127 within the sample bank selected on the unit. Verified in the manual's Appendix B (B.3, p. 109; B.9, p. 113) and on midi.guide. It only picks among samples already loaded in the project pool: Whiplash can't list, preview or load samples. Out-of-range slots are rejected, and it can't be ramped.
- `send_transport` on `whiplash_play_pattern`, with a `WHIPLASH_SEND_TRANSPORT` env default. `true` (the default, as before) sends Start, clock and Stop. `false` sends clock only: no Start, and no Stop either, so Whiplash can't halt a pattern running on the unit. Changing it while playing restarts instead of queueing. `whiplash_status` shows `transport_mode`.
- `overlap_warning` on every `whiplash_play_pattern` result (start and queued switch). MIDI Start also starts the Digitakt's own sequencer, so trigs in the pattern selected on the unit play on top; the warning tells the user to select an empty pattern, or to use clock only.
- CI also runs on `feat/v04`.

Changed
- **Sample policy relaxed, narrowly.** CC 19 is now sent, but only through the named param, so raw `cc: 19` is still refused. Sample bank select (CC 24, NRPN 1:9), the sample NRPNs 1:3 and 1:8, MIDI bank select, SysEx and program change all stay blocked.
- Machine type (Oneshot, Werp, ...) is not controllable: neither the manual nor midi.guide documents a CC or NRPN for it.
- README and the catalog drafts say what sample select can and can't do, and add the empty-pattern advice.

## 0.3.0

Whiplash goes from playing a beat to performing it: three new tools (11 in all), and pattern changes that land on the bar.

Added
- `whiplash_ramp_param`: sweeps a named param or raw CC `from` → `to` over `beats` or `bars`, advanced on the sequencer's MIDI clock. Curves linear, exp and log. It sends only when the integer value changes, runs several ramps at once (a new one on the same track/param replaces the old), and cancels by id or `all`. `whiplash_stop` cancels all ramps, and `whiplash_set_param` on the same param cancels that ramp. Needs a pattern playing.
- `whiplash_mutate`: live `density` (thin/thicken), `fill` (one-bar drum fill on the next bar), `swing` (50-80 %), `humanize` (bounded, never drifts), `drop` (silence tracks for N bars with auto-return and optional fill), and `reset`. Deterministic, seeded, and timed to the bar.
- `whiplash_list_params`: the named Digitakt II parameter map, grouped, with ranges, centres and aliases.
- Bar-quantized pattern switching. `whiplash_play_pattern` while playing queues the new pattern for the next bar line (`mode: "queued"`, `switch_at_bar`) without a Stop/Start. Mutes, ramps and scheduled drops/fills carry over; density, swing and humanize reset. A second queued call replaces the first.
- Hot-plug notify. While on the virtual fallback port, every tool result carries `device_available` and a notice once a Digitakt appears. Whiplash never switches on its own. Port enumeration is rate-limited to every 2 s and never runs in the clock thread.
- Port loss. If a send fails (USB unplugged), the port is dropped, `whiplash_status` shows `port_lost`, and the next call re-detects and reopens it.
- `docs/catalog-entry.yaml` and `docs/catalog-pr.md`: drafts for the Hermes plugin catalog submission.
- CI also runs on `feat/v2`.

Changed
- **Parameter map rewritten** from the Digitakt II manual (Appendix B), cross-checked with midi.guide: 36 params across track, src, filter, amp, fx and lfo, with ranges and centres. Named params are sent as CC only, because several NRPN addresses disagree between the two sources. Out-of-range values clamp into the param's range (switches like `mute` and `play_mode` reject instead). Unknown names get close-match suggestions. The old names keep working as aliases (`level`, `volume`, `cutoff`, `filter_cutoff`, `resonance`, `filter_resonance`, `decay`).
- **Mutes now carry over** a live pattern switch. They still reset on `whiplash_stop` and on a fresh start.
- `whiplash_play_pattern` returns `mode` (`started` or `queued`). `whiplash_stop` also returns `ramps_cancelled`.
- Stopping mid-beat sends note-offs only for notes actually sounding, with no stray note-offs for note-ons that never went out.
- The MIDI backend error suggests the ALSA runtime when `libasound` is missing.

## 0.2.0

**Breaking:** every tool is now prefixed `whiplash_` (`play_pattern` → `whiplash_play_pattern`, `stop` → `whiplash_stop`, and so on), so Whiplash can't collide with another plugin's tools.

Fixed
- `whiplash_play_pattern` validates `bpm` (30-300) and `bars` (1-512) before touching the running beat. A negative tempo used to spin the sequencer and flood the port with clock messages.
- NRPN values are always sent as 14 bits (MSB = `value >> 7`, LSB = `value & 127`). Values up to 127 used to be sent as the MSB alone, so 127 was louder than 128.
- Stopping sends one panic (All Notes Off + transport Stop) instead of two.
- Mutes reset on stop and when a new pattern starts, and the result reports them in `mutes_cleared`. A forgotten mute used to silently carry into the next beat. Mutes Whiplash set on the unit itself (CC 94) are released at the same time.

Added
- Exit cleanup: a normal Hermes exit silences the unit, releases hardware mutes, and closes the port.
- A transport lock, so overlapping `play`/`stop` calls can't leave two sequencers running.
- A `warning` on every tool result while output is going to the virtual fallback port.
- `last_error`, `fallback`, and `hardware_muted` in `whiplash_status`.
- `whiplash_set_param` takes exactly one of `param`, `cc`, `nrpn` and rejects a bad request before sending anything.
- `pyproject.toml` with bounded dependencies, `python_dependencies` and `requires_hermes` in `plugin.yaml`.
- GitHub Actions workflow running the tests on Linux and macOS.

Changed
- Author metadata is `pgbouncer`. `requirements.txt` is replaced by `pyproject.toml`.

## 0.1.0

First version: eight tools, four genres, MIDI clock and transport, CC/NRPN parameters, mutes, tempo, virtual-port fallback.
