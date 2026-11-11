# Clock timing: the macOS CI flake, measured

**Question:** main's CI failed on macOS in the rehearsal's clock-jitter check after PR #16, and PR #18 added a single rerun. Is that CI-runner noise, or a real engine or clock problem that could bite on Phil's MacBook Air?

**Verdict:**
- **The CI failures came from an over-sensitive test, not from engine work.** The engine's own work adds no lateness that we can measure: tool calls, bar boundaries, queued switches, progressions and arrangements. On Linux at 1x, idle, ticks go out 0.05 ms late (median) and 0.1-0.4 ms late (p99), against a tick period of about 20 ms. The old check failed whenever a macOS runner stalled for about one tick period, which is 5 ms at 4x.
- **The clock is only as precise as the machine's sleep, and on macOS CI runners that is poor.** The engine waits for each tick in short `time.sleep` calls of up to 2 ms. On the `macos-26-arm64` runner VMs, a 1 ms sleep takes 7-10 ms (p50), so at 1x ticks go out 7-10 ms late (p50) and about 24 ms late (p99). That is at or over the ~6 ms level where a late hit becomes audible (§4).
  - **Raising the thread's priority class doesn't help:** macOS user-interactive QoS (`--qos`) changed nothing.
  - **Busy-waiting the last 1 ms of each sleep halves it** (`--spin 1`: p50 4 ms, p99 12 ms).
  - **Whether a real MacBook Air behaves like this VM is unknown.** Real Mac hardware usually sleeps far more precisely than a VM, but nobody has measured it. Checklist §0.2 measures it on the Air before the session (2 min, no unit needed).
- **The other 1x risk comes from the host process.** The plugin runs inside the Hermes gateway's Python process and shares its interpreter lock (the GIL) and its garbage collector:
  - A busy Python thread in the gateway makes every tick about 5 ms late (13 ms on the macOS runner).
  - A full garbage collection of a large gateway heap stalls the clock for its whole length: 16 ms at 300k objects and 75 ms at 1.4M objects, measured.
- **What to change:** no `engine.py` change is needed before the Air numbers exist. If §0.2 shows Air sleeps like the runner's, the v0.6.2 agent's change in §6 (item 2, sleep-then-spin) is the fix. Item 1 (lateness in `whiplash_status`) is recommended either way, so the gateway itself gets measured. Nothing here is hardware-verified.
- **The test is now principled instead of retry-based.** It measures lateness against the engine's own grid, beyond what a sleep costs on the machine. A canary process excuses machine stalls, and stalls are counted per unit of real time (§5).

---

## 1. What MIDI clock tolerates at 120-130 BPM

| | 120 BPM | 126 BPM (tech house) | 130 BPM (techno) |
| --- | --- | --- | --- |
| Clock tick (24 PPQN) | 20.83 ms | 19.84 ms | 19.23 ms |
| 16th note (6 ticks) | 125 ms | 119 ms | 115 ms |

