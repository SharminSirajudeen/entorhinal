"""The write path against a fake `chat` with hand-written replies; expected values derived by hand from the goldens."""
import json
from pathlib import Path

import pytest

from life import llm, memory
from life.constants import LIGHTNING, S6_MODEL, SUPER, ULTRA
from life.store import Store
from life.types import Fact, Session
from tests.test_golden import sessions_of

GOLDEN = Path(__file__).parent / "golden"


class Fake:
    """chat(...) that pops the next scripted reply for the model asked; an unscripted call fails the test."""

    def __init__(self, light=(), s6=()):
        self.script = {LIGHTNING: list(light), S6_MODEL: list(s6)}
        self.calls = []

    def __call__(self, model, messages, json_mode=False, think=False, max_tokens=4000):
        self.calls.append({"model": model, "json_mode": json_mode, "think": think, "prompt": messages[0]["content"]})
        reply = self.script[model].pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply, {}


def facts(*rows):
    return json.dumps({"facts": [dict(zip(("subject", "attribute", "value"), r)) for r in rows]})


def decisions(*rows):
    return json.dumps([dict(zip(("old_id", "verdict", "by", "reason"), r)) for r in rows])


def fact(i, subject="user", value="v", time="2026-01-01 00:00", status="active"):
    return Fact(i, subject, "attr", value, time, 0, status)


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "m.db"))


def text_of(f):
    return f"{f.subject} {f.attribute} {f.value}".lower()


def check_golden(store, expected):
    """The goldens' `_rule`: stale entries by substring, invalidated_by an active fact; active strings found."""
    active = store.active()
    for want in expected["stale"]:
        hits = [s for s in store.stale() if any(o in text_of(s) for o in want["old"])
                and any(any(b in text_of(a) for b in want["by"]) for a in active if a.id == s.invalidated_by)]
        assert hits, f"no stale fact like {want}"
    if not expected["stale"]:
        assert store.stale() == []
    for s in expected["active"]:
        assert any(s in text_of(a) for a in active), s


# per golden: the S4 reply for session 0 and 1, and the S6 reply (hand-written)
SCRIPTS = {
    "bike_leg": ([facts(("user", "commute", "bikes 10 miles to work daily")),
                  facts(("user", "health", "leg in a cast for six weeks"))],
                 decisions(("s0f0", "stale", "s1f0", "a cast on the leg stops cycling"))),
    "no_conflict": ([facts(("user", "workplace", "works at a bakery downtown")),
                     facts(("user", "pet", "adopted a cat"))],
                    decisions(("s0f0", "keep", "s1f0", "a cat says nothing about the job"))),
    "changed_value": ([facts(("user", "residence", "lives in Dubai")),
                       facts(("user", "residence", "moved to Abu Dhabi"))],
                      decisions(("s0f0", "changed", "s1f0", "moved from Dubai to Abu Dhabi"))),
    "late_shift": ([facts(("user", "work hours", "8 a.m. to 4 p.m. on weekdays")),
                    facts(("user", "work hours", "late shift, noon to 8 p.m."))],
                   decisions(("s0f0", "stale", "s1f0", "the late shift replaces the day shift"))),
}


@pytest.mark.parametrize("name", list(SCRIPTS))
def test_golden_ingest(name, store):
    d = json.loads((GOLDEN / f"{name}.json").read_text())
    light, verdict = SCRIPTS[name]
    chat = Fake(light, [verdict])
    for s in sessions_of(d):
        memory.ingest(store, s, chat)
    check_golden(store, d["expected"])
    assert len(store.timeline()) == 2  # nothing deleted


def test_first_session_asks_no_adjudication(store):
    chat = Fake([facts(("user", "job", "baker"))])
    memory.ingest(store, Session(0, "2026-01-01 00:00", [{"role": "user", "content": "I bake"}]), chat)
    assert [c["model"] for c in chat.calls] == [LIGHTNING]  # no Ultra call: nothing older to judge


