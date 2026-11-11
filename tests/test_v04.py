"""v0.4: sample-slot select over plain MIDI, and the clock-only transport option."""
import pytest

from whiplash import ccmap, engine, patterns, schemas, tools
from test_whiplash import FakePort, call, make_engine, tool_engine  # noqa: F401  (fixture)
from test_live import finish, wait_bar

P = patterns.PATTERNS
BAR = engine.TICKS_PER_BAR


@pytest.fixture
def fake():
    eng, port = make_engine()
    yield eng, port
    eng.shutdown()


# ---- sample slot ---------------------------------------------------------

def test_sample_slot_is_cc19_in_src_and_a_switch():
    p = ccmap.PARAMS["sample_slot"]
    assert (p.cc, p.group, p.min, p.max, p.discrete, p.lsb_cc) == (19, "src", 0, 127, True, None)
    assert p.nrpn == (1, 8)  # documentation only
    for alias in ("sample", "Sample Select", "smp", "slot", "sample-slot"):
        assert ccmap.lookup(alias) is p


def test_set_sample_slot_by_name_sends_cc19_on_the_track_channel(fake):
    eng, port = fake
    eng.ensure_port()
    out = eng.set_param(7, 12, param="sample_slot")
    assert out == {"track": 7, "cc": 19, "value": 12, "param": "sample_slot"}
    m = port.messages[-1]
    assert (m.type, m.channel, m.control, m.value) == ("control_change", 6, 19, 12)
    assert len(port.messages) == 1  # one plain CC: no bank select, no NRPN, no SysEx


def test_sample_slot_rejects_out_of_range_and_ramps(fake):
    eng, port = fake
    eng.ensure_port()
    for bad in (128, -1, 3.5, "x"):
        with pytest.raises(engine.WhiplashError):
            eng.set_param(1, bad, param="sample_slot")
    eng.play(P["techno"], bpm=300)
    with pytest.raises(engine.WhiplashError, match="switch"):
        eng.ramp(1, 20, param="sample_slot", start=0, bars=1)
    eng.stop()
    assert not [m for m in port.messages if m.type == "control_change" and m.control == 19]


def test_raw_sample_cc_and_nrpns_stay_blocked(fake):
    eng, port = fake
    eng.ensure_port()
    with pytest.raises(engine.WhiplashError, match="sample_slot"):
        eng.set_param(1, 5, cc=19)  # only via the named, validated path
    with pytest.raises(engine.WhiplashError, match="blocked"):
        eng.set_param(1, 1, cc=24)  # sample bank select
    for addr in ([1, 3], [1, 8], [1, 9]):
        with pytest.raises(engine.WhiplashError, match="blocked"):
            eng.set_param(1, 5, nrpn=addr)
    for cc in (0, 32):  # MIDI bank select
        with pytest.raises(engine.WhiplashError, match="blocked"):
            eng.set_param(1, 0, cc=cc)
    assert port.messages == []


def test_sysex_and_program_change_still_refused(fake):
    mido = pytest.importorskip("mido")
    eng, port = fake
    eng.ensure_port()
    for msg in (mido.Message("sysex", data=[0, 32, 60]), mido.Message("program_change", program=5)):
        with pytest.raises(engine.WhiplashError, match="refusing"):
            eng.send(msg)
    assert port.messages == []


def test_select_sample_tool(tool_engine):
    eng, port = tool_engine()
    out = call("whiplash_select_sample", track=8, slot=3)
    assert out["success"] and (out["track"], out["slot"], out["cc"]) == (8, 3, 19)
    assert "can't list" in out["note"]
    m = port.messages[-1]
    assert (m.channel, m.control, m.value) == (7, 19, 3)
    for bad in (dict(track=8, slot=200), dict(track=17, slot=1), dict(track=1)):
        res = call("whiplash_select_sample", **bad)
        assert not res["success"] and res["error"]
    assert call("whiplash_set_param", track=2, param="sample", value=9)["cc"] == 19


def test_list_params_shows_sample_slot(tool_engine):
    tool_engine()
    out = call("whiplash_list_params")
    src = {p["name"]: p for p in out["params"]["src"]}
    assert src["sample_slot"]["cc"] == 19 and src["sample_slot"]["range"] == [0, 127]
    assert src["sample_slot"]["discrete"] and "sample" in src["sample_slot"]["aliases"]
    assert out["count"] == 38 and "can't list" in out["notes"]
    assert "sample_bank" not in str(out["params"])


def test_select_sample_schema():
    s = schemas.SCHEMAS["whiplash_select_sample"]
    assert s["parameters"]["required"] == ["track", "slot"]
    assert s["parameters"]["properties"]["slot"]["maximum"] == 127
    assert "can't list" in s["description"]


# ---- transport -----------------------------------------------------------

def test_default_sends_start_and_stop(fake):
    eng, port = fake
    out = eng.play(P["techno"], bpm=300, bars=1)
    assert out["send_transport"] is True
    finish(eng)
    kinds = [m.type for m in port.messages]
    assert kinds.count("start") == 1 and kinds.count("stop") == 1 and kinds[0] == "start"
    assert eng.status()["transport_mode"] == "start_stop"


def test_clock_only_sends_neither_start_nor_stop(fake):
    eng, port = fake
    out = eng.play(P["techno"], bpm=300, bars=1, send_transport=False)
    assert out["send_transport"] is False and eng.status()["transport_mode"] == "clock_only"
    finish(eng)
    eng.stop()  # idle panic in clock-only mode: still no Stop
    assert port.count("clock") == BAR
    assert port.count("start") == 0 and port.count("stop") == 0
    assert port.count("control_change", control=123) >= 8  # All Notes Off still goes out
    assert port.count("note_on") == port.count("note_off")


