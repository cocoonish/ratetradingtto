// FX Vol İzleme: the currency option market at a glance - USDTRY, the G10 pairs, the crosses and whatever the desk
// adds (a pair, or any Bloomberg ticker).  Every vol's level, its moves over a day / a week / a month and where it
// stands in its recent history (z-score, percentile, range - the workbook's macro block, for every pair), a heat map
// of the whole set, the day's movers, one pair in depth (term structure, skew and smile now against a week and a month
// ago, time series, implied against realized).  Each section can be shown or hidden.
import { api } from '../api.js';
import { h, clear, errorToast, toast, confirmDialog, promptDialog } from '../ui.js';
import { Grid, plainData, copyGrid } from '../grid.js';
import { Chart } from '../chart.js';
import { serialOfIso } from '../fan.js';
import { num, isoToTr } from '../format.js';

const SECTIONS = [['summary', 'Özet'], ['heat', 'Isı haritası'], ['movers', 'Hareketler'], ['pair', 'Parite ayrıntısı'],
  ['own', 'Kendi ticker\'larım'], ['method', 'Yöntem']];
const WINDOWS = [[63, '3A', 'Son 63 kapanış (~3 ay)'], [126, '6A', 'Son 126 kapanış (~6 ay)'], [250, '1Y', 'Son 250 kapanış (~1 yıl)']];
const METRICS = [['last', 'Seviye'], ['d1', 'Δ1G'], ['w1', 'Δ1H'], ['m1', 'Δ1A'], ['z', 'z'], ['pct', 'Yüzdelik']];
const KIND = { ATM: 'ATM', RR25: '25D RR', BF25: '25D BF', RR10: '10D RR', BF10: '10D BF' };
const BLUE = '4F81BD', ORANGE = 'F79646', PURPLE = '8064A2', GREEN = '9BBB59';
const REFRESH_MS = 15000;

const isNum = (v) => typeof v === 'number' && isFinite(v);
const sgn = (v, d = 2) => (isNum(v) ? (v > 0 ? '+' : '') + num(v, d, false) : '');

function pref(key, fallback) {
  try { const v = localStorage.getItem(key); return v === null ? fallback : v; } catch (e) { return fallback; }
}

function keep(key, value) {
  try { localStorage.setItem(key, String(value)); } catch (e) { /* not kept */ }
}

function seg(options, value, onChange, id) {
  const el = h('div', { class: 'seg', id });
  const set = (v) => { for (const b of el.children) b.classList.toggle('on', b.dataset.v === String(v)); };
  for (const [v, label, title] of options) {
    const b = h('button', { type: 'button', title: title || '' }, label);
    b.dataset.v = String(v);
    b.addEventListener('click', () => { set(v); onChange(v); });
    el.appendChild(b);
  }
  set(value);
  return el;
}

function rgb(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '128, 128, 128';
}

/** Red up, blue down, deeper as |t| nears 1 (t in −1 … 1); nothing for no value. */
function paint(el, t) {
  if (!isNum(t) || Math.abs(t) < 0.02) { el.style.background = ''; return; }
  const c = 'rgba(' + rgb(t > 0 ? '--heat-up' : '--heat-down') + ', ' + (0.1 + 0.62 * Math.min(1, Math.abs(t))).toFixed(3) + ')';
  el.style.background = 'linear-gradient(' + c + ', ' + c + '), var(--heat-mid)';
}

/** The same scale as a hex colour for a grid cell (the grid makes its strength from the colour's chroma). */
function heatHex(t) {
  if (!isNum(t) || Math.abs(t) < 0.02) return null;
  const a = Math.min(1, Math.abs(t));
  const base = t > 0 ? [230, 103, 103] : [57, 135, 229];
  const mix = base.map((c) => Math.round(128 + (c - 128) * a));
  return mix.map((c) => c.toString(16).padStart(2, '0')).join('').toUpperCase();
}

function spark(values, w = 90, ht = 22) {
  const v = (values || []).filter(isNum);
  const el = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  el.setAttribute('class', 'fxspark');
  el.setAttribute('width', w);
  el.setAttribute('height', ht);
  if (v.length < 2) return el;
  const lo = Math.min(...v), hi = Math.max(...v), span = hi - lo || 1;
  const pts = v.map((x, i) => (1 + (i / (v.length - 1)) * (w - 4)).toFixed(1) + ',' + (ht - 2 - ((x - lo) / span) * (ht - 4)).toFixed(1));
  const p = document.createElementNS('http://www.w3.org/2000/svg', 'path');
  p.setAttribute('d', 'M' + pts.join(' L'));
  el.appendChild(p);
  const last = pts[pts.length - 1].split(',');
  const c = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
  c.setAttribute('cx', last[0]);
  c.setAttribute('cy', last[1]);
  c.setAttribute('r', 2.2);
  el.appendChild(c);
  return el;
}

/** What a cell shows of a series' statistics, and its tooltip. */
function statText(st, metric) {
  if (!st) return '';
  if (metric === 'pct') return isNum(st.pct) ? num(st.pct * 100, 0, false) + '%' : '';
  if (metric === 'z') return isNum(st.z) ? sgn(st.z, 2) : '';
  if (metric === 'last') return isNum(st.last) ? num(st.last, 2, false) : '';
  return isNum(st[metric]) ? sgn(st[metric], 2) : '';
}

