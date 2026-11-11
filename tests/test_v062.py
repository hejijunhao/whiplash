"""v0.6.2: DJ-style transitions (cut, filter_swap, drop_swap, riser) on a queued switch and between arrangement
sections, and whiplash_mix (track LEVEL CC 95, PAN CC 90, presets, snapshots). Everything here runs against fake
ports; nothing in it says how the Digitakt II sounds."""
from pathlib import Path

import mido
import pytest

import whiplash
from whiplash import arrange, ccmap, engine, mixer, patterns, schemas, tools, transition
from test_whiplash import call, make_engine, tool_engine  # noqa: F401  (fixture)
from test_live import bar_events, pretend_playing, timeline, wait_bar
from test_v051 import TimedPort, assert_jitter

P = patterns.PATTERNS
ROOT = Path(whiplash.__path__[0])
BAR = engine.TICKS_PER_BAR
DEEPHOUSE_HIGHS = [2, 3, 4, 5, 7, 8]  # everything but kick (1) and bass (6)
ALLOWED_CCS = {ccmap.PARAMS["filter_freq"].cc, ccmap.PARAMS["track_level"].cc, ccmap.PARAMS["pan"].cc,
               engine.ALL_NOTES_OFF}


@pytest.fixture
def fake():
    eng, port = make_engine()
    yield eng, port
    eng.shutdown()


def play_bar(eng, bar):
    """Drive one whole bar by hand: its bar line, then a bar of clock ticks for the ramps."""
    events = bar_events(eng, bar)
    for _ in range(BAR):
        eng._advance_ramps(mido)
    return events


def tracks_in(events):
    return {t for _, t, *_ in events}


def cc_values(port, control, start=0):
    """{track: [values]} for one CC, from message index start."""
    out = {}
    for m in port.messages[start:]:
        if m.type == "control_change" and m.control == control:
            out.setdefault(m.channel + 1, []).append(m.value)
    return out


def last_cc(eng, track, control):
    return eng._cc_values.get((track - 1, control))


def assert_safe(port):
    for m in port.messages:
        assert m.type in engine.ALLOWED_TYPES, m
        if m.type == "control_change":
            assert m.control not in ccmap.BLOCKED_CCS, m


# ---- transition.py ------------------------------------------------------------------------

def test_transition_names_bars_and_filter_from():
    assert transition.kind(None) is None and transition.kind("") is None
    assert transition.kind("Filter Swap") == transition.kind("filter") == "filter_swap"
    assert transition.kind("drop-out") == "drop_swap" and transition.kind("none") == "cut"
    with pytest.raises(transition.TransitionError, match="one of cut, filter_swap"):
        transition.kind("spinback")
    assert [transition.bars(k, None) for k in transition.KINDS] == [0, 4, 1, 4]
    assert transition.bars("riser", 8) == 8
    for bad in (0, 9, 2.5, True, "x"):
        with pytest.raises(transition.TransitionError):
            transition.bars("filter_swap", bad)
    with pytest.raises(transition.TransitionError, match="other than cut"):
        transition.bars("cut", 2)
    with pytest.raises(transition.TransitionError, match="other than cut"):
        transition.bars(None, 2)
    assert transition.filter_from("filter_swap", 127) == 127 and transition.filter_from("riser", None) is None
    with pytest.raises(transition.TransitionError, match="only applies"):
        transition.filter_from("riser", 100)
    with pytest.raises(transition.TransitionError, match="0-127"):
        transition.filter_from("filter_swap", 128)


# ---- filter_swap on a queued switch -------------------------------------------------------

