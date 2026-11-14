// Fan chart: where the option market says a currency pair is going.  The spot's recent past, then from today the
// forward path and around it the risk-neutral distribution of the spot at every tenor as nested percentile bands -
// the cloud - in one hue that deepens towards the middle.  Between two tenors the bands are drawn straight; at today
// they all start at the spot.  Plain SVG with the tokens of chart.js; a crosshair reads the bands at any date.
import { h, clear } from './ui.js';
import { num, settings } from './format.js';
import { valueScale, formatAxisDate } from './chart.js';

const NS = 'http://www.w3.org/2000/svg';
const isNum = (v) => typeof v === 'number' && isFinite(v);
const f1 = (v) => (Math.round(v * 10) / 10).toString();
/** fill opacity of a band by its place from the outside in: the middle of the cloud is the deepest */
const BAND_ALPHA = [0.12, 0.16, 0.2, 0.26];

function svg(tag, attrs, parent) {
  const el = document.createElementNS(NS, tag);
  if (attrs) for (const k of Object.keys(attrs)) el.setAttribute(k, attrs[k]);
  if (parent) parent.appendChild(el);
  return el;
}

/** ISO date -> Excel serial (the axis unit of chart.js). */
export function serialOfIso(iso) {
  return Math.round(Date.UTC(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10)) / 86400000) + 25569;
}

function monthTicks(v0, v1, pxPerDay, labelWidth) {
  const at = (s) => new Date(Math.round((s - 25569) * 86400000));
  const d0 = at(v0), d1 = at(v1);
  const m0 = d0.getUTCFullYear() * 12 + d0.getUTCMonth(), m1 = d1.getUTCFullYear() * 12 + d1.getUTCMonth();
  const every = [1, 2, 3, 6, 12, 24].find((s) => s * 30.4375 * pxPerDay >= labelWidth + 14) || 24;
  const out = [];
  for (let m = m0; m <= m1; m++) {
    if (m % every) continue;
    const s = Date.UTC(Math.floor(m / 12), m % 12, 1) / 86400000 + 25569;
    if (s >= v0 - 0.5 && s <= v1 + 0.5) out.push(s);
  }
  return out;
}

/**
 * data: { today (serial), spot, hist: [[serial, close]], points: [{x (serial), label, fwd, q: {"0.05": level, ...}}],
 *         bands: [["0.05", "0.95"], ["0.25", "0.75"]] (outside in), median (bool), levels: [price], decimals,
 *         horizon (serial: how far to the right) }
 */
