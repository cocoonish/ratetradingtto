// Realized Vol · Carry: the realized volatility of whatever is typed - a tenor, a spread, a fly, a forward, the
// way a broker writes it - from the daily closes the dashboard keeps, and the flies (or spreads) of the Carry &
// Roll sheet with their carry measured against that volatility.
import { api } from '../api.js';
import { h, clear, errorToast, debounce } from '../ui.js';
import { Grid, plainData, copyGrid } from '../grid.js';
import { toolsOf } from '../columns.js';
import { Chart } from '../chart.js';
import { num, isoToTr } from '../format.js';

const KIND = { outright: 'Outright', spread: 'Spread', fly: 'Fly', fra: 'FRA', fwd: 'Forward' };
const DEFAULT_ITEMS = '1y, 2y, 5y, 1y2y, 2y5y, 1y2y3y, 2y3y4y, 2y5y10y, 9x12';
const BLUE = '4F81BD', ORANGE = 'F79646';

const isNum = (v) => typeof v === 'number' && isFinite(v);
/** A number with its sign: "+" only when its decimals show more than zero (never "+0,0"; num() writes no "-0,0"). */
const signed = (v, d) => { const t = num(v, d, false); return (v > 0 && /[1-9]/.test(t) ? '+' : '') + t; };
const serialOf = (iso) => Math.round(Date.UTC(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10)) / 86400000) + 25569;

function seg(options, value, onChange, id) {
  const el = h('div', { class: 'seg', id });
  const set = (v) => { for (const b of el.children) b.classList.toggle('on', b.dataset.v === String(v)); };
  for (const [v, label, title] of options) {
    const b = h('button', { type: 'button', title: title || '' }, label);
    b.dataset.v = String(v);
    b.addEventListener('click', () => { set(v); onChange(v); });
    el.appendChild(b);
  }
  el.set = set;
  set(value);
  return el;
}

function pref(key, fallback) {
  try { const v = localStorage.getItem(key); return v === null ? fallback : v; } catch (e) { return fallback; }
}

function keep(key, value) {
  try { localStorage.setItem(key, String(value)); } catch (e) { /* ignore */ }
}

export class VolPage {
  constructor(host, ctx) {
    this.host = host;
    this.ctx = ctx;
    this.window = Number(pref('tto.vol.window', '20')) || 20;
    this.annual = pref('tto.vol.annual', '0') === '1';
    this.items = pref('tto.vol.items', DEFAULT_ITEMS);
    const kind0 = pref('tto.vol.kind', 'fly');
    this.kind = kind0 === 'spread' || kind0 === 'list' ? kind0 : 'fly';
    this.horizon = pref('tto.vol.horizon', 'b') === 'a' ? 'a' : 'b';
    this.picked = null;                 // the instrument whose history is drawn
    this.vol = null;
    this.carry = null;
    this.grids = {};
    this.rowKeys = {};
    this.extra = null;                  // the history of a carry row (not one of the typed instruments)
    this.charts = {};
    this.loaded = 0;
    this.typed = debounce(() => {
      this.loadVol().catch(errorToast);
      if (this.kind === 'list') this.loadCarry().catch(errorToast);       // the carry of what is typed
    }, 450);
  }

  async load() {
    clear(this.host);
    this.host.appendChild(h('div', { class: 'loading' }, 'Yükleniyor…'));
    const [vol, carry] = await Promise.all([this.fetchVol(), this.fetchCarry()]);
    if (this.dead) return;
    this.vol = vol;
    this.carry = carry;
    this.loaded = Date.now();
    this.build();
    this.fill();
  }

  /** Market data moves the carry, a new close the volatility: neither by the second. */
  async refresh() {
    if (Date.now() - this.loaded < 20000 || this.busy) return;
    this.busy = true;
    try {
      const [vol, carry] = await Promise.all([this.fetchVol(), this.fetchCarry()]);
      if (this.dead) return;
      this.vol = vol;
      this.carry = carry;
      this.loaded = Date.now();
      this.fill();
    } finally { this.busy = false; }
  }

  destroy() {
    this.dead = true;
    this.typed.cancel();
    for (const c of Object.values(this.charts)) if (c) c.destroy();
  }

  fetchVol() {
    return api.post('/api/vol', { text: this.items, window: this.window });
  }

  fetchCarry() {
    const ask = this.kind === 'list' ? api.post('/api/vol/carry', { kind: 'list', window: this.window, text: this.items })
      : api.get('/api/vol/carry', { kind: this.kind, window: this.window });
    return ask.catch((err) => ({ error: err.message, rows: [], horizons: {} }));
  }

