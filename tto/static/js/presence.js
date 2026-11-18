// Who is at the desk (tto/presence.py): the top bar's "● 3 çevrimiçi" and, on a click, the desk's users - çevrimiçi,
// uzakta (the dashboard open, nobody at it for 15 minutes), çevrimdışı - with when each was last seen and last signed in.
// The live stream carries the counts and a version: the list is asked for while it is open and only when somebody's
// state changed - nothing is polled.  Every tab (a window of its own too) tells the server when somebody types, clicks,
// scrolls or moves the mouse in it: at most once a minute, so the first move after a while is heard at once.
import { api, session } from './api.js';
import { h, clear } from './ui.js';

/** a tab tells the server of input at most this often (ms) */
const REPORT_EVERY = 60000;
/** the open list's "12 dk önce" is written again this often (ms) */
const PAINT_EVERY = 30000;
const DOT = { online: '●', away: '◐', offline: '○' };
export const STATE_TEXT = { online: 'çevrimiçi', away: 'uzakta', offline: 'çevrimdışı' };
const RANK = { online: 0, away: 1, offline: 2 };

const pr = {
  on: false,          // signed in: input is reported
  chip: false,        // this window has the top bar's chip (a window of its own has none)
  counters: null,     // the live stream's last word: {v, online, away, boot}
  data: null,         // the list as last asked for
  skew: 0,            // this computer's clock minus the server's (ms), from the list's "now"
  got: 0,             // when the list came (this computer's clock)
  pop: null,          // the open list: {el, timer}
  loading: null,
  again: false,
  input: Date.now(),  // the last key / click / scroll / mouse move in this tab
  sent: 0,            // when this tab last told the server
  subs: new Set(),    // what else follows a change (the Kullanıcılar page)
};

const $ = (id) => document.getElementById(id);
const pad = (n) => String(n).padStart(2, '0');

/** "2026-11-18 10:15:03" (the server's local time) as milliseconds - read the same way as the list's "now". */
export function stampMs(stamp) {
  const m = /^(\d{4})-(\d\d)-(\d\d)[ T](\d\d):(\d\d)(?::(\d\d))?/.exec(stamp || '');
  return m ? new Date(+m[1], m[2] - 1, +m[3], +m[4], +m[5], +(m[6] || 0)).getTime() : null;
}

/** When, said shortly against ``nowMs``: "şimdi", "12 dk önce", "bugün 08:01", "dün 18:40", "14.11 09:12" (another
 *  year: "14.11.2025 09:12"); "—": never. */
export function ago(stamp, nowMs) {
  const t = stampMs(stamp);
  if (t === null) return '—';
  const d = nowMs - t;
  if (d < 60000) return 'şimdi';
  if (d < 3600000) return Math.floor(d / 60000) + ' dk önce';
  const at = new Date(t);
  const now = new Date(nowMs);
  const hm = pad(at.getHours()) + ':' + pad(at.getMinutes());
  const days = Math.round((new Date(now.getFullYear(), now.getMonth(), now.getDate()) - new Date(at.getFullYear(), at.getMonth(), at.getDate())) / 86400000);
  if (days === 0) return 'bugün ' + hm;
  if (days === 1) return 'dün ' + hm;
  return pad(at.getDate()) + '.' + pad(at.getMonth() + 1) + (at.getFullYear() !== now.getFullYear() ? '.' + at.getFullYear() : '') + ' ' + hm;
}

/** "18.11.2026 10:15" of a stamp (a cell's title). */
function full(stamp) {
  const t = stampMs(stamp);
  if (t === null) return '';
  const d = new Date(t);
  return pad(d.getDate()) + '.' + pad(d.getMonth() + 1) + '.' + d.getFullYear() + ' ' + pad(d.getHours()) + ':' + pad(d.getMinutes());
}

