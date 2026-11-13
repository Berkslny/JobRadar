"""Settings the app manages: ``data/settings.json`` overrides ``jobradar.yaml``.

The YAML file stays the hand-written base (comments and all) and is never rewritten. Whatever a client
changes through the API is stored in the overlay, merged on top at load time and applied to the running
configuration in place, so no restart is needed.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

from jobradar.config import AppConfig

OVERLAY_NAME = "settings.json"
# top-level keys a client may change; paths, ports and the server section stay in jobradar.yaml
EDITABLE = ("language", "follow_up_days", "tracks", "search", "sources", "filters", "scoring", "matching", "llm",
            "notify", "mail_sync", "tailor", "quick")
_lock = threading.Lock()


def deep_merge(base: dict[str, Any], patch: dict[str, Any]) -> dict[str, Any]:
    """Dicts merge key by key; lists and scalars in ``patch`` replace the base value."""
    out = dict(base)
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def overlay_path(cfg: AppConfig) -> Path:
    return cfg.data_path / OVERLAY_NAME


def read_overlay(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def merged_data(yaml_data: dict[str, Any], base_dir: Path) -> dict[str, Any]:
    """YAML content with the overlay on top (used by load_config)."""
    data_dir = Path(str(yaml_data.get("data_dir") or "data")).expanduser()
    if not data_dir.is_absolute():
        data_dir = base_dir / data_dir
    overlay = {k: v for k, v in read_overlay(data_dir / OVERLAY_NAME).items() if k in EDITABLE}
    return deep_merge(yaml_data, overlay) if overlay else yaml_data


def apply(cfg: AppConfig, patch: dict[str, Any]) -> None:
    """Validate ``patch`` against the whole configuration and apply it to ``cfg`` in place."""
    new = AppConfig.model_validate(deep_merge(cfg.model_dump(), patch))
    for name in AppConfig.model_fields:
        setattr(cfg, name, getattr(new, name))


def update(cfg: AppConfig, patch: dict[str, Any]) -> None:
    """Apply a change and remember it. Raises pydantic.ValidationError (nothing is written) when invalid."""
    unknown = [k for k in patch if k not in EDITABLE]
    if unknown:
        raise ValueError(f"not editable: {', '.join(unknown)}")
    with _lock:
        apply(cfg, patch)
        path = overlay_path(cfg)
        merged = deep_merge(read_overlay(path), patch)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp, path)


WORKSPACE_YAML = """\
# JobRadar workspace. The JobRadar app manages its settings in data/settings.json, which overrides this file.
# You can still edit this file by hand; see the project README for every option.
data_dir: data
profile: data/profile.yaml
tracks: []
search:
  country: ""
  locations: []
  preferred_cities: []
  employment_types: [fulltime]
sources:
  arbeitsagentur: {enabled: false}
  freehire: {enabled: false, countries: []}
  companies: []
filters:
  title_exclude: []
llm:
  provider: none
  output_language: auto
  claude_cli: {subscription_only: false}
tailor:
  sender_city: ""
"""


def ensure_workspace(folder: Path) -> Path:
    """Create an empty workspace (config and data folders) when ``folder`` has none; returns the config path."""
    folder = folder.expanduser()
    (folder / "data" / "inbox").mkdir(parents=True, exist_ok=True)
    cfg_path = folder / "jobradar.yaml"
    if not cfg_path.exists():
        cfg_path.write_text(WORKSPACE_YAML, encoding="utf-8")
    return cfg_path
