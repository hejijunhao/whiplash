"""v0.9.0 ontology O1a: the library, genre records and house compile, aliases, 9th/11th shapes and the shell voicing,
named progressions, key lock, groove lanes with energy levels, microtiming, named fills, and the new tool params.

Fake and virtual ports only. Nothing here is a hardware result (docs/executing/ontology-v1-spec.md §8)."""
import json
import statistics
import time
import tomllib
from pathlib import Path

import pytest
import yaml

import whiplash
from whiplash import (engine, genres, grooves, harmony, kitmap, library, mutate, parts, patterns, phrases,
                      progressions, schemas, tools)
from conftest import STRICT_TIMING
from test_live import bar_events, pretend_playing
from test_whiplash import FakePort, make_engine

ROOT = Path(__file__).resolve().parent.parent
P = patterns.PATTERNS
AM = harmony.Key(9, "minor")


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


def drums(events, tracks=(1, 2, 3, 4, 5, 8)):
    return [e for e in events if e[1] in tracks]


# ---- version, tools, budget -----------------------------------------------

def test_version_is_0_9_3():  # v0.9.3 (ontology O4)
    assert whiplash.__version__ == "0.9.3"
    assert yaml.safe_load(open(ROOT / "plugin.yaml"))["version"] == "0.9.3"
    assert yaml.safe_load(open(ROOT / "docs" / "catalog-entry.yaml"))["version"] == "0.9.3"
    assert tomllib.load(open(ROOT / "pyproject.toml", "rb"))["project"]["version"] == "0.9.3"
    releases = [h for h in (ROOT / "CHANGELOG.md").read_text().split("\n## ")[1:] if not h.startswith("Unreleased")]
    assert releases[0].startswith("0.9.3") and releases[1].startswith("0.9.2")


def test_list_library_is_the_one_new_tool():
    assert len(tools.HANDLERS) == 26
    assert list(tools.HANDLERS)[23] == "whiplash_list_library" == list(schemas.SCHEMAS)[23]
    desc = schemas.SCHEMAS["whiplash_list_library"]["description"]
    assert len(desc) <= 130 and "by name" in desc


def test_names_are_never_schema_enums():
    props = schemas.SCHEMAS["whiplash_play_pattern"]["parameters"]["properties"]
    assert "enum" not in props["groove"] and props["energy"]["maximum"] == 5
    assert "enum" not in schemas.SCHEMAS["whiplash_set_progression"]["parameters"]["properties"]["name"]
    assert "enum" not in schemas.SCHEMAS["whiplash_write_part"]["parameters"]["properties"]["groove"]
    genre_enum = props["genre"]["enum"]
    assert "chicago" in genre_enum and "house" not in genre_enum and "deephouse" in genre_enum


# ---- library ----------------------------------------------------------------

@pytest.mark.parametrize("kind, text, hint, name", [
    ("groove", "deep house shuffle groove", None, "deephouse.shuffle"),
    ("groove", "chicago jack", None, "house.jack"),
    ("groove", "Deep-House_Shuffle", None, "deephouse.shuffle"),
    ("groove", "deephouse.A", None, "deephouse.classic"),
    ("groove", "DEEPHOUSE.a", None, "deephouse.classic"),
    ("groove", "A", "techno", "techno.classic"),
    ("groove", "classic", "techhouse", "techhouse.classic"),
    ("groove", "rolling", "techno", "techno.rolling"),
    ("groove", "rolling", "techhouse", "techhouse.rolling"),
    ("groove", "shuffle", None, "deephouse.shuffle"),
    ("groove", "chicago", None, "house.jack"),
    ("groove", "house jack", None, "house.jack"),
    ("progression", "gospel", None, "deephouse.gospel"),
    ("progression", "deep house gospel progression", None, "deephouse.gospel"),
    ("progression", "piano stab", None, "house.piano_stab"),
    ("lane", "hat offbeat shuffle", None, "hat.offbeat_shuffle"),
    ("fill", "Snare Flam Roll", None, "snare.flam_roll"),
    ("genre", "chicago house", None, "house"),
])
def test_resolve_reads_what_a_model_types(kind, text, hint, name):
    assert library.resolve(kind, text, genre=hint).name == name


