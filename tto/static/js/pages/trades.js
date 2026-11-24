// Trades: the desk's trades (Masa) and each trader's own (Kişisel), apart from the desk's position.  Entered here with
// their trade date, settle date and trade price; valued only when asked ("MTM yenile"), with the daily, weekly and total
// P&L each split into carry and price effect.  The server reads the form, says each trade in the desk's words and works
// out every number (tto/tradebook.py); this page shows them.  A trader's own trades never leave the server for anyone
// else.  Nothing here is live: the lists come again when they change (the live stream's counter), the values when
// "MTM yenile" is clicked.
import { api } from '../api.js';
import { h, clear, toast, errorToast, confirmDialog, modal, debounce } from '../ui.js';
import { num, isoToTr, settings } from '../format.js';

const PRODUCTS = [['ois', 'TRY OIS'], ['sofr', 'SOFR'], ['dibs', 'DİBS'], ['fxspot', 'FX spot'], ['fxopt', 'FX opsiyon']];
const STRUCTURES = [['outright', 'Outright'], ['mpc', 'PPK / FOMC'], ['spread', 'Spread'], ['fly', 'Fly'], ['fra', 'FRA']];
const PACKAGE_SIDES = { spread: [['steepener', 'STEEPENER'], ['flattener', 'FLATTENER']], fly: [['rec_body', 'REC GÖVDE'], ['pay_body', 'PAY GÖVDE']] };
// what a package's side sets its legs to, short → long (the server keeps the legs in that order)
const PACKAGE_LEGS = { steepener: ['receive', 'pay'], flattener: ['pay', 'receive'], rec_body: ['pay', 'receive', 'pay'], pay_body: ['receive', 'pay', 'receive'] };
const LEG_NAMES = { spread: ['Kısa bacak', 'Uzun bacak'], fly: ['Kanat 1', 'Gövde', 'Kanat 2'] };
const PAIRS = ['USDTRY', 'EURTRY', 'GBPTRY', 'EURUSD', 'GBPUSD', 'USDJPY', 'USDCHF', 'AUDUSD', 'USDCAD', 'XAUUSD'];
// a field's name in the log of changes
const FIELD_TEXT = { trade_date: 'İşlem tarihi', settle_date: 'Valör', value_date: 'Başlangıç', end_date: 'Vade', tenor: 'Vade',
  notional: 'Nominal', dv01: 'DV01', dv01_ccy: 'DV01 dövizi', sized_by: 'Büyüklük', price: 'Fiyat', yield: 'Getiri',
  price_kind: 'Fiyat tipi', side: 'Yön', structure: 'Yapı', meeting: 'Toplantı', mpc_date: 'Toplantı', mpc_end: 'Bitiş toplantısı',
  tenor_months: 'Vade (ay)', yield_conv: 'Getiri kuralı', fra: 'FRA', legs: 'Bacaklar', isin: 'ISIN',
  pair: 'Parite', quote_amount: 'Tutar (2. döviz)', amount_typed: 'Yazılan tutar', call_put: 'Call / put', strike: 'Strike',
  expiry: 'Vade (expiry)', delivery: 'Teslim', premium_ccy: 'Prim dövizi', premium_date: 'Prim valörü',
  manual_price: 'Elle fiyat', note: 'Not', book: 'Karşı taraf / defter', weights: 'Ağırlıklar', notional_ccy: 'Döviz',
  target: 'Hedef', stop: 'Stop' };
const SHOW = [['ccy', 'İşlem dövizi'], ['try', 'TL'], ['usd', 'USD']];
const UNIT = { try: 'TL', usd: '$' };
// the products whose valuation realises coupons ("Kupon"), the swaps of them ("Kuponlar": a schedule)
const COUPONS = ['ois', 'sofr', 'dibs'];
const SWAPS = ['ois', 'sofr'];
const COUPON_TIP = 'Gerçekleşen kupon: biten dönemlerin net ödemesi (alınan +, ödenen −). MTM kalan dönemlerin değeridir: MTM + kupon = '
  + 'toplam K/Z, ödeme gününde K/Z sıçramaz (kupon MTM\'den bu sütuna geçer)';
const COUPON_STATE = { paid: 'ödendi', due: 'ödenecek', running: 'işliyor (bugüne kadar)', future: 'bekliyor' };
// the products whose K/Z adds the funding beside the value (the desk, 19.11.2026: spot and DİBS K/Z = price move + carry)
const FUNDED = ['fxspot', 'dibs'];
const RUNNING_TIP = 'Biriken: işleyen kupon döneminin bugüne kadarki neti (sabit − fixinglerin bileşiği; alınan +, ödenen −). '
  + 'MTM\'in içindedir; dönem bitince "Kupon"a geçer.';
const FUNDING_TIP = 'Fonlama: valörden bu yana pozisyonu taşımanın maliyeti / getirisi - FX spot\'ta her gün bir sonraki spot valörüne iki '
  + 'paranın O/N faiziyle, DİBS\'te kirli fiyatın TLREF ile fonlanması. MTM\'de yoktur, K/Z\'a girer: MTM + Kupon + Fonlama = toplam K/Z '
  + '(K/Z\'ın "c"si carry, "f"si yalnız fiyat hareketi).';
const CARRY_TIP = 'Carry (1g): piyasa aynı kalırsa bir sonraki iş gününe (hafta sonunda 3 takvim günü) kazandırdığı (+) / kaybettirdiği (−).';
// a level's distance as the desk reads it (tto/tradebook.py levels_of: positive = still to go)
const DIST = { bp: [1, ' bp'], pip: [0, ' pip'], '%': [1, '%'], puan: [3, ' puan'] };

/** A trade's level (target, stop) in its own quote: a rate %38,50, a spread's -20,0 bp, a price, a premium. */
function levelText(v, lu) {
  if (typeof v !== 'number' || !isFinite(v)) return '—';
  const u = (lu && lu.short) || '';
  if (u === '%' || u === 'getiri %') return '%' + num(v, Math.abs(v * 100 - Math.round(v * 100)) > 1e-6 ? 4 : 2);
  if (u === 'bp') return (v > 0 ? '+' : '') + num(v, 1) + ' bp';
  return num(v, lu && typeof lu.digits === 'number' ? lu.digits : 4);
}

/** What is left to a level ("80,0 bp", "1.500 pip", "+150,0%"), or that it was reached. */
function distText(d, unit) {
  if (typeof d !== 'number' || !isFinite(d)) return '—';
  if (d <= 0) return 'geldi';
  const [digits, suffix] = DIST[unit] || [2, ''];
  return num(d, digits) + suffix;
}

/** The unit a trade's target / stop is typed in, as its price box shows it (tto/tradebook.py level_spec). */
function levelUnitOf(product, structure, priceKind) {
  if (product === 'ois' || product === 'sofr') return structure === 'spread' || structure === 'fly' ? 'bp' : '%';
  if (product === 'dibs') return priceKind === 'yield' ? 'getiri %' : 'temiz fiyat';
  return product === 'fxspot' ? 'kur' : 'prim tutarı';
}

let bondsCache = null;
/** The bonds of the form's ISIN list (the catalog), once a page. */
function bondCatalog() {
  if (!bondsCache) bondsCache = api.get('/api/bonds/catalog').then((d) => d.bonds || [], () => { bondsCache = null; return []; });
  return bondsCache;
}

function pref(key, fallback) {
  try { return localStorage.getItem('tto.trades.' + key) || fallback; } catch (e) { return fallback; }
}

function setPref(key, value) {
  try { localStorage.setItem('tto.trades.' + key, value); } catch (e) { /* not kept */ }
}

/** A signed amount (+1.234 / -1.234): the P&L's own way. */
function signed(v, digits = 0) {
  if (typeof v !== 'number' || !isFinite(v)) return '—';
  return (v > 0 ? '+' : '') + num(v, digits);
}

/** A rate in percent as the desk writes it: two decimals at least, four at most (4,10 · 38,125). */
function rateText(v) {
  if (typeof v !== 'number' || !isFinite(v)) return '—';
  const frac = (v.toFixed(4).split('.')[1] || '').replace(/0+$/, '');
  return num(v, Math.max(2, frac.length));
}

/** An amount as the desk types it back into a box: 100m, 2,5m, 500k (the server reads it the same). */
function amountText(v) {
  if (typeof v !== 'number' || !isFinite(v)) return '';
  const a = Math.abs(v);
  for (const [unit, div] of [['m', 1e6], ['k', 1e3]]) {
    if (a >= div && Math.abs(Math.round(v / div * 1000) - v / div * 1000) < 1e-6) return plain(v / div) + unit;
  }
  return plain(v);
}

/** A number typed back into a box, as many decimals as it has (38,5 · 42,1525). */
function plain(v) {
  if (typeof v !== 'number' || !isFinite(v)) return '';
  const s = String(Number(v.toPrecision(12)));
  return settings.lang === 'en' ? s : s.replace('.', ',');
}

/** A swap's side as the form says it: the valuation keeps it as the blotter's code ("S" receives, "B" pays). */
function rateSide(s) {
  const k = String(s || '').toLowerCase();
  return k === 's' || k === 'receive' ? 'receive' : (k === 'b' || k === 'pay' ? 'pay' : null);
}

/** A package's legs' DV01 weights (the valuation's ``{weights: [...]}`` or a list), else 1:1 / 50/50. */
function weightsOf(w, st) {
  const x = w && w[st];
  const list = Array.isArray(x) ? x : (x && Array.isArray(x.weights) ? x.weights : null);
  return list || (st === 'fly' ? [0.5, 1, 0.5] : [1, 1]);
}

/** dd.mm.yyyy -> yyyy-mm-dd (null when it is not such a date: a shortcut, nothing). */
function trToIso(text) {
  const m = /^\s*(\d{1,2})[./](\d{1,2})[./](\d{4})\s*$/.exec(text || '');
  if (m) return m[3] + '-' + m[2].padStart(2, '0') + '-' + m[1].padStart(2, '0');
  return /^\d{4}-\d{2}-\d{2}$/.test((text || '').trim()) ? text.trim() : null;
}

function seg(options, value, onPick, id) {
  const el = h('div', { class: 'seg', id: id || null });
  const set = (v) => {
    el.value = v;
    for (const b of el.children) b.classList.toggle('on', b.dataset.v === v);
  };
  for (const [v, label] of options) {
    const b = h('button', { type: 'button' }, label);
    b.dataset.v = v;
    b.addEventListener('click', () => { set(v); onPick(v); });
    el.appendChild(b);
  }
  el.set = set;
  set(value);
  return el;
}

function field(label, control, opts = {}) {
  const el = h('div', { class: 'field' + (opts.cls ? ' ' + opts.cls : '') }, h('label', null, label), control);
  if (opts.width) el.style.width = opts.width;
  if (opts.name) {
    el.appendChild(h('div', { class: 'echo muted', 'data-echo': opts.name }));
    el.appendChild(h('div', { class: 'ferr', 'data-for': opts.name }));
  }
  return el;
}

function td(text, cls, title) {
  return h('td', { class: cls || null, title: title || null }, text);
}

/** Where a period starts, as its cell's tip says it. */
function fromText(per) {
  if (!per) return '';
  if (per.why) return per.why;
  if (per.basis === 'inception') return 'İşlem tarihinden (' + isoToTr(per.from) + ') bu yana';
  return isoToTr(per.from) + ' kapanışından bu yana';
}

/** A P&L cell: the number, and under it its carry and price effect. */
function pnlCell(per, key) {
  if (!per) return td('', 'pnl');
  if (per.out) return td('', 'pnl muted', 'bu dönemden önce kapandı');
  const v = per.pnl[key];
  if (typeof v !== 'number') return td('—', 'pnl muted', per.why || 'bilinmiyor');
  const cell = h('td', { class: 'pnl ' + (v > 0 ? 'pos' : (v < 0 ? 'neg' : '')), title: fromText(per) },
    h('div', { class: 'v' }, signed(v)),
    h('div', { class: 'cs' }, 'c ' + signed(per.carry[key]) + ' · f ' + signed(per.price[key])));
  return cell;
}

function greeksText(g) {
  if (!g) return '';
  const names = { delta: 'Δ', gamma: 'Γ', vega: 'Vega', theta: 'Θ', rho: 'ρ' };
  return Object.keys(g).map((k) => (names[k] || k) + ' ' + num(g[k], Math.abs(g[k]) < 10 ? 4 : 0)).join(' · ');
}

const PREMIUM_VOL_TIP = 'Primin vol\'ü: bugünkü spot, forward ve iskontoyla (değerlemenin kendi girdileri) opsiyonu tam primine '
  + 'eşitleyen Garman-Kohlhagen vol\'ü - MTM\'in 0 olduğu vol. İşlem günü bayinin primindeki vol\'dür; sonra spot ve zaman '
  + 'değiştikçe değişir.';

/** The form's line for an FX option (``/api/trades/check``'s ``vol``): the vol its premium implies, beside the vol the
 * valuation uses - the smile's at the strike, or the one typed - and the premium that vol gives; or why no vol reaches
 * the premium. */
