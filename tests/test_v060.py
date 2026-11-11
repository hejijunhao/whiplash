"""v0.6.0: keys and scales on play_pattern and write_part, chord progressions (whiplash_set_progression)."""
import json
import statistics
from pathlib import Path

import pytest

import whiplash
from whiplash import engine, harmony, kitmap, parts, patterns, schemas, tools
from test_whiplash import call, make_engine, tool_engine  # noqa: F401  (fixture)
from test_live import bar_events, pretend_playing, timeline, wait_bar
from test_v051 import TimedPort, _jitter

P = patterns.PATTERNS
ROOT = Path(whiplash.__path__[0])
AM = harmony.Key(9, "minor")


@pytest.fixture
def fake():
    eng, port = make_engine()
    yield eng, port
    eng.shutdown()


def notes(eng, track, bar):
    return [n for _, t, n, *_ in bar_events(eng, bar) if t == track]


def by_step(eng, track, bar):
    out = {}
    for s, t, n, *_ in bar_events(eng, bar):
        if t == track:
            out.setdefault(s, []).append(n)
    return out


def pcs(ns):
    return {n % 12 for n in ns}


# ---- keys -------------------------------------------------------------------

@pytest.mark.parametrize("key, scale, expect", [
    ("Am", None, (9, "minor")), ("A", "minor", (9, "minor")), ("F minor", None, (5, "minor")),
    ("F#", "dorian", (6, "dorian")), ("Bb", None, (10, "major")), ("C", "aeolian", (0, "minor")),
    ("Ebm", None, (3, "minor")),
])
def test_parse_key(key, scale, expect):
    assert tuple(harmony.parse_key(key, scale)) == expect


@pytest.mark.parametrize("key, name", [((9, "minor"), "A minor"), ((5, "minor"), "F minor"), ((10, "major"), "Bb major"),
                                       ((6, "minor"), "F# minor"), ((3, "minor"), "Eb minor"), ((0, "major"), "C major")])
def test_key_names_spell_flats_in_flat_keys(key, name):
    assert harmony.Key(*key).name == name


@pytest.mark.parametrize("key, scale", [("H", None), ("A", "klingon"), ("", None), (None, None), ("A99", None)])
def test_bad_keys_are_refused(key, scale):
    with pytest.raises(harmony.HarmonyError):
        harmony.parse_key(key, scale)


def test_every_pattern_has_a_home_key_its_lines_fit():
    for name, pattern in P.items():
        key = harmony.key_of(pattern.key)
        assert key is not None, name
        for track, bars in pattern.bars.items():
            if not patterns.is_melodic(bars):
                continue
            outside = [n for n in patterns.notes_of(bars) if (n - key.pc) % 12 not in key.steps]
            # deep house and soul lean on G# (the harmonic-minor leading tone of A minor)
            assert all((n - key.pc) % 12 == 11 for n in outside), (name, track, outside)


@pytest.mark.parametrize("name", sorted(P))
@pytest.mark.parametrize("key", [(0, "major"), (5, "minor"), (6, "minor"), (2, "dorian"), (11, "minor")])
def test_in_key_moves_melodic_lines_and_keeps_register_and_drums(name, key):
    key = harmony.Key(*key)
    pattern = P[name]
    moved = harmony.in_key(pattern, key)
    assert moved.key == tuple(key) and moved.name == pattern.name and moved.bpm == pattern.bpm
    for track, bars in pattern.bars.items():
        if not patterns.is_melodic(bars):
            assert moved.bars[track] == bars  # drums untouched
            continue
        new = patterns.notes_of(moved.bars[track])
        assert len(new) == len(patterns.notes_of(bars))  # same rhythm, same hit count
        assert [h[0] for b in moved.bars[track] for h in b] == [h[0] for b in bars for h in b]
        assert all(patterns.NOTE_MIN <= n <= patterns.NOTE_MAX for n in new)
        assert statistics.median(new) >= patterns.NATIVE - patterns.NATIVE_FLOOR  # the v0.5 register rule
        home = harmony.key_of(pattern.key)
        for old, n in zip(patterns.notes_of(bars), new):
            if (old - home.pc) % 12 in home.steps:  # in-scale notes land in the new scale
                assert (n - key.pc) % 12 in key.steps, (name, track, old, n)


