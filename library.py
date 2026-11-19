"""One naming scheme and lookup for every v0.9 library (ontology O1a). Pure; no MIDI, no engine state.

Names are `<genre>.<name>` for genre-owned entries (deephouse.gospel, house.jack) and `<role>.<name>` for shared
lanes and fills (hat.offbeat_shuffle, snare.roll). Each kind is its own namespace. resolve() accepts what a model
is likely to type: any case, spaces / - / _, a missing genre prefix when only one genre (or the hint) has the name,
natural phrases ("deep house shuffle groove", "chicago jack") and letter aliases (deephouse.A). Names are never
schema enums (hundreds of names would blow the tool-description budget); whiplash_list_library lists them.
"""
import difflib
import re

from . import genres, grooves, phrases, progressions

KINDS = ("genre", "progression", "groove", "lane", "phrase", "fill", "form", "move")
LIST_MAX = 40
LATER = {"form": "O4 (v0.9.3)", "move": "O4 (v0.9.3)"}
# Words a model may use for a genre, longest first when matching. Bare "house" is the classic-house id here, the
# library prefix; as a genre word in play_pattern it still means deep house (patterns.ALIASES).
GENRE_WORDS = {
    "deep house": "deephouse", "deephouse": "deephouse", "deep": "deephouse",
    "classic house": "house", "chicago house": "house", "chicago": "house", "house": "house",
    "tech house": "techhouse", "techhouse": "techhouse", "tech": "techhouse",
    "techno": "techno", "peak time techno": "techno",
}
FILLER = {"groove", "grooves", "progression", "progressions", "chords", "chord", "lane", "lanes", "fill", "fills",
          "the", "a", "an", "feel", "beat", "pattern", "loop", "style", "genre", "please", "with", "some", "in"}


class LibraryError(ValueError):
    pass


def _tables():
    return {"genre": genres.GENRES, "progression": progressions.PROGRESSIONS, "groove": grooves.GROOVES,
            "lane": grooves.LANES, "fill": grooves.FILLS, "phrase": phrases.PHRASES, "form": {}, "move": {}}


def table(kind):
    kind = check_kind(kind)
    return _tables()[kind]


def check_kind(kind):
    word = str(kind or "").strip().lower()
    if word not in KINDS:
        raise LibraryError(f"kind must be one of {', '.join(KINDS)}, got {kind!r}")
    return word


def _norm(text):
    return re.sub(r"[\s_\-]+", " ", str(text).strip().lower()).strip()


def _key(text):
    return _norm(text).replace(" ", "_")


def _hint(kind):
    return f"see whiplash_list_library(kind: {kind!r})"


def _aliases(kind):
    if kind == "groove":
        return {a.lower(): n for a, n in grooves.ALIASES.items()}
    return {}


def resolve(kind, text, genre=None):
    """The entry of kind named by text. genre (a genre id) breaks ties for a bare name. Raises LibraryError."""
    kind = check_kind(kind)
    names = _tables()[kind]
    if kind in LATER:
        raise LibraryError(f"no {kind}s yet: they arrive in {LATER[kind]}")
    if not isinstance(text, str) or not text.strip():
        raise LibraryError(f"give a {kind} name; {_hint(kind)}")
    by_lower = {n.lower(): n for n in names}
    aliases = _aliases(kind)
    hint_genre = genre

    def found(name):
        return names[name]

    raw = text.strip().lower()
    key = _key(raw)
    for candidate in (raw, key):
        if candidate in by_lower:
            return found(by_lower[candidate])
        if candidate in aliases:
            return found(aliases[candidate])
    if kind == "groove" and key in ("a", "classic") and hint_genre in grooves.CLASSIC:  # a bare letter alias
        return found(grooves.CLASSIC[hint_genre])
    if "." in key:  # "deep_house.shuffle", "Chicago.jack"
        head, rest = key.split(".", 1)
        canon = GENRE_WORDS.get(head.replace("_", " "), head.replace("_", ""))
        for g in (canon, "deephouse" if canon == "house" else None):
            if g and f"{g}.{rest}" in by_lower:
                return found(by_lower[f"{g}.{rest}"])
            if g and f"{g}.{rest}".lower() in aliases:
                return found(aliases[f"{g}.{rest}".lower()])
    words = [w for w in _norm(raw.replace(".", " ")).split() if w not in FILLER]
    phrase = " ".join(words)
    genre_word = None
    for gw in sorted(GENRE_WORDS, key=len, reverse=True):
        if re.search(rf"(^| ){re.escape(gw)}( |$)", phrase):
            genre_word = gw
            break
    rest = phrase
    if genre_word:
        rest = re.sub(rf"(^| ){re.escape(genre_word)}( |$)", " ", phrase).strip()
        hint_genre = GENRE_WORDS[genre_word]
    rest_key = rest.replace(" ", "_")
    for cut in range(1, len(words)):  # "hat offbeat shuffle" -> hat.offbeat_shuffle (role- or genre-prefixed)
        dotted = "_".join(words[:cut]) + "." + "_".join(words[cut:])
        if dotted in by_lower:
            return found(by_lower[dotted])
    if kind == "genre":
        if hint_genre in names and not rest_key:
            return found(hint_genre)
    elif kind == "groove" and genre_word and not rest_key:  # "chicago" -> house's default groove
        record = genres.GENRES.get(hint_genre)
        if record:
            return found(record.groove)
    if kind == "groove" and rest_key in ("classic",) and hint_genre in grooves.CLASSIC:
        return found(grooves.CLASSIC[hint_genre])
    if rest_key:
        if hint_genre:
            for g in (hint_genre, "deephouse" if genre_word == "house" else None):
                if g and f"{g}.{rest_key}" in by_lower:
                    return found(by_lower[f"{g}.{rest_key}"])
        suffix = [n for n in names if n.split(".", 1)[-1].lower() == rest_key or n.lower() == rest_key]
        if len(suffix) == 1:
            return found(suffix[0])
        if len(suffix) > 1:
            raise LibraryError(f"{text!r} is ambiguous: {', '.join(sorted(suffix))}; give the full name")
    pool = [*names, *[n.split(".", 1)[-1] for n in names], *aliases]
    close = difflib.get_close_matches(key, [p.lower() for p in pool], n=3, cutoff=0.5)
    close = [by_lower.get(c, aliases.get(c, c)) for c in close]
    shown = []
    for c in close:
        full = c if c in names else next((n for n in names if n.split(".", 1)[-1].lower() == c), c)
        if full not in shown:
            shown.append(full)
    near = f"closest: {', '.join(shown)}; " if shown else ""
    scope = f", genre: {hint_genre!r}" if hint_genre else ""
    raise LibraryError(f"unknown {kind} {text!r}; {near}see whiplash_list_library(kind: {kind!r}{scope})")


