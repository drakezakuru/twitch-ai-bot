/** Shared, injection-safe URL appearance controls for OBS widgets. */
(function () {
    const params = new URLSearchParams(window.location.search);
    const root = document.documentElement;
    window.widgetScopedUrl = function (endpoint) {
        const target = new URL(endpoint, window.location.origin);
        const accountId = params.get('account_id');
        const channel = (params.get('channel') || '').trim().toLowerCase().replace(/^#+/, '');
        if (accountId) target.searchParams.set('account_id', accountId);
        if (channel) target.searchParams.set('channel', channel);
        return target.toString();
    };
    const theme = params.get('theme');
    const commonThemes = new Set(['dark', 'light', 'neon', 'fire', 'glass', 'mono']);
    if (theme && commonThemes.has(theme)) {
        root.setAttribute('data-widget-theme', theme);
    }

    const rawOpacity = params.get('opacity');
    if (rawOpacity !== null && rawOpacity.trim() !== '') {
        const value = Number(rawOpacity);
        if (Number.isFinite(value)) {
            const opacity = Math.max(0, Math.min(1, value));
            root.style.setProperty('--widget-opacity', String(opacity));
            root.style.setProperty('--widget-opacity-percent', `${opacity * 100}%`);
        }
    }

    // Q28: акцент/фон поверх темы — из URL (пипетка и брендовая палитра в панели).
    const hexPattern = /^#?[0-9a-fA-F]{6}$/;
    const rawAccent = (params.get('accent') || '').trim();
    if (hexPattern.test(rawAccent)) {
        root.style.setProperty('--w-accent', rawAccent);
        root.style.setProperty('--widget-theme-accent', rawAccent);
    }
    const rawBg = (params.get('bg') || '').trim();
    if (hexPattern.test(rawBg)) {
        root.style.setProperty('--w-bg', rawBg);
        root.style.setProperty('--widget-theme-surface', rawBg);
    }

    if (root.getAttribute?.('data-widget-layout') !== 'bounded') return;

    const rawScale = params.get('scale');
    let scale = null;
    if (rawScale !== null && rawScale.trim() !== '') {
        const value = Number(rawScale);
        if (Number.isFinite(value)) scale = Math.max(0.5, Math.min(3, value));
    }

    const rawPosition = params.get('pos');
    const positions = new Set(['tl', 'tc', 'tr', 'bl', 'bc', 'br']);
    const position = positions.has(rawPosition) ? rawPosition : null;
    if (scale === null && position === null) return;

    const applyLayout = () => {
        const selector = root.getAttribute('data-widget-root');
        if (!selector) return;
        document.querySelectorAll(selector).forEach((element) => {
            const width = element.getBoundingClientRect().width;
            if (position && width > 0) {
                element.style.setProperty('--widget-natural-width', `${width}px`);
            }
            if (scale !== null) {
                element.style.setProperty('--widget-scale', String(scale));
            }
            element.classList.add('widget-appearance-root');
        });
        if (position) root.setAttribute('data-widget-pos', position);
    };
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', applyLayout, { once: true });
    } else {
        applyLayout();
    }
})();
