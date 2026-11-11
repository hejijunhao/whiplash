"""v0.5.1 P0b: whiplash_write_part (notes, melodies, rhythm presets, lock_to, exact note lengths, envelope)."""
import statistics
import threading
import time
from pathlib import Path

import pytest

import whiplash
from whiplash import engine, mutate, parts, patterns, schemas
from test_whiplash import FakePort, call, make_engine, tool_engine  # noqa: F401  (fixture)
from test_live import bar_events, finish, pretend_playing, timeline, wait_bar

P = patterns.PATTERNS
ROOT = Path(whiplash.__path__[0])
STEP = engine.TICKS_PER_STEP


@pytest.fixture
def fake():
    eng, port = make_engine()
    yield eng, port
    eng.shutdown()


def track_hits(eng, track, bar=0):
    """[(step, note, vel, gate)] the engine builds for one track in one bar."""
    return [(s, n, v, g) for s, t, n, v, g, _ in bar_events(eng, bar) if t == track]


def steps_of(eng, track, bar=0):
    return [h[0] for h in track_hits(eng, track, bar)]


# ---- parsing (pure) --------------------------------------------------------

def test_note_names_follow_elektron_octaves():
    assert [parts.note_number(n) for n in ("C5", "D#5", "Eb5", "F4", "A4", "c6", "B#4", "E1", "C7")] == \
        [60, 63, 63, 53, 57, 72, 60, 16, 84]
    assert parts.parse_notes(["C5", 63, "64", ".", "G5"]) == [60, 63, 64, None, 67]
    assert parts.parse_notes("A4 C5, E5") == [57, 60, 64]
    for bad in ("H5", "C", "C#x", True, None, 1.5, 15, 85, "C8", ["."]):
        with pytest.raises(parts.PartError):
            parts.parse_notes(bad if isinstance(bad, list) else [bad])


def test_scale_degrees_parse_into_notes():
    root, scale, name = parts.parse_key("C")
    assert (root, name) == (60, "C5 major")
    assert parts.parse_notes("1 3 5 b7 8", (root, scale)) == [60, 64, 67, 70, 72]
    root, scale, name = parts.parse_key("Am")
    assert (root, name) == (57, "A4 minor")
    assert parts.parse_notes([1, 3, 5, "#4", 9], (root, scale)) == [57, 60, 64, 63, 59 + 12]
    root, scale, name = parts.parse_key("F#3", "dorian")
    assert root == 42 and name == "F#3 dorian"
    assert parts.parse_key("G")[0] == 55 and parts.parse_key("F")[0] == 65  # roots sit nearest note 60
    assert parts.parse_key("A", "minor pentatonic")[2] == "A4 minor_pentatonic"
    for bad in (("H",), ("C", "klingon"), ("C9",)):
        with pytest.raises(parts.PartError):
            parts.parse_key(*bad)
    with pytest.raises(parts.PartError):
        parts.parse_notes(["0"], parts.parse_key("C")[:2])


@pytest.mark.parametrize("rhythm, expected", [
    ("four_on_floor", [0, 4, 8, 12]),
    ("offbeat_8ths", [2, 6, 10, 14]),
    ("8ths", list(range(0, 16, 2))),
    ("16ths", list(range(16))),
    ("off_16ths", list(range(1, 16, 2))),
    ("syncopated", [0, 3, 6, 10, 13]),
    ("half_time", [0, 8]),
    ("four on the floor", [0, 4, 8, 12]),  # alias
])
def test_rhythm_presets_place_the_expected_steps(rhythm, expected):
    kind, value = parts.placement(rhythm=rhythm)
    part = parts.build(kind, value)
    assert part.bars_written == 1
    for bar in part.bars:
        assert [h[0] for h in bar] == expected
        assert all(h[1] == patterns.DRUM and h[2] == parts.DEFAULT_VELOCITY and h[3] == 1.0 for h in bar)


