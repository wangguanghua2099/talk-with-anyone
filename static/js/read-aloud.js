// read-aloud.js - 对话内容连续朗读模块（右键消息气泡 → 从该条朗读到对话末尾）
const ReadAloudModule = {
    isReading: false,
    _stopRequested: false,
    _currentItemEl: null,

    init() {
        const messagesDiv = document.getElementById('messages');
        if (messagesDiv) {
            messagesDiv.addEventListener('contextmenu', (e) => this.onContextMenu(e));
        }
        window.__onTTSStop = () => this.cancelReading();
    },

    onContextMenu(e) {
        const msgEl = e.target.closest('.message');
        if (!msgEl) return;
        const bubble = msgEl.querySelector('.bubble');
        if (!bubble || !bubble.innerText.trim()) return;
        e.preventDefault();
        e.stopPropagation();
        this.showContextMenu(e, msgEl);
    },

    showContextMenu(e, msgEl) {
        this.hideContextMenu();
        const menu = document.createElement('div');
        menu.className = 'msg-context-menu';
        const item = document.createElement('div');
        item.className = 'msg-context-item';
        item.textContent = I18N.t('readAloudMenu');
        item.addEventListener('click', () => {
            this.hideContextMenu();
            this.startFromMessage(msgEl);
        });
        menu.appendChild(item);
        menu.style.left = Math.min(e.pageX, window.innerWidth - 140) + 'px';
        menu.style.top = Math.min(e.pageY, window.innerHeight - 60) + 'px';
        document.body.appendChild(menu);

        const closeMenu = () => {
            this.hideContextMenu();
            document.removeEventListener('click', closeMenu);
        };
        setTimeout(() => document.addEventListener('click', closeMenu), 0);
    },

    hideContextMenu() {
        const existing = document.querySelector('.msg-context-menu');
        if (existing) existing.remove();
    },

    startFromMessage(msgEl) {
        this.stop();
        const allMsgs = document.querySelectorAll('#messages .message');
        const startIdx = Array.from(allMsgs).indexOf(msgEl);
        if (startIdx < 0) return;

        const items = [];
        for (let i = startIdx; i < allMsgs.length; i++) {
            const m = allMsgs[i];
            const bubble = m.querySelector('.bubble');
            const text = bubble ? bubble.innerText.trim() : '';
            if (!text) continue;
            const role = m.classList.contains('user') ? 'user' : 'assistant';
            items.push({ element: m, role, text });
        }
        if (items.length === 0) {
            alert(I18N.t('noContentToRead'));
            return;
        }
        this.run(items);
    },

    async run(items) {
        this._stopRequested = false;
        this.isReading = true;
        TTSModule.keepProgress = true;
        TTSModule.showProgress(true);
        try {
            for (let i = 0; i < items.length; i++) {
                if (this._stopRequested) break;
                const item = items[i];
                this.highlight(item.element);
                const voice = item.role === 'user'
                    ? ConfigModule.get('user_voice', '云扬')
                    : ConfigModule.get('ai_voice', '晓晓');
                try {
                    await TTSModule.speakAndWait(item.text, voice);
                } catch (e) {
                    console.error('[ReadAloud] 朗读失败:', e);
                }
            }
        } finally {
            this.isReading = false;
            this.clearHighlight();
            TTSModule.keepProgress = false;
            TTSModule.showProgress(false);
        }
    },

    highlight(el) {
        this.clearHighlight();
        if (el) {
            this._currentItemEl = el;
            el.classList.add('reading');
            el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
    },

    clearHighlight() {
        if (this._currentItemEl) {
            this._currentItemEl.classList.remove('reading');
            this._currentItemEl = null;
        }
    },

    stop() {
        this.cancelReading();
        TTSModule.stop();
    },

    cancelReading() {
        this._stopRequested = true;
        this.isReading = false;
        this.clearHighlight();
        TTSModule.keepProgress = false;
        TTSModule.showProgress(false);
    }
};
