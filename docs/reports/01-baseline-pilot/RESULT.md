# Baseline pilot result: STALE, 20 scenarios (seed 7: 10 T1, 10 T2), run 28 Oct 2026 on Nebius Token Factory (Nebius key only)

| Condition | SR (T1 / T2) | PR (T1 / T2) | IPA (T1 / T2) | Overall (60 judged answers) |
|---|---|---|---|---|
| Baseline: Lightning reads the full ~150K-token history | 0 / 1 | **0 / 0** | 2 / 3 | 6 of 60 = 10.0% |
| Ours (crude): Lightning extracts facts per session (thinking off) → Ultra finds changes (thinking on) → Super answers with a 3-step premise check | 7 / 4 | **5 / 3** | 5 / 5 | 29 of 60 = 48.3% |

- **Premise Resistance, combined: 0 of 20 → 8 of 20.**
- **Cost:** $2.39 for both conditions together (summed from the API `usage` field at mastra/models.dev prices).
- **Judge:** Nemotron-3-Ultra with STALE's own judge prompt, unchanged. **The paper used Gemini-3.1-flash-lite**, so
  these numbers are not directly comparable to the paper's table.
- **Noise:** the same code gave different grades on back-to-back pilot runs. n=20, single run.
- **Published, for context (the paper's judge):** PR, Type I / Type II:
  - Zep 0.0 / 1.0;
  - mem-0 1.0 / 0.0;
  - GPT-5.4 2.0 / 2.0;
  - Gemini-3.1-pro 30.0 / 14.0;
  - CUPMem 78.0 / 75.0.
- **Kill rule** (from the plan: "continue only if crude ours beats the baseline on PR"): **passed.**
- **Pilot lessons, carried into the build:**
  1. Put the instruction after a long history.
  2. Send `chat_template_kwargs.enable_thinking=false` everywhere, except change detection: Nemotron otherwise writes
     its thinking into `content`.
  3. Change detection needs Ultra with thinking on. Super with thinking off missed both changes in the pilot.