function statTip(name, st, window) {
  if (!st) return name;
  const lines = [name + (st.ticker ? ' · ' + st.ticker : '')];
  if (!isNum(st.last)) lines.push(st.why || 'veri yok');
  else lines.push('Son: ' + num(st.last, 3, false) + (st.live ? '' : ' (son kapanış)'));
  if (isNum(st.d1)) lines.push('Δ1G ' + sgn(st.d1, 3) + ' · Δ1H ' + sgn(st.w1, 3) + ' · Δ1A ' + sgn(st.m1, 3));
  if (isNum(st.avg3m)) lines.push('Ort. 3A ' + num(st.avg3m, 3, false) + ' · z 3A ' + sgn(st.z3m, 2));
  if (isNum(st.z)) lines.push('z (' + st.window + ' kapanış) ' + sgn(st.z, 2) + ' · yüzdelik ' + num(st.pct * 100, 0, false) + '%');
  if (isNum(st.min)) lines.push('Aralık ' + num(st.min, 3, false) + ' – ' + num(st.max, 3, false));
  lines.push(st.n ? st.n + ' kapanış' + (st.day ? ', son ' + isoToTr(st.day) : '') : 'tarihçe yok');
  return lines.join('\n');
}

export class FxVolPage {
  constructor(host, ctx) {
    this.host = host;
    this.ctx = ctx;
    this.window = Number(pref('tto.fxvol.window', '250')) || 250;
    this.metric = pref('tto.fxvol.metric', 'w1');
    this.sumMetric = pref('tto.fxvol.summetric', 'last');
    this.pair = pref('tto.fxvol.pair', 'USDTRY');
    this.tenor = pref('tto.fxvol.tenor', '1M');
    let on = null;
    try { on = JSON.parse(pref('tto.fxvol.sections', 'null')); } catch (e) { on = null; }
    this.on = new Set(Array.isArray(on) ? on : SECTIONS.map((s) => s[0]));
    this.grids = {};
    this.charts = {};
    this.loaded = 0;
  }

  async load() {
    clear(this.host);
    this.host.appendChild(h('div', { class: 'loading' }, 'Yükleniyor…'));
    const [mon, det] = await Promise.all([this.fetchMonitor(), this.fetchPair()]);
    if (this.dead) return;
    this.mon = mon;
    this.det = det;
    this.loaded = Date.now();
    this.build();
    this.fill();
  }

  async refresh() {
    if (this.busy || Date.now() - this.loaded < REFRESH_MS) return;
    this.busy = true;
    try {
      const [mon, det] = await Promise.all([this.fetchMonitor(), this.on.has('pair') ? this.fetchPair() : Promise.resolve(this.det)]);
      if (this.dead) return;
      this.mon = mon;
      this.det = det;
      this.loaded = Date.now();
      this.fill();
    } finally { this.busy = false; }
  }

  destroy() {
    this.dead = true;
    for (const c of Object.values(this.charts)) if (c) c.destroy();
  }

  fetchMonitor() { return api.get('/api/fx/monitor', { window: this.window }); }

  fetchPair() { return api.get('/api/fx/pair', { pair: this.pair, tenor: this.tenor }); }

  async reloadMonitor() {
    try { this.mon = await this.fetchMonitor(); if (!this.dead) this.fill(); } catch (err) { errorToast(err); }
  }

  async reloadPair() {
    const seq = (this.pseq = (this.pseq || 0) + 1);
    try {
      const det = await this.fetchPair();
      if (this.dead || seq !== this.pseq) return;
      this.det = det;
      this.fillPair();
    } catch (err) { errorToast(err); }
  }

