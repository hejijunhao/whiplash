"""v0.9.3 ontology O4: the arrangement grammar. Section types, energy per section, breakdown styles, fill_every,
enter/exit, then, the eight forms, and the moves (build, drop, breakdown, slam).

Fake and virtual ports only. Nothing here is a hardware result (docs/executing/ontology-v1-spec.md §8)."""
import hashlib
import json

import pytest

from whiplash import arrange, engine, form, genres, grooves, library, mutate, patterns, schemas, tools
from test_live import bar_events, pretend_playing
from test_whiplash import make_engine

P = patterns.PATTERNS


@pytest.fixture
def eng():
    e, port = make_engine()
    e.test_port = port
    yield e
    e.shutdown()


@pytest.fixture
def tool(monkeypatch):
    e, port = make_engine()
    monkeypatch.setattr(tools, "ENGINE", e)
    e.test_port = port
    yield e
    e.shutdown()


def call(name, **params):
    return json.loads(tools.HANDLERS[name](params))


def playing(eng, genre="deephouse"):
    pretend_playing(eng, P[genre])
    bar_events(eng, 0)
    return eng


def hits(eng, bar, track):
    return [(s, n) for s, t, n, *_ in bar_events(eng, bar) if t == track]


def ccs(port, control):
    return [(m.channel + 1, m.value) for m in port.messages if m.type == "control_change" and m.control == control]


def compiled(name, genre=None):
    entry = form.FORMS[name]
    raw, warnings = form.expand(form.form_sections(entry), genres.GENRES.get(genre), entry.energy_filter, entry)
    return arrange.sections(raw, internal=True), warnings


# ---- pure: forms, types, styles, moves (spec §6.5) ------------------------------------------------------------------

@pytest.mark.parametrize("name", [n for n, f in form.FORMS.items() if not f.preset])
def test_every_library_form_compiles_within_the_limits(name):
    entry = form.FORMS[name]
    for genre in (entry.genre if entry.genre in genres.GENRES else None, "techno", None):
        secs, warnings = compiled(name, genre)
        assert not warnings and all(s.bars % 8 == 0 for s in secs), name
        assert len(secs) <= arrange.SECTIONS_MAX and sum(s.bars for s in secs) <= arrange.TOTAL_BARS_MAX
        assert all(s.bars <= arrange.SECTION_BARS_MAX for s in secs)


def test_each_genre_record_names_a_form_and_a_style_that_exist():
    for record in genres.GENRES.values():
        assert record.form in form.FORMS and record.breakdown in form.BREAKDOWNS
        assert library.resolve("form", record.name.replace(".", " ")).name == record.form


def test_a_form_string_takes_each_types_defaults():
    secs = arrange.sections(form.expand(form.parse("intro 16, build 8, drop 16"))[0], internal=True)
    intro, build, drop = secs
    assert (intro.name, intro.energy, intro.tracks, intro.fill_every) == ("intro", 1, ("kick", "hats"), 8)
    assert (build.energy, build.tracks, build.drop) == ("rising", ("kick", "hats", "perc", "music"), ("kick",))
    assert build.fill == "default" and build.fill_name == "snare.roll" and build.enter == (("hats", 4),)
    assert not build.ramps  # the music filter only when opted in (Q-A1)
    assert (drop.energy, drop.tracks, drop.fill_every) == (5, None, 8)
    assert [s.name for s in arrange.sections(form.expand(form.parse("drop, drop, outro"))[0], internal=True)] == \
        ["drop", "drop 2", "outro"]


def test_a_section_off_the_8_bar_grid_warns_and_still_compiles():
    raw, warnings = form.expand(form.parse("intro 12, drop 16"))
    assert len(warnings) == 1 and "intro is 12 bars" in warnings[0]
    assert [s.bars for s in arrange.sections(raw, internal=True)] == [12, 16]


