# Whiplash Visualiser: UI design proposal

Status: **approved by Phil on 2026-11-11**, with the decisions below. Implemented on `feat/visualiser` (based on v0.3.0, `11eb6dd`).

### Approved decisions

1. **Conversation:** a side panel in full-frame windows, switching automatically to lower-third captions when the window is narrower than 1100 px (terminal beside the page).
2. **Feed:** Hermes plugin hooks, with replies **streaming word by word** through `on_stream_start` / `on_stream_delta` / `on_stream_end`, alongside `pre_llm_call`, `post_llm_call`, `pre_tool_call` and `post_tool_call`. Phil confirmed all of these are in `VALID_HOOKS` on his Air's Hermes v0.23.1. A read-only `state.db` poll is the fallback. Hooks must be non-blocking, never raise, and return `None`.
3. **Look:** clean neon **plus** a perspective-tilted "runway" step grid. No scanlines and no chromatic aberration. Keep it light on the Air's GPU.
4. **Grid:** the current bar's 16 steps big, plus a 4-bar minimap.

Sections 1–5 are the original proposal. Where they differ from the decisions above, the decisions win. Section 6 records how each open question was resolved.

---

## 1. Vision

An **ultra sick, futuristic DAW look**, not a plain dashboard. On camera it should read as a next-gen instrument or performance surface sitting beside the terminal, not an admin panel.

It must:

- **Show every channel the agent is driving, and only those.** If Hermes is playing 5 tracks there are 5 lanes, not 8 strips with 3 empty. If it touches channel 11 with `set_param`, channel 11 gets a lane. For each lane: the notes, live params, mute/drop/fill state and ramps.
- **Make BPM prominent.** BPM is the biggest number on the page and always visible. It is not a status chip.
- **Include a frequency visualiser**: spectrum analyser, oscilloscope, level meters.
- **Include a sleek collapsible agent overlay** that shows the live conversation between Phil and Hermes. Tool calls stay hidden until Phil asks for them.

The page has three rules:

1. **Cause and effect are visible.** When Hermes says "sweeping the bass filter", a magenta ramp bar appears on the bass lane in the same second.
2. **It never lies.** Real audio is labelled `AUDIO`. Animation derived from MIDI is labelled `MIDI`. The virtual port is labelled `VIRTUAL · SILENT` in red.
3. **It never touches the clock.** The page only reads state. It cannot send MIDI and cannot slow the sequencer thread.

---

## 2. Layout wireframe at 1920 × 1080

The full-frame layout has the overlay open. Sizes are approximate CSS px at 1080p.

