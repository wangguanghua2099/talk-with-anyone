import os
import re
import time
import asyncio
import threading
import numpy as np
from .base import BaseTTSEngine

# 文本分块常量（RTX 4060 优化）
_SENTENCE_END = re.compile(r"[.!?。！？…\n]")
_CLAUSE_END = re.compile(r"[,;:，、；：]")
_SOFT_BREAK = re.compile(r"\s+")
_MIN_TTS_CHARS = 6
_TARGET_TTS_CHARS = 24
_MAX_TTS_CHARS = 48

DEFAULT_MODEL_NAME = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
DEFAULT_MAX_NEW_TOKENS = 4000

# 非 TTS 字符正则
_NON_TTS_CHAR = re.compile(r'[^\u4e00-\u9fa5a-zA-Z0-9\s]')


def clean_text_for_tts(text: str) -> str:
    """清理文本，去掉标点、emoji 等非文字字符"""
    return _NON_TTS_CHAR.sub('', text).strip()


def split_text(text: str) -> list:
    """将文本分割为适合 TTS 合成的片段"""
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
    """分割文本，第一个 chunk 尽量短以降低首包延迟"""
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


class Qwen3CloneTTSEngine(BaseTTSEngine):
    """Qwen3 TTS 声音克隆引擎，使用 Base 模型"""

    def __init__(self, config=None, custom_voice_manager=None):
        self.config = config or {}
        self.is_playing = False
        self.model = None
        self.audio_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
        os.makedirs(self.audio_dir, exist_ok=True)

        # 模型名优先级：环境变量 > config.json > 默认值。
        # 高配用户可用 QWEN3_TTS_CLONE_MODEL 直接指定 1.7B：
        #   set QWEN3_TTS_CLONE_MODEL=Qwen/Qwen3-TTS-12Hz-1.7B-Base
        self.model_name = (
            os.environ.get("QWEN3_TTS_CLONE_MODEL")
            or self.config.get("qwen3_clone_model_name")
            or DEFAULT_MODEL_NAME
        )
        self.device = self.config.get("qwen3_device", "cuda")
        self.language = self.config.get("qwen3_language", "chinese")
        self.max_new_tokens = self.config.get("qwen3_max_new_tokens", DEFAULT_MAX_NEW_TOKENS)

        # 声音克隆参考音频路径
        self.ref_audio = self.config.get("qwen3_clone_ref_audio", None)
        self.ref_text = self.config.get("qwen3_clone_ref_text", "")
        self.custom_voice_manager = custom_voice_manager

        # 线程安全和加载状态
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
        """同步加载模型"""
        if self.model is not None or self._load_complete:
            return

        if self._load_failed and (time.time() - self._last_fail_time) < self._COOLDOWN_SECONDS:
            remaining = int(self._COOLDOWN_SECONDS - (time.time() - self._last_fail_time))
            print(f"[Qwen3 Clone] 冷却期中，{remaining}秒后重试")
            return

        if self._load_attempts >= self._MAX_ATTEMPTS:
            self._load_failed = True
            self._last_fail_time = time.time()
            print(f"[Qwen3 Clone] 加载失败 {self._MAX_ATTEMPTS} 次，进入 {self._COOLDOWN_SECONDS} 秒冷却期")
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

                print(f"[Qwen3 Clone] 正在加载模型 (第 {self._load_attempts + 1} 次): {self.model_name}")
                self.model = FasterQwen3TTS.from_pretrained(
                    self.model_name,
                    device=self.device,
                    dtype=dtype,
                    attn_implementation="eager",
                )
                self._load_complete = True
                self._load_attempts = 0
                self._load_failed = False
                print(f"[Qwen3 Clone] 模型加载完成，设备: {self.device}")

                # CUDA Graph 预热（需要有效的参考音频）
                if self.ref_audio:
                    print(f"[Qwen3 Clone] 开始 CUDA Graph 预热: {self.ref_audio}")
                    try:
                        for _ in range(3):
                            for item in self.model.generate_voice_clone(
                                text="你好",
                                language="chinese",
                                ref_audio=self.ref_audio,
                                ref_text=self.ref_text,
                                max_new_tokens=50,
                                non_streaming_mode=False,
                            ):
                                pass
                        print("[Qwen3 Clone] CUDA Graph 预热完成")
                    except Exception as e:
                        print(f"[Qwen3 Clone] CUDA Graph 预热失败: {e}")
                else:
                    print("[Qwen3 Clone] 无参考音频，跳过 CUDA Graph 预热")
            except Exception as e:
                self._load_attempts += 1
                self._load_failed = True
                self._last_fail_time = time.time()
                print(f"[Qwen3 Clone] 模型加载失败 (第 {self._load_attempts} 次): {e}")
            finally:
                self._loading = False

    async def _ensure_model(self):
        """确保模型已加载"""
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

    def _generate_audio_sync(self, text, ref_audio, ref_text):
        """同步生成音频（非流式，一次性获取完整音频）"""
        chunks = split_text_first_short(text)

        for chunk in chunks:
            if not chunk.strip():
                continue
            if not self.is_playing:
                break

            audio_list, sr = self.model.generate_voice_clone(
                text=chunk,
                language=self.language,
                ref_audio=ref_audio,
                ref_text=ref_text,
                max_new_tokens=self.max_new_tokens,
                non_streaming_mode=True,
            )

            if audio_list:
                audio = np.asarray(audio_list[0], dtype=np.float32).squeeze()
                if audio.size > 0:
                    yield audio

    async def speak(self, text, voice_id=None, ref_audio=None, ref_text=None):
        """合成语音（非流式，返回文件路径）"""
        self.is_playing = True
        output_path = os.path.join(self.audio_dir, "current_audio.wav")

        try:
            if not await self._ensure_model():
                print("[Qwen3 Clone] 模型不可用")
                self.is_playing = False
                return None

            # 检查是否是自定义音色
            if voice_id and self.custom_voice_manager:
                custom = self.custom_voice_manager.get_by_name(voice_id)
                if custom:
                    ref_audio = custom["audio_path"]
                    ref_text = custom.get("ref_text", "")

            # 使用传入的参考音频，或使用配置中的默认参考音频
            use_ref_audio = ref_audio or self.ref_audio
            use_ref_text = ref_text or self.ref_text

            if not use_ref_audio:
                print("[Qwen3 Clone] 未提供参考音频")
                self.is_playing = False
                return None

            # 在后台线程生成音频
            all_audio = []
            def collect_audio():
                for chunk in self._generate_audio_sync(text, use_ref_audio, use_ref_text):
                    all_audio.append(chunk)
            await asyncio.to_thread(collect_audio)

            if all_audio:
                import soundfile as sf
                combined = np.concatenate(all_audio)
                sf.write(output_path, combined, 24000, format="WAV", subtype="PCM_16")
            else:
                print("[Qwen3 Clone] 未生成音频数据")
                self.is_playing = False
                return None
        except Exception as e:
            print(f"[Qwen3 Clone] 生成失败: {e}")
            self.is_playing = False
            raise e

        self.is_playing = False
        return "/static/current_audio.wav"

    async def speak_streaming(self, text, voice_id=None, ref_audio=None, ref_text=None):
        """流式合成语音（后台线程生成，不阻塞事件循环）"""
        self.is_playing = True
        import time as _time

        try:
            t0 = _time.perf_counter()
            if not await self._ensure_model():
                print(f"[Qwen3 Clone] 模型不可用 (耗时 {_time.perf_counter()-t0:.1f}s)")
                self.is_playing = False
                return

            # 检查是否是自定义音色
            if voice_id and self.custom_voice_manager:
                custom = self.custom_voice_manager.get_by_name(voice_id)
                if custom:
                    ref_audio = custom["audio_path"]
                    ref_text = custom.get("ref_text", "")

            use_ref_audio = ref_audio or self.ref_audio
            use_ref_text = ref_text or self.ref_text

            if not use_ref_audio:
                print("[Qwen3 Clone] 未提供参考音频")
                self.is_playing = False
                return

            # 短文本一次性合成（避免每个分句都重跑一遍参考音频 prefill）；
            # 超长文本才分段，防止单次生成过长
            if len(text) > 800:
                chunks = split_text_first_short(text)
            else:
                chunks = [text]

            # 用 asyncio.Queue 把阻塞的生成循环放到后台线程，不阻塞事件循环
            queue = asyncio.Queue(maxsize=8)
            loop = asyncio.get_running_loop()

            def _generate_thread():
                chunk_idx = 0
                try:
                    for chunk in chunks:
                        if not chunk or not chunk.strip() or not self.is_playing:
                            break
                        audio_iter = self.model.generate_voice_clone_streaming(
                            text=chunk,
                            language=self.language,
                            ref_audio=use_ref_audio,
                            ref_text=use_ref_text,
                            max_new_tokens=self.max_new_tokens,
                            chunk_size=8,
                            non_streaming_mode=False,
                        )
                        for audio_chunk, sr, timing in audio_iter:
                            if not self.is_playing:
                                break
                            now = _time.perf_counter()
                            audio_chunk = np.asarray(audio_chunk, dtype=np.float32).squeeze()
                            if audio_chunk.size > 0:
                                if chunk_idx == 0:
                                    total_time = now - t0
                                    print(f"[Qwen3 Clone] 首包延迟: {total_time:.2f}s")
                                chunk_idx += 1
                                loop.call_soon_threadsafe(queue.put_nowait, ("chunk", audio_chunk))
                except Exception:
                    import traceback
                    traceback.print_exc()
                finally:
                    loop.call_soon_threadsafe(queue.put_nowait, ("done", None))
                    print(f"[Qwen3 Clone] 流式完成, 共 {chunk_idx} 个 chunk, "
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
            print(f"[Qwen3 Clone] 流式生成失败: {e}")
            traceback.print_exc()

        self.is_playing = False

    def set_ref_audio(self, ref_audio, ref_text=""):
        """设置参考音频"""
        self.ref_audio = ref_audio
        self.ref_text = ref_text
        if self.model is not None and self._load_complete and ref_audio:
            print(f"[Qwen3 Clone] 参考音频已设置，开始 CUDA Graph 预热")
            try:
                for _ in range(3):
                    for item in self.model.generate_voice_clone(
                        text="你好",
                        language="chinese",
                        ref_audio=ref_audio,
                        ref_text=ref_text,
                        max_new_tokens=50,
                        non_streaming_mode=False,
                    ):
                        pass
                print("[Qwen3 Clone] CUDA Graph 预热完成")
            except Exception as e:
                print(f"[Qwen3 Clone] CUDA Graph 预热失败: {e}")

    def preload(self):
        """预加载模型"""
        if self._load_complete or self._loading:
            return
        if self._load_failed and (time.time() - self._last_fail_time) < self._COOLDOWN_SECONDS:
            return
        self._preload_task = asyncio.create_task(asyncio.to_thread(self._load_model_sync))

    def get_voices(self):
        return ["clone engine"]

    def get_voice_info(self, voice_id):
        return {"name": "声音克隆", "description": "使用参考音频克隆声音"}

    def stop(self):
        self.is_playing = False

    def unload(self):
        self.model = None
        self._load_complete = False
        self._loading = False
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
