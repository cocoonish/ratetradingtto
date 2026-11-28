// Pages built on the dashboard's own history: the end-of-day change matrix, the pricing of every MPC meeting
// over time, and the settings behind them (the meeting calendar).
import { api } from '../api.js';
import { h, clear, toast, errorToast, confirmDialog, modal, copyText, foldNote } from '../ui.js';
import { Grid, copyGrid } from '../grid.js';
import { Chart } from '../chart.js';
import { num, pct, isoToTr } from '../format.js';
import { SeriesView } from '../serieschart.js';

const isNum = (v) => typeof v === 'number' && isFinite(v);
/** A TRY rate's decimals on the end-of-day matrix (OIS, offshore, TLREF, a meeting's TLREF after it, a bond's yield): two,
 *  as on the header strip and the pricing tables (the desk, 25.11.2026; for this page 28.11.2026: B19). */
export const TRY_DIGITS = 2;
const HD = (t, extra) => Object.assign({ t, k: 's', b: 1, f: 'hd' }, extra || {});
const TXT = (t, extra) => Object.assign({ t: t || '', k: 's' }, extra || {});
const EMPTY = () => ({ t: '', k: '' });
const SKIP = () => ({ t: '', k: '', sk: 1 });
const serialOf = (iso) => Math.round(Date.parse(iso + 'T00:00:00Z') / 86400000) + 25569;
const shortDate = (iso) => (iso ? iso.slice(8, 10) + '.' + iso.slice(5, 7) : '');

/** "10.12.2026", "10/12/2026", "2026-12-10" -> "2026-12-10" (null when it is not a date). */
export function parseTrDate(text) {
  const s = (text || '').trim();
  let y, m, d;
  let x = /^(\d{1,2})[./-](\d{1,2})[./-](\d{4})$/.exec(s);
  if (x) { d = +x[1]; m = +x[2]; y = +x[3]; } else {
    x = /^(\d{4})-(\d{1,2})-(\d{1,2})$/.exec(s);
    if (!x) return null;
    y = +x[1]; m = +x[2]; d = +x[3];
  }
  if (y < 2000 || y > 2100 || m < 1 || m > 12 || d < 1 || d > 31) return null;
  const t = new Date(Date.UTC(y, m - 1, d));
  if (t.getUTCMonth() !== m - 1 || t.getUTCDate() !== d) return null;        // 31.02 is not a day
  return t.toISOString().slice(0, 10);
}

/** A number as a cell (a blank cell when there is none). */
function N(v, digits, extra) {
  if (!isNum(v)) return EMPTY();
  return Object.assign({ t: num(v, digits, false), v, k: 'n' }, extra || {});
}

/** The heat map's colour of a rise / a fall (app.css ``--heat-up`` / ``--heat-down``: Eğri Hareketi's, FX Vol's). */
export function heatBase(up) {
  let text = '';
  try { text = getComputedStyle(document.documentElement).getPropertyValue(up ? '--heat-up' : '--heat-down'); } catch (e) { text = ''; }
  const rgb = String(text || '').split(',').map((x) => Number(x.trim()));
  return rgb.length === 3 && rgb.every((x) => x >= 0 && x <= 255) ? rgb : (up ? [230, 103, 103] : [57, 135, 229]);
}

/** Background of a change: the heat map's colour of a rise (up) or a fall (down), stronger the larger it is against
 *  `scale` - one scale on every page (the desk, 27.11.2026: the layout proposals). */
export function heat(v, scale, base) {
  if (!isNum(v) || !(scale > 0) || Math.abs(v) < 1e-9) return null;
  const t = Math.min(1, Math.abs(v) / scale) * 0.62 + 0.1;
  const c = base || heatBase(v > 0);
  return c.map((x) => Math.round(128 + (x - 128) * t).toString(16).padStart(2, '0')).join('');
}

/** A change as a cell: signed, coloured by size, the earlier level in its tooltip. */
function D(v, scale, digits, from, fromDay, fromDigits) {
  if (!isNum(v)) return EMPTY();
  const shown = Math.abs(v) < 0.5 * Math.pow(10, -digits) ? 0 : v;
  const cell = { t: (shown > 0 ? '+' : '') + num(shown, digits, false), v, k: 'n' };
  const hx = heat(v, scale);
  if (hx) cell.heat = hx;
  if (isNum(from)) cell.tip = (fromDay ? isoToTr(fromDay) + ': ' : 'önceki: ') + num(from, fromDigits === undefined ? 3 : fromDigits, false);
  return cell;
}

const TYPE_TIP = 'Tip: B bono, S sabit kuponlu, T TLREF\'e endeksli, F değişken faizli · Bloomberg\'in adı (NAME) ISIN ve Tip hücresinin üzerinde';

/** Whether the bonds' names tell more than their kind ("Tip"): Bloomberg's NAME is "TURKIYE GOVERNMENT BOND" /
 *  "TURKIYE T-BILL" for nearly every DİBS - repeated down the table it says nothing a kind does not. */
export function namesTellMore(bonds) {
  const byType = new Map();
  for (const b of bonds || []) {
    const n = String(b.name || '').trim();
    if (!n) continue;
    const k = String(b.type || '');
    if (!byType.has(k)) byType.set(k, new Set());
    byType.get(k).add(n);
  }
  return [...byType.values()].some((s) => s.size > 1);
}

/** Largest change of a block (never below `floor`), so that colours compare within the block. */
function scaleOf(values, floor) {
  let m = floor;
  for (const v of values) if (isNum(v) && Math.abs(v) > m) m = Math.abs(v);
  return m;
}

/** A panel; ``fit``: as wide as its table (side by side with another when they fit); ``fold``: a ▾ / ▸ in its header
 *  folds it - ``folded`` by default, each user's own choice kept in this browser (``tto.hist.fold.<id>``); ``clamp``: its
 *  note two lines, "devamı" the rest (the desk, 28.11.2026: Gün Sonu's notes folded). */
function panel(title, opts = {}) {
  const body = h('div', { class: 'body' });
  const tools = h('div', { class: 'tools' });
  const h2 = h('h2', { title }, title);
  const head = h('header', null, h2, opts.badge || null, tools);
  const el = h('section', { class: 'panel' + (opts.wide ? ' wide' : '') + (opts.fit ? ' fit' : '') + (opts.chart ? ' chart full' : '') }, head, body);
  if (opts.id) el.dataset.panel = opts.id;
  const note = h('div', { class: 'note hidden' });
  el.appendChild(note);
  const clamp = opts.clamp ? foldNote(note) : null;
  const p = { el, body, tools, head, title: h2, note,
    setNote(text) {
      if (!clamp) { note.textContent = text || ''; note.classList.toggle('hidden', !text); return; }
      while (note.firstChild && note.firstChild !== clamp.more) note.removeChild(note.firstChild);
      if (text) note.insertBefore(document.createTextNode(text), clamp.more);
      note.classList.toggle('hidden', !text);
      clamp.check();
    } };
  if (opts.fold && opts.id) {
    const key = 'tto.hist.fold.' + opts.id;
    let kept = null;
    try { kept = localStorage.getItem(key); } catch (e) { kept = null; }
    const btn = h('button', { class: 'iconbtn fold', type: 'button', title: 'Daralt / aç' });
    btn.dataset.fold = opts.id;
    p.fold = (on, remember) => {
      el.classList.toggle('collapsed', on);
      btn.textContent = on ? '▸' : '▾';
      if (remember) try { localStorage.setItem(key, on ? '1' : '0'); } catch (e) { /* not kept */ }
    };
    btn.addEventListener('click', () => p.fold(!el.classList.contains('collapsed'), true));
    head.insertBefore(btn, h2);                      // (in sight: not among the tools that show on hover)
    h2.addEventListener('click', () => { if (el.classList.contains('collapsed')) p.fold(false, true); });
    p.fold(kept === null ? !!opts.folded : kept === '1', false);
  }
  return p;
}

function gridPanel(title, opts = {}) {
  const p = panel(title, opts);
  p.grid = null;
  p.setData = (data) => {
    if (!p.grid) {
      p.grid = new Grid({ data, editable: false, name: opts.id ? 'h/' + opts.id : null, tools: p.tools });
      if (opts.onCell) {
        // a click on a cell: its row and column in ``data`` (header rows counted)
        p.grid.el.classList.add('pickable');
        p.grid.el.addEventListener('click', (e) => {
          if (e.target.closest('button')) return;
          const td = e.target.closest('td');
          if (td && td.__i !== undefined) opts.onCell(td.__i, td.__j);
        });
      }
      p.body.appendChild(p.grid.el);
      const cp = h('button', { class: 'iconbtn', type: 'button', title: 'Tüm tabloyu kopyala (Excel\'e yapıştırılabilir)' }, 'Kopyala');
      cp.addEventListener('click', () => copyGrid(p.grid, false));
      p.tools.appendChild(cp);
    } else {
      p.grid.replace(data);
    }
  };
  return p;
}

function seg(options, value, onChange) {
  const el = h('div', { class: 'seg' });
  const set = (v) => { for (const b of el.children) b.classList.toggle('on', b.dataset.v === String(v)); };
  for (const [v, label, title] of options) {
    const b = h('button', { type: 'button', title: title || null }, label);
    b.dataset.v = String(v);
    b.addEventListener('click', () => { set(v); onChange(v); });
    el.appendChild(b);
  }
  el.set = set;
  set(value);
  return el;
}

/** One line on what the history holds and whether it is being filled right now. */
function stateText(st) {
  if (!st) return '';
  if (st.phase === 'fetch') return 'Kapanışlar çekiliyor…';
  if (st.phase === 'mpc' && st.total) return 'PPK geçmişi hesaplanıyor: ' + st.done + ' / ' + st.total + ' gün';
  const parts = [];
  if (st.last_day) parts.push('son kapanış ' + isoToTr(st.last_day));
  if (st.mpc_days) parts.push('PPK geçmişi ' + st.mpc_days + ' gün');
  if (st.last_sync) parts.push('güncelleme ' + st.last_sync.slice(11, 16));
  if (st.error) parts.push('hata: ' + st.error);
  return parts.join(' · ');
}

/** Shared behaviour: fetch on open, look again when the history changed, poll while it is being filled. */
class HistoryPage {
  constructor(host, ctx) {
    this.host = host;
    this.ctx = ctx;
    this.dead = false;
    this.rev = -1;
    this.data = null;
    this.timer = null;
    this.busy = false;
    this.stateEl = h('span', { class: 'muted hist-state' });
  }

  async load() {
    clear(this.host);
    this.host.appendChild(h('div', { class: 'loading' }, 'Yükleniyor…'));
    const data = await this.fetch();
    if (this.dead) return;
    this.data = data;
    this.rev = data.rev;
    clear(this.host);
    this.build();
    this.render();
    this.showState(data.state);
    this.timer = setInterval(() => { if (this.running) this.refresh().catch(() => {}); }, 4000);
  }

  showState(st) {
    this.running = !!st && st.phase !== 'idle';
    this.stateEl.textContent = stateText(st);
    this.stateEl.classList.toggle('run', this.running);
  }

  /** Called on every market tick: only the (cheap) status is asked unless the history itself moved. */
  async refresh(force) {
    if (this.busy || this.dead) return;
    this.busy = true;
    try {
      const st = await api.get('/api/history/status');
      if (this.dead) return;
      if (force || st.rev !== this.rev) {
        const data = await this.fetch();
        if (this.dead) return;
        this.data = data;
        this.rev = data.rev;
        this.render();
        this.showState(data.state);
      } else {
        this.showState(st);
      }
    } finally {
      this.busy = false;
    }
  }

  destroy() {
    this.dead = true;
    if (this.timer) clearInterval(this.timer);
    if (this.chart) this.chart.destroy();
  }

  focusPanel(id) {
    const el = this.host.querySelector('[data-panel="' + id + '"]');
    if (!el) return false;
    el.scrollIntoView({ block: 'start', behavior: 'smooth' });
    return true;
  }
}

// ====================================================================================== end-of-day matrix
/** Mark a picked row's cells. */
const marked = (cells, on) => (on ? cells.map((c) => Object.assign({}, c, { cls: ((c.cls || '') + ' pick').trim() })) : cells);

export class EodPage extends HistoryPage {
  constructor(host, ctx) {
    super(host, ctx);
    this.asof = null;                      // null: the last close
    this.picked = null;                    // what a click drew: {sid, title} of the history, or {mpc: date, metric}
    this.keys = { curve: [], mpc: [], bonds: [] };
  }

  destroy() {
    super.destroy();
    if (this.sv) this.sv.destroy();
  }

  fetch() {
    return api.get('/api/history/matrix', this.asof ? { asof: this.asof } : null);
  }

  build() {
    this.daySel = h('select', { class: 'inp', title: 'Matrisin tarihi' });
    this.daySel.addEventListener('change', () => {
      this.asof = this.daySel.value || null;
      this.refresh(true).catch(errorToast);
    });
    this.refLine = h('span', { class: 'muted' });
    const now = h('button', { class: 'btn sm', type: 'button', title: 'Kapanışları şimdi güncelle' }, 'Güncelle');
    now.addEventListener('click', async () => {
      try {
        this.showState(await api.post('/api/history/sync', {}));
        this.running = true;
      } catch (err) { errorToast(err); }
    });
    this.host.appendChild(h('div', { class: 'page-tools' }, h('span', { class: 'muted' }, 'Tarih'), this.daySel, this.refLine,
      h('span', { class: 'grow' }), this.stateEl, now));
    this.banner = h('div', { class: 'banner hidden' });
    this.host.appendChild(this.banner);
    // the three tables at their own width: OIS · Offshore beside PPK with DİBS under it - the page on one screen (the desk,
    // 27.11.2026; proposal B19 "Gün Sonu'nda DİBS PPK'nın altına", approved 28.11.2026); their notes two lines, "devamı" the rest
    this.curve = gridPanel('TRY OIS · Offshore — seviye ve değişim', { fit: true, clamp: true, id: 'curve', onCell: (i, j) => this.pickCurve(i, j) });
    this.mpc = gridPanel('PPK fiyatlaması — toplantı bazında', { fit: true, clamp: true, id: 'mpc', onCell: (i, j) => this.pickMpc(i, j) });
    this.bonds = gridPanel('DİBS — getiri ve değişim', { fit: true, clamp: true, id: 'dibs', onCell: (i) => this.pickBond(i) });
    // the series of the row clicked (as on Realized Vol · Carry): level, the window's mean and ±2σ, z day by day
    this.seriesPanel = panel('Seçili seri', { wide: true, clamp: true, id: 'eod-series' });
    const close = h('button', { class: 'iconbtn', type: 'button', title: 'Grafiği kapat' }, '✕');
    close.addEventListener('click', () => { this.picked = null; this.seriesPanel.el.classList.add('hidden'); this.renderTables(); });
    this.seriesPanel.tools.appendChild(close);
    this.sv = new SeriesView(this.seriesPanel.body, { rule: 'macro', prefKey: 'tto.eod.series.window', height: 230 });
    this.seriesPanel.setNote('Bir satıra tıklayınca o serinin geçmişi çizilir: seviye, seçili pencerenin ortalaması ve ±2σ bandı, her günün kendinden önceki pencereye göre '
      + 'z-skoru. Son nokta son kapanış; geçmiş, matrisin okuduğu kapanışlar (ana kaynağın olmadığı gün yedek kaynağın hareketiyle). Yeniden tıklayınca ya da ✕ ile kapanır.');
    this.seriesPanel.el.classList.add('hidden');
    this.host.appendChild(h('div', { class: 'panels' }, this.seriesPanel.el, this.curve.el,
      h('div', { class: 'stack', id: 'eod-stack' }, this.mpc.el, this.bonds.el)));
  }

