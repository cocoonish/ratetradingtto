// Dependency-free SVG charts (line / area / grouped and stacked bars) with a crosshair tooltip.
// Colours come from the theme tokens --s1..--s8 in fixed order; text always uses ink tokens.
import { h, clear } from './ui.js';
import { num } from './format.js';

const NS = 'http://www.w3.org/2000/svg';
const MAX_SERIES = 8;

function svg(tag, attrs, parent) {
  const el = document.createElementNS(NS, tag);
  if (attrs) for (const k of Object.keys(attrs)) el.setAttribute(k, attrs[k]);
  if (parent) parent.appendChild(el);
  return el;
}

function niceScale(lo, hi, target) {
  if (!isFinite(lo) || !isFinite(hi)) { lo = 0; hi = 1; }
  if (lo === hi) {
    const pad = Math.abs(lo) * 0.05 || 1;
    lo -= pad; hi += pad;
  }
  const raw = (hi - lo) / target;
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const norm = raw / mag;
  const step = (norm < 1.5 ? 1 : norm < 3 ? 2 : norm < 7 ? 5 : 10) * mag;
  const a = Math.floor(lo / step + 1e-9) * step;
  const b = Math.ceil(hi / step - 1e-9) * step;
  const ticks = [];
  for (let k = 0; a + k * step <= b + step * 1e-6; k++) ticks.push(a + k * step);
  return { lo: a, hi: b, step, ticks };
}

function stepDigits(step) {
  if (!isFinite(step) || step <= 0) return 2;
  return Math.max(0, Math.min(6, Math.ceil(-Math.log10(step) - 1e-9)));
}

export function seriesColor(k) {
  return 'var(--s' + ((k % MAX_SERIES) + 1) + ')';
}

function colorOf(s, k) {
  return seriesColor(typeof s.slot === 'number' ? s.slot : k);
}

let clipSeq = 0;

/** Grid-compatible table of the chart's numbers (the chart's "table view", copyable to Excel). */
export function chartTable(data) {
  const mult = data.unit === 'pct' ? 100 : 1;
  const digits = data.unit === 'pct' ? 3 : 4;
  const head = [{ t: '', k: 's', b: 1, f: 'hd' }].concat(data.series.map((s) => ({ t: s.name || '', k: 's', b: 1, f: 'hd' })));
  const rows = [head];
  for (let i = 0; i < data.cats.length; i++) {
    const row = [{ t: data.cats[i], k: 's' }];
    for (const s of data.series) {
      const v = s.data[i];
      row.push(typeof v === 'number' ? { t: num(v * mult, digits, false) + (mult === 100 ? '%' : ''), v, k: 'n' } : { t: '', k: '' });
    }
    rows.push(row);
  }
  return { sheet: '', rows };
}

export class Chart {
  constructor(host, data, opts = {}) {
    this.host = host;
    this.opts = Object.assign({ height: 250 }, opts);
    this.data = data;
    this.tip = null;
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
    this.data = data;
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
    const d = this.data;
    if (typeof v !== 'number') return '–';
    if (d.unit === 'pct') return num(v * 100, digits, false) + '%';
    return num(v, digits, Math.abs(v) >= 10000);
  }

