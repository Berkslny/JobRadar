from __future__ import annotations

from pathlib import Path

import pytest
import yaml

import jobradar.http as jr_http
from jobradar.config import load_config
from jobradar.demo import DEMO_PROFILE
from jobradar.profile import Profile

TEMPLATES = Path(__file__).resolve().parents[1] / "src" / "jobradar" / "templates"
FIXTURES = Path(__file__).resolve().parent / "fixtures"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(jr_http, "sleep", lambda s: None)
    import time

    monkeypatch.setattr(time, "sleep", lambda s: None)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Secrets read from a test's .env land in os.environ; start every test without them."""
    for key in ("SMTP_USER", "SMTP_PASSWORD", "MAIL_TO", "JOBRADAR_API_TOKEN", "JOBRADAR_PUBLIC_URL",
                "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
        monkeypatch.delenv(key, raising=False)


@pytest.fixture
def workspace(tmp_path: Path):
    cfg_data = yaml.safe_load((FIXTURES / "jobradar.yaml").read_text(encoding="utf-8"))
    cfg_data["sources"]["companies"] = []
    cfg_data["llm"]["provider"] = "none"
    cfg_data["tailor"]["pdf_engine"] = "none"
    (tmp_path / "data").mkdir()
    (tmp_path / "jobradar.yaml").write_text(yaml.safe_dump(cfg_data, allow_unicode=True), encoding="utf-8")
    (tmp_path / "data" / "profile.yaml").write_text(yaml.safe_dump(DEMO_PROFILE, allow_unicode=True), encoding="utf-8")
    return tmp_path


@pytest.fixture
def cfg(workspace):
    return load_config(workspace / "jobradar.yaml")


@pytest.fixture
def profile() -> Profile:
    return Profile.model_validate(DEMO_PROFILE)
