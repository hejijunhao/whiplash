"""v0.5.2: transpose on tracks 9-16, All Notes Off on every channel that played, amp_hold never slips to NOTE."""
import time
from pathlib import Path

import pytest

import whiplash
from whiplash import ccmap, engine, patterns, schemas
from test_whiplash import call, make_engine, tool_engine  # noqa: F401  (fixture)
from test_live import bar_events, finish, pretend_playing, timeline, wait_bar

P = patterns.PATTERNS
ROOT = Path(whiplash.__path__[0])


@pytest.fixture
def fake():
    eng, port = make_engine()
    yield eng, port
    eng.shutdown()


def panic_channels(messages):
    return sorted(m.channel for m in messages if m.type == "control_change" and m.control == 123)


# ---- 1. transpose on tracks 9-16 -------------------------------------------

def test_transpose_moves_a_written_part_on_a_high_track(fake):
    eng, _ = fake
    pretend_playing(eng, P["techno"])
    eng.write_part(12, rhythm="four_on_floor", notes=["C5", "E5"])
    out = eng.set_transpose(12, octaves=1)
    assert out["transpose"] == 12 and out["pitch"]["low"] == 72 and out["pitch"]["high"] == 76
    assert [e[2] for e in bar_events(eng, 0) if e[1] == 12] == [72, 76, 72, 76]
    assert eng.tracks_summary()["12"]["pitch"]["low"] == 72


def test_transpose_on_a_high_track_reaches_the_wire(fake):
    eng, port = fake
    eng.play(P["techno"], bpm=300)
    wait_bar(eng, 1)
    eng.write_part(10, rhythm="8ths", notes=["C5"])
    at = eng.set_transpose(10, semitones=7)["at_bar"]
    wait_bar(eng, at + 1)
    eng.stop()
    notes = {m.note for bar, _, m in timeline(port) if m.type == "note_on" and m.channel == 9 and bar >= at}
    assert notes == {67}


def test_transpose_on_a_silent_track_is_refused_and_changes_nothing(fake):
    eng, port = fake
    pretend_playing(eng, P["techno"])
    before = len(port.messages)
    for track in (9, 16):
        with pytest.raises(engine.WhiplashError, match="plays nothing.*write_part"):
            eng.set_transpose(track, semitones=12)
    assert eng.status()["transpose"] == {} and len(port.messages) == before
    assert eng.set_transpose(9, semitones=0)["transpose"] == 0  # putting it back is always fine
    eng.write_part(9, rhythm="half_time")
    assert eng.set_transpose(9, semitones=-5)["transpose"] == -5  # once it plays, it works
    eng.write_part(9, reset=True)
    assert eng.status()["transpose"] == {"9": -5}


def test_play_refuses_transpose_on_a_track_that_plays_nothing(fake):
    eng, port = fake
    with pytest.raises(engine.WhiplashError, match=r"\[9\] play nothing"):
        eng.play(P["techno"], bpm=300, transpose={"9": 12, "6": 12})
    assert not eng.playing() and port.messages == []  # validated before anything was sent
    eng.play(P["techno"], bpm=300, transpose={"9": 0})  # 0 is a no-op, not an error
    with pytest.raises(engine.WhiplashError, match="play nothing"):
        eng.play(P["soul"], transpose={"13": 3})  # queued switch: refused before it is queued
    assert eng.status()["queued"] is None
    eng.write_part(13, rhythm="four_on_floor")
    out = eng.play(P["soul"], transpose={"13": 3})  # the written part carries into the switch
    assert out["mode"] == "queued" and eng.status()["queued"]["transpose"] == {"13": 3}


def test_transpose_tool_refuses_a_silent_high_track(tool_engine):
    tool_engine()
    assert call("whiplash_play_pattern", genre="techno", bpm=300)["success"]
    out = call("whiplash_transpose", track=14, semitones=12)
    assert out["success"] is False and "plays nothing" in out["error"]
    call("whiplash_stop")


# ---- 2. All Notes Off on every channel that played -------------------------

def test_panic_covers_a_high_channel_that_played(fake):
    eng, port = fake
    eng.play(P["techno"], bpm=300)
    wait_bar(eng, 1)
    at = eng.write_part(12, rhythm="16ths", notes=["C5"])["at_bar"]
    wait_bar(eng, at + 1)
    mark = len(port.messages)
    eng.stop()
    assert panic_channels(port.messages[mark:]) == [0, 1, 2, 3, 4, 5, 6, 7, 11]
    mark = len(port.messages)
    eng.stop()  # idle panic: channel 12 has played nothing since, so it gets no extra message
    assert panic_channels(port.messages[mark:]) == list(range(8))


def test_panic_skips_high_channels_that_never_played(fake):
    eng, port = fake
    eng.play(P["techno"], bpm=300, bars=1)
    finish(eng)
    assert panic_channels(port.messages) == list(range(8))
    eng.ensure_port()
    eng.set_param(15, 100, param="filter_freq")  # a CC is not a note: no All Notes Off on channel 15
    mark = len(port.messages)
    eng.stop()
    assert panic_channels(port.messages[mark:]) == list(range(8))