def test_grid_steps_and_hits_place_hits():
    part = parts.build(*parts.placement(grid="x..X|..x. ...x ...."))
    assert [(h[0], h[2]) for h in part.bars[0]] == [(0, 100), (3, 120), (6, 100), (11, 100)]  # X = accent
    part = parts.build(*parts.placement(grid=["x...............", "....x..........."]))
    assert part.bars_written == 2 and [[h[0] for h in b] for b in part.bars] == [[0], [4], [0], [4]]
    part = parts.build(*parts.placement(steps=[12, 0, 3, 3]))
    assert [h[0] for h in part.bars[0]] == [0, 3, 12]
    part = parts.build(*parts.placement(steps=[[0], [2], [4]]))  # 3 bars: plays 1, 2, 3, 1
    assert part.bars_written == 4 and [b[0][0] for b in part.bars] == [0, 2, 4, 0]
    part = parts.build(*parts.placement(hits=[{"step": 0, "note": "C5", "length": 4, "velocity": 127},
                                              {"step": 8, "bar": 2}]), notes=["G5"])
    assert part.bars_written == 2
    assert part.bars[0] == [(0, 60, 127, 4.0, 0.0)] and part.bars[1] == [(8, 67, 100, 1.0, 0.0)]


def test_notes_cycle_over_the_hits_and_bars_grow_to_fit_them():
    part = parts.build(*parts.placement(rhythm="four_on_floor"), notes=["C5", "D5", "E5"])
    # 3 notes over 4 hits per bar: one bar holds them all, so the line repeats every bar
    assert part.bars_written == 1 and [h[1] for h in part.bars[0]] == [60, 62, 64, 60]
    part = parts.build(*parts.placement(rhythm="four_on_floor"), notes="C5 D5 E5 F5 G5 A5")
    assert part.bars_written == 2  # 6 notes need 8 hits
    assert [h[1] for b in part.bars[:2] for h in b] == [60, 62, 64, 65, 67, 69, 60, 62]
    assert part.bars[2] == part.bars[0] and part.bars[3] == part.bars[1]
    part = parts.build(*parts.placement(rhythm="half_time"), notes=list(range(60, 70)))
    assert part.bars_written == 4 and part.unused_notes == 2  # 8 hits in 4 bars
    part = parts.build(*parts.placement(rhythm="8ths"), notes=["C5", ".", "G5"], length=[1, 2], velocity=[100, 80])
    bar = part.bars[0]
    assert [h[0] for h in bar] == [0, 4, 6, 10, 12]  # rests use up their hit
    assert [h[3] for h in bar] == [1.0, 1.0, 2.0, 2.0, 1.0] and [h[2] for h in bar] == [100, 100, 80, 80, 100]


def test_velocity_accent():
    part = parts.build(*parts.placement(rhythm="8ths"), velocity="accent")
    assert [h[2] for h in part.bars[0]] == [120, 90] * 4


@pytest.mark.parametrize("kwargs", [
    {}, {"rhythm": "8ths", "grid": "x" * 16}, {"rhythm": "polka"}, {"grid": "x..x"}, {"grid": "x" * 15 + "y"},
    {"grid": ["x" * 16] * 5}, {"grid": "." * 16}, {"steps": [16]}, {"steps": [-1]}, {"steps": [1.5]},
    {"hits": [{"note": "C5"}]}, {"hits": [{"step": 0, "bar": 5}]}, {"hits": [{"step": 0, "pitch": 3}]},
    {"hits": "x"},
])
def test_bad_placement_raises(kwargs):
    with pytest.raises(parts.PartError):
        parts.build(*parts.placement(**kwargs))


@pytest.mark.parametrize("kwargs", [
    {"length": 0}, {"length": 17}, {"length": "long"}, {"length": True}, {"velocity": 0}, {"velocity": 128},
    {"velocity": 1.5}, {"velocity": "loud"}, {"bars": 3}, {"bars": 8}, {"notes": ["Z9"]}, {"notes": [100]},
    {"scale": "minor"}, {"key": "C", "scale": "nope"}, {"notes": ". ."},
])
def test_bad_values_raise(kwargs):
    with pytest.raises(parts.PartError):
        parts.build("rhythm", "four_on_floor", **kwargs)


# ---- engine: landing, carrying, resetting ----------------------------------

