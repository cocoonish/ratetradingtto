// Günlük İşlemler: trade entry (FX forward / OIS / bond) with live pricing, the shared blotter and the
// cost of the day's position.  Everything saved here is visible to every user at once.
import { api } from '../api.js';
import { h, clear, toast, errorToast, confirmDialog, debounce, copyText } from '../ui.js';
import { Grid, plainData, copyGrid } from '../grid.js';
import { num, pct, raw, serialDate, isoToTr, timeOf, parseNumber, settings } from '../format.js';

const FWD_BASES = [['RET_BID', 'RET bid'], ['RET_MID', 'RET mid'], ['RET_ASK', 'RET ask'], ['TRY', 'TRY faizi'], ['FWD', 'Forward kur']];
const BASIS_LABEL = { RET_BID: 'RET bid', RET_MID: 'RET mid', RET_ASK: 'RET ask', TRY: 'TRY faizi', FWD: 'Forward kur' };
const STRATEGIES = [['outright', 'Outright'], ['spread', 'Spread'], ['fly', 'Fly'], ['fra', 'FRA']];
const SIDES = {
  outright: [['PAY', 'PAY'], ['RECEIVE', 'RECEIVE']],
  fra: [['PAY', 'PAY'], ['RECEIVE', 'RECEIVE']],
  spread: [['STEEPENER', 'STEEPENER'], ['FLATTENER', 'FLATTENER']],
  fly: [['REC GÖVDE', 'REC GÖVDE'], ['PAY GÖVDE', 'PAY GÖVDE']],
};
const ROLE = { outright: 'Outright', short: 'Kısa', long: 'Uzun', wing1: 'Kanat 1', body: 'Gövde', wing2: 'Kanat 2', start: 'Başlangıç', end: 'Bitiş' };

/** "10m", "2,5 mio", "500k", "1.000.000" -> number (null when not understood). */
export function parseAmount(text) {
  const m = /^\s*([+-]?[\d.,\s]+?)\s*(k|bin|m|mn|mio|milyon|b|bn|milyar)?\s*$/i.exec(text || '');
  if (!m) return null;
  const x = parseNumber(m[1]);
  if (x === null) return null;
  const u = (m[2] || '').toLowerCase();
  const mult = !u ? 1 : (u === 'k' || u === 'bin') ? 1e3 : (u === 'b' || u === 'bn' || u === 'milyar') ? 1e9 : 1e6;
  return x * mult;
}

function seg(options, value, onChange, cls) {
  const el = h('div', { class: 'seg' });
  const set = (v) => {
    el.value = v;
    for (const b of el.children) {
      const on = b.dataset.v === v;
      b.classList.toggle('on', on);
      if (cls && cls[b.dataset.v]) b.classList.toggle(cls[b.dataset.v], on);
    }
  };
  for (const [v, label] of options) {
    const b = h('button', { type: 'button' }, label);
    b.dataset.v = v;
    b.addEventListener('click', () => { set(v); onChange(v); });
    el.appendChild(b);
  }
  el.set = set;
  set(value);
  return el;
}

function field(label, control, width) {
  const el = h('div', { class: 'field' }, h('label', null, label), control);
  if (width) el.style.width = width;
  return el;
}

function input(placeholder, cls) {
  return h('input', { type: 'text', placeholder: placeholder || '', class: cls || '', autocomplete: 'off', spellcheck: 'false' });
}

function tile(label, value, big, title) {
  const el = h('div', { class: 'q' + (big ? ' big' : '') }, h('div', { class: 'l' }, label), h('div', { class: 'v' }, value));
  if (title) el.title = title;
  return el;
}

function n(v, digits, cls) {
  return typeof v === 'number' ? { t: num(v, digits), v, k: 'n', cls } : { t: '', k: '' };
}

function p(v, digits) {
  return typeof v === 'number' ? { t: pct(v, digits), v, k: 'n' } : { t: '', k: '' };
}

/** A signed DV01: + gains when TRY rates rise (USD bought forward, fixed paid), − loses (fixed received, bond bought). */
function dv(v, digits) {
  return typeof v === 'number' ? { t: (v > 0 ? '+' : '') + num(v, digits || 0), v, k: 'n', cls: v > 0 ? 'buy' : (v < 0 ? 'sell' : '') } : { t: '', k: '' };
}

function signed(v, digits) {
  return typeof v === 'number' ? (v > 0 ? '+' : '') + num(v, digits || 0) : '—';
}

function isoDay(d) {
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
}

const DV01_HINT = 'TRY faizi +1 bp olursa kâr / zarar. + = faiz artınca kazanır (vadeli USD alışı, PAY); − = faiz artınca kaybeder (vadeli USD satışı, RECEIVE, tahvil alışı).';

export class BlotterPage {
  constructor(host, ctx) {
    this.host = host;
    this.ctx = ctx;
    this.dead = false;
    this.date = null;
    this.to = null;               // set: every day from this.date to this.to (a list to look at)
    this.data = null;
    this.users = {};
    this.market = null;
    this.tab = 'fwd';
    this.grids = {};
    this.sheetGrids = new Map();
    this.fwd = { dir: 'B', basis: 'RET_MID' };
    this.ois = { strategy: 'outright', side: 'PAY', sizeMode: 'dv01' };
    this.quoteFwd = debounce(() => this.doQuoteFwd(), 220);
    this.quoteOis = debounce(() => this.doQuoteOis(), 220);
    this.quoteBond = debounce(() => this.doQuoteBond(), 260);
  }

  query() {
    if (!this.date) return null;
    return this.to && this.to !== this.date ? { date: this.date, to: this.to } : { date: this.date };
  }

  async load() {
    clear(this.host);
    this.host.appendChild(h('div', { class: 'loading' }, 'Yükleniyor…'));
    const [data, users, market] = await Promise.all([
      api.get('/api/blotter', this.query()),
      api.get('/api/users'),
      api.get('/api/blotter/ois-market').catch(() => null),
    ]);
    if (this.dead) return;
    for (const u of users.users) this.users[u.name] = u.display;
    this.market = market;
    this.data = data;
    this.date = data.date;
    this.to = data.ranged ? data.to : null;
    this.build();
    this.fill();
  }

  async refresh() {
    const data = await api.get('/api/blotter', this.query());
    if (this.dead) return;
    const users = Object.keys(this.users);
    if (data.trades.some((t) => t.created_by && !users.includes(t.created_by))) {
      const u = await api.get('/api/users');
      for (const x of u.users) this.users[x.name] = x.display;
    }
    this.data = data;
    this.fill();
    if (this.data.is_today) {
      if (this.tab === 'fwd') this.quoteFwd(); else if (this.tab === 'ois') this.quoteOis();
    }
  }

