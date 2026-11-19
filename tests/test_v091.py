"""v0.9.1 ontology O2: harmony intents (darker, brighter, tension, release; how harmonic, timbral, register), key-only
set_progression, key lock on/off, the pedal mode and write_part(follow).

Fake and virtual ports only. Nothing here is a hardware result (docs/executing/ontology-v1-spec.md §8)."""
import json
import statistics
import time

import pytest

from whiplash import engine, harmony, kitmap, patterns, progressions, schemas, tools
from test_live import bar_events, pretend_playing
from test_whiplash import make_engine

P = patterns.PATTERNS
AM = harmony.Key(9, "minor")
FILTER = engine.FILTER_CC


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


def call(tool_name, **params):
    return json.loads(tools.HANDLERS[tool_name](params))


def notes_on(events, track):
    return [n for s, t, n, *_ in events if t == track]


def drums(events):
    return [e for e in events if e[1] in (1, 2, 3, 4, 5)]


def filter_ccs(port):
    return [(m.channel + 1, m.value) for m in port.messages if m.type == "control_change" and m.control == FILTER]


def run(eng, first, last):
    return {b: bar_events(eng, b) for b in range(first, last + 1)}


def harmony_view(eng):
    """What a refusal must leave alone."""
    with eng._lock:
        return (eng._key, eng._prog, eng._harmony_next, eng._tension, eng._register, dict(eng._transpose),
                dict(eng._timbral_base), list(eng._undo), eng.key_lock)


# ---- pure: the ladder, mode shifts, tension chords, pedal -------------------------------------------------------

def test_the_ladder_steps_one_rung_and_stops_at_phrygian_and_lydian():
    assert harmony.step_mode("minor", darker=True) == "phrygian"
    assert harmony.step_mode("phrygian", darker=True) is None  # the floor: locrian is never chosen
    assert harmony.step_mode("major", darker=False) == "lydian" and harmony.step_mode("lydian", darker=False) is None
    walk, scale = [], "lydian"
    while scale:
        walk.append(scale)
        scale = harmony.step_mode(scale, darker=True)
    assert walk == list(harmony.LADDER) and "locrian" not in walk
    with pytest.raises(harmony.HarmonyError, match="ladder"):
        harmony.step_mode("blues", darker=True)


def test_move_chord_flattens_by_degree():
    phry = harmony.Key(9, "phrygian")
    names = [harmony.move_chord(c, AM, phry).name for c in harmony.parse_chords("i7 iv7 VII7 v VImaj7 i9", AM)]
    assert names == ["Am7", "Dm7", "Gm7", "Edim", "Fmaj7", "Am7b9"]
    assert phry.flats and harmony.Key(9, "lydian").flats is False  # A phrygian spells like F major
    # a key change by interval: A minor -> F minor moves every chord down a major third
    fm = harmony.Key(5, "minor")
    assert [harmony.move_chord(c, AM, fm).name for c in harmony.parse_chords("Am F C G", AM)] == \
        ["Fm", "Db", "Ab", "Eb"]


@pytest.mark.parametrize("darker", [True, False])
def test_mode_steps_keep_every_library_progression_native_in_all_keys(darker):
    for entry in progressions.PROGRESSIONS.values():
        for pc in range(12):
            session = harmony.Key(pc, "minor")
            key, _ = progressions.key_for(entry, session)
            nxt = harmony.step_mode(key.scale, darker) if key.scale in harmony.LADDER else None
            if nxt is None:
                continue
            moved = [harmony.move_chord(c, key, harmony.Key(key.pc, nxt))
                     for c in harmony.parse_chords(entry.chords, key)]
            for voicing in ("close", "shell", entry.voicing or "close"):
                for notes in harmony.voice(moved, voicing):
                    assert all(harmony.CHORD_BOTTOM <= n <= harmony.CHORD_HIGH for n in notes), (entry.name, pc)
                    assert statistics.median(notes) >= harmony.CHORD_LOW, (entry.name, pc)


