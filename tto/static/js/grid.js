// Spreadsheet-like table: range selection, Excel-compatible copy / paste, in-cell editing of input cells,
// in-place refresh with change flashes, the columns each user hides, the decimals each user sees (decimals.js).  An
// input cell takes a formula as Excel does: "=" and a click on a cell - of this table, another one on the page, another
// tab's, the side drawer's, a launchpad's - puts its reference in where a reference may go (Ctrl+click anywhere); the
// server evaluates it, live (inputformula.py).
import { h, clear, menu, closeMenu, inFormControl, toast } from './ui.js';
import { raw } from './format.js';
import { Columns, captionKey, columnOrder, markGaps, uniqueKeys } from './columns.js';
import { decimalItems, decimalsTip } from './decimals.js';
import { workbookRef, canPoint, isFormula } from './pointing.js';

const hooks = {
  // async (book, items, adhoc, lenient, copy) -> result   (lenient: cells that are not inputs are skipped; copy: the id of
  // the temporary copy the table is - its own inputs, not the user's)
  setInputs: null,
  paste: null,         // async (book, anchorRef, text, adhoc) -> result
  reset: null,         // async (book, refs, shared, copy) -> result
  onSelect: null,      // (info | null)
  trade: null,         // (price: {view, panel, row, col, text, label}) - "İşlem gir" on a price (see priceOf)
};

const sel = { grid: null, r0: 0, c0: 0, r1: 0, c1: 0, cells: [], cur: null, dragging: false };
// {grid, i, j, td, input, point: the reference just put in ({start, end}), pts: its cells marked, ptAt: where they are
//  ({g, box}: marked again when that table is drawn anew), drag, switching: a tab of the page being opened while the
//  formula is typed}
let editing = null;

/** A column of a sheet, by its letters (a column the dashboard adds to a table has a name: "Broker bid", "Kart"). */
const isLetter = (c) => typeof c === 'string' && /^[A-Z]{1,3}$/.test(c);

/**
 * The rows and columns of a table as the sheet has them - its own order, all of them: the table as it came, before this
 * user's order of the columns (and, for a launchpad's part of a table, the whole table's: ``ar`` / ``ac``).  A gap in
 * them is the sheet's own: rows / columns hidden in Excel, or empty and left out.
 */
function ownLayout(grid) {
  const src = grid.source || grid.data || {};
  return { r: src.ar || src.r || [], c: src.ac || src.c || [] };
}

export function configureGrid(opts) {
  const own = Object.assign({}, opts);
  for (const k of ['setInputs', 'paste', 'reset']) {          // (a write through them is counted until answered)
    const fn = own[k];
    if (typeof fn === 'function') own[k] = (...args) => trackWrite(fn(...args));
  }
  Object.assign(hooks, own);
}

// ---------------------------------------------------------------------- the writes in flight
// Every input write sent and not answered yet - a cell typed, a block pasted, a cell reset, a value typed elsewhere
// (the manual spot): a scenario load waits for them (scenarios.js), so that it lands after the last value typed - the
// server applies the writes it has in their order (tests/test_scenario_order.py); this makes sure it has them all.
const inflight = new Set();

/** ``p`` (a write's promise) counted until it settles; returned as it is. */
export function trackWrite(p) {
  if (p && typeof p.then === 'function') {
    inflight.add(p);
    const done = () => { inflight.delete(p); };
    p.then(done, done);
  }
  return p;
}

/** Every write sent so far answered - an open cell edit committed first (it is one more): settles once they all did
 *  (one that failed too: its error is its own toast). */
export function pendingWrites() {
  if (editing) commitEdit();
  return Promise.allSettled([...inflight]).then(() => undefined);
}

export function currentSelection() {
  if (!sel.grid) return null;
  return { grid: sel.grid, top: Math.min(sel.r0, sel.r1), left: Math.min(sel.c0, sel.c1),
    bottom: Math.max(sel.r0, sel.r1), right: Math.max(sel.c0, sel.c1) };
}

export function clearSelection() {
  for (const td of sel.cells) td.classList.remove('sel');
  if (sel.cur) sel.cur.classList.remove('cur');
  sel.cells = [];
  sel.cur = null;
  sel.grid = null;
  if (hooks.onSelect) hooks.onSelect(null);
}

function heatStyle(hex) {
  const r = parseInt(hex.slice(0, 2), 16), g = parseInt(hex.slice(2, 4), 16), b = parseInt(hex.slice(4, 6), 16);
  const chroma = (Math.max(r, g, b) - Math.min(r, g, b)) / 255;
  const a = Math.min(0.62, chroma * 1.15);
  return a < 0.03 ? '' : 'rgba(' + r + ',' + g + ',' + b + ',' + a.toFixed(3) + ')';
}

function cellClass(cell) {
  let cls = cell.k || '';
  if (cell.b) cls += ' b';
  if (cell.it) cls += ' it';
  if (cell.c) cls += ' c-' + cell.c;
  if (cell.f && cell.f !== 'in') cls += ' f-' + cell.f;
  if (cell.al) cls += ' al-' + cell.al;
  if (cell.ov) cls += ' ov';
  if (cell.ovw) cls += ' ovw';                          // (a long one: it wraps in the table's width - prepare)
  if (cell.n) cls += ' nt';
  if (typeof cell.bar === 'number') cls += ' bar bar-' + (cell.bc || 'info');
  if (cell.ro) cls += ' ro';                            // an input a temporary copy keeps read-only (the reason: its tip)
  if (cell.i) {
    cls += ' in';
    if (cell.i === 's') cls += ' sh';
    if (cell.m) cls += ' mod';
    if (cell.fx && cell.m === 1) cls += ' hand';        // this user's value stands where the workbook has a formula
    // filled by the workbook (market, another cell) until typed over; one that came out empty or as an error
    // (the market did not deliver) stays a plain input: that is where a value has to be typed
    else if (cell.fx && !cell.m && cell.t && cell.k !== 'e') cls += ' auto';
    if (cell.ff) cls += cell.fe ? ' ff ffe' : ' ff';  // typed as a formula (=C60+7): a small ƒ in the corner
    // a two-way table (tto/twoway.py): the value typed in its row (✎) - the row's other values are worked out from it
    if (cell.an) cls += ' anchor';
  }
  return cls;
}

function signature(cell) {
  return (cell.t || '') + '\u0001' + cellClass(cell) + '\u0001' + (cell.heat || '') + '\u0001' + (cell.rs || 1) + 'x' + (cell.cs || 1)
    + '\u0001' + (typeof cell.bar === 'number' ? cell.bar : '') + '\u0001' + (cell.ff || '') + '\u0001' + (cell.fe || '')
    + '\u0001' + (cell.tip || '') + '\u0001' + (cell.ro || '') + '\u0001' + (cell.an || '') + '\u0001' + (cell.ao || '')
    + '\u0001' + (cell.dp === undefined ? '' : cell.dp) + (cell.dpc ? 'c' : '');
}

/** What a cell says when the mouse rests on it: an input's formula, the workbook's comment, a long text in full - in a
 *  temporary copy, why an input stays read-only there. */
function tipOf(cell) {
  let tip = '';
  if (cell.n) tip = cell.n + (cell.tip ? '\n' + cell.tip : '');          // the cell's comment in Excel
  else if (cell.tip) tip = cell.tip;
  else if (cell.k === 's' && cell.t && cell.t.length > 28 && !cell.ff) tip = cell.t;
  if (cell.ff) tip = 'Formül: ' + cell.ff + (cell.fe ? '\n' + cell.fe : '') + (tip ? '\n' + tip : '');
  // a two-way table's row: which value was typed, and that the others come from it
  if (cell.an) tip = '✎ Yazdığınız değer: satırın ' + cell.an + ' değerleri bundan hesaplanır - piyasa değişse de bu kalır. '
    + 'Silince (Delete) satır varsayılana döner.' + (tip ? '\n' + tip : '');
  else if (cell.ao) tip = 'Hesaplanan: bu satırda yazılan değer ' + cell.ao + ', bu hücre ondan hesaplanır. Buraya yazarsanız '
    + 'yazılan değer bu olur.' + (tip ? '\n' + tip : '');
  if (cell.ro) tip = 'Kopyada salt okunur: ' + cell.ro + (tip ? '\n' + tip : '');
  const dp = decimalsTip(cell);                         // (the decimals this user set for the cell)
  if (dp) tip = tip ? tip + '\n' + dp : dp;
  return tip;
}

// A date typed as a shortcut ("1A", "ay sonu", "IMM", "+5"): the date it stood for is what was stored; what was typed
// is said in the cell's tooltip from then on, while the cell holds that date (the server says both: res.shortcuts).
// book|ref -> {typed, date, text, fresh: the new value has not come back to the table yet}
const typedDates = new Map();

function typedNote(grid, i, j, cell) {
  if (!typedDates.size || !cell) return '';
  const ref = grid.ref(i, j);
  const key = ref && (grid.book || '') + '|' + ref;
  const t = key && typedDates.get(key);
  if (!t) return '';
  if (cell.v === t.date || String(cell.t || '').trim() === t.text) t.fresh = false;
  else if (!t.fresh) { typedDates.delete(key); return ''; }           // typed over since: the note goes
  return 'Kısayol: ' + t.typed + ' → ' + t.text;
}

