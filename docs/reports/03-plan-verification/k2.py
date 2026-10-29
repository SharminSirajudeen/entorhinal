"""Chain-of-Verification (Dhuliawala et al., arXiv 2309.11495) on top of CUPMem's planning answers.

CUPMem's memory and its dim1/dim2 answers are untouched. Only the dim3 (plan) answer is verified:
draft = CUPMem's answer -> Ultra lists the plan's assumptions about the user -> Ultra checks them against CUPMem's own
final memory snapshot -> if any is false, Super revises the plan; otherwise the draft is kept unchanged.
Both variants are graded by Ultra with STALE's judge prompt (same as PILOT).
Usage: python3 -I k2.py <stale_dir> <k0.py> <out.jsonl>
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
exec(compile(src, PILOT, "exec"), ns)  # the baseline pilot's judge text and constants
URL, SUPER, ULTRA, PRICE, DIMS = ns["URL"], ns["SUPER"], ns["ULTRA"], ns["PRICE"], ns["DIMS"]
INDICES = [0, 1, 2, 3, 4, 10, 11, 12, 13, 14]

ASSUME = ("Below is a user's request and an assistant's draft plan. List every assumption the PLAN makes about the "
          "user's current situation (schedule, health, location, job, possessions, abilities, relationships, "
          "documents, plans). One short assumption per line. After thinking, output 'FINAL:' then only the list.")
CHECK = ("Below is the user's memory: ACTIVE items are current; STALE items are no longer true. For each "
         "assumption, decide from the CURRENT memory whether it holds. Consider implicit consequences of active "
         "items (a cast means no cycling; a late shift means mornings are free). After thinking, output 'FINAL:' "
         "then one line per assumption: 'FALSE | assumption | item id and why' or 'OK | assumption'.")
REVISE = ("Revise the draft plan so that it no longer relies on the false assumptions listed, using the user's "
          "current situation. Keep everything else the same. Output only the revised plan.")


def chat(model, messages, think=False, json_mode=False, max_tokens=8000, log=None):
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0,
            "chat_template_kwargs": {"enable_thinking": think}}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    req = urllib.request.Request(URL, json.dumps(body).encode(), headers={
        "Authorization": "Bearer " + os.environ["NEBIUS_API_KEY"], "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        d = json.load(r)
    u = d.get("usage", {})
    if log is not None:
        log.append(u.get("prompt_tokens", 0) * PRICE[model][0] / 1e6 + u.get("completion_tokens", 0) * PRICE[model][1] / 1e6)
    text = d["choices"][0]["message"].get("content") or ""
    return text.split("FINAL:")[-1].strip() if think else text


def memory_text(snap):
    rows = [f"ACTIVE [{i.get('item_id')}] {i.get('value')} (updated {i.get('last_updated')})"
            for items in snap.get("active_profile", {}).values() for i in (items if isinstance(items, list) else [])]
    rows += [f"STALE [{i.get('item_id')}] {i.get('value')} (updated {i.get('last_updated')})"
             for i in snap.get("stale_archive", [])]
    return "\n".join(rows)


def judge(item, answers, log):
    text = chat(ULTRA, [{"role": "system", "content": ns["JUDGE_SYS"]},
                        {"role": "user", "content": judge_user(item, answers)}], json_mode=True, log=log)
    m = re.search(r"\{.*\}", text, re.S)
    v = json.loads(m.group(0)) if m else {}
    return {dm: bool(v.get(f"dim{dm[3]}_eval", {}).get("pass")) for dm in DIMS}


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


def run_dir(idx):
    pat = f"{STALE}/cup_runs/*/" if idx == 0 else f"{STALE}/cup_runs10/idx_{idx}/*/"
    found = sorted(p for p in glob.glob(pat) if os.path.exists(p + "trace.json") and os.path.exists(p + "summary.json"))
    return found[-1] if found else None


def one(idx):
    item, d = data[idx], run_dir(idx)
    if not d:
        return {"idx": idx, "uid": item["uid"], "type": item["type"], "missing": True}
    trace, summ, log = json.load(open(d + "trace.json")), json.load(open(d + "summary.json")), []
    orig = dict(summ["answers"])
    mem, req, draft = memory_text(trace["final_profile_snapshot"]), item["probing_queries"]["dim3_query"], orig["dim3_query"]
    assumptions = chat(ULTRA, [{"role": "user", "content": f"[Request]\n{req}\n\n[Draft plan]\n{draft}\n\nTask: {ASSUME}"}],
                       think=True, log=log)
    checks = chat(ULTRA, [{"role": "user", "content": f"[User memory]\n{mem}\n\n[Assumptions]\n{assumptions}\n\nTask: {CHECK}"}],
                  think=True, log=log)
    false = [ln for ln in checks.splitlines() if ln.strip().upper().startswith("FALSE")]
    verified = dict(orig)
    if false:
        verified["dim3_query"] = chat(SUPER, [{"role": "user", "content": (
            f"[Request]\n{req}\n\n[Draft plan]\n{draft}\n\n[False assumptions]\n" + "\n".join(false) +
            f"\n\nTask: {REVISE}")}], log=log)
    jlog: list = []
    return {"idx": idx, "uid": item["uid"], "type": item["type"], "false_assumptions": false,
            "orig": judge(item, orig, jlog), "verified": judge(item, verified, jlog),
            "draft": draft, "revised": verified["dim3_query"], "verify_usd": sum(log), "judge_usd": sum(jlog),
            "memory_chars": len(mem)}


data = json.load(open(f"{STALE}/data/k0_20_MAIN.json"))
with ThreadPoolExecutor(5) as ex, open(OUT, "w") as f:
    for r in ex.map(one, INDICES):
        f.write(json.dumps(r) + "\n")
        f.flush()
        print(r["idx"], r["type"], "MISSING" if r.get("missing") else
              f"orig {r['orig']} verified {r['verified']} false={len(r['false_assumptions'])} "
              f"${r['verify_usd'] + r['judge_usd']:.3f}", flush=True)
