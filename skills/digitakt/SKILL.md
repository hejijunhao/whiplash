---
name: digitakt
description: How to drive an Elektron Digitakt II through the Whiplash tools - writing melodies and rhythms, pitch and register, sample slots, note length vs AMP MODE/HOLD, transport overlap, and a checklist for sounds that come out wrong.
---

# Whiplash on a Digitakt II

Whiplash sends MIDI notes, clock, transport and CCs to the Digitakt II, one MIDI channel per track (track N = channel N). It can't read anything back from the unit. This skill ships with the plugin and is updated with it, so trust it over any older notes of your own.

## Writing notes, melodies and rhythms

You **can write melodies and rhythms**: `whiplash_write_part` replaces one track's generated line with the notes you give, from the next bar line. Don't send the user to KEYBOARD mode for a melody.

- **Where the hits go** (pick one):
  - `rhythm`: `four_on_floor` (every beat), `on_kick` (copies track 1's hits), `offbeat_8ths`, `8ths`, `16ths`, `off_16ths`, `syncopated`, `half_time`.
  - `grid`: a 16-cell step mask per bar, `"x..x..x.x..x..x."` (`X` = accent), or a list of up to 4 bars.
  - `steps`: `[0, 3, 6, 10]` (0 = the downbeat, 4 = beat 2, 15 = the last 16th).
  - `hits`: `[{step, note, length, velocity, bar}]` for full control.
  - `lock_to`: another track's hits, copied now (`lock_to: 1` locks a bass to the kick). It doesn't follow later changes to that track.
- **What plays:** `notes` cycle over the hits: `["C5", "D#5", "G5"]`, MIDI numbers, `"."` for a rest, or with `key` (and `scale`) degrees like `"1 3 5 b7"`. C5 = MIDI 60 = the sample's own pitch, so write bass and synth lines **around C5** (roughly C4-C6), not down at C2/C3 where they sound stretched.
- **Shape:** `length` in 16th steps (0.25-16; 1 = a 16th, 4 = a beat), `velocity` (1-127, a list, or `"accent"`), `bars` (1, 2 or 4 before it repeats).
- Examples:
  - Four-on-the-floor bass on track 6: `whiplash_write_part(track: 6, rhythm: "four_on_floor", notes: ["A4"])`.
  - Bass locked to the kick: `whiplash_write_part(track: 6, lock_to: 1, notes: ["A4", "A4", "C5", "G4"])`.
  - A melody: `whiplash_write_part(track: 7, rhythm: "8ths", key: "Am", notes: "1 3 5 8 7 5 3 .", length: 1.5)`.
- Mutes, drops, fills, density, humanize and transpose still apply to a written part. It carries across pattern switches and `whiplash_mutate reset`; `reset: true` brings back the generated line, and `whiplash_stop` clears every written part.
- Tracks 1-16 work. On 9-16, check with the user that the unit's AUTO CHANNEL and FX CONTROL CH aren't on that channel.
- The result echoes each bar as a grid with note names; read it back to the user in their terms.

## Pitch and register (check this first)

- MIDI note **60 plays a sample at its own pitch**, as long as TUNE is 64 and the preset's OCTAVE (FUNC+FLTR > TRACK) is unchanged. Each semitone below pitches the sample down, which makes it slower and grainier. Whiplash can't see OCTAVE or an LFO on tune, so if `pitch` looks right but the sound doesn't, ask the user about those.
- On Grid/Slice machines with SLICE = NOTE, the note picks a slice instead of a pitch, so transpose changes which slice plays.
- Generated melodic parts (bass, chords, stabs) are placed near 60. Each `whiplash_play_pattern` and `whiplash_status` result shows `tracks[n].pitch`, including `semitones_from_native`.
- If a line sounds **stretched, grainy, muddy or distorted**, look at `pitch` before anything else. Raise it with `whiplash_transpose(track, octaves: 1)` or `semitones`, or with `tune` (`whiplash_set_param`, 64 = none, 76 = +12). Do this before you touch the envelope or density.
- Note names follow Elektron's numbering: C0 = MIDI 0, so C5 = MIDI 60. Logic Pro calls 60 "C3" and General MIDI "C4", so quote raw numbers when it matters.
- Transpose works on any track that plays, including written parts on 9-16. On a track that plays nothing it is refused: write the part first.
- Transpose lands on the next bar, carries across pattern switches, and `whiplash_stop` resets it. You can also pass it at start: `whiplash_play_pattern(genre, transpose: {"6": 12})`.

## Track roles are assumptions

- The pattern assumes 1 kick, 2 rim/snare, 3 clap, 4 closed hat, 5 open hat, 6 bass, 7-8 chords or stabs. Results mark these `(assumed)`.
- The user's kit may be laid out differently, so ask what each track holds before you describe the beat as "bass" or "chords".

## Sample select

- `whiplash_select_sample(track, slot)` **does switch samples**: it sends CC 19, a slot 0-127 within the sample bank currently selected on the unit. It only picks among samples already loaded in the project.
- Whiplash can't list, name, preview or load samples. Ask the user what a slot holds, or try neighbouring slots and ask how they sound.
- `slot` in status is the last slot Whiplash sent. It is `null` until Whiplash has sent one.

## Note length and the amp envelope

- `whiplash_write_part` sends `length` as the exact MIDI note-off. Every result carries `length_audible`: read it before you promise shorter notes.
- To make length audible, ask the user, then either pass `envelope: "note"` on `whiplash_write_part` (one CC 80 = 127, HOLD = NOTE) or call `whiplash_set_param(track, param: "amp_hold", value: "note")`. The result says `hold: "NOTE"`. For release tails, `amp_mode` 1 (ADSR) plus `amp_release`.
- A note's length only shortens the sound if the track's envelope listens to note-off. That is the case in **AMP MODE = ADSR** (`amp_mode` 1, CC 87) or in **AHD with HOLD = NOTE** (`amp_hold` 127, CC 80). midi.guide lists AHD with HOLD = NOTE as the default, but a given preset may differ, so ask.
- In AHD with a fixed hold (0-126), note-off is ignored and every hit is the same length.
- `amp_hold` 127 is not "the most hold": it switches HOLD to NOTE. So `amp_hold` clamps to 0-126 and ramps never go past 126. Only `"note"` or exactly 127 sends NOTE, and the result says so.
- "Plays non-stop" or "too droney" usually means a long decay (127 = infinite) or a fixed hold on the unit. Shorten `amp_decay`, or (with the user's OK) set `amp_hold` to `"note"` so the note length counts.
- Never change the envelope mode without telling the user. It changes the sound of their kit until they reload it.

## Transport and the unit's own pattern

- By default Whiplash sends MIDI Start, which also starts the Digitakt's own sequencer, so trigs stored in the pattern selected on the unit play on top.
- Unexpected drums or notes that mutes can't silence come from the unit's own pattern. Tell the user to select an empty pattern, or restart with `send_transport: false` (clock only).

## Diagnostics checklist

| Symptom | Check first |
| --- | --- |
| Stretched, grainy, too low | `tracks[n].pitch`, then `whiplash_transpose` up an octave |
| Plays non-stop, droney | amp hold/decay, and `amp_mode` (see above); then shorter `length` in `whiplash_write_part` |
| "Wrong rhythm", "make it 4/4", "lock to the kick" | `whiplash_write_part` with `rhythm` or `lock_to`, not density |
| "Play a melody", "different notes" | `whiplash_write_part` with `notes` (and `key`) |
| Drums you didn't ask for | the unit's own pattern: empty pattern or clock only |
| Wrong instrument on a track | ask the user, then `whiplash_select_sample` |
| Silence everywhere | `warning` in a result: virtual port, no Digitakt connected |

## What Whiplash can never do

- Send SysEx, read sample names, or load files onto the unit.
- Switch sample banks (CC 24) or machines (Oneshot, Werp, ...).
- Write or save projects, patterns or kits.

## After a plugin update

The Hermes gateway keeps the old plugin code until it restarts, so run `hermes gateway restart`. A new chat is not enough.
