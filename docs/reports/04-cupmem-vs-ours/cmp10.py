"""CUPMem vs ours on the same 10 STALE scenarios, both on Nemotron, both graded by Ultra with STALE's judge prompt.

Usage: python3 -I cmp10.py <stale_dir> <k0.py> <out.jsonl>
- CUPMem answers come from its run folders (cup_runs/<first run>, cup_runs10/idx_N/*/summary.json).
- Ours is re-run here with per-step token logging (the baseline pilot logged only dollars), using the baseline pilot's prompts unchanged.
"""
import glob
import json
import os
import re
import sys
import urllib.request
from concurrent.futures import ThreadPoolExecutor

STALE, PILOT, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
src = open(PILOT).read().split("\ndata = json.load")[0]
sys.argv = [PILOT, "", STALE + "/repo/STALE/Evaluation"]
ns: dict = {}
exec(compile(src, PILOT, "exec"), ns)  # the baseline pilot's prompts, judge text, history(), prompts(); its chat() is replaced below
URL, LIGHT, SUPER, ULTRA, PRICE = ns["URL"], ns["LIGHT"], ns["SUPER"], ns["ULTRA"], ns["PRICE"]
INDICES = [0, 1, 2, 3, 4, 10, 11, 12, 13, 14]


def chat(model, messages, json_mode=False, max_tokens=6000, think=False, log=None, step=""):
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0,
            "chat_template_kwargs": {"enable_thinking": think}}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    req = urllib.request.Request(URL, json.dumps(body).encode(), headers={
        "Authorization": "Bearer " + os.environ["NEBIUS_API_KEY"], "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        d = json.load(r)
    u = d.get("usage", {})
    pin, pout = PRICE[model]
    rec = {"step": step, "model": model, "in": u.get("prompt_tokens", 0), "out": u.get("completion_tokens", 0)}
    rec["usd"] = rec["in"] * pin / 1e6 + rec["out"] * pout / 1e6
    if log is not None:
        log.append(rec)
    return d["choices"][0]["message"].get("content") or ""


def judge(item, answers, log):
    q = item["probing_queries"]
    text = chat(ULTRA, [{"role": "system", "content": ns["JUDGE_SYS"]},
                        {"role": "user", "content": judge_user(item, answers)}], True, log=log, step="judge")
    m = re.search(r"\{.*\}", text, re.S)
    v = json.loads(m.group(0)) if m else {}
    return {dm: bool(v.get(f"dim{dm[3]}_eval", {}).get("pass")) for dm in ns["DIMS"]}, q


def judge_user(item, a):
    q = item["probing_queries"]
    return f"""
[Ground Truth Context]
- M_old: "{item.get('M_old') or item.get('old_info')}"
- M_new: "{item['M_new']}"
- Hidden Logic: {item['explanation']}

--------------------------------------------------
[Dimension 1: Explicit Probing]
Question 1: {q['dim1_query']}
Target Model Response 1: {a['dim1_query']}

--------------------------------------------------
[Dimension 2: Adversarial Robustness]
Question 2: {q['dim2_query']}
Target Model Response 2: {a['dim2_query']}

--------------------------------------------------
[Dimension 3: Implicit Task]
Question 3: {q['dim3_query']}
Target Model Response 3: {a['dim3_query']}
"""


def ours(item, log):
    ts, jobs = item.get("timestamps") or [], []
    for i, session in enumerate(item["haystack_session"]):
        if session:
            t = ts[i] if i < len(ts) else "unknown time"
            text = "\n".join(f"{'User' if x['role'] == 'user' else 'Assistant'}: {x['content']}" for x in session)
            jobs.append([{"role": "user", "content": f"[Session time: {t}]\n{text}\n\nTask: {ns['FACT_PROMPT']}"}])
    with ThreadPoolExecutor(10) as ex:
        outs = list(ex.map(lambda m: chat(LIGHT, m, max_tokens=1500, log=log, step="extract"), jobs))
    facts = "\n".join(o.strip() for o in outs if o.strip() and o.strip().upper() != "NONE")
    msg = f"[User facts, dated]\n{facts}\n\nTask: {ns['CHANGE_PROMPT']}"
    changes = chat(ULTRA, [{"role": "user", "content": msg}], max_tokens=12000, think=True, log=log, step="changes")
    changes = changes.split("FINAL:")[-1].strip()
    memory = f"[Detected changes: older facts that are NO LONGER TRUE]\n{changes}\n\n[All dated facts]\n{facts}"
    ans = {}
    for dm in ns["DIMS"]:
        s, u = ns["prompts"]("User Memory", memory, item["probing_queries"][dm], dm)
        ans[dm] = chat(SUPER, [{"role": "system", "content": s + " " + ns["PREMISE_NOTE"]},
                               {"role": "user", "content": u}], log=log, step="answer")
    return ans


def cup_summary(idx):
    paths = glob.glob(f"{STALE}/cup_runs10/idx_{idx}/*/summary.json") if idx else []
    if idx == 0:
        paths = sorted(glob.glob(f"{STALE}/cup_runs/*/summary.json"))[-1:]
    return json.load(open(paths[0])) if paths else None


def one(idx):
    item = data[idx]
    row = {"idx": idx, "uid": item["uid"], "type": item["type"]}
    s = cup_summary(idx)
    if s:
        jlog: list = []
        row["cupmem"], _ = judge(item, s["answers"], jlog)
        b = s["usage_summary"]["billed_usage"]
        row["cupmem_tokens"] = {"in": b["prompt_tokens"], "out": b["completion_tokens"]}
        row["cupmem_usd"] = b["prompt_tokens"] * PRICE[SUPER][0] / 1e6 + b["completion_tokens"] * PRICE[SUPER][1] / 1e6
        row["cupmem_judge_usd"] = sum(r["usd"] for r in jlog)
    else:
        row["cupmem"] = None
    log: list = []
    row["ours_answers"] = ours(item, log)
    row["ours_steps"] = {st: {"calls": sum(1 for r in log if r["step"] == st),
                              "in": sum(r["in"] for r in log if r["step"] == st),
                              "out": sum(r["out"] for r in log if r["step"] == st),
                              "usd": round(sum(r["usd"] for r in log if r["step"] == st), 5)}
                         for st in ("extract", "changes", "answer")}
    jlog = []
    row["ours"], _ = judge(item, row["ours_answers"], jlog)
    row["ours_judge_usd"] = sum(r["usd"] for r in jlog)
    return row


data = json.load(open(f"{STALE}/data/k0_20_MAIN.json"))
with ThreadPoolExecutor(3) as ex, open(OUT, "w") as f:
    for r in ex.map(one, INDICES):
        f.write(json.dumps(r) + "\n")
        f.flush()
        print(r["idx"], r["type"], "cupmem", r["cupmem"], "ours", r["ours"], flush=True)
