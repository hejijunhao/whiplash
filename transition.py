"""DJ-style transitions (v0.6.2): how one pattern or section hands over to the next.

Pure: names, defaults and validation only, no MIDI and no engine state. The engine builds every transition from
primitives it already has (bar-scheduled ramps, drops and fills), timed on its own clock, so there is no new clock
path. A transition runs over the last `bars` bars before the hand-over:

- cut: nothing; the switch lands on the next bar line (the behaviour before v0.6.2).
- filter_swap: the outgoing tracks' filter cutoff (filter_freq, CC 74) closes to FILTER_FLOOR over `bars` bars, the
  switch lands on the one, then each closed track's cutoff ramps back to where it was over REOPEN_BARS bar(s). Kick
  and bass keep their filter, so the low end holds the groove. Only the last value Whiplash sent is known, so a
  track it hasn't sent a cutoff to needs `filter_from`.
- drop_swap: kick and bass sit out the last `bars` bars (default 1), and come back with the switch on the one.
- riser: a rising filter ramp (FILTER_FLOOR+ -> 127, exp) on every track labelled fx (riser, sweep, noise...), and
  a drum fill on the last bar. Without an fx label it is the fill only, and the result says so.
"""
KINDS = ("cut", "filter_swap", "drop_swap", "riser")
DEFAULT_BARS = {"cut": 0, "filter_swap": 4, "drop_swap": 1, "riser": 4}
BARS_MIN, BARS_MAX = 1, 8
FILTER_FLOOR = 30  # filter_freq the outgoing tracks close to: dark, not silent
REOPEN_BARS = 1
RISER_FROM, RISER_TO = 20, 127
LOW_ROLES = frozenset({"kick", "bass"})  # drop_swap drops them; filter_swap leaves them open
ALIASES = {"none": "cut", "filter": "filter_swap", "filterswap": "filter_swap", "filter_sweep": "filter_swap",
           "sweep": "filter_swap", "drop": "drop_swap", "dropswap": "drop_swap", "drop_out": "drop_swap",
           "dropout": "drop_swap", "build": "riser", "rise": "riser"}


class TransitionError(ValueError):
    pass


def kind(value):
    """A transition name -> one of KINDS, or None when none is given."""
    if value in (None, ""):
        return None
    word = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    word = ALIASES.get(word, word)
    if word not in KINDS:
        raise TransitionError(f"transition must be one of {', '.join(KINDS)}, got {value!r}")
    return word


def bars(name, value):
    """transition_bars for a transition -> whole number BARS_MIN-BARS_MAX (its default when None). cut: 0."""
    if name in (None, "cut"):
        if value not in (None, ""):
            raise TransitionError("transition_bars needs a transition other than cut (filter_swap, drop_swap, riser)")
        return 0
    if value in (None, ""):
        return DEFAULT_BARS[name]
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float("nan")
    if isinstance(value, bool) or not (BARS_MIN <= number <= BARS_MAX and number == int(number)):
        raise TransitionError(f"transition_bars must be a whole number {BARS_MIN}-{BARS_MAX}, got {value!r}")
    return int(number)


def filter_from(name, value):
    """filter_from (the cutoff to start a filter_swap from where Whiplash hasn't sent one) -> 0-127 or None."""
    if value in (None, ""):
        return None
    if name != "filter_swap":
        raise TransitionError("filter_from only applies to transition filter_swap")
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = float("nan")
    if isinstance(value, bool) or not (0 <= number <= 127 and number == int(number)):
        raise TransitionError(f"filter_from must be a whole number 0-127, got {value!r}")
    return int(number)


def describe(name, n):
    """One line for a tool result."""
    return {
        "cut": "switches on the next bar line",
        "filter_swap": (f"outgoing cutoff (filter_freq) closes to {FILTER_FLOOR} over {n} bar(s), the switch lands on "
                        f"the one, then the cutoff reopens to where it was over {REOPEN_BARS} bar"),
        "drop_swap": f"kick and bass sit out the last {n} bar(s), then come back with the switch on the one",
        "riser": (f"fx-labelled tracks' filter_freq rises {RISER_FROM}->{RISER_TO} over {n} bar(s), with a drum fill "
                  "on the last bar"),
    }[name]