/** How long, from seconds: "16 dk", "1 sa 20 dk". */
export function lasted(seconds) {
  const m = Math.floor(Math.max(0, seconds) / 60);
  return m < 60 ? m + ' dk' : Math.floor(m / 60) + ' sa ' + (m % 60) + ' dk';
}

// ---------------------------------------------------------------------- this tab's input, told to the server
function report(idle) {
  if (!pr.on) return;
  pr.sent = Date.now();
  api.post('/api/presence', { idle: Math.max(0, Math.round(idle || 0)) }).catch(() => { /* told with the next move */ });
}

function moved() {
  pr.input = Date.now();
  if (pr.on && pr.input - pr.sent >= REPORT_EVERY) report(0);
}

for (const ev of ['pointerdown', 'keydown', 'wheel', 'touchstart', 'mousemove']) {
  window.addEventListener(ev, moved, { capture: true, passive: true });
}
window.addEventListener('focus', moved);
document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') moved(); });

// ---------------------------------------------------------------------- the chip
function paintChip() {
  const chip = $('presence-chip');
  if (!chip) return;
  const c = pr.on && pr.chip ? pr.counters : null;
  chip.classList.toggle('hidden', !c);
  if (!c) return;
  $('presence-n').textContent = String(c.online);
  chip.title = c.online + ' çevrimiçi' + (c.away ? ', ' + c.away + ' uzakta' : '')
    + ' – kim bağlı, kim en son ne zaman girdi: görmek için tıklayın';
}

// ---------------------------------------------------------------------- the list
async function load() {
  if (pr.loading) { pr.again = true; return pr.loading; }
  pr.loading = (async () => {
    do {
      pr.again = false;
      const d = await api.get('/api/presence');
      if (!pr.on) return;
      pr.data = d;
      pr.got = Date.now();
      const t = stampMs(d.now);
      pr.skew = t === null ? 0 : pr.got - t;
      paint();
    } while (pr.again);
  })().catch(() => { /* the list waits for the next change */ }).finally(() => { pr.loading = null; });
  return pr.loading;
}

function place() {
  const chip = $('presence-chip');
  if (!pr.pop || !chip) return;
  const r = chip.getBoundingClientRect();
  const el = pr.pop.el;
  const w = el.offsetWidth;
  el.style.top = Math.round(r.bottom + 6) + 'px';
  el.style.left = Math.max(6, Math.min(Math.round(r.right - w), window.innerWidth - w - 6)) + 'px';
}

function paint() {
  if (!pr.pop) return;
  const el = clear(pr.pop.el);
  const d = pr.data;
  if (!d) {
    el.appendChild(h('div', { class: 'empty' }, 'Yükleniyor…'));
    place();
    return;
  }
  const now = Date.now() - pr.skew;                         // the server's clock now
  const since = Math.max(0, (Date.now() - pr.got) / 1000);  // seconds since the list came
  const users = d.users.slice().sort((a, b) => RANK[a.state] - RANK[b.state] || a.display.localeCompare(b.display, 'tr'));
  const off = users.length - d.online - d.away;
  el.appendChild(h('div', { class: 'pr-head' }, h('b', null, 'Masa'),
    h('span', { class: 'muted', id: 'presence-sum' }, ' · ' + d.online + ' çevrimiçi' + (d.away ? ' · ' + d.away + ' uzakta' : '')
      + ' · ' + off + ' çevrimdışı')));
  const body = h('tbody');
  for (const u of users) {
    const idle = u.state === 'away' && u.idle !== undefined && u.idle !== null ? lasted(u.idle + since) : '';
    body.appendChild(h('tr', { dataset: { user: u.name, state: u.state }, class: u.me ? 'me' : null },
      h('td', { class: 'l pr-name' }, h('span', { class: 'pr-dot ' + u.state, 'aria-hidden': 'true' }, DOT[u.state]), ' ', u.display,
        u.me ? h('span', { class: 'muted' }, ' (siz)') : null),
      h('td', { class: 'l pr-state ' + u.state, title: idle ? 'Dashboard açık; ' + idle + ' boyunca klavye / fare kullanılmadı' : null },
        STATE_TEXT[u.state] + (idle ? ' · ' + idle : '')),
      h('td', { class: 'pr-seen', title: full(u.last_seen) || null }, u.state === 'offline' ? ago(u.last_seen, now) : 'şimdi'),
      h('td', { class: 'pr-login', title: full(u.last_login) || null }, ago(u.last_login, now))));
  }
  el.appendChild(h('table', { class: 'plain pr-table', id: 'presence-table' },
    h('thead', null, h('tr', null, h('th', { class: 'l' }, 'Kullanıcı'), h('th', { class: 'l' }, 'Durum'), h('th', null, 'Son görülme'),
      h('th', null, 'Son giriş'))), body));
  el.appendChild(h('div', { class: 'pr-note muted' }, 'Çevrimiçi: dashboard bir tarayıcıda açık ve son 15 dakikada klavye ya da fare '
    + 'kullanılmış. Uzakta: açık, ama 15 dakikadır kullanılmıyor. Son görülme: dashboard\'un en son açık olduğu an; son giriş: '
    + 'şifreyle en son giriş.'));
  place();
}