function premiumVolLine(v) {
  const el = h('div', { class: 'tf-vol', id: 'tf-vol', title: PREMIUM_VOL_TIP });
  if (!v || !v.ok) {
    el.classList.add('muted');
    el.textContent = 'Primin vol\'ü: ' + ((v && v.why) || 'hesaplanamadı');
    return el;
  }
  if (typeof v.vol !== 'number') {
    el.classList.add('errtxt');
    el.textContent = 'Bu prime hiçbir vol ulaşmıyor: ' + (v.vol_why || '');
    return el;
  }
  const bits = ['Primin vol\'ü ' + num(v.vol, 2)];
  if (typeof v.used === 'number') {
    bits.push((v.model === 'elle vol' ? 'elle vol ' : 'smile' + (v.model ? ' (' + v.model.toUpperCase() + ', strike\'ta) ' : ' ')) + num(v.used, 2));
    bits.push('fark ' + signed(v.vol - v.used, 2) + ' vol');
    if (typeof v.used_premium === 'number') bits.push((v.model === 'elle vol' ? 'o vol\'le prim ' : 'smile\'la prim ') + num(v.used_premium, 0) + ' ' + v.premium_ccy);
  } else {
    bits.push('smile yok' + (v.used_why ? ': ' + v.used_why : ''));
  }
  el.textContent = bits.join(' · ');
  return el;
}

export class TradesPage {
  constructor(host, ctx) {
    this.host = host;
    this.ctx = ctx;
    this.dead = false;
    this.scope = pref('scope', 'desk') === 'personal' ? 'personal' : 'desk';
    this.show = ['ccy', 'try', 'usd'].includes(pref('show', 'ccy')) ? pref('show', 'ccy') : 'ccy';
    this.legRows = pref('legrows', '') === '1';
    this.quantOnly = pref('quant', '') === '1';
    this.data = null;
    this.quant = null;
    this.expanded = new Set();
    this.bonds = null;
    this.loadedAt = 0;
    this.reloadSoon = debounce(() => { this.reload().catch(() => {}); }, 150);
  }

  async load() {
    this.build();
    await this.reload();
  }

  async reload() {
    const data = await api.get('/api/trades', { scope: this.scope });
    if (this.dead || data.scope !== this.scope) return;
    this.data = data;
    this.loadedAt = Date.now();
    if (this.quantOnly) this.loadQuant().catch(() => {});
    this.paint();
  }

  /** The values come with "MTM yenile"; only the distances to the targets and stops follow the market - the server values
   * those trades every few seconds (the alarms' round): the list again at most every 10 s while one is open. */
  refresh() {
    const open = (this.data && this.data.open) || [];
    if (!this.dead && open.some((it) => it.levels) && Date.now() - this.loadedAt > 10000) {
      this.loadedAt = Date.now();
      return this.reload().catch(() => {});
    }
    return Promise.resolve();
  }

  /** The live stream's counters: the desk's trades or one's own changed somewhere (another trader, another window). */
  onDesk(changed) {
    if (changed.includes('trades')) this.reloadSoon();
  }

  destroy() {
    this.dead = true;
    this.reloadSoon.cancel();
  }

  // ------------------------------------------------------------------ the page
  build() {
    clear(this.host);
    this.tabs = h('div', { class: 'viewtabs', id: 'trades-scope', role: 'tablist' });
    for (const [s, label, tip] of [['desk', 'Masa', 'Masanın işlemleri: herkes görür ve girer; giren ya da bir yönetici değiştirir'],
      ['personal', 'Kişisel', 'Yalnızca sizin işlemleriniz: başka hiç kimse - yöneticiler de - görmez']]) {
      const b = h('button', { type: 'button', role: 'tab', title: tip }, label);
      b.dataset.scope = s;
      b.addEventListener('click', () => this.setScope(s));
      this.tabs.appendChild(b);
    }
    const add = h('button', { class: 'btn primary sm', type: 'button', id: 'trades-new' }, '+ Yeni işlem');
    add.addEventListener('click', () => this.openForm(null));
    this.mtmBtn = h('button', { class: 'btn sm', type: 'button', id: 'trades-mtm',
      title: 'Bu sekmedeki bütün işlemleri şimdi değerle (MTM, günlük / haftalık / toplam K/Z). Sürekli canlı değildir: yalnızca tıklayınca hesaplanır.' }, 'MTM yenile');
    this.mtmBtn.addEventListener('click', () => this.runMtm());
    this.mtmAt = h('span', { class: 'muted', id: 'trades-mtm-at' });
    // the curve the values are on: the viewer's setting (Ayarlar → Eğri interpolasyonu) - "MTM yenile" keeps both
    this.mtmCurve = h('span', { class: 'chip', id: 'trades-mtm-curve' });
    const show = h('select', { class: 'inp', id: 'trades-ccy', title: 'İşlem satırlarının gösterildiği döviz (toplamlar her zaman TL ve USD)' });
    for (const [v, label] of SHOW) show.appendChild(h('option', { value: v }, label));
    show.value = this.show;
    show.addEventListener('change', () => { this.show = show.value; setPref('show', this.show); this.paint(); });
    const legs = h('input', { type: 'checkbox', id: 'trades-legrows' });
    legs.checked = this.legRows;
    legs.addEventListener('change', () => { this.legRows = legs.checked; setPref('legrows', legs.checked ? '1' : ''); this.paint(); });
    const log = h('button', { class: 'btn sm', type: 'button', id: 'trades-log', title: 'Bu sekmedeki işlemlerde kim, ne zaman, ne yaptı' }, 'Değişiklik kaydı');
    log.addEventListener('click', () => this.showRecent());
    // "Quant'tan": only the trades taken from a quant line ("İşleme al"), and per family what they made
    this.quantBtn = h('button', { class: 'btn sm' + (this.quantOnly ? ' on' : ''), type: 'button', id: 'trades-quant', 'aria-pressed': String(this.quantOnly),
      title: 'Yalnızca quant sinyallerinden ("İşleme al") alınan işlemler ve aile aile ne kazandırdıkları (masanın ve sizin kişisel işlemleriniz)' }, 'Quant\'tan');
    this.quantBtn.addEventListener('click', () => {
      this.quantOnly = !this.quantOnly;
      setPref('quant', this.quantOnly ? '1' : '');
      this.quantBtn.classList.toggle('on', this.quantOnly);
      this.quantBtn.setAttribute('aria-pressed', String(this.quantOnly));
      if (this.quantOnly) this.loadQuant().catch(errorToast);
      this.paint();
    });
    this.closeInfo = h('span', { class: 'muted', id: 'trades-close-info' });
    this.host.appendChild(this.tabs);
    this.host.appendChild(h('div', { class: 'page-tools' }, add, this.mtmBtn, this.mtmAt, this.mtmCurve,
      h('span', { class: 'muted' }, 'Gösterim'), show,
      h('label', { class: 'check', title: 'Spread, fly ve FRA\'ların bacakları kendi satırlarında: vadelere göre outright pozisyon' }, legs, ' Bacaklar ayrı satır'),
      this.quantBtn, log, h('span', { class: 'grow' }), this.closeInfo));
    this.stale = h('div', { class: 'banner hidden', id: 'trades-stale' });
    this.host.appendChild(this.stale);
    this.curveNote = h('div', { class: 'banner hidden', id: 'trades-curve-note' });
    this.host.appendChild(this.curveNote);
    const section = (id, title) => {
      const count = h('span', { class: 'muted' });
      const body = h('div', { class: 'body' });
      const el = h('section', { class: 'panel wide trades' }, h('header', null, h('h2', null, title), count), body);
      this.host.appendChild(el);
      return { el, body, count, id };
    };
    this.quantSec = section('trades-quant-sec', 'Quant\'tan · aile aile');
    this.openSec = section('trades-open', 'Açık işlemler');
    this.totalSec = section('trades-totals', 'Toplamlar (TL · USD)');
    this.riskSec = section('trades-dv01', 'DV01 · vade (faiz +1 bp, $ · payer +)');
    this.closedSec = section('trades-closed', 'Kapanan işlemler');
    this.host.appendChild(h('div', { class: 'note muted trades-note' },
      'K/Z: günlük son kapanıştan, haftalık önceki haftanın son kapanışından, toplam işlem tarihinden bu yana; her biri carry (c) + fiyat etkisi (f). '
      + 'Swap\'ta MTM kalan dönemlerin değeridir; biten dönemlerin net kuponu "Kupon"dadır (MTM + Kupon = toplam K/Z: ödeme gününde K/Z sıçramaz), '
      + 'dönem dönem "Kuponlar"da; işleyen dönemin bugüne kadarki kuponu "Biriken"de (MTM\'in içinde). '
      + 'FX spot ve DİBS\'te pozisyonu taşımanın fonlaması (iki paranın O/N faiz farkı; kirli fiyatın TLREF ile fonlanması) K/Z\'a girer: '
      + '"Fonlama" valörden bu yana toplamı, MTM + Kupon + Fonlama = toplam K/Z. "Carry (1g)": piyasa aynı kalırsa bir sonraki iş gününün carry\'si. '
      + 'Kapanış kaydı her iş günü masanın Trades kapanış saatinde alınır. Bu işlemler Günlük İşlemler\'e, pozisyona, DV01 riskine ve RET akışına girmez.'));
  }

  setScope(s) {
    if (s === this.scope) return;
    this.scope = s;
    setPref('scope', s);
    this.data = null;
    this.paint();
    this.reload().catch(errorToast);
  }

  values() {
    return (this.data && this.data.mtm) || null;
  }

  paint() {
    for (const b of this.tabs.children) b.classList.toggle('on', b.dataset.scope === this.scope);
    const d = this.data;
    const mtm = this.values();
    this.mtmAt.textContent = mtm ? 'son yenileme: ' + mtm.at.slice(11, 16) + (mtm.by_name ? ' (' + mtm.by_name + ')' : '') : 'henüz değerlenmedi';
    this.stale.classList.toggle('hidden', !(mtm && mtm.stale));
    this.stale.textContent = 'Son yenilemeden sonra işlemler değişti: güncel değerler için "MTM yenile".';
    // which curve the numbers are on: the snapshot's (kept on both: the viewer's own), else the viewer's setting
    const curveText = (mtm && mtm.curve_text) || (d && d.curve_text) || '';
    this.mtmCurve.textContent = curveText ? 'Eğri: ' + curveText : '';
    this.mtmCurve.classList.toggle('hidden', !curveText);
    this.mtmCurve.title = 'MTM, kupon ve K/Z bu eğriyle (Ayarlar → Eğri interpolasyonu, sizin ayarınız). "MTM yenile" ve kapanış kaydı '
      + 'iki eğride de alınır; herkes kendi ayarınınkini görür. Hedef / stop alarmları Bootstrap (Murex) ile.';
    const note = (mtm && mtm.curve_note) || '';
    this.curveNote.textContent = note;
    this.curveNote.classList.toggle('hidden', !note);
    if (d && d.close) {
      const last = d.close.last;
      this.closeInfo.textContent = 'Kapanış kaydı her iş günü ' + d.close.time + (last ? ' · son: ' + isoToTr(last.day) + (last.late ? ' (geç alındı)' : '') : ' · henüz yok');
    }
    this.paintQuant();
    this.paintOpen();
    this.paintTotals();
    this.paintRisk();
    this.paintClosed();
  }

  /** The trades of the tab - with "Quant'tan" on, only those taken from a quant line. */
  shown(list) {
    const items = list || [];
    return this.quantOnly ? items.filter((it) => it.source && it.source.kind === 'quant') : items;
  }

  // ------------------------------------------------------------------ "Quant'tan": per family, what its lines' trades made
  async loadQuant() {
    const d = await api.get('/api/trades/quant');
    if (this.dead) return;
    this.quant = d;
    this.paintQuant();
  }

  paintQuant() {
    const sec = this.quantSec;
    sec.el.classList.toggle('hidden', !this.quantOnly);
    if (!this.quantOnly) return;
    clear(sec.body);
    const d = this.quant;
    sec.count.textContent = d ? 'masanın ve sizin kişisel işlemleriniz · ' + d.at.slice(11, 16) : 'yükleniyor…';
    const t = h('table', { class: 'plain trades', id: 'trades-quant-table' });
    const head = ['Aile', 'İşlem (masa / kişisel)', 'Açık', 'Kapanan', 'Toplam K/Z (TL)', 'Ortalama K/Z (TL)', 'Hedefte', 'Stopta', 'Diğer', 'İsabet'];
    t.appendChild(h('tr', null, ...head.map((x, i) => h('th', { class: i < 2 ? 'l' : null }, x))));
    const pnl = (v) => td(typeof v === 'number' ? signed(v) : '—', typeof v === 'number' ? (v > 0 ? 'pos' : (v < 0 ? 'neg' : '')) : 'muted');
    const line = (f, cls) => h('tr', { class: cls || null, 'data-family': f.family || null }, td(f.label, 'l'), td(f.count + ' (' + f.desk + ' / ' + f.personal + ')', 'l'),
      td(String(f.open)), td(String(f.closed)), pnl(f.pnl_try), pnl(f.avg_try), td(String(f.target)), td(String(f.stop)), td(String(f.other)),
      td(typeof f.hit_rate === 'number' ? num(f.hit_rate * 100, 0) + '%' : '—', null, 'Kapananların hedefte kapanan payı'));
    if (!d || !d.families.length) {
      t.appendChild(h('tr', null, h('td', { class: 'l muted', colspan: String(head.length) }, d ? 'Henüz quant sinyalinden alınmış işlem yok: '
        + 'Sinyaller listesinde bir satırın "İşleme al" düğmesiyle girin.' : 'Yükleniyor…')));
    } else {
      for (const f of d.families) t.appendChild(line(f));
      t.appendChild(line(d.all, 'sum'));
    }
    sec.body.appendChild(t);
    sec.body.appendChild(h('div', { class: 'note muted trades-note' }, 'Açık işlemin K/Z\'ı şimdiki değerle (işlem tarihinden bu yana), kapananınki '
      + 'gerçekleşen. Hedefte / stopta: kapanış fiyatı o seviyede, ötesinde ya da hedef–stop aralığının %5\'i kadar yakınında; diğer: başka bir fiyattan '
      + 'kapandı. İki sekme birlikte sayılır (masanın işlemleri ve sizin kişisel işlemleriniz).'));
  }

