"""The suite can never spend: the key is removed for every test, so a missed recording fails before any request."""
import pytest


@pytest.fixture(autouse=True)
def no_key(monkeypatch):
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
