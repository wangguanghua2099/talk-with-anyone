import os
import base64
import struct
import numpy as np
from fastapi import APIRouter, UploadFile, File, Form, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import StreamingResponse
from models import TTSRequest
from state import tts_manager, load_config, save_config, BASE_DIR, UPLOAD_DIR
from agent.tools import fetch_web_content, read_file
from errors import AppError
import auth

router = APIRouter()


def _wav_header(sample_rate: int) -> bytes:
    """PCM16 单声道 WAV 头；data size 用 0xFFFFFFFF 表示未知流长度"""
    byte_rate = sample_rate * 2
    return struct.pack(
        '<4sI4s4sIHHIIHH4sI',
        b'RIFF', 0xFFFFFFFF, b'WAVE',
        b'fmt ', 16, 1, 1, sample_rate, byte_rate, 2, 16,
        b'data', 0xFFFFFFFF,
    )


@router.get("/api/tts/stream")
async def tts_stream(request: Request, text: str = "", voice: str = ""):
    """HTTP 流式 TTS：边生成边发送 WAV PCM 数据，供客户端渐进式播放。

    鉴权用查询参数 token（MediaPlayer 无法自定义请求头），因此本端点不走
    全局 Bearer 校验，而是自行校验。
    """
    expected = auth.get_expected_token()
    if expected and not auth.token_matches(expected, request.query_params.get("token", "")):
        raise AppError("UNAUTHORIZED", "需要访问口令", 401)

    if not text:
        raise AppError("TTS_EMPTY_CONTENT", "没有可朗读的内容", 400)

    engine = tts_manager.get_current_engine()

    if not hasattr(engine, 'speak_streaming'):
        audio_path = await engine.speak(text, voice or load_config().get("ai_voice", "晓晓"))
        if not audio_path or not os.path.exists(os.path.join(BASE_DIR, audio_path.lstrip("/"))):
            raise AppError("TTS_EMPTY_CONTENT", "合成失败", 500)
        return StreamingResponse(
            open(os.path.join(BASE_DIR, audio_path.lstrip("/")), "rb"),
            media_type="audio/wav",
        )

    sample_rate = getattr(engine, 'sample_rate', 24000)

    async def gen():
        try:
            yield _wav_header(sample_rate)
            async for audio_chunk in engine.speak_streaming(text, voice or load_config().get("ai_voice", "晓晓")):
                # 客户端已断开（App 打断/退出）就停止合成，避免浪费 GPU
                if await request.is_disconnected():
                    print("[TTS] HTTP 流式：客户端已断开，停止合成")
                    break
                audio_int16 = np.clip(audio_chunk * 32768, -32768, 32767).astype(np.int16)
                yield audio_int16.tobytes()
        finally:
            engine.stop()

    return StreamingResponse(gen(), media_type="audio/wav", headers={
        "Cache-Control": "no-cache",
        "X-Accel-Buffering": "no",
    })


@router.websocket("/ws/tts-stream")
async def tts_stream_websocket(websocket: WebSocket):
    """WebSocket 流式 TTS - 边生成边播放"""
    await websocket.accept()
    print("[TTS] WebSocket 流式连接已建立")

    # 可选访问口令校验
    expected = auth.get_expected_token()
    if expected and not auth.token_matches(expected, websocket.query_params.get("token", "")):
        await websocket.close(code=1008, reason="需要访问口令")
        return

    try:
        while True:
            data = await websocket.receive_json()
            text = data.get("text", "")
            voice = data.get("voice") or load_config().get("ai_voice", "晓晓")

            if not text:
                await websocket.send_json({"type": "error", "message": "文本为空"})
                continue

            # 获取当前引擎
            engine = tts_manager.get_current_engine()

            # 检查是否支持流式生成
            if not hasattr(engine, 'speak_streaming'):
                audio_path = await engine.speak(text, voice)
                await websocket.send_json({"type": "audio.done", "path": audio_path})
                continue

            sample_rate = getattr(engine, 'sample_rate', 24000)
            await websocket.send_json({"type": "audio.start", "sample_rate": sample_rate})

            try:
                async for audio_chunk in engine.speak_streaming(text, voice):
                    audio_int16 = np.clip(audio_chunk * 32768, -32768, 32767).astype(np.int16)
                    chunk_b64 = base64.b64encode(audio_int16.tobytes()).decode("ascii")
                    await websocket.send_json({
                        "type": "audio.chunk",
                        "data": chunk_b64,
                        "samples": len(audio_chunk),
                    })

                await websocket.send_json({"type": "audio.done"})
            except Exception:
                # 客户端断开或发送失败：立即停止引擎合成，避免浪费 GPU
                engine.stop()
                print("[TTS] 流式中断，已停止合成")
                raise

    except WebSocketDisconnect:
        print("[TTS] WebSocket 断开")
    except Exception as e:
        print(f"[TTS] WebSocket 错误: {e}")
        try:
            await websocket.send_json({"type": "error", "message": str(e)})
        except Exception:
            pass


@router.post("/api/tts/speak")
async def tts_speak(req: TTSRequest):
    voice = req.voice or load_config().get("ai_voice", "晓晓")
    if req.url:
        text = fetch_web_content(req.url)
    elif req.file_path:
        text = read_file(req.file_path)
    else:
        text = req.text or ""
    if not text:
        raise AppError("TTS_EMPTY_CONTENT", "没有可朗读的内容", 400)
    audio_path = await tts_manager.speak(text, voice)
    return {"audio": audio_path, "text": text}


