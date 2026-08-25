"""TTS 文本清洗：去掉 LLM 输出中的 Markdown 符号，避免朗读卡顿/读出星号。

设计原则：只删符号不删内容；幂等（清洗两次结果一致）；
保守处理数字列表（"1." → "1、"）让中文 TTS 读起来自然。
"""
import re

# **粗体** / __粗体__ / *斜体* / _斜体_ / `代码`
_RE_BOLD = re.compile(r"\*\*(.+?)\*\*", re.S)
_RE_BOLD2 = re.compile(r"(?<!\w)__(.+?)__(?!\w)", re.S)
_RE_ITALIC = re.compile(r"(?<![\w*])\*(?![\s*])([^*\n]+?)\*(?![\w*])")
_RE_ITALIC2 = re.compile(r"(?<!\w)_([^\n_]+?)_(?!\w)")
_RE_CODE = re.compile(r"`+([^`]*)`+")
# [文字](链接) → 文字；图片整体删除
_RE_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
_RE_IMG = re.compile(r"!\[[^\]]*\]\([^)]*\)")
# 行首标记：标题#/引用>/项目符*-+
_RE_HEADING = re.compile(r"(?m)^\s{0,3}#{1,6}\s*")
_RE_QUOTE = re.compile(r"(?m)^\s{0,3}>\s?")
_RE_BULLET = re.compile(r"(?m)^\s{0,6}[*\-+]\s+")
# 数字列表 "1. " / "1)" → "1、"
_RE_ORDERED = re.compile(r"(?m)^\s{0,6}(\d{1,3})[.)]\s+")
# 表格分隔行 |---|---| 整行删除
_RE_TABLE_SEP = re.compile(r"(?m)^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)+\|?\s*$")
# 分隔线 *** 或 --- 独占一行
_RE_HR = re.compile(r"(?m)^\s{0,3}([*_\-])\s*(?:\1\s*){2,}$")
# 残留的孤立符号
_RE_STRAY = re.compile(r"[*_`]+|^\s*~{2,}\s*$", re.M)
# 连续空行压缩
_RE_BLANK = re.compile(r"\n{3,}")
# 表格竖线读成逗号停顿
_RE_PIPE = re.compile(r"\s*\|\s*")


def clean_for_tts(text: str) -> str:
    if not text:
        return text
    s = text
    s = _RE_IMG.sub("", s)
    s = _RE_LINK.sub(r"\1", s)
    s = _RE_CODE.sub(r"\1", s)
    s = _RE_BOLD.sub(r"\1", s)
    s = _RE_BOLD2.sub(r"\1", s)
    s = _RE_ITALIC.sub(r"\1", s)
    s = _RE_ITALIC2.sub(r"\1", s)
    s = _RE_TABLE_SEP.sub("", s)
    s = _RE_PIPE.sub("，", s)
    s = _RE_HR.sub("", s)
    s = _RE_HEADING.sub("", s)
    s = _RE_QUOTE.sub("", s)
    s = _RE_BULLET.sub("", s)
    s = _RE_ORDERED.sub(r"\1、", s)
    s = _RE_STRAY.sub("", s)
    s = _RE_BLANK.sub("\n\n", s)
    return s.strip()
