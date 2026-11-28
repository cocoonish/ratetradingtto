// The columns a user hides in a table, and the order they put them in.  Everybody looks at the tables their own way:
// what is hidden and how the columns are ordered is kept with the account on the server, so any computer shows the
// same.  A table is named by its page ("v/dibs/B5": a table of a sheet, "eod/curve": one of the dashboard's own); a
// column by its letter in the sheet, or by its caption.
import { api } from './api.js';
import { h, menu, modal, toast } from './ui.js';

export const NO_COLUMNS = new Set();

const kept = new Map();           // table -> Set of the keys of the columns this user hid
const orders = new Map();         // table -> the keys of its columns in the order this user put them
const presets = new Map();        // table -> [{name, hide}]: ready views of it (the server's: DİBS Trading's Trading / RV / Risk)
const saving = new Map();         // table -> its last save: the saves of one table go one after the other
const listeners = new Set();      // fn(table) after this user hides or shows a column (false: no longer)

/** The keys of the columns of a table this user hid (a page that writes elsewhere what a hidden column held reads it). */
export function hiddenKeys(name) {
  return kept.get(name) || NO_COLUMNS;
}

/** ``fn(name)`` each time this user hides or shows a column of a table; it returns false when it wants no more. */
export function onHiddenChange(fn) {
  listeners.add(fn);
}

/** The columns this user hid and the orders they chose (on signing in, before the first table is drawn); a table they
 *  never chose for hides what it hides by default (the server's ``defaults``: DİBS RV's own FX swap columns). */
export async function loadHiddenColumns() {
  kept.clear();
  orders.clear();
  presets.clear();
  try {
    const res = await api.get('/api/columns');
    for (const name of Object.keys(res.tables || {})) kept.set(name, new Set(res.tables[name]));
    for (const name of Object.keys(res.defaults || {})) if (!kept.has(name)) kept.set(name, new Set(res.defaults[name]));
    for (const name of Object.keys(res.order || {})) orders.set(name, res.order[name].slice());
    for (const name of Object.keys(res.presets || {})) presets.set(name, (res.presets[name] || []).slice());
  } catch (e) { /* every column on screen; a change says what is wrong */ }
}

/** The ready views of a table (``[{name, hide}]``, the server's) - [] for a table without any. */
export function columnPresets(name) {
  return presets.get(name) || [];
}

/** The keys of a table's columns in this user's order (null: the sheet's own). */
export function columnOrder(name) {
  return orders.get(name) || null;
}

function post(name, body) {
  const next = (saving.get(name) || Promise.resolve()).then(() => api.post('/api/columns', body)).catch((err) => {
    if (err.status !== 401) toast('Sütun seçiminiz kaydedilemedi: ' + err.message, 'err', 6000);
  });
  saving.set(name, next);
}

function save(name, keys) {
  if (keys.size) kept.set(name, keys); else kept.delete(name);
  post(name, { table: name, hidden: [...keys] });
  for (const fn of [...listeners]) {
    try { if (fn(name) === false) listeners.delete(fn); } catch (e) { listeners.delete(fn); }
  }
}

function saveOrder(name, keys) {
  if (keys.length) orders.set(name, keys.slice()); else orders.delete(name);
  post(name, { table: name, order: keys.slice() });
}

/** A caption as a column's key: without the marks that come and go (a sort arrow, the tick of "all picked"). */
export function captionKey(text) {
  return String(text || '').replace(/[▲▼△▽☐☑]/g, ' ').replace(/\s+/g, ' ').trim();
}

const short = (text, n = 38) => (text.length > n ? text.slice(0, n - 1) + '…' : text);

/** Two columns under one caption are still two columns: the second one's key is "caption #2". */
export function uniqueKeys(cols) {
  const seen = new Map();
  for (const c of cols) {
    const n = (seen.get(c.key) || 0) + 1;
    seen.set(c.key, n);
    if (n > 1) c.key += ' #' + n;
  }
  return cols;
}

