# Hackathon live demo: Whiplash on a Digitakt II (about 3 minutes)

One run of prompts, typed live into Hermes, with the Digitakt II on the table and the visualiser on the projector. It follows the hardware checklist's smoke test ([Part A](../testing/hardware-checklist.md#a-smoke-test-and-demo-path-10-minutes)) prompt for prompt, so **run Part A on the unit before you go on stage**. If A passes, this script is safe. None of this is hardware-verified until that run is recorded in [docs/digitakt-ii/reference.md](../digitakt-ii/reference.md).

**Rehearse first: `uv run python scripts/rehearse_demo.py`** (about 30 s, no unit needed). It makes the same tool calls as the run below against a recording port, writes `demo.mid` and `report.txt`, and must end in `RESULT: PASS` (exit 0). It runs in its own process with its own visualiser port, so it doesn't disturb a running Hermes. It uses project 6's labels below and checks the plugin, not the unit: Part A on the Digitakt is still the real test.

The pitch in one line: *the model makes one validated call; Whiplash's own MIDI clock does the music, so every change lands on the beat however long the model takes to answer.*

The kit lines below are for Phil's project 6 (tracks 7-8 tuned cymbals, slot 9 a dirty bass, slot 11 a synth). For another kit, change only the labels in step 2.

---

## Setup (before the slot, about 5 min)

**Laptop**

```bash
git -C ~/whiplash pull            # or: hermes plugins update whiplash
(cd ~/whiplash && uv run python scripts/rehearse_demo.py -q)  # rehearse; must print RESULT: PASS
hermes gateway restart            # required after any update; a new chat is not enough
hermes plugins list               # whiplash enabled, v0.6.1, 19 tools
```

- Start a **new chat** in Hermes, so the kit map and the conversation are empty.
- Terminal on the left third of the screen, browser on the right (narrower than 1100 px turns the chat into lower-third captions, which reads well on a projector).
- Turn on Do Not Disturb. The visualiser shows the conversation, so close anything you don't want on screen; `B` blurs the chat if needed.

**Digitakt II**

- USB to the laptop. SETTINGS > MIDI CONFIG: RECEIVE NOTES and CC/NRPN on, CLOCK RECEIVE and TRANSPORT RECEIVE on, AUTO CHANNEL and FX CONTROL CH off channels 1-8. USB CONFIG = USB AUDIO/MIDI if you want the real VU.
- Load the demo project and **select an empty pattern**, so MIDI Start doesn't layer the unit's own trigs in.
- [FUNC] + [NO] to reload the pattern, so TUNE is 64 and no earlier edit lingers.
- Main outs to the PA, levels checked with a quick *"Play techno"* / *"Stop"* (then start a new chat again).

---

## The run

Type each prompt as written. Times are cumulative and approximate; each Hermes turn takes a few seconds, and the music keeps going while it thinks.

| Time | Type | Audience hears | Audience sees (visualiser) |
| --- | --- | --- | --- |
| 0:00 | *"Is my Digitakt connected? And launch the visualiser."* | Nothing yet. | The idle rack opens: tape transport, hub, master OUT, the port name *Elektron Digitakt II*. Click **CONNECT AUDIO** (or press `A`) once for a real VU needle. |
| 0:15 | *"Tracks 7 and 8 are tuned cymbals. Sample slot 9 is my dirty bass, and slot 11 is a synth I like."* | Nothing (labels are memory only; nothing is sent to the unit). | Say it: *"Whiplash can't read sample names off the unit without SysEx, which it never sends, so it asks me."* |
| 0:30 | *"Play some groovy deep house with the dirty bass on track 6."* | Deep house at 122 BPM with swing: kick, rim, clap, hats, the dirty bass. **No chords on the cymbals**: the chord parts are dropped, the open-hat rhythm moves to the tuned cymbal on 7. | Modules light up and fire in time. 7 and 8 carry your labels in white; 6 shows `SMP 009 dirty bass`; 8 says `NO PART`. One tool call did the start and the sample switch. |
| 0:50 | *"Close the filter on the bass, then open it slowly over 8 bars."* | The bass goes muffled, then opens up smoothly over 8 bars, locked to the tempo. | The FLT knob on module 6 turns toward its target tick. |
| 1:10 | *"Give track 8 a melody: eighth notes in A minor, degrees 1 3 5 8 7 5 3 1, length 2."* | From the next bar line, the tuned cymbal plays an arpeggio up and back down. | Module 8 swaps `NO PART` for `WR`, flashes, and its strip becomes a piano roll with those notes. |
| 1:35 | *"Drop the kick and bass for two bars with a fill."* | Kick and bass vanish on the next bar, the cymbal melody hangs in the air, a snare roll and hat ratchets build, and kick and bass **slam back on the one**. | Modules 1 and 6 show `DROP <2`, `<1`, flash inverted, then come back. |
| 1:55 | *"Switch to tech house on the next bar."* | At the next bar line, no stop, no gap: 126 BPM tech house, four on the floor, rolling off-beat bass (still the dirty bass), the cymbal melody carrying over. The unit's delay keeps ringing in time. | The transport counts down the queued switch, then the BPM readout rolls from 122 to 126. |
| 2:20 | *"What's playing?"* | Tech house carries on. | Hermes answers in your terms: your labels, slot 9 "dirty bass", the written melody on 8. Point out that roles are no longer "(assumed)". |
| 2:40 | *"Stop."* | Clean silence, no hanging notes. | The reels stop; the hub goes still. |