export class FanChart {
  constructor(host, data, opts = {}) {
    this.host = host;
    this.opts = opts;
    this.data = data;
    this.tip = null;
    this.hover = null;
    this.width = 0;
    this.wrap = h('div', { class: 'chart-wrap fan' });
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
    if (key === this.key && this.plot.firstChild) return;
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

  /** The cloud at a date after today: each quantile (and the forward) straight between the tenors, the spot at today. */
  at(x) {
    const d = this.data;
    const pts = [{ x: d.today, fwd: d.spot, q: null }].concat(d.points);
    for (let i = 0; i < pts.length - 1; i++) {
      const a = pts[i], b = pts[i + 1];
      if (x < a.x || x > b.x) continue;
      const w = b.x === a.x ? 0 : (x - a.x) / (b.x - a.x);
      const lerp = (u, v) => (isNum(u) && isNum(v) ? u + (v - u) * w : null);
      const q = {};
      for (const k of Object.keys(b.q)) q[k] = lerp(a.q ? a.q[k] : d.spot, b.q[k]);
      return { fwd: lerp(a.fwd, b.fwd), q };
    }
    return null;
  }

  render() {
    const d = this.data;
    this.key = JSON.stringify(d) + '|' + settings.lang;
    clear(this.legend);
    clear(this.plot);
    this.hideTip();
    if (!d || !isNum(d.spot) || !d.points.length) {
      this.plot.appendChild(h('div', { class: 'chart-empty' }, 'Çizilecek dağılım yok (forward ya da vol gelmedi).'));
      return;
    }
    const digits = isNum(d.decimals) ? d.decimals : 4;
    const W = Math.max(320, Math.floor(this.plot.clientWidth || this.host.clientWidth || 720));
    this.width = W;
    const H = this.opts.height || 380;
    const hist = (d.hist || []).filter((p) => isNum(p[1]) && p[0] < d.today);
    const x0 = hist.length ? hist[0][0] : d.today - 30;
    const pts = d.points.filter((p) => p.x <= d.horizon + 0.5);
    const last = d.points.find((p) => p.x > d.horizon + 0.5);
    const x1 = Math.max(d.today + 7, Math.min(d.horizon, (last || pts[pts.length - 1] || { x: d.horizon }).x));
    // ---- the cloud's corners up to the horizon (cut between two tenors where it falls)
    const cut = [{ x: d.today, fwd: d.spot, q: null }].concat(pts);
    const end = this.at(x1);
    if (end && (!pts.length || pts[pts.length - 1].x < x1 - 0.5)) cut.push({ x: x1, fwd: end.fwd, q: end.q });
    // ---- the value range: the past, every band shown, the levels
    const vals = hist.map((p) => p[1]).concat([d.spot]);
    for (const p of cut) {
      if (isNum(p.fwd)) vals.push(p.fwd);
      if (!p.q) continue;
      for (const [lo, hi] of d.bands) { if (isNum(p.q[lo])) vals.push(p.q[lo]); if (isNum(p.q[hi])) vals.push(p.q[hi]); }
      if (d.median && isNum(p.q['0.5'])) vals.push(p.q['0.5']);
    }
    for (const L of d.levels || []) if (isNum(L)) vals.push(L);
    const top = 14, bottom = 26;
    const ph = H - top - bottom;
    const scale = valueScale({ auto: 'fit' }, Math.min(...vals), Math.max(...vals), ph);
    const fmtY = (v) => num(v, Math.max(0, Math.min(6, Math.ceil(-Math.log10(scale.step) - 1e-9))), false);
    const left = Math.ceil(Math.max(...scale.ticks.map((t) => fmtY(t).length * 6.4)) + 14);
    const right = 46;
    const pw = W - left - right;
    const X = (x) => left + ((x - x0) / Math.max(1, x1 - x0)) * pw;
    const Y = (v) => top + (1 - (v - scale.lo) / (scale.hi - scale.lo)) * ph;
    const root = svg('svg', { class: 'chart', viewBox: '0 0 ' + W + ' ' + H, width: W, height: H, role: 'img',
      'aria-label': 'İma edilen yol ve olasılık bulutu' });
    // ---- grid and axes
    const grid = svg('g', { class: 'grid' }, root);
    for (const t of scale.ticks) {
      svg('line', { x1: left, x2: left + pw, y1: f1(Y(t)), y2: f1(Y(t)) }, grid);
      svg('text', { x: left - 6, y: f1(Y(t) + 3.5), 'text-anchor': 'end' }, root).textContent = fmtY(t);
    }
    const axis = svg('g', { class: 'axis' }, root);
    svg('line', { x1: left, x2: left + pw, y1: top + ph, y2: top + ph }, axis);
    for (const s of monthTicks(x0, x1, pw / Math.max(1, x1 - x0), 34)) {
      svg('line', { x1: f1(X(s)), x2: f1(X(s)), y1: top + ph, y2: top + ph + 4 }, axis);
      svg('text', { x: f1(X(s)), y: top + ph + 16, 'text-anchor': 'middle' }, root).textContent = formatAxisDate(s, 'mmm yy');
    }
    // ---- the cloud: nested bands, the outer first
    const blue = 'var(--c-blue)';
    d.bands.forEach(([lo, hi], k) => {
      const up = [], down = [];
      for (const p of cut) {
        const a = p.q ? p.q[lo] : d.spot, b = p.q ? p.q[hi] : d.spot;
        if (!isNum(a) || !isNum(b)) continue;
        up.push(f1(X(p.x)) + ',' + f1(Y(b)));
        down.push(f1(X(p.x)) + ',' + f1(Y(a)));
      }
      if (up.length < 2) return;
      const alpha = BAND_ALPHA[Math.min(BAND_ALPHA.length - 1, k + Math.max(0, BAND_ALPHA.length - d.bands.length))];
      svg('path', { d: 'M' + up.join(' L') + ' L' + down.reverse().join(' L') + ' Z', fill: blue, 'fill-opacity': alpha, stroke: 'none' }, root);
    });
    // ---- levels of the probability table: dotted lines, their value just above the line at the left (the right end
    // belongs to the cloud's own labels)
    const lv = svg('g', null, root);
    for (const L of d.levels || []) {
      if (!isNum(L) || L < scale.lo || L > scale.hi) continue;
      svg('line', { x1: left, x2: left + pw, y1: f1(Y(L)), y2: f1(Y(L)), stroke: 'var(--ink-3)', 'stroke-width': 1, 'stroke-dasharray': '2 3' }, lv);
      const t = svg('text', { x: left + 4, y: f1(Y(L) - 3), class: 'pt' }, lv);
      t.textContent = num(L, digits > 2 ? 2 : digits, false);
    }
    // ---- today
    svg('line', { x1: f1(X(d.today)), x2: f1(X(d.today)), y1: top, y2: top + ph, stroke: 'var(--line-2)', 'stroke-dasharray': '3 3' }, root);
    svg('text', { x: f1(X(d.today) + 4), y: top + 9, class: 'pt' }, root).textContent = 'bugün';
    // ---- lines: the past, the forward, the median
    const line = (p, attrs) => (p.length > 1 ? svg('path', Object.assign({ d: 'M' + p.join(' L'), fill: 'none', 'stroke-width': 2,
      'stroke-linejoin': 'round', 'stroke-linecap': 'round' }, attrs), root) : null);
    line(hist.map((p) => f1(X(p[0])) + ',' + f1(Y(p[1]))).concat([f1(X(d.today)) + ',' + f1(Y(d.spot))]), { stroke: 'var(--ink-2)' });
    const fwd = cut.filter((p) => isNum(p.fwd)).map((p) => f1(X(p.x)) + ',' + f1(Y(p.fwd)));
    line(fwd, { stroke: 'var(--ink)', 'stroke-width': 1.5, 'stroke-dasharray': '6 4', 'stroke-linecap': 'butt' });
    if (d.median) {
      line(cut.map((p) => (p.q ? p.q['0.5'] : d.spot)).map((v, i) => (isNum(v) ? f1(X(cut[i].x)) + ',' + f1(Y(v)) : null)).filter(Boolean),
        { stroke: blue });
    }
    // markers at the tenors on the forward path (where the numbers are)
    for (const p of pts) {
      if (!isNum(p.fwd)) continue;
      svg('circle', { cx: f1(X(p.x)), cy: f1(Y(p.fwd)), r: 3.2, class: 'mk' }, root).style.fill = 'var(--ink)';
    }
    svg('circle', { cx: f1(X(d.today)), cy: f1(Y(d.spot)), r: 4, class: 'mk' }, root).style.fill = 'var(--ink-2)';
    // ---- direct labels at the right end: the outer band's edges, the median, the forward
    const tail = cut[cut.length - 1];
    if (tail && tail.q) {
      const labels = [];
      if (d.bands.length) {
        const [lo, hi] = d.bands[0];
        labels.push([tail.q[hi], '%' + Math.round(+hi * 100)], [tail.q[lo], '%' + Math.round(+lo * 100)]);
      }
      if (d.median) labels.push([tail.q['0.5'], 'medyan']);
      labels.push([tail.fwd, 'fwd']);
      const used = [];
      for (const [v, text] of labels) {
        if (!isNum(v)) continue;
        let y = Y(v) + 3.5;
        if (used.some((u) => Math.abs(u - y) < 10)) continue;                // never two labels on top of each other
        used.push(y);
        svg('text', { x: f1(X(tail.x) + 4), y: f1(y), class: 'pt' }, root).textContent = text;
      }
    }
    // ---- legend
    const key = (swatch, text) => this.legend.appendChild(h('span', { class: 'key' }, swatch, text));
    const lineSw = (color, dash) => {
      const s = svg('svg', { width: 22, height: 10 });
      const l = svg('line', { x1: 1, x2: 21, y1: 5, y2: 5, stroke: color, 'stroke-width': 2 }, s);
      if (dash) l.setAttribute('stroke-dasharray', '5 3');
      return s;
    };
    const boxSw = (alpha) => {
      const s = svg('svg', { width: 14, height: 10 });
      svg('rect', { x: 1, y: 1, width: 12, height: 8, rx: 2, fill: blue, 'fill-opacity': alpha }, s);
      return s;
    };
    key(lineSw('var(--ink-2)'), 'spot (geçmiş)');
    key(lineSw('var(--ink)', true), 'forward');
    if (d.median) key(lineSw(blue), 'medyan');
    d.bands.forEach(([lo, hi], k) => {
      const alpha = BAND_ALPHA[Math.min(BAND_ALPHA.length - 1, k + Math.max(0, BAND_ALPHA.length - d.bands.length))];
      key(boxSw(Math.min(0.9, alpha * (k + 1))), '%' + Math.round(+lo * 100) + '–' + Math.round(+hi * 100));
    });
    // ---- hover: the past's close, or the cloud at that date
    const cross = svg('line', { class: 'cross', y1: top, y2: top + ph, x1: 0, x2: 0, visibility: 'hidden' }, root);
    const hit = svg('rect', { x: left, y: top, width: pw, height: ph, fill: 'transparent' }, root);
    const fmt = (v) => (isNum(v) ? num(v, digits, false) : '–');
    const show = (pt) => {
      const box = root.getBoundingClientRect();
      if (!box.width) return;
      const mx = (pt.clientX - box.left) * (W / box.width);
      const x = x0 + ((mx - left) / pw) * (x1 - x0);
      cross.setAttribute('x1', f1(mx));
      cross.setAttribute('x2', f1(mx));
      cross.setAttribute('visibility', 'visible');
      if (!this.tip) { this.tip = h('div', { class: 'chart-tip' }); document.body.appendChild(this.tip); }
      clear(this.tip);
      const row = (name, v) => this.tip.appendChild(h('div', { class: 'r' }, h('span', null, name), h('b', null, fmt(v))));
      if (x <= d.today) {
        let best = null;
        for (const p of hist) if (!best || Math.abs(p[0] - x) < Math.abs(best[0] - x)) best = p;
        const p = best && Math.abs(best[0] - x) > Math.abs(d.today - x) ? [d.today, d.spot] : best;
        this.tip.appendChild(h('div', { class: 't' }, p ? formatAxisDate(p[0], 'dd.mm.yy') : ''));
        row(p && p[0] === d.today ? 'spot (şimdi)' : 'kapanış', p ? p[1] : null);
      } else {
        const c = this.at(x);
        const near = pts.find((p) => Math.abs(p.x - x) <= 3);
        this.tip.appendChild(h('div', { class: 't' }, formatAxisDate(Math.round(x), 'dd.mm.yy') + (near ? ' · ' + near.label : '')));
        if (c) {
          row('forward', c.fwd);
          // the edges of the bands shown and the median, highest first
          const shown = new Set([].concat(...d.bands).concat(d.median ? ['0.5'] : []));
          const ks = Object.keys(c.q).filter((k) => shown.has(k)).map(Number).sort((a, b) => b - a);
          for (const k of ks) row(k === 0.5 ? 'medyan' : '%' + num(k * 100, k * 100 % 1 ? 1 : 0, false), c.q[String(k)]);
        }
      }
      const tr = this.tip.getBoundingClientRect();
      let tx = pt.clientX + 14, ty = pt.clientY + 14;
      if (tx + tr.width > window.innerWidth - 8) tx = pt.clientX - tr.width - 14;
      if (ty + tr.height > window.innerHeight - 8) ty = pt.clientY - tr.height - 14;
      this.tip.style.left = Math.max(4, tx) + 'px';
      this.tip.style.top = Math.max(4, ty) + 'px';
    };
    hit.addEventListener('pointermove', (evt) => { this.hover = { clientX: evt.clientX, clientY: evt.clientY }; show(this.hover); });
    hit.addEventListener('pointerleave', () => { this.hover = null; cross.setAttribute('visibility', 'hidden'); this.hideTip(); });
    this.plot.appendChild(root);
    if (this.hover) show(this.hover);
  }
}