def test_in_key_is_degree_by_degree():
    # A minor -> C major: the tonic moves up 3, the minor third (C) becomes the major third (E)
    assert harmony.remap(57, AM, harmony.Key(0, "major"), 3) == 60
    assert harmony.remap(60, AM, harmony.Key(0, "major"), 3) == 64
    assert harmony.remap(56, AM, harmony.Key(5, "minor"), -4) == 52  # G# keeps its offset: E in F minor
    assert harmony.in_key(P["techno"], harmony.Key(5, "minor")) is P["techno"]  # already there
    assert harmony.in_key(P["techno"], None) is P["techno"]


def test_snap_and_nearest():
    assert harmony.snap(61, AM) == 60 and harmony.snap(66, AM) == 65 and harmony.snap(60, AM) == 60
    assert harmony.snap(68, AM) == 67  # G# isn't in natural minor: tie goes down
    assert harmony.nearest(9, 60) == 57 and harmony.nearest(5, 60) == 65 and harmony.nearest(0, 60) == 60
    assert harmony.nearest(6, 60) == 54  # tie (6 each way) goes down
    assert harmony.snap(17, harmony.Key(0, "major")) == 17
    assert harmony.snap(16, harmony.Key(1, "major")) == 17  # 15 would fall below the 16-84 range: go up instead


def test_play_pattern_key_moves_the_lines_on_the_wire(fake):
    eng, port = fake
    eng.play(P["techno"], bpm=300, key="A", scale="minor")
    with eng._lock:
        work = dict(eng._work)
    assert eng.key_name() == "A minor" and eng.status()["key_source"] == "set"
    bass = {h[1] for bar in work[6] for h in bar}
    assert pcs(bass) == {9}  # F -> A
    assert [h[1] for bar in work[1] for h in bar] == [60] * 16  # the kick still plays note 60
    wait_bar(eng, 1)
    eng.stop()
    ons = [m.note for _, _, m in timeline(port) if m.type == "note_on" and m.channel == 5]
    assert ons and pcs(ons) == {9}
    assert eng.status()["key"] == "F minor" and eng.status()["key_source"] == "pattern"  # stop resets the key


def test_queued_switch_carries_the_session_key(fake):
    eng, _ = fake
    eng.play(P["techno"], bpm=300, key="Am")
    out = eng.play(P["breaks"], bpm=300)
    assert out["mode"] == "queued" and eng.status()["queued"]["key"] == "A minor"
    wait_bar(eng, out["switch_at_bar"] + 1)
    with eng._lock:
        assert eng.pattern.name == "breaks" and eng.pattern.key == (9, "minor")
    out = eng.play(P["soul"], bpm=300, key="D", scale="dorian")
    assert eng.status()["queued"]["key"] == "D dorian"
    wait_bar(eng, out["switch_at_bar"] + 1)
    assert eng.key_name() == "D dorian"
    eng.stop()


def test_bad_key_changes_nothing(fake):
    eng, port = fake
    eng.play(P["techno"], bpm=300)
    sent = len(port.messages)
    for kwargs in ({"key": "H"}, {"key": "A", "scale": "nope"}, {"scale": "minor"}):
        with pytest.raises(engine.WhiplashError):
            eng.play(P["breaks"], bpm=300, **kwargs)
    assert eng.status()["queued"] is None and eng.key_name() == "F minor"
    assert {m.type for m in port.messages[sent:]} <= {"start", "clock", "note_on", "note_off"}  # no CC
    eng.stop()