def _genre_of(entry):
    return getattr(entry, "genre", None) or (entry.name if isinstance(entry, genres.Genre) else None)


def _tags(entry):
    return set(getattr(entry, "tags", ()) or ())


def summary(kind, entry):
    """One listing row: {name, about, tags, ...kind-specific}."""
    out = {"name": entry.name, "about": entry.about, "tags": sorted(_tags(entry))}
    if kind == "genre":
        out.update(bpm=entry.bpm, swing=entry.swing, key=harmony_key(entry.key), groove=entry.groove,
                   grooves=sorted(g.name for g in grooves.GROOVES.values() if g.genre == entry.name))
        if entry.progression:
            out["progression"] = entry.progression
        if entry.recommends:
            out["recommends"] = dict(entry.recommends)
    elif kind == "progression":
        session = genres.GENRES[entry.genre].key if entry.genre in genres.GENRES else (9, "minor")
        out.update(chords=entry.chords, scale=entry.scale, bars_per_chord=entry.bars_per_chord,
                   **_names(entry, session))
        if entry.voicing:
            out["voicing"] = entry.voicing
    elif kind == "groove":
        out.update(genre=entry.genre, swing=entry.swing, energy_levels=sorted(entry.levels),
                   lanes_at_3=dict(entry.levels[3]))
        if entry.aliases:
            out["aliases"] = list(entry.aliases)
    elif kind == "lane":
        out.update(role=entry.role, bars=len(entry.grid), grid=list(entry.grid), velocity_curve=entry.curve,
                   micro=sorted({m for m in entry.micro if m}) if entry.micro else [])
    elif kind == "phrase":
        out.update(phrases.describe(entry))
    elif kind == "fill":
        out.update(roles=sorted(entry.roles))
        if entry.fallback:
            out["fallback"] = entry.fallback
    out["source"] = entry.source
    return out


def harmony_key(key):
    from . import harmony
    return harmony.Key(*key).name


def _names(prog, session_key):
    from . import harmony
    key, note = progressions.key_for(prog, harmony.Key(*session_key))
    names = [harmony.parse_chord(c, key).name for c in harmony.split_chords(prog.chords)]
    out = {"in_key": key.name, "names": names}
    if note:
        out["key_note"] = note
    return out


def entries(kind, genre=None, tag=None):
    """{kind, entries: [...], more: n} for whiplash_list_library: at most 40 rows, sorted by name."""
    kind = check_kind(kind)
    rows = list(_tables()[kind].values())
    out = {"kind": kind}
    if kind in LATER:
        return {**out, "entries": [], "more": 0, "note": f"no {kind}s yet: they arrive in {LATER[kind]}"}
    genre_id = None
    if genre not in (None, ""):
        genre_id = GENRE_WORDS.get(_norm(genre), _norm(genre).replace(" ", ""))
        rows = [e for e in rows if _genre_of(e) == genre_id or genre_id in _tags(e)]
    if tag not in (None, ""):
        word = _norm(tag)
        rows = [e for e in rows if word in {_norm(t) for t in _tags(e)}
                or (kind in ("lane", "phrase") and _norm(e.role) == word)
                or (kind == "fill" and word in e.roles)]
    rows.sort(key=lambda e: e.name)
    if not rows:
        all_rows = list(_tables()[kind].values())
        known_genres = sorted({g for g in (_genre_of(e) for e in all_rows) if g})
        known_tags = sorted({t for e in all_rows for t in _tags(e)})
        return {**out, "entries": [], "more": 0,
                "note": (f"nothing matches; genres: {', '.join(known_genres) or 'none'}; "
                         f"tags: {', '.join(known_tags)}")}
    shown = rows[:LIST_MAX]
    return {**out, "entries": [summary(kind, e) for e in shown], "more": len(rows) - len(shown)}
