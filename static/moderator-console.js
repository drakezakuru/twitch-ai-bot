'use strict';

const MC_TEXT = {
    ru: {title:'Moderator Console',login_title:'Вход через Twitch',login_hint:'Одноразовая ссылка привязывает вход к выданному владельцем доступу.',login_button:'Войти через Twitch',device_hint:'Откройте Twitch и введите код:',device_open:'Открыть Twitch',channel:'Канал',session:'Сессия',message:'Сообщение',message_ph:'Текст для озвучки',voice:'Голос',send:'Отправить в очередь',queue:'Моя очередь',refresh:'Обновить',queue_hint:'Accepted означает приём в audio queue, а не подтверждённое воспроизведение в OBS.',missing_invite:'Ссылка входа отсутствует или уже использована.',starting:'Запрашиваю вход Twitch…',waiting:'Жду подтверждения в Twitch…',login_failed:'Не удалось войти',policy_off:'Владелец ещё не включил TTS policy для этого канала.',no_permission:'Право send_tts не выдано.',no_voices:'Нет разрешённых голосов.',default_voice:'по умолчанию',favorite:'Избранное',sent:'Принято в audio queue.',empty:'Введите текст.',no_commands:'Команд пока нет.',expires:'до',save_failed:'Не удалось сохранить предпочтения',tab_tts:'TTS',tab_media:'GIF / медиа',tab_sounds:'Звуки',media_title:'GIF и медиа',media_hint:'Только одобренная владельцем библиотека этого канала.',sounds_title:'Звуки',sounds_hint:'Звук запускается в exact-scoped OBS Soundboard, а не в этой консоли.',stop_sound:'Остановить звук',sound_stopped:'Команда Stop принята.',search:'Поиск',upload_media:'Загрузить на проверку',preview:'Превью',play:'Запустить',close:'Закрыть',no_items:'Нет одобренных элементов.',queued:'Принято в очередь.',uploaded_pending:'Загружено и ожидает одобрения владельца.'},
    en: {title:'Moderator Console',login_title:'Sign in with Twitch',login_hint:'The one-time link binds this login to access granted by the owner.',login_button:'Sign in with Twitch',device_hint:'Open Twitch and enter this code:',device_open:'Open Twitch',channel:'Channel',session:'Session',message:'Message',message_ph:'Text to speak',voice:'Voice',send:'Send to queue',queue:'My queue',refresh:'Refresh',queue_hint:'Accepted means admitted to the audio queue, not confirmed OBS playback.',missing_invite:'The login link is missing or has already been used.',starting:'Starting Twitch sign-in…',waiting:'Waiting for Twitch confirmation…',login_failed:'Could not sign in',policy_off:'The owner has not enabled TTS policy for this channel.',no_permission:'The send_tts permission was not granted.',no_voices:'No approved voices.',default_voice:'default',favorite:'Favorite',sent:'Accepted into the audio queue.',empty:'Enter text.',no_commands:'No commands yet.',expires:'until',save_failed:'Could not save preferences',tab_tts:'TTS',tab_media:'GIF / media',tab_sounds:'Sounds',media_title:'GIF and media',media_hint:'Only the owner-approved library for this channel.',sounds_title:'Sounds',sounds_hint:'Sound plays in the exact-scoped OBS Soundboard, not in this console.',stop_sound:'Stop sound',sound_stopped:'Stop command accepted.',search:'Search',upload_media:'Upload for review',preview:'Preview',play:'Play',close:'Close',no_items:'No approved items.',queued:'Accepted into the queue.',uploaded_pending:'Uploaded and awaiting owner approval.'},
    ua: {title:'Moderator Console',login_title:'Вхід через Twitch',login_hint:'Одноразове посилання прив’язує вхід до доступу, виданого власником.',login_button:'Увійти через Twitch',device_hint:'Відкрийте Twitch і введіть код:',device_open:'Відкрити Twitch',channel:'Канал',session:'Сесія',message:'Повідомлення',message_ph:'Текст для озвучення',voice:'Голос',send:'Надіслати в чергу',queue:'Моя черга',refresh:'Оновити',queue_hint:'Accepted означає прийняття в audio queue, а не підтверджене відтворення в OBS.',missing_invite:'Посилання для входу відсутнє або вже використане.',starting:'Запитую вхід Twitch…',waiting:'Чекаю підтвердження в Twitch…',login_failed:'Не вдалося увійти',policy_off:'Власник ще не ввімкнув TTS policy для цього каналу.',no_permission:'Право send_tts не видано.',no_voices:'Немає дозволених голосів.',default_voice:'типовий',favorite:'Обране',sent:'Прийнято до audio queue.',empty:'Введіть текст.',no_commands:'Команд поки немає.',expires:'до',save_failed:'Не вдалося зберегти налаштування',tab_tts:'TTS',tab_media:'GIF / медіа',tab_sounds:'Звуки',media_title:'GIF і медіа',media_hint:'Лише схвалена власником бібліотека цього каналу.',sounds_title:'Звуки',sounds_hint:'Звук запускається в exact-scoped OBS Soundboard, а не в цій консолі.',stop_sound:'Зупинити звук',sound_stopped:'Команду Stop прийнято.',search:'Пошук',upload_media:'Завантажити на перевірку',preview:'Прев’ю',play:'Запустити',close:'Закрити',no_items:'Немає схвалених елементів.',queued:'Прийнято до черги.',uploaded_pending:'Завантажено й очікує схвалення власника.'},
};
let mcLang = localStorage.getItem('moderator-console-lang') || 'ru';
let mcInvite = new URLSearchParams(location.hash.slice(1)).get('invite') || '';
let mcSession = sessionStorage.getItem('moderator-console-session') || '';
let mcContext = null;
let mcTimer = null;
let mcMediaItems = [];
let mcSoundItems = [];
let mcPreviewUrl = '';

