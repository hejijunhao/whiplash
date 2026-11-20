# Whiplash web app: product vision

Status: **vision draft for Phil, 2026-11-20.** Nothing here is built. The decisions in §2 are agreed. Everything else is a proposal, and §11 lists the open questions. Nothing here has been tested on a real Digitakt II. Device claims point to [docs/digitakt-ii/reference.md](../digitakt-ii/reference.md) (cited as "reference §n").

## 1. What it is

The plan is a **web app that acts as a digital twin of the Elektron Digitakt II**. It would be a Next.js app hosted on Vercel, and it grows out of today's read-only visualiser (`view.py` / `view.html`, served on 127.0.0.1:7341). That includes the section timeline and EAR from PR #24 (`feat/viz-timeline-listen`), which merged at `3f4f883`, the commit the catalog pins.

- **It works by hand, with no agent.** Plug the unit in, open the page in Chrome or Edge, and play: tracks, trigs, mutes, params, tempo and transport.
- **An agent can take over at any time.** Hermes, or any agent, drives the same verbs the UI uses, and the UI shows every change live, on the bar where it lands.
- **The layout follows the Digitakt:** 16 tracks, a 16-step trig grid, and the instrument's parameter pages. It is an instrument surface, not a timeline editor.

**Who it's for:** first Phil, playing the unit with and without Hermes. After that, any Digitakt II owner who wants an agent to jam with them without installing a Hermes plugin before they can make a sound.

**What it is not:**
- **A DAW.** It has no audio tracks, mixing of recorded audio, clip launcher, piano-roll arrangement or plug-ins.
- **A replacement for Elektron Transfer or Overbridge.** It does no sample upload, backups, project management, OS updates or multitrack audio.
- **An editor for the unit's own patterns.** The trig grid is Whiplash's sequence, which reaches the unit as notes over MIDI. Whiplash can't write the unit's trigs or p-locks: that needs SysEx or the TRIG-page CCs 3/4/5, and both stay off (reference §15.2).
- **A skin of the hardware.** See §9.

## 2. Settled decisions (agreed with Phil)

1. **The browser does the device I/O.** Vercel's servers can't reach USB, so the page uses **Web MIDI**. That means Chrome or Edge on desktop; Safari has no Web MIDI. The page detects "Digitakt II connected" and offers manual control.
2. **Agents connect through a local bridge.** The Whiplash engine runs on the user's machine and connects to the open page over localhost. Hermes, or any agent, drives the same verbs as the UI. **Later option:** move the sequencer into the browser so the UI and the agent share one engine. That is a big rewrite, to be decided later; §5.3 sets out the tradeoff.
3. **Sample browsing waits on a SysEx decision.** Listing samples needs Elektron's undocumented SysEx protocol, and Whiplash bans SysEx. The choice is open (§8): (a) read-only SysEx used only for listing, or (b) a local sample library as the source of truth. Until Phil decides, the app keeps slot-number sample select (CC 19, which exists today) plus kit-scan and user labels.
4. **Three phases:**
   1. The Next.js app on Vercel, with Web MIDI detection and manual control.
   2. The local agent bridge.
   3. Sample browsing, after the SysEx decision.
5. **The Hermes plugin keeps working.** The catalog entry pins the repo root at `3f4f883` and has no subdir field, so `plugin.yaml` stays at the root (§7).

## 3. Screen layout

The target is one screen at 1440 px or wider, with nothing hidden in menus while playing. Below 1100 px the agent column folds into captions, as the visualiser does today (visualiser-design.md, decision 1).

