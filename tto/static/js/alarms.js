// Alarms on any cell, the watch list's "add", and telling the user an alarm fired - on whatever page is open:
// a toast that stays a while, a short tone, and the browser's own notification when it is allowed.
import { api } from './api.js';
import { h, modal, toast, errorToast } from './ui.js';

const OPS = [['>=', '≥', 'Seviyeye ulaşınca ya da üstüne çıkınca'], ['<=', '≤', 'Seviyeye inince ya da altına düşünce'],
  ['x', 'kesişir', 'Seviyeyi hangi yönde olursa olsun geçince']];

/** "Alarm kur" for a cell: a level the cell's value is watched against (typed as the cell shows it: 35,50 on a
 * cell in per cent). */
export function openAlarmDialog(ctx, { book, ref, label, text }) {
  const m = modal({ title: 'Alarm kur · ' + ref, width: 520 });
  let op = '>=';
  const name = h('input', { class: 'inp', id: 'alarm-label', value: label || ref, maxlength: '60' });
  const seg = h('div', { class: 'seg', id: 'alarm-op' });
  for (const [v, t, tip] of OPS) {
    const b = h('button', { type: 'button', title: tip }, t);
    b.dataset.v = v;
    b.classList.toggle('on', v === op);
    b.addEventListener('click', () => { op = v; for (const x of seg.children) x.classList.toggle('on', x === b); });
    seg.appendChild(b);
  }
  const level = h('input', { class: 'inp', id: 'alarm-level', value: (text || '').replace('%', '').trim(), inputmode: 'decimal' });
  const note = h('input', { class: 'inp', id: 'alarm-note', placeholder: 'not (isteğe bağlı): örn. "1Y\'de alıcı ol"', maxlength: '200' });
  m.body.appendChild(h('p', { class: 'muted' }, 'Şimdi: ' + (text || '–') + '. Seviyeyi hücrenin gösterdiği gibi yazın (faizde 35,50 = %35,50). '
    + 'Alarm bir kez çalar; Alarmlar listesinden yeniden kurulur.'));
  m.body.appendChild(h('div', { class: 'field' }, h('label', null, 'Ad'), name));
  m.body.appendChild(h('div', { class: 'field' }, h('label', null, 'Koşul'), seg));
  m.body.appendChild(h('div', { class: 'field' }, h('label', null, 'Seviye'), level));
  m.body.appendChild(h('div', { class: 'field' }, h('label', null, 'Not'), note));
  const save = h('button', { class: 'btn primary', type: 'button', id: 'alarm-save' }, 'Alarmı kur');
  save.addEventListener('click', async () => {
    save.disabled = true;
    try {
      const res = await api.post('/api/alarms/add', { book, ref, op, level: level.value, label: name.value, note: note.value });
      askPermission();
      toast(res.already ? 'Alarm kuruldu – koşul şu an zaten sağlanıyor: hemen çalar' : 'Alarm kuruldu: ' + name.value, res.already ? 'warn' : 'ok', 5000);
      m.close();
      if (ctx && ctx.refreshNow) ctx.refreshNow();
    } catch (err) { errorToast(err); save.disabled = false; }
  });
  m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Vazgeç'));
  m.foot.appendChild(save);
  level.focus();
  level.select();
}

/** "İzlemeye ekle" for a cell. */
export async function addToWatch(ctx, { book, ref, label }) {
  try {
    const res = await api.post('/api/watch/add', { book, ref, label });
    toast(res.added ? 'İzleme listesine eklendi: ' + (label || ref) : 'Zaten izleme listesinde', 'ok');
    if (ctx && ctx.refreshNow) ctx.refreshNow();
  } catch (err) { errorToast(err); }
}

/** The browser's notifications: asked for once, when the first alarm is set (a click is needed to ask). */
export function askPermission() {
  try {
    if (window.Notification && Notification.permission === 'default') Notification.requestPermission();
  } catch (e) { /* not available */ }
}

let audio = null;
function tone() {
  try {
    audio = audio || new (window.AudioContext || window.webkitAudioContext)();
    const t0 = audio.currentTime;
    for (const [at, f] of [[0, 880], [0.18, 1175]]) {
      const o = audio.createOscillator();
      const g = audio.createGain();
      o.frequency.value = f;
      g.gain.setValueAtTime(0.0001, t0 + at);
      g.gain.exponentialRampToValueAtTime(0.18, t0 + at + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + at + 0.16);
      o.connect(g).connect(audio.destination);
      o.start(t0 + at);
      o.stop(t0 + at + 0.17);
    }
  } catch (e) { /* no sound */ }
}

const seen = { last: null };

/** What fired since the last look: told once each (the first look of a session only learns where it stands). */
export async function checkAlarms() {
  let res;
  try { res = await api.get('/api/alarms/fired?since=' + (seen.last == null ? 0 : seen.last)); } catch (e) { return []; }
  if (seen.last == null) { seen.last = res.last; return []; }
  const op = Object.fromEntries(OPS.map(([v, t]) => [v, t]));
  for (const e of res.fired) {
    const text = '🔔 ' + e.label + ': ' + (e.value_text || e.value) + '  (' + (op[e.op] || e.op) + ' ' + (e.level_text || e.level) + ') · ' + e.time
      + (e.note ? ' · ' + e.note : '');
    const el = toast(text, 'alarm', 15000);
    el.addEventListener('click', () => el.remove());
    try {
      if (window.Notification && Notification.permission === 'granted') new Notification('TTO alarm · ' + e.label, { body: text.slice(2) });
    } catch (x) { /* no notification */ }
  }
  if (res.fired.length) tone();
  seen.last = Math.max(seen.last, res.last || 0);
  return res.fired;
}
