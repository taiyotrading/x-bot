import os
import time
import threading
import traceback
from datetime import datetime
from collections import deque
from telegram import Bot
from telegram.error import TelegramError, RetryAfter

# 環境変数から取得
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

# ボット初期化
bot = Bot(token=TOKEN)

# ===========================
# スレッド安全な重複防止
# ===========================
seen = set()
seen_lock = threading.Lock()
MAX_SEEN_SIZE = 10000

# ===========================
# ロギング
# ===========================
LOG_FILE = "bot.log"


def log_print(msg, level="INFO"):
    """スレッドセーフなログ出力"""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log_msg = f"[{timestamp}] [{level}] {msg}"
    print(log_msg)
    
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(log_msg + "\n")
    except Exception as e:
        print(f"ログ書き込みエラー: {e}")


def add_to_seen(key):
    """スレッド安全な重複チェック追加"""
    global seen
    
    with seen_lock:
        if len(seen) > MAX_SEEN_SIZE:
            log_print(f"⚠️  seen リセット (サイズ: {len(seen)})", "WARN")
            seen.clear()
        
        if key not in seen:
            seen.add(key)
            return True  # 新規
        return False  # 既出


# ===========================
# Telegram送信（リトライ付き）
# ===========================
def send_telegram(text, retry=3):
    """
    リトライロジック付きTelegram送信
    - retry: リトライ回数（デフォルト3回）
    - RetryAfter対応
    """
    if not text:
        return False
    
    for attempt in range(1, retry + 1):
        try:
            bot.send_message(chat_id=CHAT_ID, text=text)
            log_print(f"✅ Telegram送信成功: {text[:40]}...", "SUCCESS")
            return True
        
        except RetryAfter as e:
            # APIレート制限エラー（公式エラー）
            wait_time = e.retry_after
            log_print(
                f"⏱️  Telegramレート制限: {wait_time}秒待機（試行 {attempt}/{retry}）",
                "WARN"
            )
            time.sleep(min(wait_time + 1, 30))  # 最大30秒待機
        
        except TelegramError as e:
            # その他のTelegramエラー
            log_print(
                f"❌ Telegramエラー (試行 {attempt}/{retry}): {e}",
                "ERROR"
            )
            if attempt < retry:
                time.sleep(2 ** attempt)  # 指数バックオフ: 2s, 4s, 8s
        
        except Exception as e:
            # 予期しないエラー
            log_print(
                f"❌ 予期しないエラー (試行 {attempt}/{retry}): {e}",
                "ERROR"
            )
            if attempt < retry:
                time.sleep(2 ** attempt)
    
    log_print(f"❌ Telegram送信完全失敗 ({retry}回リトライ後)", "CRITICAL")
    return False


# ===========================
# X（Twitter）監視
# ===========================
def fetch_x_tweets():
    """
    X APIからツイートを取得
    
    返り値:
        list: [{'id': str, 'text': str, 'url': str}, ...]
    
    例外:
        API接続エラー
        認証エラー
        レート制限
    """
    # ⚠️ TODO: あなたの実装に置き換え
    # 例:
    # try:
    #     response = requests.get(...)
    #     return parse_response(response)
    # except requests.RequestException as e:
    #     log_print(f"X API接続エラー: {e}", "ERROR")
    #     raise
    
    log_print("⚠️  fetch_x_tweets() は未実装です", "WARN")
    return []