def test_note_channel_tracking_is_cheap_on_the_clock_thread(fake):
    eng, _ = fake
    eng.ensure_port()
    mido = __import__("mido")
    eng._note(mido, 13, 60, 100)
    eng._note(mido, 13, 60, 0)
    assert eng._note_channels == {13}
    eng.stop()
    assert eng._note_channels == set()


# ---- 3. amp_hold: 0-126 by clamp and ramp, NOTE only when asked --------------

def test_amp_hold_range_is_0_126():
    spec = ccmap.PARAMS["amp_hold"]
    assert (spec.cc, spec.min, spec.max) == (80, 0, 126) and not spec.discrete
    assert "NOTE" in spec.description and "explicit" in spec.description


def test_set_param_amp_hold_values(fake):
    eng, port = fake
    eng.ensure_port()
    out = eng.set_param(1, 126, param="amp_hold")
    assert out == {"track": 1, "cc": 80, "value": 126, "param": "amp_hold"}
    for explicit in (127, "note", " NOTE ", 127.0):
        out = eng.set_param(1, explicit, param="hold")
        assert out["value"] == 127 and out["hold"] == "NOTE" and "tell the user" in out["warning"]
        assert "clamped" not in out
    raw = eng.set_param(2, 127, cc=80)  # raw cc 80 gets the same label
    assert raw["value"] == 127 and raw["hold"] == "NOTE"
    for bad in (128, 200, -1, "max", "notes"):
        with pytest.raises(engine.WhiplashError):
            eng.set_param(1, bad, param="amp_hold")
    with pytest.raises(engine.WhiplashError):
        eng.set_param(1, "note", param="tune")  # 'note' means something only for amp_hold
    sent = [(m.channel, m.control, m.value) for m in port.messages if m.type == "control_change"]
    assert sent == [(0, 80, 126)] + [(0, 80, 127)] * 4 + [(1, 80, 127)]


@pytest.mark.parametrize("target", [{"param": "amp_hold"}, {"cc": 80}])
def test_ramps_on_amp_hold_never_end_on_note(fake, target):
    eng, port = fake
    eng.play(P["techno"], bpm=300)
    out = eng.ramp(3, 127, start=100, beats=1, **target)
    assert out["to"] == 126 and out["clamped"] is True and "126" in out["hold_note"]
    wait_bar(eng, 1)
    eng.stop()
    values = [m.value for m in port.messages if m.type == "control_change" and m.control == 80]
    assert values[0] == 100 and values[-1] == 126 and 127 not in values


def test_ramp_from_note_starts_below_it(fake):
    eng, port = fake
    eng.play(P["techno"], bpm=300)
    out = eng.ramp(3, 40, param="amp_hold", start=127, beats=1)
    assert out["from"] == 126 and out["clamped"] is True and "hold_note" in out
    plain = eng.ramp(4, 40, param="amp_hold", start=100, beats=1)
    assert "hold_note" not in plain and "clamped" not in plain
    eng.stop()


def test_ramp_down_from_a_sent_note_is_allowed(fake):
    eng, port = fake
    eng.play(P["techno"], bpm=300)
    eng.set_param(5, "note", param="amp_hold")
    out = eng.ramp(5, 20, param="amp_hold", beats=1)  # starts from the 127 Whiplash sent, goes down
    assert out["from"] == 127 and out["to"] == 20 and "hold_note" not in out
    eng.stop()


def test_write_part_envelope_note_still_sends_one_127(fake):
    eng, port = fake
    pretend_playing(eng, P["techno"])
    out = eng.write_part(6, rhythm="8ths", envelope="note")
    assert out["envelope"]["amp_hold"] == 127 and out["envelope"]["hold"] == "NOTE"
    assert [(m.control, m.value) for m in port.messages if m.type == "control_change"] == [(80, 127)]


def test_amp_hold_docs_match():
    skill = (ROOT / "skills" / "digitakt" / "SKILL.md").read_text()
    readme = (ROOT / "README.md").read_text()
    reference = (ROOT / "docs" / "digitakt-ii" / "reference.md").read_text()
    assert 'value: "note"' in skill and "set `amp_hold` 127 yourself" not in skill
    assert "set `amp_hold` to 127" not in skill
    assert "0-126" in readme and '"note"' in readme
    assert "| `amp_hold` | amp | 80 | | 0-126 | |" in reference
    params = schemas.SCHEMAS["whiplash_set_param"]["parameters"]["properties"]
    assert "string" in params["value"]["type"] and "'note'" in params["value"]["description"]


# ---- 4. stale text and version -----------------------------------------------

def test_stop_text_names_the_high_channels():
    readme = (ROOT / "README.md").read_text()
    assert "All Notes Off on channels 1-8 plus any channel 9-16" in readme
    assert "9-16" in schemas.SCHEMAS["whiplash_stop"]["description"]
    assert "(the usual default)" not in readme


def test_readme_test_count_is_current():
    import re
    import subprocess
    import sys
    count = int(re.search(r"^(\d+) tests, covering:", (ROOT / "README.md").read_text(), re.M).group(1))
    collected = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", str(ROOT / "tests")],
                               capture_output=True, text=True, cwd=ROOT).stdout
    total = int(re.search(r"(\d+) tests? collected", collected).group(1))
    assert count == total
