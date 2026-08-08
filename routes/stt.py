import os
import uuid
import asyncio
import numpy as np
from fastapi import APIRouter, UploadFile, File
from state import UPLOAD_DIR
from errors import AppError

router = APIRouter()


def decode_audio(path: str) -> np.ndarray:
    """解码音频为 16kHz 单声道 float32，覆盖 wav/mp3/flac/ogg/m4a

    解码链：librosa -> torchaudio，逐步兜底。
    """
    try:
        import librosa
        audio, _ = librosa.load(path, sr=16000, mono=True)
        return np.asarray(audio, dtype=np.float32).reshape(-1)
    except Exception:
        pass

    try:
        import torchaudio
        wav, sr = torchaudio.load(path)
        if wav.shape[0] > 1:
            wav = wav.mean(dim=0, keepdim=True)
        if sr != 16000:
            wav = torchaudio.functional.resample(wav, sr, 16000)
        return wav.squeeze(0).numpy().astype(np.float32)
    except Exception:
        pass

    try:
        import soundfile as sf
        audio, sr = sf.read(path, dtype="float32", always_2d=False)
        if audio.ndim > 1:
            audio = audio.mean(axis=1)
        if sr != 16000:
            from scipy.signal import resample_poly
            from math import gcd
            g = gcd(sr, 16000)
            audio = resample_poly(audio, 16000 // g, sr // g).astype(np.float32)
        return np.asarray(audio, dtype=np.float32).reshape(-1)
    except Exception:
        return np.array([], dtype=np.float32)


@router.post("/api/stt/transcribe")
async def stt_transcribe(file: UploadFile = File(...)):
    """上传音频文件并转成文本"""
    from .voice import _get_asr

    suffix = os.path.splitext(file.filename or "")[1] or ".wav"
    tmp_path = os.path.join(UPLOAD_DIR, f"stt_{uuid.uuid4().hex}{suffix}")
    with open(tmp_path, "wb") as f:
        f.write(await file.read())

    try:
        audio = await asyncio.to_thread(decode_audio, tmp_path)
        if audio.size == 0:
            raise AppError("AUDIO_DECODE_FAILED", "无法解码音频，请确认格式为 wav/mp3/flac/ogg/m4a", 400)

        asr = _get_asr()
        text = await asyncio.to_thread(asr.transcribe, audio)
        text = (text or "").strip()
        if not text:
            raise AppError("STT_NO_SPEECH", "未识别到语音内容", 400)

        return {"text": text}
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