def test_library_swap_picks_by_brightness_then_tags_then_name():
    p = progressions.PROGRESSIONS
    assert progressions.swap(p["deephouse.gospel"], darker=True).name == "deephouse.one_chord"
    assert progressions.swap(p["deephouse.two_chord"], darker=True) is None  # the genre's darkest
    assert progressions.swap(p["deephouse.two_chord"], darker=False).brightness == 0
    assert progressions.swap(p["techno.pedal"], darker=True).brightness == -2
    for entry in p.values():  # deterministic, and always the same genre
        for darker in (True, False):
            pick = progressions.swap(entry, darker)
            if pick is not None:
                assert pick.genre == entry.genre and pick == progressions.swap(entry, darker)
                assert (pick.brightness < entry.brightness) if darker else (pick.brightness > entry.brightness)


def test_dominant_and_pedal_mode():
    assert harmony.dominant(AM).name == "E7" and harmony.dominant(AM, ninth=True).name == "E9"
    assert harmony.dominant(harmony.Key(5, "minor")).name == "C7"
    hits = [(0, 45, 100, 1, 0.0), (2, 57, 90, 1, 0.0), (4, 52, 100, 1, 0.0)]  # A3 A4 E4 in A minor
    out = harmony.apply("pedal", hits, (53, 57, 60), 5, AM, 0)
    assert [n for _, n, *_ in out] == [45, 57, 57] and all(n % 12 == 9 for _, n, *_ in out)
    rel = [(0, harmony.Rel(53, "R", 0, 53), 100, 1, 0.0), (2, harmony.Rel(65, "oct", 0, 53), 90, 1, 0.0)]
    assert [n for _, n, *_ in harmony.apply("pedal", rel, (), 5, AM, 0)] == [57, 69]  # the bounce keeps its octave
    assert "pedal" in harmony.MODES


def test_intent_validation():
    assert engine.check_how(None, "darker") == ("harmonic",)
    assert engine.check_how(["register", "harmonic", "register"], "darker") == ("harmonic", "register")
    for bad, msg in ((("harmonic", "tension"), "how is for darker or brighter"), (("nope", "darker"), "how must be"),
                     (("timbral", None), "how is for darker or brighter")):
        with pytest.raises(engine.WhiplashError, match=msg):
            engine.check_how(*bad)
    with pytest.raises(engine.WhiplashError, match="intent must be one of"):
        engine.check_intent("sadder")
    assert engine.check_follow(True) == "snap" and engine.check_follow("root") == "root"
    assert engine.check_follow(False) is None
    with pytest.raises(engine.WhiplashError, match="follow must be"):
        engine.check_follow("sideways")


# ---- darker / brighter -----------------------------------------------------------------------------------------

def test_darker_goes_to_phrygian_on_the_next_bar_and_is_idempotent_at_the_floor(eng):
    pretend_playing(eng, P["deephouse"])
    bar_events(eng, 0)
    eng.set_progression(chords="i7 VImaj7 VII7 i7", bars_per_chord=1)
    before = bar_events(eng, 1)
    sent = len(eng.test_port.messages)
    out = eng.set_progression(intent="darker")
    assert out["applied"] == ["harmonic"] and out["other_options"] == ["timbral", "register"]
    assert out["did"] == "A minor -> A phrygian" and out["lands_at_bar"] == 2 and out["key"] == "A phrygian"
    assert out["chords"] == ["Am7", "Fmaj7", "Gm7", "Am7"]
    assert eng.key_name() == "A minor"  # nothing lands before the bar line
    assert bar_events(eng, 1) == before
    played = run(eng, 2, 5)
    assert eng.key_name() == "A phrygian"
    assert filter_ccs(eng.test_port) == [] and len(eng.test_port.messages) == sent  # harmonic sends no CC
    g = [n % 12 for n in notes_on(played[4], 7) + notes_on(played[4], 8)]  # bar 4 plays the third chord
    assert 7 in g or 10 in g or 2 in g  # Gm7's tones; B natural (11) gone
    assert all(n % 12 != 11 for b in played.values() for t in (6, 7, 8) for n in notes_on(b, t))
    again = eng.set_progression(intent="darker")
    assert again["unchanged"] and again["applied"] == [] and "already at the floor" in again["did"]
    assert "locrian is never chosen" in again["did"] and eng._harmony_next is None


