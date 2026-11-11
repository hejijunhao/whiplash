# Whiplash roadmap: v0.6 and beyond

Status: **brainstorm for Phil's review**, except where a version below says otherwise. **v0.6.0 (keys, scales, chord progressions) is implemented** in PR "Whiplash v0.6.0: keys, scales, chord progressions (+ v0.6 plan)", **v0.6.1 (arrangement, fills that follow the kit map)** in PR "Whiplash v0.6.1: arrangement + follow-ups", and **v0.6.2 (transitions, mix levels)** in PR "Whiplash v0.6.2: transitions + mix levels"; the v0.6 split into PRs is in [v06-build-plan.md](v06-build-plan.md). **v0.7.0 (audio capture, `whiplash_listen`, safety rails)** is implemented in PR "Whiplash v0.7.0: listening loop (capture + listen + safety rails)"; the v0.7 split is in [v07-build-plan.md](v07-build-plan.md). It builds on [v05-build-plan.md](v05-build-plan.md), which covers native-pitch register, transpose, `whiplash_write_part`, rhythm presets, the bundled skill, kit labels, a one-call start-and-configure, a `techhouse` genre, and pause and resume.

**How the versions are ordered:**

- **Each version is one demo.** It has a single sentence you can say on camera, and that sentence is its goal.
- **Each version depends only on earlier ones.**
- **Clock-safe throughout:**
  - every musical change lands on a bar or step from the sequencer clock
  - the sequencer thread never enumerates ports and never takes the transport lock
- **Needs Phil's explicit OK:**
  - SysEx
  - project, pattern or slot writes
  - file writes outside the plugin
  - new heavy dependencies

The sizes are rough: S is under half a day, M is about a day, and L is 2-4 days.

## Overview

| Version | Goal (the demo sentence) | Headline features | Size |
| --- | --- | --- | --- |
| **v0.5** | "Hermes writes a melody on my bass sample, in the right register." | See the v0.5 plan | ~1.5 days |
| **v0.6** | "Hermes plays a whole track: intro, build, drop, outro, in key." | Keys, scales and chord progressions; song arrangement; DJ-style transitions; mix levels | L |
| **v0.7** | "Hermes listens to what the Digitakt actually sounds like and fixes it." | Listening loop over USB audio; automatic kit scan; loudness and kick checks; safety rails | L |
| **v0.8** | "I play the Digitakt, Hermes plays along, and it keeps a record." | MIDI input from the unit; jam call and response; session recording and export as MIDI | M-L |
| **v0.9** | "One agent, a whole studio: Digitakt, Sub 37 and Take 5 in sync." | Multiple MIDI destinations; per-device param maps; clock master | L |
| later | Performance polish | Visualiser evolution, latency work, more genres, macros, saved sessions | ongoing |

---

## v0.6: song structure, in key

**Status:** split into three PRs ([v06-build-plan.md](v06-build-plan.md)).
- **v0.6.0** (feature 1: keys, scales, progressions) is implemented.
- **v0.6.1** (feature 2: arrangement, plus fills that follow the kit map) is implemented.
- **v0.6.2** (features 3 and 4: transitions and mix levels) is implemented. With it every v0.6 feature except more genres (5) is built.
- None of v0.6 has been tested on hardware yet.

**Goal:** go from a looping beat to a short arranged track that follows a key and a chord progression.

**Features:**

