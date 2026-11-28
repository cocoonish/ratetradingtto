// Kotasyon defteri (tto/quotelog.py; the desk, 28.11.2026: "Fiyatladiktan sonra bunu done diye gunluk islemlere
// alabilmeliyim veya done olmadiysa da hit ratiosunu takip edebilmeliyim"): the quotes given to clients - every table's
// "Kotasyon kopyala" and Fiyatlama's forward card log one - with their status (Açık / Done / Done değil), and the hit
// ratio, done / (done + done değil), by client and by product.  The whole desk's log: everyone sees every quote and who
// gave it.
//
// ``mountQuoteLog(container, ctx, opts)`` draws it into ``container`` and returns {el, refresh, destroy}: Günlük
// İşlemler's folded "Verilen kotalar" and Fiyatlama's "Kotasyon defteri" mount it.  ``opts``: {id (the prefix of its DOM
// ids, default 'ql'), days (the period first shown: 1 today, 7, 30), onChange (called after a status changed)}.
// "Bu fiyattan işlem gir" on an FX forward's quote opens Günlük İşlemler's form at the quoted level (``ctx.openTrade``)
// and marks the quote done.
import { api } from './api.js';
import { h, clear, errorToast, toast, promptDialog } from './ui.js';
import { num, isoToTr, timeOf } from './format.js';

const PERIODS = [['1', 'Bugün'], ['7', 'Son 7 gün'], ['30', 'Son 30 gün']];
const STATUS = { open: 'Açık', done: 'Done', not_done: 'Done değil' };
const KEY = 'tto.quotelog.days';

function isoDay(d) {
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
}

function pref(fallback) {
  try { const v = localStorage.getItem(KEY); return PERIODS.some((p) => p[0] === v) ? v : fallback; } catch (e) { return fallback; }
}

function ratioText(r) {
  return typeof r === 'number' && isFinite(r) ? '%' + num(r * 100, 0) : '–';
}

/** A level as the log keeps it: its text as the quote showed it, else the numbers. */
function levelText(lv) {
  if (!lv) return '';
  if (lv.text) return lv.text;
  const d = lv.unit === 'kur' ? 4 : 2;
  if (typeof lv.bid === 'number' || typeof lv.ask === 'number') return num(lv.bid, d) + ' / ' + num(lv.ask, d);
  return typeof lv.mid === 'number' ? num(lv.mid, d) : '';
}

/** The side a quote's record says the desk dealt: 'B' (AL / alış), 'S' (SAT / satış) or null. */
export function sideOfQuote(q) {
  const side = String((q && q.side) || '').trim().toUpperCase();
  if (['AL', 'B', 'BUY', 'ALIŞ', 'ALIS'].includes(side) || /ALIŞ$/.test(side)) return 'B';
  if (['SAT', 'S', 'SELL', 'SATIŞ', 'SATIS'].includes(side) || /SATIŞ$/.test(side)) return 'S';
  return null;
}

/** The trade an FX forward's quote becomes in Günlük İşlemler's form - the quoted level of the desk's side (``dir``, else
 * the record's): it buys the currency at the bid ('B'), sells at the ask ('S'); an outright as the forward rate, points as
 * swap points - or null when the quote does not say enough (no value date, no level of that side, a TRY rate only). */
export function tradeOfQuote(q, dir) {
  if (!q || q.product !== 'FX forward' || !q.value_date || !q.levels) return null;
  const side = dir || sideOfQuote(q);
  const lv = side === 'S' ? q.levels.ask : side === 'B' ? q.levels.bid : null;
  const kind = q.levels.kind || 'outright';
  if (typeof lv !== 'number' || (kind !== 'outright' && kind !== 'points')) return null;
  const spec = { kind: 'fwd', pair: q.pair || 'USDTRY', dir: side, date: isoToTr(q.value_date), basis: kind === 'points' ? 'SP' : 'FWD',
    value: kind === 'points' ? num(lv, 0, false) : num(lv, 4, false),
    note: 'Kota #' + q.id + (q.client ? ' · ' + q.client : '') + ' · ' + (q.instrument || ''), quote_log: q.id,
    said: 'İşlem kotadan dolduruldu (kota #' + q.id + '): tutarı kontrol edip kaydedin' };
  if (typeof q.size === 'number' && q.size > 0) spec.amount = num(q.size, 0, false);
  if (typeof q.spot === 'number' && kind === 'outright') spec.spot = num(q.spot, 4, false);
  return spec;
}

