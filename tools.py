"""Tool handlers. Each returns a JSON string and never raises."""
import functools
import json
import logging

from . import ccmap
from . import engine as eng
from . import patterns
from . import view

log = logging.getLogger("whiplash")
PREFIX = "whiplash_"
ENGINE = eng.Engine()

VIRTUAL_WARNING = (
    f"NO DIGITAKT DETECTED: MIDI is going to the virtual port '{eng.VIRTUAL_NAME}', so the hardware is "
    "silent. Tell the user. To switch: connect the Digitakt II over USB, get its port name from "
    "whiplash_list_midi_ports, then call whiplash_play_pattern with that port.")


SAMPLE_NOTE = ("Whiplash can't list, preview or hear samples: the slot picks a sample already loaded in the "
               "project pool, counted within the sample bank selected on the unit. Ask the user what the slot "
               "holds or try neighbouring slots. Nothing is loaded onto or saved to the unit; reloading the "
               "pattern/kit on the unit restores its own sample.")


def overlap_warning(send_transport):
    """Shown on every whiplash_play_pattern result (start and queued switch)."""
    if send_transport:
        return ("Whiplash sends MIDI Start, which also starts the Digitakt's own sequencer: any trigs stored in "
                "the pattern selected on the unit play on top of Whiplash, and Whiplash mutes can't silence them. "
                "Tell the user to select an empty pattern on the unit unless they want it layered, or restart with "
                "send_transport=false (clock only).")
    return ("Clock only: Whiplash sent no MIDI Start, so the Digitakt's own sequencer stays stopped and only "
            "Whiplash's notes play. If the user presses Play on the unit, its selected pattern plays on top in "
            "sync; Whiplash won't send Stop, so the user stops it on the unit.")


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
        view.record_action(PREFIX + fn.__name__, params or {}, out)
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
                      "64. Raw cc / nrpn stay available on whiplash_set_param. sample_slot (or "
                      "whiplash_select_sample) picks a sample already in the project pool by slot number in the "
                      "unit's current sample bank; Whiplash can't list or preview samples, and sample bank select "
                      "stays blocked.")}


@_tool
def play_pattern(p):
    pattern = patterns.resolve(p.get("genre"), p.get("mood"))
    result = ENGINE.play(pattern, bpm=p.get("bpm"), bars=p.get("bars"), port=p.get("port"),
                         send_transport=p.get("send_transport"), transpose=p.get("transpose"), tracks=p.get("tracks"))
    transport = {"send_transport": result["send_transport"],
                 "transport_mode": eng.transport_mode(result["send_transport"]),
                 "overlap_warning": overlap_warning(result["send_transport"])}
    if result["mode"] == "queued":
        status = ENGINE.status()
        out = {"mode": "queued", "playing": status["pattern"], "next": pattern.name,
               "switch_at_bar": result["switch_at_bar"], "bar": status["bar"],
               "bpm_at_switch": result_bpm(p, pattern), "swing": pattern.swing,
               "bars": eng.check_bars(p.get("bars")),
               "tracks": ENGINE.tracks_summary(pattern, transpose=_queued_transpose(status)),
               "muted_carried": status["muted"], "ramps_carried": [r["id"] for r in status["ramps"]],
               "transpose_carried": status["transpose"],
               "port": ENGINE.port_name, "virtual": ENGINE.virtual, **transport, **track_notes()}
        if result["replaced_queued"]:
            out["replaced_queued"] = result["replaced_queued"]
        if result.get("setup"):
            out["setup"] = setup_echo(result["setup"], f"at the switch, bar {result['switch_at_bar']}")
        return out
    out = {"mode": "started", "playing": pattern.name, "bpm": ENGINE.bpm, "swing": pattern.swing,
           "bars": ENGINE.bars_total, "port": ENGINE.port_name, "virtual": ENGINE.virtual,
           "tracks": ENGINE.tracks_summary(),
           "replaced_playing": result["was_playing"], "mutes_cleared": result["mutes_cleared"],
           "ramps_cancelled": result["ramps_cancelled"], **transport, **track_notes()}
    if result.get("setup"):
        out["setup"] = setup_echo(result["setup"], "before the first bar")
    return out