  // ------------------------------------------------------------------ the open trades
  paintOpen() {
    const sec = this.openSec;
    clear(sec.body);
    const items = this.shown(this.data ? this.data.open : []);
    sec.count.textContent = this.data ? items.length + ' işlem' + (this.quantOnly ? ' (quant\'tan)' : '') : 'yükleniyor…';
    const mtm = this.values();
    const vals = (mtm && mtm.values) || {};
    const key = this.show;
    const desk = this.scope === 'desk';
    const options = items.some((it) => it.product === 'fxopt');
    // "Kupon": what a swap's ended periods (a bond's coupons) have realised - beside the MTM of what is still to run;
    // "Biriken": a swap's period under way so far (inside the MTM); "Fonlama": an FX spot's / a bond's funding since
    // inception (beside the MTM: in the K/Z); "Carry (1g)": a day more with the market unchanged
    this.couponCol = items.some((it) => COUPONS.includes(it.product));
    this.runningCol = items.some((it) => SWAPS.includes(it.product));
    this.fundingCol = items.some((it) => FUNDED.includes(it.product));
    const unit = key === 'ccy' ? '' : ' (' + UNIT[key] + ')';
    const t = h('table', { class: 'plain trades', id: 'trades-open' });
    t.appendChild(h('tr', null, h('th', null, ''), h('th', { class: 'l' }, 'Ürün'), h('th', { class: 'l' }, 'İşlem'),
      h('th', null, 'İşlem tarihi'), h('th', null, 'İşlem fiyatı'), h('th', null, 'Güncel'),
      h('th', { class: 'l', title: 'Hedefe ve stopa kalan (faiz bp, FX pip, opsiyon primin %\'si, kâğıt fiyatı puan); işaretli: aralığın dörtte biri kadar yakın ya da geldi' }, 'Hedef / stop'),
      h('th', { title: 'Swap\'ta kalan dönemlerin bugünkü değeri (biten dönemlerin kuponu "Kupon"da; işleyen dönemin bugüne kadarki kuponu içinde: "Biriken")' }, 'MTM' + unit),
      this.runningCol ? h('th', { id: 'trades-running-col', title: RUNNING_TIP }, 'Biriken' + unit) : null,
      this.couponCol ? h('th', { id: 'trades-coupon-col', title: COUPON_TIP }, 'Kupon' + unit) : null,
      this.fundingCol ? h('th', { id: 'trades-funding-col', title: FUNDING_TIP }, 'Fonlama' + unit) : null,
      h('th', { id: 'trades-carry-col', title: CARRY_TIP }, 'Carry (1g)' + unit),
      h('th', null, 'Günlük K/Z'), h('th', null, 'Haftalık K/Z'),
      h('th', null, 'Toplam K/Z'), options ? h('th', { class: 'l' }, 'Greekler') : null, desk ? h('th', { class: 'l' }, 'Giren') : null,
      h('th', null, '')));
    if (!items.length) {
      t.appendChild(h('tr', null, h('td', { class: 'l muted', colspan: String(this.columns(options, desk)) },
        this.data ? (this.quantOnly ? 'Bu sekmede quant sinyalinden alınmış açık işlem yok.' : (desk ? 'Masanın açık işlemi yok.' : 'Açık kişisel işleminiz yok.')
          + ' "+ Yeni işlem" ile girin.') : 'Yükleniyor…')));
    }
    for (const it of items) {
      const v = vals[String(it.id)];
      const pkg = ['spread', 'fly', 'fra'].includes(it.structure);
      if (pkg && this.legRows) {
        this.legRowsOf(t, it, v, key, options, desk);
        continue;
      }
      t.appendChild(this.row(it, v, key, options, desk, pkg));
      if (pkg && this.expanded.has(it.id)) this.legsOf(t, it, v, key, options, desk);
    }
    sec.body.appendChild(t);
  }

  /** The value of a trade (or a leg) in the currency shown. */
  money(v, key, base = 'mtm') {
    if (!v) return null;
    const k = key === 'ccy' ? base : base + '_' + key;
    return typeof v[k] === 'number' ? v[k] : null;
  }

  /** How many columns the open list has (the optional ones: Biriken, Kupon, Fonlama, Greekler, Giren). */
  columns(options, desk) {
    return 13 + (this.couponCol ? 1 : 0) + (this.runningCol ? 1 : 0) + (this.fundingCol ? 1 : 0) + (options ? 1 : 0) + (desk ? 1 : 0);
  }

  /** "Biriken": a swap's (or a leg's) period under way, its net so far in the currency shown - inside the MTM. */
  runningCell(it, v, key) {
    const x = SWAPS.includes(it.product) ? this.money(v, key, 'running') : null;
    if (x === null) return td('', 'run');
    return td(x === 0 ? '0' : signed(x), 'run ' + (x > 0 ? 'pos' : (x < 0 ? 'neg' : 'muted')), RUNNING_TIP);
  }

  /** "Fonlama": an FX spot's or a bond's funding since inception (``periods.funding``) - its K/Z counts it beside the MTM. */
  fundingCell(it, per, key) {
    const f = FUNDED.includes(it.product) && per && per.funding ? per.funding[key] : null;
    if (typeof f !== 'number') return td('', 'fund');
    return td(f === 0 ? '0' : signed(f), 'fund ' + (f > 0 ? 'pos' : (f < 0 ? 'neg' : 'muted')), FUNDING_TIP);
  }

  /** "Carry (1g)": what a day more earns with the market unchanged (a trade's or a leg's), its parts and rates in the tip. */
  carryCell(it, v, key) {
    const x = this.money(v, key, 'carry_1d');
    if (x === null) return td('', 'c1d');
    const tip = [CARRY_TIP];
    if (typeof v.carry_days === 'number' && v.carry_days !== 1) tip.push(num(v.carry_days, 0) + ' takvim günü');
    const parts = (v.carry_parts || []).filter((p) => typeof p[1] === 'number');
    if (parts.length && !(parts.length === 1 && parts[0][0] === 'theta')) {
      tip.push(parts.map((p) => p[0] + ' ' + signed(p[1])).join(' · ') + (v.ccy ? ' ' + v.ccy : ''));
    }
    if (v.carry_note) tip.push(v.carry_note);
    if (FUNDED.includes(it.product)) tip.push('Fonlama kısmı K/Z\'a gün gün "Fonlama" olarak girer.');
    return td(x === 0 ? '0' : signed(x), 'c1d ' + (x > 0 ? 'pos' : (x < 0 ? 'neg' : 'muted')), tip.join('\n'));
  }

  /** "Kupon": the coupons a swap (or a leg) has realised - its ended periods' net, + received / − paid; a bond's coupons
   * received - in the currency shown, with the last and the next in its tip.  MTM + Kupon = the total P&L.  ``link``: a
   * swap's number (or "takvim" before it is valued) opens its "Kuponlar". */
  couponCell(it, v, key, link = false) {
    if (!this.couponCol) return null;
    const x = this.money(v, key, 'accrued');
    const open = link && SWAPS.includes(it.product);
    if (!COUPONS.includes(it.product) || (x === null && !open)) return td('', 'cpn');
    const tip = [it.product === 'dibs' ? 'Valörden beri alınan / ödenen kuponlar (ve itfa)' : COUPON_TIP];
    const info = v && v.coupon_info;
    if (info) {
      tip.push(info.n ? info.n + ' dönem bitti' : 'henüz biten dönem yok');
      if (info.last) {
        tip.push('son: ' + isoToTr(info.last.end) + ' ' + signed(info.last.net) + ' ' + (v.ccy || '') + ' · '
          + (info.last.state === 'paid' ? 'ödendi ' : 'ödenecek ') + isoToTr(info.last.pay));
      }
      if (info.next) tip.push('sıradaki ödeme: ' + isoToTr(info.next.pay));
    }
    const text = x === null ? 'takvim' : (x === 0 ? '0' : signed(x));
    const cls = 'cpn ' + (x === null ? 'muted' : (x > 0 ? 'pos' : (x < 0 ? 'neg' : 'muted')));
    if (!open) return td(text, cls, tip.join('\n'));
    tip.push('Tıklayınca "Kuponlar": dönem dönem sabit, değişken, net, ödeme günü');
    const b = h('button', { type: 'button', class: 'linkbtn act-coupons' }, text);
    b.addEventListener('click', () => this.showCoupons(it));
    return h('td', { class: cls, title: tip.join('\n') }, b);
  }

  row(it, v, key, options, desk, pkg) {
    const tr = h('tr', { 'data-id': String(it.id), class: 'trade' });
    const exp = h('td', { class: 'exp' });
    if (pkg) {
      const b = h('button', { class: 'iconbtn', type: 'button', title: 'Bacakları göster' }, this.expanded.has(it.id) ? '▾' : '▸');
      b.addEventListener('click', () => {
        if (this.expanded.has(it.id)) this.expanded.delete(it.id); else this.expanded.add(it.id);
        this.paintOpen();
      });
      exp.appendChild(b);
    }
    tr.appendChild(exp);
    tr.appendChild(td(it.product_text + (it.structure && it.structure !== 'outright' ? ' · ' + (STRUCTURES.find((s) => s[0] === it.structure) || [0, it.structure])[1] : ''), 'l'));
    tr.appendChild(this.whatCell(it));
    tr.appendChild(td(isoToTr(it.trade_date), null, 'Valör ' + isoToTr(it.settle_date)));
    tr.appendChild(td(it.price_text));
    tr.appendChild(this.nowCell(it, v));
    tr.appendChild(this.levelsCell(it));
    if (v && !v.ok) tr.appendChild(td(v.why || 'değerlenemedi', 'muted why', v.why || ''));
    else {
      const m = this.money(v, key);
      tr.appendChild(td(m === null ? '' : num(m, 0) + (key === 'ccy' && v && v.ccy ? ' ' + v.ccy : ''), m !== null ? (m > 0 ? 'pos' : (m < 0 ? 'neg' : '')) : null));
    }
    const val = v && v.ok ? v : null;
    const per = v && v.periods;
    if (this.runningCol) tr.appendChild(this.runningCell(it, val, key));
    if (this.couponCol) tr.appendChild(this.couponCell(it, val, key, true));
    if (this.fundingCol) tr.appendChild(this.fundingCell(it, per, key));
    tr.appendChild(this.carryCell(it, val, key));
    for (const name of ['day', 'week', 'total']) tr.appendChild(pnlCell(per ? per[name] : null, key));
    if (options) tr.appendChild(td(it.product === 'fxopt' && v ? greeksText(v.greeks) : '', 'l small'));
    if (desk) tr.appendChild(td(it.created_by_name || '', 'l muted'));
    tr.appendChild(this.actions(it));
    return tr;
  }

  /** "Güncel": the price now as the valuation reads it - for an FX option its vol (the smile's at the strike, or the one
   * typed) and under it the vol its premium implies on the same market ("prim vol": the MTM is 0 at it). */
  nowCell(it, v) {
    const ok = v && v.ok;
    const cell = td(ok ? (v.price_text || num(v.price_now, 4)) : '', null, ok && it.fields && it.fields.manual_price != null ? 'elle fiyat' : null);
    const pv = ok && it.product === 'fxopt' ? v.vols : null;
    if (pv) {
      const has = typeof pv.premium === 'number';
      const diff = has && typeof pv.used === 'number' ? ' (' + signed(pv.premium - pv.used, 2) + ')' : '';
      cell.appendChild(h('div', { class: 'muted small pvol' }, has ? 'prim vol ' + num(pv.premium, 2) + diff : 'prim vol yok'));
      const tip = [PREMIUM_VOL_TIP];
      if (has && typeof pv.used === 'number') {
        tip.push('Prim vol ' + num(pv.premium, 2) + ' · ' + (pv.model === 'elle vol' ? 'elle vol ' : 'smile ') + num(pv.used, 2)
          + ' · fark (prim − ' + (pv.model === 'elle vol' ? 'elle' : 'smile') + ') ' + signed(pv.premium - pv.used, 2) + ' vol');
      }
      if (!has && pv.why) tip.push(pv.why);
      if (it.fields && it.fields.manual_price != null) tip.push('elle fiyat (vol)');
      cell.title = tip.join('\n');
    }
    return cell;
  }

  /** The trade in the desk's words - its book and note, and the quant line it was taken from. */
  whatCell(it) {
    const what = h('td', { class: 'l what' }, it.text);
    if (it.fields && (it.fields.note || it.fields.book)) {
      what.appendChild(h('div', { class: 'muted small' }, [it.fields.book, it.fields.note].filter(Boolean).join(' · ')));
    }
    const src = it.source;
    if (src && src.kind === 'quant') {
      const lu = it.level_unit;
      what.appendChild(h('div', { class: 'muted small tsrc', title: 'Sinyal ' + (src.line_id || '') + (src.at ? ' · ' + src.at : '')
        + ' · sinyalin girişi ' + levelText(src.entry, lu) + ', hedefi ' + levelText(src.target, lu) + ', stopu ' + levelText(src.stop, lu) },
      'Quant · ' + (src.family_label || src.family) + (src.instrument ? ' · ' + src.instrument : '')));
    }
    return what;
  }

