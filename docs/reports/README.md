# Experiment reports: stale-aware memory on Nemotron (Nebius hackathon)

Every number here was produced by the code and data in its folder, on Nebius Token Factory, with the Nebius key
only. Each folder is self-contained. The newest results are at the bottom.

| # | Report | Date | Question | Result | Spend |
|---|---|---|---|---|---|
| 01 | [Baseline pilot](01-baseline-pilot/RESULT.md) ([page](01-baseline-pilot/k0-report.html)) | 28 Oct | Does a fact-list + change-detection pipeline beat plain Nemotron reading the whole history? | **Yes.** Premise Resistance 0/20 → 8/20; overall 10.0% → 48.3% | ≈ $3.55 (pilots $1.07, diagnostics ≈ $0.09, full run $2.39) |
| 02 | [CUPMem on Nemotron](02-cupmem-on-nemotron/README.md) | 28 Oct | Does the STALE authors' own system run on Nemotron, and at what cost? | 9 of 10 scenarios completed; 1 crashed (cause not determined). ≈ 1.42M input tokens per scenario | $4.48 for the 9 completed runs (the crashed run's spend was not recorded) |
| 03 | [Plan verification on CUPMem](03-plan-verification/README.md) | 28 Oct | Does Chain-of-Verification on CUPMem's plans raise its weakest score (IPA)? | **No.** IPA 2/9 → 2/9 (+1, −1); the checker over-flagged | ≈ $0.19 |
| 04 | [CUPMem vs ours, same 9 scenarios](04-cupmem-vs-ours/README.md) | 28 Oct | Head to head: accuracy, tokens, cost | Overall 17/27 vs 15/27; **ours 5.7× fewer input tokens, $0.085 vs $0.498 per scenario**; ours better on planning (5/9 vs 3/9), worse on premise refusal (3/9 vs 7/9) | ≈ $0.90 (our pipeline $0.85 + judging) |

**Correction (28 Oct, report 05):** in 13 of the baseline pilot's 20 scenarios the "changes" step passed Ultra's reasoning text, not
a change list, to the answer step (no real `FINAL:` line was found). The numbers in 01 and 04 stand as measured; the
step description "Ultra finds the changes" does not hold for those 13. Whether report 04 leaked too is not checked.

| 05 | [Candidate 1: premise check](05-premise-check/README.md) | 28 Oct | Does a dedicated premise check close our PR gap? | **Target missed:** PR 4/9 on report 04's 9 (target ≥ 6). On 20: PR 8 → 11, SR 18 → 15, overall 37 → 38/60 (noise level). The batch change step hit max_tokens in 11 of 20 | $2.72 |
| 06 | [Pilot: the incremental write path](06-incremental-pilot/README.md) | 28 Oct | Does the shipped one-session-at-a-time pipeline keep the batch result? | **Not as built:** 1/6 on 2 scenarios (the related-facts lookup hid the changed fact). After two fixes (every fact, Super judges, only untrue facts listed; and a misspelt marker that dropped 21 of 141 replies): 6/6 on the same 2, not a benchmark | $3.27 |
| 08 | [False flags on clean probes](08-false-flags/README.md) | 28 Oct | Do two unrelated sessions make anything go stale? | 1 of 10 (extraction made the session time a fact), then **0 of 10** after one prompt sentence | < $0.04 |
| 09 | [The measured run](09-measured-run/README.md) | 28 Oct | The shipped pipeline on 12 fresh scenarios against Lightning reading everything | **18/36 (50.0 %) vs 2/36 (5.6 %)**; Type II 6/18; 53 Super replies cut off at max_tokens | ≈ $4.73 |
| 10 | [PrefEval at 300 turns, the reply check kill test](10-prefeval-reply-check/README.md) | 29 Oct | Does the memory plus a reply check follow a stated preference after ~110K tokens? | **Failed:** ours 24/38 (63.2 %) vs RAG 29/38 (76.3 %), reminder 33/38; the reply check alone 17 → 24 | $5.64 |

**Total spent on these experiments: ≈ $25.52** (sum of the rows; the crashed CUPMem run not included).

**Common setup:** STALE (arXiv 2605.06527; Chao, Bai, Sheng, Li, Sun; code MIT, data CC BY 4.0). Scenarios drawn with
seed 7 from the 400. Judge = Nemotron 3 Ultra with STALE's own judge prompt, unchanged, temperature 0. **The paper
used Gemini-3.1-flash-lite, so none of these numbers are comparable one-to-one with the paper's table.**

**Judge noise, measured:** the same CUPMem answers, graded twice by the same judge (report 03 and report 04), scored
PR 6/9 then 7/9 and IPA 2/9 then 3/9. Differences of ±1 at n=9 are noise.
