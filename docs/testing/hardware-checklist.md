# Hardware test session: Whiplash on a Digitakt II

This is one ordered session for Phil on the Air, with Hermes and a Digitakt II on USB MIDI. It covers everything merged up to **v0.6.0 plus the visualiser's key and chord display** that hasn't been checked on a real unit yet:
- v0.6.0: keys and scales on `whiplash_play_pattern`, chord progressions (`whiplash_set_progression`), and the visualiser's KEY module and per-track chord lines,
- v0.5.3: the kit map (`whiplash_label_tracks`), one-call start (`tracks` on `whiplash_play_pattern`), the `techhouse` genre and aliases, and the shorter tool descriptions (turn latency),
- the visualiser v0.5 update: kit labels, `SMP` slot labels, `NO PART`, written parts as a piano roll, `TRN`/`LEN`/`HLD NOTE` tags, and the tracks 9-16 row,
- v0.5.2: transpose on tracks 9-16, All Notes Off on the 9-16 channels in use, and `amp_hold` 127 (NOTE) only when asked for,
- v0.5.1 `whiplash_write_part` (written melodies, rhythms and note lengths),
- v0.5.0: pitch register, status, the bundled skill and `amp_mode`,
- v0.4 sample select and transport, v0.3 live control, the reference fixes and the visualiser restyle.

Pause/resume (v0.5 plan item 11) is **not** in v0.5.3, so there is nothing to test for it here.

**Nothing in this file is verified yet.** The test suite runs on fake and virtual ports only. As you go, tick Pass or Fail and jot a note. Afterwards, record each result in [docs/digitakt-ii/reference.md](../digitakt-ii/reference.md) with who tested it, the date and the OS version (CLAUDE.md rule). Each check names the reference section or open question (§15.3 Qn) it settles.

**Order:**
- **Part A (about 10 min)** is the smoke test. It is the hackathon demo path, prompt for prompt ([docs/demo/hackathon-demo.md](../demo/hackathon-demo.md)), so if A passes, the demo is safe. Stop there if time is short.
- **Part B** covers v0.5.3 in depth: kit map, one-call start, tech house, latency. It is the newest code.
- **Part C** covers written parts (v0.5.1), **Part D** the v0.5.2 fixes, and **Part E** the visualiser.
- **Part P** (after E) covers v0.6.0 keys and chord progressions (plan HW 6.0-1 to 6.0-5). P1 is the demo's optional encore: run it before using the encore on stage.
- **Parts F-K** go deeper into older features, most important first.
- **Part L** unplugs the cable, so it comes last.

Type the prompts as written; *italic* text in a prompt is a placeholder. If Hermes picks a different tool or argument than expected, note it: that's useful too. The prompts below assume Phil's project 6 as of Nov 11 (tracks 7-8 tuned cymbals, slot 9 a "dirty bass", slot 11 a synth). If your kit differs, change the labels in A2 and keep the rest.

---

## 0. Before you start (5 min)

### 0.1 Update and restart the gateway

```bash
git -C ~/whiplash pull          # symlinked checkout; or: hermes plugins update whiplash
hermes gateway restart          # required: the gateway keeps old plugin code until it restarts
hermes plugins list             # whiplash -> enabled (v0.6.0, 18 tools)
```

A new chat is **not** enough after an update. Only `hermes gateway restart` loads the new code. If `hermes plugins list` still shows 17 tools or v0.5.3, the gateway didn't restart: run it again.

If Hermes earlier auto-created a local skill for Whiplash, delete it. Look for `~/.hermes/skills/whiplash-digitakt/` or anything similar under `~/.hermes/skills/`. It holds stale claims such as "can't switch samples".

Start a **new chat** after the restart, so the kit map and the conversation start empty.

### 0.2 On the unit

- [ ] **SETTINGS > MIDI CONFIG > PORT CONFIG:** INPUT FROM = USB (or MIDI+USB), RECEIVE NOTES on, RECEIVE CC/NRPN on.
- [ ] **SYNC:** CLOCK RECEIVE on, TRANSPORT RECEIVE on.
- [ ] **CHANNELS:** TRACK 1-8 = channels 1-8. **Write down AUTO CHANNEL, FX CONTROL CH and PRG CHG IN CH as you find them** (this answers §15.3 Q1). Then move AUTO and FX CONTROL off channels 1-12, or set them to OFF (parts C and D write on 10 and 11).
- [ ] **USB CONFIG = USB AUDIO/MIDI**, which E3 needs for real audio. MIDI works in this mode too.
- [ ] **Select an empty pattern** in the project you'll demo with. Otherwise MIDI Start also plays the unit's own trigs.
- [ ] **Reload the pattern** with [FUNC] + [NO] so that earlier edits (for example tune +12 on the bass track) are gone. Every check below assumes TUNE = 64 and an unchanged preset OCTAVE.

**Cleanup at the end:** every Whiplash parameter change sticks in the active pattern's kit until you reload. When you're done, press [FUNC] + [NO], and **don't save the project**. Whiplash never saves anything.

---

## A. Smoke test and demo path, 10 minutes