  destroy() {
    this.dead = true;
    this.quoteFwd.cancel();
    this.quoteOis.cancel();
    this.quoteBond.cancel();
  }

  /** Show one day (``to`` empty) or every day of a period. */
  show(from, to) {
    if (!from) return;
    if (to && to < from) { const x = from; from = to; to = x; }
    this.date = from;
    this.to = to && to !== from ? to : null;
    this.load().catch(errorToast);
  }

  // ------------------------------------------------------------------ layout
  build() {
    clear(this.host);
    this.grids = {};                 // the tables of the previous day / period went with the page
    this.sheetGrids.clear();
    this.sheetOrder = null;
    this.dateSel = h('select', { class: 'inp' });
    this.dateSel.addEventListener('change', () => { if (this.dateSel.value) this.show(this.dateSel.value, null); });
    this.dayNote = h('span', { class: 'muted' });
    // a period instead of a day: the trades of every day between two dates, in one list
    this.fromInp = h('input', { type: 'date', class: 'inp', id: 'blotter-from', title: 'Başlangıç günü' });
    this.toInp = h('input', { type: 'date', class: 'inp', id: 'blotter-to', title: 'Bitiş günü' });
    const go = h('button', { class: 'btn sm primary', type: 'button', id: 'blotter-range' }, 'Göster');
    go.addEventListener('click', () => {
      if (!this.fromInp.value || !this.toInp.value) { toast('Aralığın iki tarihini de seçin', 'err'); return; }
      this.show(this.fromInp.value, this.toInp.value);
    });
    for (const el of [this.fromInp, this.toInp]) el.addEventListener('keydown', (e) => { if (e.key === 'Enter') go.click(); });
    const preset = (label, title, fn) => {
      const b = h('button', { class: 'btn sm', type: 'button', title }, label);
      b.addEventListener('click', () => { const [a, z] = fn(new Date()); this.show(isoDay(a), isoDay(z)); });
      return b;
    };
    const range = h('span', { class: 'rangebox' }, h('span', { class: 'muted' }, 'Aralık'), this.fromInp, h('span', { class: 'muted' }, '–'), this.toInp, go,
      preset('Bu hafta', 'Pazartesiden bugüne', (t) => { const a = new Date(t); a.setDate(t.getDate() - ((t.getDay() + 6) % 7)); return [a, t]; }),
      preset('Bu ay', 'Ayın birinden bugüne', (t) => [new Date(t.getFullYear(), t.getMonth(), 1), t]),
      preset('Son 30 gün', 'Otuz gün öncesinden bugüne', (t) => { const a = new Date(t); a.setDate(t.getDate() - 30); return [a, t]; }));
    this.todayBtn = h('button', { class: 'btn sm', type: 'button', id: 'blotter-today', title: 'Bugünün işlemlerine dön (işlem girişi yalnızca bugünde açıktır)' }, 'Bugün');
    this.todayBtn.addEventListener('click', () => this.show(this.data.today, null));
    // the workbook's end-of-day macro saved the sheet as values to Blotter_yyyy.mm.dd.xlsx: same file, as a download
    this.exportBtn = h('button', { class: 'btn sm', type: 'button',
      title: 'Seçili günün blotter\'ını Excel dosyası olarak indir (Blotter_yyyy.aa.gg.xlsx): sayfa Excel\'deki düzeniyle, yalnızca değerler; '
        + 'ayrıca işlem listesi ve maliyet özeti. Excel\'deki "gün sonu arşivle" makrosunun karşılığıdır.' }, 'Gün sonu arşivi (.xlsx)');
    this.exportBtn.addEventListener('click', async () => {
      this.exportBtn.disabled = true;
      try {
        const res = await api.download('/api/blotter/export', { date: this.date || undefined, to: this.to || undefined }, 'Blotter.xlsx');
        toast(res.name + ' indirildi', 'ok', 3200);
      } catch (err) { errorToast(err); } finally { this.exportBtn.disabled = false; }
    });
    this.host.appendChild(h('div', { class: 'page-tools' }, h('span', { class: 'muted' }, 'İşlem günü'), this.dateSel, this.todayBtn, range,
      this.exportBtn, h('span', { class: 'grow' }), h('span', { class: 'muted' }, 'Kaydedilen işlemler tüm kullanıcılarda anında görünür')));
    this.host.appendChild(this.dayNote);
    this.dayNote.className = 'banner hidden';

    this.entry = h('div', { class: 'card entry' });
    const tabs = h('div', { class: 'tabs' });
    const panes = { fwd: this.buildFwd(), ois: this.buildOis(), bond: this.buildBond() };
    const tabBtns = {};
    const show = (id) => {
      this.tab = id;
      for (const k of Object.keys(panes)) {
        panes[k].classList.toggle('hidden', k !== id);
        tabBtns[k].classList.toggle('on', k === id);
      }
      if (id === 'fwd') this.quoteFwd(); else if (id === 'ois') this.quoteOis(); else this.quoteBond();
    };
    for (const [id, label] of [['fwd', 'USDTRY Forward'], ['ois', 'OIS'], ['bond', 'Tahvil']]) {
      const b = h('button', { type: 'button' }, label);
      b.addEventListener('click', () => show(id));
      tabBtns[id] = b;
      tabs.appendChild(b);
    }
    this.entry.appendChild(h('header', null, h('h2', null, 'Yeni işlem')));
    this.entry.appendChild(tabs);
    for (const k of Object.keys(panes)) this.entry.appendChild(panes[k]);
    this.readonlyNote = h('div', { class: 'card hidden' }, h('div', { class: 'pad muted' },
      'Geçmiş bir gün ya da bir tarih aralığı görüntüleniyor. Yeni işlem girmek için "Bugün"e dönün.'));
    // what the listed trades add up to in risk
    this.riskBar = h('div', { class: 'riskbar', title: DV01_HINT });

    const lists = h('div', { class: 'lists' });
    this.sections = {};
    for (const [id, title] of [['fwd', 'Forward işlemleri'], ['ois', 'OIS işlemleri'], ['bond', 'Tahvil işlemleri'],
      ['cfwd', 'Maliyet · Forward (valöre göre)'], ['cois', 'Maliyet · OIS (vadeye göre)'], ['cbond', 'Maliyet · Tahvil']]) {
      const body = h('div', { class: 'body' });
      const count = h('span', { class: 'muted' });
      const cp = h('button', { class: 'iconbtn', type: 'button', title: 'Tabloyu kopyala (Excel\'e yapıştırılabilir)' }, 'Kopyala');
      cp.addEventListener('click', () => { if (this.grids[id]) copyGrid(this.grids[id]); });
      const sec = h('section', { class: 'panel wide' }, h('header', null, h('h2', null, title), count, h('div', { class: 'tools' }, cp)), body);
      this.sections[id] = { el: sec, body, count };
      lists.appendChild(sec);
    }
    this.host.appendChild(h('div', { class: 'blotter' }, h('div', { class: 'left' }, this.entry, this.readonlyNote),
      h('div', { class: 'right' }, this.riskBar, lists)));
    this.sheetTitle = h('div', { class: 'section-title' }, 'Excel sayfasının kendi özet tabloları (Günlük İşlemler)');
    this.sheetWrap = h('div', { class: 'panels' });
    // every cell of the workbook's blotter sheet (the per-trade columns, helpers) is one click away
    this.sheetLink = h('button', { class: 'btn sm', type: 'button',
      title: 'Günlük İşlemler sayfasının tamamını (Excel düzeni, formülleriyle) Sayfa gezgininde aç' }, 'Sayfanın tamamı');
    this.sheetLink.addEventListener('click', () => {
      try { sessionStorage.setItem('tto.explorer', JSON.stringify({ book: 'tto', sheet: 'Günlük İşlemler', range: 'A1:AA60' })); } catch (e) { /* ignore */ }
      window.location.hash = '#/explorer';
    });
    this.sheetTitle.appendChild(this.sheetLink);
    this.host.appendChild(this.sheetTitle);
    this.host.appendChild(this.sheetWrap);
    show(this.tab);
  }

