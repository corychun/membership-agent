import traceback
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

from app.core.admin_auth import admin_to_dict, normalize_role, require_permission
from app.core.db import get_db
from app.core.products import product_amount_usd, product_name, product_period_days, product_price_cny
from app.core.security import create_admin_token, hash_password, verify_password
from app.models.entities import AdminUser, DeliveryRecord, Order, OrderLog, RenewalTask
from app.services.delivery import mark_paid_and_deliver
from app.services.email_service import send_delivery_email

router = APIRouter(prefix="/admin", tags=["admin"])


class LoginRequest(BaseModel):
    username: str
    password: str


class ConfirmPaidRequest(BaseModel):
    order_no: str


class BulkConfirmPaidRequest(BaseModel):
    order_nos: list[str]


class ManualCompleteRequest(BaseModel):
    order_no: str
    delivery_content: str
    send_email: bool = True


class CancelOrderRequest(BaseModel):
    order_no: str
    reason: str = "管理员取消订单"


class RenewalUpdateRequest(BaseModel):
    notes: Optional[str] = None


class CreateAdminRequest(BaseModel):
    username: str
    password: str
    role: str = "support"


class UpdateAdminRequest(BaseModel):
    password: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


def norm(value):
    return str(value or "").lower()


def status_snapshot(order: Order) -> str:
    return f"status={order.status};payment_status={order.payment_status};delivery_status={order.delivery_status}"


def write_order_log(
    db: Session,
    order: Order | None,
    admin: AdminUser | None,
    action: str,
    before_status: str | None = None,
    detail: str = "",
):
    try:
        db.add(OrderLog(
            order_no=order.order_no if order else None,
            admin_id=admin.id if admin else None,
            admin_name=admin.username if admin else None,
            action=action,
            before_status=before_status,
            after_status=status_snapshot(order) if order else None,
            detail=detail,
            created_at=datetime.utcnow(),
        ))
    except Exception:
        # 日志不能影响主流程
        pass


def is_delivered(order: Order) -> bool:
    return norm(order.delivery_status) in {"delivered", "completed", "success", "sent"}


def is_cancelled(order: Order) -> bool:
    return norm(order.status) in {"cancelled", "canceled", "cancel"} or norm(order.delivery_status) in {"cancelled", "canceled", "cancel"}


def can_manual_confirm(order: Order) -> bool:
    if is_delivered(order) or is_cancelled(order):
        return False
    return norm(order.payment_status) in {
        "waiting", "pending", "pending_payment", "unpaid", "paid", "finished", "confirmed", "", "none",
    }