def test_the_build_move_is_the_spec_build_then_a_drop():
    for genre, filt in (("deephouse", False), ("techno", False), ("progressivehouse", True), ("melodictechno", True)):
        items, on = form.move_sections("build", 16, genres.GENRES[genre])
        assert on is filt
        build, drop = arrange.sections(form.expand(items, genres.GENRES[genre], on)[0], internal=True)
        assert (build.bars, build.enter, build.drop, build.fill_name) == (16, (("hats", 12),), ("kick",), "snare.roll")
        ramps = [(r.track, r.param, r.start, r.to, r.bars, r.curve) for r in build.ramps]
        assert ramps == ([("music", "filter_freq", 20, 127, 16, "exp")] if filt else [])
        assert (drop.bars, drop.energy, drop.fill_every, drop.crash, drop.ramps) == (16, 5, 8, True, ())


def test_moves_take_their_default_bars_and_slam_refuses_bars():
    assert form.move_sections("build", None)[0][0]["bars"] == 8
    assert form.move_sections("breakdown", None)[0][0]["bars"] == 16
    assert form.move_sections("drop", 4)[0][0]["bars"] == 4
    assert [s["name"] for s in form.move_sections("slam", None)[0]] == ["slam", "all in"]
    with pytest.raises(form.FormError, match="bars is for build"):
        form.move_sections("slam", 4)
    with pytest.raises(form.FormError, match="build, drop, breakdown, slam"):
        form.move_name("explode")


@pytest.mark.parametrize("style,check", [
    ("kick_bass_out", lambda s: s.mute == ("kick", "bass") and s.style is None),
    ("kick_drop", lambda s: s.mute == ("kick",)),
    ("filter_low_end", lambda s: s.tracks is None and s.style == "filter_low_end"),
    ("filter_bass", lambda s: s.style == "filter_low_end"),
    ("reduce_drums", lambda s: s.energy == 1 and s.style == "reduce_drums"),
    ("subtract_one", lambda s: s.tracks is None and s.style == "subtract_one"),
])
def test_each_breakdown_style_compiles_to_its_row(style, check):
    record = next(g for g in genres.GENRES.values() if g.breakdown == style) if style != "filter_bass" else None
    sec = arrange.sections(form.expand([{"type": "breakdown", "bars": 16}], record)[0], internal=True)[0]
    assert sec.energy is not None and check(sec), sec


def test_bad_forms_say_what_exists():
    with pytest.raises(form.FormError, match="intro, groove, build, breakdown, drop, outro"):
        form.parse("intro 16, chorus2 8")
    with pytest.raises(form.FormError, match="adds up to 576 bars"):
        form.parse(", ".join(["groove 64"] * 9))
    with pytest.raises(arrange.ArrangeError, match=r"bar 20 is outside build \(8 bars\)"):
        arrange.sections(form.expand([{"type": "build", "enter": {"hats": 20}}])[0], internal=True)
    with pytest.raises(arrange.ArrangeError, match="can't both enter and exit"):
        arrange.sections([{"bars": 8, "enter": {"hats": 2}, "exit": {"hats": 4}}])
    with pytest.raises(arrange.ArrangeError, match="energy must be 1-5"):
        arrange.sections([{"bars": 8, "energy": 7}])
    with pytest.raises(arrange.ArrangeError, match="unknown key"):
        arrange.sections([{"bars": 8, "_style": "subtract_one"}])  # form.py's own keys aren't public


def test_section_fill_takes_a_fill_name():
    sec = arrange.sections([{"bars": 8, "fill": "snare flam roll"}])[0]
    assert sec.fill == "default" and sec.fill_name == "snare.flam_roll"
    assert arrange.sections([{"bars": 8, "fill": "kick"}])[0].fill == ("kick",)  # a group word stays a group
    with pytest.raises(arrange.ArrangeError, match="fill name"):
        arrange.sections([{"bars": 8, "fill": "kaboom"}])


def test_energy_filter_targets_follow_the_levels():
    raw, _ = form.expand(form.parse("intro 8, build 8, drop 8, breakdown 8"), None, True)
    secs = arrange.sections(raw, internal=True)
    got = [[(r.start, r.to) for r in s.ramps] for s in secs]
    assert got == [[(127, 48)], [(20, 127)], [], [(127, 72)]]


# ---- engine (spec §6.5) ---------------------------------------------------------------------------------------------

