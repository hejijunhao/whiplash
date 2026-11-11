"""scripts/rehearse_demo.py: the hackathon demo, rehearsed against a recording port at 4x clock."""
import importlib.util
from pathlib import Path

import mido
import pytest

import whiplash
from whiplash import engine, tools, view

SCRIPT = Path(whiplash.__path__[0]) / "scripts" / "rehearse_demo.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("rehearse_demo", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


rehearse = _load_script()


def _rehearse(out, **kwargs):
    """Run the rehearsal at 4x. No retry: its clock check excuses machine stalls the canary process saw and allows
    one stall plus one per 10 s of real time, so CI-runner noise passes and a repeating engine stall fails
    (test_the_timing_rule_* below; docs/testing/clock-jitter.md)."""
    saved = (tools.ENGINE, engine.time, view.time, engine.list_ports)
    r = rehearse.Rehearsal(speed=4, out=out, log=lambda *a: None, **kwargs)
    r.run()
    report = r.write()
    assert (tools.ENGINE, engine.time, view.time, engine.list_ports) == saved  # nothing left patched
    return r, report


@pytest.fixture(scope="module")
def rehearsal(tmp_path_factory):
    return _rehearse(tmp_path_factory.mktemp("rehearsal"))


def test_the_demo_rehearses_clean(rehearsal):
    r, report = rehearsal
    assert r.violations == [], report
    assert report.rstrip().endswith("RESULT: PASS"), report
    for step in ("A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9"):
        assert f"\n{step}  " in report
    assert "[FAIL]" not in report


def test_the_midi_file_holds_what_was_sent(rehearsal):
    r, _ = rehearsal
    mid = mido.MidiFile(r.out / "demo.mid")
    assert mid.type == 1
    names = [t.name for t in mid.tracks]
    assert names[0].startswith("Whiplash demo rehearsal") and "ch 6 (track 6)" in names and "ch 8 (track 8)" in names
    sent = [s.msg for s in r.port.sent if s.msg.type in ("note_on", "note_off", "control_change")]
    in_file = [m for t in mid.tracks for m in t if not m.is_meta]
    assert len(in_file) == len(sent)
    assert all(m.type in ("note_on", "note_off", "control_change") for m in in_file)  # no clock bytes, no SysEx
    assert any(m.type == "control_change" and m.control == 19 and m.value == 9 and m.channel == 5 for m in in_file)
    markers = [m.text for m in mid.tracks[0] if m.type == "marker"]
    assert "MIDI Start" in markers and "MIDI Stop" in markers and "run 1 bar 9" in markers
    assert any(t.startswith("A7 play_pattern") for t in markers)
    # event times are the engine's musical time: the file is as long as the demo at 1x, not 4x
    clocks = [s for s in r.port.sent if s.msg.type == "clock"]
    musical = clocks[-1].music - r.port.sent[0].music
    assert abs(mid.length - musical) < 0.6 and mid.length > 20


def test_the_checks_catch_sysex_blocked_ccs_and_hanging_notes(rehearsal):
    r, _ = rehearsal
    sent = list(r.port.sent)
    try:
        last = sent[-1]
        for msg in (mido.Message("sysex", data=[0x00, 0x20, 0x3C]), mido.Message("program_change", program=3),
                    mido.Message("control_change", channel=0, control=24, value=1),
                    mido.Message("note_on", channel=2, note=60, velocity=100)):
            r.port.sent.append(rehearse.Sent(last.real, last.music, last.run, last.clocks, msg))
        report = r.analyse()
        text = " ".join(v for _, v in r.violations)
        assert "SysEx" in text and "program_change" in text and "(1, 24)" in text and "(3, 60)" in text
        assert "RESULT: FAIL" in report
    finally:
        r.port.sent[:] = sent
        r.analyse()


def test_main_runs_the_cli_and_exits_1_on_a_violation(tmp_path, monkeypatch):
    run = rehearse.Rehearsal.run

    def run_then_misbehave(self):
        run(self)
        last = self.port.sent[-1]
        self.port.sent.append(rehearse.Sent(last.real, last.music, last.run, last.clocks,
                                            mido.Message("control_change", channel=0, control=0, value=1)))
    monkeypatch.setattr(rehearse.Rehearsal, "run", run_then_misbehave)
    assert rehearse.main(["--speed", "16", "--out", str(tmp_path), "-q"]) == 1
    assert "no blocked CC" in (tmp_path / "report.txt").read_text()
    assert (tmp_path / "demo.mid").exists() and (tmp_path / "results.json").exists()
    with pytest.raises(SystemExit):
        rehearse.main(["--speed", "100"])


# ---- optional v0.6 section (--v06): off by default, so the default run stays the demo ----------------

def test_the_v06_section_is_off_by_default(rehearsal):
    r, report = rehearsal
    assert r.v06 is False and r.v061 is False and [s.id for s in r.steps][-1] == "A9c"
    assert "\nH1  " not in report and "progression (v0.6)" not in report
    assert "--v06" in rehearse.__doc__