def test_filter_swap_closes_switches_on_the_one_and_reopens(fake):
    eng, port = fake
    pretend_playing(eng, P["deephouse"])
    play_bar(eng, 0)
    for t in (2, 4):
        eng.set_param(t, 100, param="filter_freq")  # known cutoffs; the rest come from filter_from
    sent = len(port.messages)
    out = eng.play(P["techno"], transition="filter_swap", transition_bars=2, filter_from=127)
    assert out["mode"] == "queued" and out["switch_at_bar"] == 3
    assert out["transition"]["starts_at_bar"] == 1 and out["transition"]["filter"] == DEEPHOUSE_HIGHS
    assert len(port.messages) == sent  # nothing is sent until the bar line
    play_bar(eng, 1)
    play_bar(eng, 2)
    assert eng.pattern.name == "deephouse"  # still the outgoing pattern
    closing = cc_values(port, 74, sent)
    assert set(closing) == set(DEEPHOUSE_HIGHS)  # kick and bass keep their filter
    assert closing[3][0] == 127 and closing[2][0] == 99  # filter_from sent on the one; track 2 starts from 100
    for t in DEEPHOUSE_HIGHS:
        assert closing[t] == sorted(closing[t], reverse=True) and closing[t][-1] == transition.FILTER_FLOOR
    assert eng._restore == {(2, 74): 100, (3, 74): 127, (4, 74): 100, (5, 74): 127, (7, 74): 127, (8, 74): 127}
    before = len(port.messages)
    events = play_bar(eng, 3)
    assert eng.pattern.name == "techno" and eng.pattern_start == 3  # switched on the one
    assert 1 in tracks_in(events) and any(s == 0 for s, t, *_ in events if t == 1)
    reopening = cc_values(port, 74, before)
    for t in DEEPHOUSE_HIGHS:
        assert reopening[t] == sorted(reopening[t]) and reopening[t][-1] == eng._cc_values[(t - 1, 74)]
    assert last_cc(eng, 2, 74) == 100 and last_cc(eng, 7, 74) == 127  # back where each was
    assert eng._restore == {} and eng.ramps() == []
    assert port.count("start") == port.count("stop") == 0  # no Stop/Start around the switch
    assert_safe(port)


def test_filter_swap_without_a_known_cutoff_is_refused_and_changes_nothing(fake):
    eng, port = fake
    pretend_playing(eng, P["deephouse"])
    play_bar(eng, 0)
    sent = len(port.messages)
    with pytest.raises(engine.WhiplashError, match="filter_from"):
        eng.play(P["techno"], transition="filter_swap")
    for bad in ({"transition": "spin"}, {"transition": "cut", "transition_bars": 2},
                {"transition": "riser", "filter_from": 100}, {"transition": "drop_swap", "transition_bars": 9}):
        with pytest.raises(engine.WhiplashError):
            eng.play(P["techno"], **bad)
    assert eng._queued is None and eng._timed == {} and eng._drops == {} and len(port.messages) == sent
    assert eng.play(P["techno"], transition="cut")["switch_at_bar"] == 1  # cut: today's switch


def test_a_fresh_start_ignores_the_transition(fake):
    eng, port = fake
    out = eng.play(P["techno"], transition="filter_swap", filter_from=127)
    try:
        assert out["mode"] == "started" and "ignored" in out["transition_note"]
        assert eng._timed == {}
    finally:
        eng.stop()


# ---- drop_swap and riser ------------------------------------------------------------------

def test_drop_swap_drops_kick_and_bass_then_brings_them_back_on_the_switch(fake):
    eng, _ = fake
    pretend_playing(eng, P["deephouse"])
    play_bar(eng, 0)
    out = eng.play(P["techno"], transition="drop_swap")
    assert out["switch_at_bar"] == 2 and out["transition"]["dropped"] == [1, 6]
    playing = tracks_in(play_bar(eng, 1))
    assert 1 not in playing and 6 not in playing and {2, 4, 7} <= playing
    back = tracks_in(play_bar(eng, 2))
    assert eng.pattern.name == "techno" and {1, 6} <= back and eng._drops == {}


