"""v0.5.3: kit map labels, one-call start with per-track setup, techhouse, leaner tool descriptions."""
import json
import statistics
from pathlib import Path

import pytest

import whiplash
from whiplash import engine, kitmap, patterns, schemas, tools, view
from test_whiplash import call, make_engine, tool_engine  # noqa: F401  (fixture)
from test_live import bar_events, pretend_playing, timeline, wait_bar

P = patterns.PATTERNS
ROOT = Path(whiplash.__path__[0])


@pytest.fixture
def fake():
    eng, port = make_engine()
    yield eng, port
    eng.shutdown()


def tracks_in(events):
    return {e[1] for e in events}


def notes_on(events, track):
    return [e[2] for e in events if e[1] == track]


# ---- 1. kit map: vocabulary ------------------------------------------------

@pytest.mark.parametrize("text, role", [
    ("kick", "kick"), ("808 kick", "kick"), ("bass drum", "kick"), ("tuned cymbal", "cymbal"), ("ride", "cymbal"),
    ("dirty bass", "bass"), ("sub", "bass"), ("pad", "pad"), ("warm pad", "pad"), ("open hat", "open hat"),
    ("hi-hat", "closed hat"), ("hats", "closed hat"), ("snare", "snare"), ("rimshot", "rim"), ("clap", "clap"),
    ("toms", "perc"), ("stab", "stab"), ("chords", "chord"), ("synth Phil likes", "lead"), ("riser", "fx"),
    ("Closed_Hat", "closed hat"), ("a door slam", "other"),
])
def test_free_text_maps_to_the_role_vocabulary(text, role):
    assert kitmap.classify(text) == role
    assert role in kitmap.ROLES


def test_every_generated_role_is_in_the_vocabulary():
    for pattern in P.values():
        for track, role in pattern.roles.items():
            assert kitmap.generated_role(role) != "other", (pattern.name, track, role)


# ---- 1. kit map: routing -----------------------------------------------------

def test_a_kick_labelled_on_track_9_receives_the_kick_part(fake):
    eng, _ = fake
    eng.label_tracks(tracks={"9": "kick"})
    pretend_playing(eng, P["techno"])
    events = bar_events(eng, 0)
    assert [e[0] for e in events if e[1] == 9] == [0, 4, 8, 12]
    assert 1 not in tracks_in(events)  # the pattern's own kick track gets nothing: the kick moved
    assert eng.tracks_summary()["9"]["role"] == "kick" and eng.tracks_summary()["9"]["kit_role"] == "kick"


def test_unlabelled_roles_fall_back_to_the_default_layout(fake):
    eng, _ = fake
    eng.label_tracks(tracks={"1": "kick"})
    pretend_playing(eng, P["techno"])
    events = bar_events(eng, 0)
    assert tracks_in(events) == set(range(1, 9))
    status = eng.status()["tracks"]
    assert status["1"]["role"] == "kick" and "kit_role" in status["1"]
    assert status["6"]["role"] == "bass (assumed)" and "kit_role" not in status["6"]
    assert events == bar_events(engine_without_labels(P["techno"]), 0)


def engine_without_labels(pattern):
    eng, _ = make_engine()
    return pretend_playing(eng, pattern)


def test_a_cymbal_track_never_gets_chords(fake):
    eng, _ = fake
    eng.label_tracks(tracks={"7": "tuned cymbal", "5": "pad"})
    pretend_playing(eng, P["deephouse"])
    events = bar_events(eng, 0)
    assert all(n == patterns.DRUM for n in notes_on(events, 7))  # at most an unpitched drum part, never chords
    raw = bar_events(engine_without_labels(P["deephouse"]), 0)
    assert notes_on(events, 5) == notes_on(raw, 7)  # the minor chords moved onto the pad
    assert notes_on(events, 8) == notes_on(raw, 8)  # track 8 is unlabelled: its chords stay
    tracks = eng.status()["tracks"]
    assert tracks["7"]["role"] == "tuned cymbal" and tracks["7"]["kit_role"] == "cymbal"
    assert tracks["5"]["role"] == "pad" and tracks["5"]["pitch"] is not None


def test_cymbal_and_fx_tracks_take_no_melodic_part_in_any_genre():
    labels = {7: ("cymbal", "cymbal"), 8: ("fx", "noise")}
    for pattern in P.values():
        routed = kitmap.route(pattern, labels)
        for track in (7, 8):
            assert not patterns.is_melodic(routed.bars.get(track, [[]])), pattern.name