```
 0                                                                         1440                 1920
 ┌──────────────────────────────────────────────────────────────────────────┬────────────────────┐
 │ ███ 122.0 BPM    BAR 0012 ▸ ●●○○  4/4      DEEPHOUSE   ⇢ TECHNO @ BAR 16 │ HERMES · LIVE   ⟨⟩ │ 0
 │ ███  (≈120px     loop 3/4 ▓▓▓░            (pattern)    (queued, 2 beats) │ [tools: off]       │
 │      numerals)                         ◉ DIGITAKT II  USB  · clock ok    │────────────────────│
 ├──────────────────────────────────────────────────────────────────────────┤ PHIL         07:41 │ 132
 │ T1 KICK   ▮ ▯ ▯ ▯ ▮ ▯ ▯ ▯ ▮ ▯ ▯ ▯ ▮ ▯ ▯ ▯ │ C4 v118     │ ▁▃▅█ │ meter  │ play something deep │
 │ T2 RIM    ▯ ▯ ▯ ▮ ▯ ▯ ▯ ▯ ▯ ▯ ▮ ▯ ▯ ▯ ▯ ▯ │             │      │        │                    │
 │ T3 CLAP   ▯ ▯ ▯ ▯ ▮ ▯ ▯ ▯ ▯ ▯ ▯ ▯ ▮ ▯ ▯ ▯ │             │      │        │ HERMES       07:41 │
 │ T4 C.HAT  ▮ ▯ ▮ ▮ ▮ ▯ ▮ ▮ ▮ ▯ ▮ ▮ ▮ ▯ ▮ ▮ │  ░░ MUTED ░░ (lane hatched)  │ Deep house at 122, │
 │ T5 O.HAT  ▯ ▯ ▮ ▯ ▯ ▯ ▮ ▯ ▯ ▯ ▮ ▯ ▯ ▯ ▮ ▯ │ DROP · back in 2 bars        │ rim and chords in. │
 │ T6 BASS   ▯ ▯ ▯ A3▯ ▯ A3▯ ▯ ▯ A3▯ ▯ ▯ C4▯ │ cutoff ━━━━━▶·····  r3 62%   │ ⚙ 1 tool call  ▸   │
 │ T7 MINOR  A3▯ ▯ A3▯ ▯ A3▯ ▯ ▯ A3▯ ▯ ▯ ▯ ▯ │ reso ━━━━━━░░               │                    │
 │ T8 MAJOR  C4▯ ▯ C4▯ ▯ C4▯ ▯ ▯ C4▯ ▯ ▯ ▯ ▯ │ FILL next bar               │ PHIL         07:42 │
 │           └──────── 16 steps, current bar ───────┘ ▲ playhead (cyan)     │ open the filter on │
 │ 4-bar minimap  ▕▓▓▓▓▕▓▓▓▓▕▓▓▓▓▕▓▓▓▓▏  drops/fills marked on the minimap   │ the bass slowly    │
 ├──────────────────────────────────────────────────────────────────────────┤                    │ 752
 │ [AUDIO · Digitakt II USB]                                    │  L ▮▮▮▮▮▯  │ HERMES ● thinking… │
 │ spectrum (log-freq, 64–96 bands, peak-hold)       │ scope    │  R ▮▮▮▮▯▯  │  ⚙ whiplash_ramp…  │
 │ ▁▂▃▅▇█▇▆▅▄▃▃▂▂▁▁▁▂▂▁▁                                 │ ∿∿∿∿     │ -6 dBFS    │                    │
 ├──────────────────────────────────────────────────────────────────────────┤ (glass panel,      │ 1032
 │ LOG 07:42:10 ramp_param t6 cutoff 20→110 / 4 bars → r3 · 07:41:55 play … │  collapsible)      │ 1080
 └──────────────────────────────────────────────────────────────────────────┴────────────────────┘
```

| Region | Box (x, y, w × h) | Notes |
|---|---|---|
| Transport header | 0, 0, 1440 × 132 | BPM numerals about 120 px tall, the largest thing on the page |
| Track lanes | 0, 132, 1440 × 620 | 8 lanes ≈ 77 px each. Fewer lanes grow up to a 120 px cap, and more than 8 (up to 16 channels) shrink to a 44 px floor |
| Lane columns | header 220 · step grid 860 · params 320 · meter 40 | Step cells about 50 px, so they are readable on a compressed video |
| 4-bar minimap | inside lanes, bottom 28 px | Shows where in the 4-bar loop we are, plus scheduled drops and fills |
| Analyser | 0, 752, 1440 × 280 | Spectrum about 1000 wide, scope about 280, master L/R meters about 160 |
| Instrument log | 0, 1032, 1440 × 48 | A one-line ticker of Whiplash tool actions only |
| Agent overlay | 1440, 0, 480 × 1080 | A glass panel. Collapsed, it becomes a 56 px rail and the main area widens to 1864 |

**With the terminal beside it** (a window about 960 wide, the usual demo split), the overlay starts collapsed, because the terminal already shows the conversation. The BPM header compresses to a single 72 px row with the BPM still the largest element. The lane params column folds under the grid, and the analyser shrinks to spectrum plus meters with the scope hidden. Below 700 px wide, the lanes drop the note labels and keep the cells.

**With the terminal over it** (a floating terminal in the lower-right), the important parts sit in the top-left. BPM and lanes stay clear, and the analyser and log are what get covered.

---

## 3. Panels: purpose and data source

All engine data comes from one immutable **snapshot** that the plugin builds off the clock thread (see §3.8). Field names refer to `Engine.status()` and the engine internals in v0.3.0.

