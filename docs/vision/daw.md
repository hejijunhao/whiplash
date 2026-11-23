# Whiplash DAW: vision

Status: **vision draft, updated 2026-11-23 with Phil's answers to the open questions.** Nothing of the app is built, and the build starts only on Phil's explicit go-ahead. Facts are cited inline and were checked on 2026-11-21 or 2026-11-23. Anything marked **UNVERIFIED** wasn't confirmed from a primary source, and **[inferred]** marks our own reasoning. **Nothing in this doc is hardware-verified.** §13 holds the decisions and the questions still open.

**Copyright:** Kamino Research Corporation (legal entity: Bradgate Capital Management Pte Ltd, Singapore), the same owner as Riddim. **Licence:** AGPL-3.0, with a CLA for outside contributions from day one (§1.1).

**Repo:** the app lives in **[kaminocorp/whiplash-daw](https://github.com/kaminocorp/whiplash-daw)** (Phil, 23 Nov). This doc was drafted in hejijunhao/whiplash (PR #35), which is the Hermes plugin.

**Framing and updates from Phil:**
- **21 Nov: a new project** that keeps only the name *Whiplash*. It is not the Hermes plugin and not the Digitakt web twin (hejijunhao/whiplash#34). Digitakt II support is out of scope.
- **21 Nov, 8:14 SGT: core DAW first.** The baseline is an **Ableton/Logic hybrid**. Agent control is a later phase (§10). It doesn't drive the scope, the stack or the phasing.
- **21 Nov, 8:24 SGT: the engine is a separate repo,** **[kaminocorp/riddim](https://github.com/kaminocorp/riddim)** ("Riddim", our own audio engine in Rust, public since 2026-11-21). This doc covers the **app**. §9 says what the app needs from Riddim.
- **21 Nov, ~16:50 SGT, decisions:**
  - Tauri 2 with WebGPU;
  - macOS first, Windows later, Linux a by-product;
  - Kamino owns the copyright;
  - Phil's rig is a Mac Mini M4 Pro, and Helix is not owned.
- **23 Nov: answers to all 13 open questions** (§13), applied throughout:
  - a smaller, high-quality v1, with no advanced editing in the GUI apart from the piano roll (below);
  - open source under AGPL-3.0 with a CLA;
  - macOS 15+, with a WebGL2 fallback;
  - the 2i2 is 1st gen;
  - the UI is built as a web app first, then wrapped in Tauri;
  - the installed plugins are the test set, with no purchases.
- **23 Nov, later decisions:**
  - **v1 includes a piano roll** for instrument tracks (§4.3);
  - **Apple Silicon only:** arm64, macOS 15+, with no Intel build and no universal binary (§8.4);
  - **one fixed BPM and time signature per project,** with no tempo map or tempo changes (§3, §5.1).

  Riddim details are aligned with its [`docs/api/embedding.md`](https://github.com/kaminocorp/riddim/blob/main/docs/api/embedding.md) and its vision's §1.1 ([riddim.md](https://github.com/kaminocorp/riddim/blob/main/docs/visions/riddim.md)), as of `main` at `e4bbf49`.

---

## 1. What it is, and what it isn't

**It is:**
- **Our own desktop DAW, open source and public,** with Riddim underneath.
  - It ships on **macOS 15 Sequoia and later, Apple Silicon only** (arm64). There is no Intel build.
  - **Windows comes later** from the same code (§8.4).
  - In look and workflow it's an Ableton Live and Logic Pro hybrid: a Logic-style arrange window and mixer, with Ableton's speed and device chain.
- **Small and high quality in v1** (§3):
  - record;
  - an arrange timeline with basic edits;
  - a piano roll for instrument tracks;
  - a mixer;
  - AU and VST3 plugins;
  - export.

  It does those few things very well. Beyond the piano roll, **sophisticated editing is left to agents later** (§10), so the GUI gets no other advanced editing controls.
- **Built for Phil first** to record and finish music with the plugins he already has installed.

**It isn't:**
- **A toy or a demo.** It has to record a real session with real plugins without losing a take.
- **A browser app.** The UI is a web app, developed in Chrome and shipped inside Tauri 2 (§8). Audio, plugins and files live in native code: the Rust core and Riddim. Browsers can't host AU or VST3 plugins, so there is no pure in-browser build.
- **A Logic or Ableton replacement in breadth.** v1 has none of these:
  - an audio editor;
  - automation lanes;
  - tempo changes or a tempo map;
  - session view;
  - comping, time-stretch, notation, video or surround.

  Some come later (§11), and some come through agents (§10).
- **An AAX host.**

**Who it's for:** Phil first, on a **Mac Mini with an M4 Pro** and a **Focusrite Scarlett 2i2 (1st generation)**. After that, anyone: the project is public, and old interfaces like Phil's are supported deliberately (§9.2).

### 1.1 Ownership, licence and contributions

- **Owner:** Kamino Research Corporation (legal entity: Bradgate Capital Management Pte Ltd, Singapore), which Phil wholly owns. Riddim has the same owner (Riddim [D79](https://github.com/kaminocorp/riddim/blob/main/docs/decisions.md)).
- **Licence: AGPL-3.0, like Riddim, for now** (Phil, 23 Nov). Riddim is AGPL-3.0-only ([COPYRIGHT](https://github.com/kaminocorp/riddim/blob/main/COPYRIGHT)). Because the owner is the same, Whiplash can link the engine on any terms ([embedding.md](https://github.com/kaminocorp/riddim/blob/main/docs/api/embedding.md), "Licence").
- **Kamino keeps the right to relicense,** so **a CLA is required for outside contributions from day one.** Riddim's model is the starting point:
  - a licence grant to the owner, not an assignment, with the right to license on other terms;
  - a DCO sign-off on every commit;
  - the maintainer reviews every change.

  Riddim's [`CONTRIBUTING.md`](https://github.com/kaminocorp/riddim/blob/main/CONTRIBUTING.md) and [`CLA.md`](https://github.com/kaminocorp/riddim/blob/main/CLA.md) are the model. Riddim's CLA is "a plain-language draft that no lawyer has read" (Riddim D81). Whiplash's should be reviewed by counsel before the first outside contribution (Q-N3).
- **Files to add in whiplash-daw when the code starts:** `LICENSE` (the AGPL text), `COPYRIGHT`, `CONTRIBUTING.md` and `CLA.md`. They are not part of this docs-only change.

---

## 2. Architecture at a glance

```
┌──────────────── UI: a web app (TypeScript) ──────────────────────────────────────┐
│  arrange · mixer · browser · inspector · transport                               │
│  drawing: WebGPU when navigator.gpu exists, WebGL2 otherwise                      │
│  one EngineLink interface ─┬─ development: WebSocket to the dev host (Chrome)     │
│                            └─ product:     Tauri IPC (Tauri 2 web view)           │
└──────────────── JSON commands ↓  ·  ↑ JSON events ───────────────────────────────┘
┌──────────────── Whiplash core (Rust crate, shared) ──────────────────────────────┐
│  command API (record, edit, CRUD) · undo stack · project folder & file           │
│  media pool & waveform overviews · plugin-editor windows · main-thread pump      │
│  hosted by: whiplash-dev-host (localhost WebSocket)  or  the Tauri 2 shell       │
└──────────────── riddim crate, in process ────────────────────────────────────────┘
┌──────────────── Riddim (kaminocorp/riddim, Rust) ────────────────────────────────┐
│  engine model (tracks, clips, routing, automation, tempo map, plugin slots)      │
│  ops with inverses · devices · real-time graph · PDC · recording                  │
│  AU/VST3/CLAP hosting · scan · offline render                                     │
└──────────────────────────────────────────────────────────────────────────────────┘
```

**The boundary, as Riddim defines it** (vision §1.1): "Riddim owns everything that has to be correct in time (samples, latency, plugin lifetimes, files being written). Whiplash owns everything about intent and presentation."
- **Riddim owns the engine model** and the **edit ops**, which it validates and applies atomically and which each return their **inverse**.
- **Whiplash owns:**
  - the project folder and file format;
  - the media pool and waveform overviews;
  - the UI state;
  - the **undo stack**, built from Riddim's inverses;
  - the **command API**.

**The command API is the centre of the app** (Phil, 23 Nov, Q6). Every action is a typed command in the Rust core: record, transport, clip and track create/read/update/delete, edits, mixer changes, plugins. The UI uses only that API. An agent layer later uses the same one (§10). That's why it's built now, whatever the agent UI turns out to be.

---

## 3. Core functionality (v1)

**v1 is smaller but high quality** (Phil, 23 Nov, Q1): record, an arrange timeline with basic edits, a mixer, AU/VST3 hosting and export.
- **Plus a piano roll** for instrument tracks (Phil, 23 Nov, later decision).
- Apart from that, the GUI gets **no advanced editing controls**.

| Area | v1 scope | Not in v1 |
|---|---|---|
| **Recording** | Mono and stereo audio from the interface's inputs. MIDI from a controller into an instrument. Input monitoring. Arm several tracks at once. Latency-corrected placement. Every take kept | Loop and punch takes, comping (Riddim already supports loop and punch, so they're a cheap v1.x) |
| **Tracks** | Audio and instrument tracks, plus buses and master | Folders, track stacks, multi-out instrument channels |
| **Arrange timeline** | Tracks and clips on bars and beats. Grid and snap. Zoom and scroll. Loop range. **One BPM and time signature per project**, fixed for the whole song and editable in the project settings (§5.1) | Tempo changes and a tempo map, markers and sections, session view (Q10) |
| **Basic edits** | On audio and MIDI clips: **move, cut, copy, paste, trim, fades**. Also select, delete, duplicate, split at the playhead, clip gain | An audio editor, time-stretch, humanise. Agents handle these later (§10) |
| **Piano roll** (instrument tracks) | Draw or place, move, resize and delete notes. Note velocity. Quantise (§4.3) | CC and pitch-bend editing, scale tools, step sequencer |
| **Mixer** | Channel strips: inserts (AU/VST3), sends, buses, master, volume, pan, mute, solo, record arm, input monitor. Peak meters | Sidechain, automation lanes, RMS and true peak |
| **Plugins** | AU and VST3 instruments and effects. Scan, a plugin manager, native editor windows, state saved with the project (§6) | CLAP in the UI (Riddim hosts it), plugin MIDI out routing, multi-out |
| **Transport** | Play, stop, record, loop, metronome with count-in, follow playhead. Shows the project's BPM | Punch in/out, tap tempo |
| **Export** | Offline bounce of the master to WAV (and AIFF). Progress and cancel | Stems, real-time bounce |
| **Project** | Save, load, autosave, crash recovery. A self-contained project folder (§5) | |
| **Undo** | Unlimited, one history for every edit (§5.3) | |

---

## 4. Look, workflow and mixer

### 4.1 What comes from where

| From **Ableton Live** (12.4.16 current; Live 13 announced for early 2027, [ableton.com](https://www.ableton.com/shop/live-13)) | From **Logic Pro** (13.0, [Apple](https://support.apple.com/en-us/109503)) |
|---|---|
| **Speed:** single window, few modal dialogs, keyboard-first, drag-and-drop everywhere | **The arrange window** as the main canvas ([Tracks area](https://support.apple.com/guide/logicpro/tracks-area-overview-lgcpf7c0d5d8/mac)) |
| **The device chain:** a horizontal strip of devices along the bottom ([Live manual](https://www.ableton.com/en/live-manual/12/working-with-instruments-and-effects/)) | **The mixer:** a full console with sends and buses ([Mixer](https://support.apple.com/guide/logicpro/mixing-overview-lgcpbc219818/mac)) |
| **The browser:** one searchable place for instruments, plugins, presets and samples | **The inspector** with the selected track's channel strip |

### 4.2 Main window

```
┌──────┬──────────────────────────────────────────────────────────────┬────────────┐
│ ◀ ▶ ● ⟲  │ 1.3.2 │ 120.00 │ 4/4 │ ⧗ count │ CPU ▮▮▯ │ DISK ▮▯ │ 2i2 48k/128        │
├──────┼──────────────────────────────────────────────────────────────┼────────────┤
│ INSP │  ruler                                                         │ BROWSER    │
│      │  ─────────────────────────────────────────────────────────── │ instr      │
│ chan │  01 Keys   LABS ▸ [MIDI clip───────][MIDI clip──]            │ plugins    │
│ strip│  02 Synth  INSTRUMENT [MIDI clip─────]                        │ presets    │
│      │  03 Gtr    ● TH-U ~~~audio~~~~~~~~~                           │ samples    │
│      │  04 Vox    ● ~~~~~audio~~~~~                                  │ files      │
│      │  Bus A · Master                                               │            │
├──────┴──────────────────────────────────────────────────────────────┴────────────┤
│ DETAIL (Tab): device chain ▸ [AirEQ][VMR][VerbSuite send]  or  piano roll         │
└───────────────────────────────────────────────────────────────────────────────────┘
   X = full-screen mixer (Logic-style console)
```

- **Centre: the arrange window.** Tracks run top to bottom and time left to right. Waveforms are drawn from overviews the Rust core precomputes (§5.2), at any zoom and without stalls.
- **Bottom: the detail pane.** The selected track's device chain, or the **piano roll** for the selected MIDI clip (double-click a clip, or press Tab to toggle), as in Ableton's Detail View and Logic's docked editor.
- **Left: the inspector.** The selected track's channel strip.
- **Right: the browser** for plugins, presets, samples and project files. Drag an item onto a track, or onto the empty area to create one.

### 4.3 Editing in v1

- **In the arrange view: clip-level edits.** Move, cut, copy, paste, trim, fades, plus select, delete, duplicate, split and clip gain. Edits snap to the grid, and holding a modifier turns snapping off.
- **In the piano roll: note editing for instrument tracks** (Phil, 23 Nov: a must for v1, like Ableton's or Logic's):
  - **Draw or place** notes with the pencil, or by double-clicking in the note grid. A new note takes the last-used length and velocity.
  - **Move** notes in time and pitch, snapping to the grid (a modifier turns snapping off). Alt-drag copies.
  - **Resize** a note from either edge.
  - **Delete** notes (key or click).
  - **Velocity:**
    - a velocity lane under the note grid, with drag-to-set on one or several notes;
    - note colour shows velocity.
  - **Quantise** the selected notes, or the whole clip, to the grid. **[proposal]** With strength (0-100 %) and a choice of starts only or starts and ends, as in Logic and Live.
  - **The basics around it:**
    - a piano keyboard down the side, where clicking a key plays the note;
    - selection by click, shift and marquee;
    - cut, copy, paste and duplicate notes;
    - nudge and transpose with the arrow keys;
    - the grid size;
    - zoom and scroll;
    - looping playback of the clip;
    - undo, as everywhere.
- **What the piano roll needs, and what it doesn't:**
  - **It needs to play a note when you place it or click a key**, so you hear what you're editing. Riddim already has this: `Engine::play_note(track, body)` "plays a note or controller into a track's instrument, as an on-screen keyboard would" ([engine.rs](https://github.com/kaminocorp/riddim/blob/main/crates/riddim-engine/src/engine.rs)). Note edits are ordinary model ops, and Riddim's note model carries velocity (`riddim-model`, `Note`).
  - **It doesn't need automation lanes or an audio editor.** Both stay out of v1.
  - **CC and pitch-bend data** recorded from a controller is kept and played back, but isn't editable in v1. A CC lane is the first thing to add if that hurts (§11).
- **Everything else in editing** (humanise, audio surgery, arrangement rewrites) comes through agents on the command API (§10), and doesn't get GUI controls.

### 4.4 Mixer UI

- **A full-screen console** (`X`) with strips for audio and instrument tracks, buses and master, in track order.
- **Each strip:** input, inserts (drag to reorder, alt-drag to copy), sends with levels, output, pan, fader, peak meter, mute, solo, record and monitor.
- **Meters:**
  - Riddim sends per-strip peaks in a `meters` event about thirty times a second ([events.md](https://github.com/kaminocorp/riddim/blob/main/docs/api/events.md)).
  - The UI smooths them, holds the peaks and draws them.
  - The UI never computes audio.

### 4.5 Look and feel (Phil, 23 Nov, Q9)

**A hybrid look, dark-led, ultra-minimal and premium, that feels Apple-made.**
- **Dark-led:** the dark theme is the primary one, and the app is designed in it first. **[inferred]** "Hybrid" leaves room for a light theme later.
- **Ultra-minimal:**
  - few controls on screen, with more appearing on hover or selection;
  - no chrome for its own sake;
  - colour only where it means something: track colour, meters, record state.
- **Premium and Apple-made:**
  - system font (SF Pro) with tabular numerals for time and values;
  - precise spacing;
  - restrained motion;
  - native macOS menus (Tauri has a menu API) and macOS keyboard conventions;
  - smooth scrolling and zoom.
- **No purple gradients, glassmorphism, sparkle icons or generic AI styling.**
- **Plugin windows look like their vendors made them.** We frame them and never skin them.
- **Readable across a room:** large transport numerals and a clear record state.

### 4.6 Key commands (Phil, 23 Nov, Q7)

- **Two shortcut presets, Logic and Ableton,** chosen in Preferences.
- **[inferred]** Both map onto the same command API (§2), so a preset is a keymap file and adding one is cheap.
- **Where the two clash** or have no equivalent, the preset falls back to a shared default set.

---

## 5. Project model

### 5.1 Structure

**Riddim's engine model** (`riddim-model`, typed, serialisable and versioned):
- tracks, clips, routing (buses, sends, inserts), automation curves;
- timing in Riddim's integer time (beat ticks and superclock, `riddim-time`). Riddim's model has a tempo and meter map, and **Whiplash uses it with exactly one entry** (below);
- plugin slots with opaque state blobs.

**Whiplash's additions** (vision §1.1 lists them as the app's):
- the media pool;
- UI state: zoom, selection, track colours, window layout and plugin-window positions;
- browser favourites;
- **each plugin's chosen format** (§6.3).

**Objects are addressed by Riddim's IDs**, so ops, undo and events refer to objects, never to list positions.

**Tempo and time signature (Phil, 23 Nov):**
- **No tempo map and no tempo changes.** Each project has **one user-defined BPM and one time signature**, fixed for the whole song.
- **They're editable per project,** in the project settings and the transport display. A new project starts at 120 BPM in 4/4, or a preference.
- Editing the BPM is one undoable command that replaces the single tempo entry.
- **[inferred] What a BPM edit does:**
  - clips are placed in beats, so they keep their bar positions;
  - MIDI follows the new tempo;
  - audio isn't time-stretched (that's not in v1), so recorded audio drifts against the grid if the BPM changes after recording. The app warns before applying the change to a project that has audio clips.
- **Imported MIDI files with tempo changes** (Riddim's importer reads a tempo map, `riddim/src/import.rs`) keep their notes. The app offers to adopt the file's first tempo, and ignores the later changes.

### 5.2 Files

- **A project folder:** the project file, `Audio/` (recordings and imports, copied in), `Overviews/` (waveform peak files) and `Autosave/`. Plugin state travels inside the model as opaque blobs. Whether large blobs move to side files is **to confirm** with Riddim.
- **The project file:** a versioned JSON document. Riddim's model is its core (`Model::to_json`, versioned by the model's `schema` number and covered by Riddim's [stability policy](https://github.com/kaminocorp/riddim/blob/main/docs/api/stability.md)). Whiplash's own sections wrap it, under Whiplash's own version number.
- **Media:**
  - imports are copied in by default;
  - missing media shows as offline (Riddim sends `media_missing` and plays those clips as silence);
  - missing plugins show as placeholders that keep their state and never drop it.
- **Autosave** every few seconds to `Autosave/`. Crash recovery offers the newest autosave.
- **Recording:** Riddim writes recordings incrementally as ordinary WAVs. `recording_finished` names the media entry, so a crash loses at most the last flush.
- **Waveform overviews** are the app's work: the Rust core computes them (embedding.md).

### 5.3 Commands and undo

- **Every user action is a typed command** in the core's command API (§2), whether it comes from a menu, a shortcut, a drag or (later) an agent. A command is one or more Riddim **ops**.
- **The core sends the ops through `engine.apply_wait(ops)`.** Riddim validates them, applies them atomically, and replies with `Applied { revision, inverses }` or `Rejected { index, error }`. A rejected batch leaves the model unchanged, so bad input never changes what's playing.
- **The undo stack** is a list of inverse batches, one per user command, with labels. Gestures such as a fader drag merge into one step.
- **Edits the engine makes itself** (a finished recording) arrive as `model_changed` with their inverses, and go on the same stack.
- **Determinism:** the same command on the same model gives the same result. Anything randomised takes a recorded seed.

---

## 6. Third-party plugins (AU and VST3 are a hard requirement)

### 6.1 The test set: what's installed on Phil's Mac (Phil, 23 Nov, Q13)

**No plugin purchases.** Testing uses what Phil already has installed. The earlier targets (Kontakt with Noire, Superior Drummer 3, EZbass, Helix) are **not required**, and their "done when" criteria are gone (§11).

| Installed (per Phil) | What it exercises **[inferred]** |
|---|---|
| **Slate Digital:** Virtual Mix Rack, FG-X, VerbSuite, Virtual Tape Machines | Effect inserts and sends, a reverb on a bus, mastering on the master bus, account-based licensing in a host |
| **Kilohearts** (which products: **to list**) | Effects; a modular host plugin if Snap Heap/Multipass is installed |
| **Eiosis AirEQ** | A large, resizable editor; an EQ on inserts |
| **Overloud TH-U** | An amp sim on a recorded guitar: latency and low-latency monitoring |
| **LANDR** (which plugins: **to list**) | Depends on the plugins |
| **Splice INSTRUMENT** | An instrument on an instrument track; online sample-library content |
| **LABS** | An instrument that streams samples from disk; slow loads |

**Not checked:** each plugin's formats, versions, whether it is native on Apple Silicon (the app hosts arm64 plugins only, §8.4), and licensing behaviour. The app's first scan on Phil's Mac produces that list. It also shows which plugins ship both AU and VST3, which matters for §6.3.

**What a host needs from these** (all within v1's scope):
- instruments and effects in AU and VST3;
- state that survives save and reload;
- latency reporting and PDC;
- slow loads that never stall audio or the UI;
- resizable editors;
- vendor licensing that the host stays out of: no blocking of first-run dialogs or network access, and no killing a slow load.

**Later targets, not owned:** Kontakt 8 Player with Noire, Superior Drummer 3, EZbass and Helix Stadium Native. Earlier research on them (21 Nov) found these needs:
- multi-output instruments: SD3 has 16 stereo outs ([Toontrack](https://www.toontrack.com/product/superior-drummer-3/));
- plugin MIDI out and OS file drags from plugin windows ([SD3 notes](https://www.toontrack.com/release-notes/superior-drummer-3/));
- sidechain ([Line 6 KB](https://kb.line6.com/helix-stadium-native-faq));
- very large memory use: 3.7-18 GB per SD3 preset ([Toontrack FAQ](https://www.toontrack.com/faq/how-much-ram-does-a-superior-library-or-sdx-use/)).

These are v1.x features (§11), and they get tested when someone owns the plugins.

### 6.2 Who does what (v1)

| Need | App | Riddim (§9.2) |
|---|---|---|
| **Scan** | Plugin manager with progress, failures, a blocklist and rescan | Out-of-process scan with a cache |
| **Load and state** | Progress UI, so the project stays usable while a plugin loads | Loads one plugin per main-thread pump, so audio keeps running (Riddim D50). Runs a plugin's first block off the audio thread (D84). Gets and sets opaque state |
| **Editors** | One native window per editor, framed, with position remembered | `open_editor(ParentWindow::AppKit(ns_view))` and `plugin_editor_resize` |
| **Latency** | Shows each strip's latency, with a low-latency monitoring toggle for armed tracks | Reports latency and compensates (PDC) |
| **Host playhead** | The project's single BPM and time signature (§5.1) | Supplies tempo, time signature, position and transport to plugins |

### 6.3 Format policy (Phil, 23 Nov, Q8)

- **VST3 is the default** when a plugin ships both formats.
- **AU is available on macOS,** with a preference: "Prefer AU when a plugin ships both".
- **Never mix formats of one plugin in a project:**
  - the first time a plugin is used in a project, its format is fixed for that project and stored in the project (§5.1);
  - every later instance of that plugin uses the same format, whatever the preference says;
  - changing the preference affects new projects only;
  - **[proposal]** changing a project's format for a plugin is an explicit command, because the state may not carry across formats. Show a warning, and keep the old state in case the change is reverted.
- **[inferred]** The plugin manager groups a plugin's AU and VST3 under one entry, so the format choice stays out of the way.

### 6.4 Plugin windows

- **Plugin editors are native windows, never web content** (embedding.md).
  - The Rust core makes one native window per editor, on the main thread. Riddim puts the editor into it.
  - Our frame adds a title, bypass, preset menu, A/B and a latency readout.
  - Windows float and remember their position per instance.
  - Riddim's CLI already does this, and its editor-window code can be reused (embedding.md).
- **The same in both hosts:** the dev host (§8) and the Tauri shell are both native Rust processes, so editor windows behave identically in Chrome development and in the shipped app. **[inferred]** In Chrome mode the editor windows belong to the dev host's process, not the browser's, so they won't stack with Chrome's windows the way they will with the Tauri window.
- **Missing or crashed plugins:** an offline placeholder that keeps its state. A crash shows clearly, and the app recovers from autosave. Riddim's opt-in out-of-process hosting has no editor yet (embedding.md).

---

## 7. Workflow details that make or break it

- **Never block the UI:** loading a project, a plugin, a scan, a bounce. Everything slow shows progress and can be cancelled.
- **Recording must feel safe:**
  - a clear arm and record state;
  - input meters before you press record;
  - the disk space left;
  - every take kept.
- **Keyboard-first:** every common action has a shortcut in both presets (§4.6).
- **Snapping and zoom:** smooth, fast, and predictable to the sample.
- **Low-latency monitoring** while recording: high-latency plugins are bypassed or flagged on armed tracks.

---

## 8. UI stack and how it's built

**Decided** (Phil, 21 Nov; Riddim D83): **[Tauri](https://github.com/tauri-apps/tauri) 2** (MIT/Apache-2.0; `tauri-v2.12.7`, 2026-11-18, [releases](https://github.com/tauri-apps/tauri/releases)):
- a Rust core linking Riddim in process;
- a TypeScript web UI;
- WebGPU for waveforms and meters.

**How we get there fastest** (Phil, 23 Nov, Q12):
1. **Build the UI as a plain web app** against the local Riddim engine, developed in Chrome.
2. **Then wrap it in Tauri 2.**

**No pure in-browser build:** browsers can't host AU or VST3, so Riddim is always running natively underneath.

### 8.1 The pieces

| Piece | What it is |
|---|---|
| **`whiplash-core`** (Rust crate) | The command API, undo stack, project I/O, media pool, waveform overviews, plugin-editor windows and the Riddim main-thread pump. Links `riddim` in process. Shared by both hosts |
| **`whiplash-dev-host`** (Rust binary, development) | Runs `whiplash-core` on its main thread. Serves the UI's JSON commands and events over a **localhost WebSocket**, and the UI's files over HTTP. Chrome talks to it |
| **The Tauri shell** (product) | Runs `whiplash-core` in a Tauri 2 app. Commands arrive as Tauri commands, and events go out through `emit` or a `tauri::ipc::Channel` |
| **The web UI** (TypeScript) | All views. Talks to the core only through an `EngineLink` interface with two implementations, WebSocket and Tauri IPC. **The JSON is the same over both** |

The names are proposals. The point is that the same core and the same UI run in both modes, and only the transport differs.

**Dev host safety [proposal]:**
- binds `127.0.0.1` only;
- checks the `Origin` header against an allow-list;
- requires a random token per launch, passed in the URL fragment.

These follow the same pattern as the Digitakt web app's local bridge (hejijunhao/whiplash#34). The dev host is a development tool and isn't shipped in v1. **[inferred]** It's also a natural base for the agent API later (§10).

### 8.2 Threads (from Riddim's embedding guide)

| Part | Lives on | Does |
|---|---|---|
| **`Engine`** | shared state behind a `Mutex` (`tauri::State` in the shell) | Commands and queries. Its methods are quick and never wait on audio |
| **`MainThread`** (`Engine::take_main_thread`) | **the host's main thread, for good**, never in shared state | Holds plugin instances. On macOS, plugins, their editors and Audio Units must be created and called on the main thread. `pump()` runs a few dozen times a second from the run loop. The exact Tauri hook is **unbuilt design** |
| **Event forwarder** | its own thread | Drains `Engine::subscribe()` and sends events to the UI (WebSocket or Tauri), so a slow UI never backs up into the engine |
| **Core workers** | worker threads | Project load and save, autosave, media import, waveform overviews |

- **Quit order:** drop the `Engine`, keep pumping until `pump()` returns `false`, then drop the `MainThread`.
- **Never hold the engine lock across a wait** ([embedding.md](https://github.com/kaminocorp/riddim/blob/main/docs/api/embedding.md)).
- "No Tauri application has been built or run against the engine" (embedding.md). The dev host is the first real host.

### 8.3 Drawing: WebGPU when available, WebGL2 otherwise (Phil, 23 Nov, Q4)

- **Use WebGPU whenever `navigator.gpu` exists:** in Chrome during development, and in WKWebView on **macOS 26+**. WebGPU "is supported and enabled by default" in WebKit only from macOS Tahoe 26 ([gpuweb implementation status](https://github.com/gpuweb/gpuweb/wiki/Implementation-Status)).
  - Whether WKWebView exposes `navigator.gpu` on macOS 26 is **UNVERIFIED**. An Apple forum reply suggests it does once the feature is on by default ([Apple forums](https://developer.apple.com/forums/thread/770862)), and one WebKit bug reports it missing in Safari 26.x ([WebKit 301627](https://bugs.webkit.org/show_bug.cgi?id=301627)).
- **Use WebGL2 on macOS 15**, where WKWebView has no WebGPU.
- **[proposal] Keep the drawing layer small:** timeline clips, waveforms, the piano roll's note grid and velocity lane, meters and the playhead, behind one renderer interface with two back ends. Panels, the inspector and dialogs are DOM.
- **[proposal] Make the fallback testable in Chrome:** the UI can be forced onto WebGL2 there (a debug switch). CI and a regular manual pass also run the UI in Safari or WKWebView, because Chrome isn't the shipping engine.
- **Windows (later):** in 2023 Tauri's WebView2 didn't expose WebGPU ([tauri#6381](https://github.com/tauri-apps/tauri/issues/6381)). Current behaviour is **UNVERIFIED**. The WebGL2 path covers it either way.

### 8.4 Platforms (Phil, 21 and 23 Nov)

**macOS 15 Sequoia minimum, Apple Silicon only (arm64).** No Intel build and no universal binary (Phil, 23 Nov, later decision, replacing the earlier universal-binary answer).

How others draw the line (checked 2026-11-23). On the floor we're close to Cubase 16. On the CPU we follow Logic: Apple Silicon only.

| DAW | Minimum macOS | Intel Macs |
|---|---|---|
| **Logic Pro 13** | "requires macOS 26.1 or later and a Mac with Apple silicon" ([Apple, 2026-11-18](https://support.apple.com/en-us/125029)) | no |
| **Cubase 16** (released 2026-11-04) | macOS 15 Sequoia, 26 Tahoe, 27 ([Best Service listing](https://www.bestservice.com/en/cubase_pro.html); Steinberg's own page not reached) | yes: "Intel Core i5 (2018 or later) or Apple silicon" |
| **Cubase 15** | Sonoma 14, Sequoia 15, Tahoe 26 ([macOS Audio](https://www.macosaudio.com/2025/11/cubase-15-unlocks-new-features-and-workflows/), from Steinberg's announcement) | yes |
| **Ableton Live 13** (announced, early 2027) | "MacOS 14.8.9 Sonoma or later" ([Ableton](https://www.ableton.com/shop/live-13)) | yes: "Intel® Core™ i5 processor or Apple Silicon" |
| **Bitwig Studio 6** | macOS 12 or later ([Bitwig](https://www.bitwig.com/en/bitwig-studio/tech-specs.html), [6.1 notes](https://downloads.bitwig.com/6.1/Release-Notes-6.1.html)) | yes, Intel with AVX2 |
| **FL Studio** (26.1.5) | macOS 10.15.7 or newer ([Image-Line](https://www.image-line.com/fl-studio/download)) | yes |
| **REAPER** (7.86) | "macOS 10.5* to macOS 26"; a "Universal for Intel and ARM64" build ([REAPER](https://www.reaper.fm/download.php)) | yes |

**Note on Phil's Cubase citation:** it's Cubase **16** that starts at macOS 15. Cubase 15 also supports Sonoma 14.

**What the decision means:**
- **One build target: `aarch64-apple-darwin`.** This matches Riddim, whose vision says "We target arm64 plugins only" (Riddim vision §7.1), so Riddim needs nothing new.
- **No Intel testing.**
- **Plugins:** the app hosts arm64 plugins (native or universal). Intel-only plugins don't load, because there's no Rosetta bridging, and the plugin manager lists them as unsupported with the reason.
- **On an Intel Mac** the app doesn't install or launch. The download page and the installer say so.
- **Drawing:** WebGL2 on macOS 15, and WebGPU on 26+ where available (§8.3).
- **Windows later.** Phil wants both, provided Windows isn't double the effort. What Windows adds is mostly in Riddim:
  - device backends ("no audio device backend there yet", Riddim D82);
  - Win32 editor parenting;
  - the bridge transport;
  - installers and signing.

  **[inferred]** That's well short of double, but nothing on Windows has run yet. The UI, the core and the dev host stay portable from day one.
- **Linux is a by-product.** Riddim builds and tests on Linux, deviceless only. The dev host on Linux is useful for UI development and CI.

---

## 9. What the DAW needs from Riddim

**Decision note.** Phil chose (21 Nov 2026) to build our own engine, Riddim, in Rust rather than adopt Tracktion Engine, JUCE or Ardour. An earlier draft of this doc recommended Tracktion Engine + JUCE. That analysis is superseded.

**Where Riddim stands** ([phases README](https://github.com/kaminocorp/riddim/blob/main/docs/phases/README.md), 2026-11-21):
- every phase's code is written and passes on Linux, and 9 of 22 criteria are met there;
- "Nothing has run on macOS at all";
- several of its criteria are Whiplash milestones, which the two projects finish together.

### 9.1 Shape of the API (as Riddim provides it)

- **In process:** the `riddim` crate, used directly from `whiplash-core`. The C ABI is for other clients (embedding.md).
- **Three channels** (Riddim vision §1.1):
  - **commands:** `apply` and `apply_wait`, `transport`, `set_param`;
  - **queries:** `model`, `status`;
  - **events:** `subscribe`.

  Everything has a JSON form (D83), which the UI's `EngineLink` passes through over WebSocket or Tauri IPC.
- **Edits are ops with inverses** (§5.3). Slow work started by an op is reported by events ([events.md](https://github.com/kaminocorp/riddim/blob/main/docs/api/events.md)).
- **Tests without hardware:** Riddim's manual and timer devices (`EngineConfig::manual`, D82) let the app's tests run in CI.
- **Versioning:** Riddim is pre-1.0, and the command JSON isn't pinned by golden files yet ([stability.md](https://github.com/kaminocorp/riddim/blob/main/docs/api/stability.md)). **App side:** pin a Riddim version, and keep contract tests on the JSON the UI sends and reads.

### 9.2 Capabilities the app relies on

| Capability | v0 | v0.5 | v1 |
|---|---|---|---|
| **Devices:** list CoreAudio devices, open at a rate and buffer size, report latencies, device loss and change. **Old class-compliant interfaces supported**, with Phil's **Scarlett 2i2 1st gen** as the reference (below) | ✓ | | |
| **Transport:** play, stop, locate, loop; a single tempo and meter per project (§5.1); metronome and count-in | ✓ | | |
| **Playback:** audio clips (offset, gain, fades) and MIDI clips into instruments | ✓ | | |
| **Recording:** arm, input select, monitoring; incremental WAVs; latency-corrected placement | audio + MIDI | | |
| **Mixing:** volume, pan, mute, solo, master | ✓ | inserts, sends, buses | |
| **Plugins:** out-of-process scan; load AU and VST3 by identity and **format**; parameters; opaque state; `open_editor`; latency | one instrument | effects, state save and restore | |
| **PDC** across the graph | | ✓ | |
| **Metering:** per-strip peaks; CPU, xruns, starvation | ✓ | | |
| **Note audition:** `play_note` into a track's instrument, for the piano roll's keyboard and note placement (§4.3; exists) | | ✓ | |
| **Render:** deterministic offline bounce of the master, with progress and cancel | | ✓ | |

**Platform:** arm64 macOS only (`aarch64-apple-darwin`), as Riddim already targets (§8.4).

**The interface** (Phil, 23 Nov, Q5):
- Phil's 2i2 is **1st generation, USB PID 0x8006** (Phil's report). The Linux kernel's Scarlett driver lists the 2i2 1st Gen as `1235:8006` ([kernel commit](https://mirrors.lzu.edu.cn/git/linux-net/-/commit/8780f561f6717dec52351251881bff79e960eb46)).
- Focusrite lists it as class compliant on macOS with "No Driver Required" ([Focusrite downloads](https://downloads.focusrite.com/focusrite/scarlett-1st-gen/scarlett-2i2-1st-gen)). Focusrite's control software no longer recognises 1st Gen devices, but they still pass audio as class-compliant devices ([Focusrite support](https://support.focusrite.com/hc/en-gb/articles/12033372452754)).
- So Riddim and the app must not depend on any vendor control software.
- Riddim D77 assumed a 2nd or 3rd gen; with a 1st gen, its loopback measurement places recordings the same way.
- **Not verified on hardware:** nothing has run with this interface.

---

## 10. Agent control (after the core works)

**Phil, 23 Nov (Q6):**
- Agent control comes **after the core works**, and it will likely need a UI rethink.
- **The engine command API (record, edit, CRUD) is built now either way** (§2, §5.3). It's the same API the UI uses.

So the cost now is only discipline: no UI action bypasses the command API.

**A sketch, to refine when it's scheduled:**
- the command API exposed locally (the dev host's WebSocket is a starting point), then over MCP;
- sophisticated editing done by agents, because the GUI deliberately has none beyond the piano roll's basics: humanise, groove, voicing and note transforms, audio cleanup, arrangement changes;
- each agent proposal applied as one labelled undo step;
- semantic names for plugin parameters.

**Prior art:**
- Logic Pro 13's "intelligent assistant" (beta; "requires an Apple Creator Studio subscription, a Mac with Apple silicon, and macOS 27 or later", [Apple](https://support.apple.com/en-us/109503));
- Ableton's Extensions SDK (public beta since 2026-06-02, [Ableton](https://www.ableton.com/en/blog/introducing-extensions-sdk));
- [ableton-mcp](https://github.com/ahujasid/ableton-mcp);
- REAPER's [ReaScript](https://www.reaper.fm/sdk/reascript/reascript.php).

---

## 11. Phasing: the fastest credible MVP

| Phase | App ships | Needs from Riddim (§9.2) | Done when |
|---|---|---|---|
| **v0 "tape"** (web app in Chrome) | `whiplash-core` and the dev host. The web UI in Chrome: an arrange view with audio and instrument tracks, record and play, transport and metronome, save and load, and undo from day one. One instrument's native editor window. WebGPU and WebGL2 drawing | the v0 column | Phil records a take over an installed instrument (LABS or Splice INSTRUMENT) through the 2i2, saves, reopens and hears it identically. This is also Riddim's P2 criterion 1 |
| **v0.5 "MVP"** (still in Chrome) | Basic edits (move, cut, copy, paste, trim, fades). **The piano roll** (§4.3). The project's BPM and time signature in the settings. The mixer with inserts, sends and buses. The plugin manager and format policy. Offline bounce. Both shortcut presets | the v0.5 column | a short song made with the installed plugins (§6.1), with at least one instrument part written or corrected in the piano roll, bounced to WAV |
| **v1** (Tauri 2) | The same UI and core wrapped in Tauri 2. An arm64 build for macOS 15+, signed and notarised. Autosave and crash recovery. The full-screen mixer. Look-and-feel polish (§4.5). Public release with LICENSE, CLA and CONTRIBUTING | the v1 column | Phil makes a track start to finish, from recording to bounce, without opening Logic. It installs and runs on a clean macOS 15 Apple Silicon Mac |
| **v1.x** | Loop and punch takes. Stems export. Automation lanes. CC and pitch-bend lanes in the piano roll. Sidechain. CLAP in the UI. Multi-out instruments, plugin MIDI out and file drops from plugin windows, when someone owns a plugin that needs them | as needed | |
| **Agent control** | The command API exposed to agents (§10), and the UI rethink that goes with it | | |
| **Windows** | The same app on Windows (§8.4) | WASAPI or ASIO, Win32 editor parenting, the bridge transport | Phil decides once the macOS app is in use and the effort can be measured |
| **Later, deliberately** | Session view. Comping. Time-stretch. Tempo changes, only if Phil reopens the decision (§5.1). Control surfaces. Plugin crash isolation with editors | | |

**Ordering:** v0 and v0.5 run in Chrome because that's the fastest loop: hot reload, devtools, and nothing to package. Wrapping in Tauri for v1 is then mostly the transport swap (§8.1). **[inferred]** Run a minimal Tauri build early, during v0, as a smoke test, so a WKWebView or main-thread surprise surfaces before v1.

---

## 12. Risks and hard parts

- **Scale.** Even a small DAW is a lot of work. The narrow v1 (§3) is the main mitigation. Expect months to v0.5 and longer to a polished v1 **[estimate, not a commitment]**.
- **Nothing has run on macOS yet,** not Riddim and not a host around it (§9). The dev host on Phil's Mac is the first real test.
- **Chrome isn't the shipping engine.** Developing in Chrome hides WKWebView differences (WebGPU availability, fonts, scrolling, input). **Mitigation:** a regular Safari or WKWebView pass, an early Tauri smoke test, and a forced-WebGL2 mode.
- **Two renderers** (WebGPU and WebGL2) double the drawing code. **Mitigation:** keep the drawing layer small (§8.3). If WebGL2 alone proves good enough, WebGPU can wait.
- **The piano roll is the biggest single UI piece in v1.** Snapping, resize handles, marquee selection and a velocity lane all have to feel as good as Logic's. **Mitigation:** draw it in the same canvas layer as the timeline (§8.3), and keep v1 to the listed tools (§4.3).
- **A fixed BPM with audio clips.** Changing the BPM after recording audio misaligns it, because there's no time-stretch. **Mitigation:** warn before the change (§5.1).
- **Native feel in a web UI** ("feels Apple-made", §4.5) is many small things. Budget for it in v1.
- **Two repos, one contract.** Riddim is pre-1.0. **Mitigation:** a pinned version and contract tests.
- **Untested plugins.** The test set (§6.1) is effects-heavy, with two instruments. Multi-out, MIDI out and very large samplers stay untested until someone owns one.
- **Open source logistics.** Public issues, signing and notarisation, a CLA without counsel's review yet (§1.1), and support load.

---

## 13. Decisions and open questions

### 13.1 Resolved

**21 Nov 2026:**
- **UI stack:** Tauri 2, a Rust core with a TypeScript web UI and WebGPU (§8).
- **Document and timeline ownership:** Riddim owns the engine model and ops. Whiplash owns the project, UI state and undo stack (§2, §5).
- **Platforms:** macOS first, Windows later, Linux a by-product (§8.4).
- **Copyright:** Kamino Research Corporation (legal entity: Bradgate Capital Management Pte Ltd, Singapore) (§1.1).
- **Rig:** a Mac Mini M4 Pro and a Scarlett 2i2. Helix isn't owned.

**23 Nov 2026 (Phil's answers):**
1. **v1 scope:** smaller but high quality. Record, an arrange timeline with basic edits (move, cut, copy, paste, trim, fades), a mixer, AU/VST3 hosting, export. Sophisticated editing is left to agents later, so the GUI gets no advanced editing controls (§3, §4.3). **Amended later on 23 Nov:** v1 must include a piano roll (MIDI note editor) like Ableton's or Logic's for instrument tracks: draw or place, move, resize and delete notes, velocity, quantise (§4.3). The audio editor and automation lanes stay out of v1, because the piano roll needs neither. It needs note audition, which Riddim already has.
2. **Audience:** open source and public (§1).
3. **Licence:** AGPL-3.0, like Riddim, for now. Kamino keeps the right to relicense, so a CLA is required for outside contributions from day one (§1.1).
4. **macOS floor:**
   - macOS 15 Sequoia minimum. **Amended later on 23 Nov:** Apple Silicon only (arm64). Intel and the universal binary are dropped entirely, and so is Intel testing (§8.4);
   - WebGPU when `navigator.gpu` exists (macOS 26+), and WebGL2 on 15;
   - cited against Cubase, Ableton, Bitwig, FL Studio, REAPER and Logic (§8.3, §8.4). Note: the Cubase that starts at macOS 15 is Cubase 16; Cubase 15 also supports 14.
5. **Interface:** Phil's 2i2 is 1st gen (USB PID 0x8006) and class compliant. Old interfaces are supported (§9.2).
6. **Agent control:** after the core works, likely with a UI rethink. The engine command API (record, edit, CRUD) is built now either way (§2, §10).
7. **Shortcuts:** Logic and Ableton presets, as a user preference (§4.6).
8. **Plugin formats:** VST3 is the default when a plugin ships both. AU is available on macOS, with a preference setting. Formats of one plugin are never mixed in a project (§6.3).
9. **Look:** hybrid, dark-led, ultra-minimal, premium, feels Apple-made (§4.5).
10. **Session view:** arrange timeline only for v1, no session view (§3).
11. **Repo:** the app lives in a new repo, [kaminocorp/whiplash-daw](https://github.com/kaminocorp/whiplash-daw).
12. **Fastest credible MVP:** build the UI as a plain web app against the local Riddim engine (developed in Chrome), then wrap it in Tauri 2. No pure in-browser build, since browsers can't host AU/VST3 (§8, §11).
13. **Plugins:** no purchases. Test with the installed Slate (Virtual Mix Rack, FG-X, VerbSuite, Virtual Tape Machines), Kilohearts, Eiosis AirEQ, Overloud TH-U, LANDR, Splice INSTRUMENT and LABS. The "Kontakt/SD3/EZbass required" done-when criteria are dropped (§6.1, §11).

### 13.2 New questions these answers raised

**Resolved (Phil, 2026-11-23):**
- **Q-N1. Riddim and Intel.** *Resolved:* Apple Silicon only, arm64, macOS 15+. There's no Intel build, no universal binary and no Intel testing. This matches Riddim's arm64-only target, so Riddim needs no change (§8.4).
- **Q-N5. Can tempo change in v1?** *Resolved:* no tempo map and no tempo changes. Each project has one user-defined BPM and time signature, fixed for the whole song and editable per project (§5.1).

**Still open:**
- **Q-N2. Which Kilohearts and LANDR plugins** are installed? The first scan will list them, along with every plugin's formats.
- **Q-N3. The CLA.** Reuse Riddim's draft (adapted to Whiplash), and when does counsel review it: before the repo goes public, or before the first outside contribution?
- **Q-N4. Is whiplash-daw public from day one,** or private until v0.5?
- **Q-N6. The dev host after v1.** Keep it as the agent API's transport (§10), or retire it once Tauri ships?
