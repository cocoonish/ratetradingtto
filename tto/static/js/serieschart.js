// The past of whatever a picked row or cell stands for (as on Realized Vol · Carry, a click draws it): its daily closes
// with the window's mean and ±2σ, and its z-score day by day.  The statistics are the ones the page itself shows next
// to it (seriesstats.js: rule 'macro' for FX Vol İzleme and the end-of-day matrix, 'raw' for İzleme · Alarmlar), so
// that the picture and the table agree to the last digit.  Every day of the z chart is that day's close against the
// ``window`` closes before it (shown once there are 20 of them, or the whole window when it is shorter); the last
// point is the value now - the live one, or else the last close standing in for it as in the tables - the same number
// as the line above the charts.
import { h } from './ui.js';
import { Chart } from './chart.js';
import { num, isoToTr } from './format.js';
import { basis, need, standing, rollingZ, CHART_MIN } from './seriesstats.js';

export const WINDOWS_MACRO = [[63, '3A', 'Son 63 kapanış (~3 ay)'], [126, '6A', 'Son 126 kapanış (~6 ay)'], [250, '1Y', 'Son 250 kapanış (~1 yıl)']];
export const WINDOWS_WATCH = [[20, '1A', 'Son 20 kapanış (~1 ay)'], [60, '3A', 'Son 60 kapanış (~3 ay)'], [250, '1Y', 'Son 250 kapanış (~1 yıl)']];
const BLUE = '4F81BD', GREY = '7F7F7F', PURPLE = '8064A2';
const isNum = (v) => typeof v === 'number' && isFinite(v);
const serialOf = (iso) => Math.round(Date.UTC(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10)) / 86400000) + 25569;

function pref(key, fallback) {
  try { const v = localStorage.getItem(key); return v === null ? fallback : v; } catch (e) { return fallback; }
}

function keep(key, value) {
  try { localStorage.setItem(key, String(value)); } catch (e) { /* not kept */ }
}

/** Decimals and unit of a watched value, by how the watch shows it (tto.watch SHOWS). */
const WATCH_SHOW = { pct: [3, '%'], bp: [1, 'bp'], px: [3, 'fiyat'], fx: [4, ''], raw: [2, ''] };

/** A watched subject's history (POST /api/watch/history) as what :class:`SeriesView` draws. */
export function watchSpec(d, title) {
  const [digits, unit] = WATCH_SHOW[d.show] || WATCH_SHOW.raw;
  return { title: title || d.label, points: d.points, live: d.value, today: d.today, digits, unit,
    note: d.source ? 'kapanışlar: ' + d.source : '',
    why: 'Geçmiş yok: OIS, TLREF ve offshore tarihçe deposundan, diğerleri dashboard\'un her gün kaydettiği kapanıştan gelir (izlemeye alındığı günden beri).' };
}

export class SeriesView {
  /**
   * host: where it is drawn.  opts: {rule ('macro' | 'raw'), windows ([[n, label, title], ...]), window (the first),
   * windowSeg (its own window buttons; false when the page's own set it - :meth:`setWindow`), prefKey, height, hint}
   */
  constructor(host, opts = {}) {
    this.host = host;
    this.opts = opts;
    this.rule = opts.rule === 'raw' ? 'raw' : 'macro';
    this.windows = opts.windows || (this.rule === 'raw' ? WINDOWS_WATCH : WINDOWS_MACRO);
    const known = (v) => this.windows.some((x) => x[0] === v);
    const kept = opts.windowSeg === false ? null : Number(pref(opts.prefKey || 'tto.series.window', ''));
    this.window = known(kept) ? kept : (known(opts.window) ? opts.window : this.windows[this.windows.length - 1][0]);
    this.charts = {};
    this.spec = null;
    this.el = h('div', { class: 'seriesview' });
    this.titleEl = h('div', { class: 'ct svtitle' });
    this.statEl = h('div', { class: 'muted svstat' });
    this.seg = h('div', { class: 'seg svwin' });
    for (const [v, label, title] of this.windows) {
      const b = h('button', { type: 'button', title }, label);
      b.dataset.v = String(v);
      b.addEventListener('click', () => {
        if (opts.prefKey !== false) keep(opts.prefKey || 'tto.series.window', v);
        this.setWindow(v);
      });
      this.seg.appendChild(b);
    }
    const top = h('div', { class: 'svtop' }, this.titleEl, h('span', { class: 'grow' }));
    if (opts.windowSeg !== false) top.appendChild(h('span', { class: 'svwinbox' }, h('span', { class: 'muted' }, 'Pencere'), this.seg));
    this.levelHead = h('div', { class: 'ct' });
    this.zHead = h('div', { class: 'ct' });
    this.levelHost = h('div', { class: 'volchart' });
    this.zHost = h('div', { class: 'volchart' });
    this.plots = h('div', { class: 'volcharts svcharts' }, h('div', null, this.levelHead, this.levelHost), h('div', null, this.zHead, this.zHost));
    this.empty = h('div', { class: 'empty' });
    this.el.appendChild(top);
    this.el.appendChild(this.statEl);
    this.el.appendChild(this.plots);
    this.el.appendChild(this.empty);
    host.appendChild(this.el);
    this.markWindow();
    this.render();
  }

  /**
   * spec: {title, points: [[iso, value], ...], live (the value now; null: the last close), today (iso), from (iso: the
   * first day of the statistics' axis), digits, unit (said after a number), axis (the level axis' title when it is not
   * the unit: a ratio has none to say), note, why (no points: the reason)}
   */
  show(spec) {
    this.spec = spec;
    this.render();
  }

