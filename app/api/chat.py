from fastapi import APIRouter
from app.schemas.chat import ChatRequest, ChatResponse
from app.services.agent_service import chat_reply

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("", response_model=ChatResponse)
def chat(payload: ChatRequest):
    return ChatResponse(reply=chat_reply(payload.message))
