import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from alpaca.trading.client import TradingClient
from execution import execute_order
from logger import log_trade

class TradingBot:
    def __init__(self, token, chat_id):
        
        self.alpaca = TradingClient(
            os.getenv("PAPER_ALPACA_API_KEY"), 
            os.getenv("PAPER_ALPACA_SECRET_KEY"), 
            paper=True
        )
        
        self.app = Application.builder().token(token).build()
        self.chat_id = chat_id
        self.app.add_handler(CommandHandler("start", self.start_command))
        self.app.add_handler(CommandHandler("portfolio", self.portfolio_command))
        self.app.add_handler(CallbackQueryHandler(self.handle_button))

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        await update.message.reply_text("🤖 AI Trader Interface Active. Waiting for signals...")
        
    async def portfolio_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Fetches and sends the current Alpaca account status."""
        try:
            account = self.alpaca.get_account()
            
            # Format the data for a clean look
            equity = float(account.equity)
            buying_power = float(account.buying_power)
            total_pl = equity - 100000.00  # Assuming 100k starting paper balance
            
            message = (
                "💰 **Current Portfolio Status**\n"
                "--- \n"
                f"🏦 **Equity:** ${equity:,.2f}\n"
                f"💸 **Buying Power:** ${buying_power:,.2f}\n"
                f"📊 **Total P/L:** ${total_pl:,.2f}\n"
                "--- \n"
                "✅ Bot is connected and scanning."
            )
            await update.message.reply_text(message, parse_mode="Markdown")
            
        except Exception as e:
            await update.message.reply_text(f"❌ Error fetching portfolio: {e}")

    async def send_approval_request(self, symbol, action, price, reason):
        """Sends a trade proposal with Approve/Reject buttons."""
        keyboard = [[
            InlineKeyboardButton("✅ Approve", callback_data=f"exec_{action}_{symbol}_{price}"),
            InlineKeyboardButton("❌ Reject", callback_data="cancel")
        ]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        message = (f"🚨 *TRADE SIGNAL: {action}*\n"
                   f"Stock: {symbol}\nPrice: ${price}\n"
                   f"Reason: {reason}")
        
        await self.app.bot.send_message(
            chat_id=self.chat_id, 
            text=message, 
            reply_markup=reply_markup, 
            parse_mode="Markdown"
        )

    async def handle_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()

        if query.data.startswith("exec_"):
            _, action, symbol, price = query.data.split("_")
            # Trigger Execution
            execute_order(symbol, 1, action)
            log_trade({"symbol": symbol, "action": action, "price": float(price), "status": "Manually Approved"})
            await query.edit_message_text(text=f"🚀 *EXECUTED*: {action} {symbol} at ${price}", parse_mode="Markdown")
        else:
            await query.edit_message_text(text="🗑 Trade Cancelled.")

    def run(self):
        """Starts the polling loop."""
        self.app.run_polling()