"""The app over real HTTP with a fake chat: golden 1 end to end, the daily cap, the no-outside-request
proofs, and one memory per browser, deleted 24 hours after its cookie was issued."""
import hashlib
import json
import re
import socketserver
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from app import guard, server
from life import llm
from life.constants import LIGHTNING, SUPER
from life.store import Store
from life.types import Fact

STATIC = Path(__file__).parent.parent / "app" / "static"
EXAMPLES = Path(__file__).parent.parent / "app" / "examples"
RUN = Path(__file__).parent.parent / "results" / "measured-run"  # docs/reports/09-measured-run
GOLDEN = json.loads((Path(__file__).parent / "golden" / "bike_leg.json").read_text())
USAGE = {"prompt_tokens": 1000, "completion_tokens": 100}
PREMISE = {"assumptions": [{"assumption": "I can bike tomorrow", "verdict": "OUTDATED", "fact_id": "s0f0",
                            "reason": "a cast stops cycling"}]}


def fake_chat(model, messages, json_mode=False, think=False, max_tokens=4000):
    """Hand-written replies for golden 1, chosen by model and by what the prompt contains."""
    prompt = messages[-1]["content"]
    if model == LIGHTNING:
        fact = ("commute", "bikes 10 miles to work daily") if "bike 10 miles" in prompt else (
            "health", "leg in a cast for six weeks")
        return json.dumps({"facts": [{"subject": "user", "attribute": fact[0], "value": fact[1]}]}), USAGE
    if "OLD facts:" in prompt:  # S6
        return json.dumps([{"old_id": "s0f0", "verdict": "stale", "by": "s1f0",
                            "reason": "a cast on the leg stops cycling"}]), USAGE
    if think:
        return json.dumps(PREMISE), USAGE
    return "You said on 2026-03-22 your leg is in a cast, so no biking.", USAGE


