# AI Trading Agent

An autonomous stock trading agent powered by Google Gemini that scans AAPL, NVDA, and TSLA every 10 minutes, generates BUY/SELL/HOLD signals, and delivers them to you via Telegram for one-tap approval before executing on Alpaca paper trading.

## Architecture

```
yfinance (price + news)
        │
        ▼
  brain.py (Gemini LLM)  ──▶  BUY/SELL/HOLD decision
        │
        ▼
  risk.py (10% position cap)
        │
        ▼
  Telegram bot  ──▶  ✅ Approve / ❌ Reject
        │
        ▼
  execution.py (Alpaca paper trade)
        │
        ▼
  logger.py  ──▶  trade_logs.json  ──▶  dashboard.py (Streamlit)
```

## Features

- **AI-powered signals** — Gemini Flash analyses price data and recent news headlines to recommend BUY / SELL / HOLD with a short explanation.
- **Human-in-the-loop** — every signal is sent to your Telegram chat with Approve / Reject inline buttons; no trade fires without your explicit tap.
- **Paper trading** — orders execute against an Alpaca paper account so real money is never at risk while you refine the strategy.
- **Risk guard** — a single trade may not exceed 10% of your current account balance.
- **API key rotation** — rotates through multiple Gemini keys with exponential back-off when quota is exhausted.
- **Streamlit dashboard** — visualises trade history and P/L; run locally alongside the bot.
- **Koyeb-ready** — exposes a lightweight HTTP heartbeat on `$PORT` so the deployment stays alive.

## Setup

### Prerequisites

- Python 3.11+
- A [Google AI Studio](https://aistudio.google.com) API key (or multiple for key rotation)
- A [Telegram bot token](https://core.telegram.org/bots/tutorial) and your Telegram chat ID
- An [Alpaca](https://alpaca.markets) paper trading account (API key + secret)

### Install

```bash
git clone https://github.com/radoych/trading-agent.git
cd trading-agent
pip install -r requirements.txt
```

### Environment variables

Create a `.env` file in the project root:

```env
# Gemini — comma-separated list for key rotation
GEMINI_APP_KEYS=key1,key2,key3

# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token
MY_TELEGRAM_CHAT_ID=your_chat_id

# Alpaca paper trading
PAPER_ALPACA_API_KEY=your_alpaca_key
PAPER_ALPACA_SECRET_KEY=your_alpaca_secret

# Optional — defaults to 8080 (set automatically by Koyeb)
PORT=8080
```

### Run

```bash
# Start the trading agent
python main.py

# Start the dashboard (separate terminal)
streamlit run dashboard.py
```

## Telegram commands

| Command | Description |
|---|---|
| `/start` | Confirm the bot is live |
| `/portfolio` | Show current equity, buying power, and total P/L |

When a signal fires, the bot sends a message like:

```
🚨 TRADE SIGNAL: BUY
Stock: NVDA  |  Price: $135.40
Reason: strong uptrend supported by positive earnings news
  ✅ Approve     ❌ Reject
```

## Project structure

```
main.py          — entry point; trading loop + heartbeat server
brain.py         — Gemini LLM integration and key rotation
risk.py          — position sizing rules and trade logging helpers
execution.py     — Alpaca order submission
telegram_bot.py  — bot handlers and approval flow
logger.py        — trade event logging to trade_logs.json
dashboard.py     — Streamlit monitoring dashboard
tests/           — pytest test suite
.github/         — GitHub Actions CI
```

## CI

GitHub Actions runs the full test suite on every push and pull request to `main`.

```bash
pytest -q
```

## Deployment (Koyeb)

1. Push the repo to GitHub.
2. Create a new Koyeb service pointing at this repo.
3. Set all environment variables from the list above in the Koyeb dashboard.
4. Koyeb will build from `requirements.txt` and start `python main.py`.

The heartbeat endpoint (`GET /`) keeps the service from being scaled to zero.

## Disclaimer

This project is for educational and paper-trading purposes only. It does not constitute financial advice. Past signal performance does not guarantee future results.
