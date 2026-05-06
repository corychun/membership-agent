from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import JSONResponse

from app.core.db import Base, engine, SessionLocal
from app.models.entities import SystemErrorLog
from sqlalchemy import inspect, text
from app.core.admin_auth import seed_first_admin

from app.api.orders import router as orders
from app.api.payments import router as payments
from app.api.webhooks import router as webhooks
from app.api.deliveries import router as deliveries
from app.api.inventory import router as inventory_router
from app.api.admin import router as admin_router
from app.api.support import router as support_router
from app.api.support_ws import router as support_ws_router
from app.api.products import router as products_router


def ensure_order_extra_columns():
    """给旧数据库补充新字段。

    只添加缺失字段，不删除、不修改旧字段，避免影响现有订单、库存、发货、邮件功能。
    """
    try:
        inspector = inspect(engine)
        tables = inspector.get_table_names()
        if "orders" not in tables:
            return

        existing = {c["name"] for c in inspector.get_columns("orders")}
        columns = {
            "payment_method": "VARCHAR(50)",
            "payment_proof_url": "VARCHAR(500)",
            "payment_proof_status": "VARCHAR(50) DEFAULT 'not_uploaded'",
            "payment_proof_checked_at": "TIMESTAMP",
            "payment_proof_checked_by": "VARCHAR(80)",
            "admin_note": "TEXT",
            "payment_confirm_note": "TEXT",
            "confirmed_at": "TIMESTAMP",
        }

        with engine.begin() as conn:
            for name, column_type in columns.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE orders ADD COLUMN {name} {column_type}"))
    except Exception as e:
        # 迁移失败不能阻止服务启动，具体错误可在 Render 日志查看。
        print(f"ensure_order_extra_columns skipped: {e}")

app = FastAPI(title="membership-agent", version="1.0.0")


@app.on_event("startup")
def init():
    Base.metadata.create_all(bind=engine)
    ensure_order_extra_columns()

    db = SessionLocal()
    try:
        seed_first_admin(db)
    finally:
        db.close()


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
def root():
    return {"ok": True}


@app.get("/health")
def health():
    return {"ok": True}



@app.exception_handler(Exception)
async def log_unhandled_exception(request: Request, exc: Exception):
    db = SessionLocal()
    try:
        db.add(SystemErrorLog(
            source="api",
            level="error",
            message=str(exc),
            detail=f"{request.method} {request.url.path}",
        ))
        db.commit()
    except Exception as log_error:
        print(f"system error log skipped: {log_error}")
    finally:
        db.close()
    return JSONResponse(status_code=500, content={"detail": "系统异常，请稍后重试"})


app.include_router(orders)
app.include_router(payments)
app.include_router(webhooks)
app.include_router(deliveries)
app.include_router(inventory_router)
app.include_router(admin_router)
app.include_router(support_router)
app.include_router(support_ws_router)
app.include_router(products_router)
