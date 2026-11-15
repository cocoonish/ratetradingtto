// Spreadsheet-like table: range selection, Excel-compatible copy / paste, in-cell editing of input cells,
// in-place refresh with change flashes, the columns each user hides.
import { h, clear, menu, closeMenu, inFormControl, toast } from './ui.js';
import { raw } from './format.js';
import { Columns, captionKey, markGaps, uniqueKeys } from './columns.js';

const hooks = {
  setInputs: null,     // async (book, items, adhoc, lenient) -> result   (lenient: cells that are not inputs are skipped)
  paste: null,         // async (book, anchorRef, text, adhoc) -> result
  reset: null,         // async (book, refs, shared) -> result
  onSelect: null,      // (info | null)
};

const sel = { grid: null, r0: 0, c0: 0, r1: 0, c1: 0, cells: [], cur: null, dragging: false };
let editing = null;      // {grid, i, j, td, input}

export function configureGrid(opts) {
  Object.assign(hooks, opts);
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
  if (cell.n) cls += ' nt';
  if (typeof cell.bar === 'number') cls += ' bar bar-' + (cell.bc || 'info');
  if (cell.i) {
    cls += ' in';
    if (cell.i === 's') cls += ' sh';
    if (cell.m) cls += ' mod';
    if (cell.fx && cell.m === 1) cls += ' hand';        // this user's value stands where the workbook has a formula
    // filled by the workbook (market, another cell) until typed over; one that came out empty or as an error
    // (the market did not deliver) stays a plain input: that is where a value has to be typed
    else if (cell.fx && !cell.m && cell.t && cell.k !== 'e') cls += ' auto';
  }
  return cls;
}

function signature(cell) {
  return (cell.t || '') + '\u0001' + cellClass(cell) + '\u0001' + (cell.heat || '') + '\u0001' + (cell.rs || 1) + 'x' + (cell.cs || 1)
    + '\u0001' + (typeof cell.bar === 'number' ? cell.bar : '');
}

/**
 * Excel lets a long text run over the empty cells to its right; do the same with a column span so notes and
 * captions do not blow up the width of their own column.  Marks the data once (the shape check sees it).
 */
function prepare(data) {
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
        for (let k = 1; k <= n; k++) row[j + k].sk = 1;
        j += n;
      }
    }
  }
  return data;
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

export class Grid {
  /**
   * opts: book, data {sheet, rows, r, c}, editable (bool), adhoc (bool: any cell may be overridden),
   *       axis (bool: show A/B/C and 1/2/3 headers), header (bool: detect header rows),
   *       name (the table's stable name: each user hides columns of it, kept with the account),
   *       tools (the panel's tools: the "Sütunlar" button goes there)
   */
  constructor(opts) {
    this.opts = Object.assign({ editable: true, adhoc: false, axis: false, header: true }, opts);
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
    this.columns = this.opts.name && !this.opts.axis ? new Columns(this.opts.name, () => this._showColumns()) : null;
    if (this.columns) this.columns.mount(this.opts.tools);
    this.update(this.opts.data, false);
    if (window.ResizeObserver) {
      // column widths change with the content and when a collapsed panel opens: re-pin the frozen columns
      this._ro = new ResizeObserver(() => this._freeze());
      this._ro.observe(this.el);
    }
  }

