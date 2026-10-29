"""A user's memory is one SQLite file they own. Stale facts are kept, linked to what replaced them, never deleted;
only the user's delete_all() removes anything."""
import json
import sqlite3
from dataclasses import asdict, astuple, fields

from life.types import Fact

COLUMNS = ", ".join(f.name for f in fields(Fact))
SCHEMA = """CREATE TABLE IF NOT EXISTS facts (
  id TEXT PRIMARY KEY, subject TEXT NOT NULL, attribute TEXT NOT NULL, value TEXT NOT NULL, time TEXT NOT NULL,
  source_idx INTEGER NOT NULL, status TEXT NOT NULL CHECK (status IN ('active', 'stale')),
  invalidated_by TEXT, reason TEXT)"""


class Store:
    def __init__(self, path: str):
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.execute(SCHEMA)

    def _select(self, where: str = "", args: tuple = ()) -> list[Fact]:
        rows = self.db.execute(f"SELECT {COLUMNS} FROM facts {where} ORDER BY time, id", args)
        return [Fact(*r) for r in rows]

    def put(self, *facts: Fact) -> None:
        """Insert, or replace the facts with the same ids (how a fact is marked stale), in one transaction."""
        with self.db:
            self.db.executemany(f"INSERT OR REPLACE INTO facts ({COLUMNS}) VALUES (?,?,?,?,?,?,?,?,?)",
                                map(astuple, facts))

    def get(self, fact_id: str) -> Fact | None:
        found = self._select("WHERE id = ?", (fact_id,))
        return found[0] if found else None

    def active(self) -> list[Fact]:
        return self._select("WHERE status = 'active'")

    def stale(self) -> list[Fact]:
        return self._select("WHERE status = 'stale'")

    def timeline(self) -> list[Fact]:
        """Every fact, oldest first: what the user said, and which later fact made it untrue."""
        return self._select()

    def export_json(self) -> str:
        return json.dumps([asdict(f) for f in self.timeline()], ensure_ascii=False, indent=1)

    def delete_all(self) -> None:
        with self.db:
            self.db.execute("DELETE FROM facts")
