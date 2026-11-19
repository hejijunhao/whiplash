"""v0.9.0 ontology O1b: chord-relative notes (harmony.Rel, mode phrase), the phrase library and write_part(phrase),
classic house compiled from its phrases, and the taste layer (bar digest, change log, status review, taste_hint).

Fake and virtual ports only. Nothing here is a hardware result (docs/executing/ontology-v1-spec.md §8)."""
import json
import statistics
import time

import mido
import pytest

from whiplash import engine, genres, harmony, library, patterns, phrases, progressions, schemas, taste, tools
from test_live import bar_events, pretend_playing
from test_v080 import FakeInput, cc, make, wait
from test_whiplash import make_engine

P = patterns.PATTERNS
AM = harmony.Key(9, "minor")
PC = {"A": 9, "F": 5, "C": 0, "G": 7}


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


def track_notes(events, track):
    return [(s, n) for s, t, n, *_ in events if t == track]


def run(eng, first, last):
    return {b: bar_events(eng, b) for b in range(first, last + 1)}


# ---- Rel ------------------------------------------------------------------------------------------------------

def test_rel_arithmetic_keeps_the_tone_and_hashes_as_its_int():
    r = harmony.Rel(57, "oct", 0, 53)
    up = r + 12
    assert isinstance(up, harmony.Rel) and int(up) == 69 and (up.tone, up.octave, up.floor) == ("oct", 0, 53)
    assert isinstance(12 + r, harmony.Rel) and isinstance(r - 3, harmony.Rel) and int(r - 3) == 54
    assert not isinstance(60 - r, harmony.Rel)  # a difference is a plain number
    assert r == 57 and hash(r) == hash(57) and {r: 1}[57] == 1 and json.dumps([r]) == "[57]"
    assert repr(r) == "Rel(57, 'oct', 0, 53)"


def test_register_and_in_key_keep_rels():
    house = patterns.RAW["house"]
    assert all(isinstance(h[1], harmony.Rel) for bar in patterns.register(house).bars[6] for h in bar)
    moved = harmony.in_key(P["house"], harmony.Key(5, "minor"))
    assert all(isinstance(h[1], harmony.Rel) for bar in moved.bars[6] for h in bar)


@pytest.mark.parametrize("text, want", [("R", ("R", 0)), ("R+12", ("oct", 0)), ("5-12", ("5", -1)),
                                        ("b7", ("7", 0)), ("step-2", ("step-2", 0)), ("chord", ("chord", 0))])
def test_parse_tone(text, want):
    assert harmony.parse_tone(text) == want


def test_parse_tone_refuses_nonsense():
    with pytest.raises(harmony.HarmonyError):
        harmony.parse_tone("11th")


# ---- resolution -----------------------------------------------------------------------------------------------

def _prog(name, key):
    return phrases.fallback(name, key)


@pytest.mark.parametrize("phrase", sorted(phrases.PHRASES))
def test_every_phrase_over_every_progression_in_all_keys_stays_native(phrase):
    entry = phrases.PHRASES[phrase]
    for name, prog_entry in sorted(progressions.PROGRESSIONS.items()):
        for pc in range(12):
            prog = _prog(name, harmony.Key(pc, prog_entry.scale))
            bars, _ = phrases.build(entry, prog)
            notes = [int(h[1]) for bar in bars for h in bar]
            assert statistics.median(notes) >= 53, (phrase, name, pc)
            assert patterns.NOTE_MIN <= min(notes) and max(notes) <= patterns.NOTE_MAX


def test_resolution_against_a_chord():
    key = AM
    f = harmony.parse_chord("F", key)
    notes = harmony.voice([f], "close")[0]
    rel = lambda tone, octave=0: harmony.Rel(0, tone, octave, 53)
    assert harmony.resolve(rel("R"), f, notes, key) == 53
    assert harmony.resolve(rel("oct"), f, notes, key) == 65
    assert harmony.resolve(rel("5"), f, notes, key) == 60
    assert harmony.resolve(rel("3"), f, notes, key) == 57
    assert harmony.resolve(rel("7"), f, notes, key) == 65  # no 7th on a triad: the nearest chord tone (the octave)
    assert harmony.resolve(rel("R", 1), f, notes, key) == 65
    assert harmony.resolve(rel("chord"), f, notes, key, rank=0) == notes[-1]
    assert harmony.resolve(rel("chord"), f, notes, key, rank=1) == notes[-2]
    assert harmony.resolve(rel("step-1"), f, notes, key) == 52  # E below F in A minor