/** A cell's tooltip: its own (tipOf) and, for a date typed as a shortcut, what was typed. */
function titleOf(grid, i, j, cell) {
  const a = tipOf(cell), b = typedNote(grid, i, j, cell);
  return a && b ? a + '\n' + b : (a || b);
}

/** The dates of a write that were typed as shortcuts (``shortcuts``: {ref: {typed, date, text}}), into the tooltips. */
function noteTyped(grid, shortcuts) {
  if (!shortcuts || !grid) return;
  for (const ref of Object.keys(shortcuts)) typedDates.set((grid.book || '') + '|' + ref, Object.assign({ fresh: true }, shortcuts[ref]));
  const d = grid.data;
  if (!d || !d.r || !d.c) return;
  for (let i = 0; i < grid.tds.length; i++) {
    for (let j = 0; j < grid.tds[i].length; j++) {
      const td = grid.tds[i][j];
      const ref = td && grid.ref(i, j);
      if (ref && shortcuts[ref]) td.title = titleOf(grid, i, j, grid.cell(i, j));
    }
  }
}

/** A text this long that runs over the cells to its right is a note: it wraps in the table's width (``ovw``). */
const WRAP_AT = 70;

/**
 * Excel lets a long text run over the empty cells to its right; do the same with a column span so notes and
 * captions do not blow up the width of their own column.  Marks the data once (the shape check sees it).  A long one
 * (``WRAP_AT`` characters or more: a note inside the sheet's range, up to 1 400 characters) wraps within the width the
 * table's other cells give it instead of making every column under it wider (the desk, 27.11.2026: an 11-column table
 * was 7 531 px wide from its note) - unless ``wrap`` is false (a notes panel: its own rule).
 */
function prepare(data, wrap = true) {
  if (!data || data.__prepared || !data.rows) return data;
  data.__prepared = true;
  for (const row of data.rows) {
    for (let j = 0; j < row.length; j++) {
      const c = row[j];
      if (c.sk || c.k !== 's' || c.cs || c.rs || c.i || c.act || c.chk || !c.t || c.t.length < 14) continue;
      if (c.al === 'r' || c.al === 'c') continue;
      let n = 0;
      while (j + n + 1 < row.length) {
        const x = row[j + n + 1];
        if (x.sk || x.t || x.i || x.f || x.heat || x.cs || x.rs || x.act || x.chk) break;
        n += 1;
      }
      if (n > 0) {
        c.cs = n + 1;
        c.ov = 1;
        if (wrap && c.t.length >= WRAP_AT) c.ovw = 1;
        for (let k = 1; k <= n; k++) { row[j + k].sk = 1; row[j + k].ovk = 1; }      // (ovk: run over, no merged cell)
        j += n;
      }
    }
  }
  return data;
}

/** A cell's text into its <td>: a long note that wraps (``ovw``) in a box of its own that gives the table no width. */
function fillText(td, cell) {
  const t = cell.t || '';
  if (!cell.ovw) { td.textContent = t; return; }
  let box = td.firstElementChild;
  if (!box || !box.classList.contains('ovt')) {
    td.textContent = '';
    box = td.appendChild(document.createElement('div'));
    box.className = 'ovt';
  }
  box.textContent = t;
}

function isHeaderRow(row) {
  let n = 0, strong = 0;
  for (const cell of row) {
    if (cell.sk || !cell.t) continue;
    if (cell.k !== 's' || cell.i) return false;
    if (cell.c || (cell.f && cell.f !== 'hd' && cell.f !== 'sub')) return false;      // status colours are data
    n += 1;
    if (cell.b || cell.f === 'hd') strong += 1;
  }
  return n >= 2 && strong * 2 >= n;
}

/** The caption rows of a table (at most two, from the top; a lone title row may precede them). */
function headerRows(d, opts) {
  const out = [];
  let run = opts.header;
  for (let i = 0; run && i < d.rows.length; i++) {
    const row = d.rows[i];
    if (out.length < 2 && d.rows.length > 1 && isHeaderRow(row)) out.push(i);
    else if (i > 0 || !opts.header) run = false;
    else if (row.filter((c) => !c.sk && c.t).length > 1) run = false;
  }
  return out;
}

/** The cell that covers row i, column j (a merged caption, one from the row above); a text running over from the left does not. */
function captionOver(rows, i, j) {
  for (let r = i; r >= 0; r--) {
    for (let k = j; k >= 0; k--) {
      const c = rows[r][k];
      if (!c || c.sk) continue;
      if (k + (c.ov ? 1 : (c.cs || 1)) > j && r + (c.rs || 1) > i) return c;
    }
  }
  return null;
}

/**
 * The columns of a table for the user's column choice: [{j, key, name, sub}].  A table of a sheet keys a column by its
 * letter, one of the dashboard's own by its caption (``ck`` of a caption cell, when the caption itself changes).
 */
function gridColumns(d, heads) {
  const n = d.rows.length ? d.rows[0].length : 0;
  const sheet = !!(d.c && d.c.length === n);
  const out = [];
  for (let j = 0; j < n; j++) {
    const texts = [];
    let ck = '';
    for (const i of heads) {
      const c = captionOver(d.rows, i, j);
      if (!c) continue;
      if (c.ck) ck = c.ck;
      const t = captionKey(c.t);
      if (t && texts[texts.length - 1] !== t) texts.push(t);
    }
    const caption = texts.join(' · ');
    let sample = '';
    for (let i = 0; !caption && !sample && i < d.rows.length && i < 12; i++) {
      const c = d.rows[i][j];
      if (c && !c.sk && c.t) sample = String(c.t).trim();
    }
    if (sample.length > 24) sample = sample.slice(0, 23) + '…';
    const letter = sheet && /^[A-Z]{1,3}$/.test(d.c[j]) ? d.c[j] : '';        // (a column the dashboard adds has a name)
    out.push({ j, key: sheet ? d.c[j] : (ck || caption || '#' + j),
      name: caption || (letter ? 'Sütun ' + letter : 'Sütun ' + (j + 1)), sub: caption ? letter : sample });
  }
  return uniqueKeys(out);
}

/**
 * The columns of a table in the order this user put them (``order``: column keys, ``keys``: the table's own, left to
 * right; a column not in the order follows the ordered ones, in the table's order).  A new table: every cell keeps its
 * reference (``c`` moves with it), a merged cell whose columns are no longer side by side is split (its text stays in
 * its own first column), the frozen columns are those still at the left; text that ran over empty cells (prepare) is
 * laid out again on the new order.
 */
function ordered(data, keys, order) {
  const n = data.rows.length ? data.rows[0].length : 0;
  if (!n || keys.length !== n) return data;
  const rank = new Map(order.map((k, i) => [k, i]));
  const at = (j) => (rank.has(keys[j]) ? rank.get(keys[j]) : order.length + j);
  const perm = [...Array(n).keys()].sort((a, b) => at(a) - at(b));
  if (perm.every((j, p) => j === p)) return data;
  const pos = new Array(n);
  perm.forEach((j, p) => { pos[j] = p; });
  const rows = data.rows.map((row) => row.map(() => ({ t: '', k: '' })));
  data.rows.forEach((row, i) => {
    row.forEach((cell, j) => {
      if (!cell || (cell.sk && !cell.ovk)) return;                 // (covered by a merged cell: placed with it)
      const c = Object.assign({}, cell);
      if (c.ovk) { delete c.sk; delete c.ovk; rows[i][pos[j]] = c; return; }
      if (c.ov) { delete c.ov; delete c.cs; delete c.ovw; }
      const cs = c.cs || 1;
      const rs = c.rs || 1;
      const ps = [];
      for (let k = j; k < j + cs && k < n; k++) ps.push(pos[k]);
      const lo = Math.min(...ps);
      const together = Math.max(...ps) - lo + 1 === ps.length;
      if (!together) delete c.cs;
      const own = together ? lo : pos[j];
      rows[i][own] = c;
      for (let r = 0; r < rs; r++) {
        if (!rows[i + r]) continue;
        for (const p of (together ? ps : [pos[j]])) if (r || p !== own) rows[i + r][p] = { sk: 1 };
      }
    });
  });
  const out = Object.assign({}, data, { rows });
  delete out.__prepared;
  if (data.c && data.c.length === n) out.c = perm.map((j) => data.c[j]);
  if (data.fz) {
    let k = 0;
    while (k < n && perm[k] < data.fz) k += 1;
    if (k > 0 && k < n) out.fz = k; else delete out.fz;
  }
  return out;
}

