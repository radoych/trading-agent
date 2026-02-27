import os, json, time
import itertools
from google.api_core.exceptions import ResourceExhausted, TooManyRequests
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage

api_keys = [key.strip() for key in os.getenv("GEMINI_APP_KEYS", "").split(",") if key.strip()]

def get_decision(symbol, price, news):
    """Get trading decision with automatic API key rotation on quota exhaustion."""
    key_cycle = itertools.cycle(api_keys)
    max_retries = len(api_keys)
    
    for attempt in range(max_retries):
        current_key = next(key_cycle)
        backoff_time = 2 ** attempt  # Exponential backoff: 1, 2, 4, 8...
        
        try:
            llm = ChatGoogleGenerativeAI(
                model="gemini-flash-lite-latest",
                google_api_key=current_key,
                temperature=0.7
            )
            
            system_prompt = """You are a stock trading assistant that provides clear BUY/SELL/HOLD recommendations based on price data and news.
Return your response strictly in JSON format with no markdown blocks.
Example: {"action": "BUY", "reason": "strong uptrend"}"""

            user_prompt = f"""Analyze {symbol} based on:
Price Data: {price}
Recent News: {news}

Respond ONLY in JSON format:
{{"action": "BUY" | "SELL" | "HOLD", "reason": "short explanation"}}"""
            
            response = llm.invoke([
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt)
            ])
            
            # Parse and validate JSON response
            decision = json.loads(response.content)
            if decision.get("action") not in ["BUY", "SELL", "HOLD"]:
                raise ValueError(f"Invalid action: {decision.get('action')}")
            return decision

        except (ResourceExhausted, TooManyRequests) as e:
            # Quota/rate limit errors
            print(f"⚠️ Key quota exhausted (attempt {attempt + 1}/{max_retries}). Retrying with backoff...")
            if attempt < max_retries - 1:
                time.sleep(backoff_time)
            continue
            
        except (json.JSONDecodeError, ValueError) as e:
            # JSON parsing or validation errors - likely bad response, don't retry
            print(f"❌ Invalid response format: {e}")
            return {"action": "HOLD", "reason": "Invalid API response"}
            
        except Exception as e:
            # Other errors
            print(f"❌ Unexpected error: {e}")
            if attempt < max_retries - 1:
                time.sleep(backoff_time)
            continue

    return {"action": "HOLD", "reason": "All API keys exhausted for today."}