def test_approach_lands_one_scale_step_below_the_next_root():
    am = harmony.parse_chord("Am", AM)
    rel = harmony.Rel(0, "approach", 0, 53)
    note = harmony.resolve(rel, am, harmony.voice([am])[0], AM, nxt=5)  # next chord F: approach from E
    assert note == 52 and harmony.scale_step(note, 1, AM) == 53


def test_seeded_phrase_is_identical_across_runs_and_varies_with_the_seed():
    deep = phrases.PHRASES["bass.rolling_deep"]
    prog = _prog(None, AM)
    a, _ = phrases.build(deep, prog, seed=7)
    b, _ = phrases.build(deep, prog, seed=7)
    assert a == b and [[h[1].tone for h in bar] for bar in a] == [[h[1].tone for h in bar] for bar in b]
    tones = {tuple(h[1].tone for h in phrases.build(deep, prog, seed=s)[0][3]) for s in range(12)}
    assert len(tones) > 1  # bar 4 turns around differently per seed
    assert all(bar == a[0] for bar in a[:3])  # bars 1-3 are the phrase as written


def test_density_keeps_the_top_ranked_hits():
    offbeat = phrases.PHRASES["bass.offbeat"]
    assert [h[0] for h in phrases.shape(offbeat)[0]] == [2, 6, 10, 14]  # its default 0.5
    assert [h[0] for h in phrases.shape(offbeat, 1)[0]] == [2, 3, 6, 7, 10, 11, 14, 15]
    assert [h[0] for h in phrases.shape(phrases.PHRASES["stab.offbeat"], 0.25)[0]] == [6]
    pump = phrases.shape(phrases.PHRASES["bass.octave_pump"], 0.25)[0]
    assert [(h[0], h[1]) for h in pump] == [(0, "R"), (8, "R")]  # tones belong to their grid hits


def test_no_on_request_phrase_is_a_genre_default():
    for record in genres.GENRES.values():
        for name in (record.bass, record.chords, record.recommends.get("bass"), record.recommends.get("chords")):
            if name in phrases.PHRASES:
                assert not phrases.PHRASES[name].on_request


def test_phrase_library_lists_and_resolves(tool):
    out = call("whiplash_list_library", kind="phrase")
    assert out["success"] and {e["name"] for e in out["entries"]} == set(phrases.PHRASES)
    bass = call("whiplash_list_library", kind="phrase", tag="bass")["entries"]
    assert {e["name"] for e in bass} == {n for n, p in phrases.PHRASES.items() if p.role == "bass"}
    assert [e["name"] for e in call("whiplash_list_library", kind="phrase", genre="chicago")["entries"]] == \
        ["bass.octave_pump", "stab.offbeat"]
    assert library.resolve("phrase", "octave pump").name == "bass.octave_pump"
    with pytest.raises(library.LibraryError, match="list_library"):
        library.resolve("phrase", "bass.wobble_9000")


# ---- classic house from its phrases -----------------------------------------------------------------------------

def test_house_is_compiled_from_its_phrases_with_o1a_notes():
    house = P["house"]
    chords = harmony.parse_chords("i III bII i", AM)
    voiced = harmony.voice(chords, "close")
    for b, (chord, notes) in enumerate(zip(chords, voiced)):
        root = harmony.nearest(chord.root, 55)  # O1a's baked bounce
        assert [(s, int(n), v, g) for s, n, v, g in house.bars[6][b]] == sorted(
            [(s, root, 108, 1) for s in (0, 4, 8, 12)] + [(s, root + 12, 96, 1) for s in (2, 6, 10, 14)])
        for rank, track in enumerate((7, 8)):
            assert [(s, int(n), v, g) for s, n, v, g in house.bars[track][b]] == \
                [(s, notes[::-1][rank], 100 if s == 2 else 88, 1) for s in (2, 6, 10, 14)]
    assert all(isinstance(h[1], harmony.Rel) for t in (6, 7, 8) for bar in house.bars[t] for h in bar)