  /** Draw a history series ({sid, title}) or a meeting's pricing ({mpc, metric, title}); the same again closes it. */
  async pick(what) {
    const same = this.picked && JSON.stringify(this.picked) === JSON.stringify(what);
    if (same && !this.seriesPanel.el.classList.contains('hidden')) {
      this.picked = null;
      this.seriesPanel.el.classList.add('hidden');
      this.renderTables();
      return;
    }
    this.picked = what;
    this.seriesPanel.el.classList.remove('hidden');
    this.renderTables();
    this.seriesPanel.el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    await this.loadPicked(true);
  }

  async loadPicked(fresh) {
    const w = this.picked;
    if (!w || !this.sv) return;
    const seq = (this.pseq = (this.pseq || 0) + 1);
    if (fresh) this.sv.loading(w.title);
    try {
      let spec;
      if (w.mpc) {
        if (!this.mpcData || this.mpcData.rev !== this.rev) this.mpcData = Object.assign(await api.get('/api/history/mpc'), { rev: this.rev });
        const d = this.mpcData;
        const M = METRICS[w.metric];
        const vals = (d.series[w.mpc] || {})[w.metric] || [];
        spec = { title: w.title, points: d.days.map((day, k) => [day, isNum(vals[k]) ? vals[k] * M.scale : null]).filter((p) => isNum(p[1])),
          digits: M.digits, unit: w.metric === 'level' ? '%' : 'bp', note: 'çözücünün o günün OIS kapanışlarıyla verdiği değer',
          why: 'Bu toplantının fiyatlama geçmişi yok' };
      } else {
        const d = await api.get('/api/history/closes', { sid: w.sid });
        const px = d.unit === 'px';
        spec = { title: w.title, points: d.points, digits: 3, unit: px ? 'fiyat' : '%',
          note: d.ticker + ' · ' + d.field + (d.backup_days ? ' · ' + d.backup_days + ' gün yedek kaynaktan' : ''), why: 'Bu serinin kapanışı yok' };
      }
      if (this.dead || seq !== this.pseq) return;
      this.sv.show(spec);
    } catch (err) {
      if (!this.dead && seq === this.pseq) this.sv.show({ title: w.title, points: [], why: (err && err.message) || 'Geçmiş alınamadı' });
    }
  }

  pickCurve(i, j) {
    const k = this.keys.curve[i];
    if (!k) return;
    const side = j >= 5 ? k.off : (j >= 1 ? k.ois : (k.ois || k.off));
    if (side && side.sid) this.pick({ sid: side.sid, title: side.title });
  }

  pickMpc(i, j) {
    const date = this.keys.mpc[i];
    if (!date) return;
    const metric = j >= 9 ? 'cum' : (j >= 5 ? 'level' : 'step');
    this.pick({ mpc: date, metric, title: 'PPK ' + isoToTr(date) + ' · ' + METRICS[metric].label });
  }

  pickBond(i) {
    const k = this.keys.bonds[i];
    if (k && k.sid) this.pick({ sid: k.sid, title: k.title });
  }

  /** The tables again (the picked row marked) without asking for anything. */
  renderTables() {
    if (!this.data) return;
    this.renderCurve(this.data);
    this.renderMpc(this.data);
    this.renderBonds(this.data);
  }

  render() {
    const d = this.data;
    // ---- the day picker
    const want = this.asof || '';
    clear(this.daySel);
    this.daySel.appendChild(h('option', { value: '' }, 'Son kapanış' + (d.days[0] ? ' (' + isoToTr(d.days[0]) + ')' : '')));
    for (const day of d.days.slice(1)) this.daySel.appendChild(h('option', { value: day }, isoToTr(day)));
    if (want && !d.days.includes(want)) this.daySel.appendChild(h('option', { value: want }, isoToTr(want)));
    this.daySel.value = want;
    this.refLine.textContent = isoToTr(d.asof) + ' kapanışı · Δ1G ' + shortDate(d.ref.d1) + ' · Δ1H ' + shortDate(d.ref.w1)
      + ' · Δ1A ' + shortDate(d.ref.m1) + ' kapanışına göre (1 / 5 / 21 iş günü)';

    const notes = [];
    const have = d.curve.filter((r) => r.ois).length, all = d.curve.filter((r) => r.months >= 0.25).length;
    if (!d.live) {
      notes.push('Kayıtlı veri: Excel dosyasının sakladığı geçmiş (' + have + ' OIS vadesi, XCCY 1Y) ve TLREF. Bloomberg bağlıyken '
        + 'tüm vadeler, offshore eğrisi ve DİBS getirileri bir yıl geriye doldurulur.');
    } else if (!d.days.length) {
      notes.push('Henüz kapanış verisi yok – Bloomberg geçmişi çekiliyor.');
    } else if (have < all / 2) {
      notes.push('Bazı serilerde geçmiş yok. Hangi ticker / alanın veri vermediği: Ayarlar → Tarihçe serileri.');
    }
    this.banner.textContent = notes.join(' ');
    this.banner.classList.toggle('hidden', !notes.length);

    this.renderTables();
    if (this.picked) this.loadPicked(false);
  }

  renderCurve(d) {
    const rows = [];
    rows.push([HD('Vade'), HD('TRY OIS · par (%)', { cs: 4 }), SKIP(), SKIP(), SKIP(),
      HD('Offshore · FX swap ima ≤ 9A, XCCY ≥ 1Y (%)', { cs: 4 }), SKIP(), SKIP(), SKIP()]);
    rows.push([HD(''), HD('Son'), HD('Δ1G bp'), HD('Δ1H bp'), HD('Δ1A bp'), HD('Son'), HD('Δ1G bp'), HD('Δ1H bp'), HD('Δ1A bp')]);
    const sides = (list) => {
      const vals = [];
      for (const e of list) if (e) vals.push(e.d1, e.w1, e.m1);
      return scaleOf(vals, 10);
    };
    const so = sides(d.curve.map((r) => r.ois).concat([d.tlref])), sf = sides(d.curve.map((r) => r.off));
    // (``dg``: the level's decimals - TRY rates two, as on the header strip and every other page: the desk, 25.11.2026,
    // and 28.11.2026 for this page, B19 "TRY 2 ondalık")
    const half = (e, scale, dg = TRY_DIGITS) => (e
      ? [N(e.last, dg, { tip: e.ticker + ' · ' + e.field + (e.day ? ' · ' + isoToTr(e.day) : '')
          + (e.backup ? ' · bu günün kapanışı yedek kaynaktan (' + e.backup + '): onun hareketi ana kaynağın seviyesine eklendi' : ''),
        c: e.backup ? 'mute' : undefined }),
        D(e.d1, scale, 1, e.d1_from, d.ref.d1, dg), D(e.w1, scale, 1, e.w1_from, d.ref.w1, dg), D(e.m1, scale, 1, e.m1_from, d.ref.m1, dg)]
      : [EMPTY(), EMPTY(), EMPTY(), EMPTY()]);
    // what a click on a row draws: the OIS side (columns 1-4, the tenor) or the offshore side (5-8)
    const keys = [null, null];
    const pickedSid = this.picked && this.picked.sid;
    const side = (e, title) => (e && e.sid ? { sid: e.sid, title } : null);
    const offName = (r) => (r.off && r.months >= 12 ? 'XCCY ' : 'Offshore ') + r.tenor;
    if (d.tlref) {
      rows.push(marked([TXT('TLREF', { cls: 'lab' })].concat(half(d.tlref, so)), pickedSid && d.tlref.sid === pickedSid).concat(half(null)));
      keys.push({ ois: side(d.tlref, 'TLREF'), off: null });
    }
    for (const r of d.curve) {
      if (!r.ois && !r.off) continue;
      const onOis = !!(pickedSid && r.ois && r.ois.sid === pickedSid), onOff = !!(pickedSid && r.off && r.off.sid === pickedSid);
      rows.push(marked([TXT(r.tenor, { cls: 'lab' })], onOis || onOff).concat(marked(half(r.ois, so), onOis), marked(half(r.off, sf), onOff)));
      keys.push({ ois: side(r.ois, 'TRY OIS ' + r.tenor), off: side(r.off, offName(r)) });
    }
    this.keys.curve = keys;
    this.curve.setData({ sheet: '', rows });
    this.curve.setNote('Kaynak sırası (Ayarlar → Veri kaynakları): OIS ' + d.source.ois + ' · offshore ' + d.source.off + ' · XCCY ' + d.source.xccy
      + '. Ana kaynağın kapanışı olmayan günde sıradaki kaynağın o günkü hareketi ana kaynağın seviyesine eklenir (soluk yazılır). '
      + 'Hücrenin üzerinde durunca önceki kapanış ve kaynak görünür; tıklayınca o tarafın (OIS ya da offshore) geçmişi çizilir.');
  }

  renderMpc(d) {
    const rows = [];
    rows.push([HD('Toplantı'), HD('Fiyatlanan adım (bp)', { cs: 4 }), SKIP(), SKIP(), SKIP(),
      HD('Toplantı sonrası ima TLREF (%)', { cs: 4 }), SKIP(), SKIP(), SKIP(), HD('Kümülatif (bp)', { cs: 2 }), SKIP()]);
    rows.push([HD(''), HD('Son'), HD('Δ1G'), HD('Δ1H'), HD('Δ1A'), HD('Son'), HD('Δ1G bp'), HD('Δ1H bp'), HD('Δ1A bp'), HD('Son'), HD('Δ1G')]);
    const vals = [];
    for (const m of d.mpc) vals.push(m.step.d1, m.step.w1, m.step.m1, m.level.d1, m.level.w1, m.level.m1);
    const sc = scaleOf(vals, 10);
    const keys = [null, null];
    for (const m of d.mpc) {
      const s = m.step, l = m.level, c = m.cum;
      keys.push(m.meeting);
      rows.push(marked([TXT(isoToTr(m.meeting) + (m.front ? ' · ilk' : ''), { cls: 'lab', tip: m.front ? 'İlk toplantı: adım bugünkü TLREF\'e göre ölçülür' : '' }),
        N(s.last, 1), D(s.d1, sc, 1, s.d1_from, d.ref.d1, 1), D(s.w1, sc, 1, s.w1_from, d.ref.w1, 1), D(s.m1, sc, 1, s.m1_from, d.ref.m1, 1),
        N(isNum(l.last) ? l.last * 100 : null, TRY_DIGITS), D(l.d1, sc, 1, isNum(l.d1_from) ? l.d1_from * 100 : null, d.ref.d1, TRY_DIGITS),
        D(l.w1, sc, 1, isNum(l.w1_from) ? l.w1_from * 100 : null, d.ref.w1, TRY_DIGITS),
        D(l.m1, sc, 1, isNum(l.m1_from) ? l.m1_from * 100 : null, d.ref.m1, TRY_DIGITS),
        N(c.last, 1), D(c.d1, sc, 1, c.d1_from, d.ref.d1, 1)], !!(this.picked && this.picked.mpc === m.meeting)));
    }
    this.keys.mpc = keys;
    if (!d.mpc.length) rows.push([TXT('Bu tarih için hesaplanmış PPK fiyatlaması yok' + (d.state && d.state.phase !== 'idle' ? ' – hesaplanıyor…' : ''), { cs: 11 })]
      .concat(Array.from({ length: 10 }, SKIP)));
    this.mpc.setData({ sheet: '', rows });
    this.mpc.setNote((d.decision_day ? 'PPK günü: o günün TLREF fixingi kararı henüz yansıtmadığı için adımlar çözücünün karar sonrası ima ettiği seviyeden ölçülür. ' : '')
      + 'Her gün o günün OIS kapanışlarıyla Excel\'in kendi çözücüsü (Motor · GLOBAL İMA PPK) yeniden çalıştırılır. '
      + 'Satıra tıklayınca o toplantının geçmişi çizilir (adım, seviye ya da kümülatif: tıklanan sütun); hepsi bir arada: PPK Fiyatlama Geçmişi sayfası.');
  }

  renderBonds(d) {
    const rows = [];
    const latest = !d.days.length || d.asof === d.days[0];
    // Bloomberg's name ("TURKIYE GOVERNMENT BOND" down the whole table) only when it tells more than "Tip"; else it is
    // the ISIN's and the Tip's tooltip
    const named = namesTellMore(d.bonds);
    rows.push([HD('ISIN'), named ? HD('Ad') : null, HD('Vade'), HD('Tip', named ? null : { tip: TYPE_TIP }), HD('Son'), HD('Δ1G'), HD('Δ1H'), HD('Δ1A'),
      HD('Son · Δ birimi'), HD('Kapanış'),
      HD('DİBS RV · BIST bileşik %', { tip: 'Excel\'in kendi hesabı (DİBS RV sayfası, şu anki değer) – Bloomberg getirisiyle karşılaştırmak için' })]
      .filter(Boolean));
    const sc = scaleOf(d.bonds.filter((b) => b.unit === 'pct').flatMap((b) => [b.d1, b.w1, b.m1]), 10);
    const sp = scaleOf(d.bonds.filter((b) => b.unit !== 'pct').flatMap((b) => [b.d1, b.w1, b.m1]), 0.25);
    let any = false;
    const keys = [null];
    for (const b of d.bonds) {
      // (a yield a TRY rate: two decimals; a price - a floater's - three, as the bond pages show it)
      const pct = b.unit === 'pct', s = pct ? sc : sp, dg = pct ? 1 : 3, lv = pct ? TRY_DIGITS : 3;
      if (isNum(b.last)) any = true;
      keys.push(b.sid ? { sid: b.sid, title: (b.name || b.isin) + (b.name ? ' (' + b.isin + ')' : '') + (pct ? ' · getiri' : ' · fiyat') } : null);
      const name = named || !b.name ? '' : ' · ' + b.name;
      rows.push(marked([TXT(b.isin, { cls: 'lab', tip: b.ticker + ' · ' + b.field + name }), named ? TXT(b.name) : null, TXT(isoToTr(b.maturity)),
        TXT(b.type, named || !b.name ? null : { tip: b.name }),
        N(b.last, lv), D(b.d1, s, dg, b.d1_from, d.ref.d1, lv), D(b.w1, s, dg, b.w1_from, d.ref.w1, lv), D(b.m1, s, dg, b.m1_from, d.ref.m1, lv),
        TXT(pct ? 'getiri · bp' : 'fiyat · puan', { c: 'mute' }), TXT(isoToTr(b.day), { c: 'mute' }),
        latest && isNum(b.bist) ? N(b.bist * 100, TRY_DIGITS) : EMPTY()].filter(Boolean), !!(this.picked && b.sid && this.picked.sid === b.sid)));
    }
    this.keys.bonds = keys;
    this.bonds.setData({ sheet: '', rows });
    this.bonds.setNote(any
      ? 'Tahviller DİBS RV sayfasındaki listeden; getiri Bloomberg alanı ' + d.source.dibs_field + ' (Ayarlar\'dan değiştirilebilir). Floater\'larda (TLREF: T, FRN: F) fiyat izlenir. '
        + 'Satıra tıklayınca tahvilin geçmişi çizilir.'
      : 'DİBS geçmişi yok' + (d.live ? ': Bloomberg bu alan (' + d.source.dibs_field + ') için geçmiş vermedi – Ayarlar\'dan alanı değiştirin.'
        : ' – Excel dosyası tahvil geçmişi saklamıyor; Bloomberg bağlıyken ' + d.source.dibs_field + ' alanından doldurulur.'));
  }
}

// ====================================================================================== spreads over OIS
const Z_NAMES = { 20: '1A', 60: '3A', 250: '1Y' };

