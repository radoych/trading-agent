"""Manual connectivity check for every external service the agent depends on.

Not a test. It talks to live APIs and is deliberately kept out of tests/ so
pytest never collects it (the previous version sent a real Telegram message on
every local test run and broke CI on missing imports).

Usage:
    python scripts/check_connections.py           # validate credentials only
    python scripts/check_connections.py --send    # also send a Telegram message
"""

import os
import sys

import requests
from dotenv import load_dotenv

load_dotenv()

TIMEOUT = 15


def check_alpaca():
    try:
        from alpaca.trading.client import TradingClient

        key, sec = os.getenv("PAPER_ALPACA_API_KEY"), os.getenv("PAPER_ALPACA_SECRET_KEY")
        if not key or not sec:
            return False, "PAPER_ALPACA_API_KEY / PAPER_ALPACA_SECRET_KEY not set"
        acct = TradingClient(key, sec, paper=True).get_account()
        return True, f"paper account {acct.status}, equity ${float(acct.equity):,.2f}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def check_gemini():
    keys = [k.strip() for k in os.getenv("GEMINI_APP_KEYS", "").split(",") if k.strip()]
    if not keys:
        return False, "GEMINI_APP_KEYS not set (agent would silently HOLD forever)"
    try:
        from brain import get_decision

        d = get_decision("AAPL", 100.0, ["connectivity check"])
        if d.get("reason") == "All API keys exhausted for today.":
            return False, f"{len(keys)} key(s) configured but none answered"
        return True, f"{len(keys)} key(s) configured, responded {d['action']}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def check_telegram(send=False):
    token, chat_id = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("MY_TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        return False, "TELEGRAM_BOT_TOKEN / MY_TELEGRAM_CHAT_ID not set"
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=TIMEOUT)
        if r.status_code != 200:
            return False, f"getMe returned {r.status_code}: {r.text[:120]}"
        name = r.json().get("result", {}).get("username", "?")
        if not send:
            return True, f"token valid for @{name} (use --send to post a message)"
        r = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", timeout=TIMEOUT,
                          json={"chat_id": chat_id, "text": "AI Trader: connectivity check OK"})
        if r.status_code != 200:
            return False, f"sendMessage returned {r.status_code}: {r.text[:120]}"
        return True, f"message delivered to @{name}"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def check_lse():
    if not os.getenv("LSE_API_KEY"):
        return None, "LSE_API_KEY not set (optional)"
    try:
        from lse import LSE

        n = len(LSE(api_key=os.getenv("LSE_API_KEY")).candles("AAPL", "1d", start="2026-01-02"))
        return True, f"reachable, {n} AAPL daily candles"
    except ImportError:
        return None, "lse-data not installed (optional: pip install lse-data)"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def main():
    send = "--send" in sys.argv
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

    results = [("Alpaca", *check_alpaca()),
               ("Gemini", *check_gemini()),
               ("Telegram", *check_telegram(send)),
               ("LSE", *check_lse())]

    print("\nConnectivity check\n" + "-" * 60)
    failed = 0
    for name, ok, detail in results:
        mark = "SKIP" if ok is None else ("OK  " if ok else "FAIL")
        failed += ok is False
        print(f"  [{mark}] {name:9} {detail}")
    print("-" * 60)
    print(f"{failed} failure(s)\n")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
