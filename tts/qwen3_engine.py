import os
import re
import time
import asyncio
import threading
import numpy as np
from .base import BaseTTSEngine

QWEN3_VOICES = {
    "Vivian": "中文女声",
    "Serena": "中文女声",
    "Uncle_Fu": "中文男声",
    "Dylan": "中文男声（北京口音）",
    "Eric": "中文男声（四川口音）",
    "Ryan": "英文男声",
    "Aiden": "英文男声",
    "Ono_Anna": "日文女声",
    "Sohee": "韩文女声",
}

_SENTENCE_END = re.compile(r"[.!?。！？…\n]")
_CLAUSE_END = re.compile(r"[,;:，、；：]")
_SOFT_BREAK = re.compile(r"\s+")
_MIN_TTS_CHARS = 6
_TARGET_TTS_CHARS = 24
_MAX_TTS_CHARS = 48
_FIRST_CHUNK_MAX = 6

DEFAULT_MODEL_NAME = "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice"
DEFAULT_MAX_NEW_TOKENS = 4000

_NON_TTS_CHAR = re.compile(r'[^\u4e00-\u9fa5a-zA-Z0-9\s]')


def clean_text_for_tts(text: str) -> str:
    return _NON_TTS_CHAR.sub('', text).strip()


def split_text(text: str) -> list:
    if not text or not text.strip():
        return []
    text = text.strip()
    chunks = []
    while text:
        text = text.lstrip()
        if not text:
            break
        sentence = _SENTENCE_END.search(text)
        if sentence and sentence.end() <= _TARGET_TTS_CHARS:
            end = sentence.end()
            head, tail = text[:end], text[end:]
            if len(head.strip()) >= _MIN_TTS_CHARS or tail.strip():
                chunks.append(head.strip())
                text = tail
                continue
        if len(text) >= _TARGET_TTS_CHARS:
            clause = None
            for match in _CLAUSE_END.finditer(text):
                if match.end() >= _MIN_TTS_CHARS:
                    clause = match
                    if match.end() >= _TARGET_TTS_CHARS:
                        break
            if clause and clause.end() <= _MAX_TTS_CHARS:
                end = clause.end()
                chunks.append(text[:end].strip())
                text = text[end:]
                continue
        if sentence and sentence.end() <= _MAX_TTS_CHARS:
            end = sentence.end()
            head, tail = text[:end], text[end:]
            if len(head.strip()) >= _MIN_TTS_CHARS or tail.strip():
                chunks.append(head.strip())
                text = tail
                continue
        if len(text) < _MAX_TTS_CHARS:
            chunks.append(text.strip())
            break
        window = text[:_MAX_TTS_CHARS]
        split_at = 0
        for match in _SOFT_BREAK.finditer(window):
            if match.end() >= _TARGET_TTS_CHARS:
                split_at = match.end()
                break
            split_at = match.end()
        if split_at < _MIN_TTS_CHARS:
            split_at = _MAX_TTS_CHARS
        chunks.append(text[:split_at].strip())
        text = text[split_at:]
    return chunks if chunks else [text.strip()] if text.strip() else []


def split_text_first_short(text: str) -> list:
    if not text or not text.strip():
        return []
    raw_chunks = split_text(text)
    if not raw_chunks:
        return []
    cleaned_chunks = []
    for chunk in raw_chunks:
        cleaned = clean_text_for_tts(chunk)
        if not cleaned:
            continue
        if len(cleaned) > _TARGET_TTS_CHARS:
            split_at = _TARGET_TTS_CHARS
            for i in range(min(_TARGET_TTS_CHARS, len(cleaned)), _MIN_TTS_CHARS, -1):
                split_at = i
                break
            cleaned_chunks.append(cleaned[:split_at])
            remaining = cleaned[split_at:]
            if remaining:
                cleaned_chunks.append(remaining)
        else:
            cleaned_chunks.append(cleaned)
    if not cleaned_chunks:
        return []
    if len(cleaned_chunks) > 1 and len(cleaned_chunks[0]) < 8:
        first = cleaned_chunks[0]
        second = cleaned_chunks[1]
        if len(first) + len(second) <= _TARGET_TTS_CHARS:
            cleaned_chunks = [first + second] + cleaned_chunks[2:]
    return cleaned_chunks


