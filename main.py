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
    symbols = ["AAPL", "NVDA", "TSLA"] 
    
    while True:
        for symbol in symbols:
            try:
                print(f"📡 Scanning {symbol}...")
                ticker = yf.Ticker(symbol)
                
                # 1. Safety check for price
                fast_info = ticker.fast_info
                if fast_info is None or not hasattr(fast_info, 'last_price'):
                    print(f"⚠️ Price data missing for {symbol}. Skipping...")
                    continue
                price = fast_info.last_price

                # 2. Safety check for news (This fixes the 'NoneType' error)
                raw_news = ticker.news
                news = []
                
                if raw_news: # Check if raw_news is not None and not empty
                    for n in raw_news[:3]:
                        # Use .get() to avoid errors if 'content' or 'title' is missing
                        content = n.get('content', {})
                        if content:
                            title = content.get('title')
                            if title:
                                news.append(title)
                
                if not news:
                    print(f"ℹ️ No news found for {symbol}, proceeding with price only.")

                # 3. Ask Gemini
                decision = get_decision(symbol, price, news)
                print(f"🤖 Gemini {symbol} Decision: {decision['action']}")
                
                if decision['action'] in ["BUY", "SELL"]:
                    await bot.send_approval_request(
                        symbol=symbol, 
                        action=decision['action'], 
                        price=round(price, 2), 
                        reason=decision['reason']
                    )
                
                await asyncio.sleep(10) # Gap between symbols

            except Exception as e:
                print(f"⚠️ Error scanning {symbol}: {e}")
                await asyncio.sleep(10)
        
        print("😴 Round finished. Sleeping for 10 minutes...")
        await asyncio.sleep(600)

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