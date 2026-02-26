import os, json
import itertools
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import HumanMessage, SystemMessage

def get_decision(symbol, price_data, news):
    
    # Rotate through multiple Gemini API keys to avoid rate limits 
    current_key = next(itertools.cycle([k.strip() for k in os.getenv("GEMINI_API_KEYS").split(",") if k.strip()]))
    
    llm = ChatGoogleGenerativeAI(model="gemini-flash-lite-latest", google_api_key=current_key)
    instructions = f"""
        You are a stock trading assistant that provides clear BUY/SELL/HOLD recommendations based on price data and news. 
        Return your response strictly in JSON format.
        Do not include markdown blocks like ```json.Do not include markdown blocks like ```json.
    """
    prompt = f"""
        Analyze {symbol} based on:
        Price Data: {price_data}
        Recent News: {news}
        
        Respond ONLY in JSON format:
        {{"action": "BUY" | "SELL" | "HOLD", "reason": "short explanation"}}
    """
    
    response = llm.invoke([
        SystemMessage(content=instructions),
        HumanMessage(content=prompt)
    ])
    # In a real app, use a JSON parser here
    #return json response.content.json()
    return json.loads(response.content) 