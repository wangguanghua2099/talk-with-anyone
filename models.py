from pydantic import BaseModel
from typing import Optional


class ChatRequest(BaseModel):
    message: str


class ConfigUpdate(BaseModel):
    ai_role_prompt: Optional[str] = None
    user_role_prompt: Optional[str] = None
    ai_voice: Optional[str] = None
    user_voice: Optional[str] = None
    ai_display_name: Optional[str] = None
    user_name: Optional[str] = None
    tts_read_user: Optional[bool] = None
    tts_read_ai: Optional[bool] = None
    llm_backend: Optional[str] = None
    llm_url: Optional[str] = None
    llm_api_key: Optional[str] = None
    llm_model: Optional[str] = None
    llm_profiles: Optional[dict] = None
    web_search_enabled: Optional[bool] = None


class TTSRequest(BaseModel):
    text: Optional[str] = None
    voice: Optional[str] = None
    url: Optional[str] = None
    file_path: Optional[str] = None


class FileRequest(BaseModel):
    path: str
    content: Optional[str] = None


class WebRequest(BaseModel):
    url: str


class SearchRequest(BaseModel):
    query: str


class CharacterRequest(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    display_name: Optional[str] = None
    ai_prompt: Optional[str] = None
    user_prompt: Optional[str] = None
    ai_voice: Optional[str] = None
    user_voice: Optional[str] = None
    engine_voices: Optional[dict] = None
