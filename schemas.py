"""Tool schemas shown to the model."""
from .ccmap import PARAMS
from .engine import (BARS_MAX, BPM_MAX, BPM_MIN, CURVES, DROP_BARS_MAX, RAMP_BARS_MAX, RAMP_BEATS_MAX, SWING_MAX,
                     SWING_MIN, TRANSPOSE_MAX)
from .parts import LENGTH_MAX, LENGTH_MIN, SCALES, rhythm_names
from .patterns import MOODS, PATTERNS

TRACK = {"type": "integer", "minimum": 1, "maximum": 16, "description": "Digitakt track number (= MIDI channel), 1-8 used by patterns"}
TRACKS = {"type": "array", "items": {"type": "integer", "minimum": 1, "maximum": 16},
          "description": ("Track numbers 1-16 (patterns assume 1 kick, 2 rim/snare, 3 clap, 4 closed hat, 5 open hat, "
                          "6 bass, 7-8 chords; 9-16 only play written parts)")}
NOTE = {"type": ["string", "integer"]}
PARAM = {"type": "string", "description": f"Named Digitakt II param (see whiplash_list_params), e.g. {', '.join(list(PARAMS)[:8])}, ..."}
EMPTY = {"type": "object", "properties": {}}
SKILL = " See skill whiplash:digitakt for pitch, sample, envelope and transport guidance."

