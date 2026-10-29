"""Run a condition over a STALE sample and judge it. Reads/prompts follow docs/reports/01-baseline-pilot/k0.py, which
reproduces STALE/Evaluation/run_target_model.py (MIT).

    python -m bench.run --condition baseline|baseline-super|baseline-ultra|ours --n 10 --seed 7 --types T1,T2 --cap 3.0

Writes results/<run>.jsonl (one EvalRow per answer) and results/<run>.md. Prints the projected cost first and refuses
above --cap; while running, refuses any call once the actual spend has reached --cap (the projection is only an
estimate: a pilot measured it short). A paid run needs NEBIUS_API_KEY; the suite only ever
passes a `chat` with scripted test replies.
"""
import argparse
import json
import sys
import threading
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from functools import partial
from pathlib import Path

from bench.judge import DIMS, judge
from bench.stale import load_stale
from life import llm
from life.constants import LIGHTNING, PRICES, S6_MODEL, SUPER, ULTRA
from life.store import Store
from life.types import EvalRow, Instance, Session

CHARS_PER_TOKEN = 4  # estimate for the projection only
OUT_TOKENS = 4000  # the max_tokens every call is allowed; the projection prices every call at it
JUDGE_PROMPT_TOKENS = 1000  # the judge's system prompt and question text, an estimate
# the whole-history baselines: each model reads every session, STALE's own setup. The larger models get their stronger
# setting, reasoning on, with room to reason, so a reply cut off at its token cap does not count against them
REASON = {"think": True, "max_tokens": 16000}
BASELINES = {"baseline": (LIGHTNING, {}), "baseline-super": (SUPER, REASON), "baseline-ultra": (ULTRA, REASON)}
WORKERS = 5
HISTORY_PROMPT = "You are a helpful assistant. Review the following conversation history with the user, then "

CONDITIONS = {"ours": S6_MODEL, "ours-ultra": ULTRA}  # the change-judge model per condition

def history(inst: Instance) -> str:
    out = ""
    for i, session in enumerate(inst.haystack_session):
        if not session:
            continue
        t = f" [Time: {inst.timestamps[i]}]" if i < len(inst.timestamps) else ""
        out += f"\n=== Session {i + 1}{t} ===\n"
        for turn in session:
            out += f"{'User' if turn['role'] == 'user' else 'Assistant'}: {turn['content']}\n"
    return out


def prompts(context: str, query: str, dim: str) -> list[dict]:
    """STALE's two target prompts: dim3 is a task, dim1 and dim2 are questions."""
    if dim == DIMS[2]:
        system = HISTORY_PROMPT + "respond to the user's latest query directly."
        user = f"[Conversation History]\n{context}\n\n[Latest Query]\n{query}"
    else:
        system = HISTORY_PROMPT + "accurately answer the question."
        user = f"[Conversation History]\n{context}\n\n[Question]\n{query}"
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def reply_with_room(chat, model: str, messages: list[dict], settings: dict) -> str:
    """The answer; a reply cut at its token cap is tried once more with twice the room, and a second cut is no
    answer (scored as wrong) rather than an error that stops the run."""
    try:
        return chat(model, messages, **settings)[0]
    except llm.Truncated:
        roomier = {**settings, "max_tokens": 2 * settings.get("max_tokens", OUT_TOKENS)}
        try:
            return chat(model, messages, **roomier)[0]
        except llm.Truncated:
            return ""


def baseline(inst: Instance, chat=llm.chat, condition: str = "baseline") -> dict:
    """{dim: (answer, cost)}: the condition's model reads the whole history, STALE's own baseline. A dimension's
    cost is every call it took, a cut-off one included."""
    model, settings = BASELINES[condition]
    h, out = history(inst), {}
    for d in DIMS:
        metered, spent = meter(chat)
        out[d] = (reply_with_room(metered, model, prompts(h, inst.probing_queries[d], d), settings), sum(spent))
    return out


def meter(chat):
    """(a chat that adds each call's price to `spent`, spent): for steps that return no cost of their own."""
    spent = []
    return partial(llm.billed, chat, spent.append), spent


class CapReached(RuntimeError):
    """Raised by `capped` instead of a call, once the run's actual spend has reached --cap."""


def capped(chat, cap: float):
    """chat that refuses every call once the calls made so far cost `cap` or more (list prices, summed across the
    worker threads). Calls already in flight finish, so a run passes the cap by at most WORKERS calls."""
    spent, lock = [0.0], threading.Lock()

    def add(usd):
        with lock:
            spent[0] += usd

    def call(model, messages, **kw):
        with lock:
            if spent[0] >= cap:
                raise CapReached(f"actual spend ${spent[0]:.4f} reached the ${cap:.2f} cap")
        return llm.billed(chat, add, model, messages, **kw)

    return call


def ours(inst: Instance, ingest, answer, chat=llm.chat) -> dict:
    """{dim: (answer, cost)}: S7 ingest every session in time order into a fresh Store, then S9 answer each query.
    A dimension's cost is its Answer.cost_usd plus a third of the metered ingest spend."""
    store, out = Store(":memory:"), {}
    metered, spent = meter(chat)
    for i, turns in enumerate(inst.haystack_session):
        if turns:
            ingest(store, Session(i, inst.timestamps[i], turns), metered)
    for d in DIMS:
        a = answer(store, inst.probing_queries[d], chat)
        out[d] = (a.text, a.cost_usd + sum(spent) / len(DIMS))
    return out


