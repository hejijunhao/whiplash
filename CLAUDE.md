# Whiplash: notes for agents

Whiplash is a Hermes Agent plugin that plays an Elektron Digitakt II over USB MIDI. Start with [README.md](README.md) for what it does and [CHANGELOG.md](CHANGELOG.md) for what changed.

## Device reference (read before touching MIDI)

**[docs/digitakt-ii/reference.md](docs/digitakt-ii/reference.md) is the canonical Digitakt II reference.** Consult it before changing or claiming anything about how the unit behaves. That covers:
- the parameter map (`ccmap.py`),
- notes and pitch (`patterns.py`),
- channels, transport or mutes (`engine.py`),
- and any README text about the hardware.

It cites the official OS 1.17 manual by page, cross-checks [midi.guide](https://midi.guide/d/elektron/digitakt-ii/), and lists every discrepancy and open hardware question. If you learn something new about the unit, update that file, with the source and date. [docs/digitakt-ii/README.md](docs/digitakt-ii/README.md) says where the manual is and why the PDF itself isn't committed.

## Rules

- **Never send SysEx or program change.** `Engine.send()` refuses them, so don't widen its allow-list. Program change switches patterns, and SysEx can overwrite slots on the unit.
- **Write nothing to the unit:**
  - no project, pattern, kit or preset saves,
  - no +Drive access,
  - no file transfer.
- **Don't unblock anything in `ccmap.BLOCKED_CCS` / `BLOCKED_NRPNS`:**
  - bank select (CC 0/32),
  - sample bank (CC 24, which is also delay feedback on the FX channel),
  - the NRPN data CCs,
  - the sample NRPNs.

  Relaxing one needs an explicit decision from the maintainer.
- **Keep the clock thread clean.** No port enumeration, I/O or locks held long in the sequencer thread. Every musical change is timed on Whiplash's own MIDI clock.
- **Validate before touching the beat.** Bad input must never change what is playing.
- **Never claim hardware behaviour is verified** unless it was tested on a real Digitakt II. If so, record who tested it and when in `docs/digitakt-ii/reference.md`. The test suite runs against fake and virtual ports only.

## Tests

`uv sync && uv run pytest -q`. CI runs Linux and macOS (`.github/workflows/tests.yml`).

The repo root is the package, loaded as `whiplash` (see `tests/conftest.py`). Run the tests from a checkout directory named `whiplash`, or from another valid Python identifier. A worktree directory with a hyphen, such as `whiplash-viz`, breaks collection.