def test_fill_every_fills_bars_8_and_16_only(eng):
    playing(eng)
    eng.arrange(sections=[{"name": "groove", "bars": 16, "fill_every": 8}])
    filled = []
    for bar in range(1, 17):
        bar_events(eng, bar)
        if eng.bar_fills[1]:
            filled.append(bar - 0)
    assert filled == [8, 16]


def test_enter_unmutes_the_hats_exactly_at_bar_13_of_16(eng):
    playing(eng)
    out = eng.arrange(sections=[{"name": "build", "bars": 16, "enter": {"hats": -4}}])
    assert out["sections"][0]["enter"] == {"hats": 13}
    for bar in range(1, 17):
        bar_events(eng, bar)
        assert ({4, 5} <= eng.muted) is (bar < 13), bar


def test_exit_mutes_a_group_from_its_bar(eng):
    playing(eng)
    eng.arrange(sections=[{"name": "g", "bars": 8, "exit": {"bass": 5}}])
    for bar in range(1, 9):
        bar_events(eng, bar)
        assert (6 in eng.muted) is (bar >= 5)


def test_then_continue_keeps_the_beat_and_lifts_every_arrangement_mute(eng):
    playing(eng)
    out = eng.arrange(sections=[{"name": "a", "bars": 2, "tracks": ["kick"]}], then="continue")
    assert out["then"] == "continue" and "keeps playing from bar 3" in out["ends"]
    bar_events(eng, 1)
    assert eng.muted >= {4, 6, 7}
    assert bar_events(eng, 3)  # not None: the run goes on
    assert eng.muted == set() and eng._arr is None
    assert not [m for m in eng.test_port.messages if m.type == "stop"]


def test_loop_true_is_then_loop(eng):
    playing(eng)
    a = eng.arrange(sections=[{"bars": 1, "tracks": ["kick"]}, {"bars": 1}], loop=True)
    assert a["then"] == "loop" and a["loop"] is True
    with pytest.raises(engine.WhiplashError, match="disagree"):
        eng.arrange(sections=[{"bars": 1}], loop=True, then="stop")


def test_section_energy_lands_on_its_bar_and_continue_brings_the_old_level_back(eng):
    playing(eng, "techno")
    out = eng.arrange(form="intro 8, drop 8", then="continue")
    assert out["sections"][0]["energy"] == 1 and out["sections"][1]["energy"] == 5 and "energy_note" in out
    assert "energy goes back to 3" in out["ends"]
    level = {b: (bar_events(eng, b), eng._groove_info()["energy"])[1] for b in range(1, 18)}
    assert level[1] == level[8] == 1 and level[9] == level[16] == 5 and level[17] == 3
    assert eng._groove_info()["name"] == "techno.classic"
    assert not [m for m in eng.test_port.messages if m.type in ("stop", "start")]


def test_energy_3_on_a_classic_groove_is_todays_pattern(eng):
    playing(eng, "deephouse")
    before = [bar_events(eng, b) for b in range(1, 5)]
    eng.arrange(sections=[{"bars": 4, "energy": 3}])
    with eng._lock:
        eng.bar = 4
    assert [bar_events(eng, b) for b in range(5, 9)] == before


def test_a_rising_build_steps_2_3_4(eng):
    playing(eng, "techno")
    eng.arrange(sections=[{"type": "build", "bars": 8, "tracks": "all"}])
    got = [(bar_events(eng, b), eng._groove_info()["energy"])[1] for b in range(1, 9)]
    assert got == [2, 2, 2, 3, 3, 4, 4, 4]  # steps on bars 1, 4 and 6