export class SpreadsPage extends HistoryPage {
  constructor(host, ctx) {
    super(host, ctx);
    let w = 60;
    try { w = Number(localStorage.getItem('tto.spreads.window')) || 60; } catch (e) { /* ignore */ }
    this.window = Z_NAMES[w] ? w : 60;
    this.picked = null;                    // the spread drawn: its id ("off:12", "viop:A1Z6 Curncy")
    this.fetched = 0;
  }

  fetch() {
    this.fetched = Date.now();
    return api.get('/api/spreads');
  }

  /** The live points move with the market: look again every 15 seconds, and whenever the history moved. */
  async refresh(force) {
    if (this.busy || this.dead) return;
    if (!force && Date.now() - this.fetched < 15000) return super.refresh(false);
    this.busy = true;
    try {
      const data = await this.fetch();
      if (this.dead) return;
      this.data = data;
      this.rev = data.rev;
      this.render();
      this.showState(data.state);
    } finally {
      this.busy = false;
    }
  }

  build() {
    this.winSeg = seg(Object.keys(Z_NAMES).map((n) => [Number(n), n + ' gün', 'z-skoru, ortalama, σ, aralık ve yüzdelik son ' + n + ' kapanıştan']),
      this.window, (v) => {
        this.window = Number(v);
        try { localStorage.setItem('tto.spreads.window', String(this.window)); } catch (e) { /* ignore */ }
        this.render();
      });
    this.winSeg.id = 'spread-window';
    const now = h('button', { class: 'btn sm', type: 'button', title: 'Kapanışları şimdi güncelle' }, 'Güncelle');
    now.addEventListener('click', async () => {
      try { this.showState(await api.post('/api/history/sync', {})); this.running = true; } catch (err) { errorToast(err); }
    });
    this.host.appendChild(h('div', { class: 'page-tools' }, h('span', { class: 'muted' }, 'İstatistik penceresi'), this.winSeg,
      h('span', { class: 'grow' }), this.stateEl, now));
    this.banner = h('div', { class: 'banner hidden' });
    this.host.appendChild(this.banner);
    this.offPanel = gridPanel('Offshore − OIS · vade bazında (bp)', { wide: true, id: 'spread-off' });
    this.viopPanel = gridPanel('VİOP − OIS · kontrat bazında (bp)', { wide: true, id: 'spread-viop' });
    this.chartPanel = panel('Spread geçmişi', { wide: true, chart: true, id: 'spread-chart' });
    this.chartHost = h('div');
    this.chartPanel.body.appendChild(this.chartHost);
    this.host.appendChild(h('div', { class: 'panels' }, this.chartPanel.el, this.offPanel.el, this.viopPanel.el));
    // a click on a row's tenor / contract draws its spread, as the row's 📈 does (``ids``: the spread of each table row)
    for (const p of [this.offPanel, this.viopPanel]) {
      p.ids = [];
      p.body.addEventListener('click', (e) => {
        const td = e.target.closest('td.chartlink');
        const id = td ? p.ids[td.__i] : null;
        if (id) this.pick(id);
      });
    }
  }

  /** Draw a spread in the chart and bring the chart into view - scrolling the page (the host) up or down only:
   *  scrollIntoView would also move a page wider than the window sideways, its menu out of sight. */
  pick(id) {
    this.picked = id;
    this.render();
    const top = this.chartPanel.el.getBoundingClientRect().top - this.host.getBoundingClientRect().top;
    if (top < 0 || top > this.host.clientHeight - 80) this.host.scrollBy({ top: top - 14, behavior: 'smooth' });
  }

  /** One spread as a row: its level and moves, then where it stands against the window's closes (the drawn one marked). */
  cells(r, sc, first) {
    const b = (r.bands || {})[String(this.window)] || {};
    const zc = isNum(b.z) ? { t: (b.z > 0 ? '+' : '') + num(b.z, 2, false), v: b.z, k: 'n', b: Math.abs(b.z) >= 2 ? 1 : 0,
      heat: heat(b.z, 3), tip: b.n + ' kapanış: ortalama ' + num(b.mean, 1, false) + ' bp, σ ' + num(b.sd, 1, false) + ' bp' } : EMPTY();
    const lv = { t: num(r.level, 1, false), v: r.level, k: 'n', b: 1,
      tip: r.live ? 'Canlı (bugünün kotası)' : isoToTr(r.day) + ' kapanışı (canlı kota yok)', c: r.live ? undefined : 'mute' };
    const pick = { t: '', k: '', cls: 'act', act: { id: 'chart', label: '📈', title: 'Grafikte göster', fn: () => this.pick(r.id) } };
    const out = first.concat([lv, D(r.d1, sc, 1, r.d1_from, r.d1_day, 1), D(r.w1, sc, 1, r.w1_from, r.w1_day, 1), D(r.m1, sc, 1, r.m1_from, r.m1_day, 1),
      N(b.mean, 1), N(b.sd, 1), zc, N(b.min, 1), N(b.max, 1),
      isNum(b.pct) ? { t: '%' + num(b.pct * 100, 0, false), v: b.pct, k: 'n', tip: 'Son ' + b.n + ' kapanışın ne kadarı bugünkünün altında' } : EMPTY(),
      { t: String(r.n), k: 'n', tip: isoToTr(r.first) + ' – ' + isoToTr(r.day) }, pick]);
    if (r.id === this.picked) for (const c of out) c.cls = ((c.cls || '') + ' pick').trim();
    return out;
  }

  render() {
    const d = this.data;
    const W = this.window;
    const tail = ['Spread', 'Δ1G', 'Δ1H', 'Δ1A', 'Ort. ' + W + 'g', 'σ ' + W + 'g', 'z ' + W + 'g', 'Min', 'Maks', 'Yüzdelik', 'Kapanış', ''].map((t) => HD(t));
    const all = d.off.concat(d.viop);
    // the spread drawn: the one picked, else the first with a history
    const row = all.find((r) => r.id === this.picked) || all.find((r) => r.n > 1) || all[0];
    if (row) this.picked = row.id;
    const notes = [];
    if (!all.some((r) => r.n > 1)) {
      notes.push(d.live ? 'Henüz kapanış geçmişi yok – Bloomberg geçmişi çekiliyor ya da bu seriler için geçmiş gelmedi (Ayarlar → Tarihçe serileri).'
        : 'Kayıtlı veri modunda spread geçmişi yok: yalnızca bugünün seviyesi görünür. Bloomberg bağlıyken offshore ve OIS kapanışları bir yıl '
          + 'geriye doldurulur, VİOP geçmişi VİOP sayfasındaki geçmiş tablosundan gelir.');
    }
    this.banner.textContent = notes.join(' ');
    this.banner.classList.toggle('hidden', !notes.length);

    // ---- offshore − OIS
    const so = scaleOf(d.off.flatMap((r) => [r.d1, r.w1, r.m1]), 10);
    const offRows = [[HD('Vade'), HD('Tür'), HD('Offshore %'), HD('OIS %')].concat(tail)];
    for (const r of d.off) {
      offRows.push(this.cells(r, so, [TXT(r.tenor, { cls: 'lab chartlink', b: 1, tip: 'Grafikte göster' }), TXT(r.kind, { c: 'mute' }),
        // (TRY rates in two decimals, as the VİOP table under it)
        N(r.off_now, 2, { tip: 'Offshore ' + r.off_label + ': kullanılan kaynağın bid / ask ortası (Ayarlar → Veri kaynakları)' }),
        N(r.ois_now, 2, { tip: 'TRY OIS ' + r.ois_label + ': kullanılan kaynak' })]));
    }
    if (!d.off.length) offRows.push([TXT('Offshore ve OIS\'in ortak vadesi için ne kapanış ne canlı kota var', { cs: 16 })].concat(Array.from({ length: 15 }, SKIP)));
    this.offPanel.ids = [null].concat(d.off.map((r) => r.id));
    this.offPanel.setData({ sheet: '', rows: offRows });
    this.offPanel.setNote('Offshore: 9 aya kadar FX swap ima getirisi (ICAP), 1 yıldan itibaren XCCY. Kapanışlar Gün Sonu Matrisi\'nin '
      + 'serileridir (kaynak sırası: ' + ((d.history && d.history.source) || 'Ayarlar') + '); spread yalnızca iki eğrinin de kapanışı olan günlerden '
      + 'hesaplanır. Spread sütunu canlıysa bugünün kotası (soluk: son kapanış). z = (spread − ortalama) / σ, son ' + W + ' kapanışa göre.');

    // ---- VİOP − OIS
    const sv = scaleOf(d.viop.flatMap((r) => [r.d1, r.w1, r.m1]), 10);
    const viopRows = [[HD('Kontrat'), HD('Vadeye gün'), HD('VİOP ima %'), HD('OIS %')].concat(tail)];
    for (const r of d.viop) {
      viopRows.push(this.cells(r, sv, [TXT(r.tenor, { cls: 'lab chartlink', b: 1,
        tip: r.ticker + (r.expiry ? ' · vade ' + isoToTr(r.expiry) : '') + ' · grafikte göster' }),
        N(r.to_expiry, 0), N(r.imp_now, 2, { tip: 'Bugünün son fiyatından ima TRY faizi (VİOP sayfasının formülü)' }),
        N(r.ois_now, 2, { tip: 'Aynı güne OIS (ACT/360) – VİOP sayfasının baz formülünün karşılaştırdığı' })]));
    }
    if (!d.viop.length) viopRows.push([TXT('VİOP geçmiş grafiğinde kontrat seçili değil', { cs: 16 })].concat(Array.from({ length: 15 }, SKIP)));
    this.viopPanel.ids = [null].concat(d.viop.map((r) => r.id));
    this.viopPanel.setData({ sheet: '', rows: viopRows });
    this.viopPanel.setNote('Kontratlar ve geçmişin uzunluğu VİOP sayfasındaki VİOP GEÇMİŞİ tablosundan (Çizgi 1–6; Geçmiş '
      + (isNum(d.viop_days) ? num(d.viop_days, 0) + ' iş günü' : '—') + '). Baz: VİOP sayfasının kendi formülü (ima TRY − aynı vadeye OIS, bp); '
      + 'son nokta bugünün canlı son fiyatı.');

    // ---- the chart of the one picked
    this.chartPanel.el.classList.toggle('hidden', !row);
    if (!row) return;
    const name = (row.id.startsWith('viop:') ? 'VİOP ' : 'Offshore ') + row.tenor + ' − OIS';
    const b = (row.bands || {})[String(W)] || {};
    const n = row.days.length;
    const flat = (v) => row.days.map(() => (isNum(v) ? v : null));
    const series = [{ name, kind: 'line', color: '4F81BD', data: row.values, marker: n <= 45 }];
    if (isNum(b.mean) && isNum(b.sd)) {
      series.push({ name: 'Ortalama (' + W + 'g)', kind: 'line', color: '7F7F7F', dash: true, data: flat(b.mean), marker: false });
      series.push({ name: '±2σ', kind: 'line', color: 'F79646', dash: true, data: flat(b.mean + 2 * b.sd), marker: false });
      series.push({ name: '', kind: 'line', color: 'F79646', dash: true, data: flat(b.mean - 2 * b.sd), marker: false, legend: 0 });
    } else if (series.length === 1) {
      series.push({ name: '', kind: 'line', data: row.days.map(() => null), legend: 0 });
    }
    const spec = { title: name, cats: row.days.map(isoToTr), x: { type: 'date', values: row.days.map(serialOf), format: 'mmm yy' },
      auto: 'fit', decimals: 0, y_title: 'bp', aspect: 0.3, series };
    if (this.chart) this.chart.update(spec);
    else this.chart = new Chart(this.chartHost, spec, { height: 300 });
    this.chartPanel.title.textContent = name + ' (bp)' + (n > 1 ? ' · ' + isoToTr(row.days[0]) + ' – ' + isoToTr(row.days[n - 1]) : '');
    this.chartPanel.setNote(isNum(b.z) ? 'Şu an ' + num(row.level, 1, false) + ' bp: son ' + W + ' kapanışın ortalaması ' + num(b.mean, 1, false)
      + ' bp, σ ' + num(b.sd, 1, false) + ' bp → z ' + (b.z > 0 ? '+' : '') + num(b.z, 2, false) + '. Kesikli çizgiler: ortalama ve ±2σ.'
      : 'z-skoru için en az 20 kapanış gerekir. Tabloda vadeye / kontrata (ya da 📈\'e) tıklayınca o spread çizilir.');
  }
}

// ====================================================================================== meeting pricing history
const SLOTS = ['3B83F7', 'DF2A48', '247F50', '9F5EC9', '07A2B0', 'D67A29'];        // one colour family per chart line
const METRICS = {
  step: { label: 'Adım (bp)', title: 'Toplantıda fiyatlanan adım (ilk toplantı: bugünkü TLREF\'e göre)', digits: 1, scale: 1 },
  cum: { label: 'Kümülatif (bp)', title: 'Toplantı sonrası ima seviye − o günün TLREF\'i', digits: 1, scale: 1 },
  level: { label: 'Seviye (%)', title: 'Toplantıdan sonra geçerli ima TLREF', digits: 3, scale: 100 },
};

export class MpcPage extends HistoryPage {
  constructor(host, ctx) {
    super(host, ctx);
    this.metric = 'step';
    this.range = 0;                        // days shown (0: everything)
    this.picked = null;                    // Map: meeting date -> colour slot
  }

  fetch() {
    return api.get('/api/history/mpc');
  }

  build() {
    this.metricSeg = seg(Object.keys(METRICS).map((k) => [k, METRICS[k].label, METRICS[k].title]), this.metric,
      (v) => { this.metric = v; this.render(); });
    this.rangeSeg = seg([[30, '1A'], [91, '3A'], [182, '6A'], [0, '1Y']], this.range, (v) => { this.range = Number(v); this.render(); });
    const now = h('button', { class: 'btn sm', type: 'button', title: 'Kapanışları güncelle ve eksik günleri hesapla' }, 'Güncelle');
    now.addEventListener('click', async () => {
      try { this.showState(await api.post('/api/history/sync', {})); this.running = true; } catch (err) { errorToast(err); }
    });
    this.host.appendChild(h('div', { class: 'page-tools' }, this.metricSeg, this.rangeSeg, h('span', { class: 'grow' }), this.stateEl, now));
    this.banner = h('div', { class: 'banner hidden' });
    this.host.appendChild(this.banner);
    this.chips = h('div', { class: 'chips' });
    this.chartPanel = panel('Toplantı fiyatlaması · zaman serisi', { wide: true, chart: true, id: 'chart' });
    this.chartHost = h('div');
    this.chartPanel.body.appendChild(this.chips);
    this.chartPanel.body.appendChild(this.chartHost);
    this.table = gridPanel('Toplantılar', { wide: true, id: 'meetings' });
    this.daily = gridPanel('Günlük geçmiş', { wide: true, id: 'daily' });
    this.host.appendChild(h('div', { class: 'panels' }, this.chartPanel.el, this.table.el, this.daily.el));
  }

  defaults() {
    const d = this.data;
    const ahead = d.meetings.filter((m) => !m.passed).slice(0, 4);
    const held = d.meetings.filter((m) => m.passed).slice(-1);
    this.picked = new Map();
    held.concat(ahead).forEach((m) => this.picked.set(m.date, this.freeSlot()));
  }

  freeSlot() {
    const used = new Set(this.picked.values());
    for (let k = 0; k < SLOTS.length; k++) if (!used.has(k)) return k;
    return -1;
  }

  toggle(date) {
    if (this.picked.has(date)) {
      this.picked.delete(date);
    } else {
      const slot = this.freeSlot();
      if (slot < 0) { toast('Grafikte en fazla ' + SLOTS.length + ' toplantı gösterilir – önce birini kaldırın', '', 3200); return; }
      this.picked.set(date, slot);
    }
    this.render();
  }

