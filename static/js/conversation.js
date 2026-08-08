// conversation.js - 对话管理模块
const ConversationModule = {
    conversations: [],
    currentId: null,
    searchKeyword: '',
    _searchTimer: null,

    async loadList() {
        try {
            const resp = await fetch('/api/conversations');
            const data = await resp.json();
            this.conversations = data.conversations || [];
            this.currentId = data.current_id;
            this.renderList();
        } catch (e) {
            console.error('加载对话列表失败:', e);
        }
    },

    async create() {
        try {
            const resp = await fetch('/api/conversations', { method: 'POST' });
            const data = await resp.json();
            this.currentId = data.conversation.id;
            this.conversations.unshift(data.conversation);
            this.renderList();
            ChatModule.clear();
            await this.open(data.conversation.id);
        } catch (e) {
            console.error('创建对话失败:', e);
        }
    },

    async open(convId) {
        try {
            const resp = await fetch(`/api/conversations/${convId}`);
            const data = await resp.json();
            const conv = data.conversation;
            this.currentId = convId;

            await fetch('/api/conversations/switch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ conv_id: convId })
            });

            ChatModule.clear();
            conv.messages.forEach(msg => {
                ChatModule.addMessage(msg.role, msg.content, msg.timestamp, msg.display_name, msg.character_id);
            });
            this.renderList();
        } catch (e) {
            console.error('打开对话失败:', e);
        }
    },

    async delete(convId) {
        if (!confirm(I18N.t('confirmDeleteConv'))) return;
        try {
            await fetch(`/api/conversations/${convId}`, { method: 'DELETE' });
            await this.loadList();
            if (this.conversations.length > 0) {
                await this.open(this.conversations[0].id);
            } else {
                await this.create();
            }
        } catch (e) {
            console.error('删除对话失败:', e);
        }
    },

    async rename(convId) {
        const conv = this.conversations.find(c => c.id === convId);
        const oldTitle = conv ? conv.title : '';
        const newTitle = prompt(I18N.t('renameConv'), oldTitle);
        if (newTitle === null || newTitle.trim() === '') return;
        try {
            await fetch(`/api/conversations/${convId}/rename`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ title: newTitle.trim() })
            });
            await this.loadList();
        } catch (e) {
            console.error('重命名失败:', e);
        }
    },

    groupByMonth(conversations) {
        const groups = {};
        conversations.forEach(conv => {
            const date = new Date(conv.updated_at || conv.created_at);
            const key = `${date.getFullYear()}.${String(date.getMonth() + 1).padStart(2, '0')}`;
            if (!groups[key]) groups[key] = [];
            groups[key].push(conv);
        });
        return groups;
    },

    showContextMenu(e, convId) {
        e.preventDefault();
        e.stopPropagation();

        this.hideContextMenu();

        const menu = document.createElement('div');
        menu.className = 'conv-context-menu';
        menu.innerHTML = `
            <div class="conv-context-item" onclick="ConversationModule.rename('${convId}'); ConversationModule.hideContextMenu();">${I18N.t('renameBtn')}</div>
            <div class="conv-context-item conv-context-danger" onclick="ConversationModule.delete('${convId}'); ConversationModule.hideContextMenu();">${I18N.t('deleteBtn')}</div>
        `;
        menu.style.left = e.pageX + 'px';
        menu.style.top = e.pageY + 'px';
        document.body.appendChild(menu);

        const closeMenu = () => {
            this.hideContextMenu();
            document.removeEventListener('click', closeMenu);
        };
        setTimeout(() => document.addEventListener('click', closeMenu), 0);
    },

    hideContextMenu() {
        const existing = document.querySelector('.conv-context-menu');
        if (existing) existing.remove();
    },

    filterByKeyword(keyword) {
        this.searchKeyword = keyword.trim();
        if (!this.searchKeyword) {
            this.renderList();
            return;
        }
        clearTimeout(this._searchTimer);
        this._searchTimer = setTimeout(() => {
            this.searchFromServer(this.searchKeyword);
        }, 300);
    },

    async searchFromServer(keyword) {
        try {
            const resp = await fetch(`/api/conversations/search?q=${encodeURIComponent(keyword)}`);
            const data = await resp.json();
            this.renderSearchResults(data.conversations || []);
        } catch (e) {
            console.error('搜索对话失败:', e);
        }
    },

    highlightText(text, keyword) {
        if (!keyword || !text) return this.escapeHtml(text);
        const escaped = this.escapeHtml(text);
        const kwEscaped = keyword.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        const regex = new RegExp(`(${kwEscaped})`, 'gi');
        return escaped.replace(regex, '<mark class="search-highlight">$1</mark>');
    },

    scrollToMessage(msgIndex) {
        const messagesDiv = document.getElementById('messages');
        const msgs = messagesDiv.querySelectorAll('.message');
        if (msgIndex >= 0 && msgIndex < msgs.length) {
            const msg = msgs[msgIndex];
            msg.scrollIntoView({ behavior: 'smooth', block: 'center' });
            msg.classList.add('message-flash');
            setTimeout(() => msg.classList.remove('message-flash'), 2000);
        }
    },

    openAndScroll(convId, msgIndex) {
        this.open(convId).then(() => {
            setTimeout(() => this.scrollToMessage(msgIndex), 100);
        });
    },

    renderSearchResults(results) {
        const container = document.getElementById('conversationList');
        if (!container) return;

        if (results.length === 0) {
            container.innerHTML = `<div class="conv-empty">${I18N.t('noMatchingConv')}</div>`;
            return;
        }

        const keyword = this.searchKeyword;
        let html = '';
        results.forEach((conv, convIdx) => {
            const isActive = conv.id === this.currentId;
            const title = conv.title || I18N.t('newConversation');
            const date = new Date(conv.updated_at || conv.created_at);
            const timeStr = I18N.t('dateTimeFormat', { m: date.getMonth() + 1, d: date.getDate(), h: String(date.getHours()).padStart(2, '0'), mi: String(date.getMinutes()).padStart(2, '0') });

            let snippetHtml = '';
            if (conv.snippets && conv.snippets.length > 0) {
                snippetHtml = '<div class="conv-item-snippets">';
                conv.snippets.forEach((s, sIdx) => {
                    const msgIdx = conv.snippet_indices ? conv.snippet_indices[sIdx] : -1;
                    const clickHandler = msgIdx >= 0
                        ? `onclick="event.stopPropagation(); ConversationModule.openAndScroll('${conv.id}', ${msgIdx})"`
                        : `onclick="event.stopPropagation(); ConversationModule.open('${conv.id}')"`;
                    snippetHtml += `<div class="conv-item-snippet" ${clickHandler} title="${I18N.t('jumpToMsg')}">${this.highlightText(s, keyword)}</div>`;
                });
                snippetHtml += '</div>';
            }

            const matchLabel = conv.match_type === 'title' ? `<span class="conv-item-match-title">${I18N.t('matchTitle')}</span>` : `<span class="conv-item-match-content">${I18N.t('matchContent')}</span>`;

            html += `
                <div class="conv-item ${isActive ? 'active' : ''}" onclick="ConversationModule.open('${conv.id}')" oncontextmenu="ConversationModule.showContextMenu(event, '${conv.id}')">
                    <div class="conv-item-title">${this.highlightText(title, keyword)} ${matchLabel}</div>
                    ${snippetHtml}
                    <div class="conv-item-meta">
                        <span class="conv-item-time">${timeStr}</span>
                        <span class="conv-item-count">${I18N.t('msgCount', { n: conv.message_count || 0 })}</span>
                    </div>
                </div>
            `;
        });
        container.innerHTML = html;
    },

    renderList() {
        const container = document.getElementById('conversationList');
        if (!container) return;

        const groups = this.groupByMonth(this.conversations);
        let html = '';

        Object.keys(groups).sort().reverse().forEach(month => {
            html += `<div class="conv-group"><div class="conv-group-title">${month}</div>`;
            groups[month].forEach(conv => {
                const isActive = conv.id === this.currentId;
                const title = conv.title || I18N.t('newConversation');
                const date = new Date(conv.updated_at || conv.created_at);
                const timeStr = I18N.t('dateTimeFormat', { m: date.getMonth() + 1, d: date.getDate(), h: String(date.getHours()).padStart(2, '0'), mi: String(date.getMinutes()).padStart(2, '0') });
                html += `
                    <div class="conv-item ${isActive ? 'active' : ''}" onclick="ConversationModule.open('${conv.id}')" oncontextmenu="ConversationModule.showContextMenu(event, '${conv.id}')">
                        <div class="conv-item-title">${this.escapeHtml(title)}</div>
                        <div class="conv-item-meta">
                            <span class="conv-item-time">${timeStr}</span>
                            <span class="conv-item-count">${I18N.t('msgCount', { n: conv.message_count || 0 })}</span>
                        </div>
                    </div>
                `;
            });
            html += '</div>';
        });

        if (this.conversations.length === 0) {
            html = `<div class="conv-empty">${I18N.t('noConversations')}</div>`;
        }

        container.innerHTML = html;
    },

    escapeHtml(str) {
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    }
};
