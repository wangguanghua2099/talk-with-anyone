from fastapi import APIRouter
from state import agent

router = APIRouter()


@router.get("/api/debug/logs")
async def get_debug_logs():
    return {"logs": agent.llm.get_logs()}


@router.post("/api/debug/clear")
async def clear_debug_logs():
    agent.llm.clear_logs()
    return {"status": "cleared"}