def test_write_part_replaces_the_line_from_the_next_bar(fake):
    eng, port = fake
    eng.play(P["techno"], bpm=300)
    wait_bar(eng, 1)
    out = eng.write_part(6, rhythm="four_on_floor", notes=["C5", "D#5", "G5", "A#5"])
    at = out["at_bar"]
    assert out["applies"] == "next bar" and out["part"] == "written" and out["placed_by"] == "four_on_floor"
    assert [h["name"] for h in out["written"][0]["hits"]] == ["C5", "D#5", "G5", "A#5"]
    assert out["written"][0]["grid"] == "x...x...x...x..."
    assert "ADSR" in out["length_audible"] and "HOLD" in out["length_audible"]
    wait_bar(eng, at + 1)
    eng.stop()
    ons = [(b, m.note) for b, _, m in timeline(port) if m.type == "note_on" and m.channel == 5]
    assert {n for b, n in ons if b < at} <= {53}  # the generated techno bass until the bar line
    assert [n for b, n in ons if b == at] == [60, 63, 67, 70]
    assert port.count("note_on") == port.count("note_off")


def test_part_survives_mutate_reset_and_switches_and_clears_on_stop(fake):
    eng, _ = fake
    pretend_playing(eng, P["techno"])
    eng.write_part(6, rhythm="four_on_floor", notes=["C5"])
    eng.mutate_density([1], -0.5)
    eng.reset_mutations()
    assert steps_of(eng, 6) == [0, 4, 8, 12]
    with eng._lock:  # a live switch lands at the bar line
        eng._queued = {"pattern": P["soul"], "bpm": 86, "bars": None, "at": 1, "transpose": {}}
    assert steps_of(eng, 6, 1) == [0, 4, 8, 12] and eng.pattern.name == "soul"
    assert eng.status()["parts"] == {"6": {"placed_by": "four_on_floor", "bars": 1}}
    assert eng.status()["tracks"]["6"]["part"] == "written"
    eng.playing = lambda: False
    eng.stop()
    assert eng.status()["parts"] == {}
    assert eng._work[6] == mutate.working(P["soul"])[6]


def test_reset_restores_the_generated_part(fake):
    eng, _ = fake
    pretend_playing(eng, P["techno"])
    generated = track_hits(eng, 6)
    eng.write_part(6, steps=[0])
    assert steps_of(eng, 6) == [0]
    with pytest.raises(engine.WhiplashError, match="only track"):
        eng.write_part(6, reset=True, notes=["C5"])
    out = eng.write_part(6, reset=True)
    assert out["reset"] and out["was_written"] and out["part"] == "generated"
    assert track_hits(eng, 6) == generated
    out = eng.write_part(12, reset=True)  # nothing written there: harmless
    assert not out["was_written"] and out["part"] is None and 12 not in eng._work


def test_density_drop_fill_and_mute_apply_to_a_written_part(fake):
    eng, port = fake
    pretend_playing(eng, P["techno"])
    eng.write_part(1, rhythm="16ths")
    eng.write_part(6, rhythm="8ths", notes=["C5"])
    eng.mutate_density([6], -0.5)
    assert len(steps_of(eng, 6)) == 4  # half of 8 thinned away
    eng.mutate_density([6], 0.5)
    assert len(steps_of(eng, 6)) > 8
    eng.mutate_density([6], 0)
    eng.write_part(6, rhythm="four_on_floor", notes=["C5"], velocity=[120, 40])  # density re-applies to a new part
    assert steps_of(eng, 6) == [0, 4, 8, 12]
    eng.schedule_fill([1])  # kick fill: sits out the last beat
    assert steps_of(eng, 1, 1) == list(range(12))
    eng.schedule_drop([6], 1)
    assert steps_of(eng, 6, 2) == [] and steps_of(eng, 6, 3) == [0, 4, 8, 12]
    eng.playing = lambda: True
    eng.set_mute(6, True)
    assert 6 in eng.muted  # the sequencer skips muted tracks whatever their part


def test_mute_and_drop_silence_a_written_part_on_the_wire(fake):
    eng, port = fake
    eng.play(P["techno"], bpm=300)
    wait_bar(eng, 1)
    at = eng.write_part(10, rhythm="four_on_floor", notes=["C5"])["at_bar"]
    eng.schedule_drop([10], 1)  # from the same next bar
    wait_bar(eng, at + 2)
    eng.set_mute(10, True)
    muted_at = eng.bar
    wait_bar(eng, muted_at + 2)
    eng.stop()
    per_bar = {}
    for b, _, m in timeline(port):
        if m.type == "note_on" and m.channel == 9:
            per_bar[b] = per_bar.get(b, 0) + 1
    assert at not in per_bar and per_bar.get(at + 1) == 4  # dropped one bar, then back
    assert not any(b > muted_at for b in per_bar)


