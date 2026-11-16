// An item of a launchpad, of the side drawer or of a pop-out window: a table of a page, live and editable in place
// (the same cells of the same book: a value typed here is the page's value too).  Every box on screen is brought up to
// date in one request (/api/panels), whatever pages its tables come from - a browser has six connections to the
// dashboard, and a launchpad may show tables of ten pages.
import { api } from './api.js';
import { h, clear, menu, modal, promptDialog, toast } from './ui.js';
import { Grid, copyGrid, findCell } from './grid.js';
import { Chart } from './chart.js';
import { bondCardLinks, bondFlags } from './bonds.js';
import { WIDTHS } from './layout.js';

let seq = 0;

/** Every box on screen, brought up to date together: one request for all of them. */
export const hub = {
  boxes: new Set(),
  busy: null,
  again: false,

  add(box) { this.boxes.add(box); },
  remove(box) { this.boxes.delete(box); },

  /** Bring the boxes on screen up to date (a collapsed one, or one out of the document, waits). */
  refresh() {
    if (this.busy) { this.again = true; return this.busy; }
    this.busy = (async () => {
      try {
        do { this.again = false; await this.once(); } while (this.again);
      } finally { this.busy = null; }
    })();
    return this.busy;
  },

  async once() {
    const live = [...this.boxes].filter((b) => b.wanted());
    if (!live.length) return;
    let res;
    try {
      res = await api.post('/api/panels', { items: live.map((b) => b.request()) });
    } catch (err) {
      if (!err.network && err.status !== 401) for (const b of live) if (!b.entry) b.fail(err.message);
      return;
    }
    for (const b of live) if (this.boxes.has(b)) b.apply((res.panels || {})[b.key]);
  },

  /** Boxes whose numbers are older than the latest generation, among those on screen: dimmed until they are not. */
  markStale(gen) {
    for (const b of this.boxes) if (b.wanted() && b.entry && (b.gen || 0) < gen) b.el.classList.add('stale');
  },

  setAdhoc(on) {
    for (const b of this.boxes) b.setAdhoc(on);
  },

  /** The <td> of a workbook cell in a box under ``root`` (a launchpad, the drawer). */
  findCell(ref, root) {
    for (const b of this.boxes) {
      if (!b.grid || (root && !root.contains(b.el))) continue;
      const td = findCell(ref, b.el);
      if (td) return td;
    }
    return null;
  },
};

// ---------------------------------------------------------------------- the parts of a table (the picker)
/** The name of a row: its first text from the left (as the server reads it - service._row_label). */
export function rowLabel(row) {
  for (const c of row || []) {
    if (!c || c.sk || c.k !== 's') continue;
    const t = String(c.t || '').split(/\s+/).filter(Boolean).join(' ');
    if (t) return t;
  }
  return null;
}

function headerRow(row) {
  let n = 0, strong = 0;
  for (const c of row) {
    if (!c || c.sk || !c.t) continue;
    if (c.k !== 's' || c.i) return false;
    if (c.c || (c.f && c.f !== 'hd' && c.f !== 'sub')) return false;
    n += 1;
    if (c.b || c.f === 'hd') strong += 1;
  }
  return n >= 2 && strong * 2 >= n;
}

/** The rows at the top that name the columns (and a lone title above them): a part of the table keeps them. */
export function captionRows(rows, nums) {
  const out = new Set();
  (nums || []).forEach((r, i) => { if (r === 0) out.add(i); });
  for (let i = 0; i < rows.length; i++) {
    if (out.has(i)) continue;
    if (rows.length > 1 && headerRow(rows[i]) && out.size < 3) out.add(i);
    else if (i === 0 && rows[i].filter((c) => c && !c.sk && c.t).length <= 1) out.add(i);
    else break;
  }
  return out;
}

/** The caption over column j (the caption rows' texts, a merged one included). */
function columnCaption(data, heads, j) {
  const parts = [];
  for (const i of heads) {
    const row = data.rows[i] || [];
    for (let k = j; k >= 0; k--) {
      const c = row[k];
      if (!c || c.sk) continue;
      if (k + (c.cs || 1) > j && c.t && String(c.t).trim()) parts.push(String(c.t).trim());
      break;
    }
  }
  return [...new Set(parts)].join(' · ');
}

const mark = (on) => (on ? '✓ ' : '    ');