def test_chicago_plays_its_phrases_alone_and_follows_a_progression(tool):
    out = call("whiplash_play_pattern", genre="chicago")
    assert out["success"] and out["tracks"]["6"]["progression"] == "phrase"
    tool.stop()
    pretend_playing(tool, P["house"])
    tool._warm_fallback(P["house"])
    with tool._lock:
        tool._refresh_harmony()
    bars = run(tool, 0, 3)
    for b, root in zip(range(4), ("A", "C", "A#", "A")):
        beat = {patterns.note_name(n)[:-1] for s, n in track_notes(bars[b], 6) if s % 4 == 0}
        assert beat == {root}
    house = P["house"]
    for b in range(4):  # with nothing set it plays exactly the compiled notes
        assert track_notes(bars[b], 7) == [(s, int(n)) for s, n, *_ in house.bars[7][b]]
    assert tool.set_progression(name="house.uplift")["starts_at_bar"] == 4
    played = run(tool, 4, 11)
    for b, name in zip(range(4, 12), "A A F F C C G G".split()):
        notes = track_notes(played[b], 6)
        roots = {n for s, n in notes if s % 4 == 0}
        assert len(roots) == 1 and (roots.pop() - PC[name]) % 12 == 0
        assert all(n == notes[0][1] + 12 for s, n in notes if s % 4 == 2)  # still the octave bounce


# ---- write_part(phrase) ------------------------------------------------------------------------------------------

def test_octave_pump_follows_house_uplift_and_undo_brings_the_line_back(eng):
    pretend_playing(eng, P["deephouse"])
    before = track_notes(bar_events(eng, 0), 6)
    out = eng.write_part(6, phrase="bass.octave_pump")
    assert out["phrase"] == "bass.octave_pump" and out["follows"] == "key" and out["at_bar"] == 1
    assert [h["step"] for h in out["now"]["hits"]] == list(range(0, 16, 2)) and out["now"]["chord"] == "Am"
    assert out["register"]["root_window"] == ["F4", "E5"]
    eng.set_progression(name="house.uplift")
    played = run(eng, 1, 8)
    for b, name in zip(range(1, 9), "A A F F C C G G".split()):
        notes = track_notes(played[b], 6)
        beats = [n for s, n in notes if s % 4 == 0]
        assert len(set(beats)) == 1 and (beats[0] - PC[name]) % 12 == 0 and 53 <= beats[0] <= 64
        assert [n for s, n in notes if s % 4 == 2] == [beats[0] + 12] * 4
    assert eng.undo()["back_to"] == "the generated line"
    after = run(eng, 9, 9)[9]
    assert [s for s, _ in track_notes(after, 6)] == [s for s, _ in before]  # the hand bass's rhythm again


def test_phrase_follows_the_key_with_no_progression(eng):
    pretend_playing(eng, P["deephouse"])
    eng.write_part(6, phrase="bass.bouncy")
    notes = track_notes(bar_events(eng, 1), 6)
    assert [s for s, _ in notes] == [2, 3, 6, 10, 11, 14] and {n % 12 for _, n in notes} == {9}


def test_thicken_ghost_on_a_phrase_keeps_a_rel_and_resolves(eng):
    pretend_playing(eng, P["deephouse"])
    eng.write_part(6, phrase="bass.octave_pump", density=0.5)
    bar_events(eng, 1)
    eng.mutate_density([6], 1.0)
    with eng._lock:
        eng._rebuild(6)
        eng._refresh_harmony()
    work = eng._work[6][0]
    assert len(work) > 4 and all(isinstance(h[1], harmony.Rel) for h in work)
    eng.set_progression(chords="F", bars_per_chord=4)
    notes = track_notes(bar_events(eng, 2), 6)
    assert len(notes) > 4 and {n % 12 for _, n in notes} == {5}  # every ghost resolved onto F


