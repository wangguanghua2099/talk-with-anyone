"""本地 RAG 知识库：把 txt 文档切块、向量化、检索，注入聊天上下文以降低小模型幻觉。"""
from .embedder import EmbeddingBackend, EmbeddingError, get_embedder  # noqa: F401
from .service import RAGService, get_rag_service  # noqa: F401
