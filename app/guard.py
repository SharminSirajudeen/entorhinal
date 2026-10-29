"""The hosted demo's daily cap. The day's spend is one ledger shared by every visitor. When SPEND_URL names a
Render Key Value instance (Valkey), the ledger lives there, so it outlives this web service's sleeps and restarts;
otherwise it is a SQLite file beside the visitors' memories (local runs and the tests). Delete everything never
touches it."""
import socket
import sqlite3
from pathlib import Path
from urllib.parse import urlsplit

from life.constants import DAILY_CAP_USD, PRICES, ULTRA

SCHEMA = "CREATE TABLE IF NOT EXISTS spend (day TEXT NOT NULL, usd REAL NOT NULL)"
EST_OUT_TOKENS = 4000  # a reply from the dearest model, Ultra, with thinking on
CHARS_PER_TOKEN = 4
KEEP_DAYS = 3  # a day's key in Key Value expires this long after its last spend


class Sqlite:
    def __init__(self, path):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute(SCHEMA)

    def record(self, day: str, usd: float) -> None:
        with self.db:
            self.db.execute("INSERT INTO spend (day, usd) VALUES (?, ?)", (day, usd))

    def spent_today(self, day: str) -> float:
        return self.db.execute("SELECT COALESCE(SUM(usd), 0) FROM spend WHERE day = ?", (day,)).fetchone()[0]


class Valkey:
    """Three commands over RESP, one short connection each. Render's internal Key Value URL needs no password or TLS
    (render.com/docs/key-value: "unauthenticated by default"). If the store cannot be reached, the day counts as spent,
    so paid work is refused rather than run uncounted."""

    def __init__(self, url: str):
        u = urlsplit(url)
        self.addr = (u.hostname, u.port or 6379)

    def command(self, *args) -> bytes | None:
        words = [str(a).encode() for a in args]
        request = b"*%d\r\n" % len(words) + b"".join(b"$%d\r\n%s\r\n" % (len(w), w) for w in words)
        with socket.create_connection(self.addr, timeout=5) as s:
            s.sendall(request)
            reply = s.makefile("rb")
            line = reply.readline()
            if line[:1] == b"-" or not line:
                raise OSError(line.decode(errors="replace").strip() or "no reply")
            if line[:1] == b"$":
                size = int(line[1:])
                return None if size < 0 else reply.read(size + 2)[:-2]
            return line[1:].strip()

    def record(self, day: str, usd: float) -> None:
        try:
            self.command("INCRBYFLOAT", f"spend:{day}", repr(usd))
            self.command("EXPIRE", f"spend:{day}", KEEP_DAYS * 86400)
        except OSError:
            pass  # the call is already paid; the next spent_today cannot reach the store either, and refuses

    def spent_today(self, day: str) -> float:
        try:
            return float(self.command("GET", f"spend:{day}") or 0)
        except OSError:
            return float("inf")


def ledger(folder, url: str | None):
    return Valkey(url) if url else Sqlite(Path(folder) / "spend.db")


def estimate(text: str) -> float:
    """USD for one request: the text read at Ultra's input price plus a full-length Ultra reply."""
    rate_in, _, rate_out = PRICES[ULTRA]
    return (len(text) / CHARS_PER_TOKEN * rate_in + EST_OUT_TOKENS * rate_out) / 1e6


def budget_guard(spent_today: float, estimate: float) -> tuple[bool, str]:
    if spent_today + estimate > DAILY_CAP_USD:
        return False, f"The daily budget of ${DAILY_CAP_USD:.2f} for this demo is used up. Please try again tomorrow."
    return True, ""