def test_phrase_genre_per_genre(eng):
    pretend_playing(eng, P["deephouse"])
    assert eng.write_part(6, phrase="genre")["phrase"] == "bass.rolling_deep"
    with pytest.raises(engine.WhiplashError, match="pad.hold.*O3"):
        eng.write_part(7, phrase="genre")
    eng.stop()
    pretend_playing(eng, P["techhouse"])
    out = eng.write_part(7, phrase="genre")
    assert out["phrase"] == "stab.offbeat" and out["density"] == 0.25
    assert [h["step"] for h in out["now"]["hits"]] == [6]
    assert eng.write_part(6, phrase="genre")["phrase"] == "bass.bouncy"
    eng.stop()
    pretend_playing(eng, P["techno"])
    assert eng.write_part(6, phrase="genre")["phrase"] == "bass.offbeat"
    eng.label_tracks({"9": "lead synth"})
    with pytest.raises(engine.WhiplashError, match="leads stay model-written"):
        eng.write_part(9, phrase="genre")
    eng.stop()
    pretend_playing(eng, P["soul"])
    with pytest.raises(engine.WhiplashError, match="no genre phrases"):
        eng.write_part(6, phrase="genre")


def test_phrase_refusals_change_nothing(tool):
    pretend_playing(tool, P["deephouse"])
    tool.label_tracks({"9": "kick"})
    before = tool.status()
    cases = [dict(track=9, phrase="bass.octave_pump"), dict(track=1, phrase="bass.octave_pump"),
             dict(track=6, phrase="bass.octave_pump", notes=["C5"]),
             dict(track=6, phrase="bass.octave_pump", rhythm="8ths"),
             dict(track=6, phrase="bass.octave_pump", out_of_key=True),
             dict(track=6, phrase="bass.octave_pump", density=2), dict(track=6, phrase="bass.octave_pump", register="up"),
             dict(track=6, density=0.5, rhythm="8ths", notes=["A4"]), dict(track=6, phrase="bass.nope")]
    errors = [call("whiplash_write_part", **c) for c in cases]
    assert all(not e["success"] for e in errors), errors
    assert "drum, cymbal or fx" in errors[0]["error"] and "is labelled kick" in errors[0]["error"]
    assert errors[2]["error"] == "phrase brings its own notes; drop notes, or use rhythm + notes"
    assert "list_library" in errors[-1]["error"]
    after = tool.status()
    for k in ("parts", "tracks", "progression", "undo"):
        assert before[k] == after[k], k


def test_phrase_on_a_high_track_and_register(eng):
    pretend_playing(eng, P["deephouse"])
    out = eng.write_part(10, phrase="bass.octave_pump", register="high")
    assert out["channel_note"] and out["register"]["root_window"] == ["G5", "F#6"]
    assert all(67 <= h["note"] <= 90 for h in out["now"]["hits"])


def test_stab_phrases_rank_and_count_for_the_shell_rule(eng):
    pretend_playing(eng, P["deephouse"])
    eng.write_part(7, phrase="stab.offbeat")
    eng.write_part(8, phrase="stab.offbeat")
    out = eng.set_progression(name="deephouse.gospel")
    assert out["voicing"] == "shell" and out["phrases_follow"] == [7, 8] and "note" not in out
    notes = {t: {n for s, tt, n, *_ in bar_events(eng, 1) if tt == t} for t in (7, 8)}
    assert len(notes[7]) == 1 and len(notes[8]) == 1 and notes[7] != notes[8]


# ---- equivalence -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("genre", ["deephouse", "techhouse", "techno", "soul", "breaks"])
def test_hand_written_genres_have_no_phrases_and_play_their_tables(eng, genre):
    pretend_playing(eng, P[genre])
    assert eng._prog_modes == {}
    for b in range(4):
        want = sorted((h[0], t, h[1], h[2], h[3], h[4] if len(h) > 4 else 0.0)
                      for t, bars in P[genre].bars.items() for h in bars[b])
        assert bar_events(eng, b) == want
    eng.set_progression(chords="i VI III VII")
    assert harmony.PHRASE not in eng._prog_modes.values()