def test_parts_for_roles_nobody_has_are_dropped_and_extra_labels_stay_silent():
    labels = {6: ("perc", "conga"), 9: ("lead", "lead synth"), 10: ("bass", "bass"), 11: ("bass", "sub")}
    info = kitmap.plan(P["techno"], labels)
    assert info["moves"][6] == 10  # the bass part follows the bass label off its default track
    assert info["moves"][7] == 9  # no stab track: the stab goes to the lead, its close role
    assert info["moves"][8] == 6  # techno's perc goes to the conga on 6
    assert info["silent"] == [11] and info["dropped"] == {}
    deep = kitmap.plan(P["deephouse"], {5: ("pad", "pad"), 7: ("cymbal", "cymbal")})
    assert deep["moves"][5] == 7  # deep house's open hat lands on the cymbal (close role), not dropped


def test_routing_keeps_the_register_and_reports_it(fake):
    eng, _ = fake
    eng.label_tracks(tracks={"12": "dirty bass"})
    pretend_playing(eng, P["techno"])
    pitch = eng.tracks_summary()["12"]["pitch"]
    assert pitch["register_shift"] == 12 and pitch["low"] == 53


def test_labels_while_playing_apply_on_the_next_bar(fake):
    eng, _ = fake
    pretend_playing(eng, P["techno"])
    assert 9 not in tracks_in(bar_events(eng, 0))
    out = eng.label_tracks(tracks={"9": "kick"})
    assert out["applies"] == "next bar" and out["at_bar"] == 1 and out["routing"]["parts"]["9"].startswith("kick")
    assert 9 not in eng.pattern.bars  # nothing moves until the sequencer reaches the bar line
    events = bar_events(eng, 1)
    assert 9 in tracks_in(events) and 1 not in tracks_in(events)


def test_relabelling_keeps_density_swing_and_humanize(fake):
    eng, _ = fake
    pretend_playing(eng, P["techno"])
    eng.mutate_swing(62)
    eng.mutate_humanize(0.5)
    eng.mutate_density([4], -0.5)
    eng.label_tracks(tracks={"9": "kick"})
    bar_events(eng, 1)
    assert eng.swing == 0.62 and eng.humanize == 0.5 and eng.mutations()["density"] == {"4": -0.5}


def test_map_survives_stop_and_switches_and_reset_clears_it(fake):
    eng, _ = fake
    eng.label_tracks(tracks={"9": "kick"}, slots={"11": "synth Phil likes"})
    eng.play(P["techno"], bpm=300)
    wait_bar(eng, 1)
    eng.play(P["soul"])  # queued switch
    wait_bar(eng, 3)
    assert eng.pattern.name == "soul" and 9 in eng.pattern.bars and 1 not in eng.pattern.bars
    eng.stop()
    assert eng.kit()["tracks"] == {"9": {"role": "kick", "label": "kick"}}
    assert eng.kit()["slots"] == {"11": "synth Phil likes"}
    assert 9 in eng.pattern.bars  # after stop the reloaded pattern still follows the map
    out = eng.label_tracks(reset=True)
    assert out["kit"] == {"tracks": {}, "slots": {}} and 1 in eng.pattern.bars and 9 not in eng.pattern.bars


def test_labels_merge_and_null_removes_one(fake):
    eng, _ = fake
    eng.label_tracks(tracks={"5": "pad", "7": "cymbal"}, slots={"9": "dirty bass"})
    eng.label_tracks(tracks={"7": None, "8": {"role": "chord", "label": "Rhodes"}}, slots={"9": ""})
    assert eng.kit() == {"tracks": {"5": {"role": "pad", "label": "pad"},
                                    "8": {"role": "chord", "label": "Rhodes"}}, "slots": {}}
    out = eng.label_tracks(reset=True, tracks={"1": "kick"})
    assert out["kit"]["tracks"] == {"1": {"role": "kick", "label": "kick"}}


