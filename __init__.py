"""Whiplash: let a Hermes agent jam on an Elektron Digitakt II over USB MIDI.

register() only wires schemas to handlers and subscribes the visualiser's
conversation hooks (in-memory, return None, never raise). MIDI ports, the
sequencer thread and the view server open lazily on the first tool call.
"""
import logging

from . import chat
from .schemas import SCHEMAS
from .tools import HANDLERS

log = logging.getLogger("whiplash")
TOOLSET = "whiplash"


def register(ctx):
    for name, schema in SCHEMAS.items():
        ctx.register_tool(name=name, toolset=TOOLSET, schema=schema, handler=HANDLERS[name], emoji="🥁")
    hooks = chat.register_hooks(ctx)
    log.info("whiplash: registered %d tools, %d hooks", len(SCHEMAS), len(hooks))
