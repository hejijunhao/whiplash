"""Named chord progressions (v0.9.0, ontology O1a): pure tables, no MIDI, no engine state.

Each entry is a starting point from docs/research/genre-conventions.md (the `source` names its section) and still
needs Phil's ear on his kit (docs/executing/ontology-v1-spec.md §8, HW O-5). Numerals follow
harmony.parse_chord: scale degrees of the progression's own scale, so in A minor VI is F, VII is G and III is C
(the research's bVI, bVII, bIII), and an accidental is a note outside the scale (bII in A minor is B flat).

The progression plays on the session's root in its own scale, except major <-> minor, which use the relative key
(an A minor session playing a major entry plays it in C major). See key_for().
"""
from dataclasses import dataclass

from . import harmony

# Mood and use words an entry may carry, besides genre names. Fixed, so tags stay a vocabulary (integrity test).
TAGS = frozenset({
    "classic", "hypnotic", "soulful", "warm", "jazzy", "gospel", "afro", "rolling", "deep tech", "piano", "bright",
    "uplift", "organ", "jacking", "twist", "sparse", "dark", "phrygian", "stab", "minor", "major", "dorian",
    "circular", "patient", "prydz-like", "restrained uplift", "cinematic", "conservative", "sunny", "wistful",
})
GENRE_TAGS = frozenset({"deephouse", "house", "techhouse", "techno", "progressivehouse", "melodictechno",
                        "minimal", "tropicalhouse"})


@dataclass(frozen=True)
class Prog:
    name: str  # "deephouse.gospel"
    chords: str  # numerals in the progression's own scale
    bars_per_chord: int
    voicing: str | None  # None: the default rule (shell for 7th/9th/11th on <= 3 chord tracks, pads full; else close)
    scale: str  # the scale it is written in
    bass: str | None  # a phrase it is written for (bass.descending_walk), else None
    tags: frozenset
    brightness: int  # -2 (darkest) .. +2, for the O2 intents
    tension: int  # 0 (static vamp) .. 3 (dominant pull)
    source: str
    about: str

    @property
    def genre(self):
        return self.name.split(".", 1)[0]


def _p(name, chords, bars, scale, tags, brightness, tension, source, about, voicing=None, bass=None):
    genre = name.split(".", 1)[0]
    return Prog(name, chords, bars, voicing, scale, bass, frozenset({genre, *tags}), brightness, tension, source, about)


