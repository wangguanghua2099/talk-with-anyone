// typewriter.js - AI 回复打字机平滑显示
// 流式增量（或一次性全文）进入缓冲区，按固定节奏逐字揭示：
// 基准 100 字/秒；积压过多时按"总时长不超过 maxDuration"自动加速；
// 点击消息立即显示全部（跳过后后续流式内容直接全量显示，不再逐字）。
const TypeWriter = {
    _items: new Set(),
    _TICK_MS: 40,

    create(textEl, opts = {}) {
        const cps = opts.cps || 100;                // 基准速度：字/秒
        const maxDuration = opts.maxDuration || 3;  // 积压全部放完的时长上限：秒
        const ticksPerCap = (maxDuration * 1000) / this._TICK_MS;
        const scrollEl = opts.scrollEl || null;

        const cursor = document.createElement('span');
        cursor.className = 'typing-cursor';

        const ctrl = {
            _el: textEl,
            _buf: '',
            _shown: 0,
            _timer: null,
            _done: false,
            _skipped: false,
            _finished: false,

            push(chunk) {
                if (this._finished) return;
                this._buf += chunk;
                if (this._skipped) {
                    // 跳过模式：后续流式内容直接全量显示
                    this._el.textContent = this._buf;
                    return;
                }
                this._ensureCursor();
                this._start();
            },

            // 流结束：不再接收新内容，剩余缓冲继续按动画放完
            finish() {
                this._done = true;
                if (this._skipped || this._shown >= this._buf.length) this._cleanup();
                else this._start();
            },

            // 立即显示全部；后续 push 的内容也直接显示（流未结束时不丢字）
            skip() {
                if (this._finished) return;
                this._skipped = true;
                this._el.textContent = this._buf;
                if (this._timer) { clearInterval(this._timer); this._timer = null; }
                if (cursor.parentNode) cursor.parentNode.removeChild(cursor);
                if (this._done) this._cleanup();
            },

            _start() {
                if (this._timer) return;
                this._timer = setInterval(() => this._tick(), TypeWriter._TICK_MS);
            },

            _tick() {
                const backlog = this._buf.length - this._shown;
                if (backlog <= 0) {
                    if (this._done) this._cleanup();
                    return;
                }
                // 基准步长与"总时长上限"步长取大者
                const step = Math.max(
                    Math.ceil(cps * TypeWriter._TICK_MS / 1000),
                    Math.ceil(backlog / ticksPerCap)
                );
                this._shown = Math.min(this._buf.length, this._shown + step);
                let text = this._buf.slice(0, this._shown);
                // 避免把 emoji 等代理对从中间切开（下一拍会自然补齐）
                const last = text.charCodeAt(text.length - 1);
                if (last >= 0xD800 && last <= 0xDBFF && this._shown < this._buf.length) {
                    text = this._buf.slice(0, this._shown + 1);
                }
                this._el.textContent = text;
                if (scrollEl) scrollEl.scrollTop = scrollEl.scrollHeight;
                if (this._done && this._shown >= this._buf.length) this._cleanup();
            },

            _ensureCursor() {
                if (!cursor.parentNode || cursor.parentNode !== this._el.parentNode) {
                    this._el.parentNode.insertBefore(cursor, this._el.nextSibling);
                }
            },

            _cleanup() {
                this._finished = true;
                if (this._timer) { clearInterval(this._timer); this._timer = null; }
                if (cursor.parentNode) cursor.parentNode.removeChild(cursor);
                TypeWriter._items.delete(ctrl);
            },
        };

        // 点击消息立即显示全部
        const clickEl = opts.clickToSkipEl || textEl.closest('.message, .phone-msg') || textEl;
        clickEl.addEventListener('click', () => ctrl.skip());

        this._items.add(ctrl);
        return ctrl;
    },

    // 发新消息前清场：所有进行中的打字立即放完
    skipAll() {
        this._items.forEach((ctrl) => ctrl.skip());
        this._items.clear();
    },
};
