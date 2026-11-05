"""Tool schemas shown to the model."""
from .ccmap import PARAMS
from .patterns import MOODS, PATTERNS

TRACK = {"type": "integer", "minimum": 1, "maximum": 16, "description": "Digitakt track number (= MIDI channel), 1-8 used by patterns"}

SCHEMAS = {
    "list_midi_ports": {
        "name": "list_midi_ports",
        "description": "List MIDI input/output ports and whether an Elektron Digitakt II is connected over USB.",
        "parameters": {"type": "object", "properties": {}},
    },
    "play_pattern": {
        "name": "play_pattern",
        "description": ("Start a generated beat on the Digitakt II tracks 1-8 (MIDI channels 1-8) with MIDI clock "
                        "and start/stop, in the background. Pick by genre or mood. Falls back to a virtual MIDI "
                        "port named 'Whiplash' when no Digitakt is connected. Replaces any playing pattern."),
        "parameters": {"type": "object", "properties": {
            "genre": {"type": "string", "enum": sorted(PATTERNS), "description": "Pattern genre"},
            "mood": {"type": "string", "description": f"Mood word if no genre, e.g. {', '.join(sorted(MOODS))}"},
            "bpm": {"type": "number", "minimum": 30, "maximum": 300, "description": "Tempo; default is the genre's"},
            "bars": {"type": "integer", "minimum": 1, "maximum": 512, "description": "Stop after N bars; omit to loop until stop"},
            "port": {"type": "string", "description": "Exact output port name (optional; auto-detects Digitakt)"},
        }},
    },
    "set_param": {
        "name": "set_param",
        "description": ("Change a sound parameter on one Digitakt II track live via CC or NRPN. Use a friendly "
                        f"param name ({', '.join(sorted(PARAMS))}) or a raw cc / nrpn [msb, lsb]."),
        "parameters": {"type": "object", "required": ["track", "value"], "properties": {
            "track": TRACK,
            "param": {"type": "string", "description": "Friendly parameter name"},
            "cc": {"type": "integer", "minimum": 0, "maximum": 119},
            "nrpn": {"type": "array", "items": {"type": "integer"}, "minItems": 2, "maxItems": 2},
            "value": {"type": "integer", "minimum": 0, "maximum": 16383},
        }},
    },
    "mute_track": {
        "name": "mute_track",
        "description": "Mute a track live (Whiplash stops sending its notes; optionally also sends Digitakt CC94 mute).",
        "parameters": {"type": "object", "required": ["track"], "properties": {
            "track": TRACK, "hardware": {"type": "boolean", "description": "Also toggle the unit's own track mute (CC94)"}}},
    },
    "unmute_track": {
        "name": "unmute_track",
        "description": "Unmute a track muted with mute_track.",
        "parameters": {"type": "object", "required": ["track"], "properties": {
            "track": TRACK, "hardware": {"type": "boolean"}}},
    },
    "set_tempo": {
        "name": "set_tempo",
        "description": "Change the tempo live (30-300 BPM); the MIDI clock follows so the Digitakt's FX sync.",
        "parameters": {"type": "object", "required": ["bpm"], "properties": {
            "bpm": {"type": "number", "minimum": 30, "maximum": 300}}},
    },
    "stop": {
        "name": "stop",
        "description": "Stop playback: note-offs, All Notes Off on channels 1-8, and MIDI transport Stop.",
        "parameters": {"type": "object", "properties": {}},
    },
    "whiplash_status": {
        "name": "whiplash_status",
        "description": "Show what Whiplash is playing: port, pattern, bpm, bar, muted tracks.",
        "parameters": {"type": "object", "properties": {}},
    },
}