def test_lock_to_copies_the_kick_at_call_time(fake):
    eng, _ = fake
    pretend_playing(eng, P["soul"])
    kick = [[h[0] for h in bar] for bar in P["soul"].bars[1]]
    out = eng.write_part(6, lock_to=1, notes=["A4", "C5"])
    assert out["locked_to"]["track"] == 1 and out["locked_to"]["follows_live"] is False and out["bars"] == 4
    assert [steps_of(eng, 6, b) for b in range(4)] == kick
    eng.write_part(7, rhythm="on_kick")  # the preset is lock_to 1
    assert [steps_of(eng, 7, b) for b in range(4)] == kick
    eng.write_part(1, rhythm="half_time")  # later edits of the source are not followed (P1)
    assert [steps_of(eng, 6, b) for b in range(4)] == kick
    with pytest.raises(engine.WhiplashError, match="another track"):
        eng.write_part(6, lock_to=6)
    with pytest.raises(engine.WhiplashError, match="no hits"):
        eng.write_part(6, lock_to=12)


def test_bad_input_leaves_the_beat_alone(fake):
    eng, port = fake
    pretend_playing(eng, P["techno"])
    eng.write_part(7, rhythm="half_time", notes=["G5"])
    before = (dict(eng._work), dict(eng._parts), len(port.messages))
    bad = [
        {"track": 0, "rhythm": "8ths"}, {"track": 17, "rhythm": "8ths"}, {"track": "six", "rhythm": "8ths"},
        {"track": 6}, {"track": 6, "rhythm": "8ths", "steps": [0]}, {"track": 6, "grid": "x.x"},
        {"track": 6, "rhythm": "8ths", "notes": ["C9"]}, {"track": 6, "rhythm": "8ths", "notes": "C5 nope"},
        {"track": 6, "rhythm": "8ths", "length": 0.1}, {"track": 6, "rhythm": "8ths", "length": [1, 99]},
        {"track": 6, "rhythm": "8ths", "velocity": 200}, {"track": 6, "rhythm": "8ths", "bars": 3},
        {"track": 6, "rhythm": "8ths", "envelope": "adsr"}, {"track": 7, "rhythm": "8ths", "reset": "maybe"},
        {"track": 6, "rhythm": "8ths", "notes": ["C5"], "envelope": "note", "length": -1},
    ]
    for kwargs in bad:
        with pytest.raises(engine.WhiplashError):
            eng.write_part(**kwargs)
    assert (dict(eng._work), dict(eng._parts), len(port.messages)) == before  # not even an envelope CC
    eng.playing = lambda: False
    with pytest.raises(engine.WhiplashError, match="play_pattern"):
        eng.write_part(6, rhythm="8ths")


def test_tracks_9_to_16_and_mutate_up_to_16(fake):
    eng, _ = fake
    pretend_playing(eng, P["techno"])
    out = eng.write_part(16, steps=[0, 8], notes=["C5", "G5"], length=8)
    assert "AUTO CHANNEL" in out["channel_note"]
    assert track_hits(eng, 16) == [(0, 60, 100, 8.0), (8, 67, 100, 8.0)]
    assert eng.mutate_density([16], -1)["density"] == {"16": -1}
    assert eng.schedule_drop([16], 1)["dropped"] == [16]
    with pytest.raises(engine.WhiplashError, match="nothing"):
        eng.mutate_density([13], 0.5)
    assert eng.status()["tracks"]["16"]["part"] == "written"


def test_transpose_still_applies_and_is_reported(fake):
    eng, _ = fake
    pretend_playing(eng, P["techno"])
    eng.set_transpose(6, semitones=12)
    out = eng.write_part(6, rhythm="four_on_floor", notes=["C5"])
    assert "+12" in out["transpose_note"] and out["pitch"]["low"] == 72
    assert {n for _, n, _, _ in track_hits(eng, 6)} == {72}
    assert "register_shift" not in eng.tracks_summary()["6"]["pitch"]  # a written part has no register lift


# ---- engine: note length on the wire ---------------------------------------

