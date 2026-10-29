"""Was the old fact among the facts the related-facts lookup sent to the change judge when the changing session arrived? (REPLAY=1, nothing spent)"""
import os
os.environ["REPLAY"] = "1"
from bench.stale import load_stale
from life import llm, memory
from life.constants import ULTRA
from life.store import Store
from life.types import Session
for inst, old_id in zip(load_stale("data/T1_T2_400_FULL.json", 1, 7), ["s12f0", "s4f1"]):
    store, new_idx = Store(":memory:"), inst.relevant_session_index[1]
    for i, turns in enumerate(inst.haystack_session[:new_idx]):
        if turns:
            memory.ingest(store, Session(i, inst.timestamps[i], turns), llm.chat, s6_model=ULTRA)
    new = memory.extract_facts(Session(new_idx, inst.timestamps[new_idx], inst.haystack_session[new_idx]), llm.chat)
    sent = memory.related_active(store, new)
    print(inst.type, "active before:", len(store.active()), "sent to the change judge:", len(sent), "old fact sent:", old_id in {f.id for f in sent},
          "oldest sent:", min(f.source_idx for f in sent))