### 3.1 Transport header
- **BPM**: `bpm`. Shows one decimal only when the value isn't whole.
- **Bar / beat**: `bar`, `pattern_bar`, `bars`, plus the current step published by the clock thread. Four beat dots light on each beat.
- **Loop position**: `pattern_bar % 4` of the 4-bar pattern. With a `bars` limit set, it also shows "bar 12 / 32".
- **Pattern**: `pattern` and `swing`. Swing appears as a small `SW 55%` beside the name, only when it isn't 50.
- **Queued switch**: `queued` → `⇢ TECHNO @ BAR 16`, with a beat countdown and the BPM at the switch if it differs.
- **Port**: `port`, `virtual`, `fallback`, `port_lost`, `last_error`. Real device shows a cyan dot and the port name. Virtual fallback shows a red `VIRTUAL · SILENT` pill. A lost port shows a flashing red `PORT LOST: <name>`. The `last_error` text appears on hover or click.
- **Idle**: with nothing playing, BPM is dimmed at its last or default value, the lanes show an empty-state line, and the port status is still live.

### 3.2 Track lanes: the in-use set
A lane exists for channel *t* if **any** of these holds:
- the current or queued pattern has hits on *t*;
- *t* is muted, hardware-muted, dropped, filled, density-mutated or ramped;
- Whiplash has sent a CC or NRPN on *t* this run (`_cc_values` keys).

Lanes are ordered by channel. Lanes appear with a 300 ms slide-in and leave the same way on the next bar after they stop being in use. `whiplash_stop` clears the set.

Each lane has four parts:
- **Header**: `T6`, the role from `pattern.roles` (`BASS`), and state badges (`MUTE`, `HW`, `DROP 2`, `FILL`, `DENS -40%`).
- **Step grid** (16 cells, current bar of the *working* pattern, so density changes show): each hit is a filled cell. Brightness follows velocity, and gate length shows as a tail into the next cells. Melodic tracks print the note name (`A3`). Drums show only cells (all note 60). A channel touched only by CC shows the label "CC only" and no grid.
- **Params column**: one bar per param Whiplash has set on that track (named via `ccmap`, raw `CC 74` otherwise), showing the last value sent out of 0–127. Active ramps replace their param's bar with the animated ramp bar (§4.4).
- **Activity meter**: MIDI note-on energy (velocity, decaying). It is always labelled as MIDI, because USB audio from the Digitakt is the stereo main mix and has no per-track signal.

### 3.3 Analyser: spectrum, scope and master meters
- **Real path (AUDIO)**: the page calls `navigator.mediaDevices.getUserMedia({audio: {deviceId, echoCancellation: false, noiseSuppression: false, autoGainControl: false}})`. The processing flags are switched off on purpose, because otherwise the browser reshapes the signal. The audio goes into a Web Audio `AnalyserNode` (fftSize 4096, smoothing 0.75). `http://127.0.0.1` counts as a secure context, so this works without HTTPS. The Digitakt II is class-compliant USB audio.
  - Flow: a `CONNECT AUDIO` button asks for mic permission. The browser only reveals device labels after that, so the device picker comes next. The page auto-selects the device whose label contains "Digitakt" and remembers the choice in localStorage.
  - Spectrum: log-frequency, 20 Hz–20 kHz, 64–96 bars with peak-hold caps. Scope: time-domain trace triggered on zero crossings, so it holds still. Meters: L/R peak plus RMS in dBFS, with a clip light.
- **Fallback (MIDI FALLBACK)**: used when permission is refused or no device is chosen. The analyser draws a synthetic display from note-on energy per track. Each track maps to a fixed frequency band (kick low, hats high, chords mid), decaying at the step rate. The scope area shows a step-rate pulse train instead of a waveform. The meters show `—` rather than invented dB values.
- **Labelling**: the panel's top-left badge reads either `AUDIO · <device label>` (lime) or `MIDI FALLBACK · not real audio` (amber, dashed outline). The badge can't be hidden, and the fallback's bars are drawn hollow so the two modes look different even in a still frame.

### 3.4 Agent overlay: conversation first
**Default view: conversation only.** Phil's messages and Hermes's final replies appear as alternating blocks with a role label and timestamp. Replies render a safe subset of Markdown (bold, code, lists). Content is inserted as text, never HTML.

