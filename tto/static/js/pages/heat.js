// Eğri Hareketi: a heat map of the curves - every point's change since the previous close, the day's open or a
// reference taken on purpose (the morning meeting): OIS, offshore and their difference by tenor, the VİOP contracts,
// the bonds of the trading list.  Red: up (a rate, a spread higher), blue: down; the deeper, the larger against the
// day's largest move.  A click on a point draws its past (closes, band, z-score), watches it or sets an alarm on it.
import { api } from '../api.js';
import { h, clear, toast, errorToast, menu } from '../ui.js';
import { openWatchDialog, watchSubject } from '../alarms.js';
import { SeriesView, watchSpec } from '../serieschart.js';
import { isoToTr } from '../format.js';
import { TableColumns, toolsOf } from '../columns.js';

const BASES = [['close', 'Önceki kapanış', 'Bir önceki iş gününün kapanışına göre (OIS, TLREF, offshore: tarihçe; diğerleri: dashboard\'un iş günlerinde kaydettiği kapanış). '
  + 'Hafta sonu piyasa kapalı: son iş gününün kapanışı gösterilir, değişim yoktur'],
  ['open', 'Açılış', 'Dashboard\'un bugün gördüğü ilk değere göre'],
  ['ref', 'Referans', '"Referansı şimdi al" ile alınan seviyelere göre (ör. sabah toplantısı)']];
const KEY = 'tto.heat.basis';
const isNum = (v) => typeof v === 'number' && isFinite(v);
const HISTORY_AGAIN_MS = 5 * 60 * 1000;   // a drawn history is asked again this often (the value now: every refresh)
const keyOf = (subject) => JSON.stringify(subject || null);

function savedBasis() {
  try { const v = localStorage.getItem(KEY); return BASES.some((b) => b[0] === v) ? v : 'close'; } catch (e) { return 'close'; }
}

function rgbOf(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '128, 128, 128';
}

/** The colour of a move: red up, blue down, deeper as it nears the scale's end; nothing for no move. */
function paint(td, chg, cap) {
  if (!isNum(chg) || Math.abs(chg) < 0.05) { td.style.background = ''; return; }
  const t = Math.min(1, Math.abs(chg) / cap);
  const c = 'rgba(' + rgbOf(chg > 0 ? '--heat-up' : '--heat-down') + ', ' + (0.12 + 0.6 * t).toFixed(3) + ')';
  td.style.background = 'linear-gradient(' + c + ', ' + c + '), var(--heat-mid)';
}

export class HeatPage {
  constructor(host, ctx) {
    this.host = host;
    this.ctx = ctx;
    this.basis = savedBasis();
    this.data = null;
    this.picked = null;                    // the point whose past is drawn: {key, subject, label}
    this.build();
  }

