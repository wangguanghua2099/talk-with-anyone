from agent.conversation import ConversationManager


def _manager(tmp_path):
    return ConversationManager(str(tmp_path))


def test_create_and_get(tmp_path):
    mgr = _manager(tmp_path)
    conv = mgr.create()
    assert conv["id"].startswith("conv_")
    assert conv["messages"] == []
    assert mgr.current_id == conv["id"]

    got = mgr.get(conv["id"])
    assert got["id"] == conv["id"]
    assert mgr.get("nonexistent") is None


def test_add_message_auto_title(tmp_path):
    mgr = _manager(tmp_path)
    conv = mgr.create()
    mgr.add_message(conv["id"], "user", "你好，请问今天天气如何？", "用户")
    mgr.add_message(conv["id"], "assistant", "今天天气不错。", "AI")

    msgs = mgr.get_messages(conv["id"])
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[1]["role"] == "assistant"

    updated = mgr.get(conv["id"])
    assert updated["title"] == "你好，请问今天天气如何？"


def test_clear_messages_keeps_conversation(tmp_path):
    mgr = _manager(tmp_path)
    conv = mgr.create()
    mgr.add_message(conv["id"], "user", "第一条")
    mgr.add_message(conv["id"], "assistant", "第二条")
    assert len(mgr.get_messages(conv["id"])) == 2

    mgr.clear_messages(conv["id"])
    assert mgr.get_messages(conv["id"]) == []
    assert mgr.get(conv["id"]) is not None


def test_rename(tmp_path):
    mgr = _manager(tmp_path)
    conv = mgr.create()
    mgr.rename(conv["id"], "新标题")
    assert mgr.get(conv["id"])["title"] == "新标题"


def test_delete_updates_current(tmp_path):
    mgr = _manager(tmp_path)
    c1 = mgr.create()
    c2 = mgr.create()
    assert mgr.current_id == c2["id"]

    mgr.add_message(c1["id"], "user", "内容", "用户")
    mgr.delete(c1["id"])
    assert mgr.get(c1["id"]) is None
    assert mgr.current_id != c1["id"]


def test_switch_to(tmp_path):
    mgr = _manager(tmp_path)
    c1 = mgr.create()
    c2 = mgr.create()
    mgr.switch_to(c1["id"])
    assert mgr.current_id == c1["id"]
    assert mgr.switch_to("nonexistent") is None


def test_search_content(tmp_path):
    mgr = _manager(tmp_path)
    conv = mgr.create()
    mgr.add_message(conv["id"], "user", "今天有什么安排？", "用户")
    mgr.add_message(conv["id"], "assistant", "今天要学习 FastAPI 框架", "AI")
    results = mgr.search("FastAPI")
    assert len(results) == 1
    assert results[0]["match_type"] == "content"
    assert any("FastAPI" in s for s in results[0]["snippets"])

    assert mgr.search("") == mgr.list_all()
    assert mgr.search("不存在的关键词") == []
