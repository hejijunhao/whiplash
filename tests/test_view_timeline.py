"""Visualiser: the SECTIONS timeline (v0.6.1 arrangement) and the EAR module (v0.7.0 listening loop).

Both read only what the view already had: Engine.view_state(), the read-only Engine.arrangement_status() and
Engine.listen_status()/last_listen that whiplash_status uses, and the whiplash_listen result passing through
view.record_action. No engine or tool change."""
import json
import re
import time

import pytest

from whiplash import chat, listen, patterns, view
from test_live import bar_events, pretend_playing
from test_view_harmony import render
from test_whiplash import make_engine

P = patterns.PATTERNS


@pytest.fixture
def fake():
    eng, port = make_engine()
    yield eng, port
    eng.shutdown()


@pytest.fixture(autouse=True)
def fresh_listen():
    view.LISTEN.update(last=None, error=None)
    yield
    view.LISTEN.update(last=None, error=None)


def arranged(eng, pattern="deephouse", upto=0, **kw):
    pretend_playing(eng, P[pattern])
    bar_events(eng, 0)
    out = eng.arrange(**kw)
    for b in range(1, upto + 1):
        bar_events(eng, b)
    return out


def heard(clipping=False, silent=False, from_bar=17):
    """A whiplash_listen result as listen._listen returns it (bands in listen.BANDS order)."""
    return {
        "success": True, "device": "Elektron Digitakt II", "sample_rate": 48000, "channels": 2, "bars": 2,
        "bpm": 124.0, "seconds": 3.87, "playing": True, "from_bar": from_bar,
        "loudness": {"lufs_ish": -13.4, "rms_dbfs": -16.0, "peak_dbfs": 0.0 if clipping else -3.2,
                     "headroom_db": 0.0 if clipping else 3.2, "clipping": clipping, "clipped_samples": 9 if clipping else 0},
        "silent": silent,
        "bands": None if silent else {"low": {"pct": 52.1, "db": -2.8}, "low_mid": {"pct": 21.0, "db": -6.8},
                                      "mid": {"pct": 19.4, "db": -7.1}, "high": {"pct": 7.5, "db": -11.2}},
        "onsets": {"count": 30, "per_bar": 15.0, "median_abs_offset_ms": 2.1, "max_abs_offset_ms": 6.0,
                   "on_grid_pct": 97, "latency_corrected_ms": 8.2},
        "kick": {"sent": 8, "heard": 8, "missed": 0, "median_offset_ms": 8.2, "spread_ms": 1.4,
                 "offsets_ms": [8.0, 8.2, 8.9, 7.5, 8.1, 8.3, 8.2, 8.0]},
        "low_end": {"kick_over_rest_db": 9.0, "masking": False},
        "tracks": {"1": {"notes": 8, "solo_hits": 2, "heard": 2, "seems_silent": False},
                   "7": {"notes": 4, "solo_hits": 4, "heard": 0, "seems_silent": True}},
        "notes": ["track(s) [7] sent notes but nothing was heard on their solo hits"], "note": listen.NOTE,
    }


def listened(eng, result):
    """What tools.listen does on success: the engine keeps its summary, then the wrapper logs the call."""
    if result.get("success", True):
        eng.record_listen(result)
    view.record_action("whiplash_listen", {"bars": result.get("bars")}, result)


# ---- timeline snapshot -----------------------------------------------------------------------

def test_timeline_lays_the_arrangement_on_bar_lines(fake):
    eng, _ = fake
    arranged(eng, preset="club", upto=19)
    tl = view.snapshot(eng)["timeline"]
    a = tl["arrangement"]
    st = eng.status()["arrangement"]
    assert a["name"] == "club" and a["total"] == 80 and a["start"] == 1 and a["cycle"] == 1 and a["loop"] is False
    assert [(s["name"], s["start"], s["end"]) for s in a["sections"]] == [
        ("intro", 1, 17), ("build", 17, 25), ("drop", 25, 41), ("break", 41, 49), ("drop 2", 49, 65), ("outro", 65, 81)]
    assert [s["start"] for s in a["sections"]] == [s["starts_at_bar"] for s in st["sections"]]
    assert (a["index"], a["next"], a["next_at"]) == (1, "drop", 25) == (
        st["current"]["index"], st["current"]["next"], st["current"]["next_at_bar"])
    # the build's own fill and kick drop were scheduled when it started (bar 17) on its last bar, 24
    kinds = {(e["kind"], e["bar"]) for e in tl["events"]}
    assert ("fill", 24) in kinds and ("drop", 24) in kinds
    drop = next(e for e in tl["events"] if e["kind"] == "drop")
    assert drop["tracks"] == [1] and drop["bars"] == 1
    json.dumps(tl)


