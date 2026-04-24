"""
Budget Bot — FastAPI backend
Handles: API state save/load, Telegram webhook, serves static Mini App
"""
import os, json, hmac, hashlib, sqlite3, logging
from contextlib import contextmanager
from urllib.parse import parse_qsl
from datetime import datetime

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import httpx
import uvicorn

try:
    from apscheduler.schedulers.asyncio import AsyncIOScheduler
    from apscheduler.triggers.cron import CronTrigger
    HAS_APScheduler = True
except ImportError:
    HAS_APScheduler = False

scheduler = None

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

BOT_TOKEN  = os.getenv("BOT_TOKEN", "")
WEBHOOK_PATH = "/webhook/" + BOT_TOKEN  # secret path
DB_PATH    = os.getenv("DB_PATH", "budget.db")

app = FastAPI(title="Budget Bot API", docs_url=None, redoc_url=None)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ── Database ─────────────────────────────────────────────────────────────────

def init_db():
    with sqlite3.connect(DB_PATH) as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS user_state (
                user_id  INTEGER PRIMARY KEY,
                username TEXT,
                state    TEXT NOT NULL DEFAULT '{}',
                updated  TEXT DEFAULT (datetime('now'))
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS habit_notifs (
                user_id    INTEGER,
                hab_id     TEXT,
                hab_name   TEXT,
                notif_time TEXT,
                PRIMARY KEY (user_id, hab_id)
            )
        """)
        db.commit()

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

# ── Telegram init data validation ────────────────────────────────────────────

def validate_init_data(raw: str) -> dict:
    """Verify Telegram WebApp initData signature, return user dict."""
    if not BOT_TOKEN:
        raise HTTPException(status_code=500, detail="BOT_TOKEN not set")
    if not raw:
        raise HTTPException(status_code=401, detail="Missing init data")

    params = dict(parse_qsl(raw, keep_blank_values=True))
    received_hash = params.pop("hash", "")

    check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(params.items())
    )
    secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    expected    = hmac.new(secret_key, check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(expected, received_hash):
        raise HTTPException(status_code=401, detail="Invalid init data signature")

    user = json.loads(params.get("user", "{}"))
    if not user.get("id"):
        raise HTTPException(status_code=401, detail="No user in init data")
    return user

def get_user_from_request(request: Request) -> dict:
    raw = request.headers.get("X-Init-Data", "")
    # Dev mode: allow ?dev=USER_ID to skip validation
    dev = request.query_params.get("dev")
    if dev and not BOT_TOKEN:
        return {"id": int(dev), "first_name": "Dev"}
    return validate_init_data(raw)

# ── API routes ────────────────────────────────────────────────────────────────

@app.get("/api/state")
async def get_state(request: Request):
    user = get_user_from_request(request)
    user_id = user["id"]
    with get_db() as db:
        row = db.execute(
            "SELECT state FROM user_state WHERE user_id = ?", (user_id,)
        ).fetchone()
    if row:
        return JSONResponse(json.loads(row["state"]))
    return JSONResponse({})


@app.post("/api/state")
async def save_state(request: Request):
    user = get_user_from_request(request)
    user_id   = user["id"]
    username  = user.get("username", "")
    body      = await request.json()
    state_str = json.dumps(body, ensure_ascii=False)

    with get_db() as db:
        db.execute("""
            INSERT INTO user_state (user_id, username, state, updated)
            VALUES (?, ?, ?, datetime('now'))
            ON CONFLICT(user_id) DO UPDATE SET
                state   = excluded.state,
                username = excluded.username,
                updated = excluded.updated
        """, (user_id, username, state_str))
        db.commit()
    return {"ok": True}


async def _send_tg_message(chat_id: int, text: str):
    if not BOT_TOKEN:
        return
    try:
        async with httpx.AsyncClient() as client:
            await client.post(
                f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                json={"chat_id": chat_id, "text": text}
            )
    except Exception as e:
        log.error("TG send error: %s", e)


@app.post("/api/notify")
async def save_notification(request: Request):
    """Save/update notification schedule for a habit, or send immediate test."""
    user = get_user_from_request(request)
    user_id = user["id"]
    body = await request.json()
    hab_id    = body.get("habId", "")
    hab_name  = body.get("habitName", "Привычка")
    notif_time = body.get("time", "")     # "07:30" or ""
    test_only  = body.get("test", False)

    if not BOT_TOKEN:
        return {"ok": False, "error": "BOT_TOKEN not configured"}

    # Immediate test message
    if test_only:
        msg = f"🔔 Напоминание: {hab_name}\n\nВремя выполнить привычку!"
        await _send_tg_message(user_id, msg)
        return {"ok": True}

    # Save / remove notification preference
    with get_db() as db:
        if notif_time:
            db.execute("""
                INSERT INTO habit_notifs (user_id, hab_id, hab_name, notif_time)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(user_id, hab_id) DO UPDATE SET
                    hab_name=excluded.hab_name,
                    notif_time=excluded.notif_time
            """, (user_id, hab_id, hab_name, notif_time))
        else:
            db.execute("DELETE FROM habit_notifs WHERE user_id=? AND hab_id=?", (user_id, hab_id))
        db.commit()

    # Re-schedule in APScheduler
    if HAS_APScheduler and scheduler:
        job_id = f"notif_{user_id}_{hab_id}"
        try:
            scheduler.remove_job(job_id)
        except Exception:
            pass
        if notif_time:
            h, m = map(int, notif_time.split(":"))
            scheduler.add_job(
                _send_tg_message,
                CronTrigger(hour=h, minute=m),
                args=[user_id, f"🔔 {hab_name}\n\nВремя выполнить привычку!"],
                id=job_id,
                replace_existing=True,
            )

    return {"ok": True}


# ── Telegram webhook ──────────────────────────────────────────────────────────

@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    """Handle Telegram updates via webhook."""
    try:
        from bot import handle_update
        data = await request.json()
        await handle_update(data)
    except Exception as e:
        log.error("Webhook error: %s", e)
    return {"ok": True}


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    global scheduler
    init_db()
    log.info("DB initialised at %s", DB_PATH)
    if HAS_APScheduler:
        scheduler = AsyncIOScheduler()
        scheduler.start()
        # Reload saved notification schedules
        with get_db() as db:
            rows = db.execute("SELECT user_id, hab_id, hab_name, notif_time FROM habit_notifs").fetchall()
        for row in rows:
            uid, hid, hname, htime = row["user_id"], row["hab_id"], row["hab_name"], row["notif_time"]
            if htime:
                try:
                    h, m = map(int, htime.split(":"))
                    scheduler.add_job(
                        _send_tg_message,
                        CronTrigger(hour=h, minute=m),
                        args=[uid, f"🔔 {hname}\n\nВремя выполнить привычку!"],
                        id=f"notif_{uid}_{hid}",
                        replace_existing=True,
                    )
                except Exception as e:
                    log.warning("Could not restore notif job: %s", e)
        log.info("Scheduler started, %d jobs loaded", len(rows))
    else:
        log.warning("APScheduler not installed — push notifications disabled")


# ── Serve static Mini App (must be LAST) ─────────────────────────────────────
# Only mounted if static/ folder exists
import pathlib
static_dir = pathlib.Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=True)
