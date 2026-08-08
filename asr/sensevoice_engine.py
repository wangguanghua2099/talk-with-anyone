import re
import numpy as np
from .base import BaseASREngine


class SenseVoiceEngine(BaseASREngine):
    """SenseVoice Small ASR 引擎"""

    def __init__(self, device: str = "cuda"):
        self.device = device
        self.model = None

    def load_model(self):
        """加载 SenseVoice 模型"""
        from funasr import AutoModel

        print("[ASR] 正在加载 SenseVoice 模型...")
        self.model = AutoModel(
            model="iic/SenseVoiceSmall",
            device=self.device,
            disable_update=True,
        )
        print(f"[ASR] SenseVoice 模型加载完成，设备: {self.device}")

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        """识别音频"""
        if self.model is None:
            self.load_model()

        audio = np.asarray(audio, dtype=np.float32).reshape(-1)

        result = self.model.generate(
            input=audio,
            language="auto",
            use_itn=True,
        )

        if not result:
            return ""

        text = str(result[0].get("text", "")).strip()

        # 去除情绪标签 <|...|>
        text = re.sub(r"<\|[^|]+?\|>", "", text)

        return text.strip()