  // ------------------------------------------------------------------ forward form
  buildFwd() {
    const f = this.fwd;
    const pane = h('div', { class: 'pad form' });
    f.dirSeg = seg([['B', 'Alış (USD al)'], ['S', 'Satış (USD sat)']], f.dir, (v) => { f.dir = v; this.quoteFwd(); }, { B: 'buy', S: 'sell' });
    f.amount = input('örn. 10m ya da 10.000.000', 'num');
    f.amountEcho = h('div', { class: 'muted echo' });
    f.date = input('gg.aa.yyyy');
    const picker = h('input', { type: 'date', class: 'datepick', tabindex: '-1', 'aria-label': 'Takvim' });
    picker.addEventListener('change', () => {
      if (picker.value) { f.date.value = isoToTr(picker.value); this.quoteFwd(); }
    });
    const cal = h('button', { class: 'btn sm', type: 'button', title: 'Takvimden seç' }, '📅');
    cal.addEventListener('click', () => { try { picker.showPicker(); } catch (e) { picker.focus(); } });
    f.manual = input('', 'num');
    f.manualField = field('TRY faizi (%)', f.manual, '150px');
    f.basisSeg = seg(FWD_BASES, f.basis, (v) => {
      f.basis = v;
      const manual = v === 'TRY' || v === 'FWD';
      f.manualField.classList.toggle('hidden', !manual);
      f.manualField.firstChild.textContent = v === 'TRY' ? 'TRY faizi (%)' : 'Forward kur';
      f.manual.placeholder = v === 'TRY' ? 'örn. 36,50' : 'örn. 52,1000';
      if (manual) f.manual.focus();
      this.quoteFwd();
    });
    f.manualField.classList.add('hidden');
    f.cpt = input('opsiyonel');
    f.note = input('opsiyonel');
    f.quote = h('div', { class: 'quotebox' });
    f.save = h('button', { class: 'btn primary', type: 'button' }, 'İşlemi kaydet');
    f.save.addEventListener('click', () => this.saveFwd());
    for (const el of [f.amount, f.date, f.manual]) {
      el.addEventListener('input', () => this.quoteFwd());
      el.addEventListener('keydown', (e) => { if (e.key === 'Enter') this.saveFwd(); });
    }
    pane.appendChild(h('div', { class: 'row' }, field('Yön', f.dirSeg)));
    pane.appendChild(h('div', { class: 'row' }, field('Tutar (USD)', h('div', null, f.amount, f.amountEcho), '210px'),
      field('Valör', h('div', { class: 'daterow' }, f.date, cal, picker), '190px')));
    pane.appendChild(h('div', { class: 'row' }, field('Fiyatlama', f.basisSeg), f.manualField));
    pane.appendChild(f.quote);
    pane.appendChild(h('div', { class: 'row' }, field('Karşı taraf', f.cpt, '150px'), field('Not', f.note, '240px')));
    pane.appendChild(h('div', { class: 'row actions' }, f.save));
    return pane;
  }

  fwdPayload() {
    const f = this.fwd;
    const amount = parseAmount(f.amount.value);
    f.amountEcho.textContent = f.amount.value.trim() ? (amount === null ? 'tutar anlaşılamadı' : num(amount, 0) + ' USD') : '';
    return { dir: f.dir, amount, value_date: f.date.value.trim(), basis: f.basis,
      manual: (f.basis === 'TRY' || f.basis === 'FWD') ? f.manual.value.trim() : null,
      cpt: f.cpt.value.trim(), note: f.note.value.trim() };
  }