# ---- taste: pure ---------------------------------------------------------------------------------------------------

def _digest(n, events=None, chord="Am", ramping=(), sections=None, start=0):
    events = events or {0: [(1, 60, 120, 1, 0.0)], 4: [(1, 60, 120, 1, 0.0)], 8: [(6, 57, 100, 1, 0.0)]}
    return [(b, float(b), events, (sections or {}).get(b), chord, frozenset(), b in ramping)
            for b in range(start, start + n)]


ROLES = {1: "kick", 6: "bass"}


def test_fingerprints_are_stable_and_changes_reset_cycles():
    d = _digest(12)
    assert taste.fingerprint(d[0][2]) == taste.fingerprint(dict(d[0][2]))
    prints = [taste.fingerprint(x[2]) for x in d]
    assert taste.cycles_repeated(prints) == 2
    denser = {**d[0][2], 2: [(1, 60, 60, 1, 0.0)]}
    changed = d[:11] + [(11, 11.0, denser, None, "Am", frozenset(), False)]
    assert taste.cycles_repeated([taste.fingerprint(x[2]) for x in changed]) == 0
    m = taste.metrics(d[:11] + [(11, 11.0, d[0][2], None, "F", frozenset(), False)], [], [], ROLES)
    assert m["chord_static_bars"] == 1
    assert taste.fingerprint(d[0][2], frozenset({6})) != taste.fingerprint(d[0][2])  # muted tracks don't sound


@pytest.mark.parametrize("genre, limit", [("techhouse", 8), ("deephouse", 32), ("house", 32), ("techno", 64),
                                          ("soul", 16)])
def test_thresholds_fire_at_the_boundary(genre, limit):
    for bars, fires in ((limit - 1, False), (limit, True)):
        m = taste.metrics(_digest(bars), [], [], ROLES)
        assert m["unchanged_for_bars"] == bars
        assert ("repetition" in taste.hints(m, genre)) is fires


def test_changes_moves_ramps_and_sections_count_as_change():
    d = _digest(20)
    assert taste.unchanged_for(d, [(15, "t", "s")], []) == 4
    assert taste.unchanged_for(d, [], [(17, "knob")]) == 2
    assert taste.unchanged_for(_digest(20, ramping={18}), [], []) == 1
    assert taste.unchanged_for(_digest(20, sections={b: "intro" if b < 16 else "build" for b in range(20)}), [], []) == 3
    assert taste.unchanged_for(d, [(25, "t", "future")], []) == 20  # not landed yet


def test_busy_hint_and_metrics():
    events = {s: [(t, 60, 100, 1, 0.0) for t in range(1, 8)] for s in (0, 4, 8, 12)}
    events[0].append((6, 57, 100, 1, 0.0))
    roles = {1: "kick", 2: "snare", 3: "clap", 4: "closed hat", 5: "open hat", 6: "bass", 7: "perc"}
    m = taste.metrics(_digest(8, events), [], [], roles)
    assert m["drum_elements"] == 6 and m["hat_density"] == 8 and m["low_collisions"] == 5
    assert m["max_voices_per_step"] == 8
    fired = taste.hints(m, "deephouse")
    assert "busy" in fired and "holds 5" in fired["busy"]
    assert "busy" not in taste.hints(m, "techhouse")  # tech house holds 7


def test_hints_only_name_library_entries():
    for genre, s in taste.SUGGEST.items():
        assert library.resolve("lane", s["lane"]).name == s["lane"]
        assert library.resolve("fill", s["fill"]).name == s["fill"]
        assert library.resolve("phrase", s["phrase"]).name == s["phrase"]
        assert genre in genres.GENRES
    m = taste.metrics(_digest(64), [], [], ROLES)
    for genre in (*taste.SUGGEST, "soul"):
        for text in taste.hints(m, genre).values():
            assert "whiplash_mutate(action: 'energy'" in text


# ---- taste: engine -----------------------------------------------------------------------------------------------

