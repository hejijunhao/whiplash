"""Tool schemas shown to the model."""
from .ccmap import PARAMS
from .engine import BARS_MAX, BPM_MAX, BPM_MIN
from .patterns import MOODS, PATTERNS

TRACK = {"type": "integer", "minimum": 1, "maximum": 16, "description": "Digitakt track number (= MIDI channel), 1-8 used by patterns"}

SCHEMAS = {
    "whiplash_list_midi_ports": {
        "name": "whiplash_list_midi_ports",
        "description": ("List MIDI input/output ports and whether an Elektron Digitakt II is connected over USB. "
                        "A 'warning' in the result means no Digitakt was found."),
        "parameters": {"type": "object", "properties": {}},
    },
    "whiplash_play_pattern": {
        "name": "whiplash_play_pattern",
        "description": ("Start a generated beat on the Digitakt II tracks 1-8 (MIDI channels 1-8) with MIDI clock "
                        "and start/stop, in the background. Pick by genre or mood. Replaces any playing pattern "
                        "and resets all mutes. Falls back to a virtual MIDI port named 'Whiplash' when no "
                        "Digitakt is connected: the result then carries a 'warning' and the hardware is silent."),
        "parameters": {"type": "object", "properties": {
            "genre": {"type": "string", "enum": sorted(PATTERNS), "description": "Pattern genre"},
            "mood": {"type": "string", "description": f"Mood word if no genre, e.g. {', '.join(sorted(MOODS))}"},
            "bpm": {"type": "number", "minimum": BPM_MIN, "maximum": BPM_MAX, "description": "Tempo; default is the genre's"},
            "bars": {"type": "integer", "minimum": 1, "maximum": BARS_MAX, "description": "Stop after N bars; omit to loop until stop"},
            "port": {"type": "string", "description": "Exact output port name (optional; auto-detects Digitakt)"},
        }},
    },
    "whiplash_set_param": {
        "name": "whiplash_set_param",
        "description": ("Change a sound parameter on one Digitakt II track live via CC or NRPN. Use a friendly "
                        f"param name ({', '.join(sorted(PARAMS))}) or a raw cc / nrpn [msb, lsb]. "
                        "Give exactly one of param, cc or nrpn."),
        "parameters": {"type": "object", "required": ["track", "value"], "properties": {
            "track": TRACK,
            "param": {"type": "string", "description": "Friendly parameter name"},
            "cc": {"type": "integer", "minimum": 0, "maximum": 119, "description": "Raw CC number"},
            "nrpn": {"type": "array", "items": {"type": "integer", "minimum": 0, "maximum": 127},
                     "minItems": 2, "maxItems": 2, "description": "Raw NRPN address [msb, lsb]"},
            "value": {"type": "integer", "minimum": 0, "maximum": 16383,
                      "description": ("0-127 for param and cc. For nrpn, the full 14-bit value 0-16383 "
                                      "(data MSB = value >> 7, LSB = value & 127); a 7-bit amount v is v * 128")},
        }},
    },
    "whiplash_mute_track": {
        "name": "whiplash_mute_track",
        "description": ("Mute a track live (Whiplash stops sending its notes; optionally also sends Digitakt CC94 "
                        "mute). Mutes reset on whiplash_stop and whenever a new pattern starts, so mute after "
                        "whiplash_play_pattern, not before."),
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
                        "Also resets all mutes. Safe to call when nothing is playing (acts as a panic button)."),
        "parameters": {"type": "object", "properties": {}},
    },
    "whiplash_status": {
        "name": "whiplash_status",
        "description": ("Show what Whiplash is doing: port (and whether it is the silent virtual fallback), "
                        "pattern, bpm, bar, muted tracks, and last_error if the sequencer stopped on a fault."),
        "parameters": {"type": "object", "properties": {}},
    },
}
