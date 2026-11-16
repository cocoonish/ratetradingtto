// İzleme · Alarmlar: the user's watch list - anything: a VİOP contract (OIS − VİOP, implied TRY), a bond (ASW,
// yield, cheap / rich, prices), an OIS or offshore tenor, the desk strip, an expression of them, any cell (right
// click → "İzlemeye ekle") -, how each item moved today (open, change, low / high, its path, since a reference
// taken on purpose), the alarms on them, the ones that fired today, and the desk's notes of the day.  A click on an
// item (or an alarm) draws its past: the closes, the band of the z window and the z-score day by day.
// The desk's alarms ring for everyone: the ones an administrator set, the system's own (the data feed, TLREF, the
// database), who answered them ("Gördüm – Ayşe bakıyor"), what this user muted for themselves, and the day's log.
import { api } from '../api.js';
import { h, clear, toast, errorToast, menu, modal, confirmDialog } from '../ui.js';
import { num } from '../format.js';
import { openWatchDialog, askPermission, ackDesk, muteMenu } from '../alarms.js';
import { SeriesView, watchSpec } from '../serieschart.js';
import { TableColumns, toolsOf } from '../columns.js';
import { boxTools } from '../pagebox.js';

export const OP = { '>=': '≥', '<=': '≤', x: 'kesişir' };
const UNIT_TEXT = { pct: 'faiz (%) – değişim bp', bp: 'bp', px: 'fiyat', fx: 'kur', raw: 'sayı' };
export const KIND_TEXT = { viop: 'VİOP', bond: 'kâğıt', ois: 'OIS', off: 'offshore', masa: 'masa', expr: 'ifade', cell: 'hücre' };
/** A subject read as a cell is - a cell, or a cell of a bond's row / a VİOP contract's column: its unit can be chosen. */
const cellish = (s) => !!s && (s.kind === 'cell' || !!s.col || !!s.row);
const isNum = (v) => typeof v === 'number' && isFinite(v);
const HISTORY_AGAIN_MS = 5 * 60 * 1000;   // a drawn history is asked again this often (the value now: every refresh)

/** A change: "+3,2 bp", "−0,0150" (a price or FX level: in the item's own decimals). */
export function changeText(v, it) {
  if (!isNum(v)) return '';
  const bp = it.unit_name === 'bp';
  const d = bp ? 1 : (it.show === 'px' ? 3 : 4);
  return (v > 0 ? '+' : (v < 0 ? '−' : '')) + num(Math.abs(v), d, false) + (bp ? ' bp' : '');
}

