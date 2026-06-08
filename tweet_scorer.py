import logging

logger = logging.getLogger(__name__)


class TweetScorer:
    """
    スコア >= 5 で通知
    """

    KEYWORDS = {
        "collaboration": ["コラボ", "collaboration", "collab"],
        "presale": ["予約", "予約開始", "受注", "受注販売"],
        "release": ["発売", "販売", "開始", "発売開始", "販売開始"],
        "limited": ["限定", "数量限定", "期間限定", "exclusive"],
        "time_specific": ["12:00", "13:00", "18:00", "20:00"],
        "today": ["本日", "今日", "本日より", "今日から"]
    }

    @staticmethod
    def calculate_score(tweet):
        score = 0
        text = tweet.get("text", "").lower()
        likes = tweet.get("likes", 0)
        url = tweet.get("url", "")

        def hit(key):
            return any(w in text for w in TweetScorer.KEYWORDS[key])

        if hit("collaboration"):
            score += 2

        if hit("presale"):
            score += 2

        if hit("release"):
            score += 2

        if hit("limited"):
            score += 2

        if hit("time_specific"):
            score += 2

        if hit("today"):
            score += 1

        if "http" in text or url:
            score += 1

        if likes >= 50:
            score += 1
        if likes >= 200:
            score += 2
        if likes >= 500:
            score += 1

        # コンボボーナス（重要）
        if hit("limited") and hit("presale"):
            score += 2

        if hit("limited") and hit("time_specific"):
            score += 2

        return score

    @staticmethod
    def should_notify(score):
        return score >= 5