import random
import string
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models.entities import Order

router = APIRouter(tags=["orders"])


ACTIVATION_PRODUCTS = {
    "GPT_ACTIVATE_1M",
    "GPT_ACTIVATE_3M",
    "GPT_TEAM_1M",
    "CLAUDE_ACTIVATE_1M",
    "CLAUDE_ACTIVATE_3M",
    "MJ_BASIC_1M",
    "MJ_STANDARD_1M",
    "MJ_PRO_1M",
    "GEMINI_PRO_1M",
    "PERPLEXITY_PRO_1M",
    "CURSOR_PRO_1M",
    "AI_BUNDLE_1M",
}


class CreateOrderRequest(BaseModel):
    product_code: str
    customer_email: Optional[EmailStr] = None
    email: Optional[EmailStr] = None

    # 支付方式：前端会传 wechat / alipay / usdt。
    # paymentMethod 是为了兼容有些前端写法，不影响原有接口。
    payment_method: Optional[str] = None
    paymentMethod: Optional[str] = None


def make_order_no() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
    return f"ORD-{suffix}"


def get_customer_email(data: CreateOrderRequest) -> str:
    email = data.customer_email or data.email
    if not email:
        raise HTTPException(status_code=400, detail="缺少邮箱")
    return str(email)


def normalize_payment_method(method: Optional[str]) -> str:
    """统一保存支付方式，避免支付宝订单被默认成微信。"""
    value = str(method or "").strip().lower()

    if value in ["alipay", "ali", "支付宝", "zfb"]:
        return "alipay"
    if value in ["usdt", "crypto", "nowpayments", "nowpayments_usdt"]:
        return "usdt"
    if value in ["wechat", "wechat_pay", "wxpay", "weixin", "微信", "微信支付"]:
        return "wechat"

    # 兼容中文或混合字符串
    if "支付宝" in value or "alipay" in value:
        return "alipay"
    if "usdt" in value or "crypto" in value or "nowpayments" in value:
        return "usdt"
    if "微信" in value or "wechat" in value or "wx" in value:
        return "wechat"

    # 没传时默认微信，保持你原来的人工收款默认流程。
    return "wechat"


def get_payment_method(data: CreateOrderRequest) -> str:
    return normalize_payment_method(data.payment_method or data.paymentMethod)


def is_activation_product(product_code: str) -> bool:
    return product_code.upper().strip() in ACTIVATION_PRODUCTS or "ACTIVATE" in product_code.upper()


def ensure_payment_method_column(db: Session) -> None:
    """确保 orders.payment_method 存在。

    只做兼容兜底：如果数据库已经加过字段，不会改变任何数据。
    如果当前数据库不支持该语法，失败也不会影响原有下单流程。
    """
    try:
        db.execute(
            text(
                "ALTER TABLE orders "
                "ADD COLUMN IF NOT EXISTS payment_method VARCHAR(50) DEFAULT 'wechat'"
            )
        )
        db.commit()
    except Exception:
        db.rollback()


def set_order_payment_method(db: Session, order_no: str, payment_method: str) -> None:
    """用原生 SQL 写入 payment_method，避免旧版 Order 模型没有该字段时报错。"""
    try:
        db.execute(
            text("UPDATE orders SET payment_method = :payment_method WHERE order_no = :order_no"),
            {"payment_method": payment_method, "order_no": order_no},
        )
        db.commit()
    except Exception:
        db.rollback()


def read_order_payment_method(db: Session, order_no: str) -> Optional[str]:
    try:
        row = db.execute(
            text("SELECT payment_method FROM orders WHERE order_no = :order_no"),
            {"order_no": order_no},
        ).mappings().first()
        if not row:
            return None
        return row.get("payment_method")
    except Exception:
        return None


def get_inventory_meta(db: Session):
    inspector = inspect(db.bind)
    tables = inspector.get_table_names()

    table_name = None
    for name in ["inventory", "inventory_items", "inventory_item"]:
        if name in tables:
            table_name = name
            break

    if not table_name:
        raise HTTPException(status_code=500, detail="库存表不存在")

    cols = {c["name"] for c in inspector.get_columns(table_name)}

    product_col = "product_code" if "product_code" in cols else "product"

    if product_col not in cols:
        raise HTTPException(
            status_code=500,
            detail="库存表缺少 product_code 或 product 字段",
        )

    return {
        "table": table_name,
        "product_col": product_col,
        "status_col": "status" if "status" in cols else None,
        "used_col": "is_used" if "is_used" in cols else None,
    }


def available_where(meta) -> str:
    parts = []

    if meta["status_col"]:
        parts.append(
            "LOWER(COALESCE(status, 'available')) IN ('available', 'new', 'unused')"
        )

    if meta["used_col"]:
        parts.append("(is_used = false OR is_used IS NULL OR is_used = 0)")

    if not parts:
        return "1=1"

    return "(" + " OR ".join(parts) + ")"


def get_available_stock_count(db: Session, product_code: str) -> int:
    meta = get_inventory_meta(db)

    sql = text(f"""
        SELECT COUNT(*) AS count
        FROM {meta["table"]}
        WHERE UPPER({meta["product_col"]}) = :product_code
          AND {available_where(meta)}
    """)

    row = db.execute(sql, {"product_code": product_code.upper()}).mappings().first()
    return int(row["count"] or 0)


def create_order_logic(data: CreateOrderRequest, db: Session):
    product_code = data.product_code.upper().strip()
    customer_email = get_customer_email(data)
    payment_method = get_payment_method(data)

    ensure_payment_method_column(db)

    stock_count = None

    if not is_activation_product(product_code):
        stock_count = get_available_stock_count(db, product_code)
        if stock_count <= 0:
            raise HTTPException(
                status_code=400,
                detail=f"{product_code} 库存不足，暂时无法购买",
            )

    order_no = make_order_no()

    order = Order(
        order_no=order_no,
        product_code=product_code,
        customer_email=customer_email,
        status="pending_payment",
        payment_status="pending",
        delivery_status="pending",
        delivery_content=None,
        created_at=datetime.utcnow(),
    )

    db.add(order)
    db.commit()
    db.refresh(order)

    set_order_payment_method(db, order_no=order.order_no, payment_method=payment_method)

    return {
        "id": order.id,
        "order_no": order.order_no,
        "product_code": order.product_code,
        "customer_email": order.customer_email,
        "payment_method": payment_method,
        "status": order.status,
        "payment_status": order.payment_status,
        "delivery_status": order.delivery_status,
        "stock_available": stock_count,
        "is_activation_product": is_activation_product(product_code),
    }


@router.post("/orders")
def create_order(data: CreateOrderRequest, db: Session = Depends(get_db)):
    return create_order_logic(data, db)


@router.post("/orders/create")
def create_order_legacy(data: CreateOrderRequest, db: Session = Depends(get_db)):
    return create_order_logic(data, db)


@router.get("/orders/{order_no}")
def get_order(order_no: str, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.order_no == order_no).first()

    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    return {
        "id": order.id,
        "order_no": order.order_no,
        "product_code": order.product_code,
        "customer_email": order.customer_email,
        "payment_method": read_order_payment_method(db, order_no),
        "status": order.status,
        "payment_status": order.payment_status,
        "delivery_status": order.delivery_status,
        "delivery_content": order.delivery_content,
        "created_at": str(order.created_at) if order.created_at else None,
    }


@router.get("/orders/query")
def query_order(order_no: str, db: Session = Depends(get_db)):
    return get_order(order_no=order_no, db=db)
