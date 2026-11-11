"""The live Hermes conversation for the visualiser's agent overlay.

Two sources, both read-only and in memory only (nothing is written to disk):

1. Hermes plugin hooks (preferred). register() subscribes the callbacks in HOOKS. Every
   callback copies a few fields into CONVERSATION under its own small lock and returns None:
   no I/O, no engine locks, never raises (a returned value from pre_llm_call would be injected
   into the prompt, and pre_tool_call could block a tool, so returning None matters).
   Replies stream word by word through on_stream_start / on_stream_delta / on_stream_end.
2. ~/.hermes/state.db (fallback, when this Hermes has no register_hook). The view server
   polls it once a second through a read-only SQLite URI and rebuilds the newest session.

Hermes delivers stream hooks on one worker thread per callback, so start/delta/end can arrive
in any order relative to each other and to post_llm_call. Parts are keyed by
(turn_id, iteration) and the final reply is reconciled when the turn is serialised.

Sessions: only pre_llm_call decides which conversation is shown. A subagent's first turn
(parent_session_id == the shown session, no history) is remembered as a child and all of its
events are ignored. A new session id that continues the shown one (context compression) is
adopted without clearing; any other new session (e.g. /new) clears the panel.
"""
import json
import logging
import os
import sqlite3
import threading
import time
from collections import deque
from pathlib import Path

log = logging.getLogger("whiplash")

MAX_TURNS = 60
MAX_TEXT = 20_000
MAX_TOOL_TEXT = 600
SQLITE_TAIL = 400  # newest rows read per poll


def _clip(text, limit):
    text = "" if text is None else str(text)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _text(content):
    """Plain text from a message's content: str, list of parts, or a JSON string of parts."""
    if content is None:
        return ""
    if isinstance(content, str):
        stripped = content.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            try:
                return _text(json.loads(stripped))
            except ValueError:
                pass
        return content
    if isinstance(content, (list, tuple)):
        out = []
        for part in content:
            if isinstance(part, str):
                out.append(part)
            elif isinstance(part, dict):
                if part.get("type") in (None, "text", "input_text", "output_text") and part.get("text"):
                    out.append(str(part["text"]))
                elif part.get("type") in ("image", "image_url", "input_image"):
                    out.append("[image]")
        return "\n".join(out)
    if isinstance(content, dict):
        return str(content.get("text") or content.get("content") or "")
    return str(content)


def _args(args):
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except ValueError:
            return _clip(args, MAX_TOOL_TEXT)
    try:
        return _clip(json.dumps(args, separators=(",", ":"), default=str), MAX_TOOL_TEXT)
    except (TypeError, ValueError):
        return _clip(args, MAX_TOOL_TEXT)


