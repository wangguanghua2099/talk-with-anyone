// tts.js - TTS 朗读功能模块
// StreamPlayer：流式 PCM 播放器（base64 int16 → AudioContext 预排程无缝连播）。
// 关键点：不用 onended 串接（事件调度延迟会在每个缓冲衔接处产生咔哒声/破音），
// 而是每收到一块就按精确时间轴 pre-schedule，让声卡自己无缝拼接；
// onended 只用于"全部播完"的空闲检测。TTSModule 自己的 /ws/tts-stream
// 和电话模式的 voice WebSocket 共用这套播放逻辑。
const StreamPlayer = {
    create(onIdle) {
        return {
            ctx: null,
            sampleRate: 24000,
            active: false,
            _sources: new Set(),
            _nextTime: 0,
            _onIdle: onIdle || null,
            _awaitFirst: false,        // 出声计时：等待第一个音频块排程
            _playStartWallclock: 0,    // 第一个音频块实际出声的时刻（performance.now 时基）
            onFirstAudio: null,        // 出声时刻回调（分句流水测端到端延迟用）

            // 出声计时基准：每次重新标记后，下一个排程的音频块出声时触发 onFirstAudio
            markStreamStart() {
                this._awaitFirst = true;
                this._playStartWallclock = 0;
            },

            async start(sampleRate) {
                this.sampleRate = sampleRate || this.sampleRate || 24000;
                if (!this.ctx) {
                    this.ctx = new AudioContext();
                    // 在用户手势内播放一个静默帧，永久解锁 AudioContext
                    const silent = this.ctx.createBuffer(1, 128, this.ctx.sampleRate);
                    const silentSrc = this.ctx.createBufferSource();
                    silentSrc.buffer = silent;
                    silentSrc.connect(this.ctx.destination);
                    silentSrc.start();
                }
                if (this.ctx.state === 'suspended') {
                    await this.ctx.resume();
                }
                // 注意：不清空已排程的音频/时间轴——分句流水会在上一句
                // 仍在播放时调用 start() 追加下一句，清空会打断播放
                this.active = true;
            },

            push(base64Data) {
                if (!this.active || !this.ctx) return;
                const binary = atob(base64Data);
                const bytes = new Uint8Array(binary.length);
                for (let i = 0; i < binary.length; i++) {
                    bytes[i] = binary.charCodeAt(i);
                }
                const int16 = new Int16Array(bytes.buffer);
                const ctx = this.ctx;
                const buffer = ctx.createBuffer(1, int16.length, this.sampleRate);
                const channel = buffer.getChannelData(0);
                for (let i = 0; i < int16.length; i++) {
                    channel[i] = int16[i] / 32768.0;
                }
                const source = ctx.createBufferSource();
                source.buffer = buffer;
                source.connect(ctx.destination);
                // 预排程：在上一个缓冲结束的精确时刻开始，事件循环再卡也不会有缝
                const when = Math.max(this._nextTime, ctx.currentTime + 0.02);
                source.start(when);
                this._nextTime = when + buffer.duration;
                this._sources.add(source);
                if (this._awaitFirst) {
                    // 该音频块实际出声的时刻（换算到 performance.now 时基）
                    this._awaitFirst = false;
                    this._playStartWallclock = performance.now() + (when - ctx.currentTime) * 1000;
                    if (this.onFirstAudio) this.onFirstAudio(this._playStartWallclock);
                }
                source.onended = () => {
                    this._sources.delete(source);
                    // 排程的全部播完且没有新的时间点 → 本轮流式播放结束
                    if (this.active && this._sources.size === 0 &&
                        this._nextTime <= ctx.currentTime + 0.01) {
                        if (this._onIdle) this._onIdle();
                    }
                };
            },

            busy() {
                if (!this.active || !this.ctx) return false;
                return this._sources.size > 0 || this._nextTime > this.ctx.currentTime;
            },

            _stopSources() {
                for (const s of this._sources) {
                    try { s.onended = null; s.stop(); } catch (e) {}
                }
                this._sources.clear();
            },

            stop() {
                this.active = false;
                this._awaitFirst = false;
                this._playStartWallclock = 0;
                this._stopSources();
                this._nextTime = 0;
                if (this.ctx) {
                    this.ctx.close();
                    this.ctx = null;
                }
                if (this._onIdle) this._onIdle();
            },
        };
    },
};

