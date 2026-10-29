"""The benchmark harness on scripted replies and hand-derived values: the sampler against the baseline pilot's 20 uids,
the judge on hand-written replies, bench/run.py dry runs. No model is ever called: every function that reaches one
takes `chat`, and each test passes a scripted one."""
import hashlib
import inspect
import json
from dataclasses import asdict
from pathlib import Path

import pytest

from bench import judge as judge_mod
from bench import run as bench_run
from bench.stale import load_stale, sample
from life import llm
from life.constants import LIGHTNING, SUPER, ULTRA
from life.types import Answer, Instance, PremiseReport, Session

ROOT = Path(__file__).parent
INDEX = json.loads((ROOT / "recorded" / "stale_index.json").read_text())["records"]
PILOT_ROWS = ROOT.parent / "docs/reports/01-baseline-pilot/k0_full20.jsonl"
PILOT = [json.loads(line) for line in PILOT_ROWS.read_text().splitlines()]
PILOT_UIDS = [r["uid"] for r in PILOT]
DIMS = ("dim1_query", "dim2_query", "dim3_query")
VERDICT = '{"dim1_eval": {"reasoning": "r", "pass": true}, "dim2_eval": {"reasoning": "r", "pass": false}, ' \
          '"dim3_eval": {"reasoning": "r", "pass": true}}'
MILLION = 1_000_000  # tokens: a million input tokens on Lightning cost $0.06, a million output tokens on Ultra $3


def record(uid, typ, sessions=None, times=None):
    sessions = [[{"role": "user", "content": "hi"}], []] if sessions is None else sessions
    return {"uid": uid, "type": typ, "M_old": f"old {uid}", "M_new": f"new {uid}", "explanation": f"why {uid}",
            "probing_queries": {d: f"{d} of {uid}" for d in DIMS}, "haystack_session": sessions,
            "relevant_session_index": [0], "timestamps": times or ["2024-01-01 00:00", "2024-01-02 00:00"]}


def instance(uid="u1", typ="T1", **kw):
    return Instance(**record(uid, typ, **kw))


def fake_chat(calls=None, judge_reply=VERDICT, answer_usage=None, judge_usage=None):
    def chat(model, messages, json_mode=False, think=False, max_tokens=4000):
        if calls is not None:
            calls.append((model, messages, json_mode))
        if json_mode:
            return judge_reply, judge_usage or {}
        return f"answer {len(messages[-1]['content'])}", answer_usage or {}
    return chat


# ---- sample ---------------------------------------------------------------------------------------------------------

def test_index_holds_all_400_records_in_two_types():
    assert len(INDEX) == 400
    assert {r["type"] for r in INDEX} == {"T1", "T2"}


def test_seed_7_n_10_is_k0s_20_uids_in_k0s_order():
    assert [r["uid"] for r in sample(INDEX, 10, 7)] == PILOT_UIDS


def test_a_type_subset_is_the_same_records_the_full_draw_gives():
    assert [r["uid"] for r in sample(INDEX, 10, 7, ["T2"])] == PILOT_UIDS[10:]
    assert [r["uid"] for r in sample(INDEX, 10, 7, ["T1"])] == PILOT_UIDS[:10]


def test_another_seed_draws_other_records():
    assert [r["uid"] for r in sample(INDEX, 10, 8)] != PILOT_UIDS


def test_load_stale_returns_instances_n_per_type(tmp_path):
    data = tmp_path / "d.json"
    data.write_text(json.dumps([record(f"a{i}", "T1") for i in range(3)] + [record(f"b{i}", "T2") for i in range(3)]))
    got = load_stale(str(data), 2, 7)
    assert [i.type for i in got] == ["T1", "T1", "T2", "T2"]
    assert all(isinstance(i, Instance) and i.uid[0] == {"T1": "a", "T2": "b"}[i.type] for i in got)
    assert [i.type for i in load_stale(str(data), 2, 7, ["T2"])] == ["T2", "T2"]


