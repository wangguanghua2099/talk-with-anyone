// tts.js - TTS 朗读功能模块
const TTSModule = {
    audioPlayer: null,
    progressInterval: null,
    ws: null,
    audioContext: null,
    isStreaming: false,
    uttSeq: 0,
    uttEnd: null,
    keepProgress: false,
    playingViaElement: false,

    init() {
        this.audioPlayer = document.getElementById('audioPlayer');
    },

    getWebSocket() {
        if (this.ws && this.ws.readyState === WebSocket.OPEN) {
            return this.ws;
        }
        return new Promise((resolve, reject) => {
            const ws = new WebSocket(wsUrl('/ws/tts-stream'));
            ws.onopen = () => {
                console.log('[TTS] WebSocket 连接成功');
                this.ws = ws;
                resolve(ws);
            };
            ws.onerror = (e) => {
                console.error('[TTS] WebSocket 错误:', e);
                reject(e);
            };
            ws.onclose = () => {
                console.log('[TTS] WebSocket 断开');
                if (this.ws !== ws) return;
                this.ws = null;
                this._maybeFinish();
            };
            ws.onmessage = (e) => this.handleWebSocketMessage(e);
        });
    },

    handleWebSocketMessage(event) {
        const msg = JSON.parse(event.data);
        switch (msg.type) {
            case 'audio.start':
                console.log('[TTS] 开始接收音频流, sample_rate:', msg.sample_rate);
                this.isStreaming = true;
                this.serverSampleRate = msg.sample_rate || 24000;
                this.startStreamingPlayback();
                break;

            case 'audio.chunk':
                if (this.isStreaming) {
                    this.playAudioChunk(msg.data, msg.samples);
                } else {
                    console.warn('[TTS] 丢弃 chunk');
                }
                break;

            case 'audio.done':
                console.log('[TTS] 音频流接收完成');
                this.isStreaming = false;
                if (msg.path) {
                    this.playAudio(msg.path);
                }
                this.showProgress(false);
                this._maybeFinish();
                break;

            case 'error':
                console.error('[TTS] 服务器错误:', msg.message);
                this.isStreaming = false;
                this.showProgress(false);
                this._maybeFinish();
                break;
        }
    },

    startStreamingPlayback() {
        this.streamQueue = [];
        this.isPlayingStream = false;
    },

    playAudioChunk(base64Data, numSamples) {
        if (this.isPlayingStream) {
            console.log('[TTS] 入队, queueLen:', this.streamQueue.length);
            this.streamQueue.push(base64Data);
            return;
        }
        console.log('[TTS] 首次播放 chunk, samples:', numSamples);
        this.isPlayingStream = true;
        this._playAudioData(base64Data);
    },

    _playAudioData(base64Data) {
        console.log('[TTS] _playAudioData enter, queue:', this.streamQueue.length);
        const binary = atob(base64Data);
        const bytes = new Uint8Array(binary.length);
        for (let i = 0; i < binary.length; i++) {
            bytes[i] = binary.charCodeAt(i);
        }
        const int16 = new Int16Array(bytes.buffer);
        const sr = this.serverSampleRate || 24000;
        const ctx = this.audioContext;
        const buffer = ctx.createBuffer(1, int16.length, sr);
        const channel = buffer.getChannelData(0);
        for (let i = 0; i < int16.length; i++) {
            channel[i] = int16[i] / 32768.0;
        }
        const source = ctx.createBufferSource();
        source.buffer = buffer;
        source.connect(ctx.destination);
        source.onended = () => {
            if (this.audioContext !== ctx) return;
            console.log('[TTS] source.onended fired, queue:', this.streamQueue.length);
            if (this.streamQueue.length > 0) {
                const next = this.streamQueue.shift();
                this._playAudioData(next);
            } else {
                this.isPlayingStream = false;
                console.log('[TTS] 所有 chunk 播放完毕');
                this._maybeFinish();
            }
        };
        console.log('[TTS] 即将 source.start(), currentTime:', this.audioContext.currentTime);
        source.start();
        console.log('[TTS] source.start() 已调用');
    },

    async speak(text, voice) {
        this.showProgress(true);
        this.streamQueue = [];
        this.isPlayingStream = false;

        if (!this.audioContext) {
            this.audioContext = new AudioContext();
            console.log('[TTS] AudioContext state:', this.audioContext.state,
                        'sampleRate:', this.audioContext.sampleRate,
                        'currentTime:', this.audioContext.currentTime);
            // 在用户手势内播放一个静默帧，永久解锁 AudioContext
            const silent = this.audioContext.createBuffer(1, 128, this.audioContext.sampleRate);
            const silentSrc = this.audioContext.createBufferSource();
            silentSrc.buffer = silent;
            silentSrc.connect(this.audioContext.destination);
            silentSrc.start();
            console.log('[TTS] AudioContext 已解锁');
        }
        if (this.audioContext.state === 'suspended') {
            await this.audioContext.resume();
            console.log('[TTS] resume 后 state:', this.audioContext.state,
                        'currentTime:', this.audioContext.currentTime);
        }

        try {
            const ws = await this.getWebSocket();
            ws.send(JSON.stringify({ text, voice }));
        } catch (e) {
            console.log('[TTS] WebSocket 不可用，使用 HTTP 模式');
            const resp = await fetch('/api/tts/speak', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ text, voice })
            });
            const data = await resp.json();
            if (data.audio) {
                this.playAudio(data.audio);
            } else {
                this._maybeFinish();
            }
        }
    },

    async speakAndWait(text, voice) {
        const id = ++this.uttSeq;
        this.playingViaElement = false;
        this.uttEnd = { id, resolve: null };
        const done = new Promise((res) => {
            this.uttEnd.resolve = res;
        });
        try {
            await this.speak(text, voice);
        } catch (e) {
            console.error('[TTS] speakAndWait 启动失败:', e);
            this._settleUtterance(id);
            return;
        }
        const timeoutMs = Math.min(Math.max(text.length * 300, 15000), 300000);
        let timer = null;
        await Promise.race([
            done,
            new Promise((res) => {
                timer = setTimeout(() => {
                    console.warn('[TTS] speakAndWait 播放超时，强制结束本条');
                    res();
                }, timeoutMs);
            })
        ]);
        clearTimeout(timer);
        if (this.uttEnd && this.uttEnd.id === id) {
            this.uttEnd = null;
        }
    },

    _settleUtterance(id) {
        if (this.uttEnd && this.uttEnd.id === id) {
            const resolve = this.uttEnd.resolve;
            this.uttEnd = null;
            if (resolve) resolve();
        }
    },

    _maybeFinish() {
        if (this.isStreaming || this.isPlayingStream) return;
        if (this.streamQueue && this.streamQueue.length > 0) return;
        if (this.playingViaElement) return;
        this._settleUtterance(this.uttEnd && this.uttEnd.id);
    },

    async speakUserMessage(text) {
        await this.speak(text, ConfigModule.get('user_voice', '云扬'));
    },

    async speakAIReply(text) {
        await this.speak(text, ConfigModule.get('ai_voice', '晓晓'));
    },

    async readTextContent() {
        const text = document.getElementById('readText').value.trim();
        if (!text) { alert(I18N.t('enterTextToRead')); return; }
        await this.speak(text, ConfigModule.get('ai_voice', '晓晓'));
    },

    async readWeb() {
        const url = document.getElementById('webUrl').value.trim();
        if (!url) { alert(I18N.t('enterUrl')); return; }
        this.showProgress(true);
        try {
            const resp = await fetch('/api/web/fetch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ url })
            });
            const data = await resp.json();
            if (data.content && !data.content.startsWith('抓取失败')) {
                await this.speak(data.content, ConfigModule.get('ai_voice', '晓晓'));
            } else {
                alert(I18N.t('webFetchFailed') + (data.content || I18N.t('unknownError')));
                this.showProgress(false);
            }
        } catch (e) {
            alert(I18N.t('requestFailed') + e.message);
            this.showProgress(false);
        }
    },

    async uploadAndRead() {
        const fileInput = document.getElementById('fileInput');
        const file = fileInput.files[0];
        if (!file) return;
        const formData = new FormData();
        formData.append('file', file);
        const resp = await fetch('/api/upload', { method: 'POST', body: formData });
        const data = await resp.json();
        if (data.content) {
            await this.speak(data.content, ConfigModule.get('ai_voice', '晓晓'));
        } else {
            alert(I18N.t('fileEmptyError'));
        }
    },

    playAudio(audioPath) {
        this.playingViaElement = true;
        this.audioPlayer.src = audioPath + '?' + Date.now();
        this.audioPlayer.play();
        this.audioPlayer.onended = () => {
            this.playingViaElement = false;
            this.showProgress(false);
            this._maybeFinish();
        };
    },

    stop() {
        this.isStreaming = false;
        this.streamQueue = [];
        this.isPlayingStream = false;
        this.playingViaElement = false;
        if (this.audioContext) {
            this.audioContext.close();
            this.audioContext = null;
        }
        this.audioPlayer.pause();
        this.audioPlayer.currentTime = 0;
        fetch('/api/tts/stop', { method: 'POST' });
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        this.showProgress(false);
        this._maybeFinish();
        if (typeof window.__onTTSStop === 'function') {
            try { window.__onTTSStop(); } catch (e) {}
        }
    },

    showProgress(show) {
        const bar = document.getElementById('progressBar');
        if (show) {
            bar.classList.add('active');
            clearInterval(this.progressInterval);
            let width = 0;
            this.progressInterval = setInterval(() => {
                width = (width + 1) % 101;
                document.getElementById('progressFill').style.width = width + '%';
            }, 100);
        } else {
            if (this.keepProgress) return;
            bar.classList.remove('active');
            clearInterval(this.progressInterval);
            document.getElementById('progressFill').style.width = '0%';
        }
    }
};