  /** "Hedef / stop": each level and what is left to it (bp for rates, pips for FX, % of an option's premium), marked
   * when the level now is within a quarter of the target–stop range or has reached it. */
  levelsCell(it) {
    const lv = it.levels;
    if (!lv) return td('', 'l lv');
    const lu = it.level_unit;
    const bits = [];
    const tip = [];
    for (const [which, word] of [['target', 'H'], ['stop', 'S']]) {
      const level = lv[which];
      if (typeof level !== 'number') continue;
      const d = lv['to_' + which];
      bits.push(h('div', { class: 'lvl' + (lv.near === which ? ' near ' + which : ''), 'data-which': which },
        word + ' ' + levelText(level, lu) + (typeof d === 'number' ? ' · ' + distText(d, lv.unit) : '')));
      tip.push((which === 'target' ? 'Hedef ' : 'Stop ') + levelText(level, lu) + (typeof d === 'number' ? (d <= 0 ? ': geldi' : ': ' + distText(d, lv.unit) + ' kaldı') : ''));
    }
    if (typeof lv.now === 'number') tip.push('şimdi ' + levelText(lv.now, lu) + (lv.at ? ' (' + lv.at + ')' : ''));
    else tip.push('henüz değerlenmedi');
    tip.push('İzleme\'de alarmı kurulu: hedefe geldi / stopa geldi');
    return h('td', { class: 'l lv' + (lv.near ? ' near-' + lv.near : ''), title: tip.join('\n') }, ...bits);
  }

  /** A package's legs under it: each leg's MTM, realised coupons and P&L (and what the legs leave over of the whole). */
  legsOf(t, it, v, key, options, desk) {
    const per = v && v.periods;
    const legs = per && per.legs ? per.legs : null;
    const span = this.columns(options, desk);
    if (!legs) {
      for (const lg of it.legs) t.appendChild(h('tr', { class: 'leg' }, td(''), td('', 'l'), td('↳ ' + lg.text, 'l'), h('td', { colspan: String(span - 3) })));
      if (!it.legs.length) t.appendChild(h('tr', { class: 'leg' }, td(''), h('td', { class: 'l muted', colspan: String(span - 1) }, 'Bacak değerleri "MTM yenile"den sonra görünür.')));
      return;
    }
    legs.forEach((lg, i) => {
      const tr = h('tr', { class: 'leg', 'data-leg': String(i) });
      tr.appendChild(td(''));
      tr.appendChild(td('', 'l'));
      tr.appendChild(td('↳ ' + lg.label + (it.legs[i] && it.structure !== 'fra' ? ' · ' + it.legs[i].text : ''), 'l'));
      tr.appendChild(td(''));
      tr.appendChild(td(''));
      tr.appendChild(td(lg.price_text || (typeof lg.price_now === 'number' ? num(lg.price_now, 4) : '')));
      tr.appendChild(td(''));
      const m = this.money(lg, key);
      tr.appendChild(td(m === null ? '' : num(m, 0)));
      if (this.runningCol) tr.appendChild(this.runningCell(it, lg, key));
      if (this.couponCol) tr.appendChild(this.couponCell(it, lg, key));
      if (this.fundingCol) tr.appendChild(td(''));
      tr.appendChild(this.carryCell(it, lg, key));
      for (const name of ['day', 'week', 'total']) tr.appendChild(pnlCell(lg[name], key));
      if (options) tr.appendChild(td(''));
      if (desk) tr.appendChild(td(''));
      tr.appendChild(td(''));
      t.appendChild(tr);
    });
    const r = per.residual;
    if (r && ['day', 'week', 'total'].some((n) => typeof r[n].pnl[key] === 'number' && Math.abs(r[n].pnl[key]) >= 0.5)) {
      const tr = h('tr', { class: 'leg resid', title: it.structure === 'fra' ? 'FRA tek enstrüman olarak değerlenir; bacaklar katkıdır, kalan bacakların açıklamadığı kısımdır'
        : 'Bacakların dışında kalan (yuvarlama)' });
      tr.appendChild(td(''));
      tr.appendChild(td('', 'l'));
      tr.appendChild(td('↳ kalan', 'l muted'));
      // (from the trade date to "Carry (1g)": the optional Biriken / Kupon / Fonlama with them)
      tr.appendChild(h('td', { colspan: String(6 + (this.runningCol ? 1 : 0) + (this.couponCol ? 1 : 0) + (this.fundingCol ? 1 : 0)) }));
      for (const name of ['day', 'week', 'total']) tr.appendChild(pnlCell(r[name], key));
      if (options) tr.appendChild(td(''));
      if (desk) tr.appendChild(td(''));
      tr.appendChild(td(''));
      t.appendChild(tr);
    }
  }

  /** "Bacaklar ayrı satır": a package's legs as rows of their own - the desk's outright exposure by tenor. */
  legRowsOf(t, it, v, key, options, desk) {
    const per = v && v.periods;
    const legs = per && per.legs ? per.legs : null;
    const n = legs ? legs.length : it.legs.length;
    if (!n) { t.appendChild(this.row(it, v, key, options, desk, false)); return; }
    for (let i = 0; i < n; i++) {
      const lg = legs ? legs[i] : null;
      const tr = h('tr', { 'data-id': String(it.id), 'data-leg': String(i), class: 'trade legrow' });
      tr.appendChild(td(''));
      tr.appendChild(td(it.product_text + ' · bacak', 'l'));
      tr.appendChild(td((it.legs[i] ? it.legs[i].text : (lg ? lg.label : '')) + ' (' + it.text + ')', 'l what'));
      tr.appendChild(td(isoToTr(it.trade_date)));
      tr.appendChild(td(''));
      tr.appendChild(td(lg ? (lg.price_text || (typeof lg.price_now === 'number' ? num(lg.price_now, 4) : '')) : ''));
      tr.appendChild(i === 0 ? this.levelsCell(it) : td(''));
      const m = lg ? this.money(lg, key) : null;
      tr.appendChild(td(m === null ? (v && !v.ok ? '—' : '') : num(m, 0), m === null ? 'muted' : null, v && !v.ok ? v.why : null));
      if (this.runningCol) tr.appendChild(this.runningCell(it, lg, key));
      if (this.couponCol) tr.appendChild(this.couponCell(it, lg, key, true));
      if (this.fundingCol) tr.appendChild(td(''));
      tr.appendChild(this.carryCell(it, lg, key));
      for (const name of ['day', 'week', 'total']) tr.appendChild(pnlCell(lg ? lg[name] : null, key));
      if (options) tr.appendChild(td(''));
      if (desk) tr.appendChild(td(it.created_by_name || '', 'l muted'));
      tr.appendChild(i === 0 ? this.actions(it) : td(''));
      t.appendChild(tr);
    }
  }

  actions(it) {
    const cell = h('td', { class: 'acts' });
    const btn = (label, cls, tip, fn) => {
      const b = h('button', { class: 'btn sm ghost ' + cls, type: 'button', title: tip }, label);
      b.addEventListener('click', fn);
      cell.appendChild(b);
    };
    if (it.status !== 'closed' && it.can_edit) btn('Düzenle', 'act-edit', 'İşlemi düzenle', () => this.openForm(it));
    if (it.status !== 'closed' && it.can_edit) btn('Kapat', 'act-close', 'Kapanış tarihi ve fiyatıyla kapat: kapanan işlemlere gider', () => this.closeTrade(it));
    if (it.status === 'closed' && it.can_edit) btn('Geri aç', 'act-reopen', 'Kapanışı geri al', () => this.reopen(it));
    if (SWAPS.includes(it.product) && it.status === 'closed') {
      // (an open swap's: its "Kupon" cell)
      btn('Kuponlar', 'act-coupons', 'Kupon takvimi, bacak bacak: her dönemin sabit ve değişken ödemesi (fixinglerin bileşiği), neti, ödeme günü '
        + 've ödenip ödenmediği - kapanışına göre', () => this.showCoupons(it));
    }
    btn('Geçmiş', 'act-log', 'Bu işlemde kim, ne zaman, ne yaptı', () => this.showLog(it));
    if (it.can_edit) btn('Sil', 'act-del danger', 'İşlemi sil (kaydı kalır)', () => this.remove(it));
    return cell;
  }

  // ------------------------------------------------------------------ totals
  paintTotals() {
    const sec = this.totalSec;
    clear(sec.body);
    const mtm = this.values();
    const t = h('table', { class: 'plain trades', id: 'trades-totals' });
    const head = ['Ürün', 'Açık / kapanan'];
    for (const c of ['TL', 'USD']) head.push('MTM ' + c, 'Günlük ' + c, 'Haftalık ' + c, 'Toplam ' + c, 'Gerçekleşen ' + c);
    t.appendChild(h('tr', null, ...head.map((x, i) => h('th', { class: i < 2 ? 'l' : null }, x))));
    if (!mtm || !mtm.totals) {
      t.appendChild(h('tr', null, h('td', { class: 'l muted', colspan: String(head.length) }, 'Toplamlar "MTM yenile" ile hesaplanır.')));
      sec.count.textContent = '';
      sec.body.appendChild(t);
      return;
    }
    const cellOf = (row, name, ccy) => {
      const miss = row.missing || {};
      if (name === 'mtm') {
        const v = row['mtm.' + ccy];
        return td(typeof v === 'number' ? num(v, 0) : '—', typeof v === 'number' ? null : 'muted', miss['mtm.' + ccy] ? miss['mtm.' + ccy] + ' işlem değerlenemedi (toplama girmedi)' : null);
      }
      const v = row[name + '.pnl.' + ccy];
      const gap = miss[name + '.pnl.' + ccy];
      if (typeof v !== 'number') return td(gap ? '—' : '', 'pnl muted', gap ? gap + ' işlemin K/Z\'ı bilinmiyor' : null);
      const cell = h('td', { class: 'pnl ' + (v > 0 ? 'pos' : (v < 0 ? 'neg' : '')), title: gap ? gap + ' işlemin K/Z\'ı bilinmiyor (toplama girmedi)' : null },
        h('div', { class: 'v' }, signed(v) + (gap ? ' *' : '')),
        h('div', { class: 'cs' }, 'c ' + signed(row[name + '.carry.' + ccy]) + ' · f ' + signed(row[name + '.price.' + ccy])));
      return cell;
    };
    const line = (label, row, cls) => {
      const tr = h('tr', { class: cls || null }, td(label, 'l'), td(row.count + ' / ' + row.closed, 'l'));
      for (const ccy of ['try', 'usd']) for (const name of ['mtm', 'day', 'week', 'total', 'realized']) tr.appendChild(cellOf(row, name, ccy));
      return tr;
    };
    for (const p of mtm.totals.products) t.appendChild(line(p.label, p));
    t.appendChild(line('Toplam', mtm.totals.all, 'sum'));
    sec.count.textContent = '* değerlenemeyen işlem toplama girmedi';
    sec.body.appendChild(t);
  }

