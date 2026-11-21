# Whiplash DAW: vision

Status: **vision draft for Phil to refine, 2026-11-21.** Nothing is built, and the build phase starts only on Phil's explicit go-ahead. Facts are cited inline and were checked on 2026-11-21. Anything marked **UNVERIFIED** wasn't confirmed from a primary source. §13 lists the open questions.

**Framing and updates from Phil (21 Nov 2026):**
- **A new project** that keeps only the name *Whiplash*. It is not the Hermes plugin in this repo and not the Digitakt web twin (PR #34). Digitakt II support is out of scope.
- **Core DAW first** (8:14 SGT). The baseline is an **Ableton/Logic twin**. Agent control is a short later-phase note (§10), and it drives none of the scope, the stack or the phasing.
- **The engine is a separate repo** (8:24 SGT): **[kaminocorp/riddim](https://github.com/kaminocorp/riddim)**, "Riddim", our own native audio engine in Rust. Its README: "playback, recording, timeline, AU/VST3 hosting". Its vision is being written there (`docs/visions/riddim.md`). This doc treats Riddim as a **dependency behind an engine API** and covers the **app**: UX, workflow, editors, mixer UI, project model and phasing. §9 says what the app needs from Riddim.

---

## 1. What it is, and what it isn't

**It is:**
- **Our own native DAW app for macOS**, with Riddim underneath. In look and workflow it is an Ableton Live and Logic Pro hybrid: Logic's arrange window, mixer and editors, with Ableton's speed, device chain and (later) clip launching.
- **Built for Phil to record and finish music** with the instruments and plugins he owns.

**It isn't:**
- **A toy or a demo.** It has to record a real session with real plugins without losing a take.
- **A browser app.** The target plugins ship as native AU and VST3 binaries (§6), which a browser can't load. Real-time audio and multi-gigabyte projects are native territory too. *A web-technology UI inside a native shell is a different question, and it is one of the UI options in §8.*
- **Not a Logic or Ableton replacement in breadth.** No notation, video, surround, bundled instrument suite, comping or Flex Time in v1 (§11).
- **Not AAX.** Every target plugin also ships AU and VST3.

**Who it's for:** Phil first, on his Mac with a Focusrite Scarlett 2i2. Anyone else comes later, if ever (Q2).

---

## 2. Architecture at a glance

```
┌──────────────────────────── Whiplash (this repo / app) ────────────────────────────┐
│  UI: arrange · editors · mixer · browser · inspector · plugin-window frames         │
│  Workflow: commands, undo, selection, keyboard, drag-and-drop, snapping             │
│  Project model (the document): tracks, clips, routing, automation, tempo map        │
│  Files: project folder, media management, autosave, plugin-state blobs (opaque)     │
└───────────────▲───────────────────────────────────────────────┬────────────────────┘
                │ events: playhead, meters, recorded clips,      │ document snapshots / diffs,
                │ plugin param changes, progress, errors         │ transport, record, render, plugin ops
┌───────────────┴──────────────────── engine API ───────────────▼────────────────────┐
│  Riddim (kaminocorp/riddim, Rust): CoreAudio I/O, real-time graph, playback,        │
│  recording, mixing, PDC, AU/VST3 hosting, plugin scan, offline render               │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

**Proposed rule:** the app owns the **document** and its undo. Riddim owns the **real-time state**: the device, the graph, plugin instances and recording buffers. The app pushes the document, and Riddim reports what happened. The README lists "timeline" under Riddim, so where exactly the timeline model lives needs agreeing with Riddim's vision (§9.1, Q3).

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
│      │  03 Gtr    ● Helix ~~~audio~~~~~~~~~                          │ samples    │
│ quick│  04 Keys   Kontakt/Noire [MIDI──]   ← automation lane ↓      │ files      │
│ ctrls│  05 Vox    ● ~~~~~audio~~~~~                                  │            │
│      │  Bus A · Bus B · Master                                       │            │
├──────┴──────────────────────────────────────────────────────────────┴────────────┤
│ DETAIL (Tab toggles): device chain ▸ [EQ][Comp][Helix][Send A]   or               │
│ editor: piano roll / audio editor for the selected clip                           │
└───────────────────────────────────────────────────────────────────────────────────┘
   X = full-screen mixer (Logic-style console)      Tab = session grid (v1.x)
```

- **Centre: the arrange window.** Tracks top to bottom, time left to right. Automation lanes fold under each track. Waveforms are drawn from precomputed overviews (§5.2) at any zoom without stalls.
- **Bottom: the detail pane.** Ableton's device chain for the selected track, or Logic's editor for the selected clip.
- **Left: the inspector.** The channel strip, plus **quick controls**: a few plugin parameters pinned per track.
- **Right: the browser** for plugins, presets, samples and project files. Drag onto a track or the empty area to create one.

### 4.3 Editors

- **Piano roll** (v0.5):
  - notes with velocity and length;
  - a velocity lane, plus CC and pitch-bend lanes;
  - scale highlighting;
  - quantise (grid, strength, swing) and humanise (timing and velocity, seeded so it's repeatable);
  - a keyboard-first edit set: nudge, length, transpose, duplicate.
- **Audio editor** (v0.5): trim, fades, gain, reverse, normalise, silence detection to split, and clip gain envelopes. Non-destructive: edits live in the document, and the source files are never modified.
- **Later:** a step sequencer (Logic-style, [Apple](https://support.apple.com/guide/logicpro/step-sequencer-overview-lgcp39acefc9/mac)), comping, warping and time-stretch (§11).

### 4.4 Mixer UI

- **A full-screen console** (`X`) with strips for audio, instrument, aux and bus channels, plus master, in track order. Folders collapse to one strip.
- **Each strip:** input, inserts (drag to reorder, alt-drag to copy), sends with levels, output, pan, fader, meter, mute, solo, record and monitor. Multi-out instrument channels group under their instrument.
- **Sidechain:** picked from a strip's plugin, listing buses and tracks.
- **Meters and gain readouts** come from Riddim's metering stream (§9.2). The UI never computes audio.

### 4.5 Aesthetic

- **A dark instrument, Dieter Rams-adjacent:** "less, but better". Near-black and graphite surfaces. One accent colour for live state: record arm, playhead, clip.
- **Tabular monospace numerals** for time and values. Colour only where it means something, such as track colour and meters.
- **No purple gradients, glassmorphism, sparkle icons or generic AI styling.**
- **Plugin windows look like their vendors made them.** We frame them and never skin them.
- **Readable across a room:** large transport numerals and a clear record state.

---

## 5. Project model (the app's document)

### 5.1 Structure

- **Project:** sample rate, tempo and time-signature map, markers and sections, and a track list.
- **Tracks:** audio, instrument, aux/bus, folder and master. Each has a channel strip: inserts as plugin slots, sends, input, output and the automation lanes.
- **Clips:**
  - an audio clip is a media reference plus offset, length, gain, fades and gain envelope;
  - a MIDI clip holds notes and CC events.

  Times are stored in musical ticks plus a sample-accurate offset where needed, so tempo edits move clips correctly.
- **Plugin slots:** the plugin's identity (format, ID, vendor, version), an opaque state blob received from Riddim, quick-control picks and the window position.
- **Every object has a stable ID,** so diffs, undo and the engine API refer to objects, never to list positions.

### 5.2 Files

- **A project folder:** a project document, `Audio/` (recordings and imports, copied in), `Overviews/` (waveform peak files), `PluginState/` (blobs) and `Autosave/`.
- **Format:** a versioned, human-diffable document (JSON or similar) with binary blobs in side files. **[proposal]** It should be readable without Riddim, so a project survives an engine change.
- **Media:** imports are copied in by default. Missing media and missing plugins show as offline placeholders, with their state preserved and never dropped.
- **Autosave** every few seconds to `Autosave/`. Crash recovery offers the newest autosave. Recorded audio is written by Riddim as it records (§9.2), so a crash loses at most the last flush.

### 5.3 Commands and undo

- **Every edit is a typed command,** whether it comes from a menu, a shortcut or a drag. Each validates first, applies to the document, and records its inverse. Gestures such as a fader drag coalesce into one undo step.
- **After a command,** the app sends Riddim the resulting change (§9.1). Undo is a command too, so Riddim needs nothing special for it.
- **Determinism:** randomised edits (humanise) take a recorded seed. The same command on the same document gives the same result.
- This is ordinary DAW architecture, and it is also what makes later agent control (§10) cheap.

---

## 6. Third-party plugins (hard requirement)

### 6.1 Phil's target products (checked 2026-11-21)

| Product | Mac formats | Apple Silicon | Min macOS | Licensing (host involvement) |
|---|---|---|---|---|
| **Kontakt 8 Player** (free) + **Noire** (paid library) | AU, VST3, AAX, standalone ([NI specs, search excerpt](https://www.native-instruments.com/en/products/komplete/samplers/kontakt-8/specifications/)) | yes | 14, 15, 26 per an NI excerpt; another excerpt says 15, 26, 27 (**UNVERIFIED**) | Native Access with an NI account. The plugin itself shows "not activated" ([NI KB](https://support.native-instruments.com/support/solutions/articles/69000879750-kontakt-error-message-not-activated-or-full-kontakt-required-)). The host does nothing. Noire runs in the free Player per an NI excerpt ([NI](https://www.native-instruments.com/en/products/komplete/keys/noire/), **UNVERIFIED** full page) |
| **Superior Drummer 3** (3.4.4, 2026-03-26) | AU, VST3 (since 3.3.0), AAX, standalone ([release notes](https://www.toontrack.com/release-notes/superior-drummer-3/)) | native since 3.2.5 | 10.13 | Toontrack Product Manager ([Toontrack](https://www.toontrack.com/product-manager/)). The host does nothing |
| **EZbass** (1.3.4, 2026-05-29) | AU, VST3, AAX, standalone ([release notes](https://toontrack.com/release-notes/release-notes-ezbass)) | native since 1.1.0 | 10.13 | Product Manager plus an account. The host does nothing |
| **Helix Stadium Native** (launched 2026-08-04) | VST3, AU, AAX; no standalone ([Line 6 KB](https://kb.line6.com/helix-stadium-native-faq)) | yes per reviews (**UNVERIFIED**) | 14 per reviews (**UNVERIFIED**) | A Line 6 account, up to four computers ([Line 6 KB](https://kb.line6.com/helix-stadium-native-faq)). The host does nothing |

**Copy protection is handled inside each plugin and its vendor app.** The host only has to stay out of the way: no blocking of first-run dialogs or network access, and no killing a slow load.

### 6.2 What these plugins need (app side and engine side)

| Need | Source | App | Riddim (§9.2) |
|---|---|---|---|
| **Multi-output instruments.** Kontakt's AU "16xStereo" variant (NI manual excerpt, **UNVERIFIED** full page). SD3's 16 stereo outs ([Toontrack](https://www.toontrack.com/product/superior-drummer-3/)) | | creates mixer channels per output bus, grouped under the instrument | negotiates bus layouts, exposes each output as a routable channel |
| **Sidechain input** (Helix dynamics and filters) | [Line 6 KB](https://kb.line6.com/helix-stadium-native-faq) | a sidechain picker on the strip | sidechain bus routing |
| **Plugin MIDI output** (SD3, EZbass) | [SD3](https://www.toontrack.com/product/superior-drummer-3/), [EZbass notes](https://toontrack.com/release-notes/release-notes-ezbass) | routes it to other tracks, or records it | delivers plugin MIDI out as an event stream |
| **File drops from a plugin window onto the timeline.** SD3 writes a temporary MIDI file and starts an OS drag ([SD3 3.2.5 notes](https://www.toontrack.com/release-notes/superior-drummer-3/)). EZbass "may not work in some hosts" ([Toontrack](https://www.toontrack.com/product/ezbass/)) | | **the app's** drop target accepts OS file drags from any window, plugin windows included | none |
| **Host playhead** (SD3 "Follow Host") | [Toontrack forum, staff](https://www.toontrack.com/forums/topic/superior-drummer-3-are-tempo-and-time-signature-synchronized-bidirectional-in-daw/) | tempo map in the document | supplies tempo, time signature, position and transport to plugins |
| **Large memory and slow loads** (an SD3 preset takes 3.7-18 GB) | [Toontrack FAQ](https://www.toontrack.com/faq/how-much-ram-does-a-superior-library-or-sdx-use/) | progress UI, so the project stays usable while a plugin loads | asynchronous instantiation and state restore, never on the audio or UI thread |
| **Latency** (amp sims, look-ahead) | | shows a strip's latency, plus a low-latency monitoring toggle | reports it and compensates (PDC) |

### 6.3 Plugin UX in the app

- **Plugin manager:**
  - runs a scan through Riddim in the background, with progress, and never blocks;
  - lists formats, vendors and failures, with a blocklist and "rescan";
  - Phil picks AU or VST3 when a plugin ships both (Q8).
- **Plugin windows:** each plugin's own editor in a native window we frame, with title, bypass, preset menu, A/B and latency readout. Windows float and remember their position per instance.
- **Missing or crashed plugins:** an offline placeholder that keeps its state. v1 shows a crash clearly and recovers from autosave. Running plugins in a separate process to survive a crash is an engine capability for v2 (§9.2).

---

## 7. Workflow details that make or break it

- **Never block the UI:** loading a project, a plugin, a scan, a bounce. Everything slow shows progress and can be cancelled.
- **Recording must feel safe:** a clear arm and record state, input meters before you press record, the disk space left, and every take kept (the takes stack in v1, comping comes later).
- **Keyboard-first:** every common action has a shortcut. A Logic-compatible key set is an option (Q7).
- **Snapping and zoom:** smooth, fast, and predictable to the sample.
- **Low-latency monitoring** while recording: high-latency plugins are bypassed or flagged on armed tracks.

---

## 8. UI stack options (open)

The app sits on top of Riddim (Rust). Criteria:
- Logic-level polish on macOS;
- a timeline that handles thousands of clips and waveforms with smooth zoom;
- **hosting plugin editors**, which are native NSViews (**[inferred]**: standard for AU Cocoa views and VST3 `IPlugView` on macOS);
- accessibility;
- iteration speed;
- Windows later;
- licence;
- the cost of the boundary to Riddim.

| Option | Boundary to Riddim | For | Against |
|---|---|---|---|
| **A. Native Swift: AppKit + SwiftUI, Metal for the timeline** | a C ABI ([cbindgen](https://github.com/mozilla/cbindgen), MPL-2.0) or generated bindings ([UniFFI](https://github.com/mozilla/uniffi-rs), MPL-2.0; [swift-bridge](https://github.com/chinedufn/swift-bridge), MIT/Apache) | the most Mac-native feel, accessibility, text and menus. Plugin NSViews drop straight in | macOS only, so Windows means a second UI. Two languages |
| **B. Rust-native UI:** [egui](https://github.com/emilk/egui) 0.37 (MIT/Apache), [iced](https://github.com/iced-rs/iced) 0.14 (MIT), [Slint](https://github.com/slint-ui/slint) 1.19 ([royalty-free licence for proprietary desktop apps, or GPLv3, or commercial](https://github.com/slint-ui/slint/blob/master/LICENSE.md)), [vizia](https://github.com/vizia/vizia) 0.4 (MIT, from audio-plugin UI work); earlier-stage: [Xilem](https://github.com/linebender/xilem), [Floem](https://github.com/lapce/floem) | none: same language and process as Riddim | one language, cross-platform | **[inferred]** less mature for a large pro app: accessibility, text, native menus and polish need our work. Embedding plugin NSViews needs native window handles ([raw-window-handle](https://github.com/rust-windowing/raw-window-handle)). Most are pre-1.0 |
| **C. Web UI in a Rust shell:** [Tauri](https://github.com/tauri-apps/tauri) 2.x (MIT/Apache), with the system webview | Riddim in-process in the Rust core; the UI talks to it over Tauri IPC | fast iteration, rich layout, people and agents write it quickly, cross-platform | **[inferred]** a timeline at scale needs canvas or WebGPU work. Plugin editors can't live in the webview, so they need separate native windows (they float anyway). Doesn't feel native unless worked hard |
| **D. Qt / QML** via [cxx-qt](https://github.com/KDAB/cxx-qt) (MIT/Apache bindings) | Rust ↔ Qt through cxx-qt | a mature desktop toolkit, cross-platform. Zrythm uses Qt/QML ([repo](https://github.com/zrythm/zrythm)) | Qt's licence is LGPLv3 or commercial (**UNVERIFIED** current terms). It doesn't look Mac-native by default, and adds a third language (QML) |

**Leaning, not a decision:** A for a Mac-first, Logic-polish goal, accepting that Windows would need a second UI. C if iteration speed and an eventual Windows build matter more.

**Proposed spike before choosing:** build the arrange view (500 tracks of clips, waveform overviews, smooth zoom, one hosted plugin window) in A and C, against a stub of the Riddim API.

---

## 9. What the DAW needs from Riddim

**Decision note.** Phil chose (21 Nov 2026) to build our own engine, Riddim, in Rust rather than adopt Tracktion Engine, JUCE or Ardour, while borrowing their ideas. The previous draft of this doc recommended Tracktion Engine + JUCE. That analysis is superseded, and its useful facts belong in Riddim's vision:
- the VST3 SDK has been MIT since 3.8.0 ([vst3sdk](https://github.com/steinbergmedia/vst3sdk));
- Rust hosting pieces: [`vst3`](https://github.com/coupler-rs/vst3-rs), [clack](https://github.com/prokopyl/clack), and [rack](https://github.com/sinkingsugar/rack) for AU (self-described production-ready, **UNVERIFIED**);
- AUv3 runs out of process ([Apple](https://developer.apple.com/documentation/audiotoolbox/migrating-your-audio-unit-host-to-the-auv3-api));
- Rosetta remains general-purpose only "through macOS 27" ([Apple](https://developer.apple.com/documentation/apple-silicon/about-the-rosetta-translation-environment));
- CoreAudio audio workgroups (macOS 11+, [Apple](https://developer.apple.com/documentation/audiotoolbox/understanding-audio-workgroups)).

The list below is **the app's side of the contract**. To be reconciled with `docs/visions/riddim.md` once it exists.

### 9.1 Shape of the API

- **In-process,** as a Rust crate. If the UI isn't Rust (§8 options A and D), a thin binding layer on top.
- **The document flows one way.** The app sends Riddim the project state: a full snapshot at load, then **transactional diffs** keyed by object ID. Riddim applies each diff atomically at a buffer boundary, glitch-free during playback. **[proposal]** Open: if Riddim keeps its own timeline model, the diffs map onto it (Q3).
- **Threading contract:**
  - every API call is safe from the UI or worker threads, and returns quickly;
  - slow work (plugin load, state restore, scan, render) returns a handle and reports progress and completion as events;
  - the app never touches the audio thread.
- **Events back to the app,** through a lock-free queue the UI drains each frame:
  - playhead (samples plus musical time);
  - meters, CPU and dropouts;
  - recorded clips;
  - plugin parameter changes (for automation write and undo);
  - plugin latency changes, errors and device changes.
- **A headless and fake-device mode,** so the app's tests run in CI without audio hardware.
- **A versioned API** (semver), with contract tests in this repo against a pinned Riddim version.

### 9.2 Capabilities, by phase

| Capability | v0 | v0.5 | v1 |
|---|---|---|---|
| **Devices:** list CoreAudio devices, open at a sample rate and buffer size, report input, output and safety latency, report device loss and change. The Scarlett range is class compliant ([Focusrite](https://us.focusrite.com/articles/whats-the-best-interface-for-mac/); 4th Gen 2i2 **UNVERIFIED**) | ✓ | | |
| **Transport:** play, stop, locate, loop; tempo and time-signature map; metronome and count-in | ✓ | | punch |
| **Playback:** audio clips (offset, gain, fades) and MIDI clips into instruments | ✓ | crossfades, gain envelopes | |
| **Recording:** arm, input select, monitoring; write files incrementally into the folder the app names; report each recorded clip with its latency-corrected start | audio + MIDI | | loop takes, punch |
| **Mixing:** volume, pan, mute, solo, master | ✓ | inserts, sends, buses | sidechain, multi-out channels |
| **Plugins:** scan in a child process with a cache; load AU and VST3 by identity; parameter list (ID, name, unit, range) with get/set/change events; opaque state get/set; open an editor in a native view the app provides; report latency | one instrument | effects, state save/restore | bus layouts (multi-out, sidechain), plugin MIDI out |
| **PDC** across the graph, with a rebuild on latency change | | ✓ | |
| **Automation:** evaluate parameter lanes; touch and latch writes from UI gestures and plugin changes | | | ✓ |
| **Metering:** peak and RMS per channel; CPU, dropout and disk stats | basic | per channel | |
| **Render:** offline bounce of the master or stems to a file, with progress and cancel, and a real-time fallback; deterministic output | | ✓ | stems |
| **Crash isolation:** run plugins out of process | | | later (v2) |

---

## 10. Agent control (later phase; it doesn't drive scope, stack or phasing)

Per Phil's update, agent control is secondary and comes **after v1** at the earliest. The architecture is already friendly to it, because every edit is an undoable command (§5.3) and the document is separate from the engine (§2).

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
| **v0 "tape"** | Arrange view with audio and MIDI tracks. Record and play. A basic mixer strip per track. Transport, tempo, metronome. Save and load (§5). Undo from day one. Plugin window for one instrument | the v0 column | Phil records a take over Noire, saves, reopens and hears it identically |
| **v0.5** | Clip editing. Piano roll and quantise. Audio editor. Device chain with effect inserts. Sends and buses. Plugin manager. Offline bounce | the v0.5 column | a full demo song with all four target plugins, bounced |
| **v1** | Everything in §3. Automation lanes. Multi-out and sidechain UI. Plugin MIDI routing. File drops from plugin windows. Loop and punch takes. Autosave and crash recovery. Full-screen mixer. Quick controls | the v1 column | Phil makes a track start to finish, from recording to bounce, without opening Logic |
| **v1.x** | Session (clip-launch) view. Step sequencer. Racks and macros. CLAP (if Riddim adds it) | as needed | |
| **Later, deliberately** | Agent control (§10). Plugin crash isolation (with Riddim). Time-stretch and warping. Comping. Pitch correction and ARA. Control surfaces. Windows. Video. Notation. Surround | | |

---

## 12. Risks and hard parts

- **Scale.** Logic and Live are decades of work by large teams. **The realistic target:** a focused Ableton/Logic-style DAW that one musician finishes songs in, with his own plugins. Expect months to v0 and a year or more to v1 **[estimate, not a commitment]**.
- **The engine is on the critical path.** Riddim is a new Rust engine. Every app phase waits on its column in §9.2, and AU hosting from Rust is the least proven piece (**UNVERIFIED** maturity of `rack`). **Mitigation:** build the app against a stub engine with the same API, so UI work isn't blocked.
- **Two repos, one contract.** API churn between Whiplash and Riddim. **Mitigation:** a versioned API, contract tests here, and an agreed owner for the document/timeline boundary (Q3).
- **The plugin long tail.** Four named targets are tractable; "any plugin" is not. Testing licensed plugins needs real licences on a real Mac, so Phil's Mac is the compatibility lab.
- **A crash takes the session down** until Riddim isolates plugins. **Mitigation:** autosave and incremental recording.
- **The UI stack** (§8) decides how much polish costs. Choosing late, after the spike, is cheaper than switching.
- **UI polish is the long pole.** Logic-level feel (zoom, scroll, drag, snapping) is many small things.
- **Why build it at all.** Live and Logic already do all of v1. The case is ownership: a DAW shaped to Phil, with agent control as a later option. It doesn't rest on doing more than they do. Worth confirming before the build (Q12).

---

## 13. Open questions for Phil

1. **Scope of v1.** Is §3 right? Should anything move (session view, time-stretch, comping)?
2. **Audience.** Just you, or eventually others? That decides signing, installers, support and the UI-stack licence (for example Slint or Qt).
3. **Document and timeline ownership.** The app owns the document and Riddim mirrors it (proposed, §2, §9.1), or Riddim owns the timeline model and the app is a view? Decide together with Riddim's vision.
4. **The UI stack** (§8). Run the A-vs-C spike? Any strong preference (Swift, Rust or web)?
5. **The macOS floor.** 14+ (matching Kontakt and Helix) or 15+? Apple Silicon only? (Recommended: yes.)
6. **When does agent control come in?** After v1, or only once the DAW is in daily use?
7. **Key commands.** Logic-compatible shortcuts, or our own set?
8. **AU or VST3 by default** when a plugin ships both?
9. **The look.** Dark only, or a light theme too? Any references beyond "Ableton x Logic, Rams"?
10. **Session view priority.** Do you jam clip-first, or is arrange-first enough for v1?
11. **Repo.** The app in a new repository (kaminocorp/whiplash-daw?), or here? This repo is the Hermes plugin.
12. **Go-ahead criteria.** What do you need before the build starts? Proposed first proofs: Riddim hosting Noire and recording a take, and the UI spike (§8).
