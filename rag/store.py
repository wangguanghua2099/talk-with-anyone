"""知识库磁盘存取层：一个知识库 = 一个文件夹。

  rag_data/<kb_id>/
    meta.json     库名、embedding 模型指纹、分块参数、文件清单、块数、时间
    chunks.jsonl  每行一个 JSON：{"id", "text", "meta":{chapter, file}}（人类可读，好调试）
    vectors.npy   float32 向量矩阵 [N, dim]，每行已 L2 归一化

规模说明：一本书约几千块 × 1024 维 ≈ 十几 MB，numpy 暴力点积检索 <5ms，
且是精确搜索——这个量级远不需要 faiss/chroma。接口保持稳定，
将来库规模上去了可在本文件内替换实现，上层代码不动。
"""
import json
import os
import shutil
from typing import Dict, List, Optional

import numpy as np

META_FILE = "meta.json"
CHUNKS_FILE = "chunks.jsonl"
VECTORS_FILE = "vectors.npy"


class LibraryStore:
    def __init__(self, kb_dir: str):
        self.dir = kb_dir
        self.kb_id = os.path.basename(kb_dir.rstrip("/\\"))
        self.meta: Dict = {}
        self.chunks: List[Dict] = []
        self.vectors: Optional[np.ndarray] = None  # [N, dim] float32

    # ---------- 加载 / 元数据 ----------

    @classmethod
    def load(cls, kb_dir: str) -> "LibraryStore":
        store = cls(kb_dir)
        with open(os.path.join(kb_dir, META_FILE), "r", encoding="utf-8") as f:
            store.meta = json.load(f)
        store.chunks = []
        chunks_path = os.path.join(kb_dir, CHUNKS_FILE)
        if os.path.exists(chunks_path):
            with open(chunks_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        store.chunks.append(json.loads(line))
        vec_path = os.path.join(kb_dir, VECTORS_FILE)
        if os.path.exists(vec_path):
            store.vectors = np.load(vec_path)
        return store

    def save_meta(self):
        self.meta["chunk_count"] = len(self.chunks)
        with open(os.path.join(self.dir, META_FILE), "w", encoding="utf-8") as f:
            json.dump(self.meta, f, ensure_ascii=False, indent=2)

    def summary(self) -> Dict:
        return {
            "kb_id": self.kb_id,
            "name": self.meta.get("name", self.kb_id),
            "chunk_count": len(self.chunks),
            "dim": (self.vectors.shape[1] if self.vectors is not None else None),
            "embedder": self.meta.get("embedder"),
            "files": self.meta.get("files", []),
            "created_at": self.meta.get("created_at"),
            "updated_at": self.meta.get("updated_at"),
        }

    # ---------- 写入（构建 / 增量追加共用） ----------

    def append(self, new_chunks: List[Dict], new_vectors: np.ndarray,
               embedder_fp: Dict, extra_files: Optional[List[str]] = None):
        """追加文本块与向量并落盘。new_chunks 与 new_vectors 一一对应。"""
        import time as _time
        start_id = len(self.chunks)
        lines = []
        for i, ch in enumerate(new_chunks):
            lines.append(json.dumps(
                {"id": start_id + i, "text": ch["text"], "meta": ch.get("meta", {})},
                ensure_ascii=False))
        with open(os.path.join(self.dir, CHUNKS_FILE), "a", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
        self.chunks.extend({"id": start_id + i, "text": ch["text"],
                            "meta": ch.get("meta", {})} for i, ch in enumerate(new_chunks))

        if self.vectors is not None and len(self.vectors):
            merged = np.concatenate([self.vectors, new_vectors.astype(np.float32)])
        else:
            merged = new_vectors.astype(np.float32)
        tmp_path = os.path.join(self.dir, VECTORS_FILE + ".tmp")
        with open(tmp_path, "wb") as f:
            np.save(f, merged)
        os.replace(tmp_path, os.path.join(self.dir, VECTORS_FILE))
        self.vectors = merged

        self.meta["embedder"] = embedder_fp
        files = set(self.meta.get("files", []))
        files.update(extra_files or [])
        self.meta["files"] = sorted(files)
        self.meta["updated_at"] = int(_time.time())
        self.save_meta()

    def delete_disk(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    # ---------- 检索 ----------

    def search(self, query_vec: List[float], top_k: int = 4) -> List[Dict]:
        """query_vec 需已归一化；返回 [{rank, score, id, text, meta}] 按相似度降序。"""
        if self.vectors is None or len(self.chunks) == 0:
            return []
        q = np.asarray(query_vec, dtype=np.float32)
        scores = self.vectors @ q                      # 归一化行向量 → 点积即余弦
        k = min(max(1, top_k), len(scores))
        top_idx = np.argsort(-scores)[:k]
        hits = []
        for rank, idx in enumerate(top_idx, start=1):
            i = int(idx)
            hits.append({
                "rank": rank,
                "score": round(float(scores[i]), 4),
                "id": self.chunks[i]["id"],
                "text": self.chunks[i]["text"],
                "meta": self.chunks[i].get("meta", {}),
            })
        return hits


def scan_library_dirs(data_dir: str) -> List[str]:
    """列出 rag_data 下包含 meta.json 的库目录。"""
    out = []
    if not os.path.isdir(data_dir):
        return out
    for name in sorted(os.listdir(data_dir)):
        sub = os.path.join(data_dir, name)
        if os.path.isdir(sub) and os.path.exists(os.path.join(sub, META_FILE)):
            out.append(sub)
    return out