  async doQuoteFwd() {
    const f = this.fwd;
    if (!f.quote || this.dead) return;
    const pl = this.fwdPayload();
    if (!pl.value_date) { clear(f.quote); f.quote.appendChild(h('div', { class: 'muted' }, 'Valör tarihini yazın; forward ve TL tutarı otomatik hesaplanır.')); return; }
    if ((pl.basis === 'TRY' || pl.basis === 'FWD') && !pl.manual) {
      clear(f.quote);
      f.quote.appendChild(h('div', { class: 'muted' }, pl.basis === 'TRY' ? 'TRY faizini yazın.' : 'Forward kuru yazın.'));
      return;
    }
    const ticket = (f.ticket = (f.ticket || 0) + 1);
    try {
      const q = await api.post('/api/blotter/quote/forward', pl);
      if (ticket !== f.ticket || this.dead) return;
      clear(f.quote);
      const tiles = h('div', { class: 'quote' });
      tiles.appendChild(tile('TL tutarı', typeof q.tl === 'number' ? num(q.tl, 2) : '— tutar girin —', true, typeof q.tl === 'number' ? raw(q.tl) : ''));
      tiles.appendChild(tile('Forward kur', num(q.forward, 4), false, raw(q.forward)));
      tiles.appendChild(tile('TRY faizi', pct(q.try_rate, 3), false, raw(q.try_rate)));
      tiles.appendChild(tile('Gün', num(q.days, 0)));
      tiles.appendChild(tile('Spot', num(q.spot, 4), false, raw(q.spot)));
      tiles.appendChild(tile('USD faizi', pct(q.usd_rate, 3)));
      tiles.appendChild(tile('Swap puanı', num(q.points, 0)));
      tiles.appendChild(tile('Valör', serialDate(q.value_date)));
      // risk of the trade being typed (per 1 mn USD until an amount is there): the sheet's "Forward DV01" block
      const d1 = q.dv01 || {};
      const per = typeof q.amount === 'number' ? '' : ' / 1mn USD';
      const t1 = tile('DV01 (TL)' + per, signed(d1.tl, 0), false, DV01_HINT);
      const t2 = tile('DV01 ($)' + per, signed(d1.usd, 0), false, DV01_HINT);
      t1.dataset.k = 'dv01-tl';
      t2.dataset.k = 'dv01-usd';
      tiles.appendChild(t1);
      tiles.appendChild(t2);
      tiles.appendChild(tile('USD faizi DV01 ($)' + per, signed(d1.usd_leg, 0), false, 'USD faizi +1 bp olursa kâr / zarar'));
      f.quote.appendChild(tiles);
      f.quote.appendChild(this.copyLine(() => (pl.dir === 'B' ? 'ALIŞ ' : 'SATIŞ ') + (typeof q.amount === 'number' ? num(q.amount, 0) + ' USD' : 'USD')
        + ' · valör ' + serialDate(q.value_date) + ' (' + num(q.days, 0) + ' gün) · forward ' + num(q.forward, 4) + ' · spot ' + num(q.spot, 4)
        + ' · swap puanı ' + num(q.points, 0) + ' · TRY faizi ' + pct(q.try_rate, 2)
        + (typeof q.tl === 'number' ? ' · TL tutarı ' + num(q.tl, 2) : '')));
      const rows = [];
      for (const k of ['RET', 'OIS', 'ICAP', 'VIOP']) {
        const t = q.table[k] || {};
        rows.push([k, n(t.bid, 4), n(t.mid, 4), n(t.ask, 4)]);
      }
      rows.push(['RET faizi', p(q.ret_bid, 3), p(q.ret_mid, 3), p(q.ret_ask, 3)]);
      const g = new Grid({ data: plainData(['Eğri', 'Bid', 'Mid', 'Ask'], rows), editable: false });
      f.quote.appendChild(h('div', { class: 'reftable' }, g.el));
    } catch (err) {
      if (ticket !== f.ticket) return;
      clear(f.quote);
      f.quote.appendChild(h('div', { class: 'errtxt' }, err.message));
    }
  }

  async saveFwd() {
    const f = this.fwd;
    const pl = this.fwdPayload();
    if (pl.amount === null || !(pl.amount > 0)) { toast('Tutar girin (örn. 10m)', 'err'); f.amount.focus(); return; }
    if (!pl.value_date) { toast('Valör tarihini girin', 'err'); f.date.focus(); return; }
    f.save.disabled = true;
    try {
      const rec = await api.post('/api/blotter/forward', pl);
      toast((rec.dir === 'B' ? 'Alış ' : 'Satış ') + num(rec.amount, 0) + ' USD · ' + serialDate(rec.value_date) + ' · '
        + num(rec.forward, 4) + ' → ' + num(rec.tl, 2) + ' TL kaydedildi', 'ok', 4200);
      f.amount.value = '';
      f.amountEcho.textContent = '';
      f.note.value = '';
      this.ctx.refreshNow();
    } catch (err) { errorToast(err); } finally { f.save.disabled = false; }
  }

  // ------------------------------------------------------------------ OIS form
  tenorSelect(value) {
    const s = h('select', { class: 'inp' });
    for (const t of (this.data && this.data.tenors) || []) s.appendChild(h('option', { value: t }, t));
    if (value) s.value = value;
    s.addEventListener('change', () => this.quoteOis());
    return s;
  }

  monthSelect(from, to, value) {
    const s = h('select', { class: 'inp' });
    for (let m = from; m <= to; m += 3) {
      const label = m === 0 ? 'Spot' : (m % 12 === 0 ? (m / 12) + 'Y' : m + 'M');
      s.appendChild(h('option', { value: String(m) }, label));
    }
    s.value = String(value);
    s.addEventListener('change', () => this.quoteOis());
    return s;
  }

  buildOis() {
    const o = this.ois;
    const pane = h('div', { class: 'pad form' });
    o.sideHost = h('div');
    o.legsHost = h('div', { class: 'row' });
    o.level = input('', 'num');
    o.levelField = field('Oran (%)', o.level, '130px');
    o.marketHint = h('div', { class: 'muted echo' });
    o.size = input('', 'num');
    o.sizeEcho = h('div', { class: 'muted echo' });
    o.sizeSeg = seg([['dv01', 'DV01 ($/bp)'], ['nominal', 'Nominal (TL)']], o.sizeMode, (v) => {
      o.sizeMode = v;
      o.size.value = '';
      o.size.placeholder = v === 'dv01' ? (this.market && this.market.dv01 ? 'varsayılan ' + num(this.market.dv01, 0) : 'örn. 5000') : 'örn. 500m';
      this.quoteOis();
    });
    o.size.placeholder = this.market && this.market.dv01 ? 'varsayılan ' + num(this.market.dv01, 0) : 'örn. 5000';
    o.adv = h('div', { class: 'row adv' });
    o.cpt = input('opsiyonel');
    o.note = input('opsiyonel');
    o.quote = h('div', { class: 'quotebox' });
    o.save = h('button', { class: 'btn primary', type: 'button' }, 'İşlemi kaydet');
    o.save.addEventListener('click', () => this.saveOis());
    for (const el of [o.level, o.size]) {
      el.addEventListener('input', () => this.quoteOis());
      el.addEventListener('keydown', (e) => { if (e.key === 'Enter') this.saveOis(); });
    }
    o.stratSeg = seg(STRATEGIES, o.strategy, (v) => { o.strategy = v; this.layoutOis(); this.quoteOis(); });
    pane.appendChild(h('div', { class: 'row' }, field('Strateji', o.stratSeg), field('Yön', o.sideHost)));
    pane.appendChild(o.legsHost);
    pane.appendChild(h('div', { class: 'row' }, h('div', null, o.levelField, o.marketHint),
      field('Büyüklük', h('div', null, o.sizeSeg, h('div', { style: { marginTop: '6px' } }, o.size), o.sizeEcho))));
    pane.appendChild(o.adv);
    pane.appendChild(o.quote);
    pane.appendChild(h('div', { class: 'row' }, field('Karşı taraf', o.cpt, '150px'), field('Not', o.note, '240px')));
    pane.appendChild(h('div', { class: 'row actions' }, o.save));
    this.layoutOis();
    return pane;
  }

