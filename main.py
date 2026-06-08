import os
import threading
import time
import json
import asyncio
from collections import deque
from datetime import datetime
from telegram import Bot
from playwright.sync_api import sync_playwright

# =====================
# 環境変数
# =====================
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
X_SEARCH_QUERY = os.getenv("X_SEARCH_QUERY", "python")  # X検索キーワード
AMAZON_SEARCH_QUERY = os.getenv("AMAZON_SEARCH_QUERY", "")  # Amazon検索キーワード
RAKUTEN_SEARCH_QUERY = os.getenv("RAKUTEN_SEARCH_QUERY", "")  # 楽天検索キーワード

# =====================
# ロギング
# =====================
LOG_FILE = "bot.log"

def log_print(msg, level="INFO"):
    """スレッドセーフなログ"""
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
# Telegram送信キュー制御
# =====================
telegram_queue = deque()
queue_lock = threading.Lock()


def enqueue_message(text):
    """メッセージをキューに追加"""
    with queue_lock:
        telegram_queue.append(text)
    log_print(f"📬 キュー追加: {len(telegram_queue)}件", "DEBUG")


async def _send_telegram_raw(text):
    """async版 Telegram送信"""
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
# X (Twitter) Playwright スクレイピング
# =====================
def fetch_x_tweets():
    """X (Twitter) 検索ページからツイート取得 - Playwright"""
    try:
        if not X_SEARCH_QUERY:
            log_print("⚠️  X_SEARCH_QUERY未設定", "WARN")
            return []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            # X検索ページ開く
            search_url = f"https://x.com/search?q={X_SEARCH_QUERY}&f=live"
            log_print(f"🐦 X検索ページ開く: {search_url}", "DEBUG")
            page.goto(search_url, wait_until="domcontentloaded", timeout=30000)

            # ツイート読み込み待機
            time.sleep(3)
            page.wait_for_load_state("networkidle", timeout=15000)

            # ツイート要素取得
            tweets = []
            tweet_articles = page.query_selector_all("article")

            log_print(f"🐦 ツイート要素検出: {len(tweet_articles)}件", "DEBUG")

            for article in tweet_articles:
                try:
                    # ツイートID取得
                    link_elem = article.query_selector("a[href*='/status/']")
                    if not link_elem:
                        continue
                    
                    href = link_elem.get_attribute("href")
                    tweet_id = href.split("/status/")[-1] if "/status/" in href else None
                    
                    if not tweet_id:
                        continue

                    # ツイートテキスト取得
                    text_elem = article.query_selector("[data-testid='tweet'] div:nth-child(2) div:nth-child(2)")
                    tweet_text = text_elem.inner_text() if text_elem else ""

                    # ユーザー名取得
                    user_elem = article.query_selector("div span a[href*='/']")
                    username = ""
                    if user_elem:
                        user_href = user_elem.get_attribute("href")
                        username = user_href.strip("/") if user_href else ""

                    if tweet_text:
                        tweets.append({
                            "id": tweet_id,
                            "text": tweet_text,
                            "user": username,
                            "url": f"https://x.com{href}"
                        })

                except Exception as e:
                    log_print(f"⚠️  ツイート解析エラー: {e}", "DEBUG")
                    continue

            browser.close()

            log_print(f"🐦 スクレイピング完了: {len(tweets)}件", "SUCCESS")
            return tweets

    except Exception as e:
        log_print(f"❌ X スクレイピングエラー: {e}", "ERROR")
        return []


# =====================
# Amazon Playwright スクレイピング
# =====================
def fetch_amazon_products():
    """Amazon 検索ページから商品取得 - Playwright"""
    try:
        if not AMAZON_SEARCH_QUERY:
            log_print("⚠️  AMAZON_SEARCH_QUERY未設定", "WARN")
            return []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page = context.new_page()

            # Amazon検索ページ開く
            search_url = f"https://amazon.co.jp/s?k={AMAZON_SEARCH_QUERY}"
            log_print(f"📦 Amazon検索ページ開く: {search_url}", "DEBUG")
            page.goto(search_url, wait_until="domcontentloaded", timeout=30000)

            # 商品読み込み待機
            time.sleep(3)
            page.wait_for_load_state("networkidle", timeout=15000)

            # 商品要素取得
            products = []
            product_divs = page.query_selector_all("div[data-component-type='s-search-result']")

            log_print(f"📦 商品要素検出: {len(product_divs)}件", "DEBUG")

            for product_div in product_divs:
                try:
                    # ASIN取得
                    asin = product_div.get_attribute("data-asin")
                    if not asin:
                        continue

                    # 商品名取得
                    title_elem = product_div.query_selector("h2 a span")
                    title = title_elem.inner_text() if title_elem else "不明"

                    # 価格取得
                    price_elem = product_div.query_selector("span.a-price-whole")
                    price = price_elem.inner_text() if price_elem else "価格不明"

                    # リンク取得
                    link_elem = product_div.query_selector("h2 a")
                    link = link_elem.get_attribute("href") if link_elem else ""

                    if asin and title:
                        products.append({
                            "id": asin,
                            "title": title,
                            "price": price,
                            "url": f"https://amazon.co.jp{link}" if link else ""
                        })

                except Exception as e:
                    log_print(f"⚠️  Amazon商品解析エラー: {e}", "DEBUG")
                    continue

            browser.close()

            log_print(f"📦 スクレイピング完了: {len(products)}件", "SUCCESS")
            return products

    except Exception as e:
        log_print(f"❌ Amazon スクレイピングエラー: {e}", "ERROR")
        return []


