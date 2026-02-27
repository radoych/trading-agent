import os
import sys
import asyncio

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import telegram_bot


class FakeBot:
    def __init__(self):
        self.last = None

    async def send_message(self, chat_id, text, reply_markup=None, parse_mode=None):
        self.last = {"chat_id": chat_id, "text": text, "reply_markup": reply_markup, "parse_mode": parse_mode}
        return self.last


class FakeApp:
    def __init__(self):
        self.bot = FakeBot()

    def add_handler(self, h):
        return None

    def run_polling(self):
        return None


class FakeBuilder:
    def __init__(self):
        pass

    def token(self, t):
        return self

    def build(self):
        return FakeApp()


class FakeTradingClient:
    def __init__(self, a, b, paper=True):
        pass


def test_send_approval_and_handle(monkeypatch):
    monkeypatch.setattr(telegram_bot, "TradingClient", FakeTradingClient)
    monkeypatch.setattr(telegram_bot, "Application", type("A", (), {"builder": FakeBuilder}))

    # prevent actual execution/logging side effects
    monkeypatch.setattr(telegram_bot, "execute_order", lambda *a, **k: None)
    monkeypatch.setattr(telegram_bot, "log_trade", lambda *a, **k: None)

    bot = telegram_bot.TradingBot(token="t", chat_id="chat123")

    # send approval (async)
    asyncio.run(bot.send_approval_request(symbol="ABC", action="BUY", price=12.34, reason="reason"))
    assert bot.chat_id == "chat123"
    assert bot.app.bot.last is not None