@pytest.fixture(scope="module")
def rehearsal_v06(tmp_path_factory):
    return _rehearse(tmp_path_factory.mktemp("rehearsal_v06"), v06=True)


def test_the_v06_progression_rehearses_clean(rehearsal_v06):
    r, report = rehearsal_v06
    assert r.violations == [], report
    assert report.rstrip().endswith("RESULT: PASS"), report
    for line in ("slot 11 on track 7", "it starts on the next bar line", "lands exactly on the bar line",
                 "plays each chord's root", "never transposed", "no notes on the fx track 9",
                 "the visualiser shows the key and the chords", "progression (v0.6)"):
        assert line in report, line
    changes = next(l for l in report.splitlines() if l.strip().startswith("chord changes"))
    assert "1:0, 3:0, 5:0, 7:0, 9:0" in changes  # i, VI, III, VII, and the wrap back to i, each on the one


def test_the_v06_checks_catch_a_chord_on_the_cymbal_and_a_late_change(rehearsal_v06):
    r, _ = rehearsal_v06
    sent = list(r.port.sent)
    try:
        h1 = next(s for s in r.steps if s.id == "H1")
        start = h1.results[2][2]["starts_at_bar"]
        last = next(s for s in reversed(sent) if s.run == 3 and s.msg.type == "clock")
        for note_on in (mido.Message("note_on", channel=7, note=64, velocity=90),  # a chord tone on the cymbal
                        mido.Message("note_on", channel=8, note=60, velocity=90)):  # anything on the fx track
            r.port.sent.append(rehearse.Sent(last.real, last.music, 3, last.clocks, note_on))
        # a pad note of the next chord (III, bar 5) sounding one bar early, in bar 4
        early = rehearse.Sent(last.real, last.music, 3, (start + 3) * rehearse.BAR + 5,
                              mido.Message("note_on", channel=6, note=79, velocity=90))
        r.port.sent.append(early)
        r.analyse()
        text = " ".join(v for w, v in r.violations if w == "H1")
        assert "note 60" in text and "fx track 9" in text and "tone of that bar's chord" in text
    finally:
        r.port.sent[:] = sent
        r.analyse()


def test_main_takes_the_v06_flag(tmp_path, monkeypatch):
    seen = {}

    def fake_run(self):
        seen["v06"] = self.v06
        raise RuntimeError("stop here")
    monkeypatch.setattr(rehearse.Rehearsal, "run", fake_run)
    assert rehearse.main(["--v06", "--speed", "16", "--out", str(tmp_path), "-q"]) == 2
    assert seen == {"v06": True}


# ---- clock timing: lateness against the engine's grid, stalls, the canary --------------------------------

def _clocks(late_ms, period=0.02, speed=1):
    """Synthetic clocks: tick k due at k * period (musical = real at speed 1), sent late_ms[k] late."""
    out = []
    for k, ms in enumerate(late_ms):
        t = k * period + ms / 1000
        out.append(rehearse.Sent(t, t * speed, 1, k, mido.Message("clock")))
    return out


class _Canary:
    def __init__(self, stalls=()):
        self.stalls = list(stalls)

    covers = rehearse.Canary.covers
    count = rehearse.Canary.count


def test_lateness_is_measured_against_the_absolute_grid():
    late = [0.05] * 500
    late[200], late[201] = 12.0, 0.5  # one tick 12 ms late: its gap shows twice, its lateness once
    got = rehearse.lateness(_clocks(late), 1)
    assert max(got) == pytest.approx(0.01195, abs=1e-5) and got.index(max(got)) == 200
    assert sorted(got)[250] == pytest.approx(0.0, abs=1e-6)  # anchored on the least-late tick


def test_the_timing_rule_allows_one_burst_and_fails_a_repeating_stall():
    quiet = [0.05] * 960  # about 19 s at 1x: allowed 1 + 1
    burst = list(quiet)
    burst[300:304] = [60, 40, 20, 5]  # one runner stall: four ticks in one stall
    t = rehearse.timing(_clocks(burst), 1, _Canary())
    assert t["stalls"] == 1 and t["unexcused"] == 1 and t["unexcused"] <= t["allowed"] == 2
    regression = list(quiet)
    for k in range(0, 960, 96):  # 6 ms of work at every bar line: an engine regression
        regression[k + 1] = 6.0
    t = rehearse.timing(_clocks(regression), 1, _Canary())
    assert t["stalls"] == 10 and t["unexcused"] > t["allowed"] and "bar 0 tick 1" in t["where"][0]


