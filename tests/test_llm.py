"""The model client, replay cache and price on two real Token Factory responses (tests/recorded/) and hand-written
ones."""
import hashlib
import io
import json
from pathlib import Path

import pytest

from life import llm
from life.constants import SUPER, ULTRA

RECORDED = Path(__file__).parent / "recorded"
ULTRA_REPLY = json.loads((RECORDED / "ultra_think_changes.json").read_text())
SUPER_REPLY = json.loads((RECORDED / "super_think_premise.json").read_text())


def response(content, finish="stop"):
    return {"model": "m", "choices": [{"finish_reason": finish, "message": {"content": content}}], "usage": {}}


def record(directory, body, d):
    raw = json.dumps(body, sort_keys=True).encode()
    (directory / f"{hashlib.sha256(raw).hexdigest()}.json").write_text(json.dumps(d))


def test_price_charges_cached_input_at_cached_rate():
    # 11,728 fresh x $1 + 4,352 cached x $0.12 + 9,231 out x $3, per million
    assert llm.price(ULTRA, ULTRA_REPLY["usage"]) == pytest.approx(0.03994324)
    assert llm.price(SUPER, SUPER_REPLY["usage"]) == pytest.approx(0.00645)  # 16,217 x $0.30 + 1,761 x $0.90


def test_thinking_reply_is_the_answer_not_the_reasoning():
    text = llm.reply(ULTRA_REPLY, think=True)
    assert text.startswith("OLD (2023-06-13 10:30) -> NEW (2024-06-13 10:30)")
    assert llm.reply(SUPER_REPLY, think=True).startswith('{"assumptions"')


def test_quoted_marker_does_not_split():
    # an early pilot's defect: the model quoted the instruction while thinking, and a split on any 'FINAL:' kept
    # the reasoning
    text = "I must output a line 'FINAL:' followed by the list.\nOLD (a) -> NEW (b): why"
    assert llm.reply(response(text), think=True) == text


def test_answer_follows_last_marker():
    assert llm.reply(response("draft\nFINAL: one\nmore thought\nFINAL: two"), think=True) == "two"


def test_marker_kept_when_thinking_off():
    assert llm.reply(response("FINAL: x"), think=False) == "FINAL: x"


def test_truncated_reply_refused():
    with pytest.raises(ValueError, match="truncated"):
        llm.reply(response("OLD (a) -> NEW", finish="length"), think=True)


def test_replay_miss_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFE_CACHE", str(tmp_path))
    monkeypatch.setenv("REPLAY", "1")
    with pytest.raises(LookupError, match="REPLAY=1 and no recording"):  # KeyError (no key) is a LookupError too
        llm.cached({"model": SUPER, "messages": []})


@pytest.mark.parametrize("record", [False, True])
def test_a_live_reply_is_saved_only_when_recording(tmp_path, monkeypatch, record):
    """The app never asks to record, so a visitor's words never reach cache/; the benchmark does."""
    monkeypatch.setenv("LIFE_CACHE", str(tmp_path))
    monkeypatch.delenv("REPLAY", raising=False)
    monkeypatch.setenv("NEBIUS_API_KEY", "fake")  # never sent: urlopen is replaced below
    reply = json.dumps(response("hi")).encode()
    monkeypatch.setattr(llm.urllib.request, "urlopen", lambda req, timeout: io.BytesIO(reply))
    kw = {"record": True} if record else {}  # the default is what the app and Hermes use
    assert llm.chat(SUPER, [{"role": "user", "content": "my own words"}], **kw) == ("hi", {})
    assert len(list(tmp_path.iterdir())) == (1 if record else 0)


class Server:
    """urlopen stand-in: answers each call with the next status (an int is an HTTP error, a dict a reply)."""
    def __init__(self, *answers):
        self.answers, self.calls, self.waits = list(answers), 0, []

    def __call__(self, req, timeout):
        self.calls += 1
        a = self.answers.pop(0)
        if isinstance(a, int):
            raise llm.urllib.error.HTTPError(req.full_url, a, "", {}, None)
        return io.BytesIO(json.dumps(a).encode())