def test_resolve_unknown_name_gives_close_matches_and_the_list_hint():
    with pytest.raises(library.LibraryError) as exc:
        library.resolve("groove", "shufle")
    assert "deephouse.shuffle" in str(exc.value) and "whiplash_list_library(kind: 'groove')" in str(exc.value)
    with pytest.raises(library.LibraryError, match="ambiguous"):
        library.resolve("groove", "rolling")  # tech house and techno both have one
    with pytest.raises(library.LibraryError, match="kind must be one of"):
        library.resolve("colour", "x")
    assert library.resolve("form", "techno_plateau").name == "techno_plateau"  # forms and moves arrived in O4


def test_list_library_filters_caps_and_hints(tool):
    out = call("whiplash_list_library", kind="progression", genre="deep house")
    names = [e["name"] for e in out["entries"]]
    assert names == sorted(names) and "deephouse.gospel" in names and "house.uplift" in names  # tagged deephouse
    gospel = next(e for e in out["entries"] if e["name"] == "deephouse.gospel")
    assert gospel["names"] == ["Am7", "Fmaj7", "G7", "Am7"] and gospel["source"].startswith("§1")
    lanes = call("whiplash_list_library", kind="lane")
    assert len(lanes["entries"]) <= library.LIST_MAX and lanes["more"] == max(0, len(grooves.LANES) - 40)
    assert {e["name"] for e in call("whiplash_list_library", kind="lane", tag="perc")["entries"]} >= {"perc.rolling"}
    grooves_out = call("whiplash_list_library", kind="groove", genre="techno")["entries"]
    assert {e["name"] for e in grooves_out} == {"techno.classic", "techno.rolling"}
    assert grooves_out[0]["energy_levels"] == [1, 2, 3, 4, 5]
    empty = call("whiplash_list_library", kind="groove", tag="polka")
    assert empty["entries"] == [] and "genres:" in empty["note"] and "tags:" in empty["note"]
    bad = call("whiplash_list_library", kind="nope")
    assert not bad["success"] and "groove" in bad["error"]
    forms = call("whiplash_list_library", kind="form")
    assert "techno_plateau" in {e["name"] for e in forms["entries"]}  # O4 (v0.9.3)
    assert tool.test_port.messages == []  # read-only: never touches the engine or the port


def test_every_entry_has_about_tags_and_source():
    for kind in ("genre", "progression", "groove", "lane", "fill"):
        for name, entry in library.table(kind).items():
            assert entry.about and entry.source, (kind, name)
            assert library.resolve(kind, name).name == name


# ---- aliases ------------------------------------------------------------------

def test_house_words_and_peak_time():
    assert patterns.resolve("house").name == "deephouse"  # bare "house" still means deep house (§1.5)
    for word in ("chicago", "chicago house", "classic house", "Classic-House"):
        assert patterns.resolve(word).name == "house", word
    assert patterns.resolve(mood="peak time").name == "techno"
    assert patterns.resolve("peak time techno").name == "techno"
    assert patterns.resolve("peak time tech house").name == "techhouse"
    assert patterns.resolve(mood="jacking").name == "house"
    assert patterns.resolve(mood="happy").name == "breaks"  # existing moods unchanged


# ---- genre records and the house compile --------------------------------------

def test_genre_records_match_the_hand_written_tables():
    for name in ("deephouse", "techhouse", "techno"):
        record, pattern = genres.GENRES[name], patterns.RAW[name]
        assert (record.bpm, record.swing, record.key) == (pattern.bpm, pattern.swing, pattern.key)
        assert record.roles == pattern.roles
        assert grooves.GROOVES[record.groove].classic
    assert genres.GENRES["house"].bpm == 123 and genres.GENRES["house"].swing == 0.52


def test_house_compiles_the_jack_groove_octave_bounce_and_stabs():
    house = P["house"]
    assert (house.name, house.bpm, house.swing, house.key, house.family) == ("house", 123, 0.52, (9, "minor"), "house")
    jack, _ = grooves.compile(grooves.GROOVES["house.jack"], 3, house)
    for track in (1, 2, 3, 4, 5):
        assert house.bars[track] == jack.bars[track]
    roots = ["A", "C", "A#", "A"]  # house.piano_stab: Am C Bb Am, a chord a bar
    for bar, root in zip(house.bars[6], roots):
        beats = {patterns.note_name(n)[:-1] for s, n, *_ in bar if s % 4 == 0}
        offbeats = [n for s, n, *_ in bar if s % 4 == 2]
        assert beats == {root}
        assert all(n == [m for s, m, *_ in bar if s == 0][0] + 12 for n in offbeats)  # the octave bounce
    for track in (7, 8):
        assert all(sorted(s for s, *_ in bar) == [2, 6, 10, 14] for bar in house.bars[track])
    chords = harmony.parse_chords("i III bII i", AM)
    for bar, chord in zip(range(4), chords):
        tones = {house.bars[7][bar][0][1] % 12, house.bars[8][bar][0][1] % 12}
        assert tones <= {(chord.root + x) % 12 for x in chord.shape}
    notes = patterns.notes_of(house.bars[6])
    assert statistics.median(notes) >= 53 and patterns.NOTE_MIN <= min(notes) and max(notes) <= patterns.NOTE_MAX


