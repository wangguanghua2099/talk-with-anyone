"""流式文本分句器：把 LLM 的增量输出切分成适合 TTS 的完整句子。"""


class SentenceSplitter:
    """增量分句。

    规则：
    - 中文/全角标点（。！？…；;）与换行必切；
    - 英文半角 .!? 仅在后跟空白时才切，缓冲区结尾的半角标点等待下一个字符
      （避免把 3.14、e.g. 切断）；
    - 不足 min_len 的句子先攒着，与后续内容合并成一句再送 TTS（减少合成请求数）；
    - 长时间无标点时超过 max_len 强制切，优先在逗号处断句保证语调自然。

    用法：
        sp = SentenceSplitter()
        for sentence in sp.feed(delta): ...
        tail = sp.flush()
    """

    _HARD_STOPS = set("。！？…；;\n")
    _SOFT_STOPS = set(".!?")
    _COMMAS = set("，,、：:——")

    def __init__(self, min_len=4, max_len=80):
        self.min_len = min_len
        self.max_len = max_len
        self._buf = ""

    def feed(self, delta) -> list:
        """喂入增量，返回本次凑齐的完整句子列表。"""
        self._buf += delta or ""
        sentences = []
        while True:
            cut = self._next_cut(self._buf)
            if cut is None:
                if len(self._buf) >= self.max_len:
                    sentences.append(self._force_cut())
                    continue
                break
            text, rest = cut
            sentences.append(text)
            self._buf = rest
        return sentences

    def flush(self) -> str:
        """流结束时调用，返回剩余未成句的文本。"""
        text = self._buf
        self._buf = ""
        return text

    def _next_cut(self, buf):
        """返回 (句子, 剩余) 或 None（还没有可切的完整句）。"""
        n = len(buf)
        for i, ch in enumerate(buf):
            hard = ch in self._HARD_STOPS
            soft = ch in self._SOFT_STOPS
            if not hard and not soft:
                continue
            if i + 1 < self.min_len:
                continue
            if soft:
                nxt = buf[i + 1] if i + 1 < n else None
                if nxt is None:
                    # 缓冲区结尾的半角标点：可能是小数/缩写的开头，等下一个字符
                    return None
                if not nxt.isspace():
                    continue
            return buf[:i + 1], buf[i + 1:]
        return None

    def _force_cut(self):
        """超长无标点兜底：优先在 max_len 内的最后一个逗号处断，否则硬切。"""
        end = min(len(self._buf), self.max_len)
        for j in range(end - 1, self.min_len - 1, -1):
            if self._buf[j] in self._COMMAS:
                text, rest = self._buf[:j + 1], self._buf[j + 1:]
                self._buf = rest
                return text
        text, rest = self._buf[:end], self._buf[end:]
        self._buf = rest
        return text