def test_riser_ramps_the_fx_track_and_fills_the_last_bar(fake):
    eng, port = fake
    eng.label_tracks(tracks={"9": "riser"})
    pretend_playing(eng, P["deephouse"])
    play_bar(eng, 0)
    out = eng.play(P["techno"], transition="riser", transition_bars=2)
    assert out["transition"]["riser"] == [9] and out["transition"]["fill"] == [1, 2, 3, 4, 5]
    assert "until the kit is reloaded" in out["transition"]["notes"][0]
    sent = len(port.messages)
    play_bar(eng, 1)
    assert eng.bar_fills == (1, frozenset())
    play_bar(eng, 2)
    assert eng.bar_fills == (2, frozenset({1, 2, 3, 4, 5}))  # the fill on the bar before the switch
    rise = cc_values(port, 74, sent)[9]
    assert rise[0] == transition.RISER_FROM and rise[-1] == transition.RISER_TO and rise == sorted(rise)
    play_bar(eng, 3)
    assert eng.pattern.name == "techno" and last_cc(eng, 9, 74) == 127 and eng._restore == {}


def test_riser_without_an_fx_label_is_the_fill_only(fake):
    eng, _ = fake
    pretend_playing(eng, P["deephouse"])
    play_bar(eng, 0)
    out = eng.play(P["techno"], transition="riser", transition_bars=1)
    assert out["transition"]["riser"] == [] and "no track is labelled fx" in out["transition"]["notes"][0]
    assert out["switch_at_bar"] == 2 and eng._fills == {1: {1, 2, 3, 4, 5}}


# ---- replacing, stopping ------------------------------------------------------------------

def test_replacing_a_transition_cancels_it_and_reopens_at_the_new_switch(fake):
    eng, port = fake
    pretend_playing(eng, P["deephouse"])
    play_bar(eng, 0)
    eng.play(P["techno"], transition="filter_swap", transition_bars=4, filter_from=127)
    eng.schedule_drop([3], 1)
    play_bar(eng, 1)  # closing
    half = last_cc(eng, 4, 74)
    assert transition.FILTER_FLOOR < half < 127
    out = eng.play(P["breaks"])  # a plain switch on the next bar: the filter_swap is cancelled
    assert out["switch_at_bar"] == 2 and out["replaced_transition"]["kind"] == "filter_swap"
    assert out["replaced_transition"]["ramps_cancelled"] and eng.ramps() == []
    assert eng._timed == {} and (3, 74) in eng._restore
    for _ in range(40):
        eng._advance_ramps(mido)
    assert last_cc(eng, 4, 74) == half  # nothing closes any more
    play_bar(eng, 2)
    assert eng.pattern.name == "breaks" and last_cc(eng, 4, 74) == 127 and eng._restore == {}


def test_replacing_a_drop_swap_brings_the_low_end_back(fake):
    eng, _ = fake
    pretend_playing(eng, P["deephouse"])
    play_bar(eng, 0)
    eng.play(P["techno"], transition="drop_swap", transition_bars=4)
    assert 1 not in tracks_in(play_bar(eng, 1))
    eng.play(P["breaks"], transition="cut")
    assert eng._drops == {}
    assert {1, 6} & tracks_in(play_bar(eng, 2))


def test_stop_mid_filter_swap_cancels_ramps_and_puts_the_cutoff_back(fake):
    eng, port = fake
    pretend_playing(eng, P["deephouse"])
    play_bar(eng, 0)
    eng.play(P["techno"], transition="filter_swap", filter_from=110)
    play_bar(eng, 1)
    assert last_cc(eng, 7, 74) < 110
    out = eng.stop()
    assert out["cutoff_restored"] == {str(t): 110 for t in DEEPHOUSE_HIGHS}
    assert eng._timed == {} and eng.ramps() == [] and eng._restore == {} and eng._queued is None
    for t in DEEPHOUSE_HIGHS:
        assert last_cc(eng, t, 74) == 110
    assert_safe(port)


