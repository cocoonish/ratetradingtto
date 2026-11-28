// A box of one of the dashboard's own pages - Sinyaller's live list, VİOP's order levels and contracts, Broker Chat's
// board, an İzleme list, TCMB WIRP's meeting table, FX's pair summary - on a launchpad, in the side drawer, in a window
// of its own.  Each reads a light part of its page with a request of its own and keeps up by itself: a quant box when
// the quant results' version moves (the live stream's quant counters, a window of its own included), the board when
// Broker Chat changes (the stream's count of its changes - not with every generation of the market), the watch list
// with the generation.  This is the frame (a table box's: ⠿, the title, where it comes from, ⋯, ▾ - boxes.js); the kinds and
// what each draws are in pageboxes.js.  On its own page a box's panel has a table's controls (``boxTools``).
import { api } from './api.js';
import { h, clear, menu, promptDialog, toast, waiting } from './ui.js';
import { Grid, copyGrid } from './grid.js';
import { hub, changed, makeBox } from './boxes.js';
import { WIDTHS, DEFAULT_W, addButton } from './layout.js';

/** What the live stream says besides the generation, as the boxes follow it: ``quant`` the quant results' version,
 *  ``chat`` the count of Broker Chat's changes (a line kept or removed, the board reset ...). */
export const stream = { quant: null, chat: null };

/** Which field of an answer says what a box shows of each: the version / the count it was read at. */
const READ_AT = { quant: 'version', chat: 'changes' };

/** The live stream's counters (main.js hands every message here, in a window of its own as well): the boxes that follow
 *  one that moved ask again at once. */
export function boxEvent(msg) {
  if (!msg) return;
  const now = { quant: msg.quant && typeof msg.quant.version === 'number' ? msg.quant.version : null,
    chat: typeof msg.broker === 'number' ? msg.broker : null };
  const moved = Object.keys(now).filter((k) => now[k] !== null && now[k] !== stream[k]);
  for (const k of moved) stream[k] = now[k];
  if (!moved.length || document.hidden) return;        // (a tab out of view catches up when it is looked at: they differ then)
  for (const b of hub.boxes) {
    if (moved.includes(b.follows) && b.data && b.data[READ_AT[b.follows]] !== stream[b.follows] && b.wanted()) {
      b.refreshOwn(true).catch(() => {});
    }
  }
}

// two boxes reading the same part of a page at once (VİOP's levels and contracts): one request
const inflight = new Map();
function getShared(path, params) {
  const key = path + '?' + JSON.stringify(params || {});
  let p = inflight.get(key);
  if (!p) {
    p = api.get(path, params).finally(() => inflight.delete(key));
    inflight.set(key, p);
  }
  return p;
}

const mark = (on) => (on ? '✓ ' : '    ');
const HEIGHTS = [240, 360, 480, 640];
const QUANT_AGAIN_MS = 60000;            // a quant box asks again after a minute at the latest (as its page does)
const QUANT_POLL_MS = 3000;              // ... and every few seconds until the first result is there
const CHAT_AGAIN_MS = 20000;             // the board: its quotes' ages and the model move while nothing is said (as its page)

/**
 * The frame of a box of a page.  A kind gives: ``follows`` ('quant' | 'chat' | 'gen'), ``page`` (and ``panel``) - where it comes
 * from -, ``where`` (its page's name), ``part(item)`` → {path, params} (the part of its page it reads - not ``request``:
 * a box with that joins the tables' one request), ``titleText()``, ``paint(data)`` (into ``this.body``; ``this.grid``: a
 * grid drawn, for Kopyala) and ``optionItems()`` (its own lines of the ⋯ menu).
 * opts: as a table box's (boxes.js PanelBox): {ctx, place, adhoc, edit(change), remove(), move(step), extra(box), draggable, live}.
 */