def test_timeline_before_the_first_section_and_on_the_last(fake):
    eng, _ = fake
    arranged(eng, preset="club")  # starts on the next bar line: nothing current yet
    a = view.snapshot(eng)["timeline"]["arrangement"]
    assert a["index"] is None and a["next_at"] == 1 and a["cycle"] == 1 and a["stops_at"] == 81
    for b in range(1, 66):
        bar_events(eng, b)
    a = view.snapshot(eng)["timeline"]["arrangement"]
    assert a["index"] == 5 and a["next"] is None and a["stops_at"] == 81


def test_a_looping_arrangement_follows_its_cycle(fake):
    eng, _ = fake
    arranged(eng, loop=True, sections=[{"name": "a", "bars": 2, "tracks": ["kick"]},
                                       {"name": "b", "bars": 1, "tracks": "all", "transition": "riser", "transition_bars": 1}], upto=5)
    a = view.snapshot(eng)["timeline"]["arrangement"]
    # bars 1-2 a, 3 b, 4-5 a (second cycle), 6 b
    assert a["cycle"] == 4 and a["index"] == 0 and a["next"] == "b" and a["next_at"] == 6 and a["stops_at"] is None
    assert [(s["start"], s["end"], s["transition"]) for s in a["sections"]] == [(4, 6, None), (6, 7, "riser")]
    bar_events(eng, 6)
    a = view.snapshot(eng)["timeline"]["arrangement"]
    assert a["index"] == 1 and a["next"] == "a" and a["next_at"] == 7


def test_timeline_without_an_arrangement_shows_what_is_scheduled(fake):
    eng, _ = fake
    pretend_playing(eng, P["deephouse"])
    bar_events(eng, 0)
    tl = view.snapshot(eng)["timeline"]
    assert tl == {"arrangement": None, "events": [], "ahead": view.TIMELINE_AHEAD}
    eng.schedule_drop([1], 2, fill=True)
    out = eng.play(P["breaks"], transition="drop_swap", transition_bars=2)
    ev = view.snapshot(eng)["timeline"]["events"]
    kinds = [e["kind"] for e in ev]
    assert "drop" in kinds and kinds[-2:] == ["transition", "switch"]
    tx, sw = ev[-2], ev[-1]
    assert (tx["transition"], tx["bar"], tx["bars"]) == ("drop_swap", out["transition"]["starts_at_bar"], 2)
    assert (sw["pattern"], sw["bar"]) == ("breaks", out["switch_at_bar"])


def test_timeline_is_absent_when_stopped(fake):
    eng, _ = fake
    frame = view.snapshot(eng)
    assert frame["timeline"] is None and frame["listen"]["last"] is None


def test_past_events_drop_off_the_timeline(fake):
    eng, _ = fake
    pretend_playing(eng, P["deephouse"])
    bar_events(eng, 0)
    eng.schedule_fill([1])
    assert [e["kind"] for e in view.snapshot(eng)["timeline"]["events"]] == ["fill"]
    for b in (1, 2):
        bar_events(eng, b)
    assert view.snapshot(eng)["timeline"]["events"] == []


# ---- listening -------------------------------------------------------------------------------

def test_ear_before_any_listen_says_why(fake, monkeypatch):
    eng, _ = fake
    monkeypatch.setattr(view, "_deps", [{"numpy": True, "sounddevice": False}])
    e = view.snapshot(eng)["listen"]
    assert e["last"] is None and e["error"] is None and e["running"] is False and e["guard"] is False
    assert e["installed"] is False and e["deps"] == {"numpy": True, "sounddevice": False}