def get_or_create_renewal_task(db: Session, order: Order, status: str = "active") -> RenewalTask:
    period_days = product_period_days(order.product_code, 30)
    due_at = datetime.utcnow() + timedelta(days=period_days)
    task = db.query(RenewalTask).filter(RenewalTask.order_no == order.order_no).first()
    if not task:
        task = RenewalTask(
            order_no=order.order_no,
            product_code=order.product_code,
            customer_email=order.customer_email,
            period_days=period_days,
            due_at=due_at,
            status=status,
            notes="后台自动创建续费管理记录",
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
        db.add(task)
    else:
        task.product_code = order.product_code
        task.customer_email = order.customer_email
        task.period_days = period_days
        if not task.due_at:
            task.due_at = due_at
        task.status = status
        task.updated_at = datetime.utcnow()
        db.add(task)
    return task


def update_renewal_status_for_order(db: Session, order: Order, status: str, notes: str | None = None):
    task = db.query(RenewalTask).filter(RenewalTask.order_no == order.order_no).first()
    if task:
        task.status = status
        task.updated_at = datetime.utcnow()
        if notes:
            task.notes = notes
        db.add(task)




def safe_order_attr(order: Order, *names, default=None):
    """读取 ORM 上已有的字段，兼容不同版本的 Order 模型。"""
    for name in names:
        try:
            value = getattr(order, name, None)
        except Exception:
            value = None
        if value is not None and value != "":
            return value
    return default


ORDER_EXTRA_COLUMNS = [
    "payment_method", "pay_method", "payment_provider", "provider", "checkout_provider", "pay_channel",
    "payment_amount", "pay_amount", "paid_amount", "amount", "total_amount", "amount_usd", "amount_usdt",
    "price_usdt", "product_price_usdt", "pay_currency", "payment_currency", "currency",
]


def get_existing_order_extra_columns(db: Session | None) -> list[str]:
    """只探测一次 orders 表字段，避免订单列表逐条探测导致后台一直加载。"""
    if db is None:
        return []
    try:
        inspector = inspect(db.bind)
        cols = {c["name"] for c in inspector.get_columns("orders")}
        return [c for c in ORDER_EXTRA_COLUMNS if c in cols]
    except Exception:
        return []


def read_order_extras_from_db(db: Session | None, orders: list[Order]) -> dict[int, dict]:
    """批量读取 orders 表真实字段。

    目的：不改数据库结构、不影响原有功能。
    旧 Order 模型没有声明的付款金额/支付方式字段，用一条 SQL 批量读取，
    避免逐条查询导致 Render/Neon 后台订单页卡在“加载中”。
    """
    if db is None or not orders:
        return {}

    ids = [getattr(o, "id", None) for o in orders if getattr(o, "id", None)]
    if not ids:
        return {}

    try:
        selected = get_existing_order_extra_columns(db)
        if not selected:
            return {}
        sql = text('SELECT id, ' + ', '.join(selected) + ' FROM orders WHERE id = ANY(:ids)')
        rows = db.execute(sql, {"ids": ids}).mappings().all()
        return {int(row["id"]): dict(row) for row in rows}
    except Exception:
        # 付款展示不能影响后台订单列表主流程
        return {}


def read_order_extra_from_db(db: Session | None, order: Order) -> dict:
    """兼容单条读取场景；列表接口不要用这个逐条查询。"""
    data = read_order_extras_from_db(db, [order])
    return data.get(int(getattr(order, "id", 0) or 0), {})


def first_value(data: dict, names: list[str], default=None):
    for name in names:
        value = data.get(name)
        if value is not None and value != "":
            return value
    return default


def normalize_payment_method_label(value, order: Order | None = None) -> str:
    raw = str(value or "").strip()

    # 只显示订单里真实记录到的支付方式。
    # 没有记录就显示“未记录”，避免把旧订单误判成微信/支付宝/USDT。
    if not raw:
        return "未记录"
    v = raw.lower()
    if "wechat" in v or "wxpay" in v or "weixin" in v or v == "wx":
        return "微信支付"
    if "alipay" in v or v == "ali":
        return "支付宝"
    if "nowpayments" in v:
        return "NOWPayments / USDT"
    if "trc20" in v:
        return "USDT-TRC20"
    if "usdt" in v or "crypto" in v:
        return "USDT"
    return raw


def format_amount_value(value, currency: str = "") -> str:
    if value is None or value == "":
        return ""
    try:
        num = float(value)
        if num.is_integer():
            text = str(int(num))
        else:
            text = (f"{num:.8f}").rstrip("0").rstrip(".")
    except Exception:
        text = str(value)
    currency = (currency or "").strip().upper()
    return f"{text} {currency}".strip()


def get_payment_amount_for_order(order: Order, extra: dict, payment_method_label: str = "") -> tuple[object, str]:
    """后台付款金额展示规则：
    - 微信/支付宝：按套餐人民币价格显示，例如 220 元
    - USDT/NOWPayments/TRC20：按套餐 USDT 价格显示，例如 26 USDT
    - 未记录支付方式：不强行猜测，优先显示真实订单金额；没有金额则显示当前套餐 USDT 价格

    这里只影响后台展示，不写数据库，不改变订单/发货/库存/邮件流程。
    """
    method = str(payment_method_label or "").lower()

    if "微信" in payment_method_label or "支付宝" in payment_method_label or "wechat" in method or "wxpay" in method or "alipay" in method:
        return product_price_cny(order.product_code, 0), "元"

    if "usdt" in method or "nowpayments" in method or "trc20" in method or "crypto" in method:
        return product_amount_usd(order.product_code, 0), "USDT"

    amount_names = [
        "payment_amount", "pay_amount", "paid_amount", "amount", "total_amount",
        "amount_usdt", "price_usdt", "product_price_usdt", "amount_usd",
    ]
    currency_names = ["payment_currency", "currency", "pay_currency"]

    amount = safe_order_attr(order, *amount_names)
    if amount is None or amount == "":
        amount = first_value(extra, amount_names)

    currency = safe_order_attr(order, *currency_names, default=None)
    if not currency:
        currency = first_value(extra, currency_names)

    if amount is None or amount == "":
        amount = product_amount_usd(order.product_code, 0)
        currency = "USDT"

    currency_text = str(currency or "USDT").upper()
    if currency_text in {"USDTTRC20", "USDT_TRC20", "TRC20", "USD"}:
        currency_text = "USDT"
    if currency_text in {"CNY", "RMB", "人民币"}:
        currency_text = "元"

    return amount, currency_text


def get_payment_method_for_order(order: Order, extra: dict) -> str:
    names = ["payment_method", "pay_method", "payment_provider", "provider", "checkout_provider", "pay_channel", "pay_currency"]
    value = safe_order_attr(order, *names)
    if value is None or value == "":
        value = first_value(extra, names)
    return normalize_payment_method_label(value, order)


def is_revenue_order(order: Order) -> bool:
    """是否计入收入统计。只统计已付款/已完成订单，取消订单不计入。"""
    if is_cancelled(order):
        return False
    payment = norm(getattr(order, "payment_status", ""))
    status = norm(getattr(order, "status", ""))
    delivery = norm(getattr(order, "delivery_status", ""))
    return (
        payment in {"paid", "finished", "confirmed", "success", "completed"}
        or status in {"paid", "completed", "success"}
        or delivery in {"delivered", "completed", "success", "sent"}
    )


def revenue_amount_for_order(order: Order, extra: dict) -> tuple[float, str]:
    method_label = get_payment_method_for_order(order, extra)
    amount, currency = get_payment_amount_for_order(order, extra, method_label)
    try:
        num = float(amount or 0)
    except Exception:
        num = 0.0
    currency_text = str(currency or "USDT").upper()
    if currency_text in {"CNY", "RMB", "人民币", "元"}:
        currency_text = "CNY"
    elif "元" in currency_text:
        currency_text = "CNY"
    else:
        currency_text = "USDT"
    return num, currency_text


def format_revenue_number(value: float) -> str:
    try:
        value = float(value or 0)
    except Exception:
        value = 0.0
    if value.is_integer():
        return str(int(value))
    return (f"{value:.2f}").rstrip("0").rstrip(".")

def suggested_delivery_content(order: Order) -> str:
    name = product_name(order.product_code)
    code = str(order.product_code or "").upper()
    period_days = product_period_days(order.product_code, 30)
    expire_at = datetime.utcnow() + timedelta(days=period_days)
    expire_text = expire_at.strftime("%Y-%m-%d") + " 23:59（北京时间）"

    service = name
    if "GPT" in code or "CHATGPT" in name.upper():
        service = "ChatGPT Plus" if "PLUS" in code or "PLUS" in name.upper() else "ChatGPT"
    elif "CLAUDE" in code or "CLAUDE" in name.upper():
        service = "Claude Pro" if "PRO" in code or "PRO" in name.upper() else "Claude"
    elif "MJ" in code or "MIDJOURNEY" in name.upper():
        if "BASIC" in code or "BASIC" in name.upper():
            service = "Midjourney Basic"
        elif "STANDARD" in code or "STANDARD" in name.upper():
            service = "Midjourney Standard"
        elif "PRO" in code or "PRO" in name.upper():
            service = "Midjourney Pro"
        elif "MEGA" in code or "MEGA" in name.upper():
            service = "Midjourney Mega"
        else:
            service = "Midjourney"
    elif "GEMINI" in code or "GEMINI" in name.upper():
        if "ULTRA" in code or "ULTRA" in name.upper():
            service = "Gemini Ultra"
        elif "PRO" in code or "PRO" in name.upper():
            service = "Gemini Pro"
        else:
            service = "Gemini Advanced"

    return (
        f"已为您账号开通 {service}，有效期至 {expire_text}。\n"
        "请登录原账号查看，如有问题请联系网站客服。"
    )

def order_to_dict(o: Order, db: Session | None = None, extra: dict | None = None):
    extra = extra if extra is not None else read_order_extra_from_db(db, o)
    payment_method_label = get_payment_method_for_order(o, extra)
    payment_amount, payment_currency = get_payment_amount_for_order(o, extra, payment_method_label)

    return {
        "id": o.id,
        "order_no": o.order_no,
        "product_code": o.product_code,
        "product_name": product_name(o.product_code),
        "product_price_cny": product_price_cny(o.product_code, 0),
        "customer_email": o.customer_email,
        "payment_status": o.payment_status,
        "status": o.status,
        "delivery_status": o.delivery_status,
        "delivery_content": o.delivery_content,
        "created_at": str(o.created_at) if o.created_at else None,
        "payment_method": payment_method_label,
        "payment_method_label": payment_method_label,
        "payment_amount": payment_amount,
        "payment_currency": payment_currency,
        "payment_amount_text": format_amount_value(payment_amount, payment_currency),
        "suggested_delivery_content": suggested_delivery_content(o),
        "can_confirm": can_manual_confirm(o),
    }

@router.post("/login")
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    username = (payload.username or "").strip()
    admin = db.query(AdminUser).filter(AdminUser.username == username).first()

    if not admin or int(admin.is_active or 0) != 1 or not verify_password(payload.password, admin.password_hash):
        raise HTTPException(status_code=401, detail="账号或密码错误")

    admin.last_login_at = datetime.utcnow()
    db.commit()
    db.refresh(admin)

    token = create_admin_token({"sub": admin.id, "username": admin.username, "role": admin.role})
    return {"ok": True, "access_token": token, "token_type": "bearer", "admin": admin_to_dict(admin)}


@router.get("/me")
def me(current_admin: AdminUser = Depends(require_permission("orders:read"))):
    return {"ok": True, "admin": admin_to_dict(current_admin)}


@router.get("/orders")
def list_orders(
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("orders:read")),
):
    orders = db.query(Order).order_by(Order.id.desc()).limit(200).all()
    extras_by_id = read_order_extras_from_db(db, orders)
    return {"items": [order_to_dict(o, db, extras_by_id.get(int(o.id), {})) for o in orders]}


