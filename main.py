print("★★★★ TEST DEPLOY 2026-06-09 ★★★★")

import os
import threading
import time
import json
import asyncio
from collections import deque
from datetime import datetime
from telegram import Bot
from telegram.error import TelegramError, RetryAfter

# =====================
# 環境変数
# =====================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

bot = Bot(token=TOKEN)

# =====================
# ロギング
# =====================
LOG_FILE = "bot.log"

def log_print(msg, level="INFO"):
    """スレッドセーフなログ（レベル統一）"""
    # レベル値の標準化
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


# ---------------------
# load
# ---------------------
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


# ---------------------
# save（別スレッド）with atomic write
# ---------------------
def save_seen_loop():
    log_print("💾 seen保存スレッド起動", "INFO")
    while True:
        try:
            time.sleep(600)

            with seen_lock:
                data = list(seen)

            # 原子的に書き込む（.tmp → 本体）
            tmp_file = SEEN_FILE + ".tmp"
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f)
            
            # rename で原子的に交換
            if os.path.exists(SEEN_FILE):
                os.remove(SEEN_FILE)
            os.rename(tmp_file, SEEN_FILE)

            log_print(f"💾 seen保存: {len(data)}件", "DEBUG")

        except Exception as e:
            log_print(f"❌ seen保存失敗: {e}", "ERROR")


# ---------------------
# add seen
# ---------------------
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
# Telegram送信キュー制御（deque版）
# =====================
telegram_queue = deque()  # ✅ list → deque に変更（O(n) → O(1)）
queue_lock = threading.Lock()


def enqueue_message(text):
    """メッセージをキューに追加"""
    with queue_lock:
        telegram_queue.append(text)
    log_print(f"📬 キュー追加: {len(telegram_queue)}件", "DEBUG")


def send_telegram_worker():
    """キューから順次送信（レート制限対応）"""
    log_print("📤 Telegram送信ワーカー起動", "INFO")
    
    while True:
        try:
            with queue_lock:
                if not telegram_queue:
                    # ✅ sleep を 2秒 に延長（CPU無駄使い防止）
                    time.sleep(2)
                    continue
                text = telegram_queue.popleft()  # ✅ pop(0) → popleft()
            
            _send_telegram_raw(text, retry=3)
            time.sleep(1.5)  # レート制限対応（1.5秒間隔）
        
        except Exception as e:
            log_print(f"❌ 送信ワーカーエラー: {e}", "ERROR")
            time.sleep(5)


def _send_telegram_raw(text, retry=3):
    """実際の送信処理"""
    for attempt in range(1, retry + 1):
        try:
            asyncio.run(
                bot.send_message(
                    chat_id=CHAT_ID,
                    text=text
                )
            )
        
        except RetryAfter as e:
            wait = min(e.retry_after + 1, 30)
            log_print(f"⏱️  待機 {wait}秒 (試行 {attempt}/{retry})", "WARN")
            time.sleep(wait)
        
        except TelegramError as e:
            log_print(f"❌ Telegram失敗 {attempt}/{retry}: {e}", "ERROR")
            if attempt < retry:
                time.sleep(2 ** attempt)
        
        except Exception as e:
            log_print(f"❌ エラー {attempt}/{retry}: {e}", "ERROR")
            if attempt < retry:
                time.sleep(2 ** attempt)
    
    log_print(f"❌ 完全失敗: {text[:40]}...", "CRITICAL")
    return False
def fetch_x_tweets():
    log_print("fetch_x_tweets実行", "INFO")

    return [
        {
            "id": str(int(time.time())),
            "text": "X取得テスト",
            "url": "https://example.com"
        }
    ]
    
def watch_x():
    log_print("🐦 X監視スレッド起動", "INFO")

    while True:
        try:
            tweets = fetch_x_tweets()

            log_print(f"🐦 {len(tweets)}件取得", "INFO")

            for t in tweets:
                key = f"x_{t['id']}"

                if not add_to_seen(key):
                    continue

                msg = (
                    f"🐦 {t['text'][:200]}\n"
                    f"🔗 {t['url']}"
                )

                enqueue_message(msg)

        except Exception as e:
            log_print(f"❌ X監視エラー: {e}", "ERROR")

        time.sleep(30)

def watch_amazon():
    log_print("📦 Amazon監視スレッド起動", "INFO")
    fail_count = 0
    
    while True:
        try:
            if add_to_seen("amazon_test"):
                enqueue_message("📦 Amazonテスト")
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
            if add_to_seen("rakuten_test"):
                enqueue_message("🛍️ 楽天テスト")
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
    """10分ごとに生存確認"""
    log_print("💚 ハートビート起動", "INFO")
    last_send = 0
    
    while True:
        try:
            with seen_lock:
                count = len(seen)
            
            now = time.time()
            
            # 1時間ごとにハートビート送信
            if now - last_send > 3600:
                msg = f"💚 稼働中\n⏰ {datetime.now().strftime('%H:%M:%S')}\n📊 {count}件追跡"
                enqueue_message(msg)
                last_send = now
                log_print(msg, "INFO")
            
            time.sleep(300)  # 5分ごとチェック
        
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

    # seen復帰
    load_seen()

    # スレッド起動
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

    # メイン維持
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        log_print("🛑 BOT停止", "INFO")
        enqueue_message("🛑 BOT停止")
        exit(0)
