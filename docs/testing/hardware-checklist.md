# Hardware test session: Whiplash on a Digitakt II

This is one ordered session for Phil on the Air, with Hermes and a Digitakt II on USB MIDI. It covers everything that hasn't been checked on a real unit yet:
- v0.3 live control,
- v0.4 sample select and transport,
- v0.5.0 pitch register, status, skill and `amp_mode`,
- the Digitakt reference fixes,
- the restyled visualiser,
- and v0.5.1 `whiplash_write_part`, once it merges.

**Nothing in this file is verified yet.** The test suite runs on fake and virtual ports only. As you go, tick Pass or Fail and jot a note. Afterwards, record each result in [docs/digitakt-ii/reference.md](../digitakt-ii/reference.md) with who tested it, the date and the OS version (CLAUDE.md rule). Each check names the reference section or open question (§15.3 Qn) it settles.

**Order:**
- **Part A (about 10 min)** is the smoke test. If it passes, the demo is safe; stop there if time is short.
- **Parts B-H** go deeper, most important first.
- **Part I** is for v0.5.1. Skip it until that PR is merged.
- **Part J** unplugs the cable, so it comes last.

Type the prompts as written; *italic* text in a prompt is a placeholder. If Hermes picks a different tool or argument than expected, note it: that's useful too.

---

## 0. Before you start (5 min)

### 0.1 Update and restart the gateway

```bash
git -C ~/whiplash pull          # symlinked checkout; or: hermes plugins update whiplash
hermes gateway restart          # required: the gateway keeps old plugin code until it restarts
hermes plugins list             # whiplash -> enabled
```

A new chat is **not** enough after an update. Only `hermes gateway restart` loads the new code.

If Hermes earlier auto-created a local skill for Whiplash, delete it. Look for `~/.hermes/skills/whiplash-digitakt/` or anything similar under `~/.hermes/skills/`. It holds stale claims such as "can't switch samples".

### 0.2 On the unit

- [ ] **SETTINGS > MIDI CONFIG > PORT CONFIG:** INPUT FROM = USB (or MIDI+USB), RECEIVE NOTES on, RECEIVE CC/NRPN on.
- [ ] **SYNC:** CLOCK RECEIVE on, TRANSPORT RECEIVE on.
- [ ] **CHANNELS:** TRACK 1-8 = channels 1-8. **Write down AUTO CHANNEL, FX CONTROL CH and PRG CHG IN CH as you find them** (this answers §15.3 Q1). Then move AUTO and FX CONTROL off channels 1-8, or set them to OFF.
- [ ] **USB CONFIG = USB AUDIO/MIDI**, which part H needs for real audio. MIDI works in this mode too.
- [ ] **Select an empty pattern** in the project you'll demo with. Otherwise MIDI Start also plays the unit's own trigs.
- [ ] **Reload the pattern** with [FUNC] + [NO] so that last night's edits (for example tune +12 on the bass track) are gone. Every check below assumes TUNE = 64 and an unchanged preset OCTAVE.

**Cleanup at the end:** every Whiplash parameter change sticks in the active pattern's kit until you reload. When you're done, press [FUNC] + [NO], and **don't save the project**. Whiplash never saves anything.

---

## A. Smoke test, 10 minutes (good enough for the demo)

This is the 90-second demo from the README, plus the v0.5.0 checks it depends on.

### A1. Connected, and the visualiser opens
- **Type:** *"Is my Digitakt connected? And launch the visualiser."*
- **Expect:**
  - `whiplash_list_midi_ports` finds *Elektron Digitakt II*, with no `warning` about a virtual port.
  - `whiplash_open_view` opens `http://127.0.0.1:7341` in the browser and shows the idle rack: a tape transport, the hub, a master OUT and the port name.
- [ ] Pass · [ ] Fail. Notes:

### A2. Deep house plays, bass in its own register
- **Type:** *"Play some groovy deep house."*
- **Listen:** kick, rim, hats, bass and chords at 122 BPM with swing, and nothing from the unit's own pattern layered in.
- **Look:**
  - The result's `tracks["6"].pitch` shows low 52, high 65, `semitones_from_native` about [-8, 5], and no `register_shift`.
  - `overlap_warning` is present.
  - The visualiser shows 8 modules with trig LEDs firing in time.
