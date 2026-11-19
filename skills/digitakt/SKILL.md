---
name: digitakt
description: How to drive an Elektron Digitakt II through the Whiplash tools - named grooves, energy levels and progressions from the library, the kit map, one-call start, keys and chord progressions, song arrangement (intro, build, drop, outro; forms, breakdown styles and moves like "build to the drop"), DJ-style transitions and mix levels, listening to the unit's audio (loudness, clipping, kick timing) and the loudness guard, playing along with the user (their knob moves, ramps that yield, call and response, undo), writing melodies and rhythms, pitch and register, sample slots, note length vs AMP MODE/HOLD, transport overlap, and a checklist for sounds that come out wrong.
---

# Whiplash on a Digitakt II

Whiplash sends MIDI notes, clock, transport and CCs to the Digitakt II, one MIDI channel per track (track N = channel N). It can't read the unit's state; with `whiplash_play_along` on it hears what the unit sends (knob moves, notes). This skill ships with the plugin and is updated with it, so trust it over any older notes of your own. The tool descriptions are kept short on purpose; the detail is here.

## Fast path: label, then start in one call

1. When the user says what their tracks hold ("track 7 is a cymbal, track 5 is a pad"), call `whiplash_label_tracks(tracks: {"7": "cymbal", "5": "pad"})` straight away. Labelled slots too: `slots: {"11": "synth Phil likes"}`.
2. Start the beat **and** fit it to the kit in the same call: `whiplash_play_pattern(genre: "deephouse", tracks: {"6": {"slot": 9, "transpose": 12}, "8": {"mute": true}})`. Each entry takes `slot` (0-127), `tune` (64 = none), `transpose` (semitones) and `mute`.
3. Read the result, pass on its `overlap_warning` (and any `warning`), and answer. Don't follow up with separate select_sample / transpose / mute calls for things `tracks` already did.

## Named things first (v0.9.0): list, pick, combine

Don't place 16 steps by hand or invent theory. Pick named things; Whiplash does the timing and the harmony.
1. **List** what exists: `whiplash_list_library(kind: "groove", genre: "house")`. Kinds: `genre`, `progression`, `groove`, `lane`, `phrase`, `fill`, `form`, `move`. `tag` filters (`warm`, `dark`, `jacking`; for lanes a role, `perc`).
2. **Pick** by name. Names are `<genre>.<name>` or `<role>.<name>`; any case, spaces or `-` work, and a bare name works when it is unambiguous (`"gospel"`, `"shuffle"`). An unknown name answers with the closest matches.
3. **Combine** in as few calls as possible:
   - "Chicago house, jack groove, energy 3": `whiplash_play_pattern(groove: "house.jack", energy: 3)`. A full groove name picks its genre.
   - "Deep house gospel chords": `whiplash_set_progression(name: "deephouse.gospel")`.
   - "Busier" / "bring it down" while playing: `whiplash_mutate(action: "energy", amount: "up")` (or 1-5, `"down"`).
   - "A flam roll into the next bar": `whiplash_mutate(action: "fill", fill: "snare.flam_roll")`.
   - "Shuffled hats on track 10": `whiplash_write_part(track: 10, groove: "hat.offbeat_shuffle")` (a named lane).
   - "A rolling deep house bass": `whiplash_write_part(track: 6, phrase: "bass.rolling_deep")`. It follows whatever chords play, from then on. `phrase: "genre"` takes the genre's own line for that track. Don't pass `notes` with a phrase.
   - "How's it sounding?" / "is it getting stale?": `whiplash_status(review: 16)`. Quote it; don't act on it unless the user agrees. For what it *sounds* like on the unit, run `whiplash_listen` first: the review then includes what was heard.
   - "Build to the drop in 16 bars": `whiplash_arrange(move: "build", bars: 16)`. "Break it down", "drop it", "slam it": `move: "breakdown"`, `"drop"`, `"slam"`. The beat keeps playing afterwards (v0.9.3, see Arrangement).
   - "Make it a tech house DJ track": `whiplash_arrange(form: "techhouse_dj")` (or `form: "tech house"`: each genre has its own form).
   - "Darker" / "brighter": `whiplash_set_progression(intent: "darker")`. "More tension", then "let it go": `intent: "tension"`, then `"release"`. "Change key to F minor": `whiplash_set_progression(key: "Fm")` (v0.9.1, see Keys below).

**The house words, plainly:** bare "house" still means **deep house**. Classic/Chicago house is `chicago`, `chicago house` or `classic house` (`genre: "chicago"`); its library prefix is `house.` (`house.jack`). The mood "peak time" means **techno** now; "peak time tech house" keeps tech house. Bare "minimal" means **minimal house**; say "minimal techno" for the other preset. Both share the library prefix `minimal.` (`minimal.house_shuffle`, `minimal.techno_kick`, `minimal.fifth`).

