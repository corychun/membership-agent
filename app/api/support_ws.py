import json
from datetime import datetime
from typing import Dict, List

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from sqlalchemy.orm import Session

from app.core.db import SessionLocal
from app.core.admin_auth import get_admin_from_token, ROLE_PERMISSIONS
from app.models.entities import SupportSession, SupportMessage

router = APIRouter(tags=["support_ws"])


class ConnectionManager:
    def __init__(self):
        self.rooms: Dict[str, List[WebSocket]] = {}

    async def connect(self, session_no: str, websocket: WebSocket):
        await websocket.accept()
        self.rooms.setdefault(session_no, []).append(websocket)

    def disconnect(self, session_no: str, websocket: WebSocket):
        if session_no in self.rooms and websocket in self.rooms[session_no]:
            self.rooms[session_no].remove(websocket)

        if session_no in self.rooms and not self.rooms[session_no]:
            del self.rooms[session_no]

    async def broadcast(self, session_no: str, data: dict):
        sockets = list(self.rooms.get(session_no, []))

        for ws in sockets:
            try:
                await ws.send_text(json.dumps(data, ensure_ascii=False))
            except Exception:
                pass


manager = ConnectionManager()


def save_message(
    db: Session,
    session: SupportSession,
    sender_type: str,
    sender_name: str,
    content: str,
):
    msg = SupportMessage(
        session_id=session.id,
        sender_type=sender_type,
        sender_name=sender_name,
        content=content,
        is_read=0 if sender_type == "customer" else 1,
        created_at=datetime.utcnow(),
    )

    db.add(msg)
    session.last_message_at = datetime.utcnow()
    session.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(msg)

    return {
        "id": msg.id,
        "session_id": msg.session_id,
        "sender_type": msg.sender_type,
        "sender_name": msg.sender_name,
        "content": msg.content,
        "created_at": str(msg.created_at),
    }


@router.websocket("/ws/support/customer/{session_no}")
async def customer_support_ws(websocket: WebSocket, session_no: str):
    db = SessionLocal()

    try:
        session = db.query(SupportSession).filter(SupportSession.session_no == session_no).first()

        if not session:
            await websocket.accept()
            await websocket.send_text(json.dumps({"type": "error", "message": "客服会话不存在"}, ensure_ascii=False))
            await websocket.close()
            return

        await manager.connect(session_no, websocket)

        await websocket.send_text(json.dumps({
            "type": "connected",
            "role": "customer",
            "session_no": session_no,
        }, ensure_ascii=False))

        while True:
            raw = await websocket.receive_text()

            try:
                data = json.loads(raw)
            except Exception:
                data = {"content": raw}

            content = (data.get("content") or "").strip()

            if not content:
                continue

            session = db.query(SupportSession).filter(SupportSession.session_no == session_no).first()

            if not session or session.status == "closed":
                await websocket.send_text(json.dumps({"type": "error", "message": "会话已关闭"}, ensure_ascii=False))
                continue

            msg = save_message(
                db=db,
                session=session,
                sender_type="customer",
                sender_name=session.customer_email or "访客",
                content=content,
            )

            await manager.broadcast(session_no, {
                "type": "message",
                "message": msg,
            })

    except WebSocketDisconnect:
        manager.disconnect(session_no, websocket)

    finally:
        db.close()


@router.websocket("/ws/support/admin/{session_no}")
async def admin_support_ws(
    websocket: WebSocket,
    session_no: str,
    token: str = Query(...),
):
    db = SessionLocal()

    try:
        try:
            admin = get_admin_from_token(token, db)
        except Exception:
            await websocket.accept()
            await websocket.send_text(json.dumps({"type": "error", "message": "管理员登录已失效"}, ensure_ascii=False))
            await websocket.close()
            return

        perms = ROLE_PERMISSIONS.get(admin.role, [])

        if "support:reply" not in perms:
            await websocket.accept()
            await websocket.send_text(json.dumps({"type": "error", "message": "没有客服回复权限"}, ensure_ascii=False))
            await websocket.close()
            return

        session = db.query(SupportSession).filter(SupportSession.session_no == session_no).first()

        if not session:
            await websocket.accept()
            await websocket.send_text(json.dumps({"type": "error", "message": "客服会话不存在"}, ensure_ascii=False))
            await websocket.close()
            return

        await manager.connect(session_no, websocket)

        await websocket.send_text(json.dumps({
            "type": "connected",
            "role": "admin",
            "session_no": session_no,
            "admin": admin.username,
        }, ensure_ascii=False))

        while True:
            raw = await websocket.receive_text()

            try:
                data = json.loads(raw)
            except Exception:
                data = {"content": raw}

            content = (data.get("content") or "").strip()

            if not content:
                continue

            session = db.query(SupportSession).filter(SupportSession.session_no == session_no).first()

            if not session:
                await websocket.send_text(json.dumps({"type": "error", "message": "客服会话不存在"}, ensure_ascii=False))
                continue

            if session.status == "closed":
                await websocket.send_text(json.dumps({"type": "error", "message": "会话已关闭"}, ensure_ascii=False))
                continue

            session.assigned_admin_id = admin.id

            msg = save_message(
                db=db,
                session=session,
                sender_type="admin",
                sender_name=admin.username,
                content=content,
            )

            await manager.broadcast(session_no, {
                "type": "message",
                "message": msg,
            })

    except WebSocketDisconnect:
        manager.disconnect(session_no, websocket)

    finally:
        db.close()