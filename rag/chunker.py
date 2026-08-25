"""文本分块：把整本小说切成适合向量检索的小块。

策略（针对中文小说优化）：
  - 按段落聚合，目标块长 ~500 字，相邻块重叠 ~80 字（保住跨块上下文）
  - 自动识别"第X回 / 楔子 / 序章"等章节标题，记入元数据便于溯源展示
  - 超长段落按句号等标点硬切，避免单块过长
"""
import re
from typing import Dict, List

# 章节标题：第X回/章/节/卷、楔子、序章、尾声等
CHAPTER_RE = re.compile(
    r"^\s*(第\s*[0-9零〇一二两三四五六七八九十百千万]+\s*[回章节卷]|"
    r"楔子|序言|序章|引子|尾声).*$"
)
SENT_SPLIT_RE = re.compile(r"(?<=[。！？!?；;…])")

DEFAULT_CHUNK_SIZE = 500
DEFAULT_OVERLAP = 80


def _split_long_paragraph(para: str, limit: int) -> List[str]:
    """把超长段落按句子边界硬切。"""
    pieces: List[str] = []
    buf = ""
    for sent in SENT_SPLIT_RE.split(para):
        if len(buf) + len(sent) > limit and buf:
            pieces.append(buf)
            buf = ""
        buf += sent
    if buf:
        pieces.append(buf)
    return pieces


def chunk_text(text: str,
               chunk_size: int = DEFAULT_CHUNK_SIZE,
               overlap: int = DEFAULT_OVERLAP) -> List[Dict]:
    """返回 [{"text": 块内容, "meta": {"chapter": "第三回"|None}}]，保证顺序稳定。"""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]

    chunks: List[Dict] = []
    cur_parts: List[str] = []
    cur_len = 0
    chapter = None

    def flush():
        nonlocal cur_parts, cur_len
        if not cur_parts:
            return
        body = "\n".join(cur_parts).strip()
        if body:
            chunks.append({"text": body, "meta": {"chapter": chapter}})
        # 给下一块留出重叠尾部，保持上下文连续
        tail = body[-overlap:] if overlap > 0 and len(body) > overlap else ""
        cur_parts = [tail] if tail else []
        cur_len = len(tail)

    for para in paragraphs:
        m = CHAPTER_RE.match(para)
        if m:
            # 新章节开始：先收掉上一章的尾巴
            flush()
            chapter = m.group(0).strip()
            cur_parts = [para]
            cur_len = len(para)
            continue

        pieces = _split_long_paragraph(para, chunk_size) if len(para) > chunk_size else [para]
        for piece in pieces:
            if cur_len > 0 and cur_len + len(piece) + 1 > chunk_size:
                flush()
            cur_parts.append(piece)
            cur_len += len(piece) + 1
    flush()
    return chunks
