// Spreadsheet-like table: range selection, Excel-compatible copy / paste, in-cell editing of input cells,
// in-place refresh with change flashes.
import { h, clear, menu, closeMenu, inFormControl, toast } from './ui.js';
import { raw } from './format.js';

const hooks = {
  setInputs: null,     // async (book, items, adhoc) -> result
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
  if (cell.i) {
    cls += ' in';
    if (cell.i === 's') cls += ' sh';
    if (cell.m) cls += ' mod';
  }
  return cls;
}

function signature(cell) {
  return (cell.t || '') + '\u0001' + cellClass(cell) + '\u0001' + (cell.heat || '') + '\u0001' + (cell.rs || 1) + 'x' + (cell.cs || 1);
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
      if (c.sk || c.k !== 's' || c.cs || c.rs || c.i || c.act || !c.t || c.t.length < 14) continue;
      if (c.al === 'r' || c.al === 'c') continue;
      let n = 0;
      while (j + n + 1 < row.length) {
        const x = row[j + n + 1];
        if (x.sk || x.t || x.i || x.f || x.heat || x.cs || x.rs || x.act) break;
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
    n += 1;
    if (cell.b || cell.f === 'hd') strong += 1;
  }
  return n >= 2 && strong * 2 >= n;
}

export class Grid {
  /**
   * opts: book, data {sheet, rows, r, c}, editable (bool), adhoc (bool: any cell may be overridden),
   *       axis (bool: show A/B/C and 1/2/3 headers), header (bool: detect header rows)
   */
  constructor(opts) {
    this.opts = Object.assign({ editable: true, adhoc: false, axis: false, header: true }, opts);
    this.book = this.opts.book || null;
    this.data = null;
    this.tds = [];
    this.el = h('table', { class: 'grid' + (this.opts.axis ? ' addr' : '') });
    this.el.__grid = this;
    this.el.addEventListener('mousedown', (e) => this._mouseDown(e));
    this.el.addEventListener('mouseover', (e) => this._mouseOver(e));
    this.el.addEventListener('dblclick', (e) => this._dblClick(e));
    this.el.addEventListener('contextmenu', (e) => this._context(e));
    this.update(this.opts.data, false);
  }