@pytest.mark.parametrize("kwargs", [
    {}, {"tracks": {"17": "kick"}}, {"tracks": {"0": "kick"}}, {"tracks": ["kick"]}, {"tracks": {"3": 5}},
    {"tracks": {"3": {"role": "banjo"}}}, {"tracks": {"3": {"colour": "red"}}}, {"tracks": {"3": "x" * 61}},
    {"tracks": {"3": "kick\x00"}}, {"slots": {"128": "pad"}}, {"slots": {"-1": "pad"}}, {"slots": {"5": 7}},
    {"tracks": {"5": "pad", "99": "kick"}}, {"reset": "maybe"},
])
def test_bad_labels_change_nothing(fake, kwargs):
    eng, port = fake
    eng.label_tracks(tracks={"5": "pad"}, slots={"9": "bass"})
    pretend_playing(eng, P["techno"])
    before, sent = eng.kit(), len(port.messages)
    with pytest.raises(engine.WhiplashError):
        eng.label_tracks(**kwargs)
    assert eng.kit() == before and len(port.messages) == sent and not eng._kit_dirty


def test_labelling_sends_nothing_to_the_unit(fake):
    eng, port = fake
    pretend_playing(eng, P["techno"])
    sent = len(port.messages)
    eng.label_tracks(tracks={"7": "cymbal"}, slots={"11": "synth"})
    bar_events(eng, 1)
    assert len(port.messages) == sent


def test_transpose_targets_follow_the_map(fake):
    eng, _ = fake
    eng.label_tracks(tracks={"10": "bass"})
    pretend_playing(eng, P["techno"])
    out = eng.set_transpose(10, octaves=1)
    assert out["pitch"]["low"] == 65
    with pytest.raises(engine.WhiplashError, match="plays nothing"):
        eng.set_transpose(6, octaves=1)  # the bass moved off track 6


def test_slot_labels_echo_in_results(tool_engine):
    eng, _ = tool_engine()
    call("whiplash_label_tracks", slots={"11": "synth Phil likes"}, tracks={"6": "bass"})
    out = call("whiplash_select_sample", track=6, slot=11)
    assert out["success"] and out["slot_label"] == "synth Phil likes"
    assert "slot_label" not in call("whiplash_select_sample", track=6, slot=12)
    assert call("whiplash_set_param", track=6, param="sample_slot", value=11)["slot_label"] == "synth Phil likes"
    status = call("whiplash_status")
    assert status["tracks"]["6"]["slot_label"] == "synth Phil likes" and status["tracks"]["6"]["role"] == "bass"
    assert status["roles_assumed"] is False and "whiplash_label_tracks" in status["kit_note"]
    assert status["kit"]["slots"] == {"11": "synth Phil likes"}


def test_label_tool_reports_routing_and_errors(tool_engine):
    tool_engine()
    out = call("whiplash_label_tracks", tracks={"7": "tuned cymbal", "5": "pad"})
    assert out["success"] and out["applies"] == "next whiplash_play_pattern" and "routing" not in out
    play = call("whiplash_play_pattern", genre="deephouse", bpm=300)
    assert play["roles_assumed"] is False and play["tracks"]["7"]["role"] == "tuned cymbal"
    out = call("whiplash_label_tracks", tracks={"9": "kick"})
    assert out["routing"]["pattern"] == "deephouse" and out["routing"]["parts"]["9"].startswith("kick")
    bad = call("whiplash_label_tracks", tracks={"20": "kick"})
    assert bad["success"] is False and "1-16" in bad["error"]
    call("whiplash_stop")


def test_view_lanes_use_the_labels(fake):
    eng, _ = fake
    eng.label_tracks(tracks={"7": "tuned cymbal", "9": "kick"})
    pretend_playing(eng, P["deephouse"])
    lanes = {lane["track"]: lane for lane in view.snapshot(eng)["lanes"]}
    assert lanes[9]["role"] == "kick" and 1 not in lanes
    assert lanes[7]["role"] == "tuned cymbal" and not lanes[7]["melodic"]
    json.dumps(view.snapshot(eng))


# ---- 2. one-call start: per-track setup ---------------------------------------

def first_note_index(messages, channel):
    return next(i for i, m in enumerate(messages) if m.type == "note_on" and m.channel == channel)


