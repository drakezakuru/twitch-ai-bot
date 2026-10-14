// W2: public panel conversation through the connected Twitch channel.
function _dmLog() { return $('dmLog'); }
function _dmAppend(role, text) {
    const box = _dmLog();
    if (!box) return;
    const row = document.createElement('div');
    row.className = 'py-1';
    row.style.borderTop = '1px solid var(--border-light)';
    row.style.whiteSpace = 'pre-wrap';
    row.innerHTML = `<b class="${role === 'bot' ? 'text-accent' : ''}">${esc(role === 'bot' ? t('dm.you_bot') : t('dm.you'))}:</b> ${esc(text)}`;
    box.appendChild(row);
    box.scrollTop = box.scrollHeight;
}
async function openDmChat() {
    if (!_currentBotId) return;
    showModal('dmChatModal');
    const box = _dmLog();
    if (box) box.innerHTML = '';
    const channelSelect = $('dmChannel');
    if (channelSelect) {
        channelSelect.innerHTML = '';
        const account = (_bots || []).find(b => Number(b.id) === Number(_currentBotId));
        (account?.channels || []).filter(ch => ch.enabled !== false && ch.enabled !== 0).forEach(ch => {
            const name = String(ch.channel_name || ch.name || ch).replace(/^#/, '');
            if (!name) return;
            channelSelect.insertAdjacentHTML('beforeend', `<option value="${esc(name)}">#${esc(name)}</option>`);
        });
    }
    try {
        const res = await api(`/api/accounts/${_currentBotId}/dm/history`);
        const channel = channelSelect?.value || '';
        (res.messages || []).filter(m => !channel || m.channel === channel).forEach(m => _dmAppend(m.role, m.text));
    } catch (e) { console.warn('panel chat history', e); }
}
async function dmSendText() {
    const input = $('dmInput');
    const text = (input?.value || '').trim();
    const channel = $('dmChannel')?.value || '';
    if (!text) { toast(t('dm.empty'), 'error'); return; }
    if (!channel) { toast(t('dm.channel_required'), 'error'); return; }
    if (input) input.value = '';
    try {
        const res = await api(`/api/accounts/${_currentBotId}/dm`, jopts('POST', {
            text, channel, speak_reply: $('dmSpeakReply')?.classList.contains('active') || false,
        }));
        if (res.ok === false) {
            toast(t('dm.twitch_error', { detail: res.detail || res.error || 'error' }), 'error');
            return;
        }
        _dmAppend('user', text);
        if (res.reply) _dmAppend('bot', res.reply);
    } catch (e) { toast(t('dm.twitch_error', { detail: e.message }), 'error'); }
}
async function dmReset() {
    if (!_currentBotId) return;
    await api(`/api/accounts/${_currentBotId}/dm/reset`, jopts('POST', {}));
    if (_dmLog()) _dmLog().innerHTML = '';
    toast(t('msg.saved'), 'success');
}