export class Grid {
  /**
   * opts: book, data {sheet, rows, r, c}, editable (bool), adhoc (bool: any cell may be overridden),
   *       axis (bool: show A/B/C and 1/2/3 headers), header (bool: detect header rows),
   *       name (the table's stable name: each user hides columns of it, kept with the account),
   *       order (bool: the user may put its columns in an order of their own - a table of a workbook page, whose
   *              cells are known by their letter; the dashboard's own tables find a column by its place),
   *       tools (the panel's tools: the "Sütunlar" button goes there),
   *       copy (the id of a temporary copy of a table: what is typed goes to that copy's own inputs; never "Elle değer",
   *             never pointed at by a formula - a formula reads the table itself)
   *       rowItems ((i, j) -> menu items: what the right-click menu offers for the row clicked - a row's quote - first,
   *                 after a price's "İşlem gir")
   *       decimals (bool: the right-click menu sets this user's own decimals of the numbers selected - a table of a
   *                 workbook page, whose answers the server puts them on: decimals.js)
   *       freeze (n: its first n columns stay in view while it scrolls sideways - a table the page builds itself, whose
   *               data says none (``fz``: the workbook's frozen panes, a view's "freeze"); plainData takes it too)
   *       wrap (bool, default true: a long note that runs over a row wraps in the table's width - prepare; false: a
   *             notes panel, whose cells wrap by their own rule)
   *       onBuild (() => …: the table was drawn anew - its rows are new elements: a page's rows hidden by "+ Satır" /
   *                "Tümü" are hidden again)
   */
  constructor(opts) {
    this.opts = Object.assign({ editable: true, adhoc: false, axis: false, header: true, wrap: true }, opts);
    this.book = this.opts.book || null;
    this.data = null;
    this.tds = [];
    this.heads = [];
    this.el = h('table', { class: 'grid' + (this.opts.axis ? ' addr' : '') });
    this.el.__grid = this;
    this.el.addEventListener('mousedown', (e) => this._mouseDown(e));
    this.el.addEventListener('mouseover', (e) => this._mouseOver(e));
    this.el.addEventListener('dblclick', (e) => this._dblClick(e));
    this.el.addEventListener('contextmenu', (e) => this._context(e));
    this.columns = this.opts.name && !this.opts.axis
      ? new Columns(this.opts.name, () => this._showColumns(), this.opts.order ? () => this._reorder() : null) : null;
    if (this.columns) this.columns.mount(this.opts.tools);
    this.update(this.opts.data, false);
    if (window.ResizeObserver) {
      // column widths change with the content and when a collapsed panel opens: re-pin the frozen columns
      this._ro = new ResizeObserver(() => this._freeze());
      this._ro.observe(this.el);
    }
  }

  /** The workbook reference of a cell ("Forward!D2") - null for one that is no cell of a sheet: a caption row of the
   *  dashboard's own (row 0), a column it adds (named, not lettered: "Broker bid"), a table it makes itself (no sheet:
   *  the DİBS tape). */
  ref(i, j) {
    const d = this.data;
    if (!d || !d.sheet || !d.r || !d.c || !d.r[i] || !isLetter(d.c[j])) return null;
    return d.sheet + '!' + d.c[j] + d.r[i];
  }

  cell(i, j) {
    const row = this.data && this.data.rows[i];
    return row ? row[j] : undefined;
  }

  sameShape(data) {
    const a = this.data;
    if (!a || !data || a.rows.length !== data.rows.length) return false;
    if ((a.rows[0] || []).length !== (data.rows[0] || []).length) return false;
    if (a.sheet !== data.sheet) return false;
    const ar = a.r || [], br = data.r || [], ac = a.c || [], bc = data.c || [];
    if (ar.length !== br.length || ac.length !== bc.length) return false;
    for (let i = 0; i < ar.length; i++) if (ar[i] !== br[i]) return false;
    for (let j = 0; j < ac.length; j++) if (ac[j] !== bc[j]) return false;
    for (let i = 0; i < a.rows.length; i++) {
      for (let j = 0; j < a.rows[i].length; j++) {
        const x = a.rows[i][j], y = data.rows[i][j];
        if (!!x.sk !== !!y.sk || (x.rs || 1) !== (y.rs || 1) || (x.cs || 1) !== (y.cs || 1)) return false;
      }
    }
    return true;
  }

  /** New data drawn in place.  False: not drawn - its shape changed while a cell of it is being typed into (the
   *  edit would be lost or go to another cell); the next refresh brings it. */
  update(data, flash = true) {
    if (!data || !data.rows) return true;
    this.source = data;
    data = this._ordered(data);
    prepare(data, this.opts.wrap);
    if (this.sameShape(data)) {
      this._patch(data, flash);
      return true;
    }
    if (editing && editing.grid === this) return false;
    const hadSel = sel.grid === this;
    if (hadSel) clearSelection();
    this.data = data;
    this._build();
    return true;
  }

  /** Rebuild from scratch (client-built tables whose rows carry their own actions). */
  replace(data) {
    if (sel.grid === this) clearSelection();
    if (editing && editing.grid === this) editing = null;
    this.source = data;
    data = this._ordered(data);
    prepare(data, this.opts.wrap);
    this.data = data;
    this._build();
  }

  /** The table as it came, in this user's column order (a new one), or as it is. */
  _ordered(data) {
    const order = this.columns && this.columns.orderable ? columnOrder(this.columns.name) : null;
    if (!order || !order.length || !data.rows || !data.rows.length) return data;
    return ordered(data, gridColumns(data, headerRows(data, this.opts)).map((c) => c.key), order);
  }

  /** The user put the columns in another order: drawn again in it. */
  _reorder() {
    if (!this.source) return;
    if (editing && editing.grid === this) commitEdit();
    if (sel.grid === this) clearSelection();
    const data = this._ordered(this.source);
    prepare(data, this.opts.wrap);
    this.data = data;
    this._build();
  }

  _build() {
    const d = this.data;
    clear(this.el);
    this.tds = [];
    const body = h('tbody');
    if (this.opts.axis) {
      const tr = h('tr', { class: 'axisrow' }, h('td', { class: 'axis rowh' }, ''));
      for (const c of d.c) tr.appendChild(h('td', { class: 'axis' }, c));
      body.appendChild(tr);
    }
    this.heads = headerRows(d, this.opts);
    for (let i = 0; i < d.rows.length; i++) {
      const row = d.rows[i];
      const tr = h('tr');
      const hd = this.heads.indexOf(i);
      if (hd >= 0) tr.className = 'hd' + (hd === 1 ? ' hd2' : '');
      if (this.opts.axis) tr.appendChild(h('td', { class: 'axis rowh' }, String(d.r[i])));
      const line = [];
      for (let j = 0; j < row.length; j++) {
        const cell = row[j];
        if (cell.sk) { line.push(null); continue; }
        const td = document.createElement('td');
        td.className = cellClass(cell) + (cell.cls ? ' ' + cell.cls : '');
        if (cell.act) {
          // one button, or several side by side (an array)
          for (const a of [].concat(cell.act)) {
            const b = h('button', { class: 'iconbtn', type: 'button', title: a.title || '' }, a.label);
            if (a.id) b.dataset.act = a.id;
            b.addEventListener('click', (e) => { e.stopPropagation(); a.fn(); });
            td.appendChild(b);
          }
        } else if (cell.chk) {
          // a tick box of a client-built table (its row is picked for something - deleting it, say)
          const b = h('input', { type: 'checkbox', class: 'pick', title: cell.chk.title || '' });
          b.checked = !!cell.chk.on;
          b.addEventListener('click', (e) => e.stopPropagation());
          b.addEventListener('change', () => cell.chk.fn(b.checked));
          td.appendChild(b);
        } else {
          fillText(td, cell);
        }
        if (cell.rs) td.rowSpan = cell.rs;
        if (cell.cs) td.colSpan = cell.cs;
        if (cell.heat) td.style.backgroundColor = heatStyle(cell.heat);
        if (typeof cell.bar === 'number') td.style.setProperty('--bar', cell.bar + '%');
        const tip = titleOf(this, i, j, cell);
        if (tip) td.title = tip;
        td.__i = i;
        td.__j = j;
        tr.appendChild(td);
        line.push(td);
      }
      this.tds.push(line);
      body.appendChild(tr);
    }
    this.el.appendChild(body);
    if (this.columns) {
      this.columns.set(gridColumns(d, this.heads));
      this._showColumns();
    } else {
      this._freeze();
    }
    // the cells of the reference just put into a formula being typed are in this table: marked again on its new cells
    if (editing && editing.ptAt && editing.ptAt.g === this) {
      editing.pts = [];
      paintPoint(editing);
    }
    if (this.opts.onBuild) this.opts.onBuild(this);
  }

  /** True when this user hid column j of the table. */
  colHidden(j) {
    return !!this.columns && this.columns.hid.has(j);
  }

  /**
   * Put the user's column choice on the table: a hidden column's cells go, a caption over it narrows, and the
   * captions next to it get a mark.  Nothing is rebuilt: a selection, a highlight, the rows a page folds stay.
   */
  _showColumns() {
    const hid = this.columns.hid;
    const rows = this.data.rows;
    for (const f of this.el.querySelectorAll('td.colfill')) f.remove();
    for (let i = 0; i < this.tds.length; i++) {
      const line = this.tds[i];
      for (let j = 0; j < line.length; j++) {
        const td = line[j];
        if (!td) continue;
        const cell = rows[i][j];
        const cs = cell.cs || 1;
        let v = 0;
        for (let k = j; k < j + cs; k++) if (!hid.has(k)) v += 1;
        if (cell.ov && hid.has(j)) {
          // a long text runs over the empty cells to its right from its own column only: it goes with that column
          td.hidden = true;
          if (v) td.after(h('td', { class: 'colfill', colspan: String(v) }));
          continue;
        }
        if (td.hidden !== !v) td.hidden = !v;
        if (v && td.colSpan !== v) td.colSpan = v;
      }
    }
    const n = rows.length ? rows[0].length : 0;
    markGaps(this.heads.map((i) => this.tds[i].map((td, j) => (td && !td.hidden ? { el: td, j, cs: rows[i][j].cs || 1 } : null))
      .filter(Boolean)), hid, n);
    this.columns.paint();
    this._freeze();
  }

