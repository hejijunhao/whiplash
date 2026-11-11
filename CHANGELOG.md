# Changelog

## Unreleased: visualiser (`feat/visualiser`, still 0.3.0)

Added
- `whiplash_open_view` / `whiplash_close_view`: a live, read-only web page served on `127.0.0.1` and opened in the default browser. It shows:
  - **Tracks:** one lane per track in use, with the current bar's notes on a tilted runway grid, a playhead, a 4-bar minimap, mutes, drops, fills, density, param values and animated ramps.
  - **Transport:** a large BPM readout, the bar, pattern, queued switch and port status.
  - **Analyser:** spectrum, scope and L/R meters from the Digitakt's USB audio via `getUserMedia`, or an honestly labelled MIDI fallback.
  - **Conversation:** the live Hermes conversation, streamed word by word, with tool calls behind a toggle.
  - **Log:** recent Whiplash actions.
- Hermes conversation hooks: `on_session_start`, `pre_llm_call`, `on_stream_start`/`delta`/`end`, `pre_tool_call`, `post_tool_call` and `post_llm_call`. They keep in-memory observers only and return `None`. Without hook support, the view falls back to a read-only poll of `~/.hermes/state.db`.
- The engine publishes the playhead (`position`) and the current bar's hits (`bar_hits`) from the clock thread by plain assignment, and `view_state()` gives a lock-short copy of the state for the view.
- `docs/visualiser-design.md`: the approved design.
- CI also runs on `feat/visualiser`.

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
