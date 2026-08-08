// tts-studio.js - 语音合成模块
const TTSStudioModule = {
    audioPath: null,

    show() {
        document.getElementById('ttsStudioModal').style.display = 'flex';
        // 加载当前引擎
        this.loadCurrentEngine();
    },

    hide() {
        document.getElementById('ttsStudioModal').style.display = 'none';
    },

    async loadCurrentEngine() {
        try {
            const resp = await fetch('/api/tts/engines');
            const data = await resp.json();
            document.getElementById('studioEngine').value = data.current || 'edge';
            await this.loadVoices();
        } catch (e) {
            console.error('加载引擎失败:', e);
        }
    },

    async loadVoices() {
        const engine = document.getElementById('studioEngine').value;
        // 切换引擎
        await fetch('/api/tts/engine', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ engine })
        });
        // 获取音色列表
        const resp = await fetch('/api/tts/voices');
        const data = await resp.json();
        const voiceSelect = document.getElementById('studioVoice');
        voiceSelect.innerHTML = '';
        data.voices.forEach(v => {
            const label = v === 'clone engine' ? I18N.t('cloneEngineVoice') : v;
            voiceSelect.innerHTML += `<option value="${v}">${label}</option>`;
        });
    },

    onEngineChange() {
        this.loadVoices();
    },

    async synthesize() {
        const text = document.getElementById('studioText').value.trim();
        const voice = document.getElementById('studioVoice').value;
        if (!text) { alert(I18N.t('enterText')); return; }

        const btn = document.getElementById('studioSynthesizeBtn');
        btn.disabled = true;
        btn.textContent = I18N.t('saving');

        try {
            const resp = await fetch('/api/tts/synthesize', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text, voice })
            });
            const data = await resp.json();
            if (data.audio) {
                this.audioPath = data.audio;
                this.showPlayer(data.audio);
            } else {
                alert(I18N.t('synthFailed') + I18N.apiError(data));
            }
        } catch (e) {
            alert(I18N.t('synthFailed') + e.message);
        } finally {
            btn.disabled = false;
            btn.textContent = I18N.t('synthesize');
        }
    },

    showPlayer(audioPath) {
        const section = document.getElementById('studioPlayerSection');
        section.style.display = 'block';
        const player = document.getElementById('studioAudioPlayer');
        player.src = audioPath + '?' + Date.now();
        player.play();
    },

    stop() {
        const player = document.getElementById('studioAudioPlayer');
        if (player) player.pause();
        fetch('/api/tts/stop', { method: 'POST' });
    },

    download() {
        if (!this.audioPath) { alert(I18N.t('noAudioToDownload')); return; }
        const defaultName = this.audioPath.split('/').pop().replace('.wav', '').replace('.mp3', '');
        const customName = prompt(I18N.t('enterAudioFilename'), defaultName);
        if (customName === null) return;
        const filename = this.audioPath.split('/').pop();
        const saveName = customName.trim() || defaultName;
        const link = document.createElement('a');
        link.href = '/api/tts/download?filename=' + encodeURIComponent(filename) + '&save_name=' + encodeURIComponent(saveName);
        link.download = saveName + '.wav';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }
};

// 字符计数
document.addEventListener('DOMContentLoaded', () => {
    const textarea = document.getElementById('studioText');
    if (textarea) {
        textarea.addEventListener('input', () => {
            document.getElementById('studioCharCount').textContent = textarea.value.length;
        });
    }
});
