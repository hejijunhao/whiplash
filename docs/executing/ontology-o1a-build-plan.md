# Whiplash ontology O1a build plan (v0.9.0, part 1 of 2)

Status:
- **Plan for O1a**, the first phase of [ontology-v1-spec.md](ontology-v1-spec.md) §9: the library, harmony and groove layers for four genres (deep house, classic house, tech house, techno). Branch `feat/ontology-o1a`, cut from `main` at `44330c8` (the ontology spec merged, PR #25).
- O1b (phrases and taste) follows in its own PR. Both make up **v0.9.0**, so this PR moves the version to 0.9.0 and opens the 0.9.0 changelog section; O1b adds to it.
- Nothing here has been tested on a real Digitakt II. Every **HW** item in §6 is a check for Phil's Air, not a result.

Inputs:
- **Spec:** [ontology-v1-spec.md](ontology-v1-spec.md). This plan's scope is §9's O1a row. The layer sections are §1 (shared pieces), §3 (harmony), §4 (grooves), §8 (hardware checks) and §10 (decisions).
- **Research:** [genre-conventions.md](../research/genre-conventions.md), cited by the spec's tables.
- **Device reference:** [reference.md](../digitakt-ii/reference.md): §6.1 (note 60, native pitch, 16-84), §6.4 (one voice per audio track).
- **Phil's go of 19 Nov 2026** to build the spec end to end, one phase per PR.

**Goal of O1a (the demo sentence):** "Chicago house, jack groove, energy 3": one call gives a jacking groove with a late clap, an octave-bounce bass and off-beat piano stabs over i–III–♭II–i, in key. And "deep house gospel progression" gives Am7 Fmaj7 G7 Am7 as shell voicings on the chord tracks.

**Constraints** (spec §0, unchanged):
- No SysEx, program change, project, pattern, kit or +Drive writes. Slots 1-3 are never touched. `BLOCKED_CCS` / `BLOCKED_NRPNS` stay blocked; O1a sends no new CC at all.
- Clock-safe: everything compiles in the tool thread into what the engine already schedules. Per-bar costs are named below.
- **Demo-safe:** `play_pattern(genre: "deephouse")` with no groove, and `groove: "deephouse.classic"` / `"deephouse.A"` at energy 3, play today's pattern bit for bit. The same holds for `techhouse.classic` and `techno.classic`. Part A of the hardware checklist is unchanged and `scripts/rehearse_demo.py` prints `RESULT: PASS`.
- The only intended change to existing words: the mood `peak time` now picks techno (§1.5). The other intended behaviour change is key lock (Q-H2): explicit notes on a melodic track now snap to the key.

## 1. Scope

| # | Item | Spec | Size |
| --- | --- | --- | --- |
| 1 | `library.py`: one name scheme, `resolve(kind, text)`, listings with `genre` and `tag` filters; the new tool `whiplash_list_library` | §1.1, §1.3 | S |
| 2 | `genres.py`: `Genre` records for deephouse, house, techhouse and techno; the compile path, with **house** the first compiled genre | §1.2, §2.1 | M |
| 3 | Aliases and moods: `classic house`, `chicago`, `chicago house` → house; `peak time` → techno; `peak time techno`, `peak time tech house`. Bare `house` stays deep house | §1.5 | S |
| 4 | Harmony: shapes `min9`, `maj9`, `9`, `min11`, `6`, `m6`, `7sus4` and their suffixes; voicing `shell` and its default rule for library chords; pads carry the extensions | §3.2 | M |
| 5 | `progressions.py`: the deep house (6), house (5), tech house (2) and techno (4) progressions; the scale-mismatch rule; `set_progression(name)` | §3.2.1, §3.3 | M |
| 6 | Key lock: explicit melodic notes snap to the key, with `snapped` in the result and `out_of_key: true` to opt out | §3.2 | S |
| 7 | `grooves.py`: lanes marked O1, velocity curves, `GHOST_VEL`, microtiming with the negative-offset compile, named fills, and the eight O1 grooves with five energy levels | §4.2 | L |
| 8 | Tools: `play_pattern(groove, energy)`, `write_part(groove)`, `mutate(action: "energy")`, `mutate(action: "fill", fill: "<name>")` | §4.3 | M |
| 9 | Skill, README, CHANGELOG, roadmap, version 0.9.0, budget pins, hardware checklist and reference §15.3 | §1.6, §9 | S |

**Not in O1a** (O1b and later): `harmony.Rel` and mode `phrase`, the phrase library, `write_part(phrase, density, seed, register)`, `bar_digest`, `changes`, `status(review)`, `taste_hint` (O1b); intents, key-only `set_progression`, `lock`, `pedal`, `follow` (O2); the other four genres, `soul.classic`, `breaks.classic` (O3); forms, moves, `fill_every` (O4).

## 2. New modules (pure, at the repo root)

- **`library.py`.** It holds no tables of its own. It gathers the entries from `genres`, `progressions` and `grooves`, so each table lives next to its data. `resolve(kind, text)`:
  - is case-insensitive and treats spaces, `-` and `_` alike
  - accepts a missing genre prefix when only one genre has that name (`gospel` → `deephouse.gospel`), or when a `genre` hint picks one (`groove: "shuffle"` with deep house playing)
  - reads natural phrases by dropping filler words and matching genre words: "deep house shuffle groove" → `deephouse.shuffle`, "chicago jack" → `house.jack`
  - takes letter aliases (`deephouse.A`)
  - raises `LibraryError` with up to three `difflib` matches and the hint `see whiplash_list_library(kind: "groove")`

  `entries(kind, genre, tag)` returns at most 40 entries, sorted by name, with `more`. `phrase`, `form` and `move` are valid kinds that are empty until O1b and O4, and say so.
- **`genres.py`.** The `Genre` dataclass of spec §1.2, the four records of §2.1 (the O3 four arrive in O3), and `compile(record)`.
- **`progressions.py`.** The `Prog` dataclass of spec §3.2 and the four genres' tables of §3.2.1. The tag vocabulary is a fixed set (an integrity test).
- **`grooves.py`.** `Lane`, `Groove`, `VELOCITY_CURVES`, `GHOST_VEL`, `FILLS`, the lanes and the eight grooves, plus `compile(groove, energy, genre pattern, kit)` → `patterns.Pattern`.

## 3. Design notes and decisions

Researchable questions were decided here from the spec and the research brief, and the PR lists them.

1. **House is compiled with baked lines in O1a.** The spec's house record names the phrases `bass.octave_pump` and `stab.offbeat`, which arrive in O1b with `harmony.Rel`. O1a compiles house with the same lines baked into plain notes against the default progression `house.piano_stab` (Am C B♭ Am, one bar each, which is exactly the 4-bar loop): the bass plays the root on each beat and the octave on each off-beat 8th, and the stab tracks play one chord tone each on steps 2, 6, 10 and 14. O1b replaces the baked lines with the phrase objects, which also makes them follow a later `set_progression`. Until then a later progression moves the house bass through the existing `root` mode, as with every genre today.
2. **Classic grooves are today's patterns.** At energy 3, `deephouse.classic`, `techhouse.classic` and `techno.classic` return the registered pattern object itself, so equivalence is exact by construction (and tested on `bar_events`). Their other levels are built from the pattern's own drum tracks: a level names a role as `@` (the hand-written track) or `@+<lane>` (the hand-written track plus the lane's hits on steps it doesn't already play). Classic grooves carry no `micro` at any level (Q-G2).
3. **Helper lanes beyond the spec's list**, so levels can grow by hits before elements: `rim.syncopated_busy` (the spec's "plus 14 at energy 5"), `clap.ghosts` (ghosts on 7 and 15, used only as an overlay on classic claps) and `kick.ghost_7` (the overlay half of `kick.ghost_mid`). Each is tagged `helper` and sourced.
4. **Second perc lane.** `techhouse.rolling` at energy 5 adds `perc.woodblock` on a second labelled perc track. A level is keyed by slot (`perc`, `perc2`), and `perc2` has no default track, so on an unlabelled kit it is reported under `unplaced`. The "at most one lane per role" integrity rule counts slots.
5. **Negative micro compile, swing-aware.** A negative offset moves the hit to the previous step at offset `6 + micro` (one step is 6 clock ticks). Global swing delays odd steps, so the compile adds the swing difference between the two steps at the groove's own swing: the hit sounds `micro` ticks from where its own step would sound with that swing. With straight swing this is exactly the spec's `6 + micro`. A later `mutate swing` makes the push slightly off (at most the swing change, a fraction of a tick). On step 0 the offset is clamped to 0 and reported as `pushed_downbeat_clamped`. Pattern hits gain an optional fifth field, the offset in ticks, which `mutate.working()` carries; 4-field hits play as before.
6. **Ghost velocities** are seeded per lane, bar and step from a fixed string, so a groove compiles to the same notes every time.
7. **Accents.** An `X` cell plays the curve's value plus 15 (capped at 127).
8. **Placement of lanes** (spec §4.4). Each slot goes to the genre's default track for that role (kick 1, snare or rim 2, clap 3, closed hat 4, open hat 5, perc 8 when the genre has a perc track there), else to a labelled track with that role or a close one, else it is `unplaced`. A labelled track is fixed when the groove compiles; relabelling later re-routes what was placed, as today, but doesn't place an unplaced lane until the next groove or energy call.
9. **Energy changes** compile the new level in the tool thread and land at the next bar line through `_reroute` (keeps swing, humanize, density, mutes, ramps, parts and the progression). They are refused while a switch is queued. `mutate energy` on a plain classic genre (no `groove` given) treats it as its classic groove at energy 3, because that is what plays. `play_pattern(energy)` without `groove` errors as the spec says ("energy needs a groove; try groove: 'A'").
10. **Named fills.** A fill name schedules that shape on the tracks of its roles (or the named tracks, refused on a melodic line). Per-bar cost: one dict lookup per filling track. A groove's `fills` map names the shape each role plays on `fill: true`; with no perc track labelled, `perc.tom_run` falls back to `snare.roll`. "Every 8 bars" comes with O4's `fill_every`.
11. **Shell voicing rule.** Library chords with a 7th (7th, 9th, 11th shapes) voice `shell` when three or fewer one-voice chord or stab tracks follow the progression, else `close`. The count is taken when `set_progression` runs; the result says which and why. A given `voicing` wins, and chords typed with `chords` keep today's default (`close`). Pad tracks (role `pad`) play the chord's other tones (the 9th first, then the 11th, then the 5th) from the full close voicing, so they carry the colour on top of the shell. Per-bar cost: one tuple lookup per pad track.
12. **11th and minor-major 9th.** An upper-case `11` reads as a dominant 11th (0 4 7 10 14 17); a lower-case `maj9` as a minor-major 9th (0 3 7 11 14), following the existing `maj7` case rule. The spec names only `min11` and `maj9`; these keep the case rule total.
13. **Scale mismatch** (spec §3.2). A library progression in another scale plays on the session root in its own scale, except major ↔ minor, which uses the relative key. The session key doesn't change (the pattern's melodic tracks stay where they are); only the progression's key does, and the result says `"key": "C major (relative of A minor)"`.
14. **Key lock** applies to tracks whose role is melodic (bass, pad, stab, chord, lead: `kitmap.MELODIC`). Drum, cymbal, fx and unlabelled `other` tracks are never snapped, so a drum sample on note 60 can never be moved. The key is the progression's while one plays, else the session key, else the pattern's home key.
15. **Genre enum.** The `genre` enum on `play_pattern` lists `chicago` for classic house, because the bare word `house` keeps meaning deep house (§1.5). The `house` id is not in the enum.
16. **Mix preset `auto`** reads the pattern's genre (a groove pattern is named `deephouse+shuffle@3`). Classic house has no mix preset of its own yet, so `auto` plays flat there.