def test_ear_keeps_a_compact_copy_of_what_was_heard(fake):
    eng, _ = fake
    listened(eng, heard())
    e = view.snapshot(eng)["listen"]
    last = e["last"]
    assert [b["band"] for b in last["bands"]] == [b[0] for b in listen.BANDS]
    assert [b["pct"] for b in last["bands"]] == [52.1, 21.0, 19.4, 7.5]
    assert last["loudness"]["lufs_ish"] == -13.4 and last["onsets"]["on_grid_pct"] == 97
    assert last["kick"]["median_offset_ms"] == 8.2 and last["quiet_tracks"] == [7] and last["from_bar"] == 17
    assert e["guard"] is False and e["error"] is None
    assert len(json.dumps(e)) < 2000  # numbers only, never audio


def test_ear_shows_clipping_as_the_guard_and_keeps_numbers_after_a_failed_listen(fake):
    eng, _ = fake
    listened(eng, heard(clipping=True))
    e = view.snapshot(eng)["listen"]
    assert e["guard"] is True and e["last"]["loudness"]["clipping"] is True
    assert eng.status()["safety"]["loudness_guard"] is True  # the same rail whiplash_status reports
    view.record_action("whiplash_listen", {"bars": 2}, {"success": False, "error": "no audio arrived from 'x'"})
    e = view.snapshot(eng)["listen"]
    assert e["error"]["error"].startswith("no audio arrived") and e["last"]["loudness"]["clipping"] is True
    time.sleep(0.01)
    listened(eng, heard())
    e = view.snapshot(eng)["listen"]
    assert e["error"] is None and e["guard"] is False


def test_ear_silent_listen_and_summary_only_fallback(fake):
    eng, _ = fake
    listened(eng, heard(silent=True))
    last = view.snapshot(eng)["listen"]["last"]
    assert last["silent"] is True and last["bands"] is None
    view.LISTEN.update(last=None)  # heard before this view module loaded: only the engine's summary
    last = view.snapshot(eng)["listen"]["last"]
    assert last["summary_only"] is True and last["bands"] is None and last["loudness"]["lufs_ish"] == -13.4


def test_ear_shows_a_listen_in_progress(fake):
    eng, _ = fake
    assert listen._BUSY.acquire(blocking=False)
    try:
        assert view.snapshot(eng)["listen"]["running"] is True
    finally:
        listen._BUSY.release()
    assert view.snapshot(eng)["listen"]["running"] is False


def test_ear_reads_a_real_analysis():
    """The view's copy keeps the shape listen.analyse really returns (synthetic audio, needs numpy)."""
    np = pytest.importorskip("numpy")
    sr = 48000
    t = np.arange(int(sr * 2)) / sr
    audio = (0.3 * np.sin(2 * np.pi * 60 * t))[:, None]
    out = {"success": True, "bars": 1, "bpm": 120.0, "playing": False, "device": "test",
           **listen.analyse(np, audio, sr, 0.0, 2.0)}
    view.record_listen(out)
    last = view.LISTEN["last"]
    low = next(b for b in last["bands"] if b["band"] == "low")
    assert low["pct"] > 90 and last["loudness"]["peak_dbfs"] < 0 and last["silent"] is False


def test_idle_frames_stay_identical_so_the_publisher_keeps_its_heartbeat(fake):
    """No ages in the frame: the page computes them from server_time, so an idle frame doesn't change."""
    eng, _ = fake
    listened(eng, heard())
    v = view.View(eng, conversation=chat.Conversation(), hooks_active=True)
    strip = lambda f: json.dumps({k: x for k, x in f.items() if k not in ("pos", "server_time")}, default=str)
    a = strip(v.frame())
    time.sleep(0.05)
    assert strip(v.frame()) == a


# ---- the page --------------------------------------------------------------------------------

