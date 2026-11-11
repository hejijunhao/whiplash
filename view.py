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

from . import ccmap, chat, patterns
from . import engine as eng

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
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
LOG_SIZE = 40

ACTIONS = deque(maxlen=LOG_SIZE)  # recent Whiplash tool calls, appended by tools._tool
_action_ids = itertools.count(1)  # next() is atomic under the GIL: tools may run in parallel


def note_name(note):
    return f"{NOTE_NAMES[note % 12]}{note // 12 - 1}"


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
    except Exception:
        log.debug("whiplash view: action log failed", exc_info=True)


# ---- snapshot --------------------------------------------------------------

def _hits(bar_hits, track):
    return [[s, n, v, g] for s in sorted(bar_hits) for (t, n, v, g, _o) in bar_hits[s] if t == track]


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
        "transport_mode": st.get("transport_mode"),
    }
    position = st["position"]
    if playing and position:
        p_bar, p_step, due = position
        frame["pos"] = {"bar": p_bar, "step": p_step, "age": round(now - due, 4)}
    if not playing or pattern is None:
        return frame

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
    in_use |= st["muted"] | st["hw_muted"] | set(st["drops"]) | set(st["density"]) | set(ramps) | set(params) | set(slots)
    in_use |= {t for ts in st["fills"].values() for t in ts} | set(fills_now)
    future_fills = {t for b, ts in st["fills"].items() if b > bar for t in ts}

    for track in sorted(t for t in in_use if 1 <= t <= 16):
        bars = work.get(track, [])
        idx = frame["loop_bar"]
        steps = _hits(current, track) if current is not None else (
            [[s, n, v, g] for s, n, v, g, _o in bars[idx]] if bars else [])
        loop = [[[h[0], h[2]] for h in b] for b in bars]
        notes = {h[1] for b in bars for h in b}
        drop = st["drops"].get(track)
        lane = {
            "track": track, "role": roles.get(track) or next_roles.get(track) or ("cc only" if not bars else ""),
            "steps": steps, "loop": loop, "melodic": bool(notes - {patterns.DRUM}),
            "muted": track in st["muted"], "hw": track in st["hw_muted"],
            "drop": {"from": drop[0], "back": drop[1]} if drop else None,
            "fill": "now" if track in fills_now else "next" if track in future_fills else None,
            "fill_bars": sorted(b for b, ts in st["fills"].items() if track in ts),
            "density": st["density"].get(track),
            "params": sorted(params.get(track, []), key=lambda p: p["cc"]),
            "ramps": ramps.get(track, []),
            "sample_slot": slots.get(track),
        }
        for hit in lane["steps"]:
            hit.append(note_name(hit[1]) if lane["melodic"] else "")
        frame["lanes"].append(lane)
    return frame


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
