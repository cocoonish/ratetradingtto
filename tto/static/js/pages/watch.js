// İzleme · Alarmlar: the user's watch list - anything: a VİOP contract (OIS − VİOP, implied TRY), a bond (ASW,
// yield, cheap / rich, prices), an OIS or offshore tenor, the desk strip, an expression of them, any cell (right
// click → "İzlemeye ekle") -, how each item moved today (open, change, low / high, its path, since a reference
// taken on purpose), the alarms on them, the ones that fired today, and the desk's notes of the day.  A click on an
// item (or an alarm) draws its past: the closes, the band of the z window and the z-score day by day.
import { api } from '../api.js';
import { h, clear, toast, errorToast, menu, modal, confirmDialog } from '../ui.js';
import { num } from '../format.js';
import { openWatchDialog, askPermission } from '../alarms.js';
import { SeriesView, watchSpec } from '../serieschart.js';

const OP = { '>=': '≥', '<=': '≤', x: 'kesişir' };
const UNIT_TEXT = { pct: 'faiz (%) – değişim bp', bp: 'bp', px: 'fiyat', fx: 'kur', raw: 'sayı' };
const KIND_TEXT = { viop: 'VİOP', bond: 'kâğıt', ois: 'OIS', off: 'offshore', masa: 'masa', expr: 'ifade', cell: 'hücre' };
const isNum = (v) => typeof v === 'number' && isFinite(v);
const HISTORY_AGAIN_MS = 5 * 60 * 1000;   // a drawn history is asked again this often (the value now: every refresh)

/** A change: "+3,2 bp", "−0,0150" (a price or FX level: in the item's own decimals). */
function changeText(v, it) {
  if (!isNum(v)) return '';
  const bp = it.unit_name === 'bp';
  const d = bp ? 1 : (it.show === 'px' ? 3 : 4);
  return (v > 0 ? '+' : (v < 0 ? '−' : '')) + num(Math.abs(v), d, false) + (bp ? ' bp' : '');
}

/** The day's path as a small line (the open dashed). */
function spark(points, open) {
  const w = 120, hgt = 26;
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('width', w);
  svg.setAttribute('height', hgt);
  svg.setAttribute('class', 'spark');
  if (!points || points.length < 2) return svg;
  const lo = Math.min(...points, isNum(open) ? open : Infinity), hi = Math.max(...points, isNum(open) ? open : -Infinity);
  const y = (v) => (hi === lo ? hgt / 2 : 2 + (hgt - 4) * (1 - (v - lo) / (hi - lo)));
  const x = (i) => 2 + (w - 4) * (i / (points.length - 1));
  if (isNum(open)) {
    const base = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    base.setAttribute('x1', 0); base.setAttribute('x2', w);
    base.setAttribute('y1', y(open)); base.setAttribute('y2', y(open));
    base.setAttribute('class', 'base');
    svg.appendChild(base);
  }
  const path = document.createElementNS('http://www.w3.org/2000/svg', 'polyline');
  path.setAttribute('points', points.map((v, i) => x(i).toFixed(1) + ',' + y(v).toFixed(1)).join(' '));
  path.setAttribute('class', points[points.length - 1] >= points[0] ? 'up' : 'down');
  svg.appendChild(path);
  return svg;
}

/** Where the level stands in the past window: the low - high line, the mean (tick) and now (dot). */
function band(z, now) {
  const w = 96, hgt = 16;
  const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  svg.setAttribute('width', w);
  svg.setAttribute('height', hgt);
  svg.setAttribute('class', 'band');
  if (!z || !isNum(z.min) || !isNum(z.max) || !isNum(now)) return svg;
  const lo = Math.min(z.min, now), hi = Math.max(z.max, now);
  const x = (v) => (hi === lo ? w / 2 : 4 + (w - 8) * (v - lo) / (hi - lo));
  const el = (tag, attrs) => { const e = document.createElementNS('http://www.w3.org/2000/svg', tag); for (const k in attrs) e.setAttribute(k, attrs[k]); svg.appendChild(e); return e; };
  el('line', { x1: x(z.min), x2: x(z.max), y1: hgt / 2, y2: hgt / 2, class: 'range' });
  if (isNum(z.mean)) el('line', { x1: x(z.mean), x2: x(z.mean), y1: 3, y2: hgt - 3, class: 'mean' });
  el('circle', { cx: x(now), cy: hgt / 2, r: 4, class: 'now' + (isNum(z.z) && Math.abs(z.z) >= 2 ? ' far' : '') });
  return svg;
}