  render() {
    const d = this.data;
    const known = new Set(d.meetings.map((m) => m.date));
    if (!this.picked) this.defaults();
    for (const key of Array.from(this.picked.keys())) if (!known.has(key)) this.picked.delete(key);
    if (!this.picked.size && d.meetings.length) this.defaults();

    const notes = [];
    if (!d.days.length) {
      notes.push(d.state && d.state.phase !== 'idle' ? 'PPK fiyatlama geçmişi hesaplanıyor…' : 'Henüz hesaplanmış gün yok – Güncelle\'ye basın.');
    } else {
      // what the workbook's own status cell said about the days, kind by kind
      const when = (i) => (i.count === d.days.length ? 'Tüm günlerde' : i.count + ' günde');
      const which = (i) => i.days.slice(-8).reverse().map(isoToTr).join(', ') + (i.count > 8 ? ' …' : '');
      for (const i of d.issues || []) {
        if (i.kind === 'inconsistent') {
          notes.push(when(i) + ' çözücü OIS kotalarını tutturamadı' + (isNum(i.control) ? ' (model − kota farkı ' + num(i.control, 1, false) + ' bp\'ye kadar)' : '')
            + ': ' + which(i) + '. Excel\'de "Kota/takvim tutarsız" yazan durumdur; çoğunlukla o günün kapanışlarından biri bayat ya da hatalıdır. '
            + 'Bu günler grafiğe, min / maks\'a ve değişimlere alınmadı; Günlük geçmiş tablosunda ⚠ ile duruyor.');
        } else if (i.kind === 'error') {
          notes.push(when(i) + ' hesap yapılamadı: ' + which(i) + '.');
        } else {
          notes.push(when(i) + ' eksik OIS kotası var (' + i.status + '): ' + (d.live
            ? 'o günlerde bazı vadelerin kapanışı yok; eksik vadelerin ötesindeki toplantılar hesaplanmadı.'
            : 'kayıtlı veride yalnızca 1Y\'ye kadar olan OIS vadeleri var, bu yüzden değerler OIS sayfasındaki tam çözümden birkaç bp farklı olabilir. '
              + 'Bloomberg bağlıyken 16 vadenin tamamı bir yıl geriye kullanılır.'));
        }
      }
      // closes that were not used: they left their neighbours and came back the next day
      const dropped = d.days.map((day, k) => [day, (d.cleaned || [])[k]]).filter((x) => x[1]);
      if (dropped.length) {
        notes.push(dropped.length + ' günde bir vadenin kapanışı kullanılmadı (komşu vadelerden 25 bp\'den fazla ayrılıp ertesi gün geri dönen, '
          + 'yani bayat ya da hatalı kota): ' + dropped.slice(-6).reverse().map((x) => isoToTr(x[0]) + ' ' + x[1]).join('; ')
          + (dropped.length > 6 ? ' …' : '') + '. Yerine vadenin önceki kapanışı, komşularının hareketi kadar kaydırılarak kondu.');
      }
    }
    if (d.notes && d.notes.length) notes.push(d.notes.join(' · '));
    this.banner.textContent = notes.join(' ');
    this.banner.classList.toggle('hidden', !notes.length);

    // ---- which days
    let first = 0;
    if (this.range && d.days.length) {
      const limit = serialOf(d.days[d.days.length - 1]) - this.range;
      first = d.days.findIndex((x) => serialOf(x) >= limit);
      if (first < 0) first = 0;
    }
    const days = d.days.slice(first);
    const M = METRICS[this.metric];
    const col = (date) => (d.series[date] ? d.series[date][this.metric].slice(first).map((v) => (isNum(v) ? v * M.scale : null)) : []);

    // ---- chips: one per meeting, the picked ones carry the colour of their line
    clear(this.chips);
    const group = (title, list) => {
      if (!list.length) return;
      this.chips.appendChild(h('span', { class: 'lbl' }, title));
      for (const m of list) {
        const slot = this.picked.get(m.date);
        const chip = h('button', { class: 'chip' + (slot !== undefined ? ' on' : '') + (m.passed ? ' past' : ''), type: 'button',
          title: (m.label ? m.label + ' · ' : '') + isoToTr(m.date) + (m.passed ? ' · yapıldı' : '') },
        slot !== undefined ? h('i', { style: { background: 'var(--c-' + ['blue', 'red', 'green', 'purple', 'cyan', 'orange'][slot] + ')' } }) : null,
        isoToTr(m.date));
        chip.addEventListener('click', () => this.toggle(m.date));
        this.chips.appendChild(chip);
      }
    };
    group('Yapılan', d.meetings.filter((m) => m.passed));
    group('Gelecek', d.meetings.filter((m) => !m.passed));

    // ---- chart
    const lines = d.meetings.filter((m) => this.picked.has(m.date));
    // a short window is labelled day by day (dd.mm), a long one by the month ticks of the date axis
    const brief = days.length > 1 && serialOf(days[days.length - 1]) - serialOf(days[0]) < 300;
    const spec = { title: 'PPK fiyatlaması', cats: days.map(brief ? shortDate : isoToTr), x: { type: 'date', values: days.map(serialOf), format: 'mmm yy' },
      auto: 'fit', decimals: this.metric === 'level' ? 2 : 0, y_title: M.label, aspect: 0.3,
      series: lines.map((m) => ({ name: isoToTr(m.date) + (m.passed ? ' (yapıldı)' : ''), kind: 'line', color: SLOTS[this.picked.get(m.date)],
        data: col(m.date), marker: days.length <= 45 })) };
    if (lines.length === 1) spec.series.push({ name: '', kind: 'line', data: days.map(() => null), legend: 0 });   // keep the legend
    if (this.chart) this.chart.update(spec);
    else this.chart = new Chart(this.chartHost, spec, { height: 320 });
    this.chartPanel.title.textContent = 'Toplantı fiyatlaması · ' + M.label + (days.length ? ' · ' + isoToTr(days[0]) + ' – ' + isoToTr(days[days.length - 1]) : '');
    this.chartPanel.setNote(M.title + '. Her nokta o günün OIS kapanışlarıyla (kaynak: ' + d.source + ') Excel çözücüsünün verdiği değerdir; '
      + 'seri toplantının tarihine bağlıdır, toplantı listesi kaydırılsa da kopmaz. Yapılan toplantıların serisi toplantıdan önceki son iş gününde biter.');

    this.renderMeetings(d);
    this.renderDaily(d, days, first);
  }

  renderMeetings(d) {
    const rows = [[HD('Toplantı'), HD('Durum'), HD('Adım bp'), HD('Δ1G'), HD('Δ1H'), HD('Δ1A'), HD('Min'), HD('Max'), HD('Seviye %'),
      HD('Kümülatif bp'), HD('± bp'), HD('Gün'), HD('İlk'), HD('Son'), HD('Gerçekleşen bp'), HD('Sürpriz bp')]];
    const sc = scaleOf(d.meetings.flatMap((m) => [m.d1, m.w1, m.m1]), 10);
    const today = serialOf(d.today);
    const line = (m) => {
      const left = serialOf(m.date) - today;
      const status = m.passed ? TXT('yapıldı', { c: 'mute' }) : TXT((m.label ? m.label + ' · ' : '') + left + ' gün', {});
      return [TXT(isoToTr(m.date), { cls: 'lab' }), status, N(m.last.step, 1, m.passed ? { tip: 'Toplantıdan önceki son fiyatlama (' + isoToTr(m.last_day) + ')' } : null),
        m.passed ? EMPTY() : D(m.d1, sc, 1), m.passed ? EMPTY() : D(m.w1, sc, 1), m.passed ? EMPTY() : D(m.m1, sc, 1),
        N(m.min, 1), N(m.max, 1), N(isNum(m.last.level) ? m.last.level * 100 : null, 3), N(m.last.cum, 1), N(m.last.sigma, 1),
        N(m.n, 0), TXT(isoToTr(m.first_day), { c: 'mute' }), TXT(isoToTr(m.last_day), { c: 'mute' }),
        m.passed ? N(m.realized, 1, { tip: 'TLREF: toplantıdan sonraki ilk fixing − toplantı günü fixingi' }) : EMPTY(),
        m.passed ? D(m.surprise, 50, 1) : EMPTY()];
    };
    const ahead = d.meetings.filter((m) => !m.passed), held = d.meetings.filter((m) => m.passed);
    for (const m of ahead) rows.push(line(m));
    if (held.length) {
      rows.push([TXT('Yapılan toplantılar · toplantı öncesi son fiyatlama ve gerçekleşen TLREF değişimi', { cs: 16, b: 1, f: 'sub' })]
        .concat(Array.from({ length: 15 }, SKIP)));
      for (const m of held.slice().reverse()) rows.push(line(m));
    }
    if (rows.length === 1) rows.push([TXT('Veri yok', { cs: 16 })].concat(Array.from({ length: 15 }, SKIP)));
    this.table.setData({ sheet: '', rows });
    this.table.setNote('Δ1G / Δ1H / Δ1A: fiyatlanan adımın 1 / 5 / 21 iş günü önceye göre değişimi. Gerçekleşen: TLREF\'in toplantı ertesindeki değişimi; '
      + 'sürpriz = gerçekleşen − toplantı öncesi fiyatlanan adım.');
  }

  renderDaily(d, days, first) {
    const M = METRICS[this.metric];
    const cols = d.meetings.filter((m) => this.picked.has(m.date) || !m.passed).slice(0, 14);
    const rows = [[HD('Tarih'), HD('TLREF %'), HD('Kota'), HD('Durum')].concat(cols.map((m) => HD(isoToTr(m.date))))];
    const decisions = new Set(d.decision_days || []);
    const flags = d.flags || [], control = d.control || [], carried = d.carried || [], flagged = d.flagged || {};
    const cleaned = d.cleaned || [];
    const quoteTip = (k) => {
      const parts = [];
      if (carried[k]) parts.push(carried[k] + ' vadede o günün kapanışı kullanılmadı: önceki kapanış, komşu vadelerin hareketi kadar kaydırıldı');
      if (cleaned[k]) parts.push('ayıklanan kapanış: ' + cleaned[k]);
      return parts.length ? { tip: parts.join(' · ') } : null;
    };
    const state = (k) => {
      const check = isNum(control[k]) ? 'model − kota farkı en çok ' + num(control[k], 2, false) + ' bp' : '';
      if (flags[k] === 'inconsistent') return TXT('⚠ tutarsız', { c: 'mute', tip: 'Çözücü kotaları tutturamadı' + (check ? ' (' + check + ')' : '') + ': değerler güvenilir değil, grafikte yok' });
      if (flags[k] === 'error') return TXT('⚠ hata', { c: 'mute', tip: 'Bu gün hesaplanamadı' });
      if (flags[k] === 'missing') return TXT('eksik', { c: 'mute', tip: 'Bazı OIS vadelerinin kapanışı yok' + (check ? ' · ' + check : '') });
      return TXT(isNum(control[k]) ? 'OK' : '', { c: 'mute', tip: check });
    };
    for (let i = days.length - 1; i >= 0; i--) {
      const k = first + i;
      const mark = decisions.has(days[i]);
      const off = flagged[days[i]];                    // a day the solver does not stand behind: its values, greyed
      rows.push([TXT(isoToTr(days[i]) + (mark ? ' · PPK' : ''), { cls: 'lab', tip: mark
        ? 'PPK günü: TLREF fixingi kararı ertesi gün yansıtır; o gün adımlar çözücünün karar sonrası ima ettiği seviyeden ölçülür' : '' }),
      N(d.tlref[k], 2), N(d.quotes[k], 0, quoteTip(k)), state(k)].concat(cols.map((m) => {
        if (off) {
          const w = off[m.date] ? off[m.date][this.metric] : null;
          return N(isNum(w) ? w * M.scale : null, M.digits, { c: 'mute', tip: 'Çözücü bu gün kotaları tutturamadı: güvenilir değil' });
        }
        const v = d.series[m.date] ? d.series[m.date][this.metric][k] : null;
        return N(isNum(v) ? v * M.scale : null, M.digits);
      })));
    }
    this.daily.title.textContent = 'Günlük geçmiş · ' + M.label;
    this.daily.setData({ sheet: '', rows });
    this.daily.setNote('Kota: o gün çözücüye giren OIS vadesi sayısı (üzerine gelince kaçının o günün kendi kapanışı olmadığı). Durum: Excel\'deki '
      + 'çözücü durumu (OIS · PPK sayfası, "Durum" hücresi); ⚠ işaretli günlerin değerleri gri yazılır ve grafikte yer almaz. '
      + 'Tabloyu Kopyala ile Excel\'e alabilirsiniz.');
  }
}

// ====================================================================================== settings
// the holiday lists of the settings page: what each one is for (a tab's tooltip), its word in "152 TR tatili", where it
// is written
const HOL_ABOUT = {
  TRY: 'TRY tatilleri: TRY kitabının bütün WORKDAY hesapları (para piyasası, tahvil, VİOP, OIS, toplantı takvimi), FX valörlerinin TRY tarafı '
    + 've BIST swap\'ın T+1 valörü',
  USD: 'USD tatilleri: New York\'ta FX takası olmayan günler (Fed tatilleri; Good Friday iş günü) - USDTRY ve EURUSD valörleri',
  EUR: 'EUR tatilleri: TARGET2\'nin kapalı olduğu günler - EURTRY ve EURUSD valörleri',
};
const HOL_WORD = { TRY: 'TR', USD: 'USD', EUR: 'EUR' };
/** The settings page's panels, as its jump bar names them (data-panel ids; ``#/settings?p=<id>`` opens one). */
export const SETTINGS_JUMPS = [['interp', 'Eğri interpolasyonu'], ['curvepoints', 'Eğri noktaları'], ['carry', 'Carry'],
  ['sources', 'Veri kaynakları'], ['sources-used', 'Kullanılan kaynak'], ['calendar', 'PPK takvimi'], ['holidays', 'Tatiller'],
  ['history', 'Tarihçe'], ['series', 'Tarihçe serileri']];
const HOL_WHERE = { TRY: 'Yazıldığı kitaplar: ', USD: 'Yazıldığı yer: ', EUR: 'Yazıldığı yer: ' };

export class SettingsPage {
  constructor(host, ctx) {
    this.host = host;
    this.ctx = ctx;
    this.dead = false;
    this.rows = [];                        // [{date, was}] the list as edited
    this.dirty = false;
    this.cal = null;
    this.timer = null;
  }

  async load() {
    clear(this.host);
    this.host.appendChild(h('div', { class: 'loading' }, 'Yükleniyor…'));
    const [cal, cov, src, carry, hol, interp, points] = await Promise.all([api.get('/api/calendar'), api.get('/api/history/series'), api.get('/api/sources'),
      api.get('/api/carry').catch(() => ({ available: false })), api.get('/api/holidays').catch(() => ({ available: false })),
      api.get('/api/interp').catch(() => ({ available: false })), api.get('/api/curve-points').catch(() => ({ available: false }))]);
    if (this.dead) return;
    this.cal = cal;
    this.cov = cov;
    this.src = src;
    this.carry = carry;
    this.hol = hol;
    this.interp = interp;
    this.points = points;
    this.holCcy = 'TRY';
    this.holEdits = {};                    // currency -> the list as typed and not saved yet (kept while another is shown)
    this.rows = cal.meetings.map((m) => ({ date: m.date, was: m.date }));
    this.dirty = false;
    clear(this.host);
    this.build();
    this.renderInterp();
    this.renderPoints();
    this.renderCarry();
    this.renderSources(true);
    this.renderCalendar();
    this.renderHolidays(true);
    this.renderHistory();
    this.syncJumps();
    this.timer = setInterval(() => { this.pollState().catch(() => {}); }, 4000);
  }

