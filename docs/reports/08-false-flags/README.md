# 08: false flags on clean probes (28 Oct 2026, 10 "no-conflict" probes)

**Question:** when two sessions are about unrelated things, does the memory wrongly mark an old fact stale or flag a
question's premise?

**Setup:** `probes.py`, 10 hand-written pairs (first session, an unrelated second session a month later, then a
question that rests on the first; e.g. "I live in Abu Dhabi." / "I'm reading a book about Roman history." / "Where
in Abu Dhabi can I find a quiet café to read?"). The full pipeline runs live: extraction Lightning, the change judge Super, the premise check Super. A
false flag is any fact marked stale or any premise flagged. Replies are recorded; `REPLAY=1` reproduces them.

| Run | False flags | Output |
|---|---|---|
| As built (`b1565ed`) | **1 of 10** | `probes.txt` |
| After the extraction fix (`816a1b1`) | **0 of 10** | `probes-after-s4-fix.txt` |

**The one false flag was an extraction artifact:** on probe 4, extraction turned the `[Session time: …]` header into a fact
(`user / session_time: 2026-01-10 09:00`), and the change judge correctly marked it superseded by the next session's. Across the
recorded extraction replies, 9 of 185 contained such a fact (count over `cache/`, 28 Oct). The fix tells extraction the session time
only dates the facts. The measured run (seed 11, started before the fix) ran on the extraction prompt without that sentence.

**Read with care:** 10 short, hand-written probes is a small floor check, not a false-flag rate for long memories.
On the incremental pilot's 300-fact memories both the change judge models marked some unrelated facts as changed (report 06).

Spend: under $0.04 for both runs (each printed $0.0153 as the price of every call, replayed ones included).
