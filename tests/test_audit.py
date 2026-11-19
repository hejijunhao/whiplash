"""Post-O5 ontology audit (docs/executing/ontology-v1-audit.md): fixes and the frozen demo-safe pins."""
import hashlib
import json

import pytest

from test_live import bar_events, pretend_playing
from test_whiplash import make_engine
from whiplash import grooves, library, mutate, patterns, tools

P = patterns.PATTERNS
OLD = ("deephouse", "techhouse", "techno", "soul", "breaks")


def call(name, **params):
    return json.loads(tools.HANDLERS[name](params))


@pytest.fixture
def tool(monkeypatch):
    e, port = make_engine()
    monkeypatch.setattr(tools, "ENGINE", e)
    e.test_port = port
    yield e
    e.shutdown()


# ---- audit A1: demo-safe equivalence against a frozen pre-v0.9 snapshot -----------------------------------------
# The older equivalence tests compare the live table with itself (`compiled is P[genre]`), so an edit to
# patterns.py would pass them. These digests were taken on main at 3f4f883 (v0.8.0 + the visualiser timeline, the
# commit the ontology spec was cut from) with this same code, and match today's output.

FROZEN_BARS = {"deephouse": "8545d308812187b7", "techhouse": "f75039252af2e694", "techno": "be8dc832fe9e8dad",
               "soul": "e16825d5a6ad4b55", "breaks": "d2291299cfc9d032"}
FROZEN_TOOL = {("deephouse", ""): "bb1ef1d3b3f6ef05", ("deephouse", "Fm"): "ee0b07b4e667dc09",
               ("techhouse", ""): "f7858d01484b3771", ("techhouse", "Fm"): "6a6cb3b7fb4a75b9",
               ("techno", ""): "3f937bcd2e363819", ("techno", "Fm"): "3f937bcd2e363819",
               ("soul", ""): "2b7162fecf505f1d", ("soul", "Fm"): "0ab75d1b90098453",
               ("breaks", ""): "e74418119b8725c1", ("breaks", "Fm"): "630c5b32d326fb3e"}


def _bars_digest(pattern, bars=8):
    eng, _ = make_engine()
    try:
        pretend_playing(eng, pattern)
        h = hashlib.sha256()
        h.update(repr((pattern.bpm, pattern.swing)).encode())
        for bar in range(bars):
            h.update(repr(bar_events(eng, bar)).encode())
        return h.hexdigest()[:16]
    finally:
        eng.shutdown()


@pytest.mark.parametrize("genre", OLD)
def test_old_genres_play_the_pre_v09_bars(genre):
    assert _bars_digest(P[genre]) == FROZEN_BARS[genre]


@pytest.mark.parametrize("genre", OLD)
def test_classic_groove_at_energy_3_plays_the_pre_v09_bars(genre):
    groove = library.resolve("groove", f"{genre}.classic")
    compiled, _ = grooves.compile(groove, 3, P[genre])
    assert _bars_digest(compiled) == FROZEN_BARS[genre]
    if f"{genre}.A" in grooves.GROOVES[groove.name].aliases:
        assert library.resolve("groove", f"{genre}.A").name == groove.name


@pytest.mark.parametrize("genre, key", sorted(FROZEN_TOOL))
def test_play_pattern_tool_path_is_the_pre_v09_pattern(tool, genre, key):
    args = {"genre": genre, **({"key": key} if key else {})}
    out = call("whiplash_play_pattern", **args)
    assert "groove" not in out
    with tool._lock:
        w = mutate.working(tool.pattern)
        digest = hashlib.sha256(repr((tool.bpm, tool.swing, sorted(w.items()))).encode()).hexdigest()[:16]
    assert digest == FROZEN_TOOL[(genre, key)]


# ---- shared helpers for the engine checks below ---------------------------------------------------------------------

from whiplash import engine, form, harmony, taste  # noqa: E402


