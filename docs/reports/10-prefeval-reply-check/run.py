"""Report 10: PrefEval explicit preferences at 300 turns, five answers per item on one model and one judge.
The pass rule was fixed before any paid call.

PrefEval (Zhao et al., ICLR 2025; code CC BY-NC 4.0) is read at run time from $PREFEVAL_DIR, its text included (the
reminder, the RAG header, the judge prompts), and is never committed. Live spend is metered at llm.post and the run
stops starting items once it reaches the cap.

Usage: PREFEVAL_DIR=... LIFE_CACHE=... python run.py <per_topic> <cap> <out.jsonl> [limit]  (from the repo root)
"""
import ast
import json
import os
import random
import re
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache, partial
from pathlib import Path

from life import llm, memory, query
from life.constants import LIGHTNING, SUPER, ULTRA
from life.store import Store
from life.types import Session

SRC = Path(os.environ["PREFEVAL_DIR"])
TURNS = 300  # PrefEval's longest setting, the one in the paper's Table 7
SEED = 7
SUFFIX = " (Please respond within 300 words.)"  # PrefEval: max_gen_tokens 300 in config.yaml
ANSWERS = ("zero", "remind", "rag", "ours_draft", "ours")
CHECK = (
    "Below is what the user has told you (dated facts, preferences, rules) and a draft reply to the user's question. "
    "List every place where the draft contradicts, ignores or breaks something the user told you, including a "
    'preference or a rule about what to avoid. Reply with JSON {"violations": [{"fact_id": ..., "problem": one '
    'sentence}]}, with [] if the draft respects everything.')
S4_RULES = "habits, relationships, preferences, dislikes, and standing rules about what to do or avoid)"

spent, lock = [0.0], threading.Lock()
_post = llm.post


def metered(req):
    d = _post(req)
    with lock:
        spent[0] += llm.price(json.loads(req.data)["model"], d.get("usage", {}))
    return d


llm.post = metered  # every live call passes here; a local cache hit does not
chat = partial(llm.chat, record=True)


def source_text():
    """PrefEval's own strings, read from its files at run time."""
    common = (SRC / "utils/common_utils.py").read_text()
    remind = ast.literal_eval(re.search(r"^REMINDER = (\".*\")$", common, re.M).group(1))
    fn = next(n for n in ast.parse((SRC / "utils/explicit_utils.py").read_text()).body
              if isinstance(n, ast.FunctionDef) and n.name == "convert_top_k_sentences_to_msg")
    judge_sys = re.search(r'system_prompt = """(.*?)"""',
                          (SRC / "generation_task/llm_based_evaluation_errortypes.py").read_text(), re.S).group(1)
    checks = {k: (SRC / f"error_type/check_{k}.txt").read_text()
              for k in ("acknowledge", "violation", "helpful")}
    return remind, fn.body[0].value.value, fn.body[2].value.value, judge_sys, checks


REMIND, RAG_HEAD, RAG_TAIL, JUDGE_SYS, CHECKS = source_text()
assert memory.FACT_PROMPT.count("habits, relationships)") == 1, "extraction prompt changed; the rules edit no longer applies"
memory.FACT_PROMPT = memory.FACT_PROMPT.replace("habits, relationships)", S4_RULES)  # plan step 1, prototype


def filler():
    """PrefEval's inter-turns: its conversations in order, cut at 2 * TURNS messages, ending on the assistant."""
    sessions, msgs = [], []
    for c in json.loads((SRC / "benchmark_dataset/filtered_inter_turns.json").read_text()):
        turns = [{"role": m["role"], "content": m["content"]} for m in c["conversation"][: 2 * TURNS - len(msgs)]]
        if turns:
            sessions.append(turns)
            msgs += turns
    assert len(msgs) == 2 * TURNS and msgs[-1]["role"] == "assistant"
    return msgs, sessions


@lru_cache(maxsize=None)
def rag_files(topic):
    d = SRC / "benchmark_dataset/rag_retrieval/simcse_explicit_pref"
    return (json.loads((d / f"{topic}_overall300_topk_history.json").read_text()),
            json.loads((d / f"msg_index_{topic}_overall300_topk_history.json").read_text()))


def rag_ok(topic):
    try:
        rag_files(topic)
        return True
    except ValueError:  # entertain_games: PrefEval's file is cut at 240,253 bytes upstream (measured 29 Oct)
        return False


def items(per_topic):
    """Seeded items per topic; a topic whose RAG file does not parse is skipped for every answer, and said so. Its
    draw still happens, so the other topics keep their items. The order is shuffled: a cap stop leaves a random
    subset, not the last topics."""
    rng, out, skipped = random.Random(SEED), [], []
    for p in sorted((SRC / "benchmark_dataset/explicit_preference").glob("*.json")):
        rows = json.loads(p.read_text())
        picked = [(p.stem, i, rows[i]) for i in sorted(rng.sample(range(len(rows)), per_topic))]
        out, skipped = (out + picked, skipped) if rag_ok(p.stem) else (out, skipped + [p.stem])
    print(f"skipped topics (RAG file does not parse): {skipped}", file=sys.stderr)
    random.Random(SEED).shuffle(out)
    return out