Close with the line: *"Every change landed on the bar, whatever the model's latency. Whiplash never saves to the unit, never sends SysEx or program changes, and the visualiser only watches."*

### Optional encore: a chord progression (+30 s, v0.6.0)

Only if the slot has time left **and** checklist P1 passed on the unit. Rehearse it with `uv run python scripts/rehearse_demo.py --v06` (the default rehearsal leaves it out). It starts from stop, after the run above.

| Time | Type | Audience hears | Audience sees (visualiser) |
| --- | --- | --- | --- |
| +0:00 | *"Track 7 is a pad now. Play deep house in A minor with the dirty bass on 6 and my synth on 7: i-VI-III-VII, two bars per chord."* | Deep house again, the synth on 7 playing chord tones, the bass following the roots. The chord changes every 2 bars, on the one: Am, F, C, G. The drums and the cymbal on 8 don't change. | The **KEY** module appears: `A MINOR`, cells `i VI III VII` with the chord names. The playing chord is lit and moves on the bar; the next one counts down four beats. Modules 6 and 7 show `ROOT` and `CHD` lines with the notes they play in this chord. |
| +0:25 | *"Stop."* | Clean silence. | The KEY module goes away with the beat. |

Say it: *"The chords are note numbers rewritten at the bar line. Nothing on the unit changes: no scale, no root note, no saves."*

### Optional beat: a 30-second track that ends itself (+35 s, v0.6.1)

Only if the slot has time left **and** checklist R1 passed on the unit. Rehearse it with `uv run python scripts/rehearse_demo.py --v061` (the default rehearsal leaves it out). It starts from stop, after the run above (or after the encore). It is the closer: there is no "Stop" to type.

| Time | Type | Audience hears | Audience sees (visualiser) |
| --- | --- | --- | --- |
| +0:00 | *"Play techno, and make it a 30-second track: intro, build, drop, outro."* | Techno at 130 BPM from the next bar, 4 bars per section: **intro**, kick, hats and the tuned cymbal; **build**, rim and clap come in on the one, the kick sitting out the last bar; **drop**, the bass slams in on the one; **outro**, drums only. Each section but the outro ends on a fill. | Modules mute and unmute on each section's bar line. |
| +0:10 | *"Which section are we in?"* (optional) | The track carries on. | Hermes names the section, the bars left and what's next. |
| +0:30 | (nothing) | It **stops by itself** on the bar line after the outro: clean silence, no hanging notes. | The reels stop. |

Say it: *"The arrangement is Whiplash muting and unmuting on its own clock. The unit's song mode and patterns are never touched."* On this kit the build sends no filter ramp (there are no music tracks to open), so nothing new needs reloading; [FUNC] + [NO] afterwards as usual.

---

## If something misbehaves

Keep the music going and fix it with one prompt. Each of these is safe to type mid-beat.

| Symptom | Type this |
| --- | --- |
| Hermes starts deep house, then calls `whiplash_select_sample` separately | Fine, carry on. It's one extra call, not a failure. |
| The bass sounds stretched or grainy | *"Transpose the bass on track 6 up an octave."* |
| The dirty bass sounds wrong on stage | *"Put my synth on track 6."* (slot 11) |
| Drums or notes you didn't ask for, that mutes can't silence | The unit's own pattern is playing. *"Stop"*, select an empty pattern on the unit, then *"Play deep house, clock only, with the dirty bass on track 6."* |
| Hermes put chords on the cymbals (labels not applied) | *"Tracks 7 and 8 are tuned cymbals; re-route the beat."* It applies from the next bar. |
| The melody on track 8 isn't audible, or sounds bad on the cymbal | *"Put my synth on track 8."* Or skip ahead: *"Write that melody on track 6 instead."* |
| The melody notes all sound the same length | Expected with a fixed AMP HOLD. Don't change the envelope on stage. |
| "tech house" errors or picks another genre | *"Switch to techhouse on the next bar."* (one word), or *"Switch to techno on the next bar."* |
| A filter sweep is still running when you want it gone | *"Cancel all ramps."* |
| Results say `warning`: virtual port, silent | The Digitakt isn't the output. *"Is my Digitakt connected?"*, then *"Play deep house on the Digitakt."* |
| Encore: the chords sound out of tune or thin on track 7 | *"Stop."* and skip the encore. (A one-voice audio track plays one chord tone per hit: checklist P2/P3.) |
| The visualiser froze or closed | Keep playing; the beat doesn't depend on it. *"Launch the visualiser"* again, or reload the browser tab. |
| Hermes is slow to answer | Keep talking; the beat is on Whiplash's clock and doesn't wait for the model. |

## Recovery

- **Anything sounds stuck or hanging:** *"Stop."* Whiplash sends note-offs for every sounding note, All Notes Off (CC 123) on channels 1-8 and on any 9-16 it played, and MIDI Stop. It works as a panic button even when nothing is playing.
- **Still a sound after Stop:** press [STOP] on the unit. If a long envelope rings on, turn the track's level down on the unit.
- **Hermes stops responding:** press [STOP] on the unit, then `hermes gateway restart` in a second terminal. The kit map is cleared by the restart, so retype step 2.
- **USB cable knocked out:** replug, wait for the unit, then *"Play deep house again on the Digitakt."* Whiplash re-detects the port; it never switches ports by itself.
- **After the demo:** [FUNC] + [NO] on the unit to reload the pattern, and **don't save the project**. Every parameter change (the slot 9 bass, the filter) sits in the active pattern's kit until you reload. Whiplash never saves anything.
