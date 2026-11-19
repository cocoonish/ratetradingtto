// Swaption: a TRY OIS swaption to look at (tto/swaption.py) - pick the expiry × tenor and see the underlying (Fiyatlama's
// forward-start TRY OIS) on your own curve with the other beside it, the realized vols of its forward from the history's
// closes (bp/day, bp/year, % Black), and payer / receiver / straddle with their greeks at the vol used - the realized 60
// changes', or one typed in any of the three units -, the rate at the expiry and the breakevens.  Nothing is booked and
// nothing is stored on the server: the inputs go with each request, the last ones stay in this browser only.
import { api } from '../api.js';
import { h, clear, debounce } from '../ui.js';
import { num, pct, serialDate, isoToTr } from '../format.js';

const KEY = 'tto.swaption';
const EXPIRIES = ['1M', '3M', '6M', '9M', '1Y', '2Y', '3Y', '5Y'];
const TENORS = ['1Y', '2Y', '3Y', '4Y', '5Y', '7Y', '10Y'];
const MONTHS = { '1M': 1, '3M': 3, '6M': 6, '9M': 9, '1Y': 12, '2Y': 24, '3Y': 36, '4Y': 48, '5Y': 60, '7Y': 84, '10Y': 120 };
const DEFAULTS = { expiry: '1Y', tenor: '2Y', strike: '', notional: '100m', vol: '', vol_unit: 'day' };
const METHOD = { boot: 'Bootstrap (Murex)', ppk: 'PPK basamak' };
const UNITS = [['day', 'bp/gün', 'Normal vol, bir iş gününde (= günlük başabaş hareket)'],
  ['year', 'bp/yıl', 'Normal vol, yıllık (= bp/gün · √252)'],
  ['black', '% Black', 'Lognormal vol: aynı payer primini veren Black vol\'ü']];
const KINDS = [['payer', 'Payer'], ['receiver', 'Receiver'], ['straddle', 'Straddle']];

const isNum = (v) => typeof v === 'number' && isFinite(v);
const dash = (s) => (s === '' || s === null || s === undefined ? '–' : s);
const rate = (v) => dash(isNum(v) ? pct(v, 4) : '');
const signed = (v, d) => (isNum(v) ? (v > 0 && Number(v.toFixed(d)) !== 0 ? '+' : '') + num(Number(v.toFixed(d)) === 0 ? 0 : v, d) : '–');
const volText = { day: (v) => dash(num(v, 2)), year: (v) => dash(num(v, 1)), black: (v) => dash(isNum(v) ? pct(v, 2) : '') };

function load() {
  try {
    const v = JSON.parse(localStorage.getItem(KEY) || 'null');
    if (v && typeof v === 'object') return Object.assign({}, DEFAULTS, v);
  } catch (e) { /* a private window, a value of another version */ }
  return Object.assign({}, DEFAULTS);
}

function save(state) {
  try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) { /* a private window */ }
}

function seg(id, items, onPick) {
  const box = h('div', { class: 'seg', id, role: 'group' });
  for (const item of items) {
    const [v, label, tip] = Array.isArray(item) ? item : [item, item];
    const b = h('button', { type: 'button', title: tip || null }, label);
    b.dataset.v = v;
    b.addEventListener('click', () => onPick(v));
    box.appendChild(b);
  }
  return box;
}

function pickSeg(box, v) {
  for (const b of box.children) b.classList.toggle('on', b.dataset.v === v);
}

function tile(label, value, opts = {}) {
  const el = h('div', { class: 'q' + (opts.big ? ' big' : '') }, h('div', { class: 'l' }, label), h('div', { class: 'v' }, value));
  if (opts.title) el.title = opts.title;
  if (opts.id) el.id = opts.id;
  return el;
}

function field(label, control, id) {
  return h('div', { class: 'field', id: id || null }, h('label', null, label), control);
}