def test_models_and_flags(store):
    chat = Fake([facts(("user", "job", "baker")), facts(("user", "job", "pilot"))], [decisions()])
    memory.ingest(store, Session(0, "2026-01-01 00:00", [{"role": "user", "content": "x"}]), chat)
    memory.ingest(store, Session(1, "2026-02-01 00:00", [{"role": "user", "content": "y"}]), chat)
    assert [(c["model"], c["json_mode"], c["think"]) for c in chat.calls] == [
        (LIGHTNING, True, False), (LIGHTNING, True, False), (SUPER, False, True)]  # the change judge runs on Super


def test_s6_model_is_the_callers_choice(store):
    chat = Fake([facts(("user", "job", "baker")), facts(("user", "job", "pilot"))])
    chat.script[ULTRA] = [decisions()]
    memory.ingest(store, Session(0, "2026-01-01 00:00", [{"role": "user", "content": "x"}]), chat, ULTRA)
    memory.ingest(store, Session(1, "2026-02-01 00:00", [{"role": "user", "content": "y"}]), chat, ULTRA)
    assert [c["model"] for c in chat.calls] == [LIGHTNING, LIGHTNING, ULTRA]  # the ours-ultra benchmark condition


def test_extract_ids_time_and_prompt():
    turns = [{"role": "user", "content": "I own a kayak"}, {"role": "assistant", "content": "ok"}]
    s = Session(7, "2026-05-05 10:00", turns)
    chat = Fake([facts(("user", "kayak", "owns one"), ("user", "city", "Oslo"))])
    got = memory.extract_facts(s, chat)
    assert [(f.id, f.subject, f.attribute, f.value, f.time, f.source_idx, f.status) for f in got] == [
        ("s7f0", "user", "kayak", "owns one", "2026-05-05 10:00", 7, "active"),
        ("s7f1", "user", "city", "Oslo", "2026-05-05 10:00", 7, "active")]
    prompt = chat.calls[0]["prompt"]
    assert "[Session time: 2026-05-05 10:00]" in prompt and "User: I own a kayak" in prompt
    assert "The session time only dates the facts; it is not a fact itself." in prompt  # report 08's false flag


def test_extract_none_is_empty():
    assert memory.extract_facts(Session(0, "t", []), Fake([facts()])) == []


def test_extract_skips_incomplete_rows():
    rows = [{"subject": "user", "attribute": "a"}, {"subject": "user", "attribute": "b", "value": 3}, "junk",
            {"subject": "user", "attribute": "c", "value": "ok"}]
    reply = json.dumps({"facts": rows})
    got = memory.extract_facts(Session(0, "t", []), Fake([reply]))
    assert [(f.id, f.attribute) for f in got] == [("s0f0", "c")]


@pytest.mark.parametrize("bad", ["NONE", "not json {", '{"facts": "x"}', "[1, 2]", '{"other": []}', "null", ""])
def test_extract_malformed_reply_is_no_facts(bad):
    assert memory.extract_facts(Session(0, "t", []), Fake([bad])) == []


def test_extract_truncated_reply_is_no_facts():
    assert memory.extract_facts(Session(0, "t", []), Fake([ValueError("truncated")])) == []


def test_related_matches_subject_case_insensitively(store):
    store.put(fact("a", "User"))
    store.put(fact("b", "Rex"))
    got = memory.related_active(store, [fact("n", "uSER")])
    assert [f.id for f in got] == ["a"]


def test_related_matches_subject_named_in_a_value(store):
    store.put(fact("a", "Rex"))
    store.put(fact("b", "Luna"))
    assert [f.id for f in memory.related_active(store, [fact("n", "user", "walks REX daily")])] == ["a"]


def test_related_excludes_stale_and_unrelated(store):
    store.put(fact("a", "user", status="stale"))
    store.put(fact("b", "user"))
    store.put(fact("c", "bike"))
    assert [f.id for f in memory.related_active(store, [fact("n", "user")])] == ["b"]


def test_related_is_every_matching_fact_oldest_first(store):
    """The fact a session changes can be the oldest of hundreds, so none is dropped."""
    for i in range(300):
        store.put(fact(f"u{i:03}", "user", time=f"20{26 + i // 28}-01-{i % 28 + 1:02} 00:00"))
    for i in range(4):  # newest of all, but about something else
        store.put(fact(f"o{i}", "other", time="2099-01-01 00:00"))
    got = memory.related_active(store, [fact("n", "user")])
    assert [f.id for f in got] == [f"u{i:03}" for i in range(300)]


