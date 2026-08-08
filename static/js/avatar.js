// avatar.js - 头像裁剪压缩模块
const AvatarModule = {
    cropper: null,
    currentTarget: null,
    cropperReady: false,

    init() {
        // 加载 cropperjs CSS
        if (!document.querySelector('link[href*="cropper"]')) {
            const link = document.createElement('link');
            link.rel = 'stylesheet';
            link.href = 'https://cdnjs.cloudflare.com/ajax/libs/cropperjs/1.6.1/cropper.min.css';
            document.head.appendChild(link);
        }
        // 加载 cropperjs JS
        if (!window.Cropper) {
            const script = document.createElement('script');
            script.src = 'https://cdnjs.cloudflare.com/ajax/libs/cropperjs/1.6.1/cropper.min.js';
            script.onload = () => { this.cropperReady = true; };
            document.head.appendChild(script);
        } else {
            this.cropperReady = true;
        }
    },

    showUploadDialog(target) {
        this.currentTarget = target;
        const input = document.getElementById('avatarFileInput');
        input.click();
    },

    handleFileSelect(e) {
        const file = e.target.files[0];
        if (!file) return;
        const reader = new FileReader();
        reader.onload = (ev) => {
            this.showCropper(ev.target.result);
        };
        reader.readAsDataURL(file);
        e.target.value = '';
    },

    showCropper(imageSrc) {
        if (!this.cropperReady) {
            alert(I18N.t('avatarCropperLoading'));
            return;
        }
        const modal = document.getElementById('avatarModal');
        const img = document.getElementById('avatarCropImage');
        img.src = imageSrc;
        modal.style.display = 'flex';

        setTimeout(() => {
            if (this.cropper) this.cropper.destroy();
            this.cropper = new Cropper(img, {
                aspectRatio: 1,
                viewMode: 1,
                minCropBoxSize: 50
            });
        }, 150);
    },

    closeCropper() {
        const modal = document.getElementById('avatarModal');
        modal.style.display = 'none';
        if (this.cropper) {
            this.cropper.destroy();
            this.cropper = null;
        }
    },

    cropAndUpload() {
        if (!this.cropper) {
            alert(I18N.t('cropperNotReady'));
            return;
        }
        const canvas = this.cropper.getCroppedCanvas({
            width: 200,
            height: 200,
            imageSmoothingQuality: 'high'
        });
        if (!canvas) {
            alert(I18N.t('cropFailed'));
            return;
        }
        const base64 = canvas.toDataURL('image/jpeg', 0.8);
        this.uploadAvatar(base64);
    },

    async uploadAvatar(base64) {
        try {
            const resp = await fetch('/api/avatar/upload', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ avatar: base64, target: this.currentTarget })
            });
            const data = await resp.json();
            if (data.status === 'ok') {
                this.closeCropper();
                ConfigModule.set(this.currentTarget === 'ai' ? 'ai_avatar' : 'user_avatar', base64);
                const preview = document.getElementById(this.currentTarget + 'AvatarPreview');
                if (preview) preview.src = base64;
                this.refreshChatAvatars();
                alert(I18N.t('avatarSaved'));
            } else {
                alert(I18N.t('uploadFailed') + ': ' + I18N.apiError(data));
            }
        } catch (e) {
            console.error('上传头像失败:', e);
            alert(I18N.t('uploadFailed'));
        }
    },

    refreshChatAvatars() {
        // 刷新聊天框中的头像
        const charSel = document.getElementById('characterSelect');
        const charId = charSel ? charSel.value : '';
        const char = CharacterModule.characters.find(c => c.id === charId);
        const aiAvatar = (char && char.ai_avatar) || '';
        const userAvatar = ConfigModule.get('user_avatar', '');
        document.querySelectorAll('.message.assistant .avatar').forEach(img => {
            if (aiAvatar) img.src = aiAvatar;
        });
        document.querySelectorAll('.message.assistant .avatar-placeholder').forEach(el => {
            if (aiAvatar) {
                const newImg = document.createElement('img');
                newImg.className = 'avatar';
                newImg.src = aiAvatar;
                el.replaceWith(newImg);
            }
        });
        document.querySelectorAll('.message.user .avatar').forEach(img => {
            if (userAvatar) img.src = userAvatar;
        });
        document.querySelectorAll('.message.user .avatar-placeholder').forEach(el => {
            if (userAvatar) {
                const newImg = document.createElement('img');
                newImg.className = 'avatar';
                newImg.src = userAvatar;
                el.replaceWith(newImg);
            }
        });
    },

    getAvatarHtml(role, characterId, displayName) {
        if (role === 'assistant') {
            // AI 头像：优先用 character_id，否则用 displayName 匹配角色
            let char = null;
            if (characterId) {
                char = CharacterModule.characters.find(c => c.id === characterId);
            }
            if (!char && displayName) {
                // 旧消息没有 character_id，用消息的 displayName 匹配角色名
                char = CharacterModule.characters.find(c => c.name === displayName || c.display_name === displayName);
            }
            if (!char) {
                char = CharacterModule.characters.find(c => c.id === (document.getElementById('characterSelect') || {}).value);
            }
            const avatar = (char && char.ai_avatar) || '';
            const charName = (char && (char.display_name || char.name)) || 'AI';
            const initial = charName.charAt(0);
            if (avatar) {
                return `<img class="avatar" src="${avatar}" />`;
            }
            return `<div class="avatar-placeholder" style="background:#007AFF">${initial}</div>`;
        } else {
            // 用户头像从全局配置读取
            const avatar = ConfigModule.get('user_avatar', '');
            const name = ConfigModule.get('user_name', I18N.t('you'));
            const initial = name.charAt(0);
            if (avatar) {
                return `<img class="avatar" src="${avatar}" />`;
            }
            return `<div class="avatar-placeholder" style="background:#4CD964">${initial}</div>`;
        }
    }
};
