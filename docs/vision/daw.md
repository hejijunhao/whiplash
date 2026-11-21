# Whiplash DAW: vision

Status: **vision draft for Phil to refine, 2026-11-21.** Nothing is built in this repo, and the app's build phase starts only on Phil's explicit go-ahead. Facts are cited inline and were checked on 2026-11-21. Anything marked **UNVERIFIED** wasn't confirmed from a primary source, and **[inferred]** marks our own reasoning. §13 lists the open questions.

**Copyright:** Kamino Research Corporation (legal entity: Bradgate Capital Management Pte Ltd, Singapore), the same owner as Riddim (§1.1).

**Framing and updates from Phil (21 Nov 2026):**
- **A new project** that keeps only the name *Whiplash*. It is not the Hermes plugin in this repo and not the Digitakt web twin (PR #34). Digitakt II support is out of scope.
- **Core DAW first** (8:14 SGT). The baseline is an **Ableton/Logic twin**. Agent control is a short later-phase note (§10), and it drives none of the scope, the stack or the phasing.
- **The engine is a separate repo** (8:24 SGT): **[kaminocorp/riddim](https://github.com/kaminocorp/riddim)**, "Riddim", our own audio engine in Rust. This doc treats Riddim as a **dependency behind its API** and covers the **app**: UX, workflow, editors, mixer UI, project model and phasing. §9 says what the app needs from Riddim.
- **Decisions** (~16:50 SGT):
  1. **UI stack: Tauri 2.** A Rust core links Riddim in process. The UI is TypeScript in the web view, with WebGPU for waveforms and meters (§8). The earlier "native Swift" lean is dropped.
  2. **Platforms: macOS first, Windows later.** The app stays portable, and Phil wants both if Windows isn't double the effort. Linux is a by-product (§8.4).
  3. **Ownership:** Kamino Research Corporation, as above.
  4. **Phil's rig:** a Mac Mini with an M4 Pro and a Focusrite Scarlett 2i2 (2nd or 3rd generation). **No Helix yet.**

  Riddim already records the same decisions as D77 to D83 ([decisions.md](https://github.com/kaminocorp/riddim/blob/feat/v1x/docs/decisions.md)). This doc is aligned with Riddim's [`docs/api/embedding.md`](https://github.com/kaminocorp/riddim/blob/feat/v1x/docs/api/embedding.md) and its vision's §1.1 boundary ([riddim.md](https://github.com/kaminocorp/riddim/blob/feat/v1x/docs/visions/riddim.md)), as of branch `feat/v1x` at `dc7d488`.

---

## 1. What it is, and what it isn't

**It is:**
- **Our own desktop DAW**, with Riddim underneath. It ships on **macOS first**, and **Windows comes later** from the same code (§8.4). In look and workflow it is an Ableton Live and Logic Pro hybrid: Logic's arrange window, mixer and editors, with Ableton's speed, device chain and (later) clip launching.
- **Built for Phil to record and finish music** with the instruments and plugins he owns.

**It isn't:**
- **A toy or a demo.** It has to record a real session with real plugins without losing a take.
- **A browser app.** The UI is web technology, but it runs inside a native Tauri shell. Audio, plugins and files all live in native code: the Rust core and Riddim. The target plugins ship as native AU and VST3 binaries (§6), and no browser can load them.
- **A Logic or Ableton replacement in breadth.** No notation, video, surround, bundled instrument suite, comping or Flex Time in v1 (§11).
- **An AAX host.** Every target plugin also ships as AU and VST3.

**Who it's for:** Phil first, on a **Mac Mini with an M4 Pro** and a **Focusrite Scarlett 2i2 (2nd or 3rd generation, not yet known which)**. Anyone else comes later, if ever (Q2).

### 1.1 Ownership and licence

- **Owner:** Kamino Research Corporation (legal entity: Bradgate Capital Management Pte Ltd, Singapore), which Phil wholly owns. Riddim has the same owner (Riddim D79).
- **Riddim's licence:** AGPL-3.0-only ([COPYRIGHT](https://github.com/kaminocorp/riddim/blob/feat/v1x/COPYRIGHT)). Because the owner is the same, Whiplash "can link the engine on whatever terms it ships under" ([embedding.md](https://github.com/kaminocorp/riddim/blob/feat/v1x/docs/api/embedding.md), "Licence").
- **Whiplash's own licence is not decided** (Q3). **[inferred]** This repo carries no copyright notice yet. If the app lands here (Q11), the notice gets added when the code starts.

---

## 2. Architecture at a glance

```
┌──────────────────────── Whiplash (Tauri 2 app) ────────────────────────────────────┐
│  Web view (TypeScript): arrange · editors · mixer · browser · inspector            │
│    WebGPU: waveforms, meters, timeline canvas                                       │
│    commands (JSON) ↓                                        ↑ events (JSON)          │
│  Rust core: project folder & file · media pool & waveform overviews · undo stack   │
│    UI state · plugin-editor windows (native, beside the web view) · main-thread pump │
│    links the `riddim` crate, in process                                             │
└───────────────▲──────────────────────────────────────────────┬─────────────────────┘
                │ events: applied/rejected (+inverses), position, │ ops (edits), transport,
                │ meters, model_changed, recording, plugin, errors│ set_param, queries
┌───────────────┴─────────────────── riddim API ──────────────────▼────────────────────┐
│  Riddim (kaminocorp/riddim, Rust): the engine model (tracks, clips, routing,        │
│  automation, tempo map, plugin slots), validated ops with inverses, devices,        │
│  real-time graph, PDC, recording, AU/VST3/CLAP hosting, scan, offline render        │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

**The boundary, as Riddim defines it** (vision §1.1): "Riddim owns everything that has to be correct in time (samples, latency, plugin lifetimes, files being written). Whiplash owns everything about intent and presentation."
- **Riddim owns the engine model:** tracks, clips, routing, automation curves, the tempo and meter map, and plugin slots with opaque state. It also owns the **edit ops**, which it validates and applies atomically and which each return their **inverse**.
- **Whiplash owns the project:**
  - the folder and the file format that wraps the engine model;
  - the media pool and waveform overviews;
  - UI state (zoom, selection, colours, window layout);
  - the **undo stack**, built from the inverses Riddim returns;
  - every piece of presentation.

The previous draft proposed the reverse, with the app owning the document and Riddim mirroring it. That draft's Q3 is now **resolved in Riddim's favour**: Riddim has to validate every edit against the live graph (a send can't create a cycle), so it holds the model types.

---

## 3. Core functionality (v1 must-haves)

| Area | v1 scope |
|---|---|
| **Recording** | Mono and stereo audio from the interface's inputs. Input monitoring. Arm several tracks at once. Loop and punch recording, keeping takes as separate clips (no comping UI in v1). Latency-corrected placement. MIDI recording with overdub and replace |
| **Audio tracks** | Clips referencing audio files. Gain, fades and crossfades. Non-destructive |
| **MIDI and instrument tracks** | One instrument plugin (AU/VST3) per track plus an effect chain. Multi-output instruments routed to their own mixer channels. Plugin MIDI output routable to other tracks (§6.2) |
| **Arrangement** | Tracks and clips on bars and beats. Tempo and time-signature map. Markers and sections. Snap and grid. Folders and track stacks |
| **Mixer** | Channel strips with inserts, sends (pre/post), buses, master, volume, pan, mute and solo. Sidechain inputs. Peak and RMS meters |
| **Transport** | Play, stop, record, loop range, punch in/out, metronome with count-in, tap and typed tempo, follow playhead |
| **Editing** | Clip move, trim, split, duplicate and loop. Piano roll. Audio clip edits (trim, fade, gain, reverse, normalise; no time-stretch in v1). Quantise with strength and swing. Humanise |
| **Automation** | Lanes for track and plugin parameters. Read, write, touch and latch. Breakpoint editing |
| **Project** | Save, load, autosave and crash recovery. A self-contained project folder (§5) |
| **Export** | Offline bounce of the master or stems to WAV/AIFF. Real-time bounce as a fallback |
| **Undo** | Unlimited, one history for every edit (§5.3) |

---

## 4. Look, workflow, editors and mixer

### 4.1 What comes from where

| From **Ableton Live** (12.4.16 current; Live 13 announced for early 2027, [ableton.com](https://www.ableton.com/en/live/)) | From **Logic Pro** (13.0, 2026-11-06, [Apple](https://support.apple.com/en-us/109503)) |
|---|---|
| **Speed:** single window, few modal dialogs, keyboard-first, drag-and-drop everywhere | **The arrange window** as the main canvas ([Tracks area](https://support.apple.com/guide/logicpro/tracks-area-overview-lgcpf7c0d5d8/mac)) |
| **The device chain:** a horizontal strip of devices along the bottom ([Live manual](https://www.ableton.com/en/live-manual/12/working-with-instruments-and-effects/)) | **The mixer:** a full console with sends, buses, folders and colour ([Mixer](https://support.apple.com/guide/logicpro/mixing-overview-lgcpbc219818/mac)) |
| **Racks and macros,** later ([Racks](https://www.ableton.com/en/live-manual/12/instrument-drum-and-effect-racks/)) | **Docked editors:** piano roll, audio editor, later a step sequencer ([Piano Roll](https://support.apple.com/guide/logicpro/overview-lgcpa9111b0d/mac)) |
| **Session view** (clip launching), in v1.x ([Session View](https://www.ableton.com/en/live-manual/12/session-view/)) | **The inspector,** plus **Smart Controls** as our quick controls ([Smart Controls](https://support.apple.com/guide/logicpro/smart-controls-overview-lgcp7e59f24b/mac)) |
| **The browser:** one searchable place for instruments, plugins, presets and samples | **Multi-output instrument handling** ([Logic guide](https://support.apple.com/guide/logicpro/use-multi-output-instruments-lgcp8e887f45/mac)) |

### 4.2 Main window

```
┌──────┬──────────────────────────────────────────────────────────────┬────────────┐
│ ◀ ▶ ● ⟲  │ 1.3.2 │ 120.00 │ 4/4 │ ⧗ count │ CPU ▮▮▯ │ DISK ▮▯ │ 2i2 48k/128        │
├──────┼──────────────────────────────────────────────────────────────┼────────────┤
│ INSP │  ruler · markers · sections                                   │ BROWSER    │
│      │  ─────────────────────────────────────────────────────────── │ instr      │
│ chan │  01 Drums  SD3 ▸ [clip────────][clip────────]                 │ plugins    │
│ strip│  02 Bass   EZbass [MIDI clip───────]                          │ presets    │
│      │  03 Gtr    ● amp sim ~~~audio~~~~~~~~~                        │ samples    │
│ quick│  04 Keys   Kontakt/Noire [MIDI──]   ← automation lane ↓      │ files      │
│ ctrls│  05 Vox    ● ~~~~~audio~~~~~                                  │            │
│      │  Bus A · Bus B · Master                                       │            │
├──────┴──────────────────────────────────────────────────────────────┴────────────┤
│ DETAIL (Tab toggles): device chain ▸ [EQ][Comp][Amp][Send A]   or                 │
│ editor: piano roll / audio editor for the selected clip                           │
└───────────────────────────────────────────────────────────────────────────────────┘
   X = full-screen mixer (Logic-style console)      Tab = session grid (v1.x)
```

- **Centre: the arrange window.** Tracks run top to bottom and time left to right. Automation lanes fold under each track. Waveforms are drawn with WebGPU from overviews the Rust core precomputes (§5.2), at any zoom and without stalls.
- **Bottom: the detail pane.** Ableton's device chain for the selected track, or Logic's editor for the selected clip.
- **Left: the inspector.** The channel strip, plus **quick controls**: a few plugin parameters pinned per track.
- **Right: the browser** for plugins, presets, samples and project files. Drag an item onto a track, or onto the empty area to create a new track.

### 4.3 Editors

- **Piano roll** (v0.5):
  - notes with velocity and length;
  - a velocity lane, plus CC and pitch-bend lanes;
  - scale highlighting;
  - quantise (grid, strength, swing) and humanise (timing and velocity, seeded so it's repeatable);
  - a keyboard-first edit set: nudge, length, transpose, duplicate.
- **Audio editor** (v0.5): trim, fades, gain, reverse, normalise, silence detection to split, and clip gain envelopes. Non-destructive: edits live in the model, and the source files are never modified.
- **Later:** a step sequencer (Logic-style, [Apple](https://support.apple.com/guide/logicpro/step-sequencer-overview-lgcp39acefc9/mac)), comping, warping and time-stretch (§11).

### 4.4 Mixer UI

- **A full-screen console** (`X`) with strips for audio, instrument, aux and bus channels, plus master, in track order. Folders collapse to one strip.
- **Each strip:** input, inserts (drag to reorder, alt-drag to copy), sends with levels, output, pan, fader, meter, mute, solo, record and monitor. Multi-out instrument channels group under their instrument.
- **Sidechain:** picked from a strip's plugin, listing buses and tracks.
- **Meters:**
  - Riddim sends per-strip peaks in a `meters` event about thirty times a second ([events.md](https://github.com/kaminocorp/riddim/blob/feat/v1x/docs/api/events.md)).
  - The UI smooths them, holds the peaks and draws them with WebGPU.
  - If the UI wants frame-rate or binary data, the Rust core keeps the latest values and answers a per-frame request, and the engine doesn't change for that (embedding.md).
  - Engine-side RMS and true peak aren't in Riddim yet (embedding.md), so the v1 "peak and RMS" row in §3 depends on it (§9.2).
  - The UI never computes audio.

### 4.5 Aesthetic

- **A dark instrument, Dieter Rams-adjacent:** "less, but better". Near-black and graphite surfaces. One accent colour for live state: record arm, playhead, clip.
- **Tabular monospace numerals** for time and values. Colour only where it means something, such as track colour and meters.
- **No purple gradients, glassmorphism, sparkle icons or generic AI styling.**
- **Plugin windows look like their vendors made them.** We frame them and never skin them.
- **Readable across a room:** large transport numerals and a clear record state.
- **[inferred]** A web UI looks native only if we work at it: native menus (Tauri has a menu API), keyboard handling, focus, scrolling feel and text rendering. Budget for it (§12).

---

## 5. Project model

### 5.1 Structure

**Riddim's engine model** ([`riddim-model`](https://github.com/kaminocorp/riddim/tree/feat/v1x/crates), typed, serialisable and versioned):
- tracks, clips, routing (buses, sends, inserts), automation curves;
- the tempo and meter map, in Riddim's integer time (beat ticks and superclock, `riddim-time`), so tempo edits move clips correctly;
- plugin slots with opaque state blobs.

**Whiplash's additions** (vision §1.1 lists them as the app's):
- the media pool;
- UI state: zoom, selection, track colours, window layout and plugin-window positions;
- quick-control mappings, browser favourites, markers' display names if the model doesn't carry them (**to confirm** against `riddim-model`).

**Objects are addressed by Riddim's IDs**, so ops, undo and events refer to objects, never to list positions.

### 5.2 Files

- **A project folder:** the project file, `Audio/` (recordings and imports, copied in), `Overviews/` (waveform peak files) and `Autosave/`. Plugin state travels inside the model as opaque blobs. Whether large blobs (SD3, Kontakt) should move to side files is **to confirm** with Riddim.
- **The project file:** a versioned JSON document. Riddim's model is its core (`Model::to_json`, versioned by the model's `schema` number and covered by Riddim's [stability policy](https://github.com/kaminocorp/riddim/blob/feat/v1x/docs/api/stability.md)). Whiplash's own sections wrap it, under Whiplash's own version number.
- **Media:**
  - imports are copied in by default;
  - missing media shows as offline (Riddim sends `media_missing` and plays those clips as silence);
  - missing plugins show as placeholders that keep their state and never drop it.
- **Autosave** every few seconds to `Autosave/`. Crash recovery offers the newest autosave.
- **Recording:** Riddim writes recordings incrementally as ordinary WAVs. `recording_finished` names the media entry, so a crash loses at most the last flush.
- **Waveform overviews** are the app's work: the Rust core reads the media files and computes them, and Riddim isn't involved (embedding.md).

### 5.3 Commands and undo

- **Every user action is a typed command,** whether it comes from a menu, a shortcut or a drag. A command is one or more Riddim **ops**.
- **The core sends the ops through `engine.apply_wait(ops)`.** Riddim validates them, applies them atomically, and replies with `Applied { revision, inverses }` or `Rejected { index, error }`. A rejected batch leaves the model unchanged, so bad input never changes what's playing.
- **The undo stack** is a list of inverse batches, one per user command, with labels. Gestures such as a fader drag merge into one step. Undo applies the inverses as ops. Riddim needs nothing special for it.
- **Edits the engine makes itself** (a finished recording, a pass of written automation) arrive as `model_changed` with their inverses, and go on the same undo stack.
- **Determinism:** randomised edits (humanise) take a recorded seed. The same command on the same model gives the same result.
- This is ordinary DAW architecture, and it is also what makes later agent control (§10) cheap: an agent gets the same ops the UI uses.

---

## 6. Third-party plugins (hard requirement)

### 6.1 Phil's target products (checked 2026-11-21)

**Three targets now, and Helix later.** Phil doesn't own Helix yet, so it's a future test plugin, not a v1 requirement (Phil, 21 Nov; Riddim D78). Per Riddim D78 and D10, the other three haven't been bought yet either. Until they are, compatibility testing uses stand-ins (Riddim uses Surge XT and its own fixtures).

| Product | Mac formats | Apple Silicon | Min macOS | Licensing (host involvement) |
|---|---|---|---|---|
| **Kontakt 8 Player** (free) + **Noire** (paid library) | AU, VST3, AAX, standalone ([NI specs, search excerpt](https://www.native-instruments.com/en/products/komplete/samplers/kontakt-8/specifications/)) | yes | 14, 15, 26 per an NI excerpt; another excerpt says 15, 26, 27 (**UNVERIFIED**) | Native Access with an NI account. The plugin itself shows "not activated" ([NI KB](https://support.native-instruments.com/support/solutions/articles/69000879750-kontakt-error-message-not-activated-or-full-kontakt-required-)). The host does nothing. Noire runs in the free Player per an NI excerpt ([NI](https://www.native-instruments.com/en/products/komplete/keys/noire/), **UNVERIFIED** full page) |
| **Superior Drummer 3** (3.4.4, 2026-03-26) | AU, VST3 (since 3.3.0), AAX, standalone ([release notes](https://www.toontrack.com/release-notes/superior-drummer-3/)) | native since 3.2.5 | 10.13 | Toontrack Product Manager ([Toontrack](https://www.toontrack.com/product-manager/)). The host does nothing |
| **EZbass** (1.3.4, 2026-05-29) | AU, VST3, AAX, standalone ([release notes](https://toontrack.com/release-notes/release-notes-ezbass)) | native since 1.1.0 | 10.13 | Product Manager plus an account. The host does nothing |
| *Later:* **Helix Stadium Native** (launched 2026-08-04), not owned | VST3, AU, AAX; no standalone ([Line 6 KB](https://kb.line6.com/helix-stadium-native-faq)) | yes per reviews (**UNVERIFIED**) | 14 per reviews (**UNVERIFIED**) | A Line 6 account, up to four computers ([Line 6 KB](https://kb.line6.com/helix-stadium-native-faq)). The host does nothing |

**Copy protection is handled inside each plugin and its vendor app.** The host only has to stay out of the way: no blocking of first-run dialogs or network access, and no killing a slow load.

### 6.2 What these plugins need (app side and engine side)

| Need | Source | App | Riddim (§9.2) |
|---|---|---|---|
| **Multi-output instruments.** Kontakt's AU "16xStereo" variant (NI manual excerpt, **UNVERIFIED** full page). SD3's 16 stereo outs ([Toontrack](https://www.toontrack.com/product/superior-drummer-3/)) | | creates mixer channels per output bus, grouped under the instrument | negotiates bus layouts, exposes each output as a routable channel |
| **Sidechain input** (a general need; Helix's dynamics and filters use it when Helix arrives) | [Line 6 KB](https://kb.line6.com/helix-stadium-native-faq) | a sidechain picker on the strip | sidechain bus routing |
| **Plugin MIDI output** (SD3, EZbass) | [SD3](https://www.toontrack.com/product/superior-drummer-3/), [EZbass notes](https://toontrack.com/release-notes/release-notes-ezbass) | routes it to other tracks, or records it | delivers plugin MIDI out as an event stream |
| **File drops from a plugin window onto the timeline.** SD3 writes a temporary MIDI file and starts an OS drag ([SD3 3.2.5 notes](https://www.toontrack.com/release-notes/superior-drummer-3/)). EZbass "may not work in some hosts" ([Toontrack](https://www.toontrack.com/product/ezbass/)) | | **the app's** web view accepts OS file drops from any window, plugin windows included (**[inferred]**: Tauri delivers native drag-drop events with file paths to the core; to test with SD3) | none |
| **Host playhead** (SD3 "Follow Host") | [Toontrack forum, staff](https://www.toontrack.com/forums/topic/superior-drummer-3-are-tempo-and-time-signature-synchronized-bidirectional-in-daw/) | tempo map edits as ops | supplies tempo, time signature, position and transport to plugins |
| **Large memory and slow loads** (an SD3 preset takes 3.7-18 GB) | [Toontrack FAQ](https://www.toontrack.com/faq/how-much-ram-does-a-superior-library-or-sdx-use/) | progress UI, so the project stays usable while a plugin loads | loads **one plugin per main-thread pump**, so the UI is held for one plugin at a time and audio keeps running (Riddim D50, embedding.md) |
| **Latency** (amp sims, look-ahead) | | shows a strip's latency, plus a low-latency monitoring toggle | reports it and compensates (PDC) |

### 6.3 Plugin UX in the app

- **Plugin manager:**
  - runs a scan through Riddim in the background (out of process), with progress, and never blocks;
  - lists formats, vendors and failures, with a blocklist and "rescan";
  - Phil picks AU or VST3 when a plugin ships both (Q8).
- **Plugin windows** are native windows, never web content: a plugin's editor can't go inside the web view (embedding.md).
  - The Rust core makes one native window (or panel) per editor, on the main thread, beside the web view window. Riddim's `open_editor(ParentWindow::AppKit(ns_view))` puts the editor into it.
  - The core owns placement and closing, and follows `plugin_editor_resize`.
  - Our frame adds a title, bypass, preset menu, A/B and a latency readout. **[inferred]** That frame is either a thin native strip or a small web view docked to the window. To decide in the first spike.
  - Windows float and remember their position per instance.
  - Riddim's CLI already does this, and its editor-window code can be reused or used as a model (embedding.md).
  - Windows (the OS) needs a Win32 parent instead (§8.4).
- **Missing or crashed plugins:** an offline placeholder that keeps its state.
  - Riddim can run a plugin in a process of its own, opt-in per plugin (README), but bridged plugins have no editor yet (embedding.md).
  - v1 shows a crash clearly and recovers from autosave.

---

## 7. Workflow details that make or break it

- **Never block the UI:** loading a project, a plugin, a scan, a bounce. Everything slow shows progress and can be cancelled.
- **Recording must feel safe:** a clear arm and record state, input meters before you press record, the disk space left, and every take kept (the takes stack in v1, comping comes later).
- **Keyboard-first:** every common action has a shortcut. A Logic-compatible key set is an option (Q7).
- **Snapping and zoom:** smooth, fast, and predictable to the sample.
- **Low-latency monitoring** while recording: high-latency plugins are bypassed or flagged on armed tracks.

---

## 8. UI stack: Tauri 2 (decided)

**Decision (Phil, 21 Nov 2026; Riddim D83):** [Tauri](https://github.com/tauri-apps/tauri) 2 (MIT/Apache-2.0; current release `tauri-v2.12.7`, 2026-11-18, [releases](https://github.com/tauri-apps/tauri/releases)):
- a **Rust core** that links Riddim in process;
- a **TypeScript web UI** in the system web view;
- **WebGPU** for waveforms and meters.

**Replaced:** the earlier "native Swift" lean, along with the Rust-native toolkits and Qt. Those options and the A-vs-C spike are retired.

**Why it fits [inferred]:**
- one Rust process with Riddim, so no binding layer;
- fast iteration on a rich layout;
- people and agents write the UI quickly;
- the UI code carries over to Windows.

### 8.1 Who does what

| Part | Lives on | Does |
|---|---|---|
| **`Engine`** | `tauri::State<Mutex<Engine>>` | Commands and queries. Its methods are quick and never wait on audio, so a plain lock is enough (embedding.md) |
| **`MainThread`** (`Engine::take_main_thread`) | **The app's main thread, for good** (a `thread_local!` or the event loop's state, never `State`) | Holds plugin instances. On macOS, plugins, their editors and Audio Units must be created and called on the main thread. `pump()` runs a few dozen times a second, from the run loop's idle or "about to wait" event or a main-thread timer (embedding.md; the exact Tauri hook is **unbuilt design**) |
| **Event forwarder** | its own thread | Drains `Engine::subscribe()` and emits to the web view (`app_handle.emit` or a `tauri::ipc::Channel`), so a slow UI never backs up into the engine |
| **Rust core, the rest** | worker threads | Project load and save, autosave, media import, waveform overviews, the undo stack, file-drop handling |
| **Web view (TypeScript)** | the web view's own process | All views and interaction. Sends commands as JSON and renders events. Ignores event names and fields it doesn't know (events.md) |
| **WebGPU** | inside the web view | Timeline canvas, waveforms and meters |

**Quit order** (embedding.md): drop the `Engine`, keep pumping until `pump()` returns `false`, then drop the `MainThread`, so that every plugin is destroyed on the thread that made it.

### 8.2 The command path

A Tauri command is a few lines, because Riddim has a JSON form for everything (D83):

| From the UI | Rust core | Back to the UI |
|---|---|---|
| A user command, as a list of ops: `[{"op":"add_track",...}]` | `engine.apply_wait(ops)`, then the inverses go on the undo stack | `Applied` `{"revision":7,"inverses":[...]}`, or `Rejected` `{"index":0,"error":"..."}` |
| `{"command":"play"}`, `stop`, `record`, `locate` | `engine.transport(command)` | `transport` and `position` events |
| A slot, parameter ID, value 0-1 | `engine.set_param(...)` | `plugin_param` events from the plugin side |
| | `engine.model()`, `engine.status()` | the model (as the project format), `Status` |

**Rule:** never hold the engine lock across a wait. `capture_plugin_states` waits on the main-thread pump, so it must never be called from the main thread (embedding.md).

### 8.3 Known costs and how we handle them

- **WebGPU in the system web view.**
  - **macOS:** WebGPU "is supported and enabled by default" only from **macOS Tahoe 26** ([gpuweb implementation status](https://github.com/gpuweb/gpuweb/wiki/Implementation-Status)). Tauri uses WKWebView there.
    - WKWebView exposing `navigator.gpu` on macOS 26 is **UNVERIFIED**. An Apple forum reply suggests it does once the feature is on by default ([Apple forums](https://developer.apple.com/forums/thread/770862)), and one WebKit bug reports `navigator.gpu` missing in Safari 26.x ([WebKit 301627](https://bugs.webkit.org/show_bug.cgi?id=301627)).
    - So either the macOS floor is 26 or we keep a fallback renderer (Canvas 2D or WebGL) (Q4).
    - **Check on Phil's Mac first:** test for `navigator.gpu` in a bare Tauri window.
  - **Windows:** Chromium has shipped WebGPU on x86/x64 since 113, but ARM64 is still behind a flag (gpuweb status). In 2023 Tauri's WebView2 didn't expose it ([tauri#6381](https://github.com/tauri-apps/tauri/issues/6381)). Current WebView2 behaviour is **UNVERIFIED**.
  - **Linux:** no WebKitGTK WebGPU status found (**UNVERIFIED**), and Tauri documents WebKitGTK graphics problems on some drivers ([Tauri](https://v2.tauri.app/develop/debug/linux-graphics/)). That doesn't matter while Linux is a by-product.
- **A timeline at scale** (thousands of clips) is custom WebGPU or canvas work, not DOM. **[inferred]** Draw the arrange view and editors in one canvas layer, and keep the DOM for panels, inspector and dialogs.
- **IPC volume.** Meters and position at about 30 Hz as JSON are small. If profiling says otherwise, the core keeps the latest values and the UI pulls them per frame as binary (embedding.md).
- **Native feel** (menus, keyboard, focus, scrolling): real work, budgeted (§4.5, §12).
- **Plugin editors** are separate native windows (§6.3). They float anyway, as in Logic.
- **Unbuilt:** "No Tauri application has been built or run against the engine" (embedding.md). Riddim tests the embedding shape with plain threads and channels, with no Tauri in the test (`crates/riddim/tests/embedding.rs`). The first spike (§11, Q12) is what makes it real.

### 8.4 Platforms

- **macOS first.** Apple Silicon (Phil's M4 Pro). The floor is open (Q4).
- **Windows later.** Phil wants both, provided Windows isn't double the effort.
  - **[inferred]** With Tauri, the UI and the Rust core are shared. What Windows adds:
    - Riddim's device backends (WASAPI or ASIO; "no audio device backend there yet", D82);
    - Win32 parenting for plugin editor windows;
    - Riddim's out-of-process bridge transport (future work, D82);
    - installers and signing;
    - a Windows test machine.
  - That's well short of double, but most of it sits in Riddim, and nothing on Windows has run yet: Riddim "compiles, and nothing more is claimed" (D82).
  - **To keep it cheap:** no macOS-only code outside a small platform module in the core (editor windows, menus, file-drop specifics), and CI type-checks the core for Windows, as Riddim does (D82).
- **Linux is a by-product.** Riddim builds and tests on Linux, deviceless only (embedding.md). The app on Linux is useful for development and CI, not as a target.

---

## 9. What the DAW needs from Riddim

**Decision note.** Phil chose (21 Nov 2026) to build our own engine, Riddim, in Rust rather than adopt Tracktion Engine, JUCE or Ardour, while borrowing their ideas. An earlier draft of this doc recommended Tracktion Engine + JUCE. That analysis is superseded.

**Where Riddim stands** (its [phases README](https://github.com/kaminocorp/riddim/blob/feat/v1x/docs/phases/README.md), 2026-11-21):
- "Every phase's code is written and passes on Linux; 9 of the 22 criteria are met there." The rest are met only in weaker form or not at all.
- "Nothing has run on macOS at all."
- Several of Riddim's exit criteria are **Whiplash milestones**, such as "Whiplash v0: record a take over the instrument, save, reopen, hear it identically". The two projects finish those together.

### 9.1 Shape of the API (as Riddim provides it)

- **In process:** the `riddim` crate, used directly from the Rust core. The C ABI (`riddim-ffi`) is for other clients, and the app doesn't use it (embedding.md).
- **Three channels** (Riddim vision §1.1):
  - **commands:** `apply` and `apply_wait`, `transport`, `set_param`;
  - **queries:** `model`, `status`;
  - **events:** `subscribe`.

  Threading follows §8.1.
- **Edits are ops with inverses** (§5.3). Slow work started by an op, such as a plugin load, is reported by events.
- **Events** ([events.md](https://github.com/kaminocorp/riddim/blob/feat/v1x/docs/api/events.md)):
  - edits: `applied`, `rejected`, `model_changed`;
  - playback: `transport`, `position`, `jumped`;
  - monitoring: `meters`, `load`, `xrun`, `playback_starved`, `stream_changed`;
  - files and plugins: `media_missing`, `recording_finished`, `plugin_param`, `plugin_editor_resize`, `plugin_crashed`, and others.
- **Tests without hardware:** Riddim has manual and timer devices (`EngineConfig::manual`, D82), so the app's tests run in CI with no audio interface.
- **Versioning:** the Rust API by semver, the project format by the model's `schema` number. The promise starts at a tagged 1.0, which doesn't exist yet. The JSON for commands, results and status is new and not yet pinned by golden files ([stability.md](https://github.com/kaminocorp/riddim/blob/feat/v1x/docs/api/stability.md)). **App side:** pin a Riddim version, and keep contract tests in this repo that exercise the JSON the UI sends and reads.

### 9.2 Capabilities the app relies on, by phase

What each app phase needs. Riddim's own phases (P2 "tape", P3 mix, P4 v1, v1.x) map onto these columns. Their status, all on Linux so far, is in Riddim's phase notes.

| Capability | v0 | v0.5 | v1 |
|---|---|---|---|
| **Devices:** list CoreAudio devices, open at a rate and buffer size, report latencies, device loss and change. Phil's 2i2 (2nd/3rd gen) is class compliant on macOS per Riddim D77, so no driver is needed. Recordings are placed by a loopback measurement, not by reported latency (D77) | ✓ | | |
| **Transport:** play, stop, locate, loop; tempo and meter map; metronome and count-in | ✓ | | punch |
| **Playback:** audio clips (offset, gain, fades) and MIDI clips into instruments | ✓ | crossfades, gain envelopes | |
| **Recording:** arm, input select, monitoring; incremental WAVs; latency-corrected placement; `recording_finished` | audio + MIDI | | loop takes, punch |
| **Mixing:** volume, pan, mute, solo, master | ✓ | inserts, sends, buses | sidechain, multi-out channels |
| **Plugins:** out-of-process scan with a cache; load AU, VST3 and CLAP by identity; parameters with change events; opaque state; `open_editor` into an app-supplied view; report latency | one instrument | effects, state save/restore | bus layouts (multi-out, sidechain), plugin MIDI out |
| **PDC** across the graph, with a rebuild on latency change | | ✓ | |
| **Automation:** evaluate lanes; touch and latch writes arriving as `model_changed` | | | ✓ |
| **Metering:** per-strip peaks (exists); CPU, xruns, starvation | peaks | | RMS and true peak (**not in Riddim yet**, embedding.md) |
| **Render:** deterministic offline bounce of master or stems, with progress and cancel, plus a real-time fallback | | ✓ | stems |
| **Crash isolation:** per-plugin out-of-process hosting | | | exists opt-in, with **no editor yet** |

---

## 10. Agent control (later phase; it doesn't drive scope, stack or phasing)

Per Phil's update, agent control is secondary and comes **after v1** at the earliest. The architecture is already friendly to it, because every edit is an op with an inverse (§5.3), and Riddim lists an agent layer as a later client of the same API (Riddim vision §1).

**A sketch, to refine when it's scheduled:**
- a local API, then MCP, exposing the same commands the UI uses;
- notes turned into proposed command lists that Phil applies as one undo step;
- semantic names for plugin parameters, extending quick controls.

**Prior art:**
- Logic Pro 13's "intelligent assistant" (beta; "requires an Apple Creator Studio subscription, a Mac with Apple silicon, and macOS 27 or later", [Apple](https://support.apple.com/en-us/109503));
- Ableton's Extensions SDK (public beta since 2026-06-02, [Ableton](https://www.ableton.com/en/blog/introducing-extensions-sdk));
- [ableton-mcp](https://github.com/ahujasid/ableton-mcp);
- REAPER's [ReaScript](https://www.reaper.fm/sdk/reascript/reascript.php).

---

## 11. Phasing (app milestones, against Riddim's)

| Phase | App ships | Needs from Riddim (§9.2) | Done when |
|---|---|---|---|
| **Spike** (before v0) | A bare Tauri 2 window on Phil's Mac. Riddim linked in process, `MainThread` pumped from the run loop, events forwarded. One instrument's native editor window beside the web view. An arrange-view prototype in WebGPU: 500 tracks of clips, waveform overviews, smooth zoom. A `navigator.gpu` check | what exists today | it runs on the M4 Pro with the 2i2 at 48 kHz, 128 frames: a note plays, the editor opens and closes, and the arrange view stays smooth. It also answers Q4 |
| **v0 "tape"** | Arrange view with audio and MIDI tracks. Record and play. A basic mixer strip per track. Transport, tempo, metronome. Save and load (§5). Undo from day one. Plugin window for one instrument | the v0 column (Riddim P2) | Phil records a take over an instrument (Noire once bought; a stand-in until then), saves, reopens and hears it identically. This is also Riddim's P2 criterion 1 |
| **v0.5** | Clip editing. Piano roll and quantise. Audio editor. Device chain with effect inserts. Sends and buses. Plugin manager. Offline bounce | the v0.5 column (P3) | a full demo song with the three target plugins (D78), bounced |
| **v1** | Everything in §3. Automation lanes. Multi-out and sidechain UI. Plugin MIDI routing. File drops from plugin windows. Loop and punch takes. Autosave and crash recovery. Full-screen mixer. Quick controls | the v1 column (P4) | Phil makes a track start to finish, from recording to bounce, without opening Logic |
| **v1.x** | Session (clip-launch) view. Step sequencer. Racks and macros. CLAP in the plugin manager (Riddim already hosts it on Linux). Helix, once owned | as needed | |
| **Windows** | The same app on Windows (§8.4) | WASAPI/ASIO backends, Win32 editor parenting, the bridge transport | Phil decides once the macOS app is in use and the effort can be measured, not guessed |
| **Later, deliberately** | Agent control (§10). Plugin crash isolation with editors. Time-stretch and warping. Comping. Pitch correction and ARA. Control surfaces. Video. Notation. Surround | | |

---

## 12. Risks and hard parts

- **Scale.** Logic and Live are decades of work by large teams. **The realistic target:** a focused Ableton/Logic-style DAW that one musician finishes songs in, with his own plugins. Expect months to v0 and a year or more to v1 **[estimate, not a commitment]**.
- **Nothing has run on macOS yet,** not Riddim and not a Tauri shell around it (§9). Everything about the main-thread pump, AU editors and real devices is still design. **Mitigation:** the spike (§11) runs on Phil's Mac first.
- **WebGPU in WKWebView** may set a macOS 26 floor or need a fallback renderer (§8.3, Q4).
- **A web UI that feels like Logic.** Zoom, scroll, drag, snapping, keyboard focus and menus are many small things, and in a web view each one is ours to get right. **Mitigation:** one canvas for the timeline, native menus, and an early feel test in the spike.
- **Two repos, one contract.** Riddim's API is pre-1.0, and its command JSON isn't pinned yet. **Mitigation:** a pinned Riddim version, and contract tests here on the JSON the UI uses.
- **The plugin long tail.** Three named targets are tractable; "any plugin" is not. None of the three is bought yet (Riddim D78), so real compatibility testing waits on purchases, and Phil's Mac is the lab.
- **A crash takes the session down** for in-process plugins. Bridged plugins have no editor yet. **Mitigation:** autosave and incremental recording.
- **Windows might cost more than it looks,** mostly in Riddim (§8.4). Decide on measured effort, after the macOS app is in use.
- **Why build it at all.** Live and Logic already do all of v1. The case is ownership: a DAW shaped to Phil, owned by Kamino, with agent control as a later option. It doesn't rest on doing more than they do. Worth confirming before the build (Q12).

---

## 13. Open questions for Phil

**Resolved on 21 Nov 2026:**
- **UI stack:** Tauri 2, a Rust core with a TypeScript web UI and WebGPU (§8). This was Q4.
- **Document and timeline ownership:** Riddim owns the engine model and its ops. Whiplash owns the project file, media pool, UI state and undo stack (§2, §5), aligned with Riddim's vision §1.1 and embedding.md. This was Q3. Shout if you meant otherwise.
- **Platforms:** macOS first, Windows later, Linux a by-product (§8.4).
- **Copyright owner:** Kamino Research Corporation (legal entity: Bradgate Capital Management Pte Ltd, Singapore) (§1.1).
- **Rig:** a Mac Mini M4 Pro and a Scarlett 2i2 (2nd or 3rd gen). Helix isn't owned, so it's a future test plugin (§6.1).

**Still open:**
1. **Scope of v1.** Is §3 right? Should anything move (session view, time-stretch, comping)?
2. **Audience.** Just you, or eventually others? That decides signing, installers, support, and the licence in Q3.
3. **Whiplash's licence.** Proprietary, AGPL like Riddim, or decided later? Riddim lets the same owner ship on any terms (§1.1).
4. **The macOS floor and WebGPU.** Which macOS is the Mac Mini on? Require **macOS 26** for WebGPU in WKWebView, or support 14/15 with a Canvas or WebGL fallback? Apple Silicon only? (Recommended: yes.) The spike's `navigator.gpu` check answers the first part.
5. **Which 2i2 generation?** It's printed on the unit. It isn't blocking: placement uses a loopback measurement either way (Riddim D77).
6. **When does agent control come in?** After v1, or only once the DAW is in daily use?
7. **Key commands.** Logic-compatible shortcuts, or our own set?
8. **AU or VST3 by default** when a plugin ships both?
9. **The look.** Dark only, or a light theme too? Any references beyond "Ableton x Logic, Rams"?
10. **Session view priority.** Do you jam clip-first, or is arrange-first enough for v1?
11. **Repo.** The app in a new repository (kaminocorp/whiplash-daw?), or here? This repo is the Hermes plugin, under `hejijunhao`, so a Kamino-owned repo fits the ownership decision better **[inferred]**.
12. **Go-ahead criteria.** What do you need before the app build starts? Proposed: the spike (§11) passing on your Mac.
13. **Buying the plugins.** When will Kontakt/Noire, SD3 and EZbass be bought? v0.5's "done when" needs all three.
