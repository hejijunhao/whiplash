"""Whiplash: let a Hermes agent jam on an Elektron Digitakt II over USB MIDI.

register() only wires schemas to handlers; MIDI ports and the sequencer
thread open lazily on the first tool call.
"""
import logging

from .schemas import SCHEMAS
from .tools import HANDLERS

log = logging.getLogger("whiplash")
TOOLSET = "whiplash"


def register(ctx):
    for name, schema in SCHEMAS.items():
        ctx.register_tool(name=name, toolset=TOOLSET, schema=schema, handler=HANDLERS[name], emoji="🥁")
    log.info("whiplash: registered %d tools", len(SCHEMAS))
