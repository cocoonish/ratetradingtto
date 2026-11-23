// Günlük İşlemler: trade entry (FX forward / OIS / bond) with live pricing, the shared blotter and the
// cost of the day's position.  Everything saved here is visible to every user at once.
import { api, session } from '../api.js';
import { h, clear, toast, errorToast, confirmDialog, debounce, copyText, modal } from '../ui.js';
import { Grid, plainData, copyGrid } from '../grid.js';
import { toolsOf } from '../columns.js';
import { num, pct, raw, serialDate, isoToTr, timeOf, parseNumber, settings, pairOf, parseAmount } from '../format.js';
import { PositionPanel } from '../retposition.js';
import { renderTemplates, openBulk } from './blotterentry.js';

const FWD_BASES = [['RET_BID', 'RET bid'], ['RET_MID', 'RET mid'], ['RET_ASK', 'RET ask'], ['TRY', 'TRY faizi'], ['FWD', 'Forward kur'], ['SP', 'Swap puanı']];
const BASIS_LABEL = { RET_BID: 'RET bid', RET_MID: 'RET mid', RET_ASK: 'RET ask', TRY: 'TRY faizi', FWD: 'Forward kur', SP: 'Swap puanı' };
// what is typed next to the pricing choice: [label, placeholder]
const MANUAL = { TRY: ['TRY faizi (%)', 'örn. 36,50'], FWD: ['Forward kur', 'örn. 52,1000'], SP: ['Swap puanı (×10.000)', 'örn. 17.400'] };
const PAIRS = [['USDTRY', 'USDTRY'], ['EURTRY', 'EURTRY'], ['OTHER', 'Diğer']];
const STRATEGIES = [['outright', 'Outright'], ['spread', 'Spread'], ['fly', 'Fly'], ['fra', 'FRA'], ['mpc', 'MPC']];
const SIDES = {
  outright: [['PAY', 'PAY'], ['RECEIVE', 'RECEIVE']],
  fra: [['PAY', 'PAY'], ['RECEIVE', 'RECEIVE']],
  mpc: [['PAY', 'PAY'], ['RECEIVE', 'RECEIVE']],
  spread: [['STEEPENER', 'STEEPENER'], ['FLATTENER', 'FLATTENER']],
  fly: [['REC GÖVDE', 'REC GÖVDE'], ['PAY GÖVDE', 'PAY GÖVDE']],
};
const ROLE = { outright: 'Outright', short: 'Kısa', long: 'Uzun', wing1: 'Kanat 1', body: 'Gövde', wing2: 'Kanat 2', start: 'Başlangıç', end: 'Bitiş', mpc: 'MPC' };
// a quote's "İşlem gir" (``takePrefill``) empties what the quote does not give - its own date, price and note, and the
// amount (never a quote's: its box empty, a forward's typed in the pair's first currency); ``fillForm`` itself leaves
// alone what a spec leaves out (a template keeps any subset of the form)
const PREFILL_CLEARS = { fwd: { pair: 'USDTRY', basis: 'SP', date: '', value: '', note: '', amount: '' },
  ois: { strategy: 'outright', side: null, level: '', note: '' }, bond: { instrument: '', price: '', note: '', amount: '' } };
// an OIS trade against mid, as the desk reads it ("Mid'e göre"): the stored cost (+ worse than mid) with its sign turned
const VS_MID_HINT = '+ = mid\'den iyi (lehine), − = mid\'den kötü (aleyhine)';
// the boxes of a leg's own rate and the select of that leg's tenor: a rate an edit fills in belongs to its tenor
const LEG_RATES = [['short_rate', 'short'], ['wing1_rate', 'wing1'], ['wing2_rate', 'wing2'], ['start_rate', 'start_months']];
// how "Değişikliği kaydet" prices an edit (the server's ``priced``), in the line over the form's quote; 'today' names
// what changed ("Valör değişti: …")
const EDIT_PRICED = {
  today: ' değişti: bugünkü piyasayla yeniden fiyatlanır',
  trade: { fwd: 'İşlemin kuru, TRY faizi ve spot\'u aynı kalır: tutarlar ve DV01 bunlarla yeniden hesaplanır',
    ois: 'İşlem anının mid\'i ve eğrisiyle: mid\'e göre değer işlemin kendi mid\'ine göre',
    bond: 'DV01 işlemin nominal başına DV01\'iyle hesaplanır' },
  none: 'Yalnızca karşı taraf / not değişir: fiyat ve tutarlar aynı kalır',
};
// what the tip of a trade changed after it was entered says it was before (``timeCell``): [key, label, format]
const EDIT_FIELDS = {
  fwd: [['pair', 'Parite'], ['dir', 'Yön', (v) => (v === 'B' ? 'alış' : 'satış')], ['amount', 'Tutar', (v) => num(v, 0)],
    ['typed_amount', 'Yazılan tutar', (v) => num(v, 2)], ['value_date', 'Valör', serialDate], ['basis', 'Fiyatlama', (v) => BASIS_LABEL[v] || v],
    ['forward', 'Forward', (v) => num(v, 4)], ['points', 'Swap puanı', (v) => num(v, 0)], ['try_rate', 'TRY faizi', (v) => pct(v, 3)],
    ['cpt', 'Karşı taraf'], ['note', 'Not']],
  ois: [['label', 'İşlem'], ['tenor', 'Vade'], ['rate', 'Oran', (v) => pct(v, 4)], ['nominal', 'Nominal', (v) => num(v, 0)],
    ['cpt', 'Karşı taraf'], ['note', 'Not']],
  bond: [['instrument', 'Enstrüman'], ['amount', 'Tutar', (v) => num(v, 0)], ['price', 'Fiyat', (v) => num(v, 4)], ['note', 'Not']],
};

/** The DV01 of an OIS leg with the desk's sign: payer is plus, receiver is minus. */
function payerPlus(leg) {
  return typeof leg.dv01 === 'number' ? (leg.dir === 'S' ? -leg.dv01 : leg.dv01) : null;
}

/** What an OIS trade is worth against mid from its cost (``cost_bp`` / ``cost_usd`` / ``cost_tl``: + worse than mid -
 * stored so, old trades read the same): + better than mid (in its favour), − worse.  null when there is none. */
function vsMid(cost) {
  return typeof cost === 'number' ? 0 - cost : null;
}

/** "Mid'e göre" as it is shown (``digits``): signed and its sign's colour - a trade at mid is 0, neither. */
function vsShown(v, digits) {
  return typeof v === 'number' ? Number(v.toFixed(digits)) : null;
}

/** "Mid'e göre" in a list: signed, + green (better than mid), − red. */
function vsCell(v, digits) {
  const r = vsShown(v, digits);
  return r === null ? { t: '', k: '' } : { t: signed(r, digits), v, k: 'n', c: r > 0 ? 'pos' : (r < 0 ? 'neg' : undefined) };
}

/** The months of a tenor of the lists: "9M" 9, "1Y" 12, "15M" 15 (null for "ON", "1W" …). */
function monthsOf(tenor) {
  const m = /^(\d+)([MY])$/.exec(String(tenor || ''));
  return m ? Number(m[1]) * (m[2] === 'Y' ? 12 : 1) : null;
}

/** A leg that ends on a date of its own - a broken date, named by its day ("04.11.2027"; the server's ``date_tenor``). */
function isDateText(v) {
  return typeof v === 'string' && /^\d{2}\.\d{2}\.\d{4}$/.test(v);
}

/** Where a FRA leg ends, as the form's FRA takes it: its months, or its day when it is a broken date. */
function legPoint(tenor) {
  return isDateText(tenor) ? tenor : monthsOf(tenor);
}

// a trade's row actions that fill the form from it (the server's ``copy``: blotter.copy_specs): [mode, data-act, label, tip]
const COPY_ACTS = [
  ['benzer', 'copy', 'Benzerini gir', 'Benzerini gir: form bu işlemin koşullarıyla yeni işlem olarak dolar (ürün, yapı, yön, büyüklük, vade, '
    + 'karşı taraf, not; başlangıcı geçmişse aynı vade bugünkü spot\'tan). Bugünkü piyasayla fiyatlanır; kaydedene kadar hiçbir şey saklanmaz.'],
  ['ters', 'reverse', 'Ters işlem', 'Ters işlem: form bu işlemi kapatan işlemle dolar - ters yön, aynı büyüklük, aynı bitiş (vade, valör, ISIN, '
    + 'toplantı); başlangıcı geçmişse bugünkü spot\'tan (TRY OIS: işlemin vadesine kırık vade). Bugünkü piyasayla fiyatlanır; kaydedene kadar hiçbir şey saklanmaz.'],
];

/** An amount as the form reads it back to the same number: grouped when it is whole ("812.000.000"), else in full. */
function exactAmount(v) {
  return typeof v === 'number' ? (Number.isInteger(v) ? num(v, 0) : raw(v)) : '';
}

/** A rate kept as a fraction, as the form takes it: per cent, in full (0,3445 → "34,45"). */
function exactRate(v) {
  return typeof v === 'number' ? raw(v * 100) : '';
}

/** A trade in words, for the form's note and its toasts: an OIS by its label, a forward / bond by side, amount, price. */
function tradeText(kind, t) {
  if (kind === 'ois') return t.label || 'OIS işlemi';
  if (kind === 'fwd') {
    const pair = t.pair || 'USDTRY';
    return pair + ' ' + (t.dir === 'B' ? 'alış ' : 'satış ') + num(t.amount, 0) + ' ' + pair.slice(0, 3) + ' · ' + serialDate(t.value_date)
      + (typeof t.forward === 'number' ? ' · ' + num(t.forward, 4) : '');
  }
  return (t.instrument || '') + ' ' + (t.amount >= 0 ? 'alış ' : 'satış ') + num(Math.abs(t.amount), 0) + ' @ ' + num(t.price, 4);
}

/**
 * A trade of the list as the spec of ``fillForm``: what it was entered with, for "Düzenle".  ``legs``: the trade - an OIS
 * package's legs, oldest first.  A forward: pair, side, the amount in the currency it was typed in, value date, pricing and
 * its price (a pair without a curve its spot too); an OIS: strategy, side, tenors / months / days, level, the own rate of
 * every leg the form has a box for (the legs come out as they are unless changed), the size as the legs' nominal - exact
 * (a spread / fly sized by DV01 has legs of different nominals: the DV01 typed, none for the sheet's); a bond: side,
 * instrument, amount, price.  The counterparty and the note too.  null when the form cannot hold the trade.
 */