def test_play_chicago_plays_classic_house(tool):
    out = call("whiplash_play_pattern", genre="chicago")
    assert out["success"] and out["playing"] == "house" and out["bpm"] == 123


# ---- shapes and the shell voicing ---------------------------------------------

def test_ninth_and_eleventh_shapes():
    assert harmony.parse_chord("i9", AM).shape == (0, 3, 7, 10, 14)
    assert harmony.parse_chord("Am9", AM).name == "Am9"
    assert harmony.parse_chord("Fmaj9", AM).shape == (0, 4, 7, 11, 14)
    assert harmony.parse_chord("iv11", AM).name == "Dm11"
    assert harmony.parse_chord("VI6", AM).shape == (0, 4, 7, 9)
    assert harmony.parse_chord("Am6", AM).shape == (0, 3, 7, 9)
    assert harmony.parse_chord("VII7sus4", AM).name == "G7sus4"
    assert harmony.parse_chord("G9", AM).shape == (0, 4, 7, 10, 14)


def test_shell_on_am9_is_root_third_seventh_near_60():
    (notes,) = harmony.voice([harmony.parse_chord("i9", AM)], "shell")
    assert sorted(n % 12 for n in notes) == [0, 7, 9]  # C, G, A
    assert abs(statistics.median(notes) - 60) <= 4 and harmony.CHORD_BOTTOM <= min(notes) and max(notes) <= 79


def _labelled(eng, labels):
    eng.label_tracks(tracks=labels)
    with eng._lock:
        eng._reroute()


def test_shell_rule_two_chord_tracks_shell_four_close(eng):
    pretend_playing(eng, P["deephouse"])  # tracks 7 and 8 are chord tracks
    out = eng.set_progression(name="deephouse.one_chord")
    assert out["voicing"] == "shell" and "2 one-voice" in out["voicing_rule"]
    _labelled(eng, {"7": "chord", "8": "chord", "9": "chord", "10": "chord"})  # 9 and 10 hold a tone each
    out = eng.set_progression(name="deephouse.one_chord")
    assert out["voicing"] == "close" and "4 chord tracks" in out["voicing_rule"]
    out = eng.set_progression(name="deephouse.one_chord", voicing="open")
    assert out["voicing"] == "open" and "voicing_rule" not in out  # a given voicing wins
    out = eng.set_progression(chords="i7 iv7")  # typed chords keep today's default
    assert out["voicing"] == "close" and "voicing_rule" not in out


def test_pad_carries_the_ninth_over_shell_chord_tracks(eng):
    pretend_playing(eng, P["deephouse"])
    _labelled(eng, {"9": "pad"})
    out = eng.set_progression(name="deephouse.one_chord")  # Am9 held
    assert out["voicing"] == "shell" and out["pad_tones"] == {"9": "colour tones (the 9th first)"}
    events = bar_events(eng, 1)
    pad = [n for s, t, n, *_ in events if t == 9]
    assert pad and pad[0] % 12 == 11  # B, the 9th
    chord = {n % 12 for s, t, n, *_ in events if t in (7, 8)}
    assert chord <= {9, 0, 7}  # A, C, G: the shell


# ---- named progressions ---------------------------------------------------------

def test_every_progression_parses_in_all_keys_and_voices_in_range():
    for prog in progressions.PROGRESSIONS.values():
        assert prog.tags - {prog.genre} <= progressions.TAGS | progressions.GENRE_TAGS, prog.name
        assert prog.source and prog.about and (prog.bass is None or prog.bass in phrases.PHRASES)  # v0.9.2: O3 names one
        assert -2 <= prog.brightness <= 2 and 0 <= prog.tension <= 3
        for pc in range(12):
            for scale in ("minor", "major"):
                key, _ = progressions.key_for(prog, harmony.Key(pc, scale))
                chords = harmony.parse_chords(prog.chords, key)
                for voicing in {prog.voicing or "close", "shell"}:
                    for notes in harmony.voice(chords, voicing):
                        assert harmony.CHORD_BOTTOM <= min(notes) and max(notes) <= harmony.CHORD_HIGH, prog.name
                        assert statistics.median(notes) >= harmony.CHORD_LOW, prog.name
    counts = {g: sum(p.genre == g for p in progressions.PROGRESSIONS.values()) for g in
              ("deephouse", "house", "techhouse", "techno")}
    assert counts == {"deephouse": 6, "house": 5, "techhouse": 2, "techno": 4}


