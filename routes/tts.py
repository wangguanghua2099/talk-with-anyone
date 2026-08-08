import os
import base64
import numpy as np
from fastapi import APIRouter, UploadFile, File, Form, WebSocket, WebSocketDisconnect
from models import TTSRequest
from state import tts_manager, load_config, save_config, BASE_DIR, UPLOAD_DIR
from agent.tools import fetch_web_content, read_file
from errors import AppError

router = APIRouter()


@router.websocket("/ws/tts-stream")
async def tts_stream_websocket(websocket: WebSocket):
    """WebSocket 流式 TTS - 边生成边播放"""
    await websocket.accept()
    print("[TTS] WebSocket 流式连接已建立")

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

            async for audio_chunk in engine.speak_streaming(text, voice):
                audio_int16 = np.clip(audio_chunk * 32768, -32768, 32767).astype(np.int16)
                chunk_b64 = base64.b64encode(audio_int16.tobytes()).decode("ascii")
                await websocket.send_json({
                    "type": "audio.chunk",
                    "data": chunk_b64,
                    "samples": len(audio_chunk),
                })

            await websocket.send_json({"type": "audio.done"})

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

    # 使用用户指定的文件名，或使用原始文件名
    download_name = save_name if save_name else filename
    if not download_name.endswith('.wav'):
        download_name += '.wav'

    return FileResponse(
        file_path,
        media_type="audio/wav",
        filename=download_name
    )

