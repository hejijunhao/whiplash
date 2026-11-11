# Whiplash v0.7 build plan

Status:
- **v0.7.0 is implemented** in PR "Whiplash v0.7.0: listening loop (capture + listen + safety rails)": items 1, 2 and 4 below. §5 lists the decisions taken.
- **v0.7.1** (item 3, `whiplash_scan_kit`) is planned, not started.
- Nothing in v0.7 has been tested on a real Digitakt II yet. The hardware checks below are for Phil's Air.

- **Branch:** `feat/v070-listen`, cut from `main` at `1fae9d0` (v0.6.2 merged, PR #19).
- **Input:** the v0.7 section of [roadmap.md](roadmap.md), [reference.md](../digitakt-ii/reference.md) §14 (USB audio, USB CONFIG, USB OUT routing), and Phil's instruction of Nov 11 2026 to keep building toward 1.0. Phil was asleep, so the orchestrator took the scope decisions in §5 on his behalf. Each one can be reverted.
- **Goal of v0.7 (the demo sentence):** "Hermes listens to what the Digitakt actually sounds like and fixes it."
- **Constraint for this PR:** the hackathon catalog deadline is 2 PM PT, so `main` must stay demo-safe. Part A of the hardware checklist must behave exactly as before, `scripts/rehearse_demo.py` must still print `RESULT: PASS`, and the plugin must import and run with no new dependency installed.

## 1. Priorities at a glance

| PR | Item | Size | Depends on |
| --- | --- | --- | --- |
| **v0.7.0** | 1. Audio capture: find the Digitakt II's USB audio input, capture N bars aligned to Whiplash's clock | M | v0.4 clock, the optional extra (§5.1) |
| **v0.7.0** | 2. `whiplash_listen(bars=2)`: loudness, peak/clipping, 4-band balance, onsets vs grid, kick offsets, silence | M | item 1 |
| **v0.7.0** | 4. Safety rails: ramp cap, CC rate cap, loudness guard (`force`) | S | item 2 (the guard reads the last listen) |
| v0.7.1 | 3. `whiplash_scan_kit`: solo-trigger tracks 1-16 one at a time, classify, **propose** kit-map labels | M | items 1-2, v0.5.3 kit map |

Item 3 waits for v0.7.1 because it is the only v0.7 item that *plays* something new on the unit by itself (16 solo hits), and it needs the capture path proven on hardware first (HW 7.0-1).

## 2. Sources

- **[M]** *Elektron Digitakt II User Manual*, OS 1.17 (see [docs/digitakt-ii/README.md](../digitakt-ii/README.md)), with page numbers.
- **[G]** [midi.guide Digitakt II](https://midi.guide/d/elektron/digitakt-ii/).
- **[R]** [docs/digitakt-ii/reference.md](../digitakt-ii/reference.md). v0.7.0 adds the `whiplash_listen` notes to §14, §15.1 #34-35 and §15.3 Q18-21.
- ITU-R BS.1770 for the K-weighting filter and the loudness gates (the "LUFS-ish" number).

Every claim marked **HW** needs a check on the unit.

---

## Item 1 (v0.7.0): audio capture

**Problem.** Whiplash can't hear the unit. It only knows what it sent, so "it's clipping", "the bass is masking the kick" or "is it in time?" are guesses.

**Source facts ([R] §14).** The Digitakt II is a class-compliant USB audio device only with USB CONFIG = **USB AUDIO/MIDI** ([M] 14.8.1, p. 83); MIDI keeps working in that mode. **USB OUT** is a single stereo pair: MAIN, one or two tracks, EXT or OFF ([M] 14.6, p. 80-81).

**Change.**

1. **Route (a): `sounddevice` (PortAudio) + `numpy` as an optional extra** (`[project.optional-dependencies] listen`), imported lazily inside a listen. Without it, `whiplash_listen` returns an error with the install and permission hint, and nothing else changes: `register()` and every other tool are untouched, and `plugin.yaml`'s `python_dependencies` stay `mido` + `python-rtmidi`. Route (b) (the visualiser page's browser capture posting features to the local view server) stays a documented later option (§5.1).
2. **Device discovery** (`listen.find_input`): the first input whose name contains "digitakt" (case-insensitive, like the MIDI port). `device` on the call or `WHIPLASH_AUDIO_INPUT` (a name fragment or an index) overrides it. **No fallback** to another input: a laptop mic would analyse the room and give confident nonsense. Errors list the inputs seen and carry the USB CONFIG and macOS microphone hints.
3. **Clock alignment.** The sequencer appends `(bar, time of its first tick)` to `Engine.bar_log` once per bar, and, only while a listen is armed, `(time, channel, note, velocity)` per note-on to `Engine.note_log`. Both are lock-free deque appends. The listen starts on the next bar line at least 250 ms away (from `Engine.position`), captures `bars` bars plus 150 ms for the round trip, and builds the grid from the logged bar times.
4. **Capture thread.** PortAudio's callback only copies each block with its ADC timestamp. The stream clock is mapped onto `perf_counter` once; without ADC times, block arrival times minus their length and the input latency are used. The window start is the median over blocks, so callback jitter doesn't move it.
5. **Failure.** No audio block for 1 s mid-listen (unplugged, permission revoked) raises a clean error; the beat keeps playing. One listen at a time. At most 24 s per listen.

**Clock safety.** The sequencer never opens, enumerates or waits on audio. The tool call's thread waits with `sleep` and holds `Engine._lock` only to copy a few values. Analysis runs in that same thread in small numpy batches (100 ms sub-blocks, 128-frame STFT chunks, 16k-sample FFT blocks) and calls `time.sleep(0)` between them, so the sequencer gets the GIL back promptly.

## Item 2 (v0.7.0): `whiplash_listen(bars=2)`

**Returns compact features only, never audio** (a few hundred bytes; no list longer than 16):

| Field | What | How |
| --- | --- | --- |
| `loudness.lufs_ish` | Integrated loudness | K-weighting (BS.1770 48 kHz biquads, applied as a frequency response on 100 ms sub-blocks), 400 ms blocks at 75 % overlap, absolute gate −70, relative gate −10. Matches BS.1770's reference points within 0.3 dB on sines; "-ish" because sub-blocks are filtered circularly. |
| `loudness.peak_dbfs`, `headroom_db`, `clipping`, `clipped_samples` | Sample peak, clipping | 3 or more samples at |x| ≥ 0.999 = clipping. Under 1 dB of headroom is a note. |
| `bands` | 4-band balance | low < 150 Hz, low-mid 150-600, mid 600-4k, high > 4k: % and dB of the 20 Hz-20 kHz energy. |
| `onsets` | Hits vs Whiplash's grid | Spectral flux at a 5 ms hop, adaptive threshold, refined to 1 ms on the analytic envelope. Offsets against the straight 16th grid from the sequencer's bar times, corrected by the measured latency: `median_abs_offset_ms`, `on_grid_pct` (≤ 10 ms), `offbeat_delay_ms`, `swing_estimate` (reads low above 75 %, where a swung 16th is closer to the next step). |
| `kick` | Kick offsets vs Whiplash's kicks | Each note-on Whiplash sent on a kick-role track, matched to a low-band (< 150 Hz) onset within −20/+100 ms: `median_offset_ms` (the USB round trip plus any timing error), `spread_ms`, `missed`. |
| `low_end.masking` | "Bass is masking the kick" | Low-band power in 80 ms after each heard kick vs the rest; under 3 dB = masking. |
| `tracks[n].seems_silent` | A track that sent notes but wasn't heard | Its solo hits (no other track within 40 ms) vs onsets; needs 2+ solo hits, else `null`. |
| `unexpected_audio` | Sound while Whiplash sent nothing | Onsets with no notes sent: the unit's own pattern (the v0.4 overlap) or the inputs. |
| `silent` | Nothing came back | Peak below −60 dBFS. |

The last listen's loudness, peak and clipping go to `whiplash_status.listen` and arm the guard (item 4).

## Item 3 (v0.7.1): `whiplash_scan_kit` (planned)

- With the transport stopped (or clock only), it plays one note on each track 1-16 in turn, alone, and captures each with the item 1 path.
- It classifies each hit by spectral centroid, decay time, pitchedness (autocorrelation) and low-end energy into the kit-map roles (`kitmap.ROLES`), with a confidence.
- It returns **proposed** labels and the numbers behind them. It never calls `whiplash_label_tracks` itself: the agent shows the proposal and the user confirms (§5.5).
- It refuses while a pattern plays with MIDI Start (the unit's own pattern would play on top, [R] §15.1 #11), and sends nothing but notes.

## Item 4 (v0.7.0): safety rails

1. **Ramps at once: 48** (`MAX_RAMPS` = 16 tracks × filter, level, pan; the most any built-in transition plus a full mix can start). `whiplash_ramp_param` and a mix ramp past it are refused before anything changes. A scheduled ramp (transition, section) past it doesn't start, and `safety.ramps_refused` counts it.
2. **Ramp CC rate: 1,000 per second, 16 per clock tick** (`CC_RATE_MAX`, `CC_PER_TICK_MAX`; the per-tick budget is `min(16, 1000 × tick length)`, so 16 up to 120 BPM, 10 at 240, 8 at 300). Over the budget a ramp is held back to a later tick (held-back ramps go first), then sends its current value; every ramp still ends on its exact end value. Below the budget nothing changes, so the demo's single sweep (A4) is byte-identical.
3. **Loudness guard.** After a listen hears clipping, an increase on TRACK LEVEL (CC 95), AMP VOLUME (CC 89) or OVERDRIVE (CC 57) through `whiplash_set_param`, `whiplash_ramp_param` or `whiplash_mix` is refused until a listen shows none. A value Whiplash never sent counts as an increase (it can't know). Lowering is always allowed. `force: true` goes past it ("unless the user insists") and the result carries `guard`.
4. **Panic untouched.** `whiplash_stop` and `_panic` are unchanged.

**Tests** (`tests/test_v070.py` without numpy, `tests/test_v070_listen.py` with numpy):

- Packaging: the version everywhere, `whiplash_listen` after `whiplash_status` in both manifests, the extra only in `optional-dependencies`, and a subprocess that blocks numpy and sounddevice, loads and registers the plugin, runs another tool and gets the install hint from `whiplash_listen`. Importing Whiplash imports neither.
- Discovery: by name (macOS and ALSA style), by override (name, index, env), no fallback to the laptop mic, bad `bars`.
- Synthetic audio (numpy kicks, hats, sines): BS.1770 reference points and gating, peak and clipping, each band, silence, kick offsets at 4/12/25 ms and with jitter, onsets on a straight and a swung grid (58, 66, 70), masking, an unheard track, audio with nothing sent, compactness.
- A fake input stream against a running engine: end to end on the bar lines, **clock jitter with a listen running** (same p95 bound as the other jitter tests), an input that stops mid-listen, no Digitakt input (the mic is never opened), the env override, limits, the tool round trip arming and lifting the guard.
- Rails: the ramp cap three ways, the CC budget at four tempos with every ramp landing, no change under the budget, the guard on each param and tool, `force`, a clean listen lifting it, status.
- No SysEx, program change or blocked CC, throughout. The listen tests skip cleanly without numpy; CI installs numpy (dev group), never sounddevice, and needs no audio device.

## 3. Phil's hardware checks (v0.7.0)

Before you start: on the unit, SETTINGS > **USB CONFIG = USB AUDIO/MIDI**, AUDIO ROUTING > **USB OUT = MAIN**. On the Air, install the extra into Hermes' Python (`pip install 'numpy>=1.24' 'sounddevice>=0.4.6'`), `hermes gateway restart`, and allow microphone access for the terminal app when macOS asks (System Settings > Privacy & Security > Microphone).

| # | Prompt in Hermes | Listen or look for | Reference |
| --- | --- | --- | --- |
| HW 7.0-1 | "Play deep house, then listen to two bars." | A result with `device` naming the Digitakt, a `lufs_ish` around −20 to −8, `kick.heard` = 8. Note the device name and the first offsets. | Q18, Q20 |
| HW 7.0-2 | "Is it in time?" | `kick.median_offset_ms` a steady few ms, `spread_ms` small. Then "set swing to 70 and listen again": `swing_estimate` near 70, `offbeat_delay_ms` up. | Q20 |
| HW 7.0-3 | "Does the bass clash with the kick?" | Hermes answers with numbers (`low_end`, `bands.low`), proposes a fix (bass down or its filter lower), applies it, listens again, and `kick_over_rest_db` rises. Audibly cleaner. | |
| HW 7.0-4 | Turn the main volume and a track's overdrive up until it clips, then "listen", then "turn the bass up". | `clipping: true`; the level increase is refused with the loudness-guard hint. "Do it anyway" → `force` and a `guard` note. "Fix it without killing the vibe" → levels down over a couple of bars, no hard cut, the next listen shows no clipping. | §15.1 #35 |
| HW 7.0-5 | "Bring the bass down 20, then listen." | `lufs_ish` and `bands.low` drop (USB OUT = MAIN). | Q19 |
| HW 7.0-6 | Unplug USB mid-listen | `whiplash_listen` errors cleanly ("stopped delivering audio"). MIDI over the same cable goes too, so the beat stops with `port_lost`, as in L1; replug and resume. With an audio interface as the input (`WHIPLASH_AUDIO_INPUT`), unplugging it alone leaves the beat playing. | |
| HW 7.0-7 | Set USB CONFIG back to USB MIDI, then "listen". | A clean error naming USB AUDIO/MIDI; every other tool still works. | §15.1 #34 |
| HW 7.0-8 | While listening, are the main outs / headphones still audible? | Note it for INT TO MAIN = AUTO. | Q7 |
| HW 7.0-9 | "Ramp the filter, level and pan on all 16 tracks over 1 bar at 300 BPM." | Hermes refuses past 48 ramps with the cap message; the ramps that run keep the notes on time and end where asked. | Q21 |

Constraints throughout:

- No SysEx, no program change, no project/pattern/kit writes, and never touch Digitakt slots 1-3.
- The blocked CCs stay blocked (bank select, CC 24, NRPN data, sample NRPNs).
- A listen never touches the beat: it validates and opens the input first, and only reads two logs from the sequencer.
- Every change is bar-quantized and timed on Whiplash's clock. The sequencer thread never enumerates ports, opens audio or takes `_transport`.

## 4. Order and merging

v0.7.0 → v0.7.1, each cut from `main` after the previous one merges; merge commits only; Phil merges. The hardware checklist (`docs/testing/hardware-checklist.md`), `docs/demo/`, `scripts/` and the visualiser (`view.py`, `view.html`) belong to the visualiser agent and aren't touched here; the PR lists the new checks for them. Showing the last listen in the view is a follow-up for that agent, through `Engine.last_listen` (read-only).

## 5. Decisions taken for v0.7.0 (on Phil's behalf; each is reversible)

1. **Capture route (a), `sounddevice` + `numpy`, as an optional extra** (`whiplash[listen]`), imported lazily inside the listen code. Missing or no input → a clear error with the install/permission hint; nothing else changes. *Reversible:* route (b), browser capture through the visualiser page posting features to the local view server, stays a documented later option; the analysis in `listen.analyse()` takes plain arrays, so it would serve either route.
2. **No fallback input.** Only an input named Digitakt, or one named by `device` / `WHIPLASH_AUDIO_INPUT`. Why: a built-in mic would make every reading wrong without saying so.
3. **A listen starts on the next bar line** at least 250 ms away and captures whole bars on Whiplash's clock. When nothing plays it captures at once at the current tempo, without a grid. **At most 8 bars and 24 s**, one listen at a time.
4. **Loudness guard scope:** TRACK LEVEL (CC 95), AMP VOLUME (CC 89) and OVERDRIVE (CC 57) through `set_param`, `ramp_param` and `mix`. It stays on until a listen shows no clipping (not on a timer, and not cleared by stop), and an unknown current value counts as a raise. Arrangement sections (their `mix` and ramps) are **not** guarded in v0.7.0: they were validated when the arrangement was made, and the presets carry no level ramps. Filter, sends and the unit's master overdrive (FX CONTROL channel, never addressed) are outside it. Open question for Phil below.
5. **Scan-kit labels are proposals only** (v0.7.1): never applied without the user confirming.
6. **Caps:** 48 ramps, 1,000 ramp CCs/s and 16 per tick. Tool calls that send CCs directly (`set_param`, a mix on the bar line, at most 32 CCs) aren't rate-limited: they are bounded per call.
7. **Clipping = 3 samples at |x| ≥ 0.999; silent = peak under −60 dBFS; masking = under 3 dB.** Starting points from synthetic audio, to tune after HW 7.0-3/7.0-4.
8. **Tool-description budget:** the total cap rises from 3,000 to 3,300 characters for the new tool (the per-tool 400 stays), params to 8,400 and the JSON to 20,100 bytes. Trimming other descriptions again would have cut caveats the tests pin.
9. **numpy joins the dev dependency group** so CI runs the analysis tests on Linux and macOS; sounddevice never does (fake input streams), so CI needs no audio device.

**Open questions for Phil:**
- Should arrangement sections be guarded too (refuse an arrangement whose sections raise levels while the last listen clipped)? v0.7.0 says no.
- Should a stale listen (say, older than 10 minutes) stop arming the guard? v0.7.0 keeps it until a clean listen.
- Is 1,000 ramp CCs/s right for the unit (Q21), or should it be lower?
- Route (b) for machines where Hermes can't get microphone permission: worth building in v0.7.1?