def test_set_progression_by_name(eng):
    pretend_playing(eng, P["deephouse"])
    out = eng.set_progression(name="deephouse.gospel")
    assert [c["name"] for c in out["progression"]] == ["Am7", "Fmaj7", "G7", "Am7"]
    assert out["bars_per_chord"] == 2 and out["library"]["name"] == "deephouse.gospel" and out["key"] == "A minor"
    assert eng.status()["progression"]["library"] == "deephouse.gospel"
    out = eng.set_progression(name="gospel", bars_per_chord=1)  # given arguments override the entry
    assert out["bars_per_chord"] == 1
    with pytest.raises(engine.WhiplashError, match="not both"):
        eng.set_progression(name="deephouse.gospel", chords="i iv")
    with pytest.raises(engine.WhiplashError, match="whiplash_list_library"):
        eng.set_progression(name="deephouse.gospal")
    assert eng.status()["progression"]["bars_per_chord"] == 1  # the bad calls changed nothing


def test_scale_mismatch_plays_the_relative_major(eng):
    pretend_playing(eng, P["deephouse"])
    out = eng.set_progression(name="house.mixed_shuffle")
    assert out["key"] == "C major (relative of A minor)"
    assert [c["name"] for c in out["progression"]] == ["C", "A#", "Cm", "F"] or \
        [c["name"] for c in out["progression"]] == ["C", "Bb", "Cm", "F"]
    assert eng.key_name() == "A minor"  # the session key and the pattern stay in A minor
    out = eng.set_progression(name="deephouse.dorian_soul")
    assert out["key"].startswith("A dorian") and [c["name"] for c in out["progression"]] == ["Am7", "D7"]


def test_techno_progressions_in_f_minor(eng):
    pretend_playing(eng, P["techno"])
    out = eng.set_progression(name="techno.phrygian")
    assert out["voicing"] == "power" and out["key"] == "F minor"
    assert [c["name"] for c in out["progression"]][1] in ("Gb", "F#")


# ---- key lock -------------------------------------------------------------------

def test_key_lock_snaps_explicit_melodic_notes(eng):
    pretend_playing(eng, P["deephouse"])
    out = eng.write_part(7, rhythm="four_on_floor", notes=["C#5"])
    assert out["snapped"] == [{"from": "C#5", "to": "C5"}] and out["key_lock"] == "A minor"
    assert {n for s, t, n, *_ in bar_events(eng, 1) if t == 7} == {60}
    out = eng.write_part(7, rhythm="four_on_floor", notes=["C#5"], out_of_key=True)
    assert "snapped" not in out
    assert {n for s, t, n, *_ in bar_events(eng, 2) if t == 7} == {61}


def test_key_lock_never_touches_drums(eng):
    pretend_playing(eng, P["deephouse"])
    eng.set_progression(chords="I IV", key="A", scale="major")  # C (60) is out of A major
    out = eng.write_part(1, rhythm="four_on_floor")  # the kick plays note 60
    assert "snapped" not in out and "key_lock" not in out
    out = eng.write_part(1, rhythm="four_on_floor", notes=[60])
    assert "snapped" not in out
    assert {n for s, t, n, *_ in bar_events(eng, 1) if t == 1} == {60}
    out = eng.write_part(6, rhythm="four_on_floor", notes=["C5"])  # bass: melodic, follows the progression's key
    assert out["snapped"] == [{"from": "C5", "to": "B4"}]  # ties go down (C -> B or C#)


def test_key_lock_without_explicit_notes_keeps_the_default_note(eng):
    pretend_playing(eng, P["deephouse"])
    eng.set_progression(chords="I IV", key="A", scale="major")
    out = eng.write_part(6, rhythm="four_on_floor")  # no notes: note 60, the sample's own pitch
    assert "snapped" not in out


# ---- lanes and grooves: integrity ---------------------------------------------

