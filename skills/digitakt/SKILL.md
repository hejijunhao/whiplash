---
name: digitakt
description: How to drive an Elektron Digitakt II through the Whiplash tools - pitch and register, sample slots, note length vs AMP MODE/HOLD, transport overlap, and a checklist for sounds that come out wrong.
---

# Whiplash on a Digitakt II

Whiplash sends MIDI notes, clock, transport and CCs to the Digitakt II, one MIDI channel per track (track N = channel N). It can't read anything back from the unit. This skill ships with the plugin and is updated with it, so trust it over any older notes of your own.

## Pitch and register (check this first)

- MIDI note **60 plays a sample at its own pitch**, as long as TUNE is 64 and the preset's OCTAVE (FUNC+FLTR > TRACK) is unchanged. Each semitone below pitches the sample down, which makes it slower and grainier. Whiplash can't see OCTAVE or an LFO on tune, so if `pitch` looks right but the sound doesn't, ask the user about those.
- On Grid/Slice machines with SLICE = NOTE, the note picks a slice instead of a pitch, so transpose changes which slice plays.
- Generated melodic parts (bass, chords, stabs) are placed near 60. Each `whiplash_play_pattern` and `whiplash_status` result shows `tracks[n].pitch`, including `semitones_from_native`.
- If a line sounds **stretched, grainy, muddy or distorted**, look at `pitch` before anything else. Raise it with `whiplash_transpose(track, octaves: 1)` or `semitones`, or with `tune` (`whiplash_set_param`, 64 = none, 76 = +12). Do this before you touch the envelope or density.
- Note names follow Elektron's numbering: C0 = MIDI 0, so C5 = MIDI 60. Logic Pro calls 60 "C3" and General MIDI "C4", so quote raw numbers when it matters.
- Transpose lands on the next bar, carries across pattern switches, and `whiplash_stop` resets it. You can also pass it at start: `whiplash_play_pattern(genre, transpose: {"6": 12})`.

## Track roles are assumptions

- The pattern assumes 1 kick, 2 rim/snare, 3 clap, 4 closed hat, 5 open hat, 6 bass, 7-8 chords or stabs. Results mark these `(assumed)`.
- The user's kit may be laid out differently, so ask what each track holds before you describe the beat as "bass" or "chords".

## Sample select

- `whiplash_select_sample(track, slot)` **does switch samples**: it sends CC 19, a slot 0-127 within the sample bank currently selected on the unit. It only picks among samples already loaded in the project.
- Whiplash can't list, name, preview or load samples. Ask the user what a slot holds, or try neighbouring slots and ask how they sound.
- `slot` in status is the last slot Whiplash sent. It is `null` until Whiplash has sent one.

## Note length and the amp envelope

- A note's length only shortens the sound if the track's envelope listens to note-off. That is the case in **AMP MODE = ADSR** (`amp_mode` 1, CC 87) or in **AHD with HOLD = NOTE** (`amp_hold` 127, CC 80). midi.guide lists AHD with HOLD = NOTE as the default, but a given preset may differ, so ask.
- In AHD with a fixed hold (0-126), note-off is ignored and every hit is the same length.
- "Plays non-stop" or "too droney" usually means a long decay (127 = infinite) or a fixed hold on the unit. Shorten `amp_decay`, or set `amp_hold` to 127 so the note length counts.
- Never change the envelope mode without telling the user. It changes the sound of their kit until they reload it.

## Transport and the unit's own pattern

- By default Whiplash sends MIDI Start, which also starts the Digitakt's own sequencer, so trigs stored in the pattern selected on the unit play on top.
- Unexpected drums or notes that mutes can't silence come from the unit's own pattern. Tell the user to select an empty pattern, or restart with `send_transport: false` (clock only).

## Diagnostics checklist

| Symptom | Check first |
| --- | --- |
| Stretched, grainy, too low | `tracks[n].pitch`, then `whiplash_transpose` up an octave |
| Plays non-stop, droney | amp hold/decay, and `amp_mode` (see above) |
| Drums you didn't ask for | the unit's own pattern: empty pattern or clock only |
| Wrong instrument on a track | ask the user, then `whiplash_select_sample` |
| Silence everywhere | `warning` in a result: virtual port, no Digitakt connected |

## What Whiplash can never do

- Send SysEx, read sample names, or load files onto the unit.
- Switch sample banks (CC 24) or machines (Oneshot, Werp, ...).
- Write or save projects, patterns or kits.

## After a plugin update

The Hermes gateway keeps the old plugin code until it restarts, so run `hermes gateway restart`. A new chat is not enough.
