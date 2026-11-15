// What the quant pages share (quant.js: Sinyaller; quantviews.js: the analysis pages): cell helpers, a table in a panel
// whose rows can be picked, the chart of one signal (its series with ±z bands and entry / target / stop) and the page
// frame - load, a refresh when the server's result moved, the status and data-coverage tables.
import { api } from '../api.js';
import { h, clear, errorToast, toast } from '../ui.js';
import { Grid, plainData, copyGrid } from '../grid.js';
import { toolsOf } from '../columns.js';
import { Chart } from '../chart.js';
import { num, isoToTr } from '../format.js';

export const BLUE = '4F81BD', GREY = '7F7F7F', PURPLE = '8064A2', GREEN = '9BBB59', RED = 'C0504D', ORANGE = 'F79646';
export const isNum = (v) => typeof v === 'number' && isFinite(v);
export const sgn = (v, d = 2) => (isNum(v) ? (v > 0 ? '+' : '') + num(v, d, false) : '');
export const fmt = (v, d = 2) => (isNum(v) ? num(v, d, false) : '');
export const pct = (v, d = 0) => (isNum(v) ? num(v * 100, d, false) + '%' : '');
const serialOf = (iso) => Math.round(Date.UTC(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10)) / 86400000) + 25569;

export const REGIME = { MR: 'Ortalamaya dönüş', Trend: 'Trend', 'Nötr': 'Nötr' };

/** A number cell: text, value, an optional class and tooltip. */
export function N(v, d = 2, opts = {}) {
  if (!isNum(v)) return { t: opts.empty || '', k: '' };
  return Object.assign({ t: (opts.sign ? sgn(v, d) : fmt(v, d)) + (opts.unit ? ' ' + opts.unit : ''), v, k: 'n' }, opts.cls ? { cls: opts.cls } : {},
    opts.tip ? { tip: opts.tip } : {}, opts.heat ? { heat: opts.heat } : {}, opts.b ? { b: 1 } : {});
}

export function T(t, opts = {}) {
  return Object.assign({ t: t == null ? '' : String(t), k: 's' }, opts);
}

/** A z cell: bold past the entry threshold. */
export function Z(v, entry = 2, opts = {}) {
  if (!isNum(v)) return { t: '', k: '' };
  return Object.assign({ t: sgn(v, 2), v, k: 'n', cls: Math.abs(v) >= entry ? 'thru' : '' }, opts.heat ? { heat: heatHex(v / 3) } : {},
    opts.tip ? { tip: opts.tip } : {});
}

/** Red up, blue down, deeper as |t| nears 1 (a hex colour; the grid takes its strength from the colour's chroma). */
export function heatHex(t) {
  if (!isNum(t) || Math.abs(t) < 0.02) return null;
  const a = Math.min(1, Math.abs(t));
  const base = t > 0 ? [230, 103, 103] : [57, 135, 229];
  return base.map((c) => Math.round(128 + (c - 128) * a).toString(16).padStart(2, '0')).join('').toUpperCase();
}

