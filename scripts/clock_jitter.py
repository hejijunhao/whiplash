#!/usr/bin/env python3
"""Measure Whiplash's MIDI clock timing on this machine: no Digitakt, no rtmidi, nothing is sent.

    uv run python scripts/clock_jitter.py                      # 1x, 126 BPM, 30 s, idle
    uv run python scripts/clock_jitter.py --runs 5 --load 8    # five runs, 8 busy processes alongside
    uv run python scripts/clock_jitter.py --calls --gil-hog    # tool calls and a busy Python thread in-process

It plays a pattern through the real engine into a recording port (the rehearsal's, scripts/rehearse_demo.py)
and reports, per run, in real milliseconds:
- lateness: how long after its scheduled time each MIDI clock went out. The engine schedules ticks on an
  absolute grid (next_tick += tick_len), so lateness never accumulates; this is the number that matters to
  the receiving unit. The grid is anchored on the least-late tick, so this is a lower bound (>= 0).
- gap p95: the p95 deviation of tick-to-tick gaps from their median, the statistic tests/test_v051.py
  bounds (and the rehearsal did before). A tick d ms late shows up twice in it (+d, then -d).
- over / stalls / unexcused / allowed: ticks later than the rehearsal's LATE_MS, grouped into stalls, the stalls
  no machine stall explains (a canary process sleeping 1 ms at a time saw none then), and how many the
  rehearsal would allow over this run (scripts/rehearse_demo.py timing and Canary).

Conditions you can add, alone or together:
--speed S       run the engine's clock S times faster (the rehearsal's ScaledTime). Lateness is still real time.
--load N        N processes spinning on every core, as a busy laptop would.
--gil-hog       a pure-Python CPU-bound thread in the same process, as the Hermes gateway hosting the plugin
                can be (Python threads share one GIL: a waking sequencer thread waits for it).
--calls         real tool calls (status, set_param, density, label_tracks, write_part, queued same-tempo
                switch) every --call-every seconds, as Hermes makes them, but far more often.
--switch-interval S   sys.setswitchinterval(S) for the run (the interpreter's default is 0.005 s).
--gc-heap N     N extra long-lived container objects in the process and a full gc.collect() every --gc-every
                seconds from another thread: a large host process (the gateway) doing a full collection, which
                holds the GIL for its whole duration.

--json prints one JSON object per run. docs/testing/clock-jitter.md has the method and results.
This measures the computer, not the unit: the unit's response to clock jitter is a hardware check.
"""
import argparse
import importlib.util
import json
import statistics
import subprocess
import sys
import threading
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _rehearse_module():
    spec = importlib.util.spec_from_file_location("rehearse_demo", HERE / "rehearse_demo.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


R = _rehearse_module()
BAR = R.BAR


def _spin(stop):
    while not stop.is_set():
        for _ in range(100_000):
            pass


def pct(values, p):
    """The p-th percentile (nearest rank) of a non-empty list."""
    s = sorted(values)
    return s[min(len(s) - 1, int(len(s) * p / 100))]


def stats(clocks, speed, canary):
    """Lateness (vs the engine's absolute tick grid, R.lateness) and gap deviation, both in real ms, for one
    constant-tempo run, plus the rehearsal's verdict counts (R.timing: ticks over R.LATE_MS, excused or not)."""
    late = [x * 1000 for x in R.lateness(clocks, speed)]
    clock_real = [c.real for c in clocks]
    gaps = [b - a for a, b in zip(clock_real, clock_real[1:])]
    nominal = statistics.median(gaps)
    dev = [abs(g - nominal) * 1000 for g in gaps]
    period = statistics.median(gaps) * 1000
    verdict = R.timing(clocks, speed, canary)
    return {
        "ticks": len(late), "period_ms": round(period, 3),
        "late_p50": round(pct(late, 50), 3), "late_p95": round(pct(late, 95), 3),
        "late_p99": round(pct(late, 99), 3), "late_max": round(max(late), 3),
        "late_over_1ms": sum(x > 1 for x in late), "late_over_2ms": sum(x > 2 for x in late),
        "late_over_5ms": sum(x > 5 for x in late),
        "gap_p95": round(pct(dev, 95), 3), "gap_max": round(max(dev), 3),
        # the rehearsal's statistic as the share of one tick: what a fixed-ms bound misses at high --speed
        "gap_p95_of_period": round(pct(dev, 95) / period, 3),
        f"over_{R.LATE_MS:g}ms": verdict["over"], "stalls": verdict["stalls"], "unexcused": verdict["unexcused"],
        "allowed": verdict["allowed"],
        "canary_stalls": len(canary.stalls),
        "canary_max": round(max((b - a for a, b in canary.stalls), default=0) * 1000, 3),
    }


CALLS = [
    ("whiplash_status", {}),
    ("whiplash_set_param", {"track": 6, "param": "filter_freq", "value": 64}),
    ("whiplash_mutate", {"action": "density", "tracks": [4], "amount": 0.7}),
    ("whiplash_label_tracks", {"tracks": {"7": "tuned cymbal"}}),
    ("whiplash_write_part", {"track": 8, "rhythm": "8ths", "key": "A", "scale": "minor", "notes": "1 3 5 8"}),
    ("whiplash_play_pattern", {"genre": "techhouse", "bpm": None}),  # bpm filled in: a same-tempo queued switch
    ("whiplash_mutate", {"action": "reset"}),
]


def run_once(speed=1.0, seconds=30.0, bpm=126, genre="techhouse", load=0, gil_hog=False, calls=False,
             call_every=0.25, switch_interval=None, gc_heap=0, gc_every=2.0):
    """One run. Returns the stats dict. The engine and modules are patched as the rehearsal does, and restored."""
    R.load_whiplash()
    import mido  # noqa: F401  (imported before any load: a first import under --gil-hog stalls the start, not the clock)
    from whiplash import engine, tools, view
    clock = R.ScaledTime(speed)
    port = R.RecordingPort(clock)
    saved = (tools.ENGINE, engine.time, view.time, engine.list_ports, sys.getswitchinterval())
    eng = engine.Engine(opener=lambda name: (port, R.DEVICE, False), lister=lambda: [R.DEVICE])
    tools.ENGINE = eng
    engine.time = view.time = clock
    engine.list_ports = lambda: {"outputs": [R.DEVICE], "inputs": [R.DEVICE]}
    stop = threading.Event()
    procs, threads, errors = [], [], []
    canary = R.Canary()
    if switch_interval:
        sys.setswitchinterval(switch_interval)
    try:
        for _ in range(load):  # plain subprocesses: no multiprocessing pickling of this file-loaded module
            procs.append(subprocess.Popen([sys.executable, "-I", "-c", "while True: pass"]))
        if gil_hog:
            threads.append(threading.Thread(target=_spin, args=(stop,), daemon=True))
        heap = [{"k": [i, str(i)]} for i in range(gc_heap // 2)]  # dict + list: two tracked objects each
        if gc_heap:
            import gc

            def collector():
                while not stop.wait(gc_every):
                    gc.collect()
            threads.append(threading.Thread(target=collector, daemon=True))
        if calls:
            def caller():
                i = 0
                while not stop.is_set():
                    name, params = CALLS[i % len(CALLS)]
                    params = {**params, "bpm": bpm} if name == "whiplash_play_pattern" else dict(params)
                    out = json.loads(tools.HANDLERS[name](params))
                    if not out.get("success"):
                        errors.append((name, out.get("error")))
                    i += 1
                    stop.wait(call_every)
            threads.append(threading.Thread(target=caller, daemon=True))
        out = json.loads(tools.HANDLERS["whiplash_play_pattern"]({"genre": genre, "bpm": bpm}))
        if not out.get("success"):
            raise RuntimeError(out.get("error"))
        port.new_run()
        canary.start()
        for t in threads:
            t.start()
        deadline = time.perf_counter() + seconds / speed
        while time.perf_counter() < deadline and eng.playing():
            time.sleep(0.05)
        stop.set()
        for t in threads:
            t.join(5)
        eng.stop()
    finally:
        stop.set()
        canary.stop()
        for p in procs:
            p.kill()
            p.wait(5)
        try:
            eng.shutdown()
        finally:
            tools.ENGINE, engine.time, view.time, engine.list_ports, si = saved
            sys.setswitchinterval(si)
    del heap
    if errors:
        raise RuntimeError(f"tool calls failed: {errors[:3]}")
    # skip the first bar (start-up) and the last tick: on stop the engine sends its final clock at once
    ticks = [s for s in port.sent if s.msg.type == "clock"][BAR:-1]
    if len(ticks) < 2 * BAR:
        raise RuntimeError(f"only {len(ticks)} clocks recorded")
    res = stats(ticks, speed, canary)
    res.update(speed=speed, bpm=bpm, load=load, gil_hog=gil_hog, calls=calls, gc_heap=gc_heap,
               switch_interval=switch_interval
               or saved[4], platform=sys.platform, python=sys.version.split()[0])
    return res


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--seconds", type=float, default=30.0, help="musical seconds per run (default 30)")
    ap.add_argument("--bpm", type=float, default=126)
    ap.add_argument("--genre", default="techhouse")
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--load", type=int, default=0, help="busy processes alongside (default 0)")
    ap.add_argument("--gil-hog", action="store_true")
    ap.add_argument("--calls", action="store_true")
    ap.add_argument("--call-every", type=float, default=0.25, help="seconds between tool calls (default 0.25)")
    ap.add_argument("--switch-interval", type=float, default=None)
    ap.add_argument("--gc-heap", type=int, default=0, help="extra long-lived objects; with a full collection every "
                    "--gc-every seconds (default 0: off)")
    ap.add_argument("--gc-every", type=float, default=2.0)
    ap.add_argument("--json", action="store_true", help="one JSON object per run")
    args = ap.parse_args(argv)
    if not 0.25 <= args.speed <= 16:
        ap.error("--speed must be between 0.25 and 16")
    cols = ("late_p50", "late_p95", "late_p99", "late_max", "late_over_2ms", f"over_{R.LATE_MS:g}ms", "stalls", "unexcused",
            "allowed", "canary_stalls")
    if not args.json:
        print(f"speed {args.speed}x, {args.bpm} BPM, {args.seconds} s, load {args.load}, gil_hog {args.gil_hog}, "
              f"calls {args.calls}, gc_heap {args.gc_heap}, switch_interval "
              f"{args.switch_interval or sys.getswitchinterval()}")
        print("run  ticks  " + "  ".join(f"{c:>13}" for c in cols) + "   (ms; period "
              f"{60000 / args.bpm / 24 / args.speed:.2f} ms)")
    for i in range(args.runs):
        res = run_once(args.speed, args.seconds, args.bpm, args.genre, args.load, args.gil_hog, args.calls,
                       args.call_every, args.switch_interval, args.gc_heap, args.gc_every)
        if args.json:
            print(json.dumps(res), flush=True)
        else:
            print(f"{i + 1:>3}  {res['ticks']:>5}  " + "  ".join(f"{res[c]:>13}" for c in cols), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
