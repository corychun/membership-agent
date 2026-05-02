from __future__ import annotations

from datetime import datetime, timedelta
from html import escape
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.admin_auth import (
    admin_to_dict,
    normalize_role,
    require_permission,
)
from app.core.db import get_db
from app.core.security import create_admin_token, hash_password, verify_password
from app.models.entities import AdminUser, DeliveryRecord, Order
from app.services.delivery import deliver_order, is_activation_product
from app.services.email_service import send_email, send_delivery_email

router = APIRouter(prefix="/admin", tags=["admin"])


# =========================
# 商品名称映射：只用于后台邮件展示，不影响前端 UI
# =========================
PRODUCT_NAME = {
    "GPT_PLUS_1M": "ChatGPT Plus 独享账号",
    "GPT_ACTIVATE_1M": "ChatGPT Plus 代开通",
    "GPT_PLUS_3M": "ChatGPT Plus 独享季卡",
    "GPT_TEAM_1M": "ChatGPT Team 席位",
    "CLAUDE_PRO_1M": "Claude Pro 独享账号",
    "CLAUDE_ACTIVATE_1M": "Claude Pro 代开通",
    "CLAUDE_PRO_3M": "Claude Pro 独享季卡",
    "MJ_BASIC_1M": "Midjourney Basic",
    "MJ_STANDARD_1M": "Midjourney Standard",
    "MJ_PRO_1M": "Midjourney Pro",
    "GEMINI_PRO_1M": "Gemini Advanced",
    "PERPLEXITY_PRO_1M": "Perplexity Pro",
    "CURSOR_PRO_1M": "Cursor Pro",
    "AI_BUNDLE_1M": "AI全家桶月卡",
}


# =========================
# 请求模型
# =========================
class LoginRequest(BaseModel):
    username: str
    password: str


class ConfirmPaidRequest(BaseModel):
    order_no: str


class ConfirmPaidBulkRequest(BaseModel):
    order_nos: list[str]


class ManualCompleteRequest(BaseModel):
    order_no: str
    delivery_content: str
    send_email: bool = True


class ManualAutoCompleteRequest(BaseModel):
    order_no: str
    send_email: bool = True


class CancelOrderRequest(BaseModel):
    order_no: str
    reason: Optional[str] = None


class CreateAdminRequest(BaseModel):
    username: str
    password: str
    role: str = "support"


class UpdateAdminRequest(BaseModel):
    password: Optional[str] = None
    role: Optional[str] = None
    is_active: Optional[bool] = None


# =========================
# 通用工具
# =========================
def _product_name(product_code: str | None) -> str:
    code = str(product_code or "").upper().strip()
    return PRODUCT_NAME.get(code, code or "-")


def _get_order_or_404(db: Session, order_no: str) -> Order:
    order_no = str(order_no or "").strip()
    if not order_no:
        raise HTTPException(status_code=400, detail="缺少订单号")

    order = db.query(Order).filter(Order.order_no == order_no).first()
    if not order:
        raise HTTPException(status_code=404, detail="订单不存在")
    return order


def _order_to_dict(order: Order):
    return {
        "id": order.id,
        "order_no": order.order_no,
        "customer_email": order.customer_email,
        "product_code": order.product_code,
        "payment_method": getattr(order, "payment_method", None),
        "status": order.status,
        "payment_status": order.payment_status,
        "delivery_status": order.delivery_status,
        "delivery_content": order.delivery_content,
        "created_at": str(order.created_at) if order.created_at else None,
        "can_confirm": _can_confirm(order),
    }


def _is_finished(order: Order) -> bool:
    return str(order.delivery_status or "").lower() in {
        "delivered",
        "completed",
        "success",
        "sent",
    } or str(order.status or "").lower() in {"cancelled", "canceled"}


def _can_confirm(order: Order) -> bool:
    if _is_finished(order):
        return False
    return str(order.payment_status or "").lower() not in {"paid", "finished", "confirmed", "success"}


