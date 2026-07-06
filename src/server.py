from dotenv import load_dotenv
load_dotenv()

import os
import sys

# Validate BOT_TOKEN
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    print("❌ BOT_TOKEN is required. Set it in .env file.", file=sys.stderr)
    print("   Create a bot via @BotFather on Telegram to get a token.", file=sys.stderr)
    sys.exit(1)

import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.responses import JSONResponse
from datetime import datetime, timezone

from src.database import init_db
from src.bot import bot, dp
from src.api import router as api_router

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize database
    print("📦 Initializing database...")
    init_db()
    print("✅ Database ready")

    # Start Telegram bot (polling) in the background
    print("🤖 Starting Telegram bot...")
    polling_task = asyncio.create_task(dp.start_polling(bot))

    try:
        bot_info = await bot.get_me()
        print(f"✅ Bot @{bot_info.username} is running")
    except Exception as e:
        print("⚠️ Failed to fetch bot info on start:", e)

    yield

    # Graceful shutdown
    print("\n🛑 Shutting down...")
    polling_task.cancel()
    try:
        await polling_task
    except asyncio.CancelledError:
        pass

    await bot.session.close()
    print("👋 Shutdown complete")

app = FastAPI(lifespan=lifespan)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Custom exception handler to format HTTP errors with an 'error' key
# this ensures complete compatibility with the frontend's API error parsing
@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail},
    )

# Mount API routes
app.include_router(api_router)

# Health check
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
    }

# Serve static files (Mini App)
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PUBLIC_DIR = os.path.join(BASE_DIR, "public")
app.mount("/", StaticFiles(directory=PUBLIC_DIR, html=True), name="public")

if __name__ == "__main__":
    import uvicorn

    PORT = int(os.getenv("PORT", "3000"))
    WEBAPP_URL = os.getenv("WEBAPP_URL", f"http://localhost:{PORT}")

    print(f"🌐 Server running at http://localhost:{PORT}")
    print(f"📋 Employee app: {WEBAPP_URL}/status/")
    print(f"📊 Dashboard: {WEBAPP_URL}/dashboard/")

    uvicorn.run(app, host="0.0.0.0", port=PORT)
