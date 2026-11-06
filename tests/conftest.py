import sys
from pathlib import Path

import pytest

# Allow tests to import from the project root (agent, connectors, etc.)
sys.path.insert(0, str(Path(__file__).parent.parent))

import agent
from tests.fakes import FakeApi


@pytest.fixture
def api(monkeypatch):
    """A fake Claude client installed as agent.client; set api.responses, read api.requests."""
    fake = FakeApi()
    monkeypatch.setattr(agent, "client", fake)
    return fake
