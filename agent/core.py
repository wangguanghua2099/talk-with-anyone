import re
import time

from .llm import LLMClient
from .conversation import ConversationManager
from .tools import get_current_time, fetch_web_content


class AgentCore:
    def __init__(self, config):
        self.config = config
        self.llm = LLMClient(config)
        self.conv_manager = ConversationManager(
            os.path.join(os.path.dirname(os.path.dirname(__file__)))
        )
        if not self.conv_manager.current_id:
            self.conv_manager.create()
        self.history = self.conv_manager.get_messages(self.conv_manager.current_id)

    def _ensure_conv(self):
        conv = self.conv_manager.get_current()
        if not conv:
            self.conv_manager.create()
            conv = self.conv_manager.get_current()
        return conv

    def _save_turn(self, conv_id, user_message, reply):
        display_name = self.config.get("ai_display_name", "AI")
        user_name = self.config.get("user_name", "你")
        current_char_id = self.config.get("current_character_id", "default")
        self.conv_manager.add_message(conv_id, "user", user_message, display_name=user_name, character_id=current_char_id)
        self.conv_manager.add_message(conv_id, "assistant", reply, display_name=display_name, character_id=current_char_id)
        self.history = self.conv_manager.get_messages(conv_id)

    async def _prepare_messages(self, user_message):
        """构建本轮 LLM 消息列表：系统提示词（含日期/用户设定/工具注入）+ 最近历史 + 本轮用户消息"""
        system_prompt = self.config.get("ai_role_prompt", "你是一个友好的助手。")
        # 根据用户消息语言选择中文/英文处理，否则英文用户查天气/新闻会因关键词匹配不到而失败
        from .tools import get_current_time, _has_cjk
        is_zh = _has_cjk(user_message)
        lang = "zh" if is_zh else "en"
        # 把当前日期时间注入系统提示词，否则模型无法获知"今天"（训练数据截止）。
        # 这样询问日期/星期/时间时模型能按真实日期作答。
        # 同时明确禁止在正常回复中报时：部分模型会把注入的日期复读在回复开头
        if lang == "zh":
            system_prompt = (
                f"{system_prompt}\n\n（当前日期时间：{get_current_time('zh')}"
                f"。仅用于回答日期/星期/时间类问题，回复中不要报出日期时间）"
            )
        else:
            system_prompt = (
                f"{system_prompt}\n\n(Current date & time: {get_current_time('en')}"
                f". For answering date/time questions only; do not mention "
                f"the date or time in normal replies)"
            )

        # 注入用户设定（姓名/角色设定），否则模型不知道在和谁说话
        user_name = (self.config.get("user_name") or "").strip()
        user_role = (self.config.get("user_role_prompt") or "").strip()
        if user_name or user_role:
            if lang == "zh":
                parts = []
                if user_name:
                    parts.append(f"用户叫{user_name}")
                if user_role:
                    parts.append(f"关于用户的设定：{user_role}")
                system_prompt = f"{system_prompt}\n\n（{'；'.join(parts)}）"
            else:
                parts = []
                if user_name:
                    parts.append(f"User's name is {user_name}")
                if user_role:
                    parts.append(f"About the user: {user_role}")
                system_prompt = f"{system_prompt}\n\n({' ; '.join(parts)})"

        # 天气类问题优先走天气接口（免key），拿不到再退回联网搜索
        weather_keywords_zh = ["天气", "气温", "温度", "预报", "降雨", "下雨", "下雪", "台风", "降温", "升温", "阴晴"]
        weather_keywords_en = ["weather", "forecast", "temperature", "rain", "snow", "sunny", "cloudy",
                               "windy", "storm", "thunder", "typhoon", "humidity", "precipitation", "heat wave"]
        search_keywords_zh = ["新闻", "最新", "实时", "热点", "热搜", "最近", "快讯", "时事", "搜索", "查一下", "搜一下", "百度一下"]
        search_keywords_en = ["search", "news", "latest", "breaking", "headlines", "look up", "google", "find out", "live updates"]

        msg_lower = user_message.lower()
        weather_hit = any(k in user_message for k in weather_keywords_zh) if is_zh \
            else any(k in msg_lower for k in weather_keywords_en)
        search_hit = any(k in user_message for k in search_keywords_zh) if is_zh \
            else any(k in msg_lower for k in search_keywords_en)

        handled = False
        if self.config.get("web_search_enabled", True):
            # 天气类问题优先走天气接口（免key），拿不到再退回联网搜索
            if weather_hit:
                import asyncio
                from .tools import get_weather, extract_weather_city
                city = extract_weather_city(user_message)
                report = await asyncio.to_thread(get_weather, city, lang=lang)
                if report:
                    if lang == "zh":
                        system_prompt = f"{system_prompt}\n\n（天气预报（{city}）：\n{report}）"
                    else:
                        system_prompt = f"{system_prompt}\n\n(Weather forecast for {city}:\n{report})"
                    handled = True

            # 用户消息含"需要实时信息"的关键词时，自动联网搜索并注入上下文供模型参考
            if not handled and search_hit:
                import asyncio
                from .tools import search_web, extract_search_query
                query = extract_search_query(user_message)
                results = await asyncio.to_thread(search_web, query)
                if results:
                    if lang == "zh":
                        lines = ["（实时搜索结果，供回答参考；若与用户问题无关可忽略）："]
                    else:
                        lines = ["(Live search results for reference; ignore if irrelevant to the question):"]
                    for i, r in enumerate(results, 1):
                        title = r.get("title") or ("无标题" if lang == "zh" else "(no title)")
                        link = r.get("link") or ""
                        snippet = r.get("snippet") or ""
                        lines.append(f"{i}. {title}")
                        if link:
                            lines.append(f"   链接：{link}" if lang == "zh" else f"   Link: {link}")
                        if snippet:
                            lines.append(f"   摘要：{snippet}" if lang == "zh" else f"   Snippet: {snippet}")
                    system_prompt = f"{system_prompt}\n\n" + "\n".join(lines)

        # 本地知识库（RAG）检索注入：开关开启且已激活知识库时生效。
        # 嵌入服务未运行 / 未建库 / 模型不匹配等情况一律静默跳过，绝不阻塞聊天。
        self.last_rag_sources = []
        if self.config.get("rag_enabled"):
            try:
                from rag.service import get_rag_service
                svc = get_rag_service()
                active_kb = (self.config.get("rag_active_kb") or "").strip()
                top_k = int(self.config.get("rag_top_k") or 4)
                hits = await svc.search(user_message, top_k=top_k,
                                        active_kb=active_kb, config=self.config)
            except Exception as e:
                print(f"[RAG] 检索跳过: {e}")
                hits = []
            if hits:
                self.last_rag_sources = hits
                kb_name = hits[0].get("kb_name", "")
                if lang == "zh":
                    header = (f"（以下是本地知识库《{kb_name}》中与用户问题最相关的原文片段。"
                              f"回答时必须优先依据这些片段；片段未涵盖的内容请明确说明"
                              f"“资料中没有提到”，不要凭空编造）：")
                else:
                    header = ("(The following are the most relevant excerpts from local "
                              f"knowledge base '{kb_name}'. Base your answer on them first; "
                              "explicitly say so when they don't cover something, "
                              "do not fabricate):")
                lines = [header]
                for h in hits:
                    chapter = (h.get("meta") or {}).get("chapter")
                    tag = f"（{chapter}）" if chapter and lang == "zh" else (
                        f" ({chapter})" if chapter else "")
                    lines.append(f"[{h['rank']}]{tag} {h['text']}")
                system_prompt = f"{system_prompt}\n\n" + "\n\n".join(lines)
        messages = [{"role": "system", "content": system_prompt}]
        for msg in self.history[-20:]:
            messages.append({"role": "user", "content": msg["content"]} if msg["role"] == "user" else {"role": "assistant", "content": msg["content"]})
        messages.append({"role": "user", "content": user_message})
        return messages

    async def chat(self, user_message, config=None):
        if config:
            self.config = config

        conv = self._ensure_conv()
        messages = await self._prepare_messages(user_message)

        reply = await self.llm.chat(messages)
        reply = strip_datetime_prefix(reply)
        self._save_turn(conv["id"], user_message, reply)
        return reply

    async def chat_stream(self, user_message, config=None):
        """流式对话：逐段 yield 文本增量。

        结束后（含中途被打断的 CancelledError）把已生成的回复存入对话记录，
        保证历史与实际说出的内容一致。
        """
        if config:
            self.config = config

        conv = self._ensure_conv()
        messages = await self._prepare_messages(user_message)

        t0 = time.perf_counter()
        first_at = None
        parts = []
        flt = _DatetimePrefixFilter()
        try:
            async for delta in self.llm.chat_stream(messages):
                if first_at is None:
                    first_at = time.perf_counter()
                    print(f"[LLM] 首token延迟: {first_at - t0:.2f}s")
                out = flt.feed(delta)
                if out:
                    parts.append(out)
                    yield out
            # 正常结束：放行仍被扣住的内容（如整条只有时间的极短回复）
            tail = flt.flush()
            if tail:
                parts.append(tail)
                yield tail
        finally:
            if first_at is not None:
                print(f"[LLM] 回复完成: {len(parts)} 段 / {len(''.join(parts))} 字, "
                      f"总耗时 {time.perf_counter() - t0:.2f}s")
            reply = "".join(parts).strip()
            if reply:
                self._save_turn(conv["id"], user_message, reply)

    def clear_history(self):
        conv = self.conv_manager.get_current()
        if conv:
            self.conv_manager.clear_messages(conv["id"])
            self.history = []


