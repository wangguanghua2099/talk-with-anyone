// chat.js - 聊天功能模块
const ChatModule = {
    lastTimestamp: null,

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

    addMessage(role, text, timestamp, displayName, characterId) {
        const messagesDiv = document.getElementById('messages');

        if (this.shouldShowTimeHeader(timestamp)) {
            this.addTimeHeader(timestamp);
        }

        const div = document.createElement('div');
        div.className = `message ${role}`;
        if (displayName === undefined) {
            displayName = role === 'assistant' ? (ConfigModule.get('ai_display_name', 'AI')) : (ConfigModule.get('user_name', I18N.t('you')));
        }
        const avatarHtml = AvatarModule.getAvatarHtml(role, characterId, displayName);
        div.innerHTML = `
            ${avatarHtml}
            <div class="msg-content">
                <div class="label">${displayName}</div>
                <div class="bubble">${text.replace(/\n/g, '<br>')}</div>
            </div>
        `;
        messagesDiv.appendChild(div);
        messagesDiv.scrollTop = messagesDiv.scrollHeight;
    },

    async sendMessage() {
        ReadAloudModule.stop();
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
        const resp = await fetch('/api/chat', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message })
        });
        const data = await resp.json();
        this.addMessage('assistant', data.reply, new Date().toISOString(), data.display_name, charId);
        // 停止用户消息的朗读，开始读 AI 回复
        TTSModule.stop();
        if (ConfigModule.get('tts_read_ai')) {
            await TTSModule.speakAIReply(data.reply);
        }
        ConversationModule.loadList();
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
        document.getElementById('messages').innerHTML = '';
        this.resetTimeHeader();
    }
};