**Tool calls** are hidden by default and can be revealed two ways. Both are built, and the default is noted below:
- **Per message (default)**: under each Hermes reply, a quiet chip `⚙ 3 tool calls ▸` gives the count. Expanding it lists each call: name, short args, a result summary of about 120 chars, and duration. Whiplash calls get the 🥁 glyph and the accent colour of the lane they touched.
- **Global switch** `TOOLS: OFF / ON` in the overlay header, shortcut `T`. When ON, every chip is expanded and new tool calls stream in live.

While a turn is running, a `HERMES ● thinking…` row shows. Tool calls tick inside it as they happen, even with tools hidden, as a single updating line `⚙ whiplash_ramp_param…`. When the reply lands, the row turns into the reply.

**Collapse**: the `⟨⟩` button or shortcut `C` collapses the panel to a 56 px rail. The rail shows a Hermes glyph and a pulse when a new message arrives. The open/closed state is remembered.

**Linking (the camera moment)**: when a Whiplash tool call arrives, the lane it targets flashes once in that call's colour. This happens whether the overlay is open or not.

**Data source, preferred option: Hermes plugin hooks.** Hermes exposes `ctx.register_hook(name, callback)`. The hook names come from the Hermes hooks docs and `hermes_cli/plugins.py` `VALID_HOOKS`. I read a Hermes source copy on this host, not Phil's installed version.

| Hook | What we take | Notes |
|---|---|---|
| `on_session_start(session_id, …)` | starts a new conversation and clears the overlay | not fired when a session continues |
| `pre_llm_call(session_id, user_message, conversation_history, is_first_turn, …)` | Phil's message, plus a **backfill** of earlier turns from `conversation_history` | **must return `None`**: a returned string gets injected into the prompt |
| `post_tool_call(tool_name, args, result, duration_ms, status, …)` | the live tool-call feed (all tools, not only Whiplash) | fires immediately after each tool |
| `post_llm_call(session_id, user_message, assistant_response, …)` | Hermes's final reply | only fires on successful turns, so an interrupted turn shows "interrupted" |
| `on_stream_start` / `on_stream_delta(delta, kind)` / `on_stream_end(final_text, finished, error)` | the reply streaming in word by word (`kind == "text"` only, never reasoning) | added on approval; observers delivered off the token path |
| `pre_tool_call(tool_name, args, …)` | a running tool row, shown while the tool executes | must return `None` (a dict can block the tool) |

The hooks are registered in `register(ctx)`, alongside the tools, and `plugin.yaml` gains `provides_hooks`. Each callback copies its arguments into a bounded in-memory deque (about 500 entries), truncates large `result` strings, and returns. It does no I/O, takes no lock shared with the engine, and can't raise. Hermes runs these on its own turn thread, which is also time-bounded. When the view isn't open, the only cost is the append, so the text/CLI behaviour stays the same.

**Fallback option: read-only SQLite.** If `register_hook` is missing on Phil's Hermes version, the server thread polls `~/.hermes/state.db` once a second. It opens it with `sqlite3.connect("file:…/state.db?mode=ro", uri=True)` and selects `messages` (`session_id, role, content, tool_calls, tool_name, timestamp`) for the session with the max timestamp, newer than the last row seen. If the file doesn't exist, the overlay says "conversation unavailable". It doesn't guess, and nothing is assumed about kamino-dev.

**Privacy**: this page puts the conversation on camera. Tool results from non-Whiplash tools (terminal, file reads) can contain anything, which is one more reason tools default to hidden. Results are truncated, and a `B` hotkey blurs the whole overlay.

### 3.5 Instrument log
A single-line ticker at the bottom, showing **Whiplash tool actions only**: time, tool, compact args, result summary (`→ r3`, `queued @16`, `error: …` in red). Clicking it opens a 10-entry drawer. The source is a deque written by the `_tool` wrapper in `tools.py`, which already sees every call and result. This works without hooks.

### 3.6 Port and health
These sit in the header (§3.1). A disconnected SSE stream shows a grey `VIEW OFFLINE · reconnecting` bar across the top, so a frozen page can never pass for a stopped beat.