1. **Key, scale and progressions** (M). **Implemented in v0.6.0.** Chord tracks play one chord tone per hit by default, because an audio track probably plays one voice ([reference](../digitakt-ii/reference.md) §6.4).
   - `key` and `scale` on `whiplash_play_pattern` and `whiplash_write_part`, so notes can be given as scale degrees.
   - `whiplash_set_progression(chords: ["i", "VI", "III", "VII"], bars_per_chord, voicing)`. Chord tracks voice the progression; bass and lead parts follow the root, or snap to the scale.
   - It is bar-quantized and keeps to the native register from v0.5.
   - (Phil hasn't greenlit chord work for v0.5. This is where it would go.)
2. **Arrangement** (M-L). **Implemented in v0.6.1** as `whiplash_arrange`, with presets `club` and `short_demo`, group words for tracks, and a clean stop after the last section. Sections take a `transition` and a `mix` since v0.6.2.
   - `whiplash_arrange(sections: [{name: "intro", bars: 8, tracks: [1, 4], ...}, {name: "build", bars: 8, ramps: [...]}, {name: "drop", bars: 16}, ...])`.
   - A section is a set of active tracks, mutations, ramps and fills, scheduled on bar lines. That is mostly scheduling of existing primitives: queued switch, drop, fill, ramp.
   - Presets: `club` (intro 16 / build 8 / drop 16 / break 8 / drop 16 / outro 16) and `short demo` (60-90 s).
   - Status shows the current section, the bars left, and the next section.
3. **DJ-style transitions** (M). **Implemented in v0.6.2:** `cut`, `filter_swap` (low-pass closes on everything but kick and bass, then reopens after the switch), `drop_swap` and `riser`, on a queued switch or between sections.
   - `transition: "cut" | "filter_swap" | "drop_swap" | "riser"` on a queued switch.
   - For example, `filter_swap` ramps a high-pass on the outgoing tracks over N bars, then switches on the one.
   - These are built from existing ramps, drops and fills, so no new clock paths.
4. **Mixing** (S). **Implemented in v0.6.2** as `whiplash_mix`, with genre presets, group words, pan words, ramps over bars, and snapshots that sections recall.
   - `whiplash_mix(levels: {"1": 110, "6": 95}, pan: {...})` sends CC 95 (track level) and CC 90 (pan) in one call.
   - It adds named mix snapshots ("drop mix", "break mix") that sections can recall.
   - CCs are as in Appendix B, B.1 and B.5, pp. 109-110.
5. **More genres** (S each): minimal (125), more breaks variants, and dub techno.
   - Each is checked against the v0.5 register rule.

**Dependencies:**

- v0.5 `write_part`, register and transpose
- v0.5 kit map, so sections know which track is which

**Phil's hardware test checklist (v0.6):**

| Prompt in Hermes | Listen or look for on the Digitakt |
| --- | --- |
| "Play techno in F minor, chords i–VI–III–VII, two bars each." | Chord track changes every 2 bars, on the one. Bass follows the roots. Nothing out of key against a held note in KB mode. |
| "Make it a 90-second track: intro, build, drop, outro." | Tracks enter in sections. The build has a rising filter or riser. The drop lands on a bar line. The outro thins out and stops cleanly. Status shows the section names. |
| "Switch to breaks with a filter swap over 4 bars." | The outgoing pattern's high end closes over 4 bars, and breaks lands on the one with no stop/start click. |
| "Bring the bass down a bit and pan the hats left." | Track 6's level drops (watch the unit's LEVEL). Hats move left. Nothing else changes. |
| "Save this as the drop mix, then go back to it after the break." | Levels snap back exactly at the drop. |

---

## v0.7: the listening loop

**Status:** split into two PRs ([v07-build-plan.md](v07-build-plan.md)).
- **v0.7.0** (features 1, 2 and 4: capture, `whiplash_listen`, safety rails) is implemented. Route (a) was chosen on Phil's behalf, reversibly: `sounddevice` + `numpy` as an optional `[listen]` extra, lazily imported. Route (b) stays a later option.
- **v0.7.1** (feature 3: `whiplash_scan_kit`, labels proposed, never applied) is implemented in PR "Whiplash v0.7.1: kit scan (labels proposed, never applied)".
- None of v0.7 has been tested on hardware yet.

**Goal:** Hermes hears the unit's real output and reasons about it. This also gives the automatic kit scan queued in v0.5 (item 12).

**Features:**

1. **Audio capture** (M).
   - The source is the Digitakt II's class-compliant USB audio. The unit needs USB CONFIG = USB AUDIO/MIDI (manual 14.8.1, p. 83), and USB OUT routes MAIN or single tracks (14.6.4, p. 81).
   - **Two routes, Phil to choose:**
     - (a) a Python capture dependency (`sounddevice` with PortAudio, and `numpy`), which needs macOS microphone permission for Hermes
     - (b) the visualiser page's browser capture, posting features to the local view server
   - Analysis runs off the sequencer thread, always.
