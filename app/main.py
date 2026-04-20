from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path
import os

from fastapi import FastAPI, HTTPException, Header
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api import admin, quote, orders, payments, webhooks, deliveries, chat

# ✅ 新增：初始化脚本
from app.init_db import init_db
from app.seed_products import seed_products

app = FastAPI(title="membership-agent")


# ✅ CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ✅ 路由
app.include_router(quote.router)
app.include_router(orders.router)
app.include_router(payments.router)
app.include_router(webhooks.router)
app.include_router(deliveries.router)
app.include_router(chat.router)
app.include_router(admin.router)


# =========================
# ✅ 临时初始化接口（关键）
# =========================
@app.post("/admin/init")
def admin_init(x_admin_token: str = Header(default=None)):
    expected = os.getenv("ADMIN_INIT_TOKEN")

    if not expected:
        raise HTTPException(500, "ADMIN_INIT_TOKEN not set")

    if x_admin_token != expected:
        raise HTTPException(401, "Unauthorized")

    try:
        init_db()
        seed_products()

        return {
            "success": True,
            "message": "DB initialized + product seeded"
        }

    except Exception as e:
        raise HTTPException(500, str(e))


# =========================
# 静态文件
# =========================
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
INDEX_FILE = STATIC_DIR / "index.html"

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# =========================
# 健康检查
# =========================
@app.get("/health")
def healthcheck():
    return {"status": "ok"}


# =========================
# 前端页面
# =========================
@app.get("/")
def home():
    return HTMLResponse(INDEX_FILE.read_text(encoding="utf-8"))


@app.get("/frontend")
def frontend():
    return HTMLResponse(INDEX_FILE.read_text(encoding="utf-8"))