PROGRESSIONS = {p.name: p for p in (
    # Deep house (research §1; Q-H1). i-VI-III-VII is house-wide: house.uplift.
    _p("deephouse.two_chord", "i7 iv7", 2, "minor", {"classic", "hypnotic"}, -1, 1, "§1 BeatKey, Violet",
       "Am7 to Dm7, two bars each: the classic deep house vamp"),
    _p("deephouse.dorian_soul", "i7 IV7", 2, "dorian", {"soulful", "warm", "dorian"}, 0, 1, "§1 BeatKey",
       "Dorian im7 to IV7 (Am7 D7): the major IV lifts it"),
    _p("deephouse.two_five", "iv7 VII7 IIImaj7 IIImaj7", 2, "minor", {"jazzy"}, 0, 2, "§1 BeatKey",
       "ii-V-I of the relative major (Dm7 G7 Cmaj7)"),
    _p("deephouse.gospel", "i7 VImaj7 VII7 i7", 2, "minor", {"gospel", "warm"}, 0, 2, "§1 BeatKey",
       "Am7 Fmaj7 G7 Am7: gospel-tinged and warm"),
    _p("deephouse.afro", "i7 IIImaj7 VII7 VImaj7", 2, "minor", {"afro", "rolling"}, 0, 1, "§1 BeatKey",
       "Am7 Cmaj7 G7 Fmaj7: rolling afro house loop"),
    _p("deephouse.one_chord", "i9", 4, "minor", {"deep tech", "hypnotic"}, -1, 0, "§1 BeatKey",
       "One Am9 held: deep tech, all groove"),
    # Classic / Chicago house (research §2).
    _p("house.piano_stab", "i III bII i", 1, "minor", {"piano", "classic"}, -1, 1, "§2 MusicRadar",
       "Am C Bb Am: the Em-G-F-Em piano-stab shape, a chord a bar"),
    _p("house.mixed_shuffle", "I bVII i IV", 1, "major", {"piano", "bright"}, 1, 1, "§2 MusicRadar",
       "C Bb Cm F: mixed major/minor piano shuffle (relative major in a minor session)"),
    _p("house.uplift", "i VI III VII", 2, "minor", {"uplift", "deephouse", "progressivehouse"}, 1, 1,
       "§1, §2 Violet", "Am F C G: the house-wide uplifting loop"),
    _p("house.jack_vamp", "i7 iv7", 2, "minor", {"organ", "jacking"}, -1, 1, "§2 Violet",
       "Am7 Dm7: organ vamp under a jacking groove"),
    _p("house.minor_twist", "i7 v7 i7 #iii7", 1, "minor", {"twist"}, -1, 2, "§2 Violet",
       "Am7 Em7 Am7 C#m7: the Cm7-Gm7 ... Em7 twist"),
    # Tech house (research §3: harmony is secondary).
    _p("techhouse.one_note", "i5", 4, "minor", {"sparse"}, -1, 0, "§3 Mix Elite, Abletonic",
       "One A5 (root and fifth): a single note under the groove"),
    _p("techhouse.dark_two", "i7 bII", 2, "minor", {"dark", "phrygian"}, -2, 1, "§3 EDMProd, Mix Elite",
       "Am7 to Bb: a dark phrygian two-chord loop"),
    # Techno (research §5; home F minor).
    _p("techno.pedal", "i5", 4, "minor", {"hypnotic"}, -1, 0, "§5 Brizm, Armon",
       "One power chord held: hypnotic pedal", voicing="power"),
    _p("techno.phrygian", "i bII", 2, "minor", {"dark", "phrygian"}, -2, 1, "§5 Armon",
       "Fm to Gb as power chords: dark phrygian", voicing="power"),
    _p("techno.dark_vamp", "i VI", 2, "minor", {"dark"}, -2, 1, "§5 Armon", "Fm to Db: a dark two-chord vamp",
       voicing="close"),
    _p("techno.sus_stab", "isus2", 4, "minor", {"stab"}, -1, 0, "§5 Brizm", "One sus2 stab chord",
       voicing="close"),
    # Progressive house (research §4: 7ths, 9ths, sus4, not triads; long releases). O3.
    _p("progressivehouse.circle", "i7 iv7 VIIsus4 IIImaj7", 2, "minor", {"circular"}, 0, 1,
       "§4 BeatKey (voicings by ear)", "Am7 Dm7 Gsus4 Cmaj7: a circular loop of 7ths and a sus4"),
    _p("progressivehouse.long_two", "i7 iv7", 4, "minor", {"patient"}, -1, 1,
       "§4 BeatKey (held for 64 bars while texture builds)", "Am7 to Dm7, four bars each: patient, the texture builds"),
    _p("progressivehouse.phrygian_turn", "i bII i V7", 2, "minor", {"dark", "phrygian"}, -2, 3, "§4 BeatKey",
       "Am Bb Am E7: a dark phrygian turn with a dominant pull home"),
    _p("progressivehouse.descending", "i9", 4, "minor", {"prydz-like"}, -1, 1,
       "§4 BeatKey (Am-Am/G-Fmaj7-E7 as a bass walk)",
       "Am9 held over a descending bass walk (A G F E): write bass.descending_walk on the bass track",
       bass="bass.descending_walk"),
    # Melodic techno (research §8, Q-H1 challenge: sourced material only). O3.
    _p("melodictechno.cinematic", "iadd9 VImaj7 III VIIsus2", 2, "minor", {"cinematic"}, 0, 1,
       "§8 NI (i-VI-III-VII, chords every two bars, add9/maj7/sus2)",
       "Am(add9) Fmaj7 C Gsus2: cinematic minor chords, two bars each"),
    _p("melodictechno.held_vamp", "i9 VImaj7", 4, "minor", {"conservative"}, -1, 0, "§8 NI, Soundtrap; Phil default",
       "Am9 to Fmaj7, four bars each: the chords hold while the lead moves"),
    # Minimal (research §6: by default no progression; when present, one stab). O3.
    _p("minimal.stab_m7", "i7", 4, "minor", {"stab"}, -1, 0, "§6 Brizm", "One m7 stab chord"),
    _p("minimal.stab_sus2", "isus2", 4, "minor", {"stab"}, 0, 0, "§6 Brizm", "One sus2 stab chord"),
    _p("minimal.fifth", "i5", 4, "minor", {"stab"}, -1, 0, "§6 Brizm", "One root-and-fifth stab"),
    # Tropical house (research §7: pop house, maj7/9 for a brighter pad; home C major). O3.
    _p("tropicalhouse.pop", "Imaj7 V vi7 IVmaj7", 2, "major", {"sunny"}, 2, 1, "§7 Melodigging (2 bars by ear)",
       "Cmaj7 G Am7 Fmaj7: the sunny I-V-vi-IV pop loop"),
    _p("tropicalhouse.pop_minor", "vi7 IVmaj7 Imaj7 V", 2, "major", {"wistful"}, 1, 1, "§7 Melodigging",
       "Am7 Fmaj7 Cmaj7 G: the same loop from the vi, wistful"),
)}