  build() {
    const tools = h('div', { class: 'page-tools' });
    this.seg = h('div', { class: 'seg', id: 'heat-basis' });
    for (const [v, t, tip] of BASES) {
      const b = h('button', { type: 'button', title: tip }, t);
      b.dataset.v = v;
      b.classList.toggle('on', v === this.basis);
      b.addEventListener('click', () => {
        this.basis = v;
        try { localStorage.setItem(KEY, v); } catch (e) { /* not kept */ }
        for (const x of this.seg.children) x.classList.toggle('on', x === b);
        this.refresh();
      });
      this.seg.appendChild(b);
    }
    const ref = h('button', { class: 'btn', type: 'button', id: 'heat-ref', title: 'Şimdiki seviyeleri referans al (ör. sabah toplantısı); "Referans"a göre değişim o andan beri gösterilir' }, 'Referansı şimdi al');
    ref.addEventListener('click', () => this.takeRef());
    this.info = h('span', { class: 'muted', id: 'heat-info' });
    this.legend = h('span', { class: 'heat-legend', id: 'heat-legend' });
    tools.appendChild(h('span', { class: 'muted' }, 'Değişim:'));
    tools.appendChild(this.seg);
    tools.appendChild(ref);
    tools.appendChild(this.legend);
    tools.appendChild(this.info);
    this.host.appendChild(tools);
    // the past of the point clicked
    const seriesBody = h('div', { class: 'body' });
    const close = h('button', { class: 'iconbtn', type: 'button', title: 'Grafiği kapat' }, '✕');
    close.addEventListener('click', () => this.closeHistory());
    this.seriesSec = h('section', { class: 'panel wide hidden', id: 'heat-series' },
      h('header', null, h('h2', null, 'Seçili noktanın geçmişi'), h('span', { class: 'grow' }), close), seriesBody,
      h('div', { class: 'note' }, 'Bir noktaya tıklayıp "Geçmişini çiz"i seçin. Kapanışlar İzleme · Alarmlar\'daki z\'nin kullandıklarıdır (OIS, TLREF, offshore: tarihçe deposu; '
        + 'diğerleri dashboard\'un kaydettiği kapanış); son nokta şimdiki değer.'));
    this.host.appendChild(this.seriesSec);
    this.sv = new SeriesView(seriesBody, { rule: 'raw', prefKey: 'tto.heat.series.window', window: 60, height: 220 });
    this.box = h('div', { id: 'heat-panels' });
    this.host.appendChild(this.box);
  }

  async load() { await this.refresh(); }

  async refresh() {
    const d = await api.get('/api/heat?basis=' + this.basis);
    this.data = d;
    this.draw(d);
    this.liveHistory(d);
  }

  draw(d) {
    clear(this.legend);
    this.legend.appendChild(h('span', null, 'düştü −' + d.cap + ' bp'));
    this.legend.appendChild(h('span', { class: 'bar' }));
    this.legend.appendChild(h('span', null, '+' + d.cap + ' bp yükseldi'));
    const base = (BASES.find((b) => b[0] === d.basis) || BASES[0])[1].toLowerCase();
    this.info.textContent = d.basis === 'ref' && !d.ref_at ? 'Bugün referans alınmadı: "Referansı şimdi al"'
      : d.basis === 'close' && d.closed ? 'Hafta sonu, piyasa kapalı: son iş günü ' + isoToTr(d.closed) + ' kapanışı olan noktalarda değişim yok · ' + d.time
        : 'Değişim ' + (d.basis === 'ref' ? 'referanstan (' + d.ref_at + ')' : base + 'tan') + ' · ' + d.time;
    const box = clear(this.box);
    for (const p of d.panels) {
      const t = h('table', { class: 'heat', 'data-panel': p.id });
      t.appendChild(h('tr', null, h('th', { class: 'row' }, ''), ...p.cols.map((c) => h('th', { title: c.tip || null }, c.label))));
      for (const row of p.rows) {
        const tr = h('tr', null, h('th', { class: 'row' }, row.name));
        for (const c of row.cells) {
          if (!c) { tr.appendChild(h('td', { class: 'none' })); continue; }
          const has = isNum(c.chg);
          const td = h('td', { class: 'hc' + (has ? '' : ' nochg'),
            title: c.label + '\nŞimdi: ' + (c.now_text || '–') + (c.base_text ? '\n' + (d.basis === 'close' ? 'Önceki kapanış' + (c.base_day ? ' (' + c.base_day + ')' : '')
              : d.basis === 'open' ? 'Açılış' : 'Referans') + ': ' + c.base_text : '') + (has ? '\nDeğişim: ' + c.chg_text : '\nDeğişim: karşılaştıracak değer yok') },
          h('div', { class: 'c' }, has ? c.chg_text.replace(' bp', '') : '–'), h('div', { class: 'l' }, c.now_text || ''));
          paint(td, c.chg, d.cap);
          if (this.picked && this.picked.key === keyOf(c.subject)) td.classList.add('pick');
          td.addEventListener('click', (e) => this.pick(c, e));
          tr.appendChild(td);
        }
        t.appendChild(tr);
      }
      const body = h('div', { class: 'body heat-wrap' }, t);
      box.appendChild(h('section', { class: 'panel wide', id: 'heat-' + p.id }, h('header', null, h('h2', null, p.title)), body));
      // each user hides columns of their own (a right click on a caption, or "Sütunlar")
      this.colsOf = this.colsOf || new Map();
      if (!this.colsOf.has(p.id)) this.colsOf.set(p.id, new TableColumns('heat/' + p.id));
      this.colsOf.get(p.id).attach(t, toolsOf(body, true));
    }
  }

