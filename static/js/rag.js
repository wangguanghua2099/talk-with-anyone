// rag.js - 知识库管理模块
const RAGModule = {
    enabled: false,
    libraries: [],
    activeKb: null,

    async init() {
        this.enabled = ConfigModule.get('rag_enabled', false);
        this.updateIcon();
        try {
            const st = await this.api('GET', '/api/rag/status');
            this.libraries = st.libraries || [];
            this.activeKb = (st.config || {}).active_kb || null;
        } catch (e) {
            console.warn('[RAG] init failed:', e);
        }
    },

    updateIcon() {
        const icon = document.getElementById('ragToggleIcon');
        if (icon) icon.textContent = this.enabled ? '📚' : '📖';
        const btn = document.getElementById('ragToggleBtn');
        if (btn) btn.classList.toggle('btn-rag-on', this.enabled);
    },

    async toggle() {
        this.enabled = !this.enabled;
        ConfigModule.set('rag_enabled', this.enabled);
        this.updateIcon();
        ConfigModule.save({ rag_enabled: this.enabled });
    },

    show() {
        document.getElementById('ragStudioModal').style.display = 'flex';
        this.refresh();
    },

    hide() {
        if (this._pollTimer) { clearTimeout(this._pollTimer); this._pollTimer = null; }
        document.getElementById('ragStudioModal').style.display = 'none';
    },

    async refresh() {
        const el = document.getElementById('ragContent');
        try {
            const st = await this.api('GET', '/api/rag/status');
            this.libraries = st.libraries || [];
            this.activeKb = (st.config || {}).active_kb || null;
            this.render(st);
            // 有构建任务未完成时每 1.5 秒轮询刷新
            const b = st.building;
            if (b && b.stage !== 'done' && b.stage !== 'error' && b.stage !== 'idle') {
                if (!this._pollTimer) {
                    this._pollTimer = setTimeout(() => { this._pollTimer = null; this.refresh(); }, 1500);
                }
            } else if (this._pollTimer) {
                clearTimeout(this._pollTimer); this._pollTimer = null;
            }
        } catch (e) {
            el.innerHTML = '<p style="color:red;">加载失败: ' + e.message + '</p>';
        }
    },

    render(st) {
        const el = document.getElementById('ragContent');
        const emb = st.embedder || {};
        const healthy = emb.healthy;
        const cfg = st.config || {};
        const dim = cfg.rag_embed_dim || 0;
        const chunk = cfg.rag_chunk_size || 500;

        let html = '';

        // 状态区
        html += `<div style="display:flex;gap:16px;align-items:center;flex-wrap:wrap;margin-bottom:16px;padding:12px;background:#f9f9f9;border-radius:8px;">
            <span style="font-size:13px;">嵌入服务: <b style="color:${healthy?'green':'red'}">${healthy?'运行中':'未连接'}</b></span>
            <span style="font-size:13px;">模型: ${emb.model||'未知'}</span>
            <span style="font-size:13px;">URL: ${emb.url||'-'}</span>
            <span style="font-size:13px;">维度: ${dim||'自动'}</span>
        </div>`;

        // 新建区
        html += `<div style="margin-bottom:16px;padding:16px;border:1px dashed #ccc;border-radius:8px;">
            <h3 style="margin:0 0 8px 0;font-size:15px;">新建知识库</h3>
            <div style="display:flex;gap:8px;flex-wrap:wrap;">
                <input id="ragNewName" placeholder="库名称" style="flex:1;min-width:200px;padding:6px 10px;border:1px solid #ddd;border-radius:6px;">
                <label class="btn btn-outline" style="cursor:pointer;">
                    📁 选择txt文件
                    <input type="file" id="ragFileInput" accept=".txt" style="display:none;" multiple onchange="RAGModule.createFromFile()">
                </label>
                <button class="btn btn-outline" onclick="RAGModule.createFromPaste()">📋 从粘贴创建</button>
            </div>
            <div style="margin-top:8px;">
                <textarea id="ragPasteText" placeholder="粘贴文本内容..." style="width:100%;height:80px;padding:8px;border:1px solid #ddd;border-radius:6px;font-size:13px;resize:vertical;"></textarea>
            </div>
            <div id="ragCreateStatus" style="font-size:13px;color:#666;margin-top:4px;"></div>
        </div>`;

        // 检索测试区
        html += `<div style="margin-bottom:16px;padding:16px;border:1px solid #e0e0e0;border-radius:8px;">
            <h3 style="margin:0 0 8px 0;font-size:15px;">检索测试</h3>
            <div style="display:flex;gap:8px;">
                <input id="ragQueryInput" placeholder="输入问题测试检索..." style="flex:1;padding:6px 10px;border:1px solid #ddd;border-radius:6px;">
                <button class="btn btn-outline" onclick="RAGModule.testQuery()">🔍 搜索</button>
            </div>
            <div id="ragQueryResult" style="margin-top:8px;"></div>
        </div>`;

        // 库列表
        html += `<h3 style="margin:0 0 8px 0;font-size:15px;">知识库列表 (${this.libraries.length})</h3>`;
        if (this.libraries.length === 0) {
            html += '<p style="color:#999;">暂无知识库，请上传文件创建</p>';
        } else {
            const b = st.building || {};
            for (const lib of this.libraries) {
                const isActive = lib.kb_id === this.activeKb;
                const embInfo = lib.embedder || {};
                let progressHtml = '';
                if (b && b.kb_id === lib.kb_id) {
                    if (b.stage === 'error') {
                        progressHtml = `<div style="font-size:12px;color:red;margin-top:4px;">❌ 构建失败: ${b.error||'未知错误'}</div>`;
                    } else if (b.stage !== 'done') {
                        progressHtml = `<div style="font-size:12px;color:#e67e22;margin-top:4px;">⏳ 构建中 ${b.stage} ${b.done||0}/${b.total||'?'}...</div>`;
                    }
                }
                html += `<div style="border:1px solid ${isActive?'#4CAF50':'#ddd'};border-radius:8px;padding:12px;margin-bottom:8px;background:${isActive?'#f0fff0':'#fff'};">
                    <div style="display:flex;justify-content:space-between;align-items:center;">
                        <div>
                            <b>${lib.name}</b> ${isActive?'<span style="color:green;font-size:12px;">✓ 当前激活</span>':''}
                            <div style="font-size:12px;color:#666;margin-top:2px;">
                                ${lib.chunk_count} 块 | ${lib.dim!=null?lib.dim+'维':'构建中'} | 模型: ${embInfo.model||'未知'}
                                ${lib.files&&lib.files.length?' | 文件: '+lib.files.join(', '):''}
                            </div>
                            ${progressHtml}
                        </div>
                        <div style="display:flex;gap:6px;">
                            ${!isActive?`<button class="btn btn-outline" style="font-size:12px;padding:4px 8px;" onclick="RAGModule.activate('${lib.kb_id}')">设为聊天用</button>`:''}
                            <label class="btn btn-outline" style="font-size:12px;padding:4px 8px;cursor:pointer;">
                                + 追加
                                <input type="file" accept=".txt" style="display:none;" onchange="RAGModule.appendFile('${lib.kb_id}',this)">
                            </label>
                            <button class="btn btn-outline btn-danger" style="font-size:12px;padding:4px 8px;" onclick="RAGModule.remove('${lib.kb_id}','${lib.name}')">删除</button>
                        </div>
                    </div>
                </div>`;
            }
        }

        el.innerHTML = html;
    },

    async api(method, path, body) {
        const url = path;
        const opts = { method, headers: {} };
        if (body instanceof FormData) {
            opts.body = body;
        } else if (body) {
            opts.body = JSON.stringify(body);
            opts.headers['Content-Type'] = 'application/json';
        }
        const resp = await fetch(url, opts);
        const data = await resp.json();
        if (!resp.ok) throw new Error(data.detail || data.error || resp.status);
        return data;
    },

    async activate(kbId) {
        try {
            await this.api('POST', '/api/rag/libraries/' + kbId + '/activate', {});
            this.activeKb = kbId;
            this.refresh();
        } catch (e) {
            alert('激活失败: ' + e.message);
        }
    },

    async remove(kbId, name) {
        if (!confirm(`确定删除知识库「${name}」？不可恢复。`)) return;
        try {
            await this.api('DELETE', '/api/rag/libraries/' + kbId);
            if (this.activeKb === kbId) this.activeKb = null;
            this.refresh();
        } catch (e) {
            alert('删除失败: ' + e.message);
        }
    },

    async createFromFile() {
        const input = document.getElementById('ragFileInput');
        const files = input.files;
        if (!files || files.length === 0) return;
        const name = document.getElementById('ragNewName').value.trim() || files[0].name.replace(/\.txt$/i, '');
        const fd = new FormData();
        fd.append('name', name);
        for (const f of files) fd.append('files', f);
        document.getElementById('ragCreateStatus').textContent = '创建中...';
        try {
            await this.api('POST', '/api/rag/libraries', fd);
            input.value = '';
            document.getElementById('ragCreateStatus').textContent = '✅ 创建成功';
            this.refresh();
        } catch (e) {
            document.getElementById('ragCreateStatus').textContent = '❌ ' + e.message;
        }
    },

    async createFromPaste() {
        const text = document.getElementById('ragPasteText').value.trim();
        if (!text) { alert('请先粘贴文本内容'); return; }
        const name = document.getElementById('ragNewName').value.trim() || ('粘贴_' + Date.now());
        const blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
        const file = new File([blob], name + '.txt', { type: 'text/plain' });
        const fd = new FormData();
        fd.append('name', name);
        fd.append('files', file);
        document.getElementById('ragCreateStatus').textContent = '创建中...';
        try {
            await this.api('POST', '/api/rag/libraries', fd);
            document.getElementById('ragPasteText').value = '';
            document.getElementById('ragCreateStatus').textContent = '✅ 创建成功';
            this.refresh();
        } catch (e) {
            document.getElementById('ragCreateStatus').textContent = '❌ ' + e.message;
        }
    },

    async appendFile(kbId, input) {
        const file = input.files && input.files[0];
        if (!file) return;
        const fd = new FormData();
        fd.append('files', file);
        try {
            await this.api('POST', `/api/rag/libraries/${kbId}/documents`, fd);
            input.value = '';
            this.refresh();
        } catch (e) {
            alert('追加失败: ' + e.message);
        }
    },

    async testQuery() {
        const q = document.getElementById('ragQueryInput').value.trim();
        if (!q) return;
        const el = document.getElementById('ragQueryResult');
        el.innerHTML = '<p style="color:#999;">搜索中...</p>';
        try {
            const body = { query: q, top_k: 3 };
            if (this.activeKb) body.kb_id = this.activeKb;
            const data = await this.api('POST', '/api/rag/query', body);
            const hits = data.hits || [];
            if (hits.length === 0) {
                el.innerHTML = '<p style="color:#999;">无匹配结果</p>';
                return;
            }
            let html = '';
            for (const h of hits) {
                const meta = h.meta || {};
                html += `<div style="border:1px solid #e0e0e0;border-radius:6px;padding:8px;margin-bottom:6px;font-size:13px;">
                    <div><b>得分:</b> ${h.score.toFixed(4)} | <b>章节:</b> ${meta.chapter||'-'} | <b>来源:</b> ${meta.source_file||'-'}</div>
                    <div style="margin-top:4px;color:#555;">${h.text.substring(0, 200)}${h.text.length>200?'...':''}</div>
                </div>`;
            }
            el.innerHTML = html;
        } catch (e) {
            el.innerHTML = '<p style="color:red;">❌ ' + e.message + '</p>';
        }
    }
};

// 初始化由 app.js 的 initApp() 在 ConfigModule.load() 之后调用，
// 避免此处自行监听 DOMContentLoaded 时配置尚未加载、开关状态丢失的竞态
