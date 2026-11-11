# Changelog

## 0.5.0

Fixes from the second live session on a Digitakt II (Nov 11 2026): generated basslines no longer repitch samples far below their own pitch, results say where each line sits, and the agent guidance ships with the plugin. 15 tools.

Added
- **Native-pitch register.** Manual 8.4 (OS 1.15A, p. 25): MIDI notes 16-84 play the track's sample chromatically, with C5 = MIDI 60 at the sample's own pitch. `patterns.register()` lifts each generated melodic part by whole octaves at load time until its median is no more than 7 semitones below 60, keeping the intervals. The techno bass moves from 41 to 53 (the -7 that tune +12 fixed by ear), the soul and breaks basslines move up an octave, deep house is unchanged, and drums are never moved. The note tables stay as written in `patterns.RAW`.
- `whiplash_transpose(track, semitones | octaves)`: absolute, ±48 semitones, from the next bar line, clamped to 16-84. Carries across pattern switches like mutes; `whiplash_stop` and a fresh start reset it.
- `transpose` on `whiplash_play_pattern` (`{"6": -12}`): from the first bar of a fresh start, or from the switch bar of a queued one.
- `pitch` per melodic, transposed or tuned track: low/high notes with Elektron names, `semitones_from_native` (including `tune - 64` when Whiplash sent CC 16), `transpose`, `tune` and `register_shift`.
- `tracks` in `whiplash_status` and in `whiplash_play_pattern` results: role marked `(assumed)`, last sample `slot` and `tune` Whiplash sent (`null` until sent), `transpose`, `pitch`, mute, `part` and `last_cc`, plus `roles_assumed`, `kit_note` and `pitch_note`. A queued result describes the next pattern with the transposes it will play with.
- `amp_mode` named param: CC 87, 0 = AHD, 1 = ADSR, a switch (manual B.5 p. 110; midi.guide). `amp_hold` documents 127 = NOTE (manual 11.7 p. 56; midi.guide). 38 named params.
- Bundled skill `whiplash:digitakt` (`skills/digitakt/SKILL.md`), registered with `ctx.register_skill` when the Hermes build has it; older builds still load the tools. Tool descriptions point to it.
- README "Updating" section: run `hermes gateway restart` after updating, and delete any stale local `whiplash-digitakt` skill.

Not in this release (next, v0.5.1): `whiplash_write_part` (notes, rhythm presets, lock-to-kick, note lengths).

### Also in 0.5.0: the live visualiser (merged from `feat/visualiser`)

Added
- `whiplash_open_view` / `whiplash_close_view`: a live, read-only web page served on `127.0.0.1` and opened in the default browser. It shows:
  - **Tracks:** one lane per track in use, with the current bar's notes on a tilted runway grid, a playhead, a 4-bar minimap, mutes, drops, fills, density, param values and animated ramps.
  - **Transport:** a large BPM readout, the bar, pattern, queued switch and port status.
  - **Analyser:** spectrum, scope and L/R meters from the Digitakt's USB audio via `getUserMedia`, or an honestly labelled MIDI fallback.
  - **Conversation:** the live Hermes conversation, streamed word by word, with tool calls behind a toggle.
  - **Log:** recent Whiplash actions.
- Hermes conversation hooks: `pre_llm_call`, `on_stream_start`/`delta`/`end`, `pre_tool_call`, `post_tool_call` and `post_llm_call`. They keep in-memory observers only, return `None` and ignore subagent sessions. Without hook support, the view falls back to a read-only poll of `~/.hermes/state.db`.
- The engine publishes the playhead (`position`) and the current bar's hits (`bar_hits`) from the clock thread by plain assignment, and `view_state()` gives a lock-short copy of the state for the view.
- `docs/visualiser-design.md`: the approved design.
- The page shows the v0.4 transport mode (`START/STOP` or `CLOCK ONLY`) and each track's last selected sample slot.
- CI also runs on `feat/visualiser`.

## 0.4.0

Two fixes from the first live session on a Digitakt II: tracks can now switch to another sample already in the project, and the beat can run on clock alone so the unit's own pattern doesn't layer in. 12 tools.

Added
- `whiplash_select_sample(track, slot)` and the named param `sample_slot` (aliases `sample`, `smp`, `slot`): sends Sample Slot Select, CC 19, slot 0-127 within the sample bank selected on the unit. Verified in the manual's Appendix B (B.3, p. 109; B.9, p. 113) and on midi.guide. It only picks among samples already loaded in the project pool: Whiplash can't list, preview or load samples. Out-of-range slots are rejected, and it can't be ramped.
- `send_transport` on `whiplash_play_pattern`, with a `WHIPLASH_SEND_TRANSPORT` env default. `true` (the default, as before) sends Start, clock and Stop. `false` sends clock only: no Start, and no Stop either, so Whiplash can't halt a pattern running on the unit. Changing it while playing restarts instead of queueing. `whiplash_status` shows `transport_mode`.
- `overlap_warning` on every `whiplash_play_pattern` result (start and queued switch). MIDI Start also starts the Digitakt's own sequencer, so trigs in the pattern selected on the unit play on top; the warning tells the user to select an empty pattern, or to use clock only.
- CI also runs on `feat/v04`.