function editSpec(legs) {
  const t = legs[0];
  if (t.kind === 'fwd') {
    const pair = t.pair || 'USDTRY';
    const basis = BASIS_LABEL[t.basis] ? t.basis : 'RET_MID';
    const spec = { kind: 'fwd', pair, dir: t.dir === 'S' ? 'S' : 'B', date: serialDate(t.value_date), basis, value: '', spot: '',
      cpt: t.cpt || '', note: t.note || '' };
    if (t.typed === 'quote' && typeof t.typed_amount === 'number') spec.quote_amount = exactAmount(t.typed_amount);
    else spec.amount = exactAmount(t.amount);
    if (MANUAL[basis] && typeof t.manual === 'number') spec.value = basis === 'TRY' ? exactRate(t.manual) : raw(t.manual);
    if (pair !== 'USDTRY' && pair !== 'EURTRY' && typeof t.spot === 'number') spec.spot = raw(t.spot);
    return spec;
  }
  if (t.kind === 'bond') {
    return { kind: 'bond', dir: t.amount >= 0 ? 'B' : 'S', instrument: t.instrument || '', amount: exactAmount(Math.abs(t.amount)),
      price: typeof t.price === 'number' ? raw(t.price) : '', note: t.note || '' };
  }
  if (t.kind !== 'ois') return null;
  const role = {};
  for (const lg of legs) role[lg.role] = lg;
  const st = t.strategy || 'outright';
  const bp = st === 'spread' || st === 'fly';
  const spec = { kind: 'ois', strategy: st, side: { 'REC GOVDE': 'REC GÖVDE', 'PAY GOVDE': 'PAY GÖVDE' }[t.side] || t.side || null,
    level: typeof t.level === 'number' ? (bp ? raw(t.level) : exactRate(t.level)) : '', cpt: t.cpt || '', note: t.note || '' };
  let size = null;
  if (bp) {
    const one = st === 'spread' ? role.long : role.body;              // the leg of weight 1
    const others = st === 'spread' ? [role.short] : [role.wing1, role.wing2];
    if (!one || others.some((x) => !x)) return null;
    spec.tenors = st === 'spread' ? [role.short.tenor, role.long.tenor] : [role.wing1.tenor, role.body.tenor, role.wing2.tenor];
    if (st === 'spread') spec.short_rate = exactRate(role.short.rate);
    else Object.assign(spec, { wing1_rate: exactRate(role.wing1.rate), wing2_rate: exactRate(role.wing2.rate) });
    // sized by a nominal: every leg that nominal (a wing half of it); by DV01: as typed (a trade of before: its leg's DV01)
    const w = st === 'spread' ? 1 : 0.5;
    const byNominal = t.size_mode ? t.size_mode === 'nominal' : others.every((x) => Math.abs(x.nominal - w * one.nominal) < 0.5);
    spec.sizeMode = byNominal ? 'nominal' : 'dv01';
    size = byNominal ? one.nominal : (t.size_mode ? t.size_typed : Math.round(one.dv01));
  } else {
    if (st === 'outright') spec.tenors = [t.tenor];
    else if (st === 'fra') {
      if (!role.end) return null;
      spec.months = [role.start ? legPoint(role.start.tenor) : 0, legPoint(role.end.tenor)];
      if (role.start) spec.start_rate = exactRate(role.start.rate);
    } else if (st === 'mpc') {
      if (!t.mpc) return null;
      Object.assign(spec, { start: t.mpc.start, end: t.mpc.end });
    }
    spec.sizeMode = 'nominal';
    size = (role.end || t).nominal;                                    // (a FRA's two legs: one nominal)
  }
  spec.size = exactAmount(size);
  return spec;
}

/** A number kept in a template, read the same in Turkish and in English: a lone group of three ("17.400", "10,000" -
 * thousands in one format, a decimal in the other) is written out ("17400"); anything else stays as typed ("10m", "2,5m",
 * "10.000.000").  A desk template is filled by users of either format. */
