#!/usr/bin/env python3
"""Rehearse the hackathon demo offline: no Digitakt, no rtmidi, nothing leaves the laptop.

    uv run python scripts/rehearse_demo.py               # real time, about 30 s
    uv run python scripts/rehearse_demo.py --speed 4     # 4x clock, about 8 s
    uv run python scripts/rehearse_demo.py --v06         # plus the optional v0.6 progression section
    uv run python scripts/rehearse_demo.py --v061        # plus the optional v0.6.1 fill + short_demo section

It runs the tool calls behind docs/demo/hackathon-demo.md (the hardware checklist's Part A,
A1-A9) through the real tool handlers and engine, in order, with the music running between
calls. The engine's output port is a recorder named like the unit, so nothing is sent anywhere.
Each call is made mid-bar, the way a slow model reply lands, and the script waits on Whiplash's
own clock before the next one.

It writes, into --out (default: <tmp>/whiplash-rehearsal):
- demo.mid: a type 1 Standard MIDI File of everything sent, one track per MIDI channel (notes
  and CCs), plus a conductor track with markers for every step, MIDI Start/Stop and each bar.
  A Standard MIDI File can't carry real-time bytes, so the MIDI clock is kept as timing instead:
  event times are the engine's own (musical) time, at a fixed 120 BPM tempo map, so the file plays
  back at the speed the demo ran, swing and tempo switch included. Played through a DAW it sends
  notes and CCs only (including CC 19 slot 9 and the filter sweep on track 6): reload the pattern
  on the unit afterwards ([FUNC] + [NO]) and don't save.
- report.txt: per step, the calls and key results, which tracks sounded, CCs sent, when each
  change landed relative to the bar line, warnings, and the checks. Then the global checks: no
  SysEx or program change, no blocked CC, no hanging notes, and clock timing: each tick's real-time
  lateness against the engine's own grid. Ticks more than 4 ms late form a stall, which counts against
  Whiplash unless a separate canary process saw the machine stall at the same moment; a segment may have
  one such stall, plus one per 10 s of real time, plus one per machine stall the canary saw during it
  (see docs/testing/clock-jitter.md).
- results.json: every tool result, as Hermes would see it.

Exit status: 0 if every check passed, 1 on any violation, 2 if the rehearsal itself crashed.
--speed scales the engine's clock (its perf_counter and sleep), not the tool calls: the beat,
bar quantize and ramps behave as at 1x. Lateness is measured in real time either way.

--v06 adds an optional section after Part A (off by default, so the default run stays the demo):
"deep house in A minor, i-VI-III-VII, two bars per chord, pads on track 7" (hardware check HW 6.0-1,
checklist P1, and the demo's optional encore), with the synth (slot 11) on the pad track. It checks that every chord change lands on a bar line, the bass plays the roots,
drum notes never transpose, the tuned cymbal and the fx track get no chord notes, and the visualiser
shows the key and the chords.

--v061 adds another optional section (off by default; after --v06's when both are given), in two runs:
1. "Play techno, and make it a 30-second track" (the demo's optional arrangement beat; hardware check HW 6.1-1,
   checklist R1): whiplash_arrange short_demo, then "which section are we in?". It checks each section starts
   on its bar line with only its own tracks sounding, the kick sits out the build's last bar, status names the
   section, and the run stops by itself on the bar line after the outro, with MIDI Stop and no hanging notes.
2. "Track 9 is my kick", techno, a fill, stop (HW 6.1-2, checklist R2): the kick plays on track 9 only and
   sits out the fill bar's last beat.

This is a rehearsal against a recording port. It proves nothing about how the unit sounds or
responds: that still needs docs/testing/hardware-checklist.md Part A on a real Digitakt II.
"""
import argparse
import collections
import importlib.util
import json
import socket
import statistics
import subprocess
import sys
import tempfile
import threading
import time
import traceback
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEVICE = "Elektron Digitakt II"
BAR = 96  # MIDI clocks per bar (24 PPQN, 4/4)
SMF_TPB = 960  # SMF ticks per beat; the tempo map is a fixed 120 BPM, so 1920 ticks per second
SMF_TEMPO = 500_000
SMF_TICKS_PER_SEC = SMF_TPB * 1_000_000 / SMF_TEMPO
# Clock timing (docs/testing/clock-jitter.md). Each tick's lateness is measured against the engine's own absolute
# grid, in real time. Ticks later than LATE_MS are grouped into stalls (runs of late ticks). A stall counts against
# Whiplash unless an independent process (the canary) saw the machine stall at the same moment. A segment may have
# one stall, plus one per STALL_EVERY seconds of real time, plus one per machine stall the canary saw during the
# segment (a contended machine also preempts the clock thread on its own core, where the canary can't see it).
# A regression in the engine repeats (every bar, every tool call) on a quiet machine and still fails; one burst of
# CI-runner noise doesn't.
LATE_MS = 4.0  # under the ~6 ms timing JND at 16th-note spacing; above the 1 ms USB-MIDI frame
STALL_EVERY = 10.0  # seconds of real time per extra stall allowed
CANARY_STALL = 0.002  # the canary sleeps 1 ms at a time; waking more than 2 ms late is a machine stall
OK_TYPES = {"note_on", "note_off", "control_change", "clock", "start", "stop", "continue"}


def load_whiplash():
    """Load the repo root as package 'whiplash', the way Hermes and tests/conftest.py do."""
    if "whiplash" in sys.modules:
        return sys.modules["whiplash"]
    spec = importlib.util.spec_from_file_location("whiplash", ROOT / "__init__.py",
                                                  submodule_search_locations=[str(ROOT)])
    mod = importlib.util.module_from_spec(spec)
    sys.modules["whiplash"] = mod
    spec.loader.exec_module(mod)
    return mod


class ScaledTime:
    """Stands in for the time module inside engine.py and view.py: perf_counter runs `speed` times
    faster and sleep is `speed` times shorter. Everything else is the real time module."""

    def __init__(self, speed):
        self.speed = speed
        self._t0 = time.perf_counter()

    def perf_counter(self):
        return self._t0 + (time.perf_counter() - self._t0) * self.speed

    def sleep(self, seconds):
        time.sleep(max(0.0, seconds) / self.speed)

    def __getattr__(self, name):
        return getattr(time, name)


@dataclass
class Sent:
    real: float  # time.perf_counter() when the engine sent it
    music: float  # the engine's own (scaled) clock
    run: int  # which play-from-stop this belongs to
    clocks: int  # MIDI clocks sent in this run before this message
    msg: object

    @property
    def where(self):
        return f"run {self.run} bar {self.clocks // BAR} tick {self.clocks % BAR}"


class RecordingPort:
    """The engine's output port. Records everything, sends nothing, never refuses anything: the checks
    look at what the engine actually tried to send, so a filter bypass would still be caught."""

    def __init__(self, clock):
        self.clock = clock
        self.sent = []
        self.run = 0
        self.clocks = 0
        self.closed = False
        self._lock = threading.Lock()

    def send(self, msg):
        real, music = time.perf_counter(), self.clock.perf_counter()
        with self._lock:
            self.sent.append(Sent(real, music, self.run, self.clocks, msg.copy()))
            if msg.type == "clock":
                self.clocks += 1

    def new_run(self):
        with self._lock:
            self.run += 1
            self.clocks = 0

    def position(self):
        with self._lock:
            return self.run, self.clocks, len(self.sent)

    def close(self):
        self.closed = True


CANARY_CODE = r"""
import json, sys, threading, time
done = threading.Event()
threading.Thread(target=lambda: (sys.stdin.read(), done.set()), daemon=True).start()
sleeps = []
print(json.dumps({"t0": time.perf_counter()}), flush=True)
while not done.is_set():
    a = time.perf_counter()
    time.sleep(0.001)
    sleeps.append((a, time.perf_counter()))
print(json.dumps({"sleeps": sleeps}), flush=True)
"""


