import os
import sys
import json
import pytest
from datetime import datetime

# ensure the trading-agent directory is on sys.path so `import risk` works
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import risk


class DummyPosition:
    def __init__(self, qty):
        self.qty = qty


class DummyClient:
    def __init__(self, positions):
        # positions is a dict ticker->qty or will raise
        self._positions = positions

    def get_open_position(self, ticker):
        if ticker not in self._positions:
            raise Exception("no position")
        return DummyPosition(self._positions[ticker])


def test_check_current_holdings_matches_real_alpaca_api():
    """Contract test against the real client, not a hand-written stub.

    The stub above used to define `get_open_positions` and `.quantity`, which
    matched risk.py but matched nothing in alpaca-py. The tests passed while the
    function returned False in production for every ticker. autospec fails on any
    call to a method the real client does not have.
    """
    from unittest.mock import create_autospec

    from alpaca.trading.client import TradingClient
    from alpaca.trading.models import Position

    assert "qty" in Position.model_fields
    assert "quantity" not in Position.model_fields

    client = create_autospec(TradingClient, instance=True)
    client.get_open_position.return_value = DummyPosition("5")
    assert risk.check_current_holdings(client, "AAPL") is True
    client.get_open_position.assert_called_once_with("AAPL")


@pytest.mark.parametrize("action,price,balance,expected", [
    ("BUY", 50.0, 10_000.0, True),     # 50 <= 10% of 10k
    ("BUY", 1_500.0, 10_000.0, False),  # 1500 > 10% of 10k
    ("BUY", 1_000.0, 10_000.0, True),   # exactly at the cap
    ("SELL", 9_999.0, 10_000.0, True),  # cap only applies to BUY
    ("HOLD", 9_999.0, 10_000.0, True),
])
def test_check_risk(action, price, balance, expected):
    ok, reason = risk.check_risk(action, price, balance)
    assert ok is expected
    assert isinstance(reason, str) and reason


@pytest.mark.parametrize("qty,expected", [(0, False), (1, True), (100, True)])
def test_check_current_holdings_true_and_false(tmp_path, qty, expected):
    client = DummyClient({"ABC": qty})
    result = risk.check_current_holdings(client, "ABC")
    assert result is expected


def test_check_current_holdings_handles_exception():
    client = DummyClient({})
    # ticker not present should cause get_open_positions to raise
    assert not risk.check_current_holdings(client, "MISSING")


def test_log_event_writes_file(tmp_path, monkeypatch):
    # monkeypatch datetime to a fixed value for deterministic filename
    fixed = datetime(2023, 1, 1, 12, 34, 56)
    class FakeDatetime(datetime):
        @classmethod
        def now(cls):
            return fixed

    monkeypatch.setattr(risk, "datetime", FakeDatetime)

    # ensure working directory is tmp_path
    monkeypatch.chdir(tmp_path)

    ticker = "XYZ"
    action = "BUY"
    price = 123.45
    sentiment = 0.7
    news = "some news about XYZ stock" * 20  # long string
    params = {"strategy": "test"}

    risk.log_event(ticker, action, price, sentiment, news, params)

    # check that file exists with expected name
    expected_name = f"trading_log_{fixed.strftime('%Y%m%d')}_{fixed.strftime('%H%M%S')}.json"
    file_path = tmp_path / expected_name
    assert file_path.exists(), "log file was not created"

    # read the content
    lines = file_path.read_text().strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])

    assert entry["ticker"] == ticker
    assert entry["action"] == action
    assert entry["price"] == price
    assert entry["sentiment"] == sentiment
    assert entry["params"] == params
    assert entry["news"] == news[:200]


if __name__ == "__main__":
    pytest.main()