  // ------------------------------------------------------------------ layout
  build() {
    clear(this.host);
    this.grids = {};
    for (const c of Object.values(this.charts)) if (c) c.destroy();
    this.charts = {};
    this.chartHosts = null;
    const win = seg(WINDOWS, this.window, (v) => { this.window = Number(v); keep('tto.fxvol.window', v); this.reloadMonitor(); }, 'fxvol-window');
    const chips = h('div', { class: 'fxchips', id: 'fxvol-sections' });
    for (const [id, title] of SECTIONS) {
      const b = h('button', { type: 'button', title: 'Bölümü göster / gizle' }, title);
      b.classList.toggle('on', this.on.has(id));
      b.addEventListener('click', () => {
        if (this.on.has(id)) this.on.delete(id); else this.on.add(id);
        b.classList.toggle('on', this.on.has(id));
        keep('tto.fxvol.sections', JSON.stringify([...this.on]));
        this.showSections();
        if (id === 'pair' && this.on.has('pair')) this.reloadPair();
      });
      chips.appendChild(b);
    }
    const sync = h('button', { class: 'btn', type: 'button', id: 'fxvol-sync', title: 'Vol\'lerin günlük kapanışlarını Bloomberg\'den şimdi iste (ilk kez bir yıl geriye, sonra son günler)' }, 'Tarihçeyi güncelle');
    sync.addEventListener('click', () => this.sync());
    this.histNote = h('span', { class: 'muted', id: 'fxvol-history' });
    this.host.appendChild(h('div', { class: 'page-tools' }, h('span', { class: 'muted' }, 'Pencere'), win, chips, h('span', { class: 'grow' }), this.histNote, sync));
    this.banner = h('div', { class: 'banner hidden', id: 'fxvol-banner' });
    this.host.appendChild(this.banner);
    this.sections = {};

    // ---- summary
    this.sumBody = h('div');
    const sumSeg = seg([['last', 'Seviye'], ['d1', 'Δ1G'], ['w1', 'Δ1H'], ['m1', 'Δ1A']], this.sumMetric,
      (v) => { this.sumMetric = v; keep('tto.fxvol.summetric', v); this.fillSummary(); }, 'fxvol-summetric');
    this.sections.summary = this.panel('fxvol-summary', 'Özet · her parite bir satır', [sumSeg, this.copyBtn('summary')], this.sumBody,
      h('div', { class: 'note' }, 'Vol\'ler vol puanı. Renk: seçili penceredeki z-skoru (kırmızı yüksek, mavi düşük). z ve yüzdelik seçili pencerede (Masa → Makro bloğunun tanımı: '
        + 'canlı değer, dünkü kapanışa kadarki kapanışlara göre). İma − gerçekleşen: ATM 1M − spotun son 21 günlük gerçekleşen vol\'ü. Eğim: ATM 1Y − ATM 1M. Satıra tıklayınca parite ayrıntıda açılır.'));

    // ---- heat map
    this.heatBody = h('div', { class: 'heat-wrap' });
    const metricSeg = seg(METRICS, this.metric, (v) => { this.metric = v; keep('tto.fxvol.metric', v); this.fillHeat(); }, 'fxvol-metric');
    this.sections.heat = this.panel('fxvol-heat', 'Isı haritası · parite × vade', [metricSeg], this.heatBody,
      h('div', { class: 'note' }, 'Büyük: seçili ölçü (Δ vol puanı; z; yüzdelik), küçük: seviye. Değişimlerde renk o sütunun en büyük hareketine göre, z ve yüzdelikte '
        + 'tarihine göre (kırmızı yükseldi / yüksek, mavi düştü / düşük). Üzerine gelince ayrıntı; tıklayınca o paritenin ayrıntısı.'));

    // ---- movers
    this.moversBody = h('div', { class: 'volcharts' });
    this.sections.movers = this.panel('fxvol-movers', 'Hareketler · günün en büyükleri ve tarihsel uçta olanlar', null, this.moversBody);

    // ---- one pair
    this.pairSeg = h('span');
    this.tenorSeg = h('span');
    this.pairCharts = h('div', { class: 'volcharts' });
    this.pairNote = h('div', { class: 'note' });
    this.sections.pair = this.panel('fxvol-pair', 'Parite ayrıntısı', [this.pairSeg, h('span', { class: 'muted' }, 'Smile vadesi'), this.tenorSeg],
      this.pairCharts, this.pairNote);

    // ---- the desk's own
    this.ownInput = h('input', { class: 'inp', id: 'fxvol-add', spellcheck: 'false', autocomplete: 'off', placeholder: 'Parite (USDZAR) ya da ticker (VIX Index, USDTRYV1M CMPN Curncy)' });
    this.ownLabel = h('input', { class: 'inp', id: 'fxvol-add-label', spellcheck: 'false', autocomplete: 'off', placeholder: 'Ad (isteğe bağlı)', style: { width: '160px' } });
    const add = h('button', { class: 'btn primary', type: 'button', id: 'fxvol-add-btn' }, 'Ekle');
    add.addEventListener('click', () => this.addTicker());
    this.ownInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') this.addTicker(); });
    this.srcText = h('span', { class: 'muted' });
    const src = h('button', { class: 'btn ghost', type: 'button', title: 'Vol ticker\'larının Bloomberg fiyat kaynağı (herkes için)' }, 'Kaynağı değiştir');
    src.addEventListener('click', () => this.setSource());
    this.ownPairs = h('div', { class: 'fxchips' });
    this.ownBody = h('div');
    this.sections.own = this.panel('fxvol-own', 'Kendi ticker\'larım (masa için ortak)', [this.copyBtn('own')],
      h('div', { class: 'fxadd' }, this.ownInput, this.ownLabel, add, h('span', { class: 'grow' }), this.srcText, src),
      h('div', { class: 'fxadd' }, h('span', { class: 'muted' }, 'Eklenen pariteler:'), this.ownPairs), this.ownBody,
      h('div', { class: 'note' }, 'Parite yazılırsa (USDZAR) o paritenin vol seti bütün tablolara girer; başka bir ticker yazılırsa (sonunda sarı tuşuyla) aşağıdaki tabloda seviyesi, '
        + 'değişimleri ve tarihsel yeri izlenir. Liste herkes içindir.'));

    // ---- method
    this.sections.method = this.panel('fxvol-method', 'Yöntem ve kaynaklar', null, h('div', { class: 'fxmethod' },
      h('p', null, 'Ticker\'lar: ', h('code', null, '<PARİTE>V<vade> BGN Curncy'), ' (ATM), ', h('code', null, '25R'), ' / ', h('code', null, '10R'), ' (risk reversal), ',
        h('code', null, '25B'), ' / ', h('code', null, '10B'), ' (butterfly), spot ', h('code', null, '<PARİTE> Curncy'), '. Fiyat kaynağı (BGN) masanın ortak ayarıdır. '
        + 'Her paritenin izlenen seti: ATM 1W 1M 3M 6M 1Y, 25D RR ve BF 1M 3M 1Y, 10D RR ve BF 1M; ayrıntıda bütün vadeler.'),
      h('p', null, 'Değişim ve istatistikler Masa sayfasının Makro bloğundaki gibidir: hafta içi günler (boş gün önceki kapanışla), Δ1G / Δ1H / Δ1A canlı değerin 1 / 5 / 21 iş günü önceki '
        + 'kapanışa farkı; z 3A son 63 kapanışa, z ve yüzdelik seçili pencereye göre; |z| ≥ 1,5 vurgulu.'),
      h('p', null, 'Tarihçe: her vol\'ün günlük kapanışı (PX_LAST) bir kez bir yıl geriye, sonra günde bir son on gün istenir ve dashboard\'un tarihçe tablosunda saklanır. '
        + 'Gerçekleşen vol: spotun günlük log getirilerinin son 21 günlük standart sapması × √252.')));
    this.showSections();
  }

