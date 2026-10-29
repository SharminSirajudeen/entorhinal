"""Incremental-pilot triage: build each pilot Store from recordings up to the changing session (free), then run that one session's
ingest live with the related-facts lookup uncapped (every active fact goes to the change judge). Did the old fact go stale, and at what cost?"""
import os
os.environ["REPLAY"] = "1"
from bench.stale import load_stale
from life import constants, llm, memory
from life.constants import ULTRA
from life.store import Store
from life.types import Session
spent = []
def metered(model, messages, **kw):
    text, usage = llm.chat(model, messages, **kw)
    spent.append((model, usage, llm.price(model, usage)))
    return text, usage
for inst, old_id in zip(load_stale("data/T1_T2_400_FULL.json", 1, 7), ["s12f0", "s4f1"]):
    store, new_idx = Store(":memory:"), inst.relevant_session_index[1]
    for i, turns in enumerate(inst.haystack_session[:new_idx]):
        if turns:
            memory.ingest(store, Session(i, inst.timestamps[i], turns), llm.chat, s6_model=ULTRA)
    constants.MAX_RELATED = 100_000
    os.environ.pop("REPLAY")
    n = len(spent)
    memory.ingest(store, Session(new_idx, inst.timestamps[new_idx], inst.haystack_session[new_idx]), metered, s6_model=ULTRA)
    os.environ["REPLAY"] = "1"
    constants.MAX_RELATED = 40
    old = store.get(old_id)
    print(inst.type, old_id, old.status, "by", old.invalidated_by, "|", (old.reason or "")[:120])
    print("  stale now:", [(f.id, f.value[:50]) for f in store.stale()][-6:])
    for m, u, usd in spent[n:]:
        print("  ", m.split("/")[1], "in", u.get("prompt_tokens"), "cached", (u.get("prompt_tokens_details") or {}).get("cached_tokens"), "out", u.get("completion_tokens"), f"${usd:.4f}")
print(f"total ${sum(s[2] for s in spent):.4f}")
