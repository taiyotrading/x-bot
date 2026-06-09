# =========================================================
# IMPORT
# =========================================================
import asyncio
import json
import re
import logging
from pathlib import Path
from typing import List, Dict, Tuple
from urllib.parse import quote

import requests
from playwright.async_api import async_playwright


# =========================================================
# LOG
# =========================================================
logger = logging.getLogger("XBot")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s"
)


# =========================================================
# CONFIG
# =========================================================
SEEN_TWEETS_FILE = "seen_tweets.json"

CYCLE_INTERVAL = 600

EARLY_SIGNAL_THRESHOLD = 40

TOTAL_SCORE_HIGH = 110
TOTAL_SCORE_MID = 80

PRESSURE_TRIGGER_THRESHOLD = 15
HYPE_TRIGGER_THRESHOLD = 15


QUERIES = [
    "Nike Jordan drop",
    "Supreme drop",
    "予約開始",
    "抽選受付",
    "限定リリース",
    "売切れ",
    "完売",
    "争奪戦",
    "激戦",
    "プレ値",
    "転売",
    "入手困難",
]


# =========================================================
# 🇯🇵 LANGUAGE FILTER
# =========================================================
class LanguageFilter:

    @classmethod
    def is_japanese(cls, text: str) -> bool:

        jp_count = len(
            re.findall(r"[ぁ-んァ-ン一-龥]", text)
        )

        return jp_count >= 5


# =========================================================
# 🔗 URL FILTER
# =========================================================
class URLFilter:

    @classmethod
    def has_url(cls, text: str) -> bool:

        return (
            "http://" in text
            or "https://" in text
            or "x.com/" in text
        )


# =========================================================
# 🧠 INFO TYPE
# =========================================================
class InfoType:

    ANNOUNCEMENT = {
        "予約",
        "抽選",
        "発売",
        "販売開始",
        "drop",
        "release",
    }

    AVAILABILITY = {
        "販売中",
        "購入可能",
        "在庫",
        "available",
    }

    HYPE = {
        "話題",
        "転売",
        "プレ値",
        "hype",
        "resale",
    }

    @classmethod
    def classify(cls, text: str) -> Dict[str, bool]:

        t = text.lower()

        return {
            "announcement": any(k.lower() in t for k in cls.ANNOUNCEMENT),
            "availability": any(k.lower() in t for k in cls.AVAILABILITY),
            "hype": any(k.lower() in t for k in cls.HYPE),
        }


# =========================================================
# ⚖️ WEIGHT ENGINE
# =========================================================
class WeightEngine:

    @staticmethod
    def get_weights(flags: Dict[str, bool]):

        w = {
            "early": 1.2,
            "market": 1.1,
            "signal": 1.0,
            "sale": 1.2,
            "like": 0.5,
        }

        if flags["announcement"]:
            w["early"] += 0.2
            w["sale"] += 0.2

        if flags["availability"]:
            w["market"] += 0.2

        if flags["hype"]:
            w["signal"] += 0.2
            w["like"] += 0.1

        return w


# =========================================================
# 🚨 EARLY SIGNAL
# =========================================================
class EarlySignal:

    KEYWORDS = {
        "予約": 45,
        "予約開始": 45,
        "予約受付": 40,
        "抽選": 45,
        "抽選受付": 45,
        "限定リリース": 40,
        "限定": 35,
        "drop": 40,
        "release": 40,
        "新作": 35,
        "新商品": 35,
    }

    @classmethod
    def calculate(cls, text: str) -> int:

        t = text.lower()

        score = 0

        for k, v in cls.KEYWORDS.items():
            if k.lower() in t:
                score = max(score, v)

        return min(score, 50)


# =========================================================
# 📉 MARKET PRESSURE
# =========================================================
class MarketPressure:

    STRONG = {
        "完売",
        "売切れ",
        "売り切れ",
        "sold out",
        "out of stock",
    }

    MEDIUM = {
        "争奪戦",
        "激戦",
        "入手困難",
    }

    @classmethod
    def calculate(cls, text: str) -> int:

        t = text.lower()

        if any(k.lower() in t for k in cls.STRONG):
            return 30

        if any(k.lower() in t for k in cls.MEDIUM):
            return 15

        return 0


# =========================================================
# 🔥 MARKET SIGNAL
# =========================================================
class MarketSignal:

    KEYWORDS = {
        "話題": 15,
        "trending": 15,
        "hype": 15,
        "転売": 12,
        "リセール": 10,
        "resale": 10,
        "プレ値": 10,
    }

    @classmethod
    def calculate(cls, text: str) -> int:

        t = text.lower()

        score = 0

        for k, v in cls.KEYWORDS.items():
            if k.lower() in t:
                score += v

        return min(score, 40)