def _create_delivery_record_safe(db: Session, order: Order, content: str, status_value: str) -> None:
    try:
        mapper_cols = DeliveryRecord.__mapper__.columns.keys()
        kwargs = {}
        if "order_id" in mapper_cols:
            kwargs["order_id"] = order.id
        if "status" in mapper_cols:
            kwargs["status"] = status_value
        if "content" in mapper_cols:
            kwargs["content"] = content
        if "created_at" in mapper_cols:
            kwargs["created_at"] = datetime.utcnow()
        if kwargs:
            db.add(DeliveryRecord(**kwargs))
    except Exception:
        # 操作日志失败不能影响主流程
        pass


def _send_processing_email(order: Order) -> tuple[bool, Optional[str], Optional[dict]]:
    """确认收款后发送“处理中”邮件，避免客户误以为已完成。"""
    if not order.customer_email:
        return False, "订单没有客户邮箱", None

    product_name = _product_name(order.product_code)
    subject = f"您的订单正在处理中：{order.order_no}"

    text_body = (
        f"您好，您的订单已成功支付，我们已收到款项。\n\n"
        f"订单号：{order.order_no}\n"
        f"产品套餐：{product_name}\n"
        f"当前状态：正在处理中\n\n"
        f"我们正在为您进行开通操作，请耐心等待，一般会在短时间内完成。\n"
        f"如超过30分钟未完成，请联系客服处理。\n\n"
        f"开通完成后，您将收到新的完成通知邮件。\n\n"
        f"感谢您的支持。"
    )

    html_body = f"""
    <html>
      <body style="font-family: Arial, sans-serif; color: #111827; line-height: 1.7;">
        <div style="max-width: 640px; margin: 0 auto; padding: 24px; border: 1px solid #e5e7eb; border-radius: 12px;">
          <h2 style="margin-top: 0; color: #111827;">您的订单正在处理中</h2>
          <p>您好，您的订单已成功支付，我们已收到款项。</p>
          <p><strong>订单号：</strong>{escape(order.order_no or "-")}</p>
          <p><strong>产品套餐：</strong>{escape(product_name)}</p>
          <p><strong>当前状态：</strong>正在处理中</p>
          <div style="white-space: pre-wrap; background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 14px;">
我们正在为您进行开通操作，请耐心等待，一般会在短时间内完成。<br><strong style="color:#b91c1c;">如超过30分钟未完成，请联系客服处理。</strong>
          </div>
          <p>开通完成后，您将收到新的完成通知邮件。</p>
          <p style="color: #6b7280; font-size: 13px; margin-top: 20px;">感谢您的支持。</p>
        </div>
      </body>
    </html>
    """

    try:
        result = send_email(
            to_email=order.customer_email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
        )
        return True, None, result
    except Exception as e:
        return False, str(e), None


def _beijing_expire_text(days: int = 30) -> str:
    """按北京时间计算：完成当天起算，满 30 天，到期日 23:59。"""
    bj_now = datetime.utcnow() + timedelta(hours=8)
    expire_day = (bj_now + timedelta(days=days)).date()
    return f"{expire_day.strftime('%Y-%m-%d')} 23:59（北京时间）"


def _auto_delivery_content(order: Order) -> str:
    product_name = _product_name(order.product_code)
    expire_text = _beijing_expire_text(30)

    if "CLAUDE" in str(order.product_code or "").upper():
        service_name = "Claude Pro"
    elif "GPT" in str(order.product_code or "").upper() or "CHATGPT" in product_name.upper():
        service_name = "ChatGPT Plus"
    else:
        service_name = product_name

    return (
        f"已为您账号开通 {service_name}，有效期至 {expire_text}。"
        f"请登录原账号查看，如有问题请联系客服。"
    )