2. **`whiplash_listen(bars=2)`** (M) returns compact features, never raw audio, to the agent:
   - LUFS-ish loudness and peak/clipping
   - spectral balance (low, low-mid, mid, high)
   - onset times against the grid, and detected kick positions with their offset from Whiplash's kick
   - whether a track seems silent
   - "Bass is masking the kick" or "it's clipping" become things Hermes can actually observe.
3. **`whiplash_scan_kit`** (M).
   - With transport stopped (or clock only), it solo-triggers tracks 1-16 one at a time and captures each.
   - It classifies by centroid, decay, pitchedness and low-end energy, and proposes kit-map labels.
   - The user confirms the labels; they are never applied silently.
4. **Listening-aware safety rails** (S).
   - Hard caps on CC flood rate and on simultaneous ramps.
   - A loudness guard: refuse a level or overdrive change if `listen` shows clipping, unless the user insists.
   - `whiplash_panic` stays available. "Unexpected drums detected while Whiplash's tracks are muted" points to the unit's own pattern, the v0.4 overlap.

**Dependencies:**

- v0.5 kit map, which the scan fills
- the visualiser, if route (b)
- **Phil's OK** on the dependency and permission route

**Phil's hardware test checklist (v0.7):** set USB CONFIG to USB AUDIO/MIDI first.

| Prompt | Listen or look for |
| --- | --- |
| "Scan my kit." | Each track sounds once, alone, in order. The proposed labels match what you hear (kick, hat, pad...). Nothing plays from the unit's own pattern. |
| "Does the bass clash with the kick?" | Hermes answers with numbers (low-band overlap, kick offset), then proposes something like a filter or a ducking ramp. The result is audibly cleaner. |
| "It's too loud, fix it without killing the vibe." | Levels come down by a few steps. There is no hard cut, and `listen` shows no clipping afterwards. |
| "Is it in time?" | Reported kick offsets of a few ms. Deliberately set swing to 70 and confirm Hermes notices. |
| Unplug USB audio mid-listen | `listen` errors cleanly, and the beat keeps playing. |

---

## v0.8: playing with Phil

**Goal:** Whiplash reacts to what Phil does on the unit, and every jam can be kept.

**Features:**

1. **MIDI input from the unit** (M).
   - Open the Digitakt's MIDI input lazily, on a daemon reader thread that never blocks the sequencer.
   - The unit sends CC/NRPN when knobs turn, and notes from the pads or KB mode, if its MIDI CONFIG > PORT CONFIG send settings are on. The manual describes this in 14.4 MIDI CONFIG (pp. 77-79); confirm the exact menu names on the unit.
   - `whiplash_status` shows the "last user moves" (for example "you opened track 6's filter to 90").
   - Whiplash's own ramps yield when Phil grabs the same knob: the ramp is cancelled and Hermes is told.
2. **Call and response** (M).
   - `whiplash_follow(track, mode: "echo" | "answer" | "harmonize")`.
   - Phil plays a phrase on a track in KB mode; on the next bar, Hermes answers on another track: a transposed echo, a reply in the same key, or a third above.
   - Notes stay quantized to the grid.
3. **Session recording and MIDI export** (S-M).
   - The engine records everything it sends and receives with clock-tick timestamps: notes, CCs, sections.
   - `whiplash_export(name)` writes a standard MIDI file through `mido.MidiFile`, one track per channel, with tempo changes.
   - **Phil's OK needed:** this writes a file, for example under `~/.hermes/whiplash/sessions/`, and changes the disclosures.
4. **Undo** (S): `whiplash_undo` reverts the last part, mix or arrangement change on the next bar.

**Dependencies:**

- v0.6 keys, for answering in key
- the v0.5 kit map
- Phil's OK on file writes

**Phil's hardware test checklist (v0.8):** turn on the unit's CC/note send over USB.