def test_ten_bars_of_tech_house_flag_repetition_deep_house_not(tool):
    pretend_playing(tool, P["techhouse"])
    run(tool, 0, 9)
    review = call("whiplash_status", review=8)
    assert review["success"] and review["window"] == [2, 9] and review["unchanged_for_bars"] >= 8
    assert review["hints"] and "tech house" in review["hints"][0] and review["listen"] is None
    assert review["metrics"]["drum_elements"] >= 4 and "tracks" not in review
    assert call("whiplash_status")["taste"]["hint"] == review["hints"][0]
    tool.stop()
    pretend_playing(tool, P["deephouse"])
    with tool._lock:
        tool.bar_digest.clear()
    run(tool, 0, 9)
    assert call("whiplash_status", review=8)["hints"] == []


def test_energy_up_shows_under_changed_at_its_bar(tool):
    pretend_playing(tool, P["techhouse"])
    run(tool, 0, 3)
    out = call("whiplash_mutate", action="energy", amount="up")
    assert out["success"] and out["lands_at_bar"] == 4
    run(tool, 4, 6)
    review = call("whiplash_status", review=4)
    assert {"bar": 4, "what": "mutate action=energy amount=up", "by": "you"} in review["changed"]
    assert review["unchanged_for_bars"] == 2 and review["energy"] == 4


def test_a_user_knob_move_shows_as_by_user(monkeypatch):
    eng, port, inp = make()
    monkeypatch.setattr(tools, "ENGINE", eng)
    try:
        pretend_playing(eng, P["techhouse"])
        run(eng, 0, 3)
        eng.bar_log.append((3, time.perf_counter()))
        eng.play_along()
        inp.push(cc(5, 74, 40), cc(5, 74, 90))
        wait(lambda: eng.status()["play_along"]["heard"] == 2)
        run(eng, 4, 5)
        review = call("whiplash_status", review=4)
        assert {"bar": 3, "what": "filter_freq on track 6 40 -> 90", "by": "user"} in review["changed"]
        assert review["unchanged_for_bars"] == 2
    finally:
        eng.shutdown()


def test_taste_hint_rides_once(tool):
    pretend_playing(tool, P["techhouse"])
    run(tool, 0, 9)
    first = call("whiplash_mutate", action="humanize", amount=0.1)
    assert first["success"] and "tech house" in first["taste_hint"]
    assert "taste_hint" not in call("whiplash_mutate", action="humanize", amount=0.2)
    assert "taste_hint" not in call("whiplash_status")  # status is not a musical call


def test_review_sends_nothing_and_never_opens_the_input(tool):
    pretend_playing(tool, P["techhouse"])
    run(tool, 0, 5)
    sent = tool.sent_count
    review = call("whiplash_status", review=32)
    assert review["window_note"] == "only 6 bar(s) played, so the review covers those"
    assert tool.sent_count == sent and tool._input is None


def test_review_with_nothing_played_and_bad_values(tool):
    out = call("whiplash_status", review=8)
    assert out["success"] and out["review"] is None and "nothing has played" in out["note"]
    assert not call("whiplash_status", review=2)["success"]
    assert not call("whiplash_status", review="lots")["success"]
    assert call("whiplash_status")["taste"] is None


def test_schemas_carry_the_new_params():
    wp = schemas.SCHEMAS["whiplash_write_part"]["parameters"]["properties"]
    assert {"phrase", "density", "seed", "register"} <= set(wp) and "enum" not in wp["phrase"]
    st = schemas.SCHEMAS["whiplash_status"]
    assert st["parameters"]["properties"]["review"]["maximum"] == 32 and "Feedback only" in st["description"]


def test_bar_line_stays_cheap_with_phrases_and_a_progression(eng):
    pretend_playing(eng, P["house"])
    eng._warm_fallback(P["house"])
    eng.write_part(10, phrase="bass.rolling_deep")
    eng.set_progression(name="deephouse.gospel")
    bar_events(eng, 1)
    t = time.perf_counter()
    for b in range(2, 66):
        bar_events(eng, b)
    per_bar = (time.perf_counter() - t) / 64
    assert per_bar < 0.004, per_bar  # well under one clock tick (~20 ms at 123 BPM)
    assert len(eng.bar_digest) == taste.DIGEST_BARS
