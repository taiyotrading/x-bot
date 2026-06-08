import os
import threading
import time
from telegram import Bot

TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

bot = Bot(token=TOKEN)

def send_telegram(text):
    try:
        bot.send_message(chat_id=CHAT_ID, text=text)
    except Exception as e:
        print("Telegram error:", e)
        
# ===========================
# ① スレッド安全な重複防止
# ===========================
seen = set()
seen_lock = threading.Lock()
MAX_SEEN_SIZE = 10000
SEEN_FILE = "seen.json"

def load_seen():
    """seen.jsonから復帰"""
    global seen
    try:
        if os.path.exists(SEEN_FILE):
            with open(SEEN_FILE, "r") as f:
                seen = set(json.load(f))
            log_print(f"✅ seen復帰: {len(seen)}件", "INFO")
    except Exception as e:
        log_print(f"⚠️  seen復帰失敗: {e}", "WARN")
        seen = set()

def save_seen():
    """定期的にseenを保存"""
    global seen
    while True:
        try:
            time.sleep(600)  # 10分ごと
            with seen_lock:
                if len(seen) > 0:
                    with open(SEEN_FILE, "w") as f:
                        json.dump(list(seen), f)
                    log_print(f"💾 seen保存: {len(seen)}件", "DEBUG")
        except Exception as e:
            log_print(f"❌ seen保存失敗: {e}", "ERROR")

def add_to_seen(key):
    """スレッド安全な重複チェック"""
    with seen_lock:
        if len(seen) > MAX_SEEN_SIZE:
            log_print(f"⚠️  seen リセット ({len(seen)}→0)", "WARN")
            seen.clear()
        
        if key not in seen:
            seen.add(key)
            return True
        return False

# ===========================
# ② Telegram送信キュー制御
# ===========================
telegram_queue = []
queue_lock = threading.Lock()

def enqueue_message(text):
    """メッセージをキューに追加"""
    with queue_lock:
        telegram_queue.append(text)

def send_telegram_worker():
    """キューから順次送信（レート制限対応）"""
    log_print("📤 Telegram送信ワーカー起動", "INFO")
    
    while True:
        try:
            with queue_lock:
                if not telegram_queue:
                    time.sleep(1)
                    continue
                text = telegram_queue.pop(0)
            
            _send_telegram_raw(text, retry=3)
            time.sleep(1.5)  # レート制限対応（1.5秒間隔）
        
        except Exception as e:
            log_print(f"❌ 送信ワーカーエラー: {e}", "ERROR")
            time.sleep(5)

def _send_telegram_raw(text, retry=3):
    """実際の送信処理"""
    for attempt in range(1, retry + 1):
        try:
            bot.send_message(chat_id=CHAT_ID, text=text)
            log_print(f"✅ 送信: {text[:40]}...", "SUCCESS")
            return True
        
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

# ===========================
# ロギング
# ===========================
LOG_FILE = "bot.log"

