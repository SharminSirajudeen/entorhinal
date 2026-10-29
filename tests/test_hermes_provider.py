"""The Hermes provider's hooks driven directly with a fake chat; golden 1 (bike_leg) is the scenario.
Threads are joined, never slept on; where a thread must still be waiting, a join with a timeout must expire."""
import json
import threading
from pathlib import Path

import pytest

import hermes_provider
from hermes_provider import StaleAwareMemory
from life.constants import LIGHTNING
from life.store import Store

ASK = "Which route should I bike tomorrow?"
TURNS = ["I bike 10 miles to work daily, it's the best part of my morning.",
         "Bad news: I fell on the stairs and my leg is in a cast for six weeks."]
FACTS = [("user", "commute", "bikes 10 miles to work daily"), ("user", "health", "leg in a cast for six weeks")]
DECISION = [{"old_id": "s0f0", "verdict": "stale", "by": "s1f0", "reason": "a cast on the leg stops cycling"}]
PREMISE = {"assumptions": [{"assumption": "I can bike tomorrow", "verdict": "OUTDATED", "fact_id": "s0f0",
                            "reason": "cast"}]}
PATH = Path(hermes_provider.__file__).parent


class Fake:
    """S4 (Lightning) answers per turn in order, S6 (its prompt lists OLD facts) the decision, S8 the premise reply.
    `gate`, when set, holds the first S4 call until the test releases it."""

    def __init__(self, premise=PREMISE, gate=None, s8_gate=None):
        self.facts, self.premise, self.gate, self.s8_gate, self.calls = list(FACTS), premise, gate, s8_gate, []

    def __call__(self, model, messages, json_mode=False, think=False, max_tokens=4000):
        prompt = messages[0]["content"]
        kind = "s4" if model == LIGHTNING else "s6" if "OLD facts:" in prompt else "s8"
        self.calls.append((kind, prompt))
        if kind == "s4":
            if self.gate:  # holds the first S4 call only
                gate, self.gate = self.gate, None
                gate.wait()
            return json.dumps({"facts": [dict(zip(("subject", "attribute", "value"), self.facts.pop(0)))]}), {}
        if kind == "s6":
            return json.dumps(DECISION), {}
        if self.s8_gate:
            self.s8_gate.wait()
        if isinstance(self.premise, Exception):
            raise self.premise
        return json.dumps(self.premise), {"prompt_tokens": 1, "completion_tokens": 1}

    def count(self, kind):
        return sum(k == kind for k, _ in self.calls)


def make(tmp_path, chat, **kw):
    p = StaleAwareMemory(chat=chat, clock=iter(["2026-03-01 08:30", "2026-03-22 19:05"]).__next__, **kw)
    p.initialize("s", hermes_home=str(tmp_path), platform="cli")
    return p


def drain(p):
    for t in (p._sync, p._job and p._job[1]):
        if t:
            t.join()


def turn(p, n):
    p.sync_turn(TURNS[n], "assistant words", session_id="s")


@pytest.fixture
def thread_errors(monkeypatch):
    """Unhandled exceptions on hook threads: a hook must never leave one."""
    seen = []
    monkeypatch.setattr(threading, "excepthook", seen.append)
    return seen


def test_golden1_hooks_leave_commute_stale_and_prefetch_names_it(tmp_path):
    fake = Fake()
    p = make(tmp_path, fake)
    turn(p, 0)
    turn(p, 1)
    text = p.prefetch(ASK, session_id="s")
    store = Store(str(tmp_path / "entorhinal" / "memory.db"))
    assert [(f.id, f.invalidated_by) for f in store.stale()] == [("s0f0", "s1f0")]
    assert [f.id for f in store.active()] == ["s1f0"]
    assert 'this question assumes "I can bike tomorrow"' in text
    assert "(2026-03-22 19:05) user / health: leg in a cast for six weeks" in text
    assert "why: cast" in text


def test_nothing_stale_gives_empty_text(tmp_path):
    p = make(tmp_path, Fake(premise={"assumptions": [{"assumption": "x", "verdict": "SAFE", "fact_id": "s0f0"}]}))
    turn(p, 0)
    assert p.prefetch(ASK) == ""


def test_only_the_users_words_are_ingested(tmp_path):
    fake = Fake()
    p = make(tmp_path, fake)
    turn(p, 0)
    drain(p)
    prompt = fake.calls[0][1]
    assert TURNS[0] in prompt and "assistant words" not in prompt and "Assistant:" not in prompt


def test_blank_turns_and_non_primary_contexts_write_nothing(tmp_path):
    fake = Fake()
    p = make(tmp_path, fake)
    p.sync_turn("   ", "a")
    q = StaleAwareMemory(chat=fake)
    q.initialize("s", hermes_home=str(tmp_path / "other"), agent_context="subagent")
    turn(q, 0)
    assert fake.calls == [] and p._sync is None and q._sync is None


