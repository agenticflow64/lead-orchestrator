"""Shared fixtures: isolated storage, rules-only classifier (no network), dataset from docs."""

import re
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def load_dataset() -> list[tuple[int, str, str, str]]:
    """Parse docs/test-leads.md: [(num, text, expected_type, expected_urgency), ...]."""
    rows = []
    for line in (ROOT / "docs" / "test-leads.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"\|\s*(\d+)\s*\|(.*?)\|\s*(\w+)\s*\|\s*(\w+)\s*\|", line)
        if m:
            rows.append((int(m.group(1)), m.group(2).strip(), m.group(3), m.group(4)))
    assert rows, "test dataset not parsed"
    return rows


DATASET = load_dataset()


@pytest.fixture
def dataset() -> list[tuple[int, str, str, str]]:
    return DATASET


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient with temp SQLite/log and the regex fallback as the only 'provider'."""
    from app import config

    monkeypatch.setattr(config.settings, "db_path", str(tmp_path / "test.db"))
    monkeypatch.setattr(config.settings, "notifications_log", str(tmp_path / "notifications.log"))
    monkeypatch.setattr(config.settings, "telegram_bot_token", "")
    monkeypatch.setattr(config.settings, "telegram_chat_id", "")
    monkeypatch.setattr("app.classifier._providers", lambda: [])

    from app.main import app

    with TestClient(app) as c:
        yield c
