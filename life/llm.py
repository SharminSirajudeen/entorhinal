"""Chat, replay cache and price: the only code that talks to a model (Nebius Token Factory, `NEBIUS_API_KEY` only).

Measured on 28 Oct: with `enable_thinking` on, the reasoning arrives in `reasoning_content` and `content`
is the answer, sometimes behind a `FINAL:` line. Without `enable_thinking: false`, Nemotron writes its thinking into
`content`, so it is always sent.
"""
import hashlib
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path

from life.constants import PRICES

URL = "https://api.tokenfactory.nebius.com/v1/chat/completions"
# With thinking on, the answer follows the last line that starts with the marker the prompts ask for, FINAL:. Super
# also wrote FIN:, FINY:, FINYAL:, FINIAL:, FINAY: and FINARY: (count over cache/, 29 Oct: 785 FINAL, 94 FIN, ...).
MARK = re.compile(r"^FIN[A-Za-z]*:[ \t]*", re.M)
RETRY_WAITS = (5, 20, 60)  # seconds before each retry of a 429 / 5xx (Nebius answered 529, overloaded, on 28 Oct)


def price(model: str, usage: dict) -> float:
    """USD for one call; cached input tokens (usage.prompt_tokens_details.cached_tokens) at the cached rate."""
    rate_in, rate_cached, rate_out = PRICES[model]
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
    fresh = usage.get("prompt_tokens", 0) - cached
    return (fresh * rate_in + cached * rate_cached + usage.get("completion_tokens", 0) * rate_out) / 1e6


class Truncated(ValueError):
    """A reply cut at max_tokens: refused as an answer, yet billed, so it carries the usage that prices it."""

    def __init__(self, model: str, usage: dict):
        super().__init__(f"{model} stopped at max_tokens: truncated reply refused")
        self.usage = usage


def billed(chat, add, model: str, messages: list[dict], **kw) -> tuple[str, dict]:
    """chat, handing each call's price to `add`, a reply cut at max_tokens included: it is refused but billed (in
    the measured run, 53 cut-off Super replies cost $0.77). The refusal still reaches the caller."""
    cut = None
    try:
        text, usage = chat(model, messages, **kw)
    except Truncated as e:
        cut, usage = e, e.usage
    add(price(model, usage))
    if cut:
        raise cut
    return text, usage


def post(req) -> dict:
    """One live call. A 429 or 5xx is tried again after each of RETRY_WAITS; any other error, or the last attempt's,
    propagates. Each request is sent once per pass."""
    for wait in (*RETRY_WAITS, None):
        try:
            with urllib.request.urlopen(req, timeout=900) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            error = e
        if wait is None or (error.code != 429 and error.code < 500):
            raise error
        time.sleep(wait)


def cached(body: dict, record: bool = False) -> dict:
    """The recorded response for this exact request body, from `$LIFE_CACHE` (default cache/), else live; a live
    reply is saved only when `record` (the benchmark), never by default, since the app's requests carry a visitor's
    own words. REPLAY=1 makes a miss an error, so the suite can never spend."""
    raw = json.dumps(body, sort_keys=True).encode()
    path = Path(os.environ.get("LIFE_CACHE", "cache")) / f"{hashlib.sha256(raw).hexdigest()}.json"
    if path.exists():
        return json.loads(path.read_text())
    if os.environ.get("REPLAY") == "1":
        raise LookupError(f"REPLAY=1 and no recording {path}")
    req = urllib.request.Request(URL, raw, headers={
        "Authorization": "Bearer " + os.environ["NEBIUS_API_KEY"], "Content-Type": "application/json"})
    d = post(req)
    if record:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(d))
    return d


def reply(d: dict, think: bool) -> str:
    """The answer in a response. A reply cut at max_tokens is refused, never returned as if whole."""
    choice = d["choices"][0]
    if choice.get("finish_reason") == "length":
        raise Truncated(d.get("model"), d.get("usage", {}))
    text = choice["message"].get("content") or ""
    hits = list(MARK.finditer(text)) if think else []
    return (text[hits[-1].end():] if hits else text).strip()


def chat(model: str, messages: list[dict], json_mode: bool = False, think: bool = False,
         max_tokens: int = 4000, record: bool = False) -> tuple[str, dict]:
    """(answer text, usage). Temperature 0; thinking off unless asked; `record` saves a live reply."""
    body = {"model": model, "messages": messages, "max_tokens": max_tokens, "temperature": 0,
            "chat_template_kwargs": {"enable_thinking": think}}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    d = cached(body, record)
    return reply(d, think), d.get("usage", {})
