"""
Budget Bot — Telegram bot logic
Can run standalone (polling) or be called from server.py (webhook).
"""
import os, json, logging, asyncio
import httpx

BOT_TOKEN   = os.getenv("BOT_TOKEN", "")
WEBAPP_URL  = os.getenv("WEBAPP_URL", "https://your-domain.com")
API_BASE    = f"https://api.telegram.org/bot{BOT_TOKEN}"

log = logging.getLogger(__name__)


async def send_message(chat_id: int, text: str, reply_markup: dict = None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    async with httpx.AsyncClient() as client:
        await client.post(f"{API_BASE}/sendMessage", json=payload)


async def handle_update(data: dict):
    """Entry point for both webhook and polling modes."""
    message = data.get("message") or data.get("edited_message")
    if not message:
        return

    chat_id = message["chat"]["id"]
    text    = message.get("text", "")

    if text.startswith("/start"):
        await cmd_start(chat_id, message.get("from", {}))
    elif text.startswith("/help"):
        await cmd_help(chat_id)
    elif text.startswith("/stats"):
        await cmd_stats(chat_id)


async def cmd_start(chat_id: int, user: dict):
    name = user.get("first_name", "друг")
    keyboard = {
        "inline_keyboard": [[{
            "text": "💰 Открыть бюджет",
            "web_app": {"url": WEBAPP_URL}
        }]]
    }
    await send_message(
        chat_id,
        f"Привет, <b>{name}</b>! 👋\n\n"
        f"Твой личный финансовый трекер:\n"
        f"• Расходы и доходы по дням\n"
        f"• Прогресс погашения долга\n"
        f"• Привычки и чеклисты\n"
        f"• Цели на неделю / месяц\n\n"
        f"Все данные сохраняются в базе — история не сбрасывается 🔒",
        keyboard
    )


async def cmd_help(chat_id: int):
    keyboard = {
        "inline_keyboard": [[{
            "text": "📱 Открыть приложение",
            "web_app": {"url": WEBAPP_URL}
        }]]
    }
    await send_message(
        chat_id,
        "<b>Команды:</b>\n"
        "/start — открыть трекер\n"
        "/stats — краткая статистика\n"
        "/help — эта справка",
        keyboard
    )


async def cmd_stats(chat_id: int):
    # Quick stats without loading full state — just point to the app
    keyboard = {
        "inline_keyboard": [[{
            "text": "📊 Открыть детали",
            "web_app": {"url": WEBAPP_URL}
        }]]
    }
    await send_message(
        chat_id,
        "📊 Открой приложение чтобы увидеть полную статистику.",
        keyboard
    )


async def set_webhook(webhook_url: str):
    """Register webhook with Telegram."""
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{API_BASE}/setWebhook", json={"url": webhook_url})
        data = r.json()
        if data.get("ok"):
            log.info("Webhook set to %s", webhook_url)
        else:
            log.error("Failed to set webhook: %s", data)
        return data


async def delete_webhook():
    async with httpx.AsyncClient() as client:
        r = await client.post(f"{API_BASE}/deleteWebhook")
        return r.json()


# ── Polling mode (for local development) ─────────────────────────────────────

async def poll():
    """Long-polling loop — use for local testing only."""
    log.info("Starting polling mode...")
    await delete_webhook()
    offset = 0
    async with httpx.AsyncClient(timeout=35) as client:
        while True:
            try:
                r = await client.get(f"{API_BASE}/getUpdates", params={
                    "offset": offset, "timeout": 30
                })
                updates = r.json().get("result", [])
                for upd in updates:
                    offset = upd["update_id"] + 1
                    await handle_update(upd)
            except Exception as e:
                log.error("Polling error: %s", e)
                await asyncio.sleep(3)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(poll())