  panel(id, title, tools, ...body) {
    const sec = h('section', { class: 'panel wide fxpanel', id });
    const head = h('header', null, h('h2', null, title), h('span', { class: 'grow' }), ...(tools || []));
    sec.appendChild(head);
    sec.appendChild(h('div', { class: 'body fxbody' }, ...body));
    sec.titleEl = head.querySelector('h2');
    this.host.appendChild(sec);
    return sec;
  }

  copyBtn(id) {
    const b = h('button', { class: 'iconbtn', type: 'button', title: 'Tabloyu kopyala' }, 'Kopyala');
    b.addEventListener('click', () => this.grids[id] && copyGrid(this.grids[id]));
    return h('div', { class: 'tools' }, b);
  }

  showSections() {
    for (const [id] of SECTIONS) if (this.sections[id]) this.sections[id].classList.toggle('hidden', !this.on.has(id));
  }

  setGrid(id, body, header, rows, empty, onRow) {
    if (!rows.length) {
      clear(body);
      this.grids[id] = null;
      body.appendChild(h('div', { class: 'empty' }, empty));
      return null;
    }
    const data = plainData(header, rows);
    if (this.grids[id]) this.grids[id].replace(data);
    else {
      clear(body);
      const g = new Grid({ data, editable: false });
      if (onRow) {
        g.el.classList.add('pickable');
        g.el.addEventListener('click', (e) => {
          if (e.target.closest('button')) return;
          const td = e.target.closest('td');
          if (!td || td.__i === undefined || td.__i < 1) return;
          onRow(td.__i - 1, td.__j);
        });
      }
      this.grids[id] = g;
      body.appendChild(g.el);
    }
    return this.grids[id];
  }

  // ------------------------------------------------------------------ fill
  fill() {
    const m = this.mon;
    const st = m.history || {};
    this.histNote.textContent = st.phase === 'fetch' ? 'Tarihçe iniyor… (' + (st.pending || 0) + ' seri)'
      : st.last ? 'Tarihçe: son güncelleme ' + st.last : (st.auto ? 'Tarihçe sayfa açıldıkça iner' : 'Otomatik tarihçe kapalı (--no-history): "Tarihçeyi güncelle"');
    const cells = Object.values(m.cells);
    const noHist = cells.every((c) => !c.n), noLive = cells.every((c) => !isNum(c.last));
    this.banner.classList.toggle('hidden', !noHist && !noLive);
    this.banner.textContent = noLive ? 'Vol kotası gelmiyor: Bloomberg bağlı değil (kayıtlı veri modunda FX vol verisi yoktur).'
      : 'Henüz tarihçe yok: z-skoru, yüzdelik ve değişimler vol\'lerin günlük kapanışları indikçe dolar (Bloomberg bağlıyken "Tarihçeyi güncelle").';
    this.srcText.textContent = 'Fiyat kaynağı: ' + m.source;
    this.fillSummary();
    this.fillHeat();
    this.fillMovers();
    this.fillOwn();
    this.fillPair();
  }

  cell(pair, kind, tenor) { return this.mon.cells[pair + '|' + kind + '|' + tenor] || null; }

  pick(pair) {
    if (!pair || pair === this.pair) return;
    this.pair = pair;
    keep('tto.fxvol.pair', pair);
    if (!this.on.has('pair')) return;
    this.reloadPair();
    this.sections.pair.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }

