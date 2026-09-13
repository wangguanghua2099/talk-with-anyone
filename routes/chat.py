import json

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from models import ChatRequest
from state import agent, auto_chat, tts_manager, load_config
from errors import AppError

router = APIRouter()


@router.post("/api/chat")
async def chat(req: ChatRequest):
    config = agent.config
    display_name = config.get("ai_display_name", "AI")

    if req.stream:
        """SSE 流式：逐段下发 delta，最后发 done（含全文，供朗读/同步使用）"""
        async def gen():
            parts = []
            try:
                async for delta in agent.chat_stream(req.message, config=config):
                    parts.append(delta)
                    yield f"data: {json.dumps({'delta': delta}, ensure_ascii=False)}\n\n"
                yield "data: " + json.dumps({
                    "done": True,
                    "reply": "".join(parts),
                    "display_name": display_name,
                    # 本轮 RAG 命中的知识库片段（开关关闭或未命中时为空数组）
                    "sources": getattr(agent, "last_rag_sources", []) or [],
                }, ensure_ascii=False) + "\n\n"
            except Exception as e:
                yield f"data: {json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

        return StreamingResponse(gen(), media_type="text/event-stream", headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        })

    reply = await agent.chat(req.message, config=config)
    return {"reply": reply, "display_name": display_name, "history": agent.history,
            # 本轮 RAG 命中的知识库片段（开关关闭或未命中时为空数组）
            "sources": getattr(agent, "last_rag_sources", []) or []}


@router.post("/api/auto-chat/start")
async def auto_chat_start(req: ChatRequest):
    config = load_config()
    auto_chat.config = config
    auto_chat.llm = agent.llm
    auto_chat.tts = tts_manager
    auto_chat.conv_manager = agent.conv_manager
    auto_chat.history = []

    def _sync_history(conv_id):
        agent.history = agent.conv_manager.get_messages(conv_id)

    auto_chat.sync_history = _sync_history

    async def on_round(role, content):
        pass

    import asyncio
    try:
        asyncio.create_task(auto_chat.start(req.message, on_round=on_round))
    except Exception as e:
        raise AppError("AUTO_CHAT_START_FAILED", str(e), 500)
    return {"status": "started"}


@router.post("/api/auto-chat/stop")
async def auto_chat_stop():
    auto_chat.stop()
    return {"status": "stopped"}


@router.get("/api/auto-chat/status")
async def auto_chat_status():
    return {
        "is_running": auto_chat.is_running,
        "current_round": auto_chat.current_round,
        "history": auto_chat.display_history
    }
