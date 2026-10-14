// ── Календарь недели (владелец 27.09 вечером) ──────────────────────
// Расписание каналов, пачек ботов и TTS-моментов на одной сетке 7 дней,
// вместо разбросанных по разделам настроек (app/weekly_schedule.py).
const CALENDAR_DAY_KEYS = ['calendar.mon', 'calendar.tue', 'calendar.wed', 'calendar.thu', 'calendar.fri', 'calendar.sat', 'calendar.sun'];
let _calendarEvents = [];
let _calendarPacks = [];

async function loadCalendarSection() {
    const el = $('calendarGrid');
    if (!el) return;
    try {
        const [data, packs] = await Promise.all([
            api('/api/weekly-schedule'),
            api('/api/packs').catch(() => ({ packs: [] })),
        ]);
        _calendarEvents = data.events || [];
        _calendarPacks = packs.packs || (Array.isArray(packs) ? packs : []);
        renderCalendarGrid();
    } catch (e) {
        el.innerHTML = `<div class="card text-error p-4">${esc(t('api.error.request_failed'))}</div>`;
    }
}

function _calendarKindBadge(kind) {
    if (kind === 'channel') return t('calendar.kind_channel');
    if (kind === 'pack') return t('calendar.kind_pack');
    return t('calendar.kind_tts');
}

function renderCalendarGrid() {
    const el = $('calendarGrid');
    if (!el) return;
    const byDay = Array.from({ length: 7 }, () => []);
    _calendarEvents.forEach(ev => { if (byDay[ev.day_of_week]) byDay[ev.day_of_week].push(ev); });
    el.innerHTML = byDay.map((events, day) => `
        <div class="calendar-day-col">
            <div class="calendar-day-title">${esc(t(CALENDAR_DAY_KEYS[day]))}</div>
            ${events.map(ev => `
                <div class="calendar-event">
                    <div class="flex justify-between items-start gap-1">
                        <span class="calendar-event-time">${esc(ev.time)}</span>
                        <span class="badge">${esc(_calendarKindBadge(ev.kind))}</span>
                    </div>
                    <div>${esc(ev.title)}</div>
                    ${ev.channel ? `<div class="text-muted text-xs">#${esc(ev.channel)}</div>` : ''}
                    ${ev.pack_name ? `<div class="text-muted text-xs">📦 ${esc(ev.pack_name)}</div>` : ''}
                    ${ev.note ? `<div class="text-muted text-xs">${esc(ev.note)}</div>` : ''}
                    <div class="flex gap-1 mt-1">
                        <button class="btn btn-sm btn-secondary" onclick="openCalendarEventModal(${ev.id})">✎</button>
                        <button class="btn btn-sm btn-danger" onclick="deleteCalendarEvent(${ev.id})">✕</button>
                    </div>
                </div>`).join('') || `<div class="text-muted text-xs">${esc(t('calendar.empty_day'))}</div>`}
        </div>`).join('');
}

function calendarEventKindChanged() {
    const kind = $('calendarEventKind').value;
    $('calendarEventChannelGroup').classList.toggle('hidden', kind !== 'channel');
    $('calendarEventPackGroup').classList.toggle('hidden', kind !== 'pack');
}

function openCalendarEventModal(eventId) {
    const ev = eventId ? _calendarEvents.find(e => e.id === eventId) : null;
    $('calendarEventId').value = ev ? ev.id : '';
    $('calendarEventDay').value = ev ? ev.day_of_week : new Date().getDay() === 0 ? 6 : new Date().getDay() - 1;
    $('calendarEventTime').value = ev ? ev.time : '19:00';
    $('calendarEventKind').value = ev ? ev.kind : 'channel';
    $('calendarEventTitleInput').value = ev ? ev.title : '';
    $('calendarEventChannel').value = ev ? ev.channel : '';
    $('calendarEventNote').value = ev ? ev.note : '';
    $('calendarEventError').textContent = '';
    const packSel = $('calendarEventPack');
    if (packSel) {
        packSel.innerHTML = _calendarPacks.map(p => `<option value="${esc(p.id)}">${esc(p.name)}</option>`).join('');
        if (ev && ev.pack_id) packSel.value = ev.pack_id;
    }
    calendarEventKindChanged();
    showModal('calendarEventModal');
}

async function submitCalendarEvent() {
    const id = $('calendarEventId').value;
    const kind = $('calendarEventKind').value;
    const payload = {
        day_of_week: parseInt($('calendarEventDay').value, 10),
        time: $('calendarEventTime').value,
        kind,
        title: $('calendarEventTitleInput').value.trim(),
        channel: kind === 'channel' ? $('calendarEventChannel').value.trim() : '',
        pack_id: kind === 'pack' ? parseInt($('calendarEventPack').value, 10) || null : null,
        note: $('calendarEventNote').value.trim(),
    };
    if (!payload.title) { $('calendarEventError').textContent = t('calendar.error_title'); return; }
    try {
        const res = id
            ? await api(`/api/weekly-schedule/${id}`, jopts('PUT', payload))
            : await api('/api/weekly-schedule', jopts('POST', payload));
        if (res.ok === false) { $('calendarEventError').textContent = t('calendar.error_generic'); return; }
        hideModal('calendarEventModal');
        loadCalendarSection();
        toast(t('calendar.saved'), 'success');
    } catch (e) { $('calendarEventError').textContent = e.message; }
}

async function deleteCalendarEvent(eventId) {
    if (!confirm(t('calendar.delete_confirm'))) return;
    try {
        await api(`/api/weekly-schedule/${eventId}`, jopts('DELETE', {}));
        loadCalendarSection();
    } catch (e) { toast(t('toast.error_detail', { detail: e.message }), 'error'); }
}