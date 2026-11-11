"""v0.6.1: whiplash_arrange (sections on bar lines, presets), fills that follow the kit map, and the v0.6.0 /
v0.5.3 review follow-ups (written parts in routing, relabel carries transpose and density, queued results with
their own setup, the 9-16 channel note, routing on play results, vacated default tracks)."""
import json
from pathlib import Path

import pytest

import whiplash
from whiplash import arrange, engine, harmony, kitmap, mutate, patterns, schemas, tools
from test_whiplash import call, make_engine, tool_engine  # noqa: F401  (fixture)
from test_live import bar_events, ons_per_bar, pretend_playing, wait_bar
from test_v051 import TimedPort, _jitter

P = patterns.PATTERNS
ROOT = Path(whiplash.__path__[0])
DEMO_LABELS = {"7": "tuned cymbal", "8": "tuned cymbal"}  # Phil's project 6 (hardware checklist A2)


@pytest.fixture
def fake():
    eng, port = make_engine()
    yield eng, port
    eng.shutdown()


def hits(eng, bar, track):
    return [(s, n) for s, t, n, *_ in bar_events(eng, bar) if t == track]


def at_bar(eng, bar):
    """Drive the sequencer's bar boundary by hand; returns {track: [(step, note)]}."""
    out = {}
    for s, t, n, *_ in bar_events(eng, bar):
        out.setdefault(t, []).append((s, n))
    return out


def ccs(port, control):
    return [(m.channel + 1, m.value) for m in port.messages if m.type == "control_change" and m.control == control]


# ---- item 3: fills follow the kit map -------------------------------------------------------

def test_fill_shapes_follow_the_role_not_the_track_number():
    drums = [(s, patterns.DRUM, 100, 1, 0.0) for s in (0, 4, 8, 12)]
    assert mutate.fill("kick", drums) == drums[:3] == mutate.fill(1, drums)
    assert mutate.fill("snare", drums) == mutate.fill("rim", drums) == mutate.fill(2, drums)
    assert mutate.fill("cymbal", drums) == mutate.fill("open hat", drums) == drums[:3]
    assert mutate.fill("perc", drums) == mutate.fill("clap", drums) == mutate.fill(3, drums)
    assert len(mutate.fill("closed hat", drums)) == 3 + 8
    for role in ("bass", "pad", "lead", "fx", "other", None, 9):
        assert mutate.fill(role, drums) == drums  # not a drum role: unchanged
    bass = [(s, 53, 100, 2, 0.0) for s in (0, 3, 6)]
    assert mutate.fill("kick", bass) == bass  # a melodic line never becomes a roll


def test_a_kick_labelled_on_track_9_gets_the_kick_fill(fake):
    eng, _ = fake
    eng.label_tracks(tracks={"9": "kick"})
    pretend_playing(eng, P["deephouse"])
    bar_events(eng, 0)
    assert {s for s, _ in hits(eng, 1, 9)} == {0, 4, 8, 12}  # the kick part moved to 9
    out = eng.schedule_fill()
    assert 9 in out["tracks"] and 1 not in out["tracks"] and out["fill_at_bar"] == 2
    assert {s for s, _ in hits(eng, 2, 9)} == {0, 4, 8}  # sits out the last beat
    eng.schedule_fill([9])
    assert {s for s, _ in hits(eng, 3, 9)} == {0, 4, 8}


def test_default_fill_covers_the_routed_drum_tracks_and_refuses_melodic_ones(fake):
    eng, _ = fake
    eng.label_tracks(tracks={"10": "snare", "12": "closed hat"})
    pretend_playing(eng, P["techno"])
    bar_events(eng, 0)
    assert eng.schedule_fill()["tracks"] == [1, 3, 5, 10, 12]
    for track in (6, 7):
        with pytest.raises(engine.WhiplashError, match="aren't drum tracks"):
            eng.schedule_fill([track])
    with pytest.raises(engine.WhiplashError, match="track must be 1-16"):
        eng.schedule_fill([17])
    snare = hits(eng, 1, 10)
    assert [s for s, _ in snare if s >= 8] == list(range(8, 16))  # the roll on the labelled snare track