def test_write_part_key_current_uses_the_playing_key(fake):
    eng, _ = fake
    pretend_playing(eng, P["techno"])
    out = eng.write_part(7, rhythm="8ths", key="current", notes="1 3 5 8")
    assert out["key"] == "F5 minor"
    assert [h["note"] for h in out["written"][0]["hits"]][:4] == [65, 68, 72, 77]
    eng._key = harmony.Key(10, "major")
    assert eng.write_part(7, rhythm="8ths", key="current", notes="1")["key"] == "A#4 major"
    with pytest.raises(engine.WhiplashError):
        eng.write_part(7, rhythm="8ths", key="current", scale="klingon", notes="1")


# ---- chords -----------------------------------------------------------------

@pytest.mark.parametrize("symbol, key, root, shape, name", [
    ("i", AM, 9, (0, 3, 7), "Am"), ("VI", AM, 5, (0, 4, 7), "F"), ("III", AM, 0, (0, 4, 7), "C"),
    ("VII", AM, 7, (0, 4, 7), "G"), ("V7", AM, 4, (0, 4, 7, 10), "E7"), ("ii°", AM, 11, (0, 3, 6), "Bdim"),
    ("iv7", AM, 2, (0, 3, 7, 10), "Dm7"), ("bVII", harmony.Key(0, "major"), 10, (0, 4, 7), "A#"),
    ("bVII", harmony.Key(5, "major"), 3, (0, 4, 7), "Eb"), ("Imaj7", harmony.Key(0, "major"), 0, (0, 4, 7, 11), "Cmaj7"),
    ("Vsus4", harmony.Key(0, "major"), 7, (0, 5, 7), "Gsus4"), ("VI", harmony.Key(5, "minor"), 1, (0, 4, 7), "Db"),
    ("Am", AM, 9, (0, 3, 7), "Am"), ("F", AM, 5, (0, 4, 7), "F"), ("G7", AM, 7, (0, 4, 7, 10), "G7"),
    ("Bbmaj7", AM, 10, (0, 4, 7, 11), "Bbmaj7"), ("F#m7b5", AM, 6, (0, 3, 6, 10), "F#m7b5"), ("C5", AM, 0, (0, 7), "C5"),
    ("Ebm", AM, 3, (0, 3, 7), "Ebm"), ("bm", AM, 11, (0, 3, 7), "Bm"),
])
def test_parse_chord(symbol, key, root, shape, name):
    chord = harmony.parse_chord(symbol, key)
    assert (chord.root, chord.shape, chord.name, chord.symbol) == (root, shape, name, symbol)


def test_chords_split_on_spaces_commas_and_dashes():
    assert harmony.split_chords("i–VI–III–VII") == ["i", "VI", "III", "VII"]
    assert harmony.split_chords("i - VI, III | VII") == ["i", "VI", "III", "VII"]
    assert harmony.split_chords(["i", " VI "]) == ["i", "VI"]
    assert [c.name for c in harmony.parse_chords("i-VI-III-VII", harmony.Key(5, "minor"))] == ["Fm", "Db", "Ab", "Eb"]


@pytest.mark.parametrize("bad", ["", [], "Vi", "IIX", "H7", "Amaj9#11", "viiq", [3], ["i", None], ["i"] * 17, 42])
def test_bad_chords_are_refused(bad):
    with pytest.raises(harmony.HarmonyError):
        harmony.parse_chords(bad, AM)


@pytest.mark.parametrize("voicing", harmony.VOICINGS)
def test_voicings_sit_near_native_and_hold_the_chord(voicing):
    for text, key in (("i VI III VII", AM), ("ii7 V7 Imaj7 vi", harmony.Key(0, "major")),
                      ("i iv v i", harmony.Key(1, "minor")), ("Bbmaj7 F#m7b5 Esus4 C5", AM)):
        chords = harmony.parse_chords(text, key)
        for chord, ns in zip(chords, harmony.voice(chords, voicing)):
            assert list(ns) == sorted(ns) and len(set(ns)) == len(ns)
            assert harmony.CHORD_BOTTOM <= ns[0] and ns[-1] <= harmony.CHORD_HIGH
            assert harmony.CHORD_LOW <= statistics.median(ns) <= 70  # around native pitch, never stretched far down
            want = {(chord.root + i) % 12 for i in chord.shape}
            if voicing == "power":
                assert pcs(ns) <= want and chord.root in pcs(ns)
            else:
                assert pcs(ns) == want


