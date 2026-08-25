"""Embedding 后端抽象层。

当前实现：OpenAI 兼容 HTTP 服务（llama.cpp embedding server / TEI / LM Studio 均适用）。
日后更换模型或推理方式（本地 ONNX、sentence-transformers、云 API 等），
只需新增一个子类并在 get_embedder() 里注册，其余代码不动。

协议要点（jina-embeddings-v5 官方要求）：
  - 查询向量加 "Query: " 前缀，文档向量加 "Document: " 前缀（非对称检索）
  - 向量做 L2 归一化后用点积即余弦相似度
"""
import math
from typing import List

import httpx

QUERY_PREFIX = "Query: "
DOCUMENT_PREFIX = "Document: "
DEFAULT_EMBED_URL = "http://127.0.0.1:8089"


class EmbeddingError(Exception):
    pass


def _normalize(vec: List[float]) -> List[float]:
    n = math.sqrt(sum(x * x for x in vec))
    if n <= 0:
        return vec
    return [x / n for x in vec]


class EmbeddingBackend:
    """所有 embedding 后端的公共接口。"""

    backend_id = "base"

    def __init__(self, model_id: str = "", truncate_dim: int = 0):
        self.model_id = model_id or ""
        self.dim = None          # 服务返回的完整维度，首次成功调用后填充
        # Matryoshka 截断维度（0=不截断）。截断后需重新归一化。
        # 注意：换模型或改截断维度都会改变向量坐标系 → 知识库需重建。
        self.truncate_dim = int(truncate_dim) if truncate_dim else 0

    @property
    def effective_dim(self):
        if self.truncate_dim:
            return self.truncate_dim
        return self.dim

    def fingerprint(self) -> dict:
        """写入知识库 meta.json 的模型指纹；换模型后用于检测"需重建"。"""
        return {"backend": self.backend_id, "model": self.model_id,
                "dim": self.effective_dim}

    def apply_matryoshka(self, vec: List[float]) -> List[float]:
        n = self.truncate_dim
        if not n or len(vec) <= n:
            return vec
        return _normalize(vec[:n])

    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        raise NotImplementedError

    async def embed_query(self, text: str) -> List[float]:
        raise NotImplementedError


class OpenAICompatEmbedder(EmbeddingBackend):
    """调用 OpenAI 兼容的 POST {url}/v1/embeddings 服务。"""

    backend_id = "openai"
    BATCH_SIZE = 16

    def __init__(self, url: str, model_id: str = "", timeout: float = 120.0,
                 truncate_dim: int = 0):
        super().__init__(model_id, truncate_dim)
        self.url = (url or DEFAULT_EMBED_URL).rstrip("/")
        self.timeout = timeout
        self._model_detected = False

    async def detect_model(self):
        """从嵌入服务的 /v1/models 读取实际加载的模型名（读取一次），
        让知识库指纹能真实反映当前加载的模型，防止换模型后误用旧库。"""
        if self._model_detected:
            return
        self._model_detected = True
        if self.model_id and self.model_id != "unknown":
            return  # 用户显式指定了模型名，以配置为准
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{self.url}/v1/models")
            if resp.status_code < 400:
                data = resp.json().get("data") or []
                if data and data[0].get("id"):
                    mid = str(data[0]["id"]).replace("\\", "/").split("/")[-1]
                    self.model_id = mid or self.model_id
        except Exception:
            pass  # 探测失败不致命，指纹退化为 backend 维度比对

    async def _embed_batch(self, texts: List[str]) -> List[List[float]]:
        payload = {"model": self.model_id or "default", "input": texts}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(f"{self.url}/v1/embeddings", json=payload)
        except Exception as e:
            raise EmbeddingError(f"嵌入服务连接失败({self.url}): {e}") from e
        if resp.status_code >= 400:
            raise EmbeddingError(f"嵌入服务返回 HTTP {resp.status_code}: {resp.text[:200]}")
        try:
            data = resp.json()["data"]
        except Exception as e:
            raise EmbeddingError(f"嵌入服务响应格式异常: {e}") from e
        data.sort(key=lambda d: d.get("index", 0))
        vecs = [d["embedding"] for d in data]
        if len(vecs) != len(texts):
            raise EmbeddingError(f"嵌入服务返回数量不符: 要 {len(texts)} 得 {len(vecs)}")
        if self.dim is None and vecs:
            self.dim = len(vecs[0])
        return [self.apply_matryoshka(_normalize(v)) for v in vecs]

    async def embed_documents(self, texts: List[str]) -> List[List[float]]:
        await self.detect_model()
        out: List[List[float]] = []
        for i in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[i:i + self.BATCH_SIZE]
            out.extend(await self._embed_batch([DOCUMENT_PREFIX + t for t in batch]))
        return out

    async def embed_query(self, text: str) -> List[float]:
        await self.detect_model()
        return (await self._embed_batch([QUERY_PREFIX + text]))[0]

    async def healthy(self) -> bool:
        """探测嵌入服务是否在线（llama-server 提供 /health）。"""
        for path in ("/health", "/v1/models"):
            try:
                async with httpx.AsyncClient(timeout=3.0) as client:
                    resp = await client.get(f"{self.url}{path}")
                if resp.status_code < 400:
                    return True
            except Exception:
                continue
        return False


async def ping_embedder(config: dict) -> dict:
    """供状态接口使用：返回嵌入服务的连通性信息。"""
    emb = get_embedder(config)
    ok = False
    if isinstance(emb, OpenAICompatEmbedder):
        ok = await emb.healthy()
        if ok:
            await emb.detect_model()
    return {"backend": emb.backend_id, "model": emb.model_id,
            "url": getattr(emb, "url", ""), "healthy": ok,
            "dim": emb.dim, "truncate_dim": emb.truncate_dim}


def get_embedder(config: dict) -> EmbeddingBackend:
    """工厂函数：按配置创建 embedding 后端。新后端在此注册。"""
    backend = (config.get("rag_embed_backend") or "openai").strip().lower()
    if backend == "openai":
        url = (config.get("rag_embed_url") or "").strip() or DEFAULT_EMBED_URL
        try:
            truncate = int(config.get("rag_embed_dim") or 0)
        except (TypeError, ValueError):
            truncate = 0
        return OpenAICompatEmbedder(url, (config.get("rag_embed_model") or "").strip(),
                                    truncate_dim=truncate)
    raise EmbeddingError(f"未知的 embedding 后端类型: {backend}")
