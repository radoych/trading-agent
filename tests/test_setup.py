import os
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from langchain_anthropic import ChatAnthropic
import google.genai as genai
import requests

# Load credentials
load_dotenv()

def test_connections():
    print("🚀 Starting AI Trader Connection Test...\n")

    # 1. Test Alpaca (Broker)
    # try:
    #     alpaca_key = os.getenv("PAPER_ALPACA_API_KEY")
    #     alpaca_secret = os.getenv("PAPER_ALPACA_SECRET_KEY")
    #     client = TradingClient(alpaca_key, alpaca_secret, paper=True)
    #     account = client.get_account()
    #     print(f"✅ ALPACA: Connected! Paper Balance: ${account.cash}")
    # except Exception as e:
    #     print(f"❌ ALPACA: Connection Failed. Check your keys. Error: {e}")

    # # 2. Test OpenAI/LLM (The Brain)
    # try:
    #     genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))
    #     model = genai.GenerativeModel("gemini-2.5-flash")
    #     response = model.generate_content("Are you online?")
    #     print(f"✅ GEMINI: {response.text}")
    # except Exception as e:
    #     print(f"❌ GEMINI: Connection Failed. Error: {e}")
    
    # 3. Test Telegram (The Voice)
    try:
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        my_chat_id = os.getenv("MY_TELEGRAM_CHAT_ID")
        url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
        res = requests.post(url, json={"chat_id": my_chat_id, "text": "🤖 AI Trader: Connection Test Successful!"})
        if res.status_code == 200:
            print("✅ TELEGRAM: Message sent successfully!")
        else:
            print(f"❌ TELEGRAM: Failed with status {res.status_code}: {res.json()}")
    except Exception as e:
        print(f"❌ TELEGRAM: Error: {e}")

if __name__ == "__main__":
    test_connections()