**The eight genres** (one line each: its signature):
- **Deep house** (`deephouse`, 122): warm m7/m9 vamps, swung 8th hats, a late clap. Grooves `deephouse.classic` (= `A`, today's beat), `deephouse.shuffle`. Progressions: `two_chord`, `dorian_soul`, `two_five`, `gospel`, `afro`, `one_chord`.
- **Classic house** (`chicago`, 123): jacking 4/4, a late jacked clap, off-beat piano stabs, an octave-bounce bass over Am C B♭ Am. Grooves `house.jack`, `house.eighths`. Progressions: `piano_stab`, `mixed_shuffle`, `uplift`, `jack_vamp`, `minor_twist`.
- **Tech house** (`techhouse`, 126): 16th hats pushed early, a bouncy bass; change something every 8 bars. Grooves `techhouse.classic`, `techhouse.rolling`. Progressions: `one_note`, `dark_two`.
- **Techno** (`techno`, 130): kick-led, one chord or a dark two-chord vamp. Grooves `techno.classic`, `techno.rolling`. Progressions: `pedal`, `phrygian`, `dark_vamp`, `sus_stab`.
- **Progressive house** (`progressive`, 124): lush 7th/sus chords as off-beat stabs, a long root bass, long filtered builds. Groove `progressivehouse.functional`. Progressions: `circle` (default), `long_two`, `phrygian_turn`, `descending` (write `bass.descending_walk` on the bass with it). Pad breakdowns: `pad.hold`.
- **Melodic techno** (`melodic techno`, 124): cinematic minor chords every two bars as a held pad, a rolling 16th bass, stripped drums. Groove `melodictechno.stripped`. Progressions: `cinematic` (default), `held_vamp`. Ask for `lead.stutter` on a lead track if the user wants a stutter lead.
- **Minimal** (`minimal` = `minimal.house` 126, `minimal techno` 128): 3-4 drum elements, space, one change per phrase, little harmony. Grooves `minimal.house_shuffle` (a clap every other bar), `minimal.techno_kick` (a 3-against-4 perc). No progression by default; `minimal.stab_m7`, `stab_sus2`, `fifth` if asked. Minimal techno has no chord track.
- **Tropical house** (`tropical`, 108, home key C major): bright major pop chords as a pad, soft drums with shaker and bongos, a round sub; hooks instead of big drops. Groove `tropicalhouse.soft`. Progressions: `pop` (default), `pop_minor`. Ask for `lead.pentatonic_hook` for a hook.

Each genre plays its own groove, chords and bass from `play_pattern` alone: "progressive house" is one call. An example per genre: `whiplash_play_pattern(genre: "tropical")`, then `whiplash_mutate(action: "energy", amount: "up")`.

**What comes back:**
- `groove: {name, energy, lanes, swing}`. `unplaced` lists lanes with no track on this kit (deep house has no perc track by default): tell the user, and offer to label one (`{"8": "perc"}`) and call again.
- Energy 1 is kick and one hat, 2 adds the backbeat and closed hat, 3 is the genre's full groove, 4 adds hits and ghosts, 5 is the busiest. An energy change lands on the next bar and keeps everything else. `soul` and `breaks` have one level (`soul.classic`, `breaks.classic`: today's beat).
- A library progression in another scale plays in the relative key or in its own mode on the session root: read `key` back ("C major, the relative of A minor").
- Library 7th/9th/11th chords voice `shell` (root, 3rd, 7th) on up to three chord tracks (`voicing_rule` says why); a labelled pad adds the 9th (`pad_tones`). Pass `voicing` to override.
- **Key lock:** notes you write on a bass, chord, pad, stab or lead track snap to the key playing, and the result lists `snapped`. Say so. For a deliberate chromatic note pass `out_of_key: true`. A part written in its own `key` keeps its notes. Drums are never snapped.
- **Phrases** (`bass.rolling_deep`, `bass.octave_pump` (Chicago only by default), `bass.bouncy`, `bass.offbeat`, `stab.offbeat`, `bass.root_follow`, `bass.rolling_16`, `bass.stab_sparse`, `bass.round_sub`, `bass.descending_walk`, `bass.walking`, `stab.single`, `pad.hold`): the result says what the line `follows` (a progression, the genre's own chords, or the key's tonic) and `now`, the notes the next bar plays. `density` (0-1) thins it by importance, `register` (`low`, `mid`, `high` or a note) moves its window, `seed` varies the seeded ones (`bass.rolling_deep`'s and `bass.walking`'s 4th bar, `stab.single`'s last stab). Chicago house's bass and stabs, and every v0.9.2 genre's, are phrases already, so a progression moves them.
- **Leads stay yours to write** by default (key lock keeps them in key). Only when the user asks for one, name it on a lead track: `arp.chord_up`, `arp.chord_updown`, `arp.chord_seeded` (a new order each bar), `lead.stutter`, `lead.pentatonic_hook` (a 2-bar hook, repeated) or `melody.motif` (a motif, repeated, up a step, then answered on the root). `seed` picks the variation: "another one" is a new seed. `phrase: "genre"` never writes a lead.
- **Taste feedback is feedback only.** `whiplash_status(review: N)` lists what changed (by `you` or the `user`), `unchanged_for_bars`, compact metrics and `hints`, each naming a next move from the library. `whiplash_status` carries a one-line `taste`. A musical call's result may carry `taste_hint` once, when a threshold first fires: mention it in a few words, suggest the move, and never apply it unasked. "Repetitive" depends on the genre: tech house wants a change every 8 bars; progressive, melodic techno and tropical 16; deep and classic house 32; techno and minimal 64 (minimal also flags more than 4 drum elements). Each hint is one sentence ending in calls you can make as written (`try whiplash_mutate(...), ...`); offer one.
- **Heard checks in a review (v0.9.4).** When the last `whiplash_listen` was taken while this beat played and under 32 bars ago, the review's `listen` holds `masking`, `clipping`, `kick_over_rest_db` and `low_pct` (the low band's share), and the hints may say the kick is masked (try `bass.offbeat` on the bass track, or a lower bass level) or the mix clips (lower something, then listen again). Otherwise `listen` is `null` and `listen_note` says why. The review never listens by itself; ask the user before a fresh `whiplash_listen`.
- Microtiming (a late clap, pushed hats) and ghost notes are part of every non-classic groove. `whiplash_mutate humanize` adds on top. Whether they are audible on the unit is untested.

## Kit map (`whiplash_label_tracks`)

