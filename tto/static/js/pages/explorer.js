// Sayfa gezgini: any rectangle of any sheet of either workbook, with formulas in the status bar.
import { api } from '../api.js';
import { h, clear, errorToast } from '../ui.js';
import { Grid, copyGrid } from '../grid.js';

const ROWS = 60;

function colIndex(label) {
  let n = 0;
  for (const ch of label.toUpperCase()) n = n * 26 + (ch.charCodeAt(0) - 64);
  return n;
}

function colLabel(n) {
  let s = '';
  while (n > 0) { const r = (n - 1) % 26; s = String.fromCharCode(65 + r) + s; n = Math.floor((n - 1) / 26); }
  return s;
}

export class ExplorerPage {
  constructor(host, ctx) {
    this.host = host;
    this.ctx = ctx;
    this.dead = false;
    this.book = 'tto';
    this.sheet = null;
    this.range = 'A1:Z' + ROWS;
    this.grid = null;
    this.adhoc = false;
    this.books = {};
    // another page may ask for a particular sheet ("show me the whole sheet")
    try {
      const want = JSON.parse(sessionStorage.getItem('tto.explorer') || 'null');
      sessionStorage.removeItem('tto.explorer');
      if (want && want.book && want.sheet) { this.book = want.book; this.sheet = want.sheet; if (want.range) this.range = want.range; }
    } catch (e) { /* storage unavailable */ }
  }

  async load() {
    clear(this.host);
    const status = await api.get('/api/status');
    this.books = status.books || {};
    if (!this.books[this.book]) this.book = Object.keys(this.books)[0];
    this.bookSel = h('select', { class: 'inp' });
    for (const id of Object.keys(this.books)) this.bookSel.appendChild(h('option', { value: id }, this.books[id].title || id));
    this.bookSel.value = this.book;
    this.sheetSel = h('select', { class: 'inp' });
    this.rangeInp = h('input', { class: 'inp', type: 'text', value: this.range, style: { width: '130px' }, spellcheck: 'false' });
    this.info = h('span', { class: 'muted' });
    const go = h('button', { class: 'btn sm primary', type: 'button' }, 'Git');
    const up = h('button', { class: 'btn sm', type: 'button', title: 'Önceki satırlar' }, '▲');
    const down = h('button', { class: 'btn sm', type: 'button', title: 'Sonraki satırlar' }, '▼');
    const left = h('button', { class: 'btn sm', type: 'button', title: 'Önceki sütunlar' }, '◀');
    const right = h('button', { class: 'btn sm', type: 'button', title: 'Sonraki sütunlar' }, '▶');
    const copy = h('button', { class: 'btn sm', type: 'button' }, 'Kopyala');
    const what = h('button', { class: 'btn sm', type: 'button', title: 'Açıkken her hücreye kişisel bir değer yazabilirsiniz (yalnızca sizin görünümünüz değişir)' }, 'Ne-olursa modu');
    this.bookSel.addEventListener('change', () => { this.book = this.bookSel.value; this.sheet = null; this.range = 'A1:Z' + ROWS; this.loadSheets().catch(errorToast); });
    this.sheetSel.addEventListener('change', () => { this.sheet = this.sheetSel.value; this.range = 'A1:Z' + ROWS; this.show().catch(errorToast); });
    go.addEventListener('click', () => { this.range = this.rangeInp.value.trim().toUpperCase(); this.show().catch(errorToast); });
    this.rangeInp.addEventListener('keydown', (e) => { if (e.key === 'Enter') go.click(); });
    up.addEventListener('click', () => this.shift(-ROWS, 0));
    down.addEventListener('click', () => this.shift(ROWS, 0));
    left.addEventListener('click', () => this.shift(0, -20));
    right.addEventListener('click', () => this.shift(0, 20));
    copy.addEventListener('click', () => { if (this.grid) copyGrid(this.grid); });
    what.addEventListener('click', () => {
      this.adhoc = !this.adhoc;
      what.classList.toggle('on', this.adhoc);
      if (this.grid) this.grid.opts.adhoc = this.adhoc;
    });
    this.host.appendChild(h('div', { class: 'page-tools' }, this.bookSel, this.sheetSel, this.rangeInp, go, up, down, left, right, copy, what,
      h('span', { class: 'grow' }), this.info));
    this.body = h('div', { class: 'body' });
    this.host.appendChild(h('section', { class: 'panel wide' }, this.body));
    await this.loadSheets();
  }

  async loadSheets() {
    const res = await api.get('/api/sheets', { book: this.book });
    if (this.dead) return;
    clear(this.sheetSel);
    for (const s of res.sheets) this.sheetSel.appendChild(h('option', { value: s.name }, s.name + '  (' + s.formulas + ' formül)'));
    if (!this.sheet || !res.sheets.some((s) => s.name === this.sheet)) this.sheet = res.sheets[0].name;
    this.sheetSel.value = this.sheet;
    await this.show();
  }

  shift(dr, dc) {
    const m = /^([A-Z]+)(\d+):([A-Z]+)(\d+)$/.exec(this.range);
    if (!m) return;
    let c1 = colIndex(m[1]), r1 = Number(m[2]), c2 = colIndex(m[3]), r2 = Number(m[4]);
    const h1 = r2 - r1, w1 = c2 - c1;
    r1 = Math.max(1, r1 + dr);
    c1 = Math.max(1, c1 + dc);
    this.range = colLabel(c1) + r1 + ':' + colLabel(c1 + w1) + (r1 + h1);
    this.show().catch(errorToast);
  }

  async fetch() {
    return api.get('/api/grid', { book: this.book, sheet: this.sheet, range: this.range });
  }

  async show() {
    this.rangeInp.value = this.range;
    const res = await this.fetch();
    if (this.dead) return;
    clear(this.body);
    this.grid = new Grid({ book: this.book, data: res.data, axis: true, header: false, editable: true, adhoc: this.adhoc });
    this.body.appendChild(this.grid.el);
    this.info.textContent = this.sheet + ' · ' + res.dims[0] + ' satır × ' + res.dims[1] + ' sütun';
  }

  async refresh() {
    if (!this.grid) return;
    const res = await this.fetch();
    if (this.dead) return;
    this.grid.update(res.data, true);
  }

  destroy() {
    this.dead = true;
  }
}