  async loadVol() {
    const seq = (this.seq = (this.seq || 0) + 1);
    const vol = await this.fetchVol();
    if (this.dead || seq !== this.seq) return;
    this.vol = vol;
    this.fillVol();
  }

  async loadCarry() {
    const seq = (this.cseq = (this.cseq || 0) + 1);
    const carry = await this.fetchCarry();
    if (this.dead || seq !== this.cseq) return;
    this.carry = carry;
    this.fillCarry();
  }

  // ------------------------------------------------------------------ layout
  build() {
    clear(this.host);
    this.grids = {};
    for (const c of Object.values(this.charts)) if (c) c.destroy();
    this.charts = {};
    const win = seg(this.vol.windows.map((n) => [n, String(n), 'Son ' + n + ' günlük değişimin standart sapması']), this.window, (v) => {
      this.window = v;
      keep('tto.vol.window', v);
      this.loadVol().catch(errorToast);
      this.loadCarry().catch(errorToast);
    }, 'vol-window');
    const unit = seg([['0', 'bp / gün', 'Günlük değişimlerin standart sapması (bp)'], ['1', 'yıllık bp', 'Günlük × √252']], this.annual ? '1' : '0', (v) => {
      this.annual = v === '1';
      keep('tto.vol.annual', v);
      this.fill();
    }, 'vol-unit');
    this.histNote = h('span', { class: 'muted', id: 'vol-history' });
    this.host.appendChild(h('div', { class: 'page-tools' }, h('span', { class: 'muted' }, 'Pencere (gün)'), win, h('span', { class: 'muted' }, 'Birim'), unit,
      h('span', { class: 'grow' }), this.histNote));
    this.banner = h('div', { class: 'banner hidden', id: 'vol-banner' });
    this.host.appendChild(this.banner);

    // ---- what is typed
    this.input = h('input', { type: 'text', class: 'inp volbox', id: 'vol-items', spellcheck: 'false', autocomplete: 'off',
      placeholder: 'örn. 18m, 1y5y, 2y3y4y, 9x12, 5y x, TRT150328T24' });
    this.input.value = this.items;
    this.input.addEventListener('input', () => { this.items = this.input.value; keep('tto.vol.items', this.items); this.typed(); });
    this.input.addEventListener('keydown', (e) => { if (e.key === 'Enter') { this.typed.cancel(); this.loadVol().catch(errorToast); } });
    const copy = h('button', { class: 'iconbtn', type: 'button', title: 'Tabloyu kopyala (Excel\'e yapıştırılabilir)' }, 'Kopyala');
    copy.addEventListener('click', () => { if (this.grids.vol) copyGrid(this.grids.vol); });
    this.volBody = h('div', { class: 'body' });
    this.volCharts = h('div', { class: 'volcharts' });
    this.levelHost = h('div', { class: 'volchart' });
    this.rollHost = h('div', { class: 'volchart' });
    this.levelTitle = h('div', { class: 'ct' });
    this.rollTitle = h('div', { class: 'ct' });
    this.volCharts.appendChild(h('div', null, this.levelTitle, this.levelHost));
    this.volCharts.appendChild(h('div', null, this.rollTitle, this.rollHost));
    const typed = h('section', { class: 'panel wide', id: 'vol-panel' },
      h('header', null, h('h2', null, 'Realized vol · yazdığınız enstrüman'), h('span', { class: 'grow' }), h('div', { class: 'tools' }, copy)),
      h('div', { class: 'volentry' }, this.input,
        h('div', { class: 'muted' }, 'Satıra tıklayınca seviyesi ve kayan vol\'ü aşağıda çizilir (carry tablosundaki satırlarda da). Vade (18m), spread (1y5y – uzun − kısa), fly (2y3y4y – 2 × gövde − kanatlar), FRA / forward (9x12, 1y1y); cross-currency için "x" (5y x); tahvil için ISIN. '
          + 'Virgülle ayırın. Vol = günlük değişimlerin (bp) standart sapması; yalnızca bütün bacakların kapanışı olan günler sayılır.')),
      this.volBody, this.volCharts);

    // ---- carry against it
    const kind = seg([['fly', 'Fly', 'C & R sayfasının fly tablosu (gövde receive)'], ['spread', 'Spread', 'C & R sayfasının spread tablosu (flattener)'],
      ['list', 'Listem', 'Yukarıda yazdığınız enstrümanlar: OIS vadesi (receiver), spread (flattener) ve fly (gövde receive), 1M – 10Y']], this.kind, (v) => {
      this.kind = v;
      keep('tto.vol.kind', v);
      this.loadCarry().catch(errorToast);
    }, 'carry-kind');
    this.horizonSeg = h('span', { id: 'carry-horizon-host' });
    const copy2 = h('button', { class: 'iconbtn', type: 'button', title: 'Tabloyu kopyala (Excel\'e yapıştırılabilir)' }, 'Kopyala');
    copy2.addEventListener('click', () => { if (this.grids.carry) copyGrid(this.grids.carry); });
    this.carryTitle = h('h2', null, 'Carry / vol');
    this.carryNote = h('div', { class: 'muted volnote' });
    this.scatterHost = h('div', { class: 'volscatter' });
    this.carryBody = h('div', { class: 'body' });
    const carry = h('section', { class: 'panel wide', id: 'carry-panel' },
      h('header', null, this.carryTitle, h('span', { class: 'grow' }), kind, h('span', { class: 'muted' }, 'Ufuk'), this.horizonSeg, h('div', { class: 'tools' }, copy2)),
      // (the table first, the scatter beside it; one under the other on a narrower screen - the desk, 27.11.2026)
      this.carryNote, h('div', { class: 'carrygrid tablefirst' }, this.carryBody, this.scatterHost));
    this.host.appendChild(h('div', { class: 'volpage' }, typed, carry));
  }

