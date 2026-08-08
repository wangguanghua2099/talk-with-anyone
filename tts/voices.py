import json
import os
import shutil

VOICES_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "voices.json")


class VoiceManager:
    def __init__(self):
        self.voices = self._load()

    def _load(self):
        if os.path.exists(VOICES_FILE):
            try:
                with open(VOICES_FILE, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception:
                pass
        return {"edge": {}, "moss": {}}

    def _save(self):
        with open(VOICES_FILE, "w", encoding="utf-8") as f:
            json.dump(self.voices, f, ensure_ascii=False, indent=2)

    def get_voices_for_engine(self, engine_name):
        return self.voices.get(engine_name, {})

    def add_voice(self, engine_name, voice_id, voice_info):
        if engine_name not in self.voices:
            self.voices[engine_name] = {}
        self.voices[engine_name][voice_id] = voice_info
        self._save()

    def delete_voice(self, engine_name, voice_id):
        if engine_name in self.voices and voice_id in self.voices[engine_name]:
            del self.voices[engine_name][voice_id]
            self._save()

    def add_custom_voice_file(self, engine_name, voice_name, file_path):
        dest_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "custom_voices", engine_name)
        os.makedirs(dest_dir, exist_ok=True)
        ext = os.path.splitext(file_path)[1]
        dest_path = os.path.join(dest_dir, f"{voice_name}{ext}")
        shutil.copy2(file_path, dest_path)
        self.add_voice(engine_name, voice_name, {
            "name": voice_name,
            "type": "custom",
            "path": dest_path
        })
        return dest_path
