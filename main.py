import os
import threading
import time
import json
import asyncio
from collections import deque
from datetime import datetime
from telegram import Bot
from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page

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
# Playwright グローバルインスタンス
# =====================
class PlaywrightManager:
    """Playwright ブラウザ再利用マネージャー"""
    
    def __init__(self):
        self.playwright = None
        self.x_browser = None
        self.x_page = None
        self.amazon_browser = None
        self.amazon_page = None
        self.rakuten_browser = None
        self.rakuten_page = None
        self.lock = threading.Lock()
        self.x_error_count = 0
        self.amazon_error_count = 0
        self.rakuten_error_count = 0
        self.x_last_success = None
        self.amazon_last_success = None
        self.rakuten_last_success = None
    
    def init_playwright(self):
        """Playwright初期化"""
        if self.playwright:
            return
        
        try:
            self.playwright = sync_playwright().start()
            log_print("✅ Playwright初期化完了", "INFO")
        except Exception as e:
            log_print(f"❌ Playwright初期化失敗: {e}", "CRITICAL")
            raise
    
    def get_x_page(self):
        """X用ページ取得（再利用 or 新規）"""
        with self.lock:
            try:
                # ページが存在して生きているか確認
                if self.x_page and self.x_browser:
                    try:
                        self.x_page.evaluate("1 + 1")  # 簡易ヘルスチェック
                        return self.x_page
                    except:
                        pass
                
                # 既存ブラウザをクローズ
                if self.x_browser:
                    try:
                        self.x_browser.close()
                    except:
                        pass
                
                # 新規ブラウザ起動
                log_print("🐦 新規X用ブラウザ起動", "INFO")
                self.x_browser = self.playwright.chromium.launch(headless=True)
                context = self.x_browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                self.x_page = context.new_page()
                self.x_page.set_default_timeout(30000)
                self.x_error_count = 0
                
                return self.x_page
            
            except Exception as e:
                log_print(f"❌ X用ページ取得失敗: {e}", "ERROR")
                self.x_error_count += 1
                raise
    
    def get_amazon_page(self):
        """Amazon用ページ取得（再利用 or 新規）"""
        with self.lock:
            try:
                if self.amazon_page and self.amazon_browser:
                    try:
                        self.amazon_page.evaluate("1 + 1")
                        return self.amazon_page
                    except:
                        pass
                
                if self.amazon_browser:
                    try:
                        self.amazon_browser.close()
                    except:
                        pass
                
                log_print("📦 新規Amazon用ブラウザ起動", "INFO")
                self.amazon_browser = self.playwright.chromium.launch(headless=True)
                context = self.amazon_browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                self.amazon_page = context.new_page()
                self.amazon_page.set_default_timeout(30000)
                self.amazon_error_count = 0
                
                return self.amazon_page
            
            except Exception as e:
                log_print(f"❌ Amazon用ページ取得失敗: {e}", "ERROR")
                self.amazon_error_count += 1
                raise
    
    def get_rakuten_page(self):
        """楽天用ページ取得（再利用 or 新規）"""
        with self.lock:
            try:
                if self.rakuten_page and self.rakuten_browser:
                    try:
                        self.rakuten_page.evaluate("1 + 1")
                        return self.rakuten_page
                    except:
                        pass
                
                if self.rakuten_browser:
                    try:
                        self.rakuten_browser.close()
                    except:
                        pass
                
                log_print("🛍️  新規楽天用ブラウザ起動", "INFO")
                self.rakuten_browser = self.playwright.chromium.launch(headless=True)
                context = self.rakuten_browser.new_context(
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                self.rakuten_page = context.new_page()
                self.rakuten_page.set_default_timeout(30000)
                self.rakuten_error_count = 0
                
                return self.rakuten_page
            
            except Exception as e:
                log_print(f"❌ 楽天用ページ取得失敗: {e}", "ERROR")
                self.rakuten_error_count += 1
                raise

pm = PlaywrightManager()

# =====================
# X (Twitter) Playwright スクレイピング
# =====================
def fetch_x_tweets():
    """X (Twitter) 検索ページからツイート取得 - Playwright（再利用）"""
    try:
        if not X_SEARCH_QUERY:
            log_print("⚠️  X_SEARCH_QUERY未設定", "WARN")
            return []

        page = pm.get_x_page()

        search_url = f"https://x.com/search?q={X_SEARCH_QUERY}&f=live"
        log_print(f"🐦 X検索ページへ移動: {search_url}", "DEBUG")
        
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
            page.screenshot(path="x_error.png")
            log_print("🐦 x_error.pngに保存（ログイン画面やBot判定の可能性）", "WARN")
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

        pm.x_last_success = datetime.now()
        pm.x_error_count = 0
        log_print(f"🐦 スクレイピング完了: {len(tweets)}件 ✅", "SUCCESS")
        return tweets

    except Exception as e:
        log_print(f"❌ X スクレイピング失敗: {e}", "ERROR")
        pm.x_error_count += 1
        
        if pm.x_error_count > 3:
            log_print("🐦 エラー3回以上 → ブラウザリセット", "WARN")
            with pm.lock:
                if pm.x_browser:
                    try:
                        pm.x_browser.close()
                    except:
                        pass
                pm.x_browser = None
                pm.x_page = None
        
        return []

# =====================
# Amazon Playwright スクレイピング
# =====================
def fetch_amazon_products():
    """Amazon 検索ページから商品取得 - Playwright（再利用）"""
    try:
        if not AMAZON_SEARCH_QUERY:
            log_print("⚠️  AMAZON_SEARCH_QUERY未設定", "WARN")
            return []

        page = pm.get_amazon_page()

        search_url = f"https://amazon.co.jp/s?k={AMAZON_SEARCH_QUERY}"
        log_print(f"📦 Amazon検索ページへ移動: {search_url}", "DEBUG")
        
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
            page.screenshot(path="amazon_error.png")
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

        pm.amazon_last_success = datetime.now()
        pm.amazon_error_count = 0
        log_print(f"📦 スクレイピング完了: {len(products)}件 ✅", "SUCCESS")
        return products

    except Exception as e:
        log_print(f"❌ Amazon スクレイピング失敗: {e}", "ERROR")
        pm.amazon_error_count += 1
        
        if pm.amazon_error_count > 3:
            log_print("📦 エラー3回以上 → ブラウザリセット", "WARN")
            with pm.lock:
                if pm.amazon_browser:
                    try:
                        pm.amazon_browser.close()
                    except:
                        pass
                pm.amazon_browser = None
                pm.amazon_page = None
        
        return []

# =====================
# 楽天 Playwright スクレイピング（セレクタ複数対応）
# =====================
def fetch_rakuten_items():
    """楽天検索ページから商品取得 - Playwright（再利用+複数セレクタ）"""
    try:
        if not RAKUTEN_SEARCH_QUERY:
            log_print("⚠️  RAKUTEN_SEARCH_QUERY未設定", "WARN")
            return []

        page = pm.get_rakuten_page()

        search_url = f"https://search.rakuten.co.jp/search/mall/{RAKUTEN_SEARCH_QUERY}/"
        log_print(f"🛍️  楽天検索ページへ移動: {search_url}", "DEBUG")
        
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
            page.screenshot(path="rakuten_error.png")
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

        pm.rakuten_last_success = datetime.now()
        pm.rakuten_error_count = 0
        log_print(f"🛍️  スクレイピング完了: {len(items)}件 ✅", "SUCCESS")
        return items

    except Exception as e:
        log_print(f"❌ 楽天 スクレイピング失敗: {e}", "ERROR")
        pm.rakuten_error_count += 1
        
        if pm.rakuten_error_count > 3:
            log_print("🛍️  エラー3回以上 → ブラウザリセット", "WARN")
            with pm.lock:
                if pm.rakuten_browser:
                    try:
                        pm.rakuten_browser.close()
                    except:
                        pass
                pm.rakuten_browser = None
                pm.rakuten_page = None
        
        return []

# =====================
# 監視スレッド
# =====================
def watch_x():
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
    """1時間ごとにハートビート送信 + 状態通知"""
    log_print("💚 ハートビート起動", "INFO")
    last_send = 0
    
    while True:
        try:
            with seen_lock:
                count = len(seen)
            
            now = time.time()
            
            # 5分ごとにログ出力（状態確認用）
            status = f"💚 稼働中 | X最終成功: {pm.x_last_success.strftime('%H:%M:%S') if pm.x_last_success else 'なし'} | Amazon最終成功: {pm.amazon_last_success.strftime('%H:%M:%S') if pm.amazon_last_success else 'なし'} | 楽天最終成功: {pm.rakuten_last_success.strftime('%H:%M:%S') if pm.rakuten_last_success else 'なし'} | 追跡: {count}件"
            log_print(status, "HEARTBEAT")
            
            # 1時間ごとにTelegram送信
            if now - last_send > 3600:
                msg = f"💚 BOT稼働中\n⏰ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n📊 追跡: {count}件\n🐦 X最終: {pm.x_last_success.strftime('%H:%M:%S') if pm.x_last_success else '未実行'}\n📦 Amazon最終: {pm.amazon_last_success.strftime('%H:%M:%S') if pm.amazon_last_success else '未実行'}\n🛍️  楽天最終: {pm.rakuten_last_success.strftime('%H:%M:%S') if pm.rakuten_last_success else '未実行'}"
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
    
    # Playwright初期化
    try:
        pm.init_playwright()
    except Exception as e:
        log_print(f"❌ Playwright初期化失敗: {e}", "CRITICAL")
        exit(1)

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
