(function () {
    'use strict';
    const params = new URLSearchParams(location.search);
    // /obs/tts has an existing speech-language parameter, independent of UI copy.
    const requested = params.get('ui_lang') ?? (location.pathname === '/obs/tts' ? 'ru' : params.get('lang'));
    const lang = requested === 'uk' ? 'ua' : ['ru', 'en', 'ua'].includes(requested) ? requested : 'ru';
    const labels = {
        ru: {
            'common.loading': 'Загрузка…',
            'common.disconnected': 'Нет связи с панелью.',
            'common.unavailable': 'Данные недоступны.',
            'common.unavailable_http': 'Данные недоступны (HTTP {status}).',
            'common.waiting': 'Ожидание…',
            'common.viewer': 'Зритель',
            'common.preview': 'Предпросмотр',
        },
        en: {
            'common.loading': 'Loading…',
            'common.disconnected': 'Disconnected from the panel.',
            'common.unavailable': 'Data unavailable.',
            'common.unavailable_http': 'Data unavailable (HTTP {status}).',
            'common.waiting': 'Waiting…',
            'common.viewer': 'Viewer',
            'common.preview': 'Preview',
        },
        ua: {
            'common.loading': 'Завантаження…',
            'common.disconnected': 'Немає зв’язку з панеллю.',
            'common.unavailable': 'Дані недоступні.',
            'common.unavailable_http': 'Дані недоступні (HTTP {status}).',
            'common.waiting': 'Очікування…',
            'common.viewer': 'Глядач',
            'common.preview': 'Попередній перегляд',
        },
    };
    function t(key, vars = {}) {
        const value = (Object.hasOwn(labels[lang], key) && labels[lang][key])
            || (Object.hasOwn(labels.ru, key) && labels.ru[key]) || 'Текст недоступен';
        return value.replace(/\{(\w+)\}/g, (token, name) =>
            Object.hasOwn(vars, name) ? String(vars[name]) : token);
    }
    function apply(root = document) {
        for (const [suffix, attribute] of [['', null], ['-title', 'title'], ['-aria-label', 'aria-label']]) {
            const marker = 'data-widget-i18n' + suffix;
            const nodes = [...(root.matches?.(`[${marker}]`) ? [root] : []), ...root.querySelectorAll(`[${marker}]`)];
            for (const node of nodes) {
                const value = t(node.getAttribute(marker));
                if (attribute) node.setAttribute(attribute, value);
                else node.textContent = value;
            }
        }
    }
    function add(translations) {
        for (const locale of ['ru', 'en', 'ua']) Object.assign(labels[locale], translations[locale] || {});
    }
    window.WidgetI18n = {lang, t, add, apply};
    document.documentElement.lang = lang === 'ua' ? 'uk' : lang;
    document.addEventListener('DOMContentLoaded', () => apply(), {once: true});
})();