  /** A market tick: the calendar is only reloaded when nothing is being edited. */
  async refresh() {
    if (this.dead) return;
    if (this.srcPanel) {
      const src = await api.get('/api/sources');
      if (this.dead) return;
      this.src = src;
      this.renderSources(false);
    }
    if (this.cpPanel && this.points && this.points.available && !this.cpBusy && !this.cpForm.contains(document.activeElement)) {
      const points = await api.get('/api/curve-points').catch(() => null);      // (the points' values now)
      if (this.dead) return;
      if (points && !this.cpBusy && !this.cpForm.contains(document.activeElement)) {
        this.points = points;
        this.renderPoints();
      }
    }
    if (!this.dirty) {
      const cal = await api.get('/api/calendar');
      if (this.dead || this.dirty) return;
      const same = JSON.stringify(cal.meetings) === JSON.stringify(this.cal.meetings) && cal.spot === this.cal.spot;
      this.cal = cal;
      if (!same) {
        this.rows = cal.meetings.map((m) => ({ date: m.date, was: m.date }));
        this.renderCalendar();
      }
    }
    await this.pollState();
  }

  async pollState() {
    if (this.dead) return;
    const st = await api.get('/api/history/status');
    if (this.dead) return;
    const moved = !this.cov || st.rev !== this.cov.state.rev;
    if (moved) this.cov = await api.get('/api/history/series');
    else this.cov.state = st;
    if (!this.dead) this.renderHistory();
  }

  destroy() {
    this.dead = true;
    if (this.timer) clearInterval(this.timer);
  }

  build() {
    // ---- the TRY curves between their quoted tenors: Bootstrap (Murex) or PPK basamak - one's own choice
    this.interpPanel = panel('Eğri interpolasyonu · kotalı vadeler arası (kişisel)', { wide: true, id: 'interp' });
    this.interpSeg = h('div', { class: 'seg', id: 'interp-mode', role: 'group', 'aria-label': 'Eğri interpolasyonu' });
    this.interpInfo = h('div', { class: 'set-info', id: 'interp-info' });
    this.interpPanel.body.appendChild(h('div', { class: 'set-body' }, this.interpInfo,
      h('div', { class: 'carry-actions' }, h('div', { class: 'field' }, h('label', null, 'Eğri'), this.interpSeg))));
    this.interpPanel.setNote('Kotalı vadelerde iki yöntem aynıdır; fark aralarındadır (FRA, kırık tarih, çeyrek arası). PPK basamak seçilince '
      + 'bütün sayfalar (OIS, Masa, Forward, DV01, DİBS RV / ASW, Carry …), offshore eğri ve Trades\'in MTM / kupon / K/Z\'si bu eğriyle '
      + 'hesaplanır; üst şeritte "Eğri: PPK basamak" yazar. Motor\'un düğümleri (1-3 ay, sonra çeyreklik) PPK eğrisinde, aralarında ln DF '
      + 'günlere göre doğrusal: çeyrek içindeki bir tarih her toplantı basamağını değil iki düğümü görür - günlük tam PPK değerleri PPK '
      + 'sütunlarında (OIS · PPK FRA listeleri, Masa kırık vade, Günlük İşlemler FRA). Offshore eğride her toplantıda düğüm vardır. '
      + 'Bootstrap\'ta kalanlar: Günlük İşlemler ve masanın kayıtları, MTM yenile / kapanış kayıtlarının Bootstrap\'ı (ikisi de alınır), '
      + 'hedef / stop alarmları, quant, tarihçe, başkalarının ekranları. Ayar yalnız sizin için geçerlidir; "Girdilerimi sıfırla" '
      + 'Bootstrap\'a döndürür.');

    // ---- the desk's list of curve points: what each TRY curve is built from (everyone sees it, administrators change it)
    this.cpPanel = panel('Eğri noktaları · OIS ve offshore (masanın listesi)', { wide: true, id: 'curvepoints' });
    this.cpInfo = h('div', { class: 'set-info', id: 'cp-info' });
    this.cpReset = h('button', { class: 'btn', type: 'button', id: 'cp-reset',
      title: 'Varsayılan noktalar açılır, eklenenler kapanır (listede notlarıyla kalır): herkesin eğrisi bugünkü gibi olur' }, 'Varsayılana dön');
    this.cpReset.addEventListener('click', () => this.resetPoints());
    this.cpShowPpk = h('input', { type: 'checkbox', id: 'cp-show-ppk' });
    this.cpShowPpk.checked = true;
    this.cpShowPpk.addEventListener('change', () => this.renderPoints());
    this.cpTables = h('div', { class: 'cp-tables', id: 'cp-tables' });
    this.cpForm = h('div', { class: 'cp-form', id: 'cp-form' });
    this.cpLog = h('div', { class: 'cp-log', id: 'cp-log' });
    this.cpPanel.body.appendChild(h('div', { class: 'set-body' }, this.cpInfo,
      h('div', { class: 'set-actions' }, h('label', { class: 'cp-check' }, this.cpShowPpk, ' PPK toplantılarını göster'),
        h('span', { class: 'grow' }), this.cpReset),
      this.cpTables, this.cpForm, this.cpLog));
    this.cpPanel.setNote('Eğrilerin kurulduğu noktalar masanın ortak listesidir: herkes görür, yalnız yöneticiler değiştirir (herkesin eğrisi '
      + 'değişir), her değişiklik kayda geçer. Liste varsayılandayken (bugünkü kotalar: OIS_MAIN\'in kotalı vadeleri; Forward\'ın TRYI 1W … 9M '
      + 've TRYSAQ 1 … 10 satırları) her sayfa çalışma kitabının kendi formülleriyle hesaplanır. Liste farklıyken iki yöntem de listedeki '
      + 'noktalardan kurulur: Bootstrap - OIS\'te Motor\'un yöntemiyle (noktaların par faizi aylara göre doğrusal, Motor\'un çeyreklik '
      + 'düğümlerinde bootstrap), offshore\'da her nokta bir düğüm (ln DF günlere göre doğrusal); PPK basamak - MPC ima patikası, bütün '
      + 'noktalara aynen oturur. PPK toplantıları her zaman listededir (takvimden; PPK basamak orada basamaklanır, takvim değişince '
      + 'kendiliğinden). Kapatılan nokta notuyla listede kalır, eğri onun üzerinden interpolasyon yapar. Hesaplanan nokta eğriye bilgi '
      + 'eklemez: eğrinin o vadedeki par ve sıfır kupon faizidir (sizin interpolasyon ayarınızla; 18M XCCY 6A + 12A kuponla - EK_FX\'in '
      + '18M\'i bunu kullanır). Bloomberg ticker\'lı nokta yeni bir canlı aboneliktir: eklemeden önce maliyeti söylenir ve onay istenir. '
      + 'DİBS ASW listeyi izlemez (kendi kotaları ve günlük geçmişi var).');

    // ---- the carry: which TLREF path, over which horizons
    this.carryPanel = panel('Carry · TLREF patikası ve ufuklar', { wide: true, id: 'carry' });
    this.carryPath = h('select', { class: 'inp', id: 'carry-path' });
    this.carryA = h('input', { class: 'inp num', type: 'text', id: 'carry-a', style: { width: '60px' } });
    this.carryB = h('input', { class: 'inp num', type: 'text', id: 'carry-b', style: { width: '60px' } });
    this.carryInfo = h('div', { class: 'set-info', id: 'carry-info' });
    const carrySave = h('button', { class: 'btn primary', type: 'button', id: 'carry-save' }, 'Kaydet');
    carrySave.addEventListener('click', () => this.saveCarry());
    for (const inp of [this.carryA, this.carryB]) inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') this.saveCarry(); });
    this.carryPanel.body.appendChild(h('div', { class: 'set-body' }, this.carryInfo,
      h('div', { class: 'carry-actions' },
        h('div', { class: 'field' }, h('label', null, 'TLREF patikası'), this.carryPath),
        h('div', { class: 'field' }, h('label', null, 'Ufuk A (ay)'), this.carryA),
        h('div', { class: 'field' }, h('label', null, 'Ufuk B (ay)'), this.carryB),
        h('span', { class: 'grow' }), carrySave)));
    this.carryPanel.setNote('Carry = sabit bacağın ufka kadar tahakkuku − TLREF\'in ufka kadar bileşiği (iş günü; ufuktan önce ödenen kupon da bu '
      + 'patikayla taşınır). Bootstrap: piyasa OIS eğrisinin ima ettiği TLREF (varsayılan) · MPC ima: kotaların ima ettiği PPK patikası · S1 – S3: OIS '
      + 'sayfasındaki senaryolar · Sabit TLREF: bugünkü TLREF. Roll eğriyi bugünkü haliyle tutar. Carry & Roll ve Realized Vol · Carry sayfaları bu '
      + 'ayarla hesaplanır; ayar yalnız sizin için geçerlidir (ufuklar OIS sayfasındaki "Ufuk A / B ay" girdileridir).');

    // ---- the order of the pricing sources
    this.srcPanel = panel('Veri kaynakları · Bloomberg fiyat kaynağı sırası', { wide: true, id: 'sources' });
    this.srcTable = h('table', { class: 'src-table', id: 'sources-table' });
    this.srcSave = h('button', { class: 'btn primary', type: 'button', id: 'sources-save' }, 'Kaydet');
    this.srcSave.addEventListener('click', () => this.saveSources());
    const srcReset = h('button', { class: 'btn', type: 'button', id: 'sources-default',
      title: 'OIS: GFOF · offshore: ICPL · XCCY: ICPL (sonra Excel\'deki BGN ticker\'ı)' }, 'Varsayılana dön');
    srcReset.addEventListener('click', () => {
      for (const c of this.src.curves) {
        const inputs = this.srcTable.querySelectorAll('input[data-curve="' + c.id + '"]');
        inputs.forEach((inp, k) => { inp.value = c.default[k] || ''; });
      }
      this.srcDirty = true;
      this.srcSave.disabled = false;
    });
    this.srcPanel.body.appendChild(h('div', { class: 'set-body' },
      this.srcTable,
      h('div', { class: 'src-actions' }, h('span', { class: 'grow' }), srcReset, this.srcSave)));
    this.srcPanel.setNote('Her eğri için soldan sağa denenir: fiyatı olan ilk kaynak kullanılır, en sonda her zaman Excel\'deki ticker (BGN). '
      + 'Kaynak kodu Bloomberg\'in fiyat kaynağıdır (GFOF, ICPL, BGN, CMPN, TRPU …): ticker kök + kaynak + Curncy olarak sorulur. OIS\'te önce MID, yoksa PX_LAST; '
      + 'offshore ve XCCY\'de bid ve ask\'in ikisi de olan kaynak alınır. Değişiklik herkes için ve hem canlı sayfalarda hem tarihçede geçerlidir.');
    // (a long reference list: folded until opened - each user's own choice kept)
    this.usedPanel = gridPanel('Şu an kullanılan kaynak · her vade için', { wide: true, id: 'sources-used', fold: true, folded: true });

    // ---- calendar
    this.calPanel = panel('PPK toplantı takvimi', { wide: true, id: 'calendar' });
    this.calInfo = h('div', { class: 'set-info' });
    this.calTable = h('table', { class: 'set-table' });
    this.saveBtn = h('button', { class: 'btn primary', type: 'button' }, 'Kaydet');
    this.saveBtn.addEventListener('click', () => this.save(false));
    this.undoBtn = h('button', { class: 'btn', type: 'button' }, 'Vazgeç');
    this.undoBtn.addEventListener('click', () => {
      this.rows = this.cal.meetings.map((m) => ({ date: m.date, was: m.date }));
      this.dirty = false;
      this.renderCalendar();
    });
    const add = h('button', { class: 'btn', type: 'button' }, '+ Toplantı ekle');
    add.addEventListener('click', () => {
      const last = this.rows.length ? this.rows[this.rows.length - 1].date : this.cal.today;
      const next = new Date(Date.parse((last || this.cal.today) + 'T00:00:00Z') + 42 * 86400000).toISOString().slice(0, 10);
      this.rows.push({ date: next, was: null });
      this.dirty = true;
      this.renderCalendar();
      const inputs = this.calTable.querySelectorAll('input.date');
      if (inputs.length) { inputs[inputs.length - 1].focus(); inputs[inputs.length - 1].select(); }
    });
    const paste = h('button', { class: 'btn', type: 'button',
      title: 'Excel\'den kopyalanan tarih sütununu yapıştır: açıklanan tarihlerle düzelt, listeye ekle ya da gelecek toplantıların yerine koy' },
    'Toplu yapıştır…');
    paste.addEventListener('click', () => this.bulk());
    const copy = h('button', { class: 'btn', type: 'button', title: 'Tablodaki tarihleri (gg.aa.yyyy, her satıra bir tane) Excel\'e yapıştırmak için kopyala' },
      'Kopyala');
    copy.addEventListener('click', () => {
      const dates = this.dates().slice().sort();
      copyText(dates.map(isoToTr).join('\n'), 'Takvim kopyalandı (' + dates.length + ' tarih)');
    });
    this.rollBtn = h('button', { class: 'btn', type: 'button',
      title: 'Geçen toplantıları OIS sayfasındaki listeden arşive al; liste sıradaki toplantıdan başlar. Senaryo adımları toplantılarıyla birlikte kayar. '
        + 'Dashboard bunu açılışta ve gün dönünce kendiliğinden de yapar.' },
    'Geçen toplantıları arşivle');
    this.rollBtn.addEventListener('click', () => this.roll());
    this.calPanel.body.appendChild(h('div', { class: 'set-body' }, this.calInfo,
      h('div', { class: 'set-actions' }, add, paste, copy, this.rollBtn, h('span', { class: 'grow' }), this.undoBtn, this.saveBtn),
      h('div', { class: 'set-scroll' }, this.calTable)));
    this.calPanel.setNote('Toplantı tarihleri herkes için ortaktır ve OIS · PPK sayfasındaki listeyle (OIS_MAIN!P10:P89) aynıdır. Bir tarih değiştiğinde ya da '
      + 'liste kaydırıldığında bir toplantıya yazılmış her şey toplantısıyla birlikte taşınır: herkesin senaryo adımları (U:W), kayıtlı '
      + 'senaryoları, etiketi (O), elle değerleri, Motor\'un toplantı başına girdileri, o hücrelere başvuran formüller ve alarmlar. '
      + 'Listeden çıkan toplantının değerleri silinmez, kenara alınır; tarih geri eklenirse geri gelir. '
      + 'PPK fiyatlama geçmişi yeni takvimle arka planda yeniden hesaplanır. Bir toplantı geçince (tarihi OIS spot valöründen önce '
      + 'kalınca) liste açılışta ve gün dönünce kendiliğinden kayar: MPC1 her zaman sıradaki toplantıdır. Açıklanan yeni tarihler '
      + '"Toplu yapıştır… → Açıklanan tarihlerle düzelt" ile tek seferde girilir.');

    // ---- the holidays: a list per currency - TRY (both TRY workbooks), USD and EUR (the FX value dates) -, edited one at a
    //      time; the USD workbook's SIFMA holidays and FOMC meetings beside them, read only
    this.holPanel = panel('Tatiller · TRY · USD · EUR · SIFMA · FOMC', { wide: true, id: 'holidays' });
    this.holTabs = h('div', { class: 'seg small', id: 'holidays-ccy' });
    this.holPanel.tools.appendChild(this.holTabs);
    this.holInfo = h('div', { class: 'set-info', id: 'holidays-info' });
    this.holText = h('textarea', { class: 'inp hol-text', id: 'holidays-text', rows: '14', spellcheck: 'false', wrap: 'off' });
    this.holText.addEventListener('input', () => {
      this.holEdits[this.holCcy] = this.holText.value;
      this.holSave.disabled = false;
    });
    this.holSave = h('button', { class: 'btn primary', type: 'button', id: 'holidays-save' }, 'Kaydet');
    this.holSave.addEventListener('click', () => this.saveHolidays());
    const holUndo = h('button', { class: 'btn', type: 'button', id: 'holidays-undo' }, 'Vazgeç');
    holUndo.addEventListener('click', () => this.renderHolidays(true));
    const holCopy = h('button', { class: 'btn', type: 'button', title: 'Listeyi (gg.aa.yyyy ve adı, sekmeyle) Excel\'e yapıştırmak için kopyala' }, 'Kopyala');
    holCopy.addEventListener('click', () => copyText(this.holText.value, this.holCcy + ' tatilleri kopyalandı'));
    this.holOther = h('div', { class: 'hol-other', id: 'holidays-other' });
    // (the USD workbook's SIFMA holidays and FOMC meetings, read only: folded until opened)
    this.holOtherFold = h('details', { class: 'hol-fold', id: 'holidays-other-fold' },
      h('summary', null, 'SIFMA tatilleri ve FOMC toplantıları', h('span', { class: 'muted' }, ' · USD · FOMC sayfasının, salt okunur')), this.holOther);
    this.holPanel.body.appendChild(h('div', { class: 'set-body' }, this.holInfo, this.holText,
      h('div', { class: 'set-actions' }, holCopy, h('span', { class: 'grow' }), holUndo, this.holSave), this.holOtherFold));
    this.holPanel.setNote('Her satıra bir gün: tarih (gg.aa.yyyy) ve isterseniz adı - Excel\'den iki sütun yapıştırılabilir. Listeler herkes için '
      + 'ortaktır; sekmeden seçilir, her biri ayrı kaydedilir. TRY: üç kitaba birden yazılır - TRY kitabının tatilleri (Motor!A361:B523; bütün '
      + 'WORKDAY hesapları: para piyasası, tahvil, VİOP, OIS, kontrat vadeleri), DİBS ASW kitabınınki (ASW!LR2:LR200) ve Borsa Swap\'ınki '
      + '(EK_TATIL!A5:A204: BIST swap\'ın T+1 valörü); arife yarım günleri iş '
      + 'günü sayılır (listeye yazılmaz). USD (New York, Fed tatilleri) ve EUR (TARGET2): FX valörleri paritenin iki para biriminin tatilini de atlar - '
      + 'USDTRY spot bugünden 1, EURTRY 2 iş günü sonrası; vadeler ikisinin de açık olduğu güne kayar (EK_TATIL sayfası). SIFMA tatilleri '
      + '(SOFR / USD OIS) ve FOMC toplantıları USD · FOMC sayfasındadır; burada bilgi için gösterilir.');

    // ---- history
    this.histPanel = panel('Tarihçe', { wide: true, id: 'history' });
    this.histInfo = h('div', { class: 'set-info' });
    this.fieldInp = h('input', { class: 'inp', type: 'text', style: { width: '170px' }, spellcheck: 'false' });
    this.daysInp = h('input', { class: 'inp num', type: 'text', style: { width: '80px' } });
    const saveSet = h('button', { class: 'btn', type: 'button' }, 'Kaydet');
    saveSet.addEventListener('click', async () => {
      try {
        await api.post('/api/history/settings', { dibs_field: this.fieldInp.value, lookback_days: this.daysInp.value });
        toast('Kaydedildi – tarihçe güncelleniyor', 'ok');
        this.cov = await api.get('/api/history/series');
        this.renderHistory(true);
      } catch (err) { errorToast(err); }
    });
    const sync = h('button', { class: 'btn', type: 'button' }, 'Şimdi güncelle');
    sync.addEventListener('click', () => this.sync(false));
    const redo = h('button', { class: 'btn', type: 'button', title: 'Her günü Excel çözücüsüyle baştan hesapla' }, 'PPK geçmişini yeniden hesapla');
    redo.addEventListener('click', async () => {
      const ok = await confirmDialog('PPK geçmişini yeniden hesapla',
        'Saklanan her gün için çözücü yeniden çalıştırılır (gün başına birkaç saniye, arka planda). Devam edilsin mi?', 'Yeniden hesapla');
      if (ok) this.sync(true);
    });
    this.histPanel.body.appendChild(h('div', { class: 'set-body' }, this.histInfo,
      h('div', { class: 'set-actions' },
        h('div', { class: 'field' }, h('label', null, 'DİBS getiri alanı (Bloomberg)'), this.fieldInp),
        h('div', { class: 'field' }, h('label', null, 'Geriye bakış (gün)'), this.daysInp),
        saveSet, h('span', { class: 'grow' }), sync, redo)));
    this.seriesPanel = gridPanel('Tarihçe serileri · neyin geçmişi var', { wide: true, id: 'series', fold: true, folded: true });
    // a chip per panel over the page: a click brings it into view (a folded one opened) - as "#/settings?p=calendar" does
    this.folds = { 'sources-used': this.usedPanel, series: this.seriesPanel };
    this.jumps = h('div', { class: 'chips set-jump', id: 'settings-jump', role: 'navigation', 'aria-label': 'Ayarlar bölümleri' });
    for (const [id, label] of SETTINGS_JUMPS) {
      const b = h('button', { class: 'chip', type: 'button', title: label + ' bölümüne git' }, label);
      b.dataset.p = id;
      b.addEventListener('click', () => this.focusPanel(id));
      this.jumps.appendChild(b);
    }
    this.host.insertBefore(this.jumps, this.host.firstChild);
    this.host.appendChild(h('div', { class: 'panels set-panels' }, this.interpPanel.el, this.cpPanel.el, this.carryPanel.el, this.srcPanel.el, this.usedPanel.el,
      this.calPanel.el, this.holPanel.el, this.histPanel.el, this.seriesPanel.el));
  }

