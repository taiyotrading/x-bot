import os
import threading
import time
import json
import asyncio
from collections import deque
from datetime import datetime
from telegram import Bot

# =====================
# 環境変数
# =====================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# =====================
# ロギング
# =====================
LOG_FILE = "bot.log"

def log_print(msg, level="INFO"):
    """スレッドセーフなログ（レベル統一）"""
    level = level.upper()
    if level not in ["DEBUG", "INFO", "SUCCESS", "WARN", "ERROR", "CRITICAL", "HEARTBEAT"]:
        level = "INFO"
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_msg = f"[{timestamp}] [{level:8}] {msg}"
    print(log_msg)
    
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_msg + "\n")
    except:
        pass

# =====================
# seen管理（永続化）
# =====================
seen = set()
seen_lock = threading.Lock()
MAX_SEEN_SIZE = 10000
SEEN_FILE = "seen.json"


def load_seen():
    global seen
    try:
        if os.path.exists(SEEN_FILE):
            with open(SEEN_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                seen = set(data)
            log_print(f"✅ seen復帰: {len(seen)}件", "INFO")
    except Exception as e:
        log_print(f"⚠️  seen復帰失敗: {e}", "WARN")
        seen = set()


def save_seen_loop():
    log_print("💾 seen保存スレッド起動", "INFO")
    while True:
        try:
            time.sleep(600)

            with seen_lock:
                data = list(seen)

            tmp_file = SEEN_FILE + ".tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f)
            
            if os.path.exists(SEEN_FILE):
                os.remove(SEEN_FILE)
            os.rename(tmp_file, SEEN_FILE)

            log_print(f"💾 seen保存: {len(data)}件", "DEBUG")

        except Exception as e:
            log_print(f"❌ seen保存失敗: {e}", "ERROR")


def add_to_seen(key):
    with seen_lock:
        if len(seen) > MAX_SEEN_SIZE:
            log_print(f"⚠️  seen リセット ({len(seen)}→0)", "WARN")
            seen.clear()

        if key in seen:
            return False

        seen.add(key)
        return True


# =====================
# Telegram送信キュー制御（deque版 + async）
# =====================
telegram_queue = deque()
queue_lock = threading.Lock()


def enqueue_message(text):
    """メッセージをキューに追加"""
    with queue_lock:
        telegram_queue.append(text)
    log_print(f"📬 キュー追加: {len(telegram_queue)}件", "DEBUG")


async def _send_telegram_raw(text):
    """async版 Telegram送信（python-telegram-bot 22.2用）"""
    try:
        bot = Bot(token=TOKEN)

        await bot.send_message(
            chat_id=CHAT_ID,
            text=text
        )

        log_print(f"✅ 送信: {text[:40]}", "SUCCESS")
        return True

    except Exception as e:
        log_print(f"❌ Telegram送信失敗: {e}", "ERROR")
        return False


def send_telegram_worker():
    """キューから順次送信（レート制限対応）"""
    log_print("📤 Telegram送信ワーカー起動", "INFO")
    
    while True:
        try:
            with queue_lock:
                if not telegram_queue:
                    time.sleep(2)
                    continue
                
                text = telegram_queue.popleft()
            
            asyncio.run(_send_telegram_raw(text))
            time.sleep(2)
        
        except Exception as e:
            log_print(f"❌ 送信ワーカーエラー: {e}", "ERROR")
            time.sleep(5)


# =====================
# サンプル取得関数（実装予定）
# =====================
def fetch_x_tweets():
    """X (Twitter) からツイート取得"""
    # TODO: 実装
    return []


def fetch_amazon_products():
    """Amazon から商品取得"""
    # TODO: 実装
    return []


def fetch_rakuten_items():
    """楽天 から商品取得"""
    # TODO: 実装
    return []


# =====================
# 監視スレッド
# =====================
def watch_x():
    log_print("🐦 X監視スレッド起動", "INFO")

    while True:
        log_print("🐦 watch_xループ実行", "INFO")

        try:
            tweets = fetch_x_tweets()

            log_print(
                f"🐦 tweets取得: {len(tweets)}件",
                "INFO"
            )

            for tweet in tweets:
                if add_to_seen(f"x_{tweet['id']}"):
                    enqueue_message(tweet["text"])

        except Exception as e:
            log_print(f"❌ X失敗: {e}", "ERROR")

        time.sleep(30)


def watch_amazon():
    log_print("📦 Amazon監視スレッド起動", "INFO")
    fail_count = 0
    
    while True:
        try:
            products = fetch_amazon_products()
            for product in products:
                if add_to_seen(f"amazon_{product['id']}"):
                    msg = f"📦 新しい商品\n{product['title']}\n🔗 {product['url']}"
                    enqueue_message(msg)
            fail_count = 0
        except Exception as e:
            fail_count += 1
            log_print(f"❌ Amazon失敗 {fail_count}: {e}", "ERROR")
            if fail_count >= 5:
                enqueue_message(f"🚨 Amazon監視エラー: {str(e)[:80]}")
                fail_count = 0
        
        time.sleep(60)


def watch_rakuten():
    log_print("🛍️  楽天監視スレッド起動", "INFO")
    fail_count = 0
    
    while True:
        try:
            items = fetch_rakuten_items()
            for item in items:
                if add_to_seen(f"rakuten_{item['id']}"):
                    msg = f"🛍️  新しい商品\n{item['title']}\n🔗 {item['url']}"
                    enqueue_message(msg)
            fail_count = 0
        except Exception as e:
            fail_count += 1
            log_print(f"❌ 楽天失敗 {fail_count}: {e}", "ERROR")
            if fail_count >= 5:
                enqueue_message(f"🚨 楽天監視エラー: {str(e)[:80]}")
                fail_count = 0
        
        time.sleep(60)


# =====================
# ハートビート＆プロセス監視
# =====================
def heartbeat():
    """1時間ごとにハートビート送信"""
    log_print("💚 ハートビート起動", "INFO")
    last_send = 0
    
    while True:
        try:
            with seen_lock:
                count = len(seen)
            
            now = time.time()
            
            if now - last_send > 3600:
                msg = f"💚 稼働中\n⏰ {datetime.now().strftime('%H:%M:%S')}\n📊 {count}件追跡"
                enqueue_message(msg)
                last_send = now
                log_print(msg, "INFO")
            
            time.sleep(300)
        
        except Exception as e:
            log_print(f"❌ ハートビートエラー: {e}", "ERROR")
            time.sleep(300)


# =====================
# 起動
# =====================
if __name__ == "__main__":
    log_print("=" * 60, "INFO")
    log_print("🚀 BOT起動", "INFO")

    if not TOKEN or not CHAT_ID:
        log_print("❌ 環境変数が未設定", "CRITICAL")
        exit(1)

    load_seen()

    threads = [
        ("seen保存", save_seen_loop),
        ("送信ワーカー", send_telegram_worker),
        ("X監視", watch_x),
        ("Amazon監視", watch_amazon),
        ("楽天監視", watch_rakuten),
        ("ハートビート", heartbeat),
    ]
    
    for name, func in threads:
        t = threading.Thread(target=func, daemon=True, name=name)
        t.start()
        log_print(f"✅ {name}起動", "INFO")
        time.sleep(0.5)

    log_print("✅ 全スレッド起動完了", "SUCCESS")
    enqueue_message("✅ BOT起動完了")

    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        log_print("🛑 BOT停止", "INFO")
        enqueue_message("🛑 BOT停止")
        exit(0)