def test_darker_with_no_progression_moves_the_pattern_by_degree_and_keeps_drums(eng):
    pretend_playing(eng, P["deephouse"])
    before = bar_events(eng, 0)
    out = eng.set_progression(intent="darker")
    assert out["did"] == "A minor -> A phrygian" and out["chords"] == []
    after = bar_events(eng, 4)
    assert drums(after) == drums(before)
    assert all(n % 12 != 11 for t in (6, 7, 8) for n in notes_on(after, t))


def test_darker_swaps_a_library_progression_in_its_genre(eng):
    pretend_playing(eng, P["deephouse"])
    eng.set_progression(name="deephouse.gospel")
    bar_events(eng, 1)
    out = eng.set_progression(intent="darker")
    assert out["did"].startswith("deephouse.gospel -> deephouse.one_chord") and out["chords"] == ["Am9"]
    bar_events(eng, 2)
    assert eng._prog.library == "deephouse.one_chord" and eng.key_name() == "A minor"
    out = eng.set_progression(intent="darker")  # the genre's darkest: the mode ladder takes over
    assert out["did"] == "no darker deephouse progression than deephouse.one_chord; A minor -> A phrygian"
    assert out["chords"] == ["Am7b9"]
    bar_events(eng, 3)
    out = eng.set_progression(intent="brighter")
    assert out["did"] == "A phrygian -> A minor"


def test_timbral_sends_filter_freq_on_melodic_tracks_only_and_brighter_never_opens_past(eng):
    pretend_playing(eng, P["deephouse"])
    eng.label_tracks({"9": "lead"})
    eng.write_part(9, rhythm="8ths", notes=["A5"])
    for track, value in ((1, 100), (4, 100), (6, 100), (7, 90), (9, 110)):
        eng.set_param(track, value, param="filter_freq")
    bar_events(eng, 1)
    eng.test_port.messages.clear()
    out = eng.set_progression(intent="darker", how="timbral")
    assert out["applied"] == ["timbral"] and out["other_options"] == ["harmonic", "register"]
    assert "skipped track(s) [8]" in out["notes"]["timbral"]  # never sent: Whiplash won't guess a cutoff
    assert filter_ccs(eng.test_port) == []  # lands at the bar line
    bar_events(eng, 2)
    assert sorted(filter_ccs(eng.test_port)) == [(6, 84), (7, 74), (9, 94)]  # never kick 1 or hat 4
    eng.set_progression(intent="darker", how="timbral")
    bar_events(eng, 3)
    eng.test_port.messages.clear()
    for bar in (4, 5, 6):
        eng.set_progression(intent="brighter", how="timbral")
        bar_events(eng, bar)
    assert eng._cc_values[(5, FILTER)] == 100 and eng._cc_values[(6, FILTER)] == 90 and eng._cc_values[(8, FILTER)] == 110
    assert max(v for t, v in filter_ccs(eng.test_port) if t == 6) == 100
    out = eng.set_progression(intent="brighter", how="timbral")
    assert out["unchanged"] and "only reopens what a timbral darker closed" in out["did"]


def test_timbral_refuses_when_no_cutoff_is_known_and_changes_nothing(tool):
    pretend_playing(tool, P["deephouse"])
    before = harmony_view(tool)
    out = call("whiplash_set_progression", intent="darker", how=["harmonic", "timbral"])
    assert not out["success"] and "won't guess" in out["error"] and "Nothing changed" in out["error"]
    assert harmony_view(tool) == before


def test_harmonic_plus_register_moves_mode_and_lead_and_undo_restores_all(eng):
    pretend_playing(eng, P["deephouse"])
    eng.label_tracks({"9": "lead"})
    eng.write_part(9, rhythm="8ths", notes=["E5", "G5"])
    eng.set_progression(chords="i7 iv7", bars_per_chord=2)
    eng.set_param(7, 80, param="filter_freq")
    bar_events(eng, 1)
    prog, lead = eng._prog, notes_on(bar_events(eng, 2), 9)
    out = eng.set_progression(intent="darker", how=["harmonic", "register"])
    assert out["applied"] == ["harmonic", "register"] and out["other_options"] == ["timbral"]
    assert "A minor -> A phrygian" in out["did"] and "lead track 9 down an octave" in out["did"]
    played = bar_events(eng, 3)
    assert notes_on(played, 9) == [n - 12 for n in lead]
    assert all(41 <= n <= 79 for n in notes_on(played, 9))
    assert all(len(v) == len(f) - 1 for v, f in zip(eng._prog.voicings, eng._prog.thinned_from))
    undo = eng.undo()
    assert undo["undone"] == "darker (harmonic, register)" and undo["at_bar"] == 4
    assert undo["back_to"]["key"] == "A minor" and undo["back_to"]["transpose"] == {"9": 0}
    restored = bar_events(eng, 4)
    assert eng._prog == prog and eng.key_name() == "A minor" and eng._transpose == {}
    assert notes_on(restored, 9) == lead and eng._register is None