@router.get("/revenue/daily")
def daily_revenue(
    days: int = 30,
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("orders:read")),
):
    """后台每日收入金额统计。

    只读统计接口，不写数据库，不影响订单/库存/发货/邮件流程。
    微信/支付宝按人民币统计，USDT/NOWPayments/TRC20按USDT统计。
    """
    try:
        days = int(days or 30)
    except Exception:
        days = 30
    days = max(1, min(days, 90))

    # 今日收入按北京时间自然日统计。
    # 数据库 created_at 仍按原来的 UTC 时间保存，这里只在统计时换算到北京时间，
    # 不修改订单、库存、发货、邮件等任何现有流程。
    beijing_offset = timedelta(hours=8)
    now_utc = datetime.utcnow()
    now_bj = now_utc + beijing_offset
    start_bj_day = now_bj.date() - timedelta(days=days - 1)
    start_utc = datetime.combine(start_bj_day, datetime.min.time()) - beijing_offset

    orders = (
        db.query(Order)
        .filter(Order.created_at >= start_utc)
        .order_by(Order.created_at.desc())
        .limit(5000)
        .all()
    )
    extras_by_id = read_order_extras_from_db(db, orders)

    daily: dict[str, dict] = {}
    for order in orders:
        if not is_revenue_order(order):
            continue
        created_utc = getattr(order, "created_at", None) or now_utc
        created_bj = created_utc + beijing_offset
        day = created_bj.date().isoformat()
        item = daily.setdefault(day, {"date": day, "cny": 0.0, "usdt": 0.0, "orders": 0})
        amount, currency = revenue_amount_for_order(order, extras_by_id.get(int(order.id), {}))
        if currency == "CNY":
            item["cny"] += amount
        else:
            item["usdt"] += amount
        item["orders"] += 1

    today_key = now_bj.date().isoformat()
    today = daily.get(today_key, {"date": today_key, "cny": 0.0, "usdt": 0.0, "orders": 0})
    items = []
    for offset in range(days):
        day = (now_bj.date() - timedelta(days=offset)).isoformat()
        item = daily.get(day, {"date": day, "cny": 0.0, "usdt": 0.0, "orders": 0})
        items.append({
            "date": item["date"],
            "cny": format_revenue_number(item["cny"]),
            "usdt": format_revenue_number(item["usdt"]),
            "orders": item["orders"],
        })

    return {
        "ok": True,
        "today": {
            "date": today["date"],
            "cny": format_revenue_number(today["cny"]),
            "usdt": format_revenue_number(today["usdt"]),
            "orders": today["orders"],
        },
        "items": items,
    }


