"""v0.5 P0a: native-pitch register, per-track transpose and pitch, per-track status, amp_mode, bundled skill."""
import re
import statistics
from pathlib import Path

import pytest
import yaml

import whiplash
from whiplash import ccmap, engine, mutate, patterns, schemas, tools
from test_whiplash import call, make_engine, tool_engine  # noqa: F401  (fixture)
from test_live import bar_events, finish, pretend_playing, timeline, wait_bar

P = patterns.PATTERNS
ROOT = Path(whiplash.__path__[0])


@pytest.fixture
def fake():
    eng, port = make_engine()
    yield eng, port
    eng.shutdown()


def notes_on(port, channel, bar=None):
    return [m.note for b, _, m in timeline(port)
            if m.type == "note_on" and m.channel == channel and (bar is None or b == bar)]


# ---- native register -----------------------------------------------------

@pytest.mark.parametrize("name", sorted(P))
def test_melodic_parts_sit_near_native_pitch(name):
    p = P[name]
    for track, bars in p.bars.items():
        notes = patterns.notes_of(bars)
        if not patterns.is_melodic(bars):
            continue
        median = statistics.median(notes)
        # never more than NATIVE_FLOOR below the sample's own pitch, and never far above it
        assert patterns.NATIVE - patterns.NATIVE_FLOOR <= median <= patterns.NATIVE + 12, (name, track, median)
        assert all(patterns.NOTE_MIN <= n <= patterns.NOTE_MAX for n in notes)


@pytest.mark.parametrize("name", sorted(P))
def test_register_moves_whole_octaves_and_keeps_the_line(name):
    raw, p = patterns.RAW[name], P[name]
    for track, bars in raw.bars.items():
        shift = p.shifts.get(track, 0)
        assert shift % 12 == 0
        expected = [[(s, n + shift, v, g) for s, n, v, g in bar] for bar in bars]
        assert p.bars[track] == expected  # same steps, velocities, gates and intervals
        if not patterns.is_melodic(bars):
            assert track not in p.shifts and p.bars[track] == bars  # drums untouched


def test_register_matches_the_plan():
    assert {n: P["techno"].bars[6][0][0][1] for n in ("techno",)} == {"techno": 53}  # was 41: the -7 Phil fixed by ear
    assert P["techno"].shifts[6] == 12 and P["soul"].shifts[6] == 12 and P["breaks"].shifts[6] == 12
    assert set(P["deephouse"].shifts.values()) == {0}  # already near native
    assert P["soul"].shifts[7] == 0  # chops above native are left alone


def test_elektron_note_names():
    assert patterns.note_name(60) == "C5" and patterns.note_name(53) == "F4" and patterns.note_name(84) == "C7"
    # Consistent with C5 = 60, MIDI 16 is E1 (manual 8.4 prints "E2" for 16, which doesn't fit its own C5 = 60).
    assert patterns.note_name(16) == "E1"
    assert patterns.note_name(61) == "C#5"


# ---- transpose -----------------------------------------------------------

def test_transpose_shifts_notes_on_the_wire_and_leaves_drums(fake):
    eng, port = fake
    eng.play(P["techno"], bpm=300, bars=1, transpose={"6": -12, 1: 0})
    finish(eng)
    assert set(notes_on(port, 5)) == {41}
    assert set(notes_on(port, 0)) == {60}  # kick untouched
    assert port.count("note_on") == port.count("note_off")


def test_transpose_clamps_to_the_chromatic_range(fake):
    eng, _ = fake
    pretend_playing(eng, P["techno"])
    eng.set_transpose(6, semitones=48)
    eng.set_transpose(7, semitones=-48)
    events = bar_events(eng, 0)
    assert {e[2] for e in events if e[1] == 6} == {84}
    assert {e[2] for e in events if e[1] == 7} == {16}
    pitch = eng.tracks_summary()["6"]["pitch"]
    assert pitch["clamped"] and pitch["high"] == 84


