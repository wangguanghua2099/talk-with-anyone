from tts.qwen3_engine import clean_text_for_tts, split_text


def test_clean_text_removes_punctuation():
    assert clean_text_for_tts("你好，世界！") == "你好世界"
    assert clean_text_for_tts("Hello, World!") == "Hello World"
    assert clean_text_for_tts("  abc  ") == "abc"


def test_split_empty():
    assert split_text("") == []
    assert split_text("   ") == []


def test_split_short_sentence_single_chunk():
    chunks = split_text("你好，世界。")
    assert len(chunks) == 1
    assert chunks[0] == "你好，世界。"


def test_split_long_text_chunks_reassemble():
    text = "第一句话，用来测试分句。第二句话也比较长，需要继续切分下去。第三句终于结束了。" * 5
    chunks = split_text(text)
    assert len(chunks) > 1
    joined = "".join(chunks)
    assert joined.replace(" ", "") == text.replace(" ", "")


def test_split_chunks_not_too_long():
    text = "这个句子很长，".join(["内容内容内容内容内容内容"] * 30)
    chunks = split_text(text)
    for c in chunks:
        assert len(c) <= 48