def watch_x():
    """X監視スレッド（障害耐性付き）"""
    log_print("🐦 X監視スレッド起動", "INFO")
    failure_count = 0
    
    while True:
        try:
            tweets = fetch_x_tweets()
            failure_count = 0  # 成功でリセット
            
            if not tweets:
                log_print("X: ツイート0件", "DEBUG")
                time.sleep(30)
                continue
            
            log_print(f"X: {len(tweets)}件取得", "INFO")
            
            for t in tweets:
                try:
                    # キー生成
                    tweet_key = f"x_{t.get('id', '')}"
                    
                    # スレッド安全なチェック
                    if not add_to_seen(tweet_key):
                        continue  # 既出
                    
                    # メッセージ作成
                    message = f"🐦 【X】\n{t.get('text', 'N/A')[:200]}"
                    if 'url' in t and t['url']:
                        message += f"\n🔗 {t['url']}"
                    
                    # 送信
                    send_telegram(message, retry=3)
                
                except Exception as e:
                    log_print(f"X個別処理エラー: {e}", "ERROR")
                    traceback.print_exc()
                    continue
        
        except Exception as e:
            failure_count += 1
            log_print(
                f"❌ X監視エラー (失敗 {failure_count}回): {e}",
                "ERROR"
            )
            traceback.print_exc()
            
            # 5回連続失敗でアラート
            if failure_count == 5:
                send_telegram(
                    f"🚨 X監視が5回連続失敗\nエラー: {str(e)[:100]}",
                    retry=2
                )
        
        time.sleep(30)


# ===========================
# Amazon監視
# ===========================
def fetch_amazon():
    """
    Amazon APIから商品情報を取得
    
    返り値:
        list: [{'asin': str, 'title': str, 'price': str, 'url': str}, ...]
    
    例外:
        スクレイピング失敗
        HTML構造変更
        ネットワークエラー
    """
    # ⚠️ TODO: あなたの実装に置き換え
    log_print("⚠️  fetch_amazon() は未実装です", "WARN")
    return []


def watch_amazon():
    """Amazon監視スレッド（障害耐性付き）"""
    log_print("📦 Amazon監視スレッド起動", "INFO")
    failure_count = 0
    
    while True:
        try:
            items = fetch_amazon()
            failure_count = 0
            
            if not items:
                log_print("Amazon: 商品0件", "DEBUG")
                time.sleep(60)
                continue
            
            log_print(f"Amazon: {len(items)}件取得", "INFO")
            
            for p in items:
                try:
                    amazon_key = f"amazon_{p.get('asin', '')}"
                    
                    if not add_to_seen(amazon_key):
                        continue
                    
                    price = f"¥{p.get('price', 'N/A')}" if 'price' in p else "価格不明"
                    message = f"📦 【Amazon】\n{p.get('title', 'N/A')[:150]}\n💰 {price}"
                    
                    if 'url' in p and p['url']:
                        message += f"\n🔗 {p['url']}"
                    
                    send_telegram(message, retry=3)
                
                except Exception as e:
                    log_print(f"Amazon個別処理エラー: {e}", "ERROR")
                    continue
        
        except Exception as e:
            failure_count += 1
            log_print(
                f"❌ Amazon監視エラー (失敗 {failure_count}回): {e}",
                "ERROR"
            )
            traceback.print_exc()
            
            if failure_count == 5:
                send_telegram(
                    f"🚨 Amazon監視が5回連続失敗\nエラー: {str(e)[:100]}",
                    retry=2
                )
        
        time.sleep(60)


# ===========================
# 楽天監視
# ===========================
def fetch_rakuten():
    """
    楽天APIから商品情報を取得
    
    返り値:
        list: [{'id': str, 'name': str, 'price': str, 'url': str}, ...]
    
    例外:
        API接続エラー
        レート制限
        データ不足
    """
    # ⚠️ TODO: あなたの実装に置き換え
    log_print("⚠️  fetch_rakuten() は未実装です", "WARN")
    return []


