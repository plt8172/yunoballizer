"""Shared client for an OpenAI-compatible chat completions API.

Used by both `yuno larp` (text generation) and `yuno curate` (optional
AI-assisted keep/skip judgment), so the whole app configures one
provider/model/key instead of each feature maintaining its own. Talks
over plain HTTP using only the stdlib -- no new dependency -- to Groq's
free-tier Llama models by default, or any other provider with the same
request/response shape via YUNOBALLIZER_API_BASE/--api-base.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from . import brain

DEFAULT_API_BASE = "https://api.groq.com/openai/v1/chat/completions"
API_BASE_ENV = "YUNOBALLIZER_API_BASE"
API_KEY_ENV = "YUNOBALLIZER_API_KEY"
MODEL_ENV = "YUNOBALLIZER_MODEL"
DEFAULT_MODEL = "llama-3.3-70b-versatile"
DEFAULT_TIMEOUT = 30
# Generous enough that a reasoning/thinking model (which can spend hundreds
# of tokens on hidden reasoning before it says anything visible) still has
# room left to produce an actual answer, not just get cut off mid-thought.
DEFAULT_MAX_TOKENS = 800


class LlmError(Exception):
    """A chat-completion request failed. Callers decide whether that's fatal
    (SystemExit, e.g. when the call is the whole point of the command) or a
    soft skip (e.g. one best-effort signal among several in a batch)."""


def resolve_model(model: str | None = None) -> str:
    return (
        model
        or os.environ.get(MODEL_ENV)
        or (brain.active_profile() or {}).get("model")
        or DEFAULT_MODEL
    )


def resolve_api_base(api_base: str | None = None) -> str:
    return (
        api_base
        or os.environ.get(API_BASE_ENV)
        or (brain.active_profile() or {}).get("api_base")
        or DEFAULT_API_BASE
    )


def resolve_api_key() -> str | None:
    return os.environ.get(API_KEY_ENV) or (brain.active_profile() or {}).get("api_key")


def call(
    prompt: str,
    *,
    api_key: str,
    model: str | None = None,
    api_base: str | None = None,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    temperature: float = 0.9,
    timeout: int = DEFAULT_TIMEOUT,
) -> str:
    """POST a single-turn chat completion; return the stripped response text.

    Resolves `model`/`api_base` internally, so callers can pass a raw CLI
    override (possibly None) straight through. Raises `LlmError` -- not
    SystemExit -- on any failure, so callers can decide how to react.
    """
    resolved_model = resolve_model(model)
    resolved_api_base = resolve_api_base(api_base)

    payload = json.dumps({
        "model": resolved_model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode("utf-8")
    req = urllib.request.Request(
        resolved_api_base, data=payload, method="POST",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in (401, 403):
            hint = (
                "get a free key at https://console.groq.com/keys"
                if resolved_api_base == DEFAULT_API_BASE
                else "check the key for your configured provider"
            )
            raise LlmError(
                f"Request rejected the API key (HTTP {exc.code}). Run `yuno brain config` "
                f"to save a new one, check {API_KEY_ENV}, or {hint}."
            ) from exc
        if exc.code == 429:
            hint = (
                " or check https://console.groq.com/settings/limits"
                if resolved_api_base == DEFAULT_API_BASE else ""
            )
            raise LlmError(f"Hit a rate limit (HTTP 429). Wait a bit and try again{hint}.") from exc
        raise LlmError(f"Request failed: HTTP {exc.code} {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise LlmError(f"Could not reach {resolved_api_base} ({exc.reason}). Check your internet connection.") from exc
    except json.JSONDecodeError as exc:
        raise LlmError(f"Got an unparseable response: {exc}") from exc

    choice = body.get("choices", [{}])[0] if body.get("choices") else {}
    message = choice.get("message") or {}
    text = message.get("content")
    if text is None:
        if choice.get("finish_reason") == "length":
            raise LlmError(
                f"Model {resolved_model!r} used its whole token budget without "
                "producing a visible response (common with reasoning models "
                "running out of room before they finish thinking). Try a "
                "smaller/non-reasoning model."
            )
        raise LlmError(f"Response was missing the expected completion: {body!r}")
    text = text.strip()
    if not text:
        raise LlmError(f"Got an empty response from model {resolved_model!r}. Try again.")
    return text
