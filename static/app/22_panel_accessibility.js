'use strict';

Object.assign(LANGS.ru, {
    'streamer.channel_required': 'Выберите канал стримера',
    'ui.text_unavailable': 'Текст недоступен', 'ui.expand_section': 'Развернуть раздел',
    'ui.collapse_section': 'Свернуть раздел', 'ui.table_region': 'Таблица с прокруткой',
    'ui.editor_region': 'Редактор с прокруткой', 'ui.uptime_hours': '{h} ч {m} мин',
    'ui.uptime_minutes': '{m} мин {s} с', 'ui.observation_age': '{seconds} сек. назад',
    'ui.observation_frame': 'Последний кадр стрима', 'ui.observation_no_text': 'Без текстового описания',
    'instr.params_tts': 'channel=НикКанала · min_role=any|viewer|sub|mod',
    'instr.params_counter': 'key=death (ключ счётчика)',
    'instr.params_topdonator': 'URL-варианты: /widget/top-donator-alltime | -month | -day',
});
Object.assign(LANGS.en, {
    'streamer.channel_required': 'Select the streamer channel',
    'ui.text_unavailable': 'Text unavailable', 'ui.expand_section': 'Expand section',
    'ui.collapse_section': 'Collapse section', 'ui.table_region': 'Scrollable table',
    'ui.editor_region': 'Scrollable editor', 'ui.uptime_hours': '{h} h {m} min',
    'ui.uptime_minutes': '{m} min {s} s', 'ui.observation_age': '{seconds} seconds ago',
    'ui.observation_frame': 'Latest stream frame', 'ui.observation_no_text': 'No text description',
    'instr.params_tts': 'channel=ChannelLogin · min_role=any|viewer|sub|mod',
    'instr.params_counter': 'key=death (counter key)',
    'instr.params_topdonator': 'URL variants: /widget/top-donator-alltime | -month | -day',
});
Object.assign(LANGS.ua, {
    'streamer.channel_required': 'Виберіть канал стрімера',
    'ui.text_unavailable': 'Текст недоступний', 'ui.expand_section': 'Розгорнути розділ',
    'ui.collapse_section': 'Згорнути розділ', 'ui.table_region': 'Таблиця з прокручуванням',
    'ui.editor_region': 'Редактор із прокручуванням', 'ui.uptime_hours': '{h} год {m} хв',
    'ui.uptime_minutes': '{m} хв {s} с', 'ui.observation_age': '{seconds} сек. тому',
    'ui.observation_frame': 'Останній кадр стріму', 'ui.observation_no_text': 'Без текстового опису',
    'instr.params_tts': 'channel=НікКаналу · min_role=any|viewer|sub|mod',
    'instr.params_counter': 'key=death (ключ лічильника)',
    'instr.params_topdonator': 'Варіанти URL: /widget/top-donator-alltime | -month | -day',
});