def _tool_calls(raw):
    """[(id, name, args)] from an OpenAI-style tool_calls list (or its JSON string)."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    out = []
    for call in raw or []:
        if not isinstance(call, dict):
            continue
        fn = call.get("function") if isinstance(call.get("function"), dict) else call
        name = fn.get("name") or call.get("name")
        if name:
            out.append((call.get("id"), str(name), _args(fn.get("arguments", fn.get("args", {})))))
    return out


class Conversation:
    def __init__(self):
        self._lock = threading.Lock()
        self.rev = 0
        self.source = None  # "hooks" or "sqlite" once something arrived
        self.session_id = None
        self._turns = deque(maxlen=MAX_TURNS)
        self._seq = 0
        self._parts = {}  # (turn_id, iteration) -> text part being streamed
        self._children = set()  # subagent session ids: never shown

    # ---- internals (caller holds _lock) ----------------------------------
    def _bump(self, source):
        self.rev += 1
        self.source = source

    def _new_turn(self, user="", state="running", turn_id=None, ts=None):
        self._seq += 1
        turn = {"id": self._seq, "user": _clip(user, MAX_TEXT), "ts": ts or time.time(), "state": state,
                "parts": [], "final": None, "turn_id": turn_id, "error": None}
        self._turns.append(turn)
        return turn

    def _current(self, turn_id=None):
        if turn_id is not None:
            for turn in reversed(self._turns):
                if turn["turn_id"] == turn_id:
                    return turn
        if self._turns:
            turn = self._turns[-1]
            if turn_id is not None and turn["turn_id"] is None:
                turn["turn_id"] = turn_id
            return turn
        return self._new_turn(turn_id=turn_id)

    def _reset(self, session_id):
        self.session_id = session_id
        self._turns.clear()
        self._parts.clear()

    def _accept(self, session_id):
        """For every hook but pre_llm_call: False for a subagent's events, else adopt the id."""
        if session_id and session_id in self._children:
            return False
        if session_id and self.session_id is None:
            self.session_id = session_id
        elif session_id and session_id != self.session_id:
            self.session_id = session_id  # e.g. compression rotated the id mid-turn: same conversation
        return True

    def _load_messages(self, messages):
        """Append turns rebuilt from an OpenAI-format message list (history or state.db rows)."""
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            if role == "user":
                self._new_turn(_text(msg.get("content")), state="done", ts=msg.get("timestamp"))
            elif role == "assistant":
                turn = self._turns[-1] if self._turns else self._new_turn(state="done")
                text = _text(msg.get("content")).strip()
                if text:
                    turn["parts"].append({"kind": "text", "text": _clip(text, MAX_TEXT), "live": False})
                for call_id, name, args in _tool_calls(msg.get("tool_calls")):
                    turn["parts"].append({"kind": "tool", "name": name, "args": args, "result": None,
                                          "status": "called", "ms": None, "live": False, "call_id": call_id})
            elif role == "tool":
                if not self._turns:
                    continue
                turn = self._turns[-1]
                part = self._find_tool(turn, msg.get("tool_call_id"), msg.get("tool_name") or msg.get("name"))
                result = _clip(_text(msg.get("content")), MAX_TOOL_TEXT)
                if part is None:
                    turn["parts"].append({"kind": "tool", "name": str(msg.get("tool_name") or msg.get("name") or "tool"),
                                          "args": "", "result": result, "status": "done", "ms": None,
                                          "live": False, "call_id": msg.get("tool_call_id")})
                else:
                    part.update(result=result, status="done")

    @staticmethod
    def _find_tool(turn, call_id, name, live_only=False):
        for part in reversed(turn["parts"]):
            if part["kind"] != "tool" or (live_only and not part["live"]):
                continue
            if call_id and part.get("call_id") == call_id:
                return part
            if not call_id and name and part["name"] == name and (part["result"] is None):
                return part
        return None

    # ---- hook entry points -----------------------------------------------
    def user_turn(self, session_id=None, user_message=None, conversation_history=None, turn_id=None,
                  parent_session_id=None, is_first_turn=None, **_):
        with self._lock:
            if session_id and session_id in self._children:
                return
            history = list(conversation_history or [])
            first = is_first_turn if is_first_turn is not None else not any(
                isinstance(m, dict) and m.get("role") == "assistant" for m in history)
            if parent_session_id and self.session_id and parent_session_id == self.session_id and session_id \
                    and session_id != self.session_id and first:
                self._children.add(session_id)  # a subagent working for the shown conversation
                return
            fresh = not self._turns
            if session_id and session_id != self.session_id:
                if self.session_id is not None and parent_session_id == self.session_id:
                    self.session_id = session_id  # continuation (compression): keep what's shown
                else:
                    self._reset(session_id)
                    fresh = True
            text = _clip(_text(user_message), MAX_TEXT)
            if fresh and history:
                last = history[-1] if history else None
                if isinstance(last, dict) and last.get("role") == "user" and _text(last.get("content")).strip() == text.strip():
                    history = history[:-1]  # the history may already hold this turn's message
                self._load_messages(history)
            for turn in self._turns:
                if turn["state"] == "running":
                    turn["state"] = "interrupted"
                    for part in turn["parts"]:
                        part["live"] = False
            self._new_turn(text, turn_id=turn_id)
            self._bump("hooks")

    def stream_start(self, turn_id=None, iteration=None, session_id=None, **_):
        with self._lock:
            if not self._accept(session_id):
                return
            self._stream_part(turn_id, iteration)
            self._bump("hooks")

    def _stream_part(self, turn_id, iteration):
        key = (turn_id, iteration)
        part = self._parts.get(key)
        if part is None:
            turn = self._current(turn_id)
            part = {"kind": "text", "text": "", "live": True, "key": key}
            turn["parts"].append(part)
            self._parts[key] = part
            if len(self._parts) > 4 * MAX_TURNS:
                for old in list(self._parts)[: len(self._parts) - 2 * MAX_TURNS]:
                    del self._parts[old]
        return part

    def stream_delta(self, delta=None, kind="text", turn_id=None, iteration=None, session_id=None, **_):
        if kind not in (None, "text") or not delta:
            return
        with self._lock:
            if not self._accept(session_id):
                return
            part = self._stream_part(turn_id, iteration)
            if part["live"] and len(part["text"]) < MAX_TEXT:
                part["text"] = _clip(part["text"] + str(delta), MAX_TEXT)
                self._bump("hooks")

    def stream_end(self, final_text=None, finished=True, error=None, turn_id=None, iteration=None,
                   session_id=None, **_):
        with self._lock:
            if not self._accept(session_id):
                return
            part = self._stream_part(turn_id, iteration)
            if final_text:
                part["text"] = _clip(final_text, MAX_TEXT)
            part["live"] = False
            if error:
                self._current(turn_id)["error"] = _clip(error, 300)
            self._bump("hooks")

    def tool_start(self, tool_name=None, args=None, tool_call_id=None, turn_id=None, session_id=None, **_):
        with self._lock:
            if not self._accept(session_id):
                return
            turn = self._current(turn_id)
            turn["parts"].append({"kind": "tool", "name": str(tool_name or "tool"), "args": _args(args or {}),
                                  "result": None, "status": "running", "ms": None, "live": True,
                                  "call_id": tool_call_id})
            self._bump("hooks")

    def tool_end(self, tool_name=None, args=None, result=None, duration_ms=None, status=None, tool_call_id=None,
                 turn_id=None, session_id=None, error_message=None, **_):
        with self._lock:
            if not self._accept(session_id):
                return
            turn = self._current(turn_id)
            part = self._find_tool(turn, tool_call_id, tool_name, live_only=True)
            if part is None:
                part = {"kind": "tool", "name": str(tool_name or "tool"), "args": _args(args or {}), "call_id": tool_call_id}
                turn["parts"].append(part)
            ok = status in (None, "success", "ok", "done")
            part.update(result=_clip(error_message if (not ok and error_message) else _text(result), MAX_TOOL_TEXT),
                        status="done" if ok else "error", live=False,
                        ms=round(duration_ms) if isinstance(duration_ms, (int, float)) else None)
            self._bump("hooks")

    def reply(self, session_id=None, user_message=None, assistant_response=None, turn_id=None, **_):
        with self._lock:
            if not self._accept(session_id):
                return
            turn = self._current(turn_id)
            if not turn["user"] and user_message:
                turn["user"] = _clip(_text(user_message), MAX_TEXT)
            turn["final"] = _clip(_text(assistant_response), MAX_TEXT) or None
            turn["state"] = "done"
            for part in turn["parts"]:
                if part["kind"] == "tool":
                    part["live"] = False
            self._bump("hooks")

    # ---- fallback: state.db --------------------------------------------------
    def load_rows(self, session_id, rows):
        """Replace the store with a session rebuilt from state.db rows (oldest first)."""
        with self._lock:
            self._reset(session_id)
            self._children.clear()
            self._load_messages(rows)
            if self._turns:
                last = self._turns[-1]
                if not any(p["kind"] == "text" for p in last["parts"]):
                    last["state"] = "running"  # no reply yet: Hermes is still on it
            self._bump("sqlite")

    # ---- output ----------------------------------------------------------
    def snapshot(self):
        with self._lock:
            return {"rev": self.rev, "source": self.source, "session": self.session_id,
                    "turns": [self._serialise(t) for t in self._turns]}

    @staticmethod
    def _serialise(turn):
        parts, final = [], (turn["final"] or "").strip()
        for part in turn["parts"]:
            if part["kind"] == "text":
                text = part["text"].strip()
                if not text:
                    continue
                if final and (text == final or (part["live"] and final.startswith(text))):
                    continue  # the final reply below supersedes this streamed copy
                parts.append({"kind": "text", "text": part["text"], "live": part["live"]})
            else:
                parts.append({k: part.get(k) for k in ("kind", "name", "args", "result", "status", "ms", "live")})
        if final:
            # place the final reply after the last tool call, where the streamed copy would sit
            parts.append({"kind": "text", "text": turn["final"], "live": False})
        return {"id": turn["id"], "user": turn["user"], "ts": turn["ts"], "state": turn["state"],
                "error": turn["error"], "parts": parts}