# =====================
# 楽天 Playwright スクレイピング
# =====================
def fetch_rakuten_items():
    """楽天検索ページから商品取得 - Playwright"""
    try:
        if not RAKUTEN_SEARCH_QUERY:
            log_print("⚠️  RAKUTEN_SEARCH_QUERY未設定", "WARN")
            return []

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )
            page = context.new_page()

            # 楽天検索ページ開く
            search_url = f"https://search.rakuten.co.jp/search/mall/{RAKUTEN_SEARCH_QUERY}/"
            log_print(f"🛍️  楽天検索ページ開く: {search_url}", "DEBUG")
            page.goto(search_url, wait_until="domcontentloaded", timeout=30000)

            # 商品読み込み待機
            time.sleep(3)
            page.wait_for_load_state("networkidle", timeout=15000)

            # 商品要素取得
            items = []
            product_links = page.query_selector_all("a.titleLinkUrl")

            log_print(f"🛍️  商品要素検出: {len(product_links)}件", "DEBUG")

            for link in product_links:
                try:
                    # 商品名取得
                    title = link.inner_text()

                    # リンク取得
                    href = link.get_attribute("href")

                    # 商品ID取得（URLから）
                    item_id = href.split("/")[-1] if href else None

                    if item_id and title:
                        items.append({
                            "id": item_id,
                            "title": title,
                            "url": href
                        })

                except Exception as e:
                    log_print(f"⚠️  楽天商品解析エラー: {e}", "DEBUG")
                    continue

            browser.close()

            log_print(f"🛍️  スクレイピング完了: {len(items)}件", "SUCCESS")
            return items

    except Exception as e:
        log_print(f"❌ 楽天 スクレイピングエラー: {e}", "ERROR")
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
                    msg = f"🐦 【{tweet['user']}】\n{tweet['text'][:200]}\n{tweet['url']}"
                    enqueue_message(msg)
                    log_print(f"🐦 新規ツイート: {tweet['id']}", "SUCCESS")

        except Exception as e:
            log_print(f"❌ X失敗: {e}", "ERROR")

        time.sleep(30)


def watch_amazon():
    log_print("📦 Amazon監視スレッド起動", "INFO")

    while True:
        log_print("📦 watch_amazonループ実行", "INFO")

        try:
            products = fetch_amazon_products()

            log_print(
                f"📦 products取得: {len(products)}件",
                "INFO"
            )

            for product in products:
                if add_to_seen(f"amazon_{product['id']}"):
                    msg = f"📦 {product['title']}\n💰 {product['price']}\n{product['url']}"
                    enqueue_message(msg)
                    log_print(f"📦 新規商品: {product['id']}", "SUCCESS")

        except Exception as e:
            log_print(f"❌ Amazon失敗: {e}", "ERROR")

        time.sleep(60)


def watch_rakuten():
    log_print("🛍️  楽天監視スレッド起動", "INFO")

    while True:
        log_print("🛍️  watch_rakutenループ実行", "INFO")

        try:
            items = fetch_rakuten_items()

            log_print(
                f"🛍️  items取得: {len(items)}件",
                "INFO"
            )

            for item in items:
                if add_to_seen(f"rakuten_{item['id']}"):
                    msg = f"🛍️  {item['title']}\n{item['url']}"
                    enqueue_message(msg)
                    log_print(f"🛍️  新規商品: {item['id']}", "SUCCESS")

        except Exception as e:
            log_print(f"❌ 楽天失敗: {e}", "ERROR")

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