const ZDAYS_KEY = 'tto.watch.zdays';
function savedDays() {
  try { const v = Number(localStorage.getItem(ZDAYS_KEY)); return [20, 60, 250].includes(v) ? v : 60; } catch (e) { return 60; }
}

export class WatchPage {
  constructor(host, ctx) {
    this.host = host;
    this.ctx = ctx;
    this.data = null;
    this.picked = null;                    // the item / alarm whose past is drawn: {key, subject, label}
    this.build();
  }

  build() {
    const tools = h('div', { class: 'page-tools' });
    const preset = h('button', { class: 'btn', type: 'button', id: 'watch-preset' }, 'Hazır grup ekle ▾');
    preset.addEventListener('click', (e) => {
      const r = preset.getBoundingClientRect();
      menu(r.left, r.bottom + 2, (this.data ? this.data.presets : []).map((p) => ({
        label: p.group + ' (' + p.items.length + ')', action: () => this.addPreset(p.group) })));
      e.stopPropagation();
    });
    const add = h('button', { class: 'btn primary', type: 'button', id: 'watch-add', title: 'VİOP kontratı, kâğıt, OIS, offshore, masa özeti, ifade ya da hücre: izle ya da alarm kur' }, 'Ekle · alarm kur…');
    add.addEventListener('click', () => openWatchDialog(this.ctx));
    const base = h('button', { class: 'btn', type: 'button', id: 'watch-base', title: 'Her kalemin şimdiki seviyesini referans al: değişim ayrıca bundan sonrası için de gösterilir (ör. sabah toplantısı)' }, 'Referansı şimdi al');
    base.addEventListener('click', () => this.takeBase(null));
    this.perm = h('button', { class: 'btn', type: 'button', id: 'watch-perm', title: 'Alarm çalınca tarayıcı bildirimi göster' }, 'Bildirimlere izin ver');
    this.perm.addEventListener('click', () => { askPermission(); setTimeout(() => this.permState(), 800); });
    tools.appendChild(preset);
    tools.appendChild(add);
    tools.appendChild(base);
    tools.appendChild(this.perm);
    tools.appendChild(h('span', { class: 'muted' }, 'Ya da herhangi bir tablodaki hücreye sağ tıklayın: "İzlemeye ekle" / "Alarm kur…"'));
    this.host.appendChild(tools);
    const panel = (id, title) => {
      const body = h('div', { class: 'body' });
      const el = h('section', { class: 'panel wide', id }, h('header', null, h('h2', null, title)), body);
      this.host.appendChild(el);
      return body;
    };
    this.zdays = savedDays();
    this.list = panel('watch-list', 'İzleme listesi');
    const zseg = h('div', { class: 'seg small', id: 'watch-zdays', title: 'z-skoru ve tarihsel bant: son kaç günlük kapanışa göre' });
    for (const n of [20, 60, 250]) {
      const b = h('button', { type: 'button' }, n + 'g');
      b.dataset.v = String(n);
      b.classList.toggle('on', n === this.zdays);
      b.addEventListener('click', () => {
        this.zdays = n;
        try { localStorage.setItem(ZDAYS_KEY, String(n)); } catch (e) { /* not kept */ }
        for (const x of zseg.children) x.classList.toggle('on', x === b);
        if (this.sv) this.sv.setWindow(n);
        this.refresh();
      });
      zseg.appendChild(b);
    }
    this.list.parentElement.querySelector('header').appendChild(h('div', { class: 'ztools' }, h('span', { class: 'muted' }, 'z / bant:'), zseg));
    // the past of the item clicked
    const seriesBody = h('div', { class: 'body' });
    const close = h('button', { class: 'iconbtn', type: 'button', title: 'Grafiği kapat' }, '✕');
    close.addEventListener('click', () => this.closeHistory());
    this.seriesSec = h('section', { class: 'panel wide hidden', id: 'watch-series' },
      h('header', null, h('h2', null, 'Seçili kalemin geçmişi'), h('span', { class: 'grow' }), close), seriesBody,
      h('div', { class: 'note' }, 'Listede bir kaleme (ya da bir alarma) tıklayın. Kapanışlar listedeki z\'nin kullandıklarıdır: OIS, TLREF ve offshore tarihçe deposundan, '
        + 'diğerleri dashboard\'un her gün kaydettiği kapanıştan. Pencere üstteki "z / bant" seçimi; son nokta şimdiki değer.'));
    this.host.appendChild(this.seriesSec);
    this.sv = new SeriesView(seriesBody, { rule: 'raw', windowSeg: false, window: this.zdays, height: 220 });
    this.alarmBox = panel('watch-alarms', 'Alarmlar');
    this.firedBox = panel('watch-fired', 'Bugün çalan alarmlar');
    const notesBody = panel('watch-notes', 'Masa notları · bugün (herkes görür)');
    this.notes = h('textarea', { class: 'inp chatbox', id: 'notes-text', rows: '6', spellcheck: 'false',
      placeholder: 'Bugün izlenecek seviyeler, sabah toplantısı, ihale, veri takvimi…' });
    this.notesInfo = h('span', { class: 'muted', id: 'notes-info' });
    const save = h('button', { class: 'btn primary', type: 'button', id: 'notes-save' }, 'Notları kaydet');
    save.addEventListener('click', () => this.saveNotes());
    notesBody.appendChild(this.notes);
    notesBody.appendChild(h('div', { class: 'chatrow actions' }, save, this.notesInfo));
    this.permState();
  }

