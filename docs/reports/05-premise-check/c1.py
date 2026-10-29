"""Candidate 1: does a dedicated premise check close our Premise Resistance gap? (STALE, arXiv 2605.06527, MIT/CC BY)

Usage: python3 -I c1.py <repo_root> <stage: diag|run> <cap_usd>
- Reuses the baseline pilot's saved per-session facts (docs/reports/01-baseline-pilot/k0_full20.jsonl): no re-extraction.
- the baseline pilot's change step passed Ultra's reasoning text to the answer step in 13 of 20 scenarios: 9 have no 'FINAL:' marker
  at all, 4 split on a 'FINAL:' quoted from the prompt. Cause of the missing markers not determined (PILOT did not record
  finish_reason; truncation at max_tokens=12000 is the suspect). Here the change step is re-run with 16000 tokens.
  `diag` (28 Oct) found the reasoning now arrives in `reasoning_content`, so `content` is the answer (after_mark).
- Conditions, on the same re-run memory: A = the baseline pilot's answer prompt unchanged; B = premise check (Super, thinking on),
  then the answer with ANSWER_NOTE in place of the baseline pilot's PREMISE_NOTE (two changes, by design: the premises are not checked
  twice). Judge = Ultra with STALE's judge prompt (via the baseline pilot's judge()). Every response is cached on disk.
"""
import hashlib
import json
import os
import re
import sys
import threading
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT, STAGE, CAP = sys.argv[1], sys.argv[2], float(sys.argv[3])
PILOT = f"{ROOT}/docs/reports/01-baseline-pilot/k0.py"
sys.argv = [PILOT, "", f"{ROOT}/data/stale-repo/STALE/Evaluation"]
ns: dict = {}
exec(compile(open(PILOT).read().split("\ndata = json.load")[0], PILOT, "exec"), ns)  # the baseline pilot's prompts and judge()
URL, SUPER, ULTRA, PRICE, DIMS = ns["URL"], ns["SUPER"], ns["ULTRA"], ns["PRICE"], ns["DIMS"]
CACHE, OUT = f"{ROOT}/cache/c1", f"{ROOT}/docs/reports/05-premise-check"
MARK = re.compile(r"^FINAL:[ \t]*", re.M)
lock, spent, calls = threading.Lock(), [0.0], []

PREMISE_PROMPT = (
    "List each assumption the question makes about the user's CURRENT situation. Give each a verdict: OUTDATED if a "
    "newer fact or a detected change contradicts it (implicit consequences count: a broken leg means no cycling); "
    "SAFE if the newest related fact supports it; UNRESOLVED if the memory says nothing about it. 'Not mentioned' is "
    "UNRESOLVED, never OUTDATED. For OUTDATED, quote the old fact and the newer fact with their dates. After "
    "thinking, output a line 'FINAL:' followed by only JSON: {\"assumptions\": [{\"assumption\": str, \"verdict\": "
    "\"SAFE\"|\"OUTDATED\"|\"UNRESOLVED\", \"old\": str, \"new\": str, \"reason\": str}]}")
ANSWER_NOTE = ("A premise check has been run on this question (below). If it marks an assumption OUTDATED, begin your "
               "reply by correcting it, citing the newer fact and its date, then answer for the user's current "
               "situation. Do not correct assumptions it marks SAFE or UNRESOLVED.")


