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
    bass: str | None  # a phrase it is written for (O3: bass.descending_walk), else None
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