- [ ] Pass · [ ] Fail. Notes:

### A3. Filter sweep (v0.3 ramp)
- **Type:** *"Close the filter on the bass, then open it slowly over 8 bars."*
- **Expect:** a `whiplash_set_param` on track 6 `filter_freq` (about 20), then a `whiplash_ramp_param` to about 110 over 8 bars. The sweep is smooth, with no zipper steps, and lasts 8 bars. On the visualiser, the FLT knob turns toward its target tick.
- [ ] Pass · [ ] Fail. Notes:

### A4. Drop with a fill (v0.3 mutate)
- **Type:** *"Drop the kick and bass for two bars with a fill."*
- **Expect:**
  - Kick and bass go silent from the next bar.
  - A snare roll and hat ratchets play on the second dropped bar.
  - Kick and bass come back exactly on the one.
  - On the visualiser, modules 1 and 6 show `DROP` with a countdown and flash inverted when it starts.
- [ ] Pass · [ ] Fail. Notes:

### A5. Bar-quantized switch to techno: the bass no longer sounds stretched (v0.5.0 item 1)
- **Type:** *"Switch to techno on the next bar."*
- **Expect:**
  - The result says `mode: "queued"`, and the switch lands on a bar line at 130 BPM with no Stop/Start: the unit's delay keeps ringing in time.
  - `tracks["6"].pitch` shows low/high 53, `semitones_from_native` [-7, -7] and `register_shift` 12.
- **Listen:** with TUNE at 64, the track-6 bass should sound like last night's tune +12 fix: not stretched or grainy.
- [ ] Pass · [ ] Fail. Notes:

### A6. Status is honest about the kit (v0.5.0 item 5)
- **Type:** *"What's playing? Give me the per-track details."*
- **Expect:**
  - `whiplash_status` returns `tracks` with roles marked `(assumed)`, `slot`/`tune` as `null` where Whiplash hasn't sent them, `filter_freq` under `last_cc` on track 6, and a `kit_note`.
  - Hermes should **not** state the roles as fact. Ideally it asks what each track holds.
- [ ] Pass · [ ] Fail. Notes:

### A7. Clean stop
- **Type:** *"Stop."*
- **Expect:** silence right away, with no hanging notes. The unit's sequencer stops (Start/Stop mode). The visualiser reels stop.
- [ ] Pass · [ ] Fail. Notes:

**If A1-A7 pass, the demo is safe.** Write down the time each turn took (the soft latency metric, plan item 10).

---

## B. Pitch and register, v0.5.0 (plan HW 1; §15.3 Q2)

### B1. Note 60 is native pitch on a track channel
- **Setup:** KEYBOARD mode **off**. Track 1 holds a pitched or recognisable sample, TUNE = 64.
- **Type:** *"Play techno."* Then compare the kick against pressing [TRIG 1] on the unit, or previewing the track-1 sample.
- **Expect:** the pitch is identical. Whiplash's drum parts are note 60.
- [ ] Pass · [ ] Fail. Notes:

### B2. An octave down and up (notes 48 and 72)
- **Type:** *"Transpose track 1 down one octave."* Wait 2 bars. Then *"Now up one octave."* Then *"Put track 1 back to normal."*
- **Expect:**
  - Each change lands on the next bar line.
  - `pitch` shows 48, then 72, then no transpose.
  - You hear an exact octave each way.
- [ ] Pass · [ ] Fail. Notes:

### B3. The KB octave doesn't affect track channels
- **Setup:** turn KEYBOARD mode on and shift the KB octave with [KEYBOARD] + [UP] twice, while techno plays.
- **Expect:** Whiplash's pitches don't change. Then turn KB mode off: the KB octave setting is unchanged by Whiplash's notes.
- [ ] Pass · [ ] Fail. Notes:

### B4. Transpose at start, and carry over a switch
- **Type:** *"Play breaks with the bass an octave down."* This should call `whiplash_play_pattern` with `transpose: {"6": -12}`. Then *"Switch to soul on the next bar."*
- **Expect:**
  - Breaks bass `pitch` low 41. The queued result's `tracks["6"].transpose` = -12, and `transpose_carried` lists it.
  - After the switch, the soul bass plays 12 below its new register.
  - *"Stop"*, then *"play soul"*: the transpose is gone.
