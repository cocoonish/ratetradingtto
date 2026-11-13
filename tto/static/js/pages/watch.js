// İzleme · Alarmlar: the user's watch list (any cell of any page: right click → "İzlemeye ekle"), how each item
// moved today (open, change, low / high, its path, since a reference taken on purpose), the alarms on cells, the
// ones that fired today, and the desk's notes of the day.
import { api } from '../api.js';
import { h, clear, toast, errorToast, menu, modal, confirmDialog } from '../ui.js';
import { num } from '../format.js';
import { openAlarmDialog, askPermission } from '../alarms.js';

const OP = { '>=': '≥', '<=': '≤', x: 'kesişir' };
const UNIT_TEXT = { pct: 'faiz (%)', frac: 'faiz (oran, %)', bp: 'bp', px: 'fiyat', fx: 'kur' };
const isNum = (v) => typeof v === 'number' && isFinite(v);

/** A change: "+3,2 bp", "−0,0150" (a price or FX level: in the item's own decimals). */
function changeText(v, it) {
  if (!isNum(v)) return '';
  const bp = it.unit_name === 'bp';
  const d = bp ? 1 : (it.unit === 'fx' ? 4 : 3);
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

export class WatchPage {
  constructor(host, ctx) {
    this.host = host;
    this.ctx = ctx;
    this.data = null;
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
    const add = h('button', { class: 'btn', type: 'button', id: 'watch-add' }, 'Hücre ekle…');
    add.addEventListener('click', () => this.addCell());
    const base = h('button', { class: 'btn', type: 'button', id: 'watch-base', title: 'Her kalemin şimdiki seviyesini referans al: değişim ayrıca bundan sonrası için de gösterilir (ör. sabah toplantısı)' }, 'Referansı şimdi al');
    base.addEventListener('click', () => this.takeBase(null));
    this.perm = h('button', { class: 'btn', type: 'button', id: 'watch-perm', title: 'Alarm çalınca tarayıcı bildirimi göster' }, 'Bildirimlere izin ver');
    this.perm.addEventListener('click', () => { askPermission(); setTimeout(() => this.permState(), 800); });
    tools.appendChild(preset);
    tools.appendChild(add);
    tools.appendChild(base);
    tools.appendChild(this.perm);
    tools.appendChild(h('span', { class: 'muted' }, 'Bir tablodaki hücreye sağ tıklayın: "İzlemeye ekle" ya da "Alarm kur…"'));
    this.host.appendChild(tools);
    const panel = (id, title) => {
      const body = h('div', { class: 'body' });
      const el = h('section', { class: 'panel wide', id }, h('header', null, h('h2', null, title)), body);
      this.host.appendChild(el);
      return body;
    };
    this.list = panel('watch-list', 'İzleme listesi');
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
    const d = await api.get('/api/watch');
    this.data = d;
    this.fillList(d);
    this.fillAlarms(d);
    this.fillFired(d);
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
      box.appendChild(h('div', { class: 'empty' }, 'İzleme listesi boş: "Hazır grup ekle" ile masa özetini ya da OIS eğrisini ekleyin, '
        + 'ya da herhangi bir sayfadaki hücreye sağ tıklayıp "İzlemeye ekle"yi seçin.'));
      return;
    }
    const t = h('table', { class: 'plain watch', id: 'watch-table' });
    t.appendChild(h('tr', null, ...['Ad', 'Şimdi', 'Açılış', 'Gün', 'Düşük', 'Yüksek', 'Gün içi', 'Referans', 'Ref\'ten', 'Son hareket', '']
      .map((x, i) => h('th', { class: i === 0 || i === 6 || i === 10 ? 'l' : '' }, x))));
    d.items.forEach((it, k) => {
      const cls = (v) => (isNum(v) && Math.abs(v) > 1e-9 ? (v > 0 ? 'pos' : 'neg') : '');
      const name = h('td', { class: 'l name', title: it.book + ' · ' + it.ref + ' · ' + (UNIT_TEXT[it.unit] || it.unit) }, it.label);
      name.addEventListener('dblclick', () => this.rename(it));
      const acts = h('td', { class: 'l acts' });
      const btn = (label, title, fn) => { const b = h('button', { class: 'iconbtn', type: 'button', title }, label); b.addEventListener('click', fn); acts.appendChild(b); return b; };
      btn('🔔', 'Bu kaleme alarm kur', () => openAlarmDialog(this.ctx, { book: it.book, ref: it.ref, label: it.label, text: it.now }));
      btn('⟲', 'Referansı şimdi al', () => this.takeBase(it.id));
      btn('▲', 'Yukarı', () => this.move(it, -1)).disabled = k === 0;
      btn('▼', 'Aşağı', () => this.move(it, 1)).disabled = k === d.items.length - 1;
      btn('⋯', 'Ad / birim', (e) => this.more(it, e));
      btn('✕', 'Listeden çıkar', () => this.remove(it));
      const tr = h('tr', { 'data-id': it.id }, name, h('td', { class: 'now' }, it.now || ''), h('td', null, it.open_text || ''),
        h('td', { class: cls(it.change) }, changeText(it.change, it)), h('td', null, it.low_text || ''), h('td', null, it.high_text || ''),
        h('td', { class: 'l' }, spark(it.path, it.open)),
        h('td', { title: it.base_at ? 'Referans alındı: ' + it.base_at : 'Referans yok: ⟲ ile alın' }, it.base_text || ''),
        h('td', { class: cls(it.since_base) }, changeText(it.since_base, it)), h('td', { class: 'muted' }, it.moved || ''), acts);
      t.appendChild(tr);
    });
    box.appendChild(t);
  }

  fillAlarms(d) {
    const box = clear(this.alarmBox);
    if (!d.alarms.length) {
      box.appendChild(h('div', { class: 'empty' }, 'Alarm yok: bir hücreye sağ tıklayıp "Alarm kur…" ya da listedeki 🔔.'));
      return;
    }
    const t = h('table', { class: 'plain watch', id: 'alarm-table' });
    t.appendChild(h('tr', null, ...['Ad', 'Koşul', 'Seviye', 'Şimdi', 'Uzaklık', 'Durum', 'Not', ''].map((x, i) => h('th', { class: [0, 5, 6, 7].includes(i) ? 'l' : '' }, x))));
    for (const a of d.alarms) {
      const dist = isNum(a.distance) ? (a.unit_name === 'bp' ? num(a.distance, 1, false) + ' bp' : num(a.distance, 4, false)) : '';
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
      t.appendChild(h('tr', { 'data-id': a.id, class: a.active ? '' : 'fired' }, h('td', { class: 'l', title: a.book + ' · ' + a.ref }, a.label),
        h('td', null, OP[a.op] || a.op), h('td', null, a.level_text || ''), h('td', null, a.now_text || ''), h('td', null, dist),
        h('td', { class: 'l' }, state), h('td', { class: 'l muted' }, a.note || ''), acts));
    }
    box.appendChild(t);
  }

  fillFired(d) {
    const box = clear(this.firedBox);
    if (!d.fired.length) { box.appendChild(h('div', { class: 'empty' }, 'Bugün çalan alarm yok.')); return; }
    const t = h('table', { class: 'plain watch', id: 'fired-table' });
    t.appendChild(h('tr', null, ...['Saat', 'Ad', 'Koşul', 'Seviye', 'Değer', 'Not'].map((x, i) => h('th', { class: [0, 1, 5].includes(i) ? 'l' : '' }, x))));
    for (const e of d.fired.slice().reverse()) {
      t.appendChild(h('tr', null, h('td', { class: 'l' }, e.time), h('td', { class: 'l' }, e.label), h('td', null, OP[e.op] || e.op),
        h('td', null, e.level_text || ''), h('td', null, e.value_text || ''), h('td', { class: 'l muted' }, e.note || '')));
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
    const m = modal({ title: 'Ad · ' + it.ref, width: 420 });
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
    menu(r.left, r.bottom + 2, [{ label: 'Adını değiştir…', action: () => this.rename(it) }, { sep: true }, { header: 'Değişimin birimi' }]
      .concat(Object.entries(UNIT_TEXT).map(([u, t]) => ({ label: (it.unit === u ? '✓ ' : '   ') + t, action: () => this.act('/api/watch/update', { id: it.id, unit: u }) }))));
  }

  addCell() {
    const m = modal({ title: 'Hücre ekle', width: 480 });
    const ref = h('input', { class: 'inp', id: 'watch-ref', placeholder: 'örn. OIS_MAIN!B14 ya da Forward!F2' });
    const label = h('input', { class: 'inp', id: 'watch-label', placeholder: 'ad (isteğe bağlı)', maxlength: '60' });
    m.body.appendChild(h('p', { class: 'muted' }, 'Tablodaki bir hücreye sağ tıklayıp "İzlemeye ekle" demek daha kolay; burada sayfa!hücre adresi yazılır.'));
    m.body.appendChild(h('div', { class: 'field' }, h('label', null, 'Hücre'), ref));
    m.body.appendChild(h('div', { class: 'field' }, h('label', null, 'Ad'), label));
    const ok = h('button', { class: 'btn primary', type: 'button', id: 'watch-add-ok' }, 'Ekle');
    ok.addEventListener('click', async () => {
      const res = await this.act('/api/watch/add', { book: 'tto', ref: ref.value.trim(), label: label.value.trim() },
        (r) => (r.added ? 'Eklendi' : 'Zaten listede'));
      if (res) m.close();
    });
    m.foot.appendChild(ok);
    ref.focus();
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

  destroy() {}
}