/** The tools (where "Kopyala" is) in the header of the panel an element is in; ``make``: added when the header has none. */
export function toolsOf(el, make = false) {
  const panel = el && el.closest ? el.closest('.panel') : null;
  const head = panel ? panel.querySelector(':scope > header') : null;
  if (!head) return null;
  let tools = head.querySelector('.tools');
  if (!tools && make) {
    tools = h('div', { class: 'tools' });
    head.appendChild(tools);
  }
  return tools;
}

/**
 * Where columns are hidden, the captions next to them say so (as Excel's double line): ``lines`` are the caption
 * rows, each a list of the cells on screen {el, j, cs} (``cs``: the columns the cell spans as built).
 */
export function markGaps(lines, hid, n) {
  let last = n - 1;
  while (last >= 0 && hid.has(last)) last -= 1;
  for (const line of lines) {
    for (const c of line) {
      c.el.toggleAttribute('data-gapl', c.j > 0 && hid.has(c.j - 1));
      c.el.toggleAttribute('data-gapr', last < n - 1 && c.j + c.cs - 1 >= last);
    }
  }
}

/**
 * The columns of one table and which of them this user hid.  The table (a Grid, or a table built by hand) gives its
 * columns as drawn with ``set(cols)`` and puts the choice on the screen in ``draw()``; the "Sütunlar" button among
 * the panel's tools and the label in its header (shown while columns are hidden) go with it.
 */
export class Columns {
  /** ``reorder``: the table puts its columns in the user's order again (a table that can be ordered gives one). */
  constructor(name, draw, reorder) {
    this.name = name;
    this.onDraw = draw || null;
    this.onReorder = reorder || null;
    this.orderable = !!reorder;
    this.cols = [];                // [{j, key, name, sub}] left to right (as on screen)
    this.hid = NO_COLUMNS;         // the indexes (j) of the hidden ones
    this.ui = null;
  }

  /** The columns as the table is drawn now; true when that changes what is hidden. */
  set(cols) {
    this.cols = cols;
    const keys = kept.get(this.name);
    const hid = new Set();
    if (keys) for (const c of cols) if (keys.has(c.key)) hid.add(c.j);
    if (hid.size && hid.size >= cols.length) hid.clear();          // a table never goes without a column on screen
    const changed = hid.size !== this.hid.size || [...hid].some((j) => !this.hid.has(j));
    this.hid = hid.size ? hid : NO_COLUMNS;
    return changed;
  }

  draw() { if (this.onDraw) this.onDraw(); }

  /** Hide (``show`` false) or show these columns (keys); refused when no column would be left on screen. */
  change(keys, show) {
    const all = new Set(kept.get(this.name) || []);
    for (const k of keys) { if (show) all.delete(k); else all.add(k); }
    if (this.cols.length && this.cols.every((c) => all.has(c.key))) {
      toast('En az bir sütun görünür kalmalı', 'err', 2600);
      return false;
    }
    save(this.name, all);
    this.update();
    return true;
  }

  showAll() {
    save(this.name, new Set());
    this.update();
  }

  /** A ready view of the table (the desk, 28.11.2026: DİBS Trading's "Trading / RV / Risk"): its hidden columns, as a
   *  choice of the user's own (kept with the account; changed column by column afterwards like any other). */
  applyPreset(p) {
    const keys = new Set((p.hide || []).filter((k) => this.cols.some((c) => c.key === k)));
    if (this.cols.length && this.cols.every((c) => keys.has(c.key))) return false;
    save(this.name, keys);
    this.update();
    return true;
  }

  /** The preset the hidden columns are now (null: a choice of the user's own). */
  presetNow() {
    const hid = new Set(this.cols.filter((c) => this.hid.has(c.j)).map((c) => c.key));
    return columnPresets(this.name).find((p) => {
      const want = new Set((p.hide || []).filter((k) => this.cols.some((c) => c.key === k)));
      return want.size === hid.size && [...want].every((k) => hid.has(k));
    }) || null;
  }

  /** The columns in this order (keys; [] - the sheet's own order again): kept, and the table drawn in it. */
  setOrder(keys) {
    saveOrder(this.name, keys);
    if (this.onReorder) this.onReorder();
  }