def test_stop_on_a_live_run_mid_filter_swap(fake):
    eng, port = fake
    eng.play(P["deephouse"], bpm=280)
    try:
        wait_bar(eng, 1)
        for t in DEEPHOUSE_HIGHS:
            eng.set_param(t, 120, param="filter_freq")
        out = eng.play(P["techno"], transition="filter_swap", transition_bars=4)
        wait_bar(eng, out["switch_at_bar"] - 2)
    finally:
        stopped = eng.stop()
    assert stopped["was_playing"] and set(stopped["cutoff_restored"]) == {str(t) for t in DEEPHOUSE_HIGHS}
    msgs = [m for _, _, m in timeline(port)]
    stop_at = max(i for i, m in enumerate(msgs) if m.type == "stop")
    after = [m for m in msgs[stop_at + 1:] if m.type == "control_change" and m.control == 74]
    assert after == []  # the restore goes out with the panic, no ramp step after Stop
    assert eng.pattern.name == "deephouse" and port.count("clock") > 0
    for t in DEEPHOUSE_HIGHS:
        assert last_cc(eng, t, 74) == 120
    assert_safe(port)


# ---- transitions between arrangement sections ---------------------------------------------

def test_section_filter_swap_runs_over_its_last_bars_and_reopens_on_the_next(fake):
    eng, port = fake
    pretend_playing(eng, P["deephouse"])
    play_bar(eng, 0)
    out = eng.arrange(sections=[{"name": "a", "bars": 4, "transition": "filter_swap", "transition_bars": 2,
                                 "filter_from": 127}, {"name": "b", "bars": 4}], loop=True)
    assert out["sections"][0]["transition"]["starts_at_bar"] == 3
    sent = len(port.messages)
    play_bar(eng, 1)
    play_bar(eng, 2)
    assert cc_values(port, 74, sent) == {}  # nothing until the transition's first bar
    play_bar(eng, 3)
    play_bar(eng, 4)
    closed = cc_values(port, 74, sent)
    assert set(closed) == set(DEEPHOUSE_HIGHS) and all(v[-1] == transition.FILTER_FLOOR for v in closed.values())
    play_bar(eng, 5)  # section b: reopen on its one
    assert eng.arrangement_status()["current"]["section"] == "b"
    assert all(last_cc(eng, t, 74) == 127 for t in DEEPHOUSE_HIGHS) and eng._restore == {}
    assert eng.arrangement_status()["sections"][0]["transition"] == "filter_swap"


def test_section_transitions_skip_unknown_cutoffs_and_drop_and_rise(fake):
    eng, _ = fake
    eng.label_tracks(tracks={"9": "sweep"})
    pretend_playing(eng, P["deephouse"])
    play_bar(eng, 0)
    eng.set_param(4, 90, param="filter_freq")
    eng.arrange(sections=[{"name": "a", "bars": 2, "transition": "filter_swap", "transition_bars": 1},
                          {"name": "b", "bars": 2, "transition": "drop_swap"},
                          {"name": "c", "bars": 2, "transition": "riser", "transition_bars": 2}])
    play_bar(eng, 1)
    play_bar(eng, 2)
    assert eng._restore == {(4, 74): 90}  # only the known cutoff; the others are skipped
    assert any("no 'filter_from'" in s for s in eng.arrangement_status()["skipped_ramps"])
    play_bar(eng, 3)
    assert eng._restore == {} and last_cc(eng, 4, 74) == 90
    assert not {1, 6} & tracks_in(play_bar(eng, 4))  # b's last bar: low end out
    events = play_bar(eng, 5)  # c: riser over both bars, back with the low end
    assert {1, 6} <= tracks_in(events) and last_cc(eng, 9, 74) > transition.RISER_FROM
    play_bar(eng, 6)
    assert eng.bar_fills[1] == frozenset({1, 2, 3, 4, 5}) and last_cc(eng, 9, 74) == 127


