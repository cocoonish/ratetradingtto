// The agenda's recurring items' alarms (Ajanda → Tekrarlayan işler), on whatever page of the main window is open.  The
// server says what is to be told now - a deadline 15 minutes before its time, every day's item at its time (late when
// the dashboard was not open then), again when one's "Ertele" is over - and in how many seconds that changes
// (``alarms`` and ``next`` of /api/desk).  Each is told once per browser: two windows of one browser agree on which of
// them tells it (the one that wrote its name last, as the live stream's holder is chosen), the other stays quiet.  The
// toast stays until it is answered - "Ertele 10 dk" (for oneself: the others are told as before), "Bugün tamam" (that
// day only) - or the day is done or put off elsewhere; a tone and the browser's notification go with it.
// What a user typed goes on the page as text only.
import { api, session } from './api.js';
import { h, toast, errorToast } from './ui.js';
import { tone, notify } from './alarms.js';

/** how long two windows of a browser wait to agree on which of them tells an alarm (ms) */
const AGREE = 300;
const TAB = Math.random().toString(36).slice(2) + Date.now().toString(36);
const run = { state: null, timer: null, due: 0 };
const told = new Set();                 // the alarms this page told, by user (``slot``; its toast may be gone)
const shown = new Map();                // key -> its toast on this page

const pad = (n) => String(n).padStart(2, '0');
const dayOf = (d) => d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
/** Where this browser keeps which window told an alarm (``key``: "r12@2026-11-16:due"). */
const slot = (key) => 'tto.agenda.rep.' + session.user + '.' + key;

let storage = null;
/** Whether this browser keeps what it is given (a private window may not: then each page tells on its own). */
function canStore() {
  if (storage === null) {
    try {
      localStorage.setItem('tto.agenda.rep.t', '1');
      localStorage.removeItem('tto.agenda.rep.t');
      storage = true;
    } catch (e) { storage = false; }
  }
  return storage;
}

function holder(key) {
  try { return localStorage.getItem(slot(key)); } catch (e) { return null; }
}

/** What is kept of the days before yesterday goes. */
function forget() {
  const prefix = slot('');
  const before = dayOf(new Date(Date.now() - 2 * 86400000));
  try {
    const old = [];
    for (let i = 0; i < localStorage.length; i++) {
      const k = localStorage.key(i);
      if (k && k.startsWith(prefix) && (k.slice(prefix.length).split('@')[1] || '').slice(0, 10) < before) old.push(k);
    }
    for (const k of old) localStorage.removeItem(k);
  } catch (e) { /* storage unavailable */ }
}

function drop(key) {
  const el = shown.get(key);
  if (el) el.remove();
  shown.delete(key);
}

/** One alarm on the screen: what, "Ertele 10 dk" and "Bugün tamam"; a click elsewhere on it opens the agenda. */
function tell(a) {
  told.add(slot(a.key));
  const later = h('button', { class: 'btn sm ag-snooze', type: 'button',
    title: 'Yalnızca sizin için 10 dakika sonra yeniden hatırlatır (başkalarına hatırlatma sürer)' }, 'Ertele 10 dk');
  const done = h('button', { class: 'btn sm ag-done', type: 'button',
    title: 'Bugünkü tekrarı tamamlandı olarak işaretler – diğer günler değişmez' }, 'Bugün tamam');
  const el = toast(h('span', null, h('span', { class: 'ag-text' }, a.text),
    h('span', { class: 'ag-meta' }, '↻ ' + a.repeat + (a.shared ? '' : ' · kişisel')), h('span', { class: 'ag-act' }, later, done)),
  'agenda-alarm click' + (a.kind ? ' ' + a.kind : ''), 12 * 3600000);
  el.dataset.key = a.key;
  el.title = 'Ajandayı aç';
  shown.set(a.key, el);
  const answer = async (what, body) => {
    later.disabled = true;
    done.disabled = true;
    try {
      const res = await api.post('/api/agenda/rules/' + a.rule + '/' + what, body);
      drop(a.key);
      toast(what === 'snooze' ? 'Ertelendi · yeniden hatırlatma ' + (res.snoozed || '') + ' (yalnızca size)'
        : 'Bugün için tamamlandı: ' + a.time + ' · ' + a.repeat, 'ok', 3500);
    } catch (err) {
      errorToast(err);
      later.disabled = false;
      done.disabled = false;
    }
  };
  later.addEventListener('click', (e) => { e.stopPropagation(); answer('snooze', { day: a.day }); });
  done.addEventListener('click', (e) => { e.stopPropagation(); answer('done', { day: a.day, done: true }); });
  el.addEventListener('click', () => { drop(a.key); window.location.hash = '#/agenda'; });
  tone();
  notify('TTO ajanda · ' + a.time, a.text, 'tto-agenda-' + a.key);
}

/** A state of /api/desk: its alarms told (once per browser), the ones no longer to be told taken off the screen, and
 *  the state asked for again (``reload``) when what is to be told changes next.  The same state again (the shell's
 *  half-minute tick): nothing new - unless asking again at that moment did not come through (asked once more). */
export function playRepeats(st, reload) {
  if (!st || !session.user) return;
  if (st === run.state) {
    if (run.due && Date.now() > run.due + 5000) { run.due = Date.now() + 25000; reload(); }
    return;
  }
  run.state = st;
  clearTimeout(run.timer);
  run.timer = null;
  run.due = 0;
  if (typeof st.next === 'number') {
    run.due = Date.now() + st.next * 1000;
    if (st.next < 86400) run.timer = setTimeout(() => { run.timer = null; reload(); }, st.next * 1000 + 500);
  }
  const alarms = st.alarms || [];
  const current = new Set(alarms.map((a) => a.key));
  for (const key of [...shown.keys()]) if (!current.has(key)) drop(key);      // done, put off, or a later moment's
  const fresh = alarms.filter((a) => !told.has(slot(a.key)) && (!canStore() || [null, TAB].includes(holder(a.key))));
  if (!fresh.length) return;
  if (!canStore()) { fresh.forEach(tell); return; }
  for (const a of fresh) {
    try { localStorage.setItem(slot(a.key), TAB); } catch (e) { /* not kept */ }
  }
  forget();
  setTimeout(() => {
    for (const a of fresh) {
      // another window of this browser wrote after this one: that one tells it; gone meanwhile: nobody does
      if (!session.user || told.has(slot(a.key)) || holder(a.key) !== TAB) continue;
      if (!run.state || !(run.state.alarms || []).some((x) => x.key === a.key)) continue;
      tell(a);
    }
  }, AGREE);
}

/** Signed out: nothing of it stays on the screen. */
export function stopRepeats() {
  clearTimeout(run.timer);
  Object.assign(run, { state: null, timer: null, due: 0 });
  for (const key of [...shown.keys()]) drop(key);
}