def test_setup_ccs_go_out_once_before_start_and_the_first_note(fake):
    eng, port = fake
    out = eng.play(P["techno"], bpm=300, tracks={"6": {"slot": 9, "tune": 76, "transpose": -12}, "4": {"mute": True}})
    assert out["setup"][6] == {"slot": 9, "tune": 76, "transpose": -12}
    wait_bar(eng, 1)
    eng.stop()
    msgs = [m for m in port.messages if m.type != "clock"]
    ccs = [(i, m.channel, m.control, m.value) for i, m in enumerate(msgs) if m.type == "control_change"
           and m.control in (16, 19)]
    assert [c[1:] for c in ccs] == [(5, 19, 9), (5, 16, 76)]  # once each, slot first
    start = next(i for i, m in enumerate(msgs) if m.type == "start")
    assert all(i < start < first_note_index(msgs, 5) for i, *_ in ccs)
    assert not any(m.type == "note_on" and m.channel == 3 for m in msgs)  # track 4 muted from the start
    assert {m.note for m in msgs if m.type == "note_on" and m.channel == 5} == {41}  # 53 - 12


def test_setup_lands_at_the_switch_bar_when_queued(fake):
    eng, port = fake
    eng.play(P["techno"], bpm=300)
    wait_bar(eng, 1)
    out = eng.play(P["deephouse"], tracks={"7": {"slot": 3, "tune": 70}, "2": {"mute": True}})
    at = out["switch_at_bar"]
    assert out["setup"][7] == {"slot": 3, "tune": 70} and 2 not in eng.muted  # nothing changes before the bar
    wait_bar(eng, at + 1)
    eng.stop()
    line = timeline(port)
    ccs = [(bar, m.control, m.value) for bar, _, m in line
           if m.type == "control_change" and m.channel == 6 and m.control in (16, 19)]
    assert ccs == [(at, 19, 3), (at, 16, 70)]
    sent_at = max(clocks for bar, clocks, m in line if m.type == "control_change" and m.channel == 6
                  and m.control in (16, 19))
    first = min(clocks for bar, clocks, m in line if m.type == "note_on" and m.channel == 6 and bar >= at)
    assert sent_at <= first
    assert not any(m.type == "note_on" and m.channel == 1 and bar > at for bar, _, m in line)


def test_setup_cc_replaces_a_running_ramp_on_the_same_param(fake):
    eng, _ = fake
    eng.play(P["techno"], bpm=300)
    eng.ramp(6, 100, param="tune", start=64, bars=16)
    eng.play(P["deephouse"], tracks={"6": {"tune": 52}})
    wait_bar(eng, 2)
    assert eng.ramps() == [] and eng._cc_values[(5, 16)] == 52
    eng.stop()


@pytest.mark.parametrize("tracks", [
    {"6": {"slot": 128}}, {"6": {"slot": -1}}, {"6": {"slot": 1.5}}, {"17": {"slot": 1}}, {"6": {"volume": 3}},
    {"6": 9}, ["6"], {"6": {"transpose": 99}}, {"6": {"mute": "maybe"}}, {"6": {"tune": 200}},
    {"6": {"slot": 9}, "x": {"slot": 1}},
])
def test_a_bad_track_entry_rejects_the_whole_call(fake, tracks):
    eng, port = fake
    eng.play(P["techno"], bpm=300)
    wait_bar(eng, 1)
    before = (eng.pattern.name, eng._queued, set(eng.muted), dict(eng._cc_values))
    with pytest.raises(engine.WhiplashError):
        eng.play(P["deephouse"], tracks=tracks)
    assert (eng.pattern.name, eng._queued, set(eng.muted), dict(eng._cc_values)) == before
    assert not any(m.type == "control_change" and m.control in (16, 19) for m in port.messages)
    eng.stop()


def test_transpose_given_twice_must_agree(fake):
    eng, _ = fake
    with pytest.raises(engine.WhiplashError, match="twice"):
        eng.play(P["techno"], transpose={"6": 12}, tracks={"6": {"transpose": -12}})
    assert not eng.playing()
    out = eng.play(P["techno"], bpm=300, transpose={"6": 12}, tracks={"6": {"transpose": 12}})
    assert out["mode"] == "started" and eng._transpose == {6: 12}
    eng.stop()


def test_tune_clamps_like_set_param():
    setup = engine.check_setup({"6": {"tune": 127}})
    assert setup[6] == {"tune": 124, "tune_clamped": True}