import os


# 模型偶尔会把系统提示词里注入的"当前日期时间"复读在回复开头
# （如"（2026-9-13 16：26：30）""2026年09月13日 星期日 16:26:30，"），
# 导致字幕/朗读出现与对话无关的报时。这里在输出侧做前缀过滤，三个前端同时生效。
#
# _DATETIME_PREFIX_RE：完整日期时间前缀（必须含完整日期+时间才判定为报时，
#                      避免误伤"2026年9月13日是周一"这类正常内容）
# _DATETIME_PREFIX_MAYBE_RE：可能是日期前缀的"前半截"（跨 chunk 时先扣住等待）
_DATETIME_PREFIX_RE = re.compile(
    r'^[\s（(]{0,2}'
    r'\d{4}\s*[年\-/.]\s*\d{1,2}\s*[月\-/.]\s*\d{1,2}\s*日?'
    r'(?:\s*星期[一二三四五六日天]|\s*周[一二三四五六日天])?'
    r'[\s，,]*'
    r'(?:\d{1,2}[:：]\d{1,2}(?:[:：]\d{1,2})?|\d{1,2}[点时](?:\d{1,2}分?)?)'
    r'[\s，,。.!！?？;；]*'
    r'[）)]?'
)
_DATETIME_PREFIX_MAYBE_RE = re.compile(
    r'^[\s（(]{0,2}'
    r'(?:\d{1,4}'
    r'(?:\s*[年\-/.]'
    r'(?:\d{1,2}'
    r'(?:\s*[月\-/.]'
    r'(?:\d{1,2}\s*日?)?'
    r')?)?)?'
    r')?'
    r'(?:\s*星期[一二三四五六日天]|\s*周[一二三四五六日天])?'
    r'[\s，,]*'
    r'(?:\d{0,2}'
    r'(?:[:：点时]\d{0,2}'
    r'(?:[:：分]\s*\d{0,2}\s*秒?)?'
    r')?)?'
    r'[\s，,。.!！?？;；]*'
    r'[）)]?$'
)


