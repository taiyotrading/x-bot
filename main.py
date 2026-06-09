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
X_SEARCH_QUERY = os.getenv("X_SEARCH_QUERY", "python")
AMAZON_SEARCH_QUERY = os.getenv("AMAZON_SEARCH_QUERY", "")
RAKUTEN_SEARCH_QUERY = os.getenv("RAKUTEN_SEARCH_QUERY", "")

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
# スレッドローカルなPlaywright状態管理
# =====================
class ThreadLocalPlaywright:
    """各スレッドが独立したPlaywrightインスタンスを持つ"""
    
    def __init__(self):
        self._thread_local = threading.local()
        self.error_count_lock = threading.Lock()
        self.x_error_count = 0
        self.amazon_error_count = 0
        self.rakuten_error_count = 0
        self.x_last_success = None
        self.amazon_last_success = None
        self.rakuten_last_success = None
    
    def get_playwright(self):
        """スレッド内でPlaywrightインスタンスを取得"""
        if not hasattr(self._thread_local, 'playwright') or self._thread_local.playwright is None:
            self._thread_local.playwright = sync_playwright().start()
            log_print(f"✅ {threading.current_thread().name}: Playwright初期化", "DEBUG")
        return self._thread_local.playwright
    
    def get_browser(self, platform):
        """スレッド内でブラウザを取得（再利用 or 新規）"""
        playwright = self.get_playwright()
        
        attr_name = f'{platform}_browser'
        
        if not hasattr(self._thread_local, attr_name) or getattr(self._thread_local, attr_name) is None:
            try:
                log_print(f"{platform} 新規ブラウザ起動", "INFO")
                
                # ✅ サーバー環境対応（Render環境での安定性向上）
                browser = playwright.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-gpu",
                        "--single-process",
                    ]
                )
                
                setattr(self._thread_local, attr_name, browser)
                log_print(f"{platform} ブラウザ起動完了", "SUCCESS")
                
            except Exception as e:
                log_print(f"❌ {platform} ブラウザ起動失敗: {e}", "CRITICAL")
                raise
        
        return getattr(self._thread_local, attr_name)
    
    def get_page(self, platform):
        """スレッド内でページを取得（再利用 or 新規）"""
        browser = self.get_browser(platform)
        
        attr_name = f'{platform}_page'
        
        # ページが存在して生きているか確認
        if hasattr(self._thread_local, attr_name) and getattr(self._thread_local, attr_name) is not None:
            try:
                page = getattr(self._thread_local, attr_name)
                page.evaluate("1 + 1")  # ヘルスチェック
                return page
            except:
                pass
        
        # ページを新規作成
        try:
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            )
            page = context.new_page()
            page.set_default_timeout(30000)
            setattr(self._thread_local, attr_name, page)
            log_print(f"{platform} ページ作成完了", "DEBUG")
            return page
        except Exception as e:
            log_print(f"❌ {platform} ページ作成失敗: {e}", "ERROR")
            raise
    
    def close_browser(self, platform):
        """ブラウザをクローズ"""
        attr_name = f'{platform}_browser'
        if hasattr(self._thread_local, attr_name):
            try:
                browser = getattr(self._thread_local, attr_name)
                if browser:
                    browser.close()
                setattr(self._thread_local, attr_name, None)
                setattr(self._thread_local, f'{platform}_page', None)
                log_print(f"{platform} ブラウザクローズ", "DEBUG")
            except:
                pass
    
    def inc_error(self, platform):
        """エラーカウント増加"""
        with self.error_count_lock:
            if platform == "x":
                self.x_error_count += 1
                return self.x_error_count
            elif platform == "amazon":
                self.amazon_error_count += 1
                return self.amazon_error_count
            elif platform == "rakuten":
                self.rakuten_error_count += 1
                return self.rakuten_error_count
    
    def reset_error(self, platform):
        """エラーカウントリセット"""
        with self.error_count_lock:
            if platform == "x":
                self.x_error_count = 0
            elif platform == "amazon":
                self.amazon_error_count = 0
            elif platform == "rakuten":
                self.rakuten_error_count = 0

tlp = ThreadLocalPlaywright()