def test_cymbal_and_perc_fill_only_when_named(fake):
    eng, _ = fake
    eng.label_tracks(tracks=DEMO_LABELS)
    pretend_playing(eng, P["deephouse"])
    bar_events(eng, 0)
    assert eng.schedule_fill()["tracks"] == [1, 2, 3, 4]  # the open-hat line on cymbal track 7 is left alone
    assert eng.schedule_fill([7])["tracks"] == [7]
    assert [s for s, _ in hits(eng, 1, 7)] == [2, 6, 10]  # named: the open-hat shape


def test_unlabelled_fills_are_unchanged(fake):
    eng, _ = fake
    pretend_playing(eng, P["techno"])
    bar_events(eng, 0)
    assert eng.schedule_fill() == {"fill_at_bar": 1, "tracks": [1, 2, 3, 4, 5]}
    assert eng.schedule_drop([1, 6], 2, fill=True)["fill_tracks"] == [2, 3, 4, 5]


def test_demo_drop_with_fill_is_unchanged_on_the_labelled_kit(fake):
    """Hardware checklist A3-A6: the drop's fill plays on 2-4 and the cymbal tracks keep their lines."""
    eng, _ = fake
    eng.label_tracks(tracks=DEMO_LABELS)
    pretend_playing(eng, P["deephouse"])
    plain = at_bar(eng, 0)
    assert 5 not in plain and 8 not in plain and [s for s, _ in plain[7]] == [2, 6, 10, 14]
    eng.write_part(8, rhythm="8ths", key="A", scale="minor", notes="1 3 5 8 7 5 3 1", length=2)
    out = eng.schedule_drop([1, 6], 2, fill=True)
    assert out["fill_tracks"] == [2, 3, 4] and out["fill_at_bar"] == 2
    bar_events(eng, 1)
    filled = at_bar(eng, 2)
    assert 1 not in filled and 6 not in filled
    assert filled[7] == plain[7]  # the tuned cymbal keeps the open-hat rhythm
    assert len(filled[8]) == 8 and {n for _, n in filled[8]} != {patterns.DRUM}  # the melody keeps playing
    assert len([s for s, _ in filled[2] if s >= 8]) == 8  # the rim roll


# ---- follow-up: routing never hides a generated part under a written one silently ------------

def test_a_written_part_on_the_bass_track_is_reported_not_silently_lost(fake):
    eng, _ = fake
    eng.label_tracks(tracks={"10": "bass"})
    pretend_playing(eng, P["deephouse"])
    bar_events(eng, 0)
    assert hits(eng, 1, 10)  # the bass plays on 10
    out = eng.write_part(10, rhythm="four_on_floor", notes=["A4"])
    assert out["replaces_generated"] == "bass (pattern track 6)"
    routing = eng.routing()
    assert routing["replaced_by_written"] == {"10": "bass (pattern track 6)"} and routing["written"] == [10]
    assert "6" not in routing["parts"] and "10" not in routing["parts"]
    assert not hits(eng, 2, 6)  # no surprise second bass on the default track
    assert [n for _, n in hits(eng, 2, 10)] == [57] * 4
    reset = eng.write_part(10, reset=True)
    assert reset["part"] == "generated"
    assert hits(eng, 3, 10) == [(h[0], h[1]) for h in P["deephouse"].bars[6][3]]  # the bass is back


def test_a_written_part_moves_the_generated_part_to_another_matching_track(fake):
    eng, _ = fake
    eng.label_tracks(tracks={"6": "bass", "10": "dirty bass"})
    pretend_playing(eng, P["techno"])
    bar_events(eng, 0)
    bass = hits(eng, 1, 6)
    assert bass and not hits(eng, 1, 10)
    eng.write_part(6, rhythm="half_time", notes=["C5"])
    assert hits(eng, 2, 10) == bass  # the generated bass moved, not lost
    assert eng.routing()["parts"]["10"].startswith("bass")


def test_unlabelled_written_part_reports_the_part_it_replaces(fake):
    eng, _ = fake
    pretend_playing(eng, P["deephouse"])
    eng.write_part(6, rhythm="8ths", notes=["A4"])
    routing = eng.routing()
    assert routing["replaced_by_written"] == {"6": "bass (pattern track 6)"}
    assert eng.status()["tracks"]["6"]["role"] == "bass (assumed)"  # the assumed role stays
    assert kitmap.describe(P["deephouse"], {}) == {"parts": {str(t): kitmap.describe(P["deephouse"], {})["parts"][str(t)]
                                                             for t in range(1, 9)}}