def test_play_tool_echoes_the_setup_with_slot_labels(tool_engine):
    tool_engine()
    call("whiplash_label_tracks", slots={"9": "dirty bass"})
    out = call("whiplash_play_pattern", genre="techno", bpm=300, tracks={"6": {"slot": 9, "transpose": 12}})
    assert out["success"] and out["setup"]["applied"] == "before the first bar"
    assert out["setup"]["tracks"]["6"] == {"slot": 9, "transpose": 12, "slot_label": "dirty bass"}
    assert out["tracks"]["6"]["slot"] == 9 and out["tracks"]["6"]["slot_label"] == "dirty bass"
    queued = call("whiplash_play_pattern", genre="deephouse", tracks={"8": {"mute": True}})
    assert queued["mode"] == "queued" and queued["setup"]["applied"].startswith("at the switch, bar")
    bad = call("whiplash_play_pattern", genre="soul", tracks={"6": {"slot": 300}})
    assert bad["success"] is False and "slot" in bad["error"]
    call("whiplash_stop")


def test_play_schema_takes_tracks():
    props = schemas.SCHEMAS["whiplash_play_pattern"]["parameters"]["properties"]
    entry = props["tracks"]["additionalProperties"]["properties"]
    assert set(entry) == set(engine.SETUP_KEYS) and entry["slot"]["maximum"] == 127


# ---- 3. techhouse ----------------------------------------------------------------

def test_techhouse_shape():
    p = P["techhouse"]
    assert p.bpm == 126 and p.swing > 0.5
    steps = lambda track, bar=0: [h[0] for h in p.bars[track][bar]]
    assert all(steps(1, b) == [0, 4, 8, 12] for b in range(4))  # four on the floor
    assert steps(5) == [2, 6, 10, 14]  # offbeat open hat
    assert len(steps(4)) == 16  # 16th hats, shuffled by swing and accents
    assert len({h[2] for h in p.bars[4][0]}) == 3
    bass = patterns.notes_of(p.bars[6])
    assert abs(statistics.median(bass) - patterns.NATIVE) <= patterns.NATIVE_FLOOR
    assert all(s % 4 != 0 for bar in p.bars[6] for s, *_ in bar)  # rolling off the beat, never on the kick
    assert sum(len(bar) for bar in p.bars[7]) <= 4  # sparse stab
    assert set(p.roles) == set(range(1, 9))


@pytest.mark.parametrize("word", ["techhouse", "tech house", "Tech-House", "tech_house", "TECH HOUSE"])
def test_techhouse_aliases(word):
    assert patterns.resolve(word).name == "techhouse"


def test_unknown_genre_lists_the_closest_matches():
    with pytest.raises(ValueError, match="closest: techhouse"):
        patterns.resolve("tekhouse")
    assert "techhouse" in schemas.SCHEMAS["whiplash_play_pattern"]["parameters"]["properties"]["genre"]["enum"]


def test_techhouse_plays(fake):
    eng, port = fake
    eng.play(patterns.resolve("tech house"), bpm=300)
    wait_bar(eng, 1)
    eng.stop()
    assert {m.channel for m in port.messages if m.type == "note_on"} == set(range(8))


# ---- 4. shorter tool descriptions ---------------------------------------------------

def _descriptions(node):
    if isinstance(node, dict):
        return sum(len(v) if k == "description" and isinstance(v, str) else _descriptions(v) for k, v in node.items())
    if isinstance(node, list):
        return sum(_descriptions(v) for v in node)
    return 0


def test_description_size_budget():
    # v0.5.2: 7302 characters of tool descriptions over 16 tools, 11357 counting params, 18108 bytes of JSON.
    tool_text = {name: len(s["description"]) for name, s in schemas.SCHEMAS.items()}
    assert sum(tool_text.values()) <= 3300, tool_text  # v0.7.0: 3000 -> 3300 for whiplash_listen
    assert max(tool_text.values()) <= 400, tool_text
    # v0.6.0 adds whiplash_set_progression and key/scale on play_pattern: about 700 characters of params.
    # v0.6.1 adds whiplash_arrange (its section schema) and trims other tool descriptions to stay under 3000.
    # v0.6.2 adds whiplash_mix and transition params on play_pattern and arrange sections; tool descriptions were
    # trimmed again to stay under 3000, and the params / JSON caps rise by about 400 characters and 1.5 KB.
    # v0.7.0 adds whiplash_listen and `force` on set_param, ramp_param and mix (the loudness guard): the tool total
    # rises to 3300 (above), params to 8400 characters and the JSON to 20100 bytes.
    assert _descriptions(schemas.SCHEMAS) <= 8400
    assert len(json.dumps(schemas.SCHEMAS)) <= 20100