  /**
   * ``keys``: what each row stands for - a click anywhere on a row draws its history (the row is marked).
   */
  setGrid(id, body, header, rows, empty, keys) {
    this.rowKeys[id] = keys || [];
    if (!rows.length) {
      clear(body);
      this.grids[id] = null;
      body.appendChild(h('div', { class: 'empty' }, empty));
      return;
    }
    const marked = rows.map((row, i) => (keys && keys[i] && keys[i].key === this.picked
      ? row.map((c) => (c && typeof c === 'object' ? (c.sk ? c : Object.assign({}, c, { cls: ((c.cls || '') + ' pick').trim() })) : { t: c == null ? '' : String(c), k: 's', cls: 'pick' }))
      : row));
    const data = plainData(header, marked);
    if (this.grids[id]) this.grids[id].replace(data);
    else {
      clear(body);
      const g = new Grid({ data, editable: false, name: 'vol/' + id, tools: toolsOf(body) });
      g.el.classList.add('pickable');
      g.el.addEventListener('click', (e) => {
        if (e.target.closest('button')) return;
        const td = e.target.closest('td');
        if (!td || td.__i === undefined || td.__i < 1) return;                  // row 0: the captions
        const k = this.rowKeys[id][td.__i - 1];
        if (k) this.pick(k).catch(errorToast);
      });
      this.grids[id] = g;
      body.appendChild(g.el);
    }
  }

  /** Draw the history of a row: one of the typed ones, or a fly / spread of the carry table (asked for on its own). */
  async pick(k) {
    this.picked = k.key;
    const typed = (this.vol.rows || []).find((r) => r.key === k.key && r.ok);
    if (!typed && k.text) {
      const res = await api.post('/api/vol', { text: k.text, window: this.window });
      if (this.dead) return;
      this.extra = (res.rows || []).find((r) => r.ok) || null;
      if (this.extra) this.extra.key = k.key;
    }
    this.fillVol();
    this.fillCarry();
    if (k.from === 'carry') this.volCharts.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }

  /** A volatility as shown: bp a day, or a year's (× √252). */
  sigma(v) {
    return isNum(v) ? v * (this.annual ? Math.sqrt(this.vol.year || 252) : 1) : null;
  }

  fill() {
    this.fillVol();
    this.fillCarry();
  }

