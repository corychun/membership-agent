import base64
from datetime import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.admin_auth import require_permission
from app.core.db import get_db
from app.models.entities import AdminUser, SupportMessage, SupportSession

router = APIRouter(tags=["support"])

UPLOAD_DIR = Path("app/static/uploads/support")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


class CreateSession(BaseModel):
    customer_email: Optional[str] = None
    order_no: Optional[str] = None
    first_message: str


class SendMessage(BaseModel):
    content: Optional[str] = None
    image_base64: Optional[str] = None


class AdminReplyRequest(BaseModel):
    content: str


class CloseSessionRequest(BaseModel):
    status: str = "closed"


def _now() -> datetime:
    return datetime.utcnow()


def _session_no() -> str:
    return f"S{int(_now().timestamp() * 1000)}"


def _save_base64_image(value: str) -> str:
    raw = (value or "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="图片内容为空")

    if raw.startswith("[img]"):
        raw = raw.replace("[img]", "", 1)

    try:
        data_part = raw.split(",", 1)[1] if "," in raw else raw
        img_data = base64.b64decode(data_part)
    except Exception:
        raise HTTPException(status_code=400, detail="图片格式错误")

    if len(img_data) > 5 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="图片不能超过 5MB")

    filename = f"support_{int(_now().timestamp() * 1000)}.png"
    path = UPLOAD_DIR / filename
    with open(path, "wb") as f:
        f.write(img_data)
    return f"/static/uploads/support/{filename}"


def _message_to_dict(m: SupportMessage) -> dict:
    return {
        "id": m.id,
        "sender_type": m.sender_type,
        "sender_name": m.sender_name,
        "content": m.content,
        "is_read": int(m.is_read or 0),
        "created_at": str(m.created_at) if m.created_at else None,
    }


def _last_message(db: Session, session_id: int) -> SupportMessage | None:
    return (
        db.query(SupportMessage)
        .filter(SupportMessage.session_id == session_id)
        .order_by(SupportMessage.id.desc())
        .first()
    )


def _unread_customer_count(db: Session, session_id: int) -> int:
    return (
        db.query(SupportMessage)
        .filter(
            SupportMessage.session_id == session_id,
            SupportMessage.sender_type == "customer",
            SupportMessage.is_read == 0,
        )
        .count()
    )


def _session_to_dict(db: Session, s: SupportSession) -> dict:
    last = _last_message(db, s.id)
    return {
        "id": s.id,
        "session_no": s.session_no,
        "customer_email": s.customer_email,
        "order_no": s.order_no,
        "status": s.status,
        "unread_count": _unread_customer_count(db, s.id),
        "last_message": last.content if last else "",
        "last_sender_type": last.sender_type if last else "",
        "created_at": str(s.created_at) if s.created_at else None,
        "updated_at": str(s.updated_at) if s.updated_at else None,
        "last_message_at": str(s.last_message_at) if s.last_message_at else None,
    }


def _append_message(
    db: Session,
    session: SupportSession,
    sender_type: str,
    content: str,
    sender_name: str | None = None,
    is_read: int = 0,
) -> SupportMessage:
    value = (content or "").strip()
    if not value:
        raise HTTPException(status_code=400, detail="消息内容不能为空")

    msg = SupportMessage(
        session_id=session.id,
        sender_type=sender_type,
        sender_name=sender_name,
        content=value,
        is_read=is_read,
        created_at=_now(),
    )
    session.updated_at = _now()
    session.last_message_at = _now()
    db.add(msg)
    db.add(session)
    db.commit()
    db.refresh(msg)
    db.refresh(session)
    return msg