const TTSModule = {
    audioPlayer: null,
    progressInterval: null,
    ws: null,
    player: null,
    isStreaming: false,
    uttSeq: 0,
    uttEnd: null,
    keepProgress: false,
    playingViaElement: false,
    _sentenceDone: null,   // 分句流水：等待当前句合成完成的回调
    _fileQueue: [],        // 文件型引擎（edge）多句播放队列

    init() {
        this.audioPlayer = document.getElementById('audioPlayer');
        this.player = StreamPlayer.create(() => this._maybeFinish());
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
                this.player.start(msg.sample_rate || 24000);
                break;

            case 'audio.chunk':
                if (this.isStreaming) {
                    this.player.push(msg.data);
                }
                break;

            case 'audio.done':
                console.log('[TTS] 音频流接收完成');
                this.isStreaming = false;
                if (msg.path) {
                    this.playAudioQueued(msg.path);
                }
                this.showProgress(false);
                this._fireSentenceDone();
                this._maybeFinish();
                break;

            case 'error':
                console.error('[TTS] 服务器错误:', msg.message);
                this.isStreaming = false;
                this.showProgress(false);
                this._fireSentenceDone();
                this._maybeFinish();
                break;
        }
    },

    async speak(text, voice) {
        this.showProgress(true);
        if (!this.player) {
            this.player = StreamPlayer.create(() => this._maybeFinish());
        }
        // 提前解锁 AudioContext（audio.start 之后可能已无用户手势）
        await this.player.start();

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
        if (this.isStreaming) return;
        if (this.player && this.player.busy()) return;
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
            if (this._fileQueue.length > 0) {
                this.playAudio(this._fileQueue.shift());   // 播放队列中的下一句
                return;
            }
            this.playingViaElement = false;
            this.showProgress(false);
            this._maybeFinish();
        };
    },

    playAudioQueued(audioPath) {
        // 文件型引擎（edge）逐句返回 wav：排队按顺序播放，避免后句打断前句
        if (this.playingViaElement) {
            this._fileQueue.push(audioPath);
            return;
        }
        this.playAudio(audioPath);
    },

    // 分句流水专用：发送一句，返回"该句合成完成"的 Promise（合成期间播放继续，
    // 下一句等本句合成完才发送，音频块按序追加到预排程时间轴上，衔接无缝）
    speakSentence(text, voice) {
        return new Promise((resolve) => {
            let settled = false;
            const finish = () => {
                if (settled) return;
                settled = true;
                clearTimeout(timer);
                this._sentenceDone = null;
                resolve();
            };
            // 兜底：超时放行，避免极端情况下流水卡死
            const timer = setTimeout(finish, Math.max(20000, text.length * 600));
            this._sentenceDone = finish;
            this.speak(text, voice).catch((e) => {
                console.error('[TTS] 句子发送失败:', e);
                finish();
            });
        });
    },

    _fireSentenceDone() {
        const cb = this._sentenceDone;
        this._sentenceDone = null;
        if (cb) cb();
    },

    sendStats(obj) {
        // 把客户端实测统计数据发回后台展示（TTS WebSocket 打开时）
        try {
            if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                this.ws.send(JSON.stringify(obj));
            }
        } catch (e) {}
    },

    stop() {
        this.isStreaming = false;
        if (this.player) {
            this.player.stop();
        }
        this.playingViaElement = false;
        this._fileQueue = [];
        this.audioPlayer.pause();
        this.audioPlayer.currentTime = 0;
        fetch('/api/tts/stop', { method: 'POST' });
        if (this.ws) {
            this.ws.close();
            this.ws = null;
        }
        this.showProgress(false);
        this._fireSentenceDone();   // 分句流水：放行等待中的句子，避免卡死
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
