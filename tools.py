"""Tool handlers. Each returns a JSON string and never raises."""
import functools
import json
import logging

from . import engine as eng
from . import patterns

log = logging.getLogger("whiplash")
ENGINE = eng.Engine()


def _tool(fn):
    @functools.wraps(fn)
    def wrapper(params=None, **kwargs):
        try:
            return json.dumps({"success": True, **fn(params or {})})
        except (eng.WhiplashError, ValueError, TypeError) as exc:
            return json.dumps({"success": False, "error": str(exc)})
        except Exception as exc:
            log.exception("whiplash tool %s failed", fn.__name__)
            return json.dumps({"success": False, "error": f"{type(exc).__name__}: {exc}"})
    return wrapper


@_tool
def list_midi_ports(p):
    ports = eng.list_ports()
    device = eng.find_device(ports["outputs"])
    return {**ports, "digitakt": device, "fallback": None if device else f"virtual port '{eng.VIRTUAL_NAME}'"}


@_tool
def play_pattern(p):
    pattern = patterns.resolve(p.get("genre"), p.get("mood"))
    bars = p.get("bars")
    ENGINE.play(pattern, bpm=p.get("bpm"), bars=int(bars) if bars else None, port=p.get("port"))
    return {"playing": pattern.name, "bpm": ENGINE.bpm, "swing": pattern.swing, "bars": bars,
            "port": ENGINE.port_name, "virtual": ENGINE.virtual, "tracks": pattern.roles}


@_tool
def set_param(p):
    ENGINE.ensure_port()
    return ENGINE.set_param(p["track"], p["value"], param=p.get("param"), cc=p.get("cc"), nrpn=p.get("nrpn"))


def _mute(p, muted):
    track = int(p["track"])
    if not 1 <= track <= 16:
        raise eng.WhiplashError("track must be 1-16")
    ENGINE.set_mute(track, muted)
    if p.get("hardware"):
        ENGINE.ensure_port()
        ENGINE.set_param(track, 1 if muted else 0, param="mute")
    return {"track": track, "muted": muted, "all_muted": sorted(ENGINE.muted)}


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
    was = ENGINE.playing()
    ENGINE.stop()
    return {"stopped": True, "was_playing": was}


@_tool
def whiplash_status(p):
    return ENGINE.status()


HANDLERS = {f.__name__: f for f in (list_midi_ports, play_pattern, set_param, mute_track,
                                    unmute_track, set_tempo, stop, whiplash_status)}
