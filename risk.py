import json
import os
from datetime import datetime


def check_risk(action, price, balance):
    # Rule: Never spend more than 10% of balance on one trade
    max_position = balance * 0.10
    if action == "BUY" and price > max_position:
        return False, "Trade too large for risk rules"
    return True, "Risk Approved"


def check_current_holdings(client, ticker):
    """Return True if there is an open position for `ticker` (qty > 0)."""
    try:
        pos = client.get_open_positions(ticker)
        return bool(getattr(pos, "quantity", 0))
    except Exception:
        return False


def log_event(ticker, action, price, sentiment, news, params=None):
    """Append a JSON line with the event to a timestamped file.

    Filename format: trading_log_%Y%m%d_%H%M%S.json
    """
    if params is None:
        params = {}

    now = datetime.now()
    filename = f"trading_log_{now.strftime('%Y%m%d')}_{now.strftime('%H%M%S')}.json"

    entry = {
        "ticker": ticker,
        "action": action,
        "price": price,
        "sentiment": sentiment,
        "news": (news or "")[:200],
        "params": params,
        "timestamp": now.strftime("%Y-%m-%d %H:%M:%S")
    }

    with open(filename, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")