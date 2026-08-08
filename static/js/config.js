// config.js - 配置管理模块
// 根据页面协议返回 wss:// 或 ws:// 的 WebSocket 地址（HTTPS 下必须用 wss）
function wsUrl(path) {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    return `${proto}://${location.host}${path}`;
}

const ConfigModule = {
    data: {},

    async load() {
        const resp = await fetch('/api/config');
        this.data = await resp.json();
        return this.data;
    },

    async save(updates) {
        await fetch('/api/config', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(updates)
        });
        Object.assign(this.data, updates);
    },

    get(key, defaultVal) {
        return this.data[key] !== undefined ? this.data[key] : defaultVal;
    },

    set(key, value) {
        this.data[key] = value;
    }
};