## 4. Tools and budget

| Tool | Gains |
| --- | --- |
| `whiplash_list_library` (new, 26 tools) | `kind`, `genre`, `tag` |
| `whiplash_play_pattern` | `groove`, `energy`; result `groove: {name, energy, lanes, swing}`, `unplaced` |
| `whiplash_set_progression` | `name`; exclusive with `chords`; result `library`, `voicing_rule` |
| `whiplash_write_part` | `groove` (a lane, a sixth placement), `out_of_key`; results `lane`, `micro`, `velocity_curve`, `snapped` |
| `whiplash_mutate` | action `energy` with `amount` 1-5, `up` or `down`; `fill` takes a fill name for action `fill` |

Caps (`tests/test_v053.py::test_description_size_budget`): tools 4,100 → **4,250**, params 9,300 → **9,900**, JSON 22,000 → **23,500** bytes; 400 per tool stays. Tool count 25 → **26** (`test_whiplash.py`, `test_v04.py`). The final numbers are in the PR.

## 5. Tests (fake and virtual ports only)

New `tests/test_v090.py`:
- **Library:** resolve rules (case, separators, missing prefix, natural phrases, letter aliases), close matches and the hint on an unknown name, `list_library` filters, the 40-entry cap, unknown kind, empty filter.
- **Progressions:** every entry parses in all 12 keys; voicings stay in 41-79 with median ≥ 53; names unique and resolvable; tags from the fixed vocabulary; every entry has a source; `bass` references are `None` in O1a's four genres.
- **Shapes:** `parse_chord("i9", Am)` is min9; `Am9`, `Fmaj9` read; `shell` on Am9 is A, C, G near 60.
- **Shell rule:** two chord tracks → shell; four → close; a given voicing wins; with a pad the pad plays B (the 9th) and the chord tracks the shell.
- **Scale mismatch:** `house.mixed_shuffle` in A minor plays C major and reports the relative key.
- **Key lock:** `write_part(track: 7, notes: ["C#5"])` in A minor plays C5 and reports `snapped`; `out_of_key: true` plays C#5; a kick part's note 60 is never moved.
- **Lanes and grooves:** every grid parses (16 cells, 1/2/4 bars), velocities 1-127, micro −3..+3; every level names known lanes, one per slot, drum roles only; levels 1-5 never lose hits; no level passes the genre's `busy_drums` cap; classic grooves have no micro.
- **Equivalence:** `deephouse.classic`, `deephouse.A`, `techhouse.classic` and `techno.classic` at energy 3 give the same `bar_events` on bars 0-3 as today's patterns, and plain `play_pattern(genre)` is unchanged.
- **Micro:** `clap.2_4_ghosted` plays at +0.75 tick; −0.25 on step 6 lands on step 5 at 5.75 (straight swing), with the swing difference added otherwise; `humanize: 0` leaves the table exact; note-on times checked on a recording port.
- **Ghosts:** every `g` cell plays inside `GHOST_VEL`.
- **Routing:** `label_tracks({"9": "kick"})` puts the kick lane on 9 only; a perc lane with no perc track shows in `unplaced`.
- **Energy:** lands on the next bar line, keeps humanize, density and mutes, sends no Stop or Start; `up` at 5 and the no-groove errors.
- **Fills:** each named fill on its role; refused on a melodic line; `perc.tom_run` falls back to `snare.roll` with no perc track.
- **Aliases:** `resolve("house")` is deephouse; chicago words are house; `peak time` and `peak time techno` are techno; `peak time tech house` is techhouse.
- **House compile:** `play_pattern(genre: "chicago")` plays the jack groove, the octave bounce on track 6 and the stabs on 7-8.
- **Budget and tool count** pins updated; the rehearsal stays `RESULT: PASS`.