const mc = id => document.getElementById(id);
const mt = key => MC_TEXT[mcLang]?.[key] || MC_TEXT.en[key] || key;
const mh = value => { const node = document.createElement('span'); node.textContent = String(value ?? ''); return node.innerHTML; };

function mcSetLang(lang) {
    mcLang = MC_TEXT[lang] ? lang : 'en';
    localStorage.setItem('moderator-console-lang', mcLang);
    document.documentElement.lang = mcLang;
    document.querySelectorAll('[data-mc-i18n]').forEach(node => node.textContent = mt(node.dataset.mcI18n));
    document.querySelectorAll('[data-mc-i18n-placeholder]').forEach(node => node.placeholder = mt(node.dataset.mcI18nPlaceholder));
    if (mcContext) mcRenderContext();
}

async function mcApi(path, options = {}) {
    const headers = {...(options.headers || {})};
    if (options.body) headers['Content-Type'] = 'application/json';
    if (mcSession) headers.Authorization = `Bearer ${mcSession}`;
    const response = await fetch(path, {...options, headers});
    let body = {};
    try { body = await response.json(); } catch (_) {}
    if (!response.ok) throw new Error(body.detail || body.error || response.statusText);
    return body;
}

async function mcStartLogin() {
    if (!mcInvite) return mcLoginError(mt('missing_invite'));
    mc('mcLoginButton').disabled = true;
    mc('mcLoginStatus').textContent = mt('starting');
    try {
        const login = await mcApi('/api/moderator-console/twitch-device', {method:'POST', body:JSON.stringify({invite_token:mcInvite})});
        mc('mcDevice').classList.remove('hidden');
        mc('mcUserCode').textContent = login.user_code;
        mc('mcActivate').href = login.verification_uri;
        mc('mcLoginStatus').textContent = mt('waiting');
        await mcPollLogin(login.device_code, Math.max(2, Number(login.interval || 5)));
    } catch (error) { mcLoginError(`${mt('login_failed')}: ${error.message}`); }
}

async function mcPollLogin(deviceCode, interval) {
    await new Promise(resolve => setTimeout(resolve, interval * 1000));
    try {
        const result = await mcApi('/api/moderator-console/twitch-device/poll', {method:'POST', body:JSON.stringify({invite_token:mcInvite, device_code:deviceCode})});
        if (result.pending) return mcPollLogin(deviceCode, interval);
        if (result.slow_down) return mcPollLogin(deviceCode, interval + 2);
        if (!result.ok) throw new Error(result.expired ? 'expired' : result.denied ? 'denied' : result.error || 'login_failed');
        mcSession = result.session_token;
        sessionStorage.setItem('moderator-console-session', mcSession);
        mcInvite = '';
        history.replaceState(null, '', location.pathname);
        await mcLoadConsole();
    } catch (error) { mcLoginError(`${mt('login_failed')}: ${error.message}`); }
}

function mcLoginError(message) {
    mc('mcLoginStatus').textContent = message;
    mc('mcLoginStatus').style.color = 'var(--danger)';
    mc('mcLoginButton').disabled = false;
}