# ---- judge ----------------------------------------------------------------------------------------------------------

def test_judge_prompt_is_stales_byte_for_byte():
    # sha256 of SYSTEM_PROMPT_ALL_IN_ONE_JUDGE as read from STALE/Evaluation/judge_prompts.py (28 Oct)
    digest = hashlib.sha256(judge_mod.SYSTEM_PROMPT_ALL_IN_ONE_JUDGE.encode()).hexdigest()
    assert digest == "2d2d0a52992980120bde7e297197f03853255fa6f36fa3c70df7215476fbe669"


def test_judge_returns_the_pass_flags_per_dimension():
    answers = {d: f"resp {d}" for d in DIMS}
    assert judge_mod.judge(instance(), answers, fake_chat()) == {"dim1_query": True, "dim2_query": False,
                                                                 "dim3_query": True}


def test_judge_sends_ultra_json_mode_with_stales_texts():
    calls = []
    judge_mod.judge(instance(), {d: f"R-{d}" for d in DIMS}, fake_chat(calls))
    model, messages, json_mode = calls[0]
    assert (model, json_mode) == (ULTRA, True)
    assert messages[0] == {"role": "system", "content": judge_mod.SYSTEM_PROMPT_ALL_IN_ONE_JUDGE}
    assert messages[1]["content"] == (
        '\n[Ground Truth Context]\n- M_old: "old u1"\n- M_new: "new u1"\n- Hidden Logic: why u1\n\n'
        '--------------------------------------------------\n[Dimension 1: Explicit Probing]\n'
        'Question 1: dim1_query of u1\nTarget Model Response 1: R-dim1_query\n\n'
        '--------------------------------------------------\n[Dimension 2: Adversarial Robustness]\n'
        'Question 2: dim2_query of u1\nTarget Model Response 2: R-dim2_query\n\n'
        '--------------------------------------------------\n[Dimension 3: Implicit Task]\n'
        'Question 3: dim3_query of u1\nTarget Model Response 3: R-dim3_query\n')


def test_judge_reads_json_wrapped_in_prose_over_several_lines():
    reply = "Here you go:\n" + VERDICT.replace(", ", ",\n") + "\nDone."
    assert judge_mod.judge(instance(), {d: "x" for d in DIMS}, fake_chat(judge_reply=reply))["dim3_query"] is True


def test_judge_treats_only_a_real_true_as_a_pass():
    reply = '{"dim1_eval": {"pass": "false"}, "dim2_eval": {"pass": 1}, "dim3_eval": {"pass": false}}'
    got = judge_mod.judge(instance(), {d: "x" for d in DIMS}, fake_chat(judge_reply=reply))
    assert got == {"dim1_query": False, "dim2_query": False, "dim3_query": False}


def test_judge_reply_without_json_is_an_error_not_a_fail():
    with pytest.raises(ValueError, match="no JSON"):
        judge_mod.judge(instance(), {d: "x" for d in DIMS}, fake_chat(judge_reply="I refuse."))


# ---- conditions -----------------------------------------------------------------------------------------------------

def test_history_skips_empty_sessions_and_labels_times():
    inst = instance(sessions=[[], [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}]])
    assert bench_run.history(inst) == "\n=== Session 2 [Time: 2024-01-02 00:00] ===\nUser: hi\nAssistant: yo\n"


def test_dim3_is_a_task_and_dim1_dim2_are_questions():
    q = bench_run.prompts("CTX", "Q", "dim3_query")
    assert q[0]["content"].endswith("respond to the user's latest query directly.")
    assert q[1]["content"] == "[Conversation History]\nCTX\n\n[Latest Query]\nQ"
    for d in ("dim1_query", "dim2_query"):
        p = bench_run.prompts("CTX", "Q", d)
        assert p[0]["content"].endswith("accurately answer the question.")
        assert p[1]["content"] == "[Conversation History]\nCTX\n\n[Question]\nQ"