// ---------------------------------------------------------------------- one box
export class PanelBox {
  /**
   * item: {type: 'table', id, view, panel, title?, w, h, rows?, cols?, all?, collapsed?}
   * opts: {ctx, place: 'launchpad' | 'drawer' | 'pop', adhoc(): bool, edit(change) - the item changed (saved by the
   *        owner), remove(), move(step), extra(box) - more menu lines, draggable}
   */
  constructor(item, opts) {
    this.item = item;
    this.opts = opts;
    this.ctx = opts.ctx;
    this.key = 'b' + (++seq);
    this.gen = 0;
    this.as = null;
    this.book = null;
    this.entry = null;
    this.grid = null;
    this.chart = null;
    this.dead = false;
    this.el = h('section', { class: 'panel lp-item' + (opts.place === 'launchpad' ? '' : ' full') });
    this.el.__box = this;
    this.titleEl = h('h2');
    this.src = h('a', { class: 'lp-src', href: '#/' + item.view + '?p=' + encodeURIComponent(item.panel), title: 'Tablonun sayfasına git' });
    this.src.addEventListener('click', (e) => { e.preventDefault(); this.goSource(); });
    this.tools = h('div', { class: 'tools' });
    const head = h('header');
    if (opts.draggable) {
      this.handle = h('span', { class: 'lp-drag', title: 'Sürükleyip bırakarak yerini değiştirin', draggable: 'true' }, '⠿');
      head.appendChild(this.handle);
    }
    head.appendChild(this.titleEl);
    head.appendChild(this.src);
    head.appendChild(this.tools);
    this.body = h('div', { class: 'body' }, h('div', { class: 'loading' }, 'Yükleniyor…'));
    this.note = h('div', { class: 'note hidden' });
    this.el.appendChild(head);
    this.el.appendChild(this.body);
    this.el.appendChild(this.note);
    // the tools: Kopyala first (the columns' button goes after it), the item's menu, collapse, and - in the drawer - ✕
    const cp = h('button', { class: 'iconbtn', type: 'button', title: 'Tüm tabloyu kopyala (Excel\'e yapıştırılabilir)' }, 'Kopyala');
    cp.addEventListener('click', () => { if (this.grid) copyGrid(this.grid, false); });
    this.tools.appendChild(cp);
    const more = h('button', { class: 'iconbtn', type: 'button', title: 'Genişlik, yükseklik, satır / sütun seçimi, ad …' }, '⋯');
    more.dataset.action = 'item-menu';
    more.addEventListener('click', (e) => {
      e.stopPropagation();
      const r = more.getBoundingClientRect();
      menu(r.left, r.bottom + 4, this.menuItems());
    });
    this.tools.appendChild(more);
    this.colBtn = h('button', { class: 'iconbtn', type: 'button', title: 'Daralt / aç' });
    this.colBtn.addEventListener('click', () => this.setCollapsed(!this.item.collapsed));
    this.tools.appendChild(this.colBtn);
    if (opts.place === 'drawer' && opts.remove) {
      const x = h('button', { class: 'iconbtn', type: 'button', title: 'Yan panelden kaldır' }, '✕');
      x.dataset.action = 'unpin';
      x.addEventListener('click', () => opts.remove());
      this.tools.appendChild(x);
    }
    this.show(item);
    hub.add(this);
  }

  /** The item as the layout has it now (width, height, name, part of the table, collapsed). */
  show(item) {
    const before = this.item;
    this.item = item;
    this.el.dataset.key = item.view + '/' + item.panel;
    this.el.dataset.id = item.id;
    this.el.dataset.w = String(item.w || 6);
    this.el.dataset.h = String(item.h || 'auto');
    if (this.opts.place === 'launchpad') this.el.style.gridColumn = 'span ' + (item.w || 6);
    const fixed = typeof item.h === 'number';
    this.body.style.height = fixed ? item.h + 'px' : '';
    this.el.classList.toggle('fixed', fixed);
    this.el.classList.toggle('collapsed', !!item.collapsed);
    this.colBtn.textContent = item.collapsed ? '▸' : '▾';
    const part = (x) => JSON.stringify([x.view, x.panel, x.rows || [], x.cols || [], !!x.all]);
    if (before !== item && part(before) !== part(item)) {
      this.gen = 0;                                  // another table, or another part of it: all of it again
      this.as = null;
      this.entry = null;
    }
    this.paintTitle();
  }

  paintTitle() {
    const e = this.entry;
    const t = this.item.title || (e && e.title) || (this.missing ? this.item.view + ' / ' + this.item.panel : 'Tablo');
    this.titleEl.textContent = t;
    this.titleEl.title = t + (this.item.title && e && e.title && e.title !== this.item.title ? '\nTablonun kendi adı: ' + e.title : '');
    const where = this.page ? this.page + (this.tab ? ' › ' + this.tab : '') : this.item.view;
    const part = (this.item.rows && this.item.rows.length) || (this.item.cols && this.item.cols.length) ? ' · bir kısmı' : '';
    this.src.textContent = where + part;
  }