@pytest.fixture
def eng():
    e, port = make_engine()
    e.test_port = port
    yield e
    e.shutdown()


def playing(eng, genre="deephouse"):
    pretend_playing(eng, P[genre])
    bar_events(eng, 0)
    return eng


# ---- audit A2: a bare groove "A" from a cold start (spec §4.2: "A bare groove: 'A' takes the genre's classic") -----

def test_bare_groove_a_works_from_a_cold_start(tool):
    hint = call("whiplash_play_pattern", energy=4)
    assert not hint["success"] and "groove: 'A'" in hint["error"]
    out = call("whiplash_play_pattern", groove="A")  # the energy hint's own advice works with nothing playing
    assert out["success"], out
    assert out["groove"]["name"] == "deephouse.classic"
    tool.stop()
    out = call("whiplash_play_pattern", genre="techno", groove="A")
    assert out["success"] and out["groove"]["name"] == "techno.classic"


# ---- audit A3: mutate energy reports pushed_downbeat_clamped like play_pattern does (spec §4.2) ----------------------

def test_energy_change_reports_a_clamped_downbeat(tool):
    entry = grooves.GROOVES["techhouse.rolling"]
    clamped = {lv for lv in entry.levels if grooves.compile(entry, lv, P["techhouse"])[1]["clamped"]}
    assert clamped, "techhouse.rolling pushes a hat on step 0 at some level"
    start = 1 if 1 not in clamped else 2
    target = min(clamped - {start})
    pattern, _ = grooves.compile(entry, start, P["techhouse"])
    out = call("whiplash_play_pattern", groove="techhouse.rolling", energy=start)
    assert out["success"]
    out = call("whiplash_mutate", action="energy", amount=target)
    assert out["success"] and out["pushed_downbeat_clamped"]


# ---- audit A4: an explicit flat numeral spells flat (spec §1.1: "bII in A minor is B flat") -------------------------

def test_flat_numerals_spell_flat_and_sound_the_same():
    am = harmony.Key(9, "minor")
    chord = harmony.parse_chord("bII", am)
    assert chord.name == "Bb" and chord.root == 10
    assert harmony.parse_chord("#iii7", am).name == "C#m7"  # a sharp numeral stays sharp
    assert harmony.parse_chord("VI", am).name == "F"  # no accidental: the key's spelling, as before
    names = [c.name for c in harmony.parse_chords(library.resolve("progression", "house.piano_stab").chords, am)]
    assert names == ["Am", "C", "Bb", "Am"]


# ---- audit A5: the unknown-phrase hint lists the track role's phrases (spec §5.3) ------------------------------------

def test_unknown_phrase_hint_names_the_role_tag(eng):
    playing(eng)
    with pytest.raises(engine.WhiplashError, match=r"kind: 'phrase', tag: 'bass'"):
        eng.write_part(6, phrase="bass.nope")
    listed = json.loads(tools.HANDLERS["whiplash_list_library"]({"kind": "phrase", "tag": "bass"}))
    assert listed["entries"] and all(e["name"].startswith("bass.") for e in listed["entries"])


# ---- audit B1: a short section warns, never refuses (spec §6.2, Q-A4) ------------------------------------------------

@pytest.mark.parametrize("kwargs", [dict(move="drop", bars=4), dict(move="build", bars=2), dict(move="build", bars=3),
                                    dict(form="intro 4, drop 4"), dict(form="groove 4"), dict(form="groove 2, build 1")])
def test_short_sections_play_with_a_warning(eng, kwargs):
    playing(eng, "techhouse")
    out = eng.arrange(**kwargs)
    assert any("DJs count in 8" in w for w in out["warnings"])
    for sec in out["sections"]:
        for bar in sec.get("fills_at_bars", []):
            assert sec["starts_at_bar"] <= bar < sec["starts_at_bar"] + sec["bars"]


