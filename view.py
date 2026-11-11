"""Live visualiser: a tiny local web page that shows what Whiplash is doing.

whiplash_open_view starts a stdlib HTTP server bound to 127.0.0.1 inside the Hermes process
and opens the default browser on it. The page (view.html, one file, no build step) gets
state over Server-Sent Events.

Clock safety: the sequencer thread only publishes two tuples (Engine.position, Engine.bar_hits)
by plain assignment. A single "whiplash-view" publisher thread builds a snapshot at most
SNAPSHOT_HZ times a second, and only while a browser is connected, using Engine.view_state()
(a short copy under the engine lock, the same cost as whiplash_status). All formatting and
JSON encoding happen outside that lock. The browser interpolates the playhead between frames,
so the plugin never has to push at frame rate. The view is read-only: nothing here sends MIDI.
"""
import atexit
import itertools
import json
import logging
import threading
import time
import webbrowser
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import ccmap, chat, harmony, patterns
from . import engine as eng
from . import listen as _listen

log = logging.getLogger("whiplash")

HOST = "127.0.0.1"
DEFAULT_PORT = 7341
SNAPSHOT_HZ = 10
IDLE_HEARTBEAT = 2.0  # seconds between frames when nothing changes and nothing plays
SSE_PING = 15.0
PAGE = Path(__file__).with_name("view.html")
CC_NAMES = {p.cc: p.name for p in ccmap.PARAMS.values()}
CC_MAX = {p.cc: p.max for p in ccmap.PARAMS.values()}  # knob/fader travel on the page
CC_MAX[ccmap.PARAMS["amp_hold"].cc] = 127  # 127 (HOLD = NOTE) can still be sent explicitly
SAMPLE_SLOT_CC = ccmap.PARAMS["sample_slot"].cc
HIDDEN_CCS = ccmap.BLOCKED_CCS | {123, eng.MUTE_CC, SAMPLE_SLOT_CC}  # all-notes-off, NRPN plumbing; mute/slot are badges
AMP_MODE_CC = ccmap.PARAMS["amp_mode"].cc
HOLD_CC = ccmap.PARAMS["amp_hold"].cc
LOG_SIZE = 40

ACTIONS = deque(maxlen=LOG_SIZE)  # recent Whiplash tool calls, appended by tools._tool
_action_ids = itertools.count(1)  # next() is atomic under the GIL: tools may run in parallel


def note_name(note):
    """Elektron octave numbering (C5 = 60), the same names whiplash_write_part echoes back."""
    return patterns.note_name(note)


def _amp(ch, cc_values):
    """What Whiplash last sent for the amp envelope mode on this channel, or None if it sent neither.

    The unit only ends a sound on note-off with AMP MODE = ADSR or HOLD = NOTE (reference §5.2), so
    the page uses this to say whether a written part's length is audible. It is what Whiplash sent,
    not what the unit is set to: the kit may differ.
    """
    mode, hold = cc_values.get((ch, AMP_MODE_CC)), cc_values.get((ch, HOLD_CC))
    if mode is None and hold is None:
        return None
    return {"mode": "ADSR" if mode == 1 else "AHD" if mode == 0 else None, "hold_note": hold == eng.HOLD_NOTE}


# ---- tool action log -------------------------------------------------------

def _summary(name, out):
    if not out.get("success", True):
        return "error: " + str(out.get("error", ""))[:140]
    keys = {
        "whiplash_play_pattern": ("mode", "playing", "next", "switch_at_bar", "bpm"),
        "whiplash_ramp_param": ("ramp_id", "param", "from", "to", "cancelled"),
        "whiplash_set_param": ("param", "cc", "value"),
        "whiplash_mutate": ("action", "fill_at_bar", "from_bar", "returns_at_bar", "swing", "density"),
        "whiplash_mute_track": ("track", "muted"), "whiplash_unmute_track": ("track", "muted"),
        "whiplash_set_tempo": ("bpm",), "whiplash_stop": ("stopped",),
        "whiplash_open_view": ("url",), "whiplash_close_view": ("closed",),
    }.get(name, ())
    bits = [f"{k} {json.dumps(out[k], separators=(',', ':')) if isinstance(out[k], (dict, list)) else out[k]}"
            for k in keys if out.get(k) not in (None, "", [], {})]
    if out.get("warning"):
        bits.append("virtual port")
    return ", ".join(bits)[:160] or "ok"