def test_silent_until_written_leaves_out_written_tracks(fake):
    eng, _ = fake
    eng.label_tracks(tracks={"12": "pad"})
    pretend_playing(eng, P["techno"])
    assert eng.routing()["silent_until_written"] == [12]
    eng.write_part(12, rhythm="8ths", notes=["C5"])
    assert "silent_until_written" not in eng.routing()


# ---- follow-up: relabelling moves transpose and density with the part ------------------------

def test_relabel_while_playing_moves_transpose_and_density_with_the_part(fake):
    eng, _ = fake
    pretend_playing(eng, P["deephouse"])
    bar_events(eng, 0)
    eng.set_transpose(6, semitones=12)
    eng.mutate_density([6], 0.5)
    plain = [n + 12 for _, n, *_ in P["deephouse"].bars[6][1]]
    out = eng.label_tracks(tracks={"10": "bass"})
    assert out["follows_part"] == {"transpose": {"6->10": 12}, "density": {"6->10": 0.5}}
    for bar in (2, 3, 4):
        assert not hits(eng, bar, 6)
    after = hits(eng, 5, 10)  # the same bar of the loop as bar 1
    assert len(after) > len(plain) and {n for _, n in after} == set(plain)  # transposed and thickened, on 10
    assert eng._transpose == {10: 12} and eng._density == {10: 0.5}
    st = eng.status()
    assert st["transpose"] == {"10": 12} and st["mutations"]["density"] == {"10": 0.5}


def test_a_dropped_part_clears_its_settings(fake):
    eng, _ = fake
    pretend_playing(eng, P["deephouse"])
    bar_events(eng, 0)
    eng.set_transpose(6, semitones=-12)
    out = eng.label_tracks(tracks={"6": "riser fx"})  # the bass part has no track now
    assert out["follows_part"] == {"transpose": {"6->dropped": -12}}
    bar_events(eng, 1)
    assert eng._transpose == {} and not hits(eng, 2, 6)


def test_relabel_swap_moves_each_setting_with_its_own_part(fake):
    eng, _ = fake
    pretend_playing(eng, P["deephouse"])
    bar_events(eng, 0)
    eng.set_transpose(1, semitones=5)
    eng.set_transpose(6, semitones=12)
    eng.label_tracks(tracks={"1": "bass", "6": "kick"})
    bar_events(eng, 1)
    assert eng._transpose == {6: 5, 1: 12}


def test_relabel_keeps_a_written_parts_transpose(fake):
    eng, _ = fake
    pretend_playing(eng, P["deephouse"])
    eng.write_part(10, rhythm="8ths", notes=["C5"])
    eng.set_transpose(10, semitones=7)
    eng.label_tracks(tracks={"10": "lead"})
    bar_events(eng, 0)
    assert eng._transpose == {10: 7}


# ---- follow-up: queued results show their own setup; routing and 9-16 notes on play results ----

def test_queued_play_result_reflects_its_own_pending_setup(tool_engine):
    eng, port = tool_engine()
    call("whiplash_play_pattern", genre="deephouse", bpm=30)
    call("whiplash_set_param", track=6, param="sample_slot", value=3)
    call("whiplash_mute_track", track=4)
    out = call("whiplash_play_pattern", genre="techno", tracks={"6": {"slot": 9, "tune": 70, "mute": True},
                                                                 "4": {"mute": False}})
    assert out["mode"] == "queued"
    six = out["tracks"]["6"]
    assert six["slot"] == 9 and six["tune"] == 70 and six["muted"] is True
    assert six["setup_at_switch"] == {"slot": 9, "tune": 70, "mute": True}
    assert six["pitch"]["semitones_from_native"][0] == six["pitch"]["low"] - 60 + 6  # pitch uses the pending tune
    assert out["tracks"]["4"]["muted"] is False and out["muted_carried"] == [4] and out["muted_at_switch"] == [6]
    assert eng.status()["tracks"]["6"]["slot"] == 3  # nothing was sent yet
    assert out["routing"]["pattern"] == "techno"
    call("whiplash_stop")


