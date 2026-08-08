import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from urllib.parse import quote_plus

import requests
from bs4 import BeautifulSoup

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"

_SEARCH_PREFIXES = [
    "请你帮我搜索一下", "你帮我搜索一下", "请帮我搜索一下", "帮我搜索一下",
    "你帮我查一下", "请帮我查一下", "你帮我找一下", "请你帮我搜一下",
    "你帮我搜一下", "你给我搜一下", "帮我搜一下", "帮我查一下",
    "你搜索一下", "搜索一下", "帮我查询一下", "查询一下", "你查一下",
    "查一下", "你搜一下", "搜一下", "搜一搜", "百度一下", "帮我找一下",
    "你找一下", "帮我查", "帮我搜", "请搜索", "搜索", "查查",
]

_SEARCH_SUFFIXES = [
    "这个新闻", "那个新闻", "这个事件", "那个事件", "这件事情", "那件事情",
    "这件事", "那件事", "这个事", "那个事", "相关内容", "相关信息",
    "的最新消息", "最新消息", "这个", "那个",
]

_TRAILING_PARTICLES = ["吗", "呢", "啊", "吧", "呀", "哦", "哈", "的"]

_TRAILING_TOPICS = "(?:的)?(?:新闻|资讯|消息|报道|动态|相关内容|相关信息)+"

_WEATHER_TAIL = [
    "大后天", "天气预报", "会不会下雨", "会不会下雪", "明天", "今天", "昨天",
    "晚上", "早上", "白天", "夜间", "会不会", "气温", "温度", "天气", "预报",
    "降雨", "下雨", "下雪", "雷雨", "台风", "降温", "升温", "怎么样", "如何",
    "怎样", "什么样", "情况", "吗", "呢", "的",
]

_CITY_LEAD_EN = [
    "search", "please tell me", "please", "tell me", "what's the", "what is the",
    "what's", "what is", "whats", "can you tell me", "can i get", "show me",
    "give me", "look up", "find out", "i want to know", "the",
]

_WEATHER_TAIL_EN = [
    "weather forecast", "forecast", "temperature", "weather", "today", "tomorrow",
    "tonight", "now", "this week", "next week", "like", "please",
]


def _has_cjk(text):
    return any("\u4e00" <= c <= "\u9fff" for c in text)


def _title_city(city):
    c = (city or "").strip().strip(" ,.")
    return " ".join(w.capitalize() for w in re.split(r"\s+", c)) if c else ""


def extract_search_query_en(text):
    """英文版：去掉 search / look up / what is 等指令词，返回真正要搜的话题"""
    q = text.strip().strip("?!.,;: ")
    ql = q.lower()
    for pre in (
        "can you search for ", "please search for ", "please search ", "search for ",
        "search ", "look up ", "find out about ", "find out ", "tell me about ",
        "please tell me about ", "please tell me ", "can you tell me about ",
        "i want to know about ", "i need to know about ", "google ",
        "what's the latest on ", "what is the latest on ", "what's happening with ",
        "give me the latest on ", "news about ", "news on ", "the latest on ",
        "what is ", "what's ",
    ):
        if ql.startswith(pre):
            q = q[len(pre):].strip()
            ql = q.lower()
            break
    q = re.sub(r"\s+(?:please|now|today|right now)$", "", q, flags=re.I).strip()
    return q.strip("?!.,;: ") or text.strip()


def extract_weather_city_en(text):
    """英文版：从问句提取城市名，如 "weather in Paris" / "Paris weather" / "search Paris weather" -> Paris"""
    q = text.strip().strip("?!.,;: ")
    ql = q.lower()
    for w in _CITY_LEAD_EN:
        if ql.startswith(w):
            q = q[len(w):].strip()
            ql = q.lower()
            break
    m = re.search(r"(?:weather|forecast)\s+(?:in|for|at)\s+([a-z][a-z0-9\s'\-.]{0,40}?)(?=\s+(?:today|tomorrow|tonight|now|this week|please)|$)", ql)
    if m:
        return _title_city(m.group(1))
    m = re.search(r"([a-z][a-z0-9\s'\-.]{0,40}?)\s+(?:weather|forecast)\b", ql)
    if m:
        return _title_city(m.group(1))
    m = re.search(r"(?:weather|forecast)\s+([a-z][a-z0-9\s'\-.]{0,30})", ql)
    if m:
        return _title_city(m.group(1))
    q2 = ql
    for w in _WEATHER_TAIL_EN:
        if q2.endswith(w):
            q2 = q2[: -len(w)].rstrip(" ,.")
            break
    return _title_city(q2) or text.strip()