@router.post("/orders/confirm-paid")
def confirm_paid_and_deliver(
    payload: ConfirmPaidRequest,
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("orders:confirm")),
):
    order = db.query(Order).filter(Order.order_no == payload.order_no).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    before = status_snapshot(order)

    if is_delivered(order):
        write_order_log(db, order, current_admin, "confirm_paid_skip_already_delivered", before, "重复点击确认，订单已完成")
        db.commit()
        return {"ok": True, "msg": "already delivered", "order_no": order.order_no, "delivery_content": order.delivery_content}

    if is_cancelled(order):
        raise HTTPException(status_code=400, detail="订单已取消，不能继续处理")

    if not can_manual_confirm(order):
        raise HTTPException(
            status_code=400,
            detail=f"当前状态不允许发货：payment_status={order.payment_status}, delivery_status={order.delivery_status}",
        )

    try:
        result = mark_paid_and_deliver(db, order)
        db.refresh(order)
        if norm(order.delivery_status) in {"processing", "delivered", "completed", "sent"}:
            get_or_create_renewal_task(db, order, "active" if is_delivered(order) else "processing")
        write_order_log(db, order, current_admin, "confirm_paid", before, "确认收款并进入发货/代开通流程")
        db.commit()
        db.refresh(order)
        return {"ok": True, "msg": "paid + delivered", "order_no": order.order_no, "delivery_content": order.delivery_content, "result": result}
    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        print("confirm_paid_and_deliver error:")
        print(traceback.format_exc())
        raise HTTPException(status_code=400, detail=f"发货失败：{str(e)}")