async function mcLoadConsole() {
    try {
        mcContext = await mcApi('/api/moderator-console/context');
        mc('mcLogin').classList.add('hidden');
        mc('mcConsole').classList.remove('hidden');
        mcRenderContext();
        await mcLoadCommands();
        clearInterval(mcTimer);
        mcTimer = setInterval(mcLoadCommands, 5000);
    } catch (error) {
        sessionStorage.removeItem('moderator-console-session');
        mcSession = '';
        mcLoginError(`${mt('login_failed')}: ${error.message}`);
    }
}

function mcRenderContext() {
    const policy = mcContext.policy;
    const preferences = mcContext.preferences || {default_alias:'', favorites:[]};
    mc('mcChannel').textContent = `#${mcContext.channel}`;
    mc('mcSession').textContent = `${mt('expires')} ${new Date(mcContext.expires_at || Date.now()).toLocaleTimeString()}`;
    const warning = mc('mcPolicyWarning');
    const blocked = !mcContext.permissions.includes('send_tts') || !policy || !policy.enabled;
    warning.textContent = !mcContext.permissions.includes('send_tts') ? mt('no_permission') : mt('policy_off');
    warning.classList.toggle('hidden', !blocked);
    mc('mcSend').disabled = blocked;
    mc('mcText').maxLength = policy?.max_length || 300;
    mc('mcLimit').textContent = `≤ ${mc('mcText').maxLength}`;
    document.querySelector('[data-mc-tab="tts"]').disabled = !mcContext.permissions.includes('send_tts');
    document.querySelector('[data-mc-tab="media"]').disabled = !mcContext.permissions.includes('play_media');
    document.querySelector('[data-mc-tab="sounds"]').disabled = !mcContext.permissions.includes('play_sound');
    mc('mcMediaUploadLabel').classList.toggle('hidden', !mcContext.permissions.includes('upload_media'));
    const voices = [...(mcContext.voices || [])].sort((a, b) => {
        const af = preferences.favorites.includes(a.alias) ? 0 : 1;
        const bf = preferences.favorites.includes(b.alias) ? 0 : 1;
        return af - bf || a.alias.localeCompare(b.alias);
    });
    mc('mcVoices').innerHTML = voices.map((voice, index) => {
        const selectedAlias = policy?.allow_voice_choice ? preferences.default_alias : policy?.default_alias;
        const selected = selectedAlias ? voice.alias === selectedAlias : index === 0;
        const favorite = preferences.favorites.includes(voice.alias);
        return `<label class="mc-voice ${selected ? 'is-selected' : ''}"><input type="radio" name="mcVoice" value="${mh(voice.alias)}" ${selected ? 'checked' : ''} ${policy?.allow_voice_choice ? '' : 'disabled'}><span><b>${mh(voice.label)}</b><br><small class="text-muted">${mh(voice.alias)}${voice.alias === selectedAlias ? ` · ${mh(mt('default_voice'))}` : ''}</small></span><button type="button" class="mc-favorite ${favorite ? 'is-active' : ''}" data-alias="${mh(voice.alias)}" title="${mh(mt('favorite'))}">★</button></label>`;
    }).join('') || `<p class="text-muted">${mh(mt('no_voices'))}</p>`;
    document.querySelectorAll('input[name="mcVoice"]').forEach(input => input.addEventListener('change', () => {
        document.querySelectorAll('.mc-voice').forEach(label => label.classList.toggle('is-selected', label.contains(input) && input.checked));
    }));
    document.querySelectorAll('.mc-favorite').forEach(button => button.addEventListener('click', event => { event.preventDefault(); mcToggleFavorite(button.dataset.alias); }));
}

async function mcToggleFavorite(alias) {
    const favorites = new Set(mcContext.preferences.favorites || []);
    favorites.has(alias) ? favorites.delete(alias) : favorites.add(alias);
    try {
        await mcApi('/api/moderator-console/preferences', {method:'PUT', body:JSON.stringify({default_alias:mcContext.preferences.default_alias || '', favorites:[...favorites]})});
        mcContext.preferences.favorites = [...favorites];
        mcRenderContext();
    } catch (error) { mc('mcSendStatus').textContent = `${mt('save_failed')}: ${error.message}`; }
}

