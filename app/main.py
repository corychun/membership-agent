from fastapi.middleware.cors import CORSMiddleware
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api import admin, quote, orders, payments, webhooks, deliveries, chat
import app.models.entities  # noqa: F401

# ✅ 数据库相关
from app.core.db import Base, engine, SessionLocal
from app.models.entities import Product

app = FastAPI(title="membership-agent")

# ✅ 创建表
Base.metadata.create_all(bind=engine)


# ✅ 启动时初始化数据（关键）
@app.on_event("startup")
def init_data():
    db = SessionLocal()
    try:
        # 如果没有产品，就自动创建一个
        if not db.query(Product).first():
            p = Product(
                code="basic_plan",
                provider="openai",
                official_plan_name="Basic",
                billing_cycle="monthly",
                official_price=10,
                currency="USD",
                service_fee=1,
                deliver_method="api",
                is_active=True
            )
            db.add(p)
            db.commit()
    finally:
        db.close()


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


# ✅ 静态文件
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
INDEX_FILE = STATIC_DIR / "index.html"

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ✅ 健康检查
@app.get("/health")
def healthcheck():
    return {"status": "ok"}


# ✅ 前端页面
@app.get("/")
def home():
    return HTMLResponse(INDEX_FILE.read_text(encoding="utf-8"))


@app.get("/frontend")
def frontend():
    return HTMLResponse(INDEX_FILE.read_text(encoding="utf-8"))
