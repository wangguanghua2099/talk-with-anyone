import json
import agent.characters as ch


def _make_manager(tmp_path, chars):
    target = tmp_path / "characters.json"
    if chars is not None:
        target.write_text(json.dumps(chars, ensure_ascii=False), encoding="utf-8")
    ch.CHARACTERS_FILE = str(target)
    return ch.CharacterManager()


def test_add_id_monotonic_after_delete(tmp_path):
    mgr = _make_manager(tmp_path, [
        {"id": "default", "name": "默认"},
        {"id": "char_2", "name": "可卿"},
        {"id": "char_3", "name": "宝钗"},
    ])
    mgr.delete("char_2")
    new = mgr.add({"name": "白素贞", "ai_voice": "晓晓"})
    assert new["id"] == "char_4"
    ids = [c["id"] for c in mgr.get_all()]
    assert len(ids) == len(set(ids))


def test_add_id_not_reusing_deleted(tmp_path):
    mgr = _make_manager(tmp_path, [
        {"id": "char_5", "name": "A"},
        {"id": "char_6", "name": "B"},
    ])
    mgr.delete("char_5")
    new = mgr.add({"name": "C", "ai_voice": "晓晓"})
    assert new["id"] == "char_7"


def test_dedupe_repairs_duplicate_ids_on_load(tmp_path):
    chars = [
        {"id": "char_6", "name": "小白"},
        {"id": "char_6", "name": "白素贞"},
    ]
    mgr = _make_manager(tmp_path, chars)
    ids = [c["id"] for c in mgr.get_all()]
    assert len(ids) == len(set(ids))
    assert "char_6" in ids
    assert any(c["id"] != "char_6" for c in mgr.get_all() if c["name"] == "白素贞")
    with open(ch.CHARACTERS_FILE, encoding="utf-8") as f:
        saved_ids = [c["id"] for c in json.load(f)]
    assert len(saved_ids) == len(set(saved_ids))


def test_caller_supplied_colliding_id_gets_new_id(tmp_path):
    mgr = _make_manager(tmp_path, [{"id": "char_3", "name": "宝钗"}])
    new = mgr.add({"id": "char_3", "name": "新角色", "ai_voice": "晓晓"})
    assert new["id"] != "char_3"
    assert new["id"] == "char_4"


def test_default_characters_no_ids_when_no_file(tmp_path):
    mgr = _make_manager(tmp_path, None)
    ids = [c["id"] for c in mgr.get_all()]
    assert len(ids) == len(set(ids))
