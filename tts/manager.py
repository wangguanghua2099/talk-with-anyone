from .edge_engine import EdgeTTSEngine
from .moss_engine import MossTTSEngine
from .qwen3_engine import Qwen3TTSEngine
from .qwen3_clone_engine import Qwen3CloneTTSEngine
from .text_clean import clean_for_tts
from .voices import VoiceManager
from .custom_voice_manager import CustomVoiceManager


class TTSManager:
    def __init__(self, config):
        self.config = config
        self.engines = {}
        self.voice_manager = VoiceManager()
        self.custom_voice_manager = CustomVoiceManager()
        self._initialized = False

    def _ensure_engines(self):
        """懒加载引擎"""
        if self._initialized:
            return
        self.engines = {
            "edge": EdgeTTSEngine(),
            "moss": MossTTSEngine(use_gpu=True, custom_voice_manager=self.custom_voice_manager, config=self.config),
            "qwen3": Qwen3TTSEngine(self.config),
            "qwen3-clone": Qwen3CloneTTSEngine(self.config, custom_voice_manager=self.custom_voice_manager),
        }
        self._initialized = True

    def get_current_engine_name(self):
        return self.config.get("tts_engine", "edge")

    def get_current_engine(self):
        self._ensure_engines()
        engine_name = self.get_current_engine_name()
        return self.engines.get(engine_name, self.engines["edge"])

    def preload_current_engine(self):
        """预加载当前 TTS 引擎"""
        self._ensure_engines()
        engine = self.get_current_engine()
        if hasattr(engine, 'preload'):
            print(f"[TTS] 预加载引擎: {self.get_current_engine_name()}")
            engine.preload()

    async def speak(self, text, voice=None):
        engine = self.get_current_engine()
        return await engine.speak(clean_for_tts(text or ""), voice)

    def get_voices(self):
        engine = self.get_current_engine()
        engine_name = self.get_current_engine_name()
        built_in = engine.get_voices()
        # 如果是支持克隆的引擎，合并自定义音色
        if engine_name in ("moss", "qwen3-clone"):
            custom = [v["name"] for v in self.custom_voice_manager.get_all()]
            return built_in + custom
        return built_in

    def switch_engine(self, engine_name):
        self._ensure_engines()
        if engine_name in self.engines:
            old = self.get_current_engine()
            if old is not None:
                # 卸载失败（如缺依赖）不能卡住切换，否则引擎永远切不过去
                try:
                    old.unload()
                except Exception as e:
                    print(f"[TTS] 卸载旧引擎 {type(old).__name__} 失败(忽略): {e}")
            self.config["tts_engine"] = engine_name
            try:
                self.preload_current_engine()
            except Exception as e:
                print(f"[TTS] 预加载新引擎 {engine_name} 失败(忽略): {e}")
            return True
        return False

    def stop(self):
        engine = self.get_current_engine()
        engine.stop()
