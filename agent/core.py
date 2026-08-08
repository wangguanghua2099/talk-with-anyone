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

    async def chat(self, user_message, config=None):
        if config:
            self.config = config

        conv = self.conv_manager.get_current()
        if not conv:
            self.conv_manager.create()
            conv = self.conv_manager.get_current()

        system_prompt = self.config.get("ai_role_prompt", "你是一个友好的助手。")
        # 根据用户消息语言选择中文/英文处理，否则英文用户查天气/新闻会因关键词匹配不到而失败
        from .tools import get_current_time, _has_cjk
        is_zh = _has_cjk(user_message)
        lang = "zh" if is_zh else "en"
        # 把当前日期时间注入系统提示词，否则模型无法获知"今天"（训练数据截止）。
        # 这样询问日期/星期/时间时模型能按真实日期作答。
        if lang == "zh":
            system_prompt = f"{system_prompt}\n\n（当前日期时间：{get_current_time('zh')}）"
        else:
            system_prompt = f"{system_prompt}\n\n(Current date & time: {get_current_time('en')})"

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
        messages = [{"role": "system", "content": system_prompt}]
        for msg in self.history[-20:]:
            messages.append({"role": "user", "content": msg["content"]} if msg["role"] == "user" else {"role": "assistant", "content": msg["content"]})
        messages.append({"role": "user", "content": user_message})

        reply = await self.llm.chat(messages)

        display_name = self.config.get("ai_display_name", "AI")
        user_name = self.config.get("user_name", "你")
        current_char_id = self.config.get("current_character_id", "default")
        self.conv_manager.add_message(conv["id"], "user", user_message, display_name=user_name, character_id=current_char_id)
        self.conv_manager.add_message(conv["id"], "assistant", reply, display_name=display_name, character_id=current_char_id)
        self.history = self.conv_manager.get_messages(conv["id"])
        return reply

    def clear_history(self):
        conv = self.conv_manager.get_current()
        if conv:
            self.conv_manager.clear_messages(conv["id"])
            self.history = []


import os
