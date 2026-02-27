import os
import sys
import json
import types
import pytest

# ensure the trading-agent directory is on sys.path so `import brain` works
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import brain


class FakeResponse:
    def __init__(self, content):
        self.content = content


class FakeLLM:
    def __init__(self, model, google_api_key, temperature):
        self.key = google_api_key

    def invoke(self, messages):
        # Behavior controlled by key string for tests
        if self.key == "raise_quota":
            from google.api_core.exceptions import ResourceExhausted

            raise ResourceExhausted("quota exhausted")

        if self.key == "bad_json":
            return FakeResponse("not-a-json")

        if self.key == "invalid_action":
            return FakeResponse(json.dumps({"action": "FOO", "reason": "bad"}))

        # default: return a valid SELL response
        return FakeResponse(json.dumps({"action": "SELL", "reason": "ok"}))


def test_get_decision_success(monkeypatch):
    monkeypatch.setattr(brain, "ChatGoogleGenerativeAI", FakeLLM)
    monkeypatch.setattr(brain, "api_keys", ["good_key"])

    result = brain.get_decision("SYM", "100", "none")
    assert isinstance(result, dict)
    assert result["action"] == "SELL"


def test_get_decision_invalid_json(monkeypatch):
    monkeypatch.setattr(brain, "ChatGoogleGenerativeAI", FakeLLM)
    monkeypatch.setattr(brain, "api_keys", ["bad_json"])

    result = brain.get_decision("SYM", "100", "none")
    assert result == {"action": "HOLD", "reason": "Invalid API response"}


def test_get_decision_invalid_action(monkeypatch):
    monkeypatch.setattr(brain, "ChatGoogleGenerativeAI", FakeLLM)
    monkeypatch.setattr(brain, "api_keys", ["invalid_action"])

    result = brain.get_decision("SYM", "100", "none")
    assert result == {"action": "HOLD", "reason": "Invalid API response"}


def test_get_decision_quota_rotation(monkeypatch):
    # First key will raise quota error, second will succeed
    monkeypatch.setattr(brain, "ChatGoogleGenerativeAI", FakeLLM)
    monkeypatch.setattr(brain, "api_keys", ["raise_quota", "good_key"])

    result = brain.get_decision("SYM", "100", "none")
    assert isinstance(result, dict)
    assert result["action"] == "SELL"
