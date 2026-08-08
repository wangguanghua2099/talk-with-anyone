import numpy as np
from collections import deque


class VADDetector:
    """语音活动检测器 (Voice Activity Detection)"""

    # Silero VAD 要求的固定帧大小
    VAD_FRAME_SIZE = 512

    def __init__(
        self,
        threshold: float = 0.5,
        min_silence_ms: int = 800,
        min_speech_ms: int = 150,
        sample_rate: int = 16000,
        pre_roll_ms: int = 500,
    ):
        """
        初始化 VAD 检测器

        Args:
            threshold: 语音概率阈值，高于此值认为在说话
            min_silence_ms: 最小静音时长（毫秒），超过此时间认为说话结束
            min_speech_ms: 最小语音时长（毫秒），短于此时间忽略
            sample_rate: 采样率
            pre_roll_ms: 预滚缓冲时长（毫秒），保留说话前的音频
        """
        self.threshold = threshold
        self.min_silence_ms = min_silence_ms
        self.min_speech_ms = min_speech_ms
        self.sample_rate = sample_rate
        self.pre_roll_ms = pre_roll_ms

        # 计算帧数
        self.samples_per_ms = sample_rate // 1000
        self.min_silence_samples = min_silence_ms * self.samples_per_ms
        self.min_speech_samples = min_speech_ms * self.samples_per_ms
        self.pre_roll_samples = pre_roll_ms * self.samples_per_ms

        # 状态
        self._model = None
        self._is_speaking = False
        self._silence_counter = 0
        self._speech_counter = 0
        self._pre_roll_buffer = deque(maxlen=self.pre_roll_samples // self.VAD_FRAME_SIZE + 1)
        self._audio_buffer = []
        self._remainder = np.array([], dtype=np.float32)  # 剩余未处理的音频

    def load_model(self):
        """加载 Silero VAD 模型"""
        import torch

        print("[VAD] 正在加载 Silero VAD 模型...")
        self._model, _ = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            force_reload=False,
        )
        print("[VAD] Silero VAD 模型加载完成")

    def reset(self):
        """重置 VAD 状态"""
        self._is_speaking = False
        self._silence_counter = 0
        self._speech_counter = 0
        self._pre_roll_buffer.clear()
        self._audio_buffer = []
        self._remainder = np.array([], dtype=np.float32)
        if self._model:
            self._model.reset_states()

    def _ensure_model(self):
        if self._model is None:
            self.load_model()

    def _get_speech_probability(self, audio_chunk: np.ndarray) -> float:
        """计算音频块的语音概率（必须是 512 采样点）"""
        import torch

        self._ensure_model()

        # 确保是 512 采样点
        assert len(audio_chunk) == self.VAD_FRAME_SIZE, \
            f"VAD 需要 {self.VAD_FRAME_SIZE} 采样点，收到 {len(audio_chunk)}"

        audio_tensor = torch.from_numpy(audio_chunk).float()
        prob = self._model(audio_tensor, self.sample_rate).item()
        return prob

    def _process_frame(self, frame: np.ndarray) -> dict:
        """处理单个 512 采样点帧"""
        prob = self._get_speech_probability(frame)

        speaking = prob > self.threshold
        speech_start = False
        speech_end = False

        # 预滚缓冲始终保存最近的音频（说话前的静音 + 语音起始瞬间），
        # 避免 VAD 确认说话前丢掉首字，导致识别不出第一个字
        self._pre_roll_buffer.append(frame)

        if speaking:
            self._silence_counter = 0
            self._speech_counter += len(frame)

            if not self._is_speaking and self._speech_counter >= self.min_speech_samples:
                self._is_speaking = True
                speech_start = True
                # 将预滚缓冲区加入音频缓冲区（含语音起始瞬间，当前帧已在内，不重复追加）
                for buf in self._pre_roll_buffer:
                    self._audio_buffer.append(buf)
                self._pre_roll_buffer.clear()
            elif self._is_speaking:
                self._audio_buffer.append(frame)
        else:
            self._speech_counter = 0

            if self._is_speaking:
                self._silence_counter += len(frame)
                self._audio_buffer.append(frame)

                if self._silence_counter >= self.min_silence_samples:
                    self._is_speaking = False
                    speech_end = True
                    self._silence_counter = 0

        return {
            "speaking": self._is_speaking,
            "speech_start": speech_start,
            "speech_end": speech_end,
            "probability": prob,
        }

    def feed(self, audio_chunk: np.ndarray) -> dict:
        """
        输入音频块，返回 VAD 检测结果

        Args:
            audio_chunk: float32 音频块，值域 [-1, 1]，长度任意

        Returns:
            dict: {
                "speaking": bool,      # 当前是否在说话
                "speech_start": bool,  # 是否刚开始说话
                "speech_end": bool,    # 是否刚结束说话
                "probability": float,  # 语音概率
            }
        """
        audio_chunk = np.asarray(audio_chunk, dtype=np.float32).reshape(-1)

        # 合并剩余音频
        audio_chunk = np.concatenate([self._remainder, audio_chunk])

        # 分割成 512 采样点的帧
        result = {
            "speaking": self._is_speaking,
            "speech_start": False,
            "speech_end": False,
            "probability": 0.0,
        }

        while len(audio_chunk) >= self.VAD_FRAME_SIZE:
            frame = audio_chunk[:self.VAD_FRAME_SIZE]
            audio_chunk = audio_chunk[self.VAD_FRAME_SIZE:]

            frame_result = self._process_frame(frame)

            # 更新最终结果（取最后一个帧的结果）
            result["speaking"] = frame_result["speaking"]
            result["probability"] = frame_result["probability"]
            if frame_result["speech_start"]:
                result["speech_start"] = True
            if frame_result["speech_end"]:
                result["speech_end"] = True

        # 保存剩余音频
        self._remainder = audio_chunk

        return result

    def get_audio(self) -> np.ndarray:
        """获取缓冲的音频数据（说话结束后调用）"""
        if not self._audio_buffer:
            return np.array([], dtype=np.float32)

        audio = np.concatenate(self._audio_buffer)
        self._audio_buffer = []
        return audio

    @property
    def is_speaking(self) -> bool:
        return self._is_speaking
