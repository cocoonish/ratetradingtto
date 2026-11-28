// Kota mesajı: rows of a table (tenors, curves, bonds) as a message for a broker or a client - the bid / ask of one set of
// columns (points, outright, rate, price …), lined up for a chat window, copied with one click.
//
// A panel opts in with "quote" in its page definition:
//   {"prefix": "USDTRY", "label": "A", "alt": "B", "alt_when": "serbest", "first": 5, "last": 14, "date": "B45",
//    "sets": [{"id": "pts", "name": "Puan", "bid": "H", "ask": "I"},
//             {"id": "mid", "name": "Par", "mid": "B", "scale": 100, "digits": 2}]}
// A set with "mid" quotes mid ± half a width typed in bp (or the mid alone when no width is given).
import { h, clear, modal, copyText } from './ui.js';
import { num, parseNumber } from './format.js';
import { logQuoteMessage } from './quotelog.js';

function pref(key, fallback) {
  try { const v = localStorage.getItem(key); return v === null ? fallback : v; } catch (e) { return fallback; }
}
function keep(key, value) {
  try { localStorage.setItem(key, String(value)); } catch (e) { /* ignore */ }
}

function cellOf(data, i, col) {
  const j = (data.c || []).indexOf(col);
  return j < 0 ? null : (data.rows[i] || [])[j] || null;
}

function textOf(data, i, col) {
  const c = cellOf(data, i, col);
  return c ? String(c.t || '').trim() : '';
}

/** The rows a message can carry: [{key, label, i}] (the row's number in the sheet as its key). */
export function quoteRows(data, spec) {
  const out = [];
  if (!data || !data.rows || !data.r) return out;
  for (let i = 0; i < data.r.length; i++) {
    const r = data.r[i];
    if (typeof r !== 'number' || r < spec.first || r > spec.last) continue;
    let label = textOf(data, i, spec.label);
    if (spec.alt && (!label || (spec.alt_when && label.toLowerCase() === spec.alt_when))) label = textOf(data, i, spec.alt);
    if (!label) continue;
    out.push({ key: String(r), label, i });
  }
  return out;
}

/** One row's quote under a set: {bid, ask} as text ('' when the table has none). */
export function quoteOf(data, row, set, width) {
  if (set.mid) {
    const c = cellOf(data, row.i, set.mid);
    const v = c && typeof c.v === 'number' ? c.v * (set.scale || 1) : null;
    if (v === null) return { bid: '', ask: '' };
    const digits = set.digits === undefined ? 2 : set.digits;
    const w = typeof width === 'number' && width > 0 ? width / 100 : null;       // bp -> per cent
    if (w === null) return { bid: num(v, digits, false), ask: '' };
    return { bid: num(v - w / 2, digits, false), ask: num(v + w / 2, digits, false) };
  }
  return { bid: textOf(data, row.i, set.bid), ask: set.ask ? textOf(data, row.i, set.ask) : '' };
}

/** The message: a heading, then one line per row - "1M    15.115 / 16.357". */
export function quoteText(data, spec, set, keys, width, date) {
  const rows = quoteRows(data, spec).filter((r) => keys.includes(r.key));
  const lines = [];
  const w = Math.max(2, ...rows.map((r) => r.label.length));
  for (const r of rows) {
    const q = quoteOf(data, r, set, width);
    if (!q.bid && !q.ask) continue;
    lines.push(r.label.padEnd(w + 2) + (q.ask ? q.bid + ' / ' + q.ask : q.bid));
  }
  const head = [spec.prefix, set.name.toLocaleLowerCase('tr')].concat(date ? [date] : []).filter(Boolean).join(' · ');
  return [head].concat(lines).join('\n');
}

