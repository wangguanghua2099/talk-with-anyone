import asyncio


class AutoChatEngine:
    def __init__(self, llm, tts, config):
        self.llm = llm
        self.tts = tts
        self.config = config
        self.conv_manager = None
        self.sync_history = None
        self.is_running = False
        self.messages_for_llm = []
        self.display_history = []
        self.max_rounds = 50
        self.current_round = 0

    async def start(self, user_message, on_round=None):
        self.is_running = True
        self.messages_for_llm = []
        self.display_history = []
        self.current_round = 0

        if self.conv_manager:
            conv = self.conv_manager.get_current()
            if conv is None:
                conv = self.conv_manager.create()
            self.conv_id = conv["id"]
        else:
            self.conv_id = None

        ai_role = self.config.get("ai_role_prompt", "你是一个友好的助手。")
        user_role = self.config.get("user_role_prompt", "用户")

        system_prompt = f"""你是一个AI，需要和用户进行一场完整的对话，对话中由你交替扮演两个角色。

AI角色设定：{ai_role}
用户角色设定：{user_role}

对话规则：
- 每次只输出一条回复，不加任何前缀、重写、标记或解释，直接说该角色要说的话。
- 每一轮消息里都会明确告诉你要以哪个角色身份说话，你只需严格遵守那一条指令回复即可。
- 扮演AI角色时，以该角色的口吻回应；扮演用户角色时，以用户设定主动提问或回应。

现在，用户先对AI角色说了话，请以AI角色身份回复。"""

        from agent.tools import get_current_time
        system_prompt = f"{system_prompt}\n\n（当前日期时间：{get_current_time()}）"

        self.messages_for_llm.append({"role": "system", "content": system_prompt})
        self.messages_for_llm.append({"role": "user", "content": f"用户说：{user_message}"})

        if self.config.get("tts_read_user"):
            await self.tts.speak(user_message, self.config.get("user_voice"))

        self.display_history.append({"role": "user", "content": user_message})

        if self.conv_id:
            self.conv_manager.add_message(
                self.conv_id, "user", user_message,
                display_name=self.config.get("user_name", "你"),
                character_id=self.config.get("current_character_id", "default"),
            )

        if on_round:
            await on_round("user", user_message)

        while self.is_running and self.current_round < self.max_rounds:
            self.current_round += 1

            reply = await self.llm.chat(self.messages_for_llm)

            self.messages_for_llm.append({"role": "assistant", "content": reply})

            if self.current_round % 2 == 1:
                role = "ai"
                if self.config.get("tts_read_ai"):
                    await self.tts.speak(reply, self.config.get("ai_voice"))
            else:
                role = "user"
                if self.config.get("tts_read_user"):
                    await self.tts.speak(reply, self.config.get("user_voice"))

            self.display_history.append({"role": role, "content": reply})

            if self.conv_id:
                db_role = "assistant" if role == "ai" else "user"
                display_name = (
                    self.config.get("ai_display_name", "AI")
                    if db_role == "assistant"
                    else self.config.get("user_name", "你")
                )
                self.conv_manager.add_message(
                    self.conv_id, db_role, reply,
                    display_name=display_name,
                    character_id=self.config.get("current_character_id", "default"),
                )

            if on_round:
                await on_round(role, reply)

            if self.current_round % 2 == 1:
                next_prompt = "现在请你以用户角色身份说话，说一句用户会对AI说的话。"
            else:
                next_prompt = "现在请你以AI角色身份回复用户的话。"

            self.messages_for_llm.append({"role": "user", "content": next_prompt})

        self.is_running = False

        # 自聊结束后，把本次写入的对话内容同步回 agent.history，
        # 这样无需刷新页面，后续正常聊天也能接着自聊的上下文
        if self.sync_history and self.conv_id:
            try:
                self.sync_history(self.conv_id)
            except Exception:
                pass

    def stop(self):
        self.is_running = False
        self.tts.stop()