Object.assign(LANGS.ru, {
    'ui.field.role': 'Роль бота', 'ui.field.persona_preset': 'Пресет характера',
    'ui.field.custom_preset': 'Сохранённый пресет характера', 'ui.field.channel': 'Twitch-канал',
    'ui.field.voice_provider': 'Провайдер клона голоса', 'ui.field.log_level': 'Уровень логов',
    'ui.field.log_category': 'Категория логов', 'ui.field.file_editor': 'Содержимое файла бота',
    'ui.field.filter_action': 'Действие фильтра слов', 'ui.field.voice_control': 'Голосовое управление',
    'ui.field.user_role': 'Фильтр по роли зрителя', 'ui.field.streamer_photo': 'Фото стримера',
    'ui.field.tts_command': 'Команда TTS в чате', 'ui.field.media_queue': 'Обработка очереди медиа',
    'ui.field.media_position': 'Положение медиа', 'ui.field.media_width': 'Ширина медиа, %',
    'ui.field.media_duration': 'Длительность медиа, мс', 'ui.field.media_fade': 'Переход медиа, мс',
    'ui.field.sound_cooldown': 'Пауза между звуками, сек', 'ui.field.sound_rate': 'Максимум звуков в минуту',
    'ui.field.tts_output': 'Источник вывода TTS', 'ui.field.schedule_time': 'Время стрима',
    'ui.field.schedule_emoji': 'Значок стрима', 'ui.field.donation_amount': 'Сумма доната',
    'ui.field.reward_voice': 'Голос награды', 'ui.field.bridge_token': 'Токен локального моста донатов',
});
Object.assign(LANGS.en, {
    'ui.field.role': 'Bot role', 'ui.field.persona_preset': 'Personality preset',
    'ui.field.custom_preset': 'Saved personality preset', 'ui.field.channel': 'Twitch channel',
    'ui.field.voice_provider': 'Voice clone provider', 'ui.field.log_level': 'Log level',
    'ui.field.log_category': 'Log category', 'ui.field.file_editor': 'Bot file contents',
    'ui.field.filter_action': 'Word filter action', 'ui.field.voice_control': 'Voice control',
    'ui.field.user_role': 'Filter by viewer role', 'ui.field.streamer_photo': 'Streamer photo',
    'ui.field.tts_command': 'TTS chat command', 'ui.field.media_queue': 'Media queue handling',
    'ui.field.media_position': 'Media position', 'ui.field.media_width': 'Media width, %',
    'ui.field.media_duration': 'Media duration, ms', 'ui.field.media_fade': 'Media transition, ms',
    'ui.field.sound_cooldown': 'Sound cooldown, seconds', 'ui.field.sound_rate': 'Maximum sounds per minute',
    'ui.field.tts_output': 'TTS output source', 'ui.field.schedule_time': 'Stream time',
    'ui.field.schedule_emoji': 'Stream icon', 'ui.field.donation_amount': 'Donation amount',
    'ui.field.reward_voice': 'Reward voice', 'ui.field.bridge_token': 'Local donation bridge token',
});
Object.assign(LANGS.ua, {
    'ui.field.role': 'Роль бота', 'ui.field.persona_preset': 'Пресет характеру',
    'ui.field.custom_preset': 'Збережений пресет характеру', 'ui.field.channel': 'Twitch-канал',
    'ui.field.voice_provider': 'Провайдер клону голосу', 'ui.field.log_level': 'Рівень логів',
    'ui.field.log_category': 'Категорія логів', 'ui.field.file_editor': 'Вміст файлу бота',
    'ui.field.filter_action': 'Дія фільтра слів', 'ui.field.voice_control': 'Голосове керування',
    'ui.field.user_role': 'Фільтр за роллю глядача', 'ui.field.streamer_photo': 'Фото стрімера',
    'ui.field.tts_command': 'Команда TTS у чаті', 'ui.field.media_queue': 'Обробка черги медіа',
    'ui.field.media_position': 'Положення медіа', 'ui.field.media_width': 'Ширина медіа, %',
    'ui.field.media_duration': 'Тривалість медіа, мс', 'ui.field.media_fade': 'Перехід медіа, мс',
    'ui.field.sound_cooldown': 'Пауза між звуками, сек', 'ui.field.sound_rate': 'Максимум звуків за хвилину',
    'ui.field.tts_output': 'Джерело виведення TTS', 'ui.field.schedule_time': 'Час стріму',
    'ui.field.schedule_emoji': 'Значок стріму', 'ui.field.donation_amount': 'Сума донату',
    'ui.field.reward_voice': 'Голос нагороди', 'ui.field.bridge_token': 'Токен локального мосту донатів',
});