def test_lane_tables_are_well_formed():
    for lane in grooves.LANES.values():
        assert lane.role in grooves.DRUM_ROLES and lane.role in kitmap.ROLES
        assert len(lane.grid) in (1, 2, 4)
        assert sum(len(grooves.parse_cells(bar)) for bar in lane.grid) >= 1  # v0.9.2: a bar may rest (every other bar)
        assert len(lane.velocities) == 16 and all(1 <= v <= 127 for v in lane.velocities)
        assert lane.micro == () or (len(lane.micro) == 16 and all(-3 <= m <= 3 for m in lane.micro))
        assert lane.name.split(".")[0] in ("kick", "clap", "snare", "rim", "hat", "perc"), lane.name


def test_groove_levels_are_known_lanes_busier_and_capped():
    for groove in grooves.GROOVES.values():
        if groove.genre in ("soul", "breaks"):  # v0.9.2: one-level classic grooves (energy 3 = today's pattern)
            assert sorted(groove.levels) == [3] and groove.classic, groove.name
            continue
        assert sorted(groove.levels) == [1, 2, 3, 4, 5], groove.name
        cap = genres.GENRES[groove.genre].taste["busy_drums"]
        for energy, slots in groove.levels.items():
            assert len(slots) <= cap, (groove.name, energy)
            for slot, ref in slots.items():
                assert grooves.slot_role(slot) in grooves.DRUM_ROLES
                if ref.startswith("@"):
                    assert groove.classic and (ref == "@" or ref[2:] in grooves.LANES)
                else:
                    assert ref in grooves.LANES and grooves.LANES[ref].role == grooves.slot_role(slot)
        hits = grooves.hits_per_level(groove, P[groove.genre])
        assert all(hits[e] <= hits[e + 1] for e in range(1, 5)), (groove.name, hits)
        for fill in groove.fills.values():
            assert fill in grooves.FILLS
    counts = {g: sum(x.genre == g for x in grooves.GROOVES.values()) for g in ("deephouse", "house", "techhouse",
                                                                               "techno")}
    assert counts == {"deephouse": 2, "house": 2, "techhouse": 2, "techno": 2}


def test_classic_grooves_have_no_micro():
    for groove in grooves.GROOVES.values():
        if not groove.classic:
            continue
        for energy in groove.levels:
            pattern, _ = grooves.compile(groove, energy, P[groove.genre])
            offsets = {h[4] for bars in pattern.bars.values() for bar in bars for h in bar if len(h) > 4}
            assert offsets <= {0.0}, (groove.name, energy)


# ---- equivalence (demo-safe) ------------------------------------------------------

@pytest.mark.parametrize("genre, groove", [("deephouse", "deephouse.classic"), ("deephouse", "deephouse.A"),
                                           ("techhouse", "techhouse.classic"), ("techno", "techno.classic")])
def test_classic_groove_at_energy_3_is_todays_pattern(genre, groove):
    entry = library.resolve("groove", groove)
    compiled, _ = grooves.compile(entry, 3, P[genre])
    assert compiled is P[genre]
    a, _ = make_engine()
    b, _ = make_engine()
    try:
        pretend_playing(a, P[genre])
        pretend_playing(b, compiled)
        for bar in range(4):
            assert bar_events(a, bar) == bar_events(b, bar)
    finally:
        a.shutdown()
        b.shutdown()


def test_classic_level_3_built_from_refs_matches_too():
    for genre in ("deephouse", "techhouse", "techno"):
        groove = grooves.GROOVES[grooves.CLASSIC[genre]]
        rebuilt, _ = grooves.compile(replace_aliases(groove), 3, P[genre])
        assert mutate.working(rebuilt) == mutate.working(P[genre])


def replace_aliases(groove):
    from dataclasses import replace
    return replace(groove, aliases=())  # not classic any more: compile builds level 3 from the "@" refs


def test_play_pattern_without_groove_is_unchanged(tool):
    out = call("whiplash_play_pattern", genre="deephouse")
    assert out["playing"] == "deephouse" and "groove" not in out
    assert tool.pattern is P["deephouse"] or tool._raw_pattern is P["deephouse"]
    out = call("whiplash_play_pattern", genre="deephouse", groove="A")
    assert out["groove"]["name"] == "deephouse.classic" and out["next"] == "deephouse"


# ---- microtiming and ghosts ---------------------------------------------------------

