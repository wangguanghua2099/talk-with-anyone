import os
import subprocess
from .base import BaseTTSEngine

BUILTIN_VOICES = {
    # 中文男声
    "Junhao": "中文男声-模思智能",
    "Zhiming": "中文男声-京味胡同闲聊",
    "Weiguo": "中文男声-说书",
    # 中文女声
    "Xiaoyu": "中文女声-明星",
    "Yuewen": "中文女声-机车",
    "Lingyu": "中文女声-深夜电台",
    # 英文
    "Trump": "英文男声-Trump",
    "Ava": "英文女声-The Bitter Lesson",
    "Bella": "英文女声-A Gentle Reminder",
    "Adam": "英文男声-English News",
    "Nathan": "英文男声-The Quiet Motion",
    # 日文
    "Soyo": "日文女声",
    "Saki": "日文女声",
    "Mortis": "日文女声",
    "Umiri": "日文女声",
    "Mei": "日文女声",
    "Anon": "日文女声",
    "Arisa": "日文女声",
}


class MossTTSEngine(BaseTTSEngine):
    def __init__(self, model_dir=None, use_gpu=False, custom_voice_manager=None, config=None):
        self.config = config or {}
        self.use_gpu = use_gpu
        self.is_playing = False
        self.audio_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
        os.makedirs(self.audio_dir, exist_ok=True)
        self._loaded = False
        self._runtime = None
        self.custom_voice_manager = custom_voice_manager
        self._sample_rate = 24000

        # 模型目录优先级：构造参数 > config.json 的 moss_model_dir > 环境变量 MOSS_TTS_MODEL_DIR
        self.model_dir = (
            model_dir
            or self.config.get("moss_model_dir")
            or os.environ.get("MOSS_TTS_MODEL_DIR")
            or ""
        )

    def _ensure_runtime(self):
        if self._loaded and self._runtime is not None:
            return self._runtime
        if not self.model_dir:
            print("[MOSS TTS] 未配置模型目录：请在 config.json 设置 moss_model_dir，"
                  "或设置环境变量 MOSS_TTS_MODEL_DIR（指向 MOSS-TTS-Nano-100M-ONNX 快照目录）")
            return None
        try:
            from onnx_tts_runtime import OnnxTtsRuntime
            self._runtime = OnnxTtsRuntime(
                model_dir=self.model_dir,
                execution_provider="cuda" if self.use_gpu else "cpu",
            )
            self._loaded = True
            return self._runtime
        except Exception as e:
            print(f"[MOSS TTS] 初始化失败: {e}")
            return None

    async def speak(self, text, voice_id=None):
        self.is_playing = True
        output_path = os.path.join(self.audio_dir, "current_audio.wav")

        try:
            runtime = self._ensure_runtime()
            if runtime is None:
                self.is_playing = False
                raise RuntimeError("MOSS TTS runtime 初始化失败")

            # 检查是否是自定义音色
            ref_audio = None
            if voice_id and self.custom_voice_manager:
                custom = self.custom_voice_manager.get_by_name(voice_id)
                if custom:
                    ref_audio = custom["audio_path"]

            if ref_audio:
                # 使用自定义音色的声音克隆
                runtime.synthesize(
                    text=text,
                    prompt_audio_path=ref_audio,
                    output_audio_path=output_path,
                    enable_wetext=False,
                )
            else:
                # 使用内置音色
                voice = voice_id if voice_id and voice_id in BUILTIN_VOICES else "Xiaoyu"
                runtime.synthesize(
                    text=text,
                    voice=voice,
                    output_audio_path=output_path,
                    enable_wetext=False,
                )

            # 记录实际采样率（从 codec 配置获取）
            self._sample_rate = int(runtime.codec_meta["codec_config"]["sample_rate"])
        except Exception as e:
            self.is_playing = False
            raise e

        self.is_playing = False
        return "/static/current_audio.wav"

    async def speak_streaming(self, text, voice_id=None):
        """流式合成语音 — 逐 chunk 内采用增量流式解码，首段音频在生成数帧后即返回"""
        self.is_playing = True

        runtime = self._ensure_runtime()
        if runtime is None:
            return

        import queue as _queue
        import threading as _threading
        import asyncio as _asyncio
        import time as _time
        import numpy as np
        from ort_cpu_runtime import _compute_stream_lead_seconds

        self._sample_rate = int(runtime.codec_meta["codec_config"]["sample_rate"])
        sample_rate = self._sample_rate

        ref_audio = None
        if voice_id and self.custom_voice_manager:
            custom = self.custom_voice_manager.get_by_name(voice_id)
            if custom:
                ref_audio = custom["audio_path"]

        if ref_audio:
            prompt_audio_codes = runtime.encode_reference_audio(ref_audio)
        else:
            voice = voice_id if voice_id and voice_id in BUILTIN_VOICES else "Xiaoyu"
            prompt_audio_codes = runtime.resolve_prompt_audio_codes(voice=voice, prompt_audio_path=None)

        text_chunks = runtime.split_voice_clone_text(text, max_tokens=75)

        # CUDA 优化版流式解码预算（参照 MOSS-TTS-Nano PyTorch 版 _install_stream_decode_budget_patch）
        def _decode_budget(emitted, first_time):
            if first_time is None:
                return 4
            lead = _compute_stream_lead_seconds(emitted, sample_rate, first_time)
            if lead < 0.20:
                return 4
            if lead < 0.55:
                return 6
            if lead < 1.10:
                return 8
            return 12

        audio_queue = _queue.Queue()

        def generate_all():
            try:
                for chunk_text in text_chunks:
                    if not chunk_text.strip() or not self.is_playing:
                        break

                    text_token_ids = runtime.encode_text(chunk_text)
                    request_rows = runtime.build_voice_clone_request_rows(prompt_audio_codes, text_token_ids)

                    # ---- 块内增量流式解码 ----
                    runtime.codec_streaming_session.reset()
                    pending_frames = []
                    emitted_samples = 0
                    first_emit_time = None
                    decode_count = 0

                    def flush_pending(force):
                        nonlocal emitted_samples, first_emit_time, decode_count
                        if not pending_frames:
                            return
                        budget = _decode_budget(emitted_samples, first_emit_time)
                        if not force and len(pending_frames) < max(1, budget):
                            return
                        n = len(pending_frames) if force else min(len(pending_frames), max(1, budget))
                        chunk = pending_frames[:n]
                        del pending_frames[:n]
                        r = runtime.codec_streaming_session.run_frames(chunk)
                        if r is None:
                            return
                        arr, length = r
                        if length <= 0:
                            return
                        if first_emit_time is None:
                            first_emit_time = _time.perf_counter()
                        emitted_samples += length
                        decode_count += 1
                        channels = [arr[0, ci, :length].copy().astype(np.float32) for ci in range(arr.shape[1])]
                        merged = np.mean(channels, axis=0) if len(channels) > 1 else channels[0]
                        audio_queue.put(merged)

                    def on_frame(_gf, _si, frame):
                        if not self.is_playing:
                            return
                        pending_frames.append(list(frame))
                        flush_pending(False)

                    try:
                        runtime.generate_audio_frames(request_rows, on_frame=on_frame)
                        flush_pending(True)
                    finally:
                        runtime.codec_streaming_session.reset()

                    # chunk 间静音
                    if chunk_text != text_chunks[-1]:
                        word_count = len([w for w in chunk_text.strip().split() if w])
                        pause_seconds = 0.24 if word_count <= 4 else 0.14
                        pause_samples = int(sample_rate * pause_seconds)
                        if pause_samples > 0:
                            audio_queue.put(np.zeros(pause_samples, dtype=np.float32))

            except Exception as e:
                import traceback
                traceback.print_exc()
                audio_queue.put(e)
            finally:
                audio_queue.put(None)

        thread = _threading.Thread(target=generate_all, daemon=True)
        thread.start()

        while True:
            item = await _asyncio.get_event_loop().run_in_executor(None, audio_queue.get)
            if item is None:
                break
            if isinstance(item, Exception):
                raise item
            yield item

    @property
    def sample_rate(self):
        return self._sample_rate

    def get_voices(self):
        return list(BUILTIN_VOICES.keys())

    def get_voice_info(self, voice_id):
        return BUILTIN_VOICES.get(voice_id, None)

    def stop(self):
        self.is_playing = False

    def unload(self):
        self._runtime = None
        self._loaded = False
        import gc
        gc.collect()
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