@router.post("/orders/confirm-paid-bulk")
def confirm_paid_and_deliver_bulk(
    payload: BulkConfirmPaidRequest,
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("orders:confirm")),
):
    order_nos = []
    seen = set()
    for order_no in payload.order_nos or []:
        value = (order_no or "").strip()
        if value and value not in seen:
            seen.add(value)
            order_nos.append(value)

    if not order_nos:
        raise HTTPException(status_code=400, detail="请选择要确认的订单")
    if len(order_nos) > 50:
        raise HTTPException(status_code=400, detail="单次最多批量处理 50 个订单")

    results = []
    success_count = 0
    failed_count = 0

    for order_no in order_nos:
        order = db.query(Order).filter(Order.order_no == order_no).first()
        if not order:
            failed_count += 1
            results.append({"order_no": order_no, "ok": False, "msg": "订单不存在"})
            continue

        before = status_snapshot(order)

        if is_delivered(order):
            success_count += 1
            write_order_log(db, order, current_admin, "bulk_skip_already_delivered", before, "批量处理时跳过已完成订单")
            results.append({"order_no": order_no, "ok": True, "msg": "已发货，跳过", "delivery_content": order.delivery_content})
            continue

        if is_cancelled(order):
            failed_count += 1
            results.append({"order_no": order_no, "ok": False, "msg": "订单已取消"})
            continue

        if not can_manual_confirm(order):
            failed_count += 1
            results.append({"order_no": order_no, "ok": False, "msg": f"状态不允许：payment_status={order.payment_status}, delivery_status={order.delivery_status}"})
            continue

        try:
            result = mark_paid_and_deliver(db, order)
            db.refresh(order)
            if norm(order.delivery_status) in {"processing", "delivered", "completed", "sent"}:
                get_or_create_renewal_task(db, order, "active" if is_delivered(order) else "processing")
            write_order_log(db, order, current_admin, "bulk_confirm_paid", before, "批量确认收款")
            db.commit()
            db.refresh(order)
            success_count += 1
            results.append({"order_no": order_no, "ok": True, "msg": "paid + delivered", "delivery_content": order.delivery_content, "result": result})
        except Exception as e:
            db.rollback()
            failed_count += 1
            results.append({"order_no": order_no, "ok": False, "msg": str(e)})

    return {"ok": failed_count == 0, "success_count": success_count, "failed_count": failed_count, "items": results}