const PANEL_CONTROL_LABELS = {
    roleSelect: 'role', personaPreset: 'persona_preset', personaCustomPreset: 'custom_preset',
    newChannel: 'channel', overrideChannelSelect: 'channel', voiceCloneProvider: 'voice_provider',
    botLogsLevel: 'log_level', botLogsCategory: 'log_category', botFilesEditor: 'file_editor',
    badWordAction: 'filter_action', voiceControlEnabled: 'voice_control', chatUsersRoleFilter: 'user_role',
    streamerFaceFile: 'streamer_photo', modTTSChatAlias: 'tts_command', modMediaQueuePolicy: 'media_queue',
    modMediaPosition: 'media_position', modMediaWidth: 'media_width', modMediaDuration: 'media_duration',
    modMediaFade: 'media_fade', modSoundCooldown: 'sound_cooldown', modSoundRate: 'sound_rate',
    modTTSOutput: 'tts_output', waSchTime: 'schedule_time', waSchEmoji: 'schedule_emoji',
    waDonAmount: 'donation_amount', cpTtsVoice: 'reward_voice', waDonBridgeValue: 'bridge_token',
};

const _panelDialogs = [];
const _panelInert = new Map();
let _panelA11yId = 0;
let _panelA11yObserver;
let _panelSavedOverflow = '';
const PANEL_FOCUSABLE = 'a[href],button,input:not([type="hidden"]),select,textarea,summary,[tabindex],[contenteditable="true"]';

function panelElementId(element, prefix = 'panel-label') {
    if (!element.id) element.id = `${prefix}-${++_panelA11yId}`;
    return element.id;
}

function panelElementVisible(element) {
    if (!element?.isConnected) return false;
    for (let node = element; node && node !== document; node = node.parentElement) {
        if (node.hidden || node.inert || node.classList?.contains('hidden')) return false;
        const style = window.getComputedStyle(node);
        if (style.display === 'none' || style.visibility === 'hidden') return false;
        if (node.tagName === 'DETAILS' && !node.open && element !== node.querySelector('summary')
            && !node.querySelector('summary')?.contains(element)) return false;
    }
    return true;
}

function panelDialogFocusables(dialog) {
    return [...dialog.querySelectorAll(PANEL_FOCUSABLE)].filter(element =>
        !element.disabled && !element.matches(':disabled') && element.tabIndex >= 0 && panelElementVisible(element));
}

function panelRestoreInert() {
    for (const [element, inert] of _panelInert) element.inert = inert;
    _panelInert.clear();
}

function panelApplyInert() {
    panelRestoreInert();
    const top = _panelDialogs.at(-1);
    if (!top) {
        document.body.style.overflow = _panelSavedOverflow;
        return;
    }
    for (let branch = top.root; branch && branch !== document.body; branch = branch.parentElement) {
        for (const sibling of branch.parentElement?.children || []) {
            if (sibling === branch || sibling.id === 'toastContainer' || sibling.matches('script,style,link')) continue;
            _panelInert.set(sibling, sibling.inert);
            sibling.inert = true;
        }
    }
    document.body.style.overflow = 'hidden';
}

function openPanelDialog(target, options = {}) {
    const root = typeof target === 'string' ? document.getElementById(target) : target;
    if (!root) return;
    if (_panelDialogs.some(entry => entry.root === root)) return;
    const dialog = root.querySelector('[role="dialog"],.modal') || root.firstElementChild || root;
    const opener = document.activeElement;
    if (!_panelDialogs.length) _panelSavedOverflow = document.body.style.overflow;
    panelRestoreInert();
    root.hidden = false;
    root.classList.remove('hidden');
    dialog.setAttribute('role', 'dialog');
    dialog.setAttribute('aria-modal', 'true');
    dialog.setAttribute('tabindex', '-1');
    const title = dialog.querySelector('.modal-title,h1,h2,h3,h4,[data-dialog-title],b');
    if (!dialog.hasAttribute('aria-labelledby') && !dialog.hasAttribute('aria-label')) {
        if (title) dialog.setAttribute('aria-labelledby', panelElementId(title, 'panel-dialog-title'));
        else dialog.setAttribute('aria-label', t('app.title'));
    }
    const description = dialog.querySelector('[data-dialog-description],.modal-description,p');
    if (description && !dialog.hasAttribute('aria-describedby')) {
        dialog.setAttribute('aria-describedby', panelElementId(description, 'panel-dialog-description'));
    }
    const entry = {root, dialog, opener, options};
    _panelDialogs.push(entry);
    refreshPanelAccessibility(root);
    const preferred = typeof options.initialFocus === 'string' ? document.getElementById(options.initialFocus) : options.initialFocus;
    const focusable = panelDialogFocusables(dialog);
    (focusable.includes(preferred) ? preferred : focusable[0] || dialog).focus();
    panelApplyInert();
}

