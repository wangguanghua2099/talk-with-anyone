import asyncio
import os
import socket

import aiohttp
import edge_tts

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

# 微软云端偶发连不上时整体重试的次数（每次内部还会先试 IPv4 再试默认解析）
_MAX_ATTEMPTS = 3


class EdgeTTSEngine(BaseTTSEngine):
    def __init__(self):
        self.is_playing = False
        self.audio_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
        os.makedirs(self.audio_dir, exist_ok=True)

    @staticmethod
    async def _synth_once(text, voice, output_path):
        """单次合成。DNS 会把 speech.platform.bing.com 解析成 IPv6 优先，
        而很多家用网络/热点的 IPv6 出不去，导致 aiohttp 按 IPv6 连接直接失败。
        因此先强制 IPv4（绝大多数场景可用），失败再退回系统默认解析兜底。"""
        last_err = None
        for family, label in ((socket.AF_INET, "IPv4"), (0, "默认解析")):
            try:
                communicate = edge_tts.Communicate(
                    text,
                    voice,
                    connector=aiohttp.TCPConnector(family=family),
                )
                await communicate.save(output_path)
                return
            except Exception as e:
                last_err = e
                print(f"[TTS] edge 合成失败({label}): {e}")
        raise last_err

    async def speak(self, text, voice_id="晓晓"):
        self.is_playing = True
        voice = EDGE_VOICES.get(voice_id, EDGE_VOICES["晓晓"])
        output_path = os.path.join(self.audio_dir, "current_audio.mp3")
        tmp_path = output_path + ".part"
        try:
            for attempt in range(1, _MAX_ATTEMPTS + 1):
                try:
                    await self._synth_once(text, voice, tmp_path)
                    break
                except Exception:
                    if attempt >= _MAX_ATTEMPTS:
                        raise
                    await asyncio.sleep(attempt)
                    print(f"[TTS] edge 第 {attempt} 次合成失败，准备重试")
            # 先写 .part 再原子替换：避免并发朗读时另一请求读到半截文件
            os.replace(tmp_path, output_path)
        finally:
            self.is_playing = False
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
        return "/static/current_audio.mp3"

    def get_voices(self):
        return list(EDGE_VOICES.keys())

    def stop(self):
        self.is_playing = False
