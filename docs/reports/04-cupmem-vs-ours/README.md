# 04: CUPMem vs ours, the same 9 scenarios (28 Oct 2026)

**Question.** On the same scenarios, the same model family and the same judge: how do the STALE authors' system and
our pipeline compare on accuracy, tokens and cost?

## Setup (`cmp10.py`)
- **CUPMem:** its answers from report 02 (Nemotron Super throughout), graded here.
- **Ours:** the baseline pilot's pipeline re-run with per-step token logging:
  - Lightning, thinking off, extracts facts per session;
  - Ultra, thinking on, finds the changes;
  - Super, thinking off, answers with the 3-step premise check.
- **Judge:** Ultra, STALE's judge prompt, temperature 0. Scenarios: indices 0–4 and 10–14. Index 14 has no CUPMem
  answer (it crashed), so the head-to-head is n = 9.

## Results
| Same 9 scenarios | CUPMem | Ours |
|---|---|---|
| SR (knows the old fact may be outdated) | 7/9 | 7/9 |
| PR (refuses a stale premise) | **7/9** | 3/9 |
| IPA (plans for the new situation) | 3/9 | **5/9** |
| Overall | 17/27 (63%) | 15/27 (56%) |
| Input tokens per scenario | 1,416,106 | **246,515** |
| Output tokens per scenario | 81,225 | 27,846 |
| Cost per scenario (list prices) | $0.498 | **$0.085** |
| Tokens per correct answer | 792,705 | **164,617** |

By type:
- **Type I (n=5):** CUPMem SR/PR/IPA 4 / 3 / 1; ours 4 / 2 / 3.
- **Type II (n=4):** CUPMem 3 / 4 / 2; ours 3 / 1 / 2.

On all 10 scenarios, ours scored SR 8, PR 3, IPA 5 (16/30).

**Our cost by step (sum over the 9):**
- extract: 1,450,235 in / 135,504 out, $0.120;
- changes (Ultra): 136,345 in / 100,785 out, $0.439;
- answer: 632,063 in / 14,329 out, $0.203.

The change-detection step is the most expensive, mostly because of its thinking output.

## What this does and doesn't show
- **Shows:** ours uses **5.7× fewer input tokens** and costs **5.9× less per scenario**, at overall accuracy within
  2 answers of 27 (63% vs 56%), on the same model family and judge.
  - Ours is **better on planning** (IPA 5 vs 3).
  - It's **much worse on premise refusal** (PR 3 vs 7). That's where CUPMem's premise verifier earns its tokens.
- **Doesn't show:** a significant difference in overall accuracy.
  - n = 9, one run per system.
  - The judge itself varied by ±1 per dimension on identical answers (reports 03 vs 04).
  - The cost comparison is model-mix dependent: ours uses Lightning for bulk reading, while CUPMem used Super for
    every call.
- **Next lever, untested:** our weak spot (PR) is CUPMem's strong spot, and the reverse holds for IPA. A query path
  that adds a premise check of CUPMem's kind, on our cheap memory, is the obvious next experiment.

## Files
`cmp10.py`, `cmp10.jsonl` (per scenario: both gradings, CUPMem tokens and cost, our answers and per-step tokens).
