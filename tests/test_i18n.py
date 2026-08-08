import json
import pathlib
import re

PROJECT_ROOT = pathlib.Path(__file__).resolve().parent.parent
I18N_FILE = PROJECT_ROOT / "static" / "js" / "i18n.js"
INDEX_HTML = PROJECT_ROOT / "static" / "index.html"
ROUTES_DIR = PROJECT_ROOT / "routes"


def _block_keys(src: str, lang: str, start: int = 0) -> set:
    """提取 JS 对象字面量里指定语言字典的全部 key（括号平衡解析，忽略字符串内的括号）"""
    key_at = src.index(f"{lang}: {{", start) + len(f"{lang}: {{")
    depth = 1
    i = key_at
    in_str = False
    while i < len(src) and depth:
        ch = src[i]
        if ch == "'":
            if not in_str:
                in_str = True
            elif src[i - 1] != "\\":
                in_str = False
        elif not in_str:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
        i += 1
    block = src[key_at:i - 1]
    return set(re.findall(r"^\s{12}(\w+):", block, re.M))


def _dict_keys(lang: str) -> set:
    return _block_keys(I18N_FILE.read_text(encoding="utf-8"), lang)


def _error_keys(lang: str) -> set:
    src = I18N_FILE.read_text(encoding="utf-8")
    ed = src.index("const errorDict = {")
    return _block_keys(src, lang, ed)


def test_zh_en_dict_keys_match():
    assert _dict_keys("zh") == _dict_keys("en")


def test_zh_en_error_keys_match():
    assert _error_keys("zh") == _error_keys("en")


def test_all_html_keys_exist_in_dict():
    html = INDEX_HTML.read_text(encoding="utf-8")
    used = set(re.findall(r'data-i18n(?:-placeholder|-title)?="([^"]+)"', html))
    missing = used - _dict_keys("zh")
    assert not missing, f"HTML 使用了但字典缺少的 key: {missing}"


def test_all_backend_error_codes_are_translated():
    codes = set()
    for f in ROUTES_DIR.glob("*.py"):
        codes |= set(re.findall(r'AppError\("([A-Z_]+)"', f.read_text(encoding="utf-8")))
    codes |= {"INTERNAL_ERROR", "VALIDATION_ERROR", "LLM_URL_EMPTY"}
    missing = codes - _error_keys("zh")
    assert not missing, f"后端使用了但前端未翻译的 error_code: {missing}"


def test_example_configs_are_valid_json():
    for name in ("config.example.json", "characters.example.json"):
        data = json.loads((PROJECT_ROOT / name).read_text(encoding="utf-8"))
        assert isinstance(data, (dict, list))