/** The dialog: pick the rows and the set, see the message, copy it. */
export function openQuoteMessage(pageId, panel) {
  const spec = panel.quote;
  const data = panel.data;
  const base = 'tto.quote.' + pageId + '.' + panel.id;
  const rows = quoteRows(data, spec);
  let setId = pref(base + '.set', spec.sets[0].id);
  if (!spec.sets.some((s) => s.id === setId)) setId = spec.sets[0].id;
  let picked = pref(base + '.rows', '');
  picked = picked ? picked.split(',').filter((k) => rows.some((r) => r.key === k)) : rows.map((r) => r.key);
  let width = parseNumber(pref(base + '.width', ''), false);
  const date = spec.date ? (() => {
    const i = (data.r || []).indexOf(Number(String(spec.date).replace(/^[A-Z]+/, '')));
    return i >= 0 ? textOf(data, i, String(spec.date).replace(/\d+$/, '')) : '';
  })() : '';

  const m = modal({ title: 'Kota mesajı · ' + (panel.title || '').split('  ·  ')[0], width: 560 });
  m.box.id = 'quote-dialog';
  const sets = h('div', { class: 'seg', id: 'quote-set' });
  const widthBox = h('input', { class: 'inp num', type: 'text', id: 'quote-width', style: { width: '64px' }, placeholder: 'bp',
    value: typeof width === 'number' ? num(width, 1, false) : '' });
  const widthField = h('label', { class: 'field inline' }, 'Genişlik (bp)', widthBox);
  const list = h('div', { class: 'quote-rows', id: 'quote-rows' });
  const text = h('textarea', { class: 'inp quote-text', id: 'quote-text', rows: '8', readonly: 'readonly', spellcheck: 'false' });
  const set = () => spec.sets.find((s) => s.id === setId) || spec.sets[0];

  const render = () => {
    clear(sets);
    for (const s of spec.sets) {
      const b = h('button', { type: 'button', class: s.id === setId ? 'on' : '' }, s.name);
      b.dataset.v = s.id;
      b.addEventListener('click', () => { setId = s.id; keep(base + '.set', setId); render(); });
      sets.appendChild(b);
    }
    widthField.classList.toggle('hidden', !set().mid);
    clear(list);
    for (const r of rows) {
      const q = quoteOf(data, r, set(), width);
      const box = h('input', { type: 'checkbox' });
      box.checked = picked.includes(r.key);
      box.dataset.key = r.key;
      box.addEventListener('change', () => {
        picked = rows.map((x) => x.key).filter((k) => (k === r.key ? box.checked : picked.includes(k)));
        keep(base + '.rows', picked.join(','));
        text.value = quoteText(data, spec, set(), picked, width, date);
      });
      list.appendChild(h('label', { class: 'quote-row' + (q.bid || q.ask ? '' : ' soft') }, box, h('b', null, r.label),
        h('span', { class: 'muted' }, q.ask ? q.bid + ' / ' + q.ask : q.bid || '–')));
    }
    text.value = quoteText(data, spec, set(), picked, width, date);
  };
  widthBox.addEventListener('input', () => {
    width = parseNumber(widthBox.value, false);
    keep(base + '.width', widthBox.value);
    render();
  });
  const all = h('button', { class: 'btn sm', type: 'button' }, 'Tümü');
  all.addEventListener('click', () => { picked = rows.map((r) => r.key); keep(base + '.rows', picked.join(',')); render(); });
  const none = h('button', { class: 'btn sm', type: 'button' }, 'Hiçbiri');
  none.addEventListener('click', () => { picked = []; keep(base + '.rows', ''); render(); });
  m.body.appendChild(h('div', { class: 'quote-tools' }, sets, widthField, h('span', { class: 'grow' }), all, none));
  m.body.appendChild(list);
  m.body.appendChild(text);
  m.body.appendChild(h('div', { class: 'muted' }, 'Sayılar tabloda göründüğü gibidir (sizin değiştirdikleriniz dahil). Seçim bu tablo için hatırlanır.'));
  const copy = h('button', { class: 'btn primary', type: 'button', id: 'quote-copy' }, 'Kopyala');
  copy.addEventListener('click', () => { copyText(text.value, 'Kota mesajı kopyalandı'); logQuoteMessage(pageId, panel, set(), text.value); });
  m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Kapat'));
  m.foot.appendChild(copy);
  render();
  copy.focus();
  return m;
}

