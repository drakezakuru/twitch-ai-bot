// ── Channels and bulk bot×channel operations ───────
let _channelOverview = [];
let _bulkDirection = 'bots_to_channels';
let _bulkAccountIds = [];
let _bulkChannelJobId = '';
let _bulkChannelTimer = null;
let _bulkChannelResults = [];
let _channelProfileChannel = '';

async function loadChannelsSection() {
    const el = $('channelsOverview');
    if (!el) return;
    try {
        const [overview, accounts] = await Promise.all([
            api('/api/channel-overview'),
            _allBots.length ? Promise.resolve(_allBots) : api('/api/accounts'),
        ]);
        _channelOverview = overview.channels || [];
        if (!_allBots.length) _allBots = Array.isArray(accounts) ? accounts : (accounts.accounts || []);
        renderChannelsOverview();
    } catch (e) {
        el.innerHTML = `<div class="card text-error p-4">${esc(t('channels.load_failed'))}</div>`;
    }
}

function renderChannelsOverview() {
    const el = $('channelsOverview');
    if (!el) return;
    if (!_channelOverview.length) {
        el.innerHTML = `<div class="card empty-state"><div class="empty-icon">#</div>${esc(t('channels.empty'))}</div>`;
        return;
    }
    el.innerHTML = _channelOverview.map(item => {
        const isConnected = (item.connected_count || 0) > 0;
        return `<div class="card">
        <div class="card-header channel-overview-header"><span class="card-title">#${esc(item.channel)}</span>
            <span class="badge ${isConnected ? 'badge-success' : ''}">${esc(t('channels.connected_count', {connected: item.connected_count, total: item.bot_count}))}</span></div>
        <div class="flex gap-2 flex-wrap mb-3">${item.bots.map(bot => `<span class="badge ${bot.connected ? 'badge-success' : ''}">
            ${bot.connected ? '🟢' : '⚫'} ${esc(bot.nickname)}</span>`).join('')}</div>
        <div class="flex gap-2 flex-wrap items-center">
            <button class="btn btn-success btn-sm" data-channel="${esc(item.channel)}" onclick="startChannelBots(this.dataset.channel)" title="Запустить ботов только на этот канал">▶ Запустить</button>
            <button class="btn btn-secondary btn-sm" data-channel="${esc(item.channel)}" onclick="stopChannelBots(this.dataset.channel)" title="Остановить ботов канала">⏹ Стоп</button>
            <button class="btn btn-secondary btn-sm" data-channel="${esc(item.channel)}" onclick="openChannelFleetModal(this.dataset.channel)" title="Настройки автозапуска, квот и поведения флота">⚡ Автоматизация</button>
            <button class="btn btn-secondary btn-sm" data-channel="${esc(item.channel)}" onclick="openChannelSettings(this.dataset.channel)" data-i18n="channels.settings_btn">⚙️ Настройки</button>
        </div>
    </div>`;
    }).join('');
}

