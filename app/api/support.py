# app/api/support.py

import os
import base64
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime
from pathlib import Path

router = APIRouter()

UPLOAD_DIR = Path("app/static/uploads/support")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

MESSAGES = []
SESSIONS = {}

class CreateSession(BaseModel):
    customer_email: str | None = None
    order_no: str | None = None
    first_message: str

class SendMessage(BaseModel):
    content: str | None = None
    image_base64: str | None = None


def save_image(base64_str):
    img_data = base64.b64decode(base64_str.split(",")[-1])
    filename = f"{int(datetime.utcnow().timestamp()*1000)}.png"
    path = UPLOAD_DIR / filename
    with open(path, "wb") as f:
        f.write(img_data)
    return f"/static/uploads/support/{filename}"


@router.post("/support/sessions")
def create_session(data: CreateSession):
    session_no = f"S{int(datetime.utcnow().timestamp())}"
    SESSIONS[session_no] = {
        "session_no": session_no,
        "customer_email": data.customer_email,
        "order_no": data.order_no,
        "status": "open",
        "unread_count": 1
    }

    MESSAGES.append({
        "session_no": session_no,
        "sender_type": "customer",
        "content": data.first_message,
        "created_at": datetime.utcnow(),
        "read": False
    })

    return {"session": SESSIONS[session_no]}


@router.get("/support/admin/sessions")
def list_sessions():
    return {"items": list(SESSIONS.values())}


@router.get("/support/sessions/{session_no}/messages")
def get_messages(session_no: str):
    msgs = [m for m in MESSAGES if m["session_no"] == session_no]

    # 标记已读
    for m in msgs:
        if m["sender_type"] == "customer":
            m["read"] = True

    SESSIONS[session_no]["unread_count"] = 0

    return {"items": msgs}


@router.post("/support/send/{session_no}")
def send_message(session_no: str, data: SendMessage):
    if session_no not in SESSIONS:
        raise HTTPException(404, "session not found")

    content = data.content

    if data.image_base64:
        img_url = save_image(data.image_base64)
        content = f"[img]{img_url}"

    msg = {
        "session_no": session_no,
        "sender_type": "customer",
        "content": content,
        "created_at": datetime.utcnow(),
        "read": False
    }

    MESSAGES.append(msg)
    SESSIONS[session_no]["unread_count"] += 1

    return {"ok": True}
