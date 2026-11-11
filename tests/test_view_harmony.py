"""Visualiser, v0.6.0 harmony: the KEY / CHORDS module, per-track chord lines, and a jsdom render check."""
import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

import whiplash
from whiplash import chat, harmony, patterns, view
from test_live import bar_events, pretend_playing
from test_whiplash import make_engine

P = patterns.PATTERNS
RENDER = Path(whiplash.__path__[0]) / "tests" / "js" / "render_view.cjs"


@pytest.fixture
def fake():
    eng, port = make_engine()
    yield eng, port
    eng.shutdown()


def lanes(frame):
    return {lane["track"]: lane for lane in frame["lanes"]}


def deephouse_progression(eng, bar=3):
    """Hardware check HW 6.0-1's setup: deep house in A minor, i-VI-III-VII, 2 bars a chord, pads on 7."""
    eng.label_tracks(tracks={"7": "pad", "8": "tuned cymbal"})
    pretend_playing(eng, P["deephouse"])
    bar_events(eng, 0)
    out = eng.set_progression(chords="i-VI-III-VII", key="A", scale="minor", bars_per_chord=2)
    for b in range(1, bar + 1):
        bar_events(eng, b)
    return out


def test_snapshot_shows_the_key_progression_and_chord_now(fake):
    eng, _ = fake
    out = deephouse_progression(eng, bar=3)
    frame = view.snapshot(eng)
    h = frame["harmony"]
    assert h["key"] == "A minor" and h["key_source"] == "set" and h["next_key"] is None and h["flats"] is False
    p = h["progression"]
    assert [c["symbol"] for c in p["chords"]] == ["i", "VI", "III", "VII"]
    assert [c["name"] for c in p["chords"]] == ["Am", "F", "C", "G"]
    assert [c["notes"] for c in p["chords"]] == [c["note_names"] for c in out["progression"]]
    assert (p["start"], p["bars_per_chord"], p["loop_bars"], p["voicing"]) == (1, 2, 8, "close")
    assert (p["index"], p["next_at"], p["next_index"]) == (1, 5, 2)  # bars 3-4 are VI; III lands on bar 5
    assert p["index"] == eng.status()["progression"]["now"]["index"]
    assert p["next_at"] == eng.status()["progression"]["now"]["next_change_at_bar"]
    json.dumps(frame)


def test_lanes_show_mode_and_the_notes_each_track_plays_in_the_chord(fake):
    eng, _ = fake
    out = deephouse_progression(eng, bar=3)
    by = lanes(view.snapshot(eng))
    voiced = {c["chord"]: set(c["notes"]) for c in out["progression"]}
    bass, pad = by[6]["harmony"], by[7]["harmony"]
    assert bass["mode"] == "root" and bass["tag"] == "ROOT" and bass["active"] and bass["next_at"] == 5
    assert [n[:-1] for n in bass["now"]] == ["F"] and [n[:-1] for n in bass["next"]] == ["C"]  # VI -> III roots
    assert pad["mode"] == "chords" and pad["tag"] == "CHD"
    names = lambda notes: {harmony.note_label(n) for n in notes}
    assert set(pad["now"]) <= names(voiced["VI"]) and set(pad["next"]) <= names(voiced["III"])
    for track in (1, 2, 3, 4, 8):  # drums and the tuned cymbal never follow
        assert by[track]["harmony"] is None, track
    cymbal = {h[2] for bar in by[8]["loop"] for h in bar}  # it plays the open-hat line, never a chord tone
    assert by[8]["kit"]["role"] == "cymbal" and cymbal == {patterns.DRUM} and by[8]["melodic"] is False


def test_loop_shows_the_next_four_bars_as_the_sequencer_will_play_them(fake):
    """The page extrapolates the playhead between frames from lane.loop, so with a progression the loop
    must already hold each upcoming bar in its own chord, or a chord change would show late."""
    eng, _ = fake
    deephouse_progression(eng, bar=3)
    frame = view.snapshot(eng)
    by = lanes(frame)
    for k in range(4):
        bar = 3 + k
        played = bar_events(eng, bar)
        idx = (frame["loop_bar"] + k) % patterns.BARS
        for track in (1, 6, 7):
            expect = sorted((s, n) for s, t, n, *_ in played if t == track)
            shown = sorted((h[0], h[2]) for h in by[track]["loop"][idx])
            assert shown == expect, (bar, track)


def test_a_progression_waiting_for_its_bar_and_an_empty_pad_track(fake):
    eng, _ = fake
    eng.label_tracks(tracks={"12": "strings"})  # a pad track with no part at all
    pretend_playing(eng, P["breaks"])
    bar_events(eng, 0)
    eng.set_progression(chords="Am F", bars_per_chord=1)
    by = lanes(view.snapshot(eng))
    p = view.snapshot(eng)["harmony"]["progression"]
    assert p["index"] is None and p["next_at"] == 1 and p["next_index"] == 0  # lands on the next bar line
    pad = by[12]["harmony"]
    assert pad["mode"] == "chords" and pad["active"] is False and pad["next_at"] == 1 and len(pad["next"]) == 1
    assert by[12]["melodic"] is True
    bar_events(eng, 1)
    pad = lanes(view.snapshot(eng))[12]
    assert pad["harmony"]["active"] and len(pad["steps"]) == 1 and pad["steps"][0][0] == 0  # one held tone, on the one