function openList() {
  if (pr.pop) { closeList(); return; }
  const el = h('div', { class: 'presence-pop', id: 'presence-list', role: 'dialog', 'aria-label': 'Kim çevrimiçi' });
  document.body.appendChild(el);
  pr.pop = { el, timer: setInterval(paint, PAINT_EVERY) };
  $('presence-chip').setAttribute('aria-expanded', 'true');
  paint();                                   // (what is in hand at once; the list as it is now follows)
  load();
}

function closeList() {
  if (!pr.pop) return;
  clearInterval(pr.pop.timer);
  pr.pop.el.remove();
  pr.pop = null;
  const chip = $('presence-chip');
  if (chip) chip.setAttribute('aria-expanded', 'false');
}

document.addEventListener('mousedown', (e) => {
  const chip = $('presence-chip');
  if (pr.pop && !pr.pop.el.contains(e.target) && !(chip && chip.contains(e.target))) closeList();
}, true);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && pr.pop) closeList(); }, true);
window.addEventListener('resize', place);

// ---------------------------------------------------------------------- wiring (main.js, the Kullanıcılar page)
/** Signed in (``pop``: a window of its own - no chip there, its input is told all the same). */
export function startPresence(pop) {
  stopPresence();
  pr.on = true;
  pr.chip = !pop;
  pr.input = Date.now();
  const chip = $('presence-chip');
  if (chip && !chip.dataset.wired) {
    chip.dataset.wired = '1';
    chip.addEventListener('click', openList);
  }
  report(0);                                 // (signed in, the page opened: somebody is at it)
}

/** Signed out: nothing of it stays on the screen. */
export function stopPresence() {
  pr.on = false;
  pr.counters = null;
  pr.data = null;
  closeList();
  paintChip();
}

/** The live stream's word ({v, online, away, boot}): the chip follows; the open list - and whoever follows - is asked
 *  for again when somebody's state changed. */
export function presenceEvent(c) {
  if (!c || !pr.on || !session.user) return;
  const prev = pr.counters;
  pr.counters = c;
  if (prev && prev.boot !== c.boot) report((Date.now() - pr.input) / 1000);   // the server started again: how idle we are
  paintChip();
  if (prev && prev.v === c.v && prev.boot === c.boot) return;
  if (pr.pop) load();
  if (!prev) return;
  for (const fn of pr.subs) {
    try { fn(); } catch (e) { /* the follower's own business */ }
  }
}

/** ``fn`` is called whenever somebody's state changed; returns what stops it. */
export function onPresence(fn) {
  pr.subs.add(fn);
  return () => pr.subs.delete(fn);
}
