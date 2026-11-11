"""Tool schemas shown to the model."""
from .ccmap import PARAMS
from .engine import (BARS_MAX, BPM_MAX, BPM_MIN, CURVES, DROP_BARS_MAX, RAMP_BARS_MAX, RAMP_BEATS_MAX, SWING_MAX,
                     SWING_MIN, TRANSPOSE_MAX)
from .arrange import GROUPS, PRESETS, RAMPS_MAX, SECONDS_MAX, SECONDS_MIN, SECTION_BARS_MAX, SECTIONS_MAX
from .mixer import MIX_BARS_MAX, PRESETS as MIX_PRESETS
from .transition import BARS_MAX as TX_BARS_MAX, KINDS as TX_KINDS
from .harmony import BARS_PER_CHORD_MAX, MAX_CHORDS, MODES, VOICINGS
from .parts import LENGTH_MAX, LENGTH_MIN, SCALES, rhythm_names
from .kitmap import ROLES
from .patterns import MOODS, PATTERNS

TRACK = {"type": "integer", "minimum": 1, "maximum": 16, "description": "Track 1-16 (= MIDI channel)"}
TRACKS = {"type": "array", "items": {"type": "integer", "minimum": 1, "maximum": 16}, "description": "Tracks 1-16"}
NOTE = {"type": ["string", "integer"]}
PARAM = {"type": "string", "description": f"Named Digitakt II param (see whiplash_list_params), e.g. {', '.join(list(PARAMS)[:8])}, ..."}
EMPTY = {"type": "object", "properties": {}}
SKILL = " Details: skill whiplash:digitakt."
KEY = {"type": "string", "description": "Key root, e.g. 'A', 'F#', 'Bb', 'Am' (minor)"}
SCALE = {"type": "string", "enum": sorted(SCALES), "description": "Default major, or minor for keys like 'Am'"}
MIX_MAP = {"type": "object", "additionalProperties": {"type": ["integer", "string"]}}
TRANSITION = {"type": "string", "enum": list(TX_KINDS)}
TX_BARS = {"type": "integer", "minimum": 1, "maximum": TX_BARS_MAX, "description": "Default 4 (drop_swap 1)"}
FILTER_FROM = {"type": "integer", "minimum": 0, "maximum": 127,
               "description": "filter_swap: cutoff where Whiplash hasn't sent one"}

