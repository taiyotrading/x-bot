import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot起動しました")


def main():
    if not TOKEN:
        print("TOKENがありません")
        return

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    print("bot started")

    # ここが重要（async/await禁止）
    app.run_polling()


if __name__ == "__main__":
    main()
