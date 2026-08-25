"""RAG 知识库服务层：多库管理、构建（含增量追加）、检索。

设计要点：
  - 一个知识库一个文件夹（见 store.py），启动时扫描 rag_data/ 自动加载
  - 构建是后台任务：路由立即返回 kb_id，前端轮询 /api/rag/status 看进度
  - "同库同模型"约束：meta.json 记录 embedding 指纹，追加/检索时校验，
    换了 embedding 模型必须重建库，防止两套坐标系混用
  - 本模块不 import state（避免循环依赖），配置由调用方作为参数传入
"""
import asyncio
import os
import time
import uuid
from typing import Dict, List, Optional, Tuple

from errors import AppError
from .chunker import chunk_text
from .embedder import EmbeddingError, get_embedder
from .store import LibraryStore, scan_library_dirs

MAX_FILE_BYTES = 100 * 1024 * 1024      # 单文件上限 100MB
MAX_TOTAL_CHUNKS = 200_000              # 全库块数上限（保护内存）


def decode_text(data: bytes) -> str:
    for enc in ("utf-8", "gb18030"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise AppError("RAG_DECODE_FAILED", "文件不是 UTF-8/GBK 编码的纯文本", 400)


class RAGService:
    def __init__(self):
        self.data_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rag_data")
        os.makedirs(self.data_dir, exist_ok=True)
        self.libraries: Dict[str, LibraryStore] = {}
        self.progress: Dict[str, Dict] = {}       # kb_id -> 构建进度（仅构建期间存在）
        self._tasks: Dict[str, asyncio.Task] = {} # 防止后台任务被垃圾回收
        self.load_errors: Dict[str, str] = {}
        self._scan()

    # ---------- 库发现 ----------

    def _scan(self):
        for kb_dir in scan_library_dirs(self.data_dir):
            try:
                lib = LibraryStore.load(kb_dir)
                self.libraries[lib.kb_id] = lib
            except Exception as e:
                self.load_errors[os.path.basename(kb_dir)] = str(e)

    def get(self, kb_id: str) -> Optional[LibraryStore]:
        return self.libraries.get(kb_id)

    def require(self, kb_id: str) -> LibraryStore:
        lib = self.get(kb_id)
        if lib is None:
            raise AppError("RAG_LIBRARY_NOT_FOUND", "知识库不存在", 404)
        return lib

    def list_libraries(self) -> List[Dict]:
        return [lib.summary() for lib in
                sorted(self.libraries.values(), key=lambda l: l.meta.get("created_at", 0))]

    def find_by_name(self, name: str) -> Optional[LibraryStore]:
        name = (name or "").strip()
        for lib in self.libraries.values():
            if lib.meta.get("name", "").strip() == name:
                return lib
        return None

    # ---------- 构建 / 追加 ----------

    async def create_library(self, name: str,
                             files: List[Tuple[str, bytes]],
                             config: dict) -> str:
        """创建新库并后台构建；返回 kb_id。"""
        name = (name or "").strip()
        if not name:
            raise AppError("RAG_NAME_EMPTY", "知识库名称不能为空", 400)
        if self.find_by_name(name):
            raise AppError("RAG_NAME_DUPLICATED", "已存在同名知识库", 400)
        if not files:
            raise AppError("RAG_NO_FILES", "请至少上传一个 txt 文件", 400)

        kb_id = f"kb_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"
        kb_dir = os.path.join(self.data_dir, kb_id)
        os.makedirs(kb_dir, exist_ok=True)
        import json as _json
        lib = LibraryStore(kb_dir)
        lib.meta = {"name": name, "created_at": int(time.time()),
                    "files": [], "embedder": None}
        with open(os.path.join(kb_dir, "meta.json"), "w", encoding="utf-8") as f:
            _json.dump(lib.meta, f, ensure_ascii=False, indent=2)
        self.libraries[kb_id] = lib

        task = asyncio.create_task(self._ingest(kb_id, files, config))
        self._tasks[kb_id] = task
        return kb_id

    async def add_documents(self, kb_id: str,
                            files: List[Tuple[str, bytes]],
                            config: dict):
        """向已有库增量追加 txt 文件（不用重建整库）。"""
        lib = self.require(kb_id)
        if kb_id in self.progress:
            raise AppError("RAG_BUILDING", "该知识库正在构建中，请稍后再试", 409)
        task = asyncio.create_task(self._ingest(kb_id, files, config))
        self._tasks[f"{kb_id}#add{int(time.time() * 1000)}"] = task

    async def _ingest(self, kb_id: str, files: List[Tuple[str, bytes]], config: dict):
        lib = self.require(kb_id)
        progress = {"stage": "reading", "done": 0, "total": len(files), "error": None}
        self.progress[kb_id] = progress
        try:
            emb = get_embedder(config)
            # 读文件 + 分块
            all_chunks = []
            file_names = []
            for fi, (fname, data) in enumerate(files, start=1):
                if len(data) > MAX_FILE_BYTES:
                    raise AppError("RAG_FILE_TOO_LARGE",
                                   f"文件过大(>{MAX_FILE_BYTES // 1024 // 1024}MB): {fname}", 400)
                text = decode_text(data)
                size = int(config.get("rag_chunk_size") or 0) or None
                ov = int(config.get("rag_chunk_overlap") or 0) or None
                from .chunker import DEFAULT_CHUNK_SIZE, DEFAULT_OVERLAP
                chunks = chunk_text(text, size or DEFAULT_CHUNK_SIZE,
                                    DEFAULT_OVERLAP if ov is None else ov)
                for ch in chunks:
                    ch["meta"]["file"] = fname
                all_chunks.extend(chunks)
                file_names.append(fname)
                progress.update(done=fi)

            if len(lib.chunks) + len(all_chunks) > MAX_TOTAL_CHUNKS:
                raise AppError("RAG_TOO_MANY_CHUNKS", "文本块数超出上限", 400)
            if not all_chunks:
                raise AppError("RAG_EMPTY_CONTENT", "文件里没有可用文本", 400)

            progress.update(stage="embedding", done=0, total=len(all_chunks))

            # 分批向量化（embed_documents 内部按 16 条一批请求嵌入服务）
            B = 256
            for i in range(0, len(all_chunks), B):
                batch = all_chunks[i:i + B]
                vecs = await emb.embed_documents([c["text"] for c in batch])
                import numpy as np
                lib.append(batch, np.asarray(vecs, dtype=np.float32),
                           embedder_fp=emb.fingerprint(),
                           extra_files=file_names if i == 0 else None)
                progress.update(done=min(i + B, len(all_chunks)))
            progress.update(stage="done", done=progress["total"])
        except Exception as e:
            progress["error"] = str(e)
            progress["stage"] = "error"
            print(f"[RAG] 构建 {kb_id} 失败: {e}")
        finally:
            # 完成后保留几秒进度供前端收尾读取
            await asyncio.sleep(3)

    # ---------- 删除 ----------

    async def delete_library(self, kb_id: str):
        lib = self.require(kb_id)
        if kb_id in self.progress and self.progress[kb_id].get("stage") not in ("done", "error"):
            raise AppError("RAG_BUILDING", "该知识库正在构建中，无法删除", 409)
        task = self._tasks.pop(kb_id, None)
        if task and not task.done():
            task.cancel()
        lib.delete_disk()
        self.libraries.pop(kb_id, None)
        self.progress.pop(kb_id, None)

    # ---------- 检索 ----------

    async def search(self, query: str, top_k: int, active_kb: str,
                     config: dict, kb_name: str = "") -> List[Dict]:
        """检索入口。出错抛 AppError，由调用方决定提示还是静默跳过。"""
        query = (query or "").strip()
        if not query:
            return []
        lib = self.get(active_kb)
        if lib is None:
            raise AppError("RAG_NO_ACTIVE_LIBRARY", "没有激活的知识库", 400)
        if len(lib.chunks) == 0:
            raise AppError("RAG_LIBRARY_EMPTY", "知识库还没有构建完成或内容为空", 400)

        emb = get_embedder(config)
        # 先探测嵌入服务实际加载的模型名，再做指纹比对
        detect = getattr(emb, "detect_model", None)
        if detect:
            await detect()
        fp_meta = lib.meta.get("embedder") or {}
        # 指纹校验：backend 必须一致；model 双方都有值时必须一致；
        # dim 只在双方都已知时才比较（查询侧新实例未发过请求时为 None）
        if fp_meta:
            old_model = (fp_meta.get("model") or "").strip()
            new_model = (emb.model_id or "").strip()
            mismatch = fp_meta.get("backend") != emb.backend_id
            if not mismatch and old_model and new_model \
                    and old_model not in ("unknown",) and new_model != old_model:
                mismatch = True
            if not mismatch and fp_meta.get("dim") and emb.effective_dim \
                    and fp_meta["dim"] != emb.effective_dim:
                mismatch = True
            if mismatch:
                raise AppError(
                    "RAG_EMBEDDER_MISMATCH",
                    f"知识库是用 {fp_meta} 构建的，当前 embedding 配置为 "
                    f"{emb.fingerprint()}，坐标系不一致，请重建该知识库", 409)

        qvec = await emb.embed_query(query)
        # 维度守卫：截断维度等配置变更后，查询向量与库存向量维度必须一致
        if lib.vectors is not None and len(qvec) != lib.vectors.shape[1]:
            raise AppError(
                "RAG_EMBEDDER_MISMATCH",
                f"知识库向量是 {lib.vectors.shape[1]} 维，当前 embedding 配置产出 "
                f"{len(qvec)} 维（检查 rag_embed_dim 截断设置或是否更换了模型），"
                f"请重建该知识库", 409)
        hits = lib.search(qvec, top_k)
        for h in hits:
            h["kb_name"] = kb_name or lib.meta.get("name", lib.kb_id)
        return hits

    # ---------- 状态 ----------

    def status_snapshot(self) -> Dict:
        building = None
        for kb_id, p in self.progress.items():
            building = {"kb_id": kb_id, **p}
        return {
            "libraries": self.list_libraries(),
            "building": building,
            "load_errors": self.load_errors,
        }


_singleton: Optional[RAGService] = None


def get_rag_service() -> RAGService:
    global _singleton
    if _singleton is None:
        _singleton = RAGService()
    return _singleton
