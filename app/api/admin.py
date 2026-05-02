import traceback
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.admin_auth import admin_to_dict, normalize_role, require_permission
from app.core.db import get_db
from app.core.security import create_admin_token, hash_password, verify_password
from app.models.entities import AdminUser, DeliveryRecord, Order
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


class AutoManualCompleteRequest(BaseModel):
    order_no: str
    send_email: bool = True


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


def is_delivered(order: Order) -> bool:
    return norm(order.delivery_status) in {"delivered", "completed", "success", "sent"}


def can_manual_confirm(order: Order) -> bool:
    if is_delivered(order):
        return False
    return norm(order.payment_status) in {
        "waiting", "pending", "pending_payment", "unpaid", "paid", "finished", "confirmed", "", "none",
    }


def product_display_name(product_code: str) -> str:
    code = str(product_code or "").upper()
    if "GPT" in code or "CHATGPT" in code:
        return "ChatGPT Plus"
    if "CLAUDE" in code:
        return "Claude Pro"
    if "MJ" in code or "MIDJOURNEY" in code:
        return "Midjourney"
    if "GEMINI" in code:
        return "Gemini Advanced"
    if "PERPLEXITY" in code:
        return "Perplexity Pro"
    if "CURSOR" in code:
        return "Cursor Pro"
    return str(product_code or "会员服务")


def build_auto_delivery_content(order: Order) -> str:
    """
    一键自动发货的交付内容。
    业务规则：按中国用户常用时间显示，有效期从完成代开通当天起算 30 天，
    到期日当天 23:59 前有效，避免因为 UTC/美国时间造成“看起来不足 30 天”。
    """
    beijing_tz = ZoneInfo("Asia/Shanghai")
    now_cn = datetime.now(beijing_tz)
    expire_at = (now_cn + timedelta(days=30)).replace(
        hour=23, minute=59, second=0, microsecond=0
    )
    expire_text = expire_at.strftime("%Y-%m-%d %H:%M")
    product_name = product_display_name(order.product_code)
    return (
        f"已为您账号开通 {product_name}，有效期至 {expire_text}（北京时间）。"
        f"请登录原账号查看，如有问题请联系网站客服。"
    )


def complete_order_and_notify(
    db: Session,
    order: Order,
    delivery_content: str,
    send_email: bool = True,
) -> dict:
    order.payment_status = "paid"
    order.status = "completed"
    order.delivery_status = "delivered"
    order.delivery_content = delivery_content

    record = DeliveryRecord(
        order_id=order.id,
        status="delivered",
        content=delivery_content,
        created_at=datetime.utcnow(),
    )
    db.add(record)
    db.add(order)
    db.commit()
    db.refresh(order)

    email_sent = False
    email_error = None
    if send_email and order.customer_email:
        try:
            send_delivery_email(
                target_email=order.customer_email,
                product_code=order.product_code,
                order_no=order.order_no,
                delivery_content=delivery_content,
            )
            email_sent = True
        except Exception as e:
            email_error = str(e)

    return {
        "ok": True,
        "msg": "代开通订单已完成",
        "order_no": order.order_no,
        "delivery_content": order.delivery_content,
        "email_sent": email_sent,
        "email_error": email_error,
    }


def order_to_dict(o: Order):
    return {
        "id": o.id,
        "order_no": o.order_no,
        "product_code": o.product_code,
        "customer_email": o.customer_email,
        "payment_status": o.payment_status,
        "status": o.status,
        "delivery_status": o.delivery_status,
        "delivery_content": o.delivery_content,
        "payment_method": getattr(o, "payment_method", None),
        "created_at": str(o.created_at) if o.created_at else None,
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

    if is_delivered(order):
        return {"ok": True, "msg": "already delivered", "order_no": order.order_no, "delivery_content": order.delivery_content}

    if not can_manual_confirm(order):
        raise HTTPException(
            status_code=400,
            detail=f"当前状态不允许发货：payment_status={order.payment_status}, delivery_status={order.delivery_status}",
        )

    try:
        result = mark_paid_and_deliver(db, order)
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

        if is_delivered(order):
            success_count += 1
            results.append({"order_no": order_no, "ok": True, "msg": "已发货，跳过", "delivery_content": order.delivery_content})
            continue

        if not can_manual_confirm(order):
            failed_count += 1
            results.append({"order_no": order_no, "ok": False, "msg": f"状态不允许：payment_status={order.payment_status}, delivery_status={order.delivery_status}"})
            continue

        try:
            result = mark_paid_and_deliver(db, order)
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

    if is_delivered(order):
        return {
            "ok": True,
            "msg": "订单已完成，无需重复处理",
            "order_no": order.order_no,
            "delivery_content": order.delivery_content,
            "email_sent": False,
        }

    return complete_order_and_notify(
        db=db,
        order=order,
        delivery_content=delivery_content,
        send_email=payload.send_email,
    )


@router.post("/orders/manual-auto-complete")
def manual_auto_complete_order(
    payload: AutoManualCompleteRequest,
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("orders:confirm")),
):
    order_no = (payload.order_no or "").strip()
    if not order_no:
        raise HTTPException(status_code=400, detail="缺少订单号")

    order = db.query(Order).filter(Order.order_no == order_no).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")

    if is_delivered(order):
        return {
            "ok": True,
            "msg": "订单已完成，无需重复处理",
            "order_no": order.order_no,
            "delivery_content": order.delivery_content,
            "email_sent": False,
        }

    delivery_content = build_auto_delivery_content(order)
    return complete_order_and_notify(
        db=db,
        order=order,
        delivery_content=delivery_content,
        send_email=payload.send_email,
    )


@router.get("/admins")
def list_admins(
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("admins:manage")),
):
    admins = db.query(AdminUser).order_by(AdminUser.id.asc()).all()
    return {"items": [admin_to_dict(a) for a in admins]}


@router.post("/admins")
def create_admin(
    payload: CreateAdminRequest,
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("admins:manage")),
):
    username = (payload.username or "").strip()
    if len(username) < 3:
        raise HTTPException(status_code=400, detail="管理员账号至少 3 位")
    if db.query(AdminUser).filter(AdminUser.username == username).first():
        raise HTTPException(status_code=400, detail="管理员账号已存在")

    admin = AdminUser(
        username=username,
        password_hash=hash_password(payload.password),
        role=normalize_role(payload.role),
        is_active=1,
        created_at=datetime.utcnow(),
    )
    db.add(admin)
    db.commit()
    db.refresh(admin)
    return {"ok": True, "admin": admin_to_dict(admin)}


@router.put("/admins/{admin_id}")
def update_admin(
    admin_id: int,
    payload: UpdateAdminRequest,
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("admins:manage")),
):
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