  /**
   * Keep the columns Excel freezes (panes) in view while the table scrolls sideways.  Offsets come from the
   * rendered widths, so this runs again whenever the table changes size.
   */
  _freeze() {
    const width = this.data && this.data.rows && this.data.rows.length ? this.data.rows[0].length : 0;
    // the data's own (the workbook's panes, a view's "freeze") - else the page's for a table it builds (opts.freeze)
    const n = (this.data && this.data.fz) || (this.opts.freeze > 0 && this.opts.freeze < width ? this.opts.freeze : 0);
    if (!n || this.opts.axis || !this.tds.length) return;
    const rows = this.data.rows;
    const span = (i, j) => rows[i][j].cs || 1;            // as built (a hidden column narrows the cell, not this)
    const widths = [];
    for (let j = 0; j < n; j++) {
      let w = 0;
      for (let i = 0; i < this.tds.length && !this.colHidden(j); i++) {
        const td = this.tds[i][j];
        if (td && !td.hidden && span(i, j) === 1) { w = td.getBoundingClientRect().width; break; }
      }
      widths.push(w);
    }
    if (!widths.some((w) => w > 0)) return;                 // not laid out yet (a collapsed panel)
    let last = n - 1;
    while (last > 0 && this.colHidden(last)) last -= 1;     // the last frozen column on screen
    let left = 0;
    for (let j = 0; j < n; j++) {
      for (let i = 0; i < this.tds.length; i++) {
        const td = this.tds[i][j];
        if (!td || j + span(i, j) > n) continue;            // a caption that runs past the frozen part scrolls
        td.classList.add('fz');
        td.classList.toggle('fzl', j + span(i, j) - 1 >= last);
        td.style.left = left + 'px';
      }
      left += widths[j];
    }
  }

  _patch(data, flash) {
    const old = this.data;
    this.data = data;
    const moved = [];
    for (let i = 0; i < data.rows.length; i++) {
      const row = data.rows[i], prev = old.rows[i], line = this.tds[i];
      for (let j = 0; j < row.length; j++) {
        const td = line[j];
        if (!td) continue;
        const cell = row[j], before = prev[j];
        if (editing && editing.td === td) continue;
        if (signature(cell) === signature(before)) continue;
        const keepSel = td.classList.contains('sel'), keepCur = td.classList.contains('cur'), keepPt = td.classList.contains('pt');
        if (cell.act || cell.chk) continue;
        td.className = cellClass(cell) + (cell.cls ? ' ' + cell.cls : '') + (keepSel ? ' sel' : '') + (keepCur ? ' cur' : '')
          + (keepPt ? ' pt' : '');
        fillText(td, cell);
        // (a formula typed, changed or gone - or a tooltip the workbook gives, which curve a rate is of: the tooltip with
        // it; a date typed as a shortcut: what was typed; a two-way table's row typed into or back to its default)
        if (cell.ff || before.ff || (cell.tip || '') !== (before.tip || '') || typedDates.size
            || (cell.an || '') !== (before.an || '') || (cell.ao || '') !== (before.ao || '')
            || cell.dp !== before.dp || cell.dpc !== before.dpc) td.title = titleOf(this, i, j, cell);
        td.style.backgroundColor = cell.heat ? heatStyle(cell.heat) : '';
        if (typeof cell.bar === 'number') td.style.setProperty('--bar', cell.bar + '%');
        else td.style.removeProperty('--bar');
        td.classList.remove('up', 'down');
        if (flash && cell.k === 'n' && before.k === 'n' && typeof cell.v === 'number' && typeof before.v === 'number'
            && cell.v !== before.v) {
          moved.push([td, cell.v > before.v ? 'up' : 'down']);
        }
      }
    }
    // highlight what moved - unless nearly everything did (a whole curve repricing is not news cell by cell)
    if (moved.length && moved.length <= 120) {
      void this.el.offsetWidth;                      // restart the animations
      for (const [td, cls] of moved) td.classList.add(cls);
    }
    // a caption that changed may name another column now (a caption is the key of a column of the dashboard's own)
    if (this.columns && this.columns.set(gridColumns(data, this.heads))) this._showColumns();
    else this._freeze();
    if (this.columns) this.columns.paint();
    if (sel.grid === this) notifySelection();
  }

  // ------------------------------------------------------------------ selection
  _tdOf(e) {
    let t = e.target;
    while (t && t !== this.el && t.tagName !== 'TD') t = t.parentNode;
    if (!t || t === this.el || t.__i === undefined) return null;
    return t;
  }

  _mouseDown(e) {
    if (e.button !== 0) return;
    if (e.target.closest && e.target.closest('button')) return;
    const td = this._tdOf(e);
    if (!td) return;
    if (editing) {
      if (editing.td === td) return;
      commitEdit();
    }
    if (e.shiftKey && sel.grid === this) {
      setSelection(this, sel.r0, sel.c0, td.__i, td.__j);
    } else {
      setSelection(this, td.__i, td.__j, td.__i, td.__j);
    }
    sel.dragging = true;
    const active = document.activeElement;
    if (active && inFormControl(active)) active.blur();
    e.preventDefault();
  }

  _mouseOver(e) {
    if (!sel.dragging || sel.grid !== this) return;
    const td = this._tdOf(e);
    if (td) setSelection(this, sel.r0, sel.c0, td.__i, td.__j);
  }

  _dblClick(e) {
    const td = this._tdOf(e);
    if (td && !startEdit(this, td.__i, td.__j, null)) readOnlySaid(this, td.__i, td.__j);
  }

  _context(e) {
    const td = this._tdOf(e);
    if (!td) return;
    e.preventDefault();
    const s = currentSelection();
    if (!s || s.grid !== this || td.__i < s.top || td.__i > s.bottom || td.__j < s.left || td.__j > s.right) {
      setSelection(this, td.__i, td.__j, td.__i, td.__j);
    }
    const cur = currentSelection();
    const inputs = inputRefs(this, cur);
    const copy = this.opts.copy;
    const mine = inputs.filter((x) => x.cell.i === 'u' && (!copy || x.cell.m)).map((x) => x.ref);
    const shared = copy ? [] : inputs.filter((x) => x.cell.i === 's' && x.cell.m).map((x) => x.ref);
    // one cell of a sheet: watch it, or an alarm on it (a temporary copy's: no - the watch reads the table itself)
    const one = cur && cur.top === cur.bottom && cur.left === cur.right ? { ref: this.ref(cur.top, cur.left), cell: this.cell(cur.top, cur.left) } : null;
    const watchable = !copy && one && one.ref && this.book && one.cell && typeof one.cell.v === 'number' && (hooks.watch || hooks.alarm);
    const label = watchable ? cellLabel(this, cur.top, cur.left) : '';
    // one price of a table whose page names its trades: "İşlem gir" opens Günlük İşlemler with it filled (a temporary
    // copy's: no - its prices come from its own inputs, the server reads the row of the table itself)
    const price = !copy && one && hooks.trade ? priceOf(this, cur.top, cur.left) : null;
    // the columns under the click (a merged caption: all of its own) can be hidden from this user's view
    let cols = [];
    if (this.columns) {
      const lone = cur.top === cur.bottom && cur.left === cur.right ? this.cell(cur.top, cur.left) : null;
      const right = lone && !lone.ov ? cur.left + (lone.cs || 1) - 1 : cur.right;
      const js = [];
      for (let j = cur.left; j <= right; j++) js.push(j);
      cols = [{ sep: true }].concat(this.columns.menuItems(js, e.clientX, e.clientY));
    }
    // what the page offers for the row clicked (its quote: "Bu satırın kotasyonu"), after "İşlem gir"
    const own = this.opts.rowItems ? (this.opts.rowItems(td.__i, td.__j) || []) : [];
    // the decimals of the numbers selected, this user's own (a table of a workbook page: the server puts them on)
    const decs = this.opts.decimals && this.book ? decimalItems(this, cur) : [];
    menu(e.clientX, e.clientY, [
      price && !price.why ? { label: 'İşlem gir', action: () => hooks.trade(price) } : null,
      price && price.why ? { label: 'İşlem gir · ' + price.why, disabled: true } : null,
      price ? { sep: true } : null,
      ...own,
      own.length ? { sep: true } : null,
      watchable && hooks.watch ? { label: 'İzlemeye ekle', action: () => hooks.watch(this.book, one.ref, label) } : null,
      watchable && hooks.alarm ? { label: 'Alarm kur…', action: () => hooks.alarm(this.book, one.ref, label, one.cell.t) } : null,
      watchable ? { sep: true } : null,
      { label: 'Kopyala  (Ctrl+C)', action: () => copyViaCommand(false) },
      { label: 'Tam hassasiyetle kopyala  (Ctrl+Shift+C)', action: () => copyViaCommand(true) },
      { label: 'Tüm tabloyu seç  (Ctrl+A)', action: () => selectAll(this) },
      inputs.length ? { sep: true } : null,
      inputs.length ? { header: 'Yapıştırmak için Ctrl+V' } : null,
      mine.length ? { label: copy ? 'Kopyadaki değeri sil → tablonun değerine dön' : 'Kendi girdimi sil → varsayılana dön',
        action: () => resetRefs(this, mine, false) } : null,
      shared.length ? { label: 'Ortak girdiyi dosyadaki değere döndür', action: () => resetRefs(this, shared, true) } : null,
      ...decs,
      ...cols,
    ]);
  }
}

