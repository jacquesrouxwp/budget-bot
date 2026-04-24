"""
Запусти один раз после деплоя чтобы зарегистрировать webhook:
  python setup_webhook.py
"""
import asyncio, os
from dotenv import load_dotenv
load_dotenv()
from bot import set_webhook, BOT_TOKEN

WEBAPP_URL = os.getenv("WEBAPP_URL", "")

async def main():
    if not BOT_TOKEN:
        print("❌ BOT_TOKEN не задан в .env")
        return
    if not WEBAPP_URL:
        print("❌ WEBAPP_URL не задан в .env")
        return
    webhook_url = WEBAPP_URL.rstrip("/") + "/webhook/" + BOT_TOKEN
    print(f"Регистрирую webhook: {webhook_url}")
    result = await set_webhook(webhook_url)
    if result.get("ok"):
        print("✅ Webhook успешно установлен!")
    else:
        print(f"❌ Ошибка: {result}")

asyncio.run(main())
