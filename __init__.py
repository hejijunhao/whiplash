"""Whiplash: let a Hermes agent jam on an Elektron Digitakt II over USB MIDI.

register() only wires schemas to handlers, registers the bundled whiplash:digitakt
skill (when the Hermes build has ctx.register_skill), and subscribes the visualiser's
conversation hooks (in-memory, return None, never raise). MIDI ports, the
sequencer thread and the view server open lazily on the first tool call.
"""
import logging
from pathlib import Path

from . import chat
from .schemas import SCHEMAS
from .tools import HANDLERS

__version__ = "0.7.0"  # keep in sync with pyproject.toml, plugin.yaml and docs/catalog-entry.yaml (tests check)
log = logging.getLogger("whiplash")
TOOLSET = "whiplash"
SKILL_NAME = "digitakt"  # resolves as "whiplash:digitakt"
SKILL_PATH = Path(__file__).resolve().parent / "skills" / SKILL_NAME / "SKILL.md"
SKILL_DESCRIPTION = ("How to drive a Digitakt II through Whiplash: the kit map and one-call start, keys and chord "
                     "progressions, song arrangement, transitions and mix levels, listening to the unit's audio and the "
                     "loudness guard, pitch and register, "
                     "sample slots, note length vs AMP MODE/HOLD, transport overlap, and a checklist for sounds that "
                     "come out wrong.")


def register_skill(ctx):
    """Register the bundled skill. Skipped on Hermes builds without the API; never breaks loading."""
    if not hasattr(ctx, "register_skill"):
        return False
    try:
        ctx.register_skill(SKILL_NAME, SKILL_PATH, description=SKILL_DESCRIPTION)
    except Exception:
        log.exception("whiplash: registering skill %s failed; tools still load", SKILL_NAME)
        return False
    return True


def register(ctx):
    for name, schema in SCHEMAS.items():
        ctx.register_tool(name=name, toolset=TOOLSET, schema=schema, handler=HANDLERS[name], emoji="🥁")
    skill = register_skill(ctx)
    hooks = chat.register_hooks(ctx)
    log.info("whiplash: registered %d tools, %d hooks, skill %s", len(SCHEMAS), len(hooks),
             "whiplash:" + SKILL_NAME if skill else "skipped")