  /** Bring a panel into view (``#/settings?p=calendar``, a chip of the bar): a folded one is opened, a moment marked. */
  focusPanel(id) {
    const p = this.folds && this.folds[id];
    if (p && p.el.classList.contains('collapsed')) p.fold(false, true);
    const el = this.host.querySelector('[data-panel="' + id + '"]');
    if (!el || el.classList.contains('hidden')) return false;
    el.scrollIntoView({ block: 'start', behavior: 'smooth' });
    el.classList.remove('focus');
    void el.offsetWidth;
    el.classList.add('focus');
    return true;
  }

  /** A chip goes with its panel (Eğri noktaları on a dashboard without the curve points). */
  syncJumps() {
    if (!this.jumps) return;
    for (const b of this.jumps.children) {
      const el = this.host.querySelector('[data-panel="' + b.dataset.p + '"]');
      b.classList.toggle('hidden', !el || el.classList.contains('hidden'));
    }
  }

  // ------------------------------------------------------------------ the desk's list of curve points
  renderPoints() {
    const d = this.points;
    if (!d || !d.available) {
      this.cpPanel.el.classList.add('hidden');
      return;
    }
    const edit = !!d.can_edit;
    const custom = d.curves.filter((c) => c.custom);
    clear(this.cpInfo).append(...[                 // (DOM append writes a null as the text "null": the parts there are)
      custom.length
        ? h('span', { id: 'cp-status', class: 'cp-differs' }, 'Liste varsayılandan farklı: '
          + custom.map((c) => c.title + ' – ' + c.differs.join(', ')).join(' · '))
        : h('span', { id: 'cp-status' }, 'Liste varsayılan: eğriler çalışma kitabının kendi kotalarıyla (bugünkü gibi).'),
      h('span', { class: 'muted' }, 'Hesaplanan noktalar sizin ayarınızla: ', h('b', null, d.mode_text)),
      edit ? null : h('span', { class: 'muted' }, 'Listeyi yalnız yöneticiler değiştirir (herkesin eğrisi değişir).'),
      d.errors && d.errors.length ? h('span', { class: 'warn-text', id: 'cp-errors' }, 'Listenin eğrisi kurulamadı - çalışma kitabının kendi '
        + 'eğrisi kullanılıyor: ' + d.errors.join('; ')) : null].filter(Boolean));
    this.cpReset.classList.toggle('hidden', !edit);
    this.cpReset.disabled = !custom.length;
    const showPpk = this.cpShowPpk.checked;
    clear(this.cpTables);
    for (const c of d.curves) {
      const table = h('table', { class: 'cp-table', id: 'cp-table-' + c.id });      // (not .set-table: the calendar's own)
      table.appendChild(h('thead', null, h('tr', null, ...['Vade / tarih', 'Gün', 'Tür', 'Kaynak', 'Son değer', 'Not', 'Ekleyen · tarih', 'Açık']
        .map((t) => h('th', null, t)))));
      const body = h('tbody');
      for (const r of c.rows) {
        if (r.ppk && !showPpk) continue;
        body.appendChild(this.pointRow(r, edit));
      }
      table.appendChild(body);
      this.cpTables.appendChild(h('div', { class: 'cp-curve' },
        h('div', { class: 'cp-head' }, h('b', null, c.title), h('span', { class: 'muted' }, ' · spot ' + (c.spot || '') + ' · gün spot\'tan'),
          c.custom ? h('span', { class: 'cp-tag' }, 'listeden') : null),
        h('div', { class: 'set-scroll cp-scroll' }, table)));
    }
    this.renderPointForm(d, edit);
    clear(this.cpLog);
    if (d.log && d.log.length) {
      this.cpLog.appendChild(h('div', { class: 'cp-log-head' }, 'Değişiklik kaydı'));
      for (const e of d.log.slice(0, 12)) {
        this.cpLog.appendChild(h('div', { class: 'cp-log-line' }, h('span', { class: 'muted' }, (e.at || '').slice(0, 16) + ' · ' + (e.who || e.by || '') + ' · '),
          e.text || ''));
      }
    }
  }

  pointRow(r, edit) {
    const value = () => {
      if (r.ppk) return '';
      if (r.computed) {
        return r.value === null || r.value === undefined ? (r.on ? 'eğri okunamadı' : '')
          : 'par ' + pct(r.value, 4) + ' · sıfır ' + pct(r.zero, 4);
      }
      if (r.error && r.on) return r.error;
      return pct(r.value, 4);
    };
    const valueTip = r.computed && typeof r.df === 'number'
      ? 'DF ' + num(r.df, 9) + (r.schedule ? ' · kuponlar ' + r.schedule : '') + ' (' + (this.points.mode_text || '') + ')'
      : (r.schedule ? 'kuponlar ' + r.schedule : '');
    const cls = (r.ppk ? 'cp-ppk' : '') + (r.on ? '' : ' cp-off') + (r.computed ? ' cp-calc' : '');
    const valueCell = h('td', { class: 'num', title: valueTip }, value());
    if (edit && r.source === 'typed' && !r.ppk) {
      const b = h('button', { class: 'iconbtn cp-rate', type: 'button', 'data-id': r.id, title: 'Oranı değiştir' }, '✎');
      b.addEventListener('click', () => this.editPoint(r, 'rate'));
      valueCell.appendChild(b);
    }
    const noteCell = h('td', { class: 'cp-note-cell', title: r.note_tip || '' }, r.note || '');
    if (edit && !r.ppk) {
      const b = h('button', { class: 'iconbtn cp-note', type: 'button', 'data-id': r.id, title: 'Notu değiştir' }, '✎');
      b.addEventListener('click', () => this.editPoint(r, 'note'));
      noteCell.appendChild(b);
    }
    let onCell;
    if (r.ppk) {
      onCell = h('td', { class: 'muted', title: 'PPK toplantıları listeden çıkmaz: takvimden gelir' }, 'her zaman');
    } else if (edit) {
      const box = h('input', { type: 'checkbox', class: 'cp-on', 'data-id': r.id });
      box.checked = !!r.on;
      box.addEventListener('change', () => this.pointAction({ action: box.checked ? 'on' : 'off', id: r.id }, box));
      onCell = h('td', null, box);
    } else {
      onCell = h('td', null, r.on ? '✓' : '–');
    }
    const who = r.ppk ? 'takvimden' : (r.default ? 'varsayılan' : [r.added_by, (r.added_at || '').slice(0, 16)].filter(Boolean).join(' · '));
    const whoTip = r.changed_at && !r.ppk ? 'Son değişiklik: ' + [r.changed_by, r.changed_at].filter(Boolean).join(' · ') : '';
    return h('tr', { class: cls.trim(), 'data-id': r.id },
      h('td', { title: r.date ? 'Vade: ' + r.date : '' }, r.when || r.name || ''),
      h('td', { class: 'num' }, typeof r.day === 'number' ? String(Math.round(r.day)) : ''),
      h('td', { title: r.rule || '' }, r.kind_text || ''),
      h('td', { title: r.source_tip || '' }, r.source === 'ticker' && r.ticker ? 'Bloomberg · ' + r.ticker : (r.source_text || '')),
      valueCell, noteCell, h('td', { class: 'muted', title: whoTip }, who), onCell);
  }

  /** The administrator's form to add a point: made once (a market tick redraws the tables, never what is being typed). */
  renderPointForm(d, edit) {
    if (this.cpFormFor === edit) return;
    this.cpFormFor = edit;
    clear(this.cpForm);
    if (!edit) return;
    const curve = h('select', { class: 'inp', id: 'cp-add-curve' }, ...d.curves.map((c) => h('option', { value: c.id }, c.title)));
    const kind = h('select', { class: 'inp', id: 'cp-add-kind' });
    const when = h('input', { class: 'inp', type: 'text', id: 'cp-add-when', placeholder: '18M, 2Y3M ya da gg.aa.yyyy', style: { width: '150px' } });
    const source = h('select', { class: 'inp', id: 'cp-add-source' }, ...d.sources.map((s) => h('option', { value: s.id }, s.label)));
    const rate = h('input', { class: 'inp num', type: 'text', id: 'cp-add-rate', placeholder: '%, ör. 41,25', style: { width: '90px' } });
    const ticker = h('input', { class: 'inp', type: 'text', id: 'cp-add-ticker', placeholder: 'ör. TRYSAQ1H ICPL Curncy', style: { width: '190px' } });
    const note = h('input', { class: 'inp', type: 'text', id: 'cp-add-note', placeholder: 'ne olduğu', maxlength: '300', style: { width: '240px' } });
    const add = h('button', { class: 'btn primary', type: 'button', id: 'cp-add' }, 'Nokta ekle');
    const rateField = h('div', { class: 'field' }, h('label', null, 'Oran %'), rate);
    const tickerField = h('div', { class: 'field' }, h('label', null, 'Bloomberg ticker'), ticker);
    const rule = h('div', { class: 'muted cp-rule', id: 'cp-add-rule' });
    const kinds = () => {
      const keep = kind.value;
      clear(kind);
      for (const k of d.kinds) if (k.curves.includes(curve.value)) kind.appendChild(h('option', { value: k.id }, k.label));
      if ([...kind.options].some((o) => o.value === keep)) kind.value = keep;
      const k = d.kinds.find((x) => x.id === kind.value);
      rule.textContent = k ? k.label + ': ' + k.rule : '';
    };
    const sources = () => {
      rateField.classList.toggle('hidden', source.value !== 'typed');
      tickerField.classList.toggle('hidden', source.value !== 'ticker');
    };
    curve.addEventListener('change', kinds);
    kind.addEventListener('change', kinds);
    source.addEventListener('change', sources);
    kinds();
    sources();
    add.addEventListener('click', () => this.pointAction({ action: 'add', curve: curve.value, kind: kind.value, when: when.value, source: source.value,
      rate: rate.value, ticker: ticker.value, note: note.value }, add).then((ok) => {
      if (ok) { when.value = ''; rate.value = ''; ticker.value = ''; note.value = ''; }
    }));
    this.cpForm.append(h('div', { class: 'carry-actions' },
      h('div', { class: 'field' }, h('label', null, 'Eğri'), curve),
      h('div', { class: 'field' }, h('label', null, 'Vade / tarih'), when),
      h('div', { class: 'field' }, h('label', null, 'Tür'), kind),
      h('div', { class: 'field' }, h('label', null, 'Kaynak'), source),
      rateField, tickerField,
      h('div', { class: 'field' }, h('label', null, 'Not'), note), add), rule);
  }

