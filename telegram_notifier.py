import os
import requests

class TelegramNotifier:
    def __init__(self):
        self.token = os.getenv("TELEGRAM_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.session = requests.Session()

        if not self.token or not self.chat_id:
            raise ValueError("Telegram env missing")

    def send(self, message: str):
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"

        data = {
            "chat_id": self.chat_id,
            "text": message
        }

        try:
            r = self.session.post(url, data=data, timeout=10)
            return r.status_code == 200
        except Exception as e:
            print("Telegram error:", e)
            return False