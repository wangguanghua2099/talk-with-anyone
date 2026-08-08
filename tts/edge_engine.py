import edge_tts
import os
from .base import BaseTTSEngine

EDGE_VOICES = {
    "晓晓": "zh-CN-XiaoxiaoNeural",
    "云扬": "zh-CN-YunyangNeural",
    "云希": "zh-CN-YunxiNeural",
    "晓伊": "zh-CN-XiaoyiNeural",
    "云健": "zh-CN-YunjianNeural",
    "云夏": "zh-CN-YunxiaNeural",
    "晓北": "zh-CN-liaoning-XiaobeiNeural",
    "晓妮": "zh-CN-shaanxi-XiaoniNeural",
    "晓晨": "zh-TW-HsiaoChenNeural",
    "云哲": "zh-TW-YunJheNeural",
    "晓雨": "zh-TW-HsiaoYuNeural",
    "晓嘉": "zh-HK-HiuGaaiNeural",
    "晓曼": "zh-HK-HiuMaanNeural",
    "云龙": "zh-HK-WanLungNeural",
    "Aria": "en-US-AriaNeural",
    "Jenny": "en-US-JennyNeural",
    "Guy": "en-US-GuyNeural",
    "Christopher": "en-US-ChristopherNeural",
    "Michelle": "en-US-MichelleNeural",
    "Sonia": "en-GB-SoniaNeural",
    "Ryan": "en-GB-RyanNeural",
    "Libby": "en-GB-LibbyNeural",
    "Thomas": "en-GB-ThomasNeural",
    "Natasha": "en-AU-NatashaNeural",
    "William": "en-AU-WilliamNeural",
}


class EdgeTTSEngine(BaseTTSEngine):
    def __init__(self):
        self.is_playing = False
        self.audio_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
        os.makedirs(self.audio_dir, exist_ok=True)

    async def speak(self, text, voice_id="晓晓"):
        self.is_playing = True
        voice = EDGE_VOICES.get(voice_id, EDGE_VOICES["晓晓"])
        output_path = os.path.join(self.audio_dir, "current_audio.mp3")
        try:
            communicate = edge_tts.Communicate(text, voice)
            await communicate.save(output_path)
        except Exception as e:
            self.is_playing = False
            raise e
        self.is_playing = False
        return "/static/current_audio.mp3"

    def get_voices(self):
        return list(EDGE_VOICES.keys())

    def stop(self):
        self.is_playing = False