@router.post("/orders/manual-complete")
def manual_complete_order(
    payload: ManualCompleteRequest,
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("orders:confirm")),
):
    order_no = (payload.order_no or "").strip()
    delivery_content = (payload.delivery_content or "").strip()

    if not order_no:
        raise HTTPException(status_code=400, detail="缺少订单号")
    if not delivery_content:
        raise HTTPException(status_code=400, detail="请填写代开通结果或完成说明")

    order = db.query(Order).filter(Order.order_no == order_no).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")

    before = status_snapshot(order)

    if is_cancelled(order):
        raise HTTPException(status_code=400, detail="订单已取消，不能完成")

    if is_delivered(order):
        write_order_log(db, order, current_admin, "manual_complete_skip_already_delivered", before, "重复提交完成，订单已完成")
        db.commit()
        return {"ok": True, "msg": "订单已完成，无需重复处理", "order_no": order.order_no, "delivery_content": order.delivery_content, "email_sent": False}

    order.payment_status = "paid"
    order.status = "completed"
    order.delivery_status = "delivered"
    order.delivery_content = delivery_content

    record = DeliveryRecord(order_id=order.id, status="delivered", content=delivery_content, created_at=datetime.utcnow())
    db.add(record)
    db.add(order)
    task = get_or_create_renewal_task(db, order, "active")
    task.due_at = datetime.utcnow() + timedelta(days=product_period_days(order.product_code, 30))
    task.notes = "订单已完成，进入续费/到期管理"
    write_order_log(db, order, current_admin, "manual_complete", before, "手动填写完成代开通")
    db.commit()
    db.refresh(order)

    email_sent = False
    email_error = None
    if payload.send_email and order.customer_email:
        try:
            send_delivery_email(target_email=order.customer_email, product_code=order.product_code, order_no=order.order_no, delivery_content=delivery_content)
            email_sent = True
        except Exception as e:
            email_error = str(e)

    return {"ok": True, "msg": "代开通订单已完成", "order_no": order.order_no, "delivery_content": order.delivery_content, "email_sent": email_sent, "email_error": email_error}


@router.post("/orders/cancel")
def cancel_order(
    payload: CancelOrderRequest,
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("orders:confirm")),
):
    order_no = (payload.order_no or "").strip()
    reason = (payload.reason or "管理员取消订单").strip() or "管理员取消订单"

    if not order_no:
        raise HTTPException(status_code=400, detail="缺少订单号")

    order = db.query(Order).filter(Order.order_no == order_no).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")

    before = status_snapshot(order)

    if is_delivered(order):
        raise HTTPException(status_code=400, detail="订单已完成，不能取消")

    if is_cancelled(order):
        write_order_log(db, order, current_admin, "cancel_order_skip_already_cancelled", before, "订单已取消，重复操作已跳过")
        db.commit()
        return {"ok": True, "order_no": order.order_no, "msg": "订单已取消"}

    try:
        order.status = "cancelled"
        order.payment_status = "cancelled"
        order.delivery_status = "cancelled"
        order.delivery_content = reason
        update_renewal_status_for_order(db, order, "cancelled", reason)
        write_order_log(db, order, current_admin, "cancel_order", before, reason)
        db.add(order)
        db.commit()
        db.refresh(order)
        return {"ok": True, "order_no": order.order_no, "msg": "订单已取消"}
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=400, detail=f"取消订单失败：{str(e)}")


@router.get("/renewals")
def list_renewals(
    status: str = "",
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("orders:read")),
):
    q = db.query(RenewalTask)
    if status:
        q = q.filter(RenewalTask.status == status)
    items = q.order_by(RenewalTask.due_at.asc()).limit(300).all()
    now = datetime.utcnow()
    return {"items": [{
        "id": i.id,
        "order_no": i.order_no,
        "product_code": i.product_code,
        "product_name": product_name(i.product_code),
        "customer_email": i.customer_email,
        "period_days": i.period_days,
        "due_at": str(i.due_at) if i.due_at else None,
        "days_left": (i.due_at - now).days if i.due_at else None,
        "status": i.status,
        "notes": i.notes,
        "created_at": str(i.created_at) if i.created_at else None,
        "updated_at": str(i.updated_at) if i.updated_at else None,
    } for i in items]}


