// Dependency-free SVG charts drawn from the workbook's own chart definitions: lines (straight or smoothed, with
// markers), areas, clustered and stacked bars, on a category or a date axis, with a crosshair tooltip.
//
// Values arrive the way Excel plots them: a number is a point, `null` leaves a gap in the line and "c" is a point
// the line passes over (#N/A).  A series keeps the colour identity it has in the workbook - red stays red - but
// is drawn in the theme's own tone of that colour (--c-blue ... --c-orange), which are checked for colour-blind
// separation in both themes.  Text always uses ink tokens, never a series colour.
import { h, clear } from './ui.js';
import { num, settings } from './format.js';

const NS = 'http://www.w3.org/2000/svg';
// Excel's accent order; series without a colour of their own take these in turn
const ORDER = ['blue', 'red', 'green', 'purple', 'cyan', 'orange'];
const MONTHS = {
  tr: [['Oca', 'Şub', 'Mar', 'Nis', 'May', 'Haz', 'Tem', 'Ağu', 'Eyl', 'Eki', 'Kas', 'Ara'],
    ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık']],
  en: [['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'],
    ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']],
};
const MIN_HEIGHT = 230, MAX_HEIGHT = 400, DEFAULT_HEIGHT = 250;

function svg(tag, attrs, parent) {
  const el = document.createElementNS(NS, tag);
  if (attrs) for (const k of Object.keys(attrs)) el.setAttribute(k, attrs[k]);
  if (parent) parent.appendChild(el);
  return el;
}

const isNum = (v) => typeof v === 'number' && isFinite(v);
const f1 = (v) => (Math.round(v * 10) / 10).toString();

// ------------------------------------------------------------------------------------------------ colours

/** Colour family of an Excel colour ("C0504D" -> "red"); "ink" for greys, null when there is no colour. */
export function colorFamily(hex) {
  if (typeof hex !== 'string' || !/^[0-9a-f]{6}$/i.test(hex)) return null;
  const r = parseInt(hex.slice(0, 2), 16) / 255, g = parseInt(hex.slice(2, 4), 16) / 255, b = parseInt(hex.slice(4, 6), 16) / 255;
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
  const l = (mx + mn) / 2;
  const s = d === 0 ? 0 : d / (1 - Math.abs(2 * l - 1));
  if (s < 0.15 || d < 0.06) return 'ink';
  let hue = mx === r ? ((g - b) / d) % 6 : mx === g ? (b - r) / d + 2 : (r - g) / d + 4;
  hue = (hue * 60 + 360) % 360;
  if (hue >= 345 || hue < 20) return 'red';
  if (hue < 70) return 'orange';
  if (hue < 170) return 'green';
  if (hue < 200) return 'cyan';
  if (hue < 260) return 'blue';
  return 'purple';
}

/**
 * One theme colour per series.  A series with a workbook colour gets the tone of its family; the same workbook
 * colour always gets the same tone, a second colour of an already taken family (or a series without a colour)
 * takes the next free tone in Excel's accent order.
 */
export function seriesColors(series) {
  const taken = new Map();
  return series.map((s, k) => {
    const src = typeof s.color === 'string' ? s.color.toUpperCase() : '';
    let tok = colorFamily(src);
    if (tok === 'ink') return 'var(--c-ink)';
    if (!tok || (taken.has(tok) && taken.get(tok) !== src)) tok = ORDER.find((t) => !taken.has(t)) || ORDER[k % ORDER.length];
    if (!taken.has(tok)) taken.set(tok, src || 'auto' + k);
    return 'var(--c-' + tok + ')';
  });
}

// ------------------------------------------------------------------------------------------------ scales

function niceStep(raw) {
  if (!(raw > 0) || !isFinite(raw)) return 1;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  return (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
}

function stepDigits(step) {
  if (!isFinite(step) || step <= 0) return 2;
  return Math.max(0, Math.min(6, Math.ceil(-Math.log10(step) - 1e-9)));
}

/**
 * Value axis.  Limits fixed in the workbook's chart win; the rest follows Excel's automatic rule: an all-positive
 * axis starts at zero unless the data sit in the top sixth of their own maximum (then half the data span is left
 * below them), and 5 % of the span is left free above.  `auto: "fit"` (charts that are not from the workbook)
 * simply fits the data.  Major ticks are anchored at a fixed minimum, as in Excel.
 */
export function valueScale(d, lo, hi, plotHeight) {
  const fixLo = isNum(d.ymin), fixHi = isNum(d.ymax);
  if (!isFinite(lo) || !isFinite(hi)) { lo = 0; hi = 1; }
  let a = lo, b = hi;
  if (a === b) { const pad = Math.abs(a) * 0.05 || 1; a -= pad; b += pad; }
  if (d.auto !== 'fit') {
    const span = b - a;
    if (!fixLo) a = a >= 0 ? (span > b / 6 ? 0 : a - span / 2) : a - span * 0.05;
    if (!fixHi) b = b <= 0 ? (span > -lo / 6 ? 0 : b + span / 2) : b + span * 0.05;
  }
  if (fixLo) a = d.ymin;
  if (fixHi) b = d.ymax;
  if (!(b > a)) b = a + (Math.abs(a) * 0.1 || 1);
  const target = Math.max(2, Math.min(8, Math.round(plotHeight / 44)));
  let step = niceStep((b - a) / target);
  if (isNum(d.major_unit) && d.major_unit > 0 && (b - a) / d.major_unit <= 30) step = d.major_unit;
  const t0 = fixLo ? a : Math.floor(a / step + 1e-9) * step;
  let t1;
  if (fixHi) t1 = b;
  else if (fixLo) t1 = a + Math.max(1, Math.ceil((b - a) / step - 1e-9)) * step;
  else t1 = Math.ceil(b / step - 1e-9) * step;
  const ticks = [];
  for (let k = 0; t0 + k * step <= t1 + step * 1e-6 && k < 200; k++) ticks.push(t0 + k * step);
  return { lo: t0, hi: t1, step, ticks };
}

// ------------------------------------------------------------------------------------------------ dates / text

const serialOf = (y, m) => Date.UTC(y, m, 1) / 86400000 + 25569;

/** Excel serial -> text for the handful of date formats an axis uses ("mmm yy", "mm.yyyy", "d mmm" ...). */
export function formatAxisDate(serial, format) {
  const d = new Date(Math.round((serial - 25569) * 86400000));
  const names = MONTHS[settings.lang === 'en' ? 'en' : 'tr'];
  const f = format && /[my]/i.test(format) && !/general/i.test(format) ? format : 'mmm yy';
  return f.replace(/yyyy|yy|mmmm|mmm|mm|m|dd|d/gi, (t) => {
    switch (t.toLowerCase()) {
      case 'yyyy': return String(d.getUTCFullYear());
      case 'yy': return String(d.getUTCFullYear() % 100).padStart(2, '0');
      case 'mmmm': return names[1][d.getUTCMonth()];
      case 'mmm': return names[0][d.getUTCMonth()];
      case 'mm': return String(d.getUTCMonth() + 1).padStart(2, '0');
      case 'm': return String(d.getUTCMonth() + 1);
      case 'dd': return String(d.getUTCDate()).padStart(2, '0');
      default: return String(d.getUTCDate());
    }
  });
}

/** First days of the months to label between two serials, as few as needed for the labels not to touch. */
function monthTicks(v0, v1, pxPerDay, labelWidth) {
  const d0 = new Date(Math.round((v0 - 25569) * 86400000)), d1 = new Date(Math.round((v1 - 25569) * 86400000));
  const m0 = d0.getUTCFullYear() * 12 + d0.getUTCMonth(), m1 = d1.getUTCFullYear() * 12 + d1.getUTCMonth();
  const every = [1, 2, 3, 6, 12, 24, 60, 120].find((s) => s * 30.4375 * pxPerDay >= labelWidth + 14) || 120;
  const out = [];
  for (let m = m0; m <= m1; m++) {
    if (m % every) continue;
    const serial = serialOf(Math.floor(m / 12), m % 12);
    if (serial >= v0 - 0.5 && serial <= v1 + 0.5) out.push(serial);
  }
  return out;
}

let measure = null;
function textWidth(text) {
  const s = String(text);
  try {
    if (!measure) {
      measure = document.createElement('canvas').getContext('2d');
      measure.font = '10.5px ' + (getComputedStyle(document.body).fontFamily || 'sans-serif');
    }
    return measure.measureText(s).width;
  } catch (e) {
    return s.length * 6.1;
  }
}

// ------------------------------------------------------------------------------------------------ geometry

/** Runs of plotted points: `null` ends a run (gap), "c" is passed over (the line connects its neighbours). */
function runs(data, X, Y) {
  const out = [];
  let cur = [];
  for (let i = 0; i < data.length; i++) {
    const v = data[i];
    if (isNum(v)) cur.push([X(i), Y(v), i]);
    else if (v !== 'c' && cur.length) { out.push(cur); cur = []; }
  }
  if (cur.length) out.push(cur);
  return out;
}

const straight = (p) => 'M' + p.map((q) => f1(q[0]) + ',' + f1(q[1])).join(' L');

/** Smoothed line through the points: a monotone cubic, so it never swings past the values it joins. */
function smooth(p) {
  const n = p.length;
  if (n < 3) return straight(p);
  const dx = [], m = [], t = new Array(n);
  for (let i = 0; i < n - 1; i++) {
    dx.push(p[i + 1][0] - p[i][0]);
    if (!(dx[i] > 0)) return straight(p);
    m.push((p[i + 1][1] - p[i][1]) / dx[i]);
  }
  t[0] = m[0];
  t[n - 1] = m[n - 2];
  for (let i = 1; i < n - 1; i++) {
    if (m[i - 1] * m[i] <= 0) { t[i] = 0; continue; }
    const w1 = 2 * dx[i] + dx[i - 1], w2 = dx[i] + 2 * dx[i - 1];
    t[i] = (w1 + w2) / (w1 / m[i - 1] + w2 / m[i]);
  }
  let s = 'M' + f1(p[0][0]) + ',' + f1(p[0][1]);
  for (let i = 0; i < n - 1; i++) {
    const k = dx[i] / 3;
    s += ' C' + f1(p[i][0] + k) + ',' + f1(p[i][1] + t[i] * k) + ' ' + f1(p[i + 1][0] - k) + ',' + f1(p[i + 1][1] - t[i + 1] * k)
      + ' ' + f1(p[i + 1][0]) + ',' + f1(p[i + 1][1]);
  }
  return s;
}

/** Bar from the baseline `y0` to the value end `y1`: square at the baseline, rounded at the value end if asked. */
function barPath(x, w, y0, y1, round) {
  const r = round ? Math.min(4, w / 2, Math.abs(y1 - y0)) : 0;
  const s = y1 < y0 ? 1 : -1;                    // +1: the bar grows upwards on the screen
  return 'M' + f1(x) + ',' + f1(y0) + ' V' + f1(y1 + s * r) + ' Q' + f1(x) + ',' + f1(y1) + ' ' + f1(x + r) + ',' + f1(y1)
    + ' H' + f1(x + w - r) + ' Q' + f1(x + w) + ',' + f1(y1) + ' ' + f1(x + w) + ',' + f1(y1 + s * r) + ' V' + f1(y0) + ' Z';
}

function swatch(s, color) {
  const el = svg('svg', { class: 'sw', width: 22, height: 10, viewBox: '0 0 22 10', 'aria-hidden': 'true' });
  if (s.kind === 'line' || s.kind === 'scatter') {
    if (!s.noline) {
      const l = svg('line', { x1: 1, x2: 21, y1: 5, y2: 5, 'stroke-width': 2, 'stroke-linecap': s.dash ? 'butt' : 'round' }, el);
      if (s.dash) l.setAttribute('stroke-dasharray', '5 3');
      l.style.stroke = color;
    }
    if (s.marker || s.noline) svg('circle', { cx: 11, cy: 5, r: 2.8 }, el).style.fill = color;
  } else {
    const r = svg('rect', { x: 5, y: 0.5, width: 12, height: 9, rx: 2 }, el);
    r.style.fill = color;
    if (s.kind === 'area') r.setAttribute('fill-opacity', String(Math.min(0.6, areaAlpha(s) * 2)));
  }
  return el;
}

const areaAlpha = (s) => (isNum(s.alpha) ? Math.max(0.08, Math.min(0.6, s.alpha)) : 0.28);

let clipSeq = 0;

// ------------------------------------------------------------------------------------------------ table view

/** Grid-compatible table of the chart's numbers (the chart's "table view", copyable to Excel). */
export function chartTable(data) {
  const mult = data.unit === 'pct' ? 100 : 1;
  const digits = data.unit === 'pct' ? 3 : 4;
  if (data.scatter) {
    // an XY chart: label, x and y of every series side by side (series need not share their x values)
    const date = data.xaxis && data.xaxis.type === 'date';
    const xText = (v) => (date ? formatAxisDate(v, 'dd.mm.yyyy') : num(v, 4, false));
    const head = [];
    for (const s of data.series) {
      if (s.labels) head.push({ t: 'Etiket', k: 's', b: 1, f: 'hd' });
      head.push({ t: (s.name || '') + ' · x', k: 's', b: 1, f: 'hd' }, { t: s.name || '', k: 's', b: 1, f: 'hd' });
    }
    const rows = [head];
    const n = Math.max(...data.series.map((s) => s.x.length));
    for (let i = 0; i < n; i++) {
      const row = [];
      for (const s of data.series) {
        const x = s.x[i], y = s.data[i];
        if (s.labels) row.push({ t: s.labels[i] || '', k: 's' });
        row.push(isNum(x) ? { t: xText(x), v: x, k: date ? 'd' : 'n' } : { t: '', k: '' });
        row.push(isNum(y) ? { t: num(y * mult, digits, false) + (mult === 100 ? '%' : ''), v: y, k: 'n' } : { t: '', k: '' });
      }
      rows.push(row);
    }
    return { sheet: '', rows };
  }
  const head = [{ t: '', k: 's', b: 1, f: 'hd' }].concat(data.series.map((s) => ({ t: s.name || '', k: 's', b: 1, f: 'hd' })));
  const rows = [head];
  for (let i = 0; i < data.cats.length; i++) {
    const row = [{ t: data.cats[i], k: 's' }];
    for (const s of data.series) {
      const v = s.data[i];
      row.push(isNum(v) ? { t: num(v * mult, digits, false) + (mult === 100 ? '%' : ''), v, k: 'n' } : { t: '', k: '' });
    }
    rows.push(row);
  }
  return { sheet: '', rows };
}

// ------------------------------------------------------------------------------------------------ chart

export class Chart {
  constructor(host, data, opts = {}) {
    this.host = host;
    this.opts = opts;
    this.data = data;
    this.key = '';
    this.tip = null;
    this.hover = null;
    this.reshow = null;
    this.width = 0;
    this.wrap = h('div', { class: 'chart-wrap' });
    this.legend = h('div', { class: 'chart-legend' });
    this.plot = h('div');
    this.wrap.appendChild(this.legend);
    this.wrap.appendChild(this.plot);
    host.appendChild(this.wrap);
    if (window.ResizeObserver) {
      this.ro = new ResizeObserver(() => {
        const w = Math.floor(this.plot.clientWidth);
        if (w && Math.abs(w - this.width) > 4) this.render();
      });
      this.ro.observe(this.plot);
    }
    this.render();
  }

  update(data) {
    const key = JSON.stringify(data) + '|' + settings.lang;
    this.data = data;
    if (key === this.key && this.plot.firstChild) return;       // nothing moved: keep the picture (and an open tooltip)
    this.render();
  }

  destroy() {
    if (this.ro) this.ro.disconnect();
    this.hideTip();
    this.wrap.remove();
  }

  hideTip() {
    if (this.tip) { this.tip.remove(); this.tip = null; }
  }

  fmt(v, digits) {
    if (!isNum(v)) return '–';
    if (this.data.unit === 'pct') return num(v * 100, digits, false) + '%';
    return num(v, digits, Math.abs(v) >= 10000);
  }

  render() {
    const d = this.data;
    this.key = JSON.stringify(d) + '|' + settings.lang;
    clear(this.legend);
    clear(this.plot);
    this.hideTip();
    this.reshow = null;
    if (d && d.scatter) { this.renderScatter(); return; }
    const series = d && d.series ? d.series : [];
    const n = d && d.cats ? d.cats.length : 0;
    if (!n || !series.some((s) => s.data.some(isNum))) {
      this.plot.appendChild(h('div', { class: 'chart-empty' }, 'Veri yok'));
      return;
    }
    const colors = seriesColors(series);
    const label = (s, k) => s.name || ('Seri ' + (k + 1));

    // ---- legend: one key per series the workbook shows in its legend; a lone series is named by the title
    if (series.length > 1) {
      series.forEach((s, k) => {
        if (s.legend === 0) return;
        this.legend.appendChild(h('span', { class: 'key' }, swatch(s, colors[k]), label(s, k)));
      });
    }

    const W = Math.max(260, Math.floor(this.plot.clientWidth) || 520);
    const H = this.opts.height
      || (isNum(d.aspect) ? Math.round(Math.max(MIN_HEIGHT, Math.min(MAX_HEIGHT, W * d.aspect))) : DEFAULT_HEIGHT);
    this.width = W;

    // ---- value range
    const bars = series.map((s, k) => ({ s, k })).filter((x) => x.s.kind === 'bar');
    const stacked = bars.length > 1 && bars.every((x) => x.s.stacked);
    let lo = Infinity, hi = -Infinity;
    for (const s of series) {
      if (s.kind === 'bar' && stacked) continue;
      for (const v of s.data) if (isNum(v)) { if (v < lo) lo = v; if (v > hi) hi = v; }
    }
    if (stacked) {
      for (let i = 0; i < n; i++) {
        let pos = 0, neg = 0;
        for (const b of bars) {
          const v = b.s.data[i];
          if (isNum(v)) { if (v >= 0) pos += v; else neg += v; }
        }
        if (pos > hi) hi = pos;
        if (neg < lo) lo = neg;
      }
    }
    const baseZero = bars.length > 0 || series.some((s) => s.kind === 'area');
    if (baseZero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }

    const top = 8, right = 12;
    const bottom = 24 + (d.x_title ? 15 : 0);
    const ph = H - top - bottom;
    const scale = valueScale(d, lo, hi, ph);
    const mult = d.unit === 'pct' ? 100 : 1;
    let digits = stepDigits(scale.step * mult);
    if (isNum(d.decimals)) digits = Math.max(digits, Math.min(6, d.decimals));
    const tickText = scale.ticks.map((t) => this.fmt(t, digits));
    const titleRoom = d.y_title ? 17 : 0;
    const left = Math.ceil(Math.max(30, Math.max(...tickText.map(textWidth)) + 12) + titleRoom);
    const pw = W - left - right;
    const Y = (v) => top + ph - ((v - scale.lo) / (scale.hi - scale.lo)) * ph;
    const base = Math.max(scale.lo, Math.min(0, scale.hi));

    // ---- x positions: bands of equal width, or in proportion to the dates on a date axis
    const xv = d.x && d.x.type === 'date' && Array.isArray(d.x.values) && d.x.values.length === n && n > 1 ? d.x.values : null;
    const band = pw / n;
    const inset = 3;
    const X = xv ? (i) => left + inset + ((xv[i] - xv[0]) / (xv[n - 1] - xv[0])) * (pw - 2 * inset)
      : (i) => left + band * (i + 0.5);

    const root = svg('svg', { class: 'chart', viewBox: '0 0 ' + W + ' ' + H, width: W, height: H, role: 'img' });
    root.setAttribute('aria-label', d.title || 'grafik');

    // ---- value axis: grid lines and labels (labels thinned when the lines are closer than a line of text)
    const gGrid = svg('g', { class: 'grid' }, root);
    const spacing = scale.ticks.length > 1 ? ph / (scale.ticks.length - 1) : ph;
    const labelEvery = spacing < 13 ? Math.ceil(13 / spacing) : 1;
    scale.ticks.forEach((t, k) => {
      const y = Math.round(Y(t)) + 0.5;
      svg('line', { x1: left, x2: W - right, y1: y, y2: y }, gGrid);
      if (k % labelEvery) return;
      svg('text', { x: left - 7, y: y + 3.5, 'text-anchor': 'end' }, root).textContent = tickText[k];
    });
    const gAxis = svg('g', { class: 'axis' }, root);
    const yBase = Math.round(Y(base)) + 0.5;
    svg('line', { x1: left, x2: W - right, y1: yBase, y2: yBase }, gAxis);
    if (d.y_title) {
      const ty = top + ph / 2;
      const t = svg('text', { x: 11, y: ty, 'text-anchor': 'middle', class: 'ttl', transform: 'rotate(-90 11 ' + f1(ty) + ')' }, root);
      t.textContent = d.y_title;
    }
    if (d.x_title) svg('text', { x: left + pw / 2, y: H - 5, 'text-anchor': 'middle', class: 'ttl' }, root).textContent = d.x_title;

    // ---- category axis labels
    const yLab = top + ph + 15;
    let dateTicks = null;
    if (xv) {
      const pxPerDay = (pw - 2 * inset) / (xv[n - 1] - xv[0]);
      const sample = formatAxisDate(serialOf(2028, 8), d.x.format);
      const ticks = monthTicks(xv[0], xv[n - 1], pxPerDay, textWidth(sample));
      if (ticks.length >= 2) dateTicks = ticks;
    }
    if (dateTicks) {
      for (const sv of dateTicks) {
        const x = left + inset + ((sv - xv[0]) / (xv[n - 1] - xv[0])) * (pw - 2 * inset);
        const xr = Math.round(x) + 0.5;
        svg('line', { x1: xr, x2: xr, y1: top + ph, y2: top + ph + 4 }, gAxis);
        const text = formatAxisDate(sv, d.x.format);
        const half = textWidth(text) / 2;
        if (x - half < 2 || x + half > W - 2) continue;
        svg('text', { x: f1(x), y: yLab + 2, 'text-anchor': 'middle' }, root).textContent = text;
      }
    } else {
      const widths = d.cats.map(textWidth);
      const fits = (k) => {
        for (let i = 0; i + k < n; i += k) if ((widths[i] + widths[i + k]) / 2 + 8 > X(i + k) - X(i)) return false;
        return true;
      };
      const unit = d.label_skip > 1 ? Math.round(d.label_skip) : 1;      // the workbook's own "every k-th label"
      let every = unit;
      while (every < n && !fits(every)) every += unit;
      for (let i = 0; i < n; i += every) {
        if (!d.cats[i]) continue;
        svg('text', { x: f1(X(i)), y: yLab, 'text-anchor': 'middle' }, root).textContent = d.cats[i];
      }
    }

    // everything drawn from data is clipped to the plot area (an axis limit fixed in the workbook may cut a series)
    const clipId = 'tto-clip-' + (++clipSeq);
    const cp = svg('clipPath', { id: clipId }, svg('defs', null, root));
    svg('rect', { x: left, y: top, width: pw, height: ph }, cp);
    const marksRoot = svg('g', { 'clip-path': 'url(#' + clipId + ')' }, root);
    const spread = xv ? (pw - 2 * inset) / (n - 1) : band;
    const dot = Math.max(1.9, Math.min(3.3, spread * 0.22));

    // ---- areas (washes from the zero line; an outline only where the workbook draws one)
    series.forEach((s, k) => {
      if (s.kind !== 'area') return;
      for (const p of runs(s.data, X, Y)) {
        if (p.length < 2) continue;
        const y0 = f1(Y(base));
        const path = 'M' + f1(p[0][0]) + ',' + y0 + ' L' + p.map((q) => f1(q[0]) + ',' + f1(q[1])).join(' L')
          + ' L' + f1(p[p.length - 1][0]) + ',' + y0 + ' Z';
        svg('path', { d: path, 'fill-opacity': areaAlpha(s), stroke: 'none' }, marksRoot).style.fill = colors[k];
        if (!s.noline) {
          svg('path', { d: straight(p), fill: 'none', 'stroke-width': 2, 'stroke-linejoin': 'round' }, marksRoot).style.stroke = colors[k];
        }
      }
    });

    // ---- bars: clustered side by side, or stacked (positives upwards, negatives downwards from zero)
    if (bars.length) {
      const groups = stacked ? 1 : bars.length;
      const gapWidth = (isNum(d.gap_width) ? Math.max(0, Math.min(500, d.gap_width)) : 150) / 100;
      const slot = Math.min(30, band / (groups + gapWidth));
      const between = groups > 1 ? (slot >= 10 ? 2 : slot >= 5 ? 1 : 0.5) : 0;
      const bw = Math.max(1, slot - between);
      const x0 = -(groups * slot - between) / 2;
      for (let i = 0; i < n; i++) {
        let lastPos = -1, lastNeg = -1;
        if (stacked) {
          bars.forEach((b, bi) => {
            const v = b.s.data[i];
            if (isNum(v) && v > 0) lastPos = bi;
            if (isNum(v) && v < 0) lastNeg = bi;
          });
        }
        let pos = 0, neg = 0;
        bars.forEach((b, bi) => {
          const v = b.s.data[i];
          if (!isNum(v) || v === 0) return;
          let y0, y1, round = true;
          if (stacked) {
            const from = v > 0 ? pos : neg;
            if (v > 0) pos += v; else neg += v;
            y0 = Y(from);
            y1 = Y(from + v);
            round = bi === (v > 0 ? lastPos : lastNeg);            // only the outer end of the stack is rounded
            // a thin strip of surface between the segments of one stack
            if (from !== 0 && Math.abs(y1 - y0) > 3) y0 += (v > 0 ? -1.5 : 1.5);
          } else {
            y0 = Y(base);
            y1 = Y(v);
          }
          if (Math.abs(y1 - y0) < 1) y1 = y0 + (v > 0 ? -1 : 1);
          const x = X(i) + x0 + (stacked ? 0 : bi * slot);
          svg('path', { d: barPath(x, bw, y0, y1, round) }, marksRoot).style.fill = colors[b.k];
        });
      }
    }

    // ---- up / down bars: a box between two line series at every category (e.g. the RET bid-ask band)
    const ud = d.updown;
    if (ud && series[ud.first] && series[ud.last]) {
      const a = series[ud.first].data, b = series[ud.last].data;
      const gapWidth = (isNum(ud.gap_width) ? Math.max(0, Math.min(500, ud.gap_width)) : 150) / 100;
      const bw = Math.max(2, Math.min(44, spread / (1 + gapWidth)));
      for (let i = 0; i < n; i++) {
        if (!isNum(a[i]) || !isNum(b[i])) continue;
        const st = (b[i] >= a[i] ? ud.up : ud.down) || {};
        const paint = st.color ? seriesColors([{ color: st.color }])[0] : 'var(--c-ink)';
        const y0 = Y(Math.max(a[i], b[i])), y1 = Y(Math.min(a[i], b[i]));
        const box = svg('rect', { x: f1(X(i) - bw / 2), y: f1(y0), width: f1(bw), height: f1(Math.max(1, y1 - y0)), rx: 1.5 }, marksRoot);
        box.style.fill = st.nofill ? 'none' : paint;
        box.setAttribute('fill-opacity', String(isNum(st.alpha) ? st.alpha : (st.color ? 1 : 0.25)));
        if (!st.noline) {
          box.style.stroke = st.line ? seriesColors([{ color: st.line }])[0] : paint;
          box.setAttribute('stroke-opacity', String(isNum(st.line_alpha) ? st.line_alpha : 1));
          box.setAttribute('stroke-width', '1');
        }
      }
    }

    // ---- lines (each series in the workbook's order: its line, then its markers)
    series.forEach((s, k) => {
      if (s.kind !== 'line') return;
      for (const p of runs(s.data, X, Y)) {
        if (p.length > 1 && !s.noline) {
          const l = svg('path', { d: s.smooth ? smooth(p) : straight(p), fill: 'none', 'stroke-width': 2, 'stroke-linejoin': 'round',
            'stroke-linecap': s.dash ? 'butt' : 'round' }, marksRoot);
          if (s.dash) l.setAttribute('stroke-dasharray', '6 4');
          l.style.stroke = colors[k];
        }
        if (s.marker || s.noline || p.length === 1) {
          for (const q of p) svg('circle', { cx: f1(q[0]), cy: f1(q[1]), r: f1(dot), class: 'mk' }, marksRoot).style.fill = colors[k];
        }
      }
    });

    // ---- hover layer: nearest category, a crosshair (or the band of a bar chart), the values in a tooltip
    const barChart = bars.length > 0;
    const cross = barChart
      ? svg('rect', { class: 'band', y: top, height: ph, x: 0, width: Math.max(2, band), visibility: 'hidden' }, root)
      : svg('line', { class: 'cross', y1: top, y2: top + ph, x1: 0, x2: 0, visibility: 'hidden' }, root);
    const rings = svg('g', null, root);
    const hit = svg('rect', { x: left, y: top, width: pw, height: ph, fill: 'transparent' }, root);
    const tipDigits = Math.min(6, Math.max(digits + 2, d.unit === 'pct' ? 3 : 2));
    const indexAt = (mx) => {
      if (!xv) return Math.max(0, Math.min(n - 1, Math.floor((mx - left) / band)));
      let best = 0, bd = Infinity;
      for (let i = 0; i < n; i++) {
        const dist = Math.abs(X(i) - mx);
        if (dist < bd) { bd = dist; best = i; }
      }
      return best;
    };
    const show = (pt) => {
      const box = root.getBoundingClientRect();
      if (!box.width) return;
      const i = indexAt((pt.clientX - box.left) * (W / box.width));
      if (barChart) cross.setAttribute('x', f1(X(i) - band / 2));
      else { cross.setAttribute('x1', f1(X(i))); cross.setAttribute('x2', f1(X(i))); }
      cross.setAttribute('visibility', 'visible');
      clear(rings);
      series.forEach((s, k) => {
        const v = s.data[i];
        if (!isNum(v) || s.kind === 'bar' || v < scale.lo || v > scale.hi) return;
        svg('circle', { cx: f1(X(i)), cy: f1(Y(v)), r: 4.5, class: 'ring' }, rings).style.fill = colors[k];
      });
      if (!this.tip) { this.tip = h('div', { class: 'chart-tip' }); document.body.appendChild(this.tip); }
      clear(this.tip);
      this.tip.appendChild(h('div', { class: 't' }, String(d.cats[i])));
      series.forEach((s, k) => {
        this.tip.appendChild(h('div', { class: 'r' }, h('span', null, swatch(s, colors[k]), label(s, k)),
          h('b', null, this.fmt(s.data[i], tipDigits))));
      });
      const tr = this.tip.getBoundingClientRect();
      let tx = pt.clientX + 14, ty = pt.clientY + 14;
      if (tx + tr.width > window.innerWidth - 8) tx = pt.clientX - tr.width - 14;
      if (ty + tr.height > window.innerHeight - 8) ty = pt.clientY - tr.height - 14;
      this.tip.style.left = Math.max(4, tx) + 'px';
      this.tip.style.top = Math.max(4, ty) + 'px';
    };
    hit.addEventListener('pointermove', (evt) => {
      this.hover = { clientX: evt.clientX, clientY: evt.clientY };
      show(this.hover);
    });
    hit.addEventListener('pointerleave', () => {
      this.hover = null;
      cross.setAttribute('visibility', 'hidden');
      clear(rings);
      this.hideTip();
    });
    this.plot.appendChild(root);
    // a refresh that arrives while the pointer rests on the chart keeps the tooltip, with the new values
    if (this.hover) show(this.hover);
  }

  /**
   * XY (scatter) chart: every series brings its own x values, both axes are value axes (x may show dates).
   * Series are drawn in data order as lines, markers or both; points may carry a label read from the sheet.
   */
  renderScatter() {
    const d = this.data;
    const series = d.series || [];
    const drawable = (s) => s.x.some((x, i) => isNum(x) && isNum(s.data[i]));
    if (!series.some(drawable)) {
      this.plot.appendChild(h('div', { class: 'chart-empty' }, 'Veri yok'));
      return;
    }
    const colors = seriesColors(series);
    const label = (s, k) => s.name || ('Seri ' + (k + 1));
    if (series.length > 1) {
      series.forEach((s, k) => {
        if (s.legend === 0 || !drawable(s)) return;
        this.legend.appendChild(h('span', { class: 'key' }, swatch(s, colors[k]), label(s, k)));
      });
    }
    const W = Math.max(260, Math.floor(this.plot.clientWidth) || 520);
    const H = this.opts.height
      || (isNum(d.aspect) ? Math.round(Math.max(MIN_HEIGHT, Math.min(MAX_HEIGHT, W * d.aspect))) : DEFAULT_HEIGHT);
    this.width = W;
    const xa = d.xaxis || {};
    const dates = xa.type === 'date';

    let xlo = Infinity, xhi = -Infinity, ylo = Infinity, yhi = -Infinity;
    for (const s of series) {
      s.x.forEach((x, i) => {
        const y = s.data[i];
        if (!isNum(x) || !isNum(y)) return;
        if (x < xlo) xlo = x;
        if (x > xhi) xhi = x;
        if (y < ylo) ylo = y;
        if (y > yhi) yhi = y;
      });
    }
    const top = 10, right = 14;
    const bottom = 24 + (d.x_title ? 15 : 0);
    const ph = H - top - bottom;
    const ys = valueScale(d, ylo, yhi, ph);
    const mult = d.unit === 'pct' ? 100 : 1;
    let digits = stepDigits(ys.step * mult);
    if (isNum(d.decimals)) digits = Math.max(digits, Math.min(6, d.decimals));
    const yText = ys.ticks.map((t) => this.fmt(t, digits));
    const left = Math.ceil(Math.max(30, Math.max(...yText.map(textWidth)) + 12) + (d.y_title ? 17 : 0));
    const pw = W - left - right;
    // x axis: dates keep their own range (a little air at both ends), numbers follow the value-axis rules
    let xs;
    if (dates) {
      const pad = Math.max(0.5, (xhi - xlo) * 0.02);
      xs = { lo: xlo - pad, hi: xhi + pad, step: 0, ticks: [] };
    } else {
      xs = valueScale({ ymin: xa.min, ymax: xa.max, major_unit: xa.major_unit, auto: d.auto }, xlo, xhi, pw * 44 / 92);
    }
    const X = (v) => left + ((v - xs.lo) / (xs.hi - xs.lo)) * pw;
    const Y = (v) => top + ph - ((v - ys.lo) / (ys.hi - ys.lo)) * ph;
    const xDigits = dates ? 0 : stepDigits(xs.step);
    const xText = (v) => (dates ? formatAxisDate(v, 'dd.mm.yyyy') : num(v, Math.min(4, xDigits + 2), false));

    const root = svg('svg', { class: 'chart', viewBox: '0 0 ' + W + ' ' + H, width: W, height: H, role: 'img' });
    root.setAttribute('aria-label', d.title || 'grafik');
    const gGrid = svg('g', { class: 'grid' }, root);
    ys.ticks.forEach((t, k) => {
      const y = Math.round(Y(t)) + 0.5;
      svg('line', { x1: left, x2: W - right, y1: y, y2: y }, gGrid);
      svg('text', { x: left - 7, y: y + 3.5, 'text-anchor': 'end' }, root).textContent = yText[k];
    });
    const gAxis = svg('g', { class: 'axis' }, root);
    const yBase = Math.round(Y(Math.max(ys.lo, Math.min(0, ys.hi)))) + 0.5;
    svg('line', { x1: left, x2: W - right, y1: yBase, y2: yBase }, gAxis);
    if (ys.lo < 0 && ys.hi > 0) svg('line', { x1: left, x2: W - right, y1: top + ph + 0.5, y2: top + ph + 0.5 }, gGrid);
    if (d.y_title) {
      const ty = top + ph / 2;
      svg('text', { x: 11, y: ty, 'text-anchor': 'middle', class: 'ttl', transform: 'rotate(-90 11 ' + f1(ty) + ')' }, root).textContent = d.y_title;
    }
    if (d.x_title) svg('text', { x: left + pw / 2, y: H - 5, 'text-anchor': 'middle', class: 'ttl' }, root).textContent = d.x_title;

    // ---- x ticks: months (or days) on a date axis, round numbers otherwise
    const yLab = top + ph + 15;
    let ticks = [];
    if (dates) {
      const span = xs.hi - xs.lo;
      const sample = textWidth(formatAxisDate(serialOf(2028, 8), xa.format || 'dd.mm.yy'));
      if (span > 70) ticks = monthTicks(xs.lo, xs.hi, pw / span, sample);
      if (ticks.length < 2) {
        const stepDays = [1, 2, 7, 14, 28].find((k) => k * pw / Math.max(1, span) >= sample + 14) || 28;
        ticks = [];
        for (let v = Math.ceil(xs.lo); v <= xs.hi; v += stepDays) ticks.push(v);
      }
    } else {
      ticks = xs.ticks;
    }
    let lastRight = -Infinity;
    for (const v of ticks) {
      const x = X(v);
      if (x < left - 0.5 || x > W - right + 0.5) continue;
      const xr = Math.round(x) + 0.5;
      svg('line', { x1: xr, x2: xr, y1: top + ph, y2: top + ph + 4 }, gAxis);
      const text = dates ? formatAxisDate(v, xa.format || 'dd.mm.yy') : num(v, xDigits, false);
      const half = textWidth(text) / 2;
      if (x - half < lastRight + 8 || x + half > W - 1) continue;
      svg('text', { x: f1(x), y: yLab + 2, 'text-anchor': 'middle' }, root).textContent = text;
      lastRight = x + half;
    }

    const clipId = 'tto-clip-' + (++clipSeq);
    const cp = svg('clipPath', { id: clipId }, svg('defs', null, root));
    svg('rect', { x: left, y: top, width: pw, height: ph }, cp);
    const marksRoot = svg('g', { 'clip-path': 'url(#' + clipId + ')' }, root);
    const labelsRoot = svg('g', { class: 'pt-labels' }, root);
    const placed = [];
    const points = [];                                   // every drawn point, for the hover layer
    series.forEach((s, k) => {
      const sx = (i) => X(s.x[i]);
      for (const p of runs(s.data, sx, Y)) {
        if (p.length > 1 && !s.noline) {
          const l = svg('path', { d: s.smooth ? smooth(p) : straight(p), fill: 'none', 'stroke-width': 2, 'stroke-linejoin': 'round',
            'stroke-linecap': s.dash ? 'butt' : 'round' }, marksRoot);
          if (s.dash) l.setAttribute('stroke-dasharray', '6 4');
          l.style.stroke = colors[k];
        }
        const dots = s.marker || s.noline || p.length === 1;
        for (const q of p) {
          points.push({ k, i: q[2], x: q[0], y: q[1] });
          if (dots) svg('circle', { cx: f1(q[0]), cy: f1(q[1]), r: s.noline ? 4 : 3, class: 'mk' }, marksRoot).style.fill = colors[k];
        }
      }
    });
    // labels of the points (read from the sheet): above the point, below when that is taken, left out when both are
    series.forEach((s) => {
      if (!s.labels) return;
      s.labels.forEach((text, i) => {
        if (!text || !isNum(s.data[i]) || !isNum(s.x[i])) return;
        const x = X(s.x[i]), y = Y(s.data[i]);
        if (x < left || x > W - right || y < top || y > top + ph) return;
        const w = textWidth(text) * 0.92 + 4;
        for (const dy of [-8, 15]) {
          const box = { x0: x - w / 2, x1: x + w / 2, y0: y + dy - 9, y1: y + dy + 2 };
          if (box.y0 < top - 2 || box.y1 > top + ph + 2 || box.x0 < left - 2 || box.x1 > W - 2) continue;
          if (placed.some((b) => box.x0 < b.x1 && box.x1 > b.x0 && box.y0 < b.y1 && box.y1 > b.y0)) continue;
          placed.push(box);
          svg('text', { x: f1(x), y: f1(y + dy), 'text-anchor': 'middle', class: 'pt' }, labelsRoot).textContent = text;
          break;
        }
      });
    });

    // ---- hover: the nearest point, and what the other series say at the same x
    const cross = svg('line', { class: 'cross', y1: top, y2: top + ph, x1: 0, x2: 0, visibility: 'hidden' }, root);
    const rings = svg('g', null, root);
    const hit = svg('rect', { x: left, y: top, width: pw, height: ph, fill: 'transparent' }, root);
    const tipDigits = Math.min(6, Math.max(digits + 2, d.unit === 'pct' ? 3 : 1));
    const show = (pt) => {
      const box = root.getBoundingClientRect();
      if (!box.width || !points.length) return;
      const mx = (pt.clientX - box.left) * (W / box.width), my = (pt.clientY - box.top) * (H / box.height);
      let best = points[0], bd = Infinity;
      for (const q of points) {
        const dist = (q.x - mx) * (q.x - mx) + (q.y - my) * (q.y - my) * 0.35;      // x counts more than y
        if (dist < bd) { bd = dist; best = q; }
      }
      cross.setAttribute('x1', f1(best.x));
      cross.setAttribute('x2', f1(best.x));
      cross.setAttribute('visibility', 'visible');
      clear(rings);
      if (!this.tip) { this.tip = h('div', { class: 'chart-tip' }); document.body.appendChild(this.tip); }
      clear(this.tip);
      const main = series[best.k];
      const name = main.labels && main.labels[best.i] ? main.labels[best.i] + ' · ' : '';
      this.tip.appendChild(h('div', { class: 't' }, name + xText(main.x[best.i])));
      series.forEach((s, k) => {
        // this series' point at (or right next to) the same x
        let j = -1, gap = Math.max(1.5, pw * 0.012);
        s.x.forEach((x, i) => {
          if (!isNum(x) || !isNum(s.data[i])) return;
          const dx = Math.abs(X(x) - best.x);
          if (dx <= gap) { gap = dx; j = i; }
        });
        if (k === best.k) j = best.i;
        if (j < 0) return;
        const cy = Y(s.data[j]);
        if (cy >= top && cy <= top + ph) svg('circle', { cx: f1(X(s.x[j])), cy: f1(cy), r: 4.5, class: 'ring' }, rings).style.fill = colors[k];
        this.tip.appendChild(h('div', { class: 'r' }, h('span', null, swatch(s, colors[k]), label(s, k)), h('b', null, this.fmt(s.data[j], tipDigits))));
      });
      const tr = this.tip.getBoundingClientRect();
      let tx = pt.clientX + 14, ty = pt.clientY + 14;
      if (tx + tr.width > window.innerWidth - 8) tx = pt.clientX - tr.width - 14;
      if (ty + tr.height > window.innerHeight - 8) ty = pt.clientY - tr.height - 14;
      this.tip.style.left = Math.max(4, tx) + 'px';
      this.tip.style.top = Math.max(4, ty) + 'px';
    };
    hit.addEventListener('pointermove', (evt) => {
      this.hover = { clientX: evt.clientX, clientY: evt.clientY };
      show(this.hover);
    });
    hit.addEventListener('pointerleave', () => {
      this.hover = null;
      cross.setAttribute('visibility', 'hidden');
      clear(rings);
      this.hideTip();
    });
    this.plot.appendChild(root);
    if (this.hover) show(this.hover);
  }
}