  fillSummary() {
    const m = this.mon;
    const metric = this.sumMetric;
    const zc = (st) => (st && isNum(st.z) ? heatHex(st.z / 3) : null);
    const c = (st, name, digits = 2) => {
      if (!st) return { t: '', k: '' };
      const t = metric === 'last' ? (isNum(st.last) ? num(st.last, digits, false) : '') : statText(st, metric);
      const out = { t: t || (isNum(st.last) ? '' : '–'), v: metric === 'last' ? st.last : st[metric], k: 'n', tip: statTip(name, st, m.window),
        cls: isNum(st.z) && Math.abs(st.z) >= m.z_flag ? 'thru' : '' };
      const hx = zc(st);
      if (hx) out.heat = hx;
      return out;
    };
    const rows = m.rows.map((r) => {
      const p = r.pair;
      const atm1m = this.cell(p, 'ATM', '1M'), atm1y = this.cell(p, 'ATM', '1Y');
      const slope = atm1m && atm1y && isNum(atm1m.last) && isNum(atm1y.last) ? atm1y.last - atm1m.last : null;
      const vrp = isNum(r.iv1m) && isNum(r.rv1m) ? r.iv1m - r.rv1m : null;
      return [{ t: p, k: 's', b: 1, cls: p === this.pair ? 'pick' : '' }, isNum(r.spot) ? { t: num(r.spot, r.decimals || 4, false), v: r.spot, k: 'n' } : { t: '', k: '' },
        c(atm1m, p + ' ATM 1M'), c(this.cell(p, 'ATM', '3M'), p + ' ATM 3M'), c(atm1y, p + ' ATM 1Y'),
        c(this.cell(p, 'RR25', '1M'), p + ' 25D RR 1M'), c(this.cell(p, 'RR25', '3M'), p + ' 25D RR 3M'), c(this.cell(p, 'BF25', '1M'), p + ' 25D BF 1M'),
        c(this.cell(p, 'RR10', '1M'), p + ' 10D RR 1M'),
        isNum(atm1m && atm1m.z3m) ? { t: sgn(atm1m.z3m, 2), v: atm1m.z3m, k: 'n', cls: Math.abs(atm1m.z3m) >= m.z_flag ? 'thru' : '', tip: 'ATM 1M: son 63 kapanışa göre z' } : { t: '', k: '' },
        isNum(atm1m && atm1m.pct) ? { t: num(atm1m.pct * 100, 0, false) + '%', v: atm1m.pct, k: 'n', bar: Math.round(atm1m.pct * 100), bc: 'info',
          tip: 'ATM 1M\'nin ' + atm1m.window + ' kapanış içindeki yüzdeliği' } : { t: '', k: '' },
        isNum(vrp) ? { t: sgn(vrp, 2), v: vrp, k: 'n', tip: 'ATM 1M ' + num(r.iv1m, 2, false) + ' − gerçekleşen 21g ' + num(r.rv1m, 2, false) } : { t: '', k: '' },
        isNum(slope) ? { t: sgn(slope, 2), v: slope, k: 'n', tip: 'ATM 1Y − ATM 1M' } : { t: '', k: '' },
        { t: '', k: '', act: [] }];
    });
    const label = { last: '', d1: ' Δ1G', w1: ' Δ1H', m1: ' Δ1A' }[metric];
    const g = this.setGrid('summary', this.sumBody, ['Parite', 'Spot', 'ATM 1M' + label, 'ATM 3M' + label, 'ATM 1Y' + label, '25D RR 1M' + label, '25D RR 3M' + label,
      '25D BF 1M' + label, '10D RR 1M' + label, 'ATM 1M z 3A', 'ATM 1M yüzdelik', 'İma − gerç. 1M', 'Eğim 1Y−1M', 'ATM 1M · 1 yıl'], rows,
      'Parite yok', (i) => this.pick(m.rows[i] && m.rows[i].pair));
    // sparklines in the last column (drawn into the cells the grid made)
    if (g) {
      g.tds.slice(1).forEach((line, i) => {
        const td = line[line.length - 1];
        const r = m.rows[i];
        if (!td || !r) return;
        clear(td);
        td.appendChild(spark(r.spark_atm || []));
      });
    }
  }

  fillHeat() {
    const m = this.mon;
    const cols = m.core.map(([kind, tenor]) => ({ kind, tenor }));
    const box = clear(this.heatBody);
    const t = h('table', { class: 'fxheat' });
    const groups = [];
    for (const c of cols) {
      const g = groups[groups.length - 1];
      if (g && g.kind === c.kind) g.n += 1; else groups.push({ kind: c.kind, n: 1 });
    }
    t.appendChild(h('tr', null, h('th', { class: 'row' }, ''), ...groups.map((g) => h('th', { colspan: String(g.n) }, KIND[g.kind] || g.kind))));
    t.appendChild(h('tr', null, h('th', { class: 'row' }, ''), ...cols.map((c) => h('th', null, c.tenor))));
    // a move is coloured against the largest of its column, a z-score / percentile by itself
    const caps = cols.map((c) => Math.max(1e-9, ...m.rows.map((r) => {
      const st = this.cell(r.pair, c.kind, c.tenor);
      return st && isNum(st[this.metric]) ? Math.abs(st[this.metric]) : 0;
    })));
    for (const r of m.rows) {
      const tr = h('tr', null, h('th', { class: 'row' }, r.pair));
      cols.forEach((c, j) => {
        const st = this.cell(r.pair, c.kind, c.tenor);
        if (!st || !isNum(st.last)) { tr.appendChild(h('td', { class: 'none', title: st ? statTip(r.pair + ' ' + KIND[c.kind] + ' ' + c.tenor, st, m.window) : '' }, '')); return; }
        const big = this.metric === 'last' ? num(st.last, 2, false) : statText(st, this.metric) || '–';
        const td = h('td', { title: statTip(r.pair + ' ' + KIND[c.kind] + ' ' + c.tenor, st, m.window) },
          h('div', { class: 'c' }, big), h('div', { class: 'l' }, this.metric === 'last' ? (isNum(st.z) ? 'z ' + sgn(st.z, 1) : '') : num(st.last, 2, false)));
        const tone = this.metric === 'z' || this.metric === 'last' ? (isNum(st.z) ? st.z / 3 : null)
          : this.metric === 'pct' ? (isNum(st.pct) ? (st.pct - 0.5) * 2 : null)
            : (isNum(st[this.metric]) ? st[this.metric] / caps[j] : null);
        paint(td, tone);
        td.addEventListener('click', () => this.pick(r.pair));
        tr.appendChild(td);
      });
      t.appendChild(tr);
    }
    box.appendChild(t);
  }

