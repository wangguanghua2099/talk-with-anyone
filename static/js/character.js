// character.js - 角色管理模块
const CharacterModule = {
    characters: [],
    currentCharId: null,

    async load(selectId) {
        const resp = await fetch('/api/characters');
        const data = await resp.json();
        this.characters = data.characters;
        const select = document.getElementById('characterSelect');
        select.innerHTML = '';
        this.characters.forEach(c => {
            const option = document.createElement('option');
            option.value = c.id;
            option.textContent = c.name;
            select.appendChild(option);
        });
        if (selectId) {
            select.value = selectId;
            this.currentCharId = selectId;
        } else if (ConfigModule.get('current_character_id')) {
            // 优先用持久化的当前角色 ID 定位，避免两个角色共享人设文案时匹配错位
            const currentId = ConfigModule.get('current_character_id');
            if (this.characters.some(c => c.id === currentId)) {
                select.value = currentId;
                this.currentCharId = currentId;
            }
        } else if (ConfigModule.get('ai_role_prompt')) {
            const match = this.characters.find(c => c.ai_prompt === ConfigModule.get('ai_role_prompt'));
            if (match) {
                select.value = match.id;
                this.currentCharId = match.id;
            }
        }
    },

    async select() {
        const select = document.getElementById('characterSelect');
        const charId = select.value;
        this.currentCharId = charId;
        const char = this.characters.find(c => c.id === charId);
        if (char) {
            document.getElementById('aiRolePrompt').value = char.ai_prompt;
            document.getElementById('userRolePrompt').value = char.user_prompt || '';
            const engine = document.getElementById('ttsEngine').value;
            const engineVoices = char.engine_voices || {};
            document.getElementById('aiVoice').value = engineVoices[engine] || char.ai_voice || '晓晓';
            document.getElementById('userVoice').value = char.user_voice || '云扬';
            // 更新头像预览
            const aiAvatarPreview = document.getElementById('aiAvatarPreview');
            if (aiAvatarPreview) aiAvatarPreview.src = char.ai_avatar || '';

            // 立即更新 config.json
            const resp = await fetch('/api/characters/select', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    id: char.id, name: char.name,
                    ai_prompt: char.ai_prompt, user_prompt: char.user_prompt,
                    ai_voice: char.ai_voice, user_voice: char.user_voice
                })
            });
            const data = await resp.json();
            Object.assign(ConfigModule.data, data.config);
        }
    },

    async confirm() {
        // 保留 confirm 方法用于兼容，但实际更新已在 select 中完成
        await this.select();
    },

    async savePrompt() {
        if (!this.currentCharId) { alert(I18N.t('selectCharFirst')); return; }
        const aiPrompt = document.getElementById('aiRolePrompt').value;
        const userPrompt = document.getElementById('userRolePrompt').value;
        const char = this.characters.find(c => c.id === this.currentCharId);

        // 保存到角色数据
        await fetch(`/api/characters/${this.currentCharId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: char && char.name, ai_prompt: aiPrompt, user_prompt: userPrompt })
        });

        // 同步更新 config.json
        const resp = await fetch('/api/characters/select', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                id: char.id, name: char.name,
                ai_prompt: aiPrompt, user_prompt: userPrompt,
                ai_voice: char.ai_voice, user_voice: char.user_voice
            })
        });
        const data = await resp.json();
        Object.assign(ConfigModule.data, data.config);

        alert(I18N.t('charPromptSaved'));
    },

    async saveVoice() {
        if (!this.currentCharId) { alert(I18N.t('selectCharFirst')); return; }
        const aiVoice = document.getElementById('aiVoice').value;
        const char = this.characters.find(c => c.id === this.currentCharId);
        if (!char) return;

        // 获取当前引擎，保存到对应的 engine_voices 槽
        const engine = document.getElementById('ttsEngine').value;
        const engineVoices = { ...(char.engine_voices || {}), [engine]: aiVoice };

        // 保存到角色数据（同时更新 ai_voice 和 engine_voices）
        await fetch(`/api/characters/${this.currentCharId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name: char.name, ai_voice: aiVoice,
                engine_voices: { [engine]: aiVoice }
            })
        });

        // 更新本地缓存
        char.ai_voice = aiVoice;
        char.engine_voices = engineVoices;

        // 同步更新 config.json
        const resp = await fetch('/api/characters/select', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                id: char.id, name: char.name,
                ai_prompt: char.ai_prompt, user_prompt: char.user_prompt,
                ai_voice: aiVoice, engine_voices: engineVoices,
                user_voice: char.user_voice
            })
        });
        const data = await resp.json();
        Object.assign(ConfigModule.data, data.config);

        alert(I18N.t('charVoiceSaved'));
    },

    showAdd() {
        const name = prompt(I18N.t('enterCharName'));
        if (!name) return;
        const engine = document.getElementById('ttsEngine').value;
        // 新角色用空人设 + 引擎默认音色，不继承当前角色的设定
        this.add(name, name, '', '', '', engine);
    },

    async add(name, displayName, aiPrompt, userPrompt, aiVoice, engine) {
        const engineVoices = { edge: '晓晓', moss: 'Yuewen', qwen3: 'Vivian', 'qwen3-clone': '声音克隆' };
        if (aiVoice) engineVoices[engine] = aiVoice;
        const resp = await fetch('/api/characters', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                name, display_name: displayName, ai_prompt: aiPrompt,
                user_prompt: userPrompt, ai_voice: aiVoice || '晓晓',
                engine_voices: engineVoices
            })
        });
        const data = await resp.json();
        if (data.character) {
            await this.load(data.character.id);
            // 自动切换到新角色并更新 config.json
            await this.select();
            alert(I18N.t('charAdded'));
        }
    },

    async delete() {
        if (!this.currentCharId) { alert(I18N.t('selectCharFirst')); return; }
        if (!confirm(I18N.t('confirmDeleteChar'))) return;
        await fetch(`/api/characters/${this.currentCharId}`, { method: 'DELETE' });
        await this.load();
        if (this.characters.length > 0) {
            this.currentCharId = this.characters[0].id;
            document.getElementById('characterSelect').value = this.currentCharId;
            this.select();
        }
        alert(I18N.t('charDeleted'));
    },

    showContextMenu(e) {
        e.preventDefault();
        if (!this.currentCharId) return;
        this.hideContextMenu();
        const menu = document.createElement('div');
        menu.className = 'conv-context-menu';
        menu.id = 'charContextMenu';
        menu.innerHTML = `<div class="conv-context-item" onclick="CharacterModule.rename(); CharacterModule.hideContextMenu();">${I18N.t('renameChar')}</div>`;
        menu.style.left = e.pageX + 'px';
        menu.style.top = e.pageY + 'px';
        document.body.appendChild(menu);
        const close = () => { this.hideContextMenu(); document.removeEventListener('click', close); };
        setTimeout(() => document.addEventListener('click', close), 0);
    },

    hideContextMenu() {
        const m = document.querySelector('#charContextMenu');
        if (m) m.remove();
    },

    rename() {
        if (!this.currentCharId) return;
        const char = this.characters.find(c => c.id === this.currentCharId);
        if (!char) return;
        const newName = prompt(I18N.t('renameCharPrompt'), char.name);
        if (newName === null || newName.trim() === '' || newName.trim() === char.name) return;
        this.doRename(this.currentCharId, newName.trim());
    },

    async doRename(charId, newName) {
        await fetch(`/api/characters/${charId}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: newName })
        });
        const char = this.characters.find(c => c.id === charId);
        if (char && this.currentCharId === charId) {
            const resp = await fetch('/api/characters/select', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    id: char.id, name: newName,
                    ai_prompt: char.ai_prompt, user_prompt: char.user_prompt,
                    ai_voice: char.ai_voice, user_voice: char.user_voice
                })
            });
            const data = await resp.json();
            Object.assign(ConfigModule.data, data.config);
        }
        await this.load(charId);
    }
};
