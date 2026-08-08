from fastapi import APIRouter
from state import agent
from errors import AppError

router = APIRouter()


@router.get("/api/conversations")
async def list_conversations():
    convs = agent.conv_manager.list_all()
    return {"conversations": convs, "current_id": agent.conv_manager.current_id}


@router.get("/api/conversations/search")
async def search_conversations(q: str = ""):
    results = agent.conv_manager.search(q)
    return {"conversations": results}


@router.post("/api/conversations")
async def create_conversation():
    conv = agent.conv_manager.create()
    agent.history = agent.conv_manager.get_messages(conv["id"])
    return {"conversation": {
        "id": conv["id"],
        "title": conv["title"],
        "created_at": conv["created_at"],
        "updated_at": conv["updated_at"],
        "message_count": len(conv["messages"])
    }}


@router.get("/api/conversations/{conv_id}")
async def get_conversation(conv_id: str):
    conv = agent.conv_manager.get(conv_id)
    if not conv:
        raise AppError("CONV_NOT_FOUND", "对话不存在", 404)
    return {"conversation": conv}


@router.delete("/api/conversations/{conv_id}")
async def delete_conversation(conv_id: str):
    if agent.conv_manager.delete(conv_id):
        if agent.conv_manager.current_id:
            agent.history = agent.conv_manager.get_messages(agent.conv_manager.current_id)
        else:
            new_conv = agent.conv_manager.create()
            agent.history = agent.conv_manager.get_messages(new_conv["id"])
        return {"status": "deleted"}
    raise AppError("CONV_NOT_FOUND", "对话不存在", 404)


@router.post("/api/conversations/switch")
async def switch_conversation(req: dict):
    conv_id = req.get("conv_id")
    conv = agent.conv_manager.switch_to(conv_id)
    if conv:
        agent.history = agent.conv_manager.get_messages(conv["id"])
        return {"status": "ok", "conversation": conv}
    raise AppError("CONV_NOT_FOUND", "对话不存在", 404)


@router.post("/api/conversations/{conv_id}/clear")
async def clear_conversation(conv_id: str):
    conv = agent.conv_manager.get(conv_id)
    if not conv:
        raise AppError("CONV_NOT_FOUND", "对话不存在", 404)
    agent.conv_manager.clear_messages(conv_id)
    agent.history = []
    return {"status": "ok"}


@router.post("/api/conversations/{conv_id}/rename")
async def rename_conversation(conv_id: str, req: dict):
    conv = agent.conv_manager.get(conv_id)
    if not conv:
        raise AppError("CONV_NOT_FOUND", "对话不存在", 404)
    title = req.get("title", "").strip()
    if not title:
        raise AppError("TITLE_EMPTY", "标题不能为空", 400)
    agent.conv_manager.rename(conv_id, title)
    return {"status": "ok", "title": title}