def _manual_complete_order(
    db: Session,
    order: Order,
    delivery_content: str,
    send_email_flag: bool,
):
    content = str(delivery_content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="请填写交付内容")

    order.payment_status = "paid"
    order.status = "completed"
    order.delivery_status = "delivered"
    order.delivery_content = content

    _create_delivery_record_safe(db, order, content, "delivered")

    db.add(order)
    db.commit()
    db.refresh(order)

    email_sent = False
    email_error = None
    email_result = None

    if send_email_flag and order.customer_email:
        try:
            email_result = send_delivery_email(
                target_email=order.customer_email,
                product_code=order.product_code,
                order_no=order.order_no,
                delivery_content=content,
            )
            email_sent = True
        except Exception as e:
            email_error = str(e)

    return {
        "ok": True,
        "order_no": order.order_no,
        "delivery_content": content,
        "email_sent": email_sent,
        "email_error": email_error,
        "email_result": email_result,
    }


# =========================
# 登录 / 当前管理员
# =========================
@router.post("/login")
def login(data: LoginRequest, db: Session = Depends(get_db)):
    username = data.username.strip()
    password = data.password

    admin = db.query(AdminUser).filter(AdminUser.username == username).first()

    if not admin or not verify_password(password, admin.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号或密码错误")

    if int(admin.is_active or 0) != 1:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="管理员已被禁用")

    admin.last_login_at = datetime.utcnow()
    db.add(admin)
    db.commit()
    db.refresh(admin)

    token = create_admin_token({"sub": admin.id, "username": admin.username, "role": admin.role})

    return {
        "access_token": token,
        "token_type": "bearer",
        "admin": admin_to_dict(admin),
    }


@router.get("/me")
def me(admin: AdminUser = Depends(require_permission("orders:read"))):
    return {"admin": admin_to_dict(admin)}


# =========================
# 订单管理
# =========================
@router.get("/orders")
def list_orders(
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_permission("orders:read")),
):
    orders = db.query(Order).order_by(Order.id.desc()).all()
    return {"items": [_order_to_dict(o) for o in orders]}


@router.post("/orders/confirm-paid")
def confirm_paid(
    data: ConfirmPaidRequest,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_permission("orders:confirm")),
):
    order = _get_order_or_404(db, data.order_no)

    if str(order.status or "").lower() in {"cancelled", "canceled"}:
        raise HTTPException(status_code=400, detail="订单已取消，不能确认收款")

    # 代开通订单：只进入 processing，并发送“处理中”邮件，不发送“已完成”邮件。
    if is_activation_product(order.product_code):
        content = "已确认收款，订单已进入代开通流程。请等待处理完成通知。"
        order.payment_status = "paid"
        order.status = "paid"
        order.delivery_status = "processing"
        order.delivery_content = content

        _create_delivery_record_safe(db, order, content, "processing")
        db.add(order)
        db.commit()
        db.refresh(order)

        email_sent, email_error, email_result = _send_processing_email(order)

        return {
            "ok": True,
            "activation_order": True,
            "queued": True,
            "order_no": order.order_no,
            "content": content,
            "email_sent": email_sent,
            "email_error": email_error,
            "email_result": email_result,
        }

    # 库存/卡密订单：确认收款后继续走原来的发货逻辑。
    order.payment_status = "paid"
    order.status = "paid"
    db.add(order)
    db.commit()
    db.refresh(order)

    try:
        result = deliver_order(db, order)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"ok": True, "order_no": order.order_no, **result}


@router.post("/orders/confirm-paid-bulk")
def confirm_paid_bulk(
    data: ConfirmPaidBulkRequest,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_permission("orders:confirm")),
):
    success_count = 0
    failed_count = 0
    results = []

    for order_no in data.order_nos:
        try:
            result = confirm_paid(ConfirmPaidRequest(order_no=order_no), db=db, admin=admin)
            success_count += 1
            results.append({"order_no": order_no, "ok": True, "result": result})
        except Exception as e:
            failed_count += 1
            detail = getattr(e, "detail", str(e))
            results.append({"order_no": order_no, "ok": False, "error": detail})
            db.rollback()

    return {
        "success_count": success_count,
        "failed_count": failed_count,
        "results": results,
    }


@router.post("/orders/manual-complete")
def manual_complete(
    data: ManualCompleteRequest,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_permission("orders:confirm")),
):
    order = _get_order_or_404(db, data.order_no)
    if str(order.status or "").lower() in {"cancelled", "canceled"}:
        raise HTTPException(status_code=400, detail="订单已取消，不能完成代开通")
    return _manual_complete_order(db, order, data.delivery_content, data.send_email)