  ref(i, j) {
    const d = this.data;
    if (!d || !d.r || !d.c || !d.r[i] || d.c[j] === undefined) return null;      // (row 0: a caption row of the dashboard's own)
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
    prepare(data);
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
    prepare(data);
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
          td.textContent = cell.t || '';
        }
        if (cell.rs) td.rowSpan = cell.rs;
        if (cell.cs) td.colSpan = cell.cs;
        if (cell.heat) td.style.backgroundColor = heatStyle(cell.heat);
        if (typeof cell.bar === 'number') td.style.setProperty('--bar', cell.bar + '%');
        if (cell.n) td.title = cell.n + (cell.tip ? '\n' + cell.tip : '');          // the cell's comment in Excel
        else if (cell.tip) td.title = cell.tip;
        else if (cell.k === 's' && cell.t && cell.t.length > 28) td.title = cell.t;
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
    const n = this.data && this.data.fz;
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
        const keepSel = td.classList.contains('sel'), keepCur = td.classList.contains('cur');
        if (cell.act || cell.chk) continue;
        td.className = cellClass(cell) + (cell.cls ? ' ' + cell.cls : '') + (keepSel ? ' sel' : '') + (keepCur ? ' cur' : '');
        td.textContent = cell.t || '';
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
    if (td) startEdit(this, td.__i, td.__j, null);
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
    const mine = inputs.filter((x) => x.cell.i === 'u').map((x) => x.ref);
    const shared = inputs.filter((x) => x.cell.i === 's' && x.cell.m).map((x) => x.ref);
    // one cell of a sheet: watch it, or an alarm on it
    const one = cur && cur.top === cur.bottom && cur.left === cur.right ? { ref: this.ref(cur.top, cur.left), cell: this.cell(cur.top, cur.left) } : null;
    const watchable = one && one.ref && this.book && one.cell && typeof one.cell.v === 'number' && (hooks.watch || hooks.alarm);
    const label = watchable ? cellLabel(this, cur.top, cur.left) : '';
    // the columns under the click (a merged caption: all of its own) can be hidden from this user's view
    let cols = [];
    if (this.columns) {
      const lone = cur.top === cur.bottom && cur.left === cur.right ? this.cell(cur.top, cur.left) : null;
      const right = lone && !lone.ov ? cur.left + (lone.cs || 1) - 1 : cur.right;
      const js = [];
      for (let j = cur.left; j <= right; j++) js.push(j);
      cols = [{ sep: true }].concat(this.columns.menuItems(js, e.clientX, e.clientY));
    }
    menu(e.clientX, e.clientY, [
      watchable && hooks.watch ? { label: 'İzlemeye ekle', action: () => hooks.watch(this.book, one.ref, label) } : null,
      watchable && hooks.alarm ? { label: 'Alarm kur…', action: () => hooks.alarm(this.book, one.ref, label, one.cell.t) } : null,
      watchable ? { sep: true } : null,
      { label: 'Kopyala  (Ctrl+C)', action: () => copyViaCommand(false) },
      { label: 'Tam hassasiyetle kopyala  (Ctrl+Shift+C)', action: () => copyViaCommand(true) },
      { label: 'Tüm tabloyu seç  (Ctrl+A)', action: () => selectAll(this) },
      inputs.length ? { sep: true } : null,
      inputs.length ? { header: 'Yapıştırmak için Ctrl+V' } : null,
      mine.length ? { label: 'Kendi girdimi sil → varsayılana dön', action: () => resetRefs(this, mine, false) } : null,
      shared.length ? { label: 'Ortak girdiyi dosyadaki değere döndür', action: () => resetRefs(this, shared, true) } : null,
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
    grid: g, book: g.book, ref: a, single,
    label: !a ? '' : (single ? a : a + ':' + b.split('!')[1]),
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
 * True when the block, laid over the screen from (top, the columns ``vis``), covers rows and columns that follow
 * each other in the sheet as well - then the screen and the sheet agree on where every pasted cell goes.
 */
function sheetContiguous(grid, top, vis, rows, cols) {
  const d = grid.data;
  if (top + rows > d.r.length || cols > vis.length) return false;
  for (let i = 1; i < rows; i++) if (d.r[top + i] !== d.r[top + i - 1] + 1) return false;
  for (let j = 1; j < cols; j++) if (colIndex(d.c[vis[j]]) !== colIndex(d.c[vis[j - 1]]) + 1) return false;
  return true;
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
    if (single && (s.bottom > s.top || s.right > s.left)) {
      // one value onto a selection: fill every input cell of the selection (as Excel does)
      items = inputRefs(grid, s).map((x) => ({ ref: x.ref, value: clean }));
    } else if (clean !== lastCopied && !sheetContiguous(grid, s.top, vis, matrix.length, width)) {
      // a block from Excel that runs over rows / columns the table does not show (hidden in Excel, or empty
      // and left out): it keeps Excel's layout, counted in sheet cells from the top-left of the selection.
      // Nothing outside the table's own range is written; the server skips whatever is not an input; a column
      // this user hid is not written to either.
      const d = grid.data;
      const row0 = d.r[s.top], col0 = colIndex(d.c[vis[0]]);
      const rowMax = d.r[d.r.length - 1], colMax = colIndex(d.c[d.c.length - 1]);
      const hiddenCols = new Set(d.c.filter((c, j) => grid.colHidden(j)));
      for (let i = 0; i < matrix.length; i++) {
        for (let j = 0; j < matrix[i].length; j++) {
          if (row0 + i > rowMax || col0 + j > colMax) { skipped += 1; continue; }
          if (hiddenCols.has(colName(col0 + j))) { unseen += 1; continue; }
          items.push({ ref: d.sheet + '!' + colName(col0 + j) + (row0 + i), value: matrix[i][j] });
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
    const res = await hooks.setInputs(grid.book, items, grid.opts.adhoc, lenient);
    if (res) { res.skipped = skipped + (res.skipped || 0); res.unseen = unseen; }
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
  if (errs.length) msg += ' · ' + errs.length + ' hata: ' + errs.slice(0, 3).join('; ');
  toast(msg, errs.length ? 'err' : 'ok', errs.length ? 7000 : 2600);
}

async function resetRefs(grid, refs, shared) {
  try {
    const res = await hooks.reset(grid.book, refs, shared);
    toast((res.reset || 0) + ' hücre varsayılana döndü', 'ok', 2200);
  } catch (err) {
    toast(err.message || String(err), 'err', 6000);
  }
}

// ---------------------------------------------------------------------- editing
function editText(cell) {
  if (!cell) return '';
  if (cell.k === 'n' && typeof cell.v === 'number') {
    if (cell.ik === 'pct') return raw(cell.v * 100) + '%';
    return raw(cell.v);
  }
  return cell.t || '';
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
  editing = { grid, i, j, td, input, done: false };
  input.focus();
  if (typed === null) input.select();
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') { e.preventDefault(); commitEdit(); moveBy(e.shiftKey ? -1 : 1, 0, false); }
    else if (e.key === 'Tab') { e.preventDefault(); commitEdit(); moveBy(0, e.shiftKey ? -1 : 1, false); }
    else if (e.key === 'Escape') { e.preventDefault(); cancelEdit(); }
    e.stopPropagation();
  });
  input.addEventListener('blur', () => { if (editing && editing.input === input) commitEdit(); });
  return true;
}

function finishEdit() {
  const ed = editing;
  editing = null;
  if (!ed) return null;
  ed.td.classList.remove('editing');
  const cell = ed.grid.cell(ed.i, ed.j);
  if (ed.input.parentNode === ed.td) ed.td.removeChild(ed.input);
  ed.td.textContent = cell ? (cell.t || '') : '';
  return ed;
}

function cancelEdit() {
  finishEdit();
}

function commitEdit() {
  if (!editing) return;
  const value = editing.input.value;
  const ed = finishEdit();
  const cell = ed.grid.cell(ed.i, ed.j);
  if (value === editText(cell)) return;                 // nothing typed
  ed.td.textContent = value;                            // optimistic until the refresh arrives
  applyValue(ed.grid, ed.i, ed.j, value);
}

async function applyValue(grid, i, j, value) {
  const ref = grid.ref(i, j);
  if (!ref) return;
  try {
    const res = await hooks.setInputs(grid.book, [{ ref, value }], grid.opts.adhoc);
    if (res && res.errors && res.errors.length) {
      toast(res.errors.join('; '), 'err', 6000);
      const td = grid.tds[i] && grid.tds[i][j];
      const cell = grid.cell(i, j);
      if (td && cell) td.textContent = cell.t || '';
    }
  } catch (err) {
    toast(err.message || String(err), 'err', 6000);
    const td = grid.tds[i] && grid.tds[i][j];
    const cell = grid.cell(i, j);
    if (td && cell) td.textContent = cell.t || '';
  }
}

async function clearSelectionValues() {
  const s = currentSelection();
  if (!s || !s.grid.opts.editable || !s.grid.book) return;
  const items = inputRefs(s.grid, s).filter((x) => x.cell.i).map((x) => ({ ref: x.ref, value: '' }));
  if (!items.length) return;
  try {
    const res = await hooks.setInputs(s.grid.book, items, false);
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
  }
});

document.addEventListener('mouseup', () => { sel.dragging = false; });
document.addEventListener('mousedown', (e) => {
  // a click outside any grid (and outside menus / editors) drops the selection
  if (!sel.grid) return;
  const t = e.target;
  if (t.closest && (t.closest('table.grid') || t.closest('.menu') || t.closest('#statusbar'))) return;
  if (editing) commitEdit();
  clearSelection();
});

/** The <td> showing a workbook cell ("Forward!D2") if it is on screen (used by tests and deep links). */
export function findCell(ref, root = document) {
  const k = ref.lastIndexOf('!');
  if (k < 0) return null;
  const sheet = ref.slice(0, k);
  const m = /^([A-Z]+)(\d+)$/.exec(ref.slice(k + 1).toUpperCase());
  if (!m) return null;
  for (const table of root.querySelectorAll('table.grid')) {
    const g = table.__grid;
    if (!g || !g.data || g.data.sheet !== sheet || !g.data.c || !g.data.r) continue;
    const j = g.data.c.indexOf(m[1]);
    const i = g.data.r.indexOf(Number(m[2]));
    if (i >= 0 && j >= 0 && g.tds[i] && g.tds[i][j]) return g.tds[i][j];
  }
  return null;
}

/**
 * Build grid data from plain rows (client-rendered tables such as the blotter lists).  A caption is a text, or
 * {t, ck}: ``ck`` names the column for the user's column choice when the caption changes ("σ 10g (bp)" -> "σ 10g").
 */
export function plainData(header, rows) {
  const out = [];
  if (header) out.push(header.map((t) => (t && typeof t === 'object' ? Object.assign({ k: 's', b: 1, f: 'hd' }, t) : { t, k: 's', b: 1, f: 'hd' })));
  for (const row of rows) {
    out.push(row.map((c) => {
      if (c === null || c === undefined) return { t: '', k: '' };
      if (typeof c === 'object') return c;
      return { t: String(c), k: 's' };
    }));
  }
  return { sheet: '', rows: out };
}
