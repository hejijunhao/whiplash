"""Visualiser: state snapshot, action log, conversation hooks, state.db fallback, server lifecycle."""
import http.client
import json
import re
import socket
import sqlite3
import threading
import time

import pytest
import yaml

import whiplash
from whiplash import chat, engine, patterns, tools, view
from test_live import pretend_playing
from test_whiplash import call, make_engine

P = patterns.PATTERNS


@pytest.fixture
def fake():
    eng, port = make_engine()
    yield eng, port
    eng.shutdown()


@pytest.fixture
def server(fake):
    eng, _ = fake
    conv = chat.Conversation()
    v = view.View(eng, conversation=conv, hooks_active=True).start(free_port())
    yield v, eng, conv
    v.stop()


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def get(v, path, host=None):
    port = v.httpd.server_address[1]
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("GET", path, headers={"Host": host or f"127.0.0.1:{port}"})
    resp = conn.getresponse()
    body = resp.read()
    conn.close()
    return resp.status, resp.getheader("Content-Type"), body


def view_threads():
    return [t.name for t in threading.enumerate() if t.name.startswith("whiplash-view")]


# ---- plugin surface ------------------------------------------------------

def test_manifest_declares_view_tools_and_hooks():
    manifest = yaml.safe_load(open(whiplash.__path__[0] + "/plugin.yaml"))
    assert "whiplash_open_view" in manifest["provides_tools"] and "whiplash_close_view" in manifest["provides_tools"]
    assert manifest["provides_hooks"] == list(chat.HOOKS)


def test_register_subscribes_hooks_that_return_none():
    registered = {}

    class Ctx:
        def register_tool(self, name, **kw):
            pass

        def register_hook(self, name, callback):
            registered[name] = callback
    whiplash.register(Ctx())
    try:
        assert list(registered) == yaml.safe_load(open(whiplash.__path__[0] + "/plugin.yaml"))["provides_hooks"]
        # pre_llm_call's return is injected into the prompt and pre_tool_call's can block a tool: both must be None
        assert registered["pre_llm_call"](session_id="x", user_message="hi", conversation_history=[]) is None
        assert registered["pre_tool_call"](tool_name="terminal", args={"cmd": "ls"}) is None
        # garbage never raises into Hermes
        for callback in registered.values():
            assert callback(object(), 1, 2, nonsense=object()) is None
    finally:
        chat.HOOKS_REGISTERED.clear()
        chat.CONVERSATION._reset(None)


def test_register_survives_a_hermes_without_some_hooks():
    class Ctx:
        def register_tool(self, name, **kw):
            pass

        def register_hook(self, name, callback):
            if name.startswith("on_stream"):
                raise ValueError(f"unknown hook {name}")
    try:
        names = chat.register_hooks(Ctx())
        assert "pre_llm_call" in names and not any(n.startswith("on_stream") for n in names)
    finally:
        chat.HOOKS_REGISTERED.clear()


def test_register_without_hook_support_and_no_threads_at_load():
    class Ctx:
        def register_tool(self, name, **kw):
            pass
    whiplash.register(Ctx())
    assert chat.HOOKS_REGISTERED == []
    assert view_threads() == [] and view.current() is None


# ---- snapshot ------------------------------------------------------------

def test_idle_snapshot_shows_port_and_no_lanes(fake):
    eng, _ = fake
    frame = view.snapshot(eng)
    assert frame["playing"] is False and frame["lanes"] == [] and frame["pos"] is None
    assert frame["port"] == {"name": None, "virtual": False, "fallback": False, "lost": None, "error": None}
    json.dumps(frame)