def test_transpose_lands_on_the_next_bar(fake):
    eng, port = fake
    eng.play(P["techno"], bpm=300)
    wait_bar(eng, 1)
    out = eng.set_transpose(6, octaves=1)
    assert out["applies"] == "next bar" and out["transpose"] == 12 and out["previous"] == 0
    at = out["at_bar"]
    wait_bar(eng, at + 1)
    eng.stop()
    for bar in range(at):
        assert set(notes_on(port, 5, bar)) <= {53}
    assert set(notes_on(port, 5, at)) == {65}
    assert out["pitch"]["low"] == 65 and out["pitch"]["semitones_from_native"] == [5, 5]


def test_transpose_carries_over_a_switch_and_resets_on_stop(fake):
    eng, port = fake
    eng.play(P["techno"], bpm=300, transpose={"6": 12})
    eng.play(P["deephouse"], bpm=300)  # queued
    wait_bar(eng, 2)
    assert eng.status()["pattern"] == "deephouse" and eng.status()["transpose"] == {"6": 12}
    raw = {h[1] + 12 for bar in P["deephouse"].bars[6] for h in bar}
    assert set(notes_on(port, 5, 1)) <= raw and notes_on(port, 5, 1)
    eng.stop()
    assert eng.status()["transpose"] == {}
    assert eng.tracks_summary()["6"]["transpose"] == 0


def test_queued_switch_brings_its_own_transpose(fake):
    eng, _ = fake
    eng.play(P["techno"], bpm=300, transpose={"6": 12})
    out = eng.play(P["soul"], bpm=300, transpose={"7": -12, "6": 0})
    assert out["mode"] == "queued"
    assert eng.status()["queued"]["transpose"] == {"6": 0, "7": -12}
    assert eng.status()["transpose"] == {"6": 12}  # not yet: it lands with the switch
    wait_bar(eng, 2)
    assert eng.status()["pattern"] == "soul" and eng.status()["transpose"] == {"7": -12}


def test_fresh_start_resets_transpose(fake):
    eng, _ = fake
    eng.play(P["techno"], bpm=300, transpose={"6": 12})
    eng.play(P["techno"], bpm=300, send_transport=False)  # mode change: fresh start
    assert eng.status()["transpose"] == {}


def test_bad_transpose_never_touches_the_beat(fake):
    eng, port = fake
    eng.play(P["techno"], bpm=300)
    for bad in ({"6": 99}, {"17": 1}, {"6": 1.5}, {"x": 1}, [6, 12], "up"):
        with pytest.raises(engine.WhiplashError):
            eng.play(P["soul"], transpose=bad)
    assert eng.status()["queued"] is None
    for kw in ({}, {"semitones": 1, "octaves": 1}, {"semitones": 49}, {"octaves": 5}, {"semitones": "x"}):
        with pytest.raises(engine.WhiplashError):
            eng.set_transpose(6, **kw)
    with pytest.raises(engine.WhiplashError):
        eng.set_transpose(0, semitones=1)
    assert eng.status()["transpose"] == {}
    eng.stop()
    with pytest.raises(engine.WhiplashError, match="play_pattern"):
        eng.set_transpose(6, semitones=12)  # nothing playing


def test_hit_tuple_keeps_its_shape_for_the_view(fake):
    eng, _ = fake
    pretend_playing(eng, P["techno"])
    eng.set_transpose(6, semitones=5)
    with eng._lock:
        events = eng._bar_boundary(0)
    for hits in events.values():
        for hit in hits:
            assert len(hit) == 5  # (track, note, vel, gate, offset)
    assert eng.view_state()["transpose"] == {6: 5}
    assert eng.view_state()["work"][6] == mutate.working(P["techno"])[6]  # _work shape unchanged


# ---- pitch block and per-track status ------------------------------------

