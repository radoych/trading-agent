import os
import sys
import json

# ensure project root is importable
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import execution


class FakeClient:
    def __init__(self, api_key, secret, paper=True):
        self.api_key = api_key
        self.secret = secret

    def submit_order(self, order_data):
        return {"submitted": True, "order": order_data}


def test_execute_order_submits(monkeypatch):
    monkeypatch.setattr(execution, "TradingClient", FakeClient)
    monkeypatch.setattr(execution, "MarketOrderRequest", lambda **kwargs: kwargs)

    class _OS:
        BUY = "BUY"
        SELL = "SELL"

    monkeypatch.setattr(execution, "OrderSide", _OS)
    monkeypatch.setattr(execution, "TimeInForce", type("T", (), {"DAY": "DAY"}))

    result = execution.execute_order("ABC", 2, "BUY")
    assert result["submitted"] is True
    assert result["order"]["symbol"] == "ABC"
    assert result["order"]["qty"] == 2