def test_baseline_asks_lightning_once_per_dimension_and_prices_each_call():
    calls = []
    got = bench_run.baseline(instance(), fake_chat(calls, answer_usage={"prompt_tokens": MILLION}))
    assert [c[0] for c in calls] == [LIGHTNING] * 3
    assert [c[1][1]["content"].split("\n\n")[-1] for c in calls] == [
        "\n[Question]\ndim1_query of u1", "\n[Question]\ndim2_query of u1", "\n[Latest Query]\ndim3_query of u1"]
    assert {d: c for d, (_, c) in got.items()} == {d: pytest.approx(0.06) for d in DIMS}


@pytest.mark.parametrize("condition, model, price", [("baseline-super", SUPER, 0.30), ("baseline-ultra", ULTRA, 1.00)])
def test_a_larger_baseline_reads_with_reasoning_on_and_room_to_reason(condition, model, price):
    calls = []

    def chat(model, messages, **kw):
        calls.append((model, kw))
        return "a", {"prompt_tokens": MILLION}
    got = bench_run.baseline(instance(), chat, condition)
    assert calls == [(model, {"think": True, "max_tokens": 16000})] * 3
    assert {d: c for d, (_, c) in got.items()} == {d: pytest.approx(price) for d in DIMS}


def test_a_cut_off_baseline_reply_gets_twice_the_room_once_then_counts_as_no_answer():
    calls = []

    def cut(model, messages, **kw):
        calls.append(kw["max_tokens"])
        raise llm.Truncated(model, {"prompt_tokens": MILLION})
    got = bench_run.baseline(instance(), cut, "baseline-ultra")
    assert calls == [16000, 32000] * 3
    assert got == {d: ("", pytest.approx(2.00)) for d in DIMS}  # both cut calls priced: 2 x 1M input x $1


def test_ours_ingests_non_empty_sessions_in_order_then_answers_each_query_from_that_store():
    ingested, asked = [], []

    def ingest(store, session, chat):
        ingested.append((store, session))
        chat(LIGHTNING, [{"role": "user", "content": "x"}])  # one metered call: $0.06, a third per dimension

    def answer(store, question, chat):
        asked.append((store, question))
        return Answer(f"A:{question}", PremiseReport([], []), 0.25)

    got = bench_run.ours(instance(), ingest, answer, fake_chat(answer_usage={"prompt_tokens": MILLION}))
    assert [s for _, s in ingested] == [Session(0, "2024-01-01 00:00", [{"role": "user", "content": "hi"}])]
    assert [q for _, q in asked] == [f"{d} of u1" for d in DIMS]
    assert {id(s) for s, _ in ingested + asked} == {id(ingested[0][0])}
    assert got == {d: (f"A:{d} of u1", pytest.approx(0.27)) for d in DIMS}


# ---- projection, rows, table ---------------------------------------------------------------------------------------

def test_projection_is_hand_derived_per_condition():
    # history is 53 characters = 13.25 tokens. judge: (3 x 4000 + 1000) x $1 + 4000 x $3 = 25,000 (micro-dollars)
    # baseline: 3 x 13.25 x $0.06 + 3 x 4000 x $0.24 = 2,882.385 -> 27,882.385 micro-dollars
    # ours (S6 on Super): 13.25 x $0.30 + (3 + 1 session) x 4000 x $0.90 = 14,403.975 -> 39,403.975 micro-dollars
    # ours-ultra: 13.25 x $1 + (3 + 1 session) x 4000 x $3 = 48,013.25 -> 73,013.25 micro-dollars
    # baseline-super: 3 x 13.25 x $0.30 + 3 x 16000 x $0.90 = 43,211.925 -> 68,211.925 micro-dollars
    # baseline-ultra: 3 x 13.25 x $1 + 3 x 16000 x $3 = 144,039.75 -> 169,039.75 micro-dollars
    inst = instance(sessions=[[{"role": "user", "content": "hi"}]])
    assert len(bench_run.history(inst)) == 53
    assert bench_run.project([inst], "baseline") == pytest.approx(0.027882385)
    assert bench_run.project([inst], "ours") == pytest.approx(0.039403975)
    assert bench_run.project([inst], "ours-ultra") == pytest.approx(0.07301325)
    assert bench_run.project([inst], "baseline-super") == pytest.approx(0.068211925)
    assert bench_run.project([inst], "baseline-ultra") == pytest.approx(0.16903975)