### 3.7 Keyboard
`C` overlay · `T` tool calls · `A` audio source · `B` blur overlay · `F` fullscreen · `?` help. These are the only interactive controls. Nothing on the page controls the sequencer.

### 3.8 How the data gets to the page (plumbing, not look)
- The clock thread does one extra thing: at each step it assigns a small tuple `(bar, step, monotonic_t)` to an attribute. This is a single atomic assignment in CPython with no lock and no allocation beyond the tuple.
- The view server thread, which is daemonised, builds the full snapshot by calling `status()` (short `_lock` hold) at most about 10×/s, and only while a browser is connected. It pushes a frame on each bar boundary or state change via **SSE** (`text/event-stream`, stdlib `http.server`).
- **The browser extrapolates the playhead** from `bpm` and the last `(step, t)`, then corrects on each frame. The animation stays at 60 fps without the plugin sending 60 messages a second.
- Static per-pattern data (hit lists for 4 bars × 16 steps) is sent once per pattern change, not every frame.

---

## 4. Visual language

Dark only. The page is built for a camera and a dark terminal beside it.

### 4.1 Palette

| Token | Hex | Use |
|---|---|---|
| `--void` | `#05060A` | page background |
| `--panel` | `#0B0E15` | panels (overlay: `rgba(11,14,21,0.72)` + 18 px backdrop blur) |
| `--grid` | `#171C28` | empty step cells, rules |
| `--line` | `#252C3D` | panel borders (1 px, inner glow) |
| `--text` | `#E8ECF5` | primary text |
| `--dim` | `#6E778C` | labels, secondary |
| `--cyan` | `#2EE6FF` | playhead, BPM beat pulse, real-port status |
| `--magenta` | `#FF2E9A` | agent actions: ramps, tool-call flashes |
| `--lime` | `#B6FF3B` | real AUDIO signal, spectrum, meters' safe zone |
| `--amber` | `#FFB22E` | queued, fill, MIDI FALLBACK badge, meters' -6 dB zone |
| `--red` | `#FF3D4D` | VIRTUAL · SILENT, port lost, clip, errors |

The 8 track hues are evenly spaced on a single OKLCH lightness of 0.78 and chroma of 0.16, so no lane is brighter than another: T1 `#FF6B6B`, T2 `#FFA552`, T3 `#F5D547`, T4 `#7BE35B`, T5 `#3FE0C5`, T6 `#4FB6FF`, T7 `#8E8CFF`, T8 `#E07BFF`. Channels 9–16 repeat the hues with a dotted lane edge. The hex values are first-pass, and I'll check them against OKLCH when implementing.

### 4.2 Typography
- **Numerals and labels**: `ui-monospace, "SF Mono", "JetBrains Mono", Menlo, monospace`, using `font-variant-numeric: tabular-nums` so digits don't jitter. On Phil's Air this resolves to SF Mono. There are no web fonts, so the page works offline and loads instantly.
- **Conversation**: `system-ui, -apple-system, "Inter", sans-serif`, 18 px / 1.45.
- **Sizes at 1080p**: BPM 120 px, weight 200, letter-spacing −0.02em. Header values 28 px. Lane labels 18 px uppercase, tracking +0.08em. Minimum text is 14 px, because anything smaller dissolves in video compression.

### 4.3 Grid and surfaces
- 8 px base unit. 16 px gutters. Panels use 12 px radius and 1 px `--line` borders.
- A faint 32 px background grid in `--grid` at 40% suggests a "surface" without noise. A subtle CRT/scanline texture is optional (see open question 3).
- Glow comes from `box-shadow`/canvas `shadowBlur` in the element's own colour at low alpha. It is used only on live things (the playhead, hits as they trigger, ramps, signal). Static chrome never glows.

