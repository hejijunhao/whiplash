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


@pytest.fixture(scope="module")
def rehearsal(tmp_path_factory):
    saved = (tools.ENGINE, engine.time, view.time, engine.list_ports)
    r = rehearse.Rehearsal(speed=4, out=tmp_path_factory.mktemp("rehearsal"), log=lambda *a: None)
    r.run()
    report = r.write()
    assert (tools.ENGINE, engine.time, view.time, engine.list_ports) == saved  # nothing left patched
    return r, report


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
    assert r.v06 is False and [s.id for s in r.steps][-1] == "A9c"
    assert "\nH1  " not in report and "progression (v0.6)" not in report
    assert "--v06" in rehearse.__doc__


@pytest.fixture(scope="module")
def rehearsal_v06(tmp_path_factory):
    saved = (tools.ENGINE, engine.time, view.time, engine.list_ports)
    r = rehearse.Rehearsal(speed=4, out=tmp_path_factory.mktemp("rehearsal_v06"), log=lambda *a: None, v06=True)
    r.run()
    report = r.write()
    assert (tools.ENGINE, engine.time, view.time, engine.list_ports) == saved
    return r, report


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