  // ------------------------------------------------------------------ DV01 by tenor
  /** "DV01 · vade": the tab's open trades as Günlük İşlemler's "OIS · vade özeti" (O22:W39) has the day's - the net DV01,
   * per tenor the paid and received nominal, rate and DV01 ($ for +1 bp), the net position's rate - TRY OIS and SOFR
   * apart; above them the bar: TRY OIS net, bonds, their total, SOFR (tto/tradebook.py dv01_table).  From the last "MTM
   * yenile"; ON to 5Y always, 6Y on when they hold something. */
  paintRisk() {
    const sec = this.riskSec;
    clear(sec.body);
    const mtm = this.values();
    const r = mtm && mtm.dv01;
    if (!r) {
      sec.count.textContent = '';
      sec.body.appendChild(h('div', { class: 'muted' }, 'DV01 tablosu "MTM yenile" ile hesaplanır.'));
      return;
    }
    sec.count.textContent = 'açık işlemler · ' + mtm.at.slice(11, 16);
    const bar = r.bar || {};
    const tileOf = (label, v, k, big, tip) => {
      const el = h('div', { class: 'q' + (big ? ' big' : '') + (typeof v === 'number' && v !== 0 ? (v > 0 ? ' pos' : ' neg') : ''),
        'data-k': 'dv01-' + k, title: tip }, h('div', { class: 'l' }, label), h('div', { class: 'v' }, signed(v)));
      return el;
    };
    const tip = 'TRY faizi +1 bp olursa kâr / zarar ($). İşaret Günlük İşlemler\'deki gibi: payer + (PAY), receiver − (RECEIVE, tahvil alışı).';
    const riskBar = h('div', { class: 'riskbar', id: 'trades-dv01-bar' }, h('div', { class: 'l', title: tip }, 'DV01 · TRY faizi +1 bp ($) · payer +'),
      tileOf('Toplam', bar.total, 'total', true, tip), tileOf('OIS (net)', bar.ois, 'ois', false, tip),
      tileOf('Tahvil', bar.bond, 'bond', false, tip + ' Tahvil: DİBS RV\'nin DV01\'i, vadesinde.'));
    if (r.usd) riskBar.appendChild(tileOf('SOFR (USD faizi, net)', bar.sofr, 'sofr', false, 'USD faizi +1 bp olursa kâr / zarar ($), payer +: TRY toplamına girmez.'));
    if (r.unknown) riskBar.appendChild(h('div', { class: 'muted warn' }, r.unknown + ' işlemin değeri yok: toplama girmedi'));
    sec.body.appendChild(riskBar);
    const table = (book, id, title, unit) => {
      const t = h('table', { class: 'plain trades dv01', id });
      t.appendChild(h('tr', null, h('th', { class: 'l', colspan: '9' }, title)));
      t.appendChild(h('tr', null, h('th', null, ''), h('th', null, ''), h('th', { colspan: '3' }, 'Pay'), h('th', { colspan: '3' }, 'Receive'),
        h('th', null, 'Net')));
      t.appendChild(h('tr', null, ...['Net DV01 ($)', 'Vade', 'Tutar (' + unit + ')', 'Faiz', 'DV01 ($)', 'Tutar (' + unit + ')', 'Faiz', 'DV01 ($)', 'Faiz']
        .map((x, i) => h('th', { class: i === 1 ? 'l' : null }, x))));
      const amt = (v) => td(typeof v === 'number' && v !== 0 ? num(v, 0) : '0', typeof v === 'number' && v !== 0 ? null : 'muted');
      const rate = (v) => td(typeof v === 'number' ? '%' + num(v, 4) : '');
      const line = (x, cls) => h('tr', { class: cls || null, 'data-tenor': x.tenor },
        td(signed(x.net_dv01), x.net_dv01 > 0 ? 'pos' : (x.net_dv01 < 0 ? 'neg' : 'muted')), td(x.tenor, 'l'),
        amt(x.pay_nominal), rate(x.pay_rate), amt(x.pay_dv01), amt(x.rec_nominal), rate(x.rec_rate), amt(x.rec_dv01), rate(x.net_rate));
      const long = new Set(['6Y', '7Y', '8Y', '9Y', '10Y']);
      for (const x of book.rows) {
        if (long.has(x.tenor) && !x.pay_dv01 && !x.rec_dv01) continue;
        t.appendChild(line(x));
      }
      t.appendChild(line(book.total, 'sum'));
      return t;
    };
    if (r.try) sec.body.appendChild(table(r.try, 'trades-dv01-try', 'TRY OIS · vade', 'TL'));
    if (r.usd) sec.body.appendChild(table(r.usd, 'trades-dv01-usd', 'SOFR · vade', '$'));
    if (!r.try && !r.usd) sec.body.appendChild(h('div', { class: 'muted' }, 'Bu sekmede açık swap yok.'));
    sec.body.appendChild(h('div', { class: 'note muted trades-note' }, 'Günlük İşlemler\'in "OIS · vade özeti" gibi, sekmenin açık işlemleri (son MTM yenile). '
      + 'Swap bitişinde: bugün spot\'tan vadeyle girilen kendi vadesinde (15M: ½ 1Y + ½ 18M), tarihle girilen ya da başlamış olan bitiş tarihinin '
      + 'iki yanındaki vadeye gün oranında; ileri başlangıçlı (FRA, PPK dönemi, ileri bacak) spot\'tan bitişine swap ile ters yönde başlangıcına swap, '
      + 'DV01\'leri toplamı işleminki olan tek nominalle (Günlük İşlemler\'in PPK işlemi kuralı). Faiz tutarla ağırlıklı; Net faiz iki taraf da varken '
      + '(R·S − U·V) / (S − V). Tahvil yalnız üstteki toplamda (DİBS RV\'nin DV01\'i, aldığınız kâğıt −); SOFR USD faizidir, TRY toplamına girmez.'));
  }

  // ------------------------------------------------------------------ closed trades
  paintClosed() {
    const sec = this.closedSec;
    clear(sec.body);
    const items = this.shown(this.data ? this.data.closed : []);
    sec.count.textContent = items.length ? items.length + ' işlem' : '';
    const key = this.show;
    const desk = this.scope === 'desk';
    const t = h('table', { class: 'plain trades', id: 'trades-closed' });
    t.appendChild(h('tr', null, h('th', { class: 'l' }, 'Ürün'), h('th', { class: 'l' }, 'İşlem'), h('th', null, 'İşlem tarihi · fiyatı'),
      h('th', null, 'Kapanış tarihi · fiyatı'), h('th', null, 'Gerçekleşen K/Z' + (key === 'ccy' ? '' : ' (' + UNIT[key] + ')')),
      desk ? h('th', { class: 'l' }, 'Giren') : null, h('th', null, '')));
    if (!items.length) t.appendChild(h('tr', null, h('td', { class: 'l muted', colspan: '7' }, 'Kapanan işlem yok.')));
    for (const it of items) {
      const r = it.realized;
      const tr = h('tr', { 'data-id': String(it.id), class: 'trade closed' });
      tr.appendChild(td(it.product_text, 'l'));
      tr.appendChild(this.whatCell(it));
      tr.appendChild(td(isoToTr(it.trade_date) + ' · ' + it.price_text));
      const hit = it.levels && it.levels.hit;
      tr.appendChild(td(isoToTr(it.close_date) + ' · ' + (it.close_price_text || '') + (hit ? ' · ' + { target: 'hedefte', stop: 'stopta', other: 'diğer' }[hit] : ''),
        hit ? 'hit-' + hit : null, it.levels ? 'Hedef ' + levelText(it.levels.target, it.level_unit) + ' · stop ' + levelText(it.levels.stop, it.level_unit) : null));
      if (r && !r.ok) tr.appendChild(td(r.why || 'değerlenemedi', 'muted why', r.why));
      else tr.appendChild(pnlCell(r && r.periods ? r.periods.total : null, key));
      if (desk) tr.appendChild(td(it.created_by_name || '', 'l muted'));
      tr.appendChild(this.actions(it));
      t.appendChild(tr);
    }
    sec.body.appendChild(t);
  }

  // ------------------------------------------------------------------ actions
  async runMtm() {
    this.mtmBtn.disabled = true;
    this.mtmAt.textContent = 'hesaplanıyor…';
    try {
      await api.post('/api/trades/mtm', { scope: this.scope });
      if (this.dead) return;
      await this.reload();                       // (the list comes with the tab's last refresh: this one)
    } catch (err) {
      errorToast(err);
      this.paint();
    } finally {
      this.mtmBtn.disabled = false;
    }
  }

  openForm(it) {
    new TradeForm(this, it);
  }

  async remove(it) {
    if (!(await confirmDialog('İşlemi sil', it.text + ' silinsin mi? Kaydı (kim, ne zaman) kalır.', 'Sil', true))) return;
    try {
      await api.del('/api/trades/' + it.id);
      toast('İşlem silindi', 'ok');
      await this.reload();
    } catch (err) { errorToast(err); }
  }

  async reopen(it) {
    try {
      await api.post('/api/trades/' + it.id + '/reopen', {});
      toast('Kapanış geri alındı', 'ok');
      await this.reload();
    } catch (err) { errorToast(err); }
  }

  closeTrade(it) {
    const m = modal({ title: 'İşlemi kapat', width: 460 });
    const date = h('input', { class: 'inp', id: 'tc-date', value: isoToTr(this.data ? this.data.today : ''), placeholder: 'gg.aa.yyyy' });
    const unit = it.product === 'ois' || it.product === 'sofr' ? (it.structure === 'spread' || it.structure === 'fly' ? 'bp' : '%')
      : (it.product === 'fxopt' ? 'prim tutarı' : (it.fields && it.fields.price_kind === 'yield' ? 'getiri %' : 'fiyat'));
    const price = h('input', { class: 'inp num', id: 'tc-price', placeholder: unit });
    const err = h('div', { class: 'errtxt' });
    m.body.appendChild(h('p', { class: 'muted', style: { marginTop: '0' } }, it.text));
    m.body.appendChild(h('div', { class: 'row' }, field('Kapanış tarihi', date, { width: '150px' }), field('Kapanış fiyatı (' + unit + ')', price, { width: '170px' })));
    m.body.appendChild(err);
    const save = h('button', { class: 'btn primary', type: 'button', id: 'tc-save' }, 'Kapat');
    const go = async () => {
      save.disabled = true;
      try {
        const res = await api.post('/api/trades/' + it.id + '/close', { close_date: date.value, close_price: price.value });
        m.close();
        toast('İşlem kapandı' + (res.closing && !res.closing.ok ? ' (gerçekleşen K/Z: ' + (res.closing.why || 'hesaplanamadı') + ')' : ''), 'ok', 4200);
        await this.reload();
      } catch (e) {
        err.textContent = e.message;
      } finally { save.disabled = false; }
    };
    save.addEventListener('click', go);
    for (const el of [date, price]) el.addEventListener('keydown', (e) => { if (e.key === 'Enter') go(); });
    m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Vazgeç'));
    m.foot.appendChild(save);
    price.focus();
  }

  changeText(c) {
    const [k, a, b] = c;
    const show = (v) => {
      if (v === null || v === undefined || v === '') return '—';
      if (Array.isArray(v)) return k === 'legs' ? v.length + ' bacak' : v.join(' / ');
      if (typeof v === 'number') return ['notional', 'quote_amount', 'dv01'].includes(k) ? amountText(v) : plain(v);
      if (typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v)) return isoToTr(v);
      return String(v);
    };
    return (FIELD_TEXT[k] || k) + ': ' + show(a) + ' → ' + show(b);
  }

  logTable(entries, withTrade) {
    const t = h('table', { class: 'plain trades', id: 'trades-log-table' });
    t.appendChild(h('tr', null, h('th', { class: 'l' }, 'Zaman'), h('th', { class: 'l' }, 'Kim'), h('th', { class: 'l' }, 'Ne'),
      withTrade ? h('th', { class: 'l' }, 'İşlem') : null, h('th', { class: 'l' }, 'Ayrıntı')));
    for (const e of entries) {
      let detail = '';
      if (e.action === 'edit') detail = e.changes.map((c) => this.changeText(c)).join('; ');
      else if (e.action === 'close') detail = isoToTr(e.close_date) + ' · ' + (e.close_price_text || '');
      t.appendChild(h('tr', null, td(isoToTr(e.ts.slice(0, 10)) + ' ' + e.ts.slice(11, 16), 'l'), td(e.user_name, 'l'), td(e.action_text, 'l'),
        withTrade ? td(e.text, 'l') : null, h('td', { class: 'l wrap' }, detail)));
    }
    if (!entries.length) t.appendChild(h('tr', null, h('td', { class: 'l muted', colspan: '5' }, 'Kayıt yok.')));
    return t;
  }

  /** "Kuponlar": a swap's schedule leg by leg, valued now by the server (a closed swap at its close) - every period's
   * fixed and floating payment (the float compounded from the history's fixings), net, payment day and state; what has
   * been realised (paid + due) is the "Kupon" of the list. */
  async showCoupons(it) {
    try {
      const res = await api.get('/api/trades/' + it.id + '/coupons');
      const m = modal({ title: 'Kuponlar', width: 1040 });
      const when = res.status === 'closed' ? 'kapanışına göre (' + isoToTr(res.asof) + ')' : isoToTr(res.asof) + ' itibarıyla';
      m.body.appendChild(h('p', { class: 'muted', style: { marginTop: '0' } }, it.text + ' · ' + when
        + (res.curve_text ? ' · eğri: ' + res.curve_text : '')));
      const box = h('div', { id: 'trades-coupons' });
      if (!res.ok) box.appendChild(h('p', { class: 'muted why' }, res.why || 'hesaplanamadı'));
      (res.legs || []).forEach((lg, i) => box.appendChild(this.couponTable(lg, i)));
      if (res.ok && (res.legs || []).length > 1) {
        box.appendChild(h('p', { class: 'cpn-total', id: 'trades-coupons-total' }, 'Toplam gerçekleşen: ' + signed(res.realised) + ' ' + (res.ccy || '')
          + (typeof res.realised_try === 'number' && res.ccy !== 'TRY' ? ' (' + signed(res.realised_try) + ' TL)' : '')));
      }
      const notes = (res.notes || []).slice();
      notes.push('Fixingler: ' + (res.source || 'tarihçede yok') + '. Tutarlar işlemin dövizinde; + alınan, − ödenen. "Gerçekleşen" = biten '
        + 'dönemlerin neti (ödendi + ödenecek): Trades\'te MTM\'in yanındaki "Kupon", toplam K/Z\'a girer.');
      for (const n of notes) box.appendChild(h('div', { class: 'note muted trades-note' }, n));
      m.body.appendChild(box);
      m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Kapat'));
    } catch (err) { errorToast(err); }
  }

  /** One swap's periods: dates, days, payment day, the fixed and floating payments, the float's compounded rate, the net
   * and its state; a row whose float has days not had by their own fixing says which ("*"). */
  couponTable(lg, i) {
    const wrap = h('div', { class: 'cpn-leg', 'data-leg': String(i) });
    const head = [lg.label, amountText(lg.notional) + ' ' + (lg.ccy || ''), 'sabit %' + rateText(lg.rate) + ' / ' + lg.float];
    wrap.appendChild(h('h3', null, head.join(' · ')));
    wrap.appendChild(h('div', { class: 'muted small' }, lg.rule + (lg.closed ? ' · kapanış ' + isoToTr(lg.closed.date) + ' %' + rateText(lg.closed.rate)
      + ': sonraki dönemlerde yalnız sabit faiz farkı' : '')));
    const t = h('table', { class: 'plain trades cpn', id: 'trades-coupons-' + i });
    const cols = ['Dönem', 'Gün', 'Ödeme', 'Sabit', 'Değişken', 'Değişken %', 'Net', 'Durum'];
    t.appendChild(h('tr', null, ...cols.map((x, k) => h('th', { class: k === 0 || k === 7 ? 'l' : null,
      title: k === 5 ? 'Dönemin fixinglerinin bileşiği, basit yıllık (işleyen dönemde bugüne kadar)' : null }, x))));
    const amount = (x, bold) => td(typeof x === 'number' ? signed(x) : '—', (typeof x === 'number' ? (x > 0 ? 'pos' : (x < 0 ? 'neg' : '')) : 'muted')
      + (bold ? ' net' : ''));
    for (const p of lg.periods || []) {
      const est = (p.estimated || []).length;
      const flt = amount(p.float);
      if (est) {
        flt.appendChild(document.createTextNode(' *'));
        flt.title = est + ' günün fixing\'i tahmini: ' + p.estimated.map(isoToTr).join(', ');
      }
      t.appendChild(h('tr', { class: 'cpn-' + p.state, 'data-state': p.state },
        td(isoToTr(p.start) + ' – ' + isoToTr(p.end), 'l'), td(String(p.days)), td(isoToTr(p.pay)), amount(p.fixed), flt,
        td(typeof p.float_rate === 'number' ? '%' + num(p.float_rate, 4) : '—', typeof p.float_rate === 'number' ? null : 'muted'),
        amount(p.net, true), td(p.state === 'future' && typeof p.net === 'number' ? 'bekliyor (kapanışla belli)' : (COUPON_STATE[p.state] || p.state), 'l')));
    }
    const parts = [];
    if (lg.paid) parts.push('ödenen ' + signed(lg.paid));
    if (lg.due) parts.push('ödenecek ' + signed(lg.due));
    t.appendChild(h('tr', { class: 'sum' }, td('Gerçekleşen', 'l'), h('td', { colspan: '5' }), amount(lg.realised, true),
      td(parts.join(' · '), 'l')));
    wrap.appendChild(t);
    return wrap;
  }

  async showLog(it) {
    try {
      const res = await api.get('/api/trades/' + it.id + '/log');
      const m = modal({ title: 'İşlemin geçmişi', width: 900 });
      m.body.appendChild(h('p', { class: 'muted', style: { marginTop: '0' } }, it.text));
      m.body.appendChild(this.logTable(res.entries, false));
      m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Kapat'));
    } catch (err) { errorToast(err); }
  }

  async showRecent() {
    try {
      const res = await api.get('/api/trades/log', { scope: this.scope });
      const m = modal({ title: 'Değişiklik kaydı · ' + (this.scope === 'desk' ? 'Masa' : 'Kişisel'), width: 1000 });
      m.body.appendChild(this.logTable(res.entries, true));
      m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Kapat'));
    } catch (err) { errorToast(err); }
  }

  bondList() {
    return bondCatalog();
  }
}

