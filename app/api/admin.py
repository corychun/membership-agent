import traceback
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.admin_auth import admin_to_dict, normalize_role, require_permission
from app.core.db import get_db
from app.core.products import product_name, product_period_days, product_price_cny
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
    for name in names:
        try:
            value = getattr(order, name, None)
        except Exception:
            value = None
        if value is not None and value != "":
            return value
    return default


def normalize_payment_method_label(value) -> str:
    raw = str(value or "").strip()
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

def order_to_dict(o: Order):
    renewal = None
    try:
        # 这里不额外查询，列表接口会批量填充，保留空值兼容。
        pass
    except Exception:
        renewal = None
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
        "payment_method": safe_order_attr(o, "payment_method", "pay_method", "payment_provider", "provider", "checkout_provider", "pay_channel"),
        "payment_method_label": normalize_payment_method_label(safe_order_attr(o, "payment_method", "pay_method", "payment_provider", "provider", "checkout_provider", "pay_channel")),
        "payment_amount": safe_order_attr(o, "payment_amount", "pay_amount", "paid_amount", "amount", "total_amount", "amount_usdt", "price_usdt", "product_price_usdt"),
        "payment_currency": safe_order_attr(o, "payment_currency", "currency", "pay_currency", default="USDT"),
        "payment_amount_text": format_amount_value(
            safe_order_attr(o, "payment_amount", "pay_amount", "paid_amount", "amount", "total_amount", "amount_usdt", "price_usdt", "product_price_usdt"),
            safe_order_attr(o, "payment_currency", "currency", "pay_currency", default="USDT"),
        ),
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
    return {"items": [order_to_dict(o) for o in orders]}


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
    order = db.query(Order).filter(Order.order_no == order_no).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")

    before = status_snapshot(order)
    if is_delivered(order):
        raise HTTPException(status_code=400, detail="订单已完成，不能取消")

    order.status = "cancelled"
    order.payment_status = "cancelled"
    order.delivery_status = "cancelled"
    if not order.delivery_content:
        order.delivery_content = payload.reason or "管理员取消订单"
    update_renewal_status_for_order(db, order, "cancelled", payload.reason)
    write_order_log(db, order, current_admin, "cancel_order", before, payload.reason or "管理员取消订单")
    db.add(order)
    db.commit()
    return {"ok": True, "order_no": order.order_no, "msg": "订单已取消"}


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