def chat(model, messages, json_mode=False, max_tokens=6000, think=False):
    """the baseline pilot's chat() contract, (text, usd, prompt_tokens), plus a disk cache, finish_reason and the spend cap."""
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0,
            "chat_template_kwargs": {"enable_thinking": think}}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    raw = json.dumps(body, sort_keys=True).encode()
    path = f"{CACHE}/{hashlib.sha256(raw).hexdigest()}.json"
    live = not os.path.exists(path)
    if not live:
        d = json.load(open(path))
    else:
        with lock:
            if spent[0] >= CAP:
                raise SystemExit(f"cap ${CAP} reached at ${spent[0]:.3f}")
        req = urllib.request.Request(URL, raw, headers={
            "Authorization": "Bearer " + os.environ["NEBIUS_API_KEY"], "Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=900) as r:
            d = json.load(r)
        json.dump(d, open(path, "w"))
    u, choice = d.get("usage", {}), d["choices"][0]
    usd = u.get("prompt_tokens", 0) * PRICE[model][0] / 1e6 + u.get("completion_tokens", 0) * PRICE[model][1] / 1e6
    with lock:
        spent[0] += usd * live
        calls.append({"live": live, "model": model,
                      "in": u.get("prompt_tokens", 0), "out": u.get("completion_tokens", 0),
                      "usd": usd, "finish": choice.get("finish_reason"),
                      "has_reasoning_field": bool(choice["message"].get("reasoning_content"))})
    return choice["message"].get("content") or "", usd, u.get("prompt_tokens", 0)


def after_mark(text):
    """With thinking on, Token Factory returns the reasoning in `reasoning_content` (diag, 28 Oct): `content` is the
    answer, sometimes behind a FINAL: line. What follows the last such line, else all of it; None when empty."""
    hits = list(MARK.finditer(text))
    return (text[hits[-1].end():] if hits else text).strip() or None


def changes_of(facts):
    msg = f"[User facts, dated]\n{facts}\n\nTask: {ns['CHANGE_PROMPT']}"
    text, _, _ = chat(ULTRA, [{"role": "user", "content": msg}], max_tokens=16000, think=True)
    return after_mark(text)


def answer(memory, query, dim, premise=None):
    context = memory if premise is None else f"{memory}\n\n[Premise check]\n{premise}"
    s, u = ns["prompts"]("User Memory", context, query, dim)
    note = ns["PREMISE_NOTE"] if premise is None else ANSWER_NOTE
    return chat(SUPER, [{"role": "system", "content": s + " " + note}, {"role": "user", "content": u}])[0]


def premise_of(memory, query):
    msg = f"[User Memory]\n{memory}\n\n[Question]\n{query}\n\nTask: {PREMISE_PROMPT}"
    text, _, _ = chat(SUPER, [{"role": "user", "content": msg}], max_tokens=8000, think=True)
    return after_mark(text) or "(premise check produced no FINAL: section)"


def one(pair):
    row, item = pair
    facts = row["memory"].split("[All dated facts]\n", 1)[1]
    changes = changes_of(facts)
    memory = f"[Detected changes: older facts that are NO LONGER TRUE]\n{changes or ''}\n\n[All dated facts]\n{facts}"
    q = item["probing_queries"]
    a = {d: answer(memory, q[d], d) for d in DIMS}
    prem = {d: premise_of(memory, q[d]) for d in DIMS}
    b = {d: answer(memory, q[d], d, prem[d]) for d in DIMS}
    return {"uid": row["uid"], "type": row["type"], "changes": changes, "premise": prem, "answers_a": a,
            "answers_b": b, "k0": row["result"]["ours"], "a": ns["judge"](item, a)[0], "b": ns["judge"](item, b)[0]}


ns["chat"] = chat  # the baseline pilot's judge() calls chat() through its own globals
os.makedirs(CACHE, exist_ok=True)
rows = [json.loads(line) for line in open(f"{ROOT}/docs/reports/01-baseline-pilot/k0_full20.jsonl")]
items = {x["uid"]: x for x in json.load(open(f"{ROOT}/data/k0_20_MAIN.json"))}
def projected(rows):
    """Projected live spend: chars/4 tokens; report 04's mean change output (11.2K); premise output 4K (a guess)."""
    t = sum(len(r["memory"].split("[All dated facts]\n", 1)[1]) / 4 for r in rows)
    n = len(rows)
    ultra = (t + n * 300) * 1.0 + n * 11200 * 3.0 + 2 * n * (3000 * 1.0 + 800 * 3.0)
    sup = 9 * (t + n * 1500) * 0.30 + 3 * n * (500 + 4000 + 500) * 0.90
    return (ultra + sup) / 1e6


if STAGE == "diag":
    facts = rows[1]["memory"].split("[All dated facts]\n", 1)[1]
    ch = changes_of(facts)
    print("changes:", json.dumps(calls[-1]), "| marker:", ch is not None, "|", (ch or "")[:300])
    mem = f"[Detected changes: older facts that are NO LONGER TRUE]\n{ch or ''}\n\n[All dated facts]\n{facts}"
    pr = premise_of(mem, items[rows[1]["uid"]]["probing_queries"]["dim2_query"])
    print("premise:", json.dumps(calls[-1]), "| marker:", not pr.startswith("(premise check"), "|", pr[:300])
else:
    print(f"projected ${projected(rows):.2f}, cap ${CAP} (in-flight calls may pass the cap by about $0.25)")
    if projected(rows) > CAP:
        raise SystemExit("projection above cap: not running")
    if not os.environ.get("C1_DIAG_OK"):
        raise SystemExit("run `diag` first; set C1_DIAG_OK=1 only if both of its calls found the FINAL: marker")
    with ThreadPoolExecutor(5) as ex, open(f"{OUT}/c1.jsonl", "w") as f:
        for r in ex.map(one, [(r, items[r["uid"]]) for r in rows]):
            f.write(json.dumps(r) + "\n")
            print(r["uid"][:8], r["type"], "k0", r["k0"], "a", r["a"], "b", r["b"], flush=True)
    json.dump(calls, open(f"{OUT}/c1-calls.json", "w"))
    res = [json.loads(line) for line in open(f"{OUT}/c1.jsonl")]
    print("empty change lists:", sum(r["changes"] is None for r in res), "of", len(res))
    print("finish_reason=length:", sum(c["finish"] == "length" for c in calls), "of", len(calls), "calls")
    h2h = {r["uid"] for i, r in enumerate(rows) if i in (0, 1, 2, 3, 4, 10, 11, 12, 13)}  # report 04's 9 vs CUPMem
    for cond in ("k0", "a", "b"):
        print(cond, "SR/PR/IPA on 20", [sum(r[cond][d] for r in res) for d in DIMS],
              "| on report 04's 9", [sum(r[cond][d] for r in res if r["uid"] in h2h) for d in DIMS])
print(f"live spend ${spent[0]:.3f}; all calls at list price ${sum(c['usd'] for c in calls):.3f}")
