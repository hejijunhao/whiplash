"""Tool handlers. Each returns a JSON string and never raises."""
import functools
import json
import logging

from . import engine as eng
from . import patterns

log = logging.getLogger("whiplash")
PREFIX = "whiplash_"
ENGINE = eng.Engine()

VIRTUAL_WARNING = (
    f"NO DIGITAKT DETECTED: MIDI is going to the virtual port '{eng.VIRTUAL_NAME}', so the hardware is "
    "silent. Tell the user. To switch: connect the Digitakt II over USB, get its port name from "
    "whiplash_list_midi_ports, then call whiplash_play_pattern with that port.")


def _tool(fn):
    @functools.wraps(fn)
    def wrapper(params=None, **kwargs):
        try:
            out = {"success": True, **fn(params or {})}
        except KeyError as exc:
            out = {"success": False, "error": f"missing required argument {exc}"}
        except (eng.WhiplashError, ValueError, TypeError) as exc:
            out = {"success": False, "error": str(exc)}
        except Exception as exc:
            log.exception("whiplash tool %s failed", fn.__name__)
            out = {"success": False, "error": f"{type(exc).__name__}: {exc}"}
        if ENGINE.fallback:  # on every result, so the agent cannot miss that nothing is audible
            out.setdefault("warning", VIRTUAL_WARNING)
        return json.dumps(out)
    return wrapper


@_tool
def list_midi_ports(p):
    ports = eng.list_ports()
    device = eng.find_device(ports["outputs"])
    out = {**ports, "digitakt": device}
    if not device:
        out["warning"] = (f"No Digitakt II found. Whiplash will fall back to a virtual MIDI port named "
                          f"'{eng.VIRTUAL_NAME}'; nothing will sound on hardware until the unit is connected.")
    return out


@_tool
def play_pattern(p):
    pattern = patterns.resolve(p.get("genre"), p.get("mood"))
    stopped = ENGINE.play(pattern, bpm=p.get("bpm"), bars=p.get("bars"), port=p.get("port"))
    return {"playing": pattern.name, "bpm": ENGINE.bpm, "swing": pattern.swing, "bars": ENGINE.bars_total,
            "port": ENGINE.port_name, "virtual": ENGINE.virtual, "tracks": pattern.roles,
            "replaced_playing": stopped["was_playing"], "mutes_cleared": stopped["mutes_cleared"]}


@_tool
def set_param(p):
    ENGINE.ensure_port()
    return ENGINE.set_param(p["track"], p["value"], param=p.get("param"), cc=p.get("cc"), nrpn=p.get("nrpn"))


def _mute(p, muted):
    track = eng.check_track(p["track"])
    ENGINE.set_mute(track, muted, hardware=bool(p.get("hardware")))
    return {"track": track, "muted": muted, "all_muted": sorted(ENGINE.muted),
            "hardware_muted": sorted(ENGINE.hw_muted)}


@_tool
def mute_track(p):
    return _mute(p, True)


@_tool
def unmute_track(p):
    return _mute(p, False)


@_tool
def set_tempo(p):
    ENGINE.set_tempo(p["bpm"])
    return {"bpm": ENGINE.bpm}


@_tool
def stop(p):
    return {"stopped": True, **ENGINE.stop()}


@_tool
def status(p):
    return ENGINE.status()


HANDLERS = {PREFIX + f.__name__: f for f in (list_midi_ports, play_pattern, set_param, mute_track,
                                             unmute_track, set_tempo, stop, status)}