/** Set a quote's status (and what goes with it): the server's answer, or null after a toast. */
export async function setQuoteStatus(id, fields) {
  try {
    return (await api.post('/api/quote-log/' + id, fields)).quote;
  } catch (err) {
    errorToast(err);
    return null;
  }
}

export function mountQuoteLog(container, ctx, opts = {}) {
  const p = opts.id || 'ql';
  const st = { days: pref(String(opts.days || 1)), data: null, seq: 0, gone: false };
  const periodSeg = h('div', { class: 'seg', id: p + '-period' });
  const summary = h('span', { class: 'muted', id: p + '-summary' });
  const refreshBtn = h('button', { class: 'btn sm', type: 'button', id: p + '-refresh', title: 'Yenile' }, '↻');
  const hitBox = h('div', { class: 'ql-hit', id: p + '-hit' });
  const listBox = h('div', { class: 'ql-list', id: p + '-list' });
  const root = h('div', { class: 'quotelog', id: p },
    h('div', { class: 'ql-tools' }, periodSeg, summary, h('span', { class: 'grow' }), refreshBtn),
    hitBox, listBox);
  refreshBtn.addEventListener('click', () => load());
  for (const [v, label] of PERIODS) {
    const b = h('button', { type: 'button' }, label);
    b.dataset.v = v;
    b.addEventListener('click', () => {
      st.days = v;
      try { localStorage.setItem(KEY, v); } catch (e) { /* ignore */ }
      load();
    });
    periodSeg.appendChild(b);
  }

  const hitTable = (title, rows, id) => {
    const t = h('table', { class: 'plain ql-hit-table', id },
      h('tr', null, h('th', { class: 'l' }, title), h('th', null, 'Kota'), h('th', null, 'Done'), h('th', null, 'Done değil'),
        h('th', null, 'Açık'), h('th', { title: 'İsabet = done / (done + done değil); açık kotalar sayılmaz' }, 'İsabet')));
    for (const g of rows) {
      const tr = h('tr', null, h('td', { class: 'l' }, g.key), h('td', null, String(g.quotes)), h('td', { class: 'buy' }, String(g.done)),
        h('td', { class: 'sell' }, String(g.not_done)), h('td', null, String(g.open)), h('td', null, h('b', null, ratioText(g.ratio))));
      tr.dataset.key = g.key;
      t.appendChild(tr);
    }
    return t;
  };

  const change = async (q, fields, said) => {
    const got = await setQuoteStatus(q.id, fields);
    if (!got) return;
    if (said) toast(said, 'ok');
    await load();
    if (opts.onChange) opts.onChange(got);
  };

  const draw = () => {
    const d = st.data;
    for (const b of periodSeg.children) b.classList.toggle('on', b.dataset.v === st.days);
    clear(hitBox);
    clear(listBox);
    if (!d) {
      listBox.appendChild(h('div', { class: 'muted pad', id: p + '-wait' }, 'hesaplanıyor…'));
      return;
    }
    const all = d.hit.all;
    summary.textContent = all.quotes ? all.quotes + ' kota · done ' + all.done + ' · done değil ' + all.not_done + ' · açık ' + all.open
      + ' · isabet ' + ratioText(all.ratio) + (all.unbooked ? ' · işlem no\'su olmayan done: ' + all.unbooked : '') : '';
    if (!d.quotes.length) {
      listBox.appendChild(h('div', { class: 'muted pad', id: p + '-empty' }, (st.days === '1' ? 'Bugün' : 'Bu dönemde') + ' verilen kota yok: '
        + 'tabloların "Kotasyon kopyala"sı ve Fiyatlama\'nın forward kartı her kopyalamayı buraya yazar.'));
      return;
    }
    hitBox.appendChild(hitTable('Müşteri', d.hit.by_client, p + '-hit-client'));
    hitBox.appendChild(hitTable('Ürün', d.hit.by_product, p + '-hit-product'));
    const many = d.from !== d.to;
    const t = h('table', { class: 'plain ql-table', id: p + '-table' },
      h('tr', null, h('th', null, many ? 'Gün' : 'Saat'), h('th', { class: 'l' }, 'Kim'), h('th', { class: 'l' }, 'Müşteri'),
        h('th', { class: 'l' }, 'Ürün'), h('th', { class: 'l' }, 'Enstrüman'), h('th', { class: 'l' }, 'Yön'), h('th', null, 'Seviye'),
        h('th', { class: 'l' }, 'Kaynak'), h('th', { class: 'l' }, 'Durum'), h('th', { class: 'l' }, '')));
    for (const q of d.quotes.slice().reverse()) {
      const tr = h('tr', { class: 'ql-' + q.status });
      tr.dataset.id = String(q.id);
      tr.dataset.status = q.status;
      const when = (many ? isoToTr(q.date) + ' ' : '') + timeOf(q.created_at);
      const client = h('td', { class: 'l ql-client', title: 'Müşteriyi yazmak / değiştirmek için tıklayın' }, q.client || '–');
      client.addEventListener('click', async () => {
        const v = await promptDialog('Müşteri', 'Kota #' + q.id + ' kime verildi?', q.client || '');
        if (v === null || v === undefined) return;
        change(q, { client: v }, null);
      });
      const acts = h('td', { class: 'l ql-acts' });
      const btn = (label, title, fn, cls) => {
        const b = h('button', { class: 'btn sm' + (cls ? ' ' + cls : ''), type: 'button', title }, label);
        b.addEventListener('click', fn);
        acts.appendChild(b);
        return b;
      };
      if (q.status !== 'done') btn('Done', 'Müşteri işlem yaptı', () => change(q, { status: 'done' }, 'Kota #' + q.id + ': done')).dataset.act = 'done';
      if (q.status !== 'not_done') btn('Done değil', 'Müşteri işlem yapmadı', () => change(q, { status: 'not_done' }, 'Kota #' + q.id + ': done değil')).dataset.act = 'not_done';
      if (q.status !== 'open') btn('Açık', 'Henüz karar yok', () => change(q, { status: 'open' }, null)).dataset.act = 'open';
      // "Bu fiyattan işlem gir": the quoted level of the desk's side (a quote without a side: the side picked here)
      const book = async (spec) => {
        if (q.status !== 'done') await setQuoteStatus(q.id, { status: 'done' });
        ctx.openTrade(spec);
        load();
      };
      const sides = sideOfQuote(q) ? [[sideOfQuote(q), '']] : [['B', 'Alış (bid) '], ['S', 'Satış (ask) ']];
      for (const [dir, word] of sides) {
        const spec = tradeOfQuote(q, dir);
        if (!spec || !ctx || !ctx.openTrade) continue;
        btn(word + 'Bu fiyattan işlem gir', 'Günlük İşlemler\'in FX forward formu kotlanan seviyeden dolu açılır (kota done olur)',
          () => book(spec), 'primary').dataset.act = 'trade-' + dir;
      }
      const who = ctx && ctx.displayName ? ctx.displayName(q.created_by) : q.created_by;
      tr.append(h('td', { class: 'muted' }, when), h('td', { class: 'l' }, who || ''), client, h('td', { class: 'l' }, q.product || ''),
        h('td', { class: 'l', title: q.text || '' }, q.instrument || ''), h('td', { class: 'l' }, q.side || ''),
        h('td', { class: 'mono' }, levelText(q.levels)), h('td', { class: 'l muted' }, q.source || ''),
        h('td', { class: 'l' }, h('span', { class: 'ql-st ' + q.status }, d.statuses[q.status] || STATUS[q.status] || q.status)
          , q.trade_id ? h('span', { class: 'muted' }, ' · işlem #' + q.trade_id) : null), acts);
      t.appendChild(tr);
    }
    listBox.appendChild(t);
  };

  const load = async () => {
    const seq = ++st.seq;
    const to = new Date();
    const from = new Date(to.getTime() - (Number(st.days) - 1) * 86400000);
    try {
      const d = await api.get('/api/quote-log', { from: isoDay(from), to: isoDay(to) });
      if (seq !== st.seq || st.gone) return;
      st.data = d;
    } catch (err) {
      if (seq !== st.seq || st.gone) return;
      clear(listBox).appendChild(h('div', { class: 'errtxt pad' }, err.message));
      return;
    }
    draw();
  };

  container.appendChild(root);
  draw();
  load();
  return { el: root, refresh: load, destroy: () => { st.gone = true; root.remove(); } };
}
