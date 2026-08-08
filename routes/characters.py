from fastapi import APIRouter
from models import CharacterRequest
from state import char_manager, load_config, save_config, agent, auto_chat
from errors import AppError

router = APIRouter()


@router.get("/api/characters")
async def get_characters():
    return {"characters": char_manager.get_all()}


@router.post("/api/characters")
async def add_character(req: CharacterRequest):
    char = char_manager.add(req.dict(exclude_none=True))
    return {"character": char}


@router.put("/api/characters/{character_id}")
async def update_character(character_id: str, req: CharacterRequest):
    char = char_manager.update(character_id, req.dict(exclude_none=True))
    if char:
        return {"character": char}
    raise AppError("CHARACTER_NOT_FOUND", "角色不存在", 404)


@router.delete("/api/characters/{character_id}")
async def delete_character(character_id: str):
    char_manager.delete(character_id)
    return {"status": "deleted"}


@router.post("/api/characters/select")
async def select_character(req: CharacterRequest):
    config = load_config()
    if req.id:
        char = char_manager.get_by_id(req.id)
        if char:
            # 按当前引擎选音色
            current_engine = config.get("tts_engine", "edge")
            engine_voices = char.get("engine_voices", {})
            voice = engine_voices.get(current_engine) or char.get("ai_voice", "晓晓")
            config["ai_role_prompt"] = char["ai_prompt"]
            config["ai_voice"] = voice
            config["ai_display_name"] = char.get("display_name", char.get("name", "AI"))
            config["current_character_id"] = req.id
            config["engine_voices"] = engine_voices
            save_config(config)
            agent.config = config
            auto_chat.config = config
    return {"status": "ok", "config": config}
