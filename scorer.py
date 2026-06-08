import logging

logger = logging.getLogger(__name__)

class TweetScorer:
    """
    スコアリング設計：
    - キーワード加点（各2点）
    - URL加点（1点）
    - いいね数加点（1-2点）
    - 時間指定（2点）
    
    通知条件：score >= 5
    """

    KEYWORDS = {
        "collaboration": [
            "コラボ", "collaboration", "collab",
            "限定コラボ"
        ],
        "presale": [
            "予約", "予約開始", "受注", "受注販売"
        ],
        "preorder": [
            "pre-order", "preorder", "presale"
        ],
        "release": [
            "発売", "販売", "開始", "発売開始", "販売開始"
        ],
        "limited": [
            "限定", "数量限定", "期間限定", "exclusive"
        ],
        "time_specific": [
            "12:00", "13:00", "18:00", "20:00",
            "午後12時", "午後1時", "午後6時", "午後8時"
        ],
        "today": [
            "本日", "今日", "本日より", "今日から"
        ]
    }

    @staticmethod
    def calculate_score(tweet):
        """
        tweet = {
            "text": str,
            "likes": int,
            "url": str (optional)
        }
        
        返値: score (int) 0-15程度
        """

        score = 0
        text = tweet.get("text", "").lower()
        likes = tweet.get("likes", 0)
        url = tweet.get("url", "")

        # ========================================
        # キーワード加点（各2点）
        # ========================================

        # コラボ
        if any(w in text for w in TweetScorer.KEYWORDS["collaboration"]):
            score += 2
            logger.debug(f"  +2 コラボ")

        # 予約・受注
        if any(w in text for w in TweetScorer.KEYWORDS["presale"]):
            score += 2
            logger.debug(f"  +2 予約/受注")

        # 英語対応
        if any(w in text for w in TweetScorer.KEYWORDS["preorder"]):
            score += 2
            logger.debug(f"  +2 Preorder")

        # 発売・販売・開始
        if any(w in text for w in TweetScorer.KEYWORDS["release"]):
            score += 2
            logger.debug(f"  +2 発売/販売")

        # 限定
        if any(w in text for w in TweetScorer.KEYWORDS["limited"]):
            score += 2
            logger.debug(f"  +2 限定")

        # 時間指定（重要）
        if any(w in text for w in TweetScorer.KEYWORDS["time_specific"]):
            score += 2
            logger.debug(f"  +2 時間指定")

        # 本日・今日
        if any(w in text for w in TweetScorer.KEYWORDS["today"]):
            score += 1
            logger.debug(f"  +1 本日/今日")

        # ========================================
        # URL加点
        # ========================================
        if "http" in text or url:
            score += 1
            logger.debug(f"  +1 URL")

        # ========================================
        # いいね数加点
        # ========================================
        if likes >= 50:
            score += 1
            logger.debug(f"  +1 いいね50以上")

        if likes >= 200:
            score += 2
            logger.debug(f"  +2 いいね200以上")

        if likes >= 500:
            score += 1
            logger.debug(f"  +1 いいね500以上")

        logger.debug(f"  → 最終スコア: {score}")

        return score

    @staticmethod
    def should_notify(score):
        """通知判定"""
        return score >= 5