- [ ] Pass · [ ] Fail. Notes:

### B5. Tune shows up in `pitch`
- **Type:** *"Set tune on track 6 to 76."* Then *"What's the pitch on track 6?"*
- **Expect:**
  - `tracks["6"].tune` = 76, and `semitones_from_native` goes up by 12.
  - You hear an octave up.
  - Then *"Set tune on track 6 back to 64."*
- [ ] Pass · [ ] Fail. Notes:

### B6. Range edge (optional)
- **Type:** *"Transpose track 8 up 4 octaves."*
- **Expect:** `pitch` reports `clamped: true`, with high 84. Notes above 84 are held at 84, so whether the unit plays them as expected on a track channel answers the "usable note range" part of Q2.
- [ ] Pass · [ ] Fail. Notes:

---

## C. Bundled skill and updating, v0.5.0 (plan HW 4)

### C1. The plugin and skill load after a gateway restart
- **Type:** `/plugins`, then *"List your skills. Is whiplash:digitakt there? Open it and tell me what it says about pitch."*
- **Expect:**
  - whiplash is enabled.
  - `skills_list` shows `whiplash:digitakt`.
  - `skill_view("whiplash:digitakt")` returns the "note 60 plays a sample at its own pitch" section.
  - No stale local `whiplash-digitakt` skill appears alongside it.
- Note the Hermes version (`hermes --version`; v0.23.1 was expected). If the skill is missing, check the gateway log for `skill skipped`: that means this build has no `ctx.register_skill`.
- [ ] Pass · [ ] Fail. Notes:

### C2. The skill steers diagnostics
- **Setup:** techno playing, then *"Transpose track 6 down two octaves."*
- **Type:** *"The bass sounds stretched and grainy, fix it."*
- **Expect:** Hermes checks `pitch` and transposes up, or sets tune, **before** touching the envelope or density. Count the tool calls.
- [ ] Pass · [ ] Fail. Notes:

---

## D. Note length and the amp envelope, v0.5.0 `amp_mode` (part of plan HW 2; §15.3 Q6)

Generated parts send note-off at 0.8 of their gate, so the difference is audible on the soul or breaks bass (gates of 3-4 steps) and the breaks pad (16 steps).

### D1. The default envelope
- **Setup:** *"Play breaks."* On the unit, open track 8 (pad) AMP and **write down MODE and HOLD** as you find them on this preset (Q6).
- [ ] Recorded. MODE: ____ HOLD: ____

### D2. HOLD = NOTE vs a fixed hold
- **Type:** *"Set amp hold on track 8 to 127."* (On the unit, HOLD should show NOTE.) Then *"Set amp hold on track 8 to 20."*
- **Expect:** at 127, the pad holds for its note length, then decays. At 20, every hit has the same short hold whatever the note length.
- [ ] Pass · [ ] Fail. Notes:

### D3. ADSR mode
- **Type:** *"Switch the amp envelope on track 8 to ADSR."* That's `amp_mode` 1, and the unit's MODE should show ADSR. Then *"Set the amp release on track 8 to 30."*
- **Expect:** the pad sustains while the note is held, then releases. Also *"Set amp mode on track 8 to 2"* must be **rejected** with no change: it's a switch.
- **Afterwards:** *"Set amp mode on track 8 back to 0"*, or reload the pattern.
- [ ] Pass · [ ] Fail. Notes:

---

## E. Sample select and transport, v0.4

CC 19 switching slots was heard on Nov 11; the rest is new.

### E1. Slot 0: OFF or the first sample? (§15.3 Q4)
- **Setup:** deep house playing.
- **Type:** *"Switch track 7 to sample slot 0."* Then *"slot 1."*
- **Expect:** either silence (OFF) or the first pool sample on slot 0. Record which. Then *"Put track 7 back on slot* N" (its original slot).
- [ ] Recorded: slot 0 = ____