CONVERSATION = Conversation()


def _guard(fn):
    """Hook wrapper: never raise into Hermes, always return None."""
    def hook(*args, **kwargs):
        try:
            fn(*args, **kwargs)
        except Exception:
            log.debug("whiplash chat hook %s failed", fn.__name__, exc_info=True)
        return None
    hook.__name__ = f"whiplash_{fn.__name__}"
    return hook


def make_hooks(conv):
    return {
        "pre_llm_call": _guard(conv.user_turn),
        "on_stream_start": _guard(conv.stream_start),
        "on_stream_delta": _guard(conv.stream_delta),
        "on_stream_end": _guard(conv.stream_end),
        "pre_tool_call": _guard(conv.tool_start),
        "post_tool_call": _guard(conv.tool_end),
        "post_llm_call": _guard(conv.reply),
    }


HOOKS = make_hooks(CONVERSATION)
HOOKS_REGISTERED = []  # hook names Hermes accepted; empty means the state.db fallback is used


def register_hooks(ctx):
    """Subscribe the conversation hooks if this Hermes supports them. Never raises."""
    HOOKS_REGISTERED.clear()
    register = getattr(ctx, "register_hook", None)
    if not callable(register):
        return []
    for name, callback in HOOKS.items():
        try:
            register(name, callback)
            HOOKS_REGISTERED.append(name)
        except Exception as exc:  # an older Hermes may not know a hook name
            log.info("whiplash: hook %s not available (%s)", name, exc)
    return list(HOOKS_REGISTERED)


