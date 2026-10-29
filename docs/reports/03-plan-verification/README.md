# 03: Chain-of-Verification on CUPMem's plans (28 Oct 2026)

**Hypothesis.** CUPMem's weakest published dimension is IPA (planning for the new situation): 32.0% Type I and 43.0%
Type II in its README. A frontier model (Gemini-3.1-pro) scores 71.0 / 55.0 there. If we verify CUPMem's plan
against CUPMem's own memory, IPA should rise.

**Method** (`k2.py`): Chain-of-Verification (Dhuliawala, Komeili, Xu, Raileanu, Li, Celikyilmaz, Weston; arXiv
2309.11495), joint variant, on the dim3 answer only.
1. Ultra (thinking on) lists the plan's assumptions about the user.
2. Ultra (thinking on) checks each against CUPMem's `final_profile_snapshot` (ACTIVE vs STALE items).
3. If any is FALSE, Super revises the plan; otherwise the draft is kept.

CUPMem's memory and its dim1/dim2 answers are untouched. Both variants are graded by Ultra with STALE's judge
prompt.

**Kill rule (set before the run):** IPA must rise by ≥ 2 of 10 without anything else dropping.

## Result: FAILED
| n = 9 (index 14 crashed in report 02) | SR | PR | IPA |
|---|---|---|---|
| CUPMem's answers | 7 | 6 | 2 |
| + plan verification | 7 | 6 | 2 |

- IPA changed in two scenarios, cancelling out: index 2 went fail → pass, and index 12 went pass → fail.
- **Cause:** the checker over-flagged. FALSE-assumption counts per scenario were 0, 15, 9, 4, 6, 11, 1, 1, 9. It marked
  assumptions FALSE because the memory *did not mention* them (example: "no active memory item expresses this
  desire"), not because an active item *contradicted* them. The revisions became vaguer ("please share…"), which
  STALE's judge fails as "too generic".
- **Untested fix:** flag an assumption only when an ACTIVE item contradicts it, citing that item. One rerun ≈ $0.19.
- Spend ≈ $0.185.

## Files
`k2.py` (script), `k2.jsonl` (per scenario: false assumptions, draft, revised, both gradings, cost).