  ref(i, j) {
    const d = this.data;
    if (!d || !d.r || !d.c || d.r[i] === undefined || d.c[j] === undefined) return null;
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

  update(data, flash = true) {
    if (!data || !data.rows) return;
    prepare(data);
    if (this.sameShape(data)) {
      this._patch(data, flash);
    } else {
      const hadSel = sel.grid === this;
      if (hadSel) clearSelection();
      this.data = data;
      this._build();
    }
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
    let headerRun = this.opts.header;
    let headerCount = 0;
    for (let i = 0; i < d.rows.length; i++) {
      const row = d.rows[i];
      const tr = h('tr');
      if (headerRun && headerCount < 2 && isHeaderRow(row)) {
        tr.className = 'hd' + (headerCount === 1 ? ' hd2' : '');
        headerCount += 1;
      } else if (i > 0 || !this.opts.header) {
        headerRun = false;
      } else {
        // a lone title row may precede the header row
        const filled = row.filter((c) => !c.sk && c.t).length;
        if (filled > 1) headerRun = false;
      }
      if (this.opts.axis) tr.appendChild(h('td', { class: 'axis rowh' }, String(d.r[i])));
      const line = [];
      for (let j = 0; j < row.length; j++) {
        const cell = row[j];
        if (cell.sk) { line.push(null); continue; }
        const td = document.createElement('td');
        td.className = cellClass(cell) + (cell.cls ? ' ' + cell.cls : '');
        if (cell.act) {
          const b = h('button', { class: 'iconbtn', type: 'button', title: cell.act.title || '' }, cell.act.label);
          b.addEventListener('click', (e) => { e.stopPropagation(); cell.act.fn(); });
          td.appendChild(b);
        } else {
          td.textContent = cell.t || '';
        }
        if (cell.rs) td.rowSpan = cell.rs;
        if (cell.cs) td.colSpan = cell.cs;
        if (cell.heat) td.style.backgroundColor = heatStyle(cell.heat);
        if (cell.tip) td.title = cell.tip;
        td.__i = i;
        td.__j = j;
        tr.appendChild(td);
        line.push(td);
      }
      this.tds.push(line);
      body.appendChild(tr);
    }
    this.el.appendChild(body);
  }

  _patch(data, flash) {
    const old = this.data;
    this.data = data;
    for (let i = 0; i < data.rows.length; i++) {
      const row = data.rows[i], prev = old.rows[i], line = this.tds[i];
      for (let j = 0; j < row.length; j++) {
        const td = line[j];
        if (!td) continue;
        const cell = row[j], before = prev[j];
        if (editing && editing.td === td) continue;
        if (signature(cell) === signature(before)) continue;
        const keepSel = td.classList.contains('sel'), keepCur = td.classList.contains('cur');
        if (cell.act) continue;
        td.className = cellClass(cell) + (cell.cls ? ' ' + cell.cls : '') + (keepSel ? ' sel' : '') + (keepCur ? ' cur' : '');
        td.textContent = cell.t || '';
        td.style.backgroundColor = cell.heat ? heatStyle(cell.heat) : '';
        if (flash && cell.k === 'n' && before.k === 'n' && typeof cell.v === 'number' && typeof before.v === 'number'
            && cell.v !== before.v) {
          const cls = cell.v > before.v ? 'up' : 'down';
          td.classList.remove('up', 'down');
          void td.offsetWidth;                       // restart the animation
          td.classList.add(cls);
        }
      }
    }
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
    menu(e.clientX, e.clientY, [
      { label: 'Kopyala  (Ctrl+C)', action: () => copyViaCommand(false) },
      { label: 'Tam hassasiyetle kopyala  (Ctrl+Shift+C)', action: () => copyViaCommand(true) },
      { label: 'Tüm tabloyu seç  (Ctrl+A)', action: () => selectAll(this) },
      inputs.length ? { sep: true } : null,
      inputs.length ? { header: 'Yapıştırmak için Ctrl+V' } : null,
      mine.length ? { label: 'Kendi girdimi sil → varsayılana dön', action: () => resetRefs(this, mine, false) } : null,
      shared.length ? { label: 'Ortak girdiyi dosyadaki değere döndür', action: () => resetRefs(this, shared, true) } : null,
    ]);
  }
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
  let count = 0, sum = 0, n = 0, min = Infinity, max = -Infinity;
  for (let i = s.top; i <= s.bottom; i++) {
    for (let j = s.left; j <= s.right; j++) {
      const c = g.cell(i, j);
      if (!c || c.sk) continue;
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
    rows: s.bottom - s.top + 1, cols: s.right - s.left + 1,
  });
}

function inputRefs(grid, s) {
  const out = [];
  if (!s) return out;
  for (let i = s.top; i <= s.bottom; i++) {
    for (let j = s.left; j <= s.right; j++) {
      const c = grid.cell(i, j);
      const ref = grid.ref(i, j);
      if (c && !c.sk && ref && (c.i || grid.opts.adhoc)) out.push({ ref, cell: c, i, j });
    }
  }
  return out;
}

// ---------------------------------------------------------------------- clipboard
export function selectionText(full) {
  const s = currentSelection();
  if (!s) return null;
  const g = s.grid;
  const lines = [];
  for (let i = s.top; i <= s.bottom; i++) {
    const parts = [];
    for (let j = s.left; j <= s.right; j++) {
      const c = g.cell(i, j);
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
      navigator.clipboard.writeText(text).then(() => toast('Kopyalandı', 'ok', 1500), () => toast('Kopyalanamadı', 'err'));
    }
  }
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
  const s = currentSelection();
  const n = (s.bottom - s.top + 1) * (s.right - s.left + 1);
  toast(n === 1 ? 'Hücre kopyalandı' : (s.bottom - s.top + 1) + ' × ' + (s.right - s.left + 1) + ' hücre kopyalandı – Excel\'e yapıştırabilirsiniz', 'ok', 1800);
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

export async function pasteText(grid, s, text) {
  const anchor = grid.ref(s.top, s.left);
  if (!anchor) return;
  const clean = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n').replace(/\n$/, '');
  const single = !clean.includes('\t') && !clean.includes('\n');
  try {
    let res;
    if (single && (s.bottom > s.top || s.right > s.left)) {
      const items = inputRefs(grid, s).map((x) => ({ ref: x.ref, value: clean }));
      if (!items.length) { toast('Seçimde girdi hücresi yok', 'err'); return; }
      res = await hooks.setInputs(grid.book, items, grid.opts.adhoc);
    } else {
      res = await hooks.paste(grid.book, anchor, clean, grid.opts.adhoc);
    }
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
  if (!cell || !td || !grid.opts.editable || !grid.book) return false;
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
    if (g.tds[r] && g.tds[r][c]) break;
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

/** Build grid data from plain rows (client-rendered tables such as the blotter lists). */
export function plainData(header, rows) {
  const out = [];
  if (header) out.push(header.map((t) => ({ t, k: 's', b: 1, f: 'hd' })));
  for (const row of rows) {
    out.push(row.map((c) => {
      if (c === null || c === undefined) return { t: '', k: '' };
      if (typeof c === 'object') return c;
      return { t: String(c), k: 's' };
    }));
  }
  return { sheet: '', rows: out };
}