def test_pitch_block_counts_the_tune_whiplash_sent(fake):
    eng, _ = fake
    pretend_playing(eng, P["techno"])
    tracks = eng.tracks_summary()
    bass = tracks["6"]["pitch"]
    assert (bass["low"], bass["high"], bass["low_name"]) == (53, 53, "F4")
    assert bass["semitones_from_native"] == [-7, -7] and bass["tune"] is None and bass["transpose"] == 0
    assert bass["register_shift"] == 12
    assert tracks["1"]["pitch"] is None  # an untuned drum part has no pitch block
    eng.set_param(6, 76, param="tune")
    assert eng.tracks_summary()["6"]["pitch"]["semitones_from_native"] == [5, 5]
    eng.set_param(1, 52, param="tune")
    kick = eng.tracks_summary()["1"]["pitch"]
    assert kick["semitones_from_native"] == [-12, -12] and kick["tune"] == 52


def test_status_tracks_block(fake):
    eng, _ = fake
    pretend_playing(eng, P["techno"])
    status = eng.status()
    assert status["roles_assumed"] is True and "ask the user" in status["kit_note"]
    assert "C5 = MIDI 60" in status["pitch_note"]
    six = status["tracks"]["6"]
    assert six["role"] == "bass (assumed)" and six["slot"] is None and six["tune"] is None
    assert six["part"] == "generated" and six["muted"] is False and six["last_cc"] == {}
    assert set(status["tracks"]) == {str(t) for t in range(1, 9)}
    eng.set_param(6, 9, param="sample_slot")
    eng.set_param(6, 40, param="filter_freq")
    eng.set_param(11, 70, cc=30)  # a track the pattern doesn't use
    eng.set_mute(3, True)
    status = eng.status()
    six = status["tracks"]["6"]
    assert six["slot"] == 9 and six["last_cc"] == {"filter_freq": 40}
    assert status["tracks"]["11"] == {"role": None, "slot": None, "tune": None, "transpose": 0, "pitch": None,
                                      "muted": False, "part": None, "last_cc": {"cc 30": 70}}
    assert status["tracks"]["3"]["muted"] is True


def test_panic_ccs_are_not_reported_as_track_params(fake):
    eng, _ = fake
    eng.play(P["techno"], bpm=300, bars=1)
    finish(eng)  # the run's panic sent All Notes Off (CC 123) on channels 1-8
    for entry in eng.status()["tracks"].values():
        assert "cc 123" not in entry["last_cc"]


# ---- tools ---------------------------------------------------------------

def test_transpose_tool(tool_engine):
    eng, port = tool_engine()
    out = call("whiplash_transpose", track=6, octaves=1)
    assert not out["success"] and "play_pattern" in out["error"]
    call("whiplash_play_pattern", genre="techno", bpm=300)
    out = call("whiplash_transpose", track=6, semitones=-5)
    assert out["success"] and out["transpose"] == -5 and out["all"] == {"6": -5}
    assert out["pitch"]["low"] == 48 and "whiplash_transpose" in out["pitch_note"]
    out = call("whiplash_transpose", track=6, semitones=200)
    assert not out["success"]
    assert call("whiplash_status")["transpose"] == {"6": -5}
    call("whiplash_stop")
    assert call("whiplash_status")["transpose"] == {}


def test_play_tool_reports_tracks_with_pitch(tool_engine):
    tool_engine()
    out = call("whiplash_play_pattern", genre="techno", bpm=300, transpose={"6": 12})
    assert out["mode"] == "started" and out["roles_assumed"] and "ask the user" in out["kit_note"]
    assert out["tracks"]["6"]["role"] == "bass (assumed)" and out["tracks"]["6"]["pitch"]["low"] == 65
    out = call("whiplash_play_pattern", genre="deephouse", bpm=300, transpose={"7": -12})
    assert out["mode"] == "queued" and out["transpose_carried"] == {"6": 12}
    # the queued result describes the NEXT pattern with the transposes it will play with
    assert out["tracks"]["7"]["role"] == "minor chord (assumed)" and out["tracks"]["7"]["transpose"] == -12
    assert out["tracks"]["6"]["transpose"] == 12
    out = call("whiplash_play_pattern", genre="techno", transpose={"6": 99})
    assert not out["success"]
    call("whiplash_stop")


