# Elektron Digitakt II: device reference for Whiplash

The canonical reference for how the Digitakt II works, written for agents and humans working on Whiplash. Read it before changing `ccmap.py`, the note or channel handling in `engine.py`/`patterns.py`, or anything that sends MIDI.

**Sources and conventions**
- **[M] p. N** is the official *Digitakt II User Manual* for **OS 1.17** (imprint dated 2026-09-24). Printed page numbers equal PDF page numbers. [README.md](README.md) has the link and hash; run `./fetch-manual.sh` for a local copy.
- **[G]** is [midi.guide](https://midi.guide/d/elektron/digitakt-ii/), the [pencilresearch/midi CSV](https://github.com/pencilresearch/midi/blob/main/Elektron/Digitakt%20II.csv), last commit 2026-10-12. It is community data, not Elektron's.
- **HW** marks a claim that neither source settles. It needs checking on a real unit. Nothing in this file has been verified on hardware unless it says so, with a date and a source.
- **"Interpretation"** marks a place where the manual is ambiguous and this file picks a reading.
- **Note names** follow Elektron's convention: MIDI note 0 = C0, so **60 = C5** ([M] p. 25). Logic Pro calls note 60 **C3**, and General MIDI/scientific pitch calls it C4. Always pass and quote raw note numbers.
- **Channels** are written 1-16, as on the unit. `mido` uses 0-15, so Whiplash's `ch = track - 1`.

---

## 0. The short version (read this if nothing else)

1. **Sixteen tracks per pattern.** Each one is either an audio track (a sample-playback machine) or a MIDI track (it sequences external gear) [M] p. 17. Whiplash's generated patterns play tracks 1-8; since v0.5.1, parts written with `whiplash_write_part` can use 1-16.
2. **Each track listens on its own MIDI channel.** The defaults are 1-16 = tracks 1-16 ([M] p. 25, p. 79). Notes on a track's channel play that track's sound. CC/NRPN on that channel change that track's parameters.
3. **Note 60 (C5) plays the sample at its own pitch**, provided TUNE is 0 (CC 16 = 64) and the preset's OCTAVE setting is untouched ([M] p. 25, p. 38, p. 93; [G] Trig Note default 60). Every semitone away from 60 repitches the sample by a semitone. On Grid/Slice machines with SLICE = NOTE, the note picks a slice instead ([M] p. 98, p. 101).
4. **Three other channels exist:** AUTO (whichever track is active), FX CONTROL (send FX, compressor, master overdrive) and program change. Many FX-channel CC numbers mean something else on a track channel ([M] p. 79, p. 111-113). Keep AUTO and FX CONTROL off channels 1-8 when Whiplash plays (HW: the factory defaults aren't in the manual).
5. **Clock and transport are opt-in on the unit.** SETTINGS > MIDI CONFIG > SYNC has CLOCK RECEIVE and TRANSPORT RECEIVE ([M] p. 77). With transport receive on, MIDI Start also runs the unit's own sequencer, so the trigs of the selected pattern play too.
6. **Program change selects patterns** (PC 0-127 = A01-H16) when PRG CH RECEIVE is on ([M] p. 25, p. 77). SysEx can overwrite projects, patterns and presets ([M] p. 80). Whiplash sends neither, and must never.
7. **Parameter edits stick.** A CC changes the active pattern's kit, just as turning a knob does. The change stays until someone reloads ([M] p. 35, p. 49, p. 52). Nothing is written to the saved project unless a user saves.
8. **Mutes:** CC 94 = track mute, CC 110 = pattern mute ([M] p. 109, p. 113). The unit has a global mute mode, saved with the project, and a pattern mute mode, saved with the pattern ([M] p. 26-27).
9. **The CC numbers in Appendix B agree with midi.guide.** Many NRPN addresses don't, and the manual also contradicts itself on several. That is why Whiplash sends named params as CC only (§8.3).
10. **Whether note-off matters depends on the amp envelope.** With AMP MODE = AHD and HOLD = NOTE (the [G] defaults), the note length sets the hold. With a fixed HOLD time, note-off is ignored ([M] p. 56).

---

## 1. Hardware at a glance

- **Voices:** 16 stereo audio voices, three send effects (chorus, delay, reverb), and master effects (compressor, master overdrive) [M] p. 15.
- **Ports:** USB (MIDI, and audio/Overbridge, §14), MIDI IN, MIDI OUT/SYNC A, MIDI THRU/SYNC B (the last two can output DIN sync instead), IN L/R, OUT L/R and headphones [M] p. 14.
- **Converters:** 48 kHz, 24-bit [M] p. 91. Samples are 16-bit/48 kHz, mono or stereo [M] p. 29.
- **Panel keys:** the [TRIG 1-16] keys are steps, track and pattern selectors, the keyboard and the mute switches, depending on mode [M] p. 13, p. 25. [FUNC] + key gives the orange secondary functions [M] p. 13.

---

## 2. Data model: what lives where

### 2.1 The containers

| Container | Holds | Lives in | [M] |
| --- | --- | --- | --- |
| **+Drive** | Up to 128 projects and 1024 kits, the preset library (2048 presets, banks A-H × 256), and up to 20 GB of user samples. The factory samples don't count against that. | Non-volatile storage | p. 16, p. 29, p. 84 |
| **Project** | 128 patterns (banks A-H × 16), 16 songs, the **pool**, and general settings/states (including global mutes). | +Drive slot. The loaded project is the "active working state", and the unit boots into it. | p. 16, p. 27, p. 75 |
| **Pool (project RAM)** | **Samples:** up to 1016 slots / 400 MB (about 72 min mono). **Presets:** up to 128 pool presets. Pool presets are the only ones that can be preset-locked. | Part of the project | p. 17, p. 29 |
| **Pattern** | A **kit**, the sequencer data for 16 tracks (trigs, p-locks, micro timing, retrigs), the TRIG-page defaults, BPM, length, swing, time signature, quantize, and pattern mutes. | Project | p. 16, p. 29, p. 40 |
| **Kit** | 16 track presets, plus track LEVELs and pattern volume, compressor and master-overdrive settings, compressor routing, Control All config, and the send-FX settings. | Copied into a pattern. Can also be saved as a kit on the +Drive. | p. 29, p. 37 |
| **Preset** | Audio track: a sample reference plus every SRC, FLTR, AMP, FX and MOD setting. MIDI track: SRC, FLTR, AMP and MOD. Also the SETUP > TRACK settings (OCTAVE, velocity curve, key tracking, ...). | Copied into the pattern's kit. Can be saved to the +Drive library or the pool. | p. 16, p. 29, p. 38 |
| **Sample** | 16-bit/48 kHz audio. It is referenced by a content hash, so renaming or moving it is safe, but deleting it removes it from every preset. | +Drive. It must be loaded into the project's pool (a slot) before a track can use it. | p. 17, p. 29, p. 71 |
| **Song** | Up to 99 rows. Each row has a pattern, repeat count, length (2-1024 steps), tempo, swing and mute state. There are 16 songs per project. | Project. Autosaved as edited, but kept across project switches only if the project is saved. | p. 16, p. 50-52 |
| **Chain** | Up to 64 patterns in order. There is only one chain at a time. It is never saved, and is lost on power-off or on a new pattern/song selection. | Volatile | p. 40-41 |

**Copies, not links.** When a kit or preset is loaded into a pattern, the pattern gets an independent copy. Editing it never changes the stored kit or preset unless you save back ([M] p. 17, p. 29).

### 2.2 Saved, temporary and live state

- **Live edits** (knobs, incoming CC/NRPN, sample changes) go straight into the **active pattern's kit**: "any changes made will be stored as part of the active pattern" ([M] p. 35). Outside PERFORM KIT mode they are auto-kept. If you switch patterns, the other pattern loads its own kit, and the edited pattern still holds the edits when you return ([M] p. 52). Interpretation: these edits are part of the working state the unit boots into ([M] p. 16).
- **Temporary save/reload:**
  - [FUNC] + [YES] snapshots the active pattern, and [FUNC] + [NO] reloads that snapshot.
  - Without a snapshot, [FUNC] + [NO] reloads the permanently saved pattern.
  - Neither one writes anything permanently ([M] p. 49-50).
- **Permanent save:** SETTINGS > PATTERN > SAVE TO PROJ (whole pattern, kit only or sequence only), and SETTINGS > PROJECT > SAVE ([FUNC] + [SETTINGS] overwrites) ([M] p. 75-77). RELOAD FROM PROJ restores the last saved pattern ([M] p. 77).
- **Preset reload:** [TRK] + [TRIG n] + [NO] reloads one track's preset from its last saved state. [PARAMETER] + [NO] resets one parameter page ([M] p. 53).
- **PERFORM KIT mode** ([FUNC] + [PRESET/KIT]):
  - Edits are not auto-kept, and kits are **not** reloaded on a pattern change. A tweaked kit carries across patterns.
  - [PRESET/KIT] + [NO] reloads the pattern's kit, and [PRESET/KIT] + [YES] saves it.
  - A flashing "P" shows next to the pattern name ([M] p. 52).

### 2.3 Logic Pro analogies

| Digitakt II | Closest Logic Pro idea | Where the analogy breaks |
| --- | --- | --- |
| +Drive library | Your Sound Library and Patches folder on disk | It holds projects too |
| Project | A `.logicx` project | There is one active project, and it autosaves to a working state |
| Pool (samples) | The Project Audio browser: files imported into this project | Fixed 1016 slots / 400 MB of RAM |
| Pattern (bank A-H, 1-16) | A row of Live Loops cells, one cell per track, launched together | A pattern also carries its own sounds (the kit) and its own FX settings |
| Kit | A saved set of 16 channel strip settings plus the bus FX and the master compressor | It is copied into each pattern |
| Preset | One channel strip setting (`.patch`): Quick Sampler with its sample, plus filter, amp, FX and LFOs | |
| Machine | Quick Sampler mode (One Shot / Classic / Slice) or a Flex mode | Chosen per track, in the MACHINE menu only (no MIDI) |
| Track LEVEL vs AMP VOL | Channel fader vs the instrument's own volume | Only AMP VOL can be p-locked |
| Parameter lock | A per-step value in Step Sequencer (note-level parameter rows) | It applies only to the unit's own sequencer trigs |
| Song mode | The Tracks-area arrangement of Live Loops scenes | |
| Global vs pattern mute | Track mute vs muting the cells in one scene | |
| AUTO channel | "MIDI input follows the selected track" | |
| Temp save/reload | A quick Alternative / snapshot you can revert to | |
| Overbridge | Logic's External Instrument plug-in with full parameter automation, plus multitrack audio | |

---

## 3. Tracks and the signal path

- **Track types.** Any of the 16 tracks can be an audio track (the default) or a MIDI track. A track is a MIDI track when its SRC machine is MIDI ([M] p. 17). Several MIDI tracks may share a channel; on a conflict, the lowest-numbered track wins ([M] p. 17).
- **Audio voice path** ([M] p. 15 diagram, with routing options from p. 56 and p. 58):
  - The chain runs SRC machine → bit reduction → overdrive → sample-rate reduction → filter machine and base-width filter → amp (envelope, VOL) → pan → track level → mixer.
  - **Routing switches:** SRR ROUT (pre/post filter), OD.RT (overdrive pre/post filter), BW.RT (base-width pre/post the filter machine).
  - **Sends** go to chorus, delay and reverb. Chorus can feed delay and reverb, and delay can feed reverb ([M] p. 62-63).
  - **Master:** mixer → compressor (with selectable routing, [M] p. 37) → outputs. Master overdrive is set on the FX MIXER page ([M] p. 66).
- **Six parameter pages** per track: TRIG, SRC, FLTR, AMP, FX and MOD ([M] p. 17, p. 53).
  - **Where TRIG settings live:** TRIG-page settings are saved with the pattern, not the preset ([M] p. 53).
  - **MIDI tracks:** the FX page is empty, FLTR/AMP hold the CC VAL/SEL slots, and there are only 2 LFOs ([M] p. 17, p. 101-104).
- **Control All.** Hold [TRK] while turning a knob to change that parameter on all audio tracks ([M] p. 19).

---

## 4. Machines

Machines are chosen in the MACHINE menu ([FUNC] + [SRC], [M] p. 93). **No CC or NRPN selects a machine** (Appendix B has none, and neither does [G]). Machine choice is part of the preset.

### 4.1 SRC machines and what the knob CCs mean

The CCs are the same on every machine, but the meaning of knobs E/F/G (CC 20/21/22) changes ([M] p. 109: "Data entry knob E/F/G (machine dependent)"). The parameter lists come from [M] Appendix A, and the value ranges from [G].

| Machine | What it does | TUNE (CC 16) | E (CC 20) | F (CC 21) | G (CC 22) | [M] |
| --- | --- | --- | --- | --- | --- | --- |
| **Oneshot** (default) | Linear playback: forward, reverse or looped | ±5 oct | STRT 0-120 | LEN 0-120 | LOOP 0-120 | p. 93-94 |
| **Werp** | Tempo-syncs a loop by cutting it into segments | ±5 oct | SEG 0-2 (1/32, 1/16, 1/8) | Segment MODE 0-3 | BARS 0-3 (1, 2, 4, 8) | p. 95-96 |
| **Stretch** | Tempo-syncs by granular stretching (crossfaded grains) | ±5 oct | STRT 0-120 | LEN 0-120 | BARS 0-3 | p. 96 |
| **Repitch** | Tempo-syncs by repitching (speed follows tempo) | [G] lists it; [M] A.2.4 doesn't (discrepancy) | STRT 0-120 | LEN 0-120 | BARS 0-3 | p. 96-97 |
| **Slice** | Hand-edited slices, with a slice editor and linear/random slice locks | ±5 oct | SLICE 0-64 (0 = NOTE) | Slice LEN 0-63 | (none) | p. 97-100 |
| **Grid** | Even slices | ±5 oct | SLICE 0-64 (0 = NOTE) | Slice LEN 0-63 | GRID 0-4 (4, 8, 16, 32, 64 slices) | p. 100-101 |
| **MIDI** | Turns the track into a MIDI sequencer track (§4.3) | (none) | (none) | (none) | (none) | p. 101-104 |

All sample machines also have:
- **PLAY** (CC 17): 0 reverse, 1 reverse loop, 2 forward loop, 3 forward. The [G] default is 3 ([M] p. 70, p. 94).
  - **Loops are bounded.** A loop plays for the trig's LEN and is cut by the amp envelope's HOLD/DEC ([M] p. 70).
- **SAMP:** the sample slot. The list's first entry is **OFF**, which plays no sample ([M] p. 94). MIDI: CC 19 = slot 0-127 within the selected sample bank, and CC 24 = bank 0-7 ([M] p. 109, p. 113; [G]). [G] also lists NRPN 1:3 = absolute slot (bank × 128 + slot).
- **LEV** (CC 23): sample level.
- **Sample locks.** SAMP can be p-locked per step ([M] p. 94).

TUNE is bipolar, ±5 octaves, and 0 leaves the pitch unchanged ([M] p. 93). Over MIDI it is CC 16 with 64 = 0. [G] gives the range 4-124, which is ±60 semitones.

### 4.2 FLTR machines and what CC 75/76 mean

All filter machines share an ADSR filter envelope:
- **Envelope:** CC 70-73. ENV depth is CC 77 (bipolar, 64 = none). Envelope delay is CC 91 ([M] p. 104-108, p. 109).
- **Cutoff:** FREQ is CC 74.
- **Knobs F and G** are CC 75 and 76, and they are machine dependent:

| Filter machine | F (CC 75) | G (CC 76) | [M] |
| --- | --- | --- | --- |
| Multi-Mode | RESO | TYPE: morphs LP → BP → HP | p. 104-105 |
| Lowpass 4 (24 dB/oct) | RESO | (none) | p. 105-106 |
| EQ (parametric) | GAIN (bipolar) | Q | p. 106 |
| Comb- (negative feedback, hollow) | FDBK | LPF in the feedback path | p. 106-107 |
| Comb+ (positive feedback, string-like; high FDBK is loud) | FDBK | LPF | p. 107-108 |
| Legacy (Digitakt I style, 12 dB/oct) | RESO | TYPE: [G] 0 LP, 1 HP, 2 Off | p. 108 |

FLTR page 2 is common to all of them ([M] p. 55-56):
- **DEL** (envelope delay).
- **KEY.T** key tracking, CC 92, 0-100 [G]. Higher notes open the filter more.
- **BASE/WIDTH** base-width filter, CC 26/27. BASE 0 with WIDTH 127 means no effect.
- **BW.RT.**
- **RSET** filter envelope reset, CC 111.

### 4.3 The MIDI machine (MIDI tracks)

- **TRIG page:** NOTE, VEL, LEN, PROB, LFO.T, and NOT2-NOT4 for chords of up to 4 notes ([M] p. 101-102).
- **SRC page:**
  - CHAN: the output channel, OFF/1-16, which can't be p-locked.
  - BANK (CC 0), SBNK (CC 32), PROG.
  - PB, AT, MW (CC 1), BC (CC 2).
  - Every SRC parameter starts disabled; [FUNC] + knob enables it ([M] p. 102-103).
- **FLTR/AMP pages:** VAL1-16 and SEL1-16, with MIDI learn ([M] p. 103-104). Over MIDI, VAL1-8 are **CC 70-77** on the track's channel, and VAL9-16 are NRPN only (1:60-1:67) ([M] p. 113).
- **"The sequencer data is always sent on the MIDI channel specified by the CHAN parameter"** ([M] p. 79).

Whiplash implication: on a track that has the MIDI machine, CC 70-77 sent to its channel set the VAL slots, not filter parameters. Interpretation: those values are then forwarded to whatever that track drives. Whiplash's patterns assume tracks 1-8 are audio tracks.

---

## 5. Track parameter pages in detail

### 5.1 TRIG page 1 and 2 ([M] p. 53-55)

- **NOTE** (CC 3), **VEL** (CC 4), **LEN** (CC 5).
  - [G] defaults: 60, 100, 14 (= 1/16).
  - These are the *defaults for the unit's own sequencer trigs* on that track. Incoming MIDI notes bring their own note, velocity and length.
- **PROB:** trig probability.
- **LFO.T** (CC 14), **FLT.T** (CC 13): whether a trig restarts the LFO / filter envelope.
- **FILL:** the fill condition.
- **COND:** trig conditions (PRE, NEI, 1ST, LST, A:B and their negations, [M] p. 48).
- **Page 2:**
  - **Retrig:** RTRG, VFAD, LEN, RATE (1/1 to 1/80). Audio tracks only; there is no CC for it.
  - **Portamento:** PTIM (CC 9) and PORT (CC 65). Audio tracks only.

### 5.2 AMP page ([M] p. 56-57; CCs [M] p. 110; defaults [G])

| Param | CC | Notes |
| --- | --- | --- |
| ATK | 79 | |
| HOLD | 80 | 0-126 = fixed hold, which **ignores note-off**. 127 = **NOTE**: hold lasts from note-on to note-off. AHD mode only. [G] default 127 (NOTE). |
| DEC | 81 | [G]: 127 = infinite |
| SUS | 82 | ADSR mode only |
| REL | 83 | ADSR mode only. [G]: 127 = infinite. |
| RSET | 88 | Envelope reset per trig: 1 on (default), 0 off |
| MODE | 87 | 0 = AHD (the [G] default), 1 = ADSR |
| PAN | 90 | 64 = centre |
| VOL | 89 | Can be p-locked, unlike track LEVEL (CC 95). [G] default 110. |

How the envelope settings decide note length:
- **AHD with HOLD = NOTE** (default): the note's length controls the sound. After note-off, DEC runs.
- **AHD with a fixed HOLD:** note length does nothing. Every hit is the same length.
- **ADSR:** the note sustains at SUS while held, then REL.

So "droney" or "too short" notes are usually an envelope question first (HOLD/DEC/MODE), and a gate-length question second.

### 5.3 FX page ([M] p. 57-58, p. 110)

| Param | CC | Notes |
| --- | --- | --- |
| BR (bit reduction, 16 → 1 bit) | 54 | |
| OVER (overdrive) | 57 | |
| SRR (sample-rate reduction) | 55 | |
| ROUT (SRR pre/post filter) | 56 | |
| DEL / REV / CHR sends | 84 / 85 / 12 | |
| OD.RT (overdrive pre/post filter) | not in [M] App. B. [G] says CC 25 / NRPN 1:10. | |

### 5.4 MOD pages: LFOs ([M] p. 58-60, p. 110-111)

Audio tracks have three LFOs; MIDI tracks have two.

- **SPD:** bipolar, with negative values running backwards. The CCs are hi-res: LFO1 102/58, LFO2 112/60, LFO3 78/62 (MSB/LSB).
- **MULT:** BPM- or fixed-120-based multiplier. CC 103/113/52; [G] range 0-23.
- **FADE:** bipolar, −64 to 63. CC 104/114/53.
- **DEST:** CC 105/115/28. The list is in [M] Appendix C, p. 114:
  - Any SRC, FILTER, AMP or FX parameter.
  - LFO1 can modulate LFO2/3, and LFO2 can modulate LFO3.
  - On MIDI tracks: PB, AT, MW, BC and CC1-16.
- **WAVE:** TRI, SINE, SQR, SAW, EXP, RAMP, RND. CC 106/116/29; [G] 0-6.
- **SPH:** start phase. It becomes SLEW on RND. CC 107/117/30.
- **MODE:** FRE (free), TRG (restart per note), HLD (sample and hold per note), ONE (one-shot), HLF (half cycle). CC 108/118/31; [G] 0-4.
- **DEP:** bipolar, with 64 (0.00) = none. Hi-res: LFO1 109/59, LFO2 119/61, LFO3 86/63.

LFO speed table ([M] p. 60): SPD × MULT gives cycle length in steps. For example, SPD 16 with MULT 16 = one cycle per 8 steps, and SPD 32 with MULT 64 = 1 step. Try SPD 8/16/32 for straight beats.

### 5.5 SETUP > TRACK ([FUNC] + [FLTR], per preset, [M] p. 38-39)

These change how **incoming MIDI** behaves, so they matter to Whiplash. None of them has a CC.

- **OCTAVE:** the preset's base octave. If someone has changed it, note 60 no longer plays the sample at its own pitch.
- **VELOCITY TO VOL:**
  - OFF / LOG / LIN / EXP / EXP 2: how MIDI velocity maps to volume.
  - With OFF, Whiplash's accents, ghost notes and humanize change nothing audible, unless velocity is routed elsewhere (VELOCITY MOD).
  - HW: the default isn't documented.
- **LEGATO / NOTE PRIORITY / PORTAMENTO** (slope, amount, glide/glissando, legato only, gating).
- **PITCH BEND DEPTH.**
- **Modulation assignments:** KEY TRACKING, VELOCITY MOD, AFTERTOUCH, PITCH BEND, MOD WHEEL (CC 1), BREATH (CC 2). Each takes up to 4 destinations with depths. KEY TRACKING responds to incoming note numbers too.

---

## 6. Notes, pitch, KEYBOARD mode

### 6.1 How incoming notes map

[M] 8.4, p. 25:
- **Notes 0-15 (C0-D#1)** "will trigger the preset of track 1 through track 16, respectively … regardless of which track is active."
- **Notes 16-84** "will trigger the preset of the active track in it's chromatic variations (as if played by the [TRIG] keys in KEYBOARD mode)". The manual's text says "E2–C7", but by its own numbering (0 = C0) note 16 is E1, and 84 is C7.
- "C5, MIDI note 60, being middle C."
- **Program change 0-127** selects patterns A01-H16.

Interpretation, which this file uses: those two note rules describe the **AUTO channel**, which "give[s] access to the currently active track" ([M] p. 79), the same as the [TRIG] keys in KEYBOARD mode. On a **track's own channel**, notes play *that* track, whichever track is active ([M] p. 35, "PLAYING A PRESET WITH AN EXTERNAL MIDI UNIT"; p. 79). The manual gives no note range for track channels.

| Where the note arrives | What plays | Pitch |
| --- | --- | --- |
| Track n's channel (default channel n) | Track n | Chromatic around 60 = sample's own pitch. Exact range not documented (HW). |
| AUTO channel, note 0-15 | Tracks 1-16 | Not specified. Interpretation: like pressing the [TRIG] key, so the track's own pitch. |
| AUTO channel, note 16-84 | The active track | Chromatic, 60 = own pitch |
| FX CONTROL channel, note 0 (C0) | Tap tempo | [M] p. 23 |
| Grid/Slice machine with SLICE = NOTE | A slice instead of a pitch | "Slices play from C1 and upwards, wrapping around after the last slice" ([M] p. 26, p. 98). By Elektron numbering C1 = note 12 (HW: which note is slice 1 on a track channel). |

What decides the pitch you hear when a note plays a sample:
- **The note** relative to 60.
- **TUNE**, ±60 semitones (CC 16, with 64 = 0).
- **The preset's OCTAVE** (§5.5).
- **Modulation:** any LFO on TUNE, and KEY TRACKING destinations.
- **Repitch** additionally ties speed to tempo, and Werp/Stretch keep the duration tied to BARS.

A sample pitched well below 60 sounds stretched and grainy, because it is slowed down. The v0.4 hardware session hit exactly this, fixed with TUNE +12; see `docs/executing/v05-build-plan.md` item 1. v0.5.0 lifts generated lines to within 7 semitones below 60 and adds `whiplash_transpose` and a `pitch` block (§15.1 #3).

### 6.2 KEYBOARD mode ([M] p. 25-26)

- **Turning it on:** [KEYBOARD] toggles the mode, and the [TRIG] keys become a piano octave (lit keys only). [TRIG 9]-[TRIG 16] span one octave.
- **Range:** the full range is about 10 octaves (C0-G10). The keyboard transposes 4 octaves up and 5 down from the middle, with [KEYBOARD] + [UP]/[DOWN].
- **State is not per pattern.** The keyboard octave position "stays in the state as it was last set". Interpretation: the KB octave affects the [TRIG] keys and the AUTO channel; it should not affect notes on a track channel (HW).
- **KEYBOARD SETUP** ([FUNC] + [KEYBOARD]):
  - KB SCALE: 36 scales, listed in [M] Appendix D, p. 115.
  - ROOT NOTE.
  - **KB FOLD:** every key plays a scale note, and "how they are played from external MIDI devices" changes too.
  - These settings are **stored in the active pattern**.
- **No KEYBOARD mode needed for MIDI.** "You can play the active track's preset chromatically even if the Digitakt II is not in KEYBOARD mode" (via the AUTO channel, [M] p. 26).

### 6.3 Other TRIG modes ([M] p. 27-28)

[FUNC] + [UP]/[DOWN] picks the mode for the [TRIG] keys:
- **TRACKS** (default).
- **VELOCITIES:** [TRIG 1-16] = velocity 8, 16, … 127.
- **RETRIGS:** [TRIG 1-16] = rate 1/1 to 1/80.
- **SLICES.**
- **PRESET POOL.**

RETRIGS, SLICES and PRESET POOL work on audio tracks only.

---

## 7. MIDI configuration (SETTINGS > MIDI CONFIG, [M] p. 77-79)

### 7.1 SYNC

| Setting | Effect |
| --- | --- |
| CLOCK RECEIVE / CLOCK SEND | Follow / send MIDI clock |
| TRANSPORT RECEIVE / TRANSPORT SEND | Respond to / send Start, Stop, Continue |
| PRG CH RECEIVE / PRG CH SEND | Respond to / send program change. Each pattern change sends its PC. |

### 7.2 PORT CONFIG

| Setting | Values | Notes |
| --- | --- | --- |
| TURBO SPEED | | Turbo-MIDI negotiation (needs a supporting interface) |
| OUT / THRU PORT FUNCTIONALITY | MIDI, DIN 24, DIN 48 | DIN sync sends no MIDI on that port |
| **INPUT FROM** | DISABLED, MIDI, USB, MIDI+USB | Whiplash needs USB or MIDI+USB |
| OUTPUT TO | DISABLED, MIDI, USB, MIDI+USB | MIDI+USB limits USB speed |
| OUTPUT CH | Auto channel or track channel | Which channel the knobs send on |
| PARAM OUTPUT | CC or NRPN | What the knobs send |
| ENCODER DEST / TRIG KEY DEST / MUTE DEST | INT, INT+EXT, EXT | Whether the knobs, keys and mutes also send MIDI (EXT = only send) |
| **RECEIVE NOTES** | on/off | Must be on for Whiplash's notes |
| **RECEIVE CC/NRPN** | on/off | Must be on for Whiplash's params and mutes |

### 7.3 CHANNELS

| Setting | What it is |
| --- | --- |
| **TRACK 1-16 CHANNEL** | The track's dedicated channel for receiving (and sending) parameter data. OFF = no MIDI parameter data at all. Default: track n = channel n ([M] p. 25). |
| **FX CONTROL CH** | The delay, reverb, chorus and compressor pages plus master overdrive, in and out. OFF = none. HW: default not documented. |
| **AUTO CHANNEL** | Controls the currently active track. It also carries MIDI-track recording from controllers ([M] p. 42, p. 44, p. 79). HW: default not documented. |
| PROGRAM CHG IN CH / OUT CH | A channel, or AUTO |

### 7.4 Channel collisions to avoid

Track channels, the FX channel and the AUTO channel reuse the same CC numbers for different things:

| CC | Track channel | FX CONTROL channel |
| --- | --- | --- |
| 9 | Portamento time | Chorus speed |
| 12 / 13 / 14 | Chorus send / filter trig / LFO trig | Chorus → delay send / chorus → reverb send / chorus mix volume |
| 16 / 17 | Tune / play mode | Chorus depth / master overdrive |
| 21-24 | Src knob F / G / sample level / **sample bank** | Delay time / pingpong / width / **feedback** |
| 25-28 | ([G]: OD routing) / filter base / width / LFO3 destination | Delay HPF / LPF / reverb send / mix volume |
| 29-31 | LFO3 wave / phase / mode | Reverb predelay / decay / shelving freq |
| 70-77 | Filter envelope, freq, knobs F/G, env depth (MIDI track: VAL1-8) | Chorus HPF/width, external-in levels/pans/sends |
| 78-82 | LFO3 speed, amp attack/hold/decay/sustain | External-in sends, dual mono |
| 89-92 | Amp volume, pan, filter env delay, key tracking | Reverb shelving gain, HPF, LPF, mix volume |
| 111-119 | Filter env reset, LFO2 speed … LFO2 depth | Compressor threshold … dry/wet, pattern volume |

If FX CONTROL CH or AUTO CHANNEL is set to one of channels 1-8, Whiplash's per-track messages land on two targets. Keep both channels outside 1-8, or OFF.

---

## 8. The full CC / NRPN map

All CCs are 7-bit unless an LSB is listed. NRPN messages are CC 99 (NRPN MSB), CC 98 (NRPN LSB), CC 6 (data MSB), and CC 38 (data LSB).

- **Column [M]** is Appendix B, pp. 109-113. **Column [G]** is midi.guide, given only where it differs, or where [M] is silent.
- **Range and default come from [G]**; [M] gives almost none.
- **Whiplash** names the `ccmap.py` param that sends it. "blocked" means `ccmap.BLOCKED_CCS` / `BLOCKED_NRPNS` refuse it.

### 8.0 Whiplash's named params at a glance

This is exactly what `ccmap.py` sends, on the track's channel. `tests/test_reference.py` fails if this table and the code drift apart. The ranges come from [G] (the manual gives none). Centre 64 = no change. For LFOs, Whiplash sends the MSB only.

| Param | Group | CC | LSB | Range | Centre |
| --- | --- | --- | --- | --- | --- |
| `mute` | track | 94 | | 0-1 | |
| `track_level` | track | 95 | | 0-127 | |
| `tune` | src | 16 | | 4-124 | 64 |
| `play_mode` | src | 17 | | 0-3 | |
| `sample_start` | src | 20 | | 0-120 | |
| `sample_length` | src | 21 | | 0-120 | |
| `loop_pos` | src | 22 | | 0-120 | |
| `sample_slot` | src | 19 | | 0-127 | |
| `sample_level` | src | 23 | | 0-127 | |
| `filter_freq` | filter | 74 | | 0-127 | |
| `filter_reso` | filter | 75 | | 0-127 | |
| `filter_env_depth` | filter | 77 | | 0-127 | 64 |
| `filter_attack` | filter | 70 | | 0-127 | |
| `filter_decay` | filter | 71 | | 0-127 | |
| `filter_sustain` | filter | 72 | | 0-127 | |
| `filter_release` | filter | 73 | | 0-127 | |
| `filter_env_delay` | filter | 91 | | 0-127 | |
| `filter_key_tracking` | filter | 92 | | 0-100 | |
| `amp_attack` | amp | 79 | | 0-127 | |
| `amp_hold` | amp | 80 | | 0-127 | |
| `amp_decay` | amp | 81 | | 0-127 | |
| `amp_sustain` | amp | 82 | | 0-127 | |
| `amp_release` | amp | 83 | | 0-127 | |
| `amp_mode` | amp | 87 | | 0-1 | |
| `amp_volume` | amp | 89 | | 0-127 | |
| `pan` | amp | 90 | | 0-127 | 64 |
| `delay_send` | fx | 84 | | 0-127 | |
| `reverb_send` | fx | 85 | | 0-127 | |
| `chorus_send` | fx | 12 | | 0-127 | |
| `overdrive` | fx | 57 | | 0-127 | |
| `bit_reduction` | fx | 54 | | 0-127 | |
| `sample_rate_reduction` | fx | 55 | | 0-127 | |
| `lfo1_speed` | lfo | 102 | 58 | 0-127 | 64 |
| `lfo1_depth` | lfo | 109 | 59 | 0-127 | 64 |
| `lfo2_speed` | lfo | 112 | 60 | 0-127 | 64 |
| `lfo2_depth` | lfo | 119 | 61 | 0-127 | 64 |
| `lfo3_speed` | lfo | 78 | 62 | 0-127 | 64 |
| `lfo3_depth` | lfo | 86 | 63 | 0-127 | 64 |

### 8.1 Per-track (sent on the track's channel)

**Track** ([M] B.1, p. 109)

| Param | CC | NRPN [M] | NRPN [G] | Range / default [G] | Whiplash |
| --- | --- | --- | --- | --- | --- |
| Mute | 94 | 1:101 | **1:108** | 0-1 (1 = muted) / 0 | `mute` |
| Track level | 95 | 1:100 | **1:110** | 0-127 / 100 | `track_level` |

**Trig** ([M] B.2, p. 109)

| Param | CC | NRPN [M] | NRPN [G] | Range / default [G] | Whiplash |
| --- | --- | --- | --- | --- | --- |
| Note | 3 | 3:0 | | 0-127 / 60 | (none) |
| Velocity | 4 | 3:1 | | 1-127 / 100 | (none) |
| Length | 5 | 3:2 | | 0-127 / 14 (1/16; 127 = inf) | (none) |
| Filter trig | 13 | (none) | | 0-1 / 1 | (none) |
| LFO trig | 14 | (none) | | 0-1 / 1 | (none) |
| Portamento time | 9 | 3:7 | **3:6** | 0-127 / 39 | (none) |
| Portamento on/off | 65 | 3:8 | **3:7** | 0-1 / 0 | (none) |

**Source** ([M] B.3, p. 109)

| Param | CC | NRPN [M] | NRPN [G] | Range / default [G] | Whiplash |
| --- | --- | --- | --- | --- | --- |
| Tune | 16 | 1:0 | | 4-124 / 64 (centred) | `tune` |
| Play mode | 17 | 1:1 | | 0-3 / 3 | `play_mode` |
| Sample bank select | 24 | 1:9 | | 0-7 / 0 | **blocked** |
| Sample slot select | 19 | 1:8 | | 0-127 / 0 | `sample_slot` (raw cc 19 and NRPN 1:8 refused) |
| Sample (absolute) | (none) | (none) | **1:3** (0-1023 = bank × 128 + slot) | | **blocked** |
| Knob E | 20 | 1:4 | | 0-120 (Oneshot) | `sample_start` |
| Knob F | 21 | 1:5 | | 0-120 (Oneshot) | `sample_length` |
| Knob G | 22 | 1:6 | | 0-120 (Oneshot) | `loop_pos` |
| Sample level | 23 | 1:7 | | 0-127 / 100 | `sample_level` |

**Filter** ([M] B.4, pp. 109-110)

| Param | CC | NRPN [M] | NRPN [G] | Range / default [G] | Whiplash |
| --- | --- | --- | --- | --- | --- |
| Frequency | 74 | 1:20 | | 0-127 / 127 | `filter_freq` |
| Knob F | 75 | 1:21 | | 0-127 | `filter_reso` |
| Knob G | 76 | 1:22 | | (by machine) | (none) |
| Env depth | 77 | **1:23** (same as env delay) | **1:26** | 0-127 / 64 (centred) | `filter_env_depth` |
| Attack / decay / sustain / release | 70 / 71 / 72 / 73 | 1:16-1:19 | | / 0, 64, 0, 64 | `filter_attack` … `filter_release` |
| Env delay | 91 | 1:23 | | 0-127 / 0 | `filter_env_delay` |
| Key tracking | 92 | 1:69 | | 0-100 / 0 | `filter_key_tracking` |
| Base | 26 | **1:51** (same as LFO2 mult) | **1:24** | 0-127 / 0 | (none) |
| Width | 27 | **1:52** (same as LFO2 fade) | **1:25** | 0-127 / 127 | (none) |
| BW routing | (none) | (none) | **CC 27** (same as width) / 1:15 | 0-1 | (none) |
| Env reset | 111 | 1:68 | | 0-1 / 0 [G] (but [M] p. 56 says ON is default) | (none) |

**Amp** ([M] B.5, p. 110)

| Param | CC | NRPN | Range / default [G] | Whiplash |
| --- | --- | --- | --- | --- |
| Attack | 79 | 1:30 | / 0 | `amp_attack` |
| Hold | 80 | 1:31 | / 127 (= NOTE) | `amp_hold` |
| Decay | 81 | 1:32 | / 64 (127 = inf) | `amp_decay` |
| Sustain | 82 | 1:33 | / 127 | `amp_sustain` |
| Release | 83 | 1:34 | / 32 (127 = inf) | `amp_release` |
| Env reset | 88 | 1:41 | 0-1 / 1 | (none) |
| Mode | 87 | 1:40 | 0 AHD, 1 ADSR / 0 | (none) (planned `amp_mode` in v0.5) |
| Pan | 90 | 1:38 | / 64 | `pan` |
| Volume | 89 | 1:39 | / 110 | `amp_volume` |

**FX** ([M] B.7, p. 110)

| Param | CC | NRPN [M] | NRPN [G] | Whiplash |
| --- | --- | --- | --- | --- |
| Bit reduction | 54 | (none) | 1:11 | `bit_reduction` |
| Overdrive | 57 | (none) | 1:14 | `overdrive` |
| SRR | 55 | (none) | 1:12 | `sample_rate_reduction` |
| SRR routing | 56 | (none) | 1:13 | (none) |
| Overdrive routing | (none) | (none) | **CC 25** / 1:10 | (none) |
| Delay send | 84 | 1:36 | | `delay_send` |
| Reverb send | 85 | 1:37 | | `reverb_send` |
| Chorus send | 12 | 1:35 | | `chorus_send` |

**Mod / LFOs** ([M] B.8, pp. 110-111). Speed and depth are hi-res, and centred at 64 (14-bit 8192). [G] gives a speed default of 14336.

| Param | LFO1 CC (NRPN) | LFO2 CC (NRPN) | LFO3 CC (NRPN) | Whiplash |
| --- | --- | --- | --- | --- |
| Speed | 102 / LSB 58 (1:42) | 112 / 60 (1:50) | 78 / 62 (1:58) | `lfoN_speed` (MSB only) |
| Multiplier | 103 (1:43) | 113 (1:51) | 52 (1:59) | (none) |
| Fade | 104 (1:44) | 114 (1:52) | 53 (1:60) | (none) |
| Destination | 105 (1:45) | 115 (1:53) | 28 (1:61) | (none) |
| Waveform | 106 (1:46) | 116 (1:54) | 29 (1:62) | (none) |
| Start phase | 107 (1:47) | 117 (1:55) | 30 (1:70) | (none) |
| Trig mode | 108 (1:48) | 118 (1:56) | 31 (1:71) | (none) |
| Depth | 109 / LSB 59 (1:49) | 119 / 61 (1:57) | 86 / 63 (1:72) | `lfoN_depth` (MSB only) |

**Euclidean sequencer** ([M] B.6, p. 110). These are NRPN only, with no CC:
- 3:8 pulse generator 1, 3:9 pulse generator 2.
- 3:14 mode on/off, 3:10 boolean operator.
- 3:11 / 3:12 rotation generators 1 and 2, 3:13 track rotation.

Whiplash sends none of these.

**MIDI-track CC VAL slots** ([M] p. 113): VAL1-8 = CC 70-77 (NRPN 1:16-1:23), and VAL9-16 = NRPN 1:60-1:67 only. These are the same numbers as the filter CCs on audio tracks.

**Misc** ([M] B.9, p. 113)

| Param | CC | NRPN [M] | NRPN [G] | Range [G] | Whiplash |
| --- | --- | --- | --- | --- | --- |
| Pattern mute | 110 | 1:104 | **1:109** | 0-1 | (none) |
| Sample slot | 19 | 1:8 | | 0-127 | `sample_slot` |
| Sample bank | 24 | 1:9 | | 0-7 | **blocked** |

### 8.2 FX CONTROL channel (send FX, compressor, master, external in)

**Delay** ([M] B.9, p. 111). All NRPNs are on MSB 2.

| Param | CC | NRPN | [G] default |
| --- | --- | --- | --- |
| Time | 21 | 2:0 | 23 |
| Pingpong | 22 | 2:1 | 0 |
| Stereo width | 23 | 2:2 | 64 |
| **Feedback** | **24** | 2:3 | 32 |
| HPF | 25 | 2:4 | 32 |
| LPF | 26 | 2:5 | 96 |
| Reverb send | 27 | 2:6 | 0 |
| Mix volume | 28 | 2:7 | 110 |

Delay TIME is in 128th notes: 32 = 1/4, 16 = 1/8, 8 = 1/16, 24 = dotted 1/8 ([M] p. 61).

**Reverb** ([M] pp. 111-112)

| Param | CC | NRPN |
| --- | --- | --- |
| Predelay | 29 | 2:8 |
| Decay | 30 | 2:9 |
| Shelving freq | 31 | 2:10 |
| Shelving gain | 89 | 2:11 |
| HPF | 90 | 2:12 |
| LPF | 91 | 2:13 |
| Mix volume | 92 | 2:15 |

**Chorus** ([M] p. 112)

| Param | CC | NRPN |
| --- | --- | --- |
| Depth | 16 | 2:41 |
| Speed | 9 | 2:42 |
| HPF | 70 | 2:43 |
| Width | 71 | 2:44 |
| Delay send | 12 | 2:45 |
| Reverb send | 13 | 2:46 |
| Mix volume | 14 | 2:47 |

**Compressor** ([M] B.10, p. 112)

| Param | CC | NRPN | Notes |
| --- | --- | --- | --- |
| Threshold | 111 | 2:16 | |
| Attack | 112 | 2:17 | |
| Release | 113 | 2:18 | |
| Makeup | 114 | 2:19 | |
| Ratio | 115 | 2:20 | [G] 0-7 = 1.5, 2, 3, 4, 6, 8, 16, 20 |
| Sidechain source | 116 | 2:21 | |
| Sidechain filter | 117 | 2:22 | |
| Dry/wet | 118 | 2:23 | |
| Pattern volume | 119 | 2:24 | |

**External in mixer** ([M] pp. 112-113)

| Param | CC | NRPN [M] | NRPN [G] |
| --- | --- | --- | --- |
| Dual mono | 82 | 2:40 | |
| L (or LR) level | 72 | 2:30 | |
| R level | 73 | 2:31 | |
| L pan / LR balance | 74 | 2:32 | |
| R pan | 75 | 2:33 | |
| L chorus send | 76 | 2:34 | |
| R chorus send | 77 | 2:35 | |
| L delay send | 78 | 2:36 | |
| R delay send | 79 | **2:35** (same as R chorus) | **2:37** |
| L reverb send | 80 | 2:38 | |
| R reverb send | 81 | 2:39 | |

**Master overdrive** ([M] p. 113): CC 17, NRPN **2:37** in [M] and **2:50** in [G]. The [M] address is also the [G] address of the R delay send.

### 8.3 Discrepancies, all in one place

| # | Item | [M] OS 1.17 | [G] | Note |
| --- | --- | --- | --- | --- |
| 1 | Track mute NRPN | 1:101 | 1:108 | |
| 2 | Track level NRPN | 1:100 | 1:110 | |
| 3 | Portamento time / on-off NRPN | 3:7 / 3:8 | 3:6 / 3:7 | |
| 4 | Filter env depth NRPN | 1:23 | 1:26 | [M] gives 1:23 to env delay too |
| 5 | Filter base / width NRPN | 1:51 / 1:52 | 1:24 / 1:25 | [M] gives the same NRPNs to LFO2 multiplier/fade |
| 6 | Pattern mute NRPN | 1:104 | 1:109 | |
| 7 | Master overdrive NRPN | 2:37 | 2:50 | |
| 8 | Ext-in R delay send NRPN | 2:35 | 2:37 | [M] gives 2:35 to R chorus send too |
| 9 | BR / OD / SRR / SRR-routing NRPN | none | 1:11 / 1:14 / 1:12 / 1:13 | |
| 10 | Overdrive routing | not in App. B (parameter exists, p. 58) | CC 25, NRPN 1:10 | |
| 11 | BW routing | not in App. B (parameter exists, p. 56) | CC 27 (same as width), NRPN 1:15 | [G]'s CC is suspect |
| 12 | Absolute sample NRPN | none | 1:3 | |
| 13 | Repitch TUNE | A.2.4 lists no TUNE | Tune CC 16 | |
| 14 | Filter env reset default | ON (p. 56) | 0 (off) | |
| 15 | Chromatic note range label | "E2-C7" for notes 16-84 | | With [M]'s own 0 = C0, 16 is E1 |
| 16 | Section numbering | B.8/B.9 used twice; "10.7.3" sits inside 10.8 | | Cosmetic |

**Every CC number that Whiplash sends agrees in both sources.** The disagreements are all NRPN addresses, defaults, or parameters that only one source lists.

Consequences in the code:
- Named params are CC-only.
- `Param.nrpn` holds the [G] address, as documentation only.
- Raw `nrpn` stays available for anyone who has checked their own unit.

---

## 9. Transport, clock, tempo, patterns, songs

- **Clock receive** ([M] p. 77): the unit follows the incoming 24-PPQN clock for tempo. Its delay time, LFO sync and pattern speed then track Whiplash's BPM.
- **Transport receive:**
  - **Start** starts the unit's sequencer from the top, playing the selected pattern, song or chain with all its trigs.
  - **Stop** stops it.
  - **Continue** resumes. On the panel, [PLAY] while playing pauses and [PLAY] again resumes ([M] p. 40).
  - Stop cuts the sound, but delay tails ring out. [STOP] + [STOP] cuts the FX tails short ([M] p. 40).
- **Tempo** ([M] p. 22-23):
  - **Scope:** per project or per pattern, toggled with [FUNC] + knob E in the TEMPO menu.
  - **Nudge:** [LEFT]/[RIGHT] for ±10 % temporarily. **Tap:** [FUNC] + [TEMPO], or note C0 on the FX channel.
  - **Swing:** 50-80 %, set per pattern. It applies to the unit's sequencer only, not to incoming notes.
- **Pattern changes** ([M] p. 40-41, p. 46-47):
  - **When they happen:** a newly selected pattern starts **when the current one reaches its end**. PAGE SETUP > CHANGE can make that sooner or later, and RESET = INF needs CHANGE set.
  - **How to trigger them:** program change selects and queues patterns too.
  - **Chains** loop.
  - **Pattern SPEED** (1/8× to 2×) and **per-track length** (PER TRACK mode) are sequencer-only.
- **Song mode** ([M] p. 50-52):
  - **Rows:** each row has a pattern, play count, length, tempo (or one tempo for the whole song), swing and mutes. END loops or stops.
  - **Playback:** [STOP] then [PLAY] continues from the playhead, and [STOP] [STOP] rewinds. Selecting a pattern leaves song mode.
- **Fill mode** ([M] p. 49): [YES] + [PAGE] for one cycle, holding [PAGE] while it's needed, or latched. Trigs with FILL ON/OFF play accordingly. This is the unit's own fill, and it is separate from `whiplash_mutate fill`.

---

## 10. Mutes: panel modes vs CC

- **GLOBAL MUTE mode** ([FUNC] + [TRK], green keys): mutes apply in **all patterns** and are **saved with the project** ([M] p. 26-27).
- **PATTERN MUTE mode** ([FUNC] + double [TRK], magenta keys): mutes apply to the active pattern and are **saved with the pattern** ([M] p. 27).
- **Quick mute and prepared mutes:** QUICK MUTE is [FUNC] + [TRACK] keys. Prepared mute/unmute takes effect on releasing [FUNC] ([M] p. 27).
- **Song rows** carry their own mute state, initialised from the pattern ([M] p. 50).
- **MIDI:**
  - **CC 94** "Mute": track parameter, 0 = unmuted, 1 = muted ([M] p. 109, [G]).
  - **CC 110** "Pattern Mute" ([M] p. 113, [G]).
  - Interpretation: CC 94 drives the global mute and CC 110 the pattern mute. HW: check which panel mode lights up.
- **MUTE DEST** (INT / INT+EXT / EXT) decides whether panel mutes also *send* MIDI ([M] p. 78). It doesn't affect receiving.
- **Whiplash** mutes in its own sequencer by default, by not sending the notes. Only `hardware: true` sends CC 94. Because a unit-side (global) mute persists in the project, Whiplash releases every CC 94 mute it set on unmute, stop and exit.
- **A Whiplash software mute can't silence the unit's own sequencer trigs.** Those trigs play whenever transport receive started the unit (README "Transport").

---

## 11. Parameter locks, incoming CC and modulation

- **P-locks** ([M] p. 47-48):
  - Every trig can carry its own values for any PARAMETER-page parameter, up to 80 distinct locked parameters per pattern.
  - **Lock trigs** change parameters without playing a note.
  - **Sample locks** (SAMP) and **preset locks** (from the pool, audio tracks) are p-locks too.
- **How a p-lock and an incoming CC interact.** Interpretation (consistent with [M] p. 35 and p. 47): incoming CC sets the track's base value, the same as turning the knob. A p-locked trig played by the **unit's sequencer** still uses its locked value on that step. Notes arriving over MIDI aren't sequencer trigs, so they carry no p-locks and play with the current base values. Elektron's documentation doesn't spell this out (HW).
- **LFOs** modulate around the current base value, so ramping a param that an LFO targets moves the centre of the modulation.
- **Live recording** of knob moves can create p-locks ([M] p. 42-43, p. 82 PARAM LIVE REC). Whiplash never enables recording, but if the user is in LIVE RECORDING mode while Whiplash plays, incoming notes and CCs could be recorded. Interpretation from [M] p. 43: external notes on the AUTO channel are recorded.

---

## 12. Retrigs, micro timing, conditions

- **Retrigs** ([M] p. 45, p. 54):
  - Per trig, audio tracks only. RATE is 1/1 to 1/80, LEN 0.125-INF, and VFAD −64..64 sets the velocity fade.
  - There is **no MIDI control** of retrigs. Whiplash ratchets by sending extra notes (the 32nd-note hats in its fills).
- **Micro timing:** per trig, on the unit's sequencer ([M] p. 45). Whiplash's humanize offsets its own notes instead.
- **Trig conditions and probability** ([M] p. 48, p. 53): sequencer-only.
- **Euclidean mode** ([M] p. 44): per-track pulse generators, with NRPN-only control (§8.1).

---

## 13. Sampling and the sample pool

- **Sampling** ([M] p. 23-24, p. 68-69):
  - **Sources:** IN L/R, USB L R, or internal resampling, with threshold arming.
  - **Limits and processing:** 66 s maximum, normalized automatically, then trimmed and saved.
  - **Where it goes:** the saved sample lands in the +Drive's RECORDED directory ([M] p. 71), and can then be assigned to a track.
- **The SAMPLES menu** ([FUNC] + [SAMPLING], [M] p. 70-73) has views of the +Drive and of RAM.
  - **Loading:** LOAD TO PROJECT puts samples into the first free slots of the 1016.
  - **Managing:** unload, replace, rename, move, and remove unused. Transfer moves samples between a computer and the unit.
- **Assigning:** SRC knob D (SAMP) opens the pool list; [TRIG] previews ([M] p. 36).
- **What a slot number means over MIDI.** CC 19 picks slot 0-127 *within the selected sample bank* (CC 24 picks the bank, 0-7 = 8 × 128 = 1024 addresses for 1016 slots). Neither source says whether CC 19 = 0 is OFF or the first sample (HW).

---

## 14. USB audio, MIDI and Overbridge

- **USB CONFIG** ([M] p. 83) has three modes, and **picking one disables the other two**:
  - **OVERBRIDGE:** deep DAW integration through Elektron's plug-in, with parameter editing and automation, total recall, and multitrack audio ([M] p. 20).
  - **USB MIDI:** MIDI only.
  - **USB AUDIO/MIDI:** class-compliant audio and MIDI, with no driver needed ([M] p. 20).
- **AUDIO ROUTING** ([M] p. 80-81) applies when USB audio is active:
  - **USB IN:** MAIN or OFF.
  - **USB OUT** is a single stereo pair. It can be MAIN, one or two chosen tracks (L:T / R:T), EXT (the inputs), or OFF.
  - **INT TO MAIN:** OFF, ON, or **AUTO**. AUTO means "when USB audio streaming is active, no internal sound is sent to the main out".
  - **USB TO MAIN:** 0 to +18 dB.
  - **PRE/POST FADER.**
  - Track outputs over USB carry no effects. Overbridge gets per-track outputs even for tracks that don't send to MAIN.
- **TO MAIN / TO FX** ([M] p. 80-81): which tracks, effects and inputs reach the main outs and the effects.
- **Transfer** (computer app over USB MIDI) does backups, sample transfer and OS updates ([M] p. 20-21, p. 83).
- **SysEx dump** ([M] p. 79-80):
  - **Send:** the project, a pattern, or presets.
  - **Receive:** the unit "is continuously listening for SysEx data". It can store received patterns and presets to slots.
  - **This is why Whiplash refuses SysEx outright.**

Whiplash visualiser implications:
- The browser can only capture the unit when USB CONFIG = **USB AUDIO/MIDI**. MIDI keeps working in that mode.
- What it captures is the single USB OUT pair, which is normally MAIN. That's why per-track meters have to be MIDI-derived, unless USB OUT is set to specific tracks.
- With INT TO MAIN = AUTO, the main/headphone outs might go quiet while the stream is active. HW: check whether a capture-only stream (computer recording, sending nothing) counts as "streaming".

---

## 15. Implications for Whiplash

Status key: ✅ matches the manual, ⚠️ right but with a caveat worth knowing, 🔧 fixed in the PR that added this file. Nothing here is hardware-verified, except where §0 of the v0.5 plan records it (CC 19 slots switching, Phil, 2026-11-11).

### 15.1 What the code assumes

| # | Assumption (where) | Status | Why |
| --- | --- | --- | --- |
| 1 | Track n plays on MIDI channel n, 1-8 (`engine.py` `ch = track - 1`; README setup) | ✅ | The factory default is track n = channel n ([M] p. 25). It is user-changeable in CHANNELS ([M] p. 79). |
| 2 | Note 60 = the sample's own pitch (`patterns.DRUM = 60`; README) | ⚠️ | [M] p. 25 (C5 = 60), TUNE 0 = unchanged (p. 93), [G] Trig Note default 60. It only holds while TUNE = 64 and the preset OCTAVE is unchanged (p. 38), with no LFO on tune. Grid/Slice with SLICE = NOTE pick slices instead. The per-track-channel range is undocumented (HW). |
| 3 | Melodic parts several semitones to an octave and a half below 60 (`patterns.py`) | 🔧 v0.5.0 | Every semitone below 60 slows the sample down (§6.1). `patterns.register()` now lifts each generated melodic part by whole octaves until its median is at most 7 below 60; `whiplash_transpose` and the `pitch` block let the agent correct the rest. `pitch` can't see the preset OCTAVE or an LFO on tune. |
| 4 | Every named param CC number (`ccmap._TABLE`) | ✅ | All 38 CCs (37, plus `amp_mode` CC 87 in v0.5.0) and all 6 LFO LSBs match [M] App. B and [G]. `tests/test_reference.py` checks that this file's table and the code agree. |
| 5 | `loop_pos` range 0-127, "Oneshot only" (`ccmap.py`) | 🔧 | [G] gives 0-120 for Oneshot LOOP, the same as START/LENGTH. The same knob is BARS 0-3 on Werp/Stretch/Repitch and GRID 0-4 on Grid. Now `max=120`, with a machine-dependent description. |
| 6 | `lfo3_speed` had no documentation NRPN | 🔧 | [M] and [G] agree on 1:58. Added (it is still never sent). |
| 7 | Named params as CC only, NRPN documented but not sent | ✅ | §8.3 lists 8 NRPN conflicts, three of them inside the manual. |
| 8 | Blocked CCs: 0, 32, 24, 6, 38, 98-101 (`ccmap.BLOCKED_CCS`) | ✅ | **0/32:** bank select (MIDI-track BANK/SBNK, p. 103). **24:** sample bank on a track channel, and delay feedback on the FX channel (§7.4). **6/38/98-101:** NRPN plumbing. Keep them all blocked. |
| 9 | Sample select only via CC 19 inside the selected bank; NRPN 1:3/1:8/1:9 blocked | ✅ | [M] p. 109, p. 113; [G]. Whether slot 0 is OFF is still HW. |
| 10 | No SysEx and no program change (`Engine.send` allow-list) | ✅ | PC switches patterns (p. 25, p. 77). SysEx can store patterns and presets into slots (p. 80). Never relax this. |
| 11 | MIDI Start runs the unit's own pattern, so warn or use clock-only (`overlap_warning`, `send_transport`) | ✅ | TRANSPORT RECEIVE (p. 77). Patterns start from the top on Start (§9). |
| 12 | Clock-only still drives the unit's tempo | ✅ | CLOCK RECEIVE is separate from TRANSPORT RECEIVE (p. 77). |
| 13 | Hardware mute = CC 94, 1/0 (`ccmap mute`, `set_mute(hardware=True)`) | ⚠️ | The CC and values are right ([M] p. 109, [G]). Which panel mute mode it drives isn't documented. If it's the global mute, it is project-wide and saved with the project (p. 27), which is why releasing it on stop/exit matters. CC 110 (pattern mute) is unused. |
| 14 | Parameter changes last "until you reload" (README safety) | ⚠️ | True, but the edit lives in the active pattern's kit. It survives pattern switches, and (interpretation) power cycles, until a reload: [FUNC] + [NO] (p. 49), RELOAD FROM PROJ (p. 77), or [TRK] + [TRIG] + [NO] (p. 53). It is never written to the saved project unless the user saves. README updated to say so. |
| 15 | Gate lengths shape notes (`engine.GATE`, pattern gates) | ⚠️ | Only with AMP MODE = AHD and HOLD = NOTE (the [G] defaults), or with ADSR. A fixed HOLD ignores note-off (p. 56). v0.5.0 adds `amp_mode` (CC 87) and documents `amp_hold` 127 = NOTE. v0.5.1 written parts send `length` as the exact note-off, report `length_audible` with this caveat, and send CC 80 = 127 only on `envelope: "note"`. |
| 16 | Velocity accents, ghost notes and humanize are audible (`mutate.py`) | ⚠️ | Only if the preset's VELOCITY TO VOL is not OFF, or velocity is mod-routed (p. 38-39). HW: the default isn't documented. |
| 17 | Stop/panic sends note-offs per sounding note, plus CC 123 on channels 1-8 (`engine._panic`) | ⚠️ | The note-offs are the real guarantee. CC 123 (All Notes Off) is standard MIDI but isn't in [M], so whether the unit honours it is HW. It does no harm. |
| 18 | Raw `cc` and `nrpn` go to the track's channel (`set_param`) | ⚠️ | Raw CC numbers mean different things on a MIDI-machine track (CC 70-77 = VAL1-8) and on the FX channel. Raw access can't reach the FX channel unless it shares a track's channel, which §7.4 says to avoid. |
| 19 | Retrig/ratchet and fills are done by sending notes (`mutate.py`) | ✅ | The unit's retrigs and fill mode have no MIDI control (§12). |
| 20 | Swing and humanize live in Whiplash | ✅ | The unit's swing and micro timing apply only to its own sequencer (§9, §12). |
| 21 | The visualiser captures "the stereo main mix" over USB (README) | ⚠️ | Needs USB CONFIG = USB AUDIO/MIDI. USB OUT is one pair: MAIN by choice, or selected tracks (p. 81). Check INT TO MAIN (§14). |
| 22 | v0.5.0 clamps transpose to 16-84 (`engine.clamp_note`) | ✅ | Conservative: that is the documented chromatic range (AUTO channel, p. 25). The track-channel range is undocumented, and KEYBOARD mode spans C0-G10 (p. 25). v0.5.1 written notes are validated against the same 16-84. |
| 23 | v0.5.1 written parts may play on tracks 9-16 (channels 9-16) (`whiplash_write_part`) | ⚠️ | Track n = channel n holds for 9-16 too ([M] p. 25, p. 79). But AUTO CHANNEL or FX CONTROL CH may sit on one of those channels (§7.3, §7.4; factory values are HW question 1), in which case notes and CCs reach a second target. Results on tracks 9-16 carry a `channel_note` saying so. Panic still sends CC 123 only on channels 1-8; held notes on 9-16 get their own note-offs. |
| 24 | A retrigger of the same note ends the held one (`engine._run`) | ⚠️ | When a written note is longer than the gap to the next hit of the same note, Whiplash sends that note's note-off just before the new note-on, so the old note-off can't cut the new note. Whether the unit retriggers or layers voices on one track isn't documented here (HW). |

### 15.2 Things Whiplash must keep never doing

These rules are enforced in code; don't relax them:
- **No SysEx** (it can rewrite slots, p. 80).
- **No program change** (it switches patterns, p. 25).
- **No MIDI bank select** (CC 0/32).
- **No sample-bank or absolute-sample NRPN** (CC 24, NRPN 1:3/1:9).
- **No raw NRPN data-entry CCs.**

These follow from the manual, and no tool does them today:
- **No transfers:** no project, pattern, kit or preset writes, and no +Drive access (that's Transfer/SysEx territory).
- **No FX CONTROL channel traffic by default.** It is pattern-wide and can include feedback (delay feedback CC 24, comb FDBK; "can lead to a very loud signal", p. 62, p. 108).
- **No CC 1/2 by default** (mod wheel / breath, if the preset assigns them, p. 39).
- **No TRIG-page CCs 3/4/5,** which rewrite the track's default trig note, velocity and length for the unit's own sequencer.

### 15.3 Open hardware questions

Check these on the unit, and record the result in this file with a date:
1. SETTINGS > MIDI CONFIG > CHANNELS factory values for FX CONTROL CH, AUTO CHANNEL and PRG CHG IN CH (§7.3).
2. Notes 48 / 60 / 72 on a track channel with TUNE 64. Does 60 equal the [TRIG] key's pitch? Does the KB octave setting change anything on a track channel? What is the usable note range there?
3. Which mute mode CC 94 and CC 110 drive (green global vs magenta pattern).
4. CC 19 = 0: OFF or the first sample?
5. Does CC 123 (All Notes Off) silence held notes?
6. The default VELOCITY TO VOL and AMP HOLD on factory and empty presets.
7. INT TO MAIN = AUTO while the visualiser captures USB audio: do the main outs stay on?
8. Grid/Slice with SLICE = NOTE: which note plays slice 1 on a track channel?
9. Written-part length (v0.5.1): with AHD and a fixed HOLD, does `length` change nothing? With CC 80 = 127, does the unit show HOLD = NOTE and does `length` shorten the sound? With ADSR (CC 87 = 1), do length and release shape it? (v0.5 plan HW 2.)

---

## 16. Where to look in the manual

| Topic | [M] section / page |
| --- | --- |
| Data structure | 5, p. 16-17; 9, p. 29-36 |
| MIDI notes, program change | 8.4, p. 25 |
| KEYBOARD mode, scales, fold | 8.5.1-8.5.2, p. 25-26; App. D, p. 115 |
| Mute modes | 8.5.3, p. 26-27 |
| SETUP > TRACK (octave, velocity curve, mod assignments) | 9.8.2, p. 38-39 |
| Pattern change, chains | 10.1, p. 40-41 |
| P-locks, preset locks, conditions, fill | 10.8, p. 47-49 |
| Temp save/reload, song mode, perform kit | 10.8.6-10.10, p. 49-52 |
| Track parameters | 11, p. 53-60 |
| Send FX and mixer | 12, p. 61-67 |
| MIDI CONFIG (sync, ports, channels) | 14.4, p. 77-79 |
| SysEx dump | 14.5, p. 79-80 |
| Audio routing, USB config | 14.6, p. 80-81; 14.8.1, p. 83 |
| Machines | App. A, p. 93-108 |
| CC/NRPN tables | App. B, p. 109-113 |
| LFO destinations | App. C, p. 114 |
