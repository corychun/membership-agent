import uuid
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.admin_auth import require_permission
from app.models.entities import AdminUser, SupportSession, SupportMessage

router = APIRouter(prefix="/support", tags=["support"])


class CreateSupportSessionRequest(BaseModel):
    customer_email: Optional[EmailStr] = None
    order_no: Optional[str] = None
    first_message: str


class SendCustomerMessageRequest(BaseModel):
    content: str


class CloseSessionRequest(BaseModel):
    session_no: str


def session_to_dict(s: SupportSession, unread_count: int = 0):
    return {
        "id": s.id,
        "session_no": s.session_no,
        "customer_email": s.customer_email,
        "order_no": s.order_no,
        "status": s.status,
        "assigned_admin_id": s.assigned_admin_id,
        "created_at": str(s.created_at) if s.created_at else None,
        "updated_at": str(s.updated_at) if s.updated_at else None,
        "last_message_at": str(s.last_message_at) if s.last_message_at else None,
        "unread_count": unread_count,
    }


def message_to_dict(m: SupportMessage):
    return {
        "id": m.id,
        "session_id": m.session_id,
        "sender_type": m.sender_type,
        "sender_name": m.sender_name,
        "content": m.content,
        "is_read": bool(m.is_read),
        "created_at": str(m.created_at) if m.created_at else None,
    }


@router.post("/sessions")
def create_support_session(
    payload: CreateSupportSessionRequest,
    db: Session = Depends(get_db),
):
    if not payload.first_message or not payload.first_message.strip():
        raise HTTPException(status_code=400, detail="请输入咨询内容")

    session = SupportSession(
        session_no="CS-" + uuid.uuid4().hex[:12].upper(),
        customer_email=str(payload.customer_email) if payload.customer_email else None,
        order_no=(payload.order_no or "").strip() or None,
        status="open",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
        last_message_at=datetime.utcnow(),
    )

    db.add(session)
    db.commit()
    db.refresh(session)

    msg = SupportMessage(
        session_id=session.id,
        sender_type="customer",
        sender_name=session.customer_email or "访客",
        content=payload.first_message.strip(),
        is_read=0,
        created_at=datetime.utcnow(),
    )

    db.add(msg)
    session.last_message_at = datetime.utcnow()
    session.updated_at = datetime.utcnow()
    db.commit()

    return {
        "ok": True,
        "session": session_to_dict(session),
    }


@router.get("/sessions/{session_no}/messages")
def get_public_messages(
    session_no: str,
    db: Session = Depends(get_db),
):
    session = db.query(SupportSession).filter(SupportSession.session_no == session_no).first()

    if not session:
        raise HTTPException(status_code=404, detail="客服会话不存在")

    messages = (
        db.query(SupportMessage)
        .filter(SupportMessage.session_id == session.id)
        .order_by(SupportMessage.id.asc())
        .all()
    )

    return {
        "ok": True,
        "session": session_to_dict(session),
        "items": [message_to_dict(m) for m in messages],
    }


@router.post("/sessions/{session_no}/messages")
def send_customer_message(
    session_no: str,
    payload: SendCustomerMessageRequest,
    db: Session = Depends(get_db),
):
    session = db.query(SupportSession).filter(SupportSession.session_no == session_no).first()

    if not session:
        raise HTTPException(status_code=404, detail="客服会话不存在")

    if session.status == "closed":
        raise HTTPException(status_code=400, detail="该会话已关闭")

    if not payload.content or not payload.content.strip():
        raise HTTPException(status_code=400, detail="消息不能为空")

    msg = SupportMessage(
        session_id=session.id,
        sender_type="customer",
        sender_name=session.customer_email or "访客",
        content=payload.content.strip(),
        is_read=0,
        created_at=datetime.utcnow(),
    )

    db.add(msg)
    session.last_message_at = datetime.utcnow()
    session.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(msg)

    return {
        "ok": True,
        "message": message_to_dict(msg),
    }


@router.get("/admin/sessions")
def admin_list_sessions(
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("support:read")),
):
    sessions = (
        db.query(SupportSession)
        .order_by(SupportSession.last_message_at.desc(), SupportSession.id.desc())
        .limit(200)
        .all()
    )

    result = []

    for s in sessions:
        unread_count = (
            db.query(SupportMessage)
            .filter(
                SupportMessage.session_id == s.id,
                SupportMessage.sender_type == "customer",
                SupportMessage.is_read == 0,
            )
            .count()
        )
        result.append(session_to_dict(s, unread_count=unread_count))

    return {
        "ok": True,
        "items": result,
    }


@router.get("/admin/sessions/{session_no}/messages")
def admin_get_messages(
    session_no: str,
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("support:read")),
):
    session = db.query(SupportSession).filter(SupportSession.session_no == session_no).first()

    if not session:
        raise HTTPException(status_code=404, detail="客服会话不存在")

    messages = (
        db.query(SupportMessage)
        .filter(SupportMessage.session_id == session.id)
        .order_by(SupportMessage.id.asc())
        .all()
    )

    for m in messages:
        if m.sender_type == "customer":
            m.is_read = 1

    db.commit()

    return {
        "ok": True,
        "session": session_to_dict(session),
        "items": [message_to_dict(m) for m in messages],
    }


@router.post("/admin/sessions/{session_no}/close")
def admin_close_session(
    session_no: str,
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("support:close")),
):
    session = db.query(SupportSession).filter(SupportSession.session_no == session_no).first()

    if not session:
        raise HTTPException(status_code=404, detail="客服会话不存在")

    session.status = "closed"
    session.updated_at = datetime.utcnow()

    msg = SupportMessage(
        session_id=session.id,
        sender_type="system",
        sender_name="系统",
        content=f"会话已由 {current_admin.username} 关闭",
        is_read=0,
        created_at=datetime.utcnow(),
    )

    db.add(msg)
    db.commit()

    return {
        "ok": True,
        "session": session_to_dict(session),
    }