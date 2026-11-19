"""v0.9.4 (ontology O5): taste polish. Listen data in reviews, heard hints, hint wording, the threshold table.

Fake ports only: listens are recorded with Engine.record_listen from a hand-made result, never captured.
"""
import json
import re

import pytest

from whiplash import genres, library, listen, patterns, schemas, taste, tools
from test_live import bar_events, pretend_playing
from test_whiplash import make_engine

P = patterns.PATTERNS
ROLES = {1: "kick", 2: "snare", 3: "clap", 4: "closed hat", 5: "open hat", 6: "bass", 7: "perc", 8: "perc"}


@pytest.fixture
def tool(monkeypatch):
    e, port = make_engine()
    monkeypatch.setattr(tools, "ENGINE", e)
    yield e
    e.shutdown()


def call(name, **params):
    return json.loads(tools.HANDLERS[name](params))


def run(eng, first, last):
    for b in range(first, last + 1):
        bar_events(eng, b)


def heard_result(masking=True, clipping=False, low=38.5, kick_db=1.2, playing=True):
    return {"playing": playing, "bars": 2, "silent": False,
            "loudness": {"clipping": clipping, "lufs_ish": -9.5, "peak_dbfs": -0.4 if not clipping else 0.0},
            "bands": {"low": {"pct": low, "db": -4.1}, "low_mid": {"pct": 30.0, "db": -5.2}},
            "low_end": {"kick_over_rest_db": kick_db, "masking": masking} if kick_db is not None else None}


def digest(n, events=None, start=0):
    events = events or {0: [(1, 60, 120, 1, 0.0)], 4: [(1, 60, 120, 1, 0.0)], 8: [(6, 57, 100, 1, 0.0)]}
    return [(b, float(b), events, None, "Am", frozenset(), False) for b in range(start, start + n)]


def busy_events():
    """Seven drum tracks (track 8 the busiest after the kick) and a bass on two kick steps."""
    ev = {s: [(t, 60, 100, 1, 0.0) for t in (1, 2, 3, 4, 5, 7)] for s in (0, 4, 8, 12)}
    for s in range(16):
        ev.setdefault(s, []).append((8, 60, 90, 1, 0.0))
    ev[0].append((6, 45, 100, 1, 0.0))
    ev[8].append((6, 45, 100, 1, 0.0))
    return ev


# ---- listen summary --------------------------------------------------------------------------------------------

def test_summary_keeps_the_heard_low_end():
    s = listen.summary(heard_result())
    assert s["masking"] is True and s["kick_over_rest_db"] == 1.2 and s["low_pct"] == 38.5
    silent = listen.summary({"silent": True, "bands": None, "low_end": None, "loudness": {}})
    assert silent["masking"] is None and silent["kick_over_rest_db"] is None and silent["low_pct"] is None
    assert listen.summary(heard_result(kick_db=None))["masking"] is None  # under two kicks: can't judge


# ---- taste.heard (pure) ----------------------------------------------------------------------------------------

def _heard(bar, run=0, **kw):
    return {**listen.summary(heard_result(**kw)), "_bar": bar, "_run": run}


def test_heard_applies_under_32_bars_and_says_why_not():
    d = digest(40)
    block, note = taste.heard(_heard(20), d, 0)
    assert note is None and block["bars_ago"] == 19 and block["masking"] is True and block["low_pct"] == 38.5
    assert set(block) == {"bars_ago", "clipping", "masking", "kick_over_rest_db", "low_pct", "lufs_ish", "peak_dbfs"}
    assert taste.heard(_heard(8), d, 0)[0]["bars_ago"] == 31  # the last bar under the limit
    block, note = taste.heard(_heard(7), d, 0)
    assert block is None and "32 bars old" in note and "whiplash_listen again" in note
    block, note = taste.heard(_heard(20, run=0), d, 1)  # an earlier run heard another beat
    assert block is None and "another run" in note
    assert taste.heard({**_heard(20), "_bar": None}, d, 0)[0] is None  # taken while stopped
    assert taste.heard(None, d, 0) == (None, None)
    assert taste.LISTEN_BARS == 32


# ---- heard hints -----------------------------------------------------------------------------------------------

