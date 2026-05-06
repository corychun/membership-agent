import base64
import random
import re
import string
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.products import (
    get_product,
    is_activation_product,
    is_inventory_product,
    product_name,
    product_period_days,
    product_price_cny,
)
from app.models.entities import Order, RenewalTask

router = APIRouter(tags=["orders"])


class CreateOrderRequest(BaseModel):
    product_code: str
    customer_email: Optional[EmailStr] = None
    email: Optional[EmailStr] = None
    payment_method: Optional[str] = None


class UploadPaymentProofRequest(BaseModel):
    order_no: str
    image_data: str
    filename: Optional[str] = None
    customer_email: Optional[EmailStr] = None


def make_order_no() -> str:
    suffix = "".join(random.choices(string.ascii_uppercase + string.digits, k=8))
    return f"ORD-{suffix}"


def get_customer_email(data: CreateOrderRequest) -> str:
    email = data.customer_email or data.email
    if not email:
        raise HTTPException(status_code=400, detail="缺少邮箱")
    return str(email)


def normalize_payment_method(value: str | None) -> str:
    raw = str(value or "").strip().lower()
    if raw in {"wechat", "weixin", "wx", "wxpay", "微信", "微信支付"}:
        return "wechat"
    if raw in {"alipay", "ali", "支付宝", "支付宝支付"}:
        return "alipay"
    if raw in {"usdt", "trc20", "usdttrc20", "nowpayments", "crypto", "加密货币"}:
        return "usdt"
    return "unknown"


def payment_method_label(value: str | None) -> str:
    method = normalize_payment_method(value)
    if method == "wechat":
        return "微信支付"
    if method == "alipay":
        return "支付宝"
    if method == "usdt":
        return "USDT"
    return "未记录"


def save_payment_proof_image(order_no: str, image_data: str, filename: str | None = None) -> str:
    if not image_data or not str(image_data).startswith("data:image/"):
        raise HTTPException(status_code=400, detail="请上传有效的付款截图图片")

    match = re.match(r"^data:image/(png|jpeg|jpg|webp);base64,(.+)$", image_data, re.I | re.S)
    if not match:
        raise HTTPException(status_code=400, detail="仅支持 png / jpg / jpeg / webp 图片")

    ext = match.group(1).lower().replace("jpeg", "jpg")
    raw = match.group(2)

    try:
        content = base64.b64decode(raw, validate=True)
    except Exception:
        raise HTTPException(status_code=400, detail="付款截图解析失败，请重新上传")

    if len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="付款截图不能超过 5MB")

    safe_order_no = re.sub(r"[^A-Za-z0-9_-]", "", order_no or "order")
    static_dir = Path(__file__).resolve().parents[1] / "static"
    upload_dir = static_dir / "uploads" / "payment_proofs"
    upload_dir.mkdir(parents=True, exist_ok=True)
    final_name = f"{safe_order_no}_{uuid.uuid4().hex[:12]}.{ext}"
    final_path = upload_dir / final_name
    final_path.write_bytes(content)
    return f"/static/uploads/payment_proofs/{final_name}"


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
        raise HTTPException(status_code=500, detail="库存表缺少 product_code 或 product 字段")

    return {
        "table": table_name,
        "product_col": product_col,
        "status_col": "status" if "status" in cols else None,
        "used_col": "is_used" if "is_used" in cols else None,
    }


def available_where(meta) -> str:
    parts = []

    if meta["status_col"]:
        parts.append("LOWER(COALESCE(status, 'available')) IN ('available', 'new', 'unused')")

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


def ensure_renewal_task_for_order(db: Session, order: Order) -> None:
    """为代开通订单生成续费/到期管理记录。

    不改变订单主表结构，避免旧数据库 ALTER 失败。
    """
    if not is_activation_product(order.product_code):
        return

    period_days = product_period_days(order.product_code, 30)
    due_at = (order.created_at or datetime.utcnow()) + timedelta(days=period_days)

    existing = db.query(RenewalTask).filter(RenewalTask.order_no == order.order_no).first()
    if existing:
        existing.product_code = order.product_code
        existing.customer_email = order.customer_email
        existing.period_days = period_days
        existing.due_at = existing.due_at or due_at
        existing.updated_at = datetime.utcnow()
        db.add(existing)
        return

    db.add(RenewalTask(
        order_no=order.order_no,
        product_code=order.product_code,
        customer_email=order.customer_email,
        period_days=period_days,
        due_at=due_at,
        status="pending_payment",
        notes="订单创建后自动生成续费管理记录",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    ))


