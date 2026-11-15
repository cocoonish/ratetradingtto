// The desk's own corner in the shell: the "Hata / Öneri" button of the top bar (a report for the administrators; for
// them a "!" on it while reports are open, and the list to deal with them), the menu's badges of Sosyal (messages not
// read yet) and Ajanda (today's items, deadlines not met) and the agenda's reminders.  The live stream carries the
// corner's counters (no new generation): what changed is asked for, nothing else is read again.
// Everything a user typed goes on the page as text only.
import { api, session } from './api.js';
import { h, clear, toast, errorToast, modal } from './ui.js';

const DAYS = ['Pazar', 'Pazartesi', 'Salı', 'Çarşamba', 'Perşembe', 'Cuma', 'Cumartesi'];
const MONTHS = ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık'];
const KIND = { bug: 'Hata', idea: 'Öneri' };
/** how long before a deadline with a time it is told, and how long after its time a reminder is still shown (ms) */
const SOON = 15 * 60000;
const LATE = 60 * 60000;

const desk = { hooks: null, counters: null, state: null, timer: null, loading: null, again: false, day: null, reports: null };

function local(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, value);
  } catch (e) { /* storage unavailable: nothing remembered */ }
  return null;
}

const pad = (n) => String(n).padStart(2, '0');
/** "2026-11-15" of a moment, in this computer's time */
export const localDay = (d) => d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
/** "14:05" of a moment */
export const hhmm = (d) => pad(d.getHours()) + ':' + pad(d.getMinutes());
/** "15 Kasım 2026 Pazar" */
export function dayTitle(iso) {
  const [y, m, d] = iso.split('-').map(Number);
  return d + ' ' + MONTHS[m - 1] + ' ' + y + ' ' + DAYS[new Date(y, m - 1, d).getDay()];
}
/** The day after (and before) a "yyyy-mm-dd" */
export function shiftDay(iso, n) {
  const [y, m, d] = iso.split('-').map(Number);
  return localDay(new Date(y, m - 1, d + n));
}
/** "15.11.2026 14:05" of a "2026-11-15 14:05:31" */
export function stampText(stamp) {
  if (!stamp) return '';
  const [d, t] = String(stamp).split(' ');
  const [y, m, day] = d.split('-');
  return day + '.' + m + '.' + y + (t ? ' ' + t.slice(0, 5) : '');
}

/** A deadline not met: its day passed, or its time today. */
export function isLate(it, today, now) {
  return it.deadline && !it.done && (it.day < today || (it.day === today && !!it.time && it.time <= now));
}

// ---------------------------------------------------------------------- the chat read so far (this browser)
const seenKey = () => 'tto.chat.seen.' + session.user;

export function chatSeen() {
  const v = parseInt(local(seenKey()), 10);
  return Number.isFinite(v) ? v : null;
}

/** The chat page showed everything up to the message ``id``. */
export function markChatSeen(id) {
  if (!session.user || !id) return;
  if (id > (chatSeen() || 0)) local(seenKey(), String(id));
  const st = desk.state;
  if (!st || !st.chat.unread) return;
  if (id >= st.chat.last) { st.chat.unread = 0; paintNav(); } else loadState();     // something came after: count again
}

// ---------------------------------------------------------------------- what the shell shows
async function loadState() {
  if (desk.loading) { desk.again = true; return desk.loading; }
  desk.loading = (async () => {
    do {
      desk.again = false;
      const seen = chatSeen();
      const st = await api.get('/api/desk', seen === null ? {} : { seen });
      if (!session.user) return;
      if (seen === null) local(seenKey(), String(st.chat.last));      // a browser new to the chat starts with all of it read
      if ((chatSeen() || 0) >= st.chat.last) st.chat.unread = 0;       // the chat page read it all while this was asked
      desk.state = st;
      desk.day = localDay(new Date());
      paintNav();
      paintAlert();
      remind();
    } while (desk.again);
  })().catch(() => { /* the badges wait for the next change */ }).finally(() => { desk.loading = null; });
  return desk.loading;
}

function navBadge(page, n, title, alert) {
  const item = document.querySelector('#nav .nav-item[data-page="' + page + '"]');
  if (!item) return;
  let el = item.querySelector('.nav-count');
  if (!n) { if (el) el.remove(); return; }
  if (!el) { el = h('span', { class: 'nav-count' }); item.appendChild(el); }
  el.textContent = n > 99 ? '99+' : String(n);
  el.title = title;
  el.classList.toggle('alert', !!alert);
}

/** The menu's badges: Sosyal (messages of the others not read yet), Ajanda (today's items and deadlines not met). */
export function paintNav() {
  const st = desk.state;
  const onChat = desk.hooks && desk.hooks.pageId() === 'social' && document.visibilityState === 'visible';
  const unread = st && !onChat ? st.chat.unread : 0;
  navBadge('social', unread, unread + ' okunmamış mesaj', false);
  const now = new Date();
  const today = localDay(now);
  const time = hhmm(now);
  const items = st ? st.agenda : [];
  const late = items.filter((it) => isLate(it, today, time)).length;
  const todays = items.filter((it) => it.day === today && !isLate(it, today, time)).length;
  navBadge('agenda', late + todays, (todays ? 'Bugün ' + todays + ' iş' : '') + (todays && late ? ' · ' : '')
    + (late ? late + ' gecikmiş deadline' : ''), late > 0);
}