def _tracks(params):
    found = []
    for key in ("track", "tracks"):
        value = params.get(key)
        for t in value if isinstance(value, (list, tuple)) else [value]:
            try:
                n = int(t)
            except (TypeError, ValueError):
                continue
            if 1 <= n <= 16:
                found.append(n)
    return sorted(set(found))


def record_action(name, params, out):
    """Called by every tool after it ran. Cheap and never raises."""
    try:
        args = {k: v for k, v in (params or {}).items() if v not in (None, "")}
        ACTIONS.append({"id": next(_action_ids), "ts": time.time(), "tool": name,
                        "args": json.dumps(args, separators=(",", ":"), default=str)[:200],
                        "ok": bool(out.get("success", True)), "summary": _summary(name, out),
                        "tracks": _tracks(params or {})})
        if name == "whiplash_listen":
            record_listen(out)
    except Exception:
        log.debug("whiplash view: action log failed", exc_info=True)


# ---- listening loop (v0.7.0) -------------------------------------------------
# The engine keeps only a four-number summary of the last whiplash_listen (Engine.last_listen, for the loudness
# guard). The page wants what was heard in more detail: the four-band balance, onset timing, kick offsets. The
# tool result already passes through record_action, so the view keeps a compact copy of it here (never audio:
# the result never holds any). No engine or tool change.

LISTEN = {"last": None, "error": None}  # last good listen (compact) and the error of a failed one after it
_LISTEN_KEYS = {
    "loudness": ("lufs_ish", "rms_dbfs", "peak_dbfs", "headroom_db", "clipping", "clipped_samples"),
    "onsets": ("count", "per_bar", "on_grid_pct", "median_abs_offset_ms", "max_abs_offset_ms", "swing_estimate",
               "latency_corrected_ms"),
    "kick": ("sent", "heard", "missed", "median_offset_ms", "spread_ms", "offsets_ms"),
    "low_end": ("kick_over_rest_db", "masking"),
}
_deps = [None]


def _pick(d, keys):
    return {k: d.get(k) for k in keys} if isinstance(d, dict) else None


def record_listen(out):
    """Keep what the page shows of a whiplash_listen result. A failed listen keeps the last good one (dimmed)."""
    if not out.get("success", True):
        LISTEN["error"] = {"ts": time.time(), "error": str(out.get("error", ""))[:240]}
        return
    bands = out.get("bands")
    tracks = out.get("tracks") or {}
    LISTEN["error"] = None
    LISTEN["last"] = {
        "ts": time.time(), "bars": out.get("bars"), "bpm": out.get("bpm"), "from_bar": out.get("from_bar"),
        "seconds": out.get("seconds"), "playing": bool(out.get("playing")), "silent": bool(out.get("silent")),
        "device": str(out.get("device") or "")[:60],
        "bands": ([{"band": b, "pct": (bands.get(b) or {}).get("pct"), "db": (bands.get(b) or {}).get("db")}
                   for b, _lo, _hi in _listen.BANDS] if isinstance(bands, dict) else None),
        **{k: _pick(out.get(k), keys) for k, keys in _LISTEN_KEYS.items()},
        "quiet_tracks": sorted(int(t) for t, e in tracks.items() if isinstance(e, dict) and e.get("seems_silent")),
        "unexpected_audio": bool(out.get("unexpected_audio")),
        "notes": [str(n)[:160] for n in (out.get("notes") or [])[:3]],
    }


def _listen_deps():
    """numpy / sounddevice installed? Looked up once (find_spec, no import): installing them needs a restart."""
    if _deps[0] is None:
        try:
            _deps[0] = _listen.available()
        except Exception:
            _deps[0] = {}
    return _deps[0]