def test_snapshot_lanes_follow_what_the_agent_drives(fake):
    eng, _ = fake
    pretend_playing(eng, P["deephouse"])
    with eng._lock:
        events = eng._bar_boundary(0)
    eng.bar_hits = (0, events, frozenset())
    eng.position = (0, 3, time.perf_counter())
    eng.set_mute(4, True)
    eng.set_param(6, 20, param="filter_freq")
    eng.set_param(11, 90, cc=74)  # a channel outside the pattern gets a lane too
    eng.schedule_drop([1], 2, fill=True)
    eng.mutate_density([5], "thicken")
    frame = view.snapshot(eng)
    lanes = {lane["track"]: lane for lane in frame["lanes"]}
    assert sorted(lanes) == [1, 2, 3, 4, 5, 6, 7, 8, 11]
    assert lanes[1]["role"] == "kick" and [h[0] for h in lanes[1]["steps"]] == [0, 4, 8, 12]
    assert lanes[1]["drop"] == {"from": 1, "back": 3} and lanes[1]["fill"] is None
    assert lanes[2]["fill"] == "next" and lanes[2]["fill_bars"] == [2]
    assert lanes[4]["muted"] and not lanes[4]["hw"]
    assert lanes[5]["density"] == 0.5
    assert lanes[6]["melodic"] and lanes[6]["steps"][0][-1] == view.note_name(lanes[6]["steps"][0][1])
    assert lanes[6]["params"] == [{"name": "filter_freq", "cc": 74, "value": 20, "max": 127}]
    assert frame["transport_mode"] in ("start_stop", "clock_only")
    assert lanes[1]["sample_slot"] is None
    assert lanes[11]["role"] == "cc only" and lanes[11]["steps"] == [] and lanes[11]["params"][0]["value"] == 90
    assert len(lanes[1]["loop"]) == patterns.BARS and lanes[1]["loop"][0][0] == [0, 118]
    assert frame["pos"]["bar"] == 0 and frame["pos"]["step"] == 3 and frame["pos"]["age"] >= 0
    json.dumps(frame)


def test_snapshot_shows_sample_slot_badge_and_clock_only_mode(fake):
    eng, _ = fake
    eng.play(P["techno"], bpm=300, send_transport=False)
    try:
        eng.set_param(3, 12, param="sample_slot")
        frame = view.snapshot(eng)
        lane = {l["track"]: l for l in frame["lanes"]}[3]
        assert frame["transport_mode"] == "clock_only"
        assert lane["sample_slot"] == 12 and all(p["cc"] != view.SAMPLE_SLOT_CC for p in lane["params"])
    finally:
        eng.stop()


def test_snapshot_hides_plumbing_ccs_and_shows_ramps_and_queue(fake):
    eng, _ = fake
    eng.play(P["deephouse"], bpm=300)
    try:
        eng.ramp(6, 110, param="filter_freq", start=20, bars=4)
        eng.set_param(3, 1, param="mute")  # hardware mute CC 94: a badge, not a param bar
        eng.play(P["techno"])  # queued
        frame = view.snapshot(eng)
        lanes = {lane["track"]: lane for lane in frame["lanes"]}
        assert frame["queued"]["pattern"] == "techno" and frame["queued"]["at"] >= 1
        assert lanes[6]["ramps"][0]["param"] == "filter_freq" and lanes[6]["ramps"][0]["to"] == 110
        assert lanes[3]["hw"] and all(p["cc"] != engine.MUTE_CC for p in lanes[3]["params"])
    finally:
        eng.stop()
    frame = view.snapshot(eng)
    assert frame["playing"] is False and frame["lanes"] == []  # stop clears the view
    assert all(p["cc"] != 123 for lane in frame["lanes"] for p in lane["params"])


def test_snapshot_is_read_only_and_never_stalls_the_clock(fake):
    eng, port = fake
    sent = eng.sent_count
    for _ in range(50):
        view.snapshot(eng)
    assert eng.sent_count == sent and port.messages == []  # watching never sends MIDI
    # hammer snapshots from another thread while a 2-bar pattern plays at 300 BPM (1.6 s)
    stop = threading.Event()
    worst = [0.0]

    def hammer():
        while not stop.is_set():
            t = time.perf_counter()
            view.snapshot(eng)
            worst[0] = max(worst[0], time.perf_counter() - t)
    thread = threading.Thread(target=hammer, daemon=True)
    thread.start()
    t0 = time.perf_counter()
    eng.play(P["techno"], bpm=300, bars=2)
    eng._thread.join(timeout=6)
    elapsed = time.perf_counter() - t0
    stop.set()
    thread.join(timeout=2)
    assert not eng.playing()
    assert port.count("clock") == 2 * engine.TICKS_PER_BAR
    assert 1.5 < elapsed < 3.0, elapsed  # 2 bars at 300 BPM = 1.6 s, even under a snapshot flood (CI slack)
    assert worst[0] < 0.25  # a snapshot is a short copy, never a wait on the sequencer


def test_sequencer_publishes_position_and_clears_it(fake):
    eng, _ = fake
    eng.play(P["techno"], bpm=240)
    deadline = time.monotonic() + 3
    while eng.position is None or eng.bar_hits is None:
        assert time.monotonic() < deadline
        time.sleep(0.005)
    bar, step, due = eng.position
    assert bar >= 0 and 0 <= step < patterns.STEPS and due > 0
    assert eng.bar_hits[0] in (eng.bar, eng.bar - 1)  # may cross a bar line between the two reads
    eng.stop()
    assert eng.position is None and eng.bar_hits is None