def test_short_descriptions_keep_the_safety_caveats():
    d = {name: s["description"] for name, s in schemas.SCHEMAS.items()}
    assert "overlap_warning" in d["whiplash_play_pattern"] and "virtual port" in d["whiplash_play_pattern"]
    assert "user agrees" in d["whiplash_set_param"] and "NOTE" in d["whiplash_set_param"]
    assert "user agrees" in d["whiplash_write_part"] and "length_audible" in d["whiplash_write_part"]
    assert "can't list" in d["whiplash_select_sample"] and "already loaded" in d["whiplash_select_sample"]
    assert "panic" in d["whiplash_stop"] and "kit map" in d["whiplash_stop"]
    assert "read-only" in d["whiplash_open_view"]
    for name in ("whiplash_play_pattern", "whiplash_label_tracks", "whiplash_transpose", "whiplash_write_part",
                 "whiplash_status"):
        assert "whiplash:digitakt" in d[name], name


def test_schemas_stay_well_formed():
    for name, schema in schemas.SCHEMAS.items():
        assert schema["name"] == name and schema["description"].strip()
        assert schema["parameters"]["type"] == "object"
        json.dumps(schema)
    label = schemas.SCHEMAS["whiplash_label_tracks"]["parameters"]["properties"]
    assert set(label) == {"tracks", "slots", "reset"}
    for role in kitmap.ROLES:
        assert role in label["tracks"]["description"]


# ---- skill, docs, version -------------------------------------------------------------

def test_skill_covers_v053():
    skill = (ROOT / "skills" / "digitakt" / "SKILL.md").read_text()
    for fact in ("whiplash_label_tracks", "techhouse", 'tracks: {"6"', "slot_label", "reset: true", "gateway restart",
                 "mutations reset", "overlap_warning"):
        assert fact in skill, fact
    assert "Track roles are assumptions" not in skill


def test_changelog_keeps_0_5_3():  # the version itself is pinned by the newest release's test
    assert "\n## 0.5.3\n" in (ROOT / "CHANGELOG.md").read_text()


def test_no_new_message_types():
    assert engine.ALLOWED_TYPES == {"note_on", "note_off", "control_change", "clock", "start", "stop", "continue"}
    assert tools.HANDLERS["whiplash_label_tracks"]


# --- follow-ups from the v0.5.3 review (hardware-checklist PR) ---

def test_fill_leaves_a_melodic_line_on_a_drum_track_alone():
    from whiplash import mutate
    bass = [(s, 53, 100, 2, 0.0) for s in (0, 3, 6, 10, 14)]
    for track in range(1, 6):  # a bass routed onto 1-5 by the kit map never becomes a roll or loses its last beat
        assert mutate.fill(track, bass) == bass
    drums = [(s, patterns.DRUM, 100, 1, 0.0) for s in (0, 4, 8, 12)]
    assert mutate.fill(1, drums) == drums[:3]  # drum fills unchanged
    assert len(mutate.fill(2, drums)) == 2 + 8


def test_fill_skips_a_bass_routed_onto_the_snare_track():
    # v0.6.1: fills follow roles, so the default fill leaves the bass-labelled track 2 out, and naming it is refused
    def track2(fill):
        eng, _port = make_engine()
        try:
            eng.label_tracks(tracks={"2": "bass"})
            pretend_playing(eng, P["techno"])
            bar_events(eng, 0)
            if fill:
                assert 2 not in eng.schedule_fill()["tracks"]
                with pytest.raises(engine.WhiplashError, match="aren't drum tracks"):
                    eng.schedule_fill([2])
            return [e for e in bar_events(eng, 1) if e[1] == 2]
        finally:
            eng.shutdown()
    plain, filled = track2(False), track2(True)
    assert plain and {e[2] for e in plain} != {patterns.DRUM}  # the bass really is on track 2
    assert filled == plain


def test_explicit_role_accepts_underscores_and_case():
    assert kitmap.check_tracks({"4": {"role": "Closed_Hat"}}) == {4: ("closed hat", "Closed_Hat")}
