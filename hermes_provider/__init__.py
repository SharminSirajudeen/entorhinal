"""A Hermes Agent memory provider over ingest and check_premises (hooks: agent/memory_provider.py in
NousResearch/hermes-agent, MIT; only its base class is imported, and only when Hermes is present). Every model call
runs on a background thread, so no hook blocks and none raises."""
import logging
import os
import threading
from datetime import datetime
from pathlib import Path

from life import llm, memory, query
from life.store import Store
from life.types import Session

try:
    from agent.memory_provider import MemoryProvider, spawn_context_thread
except ImportError:  # Hermes is not installed (tests, a plain checkout)
    MemoryProvider = object

    def spawn_context_thread(target, *, name, args=(), kwargs=None, daemon=True):
        return threading.Thread(target=target, args=args, kwargs=kwargs, name=name, daemon=daemon)

log = logging.getLogger(__name__)
NAME = "entorhinal"
PREFETCH_WAIT_S = 6.0  # Hermes gives an external prefetch 8 s (agent/memory_manager.py, _EXTERNAL_PREFETCH_TIMEOUT_S)


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _spawn(name, work, *args):
    thread = spawn_context_thread(work, name=name, args=args)
    thread.start()
    return thread


def _after(prev):
    if prev:
        prev.join()


class StaleAwareMemory(MemoryProvider):
    def __init__(self, chat=llm.chat, clock=_now, wait: float = PREFETCH_WAIT_S):
        self._chat, self._clock, self._wait = chat, clock, wait
        self._store = self._sync = self._job = None  # _job: ((question, ingest thread), thread, result)
        self._writes, self._next_idx = True, 0

    @property
    def name(self) -> str:
        return NAME

    def is_available(self) -> bool:
        return bool(os.environ.get("NEBIUS_API_KEY"))

    def unavailable_reason(self) -> str:
        return "Set NEBIUS_API_KEY: the memory's model calls go to Nebius Token Factory."

    def initialize(self, session_id: str, **kwargs) -> None:
        home = Path(kwargs["hermes_home"]) / NAME
        home.mkdir(parents=True, exist_ok=True)
        self._store = Store(str(home / "memory.db"))
        self._writes = kwargs.get("agent_context", "primary") == "primary"  # subagent/cron/flush turns aren't the user
        self._next_idx = 1 + max((f.source_idx for f in self._store.timeline()), default=-1)

    def system_prompt_block(self) -> str:
        return ("Memory notes when a newer fact makes an older one untrue; any such stale assumption in the user's "
                "question is listed under the recalled context. Do not act on it: say what changed first.")

    def get_tool_schemas(self) -> list[dict]:
        return []  # the check rides on prefetch; a tool would only add a second path to the same call

    def sync_turn(self, user_content: str, assistant_content: str, *, session_id: str = "", **kwargs) -> None:
        """Ingest the user's side of the turn only, queued behind the previous turn's ingest."""
        if not self._writes or not user_content.strip():
            return
        session = Session(self._next_idx, self._clock(), [{"role": "user", "content": user_content}])
        self._next_idx += 1
        self._sync = _spawn("entorhinal-ingest", self._ingest, session, self._sync)

    def _ingest(self, session, prev) -> None:
        _after(prev)
        try:
            memory.ingest(self._store, session, self._chat)
        except Exception:  # a failed model call loses this turn's facts, never the agent's turn
            log.warning("entorhinal ingest failed; this turn's facts are lost", exc_info=True)

    def queue_prefetch(self, query: str, *, session_id: str = "") -> None:
        self._start(query)

    def prefetch(self, query: str, *, session_id: str = "") -> str:
        """The stale premises of this question; "" when none, or when the check is not done within the wait (asked
        again, the same question finds it done)."""
        _, thread, result = self._start(query)
        thread.join(self._wait)
        return result[0] if result else ""

    def _start(self, question: str):
        key = (question, self._sync)  # a newer turn's ingest makes the earlier check out of date
        if self._job and self._job[0] == key:
            return self._job
        result: list[str] = []
        self._job = (key, _spawn("entorhinal-check", self._check, question, self._sync, result), result)
        return self._job

    def _check(self, question, ingest, result) -> None:
        _after(ingest)  # the premise check must see the facts the last turn added
        try:
            result.append(self._text(query.check_premises(self._store, question, self._chat)))
        except Exception:
            log.warning("entorhinal premise check failed", exc_info=True)  # no text: prefetch returns ""

    def _text(self, report) -> str:
        return "\n".join(
            f'Stale premise: this question assumes "{s["premise"]}", but the user later said: '
            f'{query.show(s["invalidated_by"], self._store)} (why: {s["reason"]})' for s in report.stale)


def register(ctx) -> None:
    ctx.register_memory_provider(StaleAwareMemory())
