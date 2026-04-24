"""
Budget Bot — FastAPI backend
Handles: API state save/load, Telegram webhook, serves static Mini App
"""
import os, json, hmac, hashlib, sqlite3, logging
from contextlib import contextmanager
from urllib.parse import parse_qsl

from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

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
def startup():
    init_db()
    log.info("DB initialised at %s", DB_PATH)


# ── Serve static Mini App (must be LAST) ─────────────────────────────────────
# Only mounted if static/ folder exists
import pathlib
static_dir = pathlib.Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")


if __name__ == "__main__":
    uvicorn.run("server:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=True)