def test_rows_carry_the_judge_model_and_split_the_judge_cost():
    answers = {d: (f"a-{d}", 0.5) for d in DIMS}
    rows = bench_run.rows_for(instance(), "baseline", answers, {"dim1_query": True, "dim2_query": False,
                                                                "dim3_query": True}, 0.3)
    assert [(r.dim, r.response, r.correct, r.judge_model) for r in rows] == [
        ("dim1_query", "a-dim1_query", True, ULTRA), ("dim2_query", "a-dim2_query", False, ULTRA),
        ("dim3_query", "a-dim3_query", True, ULTRA)]
    assert [r.cost_usd for r in rows] == [pytest.approx(0.6)] * 3


def test_table_counts_passes_per_type_and_overall():
    def row(typ, dim, ok):
        return bench_run.EvalRow("u", typ, dim, "baseline", "r", ok, ULTRA, 0.0)

    rows = [row("T1", "dim1_query", True), row("T1", "dim1_query", False), row("T2", "dim1_query", True),
            row("T1", "dim2_query", False), row("T2", "dim2_query", False), row("T1", "dim3_query", True),
            row("T2", "dim3_query", True)]
    assert bench_run.table(rows).splitlines()[2:] == [
        "| T1 | 1/2 (50%) | 0/1 (0%) | 1/1 (100%) |",
        "| T2 | 1/1 (100%) | 0/1 (0%) | 1/1 (100%) |",
        "| all | 2/3 (67%) | 0/2 (0%) | 2/2 (100%) |"]


# ---- bench/run.py end to end on a fake chat ----------------------------------------------------------------------

def args(tmp_path, condition, cap="100"):
    data = tmp_path / "d.json"
    data.write_text(json.dumps([record("a1", "T1"), record("b1", "T2")]))
    return ["--condition", condition, "--n", "1", "--seed", "7", "--types", "T1,T2", "--cap", cap,
            "--data", str(data), "--out", str(tmp_path / "results")]


def test_baseline_dry_run_writes_rows_and_a_table(tmp_path, capsys):
    chat = fake_chat(answer_usage={"prompt_tokens": MILLION}, judge_usage={"completion_tokens": MILLION})
    assert bench_run.main(args(tmp_path, "baseline"), chat=chat) == 0
    out = tmp_path / "results"
    rows = [json.loads(line) for line in (out / "baseline-n1-seed7-T1T2.jsonl").read_text().splitlines()]
    assert [(r["uid"], r["type"], r["dim"], r["correct"]) for r in rows] == [
        ("a1", "T1", "dim1_query", True), ("a1", "T1", "dim2_query", False), ("a1", "T1", "dim3_query", True),
        ("b1", "T2", "dim1_query", True), ("b1", "T2", "dim2_query", False), ("b1", "T2", "dim3_query", True)]
    assert {(r["condition"], r["judge_model"]) for r in rows} == {("baseline", ULTRA)}
    assert [r["cost_usd"] for r in rows] == [pytest.approx(0.06 + 1.0)] * 6  # $0.06 answer + $3 judge / 3
    md = (out / "baseline-n1-seed7-T1T2.md").read_text()
    assert f"- judge model: {ULTRA}" in md
    assert "- cost: $6.3600 (projected $" in md  # 2 instances x (3 x $0.06 + $3)
    assert "| T1 | 1/1 (100%) | 0/1 (0%) | 1/1 (100%) |\n| T2 | 1/1 (100%) | 0/1 (0%) | 1/1 (100%) |\n" in md
    assert "projected cost $" in capsys.readouterr().out


