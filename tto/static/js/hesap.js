// "Hesap" (tto/progress.py): where the long calculations are - the quant fit, the ML family's models, the backtest, the
// history sync.  In the top bar only while one runs, short ("Hesap Quant 14/26 +2 · ~3 dk": the first job, how many more,
// the time left - the desk, 28.11.2026); its tooltip and a click list each job with its step, done / total, since when
// and the time left.  It follows the status the shell
// polls (every 15 s, and on a reconnect) and, while something runs, asks /api/progress every few seconds - nothing at
// all when idle.
import { api } from './api.js';
import { h, clear, modal } from './ui.js';

const EVERY = 4000;              // ms between two asks while something runs
const OPEN_EVERY = 2000;         // ... while the details are open
let view = null;                 // the last view while something runs (null: idle)
let timer = null;
let dlg = null;                  // the details window, while open: {fill}

const el = () => document.getElementById('hesap-ind');

/** A progress view of the server (the status' ``progress``, or /api/progress): the indicator follows it. */
export function showProgress(v) {
  view = v && v.busy ? v : null;
  const b = el();
  if (b) {
    b.classList.toggle('hidden', !view);
    clear(b);
    if (view) {
      // short (the desk, 28.11.2026 - B9: the page's title was cut while "Hesap" said every job): the first job's count,
      // how many more, the time left - every job in the tooltip and a click away
      b.append(h('span', { class: 'hs-dot' }), h('span', { class: 'hs-lbl' }, 'Hesap'), h('span', { class: 'hs-txt', id: 'hesap-text' }, shortText(view)));
      b.title = view.jobs.map(line).join('\n') + '\n\nAyrıntı için tıklayın';
    } else {
      b.title = '';
    }
  }
  if (dlg) dlg.fill(view);
  clearTimeout(timer);
  timer = view ? setTimeout(poll, dlg ? OPEN_EVERY : EVERY) : null;
}

async function poll() {
  timer = null;
  if (document.hidden && !dlg) return;           // (out of view: the status poll brings it back)
  try {
    showProgress(await api.get('/api/progress'));
  } catch (err) {
    if (view) timer = setTimeout(poll, EVERY);   // (the server or the network gone a moment: ask again)
  }
}

/** The chip's text: the first job's count, "+N" the others, the time left ("Quant 14/26 +2 · ~3 dk"). */
export function shortText(v) {
  const jobs = (v && v.jobs) || [];
  const first = jobs.length ? (jobs[0].short || jobs[0].name || jobs[0].title || '') : (v && v.text) || '';
  return first + (jobs.length > 1 ? ' +' + (jobs.length - 1) : '') + (v && v.eta ? ' · ' + v.eta : '');
}

/** One job in a line: "Quant tam hesap: 14 / 26 adım · şu an Trend · 10:42:05'ten beri · ~3 dk". */
function line(j) {
  return j.title + ': ' + count(j) + (j.step ? ' · şu an ' + j.step : '') + ' · ' + j.since + '\'ten beri' + (j.eta ? ' · ' + j.eta : '');
}

function count(j) {
  return (j.total !== null && j.total !== undefined ? j.done + ' / ' + j.total : String(j.done)) + ' ' + (j.unit || '');
}

function took(s) {
  if (s === null || s === undefined) return '';
  if (s < 60) return s + ' sn';
  const m = Math.floor(s / 60);
  return m < 60 ? m + ' dk ' + (s % 60) + ' sn' : Math.floor(m / 60) + ' sa ' + (m % 60) + ' dk';
}

/** The details: every job under way, refreshed every two seconds while the window is open. */
export function openProgress() {
  if (dlg) return;
  const m = modal({ title: 'Hesap · arka planda çalışan hesaplar', width: 820, onClose: () => { dlg = null; showProgress(view); } });
  const list = h('div', { id: 'hesap-list' });
  m.body.append(list, h('p', { class: 'muted', style: { margin: '10px 0 0' } },
    'Hesaplar kendi iş parçacıklarında çalışır; sayfalar eldeki son sonuçla açılır. Kalan süre tahminidir (~): bu çalışmanın hızı ve '
    + 'aynı türden son çalışmanın süreleri (güncellemeden sonraki ilk tam hesap, önbellekler boş olduğu için sonrakilerden uzundur). '
    + 'Ölçüsü olmayan iş için tahmin yazılmaz.'));
  m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Kapat'));
  dlg = { fill: (v) => fill(list, v) };
  dlg.fill(view);
  clearTimeout(timer);
  poll();
}

function fill(list, v) {
  clear(list);
  const jobs = (v && v.jobs) || [];
  if (!jobs.length) {
    list.appendChild(h('div', { class: 'empty' }, 'Şu an çalışan hesap yok.'));
    return;
  }
  const table = h('table', { class: 'plain hesap-jobs' });
  table.appendChild(h('thead', null, h('tr', null, h('th', { class: 'l' }, 'Hesap'), h('th', { class: 'l' }, 'Şu an'), h('th', null, 'Yapılan'),
    h('th', null, 'Başladı'), h('th', null, 'Geçen'), h('th', null, 'Kalan (tahmini)'))));
  const body = h('tbody');
  for (const j of jobs) {
    body.appendChild(h('tr', { 'data-job': j.id }, h('td', { class: 'l' }, h('b', null, j.title)), h('td', { class: 'l' }, j.step || ''),
      h('td', null, count(j)), h('td', null, j.since), h('td', null, took(j.elapsed_s)), h('td', null, j.eta || '—')));
  }
  table.appendChild(body);
  list.appendChild(table);
}
