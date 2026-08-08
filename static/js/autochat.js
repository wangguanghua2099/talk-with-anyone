// autochat.js - AI 自聊功能模块
const AutoChatModule = {
    isRunning: false,
    lastDisplayCount: 0,
    pollTimer: null,

    async start() {
        const input = document.getElementById('userInput');
        const message = input.value.trim();
        if (!message) { alert(I18N.t('enterMsgToAutoChat')); return; }
        input.value = '';
        if (typeof autoGrowInput === 'function') autoGrowInput(input);
        this.lastDisplayCount = 0;
        document.getElementById('autoChatBtn').style.display = 'none';
        document.getElementById('stopAutoChatBtn').style.display = 'inline-block';
        document.getElementById('autoChatIndicator').classList.add('active');
        const resp = await fetch('/api/auto-chat/start', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ message })
        });
        const data = await resp.json();
        if (data.error || data.error_code) {
            alert(I18N.t('autoChatStartFailed') + I18N.apiError(data));
            this.resetButtons();
            return;
        }
        this.isRunning = true;
        this.poll();
    },

    async stop() {
        await fetch('/api/auto-chat/stop', { method: 'POST' });
        this.isRunning = false;
        this.resetButtons();
    },

    resetButtons() {
        document.getElementById('autoChatBtn').style.display = 'inline-block';
        document.getElementById('stopAutoChatBtn').style.display = 'none';
        document.getElementById('autoChatIndicator').classList.remove('active');
    },

    async poll() {
        if (!this.isRunning) return;
        const resp = await fetch('/api/auto-chat/status');
        const data = await resp.json();
        if (data.history && data.history.length > this.lastDisplayCount) {
            for (let i = this.lastDisplayCount; i < data.history.length; i++) {
                const msg = data.history[i];
                const charSel = document.getElementById('characterSelect');
                const charId = charSel ? charSel.value : '';
                ChatModule.addMessage(
                    msg.role === 'user' ? 'user' : 'assistant',
                    msg.content,
                    undefined,
                    undefined,
                    charId
                );
            }
            this.lastDisplayCount = data.history.length;
        }
        if (data.is_running) {
            this.pollTimer = setTimeout(() => this.poll(), 1000);
        } else {
            this.resetButtons();
        }
    }
};
