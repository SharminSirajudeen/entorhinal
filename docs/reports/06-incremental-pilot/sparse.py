"""Incremental-pilot triage: the change judge over EVERY active fact, OLD facts first, asked to list ONLY the stale/changed ones. Live on the two
changing sessions, Ultra and Super (thinking on). Stores rebuilt from recordings (free)."""
import json, os, sys
os.environ["REPLAY"] = "1"
from bench.stale import load_stale
from life import llm, memory
from life.constants import SUPER, ULTRA
from life.store import Store
from life.types import Session
MODEL = {"ultra": ULTRA, "super": SUPER}[sys.argv[1]]
PROMPT = ("Each NEW fact is dated later than every OLD fact. Find every OLD fact that a NEW fact changes or makes "
          "untrue for the user's situation now, including implicit consequences (a new job schedule replaces the old "
          "schedule; a broken leg stops cycling; a legal name change makes anything held under the old name out of "
          "date). Most sessions change nothing. After thinking, output a line 'FINAL:' followed by a JSON array listing "
          "ONLY the OLD facts that are now untrue, [] if none: "
          '{"old_id": ..., "verdict": "stale" | "changed", "by": id of the NEW fact that causes it, "reason": one sentence}.')
line = lambda f: f"[{f.id}] ({f.time}) {f.subject} / {f.attribute}: {f.value}"
total = 0.0
for inst, old_id in zip(load_stale("data/T1_T2_400_FULL.json", 1, 7), ["s12f0", "s4f1"]):
    store, new_idx = Store(":memory:"), inst.relevant_session_index[1]
    for i, turns in enumerate(inst.haystack_session[:new_idx]):
        if turns:
            memory.ingest(store, Session(i, inst.timestamps[i], turns), llm.chat, s6_model=ULTRA)
    new = memory.extract_facts(Session(new_idx, inst.timestamps[new_idx], inst.haystack_session[new_idx]), llm.chat)
    body = ("OLD facts:\n" + "\n".join(map(line, store.active())) + "\n\nNEW facts:\n" + "\n".join(map(line, new))
            + "\n\nTask: " + PROMPT)
    os.environ.pop("REPLAY")
    try:
        text, usage = llm.chat(MODEL, [{"role": "user", "content": body}], think=True, max_tokens=12000)
    except ValueError as e:
        print(inst.type, "REFUSED", e); os.environ["REPLAY"] = "1"; continue
    os.environ["REPLAY"] = "1"
    total += llm.price(MODEL, usage)
    rows = json.loads(text[text.find("["):text.rfind("]") + 1])
    print(inst.type, "in", usage.get("prompt_tokens"), "cached", (usage.get("prompt_tokens_details") or {}).get("cached_tokens"),
          "out", usage.get("completion_tokens"), f"${llm.price(MODEL, usage):.4f}", "| old fact flagged:", any(r.get("old_id") == old_id for r in rows))
    for r in rows:
        print("   ", r.get("old_id"), r.get("verdict"), r.get("by"), str(r.get("reason"))[:110])
print(f"spend ${total:.4f}")