def _listening(engine):
    """The EAR module: the last listen, whether one is running, and why there is nothing when there isn't.

    Timestamps, not ages, so an idle frame stays byte-identical and the publisher keeps to its heartbeat."""
    heard = getattr(engine, "last_listen", None)  # one reference read; record_listen replaces it whole
    deps = _listen_deps()
    last = LISTEN["last"]
    if heard is None:
        last = None  # whiplash_stop doesn't clear it, but a new engine (tests, restart) has heard nothing
    elif last is None:  # heard before this view module loaded: the engine's summary is all there is
        last = {"ts": heard.get("at"), "bars": heard.get("bars"), "silent": heard.get("silent"), "bands": None,
                "loudness": {"lufs_ish": heard.get("lufs_ish"), "peak_dbfs": heard.get("peak_dbfs"),
                             "clipping": heard.get("clipping")}, "summary_only": True}
    error = LISTEN["error"]
    if error and last and last.get("ts") and last["ts"] > error["ts"]:
        error = None
    return {"running": _listen._BUSY.locked(), "last": last, "error": error,
            "guard": bool(heard and heard.get("clipping")),
            "installed": bool(deps) and all(deps.values()), "deps": deps}


# ---- section timeline (v0.6.1 arrangement) -----------------------------------

TIMELINE_AHEAD = 32  # bars of fills, drops and switches shown ahead of the playhead


def _arrangement(engine, bar):
    """whiplash_arrange's sections laid on absolute bar lines, for the cycle the playhead is in.

    Engine.arrangement_status() is the same read-only summary whiplash_status shows; it expects the engine lock
    (a dict walk over a handful of sections, like view_state's copy)."""
    status = getattr(engine, "arrangement_status", None)
    if status is None:
        return None
    with engine._lock:
        arr = status()
    if not arr:
        return None
    secs = arr["sections"]
    lengths = [s["bars"] for s in secs]
    cur = arr.get("current")
    if cur is not None:  # the cycle start: the current section's first bar minus the sections before it
        i = cur["index"]
        cycle = cur["next_at_bar"] - lengths[i] - sum(lengths[:i])
    else:
        cycle = arr["starts_at_bar"]
    out_secs, at = [], cycle
    for s in secs:
        out_secs.append({"name": s["name"], "bars": s["bars"], "start": at, "end": at + s["bars"],
                         "transition": s.get("transition")})
        at += s["bars"]
    return {"name": arr["name"], "loop": arr["loop"], "start": arr["starts_at_bar"], "total": arr["total_bars"],
            "cycle": cycle, "sections": out_secs, "index": cur["index"] if cur else None,
            "next": cur["next"] if cur else None, "next_at": cur["next_at_bar"] if cur else arr["starts_at_bar"],
            "stops_at": cur.get("stops_at_bar") if cur else (None if arr["loop"] else arr["starts_at_bar"] + arr["total_bars"]),
            "ended_at": arr.get("ended_at_bar"), "skipped": len(arr.get("skipped_ramps") or ()),
            "muted": arr.get("muted_by_arrangement") or []}


def _timeline(engine, st, bar):
    """The SECTIONS module: the arrangement (if any) and what is already scheduled on upcoming bar lines.

    Events come from what view_state copies anyway (fills, drops, the queued switch and its transition). A
    section's own fill or drop is scheduled when the section starts, so it appears from then on."""
    events = []
    for b, ts in sorted(st["fills"].items()):
        if bar <= b <= bar + TIMELINE_AHEAD and ts:
            events.append({"kind": "fill", "bar": b, "bars": 1, "tracks": sorted(ts)})
    drops = {}
    for t, (start, back) in st["drops"].items():
        if back > bar and start <= bar + TIMELINE_AHEAD:
            drops.setdefault((start, back), []).append(t)
    for (start, back), ts in sorted(drops.items()):
        events.append({"kind": "drop", "bar": start, "bars": back - start, "tracks": sorted(ts)})
    queued = st["queued"]
    if queued:
        tx = queued.get("transition")
        if tx:
            events.append({"kind": "transition", "bar": tx["starts_at_bar"], "bars": tx["bars"],
                           "transition": tx["kind"], "tracks": []})
        events.append({"kind": "switch", "bar": queued["at"], "bars": 0, "pattern": queued["pattern"].name,
                       "tracks": []})
    try:
        arr = _arrangement(engine, bar)
    except Exception:
        log.debug("whiplash view: arrangement read failed", exc_info=True)
        arr = None
    return {"arrangement": arr, "events": events[:24], "ahead": TIMELINE_AHEAD}


# ---- snapshot --------------------------------------------------------------

def _hits(bar_hits, track):
    return [[s, n, v, g] for s in sorted(bar_hits) for (t, n, v, g, _o) in bar_hits[s] if t == track]