  layoutOis() {
    const o = this.ois;
    const st = o.strategy;
    const sides = SIDES[st];
    if (!sides.some((x) => x[0] === o.side)) o.side = sides[0][0];
    clear(o.sideHost);
    o.sideSeg = seg(sides, o.side, (v) => { o.side = v; this.quoteOis(); },
      { PAY: 'sell', RECEIVE: 'buy', 'PAY GÖVDE': 'sell', 'REC GÖVDE': 'buy' });
    o.sideHost.appendChild(o.sideSeg);
    clear(o.legsHost);
    clear(o.adv);
    const rate = (label) => {
      const el = input('piyasa', 'num');
      el.addEventListener('input', () => this.quoteOis());
      o.adv.appendChild(field(label, el, '150px'));
      return el;
    };
    o.f = {};
    if (st === 'outright') {
      o.f.tenor = this.tenorSelect('1Y');
      o.legsHost.appendChild(field('Vade', o.f.tenor, '110px'));
    } else if (st === 'spread') {
      o.f.short = this.tenorSelect('1Y');
      o.f.long = this.tenorSelect('2Y');
      o.legsHost.appendChild(field('Kısa vade', o.f.short, '110px'));
      o.legsHost.appendChild(field('Uzun vade', o.f.long, '110px'));
      o.f.short_rate = rate('Kısa bacak oranı (%)');
    } else if (st === 'fly') {
      o.f.wing1 = this.tenorSelect('1Y');
      o.f.body = this.tenorSelect('2Y');
      o.f.wing2 = this.tenorSelect('3Y');
      o.legsHost.appendChild(field('Kanat 1', o.f.wing1, '100px'));
      o.legsHost.appendChild(field('Gövde', o.f.body, '100px'));
      o.legsHost.appendChild(field('Kanat 2', o.f.wing2, '100px'));
      o.f.wing1_rate = rate('Kanat 1 oranı (%)');
      o.f.wing2_rate = rate('Kanat 2 oranı (%)');
    } else {
      o.f.start_months = this.monthSelect(0, 117, 3);
      o.f.end_months = this.monthSelect(3, 120, 6);
      o.legsHost.appendChild(field('Başlangıç', o.f.start_months, '110px'));
      o.legsHost.appendChild(field('Bitiş', o.f.end_months, '110px'));
      o.f.start_rate = rate('Başlangıç bacağı oranı (%)');
    }
    const bp = st === 'spread' || st === 'fly';
    o.levelField.firstChild.textContent = bp ? 'Seviye (bp)' : 'Oran (%)';
    o.level.placeholder = bp ? 'örn. -125' : 'örn. 37,25';
    o.level.value = '';
  }

  oisPayload() {
    const o = this.ois;
    const pl = { strategy: o.strategy, side: o.side, level: o.level.value.trim(), cpt: o.cpt.value.trim(), note: o.note.value.trim() };
    for (const k of Object.keys(o.f)) {
      const el = o.f[k];
      const v = el.value.trim();
      if (k === 'start_months' || k === 'end_months') pl[k] = Number(v);
      else if (v) pl[k] = v;
    }
    const size = parseAmount(o.size.value);
    o.sizeEcho.textContent = o.size.value.trim() ? (size === null ? 'anlaşılamadı' : num(size, 0) + (o.sizeMode === 'dv01' ? ' $/bp' : ' TL')) : '';
    if (size !== null && size > 0) pl[o.sizeMode] = size;
    return pl;
  }

  levelText(v, st) {
    if (typeof v !== 'number') return '—';
    return (st === 'spread' || st === 'fly') ? num(v, 2) + ' bp' : pct(v, 4);
  }

  async doQuoteOis() {
    const o = this.ois;
    if (!o.quote || this.dead) return;
    const pl = this.oisPayload();
    const hasLevel = !!pl.level;
    if (!hasLevel) pl.level = '0';
    const ticket = (o.ticket = (o.ticket || 0) + 1);
    try {
      const q = await api.post('/api/blotter/quote/ois', pl);
      if (ticket !== o.ticket || this.dead) return;
      const st = q.strategy;
      const bp = st === 'spread' || st === 'fly';
      clear(o.marketHint);
      if (typeof q.info.market === 'number') {
        const use = h('button', { class: 'btn sm ghost', type: 'button' }, 'kullan');
        use.addEventListener('click', () => {
          o.level.value = bp ? num(q.info.market, 2, false) : num(q.info.market * 100, 4, false);
          this.quoteOis();
        });
        o.marketHint.appendChild(h('span', null, 'Piyasa mid: ' + this.levelText(q.info.market, st) + ' '));
        o.marketHint.appendChild(use);
      }
      clear(o.quote);
      if (!hasLevel) {
        o.quote.appendChild(h('div', { class: 'muted' }, bp ? 'Seviyeyi (bp) yazın; bacaklar ve maliyet otomatik hesaplanır.'
          : 'Oranı yazın; bacaklar ve maliyet otomatik hesaplanır.'));
        return;
      }
      const tiles = h('div', { class: 'quote' });
      const cost = q.info.cost_bp;
      const costTile = tile('Maliyet (mid\'e göre)', typeof cost === 'number' ? num(cost, 2) + ' bp' : '—', true,
        'Pozitif = mid\'den kötü (ödenen), negatif = mid\'den iyi');
      if (typeof cost === 'number') costTile.classList.add(cost > 0 ? 'costpos' : 'costneg');
      tiles.appendChild(costTile);
      tiles.appendChild(tile('Maliyet ($)', typeof q.info.cost_usd === 'number' ? num(q.info.cost_usd, 0) : '—'));
      tiles.appendChild(tile('Maliyet (TL)', typeof q.info.cost_tl === 'number' ? num(q.info.cost_tl, 0) : '—'));
      tiles.appendChild(tile('İşlem seviyesi', this.levelText(q.level, st)));
      tiles.appendChild(tile('Piyasa mid', this.levelText(q.info.market, st)));
      const od = q.dv01 || {};
      const n1 = tile('Net DV01 ($)', signed(od.net, 0), false, DV01_HINT);
      n1.dataset.k = 'dv01-net';
      tiles.appendChild(n1);
      if (q.legs.length > 1) tiles.appendChild(tile('Brüt DV01 ($)', typeof od.gross === 'number' ? num(od.gross, 0) : '—', false, 'Bacakların DV01 toplamı (işaretsiz)'));
      o.quote.appendChild(tiles);
      const rows = q.legs.map((lg) => [ROLE[lg.role] || lg.role,
        { t: lg.dir === 'S' ? 'RECEIVE' : 'PAY', k: 's', cls: lg.dir === 'S' ? 'buy' : 'sell' }, lg.tenor,
        p(lg.rate, 4), n(lg.nominal, 0), n(lg.dv01, 0)]);
      const g = new Grid({ data: plainData(['Bacak', 'Yön', 'Vade', 'Oran', 'Nominal (TL)', 'DV01 ($)'], rows), editable: false });
      o.quote.appendChild(h('div', { class: 'reftable' }, g.el));
      o.quote.appendChild(h('div', { class: 'muted', style: { marginTop: '6px' } }, q.label));
      o.quote.appendChild(this.copyLine(() => q.label + ' · ' + q.legs.map((lg) => (lg.dir === 'S' ? 'REC ' : 'PAY ') + lg.tenor + ' ' + pct(lg.rate, 4)
        + ' ' + num(lg.nominal, 0) + ' TL (DV01 ' + num(lg.dv01, 0) + ' $)').join(' / ')));
    } catch (err) {
      if (ticket !== o.ticket) return;
      clear(o.quote);
      o.quote.appendChild(h('div', { class: 'errtxt' }, err.message));
    }
  }

