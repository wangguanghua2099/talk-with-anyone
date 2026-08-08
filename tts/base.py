from abc import ABC, abstractmethod


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
