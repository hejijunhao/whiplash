"""v0.8.0 play along: MIDI input from the unit (decoding, user moves, ramps yield, echo filter), whiplash_follow (call
and response in key and register), whiplash_undo, the in-memory recording, and the rails (no file writes, no SysEx,
program change or blocked CC, received messages never re-sent, the reader never stalls the clock).

Fake input and output ports only: nothing here says how the Digitakt II behaves."""
import builtins
import collections
import io
import json
import os
import threading
import time
import tomllib
from pathlib import Path

import mido
import pytest
import yaml

import whiplash
from whiplash import ccmap, engine, harmony, jam, patterns, schemas, tools
from test_whiplash import FakePort
from test_live import timeline, wait_bar
from test_v051 import TimedPort, assert_jitter

ROOT = Path(whiplash.__path__[0])
P = patterns.PATTERNS
BAR = engine.TICKS_PER_BAR
F_MINOR = harmony.Key(5, "minor")  # techno's home key


class FakeInput:
    """A MIDI input: tests push messages, the reader drains them with iter_pending()."""

    def __init__(self, fail_after=None):
        self.pending = collections.deque()
        self.closed = False
        self.read = 0
        self.fail_after = fail_after

    def push(self, *msgs):
        self.pending.extend(msgs)

    def iter_pending(self):
        while self.pending:
            if self.fail_after is not None and self.read >= self.fail_after:
                raise OSError("device unplugged")
            self.read += 1
            yield self.pending.popleft()

    def close(self):
        self.closed = True


def make(port=None, inp=None, name="Elektron Digitakt II"):
    port, inp = port or FakePort(), inp or FakeInput()
    opened = []

    def in_opener(_):
        opened.append(1)
        return inp, name
    eng = engine.Engine(opener=lambda n: (port, n or "Fake", False), in_opener=in_opener)
    eng.opened = opened
    return eng, port, inp


@pytest.fixture
def jamming():
    made = []

    def build(**kw):
        out = make(**kw)
        made.append(out[0])
        return out
    yield build
    for eng in made:
        eng.shutdown()


@pytest.fixture
def tool_jam(monkeypatch):
    made = []

    def install(**kw):
        eng, port, inp = make(**kw)
        monkeypatch.setattr(tools, "ENGINE", eng)
        made.append(eng)
        return eng, port, inp
    yield install
    for eng in made:
        eng.shutdown()


def call(name, **params):
    return json.loads(tools.HANDLERS[name](params))