# =========================================================
# 🛒 SALE SCORE
# =========================================================
class SaleScore:

    PATTERNS = [
        r"販売開始",
        r"販売中",
        r"購入可能",
        r"available",
        r"buy now",
        r"order",
    ]

    @classmethod
    def calculate(cls, text: str) -> int:

        matches = sum(
            len(re.findall(p, text, re.IGNORECASE))
            for p in cls.PATTERNS
        )

        return min(matches * 7, 25)


# =========================================================
# 👍 LIKE BONUS
# =========================================================
class LikeBonus:

    TIERS = [
        (5000, 45),
        (2000, 35),
        (1000, 25),
        (500, 15),
        (100, 8),
        (30, 5),
    ]

    @classmethod
    def calculate(cls, like_count: int) -> int:

        for threshold, bonus in cls.TIERS:
            if like_count >= threshold:
                return bonus

        return 0


# =========================================================
# 🚫 HARD BLOCK
# =========================================================
class HardBlockFilter:

    BLOCK_WORDS = {
        "出会い系",
        "詐欺",
        "スパム",
        "マルチ商法",
    }

    @classmethod
    def is_blocked(cls, text: str) -> bool:

        t = text.lower()

        return any(w.lower() in t for w in cls.BLOCK_WORDS)


# =========================================================
# 📉 NOISE ENGINE
# =========================================================
class NoiseEngine:

    # density専用
    NOISE_KEYWORDS = {
        "フォロー",
        "いいね",
    }

    # intent専用
    INTENT_KEYWORDS = {
        "rt",
        "リツイート",
        "拡散",
    }

    MODIFIERS = {
        "お願い",
        "希望",
        "ください",
    }

    CAMPAIGN_MARKERS = {
        "抽選",
        "予約",
        "発売",
    }

    @classmethod
    def calculate(cls, text: str):

        t = text.lower()

        # =========================
        # density
        # =========================
        density = sum(
            len(re.findall(re.escape(k.lower()), t))
            for k in cls.NOISE_KEYWORDS
        )

        # =========================
        # intent
        # =========================
        intent_k = sum(
            1 for k in cls.INTENT_KEYWORDS
            if k.lower() in t
        )

        intent_m = sum(
            1 for m in cls.MODIFIERS
            if m.lower() in t
        )

        intent_bonus = (
            (intent_k * 5)
            + (intent_m * 2)
        )

        # =========================
        # campaign context
        # =========================
        campaign_hits = sum(
            1 for k in cls.CAMPAIGN_MARKERS
            if k.lower() in t
        )

        is_campaign_context = (
            campaign_hits >= 1
            and density >= 2
        )

        # =========================
        # strong noise
        # =========================
        strong_noise = (
            intent_k >= 1
            and (
                intent_m >= 1
                or density >= 4
            )
            and not is_campaign_context
        )

        # =========================
        # noise score
        # =========================
        base = density * 0.9

        interaction = min(density, 5) * 0.1

        noise_score = min(
            base
            + intent_bonus
            + interaction,
            40
        )

        # =========================
        # factor
        # =========================
        noise_factor = 1 / (1 + noise_score / 60)

        noise_factor = max(0.50, noise_factor)

        if strong_noise:
            noise_factor *= 0.75

        return {
            "density": density,
            "intent_k": intent_k,
            "intent_m": intent_m,
            "intent_bonus": intent_bonus,
            "strong_noise": strong_noise,
            "noise_score": round(noise_score, 2),
            "noise_factor": round(noise_factor, 2),
        }


# =========================================================
# 📊 SCORE ENGINE
# =========================================================
def calc_total_score(
    early,
    market,
    signal,
    sale,
    like,
    weights,
    noise_factor,
):

    signal_score = (
        (early * weights["early"])
        + (market * weights["market"])
        + (signal * weights["signal"])
        + (sale * weights["sale"])
        + (like * weights["like"])
    )

    final_score = signal_score * noise_factor

    return min(max(0, final_score), 150)