MODE_TAGS = {"chords": "CHD", "stack": "STK", "root": "ROOT", "snap": "SNAP"}  # the page's short mode labels


def _line(track, bars, bar, pattern_start, hm):
    """One track's hits for absolute bar `bar`, as the sequencer will build them (before fills, humanize
    and transpose): the working line, re-voiced for the chord playing in that bar (harmony.apply), or a
    held tone for a chord track with no line. Pure lookups, outside the engine lock."""
    _session, _key, prog, modes, ranks, pads = hm
    hits = bars[(bar - pattern_start) % patterns.BARS] if bars else []
    if prog is None or bar < prog.start or track not in modes:
        return hits
    if track in pads:
        hits = harmony.pad_line()
    i = prog.index(bar)
    return harmony.apply(modes[track], hits, prog.voicings[i], prog.chords[i].root, prog.key, ranks.get(track, 0))


def _harmony(st, bar, pattern):
    """The KEY / CHORDS module: the key, the progression, the chord now and the next change."""
    session, key, prog, _modes, _ranks, _pads = st["hm"]
    queued = st["queued"]
    out = {"key": key.name if key else None, "flats": bool(key and key.flats),
           "key_source": "set" if session is not None else "pattern" if pattern is not None else None,
           "next_key": None, "progression": None}
    if queued:
        nxt = queued.get("key") or session or harmony.key_of(queued["pattern"].key)
        if nxt is not None and nxt != key:
            out["next_key"] = {"key": nxt.name, "at": queued["at"]}
    if prog is None:
        return out
    flats = prog.key.flats
    started = bar >= prog.start
    index = prog.index(bar) if started else None
    into = (bar - prog.start) % prog.bars_per_chord if started else 0
    next_at = bar + prog.bars_per_chord - into if started else prog.start
    out["flats"] = flats
    out["progression"] = {
        "key": prog.key.name, "bars_per_chord": prog.bars_per_chord, "voicing": prog.voicing,
        "loop_bars": prog.length, "start": prog.start, "index": index, "next_at": next_at,
        "next_index": prog.index(next_at),
        "chords": [{"symbol": c.symbol, "name": c.name, "notes": [harmony.note_label(n, flats) for n in v]}
                   for c, v in zip(prog.chords, prog.voicings)],
    }
    return out