# ---- action log ------------------------------------------------------------

def test_tool_calls_land_in_the_action_log(tool_engine):
    tool_engine()
    view.ACTIONS.clear()
    call("whiplash_play_pattern", genre="techno")
    call("whiplash_mute_track", track=4)
    call("whiplash_mutate", action="drop", tracks=[1, 2], bars=2)
    call("whiplash_set_tempo", bpm=999)  # rejected
    call("whiplash_stop")
    log = list(view.ACTIONS)
    assert [e["tool"] for e in log] == ["whiplash_play_pattern", "whiplash_mute_track", "whiplash_mutate",
                                        "whiplash_set_tempo", "whiplash_stop"]
    assert log[1]["tracks"] == [4] and log[2]["tracks"] == [1, 2]
    assert log[3]["ok"] is False and log[3]["summary"].startswith("error:")
    assert "techno" in log[0]["summary"]
    assert all(e["id"] > 0 for e in log)


@pytest.fixture
def tool_engine(monkeypatch):
    installed = []

    def install():
        eng, port = make_engine()
        monkeypatch.setattr(tools, "ENGINE", eng)
        installed.append(eng)
        return eng, port
    yield install
    for eng in installed:
        eng.shutdown()


# ---- conversation store ---------------------------------------------------

def test_conversation_streams_and_reconciles_out_of_order_hooks():
    c = chat.Conversation()
    c.user_turn(session_id="s", user_message="play deep house")
    c.tool_start(tool_name="whiplash_play_pattern", args={"genre": "deephouse"}, tool_call_id="c1")
    c.tool_end(tool_name="whiplash_play_pattern", result='{"success": true}', duration_ms=12.4, status="success",
               tool_call_id="c1")
    c.stream_delta(delta="Deep ", turn_id="t", iteration=1)  # a delta can beat its own start
    c.stream_start(turn_id="t", iteration=1)
    c.stream_delta(delta="house ", turn_id="t", iteration=1)
    live = c.snapshot()["turns"][-1]
    assert live["state"] == "running" and live["parts"][-1] == {"kind": "text", "text": "Deep house ", "live": True}
    c.reply(session_id="s", assistant_response="Deep house at 122.")  # post_llm_call before on_stream_end
    c.stream_delta(delta="at ", turn_id="t", iteration=1)
    c.stream_end(final_text="Deep house at 122.", turn_id="t", iteration=1)
    c.stream_delta(delta="late", turn_id="t", iteration=1)  # after end: ignored
    turn = c.snapshot()["turns"][-1]
    texts = [p for p in turn["parts"] if p["kind"] == "text"]
    tools_ = [p for p in turn["parts"] if p["kind"] == "tool"]
    assert turn["state"] == "done" and turn["user"] == "play deep house"
    assert texts == [{"kind": "text", "text": "Deep house at 122.", "live": False}]  # exactly once
    assert tools_[0]["name"] == "whiplash_play_pattern" and tools_[0]["status"] == "done" and tools_[0]["ms"] == 12