async function startChannelBots(channel) {
    const ch = (channel || '').replace(/^#/, '').toLowerCase();
    if (!ch) return;
    try {
        toast(t('channels.starting_bots', {detail: ch}) || `Запуск ботов для #${ch}...`, 'info');
        const res = await api(`/api/channels/${encodeURIComponent(ch)}/start`, jopts('POST', {}));
        if (!res.ok) throw new Error(res.error || 'start_failed');
        const startedCount = (res.started || []).length;
        const busy = (res.skipped || []).filter(s => s.reason === 'busy_on_other_channel');
        let msg = `Канал #${ch}: запущено ботов: ${startedCount}`;
        if (busy.length > 0) {
            msg += ` (пропущено ${busy.length} занятых на других стримах)`;
        }
        toast(msg, 'success');
        await loadChannelsSection();
        if (typeof loadBotsList === 'function') loadBotsList();
    } catch (e) {
        toast(t('toast.error_detail', {detail: e.message}), 'error');
    }
}

async function stopChannelBots(channel) {
    const ch = (channel || '').replace(/^#/, '').toLowerCase();
    if (!ch) return;
    try {
        const res = await api(`/api/channels/${encodeURIComponent(ch)}/stop`, jopts('POST', {}));
        if (!res.ok) throw new Error(res.error || 'stop_failed');
        const count = (res.stopped || []).length;
        toast(`Канал #${ch}: остановлено ботов: ${count}`, 'info');
        await loadChannelsSection();
        if (typeof loadBotsList === 'function') loadBotsList();
    } catch (e) {
        toast(t('toast.error_detail', {detail: e.message}), 'error');
    }
}

// ── BC-4: добавить / переименовать / удалить канал из секции «Каналы» ──
function openChannelCreateModal() {
    const select = $('channelCreateBot');
    $('channelCreateName').value = '';
    $('channelCreateError').textContent = '';
    select.innerHTML = _allBots.map(bot => `<option value="${esc(bot.id)}">${esc(bot.nickname)}</option>`).join('');
    if (!select.options.length) {
        $('channelCreateError').textContent = t('channels.add_no_bots');
        $('channelCreateSubmit').disabled = true;
    } else {
        $('channelCreateSubmit').disabled = false;
    }
    showModal('channelCreateModal');
}

async function submitChannelCreate() {
    const name = $('channelCreateName').value.trim().replace(/^#/, '');
    const accountId = $('channelCreateBot').value;
    if (!name || !accountId) { $('channelCreateError').textContent = t('channels.add_invalid'); return; }
    try {
        const result = await api(`/api/accounts/${accountId}/channels`, jopts('POST', {channel_name: name}));
        if (result.ok === false) { $('channelCreateError').textContent = t('toast.channel_add_failed'); return; }
        hideModal('channelCreateModal');
        await loadChannelsSection();
        toast(t('toast.channel_added_for', {detail: name}), 'success');
    } catch (e) { $('channelCreateError').textContent = e.message; }
}

function openChannelRenameModal(channel, accountId) {
    const current = String(channel || '').replace(/^#/, '');
    const next = window.prompt(t('channels.rename_prompt'), current);
    if (next === null) return;
    const target = next.trim().replace(/^#/, '');
    if (!target || target === current) return;
    renameChannelBinding(accountId, current, target);
}

async function renameChannelBinding(accountId, current, target) {
    try {
        const rows = await api(`/api/accounts/${accountId}/channels`);
        const list = Array.isArray(rows) ? rows : (rows.channels || []);
        const binding = list.find(row => String(row.channel_name).replace(/^#/, '').toLowerCase() === current.toLowerCase());
        if (!binding) { toast(t('toast.channel_rename_failed'), 'error'); return; }
        let result = await api(`/api/channels/${binding.id}`, jopts('PATCH', {channel_name: target}));
        if (result.ok === false && result.code === 'channel_data_conflict') {
            if (!window.confirm(t('channels.rename_conflict', {tables: (result.tables || []).join(', ')}))) return;
            result = await api(`/api/channels/${binding.id}`, jopts('PATCH', {channel_name: target, force: true}));
        }
        if (result.ok === false) { toast(t('toast.channel_rename_failed'), 'error'); return; }
        if (typeof loadBotChannels === 'function' && _currentBotId == accountId) await loadBotChannels(accountId);
        await loadChannelsSection();
        if (!$('channelSettingsPage')?.classList.contains('hidden')) _renderChannelSettingsBots();
        toast(t('toast.channel_renamed', {detail: target}), 'success');
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

let _channelDeleteBindingId = '';

async function openChannelDeleteModal(bindingId, channel) {
    _channelDeleteBindingId = bindingId;
    const body = $('channelDepsBody');
    body.innerHTML = `<div class="text-muted">${esc(t('label.loading'))}</div>`;
    $('channelDepsConfirm').disabled = true;
    showModal('channelDepsModal');
    try {
        const deps = await api(`/api/channels/${bindingId}/dependencies`);
        if (!deps.ok) { body.innerHTML = `<div class="text-error">${esc(t('channels.deps_failed'))}</div>`; return; }
        const rows = Object.entries(deps.counts || {});
        body.innerHTML = `<p>#${esc(channel)} — ${esc(t('channels.delete_hint'))}</p>` +
            (rows.length
                ? `<ul>${rows.map(([table, count]) => `<li><code>${esc(table)}</code>: ${esc(count)}</li>`).join('')}</ul>
                   <p class="text-error">${esc(t('channels.delete_confirm_data', {total: deps.total}))}</p>`
                : `<p class="text-muted">${esc(t('channels.delete_no_data'))}</p>`);
        $('channelDepsConfirm').disabled = false;
    } catch (e) { body.innerHTML = `<div class="text-error">${esc(e.message)}</div>`; }
}

async function confirmChannelDelete() {
    if (!_channelDeleteBindingId) return;
    try {
        let result = await api(`/api/channels/${_channelDeleteBindingId}`, {method: 'DELETE'});
        if (result.ok === false && result.code === 'channel_has_dependencies') {
            result = await api(`/api/channels/${_channelDeleteBindingId}?force=true`, {method: 'DELETE'});
        }
        if (result.ok === false) { toast(t('toast.channel_delete_failed'), 'error'); return; }
        hideModal('channelDepsModal');
        _channelDeleteBindingId = '';
        await loadChannelsSection();
        if (!$('channelSettingsPage')?.classList.contains('hidden')) _renderChannelSettingsBots();
        if (typeof loadBotsList === 'function') await loadBotsList();
        toast(t('toast.channel_deleted'), 'success');
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

function _resetBulkModal() {
    _bulkChannelResults = [];
    $('bulkCheckMessage').value = t('check.default_message');
    // Q07/DEC-OWNER-011: контрольное сообщение по умолчанию ВЫКЛ.
    $('bulkCheckSendEnabled').checked = false;
    $('bulkCheckMessage').disabled = true;
    $('bulkChannelsResults').innerHTML = '';
    $('bulkChannelsDownloads').classList.add('hidden');
    $('bulkChannelsCancel').classList.add('hidden');
    $('bulkChannelsStart').disabled = false;
}

function openBotsToChannelsBulk() {
    if (!_selectedBots.size) return;
    _bulkDirection = 'bots_to_channels';
    _bulkAccountIds = [..._selectedBots];
    _resetBulkModal();
    $('bulkSelectedBots').textContent = t('common.selected', {count: _bulkAccountIds.length});
    $('bulkBotPicker').classList.add('hidden');
    $('bulkChannelsInput').value = '';
    $('bulkChannelsInput').disabled = false;
    showModal('bulkChannelsModal');
}

// Q08(б): в диалоге добавления боты сгруппированы по ролям, у группы — «выбрать всех».
const _BULK_ROLE_ORDER = ['chatter', 'voice_companion', 'lurker', 'moderator', 'director'];

function _bulkBotChoicesHtml() {
    const byRole = new Map();
    (_allBots || []).forEach(bot => {
        const role = bot.bot_role || 'chatter';
        if (!byRole.has(role)) byRole.set(role, []);
        byRole.get(role).push(bot);
    });
    const roles = [...byRole.keys()].sort((a, b) =>
        (_BULK_ROLE_ORDER.indexOf(a) + _BULK_ROLE_ORDER.length) -
        (_BULK_ROLE_ORDER.indexOf(b) + _BULK_ROLE_ORDER.length));
    return roles.map(role => `
        <div class="mb-2">
            <div class="flex items-center gap-2 mb-1">
                <span class="text-sm font-semibold">${esc(typeof _roleMetaLabel === 'function' ? _roleMetaLabel(role) : role)}</span>
                <button type="button" class="btn btn-sm btn-secondary" onclick="bulkToggleRole('${role}', this)"
                    data-i18n="bulk.select_all" aria-label="${esc(t('bulk.select_all'))}">${esc(t('bulk.select_all'))}</button>
            </div>
            <div class="flex gap-2 flex-wrap">${byRole.get(role).map(bot => `
                <label class="badge"><input type="checkbox" data-bulk-bot="${bot.id}" data-bulk-role="${role}"> ${esc(bot.nickname)}</label>`).join('')}
            </div>
        </div>`).join('');
}

function bulkToggleRole(role, button) {
    const boxes = [...document.querySelectorAll(`input[data-bulk-role="${role}"]`)];
    const allChecked = boxes.length && boxes.every(box => box.checked);
    boxes.forEach(box => { box.checked = !allChecked; });
    if (button) button.textContent = t(allChecked ? 'bulk.select_all' : 'bulk.deselect_all');
}

function openChannelToBotsBulk(channel) {
    _bulkDirection = 'channel_to_bots';
    _bulkAccountIds = [];
    _resetBulkModal();
    $('bulkSelectedBots').textContent = '';
    $('bulkBotPicker').classList.remove('hidden');
    $('bulkBotChoices').innerHTML = _bulkBotChoicesHtml();
    $('bulkChannelsInput').value = channel;
    $('bulkChannelsInput').disabled = true;
    showModal('bulkChannelsModal');
}

function _bulkSelectedAccountIds() {
    if (_bulkDirection === 'bots_to_channels') return [..._bulkAccountIds];
    return [...document.querySelectorAll('[data-bulk-bot]:checked')].map(input => Number(input.dataset.bulkBot));
}

function bulkCheckSendToggled() {
    const enabled = $('bulkCheckSendEnabled')?.checked;
    const input = $('bulkCheckMessage');
    if (input) input.disabled = !enabled;
}

async function startBulkChannels() {
    const accountIds = _bulkSelectedAccountIds();
    const channels = $('bulkChannelsInput').value.split(/[\s,]+/).map(value => value.trim().replace(/^#/, '')).filter(Boolean);
    const sendEnabled = !!$('bulkCheckSendEnabled')?.checked;
    const message = $('bulkCheckMessage').value.trim();
    if (!accountIds.length || !channels.length || (sendEnabled && !message)) { toast(t('bulk.invalid_input'), 'error'); return; }
    try {
        const job = await api('/api/bulk/channels', jopts('POST', {
            direction: _bulkDirection, account_ids: accountIds, channels, message_template: message, send_message: sendEnabled,
        }));
        if (!job.ok) { toast(t(`bulk.error.${job.code || 'bulk_failed'}`), 'error'); return; }
        _bulkChannelJobId = job.job_id;
        $('bulkChannelsStart').disabled = true;
        $('bulkChannelsCancel').classList.remove('hidden');
        $('bulkChannelsResults').innerHTML = `<div class="text-muted p-3">${esc(t('bulk.running'))}</div>`;
        clearInterval(_bulkChannelTimer);
        _bulkChannelTimer = setInterval(pollBulkChannels, 1000);
        await pollBulkChannels();
    } catch (e) { toast(t('toast.error_detail', {detail: e.message}), 'error'); }
}

async function pollBulkChannels() {
    if (!_bulkChannelJobId) return;
    try {
        const job = await api(`/api/bulk/channels/${_bulkChannelJobId}`);
        if (job.status === 'running') return;
        clearInterval(_bulkChannelTimer);
        _bulkChannelTimer = null;
        $('bulkChannelsCancel').classList.add('hidden');
        $('bulkChannelsStart').disabled = false;
        _bulkChannelResults = job.results || [];
        renderBulkChannelResults(job.status);
        if (job.status === 'completed') {
            await loadChannelsSection();
            await loadBotsList();
        }
    } catch (e) {
        clearInterval(_bulkChannelTimer);
        _bulkChannelTimer = null;
        toast(t('toast.error_detail', {detail: e.message}), 'error');
    }
}

async function cancelBulkChannels() {
    if (!_bulkChannelJobId) return;
    await api(`/api/bulk/channels/${_bulkChannelJobId}/cancel`, jopts('POST', {}));
    await pollBulkChannels();
}

function renderBulkChannelResults(status) {
    if (!_bulkChannelResults.length) {
        $('bulkChannelsResults').innerHTML = `<div class="text-muted p-3">${esc(t(`bulk.${status}`))}</div>`;
        return;
    }
    $('bulkChannelsResults').innerHTML = `<div class="table-wrap"><table><thead><tr>
        <th>${esc(t('check.col.bot'))}</th><th>${esc(t('bulk.col.channel'))}</th>
        <th>${esc(t('bulk.col.add'))}</th><th>${esc(t('bulk.col.check'))}</th>
    </tr></thead><tbody>${_bulkChannelResults.map(item => `<tr>
        <td>${esc(item.nickname || `#${item.account_id}`)}</td><td>#${esc(item.channel)}</td>
        <td>${esc(t(`bulk.value.${item.add_result}`))}: ${esc(t(`bulk.reason.${item.add_reason}`))}</td>
        <td>${esc(t(`check.value.${item.check_result}`))}: ${esc(t(`check.reason.${item.check_reason}`))}</td>
    </tr>`).join('')}</tbody></table></div>`;
    $('bulkChannelsDownloads').classList.remove('hidden');
}

function downloadBulkChannels(format) {
    if (!_bulkChannelResults.length) return;
    let body;
    let type;
    if (format === 'csv') {
        const quote = value => `"${String(value ?? '').replaceAll('"', '""')}"`;
        const rows = [['bot', 'channel', 'add_result', 'add_reason', 'token', 'join', 'read', 'send', 'check_result', 'check_reason'],
            ..._bulkChannelResults.map(item => [item.nickname, item.channel, item.add_result, item.add_reason,
                item.token_status, item.join_status, item.read_status, item.send_status, item.check_result, item.check_reason])];
        body = rows.map(row => row.map(quote).join(',')).join('\n');
        type = 'text/csv;charset=utf-8';
    } else {
        body = _bulkChannelResults.map(item => `${item.nickname || `#${item.account_id}`} @ #${item.channel}: ${t(`bulk.value.${item.add_result}`)} — ${t(`check.value.${item.check_result}`)} (${t(`check.reason.${item.check_reason}`)})`).join('\n');
        type = 'text/plain;charset=utf-8';
    }
    const link = document.createElement('a');
    link.href = URL.createObjectURL(new Blob([body], {type}));
    link.download = `bulk-channels-${Date.now()}.${format === 'csv' ? 'csv' : 'txt'}`;
    link.click();
    URL.revokeObjectURL(link.href);
}


// ── Q26 (DEC-OWNER-014): вкладка «Модерация» канала — очередь подтверждения,
// журнал наказаний, список защищённых, «Разбанить». Только панель владельца:
// ни всплывашек, ни модераторского сайта, ни авто-отмены наказаний. ──
let _channelModChannel = '';

const _modDuration = sec => {
    if (sec == null) return t('channels.mod_action_ban');
    const m = Math.round(sec / 60);
    if (m < 60) return `${t('channels.mod_action_timeout')} ${m} мин`;
    const h = Math.round(m / 60);
    if (h < 24) return `${t('channels.mod_action_timeout')} ${h} ч`;
    return `${t('channels.mod_action_timeout')} ${Math.round(h / 24)} дн`;
};

const _modStatusBadge = s => ({
    applied: 'badge-success', pending: 'badge-warning',
    cancelled: 'badge-off', expired: 'badge-off',
}[s] || '');

// ── Владелец 27.09 → уточнение 27.09: настоящая единая страница на канал
// со ВСЕМИ настройками (боты / правила / модерация / профиль), одна кнопка
// «⚙️ Настройки канала» в карточке вместо отдельных кнопок на каждую вкладку ──
const CHANNEL_SETTINGS_TABS = ['bots', 'rules', 'moderation', 'profile'];
let _channelSettingsLoaded = { bots: false, rules: false, moderation: false, profile: false };
let _channelSettingsChannel = '';

function openChannelSettingsPage(tab) {
    $('channelsListView')?.classList.add('hidden');
    $('channelSettingsPage')?.classList.remove('hidden');
    _channelSettingsLoaded = { bots: false, rules: false, moderation: false, profile: false };
    showChannelSettingsTab(tab);
}

function closeChannelSettings() {
    $('channelSettingsPage')?.classList.add('hidden');
    $('channelsListView')?.classList.remove('hidden');
}

function showChannelSettingsTab(tab) {
    if (!CHANNEL_SETTINGS_TABS.includes(tab)) return;
    for (const name of CHANNEL_SETTINGS_TABS) {
        $('channelSettingsTab' + name[0].toUpperCase() + name.slice(1))?.classList.toggle('hidden', name !== tab);
    }
    document.querySelectorAll('.channel-settings-tab-btn').forEach(b => {
        const isActive = b.dataset.channelTab === tab;
        b.classList.toggle('btn-primary', isActive);
        b.classList.toggle('btn-secondary', !isActive);
    });
    if (!_channelSettingsLoaded[tab]) {
        _channelSettingsLoaded[tab] = true;
        if (tab === 'bots') _renderChannelSettingsBots();
        if (tab === 'rules') loadChannelBaseRules();
        if (tab === 'moderation') loadChannelModeration();
        if (tab === 'profile') {
            loadGlobalStreamerProfile('ccp');
            cpLoadLore();
            cpLoadSummarySettings();
            cpLoadBans();
            cpLoadAllowed();
            cpLoadRuns();
        }
    }
}

// ── Единая точка входа: карточка канала теперь ведёт сюда одной кнопкой,
// внутри — все 4 вкладки настроек канала сразу ──
function openChannelSettings(channel, tab) {
    const ch = (channel || '').replace(/^#/, '').toLowerCase();
    _channelSettingsChannel = ch;
    _primeChannelBaseRules(ch);
    _primeChannelModeration(ch);
    _primeChannelProfile(ch);
    _loadChannelEmotes(ch);
    openChannelSettingsPage(tab || 'bots');
}

function _channelSettingsItem(ch) {
    return _channelOverview.find(i => (i.channel || '').replace(/^#/, '').toLowerCase() === ch);
}

function _renderChannelSettingsBots() {
    const box = $('channelSettingsBotsList');
    if (!box) return;
    const item = _channelSettingsItem(_channelSettingsChannel);
    box.innerHTML = (item?.bots || []).map(bot => `<span class="badge ${bot.connected ? 'badge-success' : ''}"
        data-binding-id="${esc(bot.binding_id)}" title="${esc(t('channels.binding_actions'))}">
        ${bot.connected ? '🟢' : '⚫'} ${esc(bot.nickname)}
        <button class="btn btn-sm btn-secondary" data-channel="${esc(_channelSettingsChannel)}" data-account="${esc(bot.account_id)}"
            onclick="openChannelRenameModal(this.dataset.channel, this.dataset.account)" data-i18n-aria-label="channels.rename" aria-label="${esc(t('channels.rename'))}">✎</button>
        <button class="btn btn-sm btn-danger" data-binding="${esc(bot.binding_id)}" data-channel="${esc(_channelSettingsChannel)}"
            onclick="openChannelDeleteModal(this.dataset.binding, this.dataset.channel)" data-i18n-aria-label="channels.delete" aria-label="${esc(t('channels.delete'))}">✕</button>
    </span>`).join('') || `<div class="text-muted text-sm">${esc(t('channels.bots_tab_empty'))}</div>`;
}

function _primeChannelBaseRules(ch) {
    _channelBaseRulesChannel = ch;
    const label = $('channelBaseRulesChannel');
    if (label) label.textContent = '#' + ch;
}

function _primeChannelModeration(ch) {
    _channelModChannel = ch;
    const label = $('channelModerationChannel');
    if (label) label.textContent = '#' + ch;
    const item = _channelSettingsItem(ch);
    const sel = $('channelModerationBot');
    if (sel) {
        sel.innerHTML = (item?.bots || []).map(b =>
            `<option value="${esc(b.account_id)}">${esc(b.nickname)}</option>`).join('');
    }
}

function _primeChannelProfile(ch) {
    _channelProfileChannel = ch;
    const label = $('channelProfileChannel');
    if (label) label.textContent = '#' + ch;
    const hidden = $('ccpChannel');
    if (hidden) hidden.value = '#' + ch;
    const item = _channelSettingsItem(ch);
    const sel = $('channelProfileBot');
    if (sel) {
        sel.innerHTML = (item?.bots || []).map(b =>
            `<option value="${esc(b.account_id)}">${esc(b.nickname)}</option>`).join('');
    }
}

// Оставлены для обратной совместимости и точечного открытия конкретной
// вкладки (напр. из настроек бота); карточка канала теперь ведёт через
// единый openChannelSettings().
function openChannelModeration(channel) {
    const ch = (channel || '').replace(/^#/, '').toLowerCase();
    _channelSettingsChannel = ch;
    _primeChannelModeration(ch);
    openChannelSettingsPage('moderation');
}

// ── Q09a: вкладка «Профиль канала» — инфо о стримере per-channel (тот же
// префиксный редактор, что был в «Мозге»: loadGlobalStreamerProfile('ccp')) ──
function openChannelProfile(channel) {
    const ch = (channel || '').replace(/^#/, '').toLowerCase();
    _channelSettingsChannel = ch;
    _primeChannelProfile(ch);
    openChannelSettingsPage('profile');
}

// ── Q09b: lore в модалке «Профиль канала» — per (бот × канал), тот же API,
// что был в «Мозге» (/api/accounts/{acc}/lore); скоуп-бейджи не нужны —
// модалка всегда про конкретный канал ──
function _channelProfileBotId() {
    const v = $('channelProfileBot')?.value;
    return v ? parseInt(v, 10) : null;
}

async function cpLoadLore() {
    const box = $('cpLoreList');
    const acc = _channelProfileBotId();
    if (!box || !acc || !_channelProfileChannel) return;
    try {
        const res = await api(`/api/accounts/${acc}/lore?channel=${encodeURIComponent(_channelProfileChannel)}&limit=100`);
        const items = res.items || [];
        if (!items.length) { box.innerHTML = `<div class="empty-state text-muted text-sm">${panelI18n('sharedfacts.empty')}</div>`; return; }
        box.innerHTML = items.map(it => {
            const st = it.status || 'suggested';
            const badge = st === 'approved' ? `<span class="badge badge-success">${panelI18n('dynamic.status.approved')}</span>`
                : st === 'rejected' ? `<span class="badge">${panelI18n('dynamic.status.rejected')}</span>`
                : `<span class="badge badge-warning">${panelI18n('dynamic.status.suggested')}</span>`;
            const acts = [];
            if (st !== 'approved') acts.push(`<button class="btn btn-sm btn-primary" ${panelI18nAttrs('dynamic.approve')} onclick="cpLoreAct(${it.id}, 'approve')">✓</button>`);
            if (st !== 'rejected') acts.push(`<button class="btn btn-sm btn-secondary" ${panelI18nAttrs('dynamic.reject')} onclick="cpLoreAct(${it.id}, 'reject')">✕</button>`);
            acts.push(`<button class="btn btn-sm btn-secondary" ${panelI18nAttrs('btn.delete')} onclick="cpLoreDelete(${it.id})">🗑</button>`);
            return `<div class="p-2 mb-1" style="border-bottom:1px solid var(--border)">
                <div class="flex justify-between items-start gap-2">
                    <div><div class="text-sm" data-user-content>${esc(it.fact)}</div>
                    <div class="text-xs text-muted">${panelI18n('dynamic.source')}: ${panelEnumI18n('brain.src.', it.source)} · ${panelI18n('sharedfacts.confidence')} ${(it.confidence ?? 0).toFixed(2)} · ${panelI18n('dynamic.importance')} ${it.importance ?? 50}${it.evidence ? ' · ' + esc(it.evidence) : ''}</div></div>
                    <div class="flex gap-1 items-center">${badge}${acts.join('')}</div>
                </div></div>`;
        }).join('');
    } catch (e) { box.innerHTML = `<div class="text-error text-sm">${esc(e.message)}</div>`; }
}

function cpLoreShowAdd() { $('cpLoreAddForm')?.classList.remove('hidden'); }
function cpLoreHideAdd() { $('cpLoreAddForm')?.classList.add('hidden'); }

async function cpLoreAdd(approved) {
    const acc = _channelProfileBotId();
    if (!acc) return toast(t('dynamic.pick_bot'), 'error');
    const fact = $('cpLoreNewFact')?.value.trim();
    if (!fact) return toast(t('dynamic.enter_fact'), 'error');
    const importance = parseInt($('cpLoreNewImportance')?.value || '50', 10);
    const source = $('cpLoreNewSource')?.value || 'manual';
    const res = await api(`/api/accounts/${acc}/lore`, jopts('POST', { fact, importance, source, channel: _channelProfileChannel, approved }));
    if (res.ok) { toast(t('dynamic.fact_added'), 'success'); $('cpLoreNewFact').value = ''; cpLoreHideAdd(); cpLoadLore(); }
    else toast(res.error || t('label.error'), 'error');
}

async function cpLoreAct(id, action) {
    const acc = _channelProfileBotId(); if (!acc) return;
    const res = await api(`/api/accounts/${acc}/lore/${id}/${action}`, jopts('POST', {}));
    if (res.ok) cpLoadLore(); else toast(res.error || t('label.error'), 'error');
}

async function cpLoreDelete(id) {
    const acc = _channelProfileBotId(); if (!acc) return;
    const res = await api(`/api/accounts/${acc}/lore/${id}`, jopts('DELETE', {}));
    if (res.ok) cpLoadLore(); else toast(res.error || t('label.error'), 'error');
}

// ── Q09c: live-сводки per-канал в модалке «Профиль канала» — override
// настроек бота (§2.3), статус честный: override канала или наследуется ──
async function cpLoadSummarySettings() {
    const acc = _channelProfileBotId();
    if (!acc || !_channelProfileChannel) return;
    try {
        const res = await api(`/api/accounts/${acc}/summarizer/settings?channel=${encodeURIComponent(_channelProfileChannel)}`);
        if (!res.ok) return;
        setToggle('cpSumLiveEnabled', !!res.live_enabled);
        const lg = $('cpSumLiveLang');
        if (lg) lg.value = res.live_lang === 'en' ? 'en' : 'ru';
        const st = $('cpSumLiveScopeStatus');
        if (st) st.innerHTML = res.scope === 'channel'
            ? `${panelI18n('dynamic.scope_override')} #${esc(res.channel)}` : panelI18n('dynamic.scope_inherited');
    } catch (e) { /* некритично */ }
}

async function cpSaveSummarySettings() {
    const acc = _channelProfileBotId();
    if (!acc) return toast(t('dynamic.pick_bot'), 'error');
    const body = {
        live_enabled: toggleChecked('cpSumLiveEnabled'),
        live_lang: $('cpSumLiveLang')?.value || 'ru',
        channel: _channelProfileChannel,
    };
    const res = await api(`/api/accounts/${acc}/summarizer/settings`, jopts('POST', body));
    if (res.ok) toast(t('dynamic.channel_saved', { channel: '#' + _channelProfileChannel }), 'success');
    else toast(res.error || t('label.error'), 'error');
    cpLoadSummarySettings();
}

// ── Q18b: запретные темы per-канал + базовый пресет Twitch (DEC-OWNER-004).
// Канал без своего списка наследует пресет — бейдж и кнопка «Взять пресет». ──
async function cpLoadBans() {
    if (!_channelProfileChannel) return;
    try {
        const [ch, preset] = await Promise.all([
            api(`/api/bans/channel?channel=${encodeURIComponent(_channelProfileChannel)}`),
            api('/api/bans/preset'),
        ]);
        const box = $('cpBansText');
        if (box) box.value = ch.text || '';
        const badge = $('cpBansSourceBadge');
        if (badge) badge.innerHTML = ch.source === 'channel'
            ? panelI18n('dynamic.scope_override')
            : panelI18n('channels.bans_inherited');
        const presetBox = $('cpBansPresetText');
        if (presetBox && document.activeElement !== presetBox) presetBox.value = preset.text || '';
    } catch (e) { /* некритично */ }
}

async function cpSaveBans() {
    if (!_channelProfileChannel) return;
    try {
        const res = await api('/api/bans/channel', jopts('PUT', {
            channel: _channelProfileChannel,
            text: $('cpBansText')?.value || '',
        }));
        if (!res.ok) throw new Error(res.error || 'error');
        toast(t('msg.saved'), 'success');
        cpLoadBans();
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

function cpSeedBansFromPreset() {
    const preset = $('cpBansPresetText')?.value || '';
    const box = $('cpBansText');
    if (box) box.value = preset;
}

async function cpSaveBansPreset() {
    try {
        const res = await api('/api/bans/preset', jopts('PUT', { text: $('cpBansPresetText')?.value || '' }));
        if (!res.ok) throw new Error(res.error || 'error');
        toast(t('msg.saved'), 'success');
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

// ── Разрешённые темы и поведение ботов per-канал + базовый пресет Twitch.
// Канал без своего списка наследует пресет — бейдж и кнопка «Взять пресет». ──
async function cpLoadAllowed() {
    if (!_channelProfileChannel) return;
    try {
        const [ch, preset] = await Promise.all([
            api(`/api/allowed-topics/channel?channel=${encodeURIComponent(_channelProfileChannel)}`),
            api('/api/allowed-topics/preset'),
        ]);
        const box = $('cpAllowedText');
        if (box) box.value = ch.text || '';
        const badge = $('cpAllowedSourceBadge');
        if (badge) badge.innerHTML = ch.source === 'channel'
            ? panelI18n('dynamic.scope_override')
            : panelI18n('channels.allowed_inherited');
        const presetBox = $('cpAllowedPresetText');
        if (presetBox && document.activeElement !== presetBox) presetBox.value = preset.text || '';
    } catch (e) { /* некритично */ }
}

async function cpSaveAllowed() {
    if (!_channelProfileChannel) return;
    try {
        const res = await api('/api/allowed-topics/channel', jopts('PUT', {
            channel: _channelProfileChannel,
            text: $('cpAllowedText')?.value || '',
        }));
        if (!res.ok) throw new Error(res.error || 'error');
        toast(t('msg.saved'), 'success');
        cpLoadAllowed();
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

function cpSeedAllowedFromPreset() {
    const preset = $('cpAllowedPresetText')?.value || '';
    const box = $('cpAllowedText');
    if (box) box.value = preset;
}

async function cpSaveAllowedPreset() {
    try {
        const res = await api('/api/allowed-topics/preset', jopts('PUT', { text: $('cpAllowedPresetText')?.value || '' }));
        if (!res.ok) throw new Error(res.error || 'error');
        toast(t('msg.saved'), 'success');
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}


// ── Q19: браузер прогонов сводок переехал из «Мозга» в модалку канала —
// те же эндпоинты /api/accounts/{acc}/summarizer/runs, но контекст —
// выбранный бот + канал модалки ──
async function cpLoadRuns() {
    const box = $('cpRunsList');
    const acc = _channelProfileBotId();
    if (!box || !acc || !_channelProfileChannel) return;
    try {
        const res = await api(`/api/accounts/${acc}/summarizer/runs?channel=${encodeURIComponent(_channelProfileChannel)}&limit=30`);
        const items = res.items || [];
        if (!items.length) { box.innerHTML = `<div class="empty-state text-muted text-sm">${panelI18n('brain.runs_empty')}</div>`; return; }
        box.innerHTML = items.map(r => {
            const st = r.status || 'pending';
            const badge = st === 'done' ? `<span class="badge badge-success">${panelI18n('dynamic.status.done')}</span>`
                : st === 'failed' ? `<span class="badge" style="color:#e74c3c">${panelI18n('dynamic.status.failed')}</span>`
                : st === 'running' ? `<span class="badge badge-warning">${panelI18n('dynamic.status.running')}</span>`
                : `<span class="badge">${panelI18n('dynamic.status.pending')}</span>`;
            return `<div class="p-2 mb-1 flex justify-between items-center gap-2" style="border-bottom:1px solid var(--border)">
                <div class="text-sm">${badge} <b>${esc(r.channel)}</b> · ${esc(r.run_date)} · ${esc(String(r.period_start || '').slice(0, 16))} → ${esc(String(r.period_end || '').slice(0, 16))}
                ${st === 'failed' && r.error ? ` · <span class="text-error">${esc(r.error)}</span>` : ''}</div>
                <div class="flex gap-1">
                    <button class="btn btn-sm btn-secondary" onclick="cpViewRun(${r.id})">${panelI18n('clips.open')}</button>
                    <button class="btn btn-sm btn-secondary" ${panelI18nAttrs('btn.delete')} onclick="cpDeleteRun(${r.id})">🗑</button>
                </div></div>`;
        }).join('');
    } catch (e) { box.innerHTML = `<div class="text-error text-sm">${esc(e.message)}</div>`; }
}

function cpRunsShowForm() {
    const f = $('cpRunsForm');
    if (!f) return;
    const end = new Date(); const start = new Date(end.getTime() - 3 * 3600 * 1000);
    const fmt = d => new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
    const ps = $('cpRunStart'); if (ps) ps.value = fmt(start);
    const pe = $('cpRunEnd'); if (pe) pe.value = fmt(end);
    const lang = $('cpRunLang');
    if (lang) lang.value = panelLang === 'en' ? 'en' : 'ru';
    f.classList.remove('hidden');
}
function cpRunsHideForm() { $('cpRunsForm')?.classList.add('hidden'); }

async function cpStartRun() {
    const acc = _channelProfileBotId();
    if (!acc) return toast(t('dynamic.pick_bot'), 'error');
    const ps = $('cpRunStart')?.value;
    const pe = $('cpRunEnd')?.value;
    if (!ps || !pe) return toast(t('dynamic.run_period'), 'error');
    const lang = $('cpRunLang')?.value || 'ru';
    const res = await api(`/api/accounts/${acc}/summarizer/runs`, jopts('POST', {
        channel: _channelProfileChannel, period_start: ps + ':00Z', period_end: pe + ':00Z', lang,
    }));
    if (res.ok) { toast(t('dynamic.run_started'), 'success'); cpRunsHideForm(); cpLoadRuns(); }
    else toast(res.error || t('label.error'), 'error');
}

async function cpViewRun(runId) {
    const acc = _channelProfileBotId();
    const view = $('cpRunView');
    if (!acc || !view) return;
    try {
        const res = await api(`/api/accounts/${acc}/summarizer/runs/${runId}`);
        const r = res.run || {};
        view.classList.remove('hidden');
        view.innerHTML = `<div class="p-3 form-panel">
            <div class="flex justify-between items-center mb-2">
                <b class="text-sm">${esc(r.channel)} · ${esc(r.run_date)}</b>
                <button class="btn btn-sm btn-secondary" onclick="cpHideRunView()">✕</button>
            </div>
            <div class="flex gap-1 mb-2">
                <button class="btn btn-sm btn-secondary" onclick="cpExportRun(${r.id}, 'md')">⬇ MD</button>
                <button class="btn btn-sm btn-secondary" onclick="cpExportRun(${r.id}, 'json')">⬇ JSON</button>
            </div>
            <pre class="text-sm" style="white-space:pre-wrap; max-height:420px; overflow:auto">${r.summary_md ? esc(r.summary_md) : panelI18n('dynamic.empty')}</pre>
        </div>`;
    } catch (e) { toast(e.message, 'error'); }
}

function cpHideRunView() { $('cpRunView')?.classList.add('hidden'); }

async function cpDeleteRun(runId) {
    const acc = _channelProfileBotId(); if (!acc) return;
    const res = await api(`/api/accounts/${acc}/summarizer/runs/${runId}`, jopts('DELETE', {}));
    if (res.ok) cpLoadRuns(); else toast(res.error || t('label.error'), 'error');
}

async function cpExportRun(runId, fmt) {
    const acc = _channelProfileBotId(); if (!acc) return;
    try {
        const res = await api(`/api/accounts/${acc}/summarizer/runs/${runId}`);
        if (!res.ok) return toast(res.error || t('api.error.not_found'), 'error');
        const r = res.run;
        if (fmt === 'json') {
            _brainDownload(`summary_${r.channel}_${r.run_date}.json`, JSON.stringify(r, null, 2), 'application/json');
        } else {
            _brainDownload(`summary_${r.channel}_${r.run_date}.md`, r.summary_md || '', 'text/markdown');
        }
    } catch (e) { toast(e.message, 'error'); }
}

function _channelModQuery() {
    const accId = $('channelModerationBot')?.value || '';
    return `channel=${encodeURIComponent(_channelModChannel)}${accId ? `&account_id=${accId}` : ''}`;
}

async function loadChannelModeration() {
    if (!_channelModChannel) return;
    const q = _channelModQuery();
    loadChannelModQueue(q);
    loadChannelModJournal(q);
    loadChannelModProtected(q);
}

async function loadChannelModQueue(q) {
    const el = $('channelModQueue');
    if (!el) return;
    try {
        const data = await api(`/api/moderation/journal/pending?${q}`);
        el.innerHTML = (data.entries || []).map(e => `
            <div class="flex gap-2 items-center text-sm flex-wrap">
                <strong>${esc(e.username || '?')}</strong>
                <span class="badge">${esc(_modDuration(e.duration_sec))}</span>
                <span class="text-muted text-truncate">${esc(e.rule_name || '')}${e.detail ? ` · ${esc(e.detail)}` : ''}</span>
                <button class="btn btn-sm btn-danger ml-auto" onclick="resolveChannelModCase(${e.id}, true)" data-i18n="channels.mod_queue_ban">Забанить</button>
                <button class="btn btn-sm btn-secondary" onclick="resolveChannelModCase(${e.id}, false)" data-i18n="channels.mod_queue_pardon">Не наказывать</button>
            </div>`).join('') || `<div class="text-muted text-sm">${esc(t('channels.mod_queue_empty'))}</div>`;
    } catch (e) { el.innerHTML = `<div class="text-error text-sm">${esc(t('channels.load_failed'))}</div>`; }
}

async function resolveChannelModCase(entryId, approve) {
    try {
        const res = await api(`/api/moderation/journal/${entryId}/resolve`, jopts('POST', { approve: !!approve }));
        if (res.ok === false) { toast(t('toast.error_detail', { detail: res.error }), 'error'); return; }
        toast(t(approve ? 'channels.mod_resolved_yes' : 'channels.mod_resolved_no'), 'success');
        loadChannelModeration();
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

async function loadChannelModJournal(q) {
    const el = $('channelModJournal');
    if (!el) return;
    try {
        const data = await api(`/api/moderation/journal?${q}`);
        el.innerHTML = (data.entries || []).map(e => `
            <div class="flex gap-2 items-center text-sm">
                <span class="text-muted">${esc((e.created_at || '').replace('T', ' ').slice(5, 16))}</span>
                <strong class="cursor-pointer hover:underline text-accent" onclick="openViewerDossier(_channelModChannel, '${esc(e.username || '')}')" title="Открыть досье зрителя">${esc(e.username || '?')}</strong>
                <span class="badge">${esc(_modDuration(e.duration_sec))}</span>
                ${(e.detail || '').includes('[SHADOW]')
                    ? `<span class="badge badge-warning" title="${esc(e.detail)}">👻 Теневой</span>`
                    : `<span class="badge ${_modStatusBadge(e.status)}">${esc(t('channels.mod_status_' + (e.status || 'applied')))}</span>`}
                <span class="text-muted text-truncate">${esc(e.rule_name || '')}</span>
                ${e.action === 'ban' && e.duration_sec == null && e.status === 'applied'
                    ? `<button class="btn btn-sm btn-secondary ml-auto" onclick="unbanChannelJournalEntry('${esc(e.username || '')}')" data-i18n="channels.mod_unban_btn">Разбанить</button>`
                    : ''}
            </div>`).join('') || `<div class="text-muted text-sm">${esc(t('channels.mod_journal_empty'))}</div>`;
    } catch (e) { el.innerHTML = `<div class="text-error text-sm">${esc(t('channels.load_failed'))}</div>`; }
}

async function loadChannelModProtected(q) {
    const el = $('channelModProtected');
    if (!el) return;
    const accId = $('channelModerationBot')?.value || '';
    if (!accId) { el.innerHTML = `<div class="text-muted text-sm">${esc(t('channels.mod_no_bot'))}</div>`; return; }
    try {
        const data = await api(`/api/moderation/protected?${q}`);
        el.innerHTML = (data.entries || []).map(p => `
            <div class="flex gap-2 items-center text-sm">
                <strong class="cursor-pointer hover:underline text-accent" onclick="openViewerDossier(_channelModChannel, '${esc(p.username)}')" title="Открыть досье зрителя">${esc(p.username)}</strong>
                ${p.note ? `<span class="text-muted text-truncate">${esc(p.note)}</span>` : ''}
                <button class="btn btn-sm btn-danger ml-auto" onclick="removeChannelProtected('${esc(p.username)}')" data-i18n-aria-label="channels.mod_protected_remove" aria-label="${esc(t('channels.mod_protected_remove'))}">✕</button>
            </div>`).join('') || `<div class="text-muted text-sm">${esc(t('channels.mod_protected_empty'))}</div>`;
    } catch (e) { el.innerHTML = `<div class="text-error text-sm">${esc(t('channels.load_failed'))}</div>`; }
}

async function addChannelProtected() {
    const accId = $('channelModerationBot')?.value;
    const username = $('channelModProtectedUser')?.value.trim();
    if (!accId || !username || !_channelModChannel) return;
    try {
        const res = await api('/api/moderation/protected', jopts('POST', {
            account_id: parseInt(accId, 10), channel: _channelModChannel,
            username, note: $('channelModProtectedNote')?.value.trim() || '',
        }));
        if (res.ok === false) { toast(t('toast.error_detail', { detail: res.error }), 'error'); return; }
        $('channelModProtectedUser').value = '';
        $('channelModProtectedNote').value = '';
        loadChannelModProtected(_channelModQuery());
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

async function removeChannelProtected(username) {
    const accId = $('channelModerationBot')?.value;
    if (!accId || !_channelModChannel) return;
    try {
        await api(`/api/moderation/protected/${encodeURIComponent(username)}?account_id=${accId}&channel=${encodeURIComponent(_channelModChannel)}`, jopts('DELETE', {}));
        loadChannelModProtected(_channelModQuery());
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

async function unbanChannelViewer() {
    const accId = $('channelModerationBot')?.value;
    const username = $('channelModUnbanUser')?.value.trim();
    if (!accId || !username || !_channelModChannel) return;
    try {
        const res = await api('/api/moderation/journal/unban', jopts('POST', {
            account_id: parseInt(accId, 10), channel: _channelModChannel, username,
        }));
        if (res.ok === false) { toast(t('toast.error_detail', { detail: res.error }), 'error'); return; }
        toast(t(res.already_unbanned ? 'channels.mod_unban_already' : 'channels.mod_unban_ok'), 'success');
        $('channelModUnbanUser').value = '';
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

// Владелец 27.09: разбан прямо из записи журнала — не нужно вручную перепечатывать ник
async function unbanChannelJournalEntry(username) {
    const accId = $('channelModerationBot')?.value;
    if (!accId || !username || !_channelModChannel) return;
    try {
        const res = await api('/api/moderation/journal/unban', jopts('POST', {
            account_id: parseInt(accId, 10), channel: _channelModChannel, username,
        }));
        if (res.ok === false) { toast(t('toast.error_detail', { detail: res.error }), 'error'); return; }
        toast(t(res.already_unbanned ? 'channels.mod_unban_already' : 'channels.mod_unban_ok'), 'success');
        loadChannelModJournal(_channelModQuery());
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}

function setChannelModReason(reason) {
    const input = $('channelModPunishReason');
    if (input) {
        input.value = reason;
        input.focus();
    }
}

function setChannelProtectedNote(note) {
    const input = $('channelModProtectedNote');
    if (input) {
        input.value = note;
        input.focus();
    }
}

async function applyChannelManualPunishment() {
    const accId = $('channelModerationBot')?.value;
    const username = $('channelModPunishUser')?.value.trim();
    const duration = parseInt($('channelModPunishDuration')?.value || '600', 10);
    const reason = $('channelModPunishReason')?.value.trim() || 'Нарушение правил';
    if (!accId || !username || !_channelModChannel) {
        toast(t('channels.mod_punish_fill_fields') || 'Укажите ник зрителя и выберите бота.', 'error');
        return;
    }
    try {
        const res = await api('/api/moderation/punish', jopts('POST', {
            account_id: parseInt(accId, 10),
            channel: _channelModChannel,
            username,
            duration_sec: duration,
            reason,
        }));
        if (res.ok === false) {
            toast(t('toast.error_detail', { detail: res.error }), 'error');
            return;
        }
        toast(t('channels.mod_punish_ok') || 'Наказание применено.', 'success');
        $('channelModPunishUser').value = '';
        $('channelModPunishReason').value = '';
        loadChannelModJournal(_channelModQuery());
    } catch (e) {
        toast(t('toast.error_detail', { detail: e.message }), 'error');
    }
}

// ── Q08(в) (DEC-OWNER-006): массовая смена канала для выбранных ботов ──
let _bulkChangeJobId = '';
let _bulkChangeTimer = null;

function openBulkChangeChannel() {
    if (!_selectedBots.size) return;
    const previous = document.getElementById('bulkChangeChannelModal');
    if (previous) previous.remove();
    const overlay = document.createElement('div');
    overlay.id = 'bulkChangeChannelModal';
    overlay.className = 'modal-backdrop';
    overlay.style.cssText = 'position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:999;display:flex;align-items:center;justify-content:center';
    const options = typeof botsChannelOptions === 'function' ? botsChannelOptions() : [];
    overlay.innerHTML = `
    <div class="modal" role="dialog" aria-modal="true" aria-labelledby="bulkChangeTitle" style="background:var(--bg-card);border:1px solid var(--border);border-radius:12px;padding:18px;width:min(560px,94vw);max-height:88vh;overflow:auto">
        <div class="flex items-center justify-between mb-3">
            <b id="bulkChangeTitle">${esc(t('bulk.change_channel'))} · ${esc(t('common.selected', {count: _selectedBots.size}))}</b>
            <button class="btn btn-sm btn-secondary" onclick="closeBulkChangeModal()" data-i18n-aria-label="btn.close" aria-label="${esc(t('btn.close'))}">✕</button>
        </div>
        <p class="text-sm text-muted mb-2" data-i18n="bulk.change_hint">${esc(t('bulk.change_hint'))}</p>
        <div class="flex gap-2 mb-2">
            <select id="bulkChangeSelect" class="input" data-i18n-aria-label="panel.bots.channel_filter" aria-label="${esc(t('panel.bots.channel_filter'))}">
                ${options.map(channel => `<option value="${esc(channel)}">#${esc(channel)}</option>`).join('')}
            </select>
            <input id="bulkChangeNew" class="input" placeholder="channel_name" data-i18n-aria-label="bulk.change_new" aria-label="${esc(t('bulk.change_new'))}">
        </div>
        <label class="flex items-center gap-2 text-sm mb-3">
            <input type="checkbox" id="bulkChangeReplace" checked>
            <span data-i18n="bulk.change_replace">${esc(t('bulk.change_replace'))}</span>
        </label>
        <button class="btn btn-primary btn-sm" id="bulkChangeStart" onclick="startBulkChangeChannel()">${esc(t('bulk.change_apply'))}</button>
        <div id="bulkChangeError" class="text-error text-sm mt-2" aria-live="polite"></div>
        <div id="bulkChangeResults" class="mt-3"></div>
    </div>`;
    overlay.addEventListener('click', e => { if (e.target === overlay) closeBulkChangeModal(); });
    document.body.appendChild(overlay);
    openPanelDialog(overlay, {removeOnClose: true});
}

function closeBulkChangeModal() {
    clearInterval(_bulkChangeTimer);
    _bulkChangeTimer = null;
    _bulkChangeJobId = '';
    closePanelDialog('bulkChangeChannelModal');
}

async function startBulkChangeChannel() {
    const typed = ($('bulkChangeNew')?.value || '').trim().replace(/^#/, '').toLowerCase();
    const channel = typed || ($('bulkChangeSelect')?.value || '');
    const errorBox = $('bulkChangeError');
    if (!channel) { if (errorBox) errorBox.textContent = t('bulk.change_need_channel'); return; }
    if (errorBox) errorBox.textContent = '';
    try {
        const job = await api('/api/bulk/change-channel', jopts('POST', {
            account_ids: [..._selectedBots], channel, replace: !!$('bulkChangeReplace')?.checked,
        }));
        if (!job.ok) { if (errorBox) errorBox.textContent = t(`bulk.error.${job.code || 'bulk_failed'}`); return; }
        _bulkChangeJobId = job.job_id;
        $('bulkChangeStart').disabled = true;
        $('bulkChangeResults').innerHTML = `<div class="text-muted text-sm">${esc(t('bulk.running'))}</div>`;
        clearInterval(_bulkChangeTimer);
        _bulkChangeTimer = setInterval(pollBulkChangeChannel, 1000);
        await pollBulkChangeChannel();
    } catch (e) { if (errorBox) errorBox.textContent = e.message; }
}

async function pollBulkChangeChannel() {
    if (!_bulkChangeJobId) return;
    try {
        const job = await api(`/api/bulk/channels/${_bulkChangeJobId}`);
        if (job.status === 'running') return;
        clearInterval(_bulkChangeTimer);
        _bulkChangeTimer = null;
        _bulkChangeJobId = '';
        const start = $('bulkChangeStart');
        if (start) start.disabled = false;
        const box = $('bulkChangeResults');
        const counts = job.counts || {};
        if (box) {
            const rows = (job.results || []).map(item => `<tr>
                <td>${esc(item.nickname || `#${item.account_id}`)}</td><td>#${esc(item.channel)}</td>
                <td>${esc(t(`bulk.value.${item.result}`))}: ${esc(t(`bulk.reason.${item.reason}`))}</td>
                <td>${item.detached ? `−${item.detached}` : ''}</td>
            </tr>`).join('');
            box.innerHTML = `<div class="text-sm mb-1">${esc(t('bulk.change_done', {
                changed: counts.changed || 0, added: counts.added || 0,
                skipped: counts.skipped || 0, errors: counts.errors || 0,
            }))}</div>` + (rows ? `<div class="table-wrap"><table><thead><tr>
                <th>${esc(t('check.col.bot'))}</th><th>${esc(t('bulk.col.channel'))}</th>
                <th>${esc(t('bulk.col.add'))}</th><th>−</th></tr></thead><tbody>${rows}</tbody></table></div>` : '');
        }
        if (job.status === 'completed') {
            await loadBotsList();
            if (typeof loadChannelsSection === 'function') await loadChannelsSection();
        } else if (job.status === 'failed') {
            toast(t('toast.error_detail', {detail: job.error || 'bulk_failed'}), 'error');
        }
    } catch (e) {
        clearInterval(_bulkChangeTimer);
        _bulkChangeTimer = null;
        toast(t('toast.error_detail', {detail: e.message}), 'error');
    }
}

// ── Клонирование / перенос настроек между каналами ──
function openChannelCloneModal() {
    if (!_channelSettingsChannel) return;
    const select = $('channelCloneFromSelect');
    if (!select) return;
    const otherChannels = (_channelOverview || [])
        .map(i => (i.channel || '').replace(/^#/, '').toLowerCase())
        .filter(ch => ch && ch !== _channelSettingsChannel);
    if (!otherChannels.length) {
        toast(t('channels.clone_no_source'), 'warning');
        return;
    }
    select.innerHTML = otherChannels.map(ch => `<option value="${esc(ch)}">#${esc(ch)}</option>`).join('');
    showModal('channelCloneModal');
}

async function submitChannelClone() {
    const fromChan = $('channelCloneFromSelect')?.value;
    const toChan = _channelSettingsChannel;
    if (!fromChan || !toChan) return;
    const copyRules = !!$('channelCloneRules')?.checked;
    const copyBans = !!$('channelCloneBans')?.checked;
    const copyAllowed = !!$('channelCloneAllowed')?.checked;
    if (!copyRules && !copyBans && !copyAllowed) {
        toast(t('channels.clone_pick_at_least_one'), 'warning');
        return;
    }
    const btn = $('channelCloneSubmitBtn');
    if (btn) btn.disabled = true;
    try {
        const res = await api('/api/channels/clone-settings', jopts('POST', {
            from_channel: fromChan,
            to_channel: toChan,
            copy_rules: copyRules,
            copy_bans: copyBans,
            copy_allowed: copyAllowed,
        }));
        if (!res.ok) throw new Error(res.error || 'error');
        hideModal('channelCloneModal');
        toast(t('channels.clone_ok', { from: fromChan, to: toChan }), 'success');
        _channelSettingsLoaded = { bots: false, rules: false, moderation: false, profile: false };
        const activeTab = document.querySelector('.channel-settings-tab-btn.btn-primary')?.dataset.channelTab || 'rules';
        showChannelSettingsTab(activeTab);
    } catch (e) {
        toast(t('toast.error_detail', { detail: e.message }), 'error');
    } finally {
        if (btn) btn.disabled = false;
    }
}

// ── Fleet Automation Settings (#1-#8) ──
let _currentFleetChannel = null;

async function openChannelFleetModal(channel) {
    const ch = (channel || '').replace(/^#/, '').toLowerCase();
    if (!ch) return;
    _currentFleetChannel = ch;
    const nameEl = $('fleetModalChannelName');
    if (nameEl) nameEl.textContent = '#' + ch;
    showModal('channelFleetModal');
    try {
        const res = await api(`/api/channels/${encodeURIComponent(ch)}/fleet-settings`);
        if (res && res.settings) {
            const s = res.settings;
            if ($('fleetAutoStartLive')) $('fleetAutoStartLive').checked = !!s.auto_start_on_live;
            if ($('fleetAutoStopOffline')) $('fleetAutoStopOffline').checked = !!s.auto_stop_on_offline;
            if ($('fleetBotLimit')) $('fleetBotLimit').value = s.bot_limit ?? 0;
            if ($('fleetSelectionMode')) $('fleetSelectionMode').value = s.selection_mode || 'active_first';
            if ($('fleetScaleWithViewers')) $('fleetScaleWithViewers').checked = !!s.scale_with_viewers;
            if ($('fleetViewerRatioPercent')) $('fleetViewerRatioPercent').value = s.viewer_ratio_percent ?? 10.0;
            if ($('fleetStaggerMin')) $('fleetStaggerMin').value = s.stagger_sec_min ?? 1.5;
            if ($('fleetStaggerMax')) $('fleetStaggerMax').value = s.stagger_sec_max ?? 4.0;
            if ($('fleetJitterMin')) $('fleetJitterMin').value = s.message_jitter_min_sec ?? 1.0;
            if ($('fleetJitterMax')) $('fleetJitterMax').value = s.message_jitter_max_sec ?? 5.0;
        }
    } catch (e) {
        toast(`Не удалось загрузить настройки флота: ${e.message}`, 'error');
    }
}

async function saveChannelFleetModal() {
    if (!_currentFleetChannel) return;
    const btn = $('fleetModalSaveBtn');
    if (btn) btn.disabled = true;
    try {
        const payload = {
            auto_start_on_live: !!$('fleetAutoStartLive')?.checked,
            auto_stop_on_offline: !!$('fleetAutoStopOffline')?.checked,
            bot_limit: parseInt($('fleetBotLimit')?.value, 10) || 0,
            selection_mode: $('fleetSelectionMode')?.value || 'active_first',
            scale_with_viewers: !!$('fleetScaleWithViewers')?.checked,
            viewer_ratio_percent: parseFloat($('fleetViewerRatioPercent')?.value) || 10.0,
            stagger_sec_min: parseFloat($('fleetStaggerMin')?.value) || 1.5,
            stagger_sec_max: parseFloat($('fleetStaggerMax')?.value) || 4.0,
            message_jitter_min_sec: parseFloat($('fleetJitterMin')?.value) || 1.0,
            message_jitter_max_sec: parseFloat($('fleetJitterMax')?.value) || 5.0,
        };
        const res = await api(`/api/channels/${encodeURIComponent(_currentFleetChannel)}/fleet-settings`, jopts('POST', payload));
        if (res && res.ok) {
            toast(`Настройки флота для #${_currentFleetChannel} сохранены`, 'success');
            hideModal('channelFleetModal');
        } else {
            toast('Ошибка сохранения настроек флота', 'error');
        }
    } catch (e) {
        toast(`Ошибка: ${e.message}`, 'error');
    } finally {
        if (btn) btn.disabled = false;
    }
}

// ── Синхронизация смайлов канала (7TV / BTTV / FFZ) ──

async function _loadChannelEmotes(ch) {
    const badge = $('channelEmotesBadge');
    const list = $('channelEmotesList');
    if (!badge || !list) return;
    badge.textContent = 'Загрузка...';
    list.innerHTML = '';
    try {
        const res = await api(`/api/channels/${encodeURIComponent(ch)}/emotes`);
        if (res && res.ok) {
            _renderChannelEmotes(res);
        } else {
            badge.textContent = 'Ошибка';
        }
    } catch (e) {
        badge.textContent = 'Ошибка';
    }
}

function _renderChannelEmotes(data) {
    const badge = $('channelEmotesBadge');
    const list = $('channelEmotesList');
    if (!badge || !list) return;
    const total = data.total_count || 0;
    const s = data.sources || {};
    badge.textContent = `${total} смайлов (7TV: ${s['7tv'] || 0}, BTTV: ${s.bttv || 0}, FFZ: ${s.ffz || 0})`;
    const sample = data.sample || [];
    if (sample.length === 0) {
        list.innerHTML = '<span class="text-xs text-muted">Смайлы не загружены. Нажмите «Синхронизировать».</span>';
        return;
    }
    list.innerHTML = sample.map(em => `<span class="badge badge-sm badge-outline text-xs">${esc(em)}</span>`).join(' ');
}

async function syncCurrentChannelEmotes() {
    if (!_channelSettingsChannel) return;
    const btn = $('channelEmotesSyncBtn');
    const badge = $('channelEmotesBadge');
    if (btn) btn.disabled = true;
    if (badge) badge.textContent = 'Синхронизация...';
    try {
        const res = await api(`/api/channels/${encodeURIComponent(_channelSettingsChannel)}/emotes/sync`, jopts('POST', {}));
        if (res && res.ok) {
            _renderChannelEmotes(res);
            toast(`Смайлы для #${_channelSettingsChannel} синхронизированы: ${res.total_count}`, 'success');
        } else {
            toast('Ошибка синхронизации смайлов', 'error');
            if (badge) badge.textContent = 'Ошибка';
        }
    } catch (e) {
        toast(`Ошибка: ${e.message}`, 'error');
        if (badge) badge.textContent = 'Ошибка';
    } finally {
        if (btn) btn.disabled = false;
    }
}

// ── Мини-досье зрителя в 1 клик (Viewer Dossier) ──

let _dossierChannel = '';
let _dossierUsername = '';
let _dossierData = null;

async function openViewerDossier(channel, username) {
    const ch = (channel || _channelSettingsChannel || _channelModChannel || '').replace(/^#/, '').toLowerCase();
    const user = (username || '').trim().replace(/^@/, '');
    if (!user) return;
    _dossierChannel = ch;
    _dossierUsername = user;
    _dossierData = null;

    const modal = $('viewerDossierModal');
    if (!modal) return;
    showModal('viewerDossierModal');

    const uEl = $('dossierUsername');
    if (uEl) uEl.textContent = user;
    const cEl = $('dossierChannelBadge');
    if (cEl) cEl.textContent = ch ? '#' + ch : 'Все каналы';
    const sEl = $('dossierStatusBadge');
    if (sEl) {
        sEl.className = 'badge badge-sm badge-ghost';
        sEl.textContent = 'Загрузка...';
    }

    const msgBox = $('dossierRecentMessages');
    if (msgBox) msgBox.innerHTML = '<span class="text-xs text-muted">Загрузка сообщений...</span>';
    const factBox = $('dossierFactsList');
    if (factBox) factBox.innerHTML = '<span class="text-xs text-muted">Загрузка памяти...</span>';
    const modBox = $('dossierModList');
    if (modBox) modBox.innerHTML = '<span class="text-xs text-muted">Загрузка модерации...</span>';

    try {
        const res = await api(`/api/viewers/${encodeURIComponent(ch || '_')}/${encodeURIComponent(user)}/dossier`);
        if (res && res.ok) {
            _dossierData = res;
            _renderViewerDossier(res);
        } else {
            toast(res?.error || 'Не удалось загрузить досье', 'error');
            if (sEl) sEl.textContent = 'Ошибка загрузки';
        }
    } catch (e) {
        toast(`Ошибка: ${e.message}`, 'error');
        if (sEl) sEl.textContent = 'Ошибка';
    }
}

function _renderViewerDossier(data) {
    const sEl = $('dossierStatusBadge');
    const protBtn = $('dossierProtectBtn');
    const unbanBtn = $('dossierUnbanBtn');

    const isProtected = data.status?.is_protected;
    const lastPunish = data.status?.last_punish;

    if (sEl) {
        if (isProtected) {
            sEl.className = 'badge badge-sm badge-success';
            sEl.textContent = '🛡 Защищён (Whitelist)';
        } else if (lastPunish && lastPunish.status === 'applied') {
            sEl.className = 'badge badge-sm badge-error';
            sEl.textContent = lastPunish.action === 'ban' ? '🚫 Забанен' : '⏱ Таймаут';
        } else {
            sEl.className = 'badge badge-sm badge-info';
            sEl.textContent = '🟢 Обычный зритель';
        }
    }

    if (protBtn) {
        protBtn.textContent = isProtected ? '❌ Убрать из белого списка' : '🛡 Защитить зрителя (Whitelist)';
        protBtn.className = isProtected ? 'btn btn-sm btn-outline btn-error' : 'btn btn-sm btn-secondary';
    }

    if (unbanBtn) {
        unbanBtn.style.display = (lastPunish && lastPunish.status === 'applied') ? 'inline-flex' : 'none';
    }

    // Статистика сообщений
    if ($('dossierMsgCount')) $('dossierMsgCount').textContent = `${data.stats?.total_messages || 0} сообщ.`;
    if ($('dossierFirstSeen')) $('dossierFirstSeen').textContent = (data.stats?.first_seen || '-').slice(0, 16);
    if ($('dossierLastSeen')) $('dossierLastSeen').textContent = (data.stats?.last_seen || '-').slice(0, 16);

    const msgBox = $('dossierRecentMessages');
    if (msgBox) {
        const msgs = data.stats?.recent_messages || [];
        if (!msgs.length) {
            msgBox.innerHTML = '<span class="text-xs text-muted">Сообщений в базе нет</span>';
        } else {
            msgBox.innerHTML = msgs.map(m => `
                <div class="flex items-center gap-2 p-1 bg-base-100 rounded">
                    <span class="text-muted text-[10px]">${esc((m.timestamp || '').slice(11, 19))}</span>
                    <span class="flex-1">${esc(m.text || '')}</span>
                </div>
            `).join('');
        }
    }

    // Память ботов
    const factBox = $('dossierFactsList');
    if (factBox) {
        const mems = data.bot_memories || [];
        const allFacts = [];
        mems.forEach(m => {
            (m.facts || []).forEach(f => {
                allFacts.push({ bot: m.bot_nickname, fact: f });
            });
        });
        if ($('dossierFactsCount')) $('dossierFactsCount').textContent = `${allFacts.length} фактов`;
        if (!allFacts.length) {
            factBox.innerHTML = '<span class="text-xs text-muted">Боты пока не сохранили фактов о зрителе</span>';
        } else {
            factBox.innerHTML = allFacts.map(item => `
                <div class="flex items-center gap-2 p-1 bg-base-100 rounded">
                    <span class="badge badge-xs badge-outline">${esc(item.bot)}</span>
                    <span class="flex-1">${esc(item.fact)}</span>
                </div>
            `).join('');
        }
    }

    // Модерация
    const modBox = $('dossierModList');
    if (modBox) {
        const mods = data.moderation_history || [];
        if ($('dossierModCount')) $('dossierModCount').textContent = `${mods.length} записей`;
        if (!mods.length) {
            modBox.innerHTML = '<span class="text-xs text-muted">Нарушений и наказаний не зафиксировано</span>';
        } else {
            modBox.innerHTML = mods.map(e => `
                <div class="flex items-center gap-2 p-1 bg-base-100 rounded">
                    <span class="text-muted text-[10px]">${esc((e.created_at || '').slice(5, 16))}</span>
                    <span class="badge badge-xs ${e.action === 'ban' ? 'badge-error' : 'badge-warning'}">${esc(e.action || 'action')}</span>
                    <span class="text-muted">${esc(e.duration_sec ? _modDuration(e.duration_sec) : 'навсегда')}</span>
                    <span class="flex-1 text-truncate">${esc(e.detail || e.rule_name || '')}</span>
                </div>
            `).join('');
        }
    }
}

async function dossierToggleProtect() {
    if (!_dossierData || !_dossierUsername) return;
    const isProtected = _dossierData.status?.is_protected;
    const ch = _dossierChannel || _channelModChannel || '';
    const accId = $('channelModerationBot')?.value || 1;

    try {
        if (isProtected) {
            await api(`/api/moderation/protected/${encodeURIComponent(_dossierUsername)}?account_id=${accId}&channel=${encodeURIComponent(ch)}`, jopts('DELETE', {}));
            toast(`Зритель ${_dossierUsername} удалён из белого списка`, 'info');
        } else {
            await api('/api/moderation/protected', jopts('POST', {
                account_id: parseInt(accId, 10),
                channel: ch,
                username: _dossierUsername,
                note: 'Добавлен через досье',
            }));
            toast(`Зритель ${_dossierUsername} добавлен в белый список`, 'success');
        }
        await openViewerDossier(_dossierChannel, _dossierUsername);
    } catch (e) {
        toast(`Ошибка: ${e.message}`, 'error');
    }
}

async function dossierUnban() {
    if (!_dossierUsername) return;
    const ch = _dossierChannel || _channelModChannel || '';
    try {
        await api('/api/moderation/journal/unban', jopts('POST', {
            channel: ch,
            username: _dossierUsername,
        }));
        toast(`Зритель ${_dossierUsername} разбанен`, 'success');
        await openViewerDossier(_dossierChannel, _dossierUsername);
    } catch (e) {
        toast(`Ошибка: ${e.message}`, 'error');
    }
}

async function dossierApplyPunish() {
    if (!_dossierUsername) return;
    const ch = _dossierChannel || _channelModChannel || '';
    const accId = $('channelModerationBot')?.value || 1;
    const duration = parseInt($('dossierTimeoutDuration')?.value || '600', 10);
    const reason = $('dossierTimeoutReason')?.value.trim() || 'Нарушение правил';

    try {
        const res = await api('/api/moderation/punish', jopts('POST', {
            account_id: parseInt(accId, 10),
            channel: ch,
            username: _dossierUsername,
            duration_sec: duration,
            reason,
        }));
        if (res && res.ok === false) {
            toast(res.error || 'Ошибка применения наказания', 'error');
            return;
        }
        toast(`Наказание применено к ${_dossierUsername}`, 'success');
        await openViewerDossier(_dossierChannel, _dossierUsername);
        if (typeof loadChannelModJournal === 'function' && typeof _channelModQuery === 'function') {
            loadChannelModJournal(_channelModQuery());
        }
    } catch (e) {
        toast(`Ошибка: ${e.message}`, 'error');
    }
}

window.openViewerDossier = openViewerDossier;