  // ------------------------------------------------------------------ what is typed
  fillVol() {
    const d = this.vol;
    const hst = d.history || {};
    this.histNote.textContent = hst.days ? 'Tarihçe: ' + isoToTr(hst.first) + ' – ' + isoToTr(hst.last) + ' · ' + hst.days + ' gün · kaynak ' + (hst.source || '')
      : 'Tarihçe yok';
    const short = !hst.days || hst.days < 60;
    this.banner.classList.toggle('hidden', !short);
    this.banner.textContent = !hst.days ? 'Günlük kapanış tarihçesi henüz yok: Bloomberg bağlıyken arka planda doldurulur (Gün Sonu Matrisi sayfasındaki durum satırına bakın).'
      : 'Tarihçe kısa (' + hst.days + ' gün' + (hst.live ? '' : '; kayıtlı veride yalnızca dosyadaki son ay ve şu vadeler var: ' + ((hst.tenors || {}).OIS || []).join(', '))
        + '). Uzun pencereler eldeki gün sayısıyla hesaplanır ve soluk gösterilir; Bloomberg bağlıyken tarihçe yaklaşık bir yıla tamamlanır.';
    const unit = this.annual ? ' (yıllık bp)' : ' (bp/gün)';
    // a bond followed by its price (a floater) moves in price points, everything else in bp
    const digits = (r) => (r.unit === 'px' ? 3 : 1);
    const vol = (r, n) => {
      const v = r.vols && r.vols[String(n)];
      if (!v) return { t: '', k: '' };
      const x = this.sigma(v.d);
      return { t: num(x, digits(r), false), v: x, k: 'n', cls: (v.full ? '' : 'soft') + (n === d.window ? ' b' : ''),
        tip: v.n + ' değişim' + (v.full ? '' : ' (pencere dolmadı)') + (r.unit === 'px' ? ' · fiyat puanı' : '') };
    };
    const kindOf = (r) => (r.product === 'DIBS' ? (r.unit === 'px' ? 'Tahvil · fiyat' : 'Tahvil · getiri') : (KIND[r.kind] || r.kind) + (r.unit === 'bp' ? ' (bp)' : ''));
    const rows = d.rows.map((r) => {
      const name = (r.product && r.product !== 'OIS' && r.product !== 'DIBS' ? r.product + ' ' : '') + (r.label || r.raw);
      if (!r.ok) {
        return [{ t: name, k: 's', b: 1 }, r.kind ? KIND[r.kind] || r.kind : '', { t: r.error || 'hesaplanamadı', k: 's', cls: 'soft', cs: 8 }].concat(
          Array(7).fill({ sk: 1 }), [{ t: '', k: '' }]);
      }
      return [{ t: name, k: 's', b: 1 }, kindOf(r),
        { t: num(r.level, r.unit === 'pct' ? 2 : (r.unit === 'px' ? 3 : 1), false), v: r.level, k: 'n', tip: isoToTr(r.day) + ' kapanışı' },
        isNum(r.change) ? { t: signed(r.change, digits(r)), v: r.change, k: 'n' } : { t: '', k: '' },
        isNum(r.sigma) ? { t: signed(r.sigma, 1) + ' σ', v: r.sigma, k: 'n', cls: Math.abs(r.sigma) >= 2 ? 'thru' : '',
          tip: 'Son günün hareketi ÷ ' + d.window + ' günlük realized vol' } : { t: '', k: '' },
        vol(r, 10), vol(r, 20), vol(r, 60), vol(r, 120), vol(r, 250), { t: String(r.n), k: 'n', tip: isoToTr(r.first) + ' – ' + isoToTr(r.day) },
        { t: '', k: '', cls: 'act', act: { label: '📈', title: name + ' geçmişini çiz', fn: () => this.pick({ key: r.key }).catch(errorToast) } }];
    });
    this.setGrid('vol', this.volBody, ['Enstrüman', 'Tür', 'Seviye', 'Son Δ (bp)', 'Son Δ / σ', { t: 'σ 10g' + unit, ck: 'σ 10g' }, 'σ 20g', 'σ 60g', 'σ 120g', 'σ 250g', 'Gün', ''], rows,
      'Enstrüman yazın: 18m, 1y5y, 2y3y4y, 9x12 …', d.rows.map((r) => (r.ok ? { key: r.key, from: 'vol' } : null)));

    // ---- the history of one of them: the row clicked (of either table), else the first one
    const good = d.rows.filter((r) => r.ok && r.days && r.days.length > 1);
    const extra = this.extra && this.extra.key === this.picked && this.extra.days && this.extra.days.length > 1 ? this.extra : null;
    const row = good.find((r) => r.key === this.picked) || extra || good[0];
    this.volCharts.classList.toggle('hidden', !row);
    if (!row) return;
    this.picked = row.key;
    const name = (row.product !== 'OIS' && row.product !== 'DIBS' ? row.product + ' ' : '') + row.label;
    const x = { type: 'date', values: row.days.map(serialOf), format: 'mmm yy' };
    const cats = row.days.map((s) => isoToTr(s).slice(0, 5));
    const many = row.days.length > 45;
    const unitText = row.unit === 'pct' ? '%' : (row.unit === 'px' ? 'fiyat' : 'bp');
    const level = { title: name, cats, x, auto: 'fit', decimals: row.unit === 'bp' ? 0 : 2, y_title: unitText, aspect: 0.42,
      series: [{ name, kind: 'line', color: BLUE, data: row.levels, marker: !many }] };
    const k = this.annual ? Math.sqrt(d.year || 252) : 1;
    const roll = { title: name + ' vol', cats, x, auto: 'fit', decimals: 1, y_title: this.annual ? 'yıllık bp' : 'bp / gün', aspect: 0.42,
      series: [{ name: d.window + ' günlük realized vol', kind: 'line', color: ORANGE, data: row.roll.map((v) => (isNum(v) ? v * k : null)), marker: !many }] };
    this.levelTitle.textContent = name + ' · seviye (' + unitText + ')';
    this.rollTitle.textContent = name + ' · kayan ' + d.window + ' günlük realized vol (' + (this.annual ? 'yıllık bp' : 'bp / gün') + ')';
    if (this.charts.level) this.charts.level.update(level); else this.charts.level = new Chart(this.levelHost, level, { height: 230 });
    if (this.charts.roll) this.charts.roll.update(roll); else this.charts.roll = new Chart(this.rollHost, roll, { height: 230 });
  }