def test_a_short_section_fills_on_its_last_bar_and_given_keys_are_still_checked(eng):
    playing(eng, "techhouse")
    out = eng.arrange(form="drop 4")
    assert out["sections"][0]["fills_at_bars"] == [4]
    out = eng.arrange(move="build", bars=2)
    assert "enter" not in out["sections"][0]  # hats play from the start of so short a build
    with pytest.raises(engine.WhiplashError, match="fill_every"):
        eng.arrange(sections=[{"type": "drop", "bars": 4, "fill_every": 8}])  # given by the caller: refused
    secs, warnings = form.expand([{"type": "build", "bars": 8}])
    assert secs[0]["enter"] == {"hats": -4} and secs[0].get("fill_every") is None and not warnings  # unchanged at 8


# ---- audit B2: hints that fire together each reach taste_hint (spec §7.3, O5 plan §3.6) -----------------------------

def test_two_hints_firing_at_once_ride_two_results(tool):
    pretend_playing(tool, P["techhouse"])
    for b in range(0, 10):
        bar_events(tool, b)
    tool.record_listen({"playing": True, "bars": 2, "silent": False,
                        "loudness": {"clipping": True, "lufs_ish": -6.0, "peak_dbfs": 0.0},
                        "bands": {"low": {"pct": 40.0, "db": -4.0}},
                        "low_end": {"kick_over_rest_db": 3.0, "masking": False}})
    bar_events(tool, 10)
    fired, _ = tool.taste_hints()
    assert {"repetition", "clipping"} <= set(fired)
    first = call("whiplash_mutate", action="humanize", amount=0.1)["taste_hint"]
    second = call("whiplash_mutate", action="humanize", amount=0.2)
    assert second.get("taste_hint") and second["taste_hint"] != first
    assert "taste_hint" not in call("whiplash_mutate", action="humanize", amount=0.3)


# ---- audit B3: an arrangement's enter/exit and its end count as change (spec §7.2, Q-T4) ----------------------------

def test_enter_and_exit_count_as_change(tool):
    pretend_playing(tool, P["techhouse"])
    bar_events(tool, 0)
    tool.arrange(sections=[{"name": "a", "bars": 32, "enter": {"hats": 9}}])
    for b in range(1, 15):
        bar_events(tool, b)
    review = call("whiplash_status", review=8)
    assert review["unchanged_for_bars"] == 5
    assert any(c["bar"] == 9 and c["what"].endswith(" in") for c in review["changed"])


def test_mute_changes_are_pure_and_named():
    digest = [(b, 0.0, {}, "a", None, frozenset(m), False) for b, m in ((1, {4, 5}), (2, {4, 5}), (3, {5}), (4, {5, 8}))]
    assert taste.mute_changes(digest) == [(3, "track 4 in"), (4, "track 8 out")]
    assert {3, 4} <= taste.change_bars(digest, [], [])


def test_then_continue_counts_its_end_as_change(tool):
    pretend_playing(tool, P["techhouse"])
    bar_events(tool, 0)
    tool.arrange(sections=[{"name": "a", "bars": 4}], then="continue")
    for b in range(1, 12):
        bar_events(tool, b)
    review = call("whiplash_status", review=8)
    assert {"bar": 5, "what": "the arrangement ended", "by": "you"} in review["changed"]
    assert review["unchanged_for_bars"] == 6


# ---- audit B4: continue (or clear) reopens what the energy filter closed (spec §6.2, O4 plan §2) -------------------

def test_continue_reopens_the_energy_filter(eng):
    playing(eng, "progressivehouse")
    out = eng.arrange(form="groove 8, outro 8", energy_filter=True, then="continue")
    assert "reopens to 127" in out["filter_note"]
    for b in range(1, 17):
        bar_events(eng, b)
    music = sorted(t for t, ramp in eng._ramps.items() if t[1] == engine.FILTER_CC)
    assert music, "the outro closes the music cutoffs"
    with eng._lock:  # where the closing ramps end (no clock ticks in this harness)
        for track, cc in music:
            eng._cc_values[(track - 1, cc)] = form.ENERGY_FILTER[1]
    bar_events(eng, 17)  # the arrangement ends, the beat goes on
    assert eng._arr is None
    for key in music:
        ramp = eng._ramps[key]
        assert (ramp.start, ramp.end, ramp.owner) == (form.ENERGY_FILTER[1], 127, engine.REOPEN)


