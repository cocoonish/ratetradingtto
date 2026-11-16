// The side drawer: tables pinned to the right of every page - the same live, editable boxes as a launchpad's - opened
// and closed from the top bar or with Alt+Y.  What is pinned is kept with the account (any computer shows the same);
// whether the drawer is open and how wide, in this browser.
import { h, clear } from './ui.js';
import { hub, PanelBox, changed } from './boxes.js';
import { onLayout, drawerItems, saveLayout } from './layout.js';

function pref(key) {
  try { return localStorage.getItem(key); } catch (e) { return null; }
}

function setPref(key, value) {
  try { localStorage.setItem(key, value); } catch (e) { /* ignore */ }
}

export class Drawer {
  constructor(ctx) {
    this.ctx = ctx;
    this.el = document.getElementById('drawer');
    this.list = document.getElementById('dr-list');
    this.btn = document.getElementById('btn-drawer');
    this.boxes = new Map();            // item id -> PanelBox
    this.on = false;
    this.off = null;
    document.getElementById('dr-close').addEventListener('click', () => this.setOpen(false));
    document.getElementById('dr-wide').addEventListener('click', () => {
      const wide = !document.getElementById('app').classList.contains('drawer-wide');
      document.getElementById('app').classList.toggle('drawer-wide', wide);
      setPref('tto.drawer.wide', wide ? '1' : '0');
    });
    this.btn.addEventListener('click', () => this.toggle());
  }

  /** Signed in: the pinned tables, and the drawer open if it was. */
  start() {
    this.stop();
    this.off = onLayout(() => this.sync());
    document.getElementById('app').classList.toggle('drawer-wide', pref('tto.drawer.wide') === '1');
    this.sync();
    this.setOpen(pref('tto.drawer') === '1', true);
  }

  /** Signed out: nothing of it stays. */
  stop() {
    if (this.off) { this.off(); this.off = null; }
    for (const box of this.boxes.values()) { box.destroy(); box.el.remove(); }
    this.boxes.clear();
    this.setOpen(false, true);
  }

  toggle() {
    this.setOpen(!this.on);
  }

  setOpen(on, quiet) {
    this.on = !!on;
    document.getElementById('app').classList.toggle('drawer-open', this.on);
    this.el.classList.toggle('hidden', !this.on);
    this.btn.classList.toggle('on', this.on);
    this.btn.setAttribute('aria-pressed', this.on ? 'true' : 'false');
    if (!quiet) setPref('tto.drawer', this.on ? '1' : '0');
    if (this.on) {
      if (this.ctx.gen) hub.markStale(this.ctx.gen());
      hub.refresh();
    }
  }

  /** The pinned tables as the layout has them now. */
  sync() {
    const items = drawerItems();
    const keep = new Set(items.map((it) => it.id));
    for (const [id, box] of this.boxes) {
      if (!keep.has(id)) { box.destroy(); box.el.remove(); this.boxes.delete(id); }
    }
    let fresh = false;
    for (const it of items) {
      let box = this.boxes.get(it.id);
      if (!box) {
        box = new PanelBox(it, this.boxOpts(it.id));
        this.boxes.set(it.id, box);
        fresh = true;
      } else if (JSON.stringify(box.item) !== JSON.stringify(it)) {
        if (box.show(it)) fresh = true;
      }
      this.list.appendChild(box.el);
    }
    clear(document.getElementById('dr-empty'));
    if (!items.length) {
      document.getElementById('dr-empty').append('Yan panel boş. Bir tablonun başlığındaki "+ Launchpad" → "Yan panele sabitle" ile '
        + 'tabloyu buraya alın: hangi sayfaya geçerseniz geçin burada durur.');
    }
    document.getElementById('dr-empty').classList.toggle('hidden', items.length > 0);
    document.getElementById('dr-count').textContent = items.length ? String(items.length) : '';
    this.btn.title = 'Yan panel: sabitlediğiniz ' + items.length + ' tablo her sayfada sağda (Alt+Y)';
    if (fresh && this.on) hub.refresh();
  }

  boxOpts(id) {
    const edit = (fn) => {
      const items = JSON.parse(JSON.stringify(drawerItems()));
      const i = items.findIndex((x) => x.id === id);
      if (i < 0) return;
      fn(items, i);
      saveLayout({ drawer: items }).catch(() => {});
    };
    return {
      ctx: this.ctx,
      place: 'drawer',
      live: () => this.on,
      adhoc: () => this.ctx.handMode ? this.ctx.handMode() : false,
      edit: (change) => edit((items, i) => { items[i] = changed(items[i], change); }),
      remove: () => edit((items, i) => { items.splice(i, 1); }),
      move: (step) => edit((items, i) => {
        const j = i + step;
        if (j < 0 || j >= items.length) return;
        const [it] = items.splice(i, 1);
        items.splice(j, 0, it);
      }),
      extra: (box) => [
        this.ctx.addToLaunchpadMenu ? { label: 'Launchpad\'e ekle…', action: () => this.ctx.addToLaunchpadMenu(box) } : null,
        this.ctx.popOut ? { label: 'Ayrı pencerede aç', action: () => this.ctx.popOut(box.item) } : null,
      ],
    };
  }

  /** "Elle değer" switched on a page: the drawer's tables follow. */
  hand(on) {
    this.el.classList.toggle('hand', !!on);
    for (const box of this.boxes.values()) box.setAdhoc(on);
  }

  findCell(ref) {
    for (const box of this.boxes.values()) {
      const td = box.findCell(ref);
      if (td) return td;
    }
    return null;
  }
}
