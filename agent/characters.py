import json
import os
import re

CHARACTERS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "characters.json")

ALL_ENGINES = ["edge", "moss", "qwen3", "qwen3-clone"]

DEFAULT_ENGINE_VOICES = {
    "edge": "晓晓",
    "moss": "女声中文1",
    "qwen3": "Vivian",
    "qwen3-clone": "声音克隆",
}

DEFAULT_CHARACTERS = [
    {
        "id": "default",
        "name": "默认助手",
        "display_name": "助手",
        "ai_prompt": "你是一个友好的AI助手，说话自然亲切。你不是任何公司的产品，你就是一个独立的助手。",
        "ai_voice": "晓晓",
        "ai_avatar": "",
        "engine_voices": {
            "edge": "晓晓",
            "moss": "女声中文1",
            "qwen3": "Vivian",
            "qwen3-clone": "声音克隆"
        }
    },
    {
        "id": "qianyun",
        "name": "千云",
        "display_name": "千云",
        "ai_prompt": "你叫千云，是一位26岁女生，性格活泼开朗，长得漂亮身材好，博学多才。你不是任何公司的产品，你就是千云。回复内容控制在80字以内。回复内容不要使用表情符号。",
        "ai_voice": "晓晓",
        "ai_avatar": "",
        "engine_voices": {
            "edge": "晓晓",
            "moss": "女声中文1",
            "qwen3": "Vivian",
            "qwen3-clone": "声音克隆"
        }
    }
]


class CharacterManager:
    def __init__(self):
        self.characters = self._load()
        # 自愈：若数据里存在重复 ID，重新分配唯一 ID 并落盘
        if self._dedupe(self.characters):
            self._save()

    def _load(self):
        if os.path.exists(CHARACTERS_FILE):
            try:
                with open(CHARACTERS_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return DEFAULT_CHARACTERS.copy()

    def _next_id(self, chars=None):
        # 单调递增：取现有 char_<n> 的最大序号 + 1，删除后也绝不复用旧 ID
        source = chars if chars is not None else self.characters
        max_n = 0
        for c in source:
            m = re.match(r"^char_(\d+)$", c.get("id", "") or "")
            if m:
                max_n = max(max_n, int(m.group(1)))
        return f"char_{max_n + 1}"

    def _dedupe(self, chars):
        changed = False
        seen = set()
        for c in chars:
            cid = c.get("id", "") or ""
            if not cid or cid in seen:
                c["id"] = self._next_id(chars)
                changed = True
            seen.add(c["id"])
        return changed

    def _save(self):
        with open(CHARACTERS_FILE, "w", encoding="utf-8") as f:
            json.dump(self.characters, f, ensure_ascii=False, indent=2)

    def get_all(self):
        return self.characters

    def get_by_id(self, character_id):
        for c in self.characters:
            if c["id"] == character_id:
                return c
        return None

    def add(self, character):
        if not character.get("id"):
            character["id"] = self._next_id()
        elif any(c["id"] == character["id"] for c in self.characters):
            # 调用方传入的 ID 与现有角色冲突时，强制换新，保证唯一
            character["id"] = self._next_id()
        if not character.get("ai_voice"):
            character["ai_voice"] = "晓晓"
        engine_voices = character.setdefault("engine_voices", {})
        for eng in ALL_ENGINES:
            engine_voices.setdefault(eng, DEFAULT_ENGINE_VOICES.get(eng, "晓晓"))
        for key in ["user_voice", "user_prompt", "user_avatar"]:
            character.pop(key, None)
        self.characters.append(character)
        self._save()
        return character

    def update(self, character_id, updates):
        for c in self.characters:
            if c["id"] == character_id:
                for key in ["user_voice", "user_prompt", "user_avatar"]:
                    updates.pop(key, None)
                if "engine_voices" in updates:
                    c.setdefault("engine_voices", {}).update(updates.pop("engine_voices"))
                c.update(updates)
                self._save()
                return c
        return None

    def delete(self, character_id):
        self.characters = [c for c in self.characters if c["id"] != character_id]
        self._save()
        return True