Changed
- **Sample policy relaxed, narrowly.** CC 19 is now sent, but only through the named param, so raw `cc: 19` is still refused. Sample bank select (CC 24, NRPN 1:9), the sample NRPNs 1:3 and 1:8, MIDI bank select, SysEx and program change all stay blocked.
- Machine type (Oneshot, Werp, ...) is not controllable: neither the manual nor midi.guide documents a CC or NRPN for it.
- README and the catalog drafts say what sample select can and can't do, and add the empty-pattern advice.

## 0.3.0

Whiplash goes from playing a beat to performing it: three new tools (11 in all), and pattern changes that land on the bar.

Added
- `whiplash_ramp_param`: sweeps a named param or raw CC `from` → `to` over `beats` or `bars`, advanced on the sequencer's MIDI clock. Curves linear, exp and log. It sends only when the integer value changes, runs several ramps at once (a new one on the same track/param replaces the old), and cancels by id or `all`. `whiplash_stop` cancels all ramps, and `whiplash_set_param` on the same param cancels that ramp. Needs a pattern playing.
- `whiplash_mutate`: live `density` (thin/thicken), `fill` (one-bar drum fill on the next bar), `swing` (50-80 %), `humanize` (bounded, never drifts), `drop` (silence tracks for N bars with auto-return and optional fill), and `reset`. Deterministic, seeded, and timed to the bar.
- `whiplash_list_params`: the named Digitakt II parameter map, grouped, with ranges, centres and aliases.
- Bar-quantized pattern switching. `whiplash_play_pattern` while playing queues the new pattern for the next bar line (`mode: "queued"`, `switch_at_bar`) without a Stop/Start. Mutes, ramps and scheduled drops/fills carry over; density, swing and humanize reset. A second queued call replaces the first.
- Hot-plug notify. While on the virtual fallback port, every tool result carries `device_available` and a notice once a Digitakt appears. Whiplash never switches on its own. Port enumeration is rate-limited to every 2 s and never runs in the clock thread.
- Port loss. If a send fails (USB unplugged), the port is dropped, `whiplash_status` shows `port_lost`, and the next call re-detects and reopens it.
- `docs/catalog-entry.yaml` and `docs/catalog-pr.md`: drafts for the Hermes plugin catalog submission.
- CI also runs on `feat/v2`.

Changed
- **Parameter map rewritten** from the Digitakt II manual (Appendix B), cross-checked with midi.guide: 36 params across track, src, filter, amp, fx and lfo, with ranges and centres. Named params are sent as CC only, because several NRPN addresses disagree between the two sources. Out-of-range values clamp into the param's range (switches like `mute` and `play_mode` reject instead). Unknown names get close-match suggestions. The old names keep working as aliases (`level`, `volume`, `cutoff`, `filter_cutoff`, `resonance`, `filter_resonance`, `decay`).
- **Mutes now carry over** a live pattern switch. They still reset on `whiplash_stop` and on a fresh start.
- `whiplash_play_pattern` returns `mode` (`started` or `queued`). `whiplash_stop` also returns `ramps_cancelled`.
- Stopping mid-beat sends note-offs only for notes actually sounding, with no stray note-offs for note-ons that never went out.
- The MIDI backend error suggests the ALSA runtime when `libasound` is missing.

## 0.2.0

**Breaking:** every tool is now prefixed `whiplash_` (`play_pattern` → `whiplash_play_pattern`, `stop` → `whiplash_stop`, and so on), so Whiplash can't collide with another plugin's tools.

Fixed
- `whiplash_play_pattern` validates `bpm` (30-300) and `bars` (1-512) before touching the running beat. A negative tempo used to spin the sequencer and flood the port with clock messages.
- NRPN values are always sent as 14 bits (MSB = `value >> 7`, LSB = `value & 127`). Values up to 127 used to be sent as the MSB alone, so 127 was louder than 128.
- Stopping sends one panic (All Notes Off + transport Stop) instead of two.
- Mutes reset on stop and when a new pattern starts, and the result reports them in `mutes_cleared`. A forgotten mute used to silently carry into the next beat. Mutes Whiplash set on the unit itself (CC 94) are released at the same time.

Added
- Exit cleanup: a normal Hermes exit silences the unit, releases hardware mutes, and closes the port.
- A transport lock, so overlapping `play`/`stop` calls can't leave two sequencers running.
- A `warning` on every tool result while output is going to the virtual fallback port.
- `last_error`, `fallback`, and `hardware_muted` in `whiplash_status`.
- `whiplash_set_param` takes exactly one of `param`, `cc`, `nrpn` and rejects a bad request before sending anything.
- `pyproject.toml` with bounded dependencies, `python_dependencies` and `requires_hermes` in `plugin.yaml`.
- GitHub Actions workflow running the tests on Linux and macOS.

Changed
- Author metadata is `pgbouncer`. `requirements.txt` is replaced by `pyproject.toml`.

## 0.1.0

First version: eight tools, four genres, MIDI clock and transport, CC/NRPN parameters, mutes, tempo, virtual-port fallback.