# =====================
# X (Twitter) スクレイピング
# =====================
def fetch_x_tweets():
    """X (Twitter) 検索ページからツイート取得 - Playwright（スレッドローカル）"""
    try:
        if not X_SEARCH_QUERY:
            log_print("⚠️  X_SEARCH_QUERY未設定", "WARN")
            return []

        page = tlp.get_page("x")

        search_url = f"https://x.com/search?q={X_SEARCH_QUERY}&f=live"
        log_print(f"🐦 X検索ページへ移動", "DEBUG")
        
        page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(2)

        # ツイート要素検出待機
        try:
            page.wait_for_selector("article", timeout=10000)
        except:
            log_print("⚠️  article要素タイムアウト（ログイン画面の可能性）", "WARN")

        tweet_articles = page.query_selector_all("article")

        log_print(f"🐦 ツイート要素検出: {len(tweet_articles)}件", "DEBUG")

        # 0件ならログイン画面やBot判定の可能性が高い
        if len(tweet_articles) == 0:
            log_print("⚠️  ツイート取得0件 → ページスクリーンショット保存", "WARN")
            try:
                page.screenshot(path="x_error.png")
                log_print("🐦 x_error.pngに保存（ログイン画面やBot判定の可能性）", "WARN")
            except:
                pass
            return []

        tweets = []

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
                text_elem = article.query_selector("div[lang]")
                tweet_text = text_elem.inner_text() if text_elem else ""

                # ユーザー名取得
                user_elem = article.query_selector("a[href*='/'] span")
                username = user_elem.inner_text() if user_elem else "Unknown"

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

        tlp.x_last_success = datetime.now()
        tlp.reset_error("x")
        log_print(f"🐦 スクレイピング完了: {len(tweets)}件 ✅", "SUCCESS")
        return tweets

    except Exception as e:
        log_print(f"❌ X スクレイピング失敗: {e}", "ERROR")
        error_count = tlp.inc_error("x")
        
        if error_count > 3:
            log_print("🐦 エラー3回以上 → ブラウザリセット", "WARN")
            tlp.close_browser("x")
        
        return []

# =====================
# Amazon スクレイピング
# =====================
def fetch_amazon_products():
    """Amazon 検索ページから商品取得 - Playwright（スレッドローカル）"""
    try:
        if not AMAZON_SEARCH_QUERY:
            log_print("⚠️  AMAZON_SEARCH_QUERY未設定", "WARN")
            return []

        page = tlp.get_page("amazon")

        search_url = f"https://amazon.co.jp/s?k={AMAZON_SEARCH_QUERY}"
        log_print(f"📦 Amazon検索ページへ移動", "DEBUG")
        
        page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(2)

        try:
            page.wait_for_selector("[data-component-type='s-search-result']", timeout=10000)
        except:
            log_print("⚠️  商品要素タイムアウト", "WARN")

        product_divs = page.query_selector_all("[data-component-type='s-search-result']")

        log_print(f"📦 商品要素検出: {len(product_divs)}件", "DEBUG")

        if len(product_divs) == 0:
            log_print("⚠️  商品取得0件 → ページスクリーンショット保存", "WARN")
            try:
                page.screenshot(path="amazon_error.png")
            except:
                pass
            return []

        products = []

        for product_div in product_divs:
            try:
                asin = product_div.get_attribute("data-asin")
                if not asin:
                    continue

                title_elem = product_div.query_selector("h2 a span")
                title = title_elem.inner_text() if title_elem else "不明"

                price_elem = product_div.query_selector("span.a-price-whole")
                price = price_elem.inner_text() if price_elem else "価格不明"

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

        tlp.amazon_last_success = datetime.now()
        tlp.reset_error("amazon")
        log_print(f"📦 スクレイピング完了: {len(products)}件 ✅", "SUCCESS")
        return products

    except Exception as e:
        log_print(f"❌ Amazon スクレイピング失敗: {e}", "ERROR")
        error_count = tlp.inc_error("amazon")
        
        if error_count > 3:
            log_print("📦 エラー3回以上 → ブラウザリセット", "WARN")
            tlp.close_browser("amazon")
        
        return []