function closePanelDialog(target) {
    const root = typeof target === 'string' ? document.getElementById(target) : target;
    if (!root) return;
    const index = _panelDialogs.findIndex(entry => entry.root === root);
    if (index < 0) { root.classList.add('hidden'); return; }
    const wasTop = index === _panelDialogs.length - 1;
    const [entry] = _panelDialogs.splice(index, 1);
    if (entry.options.removeOnClose) root.remove();
    else root.classList.add('hidden');
    panelApplyInert();
    if (!wasTop) return;
    const top = _panelDialogs.at(-1);
    if (panelElementVisible(entry.opener) && !entry.opener.disabled && (!top || top.dialog.contains(entry.opener))) {
        entry.opener.focus();
    } else if (top) {
        (panelDialogFocusables(top.dialog)[0] || top.dialog).focus();
    } else {
        const fallback = document.querySelector('.nav-btn.active,main');
        if (fallback && panelElementVisible(fallback)) fallback.focus();
    }
}

function dismissPanelDialog() {
    const entry = _panelDialogs.at(-1);
    if (!entry) return;
    if (entry.options.onDismiss) entry.options.onDismiss();
    else closePanelDialog(entry.root);
}

function panelDialogKeydown(event) {
    const entry = _panelDialogs.at(-1);
    if (!entry || event.isComposing) return;
    if (event.key === 'Escape') {
        event.preventDefault();
        event.stopImmediatePropagation();
        dismissPanelDialog();
    } else if (event.key === 'Tab') {
        const focusable = panelDialogFocusables(entry.dialog);
        const first = focusable[0] || entry.dialog;
        const last = focusable.at(-1) || entry.dialog;
        if (!focusable.length || !focusable.includes(document.activeElement)) {
            event.preventDefault();
            (event.shiftKey ? last : first).focus();
        } else if (event.shiftKey && document.activeElement === first) {
            event.preventDefault(); last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault(); first.focus();
        }
    }
}

function panelAccessibilityNodes(root, selector) {
    return [...(root.matches?.(selector) ? [root] : []), ...root.querySelectorAll(selector)];
}