  /** Brought up to date with the others: on screen (a closed drawer's wait), open, not removed. */
  wanted() {
    return !this.dead && !this.item.collapsed && this.el.isConnected && (!this.opts.live || this.opts.live());
  }

  request() {
    const it = this.item;
    const r = { key: this.key, view: it.view, panel: it.panel };
    if (it.rows && it.rows.length) r.rows = it.rows;
    if (it.cols && it.cols.length) r.cols = it.cols;
    if (it.all) r.all = true;
    if (this.entry && this.gen && this.as) { r.since = this.gen; r.as = this.as; }
    return r;
  }

  fail(message) {
    clear(this.body);
    this.body.appendChild(h('div', { class: 'lp-missing' }, 'Tablo okunamadı: ' + message));
  }

  /** The answer of the batch for this box. */
  apply(ans) {
    if (!ans || this.dead) return;
    if (ans.missing) { this.showMissing(ans); return; }
    if (this.missing) { this.missing = null; this.el.classList.remove('missing'); clear(this.body); }
    this.as = ans.as || null;
    if (ans.unchanged) {
      this.gen = Math.max(this.gen || 0, ans.gen || 0);
      this.el.classList.remove('stale');
      return;
    }
    const e = ans.entry || {};
    this.book = ans.book || null;
    this.page = ans.page || '';
    this.tab = ans.tab || '';
    if (e.error) {
      this.dropContent();
      clear(this.body);
      this.body.appendChild(h('div', { class: 'lp-missing' }, 'Tabloda hata: ' + e.error));
    } else if (e.type === 'chart') {
      if (!e.data) { this.dropContent(); clear(this.body); this.body.appendChild(h('div', { class: 'chart-empty' }, 'Grafik bulunamadı')); }
      else if (this.chart) this.chart.update(e.data);
      else { this.dropContent(); clear(this.body); this.chart = new Chart(this.body, e.data); }
    } else if (e.type === 'image') {
      this.dropContent();
      clear(this.body);
      this.body.appendChild(h('img', { class: 'sheet-image', src: e.src, alt: e.title || 'Resim' }));
    } else if (e.data) {
      if (this.grid && this.grid.book === this.book) {
        if (this.grid.update(e.data, true) === false) { this.entry = e; this.paintTitle(); return; }      // (being typed into: later)
      } else {
        this.dropContent();
        clear(this.body);
        this.grid = new Grid({ book: this.book, data: e.data, editable: true, adhoc: this.opts.adhoc ? this.opts.adhoc() : false,
          name: e.type === 'notes' ? null : 'v/' + this.item.view + '/' + this.item.panel, tools: this.tools });
        this.body.appendChild(this.grid.el);
        if (e.card === 'bond') bondCardLinks(this.ctx, this.grid.el);
        if (e.flags === 'dibs') bondFlags(this.ctx, this.grid.el);
      }
    } else {
      this.dropContent();
      clear(this.body);
      this.body.appendChild(h('div', { class: 'empty' }, 'Bu tabloda şu an gösterilecek bir şey yok'));
    }
    this.entry = e;
    this.gen = ans.gen || 0;
    this.el.classList.remove('stale');
    const partMissing = e.data && e.data.part_missing;
    this.note.textContent = partMissing ? 'Seçtiğiniz satır / sütunların hiçbiri tabloda artık yok – bütün tablo gösteriliyor (⋯ → Satırlar ve sütunlar).' : '';
    this.note.classList.toggle('hidden', !partMissing);
    this.paintTitle();
  }

  dropContent() {
    if (this.chart) { this.chart.destroy(); this.chart = null; }
    this.grid = null;
  }

  /** The table is not there any more, or not this user's to see: said in the box; the rest of the page goes on. */
  showMissing(ans) {
    this.missing = ans;
    this.entry = null;
    this.gen = 0;
    this.dropContent();
    this.el.classList.add('missing');
    this.el.classList.remove('stale');
    clear(this.body);
    const denied = ans.status === 403;
    const box = h('div', { class: 'lp-missing' },
      h('b', null, denied ? 'Erişim yok' : 'Bu tablo artık yok'),
      h('span', null, ' – ' + (denied ? 'bu tablonun sayfası yalnızca yöneticilere açık.' : 'sayfası ya da kendisi güncellemeyle kaldırılmış olabilir.')));
    if (this.opts.remove) {
      const b = h('button', { class: 'btn sm', type: 'button' }, 'Kaldır');
      b.addEventListener('click', () => this.opts.remove());
      box.appendChild(h('div', { style: { marginTop: '6px' } }, b));
    }
    this.body.appendChild(box);
    this.page = '';
    this.paintTitle();
  }

