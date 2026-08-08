from typing import Optional
import numpy as np
from .base import BaseASREngine
from .sensevoice_engine import SenseVoiceEngine


class ASRManager:
    """ASR 管理器，支持动态切换引擎"""

    ENGINES = {
        "sensevoice": SenseVoiceEngine,
        # "paraformer": ParaformerEngine,  # 需要时取消注释
        # "whisper": WhisperEngine,        # 需要时取消注释
    }

    def __init__(self, config: dict = None):
        self.config = config or {}
        self.current_engine_name = self.config.get("asr_engine", "sensevoice")
        self.engines = {}
        self._current_engine: Optional[BaseASREngine] = None

    def get_engine(self, name: str = None) -> BaseASREngine:
        engine_name = name or self.current_engine_name

        if engine_name not in self.engines:
            if engine_name not in self.ENGINES:
                raise ValueError(
                    f"未知的 ASR 引擎: {engine_name}。"
                    f"可用引擎: {list(self.ENGINES.keys())}"
                )

            engine_class = self.ENGINES[engine_name]
            device = self.config.get("asr_device", "cuda")

            print(f"[ASR] 初始化引擎: {engine_name}")
            self.engines[engine_name] = engine_class(device=device)
            self.engines[engine_name].load_model()

        return self.engines[engine_name]

    @property
    def current_engine(self) -> BaseASREngine:
        if self._current_engine is None:
            self._current_engine = self.get_engine()
        return self._current_engine

    def switch_engine(self, name: str) -> bool:
        if name not in self.ENGINES:
            return False

        self.current_engine_name = name
        self._current_engine = None
        print(f"[ASR] 切换到引擎: {name}")
        return True

    def transcribe(self, audio: np.ndarray, **kwargs) -> str:
        return self.current_engine.transcribe(audio, **kwargs)

    def list_engines(self) -> list:
        return list(self.ENGINES.keys())

    def get_status(self) -> dict:
        return {
            "engine": self.current_engine_name,
            "available_engines": self.list_engines(),
            "loaded_engines": list(self.engines.keys()),
            "device": self.config.get("asr_device", "cuda"),
        }
