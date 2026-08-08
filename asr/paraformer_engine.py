import numpy as np
from .base import BaseASREngine


class ParaformerEngine(BaseASREngine):
    """Paraformer ASR 引擎（中文最高精度）"""

    def __init__(self, device: str = "cuda"):
        self.device = device
        self.model = None
        self.punc_model = None

    def load_model(self):
        """加载 Paraformer 模型"""
        from funasr import AutoModel

        print("[ASR] 正在加载 Paraformer 模型...")
        self.model = AutoModel(
            model="iic/speech_seaco_paraformer_large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
            device=self.device,
            disable_update=True,
        )

        self.punc_model = AutoModel(
            model="iic/punc_ct-transformer_cn-en-common-vocab471067-large",
            device=self.device,
            disable_update=True,
        )
        print(f"[ASR] Paraformer 模型加载完成，设备: {self.device}")

    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        """识别音频"""
        if self.model is None:
            self.load_model()

        audio = np.asarray(audio, dtype=np.float32).reshape(-1)

        result = self.model.generate(input=audio)
        text = result[0].get("text", "")

        # 标点恢复
        if self.punc_model and text:
            punc_result = self.punc_model.generate(input=text)
            text = punc_result[0].get("text", text)

        return text.strip()