  setAdhoc(on) {
    if (this.grid) this.grid.opts.adhoc = !!on;
  }

  setCollapsed(on) {
    if (this.opts.edit) this.opts.edit({ collapsed: !!on });
    else this.show(Object.assign({}, this.item, { collapsed: !!on }));
    if (!on) hub.refresh();
  }

  goSource() {
    if (this.ctx.gotoSource) this.ctx.gotoSource(this.item.view, this.item.panel);
    else this.ctx.goto(this.item.view, this.item.panel);
  }

  menuItems() {
    const it = this.item;
    const o = this.opts;
    const items = [];
    if (o.edit && o.place === 'launchpad') {
      items.push({ header: 'Genişlik' });
      for (const [w, label] of WIDTHS) items.push({ label: mark(it.w === w) + label, action: () => o.edit({ w }) });
    }
    if (o.edit) {
      items.push({ header: 'Yükseklik' });
      items.push({ label: mark(it.h === 'auto') + 'Otomatik (tablo kadar)', action: () => o.edit({ h: 'auto' }) });
      for (const px of [240, 360, 480, 640]) items.push({ label: mark(it.h === px) + px + ' px – içinde kaydırılır', action: () => o.edit({ h: px }) });
      items.push({ label: (typeof it.h === 'number' && ![240, 360, 480, 640].includes(it.h) ? mark(true) + it.h + ' px · ' : mark(false)) + 'Başka bir yükseklik…',
        action: () => this.askHeight() });
      items.push({ sep: true });
      items.push({ label: 'Satırlar ve sütunlar…', action: () => this.openPicker() });
      items.push({ label: 'Yeniden adlandır…', action: () => this.rename() });
      if (it.title) items.push({ label: 'Tablonun kendi adına dön', action: () => o.edit({ title: null }) });
      if (o.move) {
        const vertical = o.place === 'drawer';
        items.push({ label: vertical ? 'Yukarı taşı' : 'Sola taşı', action: () => o.move(-1) });
        items.push({ label: vertical ? 'Aşağı taşı' : 'Sağa taşı', action: () => o.move(1) });
      }
      items.push({ sep: true });
    }
    if (o.extra) items.push(...o.extra(this));
    items.push({ label: 'Tablonun sayfasına git', action: () => this.goSource() });
    if (o.remove) {
      items.push({ sep: true });
      items.push({ label: o.place === 'drawer' ? 'Yan panelden kaldır' : 'Launchpad\'den kaldır', action: () => o.remove() });
    }
    return items;
  }

  async askHeight() {
    const v = await promptDialog('Yükseklik', 'Piksel (80–2400); tablo bu yükseklikte, içinde kaydırılır', typeof this.item.h === 'number' ? String(this.item.h) : '400');
    if (v === null) return;
    const n = Math.round(Number(v));
    if (!Number.isFinite(n) || n < 80 || n > 2400) { toast('Yükseklik 80 ile 2400 piksel arasında olmalı', 'err'); return; }
    this.opts.edit({ h: n });
  }

  async rename() {
    const v = await promptDialog('Yeniden adlandır', 'Bu kutunun adı (yalnızca sizin launchpad\'inizde)', this.item.title || (this.entry && this.entry.title) || '');
    if (v === null) return;
    this.opts.edit({ title: v });
  }