- Free text is matched to a role: kick, snare, rim, clap, closed hat, open hat, cymbal, perc, bass, pad, stab, chord, lead, fx, other ("tuned cymbal" -> cymbal, "dirty bass" -> bass, "synth" -> lead). Or give `{"role": "chord", "label": "Rhodes"}`. `null` (or `""`) removes a label; labels merge, so you only send what changed.
- **Generated parts follow the map** from the next bar (or the next start). Each part goes to a track labelled with its role, else to one with a close role (rim <-> snare, chord -> pad, stab -> lead, open hat -> cymbal), else stays on its default track if the user hasn't labelled that track as something else, else it is dropped. A cymbal or fx track never gets a chord, bass or other melodic line. Labelled tracks with no matching part stay silent: write one with `whiplash_write_part`.
- Every `whiplash_play_pattern` result (fresh start and queued switch), every `whiplash_label_tracks` result and `whiplash_status` carry `routing`: which part lands where (`parts`), which were `dropped`, and which labelled tracks are `silent_until_written`. Tell the user in their terms.
- **Written parts win their track.** A track playing a `whiplash_write_part` part is never a routing target: the generated part goes to the next track with a matching label, or, if there is none, `routing.replaced_by_written` names it (the write_part result says `replaces_generated`). Nothing is lost silently, and no second bass appears on the default track.
- **`vacated`:** an unlabelled default track whose part moved to a labelled track plays nothing (e.g. "tracks 7 and 8 are tuned cymbals" moves the open hat from track 5 to 7, so track 5 goes quiet). `routing.vacated` and `vacated_note` say so: tell the user, and offer to label track 5 (e.g. as open hat) or write a part there. Whether this should happen at all is an open question for Phil; don't promise either behaviour.
- **Relabelling while playing:** a part that moves takes its `whiplash_transpose` and density with it (`follows_part` in the result, e.g. `{"transpose": {"6->10": 12}}`). A part that ends up on no track drops them (`"6->dropped"`).
- **Tracks 9-16:** when the kit map routes a generated part there, or `tracks` setup names one, the result carries `channel_note` and `tracks_9_16`. Ask the user to check that AUTO CHANNEL and FX CONTROL CH aren't on those channels.
- Results and `whiplash_status` show the label as `tracks[n].role` (without "(assumed)") plus `kit_role`; `roles_assumed` is false once anything is labelled. A selected slot with a label shows `slot_label`, in `whiplash_select_sample`, `whiplash_set_param` sample_slot and the play `setup` echo too.
- The map lives in memory for the session: it survives `whiplash_stop` and pattern switches. `reset: true` clears it, and so does a gateway restart.
- Labels are only what the user told you. Whiplash can't read sample names (that would need SysEx, which it never sends).
- **Kit scan (`whiplash_scan_kit`):** "scan my kit" or "what's on my tracks?" with the listen setup in place. Stop the beat first; it refuses while one plays. It plays one note per track alone (about 17-35 s for 16 tracks; `tracks: [9, 10]` for a few) and returns `proposed` labels with `confidence`, plus `apply_with`. **It never applies them.** Show the user a short list (track: label, confidence; say which are `unknown` or `silent`), take their corrections, and only on their yes call `whiplash_label_tracks(tracks: apply_with.tracks)` with those corrections merged in. If `unexpected_audio` or the error says the unit is already making sound, its own pattern is running: ask them to press Stop on the unit, then scan again. `silent` means muted on the unit, level 0, an empty slot, a changed MIDI channel, or USB OUT not on MAIN.

## Keys and chord progressions