## 6. Phil's hardware checks (O1a)

From spec §8. They go into `docs/testing/hardware-checklist.md` (new Part O) and `reference.md` §15.3 as open questions. No result is claimed.

| # | Check | Listen for |
| --- | --- | --- |
| HW O-1 | "Deep house shuffle groove, energy 3", then "tech house rolling groove" | the clap sits behind the beat, the hats push ahead, both audible above USB jitter |
| HW O-2 | Ghost notes vs VELOCITY TO VOL on `deephouse.shuffle` and `house.jack` | ghosts audible but quiet (else `GHOST_VEL` → 40-55) |
| HW O-3 | "Chicago house" (track 6, 123 BPM) | clean root and octave retriggers near native pitch (the baked line in O1a) |
| HW O-4 | "Deep house gospel progression" on two or three chord tracks, then with a pad | Am7 Fmaj7 G7 Am7 with clean low-mids; the pad adds the 9th without mud |
| HW O-5 | By ear: the deep house six, house five, tech house two, techno four | each sounds like its genre on Phil's kit; list any to drop or revoice |
| HW O-6 | "Energy 5", then "energy 1" | each lands on the one, no stuck notes, no Stop or Start |

## 7. Order and merging

One PR against `main`, merge commit only; Deck merges. O1b is cut from `main` after this merges.
