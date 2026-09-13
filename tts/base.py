import threading
from abc import ABC, abstractmethod

# 全局模型加载锁：同一进程内同一时间只允许一个 TTS 引擎加载模型。
# transformers/faster_qwen3_tts 的 from_pretrained 并发调用会互相干扰
# （权重停在 meta 设备："Cannot copy out of meta tensor"），
# 切换引擎时旧引擎加载未完成、新引擎就开始预加载会触发该问题。
MODEL_LOAD_LOCK = threading.Lock()


class BaseTTSEngine(ABC):
    """TTS 引擎基类，所有引擎必须实现"""

    @abstractmethod
    async def speak(self, text, voice_id=None) -> str:
        """合成语音，返回音频文件路径"""
        pass

    @abstractmethod
    def get_voices(self) -> list:
        """获取可用音色列表"""
        pass

    @abstractmethod
    def stop(self):
        """停止播放"""
        pass

    def unload(self):
        """释放 GPU 资源，切引擎时调用"""
        pass

    @property
    def sample_rate(self) -> int:
        return 24000

    def get_name(self) -> str:
        return self.__class__.__name__