/** A name for a cell, from its table: the text of its row (left of it) and the caption of its column (above). */
function cellLabel(grid, i, j) {
  const txt = (c) => (c && c.k === 's' && typeof c.t === 'string' ? c.t.trim() : '');
  let row = '';                                          // the row's name: its first text from the left
  for (let k = 0; k < j && !row; k++) row = txt(grid.cell(i, k));
  let col = '';
  for (let k = i - 1; k >= 0 && !col; k--) {
    const c = grid.cell(k, j);
    if (c && (c.f === 'hd' || c.b) && txt(c)) col = txt(c);
  }
  const name = [row, col].filter(Boolean).join(' · ').slice(0, 60);
  return name || grid.ref(i, j) || '';
}

/**
 * A price of a table whose page names its trades (the view's "trade" hint, as the server sends it with the table:
 * ``data.trade`` = {view, panel, first, last, cells}): ``cells`` keys a price by its column - for the sheet's rows
 * ``first`` .. ``last`` - or by one cell ("F173"), and gives "" for a trade or why there is none (a VİOP contract).
 * {view, panel, row, col, text, label, why} - the row's number in the sheet and the column's letters (never its place
 * on screen: a user's column order or a launchpad's part keep them), the price as it is on screen; null: no price
 * (a caption, a date, an empty cell, a table without the hint).  The server reads the rest from the row's own cells.
 */
function priceOf(grid, i, j) {
  const d = grid.data;
  const t = d && d.trade;
  if (!t || !t.cells || !d.r || !d.c) return null;
  const row = d.r[i], col = d.c[j], cell = grid.cell(i, j);
  if (typeof row !== 'number' || !isLetter(col) || !cell || cell.sk || typeof cell.v !== 'number') return null;
  let why = t.cells[col + row];
  if (why === undefined && !(t.first && row < t.first) && !(t.last && row > t.last)) why = t.cells[col];
  if (typeof why !== 'string') return null;
  return { view: t.view, panel: t.panel, row, col, text: cell.t || '', label: cellLabel(grid, i, j), why };
}

function setSelection(grid, r0, c0, r1, c1) {
  if (sel.grid !== grid) {
    for (const td of sel.cells) td.classList.remove('sel');
    if (sel.cur) sel.cur.classList.remove('cur');
    sel.cells = [];
    sel.cur = null;
  }
  sel.grid = grid;
  sel.r0 = r0; sel.c0 = c0; sel.r1 = r1; sel.c1 = c1;
  const top = Math.min(r0, r1), bottom = Math.max(r0, r1), left = Math.min(c0, c1), right = Math.max(c0, c1);
  for (const td of sel.cells) td.classList.remove('sel');
  if (sel.cur) sel.cur.classList.remove('cur');
  const cells = [];
  const single = top === bottom && left === right;
  for (let i = top; i <= bottom; i++) {
    const line = grid.tds[i];
    if (!line) continue;
    for (let j = left; j <= right; j++) {
      const td = line[j];
      if (td) { if (!single) td.classList.add('sel'); cells.push(td); }
    }
  }
  sel.cells = cells;
  const cur = grid.tds[r1] && grid.tds[r1][c1];
  if (cur) { cur.classList.add('cur'); sel.cur = cur; }
  notifySelection();
}

function selectAll(grid) {
  const d = grid.data;
  if (!d.rows.length) return;
  setSelection(grid, 0, 0, d.rows.length - 1, d.rows[0].length - 1);
}

function notifySelection() {
  if (!hooks.onSelect) return;
  const s = currentSelection();
  if (!s) { hooks.onSelect(null); return; }
  const g = s.grid;
  let count = 0, sum = 0, n = 0, min = Infinity, max = -Infinity, cols = 0;
  for (let j = s.left; j <= s.right; j++) if (!g.colHidden(j)) cols += 1;
  for (let i = s.top; i <= s.bottom; i++) {
    for (let j = s.left; j <= s.right; j++) {
      const c = g.cell(i, j);
      if (!c || c.sk || g.colHidden(j)) continue;
      if (c.t) count += 1;
      if (c.k === 'n' && typeof c.v === 'number') {
        sum += c.v; n += 1;
        if (c.v < min) min = c.v;
        if (c.v > max) max = c.v;
      }
    }
  }
  const a = g.ref(s.top, s.left), b = g.ref(s.bottom, s.right);
  const single = s.top === s.bottom && s.left === s.right;
  hooks.onSelect({
    grid: g, book: g.book, ref: a, single, copy: g.opts.copy || null,
    label: !a ? '' : (single || !b ? a : a + ':' + b.split('!')[1]),     // (!b: the block runs into a column the dashboard adds)
    cell: g.cell(sel.r1, sel.c1), focusRef: g.ref(sel.r1, sel.c1),
    count, n, sum, avg: n ? sum / n : null, min: n ? min : null, max: n ? max : null,
    rows: s.bottom - s.top + 1, cols,
  });
}

/** The input cells of a selection that are on screen (a column the user hid is never written to). */
function inputRefs(grid, s) {
  const out = [];
  if (!s) return out;
  for (let i = s.top; i <= s.bottom; i++) {
    for (let j = s.left; j <= s.right; j++) {
      if (grid.colHidden(j)) continue;
      const c = grid.cell(i, j);
      const ref = grid.ref(i, j);
      if (c && !c.sk && ref && (c.i || grid.opts.adhoc)) out.push({ ref, cell: c, i, j });
    }
  }
  return out;
}

// ---------------------------------------------------------------------- clipboard
/** The selection as Excel takes it: what is on screen (the columns this user hid stay out). */
export function selectionText(full) {
  const s = currentSelection();
  if (!s) return null;
  const g = s.grid;
  const lines = [];
  for (let i = s.top; i <= s.bottom; i++) {
    const parts = [];
    let carry = null;                // a merged cell that starts in a hidden column shows in the first one on screen
    for (let j = s.left; j <= s.right; j++) {
      let c = g.cell(i, j);
      if (g.colHidden(j)) {
        if (c && !c.sk && !c.ov && (c.cs || 1) > 1) carry = { c, end: j + c.cs - 1 };
        continue;
      }
      if ((!c || c.sk) && carry && j <= carry.end) c = carry.c;
      carry = null;
      if (!c || c.sk) { parts.push(''); continue; }
      let t = c.t || '';
      if (full && c.k === 'n' && typeof c.v === 'number') t = raw(c.v);
      parts.push(String(t).replace(/[\t\r\n]+/g, ' '));
    }
    lines.push(parts.join('\t'));
  }
  return lines.join('\r\n');
}

let copyFull = false;
function copyViaCommand(full) {
  copyFull = full;
  let ok = false;
  try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
  copyFull = false;
  if (!ok) {
    const text = selectionText(full);
    if (navigator.clipboard && text !== null) {
      lastCopied = normalise(text);
      navigator.clipboard.writeText(text).then(() => toast('Kopyalandı', 'ok', 1500), () => toast('Kopyalanamadı', 'err'));
    }
  }
}

// What was last copied out of a grid.  Text that comes back unchanged was copied from the screen, so it is
// pasted onto the screen cell by cell; anything else comes from Excel and keeps Excel's own layout.
let lastCopied = null;
const normalise = (text) => text.replace(/\r\n/g, '\n').replace(/\r/g, '\n').replace(/\n$/, '');

function colIndex(name) {
  let n = 0;
  for (const ch of name) n = n * 26 + (ch.charCodeAt(0) - 64);
  return n;
}

function colName(n) {
  let s = '';
  while (n > 0) { const m = (n - 1) % 26; s = String.fromCharCode(65 + m) + s; n = (n - 1 - m) / 26; }
  return s;
}

export function copyGrid(grid, full = false) {
  selectAll(grid);
  copyViaCommand(full);
}

document.addEventListener('copy', (e) => {
  if (inFormControl(e.target) && !editing) return;
  if (editing) return;
  const text = selectionText(copyFull || shiftHeld);
  if (text === null) return;
  const native = window.getSelection();
  if (native && !native.isCollapsed && !copyFull) {
    // the user selected page text with the mouse outside a grid: leave the browser alone
    const node = native.anchorNode;
    const inGrid = node && (node.nodeType === 1 ? node : node.parentNode).closest && (node.nodeType === 1 ? node : node.parentNode).closest('table.grid');
    if (!inGrid) return;
  }
  e.clipboardData.setData('text/plain', text);
  e.preventDefault();
  lastCopied = normalise(text);
  const s = currentSelection();
  let cols = 0;
  for (let j = s.left; j <= s.right; j++) if (!s.grid.colHidden(j)) cols += 1;
  const n = (s.bottom - s.top + 1) * cols;
  toast(n === 1 ? 'Hücre kopyalandı' : (s.bottom - s.top + 1) + ' × ' + cols + ' hücre kopyalandı – Excel\'e yapıştırabilirsiniz'
    + (cols < s.right - s.left + 1 ? ' (gizlediğiniz sütunlar hariç)' : ''), 'ok', 1800);
});