def test_section_transition_validation_and_clear(fake):
    eng, port = fake
    pretend_playing(eng, P["deephouse"])
    play_bar(eng, 0)
    sent = len(port.messages)
    for bad in ({"bars": 2, "transition": "riser", "transition_bars": 4},
                {"bars": 4, "transition_bars": 2}, {"bars": 4, "transition": "drop_swap", "filter_from": 3},
                {"bars": 4, "mix": "no such mix"}, {"bars": 4, "mix": 5}):
        with pytest.raises(engine.WhiplashError):
            eng.arrange(sections=[bad])
    assert eng._arr is None and len(port.messages) == sent
    eng.arrange(sections=[{"bars": 4, "transition": "filter_swap", "transition_bars": 3, "filter_from": 120},
                          {"bars": 4}])
    play_bar(eng, 1)
    play_bar(eng, 2)
    assert eng._restore and eng.ramps()
    out = eng.arrange(clear=True)
    assert out["transition_ramps_cancelled"] and out["cutoff_reopening"] == DEEPHOUSE_HIGHS
    play_bar(eng, 3)
    assert all(last_cc(eng, t, 74) == 120 for t in DEEPHOUSE_HIGHS) and eng.ramps() == []


def test_presets_carry_no_transition():  # the demo's arrangements are unchanged in v0.6.2
    for raw in (arrange.club(), arrange.short_demo(120)):
        assert all(s.transition is None and s.mix is None for s in arrange.sections(raw))


# ---- mix ----------------------------------------------------------------------------------

def test_mix_lands_on_the_bar_one_cc_per_change(fake):
    eng, port = fake
    pretend_playing(eng, P["deephouse"])
    play_bar(eng, 0)
    sent = len(port.messages)
    out = eng.mix(levels={"6": 95, "kick": 118}, pan={"hats": "left", "7": 80})
    assert out["applies"] == "next bar" and out["at_bar"] == 1
    assert out["levels"] == {"1": 118, "6": 95} and out["pan"] == {"4": 32, "5": 32, "7": 80}
    assert len(port.messages) == sent
    play_bar(eng, 1)
    new = [(m.channel + 1, m.control, m.value) for m in port.messages[sent:]]
    assert sorted(new) == [(1, 95, 118), (4, 90, 32), (5, 90, 32), (6, 95, 95), (7, 90, 80)]
    sent = len(port.messages)
    eng.mix(levels={"6": 95, "1": 110})  # 6 is already 95: only track 1 goes out
    play_bar(eng, 2)
    assert [(m.channel + 1, m.value) for m in port.messages[sent:]] == [(1, 110)]
    status = eng.status()["mix"]
    assert status["levels"] == {"1": 110, "6": 95} and status["pan"]["4"] == 32


def test_mix_ramps_over_bars_and_replaces_a_running_ramp(fake):
    eng, port = fake
    pretend_playing(eng, P["deephouse"])
    play_bar(eng, 0)
    eng.set_param(6, 100, param="level")
    eng.ramp(6, 127, param="track_level", bars=8)
    out = eng.mix(levels={"6": 60, "7": 90}, bars=2)
    assert out["ramp_bars"] == 2 and out["jumps"] == [7]
    sent = len(port.messages)
    play_bar(eng, 1)
    assert last_cc(eng, 7, 95) == 90  # unknown before: jumps on the bar line
    assert 60 < last_cc(eng, 6, 95) < 100
    play_bar(eng, 2)
    vals = cc_values(port, 95, sent)[6]
    assert vals == sorted(vals, reverse=True) and vals[-1] == 60 and eng.ramps() == []


def test_mix_save_and_recall_round_trip(fake):
    eng, port = fake
    pretend_playing(eng, P["deephouse"])
    play_bar(eng, 0)
    out = eng.mix(levels={"1": 120, "6": 110}, pan={"4": 40}, save_as="Drop  Mix")
    assert out["saved_as"] == "drop mix" and out["saved_mixes"] == ["drop mix"]
    play_bar(eng, 1)
    eng.mix(levels={"6": 80, "1": 100})
    play_bar(eng, 2)
    sent = len(port.messages)
    out = eng.mix(recall="drop mix")
    assert out["recalled"] == "drop mix" and out["changes"] == 2
    play_bar(eng, 3)
    assert sorted((m.channel + 1, m.control, m.value) for m in port.messages[sent:]) == [(1, 95, 120), (6, 95, 110)]
    eng.stop()
    del eng.playing  # pretend_playing's stand-in: idle again
    assert eng.mix(recall="drop mix")["applies"] == "now"  # snapshots survive stop; idle sends now
    with pytest.raises(engine.WhiplashError, match="no saved mix"):
        eng.mix(recall="break mix")