async function mcSend() {
    const text = mc('mcText').value.trim();
    if (!text) return mc('mcSendStatus').textContent = mt('empty');
    const voice = mcContext.policy?.allow_voice_choice ? (document.querySelector('input[name="mcVoice"]:checked')?.value || '') : '';
    mc('mcSend').disabled = true;
    try {
        await mcApi('/api/moderator-console/tts', {method:'POST', body:JSON.stringify({text, voice_alias:voice, idempotency_key:`web:${crypto.randomUUID()}`})});
        mc('mcText').value = '';
        mc('mcCount').textContent = '0';
        mc('mcSendStatus').textContent = mt('sent');
        await mcLoadCommands();
    } catch (error) { mc('mcSendStatus').textContent = error.message; }
    finally { mc('mcSend').disabled = false; }
}

async function mcLoadCommands() {
    try {
        const result = await mcApi('/api/moderator-console/tts/commands');
        mc('mcCommands').innerHTML = (result.commands || []).map(command => `<article class="mc-command"><div class="flex justify-between gap-2"><span class="badge ${command.status === 'accepted' ? 'on' : 'off'}">${mh(command.status)}</span><time class="text-xs text-muted">${mh(new Date(command.created_at).toLocaleTimeString())}</time></div><p class="mc-command-text mt-1">${mh(command.text)}</p><small class="text-muted">${mh(command.voice_alias)}${command.reason ? ` · ${mh(command.reason)}` : ''}</small></article>`).join('') || `<p class="text-muted">${mh(mt('no_commands'))}</p>`;
    } catch (_) {}
}

function mcSwitchTab(tab) {
    document.querySelectorAll('[data-mc-panel]').forEach(panel => panel.classList.toggle('hidden', panel.dataset.mcPanel !== tab));
    document.querySelectorAll('[data-mc-tab]').forEach(button => {
        button.classList.toggle('btn-primary', button.dataset.mcTab === tab);
        button.classList.toggle('btn-secondary', button.dataset.mcTab !== tab);
    });
    if (tab === 'media') mcLoadMedia();
    if (tab === 'sounds') mcLoadSounds();
}

function mcRenderLibrary(kind) {
    const items = kind === 'media' ? mcMediaItems : mcSoundItems;
    const needle = mc(kind === 'media' ? 'mcMediaSearch' : 'mcSoundSearch').value.trim().toLowerCase();
    const box = mc(kind === 'media' ? 'mcMediaItems' : 'mcSoundItems');
    const filtered = items.filter(item => item.name.toLowerCase().includes(needle));
    box.innerHTML = filtered.map(item => `<article class="mc-library-item"><div class="flex justify-between gap-2"><b>${mh(item.name)}</b><button class="mc-favorite ${item.favorite ? 'is-active' : ''}" data-mc-favorite="${kind}" data-id="${item.id}" title="${mh(mt('favorite'))}">★</button></div><small class="text-muted">${mh(item.mime)}${item.duration_ms ? ` · ${(item.duration_ms / 1000).toFixed(1)}s` : ''}</small><div class="mc-library-actions"><button class="btn btn-secondary btn-sm" data-mc-preview="${kind}" data-id="${item.id}">${mh(mt('preview'))}</button><button class="btn btn-primary btn-sm" data-mc-play="${kind}" data-id="${item.id}">${mh(mt('play'))}</button></div></article>`).join('') || `<p class="text-muted">${mh(mt('no_items'))}</p>`;
}

async function mcLoadMedia() {
    try { const result = await mcApi('/api/moderator-media/library'); mcMediaItems = result.items || []; mcRenderLibrary('media'); }
    catch (error) { mc('mcMediaStatus').textContent = error.message; }
}

async function mcLoadSounds() {
    try { const result = await mcApi('/api/moderator-console/sounds'); mcSoundItems = result.items || []; mcRenderLibrary('sounds'); }
    catch (error) { mc('mcSoundStatus').textContent = error.message; }
}

async function mcStopSound() {
    try {
        await mcApi('/api/moderator-console/sounds/stop', {method:'POST'});
        mc('mcStatus').textContent = mcT('sound_stopped');
    } catch (error) { mc('mcStatus').textContent = error.message; }
}

async function mcPlayLibrary(kind, id) {
    const path = kind === 'media' ? '/api/moderator-media/cues' : '/api/moderator-console/sounds/play';
    const body = kind === 'media' ? {media_id:id, idempotency_key:`web:${crypto.randomUUID()}`} : {track_id:id, idempotency_key:`web:${crypto.randomUUID()}`};
    const status = mc(kind === 'media' ? 'mcMediaStatus' : 'mcSoundStatus');
    try { await mcApi(path, {method:'POST', body:JSON.stringify(body)}); status.textContent = mt('queued'); }
    catch (error) { status.textContent = error.message; }
}

