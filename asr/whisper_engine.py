import numpy as np
from .base import BaseASREngine


class WhisperEngine(BaseASREngine):
    """Whisper ASR 引擎"""

    def __init__(self, model_name: str = "small", device: str = "cuda"):
        self.model_name = model_name
        self.device = device
        self.model = None

    def load_model(self):
        """加载 Whisper 模型"""
        import whisper

        print(f"[ASR] 正在加载 Whisper {self.model_name} 模型...")
        self.model = whisper.load_model(self.model_name, device=self.device)
        print(f"[ASR] Whisper 模型加载完成")

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        """识别音频"""
        if self.model is None:
            self.load_model()

        audio = np.asarray(audio, dtype=np.float32).reshape(-1)

        result = self.model.transcribe(
            audio,
            language="zh",
            fp16=False if self.device == "cpu" else True,
        )

        return result.get("text", "").strip()