def test_play_results_carry_routing_and_the_vacated_note(tool_engine):
    eng, _ = tool_engine()
    call("whiplash_label_tracks", tracks=DEMO_LABELS)
    out = call("whiplash_play_pattern", genre="deephouse", bpm=300, tracks={"6": {"slot": 9}})
    routing = out["routing"]
    assert routing["pattern"] == "deephouse" and routing["parts"]["7"].startswith("open hat")
    assert routing["dropped"] == {"7": "minor chord", "8": "major chord"} and routing["silent_until_written"] == [8]
    assert routing["vacated"] == {"5": 7} and "track 5 plays nothing" in routing["vacated_note"]
    assert "channel_note" not in out
    queued = call("whiplash_play_pattern", genre="techhouse")
    assert queued["routing"]["pattern"] == "techhouse" and queued["routing"]["vacated"] == {"5": 7}
    call("whiplash_stop")


def test_no_labels_means_a_plain_routing(tool_engine):
    tool_engine()
    out = call("whiplash_play_pattern", genre="techno", bpm=300)
    assert set(out["routing"]["parts"]) == {str(t) for t in range(1, 9)} and set(out["routing"]) == {"parts", "pattern"}
    call("whiplash_stop")


def test_channel_note_when_routing_or_setup_lands_on_9_16(tool_engine):
    tool_engine()
    out = call("whiplash_label_tracks", tracks={"9": "kick"})
    assert "channel_note" not in out  # nothing to route yet
    out = call("whiplash_play_pattern", genre="techno", bpm=300)
    assert out["tracks_9_16"] == [9] and "AUTO CHANNEL" in out["channel_note"]
    out = call("whiplash_label_tracks", tracks={"9": None})
    assert "channel_note" not in out
    out = call("whiplash_label_tracks", tracks={"11": "bass"})
    assert out["routing"]["tracks_9_16"] == [11] and "channel_note" in out
    call("whiplash_label_tracks", reset=True)
    out = call("whiplash_play_pattern", genre="soul", tracks={"10": {"slot": 4}})
    assert out["mode"] == "queued" and out["tracks_9_16"] == [10] and "channel_note" in out
    out = call("whiplash_play_pattern", genre="techno", bpm=300, send_transport=False)  # fresh start
    assert "channel_note" not in out
    call("whiplash_stop")


def test_vacated_is_reported_only_for_unlabelled_default_tracks():
    info = kitmap.plan(P["deephouse"], kitmap.check_tracks(DEMO_LABELS))
    assert info["vacated"] == {5: 7}
    info = kitmap.plan(P["deephouse"], kitmap.check_tracks({**DEMO_LABELS, "5": "open hat"}))
    assert info["vacated"] == {} and info["moves"][5] == 5
    assert kitmap.plan(P["deephouse"], {})["vacated"] == {}


# ---- item 2: arrangement -------------------------------------------------------------------

def arranged(eng, pattern="deephouse", **kw):
    pretend_playing(eng, P[pattern])
    bar_events(eng, 0)
    return eng.arrange(**kw)


def test_club_preset_bar_counts_are_exact():
    secs = arrange.sections(arrange.club())
    assert [(s.name, s.bars) for s in secs] == [("intro", 16), ("build", 8), ("drop", 16), ("break", 8),
                                                 ("drop 2", 16), ("outro", 16)]


@pytest.mark.parametrize("name", sorted(P))
def test_short_demo_lasts_60_to_90_seconds_at_each_genres_tempo(name):
    bpm = P[name].bpm
    secs = arrange.sections(arrange.short_demo(bpm))
    total = sum(s.bars for s in secs)
    assert 60 <= total * 240 / bpm <= 90, (name, total)
    assert total % 4 == 0 and [s.name for s in secs][:2] == ["intro", "build"] and secs[-1].name == "outro"
    long = sum(s.bars for s in arrange.sections(arrange.short_demo(bpm, 180)))
    assert abs(long * 240 / bpm - 180) <= 16 * 240 / bpm