def test_a_move_replaces_the_arrangement_and_undo_brings_it_back_in_its_section(eng):
    playing(eng)
    eng.arrange(sections=[{"name": "a", "bars": 8, "tracks": ["kick"]}, {"name": "b", "bars": 8}])
    for bar in (1, 2, 3):
        bar_events(eng, bar)
    out = eng.arrange(move="breakdown", bars=8)
    assert out["move"] == "breakdown" and out["lands_at_bar"] == 4 and out["replaced_arrangement"] == "custom"
    assert out["then"] == "continue"
    bar_events(eng, 4)
    assert eng.status()["arrangement"]["current"]["section"] == "breakdown"
    eng.undo()
    bar_events(eng, 5)
    st = eng.status()["arrangement"]
    assert st["name"] == "custom" and st["current"]["section"] == "a" and st["current"]["next_at_bar"] == 9
    assert eng.muted >= {4, 6}  # section a: only the kick plays
    bar_events(eng, 9)
    assert eng.status()["arrangement"]["current"]["section"] == "b"


def test_a_move_needs_a_beat(eng):
    with pytest.raises(engine.WhiplashError, match="nothing is playing"):
        eng.arrange(move="build")


def test_techno_breakdown_mutes_the_kick_and_keeps_the_bass(eng):
    playing(eng, "techno")
    out = eng.arrange(move="breakdown", bars=8)
    assert out["sections"][0]["breakdown"] == "kick_drop"
    bar_events(eng, 1)
    assert 1 in eng.muted and 6 not in eng.muted


def test_techhouse_breakdown_closes_and_reopens_the_bass_filter_only(eng):
    playing(eng, "techhouse")
    port = eng.test_port
    out = eng.arrange(sections=[{"type": "breakdown", "bars": 8}, {"name": "back", "bars": 2}])
    assert out["sections"][0]["breakdown"] == "filter_low_end" and "breakdown_note" in out
    bar_events(eng, 1)
    assert list(eng._ramps) == [(6, engine.FILTER_CC)] and 6 not in eng.muted
    ramp = eng._ramps[(6, engine.FILTER_CC)]
    assert (ramp.start, ramp.end, ramp.total) == (127, 40, 2 * engine.TICKS_PER_BAR)
    assert {t for t, _ in ccs(port, engine.FILTER_CC)} == {6}  # the bass only
    assert eng._restore == {(6, engine.FILTER_CC): 127}
    for bar in range(2, 9):
        bar_events(eng, bar)
    with eng._lock:
        eng._cc_values[(5, engine.FILTER_CC)] = 40  # where the closing ramp ends (no clock ticks here)
    bar_events(eng, 9)
    reopen = eng._ramps[(6, engine.FILTER_CC)]
    assert (reopen.start, reopen.end, reopen.owner) == (40, 127, engine.REOPEN) and eng._restore == {}


def test_minimal_breakdown_subtracts_its_busiest_element(eng):
    playing(eng, "minimal.house")
    eng.arrange(move="breakdown", bars=8)
    bar_events(eng, 1)
    st = eng.status()["arrangement"]
    assert st["subtracted"] == 8 and eng.muted == {8}


def test_tropical_breakdown_drops_the_drums_to_energy_1_and_keeps_the_chords(eng):
    playing(eng, "tropicalhouse")
    eng.arrange(move="breakdown", bars=8)
    events = bar_events(eng, 1)
    assert eng._groove_info()["energy"] == 1
    tracks = {t for _, t, *_ in events if t not in eng.muted}
    assert {6, 7} <= tracks and 3 not in tracks


def test_drop_move_crashes_on_a_labelled_cymbal(eng):
    playing(eng)
    eng.label_tracks({"9": "crash cymbal"})
    out = eng.arrange(move="drop", bars=8)
    assert out["sections"][0]["crash"] == [9] and out["sections"][0]["energy"] == 5
    first = [e for e in bar_events(eng, 1) if e[1] == 9]
    assert first[0][:5] == (0, 9, patterns.DRUM, 112, 8)  # the crash on the one, over whatever 9 plays
    assert not [e for e in bar_events(eng, 2) if e[1] == 9 and e[3] == 112]


def test_drop_move_without_a_cymbal_says_so(eng):
    playing(eng)
    out = eng.arrange(move="drop")
    assert "no cymbal" in out["sections"][0]["crash"]