function paintAlert() {
  const btn = document.getElementById('btn-feedback');
  const mark = document.getElementById('fb-alert');
  if (!btn || !mark) return;
  const admin = session.role === 'admin';
  const n = admin && desk.state ? desk.state.feedback || 0 : 0;
  mark.classList.toggle('hidden', !n);
  btn.title = !admin ? 'Hata bildirin ya da öneri gönderin (yöneticilere gider)'
    : n ? n + ' açık bildirim – görmek için tıklayın' : 'Bildirimler · hata bildirin ya da öneri gönderin';
}

// ---------------------------------------------------------------------- the agenda's reminders
const toldKey = () => 'tto.agenda.told.' + session.user;

/** What is to be told of an item now: [stage, text, toast kind]. */
function reminders(it, now) {
  const out = [];
  const what = (it.time ? it.time + ' · ' : '') + it.text;
  if (it.time) {
    const left = new Date(it.day + 'T' + it.time + ':00') - now;
    if (it.deadline && left > 0 && left <= SOON) out.push(['soon', 'Deadline yaklaşıyor (' + Math.ceil(left / 60000) + ' dk): ' + what, 'warn']);
    if (left <= 0 && left > -LATE) out.push(['now', (it.deadline ? 'Deadline geldi: ' : 'Hatırlatma: ') + what, it.deadline ? 'err' : '']);
  } else if (it.deadline) {
    const today = localDay(now);
    if (it.day === shiftDay(today, 1)) out.push(['eve', 'Yarın son gün: ' + it.text, 'warn']);
    if (it.day === today) out.push(['day', 'Bugün son gün: ' + it.text, 'err']);
  }
  return out;
}

/** Tell (once per browser) what is coming or has come: a deadline 15 minutes before its time and at it (one without a
 * time the day before and on the day), any item with a time at its time. */
function remind() {
  const st = desk.state;
  if (!st || !session.user) return;
  const now = new Date();
  let told;
  try { told = new Set(JSON.parse(local(toldKey()) || '[]')); } catch (e) { told = new Set(); }
  for (const it of st.agenda) {
    for (const [stage, text, kind] of reminders(it, now)) {
      const key = it.id + ':' + stage;
      if (told.has(key)) continue;
      told.add(key);
      const t = toast(text, kind + ' click', 20000);
      t.title = 'Ajandayı aç';
      t.addEventListener('click', () => { t.remove(); window.location.hash = '#/agenda'; });
    }
  }
  const due = new Set(st.agenda.map((it) => String(it.id)));
  local(toldKey(), JSON.stringify([...told].filter((k) => due.has(k.split(':')[0]))));
}

function tick() {
  if (!session.user) return;
  if (desk.day !== localDay(new Date())) { loadState(); return; }   // a new day: what is due is asked again
  paintNav();
  remind();
}

// ---------------------------------------------------------------------- reports: the form, the administrators' list
function openReportForm() {
  const where = desk.hooks.where();
  const m = modal({ title: 'Hata bildir · öneri gönder', width: 540 });
  let kind = 'bug';
  const seg = h('div', { class: 'seg', id: 'fb-kind' },
    h('button', { type: 'button', class: 'on', 'data-v': 'bug' }, 'Hata'), h('button', { type: 'button', 'data-v': 'idea' }, 'Öneri'));
  const text = h('textarea', { class: 'inp', id: 'fb-text', rows: '7', maxlength: '2000',
    placeholder: 'Ne oldu, ne bekliyordunuz? Hangi sayfada olduğunuz kendiliğinden eklenir.' });
  seg.addEventListener('click', (e) => {
    const b = e.target.closest('button');
    if (!b) return;
    kind = b.dataset.v;
    for (const x of seg.children) x.classList.toggle('on', x === b);
    text.placeholder = kind === 'bug' ? 'Ne oldu, ne bekliyordunuz? Hangi sayfada olduğunuz kendiliğinden eklenir.'
      : 'Neyin nasıl daha iyi olabileceğini yazın.';
    text.focus();
  });
  const err = h('div', { class: 'errtxt' });
  m.body.appendChild(h('div', { class: 'fb-form' }, seg, text,
    h('div', { class: 'muted' }, 'Sayfa: ' + (where.title || '–') + ' · Yöneticilere gider.'), err));
  const send = h('button', { class: 'btn primary', type: 'button', id: 'fb-send' }, 'Gönder');
  const submit = async () => {
    if (!text.value.trim()) { err.textContent = 'Bir şey yazın'; text.focus(); return; }
    send.disabled = true;
    try {
      await api.post('/api/feedback', { kind, text: text.value, page: where.id, title: where.title });
      m.close();
      toast('Teşekkürler – ' + (kind === 'bug' ? 'bildiriminiz' : 'öneriniz') + ' yöneticilere iletildi', 'ok', 4000);
    } catch (e) {
      err.textContent = e.message;
    } finally {
      send.disabled = false;
    }
  };
  send.addEventListener('click', submit);
  text.addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); submit(); } });
  m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Vazgeç'));
  m.foot.appendChild(send);
  text.focus();
}