  /** A change of the list (an administrator's): a ticker point asks for its cost to be confirmed first. */
  async pointAction(body, ctl) {
    if (this.cpBusy) return false;
    this.cpBusy = true;
    if (ctl) ctl.disabled = true;
    try {
      let res = await api.post('/api/curve-points', body);
      if (res.needs_confirm) {
        const ok = await confirmDialog('Bloomberg: yeni canlı ticker', (res.ticker ? res.ticker + ' · ' : '') + res.cost + ' Onaylıyor musunuz?',
          'Onayla');
        if (!ok) {
          this.renderPoints();
          return false;
        }
        res = await api.post('/api/curve-points', Object.assign({}, body, { confirm: true }));
      }
      this.points = res;
      this.renderPoints();
      if (res.done) toast(res.done, 'ok', 4200);
      if (this.ctx.refreshNow) this.ctx.refreshNow();
      return true;
    } catch (err) {
      errorToast(err);
      this.renderPoints();
      return false;
    } finally {
      this.cpBusy = false;
      if (ctl) ctl.disabled = false;
    }
  }

  editPoint(r, what) {
    const m = modal({ title: (what === 'rate' ? 'Oran · ' : 'Not · ') + (r.name || r.when), width: 440 });
    const input = h('input', { class: 'inp', id: 'cp-edit-input', style: { width: '100%' }, maxlength: '300',
      value: what === 'rate' ? (typeof r.rate === 'number' ? num(r.rate * 100, 4, false) : '') : (r.note || '') });
    const save = () => {
      m.close();
      this.pointAction(what === 'rate' ? { action: 'rate', id: r.id, rate: input.value } : { action: 'note', id: r.id, note: input.value });
    };
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') save(); });
    m.body.appendChild(h('div', { class: 'field' }, h('label', null, what === 'rate' ? 'Oran (%)' : 'Not (ne olduğu)'), input));
    m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Vazgeç'));
    m.foot.appendChild(h('button', { class: 'btn primary', type: 'button', id: 'cp-edit-save', onclick: save }, 'Kaydet'));
    input.focus();
    input.select();
  }

  async resetPoints() {
    const ok = await confirmDialog('Eğri noktaları · varsayılana dön',
      'Varsayılan noktalar açılır, eklenen noktalar kapanır (listede notlarıyla kalır). Herkesin eğrisi bugünkü kotalarla kurulur. Devam edilsin mi?',
      'Varsayılana dön');
    if (ok) await this.pointAction({ action: 'reset' }, this.cpReset);
  }

  renderInterp() {
    const d = this.interp;
    if (!d || !d.available) {
      this.interpPanel.el.classList.add('hidden');
      return;
    }
    clear(this.interpSeg);
    for (const c of d.choices) {
      const b = h('button', { type: 'button', class: c.id === d.mode ? 'on' : '', title: c.about, 'data-mode': c.id },
        c.label + (c.id === d.default ? ' (varsayılan)' : ''));
      b.addEventListener('click', () => this.saveInterp(c.id));
      this.interpSeg.appendChild(b);
    }
    const st = d.stats || {};
    clear(this.interpInfo).append(...[h('span', null, 'Şu an: ', h('b', { id: 'interp-status' }, d.status || '')),
      d.mode === 'ppk' && st.last_ms !== null && st.last_ms !== undefined
        ? h('span', { class: 'muted' }, 'PPK eğrisi son ' + (st.at || '') + ' hesaplandı (' + st.last_ms + ' ms) · PPK\'daki kullanıcı: ' + (st.users || 0))
        : null].filter(Boolean));
  }

  async saveInterp(mode) {
    if (this.interp && this.interp.mode === mode) return;
    for (const b of this.interpSeg.children) b.disabled = true;
    try {
      this.interp = await api.post('/api/interp', { mode });
      this.renderInterp();
      toast(mode === 'ppk' ? 'Eğri: PPK basamak – sayfalar ve Trades bu eğriyle (yalnız sizde)' : 'Eğri: Bootstrap (Murex)', 'ok', 3600);
      if (this.ctx.refreshNow) this.ctx.refreshNow();
    } catch (err) {
      errorToast(err);
      this.renderInterp();
    }
  }

  renderCarry() {
    const c = this.carry;
    if (!c || !c.available) {
      this.carryPanel.el.classList.add('hidden');
      return;
    }
    clear(this.carryPath);
    for (const o of c.options) {
      const opt = h('option', { value: o.id, title: o.about }, o.label + (o.id === c.default ? ' (varsayılan)' : ''));
      if (o.id === c.path) opt.selected = true;
      this.carryPath.appendChild(opt);
    }
    this.carryA.value = c.a !== null && c.a !== undefined ? String(c.a) : '';
    this.carryB.value = c.b !== null && c.b !== undefined ? String(c.b) : '';
    const hz = c.horizons || {};
    const end = (k) => (hz[k] && hz[k].date ? isoToTr(hz[k].date) : '–');
    this.carryInfo.textContent = 'Şu an: ' + (c.about || c.path) + ' · Ufuk A sonu ' + end('a') + ', Ufuk B sonu ' + end('b');
  }

  async saveCarry() {
    try {
      this.carry = await api.post('/api/carry', { path: this.carryPath.value, a: this.carryA.value, b: this.carryB.value });
      this.renderCarry();
      toast('Carry ayarı kaydedildi', 'ok');
    } catch (err) { errorToast(err); }
  }

  renderSources(force) {
    const src = this.src;
    if (!src || !src.available) {
      clear(this.srcTable).appendChild(h('tr', null, h('td', null, 'Bu dosyada kaynak sayfası yok (EK_KAYNAK) – Excel\'deki ticker\'lar kullanılıyor.')));
      this.srcSave.disabled = true;
      return;
    }
    if (force || !this.srcDirty) {
      const t = clear(this.srcTable);
      t.appendChild(h('tr', null, h('th', null, 'Eğri'), h('th', null, '1. kaynak'), h('th', null, '2. kaynak'), h('th', null, '3. kaynak'),
        h('th', null, '4. kaynak'), h('th', null, 'Son yedek (her zaman)')));
      for (const c of src.curves) {
        const cells = [h('td', null, h('b', null, c.title))];
        for (let k = 0; k < 4; k++) {
          const inp = h('input', { class: 'inp src', type: 'text', spellcheck: 'false', maxlength: '8', 'data-curve': c.id,
            placeholder: k === 0 ? 'kaynak' : '', value: c.sources[k] || '', title: 'Bloomberg fiyat kaynağı kodu (boş = yok)' });
          inp.addEventListener('input', () => { this.srcDirty = true; this.srcSave.disabled = false; });
          inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') this.saveSources(); });
          cells.push(h('td', null, inp));
        }
        cells.push(h('td', { class: 'muted' }, c.fallback));
        t.appendChild(h('tr', null, ...cells));
      }
      this.srcDirty = false;
      this.srcSave.disabled = true;
    }
    const names = Object.fromEntries(src.curves.map((c) => [c.id, c.title]));
    const rows = [[HD('Eğri'), HD('Vade'), HD('Kullanılan kaynak'), HD('Ticker'), HD('Değer · bid'), HD('Ask'), HD('Excel\'deki ticker')]];
    for (const r of src.rows) {
      const fallback = !(r.rank >= 1 && r.rank <= 4);
      rows.push([TXT(names[r.curve] || r.curve), TXT(r.tenor, { cls: 'lab' }),
        TXT(r.source, { c: fallback ? 'mute' : 'pos', tip: fallback ? 'Listedeki kaynakların hiçbiri fiyat vermedi: Excel\'deki ticker' : r.rank + '. kaynak' }),
        TXT(r.ticker), isNum(r.bid) ? N(r.bid, 4) : TXT(typeof r.bid === 'string' ? r.bid : '', { c: 'mute' }),
        isNum(r.ask) ? N(r.ask, 4) : TXT(typeof r.ask === 'string' ? r.ask : '', { c: 'mute' }), TXT(r.excel, { c: 'mute' })]);
    }
    this.usedPanel.setData({ sheet: '', rows });
    this.usedPanel.setNote(src.live ? 'Canlı: kaynak yanıt verene kadar (Requesting) sıradaki kaynak görünür. OIS değeri yüzde, offshore ve XCCY bid / ask.'
      : 'Kayıtlı veri: Excel dosyasında ICAP (ICPL) kotası olmadığı için offshore satırları Excel\'deki ticker\'ı gösterir; sayfalardaki değerler dosyanınkidir.');
  }

  async saveSources() {
    const lists = {};
    for (const c of this.src.curves) {
      lists[c.id] = [...this.srcTable.querySelectorAll('input[data-curve="' + c.id + '"]')].map((i) => i.value.trim()).filter(Boolean);
    }
    try {
      this.src = await api.post('/api/sources', { lists });
      this.srcDirty = false;
      this.renderSources(true);
      toast('Kaynak sırası kaydedildi – canlı sayfalar ve tarihçe yeni sırayla güncelleniyor', 'ok');
    } catch (err) { errorToast(err); }
  }

  /** The holiday lists of the answer: one per currency (an older answer had the TRY list alone). */
  holLists() {
    const d = this.hol;
    return d.lists || { TRY: { items: d.tr, slots: d.slots, books: d.books } };
  }

  /** ``force``: the shown list as it is saved (what was typed into it and not saved is dropped). */
  renderHolidays(force) {
    const d = this.hol;
    if (!d || !d.available) {
      this.holPanel.el.classList.add('hidden');
      return;
    }
    const lists = this.holLists();
    if (!lists[this.holCcy]) this.holCcy = 'TRY';
    const ccy = this.holCcy;
    const cur = lists[ccy];
    if (force) delete this.holEdits[ccy];
    const typed = this.holEdits[ccy];
    this.holText.value = typed !== undefined ? typed : cur.items.map((x) => isoToTr(x.date) + (x.name ? '\t' + x.name : '')).join('\n');
    this.holSave.disabled = typed === undefined;
    clear(this.holTabs);
    for (const c of Object.keys(lists)) {
      // (a list typed into and not saved yet keeps a mark on its tab)
      const b = h('button', { type: 'button', class: c === ccy ? 'on' : '', 'data-ccy': c, title: HOL_ABOUT[c] || '' },
        c + (c !== ccy && this.holEdits[c] !== undefined ? ' •' : ''));
      b.addEventListener('click', () => {
        if (c === this.holCcy) return;
        this.holCcy = c;
        this.renderHolidays(false);
      });
      this.holTabs.appendChild(b);
    }
    const next = cur.items.find((x) => x.date >= (this.cal && this.cal.today ? this.cal.today : ''));
    // the list opens at its next holiday (the years before it are history; USD and EUR start in 2020)
    this.holText.scrollTop = typed === undefined && next
      ? Math.max(0, cur.items.indexOf(next) - 1) * (this.holText.scrollHeight / Math.max(1, cur.items.length)) : 0;
    const books = (cur.books || []).map((b) => (b === 'asw' ? 'DİBS ASW' : b === 'borsa' ? 'Borsa Swap'
      : ccy === 'TRY' ? 'TRY (Motor)' : 'EK_TATIL (TRY kitabı)'));
    clear(this.holInfo).append(h('span', null, h('b', null, String(cur.items.length)), ' ' + (HOL_WORD[ccy] || ccy) + ' tatili (en çok ' + cur.slots + ')'),
      h('span', null, 'Sıradaki: ', h('b', null, next ? isoToTr(next.date) + (next.name ? ' · ' + next.name : '') : '–')),
      h('span', null, (HOL_WHERE[ccy] || 'Yazıldığı yer: ') + books.join(' · ')));
    const chips = (list) => (list.length ? list.map(isoToTr).join(', ') : '–');
    clear(this.holOther).append(h('div', null, h('b', null, 'ABD tatilleri (SIFMA · SOFR / USD OIS, salt okunur): '), chips(d.us)),
      h('div', null, h('b', null, 'FOMC toplantıları: '), chips(d.fomc)));
  }

  async saveHolidays() {
    const ccy = this.holCcy;
    const items = [];
    const bad = [];
    for (const line of this.holText.value.split(/\r?\n/)) {
      const s = line.trim();
      if (!s) continue;
      const m = /^(\S+)\s*(.*)$/.exec(s);
      const iso = parseTrDate(m[1]);
      if (!iso) { bad.push(m[1]); continue; }
      items.push({ date: iso, name: m[2].trim() });
    }
    if (bad.length) {
      toast('Tarih anlaşılamadı: ' + bad.slice(0, 5).join(', '), 'err', 6000);
      return;
    }
    try {
      this.hol = await api.post('/api/holidays', { ccy, items });
      this.holCcy = ccy;
      this.renderHolidays(true);
      toast(ccy + ' tatilleri kaydedildi: ' + this.holLists()[ccy].items.length + ' gün'
        + (ccy === 'TRY' ? ' (TRY ve DİBS ASW kitapları)' : ' (FX valörleri)'), 'ok');
    } catch (err) { errorToast(err); }
  }

