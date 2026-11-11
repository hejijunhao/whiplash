# Changelog

## 0.5.2

Review follow-ups from the v0.5.0 review (PR #10): three fixes, each with tests. Still 16 tools. Nothing here has been tested on a real Digitakt II yet.

Fixed
- **Transpose on tracks 9-16.** `whiplash_transpose` and `play_pattern(transpose=...)` used to return success on a track that plays nothing, such as 9-16 without a written part, and then do nothing. Transpose applies to any track that plays, including written parts on 9-16. A non-zero transpose on a track with no notes (in the current pattern, the queued one, or a carried written part) is now refused with an error that says to write the part first. It is validated before anything changes. `0` is always accepted.
- **All Notes Off on 9-16.** Stop, panic and the run's own exit sent CC 123 only on channels 1-8, but written parts can play on 9-16. CC 123 now also goes to every channel 9-16 that played a note since the last panic, and to no other. Channels 1-8 still get it every time, as before. The clock thread only adds the channel to a set when it sends a note-on.
- **`amp_hold` can't slip into HOLD = NOTE.** On CC 80, 127 is not the longest hold: it switches HOLD to NOTE (manual 11.7 p. 56; midi.guide), and this was the top of a clamped, rampable range. The fix:
  - Named `amp_hold` now has range 0-126.
  - Every ramp on CC 80 (named or raw `cc: 80`) stops at 126 and says why in `hold_note`.
  - `whiplash_set_param` sends 127 only for `value: "note"` or exactly 127, and labels the result `hold: "NOTE"` with a warning to tell the user.
  - `write_part` `envelope: "note"` uses the same path, and its result carries the same label.
  - Values above 127 were already refused as non-7-bit. The skill, README, schemas and reference (§5.2, §8.0, §15.1 #25) say so.

Changed
- README: the test count is checked by a test now. Also corrected "HOLD = NOTE (the usual default)": that is only the midi.guide default (reference §15.3 Q6). The CHANNELS setup now says to keep AUTO/FX CONTROL CH off any channel 9-16 you write parts on.
- The view keeps `amp_hold` knob travel at 0-127, so an explicit NOTE shows at the top.
- Version 0.5.2 in `pyproject.toml`, `plugin.yaml` and `docs/catalog-entry.yaml`.

## 0.5.1

Written parts: Hermes can now write melodies, basslines and rhythms itself, the three asks from the Nov 11 2026 Digitakt II session that v0.5.0 left open ("play different notes so it's a melody", "4/4 on the bass drum, not 16ths", "plays non-stop"). 16 tools. Nothing here has been tested on a real Digitakt II yet.

Added
- `whiplash_write_part(track 1-16, ...)` replaces one track's line in the working pattern from the next bar line:
  - **Placement**, one of: `rhythm` presets (`four_on_floor`, `on_kick`, `offbeat_8ths`, `8ths`, `16ths`, `off_16ths`, `syncopated`, `half_time`), `grid` step masks (16 cells per bar, `X` = accent, up to 4 bars), `steps`, `hits` (`{step, note, length, velocity, bar}`) or `lock_to` (copies another track's hits at call time; `on_kick` = `lock_to: 1`; live follow is P1).
  - **Notes** cycle over the hits: Elektron names (C5 = 60), MIDI numbers 16-84, `.` rests, or scale degrees with `key`/`scale` (13 scales). The result echoes each bar as a grid with note numbers and names, plus the `pitch` block.
  - **`length`** in 16th steps (0.25-16, a list cycles) is sent as the exact MIDI note-off, with no 0.8 `GATE` factor. **`velocity`** 1-127, a list, or `accent`. **`bars`** 1, 2 or 4 (default: the shortest that plays every note).
  - **`length_audible`** in every result: the unit only ends a sound on note-off with AMP MODE = ADSR or HOLD = NOTE (manual 11.7 p. 56, B.5 p. 110; midi.guide; reference §5.2). It says so more confidently when Whiplash itself last sent `amp_hold` 127 or `amp_mode` 1.
  - **`envelope: "note"`** (opt-in) sends exactly one CC 80 = 127 (HOLD = NOTE) on the track, after validation. The envelope is never changed silently.
  - Mutes, drops, fills, density, humanize and transpose still apply to a written part. It carries across live pattern switches and `whiplash_mutate reset`; `reset: true` or `whiplash_stop` clears it (the same lifetime as mutes and transposes).
  - Bad input (track, placement, notes, grid, length, velocity, bars, envelope) raises before anything changes: no part, no CC.
  - On tracks 9-16 the result warns that the unit's AUTO CHANNEL or FX CONTROL CH may share the channel (reference §7.4).
- `whiplash_status` gains `parts`, and `tracks[n].part` is `written` for a written part.
- The bundled `whiplash:digitakt` skill teaches `whiplash_write_part`: that Hermes can write melodies and rhythms, how to place hits, write lines around C5, read `length_audible`, and make length audible with `envelope: "note"` or ADSR.

Changed
- `whiplash_mutate` `density` and `drop` accept tracks 1-16 (was 1-8). Density on a track with no notes is rejected.
- The sequencer ends a held note just before the same note retriggers on the same channel, instead of letting the earlier note-off cut the new note short. Generated parts never overlapped this way, so they sound the same.
- New module `parts.py`: pure parsing and building of written parts, no MIDI.

### Also in 0.5.1: visualiser pixel-art rack restyle (PR #8)

Changed
- `whiplash_open_view` page (`view.html`) restyled as a flat, strict-grayscale pixel-art hardware rack, per [docs/executing/viz-style-brief.md](docs/executing/viz-style-brief.md). It is still one self-contained file with no new dependencies, fonts or CDNs, and the tool contracts are unchanged.
  - **Track modules:** a trig LED and note readout fire on each scheduled hit. The LVL fader and FLT/RES/DEC knobs show the last values sent, plus a fourth knob for any other param. Ramping knobs turn toward a target tick. Each module has a 16-step pixel strip and a mute bat toggle. A mute dims the module, and a drop or fill starting flashes it inverted.
  - **Tape transport:** the reels turn in proportion to the BPM and stop with the transport. It also has a REC LED, a bitmap BPM, bar and loop position, the queued switch and the port status.
  - **Master OUT:** the VU needle follows an envelope derived from the scheduled hits and track levels, clearly labelled as not real audio. It follows the real input's RMS after CONNECT AUDIO.
  - **Hub:** dotted rings pulse on kicks and bar downbeats.
  - **Cables:** white bezier patch cables run from each track OUT to its master IN. A hit shakes the cable, and a muted or dropped track's cable goes dashed. `R` toggles the cables (it was runway tilt). The spectrum and scope panels are gone.
- View snapshot param rows carry `max` from `ccmap`, so knob travel matches each param's range.

Added
- Tests: the page has no external URLs, its palette is strict grayscale, every state field the page reads exists in a real frame, and param `max` follows `ccmap`.
- `docs/executing/viz-style-brief.md` (the design brief) and a roadmap entry under visualiser evolution.

### Also in 0.5.1: hardware test plan and v0.5.0 review (PR #10)

Added
- `docs/testing/hardware-checklist.md`: one ordered hardware session for a real Digitakt II. It starts with a 10-minute smoke test, which covers the demo plus one written melody. Then it covers:
  - the v0.5.0 pitch register, status, skill and `amp_mode`,
  - v0.4 sample select and transport modes,
  - v0.3 live control,
  - the reference fixes,
  - the visualiser restyle,
  - v0.5.1 `whiplash_write_part` (melody, rhythm presets, lock to kick, length vs HOLD/MODE, retrigger, tracks 9-16),
  - a placeholder for the v0.5.2 fixes from the review (transpose on 9-16, All Notes Off on 1-16, `amp_hold` NOTE only when explicit),
  - and hot-plug.

  Each check has the setup, the prompt to type, what to expect, and pass/fail boxes. The checks map to the reference's open hardware questions (§15.3). It is linked from README and CLAUDE.md.

Fixed (docs)
- Reference §8.1 Amp table: `amp_mode` is shipped (it said "planned").
- README setup: HOLD = NOTE is the midi.guide default, not a known factory default (reference §15.3 Q6).
- v0.5 build plan status: P0a shipped in v0.5.0, and P0b shipped in v0.5.1.

## 0.5.0

Fixes from the second live session on a Digitakt II (Nov 11 2026): generated basslines no longer repitch samples far below their own pitch, results say where each line sits, and the agent guidance ships with the plugin. 15 tools.

Added
- **Native-pitch register.** Note 60 (C5, Elektron numbering) plays a sample at its own pitch while TUNE is 64 and the preset OCTAVE is unchanged (reference.md §6.1; manual p. 25, p. 38). `patterns.register()` lifts each generated melodic part by whole octaves at load time until its median is no more than 7 semitones below 60, keeping the intervals. The techno bass moves from 41 to 53 (the -7 that tune +12 fixed by ear), the soul and breaks basslines move up an octave, deep house is unchanged, and drums are never moved. The note tables stay as written in `patterns.RAW`.
- `whiplash_transpose(track, semitones | octaves)`: absolute, ±48 semitones, from the next bar line, clamped to 16-84 (the manual's documented chromatic range; the track-channel range is undocumented). Carries across pattern switches like mutes; `whiplash_stop` and a fresh start reset it.
- `transpose` on `whiplash_play_pattern` (`{"6": -12}`): from the first bar of a fresh start, or from the switch bar of a queued one.
- `pitch` per melodic, transposed or tuned track: low/high notes with Elektron names, `semitones_from_native` (including `tune - 64` when Whiplash sent CC 16), `transpose`, `tune` and `register_shift`.
- `tracks` in `whiplash_status` and in `whiplash_play_pattern` results: role marked `(assumed)`, last sample `slot` and `tune` Whiplash sent (`null` until sent), `transpose`, `pitch`, mute, `part` and `last_cc`, plus `roles_assumed`, `kit_note` and `pitch_note`. A queued result describes the next pattern with the transposes it will play with.
- `amp_mode` named param: CC 87, 0 = AHD, 1 = ADSR, a switch (manual B.5 p. 110; midi.guide). `amp_hold` documents 127 = NOTE (manual 11.7 p. 56; midi.guide). 38 named params.
- Bundled skill `whiplash:digitakt` (`skills/digitakt/SKILL.md`), registered with `ctx.register_skill` when the Hermes build has it; older builds still load the tools. Tool descriptions point to it.
- README "Updating" section: run `hermes gateway restart` after updating, and delete any stale local `whiplash-digitakt` skill.

- The reference's named-param table gains `amp_mode`, and its §15.1 audit marks items 3, 15 and 22 as handled in v0.5.0. `pitch_note`, the skill and the README now carry the reference's caveats: the preset OCTAVE and an LFO on tune are invisible to Whiplash, SLICE = NOTE picks slices, HOLD = NOTE is the usual default, and Logic calls note 60 C3.

Not in this release (next, v0.5.1): `whiplash_write_part` (notes, rhythm presets, lock-to-kick, note lengths).

### Also in 0.5.0: the Digitakt II device reference (PR #6)

Added
- `docs/digitakt-ii/reference.md`: a detailed device reference with manual page numbers, cross-checked against midi.guide (CSV of 2026-10-12). It covers:
  - the data model (project, pattern, kit, preset, pool, +Drive),
  - machines and their knob CCs,
  - how incoming notes map to pitch,
  - channels (track, AUTO, FX CONTROL) and their CC collisions,
  - the full CC/NRPN map with 16 discrepancies listed,
  - transport and clock, mutes, p-locks, LFOs, and USB audio and Overbridge,
  - an "Implications for Whiplash" audit of 22 code assumptions.

  It is the canonical device reference.
- `docs/digitakt-ii/README.md` and `fetch-manual.sh`. They give the link, edition and SHA-256 of the official OS 1.17 manual, and download it locally with a hash check. The PDF isn't committed: its imprint forbids reproduction without written authorization.
- `CLAUDE.md`: agent notes. They point at the reference and restate the safety rules (no SysEx, no program change, no writes to the unit, blocked CCs stay blocked).
- `tests/test_reference.py`: checks the reference's named-param table against `ccmap.py`, the `loop_pos` range on the wire, and that the safety blocks are unchanged.

Fixed
- `loop_pos` (CC 22) range is now 0-120, not 0-127, matching midi.guide's Oneshot Loop Pos and the sibling `sample_start`/`sample_length`. Values above 120 clamp, with `clamped: true`. The description now says the knob is machine dependent (Bars on Werp, Stretch and Repitch; Grid on Grid).
- `lfo3_speed` documents its NRPN (1:58; the manual and midi.guide agree). It is documentation only and still never sent.

Changed
- README:
  - Setup now says to keep AUTO CHANNEL and FX CONTROL CH off channels 1-8.
  - Note 60 = original pitch now carries its two caveats: TUNE centred and preset OCTAVE unchanged.
  - Note lengths depend on AMP HOLD = NOTE or ADSR.
  - Safety says parameter edits stay in the active pattern's kit until reloaded.
  - It links the reference.

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