export class OwnBox {
  constructor(item, opts) {
    this.item = item;
    this.opts = opts;
    this.ctx = opts.ctx;
    this.data = null;
    this.at = 0;
    this.gen = 0;
    this.entry = null;                   // (a box that follows the generation: the hub dims it while it is behind)
    this.grid = null;
    this.dead = false;
    this.busy = null;
    this.timer = null;
    this.el = h('section', { class: 'panel lp-item ownbox' + (opts.place === 'launchpad' ? '' : ' full') });
    this.el.__box = this;
    this.titleEl = h('h2');
    this.src = h('a', { class: 'lp-src', title: 'Sayfasına git' });
    this.src.addEventListener('click', (e) => { e.preventDefault(); this.goSource(); });
    this.tools = h('div', { class: 'tools' });
    const head = h('header');
    if (opts.draggable) {
      this.handle = h('span', { class: 'lp-drag', title: 'Sürükleyip bırakarak yerini değiştirin', draggable: 'true' }, '⠿');
      head.appendChild(this.handle);
    }
    head.append(this.titleEl, this.src, this.tools);
    this.body = h('div', { class: 'body' }, waiting());       // (its first answer on its way)
    this.note = h('div', { class: 'note hidden' });
    this.el.append(head, this.body, this.note);
    this.copyBtn = h('button', { class: 'iconbtn hidden', type: 'button', title: 'Tabloyu kopyala (Excel\'e yapıştırılabilir)' }, 'Kopyala');
    this.copyBtn.addEventListener('click', () => { if (this.grid) copyGrid(this.grid, false); });
    const more = h('button', { class: 'iconbtn', type: 'button', title: 'Seçenekler, genişlik, yükseklik, ad …' }, '⋯');
    more.dataset.action = 'item-menu';
    more.addEventListener('click', (e) => {
      e.stopPropagation();
      const r = more.getBoundingClientRect();
      menu(r.left, r.bottom + 4, this.menuItems());
    });
    this.colBtn = h('button', { class: 'iconbtn', type: 'button', title: 'Daralt / aç' });
    this.colBtn.addEventListener('click', () => this.setCollapsed(!this.item.collapsed));
    this.tools.append(this.copyBtn, more, this.colBtn);
    if (opts.place === 'drawer' && opts.remove) {
      const x = h('button', { class: 'iconbtn', type: 'button', title: 'Yan panelden kaldır' }, '✕');
      x.dataset.action = 'unpin';
      x.addEventListener('click', () => opts.remove());
      this.tools.appendChild(x);
    }
  }

  /** Called by a kind's constructor once its own fields are set. */
  start() {
    this.src.href = '#/' + this.page;
    this.show(this.item);
    hub.add(this);
  }

  /** The item as the layout has it now; true when its part of the page has to be asked for again. */
  show(item) {
    const before = this.item;
    this.item = item;
    this.el.dataset.id = item.id;
    this.el.dataset.type = item.type;
    this.el.dataset.w = String(item.w || DEFAULT_W);
    this.el.dataset.h = String(item.h || 'auto');
    if (this.opts.place === 'launchpad') this.el.style.gridColumn = 'span ' + (item.w || DEFAULT_W);
    const fixed = typeof item.h === 'number';
    this.body.style.height = fixed ? item.h + 'px' : '';
    this.el.classList.toggle('fixed', fixed);
    this.el.classList.toggle('collapsed', !!item.collapsed);
    this.colBtn.textContent = item.collapsed ? '▸' : '▾';
    const ask = (x) => JSON.stringify(this.part(x));
    const again = before !== item && ask(before) !== ask(item);
    if (again) { this.data = null; this.at = 0; }                     // another part of its page: asked for again
    else if (before !== item && this.data) this.draw();                 // (the same answer, drawn another way)
    this.paintTitle();
    return again || (before !== item && !!before.collapsed && !item.collapsed);
  }

  paintTitle() {
    const own = this.titleText();
    const t = this.item.title || own;
    this.titleEl.textContent = t;
    this.titleEl.title = t + (this.item.title && own !== this.item.title ? '\nKutunun kendi adı: ' + own : '');
    this.src.textContent = this.where;
    if (this.opts.place === 'pop' && this.ctx.setTitle) this.ctx.setTitle(t);
  }

  /** Brought up to date with the others: on screen (a closed drawer's wait), open, not removed. */
  wanted() {
    return !this.dead && !this.item.collapsed && this.el.isConnected && (!this.opts.live || this.opts.live());
  }

  /** Whether what it shows is behind: a quant box when the results' version moved (or a minute went by), the board when
   *  Broker Chat changed (or its quotes aged), a generation's box always (the hub asks on each generation). */
  due() {
    if (!this.data || this.follows === 'gen') return true;
    if (this.follows === 'quant' && !this.data.ready) return true;
    const k = this.follows;
    if (stream[k] !== null && this.data[READ_AT[k]] !== stream[k]) return true;
    return Date.now() - this.at > (k === 'quant' ? QUANT_AGAIN_MS : CHAT_AGAIN_MS);
  }