def test_clock_only_explicit_stop_mid_beat(fake):
    eng, port = fake
    eng.play(P["deephouse"], bpm=300, send_transport=False)
    wait_bar(eng, 1)
    assert eng.stop()["was_playing"]
    assert port.count("start") == 0 and port.count("stop") == 0
    assert port.count("note_on") == port.count("note_off")


@pytest.mark.parametrize("raw, expected", [
    (None, True), ("1", True), ("true", True), ("0", False), ("false", False), ("clock_only", False),
    ("OFF", False), ("bogus", True)])
def test_env_default(monkeypatch, raw, expected):
    if raw is not None:
        monkeypatch.setenv(engine.TRANSPORT_ENV, raw)
    assert engine.default_send_transport() is expected


def test_env_default_applies_and_tool_arg_overrides(monkeypatch, fake):
    eng, port = fake
    monkeypatch.setenv(engine.TRANSPORT_ENV, "0")
    assert eng.status()["transport_mode"] == "clock_only"  # before any run, status shows the default
    eng.play(P["techno"], bpm=300, bars=1)
    finish(eng)
    assert port.count("start") == 0 and port.count("stop") == 0
    eng.play(P["techno"], bpm=300, bars=1, send_transport=True)
    finish(eng)
    assert port.count("start") == 1 and port.count("stop") == 1


def test_bad_send_transport_rejected_before_touching_the_beat(fake):
    eng, _ = fake
    eng.play(P["techno"], bpm=300)
    with pytest.raises(engine.WhiplashError, match="send_transport"):
        eng.play(P["soul"], send_transport="maybe")
    assert eng.playing() and eng.status()["queued"] is None


def test_queued_switch_keeps_the_running_mode(fake):
    eng, port = fake
    eng.play(P["techno"], bpm=300, send_transport=False)
    out = eng.play(P["soul"], bpm=300)  # no arg: keep clock-only, queue on the bar
    assert out["mode"] == "queued" and out["send_transport"] is False
    out = eng.play(P["breaks"], bpm=300, send_transport=False)  # same mode given explicitly: still queued
    assert out["mode"] == "queued"
    eng.stop()
    assert port.count("start") == 0 and port.count("stop") == 0


def test_changing_mode_while_playing_restarts(fake):
    eng, port = fake
    eng.play(P["techno"], bpm=300)  # start/stop
    out = eng.play(P["techno"], bpm=300, send_transport=False)
    assert out["mode"] == "started" and out["was_playing"]
    assert port.count("start") == 1 and port.count("stop") == 1  # old run stopped in its own mode
    eng.stop()
    assert port.count("stop") == 1  # the clock-only run sends no Stop
    out = eng.play(P["techno"], bpm=300, send_transport=True)
    assert out["mode"] == "started"
    eng.stop()
    assert port.count("start") == 2 and port.count("stop") == 2


def test_play_tool_always_carries_the_overlap_warning(tool_engine):
    tool_engine()
    out = call("whiplash_play_pattern", genre="techno", bpm=300)
    assert out["mode"] == "started" and out["transport_mode"] == "start_stop"
    assert "empty pattern" in out["overlap_warning"] and "send_transport=false" in out["overlap_warning"]
    out = call("whiplash_play_pattern", genre="deephouse", bpm=300)
    assert out["mode"] == "queued" and "empty pattern" in out["overlap_warning"]
    out = call("whiplash_play_pattern", genre="deephouse", bpm=300, send_transport=False)
    assert out["mode"] == "started" and out["send_transport"] is False
    assert "Clock only" in out["overlap_warning"]
    out = call("whiplash_play_pattern", genre="soul", bpm=300)
    assert out["mode"] == "queued" and out["transport_mode"] == "clock_only" and "Clock only" in out["overlap_warning"]
    status = call("whiplash_status")
    assert status["transport_mode"] == "clock_only" and status["send_transport"] is False
    call("whiplash_stop")


def test_play_schema_has_send_transport():
    props = schemas.SCHEMAS["whiplash_play_pattern"]["parameters"]["properties"]
    assert props["send_transport"]["type"] == "boolean"
    assert "overlap_warning" in schemas.SCHEMAS["whiplash_play_pattern"]["description"]


def test_tools_in_manifest_order():
    assert list(tools.HANDLERS)[4] == "whiplash_select_sample" == list(schemas.SCHEMAS)[4]
    assert list(tools.HANDLERS)[5] == "whiplash_label_tracks" == list(schemas.SCHEMAS)[5]  # v0.5.3
    assert list(tools.HANDLERS)[6] == "whiplash_transpose" == list(schemas.SCHEMAS)[6]  # v0.5
    assert list(tools.HANDLERS)[7] == "whiplash_write_part" == list(schemas.SCHEMAS)[7]  # v0.5.1
    assert list(tools.HANDLERS)[8] == "whiplash_set_progression" == list(schemas.SCHEMAS)[8]  # v0.6.0
    # v0.4's 12 tools, v0.5's transpose, v0.5.1's write_part, v0.5.3's label_tracks, v0.6.0's set_progression,
    # then the visualiser's two
    assert len(tools.HANDLERS) == 18 and list(tools.HANDLERS)[16:] == ["whiplash_open_view", "whiplash_close_view"]