def extract_search_query(text):
    """从问句里提取真正要搜的话题词，去掉"你搜索一下/帮我查一下/这个新闻/吗"等指令与语气词"""
    if not _has_cjk(text):
        return extract_search_query_en(text)
    q = text.strip().strip("。！？!?.,，、；; ")
    for pre in _SEARCH_PREFIXES:
        if q.startswith(pre):
            q = q[len(pre):].lstrip(" ，,。")
            break
    for suf in _SEARCH_SUFFIXES:
        if q.endswith(suf):
            q = q[: -len(suf)].rstrip(" ，,。")
            break
    while q and q[-1] in _TRAILING_PARTICLES:
        q = q[:-1]
    m = re.search(_TRAILING_TOPICS + "$", q)
    if m:
        stripped = q[:m.start()].rstrip(" ，,。")
        vague = re.search(r"(什么|是|有|今天|明天|昨天|今日|最近|最新|现在|当下)$", stripped)
        if len(stripped) >= 3 and not vague:
            q = stripped
    q = q.strip(" ，,。")
    return q or text.strip()


def extract_weather_city(text):
    """从问句提取城市名，如：查一下成都明天天气 -> 成都"""
    if not _has_cjk(text):
        return extract_weather_city_en(text)
    q = extract_search_query(text)
    if not q:
        return text.strip()
    changed = True
    while changed:
        changed = False
        for w in _WEATHER_TAIL:
            if q.endswith(w):
                q = q[: -len(w)].rstrip(" ，,。")
                changed = True
                break
    return q or text.strip()


