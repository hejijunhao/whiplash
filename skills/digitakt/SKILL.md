---
name: digitakt
description: How to drive an Elektron Digitakt II through the Whiplash tools - the kit map, one-call start, keys and chord progressions, song arrangement (intro, build, drop, outro), writing melodies and rhythms, pitch and register, sample slots, note length vs AMP MODE/HOLD, transport overlap, and a checklist for sounds that come out wrong.
---

# Whiplash on a Digitakt II

Whiplash sends MIDI notes, clock, transport and CCs to the Digitakt II, one MIDI channel per track (track N = channel N). It can't read anything back from the unit. This skill ships with the plugin and is updated with it, so trust it over any older notes of your own. The tool descriptions are kept short on purpose; the detail is here.

## Fast path: label, then start in one call

1. When the user says what their tracks hold ("track 7 is a cymbal, track 5 is a pad"), call `whiplash_label_tracks(tracks: {"7": "cymbal", "5": "pad"})` straight away. Labelled slots too: `slots: {"11": "synth Phil likes"}`.
2. Start the beat **and** fit it to the kit in the same call: `whiplash_play_pattern(genre: "deephouse", tracks: {"6": {"slot": 9, "transpose": 12}, "8": {"mute": true}})`. Each entry takes `slot` (0-127), `tune` (64 = none), `transpose` (semitones) and `mute`.
3. Read the result, pass on its `overlap_warning` (and any `warning`), and answer. Don't follow up with separate select_sample / transpose / mute calls for things `tracks` already did.

## Kit map (`whiplash_label_tracks`)

- Free text is matched to a role: kick, snare, rim, clap, closed hat, open hat, cymbal, perc, bass, pad, stab, chord, lead, fx, other ("tuned cymbal" -> cymbal, "dirty bass" -> bass, "synth" -> lead). Or give `{"role": "chord", "label": "Rhodes"}`. `null` (or `""`) removes a label; labels merge, so you only send what changed.
- **Generated parts follow the map** from the next bar (or the next start). Each part goes to a track labelled with its role, else to one with a close role (rim <-> snare, chord -> pad, stab -> lead, open hat -> cymbal), else stays on its default track if the user hasn't labelled that track as something else, else it is dropped. A cymbal or fx track never gets a chord, bass or other melodic line. Labelled tracks with no matching part stay silent: write one with `whiplash_write_part`.
- Every `whiplash_play_pattern` result (fresh start and queued switch), every `whiplash_label_tracks` result and `whiplash_status` carry `routing`: which part lands where (`parts`), which were `dropped`, and which labelled tracks are `silent_until_written`. Tell the user in their terms.
- **Written parts win their track.** A track playing a `whiplash_write_part` part is never a routing target: the generated part goes to the next track with a matching label, or, if there is none, `routing.replaced_by_written` names it (the write_part result says `replaces_generated`). Nothing is lost silently, and no second bass appears on the default track.
- **`vacated`:** an unlabelled default track whose part moved to a labelled track plays nothing (e.g. "tracks 7 and 8 are tuned cymbals" moves the open hat from track 5 to 7, so track 5 goes quiet). `routing.vacated` and `vacated_note` say so: tell the user, and offer to label track 5 (e.g. as open hat) or write a part there. Whether this should happen at all is an open question for Phil; don't promise either behaviour.
- **Relabelling while playing:** a part that moves takes its `whiplash_transpose` and density with it (`follows_part` in the result, e.g. `{"transpose": {"6->10": 12}}`). A part that ends up on no track drops them (`"6->dropped"`).
- **Tracks 9-16:** when the kit map routes a generated part there, or `tracks` setup names one, the result carries `channel_note` and `tracks_9_16`. Ask the user to check that AUTO CHANNEL and FX CONTROL CH aren't on those channels.
- Results and `whiplash_status` show the label as `tracks[n].role` (without "(assumed)") plus `kit_role`; `roles_assumed` is false once anything is labelled. A selected slot with a label shows `slot_label`, in `whiplash_select_sample`, `whiplash_set_param` sample_slot and the play `setup` echo too.
- The map lives in memory for the session: it survives `whiplash_stop` and pattern switches. `reset: true` clears it, and so does a gateway restart.
- Labels are only what the user told you. Whiplash can't read sample names (that would need SysEx, which it never sends).

## Keys and chord progressions