### 4.4 Element by element
- **Playhead**: a 4 px cyan vertical light bar sweeping all lanes, with a 3-step fading trail. As it passes a hit, the cell flashes white-hot for 1 step and settles to its track hue. On the bar line the trail briefly spans the full lanes area.
- **Step cells**: empty cells are `--grid` rounded squares. Hits are filled with the track hue, at alpha scaled by velocity (40–100%). Gate tails are a thinner bar into the following cells. Note names sit inside melodic cells in 12 px mono, the one exception to the 14 px minimum. They're decoration, and the cell colour carries the meaning.
- **Param bars**: a thin horizontal track holding the fill (0–127) in the lane hue, with the name and value on the left, e.g. `CUTOFF 74`. A change jumps with a 120 ms ease and a brief brighten.
- **Ramps**: the bar turns **magenta**. A hollow ghost marker sits at the target value, and the fill animates from start toward target as the ramp progresses. A small curve glyph (`╱` linear, `⌒` log, `⌣` exp) and `r3 · 62%` show the ramp id and progress. Behind the fill, faint chevrons travel in the direction of travel. When the ramp completes, the bar flashes once and returns to the lane hue.
- **Mute**: the lane drops to 25% saturation and opacity, with a diagonal 45° hatch overlay and a `MUTE` badge. The playhead still passes but cells don't flash. A hardware mute (CC 94) adds an `HW` badge so it's clear the unit itself is muted.
- **Drop**: the lane goes near-black. The badge reads `DROP · back in 2 bars`, with a countdown ring on the bar line. The minimap shows the dropped span as a dark gap. On the return bar the lane re-lights with a left-to-right sweep. A drop with a fill shows the amber fill stamp on its last bar.
- **Fill**: the bar before a fill, the target lanes get an amber `FILL ▸ next bar` tag. On the fill bar, the lane border pulses amber and the fill hits render as amber cells.
- **Density**: a `DENS +30%` or `DENS −40%` badge. Cells that density removed show as dotted outlines (ghosts) for one bar, then vanish.
- **Queued switch**: an amber chip `⇢ TECHNO @ BAR 16` in the header, with a beat countdown `●●○○`. On the switch bar, lanes cross-fade to the new pattern (150 ms) and lanes that join or leave slide in or out.
- **BPM**: giant numerals. On each beat the cyan underline pulses (opacity 0.4 → 1 → 0.4). The numerals never scale, so they stay readable. On `set_tempo` the digits roll to the new value over 400 ms, with a `▲ +10` or `▼ −10` delta tag that fades after 2 bars.
- **Meters**: vertical L/R bars in segments, lime → amber (−6 dBFS) → red (−1 dBFS). A peak-hold line falls at 12 dB/s. The clip light latches for 2 s.
- **Spectrum**: rounded-top bars in a lime→cyan vertical gradient, with peak caps in `--text` at 60%. A faint reflection below the baseline gives a "surface" feel. In MIDI fallback the bars are hollow amber outlines.
- **Scope**: a single 2 px cyan trace with a glow, triggered on zero crossings.
- **Agent overlay**: a glass panel over the right of the surface. Phil's blocks carry a `PHIL` label in `--dim` with a 2 px cyan left rule. Hermes blocks carry a `HERMES` label with a 2 px magenta left rule. The thinking row shows a slow magenta breathing dot. Tool-call chips are `--dim` outlined pills. When expanded they show monospace rows, and Whiplash rows get a coloured dot for the lane they touched. New messages slide up 12 px and fade in over 200 ms.

### 4.5 Motion rules
- Everything that moves is tied to the clock (step, beat, bar) or to an event (a tool call, a reply). Nothing moves idly except the thinking dot and the playhead.
- Movement durations are 120 ms for value changes, 200–300 ms for layout, and 400 ms for the BPM roll.
- `prefers-reduced-motion` turns off trails, chevrons and slides, and leaves the playhead plus instant state changes.
- The lanes, spectrum and scope render on `<canvas>`; text and overlay are DOM. The page is one HTML file with inline CSS/JS, no build step and no external requests.

---

## 5. What reads on camera in a <90 s demo

A video viewer gets a few seconds per moment, through compression, often at small size. These choices are made for that:

- **Big, high-contrast anchors.** BPM, lane colours and the playhead are readable at 480p. Nothing important is under 14 px or depends on a 1 px line.
- **Every agent action has a visible effect within a bar.** A mute desaturates, a ramp turns magenta and moves, a drop goes dark with a countdown, a switch shows an amber chip and then a lane cross-fade.
- **Honesty badges are clear in a still frame**, so nobody can say the spectrum was faked.

A suggested 90 s storyboard that the design is tuned for:

