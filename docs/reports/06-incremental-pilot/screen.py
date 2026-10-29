"""Incremental-pilot triage: a Lightning screen over EVERY active fact. Recall on the two changing sessions; how many candidates on
the sessions just before them (distractors). Stores are rebuilt from recordings (free); only the screen is live."""
import json, os
os.environ["REPLAY"] = "1"
from bench.stale import load_stale
from life import llm, memory
import sys
from life.constants import LIGHTNING, SUPER, ULTRA
MODEL = {'lightning': LIGHTNING, 'super': SUPER}[sys.argv[1]]
from life.store import Store
from life.types import Session
PROMPT = ("Below are facts about the user held as current, each with an id, then new facts from the user's latest "
          "session. List the id of every current fact that the new facts could make untrue or out of date, directly "
          "or as an implied consequence (a broken leg means the user can no longer cycle; a legal name change makes "
          "anything held under the old name out of date). Give at most 10 ids, the most likely first; most new facts "
          "change nothing, so return an empty list unless a current fact is clearly affected. Output only JSON: "
          "{\"ids\": [\"...\"]}")
line = lambda f: f"[{f.id}] ({f.time}) {f.subject} / {f.attribute}: {f.value}"
total = 0.0
for inst, old_id in zip(load_stale("data/T1_T2_400_FULL.json", 1, 7), ["s12f0", "s4f1"]):
    store, new_idx = Store(":memory:"), inst.relevant_session_index[1]
    probes = [new_idx - 3, new_idx - 2, new_idx - 1, new_idx]
    for i, turns in enumerate(inst.haystack_session[:new_idx + 1]):
        if not turns:
            continue
        if i in probes:
            new = memory.extract_facts(Session(i, inst.timestamps[i], turns), llm.chat)
            body = ("[Current facts]\n" + "\n".join(map(line, store.active())) + "\n\n[New facts]\n" + "\n".join(map(line, new))
                    + "\n\nTask: " + PROMPT)
            os.environ.pop("REPLAY")
            text, usage = llm.chat(MODEL, [{"role": "user", "content": body}], json_mode=True, max_tokens=2000)
            os.environ["REPLAY"] = "1"
            ids = json.loads(text)["ids"]; total += llm.price(MODEL, usage)
            print(inst.type, f"s{i}", "changing" if i == new_idx else "distractor", "active", len(store.active()),
                  "in", usage.get("prompt_tokens"), "->", len(ids), "ids", "| old fact found:" if i == new_idx else "", (old_id in ids) if i == new_idx else "", ids[:8])
        if i < new_idx:
            memory.ingest(store, Session(i, inst.timestamps[i], turns), llm.chat, s6_model=ULTRA)
print(f"screen spend ${total:.4f}")