export function portable(text) {
  const s = String(text || '').trim();
  const m = /^([+-]?[1-9]\d{0,2}[.,]\d{3})\s*([a-zA-Z]*)$/.exec(s);
  if (!m) return s;
  const x = parseNumber(m[1]);
  return x === null ? s : String(x) + m[2];
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

/** A forward's amount in the list - its first currency's (``side`` 'base', to the unit) or its second's ('quote', to the
 * kuruş) -, the one it was typed in marked (✎) when that was the second (a minor-currency entry). */
function typedCell(t, side) {
  const cell = side === 'base' ? n(t.amount, 0) : n(t.tl, 2);
  if (t.typed !== 'quote' || typeof t.amount !== 'number') return cell;
  const pair = t.pair || 'USDTRY';
  return Object.assign(cell, side === 'quote' ? { cls: 'typed', tip: 'Yazılan tutar (' + pair.slice(3) + '): işlem bu tutarla girildi' }
    : { tip: num(t.amount, 2) + ' ' + pair.slice(0, 3) + ' = ' + num(t.tl, 2) + ' ' + pair.slice(3) + ' / ' + num(t.forward, 4) + ' (forward kurundan)' });
}

function signed(v, digits) {
  return typeof v === 'number' ? (v > 0 ? '+' : '') + num(v, digits || 0) : '—';
}

function isoDay(d) {
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
}

const DV01_HINT = 'TRY faizi +1 bp olursa kâr / zarar. İşaret her yerde aynı: payer + (faiz artınca kazanır: PAY, vadeli döviz alışı); receiver − (RECEIVE, vadeli döviz satışı, tahvil alışı).';
const PPK_HINT = 'Piyasa mid = Bootstrap (Murex): bugünkü eğri, Murex\'in MTM\'i. PPK basamak = TLREF toplantılar arasında sabit, '
  + 'OIS kotalarına aynen oturur: aynı FRA, aynı takvim ve gün sayımı, öbür eğri. İki eğri kotalı vadelerde aynı, aralarında farklı (12x15, 15x18 …).';

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
    this.fwd = { dir: 'B', basis: 'RET_MID', pair: 'USDTRY', typed: 'base' };      // typed: the amount typed - 'base' (USD) or 'quote' (TRY)
    this.ois = { strategy: 'outright', side: 'PAY', sizeMode: 'dv01' };
    this.editing = null;          // the trade the form is changing ("Düzenle"): {id, kind, label, rates, restore}
    this.copied = null;           // what the form was filled from ("Benzerini gir" / "Ters işlem"): {kind, head, how}
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
    if (this.data.can_enter) this.takePrefill();         // a trade filled from a quote, if one was sent here
  }

  async refresh() {
    const data = await api.get('/api/blotter', this.query());
    if (this.dead) return;
    const users = Object.keys(this.users);
    const lastBy = (t) => (Array.isArray(t.edits) && t.edits.length ? t.edits[t.edits.length - 1].by : null);
    if (data.trades.some((t) => (t.created_by && !users.includes(t.created_by)) || (lastBy(t) && !users.includes(lastBy(t))))) {
      const u = await api.get('/api/users');
      for (const x of u.users) this.users[x.name] = x.display;
    }
    this.data = data;
    this.fill();
    if (this.data.can_enter) {
      if (this.tab === 'fwd') this.quoteFwd(); else if (this.tab === 'ois') this.quoteOis();
    }
  }

  destroy() {
    this.dead = true;
    this.quoteFwd.cancel();
    this.quoteOis.cancel();
    this.quoteBond.cancel();
  }

  /** ``#/blotter?p=position``: the position and its cost per RET tenor. */
  focusPanel(id) {
    if (id === 'position' && this.position) this.position.focus();
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
        // the desk's trades said in the broker chat that are not here: said before the day is archived
        if (this.ctx.checkArchive && !(await this.ctx.checkArchive(this.data.date, this.data.ranged ? this.data.to : null))) return;
        const res = await api.download('/api/blotter/export', { date: this.date || undefined, to: this.to || undefined }, 'Blotter.xlsx');
        toast(res.name + ' indirildi', 'ok', 3200);
      } catch (err) { errorToast(err); } finally { this.exportBtn.disabled = false; }
    });
    this.host.appendChild(h('div', { class: 'page-tools' }, h('span', { class: 'muted' }, 'İşlem günü'), this.dateSel, this.todayBtn, range,
      this.exportBtn, h('span', { class: 'grow' }), h('span', { class: 'muted' }, 'Kaydedilen işlemler tüm kullanıcılarda anında görünür')));
    this.host.appendChild(this.dayNote);
    this.dayNote.className = 'banner hidden';

    this.entry = h('div', { class: 'card entry' });
    this.editing = null;             // (the forms are new: an edit of the page before is gone with them)
    const tabs = h('div', { class: 'tabs' });
    const panes = { fwd: this.buildFwd(), ois: this.buildOis(), bond: this.buildBond() };
    const tabBtns = (this.tabBtns = {});
    const show = (id) => {
      this.tab = id;
      this.showTab = show;
      for (const k of Object.keys(panes)) {
        panes[k].classList.toggle('hidden', k !== id);
        tabBtns[k].classList.toggle('on', k === id);
      }
      this.copyNote.classList.toggle('hidden', !this.copied || this.copied.kind !== id);     // (the line belongs to its product)
      if (id === 'fwd') this.quoteFwd(); else if (id === 'ois') this.quoteOis(); else this.quoteBond();
    };
    for (const [id, label] of [['fwd', 'FX Forward'], ['ois', 'OIS'], ['bond', 'Tahvil']]) {
      const b = h('button', { type: 'button' }, label);
      b.addEventListener('click', () => show(id));
      tabBtns[id] = b;
      tabs.appendChild(b);
    }
    // rows copied from Excel, checked and kept together; the templates of the form one click away
    const bulkBtn = h('button', { class: 'btn sm', type: 'button', id: 'bulk-open',
      title: 'Excel\'den kopyalanan işlem satırlarını yapıştırın: her satır formdaki gibi denetlenir, önizlemeden sonra geçerliler tek seferde kaydedilir' },
    'Excel\'den yapıştır');
    bulkBtn.addEventListener('click', () => openBulk(this));
    this.tplBar = h('div', { class: 'tplbar', id: 'blotter-templates' });
    this.tplKey = null;
    this.entryTitle = h('h2', { id: 'blotter-entry-title' }, 'Yeni işlem');
    // "Düzenle": which trade the form is changing, while it does (``markEditing``)
    this.editNote = h('div', { class: 'editnote hidden', id: 'blotter-edit-note' });
    // "Benzerini gir" / "Ters işlem": which trade the form was filled from (``markCopied``), until it is saved
    this.copyNote = h('div', { class: 'editnote hidden', id: 'blotter-copy-note' });
    this.copied = null;
    this.entry.appendChild(h('header', null, this.entryTitle, bulkBtn));
    this.entry.appendChild(this.editNote);
    this.entry.appendChild(this.copyNote);
    this.entry.appendChild(this.tplBar);
    this.entry.appendChild(tabs);
    for (const k of Object.keys(panes)) this.entry.appendChild(panes[k]);
    this.readonlyNote = h('div', { class: 'card hidden' }, h('div', { class: 'pad muted' },
      'Geçmiş bir gün ya da bir tarih aralığı görüntüleniyor. Yeni işlem girmek için "Bugün"e dönün.'));
    // what the listed trades add up to in risk
    this.riskBar = h('div', { class: 'riskbar', title: DV01_HINT });

    const lists = h('div', { class: 'lists' });
    this.sections = {};
    for (const [id, title] of [['fwd', 'Forward işlemleri'], ['ois', 'OIS işlemleri'], ['bond', 'Tahvil işlemleri'],
      ['cfwd', 'Maliyet · Forward (parite ve valöre göre)'], ['cois', 'Maliyet · OIS (vadeye göre)'], ['cbond', 'Maliyet · Tahvil']]) {
      const body = h('div', { class: 'body' });
      const count = h('span', { class: 'muted' });
      const cp = h('button', { class: 'iconbtn', type: 'button', title: 'Tabloyu kopyala (Excel\'e yapıştırılabilir)' }, 'Kopyala');
      cp.addEventListener('click', () => { if (this.grids[id]) copyGrid(this.grids[id]); });
      const sec = h('section', { class: 'panel wide' }, h('header', null, h('h2', null, title), count, h('div', { class: 'tools' }, cp)), body);
      this.sections[id] = { el: sec, body, count };
      lists.appendChild(sec);
    }
    // the desk's net TRY position and its cost per RET tenor, today and the last days (retposition.js)
    this.position = new PositionPanel(this.ctx);
    lists.appendChild(this.position.el);
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
    if (session.role === 'admin') this.sheetTitle.appendChild(this.sheetLink);          // the sheet explorer is the administrators'
    // what the workbook's own sheet cannot hold is said next to its tables
    this.sheetNote = h('span', { class: 'sheetnote hidden', id: 'blotter-sheet-note' });
    this.sheetTitle.appendChild(this.sheetNote);
    // a period's (or a day gone by's without its archive): the same tables over the trades shown - said what they cover
    this.sheetScope = h('div', { class: 'banner hidden', id: 'blotter-sheet-scope' });
    this.host.appendChild(this.sheetTitle);
    this.host.appendChild(this.sheetScope);
    this.host.appendChild(this.sheetWrap);
    this.showTab = show;
    show(this.tab);
  }

  /**
   * A trade filled from a quote - a matrix row, a chat line, a price right-clicked on a page: its tab, side and fields,
   * waiting for an amount and "İşlemi kaydet" (nothing is saved here; every field stays the user's to change).
   *
   * The way in from elsewhere is ``ctx.openTrade(spec)`` (main.js: kept for this page, then opened); the form is filled by
   * ``fillForm``, the form's one way in. ``spec``:
   *   {kind: 'fwd', pair: 'USDTRY' | 'EURTRY', dir: 'B' | 'S' | null, date: '15.12.2026' | '3M', basis: 'SP' | 'FWD' | 'TRY'
   *    | 'RET_BID' | 'RET_MID' | 'RET_ASK', value: the points / outright / TRY rate as text (none for RET), note, cpt}
   *   {kind: 'ois', strategy: 'outright' | 'spread' | 'fly' | 'fra' | 'mpc', side: 'PAY' | 'RECEIVE' | … | null,
   *    tenors: ['1Y', …] (outright / spread / fly), months: [start, end] (FRA), start, end (MPC: serials of the form's days),
   *    level: as text, note, cpt}
   *   {kind: 'bond', dir: 'B' | 'S' | null, instrument: ISIN, price: as text, note}
   * The fields a quote does not give are emptied (``PREFILL_CLEARS``).  A side of null is left to the user: no side is
   * chosen and the trade is not saved until one is.  The amount is never filled - its box empty, a forward's in the pair's
   * first currency -, the counterparty only by a broker's chat line (``cpt``; without one, the one typed stays).
   */
  takePrefill() {
    let spec = null;
    try {
      spec = JSON.parse(sessionStorage.getItem('tto.trade.prefill') || 'null');
      sessionStorage.removeItem('tto.trade.prefill');
    } catch (e) { spec = null; }
    if (!spec || !this.showTab || !PREFILL_CLEARS[spec.kind]) return false;
    if (!spec.cpt) delete spec.cpt;                    // (no counterparty in the quote: the one typed stays)
    const said = spec.said || 'İşlem kotadan dolduruldu: tutarı yazıp kaydedin';      // (a Ctrl+K command says its own)
    delete spec.said;
    this.endEdit(true);                                // a new trade: an edit in progress is left, the trade as it was
    this.markCopied(null);
    const done = this.fillForm(Object.assign({ dir: null }, PREFILL_CLEARS[spec.kind], spec));
    if (!done) return false;
    toast(said + (done.warn ? ' (' + done.warn + ')' : ''), done.warn ? 'warn' : 'ok', done.warn ? 7000 : 4000);
    return true;
  }

  /**
   * Fill the entry form: the one way in for whatever opens a trade to enter - a quote's "İşlem gir" (``ctx.openTrade`` →
   * ``takePrefill``), a template (``applyTemplate``).  Opens the product's tab and prices what is there; nothing is saved.
   * A field the spec leaves out stays as it is on the form; every field is optional but ``kind``:
   *   kind 'fwd':  pair ('USDTRY', 'EURTRY', any other - "Diğer" with its code), dir ('B' | 'S'), amount (in the pair's first
   *                currency, as typed: '10m') or quote_amount (in its second: the TRY of USDTRY), date (a date or a tenor:
   *                '15.12.2026', '3M'), basis ('RET_BID' … 'SP'), value (the rate / outright / points of that basis), spot,
   *                cpt, note
   *   kind 'ois':  strategy, side, tenors ([tenor] | [short, long] | [wing1, body, wing2]), months ([start, end] of a FRA),
   *                start / end (a meeting swap's two days, as serials) or mpc ([k1, k2]: places in the list of meetings -
   *                0 the spot, k the k-th meeting), level, size with sizeMode ('dv01' | 'nominal'), a leg's own rate (%,
   *                ``LEG_RATES``: short_rate, wing1_rate, wing2_rate, start_rate - a trade being edited), cpt, note
   *   kind 'bond': dir, instrument, amount, price, note
   * Returns null when the spec is no trade of the form, else ``{ warn }``: what could not be filled, in words ('' when all was).
   */
  fillForm(spec) {
    if (!spec || !this.showTab || !['fwd', 'ois', 'bond'].includes(spec.kind)) return null;
    const has = (k) => Object.prototype.hasOwnProperty.call(spec, k);
    const text = (k, el) => { if (has(k)) el.value = spec[k] === null || spec[k] === undefined ? '' : String(spec[k]); };
    const missing = [];                    // what the form has no option for (a tenor it does not list)
    let sideKnown = true;
    const pick = (sel, value, label) => {
      if (!sel || value === undefined || value === null || value === '') return false;
      const v = String(value);
      if (![...sel.options].some((x) => x.value === v)) {
        if (!label) { missing.push(v); return false; }
        sel.appendChild(h('option', { value: v }, label));           // a FRA month off the quarterly grid
      }
      sel.value = v;
      return true;
    };
    if (spec.kind === 'fwd') {
      const f = this.fwd;
      if (has('pair')) {
        const code = pairOf(spec.pair) || 'USDTRY';
        f.pair = code === 'USDTRY' || code === 'EURTRY' ? code : 'OTHER';
        if (f.pair === 'OTHER') f.code.value = code;
        f.pairSeg.set(f.pair);
      }
      if (has('dir')) {
        sideKnown = spec.dir === 'B' || spec.dir === 'S';
        f.dir = sideKnown ? spec.dir : null;               // (not known: left to the user)
        f.dirSeg.set(f.dir);
      }
      if (has('basis')) {
        f.basis = BASIS_LABEL[spec.basis] ? spec.basis : 'SP';
        f.basisSeg.set(f.basis);
      }
      text('date', f.date);
      text('value', f.manual);
      text('spot', f.spot);
      text('cpt', f.cpt);
      text('note', f.note);
      if (has('amount') || has('quote_amount')) {
        // one amount, in the currency it was typed in: the other one is worked out again from today's forward
        f.typed = spec.quote_amount && !spec.amount ? 'quote' : 'base';
        f.amount.value = f.typed === 'base' ? String(spec.amount || '') : '';
        f.quoteAmount.value = f.typed === 'quote' ? String(spec.quote_amount) : '';
        f.amount.title = f.quoteAmount.title = '';       // (the worked-out one's tip: said again by the quote)
        this.markTyped();
      }
      this.layoutFwd();
      this.showTab('fwd');
      (f.typed === 'quote' ? f.quoteAmount : f.amount).focus();
    } else if (spec.kind === 'ois') {
      const o = this.ois;
      clear(o.marketHint);                 // (the mid of the trade on the form before: its "kullan" is not this one's)
      if (has('strategy')) {
        o.strategy = STRATEGIES.some((x) => x[0] === spec.strategy) ? spec.strategy : 'outright';
        o.stratSeg.set(o.strategy);
      }
      if (has('side')) {
        if (spec.side && SIDES[o.strategy].some((x) => x[0] === spec.side)) o.side = spec.side;
        else sideKnown = false;
      }
      if (has('strategy')) this.layoutOis();             // its legs and sides (the level is emptied: filled below)
      else if (has('side')) o.sideSeg.set(o.side);
      if (!sideKnown) { o.side = null; o.sideSeg.set(null); }      // (not known: left to the user)
      const legs = { outright: ['tenor'], spread: ['short', 'long'], fly: ['wing1', 'body', 'wing2'] }[o.strategy] || [];
      // (a leg to a date of its own - a broken date: an option of its own, as a FRA month off the grid)
      const broken = (v) => (isDateText(v) ? v + ' · kırık vade' : undefined);
      if (has('tenors')) legs.forEach((k, i) => pick(o.f[k], (spec.tenors || [])[i], broken((spec.tenors || [])[i])));
      if (o.strategy === 'fra' && spec.months && spec.months.length === 2) {
        const label = (m) => (m === 0 ? 'Spot' : (m % 12 === 0 ? (m / 12) + 'Y' : m + 'M'));
        spec.months.forEach((m, i) => {
          if (typeof m === 'number' && Number.isInteger(m) && m >= 0) pick(o.f[i ? 'end_months' : 'start_months'], m, label(m));
          else if (isDateText(m)) pick(o.f[i ? 'end_months' : 'start_months'], m, broken(m));
          else missing.push(String(m));
        });
      }
      if (o.strategy === 'mpc' && (has('start') || has('end') || has('mpc'))) {
        // a meeting swap: its two days among the form's (OIS spot, the meetings' effective days) - a template's by their
        // place in the list (the next meeting stays the next one as meetings pass)
        const m = (this.market && this.market.mpc) || { dates: [] };
        const day = (k) => (k === 0 ? m.spot : (m.dates[k - 1] || {}).date);
        const days = has('mpc') && Array.isArray(spec.mpc) ? { start: day(spec.mpc[0]), end: day(spec.mpc[1]) } : { start: spec.start, end: spec.end };
        for (const k of ['start', 'end']) {
          const sel = o.f[k];
          const v = String(days[k]);
          if (sel && [...sel.options].some((x) => x.value === v)) sel.value = v;
          else missing.push(serialDate(days[k]) || (has('mpc') ? 'MPC' + spec.mpc[k === 'start' ? 0 : 1] : v));
        }
      }
      if (has('size')) {
        this.setSizeMode(spec.sizeMode === 'nominal' ? 'nominal' : 'dv01');
        text('size', o.size);
      }
      text('level', o.level);
      for (const [k] of LEG_RATES) if (o.f[k]) text(k, o.f[k]);
      text('cpt', o.cpt);
      text('note', o.note);
      this.showTab('ois');
      (o.level.value ? o.size : o.level).focus();
    } else {
      const b = this.bond;
      if (has('dir')) {
        sideKnown = spec.dir === 'B' || spec.dir === 'S';
        b.dir = sideKnown ? spec.dir : null;              // (not known: left to the user)
        b.dirSeg.set(b.dir);
      }
      text('instrument', b.inst);
      text('amount', b.amount);
      text('price', b.price);
      text('note', b.note);
      b.amount.dispatchEvent(new Event('input'));       // (its echo)
      this.showTab('bond');
      b.amount.focus();
    }
    const warn = [missing.length ? 'listede olmayan vade: ' + missing.join(', ') + ' – elle seçin' : '', sideKnown ? '' : 'yönü seçin'].filter(Boolean);
    return { warn: warn.join('; ') };
  }

  /** The form of a product as a spec of ``fillForm`` - every field that has something in it (what a template keeps; its
   * amounts and points ``portable``: the same in either number format). */
  formSpec(kind) {
    const out = { kind };
    const put = (k, v) => { if (v !== undefined && v !== null && String(v).trim() !== '') out[k] = typeof v === 'string' ? v.trim() : v; };
    if (kind === 'fwd') {
      const f = this.fwd;
      put('pair', this.fwdPair());
      put('dir', f.dir);
      if (f.typed === 'quote') put('quote_amount', portable(f.quoteAmount.value)); else put('amount', portable(f.amount.value));
      put('date', f.date.value);
      put('basis', f.basis);
      if (MANUAL[f.basis]) put('value', f.basis === 'SP' ? portable(f.manual.value) : f.manual.value);
      if (f.pair === 'OTHER') put('spot', f.spot.value);
      put('cpt', f.cpt.value);
      put('note', f.note.value);
    } else if (kind === 'ois') {
      const o = this.ois;
      put('strategy', o.strategy);
      put('side', o.side);
      const legs = { outright: ['tenor'], spread: ['short', 'long'], fly: ['wing1', 'body', 'wing2'] }[o.strategy];
      if (legs) out.tenors = legs.map((k) => o.f[k].value);
      if (o.strategy === 'fra') out.months = [o.f.start_months.value, o.f.end_months.value].map((v) => (isDateText(v) ? v : Number(v)));
      if (o.strategy === 'mpc') {
        const m = (this.market && this.market.mpc) || { dates: [] };
        const place = (v) => (Number(v) === m.spot ? 0 : 1 + m.dates.findIndex((d) => d.date === Number(v)));
        const k = [place(o.f.start.value), place(o.f.end.value)];
        if (k[1] > k[0]) out.mpc = k;
      }
      put('level', o.level.value);
      if (o.size.value.trim()) { put('size', portable(o.size.value)); out.sizeMode = o.sizeMode; }
      put('cpt', o.cpt.value);
      put('note', o.note.value);
    } else {
      const b = this.bond;
      put('dir', b.dir);
      put('instrument', b.inst.value);
      put('amount', portable(b.amount.value));
      put('price', b.price.value);
      put('note', b.note.value);
    }
    return out;
  }

  // ------------------------------------------------------------------ "Düzenle": a trade changed after it was entered
  /** The form of a product as it stands, every field said - the empty ones too (a spec of ``fillForm``): what an edit gives
   * back when it ends. */
  formSnapshot(kind) {
    const o = this.ois, f = this.fwd;
    const blank = { fwd: { pair: f.pair === 'OTHER' ? f.code.value : f.pair, dir: f.dir, date: '', value: '', spot: '', cpt: '', note: '', amount: '' },
      ois: { side: o.side, level: '', size: '', sizeMode: o.sizeMode, cpt: '', note: '' },
      bond: { dir: this.bond.dir, instrument: '', amount: '', price: '', note: '' } }[kind];
    const out = Object.assign(blank, this.formSpec(kind));
    if (kind === 'ois') for (const [k] of LEG_RATES) if (o.f[k] && o.f[k].value.trim()) out[k] = o.f[k].value;
    return out;
  }

  /**
   * "Düzenle" on a trade of the list: the form of its product filled with what it was entered with (``editSpec``); its
   * button says "Değişikliği kaydet" (with "Vazgeç" beside it) and its quote is what saving would keep (``quoteOf``: the
   * server's preview), a line over it saying how it is priced (``pricingLine``).  Saved, the trade changes in place
   * (``POST /api/blotter/trade/<id>``: the same ids, its time and who entered it stay) - what the form changed alone moves:
   * the counterparty / note, at the trade's own prices, or on today's market for another instrument; the form as it was
   * before comes back.  The product and an OIS's strategy stay what they are.
   */
  startEdit(t) {
    this.endEdit(true);
    this.markCopied(null);
    const legs = t.kind === 'ois' && t.package ? this.data.trades.filter((x) => x.package === t.package) : [t];
    const spec = editSpec(legs);
    if (!spec) { toast('Bu işlem formda açılamıyor: silip yeniden girin', 'err'); return; }
    const restore = this.formSnapshot(spec.kind);
    const rates = {};
    for (const [k] of LEG_RATES) if (spec[k] !== undefined) rates[k] = String(spec[k]);
    // (an OIS's size as filled in: given back untouched, it is the trade's - its legs' nominals stay)
    const size = spec.kind === 'ois' ? { text: String(spec.size || ''), mode: spec.sizeMode } : null;
    this.editing = { id: t.id, kind: spec.kind, label: tradeText(spec.kind, legs[0]), at: legs[0].created_at, by: this.who(legs[0]), rates, size, restore };
    const done = this.fillForm(spec);
    this.markEditing();
    this.entry.scrollIntoView({ block: 'nearest' });
    if (done && done.warn) toast('Düzenleniyor (' + done.warn + ')', 'warn', 6000);
  }

  /** The form says whether it enters a new trade or changes one (``this.editing``): its title, which trade, its buttons. */
  markEditing() {
    const ed = this.editing;
    this.entryTitle.textContent = ed ? 'İşlemi düzenle' : 'Yeni işlem';
    clear(this.editNote);
    if (ed) {
      this.editNote.appendChild(h('div', null, h('b', null, 'Düzenleniyor: '), ed.label));
      this.editNote.appendChild(h('div', { class: 'muted' }, 'Girildi: ' + timeOf(ed.at) + ' · ' + ed.by
        + '. Değiştirilmeyen oynamaz: fiyat kutusunun üstündeki satır kaydedince nasıl fiyatlanacağını söyler; aynı kayıt değişir, önceki değerler işlemde saklanır.'));
    }
    this.editNote.classList.toggle('hidden', !ed);
    for (const [k, b] of Object.entries(this.tabBtns)) b.disabled = !!ed && k !== ed.kind;      // (the product stays)
    for (const [k, form] of [['fwd', this.fwd], ['ois', this.ois], ['bond', this.bond]]) {
      const on = !!ed && ed.kind === k;
      form.save.textContent = on ? 'Değişikliği kaydet' : 'İşlemi kaydet';
      form.cancel.classList.toggle('hidden', !on);
    }
    for (const b of this.ois.stratSeg.children) {              // (so does an OIS's strategy: the server refuses another)
      b.disabled = !!ed && ed.kind === 'ois' && b.dataset.v !== this.ois.strategy;
      b.title = b.disabled ? 'Düzenlemede strateji değişmez: strateji değişiyorsa işlemi silip yeniden girin' : '';
    }
  }

  /** Out of an edit (saved, "Vazgeç", the form wanted for a new trade): the form back to a new trade - as it was before the
   * edit when ``restore``. */
  endEdit(restore) {
    const ed = this.editing;
    if (!ed) return;
    this.editing = null;
    this.markEditing();
    if (restore) this.fillForm(ed.restore);
  }

  /** "Değişikliği kaydet": the trade being edited changed in place - what the form changed alone moves (the server's rules:
   * the counterparty / note alone, at the trade's own prices, or on today's market when the instrument changed). */
  async saveEdit(kind, pl, btn) {
    const ed = this.editing;
    btn.disabled = true;
    try {
      const res = await api.post('/api/blotter/trade/' + ed.id, Object.assign({ kind }, pl));
      toast(res.edited ? 'İşlem güncellendi: ' + tradeText(kind, res) + (res.priced === 'today' ? ' · bugünkü piyasayla yeniden fiyatlandı' : '')
        : 'Değişiklik yok: işlem olduğu gibi kaldı', res.edited ? 'ok' : 'warn', 4200);
      if (this.editing === ed) this.endEdit(true);
      this.ctx.refreshNow();
    } catch (err) { errorToast(err); } finally { btn.disabled = false; }
  }

  /** The form's quote: a new trade's (``url``) - or, while a trade of this product is edited, what saving it would make of it
   * (``…/preview``: the trade as it would be kept, how it is priced).  ``{ q, edit }``: the quote, the edit's answer (or null). */
  async quoteOf(kind, url, pl) {
    const ed = this.editing;
    if (!ed || ed.kind !== kind) return { q: await api.post(url, pl), edit: null };
    const edit = await api.post('/api/blotter/trade/' + ed.id + '/preview', Object.assign({ kind }, pl));
    return { q: edit.quote, edit };
  }

  /** While a trade is edited: how "Değişikliği kaydet" prices it, one line over the quote (``edit``: the preview's answer) -
   * on today's market (what changed; the line marked), at the trade's own prices, or its counterparty / note alone. */
  pricingLine(box, edit) {
    if (!edit || !this.editing) return;
    const why = (edit.why || []).join(' / ');
    const text = edit.priced === 'today' ? why.charAt(0).toUpperCase() + why.slice(1) + EDIT_PRICED.today
      : (edit.priced === 'trade' ? EDIT_PRICED.trade[this.editing.kind] : (edit.priced === 'none' ? EDIT_PRICED.none : 'Değişiklik yok'));
    box.insertBefore(h('div', { class: 'editprice' + (edit.priced === 'today' ? ' today' : ''), 'data-k': 'edit-pricing' }, text), box.firstChild);
  }

  // ------------------------------------------------------------------ "Benzerini gir" / "Ters işlem": a trade copied
  /**
   * "Benzerini gir" (the trade again, a new one) or "Ters işlem" (the trade that offsets it) on a trade of the list -
   * today's or a day gone by's, wherever the form is open: the form of its product filled with what the server made of it
   * (``t.copy[mode]``, :func:`blotter.copy_specs`: the spec of ``fillForm`` - amounts and sizes as numbers, written here in
   * the user's format -, ``how`` it was made), as a new trade: an edit in progress is left.  No price, rate or level comes
   * along: the form prices it on today's market as any new trade; a line over the form says what it was filled from.
   * Nothing is saved until "İşlemi kaydet".
   */
  copyFrom(t, mode, what) {
    const c = (t.copy || {})[mode];
    if (!c || !c.spec) { toast((c && c.why) || 'Bu işlem formda açılamıyor', 'err'); return; }
    this.endEdit(true);
    const spec = Object.assign({}, c.spec);
    for (const k of ['amount', 'quote_amount', 'size']) if (typeof spec[k] === 'number') spec[k] = exactAmount(spec[k]);
    const done = this.fillForm(spec);
    if (!done) { toast('Bu işlem formda açılamıyor', 'err'); return; }
    const head = (mode === 'ters' ? 'Ters işlem: ' : 'Benzeri: ') + what + (t.trade_date !== this.data.today ? ' (' + isoToTr(t.trade_date) + ')' : '');
    this.markCopied({ kind: spec.kind, mode, head, how: c.how || '' });
    this.entry.scrollIntoView({ block: 'nearest' });
    toast(head + ' – form dolduruldu: fiyatı kontrol edip kaydedin' + (done.warn ? ' (' + done.warn + ')' : ''), done.warn ? 'warn' : 'ok',
      done.warn ? 7000 : 3500);
  }

  /** The line over the form: which trade it was filled from ("Benzeri: …" / "Ters işlem: …") and how - until that trade
   * is saved or the form is filled from something else (null: none). */
  markCopied(c) {
    if (!this.copyNote) return;
    this.copied = c;
    clear(this.copyNote);
    if (c) {
      this.copyNote.appendChild(h('div', { 'data-k': 'copy-head' }, h('b', null, c.head)));
      this.copyNote.appendChild(h('div', { class: 'muted', 'data-k': 'copy-how' }, (c.how ? c.how + '. ' : '')
        + 'Bugünkü piyasayla fiyatlanır; "İşlemi kaydet"e basılana kadar hiçbir şey saklanmaz.'));
    }
    this.copyNote.classList.toggle('hidden', !c || c.kind !== this.tab);
  }

  /** "Benzerini gir" / "Ters işlem" of a trade (the server's ``copy``, on a listing where the form is open): a button
   * each - none where one makes no sense for the trade, the cell's tip saying why. */
  copyActs(t, what) {
    const out = { act: [], why: [] };
    if (!t.copy || !this.data.can_enter) return out;
    for (const [mode, id, label, title] of COPY_ACTS) {
      const c = t.copy[mode] || {};
      if (c.spec) out.act.push({ id, label, title, fn: () => this.copyFrom(t, mode, what) });
      else out.why.push(label + ' yok: ' + (c.why || 'formda açılamıyor'));
    }
    return out;
  }

  /** "Düzenle" on a trade of a day gone by: its counterparty and note alone (all that changes after its day; its prices
   * and amounts stay) - in a dialog, the day's entry form being closed. */
  editFields(t) {
    const legs = t.kind === 'ois' && t.package ? this.data.trades.filter((x) => x.package === t.package) : [t];
    const m = modal({ title: 'Karşı taraf ve not', width: 460 });
    m.box.id = 'blotter-fields';
    const cpt = input('opsiyonel');
    cpt.id = 'blotter-fields-cpt';
    cpt.value = t.cpt || '';
    const note = input('opsiyonel');
    note.id = 'blotter-fields-note';
    note.value = t.note || '';
    m.body.appendChild(h('div', { class: 'pad form' }, h('div', { class: 'muted' }, isoToTr(t.trade_date) + ' · ' + tradeText(t.kind, legs[0])),
      t.kind === 'bond' ? null : h('div', { class: 'row' }, field('Karşı taraf', cpt)), h('div', { class: 'row' }, field('Not', note)),
      h('div', { class: 'muted' }, 'Geçmiş günün işleminde yalnızca karşı taraf ve not değişir: fiyat ve tutarlar aynı kalır.')));
    const save = h('button', { class: 'btn primary', type: 'button', id: 'blotter-fields-save' }, 'Kaydet');
    save.addEventListener('click', async () => {
      save.disabled = true;
      try {
        const fields = t.kind === 'bond' ? { note: note.value } : { cpt: cpt.value, note: note.value };
        const res = await api.post('/api/blotter/trade/' + t.id, { kind: t.kind, fields });
        toast(res.edited ? 'Karşı taraf / not güncellendi' : 'Değişiklik yok', res.edited ? 'ok' : 'warn', 3000);
        m.close();
        this.ctx.refreshNow();
      } catch (err) { errorToast(err); } finally { save.disabled = false; }
    });
    for (const el of [cpt, note]) el.addEventListener('keydown', (e) => { if (e.key === 'Enter') save.click(); });
    m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Vazgeç'));
    m.foot.appendChild(save);
    (t.kind === 'bond' ? note : cpt).focus();
  }

  // ------------------------------------------------------------------ forward form
  buildFwd() {
    const f = this.fwd;
    const pane = h('div', { class: 'pad form' });
    f.dirSeg = seg([['B', 'Alış (USD al)'], ['S', 'Satış (USD sat)']], f.dir, (v) => { f.dir = v; this.quoteFwd(); }, { B: 'buy', S: 'sell' });
    // the amount in either currency of the pair, side by side: the one typed is kept, the other follows from the forward
    f.amount = input('örn. 10m ya da 10.000.000', 'num');
    f.amount.id = 'fwd-amount';
    f.amountEcho = h('div', { class: 'muted echo' });
    f.quoteAmount = input('örn. 500m', 'num');
    f.quoteAmount.id = 'fwd-quote-amount';
    f.quoteEcho = h('div', { class: 'muted echo' });
    const amountField = (box, echo, id, tip) => {
      const text = h('span');
      const label = h('label', { title: tip }, text, ' ', h('span', { class: 'typedmark', title: 'İşlem bu tutarla girilir; öbürü forward kurundan hesaplanır' }, '✎ yazılan'));
      const el = h('div', { class: 'field amt', id }, label, h('div', null, box, echo));
      el.text = text;
      return el;
    };
    f.amountField = amountField(f.amount, f.amountEcho, 'fwd-amount-field', 'İşlemin tutarı paritenin ilk dövizinde (USDTRY\'de USD)');
    f.quoteField = amountField(f.quoteAmount, f.quoteEcho, 'fwd-quote-field',
      'Tutarı paritenin ikinci dövizinde yazın (USDTRY\'de TRY, EURUSD\'de USD): döviz tutarı işlemin forward kurundan hesaplanır, işlem yine dövizde kaydedilir');
    f.amountField.style.width = '180px';
    f.quoteField.style.width = '200px';
    for (const [box, side] of [[f.amount, 'base'], [f.quoteAmount, 'quote']]) {
      box.addEventListener('input', () => { f.typed = side; this.markTyped(); this.quoteFwd(); });
      box.addEventListener('keydown', (e) => { if (e.key === 'Enter') this.saveFwd(); });
    }
    // the pair: the two the workbook prices itself, or any other (typed) whose forward is entered by hand
    f.code = input('örn. GBP ya da GBPTRY');
    f.code.id = 'fwd-code';
    f.code.maxLength = 7;
    f.codeField = field('Döviz / parite', f.code, '170px');
    f.spot = input('örn. 63,2500', 'num');
    f.spot.id = 'fwd-spot';
    f.spotField = field('Spot (elle)', f.spot, '130px');
    f.pairSeg = seg(PAIRS, f.pair, (v) => { f.pair = v; this.layoutFwd(); if (v === 'OTHER') f.code.focus(); this.quoteFwd(); });
    f.pairSeg.id = 'fwd-pair';
    f.date = input('gg.aa.yyyy');
    f.date.id = 'fwd-date';
    f.date.title = 'Valör: tarih (15.12.2026) ya da kısayol - 1A / 3M ay, 1Y yıl, 2H / 2W hafta, ON, TN, SN, ay sonu, IMM, +5 iş günü '
      + '(paritenin spot valöründen, iki para biriminin tatilleriyle)';
    f.dateEcho = h('div', { class: 'muted echo', id: 'fwd-date-echo' });
    const picker = h('input', { type: 'date', class: 'datepick', tabindex: '-1', 'aria-label': 'Takvim' });
    picker.addEventListener('change', () => {
      if (picker.value) { f.date.value = isoToTr(picker.value); this.quoteFwd(); }
    });
    const cal = h('button', { class: 'btn sm', type: 'button', title: 'Takvimden seç' }, '📅');
    cal.addEventListener('click', () => { try { picker.showPicker(); } catch (e) { picker.focus(); } });
    f.manual = input('', 'num');
    f.manualField = field('TRY faizi (%)', f.manual, '160px');
    f.manualField.title = 'TRY faizi: basit ACT/360, %. Forward kur: outright. Swap puanı: (forward − spot) × 10.000 – forward = spot + puan / 10.000.';
    f.basisSeg = seg(FWD_BASES, f.basis, (v) => {
      f.basis = v;
      this.layoutFwd();
      if (MANUAL[v]) f.manual.focus();
      this.quoteFwd();
    });
    f.manualField.classList.add('hidden');
    f.cpt = input('opsiyonel');
    f.note = input('opsiyonel');
    f.quote = h('div', { class: 'quotebox' });
    f.save = h('button', { class: 'btn primary', type: 'button' }, 'İşlemi kaydet');
    f.save.addEventListener('click', () => this.saveFwd());
    f.cancel = this.cancelButton('fwd-edit-cancel');
    // (while a trade is edited, its counterparty / note alone is an edit of its own: the line over the quote says so)
    for (const el of [f.cpt, f.note]) el.addEventListener('input', () => { if (this.editing) this.quoteFwd(); });
    for (const el of [f.date, f.manual, f.code, f.spot]) {
      el.addEventListener('input', () => { if (el === f.code) this.layoutFwd(); this.quoteFwd(); });
      el.addEventListener('keydown', (e) => { if (e.key === 'Enter') this.saveFwd(); });
    }
    pane.appendChild(h('div', { class: 'row' }, field('Parite', f.pairSeg), f.codeField, f.spotField));
    pane.appendChild(h('div', { class: 'row' }, field('Yön', f.dirSeg),
      field('Valör', h('div', null, h('div', { class: 'daterow' }, f.date, cal, picker), f.dateEcho), '190px')));
    pane.appendChild(h('div', { class: 'row amounts' }, f.amountField, f.quoteField));
    pane.appendChild(h('div', { class: 'row' }, field('Fiyatlama', f.basisSeg), f.manualField));
    pane.appendChild(f.quote);
    pane.appendChild(h('div', { class: 'row' }, field('Karşı taraf', f.cpt, '150px'), field('Not', f.note, '240px')));
    pane.appendChild(h('div', { class: 'row actions' }, f.cancel, f.save));
    this.layoutFwd();
    this.markTyped();
    return pane;
  }

  /** "Vazgeç" beside a form's save button, while a trade is edited: out of the edit, the trade as it was. */
  cancelButton(id) {
    const b = h('button', { class: 'btn hidden', type: 'button', id, title: 'Düzenlemeden çık: işlem olduğu gibi kalır' }, 'Vazgeç');
    b.addEventListener('click', () => { this.endEdit(true); toast('Düzenleme bırakıldı: işlem olduğu gibi kaldı', 'ok', 2600); });
    return b;
  }

  /** Which of the two amounts was typed (``fwd.typed``): marked on the form - the other one is worked out. */
  markTyped() {
    const f = this.fwd;
    for (const [el, side] of [[f.amountField, 'base'], [f.quoteField, 'quote']]) {
      el.classList.toggle('typed', f.typed === side);
      el.classList.toggle('calc', f.typed !== side);
    }
  }

  /** The amount not typed, as the forward on screen makes it: the USD of a TRY amount to the desk's usual unit (whole
   * dollars; the cents in its tip), the TRY of a USD one to the kuruş.  ``q`` null: nothing to show. */
  showOtherSide(q, typed) {
    const f = this.fwd;
    if (typed !== f.typed) return;                 // typed in the other box meanwhile: that one is the typed one now
    const quote = typed === 'quote';
    const box = quote ? f.amount : f.quoteAmount;
    const echo = quote ? f.amountEcho : f.quoteEcho;
    if (!q || typeof q.amount !== 'number') {
      box.value = '';
      box.title = '';
      echo.textContent = '';
      return;
    }
    box.value = quote ? num(q.amount, 0) : num(q.tl, 2);
    box.title = quote ? num(q.amount, 2) + ' ' + q.base + ' = ' + num(q.tl, 2) + ' ' + q.quote + ' / ' + num(q.forward, 4) + ' (forward)'
      : num(q.amount, 0) + ' ' + q.base + ' × ' + num(q.forward, 4) + ' (forward) = ' + num(q.tl, 2) + ' ' + q.quote;
    echo.textContent = '= forward ' + num(q.forward, 4) + ' ile';
  }

  /** The pair being typed ("USDTRY", "EURTRY", or what stands in the box of "Diğer"; null while that is no pair). */
  fwdPair() {
    const f = this.fwd;
    return f.pair === 'OTHER' ? pairOf(f.code.value) : f.pair;
  }

  /** Labels and fields of the forward form follow the pair and the pricing choice. */
  layoutFwd() {
    const f = this.fwd;
    const other = f.pair === 'OTHER';
    const pair = this.fwdPair();
    const base = pair ? pair.slice(0, 3) : 'döviz';
    f.codeField.classList.toggle('hidden', !other);
    f.spotField.classList.toggle('hidden', !other);
    // a pair without a curve in the workbook is priced by hand: an outright, or points on a spot
    for (const b of f.basisSeg.children) b.classList.toggle('hidden', other && b.dataset.v !== 'FWD' && b.dataset.v !== 'SP');
    if (other && f.basis !== 'FWD' && f.basis !== 'SP') { f.basis = 'FWD'; f.basisSeg.set('FWD'); }
    f.dirSeg.children[0].textContent = 'Alış (' + base + ' al)';
    f.dirSeg.children[1].textContent = 'Satış (' + base + ' sat)';
    f.amountField.text.textContent = 'Tutar (' + base + ')';
    f.quoteField.text.textContent = pair ? 'Tutar (' + pair.slice(3) + ')' : 'Karşı tutar';
    const m = MANUAL[f.basis];
    f.manualField.classList.toggle('hidden', !m);
    if (m) {
      f.manualField.firstChild.textContent = m[0];
      f.manual.placeholder = m[1];
    }
  }

  /** What the form sends: the amount of the side typed only (``amount`` in the pair's first currency, or ``quote_amount``
   * in its second - the server works the other one out from the forward). */
  fwdPayload() {
    const f = this.fwd;
    const pair = this.fwdPair();
    const quote = f.typed === 'quote';
    const box = quote ? f.quoteAmount : f.amount;
    const amount = parseAmount(box.value);
    const ccy = pair ? (quote ? pair.slice(3) : pair.slice(0, 3)) : '';
    (quote ? f.quoteEcho : f.amountEcho).textContent = box.value.trim() ? (amount === null ? 'tutar anlaşılamadı' : num(amount, 0) + ' ' + ccy) : '';
    const pl = { pair, dir: f.dir, value_date: f.date.value.trim(), basis: f.basis,
      manual: MANUAL[f.basis] ? f.manual.value.trim() : null, spot: f.pair === 'OTHER' ? (f.spot.value.trim() || null) : null,
      cpt: f.cpt.value.trim(), note: f.note.value.trim() };
    if (quote) pl.quote_amount = amount; else pl.amount = amount;
    return pl;
  }

  async doQuoteFwd() {
    const f = this.fwd;
    if (!f.quote || this.dead) return;
    const pl = this.fwdPayload();
    const typed = f.typed;
    f.ticket = (f.ticket || 0) + 1;                 // whatever is still on its way belongs to what was typed before
    f.dateEcho.textContent = '';                    // (what a shortcut became: said again by the answer)
    const waiting = (text) => { clear(f.quote); f.quote.appendChild(h('div', { class: 'muted' }, text)); this.showOtherSide(null, typed); };
    if (!pl.pair) { waiting('Dövizi ya da pariteyi yazın (örn. GBP, CHFTRY, EURUSD).'); return; }
    if (!pl.value_date) { waiting('Valör tarihini yazın; forward ve TL tutarı otomatik hesaplanır.'); return; }
    if (MANUAL[pl.basis] && !pl.manual) {
      waiting(pl.basis === 'TRY' ? 'TRY faizini yazın.' : (pl.basis === 'SP' ? 'Swap puanını yazın.' : 'Forward kuru yazın.'));
      return;
    }
    const ticket = f.ticket;
    try {
      const { q, edit } = await this.quoteOf('fwd', '/api/blotter/quote/forward', pl);
      if (ticket !== f.ticket || this.dead) return;
      // a value date typed as a shortcut ("3A", "ay sonu", "IMM", "+5"): the date it is, under the box
      f.dateEcho.textContent = q.value_date_typed ? q.value_date_typed + ' → ' + serialDate(q.value_date) : '';
      clear(f.quote);
      this.showOtherSide(q, typed);
      const base = q.base, vsTry = q.quote === 'TRY';
      const dash = (v, fn) => (typeof v === 'number' ? fn(v) : '—');
      const tiles = h('div', { class: 'quote' });
      const total = tile(vsTry ? 'TL tutarı' : 'Karşı tutar (' + q.quote + ')', typeof q.tl === 'number' ? num(q.tl, 2) : '— tutar girin —', true, typeof q.tl === 'number' ? raw(q.tl) : '');
      total.dataset.k = 'fwd-total';
      if (q.typed === 'quote') {
        total.classList.add('typed');               // the amount typed: the USD follows from it
        total.title = 'Yazılan tutar: ' + num(q.tl, 2) + ' ' + q.quote + ' · ' + num(q.amount, 2) + ' ' + base + ' forward kurundan';
      }
      tiles.appendChild(total);
      const fw = tile('Forward kur', num(q.forward, 4), false, raw(q.forward));
      fw.dataset.k = 'fwd-forward';
      tiles.appendChild(fw);
      tiles.appendChild(tile('TRY faizi', dash(q.try_rate, (v) => pct(v, 3)), false, typeof q.try_rate === 'number' ? raw(q.try_rate)
        : 'Bu paritenin döviz faizi çalışma kitabında yok: ima TRY faizi hesaplanmaz'));
      tiles.appendChild(tile('Gün', num(q.days, 0)));
      tiles.appendChild(tile('Spot', dash(q.spot, (v) => num(v, 4)), false, typeof q.spot === 'number' ? raw(q.spot) : 'Spot yazılmadı'));
      tiles.appendChild(tile(base + ' faizi', dash(q.usd_rate, (v) => pct(v, 3))));
      const sp = tile('Swap puanı', dash(q.points, (v) => num(v, 0)));
      sp.dataset.k = 'fwd-points';
      tiles.appendChild(sp);
      tiles.appendChild(tile('Valör', serialDate(q.value_date)));
      // risk of the trade being typed (per 1 mn until an amount is there): the sheet's "Forward DV01" block
      const d1 = q.dv01 || {};
      const per = typeof q.amount === 'number' ? '' : ' / 1mn ' + base;
      const t1 = tile('DV01 (TL)' + per, signed(d1.tl, 0), false, DV01_HINT);
      const t2 = tile('DV01 ($)' + per, signed(d1.usd, 0), false, DV01_HINT);
      t1.dataset.k = 'dv01-tl';
      t2.dataset.k = 'dv01-usd';
      tiles.appendChild(t1);
      tiles.appendChild(t2);
      tiles.appendChild(tile(base + ' faizi DV01 (' + (base === 'USD' ? '$' : base) + ')' + per, signed(d1.usd_leg, 0), false, base + ' faizi +1 bp olursa kâr / zarar'));
      f.quote.appendChild(tiles);
      f.quote.appendChild(this.copyLine(() => q.pair + ' ' + (pl.dir === 'B' ? 'ALIŞ ' : (pl.dir === 'S' ? 'SATIŞ ' : '')) + (typeof q.amount === 'number' ? num(q.amount, 0) + ' ' + base : base)
        + ' · valör ' + serialDate(q.value_date) + ' (' + num(q.days, 0) + ' gün) · forward ' + num(q.forward, 4)
        + (typeof q.spot === 'number' ? ' · spot ' + num(q.spot, 4) + ' · swap puanı ' + num(q.points, 0) : '')
        + (typeof q.try_rate === 'number' ? ' · TRY faizi ' + pct(q.try_rate, 2) : '')
        + (typeof q.tl === 'number' ? ' · ' + (vsTry ? 'TL tutarı ' : q.quote + ' tutarı ') + num(q.tl, 2) : '')));
      const rows = [];
      for (const k of ['RET', 'OIS', 'ICAP', 'VIOP', 'BBG']) {
        const t = q.table[k];
        if (t && (typeof t.bid === 'number' || typeof t.ask === 'number')) rows.push([k, n(t.bid, 4), n(t.mid, 4), n(t.ask, 4)]);
      }
      if (typeof q.ret_bid === 'number' && q.table.RET) rows.push(['RET faizi', p(q.ret_bid, 3), p(q.ret_mid, 3), p(q.ret_ask, 3)]);
      if (rows.length) {
        const g = new Grid({ data: plainData(['Eğri', 'Bid', 'Mid', 'Ask'], rows), editable: false });
        f.quote.appendChild(h('div', { class: 'reftable' }, g.el));
      } else if (q.pair !== 'USDTRY' && q.pair !== 'EURTRY') {
        f.quote.appendChild(h('div', { class: 'muted', style: { marginTop: '8px' } }, q.pair + ' için çalışma kitabında eğri yok: forward yazdığınız kur'
          + (typeof q.spot_market === 'number' ? ' (Bloomberg spotu ' + num(q.spot_market, 4) + ')' : '') + '. İma TRY faizi hesaplanmaz; TRY faizi DV01\'i valöre kadarki TRY iskonto faktörüyle verilir.'));
      }
      this.pricingLine(f.quote, edit);
    } catch (err) {
      if (ticket !== f.ticket) return;
      clear(f.quote);
      f.quote.appendChild(h('div', { class: 'errtxt' }, err.message));
      this.showOtherSide(null, typed);
    }
  }

  async saveFwd() {
    const f = this.fwd;
    const pl = this.fwdPayload();
    const quote = f.typed === 'quote';
    const amount = quote ? pl.quote_amount : pl.amount;
    if (!pl.pair) { toast('Dövizi ya da pariteyi yazın (örn. GBP)', 'err'); f.code.focus(); return; }
    if (!pl.dir) { toast('Yönü seçin: alış ya da satış', 'err'); return; }
    if (amount === null || !(amount > 0)) { toast('Tutar girin (örn. 10m)', 'err'); (quote ? f.quoteAmount : f.amount).focus(); return; }
    if (!pl.value_date) { toast('Valör tarihini girin', 'err'); f.date.focus(); return; }
    if (this.editing && this.editing.kind === 'fwd') { await this.saveEdit('fwd', pl, f.save); return; }
    f.save.disabled = true;
    try {
      const rec = await api.post('/api/blotter/forward', pl);
      toast(rec.pair + ' ' + (rec.dir === 'B' ? 'alış ' : 'satış ') + num(rec.amount, 0) + ' ' + rec.pair.slice(0, 3) + ' · ' + serialDate(rec.value_date) + ' · '
        + num(rec.forward, 4) + ' → ' + num(rec.tl, 2) + ' ' + rec.pair.slice(3) + (rec.typed === 'quote' ? ' (yazılan)' : '') + ' kaydedildi', 'ok', 4200);
      for (const el of [f.amount, f.quoteAmount]) { el.value = ''; el.title = ''; }
      f.amountEcho.textContent = '';
      f.quoteEcho.textContent = '';
      f.note.value = '';
      if (this.copied && this.copied.kind === 'fwd') this.markCopied(null);       // (the copy is saved: a trade of its own)
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

  /** The dates a meeting-dated swap can start or end on: OIS spot (a start only) and the day after every decision. */
  mpcSelect(withSpot, value) {
    const s = h('select', { class: 'inp' });
    const m = (this.market && this.market.mpc) || { dates: [] };
    if (withSpot && typeof m.spot === 'number') s.appendChild(h('option', { value: String(m.spot) }, 'Spot · ' + m.spot_text));
    for (const d of m.dates) s.appendChild(h('option', { value: String(d.date) }, 'MPC' + d.k + ' · ' + d.text));
    const pick = m.dates[value];
    if (pick) s.value = String(pick.date);
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
      o.size.value = '';
      this.setSizeMode(v);
      this.quoteOis();
    });
    this.setSizeMode(o.sizeMode);
    o.adv = h('div', { class: 'row adv' });
    o.cpt = input('opsiyonel');
    o.note = input('opsiyonel');
    o.quote = h('div', { class: 'quotebox' });
    o.save = h('button', { class: 'btn primary', type: 'button' }, 'İşlemi kaydet');
    o.save.addEventListener('click', () => this.saveOis());
    o.cancel = this.cancelButton('ois-edit-cancel');
    for (const el of [o.cpt, o.note]) el.addEventListener('input', () => { if (this.editing) this.quoteOis(); });
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
    pane.appendChild(h('div', { class: 'row actions' }, o.cancel, o.save));
    this.layoutOis();
    return pane;
  }

  /** The OIS size as DV01 ($/bp) or as a TL nominal. */
  setSizeMode(v) {
    const o = this.ois;
    o.sizeMode = v;
    o.sizeSeg.set(v);
    o.size.placeholder = v === 'dv01' ? (this.market && this.market.dv01 ? 'varsayılan ' + num(this.market.dv01, 0) : 'örn. 5000') : 'örn. 500m';
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
    } else if (st === 'mpc') {
      // one swap between two dates, paid at its end: from a meeting's effective day (or spot) to a later meeting's
      o.f.start = this.mpcSelect(true, 0);
      o.f.end = this.mpcSelect(false, 1);
      o.f.start.id = 'ois-mpc-start';
      o.f.end.id = 'ois-mpc-end';
      o.legsHost.appendChild(field('Başlangıç', o.f.start, '170px'));
      o.legsHost.appendChild(field('Bitiş', o.f.end, '170px'));
    } else {
      o.f.start_months = this.monthSelect(0, 117, 3);
      o.f.end_months = this.monthSelect(3, 120, 6);
      o.legsHost.appendChild(field('Başlangıç', o.f.start_months, '110px'));
      o.legsHost.appendChild(field('Bitiş', o.f.end_months, '110px'));
      o.f.start_rate = rate('Başlangıç bacağı oranı (%)');
    }
    // a leg's own rate an edit filled in is that tenor's: another tenor chosen for the leg, the market's again
    for (const [k, sel] of LEG_RATES) {
      if (!o.f[k] || !o.f[sel]) continue;
      o.f[sel].addEventListener('change', () => {
        const ed = this.editing;
        if (ed && ed.rates[k] !== undefined && o.f[k].value === ed.rates[k]) o.f[k].value = '';
      });
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
      if (k === 'start_months' || k === 'end_months') pl[k] = isDateText(v) ? v : Number(v);     // (a FRA's broken date: its day)
      else if (k === 'start' || k === 'end') pl[k] = Number(v);
      else if (v) pl[k] = v;
    }
    const size = parseAmount(o.size.value);
    o.sizeEcho.textContent = o.size.value.trim() ? (size === null ? 'anlaşılamadı' : num(size, 0) + (o.sizeMode === 'dv01' ? ' $/bp' : ' TL')) : '';
    if (size !== null && size > 0) pl[o.sizeMode] = size;
    // an edit's size given back as it was filled in: the trade's own (a spread sized by DV01 cannot say its legs' nominals)
    const ed = this.editing;
    if (ed && ed.kind === 'ois' && ed.size && o.size.value === ed.size.text && o.sizeMode === ed.size.mode) pl.keep_size = true;
    return pl;
  }

  levelText(v, st) {
    if (typeof v !== 'number') return '—';
    return (st === 'spread' || st === 'fly') ? num(v, 2) + ' bp' : pct(v, 4);
  }

  /** An FRA's second view (the quote's ``market_ppk``): the mid on the PPK step curve beside the market hint. */
  ppkHint(q, st) {
    if (typeof q.info.market_ppk !== 'number') return;
    const span = h('span', { class: 'muted', id: 'blotter-ppk-hint' }, ' · PPK basamak mid: ' + this.levelText(q.info.market_ppk, st));
    span.title = PPK_HINT;
    this.ois.marketHint.appendChild(span);
  }

  /** Its tiles, after the quote's own: the PPK step mid and the trade against it (+ better than that mid, − worse). */
  ppkTiles(tiles, q, st) {
    if (typeof q.info.market_ppk !== 'number') return;
    const mid = tile('Piyasa mid · PPK basamak', this.levelText(q.info.market_ppk, st), false, PPK_HINT);
    mid.dataset.k = 'ppk-mid';
    tiles.appendChild(mid);
    const vs = typeof q.info.cost_bp_ppk === 'number' ? -q.info.cost_bp_ppk : null;
    const t = tile("Mid'e göre · PPK (bp)", vs === null ? '—' : signed(vs, 2), false,
      "İşlem PPK basamak mid'ine göre: + mid'den iyi (lehine), − mid'den kötü (aleyhine)");
    t.dataset.k = 'ppk-vs-mid';
    if (vs !== null && vs !== 0) t.classList.add(vs > 0 ? 'costneg' : 'costpos');
    tiles.appendChild(t);
  }

  async doQuoteOis() {
    const o = this.ois;
    if (!o.quote || this.dead) return;
    const pl = this.oisPayload();
    const hasLevel = !!pl.level;
    if (!hasLevel) pl.level = '0';
    const ticket = (o.ticket = (o.ticket || 0) + 1);
    if (!pl.side) {                       // (a price filled without its side: the user chooses it first)
      clear(o.marketHint);                // (the last quote's market was another trade's)
      clear(o.quote);
      o.quote.appendChild(h('div', { class: 'muted' }, 'Yönü seçin (' + SIDES[o.strategy].map((x) => x[1]).join(' / ') + '): bacaklar ve maliyet yöne göre hesaplanır.'));
      return;
    }
    try {
      const { q, edit } = await this.quoteOf('ois', '/api/blotter/quote/ois', pl);
      if (ticket !== o.ticket || this.dead) return;
      const st = q.strategy;
      const bp = st === 'spread' || st === 'fly';
      // an edit that keeps the instrument counts against the mid at the trade, not today's
      const midLabel = edit && edit.priced !== 'today' ? 'Mid (işlem anı)' : 'Piyasa mid';
      clear(o.marketHint);
      if (typeof q.info.market === 'number') {
        const use = h('button', { class: 'btn sm ghost', type: 'button' }, 'kullan');
        use.addEventListener('click', () => {
          o.level.value = bp ? num(q.info.market, 2, false) : num(q.info.market * 100, 4, false);
          this.quoteOis();
        });
        o.marketHint.appendChild(h('span', null, midLabel + ': ' + this.levelText(q.info.market, st) + ' '));
        o.marketHint.appendChild(use);
      }
      this.ppkHint(q, st);
      clear(o.quote);
      if (!hasLevel) {
        o.quote.appendChild(h('div', { class: 'muted' }, bp ? 'Seviyeyi (bp) yazın; bacaklar ve maliyet otomatik hesaplanır.'
          : 'Oranı yazın; bacaklar ve maliyet otomatik hesaplanır.'));
        this.pricingLine(o.quote, edit);
        return;
      }
      const tiles = h('div', { class: 'quote' });
      // the trade against mid as the desk reads it: + better than mid (in its favour, green), − worse (red)
      for (const [key, label, cost, digits, unit] of [['bp', 'Mid\'e göre (bp)', q.info.cost_bp, 2, ' bp'],
        ['usd', 'Mid\'e göre ($)', q.info.cost_usd, 0, ''], ['tl', 'Mid\'e göre (TL)', q.info.cost_tl, 0, '']]) {
        const v = vsShown(vsMid(cost), digits);
        const el = tile(label, v === null ? '—' : signed(v, digits) + unit, key === 'bp', VS_MID_HINT);
        el.dataset.k = 'vs-mid-' + key;
        if (v) el.classList.add(v > 0 ? 'costpos' : 'costneg');
        tiles.appendChild(el);
      }
      tiles.appendChild(tile('İşlem seviyesi', this.levelText(q.level, st)));
      tiles.appendChild(tile(midLabel, this.levelText(q.info.market, st)));
      const od = q.dv01 || {};
      const n1 = tile('Net DV01 ($)', signed(od.net, 0), false, DV01_HINT);
      n1.dataset.k = 'dv01-net';
      tiles.appendChild(n1);
      if (q.legs.length > 1) tiles.appendChild(tile('Brüt DV01 ($)', typeof od.gross === 'number' ? num(od.gross, 0) : '—', false, 'Bacakların DV01 toplamı (işaretsiz)'));
      this.ppkTiles(tiles, q, st);
      o.quote.appendChild(tiles);
      const rows = q.legs.map((lg) => [ROLE[lg.role] || lg.role,
        { t: lg.dir === 'S' ? 'RECEIVE' : 'PAY', k: 's', cls: lg.dir === 'S' ? 'buy' : 'sell' }, lg.tenor,
        p(lg.rate, 4), n(lg.nominal, 0), dv(payerPlus(lg))]);
      const g = new Grid({ data: plainData(['Bacak', 'Yön', 'Vade', 'Oran', 'Nominal (TL)', 'DV01 ($)'], rows), editable: false });
      o.quote.appendChild(h('div', { class: 'reftable' }, g.el));
      o.quote.appendChild(h('div', { class: 'muted', style: { marginTop: '6px' } }, q.label));
      o.quote.appendChild(this.copyLine(() => q.label + ' · ' + q.legs.map((lg) => (lg.dir === 'S' ? 'REC ' : 'PAY ') + lg.tenor + ' ' + pct(lg.rate, 4)
        + ' ' + num(lg.nominal, 0) + ' TL (DV01 ' + signed(payerPlus(lg), 0) + ' $)').join(' / ')));
      this.pricingLine(o.quote, edit);
    } catch (err) {
      if (ticket !== o.ticket) return;
      clear(o.quote);
      o.quote.appendChild(h('div', { class: 'errtxt' }, err.message));
    }
  }

  async saveOis() {
    const o = this.ois;
    const pl = this.oisPayload();
    if (!pl.side) { toast('Yönü seçin: ' + SIDES[o.strategy].map((x) => x[1]).join(' ya da '), 'err'); return; }
    if (!pl.level) { toast('Seviye girin', 'err'); o.level.focus(); return; }
    if (this.editing && this.editing.kind === 'ois') { await this.saveEdit('ois', pl, o.save); return; }
    o.save.disabled = true;
    try {
      const q = await api.post('/api/blotter/ois', pl);
      toast(q.label + ' kaydedildi (' + q.legs.length + ' bacak)', 'ok', 4200);
      o.level.value = '';
      o.note.value = '';
      if (this.copied && this.copied.kind === 'ois') this.markCopied(null);
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
    for (const el of [b.price, b.note]) el.addEventListener('input', () => { if (this.editing) this.quoteBond(); });   // (an edit's line)
    for (const el of [b.inst, b.amount, b.price]) el.addEventListener('keydown', (e) => { if (e.key === 'Enter') this.saveBond(); });
    b.save = h('button', { class: 'btn primary', type: 'button' }, 'İşlemi kaydet');
    b.save.addEventListener('click', () => this.saveBond());
    b.cancel = this.cancelButton('bond-edit-cancel');
    pane.appendChild(h('div', { class: 'row' }, field('Yön', b.dirSeg), field('Enstrüman', b.inst, '200px')));
    pane.appendChild(h('div', { class: 'row' }, field('Tutar', h('div', null, b.amount, b.amountEcho), '190px'), field('Fiyat', b.price, '130px')));
    pane.appendChild(b.quote);
    pane.appendChild(h('div', { class: 'row' }, field('Not', b.note, '330px')));
    pane.appendChild(h('div', { class: 'row actions' }, b.cancel, b.save));
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
      const { q, edit } = await this.quoteOf('bond', '/api/blotter/quote/bond', this.bondPayload());
      if (ticket !== b.ticket || this.dead) return;
      clear(b.quote);
      if (!q.known) {
        b.quote.appendChild(h('div', { class: 'muted' }, 'Bu enstrüman DİBS RV tablosunda yok: işlem kaydedilir, DV01 hesaplanamaz.'));
        this.pricingLine(b.quote, edit);
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
      this.pricingLine(b.quote, edit);
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

  /** What the bond form sends: the instrument, the side, the amount (as read), the price and the note. */
  bondPayload() {
    const b = this.bond;
    return { instrument: b.inst.value.trim(), dir: b.dir, amount: parseAmount(b.amount.value), price: b.price.value.trim(), note: b.note.value.trim() };
  }

  async saveBond() {
    const b = this.bond;
    const pl = this.bondPayload();
    const amount = pl.amount;
    if (!pl.instrument) { toast('Enstrüman girin', 'err'); b.inst.focus(); return; }
    if (!b.dir) { toast('Yönü seçin: alış ya da satış', 'err'); return; }
    if (amount === null || !(amount > 0)) { toast('Tutar girin', 'err'); b.amount.focus(); return; }
    if (this.editing && this.editing.kind === 'bond') { await this.saveEdit('bond', pl, b.save); return; }
    b.save.disabled = true;
    try {
      await api.post('/api/blotter/bond', pl);
      toast('Tahvil işlemi kaydedildi', 'ok');
      b.amount.value = '';
      b.amountEcho.textContent = '';
      b.note.value = '';
      if (this.copied && this.copied.kind === 'bond') this.markCopied(null);
      this.quoteBond();
      this.ctx.refreshNow();
    } catch (err) { errorToast(err); } finally { b.save.disabled = false; }
  }

  // ------------------------------------------------------------------ lists
  who(t) {
    return this.users[t.created_by] || t.created_by || '';
  }

  /** What can be done to a trade of the list: today's - "Düzenle" (the form filled with it: ``startEdit``) and ✕; a day
   * gone by's - "Düzenle" for its counterparty and note alone (``editFields``); wherever the form is open, every trade's
   * "Benzerini gir" and "Ters işlem" (``copyFrom``; one that makes no sense for the trade left out, the cell's tip says
   * why). */
  actCell(t, what) {
    const copy = this.copyActs(t, what);
    const tip = copy.why.length ? copy.why.join('\n') : undefined;
    if (t.trade_date !== this.data.today) {
      return { t: '', k: '', cls: 'act', tip, act: [{ id: 'edit', label: 'Düzenle', title: 'Karşı taraf / not: geçmiş günün işleminde yalnızca bunlar değişir',
        fn: () => this.editFields(t) }].concat(copy.act) };
    }
    if (!this.data.can_enter) return { t: '', k: '' };
    return { t: '', k: '', cls: 'act', tip, act: [
      { id: 'edit', label: 'Düzenle', title: 'İşlemi düzenle: form işlemin değerleriyle dolar, "Değişikliği kaydet" aynı kaydı değiştirir',
        fn: () => this.startEdit(t) },
      { id: 'del', label: '✕', title: 'İşlemi sil', fn: () => this.remove(t, what) }].concat(copy.act) };
  }

  /** When a trade was entered, in a list - marked (✎) when it was changed after that, the change in its tip: when, by
   * whom, how many times, what it was before the last change. */
  timeCell(t) {
    const cell = { t: timeOf(t.created_at), k: 's' };
    const edits = Array.isArray(t.edits) ? t.edits : [];
    if (!edits.length) return cell;
    const last = edits[edits.length - 1];
    const was = last.was || {};
    const shown = (v, fmt) => (v === null || v === undefined || v === '' ? '—' : (fmt ? fmt(v) : String(v)));
    const before = (EDIT_FIELDS[t.kind] || []).filter(([k]) => Object.prototype.hasOwnProperty.call(was, k))
      .map(([k, label, fmt]) => label + ' ' + shown(was[k], fmt));
    const tip = ['Düzenlendi: ' + timeOf(last.at) + ' · ' + (this.users[last.by] || last.by || '') + (edits.length > 1 ? ' (' + edits.length + '. düzenleme)' : ''),
      'Girildi: ' + timeOf(t.created_at) + ' · ' + this.who(t)];
    const priced = { today: 'Bugünkü piyasayla yeniden fiyatlandı' + (last.why && last.why.length ? ' (' + last.why.join(', ') + ' değişti)' : ''),
      trade: 'İşlemin kendi fiyatlarıyla (kur / mid işlem anındaki)', none: 'Yalnızca karşı taraf / not' }[last.priced];
    if (priced) tip.push(priced);
    if (before.length) tip.push('Önceki: ' + before.join(' · '));
    return Object.assign(cell, { cls: 'edited', tip: tip.join('\n') });
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
      sec.body.appendChild(h('div', { class: 'empty' }, this.data.can_enter ? (this.data.ranged ? 'Bu aralıkta kayıt yok – bugünün işlemini soldaki formdan girin'
        : 'Henüz işlem yok – soldaki formdan girin') : (this.data.ranged ? 'Bu aralıkta kayıt yok' : 'Kayıt yok')));
      return;
    }
    if (this.grids[id]) {
      this.grids[id].replace(data);
    } else {
      clear(sec.body);
      this.grids[id] = new Grid({ data, editable: false, name: 'blotter/' + id, tools: toolsOf(sec.body) });
      sec.body.appendChild(this.grids[id].el);
    }
  }

  /** One click on a template: the form filled with it, waiting for "İşlemi kaydet" (nothing is saved). */
  applyTemplate(t) {
    this.endEdit(true);                    // a template is a new trade: an edit in progress is left, the trade as it was
    this.markCopied(null);
    const done = this.fillForm(t.spec);
    if (!done) { toast('Bu şablon formu dolduramıyor', 'err'); return; }
    toast('Şablon: ' + t.name + ' – form dolduruldu, kontrol edip kaydedin' + (done.warn ? ' (' + done.warn + ')' : ''), done.warn ? 'warn' : 'ok',
      done.warn ? 6000 : 2600);
  }

  fill() {
    const d = this.data;
    renderTemplates(this);
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
      ? 'Aralık: ' + isoToTr(d.date) + ' – ' + isoToTr(d.to) + ' · ' + (d.days || 0) + ' işlem günü, ' + d.trades.length + ' kayıt'
        + (d.can_enter ? ' – soldaki formdan girilen işlem bugüne (' + isoToTr(d.today) + ') yazılır ve listeye eklenir. ' : ' – yalnızca görüntüleme. ')
        + 'Maliyet ve DV01 bu aralıktaki işlemlerin toplamıdır.'
      : 'Geçmiş gün – yalnızca görüntüleme' + (d.snapshot_at ? ' (özet: ' + d.snapshot_at + ')' : ''));
    this.dayNote.classList.toggle('hidden', d.is_today);
    if (this.editing && !d.trades.some((t) => t.id === this.editing.id)) {      // deleted meanwhile (by anyone)
      this.endEdit(true);
      toast('Düzenlenen işlem silindi: düzenleme bırakıldı', 'warn', 5000);
    }
    this.entry.classList.toggle('hidden', !d.can_enter);
    this.readonlyNote.classList.toggle('hidden', !!d.can_enter);

    // risk of what is listed
    const r = d.risk || {};
    clear(this.riskBar);
    const rt = (label, v, key, title) => {
      const el = tile(label, signed(v, 0), key === 'total', title || DV01_HINT);
      el.dataset.k = 'risk-' + key;
      if (typeof v === 'number' && v !== 0) el.classList.add(v > 0 ? 'pos' : 'neg');
      return el;
    };
    this.riskBar.appendChild(h('div', { class: 'l', title: DV01_HINT }, 'DV01 · TRY faizi +1 bp ($) · payer +'));
    this.riskBar.appendChild(rt('Toplam', r.total, 'total'));
    this.riskBar.appendChild(rt('Forward', r.fwd, 'fwd', DV01_HINT + ' TL karşılığı: ' + signed(r.fwd_tl, 0)));
    this.riskBar.appendChild(rt('OIS (net)', r.ois, 'ois', DV01_HINT + ' Brüt: ' + (typeof r.ois_gross === 'number' ? num(r.ois_gross, 0) : '—')));
    this.riskBar.appendChild(rt('Tahvil', r.bond, 'bond', DV01_HINT + ' TL karşılığı: ' + signed(r.bond_tl, 0)));
    if (r.unknown) this.riskBar.appendChild(h('div', { class: 'muted warn' }, r.unknown + ' işlemin DV01\'i bilinmiyor (DİBS RV tablosunda olmayan tahvil ya da TRY\'ye karşı olmayan forward)'));
    this.riskBar.classList.toggle('hidden', !d.trades.length);

    // in a period every row says which day it belongs to
    const day = (t) => (d.ranged ? [{ t: isoToTr(t.trade_date), k: 's' }] : []);
    const dayHead = d.ranged ? ['Tarih'] : [];

    const fw = d.trades.filter((t) => t.kind === 'fwd');
    // "O/N" is column F of the workbook's blotter sheet: the overnight equivalent of the trade's TRY rate
    const pairOfTrade = (t) => t.pair || 'USDTRY';
    this.setGrid('fwd', dayHead.concat(['Saat', 'Kullanıcı', 'Parite', 'Yön', 'Tutar (döviz)', 'Valör', 'Gün', 'TRY faizi', 'O/N', 'Forward', 'Swap puanı', 'Karşı tutar',
      'DV01 (TL)', 'DV01 ($)', 'Fiyatlama', 'Karşı taraf', 'Not', '']),
      fw.map((t) => day(t).concat([this.timeCell(t), this.who(t), { t: pairOfTrade(t), k: 's', b: 1 },
        { t: t.dir === 'B' ? 'ALIŞ' : 'SATIŞ', k: 's', cls: t.dir === 'B' ? 'buy' : 'sell' },
        typedCell(t, 'base'), { t: serialDate(t.value_date), v: t.value_date, k: 'd' }, n(t.days, 0), p(t.try_rate, 3), p(t.on_rate, 2), n(t.forward, 4), n(t.points, 0),
        typedCell(t, 'quote'), dv(t.dv01_tl), dv(t.dv01), BASIS_LABEL[t.basis] || t.basis, t.cpt || '', t.note || '',
        this.actCell(t, pairOfTrade(t) + ' ' + (t.dir === 'B' ? 'alış ' : 'satış ') + num(t.amount, 0) + ' ' + pairOfTrade(t).slice(0, 3) + ' · ' + serialDate(t.value_date))])),
      fw.length ? fw.length + ' işlem' : '');

    const os = d.trades.filter((t) => t.kind === 'ois');
    const seenPkg = new Set();
    // the trade against mid (+ better than mid): the stored cost turned round, on a package's first leg
    this.setGrid('ois', dayHead.concat(['Saat', 'Kullanıcı', 'İşlem', 'Bacak', 'Yön', 'Vade', 'Oran', 'Nominal (TL)', 'DV01 ($)',
      { t: 'Mid\'e göre (bp)', tip: VS_MID_HINT }, { t: 'Mid\'e göre ($)', tip: VS_MID_HINT }, 'Karşı taraf', 'Not', '']),
      os.map((t) => {
        const first = !t.package || !seenPkg.has(t.package);
        if (t.package) seenPkg.add(t.package);
        return day(t).concat([this.timeCell(t), this.who(t), first ? (t.label || '') : '', ROLE[t.role] || t.role || '',
          { t: t.dir === 'S' ? 'RECEIVE' : 'PAY', k: 's', cls: t.dir === 'S' ? 'buy' : 'sell' }, t.tenor, p(t.rate, 4), n(t.nominal, 0), dv(payerPlus(t)),
          first ? vsCell(vsMid(t.cost_bp), 2) : { t: '', k: '' }, first ? vsCell(vsMid(t.cost_usd), 0) : { t: '', k: '' }, t.cpt || '', first ? (t.note || '') : '',
          first ? this.actCell(t, t.label || 'OIS işlemi') : { t: '', k: '' }]);
      }), os.length ? os.length + ' bacak' : '');

    const bd = d.trades.filter((t) => t.kind === 'bond');
    this.setGrid('bond', dayHead.concat(['Saat', 'Kullanıcı', 'Enstrüman', 'Yön', 'Tutar', 'Fiyat', 'DV01 (TL)', 'DV01 ($)', 'Not', '']),
      bd.map((t) => day(t).concat([this.timeCell(t), this.who(t), t.instrument, { t: t.amount >= 0 ? 'ALIŞ' : 'SATIŞ', k: 's', cls: t.amount >= 0 ? 'buy' : 'sell' },
        n(Math.abs(t.amount), 0), n(t.price, 4), dv(t.dv01_tl), dv(t.dv01), t.note || '', this.actCell(t, t.instrument + ' ' + num(Math.abs(t.amount), 0))])),
      bd.length ? bd.length + ' işlem' : '');

    const c = d.cost || { fwd: [], ois: [], bond: [] };
    this.setGrid('cfwd', ['Parite', 'Valör', 'Alış (döviz)', 'Ort. alış kuru', 'Satış (döviz)', 'Ort. satış kuru', 'Net (döviz)', 'Maliyet (kur)', 'Gerçekleşen K/Z'],
      c.fwd.map((x) => [{ t: x.pair || 'USDTRY', k: 's', b: 1 }, { t: serialDate(x.key), v: x.key, k: 'd' }, n(x.buy, 0), n(x.buy_avg, 4), n(x.sell, 0), n(x.sell_avg, 4),
        n(x.net, 0), n(x.cost, 4), n(x.realised, 2)]));
    this.setGrid('cois', ['Vade', 'Pay DV01 ($)', 'Ort. pay', 'Receive DV01 ($)', 'Ort. receive', 'Net DV01 ($)', 'Maliyet', 'Gerçekleşen K/Z ($)'],
      c.ois.map((x) => [x.key, n(x.buy, 0), p(x.buy_avg, 4), n(x.sell, 0), p(x.sell_avg, 4), dv(x.net), p(x.cost, 4), n(x.realised, 0)]));
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
          const g = new Grid({ book: 'tto', data: s.data, editable: false, name: 'blotter/sheet/' + s.id, tools });
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
    const others = d.trades.filter((t) => t.kind === 'fwd' && (t.pair || 'USDTRY') !== 'USDTRY').length;
    const mpc = d.trades.filter((t) => t.kind === 'ois' && t.mpc).length;
    const parts = [];
    if (others) parts.push(others + ' forward başka paritede: tutarı işlem anındaki kurlarla USD karşılığı, faizi kendi TRY faizi (TL maliyeti)');
    if (mpc) parts.push(mpc + ' MPC tarihli OIS ana vadelere dağıtıldı: bitişe kadar olan swap ile ters yöndeki başlangıca kadar olan swap, '
      + 'her biri tarihinin iki yanındaki ana vadeye gün oranında (DV01\'leriyle)');
    this.sheetNote.textContent = parts.length ? 'Tablolarda: ' + parts.join(' · ') + '.' : '';
    this.sheetNote.classList.toggle('hidden', !parts.length || !sheet.length);
    this.sheetTitle.classList.toggle('hidden', !sheet.length);
    this.sheetScope.textContent = d.sheet_scope || '';
    this.sheetScope.classList.toggle('hidden', !d.sheet_scope || !sheet.length);
    // (the sheet explorer shows the sheet itself - today's: not a period's tables)
    this.sheetLink.classList.toggle('hidden', !sheet.length || !!d.sheet_scope);
    if (this.position) this.position.refresh();
  }
}

export { settings };
// (what is typed - a pair, an amount - is read in format.js: the Ctrl+K commands read it the same way)
export { pairOf, parseAmount };