- **Transport floor:**
  - On DIN MIDI, a byte takes 320 µs (31.25 kbaud, 10 bits a byte). A clock is one byte (F8); a note is three bytes, about 0.96 ms. A clock byte can be held back by up to one byte of another message. Sources: the MIDI 1.0 electrical spec as reprinted by [Hinton Instruments](https://hinton-instruments.co.uk/reference/midi/protocol/index.htm), and [MIDI beat clock](https://en.wikipedia.org/wiki/MIDI_beat_clock).
  - **USB MIDI** (how the Digitakt II connects) carries events in 1 ms USB frames. An event waits 0-1 ms for the next frame, so about 1 ms of jitter is inherent before Whiplash does anything. At 120 BPM, ticks alternate between 20 and 21 ms on the wire. Sources: [linux-audio-dev, 2004](https://lists.linuxaudio.org/archives/linux-audio-dev/2004-September/009849.html) and the [MIDI.org forum on USB jitter](https://midi.org/community/midi-connections/jitter-and-latency-usb-firewire-thunderbolt). [Behaviour Research Methods (2018)](https://link.springer.com/article/10.3758/s13428-018-1042-7) measured MIDI devices and found millisecond accuracy is not generally achievable.
- **What listeners notice:** for a tone displaced in an isochronous sequence with inter-onset intervals under about 240 ms, the just-noticeable difference is about **6 ms**. Above that it is about 2.5 % of the interval. Musical training made no difference (Friberg & Sundberg, "Time discrimination in a monotonic, isochronous sequence", JASA 98(5), 1995, pp. 2524-2531; [abstract](https://typeset.io/pdf/time-discrimination-in-a-monotonic-isochronous-sequence-ynslrz5yhj.pdf)). Whiplash's 16ths at 120-130 BPM are 115-125 ms apart, so 6 ms is the scale where a late note becomes audible.
- **The unit:** the manual says CLOCK RECEIVE makes the unit follow the incoming 24-PPQN clock ([M] p. 77, reference §9). It doesn't say how the unit smooths an uneven clock, for example its tempo readout or whether one late tick moves its delay or LFO. That is reference §15.3 Q22, checked by checklist R10.
- **Whiplash's side:** the sequencer schedules every tick on an absolute grid (`next_tick += tick_len` in `Engine._run`). Notes are scheduled from the same grid by the same thread. So:
  - A stall delays the clock and the notes together, and a late tick never shifts the ones after it.
  - After a stall, the overdue ticks go out back to back, so the unit's tick count, and therefore its bar position, stays right.
  - On stop, the last clock goes out at once, ahead of its slot. The measurements below leave that tick out.

**Budget used below:** under 1 ms is below the USB floor. 1-4 ms is jitter well under the 6 ms JND. **More than 4 ms late** is what the test counts as a stall. More than 6 ms may be audible as a late hit, if the unit follows each tick.

## 2. Method

`scripts/clock_jitter.py` (new) plays a pattern through the real engine into the rehearsal's recording port. It records every clock with both the real time and the engine's own clock, then fits the engine's grid. The period is the median one-bar span divided by 96, and the grid is anchored on the least-late tick. It reports each tick's **lateness** in real time, which is what the unit would see at 1x. For comparison it also gives the old statistic, the p95 deviation of tick-to-tick gaps.

The old statistic counts a late tick twice (+d, then -d), and it is capped by the period. At 4x the period is 5 ms, so any 5 ms stall of the runner looks like a 100 % deviation.

The conditions can be combined:
- `--speed` runs the engine clock faster.
- `--load N` adds N busy processes.
- `--calls` makes real tool calls every 0.1 s: status, set_param, density, label_tracks, write_part, a same-tempo queued switch and reset. That is far more often than Hermes calls.
- `--gil-hog` adds a CPU-bound Python thread in the same process.
- `--gc-heap N` adds N long-lived objects and a full `gc.collect()` every 2 s from another thread.
- `--switch-interval` sets `sys.setswitchinterval`.

A **canary** process sleeps 1 ms at a time and records every wake-up more than 2 ms late: a machine stall.

**Local machine:** Linux 6.12, 16 cores, Python 3.12.11, 2026-11-11. The matrix covers 5-10 runs of 20 s each per condition (40-80 s at 4x and 16x). The full suite and the rehearsal ran here too.

**CI runners:** five rehearsal failure reports from main's and PR #18's macOS jobs (runs 43012009948, 43015115037 and 43017537062, all at 4x). This PR's workflow also adds an informational step that runs `clock_jitter.py` on every runner (§4).

## 3. Results (local, Linux)

Lateness in real ms, all runs of a condition pooled (median of the run p95s, worst p99 and max), and ticks over 2 ms:

| Condition | Period | p50 | p95 | p99 (worst run) | max (worst run) | > 2 ms |
| --- | --- | --- | --- | --- | --- | --- |
| 1x idle, 126 BPM | 19.84 | 0.05 | 0.08 | 0.21 | 10.6 | 1 / 9130 |
| 1x, 16 busy processes | 19.84 | 0.04 | 0.06 | 0.12 | 34.8 | 19 / 9136 |
| 1x, 32 busy processes (2 per core) | 19.84 | 0.05 | 0.06 | 0.84 | 9.9 | 21 / 4570 |
| 1x, tool calls every 0.1 s | 19.84 | 0.05 | 0.07 | 0.31 | 0.74 | 0 / 9137 |
| 1x, tool calls + 16 busy | 19.84 | 0.04 | 0.06 | 0.14 | 9.6 | 20 / 9136 |
| 1x, 120 / 130 BPM + 16 busy | 20.83 / 19.23 | 0.04 / 0.01 | 0.06 / 0.02 | 0.07 / 0.06 | 7.7 / 8.9 | 3 / 4326, 8 / 4727 |
| 4x idle | 4.96 | 0.05 | 0.06 | 0.07 | 3.2 | 1 / 19231 |
| 4x, 16 busy | 4.96 | 0.05 | 0.06 | 0.10 | 12.3 | 42 / 19230 |
| 4x, tool calls + 16 busy | 4.96 | 0.05 | 0.07 | 1.23 | 35.8 | 73 / 19231 |
| 16x, 16 busy | 1.24 | 0.05 | 0.07 | 1.82 | 21.5 | 109 / 19705 |
| **1x, busy Python thread in-process** | 19.84 | **5.14** | **5.32** | 10.2 | 43.4 | 4458 / 4570 |
| 1x, busy thread, switch interval 1 ms | 19.84 | 1.10 | 1.14 | 1.32 | 38.2 | 8 / 4568 |
| 1x, busy thread + tool calls | 19.84 | 5.13 | 5.33 | 5.55 | 10.4 | 4246 / 4572 |
| **1x, full GC of 1.4M objects every 2 s** | 19.84 | 0.05 | 0.21 | 57.8 | **77.6** | 35 / 913 |
| 1x, full GC of 300k objects every 2 s | 19.84 | 0.06 | 0.09 | 0.38 | **16.2** | 7 / 913 |

What the table shows:
- **The engine's own work costs nothing measurable.** Tool calls at ten times Hermes's rate leave p99 at 0.3 ms. The 4x rehearsal segments, with the arrangement, progression, fills and switches, show p50 0.03-0.05 ms and p99 under 0.1 ms on an idle machine.
- **OS scheduling** (more busy threads than cores) causes rare stalls:
  - **Where:** at random positions in the bar, not at bar lines. Checked by tick position over three 60-160 s runs.
  - **Size and rate:** single stalls of 3-35 ms, on about 0.1-0.5 % of ticks. Over 200 s at 1x with 16 busy processes, 8 ticks were more than 5 ms late.
  - **The canary:** it catches some of them. Thread-level preemption on another core doesn't show up in another process, which is why the test allows a stall per unit of time rather than none.
- **The interpreter is the real risk.**
  - **Busy thread:** a CPU-bound Python thread in the same process holds the GIL for its switch interval (5 ms by default). Every wake-up of the clock thread then waits for it, so ticks are about 5 ms late with up to 5 ms of variation. A 1 ms switch interval cuts that to about 1.1 ms.
  - **Garbage collection:** a full collection holds the GIL for its whole length. In the rehearsal itself no full collection ran (39k objects; gen-1 pauses at most 0.4 ms). In a gateway-sized heap a pause is a 16-78 ms clock stall, followed by a burst of overdue ticks.
  - **The canary can't see either**, because both happen inside Whiplash's own process. The check therefore counts them, as it should: they are what Phil's stage setup could hit.

**The CI failures** (macOS, 4x, old statistic):

| Run / job | Baseline gap p95 | Failing segment | Value | Bound |
| --- | --- | --- | --- | --- |
| 43015115037 / py3.13 | 2.06 ms | tech house | 5.07 ms | 5.06 ms |
| 43017537062 / py3.13 | 1.78 ms | techno (second run) | 4.95 ms | 4.78 ms |
| 43017537062 / py3.11 | 1.83 ms | tech house | 5.09 ms | 4.83 ms |
| 43012009948 / both | 2.10-2.44 ms | none (failed on the A7 tempo check, since fixed) | | |

- **Why these are runner noise:**
  - **Values:** every failing value sits right at the 4x tick period: 4.96 ms at 126 BPM and 4.81 ms at 130 BPM. That is the signature of an occasional stall of about one period. A slow engine would show a steady excess instead.
  - **Segments:** the failing segment changes from run to run.
  - **Other jobs:** on the same commit, the other Python version passed.
- **Even on quiet runs, macOS runners showed a 1.8-2.4 ms baseline.** At 4x the rehearsal sleeps in 0.5 ms steps, and macOS timer coalescing oversleeps them. A fixed 3 ms slack over that baseline was always close to the 5 ms period.

**The new rule locally** (20+ rehearsals with `--v06 --v061` at 4x):
- **Idle machine:** 10 of 10 pass. Every segment's p99 was under 0.1 ms, and the canary saw at most one machine stall per run.
- **16 busy processes (one per core):** the first version of the rule allowed 1 stall plus 1 per 10 s, and 5 of 10 runs failed.
  - **What failed:** 1-3 single-tick stalls of 4-11 ms in a segment, at random positions. The canary saw 13-36 machine stalls per run, but not at those moments: the clock thread was preempted on its own core.
  - **The fix:** each machine stall the canary saw during a segment now adds one to that segment's allowance (contention credit). With it, 10 of 10 pass under the same load.
  - **Regressions still fail:** a quiet machine earns no credit. A busy Python thread in the process gets none either, because the canary sees nothing (tested).
- **One unexplained stall:** in one earlier idle run, the tech-house segment had a single 30 ms stall the canary didn't see. Under the final rule that is one allowed stall, and it didn't recur in about 30 further idle runs.

## 4. CI runners (informational step)

Each job now ends with `scripts/clock_jitter.py`, and the step can't fail the job:
- 3 x 20 s at 1x,
- 3 x 40 s at 4x,
- 2 x 20 s with 3 busy processes,
- 2 x 20 s with `--qos`,
- 2 x 20 s with `--spin 1`.

Both macOS jobs agreed, on two runs (43033584124 and 43036000201, 2026-11-11, image `macos-26-arm64`, Python 3.11.9 and 3.13). Lateness is in real ms. The sleep column is how long the canary's 1 ms sleep took (p50 / p99):

| Runner, condition | p50 | p95 | p99 | max | 1 ms sleep takes |
| --- | --- | --- | --- | --- | --- |
| Linux (ubuntu-latest), 1x idle | 0.03-0.05 | 0.05-0.07 | 0.07-0.13 | 0.2-0.3 | 1.05 / 1.07 |
| Linux, 4x idle | 0.05 | 0.06 | 0.07-0.10 | 0.3-2.3 | 1.05 / 1.07 |
| Linux, 1x + 3 busy processes | 0.05 | 0.07 | 0.08-0.13 | 0.8-3.7 | (23 stalls seen) |
| **macOS, 1x idle** | **6.4-10.5** | 15-22 | 16-165 | 25-343 | **6.7-10.5 / 13.6-24** |
| macOS, 4x idle | 2.5-4.2 | 5.7-7.6 | 6.2-8.4 | 7.6-57 | 9-10 / 13.6 |
| macOS, 1x + 3 busy processes | 5.2-7.6 | 13.7-16 | 15.7-18.5 | 18-25 | 7.4-9 / 12-12.4 |
| macOS, 1x, `--qos` (user-interactive QoS on the clock thread) | 8.5-10.3 | 20.6-22.1 | 23.5-66.7 | 25-245 | 9.2-10.4 / 13.6 |
| **macOS, 1x, `--spin 1`** (busy-wait the last 1 ms) | **3.6-4.7** | 9.8-11.1 | 11.2-12.3 | 11.6-17.6 | 9.2-10 / 13.6 |
| macOS, 1x, busy Python thread in-process (test) | 12.3-13.4 | 31-32 | | | |

- **What the macOS rows show:** a sleep on these VMs is coarse, about 10 ms whatever is asked for. The engine's lateness follows it. It isn't load (the idle rows are the worst) and it isn't the engine's work (the Linux rows on the same commit are at 0.05 ms).
- **QoS:** user-interactive QoS on the clock thread doesn't change it.
- **Spin:** busy-waiting the last 1 ms halves it, but each remaining 1 ms sleep still takes ~10 ms. To beat it, the engine would have to stop sleeping a margin before the tick, sized to the machine's sleep (§6 item 2).
- **Old CI history:** earlier macOS runs (PRs #16-#18) showed a 1.8-2.4 ms gap baseline at 4x, which fits the same coarse sleep, measured with the old statistic.
- **Does this apply to the Air?** It is a VM. Apple Silicon hardware running a foreground process usually wakes from a 1 ms sleep within a fraction of a ms, but that is not verified here. A gateway running as a background service could get coarser timers. **§0.2 on the Air answers it.**

## 5. The test change: from "retry once" to a principled check

`scripts/rehearse_demo.py`'s global clock check, used by `tests/test_rehearsal.py` and the CLI, now works like this:
1. **Measure lateness, not gap deviation.** Each tick's lateness is measured in real time against the engine's own absolute grid, per constant-tempo segment, leaving out each run's last clock (sent early on stop).
2. **Group late ticks into stalls.** A tick more than **4 ms** late is late: under the 6 ms JND and four times the USB-MIDI frame. Late ticks with at most one on-time tick between them form one stall.
3. **Judge Whiplash against the machine, and excuse what the machine did.** The **canary** process sleeps 1 ms at a time for the whole run and records how long each sleep took.
   - **Late threshold:** a tick counts as late only beyond **4 ms or the machine's p99 sleep, whichever is longer**. The engine can't be more precise than the sleeps it waits in. That means 4 ms on Linux and about 14 ms on the macOS runners (§4).
   - **Excused stalls:** a stall is excused if the canary saw a machine stall during it (a sleep longer than 2 ms, or 3x its median sleep if that is longer). The engine's own causes are never excused: work on the clock thread, its lock held by a tool call, or the GIL or GC of its process. None of them stalls another process.
4. **Allow a rate, not a count, plus contention credit.** A segment may have **1 unexcused stall, plus 1 per 10 s of real time, plus 1 per machine stall the canary saw during the segment**. Credit is needed because a contended machine also preempts the clock thread on its own core, where a separate process can't see it.
   - **Still fails:** a regression repeats. Work on every bar line, or every tool call, gives a stall per bar, which is 2 per second at 4x. It fails, as `test_the_timing_rule_allows_one_burst_and_fails_a_repeating_stall` checks.
   - **Passes:** one burst of runner noise.
   - **No speed dependence:** the allowance is per real second, so it doesn't change with `--speed`.
5. **Name the stall.** Each unexcused stall is printed in the report with its run, bar and tick, so a CI failure says where it happened.

The single rerun in `tests/test_rehearsal.py` is removed. v0.7.0 (PR #20) made every wall-clock bound report-only on CI (`conftest.STRICT_TIMING`), and this check follows that policy. On CI it is printed in the report; locally, or with `WHIPLASH_STRICT_TIMING=1`, it must pass. On a quiet runner it passes anyway: the threshold follows the machine's sleep, so it is safe to make strict on CI later. New tests cover:
- the lateness fit,
- the stall rule (one burst passes, a per-bar regression fails),
- the canary excuse,
- the canary process itself,
- and `clock_jitter.py`, which must see a busy Python thread as unexcused lateness.

`tests/test_v051.py`, `test_v060.py` and `test_v061.py` keep their gap-p95 bound for now. They compare two parts of the same short 1x run (at 240 BPM) and have not flaked. The rule above could replace them if they ever do.

## 6. Proposed engine change (for the v0.6.2 agent; `engine.py` is not touched here)

The engine's own work is fine. Two things are unknown: how precise sleeps are on the Air, and what the gateway's GIL and GC do there. In order of priority:

1. **Report clock lateness in `whiplash_status`** (cheap; do this). In `Engine._run`, right after `self.send(mido.Message("clock"))`:

   ```python
   late = time.perf_counter() - next_tick          # >= 0; the tick's slot is next_tick
   self._clock_stats.add(late)                      # no lock: only this thread writes, status reads a copy
   ```

   - **`_clock_stats`:** a small object with tick count, max, last stall bar, a count over 4 ms (stall), and a fixed bucket histogram (0.5, 1, 2, 4, 8, 16, 32, 64+ ms) for p50 and p99. It is reset on a fresh start.
   - **In status:** `clock: {ticks, late_p50_ms, late_p99_ms, late_max_ms, stalls_over_4ms, last_stall_at_bar}`.
   - **Cost:** one subtraction and a bucket increment per tick, outside the lock, with no I/O on the clock thread.
   - **Exclude:** skip the final tick on stop (it is sent ahead of its slot).
   - **Tests:** a fake-port run with a forced 10 ms sleep in a tool call holding `_lock` shows a stall. An idle run shows p99 under 1 ms.
   - **Hardware:** checklist R10 asks Phil to copy the numbers.
2. **If §0.2 or (1) shows coarse sleeps on the Air** (a 1 ms sleep taking several ms, ticks p50 over 1 ms): sleep only until a margin before the next event, then busy-wait. In the wait loop of `Engine._run`, replace `time.sleep(max(0.0, min(wake - now, 0.002)))` with:

   ```python
   gap = wake - now
   if gap > SPIN_MARGIN:                  # e.g. 3 ms, or measured: the p99 of a 1 ms sleep at start-up, capped at 15 ms
       time.sleep(min(gap - SPIN_MARGIN, 0.002))
   # else: loop again without sleeping (busy-wait); the loop already re-reads perf_counter and flushes notes
   ```

   - **CPU:** the clock thread spins for up to `SPIN_MARGIN` before each tick and each note event: about 15 % of one core at 3 ms and 126 BPM, and up to 75 % at a 15 ms margin.
   - **GIL:** a spinning Python thread holds the GIL until its switch interval expires, which delays the gateway's own threads by up to 5 ms at a time.
   - **Measured on the macOS runner,** emulated from outside the engine with `clock_jitter.py --spin 1`: p50 halved from 9 to 4 ms. A margin as large as the runner's sleep would be needed to get under 1 ms.
   - **Gate it:** use `WHIPLASH_SPIN_MS`, with the default from a start-up measurement, so Linux and a precise Mac don't pay for it.
   - **Tests:** a fake time module whose `sleep` oversleeps by 10 ms must still give ticks under 1 ms late.
3. **Only if (1) shows GIL waits in the gateway** (p50 or p99 of about 5 ms): call `sys.setswitchinterval(0.001)` while playing and restore it on stop. Measured here: a busy in-process thread costs 5.1 ms per tick by default and 1.1 ms at 1 ms. It is process-wide, so the gateway's CPU-bound threads switch more often (a small throughput cost). Gate it with `WHIPLASH_SWITCH_INTERVAL` and say so in the README.
4. **Only if (1) shows rare 15-80 ms stalls** (GC of the gateway's heap): `gc.freeze()` at play start moves the existing heap out of the collector's view, so full collections only walk new objects. It is intrusive for the host: frozen cycles are never collected. The robust long-term fix for both 3 and 4 is to run the sequencer in its own process (its own GIL and heap), which is v0.7-sized.
5. **Not recommended:** macOS user-interactive QoS on the clock thread (`pthread_set_qos_class_self_np`). On the runners it changed nothing (§4). **Not recommended yet:** spreading the overdue ticks after a stall instead of sending them back to back. Sending them all keeps the unit's position exact. Whether the burst upsets the unit's tempo is §15.3 Q22; decide after R10.

## 7. For Phil's MacBook Air

- **Before the session:** checklist §0.2 runs `scripts/clock_jitter.py` on the Air (no unit needed) and records p99, max and unexcused stalls. That measures macOS scheduling on that machine, not the gateway.
- **During the session:** R10 watches the unit's tempo readout for flicker or hiccups.
- **If §0.2 shows a 1 ms sleep taking several ms on the Air,** tell the v0.6.2 agent before the demo: §6 item 2 is the fix. The rehearsal can't catch this, because its threshold follows the machine's own sleep.
- **On stage:** the demo itself is quiet (one Hermes turn at a time). The remaining risks are a gateway busy with CPU work or a large heap, both covered by §6 item 1.
- **Nothing here was tested on a Digitakt II.** Record results in [docs/digitakt-ii/reference.md](../digitakt-ii/reference.md) §15.3 Q22 with who, when and the OS version.
