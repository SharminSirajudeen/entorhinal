"""One small standard-library HTTP server and one static page. Each browser has its own memory file, found by a random
cookie and deleted KEEP_SECONDS after the cookie was issued; the day's spend is one ledger shared by every visitor
(app/guard.py: Render Key Value when SPEND_URL is set, else a file).
Each browser also has an activity log in memory only (GET /activity), filled from the "life" logger while its request
runs, for the page's live pipeline view. python -m app.server --port 7860 --dir memories"""
import argparse
import json
import logging
import os
import re
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import asdict
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from app import guard
from life import llm, memory, query
from life.store import Store
from life.types import Fact, Session

STATIC = Path(__file__).parent / "static"
# the long examples, by name: a request names one, never a path (docs/reports/09-measured-run/seed.py built them)
EXAMPLES = {p.stem: p for p in (Path(__file__).parent / "examples").glob("*.json")}
PAGES = {"/": "index.html", "/app.js": "app.js", "/app.css": "app.css", "/scene.js": "scene.js",
         "/vendor/three.module.min.js": "vendor/three.module.min.js"}
TYPES = {".html": "text/html", ".js": "text/javascript", ".css": "text/css"}
CSP = "default-src 'self'"
MAX_BODY = 1_000_000
TIME = re.compile(r"\d{4}-\d\d-\d\d \d\d:\d\d")
KEEP_SECONDS = 24 * 3600  # a visitor's memory is deleted this long after their cookie was issued
# the id is "<unix time issued>-<secrets.token_urlsafe(16)>": the time drives the deletion, the token is the secret
VISITOR = re.compile(r"(?:^|;)\s*visitor=((\d{10})-[A-Za-z0-9_-]{22})\s*(?:;|$)")
EVENTS_KEPT = 200  # the newest activity events kept per visitor, in memory only
CURRENT = threading.local()  # .events: the activity of the visitor whose request this thread is serving
LOG = logging.getLogger("life")


class Activity(logging.Handler):
    """Each "life" record, as an event {t, step, text, call, ids, labels} in the activity of the visitor this thread
    serves; `ids` names the facts the step touched, so the page's scene can move exactly those."""

    def emit(self, record):
        events = getattr(CURRENT, "events", None)
        if events is not None:
            events.append({"t": record.created, "step": getattr(record, "step", ""), "text": record.getMessage(),
                           "call": getattr(record, "call", None), "ids": getattr(record, "ids", []),
                           "labels": getattr(record, "labels", [])})


LOG.addHandler(Activity())
LOG.setLevel(logging.INFO)


def logged(chat, off: str, on: str):
    """chat, logging each call's model, seconds, tokens and price under step `on` with thinking, else `off`. Spend is
    recorded elsewhere, once."""
    def call(model, messages, **kw):
        start = time.monotonic()
        text, usage = chat(model, messages, **kw)
        tokens = usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)
        LOG.info("%s replied", model.split("/")[-1], extra={"step": on if kw.get("think") else off, "call": {
            "model": model, "seconds": time.monotonic() - start, "tokens": tokens, "usd": llm.price(model, usage)}})
        return text, usage
    return call


def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def bad(message: str) -> tuple[int, dict]:
    return 400, {"error": message}


def valid_sessions(rows) -> bool:
    return isinstance(rows, list) and bool(rows) and all(
        isinstance(r, dict) and isinstance(r.get("time"), str) and TIME.fullmatch(r["time"])
        and isinstance(r.get("text"), str) and r["text"].strip() for r in rows)


def visitor(cookie: str, now: float) -> str | None:
    """The id in a browser's Cookie header, if it is one this server issued and it has not expired."""
    m = VISITOR.search(cookie)
    return m[1] if m and now - KEEP_SECONDS < int(m[2]) <= now else None


