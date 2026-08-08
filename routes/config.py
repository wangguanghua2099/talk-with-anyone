from fastapi import APIRouter
from models import ConfigUpdate
from state import load_config, save_config, agent, auto_chat
from errors import AppError

router = APIRouter()


@router.get("/api/config")
async def get_config():
    config = load_config()
    return config


@router.post("/api/config")
async def update_config(req: ConfigUpdate):
    config = load_config()
    update_data = req.dict(exclude_none=True)
    config.update(update_data)
    save_config(config)
    agent.config = config
    auto_chat.config = config
    agent.llm.backend = config.get("llm_backend", "local")
    agent.llm.url = config.get("llm_url", "")
    agent.llm.api_key = config.get("llm_api_key", "")
    agent.llm.model = config.get("llm_model", "")
    return {"status": "ok", "config": config}


@router.post("/api/llm/models")
async def get_llm_models(req: dict):
    url = (req.get("llm_url") or "").strip()
    backend = req.get("llm_backend") or "openai"
    api_key = (req.get("llm_api_key") or "").strip()
    if backend != "local" and not url:
        return {"models": [], "error": "请先填写 API 地址", "error_code": "LLM_URL_EMPTY"}
    result = await agent.llm.list_models(
        url=url or None,
        api_key=api_key or None,
        backend=backend,
    )
    return result


@router.post("/api/avatar/upload")
async def upload_avatar(req: dict):
    avatar = req.get("avatar", "")
    target = req.get("target", "ai")
    if not avatar:
        raise AppError("AVATAR_EMPTY", "头像数据为空", 400)
    config = load_config()
    if target == "ai":
        # AI 头像只保存到当前角色（characters.json）
        from state import char_manager
        current_char_id = config.get("current_character_id", "default")
        char = char_manager.get_by_id(current_char_id)
        if char:
            char["ai_avatar"] = avatar
            char_manager.update(current_char_id, char)
    else:
        # 用户头像保存到全局配置
        config["user_avatar"] = avatar
    save_config(config)
    agent.config = config
    return {"status": "ok"}
