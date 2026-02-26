import os
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce

def execute_order(symbol, qty, side):
    api_key = os.getenv("PAPER_ALPACA_API_KEY")
    secret = os.getenv("PAPER_ALPACA_SECRET_KEY")
    client = TradingClient(api_key, secret, paper=True)
    
    order_data = MarketOrderRequest(
        symbol=symbol,
        qty=qty,
        side=OrderSide.BUY if side == "BUY" else OrderSide.SELL,
        time_in_force=TimeInForce.DAY
    )
    return client.submit_order(order_data)