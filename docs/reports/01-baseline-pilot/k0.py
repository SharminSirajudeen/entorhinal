"""Baseline pilot, a crude kill test on STALE (arXiv 2605.06527, MIT; data CC BY 4.0).

Prompts and haystack format reproduce STALE/Evaluation/run_target_model.py and judge_prompts.py (MIT) verbatim.
Conditions: baseline = Lightning reads full history; crude ours = Lightning writes a dated current-state memory once,
Super answers from it with a premise check. Judge = Ultra with STALE's all-in-one judge prompt.
"""
import json
import os
import random
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

URL = "https://api.tokenfactory.nebius.com/v1/chat/completions"
LIGHT = "nvidia/Nemotron-3_5-Lightning"
SUPER = "nvidia/nemotron-3-super-120b-a12b"
ULTRA = "nvidia/Nemotron-3-Ultra-550b-a55b"
PRICE = {LIGHT: (0.06, 0.24), SUPER: (0.30, 0.90), ULTRA: (1.0, 3.0)}  # $/1M in, out (mastra/models.dev, 28 Oct)
DIMS = ("dim1_query", "dim2_query", "dim3_query")
JUDGE_SYS = open(sys.argv[2] + "/judge_prompts.py").read().split('"""')[1]
MEMORY_SYS = ("You maintain a user's long-term memory. Read the conversation history and write the user's CURRENT "
              "state as a dated list of facts about the user. If something said later changes or makes an earlier "
              "fact untrue (even implicitly), mark the earlier fact STALE and say which later message changed it "
              "and when. Be concise.")
PREMISE_NOTE = ("Step 1: list every assumption the question makes about the user. Step 2: for each assumption, "
                "find the most recent related fact in the user memory. Facts are dated and later facts override "
                "earlier ones, including their implicit consequences (for example, a broken leg means no cycling). "
                "Step 3: if any assumption is outdated, begin your reply by correcting it and citing the newer fact "
                "and its date, then answer for the user's current situation.")