  /** Move a column one place to the left (-1) or right (+1) among those on screen. */
  moveCol(j, step) {
    const keys = this.cols.map((c) => c.key);
    const i = this.cols.findIndex((c) => c.j === j);
    if (i < 0) return;
    let k = i + step;
    while (k >= 0 && k < this.cols.length && this.hid.has(this.cols[k].j)) k += step;
    if (k < 0 || k >= this.cols.length) return;
    const [key] = keys.splice(i, 1);
    keys.splice(k, 0, key);
    this.setOrder(keys);
  }

  /** The columns as a list to put in order: drag a line, or its ↑ ↓; "Excel sırası" the sheet's own again. */
  openOrder() {
    const byKey = new Map(this.cols.map((c) => [c.key, c]));
    const keys = this.cols.map((c) => c.key);
    const m = modal({ title: 'Sütun sırası · yalnız sizin görünümünüz', width: 520 });
    m.box.classList.add('colorder-dlg');
    m.body.appendChild(h('p', { class: 'muted', style: { margin: '0 0 8px', fontSize: '12px' } },
      'Sütunları sürükleyip bırakın ya da ↑ ↓ ile taşıyın. Sıra hesabınızla saklanır: bu tablo sayfasında, launchpad\'de, yan panelde '
      + 've ayrı pencerede bu sırayla görünür.'));
    const list = h('div', { class: 'colorder', id: 'colorder-list' });
    let from = null;
    const move = (i, j) => {
      if (j < 0 || j >= keys.length || i === j) return;
      const [k] = keys.splice(i, 1);
      keys.splice(j, 0, k);
      paint();
    };
    const paint = () => {
      while (list.firstChild) list.removeChild(list.firstChild);
      keys.forEach((key, i) => {
        const c = byKey.get(key);
        const up = h('button', { type: 'button', title: 'Yukarı (sola)' }, '↑');
        const down = h('button', { type: 'button', title: 'Aşağı (sağa)' }, '↓');
        up.dataset.act = 'up';
        down.dataset.act = 'down';
        up.addEventListener('click', () => move(i, i - 1));
        down.addEventListener('click', () => move(i, i + 1));
        const row = h('div', { class: 'co', draggable: 'true' }, h('span', { class: 'k' }, c.sub || ''), h('span', { class: 't', title: c.name }, c.name),
          this.hid.has(c.j) ? h('span', { class: 'hid' }, 'gizli') : null, up, down);
        row.dataset.key = key;
        row.addEventListener('dragstart', (e) => { from = i; row.classList.add('dragging'); try { e.dataTransfer.setData('text/plain', key); } catch (x) { /* ignore */ } });
        row.addEventListener('dragend', () => { from = null; row.classList.remove('dragging'); });
        row.addEventListener('dragover', (e) => { if (from !== null) { e.preventDefault(); row.classList.add('over'); } });
        row.addEventListener('dragleave', () => row.classList.remove('over'));
        row.addEventListener('drop', (e) => { e.preventDefault(); row.classList.remove('over'); if (from !== null) move(from, i); });
        list.appendChild(row);
      });
    };
    paint();
    m.body.appendChild(list);
    const reset = h('button', { class: 'btn', type: 'button', id: 'colorder-reset', disabled: !orders.has(this.name),
      onclick: () => { m.close(); this.setOrder([]); toast('Sütunlar Excel\'deki sırasında', 'ok', 2200); } }, 'Excel sırası');
    m.foot.appendChild(reset);
    m.foot.appendChild(h('span', { style: { flex: '1' } }));
    m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Vazgeç'));
    m.foot.appendChild(h('button', { class: 'btn primary', type: 'button', id: 'colorder-save', onclick: () => { m.close(); this.setOrder(keys); } }, 'Kaydet'));
  }

  update() {
    this.set(this.cols);
    this.draw();
    this.paint();
  }

