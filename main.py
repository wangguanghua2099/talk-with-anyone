import os

# 设置 HuggingFace 镜像（国内加速）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

# 清理环境变量中的尾部空格（防止 URL 解析错误）
for key in ("HF_ENDPOINT", "HF_HOME", "HF_HUB_CACHE"):
    val = os.environ.get(key)
    if val and isinstance(val, str):
        os.environ[key] = val.strip()

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException
from state import BASE_DIR
from routes import all_routers
from errors import AppError

app = FastAPI(title="Talk With Anyone", version="0.1.0")


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError):
    return JSONResponse(status_code=exc.status_code, content={
        "error_code": exc.error_code,
        "message": exc.message,
        "error": exc.message,
    })


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(status_code=exc.status_code, content={
        "error_code": f"HTTP_{exc.status_code}",
        "message": str(exc.detail),
        "error": str(exc.detail),
    })


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(status_code=422, content={
        "error_code": "VALIDATION_ERROR",
        "message": "请求参数错误",
        "error": str(exc.errors())[:500],
    })


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"[ERROR] {request.method} {request.url.path}: {exc}")
    return JSONResponse(status_code=500, content={
        "error_code": "INTERNAL_ERROR",
        "message": "服务器内部错误",
        "error": str(exc),
    })


# 挂载路由
for router in all_routers:
    app.include_router(router)


@app.get("/")
async def index():
    return FileResponse(os.path.join(BASE_DIR, "static", "index.html"))


@app.on_event("startup")
async def startup_event():
    """服务器启动时预加载模型"""
    from state import tts_manager, load_config

    # 预加载当前 TTS 引擎
    config = load_config()
    if config.get("tts_engine") == "qwen3":
        print("[STARTUP] 开始预加载 TTS 模型...")
        tts_manager.preload_current_engine()


app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


if __name__ == "__main__":
    import uvicorn
    # 存在 cert.pem/key.pem 时以 HTTPS 启动，否则保持 HTTP。
    # 手机等局域网设备在 HTTP 下无法调用麦克风（浏览器要求安全上下文），
    # 用 python generate_cert.py 生成证书后自动切换为 HTTPS。
    cert_file = os.path.join(BASE_DIR, "cert.pem")
    key_file = os.path.join(BASE_DIR, "key.pem")
    if os.path.exists(cert_file) and os.path.exists(key_file):
        print("[MAIN] 检测到 HTTPS 证书，以 https://<本机IP>:7862 启动")
        uvicorn.run(app, host="0.0.0.0", port=7862, ssl_certfile=cert_file, ssl_keyfile=key_file)
    else:
        uvicorn.run(app, host="0.0.0.0", port=7862)
