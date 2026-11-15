// The columns a user hides in a table.  Everybody looks at the tables their own way: what is hidden is kept with the
// account on the server, so any computer shows the same.  A table is named by its page ("v/dibs/B5": a table of a
// sheet, "eod/curve": one of the dashboard's own); a column by its letter in the sheet, or by its caption.
import { api } from './api.js';
import { h, menu, toast } from './ui.js';

export const NO_COLUMNS = new Set();

const kept = new Map();           // table -> Set of the keys of the columns this user hid
const saving = new Map();         // table -> its last save: the saves of one table go one after the other

/** The columns this user hid (on signing in, before the first table is drawn). */
export async function loadHiddenColumns() {
  kept.clear();
  try {
    const res = await api.get('/api/columns');
    for (const name of Object.keys(res.tables || {})) kept.set(name, new Set(res.tables[name]));
  } catch (e) { /* every column on screen; a change says what is wrong */ }
}

function save(name, keys) {
  if (keys.size) kept.set(name, keys); else kept.delete(name);
  const body = { table: name, hidden: [...keys] };
  const next = (saving.get(name) || Promise.resolve()).then(() => api.post('/api/columns', body)).catch((err) => {
    if (err.status !== 401) toast('Sütun seçiminiz kaydedilemedi: ' + err.message, 'err', 6000);
  });
  saving.set(name, next);
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
  constructor(name, draw) {
    this.name = name;
    this.onDraw = draw || null;
    this.cols = [];                // [{j, key, name, sub}] left to right
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

  update() {
    this.set(this.cols);
    this.draw();
    this.paint();
  }

  /** The list of the columns, each with its tick (ticked: on screen), and "Tümünü göster". */
  openMenu(x, y) {
    const items = [{ header: 'Gösterilen sütunlar · yalnız sizin görünümünüz' }];
    for (const c of this.cols) {
      items.push({ check: true, on: !this.hid.has(c.j), label: short(c.name, 46), sub: c.sub, title: c.name,
        action: (on) => this.change([c.key], on) });
    }
    if (!this.cols.length) items.push({ header: 'Tabloda şu an sütun yok' });
    items.push({ sep: true });
    items.push({ label: 'Tümünü göster', disabled: !kept.has(this.name), action: () => this.showAll() });
    menu(x, y, items);
  }

  /** What a right click on columns ``js`` offers: hide them, show every hidden one, the list. */
  menuItems(js, x, y) {
    const cols = this.cols.filter((c) => js.indexOf(c.j) >= 0 && !this.hid.has(c.j));
    const left = this.cols.length - this.hid.size;
    return [
      cols.length ? { label: cols.length === 1 ? 'Sütunu gizle: ' + short(cols[0].name) : 'Bu ' + cols.length + ' sütunu gizle',
        disabled: cols.length >= left, action: () => this.change(cols.map((c) => c.key), false) } : null,
      this.hid.size ? { label: 'Gizlediğiniz sütunları göster (' + this.hid.size + ')', action: () => this.showAll() } : null,
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
    ui.chip.classList.toggle('hidden', !off.length);
    ui.chip.textContent = off.length ? 'Gizlediğiniz ' + off.length + ' sütun' : '';
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