  /** A history on its way: the title, and "loading" in place of the charts. */
  loading(title) {
    this.spec = { title, points: [], why: 'Yükleniyor…' };
    this.render();
  }

  setWindow(w) {
    if (!this.windows.some((x) => x[0] === w)) return;
    this.window = w;
    this.markWindow();
    this.render();
  }

  markWindow() {
    for (const b of this.seg.children) b.classList.toggle('on', b.dataset.v === String(this.window));
  }

  destroy() {
    for (const c of Object.values(this.charts)) if (c) c.destroy();
    this.charts = {};
    this.el.remove();
  }

  render() {
    const s = this.spec;
    const raw = s ? (s.points || []).filter((p) => p && isNum(p[1]) && (!s.today || p[0] < s.today)) : [];
    const has = raw.length > 1;
    this.titleEl.textContent = s ? s.title || '' : '';
    this.plots.classList.toggle('hidden', !has);
    this.empty.classList.toggle('hidden', has);
    if (!has) {
      this.statEl.textContent = '';
      this.empty.textContent = !s ? (this.opts.hint || 'Bir satıra tıklayın: geçmişi burada çizilir.')
        : (s.why || 'Bu serinin geçmişi yok (tarihçe henüz inmemiş olabilir).');
      return;
    }
    const w = this.window;
    const d = isNum(s.digits) ? s.digits : 2;
    const unit = s.unit ? ' ' + s.unit : '';
    const axis = s.axis !== undefined ? s.axis : (s.unit || '');
    const base = basis(raw, this.rule, s.today, s.from);
    const closes = base.map((p) => p[1]);
    const live = isNum(s.live);
    const now = live ? s.live : closes[closes.length - 1];
    const st = standing(closes, now, w, this.rule);

    // ---- the level: the closes (and the value now), the window's mean and ±2σ over the window
    const days = raw.map((p) => p[0]);
    const vals = raw.map((p) => p[1]);
    if (live && s.today && s.today > days[days.length - 1]) { days.push(s.today); vals.push(s.live); }
    const first = base.length > w ? base[base.length - w][0] : (base.length ? base[0][0] : days[0]);
    const band = (k) => days.map((x) => (st && x >= first ? st.mean + k * st.sd : null));
    const dated = (list) => ({ type: 'date', values: list.map(serialOf), format: 'mmm yy' });
    const level = { title: s.title, cats: days.map(isoToTr), x: dated(days), auto: 'fit', decimals: d, y_title: axis, aspect: 0.42,
      series: [{ name: s.title, kind: 'line', color: BLUE, data: vals, marker: false },
        { name: 'ortalama', kind: 'line', color: GREY, data: band(0), marker: false },
        { name: '±2σ', kind: 'line', color: GREY, dash: true, data: band(2), marker: false },
        { name: '−2σ', kind: 'line', color: GREY, dash: true, data: band(-2), marker: false, legend: 0 }] };

    // ---- z day by day (the statistics' own closes), the value now last
    const zDays = base.map((p) => p[0]);
    const z = rollingZ(closes, w, this.rule === 'raw' ? need('raw', w) : CHART_MIN);
    if (live && s.today && (!zDays.length || s.today > zDays[zDays.length - 1])) { zDays.push(s.today); z.push(st ? st.z : null); }
    else if (!live && z.length) z[z.length - 1] = st ? st.z : null;            // the last close stands in for the value now
    const zspec = { title: s.title + ' z', cats: zDays.map(isoToTr), x: dated(zDays), auto: 'fit', decimals: 2, y_title: 'z', aspect: 0.42,
      series: [{ name: 'z', kind: 'line', color: PURPLE, data: z, marker: false },
        { name: '±2', kind: 'line', color: GREY, dash: true, data: zDays.map(() => 2), marker: false },
        { name: '−2', kind: 'line', color: GREY, dash: true, data: zDays.map(() => -2), marker: false, legend: 0 }] };
    this.levelHead.textContent = 'Seviye' + (axis ? ' (' + axis + ')' : '') + ' · ortalama ve ±2σ: son ' + w + ' kapanış';
    this.zHead.textContent = 'z-skoru · her gün, kendinden önceki ' + w + ' kapanışa göre';
    const height = this.opts.height || 230;
    if (this.charts.level) this.charts.level.update(level); else this.charts.level = new Chart(this.levelHost, level, { height });
    if (this.charts.z) this.charts.z.update(zspec); else this.charts.z = new Chart(this.zHost, zspec, { height });

    const f = (v) => num(v, d, false);
    const pct = st ? (this.rule === 'raw' ? 'altında kalan %' : 'yüzdelik %') + num(st.pct * 100, 0, false) : '';
    this.statEl.textContent = (live ? 'Şimdi ' : 'Son kapanış ') + f(now) + unit
      + (st ? ' · z ' + (st.z > 0 ? '+' : '') + num(st.z, 2, false) + ' · ' + pct + ' · ortalama ' + f(st.mean) + ' · σ ' + f(st.sd)
        + ' · aralık ' + f(st.min) + ' – ' + f(st.max) + ' · ' + st.n + ' kapanış' : ' · z için kapanış yetmiyor')
      + ' · ' + isoToTr(raw[0][0]) + ' – ' + isoToTr(raw[raw.length - 1][0]) + (s.note ? ' · ' + s.note : '');
  }
}