def test_undo_after_timbral_restores_the_cc_values(eng):
    pretend_playing(eng, P["deephouse"])
    eng.set_param(6, 100, param="filter_freq")
    eng.set_param(7, 64, param="filter_freq")
    eng.set_progression(intent="darker", how="timbral")
    bar_events(eng, 1)
    assert eng._cc_values[(5, FILTER)] == 84 and eng._cc_values[(6, FILTER)] == 48
    out = eng.undo()
    assert out["back_to"]["filter_freq"] == {"6": 100, "7": 64}
    bar_events(eng, 2)
    assert eng._cc_values[(5, FILTER)] == 100 and eng._cc_values[(6, FILTER)] == 64 and eng._timbral_base == {}


def test_register_brighter_only_restores_and_the_floor_is_respected(eng):
    pretend_playing(eng, P["deephouse"])
    out = eng.set_progression(intent="brighter", how="register")
    assert out["unchanged"] and "nothing to restore" in out["did"]
    eng.label_tracks({"9": "lead"})
    eng.write_part(9, rhythm="8ths", notes=["E4"])  # 52: an octave down would be 40, below 41
    out = eng.set_progression(intent="darker", how="register")
    assert out["unchanged"] and "below" in out["did"]


def test_two_intents_in_one_bar_compose(eng):
    pretend_playing(eng, P["deephouse"])
    eng.set_param(6, 100, param="filter_freq")
    eng.set_progression(chords="i7 VII7", bars_per_chord=2)
    bar_events(eng, 1)
    eng.set_progression(intent="darker")
    out = eng.set_progression(intent="darker", how="timbral")
    assert out["key"] == "A phrygian"  # built on the pending darker
    bar_events(eng, 2)
    assert eng.key_name() == "A phrygian" and eng._cc_values[(5, FILTER)] == 84


# ---- tension / release ------------------------------------------------------------------------------------------

def test_tension_steps_then_release_brings_the_exact_progression_back(eng):
    pretend_playing(eng, P["deephouse"])
    eng.set_progression(chords="i VI III VII", bars_per_chord=1)
    bar_events(eng, 1)
    prog = eng._prog
    first = eng.set_progression(intent="tension")
    assert first["level"] == 1 and first["did"] == "last chord G -> E7" and first["chords"] == ["Am", "F", "C", "E7"]
    bar_events(eng, 2)
    second = eng.set_progression(intent="tension")
    assert second["did"] == "last chord E7 -> E9"
    bar_events(eng, 3)
    third = eng.set_progression(intent="tension")
    assert "pedal" in third["did"] and third["level"] == 3
    played = run(eng, 4, 7)
    assert eng._prog_modes[6] == "pedal"
    assert {n % 12 for b in played.values() for n in notes_on(b, 6)} == {9}  # A under every chord
    assert eng.set_progression(intent="tension")["unchanged"]
    status = eng.status()["progression"]
    assert status["tension"] == {"level": 3, "of": 3} and "pedal" in status
    out = eng.set_progression(intent="release")
    assert out["did"] == "back to Am F C G, pedal off"
    bar_events(eng, 8)
    assert eng._prog == prog and eng._prog_modes[6] == "root" and eng._tension is None


