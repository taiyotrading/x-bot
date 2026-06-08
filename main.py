import asyncio
import os
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")


# /start コマンド
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Bot起動しました")


async def main():
    if not TOKEN:
        print("TOKENが設定されていません")
        return

    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))

    print("bot started")

    # ← これが常駐処理（重要）
    await app.run_polling()


if __name__ == "__main__":
    asyncio.run(main())
