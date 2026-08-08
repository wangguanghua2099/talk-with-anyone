import edge_tts
import asyncio
import os

VOICES = {
    "晓晓": "zh-CN-XiaoxiaoNeural",
    "云扬": "zh-CN-YunyangNeural",
    "云希": "zh-CN-YunxiNeural",
    "晓秋": "zh-CN-XiaoyiNeural",
    "云夏": "zh-CN-YunxiaNeural",
}


class TTSEngine:
    def __init__(self):
        self.is_playing = False
        self.current_task = None
        self.audio_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
        os.makedirs(self.audio_dir, exist_ok=True)

    async def speak(self, text, voice="晓晓"):
        self.is_playing = True
        voice_id = VOICES.get(voice, VOICES["晓晓"])
        output_path = os.path.join(self.audio_dir, "current_audio.mp3")
        try:
            communicate = edge_tts.Communicate(text, voice_id)
            await communicate.save(output_path)
        except Exception as e:
            self.is_playing = False
            raise e
        self.is_playing = False
        return "/static/current_audio.mp3"

    def stop(self):
        self.is_playing = False
        if self.current_task:
            self.current_task.cancel()

    def get_voices(self):
        return list(VOICES.keys())