@router.post("/renewals/{task_id}/mark-renewed")
def mark_renewed(
    task_id: int,
    payload: RenewalUpdateRequest | None = None,
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("orders:confirm")),
):
    task = db.query(RenewalTask).filter(RenewalTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="续费记录不存在")
    before = f"status={task.status};due_at={task.due_at}"
    base = task.due_at if task.due_at and task.due_at > datetime.utcnow() else datetime.utcnow()
    task.due_at = base + timedelta(days=int(task.period_days or 30))
    task.status = "active"
    task.notes = payload.notes if payload and payload.notes else "已标记续费，自动顺延到期时间"
    task.updated_at = datetime.utcnow()
    db.add(task)
    dummy_order = db.query(Order).filter(Order.order_no == task.order_no).first()
    write_order_log(db, dummy_order, current_admin, "renewal_mark_renewed", before, task.notes)
    db.commit()
    return {"ok": True, "item": {"id": task.id, "order_no": task.order_no, "due_at": str(task.due_at), "status": task.status}}


@router.post("/renewals/{task_id}/close")
def close_renewal(
    task_id: int,
    payload: RenewalUpdateRequest | None = None,
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("orders:confirm")),
):
    task = db.query(RenewalTask).filter(RenewalTask.id == task_id).first()
    if not task:
        raise HTTPException(status_code=404, detail="续费记录不存在")
    before = f"status={task.status};due_at={task.due_at}"
    task.status = "closed"
    task.notes = payload.notes if payload and payload.notes else "已关闭续费管理"
    task.updated_at = datetime.utcnow()
    db.add(task)
    dummy_order = db.query(Order).filter(Order.order_no == task.order_no).first()
    write_order_log(db, dummy_order, current_admin, "renewal_close", before, task.notes)
    db.commit()
    return {"ok": True, "item": {"id": task.id, "order_no": task.order_no, "status": task.status}}


@router.get("/order-logs")
def list_order_logs(
    order_no: str = "",
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("orders:read")),
):
    q = db.query(OrderLog)
    if order_no:
        q = q.filter(OrderLog.order_no == order_no)
    items = q.order_by(OrderLog.id.desc()).limit(300).all()
    return {"items": [{
        "id": i.id,
        "order_no": i.order_no,
        "admin_id": i.admin_id,
        "admin_name": i.admin_name,
        "action": i.action,
        "before_status": i.before_status,
        "after_status": i.after_status,
        "detail": i.detail,
        "created_at": str(i.created_at) if i.created_at else None,
    } for i in items]}


@router.get("/admins")
def list_admins(db: Session = Depends(get_db), current_admin: AdminUser = Depends(require_permission("admins:manage"))):
    admins = db.query(AdminUser).order_by(AdminUser.id.asc()).all()
    return {"items": [admin_to_dict(a) for a in admins]}


@router.post("/admins")
def create_admin(payload: CreateAdminRequest, db: Session = Depends(get_db), current_admin: AdminUser = Depends(require_permission("admins:manage"))):
    username = (payload.username or "").strip()
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="管理员账号至少 3 位")
    if db.query(AdminUser).filter(AdminUser.username == username).first():
        raise HTTPException(status_code=400, detail="管理员账号已存在")
    admin = AdminUser(username=username, password_hash=hash_password(payload.password), role=normalize_role(payload.role), is_active=1, created_at=datetime.utcnow())
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return {"ok": True, "admin": admin_to_dict(admin)}


@router.put("/admins/{admin_id}")
def update_admin(admin_id: int, payload: UpdateAdminRequest, db: Session = Depends(get_db), current_admin: AdminUser = Depends(require_permission("admins:manage"))):
    admin = db.query(AdminUser).filter(AdminUser.id == admin_id).first()
    if not admin:
        raise HTTPException(status_code=404, detail="管理员不存在")
    if admin.id == current_admin.id and payload.is_active is False:
        raise HTTPException(status_code=400, detail="不能禁用当前登录的管理员")
    if payload.password:
        admin.password_hash = hash_password(payload.password)
    if payload.role is not None:
        admin.role = normalize_role(payload.role)
    if payload.is_active is not None:
        admin.is_active = 1 if payload.is_active else 0
    db.commit()
    db.refresh(admin)
    return {"ok": True, "admin": admin_to_dict(admin)}
