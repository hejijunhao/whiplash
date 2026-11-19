"""v0.9.2 ontology O3: the other four genres (progressive house, melodic techno, minimal house and techno, tropical
house): records, progressions, lanes, grooves and phrases; the leads on request; soul.classic and breaks.classic;
the O3 aliases and moods; taste thresholds.

Fake and virtual ports only. Nothing here is a hardware result (docs/executing/ontology-v1-spec.md §8)."""
import json
import statistics

import pytest

from whiplash import engine, genres, grooves, harmony, library, patterns, phrases, progressions, taste, tools
from test_live import bar_events, pretend_playing
from test_whiplash import make_engine

P = patterns.PATTERNS
AM = harmony.Key(9, "minor")
CM = harmony.Key(0, "major")
NEW = ("progressivehouse", "melodictechno", "minimal.house", "minimal.techno", "tropicalhouse")


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


def names(prog_name, key):
    entry = progressions.PROGRESSIONS[prog_name]
    prog_key, _ = progressions.key_for(entry, key)
    return [c.name for c in harmony.parse_chords(entry.chords, prog_key)]


# ---- records (spec §2.1) -------------------------------------------------------------------------------------------

SPEC = {  # bpm, swing, key, groove, progression, bass, chords, breakdown, form, unchanged, busy
    "progressivehouse": (124, 0.50, (9, "minor"), "progressivehouse.functional", "progressivehouse.circle",
                         "bass.root_follow", "stab.offbeat", "kick_bass_out", "progressive_journey", 16, 5),
    "melodictechno": (124, 0.50, (9, "minor"), "melodictechno.stripped", "melodictechno.cinematic",
                      "bass.rolling_16", "pad.hold", "kick_bass_out", "melodic_journey", 16, 6),
    "minimal.house": (126, 0.57, (9, "minor"), "minimal.house_shuffle", None, "bass.stab_sparse", "stab.single",
                      "subtract_one", "minimal_long", 64, 4),
    "minimal.techno": (128, 0.53, (9, "minor"), "minimal.techno_kick", None, "bass.offbeat", None, "subtract_one",
                       "minimal_long", 64, 4),
    "tropicalhouse": (108, 0.53, (0, "major"), "tropicalhouse.soft", "tropicalhouse.pop", "bass.round_sub",
                      "pad.hold", "reduce_drums", "tropical_song", 16, 5),
}


@pytest.mark.parametrize("name", NEW)
def test_records_match_the_spec(name):
    r = genres.GENRES[name]
    got = (r.bpm, r.swing, r.key, r.groove, r.progression, r.bass, r.chords, r.breakdown, r.form,
           r.taste["unchanged_bars"], r.taste["busy_drums"])
    assert got == SPEC[name]
    assert name in genres.COMPILED and r.source.startswith("§")
    assert grooves.GROOVES[r.groove].genre == name
    assert grooves.GROOVES[r.groove].swing == r.swing


@pytest.mark.parametrize("name", NEW)
def test_each_genre_compiles_its_groove_and_phrases_in_native_register(name):
    r, p = genres.GENRES[name], P[name]
    assert (p.name, p.bpm, p.swing, p.key, p.family) == (name, r.bpm, r.swing, r.key, name)
    groove, _ = grooves.compile(grooves.GROOVES[r.groove], 3, p)
    drums = grooves.drum_tracks(p)
    assert drums and all(p.bars[t] == groove.bars[t] for t in drums)
    assert len(drums) <= r.taste["busy_drums"]
    assert harmony.is_phrase(p.bars[6])  # the bass follows the chords
    chord_tracks = [t for t in (7, 8) if t in p.bars and harmony.is_phrase(p.bars[t])]
    assert bool(chord_tracks) == (r.chords is not None)
    for track, bars in p.bars.items():
        if patterns.is_melodic(bars):
            notes = [int(n) for n in patterns.notes_of(bars)]
            assert statistics.median(notes) >= 53, (name, track)
            assert patterns.NOTE_MIN <= min(notes) and max(notes) <= patterns.NOTE_MAX
        else:
            assert set(patterns.notes_of(bars)) == {patterns.DRUM}  # drums never pitched