def test_transpose_schemas():
    s = schemas.SCHEMAS["whiplash_transpose"]
    assert s["parameters"]["required"] == ["track"]
    assert s["parameters"]["properties"]["semitones"]["maximum"] == engine.TRANSPOSE_MAX
    assert "whiplash:digitakt" in s["description"]
    play = schemas.SCHEMAS["whiplash_play_pattern"]["parameters"]["properties"]["transpose"]
    assert play["type"] == "object" and play["additionalProperties"]["type"] == "integer"
    assert "whiplash:digitakt" in schemas.SCHEMAS["whiplash_status"]["description"]


# ---- amp_mode ------------------------------------------------------------

def test_amp_mode_is_cc87_and_a_switch(fake):
    p = ccmap.PARAMS["amp_mode"]
    assert (p.cc, p.group, p.min, p.max, p.discrete) == (87, "amp", 0, 1, True)
    assert p.nrpn == (1, 40)  # documentation only
    assert "127" in ccmap.PARAMS["amp_hold"].description and "NOTE" in ccmap.PARAMS["amp_hold"].description
    eng, port = fake
    eng.ensure_port()
    assert eng.set_param(6, 1, param="amp_mode") == {"track": 6, "cc": 87, "value": 1, "param": "amp_mode"}
    for bad in (2, 127):
        with pytest.raises(engine.WhiplashError):
            eng.set_param(6, bad, param="amp_mode")
    eng.play(P["techno"], bpm=300)
    with pytest.raises(engine.WhiplashError, match="switch"):
        eng.ramp(6, 1, param="amp_mode", start=0, bars=1)
    eng.stop()
    assert [m.value for m in port.messages if m.type == "control_change" and m.control == 87] == [1]


# ---- bundled skill -------------------------------------------------------

class SkillCtx:
    def __init__(self, fail=False):
        self.tools, self.skills, self.fail = [], [], fail

    def register_tool(self, name, **kw):
        self.tools.append(name)

    def register_skill(self, name, path, description="", frontmatter=None):
        if self.fail:
            raise ValueError("boom")
        self.skills.append((name, Path(path), description))


def test_register_registers_the_skill():
    ctx = SkillCtx()
    whiplash.register(ctx)
    [(name, path, description)] = ctx.skills
    assert name == "digitakt" and ":" not in name and re.fullmatch(r"[a-zA-Z0-9_-]+", name)
    assert path.is_file() and path.name == "SKILL.md" and path == ROOT / "skills" / "digitakt" / "SKILL.md"
    assert description
    assert set(ctx.tools) == set(tools.HANDLERS)


def test_register_without_the_skill_api_or_when_it_fails():
    class Old:
        def __init__(self):
            self.tools = []

        def register_tool(self, name, **kw):
            self.tools.append(name)
    old = Old()
    whiplash.register(old)  # an older Hermes: no register_skill, tools still load
    assert set(old.tools) == set(tools.HANDLERS)
    broken = SkillCtx(fail=True)
    whiplash.register(broken)
    assert set(broken.tools) == set(tools.HANDLERS) and broken.skills == []


def test_skill_frontmatter_and_content():
    text = (ROOT / "skills" / "digitakt" / "SKILL.md").read_text()
    assert text.startswith("---\n")
    front = yaml.safe_load(text.split("---\n")[1])
    assert front["name"] == "digitakt" and front["description"]
    body = text.lower()
    for stale in ("can't switch samples", "cannot switch samples", "can't author", "no way to change samples"):
        assert stale not in body
    for fact in ("note **60", "whiplash_transpose", "amp_mode", "hermes gateway restart", "cc 19", "c5 = midi 60"):
        assert fact in body, fact


def test_readme_has_an_updating_section():
    readme = (ROOT / "README.md").read_text()
    section = readme.split("## Updating", 1)[1].split("\n## ", 1)[0]
    assert "hermes gateway restart" in section and "whiplash-digitakt" in section
