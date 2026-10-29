"""check_premises and answer: before answering, list what the question assumes about the user, flag any
assumption a newer fact has made untrue, and correct it first, citing the newer fact and its date."""
import json
import logging

from life import llm
from life.constants import SUPER
from life.types import Answer, Fact, PremiseReport

log = logging.getLogger("life")  # each step in words, for the app's live view; the step goes in `extra`

PREMISE_PROMPT = (
    "List each assumption the question makes about the user's CURRENT situation. Give each a verdict: OUTDATED if a "
    "newer fact contradicts it (implicit consequences count: a broken leg means no cycling); SAFE if the newest "
    "related fact supports it; UNRESOLVED if the memory says nothing about it. 'Not mentioned' is UNRESOLVED, never "
    "OUTDATED. For OUTDATED, give the id of the STALE fact the assumption rests on. After thinking, output a line "
    "'FINAL:' followed by only JSON: {\"assumptions\": [{\"assumption\": str, \"verdict\": \"SAFE\"|\"OUTDATED\"|"
    "\"UNRESOLVED\", \"fact_id\": str, \"reason\": str}]}")
ANSWER_NOTE = (
    "Step 1: list every assumption the question makes about the user. Step 2: for each, find the most recent related "
    "fact in the memory; later facts override earlier ones, including their implicit consequences (a broken leg "
    "means no cycling). Step 3: if an assumption is outdated, begin your reply by correcting it, citing the newer "
    "fact and its date, then answer for the user's current situation. Do not correct assumptions the premise check "
    "marks as safe or unresolved.")


def line(fact: Fact, store) -> str:
    """One memory line carrying the fact id; a stale fact also says what replaced it, and when."""
    head = f"[{fact.id}] ({fact.time}) {fact.subject} / {fact.attribute}: {fact.value}"
    if fact.status == "active":
        return head
    newer = store.get(fact.invalidated_by) if fact.invalidated_by else None
    when = f" ({newer.time})" if newer else ""
    return f"{head}; STALE, replaced by [{fact.invalidated_by}]{when} because: {fact.reason}"


def show(fact_id, store) -> str:
    fact = store.get(fact_id) if fact_id else None
    return line(fact, store) if fact else f"[{fact_id}] (not in memory)"


def memory_text(store) -> str:
    return "\n".join(line(f, store) for f in store.timeline())


def parse(text: str, store) -> PremiseReport:
    """Only OUTDATED assumptions that name a fact the Store holds as stale are flagged; the replacing fact and the
    default reason come from the Store, not from the model."""
    items = json.loads(text[text.find("{"):text.rfind("}") + 1])["assumptions"]
    stale_by_id = {f.id: f for f in store.stale()}
    flagged = [{"premise": i["assumption"], "fact_id": i["fact_id"],
                "invalidated_by": stale_by_id[i["fact_id"]].invalidated_by,
                "reason": i.get("reason") or stale_by_id[i["fact_id"]].reason}
               for i in items if i.get("verdict") == "OUTDATED" and i.get("fact_id") in stale_by_id]
    return PremiseReport([i["assumption"] for i in items], flagged)


def run_check(store, question, chat) -> tuple[PremiseReport, float]:
    """The report and its cost. A reply that is cut off or does not parse gives an empty report, never an error."""
    task = f"[User memory, dated]\n{memory_text(store)}\n\n[Question]\n{question}\n\nTask: {PREMISE_PROMPT}"
    costs: list[float] = []  # a reply cut off at max_tokens is billed too
    try:
        text, _ = llm.billed(chat, costs.append, SUPER, [{"role": "user", "content": task}], think=True,
                             max_tokens=8000)
        return parse(text, store), sum(costs)
    except (ValueError, KeyError, TypeError, AttributeError):
        return PremiseReport([], []), sum(costs)


def check_premises(store, question: str, chat=llm.chat) -> PremiseReport:
    """Super with thinking on (docs/reports/05-premise-check: premise resistance 8 to 11 of 20, about $0.01 a
    question)."""
    return run_check(store, question, chat)[0]


def report_text(report: PremiseReport, store) -> str:
    if not report.stale:
        return "No assumption was found outdated."
    return "\n".join(
        f"OUTDATED: {s['premise']}\n  old: {show(s['fact_id'], store)}\n  newer: {show(s['invalidated_by'], store)}"
        f"\n  why: {s['reason']}" for s in report.stale)


def answer(store, question: str, chat=llm.chat) -> Answer:
    """Super with thinking off; corrects a flagged premise first, then answers for the current situation."""
    report, cost = run_check(store, question, chat)
    log.info("Assumptions found: %d, outdated: %d", len(report.premises), len(report.stale),
             extra={"step": "S8", "ids": [s["fact_id"] for s in report.stale]})
    user = (f"[User memory, dated]\n{memory_text(store)}\n\n[Premise check]\n{report_text(report, store)}"
            f"\n\n[Question]\n{question}")
    messages = [{"role": "system", "content": ANSWER_NOTE}, {"role": "user", "content": user}]
    text, usage = chat(SUPER, messages, think=False, max_tokens=2000)
    return Answer(text, report, cost + llm.price(SUPER, usage))
