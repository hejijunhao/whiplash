#!/usr/bin/env python3
"""Rehearse the hackathon demo offline: no Digitakt, no rtmidi, nothing leaves the laptop.

    uv run python scripts/rehearse_demo.py               # real time, about 30 s
    uv run python scripts/rehearse_demo.py --speed 4     # 4x clock, about 8 s

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
  SysEx or program change, no blocked CC, no hanging notes, clock jitter within the bound the
  test suite uses (tests/test_v051.py: p95 <= max(2 x baseline, baseline + 3 ms)).
- results.json: every tool result, as Hermes would see it.

Exit status: 0 if every check passed, 1 on any violation, 2 if the rehearsal itself crashed.
--speed scales the engine's clock (its perf_counter and sleep), not the tool calls: the beat,
bar quantize and ramps behave as at 1x. Jitter is measured in real time either way.

This is a rehearsal against a recording port. It proves nothing about how the unit sounds or
responds: that still needs docs/testing/hardware-checklist.md Part A on a real Digitakt II.
"""
import argparse
import collections
import importlib.util
import json
import socket
import statistics
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
JITTER_SLACK = 0.003  # seconds, as in tests/test_v051.py
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


class Rehearsal:
    def __init__(self, speed=1.0, out=None, log=print):
        self.speed = speed
        self.out = Path(out) if out else Path(tempfile.gettempdir()) / "whiplash-rehearsal"
        self.log = log
        self.whiplash = load_whiplash()
        from whiplash import engine, tools, view
        self.engine_mod, self.tools, self.view = engine, tools, view
        self.clock = ScaledTime(speed)
        self.port = RecordingPort(self.clock)
        self.steps = demo_steps()
        self.violations = []  # (where, text)
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

    def _free_port(self):
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            return s.getsockname()[1]

    def run(self):
        saved = self._patch()
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
                    self._wait_for(1, 0)
                    self._probe_view(step)
            time.sleep(0.05)
        finally:
            self._unpatch(saved)
        self.end = len(self.port.sent)

    def _probe_view(self, step):
        url = next((r.get("url") for _, _, r in self.steps[0].results if r.get("url")), None)
        if not url:
            return
        try:
            with urllib.request.urlopen(url.rstrip("/") + "/state", timeout=5) as resp:
                self.view_probe = (resp.status, json.loads(resp.read()))
        except Exception as exc:
            self.view_probe = (None, f"{type(exc).__name__}: {exc}")

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
                 "Not a hardware test: run docs/testing/hardware-checklist.md Part A on the unit.", ""]
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
        if self.view_probe is not None:
            status, body = self.view_probe
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
        """Tempo over whole bars of clock (first clock of `bar` to the first clock `bars` later), in the
        engine's (musical) time. Per-tick gaps are no good at high --speed: a coarse sleep (macOS) skews
        their median, while the engine's absolute schedule keeps the bar length exact."""
        a, b = bar * BAR, (bar + bars) * BAR
        t = {s.clocks: s.music for s in events if s.msg.type == "clock" and s.clocks in (a, b)}
        return 4 * 60.0 * bars / (t[b] - t[a]) if len(t) == 2 else 0.0

    @staticmethod
    def jitter(times):
        gaps = [b - a for a, b in zip(times, times[1:])]
        nominal = statistics.median(gaps)
        return sorted(abs(g - nominal) for g in gaps)[int(len(gaps) * 0.95)]

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
        self.check("global", slot == [(6, 9)], f"CC 19 only as slot 9 on track 6 ({slot})", lines)
        self.check("global", not self.hanging(sent), f"no note left sounding at the end ({self.hanging(sent) or 'none'})",
                   lines)
        self.check("global", self.engine.last_error is None, f"engine last_error {self.engine.last_error}", lines)
        self.check("global", self.port.closed, "the port was closed on shutdown", lines)
        # jitter: real-time clock gaps per constant-tempo segment, against the first two bars of the demo
        r = {s.id: s for s in self.steps}
        switch = self.res(r["A7"]).get("switch_at_bar")
        run1 = [s for s in sent if s.run == 1 and s.msg.type == "clock"]
        segments = {"deep house (before the A4 call)": [s for s in run1 if s.clocks < r["A4"].call_pos[1]]}
        if switch:
            segments["deep house, live calls"] = [s for s in run1 if r["A4"].call_pos[1] <= s.clocks < switch * BAR]
            segments["tech house"] = [s for s in run1 if s.clocks >= switch * BAR]
        segments["techno (second run)"] = [s for s in sent if s.run == 2 and s.msg.type == "clock"]
        base_events = segments["deep house (before the A4 call)"]
        if len(base_events) < 50:
            self.fail("global", "too few clocks for a jitter baseline")
            return
        base = self.jitter([s.real for s in base_events])
        bound = max(base * 2, base + JITTER_SLACK)
        lines.append(f"  clock jitter (p95 deviation from the tick period, real time): baseline {base * 1000:.2f} ms,"
                     f" bound {bound * 1000:.2f} ms")
        for name, events in segments.items():
            if len(events) < 10:
                continue
            j = self.jitter([s.real for s in events])
            self.check("global", j <= bound, f"{name}: {j * 1000:.2f} ms over {len(events)} ticks", lines)

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
    args = ap.parse_args(argv)
    if not 0.25 <= args.speed <= 16:
        ap.error("--speed must be between 0.25 and 16")
    say = (lambda *a: None) if args.quiet else print
    rehearsal = Rehearsal(speed=args.speed, out=args.out, log=say)
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
