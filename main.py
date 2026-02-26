import os, asyncio, warnings
import yfinance as yf
from aiohttp import web  # Import web for the heartbeat
from dotenv import load_dotenv
from telegram_bot import TradingBot
from brain import get_decision
from telegram import Update

load_dotenv()

# --- HEARTBEAT SERVER ---
async def handle_heartbeat(request):
    return web.Response(text="ping")

async def start_web_server():
    app = web.Application()
    app.router.add_get("/", handle_heartbeat)
    runner = web.AppRunner(app)
    await runner.setup()
    # Koyeb provides the PORT environment variable automatically
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"🌐 Heartbeat server active on port {port}")

# --- TRADING LOOP ---
async def trading_loop(bot):
    symbol = "AAPL"
    while True:
        try:
            print(f"📡 Scanning {symbol}...")
            ticker = yf.Ticker(symbol)
            price = ticker.fast_info.last_price
            news = [n['content']['title'] for n in ticker.news[:2]]
            
            decision = get_decision(symbol, price, news)
            
            if decision['action'] in ["BUY", "SELL"]:
                await bot.send_approval_request(
                    symbol=symbol, 
                    action=decision['action'], 
                    price=round(price, 2), 
                    reason=decision['reason']
                )
        except Exception as e:
            print(f"⚠️ Loop Error: {e}")
            
        await asyncio.sleep(360) # 6 min sleep

# --- MAIN ENTRY ---
async def main():
    bot = TradingBot(
        token=os.getenv("TELEGRAM_BOT_TOKEN"),
        chat_id=os.getenv("MY_TELEGRAM_CHAT_ID")
    )
    
    await bot.app.initialize()
    await bot.app.start()
    await bot.app.updater.start_polling(allowed_updates=Update.ALL_TYPES)
    
    # 1. Start the Web Server to prevent Koyeb sleep
    await start_web_server()
    
    # 2. Start the trading loop in the background
    asyncio.create_task(trading_loop(bot))
    
    print("📡 Bot is live and multitasking.")
    
    try:
        # Keep the main process alive
        while True:
            await asyncio.sleep(3600)
    finally:
        await bot.app.stop()

if __name__ == "__main__":
    asyncio.run(main())