  pick(c, e) {
    menu(e.clientX, e.clientY, [{ header: c.label },
      { label: 'Geçmişini çiz (z-skoru ile)', action: () => this.showHistory({ key: keyOf(c.subject), subject: c.subject, label: c.label }) },
      { label: 'İzlemeye ekle', action: () => watchSubject(this.ctx, c.subject) },
      { label: 'Alarm kur…', action: () => openWatchDialog(this.ctx, { subject: c.subject, focus: 'alarm' }) },
      { label: 'Hareket alarmı…', action: () => openWatchDialog(this.ctx, { subject: c.subject, focus: 'alarm', mode: 'move' }) }]);
    e.stopPropagation();
  }

  async takeRef() {
    try {
      const r = await api.post('/api/heat/ref', {});
      toast(r.count + ' noktanın referansı alındı (' + r.at + ')', 'ok');
      if (this.basis !== 'ref') {
        this.basis = 'ref';
        try { localStorage.setItem(KEY, 'ref'); } catch (x) { /* not kept */ }
        for (const x of this.seg.children) x.classList.toggle('on', x.dataset.v === 'ref');
      }
      this.ctx.refreshNow();
    } catch (err) { errorToast(err); }
  }

  // ------------------------------------------------------------------ the past of the point clicked
  showHistory(w) {
    this.picked = w;
    this.hist = null;
    this.seriesSec.classList.remove('hidden');
    this.markPicked();
    this.seriesSec.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    this.loadHistory(true);
  }

  closeHistory() {
    this.picked = null;
    this.hist = null;
    this.seriesSec.classList.add('hidden');
    this.markPicked();
  }

  markPicked() {
    if (!this.data) return;
    const tds = this.box.querySelectorAll('td.hc');
    let k = 0;
    for (const p of this.data.panels) {
      for (const row of p.rows) {
        for (const c of row.cells) {
          if (!c) continue;
          const td = tds[k++];
          if (td) td.classList.toggle('pick', !!(this.picked && this.picked.key === keyOf(c.subject)));
        }
      }
    }
  }

  async loadHistory(fresh) {
    const w = this.picked;
    if (!w) return;
    const seq = (this.hseq = (this.hseq || 0) + 1);
    if (fresh) this.sv.loading(w.label);
    try {
      const d = await api.post('/api/watch/history', { subject: w.subject });
      if (seq !== this.hseq || this.picked !== w) return;
      this.hist = d;
      this.histAt = Date.now();
      this.sv.show(watchSpec(d, w.label));
    } catch (err) {
      if (seq === this.hseq) this.sv.show({ title: w.label, points: [], why: (err && err.message) || 'Geçmiş alınamadı' });
    }
  }

  /** The value now from the map (every refresh); the closes again now and then. */
  liveHistory(d) {
    const w = this.picked;
    if (!w || !this.hist) return;
    if (Date.now() - (this.histAt || 0) > HISTORY_AGAIN_MS) { this.loadHistory(false); return; }
    for (const p of d.panels) {
      for (const row of p.rows) {
        for (const c of row.cells) {
          if (c && keyOf(c.subject) === w.key && isNum(c.now) && c.now !== this.hist.value) {
            this.hist.value = c.now;
            this.sv.show(watchSpec(this.hist, w.label));
            return;
          }
        }
      }
    }
  }

  destroy() {
    if (this.sv) this.sv.destroy();
  }
}