def create_order_logic(data: CreateOrderRequest, db: Session):
    product_code = (data.product_code or "").upper().strip()
    customer_email = get_customer_email(data)

    if not product_code:
        raise HTTPException(status_code=400, detail="缺少产品代码")

    stock_count = None
    product = get_product(product_code)

    # 兼容历史/临时产品：未知产品按库存商品处理，避免破坏旧功能。
    should_check_inventory = (product.inventory if product else not is_activation_product(product_code))

    if should_check_inventory:
        stock_count = get_available_stock_count(db, product_code)
        if stock_count <= 0:
            raise HTTPException(status_code=400, detail=f"{product_code} 库存不足，暂时无法购买")

    order_no = make_order_no()

    order = Order(
        order_no=order_no,
        product_code=product_code,
        customer_email=customer_email,
        status="pending_payment",
        payment_status="pending",
        delivery_status="pending",
        delivery_content=None,
        payment_method=normalize_payment_method(data.payment_method),
        created_at=datetime.utcnow(),
    )

    db.add(order)
    db.flush()
    ensure_renewal_task_for_order(db, order)
    db.commit()
    db.refresh(order)

    return {
        "id": order.id,
        "order_no": order.order_no,
        "product_code": order.product_code,
        "product_name": product_name(order.product_code),
        "product_price_cny": product_price_cny(order.product_code, 0),
        "customer_email": order.customer_email,
        "status": order.status,
        "payment_status": order.payment_status,
        "delivery_status": order.delivery_status,
        "payment_method": payment_method_label(order.payment_method),
        "payment_method_code": normalize_payment_method(order.payment_method),
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

    renewal = db.query(RenewalTask).filter(RenewalTask.order_no == order.order_no).first()

    return {
        "id": order.id,
        "order_no": order.order_no,
        "product_code": order.product_code,
        "product_name": product_name(order.product_code),
        "product_price_cny": product_price_cny(order.product_code, 0),
        "customer_email": order.customer_email,
        "status": order.status,
        "payment_status": order.payment_status,
        "delivery_status": order.delivery_status,
        "delivery_content": order.delivery_content,
        "payment_method": payment_method_label(getattr(order, "payment_method", None)),
        "payment_method_code": normalize_payment_method(getattr(order, "payment_method", None)),
        "payment_proof_url": getattr(order, "payment_proof_url", None),
        "created_at": str(order.created_at) if order.created_at else None,
        "renewal_due_at": str(renewal.due_at) if renewal and renewal.due_at else None,
        "renewal_status": renewal.status if renewal else None,
    }


@router.post("/orders/payment-proof")
def upload_payment_proof(data: UploadPaymentProofRequest, db: Session = Depends(get_db)):
    order_no = (data.order_no or "").strip()
    if not order_no:
        raise HTTPException(status_code=400, detail="缺少订单号")

    order = db.query(Order).filter(Order.order_no == order_no).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")

    # 简单校验邮箱，避免别人拿订单号乱传。历史订单没有邮箱时不阻断。
    if data.customer_email and order.customer_email and str(data.customer_email).lower() != str(order.customer_email).lower():
        raise HTTPException(status_code=403, detail="订单邮箱不匹配")

    if normalize_payment_method(getattr(order, "payment_method", None)) == "usdt":
        raise HTTPException(status_code=400, detail="USDT 订单不需要上传付款截图")

    url = save_payment_proof_image(order.order_no, data.image_data, data.filename)
    order.payment_proof_url = url
    if norm := normalize_payment_method(getattr(order, "payment_method", None)):
        if norm == "unknown":
            order.payment_method = "wechat"
    db.add(order)
    db.commit()
    db.refresh(order)

    return {"ok": True, "order_no": order.order_no, "payment_proof_url": url}


@router.get("/orders/query")
def query_order(order_no: str, db: Session = Depends(get_db)):
    return get_order(order_no=order_no, db=db)