@router.post("/api/tts/stop")
async def tts_stop():
    tts_manager.stop()
    return {"status": "stopped"}


@router.get("/api/tts/voices")
async def tts_voices():
    return {"voices": tts_manager.get_voices()}


@router.get("/api/tts/engines")
async def get_tts_engines():
    return {"engines": ["edge", "moss", "qwen3", "qwen3-clone"], "current": tts_manager.get_current_engine_name()}


@router.post("/api/tts/engine")
async def switch_tts_engine(req: dict):
    engine = req.get("engine", "edge")
    if tts_manager.switch_engine(engine):
        config = load_config()
        config["tts_engine"] = engine
        # 切换后按角色保存的引擎音色自动选择
        engine_voices = config.get("engine_voices", {})
        if engine in engine_voices:
            config["ai_voice"] = engine_voices[engine]
        save_config(config)
        return {"status": "ok", "engine": engine, "config": config}
    raise AppError("TTS_UNKNOWN_ENGINE", "未知引擎", 400)


@router.post("/api/tts/custom-voice")
async def add_custom_voice(file: UploadFile = File(...), name: str = ""):
    if not name:
        raise AppError("VOICE_NAME_EMPTY", "音色名称不能为空", 400)
    upload_dir = os.path.join(BASE_DIR, "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, file.filename)
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)
    engine_name = tts_manager.get_current_engine_name()
    tts_manager.voice_manager.add_custom_voice_file(engine_name, name, file_path)
    return {"status": "ok", "name": name}


@router.post("/api/tts/clone-ref")
async def upload_clone_ref(file: UploadFile = File(...), ref_text: str = ""):
    """上传声音克隆参考音频"""
    upload_dir = os.path.join(BASE_DIR, "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    file_path = os.path.join(upload_dir, f"clone_ref_{file.filename}")
    with open(file_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # 更新配置
    config = load_config()
    config["qwen3_clone_ref_audio"] = file_path
    config["qwen3_clone_ref_text"] = ref_text
    save_config(config)

    # 更新引擎配置
    clone_engine = tts_manager.engines.get("qwen3-clone")
    if clone_engine:
        clone_engine.set_ref_audio(file_path, ref_text)

    return {"status": "ok", "file_path": file_path}


@router.get("/api/tts/custom-voices")
async def get_custom_voices():
    """获取所有自定义音色"""
    voices = tts_manager.custom_voice_manager.get_all()
    return {"voices": voices}


@router.post("/api/tts/custom-voices")
async def add_custom_voice(name: str = Form(...), ref_text: str = Form(""), file: UploadFile = File(...)):
    """添加自定义音色"""
    if not name:
        raise AppError("VOICE_NAME_EMPTY", "音色名称不能为空", 400)

    # 保存上传的音频文件
    upload_dir = os.path.join(BASE_DIR, "uploads")
    os.makedirs(upload_dir, exist_ok=True)
    temp_path = os.path.join(upload_dir, f"temp_{file.filename}")
    with open(temp_path, "wb") as f:
        content = await file.read()
        f.write(content)

    # 添加到自定义音色管理器
    voice = tts_manager.custom_voice_manager.add(name, temp_path, ref_text)

    # 删除临时文件
    if os.path.exists(temp_path):
        os.remove(temp_path)

    return {"status": "ok", "voice": voice}


@router.delete("/api/tts/custom-voices/{voice_id}")
async def delete_custom_voice(voice_id: str):
    """删除自定义音色"""
    if tts_manager.custom_voice_manager.delete(voice_id):
        return {"status": "deleted"}
    raise AppError("VOICE_NOT_FOUND", "音色不存在", 404)


@router.post("/api/tts/synthesize")
async def synthesize_audio(req: TTSRequest):
    """合成音频并保存，返回文件路径"""
    voice = req.voice or load_config().get("ai_voice", "晓晓")
    text = req.text or ""
    if not text:
        raise AppError("TTS_EMPTY_TEXT", "文本为空", 400)

    # 使用当前引擎合成
    audio_path = await tts_manager.speak(text, voice)
    return {"audio": audio_path, "text": text}


@router.get("/api/tts/download")
async def download_audio(filename: str = "current_audio.wav", save_name: str = ""):
    """下载音频文件"""
    from fastapi.responses import FileResponse
    # 支持多种文件名格式
    if filename.startswith("/static/"):
        file_path = os.path.join(BASE_DIR, filename.lstrip("/"))
    else:
        file_path = os.path.join(BASE_DIR, "static", filename)

    if not os.path.exists(file_path):
        raise AppError("FILE_NOT_FOUND", "文件不存在", 404)

    # 使用用户指定的文件名，或使用原始文件名（按真实扩展名给对 MIME，
    # edge 输出 MP3 却标成 audio/wav 时部分播放器会解码失败）
    is_mp3 = file_path.lower().endswith(".mp3")
    download_name = save_name if save_name else os.path.basename(filename)
    if not (download_name.lower().endswith(".wav") or download_name.lower().endswith(".mp3")):
        download_name += ".wav"

    return FileResponse(
        file_path,
        media_type="audio/mpeg" if is_mp3 else "audio/wav",
        filename=download_name
    )