- **Key:** `whiplash_play_pattern(genre: "techno", key: "Am")` (or `key: "A", scale: "minor"`) moves the bass, chords and stabs into that key from the first bar, or from the switch bar when queued. Drums never move. Without a key each genre plays in its home key (deep house, soul, tech house A minor; techno F minor; breaks G minor). Once set, the key stays for later switches until `whiplash_stop`. Results and status show `key`.
- **Progression:** `whiplash_set_progression(chords: "i VI III VII", bars_per_chord: 2)`. It starts on the next bar line and loops. Chords are Roman numerals in the key (upper case = major, lower = minor; `V7`, `ii°`, `bVII`, `Imaj7`, `sus4`) or names (`"Am F C G"`). `key` changes the key at the same bar. `voicing`: `close` (default, voice-led), `root`, `open`, `power`.
- **Who follows**, by role (the kit map first, else the pattern's role):
  - chord, pad and stab tracks → `chords`: one chord tone per hit, and each chord track starts on a different tone, so two or three chord tracks together sound the chord.
  - bass → `root`: every hit plays the chord root, in the line's own register.
  - lead → `snap`: notes snap to the scale.
  - Drums, hats, perc, cymbal and fx tracks never change, and `tracks` overrides on them are refused. Never promise chords on a cymbal.
- **One note at a time:** the manual gives the Digitakt II 16 audio voices for 16 tracks and documents chords only on MIDI tracks, so an audio track probably plays one note at a time (not yet checked on hardware). That is why `chords` spreads the chord over tracks and hits. `stack` sends every tone on every hit: only for a MIDI track or a polyphonic target, or if the user finds their unit layers notes.
- **Overrides:** `tracks: {"9": "chords", "6": "off"}` with modes `chords`, `stack`, `root`, `snap`, `off`. A chord track with no line of its own (a labelled pad that got no part) holds one chord tone per bar.
- **"Pads on track 7":** label it first (`whiplash_label_tracks(tracks: {"7": "pad"})`), or pass `tracks: {"7": "chords"}`.
- Written parts play as written unless `tracks` names them (the result lists `written_unchanged`). Transpose, mutes, drops, fills and density still apply on top. The progression carries across switches and `whiplash_mutate reset`; `clear: true` or `whiplash_stop` ends it.
- `whiplash_status` shows `progression.now` (the chord playing and `next_change_at_bar`), every voiced chord with note names, and `tracks[n].progression`. Read the chord names back to the user.
- A melody in the playing key: `whiplash_write_part(track: 8, rhythm: "8ths", key: "current", notes: "1 3 5 8")`.
- Typical request, "deep house in A minor, i-VI-III-VII, two bars per chord, pads on track 7", is three calls: `whiplash_label_tracks(tracks: {"7": "pad"})`, `whiplash_play_pattern(genre: "deephouse", key: "Am")`, then `whiplash_set_progression(chords: "i VI III VII", bars_per_chord: 2)`.

## Arrangement: a whole track (`whiplash_arrange`)

- `whiplash_arrange(preset: "short_demo")` turns the playing beat into a song from the next bar line: intro, build, drop, outro, about 75 s at the current tempo (`seconds: 90` for "a 90-second track"; it rounds to 4-bar phrases). `preset: "club"` is intro 16 / build 8 / drop 16 / break 8 / drop 16 / outro 16 bars (80 bars, about 2.5 minutes at 128 BPM).
- In both presets: the intro plays kick and hats; the build adds perc and the music tracks with a rising filter (`filter_freq` 20 → 127, exp curve) and the kick sits out its last bar; the drop plays everything; the break drops kick and bass; the outro thins to drums. Every section but the outro ends on a fill.
- **It stops by itself:** with `loop: false` (the default) the run stops cleanly on the bar line after the last section (note-offs, MIDI Stop). `loop: true` starts over from the first section. `clear: true` ends the arrangement and unmutes what it muted; the beat keeps playing. `whiplash_stop` ends everything.
- **Custom sections:** `sections: [{name, bars, tracks, mute, drop, fill, chords, bars_per_chord, ramps}]`, 1-16 sections of 1-64 bars.
  - `tracks`: what plays (everything else is muted by Whiplash, never with the unit's CC 94). Track numbers or groups: `all`, `drums`, `kick`, `hats` (closed, open, cymbal), `perc` (snare, rim, clap, perc), `bass`, `music` (pad, chord, stab, lead, fx, other), or any kit role. Or `mute`: what doesn't play. Groups resolve again at each section's first bar from the roles playing then, so the arrangement follows a switch or relabel.
  - `drop`: tracks that sit out the section's last bar. `fill: true`: a drum fill on its last bar.
  - `ramps: [{track, param, from, to, bars, curve}]` start on the section's first bar (default length: the section). Without `from` a ramp starts from the last value Whiplash sent; if there is none it is skipped (`skipped_ramps` in status). A ramp leaves the param where it ends, which changes the kit's sound until it is reloaded on the unit (the result's `filter_note`): tell the user.
  - `chords`: a progression in the key playing, from the section's first bar (`"i VI III VII"`, `bars_per_chord`); `"none"` ends it. Sections without `chords` keep the one playing.
- The result lists each section's `starts_at_bar`, `plays_now` (the groups resolved now), fills, drops, ramps and chords, plus `seconds` and when it `ends`. `whiplash_status.arrangement.current` gives the section playing, `bars_left`, `next` and `next_at_bar`. Read these back instead of guessing.
- Typical request, "make it a 90-second track: intro, build, drop, outro": `whiplash_play_pattern(genre: ...)` if nothing plays, then `whiplash_arrange(preset: "short_demo", seconds: 90)`. Transitions between sections (filter swap, riser) come in v0.6.2.

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

## Patterns, switching and live changes

- Genres: `deephouse` 122 BPM, `soul` 86, `techno` 130, `breaks` 132, `techhouse` 126 (four on the floor, offbeat open hat, shuffled 16th hats, rolling off-beat bass). "tech house", "tech-house" and similar spellings resolve to `techhouse`; an unknown genre's error lists the closest matches.
- Without labels a pattern assumes 1 kick, 2 rim/snare, 3 clap, 4 closed hat, 5 open hat, 6 bass, 7-8 chords or stabs, and marks those roles `(assumed)`. Ask what the tracks hold before calling a line "bass" or "chords".
- While a pattern plays, `whiplash_play_pattern` queues the new one for the next bar line without stopping the clock (`mode: "queued"`, `switch_at_bar`). Mutes, ramps, drops, transposes, written parts, the progression and the arrangement carry over; mutations reset (density, swing, humanize). `tracks` settings in a queued call land at the switch bar. A different `port` or `send_transport` restarts instead.
- A queued result's `tracks` describe the switch **as it will land**: its own slot, tune, transpose and mute are already in them (`setup_at_switch` marks those), and `muted_at_switch` lists the mutes after the switch. `muted_carried` is what is muted now.
- `whiplash_mutate`: `density` (tracks, amount -1..1 or thin/thicken), `fill` (drum fill on the next bar; shapes follow each track's role, so a kick labelled on track 9 gets the kick fill; with no `tracks` it fills every kick, snare/rim, clap and hat track playing; cymbal and perc tracks only fill when named; melodic tracks are refused), `swing` (50-80), `humanize` (0-1), `drop` (silence tracks for `bars`, then they return; `fill: true` adds a fill on the last dropped bar), `reset` (back to the pattern; written parts stay).
- `whiplash_ramp_param` sweeps on the clock; a new ramp on the same track and param replaces the old one, and `whiplash_stop` cancels all. Ramps on `amp_hold` stop at 126.
- Mutes reset on `whiplash_stop` or a fresh start, so mute after starting (or use `tracks: {"n": {"mute": true}}`).
- `whiplash_stop` silences everything and resets mutes, ramps, mutations, transposes, written parts and any queued switch. The kit map stays.
- With no Digitakt connected Whiplash plays into a virtual port named "Whiplash", which is silent. Results then carry a `warning`: tell the user. `whiplash_open_view` opens a read-only local visualiser if the user wants to watch.

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
| "Play a melody", "different notes" | `whiplash_write_part` with `notes` (and `key`, or `key: "current"`) |
| "In A minor", "change the chords", "i-VI-III-VII" | `key` on `whiplash_play_pattern`, then `whiplash_set_progression` |
| "Make it a whole track", "intro, build, drop", "90 seconds" | `whiplash_arrange` (`preset: "short_demo"`, `seconds`) |
| A track went quiet after labelling | `routing.vacated` (its part moved to a labelled track) or `replaced_by_written` |
| No fill on a moved drum part | label the track (fills follow roles), or name it in `tracks` |
| Chords sound like one note | expected on an audio track: use two or three chord tracks in `chords` mode |
| Drums you didn't ask for | the unit's own pattern: empty pattern or clock only |
| Wrong instrument on a track | ask the user, label it with `whiplash_label_tracks`, then `whiplash_select_sample` or `tracks: {"n": {"slot": ...}}` |
| Chords on a cymbal, bass on a hat | the pattern's assumed layout: label the tracks with `whiplash_label_tracks` |
| Many calls just to set the kit up | one `whiplash_play_pattern` with `tracks` |
| Silence everywhere | `warning` in a result: virtual port, no Digitakt connected |

## What Whiplash can never do

- Send SysEx, read sample names, or load files onto the unit.
- Switch sample banks (CC 24) or machines (Oneshot, Werp, ...).
- Write or save projects, patterns or kits.

## After a plugin update

The Hermes gateway keeps the old plugin code until it restarts, so run `hermes gateway restart`. A new chat is not enough.