export function seg(options, value, onChange, id) {
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

export function pref(key, fallback) {
  try { const v = localStorage.getItem(key); return v === null ? fallback : v; } catch (e) { return fallback; }
}

export function keep(key, value) {
  try { localStorage.setItem(key, String(value)); } catch (e) { /* not kept */ }
}

/** A panel with a title, its tools (copy) and a body: ``{el, body, note, setTitle}``. */
export function panel(id, title, opts = {}) {
  const body = h('div', { class: 'body' });
  const note = h('div', { class: 'muted qnote' });
  const head = h('h2', null, title);
  const tools = h('div', { class: 'tools' });
  const el = h('section', { class: 'panel wide' + (opts.cls ? ' ' + opts.cls : ''), id },
    h('header', null, head, h('span', { class: 'grow' }), ...(opts.right || []), tools), opts.top || null, body, note);
  return { el, body, note, tools, setTitle: (t) => { head.textContent = t; } };
}

/**
 * A table of the dashboard's grid in a panel body: rows can be clicked (``onPick(key)``), the picked one is marked,
 * the copy button puts it on the clipboard (Excel).
 */
export class GridBox {
  constructor(p, name, onPick) {
    this.p = p;
    this.name = name;
    this.onPick = onPick;
    this.grid = null;
    this.keys = [];
    const copy = h('button', { class: 'iconbtn', type: 'button', title: 'Tabloyu kopyala (Excel\'e yapıştırılabilir)' }, 'Kopyala');
    copy.addEventListener('click', () => { if (this.grid) copyGrid(this.grid); });
    p.tools.appendChild(copy);
  }

  set(header, rows, keys, empty, picked) {
    this.keys = keys || [];
    const body = this.p.body;
    if (!rows.length) {
      clear(body);
      this.grid = null;
      body.appendChild(h('div', { class: 'empty' }, empty || 'Veri yok'));
      return;
    }
    const marked = rows.map((row, i) => (picked && this.keys[i] === picked
      ? row.map((c) => (c && typeof c === 'object' ? (c.sk ? c : Object.assign({}, c, { cls: ((c.cls || '') + ' pick').trim() })) : { t: c == null ? '' : String(c), k: 's', cls: 'pick' }))
      : row));
    const data = plainData(header, marked);
    if (this.grid) { this.grid.replace(data); return; }
    clear(body);
    const g = new Grid({ data, editable: false, name: this.name, tools: toolsOf(body) });
    if (this.onPick) {
      g.el.classList.add('pickable');
      g.el.addEventListener('click', (e) => {
        if (e.target.closest('button')) return;
        const td = e.target.closest('td');
        if (!td || td.__i === undefined || td.__i < 1) return;
        const k = this.keys[td.__i - 1];
        if (k) this.onPick(k);
      });
    }
    this.grid = g;
    body.appendChild(g.el);
  }
}

// ------------------------------------------------------------------------------------------------ one signal, drawn
/** The series of a signal (or of any monitor): the level with its window mean, ±entry and ±stop bands (in z), the
 * entry / target / stop lines; below it the score day by day against ±entry and ±stop. */
export class SignalChart {
  constructor(host) {
    this.host = host;
    this.charts = {};
    this.el = h('div', { class: 'seriesview qchart' });
    this.titleEl = h('div', { class: 'ct svtitle' });
    this.statEl = h('div', { class: 'muted svstat' });
    this.levelHead = h('div', { class: 'ct' });
    this.zHead = h('div', { class: 'ct' });
    this.levelHost = h('div', { class: 'volchart' });
    this.zHost = h('div', { class: 'volchart' });
    this.zBox = h('div', null, this.zHead, this.zHost);
    this.plots = h('div', { class: 'volcharts svcharts' }, h('div', null, this.levelHead, this.levelHost), this.zBox);
    this.details = h('div', { class: 'qdetails' });
    this.empty = h('div', { class: 'empty' }, 'Bir sinyale ya da satıra tıklayın: serisi, ±z bantları ve giriş / hedef / stop burada çizilir.');
    this.el.append(this.titleEl, this.statEl, this.plots, this.details, this.empty);
    this.plots.classList.add('hidden');
    host.appendChild(this.el);
  }

  destroy() {
    for (const c of Object.values(this.charts)) if (c) c.destroy();
    this.charts = {};
    this.el.remove();
  }

  loading(title) {
    this.titleEl.textContent = title || '';
    this.empty.textContent = 'Yükleniyor…';
    this.empty.classList.remove('hidden');
    this.plots.classList.add('hidden');
  }

  show(d) {
    const m = d.monitor || {};
    const s = d.signal;
    const hist = d.history || {};
    const cfg = d.settings || {};
    const days = hist.days || [];
    const vals = hist.values || [];
    this.titleEl.textContent = (m.family_label ? m.family_label + ' · ' : '') + (s ? s.expression : m.name || '');
    clear(this.details);
    if (days.length < 2) {
      this.plots.classList.add('hidden');
      this.empty.classList.remove('hidden');
      this.empty.textContent = 'Bu serinin geçmişi yok.';
      return;
    }
    this.empty.classList.add('hidden');
    this.plots.classList.remove('hidden');
    const digits = isNum(m.digits) ? m.digits : 2;
    const entryZ = isNum(m.entry) ? m.entry : (cfg.entry_z || 2);
    const stopZ = cfg.stop_z || 3.5;
    const fisher = hist.transform === 'fisher';
    const fw = (x) => (fisher ? 0.5 * Math.log((1 + x) / (1 - x)) : x);
    const inv = (x) => (fisher ? Math.tanh(x) : x);
    const allDays = days.slice();
    const allVals = vals.slice();
    if (isNum(m.level) && d.today && d.today > days[days.length - 1]) { allDays.push(d.today); allVals.push(m.level); }
    const flat = (v) => allDays.map(() => (isNum(v) ? v : null));
    const series = [{ name: m.name || 'seri', kind: 'line', color: BLUE, data: allVals, marker: false }];
    const mr = isNum(hist.mean) && isNum(hist.sd) && m.mode !== 'drift';
    if (mr) {
      const mu = fw(hist.mean);
      series.push({ name: 'ortalama', kind: 'line', color: GREY, data: flat(hist.mean), marker: false });
      series.push({ name: '±' + num(entryZ, 1, false) + 'σ (giriş)', kind: 'line', color: GREY, dash: true, data: flat(inv(mu + entryZ * hist.sd)), marker: false });
      series.push({ name: '−giriş', kind: 'line', color: GREY, dash: true, data: flat(inv(mu - entryZ * hist.sd)), marker: false, legend: 0 });
      series.push({ name: '±' + num(stopZ, 1, false) + 'σ (stop)', kind: 'line', color: RED, dash: true, data: flat(inv(mu + stopZ * hist.sd)), marker: false });
      series.push({ name: '−stop', kind: 'line', color: RED, dash: true, data: flat(inv(mu - stopZ * hist.sd)), marker: false, legend: 0 });
    }
    if (s) {
      series.push({ name: 'giriş (şimdi)', kind: 'line', color: PURPLE, data: flat(s.entry), marker: false });
      series.push({ name: 'hedef', kind: 'line', color: GREEN, data: flat(s.target), marker: false });
      series.push({ name: 'stop', kind: 'line', color: ORANGE, data: flat(s.stop), marker: false });
    }
    const x = { type: 'date', values: allDays.map(serialOf), format: 'mmm yy' };
    const unit = m.unit || '';
    const level = { title: m.name, cats: allDays.map(isoToTr), x, auto: 'fit', decimals: digits, y_title: unit, aspect: 0.42, series };
    this.levelHead.textContent = 'Seviye' + (unit ? ' (' + unit + ')' : '') + (mr ? ' · ortalama, ±giriş ve ±stop bantları penceresinin σ\'sıyla' : '');
    if (this.charts.level) this.charts.level.update(level); else this.charts.level = new Chart(this.levelHost, level, { height: 250 });
    const zs = (hist.z || []).slice();
    const hasZ = zs.some(isNum);
    this.zBox.classList.toggle('hidden', !hasZ);
    if (hasZ) {
      const zDays = days.slice();
      if (isNum(m.z) && d.today && d.today > days[days.length - 1]) { zDays.push(d.today); zs.push(m.z); }
      const zf = (v) => zDays.map(() => v);
      const zspec = { title: (m.score_name || 'z'), cats: zDays.map(isoToTr), x: { type: 'date', values: zDays.map(serialOf), format: 'mmm yy' },
        auto: 'fit', decimals: 2, y_title: m.score_name || 'z', aspect: 0.42,
        series: [{ name: m.score_name || 'z', kind: 'line', color: PURPLE, data: zs, marker: false },
          { name: '±giriş', kind: 'line', color: GREY, dash: true, data: zf(entryZ), marker: false },
          { name: '−giriş', kind: 'line', color: GREY, dash: true, data: zf(-entryZ), marker: false, legend: 0 },
          { name: '±stop', kind: 'line', color: RED, dash: true, data: zf(stopZ), marker: false },
          { name: '−stop', kind: 'line', color: RED, dash: true, data: zf(-stopZ), marker: false, legend: 0 }] };
      this.zHead.textContent = (m.score_name || 'z') + ' · gün gün';
      if (this.charts.z) this.charts.z.update(zspec); else this.charts.z = new Chart(this.zHost, zspec, { height: 250 });
    }
    this.statEl.textContent = 'Şimdi ' + fmt(m.level, digits) + (unit ? ' ' + unit : '') + ' · ' + (m.score_name || 'z') + ' ' + sgn(m.z, 2)
      + (isNum(m.half_life) ? ' · yarı ömür ' + fmt(m.half_life, 1) + ' gün' : '')
      + (m.regime && m.regime.tag ? ' · rejim ' + (REGIME[m.regime.tag] || m.regime.tag) : '')
      + ' · ' + isoToTr(days[0]) + ' – ' + isoToTr(days[days.length - 1]) + ' · ' + days.length + ' gün';
    this.fillDetails(d);
  }

  fillDetails(d) {
    const m = d.monitor || {};
    const s = d.signal;
    const box = this.details;
    if (s) {
      const legs = h('table', { class: 'plain qlegs' }, h('tr', null, h('th', null, 'Bacak'), h('th', null, 'Ağırlık'), h('th', null, 'DV01'), h('th', null, 'Nominal (mn)')));
      for (const l of s.legs || []) {
        legs.appendChild(h('tr', null, h('td', null, l.text), h('td', { class: 'n' }, fmt(l.weight, 2)), h('td', { class: 'n' }, isNum(l.dv01) ? sgn(l.dv01, 0) : ''),
          h('td', { class: 'n' }, isNum(l.notional) ? fmt(l.notional, 1) : '')));
      }
      const p = s.parts || {};
      const lines = [
        ['Yön', s.expression],
        ['Skor', (s.score_name || 'z') + ' ' + sgn(s.z, 2) + ' (giriş ' + fmt(s.entry_z, 2) + ') · ' + s.strength],
        ['Giriş / hedef / stop', fmt(s.entry, s.digits) + ' / ' + fmt(s.target, s.digits) + ' / ' + fmt(s.stop, s.digits) + (s.unit ? ' ' + s.unit : '')],
        ['Yarı ömür · tutma', (isNum(s.half_life) ? fmt(s.half_life, 1) + ' gün' : '—') + ' · ' + (isNum(s.hold) ? fmt(s.hold, 0) + ' gün' : '—')],
        ['Carry + roll / hafta', isNum(s.carry_week) ? sgn(s.carry_week, 2) + ' bp' : '—'],
        ['Rejim', (s.regime || '—') + (s.regime_info && isNum(s.regime_info.vr_z) ? ' (VR ' + fmt(s.regime_info.vr, 2) + ', z ' + sgn(s.regime_info.vr_z, 2)
          + (isNum(s.regime_info.hurst) ? ', H ' + fmt(s.regime_info.hurst, 2) : '') + (isNum(s.regime_info.vol_pct) ? ', vol yüzdelik ' + pct(s.regime_info.vol_pct) : '') + ')' : '')],
        ['Uyum', s.agree + ' aile aynı yönde' + (s.agree_with && s.agree_with.length ? ' (' + s.agree_with.join(', ') + ')' : '')
          + (s.conflict ? ' · ' + s.conflict + ' ters (' + s.conflict_with.join(', ') + ')' : '')],
        ['Bileşik', fmt(s.composite, 2) + ' = |z| ' + fmt(p.z, 2) + ' × rejim ' + fmt(p.regime, 2) + ' × yarı ömür ' + fmt(p.hl, 2) + ' × carry ' + fmt(p.carry, 2)
          + (s.gated ? ' · elendi: ' + s.gated : '')],
      ];
      const kv = h('table', { class: 'plain qkv' });
      for (const [k, v] of lines) kv.appendChild(h('tr', null, h('th', null, k), h('td', null, v)));
      box.append(h('div', { class: 'qcols' }, kv, legs));
    }
    const info = m.info || {};
    const extra = [];
    if (info.ou && isNum(info.ou.b)) extra.push('OU: b ' + fmt(info.ou.b, 3) + (isNum(info.ou.mu) ? ', μ ' + fmt(info.ou.mu, 2) : '') + (isNum(info.ou.sigma_eq) ? ', σ_eq ' + fmt(info.ou.sigma_eq, 2) : ''));
    if (isNum(info.beta)) extra.push('β ' + fmt(info.beta, 3) + (isNum(info.static_beta) ? ' (statik ' + fmt(info.static_beta, 3) + ', statik z ' + sgn(info.static_z, 2) + ')' : '')
      + (isNum(info.adf) ? ' · ADF ' + fmt(info.adf, 2) + ' (%5 kritik ' + fmt(info.crit5, 2) + ')' : ''));
    if (isNum(info.hit_rate)) extra.push('Model: yukarı olasılığı ' + pct(info.p, 1) + ' · doğrulama isabeti ' + pct(info.hit_rate, 1) + ' (' + info.n_test + ' test, log-loss ' + fmt(info.log_loss, 3) + ')');
    if (info.garch && isNum(info.garch.alpha)) extra.push('GARCH(1,1): α ' + fmt(info.garch.alpha, 3) + ', β ' + fmt(info.garch.beta, 3) + ', uzun dönem vol ' + fmt(Math.sqrt(252 * info.garch.long_var), 2));
    if (info.phase) extra.push('Faz: ' + info.phase + ' · ortalama ' + sgn(info.mean, 1) + ' bp · n ' + info.n + ' · t ' + sgn(info.t, 2));
    if (m.note) extra.push(m.note);
    for (const t of extra) box.appendChild(h('div', { class: 'muted qline' }, t));
  }
}

/** The rows of a signal table (the ranked list, and each analysis page's own signals). */
export function signalRows(list, opts = {}) {
  return list.map((s, i) => {
    const row = [];
    if (opts.rank) row.push({ t: String(i + 1), v: i + 1, k: 'n' });
    row.push(T(s.family_label), T(s.asset), T(s.expression, { b: 1, tip: (s.legs || []).map((l) => l.text).join('\n') + (s.note ? '\n' + s.note : '') }),
      Z(s.z, s.entry_z, { tip: (s.score_name || 'z') + ' · giriş eşiği ' + fmt(s.entry_z, 2) }), T(s.strength, { cls: 'qs-' + (s.strength || '').toLowerCase() }),
      N(s.entry, s.digits), N(s.target, s.digits), N(s.stop, s.digits), T(s.unit),
      N(s.half_life, 1), N(s.hold, 0), N(s.carry_week, 2, { sign: true, tip: 'Carry + roll, işlemin yönünde (bp / hafta)' }),
      T(s.regime || '—'), T(s.agree + (s.conflict ? ' / −' + s.conflict : ''), { tip: (s.agree_with || []).join(', ') + (s.conflict ? '\nters: ' + s.conflict_with.join(', ') : '') }));
    if (opts.gated) row.push(T(s.gated, { cls: 'soft' }));
    else row.push(N(s.composite, 2, { b: 1, tip: '|z| ' + fmt(s.parts.z, 2) + ' × rejim ' + fmt(s.parts.regime, 2) + ' × yarı ömür ' + fmt(s.parts.hl, 2) + ' × carry ' + fmt(s.parts.carry, 2) }));
    row.push(T((s.live ? '● ' : '') + (s.time || ''), { tip: s.live ? 'canlı değerle' : 'son kapanışla' }));
    return row;
  });
}

export const SIGNAL_HEAD = ['Aile', 'Varlık', 'İşlem', 'z', 'Güç', 'Giriş', 'Hedef', 'Stop', 'Birim', 'Yarı ömür (g)', 'Tutma (g)', 'Carry / hf', 'Rejim', 'Uyum'];

/** A status table of the quant worker: what every page shows at the bottom (and the first thing before a result). */
export function statusRows(st) {
  st = st || {};
  const t = st.timing || {};
  const rows = [[T('Son tam hesap'), T(st.fit_at || 'henüz yok')], [T('Tam hesabın süresi'), N(st.fit_ms, 0, { unit: 'ms' })],
    [T('Son canlı yenileme'), T(st.live_at || '—')], [T('Canlı yenilemenin süresi'), N(st.live_ms, 0, { unit: 'ms' })],
    [T('Motor iş parçacığında geçen (son okuma)'), N(st.engine_ms, 1, { unit: 'ms', tip: 'Çalışma kitabından kısa okuma; hesapların kendisi ayrı iş parçacığında' })],
    [T('İzlenen enstrüman'), N(st.monitors, 0)], [T('Durum'), T(st.phase === 'fit' ? 'hesaplanıyor…' : (st.error ? 'hata: ' + st.error : 'hazır'))]];
  for (const [k, v] of Object.entries(t)) rows.push([T('  · ' + k), N(v, 0, { unit: 'ms' })]);
  for (const [k, v] of Object.entries(st.errors || {})) rows.push([T('  ! ' + k), T(v, { cls: 'soft' })]);
  return rows;
}

// ------------------------------------------------------------------------------------------------ the shared page frame
export const live = { page: null, version: 0, alerts: null, busy: false };

/** What every quant page shares: load, a refresh when the server's result moved (or a minute passed), the status
 * table, the chart of a picked signal. */
export class QuantPage {
  constructor(host, ctx, what) {
    this.host = host;
    this.ctx = ctx;
    this.what = what;
    this.data = null;
    this.version = -1;
    this.loaded = 0;
    this.picked = null;
    this.boxes = {};
  }

  async load() {
    clear(this.host);
    this.host.appendChild(h('div', { class: 'loading' }, 'Yükleniyor…'));
    const d = await this.fetch();
    if (this.dead) return;
    this.data = d;
    this.version = d.version;
    this.loaded = Date.now();
    clear(this.host);
    this.build();
    this.fill();
    live.page = this;
    if (!d.ready) this.poll();
  }

  fetch() {
    return api.get('/api/quant/' + this.what, this.query ? this.query() : undefined);
  }

  async refresh(force) {
    if (this.busy || this.dead) return;
    if (!force && this.data && this.data.ready && live.version === this.version && Date.now() - this.loaded < 60000) return;
    this.busy = true;
    try {
      const d = await this.fetch();
      if (this.dead) return;
      this.data = d;
      this.version = d.version;
      this.loaded = Date.now();
      this.fill();
    } catch (err) {
      if (!err.network) console.warn('quant refresh failed', err);
    } finally { this.busy = false; }
  }

  /** No result yet (the first fit runs a few seconds after the start): ask again until there is one. */
  poll() {
    clearTimeout(this.timer);
    this.timer = setTimeout(async () => {
      if (this.dead) return;
      await this.refresh(true);
      if (!this.dead && !(this.data && this.data.ready)) this.poll();
    }, 3000);
  }

  destroy() {
    this.dead = true;
    clearTimeout(this.timer);
    if (live.page === this) live.page = null;
    if (this.chart) this.chart.destroy();
    for (const c of Object.values(this.charts || {})) if (c) c.destroy();
  }

  /** Tools row: the status line and "Şimdi hesapla". */
  tools(extra = []) {
    this.statusLine = h('span', { class: 'muted', id: 'quant-status' });
    const again = h('button', { class: 'btn', type: 'button', id: 'quant-recompute', title: 'Bütün analizleri şimdi yeniden hesapla (ayrı iş parçacığında)' }, 'Şimdi hesapla');
    again.addEventListener('click', async () => {
      again.disabled = true;
      try {
        await api.post('/api/quant/recompute', {});
        toast('Hesap başladı: sonuç birkaç saniyede gelir', 'ok', 2500);
        this.poll();
      } catch (e) { errorToast(e); } finally { again.disabled = false; }
    });
    this.banner = h('div', { class: 'banner hidden', id: 'quant-banner' });
    this.host.appendChild(h('div', { class: 'page-tools' }, ...extra, h('span', { class: 'grow' }), this.statusLine, again));
    this.host.appendChild(this.banner);
  }

  fillStatus() {
    const d = this.data || {};
    const st = d.status || {};
    if (this.statusLine) {
      this.statusLine.textContent = d.ready ? 'Hesap ' + (st.fit_at || '') + ' (' + fmt(st.fit_ms / 1000, 1) + ' sn)' + (st.live_at ? ' · canlı ' + st.live_at.slice(11, 16) : '')
        : 'İlk hesap yapılıyor…';
    }
    if (this.banner) {
      const errs = Object.entries(d.errors || {});
      this.banner.classList.toggle('hidden', !!d.ready && !errs.length);
      this.banner.textContent = !d.ready ? 'Analizler hesaplanıyor (ayrı iş parçacığında); sonuç gelince sayfa kendiliğinden dolar.'
        : errs.map(([k, v]) => k + ': ' + v).join(' · ');
    }
    if (this.boxes.status) this.boxes.status.set(['Hesap', 'Değer'], statusRows(st), null, 'Durum yok');
    if (this.boxes.coverage) {
      const cov = d.coverage || [];
      this.boxes.coverage.set(['Seri', 'Grup', 'Ticker', 'Gün', 'İlk', 'Son', 'Canlı'], cov.map((c) => [T(c.label, { b: 1 }), T(c.group), T(c.ticker),
        N(c.n, 0, { cls: c.n < ((d.settings || {}).min_obs || 120) ? 'soft' : '' }), T(isoToTr(c.first)), T(isoToTr(c.last)), T(c.live ? '●' : '')]), null,
      'Kapsam bilgisi henüz yok');
    }
  }

  /** The status and the data coverage at the bottom of a page. */
  addStatus(parent) {
    const cov = panel(this.what + '-coverage', 'Veri kapsamı (günlük kapanışlar)', { cls: 'aux' });
    cov.note.textContent = 'Gün: analizlerin okuduğu kapanış sayısı (bugün hariç; bugün canlı değerdir). En az gözlemin altındakiler soluk. Yeni ticker\'lar canlı '
      + 'dashboard\'un tarihçe güncellemesiyle iki yıl geriye doldurulur (Ayarlar → tarihçe kapsamı).';
    this.boxes.coverage = new GridBox(cov, 'quant/' + this.what + '/coverage');
    const st = panel(this.what + '-status', 'Hesap durumu', { cls: 'aux' });
    st.note.textContent = 'Analizler motor iş parçacığında değil, kendi iş parçacığında çalışır: yeni kapanışta tam hesap, dakikada en çok bir kez son noktanın canlı değerle yenilenmesi.';
    this.boxes.status = new GridBox(st, 'quant/' + this.what + '/status');
    parent.appendChild(cov.el);
    parent.appendChild(st.el);
  }

  /** Draw one monitor (a click on a signal or on a row that has one). */
  async pick(sid) {
    if (!sid || !this.chart) return;
    this.picked = sid;
    this.chart.loading('');
    try {
      const d = await api.get('/api/quant/signal', { id: sid });
      if (this.dead || this.picked !== sid) return;
      this.chart.show(d);
      if (this.afterPick) this.afterPick();
    } catch (e) { errorToast(e); }
  }
}

