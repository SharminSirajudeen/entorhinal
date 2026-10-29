# 06: The incremental write path, a pilot (28 Oct 2026)

**Question:** does the shipped, incremental write path (one session at a time: extraction → the related-facts lookup → the change judge) keep the batch
pipeline's result on STALE?

**Answer, as first built: no.** On the two pilot scenarios it scored 1 of 6, because the related-facts lookup showed the change judge only the 40 newest
facts and the fact each scenario changes was older. With that fixed and a parse defect fixed, the same two
scenarios score 6 of 6.

## The pilot as first built (`dbe532a`)
`python -m bench.run --condition ours --n 1 --seed 7 --cap 1.75` (the change judge on Ultra; judge Ultra with STALE's prompt).

| type | SR | PR | IPA | cost | wall clock |
|---|---|---|---|---|---|
| T1 + T2 (2 scenarios) | 0/2 | 0/2 | 1/2 | $1.569 | 1152 s (2 scenarios in parallel) |

Rows: `ours-n1-seed7-all.jsonl`, table: `ours-n1-seed7-all.md`. The `ours-super` pilot was stopped mid-run: it had the
same cap, so its quality was already known. The projection, $1.6752, was printed as an upper bound; it was not one,
and the harness had no stop on actual spend (fixed in `6550a51`: every call is refused once spend reaches `--cap`).

## Why (replayed from the recordings, `REPLAY=1`, $0)
- `replay_pilot.py`: T1 `s12f0` "8 a.m. to 4 p.m." and T2 `s4f1` "union card" are still **active** after the
  sessions that changed them (`s36f0` late shift, `s34f0` legal name change). The premise check flags only facts the
  Store holds as stale, so it flagged nothing.
- `s5check.py`: when the changing session arrived, 326 (T1) and 321 (T2) facts were active; the related-facts lookup sent the 40 newest,
  the oldest from session 31 (T1) and 30 (T2). Neither old fact reached the change judge.

## Fixes tried on the two changing sessions only (live, n = 2)
| Script | Change | Result |
|---|---|---|
| `s6all.py` | The related-facts lookup uncapped, the change judge prompt as built (one row per OLD fact) | Ultra stopped at max_tokens (12,818 in, 12,000 out); reply refused; its reasoning had written "keep" for every fact |
| `screen.py lightning` | Lightning lists candidate ids over every active fact | listed every id ("include when unsure"); capped at 10, the first 10 ids, every session |
| `screen.py super` | Super, thinking off, as that screen | [] on all 8 sessions, the two changing ones included |
| `sparse.py ultra` | The change judge over every active fact, OLD first, **only** the untrue ones | found the changed fact 2/2; $0.0485 (11,832 of 12,000 output tokens) and $0.0283; over-flags on T2 |
| `sparse.py super` | the same on Super | found it 1/2 (T2 named `s4f0`, not `s4f1`); $0.0082 and $0.0049; over-flags on T1 |

Shipped (`49757bd`): the related-facts lookup returns every matching active fact, oldest first; the change judge asks only for the untrue facts; the change judge runs on
Super (`S6_MODEL`), because Ultra's 11,832 of 12,000 output tokens on a 326-fact memory means a larger memory cuts
the reply off and nothing goes stale. n = 2 is not a quality comparison between the two models.

Spend, pilot and triage: $1.9865 (sum of list prices over the recordings written since the pilot began).

## The fixed pipeline on the same two scenarios
**First rerun (cap fix, `49757bd`):** `python -m bench.run --condition ours --n 1 --seed 7 --cap 2.6 --out results/pilot`
(the attempt before it died on HTTP 529; the model client now retries). Rows: `rerun1-d1-ours-n1-seed7-all.jsonl`.

| type | SR | PR | IPA | cost |
|---|---|---|---|---|
| T1 + T2 (2 scenarios) | 1/2 | 0/2 | 1/2 | $0.6190 (projected $0.5376) |

T2 now has `s4f1` stale (by `s34f0`, the name change). T1 still had `s12f0` active, and the cause was a parse, not
recall: Super's change-judge reply for session 36 lists `s12f0` as changed by `s36f0`, but behind the line `FIN: [`
instead of `FINAL:`; across the cache, 21 of 141 Super change-judge replies had a misspelt marker and every one lost its
decisions. Fixed in `24122c1` (the change judge reads the array wherever it sits).

**Second rerun (marker fix, `24122c1`):** `python -m bench.run --condition ours --n 1 --seed 7 --cap 2.0 --out results/pilot`.
Rows: `rerun2-d2-ours-n1-seed7-all.jsonl`.

| type | SR | PR | IPA | cost in the rows |
|---|---|---|---|---|
| T1 + T2 (2 scenarios) | 2/2 | 2/2 | 2/2 | $0.6408 (projected $0.5376) |

The rows' cost counts every call's price, replayed ones included; the money spent is what the new recordings cost.

**Read with care:** 2 scenarios, the very two the fixes were found on. This shows the pipeline now does what it was
built to do on them; it is not a benchmark result. That is the measured run, on other scenarios (seed 11).

## Spend
Every recording written from 20:13 to 21:52 (the pilot, the triage, the 529-crashed rerun and both reruns), summed at
list prices: **$3.2664** (Lightning $0.0319, Super $1.5316, Ultra $1.7028). Calls killed in flight are not recorded.