document.addEventListener('paste', (e) => {
  if (inFormControl(e.target)) return;
  const s = currentSelection();
  if (!s) return;
  const g = s.grid;
  if (!g.opts.editable || !g.book) return;
  const text = (e.clipboardData || window.clipboardData).getData('text/plain');
  if (!text) return;
  e.preventDefault();
  pasteText(g, s, text);
});

/**
 * How a block pasted at (top, the columns ``vis``) is laid over the table, down its rows and across its columns each:
 * 'screen' - onto the rows / columns on screen, one after the other - or 'sheet' - Excel's own layout, counted in rows /
 * columns of the sheet from the top-left.  Excel's only where the screen is the sheet's own layout and the block runs
 * over a gap of it (hidden in Excel, or empty and left out: a block copied in Excel carries those); the screen's where it
 * is laid out otherwise - a user's order of the columns, a launchpad's part of the table: the block lands where it looks
 * like it lands - and for a block copied from the screen.
 */
function pasteLayout(grid, top, vis, rows, cols, fromScreen) {
  const d = grid.data;
  const own = ownLayout(grid);
  const same = (a, b) => a.length === b.length && a.every((x, k) => x === b[k]);
  let down = 'screen', across = 'screen';
  if (!fromScreen && same(d.r, own.r)) {
    for (let i = 1; i < rows && down === 'screen'; i++) {
      if (top + i >= d.r.length || d.r[top + i] !== d.r[top + i - 1] + 1) down = 'sheet';
    }
  }
  if (!fromScreen && same(d.c, own.c)) {
    for (let j = 1; j < cols && across === 'screen'; j++) {
      if (j >= vis.length || colIndex(d.c[vis[j]]) !== colIndex(d.c[vis[j - 1]]) + 1) across = 'sheet';
    }
  }
  return { down, across };
}

export async function pasteText(grid, s, text) {
  // the screen's columns from the left of the selection on: the ones this user hid are not there
  const vis = [];
  const width0 = grid.data && grid.data.rows.length ? grid.data.rows[0].length : 0;
  for (let j = s.left; j < width0; j++) if (!grid.colHidden(j)) vis.push(j);
  if (!vis.length || !grid.ref(s.top, vis[0])) return;
  const clean = normalise(text);
  const matrix = clean.split('\n').map((line) => line.split('\t'));
  const single = matrix.length === 1 && matrix[0].length === 1;
  const width = Math.max(...matrix.map((row) => row.length));
  try {
    let items = [];
    let skipped = 0;
    let unseen = 0;
    let lenient = false;
    const lay = pasteLayout(grid, s.top, vis, matrix.length, width, clean === lastCopied);
    if (single && (s.bottom > s.top || s.right > s.left)) {
      // one value onto a selection: fill every input cell of the selection (as Excel does)
      items = inputRefs(grid, s).map((x) => ({ ref: x.ref, value: clean }));
    } else if (lay.down === 'sheet' || lay.across === 'sheet') {
      // a block from Excel that runs over rows / columns the table does not show (hidden in Excel, or empty
      // and left out): that way it keeps Excel's layout, counted in sheet cells from the top-left of the selection
      // (the other way, if the screen's, onto the rows / columns on screen).  Nothing outside the table's own range is
      // written; the server skips whatever is not an input; a column this user hid is not written to either.
      const d = grid.data;
      const own = ownLayout(grid);
      const row0 = d.r[s.top], col0 = colIndex(d.c[vis[0]]);
      const rowMax = Math.max(...own.r), colMax = Math.max(...own.c.filter(isLetter).map(colIndex));
      const hiddenCols = new Set(d.c.filter((c, j) => grid.colHidden(j)));
      for (let i = 0; i < matrix.length; i++) {
        for (let j = 0; j < matrix[i].length; j++) {
          const row = lay.down === 'sheet' ? row0 + i : d.r[s.top + i];
          const col = lay.across === 'sheet' ? (col0 + j <= colMax ? colName(col0 + j) : null) : d.c[vis[j]];
          if (!row || row > rowMax || !isLetter(col)) { skipped += 1; continue; }
          if (hiddenCols.has(col)) { unseen += 1; continue; }
          items.push({ ref: d.sheet + '!' + col + row, value: matrix[i][j] });
        }
      }
      lenient = true;
    } else {
      // a block: cell by cell onto what is on screen, starting at the top-left of the selection.
      // Rows / columns the table does not show are never written to, and neither are non-input cells.
      for (let i = 0; i < matrix.length; i++) {
        for (let j = 0; j < matrix[i].length; j++) {
          const cell = vis[j] === undefined ? undefined : grid.cell(s.top + i, vis[j]);
          const ref = vis[j] === undefined ? null : grid.ref(s.top + i, vis[j]);
          if (cell && !cell.sk && ref && (cell.i || grid.opts.adhoc)) items.push({ ref, value: matrix[i][j] });
          else skipped += 1;
        }
      }
    }
    if (!items.length) { toast(unseen ? 'Yapıştırılan alan gizlediğiniz sütunlarda kalıyor' : 'Yapıştırılan alanda girdi hücresi yok', 'err'); return; }
    const res = await hooks.setInputs(grid.book, items, grid.opts.adhoc, lenient, grid.opts.copy || null);
    if (res) { res.skipped = skipped + (res.skipped || 0); res.unseen = unseen; }
    if (res && res.shortcuts) noteTyped(grid, res.shortcuts);           // (dates pasted as shortcuts, cell by cell)
    if (res && lenient && !res.applied && !(res.errors || []).length) { toast('Yapıştırılan alanda girdi hücresi yok', 'err'); return; }
    reportApply(res, 'yapıştırıldı');
  } catch (err) {
    toast(err.message || String(err), 'err', 6000);
  }
}

function reportApply(res, verb) {
  if (!res) return;
  const errs = res.errors || [];
  let msg = (res.applied || 0) + ' hücre ' + verb;
  if (res.skipped) msg += ' · ' + res.skipped + ' hücre girdi olmadığı için atlandı';
  if (res.unseen) msg += ' · ' + res.unseen + ' hücre gizlediğiniz sütunda olduğu için yazılmadı';
  // a meeting list changed with the write: what moved, what was set aside (the server says it)
  if (res.note) msg += ' · ' + res.note;
  if (errs.length) msg += ' · ' + errs.length + ' hata: ' + errs.slice(0, 3).join('; ');
  toast(msg, errs.length ? 'err' : 'ok', errs.length ? 9000 : (res.note ? 9000 : 2600));
}

async function resetRefs(grid, refs, shared) {
  try {
    const res = await hooks.reset(grid.book, refs, shared, grid.opts.copy || null);
    toast((res.reset || 0) + (grid.opts.copy ? ' hücre tablonun değerine döndü' : ' hücre varsayılana döndü'), 'ok', 2200);
  } catch (err) {
    toast(err.message || String(err), 'err', 6000);
  }
}

// ---------------------------------------------------------------------- editing
function editText(cell) {
  if (!cell) return '';
  if (cell.ff) return cell.ff;                          // an input typed as a formula: its text (F2, a double click)
  if (cell.k === 'n' && typeof cell.v === 'number') {
    if (cell.ik === 'pct') return raw(cell.v * 100) + '%';
    return raw(cell.v);
  }
  return cell.t || '';
}

/** An input a temporary copy keeps read-only, typed into: why it is (said once per try). */
function readOnlySaid(grid, i, j) {
  const cell = grid.cell(i, j);
  if (cell && cell.ro) toast('Kopyada salt okunur: ' + cell.ro, 'err', 6000);
}

export function startEdit(grid, i, j, typed) {
  const cell = grid.cell(i, j);
  const td = grid.tds[i] && grid.tds[i][j];
  if (!cell || !td || td.hidden || !grid.opts.editable || !grid.book) return false;
  if (!cell.i && !grid.opts.adhoc) return false;
  if (editing) commitEdit();
  if (cell.o && cell.o.length && typed === null) {
    const r = td.getBoundingClientRect();
    menu(r.left, r.bottom + 2, cell.o.map((o) => ({ label: o, action: () => applyValue(grid, i, j, o) })));
    return true;
  }
  const input = h('input', { type: 'text', spellcheck: 'false', autocomplete: 'off' });
  input.value = typed !== null ? typed : editText(cell);
  td.classList.add('editing');
  td.textContent = '';
  td.appendChild(input);
  editing = { grid, i, j, td, input, done: false, point: null, pts: [], drag: null, switching: false };
  input.classList.toggle('fxe', isFormula(input.value));
  input.focus();
  // a formula opens with the caret at its end, as Excel's F2 (a reference clicked goes in there); a value is selected
  if (typed === null && !isFormula(input.value)) input.select();
  else input.setSelectionRange(input.value.length, input.value.length);
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); commitEdit('key'); moveBy(e.shiftKey ? -1 : 1, 0, false); }
    else if (e.key === 'Tab') { e.preventDefault(); commitEdit('key'); moveBy(0, e.shiftKey ? -1 : 1, false); }
    else if (e.key === 'Escape') { e.preventDefault(); cancelEdit(); }
    e.stopPropagation();
  });
  input.addEventListener('input', () => {
    if (!editing || editing.input !== input) return;
    editing.point = null;                               // (typed on: the next click puts a reference in, not in place)
    markPoint(editing);
    input.classList.toggle('fxe', isFormula(input.value));
  });
  input.addEventListener('blur', () => {
    // a tab of the page opened while a formula is typed - its tables can be pointed at - or the editor taken out of
    // the page with its table (re-homed by reviveEditor): the typing goes on
    if (editing && editing.input === input && !editing.switching && input.isConnected) commitEdit();
  });
  return true;
}