def snapshot(engine, now=None):
    """The frame the page renders: plain JSON-able data. Never raises on a consistent engine."""
    now = time.perf_counter() if now is None else now
    st = engine.view_state()
    pattern, playing, bar = st["pattern"], st["playing"], st["bar"]
    queued = st["queued"]
    frame = {
        "playing": playing, "bpm": st["bpm"], "swing": round(st["swing"] * 100), "humanize": st["humanize"],
        "bar": bar, "pattern": pattern.name if pattern else None,
        "pattern_bar": bar - st["pattern_start"], "bars": st["bars"],
        "loop_bar": (bar - st["pattern_start"]) % patterns.BARS, "steps": patterns.STEPS,
        "queued": ({"pattern": queued["pattern"].name, "bpm": queued["bpm"], "at": queued["at"]} if queued else None),
        "port": {"name": st["port"], "virtual": st["virtual"], "fallback": st["fallback"],
                 "lost": st["port_lost"], "error": st["last_error"]},
        "messages_sent": st["messages_sent"], "pos": None, "lanes": [],
        "transport_mode": st.get("transport_mode"), "harmony": None, "timeline": None,
        "listen": _listening(engine),
    }
    position = st["position"]
    if playing and position:
        p_bar, p_step, due = position
        frame["pos"] = {"bar": p_bar, "step": p_step, "age": round(now - due, 4)}
    if not playing or pattern is None:
        return frame
    # v0.6.0 keys and progressions: a read-only copy from view_state (older engines have none)
    hm = st["hm"] = st.get("harmony") or (None, None, None, {}, {}, frozenset())
    prog, prog_modes = hm[2], hm[3]
    frame["harmony"] = _harmony(st, bar, pattern)
    frame["timeline"] = _timeline(engine, st, bar)
    flats = frame["harmony"]["flats"]

    work, bar_hits = st["work"], st["bar_hits"]
    current = bar_hits[1] if bar_hits and bar_hits[0] == bar else None
    fills_now = bar_hits[2] if bar_hits and bar_hits[0] == bar else frozenset()
    roles = dict(pattern.roles)
    next_roles = queued["pattern"].roles if queued else {}
    params, slots = {}, {}
    for (ch, cc), value in st["cc_values"].items():
        if cc == SAMPLE_SLOT_CC:
            slots[ch + 1] = value
        if cc not in HIDDEN_CCS:
            params.setdefault(ch + 1, []).append({"name": CC_NAMES.get(cc, f"cc {cc}"), "cc": cc, "value": value,
                                                  "max": CC_MAX.get(cc, 127)})
    ramps = {}
    for ramp in st["ramps"]:
        ramps.setdefault(ramp["track"], []).append(ramp)
    in_use = {t for t, bars in work.items() if any(bars)}
    in_use |= {t for t, bars in (queued["pattern"].bars.items() if queued else ()) if any(bars)}
    kit, kit_slots = st.get("kit_tracks") or {}, st.get("kit_slots") or {}
    in_use |= set(kit)  # a labelled track gets a module even while it waits for a written part
    in_use |= st["muted"] | st["hw_muted"] | set(st["drops"]) | set(st["density"]) | set(ramps) | set(params) | set(slots)
    in_use |= {t for ts in st["fills"].values() for t in ts} | set(fills_now)
    in_use |= set(hm[5]) if prog is not None else set()  # a chord track with no line holds a tone per bar
    future_fills = {t for b, ts in st["fills"].items() if b > bar for t in ts}

    for track in sorted(t for t in in_use if 1 <= t <= 16):
        bars = work.get(track, [])
        idx = frame["loop_bar"]
        shift = st["transpose"].get(track, 0)
        follows = prog is not None and track in prog_modes
        if follows:  # the loop shows the next four bars as they will play, each in its own chord
            start = st["pattern_start"]
            bars = [None] * patterns.BARS
            for k in range(patterns.BARS):
                bars[(bar + k - start) % patterns.BARS] = _line(track, work.get(track), bar + k, start, hm)
        steps = _hits(current, track) if current is not None else (
            [[s, eng.clamp_note(n + shift), v, g] for s, n, v, g, _o in bars[idx]] if bars else [])
        notes = {h[1] for b in bars for h in b}
        melodic = bool(notes - {patterns.DRUM}) or follows  # a chord tone can be note 60 too
        written = track in st["parts"]
        # [step, velocity, note, length]: note with the live transpose, length in 16th steps
        loop = [[[h[0], h[2], eng.clamp_note(h[1] + shift), h[3]] for h in b] for b in bars]
        played = [h[2] for b in loop for h in b]
        pitch = None
        if played and (melodic or shift):
            low, high = min(played), max(played)
            pitch = {"low": low, "high": high, "low_name": note_name(low), "high_name": note_name(high)}
        lengths = sorted({h[3] for b in loop for h in b}) if written else []
        drop = st["drops"].get(track)
        lane = {
            "track": track, "role": (kit[track][1] if track in kit else
                                       roles.get(track) or next_roles.get(track) or ("cc only" if not bars else "")),
            "steps": steps, "loop": loop, "melodic": melodic,
            "written": written, "transpose": shift, "pitch": pitch,
            "length": [lengths[0], lengths[-1]] if lengths else None,
            "amp": _amp(track - 1, st["cc_values"]),
            # whiplash_label_tracks: the user's label (role is then that label, not an assumption)
            "kit": {"role": kit[track][0], "label": kit[track][1]} if track in kit else None,
            "slot_label": kit_slots.get(slots.get(track)),
            "muted": track in st["muted"], "hw": track in st["hw_muted"],
            "drop": {"from": drop[0], "back": drop[1]} if drop else None,
            "fill": "now" if track in fills_now else "next" if track in future_fills else None,
            "fill_bars": sorted(b for b, ts in st["fills"].items() if track in ts),
            "density": st["density"].get(track),
            "params": sorted(params.get(track, []), key=lambda p: p["cc"]),
            "ramps": ramps.get(track, []),
            "sample_slot": slots.get(track),
            "harmony": _lane_harmony(track, work.get(track), steps, shift, bar, st, hm, flats) if follows else None,
        }
        for hit in lane["steps"]:
            hit.append(note_name(hit[1]) if lane["melodic"] else "")
        frame["lanes"].append(lane)
    return frame