def test_build_move_on_deep_house_plays_the_spec_sentence(eng):
    playing(eng)
    out = eng.arrange(move="build", bars=16)
    assert [s["name"] for s in out["sections"]] == ["build", "drop"] and out["total_bars"] == 32
    build = {b: bar_events(eng, b) for b in range(1, 17)}
    kick16 = [e for e in build[16] if e[1] == 1]
    assert kick16 == []  # the kick sits out bar 16
    assert len([e for e in build[16] if e[1] == 2 and e[0] >= 8]) == 8  # the rim rolls through the second half
    assert hits(eng, 17, 1)[0][0] == 0  # the drop lands on the one
    assert eng._groove_info()["energy"] == 5


def test_outro_thins_the_hats_over_its_last_bars_and_restores_them(eng):
    playing(eng)
    eng.arrange(sections=[{"type": "outro", "bars": 16}, {"name": "after", "bars": 1}])
    for bar in range(1, 9):  # deep house at energy 1: kick and the open hat (track 5)
        bar_events(eng, bar)
        assert eng._density.get(5, 0) == 0
    bar_events(eng, 9)
    assert eng._density[5] == pytest.approx(-0.3)
    for bar in range(10, 18):
        bar_events(eng, bar)
    assert eng._density.get(5, 0) == 0


def test_section_named_fill_plays_on_its_roles(eng):
    playing(eng, "house")
    eng.arrange(sections=[{"bars": 8, "fill_every": 4, "fill": "snare.flam_roll"}])
    names = {}
    for bar in range(1, 9):
        with eng._lock:
            pending = dict(eng._fill_names.get(bar, {}))
        bar_events(eng, bar)
        if eng.bar_fills[1]:
            names[bar] = sorted(eng.bar_fills[1])
    assert names == {4: [2], 8: [2]}


def test_house_jack_form_plays_tom_runs_or_their_fallback(eng):
    playing(eng, "house")
    out = eng.arrange(form="house jack")
    assert out["form"] == "house_jack" and out["sections"][0]["fill"] == "perc.tom_run"


def test_a_form_by_genre_word_and_a_preset_form(eng):
    playing(eng, "techno")
    assert eng.arrange(form="techno")["arrangement"] == "techno_plateau"
    club = eng.arrange(form="club")
    assert club["arrangement"] == "club" and club["then"] == "stop"


def test_bad_arrange_calls_change_nothing(eng):
    playing(eng)
    for kw, match in ((dict(form="intro 16", move="build"), "exactly one"),
                      (dict(form="intro 16", bars=8), "bars is the length of a move"),
                      (dict(sections=[{"bars": 8}], energy_filter=True), "energy_filter is for"),
                      (dict(move="build", then="loop"), "a move ends"),
                      (dict(form="intro 16, wobble 8"), "unknown section type"),
                      (dict(form="nonsense form name"), "unknown form")):
        with pytest.raises(engine.WhiplashError, match=match):
            eng.arrange(**kw)
    assert eng._arr is None and eng.muted == set()


def test_clear_after_a_section_energy_lands_the_old_level_on_the_next_bar(eng):
    playing(eng, "techno")
    eng.arrange(form="drop 8")
    bar_events(eng, 1)
    assert eng._groove_info()["energy"] == 5
    out = eng.arrange(clear=True)
    assert out["energy_back_to"] == 3 and eng._groove_info()["energy"] == 5  # not mid-bar
    bar_events(eng, 2)
    assert eng._groove_info()["energy"] == 3


# ---- tools, library -------------------------------------------------------------------------------------------------

def test_list_library_lists_forms_and_moves(tool):
    out = call("whiplash_list_library", kind="form")
    names = [e["name"] for e in out["entries"]]
    assert set(names) == set(form.FORMS) and names == sorted(names)
    td = next(e for e in out["entries"] if e["name"] == "techhouse_dj")
    assert td["bars"] == 168 and td["sections"].startswith("intro 32, build 16")
    assert [e["name"] for e in call("whiplash_list_library", kind="form", genre="minimal techno")["entries"]] == \
        ["minimal_long"]
    moves = call("whiplash_list_library", kind="move")
    assert [e["name"] for e in moves["entries"]] == ["breakdown", "build", "drop", "slam"]
    assert library.resolve("move", "build up").name == "build"
    assert tool.test_port.messages == []


