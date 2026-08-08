// stt-studio.js - 语音转文本独立模块
const STTStudioModule = {
    ws: null,
    mediaStream: null,
    audioContext: null,
    processor: null,
    isMicOn: false,

    show() {
        document.getElementById('sttStudioModal').style.display = 'flex';
        this.updateCharCount();
    },

    hide() {
        if (this.isMicOn) this.stopMic();
        document.getElementById('sttStudioModal').style.display = 'none';
    },

    setStatus(text) {
        const el = document.getElementById('sttStatus');
        if (el) el.textContent = text;
    },

    setMicState(on) {
        const btn = document.getElementById('sttMicBtn');
        if (!btn) return;
        if (on) {
            btn.classList.add('recording');
            btn.textContent = '🔴';
            btn.title = I18N.t('sttDisableMic');
        } else {
            btn.classList.remove('recording');
            btn.textContent = '🎤';
            btn.title = I18N.t('sttEnableMic');
        }
        const wave = document.getElementById('sttWave');
        if (wave) wave.style.display = on ? 'flex' : 'none';
    },

    appendText(text) {
        const ta = document.getElementById('sttText');
        const cur = ta.value.trim();
        ta.value = cur ? cur + '\n' + text : text;
        ta.scrollTop = ta.scrollHeight;
        this.updateCharCount();
    },

    updateCharCount() {
        const ta = document.getElementById('sttText');
        if (ta) document.getElementById('sttCharCount').textContent = ta.value.length;
    },

    async toggleMic() {
        if (this.isMicOn) {
            this.stopMic();
            return;
        }

        try {
            this.setStatus(I18N.t('sttRequesting'));
            this.mediaStream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    sampleRate: 16000,
                    channelCount: 1,
                    echoCancellation: true,
                    noiseSuppression: true,
                },
            });
        } catch (err) {
            this.setStatus(window.isSecureContext ? I18N.t('sttMicDenied') : I18N.t('micNeedsHttps'));
            return;
        }

        this.ws = new WebSocket(wsUrl('/ws/voice'));
        this.isMicOn = true;
        this.setMicState(true);

        this.ws.onopen = () => {
            this.ws.send(JSON.stringify({ type: 'session.start', mode: 'transcribe' }));
            this.setStatus(I18N.t('sttListeningSentence'));
        };
        this.ws.onmessage = (e) => {
            let data;
            try { data = JSON.parse(e.data); } catch { return; }

            if (data.type === 'asr.result' && data.is_final) {
                this.appendText(data.text);
                this.setStatus(I18N.t('sttListening'));
            } else if (data.type === 'asr.error') {
                this.setStatus(I18N.t('sttRecogError') + data.message);
            } else if (data.type === 'error') {
                this.setStatus(I18N.t('sttError') + data.message);
            } else if (data.type === 'vad.speaking') {
                this.setStatus(data.speaking ? I18N.t('sttListening') : I18N.t('sttListeningSentence'));
            }
        };
        this.ws.onclose = () => {
            this.setMicState(false);
            this.setStatus(I18N.t('sttMicDisabled'));
        };
        this.ws.onerror = () => {
            this.setStatus(I18N.t('sttConnError'));
            this.stopMic();
        };

        this.audioContext = new AudioContext({ sampleRate: 16000 });
        const source = this.audioContext.createMediaStreamSource(this.mediaStream);
        this.processor = this.audioContext.createScriptProcessor(4096, 1, 1);
        this.processor.onaudioprocess = (e) => {
            const audioData = e.inputBuffer.getChannelData(0);
            const pcm16 = this.float32ToInt16(audioData);
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.ws.send(pcm16.buffer);
            }
        };
        source.connect(this.processor);
        this.processor.connect(this.audioContext.destination);
    },

    stopMic() {
        if (this.processor) {
            this.processor.disconnect();
            this.processor = null;
        }
        if (this.mediaStream) {
            this.mediaStream.getTracks().forEach(t => t.stop());
            this.mediaStream = null;
        }
        if (this.audioContext) {
            this.audioContext.close();
            this.audioContext = null;
        }
        if (this.ws) {
            try {
                if (this.ws.readyState === WebSocket.OPEN) {
                    this.ws.send(JSON.stringify({ type: 'session.stop' }));
                }
                this.ws.close();
            } catch (e) {
                console.error('[STT] 关闭连接失败:', e);
            }
            this.ws = null;
        }
        this.isMicOn = false;
        this.setMicState(false);
        this.setStatus(I18N.t('sttStatusIdle'));
    },

    float32ToInt16(float32Array) {
        const int16Array = new Int16Array(float32Array.length);
        for (let i = 0; i < float32Array.length; i++) {
            const s = Math.max(-1, Math.min(1, float32Array[i]));
            int16Array[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
        }
        return int16Array;
    },

    async upload() {
        const input = document.getElementById('sttFileInput');
        const file = input.files && input.files[0];
        if (!file) return;

        const fd = new FormData();
        fd.append('file', file);
        this.setStatus(I18N.t('sttUploading'));
        try {
            const resp = await fetch('/api/stt/transcribe', { method: 'POST', body: fd });
            const data = await resp.json();
            if (data.text) {
                this.appendText(data.text);
                this.setStatus(I18N.t('sttDone'));
            } else {
                this.setStatus(I18N.t('sttRecogFailed') + I18N.apiError(data));
            }
        } catch (e) {
            this.setStatus(I18N.t('sttUploadFailed') + e.message);
        } finally {
            input.value = '';
        }
    },

    saveTxt() {
        const text = document.getElementById('sttText').value.trim();
        if (!text) { alert(I18N.t('sttNoTextToSave')); return; }

        const now = new Date();
        const pad = n => String(n).padStart(2, '0');
        const defaultName = I18N.t('sttFilePrefix') + '_' + now.getFullYear() + pad(now.getMonth() + 1) + pad(now.getDate()) +
            '_' + pad(now.getHours()) + pad(now.getMinutes()) + pad(now.getSeconds());
        const name = prompt(I18N.t('sttEnterFilename'), defaultName);
        if (name === null) return;

        const filename = (name.trim() || defaultName).replace(/\.txt$/i, '') + '.txt';
        const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
        const link = document.createElement('a');
        link.href = URL.createObjectURL(blob);
        link.download = filename;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(link.href);
    },

    copy() {
        const text = document.getElementById('sttText').value.trim();
        if (!text) { alert(I18N.t('sttNoTextToCopy')); return; }
        navigator.clipboard.writeText(text)
            .then(() => this.setStatus(I18N.t('sttCopied')))
            .catch(() => alert(I18N.t('sttCopyFailed')));
    },

    clear() {
        document.getElementById('sttText').value = '';
        this.updateCharCount();
    }
};

document.addEventListener('DOMContentLoaded', () => {
    const ta = document.getElementById('sttText');
    if (ta) {
        ta.addEventListener('input', () => STTStudioModule.updateCharCount());
    }
});