### E2. Slot select refusals
- **Type:** *"Send raw CC 19 value 5 on track 7."* Then *"Send CC 24 on track 7."*
- **Expect:** both are refused. CC 19 goes only through `sample_slot`, and CC 24 is blocked. Nothing changes on the unit.
- [ ] Pass · [ ] Fail. Notes:

### E3. Clock only: the unit's own pattern stays stopped
- **Setup:** select a pattern on the unit that **has** trigs.
- **Type:** *"Play techno, clock only."* That's `send_transport: false`.
- **Expect:**
  - Only Whiplash's notes play. The unit's PLAY LED stays off, and its tempo shows 130.
  - Press [PLAY] on the unit: its pattern joins in sync.
  - *"Stop"*: Whiplash stops, the **unit keeps playing** (no Stop is sent), and you stop it on the unit.
- [ ] Pass · [ ] Fail. Notes:

### E4. Start/Stop layers the unit's pattern, and the warning says so
- **Setup:** the same pattern with trigs.
- **Type:** *"Play techno."*
- **Expect:**
  - The unit's sequencer starts with Whiplash and its trigs layer in.
  - `overlap_warning` explains it.
  - *"Mute track 1"* silences Whiplash's kick but **not** the unit's own track-1 trigs.
  - *"Stop"* stops both.
- **Afterwards:** select the empty pattern again.
- [ ] Pass · [ ] Fail. Notes:

### E5. Changing the transport mode while playing restarts
- **Type:** *"Play deep house."* Then *"Switch to techno, clock only."*
- **Expect:** `mode: "started"`, not queued: a restart, not a bar-quantized switch.
- [ ] Pass · [ ] Fail. Notes:

---

## F. Live control, v0.3

### F1. Ramp curves
- **Type:** *"Ramp the reverb send on track 3 from 0 to 100 over 2 beats with a log curve."* Then *"Sweep the cutoff on track 6 from 20 to 120 over 4 bars, exponential."*
- **Expect:** log rises fast then settles; exp starts slow and finishes fast. Both stay locked to the tempo.
- [ ] Pass · [ ] Fail. Notes:

### F2. Cancel, and set_param overrides a ramp
- **Type:** *"Ramp the cutoff on track 6 from 20 to 127 over 16 bars."* Then *"Set the cutoff on track 6 to 60."*
- **Expect:** the result shows `cancelled_ramp`, and the cutoff jumps to 60 and stays there. *"Cancel all ramps"* returns an empty list.
- [ ] Pass · [ ] Fail. Notes:

### F3. Density, swing, humanize, reset
- **Type:**
  1. *"Thicken the hats."*
  2. *"Thin out the rim."*
  3. *"Swing it to 62."*
  4. *"Loosen it up a bit."* (humanize)
  5. *"Reset the mutations."*
