// config.js - 配置管理模块
// 根据页面协议返回 wss:// 或 ws:// 的 WebSocket 地址（HTTPS 下必须用 wss）
function wsUrl(path) {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const token = getAccessToken();
    const q = token ? '?token=' + encodeURIComponent(token) : '';
    return `${proto}://${location.host}${path}${q}`;
}

// 访问口令：仅保存在浏览器本地（localStorage），随请求发送
const AUTH_TOKEN_KEY = 'twa_access_token';

function getAccessToken() {
    try { return localStorage.getItem(AUTH_TOKEN_KEY) || ''; } catch (e) { return ''; }
}

function setAccessToken(token) {
    try {
        if (token) localStorage.setItem(AUTH_TOKEN_KEY, token);
        else localStorage.removeItem(AUTH_TOKEN_KEY);
    } catch (e) { /* 忽略存储失败 */ }
}

// 全局注入 Authorization 头：启用口令后所有 /api/* 请求自动携带
(function injectAuthHeader() {
    const origFetch = window.fetch;
    window.fetch = function (url, opts) {
        opts = opts || {};
        const token = getAccessToken();
        if (token && String(url).indexOf('/api/') !== -1) {
            opts.headers = Object.assign({}, opts.headers);
            if (!opts.headers.Authorization && !opts.headers.authorization) {
                opts.headers.Authorization = 'Bearer ' + token;
            }
        }
        return origFetch.call(window, url, opts);
    };
})();

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
