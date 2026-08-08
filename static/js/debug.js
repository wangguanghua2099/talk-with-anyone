// debug.js - 调试日志模块
const DebugModule = {
    toggle() {
        const panel = document.getElementById('debugPanel');
        panel.classList.toggle('active');
        if (panel.classList.contains('active')) {
            this.refresh();
        }
    },

    async refresh() {
        const resp = await fetch('/api/debug/logs');
        const data = await resp.json();
        const container = document.getElementById('debugLogs');
        container.innerHTML = '';
        data.logs.forEach(log => {
            const div = document.createElement('div');
            div.className = 'debug-log';
            div.innerHTML = `
                <span class="timestamp">${log.timestamp}</span>
                <span>${I18N.t('debugBackendLabel')}: ${log.backend}</span>
                ${log.error ? `<span style="color:#FF3B30;margin-left:8px;">${I18N.t('errorLabel')}: ${log.error}</span>` : ''}
                <div class="section">
                    <div class="section-title">${I18N.t('debugReqLabel')}:</div>
                    <pre>${JSON.stringify(log.request, null, 2)}</pre>
                </div>
                <div class="section">
                    <div class="section-title">${I18N.t('debugRawLabel')}:</div>
                    <pre>${JSON.stringify(log.raw_response, null, 2)}</pre>
                </div>
                <div class="section">
                    <div class="section-title">${I18N.t('debugReplyLabel')}:</div>
                    <pre>${log.response || ''}</pre>
                </div>
            `;
            container.appendChild(div);
        });
    },

    async clear() {
        await fetch('/api/debug/clear', { method: 'POST' });
        document.getElementById('debugLogs').innerHTML = '';
    }
};
