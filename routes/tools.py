import os
from fastapi import APIRouter, UploadFile, File
from models import FileRequest, WebRequest, SearchRequest
from state import BASE_DIR, UPLOAD_DIR
from agent.tools import fetch_web_content, read_file, write_file, search_web, get_current_time
from errors import AppError

router = APIRouter()


@router.post("/api/upload")
async def upload_file(file: UploadFile = File(...)):
    file_path = os.path.join(UPLOAD_DIR, file.filename)
    raw = await file.read()
    with open(file_path, "wb") as f:
        f.write(raw)
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("gbk", errors="replace")
    return {"file_path": file_path, "filename": file.filename, "content": text}


@router.post("/api/file/read")
async def api_read_file(req: FileRequest):
    content = read_file(req.path)
    return {"content": content}


@router.post("/api/file/write")
async def api_write_file(req: FileRequest):
    if not req.content:
        raise AppError("CONTENT_EMPTY", "内容不能为空", 400)
    success = write_file(req.path, req.content)
    return {"success": success}


@router.post("/api/web/fetch")
async def api_fetch_web(req: WebRequest):
    content = fetch_web_content(req.url)
    return {"content": content}


@router.post("/api/search")
async def api_search(req: SearchRequest):
    result = search_web(req.query)
    return {"result": result}


@router.get("/api/time")
async def api_time():
    return {"time": get_current_time()}