def test_key_without_a_progression_and_a_queued_key(fake):
    eng, _ = fake
    eng.play(P["techno"], bpm=300)
    try:
        h = view.snapshot(eng)["harmony"]
        assert h["key"] == "F minor" and h["key_source"] == "pattern" and h["progression"] is None
        assert all(lane["harmony"] is None for lane in view.snapshot(eng)["lanes"])
        out = eng.play(P["breaks"], bpm=300, key="A", scale="minor")
        h = view.snapshot(eng)["harmony"]
        assert h["next_key"] == {"key": "A minor", "at": out["switch_at_bar"]}
    finally:
        eng.stop()
    assert view.snapshot(eng)["harmony"] is None


def test_page_reads_only_harmony_fields_the_snapshot_has(fake):
    eng, _ = fake
    deephouse_progression(eng, bar=3)
    frame = view.snapshot(eng)
    script = view.PAGE.read_text()
    script = script[script.index("<script>"):]
    used = set(re.findall(r"\bH\.(\w+)", script))
    assert {"key", "key_source", "progression", "next_key"} <= used <= set(frame["harmony"])
    assert set(re.findall(r"\bP\.(\w+)", script)) <= set(frame["harmony"]["progression"])
    lane_h = set(re.findall(r"\bhm\.(\w+)", script)) | set(re.findall(r"\bl\.harmony\.(\w+)", script))
    assert {"tag", "now", "next", "next_at"} <= lane_h <= set(lanes(frame)[7]["harmony"])
    assert set(re.findall(r"\bc\.(symbol|name|notes)\b", script)) <= set(frame["harmony"]["progression"]["chords"][0])


# ---- jsdom render check ----------------------------------------------------------------------

def _node_with_jsdom():
    node = shutil.which("node")
    if node:
        probe = subprocess.run([node, "-e", "require('jsdom')"], capture_output=True, timeout=30)
        if probe.returncode == 0:
            return node
    if os.environ.get("WHIPLASH_JSDOM") == "required":  # CI installs jsdom: never skip silently there
        pytest.fail("node + jsdom required (WHIPLASH_JSDOM=required) but not found; see .github/workflows/tests.yml")
    pytest.skip("node with jsdom not available (npm install jsdom@24.1.3, then set NODE_PATH)")


def render(frames, tmp_path):
    node = _node_with_jsdom()
    path = tmp_path / "frames.json"
    path.write_text(json.dumps(frames, default=str))
    proc = subprocess.run([node, str(RENDER), str(view.PAGE), str(path)], capture_output=True, text=True, timeout=60)
    assert proc.returncode == 0, proc.stderr
    out = json.loads(proc.stdout)
    assert out["errors"] == [], out["errors"]
    return out["shots"]


def test_page_renders_key_chords_and_chord_lines_in_jsdom(fake, tmp_path):
    eng, _ = fake
    deephouse_progression(eng, bar=3)
    v = view.View(eng, conversation=chat.Conversation(), hooks_active=True)
    first = v.frame()
    first["pos"] = {"bar": 3, "step": 2, "age": 0.0}
    bar_events(eng, 4)
    crossing = v.frame()  # last step of bar 4, already 0.2 s old: the playhead runs into bar 5 (III)
    crossing["pos"] = {"bar": 4, "step": 15, "age": 0.2}
    eng.set_progression(clear=True)
    cleared = v.frame()
    cleared["pos"] = {"bar": 4, "step": 3, "age": 0.0}
    stopped = {**cleared, "playing": False, "pos": None, "lanes": [], "harmony": None}
    a, b, c, d = render([first, crossing, cleared, stopped], tmp_path)

    assert a["harm_hidden"] is False and a["key"] == "A MINOR" and a["key_src"] == "SET"
    assert [x["num"] for x in a["cells"]] == ["i", "VI", "III", "VII"]  # numerals keep their case
    assert [x["name"] for x in a["cells"]] == ["Am", "F", "C", "G"]
    assert [x["now"] for x in a["cells"]] == [False, True, False, False]
    assert [x["next"] for x in a["cells"]] == [False, False, True, False]
    assert a["cells"][1]["bars_on"] == 1 and "2 BARS EACH" in a["meta"]
    assert a["follow"] == "FOLLOW · 6 ROOT · 7 CHD"
    pad, bass = a["tracks"]["7"]["chd"], a["tracks"]["6"]["chd"]
    assert pad.startswith("CHD ") and "@6" in pad and bass.startswith("ROOT F4") and "> C5 @6" in bass
    assert a["tracks"]["1"]["chd"] is None and a["tracks"]["8"]["chd"] is None  # kick, tuned cymbal

    assert [x["now"] for x in b["cells"]] == [False, False, True, False]  # III lit on the bar, before a new frame
    assert b["tracks"]["6"]["chd"].startswith("ROOT C")

    assert c["harm_hidden"] is False and c["cells"] == [] and "NO PROGRESSION" in c["row"]
    assert all(t["chd"] is None for t in c["tracks"].values())
    assert d["harm_hidden"] is True