class Canary:
    """A separate Python process that sleeps 1 ms at a time for the whole run and records how long each sleep took.

    It gives two things:
    - **The machine's timing floor.** On Linux a 1 ms sleep takes about 1.1 ms; on a macOS CI runner it took about
      7 ms (docs/testing/clock-jitter.md §4). The engine waits in short sleeps too, so a tick is only counted as
      late beyond what a sleep costs on this machine: `late_threshold` is LATE_MS, or the canary's p99 sleep if
      that is longer.
    - **Machine stalls:** sleeps longer than `stall_threshold` (2 ms, or 3x the canary's median sleep if that is
      longer). A tick late during one is excused, and each one during a segment adds to its allowance.

    Whiplash's own causes of lateness (work on the clock thread, its lock held by a tool call, a busy Python thread
    or a garbage collection in its process) don't slow another process, so they are never excused on a quiet
    machine. perf_counter is a system-wide monotonic clock on Linux and macOS (mach time / CLOCK_MONOTONIC)."""

    def __init__(self, limit=CANARY_STALL):
        self.limit, self.proc, self.offset = limit, None, 0.0
        self.sleeps, self.stalls, self.loops = [], [], 0
        self.sleep_p50 = self.sleep_p99 = None
        self.stall_threshold, self.late_threshold = limit, LATE_MS / 1000

    def start(self):
        try:
            self.proc = subprocess.Popen([sys.executable, "-I", "-c", CANARY_CODE],
                                         stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
            self.offset = time.perf_counter() - json.loads(self.proc.stdout.readline())["t0"]  # pipe latency only
        except Exception:
            self.proc = None  # no canary: nothing is excused, and LATE_MS is the threshold
        return self

    def stop(self):
        if self.proc is None:
            return self
        try:
            out, _ = self.proc.communicate("", timeout=30)
            self.sleeps = [tuple(x) for x in json.loads(out.strip().splitlines()[-1])["sleeps"]]
        except Exception:
            self.proc.kill()
            self.sleeps = []
        return self._digest()

    def _digest(self):
        """From the recorded sleeps: the machine's sleep percentiles, both thresholds and the stalls."""
        self.loops = len(self.sleeps)
        if self.sleeps:
            took = sorted(b - a for a, b in self.sleeps)
            self.sleep_p50, self.sleep_p99 = took[len(took) // 2], took[min(len(took) - 1, int(len(took) * 0.99))]
            self.stall_threshold = max(self.limit, 3 * self.sleep_p50)
            self.late_threshold = max(LATE_MS / 1000, self.sleep_p99)
            self.stalls = [(a, b) for a, b in self.sleeps if b - a > self.stall_threshold]
        return self

    def covers(self, start, end, slack=0.0005):
        return any(a - slack <= end and b + slack >= start for a, b in self.stalls)

    def count(self, start, end):
        """Machine stalls the canary saw between start and end."""
        return sum(1 for a, b in self.stalls if a <= end and b >= start)

    def describe(self):
        if self.proc is None:
            return "no canary: nothing excused"
        if not self.sleeps:
            return "the canary returned nothing: nothing excused"
        return (f"a 1 ms sleep took p50 {self.sleep_p50 * 1000:.2f} / p99 {self.sleep_p99 * 1000:.2f} ms over "
                f"{self.loops} sleeps; {len(self.stalls)} machine stall(s) over {self.stall_threshold * 1000:.1f} ms"
                + (f", longest {max(b - a for a, b in self.stalls) * 1000:.1f} ms" if self.stalls else "")
                + f"; ticks count as late over {self.late_threshold * 1000:.1f} ms")


def lateness(clocks, speed):
    """Real-time lateness (seconds) of each clock in one constant-tempo stretch, against the engine's absolute
    grid (it schedules next_tick += tick_len, so lateness never accumulates). The period is the median one-bar
    span / 96 of the engine's own clock, the grid is anchored on the least-late tick: a lower bound, >= 0."""
    music = [s.music for s in clocks]
    span = min(BAR, len(music) - 1)
    period = statistics.median((music[k + span] - music[k]) / span for k in range(len(music) - span))
    grid = [m - k * period for k, m in enumerate(music)]
    origin = min(grid)
    return [(g - origin) / speed for g in grid]


def timing(clocks, speed, canary):
    """Lateness of one stretch of clocks: percentiles (ms), the ticks later than the canary's late_threshold (LATE_MS
    on a machine with precise sleeps), and those grouped into
    stalls (late ticks with at most one on-time tick between them). A stall is excused when the canary saw the
    machine stall during any of its ticks. `allowed` is how many unexcused stalls the segment may have."""
    late = lateness(clocks, speed)
    limit = getattr(canary, "late_threshold", LATE_MS / 1000)
    over = [k for k, l in enumerate(late) if l > limit]
    stalls = []
    for k in over:
        if stalls and k - stalls[-1][-1] <= 2:
            stalls[-1].append(k)
        else:
            stalls.append([k])
    seen = lambda k: canary.covers(clocks[k].real - late[k], clocks[k].real)
    unexcused = [st for st in stalls if not any(seen(k) for k in st)]
    ms = sorted(l * 1000 for l in late)
    pick = lambda p: ms[min(len(ms) - 1, int(len(ms) * p))]
    seconds = clocks[-1].real - clocks[0].real
    contended = canary.count(clocks[0].real, clocks[-1].real)
    return {"ticks": len(late), "p50": pick(0.5), "p99": pick(0.99), "max": ms[-1], "over": len(over),
            "stalls": len(stalls), "unexcused": len(unexcused), "contended": contended, "limit_ms": limit * 1000,
            "allowed": 1 + int(seconds / STALL_EVERY) + contended,
            "where": [f"{clocks[st[0]].where} ({len(st)} ticks, {max(late[k] for k in st) * 1000:.1f} ms)"
                      for st in unexcused]}


# ---- the demo, step by step -------------------------------------------------------------------

@dataclass
class Step:
    id: str
    prompt: str
    calls: list
    at: tuple = None  # (bar, tick) in the current run to make the first call at; None = now
    new_run: bool = False  # a play from stop: the recorder starts counting clocks again
    probe_view: bool = False
    results: list = field(default_factory=list)
    probe: tuple = None  # (HTTP status, /state frame or error) when probe_view
    wait_stop: bool = False  # after the calls, wait for the run to stop by itself (an arrangement's end)
    call_pos: tuple = None  # (run, clocks, index into sent)


def demo_steps():
    """The calls the hardware checklist's Part A expects Hermes to make, in order (A1-A9)."""
    return [
        Step("A1", "Is my Digitakt connected? And launch the visualiser.",
             [("whiplash_list_midi_ports", {}), ("whiplash_open_view", {"open_browser": False})]),
        Step("A2", "Tracks 7 and 8 are tuned cymbals. Sample slot 9 is my dirty bass, and slot 11 is a synth I like.",
             [("whiplash_label_tracks", {"tracks": {"7": "tuned cymbal", "8": "tuned cymbal"},
                                         "slots": {"9": "dirty bass", "11": "synth I like"}})]),
        Step("A3", "Play some groovy deep house with the dirty bass on track 6.",
             [("whiplash_play_pattern", {"genre": "deephouse", "tracks": {"6": {"slot": 9}}})],
             new_run=True, probe_view=True),
        Step("A4", "Close the filter on the bass, then open it slowly over 8 bars.",
             [("whiplash_set_param", {"track": 6, "param": "filter_freq", "value": 20}),
              ("whiplash_ramp_param", {"track": 6, "param": "filter_freq", "to": 110, "bars": 8})], at=(2, 37)),
        Step("A5", "Give track 8 a melody: eighth notes in A minor, degrees 1 3 5 8 7 5 3 1, length 2.",
             [("whiplash_write_part", {"track": 8, "rhythm": "8ths", "key": "A", "scale": "minor",
                                       "notes": "1 3 5 8 7 5 3 1", "length": 2})], at=(3, 50)),
        Step("A6", "Drop the kick and bass for two bars with a fill.",
             [("whiplash_mutate", {"action": "drop", "tracks": [1, 6], "bars": 2, "fill": True})], at=(5, 20)),
        Step("A7", "Switch to tech house on the next bar.",
             [("whiplash_play_pattern", {"genre": "tech house"})], at=(8, 61)),
        Step("A8", "What's playing? Give me the per-track details.",
             [("whiplash_status", {})], at=(11, 10)),
        Step("A9", "Stop.", [("whiplash_stop", {})], at=(12, 5)),
        Step("A9b", "Play techno. (checklist A9: the kit map survived the stop, the melody did not)",
             [("whiplash_play_pattern", {"genre": "techno"})], new_run=True),
        Step("A9c", "Stop.", [("whiplash_stop", {})], at=(2, 30)),
    ]


V06_PROMPT = ("Track 7 is a pad now. Play deep house in A minor with the dirty bass on 6 and my synth on 7: "
              "i-VI-III-VII, two bars per chord.")
V06_CHORDS = ("i", "VI", "III", "VII")
V06_BARS_PER_CHORD = 2
V06_STOP_BAR = 10  # a full 8-bar loop of the progression, and the wrap back to i on bar 9


def v06_steps():
    """Optional (--v06): the v0.6.0 progression beat (hardware checklist P1, HW 6.0-1; the demo's encore). It runs
    after Part A, so the kit map still says tracks 7-8 are tuned cymbals: 7 is relabelled a pad (9 is marked fx,
    so the run also proves an fx track gets nothing), then one start with slots and key, then the progression."""
    return [
        Step("H1", V06_PROMPT,
             [("whiplash_label_tracks", {"tracks": {"7": "pad", "9": "fx"}}),
              ("whiplash_play_pattern", {"genre": "deephouse", "key": "A", "scale": "minor",
                                         "tracks": {"6": {"slot": 9}, "7": {"slot": 11}}}),
              ("whiplash_set_progression", {"chords": "-".join(V06_CHORDS), "bars_per_chord": V06_BARS_PER_CHORD})],
             new_run=True, probe_view=True),
        Step("H2", "Stop.", [("whiplash_stop", {})], at=(V06_STOP_BAR, 5)),
    ]


V061_SECONDS = 30  # short_demo's minimum: 16 bars at techno's 130 BPM (intro, build, drop, outro; 4 bars each)
V061_SECTIONS = ["intro", "build", "drop", "outro"]
V061_PROMPT = f"Play techno, and make it a {V061_SECONDS}-second track: intro, build, drop, outro."


def v061_steps():
    """Optional (--v061): whiplash_arrange and fills by role (hardware checklist R1-R2, HW 6.1-1 and 6.1-2).
    Run 1 is the demo's optional arrangement beat: one start, one arrangement, and it ends the run by itself,
    so there is no stop call. Run 2 labels a kick on track 9: the routing moves the kick there and the fill
    follows it (not a demo step: it needs a kick sample on track 9 and channel 9 free on the unit)."""
    return [
        Step("V1", V061_PROMPT, [("whiplash_play_pattern", {"genre": "techno"}),
                                 ("whiplash_arrange", {"preset": "short_demo", "seconds": V061_SECONDS})],
             new_run=True),
        Step("V2", "Which section are we in? (then the arrangement stops the run by itself)",
             [("whiplash_status", {})], at=(6, 10), wait_stop=True),
        Step("V3", "Track 9 is my kick. Play techno.",
             [("whiplash_label_tracks", {"tracks": {"9": "kick"}}), ("whiplash_play_pattern", {"genre": "techno"})],
             new_run=True),
        Step("V4", "Give me a fill.", [("whiplash_mutate", {"action": "fill"})], at=(1, 40)),
        Step("V5", "Stop.", [("whiplash_stop", {})], at=(3, 20)),
    ]


class Rehearsal:
    def __init__(self, speed=1.0, out=None, log=print, v06=False, v061=False):
        self.speed = speed
        self.out = Path(out) if out else Path(tempfile.gettempdir()) / "whiplash-rehearsal"
        self.log = log
        self.whiplash = load_whiplash()
        from whiplash import engine, tools, view
        self.engine_mod, self.tools, self.view = engine, tools, view
        self.clock = ScaledTime(speed)
        self.port = RecordingPort(self.clock)
        self.v06, self.v061 = v06, v061
        self.steps = demo_steps() + (v06_steps() if v06 else []) + (v061_steps() if v061 else [])
        self.violations = []  # (where, text)
        self.canary = Canary()
        self.view_probe = None
        self.end = None  # len(port.sent) when the run finished

    # -- running ------------------------------------------------------------------------------
    def _opener(self, name):
        if name not in (None, DEVICE):
            raise self.engine_mod.WhiplashError(f"rehearsal: only {DEVICE!r} exists here, not {name!r}")
        return self.port, DEVICE, False

    def _patch(self):
        eng = self.engine_mod
        saved = (self.tools.ENGINE, eng.time, self.view.time, eng.list_ports)
        self.engine = eng.Engine(opener=self._opener, lister=lambda: [DEVICE])
        self.tools.ENGINE = self.engine
        eng.time = self.view.time = self.clock
        eng.list_ports = lambda: {"outputs": [DEVICE], "inputs": [DEVICE]}
        return saved

    def _unpatch(self, saved):
        eng = self.engine_mod
        try:
            self.engine.shutdown()
            self.view.close_view()
        finally:
            self.tools.ENGINE, eng.time, self.view.time, eng.list_ports = saved

    def _wait_for(self, bar, tick):
        target = bar * BAR + tick
        tick_real = 60.0 / max(self.engine.bpm, 30) / 24 / self.speed
        deadline = time.perf_counter() + (target - self.port.clocks) * tick_real * 4 + 5
        while self.port.clocks < target:
            if not self.engine.playing():
                raise RuntimeError(f"the sequencer stopped while waiting for bar {bar} tick {tick}")
            if time.perf_counter() > deadline:
                raise RuntimeError(f"the clock stalled waiting for bar {bar} tick {tick} (at {self.port.clocks})")
            time.sleep(0.0005)

    def _wait_stopped(self, limit_bars=64):
        """Wait for the sequencer to stop by itself (an arrangement ending), at most limit_bars."""
        deadline = time.perf_counter() + limit_bars * 4 * 60.0 / max(self.engine.bpm, 30) / self.speed * 2 + 5
        while self.engine.playing():
            if time.perf_counter() > deadline:
                raise RuntimeError(f"the run didn't stop by itself within {limit_bars} bars")
            time.sleep(0.005)

    def _free_port(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def run(self):
        saved = self._patch()
        self.canary.start()
        try:
            for step in self.steps:
                if step.at:
                    self._wait_for(*step.at)
                if step.new_run:
                    self.port.new_run()
                step.call_pos = self.port.position()
                for name, params in step.calls:
                    if name == "whiplash_open_view":
                        params = {**params, "port": self._free_port()}
                    raw = self.tools.HANDLERS[name](dict(params))
                    step.results.append((name, params, json.loads(raw)))
                self.log(f"{step.id} {step.calls[0][0]} at {self._pos(step)}")
                if step.probe_view:
                    self._wait_for(1, 48)  # mid bar 1: the beat (and a progression set for bar 1) is running
                    self._probe_view(step)
                if step.wait_stop:
                    self._wait_stopped()
            time.sleep(0.05)
        finally:
            self.canary.stop()
            self._unpatch(saved)
        self.end = len(self.port.sent)

    def _probe_view(self, step):
        url = next((r.get("url") for _, _, r in self.steps[0].results if r.get("url")), None)
        if not url:
            return
        try:
            with urllib.request.urlopen(url.rstrip("/") + "/state", timeout=5) as resp:
                step.probe = (resp.status, json.loads(resp.read()))
        except Exception as exc:
            step.probe = (None, f"{type(exc).__name__}: {exc}")
        if self.view_probe is None:
            self.view_probe = step.probe

    @staticmethod
    def _pos(step):
        run, clocks, _ = step.call_pos
        return f"run {run} bar {clocks // BAR} tick {clocks % BAR}" if run else "before any clock"

    # -- analysis -----------------------------------------------------------------------------
    def window(self, i):
        start = self.steps[i].call_pos[2]
        end = self.steps[i + 1].call_pos[2] if i + 1 < len(self.steps) else self.end
        return self.port.sent[start:end]

    def fail(self, where, text):
        self.violations.append((where, text))
        return False

    def check(self, where, ok, text, lines):
        lines.append(f"  [{'ok' if ok else 'FAIL'}] {text}")
        if not ok:
            self.fail(where, text)
        return ok

    def run_events(self, run):
        return [s for s in self.port.sent if s.run == run]

    def notes_in_bar(self, run, bar, channel):
        return [s for s in self.run_events(run) if s.msg.type == "note_on" and s.msg.channel == channel
                and s.clocks // BAR == bar]

    @staticmethod
    def summarize(window, lines):
        ons = collections.Counter(s.msg.channel for s in window if s.msg.type == "note_on")
        if ons:
            lines.append("  sounded: " + ", ".join(f"track {ch + 1} x{n}" for ch, n in sorted(ons.items())))
        else:
            lines.append("  sounded: nothing")
        ccs = collections.defaultdict(list)
        for s in window:
            if s.msg.type == "control_change":
                ccs[(s.msg.channel, s.msg.control)].append(s.msg.value)
        from whiplash import ccmap
        for (ch, cc), values in sorted(ccs.items()):
            spec = ccmap.BY_CC.get(cc)
            name = spec.name if spec else {123: "all notes off"}.get(cc, "raw")
            span = f"{values[0]}" if len(set(values)) == 1 else f"{values[0]} -> {values[-1]}"
            lines.append(f"  cc: track {ch + 1} CC {cc} ({name}) x{len(values)}, {span}")
        other = collections.Counter(s.msg.type for s in window if s.msg.type in ("start", "stop", "continue"))
        if other:
            lines.append("  transport: " + ", ".join(f"{k} x{v}" for k, v in sorted(other.items())))
        clocks = sum(s.msg.type == "clock" for s in window)
        lines.append(f"  clock: {clocks} ticks in this step")

    def analyse(self):
        self.violations = []
        lines = [f"Whiplash demo rehearsal: {time.strftime('%Y-%m-%d %H:%M:%S')}",
                 f"speed {self.speed}x, output: recording port named {DEVICE!r} (fake; nothing was sent to "
                 "any device), whiplash v" + self._version(),
                 f"{len(self.port.sent)} messages recorded across {self.port.run} run(s)",
                 "Not a hardware test: run docs/testing/hardware-checklist.md Part A on the unit"
                 + (" (and P1 for the v0.6 section)" if self.v06 else "")
                 + (" (and R1-R2 for the v0.6.1 section)" if self.v061 else "") + ".", ""]
        r = {s.id: s for s in self.steps}
        for i, step in enumerate(self.steps):
            lines.append(f"{step.id}  \"{step.prompt}\"")
            lines.append(f"  called at {self._pos(step)}")
            for name, params, res in step.results:
                lines.append(f"  -> {name}({json.dumps(params, separators=(',', ':'))}) success={res.get('success')}")
                self.check(step.id, res.get("success") is True, f"{name} succeeded"
                           + ("" if res.get("success") else f": {res.get('error')}"), lines)
                for key in ("warning", "notice", "port_lost"):
                    if res.get(key):
                        lines.append(f"  warning ({key}): {res[key]}")
                        self.fail(step.id, f"{name} returned {key}: {res[key]}")
                if res.get("overlap_warning"):
                    lines.append(f"  note: overlap_warning present (transport_mode {res.get('transport_mode')}); "
                                 "Hermes should pass it on")
            self.summarize(self.window(i), lines)
            getattr(self, "check_" + step.id.lower(), lambda *a: None)(step, r, lines)
            lines.append("")
        lines.append("Global")
        self.check_global(lines)
        verdict = "PASS" if not self.violations else f"FAIL ({len(self.violations)} violation(s))"
        lines += ["", f"RESULT: {verdict}"]
        for where, text in self.violations:
            lines.append(f"  - {where}: {text}")
        return "\n".join(lines) + "\n"

    def _version(self):
        import tomllib
        return tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]

    @staticmethod
    def res(step, n=0):
        return step.results[n][2] if len(step.results) > n else {}

    # per-step checks: what the hardware checklist's Part A expects, as far as it shows in the MIDI
    def check_a1(self, step, r, lines):
        ports, view = self.res(step, 0), self.res(step, 1)
        self.check("A1", ports.get("digitakt") == DEVICE, f"list_midi_ports finds {DEVICE!r}", lines)
        self.check("A1", bool(view.get("url")), f"open_view serves {view.get('url')}", lines)
        self.check("A1", not self.window(0), "nothing sent to the unit", lines)

    def check_a2(self, step, r, lines):
        res = self.res(step)
        kit = res.get("kit", {})
        roles = {t: kit.get("tracks", {}).get(t, {}).get("role") for t in ("7", "8")}
        self.check("A2", roles == {"7": "cymbal", "8": "cymbal"}, f"tracks 7 and 8 are role cymbal ({roles})", lines)
        self.check("A2", set(kit.get("slots", {})) == {"9", "11"}, "slots 9 and 11 labelled", lines)
        self.check("A2", res.get("applies") == "next whiplash_play_pattern", f"applies: {res.get('applies')}", lines)
        self.check("A2", not self.window(1), "nothing sent to the unit", lines)

    def check_a3(self, step, r, lines):
        res = self.res(step)
        idx = self.steps.index(step)
        win = self.window(idx)
        self.check("A3", res.get("mode") == "started" and res.get("playing") == "deephouse",
                   f"started {res.get('playing')} at {res.get('bpm')} BPM, swing {res.get('swing')}", lines)
        label = res.get("setup", {}).get("tracks", {}).get("6", {}).get("slot_label")
        self.check("A3", label == "dirty bass", f"setup echoes track 6 slot_label {label!r}", lines)
        slot = [k for k, s in enumerate(win) if s.msg.type == "control_change" and s.msg.channel == 5
                and s.msg.control == 19]
        first_clock = next((k for k, s in enumerate(win) if s.msg.type == "clock"), None)
        first_bass = next((k for k, s in enumerate(win) if s.msg.type == "note_on" and s.msg.channel == 5), None)
        self.check("A3", bool(slot) and win[slot[0]].msg.value == 9, "CC 19 = 9 on track 6 (slot 9)", lines)
        if res.get("send_transport"):
            start = next((k for k, s in enumerate(win) if s.msg.type == "start"), None)
            self.check("A3", bool(slot) and start is not None and slot[0] < start < first_clock,
                       "CC 19 goes out before MIDI Start, Start before the first clock", lines)
        self.check("A3", bool(slot) and first_bass is not None and slot[0] < first_bass,
                   "the first bass note already follows the slot change", lines)
        tracks = res.get("tracks", {})
        pitch6 = (tracks.get("6") or {}).get("pitch") or {}
        lines.append(f"  track 6 pitch: {json.dumps(pitch6, separators=(',', ':'))}")
        self.check("A3", pitch6.get("low") == 52 and pitch6.get("high") == 65 and not pitch6.get("register_shift"),
                   "track 6 pitch low 52, high 65, no register_shift (checklist A3)", lines)
        ons = {s.msg.channel + 1 for s in win if s.msg.type == "note_on"}
        self.check("A3", 7 in ons, "track 7 (tuned cymbal) plays the open-hat line", lines)
        self.check("A3", 8 not in ons, "track 8 stays silent (no part routed)", lines)
        self.check("A3", not (ons - {1, 2, 3, 4, 6, 7}), f"only tracks 1-4, 6, 7 sound ({sorted(ons)})", lines)
        roles = {t: (v or {}).get("role") for t, v in tracks.items()}
        bad = {t: ro for t, ro in roles.items() if ro and any(w in ro for w in ("chord", "pad", "stab"))}
        self.check("A3", not bad, f"no chord parts anywhere ({bad or 'none'})", lines)
        routing = res.get("routing") or {}
        self.check("A3", routing.get("vacated") == {"5": 7} and bool(routing.get("vacated_note"))
                   and routing.get("silent_until_written") == [8] and bool(routing.get("dropped")),
                   f"routing: chords dropped {sorted(routing.get('dropped') or {})}, silent_until_written "
                   f"{routing.get('silent_until_written')}, vacated {routing.get('vacated')} with a note (v0.6.1)", lines)
        if step.probe is not None:
            status, body = step.probe
            ok = status == 200 and isinstance(body, dict) and body.get("playing") is True
            self.check("A3", ok, f"visualiser /state answers while playing (HTTP {status})", lines)

    def check_a4(self, step, r, lines):
        run, at, _ = step.call_pos
        ramp = [s for s in self.run_events(run) if s.msg.type == "control_change" and s.msg.channel == 5
                and s.msg.control == 74]
        values = [s.msg.value for s in ramp]
        self.check("A4", bool(values) and values[0] == 20, "CC 74 (filter_freq) = 20 on track 6 first", lines)
        self.check("A4", values == sorted(values) and bool(values) and values[-1] == 110,
                   f"the sweep only rises and ends at 110 ({len(values)} CCs, no repeats: "
                   f"{len(values) == len(set(values))})", lines)
        if len(ramp) > 1:
            span = ramp[-1].clocks - ramp[0].clocks
            lines.append(f"  sweep: {ramp[0].where} -> {ramp[-1].where}, {span} clocks ({span / BAR:.2f} bars)")
            # the last CC goes out when the rounded value first reaches 110, up to half a CC step early
            slack = 8 * BAR / (2 * abs(values[-1] - values[0])) + 2
            self.check("A4", abs(span - 8 * BAR) <= slack, "the sweep lasts 8 bars on Whiplash's clock "
                       f"(within {slack:.1f} clocks)", lines)

    def check_a5(self, step, r, lines):
        run, at, _ = step.call_pos
        res = self.res(step)
        bar = at // BAR + 1
        ons = [s for s in self.run_events(run) if s.msg.type == "note_on" and s.msg.channel == 7]
        first = ons[0] if ons else None
        self.check("A5", first is not None and first.clocks == bar * BAR,
                   f"the melody starts exactly on the next bar line (bar {bar}): "
                   f"{first.where if first else 'never'}", lines)
        notes = [s.msg.note for s in self.notes_in_bar(run, bar, 7)]
        from whiplash import patterns
        lines.append("  bar notes: " + " ".join(patterns.note_name(n) for n in notes))
        self.check("A5", len(notes) == 8 and notes[0] == notes[-1] and notes[3] - notes[0] == 12,
                   "eight 8ths, up an octave and back (1 3 5 8 7 5 3 1)", lines)
        lines.append(f"  pitch {json.dumps(res.get('pitch'), separators=(',', ':'))}")
        if res.get("length_audible"):
            lines.append(f"  {res['length_audible']}")
        sent_env = [s for s in self.window(self.steps.index(step)) if s.msg.type == "control_change"
                    and s.msg.channel == 7 and s.msg.control in (80, 87)]
        self.check("A5", not sent_env, "no envelope change on track 8", lines)

    def check_a6(self, step, r, lines):
        run, at, _ = step.call_pos
        res = self.res(step)
        first, back = res.get("from_bar"), res.get("returns_at_bar")
        self.check("A6", first == at // BAR + 1 and back == first + 2,
                   f"drop from bar {first}, back at bar {back}, fill at bar {res.get('fill_at_bar')}", lines)
        if first is None:
            return
        for ch, name in ((0, "kick"), (5, "bass")):
            during = sum(len(self.notes_in_bar(run, b, ch)) for b in range(first, back))
            self.check("A6", during == 0, f"no {name} (track {ch + 1}) during the drop", lines)
        kick = self.notes_in_bar(run, back, 0)
        self.check("A6", bool(kick) and kick[0].clocks == back * BAR, "the kick slams back on the one", lines)
        bass = self.notes_in_bar(run, back, 5)
        self.check("A6", bool(bass), f"the bass returns in bar {back} "
                   f"({bass[0].where if bass else 'never'})", lines)
        melody = sum(len(self.notes_in_bar(run, b, 7)) for b in range(first, back))
        self.check("A6", melody > 0, "the melody on track 8 keeps playing", lines)
        if res.get("fill_at_bar") is not None:
            fill = res["fill_at_bar"]
            drums = lambda b: sum(len(self.notes_in_bar(run, b, ch)) for ch in (1, 2, 3, 4))
            self.check("A6", drums(fill) > drums(first), f"the fill bar has more snare/clap/hat hits "
                       f"({drums(fill)} vs {drums(first)})", lines)

    def check_a7(self, step, r, lines):
        run, at, _ = step.call_pos
        res = self.res(step)
        bar = res.get("switch_at_bar")
        self.check("A7", res.get("mode") == "queued" and res.get("next") == "techhouse" and bar == at // BAR + 1,
                   f"'tech house' queued as {res.get('next')} for bar {bar}", lines)
        self.check("A7", res.get("bpm_at_switch") == 126, f"bpm at switch {res.get('bpm_at_switch')}", lines)
        pitch6 = ((res.get("tracks") or {}).get("6") or {}).get("pitch") or {}
        lines.append(f"  track 6 pitch: {json.dumps(pitch6, separators=(',', ':'))}")
        self.check("A7", pitch6.get("low") == 55 and pitch6.get("high") == 62,
                   "track 6 pitch low 55, high 62 (checklist A7)", lines)
        routing = res.get("routing") or {}
        self.check("A7", routing.get("written") == [8] and routing.get("vacated") == {"5": 7},
                   f"routing: written {routing.get('written')}, vacated {routing.get('vacated')} (v0.6.1)", lines)
        if bar is None:
            return
        events = self.run_events(run)
        stops = [s for s in events if s.msg.type in ("start", "stop") and 0 < s.clocks < r["A9"].call_pos[1]]
        self.check("A7", not stops, "no MIDI Stop/Start around the switch", lines)
        before, after = self.bpm_of(events, bar - 2), self.bpm_of(events, bar + 1)
        lines.append(f"  measured tempo: bars {bar - 2}-{bar - 1} {before:.1f} BPM, bars {bar + 1}-{bar + 2} "
                     f"{after:.1f} BPM")
        self.check("A7", abs(before - 122) < 1 and abs(after - 126) < 1, "the tempo goes 122 -> 126 at the switch",
                   lines)
        kick = self.notes_in_bar(run, bar, 0)
        self.check("A7", bool(kick) and kick[0].clocks == bar * BAR, "tech house's first kick is on the bar line",
                   lines)
        self.check("A7", len(self.notes_in_bar(run, bar, 7)) == 8, "the melody on track 8 carries over", lines)

    def check_a8(self, step, r, lines):
        res = self.res(step)
        tracks = res.get("tracks", {})
        self.check("A8", res.get("roles_assumed") is False, "roles_assumed false", lines)
        for t in ("7", "8"):
            info = tracks.get(t) or {}
            self.check("A8", info.get("role") == "tuned cymbal" and info.get("kit_role") == "cymbal",
                       f"track {t} role {info.get('role')!r}, kit_role {info.get('kit_role')!r}", lines)
        six = tracks.get("6") or {}
        self.check("A8", six.get("slot") == 9 and six.get("slot_label") == "dirty bass" and six.get("tune") is None,
                   f"track 6 slot {six.get('slot')} {six.get('slot_label')!r}, tune {six.get('tune')}", lines)
        self.check("A8", (six.get("last_cc") or {}).get("filter_freq") == 110,
                   f"track 6 filter_freq {(six.get('last_cc') or {}).get('filter_freq')}", lines)
        self.check("A8", (tracks.get("8") or {}).get("part") == "written" and "8" in res.get("parts", {}),
                   "track 8 part written", lines)
        self.check("A8", res.get("last_error") is None, f"last_error {res.get('last_error')}", lines)

    def check_a9(self, step, r, lines):
        run, at, idx = step.call_pos
        events = self.run_events(run)
        tail = [s for s in self.port.sent[idx:] if s.run == run]
        self.check("A9", self.res(step).get("was_playing") is True, "stopped a running beat", lines)
        self.check("A9", not self.hanging(events), f"no hanging notes ({self.hanging(events) or 'none'})", lines)
        panic = {s.msg.channel for s in tail if s.msg.type == "control_change" and s.msg.control == 123}
        self.check("A9", set(range(8)) <= panic, f"All Notes Off on channels 1-8 ({sorted(c + 1 for c in panic)})",
                   lines)
        if self.engine_send_transport(r):
            self.check("A9", any(s.msg.type == "stop" for s in tail), "MIDI Stop sent", lines)
        stop_at = next((k for k, s in enumerate(tail) if s.msg.type in ("stop",) or
                        (s.msg.type == "control_change" and s.msg.control == 123)), None)
        late = stop_at is not None and any(s.msg.type in ("clock", "note_on") for s in tail[stop_at:])
        self.check("A9", not late, "no clock or note after the panic", lines)

    def check_a9b(self, step, r, lines):
        run = step.call_pos[0]
        res = self.res(step)
        self.check("A9b", res.get("mode") == "started" and res.get("playing") == "techno", "techno started", lines)
        ons = {s.msg.channel + 1 for s in self.run_events(run) if s.msg.type == "note_on"}
        self.check("A9b", 8 not in ons, "track 8 is silent again (stop cleared the written melody)", lines)
        roles = {t: (v or {}).get("role") for t, v in (res.get("tracks") or {}).items()}
        self.check("A9b", roles.get("7") == "tuned cymbal" and roles.get("8") == "tuned cymbal",
                   "the kit map survived the stop", lines)
        bad = {t: ro for t, ro in roles.items() if t in ("7", "8") and ro and
               any(w in ro for w in ("chord", "stab", "pad"))}
        self.check("A9b", not bad, "no stab or chords on the cymbals", lines)

    def check_a9c(self, step, r, lines):
        run = step.call_pos[0]
        self.check("A9c", not self.hanging(self.run_events(run)), "no hanging notes", lines)

    # -- optional v0.6 section (--v06) ---------------------------------------------------------
    def check_h1(self, step, r, lines):
        from whiplash import harmony, patterns
        run = step.call_pos[0]
        label, play, prog = self.res(step, 0), self.res(step, 1), self.res(step, 2)
        kit = (label.get("kit") or {}).get("tracks", {})
        roles = {t: (kit.get(t) or {}).get("role") for t in ("7", "8", "9")}
        self.check("H1", roles == {"7": "pad", "8": "cymbal", "9": "fx"}, f"kit roles 7-9 {roles}", lines)
        self.check("H1", play.get("mode") == "started" and play.get("playing") == "deephouse"
                   and play.get("key") == "A minor", f"started {play.get('playing')} in {play.get('key')}", lines)
        start = prog.get("starts_at_bar")
        names = [c.get("name") for c in prog.get("progression") or []]
        self.check("H1", names == ["Am", "F", "C", "G"] and prog.get("bars_per_chord") == V06_BARS_PER_CHORD,
                   f"progression {' '.join(V06_CHORDS)} = {names}, {prog.get('bars_per_chord')} bars each", lines)
        self.check("H1", start == step.call_pos[1] // BAR + 1, f"it starts on the next bar line (bar {start})", lines)
        modes = prog.get("tracks") or {}
        self.check("H1", modes == {"6": "root", "7": "chords"},
                   f"track modes {modes}: bass follows the roots, the pad voices the chords, nothing else", lines)
        if start is None or len(names) != len(V06_CHORDS):
            return
        voiced = [set(c["notes"]) for c in prog["progression"]]
        roots = [harmony.parse_chord(c, harmony.Key(9, "minor")).root for c in V06_CHORDS]
        end = r["H2"].call_pos[1] // BAR  # the last whole bar played is end - 1
        chord = lambda b: ((b - start) // V06_BARS_PER_CHORD) % len(V06_CHORDS)
        bad_pad, bad_bass, changes = [], [], []
        for b in range(start, end):
            pad = [s for s in self.notes_in_bar(run, b, 6)]
            bass = {s.msg.note % 12 for s in self.notes_in_bar(run, b, 5)}
            if not pad or not {s.msg.note for s in pad} <= voiced[chord(b)]:
                bad_pad.append(b)
            if bass and bass != {roots[chord(b)]}:
                bad_bass.append(b)
            if b == start or chord(b) != chord(b - 1):
                changes.append((b, pad[0].clocks - b * BAR if pad else None))
        lines.append("  chord changes (bar, clocks after the bar line of the first pad note): "
                     + ", ".join(f"{b}:{c}" for b, c in changes))
        self.check("H1", not bad_pad, f"every pad note in bars {start}-{end - 1} is a tone of that bar's chord "
                   f"(bad bars: {bad_pad or 'none'})", lines)
        self.check("H1", all(c == 0 for _, c in changes) and len(changes) >= len(V06_CHORDS),
                   f"each of {len(changes)} chord changes lands exactly on the bar line", lines)
        self.check("H1", not bad_bass, f"the bass (track 6) plays each chord's root (bad bars: {bad_bass or 'none'})",
                   lines)
        events = self.run_events(run)
        drums = sorted({(s.msg.channel + 1, s.msg.note) for s in events if s.msg.type == "note_on"
                        and s.msg.channel in (0, 1, 2, 3, 4, 7) and s.msg.note != patterns.DRUM})
        self.check("H1", not drums, f"drums and the tuned cymbal stay on note 60, never transposed ({drums or 'none'})",
                   lines)
        fx = [s for s in events if s.msg.type == "note_on" and s.msg.channel == 8]
        self.check("H1", not fx, f"no notes on the fx track 9 ({len(fx)})", lines)
        if step.probe is not None:
            status, body = step.probe
            h = body.get("harmony") if isinstance(body, dict) else None
            p = (h or {}).get("progression") or {}
            ok = status == 200 and (h or {}).get("key") == "A minor" and [c["name"] for c in p.get("chords", [])] == names
            self.check("H1", ok, f"the visualiser shows the key and the chords (HTTP {status}, key "
                       f"{(h or {}).get('key')}, now {p.get('index')})", lines)

    def check_h2(self, step, r, lines):
        run = step.call_pos[0]
        self.check("H2", self.res(step).get("was_playing") is True, "stopped a running beat", lines)
        self.check("H2", not self.hanging(self.run_events(run)), "no hanging notes", lines)

    # -- optional v0.6.1 section (--v061) -------------------------------------------------------
    def check_v1(self, step, r, lines):
        run = step.call_pos[0]
        play, res = self.res(step, 0), self.res(step, 1)
        self.check("V1", play.get("mode") == "started" and play.get("playing") == "techno", "techno started", lines)
        self.check("V1", isinstance(play.get("routing"), dict), "the play result carries routing (v0.6.1)", lines)
        start, total = res.get("starts_at_bar"), res.get("total_bars")
        plan = res.get("sections") or []
        names = [sec.get("name") for sec in plan]
        lines.append(f"  arrangement {res.get('arrangement')}: {total} bars from bar {start}, {res.get('seconds')} s")
        for sec in plan:
            lines.append(f"    {sec.get('name')} @{sec.get('starts_at_bar')} x{sec.get('bars')}: plays "
                         f"{sec.get('plays_now')}" + (f", fill @{sec['fill_at_bar']}" if "fill_at_bar" in sec else "")
                         + (f", drop {sec['drop_last_bar']} on its last bar" if sec.get("drop_last_bar") else "")
                         + (f", ramps {sec['ramps']}" if sec.get("ramps") else ""))
        self.check("V1", res.get("arrangement") == "short_demo" and start == step.call_pos[1] // BAR + 1,
                   f"short_demo starts on the next bar line (bar {start})", lines)
        self.check("V1", names == V061_SECTIONS and total == 16, f"sections {names}, {total} bars", lines)
        if names != V061_SECTIONS or start is None:
            return
        events = self.run_events(run)
        stray = []
        for sec in plan:
            allowed = {t - 1 for t in sec.get("plays_now") or []}
            first = sec["starts_at_bar"]
            for b in range(first, first + sec["bars"]):
                extra = {s.msg.channel + 1 for s in events if s.msg.type == "note_on" and s.clocks // BAR == b
                         and s.msg.channel not in allowed}
                if extra:
                    stray.append((sec["name"], b, sorted(extra)))
        self.check("V1", not stray, "each section sounds only its own tracks, from its first bar line "
                   f"(stray: {stray or 'none'})", lines)
        entered = []
        for prev, sec in zip(plan, plan[1:]):
            new = set(sec.get("plays_now") or []) - set(prev.get("plays_now") or [])
            for t in sorted(new):
                hits = [s for s in events if s.msg.type == "note_on" and s.msg.channel == t - 1
                        and s.clocks >= sec["starts_at_bar"] * BAR]
                if hits and hits[0].clocks // BAR != sec["starts_at_bar"]:
                    entered.append((sec["name"], t, hits[0].where))
        self.check("V1", not entered, f"tracks coming in start in their section's first bar (late: {entered or 'none'})",
                   lines)
        build = plan[1]
        last = build["starts_at_bar"] + build["bars"] - 1
        drop = build.get("drop_last_bar") or []
        silent = all(not self.notes_in_bar(run, last, t - 1) for t in drop)
        self.check("V1", bool(drop) and silent, f"the kick (track {drop}) sits out the build's last bar (bar {last})",
                   lines)
        end = start + total
        clocks = [s.clocks for s in events if s.msg.type == "clock"]
        stops = [s for s in events if s.msg.type == "stop"]
        self.check("V1", bool(clocks) and max(clocks) + 1 == end * BAR,
                   f"the run ends on the bar line after the outro (bar {end}; clocks sent: "
                   f"{max(clocks) + 1 if clocks else 0} = bar {(max(clocks) + 1) // BAR if clocks else 0})", lines)
        if self.engine_send_transport(r):
            self.check("V1", bool(stops) and stops[-1].clocks == end * BAR, "MIDI Stop at that bar line", lines)
        late = [s for s in events if s.msg.type == "note_on" and s.msg.velocity and s.clocks >= end * BAR]
        self.check("V1", not late, f"no note after the end ({len(late)})", lines)
        self.check("V1", not self.hanging(events), f"no hanging notes ({self.hanging(events) or 'none'})", lines)

    def check_v2(self, step, r, lines):
        cur = ((self.res(step).get("arrangement") or {}).get("current")) or {}
        self.check("V2", cur.get("section") == "build" and cur.get("next") == "drop",
                   f"status: section {cur.get('section')!r}, bars_left {cur.get('bars_left')}, next "
                   f"{cur.get('next')!r}", lines)
        self.check("V2", step.call_pos[0] == r["V1"].call_pos[0] and r["V3"].call_pos[0] == step.call_pos[0] + 1,
                   "the arrangement ended the run by itself (no stop call)", lines)

    KICK9 = 8  # MIDI channel of track 9

    def check_v3(self, step, r, lines):
        run = step.call_pos[0]
        label, play = self.res(step, 0), self.res(step, 1)
        role = ((label.get("kit") or {}).get("tracks", {}).get("9") or {}).get("role")
        self.check("V3", role == "kick", f"track 9 labelled role {role!r}", lines)
        self.check("V3", bool(label.get("channel_note")), "the label result carries a channel_note (track 9 plays on "
                   "channel 9: AUTO / FX CONTROL CH must be elsewhere)", lines)
        self.check("V3", play.get("mode") == "started" and play.get("playing") == "techno", "techno started", lines)
        events = self.run_events(run)
        kick9 = [s for s in events if s.msg.type == "note_on" and s.msg.channel == self.KICK9]
        kick1 = [s for s in events if s.msg.type == "note_on" and s.msg.channel == 0]
        self.check("V3", bool(kick9) and not kick1, f"the kick plays on track 9 ({len(kick9)} hits), none on track 1 "
                   f"({len(kick1)})", lines)

    def check_v4(self, step, r, lines):
        run = step.call_pos[0]
        res = self.res(step)
        fill = res.get("fill_at_bar")
        self.check("V4", fill == step.call_pos[1] // BAR + 1 and 9 in (res.get("tracks") or []),
                   f"fill at bar {fill} on tracks {res.get('tracks')} (includes the kick on 9)", lines)
        if fill is None:
            return
        last_beat = lambda b: [s for s in self.notes_in_bar(run, b, self.KICK9) if s.clocks % BAR >= 3 * BAR // 4]
        self.check("V4", bool(last_beat(fill - 1)) and not last_beat(fill),
                   f"track 9's kick sits out the fill bar's last beat (bar {fill - 1}: {len(last_beat(fill - 1))} "
                   f"hits there, bar {fill}: {len(last_beat(fill))})", lines)
        back = self.notes_in_bar(run, fill + 1, self.KICK9)
        self.check("V4", bool(back) and back[0].clocks == (fill + 1) * BAR, "the kick is back on the one after", lines)

    def check_v5(self, step, r, lines):
        run = step.call_pos[0]
        self.check("V5", self.res(step).get("was_playing") is True, "stopped a running beat", lines)
        self.check("V5", not self.hanging(self.run_events(run)), "no hanging notes", lines)

    def engine_send_transport(self, r):
        return bool(self.res(r["A3"]).get("send_transport"))

    @staticmethod
    def hanging(events):
        sounding = set()
        for s in events:
            if s.msg.type == "note_on" and s.msg.velocity:
                sounding.add((s.msg.channel, s.msg.note))
            elif s.msg.type in ("note_on", "note_off"):
                sounding.discard((s.msg.channel, s.msg.note))
        return sorted((ch + 1, n) for ch, n in sounding)

    @staticmethod
    def bpm_of(events, bar, bars=2):
        """Tempo over `bars` bars from `bar`, in the engine's (musical) time: the median one-bar span over every
        start tick in the window. Per-tick gaps are no good at high --speed, where a coarse sleep (macOS) skews
        their median. Two single clocks aren't either, since either one may be late (a macOS runner's ticks are
        often 7 ms or more late). The engine's absolute schedule keeps the bar length exact."""
        a, b = bar * BAR, (bar + bars) * BAR
        t = {s.clocks: s.music for s in events if s.msg.type == "clock" and a <= s.clocks <= b}
        spans = [t[k + BAR] - t[k] for k in range(a, b - BAR + 1) if k in t and k + BAR in t]
        return 4 * 60.0 / statistics.median(spans) if spans else 0.0

    def check_global(self, lines):
        from whiplash import ccmap
        sent = self.port.sent
        types = collections.Counter(s.msg.type for s in sent)
        lines.append("  messages: " + ", ".join(f"{k} {v}" for k, v in sorted(types.items())))
        bad_types = {k: v for k, v in types.items() if k not in OK_TYPES}
        self.check("global", not bad_types, f"no SysEx, program change or other types ({bad_types or 'none'})", lines)
        blocked = sorted({(s.msg.channel + 1, s.msg.control) for s in sent if s.msg.type == "control_change"
                          and s.msg.control in ccmap.BLOCKED_CCS})
        self.check("global", not blocked, f"no blocked CC {sorted(ccmap.BLOCKED_CCS)} ({blocked or 'none'})", lines)
        slot = sorted({(s.msg.channel + 1, s.msg.value) for s in sent if s.msg.type == "control_change"
                       and s.msg.control == ccmap.PARAMS["sample_slot"].cc})
        want = [(6, 9), (7, 11)] if self.v06 else [(6, 9)]
        self.check("global", slot == want, "CC 19 only as slot 9 on track 6" + (" and slot 11 on track 7 (v0.6)" if
                   self.v06 else "") + f" ({slot})", lines)
        self.check("global", not self.hanging(sent), f"no note left sounding at the end ({self.hanging(sent) or 'none'})",
                   lines)
        self.check("global", self.engine.last_error is None, f"engine last_error {self.engine.last_error}", lines)
        self.check("global", self.port.closed, "the port was closed on shutdown", lines)
        # clock timing per constant-tempo segment
        r = {s.id: s for s in self.steps}
        switch = self.res(r["A7"]).get("switch_at_bar")
        run1 = [s for s in sent if s.run == 1 and s.msg.type == "clock"]
        segments = {"deep house (before the A4 call)": [s for s in run1 if s.clocks < r["A4"].call_pos[1]]}
        if switch:
            segments["deep house, live calls"] = [s for s in run1 if r["A4"].call_pos[1] <= s.clocks < switch * BAR]
            segments["tech house"] = [s for s in run1 if s.clocks >= switch * BAR]
        segments["techno (second run)"] = [s for s in sent if s.run == 2 and s.msg.type == "clock"]
        if self.v06:
            segments["deep house in A minor, progression (v0.6)"] = [s for s in sent if s.run == 3 and s.msg.type == "clock"]
        if self.v061:
            for sid, name in (("V1", "techno short_demo (v0.6.1)"), ("V3", "techno, kick on 9 and a fill (v0.6.1)")):
                run = r[sid].call_pos[0]
                segments[name] = [s for s in sent if s.run == run and s.msg.type == "clock"]
        # a stop sends its run's last clock at once, ahead of the grid: leave each run's last clock out
        last = {}
        for s in sent:
            if s.msg.type == "clock":
                last[s.run] = s
        segments = {name: [s for s in events if s is not last.get(s.run)] for name, events in segments.items()}
        canary = self.canary
        lines.append(f"  clock timing (real-time lateness vs the engine's own grid; ticks late by more than {LATE_MS:g} ms, "
                     "or by more than a 1 ms sleep takes on this machine (p99), form a stall, which counts unless the "
                     f"canary process saw the machine stall then; allowed: 1 + 1 per {STALL_EVERY:g} s + 1 per machine "
                     "stall the canary saw in the segment)")
        lines.append(f"  canary: {canary.describe()}")
        for name, events in segments.items():
            if len(events) < 2 * BAR:
                continue
            t = timing(events, self.speed, canary)
            self.check("global", t["unexcused"] <= t["allowed"],
                       f"{name}: {t['ticks']} ticks, lateness p50 {t['p50']:.2f} / p99 {t['p99']:.2f} / max "
                       f"{t['max']:.2f} ms; {t['over']} tick(s) over {t['limit_ms']:.1f} ms in {t['stalls']} stall(s), "
                       f"{t['unexcused']} not seen by the canary (allowed {t['allowed']}"
                       + (f", {t['contended']} for machine stalls" if t["contended"] else "") + ")", lines)
            for where in t["where"]:
                lines.append(f"    unexcused stall at {where}")

    # -- output -------------------------------------------------------------------------------
    def write_midi(self, path):
        import mido
        sent = self.port.sent
        t0 = sent[0].music if sent else 0.0
        tick = lambda s: max(0, round((s - t0) * SMF_TICKS_PER_SEC))
        conductor = [(0, mido.MetaMessage("track_name", name="Whiplash demo rehearsal (markers)")),
                     (0, mido.MetaMessage("set_tempo", tempo=SMF_TEMPO)),
                     (0, mido.MetaMessage("time_signature", numerator=4, denominator=4))]
        for step in self.steps:
            if step.call_pos[2] < len(sent):
                at = sent[step.call_pos[2]].music
            else:
                at = sent[-1].music if sent else t0
            label = f"{step.id} {step.calls[0][0].removeprefix('whiplash_')}: {step.prompt}"[:120]
            conductor.append((tick(at), mido.MetaMessage("marker", text=label)))
        channels = collections.defaultdict(list)
        for s in sent:
            m = s.msg
            if m.type == "clock":
                if s.clocks % BAR == 0:
                    conductor.append((tick(s.music), mido.MetaMessage("marker", text=f"run {s.run} bar {s.clocks // BAR}")))
            elif m.type in ("start", "stop", "continue"):
                conductor.append((tick(s.music), mido.MetaMessage("marker", text=f"MIDI {m.type.title()}")))
            elif hasattr(m, "channel"):
                channels[m.channel].append((tick(s.music), m))
        mid = mido.MidiFile(type=1, ticks_per_beat=SMF_TPB)
        for name, events in [("conductor", conductor)] + [(f"ch {ch + 1} (track {ch + 1})", channels[ch])
                                                          for ch in sorted(channels)]:
            track = mido.MidiTrack()
            if name != "conductor":
                track.append(mido.MetaMessage("track_name", name=name, time=0))
            now = 0
            for t, m in sorted(events, key=lambda e: e[0]):
                track.append(m.copy(time=t - now))
                now = t
            mid.tracks.append(track)
        mid.save(path)
        return mid

    def write(self):
        self.out.mkdir(parents=True, exist_ok=True)
        report = self.analyse()
        self.write_midi(self.out / "demo.mid")
        (self.out / "report.txt").write_text(report)
        results = [{"step": s.id, "prompt": s.prompt, "calls": [{"tool": n, "args": p, "result": res}
                                                                 for n, p, res in s.results]} for s in self.steps]
        (self.out / "results.json").write_text(json.dumps(results, indent=1, default=str))
        return report


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--speed", type=float, default=1.0, help="clock speed-up, 1 = real time (default), max 16")
    ap.add_argument("--out", help="output directory (default: <tmp>/whiplash-rehearsal)")
    ap.add_argument("-q", "--quiet", action="store_true", help="print only the result and file paths")
    ap.add_argument("--v06", action="store_true", help="also rehearse the optional v0.6 progression beat (off by default)")
    ap.add_argument("--v061", action="store_true",
                    help="also rehearse v0.6.1: a 30 s short_demo arrangement and a fill on a kick on track 9 (off by default)")
    args = ap.parse_args(argv)
    if not 0.25 <= args.speed <= 16:
        ap.error("--speed must be between 0.25 and 16")
    say = (lambda *a: None) if args.quiet else print
    rehearsal = Rehearsal(speed=args.speed, out=args.out, log=say, v06=args.v06, v061=args.v061)
    try:
        rehearsal.run()
    except Exception:
        traceback.print_exc()
        print("REHEARSAL CRASHED: the demo did not run to the end", file=sys.stderr)
        try:
            rehearsal.end = len(rehearsal.port.sent)
            rehearsal.write()
        except Exception:
            pass
        return 2
    report = rehearsal.write()
    if not args.quiet:
        print()
        print(report, end="")
    else:
        print(report.strip().splitlines()[-1 - len(rehearsal.violations)])
    print(f"wrote {rehearsal.out / 'demo.mid'}, {rehearsal.out / 'report.txt'}, {rehearsal.out / 'results.json'}")
    return 1 if rehearsal.violations else 0


if __name__ == "__main__":
    sys.exit(main())