# ---- state.db reader -------------------------------------------------------

def state_db_path():
    home = os.environ.get("HERMES_HOME")
    return Path(home).expanduser() / "state.db" if home else Path.home() / ".hermes" / "state.db"


class StateDbTail:
    """Polls the newest session from Hermes' state.db, read-only. Used only without hooks."""

    def __init__(self, conv, path=None):
        self.conv = conv
        self.path = Path(path) if path else state_db_path()
        self._seen = None
        self.error = None

    def poll(self):
        """Refresh the conversation if the newest session changed. Returns True on change. Never raises."""
        if not self.path.exists():
            self.error = f"{self.path} not found"
            return False
        try:
            uri = f"file:{self.path}?mode=ro"
            with sqlite3.connect(uri, uri=True, timeout=0.5) as db:
                cols = {row[1] for row in db.execute("PRAGMA table_info(messages)")}
                needed = {"session_id", "role", "content", "timestamp"}
                if not needed <= cols:
                    self.error = f"state.db messages table lacks {sorted(needed - cols)}"
                    return False
                extra = [c for c in ("tool_calls", "tool_name", "tool_call_id") if c in cols]
                row = db.execute("SELECT session_id FROM messages ORDER BY timestamp DESC LIMIT 1").fetchone()
                if row is None:
                    self.error = None
                    return False
                session = row[0]
                marker = db.execute("SELECT COUNT(*), MAX(timestamp) FROM messages WHERE session_id = ?",
                                    (session,)).fetchone()
                if (session, *marker) == self._seen:
                    return False
                select = ", ".join(["role", "content", "timestamp", *extra])
                rows = db.execute(f"SELECT {select} FROM messages WHERE session_id = ? "
                                  f"ORDER BY timestamp DESC, rowid DESC LIMIT {SQLITE_TAIL}", (session,)).fetchall()
            names = ["role", "content", "timestamp", *extra]
            messages = [dict(zip(names, r)) for r in reversed(rows)]
            for msg in messages:
                if not isinstance(msg.get("timestamp"), (int, float)):
                    msg.pop("timestamp", None)
            self.conv.load_rows(session, messages)
            self._seen = (session, *marker)
            self.error = None
            return True
        except Exception as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            return False