def test_a_projection_above_the_cap_refuses_before_any_call(tmp_path, capsys):
    calls = []
    assert bench_run.main(args(tmp_path, "baseline", cap="0.0001"), chat=fake_chat(calls)) == 2
    assert calls == []
    assert not (tmp_path / "results").exists()
    assert "refused" in capsys.readouterr().err


@pytest.mark.parametrize("condition, s6", [("ours", SUPER), ("ours-ultra", ULTRA)])
def test_ours_dry_run_with_fake_ingest_and_answer(tmp_path, condition, s6):
    models = []

    def answer(store, question, chat):
        return Answer("ok", PremiseReport([], []), 0.0)

    def ingest(store, session, chat, s6_model):
        models.append(s6_model)

    assert bench_run.main(args(tmp_path, condition), chat=fake_chat(), ingest=ingest, answer=answer) == 0
    out = tmp_path / "results"
    rows = [json.loads(line) for line in (out / f"{condition}-n1-seed7-T1T2.jsonl").read_text().splitlines()]
    assert {r["condition"] for r in rows} == {condition} and len(rows) == 6
    assert set(models) == {s6}


def test_eval_row_round_trips_through_jsonl(tmp_path):
    row = bench_run.rows_for(instance(), "baseline", {d: ("a", 0.0) for d in DIMS}, dict.fromkeys(DIMS, True), 0.0)[0]
    assert bench_run.EvalRow(**json.loads(json.dumps(asdict(row)))) == row


def test_a_paid_run_records_every_live_reply():
    """The benchmark is the one caller that saves replies to cache/, so a rerun replays instead of paying."""
    assert inspect.signature(bench_run.main).parameters["chat"].default.keywords == {"record": True}


def test_capped_refuses_every_call_once_actual_spend_reaches_the_cap():
    calls = []
    # each call: 1,000 Ultra input tokens = $0.001; spend before calls 1-3 is 0, 0.001, 0.002 (< 0.0025), then 0.003
    chat = bench_run.capped(fake_chat(calls, answer_usage={"prompt_tokens": 1000}), 0.0025)
    for _ in range(3):
        chat(ULTRA, [{"role": "user", "content": "q"}])
    with pytest.raises(bench_run.CapReached, match=r"\$0\.0030 reached the \$0\.00 cap"):
        chat(ULTRA, [{"role": "user", "content": "q"}])
    assert len(calls) == 3


def test_capped_counts_replies_cut_off_at_max_tokens():
    calls = []

    def cut(model, messages, **kw):
        calls.append(model)
        raise bench_run.llm.Truncated(ULTRA, {"prompt_tokens": 1000})  # $0.001 each, billed though refused

    chat = bench_run.capped(cut, 0.0025)
    for _ in range(3):
        with pytest.raises(bench_run.llm.Truncated):
            chat(ULTRA, [])
    with pytest.raises(bench_run.CapReached):
        chat(ULTRA, [])
    assert len(calls) == 3


def test_a_run_whose_actual_spend_passes_the_cap_stops_with_no_table(tmp_path, capsys):
    # the projection for these tiny records is far below $3.20, but the run costs $6.36 (see the dry run above):
    # finishing both instances would need a call to start after more than $3.20 was spent
    chat = fake_chat(answer_usage={"prompt_tokens": MILLION}, judge_usage={"completion_tokens": MILLION})
    assert bench_run.main(args(tmp_path, "baseline", cap="3.2"), chat=chat) == 3
    assert "stopped: actual spend" in capsys.readouterr().err
    assert not (tmp_path / "results" / "baseline-n1-seed7-T1T2.md").exists()
