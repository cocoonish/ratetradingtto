// A personal calc sheet ("Hesap tablosu"): a small Excel-like grid of one's own on a launchpad, in the side drawer or in
// a window of its own.  Its cells hold numbers, texts or formulas over the dashboard's live cells (=MASA!I60+25); the
// server keeps the sheet with the account and evaluates it as the user's pages are (calc.py) - again on each generation,
// all the sheets on screen in one request.  Excel's habits: click to select, Enter / F2 / typing to edit, the formula
// bar, arrows and Tab, Esc, a block copied to / pasted from Excel, Delete, a number format per cell, column widths;
// while a formula is typed a click on one of its cells (Ctrl+click on a table of a page or of the drawer) puts the
// reference in.  Bloomberg functions are refused by the server, with the reason.
import { api, session } from './api.js';
import { h, clear, menu, toast, promptDialog } from './ui.js';
import { num, raw, settings } from './format.js';
import { WIDTHS, saveLayout, drawerItems, launchpads, findLaunchpad, changeLaunchpad, createLaunchpad, newId } from './layout.js';

export const MAX_ROWS = 50;
export const MAX_COLS = 12;
const DEFAULT_W = 96;
const MIN_W = 40;
const MAX_W = 600;
const RH_W = 34;                                   // the row numbers' column
const DATE_FMT = 'dd\\.mm\\.yyyy';
const HELP = 'Hücreye sayı, metin ya da formül yazın: =MASA!I60+25 · kendi hücreleri: A1, $A$1, A1:A5 · '
  + 'dashboard\'un hücreleri sayfa adıyla: MASA!I60, \'C & R\'!B5 · diğer kitaplar köşeli parantezle: [sofr]SOFR_FOMC!B9, '
  + '[asw]ASW!C5, [borsa]bu!A1 · işlev adları İngilizce (SUM, IF, ROUND, WORKDAY …), ayırıcı virgül ya da noktalı virgül · '
  + 'formül yazarken bir hücreye tıklayın (bir sayfanın ya da yan panelin tablosunda Ctrl+tık): adresi eklenir · '
  + 'Bloomberg işlevleri (BDP, BDH, BDS …) kullanılamaz.';

let seq = 0;
const live = new Map();          // sheet id -> the boxes showing it in this window
let editingBox = null;           // the box one of whose cells is being typed into
let clip = null;                 // what was last copied out of a calc sheet: pasted back, its formulas move along
let resizing = null;             // a column being widened by its grip

export function colName(n) {
  let s = '';
  while (n > 0) { const m = (n - 1) % 26; s = String.fromCharCode(65 + m) + s; n = (n - 1 - m) / 26; }
  return s;
}

function colIndex(s) {
  let n = 0;
  for (const ch of s) n = n * 26 + (ch.charCodeAt(0) - 64);
  return n;
}

export const cellName = (r, c) => colName(c) + r;
const isFormula = (s) => typeof s === 'string' && s.startsWith('=');
const normalise = (text) => text.replace(/\r\n/g, '\n').replace(/\r/g, '\n').replace(/\n$/, '');
const clamp = (x, lo, hi) => Math.max(lo, Math.min(hi, x));