class Qwen3TTSEngine(BaseTTSEngine):

    def __init__(self, config=None):
        self.config = config or {}
        self.is_playing = False
        self.model = None
        self.audio_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
        os.makedirs(self.audio_dir, exist_ok=True)

        # 模型名优先级：环境变量 > config.json > 默认值。
        # 高配用户可用 QWEN3_TTS_MODEL 直接指定 1.7B：
        #   set QWEN3_TTS_MODEL=Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice
        self.model_name = (
            os.environ.get("QWEN3_TTS_MODEL")
            or self.config.get("qwen3_model_name")
            or DEFAULT_MODEL_NAME
        )
        self.device = self.config.get("qwen3_device", "cuda")
        self.language = self.config.get("qwen3_language", "chinese")
        self.max_new_tokens = self.config.get("qwen3_max_new_tokens", DEFAULT_MAX_NEW_TOKENS)
        self.speaker = self.config.get("qwen3_speaker", "Vivian")

        self._lock = threading.Lock()
        self._loading = False
        self._load_complete = False
        self._load_attempts = 0
        self._load_failed = False
        self._last_fail_time = 0
        self._COOLDOWN_SECONDS = 60
        self._MAX_ATTEMPTS = 3
        self._preload_task = None

    def _load_model_sync(self):
        if self.model is not None or self._load_complete:
            return
        if self._load_failed and (time.time() - self._last_fail_time) < self._COOLDOWN_SECONDS:
            remaining = int(self._COOLDOWN_SECONDS - (time.time() - self._last_fail_time))
            print(f"[Qwen3 TTS] 冷却期中，{remaining}秒后重试")
            return
        if self._load_attempts >= self._MAX_ATTEMPTS:
            self._load_failed = True
            self._last_fail_time = time.time()
            print(f"[Qwen3 TTS] 加载失败 {self._MAX_ATTEMPTS} 次，进入 {self._COOLDOWN_SECONDS} 秒冷却期")
            return
        with self._lock:
            if self.model is not None or self._load_complete:
                return
            if self._loading:
                return
            self._loading = True
            try:
                import torch
                from faster_qwen3_tts import FasterQwen3TTS
                dtype = torch.bfloat16 if torch.cuda.is_bf16_supported() else torch.float16
                print(f"[Qwen3 TTS] 正在加载模型 (第 {self._load_attempts + 1} 次): {self.model_name}")
                self.model = FasterQwen3TTS.from_pretrained(
                    self.model_name,
                    device=self.device,
                    dtype=dtype,
                    attn_implementation="sdpa",
                )
                print(f"[Qwen3 TTS] 模型权重加载完成，正在预热 CUDA 图...")
                self.model._warmup(100)
                self._load_complete = True
                self._load_attempts = 0
                self._load_failed = False
                print(f"[Qwen3 TTS] 模型加载 + CUDA 图预热完成，设备: {self.device}")
            except Exception as e:
                self._load_attempts += 1
                self._load_failed = True
                self._last_fail_time = time.time()
                print(f"[Qwen3 TTS] 模型加载失败 (第 {self._load_attempts} 次): {e}")
            finally:
                self._loading = False

    async def _ensure_model(self):
        if self.model is not None:
            return True
        if self._load_failed and (time.time() - self._last_fail_time) < self._COOLDOWN_SECONDS:
            return False
        if self._loading:
            for _ in range(100):
                if not self._loading:
                    break
                await asyncio.sleep(0.1)
            return self.model is not None
        await asyncio.to_thread(self._load_model_sync)
        return self.model is not None

    def _available_speakers(self):
        """模型实际可用的音色；未加载时回退到内置列表（兼容 0.6B/1.7B 音色差异）"""
        if self.model is not None:
            try:
                spk_id = self.model.model.config.talker_config.spk_id
                speakers = list(spk_id.keys())
                if speakers:
                    return speakers
            except Exception:
                pass
        return list(QWEN3_VOICES.keys())

    def _generate_audio_sync(self, text, speaker):
        audio_list, sr = self.model.generate_custom_voice(
            text=text,
            speaker=speaker,
            language=self.language,
            max_new_tokens=self.max_new_tokens,
        )
        if audio_list:
            audio = np.asarray(audio_list[0], dtype=np.float32).squeeze()
            if audio.size > 0:
                yield audio

    async def speak(self, text, voice_id=None):
        self.is_playing = True
        output_path = os.path.join(self.audio_dir, "current_audio.wav")
        try:
            if not await self._ensure_model():
                print("[Qwen3 TTS] 模型不可用")
                self.is_playing = False
                return None
            available = self._available_speakers()
            speaker = voice_id or self.speaker
            if speaker not in available:
                speaker = "Vivian" if "Vivian" in available else available[0]
            all_audio = []
            def collect_audio():
                for chunk in self._generate_audio_sync(text, speaker):
                    all_audio.append(chunk)
            await asyncio.to_thread(collect_audio)
            if all_audio and self.is_playing:
                import soundfile as sf
                combined = np.concatenate(all_audio)
                sf.write(output_path, combined, 24000, format="WAV", subtype="PCM_16")
        except Exception as e:
            print(f"[Qwen3 TTS] 生成失败: {e}")
            self.is_playing = False
            raise e
        self.is_playing = False
        return "/static/current_audio.wav"

    async def speak_streaming(self, text, voice_id=None):
        self.is_playing = True
        import time as _time

        try:
            t0 = _time.perf_counter()
            if not await self._ensure_model():
                print(f"[Qwen3 TTS] 模型不可用 (耗时 {_time.perf_counter()-t0:.1f}s)")
                self.is_playing = False
                return
            print(f"[Qwen3 TTS] 模型就绪耗时: {_time.perf_counter()-t0:.1f}s")

            available = self._available_speakers()
            speaker = voice_id or self.speaker
            if speaker not in available:
                speaker = "Vivian" if "Vivian" in available else available[0]

            # 用 asyncio.Queue 把阻塞的生成循环放到后台线程，不阻塞事件循环
            queue = asyncio.Queue(maxsize=8)
            loop = asyncio.get_running_loop()

            def _generate_thread():
                """在后台线程中运行同步生成循环"""
                audio_iter = self.model.generate_custom_voice_streaming(
                    text=text,
                    speaker=speaker,
                    language=self.language,
                    max_new_tokens=min(1024, self.max_new_tokens),
                    non_streaming_mode=False,
                )
                gen_created = _time.perf_counter()

                chunk_idx = 0
                for item in audio_iter:
                    if not self.is_playing:
                        break
                    now = _time.perf_counter()
                    if isinstance(item, tuple) and len(item) >= 2:
                        audio_chunk = item[0]
                    else:
                        audio_chunk = getattr(item, "audio", None)

                    if audio_chunk is not None:
                        audio_chunk = np.asarray(audio_chunk, dtype=np.float32).squeeze()
                        if chunk_idx == 0:
                            gen_time = now - gen_created
                            total_time = now - t0
                            print(f"[Qwen3 TTS] 首包延迟: {total_time:.2f}s (gen={gen_time:.2f}s)")
                        chunk_idx += 1
                        loop.call_soon_threadsafe(queue.put_nowait, ("chunk", audio_chunk))

                loop.call_soon_threadsafe(queue.put_nowait, ("done", None))
                print(f"[Qwen3 TTS] 流式完成, 共 {chunk_idx} 个 chunk, "
                      f"总耗时 {_time.perf_counter()-t0:.1f}s")

            # 启动后台线程
            thread = threading.Thread(target=_generate_thread, daemon=True)
            thread.start()

            # 异步消费队列（不阻塞事件循环）
            while True:
                msg_type, data = await queue.get()
                if msg_type == "done":
                    break
                yield data

            thread.join()

        except Exception as e:
            import traceback
            print(f"[Qwen3 TTS] 流式生成失败: {e}")
            traceback.print_exc()

        self.is_playing = False

    def preload(self):
        if self._load_complete or self._loading:
            return
        if self._load_failed and (time.time() - self._last_fail_time) < self._COOLDOWN_SECONDS:
            return
        self._preload_task = asyncio.create_task(asyncio.to_thread(self._load_model_sync))

    def get_voices(self):
        return self._available_speakers()

    def get_voice_info(self, voice_id):
        return QWEN3_VOICES.get(voice_id, None)

    def stop(self):
        self.is_playing = False

    def unload(self):
        self.model = None
        self._load_complete = False
        self._loading = False
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