SCHEMAS = {
    "whiplash_list_midi_ports": {
        "name": "whiplash_list_midi_ports",
        "description": "List MIDI ports and whether a Digitakt II is connected.",
        "parameters": EMPTY,
    },
    "whiplash_list_params": {
        "name": "whiplash_list_params",
        "description": "List the named sound params (CC, range, alias).",
        "parameters": EMPTY,
    },
    "whiplash_play_pattern": {
        "name": "whiplash_play_pattern",
        "description": ("Start a beat (genre or mood), or queue a switch on the next bar if one plays. key/scale set its "
                        "key; tracks sets each track's slot, tune, transpose and mute in the same call. Pass the "
                        "result's overlap_warning (and any 'warning': virtual port, hardware silent) on to the user. "
                        "Roles follow whiplash_label_tracks." + SKILL),
        "parameters": {"type": "object", "properties": {
            "genre": {"type": "string", "enum": sorted(PATTERNS), "description": "Pattern genre"},
            "mood": {"type": "string", "description": f"Mood word if no genre, e.g. {', '.join(sorted(MOODS))}"},
            "bpm": {"type": "number", "minimum": BPM_MIN, "maximum": BPM_MAX,
                    "description": "Default: the genre's"},
            "bars": {"type": "integer", "minimum": 1, "maximum": BARS_MAX, "description": "Stop after N bars; omit to loop until stop"},
            "port": {"type": "string", "description": "Output port (default: auto-detect)"},
            "send_transport": {"type": "boolean",
                               "description": "false: clock only, so the unit's own sequencer stays stopped"},
            "transpose": {"type": "object",
                          "additionalProperties": {"type": "integer", "minimum": -TRANSPOSE_MAX, "maximum": TRANSPOSE_MAX},
                          "description": 'Semitones per track, e.g. {"6": -12}'},
            "key": KEY,
            "scale": SCALE,
            "tracks": {"type": "object", "additionalProperties": {"type": "object", "properties": {
                "slot": {"type": "integer", "minimum": 0, "maximum": 127},
                "tune": {"type": "integer", "minimum": 0, "maximum": 127, "description": "64 = none"},
                "transpose": {"type": "integer", "minimum": -TRANSPOSE_MAX, "maximum": TRANSPOSE_MAX},
                "mute": {"type": "boolean"}}},
                       "description": ('Per-track setup sent with the start or at the switch bar, e.g. '
                                       '{"6": {"slot": 9, "transpose": 12}, "8": {"mute": true}}')},
            "transition": {**TRANSITION, "description": "Queued switch: hand over over transition_bars, then switch"},
            "transition_bars": TX_BARS,
            "filter_from": FILTER_FROM,
        }},
    },
    "whiplash_set_param": {
        "name": "whiplash_set_param",
        "description": ("Set one sound param on a track now: named param, or raw cc / nrpn. amp_hold 127 ('note') switches "
                        "HOLD to NOTE; send it only when the user agrees."),
        "parameters": {"type": "object", "required": ["track", "value"], "properties": {
            "track": TRACK,
            "param": PARAM,
            "cc": {"type": "integer", "minimum": 0, "maximum": 119, "description": "Raw CC number"},
            "nrpn": {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 127},
                     "minItems": 2, "maxItems": 2, "description": "Raw NRPN address [msb, lsb]"},
            "value": {"type": ["integer", "string"], "minimum": 0, "maximum": 16383,
                      "description": "0-127; nrpn 0-16383 (14-bit); 'note' only for amp_hold"},
        }},
    },
    "whiplash_select_sample": {
        "name": "whiplash_select_sample",
        "description": ("Switch a track to a sample already loaded in the project (CC 19 slot, current bank). Whiplash "
                        "can't list or hear samples: ask the user what a slot holds."),
        "parameters": {"type": "object", "required": ["track", "slot"], "properties": {
            "track": TRACK,
            "slot": {"type": "integer", "minimum": 0, "maximum": 127,
                     "description": "0-127 in the current bank"},
        }},
    },
    "whiplash_label_tracks": {
        "name": "whiplash_label_tracks",
        "description": ("Record what the user says each track and slot holds (e.g. track 7 cymbal, 5 pad), as soon as they "
                        "describe their kit. Generated parts follow these roles from the next bar." + SKILL),
        "parameters": {"type": "object", "properties": {
            "tracks": {"type": "object", "additionalProperties": {"type": ["string", "object", "null"]},
                       "description": (f'Track -> what it holds, e.g. {{"7": "tuned cymbal", "5": "pad"}}. Free text is '
                                       f"matched to a role ({', '.join(ROLES)}); or give {{role, label}}. null removes.")},
            "slots": {"type": "object", "additionalProperties": {"type": ["string", "null"]},
                      "description": 'Sample slot -> label, e.g. {"11": "warm synth"}. null removes.'},
            "reset": {"type": "boolean", "description": "Clear the whole map first"},
        }},
    },
    "whiplash_transpose": {
        "name": "whiplash_transpose",
        "description": ("Shift one playing track's notes from the next bar (absolute; 0 = back). First fix for a stretched "
                        "or grainy line. Notes stay in 16-84, the documented chromatic range." + SKILL),
        "parameters": {"type": "object", "required": ["track"], "properties": {
            "track": TRACK,
            "semitones": {"type": "integer", "minimum": -TRANSPOSE_MAX, "maximum": TRANSPOSE_MAX,
                          "description": "Give this or octaves"},
            "octaves": {"type": "integer", "minimum": -(TRANSPOSE_MAX // 12), "maximum": TRANSPOSE_MAX // 12,
                        "description": "Give this or semitones"},
        }},
    },
    "whiplash_write_part": {
        "name": "whiplash_write_part",
        "description": ("Write a track's own notes or rhythm (melody, four on the floor, lock_to the kick), replacing its "
                        "line from the next bar. C5 = MIDI 60 = the sample's pitch. length only sounds if AMP MODE is "
                        "ADSR or HOLD is NOTE (read length_audible); envelope 'note' only when the user agrees. Cleared by reset or "
                        "whiplash_stop." + SKILL),
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
                    "description": ("Root for scale degrees, e.g. 'A', 'F#', 'Am' (minor), 'A3' (explicit octave), or "
                                    "'current' (the key playing). Without an octave the root sits nearest note 60.")},
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
    "whiplash_set_progression": {
        "name": "whiplash_set_progression",
        "description": ("Loop chords from the next bar: chord/pad/stab tracks voice them, bass plays roots, leads snap to "
                        "the key. Never on drum, cymbal or fx tracks. clear ends it." + SKILL),
        "parameters": {"type": "object", "properties": {
            "chords": {"type": ["array", "string"], "items": {"type": "string"}, "maxItems": MAX_CHORDS,
                       "description": "Roman numerals in the key ('i VI III VII', 'ii7 V7 Imaj7') or names ('Am F C G')"},
            "bars_per_chord": {"type": "integer", "minimum": 1, "maximum": BARS_PER_CHORD_MAX, "description": "Default 1"},
            "voicing": {"type": "string", "enum": list(VOICINGS), "description": "Default close (voice-led)"},
            "key": {**KEY, "description": "Default: the key playing; a new one moves the pattern too"},
            "scale": SCALE,
            "tracks": {"type": "object", "additionalProperties": {"type": "string", "enum": list(MODES)},
                       "description": 'Override a track\'s mode, e.g. {"9": "chords", "6": "off"}'},
            "clear": {"type": "boolean", "description": "End the progression"},
        }},
    },
    "whiplash_arrange": {
        "name": "whiplash_arrange",
        "description": ("Play the beat as a song from the next bar: sections (intro, build, drop) bring tracks in and out, "
                        "ramp, fill, swap chords, transition. Presets club, short_demo. Stops after the last section unless "
                        "loop." + SKILL),
        "parameters": {"type": "object", "properties": {
            "preset": {"type": "string", "enum": list(PRESETS)},
            "seconds": {"type": "integer", "minimum": SECONDS_MIN, "maximum": SECONDS_MAX,
                        "description": "short_demo length (default 75)"},
            "sections": {"type": "array", "maxItems": SECTIONS_MAX, "items": {"type": "object", "required": ["bars"],
                         "properties": {
                "name": {"type": "string"},
                "bars": {"type": "integer", "minimum": 1, "maximum": SECTION_BARS_MAX},
                "tracks": {"type": "array", "items": {"type": ["integer", "string"]},
                           "description": "What plays (others muted): 1-16, all, drums, kick, hats, perc, bass, music"},
                "mute": {"type": "array", "items": {"type": ["integer", "string"]}, "description": "Or: what doesn't"},
                "drop": {"type": "array", "items": {"type": ["integer", "string"]}, "description": "Sit out the last bar"},
                "fill": {"type": "boolean", "description": "Drum fill on the last bar"},
                "chords": {"type": ["string", "array"], "items": {"type": "string"}, "description": "'i VI III VII', or 'none'"},
                "bars_per_chord": {"type": "integer", "minimum": 1, "maximum": BARS_PER_CHORD_MAX},
                "ramps": {"type": "array", "maxItems": RAMPS_MAX, "items": {"type": "object", "properties": {
                    "track": {"type": ["integer", "string"]}, "param": {"type": "string"},
                    "from": {"type": "integer"}, "to": {"type": "integer"}, "bars": {"type": "integer"},
                    "curve": {"type": "string", "enum": sorted(CURVES)}}},
                          "description": "Start on the first bar; bars default to the section's"},
                "transition": {**TRANSITION, "description": "Into the next section, over its last bars"},
                "transition_bars": TX_BARS,
                "filter_from": FILTER_FROM,
                "mix": {"type": "string", "description": "Saved mix or mix preset, on the first bar"},
            }}},
            "loop": {"type": "boolean"},
            "clear": {"type": "boolean", "description": "End the arrangement"},
        }},
    },
    "whiplash_mix": {
        "name": "whiplash_mix",
        "description": ("Set track LEVEL (CC 95) and PAN (CC 90) per track or group from the next bar, or a genre "
                        "preset; bars ramps. save_as/recall a mix." + SKILL),
        "parameters": {"type": "object", "properties": {
            "levels": {**MIX_MAP, "description": 'Track or group -> 0-127, e.g. {"6": 95, "hats": 90}'},
            "pan": {**MIX_MAP, "description": "Track or group -> 0-127 (64 centre), or left, right, hard left..."},
            "preset": {"type": "string", "enum": [*MIX_PRESETS, "auto"], "description": "Levels by role; auto = genre"},
            "bars": {"type": "integer", "minimum": 0, "maximum": MIX_BARS_MAX, "description": "Ramp length; 0 = on the bar"},
            "save_as": {"type": "string"},
            "recall": {"type": "string"},
        }},
    },
    "whiplash_ramp_param": {
        "name": "whiplash_ramp_param",
        "description": "Sweep a param over beats or bars on the clock. Cancel with cancel: '<ramp_id>' or 'all'.",
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
        "description": ("Change the running pattern on the bar: density, fill, swing, humanize, drop "
                        "(silence tracks for some bars), or reset."),
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
        "description": ("Mute a track live (hardware: also the unit's CC 94 mute). Mutes reset on stop or a fresh start."),
        "parameters": {"type": "object", "required": ["track"], "properties": {
            "track": TRACK, "hardware": {"type": "boolean", "description": "Also toggle the unit's own track mute (CC94)"}}},
    },
    "whiplash_unmute_track": {
        "name": "whiplash_unmute_track",
        "description": "Unmute a track, including a unit mute Whiplash set.",
        "parameters": {"type": "object", "required": ["track"], "properties": {
            "track": TRACK, "hardware": {"type": "boolean", "description": "Also send CC94 unmute to the unit"}}},
    },
    "whiplash_set_tempo": {
        "name": "whiplash_set_tempo",
        "description": f"Change the tempo live ({BPM_MIN}-{BPM_MAX} BPM).",
        "parameters": {"type": "object", "required": ["bpm"], "properties": {
            "bpm": {"type": "number", "minimum": BPM_MIN, "maximum": BPM_MAX}}},
    },
    "whiplash_stop": {
        "name": "whiplash_stop",
        "description": ("Stop and silence: note-offs, All Notes Off on 1-8 and any 9-16 that played, MIDI Stop (not "
                        "when clock-only). Resets everything but the kit map and saved mixes. Safe as a panic "
                        "button."),
        "parameters": EMPTY,
    },
    "whiplash_status": {
        "name": "whiplash_status",
        "description": ("Now: port, pattern, key, chords, section, bpm, bar, queued switch, per-track "
                        "role/slot/pitch/part/mute, ramps, mutations, kit map, routing, errors." + SKILL),
        "parameters": EMPTY,
    },
    "whiplash_open_view": {
        "name": "whiplash_open_view",
        "description": ("Open the read-only live visualiser (a local 127.0.0.1 page) in the browser, when the user asks to "
                        "see the beat."),
        "parameters": {"type": "object", "properties": {
            "port": {"type": "integer", "minimum": 1024, "maximum": 65535,
                     "description": "Local TCP port (default 7341, or a free one if that is taken)"},
            "open_browser": {"type": "boolean", "description": "Open the default browser (default true); false only returns the URL"},
        }},
    },
    "whiplash_close_view": {
        "name": "whiplash_close_view",
        "description": "Close the visualiser server; the beat keeps playing.",
        "parameters": EMPTY,
    },
}