| t | Phil types (terminal) | What the page shows |
|---|---|---|
| 0–8 s | "launch the visualiser" | page opens: idle, `DIGITAKT II · USB` cyan, BPM dimmed |
| 8–20 s | "play some deep house" | 8 lanes slide in, BPM lights `122`, playhead starts, spectrum wakes (AUDIO) |
| 20–38 s | "slowly open the filter on the bass over 4 bars" | T6 param bar turns magenta, ghost target, fill climbs; spectrum brightens up top |
| 38–52 s | "drop the kick for two bars, then fill back in" | T1 goes dark with `back in 2 bars`, amber FILL tag, lane re-lights with a sweep |
| 52–70 s | "switch to techno at 132" | amber `⇢ TECHNO @ BAR n` countdown, lanes cross-fade, BPM rolls `122 → 132 ▲` |
| 70–90 s | "mute the hats, add swing" | T4/T5 hatch out, `SW 60%`, overlay shows Hermes's reply, Phil flips `T` to reveal the tool calls |

The overlay matters most in full-frame shots, where the terminal is off-screen. In split shots it starts collapsed.

---

## 6. Open questions (resolved, see "Approved decisions" at the top)

1. **Overlay shape: side panel or lower-third captions?** The proposal is a 480 px collapsible side panel. The alternative is a **lower-third subtitle strip**: only the latest exchange, large (28 px) and centred over the analyser, fading after about 8 s. It reads much better on a phone-sized video and doesn't duplicate a visible terminal, but it loses scrollback. Possible compromise: side panel in full-frame, auto-switch to the lower-third when the window is under 1100 px wide. **Which one should be the default?**
2. **Hooks or SQLite only?** Hooks are live and in-process, and they backfill history through `conversation_history`. They also mean `register()` registers hooks on every Hermes run, the view-open or not, and `plugin.yaml` gains `provides_hooks`. That touches the catalog surface and the existing "register only wires tools" note. SQLite-only keeps the plugin's footprint exactly as it is but has about 1 s of latency, and it depends on the `state.db` schema, which I haven't verified against Phil's Hermes version. I recommend hooks with SQLite as a fallback. **OK to register hooks?** If yes, I also need confirmation that Phil's Hermes (`requires_hermes >= 0.19`) has `register_hook` and these four hook names. I read them from a Hermes source copy on this host, not his install.
3. **How "sci-fi" should it look?** Two levels:
   - **Clean neon** (proposed): crisp flat panels, glow only on live elements, no texture.
   - **Full sci-fi**: also adds scanlines, subtle chromatic aberration on hits, and a perspective-tilted step grid ("runway") receding toward the BPM.

   Full sci-fi looks more striking in a thumbnail but costs readability and GPU time on a MacBook Air while recording. **Which level?**
4. **Smaller choice: lane grid scope.** The proposal shows the **current bar** big (16 cells) plus a thin 4-bar minimap. The alternative shows all **64 steps** in the lane at about 13 px per cell. It shows the whole groove's shape at a glance but is unreadable as cells on camera.

---

### Resolution

1. **Overlay shape:** side panel in full-frame, lower-third captions under 1100 px wide.
2. **Hooks or SQLite:** hooks, with streaming replies; `state.db` is only the fallback.
3. **Look:** clean neon plus the runway tilt. `R` toggles the tilt off, and `prefers-reduced-motion` starts it flat.
4. **Grid scope:** the current bar's 16 steps, plus the 4-bar minimap.

### Implementation notes (as built)

- **Streaming hooks:** Hermes delivers `on_stream_*` on one worker thread per callback, so start, delta and end can arrive out of order relative to each other and to `post_llm_call`. Streamed text is keyed by `(turn_id, iteration)`, and `post_llm_call`'s final reply supersedes any streamed copy of the same text when the turn is serialised. This guarantees a reply never shows twice.
- **Tool calls:** `pre_tool_call` adds a running tool row and `post_tool_call` completes it. This is what drives the "thinking… ⚙ whiplash_ramp_param…" line while tools are hidden.
- **Captions:** in narrow windows they show the latest exchange and fade 8 s after the turn finishes. `C` hides them.