  /** Its part of the page, asked for when it is behind (``force``: now) - one request at a time; the hub calls this. */
  async refreshOwn(force) {
    if (this.dead) return;
    // on its way already: once more after it - a generation (or a version, a change) that came meanwhile may be newer than
    // its answer (a quant box's and the board's answers move with their own counters: the hub's call on a generation does
    // not ask them again)
    if (this.busy) { if (force || this.follows === 'gen') this.again = true; return; }
    if (!force && !this.due()) return;
    this.busy = (async () => {
      try {
        do {
          this.again = false;
          const r = this.part(this.item);
          const d = await getShared(r.path, r.params);
          if (this.dead) return;
          this.data = d;
          this.at = Date.now();
          if (this.follows === 'gen') { this.entry = d; this.gen = d.gen || 0; }
          this.draw();
        } while (this.again && !this.dead && this.wanted());
      } catch (err) {
        if (!this.dead && !err.network && err.status !== 401) this.fail(err.message);
      } finally { this.busy = null; }
    })();
    return this.busy;
  }

  /** The answer drawn (and, for a quant box, asked for again until the first result is there). */
  draw() {
    this.el.classList.remove('stale');
    // (what it was read at: the version, the count of Broker Chat's changes, the generation)
    const at = this.data[READ_AT[this.follows]];
    this.el.dataset.version = String(at !== undefined ? at : (this.data.gen || 0));
    this.paint(this.data);
    this.copyBtn.classList.toggle('hidden', !this.grid);
    this.paintTitle();
    clearTimeout(this.pollTimer);
    if (this.follows === 'quant' && !this.data.ready) {
      this.pollTimer = setTimeout(() => { if (this.wanted()) this.refreshOwn(true); }, QUANT_POLL_MS);
    }
  }

  fail(message) {
    this.grid = null;
    clear(this.body);
    this.body.appendChild(h('div', { class: 'lp-missing' }, 'Okunamadı: ' + message));
  }

  /** A note under the box (empty: none). */
  say(text) {
    this.note.textContent = text || '';
    this.note.classList.toggle('hidden', !text);
  }

  /** A quant box before the first result: said in the box. */
  notReady(d) {
    this.grid = null;
    clear(this.body);
    this.body.appendChild(h('div', { class: 'empty' }, d.error ? 'Hesap hatası: ' + d.error : 'İlk hesap yapılıyor…'));
  }

  /** A grid in the body (the dashboard's, read only; ``name``: its page's, so that the columns hidden there are hidden
   *  here): patched in place while ``same`` says it has the same rows, rebuilt otherwise; ``onPick(i)``: a click on row i. */
  showGrid(data, name, onPick, same) {
    if (this.grid && this.grid.name_ === name && (same === undefined || this.same === same)) {
      if (same !== undefined) this.grid.update(data, true); else this.grid.replace(data);
    } else if (this.grid && this.grid.name_ === name) {
      this.grid.replace(data);
    } else {
      clear(this.body);
      this.grid = new Grid({ data, editable: false, name, tools: this.tools });
      this.grid.name_ = name;
      if (onPick) {
        this.grid.el.classList.add('pickable');
        this.grid.el.addEventListener('click', (e) => {
          if (e.target.closest('button')) return;
          const td = e.target.closest('td');
          if (td && td.__i !== undefined && td.__i >= 1) onPick(td.__i - 1);
        });
      }
      this.body.appendChild(this.grid.el);
    }
    this.same = same;
  }

  /** Nothing to show: a sentence in the body. */
  empty(text) {
    this.grid = null;
    clear(this.body);
    this.body.appendChild(h('div', { class: 'empty' }, text));
  }

  setAdhoc() {}

  findCell() {
    return null;
  }

  /** An option of the box changed (its contract, its list …): kept with the item by its owner. */
  change(patch) {
    if (this.opts.edit) this.opts.edit(patch);
    else if (this.show(changed(this.item, patch))) hub.refresh();
  }

  setCollapsed(on) {
    this.change({ collapsed: !!on });
    if (!on) hub.refresh();
  }

  goSource() {
    if (this.ctx.gotoSource) this.ctx.gotoSource(this.page, this.panel || null);
    else this.ctx.goto(this.page, this.panel || null);
  }

