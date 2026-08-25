"""RAG 知识库 API。

构建入口：POST /api/rag/libraries（上传 txt，后台构建）
检索入口：POST /api/rag/query（直接查看召回片段，调试用）
聊天注入由 agent/core.py 在开关(rag_enabled)开启时自动调用。
"""
from typing import List, Optional

from fastapi import APIRouter, File, Form, UploadFile

from errors import AppError
from state import load_config, save_config, agent
from rag.embedder import ping_embedder
from rag.service import get_rag_service

router = APIRouter()

RAG_CONFIG_KEYS = ("rag_enabled", "rag_active_kb", "rag_top_k",
                   "rag_embed_backend", "rag_embed_url", "rag_embed_model",
                   "rag_embed_dim", "rag_chunk_size", "rag_chunk_overlap")


def _read_upload_files(files: List[UploadFile]):
    """把上传文件读成 [(文件名, 字节)]，只接受 .txt。"""
    out = []
    for f in files:
        fname = f.filename or "unnamed.txt"
        if not fname.lower().endswith(".txt"):
            raise AppError("RAG_FILE_TYPE", f"仅支持 .txt 文件: {fname}", 400)
        data = f.file.read()
        if not data:
            raise AppError("RAG_EMPTY_FILE", f"文件为空: {fname}", 400)
        out.append((fname, data))
    return out


@router.get("/api/rag/libraries")
async def list_libraries():
    svc = get_rag_service()
    config = load_config()
    return {"libraries": svc.list_libraries(), "config": _rag_config_view(config)}


def _rag_config_view(config: dict) -> dict:
    return {
        "enabled": bool(config.get("rag_enabled", False)),
        "active_kb": config.get("rag_active_kb") or "",
        "top_k": int(config.get("rag_top_k") or 4),
        "embed_url": config.get("rag_embed_url") or "http://127.0.0.1:8089",
        "embed_model": config.get("rag_embed_model") or "",
    }


async def _status_payload() -> dict:
    svc = get_rag_service()
    config = load_config()
    payload = {"config": _rag_config_view(config), **svc.status_snapshot()}
    try:
        payload["embedder"] = await ping_embedder(config)
    except Exception as e:
        payload["embedder"] = {"healthy": False, "error": str(e)}
    return payload


@router.get("/api/rag/status")
async def rag_status():
    """总状态：配置 + 库列表 + 构建进度 + 嵌入服务连通性（前端轮询用）。"""
    return await _status_payload()


@router.post("/api/rag/libraries")
async def create_library(name: str = Form(...),
                         files: List[UploadFile] = File(...)):
    """创建知识库并后台构建（构建入口）。"""
    svc = get_rag_service()
    kb_id = await svc.create_library(name, _read_upload_files(files), load_config())
    return {"kb_id": kb_id, "status": "building"}


@router.post("/api/rag/libraries/{kb_id}/documents")
async def add_documents(kb_id: str, files: List[UploadFile] = File(...)):
    """向已有库增量追加 txt（无需重建整库）。"""
    svc = get_rag_service()
    await svc.add_documents(kb_id, _read_upload_files(files), load_config())
    return {"status": "appending", "kb_id": kb_id}


@router.post("/api/rag/libraries/{kb_id}/activate")
async def activate_library(kb_id: str):
    """激活某知识库（写入 config.rag_active_kb）。"""
    svc = get_rag_service()
    lib = svc.require(kb_id)
    config = load_config()
    config["rag_active_kb"] = kb_id
    save_config(config)
    agent.config = config  # 同步内存配置，聊天立即生效
    return {"status": "ok", "active_kb": kb_id, "name": lib.meta.get("name")}


@router.delete("/api/rag/libraries/{kb_id}")
async def delete_library(kb_id: str):
    svc = get_rag_service()
    await svc.delete_library(kb_id)
    # 若删除的是当前激活库，清空激活状态与开关
    config = load_config()
    changed = False
    if config.get("rag_active_kb") == kb_id:
        config["rag_active_kb"] = ""
        config["rag_enabled"] = False
        changed = True
    if changed:
        save_config(config)
        agent.config = config  # 同步内存配置
    return {"status": "deleted"}


@router.post("/api/rag/config")
async def update_rag_config(body: dict):
    """更新 RAG 开关/参数：enabled、active_kb、top_k、嵌入服务地址等。"""
    config = load_config()
    for key in RAG_CONFIG_KEYS:
        if key in body and body[key] is not None:
            value = body[key]
            if key == "rag_top_k":
                value = max(1, min(int(value), 20))
            elif key == "rag_embed_dim":
                value = max(0, min(int(value), 4096))  # 0 = 不截断
            elif key == "rag_chunk_size":
                value = max(100, min(int(value), 4000))
            elif key == "rag_chunk_overlap":
                value = max(0, min(int(value), 1000))
            elif key == "rag_enabled":
                value = bool(value)
            else:
                value = str(value).strip()
            config[key] = value
    # 激活库要存在才允许写入
    if config.get("rag_active_kb"):
        get_rag_service().require(config["rag_active_kb"])
    save_config(config)
    agent.config = config  # 同步内存配置，聊天立即生效
    return {"status": "ok", "config": _rag_config_view(config)}


@router.post("/api/rag/query")
async def query_library(body: dict):
    """检索入口（调试/预览）：返回最相关的原文片段。"""
    query = (body.get("query") or "").strip()
    if not query:
        raise AppError("RAG_EMPTY_QUERY", "查询内容不能为空", 400)
    config = load_config()
    top_k = int(body.get("top_k") or config.get("rag_top_k") or 4)
    active_kb = (body.get("kb_id") or config.get("rag_active_kb") or "").strip()
    if not active_kb:
        raise AppError("RAG_NO_ACTIVE_LIBRARY", "请先选择一个知识库", 400)
    hits = await get_rag_service().search(query, top_k=top_k,
                                          active_kb=active_kb, config=config)
    return {"hits": hits}