def track_notes():
    labelled = bool(ENGINE.kit()["tracks"])
    return {"roles_assumed": not labelled, "kit_note": eng.KIT_LABELLED_NOTE if labelled else eng.KIT_NOTE,
            "pitch_note": eng.PITCH_NOTE}


def setup_echo(setup, when):
    """play_pattern's per-track settings as applied, with slot labels from the kit map."""
    out = {}
    for track, entry in sorted(setup.items()):
        item = dict(entry)
        if "slot" in item:
            label = ENGINE.slot_label(item["slot"])
            if label:
                item["slot_label"] = label
        out[str(track)] = item
    return {"tracks": out, "applied": when}


def _queued_transpose(status):
    """The transposes the queued pattern will play with: the carried ones plus the switch's own."""
    out = {int(t): v for t, v in status["transpose"].items()}
    for t, v in (status["queued"] or {}).get("transpose", {}).items():
        if v:
            out[int(t)] = v
        else:
            out.pop(int(t), None)
    return out


def result_bpm(p, pattern):
    return eng.check_bpm(pattern.bpm if p.get("bpm") is None else p["bpm"])


@_tool
def set_param(p):
    ENGINE.ensure_port()
    out = ENGINE.set_param(p["track"], p["value"], param=p.get("param"), cc=p.get("cc"), nrpn=p.get("nrpn"))
    label = ENGINE.slot_label(out["value"]) if out.get("param") == "sample_slot" else None
    if label:
        out["slot_label"] = label
    return out


@_tool
def select_sample(p):
    ENGINE.ensure_port()
    out = ENGINE.set_param(p["track"], p["slot"], param="sample_slot")
    result = {"track": out["track"], "slot": out["value"], "cc": out["cc"], "note": SAMPLE_NOTE}
    label = ENGINE.slot_label(out["value"])
    if label:
        result["slot_label"] = label
    return result


@_tool
def label_tracks(p):
    return ENGINE.label_tracks(tracks=p.get("tracks"), slots=p.get("slots"), reset=p.get("reset"))


@_tool
def transpose(p):
    out = ENGINE.set_transpose(p["track"], semitones=p.get("semitones"), octaves=p.get("octaves"))
    return {**out, "pitch_note": eng.PITCH_NOTE}


@_tool
def write_part(p):
    out = ENGINE.write_part(p["track"], rhythm=p.get("rhythm"), grid=p.get("grid"), steps=p.get("steps"),
                            hits=p.get("hits"), lock_to=p.get("lock_to"), notes=p.get("notes"), key=p.get("key"),
                            scale=p.get("scale"), length=p.get("length"), velocity=p.get("velocity"),
                            bars=p.get("bars"), reset=p.get("reset"), envelope=p.get("envelope"))
    if not out.get("reset"):
        out["pitch_note"] = eng.PITCH_NOTE
    return out


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


@_tool
def open_view(p):
    port = p.get("port")
    if port not in (None, ""):
        port = eng.check_whole(port, 1024, 65535, "port")
    else:
        port = None
    out = view.open_view(ENGINE, port=port, browser=p.get("open_browser", True) is not False)
    out["note"] = ("A local page now shows the beat live: tracks, BPM, ramps, mutes, an audio analyser and this "
                   "conversation. It only watches; keep jamming here. Tell the user the URL in case the browser "
                   "did not open.")
    return out


@_tool
def close_view(p):
    return view.close_view()


HANDLERS = {PREFIX + f.__name__: f for f in (list_midi_ports, list_params, play_pattern, set_param,
                                             select_sample, label_tracks, transpose, write_part, ramp_param, mutate, mute_track, unmute_track, set_tempo, stop,
                                             status, open_view, close_view)}