def note_spans(port, channel):
    """[(clocks at note_on, clocks at its note_off)] for one channel, in order."""
    open_, spans = {}, []
    for _, clocks, m in timeline(port):
        if m.type not in ("note_on", "note_off") or m.channel != channel:
            continue
        if m.type == "note_on":
            open_[m.note] = clocks
        elif m.note in open_:
            spans.append((open_.pop(m.note), clocks))
    return spans


def test_note_off_lands_at_length_times_a_sixteenth(fake):
    eng, port = fake
    eng.play(P["techno"], bpm=120)  # straight (swing 50); a clock tick is ~21 ms, so runner lag stays under one
    wait_bar(eng, 1)
    at = eng.write_part(6, hits=[{"step": 0, "note": "C5", "length": 2}, {"step": 4, "note": "D5", "length": 4},
                                 {"step": 8, "note": "E5", "length": 8}, {"step": 12, "note": "F5", "length": 0.5}]
                        )["at_bar"]
    wait_bar(eng, at + 2)
    eng.stop()
    bar_start = at * engine.TICKS_PER_BAR
    spans = sorted((on - bar_start, off - on) for on, off in note_spans(port, 5) if bar_start <= on < bar_start + 96)
    assert [s for s, _ in spans] == [0, 4 * STEP, 8 * STEP, 12 * STEP]
    # exact note-off, no 0.8 GATE factor: 12, 24, 48 and 3 clocks (gated would be 10, 20, 39, 3), +-1 for CI lag
    for (_, got), want in zip(spans, (2 * STEP, 4 * STEP, 8 * STEP, STEP // 2)):
        assert abs(got - want) <= 1, spans
    # generated parts keep the 0.8 gate: the techno kick (gate 1) ends before the next 16th
    kick = note_spans(port, 0)[0]
    assert kick[1] - kick[0] < STEP


def test_a_long_note_never_cuts_its_own_retrigger(fake):
    eng, port = fake
    eng.play(P["techno"], bpm=300)
    wait_bar(eng, 1)
    at = eng.write_part(6, rhythm="four_on_floor", notes=["C5"], length=16)["at_bar"]  # each note held 4 beats
    wait_bar(eng, at + 1)
    eng.stop()
    bar_start = at * engine.TICKS_PER_BAR
    msgs = [(c - bar_start, m.type) for _, c, m in timeline(port)
            if m.type in ("note_on", "note_off") and m.channel == 5 and bar_start <= c < bar_start + 96]
    # each retrigger ends the held note right before it, and nothing ends the new note early
    assert msgs == [(0, "note_on"), (24, "note_off"), (24, "note_on"), (48, "note_off"), (48, "note_on"),
                    (72, "note_off"), (72, "note_on")]
    ons = [c for c, t in msgs if t == "note_on"]
    offs = [c for c, t in msgs if t == "note_off"]
    assert ons == [0, 24, 48, 72] and offs == [24, 48, 72]
    assert port.count("note_on") == port.count("note_off")


# ---- envelope --------------------------------------------------------------

def test_envelope_note_sends_exactly_one_cc80_127(fake):
    eng, port = fake
    pretend_playing(eng, P["techno"])
    out = eng.write_part(6, rhythm="8ths", notes=["C5"], length=0.5, envelope="note")
    cc = [m for m in port.messages if m.type == "control_change"]
    assert [(m.channel, m.control, m.value) for m in cc] == [(5, 80, 127)]
    assert out["envelope"]["amp_hold"] == 127 and "tell the user" in out["envelope"]["warning"]
    assert "last sent amp_hold 127" in out["length_audible"]
    eng.write_part(6, rhythm="8ths", notes=["C5"])  # no envelope argument: nothing sent
    assert len([m for m in port.messages if m.type == "control_change"]) == 1
    eng.set_param(7, 1, param="amp_mode")
    assert "ADSR" in eng.write_part(7, rhythm="8ths")["length_audible"].split(".")[0]


# ---- clock -----------------------------------------------------------------

class TimedPort(FakePort):
    def __init__(self):
        super().__init__()
        self.clock_times = []

    def send(self, msg):
        if msg.type == "clock":
            self.clock_times.append(time.perf_counter())
        super().send(msg)


def _jitter(times):
    gaps = [b - a for a, b in zip(times, times[1:])]
    nominal = statistics.median(gaps)
    return sorted(abs(g - nominal) for g in gaps)[int(len(gaps) * 0.95)]


def assert_jitter(base, busy, what="busy"):
    """p95 clock jitter while busy within max(2x, +3 ms) of the baseline. A wall-clock bound: enforced locally (or
    with WHIPLASH_STRICT_TIMING=1), reported only on CI, where shared runners stall 5-15 ms at times
    (conftest.STRICT_TIMING). The schedule itself is pinned on a virtual clock in test_v070.py."""
    from conftest import STRICT_TIMING
    b, j = _jitter(base), _jitter(busy)
    if STRICT_TIMING:
        assert j <= max(b * 2, b + 0.003), (b, j)
    else:
        print(f"clock jitter, {what} (not enforced on CI): base {b * 1000:.2f} ms, {what} {j * 1000:.2f} ms")


def test_clock_jitter_is_unchanged_with_8_written_parts():
    port = TimedPort()
    eng, _ = make_engine(port)
    try:
        eng.play(P["techno"], bpm=240)
        wait_bar(eng, 1)
        for track in range(1, 9):
            eng.write_part(track, rhythm="16ths", notes=["C5", "D#5", "G5"], length=[0.5, 3], velocity="accent")
        at = eng.bar + 1
        wait_bar(eng, at + 2)
        eng.stop()
    finally:
        eng.shutdown()
    t = port.clock_times
    base, written = t[:at * engine.TICKS_PER_BAR], t[at * engine.TICKS_PER_BAR:(at + 2) * engine.TICKS_PER_BAR]
    assert len(written) == 2 * engine.TICKS_PER_BAR
    assert port.count("note_on", channel=7) >= 32  # 16ths on track 8 really played
    # p95 deviation from the clock period stays within a couple of ms of the generated beat's
    assert_jitter(base, written, "8 written parts")


# ---- tool, schema, docs ------------------------------------------------------

def test_write_part_tool(tool_engine):
    eng, port = tool_engine()
    out = call("whiplash_write_part", track=6, rhythm="8ths")
    assert not out["success"] and "play_pattern" in out["error"]
    call("whiplash_play_pattern", genre="techno", bpm=300)
    out = call("whiplash_write_part", track=6, rhythm="offbeat_8ths", key="Am", notes="1 3 5 8")
    assert out["success"] and out["key"] == "A4 minor" and out["placed_by"] == "offbeat_8ths"
    assert [h["note"] for h in out["written"][0]["hits"]] == [57, 60, 64, 69]
    assert "C5 = MIDI 60" in out["pitch_note"] and out["length_audible"]
    out = call("whiplash_write_part", track=6, grid="x...", notes=["C5"])
    assert not out["success"] and "16 cells" in out["error"]
    assert call("whiplash_status")["tracks"]["6"]["part"] == "written"
    out = call("whiplash_write_part", track=6, reset=True)
    assert out["success"] and out["reset"] and "pitch_note" not in out
    out = call("whiplash_mutate", action="density", tracks=[12], amount=0.5)
    assert not out["success"] and "nothing" in out["error"]
    stop = call("whiplash_stop")
    assert stop["success"]


def test_write_part_schema():
    schema = schemas.SCHEMAS["whiplash_write_part"]
    props = schema["parameters"]["properties"]
    assert schema["parameters"]["required"] == ["track"] and props["track"]["maximum"] == 16
    assert set(props["rhythm"]["enum"]) == {*parts.RHYTHMS, "on_kick"}
    assert props["envelope"]["enum"] == ["note"] and props["bars"]["enum"] == [1, 2, 4]
    assert props["length"]["description"].startswith("Note length in 16th steps, 0.25-16")
    for word in ("length_audible", "HOLD", "ADSR", "C5 = MIDI 60", "whiplash_stop", "lock_to"):
        assert word in schema["description"], word
    assert schemas.SCHEMAS["whiplash_mutate"]["parameters"]["properties"]["tracks"]["items"]["maximum"] == 16


def test_skill_teaches_write_part():
    text = (ROOT / "skills" / "digitakt" / "SKILL.md").read_text()
    for fact in ("whiplash_write_part", "can write", "four_on_floor", "lock_to", "envelope", "length_audible",
                 "HOLD = NOTE", "amp_mode"):
        assert fact in text, fact
    assert "use kb mode" not in text.lower()