function reportItem(r, act) {
  const head = h('div', { class: 'fb-head' }, h('span', { class: 'desk-tag ' + r.kind }, KIND[r.kind] || r.kind), h('b', null, r.by),
    h('span', { class: 'muted' }, stampText(r.at)));
  if (r.page) {
    const link = h('a', { href: '#/' + encodeURIComponent(r.page), title: 'Bu sayfayı aç' }, r.title || r.page);
    link.addEventListener('click', () => { if (desk.reports) desk.reports.close(); });
    head.appendChild(h('span', { class: 'muted' }, '· '));
    head.appendChild(link);
  }
  const item = h('div', { class: 'fb-item', dataset: { id: String(r.id) } }, head, h('div', { class: 'fb-text' }, r.text));
  item.appendChild(h('div', { class: 'fb-act' }, r.done_at ? h('span', { class: 'muted' }, 'İlgilenildi: ' + r.done_by + ' · '
    + stampText(r.done_at)) : null, act));
  return item;
}

function openReports() {
  const m = modal({ title: 'Bildirimler', width: 760, onClose: () => { desk.reports = null; } });
  const box = h('div', { class: 'fb-list', id: 'fb-list' }, h('div', { class: 'empty' }, 'Yükleniyor…'));
  let historyOpen = false;                          // the history stays open when the list is drawn again
  m.body.appendChild(box);
  const act = async (id, done) => {
    try {
      render(await api.post('/api/feedback/' + id, { done }));
    } catch (e) { errorToast(e); }
  };
  const render = (d) => {
    if (desk.state) { desk.state.feedback = d.count; paintAlert(); }
    clear(box);
    box.appendChild(h('h3', null, 'Açık (' + d.count + ')'));
    if (!d.open.length) box.appendChild(h('div', { class: 'empty' }, 'Açık bildirim yok.'));
    for (const r of d.open) {
      box.appendChild(reportItem(r, h('button', { class: 'btn sm primary', type: 'button', onclick: () => act(r.id, true) }, 'İlgilenildi')));
    }
    if (d.done.length) {
      const past = h('details', { class: 'fb-done', open: historyOpen }, h('summary', null, 'İlgilenilenler (son ' + d.done.length + ')'));
      past.addEventListener('toggle', () => { historyOpen = past.open; });
      for (const r of d.done) {
        past.appendChild(reportItem(r, h('button', { class: 'btn sm', type: 'button', onclick: () => act(r.id, false) }, 'Yeniden aç')));
      }
      box.appendChild(past);
    }
  };
  const reload = () => api.get('/api/feedback').then(render).catch(errorToast);
  desk.reports = { reload, close: () => m.close() };
  m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => { m.close(); openReportForm(); } }, 'Yeni bildirim yaz'));
  m.foot.appendChild(h('span', { class: 'grow' }));
  m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Kapat'));
  reload();
}

// ---------------------------------------------------------------------- wiring (main.js)
/** Once, at boot: ``hooks`` = { page(): the open page, pageId(): its id, where(): {id, title} of the open page }. */
export function setupDesk(hooks) {
  desk.hooks = hooks;
  document.getElementById('btn-feedback').addEventListener('click', () => {
    if (session.role === 'admin') openReports(); else openReportForm();
  });
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') paintNav(); });
}

/** Signed in: the badges and the reminders start. */
export function startDesk() {
  stopDesk();
  desk.timer = setInterval(tick, 30000);
  paintAlert();
  loadState();
}

/** Signed out: nothing of the corner stays on the screen. */
export function stopDesk() {
  if (desk.timer) clearInterval(desk.timer);
  desk.timer = null;
  desk.state = null;
  desk.counters = null;
  if (desk.reports) desk.reports.close();
  paintNav();
  paintAlert();
}

/** A connection of the live stream opened: its first message is taken as news of everything. */
export function deskReconnected() {
  desk.counters = null;
}

/** The live stream's counters of the corner: what changed is read again (the badges; the open page, if it is ours). */
export function deskEvent(counters) {
  if (!counters || !session.user) return;
  const prev = desk.counters;
  desk.counters = counters;
  const changed = Object.keys(counters).filter((k) => !prev || prev[k] !== counters[k]);
  if (!changed.length) return;
  loadState();
  // the open page, also while it is still loading (it reads again once it is there: nothing is missed)
  const page = desk.hooks.page();
  if (page && page.onDesk) page.onDesk(changed);
  if (desk.reports && changed.includes('feedback')) desk.reports.reload();
}