```
┌─────────────────────────────────────────────────────────────────────────┬──────────────────────┐
│ ● DIGITAKT II · USB   ▶ ■   122.0 BPM   BAR 17 ●●○○   PTN deephouse      │ AGENT  · bridge ●    │
│ ⇢ techno @ BAR 25     KEY A min  i-VI-III-VII    SW 55%   [HANDS OFF]    │──────────────────────│
├──────────────────────────────────────────────────────────────────────────┤ PHIL                 │
│ ARR  intro 8 │ build 8 │▓drop 16▓│ break 8 │ outro 8      NOW drop 3/16  │ build to the drop    │
├──────────────────────────────────────────────────────────────────────────┤                      │
│ T1  KICK    M ■□□□■□□□■□□□■□□□   LVL ▮▮▮▮▯  FLT ◔  │ ▮▮▯              │ HERMES               │
│ T2  RIM     M □□□■□□□□□□■□□□□□                     │ ▮▯▯              │ Building over 8…     │
│ T3  CLAP    M □□□□■□□□□□□□■□□□                     │                  │  ⚙ arrange  @25      │
│ T4  CH      ▣ ░░░░░░ MUTED ░░░░░                    │                  │  ⚙ ramp_param @17    │
│ T6  BASS    M □□□A3□□A3□□□A3□□□C4□  FLT ━━━━▶···   │ ▮▮▮▯             │                      │
│ …   (16 rows; unused ones collapse to a thin line)  ▲ playhead          │ YOU (ui) mute T4 @18 │
├──────────────────────────────────────────────────────────────────────────┤                      │
│ PARAM  TRIG │ SRC │ FLTR │ AMP │ FX │ MOD     T6 BASS                    │                      │
│   FREQ ━━━━━━━▶········ 74→110 / 4 bars   RES ━━━  ENV ━━   [ramp lane] │                      │
├──────────────────────────────────────────────────────────────────────────┤                      │
│ LISTEN  L ▮▮▮▮▯ R ▮▮▮▯▯  LUFS -11  PEAK -2.1  LOW 38%   AUDIO · Digitakt │ > type to the agent  │
└──────────────────────────────────────────────────────────────────────────┴──────────────────────┘
```