def test_sections_land_on_their_bar_lines_and_mute_only_at_boundaries(fake):
    eng, _ = fake
    out = arranged(eng, sections=[{"name": "intro", "bars": 2, "tracks": ["kick", "hats"]},
                                  {"name": "full", "bars": 3, "tracks": "all"},
                                  {"name": "break", "bars": 1, "mute": ["kick", "bass"]}])
    assert out["starts_at_bar"] == 1 and out["total_bars"] == 6 and out["ends"].endswith("bar 7")
    assert [s["starts_at_bar"] for s in out["sections"]] == [1, 3, 6]
    assert out["sections"][0]["plays_now"] == [1, 4, 5]
    expected = {1: {2, 3, 6, 7, 8}, 2: {2, 3, 6, 7, 8}, 3: set(), 4: set(), 5: {7}, 6: {1, 6}}
    for bar in range(1, 7):
        bar_events(eng, bar)
        assert eng.muted == expected[bar], bar
        if bar == 4:
            eng.set_mute(7, True)  # a user mute mid-section stays until the next boundary
    with eng._lock:
        assert eng._bar_boundary(7) is None  # loop: false stops on the bar line after the last section
    assert eng.status()["arrangement"]["ended_at_bar"] == 7


def test_loop_wraps_to_the_first_section(fake):
    eng, _ = fake
    arranged(eng, loop=True, sections=[{"name": "a", "bars": 1, "tracks": ["kick"]},
                                       {"name": "b", "bars": 1, "tracks": "all"}])
    for bar, muted in ((1, True), (2, False), (3, True), (4, False)):
        assert bar_events(eng, bar) is not None
        assert (6 in eng.muted) is muted
    assert eng.status()["arrangement"]["current"]["next"] == "a"


def test_ramps_start_on_the_sections_first_bar(fake):
    eng, port = fake
    arranged(eng, sections=[{"name": "intro", "bars": 2, "tracks": ["kick"]},
                            {"name": "build", "bars": 4, "ramps": [{"track": "music", "param": "filter_freq",
                                                                    "from": 20, "to": 127, "curve": "exp"}]}])
    bar_events(eng, 1)
    bar_events(eng, 2)
    assert not eng._ramps and not ccs(port, 74)
    bar_events(eng, 3)
    assert sorted(eng._ramps) == [(7, 74), (8, 74)]
    ramp = eng._ramps[(7, 74)]
    assert (ramp.start, ramp.end, ramp.total, ramp.curve) == (20, 127, 4 * engine.TICKS_PER_BAR, "exp")
    assert ccs(port, 74) == [(7, 20), (8, 20)]  # the start value goes out on the section's first bar


def test_a_ramp_without_from_uses_the_last_value_or_is_skipped(fake):
    eng, port = fake
    out = arranged(eng, sections=[{"name": "x", "bars": 2, "ramps": [{"track": 6, "param": "cutoff", "to": 90},
                                                                     {"track": 7, "param": "cutoff", "to": 90}]}])
    assert "ramp_note" in out
    eng.set_param(6, 40, param="filter_freq")
    bar_events(eng, 1)
    assert list(eng._ramps) == [(6, 74)] and eng._ramps[(6, 74)].start == 40
    assert eng.status()["arrangement"]["skipped_ramps"] == ["x: filter_freq on track 7 (no 'from')"]


def test_fill_and_drop_land_on_the_sections_last_bar(fake):
    eng, _ = fake
    arranged(eng, sections=[{"name": "build", "bars": 3, "drop": ["kick"], "fill": True},
                            {"name": "drop", "bars": 2}])
    for bar in (1, 2):
        assert [s for s, _ in hits(eng, bar, 1)] == [0, 4, 8, 12]
    last = at_bar(eng, 3)
    assert 1 not in last  # the kick sits out the build's last bar
    assert len([s for s, _ in last[2] if s >= 8]) == 8 and len(last[4]) > 12  # rim roll, hat ratchets
    assert [s for s, _ in hits(eng, 4, 1)] == [0, 4, 8, 12]  # back on the one


