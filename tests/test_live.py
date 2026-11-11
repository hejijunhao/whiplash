"""v0.3 live control: named params, ramps, bar-quantized switching, mutate, hot-plug notify."""
import collections
import json
import time

import pytest
import yaml

import whiplash
from whiplash import ccmap, engine, mutate, patterns, schemas, tools
from test_whiplash import FakePort, call, make_engine

P = patterns.PATTERNS
BAR = engine.TICKS_PER_BAR


@pytest.fixture
def fake():
    eng, port = make_engine()
    yield eng, port
    port.fail_after = None
    eng.shutdown()


@pytest.fixture
def tool_engine(monkeypatch):
    installed = []

    def install(**kw):
        eng = engine.Engine(**kw)
        monkeypatch.setattr(tools, "ENGINE", eng)
        installed.append(eng)
        return eng
    yield install
    for eng in installed:
        eng.shutdown()


def opener_for(port):
    """Fake opener: None -> fallback virtual, 'Whiplash' -> explicit virtual, other names -> hardware."""
    def opener(name):
        return port, name or engine.VIRTUAL_NAME, name in (None, engine.VIRTUAL_NAME)
    return opener


def timeline(port):
    """[(bar, clocks_before, msg)] for every non-clock message, bar = clocks before it // 96."""
    clocks, out = 0, []
    for m in list(port.messages):
        if m.type == "clock":
            clocks += 1
        else:
            out.append((clocks // BAR, clocks, m))
    return out


def ons_per_bar(port, channel):
    return collections.Counter(bar for bar, _, m in timeline(port) if m.type == "note_on" and m.channel == channel)


def ccs(port, channel, control):
    return [(clocks, m.value) for _, clocks, m in timeline(port)
            if m.type == "control_change" and m.channel == channel and m.control == control]


def wait_bar(eng, bar, timeout=6.0):
    end = time.monotonic() + timeout
    while eng.bar < bar and eng.playing():
        assert time.monotonic() < end, f"sequencer never reached bar {bar}"
        time.sleep(0.01)


def finish(eng, timeout=8.0):
    eng._thread.join(timeout=timeout)
    assert not eng.playing()


def pretend_playing(eng, pattern):
    """Load a pattern without starting the thread, to drive _bar_boundary by hand."""
    eng.ensure_port()
    eng.playing = lambda: True
    with eng._lock:
        eng._load(pattern, pattern.bpm, None, 0)
    return eng


def bar_events(eng, bar):
    with eng._lock:
        events = eng._bar_boundary(bar)
    return sorted((s, *e) for s, evs in events.items() for e in evs)


# ---- manifest / catalog --------------------------------------------------

def test_manifest_tools_equal_schemas_and_registration():
    root = whiplash.__path__[0]
    manifest = yaml.safe_load(open(root + "/plugin.yaml"))
    assert manifest["provides_tools"] == list(schemas.SCHEMAS)  # same names, same order
    assert set(schemas.SCHEMAS) == set(tools.HANDLERS)
    assert "capabilities" not in manifest  # privileged consent ids in a Hermes manifest; Whiplash needs none
    registered = []

    class Ctx:
        def register_tool(self, name, **kw):
            registered.append(name)
    whiplash.register(Ctx())
    assert registered == manifest["provides_tools"]


def test_catalog_entry_draft_matches_manifest():
    root = whiplash.__path__[0]
    manifest = yaml.safe_load(open(root + "/plugin.yaml"))
    entry = yaml.safe_load(open(root + "/docs/catalog-entry.yaml"))
    assert entry["name"] == "whiplash" and entry["version"] == manifest["version"]
    assert entry["requires_hermes"] == manifest["requires_hermes"]
    assert entry["capabilities"]["provides_tools"] == manifest["provides_tools"]
    assert entry["capabilities"]["provides_hooks"] == manifest["provides_hooks"]
    assert entry["capabilities"]["requires_env"] == []


def test_schemas_are_well_formed():
    for name, schema in schemas.SCHEMAS.items():
        assert schema["name"] == name and schema["parameters"]["type"] == "object"
        json.dumps(schema)


# ---- parameter map -------------------------------------------------------

EXPECTED_CC = {
    "mute": 94, "track_level": 95, "amp_volume": 89, "pan": 90, "sample_level": 23, "tune": 16, "play_mode": 17,
    "sample_start": 20, "sample_length": 21, "loop_pos": 22, "filter_freq": 74, "filter_reso": 75,
    "filter_env_depth": 77, "filter_attack": 70, "filter_decay": 71, "filter_sustain": 72, "filter_release": 73,
    "filter_env_delay": 91, "filter_key_tracking": 92, "amp_attack": 79, "amp_hold": 80, "amp_decay": 81,
    "amp_sustain": 82, "amp_release": 83, "delay_send": 84, "reverb_send": 85, "chorus_send": 12, "overdrive": 57,
    "bit_reduction": 54, "sample_rate_reduction": 55, "lfo1_speed": 102, "lfo1_depth": 109, "lfo2_speed": 112,
    "lfo2_depth": 119, "lfo3_speed": 78, "lfo3_depth": 86, "sample_slot": 19, "amp_mode": 87,
}


def test_param_map_matches_the_manual():
    assert {name: p.cc for name, p in ccmap.PARAMS.items()} == EXPECTED_CC
    lsb = {name: p.lsb_cc for name, p in ccmap.PARAMS.items() if p.lsb_cc}
    assert lsb == {"lfo1_speed": 58, "lfo1_depth": 59, "lfo2_speed": 60, "lfo2_depth": 61, "lfo3_speed": 62,
                   "lfo3_depth": 63}
    for p in ccmap.PARAMS.values():
        assert p.cc not in ccmap.BLOCKED_CCS and 0 <= p.min < p.max <= 127 and p.group in ccmap.GROUPS
        if p.centered:
            assert p.default == 64 and p.min <= 64 <= p.max
    assert (ccmap.PARAMS["tune"].min, ccmap.PARAMS["tune"].max) == (4, 124)
    assert ccmap.PARAMS["sample_start"].max == ccmap.PARAMS["sample_length"].max == 120
    assert ccmap.PARAMS["filter_key_tracking"].max == 100 and ccmap.PARAMS["play_mode"].max == 3
    assert not set(ccmap.ALIASES) & set(ccmap.PARAMS)
    assert 24 in ccmap.BLOCKED_CCS and 19 not in ccmap.BLOCKED_CCS and ccmap.NAMED_ONLY_CCS == {19: "sample_slot"}
    assert {(1, 3), (1, 8), (1, 9)} == ccmap.BLOCKED_NRPNS


@pytest.mark.parametrize("name, canonical", [
    ("cutoff", "filter_freq"), ("Filter Cutoff", "filter_freq"), ("filter-freq", "filter_freq"),
    ("resonance", "filter_reso"), ("srr", "sample_rate_reduction"), ("decay", "amp_decay"),
    ("level", "track_level"), ("volume", "amp_volume"), ("PAN", "pan"), ("lfo1 depth", "lfo1_depth")])
def test_param_aliases(name, canonical):
    assert ccmap.lookup(name).name == canonical


def test_unknown_param_suggests_close_matches(fake):
    eng, port = fake
    eng.ensure_port()
    with pytest.raises(engine.WhiplashError, match="did you mean filter_freq"):
        eng.set_param(1, 10, param="cutof")
    with pytest.raises(engine.WhiplashError, match="whiplash_list_params"):
        eng.set_param(1, 10, param="sample_bank")  # bank select is not a param
    assert port.messages == []


def test_named_params_clamp_or_reject(fake):
    eng, port = fake
    eng.ensure_port()
    assert eng.set_param(1, 0, param="tune") == {"track": 1, "cc": 16, "value": 4, "param": "tune", "clamped": True}
    assert eng.set_param(1, 127, param="tune")["value"] == 124
    assert eng.set_param(1, 64, param="tune") == {"track": 1, "cc": 16, "value": 64, "param": "tune"}
    assert eng.set_param(2, 127, param="sample_start")["value"] == 120
    assert eng.set_param(2, 110, param="key_tracking")["value"] == 100
    for bad in (dict(param="play_mode", value=4), dict(param="mute", value=2), dict(param="cutoff", value=128),
                dict(param="cutoff", value=-1), dict(param="cutoff", value=1.5)):
        with pytest.raises(engine.WhiplashError):
            eng.set_param(1, bad.pop("value"), **bad)
    sent = [m.control for m in port.messages]
    assert sent == [16, 16, 16, 20, 92]  # named params send plain CC only, never NRPN
    assert eng.set_param(3, 2, param="play_mode")["value"] == 2


def test_list_params_tool():
    out = call("whiplash_list_params")
    assert out["success"] and out["count"] == len(ccmap.PARAMS)
    assert list(out["params"]) == list(ccmap.GROUPS)
    names = [p["name"] for group in out["params"].values() for p in group]
    assert sorted(names) == sorted(ccmap.PARAMS)
    freq = next(p for p in out["params"]["filter"] if p["name"] == "filter_freq")
    assert freq["cc"] == 74 and "cutoff" in freq["aliases"] and freq["range"] == [0, 127]
    pan = next(p for p in out["params"]["amp"] if p["name"] == "pan")
    assert pan["centered"] and pan["default"] == 64


# ---- ramps ---------------------------------------------------------------

def test_ramp_needs_a_running_pattern_and_valid_input(fake):
    eng, port = fake
    eng.ensure_port()
    with pytest.raises(engine.WhiplashError, match="start a pattern"):
        eng.ramp(1, 100, param="cutoff", start=0, bars=1)
    eng.play(P["techno"], bpm=300)
    before = len([m for m in port.messages if m.type == "control_change"])
    for kw in (dict(beats=4, bars=1), dict(), dict(bars=0), dict(beats=-1), dict(bars=129), dict(beats="x"),
               dict(bars=1, curve="wobble"), dict(bars=1, to=128), dict(bars=1, start=200),
               dict(bars=1, param="mute"), dict(bars=1, param="play_mode"), dict(bars=1, param=None, cc=19),
               dict(bars=1, param="cutoff", cc=74), dict(bars=1, param="nope")):
        args = {"to": 100, "param": "cutoff", "start": 0, **kw}
        with pytest.raises(engine.WhiplashError):
            eng.ramp(1, args.pop("to"), **args)
    with pytest.raises(engine.WhiplashError, match="give 'from'"):
        eng.ramp(1, 100, param="cutoff", bars=1)  # nothing sent yet, so no implicit start
    assert len([m for m in port.messages if m.type == "control_change"]) == before
    assert eng.ramps() == []


def test_ramp_is_clock_synced_monotonic_and_never_repeats(fake):
    eng, port = fake
    eng.play(P["techno"], bpm=300, bars=3)
    out = eng.ramp(6, 127, param="cutoff", start=0, bars=1)
    assert out["ramp_id"] == "r1" and out["cc"] == 74 and out["track"] == 6
    finish(eng)
    sent = ccs(port, 5, 74)
    values = [v for _, v in sent]
    assert values[0] == 0 and values[-1] == 127
    assert values == sorted(set(values))  # strictly increasing: one message per integer change
    assert sent[-1][0] - sent[0][0] in (BAR - 1, BAR)  # exactly one bar of clock ticks
    assert eng.ramps() == []


def test_ramp_in_beats_small_range_sends_each_value_once(fake):
    eng, port = fake
    eng.play(P["techno"], bpm=300, bars=2)
    eng.ramp(1, 10, param="reverb_send", start=0, beats=2)
    finish(eng)
    sent = ccs(port, 0, 85)
    assert [v for _, v in sent] == list(range(11))
    assert 2 * engine.PPQN - 3 <= sent[-1][0] - sent[0][0] <= 2 * engine.PPQN  # rounding reaches 10 a tick or two early


def test_ramp_defaults_from_to_the_last_value_sent(fake):
    eng, port = fake
    eng.play(P["techno"], bpm=300, bars=2)
    eng.set_param(1, 20, param="cutoff")
    out = eng.ramp(1, 30, param="cutoff", beats=1)
    assert out["from"] == 20
    finish(eng)
    assert [v for _, v in ccs(port, 0, 74)] == list(range(20, 31))  # 20 is not sent twice


def test_ramp_curves():
    def mid(curve):
        return engine.Ramp("r", 1, 74, "x", 0, 100, 100, curve, elapsed=50).value()
    assert mid("exp") < mid("linear") == 50 < mid("log")
    for curve in engine.CURVES:
        r = engine.Ramp("r", 1, 74, "x", 10, 90, 7, curve)
        values = []
        for _ in range(7):
            r.elapsed += 1
            values.append(r.value())
        assert values == sorted(values) and values[-1] == 90


def test_ramps_run_concurrently_replace_and_cancel(fake):
    eng, port = fake
    eng.play(P["techno"], bpm=300)
    a = eng.ramp(1, 127, param="cutoff", start=0, bars=8)
    b = eng.ramp(2, 127, param="reverb", start=0, bars=8)
    c = eng.ramp(3, 127, cc=13, start=0, bars=8)  # raw CC ramps too
    assert [r["id"] for r in eng.ramps()] == [a["ramp_id"], b["ramp_id"], c["ramp_id"]]
    d = eng.ramp(1, 0, param="filter_freq", start=127, bars=8)  # same track+CC: replaces a
    assert d["replaced"] == a["ramp_id"]
    assert [r["id"] for r in eng.ramps()] == [b["ramp_id"], c["ramp_id"], d["ramp_id"]]
    assert eng.cancel_ramps(b["ramp_id"]) == [b["ramp_id"]]
    with pytest.raises(engine.WhiplashError, match="no active ramp"):
        eng.cancel_ramps(b["ramp_id"])
    out = eng.set_param(3, 5, cc=13)  # an instant change wins over a running ramp
    assert out["cancelled_ramp"] == c["ramp_id"]
    time.sleep(0.1)
    sent_b = len(ccs(port, 1, 85))
    time.sleep(0.2)
    assert len(ccs(port, 1, 85)) == sent_b  # cancelled ramp sends nothing more
    assert eng.cancel_ramps("all") == [d["ramp_id"]] and eng.ramps() == []
    eng.ramp(1, 127, param="cutoff", start=0, bars=8)
    assert eng.stop()["ramps_cancelled"] == ["r5"]


def test_ramp_tool_and_status(tool_engine):
    eng = tool_engine(opener=lambda name: (FakePort(), "Fake", False))
    assert "start a pattern" in call("whiplash_ramp_param", track=1, param="cutoff", to=90, bars=1, **{"from": 0})["error"]
    call("whiplash_play_pattern", genre="deephouse", bpm=300)
    out = call("whiplash_ramp_param", track=7, param="cutoff", to=127, bars=4, curve="exp", **{"from": 10})
    assert out["success"] and out["ramp_id"] == "r1" and out["curve"] == "exp"
    assert "missing required argument 'to'" in call("whiplash_ramp_param", track=7, param="cutoff", bars=1)["error"]
    time.sleep(0.2)
    ramp = call("whiplash_status")["ramps"][0]
    assert ramp["id"] == "r1" and 0 < ramp["progress"] < 1 and ramp["remaining_beats"] < 16
    assert call("whiplash_ramp_param", cancel="all")["cancelled"] == ["r1"]


# ---- bar-quantized switching ---------------------------------------------

def test_live_switch_lands_on_the_bar_without_stop_or_start(fake):
    eng, port = fake
    eng.play(P["techno"], bpm=300)
    eng.set_mute(3, True)
    eng.ramp(6, 127, param="cutoff", start=0, bars=2)
    out = eng.play(P["soul"], bpm=280)
    assert out == {"mode": "queued", "switch_at_bar": 1, "replaced_queued": None, "send_transport": True}
    assert eng.status()["queued"] == {"pattern": "soul", "bpm": 280, "switch_at_bar": 1, "key": "A minor",
                                      "transpose": {}}  # v0.6.0: the key the queued pattern plays in
    wait_bar(eng, 3)
    st = eng.status()
    assert st["pattern"] == "soul" and st["bpm"] == 280 and st["queued"] is None and st["muted"] == [3]
    eng.stop()
    kicks = ons_per_bar(port, 0)
    assert kicks[0] == 4  # techno four-on-the-floor
    assert kicks[1] == 3 and kicks[2] == 4  # soul bars 0 and 1, from the switch bar on
    assert ons_per_bar(port, 2) == {}  # the clap mute carried over
    values = [v for _, v in ccs(port, 5, 74)]
    assert values[-1] == 127 and values == sorted(set(values))  # the ramp carried over and finished
    kinds = [m.type for m in port.messages]
    assert kinds.count("start") == 1 and kinds.count("stop") == 1 and kinds[-1] == "stop"
    assert port.count("note_on") == port.count("note_off")


def test_second_queue_replaces_and_bars_count_from_the_switch(fake):
    eng, port = fake
    eng.play(P["techno"], bpm=300)
    eng.play(P["soul"], bpm=300)
    out = eng.play(P["breaks"], bpm=300, bars=1)
    assert out["replaced_queued"] == "soul"
    finish(eng)
    assert port.count("clock") == 2 * BAR  # techno bar 0, breaks bar 1, then the bars limit ends it
    assert ons_per_bar(port, 0) == {0: 4, 1: 2}  # breaks kick bar 0: x.........x.....
    assert port.count("start") == 1 and port.count("stop") == 1


def test_bad_queued_call_leaves_the_beat_alone(fake):
    eng, _ = fake
    eng.play(P["techno"], bpm=300)
    with pytest.raises(engine.WhiplashError):
        eng.play(P["soul"], bpm=999)
    assert eng.status()["queued"] is None and eng.playing()


def test_new_port_restarts_instead_of_queueing(fake):
    eng, port = fake
    eng.play(P["techno"], bpm=300)
    eng.set_mute(1, True)
    out = eng.play(P["soul"], bpm=300, port="Other")
    assert out["mode"] == "started" and out["was_playing"] and out["mutes_cleared"] == [1]
    time.sleep(0.1)
    assert eng.port_name == "Other" and port.count("start") == 2


def test_switch_resets_mutations_but_keeps_mutes_and_drops(fake):
    eng, port = fake
    eng.play(P["techno"], bpm=300)
    eng.mutate_density([4], "thin")
    eng.mutate_swing(70)
    eng.mutate_humanize(0.5)
    eng.set_mute(2, True)
    drop = eng.schedule_drop([1], 4)
    eng.play(P["deephouse"], bpm=300)
    wait_bar(eng, 2)
    m = eng.mutations()
    assert m["density"] == {} and m["humanize"] == 0 and m["swing"] == 55  # deep house's own swing
    assert m["drops"] == {"1": {"from_bar": drop["from_bar"], "returns_at_bar": drop["returns_at_bar"]}}
    assert eng.status()["muted"] == [2]


# ---- mutate (deterministic, driven bar by bar) ---------------------------

def test_thin_is_deterministic_bounded_and_monotonic():
    hats = mutate.working(P["deephouse"])[4][0]
    r = lambda: mutate.rng(7, "density", 4, 0)
    light, heavy = mutate.thin(hats, 0.25, r()), mutate.thin(hats, 0.75, r())
    assert light == mutate.thin(hats, 0.25, r())  # same seed, same result
    assert set(heavy) < set(light) < set(hats)  # thinning more drops a superset
    assert len(mutate.thin(hats, 1.0, r())) == 1
    assert mutate.thin([], 1.0, r()) == []
    on_beat = {h for h in hats if h[0] % 4 == 0}
    assert on_beat <= set(light)  # the beat survives a light thin: offbeat/weak hits go first


def test_thicken_adds_quiet_ghosts_on_empty_steps():
    bass = mutate.working(P["deephouse"])[6][0]
    out = mutate.thicken(bass, 0.5, mutate.rng(0, "density", 6, 0))
    added = [h for h in out if h not in bass]
    assert added and len(out) == len({h[0] for h in out})  # one hit per step
    assert all(h[0] not in {b[0] for b in bass} for h in added)
    assert all(h[2] < min(b[2] for b in bass) for h in added)
    assert {h[1] for h in added} <= {b[1] for b in bass}  # stays in the bar's notes
    assert mutate.thicken([], 1.0, mutate.rng(0)) == []
    assert len(mutate.thicken(bass, 1.0, mutate.rng(0))) == 16


def test_fill_shapes():
    w = mutate.working(P["techno"])
    assert all(h[0] < 12 for h in mutate.fill(1, w[1][0]))
    snare = mutate.fill(2, w[2][0])
    roll = [h for h in snare if h[0] >= 8]
    assert [h[0] for h in roll] == list(range(8, 16)) and [h[2] for h in roll] == sorted(h[2] for h in roll)
    hats = mutate.fill(4, w[4][0])
    ratchets = [h for h in hats if h[0] >= 12]
    assert len(ratchets) == 8 and {h[4] for h in ratchets} == {0.0, 3.0} and all(h[3] < 1 for h in ratchets)
    assert all(1 <= h[2] <= 127 for t in range(1, 6) for h in mutate.fill(t, w[t][0]))


def test_humanize_is_bounded_and_seeded():
    a = [mutate.humanize(100, 0.0, 1.0, mutate.rng(3, i)) for i in range(200)]
    b = [mutate.humanize(100, 0.0, 1.0, mutate.rng(3, i)) for i in range(200)]
    assert a == b
    assert all(84 <= v <= 116 and -0.25 <= o <= 0.25 for v, o in a)
    assert len({v for v, _ in a}) > 5
    assert mutate.humanize(127, 0.0, 1.0, mutate.rng(1))[0] <= 127


def test_drop_auto_returns_with_a_fill(fake):
    eng = pretend_playing(fake[0], P["techno"])
    eng.bar = 0
    out = eng.schedule_drop([1, 6], 2, fill=True)
    assert out == {"dropped": [1, 6], "from_bar": 1, "returns_at_bar": 3, "fill_at_bar": 2,
                   "fill_tracks": [2, 3, 4, 5]}
    tracks = {bar: collections.Counter(e[1] for e in bar_events(eng, bar)) for bar in range(5)}
    assert tracks[0][1] == 4 and tracks[0][6] == 8
    assert tracks[1][1] == tracks[1][6] == tracks[2][1] == tracks[2][6] == 0
    assert tracks[3][1] == 4 and tracks[3][6] == 8  # back by themselves
    assert tracks[2][4] == 20 and tracks[1][4] == tracks[3][4] == 16  # hat ratchets on the last dropped bar
    assert eng.mutations()["drops"] == {}


def test_fill_lands_on_the_next_bar_only(fake):
    eng = pretend_playing(fake[0], P["techno"])
    eng.bar = 4
    assert eng.schedule_fill() == {"fill_at_bar": 5, "tracks": [1, 2, 3, 4, 5]}
    hats = {bar: sum(e[1] == 4 for e in bar_events(eng, bar)) for bar in (5, 6)}
    assert hats == {5: 20, 6: 16}
    with pytest.raises(engine.WhiplashError, match="drum tracks"):
        eng.schedule_fill([6])


def test_density_and_reset(fake):
    eng = pretend_playing(fake[0], P["techno"])
    pristine = bar_events(eng, 0)
    assert eng.mutate_density([3], 1)["density"] == {"3": 1.0}
    claps = sum(e[1] == 3 for e in bar_events(eng, 1))
    assert claps == 16
    eng.mutate_density([4], "thin")
    assert sum(e[1] == 4 for e in bar_events(eng, 2)) == 8
    assert eng.mutate_density([4], "thin")["density"]["4"] == -0.5  # idempotent, not cumulative
    for bad in (2, "loud", None):
        with pytest.raises(engine.WhiplashError):
            eng.mutate_density([4], bad)
    with pytest.raises(engine.WhiplashError):
        eng.mutate_density([9], 0.5)
    eng.mutate_swing(66)
    assert eng.swing == 0.66
    eng.reset_mutations()
    assert bar_events(eng, 4) == pristine and eng.swing == P["techno"].swing


def test_humanize_is_deterministic_per_seed(fake):
    eng = pretend_playing(fake[0], P["deephouse"])
    eng.mutate_humanize(1)
    a, b = bar_events(eng, 1), bar_events(eng, 1)
    assert a == b
    other = pretend_playing(make_engine()[0], P["deephouse"])
    other.seed = 99
    other.mutate_humanize(1)
    assert bar_events(other, 1) != a
    pristine = pretend_playing(make_engine()[0], P["deephouse"])
    assert len(a) == len(bar_events(pristine, 1))  # loosens hits, never adds or drops them
    assert all(abs(e[5]) <= mutate.HUMANIZE_TICKS for e in a)


def test_mutate_validates_and_needs_a_beat(fake):
    eng, _ = fake
    eng.ensure_port()
    with pytest.raises(engine.WhiplashError, match="nothing is playing"):
        eng.mutate_swing(60)
    eng.play(P["techno"], bpm=300)
    for fn, args in ((eng.mutate_swing, (49,)), (eng.mutate_swing, (81,)), (eng.mutate_humanize, (1.5,)),
                     (eng.schedule_drop, ([1], 0)), (eng.schedule_drop, ([1], 33)), (eng.schedule_drop, ([], 2))):
        with pytest.raises(engine.WhiplashError):
            fn(*args)
    assert eng.mutations()["drops"] == {} and eng.swing == P["techno"].swing


def test_mutate_tool(tool_engine):
    tool_engine(opener=lambda name: (FakePort(), "Fake", False))
    assert "action must be" in call("whiplash_mutate", action="explode")["error"]
    call("whiplash_play_pattern", genre="techno", bpm=300)
    out = call("whiplash_mutate", action="density", tracks=[4], amount="thicken")
    assert out["success"] and out["density"] == {"4": 0.5}
    assert call("whiplash_mutate", action="drop", tracks=[1, 6], bars=2, fill=True)["returns_at_bar"] >= 3
    assert call("whiplash_mutate", action="humanize", amount=0.3)["humanize"] == 0.3
    assert call("whiplash_mutate", action="swing", amount=60)["swing"] == 60
    assert call("whiplash_mutate", action="fill", tracks=2)["tracks"] == [2]
    call("whiplash_play_pattern", genre="soul")
    out = call("whiplash_mutate", action="swing", amount=62)
    assert "resets when it lands" in out["note"]
    assert call("whiplash_mutate", action="reset")["reset"] is True
    assert call("whiplash_status")["mutations"]["drops"] == {}


def test_live_mutations_play_on_the_bar(fake):
    eng, port = fake
    eng.play(P["techno"], bpm=300, bars=3)
    eng.schedule_drop([1], 1)
    eng.mutate_humanize(1)
    finish(eng)
    assert ons_per_bar(port, 0) == {0: 4, 2: 4}
    assert port.count("clock") == 3 * BAR  # humanize never moves the clock
    assert port.count("note_on") == port.count("note_off") and not eng._sounding


# ---- hot-plug notify and port loss ---------------------------------------

def test_hotplug_notifies_but_never_switches(tool_engine, monkeypatch):
    monkeypatch.setattr(engine, "HOTPLUG_INTERVAL", 0)
    outputs, port = [], FakePort()
    eng = tool_engine(opener=opener_for(port), lister=lambda: list(outputs))
    out = call("whiplash_play_pattern", genre="techno", bpm=300)
    assert out["virtual"] and "NO DIGITAKT" in out["warning"] and "device_available" not in out
    outputs.append("Elektron Digitakt II")
    for name, params in (("whiplash_status", {}), ("whiplash_set_tempo", {"bpm": 140}),
                         ("whiplash_set_tempo", {"bpm": 9999}), ("whiplash_play_pattern", {"genre": "soul"})):
        out = call(name, **params)
        assert out["device_available"] == "Elektron Digitakt II", name
        assert "port='Elektron Digitakt II'" in out["notice"] and "NO DIGITAKT" in out["warning"], name
    assert eng.port_name == "Whiplash" and eng.virtual  # never moved on its own
    out = call("whiplash_play_pattern", genre="soul", port="Elektron Digitakt II")
    assert out["mode"] == "started" and out["virtual"] is False and out["port"] == "Elektron Digitakt II"
    assert not any(k in out for k in ("warning", "notice", "device_available"))
    assert "device_available" not in call("whiplash_status")


def test_explicit_virtual_port_only_gets_a_plain_field(tool_engine, monkeypatch):
    monkeypatch.setattr(engine, "HOTPLUG_INTERVAL", 0)
    tool_engine(opener=opener_for(FakePort()), lister=lambda: ["Elektron Digitakt II"])
    out = call("whiplash_play_pattern", genre="techno", bpm=300, port="Whiplash")
    assert out["device_available"] == "Elektron Digitakt II"
    assert "warning" not in out and "notice" not in out
    st = call("whiplash_status")
    assert st["device_available"] == "Elektron Digitakt II" and st["fallback"] is False and "notice" not in st


def test_hotplug_check_is_rate_limited_and_off_the_clock_thread(tool_engine):
    calls = []

    def lister():
        calls.append(time.monotonic())
        raise OSError("enumeration failed")  # never breaks a tool call
    eng = tool_engine(opener=opener_for(FakePort()), lister=lister)
    call("whiplash_play_pattern", genre="techno", bpm=300)
    for _ in range(20):
        assert call("whiplash_status")["success"]
    assert len(calls) == 1  # one enumeration per HOTPLUG_INTERVAL
    time.sleep(0.3)
    assert len(calls) == 1  # the sequencer itself never enumerates
    assert eng.check_hotplug() is None


def test_unplugged_port_is_dropped_and_reopened(fake):
    eng, port = fake
    opened = []
    eng._opener = lambda name: (opened.append(name) or port, "Elektron Digitakt II", False)
    port.fail_after = 30
    eng.play(P["techno"], bpm=300)
    finish(eng)
    st = eng.status()
    assert st["port"] is None and st["port_lost"] == "Elektron Digitakt II"
    assert st["last_error"].startswith("sequencer stopped: OSError")
    port.fail_after = None
    assert eng.play(P["techno"], bpm=300)["mode"] == "started"  # re-detects on the next call
    assert len(opened) == 2 and eng.port_name == "Elektron Digitakt II" and eng.status()["port_lost"] is None