def test_conversation_backfills_history_and_resets_on_new_session():
    c = chat.Conversation()
    history = [
        {"role": "system", "content": "you are hermes"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "a", "function": {"name": "whiplash_status", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "a", "content": '{"playing": false}'},
        {"role": "assistant", "content": [{"type": "text", "text": "Nothing playing."}]},
        {"role": "user", "content": "play techno"},
    ]
    c.user_turn(session_id="s1", user_message="play techno", conversation_history=history)
    turns = c.snapshot()["turns"]
    assert [t["user"] for t in turns] == ["hi", "play techno"]  # the current message isn't duplicated
    assert turns[0]["parts"][0]["name"] == "whiplash_status" and turns[0]["parts"][0]["result"] == '{"playing": false}'
    assert turns[0]["parts"][1]["text"] == "Nothing playing."
    c.user_turn(session_id="s1", user_message="faster")
    assert c.snapshot()["turns"][-2]["state"] == "interrupted"  # never got a post_llm_call
    c.user_turn(session_id="s2", user_message="new chat")
    assert [t["user"] for t in c.snapshot()["turns"]] == ["new chat"]


def test_subagents_are_ignored_and_compression_keeps_the_conversation():
    c = chat.Conversation()
    c.user_turn(session_id="main", user_message="research some grooves", parent_session_id="")
    c.tool_start(tool_name="delegate_task", args={}, session_id="main")
    # a subagent starts its own conversation under the main session
    c.user_turn(session_id="child", user_message="subagent prompt", parent_session_id="main", is_first_turn=True)
    c.tool_start(tool_name="web_search", args={}, session_id="child")
    c.stream_delta(delta="child text", turn_id="ct", iteration=1, session_id="child")
    c.reply(session_id="child", assistant_response="child reply")
    snap = c.snapshot()
    assert snap["session"] == "main" and [t["user"] for t in snap["turns"]] == ["research some grooves"]
    assert [p["name"] for p in snap["turns"][0]["parts"]] == ["delegate_task"] and snap["turns"][0]["state"] == "running"
    # compression rotates the session id but continues the same conversation
    c.reply(session_id="main", assistant_response="done")
    c.user_turn(session_id="main-2", user_message="next", parent_session_id="main", is_first_turn=False,
                conversation_history=[{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}])
    assert [t["user"] for t in c.snapshot()["turns"]] == ["research some grooves", "next"]
    # a genuinely new chat clears the panel
    c.user_turn(session_id="fresh", user_message="hello again", parent_session_id="")
    assert [t["user"] for t in c.snapshot()["turns"]] == ["hello again"]


def test_conversation_is_bounded():
    c = chat.Conversation()
    for i in range(chat.MAX_TURNS + 25):
        c.user_turn(session_id="s", user_message=f"m{i}")
    c.stream_delta(delta="x" * (chat.MAX_TEXT + 500), turn_id="t", iteration=0)
    turns = c.snapshot()["turns"]
    assert len(turns) == chat.MAX_TURNS and turns[0]["user"] == "m25"
    assert len(turns[-1]["parts"][0]["text"]) <= chat.MAX_TEXT
    c.tool_end(tool_name="read_file", result="y" * 5000)
    assert len(c.snapshot()["turns"][-1]["parts"][-1]["result"]) <= chat.MAX_TOOL_TEXT


# ---- state.db fallback -------------------------------------------------------

def make_db(path, rows, columns="session_id, role, content, tool_calls, tool_name, timestamp"):
    with sqlite3.connect(path) as db:
        db.execute(f"CREATE TABLE messages ({columns})")
        db.executemany(f"INSERT INTO messages ({columns}) VALUES ({', '.join('?' * len(columns.split(',')))})", rows)


def test_state_db_tail_reads_newest_session_read_only(tmp_path):
    path = tmp_path / "state.db"
    make_db(path, [
        ("old", "user", "yesterday", None, None, 1.0),
        ("new", "user", "play breaks", None, None, 10.0),
        ("new", "assistant", "", json.dumps([{"id": "1", "function": {"name": "whiplash_play_pattern", "arguments": '{"genre":"breaks"}'}}]), None, 11.0),
        ("new", "tool", '{"success": true}', None, "whiplash_play_pattern", 12.0),
        ("new", "assistant", "Breaks at 132.", None, None, 13.0),
    ])
    before = path.read_bytes()
    conv = chat.Conversation()
    tail = chat.StateDbTail(conv, path)
    assert tail.poll() is True and tail.error is None
    snap = conv.snapshot()
    assert snap["session"] == "new" and snap["source"] == "sqlite"
    turn = snap["turns"][0]
    assert turn["user"] == "play breaks" and turn["state"] == "done"
    assert turn["parts"][0]["name"] == "whiplash_play_pattern" and turn["parts"][0]["result"] == '{"success": true}'
    assert turn["parts"][-1]["text"] == "Breaks at 132."
    assert tail.poll() is False  # unchanged: no rebuild
    assert path.read_bytes() == before
    with sqlite3.connect(path) as db:
        db.execute("INSERT INTO messages VALUES ('new', 'user', 'faster', NULL, NULL, 20.0)")
    assert tail.poll() is True
    assert conv.snapshot()["turns"][-1]["state"] == "running"


def test_state_db_tail_missing_or_foreign_schema(tmp_path):
    conv = chat.Conversation()
    missing = chat.StateDbTail(conv, tmp_path / "nope.db")
    assert missing.poll() is False and "not found" in missing.error
    assert not (tmp_path / "nope.db").exists()  # read-only: never creates the file
    path = tmp_path / "other.db"
    make_db(path, [("s", "hi")], columns="session_id, body")
    odd = chat.StateDbTail(conv, path)
    assert odd.poll() is False and "lacks" in odd.error


def test_state_db_path_honours_hermes_home(monkeypatch, tmp_path):
    monkeypatch.setenv("HERMES_HOME", str(tmp_path))
    assert chat.state_db_path() == tmp_path / "state.db"


# ---- server ------------------------------------------------------------------

def test_server_serves_page_state_and_refuses_foreign_hosts(server):
    v, eng, conv = server
    assert v.url.startswith("http://127.0.0.1:")
    status, ctype, body = get(v, "/")
    assert status == 200 and ctype.startswith("text/html") and b"<title>Whiplash Live</title>" in body
    status, _, body = get(v, "/state")
    frame = json.loads(body)
    assert status == 200 and frame["playing"] is False and frame["chat_source"] == "hooks"
    assert get(v, "/state", host="evil.example:80")[0] == 403  # DNS-rebinding guard
    assert get(v, "/nope")[0] == 404
    assert v.httpd.server_address[0] == "127.0.0.1"


def test_page_is_self_contained():
    html = view.PAGE.read_text()
    assert "<script src" not in html and "<link" not in html and "@import" not in html  # no network, no build step
    for label in ("MIDI FALLBACK", "AUDIO", "getUserMedia", "echoCancellation: false", "EventSource"):
        assert label in html
    # no fonts, CDNs or any other URL: the only one is the SVG namespace name, which is never fetched
    urls = set(re.findall(r"(?:https?:)?//[\w.-]+\.[a-z]{2,}[^\s\"')]*", html))
    assert urls <= {"http://www.w3.org/2000/svg"}, urls
    assert "url(" not in html and "@font-face" not in html and "fetch(" not in html


def test_page_palette_is_strict_grayscale():
    html = view.PAGE.read_text()
    colours = re.findall(r"#([0-9A-Fa-f]{6}|[0-9A-Fa-f]{3})\b", html)
    assert colours, "palette tokens missing"
    for c in colours:
        c = c if len(c) == 6 else "".join(ch * 2 for ch in c)
        assert c[0:2].lower() == c[2:4].lower() == c[4:6].lower(), f"#{c} is not gray"
    for r, g, b in re.findall(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", html):
        assert r == g == b, (r, g, b)
    for token in ("#171717", "#333333", "#808080", "#F0F0F0"):  # the brief's bg, panel, mid and highlight
        assert token in html


def test_page_reads_only_fields_the_snapshot_has(fake):
    """Every S.x / lane.x / port.x the page reads exists in a real frame, so motion follows real state."""
    eng, _ = fake
    pretend_playing(eng, P["deephouse"])
    with eng._lock:
        events = eng._bar_boundary(0)
    eng.bar_hits = (0, events, frozenset())
    eng.position = (0, 3, time.perf_counter())
    eng.set_param(6, 20, param="filter_freq")
    eng.schedule_drop([1], 2, fill=True)
    v = view.View(eng, conversation=chat.Conversation(), hooks_active=True)
    frame = v.frame()
    html = view.PAGE.read_text()
    script = html[html.index("<script>"):]
    used = set(re.findall(r"\bS\.(\w+)", script))
    assert {"playing", "bpm", "bar", "loop_bar", "lanes", "pos", "port", "queued", "swing", "messages_sent"} <= used
    assert used <= set(frame), used - set(frame)
    lane_keys = set().union(*(set(lane) for lane in frame["lanes"]))
    lane_used = set(re.findall(r"\blane\.(\w+)", script))
    assert {"steps", "loop", "muted", "drop", "fill", "params", "ramps", "melodic", "role", "track"} <= lane_used
    assert lane_used <= lane_keys, lane_used - lane_keys
    assert set(re.findall(r"\bport\.(\w+)", script)) <= set(frame["port"])
    assert set(re.findall(r"\bS\.queued\.(\w+)", script)) <= {"pattern", "bpm", "at"}
    assert set(re.findall(r"\bS\.pos\.(\w+)", script)) <= set(frame["pos"])
    six = {lane["track"]: lane for lane in frame["lanes"]}[6]
    assert six["params"][0]["max"] == 127  # knob travel comes from ccmap, not a guess in the page
    assert set(re.findall(r"\bp\.(name|cc|value|max)\b", script)) <= set(six["params"][0])
    ramp_used = set(re.findall(r"\b(?:r|c\.ramp|lv\.ramp)\.(\w+)", script)) - {"_t0"}
    eng.ramp(6, 110, param="filter_freq", start=20, bars=4)
    ramp = view.snapshot(eng)["lanes"]
    ramp = next(l for l in ramp if l["track"] == 6)["ramps"][0]
    assert ramp_used <= set(ramp), ramp_used - set(ramp)


def test_snapshot_param_max_follows_ccmap(fake):
    eng, _ = fake
    pretend_playing(eng, P["deephouse"])
    eng.set_param(3, 100, param="loop_pos")
    eng.set_param(3, 50, param="filter_key_tracking")
    lane = {l["track"]: l for l in view.snapshot(eng)["lanes"]}[3]
    assert {p["name"]: p["max"] for p in lane["params"]} == {"loop_pos": 120, "filter_key_tracking": 100}


def test_events_stream_state_and_chat(server):
    v, eng, conv = server
    conv.user_turn(session_id="s", user_message="hello from the test")
    port = v.httpd.server_address[1]
    sock = socket.create_connection(("127.0.0.1", port), timeout=5)
    sock.sendall(f"GET /events HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n\r\n".encode())
    data = b""
    deadline = time.monotonic() + 5
    while (b"event: state" not in data or b"hello from the test" not in data) and time.monotonic() < deadline:
        data += sock.recv(65536)
    assert b"text/event-stream" in data and b"event: state" in data and b"event: chat" in data
    assert b"hello from the test" in data
    conv.user_turn(session_id="s", user_message="second message")
    while b"second message" not in data and time.monotonic() < deadline + 3:
        data += sock.recv(65536)
    assert b"second message" in data
    sock.close()


def test_publisher_idles_without_viewers(fake):
    eng, _ = fake
    calls = []
    original = eng.view_state
    eng.view_state = lambda: calls.append(1) or original()
    v = view.View(eng, conversation=chat.Conversation(), hooks_active=True).start(free_port())
    try:
        time.sleep(0.4)
        assert calls == []  # nobody watching: no snapshots taken
    finally:
        v.stop()


def test_stop_releases_port_and_threads(fake):
    eng, _ = fake
    port = free_port()
    v = view.View(eng, conversation=chat.Conversation(), hooks_active=True).start(port)
    assert get(v, "/state")[0] == 200
    v.stop()
    assert not any(t.is_alive() for t in v.threads)
    with pytest.raises(OSError):
        socket.create_connection(("127.0.0.1", port), timeout=1).close()


def test_sqlite_mode_when_hooks_are_missing(fake, tmp_path):
    eng, _ = fake
    make_db(tmp_path / "state.db", [("s", "user", "from the db", None, None, 1.0)])
    v = view.View(eng, conversation=chat.Conversation(), hooks_active=False, state_db=tmp_path / "state.db")
    v.start(free_port())
    try:
        v.tail.poll()
        status, _, body = get(v, "/chat")
        out = json.loads(body)
        assert out["mode"] == "sqlite" and out["turns"][0]["user"] == "from the db"
    finally:
        v.stop()


# ---- tools ---------------------------------------------------------------------

def test_open_and_close_view_tools(tool_engine, monkeypatch):
    tool_engine()
    opened = []
    monkeypatch.setattr(view, "open_browser", opened.append)
    monkeypatch.setattr(view.atexit, "register", lambda fn: fn)
    port = free_port()
    try:
        out = call("whiplash_open_view", port=port)
        assert out["success"] and out["url"] == f"http://127.0.0.1:{port}/" and out["already_open"] is False
        assert opened == [out["url"]]
        again = call("whiplash_open_view", open_browser=False)
        assert again["already_open"] is True and again["url"] == out["url"] and opened == [out["url"]]
        assert view_threads()
    finally:
        closed = call("whiplash_close_view")
    assert closed["success"] and closed["closed"] is True
    assert call("whiplash_close_view")["closed"] is False
    assert view.current() is None


def test_open_view_rejects_bad_ports(tool_engine):
    tool_engine()
    out = call("whiplash_open_view", port=80, open_browser=False)
    assert out["success"] is False and "port" in out["error"]
    assert view.current() is None


def test_open_view_reports_a_port_in_use(tool_engine):
    tool_engine()
    with socket.socket() as busy:
        busy.bind(("127.0.0.1", 0))
        busy.listen()
        out = call("whiplash_open_view", port=busy.getsockname()[1], open_browser=False)
    assert out["success"] is False and "could not open the view" in out["error"]
    assert view.current() is None