def test_progressive_house_plays_off_beat_stabs_over_the_circle_and_a_root_bass():
    p = P["progressivehouse"]
    chords = harmony.parse_chords("i7 iv7 VIIsus4 IIImaj7", AM)
    for bar in range(4):
        chord = chords[bar // 2]
        bass = p.bars[6][bar]
        assert [s for s, *_ in bass] == [0, 8] and {n % 12 for _, n, *_ in bass} == {chord.root}
        for track in (7, 8):
            hits = p.bars[track][bar]
            assert [s for s, *_ in hits] == [2, 6, 10, 14]
            assert {n % 12 for _, n, *_ in hits} <= {(chord.root + x) % 12 for x in chord.shape}


def test_melodic_techno_rolls_16ths_and_holds_a_pad():
    p = P["melodictechno"]
    kick_steps = {0, 4, 8, 12}
    for bar in p.bars[6]:
        steps = [s for s, *_ in bar]
        assert len(steps) == 12 and not kick_steps & set(steps)  # 16ths off the kick steps
    for bar in p.bars[7]:
        ((step, _, vel, gate),) = bar
        assert (step, vel, gate) == (0, harmony.PAD_VELOCITY, harmony.PAD_GATE)  # pad.hold = the existing pad line
    assert {s for bar in p.bars[8] for s, *_ in bar} == set(range(16))  # the shaker


def test_minimal_is_space_four_elements_and_little_harmony():
    house, techno = P["minimal.house"], P["minimal.techno"]
    assert [len(b) for b in house.bars[3]] == [0, 2, 0, 2]  # the clap every other bar
    assert [len(b) for b in house.bars[6]] == [1, 2, 1, 2]  # one or two short bass notes a bar
    assert [[s for s, *_ in b] for b in house.bars[7][:3]] == [[6], [6], [6]]  # a single stab on step 6
    assert 7 not in techno.bars  # minimal techno has no chord track
    assert len(grooves.drum_tracks(house)) == len(grooves.drum_tracks(techno)) == 4


def test_tropical_house_is_soft_and_bright_in_c_major():
    p = P["tropicalhouse"]
    assert {h[2] for b in p.bars[1] for h in b} == {96}  # the soft kick
    assert p.roles[4] == "closed hat" and len(p.bars[4][0]) == 16  # shaker 16ths on the closed-hat track
    bass_roots = [{n % 12 for _, n, *_ in b} for b in p.bars[6]]
    assert bass_roots == [{0}, {0}, {7}, {7}]  # Cmaj7 then G, two bars each
    assert [s for s, *_ in p.bars[6][0]] == [0, 8]  # density 0.67 keeps 1 and 3


# ---- progressions (spec §3.2.1) ------------------------------------------------------------------------------------

O3_PROGS = {
    "progressivehouse.circle": (AM, ["Am7", "Dm7", "Gsus4", "Cmaj7"]),
    "progressivehouse.long_two": (AM, ["Am7", "Dm7"]),
    "progressivehouse.phrygian_turn": (AM, ["Am", "A#", "Am", "E7"]),  # B flat, named as house.piano_stab names it
    "progressivehouse.descending": (AM, ["Am9"]),
    "melodictechno.cinematic": (AM, ["Amadd9", "Fmaj7", "C", "Gsus2"]),
    "melodictechno.held_vamp": (AM, ["Am9", "Fmaj7"]),
    "minimal.stab_m7": (AM, ["Am7"]),
    "minimal.stab_sus2": (AM, ["Asus2"]),
    "minimal.fifth": (AM, ["A5"]),
    "tropicalhouse.pop": (CM, ["Cmaj7", "G", "Am7", "Fmaj7"]),
    "tropicalhouse.pop_minor": (CM, ["Am7", "Fmaj7", "Cmaj7", "G"]),
}


@pytest.mark.parametrize("name", sorted(O3_PROGS))
def test_o3_progressions_spell_as_the_spec(name):
    key, want = O3_PROGS[name]
    assert names(name, key) == want
    entry = progressions.PROGRESSIONS[name]
    assert entry.tags - progressions.GENRE_TAGS - {"progressivehouse"} <= progressions.TAGS
    assert entry.source and -2 <= entry.brightness <= 2 and 0 <= entry.tension <= 3
    assert library.resolve("progression", name) is entry


def test_tropical_pop_in_a_minor_plays_the_relative_major():
    assert names("tropicalhouse.pop", AM) == ["Cmaj7", "G", "Am7", "Fmaj7"]


def test_descending_names_its_bass_and_walks_a_g_f_e():
    entry = progressions.PROGRESSIONS["progressivehouse.descending"]
    assert entry.bass == "bass.descending_walk" and entry.bass in phrases.PHRASES
    prog = phrases.fallback(entry.name, AM)
    bars, _ = phrases.build(phrases.PHRASES[entry.bass], prog)
    assert [patterns.note_name(int(b[0][1]))[:-1] for b in bars] == ["A", "G", "F", "E"]
    assert all(len(b) == 1 and b[0][3] == 16 for b in bars)  # one held note a bar


def test_set_progression_by_name_recommends_the_written_bass(eng):
    pretend_playing(eng, P["progressivehouse"])
    out = eng.set_progression(name="progressivehouse.descending")
    assert out["library"]["bass"] == "bass.descending_walk" and "phrase: 'bass.descending_walk'" in out["bass_hint"]
    out = eng.write_part(6, phrase="bass.descending_walk")
    played = run(eng, 1, 4)
    walk = [patterns.note_name(n)[:-1] for b in range(1, 5) for s, n in track_notes(played[b], 6)]
    assert sorted(walk) == sorted(["A", "G", "F", "E"])  # one note a bar; which bar starts depends on the loop


def test_darker_swaps_within_the_new_genres():
    pick = progressions.swap(progressions.PROGRESSIONS["progressivehouse.circle"], True)
    assert pick.genre == "progressivehouse" and pick.brightness == -1
    assert progressions.swap(progressions.PROGRESSIONS["tropicalhouse.pop"], True).name == "tropicalhouse.pop_minor"
    assert progressions.swap(progressions.PROGRESSIONS["tropicalhouse.pop"], False) is None  # the brightest


# ---- lanes and grooves (spec §4.2) ---------------------------------------------------------------------------------

def test_poly3_hits_every_third_cell_over_the_loop():
    bars, _ = grooves.lane_bars(grooves.LANES["perc.poly3"])
    cells = [b * 16 + s for b, bar in enumerate(bars) for s, *_ in bar]
    assert cells[:22] == list(range(0, 64, 3))  # 0, 3, ..., 63: it resets every 4 bars
    assert all(h[4] == 0.25 for bar in bars for h in bar)


def test_o3_lanes():
    lane = grooves.LANES
    assert [len(b) for b in grooves.lane_bars(lane["clap.every_other_bar"])[0]] == [0, 2, 0, 2]
    assert [s for s, *_ in grooves.lane_bars(lane["rim.on_3"])[0][0]] == [8]
    rim, _ = grooves.lane_bars(lane["rim.sparse_2_4"])
    assert [(s, v, o) for s, _, v, _, o in rim[0]] == [(4, 56, 0.5), (12, 56, 0.5)]
    bongo, _ = grooves.lane_bars(lane["perc.bongo"])
    assert [s for s, *_ in bongo[0]] == [3, 7, 10, 14]
    shaker, _ = grooves.lane_bars(lane["hat.shaker_16"])
    assert lane["hat.shaker_16"].role == "closed hat" and len(shaker[0]) == 16
    assert all(grooves.GHOST_VEL[0] <= v <= grooves.GHOST_VEL[1] for s, _, v, *_ in shaker[0] if s % 2)


@pytest.mark.parametrize("name", [genres.GENRES[n].groove for n in NEW])
def test_new_grooves_have_five_levels_get_busier_and_stay_capped(name):
    groove = grooves.GROOVES[name]
    assert sorted(groove.levels) == [1, 2, 3, 4, 5] and not groove.classic
    base = P[groove.genre]
    hits = grooves.hits_per_level(groove, base)
    assert all(hits[e] <= hits[e + 1] for e in range(1, 5)), hits
    cap = genres.GENRES[groove.genre].taste["busy_drums"]
    for energy, slots in groove.levels.items():
        assert len(slots) <= cap and all(ref in grooves.LANES for ref in slots.values())
        _, info = grooves.compile(groove, energy, base)
        assert not info["unplaced"], (name, energy)
    for role, fill in groove.fills.items():
        assert role in grooves.DRUM_ROLES and fill in grooves.FILLS
    assert any(any(lane.micro) for lane in (grooves.LANES[r] for r in groove.levels[3].values()))  # microtiming on


@pytest.mark.parametrize("genre", ["soul", "breaks"])
def test_soul_and_breaks_classic_are_todays_pattern_with_one_level(genre, eng):
    groove = library.resolve("groove", f"{genre}.A")
    assert groove.name == f"{genre}.classic" and sorted(groove.levels) == [3]
    pattern, info = grooves.compile(groove, 3, P[genre])
    assert pattern is P[genre]
    with pytest.raises(grooves.GrooveError, match="one energy level"):
        grooves.compile(groove, 4, P[genre])
    pretend_playing(eng, P[genre])
    before = run(eng, 0, 3)
    with eng._lock:
        status = eng.groove_status()
    assert status["name"] == f"{genre}.classic" and status["energy"] == 3
    with pytest.raises(engine.WhiplashError, match=rf"{genre}.classic has one energy level \(3\)"):
        eng.set_energy("up")
    assert eng._energy_next is None
    assert run(eng, 0, 3) == before


def test_energy_changes_on_a_plain_compiled_genre(eng):
    pretend_playing(eng, P["minimal.techno"])
    out = eng.set_energy(1)
    assert out["groove"] == "minimal.techno_kick"
    ev = bar_events(eng, 1)
    assert {t for _, t, *_ in ev if t <= 5 or t == 8} == {1, 5}  # kick and the open hat


def test_play_pattern_groove_and_energy_for_a_new_genre(tool):
    out = call("whiplash_play_pattern", groove="tropical soft", energy=5)
    assert out["success"] and out["groove"]["name"] == "tropicalhouse.soft" and out["groove"]["energy"] == 5
    assert out["playing"].startswith("tropicalhouse") and not out.get("unplaced")
    tool.stop()
    out = call("whiplash_play_pattern", genre="soul", groove="A", energy=4)
    assert not out["success"] and "one energy level" in out["error"]


# ---- phrases (spec §5.2.1) -----------------------------------------------------------------------------------------

O3_PHRASES = ("bass.root_follow", "bass.rolling_16", "bass.stab_sparse", "bass.round_sub", "bass.descending_walk",
              "bass.walking", "stab.single", "pad.hold", "arp.chord_up", "arp.chord_updown", "arp.chord_seeded",
              "lead.stutter", "lead.pentatonic_hook", "melody.motif")


def test_the_o3_phrases_exist_and_leads_are_on_request():
    for name in O3_PHRASES:
        entry = library.resolve("phrase", name)
        assert entry.name == name and entry.source and entry.about
    leads = {n for n, p in phrases.PHRASES.items() if p.role == "lead"}
    assert leads == {"arp.chord_up", "arp.chord_updown", "arp.chord_seeded", "lead.stutter", "lead.pentatonic_hook",
                     "melody.motif"}
    assert all(phrases.PHRASES[n].on_request for n in leads)
    defaults = {g.bass for g in genres.GENRES.values()} | {g.chords for g in genres.GENRES.values()}
    defaults |= {v for g in genres.GENRES.values() for k, v in g.recommends.items() if k in ("bass", "chords")}
    assert not leads & defaults


@pytest.mark.parametrize("name", ["arp.chord_seeded", "lead.pentatonic_hook", "melody.motif", "stab.single",
                                  "bass.walking"])
def test_seeded_o3_phrases_are_deterministic_and_vary_with_the_seed(name):
    entry = phrases.PHRASES[name]
    prog = phrases.fallback("deephouse.gospel", AM)
    a = phrases.shape(entry, seed="phil")
    assert phrases.shape(entry, seed="phil") == a
    assert any(phrases.shape(entry, seed=s) != a for s in range(1, 12))
    bars, _ = phrases.build(entry, prog, seed="phil")
    assert bars == phrases.build(entry, prog, seed="phil")[0]


def test_motif_repeats_sequences_up_a_step_and_answers_on_the_root():
    entry = phrases.PHRASES["melody.motif"]
    for seed in range(20):
        bars = phrases.shape(entry, seed=seed)
        tones = [[(t, o) for _, t, o, *_ in bar] for bar in bars]
        assert tones[0] == tones[1] and tones[0][0] == ("R", 0)
        assert tones[3][-1] == ("R", 0)
        assert tones[2] != tones[0]  # sequenced
    one = phrases.fallback(None, AM)  # the tonic chord: steps are scale steps from A
    bars, _ = phrases.build(entry, one, seed=3)
    first, third = [int(h[1]) for h in bars[0]], [int(h[1]) for h in bars[2]]
    assert all(harmony.scale_step(a, 1, AM) == b for a, b in zip(first, third))


def test_hook_repeats_every_two_bars():
    bars = phrases.shape(phrases.PHRASES["lead.pentatonic_hook"], seed=5)
    assert bars[0] == bars[2] and bars[1] == bars[3] and bars[0] != bars[1]
    tones = {t for bar in bars for _, t, *_ in bar}
    assert tones <= {"R", "3", "5", "9", "oct"}


def test_arp_up_climbs_the_chord_and_stutter_is_short():
    prog = phrases.fallback(None, AM)
    bars, _ = phrases.build(phrases.PHRASES["arp.chord_up"], prog)
    first = [int(h[1]) for h in bars[0][:4]]
    assert first == sorted(first) and {n % 12 for n in first} == {9, 0, 4} and first[3] == first[0] + 12
    stutter, _ = phrases.build(phrases.PHRASES["lead.stutter"], prog)
    assert [s for s, *_ in stutter[0]] == [0, 1, 3, 4, 5, 7, 8, 9, 11, 12, 13, 15]
    assert {h[3] for bar in stutter for h in bar} == {0.5}


def test_stab_single_moves_only_in_bar_four():
    for seed in range(10):
        bars = phrases.shape(phrases.PHRASES["stab.single"], seed=seed)
        assert [[s for s, *_ in b] for b in bars[:3]] == [[6]] * 3
        assert len(bars[3]) == 1 and bars[3][0][0] in phrases.SHIFT_STEPS


def test_phrase_genre_picks_the_new_records_phrases_and_refuses_leads(eng):
    pretend_playing(eng, P["melodictechno"])
    assert eng.write_part(6, phrase="genre")["phrase"] == "bass.rolling_16"
    assert eng.write_part(7, phrase="genre")["phrase"] == "pad.hold"
    eng.label_tracks({"9": "lead synth"})
    with pytest.raises(engine.WhiplashError, match="leads stay model-written.*lead.stutter"):
        eng.write_part(9, phrase="genre")
    eng.stop()
    pretend_playing(eng, P["minimal.techno"])
    eng.label_tracks({"10": "stab"})
    with pytest.raises(engine.WhiplashError, match="minimal.techno has no chord phrase"):
        eng.write_part(10, phrase="genre")


def test_an_arp_on_a_lead_follows_the_chords(eng):
    pretend_playing(eng, P["tropicalhouse"])
    eng.label_tracks({"9": "lead pluck"})
    out = eng.write_part(9, phrase="arp.chord_up")
    assert out["phrase"] == "arp.chord_up"
    eng.set_progression(name="tropicalhouse.pop_minor")
    played = run(eng, 1, 8)
    chords = harmony.parse_chords("vi7 IVmaj7 Imaj7 V", CM)
    for b in range(1, 9):
        chord = chords[((b - 1) // 2) % 4]
        notes = {n % 12 for _, n in track_notes(played[b], 9)}
        assert notes and notes <= {(chord.root + x) % 12 for x in chord.shape}, b


def test_new_genre_phrases_follow_a_key_change(eng):
    pretend_playing(eng, P["progressivehouse"])
    eng._warm_fallback(P["progressivehouse"])
    with eng._lock:
        eng._refresh_harmony()
    before = [n for _, n in track_notes(bar_events(eng, 0), 6)]
    out = eng.set_progression(key="Fm")
    assert out["lands_at_bar"] == 1
    after = [n for _, n in track_notes(run(eng, 1, 1)[1], 6)]
    assert after and {n % 12 for n in after} == {5} and {n % 12 for n in before} == {9}  # F minor's tonic, was A


@pytest.mark.parametrize("genre", ["progressive", "melodic techno", "minimal", "minimal techno", "tropical"])
def test_play_pattern_alone_plays_the_records_lines(tool, genre):
    out = call("whiplash_play_pattern", genre=genre)
    pattern = patterns.resolve(genre)
    assert out["success"] and out["playing"] == pattern.name and out["bpm"] == pattern.bpm
    assert out["tracks"]["6"]["progression"] == "phrase"


# ---- aliases, moods, library -------------------------------------------------------------------------------------

@pytest.mark.parametrize("word, genre", [
    ("progressive", "progressivehouse"), ("progressive house", "progressivehouse"), ("prog house", "progressivehouse"),
    ("melodic techno", "melodictechno"), ("tropical", "tropicalhouse"), ("tropical house", "tropicalhouse"),
    ("minimal", "minimal.house"), ("minimal house", "minimal.house"), ("minimal techno", "minimal.techno"),
    ("minimal.techno", "minimal.techno"), ("house", "deephouse"), ("chicago", "house")])
def test_o3_genre_words(word, genre):
    assert patterns.resolve(word).name == genre


@pytest.mark.parametrize("mood, genre", [
    ("journey", "progressivehouse"), ("cinematic", "melodictechno"), ("emotional", "melodictechno"),
    ("sunny", "tropicalhouse"), ("summer", "tropicalhouse"), ("beach", "tropicalhouse"), ("sparse", "minimal.house"),
    ("happy", "breaks"), ("peak time", "techno")])
def test_o3_moods(mood, genre):
    assert patterns.resolve(None, mood).name == genre


@pytest.mark.parametrize("kind, text, name", [
    ("groove", "minimal house shuffle", "minimal.house_shuffle"), ("groove", "minimal shuffle", "minimal.house_shuffle"),
    ("groove", "minimal techno", "minimal.techno_kick"), ("groove", "progressive house", "progressivehouse.functional"),
    ("groove", "soul.A", "soul.classic"), ("progression", "prog circle", "progressivehouse.circle"),
    ("progression", "minimal fifth", "minimal.fifth"), ("phrase", "pad hold", "pad.hold"),
    ("genre", "tropical", "tropicalhouse"), ("genre", "minimal techno", "minimal.techno")])
def test_library_reads_the_new_names(kind, text, name):
    assert library.resolve(kind, text).name == name


def test_list_library_by_new_genre():
    def listed(kind, genre):
        return [e["name"] for e in library.entries(kind, genre=genre)["entries"]]
    assert listed("groove", "minimal techno") == ["minimal.techno_kick"]
    assert listed("progression", "minimal techno") == ["minimal.fifth", "minimal.stab_m7", "minimal.stab_sus2"]
    assert "bass.offbeat" in listed("phrase", "minimal techno")
    assert listed("genre", "tropical") == ["tropicalhouse"]
    out = library.entries("progression", genre="tropical")["entries"][0]
    assert out["in_key"] == "C major" and out["names"] == ["Cmaj7", "G", "Am7", "Fmaj7"]


# ---- taste (spec §7.2) ---------------------------------------------------------------------------------------------

ROLES = {1: "kick", 3: "clap", 4: "closed hat", 6: "bass"}


def _digest(bars):
    events = {0: [(1, 60, 100, 1, 0.0)], 4: [(3, 60, 100, 1, 0.0)], 8: [(1, 60, 100, 1, 0.0)]}
    return [(b, b * 2.0, events, None, "Am", frozenset(), False) for b in range(bars)]


@pytest.mark.parametrize("genre, limit", [("progressivehouse", 16), ("melodictechno", 16), ("tropicalhouse", 16),
                                          ("minimal.house", 64), ("minimal.techno", 64)])
def test_new_thresholds_fire_at_the_boundary(genre, limit):
    for bars, fires in ((limit - 1, False), (limit, True)):
        m = taste.metrics(_digest(bars), [], [], ROLES)
        hint = taste.hints(m, genre).get("repetition")
        assert (hint is not None) is fires
        if hint:
            assert taste.name_of(genre) in hint and taste.SUGGEST[genre]["lane"] in hint


def test_minimal_flags_five_drum_elements():
    events = {s: [(t, 60, 100, 1, 0.0) for t in (1, 2, 3, 4, 5)] for s in (0, 8)}
    roles = {1: "kick", 2: "rim", 3: "clap", 4: "closed hat", 5: "open hat"}
    m = taste.metrics([(b, b * 2.0, events, None, None, frozenset(), False) for b in range(8)], [], [], roles)
    assert "holds 4" in taste.hints(m, "minimal.house")["busy"]
    assert "busy" not in taste.hints(m, "progressivehouse")


# ---- equivalence ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("genre", ["deephouse", "techhouse", "techno", "soul", "breaks", "house"])
def test_old_genres_play_as_before(genre, eng):
    """The registered tables are unchanged: hand-written genres are still today's tables, classic house still its
    O1b compile (genres.compile now passes the whole layout, which changes nothing for house)."""
    p = P[genre]
    if genre == "house":
        r = genres.GENRES["house"]
        base = patterns.Pattern("house", r.bpm, r.swing, {t: v for t, v in r.roles.items() if t in (6, 7, 8)},
                                genres.melodic_lines(r), key=r.key)
        old, _ = grooves.compile(grooves.GROOVES[r.groove], 3, base, name="house")
        assert {t: b for t, b in p.bars.items()} == patterns.register(old).bars
    else:
        assert p == patterns.register(patterns.RAW[genre])
    pretend_playing(eng, p)
    played = run(eng, 0, 3)
    for b in range(4):
        for track, bars in p.bars.items():
            assert [(s, n) for s, n in track_notes(played[b], track)] == [(s, int(h[1])) for h in bars[b]
                                                                         for s in (h[0],)] or track > 8


def test_o1b_phrases_build_the_same_lines_with_tones_counted_across_the_loop():
    # Every O1b phrase holds a whole number of tone cycles per bar, so counting tones across the loop (O3) changes
    # nothing: the line matches a per-bar count, bar for bar.
    for name in ("bass.rolling_deep", "bass.octave_pump", "bass.bouncy", "bass.offbeat", "stab.offbeat"):
        entry = phrases.PHRASES[name]
        for bar in parts_cells(entry):
            assert len(bar) % len(entry.tones) == 0 and len(bar) % len(entry.velocity) == 0
            assert len(bar) % len(entry.length) == 0


def parts_cells(entry):
    from whiplash import parts
    return [parts.parse_grid_bar(g) for g in entry.grid]


def test_mix_auto_picks_the_new_genres_presets():
    from whiplash import mixer
    for name in NEW:
        assert mixer.preset("auto", name) == (name, mixer.PRESETS[name])
    assert mixer.preset("tropical", None)[0] == "tropicalhouse" and mixer.preset("minimal", None)[0] == "minimal.house"
    assert mixer.PRESETS["tropicalhouse"]["kick"] < mixer.PRESETS["house"]["kick"]  # soft drums