def test_masking_hint_counts_the_collisions_and_suggests_an_offbeat_bass():
    m = taste.metrics(digest(8, busy_events()), [], [], ROLES)
    assert m["low_collisions"] == 2 and m["bass_track"] == 6
    block, _ = taste.heard(_heard(5), digest(8), 0)
    fired = taste.hints(m, "techhouse", 3, block, 5)
    assert fired["masking"].startswith("Bass hits 2 kick steps per bar and the last listen heard the kick masked")
    assert "whiplash_write_part(track: 6, phrase: 'bass.offbeat')" in fired["masking"]
    assert "whiplash_mix(levels: {'bass': 95})" in fired["masking"]
    clean = taste.metrics(digest(8), [], [], {1: "kick", 6: "bass"})
    assert clean["low_collisions"] == 0
    text = taste.hints(clean, "techhouse", 3, block, 5)["masking"]
    assert "avoids the kick steps" in text and "bass.offbeat" not in text
    assert "masking" not in taste.hints(m, "techhouse", 3, taste.heard(_heard(5, masking=False), digest(8), 0)[0], 5)
    assert "masking" not in taste.hints(m, "techhouse", 3, None, 5)  # nothing heard: no heard hint


def test_clipping_hint_only_when_heard():
    m = taste.metrics(digest(4), [], [], ROLES)
    block, _ = taste.heard(_heard(2, masking=False, clipping=True), digest(4), 0)
    fired = taste.hints(m, "deephouse", 3, block, 5)
    assert list(fired) == ["clipping"] and "whiplash_mix" in fired["clipping"] and "listen again" in fired["clipping"]
    assert taste.hints(m, "deephouse", 3, None, 5) == {}


# ---- hint wording ----------------------------------------------------------------------------------------------

def _all_hints(genre, energy=3, levels=5):
    m = taste.metrics(digest(64, busy_events()), [], [], ROLES)
    block, _ = taste.heard(_heard(60, clipping=True), digest(64), 0)
    return taste.hints(m, genre, energy, block, levels)


ALL_GENRES = (*genres.GENRES, "soul", "breaks")


@pytest.mark.parametrize("genre", ALL_GENRES)
def test_every_hint_names_real_calls_and_library_entries(genre):
    fired = _all_hints(genre, *((3, 1) if genre in ("soul", "breaks") else (3, 5)))
    assert {"repetition", "masking", "clipping"} <= set(fired)
    for text in fired.values():
        assert text.count(". ") == 0 and text.endswith(".")  # one sentence
        assert ": try " in text
        for name in re.findall(r"\b(whiplash_\w+)", text):
            assert name in schemas.SCHEMAS, name
        for kind, name in re.findall(r"(groove|phrase|fill): '([\w.]+)'", text):
            kind = "lane" if kind == "groove" else kind  # write_part(groove: ...) takes a lane
            assert library.resolve(kind, name).name == name, (kind, name)


def test_energy_steps_follow_the_groove_levels():
    m = taste.metrics(digest(64), [], [], ROLES)
    rep = lambda genre, energy, levels: taste.hints(m, genre, energy, None, levels)["repetition"]
    assert "amount: 'up'" in rep("techhouse", 3, 5)
    assert "amount: 'down'" in rep("techhouse", 5, 5)  # already at the top
    assert "whiplash_play_pattern(groove: 'techhouse.classic', energy: 4)" in rep("techhouse", None, None)
    for genre in ("soul", "breaks"):  # one energy level: never offer one
        text = rep(genre, 3, 1)
        assert "'energy'" not in text and "amount: 'thicken'" in text
    assert "whiplash_mutate(action: 'fill', fill: 'kick.sit_out')" in rep("techhouse", 3, 5)
    assert "whiplash_write_part(groove: 'perc.woodblock') on a free track" in rep("techhouse", 3, 5)


def test_filter_sweep_where_automation_is_the_change():
    m = taste.metrics(digest(64), [], [], ROLES)
    sweep = {g for g in genres.GENRES if "whiplash_ramp_param" in taste.hints(m, g, 3, None, 5)["repetition"]}
    assert sweep == {"deephouse", "progressivehouse", "melodictechno", "techno", "minimal.house", "minimal.techno"}
    assert "whiplash_write_part(phrase: 'bass.bouncy')" in taste.hints(m, "techhouse", 3, None, 5)["repetition"]


def test_busy_hint_names_the_busiest_drum_after_the_kick():
    m = taste.metrics(digest(8, busy_events()), [], [], ROLES)
    assert m["drum_elements"] == 7 and m["busiest_drum"] == 8
    text = taste.hints(m, "minimal.house", 3, None, 5)["busy"]
    assert text == ("Busy for minimal house: 7 drum elements, and minimal house holds 4: try "
                    "whiplash_mute_track(track: 8), the busiest drum after the kick, or "
                    "whiplash_mutate(action: 'energy', amount: 'down').")
    assert "'energy'" not in taste.hints(m, "soul", 3, None, 1)["busy"]
    assert "amount: 'up'" in taste.hints(m, "minimal.house", 1, None, 5)["busy"]  # at energy 1 there is no down


