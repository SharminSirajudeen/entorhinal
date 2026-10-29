"""STALE's all-in-one judge (Ultra, JSON mode, temperature 0). The system prompt is STALE's
`SYSTEM_PROMPT_ALL_IN_ONE_JUDGE` verbatim and the user template is STALE's own (STALE/Evaluation, MIT).

STALE's licence notice, which covers the prompt text below:

    MIT License

    Copyright (c) 2026 Hanxiang Chao

    Permission is hereby granted, free of charge, to any person obtaining a copy
    of this software and associated documentation files (the "Software"), to deal
    in the Software without restriction, including without limitation the rights
    to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
    copies of the Software, and to permit persons to whom the Software is
    furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice shall be included in all
    copies or substantial portions of the Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
    SOFTWARE.
"""
import json
import re
from pathlib import Path

from life import llm
from life.constants import ULTRA
from life.types import Instance

DIMS = ("dim1_query", "dim2_query", "dim3_query")
SYSTEM_PROMPT_ALL_IN_ONE_JUDGE = (Path(__file__).parent / "stale_judge_prompt.txt").read_text()

USER = """
[Ground Truth Context]
- M_old: "{M_old}"
- M_new: "{M_new}"
- Hidden Logic: {explanation}

--------------------------------------------------
[Dimension 1: Explicit Probing]
Question 1: {q1}
Target Model Response 1: {a1}

--------------------------------------------------
[Dimension 2: Adversarial Robustness]
Question 2: {q2}
Target Model Response 2: {a2}

--------------------------------------------------
[Dimension 3: Implicit Task]
Question 3: {q3}
Target Model Response 3: {a3}
"""


def judge(inst: Instance, answers: dict, chat=llm.chat) -> dict:
    """{dim: bool}: did the response respect the new state. A judge reply with no JSON is an error, never a fail."""
    q = inst.probing_queries
    user = USER.format(M_old=inst.M_old, M_new=inst.M_new, explanation=inst.explanation,
                       q1=q[DIMS[0]], a1=answers[DIMS[0]], q2=q[DIMS[1]], a2=answers[DIMS[1]],
                       q3=q[DIMS[2]], a3=answers[DIMS[2]])
    text, _ = chat(ULTRA, [{"role": "system", "content": SYSTEM_PROMPT_ALL_IN_ONE_JUDGE},
                           {"role": "user", "content": user}], json_mode=True)
    found = re.search(r"\{.*\}", text, re.S)
    if not found:
        raise ValueError(f"judge reply has no JSON object: {text[:200]!r}")
    verdict = json.loads(found.group(0))
    return {d: verdict[f"dim{i + 1}_eval"]["pass"] is True for i, d in enumerate(DIMS)}