def test_section_chords_swap_the_progression_at_its_first_bar(fake):
    eng, _ = fake
    arranged(eng, sections=[{"name": "a", "bars": 2, "chords": "i VI", "bars_per_chord": 1},
                            {"name": "b", "bars": 2, "chords": "iv v"},
                            {"name": "c", "bars": 1, "chords": "none"}])
    bar_events(eng, 1)
    st = eng.status()["progression"]
    assert st["names"] == ["Am", "F"] and st["starts_at_bar"] == 1 and st["now"]["name"] == "Am"
    bar_events(eng, 2)
    assert eng.status()["progression"]["now"]["name"] == "F"
    bar_events(eng, 3)
    st = eng.status()["progression"]
    assert st["names"] == ["Dm", "Em"] and st["starts_at_bar"] == 3 and st["now"]["name"] == "Dm"
    assert {n % 12 for _, n in hits(eng, 4, 6)} == {4}  # the bass on E, the root of v
    bar_events(eng, 5)
    assert eng.status()["progression"] is None


def test_status_shows_section_bars_left_and_next(fake):
    eng, _ = fake
    arranged(eng, preset="club")
    st = eng.status()["arrangement"]
    assert st["name"] == "club" and st["total_bars"] == 80 and "current" not in st
    for bar in range(1, 4):
        bar_events(eng, bar)
    cur = eng.status()["arrangement"]["current"]
    assert cur == {"section": "intro", "index": 0, "bars_left": 14, "next": "build", "next_at_bar": 17}
    for bar in range(4, 66):
        bar_events(eng, bar)
    cur = eng.status()["arrangement"]["current"]
    assert cur["section"] == "outro" and cur["next"] is None and cur["stops_at_bar"] == 81 and cur["bars_left"] == 16


def test_club_preset_on_the_default_layout(fake):
    eng, port = fake
    out = arranged(eng, preset="club")
    plays = {s["name"]: s["plays_now"] for s in out["sections"]}
    assert plays == {"intro": [1, 4, 5], "build": [1, 2, 3, 4, 5, 7, 8], "drop": list(range(1, 9)),
                     "break": [2, 3, 4, 5, 7, 8], "drop 2": list(range(1, 9)), "outro": [1, 2, 3, 4, 5]}
    assert out["sections"][1]["drop_last_bar"] == [1] and "filter_note" in out
    for bar in range(1, 18):
        bar_events(eng, bar)
    assert ccs(port, 74) == [(7, 20), (8, 20)]  # the build's filter starts closed on the chord tracks


def test_bad_arrangements_change_nothing(fake):
    eng, port = fake
    pretend_playing(eng, P["deephouse"])
    bar_events(eng, 0)
    eng.set_mute(3, True)
    sent = len(port.messages)
    bad = [
        {}, {"sections": []}, {"sections": "intro"}, {"preset": "festival"}, {"preset": "club", "sections": [{}]},
        {"preset": "club", "seconds": 60}, {"sections": [{"bars": 4}], "seconds": 60},
        {"sections": [{"name": "a"}]}, {"sections": [{"bars": 0}]}, {"sections": [{"bars": 65}]},
        {"sections": [{"bars": 4, "transition": "cut"}]}, {"sections": [{"bars": 4, "tracks": ["tuba"]}]},
        {"sections": [{"bars": 4, "tracks": [17]}]}, {"sections": [{"bars": 4, "tracks": [1], "mute": [2]}]},
        {"sections": [{"bars": 4}] * 17}, {"sections": [{"bars": 64}] * 9},
        {"sections": [{"bars": 4, "chords": "i Q"}]}, {"sections": [{"bars": 4, "bars_per_chord": 2}]},
        {"sections": [{"bars": 4, "chords": "i", "bars_per_chord": 0}]},
        {"sections": [{"bars": 4, "ramps": [{"track": 1, "param": "nope", "to": 3}]}]},
        {"sections": [{"bars": 4, "ramps": [{"track": 1, "param": "mute", "to": 1}]}]},
        {"sections": [{"bars": 4, "ramps": [{"track": 1, "param": "cutoff"}]}]},
        {"sections": [{"bars": 4, "ramps": [{"track": 1, "param": "cutoff", "to": 300}]}]},
        {"sections": [{"bars": 4, "ramps": [{"track": 1, "param": "cutoff", "to": 3, "curve": "zigzag"}]}]},
        {"sections": [{"bars": 4, "ramps": [{"track": 1, "cc": 0, "to": 3}]}]},
        {"sections": [{"bars": 4, "ramps": [{"track": 1, "param": "bank", "to": 3}]}]},
        {"sections": [{"bars": 4, "name": "x" * 30}]}, {"sections": [{"bars": 4}], "loop": "maybe"},
        {"clear": True, "preset": "club"},
    ]
    for kw in bad:
        with pytest.raises(engine.WhiplashError):
            eng.arrange(**kw)
    assert eng._arr is None and eng.muted == {3} and len(port.messages) == sent and not eng._ramps


