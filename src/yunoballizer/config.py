"""Manages user-editable configuration and application storage locations.

Follows the XDG Base Directory conventions:

- Data:   $YUNOBALLIZER_DATA_DIR, else $XDG_DATA_HOME/yunoballizer, else ~/.local/share/yunoballizer
- Config: $XDG_CONFIG_HOME/yunoballizer, else ~/.config/yunoballizer
- State:  $XDG_STATE_HOME/yunoballizer, else ~/.local/state/yunoballizer

A relative path in any of these environment variables is rejected outright
(rather than silently falling back) so a typo doesn't quietly redirect where
content is saved.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def _env_path(name: str) -> Path | None:
    value = os.environ.get(name)
    if not value:
        return None
    path = Path(value)
    if not path.is_absolute():
        raise SystemExit(f"{name} must be an absolute path, got: {value!r}")
    return path


def _data_root() -> Path:
    override = _env_path("YUNOBALLIZER_DATA_DIR")
    if override is not None:
        return override
    xdg_data_home = _env_path("XDG_DATA_HOME")
    if xdg_data_home is not None:
        return xdg_data_home / "yunoballizer"
    return Path.home() / ".local" / "share" / "yunoballizer"


def _config_root() -> Path:
    xdg_config_home = _env_path("XDG_CONFIG_HOME")
    if xdg_config_home is not None:
        return xdg_config_home / "yunoballizer"
    return Path.home() / ".config" / "yunoballizer"


def _state_root() -> Path:
    xdg_state_home = _env_path("XDG_STATE_HOME")
    if xdg_state_home is not None:
        return xdg_state_home / "yunoballizer"
    return Path.home() / ".local" / "state" / "yunoballizer"


DATA_DIR = _data_root()
CONFIG_DIR = _config_root()
STATE_DIR = _state_root()

DOWNLOADED_DIR = DATA_DIR / "downloaded"
REVIEW_DIR = DATA_DIR / "review"
SELECTED_DIR = DATA_DIR / "selected"

ARCHIVE_DIR = STATE_DIR / "archives"
SELECTED_PATH = CONFIG_DIR / "selected.json"

LARP_PATH = CONFIG_DIR / "larp.json"

ENV_FILE = CONFIG_DIR / ".env"
INPUT_KEYS = ("instagram", "youtube", "tiktok", "urls")


def inputs_path() -> Path:
    return CONFIG_DIR / "inputs.json"


def _empty_inputs() -> dict[str, list[str]]:
    return {key: [] for key in INPUT_KEYS}


def _validate_input_key(key: str) -> None:
    if key not in INPUT_KEYS:
        raise SystemExit(f"Unknown input key {key!r}. Choose from: {', '.join(INPUT_KEYS)}")


def _normalize_input_values(key: str, values: list[str]) -> list[str]:
    normalized = []
    for value in values:
        value = value.strip()
        if key != "urls":
            value = value.lstrip("@").lower()
        if not value:
            raise SystemExit(f"Invalid {inputs_path()}: {key!r} contains an empty value.")
        if value not in normalized:
            normalized.append(value)
    return normalized


def read_inputs() -> dict[str, list[str]]:
    """Read and validate the unified download inputs."""
    path = inputs_path()
    if not path.exists():
        return _empty_inputs()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Could not read {path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise SystemExit(f"Invalid {path}: expected a JSON object.")
    unknown = set(raw) - set(INPUT_KEYS)
    if unknown:
        raise SystemExit(f"Invalid {path}: unknown key(s): {', '.join(sorted(unknown))}")
    inputs = _empty_inputs()
    for key in INPUT_KEYS:
        values = raw.get(key, [])
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise SystemExit(f"Invalid {path}: {key!r} must be an array of strings.")
        inputs[key] = _normalize_input_values(key, values)
    return inputs


def write_json_atomic(path: Path, data: object) -> None:
    """Write data as JSON to path via a temp file + atomic rename, so a crash
    or concurrent read mid-write can't ever observe a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}-", suffix=".tmp", delete=False
    ) as handle:
        temp_path = Path(handle.name)
        json.dump(data, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    temp_path.replace(path)


def write_inputs(inputs: dict[str, list[str]]) -> None:
    """Atomically write all unified download inputs."""
    normalized = {
        key: _normalize_input_values(key, list(inputs.get(key, [])))
        for key in INPUT_KEYS
    }
    write_json_atomic(inputs_path(), normalized)


def input_values(key: str) -> list[str]:
    _validate_input_key(key)
    return read_inputs()[key]


def set_input_values(key: str, values: list[str]) -> None:
    _validate_input_key(key)
    inputs = read_inputs()
    inputs[key] = values
    write_inputs(inputs)


def add_input(key: str, value: str) -> bool:
    _validate_input_key(key)
    inputs = read_inputs()
    if value in inputs[key]:
        return False
    inputs[key].append(value)
    write_inputs(inputs)
    return True


def remove_input(key: str, value: str) -> bool:
    _validate_input_key(key)
    inputs = read_inputs()
    if value not in inputs[key]:
        return False
    inputs[key].remove(value)
    write_inputs(inputs)
    return True


def ensure_config() -> None:
    """Create config/data/state directories and the unified input file."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    for directory in (
        DOWNLOADED_DIR, REVIEW_DIR, SELECTED_DIR,
        ARCHIVE_DIR,
    ):
        directory.mkdir(parents=True, exist_ok=True)

    if not inputs_path().exists():
        write_inputs(_empty_inputs())


def load_env_file() -> None:
    """Load $CONFIG_DIR/.env into the process environment (KEY=VALUE per
    line, '#' comments and blank lines ignored, optional matching quotes
    around the value stripped). Never overrides a variable already set in
    the environment -- an explicit shell `export` always wins over this
    file.
    """
    if not ENV_FILE.exists():
        return
    for raw_line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            os.environ.setdefault(key, value)
