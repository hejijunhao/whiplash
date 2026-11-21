# Whiplash DAW: vision

Status: **vision draft for Phil to refine, 2026-11-21.** Nothing is built, and the build phase starts only on Phil's explicit go-ahead. Facts are cited inline and were checked on 2026-11-21. Anything marked **UNVERIFIED** wasn't confirmed from a primary source. §10 lists the open questions.

**Framing (Phil, 21 Nov 2026):** this is a new project that keeps only the name *Whiplash*.
- It is not the Hermes plugin in this repo and not the Digitakt web twin (PR #34).
- Digitakt II support is out of scope for now.
- Nothing here builds on the existing plugin code.

**Update (Phil, 21 Nov 2026, 8:14 SGT):** the baseline is an **Ableton/Logic twin: core DAW first.** Agent control is secondary. It is a short later-phase note (§5), and it drives none of the scope, the stack choice or the v0/v1 phasing.

---

## 1. What it is, and what it isn't

**It is:**
- **Our own native DAW for macOS.** In look and workflow it is an Ableton Live and Logic Pro hybrid: Logic's arrange window, mixer and editors, with Ableton's speed, device chain and (later) clip launching.
- **Built for Phil to record and finish music** with the instruments and plugins he owns.
- **A complete core DAW before anything else.** Agent control may come later (§5), and nothing in v0 or v1 waits on it.

**It isn't:**
- **A toy or a demo.** It has to record a real session with real plugins without losing a take.
- **A web app.** Native wins, for three reasons:
  - **Plugin hosting.** Kontakt, Superior Drummer, EZbass and Helix ship as AU, VST3 and AAX binaries (§4). A browser can't load them, so a web DAW can't host any of them.
  - **Real-time audio.** CoreAudio at 64-128-sample buffers, with real-time threads joined to the device's audio workgroup (macOS 11+, [Apple](https://developer.apple.com/documentation/audiotoolbox/understanding-audio-workgroups)). A browser's audio stack is a worse foundation for 30 plugin instances at low latency **[inferred]**.
  - **Files.** Multi-gigabyte projects, sample streaming and recording to disk.
- **Not a Logic or Ableton replacement in breadth.** No notation, no video, no surround or Atmos, no bundled instrument suite, no comping or Flex Time in v1 (§8).
- **Not AAX.** AAX is for Pro Tools. Every target plugin also ships AU and VST3.

**Who it's for:** Phil first, on his Mac with a Focusrite Scarlett 2i2. Anyone else comes later, if ever (Q2).

---

## 2. Core functionality (v1 must-haves)

| Area | v1 scope |
|---|---|
| **Recording** | Mono and stereo audio from the interface's inputs. Input monitoring. Arm several tracks at once. Loop and punch recording, keeping takes as separate clips (no comping UI in v1). Latency-corrected placement. MIDI recording with overdub and replace |
| **Audio tracks** | Clips referencing audio files. Gain, fades and crossfades. Non-destructive |
| **MIDI and instrument tracks** | One instrument plugin (AU/VST3) per track plus an effect chain. Multi-output instruments routed to their own mixer channels. Plugin MIDI output routable to other tracks (§4.2) |
| **Arrangement timeline** | Tracks and clips on bars and beats. A tempo and time-signature map. Markers and sections. Snap and grid. Track folders and stacks |
| **Mixer** | Channel strips with an inserts chain, sends (pre/post), buses, master, volume, pan, mute and solo. Sidechain inputs (§4.2). Peak and RMS meters |
| **Transport** | Play, stop, record, loop range, punch in/out, metronome with count-in, tap and typed tempo, follow playhead |
| **Editing** | Clip move, trim, split, duplicate and loop. Piano roll (notes, velocity, length, CC lanes). Audio clip edits (trim, fade, gain, reverse, normalise; no time-stretch in v1). Quantise with strength and swing. Humanise |
| **Automation** | Per-parameter lanes for track and plugin parameters. Read, write, touch and latch modes. Breakpoint editing |
| **Project** | Save, load and autosave. A project folder with audio files, collected and self-contained. Plugin state stored per instance (§4.3). Crash recovery from autosave |
| **Export** | Offline bounce of the master or stems to WAV/AIFF at the project rate. Real-time bounce as a fallback for plugins that misbehave offline (§7.5) |
| **Undo** | Unlimited, one history for every edit. Every edit is an undoable command internally, which is standard DAW design (Tracktion Engine's `Edit` owns a `juce::UndoManager`, [tracktion_Edit.h](https://github.com/Tracktion/tracktion_engine/blob/develop/modules/tracktion_engine/model/edit/tracktion_Edit.h)) |

---

## 3. Look and workflow

### 3.1 What comes from where

| From **Ableton Live** (12.4.16 current; Live 13 announced for early 2027, [ableton.com](https://www.ableton.com/en/live/)) | From **Logic Pro** (13.0, 2026-11-06, [Apple](https://support.apple.com/en-us/109503)) |
|---|---|
| **Speed:** single window, few modal dialogs, keyboard-first, drag-and-drop everywhere | **The arrange window** as the main canvas ([Tracks area](https://support.apple.com/guide/logicpro/tracks-area-overview-lgcpf7c0d5d8/mac)) |
| **The device chain:** a horizontal strip of devices along the bottom, with instant add and reorder ([Live manual](https://www.ableton.com/en/live-manual/12/working-with-instruments-and-effects/)) | **The mixer:** a full console with sends, buses, folders and colour, and the polish to work in for hours ([Mixer](https://support.apple.com/guide/logicpro/mixing-overview-lgcpbc219818/mac)) |
| **Racks and macros,** later ([Racks](https://www.ableton.com/en/live-manual/12/instrument-drum-and-effect-racks/)) | **Editors** that dock in a bottom pane: piano roll, audio editor, later a step sequencer ([Piano Roll](https://support.apple.com/guide/logicpro/overview-lgcpa9111b0d/mac)) |
| **Session view** (clip launching), in v1.x ([Session View](https://www.ableton.com/en/live-manual/12/session-view/)) | **The inspector:** the selected track's channel strip at the left. **Smart Controls** become our quick controls (§3.2) |
| **The browser:** one searchable place for instruments, plugins, presets and samples | **Multi-output instrument handling** ([Logic guide](https://support.apple.com/guide/logicpro/use-multi-output-instruments-lgcp8e887f45/mac)) |

### 3.2 Proposed layout (one window)

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

- **Centre:** the arrange window. Tracks run top to bottom and time left to right, with automation lanes folding under each track.
- **Bottom:** the detail pane, Ableton's device chain for the selected track or Logic's editor for the selected clip.
- **Left:** the inspector: the channel strip, plus quick controls, a handful of pinned plugin parameters per track in the spirit of Logic's Smart Controls ([Apple](https://support.apple.com/guide/logicpro/smart-controls-overview-lgcp7e59f24b/mac)).
- **Right:** the browser.
- **Mixer:** a full-screen Logic-style console (`X`).
- **Session grid:** comes later, sharing the same tracks, as in Live.

### 3.3 Aesthetic

- **A dark instrument, Dieter Rams-adjacent:** "less, but better". Near-black and graphite surfaces. One accent colour for live state: record arm, playhead, clip.
- **Tabular monospace numerals** for time and values.
- **The usual hierarchy:** colour only where it means something, such as track colour and meters. No decoration.
- **No purple gradients, glassmorphism, sparkle icons or generic AI styling.**
- **Plugin windows look like their vendors made them.** We frame them and never skin them.
- **Readable at a glance across a room:** large transport numerals and a clear record state.

---

## 4. Third-party plugins (hard requirement)

### 4.1 Phil's target products (checked 2026-11-21)

| Product | Mac formats | Apple Silicon | Min macOS | Licensing (host involvement) |
|---|---|---|---|---|
| **Kontakt 8 Player** (free) + **Noire** (paid library) | AU, VST3, AAX, standalone ([NI specs, from a search excerpt](https://www.native-instruments.com/en/products/komplete/samplers/kontakt-8/specifications/)) | yes | 14, 15, 26 per an NI excerpt; another excerpt says 15, 26, 27 (**UNVERIFIED**) | Native Access with an NI account. The plugin itself shows "not activated" ([NI KB](https://support.native-instruments.com/support/solutions/articles/69000879750-kontakt-error-message-not-activated-or-full-kontakt-required-)). The host does nothing. Noire runs in the free Player, per an NI page excerpt ([NI](https://www.native-instruments.com/en/products/komplete/keys/noire/), **UNVERIFIED** full page) |
| **Superior Drummer 3** (3.4.4, 2026-03-26) | AU, VST3 (since 3.3.0), AAX, standalone ([release notes](https://www.toontrack.com/release-notes/superior-drummer-3/)) | native since 3.2.5 | 10.13 | Toontrack Product Manager ([Toontrack](https://www.toontrack.com/product-manager/)). The host does nothing |
| **EZbass** (1.3.4, 2026-05-29) | AU, VST3, AAX, standalone ([release notes](https://toontrack.com/release-notes/release-notes-ezbass)) | native since 1.1.0 | 10.13 | Product Manager plus an account. The host does nothing |
| **Helix Stadium Native** (launched 2026-08-04) | VST3, AU, AAX; **no standalone** ([Line 6 KB](https://kb.line6.com/helix-stadium-native-faq)) | yes per reviews (**UNVERIFIED** from Line 6) | 14 per reviews (**UNVERIFIED**) | A Line 6 account, up to four computers ([Line 6 KB](https://kb.line6.com/helix-stadium-native-faq)). The host does nothing |

**Copy protection is handled inside each plugin and its vendor app.** The host's only duty is to stay out of the way:
- don't block a plugin's network access or its first-run dialogs;
- don't kill a slow instantiation.

### 4.2 Host features these products need

- **Multi-output instruments:**
  - Kontakt in AU hosts offers a "16xStereo" multi-out variant, capped at 16 channels in AU/AAX and 64 mono in VST3 (NI manual excerpt, **UNVERIFIED** full page).
  - Superior Drummer 3 has 16 stereo outputs ([Toontrack](https://www.toontrack.com/product/superior-drummer-3/)).
  - So the host must negotiate output buses (AU bus layouts, VST3 bus arrangements) and create mixer channels for them.
- **Sidechain input** on effects: Helix's dynamics and some filter blocks ([Line 6 KB](https://kb.line6.com/helix-stadium-native-faq)).
- **Plugin MIDI output** routed to other tracks: SD3 and EZbass.
- **OS file drops from a plugin window onto the timeline.** SD3 writes a temporary MIDI file and starts a drag ([SD3 3.2.5 notes](https://www.toontrack.com/release-notes/superior-drummer-3/)). EZbass's vendor warns that MIDI drag-and-drop "may not work in some hosts" ([Toontrack](https://www.toontrack.com/product/ezbass/)).
- **The host playhead:** tempo, time signature, position and transport. SD3's "Follow Host" uses it ([Toontrack forum, staff](https://www.toontrack.com/forums/topic/superior-drummer-3-are-tempo-and-time-signature-synchronized-bidirectional-in-daw/)).
- **Large memory and slow loads.** One SD3 preset ranges from 3.7 GB to 18 GB with full bleed ([Toontrack FAQ](https://www.toontrack.com/faq/how-much-ram-does-a-superior-library-or-sdx-use/)). Instantiation and state restore must be asynchronous with progress, and must never block the audio or UI thread.
- **Latency reporting and delay compensation** for amp sims and look-ahead dynamics (§7.4). Helix's reported latency is **UNVERIFIED**.

### 4.3 How hosting works

- **Formats:**
  - **AU** (macOS): AUv2 via AudioToolbox and AUv3 via `AVAudioUnit`. Apple calls AUv2 "maintenance mode" and recommends AUv3 for new development ([Apple](https://developer.apple.com/documentation/audiotoolbox/hosting-audio-unit-extensions-using-the-auv2-api)). Most commercial instruments, these four included, still ship AUv2 **[inferred]**.
  - **VST3:** the SDK is **MIT-licensed since 3.8.0 (2025-10-20)**. "Licensing under GPLv3 and the Steinberg proprietary license is no longer available" ([vst3sdk](https://github.com/steinbergmedia/vst3sdk), [Steinberg](https://steinbergmedia.github.io/vst3_dev_portal/pages/VST+3+Licensing/Index.html)). Current version: 3.8.1 (2026-08-11). The VST name and logo are optional and covered by trademark rules. VST2 has been discontinued since 2018 ([Steinberg forum](https://forums.steinberg.net/t/vst-2-sdk-discontinued/201774)), so there is no VST2.
  - **CLAP:** MIT ([free-audio/clap](https://github.com/free-audio/clap)), with an MIT host-side SDK ([clap-helpers](https://github.com/free-audio/clap-helpers)). Bitwig, REAPER, FL Studio and Studio One support it, but neither Logic nor Live does ([clapdb](https://clapdb.tech/category/hostsdaws)). Optional, after v1.
- **Scanning:** in a child process, so a plugin that crashes on load doesn't take the DAW with it. JUCE's AudioPluginHost and Tracktion Engine both do this ([JUCE](https://github.com/juce-framework/JUCE/blob/master/extras/AudioPluginHost/Source/UI/MainHostWindow.cpp), [Tracktion](https://github.com/Tracktion/tracktion_engine/blob/develop/modules/tracktion_engine/plugins/tracktion_PluginScanHelpers.h)). Results are cached by path, version and modified time, with a blocklist for repeat offenders.
- **GUI windows:** each plugin's own view is hosted in a native window we frame: title, bypass, preset and A/B. Windows float above the main window and remember their position per instance.
- **State:** the VST3 component and controller state, and the AU `ClassInfo` / full-state property, are stored opaquely per instance in the project, alongside the plugin's identity and version. A plugin that is missing on load keeps its state and shows as an offline placeholder, never silently dropped.
- **Crash isolation:**
  - **AUv3** runs out of process by default, for free ([Apple](https://developer.apple.com/documentation/audiotoolbox/migrating-your-audio-unit-host-to-the-auv3-api)).
  - **AUv2 and VST3** run in our process unless we build a bridge. Bitwig offers five sandbox modes, from in-engine to each instance alone ([Bitwig](https://bitwig.com/userguide/latest/vst_plug-in_handling_and_options)). REAPER runs a plugin in a shared or dedicated bridge process ([REAPER guide](https://www.reaper.fm/userguide/ReaperUserGuide786c.pdf), p. 339).
  - **Neither JUCE nor Tracktion Engine ships a runtime sandbox** **[source: code search, see §6]**.
  - **v1 plan:** in-process hosting, plus autosave every few seconds and crash recovery. **A bridge process is v2** (§8): shared-memory audio and one-block IPC per process, at real CPU and latency cost.
- **Rosetta:** an Intel-only AU can be loaded through Apple's out-of-process helper (`AUHostingServiceXPC_arrow`) ([Apple](https://developer.apple.com/documentation/audiotoolbox/debugging-out-of-process-audio-units-on-apple-silicon)). Rosetta stays a general-purpose tool only "through macOS 27" ([Apple](https://developer.apple.com/documentation/apple-silicon/about-the-rosetta-translation-environment)), so we target **arm64-native plugins only**. All four targets are native.

---

## 5. Agent control (later phase; it doesn't drive scope, stack or phasing)

Per Phil's update of 21 Nov, agent control is **secondary** and comes **after v1** at the earliest (§8). Nothing in v0 or v1 depends on it. The only requirement now is to keep the architecture friendly to it, and a good DAW is already built that way:
- **Every edit is an undoable command.** We need that for undo regardless (§2).
- **The project model is separate from the audio engine** (§7.1).

**What it could become later, as a sketch to refine when it's scheduled:**
- **A local API.** Then an MCP server, exposing the same commands the UI uses, with read-only queries for project state.
- **Notes to changes.** Phil writes a note ("the chorus bass is muddy"), an agent proposes a list of commands, and Phil applies it as one undo step or discards it.
- **Parameter maps.** Semantic names for third-party plugin parameters, so an agent can drive them. This extends the quick controls in §3.2.

**Prior art, for when it's scheduled:**
- Logic Pro 13's "intelligent assistant" (beta; "requires an Apple Creator Studio subscription, a Mac with Apple silicon, and macOS 27 or later", [Apple](https://support.apple.com/en-us/109503)).
- Ableton's Extensions SDK (public beta since 2026-06-02, [Ableton](https://www.ableton.com/en/blog/introducing-extensions-sdk)) and the community [ableton-mcp](https://github.com/ahujasid/ableton-mcp).
- REAPER's [ReaScript](https://www.reaper.fm/sdk/reascript/reascript.php).

---

## 6. Technical foundations

| Option | What it gives | Licence (checked 2026-11-21) | Fit |
|---|---|---|---|
| **Tracktion Engine + JUCE** (C++20) | **The most DAW for the least work.** From Tracktion Engine ([FEATURES.md](https://github.com/Tracktion/tracktion_engine/blob/develop/FEATURES.md)): an Edit model with audio, MIDI and step clips; clip launching and scenes; tempo, time-signature and key curves; automation; PDC; background rendering; MIDI clock; and AU/VST3/LV2 hosting through JUCE. It is the engine behind Tracktion Waveform. Last commit 2026-11-20 ([repo](https://github.com/Tracktion/tracktion_engine)). It has no UI | **Tracktion:** GPL-3.0-or-later or commercial. Personal is free up to $50k revenue with branding; Indie is $35/seat/month up to $200k ([engine.tracktion.com](https://engine.tracktion.com/)). **JUCE 9** (9.0.6, 2026-11-19): AGPLv3 or commercial. Starter is free up to $20k; Indie is $800 perpetual up to $300k; Pro is $3,500 ([juce.com](https://juce.com/get-juce/)). No splash screen since JUCE 8. **Whether Tracktion commercial also needs JUCE commercial: UNVERIFIED (we assume yes).** **JUCE EULA clause 1.12, "may not … Distribute Products that create other Products", needs a legal read for a DAW** | **Recommended** |
| **JUCE alone** | the same hosting, audio I/O and UI toolkit. We write the edit model, timeline, automation, PDC graph and rendering ourselves | JUCE as above | more control, many more months of work |
| **Ardour / libardour** (C++) | the most complete open DAW back end. AU, VST3, LV2 and VST2 on macOS, out-of-process scanning, and no CLAP ("no plans", [tracker 9417](https://tracker.ardour.org/view.php?id=9417)). 9.10 released 2026-11-10 | **GPLv2+** ([COPYING](https://github.com/Ardour/ardour/blob/master/COPYING)). The developers' stated position (2002) is that linking libardour makes your app GPL ([linux-audio-dev](https://lists.linuxaudio.org/archives/linux-audio-dev/2002-November/001137.html)). Harrison Mixbus is a commercial precedent built on GPL source ([Harrison](https://rsrc.harrisonconsoles.com/mixbus/mixbus-live-manual/topic/mixbus-license-terms-and-gpl-compliance)) | strong engine, but GPL for good and a GTK UI we'd fight to restyle |
| **Rust from scratch** | memory safety and long-term ownership. Pieces: cpal for I/O (Apache-2.0, [repo](https://github.com/RustAudio/cpal)); clack-host for CLAP hosting (MIT/Apache, [repo](https://github.com/prokopyl/clack)); the `vst3` crate (MIT/Apache, bindings from the now-MIT SDK headers, [repo](https://github.com/coupler-rs/vst3-rs)); `rack` for AU hosting (MIT/Apache, which calls itself production-ready, **UNVERIFIED**, [repo](https://github.com/sinkingsugar/rack)). nih-plug is for *making* plugins, not hosting them ([repo](https://github.com/robbert-vdh/nih-plug)). The notable Rust DAW, Meadowlark, is effectively dormant ([Codeberg](https://codeberg.org/Meadowlark/Meadowlark)) | permissive throughout | everything above the I/O and format bindings is ours: years before it records a song. AU hosting is the weakest link |
| **Others** | Zrythm (AGPLv3; C++23, Qt/QML **and JUCE**; optional plugin bridging, [repo](https://github.com/zrythm/zrythm)). Qtractor (GPL-2.0). LMMS (GPL-2.0; last stable release 2020). I/O-only libraries: miniaudio, PortAudio, RtAudio (permissive) | — | reference reading, not a base |

**Recommendation: Tracktion Engine + JUCE 9, macOS (arm64) first.**
- **It reaches a usable v0 soonest.** The hard, boring parts already exist and ship in a commercial DAW: the edit model, tempo map, clips, automation, PDC and offline render. That frees our effort for the workflow and the UI, which are what make this ours.
- **It meets the plugin requirement out of the box.** AU and VST3 hosting through JUCE is mature, and JUCE 9.0.5 still fixes VST3 hosting details ([CHANGE_LIST](https://github.com/juce-framework/JUCE/blob/master/CHANGE_LIST.md)).
- **The licences are fine for personal use.** While Whiplash is Phil's own tool and isn't distributed, the GPL and AGPL options impose nothing, because their obligations start on distribution (or network use, for AGPL) **[inferred; standard reading]**. Going commercial later means paying for Tracktion and JUCE, budgeted from the tiers above (Q3).
- **The costs:**
  - **C++ real-time code:** a stricter review burden on agent-written code (§9).
  - **The UI:** JUCE's toolkit is capable but not native AppKit, so reaching Logic-level polish is our work.
  - **CLAP:** neither JUCE nor Tracktion hosts it ([clap-juce-extensions](https://github.com/free-audio/clap-juce-extensions): "does not support JUCE-based CLAP hosting"). We'd add it with clap-helpers if we want it.
- **Keep an exit.** The project format and our UI-facing edit commands belong to us, not to Tracktion's Edit, so the engine could be swapped later (Q4).

**Platform:** macOS 14+ on Apple Silicon first (Q5 for the floor). Windows comes later, if ever. JUCE and Tracktion run there, but driver handling (ASIO), testing and plugin quirks double the work.

---

## 7. Audio engine realities

1. **The real-time thread rules.** The audio callback never:
   - allocates or frees memory;
   - takes a lock that a non-real-time thread can hold;
   - does file or network I/O, or logs synchronously;
   - calls Objective-C or Swift runtime paths that might allocate.

   Graph changes are compiled off-thread and swapped in with an atomic pointer exchange. The old graph is freed off-thread. Parallel processing threads join the device's audio workgroup ([Apple](https://developer.apple.com/documentation/apple-silicon/porting-your-audio-code-to-apple-silicon)).
2. **Buffer sizes.** 64-128 samples while recording and monitoring; 128 at 48 kHz is 2.7 ms per buffer. 512-1024 for mixing with heavy plugins. Switchable per session without reopening the project.
3. **Driver I/O.** CoreAudio HAL through JUCE's device layer.
   - Focusrite says its Scarlett range is class compliant ([Focusrite](https://us.focusrite.com/articles/whats-the-best-interface-for-mac/)), and its 3rd Gen guide says no Mac driver is needed ([Focusrite](https://userguides.focusrite.com/hc/en-gb/articles/23031328571282-Scarlett-2i2-3rd-Gen-overview)). **The 2i2 4th Gen specifically: UNVERIFIED (very likely).**
   - Recorded audio is placed using the device's reported input, output and safety-offset latency, plus a manual offset we calibrate with a loopback test.
4. **Plugin delay compensation (PDC).** Every node reports its latency. The graph delays parallel paths so they meet aligned at sums, sends and the master. A latency change at runtime (an oversampling toggle, say) triggers a graph rebuild. Tracktion Engine provides PDC ([FEATURES.md](https://github.com/Tracktion/tracktion_engine/blob/develop/FEATURES.md)). Live and Logic document the same behaviour ([Live](https://www.ableton.com/en/live-manual/12/working-with-instruments-and-effects/#device-delay-compensation), [Logic](https://support.apple.com/guide/logicpro/work-with-plug-in-latencies-lgcpe11997ba/mac)). Monitoring paths with latency show their delay, and offer low-latency monitoring that bypasses high-latency plugins, as Logic does **[inferred feature choice]**.
5. **Offline bounce.**
   - Faster than real time, with plugins put in offline or non-real-time mode.
   - Sample streamers need time to fetch from disk, so the renderer has to tolerate plugins that need real-time pacing. A **real-time bounce** fallback is kept. None of the four vendors documents offline-render behaviour (**UNVERIFIED**).
   - A bounce of the same project is bit-identical, a test we can automate, except for plugins that are themselves non-deterministic.
6. **Recording safety.** Captured audio goes through a lock-free FIFO to a disk-writer thread, with headroom for disk stalls. Files are written incrementally, so a crash keeps everything up to the last flush. A dropped buffer is shown and logged, never hidden.

---

## 8. Phasing

| Phase | Ships | Done when |
|---|---|---|
| **v0 "tape"** | CoreAudio I/O with the 2i2. Audio tracks: record and play. MIDI tracks: record and play into **one hosted AU or VST3 instrument** (Noire in Kontakt Player as the first target). A basic mixer (volume, pan, mute, solo, master). Transport, tempo, metronome. Save and load. **Undo from day one** | Phil records a take over Noire, saves, reopens and hears it identically |
| **v0.5** | Arrangement editing (move, trim, split, loop). Piano roll and quantise. Effect inserts. Sends and buses. PDC. Plugin state save and restore. Offline bounce. Superior Drummer 3, EZbass and Helix loaded and saved | a full demo song with all four target plugins, bounced |
| **v1** | Everything in §2. Automation. Multi-out instruments. Sidechain. Plugin MIDI out. File drops from plugin windows. Loop and punch recording. Autosave and crash recovery. Quick controls for the four targets | Phil makes a track start to finish, from recording to bounce, without opening Logic |
| **v1.x** | Session (clip-launch) view. Step sequencer. Racks and macros. CLAP | |
| **Later, deliberately** | **Agent control (§5)**: a local API, then MCP, notes to changes, and parameter maps. A plugin sandbox bridge. Time-stretch and warping (needs a stretch library: Rubber Band is GPL or commercial, élastique is commercial, both **UNVERIFIED** current terms). Comping. Pitch correction and ARA. Control surfaces. Windows. Video. Notation. Surround | |

---

## 9. Risks and hard parts

- **Scale.** Logic and Live are decades of work by large teams. Ardour is over 20 years old. A small team plus agents won't reach their breadth. **The realistic target:** a focused Ableton/Logic-style DAW that one musician can finish songs in, with his own plugins. Expect months to v0 and a year or more to v1 **[estimate, not a commitment]**.
- **The plugin long tail.** Each plugin interprets the AU and VST3 specs a little differently: bus layouts, state, threading, GUI resizing, latency changes. Four named targets are tractable. "Any plugin" is not. Testing licensed plugins needs real licences on a real Mac, so CI can't cover it. Phil's Mac is the compatibility lab.
- **A crash takes the session down in v1.** Without a sandbox, one bad plugin crashes the app. The mitigation is autosave and incremental recording, which makes the bridge a real v2 item.
- **Real-time correctness.** Priority inversions, allocation in the callback and denormals are subtle, and agent-written C++ makes them likelier. Needed from the start:
  - real-time-safety tests and assertions in debug builds;
  - stress tests at 64-sample buffers;
  - a human review of everything that runs on the audio thread.
- **UI polish is the long pole.** Logic-level feel (zoom, scroll, drag) is many small things. JUCE draws its own UI, so we own the feel completely, for better and for worse.
- **Licensing and legal:**
  - the JUCE clause 1.12 question;
  - Tracktion and JUCE combined commercial cost if Whiplash is ever sold;
  - stretch-library licences;
  - trademark care: no "VST" logo unless we follow Steinberg's rules, and no Ableton or Logic look-alike assets.
- **Platform churn.** Rosetta narrows after macOS 27 ([Apple](https://developer.apple.com/documentation/apple-silicon/about-the-rosetta-translation-environment)). Xcode 27 needs `x86_64` added to ARCHS explicitly. Apple steers hosts toward AUv3.
- **Why build it at all.** Live and Logic already do all of v1. The case for Whiplash is ownership: a DAW shaped exactly to Phil's workflow, with the option of agent control later (§5). It doesn't rest on doing more than they do. That is worth Phil confirming before the build (Q11).

---

## 10. Open questions for Phil

1. **Scope of v1.** Is §2 right? Should anything move up (session view, time-stretch, comping) or down?
2. **Audience.** Just you, or eventually other people? That decides licensing (GPL/AGPL is fine for personal use; selling needs Tracktion and JUCE commercial), code signing, installers and support.
3. **Budget for licences**, if it's ever distributed: Tracktion plus JUCE tiers (§6), and a legal read on JUCE EULA clause 1.12.
4. **The foundation.** Accept the Tracktion Engine + JUCE recommendation? Or do you want a Rust-first core for safety and long-term ownership, accepting a much later v0?
5. **The macOS floor.** 14+ (matching Kontakt and Helix) or 15+? Do you need Intel Macs at all? (Recommended: no.)
6. **When does agent control come in?** After v1 (as written), or not at all unless the core DAW is in daily use?
7. **The look.** Dark only, or a light theme too? Any reference images beyond "Ableton x Logic, Rams"?
8. **Session view priority.** Clip launching is very Ableton. Do you jam that way, or is arrange-first enough for v1?
9. **Interfaces beyond the 2i2.** Any other gear to support early: MIDI controllers, a control surface?
10. **Repo.** A new repository (recommended, since this isn't the plugin), or a directory here? The project only keeps the name.
11. **Go-ahead criteria.** What do you need to see or decide before the build phase starts? A spike that hosts Noire in a minimal Tracktion Engine app would be the obvious first proof.