def test_arrange_needs_a_pattern_playing(fake):
    eng, _ = fake
    with pytest.raises(engine.WhiplashError, match="nothing is playing"):
        eng.arrange(preset="club")


def test_clear_unmutes_what_the_arrangement_muted_and_stop_ends_it(fake):
    eng, _ = fake
    arranged(eng, sections=[{"bars": 4, "tracks": ["kick"]}])
    eng.set_mute(1, True)
    bar_events(eng, 1)
    assert eng.muted == {2, 3, 4, 5, 6, 7, 8}  # the section's own tracks play: the kick is unmuted
    eng.set_mute(1, True)
    out = eng.arrange(clear=True)
    assert out["cleared"] and out["unmuted"] == [2, 3, 4, 5, 6, 7, 8] and eng.muted == {1}
    assert eng.status()["arrangement"] is None and eng.arrange(clear=True)["cleared"] is False
    eng.arrange(preset="short_demo")
    eng.stop()
    assert eng._arr is None and eng._arr_muted == set()


def test_arrangement_follows_a_switch_and_a_relabel(fake):
    eng, _ = fake
    arranged(eng, sections=[{"bars": 2, "tracks": ["bass"]}, {"bars": 2, "tracks": ["bass"]}])
    bar_events(eng, 1)
    assert 6 not in eng.muted
    eng.label_tracks(tracks={"10": "bass"})
    bar_events(eng, 2)
    bar_events(eng, 3)
    assert 10 not in eng.muted and 6 not in eng.muted and 1 in eng.muted  # groups resolve at each section


def test_arrange_tool_round_trip_and_status(tool_engine):
    eng, port = tool_engine()
    assert "nothing is playing" in call("whiplash_arrange", preset="club")["error"]
    call("whiplash_play_pattern", genre="techno", bpm=300)
    out = call("whiplash_arrange", preset="short_demo", seconds=60)
    assert out["success"] and out["arrangement"] == "short_demo" and out["loop"] is False
    assert 50 <= out["total_bars"] * 240 / 300 <= 70 or out["total_bars"] == 16
    wait_bar(eng, out["starts_at_bar"])
    st = call("whiplash_status")["arrangement"]
    assert st["current"]["section"] == "intro" and st["sections"][0]["name"] == "intro"
    queued = call("whiplash_play_pattern", genre="breaks")
    assert queued["arrangement_carried"] == "short_demo"
    bad = call("whiplash_arrange", sections=[{"bars": 4, "tracks": ["tuba"]}])
    assert not bad["success"] and "tuba" in bad["error"]
    assert call("whiplash_arrange", clear=True)["cleared"]
    stop = call("whiplash_stop")
    assert stop["success"] and call("whiplash_status")["arrangement"] is None


def test_a_short_arrangement_plays_its_sections_and_stops_by_itself(fake):
    eng, port = fake
    eng.play(P["techno"], bpm=300)
    wait_bar(eng, 1)
    out = eng.arrange(sections=[{"bars": 1, "tracks": ["kick"]}, {"bars": 1, "tracks": "all"},
                                {"bars": 1, "tracks": ["bass"]}])
    start = out["starts_at_bar"]
    eng._thread.join(timeout=10)
    assert not eng.playing()
    kicks, bass = ons_per_bar(port, 0), ons_per_bar(port, 5)
    assert kicks[start] == 4 and bass[start] == 0
    assert kicks[start + 1] == 4 and bass[start + 1] == 8
    assert kicks[start + 2] == 0 and bass[start + 2] == 8
    assert kicks[start + 3] == 0 and bass[start + 3] == 0  # stopped on the bar line
    assert [m for m in port.messages if m.type == "stop"]  # a clean stop: MIDI Stop sent


