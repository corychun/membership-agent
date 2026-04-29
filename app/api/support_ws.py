# app/api/support_ws.py

from fastapi import WebSocket, APIRouter
import json

router = APIRouter()

connections = {}

@router.websocket("/ws/support/customer/{session_no}")
async def customer_ws(ws: WebSocket, session_no: str):
    await ws.accept()
    connections.setdefault(session_no, []).append(ws)

    try:
        while True:
            data = await ws.receive_text()
            for conn in connections[session_no]:
                await conn.send_text(data)
    except:
        connections[session_no].remove(ws)


@router.websocket("/ws/support/admin/{session_no}")
async def admin_ws(ws: WebSocket, session_no: str):
    await ws.accept()
    connections.setdefault(session_no, []).append(ws)

    try:
        while True:
            data = await ws.receive_text()
            for conn in connections[session_no]:
                await conn.send_text(data)
    except:
        connections[session_no].remove(ws)
