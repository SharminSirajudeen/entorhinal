# Third-party material in this repository

| What | Where here | Source | Licence |
|---|---|---|---|
| STALE judge prompt (`SYSTEM_PROMPT_ALL_IN_ONE_JUDGE`), byte for byte | `bench/stale_judge_prompt.txt` | github.com/icedreamc/STALE, `STALE/Evaluation/judge_prompts.py` (Chao, Bai, Sheng, Li, Sun; arXiv 2605.06527) | MIT |
| STALE record ids and types (400 `uid`/`type` pairs, no text) | `tests/recorded/stale_index.json` | huggingface.co/datasets/STALEproj/STALE | CC BY 4.0 |
| Two sessions of STALE scenario `f40ff9ce` | `tests/golden/late_shift.json` | huggingface.co/datasets/STALEproj/STALE | CC BY 4.0 |
| Three STALE scenarios as this pipeline extracted them (facts, not the sessions), each with its third probing question and the answer our baseline gave to it: `855155ad`, `cffcf125`, `d74f7f3e` | `app/examples/*.json` | huggingface.co/datasets/STALEproj/STALE; its distractor sessions derive from LongMemEval (Wu et al.) | CC BY 4.0; MIT |
| STALE's distractor sessions (not stored here; downloaded to `data/` for benchmark runs) | — | derived from LongMemEval (Wu et al.) | MIT |
| three.js r170, `build/three.module.min.js`, unmodified (sha256 pinned by `tests/test_app.py`) | `app/static/vendor/three.module.min.js`, licence text in `app/static/vendor/LICENSE` | npm package `three@0.170.0` (three.js authors) | MIT |

The STALE dataset itself is not redistributed, only the parts listed above. To download it for benchmark runs:
`curl -L -o data/T1_T2_400_FULL.json https://huggingface.co/datasets/STALEproj/STALE/resolve/main/T1_T2_400_FULL.json`.
