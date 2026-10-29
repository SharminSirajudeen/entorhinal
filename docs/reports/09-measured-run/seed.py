"""The demo's long examples (app/examples/): three scenarios' memories from the measured run, rebuilt from its recorded replies only, so
nothing is spent (REPLAY=1 turns a missing recording into an error). Each file also carries the scenario's dim3 question
and two recorded answers to it (results/measured-run): Nemotron 3 Super's, reasoning on, reading the whole history (the
same model that answers in our pipeline), and ours, which this script re-derives from the same recordings and checks
against the run's row.

The recordings (cache/) are not in the repo, and the request bodies must match the run's, so this runs in a checkout of
`fefcf45`, the commit the run used:
    git worktree add ../measured fefcf45 && cd ../measured
    REPLAY=1 LIFE_CACHE=<repo>/cache PYTHONPATH=. python <repo>/docs/reports/09-measured-run/seed.py <repo> travel d74f7f3e
"""
import json
import os
import sys
from dataclasses import asdict
from pathlib import Path

from life import llm, memory, query
from life.constants import SUPER
from life.store import Store
from life.types import Session

assert os.environ.get("REPLAY") == "1", "replay only: a missing recording must fail, not spend"
repo, name, uid = Path(sys.argv[1]), sys.argv[2], sys.argv[3]
rec = next(r for r in json.loads((repo / "data/T1_T2_400_FULL.json").read_text()) if r["uid"].startswith(uid))


def row(condition: str) -> dict:
    return next(json.loads(r) for r in open(repo / f"results/measured-run/{condition}-n6-seed11-all.jsonl")
                if r.startswith(f'{{"uid": "{rec["uid"]}"') and '"dim3_query"' in r)


flat, ours = row("baseline-super"), row("ours")
store = Store(":memory:")
for i, turns in enumerate(rec["haystack_session"]):  # as bench.run.ours did in the run
    if turns:
        memory.ingest(store, Session(i, rec["timestamps"][i], turns), llm.chat, s6_model=SUPER)
question = rec["probing_queries"]["dim3_query"]
answer = query.answer(store, question, llm.chat)
assert answer.text == ours["response"], "the re-derived answer must be the one the run recorded"
facts = json.loads(store.export_json())
out = {"source": f"STALE scenario {rec['uid']} (huggingface.co/datasets/STALEproj/STALE, CC BY 4.0); facts built by "
                 "this pipeline in our measured STALE run (docs/reports/09-measured-run), from its recorded replies",
       "sessions": sum(1 for s in rec["haystack_session"] if s),
       "chars": sum(len(t["content"]) for s in rec["haystack_session"] for t in s),
       "question": question, "flat": {"answer": flat["response"], "correct": flat["correct"]},
       "ours": {"answer": asdict(answer), "correct": ours["correct"]}, "facts": facts}
(repo / "app/examples" / f"{name}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n")
print(name, rec["uid"], "facts", len(facts), "stale", sum(f["status"] == "stale" for f in facts))
