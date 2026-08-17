"""Generates comment/caption text via the Groq API, trained on per-style
saved templates under $CONFIG_DIR/larp/styles/ (one file per style/alias).

Templates get there two ways: `yuno larp add/list/remove/rename/delete`
(or editing a style's file directly), and `yuno select`'s 'c' key, which
files the item you're currently looking at -- its own downloaded caption
-- into a style you pick while browsing. A fully separate action from
picking favorites with 's' (see select.py), just another way of writing
into the same template files.

Styles are kept in separate files rather than one shared pool so that
different voices/formats (e.g. a chatty travel-caption style vs a terse
one-liner style) don't blend into an incoherent average when generating.

Generation itself calls an OpenAI-compatible chat completions endpoint
(Groq's free-tier Llama models by default; any provider with the same
request/response shape works -- OpenRouter, Together, a local vLLM/LM
Studio server, etc. -- via --api-base/--model) as a few-shot text
generator: a style's saved templates go in as examples, and the model is
asked for one new example in the same voice. Needs a free API key in
$YUNOBALLIZER_API_KEY (https://console.groq.com/keys for the Groq
default) -- only `generate()` needs it; every template-storage function
above works without one. Talks over plain HTTP using only the stdlib (no
new dependency), and never degrades silently on failure (missing key,
rate limit, network error, etc. all raise an actionable SystemExit) since
the call is the entire point of running `yuno larp`, not a background
best-effort signal.
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from . import config

_STYLE_NAME_RE = re.compile(r"^[A-Za-z0-9가-힣_-]{1,50}$")

DEFAULT_API_BASE = "https://api.groq.com/openai/v1/chat/completions"
API_BASE_ENV = "YUNOBALLIZER_API_BASE"
API_KEY_ENV = "YUNOBALLIZER_API_KEY"
MODEL_ENV = "YUNOBALLIZER_MODEL"
DEFAULT_MODEL = "llama-3.3-70b-versatile"
DEFAULT_TIMEOUT = 30
DEFAULT_MAX_EXAMPLES = 8


def _validate_style_name(style: str) -> str:
    style = style.strip()
    if not _STYLE_NAME_RE.match(style):
        raise ValueError(
            f"Invalid style name {style!r}: use letters, numbers, '-' or '_' only (max 50 chars)"
        )
    return style


def _style_path(style: str) -> Path:
    return config.LARP_STYLES_DIR / f"{_validate_style_name(style)}.txt"


def list_styles() -> list[str]:
    """Return known style names (aliases), sorted, one per templates file under larp/styles/."""
    if not config.LARP_STYLES_DIR.exists():
        return []
    return sorted(p.stem for p in config.LARP_STYLES_DIR.glob("*.txt"))


def read_templates(style: str) -> list[str]:
    """Parse blank-line-separated template blocks from a style's file, skipping comment lines."""
    path = _style_path(style)
    if not path.exists():
        return []

    blocks: list[str] = []
    current: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("#"):
            continue
        if not line:
            if current:
                blocks.append("\n".join(current))
                current = []
            continue
        current.append(raw_line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def add_template(style: str, text: str) -> None:
    """Append a new template block to a style's file, creating the style if needed."""
    text = text.strip()
    if not text:
        raise ValueError("Template text must not be empty")

    path = _style_path(style)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    with path.open("a", encoding="utf-8") as f:
        if existing.strip():
            if not existing.endswith("\n"):
                f.write("\n")
            f.write("\n")
        f.write(text + "\n")


def get_template(style: str, index: int) -> str:
    """Return the full text of the template at `index` within a style (see `yuno larp list <style>`)."""
    templates = read_templates(style)
    if index < 0 or index >= len(templates):
        raise IndexError(f"No template at index {index} in style {style!r}")
    return templates[index]


def remove_template(style: str, index: int) -> str:
    """Remove and return the template at `index` within a style (see `read_templates`/`yuno larp list <style>`).

    Deletes the style's file (dropping the alias) once its last template is removed.
    """
    templates = read_templates(style)
    if index < 0 or index >= len(templates):
        raise IndexError(f"No template at index {index} in style {style!r}")
    removed = templates.pop(index)

    path = _style_path(style)
    if templates:
        path.write_text("\n\n".join(templates) + "\n", encoding="utf-8")
    else:
        path.unlink(missing_ok=True)
    return removed


def rename_style(old: str, new: str) -> None:
    """Rename a style's alias by renaming its underlying templates file."""
    old_path = _style_path(old)
    new_path = _style_path(new)
    if not old_path.exists():
        raise SystemExit(f"No such style: {old!r}")
    if new_path.exists():
        raise SystemExit(f"Style {new!r} already exists")
    new_path.parent.mkdir(parents=True, exist_ok=True)
    old_path.rename(new_path)


def delete_style(style: str) -> None:
    """Delete a style and all of its saved templates."""
    path = _style_path(style)
    if not path.exists():
        raise SystemExit(f"No such style: {style!r}")
    path.unlink()


def build_corpus(style: str | None = None) -> list[str]:
    styles = list_styles()
    if style is not None:
        if style not in styles:
            known = ", ".join(styles) if styles else "(none saved yet)"
            raise SystemExit(f"No such style: {style!r}. Known styles: {known}")
        return read_templates(style)
    if len(styles) == 1:
        return read_templates(styles[0])
    if len(styles) > 1:
        raise SystemExit(
            "Multiple template styles saved -- pick one with --style to avoid mixing them.\n"
            f"Known styles: {', '.join(styles)}"
        )
    return []


def _build_prompt(examples: list[str], language: str | None = None) -> str:
    blocks = "\n\n".join(f"Example {i}:\n{t}" for i, t in enumerate(examples, 1))
    language_instruction = (
        f" Write it in {language}, even if the examples above are in a different language."
        if language else ""
    )
    return (
        "You are helping write a new social media comment/caption in a specific "
        "personal style. Below are real examples of that style.\n\n"
        f"{blocks}\n\n"
        "Write ONE new example in the same voice, tone, length, and formatting "
        "(hashtags, emoji, capitalization, punctuation) as the examples above."
        f"{language_instruction} "
        "Do not copy any example verbatim -- write something new that could "
        "plausibly belong to the same collection. Output only the new example "
        "itself, with no quotation marks, labels, or explanation before or after it."
    )


def _resolve_model(model: str | None) -> str:
    return model or os.environ.get(MODEL_ENV) or DEFAULT_MODEL


def _resolve_api_base(api_base: str | None) -> str:
    return api_base or os.environ.get(API_BASE_ENV) or DEFAULT_API_BASE


def _call_llm(prompt: str, *, api_key: str, model: str, api_base: str, timeout: int) -> str:
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.9,
        "max_tokens": 200,
    }).encode("utf-8")
    req = urllib.request.Request(
        api_base, data=payload, method="POST",
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
                if api_base == DEFAULT_API_BASE
                else "check the key for your configured provider"
            )
            raise SystemExit(
                f"Request rejected the API key (HTTP {exc.code}). Check {API_KEY_ENV}, or {hint}."
            ) from exc
        if exc.code == 429:
            hint = (
                " or check https://console.groq.com/settings/limits"
                if api_base == DEFAULT_API_BASE else ""
            )
            raise SystemExit(
                f"Hit a rate limit (HTTP 429). Wait a bit and try again{hint}."
            ) from exc
        raise SystemExit(f"Request failed: HTTP {exc.code} {exc.reason}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(f"Could not reach {api_base} ({exc.reason}). Check your internet connection.") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Got an unparseable response: {exc}") from exc

    try:
        text = body["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise SystemExit(f"Response was missing the expected completion: {exc}") from exc
    if not text:
        raise SystemExit(f"Got an empty response from model {model!r}. Try again.")
    return text


def generate(
    style: str | None = None,
    count: int = 1,
    model: str | None = None,
    api_base: str | None = None,
    language: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    max_examples: int = DEFAULT_MAX_EXAMPLES,
) -> list[str]:
    api_key = os.environ.get(API_KEY_ENV)
    if not api_key:
        raise SystemExit(
            f"{API_KEY_ENV} is not set. Get a free key at "
            "https://console.groq.com/keys, then `export "
            f"{API_KEY_ENV}=...` before running `yuno larp`."
        )

    corpus = build_corpus(style=style)
    if not corpus:
        raise SystemExit(
            "No larp templates found.\n"
            'Add one with `yuno larp add <style> "..."`, the \'c\' key in `yuno select`, '
            f"or edit a file under {config.LARP_STYLES_DIR} directly."
        )

    resolved_model = _resolve_model(model)
    resolved_api_base = _resolve_api_base(api_base)
    prompt = _build_prompt(corpus[:max_examples], language=language)

    return [
        _call_llm(prompt, api_key=api_key, model=resolved_model, api_base=resolved_api_base, timeout=timeout)
        for _ in range(count)
    ]