def test_mix_presets_and_save_of_what_was_sent(fake):
    eng, _ = fake
    pretend_playing(eng, P["techno"])
    play_bar(eng, 0)
    out = eng.mix(preset="auto")
    assert out["preset"] == "techno" and out["levels"]["1"] == mixer.PRESETS["techno"]["kick"] == 120
    play_bar(eng, 1)
    assert eng.mix(save_as="peak")["saved_as"] == "peak"
    assert eng._mixes["peak"][1] == {"level": 120}
    assert mixer.preset("flat", None)[1]["kick"] == 100 and mixer.preset("auto", None)[0] == "flat"
    assert set(mixer.PRESETS) >= set(P)  # a preset for every genre


def test_bad_mix_input_sends_nothing(fake):
    eng, port = fake
    pretend_playing(eng, P["deephouse"])
    play_bar(eng, 0)
    sent = len(port.messages)
    for bad in ({}, {"levels": {"1": 128}}, {"levels": {"1": -1}}, {"levels": {"17": 100}}, {"levels": [100]},
                {"levels": {"tuba": 100}}, {"pan": {"4": "upwards"}}, {"preset": "polka"}, {"levels": {"1": 90},
                "bars": 33}, {"recall": "x", "levels": {"1": 90}}, {"save_as": "x" * 30}, {"recall": "missing"},
                {"save_as": ""}, {"levels": {"lead": 90}}, {"save_as": "nothing yet"}):
        with pytest.raises(engine.WhiplashError):
            eng.mix(**bad)
    assert len(port.messages) == sent and eng._timed == {} and eng._mixes == {}


def test_mix_when_idle_sends_now_and_refuses_a_ramp(fake):
    eng, port = fake
    out = eng.mix(levels={"3": 90})
    assert out["applies"] == "now" and out["sent"] == 1 and port.count("control_change", control=95) == 1
    with pytest.raises(engine.WhiplashError, match="sequencer clock"):
        eng.mix(levels={"3": 80}, bars=2)


def test_a_section_recalls_a_mix_on_its_first_bar(fake):
    eng, _ = fake
    pretend_playing(eng, P["deephouse"])
    play_bar(eng, 0)
    eng.mix(levels={"6": 70}, save_as="break mix")
    play_bar(eng, 1)
    eng.mix(levels={"6": 110})
    play_bar(eng, 2)
    eng.arrange(sections=[{"bars": 2, "mix": "Break Mix"}, {"bars": 2, "mix": "flat"}], loop=True)
    play_bar(eng, 3)
    assert last_cc(eng, 6, 95) == 70
    play_bar(eng, 5)
    assert last_cc(eng, 6, 95) == 100 and last_cc(eng, 1, 95) == 100


# ---- clock and safety ---------------------------------------------------------------------

def test_clock_jitter_is_unchanged_with_transitions_and_level_ramps():
    port = TimedPort()
    eng, _ = make_engine(port)
    try:
        eng.play(P["techno"], bpm=240)
        wait_bar(eng, 2)
        base_end = eng.bar
        for t in range(1, 9):
            eng.set_param(t, 100, param="level")
        eng.play(P["deephouse"], bpm=240, transition="filter_swap", transition_bars=2, filter_from=127)
        eng.mix(levels={str(t): 60 + 5 * t for t in range(1, 9)}, pan={"hats": "left"}, bars=3)
        at = eng.bar + 1
        wait_bar(eng, at + 3)
        assert eng.pattern.name == "deephouse"
        eng.stop()
    finally:
        eng.shutdown()
    t = port.clock_times
    base = t[:base_end * BAR]
    busy = t[at * BAR:(at + 3) * BAR]
    assert len(busy) == 3 * BAR
    assert port.count("control_change", control=74) > 20 and port.count("control_change", control=95) > 20
    assert_jitter(base, busy, "transitions and mix")
    assert_safe(port)