def test_tension_on_one_chord_and_with_no_progression(eng):
    pretend_playing(eng, P["deephouse"])
    out = eng.set_progression(intent="tension")
    assert out["chords"] == ["Am", "Am", "Am", "E7"] and "vamp" in out["did"]
    bar_events(eng, 1)
    assert eng.set_progression(intent="release")["did"] == "back to no progression, pedal off"
    bar_events(eng, 2)
    assert eng._prog is None
    eng.set_progression(name="deephouse.one_chord")
    bar_events(eng, 3)
    out = eng.set_progression(intent="tension")
    assert out["chords"] == ["Am9", "Am9", "Am9", "E7"]


def test_release_with_nothing_to_release_and_a_plain_progression_forgets_tension(tool):
    pretend_playing(tool, P["deephouse"])
    tool.set_progression(chords="i iv", bars_per_chord=1)
    before = harmony_view(tool)
    out = call("whiplash_set_progression", intent="release")
    assert not out["success"] and out["error"] == "no tension to release; the progression is unchanged"
    assert harmony_view(tool) == before
    tool.set_progression(intent="tension")
    out = tool.set_progression(chords="i VI", bars_per_chord=1)
    assert out["replaced_pending"] == "tension 1" and tool._tension is None and tool._harmony_next is None


# ---- key-only set_progression ---------------------------------------------------------------------------------

def test_key_only_changes_on_the_next_bar_and_keeps_drums(eng):
    pretend_playing(eng, P["deephouse"])
    home = [n for b in range(4) for n in notes_on(bar_events(eng, b), 6)]
    out = eng.set_progression(key="Fm")  # no progression: the pattern's own lines move, degree by degree
    assert out["progression"] is None and out["lands_at_bar"] == 4
    moved = run(eng, 4, 7)
    bass = [n for b in moved.values() for n in notes_on(b, 6)]
    assert statistics.median(bass) >= 53 and sorted({(n - 5) % 12 for n in bass}) == sorted({(n - 9) % 12 for n in home})


def test_key_only_with_a_progression_lands_on_the_next_bar_and_keeps_drums(eng):
    pretend_playing(eng, P["deephouse"])
    eng.set_progression(chords="i VI III VII", bars_per_chord=1)
    bar0 = bar_events(eng, 1)
    out = eng.set_progression(key="Fm")
    assert out == {"key": "F minor", "from": "A minor", "lands_at_bar": 2, "progression": ["Fm", "Db", "Ab", "Eb"],
                   "moves": out["moves"], "lock": "on"}
    assert bar_events(eng, 1) == bar0 and eng.key_name() == "A minor"
    after = run(eng, 2, 5)
    assert eng.key_name() == "F minor"
    assert drums(after[5]) == drums(bar0)
    # the bass follows the new roots (root mode, unchanged since v0.6: the root nearest the line's own register)
    assert [{n % 12 for n in notes_on(after[b], 6)} for b in (2, 3, 4, 5)] == [{1}, {8}, {3}, {5}]  # Db Ab Eb F: the loop runs from bar 1
    assert all(41 <= n <= 79 for b in after.values() for n in notes_on(b, 6))
    assert [c.name for c in eng._prog.chords] == ["Fm", "Db", "Ab", "Eb"]


def test_key_only_rereads_numerals_and_shifts_names(eng):
    pretend_playing(eng, P["deephouse"])
    eng.set_progression(chords="Am F C G")
    bar_events(eng, 1)
    assert eng.set_progression(key="D", scale="minor")["progression"] == ["Dm", "Bb", "F", "C"]
    bar_events(eng, 2)
    eng.set_progression(chords="i VI III VII")
    bar_events(eng, 3)
    out = eng.set_progression(key="C")  # C major: numerals re-read in the new key
    assert out["progression"] == ["Cm", "A", "E", "B"]
    bar_events(eng, 4)
    out = eng.set_progression(scale="dorian")  # scale alone keeps the root
    assert out["key"] == "C dorian" and out["from"] == "C major"


def test_key_only_moves_a_phrase_and_a_library_progression(eng):
    pretend_playing(eng, P["deephouse"])
    eng.write_part(6, phrase="bass.octave_pump")
    eng.set_progression(name="house.uplift")
    bar_events(eng, 1)
    eng.set_progression(key="Fm")
    played = run(eng, 2, 9)
    for b, root in zip(range(2, 10), [5, 1, 1, 8, 8, 3, 3, 5]):  # F Db Ab Eb, two bars each from bar 1
        beats = [n for s, t, n, *_ in played[b] if t == 6 and s % 4 == 0]
        assert {n % 12 for n in beats} == {root}, b
    assert eng._prog.library == "house.uplift"