  render() {
    const d = this.data;
    clear(this.legend);
    clear(this.plot);
    this.hideTip();
    const series = (d && d.series ? d.series : []).slice(0, MAX_SERIES);
    const n = d && d.cats ? d.cats.length : 0;
    const any = series.some((s) => s.data.some((v) => typeof v === 'number'));
    if (!n || !any) {
      this.plot.appendChild(h('div', { class: 'chart-empty' }, 'Veri yok'));
      return;
    }
    if (series.length > 1) {
      series.forEach((s, k) => {
        const sw = h('i', { class: s.kind === 'line' ? '' : 'box' });
        if (s.kind === 'line') {
          sw.style.borderTopColor = colorOf(s, k);
          if (s.dash) sw.style.borderTopStyle = 'dashed';
        } else {
          sw.style.background = colorOf(s, k);
          if (s.kind === 'area') sw.style.opacity = '0.45';
        }
        this.legend.appendChild(h('span', { class: 'key' }, sw, s.name || ('Seri ' + (k + 1))));
      });
    }
    const W = Math.max(260, Math.floor(this.plot.clientWidth) || 520);
    const H = this.opts.height;
    this.width = W;

    // ---- value range
    const bars = series.map((s, k) => ({ s, k })).filter((x) => x.s.kind === 'bar');
    const stacked = bars.length > 1 && bars.every((x) => x.s.stacked);
    let lo = Infinity, hi = -Infinity;
    for (const s of series) {
      if (s.kind === 'bar' && stacked) continue;
      for (const v of s.data) if (typeof v === 'number') { if (v < lo) lo = v; if (v > hi) hi = v; }
    }
    if (stacked) {
      for (let i = 0; i < n; i++) {
        let pos = 0, neg = 0;
        for (const b of bars) {
          const v = b.s.data[i];
          if (typeof v === 'number') { if (v >= 0) pos += v; else neg += v; }
        }
        if (pos > hi) hi = pos;
        if (neg < lo) lo = neg;
      }
    }
    const baseZero = bars.length > 0 || series.some((s) => s.kind === 'area');
    if (baseZero) { lo = Math.min(lo, 0); hi = Math.max(hi, 0); }
    // axis limits fixed in the workbook's chart win over the data range
    const fixLo = typeof d.ymin === 'number', fixHi = typeof d.ymax === 'number';
    if (fixLo) lo = d.ymin;
    if (fixHi) hi = d.ymax;
    if (!(hi > lo)) hi = lo + (Math.abs(lo) * 0.1 || 1);
    const scale = niceScale(lo, hi, H < 200 ? 3 : 5);
    if (fixLo) { scale.lo = d.ymin; scale.ticks = scale.ticks.filter((t) => t >= d.ymin - scale.step * 1e-6); }
    if (fixHi) { scale.hi = d.ymax; scale.ticks = scale.ticks.filter((t) => t <= d.ymax + scale.step * 1e-6); }
    const mult = d.unit === 'pct' ? 100 : 1;
    const digits = stepDigits(scale.step * mult);
    const labels = scale.ticks.map((t) => this.fmt(t, digits));
    const left = Math.max(30, Math.max(...labels.map((t) => t.length)) * 6.3 + 12);
    const right = 12, top = 8, bottom = 24;
    const pw = W - left - right, ph = H - top - bottom;
    const band = pw / n;
    const X = (i) => left + band * (i + 0.5);
    const Y = (v) => top + ph - ((v - scale.lo) / (scale.hi - scale.lo)) * ph;

    const root = svg('svg', { class: 'chart', viewBox: '0 0 ' + W + ' ' + H, width: W, height: H, role: 'img' });
    root.setAttribute('aria-label', d.title || 'grafik');
    const gGrid = svg('g', { class: 'grid' }, root);
    scale.ticks.forEach((t, k) => {
      const y = Math.round(Y(t)) + 0.5;
      svg('line', { x1: left, x2: W - right, y1: y, y2: y }, gGrid);
      const tx = svg('text', { x: left - 7, y: y + 3.5, 'text-anchor': 'end' }, root);
      tx.textContent = labels[k];
    });
    if (scale.lo < 0 && scale.hi > 0 || baseZero) {
      const y0 = Math.round(Y(Math.max(scale.lo, Math.min(0, scale.hi)))) + 0.5;
      const ax = svg('g', { class: 'axis' }, root);
      svg('line', { x1: left, x2: W - right, y1: y0, y2: y0 }, ax);
    }
    // ---- x labels (skip to avoid collisions)
    const longest = Math.max(...d.cats.map((c) => String(c).length));
    const every = Math.max(1, Math.ceil((longest * 6.1 + 14) / band));
    for (let i = 0; i < n; i += every) {
      const tx = svg('text', { x: X(i), y: H - 7, 'text-anchor': 'middle' }, root);
      tx.textContent = d.cats[i];
    }

    // everything drawn from data is clipped to the plot (fixed axis limits may cut a series)
    const clipId = 'tto-clip-' + (++clipSeq);
    const defs = svg('defs', null, root);
    const cp = svg('clipPath', { id: clipId }, defs);
    svg('rect', { x: left, y: top - 1, width: pw, height: ph + 2 }, cp);
    const marksRoot = svg('g', { 'clip-path': 'url(#' + clipId + ')' }, root);

    // ---- areas (wash to the zero line)
    const zeroY = Y(Math.max(scale.lo, Math.min(0, scale.hi)));
    series.forEach((s, k) => {
      if (s.kind !== 'area') return;
      const pts = [];
      s.data.forEach((v, i) => { if (typeof v === 'number') pts.push([X(i), Y(v)]); });
      if (pts.length < 2) return;
      const path = 'M' + pts[0][0] + ',' + zeroY + ' ' + pts.map((p) => 'L' + p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' ')
        + ' L' + pts[pts.length - 1][0] + ',' + zeroY + ' Z';
      const a = svg('path', { d: path, 'fill-opacity': 0.16, stroke: 'none' }, marksRoot);
      a.style.fill = colorOf(s, k);
      if (s.noline) return;
      const l = svg('path', { d: 'M' + pts.map((p) => p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' L'), fill: 'none', 'stroke-width': 2,
        'stroke-linejoin': 'round' }, marksRoot);
      l.style.stroke = colorOf(s, k);
    });

    // ---- bars
    if (bars.length) {
      const groups = stacked ? 1 : bars.length;
      const bw = Math.max(2, Math.min(24, (band * 0.78) / groups - 2));
      const total = groups * bw + (groups - 1) * 2;
      for (let i = 0; i < n; i++) {
        let pos = 0, neg = 0;
        bars.forEach((b, bi) => {
          const v = b.s.data[i];
          if (typeof v !== 'number' || v === 0) return;
          let y0, y1;
          if (stacked) {
            if (v >= 0) { y0 = Y(pos); pos += v; y1 = Y(pos); } else { y0 = Y(neg); neg += v; y1 = Y(neg); }
          } else { y0 = Y(0); y1 = Y(v); }
          const x = X(i) - total / 2 + (stacked ? 0 : bi * (bw + 2));
          const yTop = Math.min(y0, y1), hgt = Math.max(1, Math.abs(y1 - y0) - (stacked ? 2 : 0));
          const r = Math.min(4, bw / 2, hgt);
          const up = v >= 0;
          const yy = up ? yTop : yTop + (stacked ? 2 : 0);
          // rounded only at the data end; square at the baseline
          const path = up
            ? 'M' + x + ',' + (yy + hgt) + ' V' + (yy + r) + ' Q' + x + ',' + yy + ' ' + (x + r) + ',' + yy + ' H' + (x + bw - r)
              + ' Q' + (x + bw) + ',' + yy + ' ' + (x + bw) + ',' + (yy + r) + ' V' + (yy + hgt) + ' Z'
            : 'M' + x + ',' + yy + ' V' + (yy + hgt - r) + ' Q' + x + ',' + (yy + hgt) + ' ' + (x + r) + ',' + (yy + hgt) + ' H' + (x + bw - r)
              + ' Q' + (x + bw) + ',' + (yy + hgt) + ' ' + (x + bw) + ',' + (yy + hgt - r) + ' V' + yy + ' Z';
          const el = svg('path', { d: path }, marksRoot);
          el.style.fill = colorOf(b.s, b.k);
        });
      }
    }

    // ---- lines
    series.forEach((s, k) => {
      if (s.kind !== 'line') return;
      const pts = [];
      s.data.forEach((v, i) => { if (typeof v === 'number') pts.push([X(i), Y(v)]); });
      if (!pts.length) return;
      if (pts.length === 1) {
        const c = svg('circle', { cx: pts[0][0], cy: pts[0][1], r: 4, class: 'ring' }, marksRoot);
        c.style.fill = colorOf(s, k);
        return;
      }
      const l = svg('path', { d: 'M' + pts.map((p) => p[0].toFixed(1) + ',' + p[1].toFixed(1)).join(' L'), fill: 'none', 'stroke-width': 2,
        'stroke-linejoin': 'round', 'stroke-linecap': s.dash ? 'butt' : 'round' }, marksRoot);
      if (s.dash) l.setAttribute('stroke-dasharray', '6 4');
      l.style.stroke = colorOf(s, k);
    });

    // ---- hover layer
    const cross = svg('line', { class: 'cross', y1: top, y2: top + ph, x1: 0, x2: 0, visibility: 'hidden' }, root);
    const marks = svg('g', null, root);
    const hit = svg('rect', { x: left, y: top, width: pw, height: ph, fill: 'transparent' }, root);
    const show = (evt) => {
      const box = root.getBoundingClientRect();
      const mx = (evt.clientX - box.left) * (W / box.width);
      const i = Math.max(0, Math.min(n - 1, Math.floor((mx - left) / band)));
      cross.setAttribute('x1', X(i));
      cross.setAttribute('x2', X(i));
      cross.setAttribute('visibility', 'visible');
      clear(marks);
      series.forEach((s, k) => {
        const v = s.data[i];
        if (typeof v !== 'number' || s.kind === 'bar' || v < scale.lo || v > scale.hi) return;
        const c = svg('circle', { cx: X(i), cy: Y(v), r: 4.5, class: 'ring' }, marks);
        c.style.fill = colorOf(s, k);
      });
      if (!this.tip) { this.tip = h('div', { class: 'chart-tip' }); document.body.appendChild(this.tip); }
      clear(this.tip);
      this.tip.appendChild(h('div', { class: 't' }, String(d.cats[i])));
      series.forEach((s, k) => {
        const sw = h('i');
        sw.style.borderTopColor = colorOf(s, k);
        if (s.dash) sw.style.borderTopStyle = 'dashed';
        this.tip.appendChild(h('div', { class: 'r' }, h('span', null, sw, s.name || ('Seri ' + (k + 1))),
          h('b', null, this.fmt(s.data[i], Math.min(6, digits + 2)))));
      });
      const tr = this.tip.getBoundingClientRect();
      let tx = evt.clientX + 14, ty = evt.clientY + 14;
      if (tx + tr.width > window.innerWidth - 8) tx = evt.clientX - tr.width - 14;
      if (ty + tr.height > window.innerHeight - 8) ty = evt.clientY - tr.height - 14;
      this.tip.style.left = Math.max(4, tx) + 'px';
      this.tip.style.top = Math.max(4, ty) + 'px';
    };
    const hide = () => {
      cross.setAttribute('visibility', 'hidden');
      clear(marks);
      this.hideTip();
    };
    hit.addEventListener('mousemove', show);
    hit.addEventListener('mouseleave', hide);
    this.plot.appendChild(root);
  }
}
