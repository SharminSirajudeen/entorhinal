"""The measured run's clean probes: two sessions about unrelated things, then a question resting on the first. Nothing should go stale
and nothing should be flagged; every stale mark or flag is a false flag. Hand-written pairs; live calls are recorded
(REPLAY=1 reproduces them for $0). Run from the repo root: python docs/reports/08-false-flags/probes.py"""
import json
import sys
from functools import partial
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from life import llm, memory, query  # noqa: E402
from life.store import Store  # noqa: E402
from life.types import Session  # noqa: E402

PROBES = [
    ("I work night shifts as a nurse at the city hospital.", "We adopted a cat named Miso last weekend.",
     "Which night shift should I swap next week?"),
    ("I drive a 2019 Corolla to work every day.", "I started learning Spanish on my phone.",
     "When is my Corolla due for its next service?"),
    ("I'm vegetarian and have been for ten years.", "I joined a climbing gym downtown.",
     "Suggest a vegetarian dinner for after climbing."),
    ("My daughter Sara starts school at 8 a.m.", "I bought a new laptop for work.",
     "What time should I leave to drop Sara at school?"),
    ("I live in Abu Dhabi.", "I'm reading a book about Roman history.",
     "Where in Abu Dhabi can I find a quiet café to read?"),
    ("I'm allergic to peanuts.", "My sister is visiting from Cairo next month.",
     "Which snacks should I avoid buying?"),
    ("I run 5 km every morning before work.", "I switched my phone plan to a cheaper one.",
     "How should I fuel before my morning run?"),
    ("I play guitar in a band every weekend.", "I repainted my bedroom blue.",
     "When should I schedule band practice this weekend?"),
    ("I'm saving for a house deposit.", "I started watching a Korean drama series.",
     "How much should I put aside this month for the deposit?"),
    ("I take the metro to work.", "I got a new haircut yesterday.",
     "What's the fastest metro route to my office?"),
]
TIMES = ("2026-01-10 09:00", "2026-02-10 09:00")


def main() -> None:
    chat = partial(llm.chat, record=True)
    rows, spent = [], []

    def metered(model, messages, **kw):
        text, usage = chat(model, messages, **kw)
        spent.append(llm.price(model, usage))
        return text, usage

    for n, (first, second, question) in enumerate(PROBES):
        store = Store(":memory:")
        for i, (time, text) in enumerate(zip(TIMES, (first, second))):
            memory.ingest(store, Session(i, time, [{"role": "user", "content": text}]), metered)
        report = query.check_premises(store, question, metered)
        rows.append({"probe": n, "facts": len(store.timeline()), "stale": [f.id for f in store.stale()],
                     "flagged": report.stale})
        print(json.dumps(rows[-1]))
    false = sum(1 for r in rows if r["stale"] or r["flagged"])
    print(f"false flags: {false} of {len(rows)} probes; spend ${sum(spent):.4f}")


if __name__ == "__main__":
    main()
