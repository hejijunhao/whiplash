# Changelog

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
