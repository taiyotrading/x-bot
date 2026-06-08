import os
import threading
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


# =========================
# Telegramコマンド
# =========================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot起動しました")


# =========================
# X監視（仮）
# =========================
def run_x_bot():
    while True:
        # ここにX監視ロジック
        print("X監視中...")
        # sleep必須
        import time
        time.sleep(30)


# =========================
# 価格監視（仮）
# =========================
def run_price_bot():
    while True:
        # ここにAmazon/楽天ロジック
        print("価格監視中...")
        import time
        time.sleep(60)


# =========================
# Telegram起動
# =========================
def main():
    if not TOKEN:
        print("TOKENがありません")
        return

    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))

    print("bot started")

    # ===== ここが重要 =====
    threading.Thread(target=run_x_bot, daemon=True).start()
    threading.Thread(target=run_price_bot, daemon=True).start()

    app.run_polling()


if __name__ == "__main__":
    main()