def watch_rakuten():
    """楽天監視スレッド（障害耐性付き）"""
    log_print("🛍️  楽天監視スレッド起動", "INFO")
    failure_count = 0
    
    while True:
        try:
            items = fetch_rakuten()
            failure_count = 0
            
            if not items:
                log_print("楽天: 商品0件", "DEBUG")
                time.sleep(45)
                continue
            
            log_print(f"楽天: {len(items)}件取得", "INFO")
            
            for p in items:
                try:
                    rakuten_key = f"rakuten_{p.get('id', '')}"
                    
                    if not add_to_seen(rakuten_key):
                        continue
                    
                    price = f"¥{p.get('price', 'N/A')}" if 'price' in p else "価格不明"
                    message = f"🛍️  【楽天】\n{p.get('name', 'N/A')[:150]}\n💰 {price}"
                    
                    if 'url' in p and p['url']:
                        message += f"\n🔗 {p['url']}"
                    
                    send_telegram(message, retry=3)
                
                except Exception as e:
                    log_print(f"楽天個別処理エラー: {e}", "ERROR")
                    continue
        
        except Exception as e:
            failure_count += 1
            log_print(
                f"❌ 楽天監視エラー (失敗 {failure_count}回): {e}",
                "ERROR"
            )
            traceback.print_exc()
            
            if failure_count == 5:
                send_telegram(
                    f"🚨 楽天監視が5回連続失敗\nエラー: {str(e)[:100]}",
                    retry=2
                )
        
        time.sleep(45)


# ===========================
# ハートビート（生存確認）
# ===========================
def heartbeat():
    """10分ごとにBOT生存確認"""
    log_print("💚 ハートビートスレッド起動", "INFO")
    
    while True:
        try:
            with seen_lock:
                seen_count = len(seen)
            
            status_msg = (
                f"💚 BOT生存確認\n"
                f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"📊 追跡中: {seen_count}件"
            )
            log_print(status_msg, "HEARTBEAT")
            
            # 1時間ごとにハートビート送信（スパム防止）
            time.sleep(3600)
            send_telegram("💚 BOT稼働中...", retry=1)
        
        except Exception as e:
            log_print(f"❌ ハートビートエラー: {e}", "ERROR")
            time.sleep(600)


# ===========================
# 定期リセット（メモリ最適化）
# ===========================
def periodic_reset():
    """48時間ごとにメモリをリセット"""
    log_print("🔄 定期リセットスレッド起動", "INFO")
    
    while True:
        try:
            # 48時間ごと
            time.sleep(48 * 3600)
            
            with seen_lock:
                old_size = len(seen)
                seen.clear()
            
            reset_msg = f"🔄 定期メモリリセット実行\n削除: {old_size}件"
            log_print(reset_msg, "INFO")
            send_telegram(reset_msg, retry=2)
        
        except Exception as e:
            log_print(f"❌ リセット処理エラー: {e}", "ERROR")
            time.sleep(3600)


# ===========================
# メイン起動
# ===========================
if __name__ == "__main__":
    log_print("=" * 60, "INFO")
    log_print("🚀 BOT起動開始", "INFO")
    log_print("=" * 60, "INFO")
    
    # TOKEN確認
    if not TOKEN or not CHAT_ID:
        error_msg = "❌ TELEGRAM_BOT_TOKEN または TELEGRAM_CHAT_ID が未設定"
        log_print(error_msg, "CRITICAL")
        exit(1)
    
    log_print(f"✅ TOKEN設定確認: {TOKEN[:20]}...", "INFO")
    log_print(f"✅ CHAT_ID: {CHAT_ID}", "INFO")
    
    try:
        # スレッド起動
        threads = [
            ("X監視", watch_x),
            ("Amazon監視", watch_amazon),
            ("楽天監視", watch_rakuten),
            ("ハートビート", heartbeat),
            ("定期リセット", periodic_reset),
        ]
        
        for name, func in threads:
            t = threading.Thread(target=func, daemon=True, name=name)
            t.start()
            log_print(f"✅ {name}スレッド起動", "INFO")
            time.sleep(1)  # スレッド起動の間隔
        
        send_telegram("✅ BOT起動完了！監視を開始します", retry=3)
        log_print("✅ すべてのスレッド起動完了", "SUCCESS")
        
        # メインスレッドを生存させる
        while True:
            time.sleep(3600)
    
    except Exception as e:
        error_msg = f"❌ 起動エラー: {e}"
        log_print(error_msg, "CRITICAL")
        traceback.print_exc()
        try:
            send_telegram(f"❌ BOT起動失敗: {str(e)[:100]}", retry=2)
        except:
            pass
        exit(1)