| Prompt or action | Listen or look for |
| --- | --- |
| While Hermes ramps track 6's filter, grab the filter knob. | The ramp stops immediately, your knob wins, and Hermes says it yielded. |
| "Answer whatever I play on track 7, on track 8." Then play 4 notes in KB mode. | On the next bar, track 8 plays a reply in key, in time, in the native register. |
| "What did I just change?" | Hermes lists your knob moves with track and param names. |
| "Export this session." | A `.mid` file appears. Importing it into a DAW shows tracks 1-8 with your notes and Hermes' parts at the right tempo. |
| "Undo that." | The last change reverts on the next bar line. |

---

## v0.9: multi-device studio

**Goal:** Whiplash drives the Digitakt plus the Moog Sub 37 and the Sequential Take 5, all on one clock.

**Features:**

1. **Multiple destinations** (M-L).
   - A device registry: port, MIDI channel(s), role, and whether the device receives clock and transport.
   - Parts target `device:channel` as well as a Digitakt track.
   - One clock master: Whiplash sends clock to each device that wants it, from the same tick, with no per-device threads.
2. **Per-device parameter maps** (M each).
   - `ccmap` becomes one map per device. Sub 37 and Take 5 CC tables come from their own manuals, with the same sourcing rule as the Digitakt: cite the page, and send a CC only when the sources agree.
   - Program change and SysEx stay blocked on every device, because a patch dump or overwrite is worse on a synth than on a drum machine.
   - Mono and poly limits: the Sub 37 is mono or duophonic, the Take 5 has 5 voices. Parts are checked against them, and `write_part` voices chords to fit.
3. **Devices in the agent's view** (S): status and the skill list each connected device, its role and its param names.

**Dependencies:**

- v0.6 progressions, so the synths get chords and bass in key
- v0.8 input, optional, to follow a synth's own keyboard
- Phil confirming the exact models and connections (USB or DIN through an interface)

**Phil's hardware test checklist (v0.9):**

| Prompt | Listen or look for |
| --- | --- |
| "Put the bassline on the Sub 37, keep drums on the Digitakt." | The Sub 37 plays the line in time. The Digitakt track 6 goes quiet. No drift after 5 minutes. |
| "Pads on the Take 5, i–VI–III–VII." | Take 5 chords of 5 voices or fewer, changing on the bar. No preset change on the synth. |
| "Open the Sub 37 filter over 8 bars." | A smooth sweep on the Sub 37 only, with no stepping (or stepping as expected for 7-bit). |
| Power off the Take 5 mid-jam | Whiplash reports a lost port for that device only; the others keep playing. |

---

## Later themes

- **Visualiser evolution:**
  - pixel-art rack restyle (grayscale modules, knobs, patch cables, tape transport, trig-driven VU): see [viz-style-brief.md](viz-style-brief.md), from Phil's 11 Nov 2026 inspiration; PR "Whiplash visualiser: pixel-art rack restyle"
  - section timeline for v0.6
  - live spectrum from the listening loop in v0.7
  - user-move markers in v0.8
  - one lane per device in v0.9
  - an "explain what you just did" overlay
- **Latency:**
  - measure round trips per turn on the Air
  - tool-description budget (started in v0.5)
  - the skill as the single reference
  - combined calls such as `play + configure + arrange`
  - a status digest that tells the agent everything in one call
- **Macros and performance moves:** "build-up", "breakdown" and "slam" as one-call presets on top of ramps, drops and fills.
- **Saved sessions:** a kit map plus mix plus arrangement, per project name (needs Phil's OK for file writes).
- **More genres:** minimal, garage/2-step, jungle, ambient, hip-hop variants, each with native-register lines.
- **Safety rails:**
  - a "what will this send" dry-run mode
  - a per-session CC budget
  - an allow-list per device
  - a big red "hands off" mode where Whiplash stops all sends but keeps the clock
  - SysEx stays off unless Phil explicitly says otherwise, with a separate audit if it is ever considered (sample names, for example)

## Cross-cutting rules (every version)

- Digitakt claims cite the OS manual (page) or midi.guide. Anything unverified is a hardware check on Phil's Air.
- No SysEx, no project, pattern or slot writes, and never touch Digitakt slots 1-3.
- Clock-safe, bar-quantized changes; tests with fake and virtual ports for every feature, and a jitter check when the sequencer changes.
- `feat/*` branch, a PR per version, merge commits only, and Phil merges.
