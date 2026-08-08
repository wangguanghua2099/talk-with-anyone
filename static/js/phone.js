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
                }
                this.updateSpeakingUI(data.speaking);
                break;

            case "asr.result":
                if (data.is_final && data.text) {
                    this.addMessage("user", data.text);
                }
                break;

            case "assistant.completed":
                if (data.text) {
                    this.addMessage("assistant", data.text);
                    // 朗读 AI 回复（先停掉可能仍在朗读的上一条）
                    if (ConfigModule.get("tts_read_ai", true)) {
                        TTSModule.stop();
                        TTSModule.speakAIReply(data.text);
                    }
                }
                break;

            case "assistant.error":
                console.error("AI 错误:", data.message);
                break;

            case "interrupt.ack":
                console.log("已打断");
                // 后端确认打断生成，同时停掉可能仍在朗读的 TTS
                TTSModule.stop();
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
        div.innerHTML = `
            <div class="sender">${role === "user" ? userName : aiName}</div>
            <div class="content">${text}</div>
        `;
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