  permState() {
    const p = window.Notification ? Notification.permission : 'denied';
    this.perm.classList.toggle('hidden', p !== 'default');
  }

  async load() { await this.refresh(); }

  async refresh() {
    const d = await api.get('/api/watch?days=' + (this.zdays || 60));
    this.data = d;
    this.fillList(d);
    this.fillAlarms(d);
    this.fillFired(d);
    this.liveHistory(d);
    if (document.activeElement !== this.notes && !this.notesDirty) this.notes.value = (d.notes && d.notes.text) || '';
    this.notesInfo.textContent = d.notes && d.notes.at ? 'Son kaydeden: ' + this.ctx.displayName(d.notes.by) + ' · ' + d.notes.at : '';
    if (!this.notes.__bound) {
      this.notes.__bound = true;
      this.notes.addEventListener('input', () => { this.notesDirty = true; });
    }
  }

  fillList(d) {
    const box = clear(this.list);
    if (!d.items.length) {
      box.appendChild(h('div', { class: 'empty' }, 'İzleme listesi boş: "Ekle · alarm kur…" ile VİOP kontratı, kâğıt, OIS, offshore, '
        + 'masa özeti ya da bir ifade ([OIS 2Y] - [OIS 1Y]) ekleyin; "Hazır grup ekle" ile masa özetini, OIS eğrisini, VİOP spread\'lerini; '
        + 'ya da herhangi bir sayfadaki hücreye sağ tıklayıp "İzlemeye ekle"yi seçin.'));
      return;
    }
    const t = h('table', { class: 'plain watch', id: 'watch-table' });
    const zh = 'z (' + (d.days || 60) + 'g)';
    t.appendChild(h('tr', null, ...['Ad', 'Şimdi', 'Açılış', 'Gün', 'Düşük', 'Yüksek', 'Gün içi', zh, 'Bant', 'Referans', 'Ref\'ten', 'Son hareket', '']
      .map((x, i) => h('th', { class: [0, 6, 8, 12].includes(i) ? 'l' : '' }, x))));
    d.items.forEach((it, k) => {
      const cls = (v) => (isNum(v) && Math.abs(v) > 1e-9 ? (v > 0 ? 'pos' : 'neg') : '');
      const kind = (it.subject && it.subject.kind) || 'cell';
      const name = h('td', { class: 'l name', title: (KIND_TEXT[kind] || kind) + ' · ' + it.what + (it.detail ? ' · ' + it.detail : '') }, it.label,
        !isNum(it.value) && it.detail ? h('span', { class: 'sub' }, it.detail) : null);
      name.addEventListener('dblclick', () => this.rename(it));
      const acts = h('td', { class: 'l acts' });
      const btn = (label, title, fn) => { const b = h('button', { class: 'iconbtn', type: 'button', title }, label); b.addEventListener('click', fn); acts.appendChild(b); return b; };
      btn('🔔', 'Bu kaleme alarm kur', () => openWatchDialog(this.ctx, { subject: it.subject, label: it.label, focus: 'alarm' }));
      btn('⟲', 'Referansı şimdi al', () => this.takeBase(it.id));
      btn('▲', 'Yukarı', () => this.move(it, -1)).disabled = k === 0;
      btn('▼', 'Aşağı', () => this.move(it, 1)).disabled = k === d.items.length - 1;
      btn('⋯', kind === 'cell' ? 'Ad / birim' : 'Ad', (e) => this.more(it, e));
      btn('✕', 'Listeden çıkar', () => this.remove(it));
      const z = it.z || {};
      const ztip = isNum(z.z) ? z.n + ' kapanış (' + (z.source || '') + ', ' + (z.first || '') + ' – ' + (z.last || '') + '): ortalama ' + (z.mean_text || '')
        + ', std ' + (z.sd_text || '') + ', en düşük ' + (z.min_text || '') + ', en yüksek ' + (z.max_text || '') + ', yüzdelik %' + num(z.pct, 0, false)
        : 'Geçmiş yetersiz: ' + (z.n || 0) + ' / ' + (z.need || 20) + ' kapanış' + (z.source ? ' (' + z.source + ')' : '')
          + '. OIS, TLREF ve offshore için tarihçe deposu; diğerleri için dashboard\'un her gün kaydettiği kapanış kullanılır.';
      btn('📈', 'Geçmişini çiz (z-skoru ile)', () => this.showHistory({ key: 'i:' + it.id, subject: it.subject, label: it.label }));
      acts.insertBefore(acts.lastChild, acts.firstChild);
      const tr = h('tr', { 'data-id': it.id, class: this.picked && this.picked.key === 'i:' + it.id ? 'pick' : '' }, name, h('td', { class: 'now' }, it.now || ''), h('td', null, it.open_text || ''),
        h('td', { class: cls(it.change) }, changeText(it.change, it)), h('td', null, it.low_text || ''), h('td', null, it.high_text || ''),
        h('td', { class: 'l' }, spark(it.path, it.open)),
        h('td', { class: 'z' + (isNum(z.z) && Math.abs(z.z) >= 2 ? ' far' : ''), title: ztip }, isNum(z.z) ? z.z_text : '–'),
        h('td', { class: 'l', title: ztip }, band(z, it.value)),
        h('td', { title: it.base_at ? 'Referans alındı: ' + it.base_at : 'Referans yok: ⟲ ile alın' }, it.base_text || ''),
        h('td', { class: cls(it.since_base) }, changeText(it.since_base, it)), h('td', { class: 'muted' }, it.moved || ''), acts);
      tr.addEventListener('click', (e) => {
        if (e.target.closest('button')) return;
        this.showHistory({ key: 'i:' + it.id, subject: it.subject, label: it.label });
      });
      t.appendChild(tr);
    });
    box.appendChild(t);
  }