def test_close_voicing_moves_less_than_root_position():
    chords = harmony.parse_chords("i VI III VII i iv v i", AM)

    def motion(vs):
        return sum(sum(abs(a - b) for a, b in zip(x, y)) for x, y in zip(vs, vs[1:]))
    assert motion(harmony.voice(chords, "close")) < motion(harmony.voice(chords, "root"))
    assert harmony.voice(chords, "close") == harmony.voice(chords, "close")  # deterministic


# ---- progressions on the beat --------------------------------------------------------

def test_progression_lands_on_the_next_bar_and_changes_every_n_bars(fake):
    eng, _ = fake
    pretend_playing(eng, P["deephouse"])
    before = bar_events(eng, 0)
    out = eng.set_progression(chords="i VI III VII", bars_per_chord=2)
    assert out["starts_at_bar"] == 1 and out["loop_bars"] == 8 and out["key"] == "A minor"
    assert [c["name"] for c in out["progression"]] == ["Am", "F", "C", "G"]
    assert out["tracks"] == {"6": "root", "7": "chords", "8": "chords"}
    assert bar_events(eng, 0) == before  # the bar already playing is untouched
    roots = {1: 9, 2: 9, 3: 5, 4: 5, 5: 0, 6: 0, 7: 7, 8: 7, 9: 9}
    for bar, root in roots.items():
        voiced = out["progression"][(bar - 1) // 2 % 4]["notes"]
        assert pcs(notes(eng, 6, bar)) == {root}, bar  # bass on the root
        for track in (7, 8):
            assert set(notes(eng, track, bar)) <= set(voiced), (bar, track)


def test_chord_tracks_split_the_chord_one_tone_per_hit(fake):
    eng, _ = fake
    pretend_playing(eng, P["deephouse"])
    out = eng.set_progression(chords=["i"])
    voiced = out["progression"][0]["notes"]
    seven, eight = by_step(eng, 7, 1), by_step(eng, 8, 1)
    assert set(seven) == set(eight) == {0, 3, 6, 10}  # the pattern's chord rhythm is kept
    for step in seven:
        assert len(seven[step]) == len(eight[step]) == 1  # one note per hit: fine on a one-voice track
        assert seven[step] != eight[step]  # the two chord tracks sound different chord tones
    assert pcs(n for s in seven.values() for n in s) | pcs(n for s in eight.values() for n in s) == pcs(voiced)


def test_stack_mode_sends_every_tone_on_every_hit(fake):
    eng, _ = fake
    pretend_playing(eng, P["deephouse"])
    out = eng.set_progression(chords=["VI"], voicing="root", tracks={"7": "stack"})
    assert out["tracks"]["7"] == "stack" and "polyphony_note" in out
    for step, ns in by_step(eng, 7, 1).items():
        assert sorted(ns) == out["progression"][0]["notes"] == [53, 57, 60]


def test_drums_never_change_and_lead_snaps(fake):
    eng, _ = fake
    fresh = pretend_playing(make_engine()[0], P["soul"])
    drums = {t: notes(fresh, t, 1) for t in range(1, 6)}
    pretend_playing(eng, P["soul"])  # track 7 "chop" is a lead line
    eng.set_progression(chords="Dm G C F", key="C")  # a key change too: the pattern moves at bar 1
    for t in range(1, 6):
        assert notes(eng, t, 1) == drums[t] and set(drums[t]) <= {60}
    status = eng.status()
    assert status["tracks"]["7"]["progression"] == "snap" and status["key"] == "C major"
    for bar in (1, 2, 3, 4):
        assert all((n % 12) in parts.SCALES["major"] for n in notes(eng, 7, bar))


def test_kit_labels_pick_the_chord_tracks_and_cymbals_never_get_chords(fake):
    eng, _ = fake
    eng.label_tracks(tracks={"7": "tuned cymbal", "9": "warm pad", "6": "dirty bass"})
    pretend_playing(eng, P["techno"])
    out = eng.set_progression(chords="i VI III VII")
    assert out["tracks"] == {"6": "root", "9": "chords"}  # the cymbal track gets no chord, bass or lead mode
    assert set(notes(eng, 7, 1)) == {60}  # it plays the open hat (its close role), untouched
    pad = by_step(eng, 9, 1)
    assert pad and all(len(ns) == 1 for ns in pad.values())
    with pytest.raises(engine.WhiplashError, match="cymbal"):
        eng.set_progression(chords="i VI", tracks={"7": "chords"})
    with pytest.raises(engine.WhiplashError, match="kick"):
        eng.set_progression(chords="i VI", tracks={"1": "root"})
    assert eng.set_progression(chords="i", tracks={"7": "off"})["tracks"] == {"6": "root", "9": "chords"}


def test_an_empty_chord_track_holds_a_tone_per_bar(fake):
    eng, _ = fake
    eng.label_tracks(tracks={"11": "pad"})
    pretend_playing(eng, P["breaks"])  # breaks' pad goes to the labelled pad track 11...
    eng.label_tracks(tracks={"12": "strings"})  # ...and a second pad track has no part at all
    eng._reroute()
    out = eng.set_progression(chords="i VI", bars_per_chord=1)
    assert out["tracks"]["12"] == "chords"
    held = [(s, n, g) for s, t, n, v, g, _ in bar_events(eng, 1) if t == 12]
    assert len(held) == 1 and held[0][0] == 0 and held[0][2] == harmony.PAD_GATE
    assert held[0][1] in out["progression"][0]["notes"]
    assert [n for s, t, n, *_ in bar_events(eng, 2) if t == 12][0] in out["progression"][1]["notes"]
    assert bar_events(eng, 0) and all(t != 12 for _, t, *_ in bar_events(eng, 0))  # nothing before the start


def test_written_parts_play_as_written_unless_named(fake):
    eng, _ = fake
    pretend_playing(eng, P["techno"])
    eng.write_part(6, rhythm="8ths", notes=["C5", "D#5"])
    out = eng.set_progression(chords="VI")
    assert "6" not in out["tracks"] and out["written_unchanged"] == [6]
    assert set(notes(eng, 6, 1)) == {60, 63}
    at = eng.set_progression(chords="VI", tracks={"6": "root"})["starts_at_bar"]
    assert pcs(notes(eng, 6, at)) == {1}  # Db, the VI of F minor
    assert "follows the progression" in eng.write_part(6, rhythm="8ths", notes=["C5"])["progression"]
    eng.write_part(6, reset=True)
    assert pcs(notes(eng, 6, at + 1)) == {1}


def test_progression_carries_across_switches_and_mutate_reset_and_stop_clears_it(fake):
    eng, port = fake
    eng.play(P["techno"], bpm=300)
    eng.set_progression(chords="i iv", bars_per_chord=1)
    out = eng.play(P["breaks"], bpm=300)
    wait_bar(eng, out["switch_at_bar"] + 1)
    assert eng.status()["progression"]["names"] == ["Fm", "Bbm"]
    with eng._lock:
        assert eng.pattern.key == (5, "minor")  # breaks (G minor) plays in the progression's key
    eng.reset_mutations()
    assert eng.status()["progression"] is not None
    eng.stop()
    status = eng.status()
    assert status["progression"] is None and status["key_source"] == "pattern"
    bass = [m.note for _, _, m in timeline(port) if m.type == "note_on" and m.channel == 5]
    assert pcs(bass) <= {5, 10, 7}  # F and Bb roots, plus breaks' own G before the progression started


def test_status_shows_the_chord_now_and_the_next_change(fake):
    eng, _ = fake
    pretend_playing(eng, P["deephouse"])
    eng.set_progression(chords="i VI III VII", bars_per_chord=2)
    assert "now" not in eng.status()["progression"]  # it starts on the next bar
    for bar in range(1, 6):
        bar_events(eng, bar)
    prog = eng.status()["progression"]
    assert prog["now"] == {"chord": "III", "name": "C", "index": 2, "next_change_at_bar": 7}
    assert prog["chords"] == ["i", "VI", "III", "VII"] and prog["key"] == "A minor" and prog["loop_bars"] == 8
    assert eng.status()["tracks"]["7"]["progression"] == "chords"


def test_bad_progression_input_changes_nothing(fake):
    eng, port = fake
    pretend_playing(eng, P["deephouse"])
    eng.set_progression(chords="i VI")
    before, sent = eng.status()["progression"], len(port.messages)
    for kwargs in ({"chords": "i XI"}, {"chords": ""}, {"chords": "i", "bars_per_chord": 0},
                   {"chords": "i", "bars_per_chord": 2.5}, {"chords": "i", "voicing": "drop9"},
                   {"chords": "i", "tracks": {"7": "loud"}}, {"chords": "i", "tracks": {"99": "chords"}},
                   {"chords": "i", "key": "H"}, {"chords": "i", "scale": "minor"},
                   {"chords": "i", "tracks": {"4": "chords"}}, {"clear": True, "chords": "i"}):
        with pytest.raises(engine.WhiplashError):
            eng.set_progression(**kwargs)
    assert eng.status()["progression"] == before and len(port.messages) == sent and eng.key_name() == "A minor"


def test_progression_needs_a_beat_and_clear_ends_it(fake):
    eng, _ = fake
    with pytest.raises(engine.WhiplashError, match="play_pattern"):
        eng.set_progression(chords="i VI")
    pretend_playing(eng, P["deephouse"])
    plain = notes(eng, 6, 4)
    at = eng.set_progression(chords="VI")["starts_at_bar"]
    assert at == 5 and notes(eng, 6, 8) != plain  # bar 8 plays the same loop bar as bar 4
    out = eng.set_progression(clear=True)
    assert out["cleared"] and notes(eng, 6, 12) == plain and eng.status()["progression"] is None


def test_transpose_still_applies_on_top(fake):
    eng, _ = fake
    pretend_playing(eng, P["deephouse"])
    eng.set_progression(chords="i")
    root = notes(eng, 6, 1)
    eng.set_transpose(6, octaves=1)
    assert notes(eng, 6, 1) == [n + 12 for n in root]


def test_progression_runs_on_the_wire_bar_by_bar(fake):
    eng, port = fake
    eng.play(P["techno"], bpm=300)
    out = eng.set_progression(chords="i VI III VII", bars_per_chord=1)
    start = out["starts_at_bar"]
    wait_bar(eng, start + 4)
    eng.stop()
    bass = {}
    for bar, _, m in timeline(port):
        if m.type == "note_on" and m.channel == 5:
            bass.setdefault(bar, set()).add(m.note % 12)
    want = [5, 1, 8, 3]  # Fm Db Ab Eb
    for i in range(4):
        assert bass[start + i] == {want[i]}, (start + i, bass)


def test_clock_jitter_is_unchanged_with_a_progression():
    port = TimedPort()
    eng, _ = make_engine(port)
    try:
        eng.play(P["deephouse"], bpm=240)
        wait_bar(eng, 1)
        for track in range(9, 13):
            eng.write_part(track, rhythm="16ths", notes=["C5"])
        eng.set_progression(chords="i VI III VII iv7 V7", voicing="open",
                            tracks={"9": "stack", "10": "stack", "11": "chords", "12": "snap"})
        at = eng.bar + 1
        wait_bar(eng, at + 2)
        eng.stop()
    finally:
        eng.shutdown()
    t = port.clock_times
    base, chords = t[:at * engine.TICKS_PER_BAR], t[at * engine.TICKS_PER_BAR:(at + 2) * engine.TICKS_PER_BAR]
    assert len(chords) == 2 * engine.TICKS_PER_BAR
    assert port.count("note_on", channel=8) >= 2 * 16 * 3  # stacked chords on 16ths really played
    assert _jitter(chords) <= max(_jitter(base) * 2, _jitter(base) + 0.003), (_jitter(base), _jitter(chords))


# ---- tool, schema, docs, version ----------------------------------------------------

def test_set_progression_tool_and_status(tool_engine):
    eng, port = tool_engine()
    out = call("whiplash_set_progression", chords="i VI III VII")
    assert not out["success"] and "play_pattern" in out["error"]
    out = call("whiplash_play_pattern", genre="deephouse", bpm=300, key="Am")
    assert out["success"] and out["key"] == "A minor"
    out = call("whiplash_set_progression", chords=["i", "VI", "III", "VII"], bars_per_chord=2, voicing="close")
    assert out["success"] and out["starts_at_bar"] >= 1 and out["tracks"]["7"] == "chords"
    status = call("whiplash_status")
    assert status["key"] == "A minor" and status["progression"]["names"] == ["Am", "F", "C", "G"]
    queued = call("whiplash_play_pattern", genre="techno", bpm=300)
    assert queued["key"] == "A minor" and queued["progression_carried"] == ["Am", "F", "C", "G"]
    out = call("whiplash_set_progression", chords="i", tracks={"1": "chords"})
    assert not out["success"] and "drums" in out["error"]
    assert call("whiplash_set_progression", clear=True)["cleared"]
    assert call("whiplash_stop")["success"]


def test_schemas_for_keys_and_progressions():
    play = schemas.SCHEMAS["whiplash_play_pattern"]["parameters"]["properties"]
    assert set(play["scale"]["enum"]) == set(parts.SCALES) and "key" in play
    prog = schemas.SCHEMAS["whiplash_set_progression"]
    props = prog["parameters"]["properties"]
    assert set(props) == {"chords", "bars_per_chord", "voicing", "key", "scale", "tracks", "clear"}
    assert props["voicing"]["enum"] == list(harmony.VOICINGS)
    assert props["tracks"]["additionalProperties"]["enum"] == list(harmony.MODES)
    assert "whiplash:digitakt" in prog["description"] and "cymbal" in prog["description"]
    assert "current" in schemas.SCHEMAS["whiplash_write_part"]["parameters"]["properties"]["key"]["description"]
    assert len(prog["description"]) <= 400
    json.dumps(schemas.SCHEMAS)


def test_never_roles_cover_every_unpitched_role():
    assert harmony.NEVER == frozenset(kitmap.ROLES) - kitmap.MELODIC - {"other"}
    assert set(harmony.ROLE_MODES) == kitmap.MELODIC


def test_skill_and_readme_cover_v060():
    skill = (ROOT / "skills" / "digitakt" / "SKILL.md").read_text()
    for fact in ("whiplash_set_progression", "bars_per_chord", "key: \"current\"", "stack", "snap", "root",
                 "i VI III VII", "cymbal", "one note at a time"):
        assert fact in skill, fact
    readme = (ROOT / "README.md").read_text()
    assert "whiplash_set_progression" in readme and "Keys and progressions" in readme


def test_changelog_keeps_0_6_0():  # the version itself is pinned by the newest release's test
    import yaml
    assert "\n## 0.6.0\n" in (ROOT / "CHANGELOG.md").read_text()
    assert "whiplash_set_progression" in yaml.safe_load(open(ROOT / "plugin.yaml"))["provides_tools"]


def test_no_new_message_types_or_unblocked_ccs():
    from whiplash import ccmap
    assert engine.ALLOWED_TYPES == {"note_on", "note_off", "control_change", "clock", "start", "stop", "continue"}
    assert {0, 32, 24, 6, 38, 98, 99} <= set(ccmap.BLOCKED_CCS)
    assert tools.HANDLERS["whiplash_set_progression"]