def test_page_reads_only_timeline_and_listen_fields_the_snapshot_has(fake):
    eng, _ = fake
    arranged(eng, loop=True, sections=[{"name": "a", "bars": 2, "tracks": ["kick"], "fill": True},
                                       {"name": "b", "bars": 2, "tracks": "all", "transition": "riser", "transition_bars": 2}], upto=1)
    eng.schedule_drop([1], 1)
    listened(eng, heard())
    frame = view.View(eng, conversation=chat.Conversation(), hooks_active=True).frame()
    script = view.PAGE.read_text()
    script = script[script.index("<script>"):]
    tl, e = frame["timeline"], frame["listen"]
    assert {"timeline", "listen", "server_time"} <= set(re.findall(r"\bS\.(\w+)", script)) <= set(frame)
    assert set(re.findall(r"\bTL\.(\w+)", script)) <= set(tl)
    assert {"sections", "cycle", "total", "loop"} <= set(re.findall(r"\bA\.(\w+)", script)) <= set(tl["arrangement"])
    assert set(re.findall(r"\bsec\.(\w+)", script)) <= set(tl["arrangement"]["sections"][0])
    ev_keys = set().union(*(set(x) for x in tl["events"])) | {"pattern", "transition"}
    assert set(re.findall(r"\bev\.(\w+)", script)) <= ev_keys
    ear = script[script.index("// ---- EAR"):script.index("// ---- transport visuals")]
    assert set(re.findall(r"\bE\.([a-z_]+)", ear)) <= set(e)
    assert set(re.findall(r"\blast\.(\w+)", ear)) <= set(e["last"]) | {"summary_only"}
    assert set(re.findall(r"\bband\.(\w+)", ear)) <= set(e["last"]["bands"][0])
    assert set(re.findall(r"\b[LOK]\.(lufs_ish|peak_dbfs|clipping|on_grid_pct|swing_estimate|median_offset_ms|spread_ms|missed)\b",
                          ear)) <= set(e["last"]["loudness"]) | set(e["last"]["onsets"]) | set(e["last"]["kick"])


def test_page_renders_sections_and_ear_in_jsdom(fake, tmp_path):
    eng, _ = fake
    arranged(eng, sections=[{"name": "intro", "bars": 2, "tracks": ["kick", "hats"], "fill": True},
                            {"name": "drop", "bars": 4, "tracks": "all", "transition": "riser"},
                            {"name": "outro", "bars": 2, "tracks": ["kick"]}], upto=1)
    v = view.View(eng, conversation=chat.Conversation(), hooks_active=True)
    intro = v.frame()
    intro["pos"] = {"bar": 1, "step": 4, "age": 0.0}
    bar_events(eng, 2)
    crossing = v.frame()  # last step of intro's last bar, 0.15 s old: the playhead runs into the drop
    crossing["pos"] = {"bar": 2, "step": 15, "age": 0.15}
    listened(eng, heard(clipping=True, from_bar=2))
    with_ear = v.frame()
    with_ear["pos"] = {"bar": 2, "step": 2, "age": 0.0}
    view.record_action("whiplash_listen", {}, {"success": False, "error": "a listen is already running"})
    failed = v.frame()
    failed["pos"] = with_ear["pos"]
    stopped = {**failed, "playing": False, "pos": None, "lanes": [], "harmony": None, "timeline": None}
    nothing = {**stopped, "listen": {"running": False, "last": None, "error": None, "guard": False,
                                     "installed": False, "deps": {"numpy": False, "sounddevice": False}}}
    a, b, c, d, s, n = render([intro, crossing, with_ear, failed, stopped, nothing], tmp_path)

    assert a["tl_hidden"] is False and a["tl_name"] == "custom" and "3 SECTIONS · 8 BARS · STOPS @10" in a["tl_meta"]
    assert a["tl_now"] == "NOW intro · 1/2" and a["tl_next"].startswith("NEXT drop @4") and a["tl_cue"] == 0
    assert a["tl_events"].startswith("FILL ") and "@3" in a["tl_events"]
    assert a["tl_label"] == "intro bars 2-3, drop bars 4-7, outro bars 8-9"
    assert a["ear_state"] == "IDLE" or a["ear_state"] == "OFF"
    assert a["ear_patched"] is False and a["guard"] is False

    assert b["tl_now"] == "NOW drop · 1/4"  # on the bar, before the next frame arrives
    assert "TX riser" in b["tl_next"] and b["tl_next"].startswith("NEXT outro @8")

    assert c["ear_state"] == "HEARD" and c["guard"] is True and c["ear_patched"] is True
    assert "LUFS -13.4" in c["ear_read"] and "CLIP" in c["ear_read"] and "GRID 97%" in c["ear_read"]
    assert "KICK +8.2MS" in c["ear_read"] and "QUIET 7" in c["ear_read"]
    assert c["ear_note"].startswith("TRACK(S) [7]")

    assert d["ear_note"].startswith("LAST LISTEN FAILED") and "LUFS -13.4" in d["ear_read"]  # last numbers kept
    assert s["tl_hidden"] is True and s["ear_state"] == "HEARD"
    assert n["ear_state"] == "OFF" and "NUMPY + SOUNDDEVICE" in n["ear_note"] and n["ear_read"] == ""