  // ------------------------------------------------------------------ carry against it
  fillCarry() {
    const d = this.carry;
    const fly = this.kind === 'fly';
    clear(this.horizonSeg);
    const hz = d.horizons || {};
    if (!hz[this.horizon]) this.horizon = hz.b ? 'b' : 'a';
    this.horizonSeg.appendChild(seg(['a', 'b'].filter((k) => hz[k]).map((k) => [k, hz[k].label, 'Ufuk sonu ' + isoToTr(hz[k].date) + ' · ' + hz[k].days + ' iş günü']),
      this.horizon, (v) => { this.horizon = v; keep('tto.vol.horizon', v); this.fillCarry(); }, 'carry-horizon'));
    const H = hz[this.horizon] || { label: '', days: 0 };
    const list = this.kind === 'list';
    // (σ's window in the title: the same for every row - B20, 28.11.2026: the "Gün" column said 20 on each line)
    this.carryTitle.textContent = 'Carry / vol · ' + (list ? 'yazdıklarınız' : fly ? 'fly\'lar' : 'spread\'ler') + ' · σ ' + d.window + ' gün';
    if (d.error) {
      this.carryNote.textContent = d.error;
      this.setGrid('carry', this.carryBody, [], [], 'Veri yok');
      clear(this.scatterHost);
      this.charts.scatter = null;
      return;
    }
    const SIDES = { fly: ['REC gövde', 'PAY gövde'], spread: ['Flattener', 'Steepener'], outright: ['Receiver', 'Payer'] };
    const pos = list ? 'alan taraf' : fly ? 'REC gövde' : 'Flattener', neg = list ? 'karşı taraf' : fly ? 'PAY gövde' : 'Steepener';
    const sideOf = (r, v) => { const s2 = list ? (SIDES[r.kind] || SIDES.outright) : [pos, neg]; return v > 0 ? s2[0] : s2[1]; };
    const what = list ? 'yazdığınız enstrümanların (OIS vadesi receiver, spread flattener, fly gövde receive; Carry & Roll sayfasının vade motorundan)'
      : 'Carry & Roll sayfasının ' + (fly ? '"fly (gövde receive)"' : '"spread (flattener)"') + ' tablosundaki';
    this.carryNote.textContent = 'C+R: ' + what + ' ' + H.label + ' carry + roll-down (bp; + ise ' + pos + ' kazanır, − ise ' + neg + '). '
      + (d.path ? 'TLREF: ' + d.path + ' (Ayarlar → Carry). ' : '')
      + 'σ: işlemin seviyesinin son ' + d.window + ' günlük realized vol\'ü; ufuk σ\'sı = günlük σ × √' + H.days
      + ' iş günü. Oran = C+R ÷ ufuk σ\'sı: bir standart sapmalık harekete karşı kaç birim carry. z: bugünkü seviyenin son 60 / 120 / 250 kapanışın '
      + 'ortalamasından kaç standart sapma uzakta olduğu (+ ise seviye ortalamanın üstünde; |z| ≥ 2 vurgulu).';
    const cr = (r) => r['cr_' + this.horizon], over = (r) => r['vol_' + this.horizon], ratio = (r) => r['ratio_' + this.horizon];
    // (the list keeps the order it was typed in; the sheet's tables come best ratio first)
    const rows = list ? d.rows.slice() : d.rows.slice().sort((a, b) => (isNum(ratio(b)) ? Math.abs(ratio(b)) : -1) - (isNum(ratio(a)) ? Math.abs(ratio(a)) : -1));
    const sign = (v, digits) => (isNum(v) ? { t: signed(v, digits), v, k: 'n' } : { t: '', k: '' });
    const zs = (d.z_windows || [60, 120, 250]).map(String);
    const zName = { 60: 'z 3a', 120: 'z 6a', 250: 'z 1y' };
    const zCell = (r, n) => {
      const v = r.z ? r.z[n] : null;
      return isNum(v) ? { t: signed(v, 2), v, k: 'n', cls: Math.abs(v) >= 2 ? 'thru' : '',
        tip: 'Son ' + Math.min(Number(n), r.closes || 0) + ' kapanışa göre z-score' } : { t: '', k: '' };
    };
    // (a caption that follows the horizon keeps one name for the user's column choice)
    this.setGrid('carry', this.carryBody, ['İşlem', { t: list ? 'Piyasa (% / bp)' : 'Piyasa (bp)', ck: 'Piyasa' }, { t: 'C+R ' + H.label + ' (bp)', ck: 'C+R ufukta' },
      'σ (bp/gün)', { t: 'σ ' + H.label + ' (bp)', ck: 'σ ufukta' }, 'C+R / σ', 'Carry\'yi alan']
      .concat(zs.map((n) => zName[n] || 'z ' + n + 'g')),
      rows.map((r) => [{ t: r.label, k: 's', b: 1 }, isNum(r.market) ? (r.kind === 'outright' ? { t: num(r.market, 2, false) + ' %', v: r.market, k: 'n' }
        : { t: num(r.market, 1, false), v: r.market, k: 'n' }) : { t: '', k: '' }, sign(cr(r), 1),
        isNum(r.vol) ? { t: num(r.vol, 1, false), v: r.vol, k: 'n', cls: r.full ? '' : 'soft', tip: r.n + ' değişim' + (r.full ? '' : ' (pencere dolmadı)') }
          : { t: r.error || '', k: 's', cls: 'soft' },
        isNum(over(r)) ? { t: num(over(r), 1, false), v: over(r), k: 'n' } : { t: '', k: '' },
        isNum(ratio(r)) ? { t: signed(ratio(r), 2), v: ratio(r), k: 'n', b: 1, cls: Math.abs(ratio(r)) >= 0.5 ? 'thru' : '' } : { t: '', k: '' },
        isNum(cr(r)) && cr(r) !== 0 ? sideOf(r, cr(r)) : ''].concat(zs.map((n) => zCell(r, n)))),
      list ? 'Yukarıya OIS vadesi, spread ya da fly yazın (örn. 1y, 1y2y, 6m1y2y)' : 'Tabloda işlem yok', rows.map((r) => ({ key: 'OIS:' + r.kind + ':' + r.tenors.join('/'), text: r.tenors.join('').toLowerCase(), from: 'carry' })));

    // ---- the picture: carry against the volatility of the same time
    const pts = d.rows.filter((r) => isNum(cr(r)) && isNum(over(r)));
    const side = (name, color, test) => {
      const list = pts.filter(test);
      return { name, kind: 'scatter', noline: true, marker: true, color, x: list.map(over), data: list.map(cr), labels: list.map((r) => r.label) };
    };
    const spec = { scatter: true, title: 'Carry / vol', auto: 'fit', decimals: 1, aspect: 0.62,
      x_title: 'σ ' + H.label + ' (bp)', y_title: 'C+R ' + H.label + ' (bp)',
      series: [side((list ? 'alan taraf (receiver / flattener / REC gövde)' : pos) + ' kazanır', BLUE, (r) => cr(r) >= 0),
        side((list ? 'karşı taraf' : neg) + ' kazanır', ORANGE, (r) => cr(r) < 0)] };
    if (!pts.length) {
      clear(this.scatterHost);
      this.charts.scatter = null;
      this.scatterHost.appendChild(h('div', { class: 'empty' }, 'Çizilecek nokta yok: bu işlemlerin vadeleri için günlük tarihçe bulunmuyor.'));
    } else if (this.charts.scatter) {
      this.charts.scatter.update(spec);
    } else {
      clear(this.scatterHost);
      this.charts.scatter = new Chart(this.scatterHost, spec, { height: 420 });
    }
  }
}