export class SwaptionPage {
  constructor(host, ctx) {
    this.host = host;
    this.ctx = ctx;
    this.state = load();
    this.data = null;
    this.seq = 0;
    this.later = debounce(() => this.ask(), 400);
    this.build();
  }

  build() {
    const box = (id, key, placeholder, cls) => {
      const el = h('input', { type: 'text', id, class: 'inp' + (cls ? ' ' + cls : ''), placeholder, autocomplete: 'off', spellcheck: 'false' });
      el.value = this.state[key] || '';
      el.addEventListener('input', () => { this.state[key] = el.value.trim(); this.later(); });
      el.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); this.state[key] = el.value.trim(); this.now(); } });
      return el;
    };
    this.expiryIn = box('swpt-expiry', 'expiry', '1Y, 18M, 2Y3M');
    this.tenorIn = box('swpt-tenor', 'tenor', '2Y, 5Y, 10Y');
    this.strikeIn = box('swpt-strike', 'strike', 'ATM', 'num');
    this.notionalIn = box('swpt-notional', 'notional', '100m', 'num');
    this.expirySeg = seg('swpt-expiry-presets', EXPIRIES, (v) => this.pick('expiry', v));
    this.tenorSeg = seg('swpt-tenor-presets', TENORS, (v) => this.pick('tenor', v));
    // the vol: typed in one unit - the other two boxes show what it is in theirs; none typed: the realized 60 changes'
    this.volIn = {};
    const vols = h('div', { class: 'swpt-vols' });
    for (const [unit, label, tip] of UNITS) {
      const el = h('input', { type: 'text', id: 'swpt-vol-' + unit, class: 'inp num', autocomplete: 'off', spellcheck: 'false', title: tip });
      el.addEventListener('input', () => this.typeVol(unit, el.value));
      el.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); this.typeVol(unit, el.value); this.now(); } });
      this.volIn[unit] = el;
      vols.appendChild(h('label', { class: 'swpt-vol', title: tip }, h('span', null, label), el));
    }
    if (this.state.vol && this.volIn[this.state.vol_unit]) this.volIn[this.state.vol_unit].value = this.state.vol;
    this.volReset = h('button', { type: 'button', class: 'btn', id: 'swpt-vol-reset', title: 'Yazılan vol\'ü sil: 60 değişimlik gerçekleşen vol' },
      'Gerçekleşen vol');
    this.volReset.addEventListener('click', () => { this.typeVol(this.state.vol_unit, ''); this.now(); });
    vols.appendChild(this.volReset);
    this.curveInfo = h('span', { class: 'muted', id: 'swpt-curve' });
    this.stamp = h('span', { class: 'muted', id: 'swpt-stamp' });
    const form = h('section', { class: 'panel wide', id: 'swpt-form' },
      h('header', null, h('h2', null, 'Swaption · TRY OIS (yalnız görüntüleme)'), this.curveInfo, this.stamp),
      h('div', { class: 'swpt-fields' },
        field('Opsiyon vadesi', h('div', { class: 'swpt-pair' }, this.expirySeg, this.expiryIn)),
        field('Swap vadesi', h('div', { class: 'swpt-pair' }, this.tenorSeg, this.tenorIn)),
        field('Strike (%)', this.strikeIn), field('Nominal (TL)', this.notionalIn),
        field('Vol (birini yazın)', vols)),
      this.errorLine = h('div', { class: 'errtxt swpt-error', id: 'swpt-error' }));
    this.head = h('div', { class: 'swpt-head', id: 'swpt-head' });
    this.noVol = h('div', { class: 'banner hidden', id: 'swpt-novol' });
    this.tiles = h('div', { class: 'quote swpt-tiles', id: 'swpt-tiles' });
    this.optBody = h('div', { class: 'body' });
    this.rangeBody = h('div', { class: 'body' });
    this.realBody = h('div', { class: 'body' });
    this.realNote = h('div', { class: 'note', id: 'swpt-realized-note' });
    this.schedBody = h('div', { class: 'body' });
    this.schedTitle = h('h2', null, 'Dayanak swap');
    this.notes = h('div', { class: 'body swpt-notes', id: 'swpt-notes' });
    this.result = h('div', { class: 'panels', id: 'swpt-result' },
      h('section', { class: 'panel wide' }, h('div', { class: 'pad' }, this.head, this.noVol, this.tiles)),
      h('section', { class: 'panel', id: 'swpt-options-panel' },
        h('header', null, h('h2', null, 'Payer · Receiver · Straddle (alıcının gözünden)')), this.optBody),
      h('section', { class: 'panel', id: 'swpt-range-panel' },
        h('header', null, h('h2', null, 'Vadede faiz (normal model)')), this.rangeBody),
      h('section', { class: 'panel', id: 'swpt-realized-panel' },
        h('header', null, h('h2', null, 'Gerçekleşen vol (forward\'ın günlük değişimi)')), this.realBody, this.realNote),
      h('section', { class: 'panel', id: 'swpt-schedule-panel' }, h('header', null, this.schedTitle), this.schedBody),
      h('section', { class: 'panel wide', id: 'swpt-notes-panel' }, h('header', null, h('h2', null, 'Model ve konvansiyonlar')), this.notes));
    this.host.appendChild(h('div', { class: 'panels swaption', id: 'swaption' }, form, this.result));
    this.marks();
  }

  /** The presets of the inputs as they are typed, and the tenors that would take expiry + tenor beyond 10Y dimmed. */
  marks() {
    pickSeg(this.expirySeg, (this.state.expiry || '').toUpperCase());
    pickSeg(this.tenorSeg, (this.state.tenor || '').toUpperCase());
    const e = this.data && !this.data.error ? this.data.expiry_m : MONTHS[(this.state.expiry || '').toUpperCase()];
    for (const b of this.tenorSeg.children) {
      const far = isNum(e) && e + MONTHS[b.dataset.v] > 120;
      b.classList.toggle('swpt-far', far);
      b.title = far ? 'Opsiyon vadesi + swap vadesi 10 yılı geçer: TRY OIS eğrisi 10Y\'de biter' : '';
    }
  }

  pick(key, v) {
    this.state[key] = v;
    (key === 'expiry' ? this.expiryIn : this.tenorIn).value = v;
    this.now();
  }

  typeVol(unit, text) {
    this.state.vol = String(text || '').trim();
    this.state.vol_unit = unit;
    for (const [u] of UNITS) if (u !== unit) this.volIn[u].value = '';
    if (this.volIn[unit].value !== text) this.volIn[unit].value = text;
    this.later();
  }

  now() {
    this.later.cancel();
    return this.ask();
  }

  query() {
    const s = this.state;
    return { expiry: s.expiry, tenor: s.tenor, strike: s.strike, notional: s.notional, vol: s.vol, vol_unit: s.vol_unit };
  }

  async load() {
    await this.ask();
  }

  async refresh() {
    if (this.busy || (this.data && this.data.error)) return;      // (an input being typed, an answer to fix: left alone)
    await this.ask(true);
  }

  async ask(quiet) {
    const seq = ++this.seq;
    this.busy = true;
    this.marks();
    try {
      const d = await api.get('/api/swaption', this.query());
      if (seq !== this.seq) return;
      save(this.state);
      this.apply(d);
    } catch (err) {
      if (seq !== this.seq || (quiet && err.network)) return;
      this.data = { error: err.message };
      this.errorLine.textContent = err.message;
      this.result.classList.add('stale');          // (the last numbers stay on the page, dimmed, under the message)
      this.marks();
    } finally {
      if (seq === this.seq) this.busy = false;
    }
  }

  apply(d) {
    this.data = d;
    this.errorLine.textContent = d.error || '';
    this.result.classList.toggle('stale', !!d.error || !d.available);
    this.curveInfo.textContent = d.curve_text ? 'Eğriniz: ' + d.curve_text + ' (Ayarlar → Eğri interpolasyonu)' : '';
    this.stamp.textContent = new Date().toLocaleTimeString('tr-TR');
    this.marks();
    if (!d.available || !d.label) return;
    this.drawHead(d);
    this.drawTiles(d);
    this.drawOptions(d);
    this.drawRange(d);
    this.drawRealized(d);
    this.drawSchedule(d);
    this.drawNotes(d);
  }

  drawHead(d) {
    clear(this.head).append(
      h('b', { id: 'swpt-label' }, d.label + ' · dayanak ' + d.underlying),
      h('span', { class: 'muted', id: 'swpt-dates' }, '  opsiyon vadesi ' + serialDate(d.expiry) + ' · swap ' + serialDate(d.start) + ' → '
        + serialDate(d.end) + ' · ' + num(d.bdays, 0) + ' iş günü (T = ' + num(d.T, 4) + ', ' + num(d.cdays, 0) + ' takvim günü)'));
    this.noVol.textContent = d.vol && d.vol.why ? d.vol.why : '';
    this.noVol.classList.toggle('hidden', !(d.vol && d.vol.why));
  }

  drawTiles(d) {
    const box = clear(this.tiles);
    const [m1, m2] = d.methods;
    box.appendChild(tile('Forward · ' + METHOD[m1], rate(d.forward[m1]), { big: true, id: 'swpt-fwd',
      title: 'Dayanak swap\'ın par\'ı (' + d.underlying + '), eğriniz ile' }));
    box.appendChild(tile('Forward · ' + METHOD[m2], rate(d.forward[m2]), { id: 'swpt-fwd-other',
      title: 'Öbür yöntemle aynı swap. Annuity: ' + num(d.annuity[m2], 6) }));
    box.appendChild(tile('PPK − Bootstrap (bp)', signed(d.diff, 2), { id: 'swpt-diff' }));
    box.appendChild(tile('Annuity (A)', dash(num(d.A, 6)), { id: 'swpt-annuity', title: 'Σ τ·DF, eğrinizde (' + METHOD[m1] + ')' }));
    box.appendChild(tile('Strike (K)', rate(d.strike), { id: 'swpt-strike-out',
      title: d.atm ? 'ATM: K = F' : 'K − F: ' + signed(d.moneyness_bp, 1) + ' bp' }));
    box.appendChild(tile('Dayanak DV01 (TL/bp)', dash(num(d.dv01, 0)), { id: 'swpt-dv01', title: 'N · A · 0,0001 (payer +). Nominal ' + num(d.notional, 0) + ' TL' }));
    const v = d.vol || {};
    const src = v.source === 'typed' ? 'yazılan (' + ({ day: 'bp/gün', year: 'bp/yıl', black: '% Black' })[v.unit] + ')'
      : 'gerçekleşen ' + v.window + (isNum(v.n) && !v.full ? ' (' + v.n + ' var)' : '');
    box.appendChild(tile('Vol · bp/gün', volText.day(v.day), { id: 'swpt-vol-day-out', title: 'Kullanılan vol: ' + src }));
    box.appendChild(tile('Vol · bp/yıl', volText.year(v.year), { id: 'swpt-vol-year-out', title: 'bp/gün · √252' }));
    box.appendChild(tile('Vol · % Black', volText.black(v.black), { id: 'swpt-vol-black-out', title: 'Aynı payer primini veren lognormal vol' }));
    box.appendChild(tile('Vol kaynağı', src, { id: 'swpt-vol-source' }));
    // the boxes not typed into show the vol used in their unit
    for (const [unit] of UNITS) this.volIn[unit].placeholder = v.day !== null && v.day !== undefined ? volText[unit](v[unit]) : '';
  }

  drawOptions(d) {
    const o = d.options;
    const rows = [
      ['running_bp', 'Prim (bp, running)', (x) => num(x, 2), 'Forward prim p'],
      ['upfront_bp', 'Prim (bp, peşin)', (x) => num(x, 2), 'A · p: nominalin bp\'si'],
      ['tl', 'Prim (TL)', (x) => num(x, 0), 'N · A · p'],
      ['delta', 'Delta (%)', (x) => num(x * 100, 1) + '%', 'Φ(d); receiver −Φ(−d)'],
      ['delta_tl', 'Delta (TL/bp)', (x) => signed(x, 0), 'F 1 bp yükselince prim değişimi'],
      ['gamma_tl', 'Gamma (TL/bp/bp)', (x) => num(x, 2), 'Deltanın 1 bp\'lik değişimi'],
      ['vega_tl', 'Vega (TL / 1 bp normal vol)', (x) => num(x, 0), 'σN 1 bp/yıl artınca'],
      ['vega_black_tl', 'Vega (TL / %1 Black vol)', (x) => (isNum(x) ? num(x, 0) : '–'), 'Black vol 1 puan artınca'],
      ['theta_tl', 'Teta (TL / iş günü)', (x) => signed(x, 0), 'Aynı F, σN, A ile bir iş günü sonra'],
    ];
    const t = h('table', { class: 'plain', id: 'swpt-options' },
      h('tr', null, h('th', { class: 'l' }, ''), ...KINDS.map(([, label]) => h('th', null, label))));
    for (const [key, label, fmt, tip] of rows) {
      const tr = h('tr', { title: tip });
      tr.dataset.row = key;
      tr.appendChild(h('td', { class: 'l' }, label));
      for (const [kind] of KINDS) tr.appendChild(h('td', null, o ? fmt(o[kind][key]) : '–'));
      t.appendChild(tr);
    }
    const be = h('tr', { class: 'pkg', title: 'Vadede başabaş: payer K + p, receiver K − p, straddle K ± (p_payer + p_receiver)' });
    be.dataset.row = 'breakeven';
    be.append(h('td', null, 'Başabaş (vadede)'),
      h('td', { id: 'swpt-be-payer', style: { textAlign: 'right' } }, o ? rate(o.payer.breakeven) : '–'),
      h('td', { id: 'swpt-be-receiver', style: { textAlign: 'right' } }, o ? rate(o.receiver.breakeven) : '–'),
      h('td', { id: 'swpt-be-straddle', style: { textAlign: 'right' } }, o ? rate(o.straddle.breakeven.low) + ' / ' + rate(o.straddle.breakeven.high) : '–'));
    t.appendChild(be);
    clear(this.optBody).appendChild(t);
  }

  drawRange(d) {
    const r = d.range;
    const t = h('table', { class: 'plain', id: 'swpt-range' });
    const rows = r ? [['−2σ', r.down2], ['−1σ', r.down1], ['F (beklenen)', r.F], ['+1σ', r.up1], ['+2σ', r.up2]] : [['F (beklenen)', d.F]];
    for (const [k, v] of rows) {
      const tr = h('tr', null, h('td', { class: 'l' }, k), h('td', null, rate(v)));
      tr.dataset.row = k;
      t.appendChild(tr);
    }
    t.appendChild(h('tr', { class: 'pkg' }, h('td', null, 'σN·√T (bp)'), h('td', { style: { textAlign: 'right' } }, r ? num(r.sd_bp, 1) : '–')));
    clear(this.rangeBody).appendChild(t);
  }

  drawRealized(d) {
    const rz = d.realized;
    const used = d.vol && d.vol.source === 'realized' ? d.vol.window : null;
    const t = h('table', { class: 'plain', id: 'swpt-realized' },
      h('tr', null, h('th', { class: 'l' }, 'Pencere'), h('th', null, 'Değişim'), h('th', null, 'bp/gün'), h('th', null, 'bp/yıl'),
        h('th', { title: 'Bugünkü F ve strike\'ta' }, '% Black'), h('th', null, 'İlk gün'), h('th', null, 'Son gün')));
    for (const r of rz.rows) {
      const tr = h('tr', { class: r.window === used ? 'swpt-used' : (isNum(r.day) ? null : 'soft') });
      tr.dataset.window = String(r.window);
      tr.append(h('td', { class: 'l' }, r.window + ' değişim' + (r.window === used ? ' · kullanılan' : '')),
        h('td', { title: r.full ? '' : 'Pencere dolmadı: olan değişimler' }, isNum(r.day) ? String(r.n) + (r.full ? '' : '*') : '–'),
        h('td', null, volText.day(r.day)), h('td', null, volText.year(r.year)), h('td', null, volText.black(r.black)),
        h('td', null, dash(isoToTr(r.first))), h('td', null, dash(isoToTr(r.last))));
      t.appendChild(tr);
    }
    clear(this.realBody).appendChild(t);
    const info = d.history || {};
    const parts = ['Forward\'ın ihtiyaç duyduğu OIS vadeleri: ' + (rz.need || []).join(', ') + '.'];
    if ((rz.missing || []).length) parts.push('Geçmişte kapanışı olmayan: ' + rz.missing.join(', ') + '.');
    parts.push(rz.days ? 'Forward\'ın ' + rz.days + ' günü var (' + isoToTr(rz.first) + ' – ' + isoToTr(rz.last) + ').' : 'Forward\'ın geçmişi yok.');
    if (info.days) parts.push('Tarihçe: ' + info.days + ' gün, ' + isoToTr(info.first) + ' – ' + isoToTr(info.last) + (info.source ? ' (' + info.source + ')' : '') + '.');
    parts.push('* pencere dolmadı. Geçmiş her zaman Bootstrap\'ta.');
    this.realNote.textContent = parts.join(' ');
  }

  drawSchedule(d) {
    const [m1, m2] = d.methods;
    this.schedTitle.textContent = 'Dayanak swap · ' + d.underlying + ' · ' + d.schedule.length + ' kupon, ACT/365 (vadeden geriye, kısa dönem başta)';
    const t = h('table', { class: 'plain', id: 'swpt-schedule' },
      h('tr', null, h('th', null, '#'), h('th', null, 'Dönem başı'), h('th', null, 'Ödeme'), h('th', null, 'Gün'), h('th', null, 'τ'),
        h('th', null, 'DF · ' + METHOD[m1]), h('th', null, 'DF · ' + METHOD[m2])));
    d.schedule.forEach((lg, i) => {
      t.appendChild(h('tr', null, h('td', null, String(i + 1)), h('td', null, serialDate(lg.start)), h('td', null, serialDate(lg.pay)),
        h('td', null, num(lg.days, 0)), h('td', null, num(lg.tau, 6)), h('td', null, num(lg.df[m1], 6)), h('td', null, num(lg.df[m2], 6))));
    });
    t.appendChild(h('tr', { class: 'pkg' }, h('td', null, 'Annuity'), h('td', null, ''), h('td', null, ''), h('td', null, ''), h('td', null, ''),
      h('td', { style: { textAlign: 'right' } }, num(d.annuity[m1], 6)), h('td', { style: { textAlign: 'right' } }, num(d.annuity[m2], 6))));
    clear(this.schedBody).appendChild(t);
  }

  drawNotes(d) {
    const box = clear(this.notes);
    const tx = d.texts || {};
    for (const k of ['view', 'underlying', 'model', 'time', 'vol', 'realized', 'curve', 'signs', 'range', 'breakeven', 'strike']) {
      if (tx[k]) box.appendChild(h('p', { class: k === 'view' ? 'swpt-view' : null }, tx[k]));
    }
    for (const e of d.errors || []) box.appendChild(h('p', { class: 'swpt-warn' }, e));
  }

  destroy() {
    this.later.cancel();
    this.seq += 1;
  }
}
