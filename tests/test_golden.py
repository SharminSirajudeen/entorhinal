"""The goldens are the executable spec for the write and read paths: each parses into the shared types with a
well-formed expectation."""
import json
from pathlib import Path

import pytest

from life.types import Instance, Session

GOLDEN = Path(__file__).parent / "golden"
KEYS = {"stale", "active", "premise_flagged", "answer_has"}


def sessions_of(d: dict) -> list[Session]:
    if "instance" in d:
        i = Instance(**d["instance"])
        return [Session(n, t, turns) for n, (t, turns) in enumerate(zip(i.timestamps, i.haystack_session))]
    return [Session(**s) for s in d["sessions"]]


@pytest.mark.parametrize("name", ["bike_leg", "no_conflict", "changed_value", "late_shift"])
def test_golden_parses(name):
    d = json.loads((GOLDEN / f"{name}.json").read_text())
    sessions = sessions_of(d)
    assert len(sessions) == 2
    assert [s.time for s in sessions] == sorted(s.time for s in sessions)
    assert all(t["role"] in ("user", "assistant") for s in sessions for t in s.turns)
    assert d["question"].strip()
    assert set(d["expected"]) <= KEYS and {"stale", "active"} <= set(d["expected"])
