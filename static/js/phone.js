// phone.js - 电话模式模块
const PhoneModule = {
    ws: null,
    mediaStream: null,
    audioContext: null,
    processor: null,
    isActive: false,
    timer: null,
    seconds: 0,
    messages: [],
    audioQueue: [],
    isPlaying: false,
    isConnecting: false,
    isMicMuted: false,
    // 流式回复状态（assistant.delta + voice WS 音频）
    streamPlayer: null,      // voice WS 音频播放器（audio.start/chunk/done）
    fileAudio: null,         // edge 等无流式引擎的回退：audio.file 逐句播放
    fileQueue: [],
    filePlaying: false,
    receivedAudio: false,    // 本轮是否收到过音频（决定 completed 时要不要兜底朗读）
    typingCtrl: null,        // 正在打字的 assistant 消息
    assistantText: "",
    streamFinalized: false,  // 本轮流式消息是否已收尾（防止 completed 与打断双写）
    _llmFirstTokenAt: null,  // 收到 LLM 首个文字增量的时刻（出声计时用）

    async start() {
        if (this.isActive || this.isConnecting) return;
        this.isConnecting = true;

        // 请求麦克风权限
        try {
            this.mediaStream = await navigator.mediaDevices.getUserMedia({
                audio: {
                    sampleRate: 16000,
                    channelCount: 1,
                    echoCancellation: true,
                    noiseSuppression: true,
                },
            });
        } catch (err) {
            alert(window.isSecureContext ? I18N.t("micPermissionPhone") : I18N.t("micNeedsHttps"));
            this.isConnecting = false;
            return;
        }

        // 显示电话界面
        this.showPhoneUI();

        // 建立 WebSocket
        try {
            this.ws = new WebSocket(wsUrl('/ws/voice'));
            
            this.ws.onopen = () => {
                console.log("[Phone] WebSocket 已连接");
                this.ws.send(JSON.stringify({ type: "session.start", mode: "chat" }));
                this.isConnecting = false;
                this.isActive = true;

                // 开始录音
                this.startRecording();

                // 在用户手势内解锁音频播放器，避免后续自动播放被浏览器拦截
                this.ensureStreamPlayer().start(24000);

                // 开始计时
                this.startTimer();
            };
            
            this.ws.onmessage = (e) => {
                try {
                    const data = JSON.parse(e.data);
                    this.handleMessage(data);
                } catch (err) {
                    console.error("[Phone] 解析消息失败:", err);
                }
            };
            
            this.ws.onerror = (e) => {
                console.error("[Phone] WebSocket 错误:", e);
                this.stop();
            };
            
            this.ws.onclose = (e) => {
                console.log("[Phone] WebSocket 关闭:", e.code, e.reason);
                // 只有在主动关闭时才停止
                if (this.isActive) {
                    this.stop();
                }
            };
        } catch (err) {
            console.error("[Phone] WebSocket 创建失败:", err);
            this.stop();
        }
    },

    showPhoneUI() {
        const overlay = document.getElementById("phoneOverlay");
        const charSel = document.getElementById("characterSelect");
        const charId = charSel ? charSel.value : '';
        const char = CharacterModule.characters.find((c) => c.id === charId);

        document.getElementById("phoneName").textContent = (char && char.name) || "AI";
        document.getElementById("phoneMessages").innerHTML = "";

        // 新一轮通话前清掉上一通话残留的流式状态
        this.stopStreamPlayback();
        if (this.typingCtrl) this.typingCtrl.skip();
        this.typingCtrl = null;
        this.assistantText = "";
        this.streamFinalized = false;
        this.receivedAudio = false;

        overlay.style.display = "flex";
        this.messages = [];
    },

    startRecording() {
        this.audioContext = new AudioContext({ sampleRate: 16000 });
        const source = this.audioContext.createMediaStreamSource(this.mediaStream);
        this.processor = this.audioContext.createScriptProcessor(4096, 1, 1);

        this.processor.onaudioprocess = (e) => {
            const audioData = e.inputBuffer.getChannelData(0);
            const pcm16 = this.float32ToInt16(audioData);
            if (this.ws && this.ws.readyState === WebSocket.OPEN && !this.isMicMuted) {
                this.ws.send(pcm16.buffer);
            }
        };

        source.connect(this.processor);
        this.processor.connect(this.audioContext.destination);
    },

    toggleMic() {
        if (!this.isActive) return;
        this.isMicMuted = !this.isMicMuted;

        const btn = document.getElementById("phoneMicBtn");
        const slash = document.getElementById("phoneMicSlash");
        if (this.isMicMuted) {
            if (btn) btn.classList.add("muted");
            if (slash) slash.style.display = "block";
            if (btn) btn.title = I18N.t("sttEnableMic");
        } else {
            if (btn) btn.classList.remove("muted");
            if (slash) slash.style.display = "none";
            if (btn) btn.title = I18N.t("mute");
        }
    },

    handleMessage(data) {
        switch (data.type) {
            case "server.ready":
                console.log("电话会话就绪:", data.session_id);
                break;

            case "vad.speaking":
                // 用户开口说话时，打断正在朗读的 AI 回复（barge-in）
                if (data.speaking) {
                    TTSModule.stop();
                    this.stopStreamPlayback();
                    this.finalizePartialAssistant();
                }
                this.updateSpeakingUI(data.speaking);
                break;

            case "asr.result":
                if (data.is_final && data.text) {
                    // 新一轮回复开始
                    this.receivedAudio = false;
                    this.streamFinalized = false;
                    this._llmFirstTokenAt = null;
                    this.addMessage("user", data.text);
                }
                break;

            case "assistant.delta":
                if (this._llmFirstTokenAt === null) this._llmFirstTokenAt = performance.now();
                this.appendAssistantDelta(data.text);
                break;

            case "audio.start":
                this.receivedAudio = true;
                // 出声计时：标记后首个音频块排程时触发 onFirstAudio，
                // 把「LLM首token → 出声」间隔上报后端（对齐 chat.js 流水）
                this.ensureStreamPlayer().markStreamStart();
                this.ensureStreamPlayer().start(data.sample_rate || 24000);
                break;

            case "audio.chunk":
                if (this.streamPlayer) {
                    this.streamPlayer.push(data.data);
                }
                break;

            case "audio.done":
                // 整条回复音频推送完毕，队列中剩余的块会继续播完
                break;

            case "audio.file":
                // 无流式接口的引擎（如 edge）：逐句合成文件播放
                this.receivedAudio = true;
                this.playFileAudio(data.path);
                break;

            case "assistant.completed":
                if (data.text) {
                    this.finishAssistantMessage(data.text);
                    // 流式模式下音频已随句子推送播放；没收到过音频才走整段朗读兜底
                    if (!this.receivedAudio && ConfigModule.get("tts_read_ai", true)) {
                        TTSModule.stop();
                        TTSModule.speakAIReply(data.text);
                    }
                } else {
                    this.finalizePartialAssistant();
                }
                break;

            case "assistant.error":
                console.error("AI 错误:", data.message);
                this.finalizePartialAssistant();
                break;

            case "interrupt.ack":
                console.log("已打断");
                // 后端确认打断生成，同时停掉可能仍在朗读的 TTS
                TTSModule.stop();
                this.stopStreamPlayback();
                this.finalizePartialAssistant();
                break;

            case "session.closed":
                this.stop();
                break;
        }
    },

    addMessage(role, text) {
        const messagesDiv = document.getElementById("phoneMessages");
        const userName = ConfigModule.get("user_name", I18N.t("you"));
        const aiName = ConfigModule.get("ai_display_name", "AI");

        const div = document.createElement("div");
        div.className = `phone-msg ${role}`;
        const sender = document.createElement("div");
        sender.className = "sender";
        sender.textContent = role === "user" ? userName : aiName;
        const content = document.createElement("div");
        content.className = "content";
        const textEl = document.createElement("span");
        textEl.className = "msg-text";
        textEl.textContent = text;
        content.appendChild(textEl);
        div.appendChild(sender);
        div.appendChild(content);
        messagesDiv.appendChild(div);
        messagesDiv.scrollTop = messagesDiv.scrollHeight;

        // 保存到消息列表
        this.messages.push({
            role,
            text,
            timestamp: new Date().toISOString(),
        });

        // 同步保存到主聊天
        ChatModule.addMessage(role, text, new Date().toISOString());
    },

    // ---- 流式回复（assistant.delta + voice WS 音频）----

    appendAssistantDelta(text) {
        if (this.streamFinalized) return; // 本轮已被打断收尾，丢弃迟到内容
        if (!this.typingCtrl) {
            const messagesDiv = document.getElementById("phoneMessages");
            const div = document.createElement("div");
            div.className = "phone-msg assistant";
            const sender = document.createElement("div");
            sender.className = "sender";
            sender.textContent = ConfigModule.get("ai_display_name", "AI");
            const content = document.createElement("div");
            content.className = "content";
            const textEl = document.createElement("span");
            textEl.className = "msg-text";
            content.appendChild(textEl);
            div.appendChild(sender);
            div.appendChild(content);
            messagesDiv.appendChild(div);
            this.typingCtrl = TypeWriter.create(textEl, {
                scrollEl: messagesDiv,
                clickToSkipEl: div,
            });
            this.assistantText = "";
        }
        this.assistantText += text;
        this.typingCtrl.push(text);
    },

    // 回复正常完成：以后端全文为准，放完打字动画后同步主聊天
    finishAssistantMessage(fullText) {
        if (this.streamFinalized) return;
        if (this.typingCtrl) {
            if (fullText.length > this.assistantText.length) {
                this.typingCtrl.push(fullText.slice(this.assistantText.length));
            }
            this.typingCtrl.finish();
        } else {
            // 没收到过 delta（旧后端/异常），直接整条显示
            this.addMessage("assistant", fullText);
        }
        this.messages.push({
            role: "assistant",
            text: fullText,
            timestamp: new Date().toISOString(),
        });
        ChatModule.addMessage("assistant", fullText, new Date().toISOString());
        this.resetStreamState();
    },

    // 回复被打断：立即显示已缓冲文字并收尾，不再等 completed
    finalizePartialAssistant() {
        if (this.streamFinalized) return;
        if (this.typingCtrl) {
            this.typingCtrl.skip();
            if (this.assistantText.trim()) {
                this.messages.push({
                    role: "assistant",
                    text: this.assistantText,
                    timestamp: new Date().toISOString(),
                });
                ChatModule.addMessage("assistant", this.assistantText, new Date().toISOString());
            }
        }
        this.resetStreamState();
    },

    resetStreamState() {
        this.typingCtrl = null;
        this.assistantText = "";
        this.streamFinalized = true;
    },

    ensureStreamPlayer() {
        if (!this.streamPlayer) {
            this.streamPlayer = StreamPlayer.create();
            // 出声计时：AI 语音第一个音频块实际出声时，把
            // "LLM首token → 出声" 的间隔回传后台展示
            this.streamPlayer.onFirstAudio = (audibleAt) => {
                if (this._llmFirstTokenAt === null) return;
                const lat = Math.round(audibleAt - this._llmFirstTokenAt);
                this._llmFirstTokenAt = null;   // 每轮只报一次
                try {
                    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
                        this.ws.send(JSON.stringify({ type: "client_stats", llm_first_token_to_audio_ms: lat }));
                    }
                } catch (e) {}
            };
        }
        return this.streamPlayer;
    },

    stopStreamPlayback() {
        if (this.streamPlayer) {
            this.streamPlayer.stop();
            this.streamPlayer = null;
        }
        this.filePlaying = false;
        this.fileQueue = [];
        if (this.fileAudio) {
            this.fileAudio.pause();
            this.fileAudio = null;
        }
    },

    playFileAudio(path) {
        if (!this.fileAudio) {
            this.fileAudio = new Audio();
            this.fileAudio.onended = () => {
                this.filePlaying = false;
                if (this.fileQueue.length > 0) {
                    this.fileAudio.src = this.fileQueue.shift() + "?" + Date.now();
                    this.filePlaying = true;
                    this.fileAudio.play().catch(() => {});
                }
            };
        }
        if (this.filePlaying) {
            this.fileQueue.push(path);
        } else {
            // 加时间戳防缓存（与 TTSModule.playAudio 一致）
            this.fileAudio.src = path + "?" + Date.now();
            this.filePlaying = true;
            this.fileAudio.play().catch(() => {});
        }
    },

    updateSpeakingUI(speaking) {
        const indicator = document.getElementById("phoneSpeakingIndicator");
        if (indicator) {
            indicator.style.display = speaking ? "flex" : "none";
        }
    },

    stop() {
        if (!this.isActive && !this.isConnecting && !this.mediaStream) return;

        console.log("[Phone] 停止电话模块");

        // 停止可能仍在朗读的 AI 回复
        TTSModule.stop();

        // 停止流式音频播放与打字动画
        this.stopStreamPlayback();
        if (this.typingCtrl) {
            this.typingCtrl.skip();
        }
        this.resetStreamState();

        // 停止录音
        if (this.processor) {
            this.processor.disconnect();
            this.processor = null;
        }
        if (this.mediaStream) {
            this.mediaStream.getTracks().forEach((t) => t.stop());
            this.mediaStream = null;
        }
        if (this.audioContext) {
            this.audioContext.close();
            this.audioContext = null;
        }

        // 关闭 WebSocket
        if (this.ws) {
            try {
                if (this.ws.readyState === WebSocket.OPEN) {
                    this.ws.send(JSON.stringify({ type: "session.stop" }));
                }
                this.ws.close();
            } catch (e) {
                console.error("[Phone] 关闭 WebSocket 失败:", e);
            }
            this.ws = null;
        }

        // 停止计时
        clearInterval(this.timer);
        this.timer = null;

        // 隐藏电话界面
        document.getElementById("phoneOverlay").style.display = "none";

        // 重置麦克风静音状态
        this.isMicMuted = false;
        const micBtn = document.getElementById("phoneMicBtn");
        if (micBtn) micBtn.classList.remove("muted");
        const slash = document.getElementById("phoneMicSlash");
        if (slash) slash.style.display = "none";

        this.isActive = false;
        this.isConnecting = false;
        this.seconds = 0;
    },

    startTimer() {
        this.seconds = 0;
        this.timer = setInterval(() => {
            this.seconds++;
            const min = String(Math.floor(this.seconds / 60)).padStart(2, "0");
            const sec = String(this.seconds % 60).padStart(2, "0");
            document.getElementById("phoneTimer").textContent = `${min}:${sec}`;
        }, 1000);
    },

    float32ToInt16(float32Array) {
        const int16Array = new Int16Array(float32Array.length);
        for (let i = 0; i < float32Array.length; i++) {
            const s = Math.max(-1, Math.min(1, float32Array[i]));
            int16Array[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
        }
        return int16Array;
    },
};