/** The day's path as a small line (the open dashed). */
export function spark(points, open) {
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
export function band(z, now) {
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
export function savedDays() {
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
    this.deskBox = panel('watch-desk', 'Masa alarmları · herkese');
    this.deskAdd = h('button', { class: 'btn sm hidden', type: 'button', id: 'desk-add', title: 'Herkese çalan bir alarm (yalnızca yöneticiler)' }, 'Masa alarmı kur…');
    this.deskAdd.addEventListener('click', () => openWatchDialog(this.ctx, { focus: 'alarm', desk: true }));
    this.deskBox.parentElement.querySelector('header').appendChild(this.deskAdd);
    this.firedBox = panel('watch-fired', 'Bugün çalan alarmlar');
    const notesBody = panel('watch-notes', 'Masa notları · bugün (herkes görür)');
    this.notes = h('textarea', { class: 'inp chatbox', id: 'notes-text', rows: '6', spellcheck: 'false',
      placeholder: 'Bugün izlenecek seviyeler, sabah toplantısı, ihale, veri takvimi…' });
    this.notesInfo = h('span', { class: 'muted', id: 'notes-info' });
    const save = h('button', { class: 'btn primary', type: 'button', id: 'notes-save' }, 'Notları kaydet');
    save.addEventListener('click', () => this.saveNotes());
    notesBody.appendChild(this.notes);
    notesBody.appendChild(h('div', { class: 'chatrow actions' }, save, this.notesInfo));
    // each list on a launchpad, in the side drawer, in a window of its own
    for (const [body, list] of [[this.list, 'items'], [this.alarmBox, 'alarms'], [this.firedBox, 'fired']]) {
      toolsOf(body, true).append(...boxTools(() => ({ type: 'watch-list', list, w: 12 }), this.ctx));
    }
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
    this.fillDesk(d);
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
      .map((x, i) => h('th', { class: [0, 6, 8, 12].includes(i) ? 'l' : '', 'data-col': x === zh ? 'z' : null }, x))));
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
      btn('⋯', cellish(it.subject) ? 'Ad / birim' : 'Ad', (e) => this.more(it, e));
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
    this.columns('list', t, box);
  }

  /** Each user hides columns of the lists their own way (a right click on a caption, or "Sütunlar"). */
  columns(name, t, box) {
    this.cols = this.cols || {};
    if (!this.cols[name]) this.cols[name] = new TableColumns('watch/' + name);
    this.cols[name].attach(t, toolsOf(box, true));
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
    this.columns('alarms', t, box);
  }

  // ------------------------------------------------------------------ the desk's alarms (everyone's)
  fillDesk(d) {
    const desk = d.desk || { alarms: [], system: [], log: [], open: [] };
    const admin = !!desk.admin;
    this.deskAdd.classList.toggle('hidden', !admin);
    const box = this.deskBox;
    // the settings form keeps what is being typed into it while the page refreshes
    const editing = this.deskForm && this.deskForm.contains(document.activeElement);
    const keep = editing ? this.deskForm : null;
    clear(box);
    const status = (entry, mute, active) => {
      const out = [];
      if (entry) {
        out.push(h('span', { class: 'pill ' + (entry.ack_by || entry.closed_at ? 'neu' : 'warn') }, 'çaldı · ' + entry.at));
        if (entry.ack_name) out.push(h('span', { class: 'ack' }, '✓ Gördüm – ' + entry.ack_name + ' bakıyor (' + entry.ack_at + ')'));
        else if (entry.closed_at) out.push(h('span', { class: 'sub' }, entry.closed_why || 'kapandı'));
        else out.push(h('span', { class: 'sub' }, 'cevap bekliyor'));
      } else if (active !== undefined) out.push(h('span', { class: 'pill neu' }, active ? 'bekliyor' : 'çaldı'));
      if (mute) out.push(h('span', { class: 'sub', title: 'Yalnızca sizin için: başkalarına çalmaya devam eder' }, '🔕 sizin için susturuldu · bitiş ' + mute.until.slice(11, 16)));
      return out;
    };
    const acts = (alarm, entry, mute, label) => {
      const td = h('td', { class: 'l acts' });
      if (entry && !entry.ack_by && !entry.closed_at) {
        const ack = h('button', { class: 'iconbtn', type: 'button', title: 'Herkese "ben bakıyorum" der' }, 'Gördüm');
        ack.addEventListener('click', async () => {
          ack.disabled = true;
          try { await ackDesk(entry.seq); this.ctx.refreshNow(); } catch (err) { errorToast(err); ack.disabled = false; }
        });
        td.appendChild(ack);
      }
      const m = h('button', { class: 'iconbtn', type: 'button', title: 'Yalnızca benim için sustur: ' + label + ' (başkalarına çalmaya devam eder)' }, mute ? '🔕' : '🔔');
      m.addEventListener('click', (e) => { const r = m.getBoundingClientRect(); muteMenu(r.left, r.bottom + 2, alarm, !!mute, () => this.ctx.refreshNow()); e.stopPropagation(); });
      td.appendChild(m);
      return td;
    };
    // ---- the alarms an administrator set
    box.appendChild(h('div', { class: 'desk-sub' }, 'Masanın alarmları'));
    if (!desk.alarms.length) {
      box.appendChild(h('div', { class: 'empty' }, admin ? 'Masa alarmı yok: "Masa alarmı kur…" ile herkese çalan bir alarm kurun (ya da alarm penceresinde '
        + '"Masa alarmı: herkese çalar"ı işaretleyin). Piyasanın değerleriyle denetlenir.' : 'Masa alarmı yok (yöneticiler kurar; çalınca herkesin ekranında uyarı çıkar).'));
    } else {
      const t = h('table', { class: 'plain watch', id: 'desk-table' });
      t.appendChild(h('tr', null, ...['Ad', 'Koşul', 'Şimdi', 'Hareket / z', 'Uzaklık', 'Durum', 'Kuran', 'Not', ''].map((x, i) => h('th', { class: [0, 1, 5, 6, 7, 8].includes(i) ? 'l' : '' }, x))));
      for (const a of desk.alarms) {
        const td = acts(a.id, a.entry && a.entry.kind === 'fired' ? a.entry : null, a.mute, a.label);
        if (admin) {
          if (!a.active) {
            const re = h('button', { class: 'iconbtn', type: 'button', title: 'Aynı koşulla herkese yeniden kur' }, 'Yeniden kur');
            re.addEventListener('click', () => this.act('/api/alarms/rearm', { id: a.id, desk: true }, 'Masa alarmı yeniden kuruldu'));
            td.appendChild(re);
          }
          const del = h('button', { class: 'iconbtn', type: 'button', title: 'Masa alarmını sil (herkesten)' }, '✕');
          del.addEventListener('click', async () => {
            if (!(await confirmDialog('Masa alarmını sil', a.label + ' (' + (a.condition || '') + ') herkesten silinsin mi?', 'Sil', true))) return;
            await this.act('/api/alarms/remove', { id: a.id, desk: true }, 'Masa alarmı silindi');
          });
          td.appendChild(del);
        }
        const open = a.entry && !a.entry.ack_by && !a.entry.closed_at;
        t.appendChild(h('tr', { 'data-id': a.id, class: (a.active ? '' : 'fired') + (open ? ' open' : '') },
          h('td', { class: 'l', title: a.what + (a.detail ? ' · ' + a.detail : '') }, a.label, !isNum(a.now) && a.detail ? h('span', { class: 'sub' }, a.detail) : null),
          h('td', { class: 'l cond' }, a.condition || ''), h('td', null, a.now_text || ''),
          h('td', null, a.mode && a.mode !== 'level' ? (a.measure_text || '–') : ''), h('td', { title: 'Koşulun sağlanmasına kalan' }, a.distance_text || ''),
          h('td', { class: 'l' }, ...status(a.entry && a.entry.kind === 'fired' ? a.entry : null, a.mute, a.active)),
          h('td', { class: 'l muted' }, a.by_name || ''), h('td', { class: 'l muted' }, a.note || ''), td));
      }
      box.appendChild(t);
    }
    // ---- the system's own
    box.appendChild(h('div', { class: 'desk-sub' }, 'Sistem alarmları'));
    const st = h('table', { class: 'plain watch', id: 'desk-system' });
    st.appendChild(h('tr', null, ...['Ad', 'Durum', 'Ne zaman', 'Ayrıntı', ''].map((x) => h('th', { class: 'l' }, x))));
    for (const s of desk.system || []) {
      const state = s.state === 'alarm' ? h('span', { class: 'pill warn' }, 'ALARM' + (s.since ? ' · ' + s.since : ''))
        : s.state === 'ok' ? h('span', { class: 'pill ok' }, 'normal')
          : h('span', { class: 'pill neu' }, s.state === 'off' ? 'kapalı' : 'denetlenmiyor');
      const open = s.entry && !s.entry.ack_by && !s.entry.closed_at;
      st.appendChild(h('tr', { 'data-kind': s.kind, class: open ? 'open' : '' }, h('td', { class: 'l' }, s.label),
        h('td', { class: 'l' }, state, ...status(s.entry, s.mute)), h('td', { class: 'l muted' }, s.threshold || ''),
        h('td', { class: 'l', style: { whiteSpace: 'normal' } }, s.text || ''), acts('sys:' + s.kind, s.entry, s.mute, s.label)));
    }
    box.appendChild(st);
    // ---- the settings: the administrators change them, everyone reads them
    const cfg = desk.settings || {};
    if (admin) {
      if (keep) box.appendChild(keep);
      else box.appendChild(this.deskSettings(cfg));
    } else {
      box.appendChild(h('div', { class: 'note' }, 'Piyasa saatleri ' + (cfg.market_open || '') + '–' + (cfg.market_close || '') + ' (masanın iş günleri) · '
        + cfg.tick_stale + ' sn tick gelmezse veri bayat · veri akışı alarmı ' + (cfg.feed_alarm ? cfg.feed_minutes + ' dk' : 'kapalı')
        + ' · TLREF ' + (cfg.tlref_alarm ? cfg.tlref_due : 'kapalı') + ' · ayarları yöneticiler değiştirir.'));
    }
    // ---- the day's log
    box.appendChild(h('div', { class: 'desk-sub' }, 'Bugünün kaydı'));
    if (!desk.log.length) { box.appendChild(h('div', { class: 'empty' }, 'Bugün masa alarmlarında bir şey olmadı.')); return; }
    const lt = h('table', { class: 'plain watch', id: 'desk-log' });
    lt.appendChild(h('tr', null, ...['Saat', 'Olay', 'Alarm', 'Kim', 'Ayrıntı'].map((x) => h('th', { class: 'l' }, x))));
    for (const e of desk.log.slice().reverse()) {
      lt.appendChild(h('tr', null, h('td', { class: 'l' }, e.at), h('td', { class: 'l' }, (desk.actions || {})[e.kind] || e.kind),
        h('td', { class: 'l' }, e.label || ''), h('td', { class: 'l' }, e.by_name || ''), h('td', { class: 'l', style: { whiteSpace: 'normal' } }, e.text || '')));
    }
    box.appendChild(lt);
  }

  /** The administrators' settings of the desk: market hours, when data counts as stale, the system alarms. */
  deskSettings(cfg) {
    const time = (key) => h('input', { class: 'inp', id: 'desk-set-' + key, value: cfg[key] || '', placeholder: 'SS:DD', maxlength: '5' });
    const n = (key, unit) => h('div', { class: 'lvl' }, h('input', { class: 'inp num', id: 'desk-set-' + key, value: String(cfg[key] || ''), inputmode: 'numeric' }), h('span', { class: 'unit muted' }, unit));
    const on = (key) => h('input', { type: 'checkbox', id: 'desk-set-' + key, checked: cfg[key] ? true : null });
    const f = (label, el) => h('div', { class: 'field' }, h('label', null, label), el);
    const form = h('div', { class: 'desk-settings', id: 'desk-settings' },
      f('Piyasa açılış', time('market_open')), f('Kapanış', time('market_close')), f('Tick gelmezse bayat', n('tick_stale', 'sn')),
      h('label', { class: 'check' }, on('feed_alarm'), 'Veri akışı alarmı'), f('akmazsa', n('feed_minutes', 'dk')),
      h('label', { class: 'check' }, on('tlref_alarm'), 'TLREF alarmı'), f('fixing gelmediyse', time('tlref_due')),
      h('label', { class: 'check' }, on('db_alarm'), 'Veritabanı alarmı'));
    const save = h('button', { class: 'btn primary sm', type: 'button', id: 'desk-set-save' }, 'Ayarları kaydet');
    save.addEventListener('click', async () => {
      const values = {};
      for (const el of form.querySelectorAll('input')) values[el.id.replace('desk-set-', '')] = el.type === 'checkbox' ? el.checked : el.value;
      save.disabled = true;
      const res = await this.act('/api/alarms/settings', { values }, 'Masa ayarları kaydedildi');
      save.disabled = false;
      if (res) { this.deskForm = null; this.ctx.refreshNow(); }
    });
    form.appendChild(save);
    this.deskForm = form;
    return form;
  }

  /** The top bar's "masa alarmı" leads here. */
  focusPanel(id) {
    const el = this.host.querySelector('#' + id);
    if (!el) return;
    el.scrollIntoView({ block: 'start', behavior: 'smooth' });
    el.classList.remove('focus');
    void el.offsetWidth;
    el.classList.add('focus');
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
    this.columns('fired', t, box);
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
    if (cellish(it.subject)) {                                // a cell does not say what it holds: how to read it
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