function finishEdit() {
  const ed = editing;
  editing = null;
  if (!ed) return null;
  ed.td.classList.remove('editing');
  markPoint(ed);
  const cell = ed.grid.cell(ed.i, ed.j);
  if (ed.input.parentNode) ed.input.parentNode.removeChild(ed.input);
  dockBar(null);
  ed.td.textContent = cell ? (cell.t || '') : '';
  return ed;
}

function cancelEdit() {
  finishEdit();
}

/** ``how``: 'key' (Enter / Tab: the cell is still the user's), or the editor was left - a click elsewhere, the focus gone. */
function commitEdit(how = 'away') {
  if (!editing) return;
  const value = editing.input.value;
  const ed = finishEdit();
  const cell = ed.grid.cell(ed.i, ed.j);
  if (value === editText(cell)) return;                 // nothing typed
  if (!isFormula(value)) ed.td.textContent = value;     // optimistic until the refresh arrives (a formula: its value then)
  applyValue(ed.grid, ed.i, ed.j, value, how);
}

// the user's clicks and keys, counted: a refused formula is typed into again only if nothing was done since it was sent
let touches = 0;
document.addEventListener('mousedown', () => { touches += 1; }, true);
document.addEventListener('keydown', () => { touches += 1; }, true);

const selNow = () => (sel.grid ? [sel.grid, sel.r0, sel.c0, sel.r1, sel.c1] : null);
const sameSel = (a, b) => !!a && !!b && a.every((x, k) => x === b[k]);

async function applyValue(grid, i, j, value, how = 'away') {
  const ref = grid.ref(i, j);
  if (!ref) return;
  const back = () => {
    const td = grid.tds[i] && grid.tds[i][j];
    const cell = grid.cell(i, j);
    if (td && cell && !(editing && editing.td === td)) td.textContent = cell.t || '';
  };
  // where the commit itself leaves the selection (Enter moves it down): taken once its handler is done
  const seen = touches;
  let after = null;
  Promise.resolve().then(() => { after = selNow(); });
  try {
    const res = await hooks.setInputs(grid.book, [{ ref, value }], grid.opts.adhoc, false, grid.opts.copy || null);
    if (res && res.shortcuts) noteTyped(grid, res.shortcuts);           // ("1A" typed: the date it is, what was typed in the tip)
    if (res && res.errors && res.errors.length) {
      const formula = isFormula(value);
      toast((formula ? value + ' kaydedilmedi – ' : '') + res.errors.join('; '), 'err', formula ? 9000 : 6000);
      back();
      // a formula refused (a Bloomberg function, a cycle, one that cannot be read) and committed by Enter / Tab: typed
      // into again, as it was - unless the user did anything since (a click, a key, another place to type in): never
      // pulled back to it then
      const act = document.activeElement;
      const free = !act || act === document.body || grid.el.contains(act);
      if (formula && how === 'key' && !editing && touches === seen && sameSel(selNow(), after) && free
          && grid.el.isConnected && grid.tds[i] && grid.tds[i][j]) {
        setSelection(grid, i, j, i, j);
        startEdit(grid, i, j, value);
      }
    } else if (res && res.note) {
      toast(res.note, 'ok', 9000);           // (a meeting date typed: what moved with it, what was set aside)
    }
  } catch (err) {
    toast(err.message || String(err), 'err', 6000);
    back();
  }
}

// ---------------------------------------------------------------------- pointing while a formula is typed
/**
 * The block of ``g`` (rows i1..i2, columns j1..j2 on screen) as a rectangle of its sheet: {r1, r2, c1, c2} (row numbers,
 * column numbers) - null when a cell of it is no cell of a sheet.  ``gap``: the rectangle takes in a row or a column of
 * the table that the block leaves out (this user's order put it elsewhere, a launchpad's part of the table left it out):
 * its reference would name cells neither shown in the block nor marked.  A row / column the sheet itself leaves out of
 * the table (hidden in Excel, or empty) is in the rectangle, as in Excel.
 */
function sheetBox(g, i1, j1, i2, j2) {
  const d = g.data;
  if (!d || !d.sheet || !d.r || !d.c) return null;
  const rows = new Set(), cols = new Set();
  for (let i = Math.min(i1, i2); i <= Math.max(i1, i2); i++) {
    if (!d.r[i]) return null;
    rows.add(d.r[i]);
  }
  for (let j = Math.min(j1, j2); j <= Math.max(j1, j2); j++) {
    if (!isLetter(d.c[j])) return null;
    cols.add(colIndex(d.c[j]));
  }
  const box = { r1: Math.min(...rows), r2: Math.max(...rows), c1: Math.min(...cols), c2: Math.max(...cols) };
  const own = ownLayout(g);
  box.gap = own.r.some((r) => r >= box.r1 && r <= box.r2 && !rows.has(r))
    || own.c.some((c) => isLetter(c) && colIndex(c) >= box.c1 && colIndex(c) <= box.c2 && !cols.has(colIndex(c)));
  return box;
}

/** The reference of a rectangle of ``g``'s sheet as the formula being typed names it: the cell's own sheet bare (C60,
 *  P94:P99), another sheet with its name, another workbook in brackets ([sofr]SOFR_FOMC!B9). */
function boxRef(ed, g, box) {
  let addr = colName(box.c1) + box.r1;
  if (box.r2 !== box.r1 || box.c2 !== box.c1) addr += ':' + colName(box.c2) + box.r2;
  const own = ed.grid.data && ed.grid.data.sheet;
  if (g.book === ed.grid.book && g.data.sheet === own) return addr;
  return workbookRef(g.book, g.data.sheet + '!' + addr);
}

/** The cells of the reference just put in, marked on screen (no ``box``: none) - kept by their rectangle in the sheet:
 *  their table drawn anew (a row more, another order of its columns) marks them again (``_build``). */
function markPoint(ed, g = null, box = null) {
  for (const td of ed.pts || []) td.classList.remove('pt');
  ed.pts = [];
  ed.ptAt = g && box ? { g, box } : null;
  paintPoint(ed);
}

function paintPoint(ed) {
  const at = ed.ptAt;
  const d = at && at.g.data;
  if (!d || !d.r || !d.c) return;
  const { g, box } = at;
  for (let i = 0; i < g.tds.length; i++) {
    if (!(d.r[i] >= box.r1 && d.r[i] <= box.r2)) continue;
    g.tds[i].forEach((td, j) => {
      const k = isLetter(d.c[j]) ? colIndex(d.c[j]) : 0;
      if (td && k >= box.c1 && k <= box.c2) { td.classList.add('pt'); ed.pts.push(td); }
    });
  }
}

/** A cell (a block, dragged over) goes into the formula at the caret - in place of the reference put just before.
 *  -> true; null: it is no cell of a sheet; false: a block whose rectangle in the sheet is not what it shows (sheetBox:
 *  nothing goes in). */
function pointAt(ed, g, i1, j1, i2 = i1, j2 = j1) {
  const box = sheetBox(g, i1, j1, i2, j2);
  if (!box) return null;
  if (box.gap) return false;
  const text = boxRef(ed, g, box);
  const inp = ed.input;
  const start = ed.point ? ed.point.start : inp.selectionStart;
  const end = ed.point ? ed.point.end : inp.selectionEnd;
  inp.value = inp.value.slice(0, start) + text + inp.value.slice(end);
  ed.point = { start, end: start + text.length };
  inp.focus({ preventScroll: true });
  inp.setSelectionRange(start + text.length, start + text.length);
  markPoint(ed, g, box);
  return true;
}

/** The formula's editor out of its cell while that cell is out of view (another tab of the page is open): it goes on in
 *  a bar of its own at the top of the window, back into the cell when the cell is on screen again. */
function dockBar(ed) {
  let bar = document.getElementById('grid-fx');
  if (!ed) { if (bar) bar.classList.add('hidden'); return; }
  if (!bar) {
    bar = h('div', { id: 'grid-fx', class: 'grid-fx hidden' }, h('span', { class: 'lbl' }), h('span', { class: 'eq' }, 'ƒ'));
    document.body.appendChild(bar);
  }
  bar.querySelector('.lbl').textContent = ed.grid.ref(ed.i, ed.j) || '';
  bar.title = 'Formül yazılıyor: bir tablonun hücresine tıklayın (Ctrl+tık formülün her yerinde) · Enter kaydeder, Esc vazgeçer';
  bar.appendChild(ed.input);
  bar.classList.remove('hidden');
}

/** The page laid its tables out again (a tab opened, the search) while a cell's value is typed: the editor where it can
 *  be typed into - in its cell when that is on screen, in the bar of its own when not.  view.js calls it after every
 *  layout; a tab clicked calls it too, whatever the tab's own handler did with the click. */
export function reviveEditor() {
  const ed = editing;
  if (!ed) return;
  const was = ed.switching;
  // (moved while focused, an input may lose its focus - a blur that must not end the typing: "switching" meanwhile)
  ed.switching = true;
  if (!ed.td.isConnected) dockBar(ed);
  else if (ed.input.parentNode !== ed.td) { ed.td.appendChild(ed.input); dockBar(null); }
  if (was || document.activeElement !== ed.input) ed.input.focus({ preventScroll: true });
  ed.switching = false;
}