def _lane_harmony(track, bars, steps, shift, bar, st, hm, flats):
    """What a track following the progression plays: its mode, the notes in this bar's chord, and the
    notes it will play in the next chord (from the bar of the next change)."""
    prog = hm[2]
    names = lambda notes: [harmony.note_label(n, flats) for n in sorted(set(notes), reverse=True)]
    started = bar >= prog.start
    next_at = bar + prog.bars_per_chord - (bar - prog.start) % prog.bars_per_chord if started else prog.start
    upcoming = _line(track, bars, next_at, st["pattern_start"], hm)
    mode = hm[3][track]
    return {"mode": mode, "tag": MODE_TAGS.get(mode, mode.upper()), "active": started,
            "now": names(h[1] for h in steps), "next": names(eng.clamp_note(h[1] + shift) for h in upcoming),
            "next_at": next_at}


# ---- HTTP ------------------------------------------------------------------

class _Handler(BaseHTTPRequestHandler):
    server_version = "Whiplash"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # keep Hermes' terminal clean
        log.debug("whiplash view: " + fmt, *args)

    def _send(self, code, body, ctype):
        data = body.encode() if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        view = self.server.view
        path = self.path.split("?", 1)[0]
        # Only answer requests addressed to this host, so a web page can't reach us via DNS rebinding.
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        if host not in ("127.0.0.1", "localhost"):
            return self._send(403, "forbidden", "text/plain")
        if path in ("/", "/index.html"):
            return self._send(200, view.page(), "text/html; charset=utf-8")
        if path == "/state":
            return self._send(200, json.dumps(view.frame()), "application/json")
        if path == "/chat":
            return self._send(200, json.dumps(view.chat()), "application/json")
        if path == "/events":
            return self._events(view)
        return self._send(404, "not found", "text/plain")

    def _events(self, view):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        self.close_connection = True
        seq, chat_rev, last_state, last_write = -1, -1, None, time.monotonic()
        with view.clients_lock:
            view.clients += 1
        view.wake.set()
        try:
            self.wfile.write(b"retry: 1000\n\n")
            self.wfile.flush()
            while not view.stopping.is_set():
                seq, state, chat_data = view.wait(seq, SSE_PING)
                out = []
                if state is not None and state is not last_state:
                    last_state = state
                    out.append(b"event: state\ndata: " + state + b"\n\n")
                if chat_data is not None and chat_data[0] != chat_rev:
                    chat_rev = chat_data[0]
                    out.append(b"event: chat\ndata: " + chat_data[1] + b"\n\n")
                if not out and time.monotonic() - last_write >= SSE_PING:
                    out.append(b": ping\n\n")
                if out:
                    self.wfile.write(b"".join(out))
                    self.wfile.flush()
                    last_write = time.monotonic()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
            pass
        finally:
            with view.clients_lock:
                view.clients -= 1


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    block_on_close = False


