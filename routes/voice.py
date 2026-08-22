import json
import uuid
import asyncio
import logging
import numpy as np
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
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

                    # VAD 检测
                    vad_result = vad.feed(audio_chunk)

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

                        # 调用 LLM
                        interrupt_event.clear()

                        # 新一轮发言开始：取消上一轮尚未完成的回复任务，
                        # 防止被打断的旧回复晚到、与新回复叠加
                        # （CancelledError 不会被 run_chat 的 except Exception 捕获）
                        if active_task is not None and not active_task.done():
                            active_task.cancel()

                        async def run_chat():
                            try:
                                reply = await agent.chat(user_text, config=config)
                                await send_json({
                                    "type": "assistant.completed",
                                    "text": reply,
                                })
                                return reply
                            except Exception as e:
                                logger.error(f"[VOICE] LLM 调用失败: {e}")
                                await send_json({
                                    "type": "assistant.error",
                                    "message": str(e),
                                })
                                return None

                        active_task = asyncio.create_task(run_chat())

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