def log_print(msg, level="INFO"):
    """スレッドセーフなログ"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_msg = f"[{timestamp}] [{level}] {msg}"
    print(log_msg)
    
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_msg + "\n")
    except:
        pass

# ===========================
# テスト用スクレイピング関数
# ===========================
def fetch_x_tweets():
    """🐦 Xテスト"""
    return [{
        "id": "test1",
        "text": "Xテスト投稿",
        "url": "https://example.com"
    }]

def fetch_amazon():
    """📦 Amazonテスト"""
    return [{
        "asin": "B000TEST",
        "title": "Amazonテスト商品",
        "price": "1980",
        "url": "https://example.com"
    }]

def fetch_rakuten():
    """🛍️  楽天テスト"""
    return [{
        "id": "r1",
        "name": "楽天テスト商品",
        "price": "2500",
        "url": "https://example.com"
    }]

# ===========================
# ③ 監視スレッド
# ===========================
def watch_x():
    """X監視"""
    log_print("🐦 X監視スレッド起動", "INFO")
    fail_count = 0
    
    while True:
        try:
            tweets = fetch_x_tweets()
            fail_count = 0
            
            for t in tweets:
                try:
                    key = f"x_{t.get('id', '')}"
                    if not add_to_seen(key):
                        log_print(f"⏭️  重複: {key}", "DEBUG")
                        continue
                    
                    msg = f"🐦 【X】\n{t.get('text', '')[:200]}"
                    if t.get('url'):
                        msg += f"\n🔗 {t['url']}"
                    
                    enqueue_message(msg)
                except Exception as e:
                    log_print(f"X処理エラー: {e}", "ERROR")
        
        except Exception as e:
            fail_count += 1
            log_print(f"❌ X失敗 {fail_count}: {e}", "ERROR")
            if fail_count >= 5:
                enqueue_message(f"🚨 X監視エラー: {str(e)[:80]}")
                fail_count = 0
        
        time.sleep(30)

def watch_amazon():
    """Amazon監視"""
    log_print("📦 Amazon監視スレッド起動", "INFO")
    fail_count = 0
    
    while True:
        try:
            items = fetch_amazon()
            fail_count = 0
            
            for p in items:
                try:
                    key = f"amazon_{p.get('asin', '')}"
                    if not add_to_seen(key):
                        log_print(f"⏭️  重複: {key}", "DEBUG")
                        continue
                    
                    msg = f"📦 【Amazon】\n{p.get('title', '')[:150]}\n💰 ¥{p.get('price', '')}"
                    if p.get('url'):
                        msg += f"\n🔗 {p['url']}"
                    
                    enqueue_message(msg)
                except Exception as e:
                    log_print(f"Amazon処理エラー: {e}", "ERROR")
        
        except Exception as e:
            fail_count += 1
            log_print(f"❌ Amazon失敗 {fail_count}: {e}", "ERROR")
            if fail_count >= 5:
                enqueue_message(f"🚨 Amazon監視エラー: {str(e)[:80]}")
                fail_count = 0
        
        time.sleep(60)

def watch_rakuten():
    """楽天監視"""
    log_print("🛍️  楽天監視スレッド起動", "INFO")
    fail_count = 0
    
    while True:
        try:
            items = fetch_rakuten()
            fail_count = 0
            
            for p in items:
                try:
                    key = f"rakuten_{p.get('id', '')}"
                    if not add_to_seen(key):
                        log_print(f"⏭️  重複: {key}", "DEBUG")
                        continue
                    
                    msg = f"🛍️  【楽天】\n{p.get('name', '')[:150]}\n💰 ¥{p.get('price', '')}"
                    if p.get('url'):
                        msg += f"\n🔗 {p['url']}"
                    
                    enqueue_message(msg)
                except Exception as e:
                    log_print(f"楽天処理エラー: {e}", "ERROR")
        
        except Exception as e:
            fail_count += 1
            log_print(f"❌ 楽天失敗 {fail_count}: {e}", "ERROR")
            if fail_count >= 5:
                enqueue_message(f"🚨 楽天監視エラー: {str(e)[:80]}")
                fail_count = 0
        
        time.sleep(45)

# ===========================
# ④ ハートビート＋プロセス監視
# ===========================
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
                log_print(msg, "HEARTBEAT")
            
            time.sleep(300)  # 5分ごとチェック
        
        except Exception as e:
            log_print(f"❌ ハートビートエラー: {e}", "ERROR")
            time.sleep(300)

# ===========================
# メイン
# ===========================
if __name__ == "__main__":
    log_print("=" * 60, "INFO")
    log_print("🚀 BOT起動", "INFO")
    
    if not TOKEN or not CHAT_ID:
        log_print("❌ 環境変数未設定", "CRITICAL")
        exit(1)
    
    # seen復帰
    load_seen()
    
    # スレッド起動
    threads = [
        ("seen保存", save_seen),
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
    
    enqueue_message("✅ BOT起動完了")
    log_print("✅ すべてのスレッド起動完了", "SUCCESS")
    
    # プロセス生存
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        log_print("🛑 BOT停止", "INFO")
        enqueue_message("🛑 BOT停止")
        exit(0)