# =====================
# 楽天 スクレイピング（セレクタ複数対応）
# =====================
def fetch_rakuten_items():
    """楽天検索ページから商品取得 - Playwright（スレッドローカル+複数セレクタ）"""
    try:
        if not RAKUTEN_SEARCH_QUERY:
            log_print("⚠️  RAKUTEN_SEARCH_QUERY未設定", "WARN")
            return []

        page = tlp.get_page("rakuten")

        search_url = f"https://search.rakuten.co.jp/search/mall/{RAKUTEN_SEARCH_QUERY}/"
        log_print(f"🛍️  楽天検索ページへ移動", "DEBUG")
        
        page.goto(search_url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(2)

        try:
            page.wait_for_selector("a", timeout=10000)
        except:
            log_print("⚠️  要素タイムアウト", "WARN")

        # 複数セレクタを試す（楽天は頻繁に変わる）
        selectors = [
            "a.titleLinkUrl",
            "a[href*='/item/']",
            "div.itemName a",
            "h2 a",
        ]

        product_links = []
        for selector in selectors:
            product_links = page.query_selector_all(selector)
            if len(product_links) > 0:
                log_print(f"🛍️  セレクタ '{selector}' で {len(product_links)}件検出", "DEBUG")
                break

        log_print(f"🛍️  商品要素検出: {len(product_links)}件", "DEBUG")

        if len(product_links) == 0:
            log_print("⚠️  商品取得0件 → ページスクリーンショット保存", "WARN")
            try:
                page.screenshot(path="rakuten_error.png")
            except:
                pass
            return []

        items = []

        for link in product_links:
            try:
                title = link.inner_text()
                href = link.get_attribute("href")

                if not href:
                    continue

                item_id = href.split("/")[-1] if "/" in href else href

                if item_id and title:
                    items.append({
                        "id": item_id,
                        "title": title,
                        "url": href
                    })

            except Exception as e:
                log_print(f"⚠️  楽天商品解析エラー: {e}", "DEBUG")
                continue

        tlp.rakuten_last_success = datetime.now()
        tlp.reset_error("rakuten")
        log_print(f"🛍️  スクレイピング完了: {len(items)}件 ✅", "SUCCESS")
        return items

    except Exception as e:
        log_print(f"❌ 楽天 スクレイピング失敗: {e}", "ERROR")
        error_count = tlp.inc_error("rakuten")
        
        if error_count > 3:
            log_print("🛍️  エラー3回以上 → ブラウザリセット", "WARN")
            tlp.close_browser("rakuten")
        
        return []

# =====================
# 監視スレッド
# =====================
def watch_x():
    """X監視スレッド（スレッドローカルPlaywright使用）"""
    log_print("🐦 X監視スレッド起動", "INFO")

    while True:
        try:
            tweets = fetch_x_tweets()

            for tweet in tweets:
                if add_to_seen(f"x_{tweet['id']}"):
                    msg = f"🐦 【{tweet['user']}】\n{tweet['text'][:200]}\n{tweet['url']}"
                    enqueue_message(msg)
                    log_print(f"🐦 新規ツイート: {tweet['id']}", "SUCCESS")

        except Exception as e:
            log_print(f"❌ watch_xエラー: {e}", "ERROR")

        time.sleep(30)


def watch_amazon():
    """Amazon監視スレッド（スレッドローカルPlaywright使用）"""
    log_print("📦 Amazon監視スレッド起動", "INFO")

    while True:
        try:
            products = fetch_amazon_products()

            for product in products:
                if add_to_seen(f"amazon_{product['id']}"):
                    msg = f"📦 {product['title']}\n💰 {product['price']}\n{product['url']}"
                    enqueue_message(msg)
                    log_print(f"📦 新規商品: {product['id']}", "SUCCESS")

        except Exception as e:
            log_print(f"❌ watch_amazonエラー: {e}", "ERROR")

        time.sleep(60)


def watch_rakuten():
    """楽天監視スレッド（スレッドローカルPlaywright使用）"""
    log_print("🛍️  楽天監視スレッド起動", "INFO")

    while True:
        try:
            items = fetch_rakuten_items()

            for item in items:
                if add_to_seen(f"rakuten_{item['id']}"):
                    msg = f"🛍️  {item['title']}\n{item['url']}"
                    enqueue_message(msg)
                    log_print(f"🛍️  新規商品: {item['id']}", "SUCCESS")

        except Exception as e:
            log_print(f"❌ watch_rakutenエラー: {e}", "ERROR")

        time.sleep(60)

# =====================
# ハートビート＆状態監視
# =====================
def heartbeat():
    """5分ごとに状態ログ + 1時間ごとにTelegram送信"""
    log_print("💚 ハートビート起動", "INFO")
    last_send = 0
    
    while True:
        try:
            with seen_lock:
                count = len(seen)
            
            now = time.time()
            
            # 5分ごとにログ出力（状態確認用）
            status = f"💚 稼働中 | X最終成功: {tlp.x_last_success.strftime('%H:%M:%S') if tlp.x_last_success else 'なし'} | Amazon最終成功: {tlp.amazon_last_success.strftime('%H:%M:%S') if tlp.amazon_last_success else 'なし'} | 楽天最終成功: {tlp.rakuten_last_success.strftime('%H:%M:%S') if tlp.rakuten_last_success else 'なし'} | 追跡: {count}件"
            log_print(status, "HEARTBEAT")
            
            # 1時間ごとにTelegram送信
            if now - last_send > 3600:
                msg = f"💚 BOT稼働中\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n📊 追跡: {count}件\n🐦 X最終: {tlp.x_last_success.strftime('%H:%M:%S') if tlp.x_last_success else '未実行'}\n📦 Amazon最終: {tlp.amazon_last_success.strftime('%H:%M:%S') if tlp.amazon_last_success else '未実行'}\n🛍️  楽天最終: {tlp.rakuten_last_success.strftime('%H:%M:%S') if tlp.rakuten_last_success else '未実行'}"
                enqueue_message(msg)
                last_send = now
            
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
        log_print("❌ TELEGRAM_BOT_TOKEN または TELEGRAM_CHAT_ID が未設定", "CRITICAL")
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
