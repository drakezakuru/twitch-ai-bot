// ── MOD-18 ModSite admin (owner) ─────────────────────────────
// Kill switch + grant revoke. RU/EN/UA labels via data-i18n on markup.
const _modsiteAdmin = { loading: false };

function _modsiteT(key, fallback) { const el = document.querySelector(`[data-i18n="${key}"]`); return el ? el.textContent : fallback; }

async function modsiteAdminRefresh() {
    if (_modsiteAdmin.loading) return;
    _modsiteAdmin.loading = true;
    try {
        const kill = await api('/api/moderator-site/admin/kill');
        const badge = document.getElementById('modsiteKillStatus');
        if (badge) { badge.textContent = kill.active ? 'ON' : 'OFF'; badge.dataset.active = kill.active ? '1' : '0'; }
        const account = document.getElementById('modsiteAccountId');
        const channel = document.getElementById('modsiteChannel');
        if (account?.value && channel?.value) {
            const grants = await api(`/api/moderator-site/admin/grants?account_id=${encodeURIComponent(account.value)}&channel=${encodeURIComponent(channel.value)}`);
            const list = document.getElementById('modsiteGrants');
            if (list) list.innerHTML = (grants.items || []).map((g) =>
                `<li><code>${esc(g.twitch_login || g.twitch_user_id)}</code> · ${g.permissions.join(', ')} · v${g.grant_version} · ${g.enabled ? 'on' : 'revoked'}
                 <button type="button" class="btn btn-danger btn-sm" onclick="modsiteRevoke('${esc(g.id)}')" ${g.enabled ? '' : 'disabled'} data-i18n="modsite.revoke">${_modsiteT('modsite.revoke', 'Отозвать')}</button></li>`).join('');
        }
    } catch (error) { toast(apiErrorInfo(error?.payload || error?.body || {}, error?.message || '').message, 'error'); }
    finally { _modsiteAdmin.loading = false; }
}

async function modsiteKillSet(active) {
    const reasonInput = document.getElementById('modsiteKillReason');
    try {
        await api('/api/moderator-site/admin/kill', jopts('POST', { active, reason: reasonInput?.value || '' }));
        toast(active ? 'Kill switch ON' : 'Kill switch OFF', active ? 'error' : 'success');
        await modsiteAdminRefresh();
    } catch (error) { toast(apiErrorInfo(error?.payload || error?.body || {}, error?.message || '').message, 'error'); }
}

async function modsiteRevoke(grantId) {
    try {
        await api(`/api/moderator-site/admin/grants/${encodeURIComponent(grantId)}/revoke`, jopts('POST', {}));
        toast('Access revoked', 'success');
        await modsiteAdminRefresh();
    } catch (error) { toast(apiErrorInfo(error?.payload || error?.body || {}, error?.message || '').message, 'error'); }
}

window.modsiteAdminRefresh = modsiteAdminRefresh;
window.modsiteKillSet = modsiteKillSet;
window.modsiteRevoke = modsiteRevoke;
document.addEventListener('DOMContentLoaded', () => { modsiteAdminRefresh(); });

// MOD-18: moderator-site admin (owner) — RU/EN/UA
Object.assign(LANGS.ru, {
    'modsite.title': 'Moderator-site: kill switch и доступы', 'modsite.kill': 'Аварийное отключение',
    'modsite.kill_on': 'Включить', 'modsite.kill_off': 'Выключить',
    'modsite.hint': 'Отзыв доступа действует сразу и переживает перезагрузку страницы; kill switch блокирует новые команды moderator-site.',
    'modsite.revoke': 'Отозвать'
});
Object.assign(LANGS.en, {
    'modsite.title': 'Moderator-site: kill switch and access', 'modsite.kill': 'Kill switch',
    'modsite.kill_on': 'Enable', 'modsite.kill_off': 'Disable',
    'modsite.hint': 'Revoking access applies immediately and survives page reloads; the kill switch blocks new moderator-site commands.',
    'modsite.revoke': 'Revoke'
});
Object.assign(LANGS.ua, {
    'modsite.title': 'Moderator-site: kill switch і доступи', 'modsite.kill': 'Kill switch',
    'modsite.kill_on': 'Увімкнути', 'modsite.kill_off': 'Вимкнути',
    'modsite.hint': 'Відкликання доступу діє одразу й переживає перезавантаження сторінки; kill switch блокує нові команди moderator-site.',
    'modsite.revoke': 'Відкликати'
});
