# 02: CUPMem on Nemotron (28 Oct 2026)

**Question.** Does the STALE authors' memory system (CUPMem, github.com/icedreamc/STALE, `cup_mem/`, MIT) run on an
NVIDIA model through Token Factory, and what does it cost?

## Setup
- CUPMem code unmodified except one local change: `extra_body={"chat_template_kwargs": {"enable_thinking": False}}`
  added to its chat call (`llm_layer/client.py`). Nemotron otherwise writes its thinking into the reply. **This patch
  is ours, and it could affect CUPMem's behaviour.**
- Model: `nvidia/nemotron-3-super-120b-a12b` for every CUPMem call. Embeddings: `all-MiniLM-L6-v2` (Apache-2.0),
  local, CPU.
- `--session-mode full` (all ~50 sessions). Scenarios: indices 0–4 (Type I) and 10–14 (Type II) of the seed-7 sample
  of 20 used in the baseline pilot.
- Run 0 alone; runs 1–4 and 10–14 five in parallel, each in its own output folder.

## Results
- **Completed: 9 of 10.** Index 14 (`d31a1e17`, Type II) **crashed** in the query stage
  (`basis_recovery_impl._filter_lane_hits_with_llm`) with `JSONDecodeError: Extra data` after CUPMem's own JSON
  retry. The failing reply was not saved (errors are not cached), so **the cause is not determined**: Nemotron's
  output, CUPMem's parser, or our thinking-off patch. Log: `idx_14-crash.log`.
- **Tokens (billed, from each run's `summary.json`):** 12,744,961 input + 731,026 output over 9 runs; **≈ 1.42M input
  per scenario**; ≈ $0.50 per scenario at Super's list price ($0.30 / $0.90 per million). Wall time ≈ 12 minutes for
  scenario 0.
- **Where the tokens go (scenario 0, from its usage log):**

  | Phase | Input tokens |
  |---|---|
  | latent_invalidation_proposer | 450,934 |
  | invalidation_judge | 191,696 |
  | delta_extractor | 151,395 |
  | stale_support_judge | 141,347 |
  | update_judge | 123,879 |
  | session_chunker | 104,650 |
  | bucket_bridge_proposer | 67,229 |
  | **Write path total** | **1,231,130** (≈ 7.5× the ≈ 165K-token history) |
  | **Query path total** (3 questions) | 156,615 |

- **Accuracy** (graded by our Ultra judge, see report 04): SR 7/9, PR 7/9, IPA 3/9 (report 03's grading of the same
  answers: 7/9, 6/9, 2/9).

## Files
`summary-idx_N.json` (answers, CUPMem's own verdicts, usage) per completed run; `idx_14-crash.log`. Full traces stay
on the Mac (scratchpad) and are not committed.