  async saveOis() {
    const o = this.ois;
    const pl = this.oisPayload();
    if (!pl.level) { toast('Seviye girin', 'err'); o.level.focus(); return; }
    o.save.disabled = true;
    try {
      const q = await api.post('/api/blotter/ois', pl);
      toast(q.label + ' kaydedildi (' + q.legs.length + ' bacak)', 'ok', 4200);
      o.level.value = '';
      o.note.value = '';
      this.ctx.refreshNow();
    } catch (err) { errorToast(err); } finally { o.save.disabled = false; }
  }

  // ------------------------------------------------------------------ bond form
  buildBond() {
    const b = (this.bond = { dir: 'B' });
    const pane = h('div', { class: 'pad form' });
    b.dirSeg = seg([['B', 'Alış'], ['S', 'Satış']], b.dir, (v) => { b.dir = v; }, { B: 'buy', S: 'sell' });
    b.inst = input('örn. TRT130629T14');
    b.amount = input('nominal, örn. 50m', 'num');
    b.amountEcho = h('div', { class: 'muted echo' });
    b.amount.addEventListener('input', () => {
      const a = parseAmount(b.amount.value);
      b.amountEcho.textContent = b.amount.value.trim() ? (a === null ? 'anlaşılamadı' : num(a, 0)) : '';
    });
    b.price = input('temiz fiyat', 'num');
    b.note = input('opsiyonel');
    b.quote = h('div', { class: 'quotebox' });
    b.dirSeg.addEventListener('click', () => this.quoteBond());
    for (const el of [b.inst, b.amount]) el.addEventListener('input', () => this.quoteBond());
    for (const el of [b.inst, b.amount, b.price]) el.addEventListener('keydown', (e) => { if (e.key === 'Enter') this.saveBond(); });
    b.save = h('button', { class: 'btn primary', type: 'button' }, 'İşlemi kaydet');
    b.save.addEventListener('click', () => this.saveBond());
    pane.appendChild(h('div', { class: 'row' }, field('Yön', b.dirSeg), field('Enstrüman', b.inst, '200px')));
    pane.appendChild(h('div', { class: 'row' }, field('Tutar', h('div', null, b.amount, b.amountEcho), '190px'), field('Fiyat', b.price, '130px')));
    pane.appendChild(b.quote);
    pane.appendChild(h('div', { class: 'row' }, field('Not', b.note, '330px')));
    pane.appendChild(h('div', { class: 'row actions' }, b.save));
    return pane;
  }

  /** Name, price in use, duration and DV01 of the bond being typed, when the DİBS RV table lists it. */
  async doQuoteBond() {
    const b = this.bond;
    if (!b || !b.quote || this.dead) return;
    const inst = b.inst.value.trim();
    clear(b.quote);
    if (!inst) { b.quote.appendChild(h('div', { class: 'muted' }, 'Enstrümanı (ISIN) yazın; DİBS RV tablosundaki bir kâğıtsa süre ve DV01 gösterilir.')); return; }
    const ticket = (b.ticket = (b.ticket || 0) + 1);
    try {
      const q = await api.post('/api/blotter/quote/bond', { instrument: inst, dir: b.dir, amount: parseAmount(b.amount.value) });
      if (ticket !== b.ticket || this.dead) return;
      clear(b.quote);
      if (!q.known) {
        b.quote.appendChild(h('div', { class: 'muted' }, 'Bu enstrüman DİBS RV tablosunda yok: işlem kaydedilir, DV01 hesaplanamaz.'));
        return;
      }
      const per = q.amount ? '' : ' / 1mn nominal';
      const tiles = h('div', { class: 'quote' });
      const t1 = tile('DV01 (TL)' + per, signed(q.dv01_tl, 0), true, DV01_HINT);
      t1.dataset.k = 'dv01-tl';
      tiles.appendChild(t1);
      tiles.appendChild(tile('DV01 ($)' + per, signed(q.dv01, 0), false, DV01_HINT));
      tiles.appendChild(tile('Mod. süre', typeof q.info.mod_dur === 'number' ? num(q.info.mod_dur, 3) : '—'));
      tiles.appendChild(tile('Temiz fiyat (tablo)', typeof q.info.clean === 'number' ? num(q.info.clean, 3) : '—', false,
        'DİBS RV tablosunda kullanılan temiz fiyat; fiyat kutusuna siz yazarsınız'));
      tiles.appendChild(tile('Vade', typeof q.info.maturity === 'number' ? serialDate(q.info.maturity) : '—'));
      b.quote.appendChild(tiles);
      b.quote.appendChild(h('div', { class: 'muted', style: { marginTop: '6px' } }, q.info.isin + (q.info.name ? ' · ' + q.info.name : '')));
    } catch (err) {
      if (ticket !== b.ticket) return;
      clear(b.quote);
      b.quote.appendChild(h('div', { class: 'errtxt' }, err.message));
    }
  }