def test_clap_plays_late_and_hat_pushes_early():
    clap, _ = grooves.lane_bars(grooves.LANES["clap.2_4_ghosted"])
    assert [(s, o) for s, _, _, _, o in clap[0] if s in (4, 12)] == [(4, 0.75), (12, 0.75)]
    push, clamped = grooves.lane_bars(grooves.LANES["hat.push_16ths"], swing=0.5)
    step5 = [h for h in push[0] if h[0] == 5]
    assert (5, 5.75) in [(h[0], h[4]) for h in step5]  # step 6's hit, 0.25 tick early
    assert clamped == ["hat.push_16ths"]  # step 0 can't be pushed into the previous bar
    swung, _ = grooves.lane_bars(grooves.LANES["hat.push_16ths"], swing=0.56)
    sw = (0.56 - 0.5) * 2 * 6
    assert any(h[0] == 5 and abs(h[4] - (5.75 - sw)) < 1e-6 for h in swung[0])  # step 6 from odd step 5
    assert any(h[0] == 4 and abs(h[4] - (5.75 + sw)) < 1e-6 for h in swung[0])  # odd step 5 from even step 4


def test_humanize_zero_leaves_the_table_exact(eng):
    pattern, _ = grooves.compile(grooves.GROOVES["deephouse.shuffle"], 3, P["deephouse"])
    pretend_playing(eng, pattern)
    claps = [(s, o) for s, t, n, v, g, o in bar_events(eng, 0) if t == 3 and s in (4, 12)]
    assert claps == [(4, 0.75), (12, 0.75)]


def test_ghost_cells_play_in_ghost_vel():
    for lane in grooves.LANES.values():
        bars, _ = grooves.lane_bars(lane)
        for b, bar in enumerate(bars):
            ghosts = {s for s, k in grooves.parse_cells(lane.grid[b % len(lane.grid)]) if k == "g"}
            for h in bar:
                if h[0] in ghosts and h[4] >= 0 and not lane.micro or (h[0] in ghosts and lane.micro and
                                                                      lane.micro[h[0]] >= 0):
                    assert grooves.GHOST_VEL[0] <= h[2] <= grooves.GHOST_VEL[1], (lane.name, h)
    a, _ = grooves.lane_bars(grooves.LANES["clap.2_4_ghosted"])
    b, _ = grooves.lane_bars(grooves.LANES["clap.2_4_ghosted"])
    assert a == b  # seeded: the same every time


class TimedPort(FakePort):
    def send(self, msg):
        super().send(msg.copy(time=time.perf_counter()))


@pytest.mark.skipif(not STRICT_TIMING, reason="wall-clock bound; the offsets are pinned exactly above")
def test_note_on_times_follow_the_micro_table():
    port = TimedPort()
    eng, _ = make_engine(port)
    try:
        pattern, _ = grooves.compile(grooves.GROOVES["deephouse.shuffle"], 3, P["deephouse"])
        eng.play(pattern, bpm=120, bars=1)
        eng._thread.join(timeout=8)
        ons = [m for m in port.messages if m.type == "note_on" and m.velocity]
        kick = [m.time for m in ons if m.channel == 0]
        clap = [m.time for m in ons if m.channel == 2 and m.velocity > 60]
        tick = 60 / 120 / 24
        delay = clap[0] - kick[1]  # step 4: the kick on the grid, the clap 0.75 tick behind
        assert abs(delay - 0.75 * tick) < 0.006, delay
    finally:
        eng.shutdown()


# ---- routing ------------------------------------------------------------------------

def test_kick_lane_follows_a_label_and_unplaced_lanes_are_reported(tool):
    call("whiplash_label_tracks", tracks={"9": "kick"})
    out = call("whiplash_play_pattern", groove="deephouse.shuffle")
    assert out["success"] and out["unplaced"] == {"perc": "perc.conga_offbeats"}  # deep house has no perc track
    with tool._lock:
        routed = tool.pattern
    assert 9 in routed.bars and 1 not in routed.bars
    call("whiplash_label_tracks", tracks={"12": "conga"})
    out = call("whiplash_play_pattern", groove="deephouse.shuffle")
    assert "unplaced" not in out


def test_second_perc_lane_needs_a_second_labelled_perc_track():
    groove, base = grooves.GROOVES["techhouse.rolling"], P["techhouse"]
    _, info = grooves.compile(groove, 5, base)
    assert info["unplaced"] == {"perc2": "perc.woodblock"}
    _, info = grooves.compile(groove, 5, base, {8: ("perc", "shaker"), 11: ("perc", "woodblock")})
    assert info["unplaced"] == {} and info["tracks"]["perc2"] == 11