def key_for(prog, session):
    """(Key the progression plays in, note) on the session key: its own scale on the session root, except
    major <-> minor, which take the relative key. note is None when the session key is used as is."""
    if prog.scale == session.scale:
        return session, None
    if {prog.scale, session.scale} == {"major", "minor"}:
        pc = (session.pc + (3 if session.scale == "minor" else 9)) % 12
        key = harmony.Key(pc, prog.scale)
        return key, f"{key.name} (relative of {session.name})"
    key = harmony.Key(session.pc, prog.scale)
    return key, f"{key.name} (its own scale on {session.name}'s root)"


# ---- intents (v0.9.1, ontology O2) -------------------------------------------------------------------------------
# set_progression(intent): each is a deterministic transform, compiled in the tool thread (engine._intent).
# darker / brighter take `how` (Q-H3): one or more of HOWS, default harmonic; the result names what was applied and
# the options left unused. tension and release change the progression only.
HOWS = ("harmonic", "timbral", "register")
INTENTS = {
    "darker": "harmonic: the same genre's next darker progression, else one step down the mode ladder (lydian > "
              "major > mixolydian > dorian > minor > phrygian); timbral: close the melodic tracks' filter a step; "
              "register: thin the highs and drop the lead an octave",
    "brighter": "the reverse of darker: the next brighter progression or one step up the ladder; timbral reopens, "
                "never past the cutoff before the first darker; register restores the highs and the lead",
    "tension": "one step per call: the last chord becomes the dominant 7th, then a dominant 9th, then the bass "
               "holds a tonic pedal",
    "release": "back to the progression that played before the first tension, pedal off",
}
TENSION_STEPS = 3


def swap(entry, darker):
    """The same genre's entry with the next lower (darker) or higher brightness, ties broken by the most shared
    tags, then the name. None when entry is already its genre's darkest (brightest)."""
    genre = entry.genre
    if darker:
        pool = [p for p in PROGRESSIONS.values() if p.genre == genre and p.brightness < entry.brightness]
        best = max((p.brightness for p in pool), default=None)
    else:
        pool = [p for p in PROGRESSIONS.values() if p.genre == genre and p.brightness > entry.brightness]
        best = min((p.brightness for p in pool), default=None)
    pool = [p for p in pool if p.brightness == best]
    if not pool:
        return None
    return min(pool, key=lambda p: (-len(p.tags & entry.tags), p.name))