  /** The list of the columns, each with its tick (ticked: on screen), and "Tümünü göster". */
  openMenu(x, y) {
    const items = [];
    const ready = columnPresets(this.name);
    if (ready.length) {
      // the table's ready views first: one click hides what that way of reading it does not need
      const now = this.presetNow();
      items.push({ label: 'Görünüm', id: 'colpresets', title: 'Tablonun hazır görünümleri - tek tıkla; sonra sütun sütun değiştirebilirsiniz',
        choices: ready.map((p) => ({ label: p.name, on: now === p, value: p.name,
          title: p.name + ' görünümü: ' + (p.hide.length ? p.hide.length + ' sütun gizli' : 'bütün sütunlar'), action: () => this.applyPreset(p) })) });
      items.push({ sep: true });
    }
    items.push({ header: 'Gösterilen sütunlar · yalnız sizin görünümünüz' });
    for (const c of this.cols) {
      items.push({ check: true, on: !this.hid.has(c.j), label: short(c.name, 46), sub: c.sub, title: c.name,
        action: (on) => this.change([c.key], on) });
    }
    if (!this.cols.length) items.push({ header: 'Tabloda şu an sütun yok' });
    items.push({ sep: true });
    items.push({ label: 'Tümünü göster', disabled: !kept.has(this.name), action: () => this.showAll() });
    if (this.orderable && this.cols.length > 1) {
      items.push({ label: 'Sütun sırası…', action: () => this.openOrder() });
      items.push({ label: 'Excel sırasına dön', disabled: !orders.has(this.name), action: () => this.setOrder([]) });
    }
    menu(x, y, items);
  }

  /** What a right click on columns ``js`` offers: hide them, show every hidden one, the list. */
  menuItems(js, x, y) {
    const cols = this.cols.filter((c) => js.indexOf(c.j) >= 0 && !this.hid.has(c.j));
    const left = this.cols.length - this.hid.size;
    const one = this.orderable && cols.length === 1 ? cols[0] : null;
    return [
      cols.length ? { label: cols.length === 1 ? 'Sütunu gizle: ' + short(cols[0].name) : 'Bu ' + cols.length + ' sütunu gizle',
        disabled: cols.length >= left, action: () => this.change(cols.map((c) => c.key), false) } : null,
      this.hid.size ? { label: 'Gizlediğiniz sütunları göster (' + this.hid.size + ')', action: () => this.showAll() } : null,
      one ? { label: '← Sütunu sola taşı', action: () => this.moveCol(one.j, -1) } : null,
      one ? { label: 'Sütunu sağa taşı →', action: () => this.moveCol(one.j, 1) } : null,
      this.orderable && orders.has(this.name) ? { label: 'Excel sırasına dön', action: () => this.setOrder([]) } : null,
      { label: 'Sütunlar…', action: () => this.openMenu(x, y) },
    ];
  }

  /** The "Sütunlar" button among the panel's tools (``tools``), the label before them; a new table of the panel takes them over. */
  mount(tools) {
    if (!tools) return;
    let ui = tools.__columns;
    if (!ui) {
      const btn = h('button', { class: 'iconbtn colsbtn', type: 'button',
        title: 'Hangi sütunları göreceğinizi seçin – yalnız sizin görünümünüz, girdiğiniz her bilgisayarda aynı' }, 'Sütunlar');
      const chip = h('button', { class: 'colschip hidden', type: 'button' });
      const open = (el) => { const r = el.getBoundingClientRect(); ui.owner.openMenu(r.left, r.bottom + 4); };
      btn.addEventListener('click', () => open(btn));
      chip.addEventListener('click', () => open(chip));
      ui = tools.__columns = { btn, chip, tools, owner: null };
      // once the panel is put together: right after its first tool ("Kopyala" stays where the desk knows it)
      queueMicrotask(() => {
        if (btn.parentNode) return;
        const first = [...tools.children].find((x) => x.tagName === 'BUTTON');
        tools.insertBefore(btn, first ? first.nextSibling : null);
      });
    }
    ui.owner = this;
    this.ui = ui;
    this.paint();
  }

  paint() {
    const ui = this.ui;
    if (!ui || ui.owner !== this) return;
    if (!ui.chip.parentNode && ui.tools.parentNode) ui.tools.parentNode.insertBefore(ui.chip, ui.tools);
    const off = this.cols.filter((c) => this.hid.has(c.j));
    const view = off.length && columnPresets(this.name).length ? this.presetNow() : null;
    ui.chip.classList.toggle('hidden', !off.length);
    ui.chip.textContent = off.length ? (view ? 'Görünüm: ' + view.name + ' · ' + off.length + ' sütun gizli' : 'Gizlediğiniz ' + off.length + ' sütun') : '';
    ui.chip.title = off.length ? 'Bu tabloda gizlediğiniz sütunlar: ' + off.map((c) => c.name).join(', ') + '\nTıklayın: sütun listesi' : '';
    ui.btn.classList.toggle('on', off.length > 0);
  }
}

