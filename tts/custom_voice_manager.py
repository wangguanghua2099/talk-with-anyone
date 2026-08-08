import json
import os
import time
import shutil
import numpy as np
from datetime import datetime

BASE_DIR = os.path.dirname(os.path.dirname(__file__))
CUSTOM_VOICES_DIR = os.path.join(BASE_DIR, "custom_voices")
AUDIO_DIR = os.path.join(CUSTOM_VOICES_DIR, "audio")
VOICES_FILE = os.path.join(CUSTOM_VOICES_DIR, "voices.json")

TARGET_SR = 24000


def normalize_audio(input_path: str, output_path: str):
    """将音频转换为 mono 24000Hz 16-bit WAV"""
    import soundfile as sf
    import torch
    import torchaudio

    waveform, sr = torchaudio.load(input_path)

    # 转 mono
    if waveform.shape[0] > 1:
        waveform = torch.mean(waveform, dim=0, keepdim=True)

    # 重采样到 24000Hz
    if sr != TARGET_SR:
        resampler = torchaudio.transforms.Resample(sr, TARGET_SR)
        waveform = resampler(waveform)

    torchaudio.save(output_path, waveform, TARGET_SR, bits_per_sample=16)


class CustomVoiceManager:
    def __init__(self):
        os.makedirs(AUDIO_DIR, exist_ok=True)
        self.voices = self._load()

    def _load(self) -> list:
        if os.path.exists(VOICES_FILE):
            try:
                with open(VOICES_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("voices", [])
            except Exception:
                pass
        return []

    def _save(self):
        with open(VOICES_FILE, "w", encoding="utf-8") as f:
            json.dump({"voices": self.voices}, f, ensure_ascii=False, indent=2)

    def add(self, name: str, audio_path: str, ref_text: str = "") -> dict:
        """添加自定义音色"""
        voice_id = f"cv_{int(time.time() * 1000)}"
        ext = os.path.splitext(audio_path)[1]
        dest_filename = f"{voice_id}{ext}"
        dest_path = os.path.join(AUDIO_DIR, dest_filename)

        # 转换音频格式（stereo→mono, 任意采样率→24000Hz）
        try:
            normalize_audio(audio_path, dest_path)
        except Exception as e:
            # 回退：直接复制
            print(f"[CustomVoice] 音频转换失败，使用原始文件: {e}")
            if audio_path != dest_path:
                shutil.copy2(audio_path, dest_path)

        voice = {
            "id": voice_id,
            "name": name,
            "audio_path": dest_path,
            "ref_text": ref_text,
            "created_at": datetime.now().isoformat(),
        }
        self.voices.append(voice)
        self._save()
        return voice

    def delete(self, voice_id: str) -> bool:
        """删除自定义音色"""
        for i, v in enumerate(self.voices):
            if v["id"] == voice_id:
                # 删除音频文件
                audio_path = v.get("audio_path", "")
                if audio_path and os.path.exists(audio_path):
                    os.remove(audio_path)
                self.voices.pop(i)
                self._save()
                return True
        return False

    def get_all(self) -> list:
        """获取所有自定义音色"""
        return self.voices

    def get_by_id(self, voice_id: str) -> dict:
        """按 ID 获取音色"""
        for v in self.voices:
            if v["id"] == voice_id:
                return v
        return None

    def get_by_name(self, name: str) -> dict:
        """按名称获取音色"""
        for v in self.voices:
            if v["name"] == name:
                return v
        return None