class Client:
    """One browser: keeps the visitor cookie the server issues, as a browser would."""
    def __init__(self, base, cookie=None):
        self.base, self.cookie = base, cookie

    def other(self):
        return Client(self.base)

    def call(self, path, body=None):
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.base + path, data=data, method="GET" if body is None else "POST")
        if self.cookie:
            req.add_header("Cookie", self.cookie)
        try:
            with urllib.request.urlopen(req) as r:
                out = r.status, dict(r.headers), r.read().decode()
        except urllib.error.HTTPError as e:
            out = e.code, dict(e.headers), e.read().decode()
        if "Set-Cookie" in out[1]:
            self.cookie = out[1]["Set-Cookie"].split(";")[0]
        return out

    @property
    def vid(self):
        return self.cookie.removeprefix("visitor=")

    def json(self, path, body=None):
        status, _, text = self.call(path, body)
        return status, json.loads(text)


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.delenv("SPEND_URL", raising=False)  # the file ledger, unless a test names a Key Value store
    started = []

    def start(chat=fake_chat):
        httpd = server.serve(str(tmp_path), 0, chat)
        # a 10 ms poll: shutdown() waits one poll interval, and the default 0.5 s made this file take 14 s
        threading.Thread(target=httpd.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()
        started.append(httpd)
        return Client(f"http://127.0.0.1:{httpd.server_address[1]}")

    yield start
    for httpd in started:
        httpd.shutdown()
        httpd.server_close()


def spend(tmp_path):
    """The shared spend file every visitor's requests are counted in."""
    return guard.Sqlite(tmp_path / "spend.db")


def sessions():
    return [{"time": s["time"], "text": s["turns"][0]["content"]} for s in GOLDEN["sessions"]]


def test_golden1_end_to_end_shows_the_stale_banner(app):
    c = app()
    assert c.json("/ingest", {"sessions": sessions()}) == (200, {"ingested": 2})
    status, out = c.json("/ask", {"question": GOLDEN["question"]})
    assert status == 200
    assert out["premise_report"]["stale"] == [{"premise": "I can bike tomorrow", "fact_id": "s0f0",
                                               "invalidated_by": "s1f0", "reason": "a cast stops cycling"}]
    assert "2026-03-22" in out["text"]
    _, facts = c.json("/timeline")
    by_id = {f["id"]: f for f in facts}
    assert by_id["s0f0"]["status"] == "stale" and by_id["s0f0"]["invalidated_by"] == "s1f0"
    assert "cast" in by_id["s1f0"]["value"] and by_id["s1f0"]["status"] == "active"
    assert by_id["s0f0"]["reason"] == "a cast on the leg stops cycling"


def test_ingest_in_two_calls_gives_distinct_ids(app):
    c = app()
    first, second = sessions()
    c.json("/ingest", {"sessions": [first]})
    c.json("/ingest", {"sessions": [second]})
    _, facts = c.json("/timeline")
    assert [f["id"] for f in facts] == ["s0f0", "s1f0"]
    assert facts[0]["status"] == "stale"


def test_ingest_sorts_a_batch_by_date(app):
    c = app()
    c.json("/ingest", {"sessions": sessions()[::-1]})
    _, facts = c.json("/timeline")
    assert [f["time"] for f in facts] == ["2026-03-01 08:30", "2026-03-22 19:05"]
    assert [f["id"] for f in facts] == ["s0f0", "s1f0"] and facts[0]["status"] == "stale"


def test_ingest_refuses_a_session_older_than_the_latest_fact(app):
    c = app()
    c.json("/ingest", {"sessions": [sessions()[1]]})
    status, out = c.json("/ingest", {"sessions": [sessions()[0]]})
    assert status == 400 and "date order" in out["error"]
    assert len(c.json("/timeline")[1]) == 1


@pytest.mark.parametrize("body", [None, [], {}, {"sessions": []}, {"sessions": [{"time": "2026-03-01", "text": "x"}]},
                                  {"sessions": [{"time": "2026-03-01 08:30", "text": "  "}]},
                                  {"sessions": [{"time": "2026-03-01 08:30"}]}, {"sessions": ["x"]}])
def test_ingest_rejects_bad_bodies(app, body):
    assert app().json("/ingest", body if body is not None else [])[0] == 400


@pytest.mark.parametrize("body", [{}, {"question": ""}, {"question": 5}, []])
def test_ask_rejects_bad_bodies(app, body):
    assert app().json("/ask", body)[0] == 400


def test_non_json_body_is_400(app):
    c = app()
    req = urllib.request.Request(c.base + "/ask", data=b"not json", method="POST")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code == 400


def test_oversized_body_is_413(app, monkeypatch):
    monkeypatch.setattr(server, "MAX_BODY", 100)
    c = app()
    assert c.json("/ask", {"question": "x" * 101})[0] == 413
    assert c.json("/ask", {"question": "x" * 50})[0] == 200


def test_unknown_route_is_404(app):
    c = app()
    assert c.call("/nope")[0] == 404
    assert c.call("/nope", {})[0] == 404


def test_export_returns_every_fact_and_delete_all_empties(app):
    c = app()
    c.json("/ingest", {"sessions": sessions()})
    status, _, text = c.call("/export")
    assert status == 200 and [f["id"] for f in json.loads(text)] == ["s0f0", "s1f0"]
    assert c.json("/delete-all", {}) == (200, {"deleted": True})
    assert c.json("/timeline") == (200, [])


def test_a_failing_model_call_is_a_502_with_a_message(app):
    def broken(*a, **k):
        raise OSError("network down")
    status, out = app(broken).json("/ingest", {"sessions": sessions()[:1]})
    assert status == 502 and "network down" in out["error"]


def test_spend_is_recorded_from_ingest_and_ask(app, tmp_path):
    c = app()
    c.json("/ingest", {"sessions": sessions()})
    c.json("/ask", {"question": GOLDEN["question"]})
    # ingest: 2 Lightning calls (1000 x 0.06 + 100 x 0.24) + 1 Super S6 call (1000 x 0.30 + 100 x 0.90);
    # ask: Answer.cost_usd = check + answer, 2 Super calls (1000 x 0.30 + 100 x 0.90) = 0.00078
    expected = 2 * 0.000084 + 0.00039 + 0.00078
    assert spend(tmp_path).spent_today(server.today()) == pytest.approx(expected)


def test_a_reply_cut_off_at_max_tokens_is_still_charged_to_the_day(app, tmp_path):
    def cut_s6(model, messages, **kw):
        if "OLD facts:" in messages[-1]["content"]:
            raise llm.Truncated(model, USAGE)  # refused, so nothing goes stale, but billed
        return fake_chat(model, messages, **kw)
    app(cut_s6).json("/ingest", {"sessions": sessions()})
    # 2 Lightning calls (1000 x 0.06 + 100 x 0.24) + the cut-off Super S6 call (1000 x 0.30 + 100 x 0.90)
    assert spend(tmp_path).spent_today(server.today()) == pytest.approx(2 * 0.000084 + 0.00039)


def test_over_the_cap_ingest_and_ask_are_429_and_call_no_model(app, tmp_path):
    calls = []

    def counting(*a, **k):
        calls.append(a)
        return fake_chat(*a, **k)
    c = app(counting)
    spend(tmp_path).record(server.today(), 0.80)
    status, out = c.json("/ingest", {"sessions": sessions()})
    assert status == 429 and "daily budget" in out["error"]
    assert c.json("/ask", {"question": "q"})[0] == 429
    assert calls == []


def test_ask_estimate_counts_the_memory(app, tmp_path):
    c = app()
    c.json("/timeline")
    Store(str(tmp_path / "visitors" / f"{c.vid}.db")).put(Fact("big", "user", "notes", "x" * 40000,
                                                               "2026-01-01 00:00", 0))
    spend(tmp_path).record(server.today(), 0.785)
    # "q" alone estimates 0.012 (0.797 in all, allowed); the 40000-character memory adds 0.010 (0.807, denied)
    assert c.json("/ask", {"question": "q"})[0] == 429
    assert c.other().json("/ask", {"question": "q"})[0] == 200  # another visitor's memory is not counted


def test_delete_all_does_not_reset_the_day_spend(app, tmp_path):
    c = app()
    spend(tmp_path).record(server.today(), 0.80)
    c.json("/delete-all", {})
    assert c.json("/ask", {"question": "q"})[0] == 429


def test_guard_allows_up_to_the_cap_and_denies_past_it():
    assert guard.budget_guard(0.55, 0.25) == (True, "")  # 0.80 exactly, as a float, is allowed
    allowed, message = guard.budget_guard(0.55, 0.26)
    assert not allowed and "$0.80" in message


def test_estimate_is_hand_derived():
    # 4000 chars = 1000 tokens at $1.00/M, plus 4000 output tokens at $3.00/M = 0.013
    assert guard.estimate("x" * 4000) == pytest.approx(0.013)


class FakeValkey(socketserver.ThreadingTCPServer):
    """The three commands the ledger sends, over RESP, as Valkey answers them; `sent` keeps every command."""
    daemon_threads = True

    def __init__(self):
        self.data, self.sent = {}, []
        super().__init__(("127.0.0.1", 0), ValkeyHandler)
        threading.Thread(target=self.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True).start()

    @property
    def url(self):
        return f"redis://127.0.0.1:{self.server_address[1]}"


class ValkeyHandler(socketserver.StreamRequestHandler):
    def handle(self):
        n = int(self.rfile.readline()[1:])
        words = [self.rfile.read(int(self.rfile.readline()[1:]) + 2)[:-2].decode() for _ in range(n)]
        self.server.sent.append(words)
        op, key, *rest = words
        if op == "INCRBYFLOAT":
            self.server.data[key] = repr(float(self.server.data.get(key, 0)) + float(rest[0]))
            reply = self.server.data[key].encode()
        elif op == "GET":
            reply = self.server.data[key].encode() if key in self.server.data else None
        else:
            self.wfile.write(b":1\r\n")
            return
        self.wfile.write(b"$-1\r\n" if reply is None else b"$%d\r\n%s\r\n" % (len(reply), reply))


@pytest.mark.parametrize("make", [lambda tmp, url: guard.Sqlite(tmp / "spend.db"), lambda tmp, url: guard.Valkey(url)],
                         ids=["file", "key-value"])
def test_each_ledger_counts_only_that_day_and_outlives_a_restart(make, tmp_path):
    store = FakeValkey()
    first = make(tmp_path, store.url)
    first.record("2026-10-27", 0.5)
    first.record("2026-10-28", 0.25)
    first.record("2026-10-28", 0.125)
    again = make(tmp_path, store.url)  # what a restarted instance opens
    assert again.spent_today("2026-10-28") == 0.375
    assert again.spent_today("2026-10-29") == 0
    store.shutdown()


def test_key_value_spend_expires_three_days_after_its_last_record():
    store = FakeValkey()
    guard.Valkey(store.url).record("2026-10-28", 0.5)
    assert store.sent == [["INCRBYFLOAT", "spend:2026-10-28", "0.5"], ["EXPIRE", "spend:2026-10-28", "259200"]]
    store.shutdown()


def test_the_app_counts_in_key_value_when_spend_url_names_one_so_a_restart_keeps_the_cap(app, tmp_path, monkeypatch):
    store = FakeValkey()
    monkeypatch.setenv("SPEND_URL", store.url)
    c = app()
    c.json("/ingest", {"sessions": sessions()})
    assert float(store.data[f"spend:{server.today()}"]) == pytest.approx(2 * 0.000084 + 0.00039)
    assert not (tmp_path / "spend.db").exists()
    store.data[f"spend:{server.today()}"] = "0.80"
    assert app().json("/ask", {"question": "q"})[0] == 429  # a new instance, same store: still over the cap
    store.shutdown()


def test_an_unreachable_key_value_refuses_paid_work(app, monkeypatch):
    calls = []

    def counting(*a, **k):
        calls.append(a)
        return fake_chat(*a, **k)
    with socketserver.TCPServer(("127.0.0.1", 0), socketserver.BaseRequestHandler) as closed:
        port = closed.server_address[1]
    monkeypatch.setenv("SPEND_URL", f"redis://127.0.0.1:{port}")
    c = app(counting)
    assert c.json("/ingest", {"sessions": sessions()})[0] == 429
    assert c.json("/ask", {"question": "q"})[0] == 429
    assert calls == []
    assert guard.Valkey(f"redis://127.0.0.1:{port}").record(server.today(), 0.1) is None  # a paid call: no crash


def test_every_response_carries_the_csp_header(app):
    c = app()
    for path in ("/", "/app.js", "/app.css", "/timeline", "/nope"):
        assert c.call(path)[1]["Content-Security-Policy"] == "default-src 'self'", path


def test_every_data_response_forbids_caching(app):
    c = app()
    c.json("/ingest", {"sessions": sessions()})
    for path, body in (("/timeline", None), ("/activity", None), ("/export", None), ("/nope", None),
                       ("/ask", {"question": "q"}), ("/example", {"name": "travel"}), ("/delete-all", {})):
        assert c.call(path, body)[1]["Cache-Control"] == "no-store", path


def test_page_serves_each_static_file_with_its_type(app):
    c = app()
    assert c.call("/")[1]["Content-Type"].startswith("text/html")
    assert c.call("/app.js")[1]["Content-Type"].startswith("text/javascript")
    assert c.call("/app.css")[1]["Content-Type"].startswith("text/css")
    assert c.call("/scene.js")[1]["Content-Type"].startswith("text/javascript")
    assert c.call("/vendor/three.module.min.js")[1]["Content-Type"].startswith("text/javascript")
    assert c.call("/")[2] == (STATIC / "index.html").read_text()


def test_a_query_string_still_reaches_its_route(app):
    c = app()
    assert c.call("/?ref=devpost")[:3:2] == (200, (STATIC / "index.html").read_text())
    assert c.json("/timeline?x=1") == (200, [])


def test_static_files_name_no_outside_url():
    """Our own files: no URL at all. The vendored three.js is not ours to edit; it is pinned by its hash below, and the
    CSP (default-src 'self') is what stops any request at runtime."""
    files = [f for f in STATIC.iterdir() if f.is_file()]
    assert {f.name for f in files} == {"index.html", "app.js", "app.css", "scene.js"}
    for f in files:
        assert not re.search(r"(?:https?:)?//", f.read_text()), f.name


def test_vendored_three_is_the_pinned_release():
    # sha256 of build/three.module.min.js in the npm package three@0.170.0 (MIT; app/static/vendor/LICENSE)
    data = (STATIC / "vendor" / "three.module.min.js").read_bytes()
    assert hashlib.sha256(data).hexdigest() == "08fd7545d13d2c7fb65ab691530a802dafefd638596501854f267d0fb13c39e7"


def test_page_states_what_leaves_the_device_and_orders_the_premise_report_first():
    html = (STATIC / "index.html").read_text()
    assert ("Your sessions and questions are sent to NVIDIA Nemotron models on Nebius Token Factory to be read and "
            "answered. Your memory is kept on this server apart from every other visitor's, found by one cookie, "
            "and deleted 24 hours after your first visit; Export and Delete everything are below.") in html
    assert html.index('id="report"') < html.index('id="answer-text"')
    assert "invalidated by" in (STATIC / "app.js").read_text()


def test_each_browser_sees_only_its_own_memory(app, tmp_path):
    a = app()
    a.json("/ingest", {"sessions": sessions()})
    b = a.other()
    assert b.json("/timeline") == (200, [])
    assert b.call("/export")[2] == "[]"
    assert b.json("/ask", {"question": GOLDEN["question"]})[1]["premise_report"]["stale"] == []
    b.json("/delete-all", {})
    assert [f["id"] for f in a.json("/timeline")[1]] == ["s0f0", "s1f0"]
    assert a.vid != b.vid
    assert sorted(p.name for p in (tmp_path / "visitors").iterdir()) == sorted([f"{a.vid}.db", f"{b.vid}.db"])


def test_the_visitor_cookie_is_issued_once_http_only_strict_and_secure(app):
    c = app()
    assert "Set-Cookie" not in c.call("/")[1]  # the page itself needs no cookie
    headers = c.call("/timeline")[1]
    assert re.fullmatch(r"visitor=\d{10}-[A-Za-z0-9_-]{22}; Max-Age=86400; Path=/; HttpOnly; SameSite=Strict; Secure",
                        headers["Set-Cookie"])
    assert abs(int(c.vid[:10]) - time.time()) < 60
    assert "Set-Cookie" not in c.call("/timeline")[1]


NOW = 2_000_000_000  # a fixed clock for visitor(): ids are "<issued>-<22-character token>"


@pytest.mark.parametrize("cookie, expected", [
    (f"visitor={NOW - 60}-{'a' * 22}", f"{NOW - 60}-{'a' * 22}"),
    (f"theme=dark; visitor={NOW - 60}-{'a' * 22}", f"{NOW - 60}-{'a' * 22}"),
    (f"visitor={NOW - 86399}-{'a' * 22}", f"{NOW - 86399}-{'a' * 22}"),  # 1 s before the 24 h mark: still yours
    (f"visitor={NOW - 86400}-{'a' * 22}", None),  # 24 h after it was issued: expired
    (f"visitor={NOW + 1}-{'a' * 22}", None),  # issued in the future: forged
    (f"visitor={NOW - 60}-{'a' * 21}", None),
    (f"visitor={NOW - 60}-{'a' * 22}x", None),
    ("visitor=../../spend", None),
    (f"xvisitor={NOW - 60}-{'a' * 22}", None),
    ("", None),
])
def test_visitor_accepts_only_an_id_this_server_could_have_issued_in_the_last_24_hours(cookie, expected):
    assert server.visitor(cookie, NOW) == expected


def test_a_forged_cookie_gets_a_new_id_and_an_empty_memory(app, tmp_path):
    a = app()
    a.json("/ingest", {"sessions": sessions()})
    forged = Client(a.base, "visitor=../" + a.vid)
    assert forged.json("/timeline") == (200, [])
    assert forged.vid != a.vid and len(a.json("/timeline")[1]) == 2


def test_memory_is_deleted_24_hours_after_its_cookie_was_issued(app, tmp_path):
    c = app()
    now = int(time.time())
    old = tmp_path / "visitors" / f"{now - 86400 - 60}-{'a' * 22}.db"
    fresh = tmp_path / "visitors" / f"{now - 86400 + 60}-{'b' * 22}.db"
    foreign = tmp_path / "visitors" / "notes.db"  # not a name this server writes: left alone, and no crash
    old.write_bytes(b""), fresh.write_bytes(b""), foreign.write_bytes(b"")
    assert c.json("/timeline")[0] == 200
    assert not old.exists() and fresh.exists() and foreign.exists()
    assert (tmp_path / "spend.db").exists()


SUPER_ID = "nemotron-3-super-120b-a12b"


def test_ingest_activity_names_each_step_in_words_for_this_visitor_only(app):
    c = app()
    c.json("/ingest", {"sessions": sessions()})
    _, events = c.json("/activity")
    # session 1 has nothing older to judge, so S6 asks no model; session 2's cast makes the commute stale
    assert [(e["step"], e["text"]) for e in events] == [
        ("S4", "Nemotron-3_5-Lightning replied"),
        ("S4", "Extracted 'commute: bikes 10 miles to work daily'"),
        ("S5", "Related older facts: 0"),
        ("S6", "Nothing older to judge; no model asked"),
        ("Store", "Stored: 1 new, 0 marked stale"),
        ("S4", "Nemotron-3_5-Lightning replied"),
        ("S4", "Extracted 'health: leg in a cast for six weeks'"),
        ("S5", "Related older facts: 1"),
        ("S6", f"{SUPER_ID} replied"),
        ("S6", "Marked 'commute: bikes 10 miles to work daily' stale, "
               "because of 'health: leg in a cast for six weeks'"),
        ("Store", "Stored: 1 new, 1 marked stale")]
    # each call is 1000 + 100 tokens: Lightning 1000 x 0.06 + 100 x 0.24 = $0.000084, Super 1000 x 0.30 + 100 x 0.90
    calls = [(e["call"]["model"], e["call"]["tokens"], e["call"]["usd"]) for e in events if e["call"]]
    assert calls == [(LIGHTNING, 1100, pytest.approx(0.000084)), (LIGHTNING, 1100, pytest.approx(0.000084)),
                     (SUPER, 1100, pytest.approx(0.00039))]
    assert all(e["call"]["seconds"] >= 0 for e in events if e["call"])
    # the facts each step touched, for the scene: S4 the new fact and its attribute, S5 the older ones it found,
    # S6 the stale fact then the fact that replaced it
    assert [(e["step"], e["ids"], e["labels"]) for e in events if e["ids"]] == [
        ("S4", ["s0f0"], ["commute"]), ("S4", ["s1f0"], ["health"]), ("S5", ["s0f0"], []),
        ("S6", ["s0f0", "s1f0"], [])]
    assert c.other().json("/activity") == (200, [])


def test_ask_activity_logs_the_premise_check_then_the_answer(app):
    c = app()
    c.json("/ingest", {"sessions": sessions()})
    before = len(c.json("/activity")[1])
    c.json("/ask", {"question": GOLDEN["question"]})
    events = c.json("/activity")[1][before:]
    assert [(e["step"], e["text"]) for e in events] == [
        ("S8", f"{SUPER_ID} replied"), ("S8", "Assumptions found: 1, outdated: 1"), ("S9", f"{SUPER_ID} replied")]
    assert events[1]["ids"] == ["s0f0"]  # the stale fact the outdated assumption rests on


def test_delete_all_clears_the_activity(app):
    c = app()
    c.json("/ingest", {"sessions": sessions()[:1]})
    assert len(c.json("/activity")[1]) == 5
    c.json("/delete-all", {})
    assert c.json("/activity") == (200, [])


def test_activity_does_not_wait_for_the_visitors_running_request(app):
    reached, release = threading.Event(), threading.Event()

    def slow_s6(model, messages, **kw):
        if "OLD facts:" in messages[-1]["content"]:
            reached.set()
            release.wait(10)
        return fake_chat(model, messages, **kw)
    c = app(slow_s6)
    c.json("/ingest", {"sessions": sessions()[:1]})  # the cookie first, so both threads are one visitor
    adding = threading.Thread(target=c.json, args=("/ingest", {"sessions": sessions()[1:]}))
    adding.start()
    try:
        assert reached.wait(10)
        req = urllib.request.Request(c.base + "/activity", headers={"Cookie": c.cookie})
        with urllib.request.urlopen(req, timeout=5) as r:  # behind the visitor's lock, this waits for S6: a timeout
            steps = [e["step"] for e in json.loads(r.read())]
    finally:
        release.set()
        adding.join()
    assert steps[5:] == ["S4", "S4", "S5"]  # session 2 is in S6, under the lock


def test_activity_is_dropped_with_the_memory_24_hours_after_its_cookie_was_issued(tmp_path):
    a = server.App(str(tmp_path))
    old, fresh = f"{NOW - 86400}-{'a' * 22}", f"{NOW - 86399}-{'b' * 22}"
    for vid in (old, fresh):
        (tmp_path / "visitors" / f"{vid}.db").write_bytes(b"")
        a.activity[vid].append({"text": "x"})
    a.sweep(NOW)
    assert list(a.activity) == [fresh]


def test_activity_keeps_the_newest_200_events_per_visitor(tmp_path):
    events = server.App(str(tmp_path)).activity["v"]
    server.CURRENT.events = events
    try:
        for n in range(201):
            server.LOG.info("event %d", n, extra={"step": "S4"})
    finally:
        del server.CURRENT.events
    assert len(events) == 200 and events[0]["text"] == "event 1" and events[-1]["text"] == "event 200"


def refuse(model, messages, **kw):
    raise AssertionError("a long example must load with no model call")


def test_a_long_example_replaces_this_visitors_memory_with_no_model_call(app, tmp_path):
    c = app(refuse)
    c.call("/timeline")
    Store(str(tmp_path / "visitors" / f"{c.vid}.db")).put(Fact("mine", "user", "job", "nurse", "2026-01-01 09:00", 0))
    status, out = c.json("/example", {"name": "subscription"})
    assert status == 200
    assert (out["loaded"], out["sessions"], out["chars"]) == (464, 50, 714110)  # what seed.py printed, 29 Oct
    assert out["question"].startswith("I just got an alert that my main design subscription is set to auto-renew")
    assert out["flat"]["correct"] is False and out["flat"]["answer"].startswith("Yes, that sounds like a solid plan")
    assert out["ours"]["correct"] is True
    assert out["ours"]["answer"]["text"].startswith("You're actually working offline now")
    assert {s["fact_id"] for s in out["ours"]["answer"]["premise_report"]["stale"]} == {"s0f2"}
    _, facts = c.json("/timeline")
    by_id = {f["id"]: f for f in facts}
    assert (len(facts), sum(f["status"] == "stale" for f in facts)) == (464, 18)
    assert "mine" not in by_id
    assert by_id["s0f2"]["status"] == "stale" and "internet" in by_id[by_id["s0f2"]["invalidated_by"]]["value"]
    assert [e["text"] for e in c.json("/activity")[1]] == [
        "Loaded 464 facts from 50 sessions, built earlier by this pipeline: no model call"]
    assert c.other().json("/timeline") == (200, [])
    assert spend(tmp_path).spent_today(server.today()) == 0


@pytest.mark.parametrize("body", ["travel", {}, {"name": "nope"}, {"name": "../spend"}, {"name": ["travel"]}])
def test_an_example_is_named_never_a_path(app, body):
    c = app()
    c.json("/ingest", {"sessions": sessions()})
    status, out = c.json("/example", body)
    assert status == 400 and out["error"].endswith("one of: snorkel, subscription, travel.")
    assert len(c.json("/timeline")[1]) == 2


def run_rows(condition: str) -> list[dict]:
    return [json.loads(r) for r in (RUN / f"{condition}-n6-seed11-all.jsonl").open()]


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.json")), ids=lambda p: p.stem)
def test_each_long_example_is_a_whole_stale_life_with_both_recorded_answers(path):
    seed = json.loads(path.read_text())
    facts = {f["id"]: Fact(**f) for f in seed["facts"]}
    assert len(facts) == len(seed["facts"])
    assert all(f.invalidated_by in facts for f in facts.values() if f.status == "stale")
    assert seed["source"].startswith("STALE scenario ") and seed["sessions"] == 50
    uid = seed["source"].split()[2]
    flat, ours = (next(r for r in run_rows(c) if (r["uid"], r["dim"]) == (uid, "dim3_query"))
                  for c in ("baseline", "ours"))
    assert seed["flat"] == {"answer": flat["response"], "correct": False} and flat["correct"] is False
    assert seed["ours"]["answer"]["text"] == ours["response"] and seed["ours"]["correct"] is ours["correct"] is True
    assert all(facts[s["fact_id"]].status == "stale" for s in seed["ours"]["answer"]["premise_report"]["stale"])


def test_the_page_offers_exactly_the_shipped_examples():
    assert set(re.findall(r"seed: '(\w+)'", (STATIC / "app.js").read_text())) == set(server.EXAMPLES) == {
        "snorkel", "subscription", "travel"}


def run_cells(condition: str) -> list[int]:
    """Correct answers per STALE cell (T1 SR, PR, IPA, T2 SR, PR, IPA), counted from the run's own rows."""
    rows = run_rows(condition)
    return [sum(r["correct"] for r in rows if (r["type"], r["dim"]) == (t, d))
            for t in ("T1", "T2") for d in ("dim1_query", "dim2_query", "dim3_query")]


def test_the_page_states_the_measured_run():
    html = (STATIC / "index.html").read_text()
    ours, flat = run_cells("ours"), run_cells("baseline")
    for name, cells in (("ours", ours), ("flat", flat)):
        row = "".join(f"<td>{c}/6</td>" for c in cells) + f"<td>{sum(cells)}/36</td>"
        assert f'<tr data-row="{name}">' in html and row in html.split(f'<tr data-row="{name}">')[1].split("</tr>")[0]
    assert f'<b data-stat="ours">{sum(ours)}/36</b>' in html and f'<b data-stat="flat">{sum(flat)}/36</b>' in html
    assert f'<b data-stat="pr">{ours[1] + ours[4]}/12</b>' in html and f"against {flat[1] + flat[4]}/12" in html


def test_the_page_shows_both_recorded_answers_and_says_they_are_recorded():
    html, js = (STATIC / "index.html").read_text(), (STATIC / "app.js").read_text()
    assert html.index('id="compare"') < html.index('id="timeline"')
    assert ("Both answers were recorded in our STALE benchmark run and marked by the same judge: Nemotron 3 Ultra "
            "with STALE's own prompt.") in html
    assert "showAnswer(x.ours.answer, $('ours-report'), $('ours-text'))" in js
    assert "$('flat-text').textContent = x.flat.answer;" in js


def test_the_page_states_the_codes_own_limits():
    """How it works quotes each step's output cap; each must be the one in the code."""
    html = (STATIC / "index.html").read_text()
    code = {"memory": (Path(__file__).parent.parent / "life" / "memory.py").read_text(),
            "query": (Path(__file__).parent.parent / "life" / "query.py").read_text()}
    for step, module, cap in (("S4", "memory", 1500), ("S6", "memory", 12000), ("S8", "query", 8000),
                              ("S9", "query", 2000)):
        assert f"max_tokens={cap}" in code[module]
        assert html.count(f'data-cap="{step}"') == 1
        assert f"{cap:,} output tokens" in html.split(f'data-cap="{step}"')[1][:400]
