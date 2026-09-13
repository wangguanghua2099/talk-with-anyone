import base64
import json
import os
import shutil
import time
import uuid
import asyncio
import logging
import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState
from agent.sentence import SentenceSplitter
from tts.text_clean import clean_for_tts
import auth

# 配置日志输出到文件
logging.basicConfig(
    filename="voice_debug.log",
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("voice")
logger.setLevel(logging.DEBUG)

router = APIRouter()

# 全局 ASR 和 VAD 实例（懒加载）
_asr_manager = None
_vad = None
_agent = None
_tts_manager = None
_preloaded = False


def _get_config():
    from state import load_config
    return load_config()


def preload_models():
    """预加载 ASR 和 VAD 模型，避免首次使用时的延迟"""
    global _preloaded
    if _preloaded:
        return

    logger.info("[VOICE] 开始预加载模型...")
    try:
        asr = _get_asr()
        vad = _get_vad()
        logger.info("[VOICE] 模型预加载完成")
        _preloaded = True
    except Exception as e:
        logger.error(f"[VOICE] 模型预加载失败: {e}")


def _get_asr():
    global _asr_manager
    if _asr_manager is None:
        from asr import ASRManager
        config = _get_config()
        # 默认使用 CPU，避免与 TTS 的 GPU 冲突
        _asr_manager = ASRManager({
            "asr_engine": config.get("asr_engine", "sensevoice"),
            "asr_device": config.get("asr_device", "cpu"),
        })
    return _asr_manager


def _get_vad():
    global _vad
    if _vad is None:
        from asr import VADDetector
        config = _get_config()
        _vad = VADDetector(
            threshold=config.get("vad_threshold", 0.5),
            min_silence_ms=config.get("vad_min_silence_ms", 500),
            min_speech_ms=150,  # 减少到 150ms，更灵敏
            pre_roll_ms=500,    # 增加到 500ms，保留更多开头音频
        )
    return _vad


def _get_agent():
    global _agent
    if _agent is None:
        from state import agent
        _agent = agent
    return _agent


def _get_tts():
    global _tts_manager
    if _tts_manager is None:
        from state import tts_manager
        _tts_manager = tts_manager
    return _tts_manager


def _decode_pcm16(audio_bytes: bytes) -> np.ndarray:
    """解码 PCM16 音频为 float32"""
    return np.frombuffer(audio_bytes, dtype=np.int16).astype(np.float32) / 32768.0


def _encode_pcm_f32(audio: np.ndarray) -> str:
    """编码 float32 音频为 base64"""
    import base64
    chunk = np.asarray(audio, dtype=np.float32).reshape(-1)
    return base64.b64encode(chunk.tobytes()).decode("ascii")


def _iter_pcm_pieces(audio_chunk, chunk_samples=4096):
    """把 TTS 引擎吐出的 float32 音频块切成 int16 小块。

    单条 WebSocket 消息过大会压垮客户端接收缓冲区，
    与 /ws/tts-stream 的切块逻辑保持一致（约 170ms@24k）。
    """
    total = len(audio_chunk)
    for i in range(0, total, chunk_samples):
        piece = audio_chunk[i:i + chunk_samples]
        # 兼容 numpy / torch 输出
        if hasattr(piece, "numpy"):
            piece = piece.numpy()
        piece = np.asarray(piece, dtype=np.float32)
        yield np.clip(piece * 32768, -32768, 32767).astype(np.int16)


@router.get("/api/asr/engines")
async def get_asr_engines():
    """获取可用 ASR 引擎列表"""
    asr = _get_asr()
    return {"engines": asr.list_engines(), "current": asr.current_engine_name}


@router.post("/api/asr/switch")
async def switch_asr_engine(req: dict):
    """切换 ASR 引擎"""
    asr = _get_asr()
    engine = req.get("engine", "sensevoice")
    success = asr.switch_engine(engine)
    if success:
        return {"status": "ok", "engine": engine}
    return {"status": "error", "message": f"未知引擎: {engine}"}


@router.get("/api/asr/status")
async def get_asr_status():
    """获取 ASR 状态"""
    asr = _get_asr()
    return asr.get_status()


@router.websocket("/ws/voice")
async def voice_websocket(websocket: WebSocket):
    """实时语音聊天 WebSocket"""
    await websocket.accept()
    logger.info("[VOICE] WebSocket 连接已建立")

    # 可选访问口令校验
    expected = auth.get_expected_token()
    if expected and not auth.token_matches(expected, websocket.query_params.get("token", "")):
        await websocket.close(code=1008, reason="需要访问口令")
        return

    try:
        asr = _get_asr()
        logger.info(f"[VOICE] ASR 引擎: {asr.current_engine_name}")
    except Exception as e:
        logger.error(f"[VOICE] ASR 初始化失败: {e}")
        await websocket.close(code=1011, reason=f"ASR 初始化失败: {e}")
        return

    try:
        vad = _get_vad()
        logger.info("[VOICE] VAD 初始化完成")
    except Exception as e:
        logger.error(f"[VOICE] VAD 初始化失败: {e}")
        await websocket.close(code=1011, reason=f"VAD 初始化失败: {e}")
        return

    try:
        agent = _get_agent()
        tts = _get_tts()
        logger.info("[VOICE] Agent 和 TTS 初始化完成")
    except Exception as e:
        logger.error(f"[VOICE] Agent/TTS 初始化失败: {e}")
        await websocket.close(code=1011, reason=f"Agent/TTS 初始化失败: {e}")
        return

    session_id = str(uuid.uuid4())[:8]
    config = _get_config()
    mode = "chat"  # chat = 完整对话, transcribe = 仅识别文字
    interrupt_event = asyncio.Event()
    active_task = None
    client_disconnected = False

    vad.reset()

    async def send_json(payload: dict):
        try:
            await websocket.send_json(payload)
        except Exception as e:
            logger.error(f"[VOICE] 发送消息失败: {e}")

    try:
        await send_json({
            "type": "server.ready",
            "session_id": session_id,
            "asr_engine": asr.current_engine_name,
        })
        logger.info(f"[VOICE] 会话就绪: {session_id}")

        while True:
            try:
                data = await websocket.receive()

                # 二进制音频数据
                if data.get("type") == "websocket.receive" and data.get("bytes") is not None:
                    audio_bytes = data["bytes"]
                    audio_chunk = _decode_pcm16(audio_bytes)

                    # VAD 推理（silero/torch 前向）放线程池执行：不占事件循环，
                    # 否则 TTS/LLM 高负载时 GIL/CPU 争用会拖慢 delta 与音频块下发，
                    # 客户端表现为"首包出声延迟随回复变长而增长"
                    vad_result = await asyncio.to_thread(vad.feed, audio_chunk)

                    if vad_result["speech_start"]:
                        await send_json({"type": "vad.speaking", "speaking": True})

                    if vad_result["speech_end"]:
                        await send_json({"type": "vad.speaking", "speaking": False})

                        # 获取完整音频
                        full_audio = vad.get_audio()
                        if full_audio.size == 0:
                            continue

                        # ASR 识别
                        try:
                            user_text = await asyncio.to_thread(asr.transcribe, full_audio)
                        except Exception as e:
                            logger.error(f"[VOICE] ASR 识别失败: {e}")
                            await send_json({
                                "type": "asr.error",
                                "message": f"ASR 识别失败: {str(e)}",
                            })
                            continue

                        if not user_text.strip():
                            continue

                        await send_json({
                            "type": "asr.result",
                            "text": user_text,
                            "is_final": True,
                        })

                        if mode == "transcribe":
                            # 仅识别模式，不调用 LLM
                            continue

                        # 调用 LLM（流式：边生成边分句送 TTS）
                        interrupt_event.clear()

                        # 新一轮发言开始：取消上一轮尚未完成的回复任务，
                        # 防止被打断的旧回复晚到、与新回复叠加
                        # （CancelledError 不会被 run_chat_stream 的 except Exception 捕获）
                        if active_task is not None and not active_task.done():
                            active_task.cancel()

                        async def run_chat_stream(user_text=user_text, config=config):
                            """LLM 流式 → 文字 token 级直推（打字连贯），
                            分句后交给 TTS 工作线程批量合成。

                            文字与语音解耦：不等 TTS，LLM 增量立刻下发，前端打字
                            与文字聊天界面一样连贯。TTS 按引擎状态分两种策略（自适应）：
                            - 云端引擎（edge）：不占本机 GPU，边生成边合成，首句
                              ~10 字即合成，之后 ~48 字一批；
                            - 本地 GPU 引擎（qwen3/qwen3-clone/moss）：模型已驻留
                              显存（热）时同样边生成边合成；模型未加载（冷）时
                              先攒句子，等 LLM 生成完再加载+合成，避免"边流式
                              边加载模型"的算力/内存风暴。
                            工作线程串行合成保证音频块按顺序下发。
                            """
                            tts_enabled = bool(config.get("tts_read_ai", True))
                            # 本地 GPU TTS 引擎（qwen3/qwen3-clone/moss）与 LLM 同卡。
                            # 并发策略（自适应）：
                            # - 引擎未加载（冷）：并行会触发"边流式边加载模型"的加载风暴
                            #   （磁盘+CUDA初始化+图预热打满数秒，LLM 掉到几 token/s），
                            #   因此等 LLM 生成完再加载+合成；
                            # - 引擎已热（模型在显存）：短促的句级合成与 LLM 并发，
                            #   实测掉速可接受，换取首包音频大幅提前；
                            # - 云端引擎（edge）不占 GPU，始终并发。
                            try:
                                engine_name = tts.get_current_engine_name()
                            except Exception:
                                engine_name = "edge"
                            tts_is_local = engine_name != "edge"
                            engine_hot = False
                            if tts_is_local:
                                try:
                                    eng = tts.get_current_engine()
                                    engine_hot = bool(getattr(eng, "_load_complete", False)
                                                      or getattr(eng, "_loaded", False))
                                except Exception:
                                    engine_hot = False
                            tts_concurrent = (not tts_is_local) or engine_hot
                            deferred_sentences = []  # 等待模式：LLM 期间先攒句子
                            splitter = SentenceSplitter(min_len=4)
                            full_parts = []
                            audio_started = False
                            audio_seq = 0
                            send_lock = asyncio.Lock()
                            batch_chars = 48

                            async def send(payload):
                                # 主循环与 TTS 工作线程都会发消息，串行化避免并发写 WS
                                async with send_lock:
                                    await send_json(payload)

                            async def send_audio_batch(batch_text):
                                nonlocal audio_started, audio_seq
                                if not batch_text.strip():
                                    return
                                tts_text = clean_for_tts(batch_text)
                                if not tts_text.strip():
                                    return
                                engine = tts.get_current_engine()
                                voice = config.get("ai_voice", "晓晓")
                                try:
                                    if hasattr(engine, "speak_streaming"):
                                        if not audio_started:
                                            audio_started = True
                                            print(f"[VOICE] 首包音频: {time.perf_counter() - llm_t0:.2f}s")
                                            await send({
                                                "type": "audio.start",
                                                "sample_rate": getattr(engine, "sample_rate", 24000),
                                            })
                                        async for audio_chunk in engine.speak_streaming(tts_text, voice):
                                            if websocket.client_state != WebSocketState.CONNECTED:
                                                return
                                            for piece in _iter_pcm_pieces(audio_chunk):
                                                await send({
                                                    "type": "audio.chunk",
                                                    "data": base64.b64encode(piece.tobytes()).decode("ascii"),
                                                    "samples": len(piece),
                                                })
                                    else:
                                        # edge 等无流式接口的引擎：合成整批音频文件。
                                        # 引擎固定写 current_audio.<ext>，批次间会互相覆盖，
                                        # 复制到轮换文件名再下发，避免浏览器读到被覆盖的内容
                                        path = await engine.speak(tts_text, voice)
                                        if path:
                                            from state import BASE_DIR
                                            seq = audio_seq % 10
                                            audio_seq += 1
                                            ext = os.path.splitext(path)[1] or ".mp3"
                                            rot_path = f"/static/tts_sentence_{seq}{ext}"
                                            shutil.copyfile(
                                                os.path.join(BASE_DIR, path.lstrip("/")),
                                                os.path.join(BASE_DIR, rot_path.lstrip("/")),
                                            )
                                            await send({"type": "audio.file", "path": rot_path})
                                except asyncio.CancelledError:
                                    raise
                                except Exception as e:
                                    # 单批合成失败不中断回复：跳过该批音频，文字照常
                                    logger.error(f"[VOICE] 批次合成失败(跳过): {e}")

                            async def tts_worker(q):
                                # 首批阈值低（攒到 ~10 字就合成）让首音尽快出声；
                                # 之后每批 ~48 字，减少云端往返与段间静音拼接，
                                # 且合成耗时被上一批的播放时间掩盖，衔接连贯
                                first = True
                                pending = ""
                                threshold = 36
                                while True:
                                    item = await q.get()
                                    if item is None:
                                        break
                                    pending += item
                                    if len(pending) >= threshold:
                                        await send_audio_batch(pending)
                                        pending = ""
                                        first = False
                                        threshold = batch_chars
                                if pending.strip():
                                    await send_audio_batch(pending)

                            batch_q = asyncio.Queue()
                            worker = asyncio.create_task(tts_worker(batch_q)) if tts_enabled else None
                            llm_t0 = time.perf_counter()
                            first_llm_delta = False

                            try:
                                async for delta in agent.chat_stream(user_text, config=config):
                                    full_parts.append(delta)
                                    if not first_llm_delta:
                                        first_llm_delta = True
                                        print(f"[VOICE] LLM 首token延迟: {time.perf_counter() - llm_t0:.2f}s")
                                    # 文字立刻下发（token 级），不等 TTS
                                    await send({"type": "assistant.delta", "text": delta})
                                    if tts_enabled:
                                        for sentence in splitter.feed(delta):
                                            if tts_concurrent:
                                                await batch_q.put(sentence)
                                            else:
                                                deferred_sentences.append(sentence)
                                if tts_enabled:
                                    rest = splitter.flush()
                                    if rest:
                                        if tts_concurrent:
                                            await batch_q.put(rest)
                                        else:
                                            deferred_sentences.append(rest)
                            except asyncio.CancelledError:
                                # 被打断：不发生完成事件，部分内容已由 chat_stream 存库
                                if worker:
                                    worker.cancel()
                                try:
                                    tts.stop()
                                except Exception as e:
                                    logger.error(f"[VOICE] 停止 TTS 失败: {e}")
                                raise
                            except Exception as e:
                                logger.error(f"[VOICE] LLM 调用失败: {e}")
                                if worker:
                                    worker.cancel()
                                try:
                                    tts.stop()
                                except Exception:
                                    pass
                                await send({
                                    "type": "assistant.error",
                                    "message": str(e),
                                })
                                return None

                            # 正常结束：把 LLM 期间攒下的句子交给 TTS 工作线程，
                            # 批量合成并等它发完（本地引擎此时 LLM 已结束，无算力争抢）
                            try:
                                if worker:
                                    for sentence in deferred_sentences:
                                        await batch_q.put(sentence)
                                    await batch_q.put(None)
                                    await worker
                            except asyncio.CancelledError:
                                if worker:
                                    worker.cancel()
                                try:
                                    tts.stop()
                                except Exception:
                                    pass
                                raise

                            if audio_started:
                                await send({"type": "audio.done"})
                            reply = "".join(full_parts).strip()
                            print(f"[VOICE] 本轮完成: 全文 {len(reply)} 字, "
                                  f"LLM 调用起总耗时 {time.perf_counter() - llm_t0:.2f}s")
                            await send({
                                "type": "assistant.completed",
                                "text": reply,
                            })
                            return reply

                        active_task = asyncio.create_task(run_chat_stream())

                # JSON 控制消息
                elif data.get("type") == "websocket.receive" and data.get("text") is not None:
                    message = json.loads(data["text"])
                    msg_type = message.get("type", "")

                    if msg_type == "session.start":
                        mode = message.get("mode", "chat")
                        await send_json({
                            "type": "session.ready",
                            "session_id": session_id,
                            "mode": mode,
                        })
                        logger.info(f"[VOICE] 会话开始: mode={mode}")

                    elif msg_type == "client_stats":
                        # 客户端实测：收到 LLM 首个文字增量 → 用户听到语音 的间隔。
                        # 发消息→听到的总延迟 ≈ ASR 耗时 + 本值（本值不含 ASR）。
                        lat = message.get("llm_first_token_to_audio_ms")
                        if lat is not None:
                            print(f"[VOICE] LLM首token→出声: {lat} ms（客户端实测）")

                    elif msg_type == "interrupt":
                        interrupt_event.set()
                        if active_task and not active_task.done():
                            active_task.cancel()
                        try:
                            tts.stop()
                        except Exception as e:
                            logger.error(f"[VOICE] 停止 TTS 失败: {e}")
                        await send_json({
                            "type": "interrupt.ack",
                            "reason": "user_interrupt",
                        })

                    elif msg_type == "session.stop":
                        interrupt_event.set()
                        if active_task and not active_task.done():
                            active_task.cancel()
                        try:
                            tts.stop()
                        except Exception as e:
                            logger.error(f"[VOICE] 停止 TTS 失败: {e}")
                        await send_json({"type": "session.closed"})
                        client_disconnected = True
                        break

                # 连接关闭
                elif data.get("type") == "websocket.disconnect":
                    logger.info("[VOICE] 客户端断开连接")
                    client_disconnected = True
                    break
            except WebSocketDisconnect:
                logger.info("[VOICE] WebSocket 断开")
                client_disconnected = True
                break
            except Exception as e:
                # 单条消息处理失败不中断通话连接
                logger.error(f"[VOICE] 消息处理错误(继续保持连接): {e}")

    except WebSocketDisconnect:
        logger.info("[VOICE] WebSocket 断开")
        client_disconnected = True
    except Exception as e:
        logger.error(f"[VOICE] WebSocket 错误: {e}")
        try:
            await send_json({"type": "error", "message": str(e)})
        except Exception:
            pass
    finally:
        logger.info(f"[VOICE] 会话结束: {session_id}")