  /** Which rows and columns of the table this box shows: the whole table to pick from, ticked as it is now. */
  async openPicker() {
    const it = this.item;
    let full;
    try {
      const res = await api.post('/api/panels', { items: [{ key: 'full', view: it.view, panel: it.panel, all: !!it.all }] });
      const a = (res.panels || {}).full || {};
      if (a.missing) { toast(a.error || 'Tablo yok', 'err'); return; }
      full = a.entry && a.entry.data;
    } catch (err) { toast(err.message, 'err'); return; }
    if (!full || !full.rows || !full.rows.length) { toast('Bu kutuda satır / sütun seçilecek bir tablo yok', 'err'); return; }
    const heads = captionRows(full.rows, full.r);
    const labels = full.rows.map(rowLabel);
    const count = new Map();
    labels.forEach((l) => { if (l) count.set(l, (count.get(l) || 0) + 1); });
    const width = full.rows[0].length;
    const letters = full.c && full.c.length === width ? full.c : null;
    const rowsNow = it.rows || [];
    const colsNow = it.cols || [];
    const m = modal({ title: 'Satırlar ve sütunlar · ' + (it.title || (this.entry && this.entry.title) || it.panel), width: 760 });
    m.box.classList.add('lp-picker');
    const rowBoxes = [];
    const colBoxes = [];
    const rowList = h('div', { class: 'lp-pick-list' });
    full.rows.forEach((row, i) => {
      if (heads.has(i)) return;
      const num = full.r ? full.r[i] : null;
      const label = labels[i];
      const preview = row.filter((c) => c && !c.sk && c.t).map((c) => String(c.t).trim()).slice(0, 5).join(' · ');
      if (!preview) return;                                         // (an empty spacer row)
      const key = label && count.get(label) === 1 ? label : (num || null);
      if (key === null) return;
      const on = !rowsNow.length || rowsNow.includes(key) || (num && rowsNow.includes(num)) || (label && rowsNow.includes(label));
      const box = h('input', { type: 'checkbox' });
      box.checked = !!on;
      box.dataset.key = JSON.stringify(key);
      rowBoxes.push(box);
      rowList.appendChild(h('label', { class: 'lp-pick', title: preview }, box,
        h('span', { class: 'n' }, num ? String(num) : ''), h('span', { class: 't' }, preview)));
    });
    const colList = h('div', { class: 'lp-pick-list' });
    if (letters) {
      for (let j = 0; j < width; j++) {
        const cap = columnCaption(full, [...heads], j);
        const box = h('input', { type: 'checkbox' });
        box.checked = !colsNow.length || colsNow.includes(letters[j]);
        box.dataset.key = letters[j];
        colBoxes.push(box);
        colList.appendChild(h('label', { class: 'lp-pick' }, box, h('span', { class: 'n' }, letters[j]), h('span', { class: 't' }, cap || '—')));
      }
    }
    const all = (boxes, on) => () => { for (const b of boxes) b.checked = on; };
    const side = (title, list, boxes, note) => h('div', { class: 'lp-pick-side' },
      h('div', { class: 'lp-pick-head' }, h('b', null, title),
        h('button', { class: 'btn sm', type: 'button', onclick: all(boxes, true) }, 'Tümü'),
        h('button', { class: 'btn sm', type: 'button', onclick: all(boxes, false) }, 'Hiçbiri')),
      note ? h('div', { class: 'muted', style: { fontSize: '11.5px', margin: '0 0 6px' } }, note) : null, list);
    m.body.appendChild(h('div', { class: 'lp-pick-cols' },
      side('Satırlar', rowList, rowBoxes, 'Başlık satırları her zaman görünür. Satır adıyla (ilk metni) – ad tekrar ediyorsa numarasıyla – hatırlanır.'),
      letters ? side('Sütunlar', colList, colBoxes, 'Sütun harfiyle hatırlanır; sıralamak için tablonun "Sütunlar" menüsü.') : null));
    const save = () => {
      const rowsOn = rowBoxes.filter((b) => b.checked).map((b) => JSON.parse(b.dataset.key));
      const colsOn = colBoxes.filter((b) => b.checked).map((b) => b.dataset.key);
      if (rowBoxes.length && !rowsOn.length) { toast('En az bir satır seçin', 'err'); return; }
      if (colBoxes.length && !colsOn.length) { toast('En az bir sütun seçin', 'err'); return; }
      const rows = rowsOn.length === rowBoxes.length ? null : rowsOn;
      const cols = colsOn.length === colBoxes.length ? null : colsOn;
      m.close();
      this.opts.edit({ rows, cols });
    };
    m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Vazgeç'));
    m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => { m.close(); this.opts.edit({ rows: null, cols: null }); } }, 'Bütün tablo'));
    m.foot.appendChild(h('button', { class: 'btn primary', type: 'button', id: 'lp-pick-save', onclick: save }, 'Kaydet'));
  }

  findCell(ref) {
    return findCell(ref, this.el);
  }

  destroy() {
    this.dead = true;
    this.dropContent();
    hub.remove(this);
  }
}

/** The item with ``change`` applied (a null drops a field: the title back to the table's own, the whole table again). */
export function changed(item, change) {
  const out = Object.assign({}, item);
  for (const k of Object.keys(change)) {
    const v = change[k];
    if (v === null || v === undefined || v === '' || (Array.isArray(v) && !v.length) || (k === 'collapsed' && !v)) delete out[k];
    else out[k] = v;
  }
  return out;
}