- **Expect:**
  - Ghost 16ths appear on hats track 4 from the next bar.
  - Thinning drops the weakest offbeat rim hits first, and always keeps at least one hit per bar.
  - Swing applies from the next step.
  - With humanize, velocity varies but the groove never drifts. This is only audible if the preset's VELOCITY TO VOL isn't OFF (§15.1 #16), so record that setting.
  - Reset brings the original back on the next bar.
- [ ] Pass · [ ] Fail. VELOCITY TO VOL: ____

### F4. Hardware mute (CC 94; §15.3 Q3)
- **Type:** *"Mute track 2 on the unit itself."* That's `hardware: true`.
- **Expect:**
  - Track 2 is silent. **Record which mute mode lights on the unit:** green global, or magenta pattern.
  - *"Unmute track 2"* releases it on the unit.
  - Mute again, then *"Stop"*: the unit's mute is released too.
- [ ] Recorded: CC 94 drives ____ mute. Pass · Fail:

### F5. Tempo
- **Type:** *"Speed up to 140."*
- **Expect:** the tempo changes on the next tick, and the unit's tempo display and delay follow. No glitch or restart.
- [ ] Pass · [ ] Fail. Notes:

### F6. Queue twice, and a bar limit
- **Type:** *"Switch to soul."* Then, before the bar line, *"Actually, breaks."*
- **Expect:** `replaced_queued: soul`, and breaks lands on the next bar. Then *"Play deep house for 4 bars."* It stops by itself after 4 bars, with a clean stop.
- [ ] Pass · [ ] Fail. Notes:

### F7. Panic with All Notes Off (§15.3 Q5)
- **Setup:** breaks playing (the pad has 16-step gates). Set `amp_hold` 127 on track 8 so its notes are held.
- **Type:** *"Stop"* in the middle of a pad note.
- **Expect:** the pad cuts at once. Whiplash sends per-note note-offs and also CC 123. Whether CC 123 alone silences notes can't be separated from the note-offs here, so record only that the stop was clean.
- [ ] Pass · [ ] Fail. Notes:

---

## G. Digitakt reference fixes (PR #6)

### G1. `loop_pos` range is 0-120 (§15.1 #5)
- **Setup:** track 7 on a Oneshot machine.
- **Type:** *"Set play mode on track 7 to forward loop."* (`play_mode` 2) Then *"Set loop position on track 7 to 127."*
- **Expect:**
  - The result has `value: 120, clamped: true`.
  - On the unit, SRC LOOP shows its maximum, not some other wrapped value.
  - Then *"Set play mode on track 7 to 3."*
- [ ] Pass · [ ] Fail. Unit display at 120: ____

### G2. Machine-dependent knobs (optional)
- If any track uses Werp, Stretch or Repitch, *"Set loop position on track* N *to 2"* should change BARS, not loop position. Record what the unit shows.
- [ ] Recorded: ____

### G3. Grid/Slice with SLICE = NOTE (optional; §15.3 Q8)
- **Setup:** a track on Grid with SLICE = NOTE.
- **Type:** *"Transpose track* N *up 1 semitone"*, and so on.
- **Expect:** different slices play. Record which note plays slice 1.
- [ ] Recorded: ____

### G4. INT TO MAIN while capturing USB audio (§15.3 Q7)
- This is done in part H3 with CONNECT AUDIO. Note whether the unit's main and headphone outs stay on while the browser captures.
- [ ] Recorded: ____

---

## H. Visualiser restyle (PR #8)

### H1. Rack and modules
- **Setup:** deep house playing, visualiser open, window at least 1100 px wide.
- **Expect:**
  - 8 modules, each with a 16-step strip and playhead, trig LEDs and a note readout firing in time with what you hear, LVL and FLT/RES/DEC knobs (`--` until a value is sent), and a bitmap BPM that rolls on a tempo change.
  - The reels turn with the BPM, and the hub pulses on the kick and the downbeat.
  - Strict grayscale.
- [ ] Pass · [ ] Fail. Notes:

### H2. State changes show up
- **Type:** *"Mute track 5"*, *"drop the bass for 2 bars"*, *"ramp the cutoff on track 6 from 30 to 110 over 4 bars"* and *"switch to techno"*.
- **Expect:**
  - Module 5 dims, its bat toggle goes down and its cable goes dashed.
  - Module 6 shows `DROP <N`, flashes inverted, then returns.
  - The FLT knob turns toward its target tick.
  - The transport shows the queued switch with a beat countdown.
  - The module the tool touched blinks its outline.
- [ ] Pass · [ ] Fail. Notes:

### H3. Real audio
- **Type:** press `A`, or click CONNECT AUDIO, and allow the microphone.
- **Expect:**
  - The page picks the Digitakt II USB input, and the label changes to `AUDIO · <device>`.
  - The VU needle follows the real level: try *"Turn track 1 level down to 20"* and watch it drop.
  - Record G4 here too.
- [ ] Pass · [ ] Fail. Notes:

### H4. Keys and layout
- **Expect:**
  - `C` collapses the chat, `T` shows tool calls, `B` blurs the chat, `R` toggles the cables, `F` goes fullscreen and `?` opens help.
  - Narrow the window below 1100 px: the chat becomes lower-third captions.
  - The conversation streams word by word, with the `· hooks` source shown.
- [ ] Pass · [ ] Fail. Notes:

### H5. Close
- **Type:** *"Close the visualiser."*
- **Expect:** the page loses its connection, and the beat keeps playing.
- [ ] Pass · [ ] Fail. Notes:

---

## I. v0.5.1 `whiplash_write_part` (placeholder; do once it is merged)

Another agent is building this on `feat/v051-write-part`. After it merges: `git pull`, **`hermes gateway restart`**, then check that `/plugins` lists 16 tools. The prompts below follow the v0.5 plan (HW 2 and HW 3) and that branch's draft schema. Adjust them to the final README if the merged version differs.

### I1. Melody on the bass track (plan HW 3)
- **Setup:** techno playing, with track 6 on Phil's slot 9 "dirty bass".
- **Type:** *"Play a melody on track 6: C5, D#5, G5, A#4, one note every 4 steps."*
- **Expect:**
  - The melody lands on the next bar.
  - The result echoes the notes, with numbers and names, plus `pitch` and `length_audible`.
  - It sounds like playing those notes in KB mode.
  - Repeat with *"switch track 6 to slot 11"*, Phil's synth.
- [ ] Pass · [ ] Fail. Notes:

### I2. Rhythm presets and lock to kick
- **Type:** *"Make the bass four on the floor."* Then *"Lock the bass to the kick."*
- **Expect:** `rhythm: four_on_floor`, then `lock_to: 1` / `on_kick`. The bass hits exactly with the kick.
- [ ] Pass · [ ] Fail. Notes:

### I3. Note length vs envelope (plan HW 2)
- **Type:** *"Make the bass notes shorter, half a step."* Read `length_audible`. If HOLD isn't NOTE, *"Yes, set the envelope so note length counts."*
- **Expect:** with a fixed HOLD, the length changes nothing. After `envelope: "note"` (one CC 80 = 127), the notes get shorter.
- [ ] Pass · [ ] Fail. Notes:

### I4. Survives reset, cleared by stop
- **Type:** *"Reset the mutations"* (the written part stays), *"switch to breaks"* (it carries over), then *"stop"* and *"play techno"* (the generated bass is back).
- [ ] Pass · [ ] Fail. Notes:

### I5. Tracks 9-16 (only if the kit uses them)
- **Type:** *"Write a pad on track 9, holding A4 for a whole bar."*
- **Expect:** it plays on channel 9. If AUTO CHANNEL or FX CONTROL CH is on 9-16, the result warns.
- [ ] Pass · [ ] Fail. Notes:

---

## J. Hot-plug and port loss (last: it unplugs the cable)

### J1. Unplug mid-beat
- **Setup:** deep house playing.
- **Action:** pull the USB cable, then type *"What's the status?"*
- **Expect:** `port_lost` with the port name, and `last_error` set. The visualiser flashes `PORT LOST`.
- [ ] Pass · [ ] Fail. Notes:

### J2. Replug and resume
- **Action:** replug, wait for the unit, then type *"Play deep house again on the Digitakt."*
- **Expect:** the port is re-detected and the beat plays on the hardware, with no virtual-port warning.
- [ ] Pass · [ ] Fail. Notes:

### J3. Start before the unit is connected (optional)
- **Action:** restart the gateway with the unit unplugged, then *"Play techno."* Then plug it in and type *"Status?"*
- **Expect:** the first result carries the `NO DIGITAKT DETECTED` warning. After plugging in, results carry `device_available` and a notice. Whiplash doesn't switch by itself.
- [ ] Pass · [ ] Fail. Notes:

---

## Recording the results

When a result settles a question in the reference:
- update the relevant part of [docs/digitakt-ii/reference.md](../digitakt-ii/reference.md) (§15.3 open questions, §15.1 statuses, the HW notes in §5-§7 and §10),
- and add a line like `HW: verified by Phil on a Digitakt II, OS x.yy, 2026-11-11 (hardware-checklist B2)`.

Fails go in a GitHub issue, or the next build plan, with the check ID.

| Open question (§15.3) | Check |
| --- | --- |
| Q1 Factory channel settings | 0.2 |
| Q2 Note 60, 48 and 72 on a track channel; KB octave; range | B1, B2, B3, B6 |
| Q3 Which mute mode CC 94 drives | F4 |
| Q4 CC 19 = 0 | E1 |
| Q5 CC 123 | F7 (partial) |
| Q6 Default VELOCITY TO VOL and AMP HOLD | D1, F3 |
| Q7 INT TO MAIN while capturing | G4 / H3 |
| Q8 SLICE = NOTE, slice 1 | G3 |
