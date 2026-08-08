// app.js - 主入口，初始化所有模块
function toggleTab(tabId) {
    const tab = document.getElementById(tabId);
    tab.classList.toggle('active');
}
async function initApp() {
    await ConfigModule.load();
    AvatarModule.init();
    TTSModule.init();
    ReadAloudModule.init();
    await CharacterModule.load();
    updateTTSIcons();
    await loadTTSEngine();
    await ConversationModule.loadList();
    await loadConversationMessages();
    await CustomVoiceModule.load();
}

async function loadTTSEngine() {
    const resp = await fetch('/api/tts/engines');
    const data = await resp.json();
    document.getElementById('ttsEngine').value = data.current || 'edge';
}

async function loadConversationMessages() {
    if (ConversationModule.currentId) {
        await ConversationModule.open(ConversationModule.currentId);
    }
    // 加载当前角色的头像预览
    const charSel = document.getElementById('characterSelect');
    const charId = charSel ? charSel.value : '';
    const char = CharacterModule.characters.find(c => c.id === charId);
    if (char) {
        const aiAvatarPreview = document.getElementById('aiAvatarPreview');
        if (aiAvatarPreview) aiAvatarPreview.src = char.ai_avatar || '';
    }
}

function updateTTSIcons() {
    document.getElementById('ttsUserIcon').textContent = ConfigModule.get('tts_read_user', true) ? '🔊' : '🔇';
    document.getElementById('ttsAIIcon').textContent = ConfigModule.get('tts_read_ai', true) ? '🔊' : '🔇';
}

function toggleTTSReadUser() {
    const val = !ConfigModule.get('tts_read_user', true);
    ConfigModule.set('tts_read_user', val);
    updateTTSIcons();
    ConfigModule.save({ tts_read_user: val });
}

function toggleTTSReadAI() {
    const val = !ConfigModule.get('tts_read_ai', true);
    ConfigModule.set('tts_read_ai', val);
    updateTTSIcons();
    ConfigModule.save({ tts_read_ai: val });
}

async function toggleSearchEnabled() {
    const val = document.getElementById('searchEnabled').checked;
    ConfigModule.set('web_search_enabled', val);
    await ConfigModule.save({ web_search_enabled: val });
}

async function saveUserPrompt() {
    const val = document.getElementById('userRolePrompt').value;
    await ConfigModule.save({ user_role_prompt: val });
    alert(I18N.t('userPromptSaved'));
}

async function saveUserVoice() {
    const val = document.getElementById('userVoice').value;
    await ConfigModule.save({ user_voice: val });
    alert(I18N.t('userVoiceSaved'));
}

async function saveUserName() {
    const val = document.getElementById('userName').value.trim();
    if (!val) { alert(I18N.t('enterUserName')); return; }
    await ConfigModule.save({ user_name: val });
    alert(I18N.t('userNameSaved'));
}

async function saveLLMConfig() {
    const backend = document.getElementById('llmBackend').value;
    const url = document.getElementById('llmUrl').value;
    const apiKey = document.getElementById('llmApiKey').value;
    const model = document.getElementById('llmModel').value;
    // 按后端单独保存一份，切换后端时自动恢复，无需重复填写
    const profiles = ConfigModule.get('llm_profiles', {}) || {};
    profiles[backend] = { url: url, api_key: apiKey, model: model };
    await ConfigModule.save({ llm_backend: backend, llm_url: url, llm_api_key: apiKey, llm_model: model, llm_profiles: profiles });
    alert(I18N.t('llmSaved'));
}

function applyLLMProfile(backend) {
    const profiles = ConfigModule.get('llm_profiles', {}) || {};
    const prof = profiles[backend];
    // 仅当该后端有专属配置、或顶层配置本身就属于该后端时才回填，避免串用别的后端的地址
    const useTop = (!prof || !prof.url) && ConfigModule.get('llm_backend', 'local') === backend;
    document.getElementById('llmUrl').value = useTop ? (ConfigModule.get('llm_url', '') || '') : (prof && prof.url ? prof.url : '');
    document.getElementById('llmApiKey').value = useTop ? (ConfigModule.get('llm_api_key', '') || '') : (prof ? (prof.api_key || '') : '');
    document.getElementById('llmModel').value = useTop ? (ConfigModule.get('llm_model', '') || '') : (prof ? (prof.model || '') : '');
}

