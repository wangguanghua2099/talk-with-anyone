// custom-voice.js - 自定义音色管理模块
const CustomVoiceModule = {
    voices: [],

    async load() {
        try {
            const resp = await fetch('/api/tts/custom-voices');
            const data = await resp.json();
            this.voices = data.voices || [];
            this.renderList();
        } catch (e) {
            console.error('加载自定义音色失败:', e);
        }
    },

    renderList() {
        const container = document.getElementById('customVoiceList');
        if (!container) return;

        if (this.voices.length === 0) {
            container.innerHTML = `<div class="conv-empty">${I18N.t('noCustomVoices')}</div>`;
            return;
        }

        let html = '';
        this.voices.forEach(v => {
            html += `
                <div class="conv-item" style="display:flex;align-items:center;justify-content:space-between;">
                    <div style="flex:1;min-width:0;">
                        <div class="conv-item-title">${this.escapeHtml(v.name)}</div>
                        <div class="conv-item-meta">
                            <span class="conv-item-time">${this.formatTime(v.created_at)}</span>
                        </div>
                    </div>
                    <button class="btn btn-outline" style="padding:2px 8px;font-size:11px;flex-shrink:0;" 
                            onclick="CustomVoiceModule.delete('${v.id}')">${I18N.t('deleteBtn')}</button>
                </div>
            `;
        });
        container.innerHTML = html;
    },

    formatTime(isoStr) {
        if (!isoStr) return '';
        const d = new Date(isoStr);
        return I18N.t('dateFormat', { m: d.getMonth() + 1, d: d.getDate() });
    },

    escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    },

    showModal() {
        document.getElementById('customVoiceModal').style.display = 'flex';
        document.getElementById('cvName').value = '';
        document.getElementById('cvAudio').value = '';
        document.getElementById('cvRefText').value = '';
        const label = document.getElementById('cvAudioFileName');
        if (label) label.textContent = I18N.t('noFileChosen');
    },

    onFileSelected() {
        const input = document.getElementById('cvAudio');
        const label = document.getElementById('cvAudioFileName');
        if (!label) return;
        const file = input.files && input.files[0];
        label.textContent = file ? file.name : I18N.t('noFileChosen');
    },

    hideModal() {
        document.getElementById('customVoiceModal').style.display = 'none';
    },

    async save() {
        const name = document.getElementById('cvName').value.trim();
        const fileInput = document.getElementById('cvAudio');
        const refText = document.getElementById('cvRefText').value.trim();

        if (!name) {
            alert(I18N.t('enterVoiceName'));
            return;
        }
        if (!fileInput.files[0]) {
            alert(I18N.t('selectRefAudio'));
            return;
        }

        const formData = new FormData();
        formData.append('name', name);
        formData.append('file', fileInput.files[0]);
        formData.append('ref_text', refText);

        try {
            const resp = await fetch('/api/tts/custom-voices', {
                method: 'POST',
                body: formData
            });
            const data = await resp.json();
            if (data.status === 'ok') {
                this.hideModal();
                await this.load();
                // 刷新音色下拉框
                if (typeof loadVoices === 'function') {
                    await loadVoices();
                }
            } else {
                alert(I18N.t('saveFailed') + I18N.apiError(data));
            }
        } catch (e) {
            alert(I18N.t('saveFailed') + e.message);
        }
    },

    async delete(voiceId) {
        if (!confirm(I18N.t('confirmDeleteVoice'))) return;
        try {
            const resp = await fetch(`/api/tts/custom-voices/${voiceId}`, {
                method: 'DELETE'
            });
            const data = await resp.json();
            if (data.status === 'deleted') {
                await this.load();
                // 刷新音色下拉框
                if (typeof loadVoices === 'function') {
                    await loadVoices();
                }
            }
        } catch (e) {
            alert(I18N.t('deleteFailed') + e.message);
        }
    }
};
