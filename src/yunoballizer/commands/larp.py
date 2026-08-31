"""Generates comment/caption text via a shared LLM client (see llm.py),
trained on per-style saved templates kept in $CONFIG_DIR/larp.json (one
JSON list of template strings per style/alias).

Templates get there two ways: `yuno larp add/list/remove/rename/delete`,
and `yuno select`'s 'c' key, which files the item you're currently looking
at -- its own downloaded caption -- into a style you pick while browsing.
A fully separate action from picking favorites with 's' (see select.py),
just another way of writing into the same JSON.

Styles are kept as separate lists rather than one shared pool so that
different voices/formats (e.g. a chatty travel-caption style vs a terse
one-liner style) don't blend into an incoherent average when generating.
Each template is stored as its own JSON string, so a caption that itself
spans multiple paragraphs (blank lines and all) round-trips intact instead
of being mistaken for several separate templates.

Generation itself is a few-shot text generator: a style's saved templates
go in as examples, and the model is asked for one new example in the same
voice. Needs a free API key in $YUNOBALLIZER_API_KEY
(https://console.groq.com/keys for the default Groq provider) -- only
`generate()` needs it; every template-storage function above works
without one. Never degrades silently on failure (missing key, rate limit,
network error, etc. all raise an actionable SystemExit) since the call is
the entire point of running `yuno larp`, not a background best-effort
signal.
"""
from __future__ import annotations

import json
import re

from .. import config, llm, termui

_STYLE_NAME_RE = re.compile(r"^[A-Za-z0-9가-힣_-]{1,50}$")

DEFAULT_MAX_EXAMPLES = 8


def _validate_style_name(style: str) -> str:
    style = style.strip()
    if not _STYLE_NAME_RE.match(style):
        raise ValueError(
            f"Invalid style name {style!r}: use letters, numbers, '-' or '_' only (max 50 chars)"
        )
    return style


def _load_styles() -> dict[str, list[str]]:
    if not config.LARP_PATH.exists():
        return {}
    try:
        raw = json.loads(config.LARP_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Could not read {config.LARP_PATH}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SystemExit(f"Invalid {config.LARP_PATH}: expected a JSON object.")
    return raw


def _save_styles(styles: dict[str, list[str]]) -> None:
    config.write_json_atomic(config.LARP_PATH, styles)


def list_styles() -> list[str]:
    """Return known style names (aliases), sorted."""
    return sorted(_load_styles())


def read_templates(style: str) -> list[str]:
    """Return a style's saved templates, or [] if the style doesn't exist."""
    return list(_load_styles().get(_validate_style_name(style), []))


def add_template(style: str, text: str) -> None:
    """Append a new template to a style's list, creating the style if needed."""
    style = _validate_style_name(style)
    text = text.strip()
    if not text:
        raise ValueError("Template text must not be empty")

    styles = _load_styles()
    styles.setdefault(style, []).append(text)
    _save_styles(styles)


def remove_template(style: str, index: int) -> str:
    """Remove and return the template at `index` within a style (see `read_templates`/`yuno larp list <style>`).

    Drops the style (its alias) once its last template is removed.
    """
    style = _validate_style_name(style)
    styles = _load_styles()
    templates = styles.get(style, [])
    if index < 0 or index >= len(templates):
        raise IndexError(f"No template at index {index} in style {style!r}")
    removed = templates.pop(index)

    if templates:
        styles[style] = templates
    else:
        styles.pop(style, None)
    _save_styles(styles)
    return removed


def rename_style(old: str, new: str) -> None:
    """Rename a style's alias."""
    old = _validate_style_name(old)
    new = _validate_style_name(new)
    styles = _load_styles()
    if old not in styles:
        raise SystemExit(f"No such style: {old!r}")
    if new in styles:
        raise SystemExit(f"Style {new!r} already exists")
    styles[new] = styles.pop(old)
    _save_styles(styles)


def delete_style(style: str) -> None:
    """Delete a style and all of its saved templates."""
    style = _validate_style_name(style)
    styles = _load_styles()
    if style not in styles:
        raise SystemExit(f"No such style: {style!r}")
    del styles[style]
    _save_styles(styles)


def _render_browse_item(style: str, templates: list[str], index: int) -> None:
    print("\x1b[2J\x1b[H", end="")
    # Index is shown alongside position so it can be copied straight into
    # `yuno larp remove <style> <index>` -- the only other place indices matter.
    print(f"{style}: index {index} ({index + 1}/{len(templates)})")
    print()
    print(templates[index])
    print()
    print("<-/-> move   Enter/q quit")


def browse(style: str) -> None:
    """Interactively page through a style's saved templates with the arrow keys."""
    templates = read_templates(style)
    if not templates:
        raise SystemExit(f"No saved templates for style {style!r}.")

    index = 0
    _render_browse_item(style, templates, index)
    while True:
        key = termui.read_key()
        if key in ("\r", "\n", "q", "\x03", "esc"):
            break
        elif key in ("left", "up"):
            index = max(index - 1, 0)
        elif key in ("right", "down"):
            index = min(index + 1, len(templates) - 1)
        else:
            continue
        _render_browse_item(style, templates, index)


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


def generate(
    style: str | None = None,
    count: int = 1,
    model: str | None = None,
    api_base: str | None = None,
    language: str | None = None,
    timeout: int = llm.DEFAULT_TIMEOUT,
    max_examples: int = DEFAULT_MAX_EXAMPLES,
    max_tokens: int = llm.DEFAULT_MAX_TOKENS,
) -> list[str]:
    api_key = llm.resolve_api_key()
    if not api_key:
        raise SystemExit(
            f"{llm.API_KEY_ENV} is not set. Run `yuno brain config` to save one "
            f"(get a free key at https://console.groq.com/keys), or `export "
            f"{llm.API_KEY_ENV}=...` before running `yuno larp`."
        )

    corpus = build_corpus(style=style)
    if not corpus:
        raise SystemExit(
            "No larp templates found.\n"
            'Add one with `yuno larp add <style> "..."`, the \'c\' key in `yuno select`, '
            f"or edit {config.LARP_PATH} directly."
        )

    prompt = _build_prompt(corpus[:max_examples], language=language)

    results = []
    for _ in range(count):
        try:
            results.append(llm.call(
                prompt, api_key=api_key, model=model, api_base=api_base,
                timeout=timeout, max_tokens=max_tokens,
            ))
        except llm.LlmError as exc:
            raise SystemExit(str(exc)) from exc
    return results
