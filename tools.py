"""Tool handlers. Each returns a JSON string and never raises."""
import functools
import json
import logging

from . import ccmap
from . import engine as eng
from . import patterns

log = logging.getLogger("whiplash")
PREFIX = "whiplash_"
ENGINE = eng.Engine()

VIRTUAL_WARNING = (
    f"NO DIGITAKT DETECTED: MIDI is going to the virtual port '{eng.VIRTUAL_NAME}', so the hardware is "
    "silent. Tell the user. To switch: connect the Digitakt II over USB, get its port name from "
    "whiplash_list_midi_ports, then call whiplash_play_pattern with that port.")


def device_notice(name):
    return (f"DIGITAKT CONNECTED: '{name}' is now available but Whiplash is still playing into the silent "
            f"virtual port. Tell the user, then call whiplash_play_pattern with port='{name}' to move the beat "
            "onto the hardware. Whiplash never switches on its own.")


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
        if ENGINE.virtual:  # on every result, so the agent cannot miss that nothing is audible
            device = ENGINE.check_hotplug()
            if device:
                out["device_available"] = device
            if ENGINE.fallback:
                out.setdefault("warning", VIRTUAL_WARNING)
                if device:
                    out["notice"] = device_notice(device)
        if ENGINE.port_lost and not out.get("port"):
            out["port_lost"] = ENGINE.port_lost
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
def list_params(p):
    return {"params": ccmap.table(), "count": len(ccmap.PARAMS),
            "notes": ("Named params are 7-bit CC (0-127) on the track's channel; values outside a param's range "
                      "are clamped (switches like mute/play_mode are rejected instead). Centred params rest at "
                      "64. Raw cc / nrpn stay available on whiplash_set_param.")}


@_tool
def play_pattern(p):
    pattern = patterns.resolve(p.get("genre"), p.get("mood"))
    result = ENGINE.play(pattern, bpm=p.get("bpm"), bars=p.get("bars"), port=p.get("port"))
    if result["mode"] == "queued":
        status = ENGINE.status()
        out = {"mode": "queued", "playing": status["pattern"], "next": pattern.name,
               "switch_at_bar": result["switch_at_bar"], "bar": status["bar"],
               "bpm_at_switch": result_bpm(p, pattern), "swing": pattern.swing,
               "bars": eng.check_bars(p.get("bars")), "tracks": pattern.roles,
               "muted_carried": status["muted"], "ramps_carried": [r["id"] for r in status["ramps"]],
               "port": ENGINE.port_name, "virtual": ENGINE.virtual}
        if result["replaced_queued"]:
            out["replaced_queued"] = result["replaced_queued"]
        return out
    return {"mode": "started", "playing": pattern.name, "bpm": ENGINE.bpm, "swing": pattern.swing,
            "bars": ENGINE.bars_total, "port": ENGINE.port_name, "virtual": ENGINE.virtual, "tracks": pattern.roles,
            "replaced_playing": result["was_playing"], "mutes_cleared": result["mutes_cleared"],
            "ramps_cancelled": result["ramps_cancelled"]}


def result_bpm(p, pattern):
    return eng.check_bpm(pattern.bpm if p.get("bpm") is None else p["bpm"])


@_tool
def set_param(p):
    ENGINE.ensure_port()
    return ENGINE.set_param(p["track"], p["value"], param=p.get("param"), cc=p.get("cc"), nrpn=p.get("nrpn"))


@_tool
def ramp_param(p):
    if p.get("cancel") not in (None, ""):
        return {"cancelled": ENGINE.cancel_ramps(p["cancel"]), "active": ENGINE.ramps()}
    if "to" not in p:
        raise KeyError("to")
    return ENGINE.ramp(p["track"], p["to"], param=p.get("param"), cc=p.get("cc"), start=p.get("from"),
                       beats=p.get("beats"), bars=p.get("bars"), curve=p.get("curve", "linear"))


MUTATIONS = ("density", "fill", "swing", "humanize", "drop", "reset")


@_tool
def mutate(p):
    action = str(p.get("action", "")).strip().lower()
    if action not in MUTATIONS:
        raise eng.WhiplashError(f"action must be one of {', '.join(MUTATIONS)}")
    if action == "density":
        out = ENGINE.mutate_density(p.get("tracks"), p.get("amount"))
    elif action == "fill":
        out = ENGINE.schedule_fill(p.get("tracks"))
    elif action == "swing":
        out = ENGINE.mutate_swing(p.get("amount"))
    elif action == "humanize":
        out = ENGINE.mutate_humanize(p.get("amount"))
    elif action == "drop":
        out = ENGINE.schedule_drop(p.get("tracks"), p.get("bars", 2), fill=bool(p.get("fill")))
    else:
        out = ENGINE.reset_mutations()
    status = ENGINE.status()
    if status["queued"] and action in ("density", "swing", "humanize"):
        out["note"] = (f"a switch to {status['queued']['pattern']} is queued at bar "
                       f"{status['queued']['switch_at_bar']}; this mutation resets when it lands (mutes, ramps and drops "
                       "carry over)")
    return {"action": action, "bar": status["bar"], **out}


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
    out = ENGINE.status()
    if ENGINE.virtual:
        out["device_available"] = ENGINE.check_hotplug()
    return out


HANDLERS = {PREFIX + f.__name__: f for f in (list_midi_ports, list_params, play_pattern, set_param, ramp_param,
                                             mutate, mute_track, unmute_track, set_tempo, stop, status)}
