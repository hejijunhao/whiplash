# Whiplash 🥁

A [Hermes Agent](https://hermes-agent.nousresearch.com) plugin that lets your agent **jam on an Elektron Digitakt II** over USB MIDI. Ask for "something dark at 128", "mute the hats", "open the filter on the bass", and Hermes plays it live on the hardware: beats on tracks 1-8, MIDI clock and transport, live CC/NRPN sound changes, mutes, and tempo.

No Digitakt? Whiplash opens a virtual MIDI port named **Whiplash** so anyone can try it with a DAW or soft synth.

## Tools

| Tool | What it does |
| --- | --- |
| `list_midi_ports` | Lists MIDI ports and whether a Digitakt II is connected. |
| `play_pattern` | Starts a beat by `genre` (`deephouse` 122 BPM, `soul` 86, `techno` 130, `breaks` 132) or `mood` (groovy, chill, dark, energetic, ...). Optional `bpm`, `bars` (omit to loop), `port`. Runs in a background thread with MIDI clock and Start/Stop. |
| `set_param` | Live sound change on one track: friendly names (`filter_cutoff`, `resonance`, `decay`, `volume`, `level`, `pan`, `overdrive`, `reverb_send`, `delay_send`, ...) or raw `cc` / `nrpn: [msb, lsb]`. |
| `mute_track` / `unmute_track` | Live mute. `hardware: true` also flips the unit's own track mute (CC 94). |
| `set_tempo` | Live tempo change; the clock follows so the Digitakt's delay/LFOs stay in sync. |
| `stop` | Note-offs, All Notes Off on channels 1-8, transport Stop. |
| `whiplash_status` | Port, pattern, BPM, bar, muted tracks. |

Track roles (same for all genres): 1 kick, 2 rim/snare, 3 clap, 4 closed hat, 5 open hat, 6 bass, 7-8 chords/chops/stabs. Load samples to match.

## Install

```bash
pip install mido python-rtmidi          # into the same Python env Hermes runs in
# e.g. uv tool install hermes-agent --with mido --with python-rtmidi
git clone <repo> ~/whiplash
ln -s ~/whiplash ~/.hermes/plugins/whiplash   # or: hermes plugins install <owner>/whiplash
hermes plugins enable whiplash
hermes plugins list                          # whiplash -> enabled
```

Restart Hermes (`hermes`), then ask: *"Play some deep house on my Digitakt."*

Whiplash's `register()` only registers schemas. The MIDI port and sequencer thread open on the first tool call, so loading stays well under Hermes' 10 s plugin-load limit.

## Digitakt II setup

On the unit: **SETTINGS > MIDI CONFIG**
- **PORT CONFIG**: INPUT FROM = USB (or MIDI+USB). Turn **RECEIVE NOTES** and **RECEIVE CC/NRPN** on.
- **SYNC**: **CLOCK RECEIVE** and **TRANSPORT RECEIVE** on if the Digitakt's sequencer/FX should follow Whiplash.
- **CHANNELS**: TRACK 1-8 CHANNEL = 1-8 (the default).

Notes trigger each track's sample (note 60 = original pitch). Whiplash plays its own pattern, so start from an empty pattern if you don't want the unit's sequence playing too.

## Safety

- **Never sends SysEx or program changes.** `Engine.send()` only allows note on/off, control change, clock, start/stop/continue. Anything else raises.
- Sample/bank select (CC 19/24, NRPN 1:3, 1:8, 1:9) and bank-select/NRPN-data CCs are blocked from `set_param`, so the agent can't reassign samples or touch projects, sample slots, or the +Drive.
- `stop` and every sequencer exit send note-offs and All Notes Off, so nothing hangs.
- No subprocess, shell, network, or secrets.

## Tests

```bash
python -m pytest -q tests     # 14 tests: patterns, timing/clock, mute/tempo/stop, CC/NRPN, SysEx refusal, real virtual-port loopback
```

## 90-second demo script

1. (0-10 s) Digitakt on screen, USB to laptop. Terminal: `hermes plugins list` shows **whiplash enabled**.
2. (10-20 s) "Is my Digitakt connected?" → `list_midi_ports` finds *Elektron Digitakt II*.
3. (20-35 s) "Play some groovy deep house." → kick, hats, bass, and chords at 122 BPM, swing 55%.
4. (35-50 s) "Close the filter on the chords, then slowly open it." → `set_param filter_cutoff` on 7 and 8.
5. (50-60 s) "Drop the kick… bring it back." → `mute_track 1` / `unmute_track 1`.
6. (60-75 s) "Make it darker and faster." → switches to techno at 130.
7. (75-85 s) "Push it to 136." → `set_tempo`, Digitakt delay stays locked to the clock.
8. (85-90 s) "Stop." → clean stop, no hanging notes.

## Hermes plugin catalog (when the repo is public)

- Push to a public repo; submit the entry pinned to the full 40-character commit SHA (`hermes plugins install owner/whiplash --ref <sha>`).
- The install-time scan should come back **safe**: no subprocess/shell, network, or credential access.
- Declares no capabilities (no tool overrides). The tool named `stop` doesn't override a built-in in Hermes v0.19.

## License

MIT