@router.post("/orders/manual-auto-complete")
def manual_auto_complete(
    data: ManualAutoCompleteRequest,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_permission("orders:confirm")),
):
    order = _get_order_or_404(db, data.order_no)
    if str(order.status or "").lower() in {"cancelled", "canceled"}:
        raise HTTPException(status_code=400, detail="订单已取消，不能一键完成")
    content = _auto_delivery_content(order)
    return _manual_complete_order(db, order, content, data.send_email)


@router.post("/orders/cancel")
def cancel_order(
    data: CancelOrderRequest,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_permission("orders:confirm")),
):
    order = _get_order_or_404(db, data.order_no)

    if _is_finished(order) and str(order.status or "").lower() not in {"cancelled", "canceled"}:
        raise HTTPException(status_code=400, detail="已完成订单不能取消")

    reason = str(data.reason or "客户误下单，后台已取消。").strip()
    order.status = "cancelled"
    order.delivery_status = "cancelled"
    order.delivery_content = reason

    # 未付款订单保持 pending；已付款订单保持 paid，方便后续人工退款核对。
    if str(order.payment_status or "").lower() not in {"paid", "finished", "confirmed", "success"}:
        order.payment_status = "cancelled"

    _create_delivery_record_safe(db, order, reason, "cancelled")

    db.add(order)
    db.commit()
    db.refresh(order)

    return {"ok": True, "order_no": order.order_no, "message": "订单已取消"}


# 兼容之前误发版本里的旧接口路径，不影响当前后台页面。
@router.post("/confirm-payment/{order_no}")
def confirm_payment_legacy(
    order_no: str,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_permission("orders:confirm")),
):
    return confirm_paid(ConfirmPaidRequest(order_no=order_no), db=db, admin=admin)


@router.post("/complete-order/{order_no}")
def complete_order_legacy(
    order_no: str,
    data: ManualCompleteRequest,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_permission("orders:confirm")),
):
    order = _get_order_or_404(db, order_no)
    return _manual_complete_order(db, order, data.delivery_content, data.send_email)


# =========================
# 多管理员系统
# =========================
@router.get("/admins")
def list_admins(
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_permission("admins:manage")),
):
    admins = db.query(AdminUser).order_by(AdminUser.id.asc()).all()
    return {"items": [admin_to_dict(a) for a in admins]}


@router.post("/admins")
def create_admin(
    data: CreateAdminRequest,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_permission("admins:manage")),
):
    username = data.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="请输入管理员账号")

    exists = db.query(AdminUser).filter(AdminUser.username == username).first()
    if exists:
        raise HTTPException(status_code=400, detail="管理员账号已存在")

    role = normalize_role(data.role)

    new_admin = AdminUser(
        username=username,
        password_hash=hash_password(data.password),
        role=role,
        is_active=1,
        created_at=datetime.utcnow(),
    )
    db.add(new_admin)
    db.commit()
    db.refresh(new_admin)

    return {"ok": True, "admin": admin_to_dict(new_admin)}


@router.put("/admins/{admin_id}")
def update_admin(
    admin_id: int,
    data: UpdateAdminRequest,
    db: Session = Depends(get_db),
    admin: AdminUser = Depends(require_permission("admins:manage")),
):
    target = db.query(AdminUser).filter(AdminUser.id == admin_id).first()
    if not target:
        raise HTTPException(status_code=404, detail="管理员不存在")

    if data.role is not None:
        target.role = normalize_role(data.role)

    if data.password:
        target.password_hash = hash_password(data.password)

    if data.is_active is not None:
        if target.id == admin.id and data.is_active is False:
            raise HTTPException(status_code=400, detail="不能禁用当前登录管理员")
        target.is_active = 1 if data.is_active else 0

    db.add(target)
    db.commit()
    db.refresh(target)

    return {"ok": True, "admin": admin_to_dict(target)}
