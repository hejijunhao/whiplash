# Whiplash v0.8 build plan

Status:
- **v0.8.0 is implemented** in PR "Whiplash v0.8.0: play along (MIDI input, follow, undo)", branch `feat/v080-play-along`, cut from `main` at `2f7c6bb` (v0.7.1 merged, PR #22). It covers items 1, 2, 4 and 5 below. §5 lists the decisions taken.
- **v0.8.1** (item 3, `whiplash_export` to a standard MIDI file) waits for Phil's OK on file writes (§5.1).
- Nothing in v0.8 has been tested on a real Digitakt II yet. The hardware checks below are for Phil's Air.

Inputs:
- **Roadmap:** the v0.8 section of [roadmap.md](roadmap.md).
- **Device reference:** [reference.md](../digitakt-ii/reference.md):
  - §6.1-6.2: incoming notes, KEYBOARD mode, the AUTO channel.
  - §7.2-7.3: MIDI CONFIG > PORT CONFIG send settings, and CHANNELS.
  - §8: the CC/NRPN map.
- **Phil's instruction of Nov 11 2026** to keep building toward 1.0. Phil was asleep, so the orchestrator took the scope decisions in §5 on his behalf. Each one can be reverted.

**Goal of v0.8 (the demo sentence):** "I play the Digitakt, Hermes plays along, and it keeps a record."

**Constraint for this PR:** the hackathon catalog deadline is 2 PM PT, so `main` must stay demo-safe:
- Part A of the hardware checklist must behave exactly as before.
- `scripts/rehearse_demo.py` must still print `RESULT: PASS`.
- The plugin must import and run with no optional dependency installed.
- Nothing new runs unless a new tool is called. The MIDI input opens lazily, from `whiplash_play_along` or `whiplash_follow` only.

## 1. Priorities at a glance

| PR | Item | Size | Depends on |
| --- | --- | --- | --- |
| **v0.8.0** | 1. MIDI input from the unit: lazy input port, daemon reader thread, CC/NRPN decoded into named track/param moves, "last user moves" in status, ramps yield to the user's knob | M | v0.3 ramps, `ccmap` |
| **v0.8.0** | 2. `whiplash_follow(track, answer_track, mode)`: call and response on the next bar, in key, in the native register, on the grid | M | item 1, v0.6 keys, v0.5 register |
| **v0.8.0** | 4. `whiplash_undo`: revert the last part, mix or arrangement change on the next bar | S | v0.5.1 parts, v0.6.1-2 arrange and mix |
| **v0.8.0** | 5. In-memory session recording: a bounded ring buffer of sent and received events with clock-tick timestamps | S | item 1 |
| v0.8.1 | 3. `whiplash_export(name)`: write the recording as a standard MIDI file (`mido.MidiFile`, one track per channel, tempo) | S | item 5, **Phil's OK on file writes** |

Recording and export are one roadmap feature, split in two:
- **v0.8.0** keeps the session in memory. It writes nothing.
- **v0.8.1** turns that memory into a `.mid` file. It is the only v0.8 item that writes to disk, and the roadmap lists file writes outside the plugin as needing Phil's explicit OK.

## 2. Sources

- **[M]** *Elektron Digitakt II User Manual*, OS 1.17 (see [docs/digitakt-ii/README.md](../digitakt-ii/README.md)), cited by page.
- **[G]** [midi.guide Digitakt II](https://midi.guide/d/elektron/digitakt-ii/).
- **[R]** [docs/digitakt-ii/reference.md](../digitakt-ii/reference.md). v0.8.0 adds §15.1 #37 and §15.3 Q25-30.

Every claim marked **HW** needs a check on the unit.

---

## Item 1 (v0.8.0): MIDI input from the unit

**Problem.** Whiplash only knows what it sent. It can't tell when Phil turns a knob, so a running ramp fights his hand. It also can't answer what he plays.

**Source facts ([R] §7.2, [M] 14.4, p. 77-79).** The unit sends MIDI only if MIDI CONFIG > PORT CONFIG allows it:
- **OUTPUT TO** must include USB.
- **ENCODER DEST** and **TRIG KEY DEST** must be INT+EXT (or EXT).
- **OUTPUT CH** picks the AUTO channel or the track's own channel.
- **PARAM OUTPUT** picks CC or NRPN.

Moves on the track's own channel name the track. Moves on the AUTO channel don't. In KEYBOARD mode the [TRIG] keys play the active track chromatically ([R] §6.2).

**Change.**

1. **Lazy input** (`jam.open_input`). It opens the first MIDI input whose name contains "digitakt" (like the output), never the virtual "Whiplash" port and never any other device.
   - It opens only when `whiplash_play_along` or `whiplash_follow` is called.
   - With no Digitakt input, it returns a clean error that lists the inputs it saw and gives the USB and PORT CONFIG fix.
   - It never falls back to another input.
2. **Reader thread** (`whiplash-in`, daemon). It polls the port and handles at most 64 messages per batch, then sleeps 0.2 ms, which gives the GIL back under a flood. When idle it sleeps 1 ms.
   - It **never takes `Engine._lock`**. Everything it hands to the sequencer goes through lock-free deque appends, and it never sends anything.
   - An exception there (the input unplugged) ends the thread and sets `lost`. The beat is untouched.
3. **Decoding** (`jam.Decoder`):
   - CC on channel n becomes `{track: n, param: <ccmap name>, cc, value}`.
   - NRPN (CC 99/98, then data CC 6) is assembled per channel and mapped through `ccmap` `Param.nrpn`. Those addresses come from midi.guide only, and §8.3 lists several where the manual disagrees, so NRPN moves are marked `unsure` on those addresses.
   - Notes are counted per track.
   - Everything else (SysEx, program change, clock, transport, aftertouch, pitch bend) is ignored and counted by type. It is **never** re-sent and never recorded.
4. **Echo filter.** If the unit, or a MIDI thru in between, echoes Whiplash's own messages back, they must not count as user moves. While the input is open, `Engine.send` notes the last value per (kind, channel, number) with its time. An incoming CC or note matching what Whiplash sent less than 60 ms earlier is ignored (`echoes_ignored`). **HW** (Q27).
5. **Last user moves.** These are the 32 most recent moves. Consecutive moves of the same track and param are merged into one gesture, with `from`, `value` and `said` ("track 6 filter_freq 40 -> 90"). `whiplash_status.play_along` shows the last 8.
6. **Ramps yield.**
   - A user CC or NRPN on a (track, CC) where a Whiplash ramp runs is appended to a lock-free `grabs` deque (bounded, 256).
   - The sequencer drains it at the start of `_advance_ramps`, which already holds `_lock` once per tick. It cancels that ramp (and a filter_swap's pending reopen on that knob, as `whiplash_set_param` does) and logs a notice.
   - The next tool result carries `yielded_to_user`, and `whiplash_status` lists the recent ones. The knob wins within one clock tick (about 20 ms at 120 BPM).

## Item 2 (v0.8.0): `whiplash_follow(track, answer_track, mode)`

- **Call.** Phil plays notes on `track`'s channel: KEYBOARD mode on that track with OUTPUT CH = track channel, or `track` set to the AUTO channel's number.
  - The reader appends `(time, note, velocity)` for note-ons on that channel to a bounded phrase deque (64).
- **Response, on the next bar line.**
  - At each bar line the sequencer, already under `_lock`, takes the notes heard in the bar that just ended and quantizes them to its 16th grid. It uses the bar's start time and tempo, and a note half a step before the bar line belongs to the new bar.
  - The bar that starts now plays the reply on `answer_track`, replacing that track's own line for that one bar (one voice per audio track, [R] §6.4).
  - The reply has at most 16 notes, one per step. Each note lasts one step at the user's velocity.
- **Modes** (`jam.reply`, pure). Each mode works in the key playing (v0.6; chromatic without one):
  - `echo`: the phrase as played, snapped into the key.
  - `answer` (default): the contour mirrored around its first note by scale degree, ending on the nearest tonic.
  - `harmonize`: a diatonic third above each note.
- **Register (v0.5).** The reply moves by whole octaves until its median sits in 53-72: no more than 7 below native pitch, and no more than an octave above. Notes fold by octaves into 16-84. The answer track's `whiplash_transpose` still applies.
- **Refusals before anything changes:**
  - nothing playing
  - `track` = `answer_track`
  - an answer track that holds drums, cymbal or fx (as `whiplash_set_progression` refuses)
  - no Digitakt input
- **Stop path:**
  - `whiplash_follow(stop: true)`
  - `whiplash_play_along(on: false)`
  - `whiplash_stop`
  - A new follow replaces the old one.

## Item 4 (v0.8.0): `whiplash_undo`

- **What is undoable.** Each of these pushes one entry (at most 16, newest first) before it changes anything:
  - `whiplash_write_part`, a new part or `reset`. The entry is the track's previous part, or none.
  - `whiplash_mix` with changes. The entry is the previous value of each level and pan it changes.
  - `whiplash_arrange`, a new arrangement or `clear`. The entry is the previous arrangement and its mutes, or none.
- **`whiplash_undo` reverts the newest entry on the next bar line.** It runs as a timed action in `_run_timed` (kind `call`), so the change lands exactly where every other musical change does.
  - **A part:** the previous part comes back, or the generated line.
  - **A mix:** the previous values go out. A track Whiplash had never sent that value to can't be reverted, and is listed in `cannot_revert`.
  - **An arrangement:** the previous one resumes in the section the next bar falls in. With no previous arrangement it clears, like `clear: true`. If the previous one would already have ended (no loop), undo refuses before anything changes, because restoring it would stop the beat.
- **What isn't undoable.** The stack is cleared by `whiplash_stop` and by a fresh start. Undo itself can't be undone. Saved mixes (`save_as`) and the CC 80 that `envelope: "note"` sends are not reverted.

## Item 5 (v0.8.0): in-memory session recording

- **When it runs.** `jam.Recording` starts when the input first opens, and keeps recording until `whiplash_play_along(on: false)`.
  - It holds up to 65,536 events. Above that the oldest are dropped and counted.
  - That is about 15 minutes of a busy beat. The cost is a few MB of RAM.
- **What it holds.** Each event is `(direction, tick, time, type, channel, a, b)`:
  - `out`: every note and CC Whiplash sends (in `Engine.send`), but never clock.
  - `in`: every note and CC heard from the unit (echoes excluded).
  - `mark`: a pattern switch, a section start and each tempo change, at the bar line.
- **Timestamps.** The sequencer publishes `clock_ref = (tick, tick time, tick length)` once per tick as one tuple assignment. An event's tick is that tick plus the fraction of a tick since, so sent and received events share Whiplash's clock. With nothing playing the tick is `null` and the time still counts.
- **Writes nothing.** `whiplash_status.play_along.recording` shows the counts. `Engine.recording_snapshot()` returns a copy for v0.8.1's export.

## 3. Phil's hardware checks (v0.8.0)

**Before you start, on the unit:** SETTINGS > MIDI CONFIG > PORT CONFIG ([M] 14.4.2, p. 78; [R] §7.2):
- **OUTPUT TO** = USB (or MIDI+USB)
- **ENCODER DEST** = INT+EXT
- **TRIG KEY DEST** = INT+EXT
- **OUTPUT CH** = the track channel (not AUTO)
- **PARAM OUTPUT** = CC
- Keep **INPUT FROM** = USB and **RECEIVE NOTES** / **RECEIVE CC/NRPN** on, for Whiplash's own beat.

The menu names come from the manual. Confirm them on the unit and note any that differ.

| # | Prompt in Hermes, or action | Listen or look for | Reference |
| --- | --- | --- | --- |
| HW 8.0-1 | "Play techno. Play along with me." Turn track 6's filter knob. Then "what did I just change?" | `play_along.port` names the Digitakt. Hermes lists "track 6 filter_freq a -> b" with the right track and param. Note the input's name. | Q25 |
| HW 8.0-2 | "Ramp track 6's filter from 20 to 127 over 8 bars." Halfway, grab the filter knob. | The sweep stops at once and your knob wins. The next answer says Hermes yielded (`yielded_to_user`), and status lists it. | Q26 |
| HW 8.0-3 | Without touching anything, let a ramp run for 4 bars with play-along on. | No yield, and `echoes_ignored` stays 0 (or counts, if the unit echoes Whiplash's CCs). Note which. | Q27 |
| HW 8.0-4 | "Answer whatever I play on track 7, on track 8." Put the unit in KEYBOARD mode on track 7 and play 4 notes in one bar. | On the next bar, track 8 plays a 4-note reply in key, on the grid, near its native pitch. Then try `echo` and `harmonize`. | Q28 |
| HW 8.0-5 | Set OUTPUT CH to AUTO, then repeat 8.0-1. | Moves show on the AUTO channel's number, not track 6 (expected). Set it back. | Q25 |
| HW 8.0-6 | Set PARAM OUTPUT to NRPN, turn track 6's filter and level. | Moves come back via `nrpn`. Note whether filter_freq and track_level are named right (midi.guide addresses, `unsure` flags). | Q29 |
| HW 8.0-7 | "Bring the bass down 20 over 2 bars." Then "undo that." | Levels go back on the next bar line. Then write a part on track 7, "undo that": the old line returns on the bar. | |
| HW 8.0-8 | Unplug USB with play-along on. | `play_along.lost` says so. The beat stops with `port_lost` as in L1 (same cable). Replug, then `whiplash_play_along` again. | |
| HW 8.0-9 | Play fast 16ths in KEYBOARD mode while turning two knobs, at 160 BPM. | The beat stays tight, with no audible lag on Whiplash's notes. | Q30 |

Constraints throughout:
- No SysEx and no program change are sent, and no received message is ever forwarded.
- No project, pattern or kit writes, and never touch Digitakt slots 1-3.
- The blocked CCs stay blocked.
- No file writes in v0.8.0.
- The sequencer thread never enumerates or opens ports, and never waits on the input.

## 4. Order and merging

v0.8.0, then v0.8.1. Each is cut from `main` after the previous one merges. Merge commits only, and Phil merges.

These belong to the visualiser agent and aren't touched here; the PR lists the new checks for them:
- the hardware checklist (`docs/testing/hardware-checklist.md`)
- `docs/demo/` and `scripts/`
- the visualiser (`view.py`, `view.html`)

User-move markers in the view (roadmap "later themes") can read `Engine.user_moves`, read-only.

## 5. Decisions taken for v0.8.0 (on Phil's behalf; each is reversible)

1. **v0.8.0 writes no files.** Export is deferred to v0.8.1, because the roadmap lists file writes outside the plugin as needing Phil's OK. The recording lives in memory until then. *Reversible:* v0.8.1 adds `whiplash_export(name)` writing `~/.hermes/whiplash/sessions/<name>.mid` once Phil agrees, or a path he prefers.
2. **Input opens only on a new tool** (`whiplash_play_along`, `whiplash_follow`). `whiplash_status` never opens it, so Part A is unchanged. *Reversible:* status, or the first play, could open it automatically.
3. **No fallback input,** the same rule as the audio input. Only a port named Digitakt is used.
4. **User moves don't change `last_cc`.** That field stays "the last value Whiplash sent". The user's values are listed separately under `play_along.user_moves`. The other choice was writing them into the sent-values table from the reader thread, which would race the sequencer. A ramp or mix without `from` therefore still starts from Whiplash's last value. *Reversible* (open question).
5. **Follow answers each bar on the next bar.** It doesn't wait for a phrase to end, and the reply replaces the answer track's own line for that bar. *Reversible:* a `bars` option for longer phrases.
6. **Undo covers parts, mixes and arrangements** (the roadmap's list). It doesn't cover progressions, mutations, transposes or saved mixes. 16 entries, cleared by stop.
7. **Recording holds 65,536 events.** It is on whenever the input is open, and clock is never recorded.
8. **Echo window of 60 ms.** A starting point, to tune after HW 8.0-3.
9. **Tool-description budget:** three new tools.
   - The total cap rises from 3,500 to 4,100 characters (the per-tool 400 stays).
   - Params rise to 9,300 characters, and the JSON to 22,000 bytes.

**Open questions for Phil (v0.8.0):**
- File writes for v0.8.1's export: OK to write `.mid` files under `~/.hermes/whiplash/sessions/`, or somewhere else?
- Should a user's knob value become the "last value sent" (decision 4), so a later ramp starts where his hand left it?
- Should follow wait for a phrase to end (a bar of silence) before answering, instead of answering every bar?
- Should play-along open automatically with the first `whiplash_play_pattern` once HW 8.0-1 passes?