def get_weather(city, days=3, lang="zh"):
    """获取城市天气预报（免key，wttr.in），返回简洁多行文本；失败返回空字符串"""
    try:
        lang_code = "en" if lang == "en" else "zh"
        resp = requests.get(
            f"https://wttr.in/{quote_plus(city)}?format=j1&lang={lang_code}",
            timeout=15,
            headers={"User-Agent": _UA},
        )
        resp.raise_for_status()
        data = resp.json()
        weather = data.get("weather", [])
        if not weather:
            return ""
        if lang_code == "en":
            labels = ["Today", "Tomorrow", "Day after"]
            lines = []
            for i, day in enumerate(weather[: min(len(labels), days)]):
                label = labels[i] if i < len(labels) else day.get("date", "")
                maxt = day.get("maxtempC", "?")
                mint = day.get("mintempC", "?")
                hourly = day.get("hourly") or [{}]
                mid = hourly[len(hourly) // 2] if len(hourly) > 1 else hourly[0]
                desc = _weather_desc(mid, lang="en")
                rain = mid.get("chanceofrain", "0")
                wind = mid.get("windspeedKmph", "0")
                lines.append(f"{label} ({day.get('date', '')}): {desc}, {mint}~{maxt}°C, rain {rain}%, wind {wind}km/h")
            return "\n".join(lines)
        labels = ["今天", "明天", "后天"]
        lines = []
        for i, day in enumerate(weather[: min(len(labels), days)]):
            label = labels[i] if i < len(labels) else day.get("date", "")
            maxt = day.get("maxtempC", "?")
            mint = day.get("mintempC", "?")
            hourly = day.get("hourly") or [{}]
            mid = hourly[len(hourly) // 2] if len(hourly) > 1 else hourly[0]
            desc = _weather_desc(mid, lang="zh")
            rain = mid.get("chanceofrain", "0")
            wind = mid.get("windspeedKmph", "0")
            lines.append(f"{label}({day.get('date', '')}): {desc}，{mint}~{maxt}℃，降雨概率{rain}%，风速{wind}km/h")
        return "\n".join(lines)
    except Exception:
        return ""


def _weather_desc(hour, lang="zh"):
    key = "lang_en" if lang == "en" else "lang_zh"
    desc = hour.get(key) or hour.get("weatherDesc") or []
    if isinstance(desc, list) and desc and isinstance(desc[0], dict):
        return (desc[0].get("value") or "").strip()
    if isinstance(desc, str):
        return desc.strip()
    return "Unknown" if lang == "en" else "未知"


_WEEKDAYS = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]
_WEEKDAYS_EN = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


def get_current_time(lang="zh"):
    now = datetime.now()
    if lang == "en":
        return now.strftime("%Y-%m-%d %H:%M:%S") + f" {_WEEKDAYS_EN[now.weekday()]}"
    return now.strftime(f"%Y年%m月%d日 {_WEEKDAYS[now.weekday()]} %H:%M:%S")


def fetch_web_content(url, max_length=5000):
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(resp.text, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = soup.get_text(separator="\n", strip=True)
        return text[:max_length]
    except Exception as e:
        return f"抓取失败: {e}"


def read_file(file_path):
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"读取失败: {e}"


def write_file(file_path, content):
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return True
    except Exception as e:
        return False


_JUNK_MARKERS = ["黄历", "日历", "历史上的今天", "老黄历", "世界时钟", "在线时间"]


def _looks_junk(query, results):
    """Bing 偶发返回与查询无关的降级结果（如搜新闻却给日历/黄历），据此判定是否需要换源重试"""
    if not results or any(m in query for m in _JUNK_MARKERS):
        return False
    if len(results) < 2:
        return False
    hit = sum(1 for r in results if any(m in (r.get("title", "") + r.get("snippet", "")) for m in _JUNK_MARKERS))
    return hit == len(results)


def search_web(query, max_results=5):
    """联网搜索（免key）：依次尝试 cn.bing.com / www.bing.com 网页版，再退回 Bing RSS，
    若某源返回的全是无关结果则自动换下一个源。
    返回 [{"title", "link", "snippet"}, ...]，全部失败时返回空列表。"""
    for host in ("cn.bing.com", "www.bing.com"):
        try:
            results = _search_bing_html(query, max_results, host=host)
            if results and not _looks_junk(query, results):
                return results
        except Exception:
            continue
    try:
        results = _search_bing_rss(query, max_results)
        if results and not _looks_junk(query, results):
            return results
    except Exception:
        pass
    return []


def _strip_html(text):
    if not text:
        return ""
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", text))).strip()


def _search_bing_html(query, max_results, host="cn.bing.com"):
    url = f"https://{host}/search?q={quote_plus(query)}&setmkt=zh-CN&setlang=zh-hans"
    resp = requests.get(url, timeout=15, headers={"User-Agent": _UA})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    for li in soup.select("li.b_algo"):
        h2 = li.select_one("h2 a")
        title = _strip_html(h2.get_text(" ", strip=True)) if h2 else ""
        link = (h2.get("href") or "").strip() if h2 else ""
        p = li.select_one(".b_caption p") or li.select_one(".b_lineclamp2, .b_lineclamp3, .b_lineclamp4")
        snippet = _strip_html(p.get_text(" ", strip=True)) if p else ""
        if title or link:
            results.append({"title": title, "link": link, "snippet": snippet})
        if len(results) >= max_results:
            break
    return results


def _search_bing_rss(query, max_results):
    url = f"https://cn.bing.com/search?q={quote_plus(query)}&format=rss&setmkt=zh-CN"
    resp = requests.get(url, timeout=15, headers={"User-Agent": _UA})
    resp.raise_for_status()
    root = ET.fromstring(resp.text)
    results = []
    for item in root.iter("item"):
        title = _strip_html(item.findtext("title") or "")
        link = (item.findtext("link") or "").strip()
        snippet = _strip_html(item.findtext("description") or "")
        if title or link:
            results.append({"title": title, "link": link, "snippet": snippet})
        if len(results) >= max_results:
            break
    return results
