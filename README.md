# Whiplash 🥁

A [Hermes Agent](https://hermes-agent.nousresearch.com) plugin that lets your agent **jam live on an Elektron Digitakt II** over USB MIDI. Ask for "something groovy at 122", "slowly open the filter on the bass", "drop the kick for two bars with a fill", "switch to techno on the next bar", and Hermes plays it on the hardware: beats with MIDI clock and transport, routed onto what your tracks hold, bar-quantized pattern switches, named sound parameters, clock-synced sweeps, live fills, drops, density, swing and humanize, **written melodies and rhythms** ("four on the floor on the bass", "lock the bass to the kick", "play A, C, E, G on track 7"), **keys and chord progressions** ("techno in A minor, i-VI-III-VII, two bars each"), **whole tracks in sections** ("make it a 90-second track: intro, build, drop, outro"), switching a track to another sample already in the project, mutes, and tempo.

The timing lives in the plugin, not the model. Hermes makes one validated tool call ("ramp the cutoff over 8 bars"); Whiplash's sequencer does the musical part on its own MIDI clock, so sweeps stay smooth and switches land on the one however long the model takes to answer.

No Digitakt? Whiplash opens a virtual MIDI port named **Whiplash** so anyone can try it with a DAW or soft synth (macOS and Linux; Windows has no virtual MIDI ports).

## Tools

Every tool is prefixed `whiplash_` so it can't collide with another plugin's tools.

| Tool | What it does |
| --- | --- |
| `whiplash_list_midi_ports` | Lists MIDI ports and whether a Digitakt II is connected. |
| `whiplash_list_params` | The named Digitakt II parameters, grouped (track, src, filter, amp, fx, lfo), with CC, range, centre and aliases. |
| `whiplash_play_pattern` | Starts a beat by `genre` (`deephouse` 122 BPM, `soul` 86, `techno` 130, `breaks` 132, `techhouse` 126; "tech house" and similar spellings work too) or `mood` (groovy, chill, dark, energetic, funky, ...). Optional `bpm` (30-300), `bars` (1-512; omit to loop), `port`, `send_transport` (default `true`; `false` = clock only, see [Transport](#transport-and-the-units-own-pattern)), `key`/`scale` (`"Am"`, or `"F#"` + `"dorian"`: moves the bass, chords and stabs into that key; see [Keys and progressions](#keys-and-progressions)), `transpose` (`{"6": -12, "7": 5}`, semitones per track), and `tracks` to set the kit up in the same call: `{"6": {"slot": 9, "tune": 64, "transpose": 12, "mute": false}}`. Slot and tune CCs go out just before the first bar, or at the switch bar when queued; everything is validated first. While something plays, the new pattern is **queued and swaps in on the next bar line** without stopping the clock. Every result carries an `overlap_warning`, a per-track `tracks` summary with each line's `pitch` (see [Pitch](#pitch-and-register)) and the kit map's `routing`. A queued result's `tracks` already include its own `tracks` setup (`setup_at_switch`, `muted_at_switch`). A part routed onto tracks 9-16, or setup there, adds a `channel_note`. |
| `whiplash_set_param` | Instant sound change on one track: a named param (sent as CC, clamped into its range), a raw `cc`, or a raw `nrpn: [msb, lsb]`. `amp_hold` clamps to 0-126; HOLD = NOTE (CC 80 = 127) goes out only for `value: "note"` or exactly 127, and the result says `hold: "NOTE"`. |
| `whiplash_select_sample` | Switches which sample a track plays, by `slot` 0-127 among the samples **already loaded in the project's sample pool** (Sample Slot Select, CC 19). Same as `whiplash_set_param` with `param: "sample_slot"`. Whiplash can't list, preview or load samples; see [Sample select](#sample-select). |
| `whiplash_label_tracks` | Records what the user says each track holds (`tracks: {"7": "tuned cymbal", "5": "pad"}`, matched to a role vocabulary) and what sample slots hold (`slots: {"11": "warm synth"}`). Generated parts then follow the map from the next bar: a kick part goes to the track labelled kick, a cymbal track never gets chords. In memory only: it survives stop and switches; `reset: true` or a gateway restart clears it. See [Kit map](#kit-map). |
| `whiplash_transpose` | Moves one track's notes by `semitones` or `octaves` (±48 semitones) from the next bar line, keeping the line's intervals. Absolute (0 = back to the pattern). Works on any track that plays, including written parts on 9-16; on a track that plays nothing it is refused (it would do nothing). Carries across pattern switches; `whiplash_stop` resets it. Returns the new `pitch`. Needs a pattern playing. |
| `whiplash_write_part` | Writes one track's notes, melody or rhythm (tracks 1-16), replacing its generated line from the next bar line. Place hits with one of `rhythm` (`four_on_floor`, `on_kick`, `offbeat_8ths`, `8ths`, `16ths`, `off_16ths`, `syncopated`, `half_time`), `grid` (a 16-cell step mask per bar, `"x..x..x.x..x..x."`), `steps`, `hits` or `lock_to` (copy another track's hits now). `notes` cycle over the hits: Elektron names (`C5` = 60), MIDI numbers, `.` rests, or scale degrees with `key`/`scale`. `length` (16th steps, 0.25-16) is the exact note-off; `velocity`, `bars` (1, 2, 4). `envelope: "note"` also sends HOLD = NOTE (CC 80 = 127). `reset: true` goes back to the generated line. `key: "current"` uses the key playing. See [Written parts](#written-parts). |
| `whiplash_set_progression` | Loops a chord progression from the next bar line: `chords` as Roman numerals in the key (`"i VI III VII"`, `"ii7 V7 Imaj7"`) or names (`"Am F C G"`), `bars_per_chord` (1-16), `voicing` (`close` voice-led, `root`, `open`, `power`), optional `key`/`scale`. Chord, pad and stab tracks voice it, the bass plays the roots and leads snap to the scale; drum, cymbal and fx tracks are never changed. `tracks` overrides a mode (`chords`, `stack`, `root`, `snap`, `off`). `clear: true` ends it. See [Keys and progressions](#keys-and-progressions). |
| `whiplash_arrange` | Plays the beat as a song from the next bar line: `preset` `club` (intro 16 / build 8 / drop 16 / break 8 / drop 16 / outro 16) or `short_demo` (intro, build, drop, outro in about 75 s, or `seconds`), or your own `sections` (name, bars, which `tracks` play, ramps on the first bar, `fill` and `drop` on the last, `chords`). Stops cleanly after the last section unless `loop: true`; `clear: true` ends it. See [Arrangement](#arrangement). |
| `whiplash_ramp_param` | Sweeps a named param (or raw CC) `from` → `to` over `beats` or `bars`, advanced on the MIDI clock. `curve`: linear, exp, log. Returns a ramp id; `cancel: "<id>"` or `"all"`. Ramps on `amp_hold` (CC 80) stop at 126, so a ramp never switches HOLD to NOTE. |
| `whiplash_mutate` | Live edits to the running pattern: `density` (thin/thicken), `fill`, `swing`, `humanize`, `drop` (with auto-return), `reset`. `density`, `drop` and `fill` take tracks 1-16; `reset` keeps written parts. Fill shapes follow each track's role, so a kick labelled on track 9 gets the kick fill; with no tracks a fill plays on every kick, snare/rim, clap and hat track, and melodic tracks are refused. |
| `whiplash_mute_track` / `whiplash_unmute_track` | Live mute. `hardware: true` also flips the unit's own track mute (CC 94). |
| `whiplash_set_tempo` | Live tempo change (30-300 BPM); the clock follows so the Digitakt's delay/LFOs stay in sync. |
| `whiplash_stop` | Note-offs, All Notes Off on channels 1-8 plus any channel 9-16 that played a written part, transport Stop (skipped in clock-only mode). Resets mutes, ramps, mutations, transposes, written parts, the progression, the arrangement and any queued switch; keeps the kit map. Works as a panic button when nothing is playing. |
| `whiplash_status` | Port, `transport_mode` (`start_stop` or `clock_only`), pattern, BPM, bar, queued switch, mutes, active ramps with progress, mutations, `transpose`, whether output is the silent virtual fallback (and whether a Digitakt has appeared), and `last_error`. `key` and `progression` (the chord playing now and when it changes), `arrangement` (the section playing, bars left, the next one) and `routing`. `tracks` gives each track in use: role (the user's label, or the pattern's marked `(assumed)`), the last sample `slot` (with its `slot_label`) and `tune` Whiplash sent, `transpose`, `pitch`, mute state, `part` (`generated` or `written`) and last CCs; `parts` lists the written parts. |
| `whiplash_open_view` | Opens the **live visualiser**, a local web page (`http://127.0.0.1:7341`, or a free port) in the default browser. It shows the beat and the conversation while you keep chatting in the terminal. Optional `port`, and `open_browser: false` to only get the URL. Read-only. |
| `whiplash_close_view` | Stops the visualiser's local server. The beat keeps playing. |

Default track roles: 1 kick, 2 rim/snare, 3 clap, 4 closed hat, 5 open hat, 6 bass, 7 chords/chops/stabs, 8 chords, pad or perc depending on the genre. Whiplash can't see what the unit holds, so until the user labels the tracks, results mark the roles `(assumed)` and carry a `kit_note` telling the agent to ask.

### Kit map

Tell Hermes what your tracks hold ("track 7 is a cymbal, track 5 is a pad") and it calls `whiplash_label_tracks`. Each generated part then goes, in order:
1. to a track labelled with the same role,
2. else to one with a close role (rim and snare either way, chord to pad or stab, pad to chord, stab to lead or chord, lead to stab, open hat to cymbal),
3. else to its default track, if you haven't labelled that track as something else,
4. else it is dropped.

Labelled tracks that get no part stay silent until you write one. `routing` (in play, label and status results) lists where each part went.

- A track playing a written part is never a routing target. The generated part goes to the next track with a matching label, or `routing.replaced_by_written` says the written part plays instead. Nothing disappears silently.
- An unlabelled default track whose part moved to a labelled one plays nothing. For example, labelling 7 and 8 "tuned cymbal" moves the open hat from 5 to 7. `routing.vacated` and `vacated_note` report it.
- Relabelling while playing moves a part's transpose and density with it (`follows_part`). Labels live in memory for the session; nothing is written to disk or to the unit, and Whiplash still can't read sample names (that would need SysEx).

Tool descriptions are kept short so Hermes can act without describing every tool first. The detail lives in the bundled skill.

The plugin also ships a skill, **`whiplash:digitakt`** (`skills/digitakt/SKILL.md`), registered through Hermes' `ctx.register_skill` on builds that have it. It covers the kit map and one-call start, pitch and register, sample slots, note length versus AMP MODE/HOLD, the transport overlap, and a checklist for sounds that come out wrong. Tool descriptions point to it.

### Keys and progressions

- **Keys.** Every genre has a home key: deep house, soul and tech house in A minor, techno in F minor, breaks in G minor. `key` on `whiplash_play_pattern` moves the melodic tracks into another key degree by degree: the smallest tonic move (at most 6 semitones), then each scale degree onto the new scale's, so A minor to C major turns C into E. The native register is re-applied, and drums never move. The key sticks for later switches until `whiplash_stop`.
- **Progressions.** `whiplash_set_progression` starts on the next bar line and loops; each chord lasts `bars_per_chord` bars. Voicings stay near native pitch (median at or above note 53), and `close` voicings move as little as possible from chord to chord.
- **Who follows.** Each track's mode comes from its role, the kit-map label first:
  - chord, pad and stab tracks → `chords`,
  - bass → `root` (the chord root in the line's own register),
  - lead → `snap` (nearest scale note).

  Drum, hat, perc, cymbal and fx tracks are never changed, even when asked. Written parts play as written unless `tracks` names them. A labelled pad with no part of its own holds one chord tone per bar.
- **One note per track at a time.** The manual gives the Digitakt II 16 audio voices for 16 tracks and documents chords only for MIDI tracks ([reference](docs/digitakt-ii/reference.md) §6.4; manual p. 15, p. 17). So `chords` plays one chord tone per hit and gives each chord track a different tone; two or three chord tracks together sound the full chord. `stack` sends every tone at once, for a MIDI track or a polyphonic target. Whether an audio track layers stacked notes is an open hardware question.
- Nothing is sent when a key or progression is set: note numbers are rewritten at the bar line, in 16-84. No CC is sent, and the unit's own KB SCALE and ROOT NOTE are not touched.

### Arrangement

`whiplash_arrange` turns the playing beat into a track with sections. It schedules only what Whiplash already does on the bar line: mutes, drops, fills, ramps and a progression swap. The sequencer just checks once per bar whether a section starts there.

- **Presets.**
  - Intro: kick and hats.
  - Build: adds perc and the music tracks, with a low-pass filter rising from 20 to 127. The kick sits out its last bar.
  - Drop: everything.
  - Break: no kick or bass.
  - Outro: drums only.

  Every section but the outro ends on a fill. `club` runs 80 bars. `short_demo` runs about 75 s at the current tempo (`seconds` 30-600), in 4-bar phrases.
- **Sections.** `tracks` (or `mute`) take numbers or group words: `all`, `drums`, `kick`, `hats`, `perc`, `bass`, `music`, or any kit role. Each section resolves them again at its first bar, so an arrangement follows a pattern switch or a relabel.
- **Muting.** Mutes are Whiplash's own; the unit's CC 94 mute is never sent. The only CCs an arrangement sends are its ramps, and a ramp leaves its param where it ends until you reload the kit.
- **Ending.** With `loop: false` the run stops on the bar line after the last section, with note-offs and MIDI Stop. `whiplash_stop` or `clear: true` ends it early. DJ-style transitions between sections come in v0.6.2.

### Pitch and register

- **Note 60 is native pitch**, while TUNE is 64 and the preset's OCTAVE is unchanged ([reference](docs/digitakt-ii/reference.md) §6.1; manual p. 25, p. 38). Every semitone below 60 pitches the sample down, which slows and stretches it. Note names use Elektron's numbering, where 0 = C0 and 60 = C5.
- **Generated lines sit near native.** Each melodic part is lifted by whole octaves at load time until its median note is no more than 7 semitones below 60. The intervals are kept; only the register moves. So the techno bass plays at 53 (it was 41, 19 semitones down), the soul and breaks basslines move up an octave, and deep house is unchanged. Parts at or above native are left alone. Drum parts (note 60) are never moved.
- **Transpose** per track with `whiplash_transpose` or `transpose` on `whiplash_play_pattern`. It is applied to note numbers at the bar line and clamped to 16-84. The manual documents 16-84 as the chromatic range on the AUTO channel; the range on a track's own channel is undocumented, so Whiplash stays inside it.
- **`pitch`** in results, per melodic (or transposed, or tuned) track: `low`/`high` note numbers and names, `semitones_from_native`, `transpose`, `tune`, and `register_shift`. `semitones_from_native` includes `tune - 64` when Whiplash has sent `tune` (CC 16) on that track; `tune: null` means Whiplash hasn't sent it and the unit's value is unknown. Names use Elektron's octave numbering (C5 = 60; Logic calls 60 C3, General MIDI C4). Whiplash can't see the preset OCTAVE or an LFO on tune, so `pitch` assumes neither is in play.

### Written parts

- **Where and what.** `whiplash_write_part` takes one way to place hits and, optionally, the notes to play on them. Notes cycle over the hits; without `notes`, every hit plays note 60 (a drum or one-shot at its own pitch). `bars` defaults to the shortest of 1, 2 or 4 that plays every note at least once, and the part repeats across the 4-bar loop. Scale degrees use the major-scale convention for accidentals (`"1 3 5 b7"`), within the chosen `scale`. A key without an octave puts its root nearest note 60.
- **Timing.** The part replaces the track's line from the next bar line, like a density change. Mutes, drops, fills, density, humanize and transpose still apply to it. It carries across pattern switches and `whiplash_mutate reset`; `reset: true` or `whiplash_stop` returns the generated line.
- **`lock_to`** (and `rhythm: "on_kick"`, which is `lock_to: 1`) copies the source track's hits when you call it. Following the source live is not implemented yet.
- **Length.** A written note's `length` is its exact note-off (generated parts keep the 0.8 gate). If the same note retriggers before its note-off, the held note ends just before the new one, so a long note never cuts its own successor. The unit only shortens a sound on note-off when AMP MODE is ADSR or, in AHD, HOLD is NOTE ([reference](docs/digitakt-ii/reference.md) §5.2; manual p. 56), so every result carries `length_audible`. `envelope: "note"` sends exactly one CC 80 = 127 on that track, and only when asked; it changes the kit's sound until reloaded.
- **Tracks 9-16** play on channels 9-16. If the unit's AUTO CHANNEL or FX CONTROL CH sits on one of them, the notes and CCs reach that target too (reference §7.4); results on those tracks say so.
- **Validation.** Everything (track, placement, notes, lengths, velocities, bars, envelope) is checked before anything changes, so bad input never touches the beat or sends a CC.

### How live changes are timed

- **Pattern switches** land on the next bar line (`mode: "queued"`, `switch_at_bar`). No Stop/Start is sent, so the Digitakt's FX stay locked. A second call before the switch replaces the queued one. A `bpm` in that call applies at the switch; without one the new genre's tempo is used. `bars` counts from the switch. Passing a different `port` restarts on that port instead.
- **What carries across a switch:** mutes, running ramps, and scheduled drops/fills. **What resets:** density, swing and humanize (they were edits of the old pattern). `whiplash_stop` resets everything.
- **Ramps** advance one step per MIDI clock tick (24 per beat) in the sequencer thread, and send a CC only when the integer value changes. So a ramp over 8 bars takes 8 bars at any tempo, and a 0→127 sweep is at most 128 messages. Ramps on different track/param pairs run together; a new ramp on the same pair replaces the old one, and `whiplash_set_param` on that pair cancels it. `from` defaults to the last value Whiplash sent; if it has sent nothing for that param yet, `from` is required. Ramps need a pattern playing, because they are clocked by the sequencer. `exp` starts slow and finishes fast (cubic ease-in); `log` is the reverse.
- **Mutations** apply from the next bar (swing from the next step). `density` takes −1 (thinnest) … 0 (original) … +1 (busiest), or `thin` (−0.5) / `thicken` (+0.5). The amount is absolute, so repeating `thin` doesn't keep thinning. Thinning drops the weakest offbeat hits first, and thickening adds quiet ghost notes on empty 16ths in the bar's own notes. `fill` plays a one-bar fill on the next bar: the kick sits out the last beat, the snare rolls up, claps push, and hats ratchet in 32nds. `drop` silences tracks for N bars from the next bar, then brings them back by itself; `fill: true` adds a drum fill on the last dropped bar. `humanize` loosens velocity (±16 at 1.0) and timing (±¼ clock tick) per hit, never cumulatively, so the groove never drifts. All randomness is seeded, so the same calls give the same result.

## Live visualiser

Say *"launch the visualiser"*. Hermes calls `whiplash_open_view`, and a page opens in your default browser while the chat carries on in the terminal. It is drawn as a flat, grayscale pixel-art rack: a tape transport, a pulse hub, a master OUT with a VU needle, and one module per track patched into it with cables. The page only watches: it never sends MIDI and never changes the beat. It works before anything plays too, showing an idle state and the port status.

- **Tracks:** one module per track Whiplash is actually driving. That means the pattern's tracks, plus any channel it muted, dropped, filled, ramped or sent a CC to, so a channel touched only by CC still gets a module.
  - **Module:** a 16-step pixel strip with the playhead, a trig LED and note readout that fire on each hit, an LVL fader and FLT/RES/DEC knobs set to the last values Whiplash sent (`--` until it sends one), plus a fourth knob for any other param.
  - **States:** mutes (LED off, module dimmed, bat toggle down; `HW` for the unit's own mute), drops (dimmed with a `DROP <N` countdown), fills and density as tags. A drop or fill starting flashes the module inverted.
  - **Ramps:** a ramping knob turns in time toward a tick at the target value.
  - **Pitch:** the note range under the note readout (Elektron names, C5 = 60) includes the live transpose, and a `TRN +12` tag shows a transpose. Note names match what `whiplash_write_part` echoes.
  - **Written parts:** a `WR` tag, and the strip becomes a small piano roll: each note at its pitch, running for its length in steps. A `LEN` tag gives the length range. It is dashed when Whiplash has sent neither `amp_mode` 1 (ADSR) nor `amp_hold` 127 on that track, because the unit may then ignore note-off (reference §5.2). `HLD NOTE` or `ADSR`/`AHD` shows what Whiplash last sent for the envelope, not what the kit is set to.
  - **Kit map:** a track you labelled with `whiplash_label_tracks` shows your label as its role in white (assumed roles stay gray). The `SMP` tag carries the slot's label. A labelled track with no part routed to it still gets a module, tagged `NO PART` until you write one.
  - **Tracks 9-16:** they play written parts, or generated parts the kit map routed there, so they get their own row under 1-8 with a reminder to keep AUTO / FX CONTROL CH off those channels.
- **Key and chords (v0.6.0):** while a beat plays, a full-width **KEY** module shows the key it plays in (`SET` by `key` or a progression, else the pattern's `HOME` key) and a key queued for the next switch.
  - **Progression:** after `whiplash_set_progression`, one cell per chord with the numeral as you typed it (case kept: `i` minor, `VI` major), the chord name and its voiced notes. The chord playing is lit, with a square per bar of the chord; the next one is dashed and counts down four beats before the change. The highlight follows the playhead, so it moves on the bar line, not when the next frame arrives.
  - **Per track:** a track that follows the progression gets a chord line under its strip: its mode (`CHD` chords, `STK` stack, `ROOT` bass roots, `SNAP` lead) and the notes it plays in this chord, then in the next one. Drum, cymbal and fx modules never get one. The strip itself already shows each upcoming bar in its own chord.
- **Tape transport:** a bitmap BPM readout that rolls to a new tempo, REC LED, bar and 4-bar loop position, pattern and swing, a queued switch with a beat countdown, and the MIDI port. The virtual fallback shows as an inverted `VIRTUAL · SILENT`, and an unplugged device as a flashing `PORT LOST`.
- **Master VU:** the needle follows an envelope derived from the scheduled hits and track levels, labelled `MIDI FALLBACK · TRIG ENVELOPE · NOT REAL AUDIO`. The tape reels turn with the BPM and stop with the transport; the hub pulses on each kick and bar downbeat.
  - **Real audio:** click **CONNECT AUDIO** (or press `A`) and allow microphone access. The page picks the Digitakt II's USB audio input and turns off echo cancellation, noise suppression and auto-gain so the signal isn't altered. The needle then follows the input's RMS, labelled `AUDIO · <device>`.
  - **Per track:** the trig LEDs are always MIDI-derived, because the Digitakt's USB audio is only the stereo main mix.
- **Conversation:** your messages and Hermes's replies, streaming word by word.
  - **Tool calls:** hidden by default. Each reply has an `N tool calls` chip that expands, and `T` shows all of them.
  - **Layout:** in a window narrower than 1100 px (terminal beside it) the panel becomes lower-third captions.
  - **Linking:** a Whiplash tool call blinks the outline of the track module it touched.
- **Action log:** a one-line ticker of recent Whiplash tool calls along the bottom. Click it for the last 40.
- **Keys:**

  | Key | Action |
  | --- | --- |
  | `C` | collapse the conversation |
  | `T` | show tool calls |
  | `A` | connect audio |
  | `B` | blur the conversation (for screen recordings) |
  | `R` | patch cables on/off |
  | `F` | fullscreen |
  | `?` | help |

How it stays out of the way:
- **Off the clock thread.** The sequencer thread only stores its current step and the bar's notes in two attributes, with no lock and no I/O. A single `whiplash-view` thread builds a snapshot at most 10 times a second, and only while a browser is connected. That snapshot is a short copy under the same lock `whiplash_status` uses, and JSON encoding happens outside it. The browser interpolates the playhead between frames, so the plugin never pushes at frame rate.
- **Localhost only.** The server binds to `127.0.0.1` and answers only requests addressed to `127.0.0.1` or `localhost`, which blocks DNS rebinding. The page is one self-contained HTML file: no CDN, no fonts to fetch, no build step.
- **Conversation source.** Whiplash subscribes to Hermes's plugin hooks: `pre_llm_call`, `on_stream_start`/`on_stream_delta`/`on_stream_end`, `pre_tool_call`/`post_tool_call` and `post_llm_call`.
  - The callbacks copy text into a bounded in-memory buffer (60 turns) and return `None`. They never block, never raise and never write anything to disk.
  - Subagent sessions are ignored, so a delegated task doesn't take over the panel.
  - On a Hermes without `register_hook`, the view instead reads the newest session from `~/.hermes/state.db` (or `$HERMES_HOME/state.db`) once a second, through a read-only SQLite connection.
  - The page shows which source is in use (`· hooks` or `· state.db`).
- **Opening the browser** uses Python's `webbrowser` module on a short-lived daemon thread. On macOS that runs the system opener.

Without `whiplash_open_view`, nothing starts. The text/CLI session behaves exactly as before, apart from the in-memory hook buffer.

### Values

- Named params and raw `cc` take 0-127. Named params clamp into their own range (for example `tune` 4-124, `sample_start` 0-120) and say `clamped: true`; switches (`mute`, `play_mode`) reject out-of-range values instead.
- `nrpn` takes the full 14-bit value 0-16383, sent as data MSB = `value >> 7`, LSB = `value & 127`. To send a 7-bit amount `v` over NRPN, pass `v * 128`.
- Mutes reset on `whiplash_stop` and on a fresh start, so mute after starting a pattern. If Whiplash muted a track on the unit itself (CC 94), it unmutes it there on unmute, stop, and exit.
- Bad input never touches the beat: every tool validates its arguments before changing anything.

### Parameter map

38 per-track parameters sent as CC on the track's channel. Source: *Elektron Digitakt II User Manual*, Appendix B: MIDI (OS 1.15A, pp. 109-113; the OS 1.17 manual keeps the same values), cross-checked with [midi.guide](https://midi.guide/d/elektron/digitakt-ii/). The CC numbers agree between the two sources. The full CC/NRPN map, every discrepancy and how the unit treats incoming MIDI are in the device reference, [docs/digitakt-ii/reference.md](docs/digitakt-ii/reference.md).

| Group | Params (CC) |
| --- | --- |
| track | `mute` 94 (0/1), `track_level` 95 |
| src | `tune` 16 (4-124, centre 64), `play_mode` 17 (0-3), `sample_slot` 19 (0-127, see below), `sample_start` 20 (0-120), `sample_length` 21 (0-120), `loop_pos` 22 (0-120), `sample_level` 23 |
| filter | `filter_freq` 74, `filter_reso` 75, `filter_env_depth` 77 (centre 64), `filter_attack` 70, `filter_decay` 71, `filter_sustain` 72, `filter_release` 73, `filter_env_delay` 91, `filter_key_tracking` 92 (0-100) |
| amp | `amp_attack` 79, `amp_hold` 80 (0-126; `"note"` = 127 = NOTE), `amp_decay` 81, `amp_sustain` 82, `amp_release` 83, `amp_mode` 87 (0 AHD, 1 ADSR), `amp_volume` 89, `pan` 90 (centre 64) |
| fx | `delay_send` 84, `reverb_send` 85, `chorus_send` 12, `overdrive` 57, `bit_reduction` 54, `sample_rate_reduction` 55 |
| lfo | `lfo1_speed` 102, `lfo1_depth` 109, `lfo2_speed` 112, `lfo2_depth` 119, `lfo3_speed` 78, `lfo3_depth` 86 (all centre 64) |

Common aliases work (`cutoff`, `resonance`, `decay`, `volume`, `level`, `srr`, `reverb`, ...), and an unknown name gets close-match suggestions.

Some notes on the map:
- **Machine dependent.** `sample_start`, `sample_length` and `loop_pos` (SRC knobs E/F/G) are start/length/loop on Oneshot, and other things on other machines (for example Bars on Werp, Stretch and Repitch). `filter_reso` (knob F) is feedback on Comb and gain on EQ. The per-machine table is in [the reference](docs/digitakt-ii/reference.md#4-machines).
- **High-res LFOs.** The LFO params have an LSB CC (58-63). Whiplash sends the MSB only, as a plain 7-bit value.
- **CC only, never NRPN.** Several NRPN addresses disagree between the manual and midi.guide (mute 1:101 vs 1:108, track level 1:100 vs 1:110, filter env depth 1:23 vs 1:26, filter base/width 1:51/1:52 vs 1:24/1:25). Raw `nrpn` is still available on `whiplash_set_param`.
- **No machine switching.** Neither source documents a CC or NRPN for the SRC machine type (Oneshot, Werp, Stretch, ...); it is only reachable from the unit's MACHINE menu, so Whiplash can't change it.
- **Note length and the amp envelope.** A note-off only shortens a sound when the track's AMP MODE is ADSR (`amp_mode` 1, CC 87; manual B.5 p. 110, midi.guide "0: AHD; 1: ADSR") or, in AHD, when HOLD is NOTE (`amp_hold` 127, the midi.guide default; manual 11.7 p. 56: fixed hold values 0-126 ignore Note Off). Whiplash never changes the envelope mode on its own: `amp_hold` clamps and ramps within 0-126, and 127 is sent only when asked for by name (`"note"`, exactly 127, or `envelope: "note"`).
- **FX channel out of scope.** FX-channel and global params (delay time, reverb decay, ...) are not named params; raw `cc` can reach them.

### Sample select

`whiplash_select_sample` (or `whiplash_set_param` with `param: "sample_slot"`, aliases `sample`, `smp`, `slot`) sends **Sample Slot Select, CC 19**, on the track's channel, so Hermes can put, say, a pad on track 7 instead of a metallic one-shot.

- **Source.** Manual Appendix B, B.3 Source parameters (p. 109): Sample Slot Select CC 19, NRPN 1:8; Sample Bank Select CC 24, NRPN 1:9; repeated in B.9 Misc (p. 113). No CC LSB is listed. midi.guide agrees: CC 19 range 0-127, CC 24 range 0-7, and turning SMP on the unit sends only the slot within the selected bank.
- **What the slot means.** The value 0-127 is a slot within the sample bank currently selected on the unit. A project holds up to 1016 samples in its pool; the SMP list starts with OFF, which plays nothing. Neither source says whether CC value 0 lands on OFF or on the first sample, so try it.
- **What it can't do.** Whiplash can't list, preview or hear the samples, and can't load a file onto the unit. It only picks a slot in the pool that is already loaded. The agent or user has to know or try slot numbers. Reloading the pattern/kit on the unit restores its own sample; nothing is saved.
- **Still blocked:** sample bank select (CC 24, NRPN 1:9), the absolute "sample" NRPN 1:3, raw NRPN 1:8, and raw `cc: 19` (use the named param, which validates 0-127 and can't be ramped).

## Install

```bash
hermes plugins install hejijunhao/whiplash --ref <full 40-character commit SHA>
hermes plugins enable whiplash
hermes plugins list                          # whiplash -> enabled
```

Hermes installs the Python dependencies (`mido`, `python-rtmidi`) declared in `pyproject.toml` / `plugin.yaml`, after asking for consent. On Linux `python-rtmidi` also needs the ALSA runtime (`sudo apt install libasound2`; `libasound2t64` on newer Debian/Ubuntu).

For development, symlink a checkout instead and install the dependencies into the Python environment Hermes runs in:

```bash
git clone https://github.com/hejijunhao/whiplash ~/whiplash
ln -s ~/whiplash ~/.hermes/plugins/whiplash
```

Restart Hermes (`hermes`), then ask: *"Play some deep house on my Digitakt."*

Whiplash's `register()` only registers schemas, the bundled `whiplash:digitakt` skill and the visualiser's in-memory conversation hooks. The MIDI port, the sequencer thread and the view server open on first use, so loading stays well under Hermes' 10 s plugin-load limit.

## Updating

The Hermes CLI attaches to a background gateway, and the gateway loads plugins once for the whole process. A running gateway keeps the old Whiplash code after an update; a new chat is not enough. So after updating:

```bash
hermes plugins update whiplash      # or: git -C ~/whiplash pull, for a symlinked checkout
hermes gateway restart
```

Then check that `/plugins` lists whiplash and that `skills_list` shows `whiplash:digitakt`.

If Hermes earlier auto-created a local skill for Whiplash (for example `~/.hermes/skills/whiplash-digitakt/`), delete it. It may hold stale claims such as "can't switch samples". Plugin skills are namespaced and never replace local ones, so the old one keeps showing up until you remove it.

## Digitakt II setup

On the unit: **SETTINGS > MIDI CONFIG**
- **PORT CONFIG**: INPUT FROM = USB (or MIDI+USB). Turn **RECEIVE NOTES** and **RECEIVE CC/NRPN** on.
- **SYNC**: **CLOCK RECEIVE** and **TRANSPORT RECEIVE** on if the Digitakt's sequencer/FX should follow Whiplash.
- **CHANNELS**: TRACK 1-8 CHANNEL = 1-8 (the default). Keep **AUTO CHANNEL** and **FX CONTROL CH** off channels 1-8, and off any channel 9-16 you write parts on (or OFF). Otherwise Whiplash's notes and CCs also reach the active track or the send FX, because the same CC numbers mean different things there.

Notes trigger each track's sample. Note 60 is the original pitch (see [Pitch and register](#pitch-and-register)), as long as TUNE is centred and the preset's OCTAVE (FUNC+FLTR > TRACK) is unchanged. Note lengths only shape the sound when AMP HOLD is set to NOTE (the midi.guide default; a given preset may differ) or the AMP mode is ADSR. See [docs/digitakt-ii/reference.md](docs/digitakt-ii/reference.md) §5-§7 for the details.

### Transport and the unit's own pattern

By default Whiplash sends MIDI **Start**, clock, and **Stop**. With TRANSPORT RECEIVE on, Start also starts the Digitakt's **own sequencer**, so any trigs stored in the pattern selected on the unit play on top of Whiplash's notes, and Whiplash mutes can't silence them. **Select an empty pattern on the unit before you start** unless you want that layered.

Or use clock only: pass `send_transport: false` to `whiplash_play_pattern`, or set `WHIPLASH_SEND_TRANSPORT=0` in the environment Hermes runs in to make it the default. Whiplash then sends clock and notes but no Start, and never sends Stop either, so it can't halt a pattern someone runs on the unit. The unit's sequencer stays stopped; if you press Play on the unit, its pattern plays in sync with Whiplash. Changing `send_transport` while a beat plays restarts instead of queueing. Every `whiplash_play_pattern` result, start or queued switch, carries an `overlap_warning` for the current mode, and `whiplash_status` shows `transport_mode`.

### Connecting mid-session

If Hermes started before the Digitakt was plugged in, Whiplash plays into the silent virtual port and every result carries a `warning`. Once the unit shows up, results also carry `device_available` and a `notice` saying how to move over. Whiplash never switches on its own; Hermes calls `whiplash_play_pattern` with that `port`. If the unit is unplugged mid-beat, the sequencer stops, `whiplash_status` shows `port_lost` and `last_error`, and the next call re-detects the port. An explicitly chosen virtual port (`port: "Whiplash"`) only gets a plain `device_available` field.

## Safety and disclosures

- **Controls hardware.** Whiplash sends live MIDI to whatever port it opens: notes, clock, transport Start/Stop (unless clock only), and CC/NRPN parameter changes.
  - **Changes stick until you reload.** A parameter change is an edit to the active pattern's kit on the unit, just like turning a knob. It stays there, even across pattern switches, until you reload: `FUNC`+`NO` reloads the pattern, and `TRK`+`TRIG`+`NO` reloads one track's preset.
  - **Nothing is saved.** Whiplash never saves anything to the unit, and nothing reaches the saved project unless you save it.
- **Ships a read-only skill.** `skills/digitakt/SKILL.md` is registered with Hermes as `whiplash:digitakt`. It stays in the plugin directory and is not copied anywhere.
- **Never sends SysEx or program changes.** `Engine.send()` only allows note on/off, control change, clock, start/stop/continue. Anything else raises.
- **Can switch a track between samples already in the project, nothing more.** Sample Slot Select (CC 19) is sent only through `sample_slot` / `whiplash_select_sample`. It changes which already-loaded pool sample a track plays, until the pattern/kit is reloaded. Sample bank select (CC 24), the sample NRPNs (1:3, 1:8, 1:9), and the bank-select/NRPN-data CCs stay blocked. No SysEx, no file transfer onto the unit, no project, pattern or slot writes, no +Drive access, no program change.
- **Runs a background thread.** The sequencer runs as a daemon thread inside the Hermes process while a pattern plays, and is stopped by `whiplash_stop`. Port enumeration for the Digitakt check happens on tool calls only, at most every 2 s, never in the clock thread.
- **Cleans up on exit.** `whiplash_stop`, every sequencer exit, and a normal Hermes exit (via `atexit`) send note-offs, All Notes Off, and transport Stop, then close the port. A hard kill (`SIGKILL`, power loss) can't be intercepted; press Stop on the unit if that happens.
- **Visualiser (only when you open it).** `whiplash_open_view` starts a local HTTP server on `127.0.0.1` in two daemon threads (`whiplash-view-http`, `whiplash-view`) and opens the default browser through `webbrowser` on a daemon thread. On macOS that launches the system opener; it's the only process Whiplash ever starts. `whiplash_close_view` and Hermes exit (`atexit`) stop the server.
- **Reads the conversation.** In-memory observer hooks pass the conversation to the view; nothing is stored. Without hooks, the view reads `~/.hermes/state.db` read-only, and only while the page is open. The page puts the conversation on screen, so mind what's visible when recording. `B` blurs it.
- **Kit labels stay in memory.** `whiplash_label_tracks` keeps what you tell it in the Hermes process only. It writes no file and sends nothing to the unit.
- No shell, credentials, or secrets, and no network beyond the localhost page. The only environment variable read is the optional `WHIPLASH_SEND_TRANSPORT` (plus `HERMES_HOME` to find `state.db` in fallback mode).

## Tests

```bash
uv sync && uv run pytest -q          # or: pip install mido python-rtmidi pytest pyyaml && python -m pytest -q
```

542 tests, covering:
- manifest, catalog draft and dependency declarations
- the parameter map against the manual, plus aliases and clamping
- the device reference's named-param table against `ccmap.py`, so the docs can't drift
- clock-synced ramps: no duplicate sends, replace, cancel, concurrency
- bar-quantized switches: no Stop/Start, mutes and ramps carried
- every mutate action, including drop auto-return and seeded determinism
- hot-plug notices and the explicit-virtual case, rate limiting, port loss and reopen
- sample-slot select (lookup, send, reject, list) with bank select, sample NRPNs, SysEx and program change still blocked
- transport modes: Start/Stop by default, clock only (no Start, no Stop), env default, mode change restarts, overlap warning
- written parts: every placement (rhythm presets, grids, steps, hits, `lock_to`/`on_kick`), note names and scale degrees, notes cycling over hits, note-off at `length` x a sixteenth on the timeline, retriggers not cut short, bar landing, carrying over `mutate reset` and switches, `reset: true`, density/drop/fill/mute on a written part, tracks 9-16, bad input leaving the beat and port untouched, `envelope: "note"` sending exactly one CC 80 = 127, and clock jitter with 8 written parts
- the native register (no generated line far below note 60, whole-octave shifts, drums untouched), transpose on the wire (clamping, bar landing, carry over a switch, reset on stop), the `pitch` block with a sent tune, the per-track status block, `amp_mode`, and the bundled skill (registration, fallback without the API, frontmatter, no stale claims)
- v0.5.2: transpose on written parts on tracks 9-16 and refusal on silent tracks, All Notes Off on exactly the channels that played (1-8 always, 9-16 only after a note), and `amp_hold` never reaching HOLD = NOTE by clamp or ramp (named or raw CC 80) while `"note"` / 127 sends it with a label
- v0.6.0: keys (parsing, flat spelling, every genre's home key, `in_key` into five keys for every genre keeping rhythm, scale, register and drums, a session key across switches, reset on stop), chord parsing (numerals, accidentals, suffixes, names, dash splitting), voicings (exact chord tones, register, voice leading), progressions on the beat (next-bar start, chord changes every N bars, roots on the bass, one chord tone per hit spread across chord tracks, `stack`, snapping leads, drums untouched, kit-map roles, refusals on cymbal and drum tracks, pads with no line, written parts, carry across switches and reset, clear, transpose on top), the status block, bad input changing nothing, and clock jitter with stacked and spread chords
- v0.5.3: the kit map (role vocabulary, routing onto labelled tracks, fallbacks, no chords on cymbal/fx tracks, re-routing on the bar, lifetime across stop and switches, slot labels in results, bad labels changing nothing), per-track setup on `whiplash_play_pattern` (each CC once, before MIDI Start on a fresh start and at the switch bar when queued, a bad entry rejecting the whole call), the `techhouse` pattern and aliases, and a size budget on tool descriptions that keeps the safety caveats
- the v0.5.3 review follow-ups: a fill leaves a melodic line on tracks 1-5 alone (a bass routed onto track 2 never becomes a roll), and explicit kit roles accept `closed_hat`-style spelling
- v0.6.1:
  - arrangement: section bar lines, mutes only at boundaries, ramps on a section's first bar, fill and drop on its last, chord swaps, loop and clean stop, exact preset bar counts, `short_demo` length at every genre's tempo, status, clear and stop, bad input changing nothing, a real run that stops by itself, and clock jitter
  - fills by role (a kick labelled on track 9, default fill tracks, melodic refusals, cymbal and perc only when named, and the demo's drop with fill unchanged)
  - the review follow-ups: written parts in routing, transpose and density following a relabel, queued results with their own setup, the 9-16 channel note, `routing` on play results, and vacated default tracks
- input validation, single panic per stop, exit hook, SysEx refusal
- the offline demo rehearsal (`scripts/rehearse_demo.py`, below) at 4x clock: every Part A check passes, the MIDI file holds exactly what was sent, and its checks catch SysEx, program change, blocked CCs and hanging notes; with `--v06`, the progression beat (chord changes on the bar, roots on the bass, drums never transposed, nothing on cymbal or fx tracks) passes too, and its checks catch a chord tone on the cymbal or a change a bar early; with `--v061`, a 30-second `short_demo` (sections on their bar lines, only their own tracks, the stop by itself) and a fill on a kick labelled on track 9 pass, and its checks catch a muted track sounding or a note after the end
- clock timing (`scripts/clock_jitter.py`, [docs/testing/clock-jitter.md](docs/testing/clock-jitter.md)): lateness against the engine's own grid, a canary process that excuses machine stalls, a burst passing and a per-bar stall failing, and a busy Python thread in the process seen as lateness
- the visualiser:
  - the state snapshot and which lanes appear
  - written parts, transpose, the amp envelope, kit and slot labels and tracks 9-16 in the snapshot, and the page handling frames without them
  - the sequencer keeping exact time under a flood of snapshots
  - the key, progression, chord now and next change, and per-track chord lines; the strip's upcoming bars matching what the sequencer plays in each chord
  - a jsdom render of the page with real frames: chord cells, case-kept numerals, the highlight moving on the bar before a new frame arrives, chord lines, and no script errors (CI installs jsdom; locally it skips without it)
  - hooks that return `None` and never raise
  - streamed replies that arrive out of order
  - the read-only `state.db` fallback
  - server start/stop, the localhost Host check, SSE frames, and the open/close tools

One test does a real virtual-port loopback through rtmidi; it skips where the machine has no MIDI system. CI runs the suite on Linux and macOS (`.github/workflows/tests.yml`).

### Rehearse the demo offline

```bash
uv run python scripts/rehearse_demo.py             # real time, about 30 s
uv run python scripts/rehearse_demo.py --speed 4   # 4x clock, about 8 s (what CI runs)
uv run python scripts/rehearse_demo.py --v06       # plus the optional v0.6 progression encore
uv run python scripts/rehearse_demo.py --v061      # plus the optional v0.6.1 arrangement beat and fill
```

No Digitakt, no rtmidi and no MIDI system needed. It runs the tool calls behind the [hackathon demo](docs/demo/hackathon-demo.md) (hardware checklist Part A, A1-A9) through the real tool handlers and engine, with the beat running between calls and each call landing mid-bar. Output goes to a recording port named like the unit. It writes to `<tmp>/whiplash-rehearsal/` (or `--out DIR`):
- `demo.mid`: everything sent, one track per MIDI channel, with markers for each step, MIDI Start/Stop and every bar. An SMF can't hold real-time bytes, so the clock is kept as timing: events sit at the engine's own musical time and the file plays back at the speed of the demo.
- `report.txt`: per step, the calls, which tracks sounded, the CCs sent, where each change landed against the bar line, warnings and the checks. Then global checks: no SysEx or program change, no blocked CC, no hanging notes, and clock timing. Each tick's real-time lateness is measured against the engine's own grid. Ticks more than 4 ms late form a stall, which counts unless a separate canary process saw the machine stall at the same moment. A segment may have one such stall plus one per 10 s ([docs/testing/clock-jitter.md](docs/testing/clock-jitter.md)).
- `results.json`: every tool result, as Hermes would see it.

`--v06` (off by default, so the default run stays the demo) adds the demo's optional encore after Part A: deep house in A minor, i-VI-III-VII, two bars per chord, pads (the synth, slot 11) on track 7. It checks that the progression starts on the next bar, every chord change lands exactly on a bar line, every pad note is a tone of that bar's chord, the bass plays the roots, drums and the tuned cymbal stay on note 60, the fx track gets nothing, and the visualiser's frame shows the key and the chords.

`--v061` (off by default) adds two runs.
- **The demo's optional arrangement beat:** *"Play techno, and make it a 30-second track"*, using `whiplash_arrange` `short_demo`. The checks:
  - each section starts on its bar line and sounds only its own tracks,
  - the kick sits out the build's last bar,
  - status names the section,
  - and the run stops by itself on the bar line after the outro, with MIDI Stop and no hanging notes.
- **A kick labelled on track 9 and a fill** (checklist R2): the kick plays only on track 9 and sits out the fill bar's last beat.

### Measure clock timing on this machine

```bash
uv run python scripts/clock_jitter.py --runs 3          # 1x, 30 s each
uv run python scripts/clock_jitter.py --load 8 --calls  # with busy cores and tool calls every 0.25 s
```

It reports how late each MIDI clock went out against its slot (p50, p95, p99, max), stalls over 4 ms, and whether a canary process saw the machine stall then. Options add busy processes, tool calls, a busy Python thread in the process (`--gil-hog`) or full garbage collections of a large heap (`--gc-heap`). CI prints it on every runner. Method, numbers and the verdict on the old macOS flake: [docs/testing/clock-jitter.md](docs/testing/clock-jitter.md). It measures the computer, not the unit.

It exits 1 on any violation and 2 if the run crashed. `--speed` scales the engine's clock, not the order or bar timing of the calls. A pass says the plugin does what the demo needs; it says nothing about the unit. That still takes Part A on a real Digitakt II.

All of this runs against fake or virtual ports. Behaviour on a real Digitakt II is not covered by the test suite; the ordered hardware session for that, with a 10-minute smoke test first, is [docs/testing/hardware-checklist.md](docs/testing/hardware-checklist.md).

## 90-second demo: a build and drop

Digitakt II on screen, USB to the laptop, Hermes in a terminal beside it. Each line is what you type.

For a live audience, use the 3-minute stage script instead: [docs/demo/hackathon-demo.md](docs/demo/hackathon-demo.md). It adds the kit map, one-call start, a written melody and tech house, plus fallback prompts and recovery. It follows the hardware checklist's smoke test, so run that on the unit first.

| Time | Prompt | What happens |
| --- | --- | --- |
| 0:00 | *"Is my Digitakt connected? And launch the visualiser."* | `whiplash_list_midi_ports` finds *Elektron Digitakt II*, `whiplash_open_view` opens the page beside the terminal (click CONNECT AUDIO once for a real VU level). |
| 0:04 | *(On the unit: select an empty pattern so its own trigs don't layer in.)* | |
| 0:08 | *"Play some groovy deep house."* | `whiplash_play_pattern deephouse`: kick, rim, hats, bass and chords at 122 BPM, 55 % swing. |
| 0:18 | *"Close the filter on the bass, then open it slowly over 8 bars."* | `whiplash_set_param` track 6 `filter_freq` 20, then `whiplash_ramp_param` 20→110 over 8 bars, `curve: exp`. |
| 0:30 | *"Thicken the hats."* | `whiplash_mutate density` track 4 `thicken`: ghost 16ths from the next bar. |
| 0:40 | *"Drop the kick and bass for two bars with a fill."* | `whiplash_mutate drop` tracks 1 and 6, 2 bars, `fill: true`: the beat breathes, the snare rolls up, and kick and bass slam back on the one. |
| 0:55 | *"Switch to techno on the next bar."* | `whiplash_play_pattern techno`: queued, lands on the bar at 130 BPM with no Stop/Start. Mutes and running ramps carry over; the thickened hats reset with the new pattern. |
| 1:05 | *"Loosen it up and throw some reverb on the clap."* | `whiplash_mutate humanize` 0.4, then `whiplash_ramp_param` track 3 `reverb_send` 0→100 over 2 beats, `curve: log`. |
| 1:15 | *"What's playing?"* | `whiplash_status`: techno, bar, active ramps with progress. |
| 1:22 | *"Stop."* | `whiplash_stop`: clean stop, no hanging notes. |

See [CHANGELOG.md](CHANGELOG.md) for what changed between versions, [docs/digitakt-ii/reference.md](docs/digitakt-ii/reference.md) for how the Digitakt II works (with manual page references), and [docs/](docs/) for the draft Hermes plugin catalog entry and PR text.

## License

MIT