def test_second_session_continues_ids_from_the_store(tmp_path):
    fake = Fake()
    p = make(tmp_path, fake)
    turn(p, 0)
    drain(p)
    again = StaleAwareMemory(chat=Fake(), clock=lambda: "2026-04-01 09:00")
    again.initialize("s2", hermes_home=str(tmp_path))
    turn(again, 1)
    drain(again)
    assert [f.id for f in Store(str(tmp_path / "entorhinal" / "memory.db")).timeline()] == ["s0f0", "s1f0"]


def test_store_lives_under_the_profile_home_and_profiles_do_not_share(tmp_path):
    a, b = make(tmp_path / "a", Fake()), make(tmp_path / "b", Fake())
    turn(a, 0)
    drain(a)
    assert (tmp_path / "a" / "entorhinal" / "memory.db").exists()
    assert [f.id for f in b._store.timeline()] == []


def test_turns_ingest_in_order_even_when_the_first_is_slow(tmp_path):
    gate = threading.Event()
    fake = Fake(gate=gate)
    p = make(tmp_path, fake)
    turn(p, 0)
    turn(p, 1)
    p._sync.join(0.2)
    assert p._sync.is_alive() and fake.count("s6") == 0  # turn 2 waits for turn 1
    gate.set()
    drain(p)
    assert [s.invalidated_by for s in p._store.stale()] == ["s1f0"]


def test_check_waits_for_the_ingest_before_it_reads_the_store(tmp_path):
    gate = threading.Event()
    p = make(tmp_path, Fake(gate=gate))
    turn(p, 0)
    turn(p, 1)
    p.queue_prefetch(ASK)
    p._job[1].join(0.2)
    assert p._job[1].is_alive()
    gate.set()
    drain(p)
    assert "Stale premise" in p._job[2][0]


def test_prefetch_waits_for_a_slow_check_within_the_wait(tmp_path):
    """S8 is held for 0.2 s of the default 6 s wait: a prefetch that waits gets the text; one that does not gets ""."""
    gate = threading.Event()
    p = make(tmp_path, Fake(s8_gate=gate))
    turn(p, 0)
    turn(p, 1)
    threading.Timer(0.2, gate.set).start()
    assert p.prefetch(ASK).startswith("Stale premise")


def test_prefetch_gives_up_at_the_wait_and_the_same_question_reuses_the_job(tmp_path):
    gate = threading.Event()
    fake = Fake(s8_gate=gate)
    p = make(tmp_path, fake, wait=0.05)
    turn(p, 0)
    turn(p, 1)
    assert p.prefetch(ASK) == ""  # the check is still held at S8
    job = p._job
    gate.set()
    job[1].join()
    assert p.prefetch(ASK).startswith("Stale premise") and p._job is job
    assert fake.count("s8") == 1


def test_a_new_turn_or_question_starts_a_new_check(tmp_path):
    fake = Fake()
    p = make(tmp_path, fake)
    turn(p, 0)
    p.prefetch(ASK)
    p.prefetch(ASK)
    assert fake.count("s8") == 1
    p.prefetch("Another question?")
    assert fake.count("s8") == 2
    turn(p, 1)
    p.prefetch("Another question?")
    assert fake.count("s8") == 3


def test_a_failing_model_call_degrades_to_empty_text_and_later_turns_still_ingest(tmp_path, thread_errors):
    fake = Fake(premise=OSError("network"))
    p = make(tmp_path, fake)
    fake.facts = [FACTS[0]]
    turn(p, 0)
    assert p.prefetch(ASK) == ""
    boom = Fake()
    boom.facts = []  # an empty list makes S4 raise IndexError inside the thread
    p._chat = boom
    turn(p, 1)
    drain(p)
    assert p._store.timeline()[0].id == "s0f0"
    assert thread_errors == []


def test_availability_follows_the_key(tmp_path, monkeypatch):
    p = StaleAwareMemory()
    monkeypatch.setenv("NEBIUS_API_KEY", "k")
    assert p.is_available() is True
    monkeypatch.delenv("NEBIUS_API_KEY")
    assert p.is_available() is False and "NEBIUS_API_KEY" in p.unavailable_reason()


def test_static_surface_and_registration():
    got = []

    class Ctx:
        def register_memory_provider(self, provider):
            got.append(provider)

    hermes_provider.register(Ctx())
    hermes_provider.register(Ctx())
    assert got[0] is not got[1]  # one new instance per load (the multiplexing contract)
    p = got[0]
    assert p.get_tool_schemas() == [] and "older one untrue" in p.system_prompt_block()
    assert f"name: {p.name}\n" in (PATH / "plugin.yaml").read_text()