  fillMovers() {
    const m = this.mon;
    const box = clear(this.moversBody);
    const all = [];
    for (const r of m.rows) {
      for (const [kind, tenor] of m.core) {
        const st = this.cell(r.pair, kind, tenor);
        if (st && isNum(st.last)) all.push({ name: r.pair + ' ' + KIND[kind] + ' ' + tenor, pair: r.pair, st });
      }
    }
    for (const o of m.own) if (isNum(o.last)) all.push({ name: o.label, st: o });
    const day = all.filter((x) => isNum(x.st.d1)).sort((a, b) => Math.abs(b.st.d1) - Math.abs(a.st.d1)).slice(0, 12);
    const far = all.filter((x) => isNum(x.st.z) && (Math.abs(x.st.z) >= m.z_flag || x.st.pct >= 0.95 || x.st.pct <= 0.05))
      .sort((a, b) => Math.abs(b.st.z) - Math.abs(a.st.z)).slice(0, 12);
    const table = (id, list, empty) => {
      const holder = h('div');
      const rows = list.map((x) => [{ t: x.name, k: 's', b: 1, tip: statTip(x.name, x.st, m.window) }, { t: num(x.st.last, 2, false), v: x.st.last, k: 'n' },
        { t: sgn(x.st.d1, 2), v: x.st.d1, k: 'n' }, { t: sgn(x.st.w1, 2), v: x.st.w1, k: 'n' }, { t: sgn(x.st.z, 2), v: x.st.z, k: 'n', cls: isNum(x.st.z) && Math.abs(x.st.z) >= m.z_flag ? 'thru' : '' },
        isNum(x.st.pct) ? { t: num(x.st.pct * 100, 0, false) + '%', v: x.st.pct, k: 'n', bar: Math.round(x.st.pct * 100), bc: 'info' } : { t: '', k: '' }]);
      this.setGrid(id, holder, ['Vol', 'Son', 'Δ1G', 'Δ1H', 'z', 'Yüzdelik'], rows, empty, (i) => list[i] && list[i].pair && this.pick(list[i].pair));
      return holder;
    };
    this.grids.day = null;
    this.grids.far = null;
    box.appendChild(h('div', null, h('div', { class: 'ct' }, 'Günün en büyük değişimleri (vol puanı)'), table('day', day, 'Dünkü kapanış yok: tarihçe gerekiyor')));
    box.appendChild(h('div', null, h('div', { class: 'ct' }, 'Tarihsel uçta (|z| ≥ ' + num(m.z_flag, 1, false) + ' ya da yüzdelik ≤ %5 / ≥ %95)'), table('far', far, 'Uçta duran yok')));
  }

  fillOwn() {
    const m = this.mon;
    clear(this.ownPairs);
    if (!m.own_pairs.length) this.ownPairs.appendChild(h('span', { class: 'muted' }, 'yok'));
    for (const p of m.own_pairs) {
      const b = h('button', { type: 'button', class: 'on', title: (p.by ? 'Ekleyen: ' + this.ctx.displayName(p.by) + ' · ' : '') + 'Çıkarmak için tıklayın' }, p.text + ' ✕');
      b.addEventListener('click', () => this.removeTicker(p));
      this.ownPairs.appendChild(b);
    }
    const rows = m.own.map((o) => [{ t: o.label, k: 's', b: 1, tip: (o.by ? 'Ekleyen: ' + this.ctx.displayName(o.by) : '') }, { t: o.ticker, k: 's', cls: 'soft' },
      isNum(o.last) ? { t: num(o.last, 3, false), v: o.last, k: 'n', b: 1 } : { t: o.why || 'veri yok', k: 's', cls: 'soft' },
      { t: sgn(o.d1, 3), v: o.d1, k: 'n' }, { t: sgn(o.w1, 3), v: o.w1, k: 'n' }, { t: sgn(o.m1, 3), v: o.m1, k: 'n' },
      { t: sgn(o.z3m, 2), v: o.z3m, k: 'n' }, { t: sgn(o.z, 2), v: o.z, k: 'n', cls: isNum(o.z) && Math.abs(o.z) >= m.z_flag ? 'thru' : '' },
      isNum(o.pct) ? { t: num(o.pct * 100, 0, false) + '%', v: o.pct, k: 'n', bar: Math.round(o.pct * 100), bc: 'info' } : { t: '', k: '' },
      { t: isNum(o.min) ? num(o.min, 3, false) + ' – ' + num(o.max, 3, false) : '', k: 's' }, { t: String(o.n || ''), k: 'n' },
      { t: '', k: '', act: [{ label: '✕', title: 'Listeden çıkar', fn: () => this.removeTicker(o) }] }]);
    this.setGrid('own', this.ownBody, ['Ad', 'Ticker', 'Son', 'Δ1G', 'Δ1H', 'Δ1A', 'z 3A', 'z', 'Yüzdelik', 'Aralık', 'Kapanış', ''], rows,
      'Henüz eklenmiş ticker yok');
  }