def test_no_sysex_program_change_or_blocked_cc_from_transitions_and_mix(fake):
    eng, port = fake
    eng.label_tracks(tracks={"9": "riser"})
    pretend_playing(eng, P["deephouse"])
    play_bar(eng, 0)
    eng.mix(preset="auto", pan={"hats": "hard left"}, save_as="a")
    eng.play(P["techno"], transition="filter_swap", transition_bars=2, filter_from=127)
    for bar in range(1, 4):
        play_bar(eng, bar)
    eng.play(P["breaks"], transition="drop_swap")
    eng.mix(recall="a", bars=1)
    for bar in range(4, 6):
        play_bar(eng, bar)
    eng.play(P["soul"], transition="riser", transition_bars=1)
    eng.arrange(sections=[{"bars": 2, "transition": "filter_swap", "transition_bars": 1, "mix": "a"},
                          {"bars": 2, "transition": "riser", "transition_bars": 2}], loop=True)
    for bar in range(6, 12):
        play_bar(eng, bar)
    eng.stop()
    assert_safe(port)
    assert {m.control for m in port.messages if m.type == "control_change"} <= ALLOWED_CCS
    assert port.count("sysex") == port.count("program_change") == 0


# ---- tools, schemas, version --------------------------------------------------------------

def test_tools_carry_transition_and_mix(tool_engine):
    eng, port = tool_engine()
    assert call("whiplash_play_pattern", genre="deephouse", bpm=280)["success"]
    try:
        wait_bar(eng, 1)
        out = call("whiplash_play_pattern", genre="techno", transition="filter_swap", transition_bars=1)
        assert not out["success"] and "filter_from" in out["error"]
        out = call("whiplash_play_pattern", genre="techno", transition="drop_swap", transition_bars=2)
        assert out["success"] and out["transition"]["kind"] == "drop_swap" and out["mode"] == "queued"
        assert call("whiplash_status")["queued"]["transition"]["bars"] == 2
        out = call("whiplash_mix", levels={"bass": 90}, pan={"hats": "right"}, save_as="drop mix")
        assert out["success"] and out["levels"] == {"6": 90} and out["saved_mixes"] == ["drop mix"]
        assert not call("whiplash_mix", levels={"1": 200})["success"]
    finally:
        out = call("whiplash_stop")
    assert out["success"]


def test_schemas_describe_transitions_and_mix():
    play = schemas.SCHEMAS["whiplash_play_pattern"]["parameters"]["properties"]
    assert play["transition"]["enum"] == list(transition.KINDS) and play["transition_bars"]["maximum"] == 8
    section = schemas.SCHEMAS["whiplash_arrange"]["parameters"]["properties"]["sections"]["items"]["properties"]
    assert {"transition", "transition_bars", "filter_from", "mix"} <= set(section)
    mix = schemas.SCHEMAS["whiplash_mix"]
    assert "CC 95" in mix["description"] and "CC 90" in mix["description"] and len(mix["description"]) <= 400
    assert set(mix["parameters"]["properties"]) == {"levels", "pan", "preset", "bars", "save_as", "recall",
                                                       "force"}  # v0.7.0: the loudness guard
    assert tools.HANDLERS["whiplash_mix"]


def test_level_and_pan_ccs_are_the_reference_ones():
    assert ccmap.PARAMS["track_level"].cc == engine.LEVEL_CC == 95 and ccmap.PARAMS["pan"].cc == engine.PAN_CC == 90
    assert not {95, 90, 74} & ccmap.BLOCKED_CCS


def test_v062_manifest_order_and_skill():  # v0.7.0 pins the version number in test_v070.py
    import yaml
    for manifest in (yaml.safe_load(open(ROOT / "plugin.yaml"))["provides_tools"],
                     yaml.safe_load(open(ROOT / "docs" / "catalog-entry.yaml"))["capabilities"]["provides_tools"]):
        assert manifest.index("whiplash_mix") == manifest.index("whiplash_arrange") + 1
    skill = (ROOT / "skills" / "digitakt" / "SKILL.md").read_text()
    assert "whiplash_mix" in skill and "filter_swap" in skill