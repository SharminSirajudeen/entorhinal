"""The memory write path: extract_facts, related_active, adjudicate, ingest.
A malformed model reply is a safe result (no facts, no decisions), never an exception out of ingest."""
import json
import logging
from dataclasses import replace

from life.constants import LIGHTNING, S6_MODEL
from life.llm import chat as llm_chat
from life.store import Store
from life.types import Decision, Fact, Session

FIELDS = ("subject", "attribute", "value")
VERDICTS = ("keep", "stale", "changed")
log = logging.getLogger("life")  # each step in words, for the app's live view; the step goes in `extra`

FACT_PROMPT = (
    "List every fact the USER reveals about themselves in this session (situation, work, health, location, "
    "possessions, plans, habits, relationships). Reply with a JSON object "
    '{"facts": [{"subject": ..., "attribute": ..., "value": ...}]}, one entry per fact; subject is who or what '
    'the fact is about ("user" for the user), value is a short phrase. The session time only dates the facts; it '
    'is not a fact itself. Reply {"facts": []} if there are none.')

# one row per old fact ran Ultra out of max_tokens on a 326-fact memory, so only the untrue ones are asked for
CHANGE_PROMPT = (
    "Each NEW fact is dated later than every OLD fact. Find every OLD fact that a NEW fact changes or makes untrue for "
    "the user's situation now, including implicit consequences (a new job schedule replaces the old schedule; a broken "
    "leg stops cycling; a legal name change makes anything held under the old name out of date). Most sessions change "
    "nothing. After thinking, output a line 'FINAL:' followed by a JSON array listing ONLY the OLD facts that are now "
    "untrue, [] if none: "
    '{"old_id": ..., "verdict": "stale" | "changed", "by": id of the NEW fact that causes it, "reason": one sentence}.')


def _rows(text: str, key: str | None = None) -> list[dict]:
    """The objects in a model reply (under `key` when given); [] when it does not parse."""
    try:
        data = json.loads(text)
        data = data[key] if key else data
    except (ValueError, KeyError, TypeError):
        return []
    return [x for x in data if isinstance(x, dict)] if isinstance(data, list) else []


def _ask(chat, model: str, prompt: str, **kw) -> str:
    try:
        return chat(model, [{"role": "user", "content": prompt}], **kw)[0]
    except ValueError:  # a reply cut at max_tokens
        return ""


def extract_facts(session: Session, chat=llm_chat) -> list[Fact]:
    """The user's facts in one session, dated with the session time."""
    text = "\n".join(f"{t['role'].title()}: {t['content']}" for t in session.turns)
    reply = _ask(chat, LIGHTNING, f"[Session time: {session.time}]\n{text}\n\nTask: {FACT_PROMPT}",
                 json_mode=True, max_tokens=1500)
    rows = [r for r in _rows(reply, "facts") if all(isinstance(r.get(k), str) and r[k] for k in FIELDS)]
    return [Fact(f"s{session.idx}f{n}", r["subject"], r["attribute"], r["value"], session.time, session.idx)
            for n, r in enumerate(rows)]


def related_active(store: Store, facts: list[Fact]) -> list[Fact]:
    """Every active fact about a new fact's subject, or whose subject a new fact's value mentions, oldest first so
    the change judge's prompt prefix stays the same from one session to the next. No cap: a pilot measured a
    newest-40 cap hiding the very fact a session changed. O(active facts)."""
    subjects = {f.subject.casefold() for f in facts}
    values = " ".join(f.value.casefold() for f in facts)
    return [o for o in store.active() if o.subject.casefold() in subjects or o.subject.casefold() in values]


def _line(f: Fact) -> str:
    return f"[{f.id}] ({f.time}) {f.subject} / {f.attribute}: {f.value}"


def _quote(f: Fact) -> str:
    return f"'{f.attribute}: {f.value}'"


def adjudicate(new: list[Fact], olds: list[Fact], chat=llm_chat, model: str = S6_MODEL) -> list[Decision]:
    """Which of the older active facts the new facts have made untrue. Unknown old ids and verdicts are dropped;
    an unknown or missing `by` falls back to the newest new fact."""
    if not new or not olds:
        return []
    prompt = (f"OLD facts:\n{chr(10).join(map(_line, olds))}\n\nNEW facts:\n{chr(10).join(map(_line, new))}"
              f"\n\nTask: {CHANGE_PROMPT}")
    known, by_ids = {o.id for o in olds}, {n.id for n in new}
    out = []
    for r in _rows(_ask(chat, model, prompt, think=True, max_tokens=12000)):
        if r.get("old_id") in known and r.get("verdict") in VERDICTS:
            by = r["by"] if r.get("by") in by_ids else new[-1].id
            out.append(Decision(r["old_id"], r["verdict"], str(r.get("reason", "")), by))
    return out


def ingest(store: Store, session: Session, chat=llm_chat, s6_model: str = S6_MODEL) -> None:
    """Extract -> relate -> judge -> write. Stale facts are kept, linked to the new fact that replaced them. Each step
    is logged in words to the "life" logger (nothing is shown unless a handler is installed, as the app does)."""
    new = extract_facts(session, chat)
    log.info("Extracted %s", ", ".join(map(_quote, new)) or "no facts",
             extra={"step": "S4", "ids": [f.id for f in new], "labels": [f.attribute for f in new]})
    olds = related_active(store, new)
    log.info("Related older facts: %d", len(olds), extra={"step": "S5", "ids": [o.id for o in olds]})
    for f in new:
        store.put(f)
    by_id, new_by_id, stale = {o.id: o for o in olds}, {n.id: n for n in new}, 0
    for d in adjudicate(new, olds, chat, s6_model):
        if d.verdict != "keep":
            store.put(replace(by_id[d.old_id], status="stale", invalidated_by=d.by, reason=d.reason))
            log.info("Marked %s stale, because of %s", _quote(by_id[d.old_id]), _quote(new_by_id[d.by]),
                     extra={"step": "S6", "ids": [d.old_id, d.by]})
            stale += 1
    if not stale:
        log.info("No older fact made untrue" if olds else "Nothing older to judge; no model asked",
                 extra={"step": "S6"})
    log.info("Stored: %d new, %d marked stale", len(new), stale, extra={"step": "Store"})