  async addTicker() {
    const text = this.ownInput.value.trim();
    if (!text) return;
    try {
      const res = await api.post('/api/fx/tickers', { text, label: this.ownLabel.value.trim() });
      toast((res.added.kind === 'pair' ? 'Parite' : 'Ticker') + ' eklendi: ' + res.added.text, 'ok');
      this.ownInput.value = '';
      this.ownLabel.value = '';
      this.reloadMonitor();
    } catch (err) { errorToast(err); }
  }

  async removeTicker(item) {
    const name = item.text || item.ticker;
    if (!(await confirmDialog('Listeden çıkar', name + ' herkesin listesinden çıkarılsın mı?', 'Çıkar', true))) return;
    try {
      await api.post('/api/fx/tickers', { remove: item.id });
      this.reloadMonitor();
    } catch (err) { errorToast(err); }
  }

  async setSource() {
    const v = await promptDialog('Vol ticker\'larının fiyat kaynağı', 'Bloomberg kaynak kodu (BGN, CMPN, bir broker kodu …) — herkes için', this.mon.source);
    if (!v) return;
    try {
      await api.post('/api/fx/tickers', { source: v });
      toast('Fiyat kaynağı: ' + v.toUpperCase(), 'ok');
      this.reloadMonitor();
    } catch (err) { errorToast(err); }
  }

  async sync() {
    try {
      const st = await api.post('/api/fx/history', { pair: this.pair });
      toast('Tarihçe isteniyor (' + (st.pending || 0) + ' seri) — inince tablolar dolar', 'ok', 5000);
      setTimeout(() => this.reloadMonitor(), 4000);
    } catch (err) { errorToast(err); }
  }