def test_repetition_wording_example():
    m = taste.metrics(digest(8), [], [], ROLES)
    assert taste.hints(m, "techhouse", 3, None, 5)["repetition"] == (
        "8 bars unchanged in tech house, which wants a change every 8: try "
        "whiplash_mutate(action: 'energy', amount: 'up'), whiplash_mutate(action: 'fill', fill: 'kick.sit_out'), "
        "whiplash_write_part(groove: 'perc.woodblock') on a free track, or whiplash_write_part(phrase: 'bass.bouncy').")


# ---- thresholds: pinned, so a tuned value is a deliberate edit --------------------------------------------------

THRESHOLDS = {  # spec §7.2 / Q-T2. No session results yet (checklist O9, O21 untested): unchanged in O5.
    "techhouse": (8, 7), "tropicalhouse": (16, 5), "progressivehouse": (16, 5), "melodictechno": (16, 6),
    "deephouse": (32, 5), "house": (32, 5), "techno": (64, 6), "minimal.house": (64, 4), "minimal.techno": (64, 4),
    "soul": (16, 6), "breaks": (16, 6),
}


def test_threshold_table_is_pinned():
    assert {g: (t["unchanged_bars"], t["busy_drums"]) for g in THRESHOLDS
            for t in [taste.thresholds(g)]} == THRESHOLDS
    assert set(genres.GENRES) | {"soul", "breaks"} == set(THRESHOLDS)


# ---- engine ----------------------------------------------------------------------------------------------------

def test_review_reads_a_recent_listen_and_forgets_an_old_one(tool, monkeypatch):
    monkeypatch.setattr(listen, "listen", lambda *a, **k: pytest.fail("a review must never capture"))
    pretend_playing(tool, P["techhouse"])
    run(tool, 0, 3)
    tool.record_listen(heard_result())
    run(tool, 4, 9)
    sent = tool.sent_count
    review = call("whiplash_status", review=8)
    assert review["success"] and review["listen"]["bars_ago"] == 6 and review["listen"]["masking"] is True
    assert "listen_note" not in review
    assert any(h.startswith("Bass hits") or h.startswith("The last listen heard the kick masked")
               for h in review["hints"])
    assert review["energy"] == 3  # a plain classic genre is its classic groove at energy 3
    assert tool.sent_count == sent and tool._input is None
    status = call("whiplash_status")
    assert status["listen"]["masking"] is True and "_bar" not in status["listen"] and "_run" not in status["listen"]
    run(tool, 10, 35)
    review = call("whiplash_status", review=8)
    assert review["listen"] is None and "bars old" in review["listen_note"]
    assert not any("masked" in h for h in review["hints"])


def test_a_listen_from_an_earlier_run_never_applies(tool):
    pretend_playing(tool, P["techhouse"])
    run(tool, 0, 3)
    tool.record_listen(heard_result())
    with tool._lock:
        tool._run_id += 1  # what a fresh start does
        tool.bar_digest.clear()
    run(tool, 0, 5)
    review = call("whiplash_status", review=4)
    assert review["listen"] is None and "another run" in review["listen_note"]


def test_a_listen_taken_while_stopped_never_applies(tool):
    pretend_playing(tool, P["techhouse"])
    run(tool, 0, 3)
    tool.record_listen(heard_result(playing=False))
    run(tool, 4, 5)
    review = call("whiplash_status", review=4)
    assert review["listen"] is None and "while stopped" in review["listen_note"]


def test_heard_hint_rides_taste_hint_once(tool):
    pretend_playing(tool, P["deephouse"])  # 32 bars before a repetition hint: only the heard one fires
    run(tool, 0, 3)
    tool.record_listen(heard_result(masking=False, clipping=True))
    run(tool, 4, 5)
    first = call("whiplash_mutate", action="humanize", amount=0.1)
    assert first["success"] and first["taste_hint"].startswith("The last listen heard clipping")
    assert "taste_hint" not in call("whiplash_mutate", action="humanize", amount=0.2)
    assert "listen" not in tools.MUSICAL  # whiplash_listen carries its own notes, never a taste_hint


def test_no_listen_keeps_the_review_as_before(tool):
    pretend_playing(tool, P["techhouse"])
    run(tool, 0, 9)
    review = call("whiplash_status", review=8)
    assert review["listen"] is None and "listen_note" not in review
    assert review["hints"] and review["hints"][0].startswith("10 bars unchanged in tech house")
