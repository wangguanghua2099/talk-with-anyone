// mic.js - 麦克风语音输入模块
const MicModule = {
    mediaStream: null,
    audioContext: null,
    processor: null,
    ws: null,
    isRecording: false,
    isWaitingResult: false,

    async startRecording() {
        if (this.isRecording || this.isWaitingResult) return;

        // 立即设置状态，防止松开时 onRelease 不执行
        this.isRecording = true;

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
            alert(window.isSecureContext ? I18N.t("micPermission") : I18N.t("micNeedsHttps"));
            return;
        }

        // 更新 UI
        const micBtn = document.getElementById("micBtn");
        micBtn.classList.add("recording");
        micBtn.innerHTML =
            '<div class="waveform"><div class="bar"></div><div class="bar"></div><div class="bar"></div><div class="bar"></div><div class="bar"></div></div>';

        // 建立 WebSocket
        this.ws = new WebSocket(wsUrl('/ws/voice'));
        this.ws.onopen = () => {
            console.log("[Mic] WebSocket 已连接");
            this.ws.send(JSON.stringify({ type: "session.start", mode: "transcribe" }));
        };
        this.ws.onmessage = (e) => {
            try {
                const data = JSON.parse(e.data);
                this.handleMessage(data);
            } catch (err) {
                console.error("[Mic] 解析消息失败:", err);
            }
        };
        this.ws.onerror = (e) => {
            console.error("[Mic] WebSocket 错误:", e);
        };
        this.ws.onclose = (e) => {
            console.log("[Mic] WebSocket 关闭:", e.code);
            this.stopRecording();
        };

        // 开始录音
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
        this.isRecording = true;
    },

    stopRecording() {
        if (!this.isRecording && !this.isWaitingResult) return;

        console.log("[Mic] 停止录音");

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

        // 更新 UI
        const micBtn = document.getElementById("micBtn");
        micBtn.classList.remove("recording");
        micBtn.textContent = "🎤";

        // 关闭 WebSocket（如果没有在等待结果）
        if (this.ws && !this.isWaitingResult) {
            try {
                if (this.ws.readyState === WebSocket.OPEN) {
                    this.ws.send(JSON.stringify({ type: "session.stop" }));
                }
                this.ws.close();
            } catch (e) {
                console.error("[Mic] 关闭 WebSocket 失败:", e);
            }
            this.ws = null;
        }

        this.isRecording = false;
    },

    handleMessage(data) {
        console.log("[Mic] 收到消息:", data.type);

        if (data.type === "asr.result" && data.is_final) {
            // 将识别结果填入输入框
            const input = document.getElementById("userInput");
            const currentValue = input.value.trim();
            if (currentValue) {
                input.value = currentValue + " " + data.text;
            } else {
                input.value = data.text;
            }
            input.focus();
            if (typeof autoGrowInput === 'function') autoGrowInput(input);

            // 关闭 WebSocket
            this.isWaitingResult = false;
            if (this.ws) {
                try {
                    if (this.ws.readyState === WebSocket.OPEN) {
                        this.ws.send(JSON.stringify({ type: "session.stop" }));
                    }
                    this.ws.close();
                } catch (e) {
                    console.error("[Mic] 关闭 WebSocket 失败:", e);
                }
                this.ws = null;
            }
        } else if (data.type === "asr.error") {
            console.error("[Mic] ASR 错误:", data.message);
            this.isWaitingResult = false;
            if (this.ws) {
                this.ws.close();
                this.ws = null;
            }
        }
    },

    onRelease() {
        if (!this.isRecording) return;

        console.log("[Mic] 用户松开按钮，等待识别结果...");
        this.isWaitingResult = true;

        // 更新 UI - 停止跳动动画
        const micBtn = document.getElementById("micBtn");
        micBtn.classList.remove("recording");
        micBtn.textContent = "⏳";

        // 停止录音（但不关闭 WebSocket）
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

        this.isRecording = false;

        // 设置超时，如果 5 秒内没有结果就关闭
        setTimeout(() => {
            if (this.isWaitingResult) {
                console.log("[Mic] 等待超时，关闭连接");
                this.isWaitingResult = false;
                if (this.ws) {
                    this.ws.close();
                    this.ws = null;
                }
                micBtn.classList.remove("recording");
                micBtn.textContent = "🎤";
            }
        }, 5000);
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