  /** "Kopyala": the quote on screen as one line of text, to send. */
  copyLine(text) {
    const b = h('button', { class: 'btn sm ghost copyq', type: 'button', title: 'Bu fiyatı tek satır metin olarak kopyala (mesaja yapıştırmak için)' }, 'Fiyatı kopyala');
    b.addEventListener('click', () => copyText(text(), 'Fiyat kopyalandı'));
    return h('div', { class: 'copyline' }, b);
  }

  async saveBond() {
    const b = this.bond;
    const amount = parseAmount(b.amount.value);
    if (!b.inst.value.trim()) { toast('Enstrüman girin', 'err'); b.inst.focus(); return; }
    if (amount === null || !(amount > 0)) { toast('Tutar girin', 'err'); b.amount.focus(); return; }
    b.save.disabled = true;
    try {
      await api.post('/api/blotter/bond', { instrument: b.inst.value.trim(), dir: b.dir, amount, price: b.price.value.trim(), note: b.note.value.trim() });
      toast('Tahvil işlemi kaydedildi', 'ok');
      b.amount.value = '';
      b.amountEcho.textContent = '';
      b.note.value = '';
      this.quoteBond();
      this.ctx.refreshNow();
    } catch (err) { errorToast(err); } finally { b.save.disabled = false; }
  }

  // ------------------------------------------------------------------ lists
  who(t) {
    return this.users[t.created_by] || t.created_by || '';
  }

  delCell(t, what) {
    if (!this.data.is_today) return { t: '', k: '' };
    return { t: '', k: '', cls: 'act', act: { label: '✕', title: 'İşlemi sil', fn: () => this.remove(t, what) } };
  }

  async remove(t, what) {
    const ok = await confirmDialog('İşlemi sil', what + ' silinsin mi? Silinen işlem tüm kullanıcılardan kalkar.', 'Sil', true);
    if (!ok) return;
    try {
      await api.del('/api/blotter/trade/' + t.id);
      toast('İşlem silindi', 'ok');
      this.ctx.refreshNow();
    } catch (err) { errorToast(err); }
  }

  setGrid(id, header, rows, countText) {
    const sec = this.sections[id];
    sec.count.textContent = countText || '';
    const data = plainData(header, rows);
    sec.el.classList.toggle('hidden', !rows.length && id.startsWith('c'));
    if (!rows.length) {
      clear(sec.body);
      this.grids[id] = null;
      sec.body.appendChild(h('div', { class: 'empty' }, this.data.is_today ? 'Henüz işlem yok – soldaki formdan girin' : (this.data.ranged ? 'Bu aralıkta kayıt yok' : 'Kayıt yok')));
      return;
    }
    if (this.grids[id]) {
      this.grids[id].replace(data);
    } else {
      clear(sec.body);
      this.grids[id] = new Grid({ data, editable: false });
      sec.body.appendChild(this.grids[id].el);
    }
  }