/** "İşleme al" on a quant line (Sinyaller, a family's page, the line's card): the Trades form filled from the line as the
 * server has it now (tto/tradequant.py: product, legs, side, the DV01 as a nominal on the desk's lot, the entry now,
 * target and stop) - personal unless the form's "Liste" says otherwise; nothing is saved until "İşlemi kaydet". */
export async function bookLine(line) {
  try {
    openTradeForm(await api.get('/api/trades/from-quant', { id: line.id, scope: 'personal' }));
  } catch (err) { errorToast(err); }
}

/** The Trades form, filled (``prefill``: /api/trades/from-quant's answer), on whatever page is open. */
export function openTradeForm(prefill) {
  const page = { scope: prefill.scope || 'personal', data: null, reload: async () => {}, setScope: () => {}, bondList: bondCatalog };
  return new TradeForm(page, null, prefill);
}

// ---------------------------------------------------------------------- the form: a new trade, or one changed
// Every field that has a default is filled from the valuation's conventions (/api/trades/defaults) - when the form opens,
// when the product, the pair, the trade date or the expiry changes - unless the user typed into it.  A DV01 typed gives
// the nominal (rounded to 5 mn) and the DV01 it actually gives; a nominal typed wins and its DV01 is shown as information.
class TradeForm {
  constructor(page, item, prefill) {
    this.page = page;
    this.item = item;
    this.prefill = prefill || null;
    const f = item ? item.fields : (prefill ? prefill.trade : null);
    this.scope = item ? item.scope : (prefill ? prefill.scope || 'personal' : page.scope);
    this.source = prefill ? prefill.source || null : null;          // (the quant line it is taken from: kept with it)
    this.product = f ? f.product : (pref('product', 'ois'));
    if (!PRODUCTS.some((p) => p[0] === this.product)) this.product = 'ois';
    this.structure = (f && f.structure) || 'outright';
    this.values = {};                // field -> the text in its box (kept across a change of product / structure)
    this.typed = new Set();          // the fields the user typed into
    this.els = {};                   // field -> its box
    this.sized = {};                 // a sizing unit ('' or 'legs.i.') -> 'dv01' | 'notional' (what was typed)
    this.meetings = [];
    this.weights = null;
    this.seen = {};                  // what the defaults were last asked with
    this.closed = false;
    if (f) this.fromTrade(f);
    this.askPreview = debounce(() => this.preview(), 250);
    this.askSize = debounce(() => this.size(), 300);
    const from = prefill && prefill.line ? ' · ' + (prefill.line.family_label || prefill.line.family || 'quant') + ' sinyalinden' : '';
    this.m = modal({ title: item ? 'İşlemi düzenle' : 'Yeni işlem' + from, width: 980, onClose: () => { this.closed = true; this.askPreview.cancel(); this.askSize.cancel(); } });
    this.m.box.id = 'trade-form';
    if (prefill && prefill.line) {
      this.m.body.parentNode.insertBefore(h('div', { class: 'banner tf-from', id: 'tf-from' }, 'Sinyal: ' + (prefill.line.text || prefill.line.id)
        + ' - alanlar sinyalin şimdiki seviyeleriyle dolu; değiştirip "İşlemi kaydet" deyin (Masa ya da Kişisel: "Liste").'), this.m.body);
    }
    this.build();
    this.defaults();
    this.preview();
  }

  /** An existing trade into the boxes (everything counts as typed: nothing is filled over it). */
  fromTrade(f) {
    const put = (k, v) => {
      if (v === null || v === undefined || v === '') return;
      let text;
      if (typeof v === 'number') text = ['notional', 'quote_amount', 'dv01'].includes(k.split('.').pop()) ? amountText(v) : plain(v);
      else text = /^\d{4}-\d{2}-\d{2}$/.test(String(v)) ? isoToTr(v) : String(v);
      this.values[k] = text;
      this.typed.add(k);
    };
    for (const k of ['trade_date', 'settle_date', 'value_date', 'end_date', 'fra', 'isin', 'pair', 'strike', 'expiry',
      'delivery', 'notional', 'quote_amount', 'note', 'book', 'manual_price', 'premium_ccy']) put(k, f[k]);
    for (const k of ['target', 'stop']) put(k, f.product === 'fxopt' ? amountText(f[k]) : f[k]);
    if (f.tenor && (f.structure || 'outright') === 'outright') put('end_date', f.tenor);
    const meeting = f.mpc_date || f.meeting;
    if (meeting) { this.values.mpc_date = meeting; this.values.mpc_end = f.mpc_end || null; this.typed.add('mpc_date'); }
    this.values.price = f.price_kind === 'yield' ? plain(f.yield) : plain(f.price);
    if (f.product === 'fxopt') this.values.price = amountText(f.price);
    this.typed.add('price');
    for (const k of ['side', 'call_put', 'price_kind', 'amount_typed', 'dv01_ccy', 'yield_conv']) if (f[k]) this.values[k] = f[k];
    const rates = f.product === 'ois' || f.product === 'sofr';
    if (rates) this.values.side = rateSide(f.side);
    if ((f.legs || []).length) {
      // a package's side by its legs (short → long), as the form offers it
      const sides = f.legs.map((lg) => rateSide(lg.side)).join(',');
      this.values.pkg_side = Object.keys(PACKAGE_LEGS).find((k) => PACKAGE_LEGS[k].join(',') === sides) || null;
      delete this.values.side;
    }
    if (f.sized_by === 'dv01' && typeof f.dv01 === 'number') { put('dv01', f.dv01); this.sized[''] = 'dv01'; } else this.sized[''] = 'notional';
    (f.legs || []).forEach((lg, i) => {
      const p = 'legs.' + i + '.';
      put(p + 'end_date', lg.tenor || lg.end_date);
      put(p + 'notional', lg.notional);
      put(p + 'price', lg.price);
      this.values[p + 'side'] = rateSide(lg.side);
      if (lg.sized_by === 'dv01' && typeof lg.dv01 === 'number') { put(p + 'dv01', lg.dv01); this.sized[p] = 'dv01'; } else this.sized[p] = 'notional';
    });
    if ((f.legs || []).length && typeof f.dv01 === 'number') put('dv01', f.dv01);
  }

  // ------------------------------------------------------------------ boxes
  box(name, placeholder, cls) {
    const el = h('input', { type: 'text', class: 'inp' + (cls ? ' ' + cls : ''), id: 'tf-' + name.replace(/\./g, '-'), placeholder: placeholder || '',
      autocomplete: 'off', spellcheck: 'false' });
    el.value = this.values[name] || '';
    el.dataset.field = name;
    if (this.typed.has(name)) el.classList.add('typed');
    el.addEventListener('input', () => {
      this.values[name] = el.value;
      if (el.value.trim()) this.typed.add(name); else this.typed.delete(name);
      el.classList.toggle('typed', this.typed.has(name));
      el.classList.remove('info');
      this.changed(name);
    });
    el.addEventListener('keydown', (e) => { if (e.key === 'Enter') this.save(); });
    this.els[name] = el;
    return el;
  }

  /** A box filled by the form (a default, a nominal from a DV01): never over what the user typed. */
  put(name, text, info) {
    if (this.typed.has(name)) return;
    this.values[name] = text;
    const el = this.els[name];
    if (el) {
      el.value = text;
      el.classList.toggle('info', !!info);
    }
  }

  pick(name, options, label, onPick) {
    if (this.values[name] && !options.some((o) => o[0] === this.values[name])) {
      this.values[name] = null;                 // (another product's choice: RECEIVE is no side of an FX trade)
      this.typed.delete(name);
    }
    const s = seg(options, this.values[name] || null, (v) => {
      this.values[name] = v;
      this.typed.add(name);
      if (onPick) onPick(v);
      this.changed(name);
    }, 'tf-' + name.replace(/\./g, '-'));
    return field(label, s, { name });
  }