def strip_datetime_prefix(text: str) -> str:
    """非流式回复：丢弃开头的日期时间前缀（后面还有内容才丢）"""
    m = _DATETIME_PREFIX_RE.match(text or "")
    if m:
        rest = text[m.end():]
        if rest.strip():
            return rest
    return text or ""


class _DatetimePrefixFilter:
    """流式回复过滤：丢弃回复开头的日期时间前缀。

    决策规则（每个增量到达时）：
      · 完整日期前缀之后已有内容 → 确认是复读的报时，丢弃前缀放行其余；
      · 完整匹配失败但"前半截"仍可能是日期（跨 chunk）→ 继续扣住；
      · 两者都不匹配 → 开头不是日期，全部立即放行（几乎不影响首字延迟）。
    整条回复只有日期没有内容时（回答"现在几点"）在流结束时原样放行，
    不会把正常回答滤空。
    """

    _HOLD_LIMIT = 64   # 扣住字符数上限（防异常超长前缀），超过即裁决

    # 日期前缀之后仍可能是日期延续的字符（如"16：26"之后的"：30"）
    _EXTENDABLE = set("0123456789０１２３４５６７８９：:点时分秒 ，,.。")

    def __init__(self):
        self._buf = ""
        self._checking = True

    def _release(self, drop: int) -> str:
        self._checking = False
        out = self._buf[drop:]
        self._buf = ""
        return out

    def feed(self, delta: str) -> str:
        if not self._checking:
            return delta
        self._buf += delta
        m = _DATETIME_PREFIX_RE.match(self._buf)
        if m and len(self._buf) > m.end():
            rest = self._buf[m.end():]
            if (rest[0] in self._EXTENDABLE
                    and len(self._buf) < self._HOLD_LIMIT
                    and _DATETIME_PREFIX_MAYBE_RE.match(self._buf)):
                return ""    # 可能是"：30"这类日期延续，继续扣住
            return self._release(m.end())       # 明确正文：确认是复读报时，丢弃
        if not m and not _DATETIME_PREFIX_MAYBE_RE.match(self._buf):
            return self._release(0)             # 开头就不是日期：全部放行
        if len(self._buf) >= self._HOLD_LIMIT:
            end = m.end() if m else len(self._buf)
            return self._release(end)           # 异常长的疑似日期：丢弃已匹配部分
        return ""                               # 继续扣住，等下一个增量

    def flush(self) -> str:
        """流结束：仍未裁决（整条只有日期/极短回复）→ 原样放行"""
        if not self._checking:
            return ""
        return self._release(0)