  renderCalendar() {
    const cal = this.cal;
    const spot = cal.spot;
    const inList = cal.meetings.filter((m) => m.where === 'list').length;
    clear(this.calInfo);
    this.calInfo.appendChild(h('span', null, 'Bugün ', h('b', null, isoToTr(cal.today)), ' · OIS spot ', h('b', null, isoToTr(spot)),
      ' · sıradaki toplantı ', h('b', null, cal.next ? isoToTr(cal.next) : '—'), ' · listede ', h('b', null, String(inList)), ' / ' + cal.slots + ' toplantı',
      cal.passed_in_list ? h('span', { class: 'warn-text' }, ' · ' + cal.passed_in_list + ' toplantı geçti, hâlâ listede') : null));
    const auto = cal.autoroll;
    if (auto && auto.rolled && auto.rolled.length) {
      this.calInfo.appendChild(h('span', { class: 'muted' }, 'Son otomatik kaydırma: ' + auto.rolled.map(isoToTr).join(', ')
        + ' arşive alındı, MPC1 ' + isoToTr(auto.first) + ' (' + isoToTr(auto.at.slice(0, 10)) + ' ' + auto.at.slice(11, 16) + ')'));
    }
    if (cal.autoroll_error) this.calInfo.appendChild(h('span', { class: 'warn-text' }, 'Otomatik kaydırma yapılamadı: ' + cal.autoroll_error));
    if (cal.parked && cal.parked.length) {
      this.calInfo.appendChild(h('span', { class: 'muted', id: 'calendar-parked' }, 'Kenarda: ' + cal.parked.length + ' toplantının değerleri ('
        + cal.parked.slice(0, 4).map(isoToTr).join(', ') + (cal.parked.length > 4 ? ' …' : '') + ') - tarih geri eklenirse geri gelir'));
    }
    if (this.dirty) {
      // a new calendar makes every day of the meeting pricing history compute again: one save, one recalculation
      this.calInfo.appendChild(h('span', { class: 'warn-text' }, 'Kaydedince PPK fiyatlama geçmişi yeni takvimle arka planda yeniden hesaplanır'
        + (cal.history_days ? ' (~' + cal.history_days + ' gün)' : '') + ' – düzeltmeleri tek kayıtta yapın'));
    }
    this.rollBtn.disabled = !cal.passed_in_list || this.dirty;
    this.saveBtn.disabled = !this.dirty;
    this.undoBtn.disabled = !this.dirty;

    const info = new Map(cal.meetings.map((m) => [m.date, m]));
    const scroller = this.calTable.parentNode;
    const keep = this.calBuilt ? scroller.scrollTop : null;
    const t = clear(this.calTable);
    t.appendChild(h('tr', null, h('th', null, '#'), h('th', null, 'Tarih'), h('th', null, 'Gün'), h('th', null, 'Durum'), h('th', null, 'Yer'), h('th', null, '')));
    const sorted = this.rows.slice().sort((a, b) => (a.date < b.date ? -1 : a.date > b.date ? 1 : 0));
    let k = 0;
    const dayNames = ['Paz', 'Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt'];
    for (const row of sorted) {
      const m = row.was ? info.get(row.was) : null;
      const passed = row.date < spot;
      if (!passed) k += 1;
      const inp = h('input', { type: 'text', class: 'inp date', value: isoToTr(row.date), placeholder: 'gg.aa.yyyy', spellcheck: 'false',
        autocomplete: 'off' });
      inp.dataset.date = row.date;
      const commit = () => {
        const iso = parseTrDate(inp.value);
        if (!iso) { inp.classList.add('bad'); toast('Tarih anlaşılamadı: ' + inp.value + ' (gg.aa.yyyy)', 'err'); return; }
        if (iso === row.date) { inp.value = isoToTr(iso); inp.classList.remove('bad'); return; }
        row.date = iso;
        this.dirty = true;
        this.renderCalendar();
      };
      inp.addEventListener('change', commit);
      inp.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); inp.blur(); } });
      const del = h('button', { class: 'iconbtn', type: 'button', title: 'Toplantıyı listeden çıkar' }, '✕');
      del.addEventListener('click', () => {
        this.rows.splice(this.rows.indexOf(row), 1);
        this.dirty = true;
        this.renderCalendar();
      });
      const changed = row.was !== row.date;
      const wd = new Date(Date.parse(row.date + 'T00:00:00Z')).getUTCDay();
      t.appendChild(h('tr', { class: (passed ? 'past' : '') + (changed ? ' changed' : '') },
        h('td', { class: 'n' }, passed ? '' : String(k)),
        h('td', null, inp),
        h('td', { class: wd === 0 || wd === 6 ? 'warn-text' : 'muted' }, dayNames[wd]),
        h('td', null, passed ? 'geçti' : (Math.round((Date.parse(row.date) - Date.parse(cal.today)) / 86400000) + ' gün')),
        h('td', { class: 'muted' }, !row.was ? 'yeni' : (m && m.where === 'list' ? 'OIS listesi · ' + m.label + ' (P' + m.row + ')' : 'arşiv')
          + (changed && row.was ? ' · önce ' + isoToTr(row.was) : '')),
        h('td', null, del)));
    }
    // first time: start at the next meeting (the meetings that were held are above it)
    if (keep !== null) {
      scroller.scrollTop = keep;
    } else {
      const next = t.querySelector('tr:not(.past) td');
      if (next) scroller.scrollTop = Math.max(0, next.parentNode.offsetTop - 64);
      this.calBuilt = true;
    }
  }

  dates() {
    return this.rows.map((r) => r.date);
  }

  async save(roll) {
    const seen = new Set();
    for (const d of this.dates()) {
      if (seen.has(d)) { toast('Aynı tarih iki kez girilmiş: ' + isoToTr(d), 'err'); return; }
      seen.add(d);
    }
    // meetings of the OIS list taken out (✕, "yerine koy"): asked first - what was typed for them is set aside
    const kept = new Set(this.rows.map((r) => r.was).filter(Boolean));
    const out = this.cal.meetings.filter((m) => m.where === 'list' && !m.passed && !kept.has(m.date)).map((m) => m.date);
    if (!roll && out.length) {
      const list = out.slice(0, 6).map(isoToTr).join(', ') + (out.length > 6 ? ' …' : '');
      const ok = await confirmDialog('Toplantı listeden çıkıyor',
        out.length + ' toplantı OIS listesinden çıkacak (' + list + '). Onlara yazılmış her şey - herkesin senaryo adımları, kayıtlı '
        + 'senaryolardaki değerleri, etiketleri, elle değerleri - kenara alınır; tarih yeniden eklenirse geri gelir. '
        + 'Bu tarihe başvuran formüller #REF! olur.', 'Çıkar ve kaydet', true);
      if (!ok) return;
    }
    try {
      const res = await api.post('/api/calendar', { dates: this.dates(), roll: !!roll, version: this.cal.version });
      const bits = [res.meetings + ' toplantı listede', res.archive + ' arşivde'];
      if (res.rolled && res.rolled.length) bits.push(res.rolled.length + ' geçen toplantı arşive alındı');
      if (res.note) bits.push(res.note);
      toast('Takvim kaydedildi: ' + bits.join(' · '), 'ok', res.note ? 12000 : 6000);
      this.dirty = false;
      this.cal = await api.get('/api/calendar');
      this.rows = this.cal.meetings.map((m) => ({ date: m.date, was: m.date }));
      this.renderCalendar();
      this.ctx.refreshNow();
    } catch (err) {
      errorToast(err);
      if (err && err.status === 409) {
        // saved over a calendar that changed meanwhile: refused - the page shows the calendar as it is now
        this.cal = await api.get('/api/calendar');
        this.rows = this.cal.meetings.map((m) => ({ date: m.date, was: m.date }));
        this.dirty = false;
        this.renderCalendar();
      }
    }
  }

  async roll() {
    const n = this.cal.passed_in_list;
    const ok = await confirmDialog('Geçen toplantıları arşivle',
      n + ' toplantı geçti. Bunlar OIS sayfasındaki listeden arşive alınır ve liste ' + (this.cal.next ? isoToTr(this.cal.next) : 'sıradaki')
      + ' toplantısından başlar (MPC1). Her kullanıcının senaryo adımları ve kayıtlı senaryoları toplantılarıyla birlikte kaydırılır; '
      + 'geçmiş fiyatlama serileri etkilenmez.', 'Arşivle');
    if (ok) this.save(true);
  }

  /** Paste a column of dates.  The server works out what it does to the list being edited (the same pairing that
   * saving uses to carry the steps with their meetings); the table shows it, nothing is kept until "Kaydet". */
  bulk() {
    const m = modal({ title: 'Toplantı tarihlerini yapıştır', width: 520 });
    const area = h('textarea', { class: 'inp', rows: '12', style: { width: '100%', fontFamily: 'var(--mono)' },
      placeholder: '14.01.2027\n11.03.2027\n22.04.2027\n…' });
    const mode = h('select', { class: 'inp' },
      h('option', { value: 'correct' }, 'Açıklanan tarihlerle düzelt (diğerleri kalır)'),
      h('option', { value: 'merge' }, 'Listeye ekle'),
      h('option', { value: 'future' }, 'Gelecek toplantıların yerine koy'));
    const hints = {
      correct: 'Her tarih, bugünden sonraki toplantılardan en çok 45 gün uzaktaki en yakınının tarihini düzeltir (sıra korunur, tarihler '
        + 'olabildiğince az kayar); yakınında toplantı olmayan tarih yeni toplantı olarak eklenir. Açıklanmamış toplantılar (ör. sonraki '
        + 'yıllar) ve geçmiş olduğu gibi kalır; senaryo adımları toplantısıyla taşınır.',
      merge: 'Listede olmayan tarihler eklenir; eski tarihler de kalır (yanlış olanları ✕ ile silin).',
      future: 'Bugünden sonraki bütün toplantılar silinir, yerine yapıştırılanlar gelir: yapıştırılmayan toplantılar listeden çıkar, '
        + 'onlara yazılmış senaryo adımları ve değerler kenara alınır (tarih geri eklenirse geri gelir).',
    };
    const hint = h('p', { class: 'muted', style: { margin: '6px 0 0', fontSize: '12.5px' } });
    const showHint = () => { hint.textContent = hints[mode.value]; };
    mode.addEventListener('change', showHint);
    showHint();
    m.body.appendChild(h('p', { class: 'muted', style: { marginTop: '0' } }, 'Her satıra bir tarih (Excel\'den bir sütun kopyalayıp yapıştırabilirsiniz).'));
    m.body.appendChild(area);
    m.body.appendChild(h('div', { class: 'field', style: { marginTop: '10px' } }, h('label', null, 'Ne yapılsın'), mode, hint));
    m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Vazgeç'));
    const apply = h('button', { class: 'btn primary', type: 'button' }, 'Uygula');
    apply.addEventListener('click', async () => {
      const out = [];
      for (const raw of area.value.split(/[\n\r\t;]+/)) {
        const s = raw.trim();
        if (!s) continue;
        const iso = parseTrDate(s);
        if (!iso) { toast('Tarih anlaşılamadı: ' + s, 'err'); return; }
        out.push(iso);
      }
      if (!out.length) { toast('Tarih bulunamadı', 'err'); return; }
      apply.disabled = true;
      try {
        const res = await api.post('/api/calendar/preview', { current: this.dates(), dates: out, mode: mode.value });
        if (mode.value === 'future' && res.removed.length) {
          const list = res.removed.slice(0, 6).map(isoToTr).join(', ') + (res.removed.length > 6 ? ' …' : '');
          const ok = await confirmDialog('Gelecek toplantıların yerine koy',
            'Gelecekteki ' + (res.removed.length + res.unchanged) + ' toplantı silinip yerine ' + (res.added.length + res.unchanged)
            + ' tarih konacak: ' + res.removed.length + ' toplantı (' + list + ') listeden çıkacak, onlara yazılmış senaryo adımları '
            + 'kenara alınacak. Kaydetmeden önce tabloda görebilirsiniz.', 'Yerine koy', true);
          if (!ok) return;
        }
        m.close();
        this.applyPaste(res);
      } catch (err) {
        errorToast(err);
      } finally {
        apply.disabled = false;
      }
    });
    m.foot.appendChild(apply);
    area.focus();
  }

  /** What a pasted column does, on the table: corrected rows keep where they came from ("önce …"). */
  applyPaste(res) {
    const byDate = new Map(this.rows.map((r) => [r.date, r]));
    for (const [was, now] of res.corrected) {
      const row = byDate.get(was);
      if (row) row.date = now;
    }
    const gone = new Set(res.removed);
    this.rows = this.rows.filter((r) => !gone.has(r.date));
    for (const d of res.added) this.rows.push({ date: d, was: null });
    const bits = [];
    if (res.corrected.length) bits.push(res.corrected.length + ' tarih düzeltildi');
    if (res.added.length) bits.push(res.added.length + ' yeni toplantı');
    if (res.removed.length) bits.push(res.removed.length + ' toplantı çıkarıldı');
    if (res.unchanged) bits.push(res.unchanged + ' tarih zaten doğruydu');
    if (res.skipped.length) bits.push('bugünden önceki ' + res.skipped.length + ' tarih yok sayıldı (' + res.skipped.map(isoToTr).join(', ') + ')');
    const changed = res.corrected.length + res.added.length + res.removed.length;
    if (changed) this.dirty = true;
    toast((bits.join(' · ') || 'Değişiklik yok') + (changed ? ' – kaydetmeden önce tabloyu kontrol edin' : ''), changed ? 'ok' : '', 6500);
    this.renderCalendar();
  }

  async sync(recompute) {
    try {
      this.cov.state = await api.post('/api/history/sync', { recompute: !!recompute });
      this.cov.state.phase = this.cov.state.phase === 'idle' ? 'fetch' : this.cov.state.phase;
      this.renderHistory();
    } catch (err) { errorToast(err); }
  }

  renderHistory(resetInputs) {
    const st = this.cov.state;
    clear(this.histInfo);
    const line = (label, value) => h('span', { class: 'kv' }, h('span', { class: 'muted' }, label + ' '), h('b', null, value));
    this.histInfo.appendChild(line('Durum', st.phase === 'idle' ? (st.running ? 'güncel' : 'beklemede') : stateText(st)));
    this.histInfo.appendChild(line('Kapanışlar', st.first_day ? isoToTr(st.first_day) + ' – ' + isoToTr(st.last_day) + ' · ' + st.series + ' seri' : 'yok'));
    this.histInfo.appendChild(line('PPK geçmişi', st.mpc_days ? st.mpc_days + ' gün (' + isoToTr(st.mpc_first) + ' – ' + isoToTr(st.mpc_last) + ')'
      + (st.mpc_missing ? ', ' + st.mpc_missing + ' günde eksik kota' : '')
      + (st.mpc_unreliable ? ', ' + st.mpc_unreliable + ' günde çözücü tutarsız' : '') : 'yok'));
    this.histInfo.appendChild(line('Kaynak', st.mode === 'live' ? 'Bloomberg geçmişi (her ' + Math.round(st.refresh / 60) + ' dk)' : 'Excel dosyasındaki kayıtlı geçmiş + TLREF'));
    if (st.last_sync) this.histInfo.appendChild(line('Son güncelleme', st.last_sync));
    if (st.error) this.histInfo.appendChild(h('span', { class: 'kv warn-text' }, 'Hata: ' + st.error));
    if (resetInputs || !this.fieldInp.dataset.set) {
      this.fieldInp.value = st.settings.dibs_field;
      this.daysInp.value = String(st.settings.lookback_days);
      this.fieldInp.dataset.set = '1';
    }
    const names = { ref: 'TLREF', ois: 'TRY OIS', off: 'Offshore · FX swap ima', xccy: 'Offshore · XCCY', dibs: 'DİBS', sofr: 'SOFR fixing (Trades)' };
    const rows = [[HD('Grup'), HD('Seri'), HD('Ticker'), HD('Alan'), HD('İlk gün'), HD('Son gün'), HD('Gün'), HD('Durum')]];
    for (const s of this.cov.series) {
      rows.push([TXT(names[s.group] || s.group), TXT(s.label, { cls: 'lab' }), TXT(s.ticker), TXT(s.field), TXT(isoToTr(s.first)), TXT(isoToTr(s.last)), N(s.n, 0),
        s.n ? TXT(s.alt ? 'yedek kaynak' : (s.main ? 'ana kaynak' : 'var'), { c: 'pos' })
          : TXT(s.alt ? 'yedek · geçmiş yok' : (s.backed ? 'ana kaynakta geçmiş yok – yedek kullanılır' : 'geçmiş yok'), { c: s.alt || s.backed ? 'mute' : 'warn' })]);
    }
    this.seriesPanel.setData({ sheet: '', rows });
    this.seriesPanel.setNote('Seriler Excel dosyasından okunur: OIS ticker kökleri (OIS_MAIN!J9:J26), offshore ticker\'ları (Forward!AO6:AO26), DİBS RV listesi. '
      + 'SOFR fixing\'i (SOFRRATE Index) Trades\'in SOFR swap\'ları için tutulur: iki yıl bir kez, sonra günde bir kez - New York bir önceki günün fixing\'ini yayımladıktan sonra (16:30). '
      + 'Kaynak sırası yukarıdaki "Veri kaynakları" listesinden gelir (en sonda Excel\'deki ticker – BGN). '
      + 'Yedek yalnızca ana kaynağın kapanışı olmayan günleri doldurur (hareketi ana kaynağın seviyesine eklenerek); ana kaynakta hiç geçmiş yoksa seri yedekten okunur. '
      + 'Bir seride "geçmiş yok" yazıyorsa Bloomberg o ticker / alan için tarihçe vermiyor demektir.');
  }
}