function refreshPanelAccessibility(root = document) {
    panelAccessibilityNodes(root, 'label:not([for])').forEach(label => {
        if (label.querySelector('input,select,textarea')) return;
        const next = label.nextElementSibling;
        const control = next?.matches('input,select,textarea') ? next
            : next?.querySelectorAll('input,select,textarea').length === 1 ? next.querySelector('input,select,textarea') : null;
        if (control) label.setAttribute('for', panelElementId(control, 'panel-input'));
    });
    panelAccessibilityNodes(root, '.toggle').forEach(control => {
        control.setAttribute('role', 'switch');
        if (!control.hasAttribute('tabindex')) control.setAttribute('tabindex', '0');
        const checked = String(control.classList.contains('active'));
        if (control.getAttribute('aria-checked') !== checked) control.setAttribute('aria-checked', checked);
        if (!control.hasAttribute('aria-label') && !control.hasAttribute('aria-labelledby')) {
            const sibling = [control.previousElementSibling, control.nextElementSibling].find(node =>
                node?.matches('label,span,[data-i18n]') && node.textContent.trim());
            if (sibling) control.setAttribute('aria-labelledby', panelElementId(sibling));
        }
    });
    const controls = panelAccessibilityNodes(root, 'input,select,textarea,.toggle');
    const labeledIds = controls.length ? new Set([...document.querySelectorAll('label[for]')].map(label => label.getAttribute('for'))) : new Set();
    controls.forEach(control => {
        if ((control.id && labeledIds.has(control.id)) || control.closest('label') || control.hasAttribute('aria-label') || control.hasAttribute('aria-labelledby')) return;
        const key = PANEL_CONTROL_LABELS[control.id] ? `ui.field.${PANEL_CONTROL_LABELS[control.id]}`
            : control.getAttribute('data-i18n-placeholder');
        if (key && hasTranslation(key)) {
            control.setAttribute('data-i18n-aria-label', key);
            control.setAttribute('aria-label', t(key));
        }
    });
    panelAccessibilityNodes(root, '.table-wrap,.bot-files-editor,.panel-overflow-surface').forEach(surface => {
        if (!surface.hasAttribute('tabindex')) surface.setAttribute('tabindex', '0');
        if (!surface.hasAttribute('role')) surface.setAttribute('role', 'region');
        if (!surface.hasAttribute('aria-label') && !surface.hasAttribute('aria-labelledby')) {
            const title = surface.closest('.card')?.querySelector('.card-title');
            if (title) surface.setAttribute('aria-labelledby', panelElementId(title));
            else {
                const key = surface.classList.contains('bot-files-editor') ? 'ui.editor_region' : 'ui.table_region';
                surface.setAttribute('data-i18n-aria-label', key);
                surface.setAttribute('aria-label', t(key));
            }
        }
    });
    panelAccessibilityNodes(root, '[data-i18n-title]').forEach(control => {
        if (!control.matches('button,[role="button"],input,select,textarea') || control.hasAttribute('aria-labelledby')) return;
        if (!control.textContent.trim() || !/[\p{L}\p{N}]/u.test(control.textContent)) {
            control.setAttribute('data-i18n-aria-label', control.getAttribute('data-i18n-title'));
            control.setAttribute('aria-label', t(control.getAttribute('data-i18n-title')));
        }
    });
    panelAccessibilityNodes(root, '.empty-state,.error-state,[data-status-region]').forEach(region => {
        if (region.hasAttribute('aria-live') || region.parentElement?.closest('[aria-live]')) return;
        region.setAttribute('role', 'status');
        region.setAttribute('aria-live', 'polite');
        region.setAttribute('aria-atomic', 'true');
    });
}

function reconcilePanelDialogs() {
    for (const entry of [..._panelDialogs].reverse()) {
        if (!entry.root.isConnected || entry.root.hidden || entry.root.classList.contains('hidden')) closePanelDialog(entry.root);
    }
    const top = _panelDialogs.at(-1);
    if (top && !top.dialog.contains(document.activeElement)) (panelDialogFocusables(top.dialog)[0] || top.dialog).focus();
}

function initPanelAccessibility() {
    refreshPanelAccessibility();
    document.addEventListener('keydown', panelDialogKeydown, true);
    document.addEventListener('focusin', () => {
        const top = _panelDialogs.at(-1);
        if (top && !top.dialog.contains(document.activeElement)) (panelDialogFocusables(top.dialog)[0] || top.dialog).focus();
    });
    _panelA11yObserver = new MutationObserver(records => {
        _panelA11yObserver.disconnect();
        const roots = new Set();
        for (const record of records) {
            if (record.type === 'childList') {
                for (const node of record.addedNodes) if (node.nodeType === 1 && node.isConnected) roots.add(node);
            } else if (record.target.matches('.toggle')) roots.add(record.target);
        }
        for (const root of roots) {
            if (![...roots].some(other => other !== root && other.contains(root))) refreshPanelAccessibility(root);
        }
        reconcilePanelDialogs();
        _panelA11yObserver.observe(document.body, {childList: true, subtree: true, attributes: true, attributeFilter: ['class', 'hidden']});
    });
    _panelA11yObserver.observe(document.body, {childList: true, subtree: true, attributes: true, attributeFilter: ['class', 'hidden']});
}

document.addEventListener('DOMContentLoaded', initPanelAccessibility);