def test_without_the_energy_filter_continue_leaves_cutoffs_alone(eng):
    playing(eng, "techhouse")
    eng.arrange(form="groove 8, outro 8", then="continue")
    for b in range(1, 18):
        bar_events(eng, b)
    assert not [k for k, r in eng._ramps.items() if r.owner == engine.REOPEN]


# ---- audit B5: a replacing move withdraws the old section's last-bar drop and fill (spec §6.3, Q-A2) ----------------

def test_a_replacing_move_withdraws_the_old_builds_last_bar(eng):
    playing(eng, "techhouse")
    out = eng.arrange(preset="club")
    build = next(s for s in out["sections"] if s["name"].startswith("build"))
    last = build["starts_at_bar"] + build["bars"] - 1
    for b in range(1, build["starts_at_bar"] + 2):
        bar_events(eng, b)
    assert any(span == (last, last + 1) for span in eng._drops.values())
    with eng._lock:
        eng._drops[12] = (last, last + 1)  # a user's own drop on that bar stays
    eng.arrange(move="breakdown", bars=8)
    assert eng._drops == {12: (last, last + 1)}
    assert not eng._fills.get(last)
    eng.undo()  # the old arrangement comes back with its build's last bar
    bar_events(eng, build["starts_at_bar"] + 2)
    assert any(span == (last, last + 1) for t, span in eng._drops.items() if t != 12)


# ---- audit B6: the change log reads like the spec's examples (spec §7.2) --------------------------------------------

def test_change_summaries_use_the_spec_words():
    assert tools.change_summary({"action": "energy", "amount": "up"}, {"from": 3, "energy": 4}) == "energy 3 -> 4"
    assert tools.change_summary({"track": 6, "phrase": "bass.octave_pump"}) == "6 bass.octave_pump"
    assert tools.change_summary({"name": "deephouse.gospel"}) == "deephouse.gospel"
    assert tools.change_summary({"intent": "darker"}, {"applied": ["harmonic"]}) == "darker (harmonic)"
    assert tools.change_summary({"action": "fill", "fill": "snare.roll"}) == "action=fill fill=snare.roll"


# ---- audit C1: no library table silently drops a duplicate name (spec §3.5 "names are unique") ----------------------
# The tables are dict comprehensions over a tuple of entries, so a second entry with the same name would overwrite the
# first without an error. Count the entries written in the source against the dict.

import ast  # noqa: E402
from pathlib import Path  # noqa: E402

from whiplash import genres, phrases, progressions  # noqa: E402

TABLES = {"grooves.py": {"LANES": grooves.LANES, "GROOVES": grooves.GROOVES, "FILLS": grooves.FILLS},
          "phrases.py": {"PHRASES": phrases.PHRASES}, "progressions.py": {"PROGRESSIONS": progressions.PROGRESSIONS},
          "form.py": {"FORMS": form.FORMS, "MOVES": form.MOVES}, "genres.py": {"GENRES": genres.GENRES}}


@pytest.mark.parametrize("module, table", [(m, t) for m, ts in TABLES.items() for t in ts])
def test_library_tables_have_no_duplicate_names(module, table):
    tree = ast.parse((Path(__file__).resolve().parent.parent / module).read_text())
    comps = [n.value for n in ast.walk(tree) if isinstance(n, ast.Assign)
             and any(isinstance(t, ast.Name) and t.id == table for t in n.targets)]
    comps += [n.args[0] for n in ast.walk(tree) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr == "update" and isinstance(n.func.value, ast.Name) and n.func.value.id == table]
    assert comps and all(isinstance(c, ast.DictComp) and isinstance(c.generators[0].iter, ast.Tuple) for c in comps), \
        f"{table} is no longer built from literal tuples: update this test"
    written = sum(len(c.generators[0].iter.elts) for c in comps)
    kept = len(TABLES[module][table])
    assert written == kept, f"{table}: {written} entries written, {kept} kept (a duplicate name overwrote one)"