- **Header:** device status, transport, BPM (the biggest number on screen), bar and beat, the pattern, a queued switch with its countdown, key and progression, and swing. **HANDS OFF** stops every send except the clock (the roadmap's safety-rail idea).
- **Track rows (16):** the track number and its **kit-map label** (white for a user or confirmed kit-scan label, gray for an assumed one), plus the sample slot and its label.
  - **Mute:** `M` means sounding, `▣` a software mute, and `HW` a CC 94 mute.
  - **Trig grid:** 16 steps for the current bar with the playhead. Notes are shown on melodic tracks, with page dots when the part is longer than one bar.
  - **Level and filter:** a level fader and a filter knob.
  - **Meter:** a MIDI-derived activity meter.
  - **Badges:** drop, fill, density and written-part badges, as the rack shows today.
  - **Empty tracks** collapse to one line and expand on click.
- **Arrangement strip:** `whiplash_arrange` sections laid on their bar lines, with the playhead and the next section. Fills, drops and switches already scheduled are marked underneath. This is today's SECTIONS module, made full width.
- **Param lanes:** the selected track's parameter pages (TRIG / SRC / FLTR / AMP / FX / MOD), using Elektron's page model and Whiplash's named params (`ccmap.py`). A ramp is drawn as a live lane from its start value to its target, timed in bars. Each value reads "last sent" or "last heard" (§4).
- **Agent column:** the conversation, streaming. Each tool call is **tagged with the bar it lands on** (`⚙ arrange @25`), and the row it touches flashes when that bar arrives. UI actions appear in the same log as `YOU (ui)`, so the agent's moves and yours sit on one timeline. With no bridge it reads `AGENT · not connected` and the instrument still works.
- **Listen meters:** live L/R meters from the browser's own capture of the unit's USB audio (getUserMedia, as CONNECT AUDIO does today), plus the last `whiplash_listen` numbers when the bridge is up. Labels always say `AUDIO` or `MIDI` (§4).

## 4. Honest limits

The twin knows only what crossed the MIDI cable. The page has to say so, because a confident-looking UI that is wrong is worse than a sparse one.

- **It knows what Whiplash sent.** Every value shown is "last sent" unless something better is known. Until then a param reads `--`, not a guessed default. The kit's real values at load time are unknown.
- **Changes made on the unit are visible only while its MIDI input is read.** A knob turned on the unit, a pattern changed there, or a panel mute shows up only while play-along reads the input, and only with the unit's PORT CONFIG sending it (README "Play along"; reference §10 MUTE DEST). With input closed, the page shows `UNIT INPUT OFF · changes on the unit are invisible`.
- **Reloads on the unit are invisible.** [FUNC] + [NO], a pattern change or a kit reload resets the unit without telling MIDI (reference §2.2). The page can't detect this. It offers a "resync" that re-sends the twin's state, and only on a click.
- **It can't see sample contents.** There are no names, waveforms or pool listings, only slot numbers, user labels and kit-scan guesses (§8).
- **It can't see the unit's own sequence.** Trigs, p-locks, conditions and song mode on the unit are opaque. With transport receive on, MIDI Start also runs the unit's own pattern (reference §0 #5), so the existing advice stands: select an empty pattern, or use clock-only mode.
- **Per-track meters are MIDI-derived.** USB audio is one stereo pair, normally MAIN (reference §14).

## 5. Architecture

### 5.1 Pieces

- **Web app (Next.js, Vercel):** a static client app. Vercel only hosts the code: no device data, conversation or state reaches a Vercel server, and there are no accounts in phase 1.
- **Web MIDI (in the browser):** device detection and, in standalone mode, all MIDI out and in.
- **Local engine (Python, today's `engine.py`):** owns the clock, the sequencer, the library, arrangements and listening. It is reached through the bridge.
- **Agents:** Hermes through the existing plugin, and later any agent through an MCP adapter. Both call the same engine verbs.

### 5.2 Modes

| | **Standalone** (phase 1) | **Bridged** (phase 2) |
|---|---|---|
| Who owns the clock and port | a small sequencer in the browser, sending over Web MIDI | the local Python engine, over its own rtmidi port |
| Agent | none | Hermes / MCP, through the engine |
| Browsers | Chrome, Edge | any with WebSocket/SSE, **Safari included**, because the engine does the MIDI |
| What the page sends | MIDI directly | verbs to the engine; it opens no MIDI output |

**One rule:** one clock owner and one MIDI writer at a time. When the bridge connects, the page stops its own sequencer on a bar line and hands over: it sends the engine its pattern, mutes and tempo, then closes its Web MIDI output. Two writers would double the clock and fight over CCs.

**Phase 1 implication:** manual trigs, tempo and transport need a clock source, so phase 1 includes a **minimal browser sequencer**. It plays a 16-step grid on 16 channels, sends clock and transport, mutes, and params. It doesn't do genres, arrangement, harmony or listening; those stay in the engine. To keep the clock steady, it schedules ahead with Web MIDI's timestamped `send(data, timestamp)` from a worker rather than sending on a `setTimeout`. Background-tab timer throttling is a known risk to measure (§6).

### 5.3 Long-term: one engine in the browser?

| | **A. Local engine + bridge** (recommended, phase 2) | **B. Sequencer moved into the browser** |
|---|---|---|
| Engines | Two: a thin browser sequencer for standalone use, and the full Python engine | One, shared by UI and agent |
| Work | Bridge + verb API. The engine, its 26 tools and its tests are reused as they are | Port the sequencer, library, harmony, arrangement and taste to TypeScript, or run the engine in Pyodide with Web MIDI as the port. Re-earn the test suite and the clock-jitter work |
| Clock | rtmidi on a dedicated thread, already measured (docs/testing/clock-jitter.md) | Browser scheduling. Needs ahead-of-time timestamps, and throttles when the tab is hidden |
| Agent path | agent → plugin/MCP → engine | agent → local adapter → page. The page has to be open for the agent to play |
| Safari | works in bridged mode | no Web MIDI, so it doesn't work at all |
| Listening | numpy on the engine | Web Audio in the page (no numpy) |

**Recommendation:** build A now. Keep the browser sequencer deliberately small, and treat its feature list as a ceiling, not a roadmap. Revisit B only if standalone use without an engine becomes the main way people play. The trigger would be people asking for agent play without a local install, and that would also need a hosted agent, which this doc doesn't propose.

### 5.4 The bridge

- **Transport:** the engine already serves SSE frames on 127.0.0.1 with a Host check (`view.py`). The cheapest bridge is that same stdlib server plus `POST /verb`, with no new dependency. A WebSocket is the alternative if two-way latency turns out to matter, at the cost of a new dependency. Open question Q2.
- **Verbs = tools.** The page calls the same verb set as the agent tools (`whiplash_mute_track`, `whiplash_set_param`, `whiplash_play_pattern`, ...), through the same validation in `tools.py`. Bad input from the UI changes nothing, exactly as from the agent. The page gets no lower-level "send MIDI" verb.
- **UI control bypasses the agent, by design.** A click calls the engine directly, with no LLM in the loop, so it is immediate and deterministic. The change is tagged `source: "ui"` in the engine's change log, so `whiplash_status(review)` and the taste hints count it as the user's move (the review already separates "by you" from "by Whiplash"). The agent learns about it on its next status call.
- **Conflicts:** changes from either side land on bar lines in arrival order. A UI move on a param the agent is ramping stops that ramp, just as grabbing the knob does today (`yielded_to_user`).

### 5.5 Bridge security

A public website talking to a process that drives hardware on your desk needs locking down:

- **Localhost only.** The engine binds 127.0.0.1 and never 0.0.0.0. It keeps the existing Host check, which blocks DNS rebinding.
- **Origin allow-list.** It accepts the production origin and `http://localhost:<dev>` only, with no wildcard CORS. Vercel preview URLs are refused unless explicitly added for a dev session.
- **Pairing token.** The engine generates a random token per run. `whiplash_open_view`, or a `whiplash pair` command, opens the app with the token in the URL **fragment** (`#pair=…`), which browsers never send to Vercel. The page keeps it in sessionStorage. Every verb and the state stream require it, because the state stream carries the conversation.
- **Bounded even if the page is compromised.** If the hosted code were tampered with, it could only call the verb set, and `Engine.send()`'s allow-list still refuses SysEx and program change. As a privacy fallback, the engine can also serve the built app itself on 127.0.0.1, as `view.html` is served today.
- **Browser gating.** Chrome is rolling out Local Network Access permission prompts for public sites reaching loopback. Expect a prompt on first connect, and verify the exact behaviour when building.

## 6. Web MIDI and browser constraints

- **Support:**
  - Chrome and Edge on desktop are the target.
  - Firefox has Web MIDI only behind a site-permission add-on prompt, so it is out of scope for v1.
  - Safari has no Web MIDI, so it is bridged mode only.
  - Mobile is out of scope.
- **Permissions:** Web MIDI needs a secure context (Vercel's HTTPS) and a user prompt. The app requests **`{sysex: false}`**, so the browser itself refuses SysEx: a second lock behind ours. Program change is still possible in Web MIDI, so the page's send wrapper mirrors `Engine.send()`'s allow-list (note on/off, CC, clock, start/stop/continue) plus `ccmap`'s blocked CCs and NRPNs.
- **Detection:** the page matches a port name containing "Digitakt", case-insensitively, the same rule the engine uses. It hot-plugs through `onstatechange` and shows `PORT LOST` on unplug. The exact port name per OS is an open hardware question (reference §14).
- **Timing:** it schedules with timestamps 50-100 ms ahead. A hidden tab may throttle the scheduling loop, so the page warns `KEEP THIS TAB VISIBLE` while it owns the clock. That warning goes away in bridged mode.
- **Port sharing:** on Windows a MIDI port can be exclusive to one app, which is one more reason for the one-writer rule.
- **Audio:** getUserMedia with echo cancellation, noise suppression and AGC turned off, as the visualiser does today. It needs USB CONFIG = USB AUDIO/MIDI on the unit (reference §14).

## 7. Code layout and the Hermes plugin

- **Now:** the web app lives in `web/` in this repo, with Vercel's root directory set to `web/`. The Python package and `plugin.yaml` stay at the root, so the catalog listing (pinned to the root at `3f4f883`, with no subdir field) keeps working. pytest has to ignore `web/`.
- **Later layering:**
  - **core:** the engine, library, harmony, arrangement and safety rails, with no Hermes imports.
  - **adapters:** the Hermes plugin (`tools.py`, `chat.py`, `plugin.yaml`), an MCP server, and the web bridge. Each one is a thin layer over the same verbs.
  - **web app:** the client.

  A root `plugin.yaml` is kept so the listing still resolves. Splitting the code into core and adapters is its own PR and changes no behaviour.
- **`view.html`:** stays as the offline, no-Vercel visualiser until the web app reaches parity in bridged mode. Retiring it is Phil's call (Q8).

## 8. Samples and the SysEx decision (phase 3)

| | **(a) Read-only SysEx, for listing only** | **(b) A local sample library as the source of truth** |
|---|---|---|
| What it gives | real pool names and slot contents from the unit | names, tags, previews and waveforms from files on the computer, mapped to slots by the user or by a kit scan |
| Risk | Elektron's protocol is undocumented, and the unit "is continuously listening for SysEx data" and can store what it receives (reference §14). A malformed or misread message is a real risk to projects | no device risk. It can drift from what is actually loaded in the pool |
| Rules to change | needs an explicit change to the never-SysEx rule, a separate audit, and request-only (dump-request) messages behind an allow-list of exact bytes | none. Reading local files is fine; uploads stay out (Transfer's job) |
| Hardware verification | every message checked on a unit, recorded in the reference | the kit scan and slot select, both already in the checklist |

**Until Phil decides:** slot-number select (CC 19) plus labels. In the page, a slot picker shows the user's labels and the kit-scan guesses.

## 9. Aesthetic

- **A dark instrument, functional first.** It should read as a piece of gear on a desk at night, not a SaaS dashboard: near-black panels, one or two accent colours used only for live state (playhead, ramps, the agent's actions, clipping), and tabular monospace numerals.
- **Elektron-faithful, not a copy.** It uses the Digitakt's mental model: 16 trig keys in four groups of four, the parameter pages, and a terse uppercase vocabulary (`FLTR`, `AMP`, `LVL`). It doesn't use Elektron's logo, panel artwork, screen font or industrial design. "Digitakt II" is used only to name the device it works with.
- **It never lies.** It keeps the visualiser's honesty labels (`AUDIO` vs `MIDI`, `VIRTUAL · SILENT`, last-sent vs heard vs assumed), so a still frame is still truthful.
- **No purple gradients, glassmorphism, sparkle icons or generic AI styling.** The agent is shown as one more player on the timeline, not as a chat assistant bolted on.
- **Motion is tied to the clock or to an event, as in visualiser-design.md §4.5.** It respects `prefers-reduced-motion`.

## 10. Safety rules carried over

All of these apply to every mode, including standalone, where the page enforces them itself:

- **No SysEx**, pending §8. Web MIDI is requested with `sysex: false`.
- **No program change** (it switches patterns).
- **No bank select, no sample-bank CC 24, no sample NRPNs, no raw NRPN data CCs** (`ccmap.BLOCKED_CCS` / `BLOCKED_NRPNS`).
- **No project, pattern, kit or preset writes. No +Drive access and no file transfer.**
- **Leave Digitakt slots 1-3 untouched** (roadmap cross-cutting rules).
- **Validate before touching the beat:** bad input from the UI or the agent changes nothing that is playing.
- **Every musical change lands on Whiplash's clock,** on a bar line where the tool does that today.
- **No hardware claims without a test on a unit,** recorded in the reference. Each phase adds its checks to [docs/testing/hardware-checklist.md](../testing/hardware-checklist.md).

## 11. Open questions for Phil

1. **SysEx:** (a) read-only listing or (b) a local library (§8)? Or neither for now?
2. **Bridge transport:** extend the existing stdlib SSE server with `POST /verb` (no new dependency), or use a WebSocket (adds a dependency)?
3. **Phase 1 scope:** is the minimal browser sequencer in §5.2 right? Or should phase 1 be control only (mutes, params, tempo, transport) with the unit as the sequencer, and trigs editable only once bridged?
4. **Repo layout:** `web/` in this repo (recommended), or a separate repo?
5. **Hosting:** which Vercel account and domain? Do preview deployments ever get bridge access?
6. **Standalone state:** may the page remember a grid or kit map in browser storage? That isn't a unit write, but it is persistence.
7. **The conversation on a hosted page:** is the conversation feed acceptable in the Vercel-served page (it never leaves the browser), or only on a locally served page?
8. **`view.html`:** keep it alongside the web app, or retire it at phase 2 parity?
9. **MCP adapter:** does it come with phase 2, or after?
10. **Windows:** the engine has no virtual port there, but Web MIDI works. Is Windows in scope for standalone mode?
11. **Engine in the browser (§5.3 B):** park it with the trigger stated there, or set a date to revisit?