  build() {
    const body = this.m.body;
    clear(body);
    this.top = h('div', { class: 'row' });
    this.top.appendChild(field('Liste', seg([['desk', 'Masa'], ['personal', 'Kişisel']], this.scope, (v) => { this.scope = v; }, 'tf-scope')));
    if (this.item) this.top.lastChild.querySelectorAll('button').forEach((b) => { b.disabled = true; b.title = 'Liste sonradan değişmez'; });
    const prod = seg(PRODUCTS, this.product, (v) => {
      this.product = v;
      setPref('product', v);
      this.layout();
      this.defaults(true);
      this.changed('product');
    }, 'tf-product');
    if (this.item) prod.querySelectorAll('button').forEach((b) => { b.disabled = b.dataset.v !== this.product; });
    this.top.appendChild(field('Ürün', prod));
    this.structHost = h('div');
    this.top.appendChild(this.structHost);
    body.appendChild(this.top);
    this.common = h('div', { class: 'row' });
    body.appendChild(this.common);
    this.specific = h('div', { class: 'tf-specific' });
    body.appendChild(this.specific);
    this.extra = h('div', { class: 'row' });
    body.appendChild(this.extra);
    this.previewEl = h('div', { class: 'quotebox tf-preview', id: 'tf-preview' });
    body.appendChild(this.previewEl);
    this.saveBtn = h('button', { class: 'btn primary', type: 'button', id: 'tf-save' }, this.item ? 'Değişikliği kaydet' : 'İşlemi kaydet');
    this.saveBtn.addEventListener('click', () => this.save());
    this.m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => this.m.close() }, 'Vazgeç'));
    this.m.foot.appendChild(this.saveBtn);
    this.layout();
  }

  /** The boxes of the product (and of an OIS's structure); what was typed in a box of the same name stays. */
  layout() {
    this.els = {};
    clear(this.structHost);
    clear(this.common);
    clear(this.specific);
    clear(this.extra);
    const p = this.product;
    const rates = p === 'ois' || p === 'sofr';
    if (rates) {
      this.structHost.appendChild(field('Yapı', seg(STRUCTURES, this.structure, (v) => {
        this.structure = v;
        this.layout();
        this.defaults(true);
        this.changed('structure');
      }, 'tf-structure')));
    }
    const st = rates ? this.structure : null;
    const priceLabel = rates ? (st === 'spread' || st === 'fly' ? null : (st === 'fra' ? 'FRA oranı (%)' : (st === 'mpc' ? 'Dönem oranı (%)' : 'Sabit oran (%)')))
      : (p === 'dibs' ? (this.values.price_kind === 'yield' ? 'Getiri (%)' : 'Temiz fiyat') : (p === 'fxspot' ? 'Kur' : 'Prim tutarı'));
    this.common.appendChild(field('İşlem tarihi', this.box('trade_date', 'gg.aa.yyyy'), { name: 'trade_date', width: '130px' }));
    this.common.appendChild(field(p === 'fxopt' ? 'Prim valörü (settle)' : 'Valör (settle)', this.box('settle_date', 'gg.aa.yyyy ya da +1'), { name: 'settle_date', width: '150px' }));
    if (priceLabel) this.common.appendChild(field(priceLabel, this.box('price', p === 'fxopt' ? 'örn. 150k' : (rates ? 'örn. 38,50' : ''), 'num'), { name: 'price', width: '140px' }));
    if (rates) this.layoutRates(st);
    else if (p === 'dibs') this.layoutDibs();
    else if (p === 'fxspot') this.layoutFxSpot();
    else this.layoutFxOpt();
    // target and stop (optional) in the trade's own quote: İzleme's "hedefe geldi" / "stopa geldi" alarms follow them
    const lu = levelUnitOf(p, st, this.values.price_kind);
    const hint = rates ? (st === 'spread' || st === 'fly' ? 'örn. -20,0' : 'örn. 37,50') : (p === 'fxopt' ? 'örn. 300k' : 'opsiyonel');
    this.levelsRow = h('div', { class: 'row tf-levels' },
      field('Hedef (' + lu + ')', this.box('target', hint, 'num'), { name: 'target', width: '150px' }),
      field('Stop (' + lu + ')', this.box('stop', hint, 'num'), { name: 'stop', width: '150px' }),
      h('div', { class: 'muted small tf-levels-note' }, 'İsteğe bağlı. Kaydedince İzleme\'de alarm kurulur ("hedefe geldi" / "stopa geldi"; masanın işleminde herkese); '
        + 'satırda hedefe ve stopa kalan görünür. Boş bırakılan kaldırılır.'));
    this.specific.appendChild(this.levelsRow);
    this.extra.appendChild(field('Elle fiyat (piyasa fiyatlayamazsa)', this.box('manual_price', 'opsiyonel', 'num'), { name: 'manual_price', width: '190px' }));
    this.extra.appendChild(field('Karşı taraf / defter', this.box('book', 'opsiyonel'), { name: 'book', width: '170px' }));
    this.extra.appendChild(field('Not', this.box('note', 'opsiyonel'), { name: 'note', width: '300px' }));
  }

  sizing(prefix, ccy) {
    const n = this.box(prefix + 'notional', 'örn. 100m', 'num');
    const d = this.box(prefix + 'dv01', 'örn. 1.000', 'num');
    d.title = 'DV01 yazınca nominal 5 milyona yuvarlanarak hesaplanır; nominal yazarsanız nominal kalır, DV01 bilgi olarak görünür.';
    const echo = h('div', { class: 'muted echo', id: 'tf-' + prefix.replace(/\./g, '-') + 'dv01-echo' });
    this.els[prefix + '#echo'] = echo;
    return [field('Nominal (' + ccy + ')', n, { name: prefix + 'notional', width: '150px' }),
      field('DV01 (' + (this.values.dv01_ccy === 'TRY' ? 'TL' : '$') + ' / bp)', h('div', null, d, echo), { name: prefix + 'dv01', width: '150px' })];
  }

  dv01Ccy() {
    return seg([['USD', '$'], ['TRY', 'TL']], this.values.dv01_ccy || 'USD', (v) => {
      this.values.dv01_ccy = v;
      this.layout();
      this.changed('dv01_ccy');
    }, 'tf-dv01_ccy');
  }

  layoutRates(st) {
    const ccy = this.product === 'ois' ? 'TL' : 'USD';
    const row = h('div', { class: 'row' });
    this.specific.appendChild(row);
    if (st === 'outright' || st === 'mpc' || st === 'fra') {
      row.appendChild(this.pick('side', [['receive', 'RECEIVE'], ['pay', 'PAY']], 'Yön (sabit)'));
      if (st === 'outright') {
        row.appendChild(field('Başlangıç', this.box('value_date', 'valör ya da 1A'), { name: 'value_date', width: '130px' }));
        row.appendChild(field('Vade / bitiş', this.box('end_date', 'örn. 2Y ya da tarih'), { name: 'end_date', width: '150px' }));
      } else if (st === 'mpc') {
        // the meeting by its date (the period from its effective day to the next meeting's): never a row of the calendar
        const sel = h('select', { class: 'inp', id: 'tf-meeting' });
        this.els.mpc_date = sel;
        this.fillMeetings();
        sel.addEventListener('change', () => {
          this.values.mpc_date = sel.value;
          this.typed.add('mpc_date');
          const m = this.meetings.find((x) => x.meeting === sel.value);
          this.values.mpc_end = m && m.mpc_end ? m.mpc_end : null;
          this.values.value_date = m && m.start ? isoToTr(m.start) : '';
          this.values.end_date = m && m.end ? isoToTr(m.end) : '';
          this.changed('mpc_date');
        });
        row.appendChild(field(this.product === 'ois' ? 'PPK toplantısı' : 'FOMC toplantısı', sel, { name: 'mpc_date', width: '260px' }));
      } else {
        row.appendChild(field('FRA', this.box('fra', 'örn. 3x6'), { name: 'fra', width: '100px' }));
        row.appendChild(field('Başlangıç', this.box('value_date', 'ya da tarih'), { name: 'value_date', width: '130px' }));
        row.appendChild(field('Bitiş', this.box('end_date', 'ya da tarih'), { name: 'end_date', width: '130px' }));
      }
      row.appendChild(field('DV01 dövizi', this.dv01Ccy()));
      for (const el of this.sizing('', ccy)) row.appendChild(el);
      return;
    }
    // a spread / fly: the package's side and DV01, then its legs (each its own tenor, side, nominal or DV01, rate)
    const sides = PACKAGE_SIDES[st];
    if (!sides.some((x) => x[0] === this.values.pkg_side)) this.values.pkg_side = null;
    row.appendChild(this.pick('pkg_side', sides, 'Paket yönü', (v) => {
      (PACKAGE_LEGS[v] || []).forEach((s, i) => {
        if (!this.typed.has('legs.' + i + '.side')) { this.values['legs.' + i + '.side'] = s; }
      });
      this.layout();
    }));
    row.appendChild(field('Başlangıç', this.box('value_date', 'valör ya da 1A'), { name: 'value_date', width: '130px' }));
    row.appendChild(field('DV01 dövizi', this.dv01Ccy()));
    const pkg = this.box('dv01', 'örn. 1.000', 'num');
    pkg.title = 'Paketin DV01\'i: bacaklara ağırlıklarıyla dağıtılır (spread 1:1, fly 50/50) - bacağına nominal yazdığınız bacak hariç';
    row.appendChild(field('Paket DV01 (' + (this.values.dv01_ccy === 'TRY' ? 'TL' : '$') + ' / bp)', pkg, { name: 'dv01', width: '150px' }));
    this.levelEl = h('div', { class: 'muted', id: 'tf-level' });
    row.appendChild(field('Paket seviyesi', this.levelEl));
    const names = LEG_NAMES[st];
    const legs = h('table', { class: 'plain tf-legs', id: 'tf-legs' });
    legs.appendChild(h('tr', null, h('th', { class: 'l' }, 'Bacak'), h('th', { class: 'l' }, 'Yön'), h('th', { class: 'l' }, 'Vade'),
      h('th', { class: 'l' }, 'Nominal (' + ccy + ')'), h('th', { class: 'l' }, 'DV01'), h('th', { class: 'l' }, 'Oran (%)')));
    names.forEach((label, i) => {
      const p = 'legs.' + i + '.';
      const side = seg([['receive', 'REC'], ['pay', 'PAY']], this.values[p + 'side'] || null, (v) => {
        this.values[p + 'side'] = v;
        this.typed.add(p + 'side');
        this.changed(p + 'side');
      }, 'tf-leg' + i + '-side');
      const [n, d] = this.sizing(p, ccy);
      const cell = (el, name) => h('td', { class: 'l' }, el, name ? h('div', { class: 'echo muted', 'data-echo': name }) : null,
        name ? h('div', { class: 'ferr', 'data-for': name }) : null);
      legs.appendChild(h('tr', { 'data-leg': String(i) }, h('td', { class: 'l' }, label), cell(side, p + 'side'),
        cell(this.box(p + 'end_date', 'örn. 2Y'), p + 'end_date'), cell(n.querySelector('input'), p + 'notional'),
        cell(d.querySelector('div'), p + 'dv01'), cell(this.box(p + 'price', 'örn. 38,50', 'num'), p + 'price')));
    });
    this.specific.appendChild(legs);
  }

  fillMeetings() {
    const sel = this.els.mpc_date;
    if (!sel) return;
    clear(sel);
    sel.appendChild(h('option', { value: '' }, this.meetings.length ? 'Toplantı seçin' : 'takvimde toplantı yok'));
    for (const m of this.meetings) sel.appendChild(h('option', { value: m.meeting }, m.label || isoToTr(m.meeting)));
    if (this.values.mpc_date && !this.meetings.some((m) => m.meeting === this.values.mpc_date)) {
      sel.appendChild(h('option', { value: this.values.mpc_date }, isoToTr(this.values.mpc_date) + ' (takvimde yok)'));
    }
    sel.value = this.values.mpc_date || '';
  }

  layoutDibs() {
    const row = h('div', { class: 'row' });
    const isin = this.box('isin', 'TRT…');
    const list = h('datalist', { id: 'tf-isins' });
    isin.setAttribute('list', 'tf-isins');
    this.page.bondList().then((bonds) => {
      for (const b of bonds) list.appendChild(h('option', { value: b.isin }, b.label + (b.kind_text ? ' · ' + b.kind_text : '') + (b.lists && b.lists.length ? ' · ' + b.lists.join(', ') : '')));
    });
    row.appendChild(field('ISIN (DİBS RV / Tüm Kâğıtlar)', h('div', null, isin, list), { name: 'isin', width: '190px' }));
    row.appendChild(this.pick('side', [['B', 'ALIŞ'], ['S', 'SATIŞ']], 'Yön'));
    if (!this.values.price_kind) this.values.price_kind = 'price';
    row.appendChild(this.pick('price_kind', [['price', 'Temiz fiyat'], ['yield', 'Getiri']], 'Fiyat', () => this.layout()));
    if (this.values.price_kind === 'yield') {
      if (!this.values.yield_conv) this.values.yield_conv = 'bileşik';
      row.appendChild(this.pick('yield_conv', [['bileşik', 'Bileşik'], ['basit', 'Basit']], 'Getiri kuralı'));
    }
    row.appendChild(field('DV01 dövizi', this.dv01Ccy()));
    for (const el of this.sizing('', 'TL')) row.appendChild(el);
    this.specific.appendChild(row);
  }

  pairBox() {
    const pair = this.box('pair', 'örn. USDTRY');
    const list = h('datalist', { id: 'tf-pairs' }, ...PAIRS.map((x) => h('option', { value: x })));
    pair.setAttribute('list', 'tf-pairs');
    return field('Parite', h('div', null, pair, list), { name: 'pair', width: '120px' });
  }

  codes() {
    const p = String(this.values.pair || '').replace(/[^A-Za-z]/g, '').toUpperCase();
    const pair = p.length === 3 && p !== 'TRY' ? p + 'TRY' : p;
    return pair.length === 6 ? [pair.slice(0, 3), pair.slice(3)] : ['1. döviz', '2. döviz'];
  }

  layoutFxSpot() {
    const row = h('div', { class: 'row' });
    const [base, quote] = this.codes();
    row.appendChild(this.pairBox());
    row.appendChild(this.pick('side', [['B', 'ALIŞ'], ['S', 'SATIŞ']], 'Yön (' + base + ')'));
    if (!this.values.amount_typed) this.values.amount_typed = 'base';
    row.appendChild(this.pick('amount_typed', [['base', base], ['quote', quote]], 'Tutarın dövizi', () => this.layout()));
    if (this.values.amount_typed === 'quote') row.appendChild(field('Tutar (' + quote + ')', this.box('quote_amount', 'örn. 420m', 'num'), { name: 'quote_amount', width: '150px' }));
    else row.appendChild(field('Tutar (' + base + ')', this.box('notional', 'örn. 10m', 'num'), { name: 'notional', width: '150px' }));
    this.specific.appendChild(row);
  }

  layoutFxOpt() {
    const row = h('div', { class: 'row' });
    const [base, quote] = this.codes();
    row.appendChild(this.pairBox());
    row.appendChild(this.pick('call_put', [['call', 'CALL'], ['put', 'PUT']], 'Call / put'));
    row.appendChild(this.pick('side', [['B', 'ALIŞ'], ['S', 'SATIŞ']], 'Yön'));
    row.appendChild(field('Strike', this.box('strike', 'örn. 45,00', 'num'), { name: 'strike', width: '110px' }));
    row.appendChild(field('Vade (expiry)', this.box('expiry', 'örn. 1A ya da tarih'), { name: 'expiry', width: '130px' }));
    row.appendChild(field('Teslim', this.box('delivery', 'gg.aa.yyyy'), { name: 'delivery', width: '130px' }));
    row.appendChild(field('Nominal (' + base + ')', this.box('notional', 'örn. 10m', 'num'), { name: 'notional', width: '140px' }));
    const pc = h('select', { class: 'inp', id: 'tf-premium_ccy' });
    for (const c of [quote, base]) pc.appendChild(h('option', { value: c }, c));
    if (this.values.premium_ccy && ![quote, base].includes(this.values.premium_ccy)) pc.appendChild(h('option', { value: this.values.premium_ccy }, this.values.premium_ccy));
    pc.value = this.values.premium_ccy || quote;
    this.values.premium_ccy = pc.value;
    pc.addEventListener('change', () => { this.values.premium_ccy = pc.value; this.typed.add('premium_ccy'); this.changed('premium_ccy'); });
    this.els.premium_ccy = pc;
    row.appendChild(field('Prim dövizi', pc, { name: 'premium_ccy' }));
    this.specific.appendChild(row);
  }

  // ------------------------------------------------------------------ what follows a change
  changed(name) {
    const leaf = name.split('.').pop();
    if (leaf === 'dv01' || leaf === 'notional') {
      const prefix = name.slice(0, name.length - leaf.length);
      const st = this.structure;
      if (prefix === '' && leaf === 'dv01' && (this.product === 'ois' || this.product === 'sofr') && (st === 'spread' || st === 'fly')) {
        this.spreadPackage();
      } else if (this.values[name] && this.values[name].trim()) {
        // the one typed last sizes the trade: the other one is worked out (a nominal typed wins until a DV01 is typed)
        this.sized[prefix] = leaf;
        this.typed.delete(prefix + (leaf === 'notional' ? 'dv01' : 'notional'));
      } else if (this.sized[prefix] === leaf) {
        delete this.sized[prefix];
      }
    }
    if (name === 'pair') this.layoutKeep();
    this.askPreview();
    this.askSize();
  }

  /** The pair changed: the boxes named by its currencies follow (what was typed stays). */
  layoutKeep() {
    if (this.product !== 'fxspot' && this.product !== 'fxopt') return;
    const focus = document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.field : null;
    const pos = focus && this.els[focus] ? this.els[focus].selectionStart : null;
    if (!this.typed.has('premium_ccy')) delete this.values.premium_ccy;
    this.layout();
    if (focus && this.els[focus]) {
      this.els[focus].focus();
      if (pos !== null) this.els[focus].setSelectionRange(pos, pos);
    }
  }

  /** A package's DV01: each leg's DV01 by its weight (spread 1:1, fly 50/50) - a leg whose nominal was typed keeps it. */
  spreadPackage() {
    const st = this.structure;
    const total = parseAmountLoose(this.values.dv01);
    const w = weightsOf(this.weights, st);
    w.forEach((x, i) => {
      const p = 'legs.' + i + '.';
      if (this.sized[p] === 'notional' && this.typed.has(p + 'notional')) return;
      if (total === null) return;
      const d = Math.abs(x) * total;
      this.values[p + 'dv01'] = num(d, 0);
      if (this.els[p + 'dv01']) { this.els[p + 'dv01'].value = num(d, 0); this.els[p + 'dv01'].classList.remove('info'); }
      this.sized[p] = 'dv01';
    });
  }

  units() {
    const p = this.product;
    if (p !== 'ois' && p !== 'sofr' && p !== 'dibs') return [];
    if ((p === 'ois' || p === 'sofr') && (this.structure === 'spread' || this.structure === 'fly')) {
      return LEG_NAMES[this.structure].map((_, i) => ['legs.' + i + '.', i]);
    }
    return [['', null]];
  }

  async size() {
    if (this.closed) return;
    const asks = [];
    const prefixes = [];
    for (const [prefix, leg] of this.units()) {
      const how = this.sized[prefix];
      const ccy = this.values.dv01_ccy || 'USD';
      if (how === 'dv01' && (this.values[prefix + 'dv01'] || '').trim()) asks.push({ leg, dv01: this.values[prefix + 'dv01'], dv01_ccy: ccy });
      else if (how === 'notional' && (this.values[prefix + 'notional'] || '').trim()) asks.push({ leg, notional: this.values[prefix + 'notional'], dv01_ccy: ccy });
      else continue;
      prefixes.push([prefix, how]);
    }
    if (!asks.length) return;
    const ticket = (this.sizeTicket = (this.sizeTicket || 0) + 1);
    let res;
    try {
      res = await api.post('/api/trades/dv01', Object.assign(this.payload(), { size: asks }));
    } catch (e) { return; }
    if (this.closed || ticket !== this.sizeTicket) return;
    res.units.forEach((u, i) => {
      const [prefix, how] = prefixes[i];
      const echo = this.els[prefix + '#echo'];
      const unit = (u.dv01_ccy === 'TRY' ? ' TL' : ' $');
      if (u.why) { if (echo) echo.textContent = u.why; return; }
      if (how === 'dv01') {
        this.put(prefix + 'notional', amountText(u.notional));
        if (echo) echo.textContent = typeof u.dv01 === 'number' ? 'DV01 ≈ ' + num(u.dv01, 0) + unit + ' (' + amountText(u.notional) + ')' : '';
      } else {
        this.put(prefix + 'dv01', num(u.dv01, 0), true);              // information only: the nominal typed counts
        if (echo) echo.textContent = 'bilgi: bu nominalin DV01\'i';
      }
    });
    this.askPreview();
  }

  /** The defaults of the valuation: the boxes not typed into get them (and the meetings, the legs' weights). */
  async defaults(force) {
    if (this.closed) return;
    const q = { product: this.product };
    const t = this.lastTrade || {};
    const pair = t.pair || null;
    const td = t.trade_date || trToIso(this.values.trade_date);
    const exp = t.expiry || trToIso(this.values.expiry);
    if (pair) q.pair = pair;
    if (td) q.trade_date = td;
    if (this.product === 'fxopt' && exp) q.expiry = exp;
    // what else the conventions need: an FRA's "3x6" (its dates), a bond's ISIN (a bill settles the same day), the shape
    const rates = this.product === 'ois' || this.product === 'sofr';
    if (rates) q.structure = this.structure;
    if (rates && this.structure === 'fra' && (t.fra || this.values.fra)) q.fra = String(t.fra || this.values.fra).trim();
    if (this.product === 'dibs' && t.isin) q.isin = t.isin;
    const key = JSON.stringify(q);
    if (!force && key === this.seen.key) return;
    this.seen.key = key;
    let d;
    try { d = await api.get('/api/trades/defaults', q); } catch (e) { return; }
    if (this.closed || this.seen.key !== key) return;
    if (Array.isArray(d.meetings)) { this.meetings = d.meetings; this.fillMeetings(); }
    if (d.weights) this.weights = d.weights;
    for (const k of ['trade_date', 'settle_date', 'value_date', 'end_date', 'expiry', 'delivery']) {
      if (typeof d[k] === 'string' && d[k] && !(k === 'value_date' && this.structure === 'mpc')) this.put(k, isoToTr(d[k]));
    }
    if (typeof d.premium_ccy === 'string' && !this.typed.has('premium_ccy') && this.els.premium_ccy) {
      const sel = this.els.premium_ccy;
      if (![...sel.options].some((o) => o.value === d.premium_ccy)) sel.appendChild(h('option', { value: d.premium_ccy }, d.premium_ccy));
      sel.value = d.premium_ccy;
      this.values.premium_ccy = d.premium_ccy;
    }
    if (typeof d.dv01_ccy === 'string' && !this.typed.has('dv01_ccy') && !this.values.dv01_ccy) this.values.dv01_ccy = d.dv01_ccy;
    this.askPreview();
  }

  payload() {
    const v = this.values;
    const p = { scope: this.scope, product: this.product, trade_date: v.trade_date || '', settle_date: v.settle_date || '',
      price: v.price || '', manual_price: v.manual_price || '', book: v.book || '', note: v.note || '', target: v.target || '', stop: v.stop || '' };
    if (this.source && !this.item) p.source = this.source;
    const sizing = (prefix, out) => {
      out.notional = v[prefix + 'notional'] || '';
      out.sized_by = this.sized[prefix] || 'notional';
      if (out.sized_by === 'dv01') out.dv01 = v[prefix + 'dv01'] || '';
      out.dv01_ccy = v.dv01_ccy || 'USD';
    };
    if (this.product === 'ois' || this.product === 'sofr') {
      const st = this.structure;
      p.structure = st;
      p.side = (st === 'spread' || st === 'fly' ? v.pkg_side : v.side) || '';
      p.value_date = v.value_date || '';
      if (st === 'outright') p.end_date = v.end_date || '';
      if (st === 'mpc') { p.mpc_date = v.mpc_date || ''; p.mpc_end = v.mpc_end || ''; p.end_date = v.end_date || ''; }
      if (st === 'fra') { p.fra = v.fra || ''; p.end_date = v.end_date || ''; }
      if (st === 'spread' || st === 'fly') {
        delete p.price;
        p.dv01 = v.dv01 || '';
        p.dv01_ccy = v.dv01_ccy || 'USD';
        p.weights = weightsOf(this.weights, st);
        p.legs = LEG_NAMES[st].map((_, i) => {
          const q = 'legs.' + i + '.';
          const leg = { side: v[q + 'side'] || '', end_date: v[q + 'end_date'] || '', price: v[q + 'price'] || '' };
          sizing(q, leg);
          return leg;
        });
      } else sizing('', p);
    } else if (this.product === 'dibs') {
      Object.assign(p, { isin: v.isin || '', side: v.side || '', price_kind: v.price_kind || 'price' });
      if (p.price_kind === 'yield') p.yield_conv = v.yield_conv || 'bileşik';
      sizing('', p);
    } else if (this.product === 'fxspot') {
      Object.assign(p, { pair: v.pair || '', side: v.side || '', amount_typed: v.amount_typed || 'base' });
      if (p.amount_typed === 'quote') p.quote_amount = v.quote_amount || ''; else p.notional = v.notional || '';
    } else {
      Object.assign(p, { pair: v.pair || '', call_put: v.call_put || '', side: v.side || '', strike: v.strike || '', expiry: v.expiry || '',
        delivery: v.delivery || '', notional: v.notional || '', premium_ccy: v.premium_ccy || '' });
    }
    return p;
  }

  /** The form read by the server as saving reads it: the trade in the desk's words, or what does not read yet. */
  async preview() {
    if (this.closed) return;
    const ticket = (this.previewTicket = (this.previewTicket || 0) + 1);
    let res;
    try { res = await api.post('/api/trades/check', this.payload()); } catch (e) { return; }
    if (this.closed || ticket !== this.previewTicket) return;
    this.lastTrade = res.trade || {};
    this.showErrors(res.ok ? {} : res.fields, res.echo || {}, false);
    clear(this.previewEl);
    if (res.ok) {
      this.previewEl.appendChild(h('div', { class: 'tf-text', id: 'tf-text' }, res.text));
      for (const lg of res.legs || []) this.previewEl.appendChild(h('div', { class: 'muted' }, '↳ ' + lg));
      // an FX option: its premium as a vol, beside the screen's smile (a dealer's premium checked before it is saved)
      if (res.vol) this.previewEl.appendChild(premiumVolLine(res.vol));
    } else {
      this.previewEl.appendChild(h('div', { class: 'muted' }, 'Eksik ya da hatalı alanları doldurun.'));
    }
    if (this.levelEl) this.levelEl.textContent = res.trade && typeof res.trade.price === 'number' ? signed(res.trade.price, 1) + ' bp' : '—';
    // what follows from a pair, a trade date or an expiry typed: the defaults again (never over what was typed)
    this.defaults(false);
  }

  /** Each field's message under it (``shout``: also the ones the user has not typed into yet - after "kaydet"). */
  showErrors(fields, echo, shout) {
    for (const el of this.m.body.querySelectorAll('.ferr')) {
      const name = el.dataset.for;
      const msg = fields && fields[name];
      el.textContent = msg && (shout || this.typed.has(name) || (this.values[name] || '').trim()) ? msg : '';
    }
    for (const el of this.m.body.querySelectorAll('[data-echo]')) {
      const name = el.dataset.echo;
      el.textContent = echo && echo[name] ? echo[name] : '';
    }
    if (fields && fields.legs && shout) toast(fields.legs, 'err');
    if (fields && fields._) {
      clear(this.previewEl);
      this.previewEl.appendChild(h('div', { class: 'errtxt' }, fields._));
    }
  }

  async save() {
    this.saveBtn.disabled = true;
    try {
      const body = this.payload();
      const res = this.item ? await api.post('/api/trades/' + this.item.id, body) : await api.post('/api/trades', body);
      this.m.close();
      const al = res.alarms || {};
      const said = al.full ? ' · alarm listesi dolu: ' + al.full + ' alarm kurulamadı' : (al.set ? ' · İzleme\'de ' + al.set + ' alarm kuruldu' : '');
      toast(this.item ? (res.changed ? 'İşlem değişti: ' + res.text + said : 'Değişiklik yok')
        : 'Kaydedildi: ' + res.text + (this.prefill ? ' (Trades → ' + (res.scope === 'desk' ? 'Masa' : 'Kişisel') + ')' : '') + said, al.full ? 'warn' : 'ok', 5200);
      if (!this.item && res.scope && res.scope !== this.page.scope) this.page.setScope(res.scope);
      else await this.page.reload();
    } catch (err) {
      if (err.data && err.data.fields) this.showErrors(err.data.fields, {}, true);
      errorToast(err);
    } finally {
      this.saveBtn.disabled = false;
    }
  }
}

/** A DV01 / amount as typed (5k, 1.000), as the server reads it (null when it does not read). */
function parseAmountLoose(text) {
  const m = /^\s*([+-]?[\d.,\s]+?)\s*(k|bin|m|mn|mio)?\s*$/i.exec(text || '');
  if (!m) return null;
  let s = m[1].replace(/\s/g, '');
  const en = settings.lang === 'en';
  if (en) s = s.replace(/,/g, ''); else s = s.replace(/\.(?=\d{3}(\D|$))/g, '').replace(',', '.');
  const x = parseFloat(s);
  if (!isFinite(x)) return null;
  const u = (m[2] || '').toLowerCase();
  return x * (u === 'k' || u === 'bin' ? 1e3 : (u ? 1e6 : 1));
}