# =========================================================
# 🧠 DECISION ENGINE
# =========================================================
class DecisionEngine:

    @classmethod
    def decide(
        cls,
        early,
        pressure,
        market,
        like,
        total,
        noise_factor,
    ) -> Tuple[bool, str]:

        # =========================
        # HIGH
        # =========================
        if total >= TOTAL_SCORE_HIGH:
            return True, f"HIGH_CONFIDENCE({round(total, 1)})"

        # =========================
        # EARLY
        # =========================
        if (
            early >= EARLY_SIGNAL_THRESHOLD
            and noise_factor >= 0.55
            and total >= TOTAL_SCORE_MID
        ):
            return True, f"EARLY_CONFIRMED({round(total, 1)})"

        # =========================
        # PRESSURE
        # =========================
        if (
            pressure >= PRESSURE_TRIGGER_THRESHOLD
            and total >= TOTAL_SCORE_MID
        ):
            return True, f"PRESSURE_TRIGGER({round(total, 1)})"

        # =========================
        # HYPE
        # =========================
        if (
            market >= HYPE_TRIGGER_THRESHOLD
            and like >= 20
            and total >= 90
        ):
            return True, f"HYPE_TRIGGER({round(total, 1)})"

        return False, "NO_TRIGGER"


# =========================================================
# 🧮 TWEET SCORER
# =========================================================
class TweetScorer:

    def score(
        self,
        text: str,
        like_count: int = 0,
    ):

        # =========================
        # LANGUAGE
        # =========================
        if not LanguageFilter.is_japanese(text):
            return {
                "should": False,
                "reason": "NON_JAPANESE",
                "total": 0,
            }

        # =========================
        # URL
        # =========================
        if not URLFilter.has_url(text):
            return {
                "should": False,
                "reason": "NO_URL",
                "total": 0,
            }

        # =========================
        # HARD BLOCK
        # =========================
        if HardBlockFilter.is_blocked(text):
            return {
                "should": False,
                "reason": "HARD_BLOCK",
                "total": 0,
            }

        # =========================
        # FLAGS
        # =========================
        flags = InfoType.classify(text)

        weights = WeightEngine.get_weights(flags)

        # =========================
        # SCORES
        # =========================
        early = EarlySignal.calculate(text)

        pressure = MarketPressure.calculate(text)

        signal = MarketSignal.calculate(text)

        sale = SaleScore.calculate(text)

        like = LikeBonus.calculate(like_count)

        # =========================
        # NOISE
        # =========================
        noise = NoiseEngine.calculate(text)

        # =========================
        # TOTAL
        # =========================
        total = calc_total_score(
            early=early,
            market=pressure,
            signal=signal,
            sale=sale,
            like=like,
            weights=weights,
            noise_factor=noise["noise_factor"],
        )

        # =========================
        # DECISION
        # =========================
        should, reason = DecisionEngine.decide(
            early=early,
            pressure=pressure,
            market=signal,
            like=like,
            total=total,
            noise_factor=noise["noise_factor"],
        )

        return {
            "early": early,
            "market_pressure": pressure,
            "market_signal": signal,
            "sale_score": sale,
            "like_bonus": like,

            "noise_score": noise["noise_score"],
            "noise_factor": noise["noise_factor"],
            "strong_noise": noise["strong_noise"],

            "weights": weights,

            "total": round(total, 2),

            "should": should,
            "reason": reason,
        }


# =========================================================
# TELEGRAM
# =========================================================
class TelegramNotifier:

    def __init__(self):

        self.token = "YOUR_TOKEN"
        self.chat_id = "YOUR_CHAT_ID"

        self.url = (
            f"https://api.telegram.org/bot{self.token}/sendMessage"
        )

    def send(
        self,
        text: str,
        tweet_id: str,
        score: Dict,
    ):

        msg = f"""🚨 {score['reason']}

📝 {text[:120]}

⚙️ SCORE: {score['total']}

🔗 https://x.com/i/web/status/{tweet_id}
"""

        try:

            r = requests.post(
                self.url,
                json={
                    "chat_id": self.chat_id,
                    "text": msg,
                    "disable_web_page_preview": True,
                },
                timeout=10
            )

            return r.status_code == 200

        except Exception as e:

            logger.error(f"telegram error: {e}")

            return False


# =========================================================
# SCRAPER
# =========================================================
class XScraper:

    def __init__(self):

        self.seen = self._load()

    def _load(self):

        if Path(SEEN_TWEETS_FILE).exists():

            return set(
                json.loads(
                    Path(SEEN_TWEETS_FILE).read_text(
                        encoding="utf-8"
                    )
                )
            )

        return set()

    def _save(self):

        Path(SEEN_TWEETS_FILE).write_text(
            json.dumps(list(self.seen), indent=2),
            encoding="utf-8
