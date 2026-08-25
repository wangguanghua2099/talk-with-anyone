from .config import router as config_router
from .chat import router as chat_router
from .tts import router as tts_router
from .conversations import router as conversations_router
from .characters import router as characters_router
from .tools import router as tools_router
from .debug import router as debug_router
from .voice import router as voice_router
from .stt import router as stt_router
from .rag import router as rag_router

all_routers = [
    config_router,
    chat_router,
    tts_router,
    conversations_router,
    characters_router,
    tools_router,
    debug_router,
    voice_router,
    stt_router,
    rag_router,
]
