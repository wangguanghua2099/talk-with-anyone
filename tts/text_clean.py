"""TTS 文本清洗：去掉 LLM 输出中的 Markdown 符号与 Emoji 表情，
避免朗读卡顿/读出星号/把表情读成奇怪内容。

设计原则：只删符号不删内容；幂等（清洗两次结果一致）；
保守处理数字列表（"1." → "1、"）让中文 TTS 读起来自然。
"""
import re

# Emoji / 表情符号：笑脸、手势、旗帜、装饰符、箭头等，TTS 会读出怪异内容
# （含 ZWJ 组合符、变体选择符、肤色修饰符、键帽/国旗序列的组成字符）
_RE_EMOJI = re.compile(
    "["
    "\U0001F000-\U0001FAFF"   # emoji 主区：表情/手势/物品/旗帜/补充符号
    "\U00002190-\U000021FF"   # ← → ↔ 箭头
    "\U00002300-\U000023FF"   # ⌚⏰⏳ 杂项技术符号
    "\U000025A0-\U000025FF"   # ■ ● ▲ ▶ 几何图形（常被当装饰符）
    "\U00002600-\U000027BF"   # ☀⚠✅✨❤➿ 杂项符号与装饰
    "\U00002934-\U00002935"   # ⤴ ⤵
    "\U00002B00-\U00002BFF"   # ⭐ ⬛ ⭕
    "\U00003030"              # 〰
    "\U0000303D"              # 〽
    "\U00003297"              # ㊗
    "\U00003299"              # ㊙
    "\U0000203C"              # ‼
    "\U00002049"              # ⁉
    "\U00002139"              # ℹ
    "\U00002122"              # ™
    "\U0000FE00-\U0000FE0F"   # 变体选择符（文本/emoji 样式切换）
    "\U0000200D"              # ZERO WIDTH JOINER（组合 emoji 连接符）
    "\U000020E3"              # 键帽组合符（1️⃣ 的组成）
    "]+"
)
# 去 emoji 后可能残留的连续空格（拉丁文本场景）
_RE_MULTI_SPACE = re.compile(r"[ \t]{2,}")

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
    s = _RE_EMOJI.sub("", s)
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
    s = _RE_MULTI_SPACE.sub(" ", s)
    return s.strip()