function onLLMBackendChange() {
    const backend = document.getElementById('llmBackend').value;
    const isLocal = backend === 'local';
    document.getElementById('llmKeyRow').style.display = isLocal ? 'none' : '';
    document.getElementById('llmModelRow').style.display = isLocal ? 'none' : '';
    document.getElementById('llmRefreshBtn').style.display = isLocal ? 'none' : '';
    applyLLMProfile(backend);
    if (!isLocal) loadLLMModels();
}

async function loadLLMModels() {
    const backend = document.getElementById('llmBackend').value;
    if (backend === 'local') return;
    const url = document.getElementById('llmUrl').value.trim();
    if (!url) { alert(I18N.t('enterApiUrl')); return; }
    const apiKey = document.getElementById('llmApiKey').value;
    const modelSel = document.getElementById('llmModel');
    const prevModel = modelSel.value;
    try {
        const resp = await fetch('/api/llm/models', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ llm_backend: backend, llm_url: url, llm_api_key: apiKey })
        });
        const data = await resp.json();
        modelSel.innerHTML = `<option value="">${I18N.t('selectModel')}</option>`;
        (data.models || []).forEach(m => {
            const opt = document.createElement('option');
            opt.value = m;
            opt.textContent = m;
            modelSel.appendChild(opt);
        });
        if (prevModel) modelSel.value = prevModel;
        if (data.error || data.error_code) alert(I18N.t('fetchModelsFailed') + I18N.apiError(data));
    } catch (e) {
        alert(I18N.t('requestFailed') + e.message);
    }
}

async function switchTTSEngine() {
    const engine = document.getElementById('ttsEngine').value;
    const resp = await fetch('/api/tts/engine', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ engine })
    });
    const data = await resp.json();
    if (data.config) {
        Object.assign(ConfigModule.data, data.config);
    }
    ConfigModule.set('tts_engine', engine);
    await loadVoices();
}

async function loadVoices() {
    const resp = await fetch('/api/tts/voices');
    const data = await resp.json();
    const aiVoiceSel = document.getElementById('aiVoice');
    const userVoiceSel = document.getElementById('userVoice');
    aiVoiceSel.innerHTML = '';
    userVoiceSel.innerHTML = '';
    data.voices.forEach(v => {
        const label = v === 'clone engine' ? I18N.t('cloneEngineVoice') : v;
        aiVoiceSel.innerHTML += `<option value="${v}" ${v === ConfigModule.get('ai_voice') ? 'selected' : ''}>${label}</option>`;
        userVoiceSel.innerHTML += `<option value="${v}" ${v === ConfigModule.get('user_voice') ? 'selected' : ''}>${label}</option>`;
    });
}

function autoGrowInput(el) {
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 120) + 'px';
}

function bindEvents() {
    const userInput = document.getElementById('userInput');
    userInput.addEventListener('input', () => autoGrowInput(userInput));
    userInput.addEventListener('keydown', e => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            ChatModule.sendMessage();
        }
    });
    document.getElementById('aiRolePrompt').value = ConfigModule.get('ai_role_prompt', '');
    document.getElementById('userRolePrompt').value = ConfigModule.get('user_role_prompt', I18N.t('defaultUserRole'));
    document.getElementById('userName').value = ConfigModule.get('user_name', '');
    document.getElementById('searchEnabled').checked = ConfigModule.get('web_search_enabled', true);
    document.getElementById('llmBackend').value = ConfigModule.get('llm_backend', 'local');
    applyLLMProfile(document.getElementById('llmBackend').value);
    const isLocalBackend = document.getElementById('llmBackend').value === 'local';
    document.getElementById('llmKeyRow').style.display = isLocalBackend ? 'none' : '';
    document.getElementById('llmModelRow').style.display = isLocalBackend ? 'none' : '';
    document.getElementById('llmRefreshBtn').style.display = isLocalBackend ? 'none' : '';
    // 加载头像预览（AI头像从角色配置读取，用户头像从全局配置读取）
    const userAvatar = ConfigModule.get('user_avatar', '');
    if (userAvatar) document.getElementById('userAvatarPreview').src = userAvatar;
}

document.addEventListener('DOMContentLoaded', async () => {
    await initApp();
    await loadVoices();
    bindEvents();
});
