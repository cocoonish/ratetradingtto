// Kotasyon kopyala: a pricing table's prices as a quote for a client, on the clipboard with one click - in Turkish or
// English (the choice is remembered in this browser; the numbers follow it: 34,25 / 34.25).  The server writes the text
// (tto/quotes.py) from the cells the table's page definition names ("client_quote", tto/views/__init__.py), as this
// user's calculation has them; it goes on the clipboard through the RET dialog's helper (copyText).
//
// A table of several rows copies all of its priced rows (a line each); one row's quote is a right click away
// ("Bu satırın kotasyonu").  A table of quotes side by side (USDTRY | EURTRY) copies both, or one from the ▾ menu.
import { api } from './api.js';
import { h, menu, modal, copyText, errorToast } from './ui.js';

const KEY = 'tto.kotasyon.lang';

/** The language quotes are written in: 'tr' (the default) or 'en'. */
export function quoteLang() {
  try { return localStorage.getItem(KEY) === 'en' ? 'en' : 'tr'; } catch (e) { return 'tr'; }
}

function setQuoteLang(lang) {
  try { localStorage.setItem(KEY, lang === 'en' ? 'en' : 'tr'); } catch (e) { /* ignore */ }
}

/** The rows of a table of quotes ("5:14") as [first, last] - null for a table that is one quote. */
export function quoteRows(cq) {
  const m = /^\s*(\d+)\s*:\s*(\d+)\s*$/.exec((cq && cq.rows) || '');
  return m ? [Number(m[1]), Number(m[2])] : null;
}

/** The quote's text when the clipboard would not take it (the click too long ago on a slow day): copied by hand. */
function showText(text) {
  const m = modal({ title: 'Kotasyon', width: 640 });
  m.box.id = 'kotasyon-dialog';
  const area = h('textarea', { class: 'inp quote-text', id: 'kotasyon-text', rows: '10', readonly: 'readonly', spellcheck: 'false' });
  area.value = text;
  m.body.appendChild(area);
  const copy = h('button', { class: 'btn primary', type: 'button' }, 'Kopyala');
  copy.addEventListener('click', () => { area.select(); copyText(text, 'Kotasyon kopyalandı').then((ok) => { if (ok) m.close(); }); });
  m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Kapat'));
  m.foot.appendChild(copy);
  area.focus();
  area.select();
}

/** Ask the server for the quote (``where``: {row} one row, {part} one of the quotes side by side) and copy it. */
export async function copyClientQuote(viewId, panelId, where = {}) {
  const language = quoteLang();
  let res;
  try {
    res = await api.get('/api/quote', Object.assign({ view: viewId, panel: panelId, language }, where));
  } catch (err) {
    errorToast(err);
    return null;
  }
  const ok = await copyText(res.text, language === 'en' ? 'Kotasyon kopyalandı (English)' : 'Kotasyon kopyalandı (Türkçe)');
  if (!ok) showText(res.text);
  return res.text;
}

/** The header's split button: "Kotasyon kopyala" copies; ▾ picks the language (and copies in it) or one of the parts. */
export function quoteButton(viewId, panel) {
  const cq = panel.client_quote || {};
  const main = h('button', { class: 'btn sm', type: 'button',
    title: 'Müşteriye gönderilecek kotasyonu panoya kopyala (parite, valör ve vade, gün, spot, puan, outright, faizler'
      + (quoteRows(cq) ? '; tek satır için satıra sağ tık' : '') + ')' }, 'Kotasyon kopyala');
  main.dataset.action = 'kotasyon';
  main.addEventListener('click', () => copyClientQuote(viewId, panel.id));
  const more = h('button', { class: 'btn sm', type: 'button', title: 'Kotasyonun dili (Türkçe / English)'
    + ((cq.parts || []).length ? ' ve tek kotasyon' : '') }, '▾');
  more.dataset.action = 'kotasyon-menu';
  more.addEventListener('click', () => {
    const r = more.getBoundingClientRect();
    const lang = quoteLang();
    const pick = (l) => () => { setQuoteLang(l); copyClientQuote(viewId, panel.id); };
    const parts = (cq.parts || []).map((name, k) => ({ label: 'Yalnız ' + name, action: () => copyClientQuote(viewId, panel.id, { part: k }) }));
    menu(r.left, r.bottom + 2, [
      { header: 'Kotasyon dili (seçince kopyalar)' },
      { label: (lang === 'tr' ? '✓ ' : '   ') + 'Türkçe  (34,25 · 04.12.2026)', action: pick('tr') },
      { label: (lang === 'en' ? '✓ ' : '   ') + 'English  (34.25 · 04 Dec 2026)', action: pick('en') },
      parts.length ? { sep: true } : null,
      ...parts,
      quoteRows(cq) ? { sep: true } : null,
      quoteRows(cq) ? { header: 'Tek satır: satıra sağ tık → Bu satırın kotasyonu' } : null,
    ]);
  });
  return h('span', { class: 'splitbtn' }, main, more);
}

/** The right-click menu's line for a row of a table of quotes ([] for a row that is not one). */
export function quoteRowItems(viewId, panel, grid, i) {
  const span = quoteRows(panel.client_quote);
  const r = grid && grid.data && grid.data.r ? grid.data.r[i] : null;
  if (!span || typeof r !== 'number' || r < span[0] || r > span[1]) return [];
  return [{ label: 'Bu satırın kotasyonu' + (quoteLang() === 'en' ? ' (English)' : ''),
    action: () => copyClientQuote(viewId, panel.id, { row: r }) }];
}
