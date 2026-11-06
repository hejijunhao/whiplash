# Whiplash 🥁

A [Hermes Agent](https://hermes-agent.nousresearch.com) plugin that lets your agent **jam on an Elektron Digitakt II** over USB MIDI. Ask for "something dark at 128", "mute the hats", "open the filter on the bass", and Hermes plays it live on the hardware: beats on tracks 1-8, MIDI clock and transport, live CC/NRPN sound changes, mutes, and tempo.

No Digitakt? Whiplash opens a virtual MIDI port named **Whiplash** so anyone can try it with a DAW or soft synth (macOS and Linux; Windows has no virtual MIDI ports).

## Tools

Every tool is prefixed `whiplash_` so it can't collide with another plugin's tools.

| Tool | What it does |
| --- | --- |
| `whiplash_list_midi_ports` | Lists MIDI ports and whether a Digitakt II is connected. |
| `whiplash_play_pattern` | Starts a beat by `genre` (`deephouse` 122 BPM, `soul` 86, `techno` 130, `breaks` 132) or `mood` (groovy, chill, dark, energetic, ...). Optional `bpm` (30-300), `bars` (1-512; omit to loop), `port`. Runs in a background thread with MIDI clock and Start/Stop. Replaces whatever is playing and resets mutes. |
| `whiplash_set_param` | Live sound change on one track: a friendly name (`filter_cutoff`, `resonance`, `decay`, `volume`, `level`, `pan`, `overdrive`, `reverb_send`, `delay_send`, ...), a raw `cc`, or a raw `nrpn: [msb, lsb]`. Exactly one of the three. |
| `whiplash_mute_track` / `whiplash_unmute_track` | Live mute. `hardware: true` also flips the unit's own track mute (CC 94). |
| `whiplash_set_tempo` | Live tempo change (30-300 BPM); the clock follows so the Digitakt's delay/LFOs stay in sync. |
| `whiplash_stop` | Note-offs, All Notes Off on channels 1-8, transport Stop. Resets mutes. Works as a panic button when nothing is playing. |
| `whiplash_status` | Port, pattern, BPM, bar, muted tracks, whether output is the silent virtual fallback, and `last_error` if the sequencer stopped on a fault. |

Track roles (same for all genres): 1 kick, 2 rim/snare, 3 clap, 4 closed hat, 5 open hat, 6 bass, 7-8 chords/chops/stabs. Load samples to match.

### Behaviour worth knowing

- **Values.** `param` and `cc` take 0-127. `nrpn` takes the full 14-bit value 0-16383, always sent as data MSB = `value >> 7`, LSB = `value & 127`. To send a 7-bit amount `v` over NRPN, pass `v * 128`.
- **Mutes are per performance.** They reset on `whiplash_stop` and whenever a new pattern starts, and the result lists them in `mutes_cleared`. Mute after starting a pattern, not before. If Whiplash muted a track on the unit itself (CC 94), it also unmutes it there on unmute, stop, and exit.
- **Virtual fallback is loud.** If no Digitakt is found, Whiplash plays into the virtual port and every tool result carries a `warning` saying the hardware is silent and how to switch. To move to the unit once it is connected, call `whiplash_play_pattern` with `port` set to the name from `whiplash_list_midi_ports`.
- **Bad input never touches the beat.** An out-of-range `bpm` or `bars` is rejected before the running pattern is stopped.

## Install

```bash
hermes plugins install hejijunhao/whiplash --ref <full 40-character commit SHA>
hermes plugins enable whiplash
hermes plugins list                          # whiplash -> enabled
```

Hermes installs the Python dependencies (`mido`, `python-rtmidi`) declared in `pyproject.toml` / `plugin.yaml`, after asking for consent. On Linux `python-rtmidi` also needs the ALSA runtime (`sudo apt install libasound2`; `libasound2t64` on newer Debian/Ubuntu).

For development, symlink a checkout instead and install the dependencies into the Python environment Hermes runs in:

```bash
git clone https://github.com/hejijunhao/whiplash ~/whiplash
ln -s ~/whiplash ~/.hermes/plugins/whiplash
```

Restart Hermes (`hermes`), then ask: *"Play some deep house on my Digitakt."*

Whiplash's `register()` only registers schemas. The MIDI port and sequencer thread open on the first tool call, so loading stays well under Hermes' 10 s plugin-load limit.

## Digitakt II setup

On the unit: **SETTINGS > MIDI CONFIG**
- **PORT CONFIG**: INPUT FROM = USB (or MIDI+USB). Turn **RECEIVE NOTES** and **RECEIVE CC/NRPN** on.
- **SYNC**: **CLOCK RECEIVE** and **TRANSPORT RECEIVE** on if the Digitakt's sequencer/FX should follow Whiplash.
- **CHANNELS**: TRACK 1-8 CHANNEL = 1-8 (the default).

Notes trigger each track's sample (note 60 = original pitch). Whiplash plays its own pattern, so start from an empty pattern if you don't want the unit's sequence playing too.

## Safety and disclosures

- **Controls hardware.** Whiplash sends live MIDI to whatever port it opens: notes, clock, transport Start/Stop, and CC/NRPN parameter changes. Parameter changes alter the sound of the pattern loaded on the unit until you reload it; nothing is saved to the unit by Whiplash.
- **Never sends SysEx or program changes.** `Engine.send()` only allows note on/off, control change, clock, start/stop/continue. Anything else raises.
- Sample/bank select (CC 19/24, NRPN 1:3, 1:8, 1:9) and bank-select/NRPN-data CCs are blocked from `whiplash_set_param`, so the agent can't reassign samples or touch projects, sample slots, or the +Drive.
- **Runs a background thread** (the sequencer) inside the Hermes process while a pattern plays. It is a daemon thread, started on demand and stopped by `whiplash_stop`.
- **Cleans up on exit.** `whiplash_stop`, every sequencer exit, and a normal Hermes exit (via `atexit`) send note-offs, All Notes Off, and transport Stop, then close the port. A hard kill (`SIGKILL`, power loss) can't be intercepted; press Stop on the unit if that happens.
- No subprocess, shell, network, files, or secrets.

## Tests

```bash
uv sync && uv run pytest -q          # or: pip install mido python-rtmidi pytest pyyaml && python -m pytest -q
```

54 tests: manifest and dependency declarations, patterns, timing/clock, input validation, single panic per stop, mute lifecycle, CC/NRPN encoding, SysEx refusal, virtual-fallback warnings, fault reporting, the exit hook, and concurrent `play` calls. One test does a real virtual-port loopback through rtmidi; it skips where the machine has no MIDI system (for example a Linux box without the ALSA sequencer). CI runs the suite on Linux and macOS (`.github/workflows/tests.yml`).

Everything above runs against fake or virtual ports. Timing and the CC map on a real Digitakt II are checked by hand.

## 90-second demo script

1. (0-10 s) Digitakt on screen, USB to laptop. Terminal: `hermes plugins list` shows **whiplash enabled**.
2. (10-20 s) "Is my Digitakt connected?" → `whiplash_list_midi_ports` finds *Elektron Digitakt II*.
3. (20-35 s) "Play some groovy deep house." → `whiplash_play_pattern`: kick, hats, bass, and chords at 122 BPM, swing 55%.
4. (35-50 s) "Close the filter on the chords, then open it." → `whiplash_set_param filter_cutoff` on 7 and 8.
5. (50-60 s) "Drop the kick… bring it back." → `whiplash_mute_track 1` / `whiplash_unmute_track 1`.
6. (60-75 s) "Make it darker and faster." → `whiplash_play_pattern` switches to techno at 130.
7. (75-85 s) "Push it to 136." → `whiplash_set_tempo`, Digitakt delay stays locked to the clock.
8. (85-90 s) "Stop." → `whiplash_stop`: clean stop, no hanging notes.

## Hermes plugin catalog

- The catalog entry pins this repo to a full 40-character commit SHA.
- Dependencies are declared with floors and ceilings in `pyproject.toml` (mirrored in `plugin.yaml`), and `requires_hermes` is `>=0.19`.
- Registers eight tools through `ctx.register_tool` only: no hooks, no tool overrides, no core patching.
- The install-time scan should come back **safe**: no subprocess/shell, network, or credential access.

See [CHANGELOG.md](CHANGELOG.md) for what changed between versions.

## License

MIT