# ---- audit C2: test-plan gaps the audit found (spec §3.5, §4.5) ----------------------------------------------------

FILTER = engine.FILTER_CC


def test_timbral_never_touches_a_cymbal_or_fx_track_even_with_a_known_cutoff(eng):
    pretend_playing(eng, P["deephouse"])
    eng.label_tracks({"7": "tuned cymbal", "9": "fx", "10": "lead"})
    eng.write_part(10, rhythm="8ths", notes=["A5"])
    for track in (6, 7, 9, 10):
        eng.set_param(track, 100, param="filter_freq")
    bar_events(eng, 1)
    eng.test_port.messages.clear()
    eng.set_progression(intent="darker", how="timbral")
    bar_events(eng, 2)
    sent = {m.channel + 1 for m in eng.test_port.messages if m.type == "control_change" and m.control == FILTER}
    assert sent == {6, 10}


def test_undo_after_tension_restores_the_progression_and_the_pedal(eng):
    pretend_playing(eng, P["deephouse"])
    eng.set_progression(chords="i VI III VII", bars_per_chord=1)
    bar_events(eng, 1)
    chords = [c.name for c in eng._prog.chords]
    for bar in (2, 3, 4):
        eng.set_progression(intent="tension")
        bar_events(eng, bar)
    assert eng._prog_modes.get(6) == "pedal"
    eng.undo()
    bar_events(eng, 5)
    assert eng._prog_modes.get(6) != "pedal" and [c.name for c in eng._prog.chords] == ["Am", "F", "C", "E9"]
    eng.undo()
    eng.undo()
    bar_events(eng, 6)
    assert [c.name for c in eng._prog.chords] == chords


def test_tropical_pop_on_the_engine_reports_the_relative_key(eng):
    pretend_playing(eng, P["deephouse"])
    out = eng.set_progression(name="tropicalhouse.pop")
    assert out["key"] == "C major (relative of A minor)"
    assert [c["name"] for c in out["progression"]] == ["Cmaj7", "G", "Am7", "Fmaj7"]
    assert eng.key_name() == "A minor"


def test_hat_open_choke_plays_on_its_role_and_is_refused_on_a_melodic_track(eng):
    playing(eng, "deephouse")
    roles = {t: harmony.role_of(t, eng.pattern, eng._kit_tracks) for t in range(1, 9)}
    hat = next(t for t, r in roles.items() if r in grooves.FILLS["hat.open_choke"].roles)
    out = eng.schedule_fill(tracks=[hat], fill="hat.open_choke")
    at = out.get("at_bar") or out.get("fill_at_bar") or eng.bar + 1
    assert any(t == hat for _, t, *_ in bar_events(eng, at))
    with pytest.raises(engine.WhiplashError):
        eng.schedule_fill(tracks=[6], fill="hat.open_choke")


def test_a_move_replacing_an_energy_filter_form_still_reopens_at_its_end(eng):
    playing(eng, "progressivehouse")
    eng.arrange(form="groove 8, outro 8", energy_filter=True)
    for b in range(1, 11):
        bar_events(eng, b)
    music = sorted(k for k in eng._ramps if k[1] == FILTER)
    assert music
    eng.arrange(move="breakdown", bars=8)  # no energy filter of its own; then: continue
    with eng._lock:
        for track, cc in music:
            eng._cc_values[(track - 1, cc)] = form.ENERGY_FILTER[1]
    for b in range(11, 20):
        bar_events(eng, b)
    assert eng._arr is None
    assert all(eng._ramps[k].owner == engine.REOPEN and eng._ramps[k].end == 127 for k in music)
