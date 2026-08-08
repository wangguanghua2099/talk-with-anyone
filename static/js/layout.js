// layout.js - 左右侧边栏收起/展开模块
const LayoutModule = (() => {
    const STORAGE_KEY = 'twa_sidebars';
    const NARROW_THRESHOLD = 768;
    const narrowQuery = window.matchMedia('(max-width: 767px)');

    function isNarrow() { return narrowQuery.matches; }

    function state() {
        let saved = null;
        try { saved = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null'); } catch (e) { saved = null; }
        // 无历史记录时：窄屏默认收起，宽屏默认展开
        if (!saved || typeof saved !== 'object') {
            const narrow = isNarrow();
            saved = { left: narrow ? 'collapsed' : 'expanded', right: narrow ? 'collapsed' : 'expanded' };
        }
        return saved;
    }

    function ensureBackdrop() {
        let bd = document.getElementById('sidebarBackdrop');
        if (!bd) {
            bd = document.createElement('div');
            bd.id = 'sidebarBackdrop';
            bd.className = 'sidebar-backdrop';
            bd.addEventListener('click', () => {
                const s = state();
                if (s.left === 'expanded') toggle('left');
                if (s.right === 'expanded') toggle('right');
            });
            document.body.appendChild(bd);
        }
        return bd;
    }

    function apply(s) {
        const leftEl = document.querySelector('.left-sidebar');
        const rightEl = document.querySelector('.sidebar');
        if (leftEl) leftEl.classList.toggle('collapsed', s.left === 'collapsed');
        if (rightEl) rightEl.classList.toggle('collapsed', s.right === 'collapsed');
        const leftBtn = document.getElementById('toggleSidebarLeft');
        const rightBtn = document.getElementById('toggleSidebarRight');
        if (leftBtn) leftBtn.classList.toggle('active', s.left === 'expanded');
        if (rightBtn) rightBtn.classList.toggle('active', s.right === 'expanded');
        // 窄屏抽屉模式下，展开时显示半透明遮罩
        const bd = document.getElementById('sidebarBackdrop');
        if (bd) bd.style.display = (isNarrow() && (s.left === 'expanded' || s.right === 'expanded')) ? 'block' : 'none';
    }

    function persist(s) {
        try { localStorage.setItem(STORAGE_KEY, JSON.stringify(s)); } catch (e) { /* 忽略存储失败 */ }
    }

    function toggle(side) {
        const s = state();
        s[side] = s[side] === 'collapsed' ? 'expanded' : 'collapsed';
        persist(s);
        apply(s);
    }

    function init() {
        ensureBackdrop();
        apply(state());
        narrowQuery.addEventListener('change', () => apply(state()));
    }

    return { init, toggle };
})();

document.addEventListener('DOMContentLoaded', LayoutModule.init);