@pytest.fixture
def server(monkeypatch):
    def install(*answers):
        s = Server(*answers)
        monkeypatch.setattr(llm.urllib.request, "urlopen", s)
        monkeypatch.setattr(llm.time, "sleep", s.waits.append)
        return s
    return install


def request():
    return llm.urllib.request.Request(llm.URL, b"{}")


def test_overloaded_and_rate_limited_calls_are_retried_after_each_wait(server):
    s = server(529, 429, response("ok"))
    assert llm.post(request()) == response("ok")
    assert (s.calls, s.waits) == (3, [5, 20])


def test_retries_end_after_the_last_wait_with_the_servers_error(server):
    s = server(503, 503, 503, 529)
    with pytest.raises(llm.urllib.error.HTTPError, match="529"):
        llm.post(request())
    assert (s.calls, s.waits) == (4, [5, 20, 60])


def test_a_client_error_is_not_waited_on(server):
    s = server(400, 400)
    with pytest.raises(llm.urllib.error.HTTPError, match="400"):
        llm.post(request())
    assert (s.calls, s.waits) == (1, [])  # sent once, not again just to raise


def test_billed_charges_a_cut_off_reply_and_still_refuses_it():
    added = []

    def cut(model, messages, **kw):
        raise llm.Truncated(SUPER, {"prompt_tokens": 1000, "completion_tokens": 12000})

    with pytest.raises(llm.Truncated, match="max_tokens"):
        llm.billed(cut, added.append, SUPER, [])
    assert added == [pytest.approx((1000 * 0.30 + 12000 * 0.90) / 1e6)]  # 0.0111


def test_billed_passes_a_whole_reply_and_its_price():
    added = []
    assert llm.billed(lambda m, msgs, **kw: ("ok", {"completion_tokens": 1000}), added.append, SUPER, []) == (
        "ok", {"completion_tokens": 1000})
    assert added == [pytest.approx(0.0009)]


def test_a_cut_off_reply_carries_its_usage():
    d = {"model": SUPER, "usage": {"completion_tokens": 8000}, "choices": [{"finish_reason": "length", "message": {}}]}
    with pytest.raises(llm.Truncated) as e:
        llm.reply(d, think=True)
    assert e.value.usage == {"completion_tokens": 8000}


@pytest.mark.parametrize("marker", ["FINAL:", "FIN:", "FINY:", "FINYAL:", "FINIAL:", "FINAY:", "FINARY:"])
def test_every_spelling_super_used_for_the_marker_splits(marker):
    """A recorded change-judge reply began 'FIN: [{"old_id": "s12f0", ...' and lost the change its scenario turns on."""
    assert llm.reply(response(f"draft [x]\n{marker} [1]"), think=True) == "[1]"


def test_cache_key_ignores_key_order(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFE_CACHE", str(tmp_path))
    monkeypatch.setenv("REPLAY", "1")
    record(tmp_path, {"a": 1, "b": 2}, response("hit"))
    assert llm.cached({"b": 2, "a": 1}) == response("hit")


def test_chat_sends_thinking_flag_and_json_mode(tmp_path, monkeypatch):
    monkeypatch.setenv("LIFE_CACHE", str(tmp_path))
    monkeypatch.setenv("REPLAY", "1")
    msgs = [{"role": "user", "content": "hi"}]
    body = {"model": SUPER, "messages": msgs, "max_tokens": 4000, "temperature": 0,
            "chat_template_kwargs": {"enable_thinking": False}, "response_format": {"type": "json_object"}}
    record(tmp_path, body, response('{"ok": true}'))
    assert llm.chat(SUPER, msgs, json_mode=True) == ('{"ok": true}', {})