class App:
    def __init__(self, folder: str, chat=llm.chat):
        self.visitors, self.chat = Path(folder) / "visitors", chat
        self.visitors.mkdir(parents=True, exist_ok=True)
        self.spend = guard.ledger(folder, os.environ.get("SPEND_URL"))
        self.locks = defaultdict(threading.Lock)  # one small lock per visitor id, kept until restart
        self.activity = defaultdict(lambda: deque(maxlen=EVENTS_KEPT))  # dropped with the visitor's memory file

    def store(self, visitor_id: str) -> Store:
        return Store(str(self.visitors / f"{visitor_id}.db"))

    def sweep(self, now: float) -> None:
        """Delete every visitor's memory whose cookie was issued KEEP_SECONDS ago or more. O(visitor files). Ten-digit
        times compare correctly as strings, and a name that is not one of ours compares without raising."""
        cutoff = str(int(now - KEEP_SECONDS))
        for p in self.visitors.glob("*.db"):
            if p.name[:10] <= cutoff:
                p.unlink(missing_ok=True)
                self.activity.pop(p.stem, None)

    def metered(self, model, messages, **kw):
        """chat, logged as S4 or S6, with each call's price added to today's spend, a reply cut off at max_tokens
        included."""
        return llm.billed(logged(self.chat, "S4", "S6"), lambda usd: self.spend.record(today(), usd), model,
                          messages, **kw)

    def denied(self, text: str):
        allowed, message = guard.budget_guard(self.spend.spent_today(today()), guard.estimate(text))
        return None if allowed else (429, {"error": message})

    def ingest(self, store, body):
        rows = body.get("sessions") if isinstance(body, dict) else None
        if not valid_sessions(rows):
            return bad('Send {"sessions": [{"time": "YYYY-MM-DD HH:MM", "text": "..."}]}.')
        rows = sorted(rows, key=lambda r: r["time"])
        held = store.timeline()
        if held and rows[0]["time"] < max(f.time for f in held):
            return bad("Sessions must be added in date order: an earlier one than your latest cannot be added.")
        first = max((f.source_idx for f in held), default=-1) + 1
        for n, r in enumerate(rows):
            if denial := self.denied(r["text"]):
                return denial
            session = Session(first + n, r["time"], [{"role": "user", "content": r["text"]}])
            memory.ingest(store, session, self.metered)
        return 200, {"ingested": len(rows)}

    def ask(self, store, body):
        question = body.get("question") if isinstance(body, dict) else None
        if not isinstance(question, str) or not question.strip():
            return bad('Send {"question": "..."}.')
        if denial := self.denied(query.memory_text(store) + question):
            return denial
        out = query.answer(store, question, logged(self.chat, "S9", "S8"))
        self.spend.record(today(), out.cost_usd)
        return 200, asdict(out)

    def delete_all(self, store, _):
        CURRENT.events.clear()  # the activity names the visitor's facts too
        store.delete_all()
        return 200, {"deleted": True}

    def example(self, store, body):
        """Replace this visitor's memory with a long example: a whole STALE life this pipeline built in the measured
        run, loaded from its file with no model call. Returns the counts, the question, and both answers the run
        recorded to it."""
        name = body.get("name") if isinstance(body, dict) else None
        if not isinstance(name, str) or name not in EXAMPLES:
            return bad(f'Send {{"name": ...}}, one of: {", ".join(sorted(EXAMPLES))}.')
        seed = json.loads(EXAMPLES[name].read_text())
        facts = [Fact(**f) for f in seed.pop("facts")]
        self.delete_all(store, body)
        store.put(*facts)
        LOG.info("Loaded %d facts from %d sessions, built earlier by this pipeline: no model call", len(facts),
                 seed["sessions"], extra={"step": "Store"})
        return 200, {"loaded": len(facts), **seed}

    def timeline(self, store, _):
        return 200, [asdict(f) for f in store.timeline()]

    def export(self, store, _):
        return 200, store.export_json()


class Handler(BaseHTTPRequestHandler):
    app: App  # set per server by serve()
    issued = None  # a new visitor id, sent back as a cookie with this response

    def reply(self, status: int, payload, kind="application/json"):
        if not isinstance(payload, (bytes, str)):
            payload = json.dumps(payload)
        data = payload if isinstance(payload, bytes) else payload.encode()
        self.send_response(status)
        self.send_header("Content-Type", kind + "; charset=utf-8")
        self.send_header("Content-Security-Policy", CSP)
        if kind == "application/json":  # a visitor's own data, at a URL every visitor shares: never stored by a cache
            self.send_header("Cache-Control", "no-store")
        if self.issued:
            self.send_header("Set-Cookie", f"visitor={self.issued}; Max-Age={KEEP_SECONDS}; Path=/; HttpOnly; "
                                           "SameSite=Strict; Secure")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def parse_request(self):
        """Routes match the path without its query string: a link shared as /?ref=… still opens the page."""
        ok = super().parse_request()
        if ok:
            self.path = urlsplit(self.path).path
        return ok

    def body(self):
        size = int(self.headers.get("Content-Length") or 0)
        if size > MAX_BODY:
            return None, (413, {"error": "That is too much text for one request."})
        try:
            return json.loads(self.rfile.read(size) or b"null"), None
        except ValueError:
            return None, bad("The request body is not JSON.")

    def visitor_id(self) -> str:
        """This browser's visitor id; a new one, sent back as a cookie, when it has none that is valid."""
        now = time.time()
        self.app.sweep(now)
        vid = visitor(self.headers.get("Cookie") or "", now)
        if vid is None:
            vid = self.issued = f"{int(now)}-{secrets.token_urlsafe(16)}"
        return vid

    def route(self, routes, body=None):
        if self.path not in routes:
            return 404, {"error": "not found"}
        vid = self.visitor_id()
        CURRENT.events = self.app.activity[vid]
        try:
            with self.app.locks[vid]:
                return routes[self.path](self.app.store(vid), body)
        except Exception as e:  # a model or network failure is shown to the user, not a dropped connection
            return 502, {"error": f"The model call failed: {e}"}

    def do_GET(self):
        name = PAGES.get(self.path)
        if name:
            self.reply(200, (STATIC / name).read_bytes(), TYPES[Path(name).suffix])
        elif self.path == "/activity":  # no lock and no store: polled while this visitor's /ingest or /ask holds both
            self.reply(200, list(self.app.activity.get(self.visitor_id(), ())))
        else:
            self.reply(*self.route({"/timeline": self.app.timeline, "/export": self.app.export}))

    def do_POST(self):
        body, error = self.body()
        routes = {"/ingest": self.app.ingest, "/ask": self.app.ask, "/delete-all": self.app.delete_all,
                  "/example": self.app.example}
        self.reply(*(error or self.route(routes, body)))

    def log_message(self, *args):
        pass


def serve(folder: str, port: int, chat=llm.chat, host: str = "127.0.0.1") -> ThreadingHTTPServer:
    handler = type("Bound", (Handler,), {"app": App(folder, chat)})
    return ThreadingHTTPServer((host, port), handler)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1", help="0.0.0.0 inside a container")
    ap.add_argument("--port", type=int, default=7860)
    ap.add_argument("--dir", default="memories", help="visitors/<id>.db, and spend.db unless SPEND_URL is set")
    args = ap.parse_args()
    serve(args.dir, args.port, host=args.host).serve_forever()