def chat(model, messages, json_mode=False, max_tokens=6000, think=False):
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0,
            "chat_template_kwargs": {"enable_thinking": think}}  # Nemotron otherwise puts its thinking in content
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    req = urllib.request.Request(URL, json.dumps(body).encode(), headers={
        "Authorization": "Bearer " + os.environ["NEBIUS_API_KEY"], "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.load(r)
    u = d.get("usage", {})
    pin, pout = PRICE[model]
    cost = u.get("prompt_tokens", 0) * pin / 1e6 + u.get("completion_tokens", 0) * pout / 1e6
    return (d["choices"][0]["message"].get("content") or ""), cost, u.get("prompt_tokens", 0)


FACT_PROMPT = ("List every fact the USER reveals about themselves in this session (their situation, work, health, "
               "location, possessions, plans, habits, relationships). One short line per fact, prefixed with the "
               "session time. Output NONE if there are none. Output only the list.")


CHANGE_PROMPT = ("Find every older fact that a LATER fact changes or makes untrue, including implicit consequences "
                 "(a new job schedule replaces the old schedule; a name change makes documents in the old name "
                 "outdated; a broken leg stops cycling). Output one line per change: 'OLD (date) -> NEW (date): "
                 "why'. Ignore additions that contradict nothing. After thinking, output a line 'FINAL:' followed "
                 "by only those lines.")


def per_session_facts(item):
    ts, jobs = item.get("timestamps") or [], []
    for i, session in enumerate(item["haystack_session"]):
        if session:
            t = ts[i] if i < len(ts) else "unknown time"
            text = "\n".join(f"{'User' if x['role'] == 'user' else 'Assistant'}: {x['content']}" for x in session)
            jobs.append([{"role": "user", "content": f"[Session time: {t}]\n{text}\n\nTask: {FACT_PROMPT}"}])
    with ThreadPoolExecutor(10) as ex:
        outs = list(ex.map(lambda m: chat(LIGHT, m, max_tokens=1500), jobs))
    lines = [o[0].strip() for o in outs if o[0].strip() and o[0].strip().upper() != "NONE"]
    return "\n".join(lines), sum(o[1] for o in outs)


def history(item):
    out, ts = "", item.get("timestamps") or []
    for i, session in enumerate(item["haystack_session"]):
        if not session:
            continue
        t = f" [Time: {ts[i]}]" if i < len(ts) else ""
        out += f"\n=== Session {i + 1}{t} ===\n"
        for turn in session:
            out += f"{'User' if turn['role'] == 'user' else 'Assistant'}: {turn['content']}\n"
    return out


def prompts(context_label, context, query, dim):
    if dim == "dim3_query":
        sys_p = ("You are a helpful assistant. Review the following conversation history "
                 "with the user, then respond to the user's latest query directly.")
        return sys_p, f"[{context_label}]\n{context}\n\n[Latest Query]\n{query}"
    sys_p = ("You are a helpful assistant. Review the following conversation history "
             "with the user, then accurately answer the question.")
    return sys_p, f"[{context_label}]\n{context}\n\n[Question]\n{query}"


def judge(item, answers):
    q = item["probing_queries"]
    user = f"""
[Ground Truth Context]
- M_old: "{item.get('M_old') or item.get('old_info')}"
- M_new: "{item['M_new']}"
- Hidden Logic: {item['explanation']}

--------------------------------------------------
[Dimension 1: Explicit Probing]
Question 1: {q['dim1_query']}
Target Model Response 1: {answers['dim1_query']}

--------------------------------------------------
[Dimension 2: Adversarial Robustness]
Question 2: {q['dim2_query']}
Target Model Response 2: {answers['dim2_query']}

--------------------------------------------------
[Dimension 3: Implicit Task]
Question 3: {q['dim3_query']}
Target Model Response 3: {answers['dim3_query']}
"""
    text, cost, _ = chat(ULTRA, [{"role": "system", "content": JUDGE_SYS}, {"role": "user", "content": user}], True)
    m = re.search(r"\{.*\}", text, re.S)
    v = json.loads(m.group(0)) if m else {}
    return {d: bool(v.get(f"dim{d[3]}_eval", {}).get("pass")) for d in DIMS}, cost


def run(item):
    h, q, cost, res = history(item), item["probing_queries"], 0.0, {}
    base = {}
    for d in DIMS:
        s, u = prompts("Conversation History", h, q[d], d)
        base[d], c, n_in = chat(LIGHT, [{"role": "system", "content": s}, {"role": "user", "content": u}])
        cost += c
    memory, c = per_session_facts(item)
    cost += c
    change_msg = f"[User facts, dated]\n{memory}\n\nTask: {CHANGE_PROMPT}"
    changes, c, _ = chat(ULTRA, [{"role": "user", "content": change_msg}],
                         max_tokens=12000, think=True)
    changes = changes.split("FINAL:")[-1].strip()
    cost += c
    memory = f"[Detected changes: older facts that are NO LONGER TRUE]\n{changes}\n\n[All dated facts]\n{memory}"
    ours = {}
    for d in DIMS:
        s, u = prompts("User Memory", memory, q[d], d)
        msgs = [{"role": "system", "content": s + " " + PREMISE_NOTE}, {"role": "user", "content": u}]
        ours[d], c, _ = chat(SUPER, msgs)
        cost += c
    for name, ans in (("baseline", base), ("ours", ours)):
        res[name], c = judge(item, ans)
        cost += c
    return {"uid": item["uid"], "type": item["type"], "history_tokens": n_in, "result": res, "cost": cost,
            "memory": memory, "answers": {"baseline": base, "ours": ours}}


data = json.load(open(sys.argv[1]))
rng = random.Random(7)
types = sorted({x["type"] for x in data})
pick = [x for t in types for x in rng.sample([y for y in data if y["type"] == t], int(sys.argv[3]))]
with ThreadPoolExecutor(5) as ex, open(sys.argv[4], "w") as f:
    for r in ex.map(run, pick):
        f.write(json.dumps(r) + "\n")
        f.flush()
        print(r["uid"], r["type"], "tok", r["history_tokens"], "base", r["result"]["baseline"], "ours",
              r["result"]["ours"], f"${r['cost']:.3f}", flush=True)
