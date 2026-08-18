"""Manages named AI provider profiles (API key + optional model/api-base)
used by the shared LLM client (llm.py), so `yuno larp`/`yuno curate` don't
need YUNOBALLIZER_API_KEY exported in every shell.

Mirrors auth.py's saved-Instagram-session pattern: multiple profiles can
be saved side by side under different names (e.g. "groq", "openrouter"),
one is marked active, and `switch` flips between them without needing to
reconfigure anything.
"""
from __future__ import annotations

import getpass
import json
from pathlib import Path

from . import config


def _profiles_dir() -> Path:
    return config.CONFIG_DIR / "brain" / "profiles"


def _active_file() -> Path:
    return config.CONFIG_DIR / "brain" / "active_profile"


def _profile_file(name: str) -> Path:
    return _profiles_dir() / f"{name}.json"


def saved_profiles() -> list[str]:
    """Names of saved brain profiles, sorted alphabetically."""
    profiles_dir = _profiles_dir()
    if not profiles_dir.exists():
        return []
    return sorted(p.stem for p in profiles_dir.glob("*.json"))


def active_profile_name() -> str | None:
    """The name of the profile other commands use by default, if any."""
    active_file = _active_file()
    if not active_file.exists():
        return None
    name = active_file.read_text(encoding="utf-8").strip()
    return name or None


def _set_active(name: str) -> None:
    active_file = _active_file()
    active_file.parent.mkdir(parents=True, exist_ok=True)
    active_file.write_text(name + "\n", encoding="utf-8")
    active_file.chmod(0o600)


def read_profile(name: str) -> dict | None:
    """A saved profile's settings ({"api_key", "model"?, "api_base"?}), if any."""
    path = _profile_file(name)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def active_profile() -> dict | None:
    """The active profile's settings, if any is set and saved."""
    name = active_profile_name()
    if name is None:
        return None
    return read_profile(name)


def save_profile(
    name: str, api_key: str, model: str | None = None, api_base: str | None = None
) -> None:
    """Save (or overwrite) a named profile and make it the active one."""
    if not api_key:
        raise ValueError("An API key is required")

    profiles_dir = _profiles_dir()
    profiles_dir.mkdir(parents=True, exist_ok=True)
    profiles_dir.chmod(0o700)

    data = {"api_key": api_key}
    if model:
        data["model"] = model
    if api_base:
        data["api_base"] = api_base

    path = _profile_file(name)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    path.chmod(0o600)
    _set_active(name)


def configure(name: str) -> None:
    """Interactively prompt for an API key (hidden) and optional
    model/api-base, then save and activate the named profile."""
    api_key = getpass.getpass(
        f"API key for {name!r} (hidden, e.g. a free key at https://console.groq.com/keys): "
    ).strip()
    if not api_key:
        raise SystemExit("An API key is required.")
    model = input("Model [Enter for the provider's default]: ").strip()
    api_base = input("API base URL [Enter for Groq's default]: ").strip()

    save_profile(name, api_key, model=model or None, api_base=api_base or None)
    print(f"Saved and activated brain profile {name!r}.")


def remove_profile(name: str) -> None:
    """Delete a saved profile, clearing it as active if it was."""
    path = _profile_file(name)
    if not path.exists():
        raise SystemExit(f"No saved brain profile named {name!r}.")
    path.unlink()
    if active_profile_name() == name:
        _active_file().unlink(missing_ok=True)


def switch(name: str | None = None) -> str:
    """Switch the active profile; with no name, cycles to the next saved one."""
    names = saved_profiles()
    if not names:
        raise SystemExit("No saved brain profiles. Run `yuno brain config <name>` first.")

    if name is None:
        if len(names) == 1:
            raise SystemExit(
                f"Only one saved profile ({names[0]!r}) -- nothing to switch to. "
                "Run `yuno brain config <name>` to add another."
            )
        current = active_profile_name()
        index = (names.index(current) + 1) % len(names) if current in names else 0
        name = names[index]
    elif name not in names:
        raise SystemExit(f"No saved brain profile named {name!r}. Check `yuno brain list`.")

    _set_active(name)
    return name


def describe(name: str) -> str:
    """A one-line 'name (model: ..., endpoint: ...)' summary of a saved profile."""
    profile = read_profile(name) or {}
    model = profile.get("model") or "(provider default)"
    api_base = profile.get("api_base") or "(provider default)"
    return f"{name} (model: {model}, endpoint: {api_base})"


def describe_active() -> str:
    """A one-line summary of the active profile, for the bare `yuno brain` command."""
    name = active_profile_name()
    if name is None:
        return "No active brain profile. Run `yuno brain config <name>` to set one up."
    return f"Your brain is: {describe(name)}"