  // ------------------------------------------------------------------ one pair
  fillPair() {
    const d = this.det;
    if (!d || !this.mon) return;
    clear(this.pairSeg);
    const pairs = this.mon.pairs.map((p) => [p.code, p.code]);
    const sel = h('select', { class: 'inp', id: 'fxvol-pair-select', style: { width: '110px', height: '26px' } });
    for (const [v] of pairs) {
      const o = h('option', { value: v }, v);
      if (v === this.pair) o.selected = true;
      sel.appendChild(o);
    }
    sel.addEventListener('change', () => this.pick(sel.value));
    this.pairSeg.appendChild(sel);
    clear(this.tenorSeg);
    this.tenorSeg.appendChild(seg(d.tenors.map((t) => [t, t]), d.tenor, (v) => { this.tenor = v; keep('tto.fxvol.tenor', v); this.reloadPair(); }, 'fxvol-tenor'));
    this.sections.pair.titleEl.textContent = d.pair + ' · ayrıntı (' + (d.pair_info ? d.pair_info.convention : '') + ')';
    const s = d.structure;
    const lineSpec = (title, cats, series, digits = 2, y = 'vol %') => ({ title, cats, auto: 'fit', decimals: digits, y_title: y, aspect: 0.5, series });
    const three = (k, name) => [{ name: name + ' bugün', kind: 'line', color: BLUE, data: s[k].now, marker: true },
      { name: name + ' 1H önce', kind: 'line', color: ORANGE, data: s[k].w1, marker: true, dash: true },
      { name: name + ' 1A önce', kind: 'line', color: PURPLE, data: s[k].m1, marker: true, dash: true }];
    const specs = {
      term: lineSpec('ATM vade yapısı', d.tenors, three('ATM', 'ATM')),
      rr: lineSpec('Risk reversal vade yapısı', d.tenors, [{ name: '25D bugün', kind: 'line', color: BLUE, data: s.RR25.now, marker: true },
        { name: '25D 1A önce', kind: 'line', color: BLUE, data: s.RR25.m1, marker: true, dash: true },
        { name: '10D bugün', kind: 'line', color: ORANGE, data: s.RR10.now, marker: true },
        { name: '10D 1A önce', kind: 'line', color: ORANGE, data: s.RR10.m1, marker: true, dash: true }]),
      bf: lineSpec('Butterfly vade yapısı', d.tenors, [{ name: '25D bugün', kind: 'line', color: BLUE, data: s.BF25.now, marker: true },
        { name: '25D 1A önce', kind: 'line', color: BLUE, data: s.BF25.m1, marker: true, dash: true },
        { name: '10D bugün', kind: 'line', color: ORANGE, data: s.BF10.now, marker: true },
        { name: '10D 1A önce', kind: 'line', color: ORANGE, data: s.BF10.m1, marker: true, dash: true }]),
    };
    const names = ['10P', '25P', 'ATM', '25C', '10C'];
    const sm = (k) => (d.smiles[k] ? names.map((n) => d.smiles[k][n]) : names.map(() => null));
    specs.smile = lineSpec(d.tenor + ' smile (delta)', names, [{ name: 'bugün', kind: 'line', color: BLUE, data: sm('now'), marker: true },
      { name: '1H önce', kind: 'line', color: ORANGE, data: sm('w1'), marker: true, dash: true },
      { name: '1A önce', kind: 'line', color: PURPLE, data: sm('m1'), marker: true, dash: true }]);
    // time series on one date axis
    const series = (keys, colors) => {
      const days = [...new Set([].concat(...keys.map((k) => (d.series[k] || []).map((p) => p[0]))))].sort();
      const idx = new Map(days.map((x, i) => [x, i]));
      return { days, list: keys.map((k, i) => {
        const data = days.map(() => null);
        for (const [day, v] of d.series[k] || []) data[idx.get(day)] = v;
        return { name: k, kind: 'line', color: colors[i], data, marker: false };
      }) };
    };
    const dated = (title, keys, colors) => {
      const { days, list } = series(keys, colors);
      return { title, cats: days.map(isoToTr), x: { type: 'date', values: days.map(serialOfIso), format: 'mmm yy' }, auto: 'fit', decimals: 2, y_title: 'vol %',
        aspect: 0.45, series: list, empty: !days.length };
    };
    specs.atm = dated('ATM · 1 yıl', ['ATM 1M', 'ATM 3M', 'ATM 1Y'], [BLUE, ORANGE, PURPLE]);
    specs.rrs = dated('Risk reversal · 1 yıl', ['25D RR 1M', '25D RR 3M', '10D RR 1M'], [BLUE, ORANGE, PURPLE]);
    specs.bfs = dated('Butterfly · 1 yıl', ['25D BF 1M', '10D BF 1M'], [BLUE, ORANGE]);
    // implied against realized
    const rv = d.realized.filter((p) => isNum(p[1]));
    const atm = new Map((d.series['ATM 1M'] || []));
    const days = [...new Set(rv.map((p) => p[0]).concat([...atm.keys()]))].sort();
    const rvm = new Map(rv);
    specs.rv = { title: 'İma (ATM 1M) ve gerçekleşen (21g) vol', cats: days.map(isoToTr), x: { type: 'date', values: days.map(serialOfIso), format: 'mmm yy' },
      auto: 'fit', decimals: 2, y_title: 'vol %', aspect: 0.45, empty: !days.length,
      series: [{ name: 'ATM 1M', kind: 'line', color: BLUE, data: days.map((x) => (atm.has(x) ? atm.get(x) : null)) },
        { name: 'gerçekleşen 21g', kind: 'line', color: GREEN, data: days.map((x) => (rvm.has(x) ? rvm.get(x) : null)) }] };
    const order = [['term', 'ATM vade yapısı: bugün, 1 hafta ve 1 ay önce'], ['smile', d.tenor + ' smile: 10P · 25P · ATM · 25C · 10C (SVI, kendi delta strike\'larında)'],
      ['rr', 'Risk reversal (25D, 10D): bugün ve 1 ay önce'], ['bf', 'Butterfly (25D, 10D): bugün ve 1 ay önce'],
      ['atm', 'ATM 1M · 3M · 1Y'], ['rrs', 'Risk reversal 1M · 3M'], ['bfs', 'Butterfly 1M'], ['rv', 'İma ve gerçekleşen vol']];
    if (!this.chartHosts) {
      clear(this.pairCharts);
      this.chartHosts = {};
      for (const [k, title] of order) {
        const host = h('div', { class: 'volchart' });
        const head = h('div', { class: 'ct' }, title);
        this.chartHosts[k] = { host, head };
        this.pairCharts.appendChild(h('div', null, head, host));
      }
    }
    for (const [k, title] of order) {
      const spec = specs[k];
      const { host, head } = this.chartHosts[k];
      head.textContent = k === 'smile' ? title.replace(/^\S+/, d.tenor) : title;
      const empty = spec.empty || !spec.series.some((x) => (x.data || []).some(isNum));
      if (empty) {
        if (this.charts[k]) { this.charts[k].destroy(); this.charts[k] = null; }
        clear(host);
        host.appendChild(h('div', { class: 'chart-empty' }, k === 'smile' || k === 'term' || k === 'rr' || k === 'bf' ? 'Kota yok' : 'Tarihçe yok'));
        continue;
      }
      if (host.firstChild && host.firstChild.classList && host.firstChild.classList.contains('chart-empty')) clear(host);
      if (this.charts[k]) this.charts[k].update(spec); else this.charts[k] = new Chart(host, spec, { height: 240 });
    }
    this.pairNote.textContent = '1H / 1A önce: 5 / 21 iş günü önceki kapanışlar (kesikli). Smile, o günün ATM, RR ve BF kapanışlarından aynı yöntemle (SVI) kurulur; '
      + 'bir günün RR / BF kapanışı yoksa o gün için çizilmez. Zaman serileri ve gerçekleşen vol tarihçeden.';
  }
}