class View:
    """One running view server. Start with View(engine).start(port)."""

    def __init__(self, engine, conversation=None, hooks_active=None, state_db=None):
        self.engine = engine
        self.conv = conversation or chat.CONVERSATION
        self.hooks_active = bool(chat.HOOKS_REGISTERED) if hooks_active is None else hooks_active
        self.tail = None if self.hooks_active else chat.StateDbTail(self.conv, state_db)
        self.stopping = threading.Event()
        self.wake = threading.Event()
        self.clients = 0
        self.clients_lock = threading.Lock()
        self._cond = threading.Condition()
        self._seq = 0
        self._state = None
        self._chat = None
        self.httpd = None
        self.threads = []
        self.url = None
        self._page = None

    # data ------------------------------------------------------------------
    def page(self):
        if self._page is None:
            self._page = PAGE.read_bytes()
        return self._page

    def frame(self):
        frame = snapshot(self.engine)
        frame["log"] = list(ACTIONS)[-12:]
        frame["chat_source"] = "hooks" if self.hooks_active else "sqlite"
        frame["chat_error"] = self.tail.error if self.tail else None
        frame["server_time"] = time.time()
        return frame

    def chat(self):
        out = self.conv.snapshot()
        out["mode"] = "hooks" if self.hooks_active else "sqlite"
        out["error"] = self.tail.error if self.tail else None
        return out

    def wait(self, seq, timeout):
        with self._cond:
            if self._seq == seq and not self.stopping.is_set():
                self._cond.wait(timeout)
            return self._seq, self._state, self._chat

    def _publish(self):
        """Publisher loop: one snapshot per tick for all clients, only while someone watches."""
        last_body, last_sent, last_poll, chat_rev = None, 0.0, 0.0, None
        period = 1.0 / SNAPSHOT_HZ
        while not self.stopping.is_set():
            with self.clients_lock:
                watching = self.clients > 0
            if not watching:
                self.wake.wait(1.0)
                self.wake.clear()
                last_body = None  # a new client gets a fresh frame immediately
                continue
            try:
                now = time.monotonic()
                if self.tail is not None and now - last_poll >= 1.0:
                    last_poll = now
                    self.tail.poll()
                frame = self.frame()
                body = json.dumps(frame, separators=(",", ":"), default=str).encode()
                stable = json.dumps({k: v for k, v in frame.items() if k not in ("pos", "server_time")},
                                    separators=(",", ":"), default=str)
                changed = stable != last_body or frame["playing"] or now - last_sent >= IDLE_HEARTBEAT
                conv = self.conv.snapshot() if self.conv.rev != chat_rev else None
                with self._cond:
                    if changed:
                        self._state = body
                        last_body, last_sent = stable, now
                    if conv is not None:
                        chat_rev = conv["rev"]
                        conv["mode"] = "hooks" if self.hooks_active else "sqlite"
                        conv["error"] = self.tail.error if self.tail else None
                        self._chat = (chat_rev, json.dumps(conv, separators=(",", ":"), default=str).encode())
                    if changed or conv is not None:
                        self._seq += 1
                        self._cond.notify_all()
            except Exception:
                log.exception("whiplash view: snapshot failed")
            self.stopping.wait(period)

    # lifecycle -------------------------------------------------------------
    def start(self, port=None):
        tried = [port] if port else [DEFAULT_PORT, 0]
        error = None
        for candidate in tried:
            try:
                self.httpd = _Server((HOST, candidate), _Handler)
                break
            except OSError as exc:
                error = exc
        if self.httpd is None:
            raise eng.WhiplashError(f"could not open the view on {HOST}:{port}: {error}")
        self.httpd.view = self
        self.url = f"http://{HOST}:{self.httpd.server_address[1]}/"
        for name, target in (("whiplash-view-http", self.httpd.serve_forever), ("whiplash-view", self._publish)):
            thread = threading.Thread(target=target, name=name, daemon=True)
            thread.start()
            self.threads.append(thread)
        return self

    def stop(self):
        self.stopping.set()
        self.wake.set()
        with self._cond:
            self._cond.notify_all()
        if self.httpd is not None:
            try:
                self.httpd.shutdown()
                self.httpd.server_close()
            except Exception:
                log.exception("whiplash view: server close failed")
        for thread in self.threads:
            thread.join(timeout=2.0)


# ---- module-level controls used by the tools ---------------------------------

_lock = threading.Lock()
_current = [None]
_exit_hooked = [False]


def open_browser(url):
    """Open the default browser off-thread. webbrowser may run the OS opener (macOS `open`)."""
    def run():
        try:
            if not webbrowser.open(url, new=2):
                log.info("whiplash view: no browser available; open %s yourself", url)
        except Exception:
            log.exception("whiplash view: opening the browser failed")
    threading.Thread(target=run, name="whiplash-browser", daemon=True).start()


def open_view(engine, port=None, browser=True):
    with _lock:
        view = _current[0]
        already = view is not None
        if not already:
            view = View(engine).start(port)
            _current[0] = view
            if not _exit_hooked[0]:
                atexit.register(close_view)
                _exit_hooked[0] = True
    if browser:
        open_browser(view.url)
    return {"url": view.url, "already_open": already, "browser": "opening" if browser else "not opened",
            "conversation": "live via Hermes hooks" if view.hooks_active else
            f"read-only from {view.tail.path} (no Hermes hooks)"}


def close_view():
    with _lock:
        view, _current[0] = _current[0], None
    if view is None:
        return {"closed": False, "note": "the view was not open"}
    view.stop()
    return {"closed": True, "url": view.url}


def current():
    return _current[0]
