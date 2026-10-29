"""S8 check_premises and S9 answer: goldens 1, 2, 3 with a fake chat and hand-written replies, plus bad replies."""
import json
from pathlib import Path

import pytest

from life import llm, query
from life.constants import SUPER
from life.store import Store
from life.types import Fact

BIKE = Fact("f1", "user", "commute", "bikes 10 miles to work daily", "2026-03-01 08:30", 0, "stale", "f2",
            "a leg in a cast stops cycling")
CAST = Fact("f2", "user", "health", "leg in a cast for six weeks", "2026-03-22 19:05", 1)
BAKERY = Fact("f3", "user", "job", "works at a bakery", "2026-02-10 12:00", 0)
CAT = Fact("f4", "user", "pet", "adopted a cat", "2026-02-24 18:40", 1)
DUBAI = Fact("f5", "user", "residence", "lives in Dubai", "2026-01-10 09:00", 0, "stale", "f6", "moved away")
ABU = Fact("f6", "user", "residence", "moved to Abu Dhabi", "2026-04-02 20:15", 1)
S8_USAGE = {"prompt_tokens": 1000, "completion_tokens": 100}  # (1000 x 0.30 + 100 x 0.90) / 1e6 = 0.00039
S9_USAGE = {"prompt_tokens": 2000, "completion_tokens": 200}  # (2000 x 0.30 + 200 x 0.90) / 1e6 = 0.00078
RECORDED = json.loads((Path(__file__).parent / "recorded" / "super_think_premise.json").read_text())


def store_of(tmp_path, *facts):
    s = Store(str(tmp_path / "m.db"))
    for f in facts:
        s.put(f)
    return s


def verdicts(*items):
    return json.dumps({"assumptions": [dict(zip(("assumption", "verdict", "fact_id", "reason"), i)) for i in items]})


class Fake:
    """A chat that answers the premise check (think=True) and the answer (think=False) from fixed text."""
    def __init__(self, premise, text="ok"):
        self.premise, self.text, self.calls = premise, text, []

    def __call__(self, model, messages, json_mode=False, think=False, max_tokens=4000):
        self.calls.append({"model": model, "think": think, "messages": messages})
        if think and isinstance(self.premise, Exception):
            raise self.premise
        return (self.premise, S8_USAGE) if think else (self.text, S9_USAGE)


def test_golden1_flags_commute_and_answer_cites_the_date(tmp_path):
    store = store_of(tmp_path, BIKE, CAST)
    reply = json.dumps({"assumptions": [
        {"assumption": "I can bike tomorrow", "verdict": "OUTDATED", "fact_id": "f1", "reason": "cast",
         "invalidated_by": "f9"},
        {"assumption": "the user has a leg", "verdict": "OUTDATED", "fact_id": "f2", "reason": "wrong: f2 is active"},
        {"assumption": "the user has a bike", "verdict": "OUTDATED", "fact_id": "zzz", "reason": "no such fact"}]})
    fake = Fake(reply, "You said on 2026-03-22 your leg is in a cast, so no biking.")
    out = query.answer(store, "Which route should I bike tomorrow?", chat=fake)
    assert out.premise_report.premises == ["I can bike tomorrow", "the user has a leg", "the user has a bike"]
    assert out.premise_report.stale == [{"premise": "I can bike tomorrow", "fact_id": "f1", "invalidated_by": "f2",
                                         "reason": "cast"}]
    assert "2026-03-22" in out.text
    s8, s9 = fake.calls
    assert (s8["model"], s8["think"], s9["model"], s9["think"]) == (SUPER, True, SUPER, False)
    prompt = s8["messages"][0]["content"]
    assert "[f2] (2026-03-22 19:05) user / health: leg in a cast for six weeks" in prompt
    assert ("[f1] (2026-03-01 08:30) user / commute: bikes 10 miles to work daily; STALE, replaced by [f2] "
            "(2026-03-22 19:05) because: a leg in a cast stops cycling") in prompt
    told = s9["messages"][1]["content"]
    assert "OUTDATED: I can bike tomorrow" in told and "newer: [f2] (2026-03-22 19:05)" in told
    assert "begin your reply by correcting it" in s9["messages"][0]["content"]
    assert out.cost_usd == pytest.approx(0.00117)  # 0.00039 + 0.00078


def test_unresolved_and_safe_are_not_flagged(tmp_path):
    store = store_of(tmp_path, BIKE, CAST)
    fake = Fake(verdicts(("I own a bike", "UNRESOLVED", "f1", "not mentioned"), ("leg works", "SAFE", "f1", "")))
    report = query.check_premises(store, "Which route?", chat=fake)
    assert report.premises == ["I own a bike", "leg works"] and report.stale == []


def test_golden2_flags_nothing(tmp_path):
    store = store_of(tmp_path, BAKERY, CAT)
    fake = Fake(verdicts(("the user works at a bakery", "SAFE", "f3", "")), "Try a box of macarons.")
    out = query.answer(store, "Can you suggest a small gift for my coworkers at the bakery?", chat=fake)
    assert out.premise_report.stale == [] and out.text == "Try a box of macarons."
    assert "No assumption was found outdated." in fake.calls[1]["messages"][1]["content"]


def test_golden3_answers_for_abu_dhabi(tmp_path):
    store = store_of(tmp_path, DUBAI, ABU)
    fake = Fake(verdicts(("the user lives in Dubai", "OUTDATED", "f5", "moved")), "In Abu Dhabi it is hot today.")
    out = query.answer(store, "What's the weather like where I live?", chat=fake)
    assert out.premise_report.stale == [{"premise": "the user lives in Dubai", "fact_id": "f5",
                                         "invalidated_by": "f6", "reason": "moved"}]
    told = fake.calls[1]["messages"][1]["content"]
    assert "newer: [f6] (2026-04-02 20:15) user / residence: moved to Abu Dhabi" in told
    assert "Abu Dhabi" in out.text


def test_reason_defaults_to_the_stores_reason(tmp_path):
    store = store_of(tmp_path, BIKE, CAST)
    report = query.check_premises(store, "q", chat=Fake(verdicts(("bike", "OUTDATED", "f1", ""))))
    assert report.stale[0]["reason"] == "a leg in a cast stops cycling"


def test_real_malformed_reply_gives_empty_report_and_answer_still_runs(tmp_path):
    store = store_of(tmp_path, BIKE, CAST)
    fake = Fake(llm.reply(RECORDED, think=True), "plain answer")  # an unquoted string inside the JSON
    out = query.answer(store, "q", chat=fake)
    assert out.premise_report.premises == [] and out.premise_report.stale == []
    # a reply that does not parse is still billed: 0.00039 (S8) + 0.00078 (S9)
    assert out.text == "plain answer" and out.cost_usd == pytest.approx(0.00117)


@pytest.mark.parametrize("bad", ['{"nothing": 1}', '{"assumptions": 5}', '{"assumptions": [5]}', "no json here", ""])
def test_unusable_reply_gives_empty_report(tmp_path, bad):
    report = query.check_premises(store_of(tmp_path, BIKE, CAST), "q", chat=Fake(bad))
    assert report.premises == [] and report.stale == []


def test_truncated_reply_gives_empty_report_and_answer_runs(tmp_path):
    fake = Fake(llm.Truncated(SUPER, S8_USAGE), "still answered")
    out = query.answer(store_of(tmp_path, BIKE, CAST), "q", chat=fake)
    assert out.premise_report.stale == [] and out.text == "still answered"
    assert out.cost_usd == pytest.approx(0.00117)  # the cut-off S8 reply is billed too: 0.00039 + 0.00078