def test_arrange_tool_takes_move_and_bars(tool):
    playing(tool)
    out = call("whiplash_arrange", move="build", bars=16)
    assert out["success"] is not False and out["move"] == "build" and out["sections"][0]["enter"] == {"hats": 13}


def test_schema_offers_the_new_keys():
    props = schemas.SCHEMAS["whiplash_arrange"]["parameters"]["properties"]
    assert {"form", "move", "bars", "then", "energy_filter"} <= set(props)
    assert props["move"]["enum"] == list(form.MOVES)
    items = props["sections"]["items"]["properties"]
    assert {"type", "energy", "fill_every", "enter", "exit"} <= set(items)
    assert not any(k.startswith("_") for k in items)


def test_crash_fill_is_a_drum_hit_on_the_one():
    assert mutate.fill("cymbal", [], "cymbal.crash") == [(0, patterns.DRUM, 112, 8, 0.0)]
    assert "cymbal.crash" in grooves.FILLS and grooves.FILLS["cymbal.crash"].roles == {"cymbal"}


# ---- equivalence: pre-0.9.3 arrangements play bit for bit (digests taken on main at 08e67cc) ------------------------

DIGESTS = {
    ("deephouse", "club"): "aed59d503555b0d3", ("deephouse", "short_demo"): "e595156463ef5bfc",
    ("deephouse", "short_demo_loop"): "32f2231d8fe53c40", ("deephouse", "sections"): "1278d17543a8be6e",
    ("techno", "club"): "10825de8cb6e809d", ("techno", "short_demo"): "394e7d4478b39d71",
    ("techno", "short_demo_loop"): "1c455d198ddea965", ("techno", "sections"): "6298f5ba62bd077c",
    ("house", "club"): "9449099fca81b69c", ("house", "short_demo"): "0c3592efebc71dc6",
    ("house", "short_demo_loop"): "b48eed7f03378670", ("house", "sections"): "d51e508218a9a35c",
}
CASES = {
    "club": dict(preset="club"),
    "short_demo": dict(preset="short_demo"),
    "short_demo_loop": dict(preset="short_demo", loop=True),
    "sections": dict(sections=[{"name": "intro", "bars": 2, "tracks": ["kick", "hats"], "fill": True},
                               {"name": "b", "bars": 4, "mute": ["bass"], "drop": ["kick"],
                                "ramps": [{"track": "music", "param": "filter_freq", "from": 20, "to": 127}],
                                "transition": "filter_swap", "filter_from": 100},
                               {"name": "c", "bars": 2, "chords": "i VI", "fill": ["perc"]}], loop=True),
}


@pytest.mark.parametrize("genre,case", sorted(DIGESTS))
def test_presets_and_plain_sections_play_exactly_as_before(genre, case):
    eng, port = make_engine()
    try:
        pretend_playing(eng, P[genre])
        bar_events(eng, 0)
        eng.arrange(**CASES[case])
        h = hashlib.sha256()
        for bar in range(1, 100):
            with eng._lock:
                ev = eng._bar_boundary(bar)
            if ev is None:
                h.update(b"end")
                break
            h.update(repr(sorted((s, *e) for s, es in ev.items() for e in es)).encode())
            h.update(repr(sorted(eng.muted)).encode())
        h.update(repr([(m.type, getattr(m, "channel", None), getattr(m, "control", None), getattr(m, "value", None))
                       for m in port.messages]).encode())
        assert h.hexdigest()[:16] == DIGESTS[(genre, case)]
    finally:
        eng.shutdown()


def test_replacing_an_energy_form_with_plain_sections_puts_the_energy_back(eng):
    playing(eng, "techno")
    eng.arrange(form="drop 8")
    bar_events(eng, 1)
    assert eng._groove_info()["energy"] == 5
    out = eng.arrange(sections=[{"bars": 4, "tracks": "all"}])
    assert out["replaced"] is True and eng._groove_info()["energy"] == 5  # lands on the bar line, not mid-bar
    bar_events(eng, 2)
    assert eng._groove_info()["energy"] == 3