async function mcToggleLibraryFavorite(kind, id) {
    const items = kind === 'media' ? mcMediaItems : mcSoundItems;
    const item = items.find(row => row.id === id);
    if (!item) return;
    item.favorite = !item.favorite;
    const ids = items.filter(row => row.favorite).map(row => row.id);
    const body = kind === 'media' ? {media_ids:ids} : {track_ids:ids};
    const path = kind === 'media' ? '/api/moderator-media/favorites' : '/api/moderator-console/sounds/favorites';
    try { await mcApi(path, {method:'PUT', body:JSON.stringify(body)}); mcRenderLibrary(kind); }
    catch (error) { item.favorite = !item.favorite; mc(kind === 'media' ? 'mcMediaStatus' : 'mcSoundStatus').textContent = error.message; }
}

async function mcPreview(kind, id) {
    const path = kind === 'media' ? `/api/moderator-media/library/${id}/preview` : `/api/moderator-console/sounds/${id}/preview`;
    const response = await fetch(path, {headers:{Authorization:`Bearer ${mcSession}`}});
    if (!response.ok) throw new Error(response.statusText);
    if (mcPreviewUrl) URL.revokeObjectURL(mcPreviewUrl);
    mcPreviewUrl = URL.createObjectURL(await response.blob());
    const item = (kind === 'media' ? mcMediaItems : mcSoundItems).find(row => row.id === id);
    const tag = kind === 'sounds' ? 'audio' : item?.media_kind === 'video' ? 'video' : 'img';
    const node = document.createElement(tag); node.src = mcPreviewUrl;
    if (tag !== 'img') { node.controls = true; node.autoplay = true; }
    mc('mcPreviewBody').replaceChildren(node); mc('mcPreviewDialog').showModal();
}

async function mcUploadMedia(event) {
    const file = event.target.files?.[0]; if (!file) return;
    const form = new FormData(); form.append('file', file);
    const response = await fetch('/api/moderator-media/library', {method:'POST', headers:{Authorization:`Bearer ${mcSession}`}, body:form});
    let result = {}; try { result = await response.json(); } catch (_) {}
    mc('mcMediaStatus').textContent = response.ok ? mt('uploaded_pending') : (result.detail || response.statusText);
    event.target.value = '';
}

document.addEventListener('click', event => {
    const tab = event.target.closest('[data-mc-tab]'); if (tab && !tab.disabled) mcSwitchTab(tab.dataset.mcTab);
    const reload = event.target.closest('[data-mc-reload]'); if (reload) reload.dataset.mcReload === 'media' ? mcLoadMedia() : mcLoadSounds();
    const stop = event.target.closest('[data-mc-stop="sounds"]'); if (stop) mcStopSound();
    const play = event.target.closest('[data-mc-play]'); if (play) mcPlayLibrary(play.dataset.mcPlay, Number(play.dataset.id));
    const preview = event.target.closest('[data-mc-preview]'); if (preview) mcPreview(preview.dataset.mcPreview, Number(preview.dataset.id)).catch(error => { mc(preview.dataset.mcPreview === 'media' ? 'mcMediaStatus' : 'mcSoundStatus').textContent = error.message; });
    const favorite = event.target.closest('[data-mc-favorite]'); if (favorite) mcToggleLibraryFavorite(favorite.dataset.mcFavorite, Number(favorite.dataset.id));
});

document.querySelectorAll('[data-lang]').forEach(button => button.addEventListener('click', () => mcSetLang(button.dataset.lang)));
mc('mcLoginButton').addEventListener('click', mcStartLogin);
mc('mcSend').addEventListener('click', mcSend);
mc('mcRefresh').addEventListener('click', mcLoadCommands);
mc('mcText').addEventListener('input', event => mc('mcCount').textContent = event.target.value.length);
mc('mcMediaSearch').addEventListener('input', () => mcRenderLibrary('media'));
mc('mcSoundSearch').addEventListener('input', () => mcRenderLibrary('sounds'));
mc('mcMediaUpload').addEventListener('change', mcUploadMedia);
mc('mcPreviewClose').addEventListener('click', () => mc('mcPreviewDialog').close());
mcSetLang(mcLang);
if (mcSession) mcLoadConsole(); else if (!mcInvite) mcLoginError(mt('missing_invite'));