This is the hackathon demo ([docs/demo/hackathon-demo.md](../demo/hackathon-demo.md)) in the same order, with the checks behind each step. **Time each turn** (from Enter to Hermes's answer) and write it next to the check: that is the latency metric for the v0.5.3 shorter tool descriptions (plan item 10).

### A1. Connected, and the visualiser opens
- **Type:** *"Is my Digitakt connected? And launch the visualiser."*
- **Expect:**
  - `whiplash_list_midi_ports` finds *Elektron Digitakt II*, with no `warning` about a virtual port.
  - `whiplash_open_view` opens `http://127.0.0.1:7341` in the browser and shows the idle rack: a tape transport, the hub, a master OUT and the port name.
- **Optional:** click CONNECT AUDIO (or press `A`) now, so the VU follows the real mix for the rest of the run (E3 checks it in depth).
- [ ] Pass · [ ] Fail. Turn time: ____ s. Notes:

### A2. Label the kit (v0.5.3 `whiplash_label_tracks`)
- **Type:** *"Tracks 7 and 8 are tuned cymbals. Sample slot 9 is my dirty bass, and slot 11 is a synth I like."*
- **Expect:**
  - **One** call: `whiplash_label_tracks(tracks: {"7": "tuned cymbal", "8": "tuned cymbal"}, slots: {"9": "dirty bass", "11": "synth ..."})`, with no `tool_describe` first.
  - The result's `kit` shows tracks 7 and 8 as role `cymbal`, and the two slot labels. `applies` is `next whiplash_play_pattern` (nothing plays yet).
  - **Nothing is sent to the unit.** Nothing changes on its screen.
- [ ] Pass · [ ] Fail. Turn time: ____ s. Notes:

### A3. One-call start: deep house on the labelled kit, with the dirty bass (v0.5.3 items 7 and 8)
- **Type:** *"Play some groovy deep house with the dirty bass on track 6."*
- **Expect:**
  - **One** `whiplash_play_pattern(genre: "deephouse", tracks: {"6": {"slot": 9}})`, not a play followed by `whiplash_select_sample`.
  - The result echoes `setup` for track 6 with `slot_label: "dirty bass"`, and `tracks["6"].pitch` low 52, high 65, with no `register_shift`.
  - `tracks` (play results carry no `routing` field; `whiplash_label_tracks` and `whiplash_status` describe the kit): kick, rim, clap, closed hat and bass on 1-4 and 6; the **open hat part moves to track 7** (open hat -> cymbal is a close role), so track 7 shows the open-hat line under your label; there are no chord parts anywhere, and track 8 has no part. If you want the routing spelled out, ask *"How did you route the beat onto my kit?"*: Hermes can re-send the labels, whose result carries `routing` (chords `dropped`, track 8 `silent_until_written`).
  - Hermes passes on the `overlap_warning`.
- **Listen:**
  - 122 BPM with swing. **No chords on the tuned cymbals.** Track 7 plays the open-hat rhythm, and track 8 is silent.
  - **The very first bass note is already slot 9** (§15.3 Q10, fresh start: CC 19 goes out just before MIDI Start). If the first note or bar plays the old sample, note it.
  - Nothing from the unit's own pattern layered in.
- **Look (visualiser):**
  - Modules 7 and 8 show your label (`tuned cymbal`) as their role in **white**; hovering shows `kit map: tuned cymbal (cymbal)`. The other roles stay gray (assumed).
  - Module 6 has an `SMP 009 dirty bass` tag.
  - Module 8 shows `NO PART`. There is no module 5 (nothing is routed there).
  - Trig LEDs fire in time with what you hear.
- [ ] Pass · [ ] Fail. First bass note on slot 9: ____. Turn time: ____ s. Notes:

### A4. Filter sweep (v0.3 ramp)
- **Type:** *"Close the filter on the bass, then open it slowly over 8 bars."*
- **Expect:** a `whiplash_set_param` on track 6 `filter_freq` (about 20), then a `whiplash_ramp_param` to about 110 over 8 bars. The sweep is smooth, with no zipper steps, and lasts 8 bars. On the visualiser, the FLT knob turns toward its target tick.
- [ ] Pass · [ ] Fail. Turn time: ____ s. Notes:

### A5. A melody on the silent cymbal track (v0.5.1 `whiplash_write_part`)
- **Type:** *"Give track 8 a melody: eighth notes in A minor, degrees 1 3 5 8 7 5 3 1, length 2."*
- **Expect:**
  - `whiplash_write_part(track: 8, rhythm: "8ths", key: "A", scale: "minor", notes: "1 3 5 8 7 5 3 1", length: 2)` or equivalent (`key: "Am"` works too).
  - The result echoes each bar as a grid with note numbers and names, `pitch` around A4-A5 (about −3 to +9 from native), and `length_audible`. Hermes should **not** change the envelope on its own.
- **Listen:**
  - The melody starts on a bar line. The pitches are distinct and follow the line, not stretched or grainy. The clock stays steady.
  - Whether `length 2` is audible depends on track 8's AMP HOLD/MODE (C3 checks it). Don't change the envelope during the smoke test.
- **Look:** module 8 swaps `NO PART` for `WR`, its strip becomes a piano roll with the notes you hear, a `LEN 2` tag (dashed: Whiplash hasn't sent ADSR or HOLD = NOTE), and the module flashes inverted when the part lands.
- [ ] Pass · [ ] Fail. Turn time: ____ s. Notes:

### A6. Drop with a fill (v0.3 mutate)
- **Type:** *"Drop the kick and bass for two bars with a fill."*
- **Expect:**
  - Kick and bass go silent from the next bar. The tuned-cymbal melody keeps playing.
  - A snare/rim roll and hat ratchets play on the second dropped bar.
  - Kick and bass come back exactly on the one.
  - On the visualiser, modules 1 and 6 show `DROP <N` with a countdown and flash inverted when it starts.
- [ ] Pass · [ ] Fail. Turn time: ____ s. Notes:

### A7. Switch to tech house on the next bar (v0.5.3 item 9)
- **Type:** *"Switch to tech house on the next bar."*
- **Expect:**
  - `whiplash_play_pattern(genre: "techhouse")` (the words "tech house" resolve; no error, no second try). The result says `mode: "queued"`.
  - The switch lands on a bar line at 126 BPM with no Stop/Start: the unit's delay keeps ringing in time.
  - The kit map applies the same way as in A3: the open hat goes to track 7, the stab and perc parts are dropped (no track for them), and track 8 keeps its **written melody** (written parts carry across switches). Check it in `tracks` or in A8's status, not in a `routing` field (play results have none).
  - `tracks["6"].pitch` low 55, high 62 (G4-D5), no `register_shift`.
- **Listen:** four on the floor, an offbeat open hat (on the cymbal), 16th hats with accents, and a rolling off-beat bass that never lands on the kick. The bass is still the dirty bass (slot 9: the unit keeps the CC 19 change). The melody on 8 carries on.
- **Look:** the BPM readout rolls to 126; the transport shows the queued switch with a beat countdown first.
- [ ] Pass · [ ] Fail. Turn time: ____ s. Notes:

### A8. Status is honest about the kit
- **Type:** *"What's playing? Give me the per-track details."*
- **Expect:**
  - `whiplash_status` with `roles_assumed: false`. Tracks 7 and 8 show your labels as `role` (no "(assumed)") and `kit_role: "cymbal"`; unlabelled tracks keep `(assumed)`.
  - Track 6 shows `slot: 9` with `slot_label: "dirty bass"`, `tune: null` (never sent), and `filter_freq` under `last_cc`.
  - Track 8 shows `part: "written"`, and `parts` lists it.
  - Hermes describes the kit in your terms and doesn't call track 7 "chords".
- [ ] Pass · [ ] Fail. Turn time: ____ s. Notes:

### A9. Clean stop, kit map kept
- **Type:** *"Stop."*
- **Expect:**
  - Silence right away, with no hanging notes. The unit's sequencer stops, and the visualiser reels stop.
  - Then *"Play techno"*: track 8 is silent again (the written melody was cleared by stop), and the tuned cymbals still get no stab or chords (the **kit map survived** the stop).
  - *"Stop"* again before moving on.
- [ ] Pass · [ ] Fail. Notes:

**If A1-A9 pass, the demo is safe.** Write down the turn times: the median and the slowest turn are the soft latency metric (plan item 10). On Nov 11, before v0.5.3, turns took 5-40 s.

---

## B. v0.5.3 in depth: kit map, one-call start, tech house, latency (plan items 7-10; §15.1 #26-27; §15.3 Q10-11)

**Setup:** new chat, empty pattern selected on the unit, pattern reloaded with [FUNC] + [NO]. Start with *"Clear the kit map"* (`whiplash_label_tracks(reset: true)`).

### B1. Free text is matched to a role, and labels merge
- **Type, in order:**
  1. *"Track 2 is a rimshot, track 3 is a handclap, track 5 is a ride."*
  2. *"Label track 7 as a chord and call it Rhodes."*
  3. *"Forget the label on track 3."*
- **Expect:**
  - Step 1: roles `rim`, `clap` and `cymbal`, each with your text as `label`.
  - Step 2: `{role: "chord", label: "Rhodes"}`, and tracks 2, 3 and 5 are still there (calls merge).
  - Step 3: `{"3": null}`; track 3 is gone from `kit`, the rest stay.
  - Nothing is sent to the unit at any step.
- [ ] Pass · [ ] Fail. Notes:

### B2. Bad labels change nothing
- **Type:** *"Label track 17 as a kick."* Then *"Label slot 200 as a pad."*
- **Expect:** both are refused (track 1-16, slot 0-127), and `whiplash_status` shows the map from B1 unchanged.
- [ ] Pass · [ ] Fail. Notes:

### B3. Re-routing at the next bar while playing
- **Setup:** *"Clear the kit map and play techno."*
- **Type:** *"Track 5 is a pad and track 8 is a lead."*
- **Expect:**
  - The result says `applies: "next bar"` with `at_bar`.
  - `routing`: the techno stab moves from track 7 to **track 8** (stab -> lead is a close role), the open hat and perc parts are `dropped`, and track 5 is `silent_until_written`.
- **Listen:** from the next bar line, not mid-bar: the open hat stops, the stab plays on track 8's sound, track 7 goes quiet. The clock doesn't stutter, and swing is unchanged.
- **Note:** a labelled close role beats an unlabelled default track here (the stab leaves unlabelled track 7). That is the documented order; say if it feels wrong musically.
- [ ] Pass · [ ] Fail. Notes:

### B4. The kit map survives stop and switches; reset clears it
- **Type:** *"Switch to breaks."* Then *"Stop"*, then *"Play techno."* Then *"Clear the kit map."*
- **Expect:**
  - Breaks and the restarted techno both follow the labels from B3 (`roles_assumed: false`).
  - After the reset, the result is empty, and the next bar plays the default layout again (stab back on track 7, open hat on 5).
- [ ] Pass · [ ] Fail. Notes:

### B5. One-call start with slot, tune, transpose and mute (fresh start; §15.3 Q10, Q11)
- **Setup:** *"Stop."* Label the slots: *"Slot 11 is my synth."*
- **Type:** *"Play techno with my synth on track 6, tune at 64, an octave up, and track 8 muted."*
- **Expect:**
  - **One** `whiplash_play_pattern(genre: "techno", tracks: {"6": {"slot": 11, "tune": 64, "transpose": 12}, "8": {"mute": true}})`.
  - The result echoes `setup` with `slot_label`. `tracks["6"].pitch` is about 65 (12 above the 53 techno bass), with `transpose: 12`.
- **Listen:**
  - The **first** bass note is already slot 11, an octave up (Q10, fresh start).
  - Track 8 is silent from the first bar.
  - **Q11:** on the unit, open track 6 SRC and read TUNE. Does it show 64 (Whiplash's CC 16 after the slot change), or did the slot change bring another value? Whiplash sends slot first, then tune.
- [ ] Pass · [ ] Fail. First note on slot 11: ____. TUNE after: ____

### B6. One-call setup on a queued switch
- **Type, while B5 plays:** *"Switch to tech house on the next bar with the dirty bass on track 6 and unmute track 8."* (Label slot 9 first if B5 started from a clean map: *"Slot 9 is my dirty bass."*)
- **Expect:**
  - `mode: "queued"` with `setup`. Nothing changes until the bar line.
  - At the switch bar: track 6 plays slot 9 from the bar's **first** note (Q10, queued: CC 19 goes out at the bar line, right before its first note), and track 8 comes back on that same bar.
  - The transpose of 12 on track 6 carries over (the tech house bass sits an octave above its own G4-D5).
- [ ] Pass · [ ] Fail. First switched note on slot 9: ____. Notes:

### B7. A bad entry rejects the whole call
- **Type, while tech house plays:** *"Switch to breaks with slot 5 on track 6 and mute track 20."*
- **Expect:** an error about track 20 (or a schema refusal from Hermes). **Nothing changes:** tech house keeps playing, no switch is queued, and track 6 stays on slot 9 (the slot CC was never sent).
- **Also try:** *"Switch to breaks, transpose track 6 up 12, and in the track setup set track 6's transpose to -12."* That should be refused as "transpose given twice with different values", with no change.
- [ ] Pass · [ ] Fail. Notes:

### B8. Tech house, aliases and moods
- **Type:** *"Stop."* Then *"Play something bouncy."* Then *"Stop"* and *"Play tech-house at 124."* Then *"Play tek house."*
- **Expect:**
  - "bouncy" resolves to `techhouse` at 126 BPM, 56% swing. "tech-house" resolves at 124 BPM.
  - "tek house" either resolves (Hermes corrects it) or the error lists `techhouse` / `tech house` among the closest matches. Hermes should not silently pick another genre.
  - With no labels: four on the floor, a sparse rim, clap on 2 and 4, accented 16th hats, offbeat open hat, off-beat bass (A4 around note 57, never on a kick step), a sparse stab on track 7 and perc on 8.
- [ ] Pass · [ ] Fail. Notes:

### B9. Fewer round trips (plan item 10)
- **Setup:** a new chat, so Hermes has no cached tool descriptions.
- **Type, one at a time:** *"Play deep house."*, *"Thin out the hats."*, *"Mute track 3."*, *"Stop."*
- **Expect:** each turn makes the one Whiplash call it needs, with no `tool_describe` or `skill_view` before acting. Hermes may open `whiplash:digitakt` once for a complex ask (A2-A3 style), not for these.
- [ ] Pass · [ ] Fail. Turn times: ____ / ____ / ____ / ____ s. `tool_describe` calls: ____

---

## C. Written parts, v0.5.1 `whiplash_write_part` (plan HW 2 and HW 3; §15.3 Q9)

**Setup:**
- Select an empty pattern on the unit, or use clock only.
- *"Clear the kit map"*, so tracks follow the default layout.

Written parts sit around C5 (note 60 = native pitch). They carry across pattern switches and `whiplash_mutate reset`, and `reset: true` or *"stop"* clears them.

### C1. Melody on slot 9, then slot 11 (HW 3)
- **Type:** *"Play techno with slot 9 on track 6, and write a melody on track 6: eighth notes, A minor, degrees 1 3 5 8 7 5 3 1, length 2."* Then *"Now switch track 6 to slot 11, keep the melody."*
- **Expect:**
  - The pitches are distinct and follow the line. Each one sounds like pressing that key in KB mode, not stretched or grainy.
  - `pitch` is around A4-A5 (−3 to +9 from native).
  - The melody starts on a bar line, and slot 11 plays the same notes.
- [ ] Pass · [ ] Fail. Notes:

### C2. Four on the floor, lock to the kick, carry over, reset
- **Type, in order:**
  1. *"Make the bass on track 6 four on the floor, note A4."*
  2. *"Now lock the bass to the kick instead, alternating A4 and C5."*
  3. *"Switch to soul."*
  4. *"Reset the bass to the generated line."*
- **Expect:**
  - Step 1: bass on every beat.
  - Step 2: bass hits exactly on the kick hits.
  - Step 3: the part carries into soul. The rhythm stays as it was copied; it doesn't follow soul's kick live.
  - Step 4: the generated bass is back.
- [ ] Pass · [ ] Fail. Notes:

### C3. Length with a fixed HOLD vs HOLD = NOTE vs ADSR (HW 2)
- **Setup:** on the unit, set track 6 AMP HOLD to a fixed value (for example 60), with DEC fairly short.
- **Type:** *"Write track 6 as 8ths on C5 with length 0.25"*, then *"same with length 2"*.
  - **Expect:** no audible difference. The result's `length_audible` explains why.
- **Type:** *"Same part, length 0.25, and set the envelope to note."*
  - **Expect:** exactly one CC 80 = 127 goes out, and the unit's HOLD shows **NOTE**. The notes get short, and *"length 2"* makes them longer.
- **Type:** *"Set amp_mode to ADSR on track 6, sustain 100, release 20"*, then try lengths 0.25 and 2.
  - **Expect:** length plus release shape the tail.
- **Afterwards:** *"Set amp mode on track 6 back to 0"*, or reload the pattern.
- [ ] Pass · [ ] Fail. Record: fixed HOLD ____, NOTE ____, ADSR ____

### C4. Rhythm presets
- **Type, on a hat or perc track:** *"Write track 8 as offbeat 8ths"*, then *"syncopated"*, *"half time"* and *"16ths"*.
- **Expect:** each change lands on the next bar, and the clock stays steady.
- [ ] Pass · [ ] Fail. Notes:

### C5. Drops and mutes apply to a written part
- **Type:** *"Drop track 6 for 2 bars with a fill"*, then *"mute track 6"*, then *"unmute track 6"*.
- **Expect:** the written part goes silent and comes back each time.
- [ ] Pass · [ ] Fail. Notes:

### C6. Retriggering a long note (§15.1 #24)
- **Type:** *"Write track 6 as 8ths, all on C5, length 4."*
- **Expect:** each new hit restarts the note cleanly; a held note never cuts off its successor. Record whether the unit retriggers or layers voices.
- [ ] Pass · [ ] Fail. Retrigger / layer: ____

### C7. Tracks 9-16 (optional, if the kit uses them)
- **Setup:** first confirm on the unit that AUTO CHANNEL and FX CONTROL CH are not on channel 10.
- **Type:** *"Write a melody on track 10: C5 E5 G5 B5, quarter notes."*
- **Expect:** it plays on track 10, and the result carries a `channel_note`.
- [ ] Pass · [ ] Fail. Notes:

### C8. Stop clears written parts
- **Type:** *"Stop."*, then *"play techno"*.
- **Expect:** the generated parts are back, and no written part lingers.
- [ ] Pass · [ ] Fail. Notes:

---

## D. v0.5.2 fixes (PR #11; the v0.5.0 review findings)

**Setup:**
- Select an empty pattern on the unit.
- Check that AUTO CHANNEL and FX CONTROL CH are not on channels 10-12.
- Leave slots 1-3 alone.

### D1. Transpose applies to a written part on track 10
- **Type:** *"Play techno at 124."* Then *"On track 10, play C5 on every 8th note."* Then *"Transpose track 10 up an octave."*
- **Expect:** from the next bar, track 10's line jumps up an octave with the same rhythm. The result shows `transpose: 12` and pitch C6.
- [ ] Pass · [ ] Fail. Notes:

### D2. Transpose on an empty track is refused
- **Type:** *"Transpose track 11 up 5 semitones."* Track 11 has no part.
- **Expect:** Hermes reports an error ("plays nothing … write one with whiplash_write_part first"), and nothing changes in the beat.
- [ ] Pass · [ ] Fail. Notes:

### D3. Stop silences tracks 9-16 too (§15.3 Q5)
- **Setup:** keep D1's part playing on track 10, and give it a long sound: *"Set amp_hold on track 10 to note"* and *"amp_decay 127 on track 10."*
- **Type:** *"Stop."*
- **Expect:** everything goes silent at once, including track 10.
- **Optional, with a MIDI monitor:** CC 123 goes out on channels 1-8 and 10 only.
- [ ] Pass · [ ] Fail. Notes:

### D4. An explicit 127 or "note" sets HOLD = NOTE, and says so (§15.3 Q9)
- **Type:** *"Play techno."* Then *"Set amp_hold on track 6 to 127."*
- **Expect:** the result says `hold: "NOTE"`, and Hermes tells you it changed the kit's envelope. On the unit, AMP > HOLD shows NOTE.
- [ ] Pass · [ ] Fail. Notes:

### D5. A ramp stops at 126, not NOTE
- **Type:** *"Ramp amp_hold on track 6 from 20 to 127 over 4 bars."*
- **Expect:** the result says the ramp stops at 126 (`hold_note`). Afterwards, the unit's HOLD reads 126, not NOTE, and note lengths no longer change the sound.
- [ ] Pass · [ ] Fail. Notes:

### D6. 126 is a fixed hold
- **Type:** *"Set amp_hold on track 6 to 126."*
- **Expect:** HOLD shows 126.
- **Afterwards:** reload the kit with [FUNC] + [NO].
- [ ] Pass · [ ] Fail. Notes:

---

## E. Visualiser (restyle PR #8, v0.5 update PR #13)

### E1. Rack and modules
- **Setup:** *"Clear the kit map and play deep house"*, visualiser open, window at least 1100 px wide.
- **Expect:**
  - 8 modules, each with a 16-step strip and playhead, trig LEDs and a note readout firing in time with what you hear, LVL and FLT/RES/DEC knobs (`--` until a value is sent), and a bitmap BPM that rolls on a tempo change.
  - Note names under the readout use Elektron numbering: the deep house bass range reads `E4-F5` (52-65), not `E3-F4`.
  - The reels turn with the BPM, and the hub pulses on the kick and the downbeat.
  - Strict grayscale. All roles are gray (assumed).
- [ ] Pass · [ ] Fail. Notes:

### E2. State changes show up
- **Type:** *"Mute track 5"*, *"drop the bass for 2 bars"*, *"ramp the cutoff on track 6 from 30 to 110 over 4 bars"* and *"switch to techno"*.
- **Expect:**
  - Module 5 dims, its bat toggle goes down and its cable goes dashed.
  - Module 6 shows `DROP <N`, flashes inverted, then returns.
  - The FLT knob turns toward its target tick.
  - The transport shows the queued switch with a beat countdown.
  - The module the tool touched blinks its outline.
- [ ] Pass · [ ] Fail. Notes:

### E3. Real audio (and §15.3 Q7)
- **Type:** press `A`, or click CONNECT AUDIO, and allow the microphone.
- **Expect:**
  - The page picks the Digitakt II USB input, and the label changes to `AUDIO · <device>`.
  - The VU needle follows the real level: try *"Turn track 1 level down to 20"* and watch it drop.
  - **Q7:** note whether the unit's main and headphone outs stay on while the browser captures (INT TO MAIN).
- [ ] Pass · [ ] Fail. Main outs while capturing: ____

### E4. Kit labels, slot labels and NO PART (PR #13)
- **Type:** *"Track 7 is a tuned cymbal, track 8 is a pad, slot 11 is my synth."* Then *"Put my synth on track 6."*
- **Expect:**
  - From the next bar, module 7's role reads your label in **white**; hovering shows `kit map: tuned cymbal (cymbal)`. Module 8 likewise (`pad`). Unlabelled modules stay gray, and hovering says "assumed role".
  - Module 8 shows **`NO PART`** (dashed tag) and stays silent: the techno stab goes to a lead or chord track, never to a pad, and the perc part's default track is now labelled. Module 7 plays the open-hat rhythm (open hat -> cymbal).
  - Module 6 shows `SMP 011 synth` after the second prompt.
- [ ] Pass · [ ] Fail. Notes:

### E5. Written parts, transpose and envelope tags (PR #13)
- **Type:** *"Write a melody on track 8: C5 E5 G5 B5 in 8ths, length 2."* Then *"Transpose track 8 up an octave."* Then *"Set amp_hold on track 8 to note."*
- **Expect:**
  - Module 8 swaps `NO PART` for `WR`, flashes inverted when the part lands, and its strip becomes a piano roll whose notes match what you hear. The range reads `C5-B5`.
  - A dashed `LEN 2` tag (Whiplash hasn't sent ADSR or HOLD = NOTE yet).
  - After the transpose, from the next bar: `TRN +12`, and the range reads `C6-B6`.
  - After the hold: an `HLD NOTE` tag, and `LEN 2` turns solid.
- [ ] Pass · [ ] Fail. Notes:

### E6. Tracks 9-16 get their own row (PR #13)
- **Setup:** AUTO CHANNEL and FX CONTROL CH off channel 11.
- **Type:** *"On track 11, write A4 on the downbeat and on beat 3, length 4, envelope note."*
- **Expect:**
  - Module 11 appears in a separate row headed `TRK 9-16 · CHECK AUTO / FX CONTROL CH`, with `WR`, `HLD NOTE` and `LEN 4` (solid).
  - Modules 1-8 don't move or reflow.
  - *"Stop"*: the row disappears with the written part.
- [ ] Pass · [ ] Fail. Notes:

### E7. Keys and layout
- **Expect:**
  - `C` collapses the chat, `T` shows tool calls, `B` blurs the chat, `R` toggles the cables, `F` goes fullscreen and `?` opens help.
  - Narrow the window below 1100 px: the chat becomes lower-third captions.
  - The conversation streams word by word, with the `· hooks` source shown.
- [ ] Pass · [ ] Fail. Notes:

### E8. Key, chords and chord lines (v0.6.0)
- **Setup:** do this during P1 (Part P, below), visualiser open, window at least 1100 px wide.
- **Expect:**
  - A full-width **KEY** module under the tape/hub/master row reads `A MINOR` with a `SET` tag, and `4 CHORDS · 2 BARS EACH · CLOSE · LOOP 8`.
  - One cell per chord: the numeral as typed, case kept (`i VI III VII`: lower case = minor), the chord name (`Am F C G`) and its voiced notes.
  - The chord playing is an inverted (white) cell with one small square per bar of the chord. The next chord has a dashed border, and four LEDs fill on its cell during the last bar before the change.
  - The highlight moves **on the one**, with the chord you hear, not a beat late. The new cell flashes once.
  - `FOLLOW · 6 ROOT · 7 CHD` under the cells. Module 6 shows a chord line such as `ROOT A4 > F4 @3`: the note it plays in this chord, then in the next one, and the bar of the change. Module 7 shows `CHD` with the chord tones it plays. Drum modules and the cymbal on 8 show no chord line.
  - *"Clear the progression"*: the cells go, `NO PROGRESSION` shows, the key stays. *"Stop"*: the KEY module disappears.
  - *"Play techno"* (no key given): the module reads `F MINOR` with a `HOME` tag. *"Switch to breaks in A minor on the next bar"*: `NEXT KEY A MINOR @N` until the switch.
- [ ] Pass · [ ] Fail. Highlight on the one: ____

### E9. Close
- **Type:** *"Close the visualiser."*
- **Expect:** the page loses its connection, and the beat keeps playing.
- [ ] Pass · [ ] Fail. Notes:

---

## P. Keys and chord progressions, v0.6.0 (plan HW 6.0-1 to 6.0-5; §15.1 #28-29; §15.3 Q12-13)

Rehearse P1 offline first: `uv run python scripts/rehearse_demo.py --speed 4 --v06` (no unit needed) must end in `RESULT: PASS`. That checks the MIDI, not the sound.

### P1. i-VI-III-VII in A minor, two bars per chord (HW 6.0-1; the demo's encore)
- **Setup:** after Part A (tracks 7-8 labelled tuned cymbals), visualiser open.
- **Type:** *"Track 7 is a pad now. Play deep house in A minor with the dirty bass on 6 and my synth on 7: i-VI-III-VII, two bars per chord."*
- **Expect:**
  - Hermes calls `whiplash_label_tracks`, `whiplash_play_pattern` (key A minor, slots 9 and 11) and `whiplash_set_progression`. The result lists tracks `6: root, 7: chords` and nothing else.
  - The chord changes every 2 bars, **on the one**: Am, F, C, G, then back to Am.
  - Track 6 plays each chord's root. Track 7 plays chord tones.
  - The drums sound unchanged. Track 8 (tuned cymbal) plays its open-hat rhythm, never a chord tone.
  - Nothing sounds out of key against a held A minor note in KB mode.
  - The visualiser follows (E8).
- [ ] Pass · [ ] Fail. Notes:

### P2. How many notes does one audio track sound? (HW 6.0-2; §15.3 Q12)
- **Type:** *"Stack the chords on track 7."* (`tracks: {"7": "stack"}`)
- **Expect:** record what you hear: one note of the chord, all three, or a cut-off note. This decides whether `stack` becomes the chord-track default.
- [ ] Recorded: ____

### P3. Two chord tracks sound the chord across tracks (HW 6.0-3; §15.3 Q13)
- **Type:** *"Track 8 is a pad too."*
- **Expect:** from the next bar, `whiplash_status` shows tracks 7 and 8 both in `chords` mode. Each hit sounds like the chord spread across the two tracks, on different tones.
- [ ] Pass · [ ] Fail. Notes:

### P4. A cymbal never gets chords (HW 6.0-4)
- **Type:** *"Track 8 is a tuned cymbal."* Then *"Put chords on track 8."*
- **Expect:** Hermes reports a refusal (cymbal), and track 8 keeps playing what it played.
- [ ] Pass · [ ] Fail. Notes:

### P5. Techno in A minor (HW 6.0-5)
- **Type:** *"Stop."* Then *"Play techno in A minor."*
- **Expect:** the bass moves from F to A. The drums sound unchanged. No stretched or grainy bass (the register check). The visualiser's KEY module reads `A MINOR · SET`.
- [ ] Pass · [ ] Fail. Notes:

---

## F. Pitch and register, v0.5.0 (plan HW 1; §15.3 Q2)

**Setup:** *"Clear the kit map."*

### F1. Note 60 is native pitch on a track channel
- **Setup:** KEYBOARD mode **off**. Track 1 holds a pitched or recognisable sample, TUNE = 64.
- **Type:** *"Play techno."* Then compare the kick against pressing [TRIG 1] on the unit, or previewing the track-1 sample.
- **Expect:** the pitch is identical. Whiplash's drum parts are note 60.
- [ ] Pass · [ ] Fail. Notes:

### F2. An octave down and up (notes 48 and 72)
- **Type:** *"Transpose track 1 down one octave."* Wait 2 bars. Then *"Now up one octave."* Then *"Put track 1 back to normal."*
- **Expect:**
  - Each change lands on the next bar line.
  - `pitch` shows 48, then 72, then no transpose.
  - You hear an exact octave each way.
- [ ] Pass · [ ] Fail. Notes:

### F3. The KB octave doesn't affect track channels
- **Setup:** turn KEYBOARD mode on and shift the KB octave with [KEYBOARD] + [UP] twice, while techno plays.
- **Expect:** Whiplash's pitches don't change. Then turn KB mode off: the KB octave setting is unchanged by Whiplash's notes.
- [ ] Pass · [ ] Fail. Notes:

### F4. The techno bass no longer sounds stretched (v0.5.0 item 1)
- **Type:** *"Play techno."*
- **Expect:** `tracks["6"].pitch` shows low/high 53, `semitones_from_native` [-7, -7] and `register_shift` 12.
- **Listen:** with TUNE at 64, the track-6 bass should sound like the Nov 11 tune +12 fix: not stretched or grainy.
- [ ] Pass · [ ] Fail. Notes:

### F5. Transpose at start, and carry over a switch
- **Type:** *"Play breaks with the bass an octave down."* This should call `whiplash_play_pattern` with `transpose: {"6": -12}` (or `tracks: {"6": {"transpose": -12}}`). Then *"Switch to soul on the next bar."*
- **Expect:**
  - Breaks bass `pitch` low 41. The queued result's `tracks["6"].transpose` = -12, and `transpose_carried` lists it.
  - After the switch, the soul bass plays 12 below its new register.
  - *"Stop"*, then *"play soul"*: the transpose is gone.
- [ ] Pass · [ ] Fail. Notes:

### F6. Tune shows up in `pitch`
- **Type:** *"Set tune on track 6 to 76."* Then *"What's the pitch on track 6?"*
- **Expect:**
  - `tracks["6"].tune` = 76, and `semitones_from_native` goes up by 12.
  - You hear an octave up.
  - Then *"Set tune on track 6 back to 64."*
- [ ] Pass · [ ] Fail. Notes:

### F7. Range edge (optional)
- **Type:** *"Transpose track 8 up 4 octaves."*
- **Expect:** `pitch` reports `clamped: true`, with high 84. Notes above 84 are held at 84, so whether the unit plays them as expected on a track channel answers the "usable note range" part of Q2.
- [ ] Pass · [ ] Fail. Notes:

---

## G. Bundled skill and updating, v0.5.0 (plan HW 4)

### G1. The plugin and skill load after a gateway restart
- **Type:** `/plugins`, then *"List your skills. Is whiplash:digitakt there? Open it and tell me what it says about the kit map and pitch."*
- **Expect:**
  - whiplash is enabled, v0.5.3.
  - `skills_list` shows `whiplash:digitakt`.
  - `skill_view("whiplash:digitakt")` returns the "Fast path: label, then start in one call" section and the "note 60 plays a sample at its own pitch" section.
  - No stale local `whiplash-digitakt` skill appears alongside it.
- Note the Hermes version (`hermes --version`; v0.23.1 was expected). If the skill is missing, check the gateway log for `skill skipped`: that means this build has no `ctx.register_skill`.
- [ ] Pass · [ ] Fail. Notes:

### G2. The skill steers diagnostics
- **Setup:** techno playing, then *"Transpose track 6 down two octaves."* (This is the generated techno bass, so no written part should be active: *"stop"* and *"play techno"* first if one is.)
- **Type:** *"The bass sounds stretched and grainy, fix it."*
- **Expect:** Hermes checks `pitch` and transposes up, or sets tune, **before** touching the envelope or density. Count the tool calls.
- [ ] Pass · [ ] Fail. Notes:

### G3. The skill steers kit questions
- **Type:** *"Why are there cymbals playing chords?"* (with no labels set).
- **Expect:** Hermes says the roles are assumed and asks what the tracks hold, or offers `whiplash_label_tracks`, rather than changing density or samples.
- [ ] Pass · [ ] Fail. Notes:

---

## H. Note length and the amp envelope, v0.5.0 `amp_mode` (part of plan HW 2; §15.3 Q6)

Generated parts send note-off at 0.8 of their gate, so the difference is audible on the soul or breaks bass (gates of 3-4 steps) and the breaks pad (16 steps).

### H1. The default envelope
- **Setup:** *"Play breaks."* On the unit, open track 8 (pad) AMP and **write down MODE and HOLD** as you find them on this preset (Q6).
- [ ] Recorded. MODE: ____ HOLD: ____

### H2. HOLD = NOTE vs a fixed hold
- **Type:** *"Set amp hold on track 8 to 127."* (On the unit, HOLD should show NOTE. Only exactly 127 or *"to note"* sends NOTE, and the result says `hold: "NOTE"`; see D4.) Then *"Set amp hold on track 8 to 20."*
- **Expect:** at 127, the pad holds for its note length, then decays. At 20, every hit has the same short hold whatever the note length.
- [ ] Pass · [ ] Fail. Notes:

### H3. ADSR mode
- **Type:** *"Switch the amp envelope on track 8 to ADSR."* That's `amp_mode` 1, and the unit's MODE should show ADSR. Then *"Set the amp release on track 8 to 30."*
- **Expect:** the pad sustains while the note is held, then releases. Also *"Set amp mode on track 8 to 2"* must be **rejected** with no change: it's a switch.
- **Afterwards:** *"Set amp mode on track 8 back to 0"*, or reload the pattern.
- [ ] Pass · [ ] Fail. Notes:

---

## I. Sample select and transport, v0.4

CC 19 switching slots was heard on Nov 11; the rest is new.

### I1. Slot 0: OFF or the first sample? (§15.3 Q4)
- **Setup:** deep house playing.
- **Type:** *"Switch track 7 to sample slot 0."* Then *"slot 1."*
- **Expect:** either silence (OFF) or the first pool sample on slot 0. Record which. Then *"Put track 7 back on slot* N" (its original slot).
- [ ] Recorded: slot 0 = ____

### I2. Slot select refusals
- **Type:** *"Send raw CC 19 value 5 on track 7."* Then *"Send CC 24 on track 7."*
- **Expect:** both are refused. CC 19 goes only through `sample_slot`, and CC 24 is blocked. Nothing changes on the unit.
- [ ] Pass · [ ] Fail. Notes:

### I3. Clock only: the unit's own pattern stays stopped
- **Setup:** select a pattern on the unit that **has** trigs.
- **Type:** *"Play techno, clock only."* That's `send_transport: false`.
- **Expect:**
  - Only Whiplash's notes play. The unit's PLAY LED stays off, and its tempo shows 130.
  - Press [PLAY] on the unit: its pattern joins in sync.
  - *"Stop"*: Whiplash stops, the **unit keeps playing** (no Stop is sent), and you stop it on the unit.
- [ ] Pass · [ ] Fail. Notes:

### I4. Start/Stop layers the unit's pattern, and the warning says so
- **Setup:** the same pattern with trigs.
- **Type:** *"Play techno."*
- **Expect:**
  - The unit's sequencer starts with Whiplash and its trigs layer in.
  - `overlap_warning` explains it.
  - *"Mute track 1"* silences Whiplash's kick but **not** the unit's own track-1 trigs.
  - *"Stop"* stops both.
- **Afterwards:** select the empty pattern again.
- [ ] Pass · [ ] Fail. Notes:

### I5. Changing the transport mode while playing restarts
- **Type:** *"Play deep house."* Then *"Switch to techno, clock only."*
- **Expect:** `mode: "started"`, not queued: a restart, not a bar-quantized switch.
- [ ] Pass · [ ] Fail. Notes:

---

## J. Live control, v0.3

### J1. Ramp curves
- **Type:** *"Ramp the reverb send on track 3 from 0 to 100 over 2 beats with a log curve."* Then *"Sweep the cutoff on track 6 from 20 to 120 over 4 bars, exponential."*
- **Expect:** log rises fast then settles; exp starts slow and finishes fast. Both stay locked to the tempo.
- [ ] Pass · [ ] Fail. Notes:

### J2. Cancel, and set_param overrides a ramp
- **Type:** *"Ramp the cutoff on track 6 from 20 to 127 over 16 bars."* Then *"Set the cutoff on track 6 to 60."*
- **Expect:** the result shows `cancelled_ramp`, and the cutoff jumps to 60 and stays there. *"Cancel all ramps"* returns an empty list.
- [ ] Pass · [ ] Fail. Notes:

### J3. Density, swing, humanize, reset
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

### J4. Hardware mute (CC 94; §15.3 Q3)
- **Type:** *"Mute track 2 on the unit itself."* That's `hardware: true`.
- **Expect:**
  - Track 2 is silent. **Record which mute mode lights on the unit:** green global, or magenta pattern.
  - *"Unmute track 2"* releases it on the unit.
  - Mute again, then *"Stop"*: the unit's mute is released too.
- [ ] Recorded: CC 94 drives ____ mute. Pass · Fail:

### J5. Tempo
- **Type:** *"Speed up to 140."*
- **Expect:** the tempo changes on the next tick, and the unit's tempo display and delay follow. No glitch or restart.
- [ ] Pass · [ ] Fail. Notes:

### J6. Queue twice, and a bar limit
- **Type:** *"Switch to soul."* Then, before the bar line, *"Actually, breaks."*
- **Expect:** `replaced_queued: soul`, and breaks lands on the next bar. Then *"Play deep house for 4 bars."* It stops by itself after 4 bars, with a clean stop.
- [ ] Pass · [ ] Fail. Notes:

### J7. Panic with All Notes Off (§15.3 Q5)
- **Setup:** breaks playing (the pad has 16-step gates). Set `amp_hold` on track 8 to note (*"set amp hold on track 8 to note"*) so its notes are held.
- **Type:** *"Stop"* in the middle of a pad note.
- **Expect:** the pad cuts at once. Whiplash sends per-note note-offs and also CC 123. Whether CC 123 alone silences notes can't be separated from the note-offs here, so record only that the stop was clean.
- [ ] Pass · [ ] Fail. Notes:

---

## K. Digitakt reference fixes (PR #6)

### K1. `loop_pos` range is 0-120 (§15.1 #5)
- **Setup:** track 7 on a Oneshot machine.
- **Type:** *"Set play mode on track 7 to forward loop."* (`play_mode` 2) Then *"Set loop position on track 7 to 127."*
- **Expect:**
  - The result has `value: 120, clamped: true`.
  - On the unit, SRC LOOP shows its maximum, not some other wrapped value.
  - Then *"Set play mode on track 7 to 3."*
- [ ] Pass · [ ] Fail. Unit display at 120: ____

### K2. Machine-dependent knobs (optional)
- If any track uses Werp, Stretch or Repitch, *"Set loop position on track* N *to 2"* should change BARS, not loop position. Record what the unit shows.
- [ ] Recorded: ____

### K3. Grid/Slice with SLICE = NOTE (optional; §15.3 Q8)
- **Setup:** a track on Grid with SLICE = NOTE.
- **Type:** *"Transpose track* N *up 1 semitone"*, and so on.
- **Expect:** different slices play. Record which note plays slice 1.
- [ ] Recorded: ____

---

## L. Hot-plug and port loss (last: it unplugs the cable)

### L1. Unplug mid-beat
- **Setup:** deep house playing, visualiser open.
- **Action:** pull the USB cable, then type *"What's the status?"*
- **Expect:** `port_lost` with the port name, and `last_error` set. The visualiser flashes `PORT LOST`.
- [ ] Pass · [ ] Fail. Notes:

### L2. Replug and resume
- **Action:** replug, wait for the unit, then type *"Play deep house again on the Digitakt."*
- **Expect:** the port is re-detected and the beat plays on the hardware, with no virtual-port warning. The kit map from earlier (if any) still applies.
- [ ] Pass · [ ] Fail. Notes:

### L3. Start before the unit is connected (optional)
- **Action:** run `hermes gateway restart` with the unit unplugged, then *"Play techno."* Then plug it in and type *"Status?"*
- **Expect:** the first result carries the `NO DIGITAKT DETECTED` warning, and the visualiser shows `VIRTUAL · SILENT`. After plugging in, results carry `device_available` and a notice. Whiplash doesn't switch by itself. The kit map is empty (a gateway restart clears it).
- [ ] Pass · [ ] Fail. Notes:

---

## Recording the results

When a result settles a question in the reference:
- update the relevant part of [docs/digitakt-ii/reference.md](../digitakt-ii/reference.md) (§15.3 open questions, §15.1 statuses, the HW notes in §5-§7 and §10),
- and add a line like `HW: verified by Phil on a Digitakt II, OS x.yy, 2026-11-11 (hardware-checklist F2)`.

Fails go in a GitHub issue, or the next build plan, with the check ID.

| Open question (§15.3) | Check |
| --- | --- |
| Q1 Factory channel settings | 0.2 |
| Q2 Note 60, 48 and 72 on a track channel; KB octave; range | F1, F2, F3, F7 |
| Q3 Which mute mode CC 94 drives | J4 |
| Q4 CC 19 = 0 | I1 |
| Q5 CC 123 | J7, D3 (partial) |
| Q6 Default VELOCITY TO VOL and AMP HOLD | H1, J3 |
| Q7 INT TO MAIN while capturing | E3 |
| Q8 SLICE = NOTE, slice 1 | K3 |
| Q9 Written-part length vs HOLD/MODE; HOLD = NOTE display | C3, D4-D6 (and §15.1 #24: C6) |
| Q10 Setup slot lands on the first note (fresh start and queued) | A3, B5, B6 |
| Q11 TUNE after a slot change | B5 |
| Q12 Notes one audio track sounds at once | P2 |
| Q13 A chord spread across chord tracks | P3 |

| Plan item / §15.1 | Check |
| --- | --- |
| v0.5 HW 1 (note 60, octaves) | F1-F3 |
| v0.5 HW 2 (length vs envelope) | C3, H2, H3 |
| v0.5 HW 3 (melody on slots 9 and 11) | C1 |
| v0.5 HW 4 (skill after restart) | G1 |
| v0.5 HW 5 (kit labels route without cymbal chords) | A2, A3, B3 |
| Item 10 latency (soft) | A1-A8 turn times, B9 |
| §15.1 #26 kit map | A3, B1-B4, E4 |
| §15.1 #27 setup CCs | A3, B5-B7 |
| v0.6 HW 6.0-1 to 6.0-5 (keys, progressions) | P1-P5 |
| Visualiser key and chords (v0.6.0) | E8 |