function keepEditor() {
  if (editing && editing.switching) reviveEditor();
}

// while an input's formula is typed: a click on a cell of any table of a workbook on screen puts its reference in where a
// reference may go (after =, an operator, a bracket or a separator; again in place of the one just put) or, with Ctrl,
// anywhere; a click elsewhere ends the typing, as before.  (A calc sheet's own pointing acts only while one of its cells
// is typed into: the two never meet.)
document.addEventListener('mousedown', (e) => {
  const ed = editing;
  if (!ed || e.button !== 0 || !isFormula(ed.input.value)) return;
  const t = e.target;
  if (!t || !t.closest || t === ed.input) return;
  if (t.closest('.viewtabs button')) {                  // another tab: its tables can be pointed at as well
    e.preventDefault();
    ed.switching = true;
    return;
  }
  ed.switching = false;
  if (t.closest('#grid-fx')) { e.preventDefault(); ed.input.focus(); return; }
  const td = t.closest('table.grid td');
  if (!td || td === ed.td) return;
  const table = td.closest('table.grid');
  const g = table && table.__grid;
  if (!g || td.__i === undefined) return;
  if (!(e.ctrlKey || e.metaKey || ed.point || canPoint(ed.input))) return;
  e.preventDefault();
  e.stopPropagation();
  if (g.opts.copy) {
    // a formula reads the workbook as the user has it - the table itself: a temporary copy's own values are no cell of it
    toast('Geçici kopyanın hücresine başvurulamaz: formül tablonun kendisini okur – tablodaki hücreye tıklayın', 'err', 5000);
    return;
  }
  if (!pointAt(ed, g, td.__i, td.__j)) {
    toast('Bu tablonun hücreleri bir çalışma kitabı sayfasında değil: başvurusu eklenemez', 'err');
    return;
  }
  ed.drag = { g, i: td.__i, j: td.__j, said: false };
}, true);

document.addEventListener('mouseover', (e) => {
  const ed = editing;
  if (!ed || !ed.drag || !e.target.closest) return;
  const td = e.target.closest('table.grid td');
  if (!td || td.__i === undefined || td.closest('table.grid') !== ed.drag.g.el) return;
  // (dragged over a block: A1:B5) - one the sheet does not have as it is shown leaves the reference as it was
  if (pointAt(ed, ed.drag.g, ed.drag.i, ed.drag.j, td.__i, td.__j) === false && !ed.drag.said) {
    ed.drag.said = true;
    toast('Bu blok çalışma kitabında tek bir aralık değil (sütun sıranız ya da tablonun seçili kısmı arada başka satır / '
      + 'sütun bırakıyor): hücreleri tek tek gösterin', 'err', 6000);
  }
}, true);

document.addEventListener('mouseup', () => {
  if (!editing) return;
  editing.drag = null;
  // (pressed on a tab and let go: once the click - if any - is handled, whatever its handlers did with it)
  if (editing.switching) setTimeout(keepEditor, 0);
}, true);
document.addEventListener('click', () => { if (editing && editing.switching) setTimeout(keepEditor, 0); }, true);

async function clearSelectionValues() {
  const s = currentSelection();
  if (!s || !s.grid.opts.editable || !s.grid.book) return;
  const items = inputRefs(s.grid, s).filter((x) => x.cell.i).map((x) => ({ ref: x.ref, value: '' }));
  if (!items.length) return;
  try {
    const res = await hooks.setInputs(s.grid.book, items, false, false, s.grid.opts.copy || null);
    reportApply(res, 'temizlendi');
  } catch (err) {
    toast(err.message || String(err), 'err', 6000);
  }
}

// ---------------------------------------------------------------------- keyboard
function moveBy(dr, dc, extend) {
  const g = sel.grid;
  if (!g) return;
  const rows = g.data.rows.length, cols = rows ? g.data.rows[0].length : 0;
  let r = sel.r1, c = sel.c1;
  for (let guard = 0; guard < 400; guard++) {
    r += dr; c += dc;
    if (r < 0 || c < 0 || r >= rows || c >= cols) return;
    if (g.tds[r] && g.tds[r][c] && !g.tds[r][c].hidden) break;           // (a column the user hid is stepped over)
  }
  if (extend) setSelection(g, sel.r0, sel.c0, r, c);
  else setSelection(g, r, c, r, c);
  const td = g.tds[r] && g.tds[r][c];
  if (td && td.scrollIntoView) td.scrollIntoView({ block: 'nearest', inline: 'nearest' });
}

let shiftHeld = false;
document.addEventListener('keyup', (e) => { if (e.key === 'Shift') shiftHeld = false; });
document.addEventListener('keydown', (e) => {
  if (e.key === 'Shift') shiftHeld = true;
  if (editing) return;
  if (inFormControl(e.target)) return;
  if (document.querySelector('.modal-back')) return;
  const g = sel.grid;
  if (!g) return;
  if (e.altKey && e.key.startsWith('Arrow')) return;            // (Alt+← / Alt+→: back / forward, not the selection)
  const mod = e.ctrlKey || e.metaKey;
  switch (e.key) {
    case 'ArrowUp': moveBy(-1, 0, e.shiftKey); e.preventDefault(); return;
    case 'ArrowDown': moveBy(1, 0, e.shiftKey); e.preventDefault(); return;
    case 'ArrowLeft': moveBy(0, -1, e.shiftKey); e.preventDefault(); return;
    case 'ArrowRight': moveBy(0, 1, e.shiftKey); e.preventDefault(); return;
    case 'Tab': moveBy(0, e.shiftKey ? -1 : 1, false); e.preventDefault(); return;
    case 'Enter':
    case 'F2':
      if (startEdit(g, sel.r1, sel.c1, null)) e.preventDefault();
      else if (e.key === 'Enter') { moveBy(e.shiftKey ? -1 : 1, 0, false); e.preventDefault(); }
      return;
    case 'Escape': clearSelection(); closeMenu(); return;
    case 'Delete':
    case 'Backspace': clearSelectionValues(); e.preventDefault(); return;
    default: break;
  }
  if (mod && (e.key === 'a' || e.key === 'A')) { selectAll(g); e.preventDefault(); return; }
  if (!mod && !e.altKey && e.key.length === 1) {
    if (startEdit(g, sel.r1, sel.c1, e.key)) e.preventDefault();
    else readOnlySaid(g, sel.r1, sel.c1);
  }
});

document.addEventListener('mouseup', () => { sel.dragging = false; });
document.addEventListener('mousedown', (e) => {
  // a click outside any grid (and outside menus / editors) drops the selection
  if (!sel.grid) return;
  const t = e.target;
  if (t.closest && (t.closest('table.grid') || t.closest('.menu') || t.closest('#statusbar') || t.closest('#grid-fx'))) return;
  if (editing && editing.switching) return;             // (a tab opened while a formula is typed: the typing goes on)
  if (editing) commitEdit();
  clearSelection();
});

/** The <td> showing a workbook cell ("Forward!D2") if it is on screen (used by tests and deep links) - under ``root``,
 *  leaving out what is under ``skip`` (the same range may be on the page and in the side drawer).  A temporary copy of
 *  a table shows the same cells: it is looked at only when ``root`` is (or holds) the copy itself, never from the whole
 *  document - the cell of a sheet is the table's own. */
export function findCell(ref, root = document, skip = null) {
  const k = ref.lastIndexOf('!');
  if (k < 0) return null;
  const sheet = ref.slice(0, k);
  const m = /^([A-Z]+)(\d+)$/.exec(ref.slice(k + 1).toUpperCase());
  if (!m) return null;
  if (!root) return null;
  for (const table of root.querySelectorAll('table.grid')) {
    const g = table.__grid;
    if (!g || !g.data || g.data.sheet !== sheet || !g.data.c || !g.data.r) continue;
    if (skip && skip.contains(table)) continue;
    if (g.opts.copy && root === document) continue;
    const j = g.data.c.indexOf(m[1]);
    const i = g.data.r.indexOf(Number(m[2]));
    if (i >= 0 && j >= 0 && g.tds[i] && g.tds[i][j]) return g.tds[i][j];
  }
  return null;
}

/**
 * Build grid data from plain rows (client-rendered tables such as the blotter lists).  A caption is a text, or
 * {t, ck}: ``ck`` names the column for the user's column choice when the caption changes ("σ 10g (bp)" -> "σ 10g").
 * ``opts.freeze``: its first n columns stay in view while it scrolls sideways (the instrument's name of a wide list;
 * the desk, 27.11.2026) - the Grid's own ``freeze`` option does the same for every data it is given.
 */
export function plainData(header, rows, opts) {
  const out = [];
  if (header) out.push(header.map((t) => (t && typeof t === 'object' ? Object.assign({ k: 's', b: 1, f: 'hd' }, t) : { t, k: 's', b: 1, f: 'hd' })));
  for (const row of rows) {
    out.push(row.map((c) => {
      if (c === null || c === undefined) return { t: '', k: '' };
      if (typeof c === 'object') return c;
      return { t: String(c), k: 's' };
    }));
  }
  const data = { sheet: '', rows: out };
  const n = opts && opts.freeze;
  if (n > 0 && out.length && n < out[0].length) data.fz = n;
  return data;
}