def test_adjudicate_parses_and_prompt_lists_both_sides():
    chat = Fake(s6=[decisions(("o1", "stale", "n1", "why"), ("o2", "keep", "n1", "unrelated"))])
    got = memory.adjudicate([fact("n1", value="NEWVALUE")], [fact("o1", value="OLDONE"), fact("o2")], chat)
    assert [(d.old_id, d.verdict, d.reason, d.by) for d in got] == [("o1", "stale", "why", "n1"),
                                                                     ("o2", "keep", "unrelated", "n1")]
    prompt = chat.calls[0]["prompt"]
    assert "[n1]" in prompt and "OLDONE" in prompt
    # OLD facts first: the prefix is the same from one session to the next (cacheable); only untrue facts are asked for
    assert prompt.index("OLD facts:") < prompt.index("OLDONE") < prompt.index("NEW facts:") < prompt.index("[n1]")
    assert "ONLY the OLD facts that are now untrue, [] if none" in prompt


@pytest.mark.xfail(strict=True, reason="known defect (docs/reports/09-measured-run): 52 of about 580 change-judge "
                   "replies stopped at max_tokens and their sessions' changes were lost; nothing retries a cut-off "
                   "reply yet")
def test_a_cut_off_s6_reply_does_not_lose_the_sessions_changes():
    chat = Fake(s6=[llm.Truncated(SUPER, {}), decisions(("o1", "stale", "n1", "r"))])
    got = memory.adjudicate([fact("n1")], [fact("o1")], chat)
    assert [(d.old_id, d.verdict) for d in got] == [("o1", "stale")]


def test_adjudicate_drops_unknown_ids_and_verdicts():
    rows = [("ghost", "stale", "n1", "x"), ("o1", "maybe", "n1", "x"), ("o1", "changed", "n1", "ok")]
    chat = Fake(s6=[decisions(*rows)])
    assert [(d.old_id, d.verdict) for d in memory.adjudicate([fact("n1")], [fact("o1")], chat)] == [("o1", "changed")]


@pytest.mark.parametrize("bad", ['"reason": The conversion...', "[{'old_id': 'o1'}]", '{"old_id": "o1"}', "",
                                 ValueError("cut")])
def test_adjudicate_malformed_reply_is_no_decision(bad):
    assert memory.adjudicate([fact("n1")], [fact("o1")], Fake(s6=[bad])) == []


def test_ingest_survives_malformed_adjudication(store):
    store.put(fact("o1", "user", "bikes"))
    chat = Fake([facts(("user", "health", "cast"))], ['{"old_id": "o1", "verdict": "stale", "reason": The cast...}'])
    memory.ingest(store, Session(1, "2026-02-01 00:00", []), chat)
    assert [f.id for f in store.active()] == ["o1", "s1f0"] and store.stale() == []


def test_ingest_survives_malformed_extraction(store):
    store.put(fact("o1"))
    memory.ingest(store, Session(1, "2026-02-01 00:00", []), Fake(["{broken"]))
    assert [f.id for f in store.timeline()] == ["o1"]


def test_ingest_unknown_by_falls_back_to_newest_new_fact(store):
    store.put(fact("o1", "user", "bikes", time="2026-01-01 00:00"))
    chat = Fake([facts(("user", "a", "x"), ("user", "b", "y"))], [decisions(("o1", "stale", "zzz", "r"))])
    memory.ingest(store, Session(1, "2026-02-01 00:00", []), chat)
    old = store.get("o1")
    assert (old.status, old.invalidated_by, old.reason) == ("stale", "s1f1", "r")


def test_ingest_keep_leaves_fact_untouched_and_only_related_are_judged(store):
    store.put(fact("o1", "user", "bikes"))
    store.put(fact("o2", "boat", "UNRELATEDBOAT"))
    chat = Fake([facts(("user", "pet", "cat"))], [decisions(("o1", "keep", "s1f0", "fine"))])
    memory.ingest(store, Session(1, "2026-02-01 00:00", []), chat)
    assert store.get("o1").status == "active" and store.get("o1").invalidated_by is None
    assert "bikes" in chat.calls[1]["prompt"]
    assert "UNRELATEDBOAT" not in chat.calls[1]["prompt"]
