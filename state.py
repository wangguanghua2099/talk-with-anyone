import json
import os

BASE_DIR = os.path.dirname(__file__)
CONFIG_PATH = os.path.join(BASE_DIR, "config.json")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)


def load_config():
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def save_config(config):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


from tts import TTSManager
from agent import AgentCore
from agent.characters import CharacterManager
from auto_chat import AutoChatEngine

tts_manager = TTSManager(load_config())
agent = AgentCore(load_config())
auto_chat = AutoChatEngine(agent.llm, tts_manager, load_config())
char_manager = CharacterManager()
