# 05: Candidate 1, a dedicated premise check (28 Oct 2026; $2.72)

**Question.** Report 04: ours PR 3/9 vs CUPMem 7/9. Does a premise check of CUPMem's kind (verdict per assumption:
SAFE / OUTDATED / UNRESOLVED) close that gap on our cheap memory? **Target:** PR ≥ 6/9 on report 04's scenarios,
under $0.15 per scenario.

## Result: target MISSED (PR 4/9 against ≥ 6/9)
`C1_DIAG_OK=1 python3 -I c1.py <repo> run 3`, judge Ultra with STALE's prompt, live spend **$2.674** ($2.718 at list
price; cached calls counted once):

| Condition (same memory for A and B) | SR | PR | IPA | Overall | On report 04's 9: SR / PR / IPA |
|---|---|---|---|---|---|
| The baseline pilot as run (its leaked memory) | 11/20 | 8/20 | 10/20 | 29/60 | 4 / 3 / 4 |
| A: re-run change step, the baseline pilot's answer prompt | **18/20** | 8/20 | 11/20 | 37/60 | 8 / 3 / 3 |
| B: same memory + premise check (Super, thinking on) | 15/20 | **11/20** | **12/20** | **38/60** | 6 / **4** / 4 |
| CUPMem (report 04) | | | | | 7 / 7 / 3 |

- **A → B, per scenario:** PR gained 5, lost 2; SR gained 2, lost 5; IPA gained 2, lost 1. The net +1 overall is
  within judge noise (±1 per dimension at n = 9, report index). B also swapped the baseline pilot's `PREMISE_NOTE` for `ANSWER_NOTE`,
  so the SR loss may come from the lost note rather than the check: **not separated**.
- **The change step leaked again in 11 of 20:** Ultra hit `max_tokens=16000` (`finish_reason=length`) on 11 change
  calls; in 10 of them the reasoning came back in `content` with no `reasoning_content`, and `after_mark` passed it on
  (23K–52K chars). So "A = a clean change list" holds for 9 of 20 only. A and B share that memory, so A vs B stands.
  The product's model client (`life/llm.py`, `reply`) refuses a reply cut at `max_tokens`, with a mutant.
- **Cost per scenario of B's pipeline, my estimate from the logged usage:** changes ≈ $0.056, premise ≈ $0.029,
  answers ≈ $0.022, plus extraction ≈ $0.013 (report 04) ≈ **$0.12**, against CUPMem's $0.498 (report 04).
- **Next, per the agreed fallback:** lead with the measured cost claim and state the PR gap. The product's change judge is
  incremental (small inputs per session), which the incremental pilot measures; it does not reuse this batch change step.

## Defect found first: the baseline pilot's change list was mostly Ultra's reasoning
Measured 28 Oct from `docs/reports/01-baseline-pilot/k0_full20.jsonl` (the `memory` field the baseline pilot passed to the answer step):

| The baseline pilot scenario | Count | PR passed |
|---|---|---|
| "Detected changes" holds a clean `OLD -> NEW` list | 6 | 1 of 6 |
| Empty | 1 | 0 of 1 |
| Ultra's reasoning text (31K–44K chars), from its first sentence ("The user wants me to…"): no marker before it | 9 | 7 of 13, both kinds together |
| Ultra's reasoning text, cut at a `FINAL:` the model quoted from the prompt while thinking; no marker after it | 4 | |

So in all 13, no real `FINAL:` line was found.

- **Cause of the missing markers: not determined.** The baseline pilot did not record `finish_reason`. Truncation at
  `max_tokens=12000` is the suspect.
- **Report 04** ran the same split. It did not save the change text, so whether it leaked is **not checked**.
- **The baseline pilot's and report 04's numbers stand as measured.** The description "Ultra finds the changes" does not hold for
  13 of 20 scenarios: there, Super read Ultra's thinking text.
- The pattern (leaked rows PR 7/13; clean or empty rows 1/7) is small-n and could be scenario difficulty. It could also
  mean the reasoning text helped. Condition A tests that.

## Design (`c1.py`)
- **Input:** the baseline pilot's saved per-session facts for all 20 scenarios (seed 7). No re-extraction.
- **Change step re-run:** Ultra, thinking on, `max_tokens` 16000, split on the last line that *starts* with `FINAL:`.
- **A:** the baseline pilot's answer prompt, unchanged, on the re-run memory.
- **B:** a premise check (Super, thinking on, JSON after `FINAL:`; "not mentioned" is UNRESOLVED, never OUTDATED,
  which is the fix for the plan check's over-flagging), then the answer with `ANSWER_NOTE` in place of the baseline pilot's `PREMISE_NOTE`. That is
  two changes, by design: the product does not check premises twice.
- **Judge:** Ultra with STALE's judge prompt, via the baseline pilot's `judge()`.
- Every response is cached in `cache/c1/`, so a rerun is free.

**Run order:**
1. `python3 -I c1.py <repo> diag 0.10`: one Ultra change call and one Super premise call; prints `finish_reason`
   and whether each wrote the marker.
2. Only if both did: `C1_DIAG_OK=1 python3 -I c1.py <repo> run 3`.

**Projected:** $2.03 (printed by `c1.py run 0`, which exits before any call). **Cap: $3.** Key: `NEBIUS_API_KEY`
only; endpoint `api.tokenfactory.nebius.com` (grep of `c1.py` and `k0.py`).
