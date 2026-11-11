# Catalog PR description (draft)

Text for the pull request that adds `plugin-catalog/whiplash.yaml` to NousResearch/hermes-agent.
Not submitted yet: pin `sha` in [catalog-entry.yaml](catalog-entry.yaml) first and run
`hermes plugins validate . --install-deps` at that commit.

---

**Add Whiplash: let Hermes jam live on an Elektron Digitakt II**

## What it does

Whiplash turns Hermes into a live performer on an Elektron Digitakt II over USB MIDI. Hermes starts a beat by genre or mood on tracks 1-8 with MIDI clock and transport. It then works the beat like a DJ: it switches patterns on the bar line without stopping the clock, sweeps named sound parameters over beats or bars in time with the clock, thins or thickens tracks, drops tracks for a few bars with a fill before they come back, switches a track to another sample already in the project, and changes swing, humanize, mutes and tempo. Each of these is one tool call with validated arguments; the timing happens in the plugin's sequencer, not in the model.

- Repo: https://github.com/hejijunhao/whiplash (MIT)
- Pinned commit: `<sha>`
- Version 0.4.0, `requires_hermes: ">=0.19"`, platforms linux and macos
- Python dependencies: `mido>=1.3,<2`, `python-rtmidi>=1.5,<2` (declared in `pyproject.toml`, mirrored in `plugin.yaml`)

## Hermes surfaces used

- `ctx.register_tool` only: 12 tools, all prefixed `whiplash_`, matching `provides_tools` exactly.
- No hooks, middleware, commands, providers, tool overrides, or core patching. No `capabilities` requested.
- `register()` only registers schemas. MIDI ports and the sequencer open on the first tool call, so loading is instant.

## Disclosures (rule 13)

- **Controls MIDI hardware.** Sends notes, MIDI clock, transport Start/Stop (optional: a clock-only mode sends neither), and CC/NRPN parameter changes to the MIDI output it opens (the Digitakt II when found). Parameter changes alter the sound of the pattern loaded on the unit until it is reloaded. MIDI Start also starts the unit's own sequencer, and every play result warns about this.
- **Can change which sample a track plays.** `whiplash_select_sample` / `sample_slot` sends Sample Slot Select (CC 19), which switches a track to another sample *already loaded in the project's sample pool*, until the pattern/kit is reloaded. It can't list, preview or load samples. Sample bank select, the sample NRPNs and raw CC 19 are refused.
- **Never** sends SysEx or program changes (refused in code). No file transfer onto the unit, no project, pattern or slot writes, no +Drive access.
- **Long-running background thread.** While a pattern plays, a daemon sequencer thread runs inside the Hermes process. `whiplash_stop` ends it, and an `atexit` hook silences the unit and closes the port when Hermes exits.
- **Opens a virtual MIDI port** named "Whiplash" when no Digitakt is connected. Every tool result then warns that the hardware is silent, and says so again if a Digitakt appears (Whiplash never switches by itself).
- **Reads the list of MIDI ports** on the machine (at most every 2 s while on the virtual port) to detect the Digitakt.
- Reads one optional environment variable, `WHIPLASH_SEND_TRANSPORT` (transport default). No network calls, no shell or subprocess, no credentials, no file reads or writes outside the plugin directory, no telemetry.

## Testing

Tests run on GitHub Actions on Linux and macOS (Python 3.11 and 3.13) against fake and virtual MIDI ports. They cover timing, clock-synced ramps, bar-quantized switches, mutations, sample-slot select and what stays blocked, clock-only transport, hot-plug notices, port loss, exit cleanup and SysEx refusal. CI does not cover a real Digitakt II; <add the hardware check done before submitting>.