def test_key_only_refusals_change_nothing(tool):
    pretend_playing(tool, P["deephouse"])
    before = harmony_view(tool)
    cases = [dict(key="Am"), dict(key="H"), dict(key="F", bars_per_chord=2), dict(scale="minor"),
             dict(key="A", scale="nope"), dict(scale="nope")]
    errors = [call("whiplash_set_progression", **c) for c in cases]
    assert all(not e["success"] for e in errors), errors
    assert errors[0]["error"] == "already in A minor" and errors[3]["error"] == "already in A minor"
    assert "go(es) with chords or name" in errors[2]["error"]
    assert harmony_view(tool) == before


def test_intent_refusals(tool):
    out = call("whiplash_set_progression", intent="darker")
    assert not out["success"] and "start a beat first" in out["error"]
    pretend_playing(tool, P["deephouse"])
    before = harmony_view(tool)
    cases = [dict(intent="tension", how="timbral"), dict(intent="darker", chords="i iv"),
             dict(intent="darker", name="deephouse.gospel"), dict(intent="darker", key="F"),
             dict(how="harmonic"), dict(intent="happier"), dict(chords="i", name="deephouse.gospel")]
    errors = [call("whiplash_set_progression", **c) for c in cases]
    assert all(not e["success"] for e in errors), errors
    assert "how is for darker or brighter" in errors[0]["error"]
    assert "not chords and intent" in errors[1]["error"] and "not name and intent" in errors[2]["error"]
    assert errors[6]["error"] == "give chords or name, not both (name brings its own chords)"
    assert harmony_view(tool) == before


def test_the_tool_wrapper_logs_intents_as_changes(tool):
    pretend_playing(tool, P["deephouse"])
    out = call("whiplash_set_progression", intent="darker")
    assert out["success"] and out["lands_at_bar"] == 1
    assert list(tool.changes)[-1][:2] == (1, "whiplash_set_progression")
    assert tool.status()["harmony_pending"] == {"what": "darker (harmonic)", "lands_at_bar": 1}


# ---- key lock and follow ----------------------------------------------------------------------------------------

def test_lock_off_and_on(eng):
    pretend_playing(eng, P["deephouse"])
    assert eng.set_progression(lock=False) == {"lock": "off", "key": "A minor", "does": engine.KEY_LOCK_OFF}
    out = eng.write_part(7, rhythm="8ths", notes=["C#5"])
    assert notes_on(bar_events(eng, 1), 7)[0] == 61 and "snapped" not in out and "off for the session" in out["key_lock"]
    assert eng.status()["key_lock"] == "off"
    eng.stop()
    pretend_playing(eng, P["deephouse"])
    assert eng.key_lock is False  # a session preference: it survives stop, like the kit map
    out = eng.set_progression(chords="i iv", lock=True)
    assert out["lock"] == "on"
    out = eng.write_part(7, rhythm="8ths", notes=["C#5"])
    assert out["snapped"] == [{"from": "C#5", "to": "C5"}]


def test_follow_makes_a_written_part_follow_the_chords_and_the_key(eng):
    pretend_playing(eng, P["deephouse"])
    eng.label_tracks({"9": "lead"})
    out = eng.write_part(9, rhythm="8ths", notes=["B4", "C5", "D5"], follow=True)
    assert out["follow"] == "snap" and out["follows"] == "key"
    assert eng._prog_modes.get(9) == "snap"
    plain = eng.write_part(10, rhythm="8ths", notes=["B4"])
    assert "follow" not in plain and 10 not in eng._prog_modes
    eng.set_progression(key="Fm")
    played = bar_events(eng, 2)
    scale = {(5 + s) % 12 for s in harmony.Key(5, "minor").steps}
    assert all(n % 12 in scale for n in notes_on(played, 9))
    out = eng.write_part(11, rhythm="8ths", notes=["A4"], follow="root")
    eng.set_progression(chords="i VI", bars_per_chord=1)
    assert eng._prog_modes[11] == "root" and eng._prog_modes[9] == "snap"
    roots = [notes_on(bar_events(eng, b), 11) for b in (3, 4)]
    assert {n % 12 for n in roots[0]} == {5} and {n % 12 for n in roots[1]} == {1}  # Fm then Db