- **Key:** `whiplash_play_pattern(genre: "techno", key: "Am")` (or `key: "A", scale: "minor"`) moves the bass, chords and stabs into that key from the first bar, or from the switch bar when queued. Drums never move. Without a key each genre plays in its home key (A minor for most; techno F minor; breaks G minor; tropical house C major). Once set, the key stays for later switches until `whiplash_stop`. Results and status show `key`.
- **Progression:** `whiplash_set_progression(chords: "i VI III VII", bars_per_chord: 2)`. It starts on the next bar line and loops. Chords are Roman numerals in the key (upper case = major, lower = minor; `V7`, `ii°`, `bVII`, `Imaj7`, `sus4`) or names (`"Am F C G"`). `key` changes the key at the same bar. `voicing`: `close` (default, voice-led), `root`, `open`, `power`.
- **Who follows**, by role (the kit map first, else the pattern's role):
  - chord, pad and stab tracks → `chords`: one chord tone per hit, and each chord track starts on a different tone, so two or three chord tracks together sound the chord.
  - bass → `root`: every hit plays the chord root, in the line's own register.
  - lead → `snap`: notes snap to the scale.
  - Drums, hats, perc, cymbal and fx tracks never change, and `tracks` overrides on them are refused. Never promise chords on a cymbal.
- **One note at a time:** the manual gives the Digitakt II 16 audio voices for 16 tracks and documents chords only on MIDI tracks, so an audio track probably plays one note at a time (not yet checked on hardware). That is why `chords` spreads the chord over tracks and hits. `stack` sends every tone on every hit: only for a MIDI track or a polyphonic target, or if the user finds their unit layers notes.
- **Overrides:** `tracks: {"9": "chords", "6": "off"}` with modes `chords`, `stack`, `root`, `snap`, `pedal` (the key's tonic under every chord), `off`. A chord track with no line of its own (a labelled pad that got no part) holds one chord tone per bar.
- **"Pads on track 7":** label it first (`whiplash_label_tracks(tracks: {"7": "pad"})`), or pass `tracks: {"7": "chords"}`.
- Written parts play as written unless `tracks` names them (the result lists `written_unchanged`). Transpose, mutes, drops, fills and density still apply on top. The progression carries across switches and `whiplash_mutate reset`; `clear: true` or `whiplash_stop` ends it.
- `whiplash_status` shows `progression.now` (the chord playing and `next_change_at_bar`), every voiced chord with note names, and `tracks[n].progression`. Read the chord names back to the user.
- A melody in the playing key: `whiplash_write_part(track: 8, rhythm: "8ths", key: "current", notes: "1 3 5 8")`. Add `follow: true` and it follows the chords (and later key changes) like a generated line; `follow: "root"` makes it a root line.
- **Change key alone (v0.9.1):** `whiplash_set_progression(key: "Fm")` (or `scale: "dorian"` to keep the root). From the next bar the melodic tracks, the progression (numerals re-read, chord names shifted) and phrases move; drums never do. Read `key`, `from` and `progression` back. "already in A minor" means nothing changed.
- **Intents (v0.9.1): say what it should feel like, not the theory.** `whiplash_set_progression(intent: ...)`, from the next bar:
  - `darker` / `brighter` take `how`, one or a list; with none, `harmonic`:
    - `harmonic`: a library progression swaps to its genre's next darker (brighter) one; otherwise the key steps one mode along lydian > major > mixolydian > dorian > minor > phrygian, chords moving with it.
    - `timbral`: the melodic tracks' filter closes (opens) one step. Drums are never touched. It needs a cutoff Whiplash has sent (`whiplash_set_param filter_freq` first, e.g. 127 if the filters are open); brighter never opens past where darker started.
    - `register`: the top chord voice drops out and the lead goes down an octave; brighter puts them back.
  - Read back `did`, and offer one of `other_options` if the user wants more ("I made it phrygian; I could also close the filters a little").
  - `tension`: each call adds one step: a dominant 7th at the loop's end, then a 9th, then a bass pedal. `release` brings the old loop back exactly.
  - Every intent and key change is undoable with `whiplash_undo` (key, chords, filter values, the lead's octave).
- **Key lock on/off:** `whiplash_set_progression(lock: false)` lets written notes play out of key for the session (`lock: true` turns it back on). Prefer `out_of_key: true` on one part for one chromatic note.
- Typical request, "deep house in A minor, i-VI-III-VII, two bars per chord, pads on track 7", is three calls: `whiplash_label_tracks(tracks: {"7": "pad"})`, `whiplash_play_pattern(genre: "deephouse", key: "Am")`, then `whiplash_set_progression(chords: "i VI III VII", bars_per_chord: 2)`.

## Arrangement: a whole track (`whiplash_arrange`)

- `whiplash_arrange(preset: "short_demo")` turns the playing beat into a song from the next bar line: intro, build, drop, outro, about 75 s at the current tempo (`seconds: 90` for "a 90-second track"; it rounds to 4-bar phrases). `preset: "club"` is intro 16 / build 8 / drop 16 / break 8 / drop 16 / outro 16 bars (80 bars, about 2.5 minutes at 128 BPM).
- In both presets: the intro plays kick and hats; the build adds perc and the music tracks with a rising filter (`filter_freq` 20 → 127, exp curve) and the kick sits out its last bar; the drop plays everything; the break drops kick and bass; the outro thins to drums. Every section but the outro ends on a fill.
- **It stops by itself:** by default (`then: "stop"`, or `loop: false`) the run stops cleanly on the bar line after the last section (note-offs, MIDI Stop). `then: "loop"` (or `loop: true`) starts over from the first section. `then: "continue"` ends the arrangement there and keeps the beat playing: its mutes lift and the energy goes back to where it was. `clear: true` ends the arrangement and unmutes what it muted; the beat keeps playing. `whiplash_stop` ends everything.
- **Custom sections:** `sections: [{name, bars, tracks, mute, drop, fill, chords, bars_per_chord, ramps, transition, transition_bars, filter_from, mix}]`, 1-16 sections of 1-64 bars.
  - `tracks`: what plays (everything else is muted by Whiplash, never with the unit's CC 94). Track numbers or groups: `all`, `drums`, `kick`, `hats` (closed, open, cymbal), `perc` (snare, rim, clap, perc), `bass`, `music` (pad, chord, stab, lead, fx, other), or any kit role. Or `mute`: what doesn't play. Groups resolve again at each section's first bar from the roles playing then, so the arrangement follows a switch or relabel.
  - `drop`: tracks that sit out the section's last bar. `fill: true`: a drum fill on its last bar.
  - `ramps: [{track, param, from, to, bars, curve}]` start on the section's first bar (default length: the section). Without `from` a ramp starts from the last value Whiplash sent; if there is none it is skipped (`skipped_ramps` in status). A ramp leaves the param where it ends, which changes the kit's sound until it is reloaded on the unit (the result's `filter_note`): tell the user.
  - `chords`: a progression in the key playing, from the section's first bar (`"i VI III VII"`, `bars_per_chord`); `"none"` ends it. Sections without `chords` keep the one playing.
  - `transition` (`filter_swap`, `drop_swap`, `riser`) runs over the section's last `transition_bars` bars into the next section (see Transitions below). `filter_swap` closes the cutoff Whiplash last sent; a track it never sent one to is skipped (`skipped_ramps`) unless the section gives `filter_from`.
  - `mix`: a saved mix name or a mix preset, recalled on the section's first bar (see Mix below).
  - The presets carry no transition or mix, so they play exactly as in v0.6.1.
- The result lists each section's `starts_at_bar`, `plays_now` (the groups resolved now), fills, drops, ramps and chords, plus `seconds` and when it `ends`. `whiplash_status.arrangement.current` gives the section playing, `bars_left`, `next` and `next_at_bar`. Read these back instead of guessing.
- Typical request, "make it a 90-second track: intro, build, drop, outro": `whiplash_play_pattern(genre: ...)` if nothing plays, then `whiplash_arrange(preset: "short_demo", seconds: 90)`.

### Forms, section types, energy and moves (v0.9.3)

- **Moves act now and keep playing** (`then: "continue"`), from the next bar. A move while an arrangement runs replaces it (`replaced_arrangement`); `whiplash_undo` brings the old one back in its section.
  - `move: "build"`, `bars` (default 8): the hats come in for the last 4 bars, the kick sits out the last bar under a snare roll, then a 16-bar drop at energy 5. "Build to the drop in 16 bars" is `bars: 16`.
  - `move: "drop"` (`bars` default 16): everything in at energy 5, the saved `drop mix` if there is one (`whiplash_mix(save_as: "drop mix")`), a crash on a cymbal-labelled track.
  - `move: "breakdown"` (`bars` default 16): in the genre's style (below).
  - `move: "slam"`: one bar of only fx, then everything back with a fill. No `bars`.
- **Forms:** `form: "intro 16, groove 16, build 8, drop 16, breakdown 8, drop 16, outro 16"`, or a library form (`whiplash_list_library(kind: "form")`): `deephouse_dj`, `house_jack`, `techhouse_dj`, `techno_plateau`, `progressive_journey`, `melodic_journey`, `minimal_long`, `tropical_song`, or a genre word for its own (`form: "techno"`). Forms stop at their end unless `then` says otherwise. A section that isn't a multiple of 8 bars plays anyway and comes back under `warnings`: pass it on.
- **Section types** (`type` on a section, or a word in a form string) bring their defaults; a section's own keys win:
  - `intro` energy 1, kick and hats, a fill every 8 · `groove` energy 3, everything · `build` rising 2→4 (above) · `breakdown` energy 2, in the genre's style · `drop` energy 5, a fill every 8 · `outro` energy 1, drums, the hats thinning in its last 8 bars.
- **Breakdown styles** by genre: deep house, progressive and melodic techno take kick and bass out; techno drops the kick and keeps the bass; tech house and classic house close the bass's `filter_freq` to 40 over 2 bars and reopen it on the next section (if Whiplash never sent a cutoff it assumes 127, the default; `breakdown_note` says so); tropical drops the drums to energy 1 and keeps the chords; minimal takes out its busiest element besides the kick. Progressive house's result suggests `write_part(phrase: "pad.hold")` for a held breakdown pad: offer it, don't do it unasked.
- **Section keys:** `energy` (1-5 or `"rising"`) moves the groove's level on the section's first bar, like `mutate energy`, and with no `tracks` picks the groups (1 kick and hats; 2 adds perc and bass; 3-5 everything). `fill_every: 8` plays the section's fill (or `fill: "perc.tom_run"`, any fill name) on the last bar of every 8. `enter: {"hats": -4}` brings the hats in at the 4th bar from the end; `exit: {"bass": 9}` takes the bass out from bar 9 of the section.
- **Energy filter** (`energy_filter: true`): the music's `filter_freq` follows each section's energy and a build opens it 20→127. On by default only for progressive house and melodic techno. Like the build ramp it leaves the cutoff changed until the kit is reloaded: tell the user.
- Read back each section's `energy`, `fills_at_bars`, `enter`/`exit` bars, `breakdown` and `does` in the result, and `status.arrangement.current`.

## Transitions: handing over like a DJ

- On a queued switch: `whiplash_play_pattern(genre: "breaks", transition: "filter_swap", transition_bars: 4)`. The transition runs from the next bar line for `transition_bars` bars (1-8), and the switch lands on the bar after them (`switch_at_bar` in the result). Nothing stops: no MIDI Stop/Start.
  - `cut`: today's switch on the next bar line.
  - `filter_swap` (default 4 bars): every outgoing track except kick and bass closes its cutoff (`filter_freq`, CC 74) to 30, the new pattern lands on the one, and each cutoff reopens to where it was over one bar. Whiplash only knows the cutoff it last sent: if it never sent one on a track, the call is refused with a hint. Pass `filter_from` (e.g. 127 if the user says the filters are open) or ask the user.
  - `drop_swap` (default 1 bar): kick and bass sit out the last bar(s), then come back with the switch on the one.
  - `riser` (default 4 bars): every track labelled fx (riser, sweep, noise) gets a rising filter (20 → 127, exp), and the drums fill the last bar. With no fx label it is the fill only; the result says so. The riser leaves that filter at 127 until the kit is reloaded: tell the user.
- Replacing a queued switch cancels its transition (`replaced_transition`); a cutoff it closed reopens at the new switch. `whiplash_stop` mid-transition cancels the ramps and puts each closed cutoff back with one CC (`cutoff_restored`). A fresh start (nothing playing) ignores `transition` (`transition_note`).
- Depends on the filter on the unit: a low-pass closes the highs. On a high-pass or band-pass filter machine the sweep sounds different (not yet checked on hardware).

## Mix: levels and pan (`whiplash_mix`)

- `whiplash_mix(levels: {"6": 95, "kick": 118}, pan: {"hats": "left"})` sends TRACK LEVEL (CC 95, the track's post-FX fader) and PAN (CC 90, 64 = centre) on the next bar line. Keys are track numbers or the arrangement's group words, resolved from the roles playing now. Pan takes 0-127 or `hard left`, `left`, `slightly left`, `center`, `slightly right`, `right`, `hard right`.
- `bars: 4` ramps each change on the clock instead (a track Whiplash never sent a level to jumps on the bar line: `jumps`). A mix change replaces a running ramp on the same track and param.
- `preset`: `auto` (the genre playing, including the v0.9.2 genres' own presets), `techno`, `techhouse`, `deephouse`, `house`, `breaks`, `soul` or `flat` (every role at 100). It sets levels by role and never touches pan.
- `save_as: "drop mix"` stores the mix as it will be after the call (the last values sent plus this call's). `recall: "drop mix"` sends it back exactly, only what differs. Saved mixes survive `whiplash_stop`; status shows `mix.saved`. A section's `mix` recalls one on its first bar.
- Only one CC goes out per change, and only what differs from the last value Whiplash sent. Whiplash can't read the unit's levels: the kit's own come back when the user reloads it. When nothing plays the CCs go out at once.
- Typical requests: "bring the bass down a bit and pan the hats left" → `whiplash_mix(levels: {"bass": 90}, pan: {"hats": "left"})` (ask or read `status.mix.levels` for where the bass is now). "Save this as the drop mix, then go back to it after the break" → `save_as: "drop mix"` now, then `recall: "drop mix"` (or a section's `mix: "drop mix"`).

## Listening: what the unit actually sounds like (`whiplash_listen`)

- **Needs:** USB CONFIG = USB AUDIO/MIDI on the unit (manual 14.8.1, p. 83; MIDI keeps working) with USB OUT = MAIN, the plugin's optional `[listen]` extra (numpy and sounddevice), and on macOS microphone permission for the app that runs Hermes. If one is missing the call fails with a hint: pass it on. Every other tool works without it.
- `whiplash_listen(bars: 2)` captures 1-8 bars (at most 24 s) from the next bar line, or right away when nothing plays, then answers with numbers, never audio:
  - `loudness`: `lufs_ish` (gated, K-weighted, within about a dB of a meter), `peak_dbfs`, `headroom_db`, `clipping`.
  - `bands`: `low` (under 150 Hz), `low_mid`, `mid`, `high` (over 4 kHz), each as a % of the energy.
  - `kick`: how long after Whiplash sent each kick it was heard. A steady few ms is the USB round trip; `spread_ms` is the real timing wobble.
  - `onsets`: hits against Whiplash's 16th grid, corrected by that latency: `on_grid_pct`, `median_abs_offset_ms`, `offbeat_delay_ms` and `swing_estimate` (50 = straight; above 75 it reads low).
  - `low_end.masking`: the low band barely rises on the kicks, so something (usually the bass) sits on the kick.
  - `tracks[n].seems_silent`: notes went out on that track but none of its solo hits came back. `unexpected_audio`: sound while Whiplash sent no notes, usually the unit's own pattern.
  - `notes`: one-line readings. Quote the numbers to the user, then propose a fix and listen again.
- It hears only the USB OUT pair (normally MAIN), so per-track findings are inferred from note timing. Nothing is recorded or stored.
- Typical requests:
  - "Does the bass clash with the kick?" → listen; read `low_end` and `bands.low`; propose the bass down a few steps (`whiplash_mix`) or its filter a little lower; do it; listen again.
  - "It's too loud, fix it without killing the vibe" → listen; lower levels a few steps over `bars: 2` with `whiplash_mix` (no hard cut); listen until `clipping` is false.
  - "Is it in time?" → listen; report `kick.median_offset_ms`, `spread_ms`, `on_grid_pct` and `swing_estimate`.

### Safety rails

- **Loudness guard:** once a listen hears clipping, raising `track_level`, `amp_volume` or `overdrive` (with `whiplash_set_param`, `whiplash_ramp_param` or `whiplash_mix`) is refused until a later listen shows none. A track Whiplash never sent a level to counts as a raise. Lowering is always fine. Pass `force: true` only when the user insists after you told them it clips; the result then carries `guard`.
- At most 48 ramps run at once, and ramp CCs are capped at 1,000 a second (16 per clock tick); a ramp over the cap sends its value a tick later and still ends exactly. `status.safety` shows the caps, the counters and whether the guard is on; `status.listen` the last listen.
- `whiplash_stop` is still the panic button, unchanged.

## Playing along: the user plays, Whiplash reacts (`whiplash_play_along`, `whiplash_follow`, `whiplash_undo`)

- **Turn it on** when the user wants to jam on the unit with you ("play along with me", "watch what I do", "answer me"): `whiplash_play_along`. It opens the Digitakt's MIDI input; nothing else changes. `whiplash_follow` opens it too.
- **The unit only sends if it is set to.** If the result or `status.play_along.hint` says nothing was heard, read them `setup`: SETTINGS > MIDI CONFIG > PORT CONFIG, OUTPUT TO = USB, ENCODER DEST and TRIG KEY DEST = INT+EXT, OUTPUT CH = the track channel (not AUTO), PARAM OUTPUT = CC (manual 14.4, p. 77-79; the names aren't confirmed on hardware yet). With OUTPUT CH = AUTO, moves arrive on the AUTO channel's number, not their track.
- **"What did I just change?"** → `whiplash_status`, `play_along.user_moves` (newest first): read the `said` lines in plain words ("you opened track 6's filter from 40 to 90"). `unsure` means the move came as an NRPN whose address the sources disagree on. `tracks[n].last_cc` stays what *Whiplash* sent; the user's values are only in `user_moves`.
- **Ramps yield.** If the user grabs a knob Whiplash is ramping (same track and param), the ramp stops within a clock tick and their value stands. The next tool result carries `yielded_to_user`: tell them you backed off ("you grabbed the filter, so I stopped my sweep"). Don't restart that ramp unless they ask.
- **Call and response:** "answer whatever I play on track 7, on track 8" → `whiplash_follow(track: 7, answer_track: 8, mode: "answer")`. Ask them to put the unit in KEYBOARD mode on track 7. Each bar they play in is answered on the next bar line on track 8 (that bar replaces track 8's own line):
  - `answer` mirrors their contour and ends on the tonic.
  - `echo` plays it back in key.
  - `harmonize` plays it a diatonic third up.

  Every reply is in the key playing, on the 16th grid, in the native register, at most 16 notes, one per step. The answer track must be melodic: drums, cymbal and fx are refused. `status.play_along.follow.last` shows what was heard and played. `stop: true` ends it, and so do `whiplash_play_along(on: false)` and `whiplash_stop`.
- **"Undo that"** → `whiplash_undo`. It reverts the newest written part, mix, or arrangement change on the next bar line, and `status.undo` lists what can be undone. Undo can't revert:
  - a mix value Whiplash never sent before (`cannot_revert`)
  - a saved mix
  - an `envelope: "note"` CC
  - an arrangement that would already have ended (refused, because it would stop the beat)
  - progressions, mutations, transposes, or anything from before the last stop
- **Recording.** While play-along is on, everything Whiplash sends and hears is kept **in memory** with clock-tick times (`status.play_along.recording`). Export to a `.mid` file is not available yet (v0.8.1, waiting for Phil's OK on file writes). Say so if asked to export.
- Never forward anything heard to the unit. Whiplash only reads the input, and SysEx and program changes from the unit are ignored.

## Writing notes, melodies and rhythms

You **can write melodies and rhythms**: `whiplash_write_part` replaces one track's generated line with the notes you give, from the next bar line. Don't send the user to KEYBOARD mode for a melody.

- **Where the hits go** (pick one):
  - `rhythm`: `four_on_floor` (every beat), `on_kick` (copies track 1's hits), `offbeat_8ths`, `8ths`, `16ths`, `off_16ths`, `syncopated`, `half_time`.
  - `grid`: a 16-cell step mask per bar, `"x..x..x.x..x..x."` (`X` = accent), or a list of up to 4 bars.
  - `steps`: `[0, 3, 6, 10]` (0 = the downbeat, 4 = beat 2, 15 = the last 16th).
  - `hits`: `[{step, note, length, velocity, bar}]` for full control.
  - `lock_to`: another track's hits, copied now (`lock_to: 1` locks a bass to the kick). It doesn't follow later changes to that track.
- **What plays:** `notes` cycle over the hits: `["C5", "D#5", "G5"]`, MIDI numbers, `"."` for a rest, or with `key` (and `scale`) degrees like `"1 3 5 b7"`. C5 = MIDI 60 = the sample's own pitch, so write bass and synth lines **around C5** (roughly C4-C6), not down at C2/C3 where they sound stretched.
- **Shape:** `length` in 16th steps (0.25-16; 1 = a 16th, 4 = a beat), `velocity` (1-127, a list, or `"accent"`), `bars` (1, 2 or 4 before it repeats).
- Examples:
  - Four-on-the-floor bass on track 6: `whiplash_write_part(track: 6, rhythm: "four_on_floor", notes: ["A4"])`.
  - Bass locked to the kick: `whiplash_write_part(track: 6, lock_to: 1, notes: ["A4", "A4", "C5", "G4"])`.
  - A melody: `whiplash_write_part(track: 7, rhythm: "8ths", key: "Am", notes: "1 3 5 8 7 5 3 .", length: 1.5)`.
- Mutes, drops, fills, density, humanize and transpose still apply to a written part. It carries across pattern switches and `whiplash_mutate reset`; `reset: true` brings back the generated line, and `whiplash_stop` clears every written part.
- Tracks 1-16 work. On 9-16, check with the user that the unit's AUTO CHANNEL and FX CONTROL CH aren't on that channel.
- The result echoes each bar as a grid with note names; read it back to the user in their terms.

## Pitch and register (check this first)

- MIDI note **60 plays a sample at its own pitch**, as long as TUNE is 64 and the preset's OCTAVE (FUNC+FLTR > TRACK) is unchanged. Each semitone below pitches the sample down, which makes it slower and grainier. Whiplash can't see OCTAVE or an LFO on tune, so if `pitch` looks right but the sound doesn't, ask the user about those.
- On Grid/Slice machines with SLICE = NOTE, the note picks a slice instead of a pitch, so transpose changes which slice plays.
- Generated melodic parts (bass, chords, stabs) are placed near 60. Each `whiplash_play_pattern` and `whiplash_status` result shows `tracks[n].pitch`, including `semitones_from_native`.
- If a line sounds **stretched, grainy, muddy or distorted**, look at `pitch` before anything else. Raise it with `whiplash_transpose(track, octaves: 1)` or `semitones`, or with `tune` (`whiplash_set_param`, 64 = none, 76 = +12). Do this before you touch the envelope or density.
- Note names follow Elektron's numbering: C0 = MIDI 0, so C5 = MIDI 60. Logic Pro calls 60 "C3" and General MIDI "C4", so quote raw numbers when it matters.
- Transpose works on any track that plays, including written parts on 9-16. On a track that plays nothing it is refused: write the part first.
- Transpose lands on the next bar, carries across pattern switches, and `whiplash_stop` resets it. You can also pass it at start: `whiplash_play_pattern(genre, transpose: {"6": 12})`.

## Patterns, switching and live changes

- Genres: `deephouse` 122 BPM, `chicago` (classic house) 123, `soul` 86, `techno` 130, `breaks` 132, `techhouse` 126 (four on the floor, offbeat open hat, shuffled 16th hats, rolling off-beat bass), `progressivehouse` 124, `melodictechno` 124, `minimal.house` 126, `minimal.techno` 128, `tropicalhouse` 108. "tech house", "tech-house" and similar spellings resolve to `techhouse`; an unknown genre's error lists the closest matches.
- Without labels a pattern assumes 1 kick, 2 rim/snare, 3 clap, 4 closed hat, 5 open hat, 6 bass, 7-8 chords or stabs, and marks those roles `(assumed)`. Ask what the tracks hold before calling a line "bass" or "chords".
- While a pattern plays, `whiplash_play_pattern` queues the new one for the next bar line without stopping the clock (`mode: "queued"`, `switch_at_bar`). Mutes, ramps, drops, transposes, written parts, the progression and the arrangement carry over; mutations reset (density, swing, humanize). `tracks` settings in a queued call land at the switch bar. A different `port` or `send_transport` restarts instead.
- A queued result's `tracks` describe the switch **as it will land**: its own slot, tune, transpose and mute are already in them (`setup_at_switch` marks those), and `muted_at_switch` lists the mutes after the switch. `muted_carried` is what is muted now.
- `whiplash_mutate`: `density` (tracks, amount -1..1 or thin/thicken), `fill` (drum fill on the next bar; shapes follow each track's role, so a kick labelled on track 9 gets the kick fill; with no `tracks` it fills every kick, snare/rim, clap and hat track playing; cymbal and perc tracks only fill when named; melodic tracks are refused), `swing` (50-80), `humanize` (0-1), `drop` (silence tracks for `bars`, then they return; `fill: true` adds a fill on the last dropped bar), `reset` (back to the pattern; written parts stay).
- `whiplash_ramp_param` sweeps on the clock; a new ramp on the same track and param replaces the old one, and `whiplash_stop` cancels all. Ramps on `amp_hold` stop at 126.
- Mutes reset on `whiplash_stop` or a fresh start, so mute after starting (or use `tracks: {"n": {"mute": true}}`).
- `whiplash_stop` silences everything and resets mutes, ramps, mutations, transposes, written parts and any queued switch. The kit map stays.
- With no Digitakt connected Whiplash plays into a virtual port named "Whiplash", which is silent. Results then carry a `warning`: tell the user. `whiplash_open_view` opens a read-only local visualiser if the user wants to watch.

## Sample select

- `whiplash_select_sample(track, slot)` **does switch samples**: it sends CC 19, a slot 0-127 within the sample bank currently selected on the unit. It only picks among samples already loaded in the project.
- Whiplash can't list, name, preview or load samples. Ask the user what a slot holds, or try neighbouring slots and ask how they sound.
- `slot` in status is the last slot Whiplash sent. It is `null` until Whiplash has sent one.

## Note length and the amp envelope

- `whiplash_write_part` sends `length` as the exact MIDI note-off. Every result carries `length_audible`: read it before you promise shorter notes.
- To make length audible, ask the user, then either pass `envelope: "note"` on `whiplash_write_part` (one CC 80 = 127, HOLD = NOTE) or call `whiplash_set_param(track, param: "amp_hold", value: "note")`. The result says `hold: "NOTE"`. For release tails, `amp_mode` 1 (ADSR) plus `amp_release`.
- A note's length only shortens the sound if the track's envelope listens to note-off. That is the case in **AMP MODE = ADSR** (`amp_mode` 1, CC 87) or in **AHD with HOLD = NOTE** (`amp_hold` 127, CC 80). midi.guide lists AHD with HOLD = NOTE as the default, but a given preset may differ, so ask.
- In AHD with a fixed hold (0-126), note-off is ignored and every hit is the same length.
- `amp_hold` 127 is not "the most hold": it switches HOLD to NOTE. So `amp_hold` clamps to 0-126 and ramps never go past 126. Only `"note"` or exactly 127 sends NOTE, and the result says so.
- "Plays non-stop" or "too droney" usually means a long decay (127 = infinite) or a fixed hold on the unit. Shorten `amp_decay`, or (with the user's OK) set `amp_hold` to `"note"` so the note length counts.
- Never change the envelope mode without telling the user. It changes the sound of their kit until they reload it.

## Transport and the unit's own pattern

- By default Whiplash sends MIDI Start, which also starts the Digitakt's own sequencer, so trigs stored in the pattern selected on the unit play on top.
- Unexpected drums or notes that mutes can't silence come from the unit's own pattern. Tell the user to select an empty pattern, or restart with `send_transport: false` (clock only).

## Diagnostics checklist

| Symptom | Check first |
| --- | --- |
| Stretched, grainy, too low | `tracks[n].pitch`, then `whiplash_transpose` up an octave |
| Plays non-stop, droney | amp hold/decay, and `amp_mode` (see above); then shorter `length` in `whiplash_write_part` |
| "Wrong rhythm", "make it 4/4", "lock to the kick" | `whiplash_write_part` with `rhythm` or `lock_to`, not density |
| "Play a melody", "different notes" | `whiplash_write_part` with `notes` (and `key`, or `key: "current"`) |
| "In A minor", "change the chords", "i-VI-III-VII" | `key` on `whiplash_play_pattern` (or key alone on `whiplash_set_progression`), then `whiplash_set_progression` |
| "Deep house chords", "something gospel", "a Chicago groove" | `whiplash_list_library`, then `name` on `whiplash_set_progression` or `groove` on `whiplash_play_pattern` |
| "A bass that follows the chords", "the bass stays on one note" | `whiplash_write_part(phrase: ...)` on the bass track (`whiplash_list_library(kind: "phrase", tag: "bass")`) |
| "phrase brings its own notes" | drop `notes` (and any rhythm/grid) from the call, or write `rhythm` + `notes` instead |
| "Is it boring?", a `taste_hint` | `whiplash_status(review: 16)`; offer one named move, don't apply it unasked |
| "Does the kick cut through?", a review with `listen: null` and a `listen_note` | the listen is too old, from another run or taken while stopped: ask, then `whiplash_listen` and review again |
| A masking or clipping hint | offer its move (`bass.offbeat`, a lower level with `whiplash_mix`); listen again after the user agrees |
| "unknown groove / progression / lane" error | read its `closest:` names, or `whiplash_list_library(kind: ...)`; never guess a name twice |
| "energy needs a groove" | add `groove` (`"A"` is the genre's classic) |
| "has one energy level (3)" (soul.classic, breaks.classic) | switch to a genre with levels, or use `density` |
| "leads stay model-written" on `phrase: "genre"` | write the notes, or name a lead phrase (`arp.chord_up`, `lead.stutter`, ...) if the user asked for one |
| "has no chord phrase" (minimal techno) | expected: it plays without chords; name a phrase (`stab.single`) if the user wants one |
| "Play minimal" sounds like minimal house | expected: bare "minimal" is minimal house; `genre: "minimal techno"` for the other |
| `unplaced` in a play or energy result | that kit has no track for the lane: offer a label (`{"8": "perc"}`), then call again |
| "is a clap part; track 6 ..." (a lane on a melodic track) | put the lane on a drum or perc track |
| A written note came out different (`snapped`) | key lock: `out_of_key: true` if the user wants the chromatic note (or `set_progression(lock: false)` for the session) |
| "Darker", "brighter", "moodier", "more tension", "resolve it" | `whiplash_set_progression(intent: ...)`; read `did` and offer `other_options` |
| intent refused: "hasn't sent filter_freq" (`how: "timbral"`) | ask where the filters are, `whiplash_set_param filter_freq` (127 if open), then again; or `how: "harmonic"` |
| "already at the floor" / "nothing to restore" on an intent | expected: nothing changed; try another `how` from `other_options` |
| "no tension to release" | nothing to undo; the chords play as they were |
| "Change key", "up a tone", "into F minor" | `whiplash_set_progression(key: ...)` with no chords |
| A written melody ignores the chords | `follow: true` on `whiplash_write_part` |
| "Play house" sounds like deep house | expected: bare "house" is deep house; `genre: "chicago"` for classic house |
| "Make it a whole track", "intro, build, drop", "90 seconds" | `whiplash_arrange` (`preset: "short_demo"`, `seconds`), or `form` |
| "Build to the drop", "break it down", "drop it now" | `whiplash_arrange(move: ..., bars: ...)`; the beat keeps going after it |
| "unknown section type" / "unknown move" | use one of the names the error lists |
| "bar 20 is outside build (8 bars)" | `enter`/`exit` bars count inside the section: 1-8, or -1..-8 from its end |
| `warnings` on a form ("is 12 bars") | it plays; mention DJs count in 8, 16 and 32 if the user cares |
| A breakdown "didn't drop the bass" in techno | expected: techno's breakdown drops the kick and keeps the bass |
| `skipped` in status.arrangement ("no longer plays") | the genre changed under a form: section energy only moves the groove it was started on |
| "Switch with a filter swap", "drop the bass then switch", "riser into the drop" | `transition` on `whiplash_play_pattern` (or a section) |
| filter_swap refused: "hasn't sent filter_freq" | ask the user, then `filter_from` (127 if the filters are open) |
| "Bass down", "hats left", "save this mix" | `whiplash_mix` (`levels`, `pan`, `save_as`, `recall`) |
| Highs stayed dark after a stop | read `cutoff_restored` on the stop result; the riser and the build leave filters open until the kit is reloaded |
| A track went quiet after labelling | `routing.vacated` (its part moved to a labelled track) or `replaced_by_written` |
| No fill on a moved drum part | label the track (fills follow roles), or name it in `tracks` |
| Chords sound like one note | expected on an audio track: use two or three chord tracks in `chords` mode |
| Drums you didn't ask for | the unit's own pattern: empty pattern or clock only |
| Wrong instrument on a track | ask the user, label it with `whiplash_label_tracks`, then `whiplash_select_sample` or `tracks: {"n": {"slot": ...}}` |
| Chords on a cymbal, bass on a hat | the pattern's assumed layout: label the tracks with `whiplash_label_tracks` |
| Many calls just to set the kit up | one `whiplash_play_pattern` with `tracks` |
| Silence everywhere | `warning` in a result: virtual port, no Digitakt connected |
| "Does it clip?", "too loud", "is it muddy?", "is it in time?" | `whiplash_listen`, act on the numbers, listen again |
| "Scan my kit", "what's on my tracks?" | stop the beat, `whiplash_scan_kit`, show the proposal; `whiplash_label_tracks` only on the user's yes |
| Level or drive refused: "loudness guard" | lower something and listen again; `force: true` only if the user insists |
| listen: "no Digitakt II audio input" or "numpy is not installed" | pass the hint on: USB CONFIG = USB AUDIO/MIDI, macOS microphone permission, the `[listen]` extra, or `device` |

## What Whiplash can never do

- Send SysEx, read sample names, or load files onto the unit.
- Switch sample banks (CC 24) or machines (Oneshot, Werp, ...).
- Write or save projects, patterns or kits.

## After a plugin update

The Hermes gateway keeps the old plugin code until it restarts, so run `hermes gateway restart`. A new chat is not enough.