# ---- play_pattern groove / energy --------------------------------------------------

def test_play_pattern_with_a_groove_and_energy(tool):
    out = call("whiplash_play_pattern", groove="house.jack", energy=3)
    assert out["success"] and out["playing"] == "house+jack@3" and out["groove"]["lanes"]["clap"] == "clap.jacked"
    assert out["swing"] == 0.52
    out = call("whiplash_play_pattern", genre="techno", groove="rolling", energy=4)
    assert out["mode"] == "queued" and out["next"] == "techno+rolling@4"
    bad = call("whiplash_play_pattern", genre="techno", groove="house.jack")
    assert not bad["success"] and "belongs to house" in bad["error"]
    bad = call("whiplash_play_pattern", genre="techno", energy=4)
    assert not bad["success"] and "energy needs a groove" in bad["error"]
    bad = call("whiplash_play_pattern", groove="house.jack", energy=7)
    assert not bad["success"]
    assert tool.status()["queued"]["pattern"] == "techno+rolling@4"  # bad calls changed nothing


def test_energy_change_lands_on_the_bar_through_reroute(eng):
    pattern, info = grooves.compile(grooves.GROOVES["techno.rolling"], 2, P["techno"])
    pretend_playing(eng, pattern)
    eng._groove = {"name": "techno.rolling", "energy": 2, "genre": "techno"}
    eng.mutate_humanize(0.5)
    eng.mutate_density([6], -0.5)
    eng.set_mute(8, True)
    bar_events(eng, 0)
    out = eng.set_energy("up")
    assert out["energy"] == 3 and out["lands_at_bar"] == 1
    assert not any(t == 3 for _, t, *_ in bar_events(eng, 0))  # not yet
    ev = bar_events(eng, 1)
    assert any(t == 3 for _, t, *_ in ev)  # the clap comes in at energy 3, on the bar
    assert eng.humanize == 0.5 and eng._density == {6: -0.5} and 8 in eng.muted
    assert eng.status()["groove"]["energy"] == 3
    out = eng.set_energy(5)
    bar_events(eng, 2)
    with pytest.raises(engine.WhiplashError, match="already at energy 5"):
        eng.set_energy("up")
    with pytest.raises(engine.WhiplashError, match="1-5"):
        eng.set_energy(9)
    assert eng.test_port.count("start") == 0 and eng.test_port.count("stop") == 0


def test_energy_on_a_plain_classic_genre_and_refusals(eng):
    pretend_playing(eng, P["deephouse"])
    assert eng.set_energy(1)["groove"] == "deephouse.classic"
    ev = bar_events(eng, 1)
    assert {t for _, t, *_ in ev if t <= 5} == {1, 5}  # kick and the open hat
    other, port = make_engine()
    try:
        pretend_playing(other, P["soul"])
        with pytest.raises(engine.WhiplashError, match=r"soul.classic has one energy level \(3\)"):
            other.set_energy("up")  # v0.9.2 (O3): soul is a one-level classic groove
    finally:
        other.shutdown()


def test_mutate_energy_tool(tool):
    call("whiplash_play_pattern", groove="house.jack")
    out = call("whiplash_mutate", action="energy", amount="down")
    assert out["success"] and out["energy"] == 2 and out["from"] == 3


# ---- write_part(groove) -------------------------------------------------------------

def test_write_part_with_a_lane(eng):
    pretend_playing(eng, P["deephouse"])
    out = eng.write_part(10, groove="hat.offbeat_shuffle")
    assert out["lane"] == "hat.offbeat_shuffle" and out["velocity_curve"] == "deep_hat" and out["micro"] == [0.25]
    hits = [(s, o) for s, t, n, v, g, o in bar_events(eng, 1) if t == 10]
    assert (1, 0.25) in hits and (0, 0.0) in hits
    with pytest.raises(engine.WhiplashError, match="is a clap part; track 6 plays the bass"):
        eng.write_part(6, groove="clap.2_4_ghosted")
    with pytest.raises(engine.WhiplashError, match="drop rhythm"):
        eng.write_part(3, groove="clap.2_4", rhythm="8ths")
    with pytest.raises(engine.WhiplashError, match="closest"):
        eng.write_part(3, groove="clap.2_4_ghostd")


# ---- named fills --------------------------------------------------------------------

