// A quote's age (the desk, 28.11.2026: proposal C4; tto/marketdata/age.py).  A market cell - a price Bloomberg gives -
// carries ``qa``: when the price it shows last changed (epoch seconds; live only, replay sends none).  Its tooltip says
// "son değişim 10:42 (37 dk)", worked out when the pointer comes onto it; in market hours a price unchanged for the
// desk's ``quote_old`` minutes of today's market fades (``td.qold``).  The rule comes from /api/quotes/age, asked once a
// minute while a page shows market cells.  grid.js calls ``markQuote`` as it draws a cell and ``quoteTip`` for its
// tooltip; the rest is here.
import { api } from './api.js';

const state = { rule: null, timer: null, hover: false };
const LINE = /son değişim [^\n]*/;
const pad = (n) => String(n).padStart(2, '0');

/** "10:42" of an epoch (seconds), the day too when it is not today: "27.11 17:58". */
export function whenText(at, now) {
  const d = new Date(at * 1000);
  const n = new Date((now || Date.now() / 1000) * 1000);
  const day = d.toDateString() === n.toDateString() ? '' : pad(d.getDate()) + '.' + pad(d.getMonth() + 1) + ' ';
  return day + pad(d.getHours()) + ':' + pad(d.getMinutes());
}

/** A span of minutes as the desk reads it: "0 dk", "37 dk", "2 sa 5 dk", "3 gün". */
export function spanText(min) {
  const m = Math.max(0, Math.floor(min));
  if (m < 60) return m + ' dk';
  if (m < 24 * 60) return Math.floor(m / 60) + ' sa' + (m % 60 ? ' ' + (m % 60) + ' dk' : '');
  return Math.floor(m / (24 * 60)) + ' gün';
}

/** The tooltip line of a market cell: "son değişim 10:42 (37 dk)" ('' for a cell that is none). */
export function quoteTip(cell, now) {
  if (!cell || !cell.qa) return '';
  const t = now || Date.now() / 1000;
  return 'son değişim ' + whenText(cell.qa, t) + ' (' + spanText((t - cell.qa) / 60) + ')';
}

/** Whether a price that last changed at ``at`` is old now by the desk's rule (``rule``: /api/quotes/age): in market
 *  hours, unchanged ``rule.minutes`` minutes of today's market - counted from today's opening when it changed before. */
export function isOld(at, rule, now) {
  if (!at || !rule || !rule.market || !(rule.minutes > 0)) return false;
  const t = now || Date.now() / 1000;
  const n = new Date(t * 1000);
  const hm = /^(\d{1,2})[:.](\d{2})$/.exec(String(rule.open || '09:00')) || [0, 9, 0];
  const opening = new Date(n.getFullYear(), n.getMonth(), n.getDate(), +hm[1], +hm[2]).getTime() / 1000;
  return (t - Math.max(at, opening)) / 60 >= rule.minutes;
}

/** Every market cell on the screen: faded when old, its tooltip's age as of now. */
export function refreshQuotes(root) {
  const now = Date.now() / 1000;
  for (const td of (root || document).querySelectorAll('td[data-qa]')) {
    const at = Number(td.dataset.qa);
    td.classList.toggle('qold', isOld(at, state.rule, now));
    if (td.title && LINE.test(td.title)) td.title = td.title.replace(LINE, quoteTip({ qa: at }, now));
  }
}

async function tick() {
  if (!document.querySelector('td[data-qa]')) {          // (no market cell on the screen: nothing to ask for)
    clearInterval(state.timer);
    state.timer = null;
    return;
  }
  try { state.rule = await api.get('/api/quotes/age'); } catch (e) { /* the last rule stands */ }
  refreshQuotes();
}

function start() {
  if (!state.hover) {
    // the age in the tooltip as of the moment the pointer comes onto the cell (the browser shows it a moment later)
    document.addEventListener('mouseover', (e) => {
      const td = e.target && e.target.closest ? e.target.closest('td[data-qa]') : null;
      if (td && td.title && LINE.test(td.title)) td.title = td.title.replace(LINE, quoteTip({ qa: Number(td.dataset.qa) }));
    }, true);
    state.hover = true;
  }
  if (state.timer) return;
  state.timer = setInterval(tick, 60000);
  setTimeout(tick, 0);
}

/** A table cell drawn (grid.js): a market cell keeps its quote's time and fades when old; any other loses both. */
export function markQuote(td, cell) {
  if (cell && cell.qa) {
    td.dataset.qa = String(cell.qa);
    td.classList.toggle('qold', isOld(cell.qa, state.rule));
    start();
  } else if (td.dataset.qa) {
    delete td.dataset.qa;
    td.classList.remove('qold');
  }
}

/** The rule now (for tests and the status window): {minutes, market, open, close, old, of, oldest} or null. */
export function quoteRule() { return state.rule; }
