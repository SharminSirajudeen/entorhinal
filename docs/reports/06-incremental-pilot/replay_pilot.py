"""Rebuild the pilot's Stores from the recorded replies (REPLAY=1: a miss raises, nothing is spent) and show where
M_old / M_new landed and what the premise check flagged."""
import json, os, sys
from functools import partial
os.environ["REPLAY"] = "1"
from bench.stale import load_stale
from life import llm, memory, query
from life.constants import ULTRA, SUPER
from life.store import Store
from life.types import Session
s6 = {"ours": ULTRA, "ours-super": SUPER}[sys.argv[1]]
for inst in load_stale("data/T1_T2_400_FULL.json", 1, 7):
    store = Store(":memory:")
    for i, turns in enumerate(inst.haystack_session):
        if turns:
            memory.ingest(store, Session(i, inst.timestamps[i], turns), llm.chat, s6_model=s6)
    print("=" * 100, "\n", inst.uid, inst.type, "\nM_old:", inst.M_old, "\nM_new:", inst.M_new, "\nrelevant:", inst.relevant_session_index,
          "\nfacts:", len(store.timeline()), "stale:", len(store.stale()))
    for idx in inst.relevant_session_index:
        for f in store.timeline():
            if f.source_idx == idx:
                print(f"  [{f.id}] {f.status:6} {f.subject}/{f.attribute}: {f.value[:90]} | by={f.invalidated_by} {(f.reason or '')[:80]}")
    for d in ("dim1_query", "dim2_query", "dim3_query"):
        r = query.check_premises(store, inst.probing_queries[d])
        print(" ", d, inst.probing_queries[d][:100], "\n    premises:", r.premises[:4], "\n    stale:", r.stale)