  menuItems() {
    const it = this.item;
    const o = this.opts;
    const items = this.optionItems();
    if (items.length) items.push({ sep: true });
    if (o.edit && o.place === 'launchpad') {
      items.push({ header: 'Genişlik' });
      for (const [w, label] of WIDTHS) items.push({ label: mark((it.w || DEFAULT_W) === w) + label, action: () => o.edit({ w }) });
    }
    if (o.edit) {
      items.push({ header: 'Yükseklik' });
      items.push({ label: mark(it.h === 'auto') + 'Otomatik (içeriği kadar)', action: () => o.edit({ h: 'auto' }) });
      for (const px of HEIGHTS) items.push({ label: mark(it.h === px) + px + ' px – içinde kaydırılır', action: () => o.edit({ h: px }) });
      items.push({ label: (typeof it.h === 'number' && !HEIGHTS.includes(it.h) ? mark(true) + it.h + ' px · ' : mark(false)) + 'Başka bir yükseklik…',
        action: () => this.askHeight() });
      items.push({ sep: true });
      items.push({ label: 'Yeniden adlandır…', action: () => this.rename() });
      if (it.title) items.push({ label: 'Kutunun kendi adına dön', action: () => o.edit({ title: null }) });
      if (o.move) {
        const vertical = o.place === 'drawer';
        items.push({ label: vertical ? 'Yukarı taşı' : 'Sola taşı', action: () => o.move(-1) });
        items.push({ label: vertical ? 'Aşağı taşı' : 'Sağa taşı', action: () => o.move(1) });
      }
      items.push({ sep: true });
    }
    if (o.extra) items.push(...o.extra(this));
    items.push({ label: 'Sayfasına git (' + this.where + ')', action: () => this.goSource() });
    if (o.remove) {
      items.push({ sep: true });
      items.push({ label: o.place === 'drawer' ? 'Yan panelden kaldır' : 'Launchpad\'den kaldır', action: () => o.remove() });
    }
    return items;
  }

  async askHeight() {
    const v = await promptDialog('Yükseklik', 'Piksel (80–2400); kutu bu yükseklikte, içinde kaydırılır', typeof this.item.h === 'number' ? String(this.item.h) : '400');
    if (v === null) return;
    const n = Math.round(Number(v));
    if (!Number.isFinite(n) || n < 80 || n > 2400) { toast('Yükseklik 80 ile 2400 piksel arasında olmalı', 'err'); return; }
    this.opts.edit({ h: n });
  }

  async rename() {
    const v = await promptDialog('Yeniden adlandır', 'Bu kutunun adı (yalnızca sizin launchpad\'inizde)', this.item.title || this.titleText());
    if (v === null) return;
    this.opts.edit({ title: v });
  }

  destroy() {
    this.dead = true;
    clearTimeout(this.pollTimer);
    if (this.timer) clearInterval(this.timer);
    hub.remove(this);
  }
}

// ---------------------------------------------------------------------- on its own page, in a window of its own
/** "+ Launchpad" and ⧉ for a box's panel on its own page (as a table's): ``src()`` → the item's {type, ...options}. */
export function boxTools(src, ctx) {
  const out = [addButton(src, { pin: ctx.pinToDrawer, pop: ctx.popOut })];
  if (ctx.popOut) {
    const pop = h('button', { class: 'iconbtn', type: 'button', title: 'Ayrı pencerede aç (menüsüz, canlı – ikinci ekran için)' }, '⧉');
    pop.dataset.action = 'popout';
    pop.addEventListener('click', () => ctx.popOut(src()));
    out.push(pop);
  }
  return out;
}

const OWN = (it) => Object.keys(it).filter((k) => !['id', 'type', 'w', 'h', 'collapsed'].includes(k) && it[k] !== undefined && it[k] !== null);

/** The address of a box in a window of its own: "#/pop/box/<type>?o={its options and its name}". */
export function popBoxHash(src) {
  const o = {};
  for (const k of OWN(src)) o[k] = src[k];
  return '#/pop/box/' + encodeURIComponent(src.type) + (Object.keys(o).length ? '?o=' + encodeURIComponent(JSON.stringify(o)) : '');
}

/** The item a window of its own shows, from its address. */
export function popBoxItem(type, query) {
  let o = {};
  try { o = JSON.parse(query.get('o') || '{}') || {}; } catch (e) { o = {}; }
  const it = { type, id: 'pop', w: 12, h: 'auto' };
  if (o && typeof o === 'object' && !Array.isArray(o)) {
    for (const [k, v] of Object.entries(o)) if (!['id', 'type', 'w', 'h', 'collapsed'].includes(k)) it[k] = v;
  }
  return it;
}

/** A box in a window of its own (``#/pop/box/<type>``): the box, live, nothing else; its choices live in its address. */
export class PopBoxPage {
  constructor(host, ctx, item) {
    this.host = host;
    this.ctx = ctx;
    this.item = item;
    this.box = null;
    this.usesHub = true;
  }

  async load() {
    clear(this.host);
    this.host.classList.add('lp-page', 'pop-one');
    this.box = makeBox(this.item, { ctx: this.ctx, place: 'pop', adhoc: () => false,
      edit: (change) => {
        this.item = changed(this.item, change);
        const again = this.box.show(this.item);
        history.replaceState(null, '', popBoxHash(this.item));
        if (again) hub.refresh();
      } });
    this.host.appendChild(this.box.el);
    await hub.refresh();
  }

  refresh() {
    return hub.refresh();
  }

  findCell() {
    return null;
  }

  destroy() {
    if (this.box) this.box.destroy();
  }
}