def test_named_fills_play_on_their_roles(eng):
    pretend_playing(eng, P["techno"])
    out = eng.schedule_fill(fill="kick.double")
    assert out["tracks"] == [1] and out["fill"] == "kick.double"
    kicks = sorted(s for s, t, *_ in bar_events(eng, 1) if t == 1)
    assert kicks == [0, 4, 8, 12, 14, 15]
    out = eng.schedule_fill(fill="snare.flam_roll")
    assert out["tracks"] == [2]
    rim = [(s, v) for s, t, n, v, *_ in bar_events(eng, 2) if t == 2 and s >= 8]
    assert len(rim) == 16  # 8 flams, a grace and a main hit each
    with pytest.raises(engine.WhiplashError, match="aren't drum tracks"):
        eng.schedule_fill(tracks=[6], fill="snare.roll")
    with pytest.raises(engine.WhiplashError, match="closest"):
        eng.schedule_fill(fill="snare.rol")


def test_tom_run_on_perc_falls_back_to_snare_roll(eng):
    pretend_playing(eng, P["house"])  # no perc track
    out = eng.schedule_fill(fill="perc.tom_run")
    assert out["fill"] == "snare.roll" and "fallback" in out and out["tracks"] == [2]
    other, _ = make_engine()
    try:
        pretend_playing(other, P["techno"])  # perc on track 8
        out = other.schedule_fill(fill="perc.tom_run")
        assert out["tracks"] == [8]
        toms = sorted((s, n) for s, t, n, *_ in bar_events(other, 1) if t == 8 and s >= 10)
        assert {n for _, n in toms} == {60, 57, 53} and min(n for _, n in toms) >= 53
    finally:
        other.shutdown()


def test_groove_fills_on_fill_true(eng):
    pattern, _ = grooves.compile(grooves.GROOVES["deephouse.shuffle"], 3, P["deephouse"])
    pretend_playing(eng, pattern)
    eng._groove = {"name": "deephouse.shuffle", "energy": 3, "genre": "deephouse"}
    out = eng.schedule_fill()
    assert out["fills"] == {"3": "snare.roll"}
    claps = sorted(s for s, t, *_ in bar_events(eng, 1) if t == 3)
    assert claps[-8:] == list(range(8, 16))  # the clap rolls


def test_fill_true_on_a_classic_genre_is_unchanged(eng):
    pretend_playing(eng, P["deephouse"])
    out = eng.schedule_fill()
    assert "fills" not in out and "fill" not in out


# ---- budget ------------------------------------------------------------------------

def test_description_budget_for_v090():
    from test_v053 import _descriptions
    tool_text = {name: len(s["description"]) for name, s in schemas.SCHEMAS.items()}
    # v0.9.3 (O4) raised the caps to 4350 / 10200 / 24650 (test_v053.test_description_size_budget)
    assert sum(tool_text.values()) <= 4350 and max(tool_text.values()) <= 400
    assert _descriptions(schemas.SCHEMAS) <= 10200
    assert len(json.dumps(schemas.SCHEMAS)) <= 24650


def test_an_explicit_key_on_write_part_keeps_its_own_notes(eng):
    pretend_playing(eng, P["techno"])  # F minor
    out = eng.write_part(6, rhythm="offbeat_8ths", key="Am", notes="1 3 5 8")
    assert [h["note"] for h in out["written"][0]["hits"]] == [57, 60, 64, 69] and "snapped" not in out
    assert out["key_lock"].startswith("off: the part is written in its own key")
    out = eng.write_part(6, rhythm="offbeat_8ths", key="current", notes="1 3 5")
    assert out["key_lock"] == "F minor" and "snapped" not in out  # degrees of the playing key are in it


@pytest.mark.skipif(not STRICT_TIMING, reason="wall-clock bound")
def test_bar_line_stays_cheap_with_a_groove_and_a_shell_progression(eng):
    """Clock safety: the bar line does lookups only. A groove with microtiming, a shell progression with a pad and
    named fills cost about what today's beat does (well under a millisecond per bar)."""
    pattern, _ = grooves.compile(grooves.GROOVES["techhouse.rolling"], 5, P["techhouse"])
    pretend_playing(eng, pattern)
    _labelled(eng, {"9": "pad"})
    eng.set_progression(name="deephouse.gospel")
    costs = []
    for bar in range(1, 65):
        if bar % 8 == 0:
            eng.schedule_fill(fill="snare.flam_roll")
        t = time.perf_counter()
        with eng._lock:
            eng._bar_boundary(bar)
        costs.append(time.perf_counter() - t)
    assert statistics.median(costs) < 0.001, statistics.median(costs)
