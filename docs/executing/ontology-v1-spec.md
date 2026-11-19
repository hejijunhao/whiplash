# Whiplash ontology v1: spec

Status:
- **Spec only. Decisions settled** with Phil's orchestrator in two rounds (15 Nov 2026), resolved from genre research. **Fully decided 2026-11-19:** Phil confirmed every §10.1 question, with Q-H3 changed and Q-H4 delegated to Deck, and may revisit them in a later detailed review. **O1a is ready to start on Phil's go.** See §10.
- Branch `docs/ontology-spec`, cut from `main` at `3f4f883` (v0.8.0 merged, PR #23; visualiser timeline, PR #24).
- No code, tests, tool or version changes come with it.
- Nothing here has been tested on a real Digitakt II. Every item marked **HW** is a check for Phil's Air (§8), not a result.

Inputs:
- Phil's DeepSeek V4 sessions. With a weaker model, the beats still come out slightly simplistic.
- The diagnosis we agree on: today the model has to invent theory and groove on every bar, so a weaker model falls back on four on the floor plus a root note.
- [docs/research/genre-conventions.md](../research/genre-conventions.md): eight electronic genres, with sourced tempo, harmony, drum, bass, arrangement and repetition conventions. Every per-genre number below cites it, or is marked **by ear** where the research gives no figure. In Source columns, §n is the research brief's section; in prose, research sections say "research §n" and a bare §n is this spec's.
- Every module named below, read on `main` at `3f4f883`.

**Goal (the demo sentence):** "Chicago house, jack groove, energy 3": one call, and it comes with a piano-stab progression, an octave-bounce bass and a late clap, instead of four on the floor plus a root note. The same holds for each of the eight genres in §2.

**Principle.** Tools take musical intent, for example:
- "darker"
- "more tension"
- "lift the energy"
- "deep house shuffle groove, energy 3"
- "build to the drop in 16 bars"

The plugin then does the theory and the timing, deterministically, from in-repo tables. The model's job shrinks to picking and combining named things. It no longer places 16 steps by hand.

## 0. Constraints (every layer, every phase)

- **Never sent:**
  - SysEx or program change (`Engine.send()` refuses them; the allow-list stays as it is).
  - Project, pattern, kit, preset or +Drive writes, and no file transfer.
- **Never touched:** Digitakt slots 1-3.
- **Never read or written:** the unit's internal patterns. Nothing here reads anything from the unit except what v0.8.0's `whiplash_play_along` already hears.
- **Clock-safe and bar-quantised.** No new clock path and no new sequencer thread.
  - Everything compiles, in the tool thread, into what the engine already schedules: a working pattern (`Engine._work`), a progression (`Engine._prog`), queued switches (`_queued`), timed actions (`_timed`: ramps, mixes, kind `call`), fills (`_fills`), drops (`_drops`), mutes, and arrangement sections (`_arr`).
  - At the bar line the sequencer does only cheap lookups and small list work, of the kind `harmony.apply()` already does (at most 64 hits per track per bar).
  - Each new per-bar cost is named in its layer below.
- **`ccmap.BLOCKED_CCS` / `BLOCKED_NRPNS` stay blocked.** No layer needs a new CC. Filters, levels and pan use `filter_freq` (CC 74), `track_level` (CC 95) and `pan` (CC 90), which are already in use.
- **No new hard dependency.**
  - Libraries are Python tables in new pure modules at the repo root (the root is the package), like `patterns.py` today.
  - Not YAML: PyYAML isn't a dependency (`plugin.yaml` lists only mido and python-rtmidi), and the stdlib can't read it.
  - Nothing new is imported by the sequencer that it doesn't already import.
- **Native register (v0.5, [reference](../digitakt-ii/reference.md) §6.1).**
  - Note 60 is the sample's own pitch, and every note stays in 16-84.
  - A melodic line's median stays no more than `patterns.NATIVE_FLOOR` (7) below 60.
  - One voice per audio track is assumed (§6.4, Q12).
- **Tests use fake and virtual ports only:**
  - `make_engine()` and `call()` from `tests/test_whiplash.py`
  - `bar_events()`, `pretend_playing()` and `wait_bar()` from `tests/test_live.py`
  - `FakeInput` from `tests/test_v080.py`
- **Hardware checks go to Phil** as a checklist (§8). The build PRs add them to `docs/testing/hardware-checklist.md` and `reference.md` §15.3 (Q32 on), as earlier versions did. No result is claimed until Phil has run it.
- **`main` stays demo-safe.**
  - `play_pattern(genre: "deephouse")` with no `groove`, and `groove: "deephouse.classic"` (alias `deephouse.A`) at energy 3, play today's pattern bit for bit. The same holds for `techhouse.classic`, `techno.classic`, `soul.classic` and `breaks.classic`.
  - Part A of the hardware checklist is unchanged, and `scripts/rehearse_demo.py` prints `RESULT: PASS`.
  - Every library pick is opt-in, so today's calls play exactly as before. The only intentional change to existing words is the mood "peak time" (§1.5), which the changelog spells out.

## 1. Shared pieces (all layers)

### 1.1 Names and lookup: `library.py` (new, pure)

- **One naming scheme for every table:** `<genre>.<name>` for genre-owned entries, `<role>.<name>` for shared lanes, phrases and fills. Examples: `deephouse.gospel` (progression), `house.jack` (groove), `hat.offbeat_shuffle` (lane), `bass.octave_pump` (phrase), `snare.roll` (fill), `techno_plateau` (form).
- **Kinds:** `genre`, `progression`, `groove`, `lane`, `phrase`, `fill`, `form`, `move`. Each kind is its own namespace.
- **`library.resolve(kind, text)`** accepts what a model is likely to type:
  - case-insensitive
  - spaces, `-` or `_`
  - a missing genre prefix when it is unambiguous
  - natural phrases: "deep house shuffle groove", "chicago jack"
  - letter aliases where they exist today: `deephouse.A` = `deephouse.classic` (§4.2)

  An unknown name raises with the closest matches (`difflib`, as `patterns.resolve()` does) and the hint `see whiplash_list_library(kind: "groove")`.
- **Names are never schema enums.** Enumerating hundreds of names would blow the tool-description budget (§1.4). They are validated in code instead, and listed by `whiplash_list_library`.
- **Every entry carries `tags`** (genre, mood, energy and so on), a one-line `about`, and `source` (a §n of the research brief, or `by ear`).
- **Progression numerals use `harmony.parse_chord`'s convention:** scale degrees of the progression's own scale. In A minor `VI` is F, `VII` is G and `III` is C. The research writes the major-relative `bVI`, `bVII` and `bIII`; in this spec those are `VI`, `VII` and `III`. An accidental means a note outside the scale: `bII` in A minor is B♭.

### 1.2 The genre record: `genres.py` (new, pure)

```python
@dataclass(frozen=True)
class Genre:
    name: str            # "house", "minimal.house"
    family: str          # "house" | "techno" | "minimal" ...: shared rules (minimal's two presets share one)
    bpm: float           # default tempo
    swing: float         # Pattern.swing, 0.50 straight
    key: tuple           # (pitch class, scale): the home key, as patterns.HOME_KEYS
    groove: str          # default groove
    progression: str | None   # default progression (None: no chords, e.g. minimal)
    bass: str            # default bass phrase
    chords: str | None   # default phrase for the chord tracks (stab.offbeat, pad.hold, ...)
    roles: dict          # track -> role, the same 1-8 layout patterns.py uses
    breakdown: str       # breakdown style (§6.2)
    form: str            # default form (§6.2)
    taste: dict          # {"unchanged_bars": n, "busy_drums": n}  (§7.2)
    tags: frozenset
    about: str
    source: str
```

- **Existing genres keep their hand-written tables.** `deephouse`, `techhouse`, `techno`, `soul` and `breaks` stay in `patterns.PATTERNS` exactly as written. Their records add only defaults for the new layers. Their hand-written bass and chords play with every groove; the record's `bass` and `chords` are the recommended phrases (shown by `list_library`, and used by `write_part(phrase: "genre")`).
- **New genres are compiled, not hand-written.** At import, `genres.compile(record)` builds a `patterns.Pattern`:
  - the drum tracks from the default groove at energy 3 (layer 2)
  - the bass track from the `bass` phrase, and the chord tracks from the `chords` phrase, resolved against the default progression (layer 3). With no progression they resolve against the home key's tonic chord.
  - `bpm`, `swing` and `key` from the record
  
  It goes through `patterns.register` like every table today, and lands in `patterns.PATTERNS` under the record's name. Downstream (`kitmap.route`, `harmony.in_key`, fills, density, arrangement) nothing changes.
- **Tempos.** The existing tempos already match the research (122 / 126 / 130, research §1, §3, §5) and do not change.

### 1.3 `whiplash_list_library` (the one new tool)

```
whiplash_list_library(kind: "genre"|"progression"|"groove"|"lane"|"phrase"|"fill"|"form"|"move", genre?, tag?)
-> {kind, entries: [{name, about, tags, ...kind-specific: chords | energy_levels | role | bars | bpm}], more: n}
```
- At most 40 entries per call, sorted by name. `genre` and `tag` filter the list.
- It is read-only, works with nothing playing, and never touches the engine.
- **Failure hints:**
  - an unknown kind lists the kinds
  - an empty filter says which genres and tags exist
- **Description** (about 120 characters): "List named genres, progressions, grooves, lanes, phrases, fills, forms and moves (with tags) to use by name in other tools."

### 1.4 Tools and the description budget

Today the tool descriptions total 4,033 of the 4,100-character cap. The caps are pinned in `tests/test_v053.py::test_description_size_budget`: tools 4,100, params 9,300, JSON 22,000 bytes, and at most 400 per tool. The tool count is pinned in `tests/test_whiplash.py::test_every_tool_is_namespaced` (25) and in `tests/test_v04.py::test_tools_in_manifest_order`.

**One new tool** (Q-S1): `whiplash_list_library`. Discovery is the one job no tool does, because names can't be enums. Everything else folds into an existing verb:

| Need | Where it goes | Phase |
| --- | --- | --- |
| a groove and an energy level | `whiplash_play_pattern`: `groove`, `energy` | O1 |
| a named progression | `whiplash_set_progression`: `name` | O1 |
| a lane, a phrase, key lock opt-out | `whiplash_write_part`: `groove`, `phrase`, `density`, `seed`, `register`, `out_of_key` | O1 |
| energy while playing | `whiplash_mutate(action: "energy", amount: 1-5 \| "up" \| "down")` | O1 |
| a named fill | `whiplash_mutate`: `fill` takes a fill name as well as `true` | O1 |
| feedback | `whiplash_status(review: 4-32)` (status's first argument) | O1b |
| intents, key changes, lock | `whiplash_set_progression`: `intent` (with `how` for darker/brighter), `lock`; `key`/`scale` with no chords changes the key (today that errors "give chords") | O2 |
| auto-follow for written parts | `whiplash_write_part`: `follow` | O2 |
| forms and performance moves | `whiplash_arrange`: `form`, `then`, `move`, `bars`, and section keys `energy`, `fill_every`, `enter`, `exit` | O4 |

Proposed caps once all phases ship: tools 4,350, params 10,300, JSON 24,000 bytes, **26 tools**. Each phase raises only what it uses, and says so in its PR.

### 1.5 Aliases and moods (`patterns.ALIASES`, `patterns.MOODS`)

`patterns.resolve()` checks `ALIASES` before `PATTERNS`, so an alias wins over a genre name.

| Word | v0.9 resolves to | Note |
| --- | --- | --- |
| `house` | **deephouse (unchanged)** | The new classic genre's id is `house`, but the bare word keeps meaning deep house in v0.9, because the demo and the skill may say "play house". A test pins `resolve("house") == deephouse`. Remapping the bare word later is a separate, explicit decision (§11). |
| `classic house`, `chicago`, `chicago house` | house | new |
| `peak time` (mood) | **techno (changed; was techhouse)** | Research §5: peak time is techno. |
| `peak time techno` | techno | new, so the explicit form works |
| `peak time tech house` | techhouse | new, so the old meaning still works |
| `minimal` | **minimal.house** | Phil lists minimal with the house-family styles, and the two are often confused. |
| `minimal house`, `minimal techno` | minimal.house, minimal.techno | explicit presets |
| `progressive`, `progressive house`, `prog house` | progressivehouse | O3 |
| `melodic techno` | melodictechno | O3 |
| `tropical`, `tropical house` | tropicalhouse | O3 |
| new moods `jacking` → house; `journey` → progressivehouse; `cinematic`, `emotional` → melodictechno; `sunny`, `summer`, `beach` → tropicalhouse; `sparse` → minimal.house | | Existing moods (`happy` → breaks, and the rest) are unchanged. |

**Changelog lines the build PRs must carry** (O1 for house and peak time, O3 for the rest):
- "`house` still means deep house. The new classic/Chicago house genre is `classic house`, `chicago` or `chicago house`; its id is `house`, which only names it inside library entries (`house.jack`). A future version may remap the bare word."
- "The mood `peak time` now picks techno. It used to pick tech house; say `peak time tech house` for the old choice."

### 1.6 The skill

`skills/digitakt/SKILL.md` gets:
- a "Named things first" fast path: list, pick, combine
- one worked example per layer, and one line per genre (its signature, §2)
- the house ambiguity, said plainly
- a diagnostics row per new failure

The descriptions stay short, and the skill stays the single reference, as now.

---

## 2. The eight genres

The ontology v1 set is eight electronic genres. `soul` and `breaks` stay in the plugin as they are; they get `classic` grooves (O3) but no new libraries. Signatures are from the research brief.

| Genre (id) | Signature | Built in |
| --- | --- | --- |
| Deep house (`deephouse`) | 122 BPM, warm m7/m9 vamps, swung 8th hats, late clap, rolling bass, slow entries | O1 |
| House, classic/Chicago (`house`) | 123 BPM, jacking 4/4, late clap, off-beat piano stabs, octave-bounce bass, little swing | O1 |
| Tech house (`techhouse`) | 126 BPM, every-16th hats pushed early, short bouncy bass, change something every 8 bars | O1 |
| Techno (`techno`) | 130 BPM, kick-led, one chord or a dark two-chord vamp, off-beat bass, plateaus | O1 |
| Progressive house (`progressivehouse`) | 124 BPM, lush 7th/sus chords, long filtered builds, drumless breakdowns | O3 |
| Melodic techno (`melodictechno`) | 124 BPM, cinematic minor chords every two bars, rolling 16th bass, stutter leads | O3 |
| Minimal (`minimal.house`, `minimal.techno`) | 126 / 128 BPM, 3-4 drum elements, space, microtiming, one change per phrase, little harmony | O3 |
| Tropical house (`tropicalhouse`) | 108 BPM, major pop harmony, soft drums, shakers and mallets, hooks instead of big drops | O3 |

### 2.1 Defaults per genre (the `Genre` records)

| Genre | BPM | Swing | Home key | Default groove | Default progression | Bass phrase | Chord phrase | Breakdown | Form |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| deephouse | 122 (existing; §1 modal 122) | 0.55 (existing; §1 54-60%) | A minor (existing) | `deephouse.classic` | none (hand chords); recommend `deephouse.two_chord` | hand bass; recommend `bass.rolling_deep` | hand chords; recommend `pad.hold` | `kick_bass_out` | `deephouse_dj` |
| house | 123 (§2) | 0.52 (§2 50-55%) | A minor (§2: A minor / C major common) | `house.jack` | `house.piano_stab` | `bass.octave_pump` | `stab.offbeat` | `filter_bass` (**by ear**: §2 says breakdowns are less central) | `house_jack` |
| techhouse | 126 (existing; §3 modal) | 0.56 (existing; `techhouse.rolling` 0.53, §3 mild shuffle) | A minor (existing; §3 cites F, F#, G minor) | `techhouse.classic` | none (hand stab); recommend `techhouse.one_note` | hand bass; recommend `bass.bouncy` | hand stab; recommend `stab.offbeat` at density 0.25 | `filter_low_end` | `techhouse_dj` |
| techno | 130 (existing; §5) | 0.50 (existing) | F minor (existing) | `techno.classic` | none (hand stab); recommend `techno.pedal` | hand bass; recommend `bass.offbeat` | hand stab; recommend `stab.offbeat` at density 0.25 | `kick_drop` | `techno_plateau` |
| progressivehouse | 124 (§4) | 0.50 (**by ear**: §4 gives no swing; the pump is the groove) | A minor (§4) | `progressivehouse.functional` | `progressivehouse.circle` | `bass.root_follow` | `stab.offbeat` (groove), `pad.hold` (breakdown) | `kick_bass_out` | `progressive_journey` |
| melodictechno | 124 (§8) | 0.50 (**by ear**) | A minor (§8: minor/modal; NI's i–VI–III–VII example) | `melodictechno.stripped` | `melodictechno.cinematic` | `bass.rolling_16` | `pad.hold` | `kick_bass_out` | `melodic_journey` |
| minimal.house | 126 (§6) | 0.57 (§6 Attack 55-60%) | A minor (**by ear**: §6 often no key) | `minimal.house_shuffle` | none | `bass.stab_sparse` | `stab.single` | `subtract_one` | `minimal_long` |
| minimal.techno | 128 (§6) | 0.53 (§6 Schunk small shuffle) | A minor (**by ear**) | `minimal.techno_kick` | none | `bass.offbeat` | none | `subtract_one` | `minimal_long` |
| tropicalhouse | 108 (§7) | 0.53 (§7 light swing; **by ear** value) | C major (§7: major; I–V–vi–IV in C) | `tropicalhouse.soft` | `tropicalhouse.pop` | `bass.round_sub` | `pad.hold` | `reduce_drums` | `tropical_song` |

Track layout for compiled genres is the one `patterns.py` already uses: 1 kick, 2 rim or snare, 3 clap, 4 closed hat, 5 open hat, 6 bass, 7-8 chord, stab or perc. A genre that uses fewer roles leaves tracks silent, as kits with fewer labels do today.

---

## 3. Layer 1: Harmony

### 3.1 What exists, and the gap

**Exists (`harmony.py`, v0.6.0):**
- `Key` (pitch class plus a scale from `parts.SCALES`: 13 scales and modes, including dorian, phrygian, lydian, mixolydian, harmonic and melodic minor, pentatonics and blues).
- Roman-numeral and chord-name parsing, with shapes in `SHAPES`: triads, 7ths, sus, add9, power (`5`).
- `voice()` with voicings `close` (voice-led), `root`, `open` and `power`, near native pitch: median at least 53, notes 41-79.
- `in_key()` moves a pattern's melodic tracks by scale degree, and `snap()` snaps a note to the scale.
- Track modes `chords`, `stack`, `root`, `snap` and `off`, picked by role through `ROLE_MODES` (chord, pad and stab → chords; bass → root; lead → snap). Drum, cymbal and fx tracks are refused.
- `apply()` reshapes each bar's hits at the bar line.
- `whiplash_set_progression` (chords, `bars_per_chord`, voicing, key, scale, per-track overrides, clear) and `key` on `whiplash_play_pattern`. Each pattern has a home key in `patterns.HOME_KEYS`. `set_progression` needs chords today ("give chords, e.g. ...").

**Gap:**
1. **No named, tagged progressions.** The model has to know that deep house likes im7–ivm7 or a Dorian im7–IV7 with 9ths.
2. **No 9th or 11th shapes,** and no voicing that sounds like a min9 on the two or three one-voice chord tracks a kit has.
3. **No intent.** "Darker" and "more tension" have to be translated into theory by the model.
4. **Written parts and explicit notes can play out of key.** `whiplash_write_part(notes: ["C#5"])` in A minor plays C#. Only generated melodic tracks follow the key.
5. **No plain key change.** Changing the key alone takes a queued `whiplash_play_pattern(key)` or a `set_progression` that also sets chords.

### 3.2 Data model: `progressions.py` (new, pure tables) and small additions to `harmony.py`

- **New shapes** in `harmony.SHAPES`:
  - `min9` (0 3 7 10 14), `maj9` (0 4 7 11 14), `9` (0 4 7 10 14), `min11` (0 3 7 10 14 17), `6` (0 4 7 9), `m6` (0 3 7 9), `7sus4` (0 5 7 10)
  - their suffixes in `ROMAN_SUFFIX` (`9`, `maj9`, `11`, `6`, `7sus4`, with the existing upper and lower case rule) and `NAME_SUFFIX` (`m9`, `maj9`, `9`, `m11`, `6`, `m6`, `7sus4`)
- **New voicing `shell`:** the root, 3rd and 7th of a 7th, 9th or 11th chord. The 5th and the extensions are dropped (Q-H4, answered 2026-11-19).
  - **Default** for library 7th, 9th and 11th chords on chord and stab tracks when the kit has three or fewer one-voice chord tracks; otherwise `close`. A given `voicing` overrides it.
  - **Pad tracks** (role `pad`) may take the fuller voicing: `close` with the full shape, so the 9th (and 11th) sound there on top of the shell.
  - **Why:** the three shell notes keep the Digitakt's low-mids clean on one-voice audio tracks. The extensions on pads keep the deep house colour.
  - It is voice-led like `close`, with the same bounds (`CHORD_LOW` 53 median, 41-79).
  - **HW:** whether the shell, and a pad carrying the 9th, sound right on Phil's samples (§8, HW O-4).
- **Progression entries:**

```python
@dataclass(frozen=True)
class Prog:
    name: str            # "deephouse.gospel"
    chords: str          # numerals in the progression's scale (§1.1), e.g. "i7 VImaj7 VII7 i7"
    bars_per_chord: int
    voicing: str | None  # None: the default rule (shell for 7th/9th/11th on <= 3 chord tracks, pads full; else close)
    scale: str           # the scale it is written in ("minor", "dorian", "major", ...)
    bass: str | None     # a phrase it is written for (bass.descending_walk), else None
    tags: frozenset      # genre, mood words (warm, soulful, uplift, dark, hypnotic, cinematic, ...)
    brightness: int      # -2 (darkest) .. +2, for intents
    tension: int         # 0 (static vamp) .. 3 (dominant pull)
    source: str          # research section, or "by ear"
    about: str
```

- **Scale mismatch rule.** A progression plays on the session root in its own scale, except major ↔ minor, which uses the relative key (an A minor session playing `tropicalhouse.pop` plays it in C major). Mode entries such as `dorian_soul` keep the root (A dorian). The result says which: `key: "C major (relative of A minor)"`. Key lock (below) follows the progression's key while it plays.
- **Every entry is a starting point that still needs Phil's ear** (§8, HW O-5). Sources are where the progression comes from, not proof that it sounds right on his kit.

#### 3.2.1 Progression library, all eight genres

Chords shown in the genre's home key. 8-bar loops where the source allows.

**Deep house** (research §1; Q-H1). The research says deep house is not "i–VI–III–VII only"; that loop is house-wide and goes to `house.uplift`.

| name | numerals (scale) | A minor | bars/chord | tags | source |
| --- | --- | --- | --- | --- | --- |
| `deephouse.two_chord` | i7 iv7 (minor) | Am7 Dm7 | 2 | classic, hypnotic | §1 BeatKey, Violet |
| `deephouse.dorian_soul` | i7 IV7 (dorian) | Am7 D7 | 2 | soulful, warm | §1 BeatKey |
| `deephouse.two_five` | iv7 VII7 IIImaj7 IIImaj7 (minor): ii–V–I of the relative major | Dm7 G7 Cmaj7 Cmaj7 | 2 | jazzy | §1 BeatKey |
| `deephouse.gospel` | i7 VImaj7 VII7 i7 (minor) | Am7 Fmaj7 G7 Am7 | 2 | gospel, warm | §1 BeatKey |
| `deephouse.afro` | i7 IIImaj7 VII7 VImaj7 (minor) | Am7 Cmaj7 G7 Fmaj7 | 2 | afro, rolling | §1 BeatKey |
| `deephouse.one_chord` | i9 (minor) | Am9 | 4 | deep tech, hypnotic | §1 BeatKey |

**House, classic/Chicago** (research §2).

| name | numerals (scale) | A minor / home | bars/chord | tags | source |
| --- | --- | --- | --- | --- | --- |
| `house.piano_stab` | i III bII i (minor) | Am C B♭ Am (the Em–G–F–Em shape) | 1 | piano, classic | §2 MusicRadar |
| `house.mixed_shuffle` | I bVII i IV (major) | C B♭ Cm F (relative C major, by the scale-mismatch rule) | 1 | piano, bright | §2 MusicRadar |
| `house.uplift` | i VI III VII (minor) | Am F C G | 2 | uplift; also tagged deephouse, progressivehouse | §1, §2 Violet |
| `house.jack_vamp` | i7 iv7 (minor) | Am7 Dm7 | 2 | organ, jacking | §2 Violet |
| `house.minor_twist` | i7 v7 i7 #iii7 (minor) | Am7 Em7 Am7 C#m7 (the Cm7–Gm7 … Em7 shape) | 1 | twist | §2 Violet |

**Tech house** (research §3: harmony is secondary; one or two notes, dark one- or two-chord loops).

| name | numerals | A minor | bars/chord | tags | source |
| --- | --- | --- | --- | --- | --- |
| `techhouse.one_note` | i5 | A5 | 4 | sparse | §3 Mix Elite, Abletonic |
| `techhouse.dark_two` | i7 bII (minor) | Am7 B♭ | 2 | dark, phrygian | §3 EDMProd, Mix Elite |

**Techno** (research §5: one chord or pedal, or a two-chord dark vamp; stabs m7, sus2 or a 5th; home F minor).

| name | numerals | F minor | bars/chord | voicing | tags | source |
| --- | --- | --- | --- | --- | --- | --- |
| `techno.pedal` | i5 | F5 | 4 | power | hypnotic | §5 Brizm, Armon |
| `techno.phrygian` | i bII | Fm G♭ | 2 | power | dark | §5 Armon |
| `techno.dark_vamp` | i VI | Fm D♭ | 2 | close | dark | §5 Armon |
| `techno.sus_stab` | isus2 | Fsus2 | 4 | close | stab | §5 Brizm |

**Progressive house** (research §4: 7ths, 9ths, sus4, not triads; long releases).

| name | numerals (minor) | A minor | bars/chord | tags | source |
| --- | --- | --- | --- | --- | --- |
| `progressivehouse.circle` | i7 iv7 VIIsus4 IIImaj7 | Am7 Dm7 Gsus4 Cmaj7 | 2 | circular | §4 BeatKey (voicings **by ear**) |
| `progressivehouse.long_two` | i7 iv7 | Am7 Dm7 | 4 | patient | §4 BeatKey (held for 64 bars while texture builds) |
| `progressivehouse.phrygian_turn` | i bII i V7 | Am B♭ Am E7 | 2 | dark | §4 BeatKey |
| `progressivehouse.descending` | i9 (held), with `bass: bass.descending_walk` | Am9 over A G F E | 4 | prydz-like | §4 BeatKey (Am–Am/G–Fmaj7–E7 as a bass walk, see §5.2) |
| (`house.uplift`) | shared | | | restrained uplift | §4 |

**Melodic techno** (research §8, Q-H1 challenge: sourced material only).

| name | numerals (minor) | A minor | bars/chord | tags | source |
| --- | --- | --- | --- | --- | --- |
| `melodictechno.cinematic` | iadd9 VImaj7 III VIIsus2 | Am(add9) Fmaj7 C Gsus2 | 2 | cinematic | §8 NI (i–VI–III–VII, chords every two bars, add9/maj7/sus2) |
| `melodictechno.held_vamp` | i9 VImaj7 | Am9 Fmaj7 | 4 | conservative: chords hold while the lead moves | §8 NI, Soundtrap; Phil default |

**Minimal** (research §6: by default no progression; when present, one stab).

| name | numerals | A minor | bars/chord | tags | source |
| --- | --- | --- | --- | --- | --- |
| `minimal.stab_m7` | i7 | Am7 | 4 | stab | §6 Brizm |
| `minimal.stab_sus2` | isus2 | Asus2 | 4 | stab | §6 Brizm |
| `minimal.fifth` | i5 | A5 | 4 | stab | §6 Brizm |

**Tropical house** (research §7: pop house, maj7/9 for a brighter pad; home C major).

| name | numerals (major) | C major | bars/chord | tags | source |
| --- | --- | --- | --- | --- | --- |
| `tropicalhouse.pop` | Imaj7 V vi7 IVmaj7 | Cmaj7 G Am7 Fmaj7 | 2 | sunny | §7 Melodigging (2 bars **by ear**) |
| `tropicalhouse.pop_minor` | vi7 IVmaj7 Imaj7 V | Am7 Fmaj7 Cmaj7 G | 2 | wistful | §7 Melodigging |

**Soul, breaks:** no new progressions.

- **Intent tables** (`progressions.INTENTS`, pure, O2). Each intent is a deterministic transform. `tension` and `release` change the progression only.
- **`darker` and `brighter` are a menu, not one hard-wired transform** (Q-H3, answered 2026-11-19). The plugin gives the model context and a small menu of interpretations. The model picks one or combines them with `how`, and the result names which were applied, so the change is explainable and undoable. With no `how`, the **harmonic** option applies.

  | `how` | `darker` | `brighter` |
  | --- | --- | --- |
  | `harmonic` (default) | Darker chord qualities and modes; flatten the 3rd/6th; lower the voicing register. With a library progression playing, swap to the same genre's entry with the next lower `brightness` and the most shared tags. With a hand-written one, shift the mode one step down the ladder lydian → major → mixolydian → dorian → minor → phrygian. Phrygian is the floor, and locrian is never chosen. | The reverse, with lydian as the ceiling. |
  | `timbral` | Close the filter (`filter_freq`, an existing unblocked CC) or reduce brightness on the **melodic** tracks only (chord, pad, stab, bass, lead), one bounded step, at the next bar line. Drums, cymbals and fx are never touched. | Open them by the same step, never past the value before the first `darker`. |
  | `register` | Thin the highs (the top chord voice and any lead above 72 drop out or move down) and drop the lead an octave, within the 41-79 bounds. | Restore the highs and lift the lead back. |

  - **Context for the model:** the `set_progression` description names the three options in one line. The result lists the options that were not used (`"other_options": ["timbral", "register"]`), so a weak model can try another next time without guessing.
  - **Undo:** `whiplash_undo` restores the progression, the CC values Whiplash sent before the step, and the lead's register.
  - **Energy is separate:** a `timbral` step is the model's explicit choice. It is not the opt-in filter-as-energy of Q-A1, and `mutate energy` never undoes it.
  - **`tension`:** `tension` +1: turn the last chord into its dominant (V7 from harmonic minor; the home tables already lean on G♯ in A minor), or add sus4 or 9 to the last chord, or turn on a bass pedal (new track mode `pedal`: the key's tonic under every chord).
  - **`release`:** back to the progression that was playing before the first `tension`, ending on i or I. The pedal is off.
  - Each result names what it did, e.g. `{"intent": "darker", "applied": ["harmonic"], "did": "A minor -> A phrygian", "chords": [...], "other_options": ["timbral", "register"]}`.
- **Key lock follows Phil's wording** (Q-H2, answered 2026-11-19): melodic lines (bass, lead, chords) follow the key so they stay tonal. Drums stay on the grid and are never pitch-corrected to the scale; a snare must never accidentally sound like a note.
- **Key lock** (`harmony.lock`, engine state), **on by default once a key is set** (Q-H2). With a key set (`Engine.effective_key()`), every explicit melodic note snaps to the scale with `harmony.snap()`. That covers `whiplash_write_part` `notes` and `hits` on non-drum roles, and v0.8.0 follow replies, which already snap.
  - The result lists `snapped: [{"from": "C#5", "to": "C5"}]`.
  - `out_of_key: true` on `write_part` opts out, per part, for a deliberate chromatic note.
  - Drum roles (note 60) are never touched.
  - `set_progression(lock: false)` turns it off for the session (O2).
- **Auto-follow for written parts** (O2): `write_part(..., follow: true)` gives a written melodic part a mode (`snap` by default), so it follows the progression like a generated line. Phrases (layer 3) follow by default.
- **Later, not v0.9:** slash chords (`Am/G`) in the parser. Until then a moving bass under a held chord is a bass phrase (`bass.descending_walk`). Listed in §11.

### 3.3 Tools

- **`whiplash_set_progression`** gains:
  - `name: "deephouse.gospel"` (O1): chords, `bars_per_chord` and voicing come from the library. Given arguments override them.
  - `intent: "darker" | "brighter" | "tension" | "release"` (O2)
  - `how: "harmonic" | "timbral" | "register"`, or a list of them, for `darker` and `brighter` only (O2; default `harmonic`). With `tension` or `release`, it errors "how is for darker or brighter".
  - `lock: true | false` (O2)
  - **Key-only calls** (O2): `key` and/or `scale` with no `chords`, `name` or `intent` change the key from the next bar line instead of erroring. The melodic tracks move (`in_key`), a Roman-numeral progression is re-voiced in the new key, and a chord-name progression shifts by the same interval. Result: `{key, from, lands_at_bar, progression: [...], lock}`.
  - `chords`, `name` and `intent` are mutually exclusive.
  - **Failure hints:**
    - unknown name: the closest matches, and `whiplash_list_library(kind: "progression", genre: ...)`
    - `intent` with nothing playing: "start a beat first"
    - `release` with nothing to release: "no tension to release; the progression is unchanged"
    - a key equal to the current one: "already in A minor"
    - a bad key echoes `parts.parse_key`'s message

### 3.4 Scheduler and tracks

- **Library and intent picks** compile into the same `harmony.Progression` that `set_progression` builds now: parsed and voiced in the tool thread, starting on the next bar (`Progression.start`).
  - The sequencer still does only `prog.index(bar)` plus `harmony.apply()`.
  - The `pedal` mode is one `nearest()` call per hit, the same as `root`.
- **Key-only changes** are a timed action of kind `call` (as `whiplash_undo` does) at the next bar line. It sets `Engine._key` and swaps in a routed pattern prepared in the tool thread by a new shared helper, `_routed(self._raw_pattern, key)`, plus a progression re-voiced in the tool thread. The bar line does assignments only, with no voicing and no routing.
- **Roles decide who follows, through `ROLE_MODES` and the kit map, unchanged:**
  - chord, pad and stab tracks (kit roles, or the generated roles on tracks 7-8) take `chords` across one-voice tracks
  - bass takes `root` (or `pedal`)
  - lead takes `snap`
  - drums, cymbal and fx never follow
- **Tracks 9-16** follow only when labelled, as now.

### 3.5 Test plan (fake ports only)

- **Library integrity** (pure):
  - every `Prog` parses in all 12 keys and in its scale
  - every voicing stays within 41-79 with median 53 or more
  - names are unique and resolvable through `library.resolve`
  - tags come from a fixed vocabulary, and every entry has a `source`
  - every `bass` reference names a phrase that exists
- **Shapes:** `parse_chord("i9", Am)` is `(9, (0, 3, 7, 10, 14))`, `Am9` and `Fmaj9` read correctly, and `shell` on Am9 gives A, C, G (root, 3rd, 7th) near 60.
- **Shell rule:** with two labelled chord tracks a library min9 voices `shell`; with four it voices `close`; a given `voicing` wins. With chord tracks plus a `pad` track, the pad carries the 9th (B) and the chord tracks the shell.
- **Scale mismatch:** `tropicalhouse.pop` in an A minor session plays C major chords and reports the relative key.
- **Intents (O2):**
  - `darker` from A minor goes to A phrygian, and is idempotent at the floor (the result says so)
  - `darker` with no `how` applies `harmonic`, sends no `filter_freq` CC and reports `applied: ["harmonic"]` with the other options (Q-H3)
  - `darker` with `how: "timbral"` sends `filter_freq` on melodic tracks only, never on a drum, cymbal or fx channel; `how: ["harmonic", "register"]` changes the mode and moves the lead down an octave, within 41-79
  - `whiplash_undo` after each restores the progression, the CC values and the lead register
  - `brighter` after `darker` with `timbral` never opens past the value before the first step
  - `tension` then `release` brings the exact previous progression back
  - every result lists what it did
- **Key lock:** `write_part(track: 7, notes: ["C#5"])` in A minor plays C5 (`bar_events`) and reports `snapped`. With `out_of_key: true` it plays C#5. A kick part's note 60 is never moved.
- **Key-only `set_progression` (O2):** with `pretend_playing`, the key changes exactly on the next bar line. Drum notes are unchanged, the bass median stays 53 or more, and a Roman-numeral progression is re-voiced.
- **Clock safety:** a jitter check (`scripts/clock_jitter.py --calls`) shows no added lateness at the bar line with a library progression and `pedal` running.
- **Budget tests** updated to the phase's caps.

---

## 4. Layer 2: Groove library

### 4.1 What exists, and the gap

**Exists:**
- `patterns.py`: five genre patterns of 4 × 16 steps, with per-step velocity lambdas (the deep house hat 58/48/40, the techhouse shuffle 84/62/44) and a swing per pattern (0.50-0.58).
- `parts.RHYTHMS`: seven named rhythms (`four_on_floor`, `offbeat_8ths`, ...).
- `mutate.py`:
  - role-based fills (`FILL_SHAPES`: kick sits out, snare roll, clap push, 32nd hat ratchets)
  - density through `thin` and `thicken`, ranked and seeded
  - `humanize`: at most ±16 velocity and ±0.25 tick
- The working hit `(step, note, velocity, gate_steps, offset_ticks)` already carries a per-hit timing offset, which the sequencer plays as `t0 + offset * tick_len` (`Engine._run`).
- Swing is global: every odd 16th of every track moves by `(swing - 0.5) * 2 * sixteenth`.

**Gap:**
1. A genre is **one fixed drum layer.** There are no alternatives, no energy levels, and no per-role lanes to mix.
2. **Velocity shapes are lambdas inside the patterns.** They aren't named or reusable.
3. **Microtiming is only random** (humanize). No laid-back clap, no early hat, though the research treats both as the groove (research §1, §2, §3).
4. **One fill per role.** No fill variants.

### 4.2 Data model: `grooves.py` (new, pure tables)

```python
@dataclass(frozen=True)
class Lane:                # one role's part, reusable across grooves
    name: str              # "hat.offbeat_shuffle"
    role: str              # a kitmap.ROLES drum role: kick, snare, rim, clap, closed hat, open hat, cymbal, perc
    grid: tuple            # 1, 2 or 4 bars of 16 cells: x hit, X accent, g ghost, . rest (parts.parse_grid_bar + g)
    velocity: object       # a curve name (VELOCITY_CURVES) or 16 ints 1-127
    micro: tuple = ()      # 16 offsets in clock ticks, -3..+3 (0 = on the grid); () = none
    gate: float = 1        # steps
    tags: frozenset = frozenset()
    source: str = ""
    about: str = ""

@dataclass(frozen=True)
class Groove:              # a drum kit's feel at five energy levels
    name: str              # "deephouse.shuffle"
    aliases: tuple         # ("deephouse.A",) for the classic grooves only
    genre: str             # a genres record name
    swing: float           # 0.50-0.62, becomes Pattern.swing
    levels: dict           # energy 1..5 -> {role: lane name}; each level lists its full set (not deltas)
    fills: dict            # role -> fill name (FILLS), default the v0.6.1 shapes
    tags: frozenset
    source: str
    about: str
```

- **Names are descriptive; letters are aliases** (Q-G1). Only the grooves that are today's patterns get a letter: `deephouse.classic` = `deephouse.A`, and likewise `techhouse.classic`, `techno.classic`, `soul.classic` and `breaks.classic`. A bare `groove: "A"` takes the genre's classic.
- **Classic grooves are today's patterns, bit for bit** at energy 3, and carry no `micro` table at any level, so `play_pattern(genre: "deephouse")` and `groove: "deephouse.A"` sound exactly as today. Microtiming is on by default in **every other groove** (Q-G2).
- **Energy levels** share one meaning across genres:

| Energy | Meaning |
| --- | --- |
| 1 | kick and one hat (an intro or outro feel) |
| 2 | adds the backbeat (clap, rim or snare) and the closed hat |
| 3 | the genre's full groove (a classic groove's level 3 is today's pattern) |
| 4 | more hits, accents and ghosts on the same elements; 16th hats where the genre allows |
| 5 | the busiest form: doubled or jacked backbeat, extra open hats, one added element only if the genre's busy cap allows |

  **Energy above 3 adds hits before it adds elements, and no level ever passes the genre's `busy_drums` cap** (§7.2), which is an integrity test. Today's patterns sit within their caps (deep house 5 drum tracks, techno 6, tech house 6).
- **Velocity curves** (`VELOCITY_CURVES`), named from what the patterns already do:
  - `flat`
  - `beats` (120 on 0/4/8/12, 90 between, as `parts.ACCENT`)
  - `offbeat_lift`
  - `shuffle` (the techhouse 84/62/44)
  - `deep_hat` (the deep house 58/48/40)
  - `crescendo` (rises over the bar)
  - `ghosted`: an accent at 100-115, `g` cells at `GHOST_VEL`
  - `soft`: rounded transients, kick near 96 (tropical, §7)
- **Ghost notes** (Q-G4): `GHOST_VEL = (28, 40)`, one constant in `grooves.py`; each `g` cell takes a seeded value in that range. The research calls velocity variation and ghosts mandatory in house, tech house and minimal (research §2, §3, §6). If Phil hears nothing under VELOCITY TO VOL, the constant moves to (40, 55) in one place (**HW**, §8 HW O-2).
- **Microtiming** (Q-G2):
  - One clock tick is 60 / (BPM × 24) s: about 20.5 ms at 122 BPM. So the useful offsets are fractions of a tick.
  - **Positive offsets play as they do today.**
  - **Negative offsets** can't be played in place: a step's notes are queued at that step's tick, so a negative offset would sound late, at the tick. The lane compiler therefore moves a negative offset to the previous step with offset `6 + micro`, inside the same bar. On step 0 it is clamped to 0 and reported (`pushed_downbeat_clamped`).
  - This is data work in the tool thread. The sequencer doesn't change.
  - `humanize` adds on top, and `humanize: 0` leaves the table as written.
  - **HW:** are these offsets audible above USB jitter? (§8, HW O-1)
- **Per-lane swing:** hats swinging more than the kick is expressed as `micro` on odd steps, on top of the global swing. No per-track swing goes into the sequencer.
- **Fills** (`FILLS`):
  - the five existing shapes from `mutate.fill`, named `kick.sit_out`, `snare.roll`, `clap.push`, `hat.ratchet` and `open.clear` (perc reuses `clap.push` and cymbal `open.clear`, as `FILL_SHAPES` does today)
  - new: `snare.flam_roll`, `kick.double` (14 and 15), `hat.open_choke`, `perc.tom_run`
  - `perc.tom_run` uses notes 60, 57 and 53 on one perc track, inside the v0.5 floor. It is pitched, so it only plays on a perc track whose line is note 60. House uses it every 8 bars (research §2: simple tom rolls every 8), falling back to `snare.roll` when no perc track is labelled.

#### 4.2.1 Lanes (shared)

| Lane | Role | Pattern | Micro | Source | Phase |
| --- | --- | --- | --- | --- | --- |
| `kick.four_floor` | kick | every beat | 0 | all | O1 |
| `kick.last_offbeat` | kick | four on the floor plus step 14 | 0 | §2 Attack | O1 |
| `kick.ghost_mid` | kick | four on the floor plus a ghost on step 7 | 0 | §2 Attack | O1 |
| `clap.2_4` | clap | steps 4, 12 | 0 | all | O1 |
| `clap.2_4_ghosted` | clap | 4, 12, ghosts on 7 and 15 | +0.75 on 4/12 | §1 SONAA (10-20 ms late) | O1 |
| `clap.jacked` | clap | 4, 12 and the last 16th (15) | +0.5 | §2 Attack (late or jacked clap) | O1 |
| `snare.2_4` | snare | 4, 12, layered under the clap | 0 | §3 TPS (layered clap/snare) | O1 |
| `clap.every_other_bar` | clap | 2 bars: 4/12 in bar 2 only | 0 | §6 TPS | O3 |
| `rim.bossa` | rim | syncopated 3-3-2 | 0 | **by ear** | O1 |
| `rim.syncopated` | rim | 3, 6, 11 (plus 14 at energy 5) | 0 | §2 Attack (syncopated rim or cowbell) | O1 |
| `rim.on_3` | rim | step 8 | 0 | §4 BeatKey | O3 |
| `rim.sparse_2_4` | rim | 4, 12 at low velocity | +0.5 | §6 Attack | O3 |
| `hat.closed_8ths` | closed hat | every 8th, `deep_hat` | +0.25 on odd 8ths | §1 TPS (8ths, not 16ths) | O1 |
| `hat.closed_16ths` | closed hat | every 16th, `shuffle` | 0 | §2, §8 | O1 |
| `hat.offbeat_shuffle` | closed hat | 16ths, `deep_hat`, ghosts | +0.25 on odd steps | §1 SONAA, BeatKey (54-60%) | O1 |
| `hat.push_16ths` | closed hat | every 16th, accented | −0.25 | §3 Mix Elite (hits just before the beat) | O1 |
| `hat.offbeat_open` | open hat | 2, 6, 10, 14 | 0 | all | O1 |
| `perc.shaker_16` | perc | 16ths, ghosted | +0.25 | §1, §7 | O1 |
| `perc.conga_offbeats` | perc | offbeats, soft | +0.5 | §1, §6 Attack | O1 |
| `perc.rolling` | perc | between the kicks (3, 6, 11, 14) | 0 | §5 Schunk | O1 |
| `perc.woodblock` | perc | 7, 15 accents | 0 | §3 TPS | O1 |
| `perc.poly3` | perc | every 3rd step over a 4-bar grid (64 cells). 64 isn't a multiple of 3, so it resets every 4 bars: an approximation of 3-against-4 | +0.25 | §6 Brizm (polymeter) | O3 |
| `perc.bongo` | perc | 3, 7, 10, 14, soft | +0.25 | §7 Melodigging | O3 |
| `hat.shaker_16` | closed hat | ghosted 16ths for a shaker sample on the closed-hat track | +0.25 | §7 Melodigging, Splice | O3 |

#### 4.2.2 Grooves, all eight genres

Each row is the groove at energy 3. Levels 1-2 strip it down and levels 4-5 add hits, as in the energy table. Starting points by ear on top of the research; Phil hears them in §8.

| Groove (alias) | Genre | Swing | Energy 3 lanes | Fills | Source | Phase |
| --- | --- | --- | --- | --- | --- | --- |
| `deephouse.classic` (`deephouse.A`) | deephouse | 0.55 | today's pattern | v0.6.1 | existing | O1 |
| `deephouse.shuffle` | deephouse | 0.56 | `kick.four_floor`, `clap.2_4_ghosted`, `hat.closed_8ths`, `hat.offbeat_open`, `perc.conga_offbeats` | `snare.roll` | §1 | O1 |
| `house.jack` | house | 0.52 | `kick.four_floor`, `clap.jacked`, `hat.closed_16ths`, `hat.offbeat_open`, `rim.syncopated` | `perc.tom_run` every 8 | §2 Attack, SONAA | O1 |
| `house.eighths` | house | 0.50 | `kick.last_offbeat`, `clap.2_4`, `hat.closed_8ths`, `hat.offbeat_open`, `rim.syncopated` | `perc.tom_run` | §2 Attack | O1 |
| `techhouse.classic` (`techhouse.A`) | techhouse | 0.56 | today's pattern | v0.6.1 | existing | O1 |
| `techhouse.rolling` | techhouse | 0.53 | `kick.four_floor`, `clap.2_4` + `snare.2_4` (layered), `hat.push_16ths`, `hat.offbeat_open`, `perc.shaker_16`; energy 5 adds `perc.woodblock` on a second labelled perc track (else `unplaced`) | `kick.sit_out` (last bar of a build) | §3 Mix Elite, TPS | O1 |
| `techno.classic` (`techno.A`) | techno | 0.50 | today's pattern | v0.6.1 | existing | O1 |
| `techno.rolling` | techno | 0.50 | `kick.four_floor`, `hat.offbeat_open`, `perc.rolling`, `clap.2_4` (from energy 3), `hat.closed_16ths` (from energy 4) | `kick.sit_out` | §5 Schunk, Beatportal | O1 |
| `progressivehouse.functional` | progressivehouse | 0.50 | `kick.four_floor`, `clap.2_4`, `hat.closed_8ths`, `hat.offbeat_open`, `rim.on_3` | `snare.roll` | §4 BeatKey | O3 |
| `melodictechno.stripped` | melodictechno | 0.50 | `kick.four_floor`, `clap.2_4`, `hat.closed_16ths`, `perc.shaker_16`, `rim.sparse_2_4` | `snare.roll` | §8 NI, Soundtrap | O3 |
| `minimal.house_shuffle` | minimal.house | 0.57 | `kick.four_floor`, `perc.conga_offbeats`, `rim.sparse_2_4`, `clap.every_other_bar` | `hat.open_choke` | §6 Attack, TPS | O3 |
| `minimal.techno_kick` | minimal.techno | 0.53 | `kick.four_floor`, `hat.offbeat_open`, `rim.sparse_2_4`, `perc.poly3` | `kick.sit_out` | §6 Brizm, Schunk | O3 |
| `tropicalhouse.soft` | tropicalhouse | 0.53 | `kick.four_floor` (`soft`), `clap.2_4`, `hat.shaker_16`, `hat.offbeat_open`, `perc.bongo` | `snare.roll` | §7 Melodigging, Splice | O3 |
| `soul.classic` (`soul.A`), `breaks.classic` (`breaks.A`) | soul, breaks | existing | today's pattern, level 3 only | v0.6.1 | existing | O3 |

`soul.classic` and `breaks.classic` have one level. `mutate energy` on them says "soul.classic has one energy level (3); pick a genre with levels" and changes nothing.

### 4.3 Tools

- **`whiplash_play_pattern`** gains:
  - `groove: "deephouse.shuffle"`, `"shuffle"` or `"A"`. A bare name takes the genre's groove; a full name also picks the genre (`groove: "house.jack"` plays classic house).
  - `energy: 1-5` (default 3).
  - With a beat playing, either one queues a switch on the next bar line, as genre does now.
  - The result adds:
    - `groove: {name, energy, lanes: {role: lane}, swing}`
    - `unplaced`: roles with no track, see §4.4
- **`whiplash_mutate(action: "energy", amount: 1-5 | "up" | "down")`** (Q-G3): the same groove at another level, from the next bar. In forms, energy is a section key (§6). There is no separate perform verb.
- **`whiplash_write_part`** gains `groove: "hat.offbeat_shuffle"` as a sixth placement, exclusive with `rhythm`, `grid`, `steps`, `hits` and `lock_to`.
  - It brings its own velocities and microtiming, and notes default to 60.
  - The result adds `{lane, micro, velocity_curve}`.
- **`whiplash_mutate(action: "fill", fill: "snare.flam_roll")`** gets named fills (`fill: true` keeps today's behaviour). Arrangement sections accept a name for `fill` too.
- **Failure hints:**
  - unknown groove or lane: closest matches, and `whiplash_list_library(kind: "groove", genre: ...)`
  - `energy` without a groove: "energy needs a groove; try groove: 'A'"
  - `energy up` at 5: "already at energy 5"
  - a lane's role on a melodic track: refused as fills are ("lane clap.2_4_ghosted is a clap part; track 6 is labelled bass")

### 4.4 Scheduler and tracks

- **A groove plus an energy level compiles, in the tool thread, into an ordinary `patterns.Pattern`.** It keeps the genre's melodic tracks and takes the groove's drum lanes, with `swing` from the groove, `key` from the genre and `name` like `deephouse+shuffle@3`. Everything downstream is unchanged:
  - `patterns.register`, `harmony.in_key`, `kitmap.route` (lanes go to labelled tracks by role, with the same preferences and `CLOSE` fallbacks)
  - density, fills, the progression, `whiplash_arrange` group words
- **Default tracks for lane roles** follow the existing layout: kick 1, snare or rim 2, clap 3, closed hat 4, open hat 5, perc 8 (where the genre puts it).
  - A lane role with no default and no labelled track, such as a shaker on a kit without a perc label, isn't played. It is reported under `unplaced`, like kitmap's `dropped`, never silently.
  - Tracks 9-16 get lanes only when labelled, as now.
- **Written parts win their track,** as now (`kitmap.plan` "replaced").
- **Energy change:** the new pattern is prepared in the tool thread and swapped in at the bar line through the `_reroute` path (`Engine._reroute`, which keeps swing, humanize and density), not the switch path, which resets mutations.
  - Mutes, ramps, written parts, the progression and the arrangement carry over.
  - The per-bar cost is the same as a relabel today.
- **Microtiming** uses the existing `offset_ticks`. `humanize` adds on top, as now.

### 4.5 Test plan

- **Library integrity:**
  - every lane's grid parses (16 cells, 1/2/4 bars), velocities are 1-127 and micro is −3..+3
  - every groove level names known lanes, at most one lane per role, and every role is a `kitmap.ROLES` drum role
  - levels 1-5 exist and get busier: hits per bar don't decrease
  - no level of any groove uses more drum tracks than its genre's `busy_drums` cap
  - classic grooves have no `micro`
- **Equivalence (demo-safe):** `deephouse.classic` and `deephouse.A` at energy 3 yield the same drum events as today's `deephouse` (`bar_events` on bars 0-3), and so do `techhouse.classic` and `techno.classic`. `play_pattern(genre: "deephouse")` with no groove is unchanged.
- **Micro:** `clap.2_4_ghosted` plays with offset +0.75 tick; a −0.25 offset on step 6 lands on step 5 at offset 5.75. Check note-on times with `pretend_playing` and a recording port. `humanize: 0` leaves the table exact.
- **Ghosts:** every `g` cell plays in `GHOST_VEL`.
- **Routing:** with `label_tracks({"9": "kick"})` the kick lane plays on 9 only, and a shaker lane with no perc track shows in `unplaced`.
- **Energy change:** lands on the next bar line, keeps humanize, density and mutes, and sends no extra Stop or Start.
- **Fills:** each named fill on its role, and refused on a melodic line, as `mutate.fill` is; `perc.tom_run` falls back to `snare.roll` with no perc track.
- **Aliases:** `resolve("house")` is deephouse; `"chicago"`, `"chicago house"` and `"classic house"` are house; the mood `"peak time"` and `"peak time techno"` are techno; `"peak time tech house"` is techhouse. (O3 adds: bare `"minimal"` is `minimal.house`.)
- **Rehearsal:** the default `scripts/rehearse_demo.py` run is unchanged (no groove argument) and prints `RESULT: PASS`.

---

## 5. Layer 3: Phrase generators

### 5.1 What exists, and the gap

**Exists:**
- `parts.build` writes a line from a rhythm and notes (names, MIDI numbers, or scale degrees with a key), into the working hit shape.
- `harmony.apply` modes reshape any line per bar against the chord: `root` (a whole bass line on the chord root), `snap` and `chords`.
- `jam.reply` (v0.8.0) turns a phrase into an echo, answer or harmony, in key and register (`jam.fit_register`: median 53-72).

**Gap:** nothing writes a musical line from the chords. A bass in `root` mode plays one pitch per bar on the pattern's rhythm, so the line is the root note. A model asked for "a walking bass" or "an arp" has to compute every note against every chord, and can't follow a progression it didn't write.

### 5.2 Data model: `phrases.py` (new, pure) and `harmony.Rel`

- **Chord-relative notes.** A phrase's hits carry a `harmony.Rel` instead of a plain note number:
  - It is a small `int` subclass with `.tone` (`R`, `3`, `5`, `7`, `9`, `oct`, `step+n`, `step-n`, `approach`) and `.octave` (−1..+2). `step±n` counts scale steps from the chord root.
  - Its integer value is the note it plays against the key's tonic chord. So anything that doesn't know about it still sees a sensible note in 16-84: `mutate.fill`'s melodic check, `mutate.thicken`'s ghost copy (which keeps the object), the view, status.
  - The engine's transpose (`clamp_note(note + shift)`) runs after `apply()`, so it is never applied to a `Rel`.
- **A new `harmony.apply` mode, `phrase`.** For each hit it resolves `Rel` against the chord playing: chord-tone index into the voiced chord, then `harmony.nearest(pc, anchor)` around the phrase's register anchor.
  - A missing tone (a 7th on a triad) falls to the nearest chord tone.
  - `approach` needs the next chord: one more `prog.index(bar + 1)` lookup.
  - With no progression it resolves against the key's tonic chord (a triad, or a 7th for a 7th-flavoured generator).
  - This is per-hit lookup work, like `chords` and `root`, at most 64 hits per track per bar.
- **Generators:**

```python
@dataclass(frozen=True)
class Phrase:
    name: str            # "bass.octave_pump"
    role: str            # bass | lead | stab | chord | pad (kitmap.MELODIC)
    grid: tuple          # 1, 2 or 4 bars of 16 cells (x, X, g as in lanes)
    tones: tuple         # per hit, cycled: "R", "R+12", "5", "b7", "approach", "step-1", ...
    order: tuple         # 16 step ranks: which hits go first as density falls
    register: str        # low (anchor 53-57) | mid (60-64) | high (67-72)
    length: float        # steps
    velocity: object     # curve name or ints, as lanes
    variation: str       # none | seeded (rng picks tones per bar) | motif (A A' B A'' over 4 bars)
    on_request: bool     # True: never a genre default (leads, Q-P3)
    tags: frozenset
    source: str
    about: str
```

#### 5.2.1 Phrase library

| Phrase | Role | Shape | Default for | Source | Phase |
| --- | --- | --- | --- | --- | --- |
| `bass.rolling_deep` | bass | R on 0 (gate 3), R 3, 5 on 6, R on 8 (gate 3), oct 11, 5 on 14; sustained, light | deephouse (recommended) | §1 BeatKey, TPS, SONAA (rolling, root with 5th and octave passing tones) | O1 |
| `bass.octave_pump` | bass | 8ths: R on the beat, R+12 on the off-beat, gate 1 | **house only** (Q-P4) | §2 SONAA (the Chicago octave bounce) | O1 |
| `bass.bouncy` | bass | short 16ths around the off-beat (2, 3, 6, 10, 11, 14): R R R R oct R, rests between | techhouse (recommended) | §3 Mix Elite, TPS | O1 |
| `bass.offbeat` | bass | R on 2, 6, 10, 14; at density 1 also 3, 7, 11, 15 (rolling) | techno (recommended), minimal.techno | §5 Schunk, §6 Brizm | O1 |
| `stab.offbeat` | stab, chord | the chord on 2, 6, 10, 14, short, never on the kick downbeat | house; techhouse and techno at density 0.25; progressivehouse grooves | §2 MusicRadar, Attack | O1 |
| `bass.root_follow` | bass | R on 0 and 8, long gates, following the chord | progressivehouse | §4 BeatKey | O3 |
| `bass.rolling_16` | bass | 16ths off the kick steps on R, one accent 5; moves when the chord moves | melodictechno | §8 NI | O3 |
| `bass.stab_sparse` | bass | one or two short notes per bar (R on 3, oct on 11 in bar 2) | minimal.house | §6 TPS | O3 |
| `bass.round_sub` | bass | R on 0 and 8, short decay; R on 11 at density 1 | tropicalhouse | §7 Melodigging | O3 |
| `bass.descending_walk` | bass | 4 bars, one held note each over a held tonic: R, step−1, step−2, step−3 (A G F E in A minor) | `progressivehouse.descending` | §4 BeatKey (the Prydz-like Am–Am/G–Fmaj7–E7 bass) | O3 |
| `bass.walking` | bass | quarters R, step, 3 or 5, approach | — | **by ear** | O3 |
| `stab.single` | stab | one short chord hit per bar (step 6), seeded variation in bar 4 | minimal.house | §6 Brizm (a single stab) | O3 |
| `pad.hold` | pad, chord | the existing `harmony.pad_line`, named | melodictechno, tropicalhouse, progressive breakdowns | existing | O3 |
| `arp.chord_up`, `arp.chord_updown`, `arp.chord_seeded` | lead | chord tones on 16ths or 8ths, 1-2 octaves | — | **by ear** | O3 |
| `lead.stutter` | lead | short repeated chord tone on 16ths (x x . x pattern), following the chords | on request (melodictechno) | §8 NI (short stutter notes) | O3 |
| `lead.pentatonic_hook` | lead | a seeded 2-bar pentatonic hook | on request (tropicalhouse) | §7 Melodigging, Splice | O3 |
| `melody.motif` | lead | a seeded one-bar motif of chord tones on 0/4/8/12 and scale steps between; bar 2 repeats it, bar 3 sequences it up a step, bar 4 answers it and ends on R (`jam.reply`'s `answer` idea) | on request | **by ear** | O3 |

- **Leads stay model-written by default, with key lock** (Q-P3). `lead.*` and `melody.motif` are `on_request` and never a genre default.
- **Controls:**
  - `seed`: any int or word, through `mutate.rng(seed, "phrase", name, bar)`. It is deterministic across runs, as mutate is.
  - `density`: 0-1, keeping the top hits by `order`. 1 means every hit in the grid.
  - `register`: low, mid or high, or an anchor note. The final line goes through the v0.5 rule (median 53 or more, notes in 16-84), as `patterns.register` and `jam.fit_register` do.
  - A one-voice audio track plays an arp one note at a time, which is what an arp is.

### 5.3 Tools

- **`whiplash_write_part`** gains `phrase: "bass.octave_pump"` (or `"genre"`: the genre record's default for that track's role), with `density`, `seed` and `register` (Q-P1).
  - `phrase` is exclusive with the placements and with `notes`. It supplies both.
  - The result is a `parts.Part` in every respect: kit-map routing ("written parts win"), `whiplash_undo`, `whiplash_stop` clearing it, transpose, density, fills (melodic lines are left alone) and drops all work unchanged.
  - **A phrase on the bass track replaces the genre's bass** (Q-P2), as any written part does. To layer, name another track.
  - The part's track gets mode `phrase` in `Engine._prog_modes`, also when no progression plays, so it follows `set_progression` and key changes from then on.
  - The result adds `{phrase, follows: "progression" | "key", now: <the bar as it sounds on the current chord>, register}`.
  - **Failure hints:**
    - unknown phrase: closest matches, and `whiplash_list_library(kind: "phrase", tag: "bass")`
    - a phrase on a drum, cymbal or fx track: refused, as `set_progression` refuses
    - `phrase` together with `notes`: "phrase brings its own notes; drop notes, or use rhythm + notes"
- **Genre defaults appear without being asked:** compiled genres (house in O1, the O3 four) build their bass and chord tracks from the record's phrases (§1.2), so the right line plays from `play_pattern` alone.

### 5.4 Scheduler and tracks

- **The phrase is built in the tool thread,** like any written part (`Engine._parts`, then `_rebuild`).
- **At the bar line the only new work is the `phrase` branch of `harmony.apply`:** per hit, one lookup into the voiced chord and one `nearest()`.
- **Roles:** bass phrases go to a bass-role track (labelled, else track 6), arps and melodies to a lead track, and stab or pad phrases to chord tracks (with ranks, as `chords` mode does).
- **Tracks 9-16** take phrases when named explicitly (`track: 10`). `channel_note` is passed on as now.

### 5.5 Test plan

- **Pure:**
  - `Rel` arithmetic and hashing
  - `phrase` mode resolution against every library progression in all keys: medians at 53 or more, every note in 16-84, a seeded line identical across runs
  - `approach` lands one step from the next root
  - `bass.descending_walk` over `progressivehouse.descending` in A minor plays A, G, F, E on bars 1-4
  - density 0.25 keeps the four highest-ranked hits
  - no `on_request` phrase is any genre's default
- **Engine:**
  - `write_part(track: 6, phrase: "bass.octave_pump")` and then `set_progression(name: "house.uplift")`: track 6's notes on each bar are the chord's root and octave (`bar_events`, with A, F, C and G roots at 2 bars each)
  - a key-only `set_progression(key: "Fm")` moves them (O2)
  - `whiplash_undo` brings the previous line back on the bar
  - a `thicken` ghost on a phrase keeps a `Rel` and resolves
  - `play_pattern(genre: "chicago")` plays `bass.octave_pump` on track 6 and `stab.offbeat` on the chord tracks with no further call
- **Refusals:** a phrase on a kick-labelled track. Nothing changes (`status` before and after are equal).

---

## 6. Layer 4: Arrangement grammar

### 6.1 What exists, and the gap

**Exists:**
- **`arrange.py` (v0.6.1-2):**
  - sections: name, bars (at most 64; 16 sections, 512 bars in all), tracks or mute (group words), drop, fill on the last bar, chords, ramps, transition, `transition_bars`, `filter_from`, mix
  - presets `club` and `short_demo`, with the build's rising filter as `_build_ramp`
  - `resolve()` maps group words onto the roles playing at each section's first bar
  - the engine schedules sections through `_arrange_step` and `_enter_section`, with no new clock path
- **`transition.py`:** `cut`, `filter_swap`, `drop_swap` and `riser`, from existing ramps, drops and fills.
- **The roadmap's later theme:** "Macros and performance moves: build-up, breakdown and slam as one-call presets."

**Gap:**
1. A section lists its tracks and ramps by hand. **There is no section type with defaults** (what a breakdown is) **and no energy level.**
2. **Fills happen only on a section's last bar.** There's no "a fill on the last bar of every 8".
3. **Tracks can't enter mid-section** ("hats in at bar 16").
4. **No one-call intent while a beat plays** ("build to the drop in 16 bars").
5. **An arrangement either stops or loops at its end.** There's no "then keep playing".
6. **A breakdown means the same in every genre,** but the research says it doesn't (research §1-8).

### 6.2 Data model: `form.py` (new, pure; compiles into `arrange` sections)

- **Section types** (`SECTION_TYPES`), each a template of existing section keys plus `energy`:

| type | energy | default bars | what plays | built from |
| --- | --- | --- | --- | --- |
| `intro` | 1 | 16 | kick, hats (drums only, research shared norms) | fill_every 8 |
| `groove` | 3 | 16 | all | fill_every 8 |
| `build` | rising 2→4 | 8 | kick, hats, perc, music | `_build_ramp` when the energy filter is on (A1), kick drop on the last bar, `snare.roll` fill, `enter: {hats: -4}` |
| `breakdown` | 2 | 16 | by the genre's breakdown style (below) | |
| `drop` | 5 | 16 | all | fill_every 8, optional `mix` |
| `outro` | 1 | 16 | kick, hats, perc | thins out: density −0.3 on hats in the last 8 |

- **Breakdown styles** (`BREAKDOWNS`, Q-A3), set by the genre record:

| Style | Does | Genres | Source |
| --- | --- | --- | --- |
| `kick_bass_out` | kick and bass muted, chords and hats stay | deephouse, progressivehouse, melodictechno | §1, §4, §8 |
| `kick_drop` | kick muted, bass stays | techno | §5 TrackSensei, Schunk |
| `filter_low_end` | bass `filter_freq` closes to 40 over 2 bars and reopens at the next section (owner `arr`) | techhouse | §3 Mix Elite |
| `filter_bass` | as `filter_low_end` | house, soul, breaks (the old default) | §2 (**by ear**) |
| `reduce_drums` | groove energy 1, hook and chords stay | tropicalhouse | §7 Splice |
| `subtract_one` | the busiest non-kick element muted for the section | minimal.house, minimal.techno | §6 Schunk |

- **Energy** (`ENERGY`), 1-5. Each level sets:
  - the groove level (layer 2), when a groove plays
  - the groups that play, when the section gives no `tracks`
  - a music-filter target **only when opted in** (`energy_filter: true`), because a ramp leaves the kit's cutoff changed until it is reloaded, as the build already does (Q-A1). Forms default it on only for `progressive_journey` and `melodic_journey` (research §4: the filter is the performance; research §8).
- **Form strings:** `"intro 16, groove 16, build 8, drop 16, breakdown 8, drop 16, outro 16"`, or a library name. They compile to an `arrange.sections()` list. Each `type bars` item takes its type's defaults, and later keys override them. **A section whose length isn't a multiple of 8 gets a warning, never a refusal** (Q-A4; research shared norms: DJs count in 8, 16 and 32).
- **New section keys,** validated in `arrange.section`:
  - `energy` (1-5, or `"rising"`)
  - `fill_every` (N bars, with the fill on the last bar of each N)
  - `enter` / `exit`: `{group: bar}`, a bar within the section; negative counts from its end
  - `fill` accepts a fill name (layer 2)
- **New arrangement option `then: "stop" | "loop" | "continue"`:**
  - **Forms default to `stop`**, today's `loop: false` (Q-A4).
  - `loop` is today's `loop: true`.
  - `continue` ends the arrangement like `clear: true` (unmute what it muted) and keeps the beat playing. **Moves default to it.**

#### 6.2.1 Forms, one per genre

| Form | Genre | Sections (type bars) | Fills | Energy filter | Source |
| --- | --- | --- | --- | --- | --- |
| `deephouse_dj` | deephouse | intro 32, groove 32, breakdown 16, groove 32, outro 32 | fill_every 16 (add or remove something every 16) | off | §1 BeatKey, TPS |
| `house_jack` | house | intro 16, groove 32, breakdown 16, groove 32, outro 16 | fill_every 8 (`perc.tom_run`) | off | §2 SONAA |
| `techhouse_dj` | techhouse | intro 32, build 16, drop 32, breakdown 16, build 8, drop 32, outro 32 | fill_every 8; kick out on the last bar of each build | off | §3 Mix Elite, Abletonic |
| `techno_plateau` | techno | intro 32, build 16, groove 32, breakdown 16, groove 32 (one new element: `enter`), outro 32 | fill_every 16 | off | §5 TrackSensei, Schunk |
| `progressive_journey` | progressivehouse | intro 32, build 16, groove 32, breakdown 32, build 16, drop 32, outro 32 | fill_every 8; the last beat before each drop nearly empty | **on** (filter over 16-32 bars) | §4 BeatKey, WMDM, Myloops |
| `melodic_journey` | melodictechno | intro 32 (kick and bass, filtered), breakdown 16, build 8 (the drop previewed filtered), drop 32, breakdown 16, drop 32, outro 16 | kick out on the last bar of each build (a moment of space) | **on** | §8 NI, Soundtrap |
| `minimal_long` | minimal.house, minimal.techno | intro 32, groove 64 (`enter`/`exit` one element every 16), breakdown 16, groove 64, outro 32 | none; change is entries and exits | off | §6 Schunk, TPS, Brizm |
| `tropical_song` | tropicalhouse | intro 16, groove 16 (energy 2), breakdown 8 (the pre-chorus lift), drop 16 (energy 4: a hook, not a festival drop), groove 16, breakdown 8, drop 16, outro 16 | fill_every 8 | off | §7 Splice, Melodigging |
| `club`, `short_demo` | any | unchanged presets | | | existing |

Every form is within `arrange`'s limits (64 bars per section, 16 sections, 512 bars).

- **Moves** (`MOVES`) for `whiplash_arrange(move, bars)`. Each compiles to a short arrangement with `then: "continue"`, or to existing calls:

| move | compiles to |
| --- | --- |
| `build` (bars N, default 8) | a `build` section of N bars, then the drop below |
| `drop` | all in on the next bar (energy 5, `mix` recall if a "drop mix" is saved), crash on a labelled cymbal |
| `breakdown` (N, default 16) | a `breakdown` section of N bars in the genre's style |
| `slam` | one bar of everything dropped except fx, then all in with a fill |

  Energy up and down is `mutate(action: "energy")`, and darker, brighter, tension and release are `set_progression(intent)`, so they are not moves.
- **"Build to the drop in 16 bars"** = `whiplash_arrange(move: "build", bars: 16)`. It compiles to:
  - build: 16 bars, `enter: {hats: -4}`, a kick drop on bar 16, a `snare.roll` fill on bar 16, and the music filter 20→127 exp over 16 when the genre's energy filter is on
  - then a drop of 16 bars at energy 5 with `fill_every: 8`
  - `then: "continue"`

### 6.3 Tools

- **`whiplash_arrange`** gains:
  - `form`, a string or a library name, exclusive with `sections`, `preset` and `move`
  - `move` and `bars`, exclusive with the others
  - `then`
  - the section keys `energy`, `fill_every`, `enter` and `exit`

  The `club` and `short_demo` presets are unchanged.
  - **A move while an arrangement runs replaces it from the next bar** (Q-A2). The result names it (`replaced_arrangement`), and `whiplash_undo` brings it back, because arrangements are already undoable (v0.8.0).
  - Result for a move: `{move, lands_at_bar, sections: [...], then, replaced_arrangement?}`.
  - **Failure hints:**
    - unknown section type or move: lists them
    - `enter` past the section's end: "bar 20 is outside build (8 bars)"
    - a form over `TOTAL_BARS_MAX` (512): says the total
    - a move with nothing playing: "start a beat first"
  - **Warnings** (not errors): a section length that isn't a multiple of 8.

### 6.4 Scheduler and tracks

- **Forms, types and moves compile in the tool thread** into the `arrange.Section` tuple that `_arrange_step` and `_enter_section` already run. Ramps, fills, drops, mutes, mixes and progressions are all scheduled as now (owner `arr`).
- **New per-bar work** in `_arrange_step`, for the running section only:
  - one modulo for `fill_every`
  - one dict lookup for `enter` / `exit` (unmute or mute a resolved group at that bar)
  - `then: "continue"` runs the existing clear path instead of returning `None` (stop)
- **Group words resolve from roles at each section's first bar,** as now (`arrange.resolve`), so forms survive relabels and pattern switches. `subtract_one` resolves the busiest non-kick group at that bar.

### 6.5 Test plan

- **Pure:**
  - every form in the library compiles to valid sections (`arrange.sections` accepts them), and every section length is a multiple of 8
  - `"intro 16, build 8, drop 16"` gives the expected `tracks`, `ramps`, `drop` and `fill` per section
  - a 12-bar section warns and still compiles
  - `move: "build", bars: 16` produces the sections above, with the filter ramp only where the genre's energy filter is on
  - each breakdown style mutes or ramps what its row says
- **Engine (`pretend_playing` at 4x):**
  - `fill_every: 8` fills bars 8 and 16 of a 16-bar section and no others
  - `enter: {hats: -4}` unmutes the hats exactly at bar 13 of 16
  - `then: "continue"` keeps the beat running after the last section, with every arrangement mute lifted and no MIDI Stop sent
  - a move while an arrangement runs, then `whiplash_undo`: the old arrangement resumes in the right section
  - a techno breakdown mutes the kick and keeps the bass; a tech house one sends `filter_freq` on the bass track only
- **Rehearsal:** `--v061` still passes, and the presets play bar for bar as before.

---

## 7. Layer 5: Taste guardrails

### 7.1 What exists, and the gap

**Exists:**
- `whiplash_status`: pattern, key, chords, section, mutations, ramps, per-track state, `play_along.user_moves` (the user's last 8 moves), `undo` (the last four undoable changes).
- `whiplash_listen` (v0.7.0): loudness, bands, onsets, masking, silent tracks.
- The v0.8.0 recording (`jam.Recording`, only while play-along is on).
- `Engine.bar_log`: bar times. `Engine.bar_hits`: the current bar's events only.
- `view.ACTIONS`: recent tool calls, for the visualiser.

**Gap:**
1. **Nothing says what changed recently, or for how long nothing has.** The model has to remember its own calls.
2. **Nothing flags "too repetitive" or "too busy",** and "repetitive" depends on the genre (research shared norms): 16 unchanged bars is stale in tropical and fine in minimal.

### 7.2 Data model: `taste.py` (new, pure) and two bounded engine logs

- **`Engine.bar_digest`:** a `deque(maxlen=64)`. At each bar line the sequencer appends one tuple: `(bar, at, events, section name, chord symbol, frozenset(muted))`.
  - `events` is the dict `_bar_boundary` just built. It is kept by reference, not copied.
  - This is one append per bar with no computation, like `bar_log` today. Fingerprints and metrics are computed in the tool thread only.
- **`Engine.changes`:** a `deque(maxlen=64)` of `(lands_at_bar, tool, summary)`, appended by tool handlers under `_lock` when they schedule a change. Examples: `"set_progression deephouse.gospel"`, `"energy 3 -> 4"`, `"write_part 6 bass.octave_pump"`.
- **What counts as change** (Q-T4), the same for every genre: a scheduled change landing (`changes`), a user move (v0.8.0 `user_moves`, mapped to bars through `bar_log`), any bar on which a ramp is running (the user's or Whiplash's), and an arrangement `enter`/`exit`. Automation is the arrangement in minimal and progressive (research §4, §6), so ramps always count.
- **Metrics** (`taste.metrics(bars, changes, moves, last_listen, genre)`, pure), over a window of 8 bars by default:
  - **Repetition:**
    - `unchanged_for_bars`: bars since anything that counts as change
    - `cycles_repeated`: identical 4-bar fingerprints in a row, where a fingerprint is per track, per bar, over (step, note, velocity in 8-step buckets)
    - `chord_static_bars`
    - `distinct_bars`
  - **Busyness:**
    - `notes_per_bar` (and per track)
    - `drum_elements`: drum tracks playing
    - `max_voices_per_step`
    - `low_collisions`: bass hits on kick steps per bar
    - `hat_density`: hat hits per 16 steps
    - `register_crowding`: two busy melodic tracks with medians within 2 semitones
  - **Feel:**
    - `velocity_spread` per track (standard deviation; near 0 means machine-flat)
    - `swing` and `humanize` now
  - **Heard** (O5; when a `whiplash_listen` result is under 32 bars old): `masking`, `clipping`, `bands.low`. Never captured anew.
- **Thresholds per genre** (`Genre.taste`, Q-T2), from the research's repetition rows and element counts:

| Genre | `unchanged_bars` before a hint | `busy_drums` cap | Source |
| --- | --- | --- | --- |
| techhouse | **8** | 7 | §3 Mix Elite, The Ghost Production (change one thing every 8 bars); TPS (5-7 elements) |
| tropicalhouse | 16 | 5 | §7 (a hook or section should change around 16 bars) |
| progressivehouse | 16 | 5 | §4 (stale when filter and layers are also static: ramps count as change) |
| melodictechno | 16 | 6 | §8 (16-32 bars without a layer or filter change is stale) |
| deephouse | 32 | 5 | §1 (32 bars of the same vamp is normal if filter or perc evolve); TPS (4-5 elements) |
| house | 32 | 5 | §2 (high tolerance; 4-5 elements) |
| techno | 64 (true stasis only) | 6 | §5 (32 unchanged bars is not a fault; flag busyness more than repetition) |
| minimal.house, minimal.techno | 64 (true stasis only) | 4 | §6 (32-64 bars of the same skeleton is normal; 3-4 elements) |
| soul, breaks | 16 | 6 | default |

  "True stasis" uses the same definition of change as every genre; the number is what differs.
- **Hints:** each fired threshold gives one sentence plus named next steps from the libraries, never a rewrite:
  - "8 bars unchanged in tech house: try `whiplash_mutate(action: 'energy', amount: 'up')`, a fill, or `write_part` with lane `perc.woodblock`."
  - "Busy for minimal: 6 drum elements (minimal holds 4): mute one, or energy −1."
  - "Bass hits 4 kick steps per bar and the last listen heard masking: try `bass.offbeat`."

### 7.3 Tools

- **`whiplash_status(review: 4-32)`** (O1b): with `review`, status returns a compact review instead of the full status, small on purpose for weaker models:
  - `{window: [from, to], changed: [{bar, what, by: "you" | "user"}], unchanged_for_bars, section, energy, chords, metrics: {...compact}, hints: [...], listen: {...} | null}`
  - Description addition, about 90 characters: "review: N bars of what changed, plus too-repetitive or too-busy hints. Feedback only."
- **`whiplash_status`** without `review` gains `taste: {unchanged_for_bars, hint}`, one line only.
- **Musical tool results gain `taste_hint`** (Q-T3): one line, **only when a threshold newly fires** since the last result that carried one. Weaker models don't ask for a review unprompted, so the feedback has to come to them.
- **Feedback only** (Q-T1): nothing in this layer changes the playing beat. An opt-in autopilot is a later, separate decision (§11).
- **Failure hints:**
  - nothing playing: a review of the last run, if one was recorded since the last stop, else "nothing has played since the last stop"
  - fewer bars played than asked: the window shrinks, and the result says so

### 7.4 Scheduler and tracks

- **The only sequencer change is one append per bar** (`bar_digest`), the same order of cost as `bar_log.append`. Everything else runs in the tool thread on copies taken under `_lock`.
- **Nothing in this layer sends MIDI or changes the playing beat.** Hints are for the model.

### 7.5 Test plan

- **Pure:** fingerprints are stable, and a density change or a chord change resets `cycles_repeated`. Thresholds fire at the boundary values of the table above (tech house at 8, deep house at 32, techno at 64). A running ramp resets `unchanged_for_bars`. Hints only name moves, lanes and phrases that exist in the libraries (checked against `library.resolve`).
- **Engine:**
  - `pretend_playing` for 10 bars of tech house with no calls: `status(review: 8)` reports `unchanged_for_bars` ≥ 8 and the repetition hint; 10 bars of deep house give no hint
  - after `mutate(action: "energy", amount: "up")` the next review lists it under `changed` at its bar
  - a `FakeInput` knob move (v0.8.0) shows as `by: "user"`
  - `taste_hint` appears once on the first result after a threshold fires, and not on the next
- **No side effects:** `status(review)` sends nothing (the fake port's message count doesn't change), takes `_lock` only briefly, and never opens the input or the audio device.

---

## 8. Hardware checklist for Phil's Air

**Every item needs Phil's ears. Nothing here is verified.** Each check lists the spec's proposed default; the build PR that ships it adds the check to `docs/testing/hardware-checklist.md`, and results go to `reference.md` only once Phil has run them.

| # | Check | Proposed default | Listen for | If it fails |
| --- | --- | --- | --- | --- |
| HW O-1 | Microtiming vs USB jitter: "deep house shuffle groove, energy 3", then "tech house rolling groove". | clap +0.75 tick (about 15 ms at 122); hats −0.25 tick (about 5 ms at 126) via the previous-step compile | the clap sits behind the beat; the hats push ahead; both audibly, not inside USB jitter (`docs/testing/clock-jitter.md`) | widen the offsets in the lane tables, or drop the negative compile |
| HW O-2 | Ghost notes vs VELOCITY TO VOL (reference Q6). | `GHOST_VEL` 28-40 | ghosts audible but quiet on `deephouse.shuffle` and `house.jack` | raise `GHOST_VEL` to 40-55 in one place |
| HW O-3 | Octave-pump retrigger: "Chicago house" (bass on track 6, 123 BPM). | `bass.octave_pump`, gate 1 | clean R and R+12 retriggers near native pitch, not smeared by the AMP envelope (Q9); the bass follows the chords on the bar | shorten the gate, or lengthen the AMP decay advice in the skill |
| HW O-4 | Shell voicing on Phil's samples: "deep house gospel progression" on two or three chord tracks, then again with a pad track. | `shell` (root, 3rd, 7th) for 7th/9th/11th on ≤ 3 one-voice chord tracks; pads carry the 9th | it sounds like Am7, Fmaj7, G7 with clean low-mids; the pad adds the 9th's colour without mud (Q12, Q13) | default to `close` |
| HW O-5 | By-ear check of every new progression (O1: the deep house six, the house five, tech house two, techno four; O3: the rest). | §3.2.1 as written | each loop sounds like its genre on Phil's kit; list the ones to drop or revoice | edit the table; the source stays cited |
| HW O-6 | Energy changes: "energy 5", then "energy 1". | `mutate energy` through `_reroute` | each lands on the one, with no stuck notes and no Stop or Start | — |
| HW O-7 | "Build to the drop in 16 bars" (`arrange move: build, bars: 16`). | §6.2 | hats in for the last 4 bars, the kick sits out bar 16 with a snare roll, everything lands on the one, and the beat keeps going | — |
| HW O-8 | Let tech house run 16 bars, then "how's it sounding?" | `status(review)`, threshold 8 | Hermes quotes the review (unchanged bars, a named next move) and changes nothing by itself | — |

## 9. Phased build order

The ontology is **v0.9** (Q-S2). The roadmap's multi-device studio moves to v0.10. Phases are cut from `main` in order, one PR each, with merge commits only, and Phil merges.

| Phase | Version | Contents | Size | Depends on |
| --- | --- | --- | --- | --- |
| **O1a: library, harmony, grooves (four genres)** | v0.9.0 | `library.py` + `whiplash_list_library`; `genres.py` records for deephouse, house, techhouse, techno and the compile path (house is the first compiled genre); aliases and the `peak time` change (§1.5); 9th/11th shapes, `shell` and its default rule; the deep house, house, tech house and techno progressions; `set_progression(name)`; key lock with `out_of_key`; lanes marked O1, the eight O1 grooves with five energy levels, curves, `GHOST_VEL`, microtiming and the negative-offset compile; `play_pattern(groove, energy)`, `write_part(groove)`, `mutate energy`, named fills | L | v0.6 harmony, v0.5.1 parts, v0.8.0 undo |
| **O1b: phrases and taste (four genres)** | v0.9.0 | `harmony.Rel` + mode `phrase`; `bass.rolling_deep`, `bass.octave_pump`, `bass.bouncy`, `bass.offbeat`, `stab.offbeat`; `write_part(phrase)` and `phrase: "genre"`; house compiled with its phrases; `bar_digest`, `changes`, `status(review)`, `status.taste`, `taste_hint`; thresholds for the four genres | M | O1a |
| O2: harmony intents and keys | v0.9.1 | `set_progression(intent)` (darker, brighter, tension, release), with `how` for darker/brighter (`harmonic` default, `timbral`, `register`, or combined; the result names what was applied and the other options; undoable, §3.2); **NEW behaviour:** key-only `set_progression` (`key`/`scale` with no chords changes the key; today that errors "give chords"), with `lock`; `pedal` mode, `follow: true` on written parts | M | O1 |
| O3: the other four genres | v0.9.2 | records, progressions, lanes, grooves and phrases for progressivehouse, melodictechno, minimal (both presets, with the `perc.poly3` approximation) and tropicalhouse; `bass.root_follow`, `bass.rolling_16`, `bass.stab_sparse`, `bass.round_sub`, `bass.descending_walk`, `bass.walking`, `stab.single`, `pad.hold`, the arps, `lead.stutter`, `lead.pentatonic_hook`, `melody.motif`; `soul.classic` and `breaks.classic`; the O3 aliases and moods | M-L | O1 |
| O4: arrangement grammar | v0.9.3 | `form.py`: section types, energy per section, breakdown styles, `fill_every`, `enter`/`exit`, `then`, the eight forms; `arrange(form)` and `arrange(move, bars)` | M-L | O1 (energy), O3 (all genres' styles) |
| O5: taste, polish | v0.9.4 | listen data in reviews, threshold tuning from Phil's sessions, hint wording | S | O1b, O4 |

**Why this v1 slice.** It removes the three places where a weak model improvises today (the drum feel, the chords, the bass) in four genres at once:
- three already exist as patterns, so equivalence tests protect today's sound
- house adds the octave pump and the stab progressions, and is the first genre compiled from tables, which makes O3 paint-by-numbers
- together they span thresholds of 8 to 64 bars and 5 to 7 drum elements, so taste is tested across genres from the start

It adds one tool and extends five, so its budget step is small: tools about 4,250, params about 9,900.

**Each phase** keeps existing calls bit-identical (equivalence tests, as in §4.5), updates the skill, README, CHANGELOG, roadmap and budget pins, and lists its HW checks from §8.

## 10. Decisions

Settled in two rounds, from the research brief and Phil's stated defaults. On 2026-11-19 Phil answered Q-S1 to Q-H4: six confirmed, Q-H3 changed, Q-H4 decided by Deck (he delegated it). The same day he confirmed the other 21 at their defaults ("Yes to all remaining points for now. We can review in more detail."), so he may revisit them in a later detailed review.

**The spec is now fully decided. O1a is ready to start on Phil's go.** Anything marked **HW** is a proposed default that still needs his ears (§8).

### 10.1 Decisions confirmed by Phil

One line per question, with the default the spec uses. Phil can confirm or change each by ID; the tables in §10.2 give the rationale and source. Every item is answered and carries its date and decision.

**Scope**
- Q-S1. Four new tools, or fold key/lock/intents, energy, moves and review into existing verbs? **Answered 2026-11-19: confirmed.** One new tool, `whiplash_list_library` (25→26).
- Q-S2. Ontology as v0.9 (multi-device to v0.10), or v0.8.x? **Answered 2026-11-19: confirmed.** v0.9; phases ship as v0.9.0–v0.9.4.
- Q-S3. In-repo Python tables only, or also a user JSON library later? **Answered 2026-11-19: confirmed.** Python tables now; read-only user JSON after v0.9, never shadowing a built-in name.

**Harmony**
- Q-H1. Are the six deep house progressions right by ear, and which are missing? **Answered 2026-11-19: confirmed** (the researched set). `two_chord`, `dorian_soul`, `two_five`, `gospel`, `afro`, `one_chord`; i–VI–III–VII moves to `house.uplift`. Still **HW** by ear (O-5).
- Q-H2. Key lock on by default once a key is set? **Answered 2026-11-19: confirmed.** On; `out_of_key` per part; drums never snapped. Phil: melodic lines (bass, lead, chords) follow the key so they stay tonal; drums stay on the grid and are never pitch-corrected to the scale; a snare must never accidentally sound like a note.
- Q-H3. Should `darker` do both a mode shift and a filter close by default? **Answered 2026-11-19: changed.** Not hard-wired to harmony only. The plugin gives the model context and a menu (`how`): `harmonic` (darker qualities/modes, flatten the 3rd/6th, lower voicing register), `timbral` (close the filter / reduce brightness on melodic tracks) and `register` (thin the highs, drop the lead an octave). The model picks one or combines them, and the result names what was applied, so it is undoable and explainable. `brighter` mirrors it. Default with no choice: `harmonic`. **Provisional, pending the detailed review:** the two rules Deck added here stand for now: a `timbral` darker is separate from filter-as-energy (Q-A1), and `brighter` never opens the filter past its value before the first `darker`.
- Q-H4. `shell` as the default voicing for 9th (and 7th/11th) chords on audio tracks? **Answered 2026-11-19: delegated to Deck.** Shell voicings (root, 3rd, 7th) by default when there are three or fewer chord tracks; pad tracks may use fuller 9th voicings; otherwise `close`. Still **HW** (O-4).

**Groove**
- Q-G1. Groove names: letters or descriptive names? **Confirmed 2026-11-19** (at the default; Phil may revisit it in a later detailed review): descriptive; letter aliases only for today's patterns (`deephouse.classic` = `deephouse.A`, bit-identical).
- Q-G2. +0.5-tick clap and −0.25-tick hat: audible and worth it? **Confirmed 2026-11-19** (at the default; Phil may revisit it in a later detailed review): microtiming on except in the classic grooves. **HW** (O-1).
- Q-G3. Is energy a `mutate` action, a `perform` move, or both? **Confirmed 2026-11-19** (at the default; Phil may revisit it in a later detailed review): `mutate(action: "energy")` while playing, plus a form section key.
- Q-G4. Ghost velocity 28–40 vs VELOCITY TO VOL? **Confirmed 2026-11-19** (at the default; Phil may revisit it in a later detailed review): `GHOST_VEL` 28–40; fallback 40–55 in one place. **HW** (O-2).

**Phrases**
- Q-P1. `phrase` on `write_part`, or a separate tool? **Confirmed 2026-11-19** (at the default; Phil may revisit it in a later detailed review): `write_part(phrase)`.
- Q-P2. Does a phrase replace the genre's bass line by default? **Confirmed 2026-11-19** (at the default; Phil may revisit it in a later detailed review): yes; a phrase replaces that track's line. Each genre has a default bass.
- Q-P3. A seeded `melody.motif`, or keep leads hand-written? **Confirmed 2026-11-19** (at the default; Phil may revisit it in a later detailed review): leads stay model-written, with key lock; motifs/leads in O3 on request only.
- Q-P4. Octave-pump retrigger on one audio track? **Confirmed 2026-11-19** (at the default; Phil may revisit it in a later detailed review): octave-pump is the default bass only in classic house. **HW** (O-3).

**Arrangement**
- Q-A1. Energy moving the music filter: opt-in? **Confirmed 2026-11-19** (at the default; Phil may revisit it in a later detailed review): opt-in, except progressive and melodic-techno forms, which default it on.
- Q-A2. A move during an arrangement: replace (undoable), queue, or refuse? **Confirmed 2026-11-19** (at the default; Phil may revisit it in a later detailed review): replace from the next bar; `whiplash_undo` restores it.
- Q-A3. Breakdown: close the bass filter, or drop the bass? **Confirmed 2026-11-19** (at the default; Phil may revisit it in a later detailed review): per genre (§6.2).
- Q-A4. `then: "continue"` as the default for moves, `stop` for forms? **Confirmed 2026-11-19** (at the default; Phil may revisit it in a later detailed review): yes; warn, do not refuse, if a section is not a multiple of 8 bars.

**Taste**
- Q-T1. Feedback only, or an opt-in autopilot later? **Confirmed 2026-11-19** (at the default; Phil may revisit it in a later detailed review): feedback only in v0.9; autopilot is later (§11).
- Q-T2. 16 bars for deep house and 32 for techno as "repetitive"? **Confirmed 2026-11-19** (at the default; Phil may revisit it in a later detailed review): tech house 8; tropical, progressive and melodic 16; deep house and house 32; techno and minimal 64.
- Q-T3. Should `taste_hint` ride on tool results? **Confirmed 2026-11-19** (at the default; Phil may revisit it in a later detailed review): one line, only when a threshold first fires; full review via `status(review)`.
- Q-T4. Do the user's knob moves count as change? **Confirmed 2026-11-19** (at the default; Phil may revisit it in a later detailed review): yes, and ramps too.

**Aliases**
- Q-alias-house. Keep bare "house" meaning deep house in v0.9? **Confirmed 2026-11-19** (at the default; Phil may revisit it in a later detailed review): yes (unchanged). Remapping the bare word is a later, explicit decision (§11).
- Q-alias-chicago. How should classic/Chicago house be named? **Confirmed 2026-11-19** (at the default; Phil may revisit it in a later detailed review): `"classic house"`, `"chicago"` and `"chicago house"` resolve to the new `house` genre.
- Q-alias-peak-time. Keep the mood "peak time" as tech house, or move it to techno? **Confirmed 2026-11-19** (at the default; Phil may revisit it in a later detailed review): it now means techno; the changelog must note the change.
- Q-alias-peak-time-tech-house. How is the old meaning kept? **Confirmed 2026-11-19** (at the default; Phil may revisit it in a later detailed review): `"peak time tech house"` still means tech house.
- Q-alias-minimal. Bare "minimal" = which preset? **Confirmed 2026-11-19** (at the default; Phil may revisit it in a later detailed review): `minimal.house`.

### 10.2 Decision tables

**Scope:**

| Q | Decision | Rationale | Source |
| --- | --- | --- | --- |
| Q-S1 | **Confirmed 2026-11-19.** One new tool, `whiplash_list_library`. Key, lock and intents fold into `set_progression`; energy into `mutate(action: "energy")`; moves into `arrange(move, bars)`; review into `status(review)`. 26 tools. | Each folded verb already belongs to an existing tool; discovery can't be an enum. | Phil default (fewer tools), usability |
| Q-S2 | **Confirmed 2026-11-19.** The ontology is v0.9; multi-device moves to v0.10. O1 ships as v0.9.0, later phases as v0.9.x. | | Phil default |
| Q-S3 | **Confirmed 2026-11-19.** In-repo Python tables now. A read-only user JSON library under `~/.hermes/whiplash/` after v0.9, with the same integrity checks, never shadowing a built-in name. | No new dependency; deterministic tests. | Phil default |

**Harmony:**

| Q | Decision | Rationale | Source |
| --- | --- | --- | --- |
| Q-H1 | **Confirmed 2026-11-19.** Deep house: `two_chord`, `dorian_soul`, `two_five`, `gospel`, `afro`, `one_chord`. i–VI–III–VII moves to `house.uplift`. Every genre has a sourced table (§3.2.1); melodic techno has only the two sourced entries. Prydz-style descending bass is `bass.descending_walk` (O3); slash chords are a later parser extension. | Deep house is not "i–VI–III–VII only"; don't invent progressions. **HW:** by ear (HW O-5). | Research §1-8 |
| Q-H2 | **Confirmed 2026-11-19.** Key lock on by default once a key is set; `out_of_key: true` per part; drums never snapped. | Phil: melodic lines (bass, lead, chords) follow the key so they stay tonal; drums stay on the grid and are never pitch-corrected to the scale; a snare must never accidentally sound like a note. | Phil default, confirmed by Phil |
| Q-H3 | **Changed 2026-11-19.** `darker`/`brighter` take `how`: `harmonic` (default), `timbral` (melodic tracks' filter/brightness only) or `register` (thin the highs, lead down an octave), alone or combined. The result names what was applied and the unused options; undo restores all of it (§3.2). | Darkness is harmonic, timbral or registral depending on the track; a menu lets the model choose with context instead of one fixed meaning, and naming the choice keeps it explainable. | Phil |
| Q-H4 | **Decided by Deck 2026-11-19** (Phil delegated). `shell` (root, 3rd, 7th) is the default for library 7th/9th/11th chords on chord and stab tracks with three or fewer one-voice chord tracks; pad tracks may use fuller 9th voicings; otherwise `close`. | Clean low-mids on the Digitakt; the extensions on pads keep the deep house colour. **HW:** on Phil's samples (HW O-4). | Deck, research shared norms |

**Groove:**

| Q | Decision | Rationale | Source |
| --- | --- | --- | --- |
| Q-G1 | **Confirmed 2026-11-19.** Descriptive names; letter aliases only for today's patterns (`deephouse.classic` = `deephouse.A`, identical to today). | Demo-safe, and names describe themselves. | Phil default |
| Q-G2 | **Confirmed 2026-11-19.** Microtiming on by default in every non-classic groove, per genre (deep house clap +0.5 to +1 tick, about 10-20 ms at 122; Chicago jacked clap; tech house hats −0.25). `humanize: 0` leaves the table. | Late claps and pushes are the groove, not flavour. **HW:** audible above USB jitter (HW O-1). | Research §1 SONAA, §2 Attack, §3 Mix Elite |
| Q-G3 | **Confirmed 2026-11-19.** Energy is `mutate(action: "energy")` while playing and a section key in forms. No separate perform verb. | One verb per job. | Usability |
| Q-G4 | **Confirmed 2026-11-19.** Ghosts default to `GHOST_VEL` 28-40, raised to 40-55 in one place if inaudible. | Ghosts are mandatory in house-family grooves. **HW:** VELOCITY TO VOL (HW O-2). | Research §2, §3, §6 |

**Phrases:**

| Q | Decision | Rationale | Source |
| --- | --- | --- | --- |
| Q-P1 | **Confirmed 2026-11-19.** `phrase` on `write_part`. | Fewer tools; routing, undo and stop already work. | Phil default |
| Q-P2 | **Confirmed 2026-11-19.** A phrase on the bass track replaces the genre bass ("written parts win"). Each genre has a default bass phrase, so the right line appears without being asked. | Consistent with today. | Usability |
| Q-P3 | **Confirmed 2026-11-19.** Leads stay model-written with key lock. Seeded `melody.motif`, `lead.stutter` and `lead.pentatonic_hook` arrive in O3, on request only. | Genre traits, without becoming defaults. | Research §7, §8 |
| Q-P4 | **Confirmed 2026-11-19.** The octave pump is the default bass only for classic house. Deep house `bass.rolling_deep`, tech house `bass.bouncy`, techno `bass.offbeat`, and the O3 genres as in §5.2.1. | A Chicago signature, not universal. **HW:** clean retrigger on one audio track (HW O-3). | Research §2 SONAA |

**Arrangement:**

| Q | Decision | Rationale | Source |
| --- | --- | --- | --- |
| Q-A1 | **Confirmed 2026-11-19.** Energy moves the filter only when opted in; forms default it on only for progressive house and melodic techno. | Filter is the performance there; layers elsewhere; the cutoff stays changed until the kit reloads. | Research §4, §8, cross-cutting |
| Q-A2 | **Confirmed 2026-11-19.** A move during an arrangement replaces it from the next bar; `whiplash_undo` restores it; the result names what it replaced. | "Drop it now" means now. | Usability |
| Q-A3 | **Confirmed 2026-11-19.** Breakdown style per genre (§6.2): deep, progressive and melodic take kick and bass out; techno drops the kick; tech house filters the low end; tropical reduces drums and keeps the hook; minimal subtracts one element. | One default is wrong for most genres. | Research cross-cutting, §3, §5, §7 |
| Q-A4 | **Confirmed 2026-11-19.** Moves default to `then: "continue"`; forms to `stop`. Forms warn, not refuse, on a section that isn't a multiple of 8 bars. | Backward compatible; DJs count in 8, 16 and 32. | Research shared norms |

**Taste:**

| Q | Decision | Rationale | Source |
| --- | --- | --- | --- |
| Q-T1 | **Confirmed 2026-11-19.** Feedback only in v0.9; an opt-in autopilot later. | | Phil default |
| Q-T2 | **Confirmed 2026-11-19.** Per-genre thresholds (§7.2): tech house 8; tropical 16; progressive and melodic 16; deep house and house 32; techno and minimal 64. Busy-drum caps: minimal 4; deep, house, progressive, tropical 5; techno and melodic 6; tech house 7. | "Repetitive" is genre-relative. | Research §1-8 |
| Q-T3 | **Confirmed 2026-11-19.** `taste_hint` on tool results, one line, only when a threshold newly fires. Full review via `status(review)`. | Weak models don't ask unprompted. | Usability |
| Q-T4 | **Confirmed 2026-11-19.** User knob moves and ramps count as change. | Automation is the arrangement in minimal and progressive; don't nag a performer. | Research §4, §6 |

## 11. Later, not v0.9

- Slash chords (`Am/G`) in `harmony.parse_chord` (a harmony-parser extension; `bass.descending_walk` covers the musical need until then).
- The read-only user JSON library under `~/.hermes/whiplash/` (Q-S3).
- An opt-in taste autopilot (Q-T1).
- Remapping the bare word `house` to classic house: a separate, explicit decision (§1.5).
- Energy levels for `soul.classic` and `breaks.classic`.