def test_follow_refusals_change_nothing(tool):
    pretend_playing(tool, P["deephouse"])
    before = (harmony_view(tool), tool.status()["parts"])
    cases = [dict(track=1, rhythm="four_on_floor", follow=True), dict(track=7, notes=["C5"], rhythm="8ths",
                                                                       follow=True, out_of_key=True),
             dict(track=4, groove="hat.closed_8ths", follow=True), dict(track=6, phrase="bass.octave_pump", follow=False),
             dict(track=7, rhythm="8ths", follow="sideways")]
    errors = [call("whiplash_write_part", **c) for c in cases]
    assert all(not e["success"] for e in errors), errors
    assert "follow is for melodic parts" in errors[0]["error"] and "drop out_of_key" in errors[1]["error"]
    assert "a lane is a drum part" in errors[2]["error"] and "a phrase always follows" in errors[3]["error"]
    assert (harmony_view(tool), tool.status()["parts"]) == before


# ---- equivalence, stop, schema, clock --------------------------------------------------------------------------

@pytest.mark.parametrize("genre", ["deephouse", "techhouse", "techno", "soul", "breaks", "house"])
def test_nothing_changes_without_o2_arguments(genre):
    """The same calls with and without an O2 code path on the way: identical bars (equivalence, spec §4.5)."""
    a, _ = make_engine()
    b, _ = make_engine()
    try:
        pretend_playing(a, P[genre])
        pretend_playing(b, P[genre])
        b.set_progression(lock=True)  # an O2 call that changes nothing musical
        for e in (a, b):
            e.set_progression(chords="i VI III VII", bars_per_chord=1)
        assert run(a, 0, 5) == run(b, 0, 5)
        for e in (a, b):
            e.set_progression(clear=True)
        assert run(a, 6, 9) == run(b, 6, 9)
    finally:
        a.shutdown()
        b.shutdown()


def test_stop_forgets_pending_intents_and_tension(eng):
    pretend_playing(eng, P["deephouse"])
    eng.set_progression(intent="tension")
    eng.stop()
    assert eng._harmony_next is None and eng._tension is None and eng._register is None and eng._undo == []


def test_schemas_carry_the_o2_params():
    props = schemas.SCHEMAS["whiplash_set_progression"]["parameters"]["properties"]
    assert props["intent"]["enum"] == ["darker", "brighter", "tension", "release"]
    assert all(h in props["how"]["description"] for h in progressions.HOWS)
    assert props["tracks"]["additionalProperties"]["enum"] == list(harmony.MODES) and "pedal" in harmony.MODES
    assert "follow" in schemas.SCHEMAS["whiplash_write_part"]["parameters"]["properties"]
    assert "intent" in schemas.SCHEMAS["whiplash_undo"]["description"]
    desc = schemas.SCHEMAS["whiplash_set_progression"]["description"]
    assert "darker" in desc and "key alone" in desc and "cymbal" in desc


def test_bar_line_stays_cheap_with_a_pedal_and_a_pending_key_change(eng):
    pretend_playing(eng, P["house"])
    eng._warm_fallback(P["house"])
    eng.set_progression(name="house.uplift")
    for _ in range(3):
        eng.set_progression(intent="tension")
    bar_events(eng, 1)
    eng.set_progression(key="Fm")
    t0 = time.perf_counter()
    for bar in range(2, 34):
        bar_events(eng, bar)
    per_bar = (time.perf_counter() - t0) / 32
    assert eng._prog_modes[6] == "pedal" and eng.key_name() == "F minor"
    assert per_bar < 0.004, per_bar  # a bar is 2 s at 120 BPM; the sequencer must never notice


def test_an_intent_that_changes_nothing_is_not_logged_as_a_change(tool):
    pretend_playing(tool, P["deephouse"])
    out = call("whiplash_set_progression", intent="brighter", how="register")
    assert out["success"] and out["unchanged"] and list(tool.changes) == []