def rag_prefix(topic, i, pref, ack):
    """PrefEval's RAG top-5, from its stored SimCSE scores over the preference, its reply and the inter-turns."""
    scores, index = rag_files(topic)
    top = sorted(scores[i]["sentence_scores"][: 2 + 2 * TURNS], key=lambda x: x[1], reverse=True)[:5]
    lines = ["User: " + pref if k == 0 else "Assistant: " + ack if k == 1 else index[str(k)] for k, _ in top]
    return RAG_HEAD + "".join(f"exchange {n}. {s}\n" for n, s in enumerate(lines, 1)) + RAG_TAIL


def say(model, messages, **kw):
    """A reply, or "" when it is cut at max_tokens (billed, and counted as an answer that failed)."""
    try:
        return chat(model, messages, **kw)[0]
    except llm.Truncated:
        return ""


def reply_check(store, q, draft):
    """Reply-check prototype: Lightning reads the draft against the memory; a violation gets one rewrite by Super."""
    mem = query.memory_text(store)
    found = memory._rows(say(LIGHTNING, [{"role": "user", "content": (
        f"[User memory]\n{mem}\n\n[Question]\n{q}\n\n[Draft reply]\n{draft}\n\nTask: {CHECK}")}],
        json_mode=True, max_tokens=1500), "violations")
    if not found:
        return draft, []
    problems = "\n".join(f"- {r.get('problem')} {query.show(r.get('fact_id'), store)}" for r in found)
    return say(SUPER, [{"role": "user", "content": (
        f"[User memory, dated]\n{mem}\n\n[Question]\n{q}\n\n[Draft reply]\n{draft}\n\n[Problems in the draft]\n"
        f"{problems}\n\nRewrite the reply so it respects everything the user told you. Reply with the answer only.")}],
        max_tokens=2000), found


def ours(pref, ack, q, fill_sessions):
    """The app's write path over the preference session and the inter-turns, then the premise check and the answer, then
    the reply check."""
    with tempfile.TemporaryDirectory() as d:
        store = Store(f"{d}/memory.db")
        for n, turns in enumerate([[{"role": "user", "content": pref}, {"role": "assistant", "content": ack}]]
                                  + fill_sessions):
            memory.ingest(store, Session(n, f"2026-01-{n + 1:02d} 09:00", turns), chat)
        draft = query.answer(store, q, chat).text
        final, found = reply_check(store, q, draft)
        return draft, final, found, len(store.timeline())


def judge_one(pref, q, resp):
    """PrefEval's four checks and its accuracy rule (get_preference_following_accuracy_generation_task.py)."""
    def ask(text):
        return say(ULTRA, [{"role": "system", "content": JUDGE_SYS}, {"role": "user", "content": text}],
                   max_tokens=1000)

    def tag(text, name):
        m = re.search(rf"<{name}>(.*?)</{name}>", text, re.S)
        return m.group(1).strip() if m else ""

    def fill(name):
        return CHECKS[name].replace("{preference}", pref).replace("{question}", q).replace("{end_generation}", resp)

    ack = "yes" in tag(ask(fill("acknowledge")), "answer").lower()
    vio = "yes" in tag(ask(fill("violation")), "answer").lower()
    unhelpful = "no" in tag(ask(fill("helpful")), "answer").lower()
    # PrefEval's rule (inconsistent, hallucinated or unaware violation, or unhelpful) reduces to this: every violation
    # is wrong whatever the acknowledgement, so its hallucination check never changes a verdict and is not run
    return {"ack": ack, "violate": vio, "unhelpful": unhelpful, "correct": not (vio or unhelpful)}


def run_item(item, fill_msgs, fill_sessions, cap):
    topic, i, row = item
    if spent[0] >= cap:
        return None
    pref, q = row["preference"], row["question"]
    system = {"role": "system", "content": "You are a helpful assistant."}  # PrefEval config.yaml
    ack = say(SUPER, [system, {"role": "user", "content": pref}], think=True, max_tokens=4000)
    head = [system, {"role": "user", "content": pref}, {"role": "assistant", "content": ack}] + fill_msgs

    def full(text):
        return say(SUPER, head + [{"role": "user", "content": text}], think=True, max_tokens=8000)

    resp = {"zero": full(q + SUFFIX), "remind": full(q + REMIND + SUFFIX),
            "rag": full(rag_prefix(topic, i, pref, ack) + q + SUFFIX)}
    resp["ours_draft"], resp["ours"], found, n_facts = ours(pref, ack, q + SUFFIX, fill_sessions)
    verdicts = {k: judge_one(pref, q, r) for k, r in resp.items()}
    return {"topic": topic, "index": i, "facts": n_facts, "caught": len(found),
            "empty": [k for k, r in resp.items() if not r], "verdicts": verdicts, "responses": resp, "check": found,
            "spent_after": round(spent[0], 4)}


def main(per_topic, cap, out_path, limit=None):
    fill_msgs, fill_sessions = filler()
    todo, cap = items(int(per_topic))[: int(limit) if limit else None], float(cap)
    with ThreadPoolExecutor(4) as pool, open(out_path, "a") as out:
        for row in pool.map(lambda it: run_item(it, fill_msgs, fill_sessions, cap), todo):
            if row:
                out.write(json.dumps(row) + "\n")
                out.flush()
    rows = [json.loads(x) for x in open(out_path)]
    print(f"items={len(rows)} of {len(todo)} spent_this_run=${spent[0]:.4f}")
    for k in ANSWERS:
        print(f"{k}: {sum(r['verdicts'][k]['correct'] for r in rows)}/{len(rows)}")


if __name__ == "__main__":
    main(*sys.argv[1:5])
