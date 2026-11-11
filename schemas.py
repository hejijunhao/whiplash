"""Tool schemas shown to the model."""
from .ccmap import PARAMS
from .engine import (BARS_MAX, BPM_MAX, BPM_MIN, CURVES, DROP_BARS_MAX, RAMP_BARS_MAX, RAMP_BEATS_MAX, SWING_MAX,
                     SWING_MIN)
from .patterns import MOODS, PATTERNS

TRACK = {"type": "integer", "minimum": 1, "maximum": 16, "description": "Digitakt track number (= MIDI channel), 1-8 used by patterns"}
TRACKS = {"type": "array", "items": {"type": "integer", "minimum": 1, "maximum": 8},
          "description": "Track numbers 1-8 (1 kick, 2 rim/snare, 3 clap, 4 closed hat, 5 open hat, 6 bass, 7-8 chords)"}
PARAM = {"type": "string", "description": f"Named Digitakt II param (see whiplash_list_params), e.g. {', '.join(list(PARAMS)[:8])}, ..."}
EMPTY = {"type": "object", "properties": {}}

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
                        "carries a 'warning' and the hardware is silent. If the user wants to watch the beat, "
                        "whiplash_open_view shows it live in a local browser page."),
        "parameters": {"type": "object", "properties": {
            "genre": {"type": "string", "enum": sorted(PATTERNS), "description": "Pattern genre"},
            "mood": {"type": "string", "description": f"Mood word if no genre, e.g. {', '.join(sorted(MOODS))}"},
            "bpm": {"type": "number", "minimum": BPM_MIN, "maximum": BPM_MAX,
                    "description": "Tempo; default is the genre's. On a live switch it applies at the switch."},
            "bars": {"type": "integer", "minimum": 1, "maximum": BARS_MAX, "description": "Stop after N bars; omit to loop until stop"},
            "port": {"type": "string", "description": "Exact output port name (optional; auto-detects Digitakt)"},
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
                        "reset (back to the original pattern). Mutations last until reset or a new pattern; mutes "
                        "are separate."),
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
        "description": ("Stop playback: note-offs, All Notes Off on channels 1-8, and MIDI transport Stop. "
                        "Also resets mutes, ramps, mutations and any queued switch. Safe to call when nothing is "
                        "playing (acts as a panic button)."),
        "parameters": EMPTY,
    },
    "whiplash_status": {
        "name": "whiplash_status",
        "description": ("Show what Whiplash is doing: port (and whether it is the silent virtual fallback, or a "
                        "Digitakt that has become available), pattern, bpm, bar, queued switch, muted tracks, active "
                        "ramps with progress, mutations, and last_error if the sequencer stopped on a fault."),
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