  fill() {
    const d = this.data;
    // date selector
    clear(this.dateSel);
    const seen = new Set();
    const add = (iso, label) => { if (!seen.has(iso)) { seen.add(iso); this.dateSel.appendChild(h('option', { value: iso }, label)); } };
    if (d.ranged) this.dateSel.appendChild(h('option', { value: '' }, 'Aralık: ' + isoToTr(d.date) + ' – ' + isoToTr(d.to)));
    add(d.today, isoToTr(d.today) + ' (bugün)');
    for (const x of d.dates) add(x.date, isoToTr(x.date) + ' · ' + x.count + ' işlem');
    if (!d.ranged) add(d.date, isoToTr(d.date));
    this.dateSel.value = d.ranged ? '' : d.date;
    this.fromInp.value = d.date;
    this.toInp.value = d.to || d.date;
    this.todayBtn.classList.toggle('hidden', d.is_today);
    this.dayNote.textContent = d.is_today ? '' : (d.ranged
      ? 'Aralık: ' + isoToTr(d.date) + ' – ' + isoToTr(d.to) + ' · ' + (d.days || 0) + ' işlem günü, ' + d.trades.length + ' kayıt – yalnızca görüntüleme. '
        + 'Maliyet ve DV01 bu aralıktaki işlemlerin toplamıdır.'
      : 'Geçmiş gün – yalnızca görüntüleme' + (d.snapshot_at ? ' (özet: ' + d.snapshot_at + ')' : ''));
    this.dayNote.classList.toggle('hidden', d.is_today);
    this.entry.classList.toggle('hidden', !d.is_today);
    this.readonlyNote.classList.toggle('hidden', d.is_today);

    // risk of what is listed
    const r = d.risk || {};
    clear(this.riskBar);
    const rt = (label, v, key, title) => {
      const el = tile(label, signed(v, 0), key === 'total', title || DV01_HINT);
      el.dataset.k = 'risk-' + key;
      if (typeof v === 'number' && v !== 0) el.classList.add(v > 0 ? 'pos' : 'neg');
      return el;
    };
    this.riskBar.appendChild(h('div', { class: 'l' }, 'DV01 · TRY faizi +1 bp ($)'));
    this.riskBar.appendChild(rt('Toplam', r.total, 'total'));
    this.riskBar.appendChild(rt('Forward', r.fwd, 'fwd', DV01_HINT + ' TL karşılığı: ' + signed(r.fwd_tl, 0)));
    this.riskBar.appendChild(rt('OIS (net)', r.ois, 'ois', DV01_HINT + ' Brüt: ' + (typeof r.ois_gross === 'number' ? num(r.ois_gross, 0) : '—')));
    this.riskBar.appendChild(rt('Tahvil', r.bond, 'bond', DV01_HINT + ' TL karşılığı: ' + signed(r.bond_tl, 0)));
    if (r.unknown) this.riskBar.appendChild(h('div', { class: 'muted warn' }, r.unknown + ' işlemin DV01\'i bilinmiyor (DİBS RV tablosunda olmayan tahvil)'));
    this.riskBar.classList.toggle('hidden', !d.trades.length);

    // in a period every row says which day it belongs to
    const day = (t) => (d.ranged ? [{ t: isoToTr(t.trade_date), k: 's' }] : []);
    const dayHead = d.ranged ? ['Tarih'] : [];

    const fw = d.trades.filter((t) => t.kind === 'fwd');
    // "O/N" is column F of the workbook's blotter sheet: the overnight equivalent of the trade's TRY rate
    this.setGrid('fwd', dayHead.concat(['Saat', 'Kullanıcı', 'Yön', 'Tutar (USD)', 'Valör', 'Gün', 'TRY faizi', 'O/N', 'Forward', 'TL tutarı', 'DV01 (TL)', 'DV01 ($)',
      'Fiyatlama', 'Karşı taraf', 'Not', '']),
      fw.map((t) => day(t).concat([timeOf(t.created_at), this.who(t), { t: t.dir === 'B' ? 'ALIŞ' : 'SATIŞ', k: 's', cls: t.dir === 'B' ? 'buy' : 'sell' },
        n(t.amount, 0), { t: serialDate(t.value_date), v: t.value_date, k: 'd' }, n(t.days, 0), p(t.try_rate, 3), p(t.on_rate, 2), n(t.forward, 4), n(t.tl, 2),
        dv(t.dv01_tl), dv(t.dv01), BASIS_LABEL[t.basis] || t.basis, t.cpt || '', t.note || '',
        this.delCell(t, (t.dir === 'B' ? 'Alış ' : 'Satış ') + num(t.amount, 0) + ' USD · ' + serialDate(t.value_date))])),
      fw.length ? fw.length + ' işlem' : '');

    const os = d.trades.filter((t) => t.kind === 'ois');
    const seenPkg = new Set();
    this.setGrid('ois', dayHead.concat(['Saat', 'Kullanıcı', 'İşlem', 'Bacak', 'Yön', 'Vade', 'Oran', 'Nominal (TL)', 'DV01 ($)', 'Maliyet (bp)', 'Maliyet ($)', 'Karşı taraf', 'Not', '']),
      os.map((t) => {
        const first = !t.package || !seenPkg.has(t.package);
        if (t.package) seenPkg.add(t.package);
        return day(t).concat([timeOf(t.created_at), this.who(t), first ? (t.label || '') : '', ROLE[t.role] || t.role || '',
          { t: t.dir === 'S' ? 'RECEIVE' : 'PAY', k: 's', cls: t.dir === 'S' ? 'buy' : 'sell' }, t.tenor, p(t.rate, 4), n(t.nominal, 0), n(t.dv01, 0),
          first ? n(t.cost_bp, 2) : { t: '', k: '' }, first ? n(t.cost_usd, 0) : { t: '', k: '' }, t.cpt || '', first ? (t.note || '') : '',
          first ? this.delCell(t, t.label || 'OIS işlemi') : { t: '', k: '' }]);
      }), os.length ? os.length + ' bacak' : '');

    const bd = d.trades.filter((t) => t.kind === 'bond');
    this.setGrid('bond', dayHead.concat(['Saat', 'Kullanıcı', 'Enstrüman', 'Yön', 'Tutar', 'Fiyat', 'DV01 (TL)', 'DV01 ($)', 'Not', '']),
      bd.map((t) => day(t).concat([timeOf(t.created_at), this.who(t), t.instrument, { t: t.amount >= 0 ? 'ALIŞ' : 'SATIŞ', k: 's', cls: t.amount >= 0 ? 'buy' : 'sell' },
        n(Math.abs(t.amount), 0), n(t.price, 4), dv(t.dv01_tl), dv(t.dv01), t.note || '', this.delCell(t, t.instrument + ' ' + num(Math.abs(t.amount), 0))])),
      bd.length ? bd.length + ' işlem' : '');

    const c = d.cost || { fwd: [], ois: [], bond: [] };
    this.setGrid('cfwd', ['Valör', 'Alış (USD)', 'Ort. alış kuru', 'Satış (USD)', 'Ort. satış kuru', 'Net (USD)', 'Maliyet (kur)', 'Gerçekleşen K/Z (TL)'],
      c.fwd.map((x) => [{ t: serialDate(x.key), v: x.key, k: 'd' }, n(x.buy, 0), n(x.buy_avg, 4), n(x.sell, 0), n(x.sell_avg, 4), n(x.net, 0),
        n(x.cost, 4), n(x.realised, 2)]));
    this.setGrid('cois', ['Vade', 'Pay DV01 ($)', 'Ort. pay', 'Receive DV01 ($)', 'Ort. receive', 'Net DV01 ($)', 'Maliyet', 'Gerçekleşen K/Z ($)'],
      c.ois.map((x) => [x.key, n(x.buy, 0), p(x.buy_avg, 4), n(x.sell, 0), p(x.sell_avg, 4), n(x.net, 0), p(x.cost, 4), n(x.realised, 0)]));
    this.setGrid('cbond', ['Enstrüman', 'Alış', 'Ort. alış', 'Satış', 'Ort. satış', 'Net', 'Maliyet', 'Gerçekleşen K/Z'],
      c.bond.map((x) => [x.key, n(x.buy, 0), n(x.buy_avg, 4), n(x.sell, 0), n(x.sell_avg, 4), n(x.net, 0), n(x.cost, 4), n(x.realised, 2)]));

    // workbook summary tables
    const sheet = d.sheet || [];
    const order = sheet.map((s) => s.id).join('|');
    if (order !== this.sheetOrder) {
      this.sheetOrder = order;
      this.sheetGrids.clear();
      clear(this.sheetWrap);
      for (const s of sheet) {
        const body = h('div', { class: 'body' });
        const tools = h('div', { class: 'tools' });
        const el = h('section', { class: 'panel' }, h('header', null, h('h2', null, s.title), h('span', { class: 'rng' }, s.range || ''), tools), body);
        if (s.data) {
          const g = new Grid({ book: 'tto', data: s.data, editable: false });
          body.appendChild(g.el);
          const cp = h('button', { class: 'iconbtn', type: 'button' }, 'Kopyala');
          cp.addEventListener('click', () => copyGrid(g));
          tools.appendChild(cp);
          this.sheetGrids.set(s.id, g);
        } else {
          body.appendChild(h('div', { class: 'err' }, s.error || 'veri yok'));
        }
        this.sheetWrap.appendChild(el);
      }
    } else {
      for (const s of sheet) {
        const g = this.sheetGrids.get(s.id);
        if (g && s.data) g.update(s.data, true);
      }
    }
    this.sheetTitle.classList.toggle('hidden', !sheet.length);
    this.sheetLink.classList.toggle('hidden', !sheet.length);
  }
}

export { settings };