def test_arrange_schema():
    schema = schemas.SCHEMAS["whiplash_arrange"]
    props = schema["parameters"]["properties"]
    assert set(props) == {"preset", "seconds", "sections", "loop", "clear"}
    assert props["preset"]["enum"] == list(arrange.PRESETS)
    section = props["sections"]["items"]["properties"]
    assert set(section) == set(arrange.SECTION_KEYS) and props["sections"]["items"]["required"] == ["bars"]
    assert "whiplash:digitakt" in schema["description"] and len(schema["description"]) <= 400
    json.dumps(schemas.SCHEMAS)


def test_clock_jitter_is_unchanged_with_an_arrangement():
    port = TimedPort()
    eng, _ = make_engine(port)
    try:
        eng.play(P["techno"], bpm=240)
        wait_bar(eng, 1)
        ramps = [{"track": t, "param": "filter_freq", "from": 10, "to": 120, "bars": 1} for t in range(1, 9)]
        sections = [{"bars": 1, "tracks": ["kick", "hats"] if i % 2 else "all", "ramps": ramps, "fill": True,
                     "drop": ["kick"], "chords": "i VI III VII" if i % 2 else "iv v"} for i in range(4)]
        out = eng.arrange(sections=sections, loop=True)
        at = out["starts_at_bar"]
        wait_bar(eng, at + 2)
        eng.stop()
    finally:
        eng.shutdown()
    t = port.clock_times
    base, arranged_ = t[:at * engine.TICKS_PER_BAR], t[at * engine.TICKS_PER_BAR:(at + 2) * engine.TICKS_PER_BAR]
    assert len(arranged_) == 2 * engine.TICKS_PER_BAR
    assert _jitter(arranged_) <= max(_jitter(base) * 2, _jitter(base) + 0.003), (_jitter(base), _jitter(arranged_))


# ---- safety, docs, version -------------------------------------------------------------------

def test_no_new_message_types_or_unblocked_ccs():
    from whiplash import ccmap
    assert engine.ALLOWED_TYPES == {"note_on", "note_off", "control_change", "clock", "start", "stop", "continue"}
    assert {0, 32, 24, 6, 38, 98, 99} <= set(ccmap.BLOCKED_CCS)


def test_arrange_sends_only_ramp_ccs(fake):
    eng, port = fake
    arranged(eng, preset="club")
    for bar in range(1, 81):
        bar_events(eng, bar)
    sent = {(m.type, getattr(m, "control", None)) for m in port.messages}
    assert sent <= {("control_change", 74)}  # the build's filter start values; notes are sent by the thread only


def test_version_is_0_6_1():
    import tomllib
    import yaml
    assert yaml.safe_load(open(ROOT / "plugin.yaml"))["version"] == "0.6.1"
    assert yaml.safe_load(open(ROOT / "docs" / "catalog-entry.yaml"))["version"] == "0.6.1"
    assert tomllib.load(open(ROOT / "pyproject.toml", "rb"))["project"]["version"] == "0.6.1"
    assert whiplash.__version__ == "0.6.1"
    assert (ROOT / "CHANGELOG.md").read_text().split("\n## ", 1)[1].startswith("0.6.1")
    for manifest in (yaml.safe_load(open(ROOT / "plugin.yaml"))["provides_tools"],
                     yaml.safe_load(open(ROOT / "docs" / "catalog-entry.yaml"))["capabilities"]["provides_tools"]):
        assert manifest.index("whiplash_arrange") == manifest.index("whiplash_set_progression") + 1


def test_stale_wording_is_gone():
    import yaml
    plugin = yaml.safe_load(open(ROOT / "plugin.yaml"))["description"]
    catalog = yaml.safe_load(open(ROOT / "docs" / "catalog-entry.yaml"))["description"]
    for text in (plugin, catalog):
        assert "tracks 1-8" not in text and "arrange" in text and "kit map" in text and "SysEx" in text
    assert "chord progressions" in catalog and "key" in catalog
    skill = (ROOT / "skills" / "digitakt" / "SKILL.md").read_text()
    assert "tracks 1-5" not in skill and "carry no `routing`" not in skill
    for fact in ("whiplash_arrange", "short_demo", "club", "routing", "replaced_by_written", "vacated",
                 "follows_part", "setup_at_switch", "channel_note", "fill"):
        assert fact in skill, fact
    readme = (ROOT / "README.md").read_text()
    assert "whiplash_arrange" in readme and "Arrangement" in readme