/** "İşlem gir": one row of a forward table and a side - Günlük İşlemler opens with the pair, the value date and the
 * swap points of that side filled (``ctx.openTrade``).  The panel's "trade" spec: {"pair", "label", "first", "last",
 * "bid", "ask", and the value date: "date_col" (each row's) or "date" (one cell for the table)}. */
export function openTradeDialog(pageId, panel, ctx) {
  const spec = panel.trade;
  const data = panel.data;
  const rows = quoteRows(data, spec);
  const base = 'tto.trade.' + pageId + '.' + panel.id;
  let pick = pref(base + '.row', rows.length ? rows[0].key : '');
  if (!rows.some((r) => r.key === pick) && rows.length) pick = rows[0].key;
  let dir = pref(base + '.dir', 'B') === 'S' ? 'S' : 'B';
  const ccy = spec.pair.slice(0, 3);
  const fixedDate = spec.date ? (() => {
    const i = (data.r || []).indexOf(Number(String(spec.date).replace(/^[A-Z]+/, '')));
    return i >= 0 ? textOf(data, i, String(spec.date).replace(/\d+$/, '')) : '';
  })() : '';
  const m = modal({ title: 'İşlem gir · ' + spec.pair, width: 520 });
  m.box.id = 'trade-dialog';
  const sides = h('div', { class: 'seg', id: 'trade-dir' });
  const list = h('div', { class: 'quote-rows', id: 'trade-rows' });
  const summary = h('div', { class: 'set-info', id: 'trade-summary' });
  const chosen = () => rows.find((r) => r.key === pick);
  const dateOf = (r) => (spec.date_col ? textOf(data, r.i, spec.date_col) : fixedDate);
  const pointsOf = (r) => textOf(data, r.i, dir === 'B' ? spec.bid : spec.ask);
  const render = () => {
    clear(sides);
    for (const [v, label] of [['B', ccy + ' al · bid puan'], ['S', ccy + ' sat · ask puan']]) {
      const b = h('button', { type: 'button', class: v === dir ? 'on' : '' }, label);
      b.dataset.v = v;
      b.addEventListener('click', () => { dir = v; keep(base + '.dir', dir); render(); });
      sides.appendChild(b);
    }
    clear(list);
    for (const r of rows) {
      const radio = h('input', { type: 'radio', name: 'trade-row' });
      radio.checked = r.key === pick;
      radio.dataset.key = r.key;
      radio.addEventListener('change', () => { pick = r.key; keep(base + '.row', pick); render(); });
      const pts = pointsOf(r);
      list.appendChild(h('label', { class: 'quote-row' + (pts ? '' : ' soft') }, radio, h('b', null, r.label), h('span', { class: 'muted' }, pts || '–')));
    }
    const r = chosen();
    summary.textContent = r ? spec.pair + ' · ' + (dir === 'B' ? ccy + ' alış' : ccy + ' satış') + ' · valör ' + (dateOf(r) || '?') + ' · swap puanı '
      + (pointsOf(r) || '?') : 'Satır yok';
    go.disabled = !(r && pointsOf(r) && dateOf(r));
  };
  const go = h('button', { class: 'btn primary', type: 'button', id: 'trade-open' }, 'Günlük İşlemler\'de aç');
  go.addEventListener('click', () => {
    const r = chosen();
    if (!r) return;
    m.close();
    ctx.openTrade({ kind: 'fwd', pair: spec.pair, dir, date: dateOf(r), basis: 'SP', value: pointsOf(r),
      note: 'Kota: ' + r.label + ' (' + (panel.title || '').split('  ·  ')[0] + ')' });
  });
  m.body.appendChild(h('div', { class: 'quote-tools' }, sides));
  m.body.appendChild(list);
  m.body.appendChild(summary);
  m.body.appendChild(h('div', { class: 'muted' }, 'Günlük İşlemler\'de parite, yön, valör ve swap puanı dolu açılır; tutarı yazıp kaydedin.'));
  m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Kapat'));
  m.foot.appendChild(go);
  render();
  return m;
}