def test_the_timing_rule_excuses_only_stalls_the_canary_saw():
    late = [0.05] * 960
    for k in (100, 400, 700):
        late[k] = 30.0
    clocks = _clocks(late)
    saw = [(clocks[k].real - 0.025, clocks[k].real - 0.001) for k in (100, 400)]  # the machine froze for two of them
    t = rehearse.timing(clocks, 1, _Canary(saw))
    assert t["stalls"] == 3 and t["unexcused"] == 1 and "bar 7 tick 28" in t["where"][0]
    # a contended machine: each stall the canary saw in the segment allows one more it didn't see
    assert t["contended"] == 2 and t["allowed"] == 1 + 1 + 2
    quiet = rehearse.timing(clocks, 1, _Canary())
    assert quiet["contended"] == 0 and quiet["allowed"] == 2


def test_the_canary_records_a_machine_stall():
    canary = rehearse.Canary(limit=0.002).start()
    assert canary.proc is not None and abs(canary.offset) < 0.05  # a system-wide clock in both processes
    canary.stop()
    assert canary.loops > 0 and isinstance(canary.stalls, list)


# ---- optional v0.6.1 section (--v061): off by default ---------------------------------------------------

@pytest.fixture(scope="module")
def rehearsal_v061(tmp_path_factory):
    return _rehearse(tmp_path_factory.mktemp("rehearsal_v061"), v061=True)


def test_the_v061_section_rehearses_clean(rehearsal_v061):
    r, report = rehearsal_v061
    assert r.violations == [], report
    assert report.rstrip().endswith("RESULT: PASS"), report
    assert [s.id for s in r.steps][-5:] == ["V1", "V2", "V3", "V4", "V5"]
    for line in ("short_demo starts on the next bar line (bar 1)", "sections ['intro', 'build', 'drop', 'outro'], 16 bars",
                 "each section sounds only its own tracks", "sits out the build's last bar",
                 "the run ends on the bar line after the outro (bar 17", "MIDI Stop at that bar line",
                 "status: section 'build'", "the arrangement ended the run by itself", "the kick plays on track 9",
                 "track 9's kick sits out the fill bar's last beat", "techno short_demo (v0.6.1)"):
        assert line in report, line


def test_the_v061_checks_catch_a_muted_track_and_a_note_after_the_end(rehearsal_v061):
    r, _ = rehearsal_v061
    sent = list(r.port.sent)
    try:
        run = next(s for s in r.steps if s.id == "V1").call_pos[0]
        last = next(s for s in reversed(sent) if s.run == run and s.msg.type == "clock")
        # the bass (track 6) is not in the intro; and a note after the outro's last bar line
        r.port.sent.append(rehearse.Sent(last.real, last.music, run, 2 * rehearse.BAR + 10,
                                         mido.Message("note_on", channel=5, note=53, velocity=90)))
        r.port.sent.append(rehearse.Sent(last.real, last.music, run, 17 * rehearse.BAR + 2,
                                         mido.Message("note_on", channel=0, note=60, velocity=90)))
        r.port.sent.append(rehearse.Sent(last.real, last.music, run, 17 * rehearse.BAR + 3,
                                         mido.Message("note_off", channel=0, note=60, velocity=0)))
        r.analyse()
        text = " ".join(v for w, v in r.violations if w == "V1")
        assert "('intro', 2, [6])" in text and "no note after the end (1)" in text
    finally:
        r.port.sent[:] = sent
        r.analyse()


def test_main_takes_the_v061_flag(tmp_path, monkeypatch):
    seen = {}

    def fake_run(self):
        seen["flags"] = (self.v06, self.v061)
        raise RuntimeError("stop here")
    monkeypatch.setattr(rehearse.Rehearsal, "run", fake_run)
    assert rehearse.main(["--v061", "--speed", "16", "--out", str(tmp_path), "-q"]) == 2
    assert seen == {"flags": (False, True)}
    assert "--v061" in rehearse.__doc__


# ---- scripts/clock_jitter.py: the measurement behind docs/testing/clock-jitter.md ------------------------

def _load_jitter():
    spec = importlib.util.spec_from_file_location("clock_jitter", SCRIPT.parent / "clock_jitter.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_clock_jitter_measures_and_sees_a_busy_python_thread():
    jitter = _load_jitter()
    saved = (tools.ENGINE, engine.time, view.time, engine.list_ports)
    quiet = jitter.run_once(speed=4, seconds=12, bpm=126)
    hog = jitter.run_once(speed=1, seconds=8, bpm=126, gil_hog=True)
    assert (tools.ENGINE, engine.time, view.time, engine.list_ports) == saved
    assert quiet["ticks"] > 300 and quiet["period_ms"] == pytest.approx(60000 / 126 / 24 / 4, rel=0.05)
    # a CPU-bound thread in the same process holds the GIL for its switch interval (5 ms) at a time: every wake-up
    # of the clock thread waits for it, and the canary (another process) can't see it, so it is never excused
    assert hog["late_p50"] > 1.0 and hog["unexcused"] > hog["allowed"], hog