/** A workbook cell ("C & R!B5" of the book "tto") as a calc formula names it: 'C & R'!B5, [sofr]SOFR_FOMC!B9. */
export function workbookRef(book, ref) {
  const k = ref.lastIndexOf('!');
  const sheet = ref.slice(0, k);
  const name = book && book !== 'tto' ? '[' + book + ']' + sheet : sheet;
  const plain = /^[A-Za-z_][A-Za-z0-9_.]*$/.test(sheet) && !/^[A-Za-z]{1,3}\d+$/.test(sheet);
  return (plain ? name : "'" + name.replace(/'/g, "''") + "'") + '!' + ref.slice(k + 1);
}

// ---------------------------------------------------------------------- number formats (the toolbar)
function decimalsShown(text) {
  const m = new RegExp('\\' + (settings.lang === 'en' ? '.' : ',') + '(\\d+)').exec(text || '');
  return m ? m[1].length : 0;
}

/** An Excel number format as the toolbar changes it: {kind: gen | num | date, d: decimals, t: thousands, p: percent}. */
function fmtParts(code, shown) {
  if (!code || code === 'General') return { kind: 'gen', d: decimalsShown(shown), t: false, p: false };
  const sec = code.split(';')[0].replace(/"[^"]*"/g, '').replace(/\[[^\]]*\]/g, '').replace(/\\./g, '');
  if (/[dmyh]/i.test(sec) && !/[0#]/.test(sec)) return { kind: 'date', d: 0, t: false, p: false };
  const m = /\.([0#]+)/.exec(sec);
  return { kind: 'num', d: m ? m[1].length : 0, t: sec.includes(','), p: sec.includes('%') };
}

const fmtCode = (p) => (p.t ? '#,##0' : '0') + (p.d > 0 ? '.' + '0'.repeat(p.d) : '') + (p.p ? '%' : '');

// ---------------------------------------------------------------------- one request for every sheet on screen
const batch = { boxes: new Set(), job: null };

function ask(box) {
  batch.boxes.add(box);
  if (!batch.job) batch.job = Promise.resolve().then(flush);
  return batch.job;
}

async function flush() {
  const boxes = [...batch.boxes].filter((b) => !b.dead);
  batch.boxes.clear();
  batch.job = null;
  if (!boxes.length) return;
  let res;
  try {
    res = await api.post('/api/calc/eval', { items: boxes.map((b) => b.wants()) });
  } catch (err) {
    if (!err.network && err.status !== 401) for (const b of boxes) if (!b.data) b.fail(err.message);
    return;
  }
  for (const b of boxes) if (!b.dead) b.apply((res.sheets || {})[b.key]);
}

// the other windows of this browser (the drawer of another tab, a pop-out) hear of a change at once
const chan = typeof window.BroadcastChannel === 'function' ? new BroadcastChannel('tto-calc') : null;
if (chan) {
  chan.onmessage = (e) => {
    const m = e.data || {};
    if (!session.user || m.user !== session.user) return;
    for (const b of live.get(m.sheet) || []) if (b.rev !== m.rev && b.wanted()) ask(b);
  };
}

/** A sheet changed here (a save answered): every box of it in this window shows the answer, the other windows ask. */
function changedHere(sheet, ans) {
  for (const b of live.get(sheet) || []) b.take(ans, false);
  if (chan) chan.postMessage({ user: session.user, sheet, rev: ans.rev });
}

// ---------------------------------------------------------------------- the page around the boxes
// while a formula is typed, Ctrl+click on a cell of a table (a page's, the drawer's) puts its reference in
document.addEventListener('mousedown', (e) => {
  const box = editingBox;
  if (!box || !box.edit || e.button !== 0 || !(e.ctrlKey || e.metaKey) || !isFormula(box.edit.input.value)) return;
  const td = e.target.closest && e.target.closest('table.grid td');
  const table = td && td.closest('table.grid');
  const g = table && table.__grid;
  if (!g || td.__i === undefined) return;
  e.preventDefault();
  e.stopPropagation();
  const ref = g.ref(td.__i, td.__j);
  if (!ref) { toast('Bu tablonun hücreleri bir çalışma kitabı sayfasında değil: başvurusu eklenemez', 'err'); return; }
  box.insertRef(workbookRef(g.book, ref));
}, true);

document.addEventListener('mousemove', (e) => {
  if (!resizing) return;
  const w = clamp(Math.round(resizing.w0 + e.clientX - resizing.x0), MIN_W, MAX_W);
  resizing.w = w;
  resizing.col.style.width = w + 'px';
  resizing.box.fitTable();
});

document.addEventListener('mouseup', () => {
  for (const set of live.values()) for (const b of set) b.drag = null;
  if (resizing) {
    const r = resizing;
    resizing = null;
    if (r.w && r.w !== r.w0) r.box.save({ widths: { [colName(r.c)]: r.w } });
  }
});

// ---------------------------------------------------------------------- a new sheet
/** A new calc sheet on the launchpad named (made when there is none); the launchpad's name, or null. */
export async function addCalcSheet(name) {
  const item = { type: 'calc', id: newId(), sheet: newId(), w: 6, h: 'auto' };
  const lp = name ? findLaunchpad(name) : null;
  if (!lp) {
    const made = await createLaunchpad([item]);
    if (made) toast('"' + made + '" launchpad\'i oluşturuldu, hesap tablosu eklendi', 'ok', 3200);
    if (made) focusSheet(item.sheet);
    return made;
  }
  if (lp.items.length >= 60) { toast('Bir launchpad en fazla 60 öğe alır', 'err'); return null; }
  try { await changeLaunchpad(lp.name, (x) => { x.items.push(item); }); } catch (e) { return null; }
  focusSheet(item.sheet);
  return lp.name;
}

function focusSheet(sheet) {
  const box = [...(live.get(sheet) || [])][0];
  if (box) { box.el.scrollIntoView({ block: 'nearest' }); box.select(1, 1, 1, 1); box.wrap.focus({ preventScroll: true }); }
}

// ---------------------------------------------------------------------- one box
export class CalcBox {
  /**
   * item: {type: 'calc', id, sheet, title?, w, h, collapsed?}
   * opts: {ctx, place: 'launchpad' | 'drawer' | 'pop', edit(change), remove(), move(step), draggable, live()}
   */
  constructor(item, opts) {
    this.item = item;
    this.opts = opts;
    this.key = 'c' + (++seq);
    this.gen = 0;
    this.rev = null;
    this.data = null;
    this.entry = null;
    this.dead = false;
    this.sel = { ar: 1, ac: 1, r: 1, c: 1 };     // the anchor and the active cell of the selection
    this.edit = null;                            // {r, c, input, where: cell | bar, mode: enter | edit, orig, point}
    this.drag = null;
    this.tds = [];
    this.selTds = [];
    this.typed = new Map();                      // cell -> {text, tok}: typed, its save on the way (shown, F2 edits it)
    this.el = h('section', { class: 'panel lp-item calc-box' + (opts.place === 'launchpad' ? '' : ' full') });
    this.el.__box = this;
    this.titleEl = h('h2');
    this.dims = h('span', { class: 'lp-src calc-dims' });
    this.tools = h('div', { class: 'tools' });
    const head = h('header');
    if (opts.draggable) head.appendChild(h('span', { class: 'lp-drag', title: 'Sürükleyip bırakarak yerini değiştirin', draggable: 'true' }, '⠿'));
    head.append(this.titleEl, this.dims, this.tools);
    const more = h('button', { class: 'iconbtn', type: 'button', title: 'Genişlik, yükseklik, ad, satır / sütun, yan panel, ayrı pencere …' }, '⋯');
    more.dataset.action = 'item-menu';
    more.addEventListener('click', (e) => {
      e.stopPropagation();
      const r = more.getBoundingClientRect();
      menu(r.left, r.bottom + 4, this.menuItems());
    });
    this.colBtn = h('button', { class: 'iconbtn', type: 'button', title: 'Daralt / aç' });
    this.colBtn.addEventListener('click', () => this.setCollapsed(!this.item.collapsed));
    this.tools.append(more, this.colBtn);
    if (opts.place === 'drawer' && opts.remove) {
      const x = h('button', { class: 'iconbtn', type: 'button', title: 'Yan panelden kaldır' }, '✕');
      x.dataset.action = 'unpin';
      x.addEventListener('click', () => opts.remove());
      this.tools.appendChild(x);
    }
    this.addr = h('span', { class: 'calc-addr' }, 'A1');
    this.fx = h('input', { class: 'calc-fx', type: 'text', spellcheck: 'false', autocomplete: 'off',
      placeholder: 'Sayı, metin ya da formül: =MASA!I60+25', title: HELP });
    this.msg = h('div', { class: 'calc-msg hidden' });
    this.wrap = h('div', { class: 'calc-wrap', tabindex: '0' }, h('div', { class: 'loading' }, 'Yükleniyor…'));
    this.hint = h('div', { class: 'calc-empty muted hidden' }, 'Boş bir hesap tablosu: bir hücreye tıklayıp yazın - sayı, metin ya da '
      + '=MASA!I60+25 gibi bir formül. Formül yazarken bir sayfanın tablosundaki hücreye Ctrl+tık: adresi eklenir.');
    this.body = h('div', { class: 'body calc-body' }, this.toolbar(),
      h('div', { class: 'calc-bar' }, this.addr, h('span', { class: 'calc-fxl', title: HELP }, 'fx'), this.fx), this.msg, this.wrap, this.hint);
    this.el.append(head, this.body);
    this.wire();
    this.show(item);
    this.join(item.sheet);
    if (CalcBox.hub) CalcBox.hub.add(this);
  }

  join(sheet) {
    if (!live.has(sheet)) live.set(sheet, new Set());
    live.get(sheet).add(this);
  }

  leave(sheet) {
    const set = live.get(sheet);
    if (set) { set.delete(this); if (!set.size) live.delete(sheet); }
  }

  /** The item as the layout has it now; true when it has to be asked for (opened again, another sheet). */
  show(item) {
    const before = this.item;
    this.item = item;
    this.el.dataset.key = 'calc/' + item.sheet;
    this.el.dataset.sheet = item.sheet;
    this.el.dataset.id = item.id;
    this.el.dataset.w = String(item.w || 6);
    this.el.dataset.h = String(item.h || 'auto');
    if (this.opts.place === 'launchpad') this.el.style.gridColumn = 'span ' + (item.w || 6);
    const fixed = typeof item.h === 'number';
    this.body.style.height = fixed ? item.h + 'px' : '';
    this.el.classList.toggle('fixed', fixed);
    this.el.classList.toggle('collapsed', !!item.collapsed);
    this.colBtn.textContent = item.collapsed ? '▸' : '▾';
    this.titleEl.textContent = item.title || 'Hesap tablosu';
    this.titleEl.title = (item.title || 'Hesap tablosu') + ' · kişisel hesap tablonuz (hesabınızla sunucuda saklanır)';
    const other = before !== item && before.sheet !== item.sheet;
    if (other) {
      this.leave(before.sheet);
      this.join(item.sheet);
      this.data = this.entry = null;
      this.gen = 0;
      this.rev = null;
    }
    return before !== item && (other || (!!before.collapsed && !item.collapsed));
  }

  wanted() {
    return !this.dead && !this.item.collapsed && this.el.isConnected && (!this.opts.live || this.opts.live());
  }

  /** Brought up to date with the other sheets on screen (one request for all of them). */
  refreshOwn() {
    return ask(this);
  }

  /** What this box asks of the sheet (no ``request()``: the hub's request is for the tables of pages). */
  wants() {
    const r = { key: this.key, sheet: this.item.sheet };
    if (this.data && this.gen) { r.since = this.gen; r.rev = this.rev; }
    return r;
  }

  fail(message) {
    clear(this.wrap);
    this.table = null;
    this.wrap.appendChild(h('div', { class: 'lp-missing' }, 'Hesap tablosu okunamadı: ' + message));
  }

  apply(ans) {
    if (!ans || this.dead) return;
    if (ans.unchanged) {
      this.gen = Math.max(this.gen || 0, ans.gen || 0);
      this.el.classList.remove('stale');
      return;
    }
    this.take(ans, true);
  }

  /** A sheet's answer on screen (``flash``: the numbers that moved flash, as the tables' do). */
  take(ans, flash) {
    if (this.dead || !ans || ans.unchanged) return;
    const before = this.data;
    this.data = this.entry = ans;
    this.gen = ans.gen || 0;
    this.rev = ans.rev;
    this.el.classList.remove('stale');
    const shape = !before || !this.table || before.rows !== ans.rows || before.cols !== ans.cols
      || JSON.stringify(before.widths || {}) !== JSON.stringify(ans.widths || {});
    if (shape && !this.edit) this.build();
    else if (shape) this.pending = true;          // (being typed into: drawn again when the typing ends)
    else this.paint(before, flash);
    this.hint.classList.toggle('hidden', Object.keys(ans.cells || {}).length > 0);
    this.dims.textContent = 'A1:' + cellName(ans.rows, ans.cols);
  }

  // ------------------------------------------------------------------ the grid
  width(c) {
    return ((this.data && this.data.widths) || {})[colName(c)] || DEFAULT_W;
  }

  build() {
    const d = this.data;
    this.pending = false;
    clear(this.wrap);
    const table = h('table', { class: 'calc-grid' });
    const cg = h('colgroup', null, h('col', { style: { width: RH_W + 'px' } }));
    this.cols = [];
    for (let c = 1; c <= d.cols; c++) {
      const col = h('col', { style: { width: this.width(c) + 'px' } });
      this.cols.push(col);
      cg.appendChild(col);
    }
    const head = h('tr', null, h('th', { class: 'corner', title: 'Tümünü seç (Ctrl+A)' }));
    for (let c = 1; c <= d.cols; c++) {
      const grip = h('span', { class: 'grip', title: 'Sürükleyerek sütunu genişletin / daraltın; çift tık: varsayılan genişlik' });
      grip.dataset.c = String(c);
      const th = h('th', { class: 'ch' }, colName(c), grip);
      th.dataset.c = String(c);
      head.appendChild(th);
    }
    const body = h('tbody');
    this.tds = [null];
    for (let r = 1; r <= d.rows; r++) {
      const rh = h('th', { class: 'rh' }, String(r));
      rh.dataset.r = String(r);
      const tr = h('tr', null, rh);
      const line = [null];
      for (let c = 1; c <= d.cols; c++) {
        const td = document.createElement('td');
        td.dataset.a = cellName(r, c);
        td.__rc = [r, c];
        tr.appendChild(td);
        line.push(td);
      }
      this.tds.push(line);
      body.appendChild(tr);
    }
    table.append(cg, h('thead', null, head), body);
    this.table = table;
    this.wrap.appendChild(table);
    this.fitTable();
    this.selTds = [];
    this.sel = { ar: clamp(this.sel.ar, 1, d.rows), ac: clamp(this.sel.ac, 1, d.cols), r: clamp(this.sel.r, 1, d.rows), c: clamp(this.sel.c, 1, d.cols) };
    this.paint(null, false);
  }

  fitTable() {
    if (!this.table) return;
    let w = RH_W;
    for (const col of this.cols) w += parseFloat(col.style.width) || DEFAULT_W;
    this.table.style.width = w + 'px';
  }

  td(r, c) {
    return (this.tds[r] && this.tds[r][c]) || null;
  }

  cellData(r, c) {
    return (this.data && this.data.cells && this.data.cells[cellName(r, c)]) || null;
  }

  paint(before, flash) {
    const d = this.data;
    if (!d || !this.table) return;
    const prev = (before && before.cells) || {};
    const moved = [];
    for (let r = 1; r <= d.rows; r++) {
      for (let c = 1; c <= d.cols; c++) {
        const td = this.td(r, c);
        if (!td) continue;
        const a = td.dataset.a;
        const cell = d.cells[a];
        const typed = this.typed.get(a);
        const sig = (typed ? 'typed\u0001' + typed.text + '\u0001' : '')
          + (cell ? [cell.t, cell.k, cell.c || '', cell.tip || '', cell.f || ''].join('\u0001') : '');
        if (td.__sig === sig) continue;
        td.__sig = sig;
        const editingHere = this.edit && this.edit.r === r && this.edit.c === c;
        if (!editingHere) td.textContent = typed ? typed.text : (cell ? cell.t : '');
        td.className = (cell ? 'k-' + (cell.k || 's') + (cell.f ? ' fx' : ' cst') + (cell.c ? ' c-' + cell.c : '') : '')
          + (editingHere && this.edit.where === 'cell' ? ' editing' : '');
        td.title = cell ? (cell.tip ? cell.t + ': ' + cell.tip : (cell.f || (cell.t && cell.t.length > 14 ? cell.t : ''))) : '';
        const p = prev[a];
        if (flash && cell && p && cell.k === 'n' && p.k === 'n' && typeof cell.v === 'number' && typeof p.v === 'number' && cell.v !== p.v) {
          moved.push([td, cell.v > p.v ? 'up' : 'down']);
        }
      }
    }
    if (moved.length && moved.length <= 60) {
      void this.wrap.offsetWidth;
      for (const [td, cls] of moved) td.classList.add(cls);
    }
    this.paintSel();
  }

  /** Every cell drawn again from the last answer (what was shown before it came - a refused change - goes). */
  repaint() {
    for (const line of this.tds) for (const td of line || []) if (td) td.__sig = null;
    this.paint(null, false);
  }

  // ------------------------------------------------------------------ the selection
  block() {
    const s = this.sel;
    return { top: Math.min(s.ar, s.r), left: Math.min(s.ac, s.c), bottom: Math.max(s.ar, s.r), right: Math.max(s.ac, s.c) };
  }

  select(ar, ac, r, c) {
    const d = this.data;
    const rows = d ? d.rows : MAX_ROWS, cols = d ? d.cols : MAX_COLS;
    this.sel = { ar: clamp(ar, 1, rows), ac: clamp(ac, 1, cols), r: clamp(r, 1, rows), c: clamp(c, 1, cols) };
    this.paintSel();
    setTimeout(() => this.status(), 0);         // (after the page's own tables let go of the status bar)
  }

  move(dr, dc, extend) {
    const s = this.sel;
    const r = s.r + dr, c = s.c + dc;
    if (extend) this.select(s.ar, s.ac, r, c); else this.select(r, c, r, c);
    const td = this.td(this.sel.r, this.sel.c);
    if (td && td.scrollIntoView) td.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }

  paintSel() {
    for (const td of this.selTds) td.classList.remove('sel', 'cur');
    const b = this.block();
    const single = b.top === b.bottom && b.left === b.right;
    const tds = [];
    for (let r = b.top; r <= b.bottom; r++) {
      for (let c = b.left; c <= b.right; c++) {
        const td = this.td(r, c);
        if (td) { if (!single) td.classList.add('sel'); tds.push(td); }
      }
    }
    const cur = this.td(this.sel.r, this.sel.c);
    if (cur) { cur.classList.add('cur'); tds.push(cur); }
    this.selTds = tds;
    this.addr.textContent = single ? cellName(b.top, b.left) : cellName(b.top, b.left) + ':' + cellName(b.bottom, b.right);
    if (!this.edit) this.fx.value = this.editText();
    const cell = this.cellData(this.sel.r, this.sel.c);
    const tip = cell && cell.tip ? cellName(this.sel.r, this.sel.c) + ' · ' + cell.t + ': ' + cell.tip : '';
    this.msg.textContent = tip;
    this.msg.classList.toggle('hidden', !tip);
  }

  /** The selection in the dashboard's status bar (when the sheet has the keyboard): its address, sum, average, count. */
  status() {
    const act = document.activeElement;
    if (this.dead || !(act === this.wrap || act === this.fx || (this.edit && act === this.edit.input))) return;
    const b = this.block();
    const addr = document.getElementById('sb-addr');
    const fx = document.getElementById('sb-fx');
    const stat = document.getElementById('sb-stat');
    if (!addr || !fx || !stat) return;
    addr.textContent = this.addr.textContent;
    fx.textContent = this.editText();
    let n = 0, sum = 0;
    for (let r = b.top; r <= b.bottom; r++) {
      for (let c = b.left; c <= b.right; c++) {
        const cell = this.cellData(r, c);
        if (cell && (cell.k === 'n') && typeof cell.v === 'number') { n += 1; sum += cell.v; }
      }
    }
    clear(stat);
    if (n > 1) stat.appendChild(h('span', null, 'Toplam ', h('b', null, num(sum, 4)), '  ·  Ortalama ', h('b', null, num(sum / n, 4)), '  ·  Adet ', h('b', null, String(n))));
  }

  /** What the formula bar shows of a cell (and what F2 edits): its formula, or its value as it is typed. */
  editText(r = this.sel.r, c = this.sel.c) {
    const typed = this.typed.get(cellName(r, c));
    if (typed) return typed.text;
    const cell = this.cellData(r, c);
    if (!cell) return '';
    if (cell.f !== undefined) return cell.f;
    if (cell.x !== undefined) return cell.x;
    return cell.t || '';
  }

  // ------------------------------------------------------------------ the mouse and the keyboard
  wire() {
    const w = this.wrap;
    w.addEventListener('mousedown', (e) => this.onDown(e));
    w.addEventListener('mouseover', (e) => this.onOver(e));
    w.addEventListener('dblclick', (e) => this.onDbl(e));
    w.addEventListener('keydown', (e) => this.onKey(e));
    w.addEventListener('copy', (e) => this.onCopy(e));
    w.addEventListener('paste', (e) => this.onPaste(e));
    w.addEventListener('focus', () => this.status());
    this.fx.addEventListener('focus', () => {
      if (!this.data) return;
      if (!this.edit) this.beginEdit(this.editText(), 'edit', 'bar');
      else if (this.edit.where === 'cell') this.toBar();
    });
    this.fx.addEventListener('keydown', (e) => this.onEditKey(e));
    this.fx.addEventListener('input', () => this.onInput());
    this.fx.addEventListener('blur', (e) => this.onBlur(e));
  }

  cellAt(target) {
    const td = target && target.closest ? target.closest('td') : null;
    return td && td.__rc && this.wrap.contains(td) ? td.__rc : null;
  }

  onDown(e) {
    if (e.button !== 0 || !this.data) return;
    const grip = e.target.closest && e.target.closest('.grip');
    if (grip) {
      e.preventDefault();
      e.stopPropagation();
      const c = Number(grip.dataset.c);
      resizing = { box: this, c, x0: e.clientX, w0: this.width(c), col: this.cols[c - 1], w: 0 };
      return;
    }
    const th = e.target.closest && e.target.closest('th');
    if (th && !this.edit) {                      // a row's / a column's header, the corner: the whole of it
      e.preventDefault();
      const d = this.data;
      if (th.dataset.r) this.select(Number(th.dataset.r), 1, Number(th.dataset.r), d.cols);
      else if (th.dataset.c) this.select(1, Number(th.dataset.c), d.rows, Number(th.dataset.c));
      else this.select(1, 1, d.rows, d.cols);
      this.wrap.focus({ preventScroll: true });
      return;
    }
    const at = this.cellAt(e.target);
    if (!at) return;
    const [r, c] = at;
    const ed = this.edit;
    if (ed) {
      if (ed.where === 'cell' && ed.r === r && ed.c === c) return;          // (inside its own editor: the caret moves)
      if (isFormula(ed.input.value) && (e.ctrlKey || e.metaKey || ed.point || this.canPoint())) {
        e.preventDefault();                                                   // (the typing goes on: a reference goes in)
        this.pointAt(r, c);
        this.drag = { point: true, r, c };
        return;
      }
      this.commit(0, 0, false, false);
    }
    e.preventDefault();
    if (e.shiftKey) this.select(this.sel.ar, this.sel.ac, r, c); else this.select(r, c, r, c);
    this.drag = { r, c };
    this.wrap.focus({ preventScroll: true });
  }

  onOver(e) {
    if (!this.drag) return;
    const at = this.cellAt(e.target);
    if (!at) return;
    if (this.drag.point) { if (this.edit) this.pointAt(this.drag.r, this.drag.c, at[0], at[1]); return; }
    if (at[0] !== this.sel.r || at[1] !== this.sel.c) this.select(this.sel.ar, this.sel.ac, at[0], at[1]);
  }

  onDbl(e) {
    if (e.target.closest && e.target.closest('.grip')) {
      const c = Number(e.target.closest('.grip').dataset.c);
      this.save({ widths: { [colName(c)]: null } });
      return;
    }
    const at = this.cellAt(e.target);
    if (!at || this.edit) return;
    this.select(at[0], at[1], at[0], at[1]);
    this.beginEdit(this.editText(), 'edit', 'cell');
  }

  onKey(e) {
    if (this.edit || !this.data || e.target !== this.wrap) return;
    const k = e.key;
    const mod = e.ctrlKey || e.metaKey;
    const d = this.data;
    const stop = () => { e.preventDefault(); e.stopPropagation(); };
    if (e.altKey) return;                                    // (Alt+← / Alt+→ / Alt+Y: the shell's)
    if (mod) {
      const l = k.toLowerCase();
      if (l === 'c') { this.fullCopy = e.shiftKey; e.stopPropagation(); return; }           // (the copy event follows)
      if (l === 'v') { e.stopPropagation(); return; }                                       // (the paste event follows)
      if (l === 'a') { stop(); this.select(1, 1, d.rows, d.cols); return; }
      if (l === 'd') { stop(); this.fill(true); return; }
      if (l === 'r') { stop(); this.fill(false); return; }
      const jump = { ArrowUp: [1, null], ArrowDown: [d.rows, null], ArrowLeft: [null, 1], ArrowRight: [null, d.cols] }[k];
      if (jump) {
        stop();
        const r = jump[0] === null ? this.sel.r : jump[0], c = jump[1] === null ? this.sel.c : jump[1];
        if (e.shiftKey) this.select(this.sel.ar, this.sel.ac, r, c); else this.select(r, c, r, c);
      }
      return;
    }
    switch (k) {
      case 'ArrowUp': stop(); this.move(-1, 0, e.shiftKey); return;
      case 'ArrowDown': stop(); this.move(1, 0, e.shiftKey); return;
      case 'ArrowLeft': stop(); this.move(0, -1, e.shiftKey); return;
      case 'ArrowRight': stop(); this.move(0, 1, e.shiftKey); return;
      case 'Tab': stop(); this.move(0, e.shiftKey ? -1 : 1, false); return;
      case 'Enter': case 'F2': stop(); this.beginEdit(this.editText(), 'edit', 'cell'); return;
      case 'Delete': stop(); this.clearCells(); return;
      case 'Backspace': stop(); this.beginEdit('', 'enter', 'cell'); return;
      case 'Escape': return;
      default: break;
    }
    if (k.length === 1) { stop(); this.beginEdit(k, 'enter', 'cell'); }
  }

  // ------------------------------------------------------------------ typing into a cell
  beginEdit(text, mode, where) {
    if (this.edit || !this.data) return;
    const { r, c } = this.sel;
    this.select(r, c, r, c);
    const td = this.td(r, c);
    if (!td) return;
    let input = this.fx;
    if (where === 'cell') {
      input = h('input', { class: 'calc-edit', type: 'text', spellcheck: 'false', autocomplete: 'off' });
      input.addEventListener('keydown', (e) => this.onEditKey(e));
      input.addEventListener('input', () => this.onInput());
      input.addEventListener('blur', (e) => this.onBlur(e));
      input.addEventListener('copy', (e) => e.stopPropagation());
      input.addEventListener('paste', (e) => e.stopPropagation());
      this.wrap.appendChild(input);
      td.classList.add('editing');
    }
    this.edit = { r, c, input, where, mode, orig: this.editText(r, c), point: null };
    editingBox = this;
    input.value = text;
    this.fx.value = text;
    if (where === 'cell') {
      this.place();
      input.focus({ preventScroll: true });
      input.setSelectionRange(text.length, text.length);
    }
    this.mirror();
  }

  /** The editor over its cell, as wide as what is typed needs (up to the sheet's width). */
  place() {
    const ed = this.edit;
    if (!ed || ed.where !== 'cell') return;
    const td = this.td(ed.r, ed.c);
    if (!td) return;
    const wr = this.wrap.getBoundingClientRect(), tr = td.getBoundingClientRect();
    const left = tr.left - wr.left + this.wrap.scrollLeft;
    ed.input.style.left = left + 'px';
    ed.input.style.top = (tr.top - wr.top + this.wrap.scrollTop) + 'px';
    ed.input.style.height = tr.height + 'px';
    const want = Math.max(tr.width, ed.input.value.length * 7.3 + 20);
    ed.input.style.width = Math.max(tr.width, Math.min(want, this.wrap.scrollWidth - left)) + 'px';
  }

  /** The cell and the formula bar show the same text while it is typed. */
  mirror() {
    const ed = this.edit;
    if (!ed) return;
    if (ed.where === 'cell') { this.fx.value = ed.input.value; this.place(); } else {
      const td = this.td(ed.r, ed.c);
      if (td) td.textContent = ed.input.value;
    }
  }

  /** Typing goes on in the formula bar (clicked while the cell was typed into). */
  toBar() {
    const ed = this.edit;
    const text = ed.input.value;
    const td = this.td(ed.r, ed.c);
    if (ed.input !== this.fx) ed.input.remove();
    if (td) { td.classList.remove('editing'); td.textContent = text; }
    ed.input = this.fx;
    ed.where = 'bar';
    ed.point = null;
    this.fx.value = text;
  }

  onInput() {
    if (!this.edit) return;
    this.edit.point = null;
    this.markPoint();
    this.mirror();
  }

  onBlur(e) {
    const ed = this.edit;
    if (!ed || e.target !== ed.input) return;
    const to = e.relatedTarget;
    if (to === this.fx || (to && to.classList && to.classList.contains('calc-edit') && this.wrap.contains(to))) return;
    this.commit(0, 0, false, false);
  }

  onEditKey(e) {
    const ed = this.edit;
    if (!ed || e.target !== ed.input) { e.stopPropagation(); return; }
    const k = e.key;
    if (k === 'Enter') { e.preventDefault(); this.commit(e.shiftKey ? -1 : 1, 0, !e.shiftKey, true); }
    else if (k === 'Tab') { e.preventDefault(); this.commit(0, e.shiftKey ? -1 : 1, false, true); }
    else if (k === 'Escape') { e.preventDefault(); this.cancel(); }
    else if (k === 'F2') { e.preventDefault(); ed.mode = ed.mode === 'enter' ? 'edit' : 'enter'; }
    else if (k.startsWith('Arrow') && ed.where === 'cell' && ed.mode === 'enter' && !e.ctrlKey && !e.metaKey) {
      const dir = { ArrowUp: [-1, 0], ArrowDown: [1, 0], ArrowLeft: [0, -1], ArrowRight: [0, 1] }[k];
      if (isFormula(ed.input.value)) {
        if (ed.point || this.canPoint()) {          // (a formula: the arrows walk a reference into it, as in Excel)
          e.preventDefault();
          const at = ed.point && ed.point.at ? ed.point.at : [ed.r, ed.c];
          this.pointAt(clamp(at[0] + dir[0], 1, this.data.rows), clamp(at[1] + dir[1], 1, this.data.cols));
        }
      } else {
        e.preventDefault();
        this.commit(dir[0], dir[1], false, true);
      }
    }
    e.stopPropagation();
  }

  /** Whether the caret stands where a reference may go (after =, an operator, a bracket or a separator). */
  canPoint() {
    const inp = this.edit.input;
    const before = inp.value.slice(0, inp.selectionStart).replace(/\s+$/, '');
    return before.startsWith('=') && /[=(,;+\-*/^&<>:]$/.test(before);
  }

  /** A cell (a block, dragged over) of this sheet goes into the formula at the caret - in place of the one put just before. */
  pointAt(r1, c1, r2 = r1, c2 = c1) {
    const ref = r1 === r2 && c1 === c2 ? cellName(r1, c1)
      : cellName(Math.min(r1, r2), Math.min(c1, c2)) + ':' + cellName(Math.max(r1, r2), Math.max(c1, c2));
    this.splice(ref, { at: [r2, c2], cells: [r1, c1, r2, c2] });
  }

  /** A workbook cell's reference (Ctrl+click on a table) goes into the formula at the caret. */
  insertRef(text) {
    if (!this.edit) return;
    this.splice(text, { at: null, cells: null });
  }

  splice(text, info) {
    const ed = this.edit;
    const inp = ed.input;
    const start = ed.point ? ed.point.start : inp.selectionStart;
    const end = ed.point ? ed.point.end : inp.selectionEnd;
    inp.value = inp.value.slice(0, start) + text + inp.value.slice(end);
    ed.point = Object.assign({ start, end: start + text.length }, info);
    inp.focus({ preventScroll: true });
    inp.setSelectionRange(start + text.length, start + text.length);
    this.mirror();
    this.markPoint();
  }

  markPoint() {
    for (const td of this.wrap.querySelectorAll('td.pt')) td.classList.remove('pt');
    const p = this.edit && this.edit.point;
    if (!p || !p.cells) return;
    const [r1, c1, r2, c2] = p.cells;
    for (let r = Math.min(r1, r2); r <= Math.max(r1, r2); r++) {
      for (let c = Math.min(c1, c2); c <= Math.max(c1, c2); c++) { const td = this.td(r, c); if (td) td.classList.add('pt'); }
    }
  }

  endEdit() {
    const ed = this.edit;
    if (!ed) return null;
    this.edit = null;
    if (editingBox === this) editingBox = null;
    for (const td of this.wrap.querySelectorAll('td.pt')) td.classList.remove('pt');
    if (ed.where === 'cell') ed.input.remove();
    const td = this.td(ed.r, ed.c);
    if (td) {
      td.classList.remove('editing');
      const cell = this.cellData(ed.r, ed.c);
      const typed = this.typed.get(cellName(ed.r, ed.c));
      td.textContent = typed ? typed.text : (cell ? cell.t : '');
    }
    if (document.activeElement === this.fx) this.fx.blur();
    if (this.pending) this.build(); else this.fx.value = this.editText();
    return ed;
  }

  cancel() {
    this.endEdit();
    this.wrap.focus({ preventScroll: true });
  }

  /** What was typed goes to the server (``dr`` / ``dc``: where the selection goes then; ``grow``: Enter on the last row
   *  adds a row, as the sheet seemed to go on).  Refused (a Bloomberg function, a formula that cannot be read): said, and
   *  the cell is typed into again with the same text. */
  async commit(dr, dc, grow, refocus) {
    if (!this.edit) return;
    const text = this.edit.input.value;                    // (before the bar shows the cell again)
    const ed = this.endEdit();
    const d = this.data;
    const change = { cells: { [cellName(ed.r, ed.c)]: text } };
    const more = grow && dr > 0 && ed.r >= d.rows && d.rows < MAX_ROWS;
    if (more) change.rows = d.rows + 1;
    if (refocus) this.wrap.focus({ preventScroll: true });
    if (text === ed.orig && !more) { if (dr || dc) this.move(dr, dc, false); return; }
    const a = cellName(ed.r, ed.c);
    const tok = {};
    this.typed.set(a, { text, tok });                      // (shown - and edited by F2 - until the answer comes)
    const td = this.td(ed.r, ed.c);
    if (td) { td.textContent = text; td.__sig = null; }
    if ((dr || dc) && !more) this.move(dr, dc, false);
    const ok = await this.save(change, () => { const t = this.typed.get(a); if (t && t.tok === tok) this.typed.delete(a); });
    if (this.dead) return;
    if (!ok) {
      this.select(ed.r, ed.c, ed.r, ed.c);
      this.beginEdit(text, 'edit', 'cell');
    } else if (more) {
      this.move(dr, dc, false);
    }
  }

  /** A change of the sheet saved; its answer (the sheet evaluated) shown in every box of it.  False: refused.
   *  ``settle``: called as the answer comes, before it is shown (what was typed gives way to it). */
  async save(change, settle) {
    let ans;
    try {
      ans = await api.post('/api/calc/save', Object.assign({ sheet: this.item.sheet }, change));
    } catch (err) {
      if (settle) settle();
      if (err.status !== 401) toast(err.message, 'err', 9000);
      if (!this.dead && this.data && this.table) this.repaint();
      return false;
    }
    if (settle) settle();
    changedHere(this.item.sheet, ans);
    return true;
  }

  clearCells() {
    const b = this.block();
    const cells = {};
    for (let r = b.top; r <= b.bottom; r++) for (let c = b.left; c <= b.right; c++) if (this.cellData(r, c)) cells[cellName(r, c)] = '';
    if (Object.keys(cells).length) this.save({ cells });
  }

  /** Ctrl+D / Ctrl+R: the first row (column) of the selection - or the one above (left of) a single row - over the rest. */
  fill(down) {
    const b = this.block();
    let from, to;
    if (down) {
      if (b.top === b.bottom) { if (b.top < 2) return; from = [b.top - 1, b.left, b.top - 1, b.right]; to = [b.top, b.left, b.bottom, b.right]; }
      else { from = [b.top, b.left, b.top, b.right]; to = [b.top + 1, b.left, b.bottom, b.right]; }
    } else if (b.left === b.right) {
      if (b.left < 2) return;
      from = [b.top, b.left - 1, b.bottom, b.left - 1]; to = [b.top, b.left, b.bottom, b.right];
    } else {
      from = [b.top, b.left, b.bottom, b.left]; to = [b.top, b.left + 1, b.bottom, b.right];
    }
    const rng = (x) => cellName(x[0], x[1]) + ':' + cellName(x[2], x[3]);
    this.save({ copy: { sheet: this.item.sheet, from: rng(from), to: rng(to) } });
  }

  // ------------------------------------------------------------------ the clipboard
  onCopy(e) {
    if (this.edit || !this.data) return;
    const b = this.block();
    const full = !!this.fullCopy;
    this.fullCopy = false;
    const lines = [];
    for (let r = b.top; r <= b.bottom; r++) {
      const parts = [];
      for (let c = b.left; c <= b.right; c++) {
        const cell = this.cellData(r, c);
        let t = cell ? cell.t || '' : '';
        if (full && cell && cell.k === 'n' && typeof cell.v === 'number') t = raw(cell.v);
        parts.push(String(t).replace(/[\t\r\n]+/g, ' '));
      }
      lines.push(parts.join('\t'));
    }
    const text = lines.join('\r\n');
    e.clipboardData.setData('text/plain', text);
    e.preventDefault();
    e.stopPropagation();
    clip = { sheet: this.item.sheet, from: cellName(b.top, b.left) + ':' + cellName(b.bottom, b.right), text: normalise(text) };
    const n = (b.bottom - b.top + 1) * (b.right - b.left + 1);
    toast(n === 1 ? 'Hücre kopyalandı' : (b.bottom - b.top + 1) + ' × ' + (b.right - b.left + 1) + ' hücre kopyalandı - Excel\'e yapıştırabilirsiniz', 'ok', 1800);
  }

  onPaste(e) {
    if (this.edit || !this.data) return;
    const text = (e.clipboardData || window.clipboardData).getData('text/plain');
    if (!text) return;
    e.preventDefault();
    e.stopPropagation();
    const b = this.block();
    const to = cellName(b.top, b.left) + ':' + cellName(b.bottom, b.right);
    if (clip && normalise(text) === clip.text) {
      this.save({ copy: { sheet: clip.sheet, from: clip.from, to } });   // (from a calc sheet: the formulas move along)
      return;
    }
    const matrix = normalise(text).split('\n').map((line) => line.split('\t'));
    const cells = {};
    if (matrix.length === 1 && matrix[0].length === 1 && (b.bottom > b.top || b.right > b.left)) {
      for (let r = b.top; r <= b.bottom; r++) for (let c = b.left; c <= b.right; c++) cells[cellName(r, c)] = matrix[0][0];
    } else {
      const width = Math.max(...matrix.map((row) => row.length));
      if (b.top + matrix.length - 1 > MAX_ROWS || b.left + width - 1 > MAX_COLS) {
        toast('Yapıştırılan blok hesap tablosuna sığmıyor (en fazla ' + MAX_ROWS + ' satır × ' + MAX_COLS + ' sütun)', 'err', 6000);
        return;
      }
      matrix.forEach((row, i) => row.forEach((v, j) => { cells[cellName(b.top + i, b.left + j)] = v; }));
      this.select(b.top, b.left, b.top + matrix.length - 1, b.left + width - 1);
    }
    this.save({ cells }).then((ok) => { if (ok) toast(Object.keys(cells).length + ' hücre yapıştırıldı', 'ok', 1800); });
  }

  // ------------------------------------------------------------------ number formats, size
  toolbar() {
    const bar = h('div', { class: 'calc-tools' });
    const btn = (label, title, fn, act) => {
      const b = h('button', { class: 'iconbtn', type: 'button', title }, label);
      b.dataset.act = act;
      b.addEventListener('mousedown', (e) => e.preventDefault());          // (the sheet keeps the keyboard)
      b.addEventListener('click', (e) => { if (this.data) fn(e); });
      bar.appendChild(b);
      return b;
    };
    btn('Biçim ▾', 'Sayı biçimi: genel, ondalık, binlik ayracı, yüzde, tarih', (e) => this.formatMenu(e.currentTarget), 'fmt');
    btn('%', 'Yüzde (aç / kapa)', () => this.toggleFmt('p'), 'pct');
    btn('000', 'Binlik ayracı (aç / kapa)', () => this.toggleFmt('t'), 'thou');
    btn('+,0', 'Ondalık artır', () => this.decimals(1), 'dec-up');
    btn('−,0', 'Ondalık azalt', () => this.decimals(-1), 'dec-down');
    bar.appendChild(h('span', { class: 'calc-sep' }));
    btn('+ Satır', 'Bir satır ekle (en fazla ' + MAX_ROWS + ')', () => this.resize(1, 0), 'add-row');
    btn('+ Sütun', 'Bir sütun ekle (en fazla ' + MAX_COLS + ')', () => this.resize(0, 1), 'add-col');
    bar.appendChild(h('span', { class: 'grow' }));
    bar.appendChild(h('span', { class: 'calc-help', title: HELP }, '?'));
    return bar;
  }

  /** The active cell's number format, its own or the one it takes from what it refers to. */
  activeFmt() {
    const a = cellName(this.sel.r, this.sel.c);
    const cell = this.cellData(this.sel.r, this.sel.c);
    return (this.data.fmt || {})[a] || (cell && cell.fm) || '';
  }

  setFmt(code) {
    const b = this.block();
    const fmt = {};
    for (let r = b.top; r <= b.bottom; r++) for (let c = b.left; c <= b.right; c++) fmt[cellName(r, c)] = code;
    this.save({ fmt });
  }

  formatMenu(anchor) {
    const cur = (this.data.fmt || {})[cellName(this.sel.r, this.sel.c)] || '';
    const mark = (code) => (cur === code ? '✓ ' : '    ');
    const r = anchor.getBoundingClientRect();
    menu(r.left, r.bottom + 4, [
      { header: 'Sayı biçimi' },
      { label: mark('') + 'Genel', action: () => this.setFmt('') },
      { label: mark('0') + 'Tam sayı (1234)', action: () => this.setFmt('0') },
      { label: mark('0.00') + 'Ondalık (1234,56)', action: () => this.setFmt('0.00') },
      { label: mark('#,##0') + 'Binlik ayraçlı (1.234)', action: () => this.setFmt('#,##0') },
      { label: mark('#,##0.00') + 'Binlik ayraçlı ondalık (1.234,56)', action: () => this.setFmt('#,##0.00') },
      { label: mark('0.00%') + 'Yüzde (%12,34)', action: () => this.setFmt('0.00%') },
      { label: mark(DATE_FMT) + 'Tarih (gg.aa.yyyy)', action: () => this.setFmt(DATE_FMT) },
      { label: mark(DATE_FMT + ' hh:mm') + 'Tarih ve saat', action: () => this.setFmt(DATE_FMT + ' hh:mm') },
    ]);
  }

  toggleFmt(which) {
    const cell = this.cellData(this.sel.r, this.sel.c);
    const p = fmtParts(this.activeFmt(), cell ? cell.t : '');
    if (p.kind === 'date') p.kind = 'num';
    if (which === 'p') { p.p = !p.p; if (p.p && p.kind === 'gen') p.d = 0; } else p.t = !p.t;
    this.setFmt(fmtCode(p));
  }

  decimals(step) {
    const cell = this.cellData(this.sel.r, this.sel.c);
    const p = fmtParts(this.activeFmt(), cell ? cell.t : '');
    if (p.kind === 'date') return;
    p.d = clamp(p.d + step, 0, 10);
    this.setFmt(fmtCode(p));
  }

  resize(dr, dc) {
    const d = this.data;
    if (d.rows + dr > MAX_ROWS || d.cols + dc > MAX_COLS) {
      toast('Hesap tablosu en fazla ' + MAX_ROWS + ' satır × ' + MAX_COLS + ' sütun olabilir', 'err');
      return;
    }
    this.save(dr ? { rows: d.rows + dr } : { cols: d.cols + dc });
  }

  /** The sheet cut to its last filled row and column (at least one each). */
  trim() {
    const d = this.data;
    let rows = 1, cols = 1;
    for (const a of Object.keys(d.cells || {})) {
      const m = /^([A-Z]+)(\d+)$/.exec(a);
      if (m) { rows = Math.max(rows, Number(m[2])); cols = Math.max(cols, colIndex(m[1])); }
    }
    this.save({ rows, cols });
  }

  // ------------------------------------------------------------------ the box
  setCollapsed(on) {
    if (this.opts.edit) this.opts.edit({ collapsed: !!on });
    else this.show(Object.assign({}, this.item, { collapsed: !!on }));
    if (!on) ask(this);
  }

  menuItems() {
    const it = this.item;
    const o = this.opts;
    const mark = (on) => (on ? '✓ ' : '    ');
    const items = [];
    if (o.edit && o.place === 'launchpad') {
      items.push({ header: 'Genişlik' });
      for (const [w, label] of WIDTHS) items.push({ label: mark(it.w === w) + label, action: () => o.edit({ w }) });
    }
    if (o.edit) {
      items.push({ header: 'Yükseklik' });
      items.push({ label: mark(it.h === 'auto') + 'Otomatik (tablo kadar)', action: () => o.edit({ h: 'auto' }) });
      for (const px of [240, 360, 480, 640]) items.push({ label: mark(it.h === px) + px + ' px – içinde kaydırılır', action: () => o.edit({ h: px }) });
      items.push({ sep: true });
      items.push({ label: 'Yeniden adlandır…', action: () => this.rename() });
      if (o.move) {
        const vertical = o.place === 'drawer';
        items.push({ label: vertical ? 'Yukarı taşı' : 'Sola taşı', action: () => o.move(-1) });
        items.push({ label: vertical ? 'Aşağı taşı' : 'Sağa taşı', action: () => o.move(1) });
      }
    }
    items.push({ sep: true });
    items.push({ label: 'Satır ekle', action: () => this.resize(1, 0) });
    items.push({ label: 'Sütun ekle', action: () => this.resize(0, 1) });
    items.push({ label: 'Boş son satır ve sütunları kaldır', action: () => this.trim() });
    items.push({ sep: true });
    if (o.place !== 'drawer') items.push({ label: 'Yan panele sabitle', action: () => this.pin() });
    if (o.place === 'drawer') items.push({ label: 'Launchpad\'e ekle…', action: () => this.toLaunchpad() });
    if (o.place !== 'pop') items.push({ label: 'Ayrı pencerede aç', action: () => this.popOut() });
    if (o.remove) {
      items.push({ sep: true });
      items.push({ label: o.place === 'drawer' ? 'Yan panelden kaldır' : 'Launchpad\'den kaldır', action: () => o.remove() });
    }
    return items;
  }

  async rename() {
    const v = await promptDialog('Yeniden adlandır', 'Bu hesap tablosunun adı', this.item.title || 'Hesap tablosu');
    if (v === null) return;
    this.opts.edit({ title: v });
  }

  /** The same sheet beside every page (the side drawer): one sheet, two places - a change shows in both. */
  pin() {
    const opened = () => { if (!document.getElementById('app').classList.contains('drawer-open')) document.getElementById('btn-drawer').click(); };
    if (drawerItems().some((x) => x.type === 'calc' && x.sheet === this.item.sheet)) { toast('Bu hesap tablosu zaten yan panelde', '', 2400); opened(); return; }
    if (drawerItems().length >= 24) { toast('Yan panel en fazla 24 öğe alır', 'err'); return; }
    const it = { type: 'calc', id: newId(), sheet: this.item.sheet, w: 12, h: 'auto' };
    if (this.item.title) it.title = this.item.title;
    saveLayout({ drawer: drawerItems().concat([it]) }).then(opened, () => {});
  }

  /** From the drawer onto a launchpad: the same sheet. */
  toLaunchpad() {
    const r = this.el.getBoundingClientRect();
    const add = (name) => {
      const it = { type: 'calc', id: newId(), sheet: this.item.sheet, w: 6, h: 'auto' };
      if (this.item.title) it.title = this.item.title;
      if (!name) { createLaunchpad([it]); return; }
      changeLaunchpad(name, (lp) => { if (lp.items.length < 60) lp.items.push(it); });
      toast('Hesap tablosu "' + name + '" launchpad\'ine eklendi', 'ok', 2600);
    };
    menu(r.left + 20, r.top + 30, [{ header: 'Launchpad\'e ekle' }]
      .concat(launchpads().map((lp) => ({ label: lp.name, action: () => add(lp.name) })), [{ label: '+ Yeni launchpad…', action: () => add(null) }]));
  }

  popOut() {
    const q = this.item.title ? '?t=' + encodeURIComponent(this.item.title) : '';
    const w = window.open('/#/pop/calc/' + encodeURIComponent(this.item.sheet) + q, 'tto-pop-calc-' + this.item.sheet, 'popup=yes,width=980,height=680');
    if (!w) toast('Tarayıcı ayrı pencereyi engelledi: bu adres için açılır pencerelere izin verin', 'err', 7000);
    else w.focus();
  }

  setAdhoc() {}

  findCell() {
    return null;
  }

  destroy() {
    if (this.edit) this.endEdit();
    this.dead = true;
    this.leave(this.item.sheet);
    if (CalcBox.hub) CalcBox.hub.remove(this);
  }
}

/** Set by boxes.js (which registers this kind of box): the boxes on screen are brought up to date together. */
CalcBox.hub = null;