def judged(inst: Instance, answers: dict, chat) -> tuple[dict, float]:
    """The judge on {dim: (answer, cost)}: ({dim: bool}, the judge call's cost)."""
    metered, spent = meter(chat)
    return judge(inst, {d: answers[d][0] for d in DIMS}, metered), sum(spent)


def project(instances: list[Instance], condition: str) -> float:
    """Estimated USD at chars/4, not a bound (`capped` enforces the cap on actual spend). A baseline: three reads of
    the history at its model's rate, each reply at its full token allowance. ours: one read at the condition's S6
    model's rate and a full-length reply per session plus three answers. Plus one Ultra judge call each."""
    base = condition in BASELINES
    model, settings = BASELINES[condition] if base else (CONDITIONS[condition], {})
    out_tokens = settings.get("max_tokens", OUT_TOKENS)
    total = 0.0
    for inst in instances:
        tokens = len(history(inst)) / CHARS_PER_TOKEN
        sessions = sum(1 for s in inst.haystack_session if s)
        reads, replies = (3, 3) if base else (1, 3 + sessions)
        total += (reads * tokens * PRICES[model][0] + replies * out_tokens * PRICES[model][2]
                  + (3 * OUT_TOKENS + JUDGE_PROMPT_TOKENS) * PRICES[ULTRA][0] + OUT_TOKENS * PRICES[ULTRA][2]) / 1e6
    return total


def rows_for(inst: Instance, condition: str, answers: dict, verdict: dict, judge_cost: float) -> list[EvalRow]:
    """One row per dimension; the judge's single call is split evenly over the three."""
    return [EvalRow(inst.uid, inst.type, d, condition, answers[d][0], verdict[d], ULTRA,
                    answers[d][1] + judge_cost / len(DIMS)) for d in DIMS]


def table(rows: list[EvalRow]) -> str:
    passed, seen = defaultdict(int), defaultdict(int)
    for r in rows:
        for key in ((r.type, r.dim), ("all", r.dim)):
            passed[key] += r.correct
            seen[key] += 1
    lines = ["| type | " + " | ".join(DIMS) + " |", "|---|" + "---|" * len(DIMS)]
    for t in sorted({r.type for r in rows}) + ["all"]:
        cells = [f"{passed[t, d]}/{seen[t, d]} ({100 * passed[t, d] / seen[t, d]:.0f}%)" for d in DIMS]
        lines.append(f"| {t} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def report(rows: list[EvalRow], condition: str, projected: float) -> str:
    cost = sum(r.cost_usd for r in rows)
    return (f"# {condition}: {len({r.uid for r in rows})} instances, {len(rows)} answers\n\n"
            f"- judge model: {ULTRA} (STALE's all-in-one judge prompt)\n"
            f"- cost: ${cost:.4f} (projected ${projected:.4f})\n\n{table(rows)}\n")


def run(instances: list[Instance], condition: str, answer_fn, chat, out_dir: str, name: str) -> list[EvalRow]:
    """Answer and judge every instance (WORKERS at a time); each instance's rows reach the .jsonl as it finishes."""
    def one(inst):
        answers = answer_fn(inst)
        verdict, judge_cost = judged(inst, answers, chat)
        return rows_for(inst, condition, answers, verdict, judge_cost)

    Path(out_dir).mkdir(parents=True, exist_ok=True)
    rows = []
    with ThreadPoolExecutor(WORKERS) as ex, open(Path(out_dir) / f"{name}.jsonl", "w") as f:
        for batch in ex.map(one, instances):
            rows += batch
            f.writelines(json.dumps(asdict(r)) + "\n" for r in batch)
            f.flush()
    return rows


def main(argv: list[str], chat=partial(llm.chat, record=True), ingest=None, answer=None) -> int:
    p = argparse.ArgumentParser(prog="bench.run")
    p.add_argument("--condition", choices=[*BASELINES, *CONDITIONS], required=True)
    p.add_argument("--n", type=int, required=True, help="instances per type")
    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--types", default=None, help="comma list, e.g. T1,T2 (default: all)")
    p.add_argument("--cap", type=float, required=True, help="refuse to run if the projected cost is above this (USD)")
    p.add_argument("--data", default="data/T1_T2_400_FULL.json")
    p.add_argument("--out", default="results")
    a = p.parse_args(argv)
    instances = load_stale(a.data, a.n, a.seed, a.types.split(",") if a.types else None)
    projected = project(instances, a.condition)
    print(f"{len(instances)} instances, projected cost ${projected:.4f}, cap ${a.cap:.2f}")
    if projected > a.cap:
        print("refused: projected cost is above the cap", file=sys.stderr)
        return 2
    chat = capped(chat, a.cap)
    if a.condition in BASELINES:
        def fn(inst):
            return baseline(inst, chat, a.condition)
    else:
        if ingest is None:  # imported here so `baseline` needs neither
            from life.memory import ingest
            from life.query import answer

        def fn(inst):
            return ours(inst, partial(ingest, s6_model=CONDITIONS[a.condition]), answer, chat)
    name = f"{a.condition}-n{a.n}-seed{a.seed}-{(a.types or 'all').replace(',', '')}"
    try:
        rows = run(instances, a.condition, fn, chat, a.out, name)
    except CapReached as e:
        print(f"stopped: {e}; finished instances are in {a.out}/{name}.jsonl", file=sys.stderr)
        return 3
    (Path(a.out) / f"{name}.md").write_text(report(rows, a.condition, projected))
    print(f"wrote {a.out}/{name}.jsonl and .md")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