def wait(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < end, "condition never became true"
        time.sleep(0.005)


def cc(ch, control, value):
    return mido.Message("control_change", channel=ch, control=control, value=value)


def note(ch, n, vel=100):
    return mido.Message("note_on", channel=ch, note=n, velocity=vel)


def assert_rails(port):
    for m in port.messages:
        assert m.type in engine.ALLOWED_TYPES, m
        if m.type == "control_change":
            assert m.control not in ccmap.BLOCKED_CCS, m


# ---- packaging -------------------------------------------------------------------------------------------------

def test_version_is_0_8_0():
    assert whiplash.__version__ == "0.8.0"
    assert yaml.safe_load(open(ROOT / "plugin.yaml"))["version"] == "0.8.0"
    assert yaml.safe_load(open(ROOT / "docs" / "catalog-entry.yaml"))["version"] == "0.8.0"
    assert tomllib.load(open(ROOT / "pyproject.toml", "rb"))["project"]["version"] == "0.8.0"
    releases = [h for h in (ROOT / "CHANGELOG.md").read_text().split("\n## ")[1:] if not h.startswith("Unreleased")]
    assert releases[0].startswith("0.8.0")


def test_new_tools_follow_scan_kit_everywhere():
    new = ["whiplash_play_along", "whiplash_follow", "whiplash_undo"]
    for manifest in (yaml.safe_load(open(ROOT / "plugin.yaml"))["provides_tools"],
                     yaml.safe_load(open(ROOT / "docs" / "catalog-entry.yaml"))["capabilities"]["provides_tools"],
                     list(schemas.SCHEMAS), list(tools.HANDLERS)):
        i = manifest.index("whiplash_scan_kit")
        assert manifest[i + 1:i + 4] == new
        assert manifest[i + 4:] == ["whiplash_open_view", "whiplash_close_view"]
    skill = (ROOT / "skills" / "digitakt" / "SKILL.md").read_text()
    readme = (ROOT / "README.md").read_text()
    for name in new:
        assert name in skill and name in readme
    assert "yielded_to_user" in skill and "MIDI CONFIG > PORT CONFIG" in skill
    assert (ROOT / "docs" / "executing" / "v08-build-plan.md").exists()


def test_no_new_runtime_dependency():
    manifest = yaml.safe_load(open(ROOT / "plugin.yaml"))
    assert manifest["python_dependencies"] == ["mido>=1.3,<2", "python-rtmidi>=1.5,<2"]


def test_play_along_and_status_never_open_the_input_by_themselves(jamming):
    eng, port, inp = jamming()
    eng.play(P["techno"], bpm=240)
    wait_bar(eng, 1)
    st = eng.status()
    assert st["play_along"] is None and st["undo"] == [] and eng.opened == []
    assert eng._input is None and eng._echo is None and eng._rec is None and eng.recording is None
    assert not any(t.name == "whiplash-in" for t in threading.enumerate() if t.is_alive())


# ---- decoding --------------------------------------------------------------------------------------------------

def test_decoder_names_ccs_by_track_and_param():
    d = jam.Decoder()
    assert d.feed(cc(5, 74, 90)) == {"kind": "cc", "track": 6, "cc": 74, "param": "filter_freq", "value": 90,
                                     "via": "cc"}
    assert d.feed(cc(0, 95, 100))["param"] == "track_level"
    assert d.feed(cc(2, 3, 10))["param"] == "cc 3"  # not in the map: named by number
    assert d.feed(note(6, 64, 90)) == {"kind": "note", "track": 7, "note": 64, "velocity": 90}
    assert d.feed(mido.Message("note_off", channel=6, note=64))["velocity"] == 0


def test_decoder_assembles_nrpn_and_flags_disputed_addresses():
    d = jam.Decoder()
    assert d.feed(cc(5, 99, 1)) is None and d.feed(cc(5, 98, 20)) is None
    move = d.feed(cc(5, 6, 77))
    assert move["param"] == "filter_freq" and move["cc"] == 74 and move["via"] == "nrpn" and move["value"] == 77
    assert "unsure" not in move
    assert d.feed(cc(5, 38, 5)) is None  # data LSB refines; no second move
    d.feed(cc(5, 99, 1)), d.feed(cc(5, 98, 110))
    level = d.feed(cc(5, 6, 50))
    assert level["param"] == "track_level" and level["unsure"] is True  # manual 1:100 vs midi.guide 1:110
    d.feed(cc(3, 99, 9)), d.feed(cc(3, 98, 9))
    assert d.feed(cc(3, 6, 1))["param"] == "nrpn 9:9" and d.feed(cc(3, 6, 1))["cc"] is None
    d.feed(cc(3, 101, 0))  # RPN select resets the NRPN state
    assert d.feed(cc(3, 6, 1)) is None


def test_decoder_ignores_sysex_program_change_clock_and_transport():
    d = jam.Decoder()
    for m in (mido.Message("sysex", data=[0x00, 0x20, 0x3C, 1, 2]), mido.Message("program_change", program=3),
              mido.Message("clock"), mido.Message("start"), mido.Message("stop"),
              mido.Message("pitchwheel", pitch=100), mido.Message("aftertouch", value=3)):
        assert d.feed(m) is None
    assert d.ignored == {"sysex": 1, "program_change": 1, "clock": 1, "start": 1, "stop": 1, "pitchwheel": 1,
                         "aftertouch": 1}


def test_find_input_never_picks_whiplash_or_another_device():
    assert jam.find_input(["Whiplash", "IAC Bus", "Elektron Digitakt II"], "Whiplash") == "Elektron Digitakt II"
    assert jam.find_input(["Whiplash:Whiplash 128:0", "Arturia KeyStep"], "Whiplash") is None
    assert jam.find_input(["Digitakt II:Digitakt II MIDI 1 20:0"], "Whiplash").startswith("Digitakt II")


def test_no_digitakt_input_is_a_clean_error_and_nothing_changes():
    class Mido:
        def get_input_names(self):
            return ["IAC Bus 1", "Arturia KeyStep"]

        def open_input(self, name):
            raise AssertionError("must not open another input")
    with pytest.raises(jam.JamError, match="Digitakt II MIDI input not found.*PORT CONFIG.*OUTPUT TO.*Arturia"):
        jam.open_input(Mido(), "Whiplash")


def test_engine_open_error_passes_the_hint_and_changes_nothing():
    def opener(_):
        raise jam.JamError(jam.NO_INPUT)
    eng = engine.Engine(opener=lambda n: (FakePort(), "Fake", False), in_opener=opener)
    try:
        with pytest.raises(engine.WhiplashError, match="ENCODER DEST"):
            eng.play_along()
        assert eng._input is None and eng._rec is None and eng.status()["play_along"] is None
    finally:
        eng.shutdown()


# ---- user moves and ramps yield --------------------------------------------------------------------------------

def test_user_moves_show_in_status_merged_into_gestures(jamming):
    eng, port, inp = jamming()
    out = eng.play_along()
    assert out["on"] and out["opened_now"] and out["port"] == "Elektron Digitakt II" and "PORT CONFIG" in out["setup"]
    assert eng.play_along()["opened_now"] is False  # idempotent: one reader
    inp.push(cc(5, 74, 40), cc(5, 74, 60), cc(5, 74, 90), cc(0, 95, 110))
    wait(lambda: eng.status()["play_along"]["heard"] == 4)
    moves = eng.status()["play_along"]["user_moves"]
    assert moves[0]["said"] == "track 1 track_level 110"
    assert moves[1] == {**moves[1], "track": 6, "param": "filter_freq", "from": 40, "value": 90,
                        "said": "track 6 filter_freq 40 -> 90"}
    assert len(moves) == 2
    # last_cc stays what Whiplash sent (decision 4): the user's value is listed separately
    assert "6" not in eng.status()["tracks"] or "filter_freq" not in eng.status()["tracks"]["6"]["last_cc"]


def test_user_moves_are_bounded(jamming):
    eng, port, inp = jamming()
    eng.play_along()
    inp.push(*[cc(t % 16, 74 if t % 2 else 75, t % 128) for t in range(200)])
    wait(lambda: eng.status()["play_along"]["heard"] == 200)
    assert len(eng.user_moves) == jam.MOVES_MAX
    assert len(eng.status()["play_along"]["user_moves"]) == jam.MOVES_SHOWN


def test_a_ramp_yields_when_the_user_grabs_the_same_knob(tool_jam):
    eng, port, inp = tool_jam()
    call("whiplash_play_pattern", genre="techno", bpm=240)
    wait_bar(eng, 1)
    call("whiplash_play_along")
    other = call("whiplash_ramp_param", track=7, param="filter_freq", to=127, **{"from": 20}, bars=8)
    ramp = call("whiplash_ramp_param", track=6, param="filter_freq", to=127, **{"from": 20}, bars=8)
    assert ramp["success"]
    inp.push(cc(5, 75, 50))  # a different knob on the same track: no yield
    inp.push(cc(5, 74, 64))
    wait(lambda: not any(r["id"] == ramp["ramp_id"] for r in eng.ramps()))
    assert any(r["id"] == other["ramp_id"] for r in eng.ramps())  # the other track's ramp keeps going
    sent_after = [m for m in port.messages if m.type == "control_change" and m.channel == 5 and m.control == 74]
    time.sleep(0.2)
    later = [m for m in port.messages if m.type == "control_change" and m.channel == 5 and m.control == 74]
    assert len(later) == len(sent_after)  # Whiplash stopped sending that knob: the user's value stands
    out = call("whiplash_status")
    assert out["yielded_to_user"][0]["track"] == 6 and out["yielded_to_user"][0]["user_value"] == 64
    assert "Tell them you yielded" in out["yield_note"]
    assert out["play_along"]["yielded"][0]["ramp"] == ramp["ramp_id"]
    assert "yielded_to_user" not in call("whiplash_status")  # reported once
    assert_rails(port)


def test_a_grab_also_drops_a_pending_filter_swap_reopen(jamming):
    eng, port, inp = jamming()
    eng.play(P["techno"], bpm=240)
    wait_bar(eng, 1)
    eng.play_along()
    with eng._lock:
        eng._restore[(7, 74)] = 100
        eng._start_ramp(mido, 7, 74, "filter_freq", 100, 30, BAR * 8, "linear", owner="t9")
    inp.push(cc(6, 74, 80))
    wait(lambda: (7, 74) not in eng._ramps)
    assert (7, 74) not in eng._restore


def test_whiplash_own_echo_never_counts_as_the_user(jamming):
    eng, port, inp = jamming()
    eng.play(P["techno"], bpm=240)
    wait_bar(eng, 1)
    eng.play_along()
    eng.ramp(6, 127, param="filter_freq", start=0, bars=8)
    wait(lambda: any(m.type == "control_change" and m.control == 74 and m.value > 3 for m in port.messages))
    last = [m for m in port.messages if m.type == "control_change" and m.channel == 5 and m.control == 74][-1]
    inp.push(last.copy())  # the unit (or a thru) sends Whiplash's own CC straight back
    wait(lambda: eng.status()["play_along"]["heard"] == 1)
    assert eng.status()["play_along"]["echoes_ignored"] == 1 and eng.status()["play_along"]["user_moves"] == []
    assert any(r["track"] == 6 for r in eng.ramps())


def test_input_loss_is_reported_and_the_beat_plays_on(jamming):
    eng, port, inp = jamming(inp=FakeInput(fail_after=2))
    eng.play(P["techno"], bpm=240)
    wait_bar(eng, 1)
    eng.play_along()
    inp.push(cc(5, 74, 1), cc(5, 74, 2), cc(5, 74, 3))
    wait(lambda: eng.status()["play_along"].get("lost"))
    st = eng.status()["play_along"]
    assert "unplugged" in st["lost"] and "whiplash_play_along" in st["hint"] and st["open"] is False
    bar = eng.bar
    wait_bar(eng, bar + 1)
    assert eng.playing()
    inp.fail_after = None
    assert eng.play_along()["opened_now"] is True  # reopens


def test_quiet_input_gets_the_send_settings_hint(jamming, monkeypatch):
    eng, port, inp = jamming()
    eng.play_along()
    monkeypatch.setattr(jam, "QUIET_HINT_AFTER", 0.0)
    assert "send settings" in eng.status()["play_along"]["hint"]


def test_play_along_off_closes_and_keeps_the_recording(tool_jam):
    eng, port, inp = tool_jam()
    call("whiplash_play_along")
    out = call("whiplash_play_along", on=False)
    assert out["success"] and out["on"] is False and out["was_open"] and inp.closed
    assert out["recording"]["in_memory_only"] is True
    assert eng._input is None and eng._rec is None and eng.recording is not None
    assert call("whiplash_play_along", on=False)["was_open"] is False


# ---- follow ----------------------------------------------------------------------------------------------------

def phrase_notes(*pairs):
    return [(step, n, 100) for step, n in pairs]


def in_key(n, key):
    return (n - key.pc) % 12 in key.steps


@pytest.mark.parametrize("mode", jam.MODES)
def test_replies_stay_in_key_and_register(mode):
    phrase = phrase_notes((0, 29), (4, 32), (8, 36), (12, 35))  # low, with an out-of-key note (35 = B in F minor)
    out = jam.reply(mode, phrase, F_MINOR)
    assert [s for s, _, _ in out] == [0, 4, 8, 12]
    notes = [n for _, n, _ in out]
    assert all(in_key(n, F_MINOR) for n in notes)
    assert all(patterns.NOTE_MIN <= n <= patterns.NOTE_MAX for n in notes)
    assert jam.REG_LOW <= sorted(notes)[len(notes) // 2] <= jam.REG_HIGH + 12  # median in the native register


def test_echo_harmonize_and_answer_shapes():
    phrase = phrase_notes((0, 65), (2, 67), (4, 68))  # F G Ab in F minor
    assert [n for _, n, _ in jam.reply("echo", phrase, F_MINOR)] == [65, 67, 68]
    assert [n for _, n, _ in jam.reply("harmonize", phrase, F_MINOR)] == [68, 70, 72]  # a diatonic third up
    answer = [n for _, n, _ in jam.reply("answer", phrase, F_MINOR)]
    assert answer[0] == 65 and answer[1] == 63  # mirrored: up a step becomes down a step
    assert answer[-1] % 12 == F_MINOR.pc  # resolves on the tonic
    chromatic = jam.reply("echo", phrase_notes((0, 61)), None)  # no key: chromatic, register only
    assert chromatic[0][1] == 61


def test_quantize_one_note_per_step_and_bounded():
    step = 0.1
    heard = [(i * step + 0.02, 60 + i % 5, 90) for i in range(16)] + [(0.03, 50, 10), (5.0, 60, 90), (-1.0, 60, 9)]
    out = jam.quantize(heard, 0.0, step)
    assert [s for s, _, _ in out] == list(range(16)) and out[0][1] == 60  # the first on a step wins
    assert len(out) <= jam.PHRASE_MAX


def test_follow_refusals_change_nothing(jamming):
    eng, port, inp = jamming()
    with pytest.raises(engine.WhiplashError, match="nothing is playing"):
        eng.follow(7, 9)
    eng.play(P["techno"], bpm=240)
    wait_bar(eng, 1)
    for kw, pattern in (({"track": 7, "answer_track": 7}, "must differ"),
                        ({"track": 7, "answer_track": 1}, "holds kick"),
                        ({"track": 7, "answer_track": 4}, "holds closed hat"),
                        ({"track": 7, "answer_track": 9, "mode": "canon"}, "mode must be"),
                        ({"track": 7}, "give track"), ({"track": 0, "answer_track": 9}, "track must be"),
                        ({"stop": True, "track": 7}, "takes nothing else")):
        with pytest.raises(engine.WhiplashError, match=pattern):
            eng.follow(**kw)
    assert eng._follow is None and eng.opened == []  # validated before the input opened


def test_follow_answers_on_the_next_bar_in_key_on_the_grid(jamming):
    eng, port, inp = jamming()
    eng.play(P["techno"], bpm=240)
    wait_bar(eng, 1)
    out = eng.follow(track=9, answer_track=7, mode="harmonize")
    assert out["following"]["answer_track"] == 7 and out["key"] == "F minor" and "KEYBOARD" in out["how"]
    start = eng.bar + 1
    wait_bar(eng, start)
    inp.push(note(8, 65), note(8, 67), note(8, 68), note(8, 70))  # played in bar `start`, on the user's track
    wait_bar(eng, start + 2)
    f = eng.status()["play_along"]["follow"]
    assert f["replies"] >= 1 and f["last"]["heard"] == [65, 67, 68, 70][:len(f["last"]["heard"])]
    answered = f["last"]["bar"]
    eng.stop()
    ons = [(bar, m.note) for bar, _, m in timeline(port) if m.type == "note_on" and m.channel == 6]
    reply = [n for bar, n in ons if bar == answered]
    assert reply == f["last"]["played"] and len(reply) == len(f["last"]["heard"])
    assert all(in_key(n, F_MINOR) for n in reply)
    assert not any(m.type == "note_on" and m.channel == 8 for m in port.messages)  # never echoes the user's notes
    assert_rails(port)


def test_answer_replaces_the_answer_tracks_line_for_one_bar(jamming):
    eng, port, inp = jamming()
    from test_live import pretend_playing
    pretend_playing(eng, P["techno"])
    with eng._lock:
        eng._follow = {"track": 9, "answer": 7, "mode": "echo", "since_bar": 1, "replies": 0, "last": None,
                       "dropped": 0}
        step = 60.0 / eng.bpm / 4
        at = 100.0
        for s, n in ((0, 65), (3, 68), (3, 70), (12, 72)):
            eng._phrase.append((at - 16 * step + s * step + 0.003, n, 99))
        eng._phrase.append((at - 0.2 * step, 77, 99))  # just before the line: belongs to the next bar
        events = eng._bar_boundary(1, at)
    on7 = sorted((s, e[1]) for s, evs in events.items() for e in evs if e[0] == 7)
    assert on7 == [(0, 65), (3, 68), (12, 72)]  # only the reply; a second note on step 3 dropped
    assert eng._follow["dropped"] == 1 and list(eng._phrase) == [(at - 0.2 * step, 77, 99)]
    assert all(e[3] == 1 and e[4] == 0 for evs in events.values() for e in evs if e[0] == 7)  # one step, on grid


def test_follow_stop_paths(jamming):
    eng, port, inp = jamming()
    eng.play(P["techno"], bpm=240)
    wait_bar(eng, 1)
    eng.follow(9, 7)
    assert eng.follow(stop=True)["stopped"] is True and eng._follow is None
    eng.follow(9, 7)
    eng.close_input()
    assert eng._follow is None
    eng.follow(9, 7)
    eng.stop()
    assert eng._follow is None


def test_follow_tool_round_trip(tool_jam):
    eng, port, inp = tool_jam()
    call("whiplash_play_pattern", genre="techno", bpm=240)
    out = call("whiplash_follow", track=9, answer_track=10, mode="echo")
    assert out["success"] and out["following"]["mode"] == "echo" and "channel_note" in out
    assert call("whiplash_status")["play_along"]["follow"]["answer_track"] == 10
    assert call("whiplash_follow", stop=True)["stopped"] is True


# ---- undo ------------------------------------------------------------------------------------------------------

def test_undo_a_written_part_on_the_next_bar(jamming):
    eng, port, inp = jamming()
    eng.play(P["techno"], bpm=240)
    wait_bar(eng, 1)
    generated = [list(b) for b in eng._work[7]]
    eng.write_part(7, rhythm="16ths", notes=["C5"])
    eng.write_part(7, rhythm="8ths", notes=["D5"])
    assert eng.status()["undo"][:2] == ["written part on track 7", "written part on track 7"]
    out = eng.undo()
    assert out["back_to"] == "the previous written part" and out["applies"] == "next bar"
    wait_bar(eng, out["at_bar"])
    assert eng._parts[7].source == "16ths"
    out = eng.undo()
    assert out["back_to"] == "the generated line"
    wait_bar(eng, out["at_bar"])
    assert 7 not in eng._parts and eng._work[7] == generated
    with pytest.raises(engine.WhiplashError, match="nothing to undo"):
        eng.undo()


def test_undo_a_mix_sends_the_old_values_on_the_bar(jamming):
    eng, port, inp = jamming()
    eng.play(P["techno"], bpm=240)
    wait_bar(eng, 1)
    eng.mix(levels={"6": 100})
    wait_bar(eng, eng.bar + 2)
    eng.mix(levels={"6": 80, "7": 90})
    wait_bar(eng, eng.bar + 2)
    out = eng.undo()
    assert out["cannot_revert"] == [7] and out["back_to"] == {"6 level": 100}
    wait_bar(eng, out["at_bar"] + 1)
    eng.stop()
    levels = [(bar, m.value) for bar, _, m in timeline(port)
              if m.type == "control_change" and m.channel == 5 and m.control == engine.LEVEL_CC]
    assert [v for _, v in levels] == [100, 80, 100] and levels[-1][0] == out["at_bar"]


def test_undo_an_arrangement_lifts_its_mutes_or_resumes_the_previous(jamming):
    eng, port, inp = jamming()
    eng.play(P["techno"], bpm=240)
    wait_bar(eng, 1)
    first = eng.arrange(sections=[{"name": "a", "bars": 4, "tracks": ["kick"]}, {"name": "b", "bars": 4,
                                                                                 "tracks": ["all"]}], loop=True)
    wait_bar(eng, first["starts_at_bar"] + 1)
    assert eng._arr_muted
    eng.arrange(sections=[{"name": "c", "bars": 8, "tracks": ["hats"]}], loop=True)
    wait_bar(eng, eng.bar + 2)
    out = eng.undo()
    assert "custom arrangement" in out["back_to"]
    wait_bar(eng, out["at_bar"])
    st = eng.status()["arrangement"]
    expected = "a" if (out["at_bar"] - first["starts_at_bar"]) % 8 < 4 else "b"
    assert st["current"]["section"] == expected
    out = eng.undo()
    assert out["back_to"].startswith("no arrangement")
    wait_bar(eng, out["at_bar"])
    assert eng.status()["arrangement"] is None and eng._arr_muted == set() and eng.muted == set()


def test_undo_refuses_to_restore_an_arrangement_that_would_have_ended(jamming):
    eng, port, inp = jamming()
    eng.play(P["techno"], bpm=240)
    wait_bar(eng, 1)
    eng.arrange(sections=[{"name": "a", "bars": 1, "tracks": ["all"]}, {"name": "b", "bars": 20, "tracks": ["all"]}])
    eng.arrange(clear=True)
    wait_bar(eng, eng.bar + 23)  # 21 bars later the first arrangement would have ended (no loop)
    with pytest.raises(engine.WhiplashError, match="would already have ended.*nothing changed"):
        eng.undo()
    assert eng.playing() and eng.status()["undo"]  # still there


def test_stop_clears_the_undo_stack(jamming):
    eng, port, inp = jamming()
    eng.play(P["techno"], bpm=240)
    wait_bar(eng, 1)
    eng.write_part(7, rhythm="8ths")
    eng.stop()
    assert eng.status()["undo"] == []
    with pytest.raises(engine.WhiplashError, match="nothing to undo"):
        eng.undo()


def test_undo_tool(tool_jam):
    eng, port, inp = tool_jam()
    assert "nothing to undo" in call("whiplash_undo")["error"]
    call("whiplash_play_pattern", genre="techno", bpm=240)
    call("whiplash_write_part", track=7, rhythm="8ths")
    out = call("whiplash_undo")
    assert out["success"] and out["kind"] == "part" and out["track"] == 7


# ---- recording -------------------------------------------------------------------------------------------------

def test_recording_ring_buffer_is_bounded():
    rec = jam.Recording(maxlen=100)
    for i in range(150):
        rec.out(mido.Message("note_on", channel=0, note=60, velocity=1 + i % 100), (i, 0.0, 1.0), float(i))
    for i in range(100):
        rec.heard(cc(1, 74, i), None, 0.0)
    s = rec.summary()
    assert s["events"] == 100 and s["sent"] == 150 and s["received"] == 100 and s["dropped"] == 150
    assert rec.snapshot()[0][0] == "in" and len(rec.snapshot()) == 100


def test_recording_holds_sent_and_heard_events_on_whiplash_clock(jamming):
    eng, port, inp = jamming()
    eng.play_along()
    eng.play(P["techno"], bpm=240)
    wait_bar(eng, 1)
    inp.push(cc(5, 74, 90), note(8, 60), mido.Message("sysex", data=[1, 2, 3]))
    wait(lambda: eng.status()["play_along"]["heard"] == 3)
    eng.set_tempo(250)
    wait_bar(eng, eng.bar + 2)
    eng.stop()
    events = eng.recording_snapshot()
    kinds = collections.Counter(e[0] for e in events)
    assert kinds["out"] > 50 and kinds["in"] == 2 and kinds["mark"] >= 1  # sysex is never recorded
    assert not any(e[3] in ("clock", "sysex", "program_change") for e in events)
    ticks = [e[1] for e in events if e[0] == "out" and e[1] is not None]
    assert ticks == sorted(ticks) and ticks[-1] > BAR  # clock-tick timestamps, in order
    assert ("mark", "tempo", 250.0) in {(e[0], e[3], e[5]) for e in events}
    heard = [e for e in events if e[0] == "in"]
    assert heard[0][3:] == ("control_change", 5, 74, 90) and heard[0][1] is not None
    assert eng.status()["play_along"]["recording"]["in_memory_only"] is True


# ---- rails -----------------------------------------------------------------------------------------------------

def test_received_messages_are_never_re_sent_and_rails_hold(jamming):
    eng, port, inp = jamming()
    eng.play(P["techno"], bpm=240)
    wait_bar(eng, 1)
    eng.follow(9, 7)
    junk = [mido.Message("sysex", data=[0x00, 0x20, 0x3C, 0x10, 0x00]), mido.Message("program_change", program=5),
            cc(0, 0, 1), cc(0, 32, 1), cc(0, 24, 3), cc(5, 99, 1), cc(5, 98, 9), cc(5, 6, 1), cc(5, 38, 0),
            mido.Message("stop"), mido.Message("start")]
    inp.push(*junk)
    wait(lambda: eng.status()["play_along"]["heard"] == len(junk))
    wait_bar(eng, eng.bar + 2)
    eng.stop()
    assert_rails(port)
    assert not any(m.type in ("sysex", "program_change") for m in port.messages)
    assert port.count("start") == 1 and port.count("stop") == 1  # its own, never the unit's


def test_play_along_follow_and_undo_write_no_files(tool_jam, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    real_open, real_io_open, real_os_open = builtins.open, io.open, os.open
    writes = []

    def guard(file, mode="r", *a, **kw):
        if any(c in str(mode) for c in "wax+"):
            writes.append(file)
        return real_open(file, mode, *a, **kw)

    def guard_os(path, flags, *a, **kw):
        if flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT):
            writes.append(path)
        return real_os_open(path, flags, *a, **kw)
    monkeypatch.setattr(builtins, "open", guard)
    monkeypatch.setattr(io, "open", guard)
    monkeypatch.setattr(os, "open", guard_os)
    eng, port, inp = tool_jam()
    call("whiplash_play_pattern", genre="techno", bpm=240)
    assert call("whiplash_play_along")["success"]
    assert call("whiplash_follow", track=9, answer_track=7)["success"]
    inp.push(cc(5, 74, 90), note(8, 65))
    call("whiplash_mix", levels={"6": 90})
    call("whiplash_write_part", track=7, rhythm="8ths")
    assert call("whiplash_undo")["success"]
    call("whiplash_status")
    call("whiplash_play_along", on=False)
    call("whiplash_stop")
    assert writes == [] and list(tmp_path.iterdir()) == []


def test_reader_never_takes_the_engine_lock(jamming):
    """Deterministic half of the jitter test: with _lock held elsewhere, the reader keeps draining the input."""
    eng, port, inp = jamming()
    eng.play_along()
    with eng._lock:
        inp.push(*[cc(i % 16, 74, i % 128) for i in range(2000)])
        end = time.monotonic() + 5
        while eng._input["heard"] < 2000:
            assert time.monotonic() < end, "the reader blocked on the engine lock"
            time.sleep(0.005)


def test_clock_jitter_is_unchanged_under_an_input_flood(jamming):
    port = TimedPort()
    eng, _, inp = jamming(port=port)
    eng.play(P["techno"], bpm=240)
    wait_bar(eng, 2)
    eng.play_along()
    eng.follow(9, 7)
    eng.ramp(6, 127, param="filter_freq", start=0, bars=4)
    base_end = len(port.clock_times)
    stop = threading.Event()

    def flood():
        i = 0
        while not stop.is_set():
            inp.push(*[cc(i % 16, 70 + i % 8, i % 128) for i in range(200)], note(8, 60 + i % 12))
            i += 1
            time.sleep(0.002)  # ~100k messages a second, far past USB MIDI
    t = threading.Thread(target=flood, daemon=True)
    begin = len(port.clock_times)
    t.start()
    wait_bar(eng, eng.bar + 3)
    stop.set()
    t.join()
    end = len(port.clock_times)
    heard = eng._input["heard"]
    eng.stop()
    times = port.clock_times
    assert heard > 10000
    assert_jitter(times[BAR:base_end], times[begin:end], "input flood")
    assert_rails(port)
