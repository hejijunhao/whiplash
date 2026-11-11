# Whiplash 🥁

A [Hermes Agent](https://hermes-agent.nousresearch.com) plugin that lets your agent **jam live on an Elektron Digitakt II** over USB MIDI. Ask for "something groovy at 122", "slowly open the filter on the bass", "drop the kick for two bars with a fill", "switch to techno on the next bar", and Hermes plays it on the hardware: beats on tracks 1-8 with MIDI clock and transport, bar-quantized pattern switches, named sound parameters, clock-synced sweeps, live fills, drops, density, swing and humanize, mutes, and tempo.

The timing lives in the plugin, not the model. Hermes makes one validated tool call ("ramp the cutoff over 8 bars"); Whiplash's sequencer does the musical part on its own MIDI clock, so sweeps stay smooth and switches land on the one however long the model takes to answer.

No Digitakt? Whiplash opens a virtual MIDI port named **Whiplash** so anyone can try it with a DAW or soft synth (macOS and Linux; Windows has no virtual MIDI ports).

## Tools

Every tool is prefixed `whiplash_` so it can't collide with another plugin's tools.

| Tool | What it does |
| --- | --- |
| `whiplash_list_midi_ports` | Lists MIDI ports and whether a Digitakt II is connected. |
| `whiplash_list_params` | The named Digitakt II parameters, grouped (track, src, filter, amp, fx, lfo), with CC, range, centre and aliases. |
| `whiplash_play_pattern` | Starts a beat by `genre` (`deephouse` 122 BPM, `soul` 86, `techno` 130, `breaks` 132) or `mood` (groovy, chill, dark, energetic, ...). Optional `bpm` (30-300), `bars` (1-512; omit to loop), `port`. While something plays, the new pattern is **queued and swaps in on the next bar line** without stopping the clock. |
| `whiplash_set_param` | Instant sound change on one track: a named param (sent as CC, clamped into its range), a raw `cc`, or a raw `nrpn: [msb, lsb]`. |
| `whiplash_ramp_param` | Sweeps a named param (or raw CC) `from` → `to` over `beats` or `bars`, advanced on the MIDI clock. `curve`: linear, exp, log. Returns a ramp id; `cancel: "<id>"` or `"all"`. |
| `whiplash_mutate` | Live edits to the running pattern: `density` (thin/thicken), `fill`, `swing`, `humanize`, `drop` (with auto-return), `reset`. |
| `whiplash_mute_track` / `whiplash_unmute_track` | Live mute. `hardware: true` also flips the unit's own track mute (CC 94). |
| `whiplash_set_tempo` | Live tempo change (30-300 BPM); the clock follows so the Digitakt's delay/LFOs stay in sync. |
| `whiplash_stop` | Note-offs, All Notes Off on channels 1-8, transport Stop. Resets mutes, ramps, mutations and any queued switch. Works as a panic button when nothing is playing. |
| `whiplash_status` | Port, pattern, BPM, bar, queued switch, mutes, active ramps with progress, mutations, whether output is the silent virtual fallback (and whether a Digitakt has appeared), and `last_error`. |

Track roles (same for all genres): 1 kick, 2 rim/snare, 3 clap, 4 closed hat, 5 open hat, 6 bass, 7-8 chords/chops/stabs. Load samples to match.

### How live changes are timed

- **Pattern switches** land on the next bar line (`mode: "queued"`, `switch_at_bar`). No Stop/Start is sent, so the Digitakt's FX stay locked. A second call before the switch replaces the queued one. A `bpm` in that call applies at the switch; without one the new genre's tempo is used. `bars` counts from the switch. Passing a different `port` restarts on that port instead.
- **What carries across a switch:** mutes, running ramps, and scheduled drops/fills. **What resets:** density, swing and humanize (they were edits of the old pattern). `whiplash_stop` resets everything.
- **Ramps** advance one step per MIDI clock tick (24 per beat) in the sequencer thread, and send a CC only when the integer value changes. So a ramp over 8 bars takes 8 bars at any tempo, and a 0→127 sweep is at most 128 messages. Ramps on different track/param pairs run together; a new ramp on the same pair replaces the old one, and `whiplash_set_param` on that pair cancels it. `from` defaults to the last value Whiplash sent; if it has sent nothing for that param yet, `from` is required. Ramps need a pattern playing, because they are clocked by the sequencer. `exp` starts slow and finishes fast (cubic ease-in); `log` is the reverse.
- **Mutations** apply from the next bar (swing from the next step). `density` takes −1 (thinnest) … 0 (original) … +1 (busiest), or `thin` (−0.5) / `thicken` (+0.5). The amount is absolute, so repeating `thin` doesn't keep thinning. Thinning drops the weakest offbeat hits first, and thickening adds quiet ghost notes on empty 16ths in the bar's own notes. `fill` plays a one-bar fill on the next bar: the kick sits out the last beat, the snare rolls up, claps push, and hats ratchet in 32nds. `drop` silences tracks for N bars from the next bar, then brings them back by itself; `fill: true` adds a drum fill on the last dropped bar. `humanize` loosens velocity (±16 at 1.0) and timing (±¼ clock tick) per hit, never cumulatively, so the groove never drifts. All randomness is seeded, so the same calls give the same result.

### Values

- Named params and raw `cc` take 0-127. Named params clamp into their own range (for example `tune` 4-124, `sample_start` 0-120) and say `clamped: true`; switches (`mute`, `play_mode`) reject out-of-range values instead.
- `nrpn` takes the full 14-bit value 0-16383, sent as data MSB = `value >> 7`, LSB = `value & 127`. To send a 7-bit amount `v` over NRPN, pass `v * 128`.
- Mutes reset on `whiplash_stop` and on a fresh start, so mute after starting a pattern. If Whiplash muted a track on the unit itself (CC 94), it unmutes it there on unmute, stop, and exit.
- Bad input never touches the beat: every tool validates its arguments before changing anything.

### Parameter map

36 per-track parameters sent as CC on the track's channel. Source: *Elektron Digitakt II User Manual*, Appendix B: MIDI (OS 1.15A, pp. 109-113; the OS 1.17 manual keeps the same values), cross-checked with [midi.guide](https://midi.guide/d/elektron/digitakt-ii/). The CC numbers agree between the two sources.

| Group | Params (CC) |
| --- | --- |
| track | `mute` 94 (0/1), `track_level` 95 |
| src | `tune` 16 (4-124, centre 64), `play_mode` 17 (0-3), `sample_start` 20 (0-120), `sample_length` 21 (0-120), `loop_pos` 22, `sample_level` 23 |
| filter | `filter_freq` 74, `filter_reso` 75, `filter_env_depth` 77 (centre 64), `filter_attack` 70, `filter_decay` 71, `filter_sustain` 72, `filter_release` 73, `filter_env_delay` 91, `filter_key_tracking` 92 (0-100) |
| amp | `amp_attack` 79, `amp_hold` 80, `amp_decay` 81, `amp_sustain` 82, `amp_release` 83, `amp_volume` 89, `pan` 90 (centre 64) |
| fx | `delay_send` 84, `reverb_send` 85, `chorus_send` 12, `overdrive` 57, `bit_reduction` 54, `sample_rate_reduction` 55 |
| lfo | `lfo1_speed` 102, `lfo1_depth` 109, `lfo2_speed` 112, `lfo2_depth` 119, `lfo3_speed` 78, `lfo3_depth` 86 (all centre 64) |

Common aliases work (`cutoff`, `resonance`, `decay`, `volume`, `level`, `srr`, `reverb`, ...), and an unknown name gets close-match suggestions.

Some notes on the map:
- **Machine dependent.** `sample_start` and `sample_length` (SRC knobs E/F) are start/length on Oneshot, Repitch and Stretch and other things on other machines. `filter_reso` (knob F) is feedback on Comb and gain on EQ.
- **High-res LFOs.** The LFO params have an LSB CC (58-63). Whiplash sends the MSB only, as a plain 7-bit value.
- **CC only, never NRPN.** Several NRPN addresses disagree between the manual and midi.guide (mute 1:101 vs 1:108, track level 1:100 vs 1:110, filter env depth 1:23 vs 1:26, filter base/width 1:51/1:52 vs 1:24/1:25). Raw `nrpn` is still available on `whiplash_set_param`.
- **FX channel out of scope.** FX-channel and global params (delay time, reverb decay, ...) are not named params; raw `cc` can reach them.

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

### Connecting mid-session

If Hermes started before the Digitakt was plugged in, Whiplash plays into the silent virtual port and every result carries a `warning`. Once the unit shows up, results also carry `device_available` and a `notice` saying how to move over. Whiplash never switches on its own; Hermes calls `whiplash_play_pattern` with that `port`. If the unit is unplugged mid-beat, the sequencer stops, `whiplash_status` shows `port_lost` and `last_error`, and the next call re-detects the port. An explicitly chosen virtual port (`port: "Whiplash"`) only gets a plain `device_available` field.

## Safety and disclosures

- **Controls hardware.** Whiplash sends live MIDI to whatever port it opens: notes, clock, transport Start/Stop, and CC/NRPN parameter changes. Parameter changes alter the sound of the pattern loaded on the unit until you reload it; Whiplash saves nothing to the unit.
- **Never sends SysEx or program changes.** `Engine.send()` only allows note on/off, control change, clock, start/stop/continue. Anything else raises.
- **Can't reassign samples.** Sample slot/bank select (CC 19/24, NRPN 1:3, 1:8, 1:9) and the bank-select/NRPN-data CCs are blocked in raw passthrough too, so the agent can't touch projects, sample slots, or the +Drive.
- **Runs a background thread.** The sequencer runs as a daemon thread inside the Hermes process while a pattern plays, and is stopped by `whiplash_stop`. Port enumeration for the Digitakt check happens on tool calls only, at most every 2 s, never in the clock thread.
- **Cleans up on exit.** `whiplash_stop`, every sequencer exit, and a normal Hermes exit (via `atexit`) send note-offs, All Notes Off, and transport Stop, then close the port. A hard kill (`SIGKILL`, power loss) can't be intercepted; press Stop on the unit if that happens.
- No subprocess, shell, network, files, or secrets.

## Tests

```bash
uv sync && uv run pytest -q          # or: pip install mido python-rtmidi pytest pyyaml && python -m pytest -q
```

98 tests, covering:
- manifest, catalog draft and dependency declarations
- the parameter map against the manual, plus aliases and clamping
- clock-synced ramps: no duplicate sends, replace, cancel, concurrency
- bar-quantized switches: no Stop/Start, mutes and ramps carried
- every mutate action, including drop auto-return and seeded determinism
- hot-plug notices and the explicit-virtual case, rate limiting, port loss and reopen
- input validation, single panic per stop, exit hook, SysEx refusal

One test does a real virtual-port loopback through rtmidi; it skips where the machine has no MIDI system. CI runs the suite on Linux and macOS (`.github/workflows/tests.yml`).

All of this runs against fake or virtual ports. Behaviour on a real Digitakt II is not covered by the test suite.

## 90-second demo: a build and drop

Digitakt II on screen, USB to the laptop, Hermes in a terminal beside it. Each line is what you type.

| Time | Prompt | What happens |
| --- | --- | --- |
| 0:00 | *"Is my Digitakt connected?"* | `whiplash_list_midi_ports` finds *Elektron Digitakt II*. |
| 0:08 | *"Play some groovy deep house."* | `whiplash_play_pattern deephouse`: kick, rim, hats, bass and chords at 122 BPM, 55 % swing. |
| 0:18 | *"Close the filter on the bass, then open it slowly over 8 bars."* | `whiplash_set_param` track 6 `filter_freq` 20, then `whiplash_ramp_param` 20→110 over 8 bars, `curve: exp`. |
| 0:30 | *"Thicken the hats."* | `whiplash_mutate density` track 4 `thicken`: ghost 16ths from the next bar. |
| 0:40 | *"Drop the kick and bass for two bars with a fill."* | `whiplash_mutate drop` tracks 1 and 6, 2 bars, `fill: true`: the beat breathes, the snare rolls up, and kick and bass slam back on the one. |
| 0:55 | *"Switch to techno on the next bar."* | `whiplash_play_pattern techno`: queued, lands on the bar at 130 BPM with no Stop/Start. Mutes and running ramps carry over; the thickened hats reset with the new pattern. |
| 1:05 | *"Loosen it up and throw some reverb on the clap."* | `whiplash_mutate humanize` 0.4, then `whiplash_ramp_param` track 3 `reverb_send` 0→100 over 2 beats, `curve: log`. |
| 1:15 | *"What's playing?"* | `whiplash_status`: techno, bar, active ramps with progress. |
| 1:22 | *"Stop."* | `whiplash_stop`: clean stop, no hanging notes. |

See [CHANGELOG.md](CHANGELOG.md) for what changed between versions, and [docs/](docs/) for the draft Hermes plugin catalog entry and PR text.

## License

MIT