// ---------------------------------------------------------------------- tables built by hand
/** Where each cell of a <table> stands: rows of {el, j, cs}; header rows: those before the first one with a <td>. */
function layout(table) {
  const rows = [];
  const at = new Map();
  const taken = [];
  let n = 0;
  let head = -1;
  [...table.rows].forEach((tr, i) => {
    const line = [];
    let j = 0;
    for (const el of tr.cells) {
      while (taken[i] && taken[i].has(j)) j += 1;
      if (el.__cs === undefined) el.__cs = el.colSpan || 1;          // as built: a hidden column narrows it later
      const cs = el.__cs, rs = el.rowSpan || 1;
      for (let r = 1; r < rs; r++) {
        taken[i + r] = taken[i + r] || new Set();
        for (let k = 0; k < cs; k++) taken[i + r].add(j + k);
      }
      const c = { el, j, cs, i };
      line.push(c);
      at.set(el, c);
      if (head < 0 && el.tagName === 'TD') head = i;
      j += cs;
    }
    n = Math.max(n, j);
    rows.push(line);
  });
  return { rows, at, n, head: head < 0 ? rows.length : head };
}

function plainColumns(lay) {
  const out = [];
  for (let j = 0; j < lay.n; j++) {
    const texts = [];
    let key = '';
    for (let i = 0; i < lay.head; i++) {
      const c = lay.rows[i].find((x) => x.j <= j && j < x.j + x.cs);
      if (!c) continue;
      if (c.el.dataset.col) key = c.el.dataset.col;
      const t = captionKey(c.el.textContent);
      if (t && texts[texts.length - 1] !== t) texts.push(t);
    }
    const caption = texts.join(' · ');
    if (!caption && !key) {
      // a column of row names (<th> all the way down) stays
      const body = lay.rows.slice(lay.head).map((r) => r.find((x) => x.j === j)).filter(Boolean);
      if (body.length && body.every((x) => x.el.tagName === 'TH')) continue;
    }
    out.push({ j, key: key || caption || '#' + j, name: caption || 'Sütun ' + (j + 1), sub: '' });
  }
  return uniqueKeys(out);
}

/**
 * Column choices for a table a page builds by hand and builds again on every refresh: make one per table when the
 * page is made, and ``attach(table, tools)`` each time the table is built.  A right click on a caption hides its column.
 */
export class TableColumns extends Columns {
  constructor(name) {
    super(name, null);
    this.table = null;
    this.lay = null;
  }

  attach(table, tools) {
    this.table = table;
    this.lay = layout(table);
    this.set(plainColumns(this.lay));
    this.draw();
    if (tools) this.mount(tools); else this.paint();
    table.addEventListener('contextmenu', (e) => {
      const c = this.lay && this.table === table && this.lay.at.get(e.target.closest('th, td'));
      if (!c || c.i >= this.lay.head) return;            // the captions; the rest of the table keeps the browser's menu
      e.preventDefault();
      const js = [];
      for (let k = c.j; k < c.j + c.cs; k++) js.push(k);
      menu(e.clientX, e.clientY, this.menuItems(js, e.clientX, e.clientY));
    });
  }

  draw() {
    if (!this.lay) return;
    const hid = this.hid;
    for (const line of this.lay.rows) {
      for (const c of line) {
        let v = 0;
        for (let k = c.j; k < c.j + c.cs; k++) if (!hid.has(k)) v += 1;
        if (c.el.hidden !== !v) c.el.hidden = !v;
        if (v && c.el.colSpan !== v) c.el.colSpan = v;
      }
    }
    markGaps(this.lay.rows.slice(0, this.lay.head).map((line) => line.filter((c) => !c.el.hidden)), hid, this.lay.n);
  }
}
