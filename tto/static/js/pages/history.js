// Pages built on the dashboard's own history: the end-of-day change matrix, the pricing of every MPC meeting
// over time, and the settings behind them (the meeting calendar).
import { api } from '../api.js';
import { h, clear, toast, errorToast, confirmDialog, modal } from '../ui.js';
import { Grid, copyGrid } from '../grid.js';
import { Chart } from '../chart.js';
import { num, isoToTr } from '../format.js';

const isNum = (v) => typeof v === 'number' && isFinite(v);
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

/** Background of a change: warm for up, cool for down, stronger the larger it is against `scale`. */
function heat(v, scale) {
  if (!isNum(v) || !(scale > 0) || Math.abs(v) < 1e-9) return null;
  const t = Math.min(1, Math.abs(v) / scale) * 0.62 + 0.1;
  const base = v > 0 ? [224, 106, 58] : [59, 131, 247];
  return base.map((c) => Math.round(128 + (c - 128) * t).toString(16).padStart(2, '0')).join('');
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

/** Largest change of a block (never below `floor`), so that colours compare within the block. */
function scaleOf(values, floor) {
  let m = floor;
  for (const v of values) if (isNum(v) && Math.abs(v) > m) m = Math.abs(v);
  return m;
}

function panel(title, opts = {}) {
  const body = h('div', { class: 'body' });
  const tools = h('div', { class: 'tools' });
  const head = h('header', null, h('h2', { title }, title), opts.badge || null, tools);
  const el = h('section', { class: 'panel' + (opts.wide ? ' wide' : '') + (opts.chart ? ' chart full' : '') }, head, body);
  if (opts.id) el.dataset.panel = opts.id;
  const note = h('div', { class: 'note hidden' });
  el.appendChild(note);
  return { el, body, tools, head, title: head.firstChild, note,
    setNote(text) { note.textContent = text || ''; note.classList.toggle('hidden', !text); } };
}

function gridPanel(title, opts = {}) {
  const p = panel(title, opts);
  p.grid = null;
  p.setData = (data) => {
    if (!p.grid) {
      p.grid = new Grid({ data, editable: false });
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
export class EodPage extends HistoryPage {
  constructor(host, ctx) {
    super(host, ctx);
    this.asof = null;                      // null: the last close
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
    this.curve = gridPanel('TRY OIS · Offshore — seviye ve değişim', { wide: true, id: 'curve' });
    this.mpc = gridPanel('PPK fiyatlaması — toplantı bazında', { wide: true, id: 'mpc' });
    this.bonds = gridPanel('DİBS — getiri ve değişim', { wide: true, id: 'dibs' });
    this.host.appendChild(h('div', { class: 'panels' }, this.curve.el, this.mpc.el, this.bonds.el));
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

    this.renderCurve(d);
    this.renderMpc(d);
    this.renderBonds(d);
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
    const half = (e, scale) => (e
      ? [N(e.last, 3, { tip: e.ticker + ' · ' + e.field + (e.day ? ' · ' + isoToTr(e.day) : '') }),
        D(e.d1, scale, 1, e.d1_from, d.ref.d1), D(e.w1, scale, 1, e.w1_from, d.ref.w1), D(e.m1, scale, 1, e.m1_from, d.ref.m1)]
      : [EMPTY(), EMPTY(), EMPTY(), EMPTY()]);
    if (d.tlref) rows.push([TXT('TLREF', { cls: 'lab' })].concat(half(d.tlref, so), half(null)));
    for (const r of d.curve) {
      if (!r.ois && !r.off) continue;
      rows.push([TXT(r.tenor, { cls: 'lab' })].concat(half(r.ois, so), half(r.off, sf)));
    }
    this.curve.setData({ sheet: '', rows });
    this.curve.setNote('OIS kaynağı: ' + d.source.ois + ' (MASA → OIS eğri RV → Kaynak). Offshore: Forward sayfasındaki TRYI / TRYSAQ ticker\'ları. '
      + 'Hücrenin üzerinde durunca önceki kapanış görünür.');
  }

  renderMpc(d) {
    const rows = [];
    rows.push([HD('Toplantı'), HD('Fiyatlanan adım (bp)', { cs: 4 }), SKIP(), SKIP(), SKIP(),
      HD('Toplantı sonrası ima TLREF (%)', { cs: 4 }), SKIP(), SKIP(), SKIP(), HD('Kümülatif (bp)', { cs: 2 }), SKIP()]);
    rows.push([HD(''), HD('Son'), HD('Δ1G'), HD('Δ1H'), HD('Δ1A'), HD('Son'), HD('Δ1G bp'), HD('Δ1H bp'), HD('Δ1A bp'), HD('Son'), HD('Δ1G')]);
    const vals = [];
    for (const m of d.mpc) vals.push(m.step.d1, m.step.w1, m.step.m1, m.level.d1, m.level.w1, m.level.m1);
    const sc = scaleOf(vals, 10);
    for (const m of d.mpc) {
      const s = m.step, l = m.level, c = m.cum;
      rows.push([TXT(isoToTr(m.meeting) + (m.front ? ' · ilk' : ''), { cls: 'lab', tip: m.front ? 'İlk toplantı: adım bugünkü TLREF\'e göre ölçülür' : '' }),
        N(s.last, 1), D(s.d1, sc, 1, s.d1_from, d.ref.d1, 1), D(s.w1, sc, 1, s.w1_from, d.ref.w1, 1), D(s.m1, sc, 1, s.m1_from, d.ref.m1, 1),
        N(isNum(l.last) ? l.last * 100 : null, 3), D(l.d1, sc, 1, isNum(l.d1_from) ? l.d1_from * 100 : null, d.ref.d1),
        D(l.w1, sc, 1, isNum(l.w1_from) ? l.w1_from * 100 : null, d.ref.w1), D(l.m1, sc, 1, isNum(l.m1_from) ? l.m1_from * 100 : null, d.ref.m1),
        N(c.last, 1), D(c.d1, sc, 1, c.d1_from, d.ref.d1, 1)]);
    }
    if (!d.mpc.length) rows.push([TXT('Bu tarih için hesaplanmış PPK fiyatlaması yok' + (d.state && d.state.phase !== 'idle' ? ' – hesaplanıyor…' : ''), { cs: 11 })]
      .concat(Array.from({ length: 10 }, SKIP)));
    this.mpc.setData({ sheet: '', rows });
    this.mpc.setNote((d.decision_day ? 'PPK günü: o günün TLREF fixingi kararı henüz yansıtmadığı için adımlar çözücünün karar sonrası ima ettiği seviyeden ölçülür. ' : '')
      + 'Her gün o günün OIS kapanışlarıyla Excel\'in kendi çözücüsü (Motor · GLOBAL İMA PPK) yeniden çalıştırılır. '
      + 'Zaman serisi: PPK Fiyatlama Geçmişi sayfası.');
  }

  renderBonds(d) {
    const rows = [];
    const latest = !d.days.length || d.asof === d.days[0];
    rows.push([HD('ISIN'), HD('Ad'), HD('Vade'), HD('Tip'), HD('Son'), HD('Δ1G'), HD('Δ1H'), HD('Δ1A'), HD('Son · Δ birimi'), HD('Kapanış'),
      HD('DİBS RV · BIST bileşik %', { tip: 'Excel\'in kendi hesabı (DİBS RV sayfası, şu anki değer) – Bloomberg getirisiyle karşılaştırmak için' })]);
    const sc = scaleOf(d.bonds.filter((b) => b.unit === 'pct').flatMap((b) => [b.d1, b.w1, b.m1]), 10);
    const sp = scaleOf(d.bonds.filter((b) => b.unit !== 'pct').flatMap((b) => [b.d1, b.w1, b.m1]), 0.25);
    let any = false;
    for (const b of d.bonds) {
      const pct = b.unit === 'pct', s = pct ? sc : sp, dg = pct ? 1 : 3;
      if (isNum(b.last)) any = true;
      rows.push([TXT(b.isin, { cls: 'lab', tip: b.ticker + ' · ' + b.field }), TXT(b.name), TXT(isoToTr(b.maturity)), TXT(b.type),
        N(b.last, 3), D(b.d1, s, dg, b.d1_from, d.ref.d1), D(b.w1, s, dg, b.w1_from, d.ref.w1), D(b.m1, s, dg, b.m1_from, d.ref.m1),
        TXT(pct ? 'getiri · bp' : 'fiyat · puan', { c: 'mute' }), TXT(isoToTr(b.day), { c: 'mute' }),
        latest && isNum(b.bist) ? N(b.bist * 100, 3) : EMPTY()]);
    }
    this.bonds.setData({ sheet: '', rows });
    this.bonds.setNote(any
      ? 'Tahviller DİBS RV sayfasındaki listeden; getiri Bloomberg alanı ' + d.source.dibs_field + ' (Ayarlar\'dan değiştirilebilir). TLREF\'e endeksli (T) kağıtlarda fiyat izlenir.'
      : 'DİBS geçmişi yok' + (d.live ? ': Bloomberg bu alan (' + d.source.dibs_field + ') için geçmiş vermedi – Ayarlar\'dan alanı değiştirin.'
        : ' – Excel dosyası tahvil geçmişi saklamıyor; Bloomberg bağlıyken ' + d.source.dibs_field + ' alanından doldurulur.'));
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
      N(d.tlref[k], 4), N(d.quotes[k], 0, quoteTip(k)), state(k)].concat(cols.map((m) => {
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
    const [cal, cov] = await Promise.all([api.get('/api/calendar'), api.get('/api/history/series')]);
    if (this.dead) return;
    this.cal = cal;
    this.cov = cov;
    this.rows = cal.meetings.map((m) => ({ date: m.date, was: m.date }));
    this.dirty = false;
    clear(this.host);
    this.build();
    this.renderCalendar();
    this.renderHistory();
    this.timer = setInterval(() => { this.pollState().catch(() => {}); }, 4000);
  }

  /** A market tick: the calendar is only reloaded when nothing is being edited. */
  async refresh() {
    if (this.dead) return;
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
    const paste = h('button', { class: 'btn', type: 'button', title: 'Excel\'den kopyalanan tarih sütununu yapıştır' }, 'Toplu yapıştır…');
    paste.addEventListener('click', () => this.bulk());
    this.rollBtn = h('button', { class: 'btn', type: 'button',
      title: 'Geçen toplantıları OIS sayfasındaki listeden arşive al; liste sıradaki toplantıdan başlar. Senaryo adımları toplantılarıyla birlikte kayar.' },
    'Geçen toplantıları arşivle');
    this.rollBtn.addEventListener('click', () => this.roll());
    this.calPanel.body.appendChild(h('div', { class: 'set-body' }, this.calInfo,
      h('div', { class: 'set-actions' }, add, paste, this.rollBtn, h('span', { class: 'grow' }), this.undoBtn, this.saveBtn),
      h('div', { class: 'set-scroll' }, this.calTable)));
    this.calPanel.setNote('Toplantı tarihleri herkes için ortaktır ve OIS · PPK sayfasındaki listeyle (OIS_MAIN!P10:P89) aynıdır. Bir tarih değiştiğinde ya da '
      + 'liste kaydırıldığında her kullanıcının senaryo adımları (U:W) ve kayıtlı senaryoları toplantısıyla birlikte taşınır; '
      + 'PPK fiyatlama geçmişi yeni takvimle arka planda yeniden hesaplanır.');

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
    this.seriesPanel = gridPanel('Tarihçe serileri · neyin geçmişi var', { wide: true, id: 'series' });
    this.host.appendChild(h('div', { class: 'panels' }, this.calPanel.el, this.histPanel.el, this.seriesPanel.el));
  }

  renderCalendar() {
    const cal = this.cal;
    const spot = cal.spot;
    const inList = cal.meetings.filter((m) => m.where === 'list').length;
    clear(this.calInfo);
    this.calInfo.appendChild(h('span', null, 'Bugün ', h('b', null, isoToTr(cal.today)), ' · OIS spot ', h('b', null, isoToTr(spot)),
      ' · sıradaki toplantı ', h('b', null, cal.next ? isoToTr(cal.next) : '—'), ' · listede ', h('b', null, String(inList)), ' / ' + cal.slots + ' toplantı',
      cal.passed_in_list ? h('span', { class: 'warn-text' }, ' · ' + cal.passed_in_list + ' toplantı geçti, hâlâ listede') : null));
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
    try {
      const res = await api.post('/api/calendar', { dates: this.dates(), roll: !!roll });
      const bits = [res.meetings + ' toplantı listede', res.archive + ' arşivde'];
      if (res.rolled && res.rolled.length) bits.push(res.rolled.length + ' geçen toplantı arşive alındı');
      if (res.moved || res.scenarios) bits.push('senaryo adımları taşındı (' + res.moved + ' hücre, ' + res.scenarios + ' kayıtlı senaryo)');
      toast('Takvim kaydedildi: ' + bits.join(' · '), 'ok', 6000);
      this.dirty = false;
      this.cal = await api.get('/api/calendar');
      this.rows = this.cal.meetings.map((m) => ({ date: m.date, was: m.date }));
      this.renderCalendar();
      this.ctx.refreshNow();
    } catch (err) { errorToast(err); }
  }

  async roll() {
    const n = this.cal.passed_in_list;
    const ok = await confirmDialog('Geçen toplantıları arşivle',
      n + ' toplantı geçti. Bunlar OIS sayfasındaki listeden arşive alınır ve liste ' + (this.cal.next ? isoToTr(this.cal.next) : 'sıradaki')
      + ' toplantısından başlar (MPC1). Her kullanıcının senaryo adımları ve kayıtlı senaryoları toplantılarıyla birlikte kaydırılır; '
      + 'geçmiş fiyatlama serileri etkilenmez.', 'Arşivle');
    if (ok) this.save(true);
  }

  bulk() {
    const m = modal({ title: 'Toplantı tarihlerini yapıştır', width: 460 });
    const area = h('textarea', { class: 'inp', rows: '12', style: { width: '100%', fontFamily: 'var(--mono)' },
      placeholder: '10.12.2026\n21.01.2027\n18.03.2027\n…' });
    const mode = h('select', { class: 'inp' }, h('option', { value: 'merge' }, 'Listeye ekle'), h('option', { value: 'future' }, 'Gelecek toplantıların yerine koy'));
    m.body.appendChild(h('p', { class: 'muted', style: { marginTop: '0' } }, 'Her satıra bir tarih (Excel\'den bir sütun kopyalayıp yapıştırabilirsiniz).'));
    m.body.appendChild(area);
    m.body.appendChild(h('div', { class: 'field', style: { marginTop: '10px' } }, h('label', null, 'Ne yapılsın'), mode));
    m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Vazgeç'));
    m.foot.appendChild(h('button', { class: 'btn primary', type: 'button', onclick: () => {
      const out = [];
      for (const raw of area.value.split(/[\n\r\t;]+/)) {
        const s = raw.trim();
        if (!s) continue;
        const iso = parseTrDate(s);
        if (!iso) { toast('Tarih anlaşılamadı: ' + s, 'err'); return; }
        out.push(iso);
      }
      if (!out.length) { toast('Tarih bulunamadı', 'err'); return; }
      if (mode.value === 'future') this.rows = this.rows.filter((r) => r.date < this.cal.spot);
      const have = new Set(this.rows.map((r) => r.date));
      for (const iso of out) if (!have.has(iso)) { this.rows.push({ date: iso, was: null }); have.add(iso); }
      this.dirty = true;
      m.close();
      this.renderCalendar();
    } }, 'Uygula'));
    area.focus();
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
    const names = { ref: 'TLREF', ois: 'TRY OIS', off: 'Offshore · FX swap ima', xccy: 'Offshore · XCCY', dibs: 'DİBS' };
    const rows = [[HD('Grup'), HD('Seri'), HD('Ticker'), HD('Alan'), HD('İlk gün'), HD('Son gün'), HD('Gün'), HD('Durum')]];
    for (const s of this.cov.series) {
      rows.push([TXT(names[s.group] || s.group), TXT(s.label, { cls: 'lab' }), TXT(s.ticker), TXT(s.field), TXT(isoToTr(s.first)), TXT(isoToTr(s.last)), N(s.n, 0),
        s.n ? TXT(s.alt ? 'yedek kaynak' : 'var', { c: 'pos' }) : TXT(s.alt ? 'yedek · geçmiş yok' : 'geçmiş yok', { c: s.alt ? 'mute' : 'warn' })]);
    }
    this.seriesPanel.setData({ sheet: '', rows });
    this.seriesPanel.setNote('Seriler Excel dosyasından okunur: OIS ticker kökleri (OIS_MAIN!J9:J26) + kaynak (MASA!S171), offshore ticker\'ları (Forward!AO6:AO26), '
      + 'DİBS RV listesi. Bir seride "geçmiş yok" yazıyorsa Bloomberg o ticker / alan için tarihçe vermiyor demektir.');
  }
}