SCHEMAS = {
    "whiplash_list_midi_ports": {
        "name": "whiplash_list_midi_ports",
        "description": ("List MIDI input/output ports and whether an Elektron Digitakt II is connected over USB. "
                        "A 'warning' in the result means no Digitakt was found."),
        "parameters": EMPTY,
    },
    "whiplash_list_params": {
        "name": "whiplash_list_params",
        "description": ("List the named Digitakt II sound parameters, grouped (track, src, filter, amp, fx, lfo), with "
                        "CC number, range, whether 64 is centre, and aliases. Use the names with whiplash_set_param "
                        "and whiplash_ramp_param."),
        "parameters": EMPTY,
    },
    "whiplash_play_pattern": {
        "name": "whiplash_play_pattern",
        "description": ("Start a generated beat on the Digitakt II tracks 1-8 (MIDI channels 1-8) with MIDI clock "
                        "and start/stop, in the background. Pick by genre or mood. If a pattern is already playing, "
                        "the new one is queued and swaps in on the next bar line without stopping the clock "
                        "(mode 'queued', with switch_at_bar); mutes, ramps and drops carry over, mutations "
                        "(density/swing/humanize) reset. Passing a different port restarts on that port. Falls back "
                        "to a virtual MIDI port named 'Whiplash' when no Digitakt is connected: the result then "
                        "carries a 'warning' and the hardware is silent. MIDI Start also starts the Digitakt's own "
                        "sequencer, so trigs in the pattern selected on the unit play on top: every result carries "
                        "an overlap_warning to pass on (select an empty pattern on the unit, or use "
                        "send_transport=false). Melodic parts play near note 60, the sample's own pitch; the result's "
                        "tracks[n].pitch shows each line's register, and track roles are assumed, not read from the "
                        "unit. If the user wants to watch the beat, whiplash_open_view shows it live in a local "
                        "browser page." + SKILL),
        "parameters": {"type": "object", "properties": {
            "genre": {"type": "string", "enum": sorted(PATTERNS), "description": "Pattern genre"},
            "mood": {"type": "string", "description": f"Mood word if no genre, e.g. {', '.join(sorted(MOODS))}"},
            "bpm": {"type": "number", "minimum": BPM_MIN, "maximum": BPM_MAX,
                    "description": "Tempo; default is the genre's. On a live switch it applies at the switch."},
            "bars": {"type": "integer", "minimum": 1, "maximum": BARS_MAX, "description": "Stop after N bars; omit to loop until stop"},
            "port": {"type": "string", "description": "Exact output port name (optional; auto-detects Digitakt)"},
            "send_transport": {"type": "boolean",
                               "description": ("true (default, or WHIPLASH_SEND_TRANSPORT): send MIDI Start/Stop "
                                               "with the clock. false: clock only, no Start and no Stop, so the "
                                               "Digitakt's own sequencer stays stopped. Changing it while playing "
                                               "restarts instead of queueing.")},
            "transpose": {"type": "object",
                          "additionalProperties": {"type": "integer", "minimum": -TRANSPOSE_MAX, "maximum": TRANSPOSE_MAX},
                          "description": ('Per-track transpose in semitones, e.g. {"6": -12, "7": 5}. Applies from '
                                          "the first bar (or the switch bar when queued) and carries across switches "
                                          "until whiplash_stop.")},
        }},
    },
    "whiplash_set_param": {
        "name": "whiplash_set_param",
        "description": ("Change a sound parameter on one Digitakt II track instantly. Use a named param "
                        "(whiplash_list_params; sent as CC, clamped into its range) or a raw cc / nrpn [msb, lsb]. "
                        "Give exactly one of param, cc or nrpn. Cancels a running ramp on the same param."),
        "parameters": {"type": "object", "required": ["track", "value"], "properties": {
            "track": TRACK,
            "param": PARAM,
            "cc": {"type": "integer", "minimum": 0, "maximum": 119, "description": "Raw CC number"},
            "nrpn": {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 127},
                     "minItems": 2, "maxItems": 2, "description": "Raw NRPN address [msb, lsb]"},
            "value": {"type": "integer", "minimum": 0, "maximum": 16383,
                      "description": ("0-127 for param and cc. For nrpn, the full 14-bit value 0-16383 "
                                      "(data MSB = value >> 7, LSB = value & 127); a 7-bit amount v is v * 128")},
        }},
    },
    "whiplash_select_sample": {
        "name": "whiplash_select_sample",
        "description": ("Switch which sample a track plays, among samples already loaded in the Digitakt II "
                        "project's sample pool (e.g. put a pad on track 7). Sends Sample Slot Select (CC 19) with "
                        "the slot number 0-127 within the sample bank currently selected on the unit. Whiplash "
                        "can't list, preview or hear samples, and can't load new ones: ask the user which slot "
                        "holds what, or try slots and listen. The unit's SMP list starts with OFF (no sound). "
                        "Same as whiplash_set_param with param 'sample_slot'."),
        "parameters": {"type": "object", "required": ["track", "slot"], "properties": {
            "track": TRACK,
            "slot": {"type": "integer", "minimum": 0, "maximum": 127,
                     "description": "Sample slot 0-127 in the unit's current sample bank"},
        }},
    },
    "whiplash_transpose": {
        "name": "whiplash_transpose",
        "description": ("Move one track's notes up or down from the next bar line, keeping the line's intervals. "
                        "Use it when a bass or synth sounds stretched, grainy or too low: note 60 is the sample's own "
                        "pitch, and the result's pitch block shows how far the line sits from it. Absolute (0 = back "
                        "to the pattern). Carries across pattern switches; whiplash_stop resets it. Notes clamp to "
                        "16-84, the manual's documented chromatic range. Needs a pattern playing." + SKILL),
        "parameters": {"type": "object", "required": ["track"], "properties": {
            "track": TRACK,
            "semitones": {"type": "integer", "minimum": -TRANSPOSE_MAX, "maximum": TRANSPOSE_MAX,
                          "description": "Transpose in semitones (give this or octaves)"},
            "octaves": {"type": "integer", "minimum": -(TRANSPOSE_MAX // 12), "maximum": TRANSPOSE_MAX // 12,
                        "description": "Transpose in whole octaves (give this or semitones)"},
        }},
    },
    "whiplash_write_part": {
        "name": "whiplash_write_part",
        "description": ("Write a track's own notes, melody or rhythm, replacing its generated line from the next bar "
                        "line. Use it for 'play a melody', 'make the bass four on the floor', 'lock the bass to the "
                        "kick' or 'shorter notes'. Give ONE of rhythm (preset), grid ('x..x..x.x...x...', one "
                        "16-step bar or a list of up to 4), steps ([0, 3, 6, 10]), hits ([{step, note, length, "
                        "velocity, bar}]) or lock_to (copy another track's hits now; rhythm 'on_kick' = lock_to 1). "
                        "notes cycle over the hits: names in Elektron octaves (C5 = MIDI 60 = the sample's own "
                        "pitch), MIDI numbers, '.' for a rest, or scale degrees ('1 3 5 b7') when key is given. "
                        "length is the exact note-off in 16th steps, but it is only audible if the track's AMP MODE "
                        "is ADSR or HOLD is NOTE: read length_audible in the result; envelope 'note' sets HOLD = "
                        "NOTE (one CC 80 = 127) when the user agrees. Mutes, drops, fills, density, humanize and "
                        "transpose still apply. The part carries across pattern switches and whiplash_mutate reset; "
                        "reset: true or whiplash_stop returns the generated line. Tracks 1-16; needs a pattern "
                        "playing. Bad input changes nothing." + SKILL),
        "parameters": {"type": "object", "required": ["track"], "properties": {
            "track": {**TRACK, "description": "Digitakt track 1-16 (= MIDI channel)"},
            "rhythm": {"type": "string", "enum": rhythm_names(),
                       "description": ("Rhythm preset: four_on_floor (every beat), on_kick (copy track 1's hits), "
                                       "offbeat_8ths, 8ths, 16ths, off_16ths, syncopated (x..x..x...x..x..), "
                                       "half_time (steps 0 and 8)")},
            "grid": {"type": ["string", "array"], "items": {"type": "string"},
                     "description": ("Step mask, 16 cells per bar: x = hit, X = accented hit, . = rest (spaces and | "
                                     "ignored). One string, or a list of up to 4 bars.")},
            "steps": {"type": "array", "items": {"type": ["integer", "array"]},
                      "description": "Steps 0-15 (0 = downbeat, 4 = beat 2) for one bar, or one list per bar (up to 4)"},
            "hits": {"type": "array", "maxItems": 64, "items": {"type": "object", "required": ["step"], "properties": {
                "step": {"type": "integer", "minimum": 0, "maximum": 15}, "note": NOTE,
                "length": {"type": "number", "minimum": LENGTH_MIN, "maximum": LENGTH_MAX},
                "velocity": {"type": "integer", "minimum": 1, "maximum": 127},
                "bar": {"type": "integer", "minimum": 1, "maximum": 4, "description": "1-4, default 1"}}},
                     "description": "Individual hits; per-hit note/length/velocity override the shared ones"},
            "lock_to": {"type": "integer", "minimum": 1, "maximum": 16,
                        "description": "Copy this track's current hits (1 = the kick); not followed live"},
            "notes": {"type": ["array", "string"], "items": NOTE,
                      "description": ("Notes cycled over the hits, e.g. ['C5', 'D#5', 'G5', 63] or 'A4 C5 . E5'. "
                                      "Elektron names (C5 = 60), MIDI 16-84, '.' = rest, or degrees with key. "
                                      "Omit for note 60 (drums, one-shots).")},
            "key": {"type": "string",
                    "description": ("Root for scale degrees, e.g. 'A', 'F#', 'Am' (minor), 'A3' (explicit octave). "
                                    "Without an octave the root sits nearest note 60.")},
            "scale": {"type": "string", "enum": sorted(SCALES),
                      "description": "Scale for degrees (default major, or minor for keys like 'Am'). b/# move a degree by a semitone."},
            "length": {"type": ["number", "array"], "items": {"type": "number"},
                       "description": (f"Note length in 16th steps, {LENGTH_MIN:g}-{LENGTH_MAX:g} (1 = a 16th, 4 = a "
                                       "beat), default 1; a list cycles over the hits. Exact MIDI note-off.")},
            "velocity": {"type": ["integer", "array", "string"], "items": {"type": "integer"},
                         "description": "1-127 (default 100), a list cycled over the hits, or 'accent' (120 on the beats, 90 between)"},
            "bars": {"type": "integer", "enum": [1, 2, 4],
                     "description": "Bars before the part repeats (default: the shortest that plays every note)"},
            "reset": {"type": "boolean", "description": "true: drop the written part and go back to the generated line"},
            "envelope": {"type": "string", "enum": ["note"],
                         "description": ("'note': also send amp_hold 127 (HOLD = NOTE, CC 80) so length is audible "
                                         "in AHD mode. Changes the kit's sound until reloaded; only when the user agrees.")},
        }},
    },
    "whiplash_ramp_param": {
        "name": "whiplash_ramp_param",
        "description": ("Sweep a sound parameter smoothly from one value to another over beats or bars, locked to "
                        "the running MIDI clock (e.g. 'slowly open the filter over 8 bars'). Needs a pattern "
                        "playing. Ramps on different track/param pairs run together; a new ramp on the same pair "
                        "replaces the old one. Returns a ramp_id. Cancel with cancel: '<ramp_id>' or 'all' "
                        "(the param stays where it got to); whiplash_stop cancels all."),
        "parameters": {"type": "object", "properties": {
            "track": TRACK,
            "param": PARAM,
            "cc": {"type": "integer", "minimum": 0, "maximum": 119, "description": "Raw CC number instead of param"},
            "from": {"type": "integer", "minimum": 0, "maximum": 127,
                     "description": "Start value; default is the last value Whiplash sent for this track/param"},
            "to": {"type": "integer", "minimum": 0, "maximum": 127, "description": "Target value"},
            "beats": {"type": "number", "exclusiveMinimum": 0, "maximum": RAMP_BEATS_MAX,
                      "description": "Duration in beats (quarter notes). Give beats or bars, not both."},
            "bars": {"type": "number", "exclusiveMinimum": 0, "maximum": RAMP_BARS_MAX, "description": "Duration in bars"},
            "curve": {"type": "string", "enum": sorted(CURVES),
                      "description": "linear (default), exp (slow start, fast finish), log (fast start, gentle finish)"},
            "cancel": {"type": "string", "description": "Cancel a ramp by id, or 'all'. Other arguments are ignored."},
        }},
    },
    "whiplash_mutate": {
        "name": "whiplash_mutate",
        "description": ("Edit the running pattern live without stopping, timed to the bar. Actions: "
                        "density (tracks + amount -1 thinnest..0 original..1 busiest, or 'thin'/'thicken'); "
                        "fill (one-bar drum fill on the next bar: snare roll, hat ratchets, kick sits out; tracks "
                        "default to 1-5); swing (amount 50-80 percent); humanize (amount 0-1 velocity and "
                        "micro-timing looseness, never drifts); drop (silence tracks for 'bars' bars from the next "
                        "bar, then they come back by themselves; fill: true adds a fill on the last dropped bar); "
                        "reset (back to the original pattern; parts written with whiplash_write_part stay). Mutations "
                        "last until reset or a new pattern; mutes are separate. density and drop take tracks 1-16."),
        "parameters": {"type": "object", "required": ["action"], "properties": {
            "action": {"type": "string", "enum": ["density", "fill", "swing", "humanize", "drop", "reset"]},
            "tracks": TRACKS,
            "amount": {"type": ["number", "string"], "description": "density: -1..1 or thin/thicken; swing: 50-80; humanize: 0-1"},
            "bars": {"type": "integer", "minimum": 1, "maximum": DROP_BARS_MAX, "description": "drop: how many bars (default 2)"},
            "fill": {"type": "boolean", "description": "drop: also play a drum fill on the last dropped bar"},
        }},
    },
    "whiplash_mute_track": {
        "name": "whiplash_mute_track",
        "description": ("Mute a track live (Whiplash stops sending its notes; optionally also sends Digitakt CC94 "
                        "mute). Mutes carry over live pattern switches and reset on whiplash_stop or a fresh start, "
                        "so mute after whiplash_play_pattern, not before."),
        "parameters": {"type": "object", "required": ["track"], "properties": {
            "track": TRACK, "hardware": {"type": "boolean", "description": "Also toggle the unit's own track mute (CC94)"}}},
    },
    "whiplash_unmute_track": {
        "name": "whiplash_unmute_track",
        "description": ("Unmute a track muted with whiplash_mute_track. Also releases the unit's own "
                        "mute if Whiplash set it."),
        "parameters": {"type": "object", "required": ["track"], "properties": {
            "track": TRACK, "hardware": {"type": "boolean", "description": "Also send CC94 unmute to the unit"}}},
    },
    "whiplash_set_tempo": {
        "name": "whiplash_set_tempo",
        "description": f"Change the tempo live ({BPM_MIN}-{BPM_MAX} BPM); the MIDI clock follows so the Digitakt's FX sync.",
        "parameters": {"type": "object", "required": ["bpm"], "properties": {
            "bpm": {"type": "number", "minimum": BPM_MIN, "maximum": BPM_MAX}}},
    },
    "whiplash_stop": {
        "name": "whiplash_stop",
        "description": ("Stop playback: note-offs, All Notes Off on channels 1-8, and MIDI transport Stop (not in "
                        "clock-only mode, so a pattern running on the unit isn't halted). "
                        "Also resets mutes, ramps, mutations, transposes, written parts and any queued switch. Safe to call when nothing is "
                        "playing (acts as a panic button)."),
        "parameters": EMPTY,
    },
    "whiplash_status": {
        "name": "whiplash_status",
        "description": ("Show what Whiplash is doing: port (and whether it is the silent virtual fallback, or a "
                        "Digitakt that has become available), transport_mode (start_stop or clock_only), pattern, bpm, bar, queued switch, muted tracks, active "
                        "ramps with progress, mutations, and last_error if the sequencer stopped on a fault. tracks "
                        "gives each track in use: assumed role, last sample slot and tune Whiplash sent, transpose, "
                        "pitch (distance from the sample's own pitch), mute, part (generated or written) and last CCs. "
                        "parts lists the written parts." + SKILL),
        "parameters": EMPTY,
    },
    "whiplash_open_view": {
        "name": "whiplash_open_view",
        "description": ("Open the Whiplash visualiser: a local web page (http://127.0.0.1 only) in the default browser "
                        "that shows the beat live while the chat continues here: every track in use with its notes "
                        "and playhead, BPM, bar, queued switches, mutes, drops, fills, ramps, the MIDI port, an "
                        "audio spectrum/scope (from the Digitakt's USB audio if the user allows it, else clearly "
                        "labelled MIDI fallback) and this conversation. Read-only: it never sends MIDI or changes "
                        "the beat. Works with or without a pattern playing. Use when the user asks to launch, open "
                        "or show the visualiser/view. Calling it again just reopens the browser on the same page."),
        "parameters": {"type": "object", "properties": {
            "port": {"type": "integer", "minimum": 1024, "maximum": 65535,
                     "description": "Local TCP port (default 7341, or a free one if that is taken)"},
            "open_browser": {"type": "boolean", "description": "Open the default browser (default true); false only returns the URL"},
        }},
    },
    "whiplash_close_view": {
        "name": "whiplash_close_view",
        "description": "Close the Whiplash visualiser's local web server. The beat keeps playing.",
        "parameters": EMPTY,
    },
}