@router.post("/support/sessions")
def create_session(data: CreateSession, db: Session = Depends(get_db)):
    first = (data.first_message or "").strip()
    if not first:
        raise HTTPException(status_code=400, detail="请输入咨询内容")

    session = SupportSession(
        session_no=_session_no(),
        customer_email=(data.customer_email or "").strip() or None,
        order_no=(data.order_no or "").strip() or None,
        status="open",
        created_at=_now(),
        updated_at=_now(),
        last_message_at=_now(),
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    _append_message(db, session, "customer", first, sender_name="客户", is_read=0)
    return {"ok": True, "session": _session_to_dict(db, session)}


@router.get("/support/sessions/{session_no}/messages")
def get_public_messages(session_no: str, db: Session = Depends(get_db)):
    session = db.query(SupportSession).filter(SupportSession.session_no == session_no).first()
    if not session:
        raise HTTPException(status_code=404, detail="客服会话不存在")

    messages = (
        db.query(SupportMessage)
        .filter(SupportMessage.session_id == session.id)
        .order_by(SupportMessage.id.asc())
        .all()
    )

    # 客户打开聊天时，将客服回复标记为已读。
    changed = False
    for m in messages:
        if m.sender_type == "admin" and int(m.is_read or 0) == 0:
            m.is_read = 1
            db.add(m)
            changed = True
    if changed:
        db.commit()

    return {"ok": True, "session": _session_to_dict(db, session), "items": [_message_to_dict(m) for m in messages]}


@router.post("/support/send/{session_no}")
def send_customer_message(session_no: str, data: SendMessage, db: Session = Depends(get_db)):
    session = db.query(SupportSession).filter(SupportSession.session_no == session_no).first()
    if not session:
        raise HTTPException(status_code=404, detail="客服会话不存在")
    if session.status == "closed":
        session.status = "open"

    content = (data.content or "").strip()
    if data.image_base64:
        content = "[img]" + _save_base64_image(data.image_base64)
    elif content.startswith("[img]data:image"):
        content = "[img]" + _save_base64_image(content)

    msg = _append_message(db, session, "customer", content, sender_name="客户", is_read=0)
    return {"ok": True, "message": _message_to_dict(msg), "session": _session_to_dict(db, session)}


@router.get("/support/admin/sessions")
def admin_list_sessions(
    status: str = "",
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("orders:read")),
):
    q = db.query(SupportSession)
    if status:
        q = q.filter(SupportSession.status == status)
    sessions = q.order_by(SupportSession.last_message_at.desc(), SupportSession.id.desc()).limit(300).all()
    return {"ok": True, "items": [_session_to_dict(db, s) for s in sessions]}


@router.get("/support/admin/sessions/{session_no}/messages")
def admin_get_messages(
    session_no: str,
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("orders:read")),
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

    changed = False
    for m in messages:
        if m.sender_type == "customer" and int(m.is_read or 0) == 0:
            m.is_read = 1
            db.add(m)
            changed = True
    if changed:
        db.commit()

    return {"ok": True, "session": _session_to_dict(db, session), "items": [_message_to_dict(m) for m in messages]}


@router.post("/support/admin/sessions/{session_no}/reply")
def admin_reply(
    session_no: str,
    data: AdminReplyRequest,
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("orders:read")),
):
    session = db.query(SupportSession).filter(SupportSession.session_no == session_no).first()
    if not session:
        raise HTTPException(status_code=404, detail="客服会话不存在")
    if session.status == "closed":
        session.status = "open"

    msg = _append_message(
        db,
        session,
        "admin",
        data.content,
        sender_name=current_admin.username,
        is_read=0,
    )
    return {"ok": True, "message": _message_to_dict(msg), "session": _session_to_dict(db, session)}


@router.post("/support/admin/sessions/{session_no}/close")
def admin_close_session(
    session_no: str,
    data: CloseSessionRequest | None = None,
    db: Session = Depends(get_db),
    current_admin: AdminUser = Depends(require_permission("orders:read")),
):
    session = db.query(SupportSession).filter(SupportSession.session_no == session_no).first()
    if not session:
        raise HTTPException(status_code=404, detail="客服会话不存在")

    session.status = (data.status if data else "closed") or "closed"
    session.updated_at = _now()
    db.add(session)
    db.commit()
    db.refresh(session)
    return {"ok": True, "session": _session_to_dict(db, session)}
