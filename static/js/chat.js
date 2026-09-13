// chat.js - 聊天功能模块
const ChatModule = {
    lastTimestamp: null,
    // 分句 TTS 流水状态
    _ttsGen: 0,          // 递增代数：新消息/清空时 +1，使旧流水自动作废
    _ttsQueue: [],       // 待合成的句子批次
    _ttsBuf: "",         // 分句缓冲（未凑成句的文本）
    _ttsBatch: "",       // 批次缓冲（凑 48 字成一批送 TTS）
    _ttsNoMore: false,   // 本轮流式已结束
    _ttsSending: false,  // 当前有句子在合成
    _ttsStarted: false,  // 本轮是否已开始朗读（首句会让位给用户朗读）
    _ttsEnabled: false,

    formatTime(ts) {
        if (!ts) return null;
        const date = new Date(ts);
        const now = new Date();
        const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
        const msgDay = new Date(date.getFullYear(), date.getMonth(), date.getDate());

        const hh = String(date.getHours()).padStart(2, '0');
        const mm = String(date.getMinutes()).padStart(2, '0');

        if (msgDay.getTime() === today.getTime()) {
            return I18N.t('todayTime', { h: hh, mi: mm });
        }
        const yesterday = new Date(today);
        yesterday.setDate(yesterday.getDate() - 1);
        if (msgDay.getTime() === yesterday.getTime()) {
            return I18N.t('yesterdayTime', { h: hh, mi: mm });
        }
        return I18N.t('dateTimeFormat', { m: date.getMonth() + 1, d: date.getDate(), h: hh, mi: mm });
    },

    shouldShowTimeHeader(ts) {
        if (!ts) return false;
        if (!this.lastTimestamp) {
            this.lastTimestamp = ts;
            return true;
        }
        const prev = new Date(this.lastTimestamp);
        const curr = new Date(ts);
        const diffMs = curr - prev;
        if (diffMs > 60000) {
            this.lastTimestamp = ts;
            return true;
        }
        return false;
    },

    resetTimeHeader() {
        this.lastTimestamp = null;
    },

    addTimeHeader(ts) {
        const messagesDiv = document.getElementById('messages');
        const timeStr = this.formatTime(ts);
        if (!timeStr) return;
        const div = document.createElement('div');
        div.className = 'time-header';
        div.innerHTML = `<span>${timeStr}</span>`;
        messagesDiv.appendChild(div);
    },

    _newMessageEl(role, timestamp, displayName, characterId) {
        const messagesDiv = document.getElementById('messages');

        if (this.shouldShowTimeHeader(timestamp)) {
            this.addTimeHeader(timestamp);
        }

        const div = document.createElement('div');
        div.className = `message ${role}`;
        if (displayName === undefined) {
            displayName = role === 'assistant' ? (ConfigModule.get('ai_display_name', 'AI')) : (ConfigModule.get('user_name', I18N.t('you')));
        }
        // 头像 HTML 由内部模块生成（可含 <img>），保留 innerHTML 注入
        div.innerHTML = AvatarModule.getAvatarHtml(role, characterId, displayName);
        // 消息文本用 textContent 写入，避免未转义内容被当成 HTML 执行
        const content = document.createElement('div');
        content.className = 'msg-content';
        const label = document.createElement('div');
        label.className = 'label';
        label.textContent = displayName;
        const bubble = document.createElement('div');
        bubble.className = 'bubble';
        const textEl = document.createElement('span');
        textEl.className = 'msg-text';
        bubble.appendChild(textEl);
        content.appendChild(label);
        content.appendChild(bubble);
        div.appendChild(content);
        return { el: div, textEl };
    },

    addMessage(role, text, timestamp, displayName, characterId) {
        const messagesDiv = document.getElementById('messages');
        const { el, textEl } = this._newMessageEl(role, timestamp, displayName, characterId);
        textEl.textContent = text;
        messagesDiv.appendChild(el);
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
    },

    // 流式开场：创建一条空的 assistant 消息，文本由 TypeWriter 逐字填充
    createEmpty(role, timestamp, displayName, characterId) {
        const messagesDiv = document.getElementById('messages');
        const { el, textEl } = this._newMessageEl(role, timestamp, displayName, characterId);
        messagesDiv.appendChild(el);
        return { el, textEl };
    },

    async sendMessage() {
        ReadAloudModule.stop();
        TypeWriter.skipAll();
        this._resetTTSStream();
        this._ttsEnabled = !!ConfigModule.get('tts_read_ai');
        const input = document.getElementById('userInput');
        const message = input.value.trim();
        if (!message) return;
        const userName = ConfigModule.get('user_name', I18N.t('you'));
        const charSel = document.getElementById('characterSelect');
        const charId = charSel ? charSel.value : '';
        this.addMessage('user', message, new Date().toISOString(), userName, charId);
        input.value = '';
        if (typeof autoGrowInput === 'function') autoGrowInput(input);
        if (ConfigModule.get('tts_read_user')) {
            TTSModule.speakUserMessage(message);  // 后台并发朗读，不等
        }
        try {
            const resp = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message, stream: true })
            });
            if (!resp.ok || !resp.body) throw new Error('HTTP ' + resp.status);

            const reader = resp.body.getReader();
            const decoder = new TextDecoder();
            let sseBuf = '', ctrl = null, doneData = null;
            const handleSSE = (payload) => {
                if (payload.error) throw new Error(payload.error);
                if (payload.delta) {
                    if (!ctrl) {
                        const { el, textEl } = this.createEmpty('assistant', new Date().toISOString(), payload.display_name, charId);
                        ctrl = TypeWriter.create(textEl, {
                            scrollEl: document.getElementById('messages'),
                            clickToSkipEl: el,
                        });
                    }
                    ctrl.push(payload.delta);
                    if (this._llmFirstTokenAt === null) this._llmFirstTokenAt = performance.now();
                    this._onTTSText(payload.delta);   // 边生成边分句送 TTS
                }
                if (payload.done) doneData = payload;
            };
            while (true) {
                const { done, value } = await reader.read();
                if (done) break;
                sseBuf += decoder.decode(value, { stream: true });
                let idx;
                while ((idx = sseBuf.indexOf('\n\n')) >= 0) {
                    const raw = sseBuf.slice(0, idx).trim();
                    sseBuf = sseBuf.slice(idx + 2);
                    if (!raw.startsWith('data:')) continue;
                    let payload;
                    try {
                        payload = JSON.parse(raw.slice(5));
                    } catch (e) {
                        continue;
                    }
                    handleSSE(payload);
                }
            }
            if (ctrl) ctrl.finish();
            // 剩余未成句文本收尾进入分句 TTS 流水（流水按句合成、按序无缝播放）
            this._endTTSText();
        } catch (e) {
            console.error('[Chat] 发送失败:', e);
            this._endTTSText();
            this.addMessage('assistant', '调用失败: ' + e.message, new Date().toISOString());
        }
        ConversationModule.loadList();
    },

    // ===== 分句 TTS 流水：LLM 出字时同步凑句合成，不等全文 =====

    // 用户点击"停止朗读"等场景：作废整条流水（在途句子放行、清空队列、
    // 后续 LLM 文字不再送 TTS）。正在播放的音频由 TTSModule.stop() 负责停止。
    stopTTSStream() {
        this._ttsGen++;
        this._ttsQueue = [];
        this._ttsBuf = "";
        this._ttsBatch = "";
        this._ttsNoMore = true;
        this._ttsSending = false;
    },

    _resetTTSStream() {
        this._ttsGen++;
        this._ttsQueue = [];
        this._ttsBuf = "";
        this._ttsBatch = "";
        this._ttsNoMore = false;
        this._ttsSending = false;
        this._ttsStarted = false;
        this._llmFirstTokenAt = null;
        this._awaitFirstAudio = false;
        if (TTSModule.player) TTSModule.player.markStreamStart();
    },

    // 喂入流式增量，切出完整句并入批（分句规则与后端 agent/sentence.py 一致）
    _onTTSText(delta) {
        if (!this._ttsEnabled || this._ttsNoMore) return;
        this._ttsBuf += delta;
        while (true) {
            const buf = this._ttsBuf;
            let cutAt = -1;
            for (let i = 0; i < buf.length; i++) {
                const ch = buf[i];
                const hard = "。！？…；;\n".includes(ch);
                const soft = ".!?".includes(ch);
                if (!hard && !soft) continue;
                if (i + 1 < 4) continue;                     // 最小句长 4 字
                if (soft) {
                    if (i + 1 >= buf.length) return;         // 半角标点在末尾：等下一字（防切断小数/缩写）
                    if (!/\s/.test(buf[i + 1])) continue;
                }
                cutAt = i + 1;
                break;
            }
            if (cutAt < 0) {
                if (buf.length >= 80) {                      // 无标点超长：强制成句
                    this._ttsBatch += buf.slice(0, 80);
                    this._ttsBuf = buf.slice(80);
                    this._ttsQueue.push(this._ttsBatch);
                    this._ttsBatch = "";
                    this._pumpTTS();
                    continue;
                }
                return;
            }
            const sentence = buf.slice(0, cutAt);
            this._ttsBuf = buf.slice(cutAt);
            this._ttsBatch += sentence;
            // 首句立即成批（尽快出声），之后凑满 48 字成一批
            if (this._ttsBatch.length >= 36) {
                this._ttsQueue.push(this._ttsBatch);
                this._ttsBatch = "";
                this._pumpTTS();
            }
        }
    },

    _endTTSText() {
        if (this._ttsBatch.trim()) {
            this._ttsQueue.push(this._ttsBatch);
            this._ttsBatch = "";
        }
        this._ttsNoMore = true;
        this._pumpTTS();
    },

    _pumpTTS() {
        if (this._ttsSending) return;
        const gen = this._ttsGen;
        const text = this._ttsQueue.shift();
        if (text === undefined) return;
        this._ttsSending = true;
        if (!this._ttsStarted) {
            this._ttsStarted = true;
            TTSModule.stop();                // 停掉用户消息的朗读，让位给 AI 语音
            TTSModule.keepProgress = true;   // 整轮朗读期间进度条常驻
            if (TTSModule.player) {
                // 出声计时：AI 语音第一个音频块实际出声时上报
                //（LLM首token时刻 → 此刻 = 用户"看到文字"到"听到声音"的间隔）
                const gen = this._ttsGen;
                TTSModule.player.markStreamStart();
                this._awaitFirstAudio = true;
                TTSModule.player.onFirstAudio = (audibleAt) => {
                    if (!this._awaitFirstAudio || this._llmFirstTokenAt === null) return;
                    if (gen !== this._ttsGen) return;
                    this._awaitFirstAudio = false;
                    const lat = Math.round(audibleAt - this._llmFirstTokenAt);
                    console.log(`[Chat] LLM首token→出声: ${lat}ms`);
                    TTSModule.sendStats({ type: 'client_stats', llm_first_token_to_audio_ms: lat });
                };
            }
        }
        TTSModule.speakSentence(text, ConfigModule.get('ai_voice', '晓晓'))
            .catch((e) => console.error('[Chat] 句子合成失败:', e))
            .finally(() => {
                this._ttsSending = false;
                if (gen !== this._ttsGen) return;    // 已有新消息，旧流水作废
                if (this._ttsNoMore && this._ttsQueue.length === 0 && !this._ttsBatch.trim()) {
                    TTSModule.keepProgress = false;
                    TTSModule.showProgress(false);
                }
                this._pumpTTS();
            });
    },

    async clearCurrent() {
        if (!confirm(I18N.t('confirmClearChat'))) return;
        const convId = ConversationModule.currentId;
        if (!convId) { this.clear(); return; }
        try {
            await fetch(`/api/conversations/${convId}/clear`, { method: 'POST' });
        } catch (e) {
            console.error('[Chat] 清空对话失败:', e);
        }
        this.clear();
        ConversationModule.loadList();
    },

    clear() {
        ReadAloudModule.stop();
        TypeWriter.skipAll();
        this._resetTTSStream();
        document.getElementById('messages').innerHTML = '';
        this.resetTimeHeader();
    }
};
