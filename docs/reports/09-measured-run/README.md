# 09: The measured run (28 Oct 2026, 21:53–22:52 Dubai)

**Question:** on STALE scenarios none of the fixes were made on, how does the shipped pipeline compare with Nemotron
reading the whole history?

**Setup:** STALE (arXiv 2605.06527), seed 11, 6 scenarios per type (12; none shared with the incremental pilot pair), all
three probing dimensions. Judge: Nemotron 3 Ultra with STALE's own judge prompt, temperature 0. Code `fefcf45`
(both pilot fixes in; the extraction prompt's session-time sentence of report 08 not yet).
- `baseline`: Nemotron 3.5 Lightning reads the full history and answers (STALE's own setup, as in the baseline pilot).
- `ours`: each session in time order through extraction (Lightning) → the related-facts lookup → the change judge (Super, thinking on) into a fresh Store, then
  each question through the premise check (Super) and the answer step (Super).

```
python -m bench.run --condition baseline --n 6 --seed 11 --cap 0.9 --out results/measured-run
python -m bench.run --condition ours     --n 6 --seed 11 --cap 4.2 --out results/measured-run
```
Rows and tables: `results/measured-run/{baseline,ours}-n6-seed11-all.{jsonl,md}`.

## Result

| | T1 SR | T1 PR | T1 IPA | T2 SR | T2 PR | T2 IPA | Correct | Overall (mean of the six) |
|---|---|---|---|---|---|---|---|---|
| baseline (Lightning, full history) | 0/6 | 0/6 | 2/6 | 0/6 | 0/6 | 0/6 | 2/36 | 5.6 % |
| **ours** | 3/6 | 4/6 | 5/6 | 2/6 | 2/6 | 2/6 | **18/36** | **50.0 %** |

Per scenario (SR PR IPA, 1 = correct), ours: T1 111, 111, 111, 011, 001, 000; T2 111, 111, 000, 000, 000, 000.
The baseline is right only on two T1 IPA questions, in two scenarios ours gets 111.

**Published rows, for context only** (STALE repo README, their judge Gemini-3.1-flash-lite, all 400 scenarios,
Overall = mean of the same six cells): CUPMem 68.0, Claude-Opus-4.6 28.3, GPT-5.4 15.7, mem-0 8.3, Zep 6.0. Our judge
and our n differ, so these are not ranked against ours.

## Cost
- Rows: baseline $0.3240; ours $3.5968.
- **Money actually spent on `ours` was about $4.39 ($0.366 to $0.369 a scenario):** every recording written in the run
  window summed $4.7486, less the baseline's $0.3240 and at most $0.0306 of report 08's probes. The rows miss
  **52 change-judge calls and 1 premise-check call on Super that stopped at max_tokens** (12,000 and 8,000 output tokens; $0.77 together):
  a reply cut off is refused, so its decisions were lost **and** its price went uncounted, by the rows and by the
  harness's cap, which this run therefore passed by about $0.19.
- Wall clock: about 60 minutes for `ours` (5 scenarios at a time; sessions in order within one).

## What this does and does not show
- On 12 fresh scenarios the pipeline answered 18 of 36 questions right where the same model reading everything got 2.
- n = 12 scenarios. Type II (implied consequences) is weaker: 6/18 against Type I's 12/18.
- 52 change-judge calls were cut off, of roughly 580 (693 Super calls in the window, less 72 for the premise check/the answer step and about 40 for the
  probes); the sessions they judged may hold changes the memory never saw.

## Reused by the demo
`seed.py` rebuilds three of these memories from the run's recordings only (`REPLAY=1`, in a checkout of `fefcf45`; $0)
into `app/examples/`: `855155ad` (T2, 464 facts, 18 stale), `cffcf125` (T2, 535, 15) and `d74f7f3e` (T1, 481, 25),
the three scenarios where ours was right on all three questions and the baseline wrong on the third. Each file also
holds that third question and both recorded answers to it: the baseline's, and ours, which `seed.py` re-derives from
the recordings (`query.answer`) and asserts equal to the measured run's row before writing it. Asking the three questions on the current code against
those memories replays the measured run's own premise-check and answer recordings (29 Oct, no key set, `REPLAY=1`): the requests are unchanged.

## Larger models reading the whole history (29 Oct)

The baseline above is Nemotron 3.5 Lightning, the smallest model. To compare like with like, the same 12 scenarios
were run with Nemotron 3 Super (the model that judges, checks and answers in `ours`) and Nemotron 3 Ultra (550B)
reading the whole history, each with reasoning on and up to 16,000 output tokens; a reply cut off there gets one retry
with 32,000, and a second cut is scored as no answer (`bench/run.py`, `BASELINES`).

```
python -m bench.run --condition baseline-super --n 6 --seed 11 --cap 2.9 --out results/measured-run
python -m bench.run --condition baseline-ultra --n 6 --seed 11 --cap 8.5 --out results/measured-run
```

| | T1 SR | T1 PR | T1 IPA | T2 SR | T2 PR | T2 IPA | Correct | Overall | Cost |
|---|---|---|---|---|---|---|---|---|---|
| Super, whole history | 1/6 | 0/6 | 5/6 | 0/6 | 0/6 | 0/6 | 6/36 | 16.7 % | $1.4264 |
| Ultra, whole history | 1/6 | 0/6 | 1/6 | 3/6 | 1/6 | 0/6 | 6/36 | 16.7 % | $4.7988 |
| ours | 3/6 | 4/6 | 5/6 | 2/6 | 2/6 | 2/6 | 18/36 | 50.0 % | $3.5968 |

- Super got none of its replies cut off. Of the 53 recorded Ultra calls (answers, retries and the judge), 7 were cut
  off; two answers stayed cut after the retry
  and count as wrong (8 of 36 if both had been right).
- Ultra's first attempt stopped on its first cut-off reply, before the retry existed; its two recorded calls ($0.2124)
  replayed for free in the run above, whose cost includes them.
- All three models answered the three demo questions wrong; the demo now shows Super's answer, the same model as ours.

