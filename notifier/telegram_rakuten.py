import requests
import logging

logger = logging.getLogger(__name__)

class TelegramNotifier:
    def __init__(self, token: str, chat_id: str):
        """
        Telegram 通知クラス
        
        Args:
            token: Telegram Bot Token
            chat_id: Chat ID
        """
        self.token = token
        self.chat_id = chat_id
        self.base_url = f"https://api.telegram.org/bot{token}"
    
    def send_message(self, message: str) -> bool:
        """
        Telegram にメッセージ送信
        
        Args:
            message: 送信するメッセージ
        
        Returns:
            bool: 送信成功時 True
        """
        try:
            url = f"{self.base_url}/sendMessage"
            payload = {
                "chat_id": self.chat_id,
                "text": message,
                "parse_mode": "HTML"
            }
            response = requests.post(url, json=payload, timeout=10)
            
            if response.status_code == 200:
                logger.info(f"✅ Telegram 通知送信成功: {message[:50]}...")
                return True
            else:
                logger.error(f"❌ Telegram 送信失敗 (Status {response.status_code}): {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Telegram 通知エラー: {str(e)}")
            return False
    
    def send_price_alert(self, product_name: str, rakuten_price: float, amazon_price: float, profit: float, rakuten_url: str) -> bool:
        """
        価格差アラート送信
        
        Args:
            product_name: 商品名
            rakuten_price: 楽天価格 (¥)
            amazon_price: Amazon価格 (¥)
            profit: 利益 (¥)
            rakuten_url: 楽天商品URL
        
        Returns:
            bool: 送信成功時 True
        """
        message = f"""
📦 <b>価格差検出!</b>

<b>商品:</b> {product_name[:60]}

💰 <b>楽天:</b> ¥{rakuten_price:,.0f}
💰 <b>Amazon:</b> ¥{amazon_price:,.0f}
📈 <b>利益:</b> <b>¥{profit:,.0f}</b>

🔗 <a href="{rakuten_url}">楽天商品リンク</a>
"""
        return self.send_message(message)