  // ------------------------------------------------------------------ the past of the item clicked
  showHistory(w) {
    if (!w || !w.subject) return;
    if (this.picked && this.picked.key === w.key && !this.seriesSec.classList.contains('hidden')) { this.closeHistory(); return; }
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
    const key = this.picked ? this.picked.key : '';
    for (const tr of this.host.querySelectorAll('#watch-table tr[data-id]')) tr.classList.toggle('pick', key === 'i:' + tr.dataset.id);
    for (const tr of this.host.querySelectorAll('#alarm-table tr[data-id]')) tr.classList.toggle('pick', key === 'a:' + tr.dataset.id);
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

  /** The value now from the list (every refresh); the closes again now and then. */
  liveHistory(d) {
    const w = this.picked;
    if (!w || !this.hist) return;
    if (Date.now() - (this.histAt || 0) > HISTORY_AGAIN_MS) { this.loadHistory(false); return; }
    const id = w.key.slice(2);
    const row = w.key[0] === 'i' ? d.items.find((x) => x.id === id) : d.alarms.find((x) => x.id === id);
    const v = row ? (w.key[0] === 'i' ? row.value : row.now) : null;
    if (isNum(v) && v !== this.hist.value) {
      this.hist.value = v;
      this.sv.show(watchSpec(this.hist, w.label));
    }
  }

  fillAlarms(d) {
    const box = clear(this.alarmBox);
    if (!d.alarms.length) {
      box.appendChild(h('div', { class: 'empty' }, 'Alarm yok: "Ekle · alarm kur…" (ör. VİOP OIS − VİOP spread\'i 250 bp üstü, bir kâğıdın ASW\'i), '
        + 'listedeki 🔔 ya da bir hücreye sağ tıklayıp "Alarm kur…".'));
      return;
    }
    const t = h('table', { class: 'plain watch', id: 'alarm-table' });
    t.appendChild(h('tr', null, ...['Ad', 'Koşul', 'Şimdi', 'Hareket / z', 'Uzaklık', 'Durum', 'Not', ''].map((x, i) => h('th', { class: [0, 1, 5, 6, 7].includes(i) ? 'l' : '' }, x))));
    for (const a of d.alarms) {
      const dist = a.distance_text || '';
      const state = a.active ? h('span', { class: 'pill neu' }, 'bekliyor') : h('span', { class: 'pill warn', title: 'Değer: ' + (a.fired_text || '') }, 'çaldı · ' + (a.fired_at || '').slice(11));
      const acts = h('td', { class: 'l acts' });
      if (!a.active) {
        const re = h('button', { class: 'iconbtn', type: 'button', title: 'Aynı seviyeyle yeniden kur' }, 'Yeniden kur');
        re.addEventListener('click', () => this.rearm(a));
        acts.appendChild(re);
      }
      const del = h('button', { class: 'iconbtn', type: 'button', title: 'Alarmı sil' }, '✕');
      del.addEventListener('click', () => this.removeAlarm(a));
      acts.appendChild(del);
      const picked = this.picked && this.picked.key === 'a:' + a.id;
      const tr = h('tr', { 'data-id': a.id, class: ((a.active ? '' : 'fired') + (picked ? ' pick' : '')).trim() },
        h('td', { class: 'l', title: a.what + (a.detail ? ' · ' + a.detail : '') + '\nTıklayın: geçmişi' }, a.label,
          !isNum(a.now) && a.detail ? h('span', { class: 'sub' }, a.detail) : null),
        h('td', { class: 'l cond' }, a.condition || ((OP[a.op] || a.op) + ' ' + (a.level_text || ''))), h('td', null, a.now_text || ''),
        h('td', null, a.mode && a.mode !== 'level' ? (a.measure_text || '–') : ''), h('td', { title: 'Koşulun sağlanmasına kalan' }, dist),
        h('td', { class: 'l' }, state), h('td', { class: 'l muted' }, a.note || ''), acts);
      tr.addEventListener('click', (e) => {
        if (e.target.closest('button')) return;
        this.showHistory({ key: 'a:' + a.id, subject: a.subject, label: a.label });
      });
      t.appendChild(tr);
    }
    box.appendChild(t);
  }

  fillFired(d) {
    const box = clear(this.firedBox);
    if (!d.fired.length) { box.appendChild(h('div', { class: 'empty' }, 'Bugün çalan alarm yok.')); return; }
    const t = h('table', { class: 'plain watch', id: 'fired-table' });
    t.appendChild(h('tr', null, ...['Saat', 'Ad', 'Koşul', 'Değer', 'Hareket / z', 'Not'].map((x, i) => h('th', { class: [0, 1, 2, 5].includes(i) ? 'l' : '' }, x))));
    for (const e of d.fired.slice().reverse()) {
      const cond = e.condition || ((OP[e.op] || e.op) + ' ' + (e.level_text || ''));
      t.appendChild(h('tr', null, h('td', { class: 'l' }, e.time), h('td', { class: 'l' }, e.label), h('td', { class: 'l' }, cond),
        h('td', null, e.value_text || ''), h('td', null, e.mode && e.mode !== 'level' ? (e.measure_text || '') : ''), h('td', { class: 'l muted' }, e.note || '')));
    }
    box.appendChild(t);
  }

  // ------------------------------------------------------------------ actions
  async act(path, body, message) {
    try {
      const res = await api.post(path, body);
      if (message) toast(typeof message === 'function' ? message(res) : message, 'ok');
      this.ctx.refreshNow();
      return res;
    } catch (err) { errorToast(err); return null; }
  }

  addPreset(group) { return this.act('/api/watch/preset', { group }, (r) => r.added + ' kalem eklendi'); }
  takeBase(id) { return this.act('/api/watch/base', { id }, (r) => r.taken + ' kalemin referansı alındı'); }
  move(it, by) { return this.act('/api/watch/update', { id: it.id, move: by }); }

  async remove(it) {
    if (!(await confirmDialog('İzlemeden çıkar', it.label + ' izleme listesinden çıkarılsın mı?', 'Çıkar', true))) return;
    await this.act('/api/watch/remove', { id: it.id }, 'Çıkarıldı');
  }

  rename(it) {
    const m = modal({ title: 'Ad · ' + it.what, width: 420 });
    const inp = h('input', { class: 'inp', value: it.label, maxlength: '60' });
    m.body.appendChild(inp);
    const ok = h('button', { class: 'btn primary', type: 'button' }, 'Kaydet');
    ok.addEventListener('click', async () => { m.close(); await this.act('/api/watch/update', { id: it.id, label: inp.value }); });
    m.foot.appendChild(ok);
    inp.focus();
    inp.select();
  }

  more(it, e) {
    const r = e.target.getBoundingClientRect();
    const items = [{ label: 'Adını değiştir…', action: () => this.rename(it) },
      { label: 'Alarm kur…', action: () => openWatchDialog(this.ctx, { subject: it.subject, label: it.label, focus: 'alarm' }) }];
    if (it.subject && it.subject.kind === 'cell') {           // a cell does not say what it holds: how to read it
      items.push({ sep: true }, { header: 'Hücre ne gösteriyor' });
      for (const [u, t] of Object.entries(UNIT_TEXT)) items.push({ label: (it.show === u ? '✓ ' : '   ') + t, action: () => this.act('/api/watch/update', { id: it.id, unit: u }) });
    }
    menu(r.left, r.bottom + 2, items);
  }

  rearm(a) { return this.act('/api/alarms/rearm', { id: a.id }, 'Alarm yeniden kuruldu'); }

  async removeAlarm(a) {
    if (!(await confirmDialog('Alarmı sil', a.label + ' (' + (OP[a.op] || a.op) + ' ' + a.level_text + ') silinsin mi?', 'Sil', true))) return;
    await this.act('/api/alarms/remove', { id: a.id }, 'Alarm silindi');
  }

  async saveNotes() {
    const res = await this.act('/api/notes', { text: this.notes.value }, 'Notlar kaydedildi');
    if (res) this.notesDirty = false;
  }

  destroy() {
    if (this.sv) this.sv.destroy();
  }
}
