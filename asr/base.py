from abc import ABC, abstractmethod
import numpy as np


class BaseASREngine(ABC):
    """ASR 引擎基类，所有 ASR 实现都继承此类"""

    @abstractmethod
    def load_model(self):
        """加载模型"""
        pass

    @abstractmethod
    def transcribe(self, audio: np.ndarray, sample_rate: int = 16000) -> str:
        """识别音频，返回文本

        Args:
            audio: float32 音频数组，值域 [-1, 1]
            sample_rate: 采样率，默认 16000

        Returns:
            识别出的文本
        """
        pass

    def warmup(self):
        """预热模型（可选）"""
        pass

    def unload(self):
        """卸载模型释放显存（可选）"""
        pass
