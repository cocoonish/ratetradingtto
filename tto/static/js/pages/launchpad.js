// Launchpad: each user's own pages of tables picked from any page of the dashboard - several, as tabs.  A table is put on
// one from its page ("+ Launchpad" in its header) or from Ctrl+K; here it is moved (drag and drop), sized, cut to the rows
// and columns wanted, renamed, collapsed or removed.  The tables are live and editable in place: a value typed here is
// the source page's value too (the same cells of the same book, as this user or for the desk as the cell says).
import { api } from '../api.js';
import { h, clear, toast, errorToast, menu, confirmDialog, promptDialog } from '../ui.js';
import { hub, makeBox, changed } from '../boxes.js';
import { onLayout, loadLayout, launchpads, findLaunchpad, changeLaunchpad, createLaunchpad, saveLayout, landing,
  pinToDrawer } from '../layout.js';
import { addCalcSheet } from '../calc.js';

const nameKey = (s) => String(s || '').replace(/I/g, 'ı').replace(/İ/g, 'i').toLocaleLowerCase('tr');

function handMode() {
  try { return sessionStorage.getItem('tto.adhoc') === '1'; } catch (e) { return false; }
}

function lastKey() {
  return 'tto.lp.last';
}

function remember(name) {
  try { localStorage.setItem(lastKey(), name); } catch (e) { /* ignore */ }
}

function remembered() {
  try { return localStorage.getItem(lastKey()); } catch (e) { return null; }
}

export class LaunchpadPage {
  /** opts: {name: the launchpad to show (else the last one opened), pop: a window of its own (no tabs, no menu)} */
  constructor(host, ctx, opts = {}) {
    this.host = host;
    this.ctx = ctx;
    this.pop = !!opts.pop;
    this.name = opts.name || (this.pop ? null : remembered());
    this.boxes = new Map();                 // item id -> PanelBox
    this.keepAlive = !this.pop;             // (kept with the last pages opened: back in view at once)
    this.usesHub = true;                    // (its refresh is the boxes' request)
    this.adhoc = handMode();
    this.dead = false;
    this.dragId = null;
  }

  async load() {
    await loadLayout();                     // (changed on another computer since the sign-in, maybe)
    if (this.dead) return;
    if (!this.off) this.off = onLayout(() => this.sync());
    this.build();
  }

  /** The launchpad on screen: the one asked for, or the first. */
  current() {
    const lp = this.name ? findLaunchpad(this.name) : null;
    if (lp || this.pop) return lp;
    return launchpads()[0] || null;
  }

  build() {
    clear(this.host);
    this.host.classList.add('lp-page');
    this.host.classList.toggle('hand', this.adhoc);
    const tools = h('div', { class: 'page-tools lp-tools' });
    const newBtn = h('button', { class: 'btn sm', type: 'button', id: 'lp-new', title: 'Boş bir launchpad oluşturun; tabloları sayfalarından "+ Launchpad" ile ekleyin' }, '+ Yeni launchpad');
    newBtn.addEventListener('click', async () => {
      const name = await createLaunchpad([]);
      if (name) this.open(name);
    });
    this.handBtn = h('button', { class: 'btn sm' + (this.adhoc ? ' on' : ''), type: 'button', id: 'lp-hand',
      title: 'Açıkken tablolardaki her hücreye – formül olanlara da – kendi değerinizi yazabilirsiniz (sayfalardaki "Elle değer" ile aynı)' }, 'Elle değer');
    this.handBtn.addEventListener('click', () => this.setHand(!this.adhoc));
    const exp = h('button', { class: 'btn sm', type: 'button', id: 'lp-export', title: 'Bu launchpad\'i bir JSON dosyası olarak indirin (saklamak ya da bir arkadaşınıza vermek için)' }, 'Dışa aktar');
    exp.addEventListener('click', () => this.exportCurrent());
    const file = h('input', { type: 'file', accept: '.json,application/json', class: 'hidden', id: 'lp-import-file' });
    file.addEventListener('change', () => { if (file.files && file.files[0]) this.importFile(file.files[0]).finally(() => { file.value = ''; }); });
    const imp = h('button', { class: 'btn sm', type: 'button', id: 'lp-import', title: 'Dışa aktarılmış bir launchpad dosyasını ekleyin' }, 'İçe aktar…');
    imp.addEventListener('click', () => file.click());
    const pop = h('button', { class: 'btn sm', type: 'button', id: 'lp-pop', title: 'Bu launchpad\'i menüsüz ayrı bir pencerede açın (ikinci ekran için)' }, 'Ayrı pencerede aç');
    pop.addEventListener('click', () => { const lp = this.current(); if (lp && this.ctx.popLaunchpad) this.ctx.popLaunchpad(lp.name); });
    this.landBtn = h('button', { class: 'btn sm', type: 'button', id: 'lp-landing', title: 'Dashboard\'u adres yazmadan açtığınızda bu launchpad açılsın' }, 'Açılış sayfası yap');
    this.landBtn.addEventListener('click', () => this.toggleLanding());
    // a calc sheet of one's own (calc.js): numbers and formulas over the dashboard's live cells
    const calcBtn = h('button', { class: 'btn sm', type: 'button', id: 'lp-calc', title: 'Bu launchpad\'e kendi hesap tablonuzu ekleyin: sayılar ve =MASA!I60+25 gibi canlı formüller' }, '+ Hesap tablosu');
    calcBtn.addEventListener('click', async () => {
      const lp = this.current();
      const name = await addCalcSheet(lp ? lp.name : null);
      if (name && (!lp || name !== lp.name)) this.open(name);
    });
    if (this.pop) tools.append(this.handBtn);
    else tools.append(newBtn, calcBtn, this.handBtn, exp, imp, file, pop, this.landBtn);
    tools.appendChild(h('span', { class: 'grow' }));
    tools.appendChild(h('span', { class: 'muted lp-hint' }, this.pop ? '' : 'Tablo eklemek için: sayfasındaki tablonun başlığında "+ Launchpad", ya da Ctrl+K'));
    this.tabs = h('div', { class: 'viewtabs lp-tabs', role: 'tablist', id: 'lp-tabs' });
    this.grid = h('div', { class: 'lp-grid', id: 'lp-grid' });
    this.empty = h('div', { class: 'lp-empty hidden' });
    this.host.appendChild(tools);
    if (!this.pop) this.host.appendChild(this.tabs);
    this.host.appendChild(this.empty);
    this.host.appendChild(this.grid);
    this.dnd();
    this.sync();
  }

  /** The layout changed (here, in another window, from the server): the tabs and the boxes follow it. */
  sync() {
    if (this.dead || !this.grid) return;
    const lp = this.current();
    if (lp) this.name = lp.name;
    if (!this.pop) this.paintTabs(lp);
    this.paintItems(lp);
    if (this.landBtn) {
      const on = !!lp && nameKey(landing()) === nameKey('launchpad/' + lp.name);
      this.landBtn.classList.toggle('on', on);
      this.landBtn.textContent = on ? 'Açılış sayfası ✓' : 'Açılış sayfası yap';
    }
    if (this.ctx.setTitle) this.ctx.setTitle(lp ? 'Launchpad · ' + lp.name : 'Launchpad');
  }

  paintTabs(cur) {
    clear(this.tabs);
    for (const lp of launchpads()) {
      const b = h('button', { type: 'button', role: 'tab', class: 'lp-tab', draggable: 'true', title: lp.items.length + ' tablo · sağ tık: adlandır, taşı, sil …' },
        lp.name, h('span', { class: 'n' }, String(lp.items.length)));
      b.dataset.name = lp.name;
      b.classList.toggle('on', !!cur && cur.name === lp.name);
      b.addEventListener('click', () => this.open(lp.name));
      b.addEventListener('contextmenu', (e) => { e.preventDefault(); this.tabMenu(lp.name, e.clientX, e.clientY); });
      this.tabs.appendChild(b);
    }
    if (cur) {
      const more = h('button', { type: 'button', class: 'lp-tabmenu', id: 'lp-menu', title: 'Bu launchpad: adlandır, taşı, dışa aktar, sil …' }, '⋯');
      more.addEventListener('click', (e) => { const r = e.currentTarget.getBoundingClientRect(); this.tabMenu(cur.name, r.left, r.bottom + 4); });
      this.tabs.appendChild(more);
    }
  }

  paintItems(lp) {
    const items = lp ? lp.items : [];
    const keep = new Set(items.map((it) => it.id));
    for (const [id, box] of this.boxes) {
      if (!keep.has(id)) { box.destroy(); box.el.remove(); this.boxes.delete(id); }
    }
    let fresh = false;
    items.forEach((it) => {
      let box = this.boxes.get(it.id);
      if (!box) {
        box = makeBox(it, this.boxOpts(it.id));
        this.boxes.set(it.id, box);
        fresh = true;
      } else if (JSON.stringify(box.item) !== JSON.stringify(it)) {
        if (box.show(it)) fresh = true;
      }
      this.grid.appendChild(box.el);                // (in the launchpad's order)
    });
    this.empty.classList.toggle('hidden', items.length > 0);
    clear(this.empty);
    if (!lp) {
      this.empty.append(h('b', null, this.pop ? 'Bu launchpad yok' : 'Henüz launchpad\'iniz yok.'), ' ',
        this.pop ? 'Silinmiş ya da adı değişmiş olabilir.' : 'Sık baktığınız tabloları bir araya toplayın: bir sayfadaki tablonun başlığında '
          + '"+ Launchpad"e tıklayın (ya da Ctrl+K ile tabloyu bulun) – istediğiniz kadar launchpad, her biri bir sekme.');
    } else if (!items.length) {
      this.empty.append(h('b', null, 'Bu launchpad boş.'), ' Bir sayfadaki tablonun başlığında "+ Launchpad" → "' + lp.name + '"; ya da Ctrl+K ile tabloyu bulup "+ Launchpad".');
    }
    if (fresh) hub.refresh();
  }

  boxOpts(id) {
    const find = (lp) => lp.items.findIndex((x) => x.id === id);
    const keepGoing = (p) => { if (p) p.catch(() => {}); };
    return {
      ctx: this.ctx,
      place: 'launchpad',
      draggable: true,
      adhoc: () => this.adhoc,
      edit: (change) => keepGoing(changeLaunchpad(this.name, (lp) => {
        const i = find(lp);
        if (i >= 0) lp.items[i] = changed(lp.items[i], change);
      })),
      remove: () => keepGoing(changeLaunchpad(this.name, (lp) => {
        const i = find(lp);
        if (i >= 0) lp.items.splice(i, 1);
      })),
      move: (step) => keepGoing(changeLaunchpad(this.name, (lp) => {
        const i = find(lp);
        const j = i + step;
        if (i < 0 || j < 0 || j >= lp.items.length) return;
        const [it] = lp.items.splice(i, 1);
        lp.items.splice(j, 0, it);
      })),
      extra: (box) => [
        { label: 'Yan panele sabitle', action: () => keepGoing(pinToDrawer(box.item)) },
        this.ctx.popOut ? { label: 'Ayrı pencerede aç', action: () => this.ctx.popOut(box.item) } : null,
      ],
    };
  }

  /** Drag a box by its handle and drop it on another: it goes before (left half) or after it. */
  dnd() {
    const clearMarks = () => { for (const el of this.grid.querySelectorAll('.drop-before, .drop-after, .dragging')) el.classList.remove('drop-before', 'drop-after', 'dragging'); };
    this.grid.addEventListener('dragstart', (e) => {
      const handle = e.target.closest && e.target.closest('.lp-drag');
      const el = handle && handle.closest('.lp-item');
      if (!el) return;
      this.dragId = el.dataset.id;
      el.classList.add('dragging');
      try {
        e.dataTransfer.effectAllowed = 'move';
        e.dataTransfer.setData('text/plain', 'lp:' + this.dragId);
        e.dataTransfer.setDragImage(el, 20, 16);
      } catch (x) { /* older browsers */ }
    });
    this.grid.addEventListener('dragover', (e) => {
      if (!this.dragId) return;
      const el = e.target.closest && e.target.closest('.lp-item');
      e.preventDefault();
      for (const x of this.grid.querySelectorAll('.drop-before, .drop-after')) if (x !== el) x.classList.remove('drop-before', 'drop-after');
      if (!el || el.dataset.id === this.dragId) return;
      const r = el.getBoundingClientRect();
      const before = e.clientX < r.left + r.width / 2;
      el.classList.toggle('drop-before', before);
      el.classList.toggle('drop-after', !before);
    });
    this.grid.addEventListener('drop', (e) => {
      if (!this.dragId) return;
      e.preventDefault();
      const el = e.target.closest && e.target.closest('.lp-item');
      const from = this.dragId;
      const before = el ? el.classList.contains('drop-before') : false;
      const to = el ? el.dataset.id : null;
      this.dragId = null;
      clearMarks();
      if (to === from) return;
      changeLaunchpad(this.name, (lp) => {
        const i = lp.items.findIndex((x) => x.id === from);
        if (i < 0) return;
        const [it] = lp.items.splice(i, 1);
        let j = to ? lp.items.findIndex((x) => x.id === to) : lp.items.length;
        if (j < 0) j = lp.items.length;
        else if (!before) j += 1;
        lp.items.splice(j, 0, it);
      }).catch(() => {});
    });
    this.grid.addEventListener('dragend', () => { this.dragId = null; clearMarks(); });
    // the tabs: dragged into another order
    this.tabs.addEventListener('dragstart', (e) => {
      const b = e.target.closest && e.target.closest('.lp-tab');
      if (!b) return;
      this.dragTab = b.dataset.name;
      try { e.dataTransfer.effectAllowed = 'move'; e.dataTransfer.setData('text/plain', 'tab:' + this.dragTab); } catch (x) { /* ignore */ }
    });
    this.tabs.addEventListener('dragover', (e) => { if (this.dragTab) e.preventDefault(); });
    this.tabs.addEventListener('drop', (e) => {
      const b = e.target.closest && e.target.closest('.lp-tab');
      const from = this.dragTab;
      this.dragTab = null;
      if (!from || !b || b.dataset.name === from) return;
      e.preventDefault();
      const all = launchpads().slice();
      const i = all.findIndex((x) => x.name === from);
      const [lp] = all.splice(i, 1);
      const r = b.getBoundingClientRect();
      let j = all.findIndex((x) => x.name === b.dataset.name);
      if (e.clientX > r.left + r.width / 2) j += 1;
      all.splice(j, 0, lp);
      saveLayout({ launchpads: all }).catch(() => {});
    });
    this.tabs.addEventListener('dragend', () => { this.dragTab = null; });
  }

  tabMenu(name, x, y) {
    const all = launchpads();
    const i = all.findIndex((lp) => lp.name === name);
    const moveTo = (j) => {
      if (j < 0 || j >= all.length) return;
      const copy = all.slice();
      const [lp] = copy.splice(i, 1);
      copy.splice(j, 0, lp);
      saveLayout({ launchpads: copy }).catch(() => {});
    };
    const isLanding = nameKey(landing()) === nameKey('launchpad/' + name);
    menu(x, y, [
      { header: name },
      { label: 'Yeniden adlandır…', action: () => this.rename(name) },
      { label: 'Sola taşı', disabled: i <= 0, action: () => moveTo(i - 1) },
      { label: 'Sağa taşı', disabled: i >= all.length - 1, action: () => moveTo(i + 1) },
      { sep: true },
      { label: isLanding ? 'Açılış sayfası olmaktan çıkar' : 'Açılış sayfası yap', action: () => this.toggleLanding(name) },
      { label: 'Ayrı pencerede aç', action: () => this.ctx.popLaunchpad && this.ctx.popLaunchpad(name) },
      { label: 'Dışa aktar (JSON)', action: () => this.exportCurrent(name) },
      { sep: true },
      { label: 'Sil…', action: () => this.remove(name) },
    ]);
  }

  /** Show another launchpad (its own address: back / forward and a bookmark find it). */
  open(name) {
    if (this.ctx.openLaunchpad) this.ctx.openLaunchpad(name);
    else this.select(name);
  }

  select(name) {
    if (name) {
      this.name = name;
      remember(name);
    }
    this.sync();
    hub.refresh();
  }

  async rename(name) {
    const v = await promptDialog('Launchpad\'i yeniden adlandır', 'Yeni adı', name);
    if (!v || v === name) return;
    if (findLaunchpad(v) && nameKey(v) !== nameKey(name)) { toast('Bu adla bir launchpad zaten var: ' + v, 'err'); return; }
    const all = JSON.parse(JSON.stringify(launchpads()));
    const lp = all.find((x) => x.name === name);
    if (!lp) return;
    lp.name = v;
    const parts = { launchpads: all };
    if (nameKey(landing()) === nameKey('launchpad/' + name)) parts.landing = 'launchpad/' + v;
    const shown = nameKey(this.name) === nameKey(name);
    if (shown) this.name = v;                     // (the one on screen keeps its place under its new name)
    try { await saveLayout(parts); } catch (e) { return; }
    if (shown) this.open(v);                      // (and its address follows)
  }

  async remove(name) {
    const lp = findLaunchpad(name);
    if (!lp) return;
    const ok = await confirmDialog('Launchpad\'i sil', '"' + name + '" ve içindeki ' + lp.items.length
      + ' tablo kutusu silinir (tabloların kendisi sayfalarında durur). Önce dışa aktarıp saklayabilirsiniz.', 'Sil', true);
    if (!ok) return;
    const parts = { launchpads: launchpads().filter((x) => x.name !== name) };
    if (nameKey(landing()) === nameKey('launchpad/' + name)) parts.landing = '';
    const shown = nameKey(this.name) === nameKey(name);
    try { await saveLayout(parts); } catch (e) { return; }
    if (shown) {
      const next = launchpads()[0];
      this.name = next ? next.name : null;
      if (next) this.open(next.name);
      else { this.sync(); if (this.ctx.openLaunchpad) history.replaceState(null, '', '#/launchpad'); }
    }
    toast('"' + name + '" silindi', 'ok');
  }

  async toggleLanding(name) {
    const lp = name ? findLaunchpad(name) : this.current();
    if (!lp) return;
    const on = nameKey(landing()) === nameKey('launchpad/' + lp.name);
    try { await saveLayout({ landing: on ? '' : 'launchpad/' + lp.name }); } catch (e) { return; }
    toast(on ? 'Açılış sayfası Masa\'ya döndü' : 'Dashboard bundan sonra "' + lp.name + '" launchpad\'iyle açılır', 'ok', 3200);
  }

  exportCurrent(name) {
    const lp = name ? findLaunchpad(name) : this.current();
    if (!lp) { toast('Dışa aktarılacak bir launchpad yok', 'err'); return; }
    api.download('/api/layout/export', { name: lp.name }, 'launchpad.json').catch(errorToast);
  }

  async importFile(file) {
    let data;
    try { data = JSON.parse(await file.text()); } catch (e) { toast('Dosya okunamadı: geçerli bir JSON değil', 'err'); return; }
    try {
      const res = await api.post('/api/layout/import', { launchpad: data });
      await loadLayout();
      toast('"' + res.name + '" launchpad\'i eklendi', 'ok');
      this.open(res.name);
    } catch (err) { errorToast(err); }
  }

  setHand(on) {
    this.adhoc = !!on;
    try { sessionStorage.setItem('tto.adhoc', on ? '1' : '0'); } catch (e) { /* ignore */ }
    this.handBtn.classList.toggle('on', this.adhoc);
    this.host.classList.toggle('hand', this.adhoc);
    for (const box of this.boxes.values()) box.setAdhoc(this.adhoc);
    if (this.ctx.handChanged) this.ctx.handChanged(this.adhoc);
    toast(this.adhoc ? 'Elle değer açık: her hücreye yazabilirsiniz (yalnızca sizde değişir; silince formül geri gelir)' : 'Elle değer kapalı', '', 3600);
  }

  /** Bring the boxes up to date (the shell's live refresh). */
  refresh() {
    return hub.refresh();
  }

  /** Back in view (kept with the last pages opened): another launchpad maybe, "Elle değer" as it is now, what changed. */
  revive(name) {
    const hand = handMode();
    if (hand !== this.adhoc) {
      this.adhoc = hand;
      if (this.handBtn) this.handBtn.classList.toggle('on', hand);
      this.host.classList.toggle('hand', hand);
      for (const box of this.boxes.values()) box.setAdhoc(hand);
    }
    if (name) { this.name = name; remember(name); }
    this.sync();
    if (this.ctx.gen) hub.markStale(this.ctx.gen());
    loadLayout();                           // (changed on another computer meanwhile, maybe: the boxes follow)
  }

  findCell(ref) {
    for (const box of this.boxes.values()) {
      const td = box.findCell(ref);
      if (td) return td;
    }
    return null;
  }

  destroy() {
    this.dead = true;
    if (this.off) { this.off(); this.off = null; }
    for (const box of this.boxes.values()) box.destroy();
    this.boxes.clear();
  }
}

/** A table of a page in a window of its own (``#/pop/<page>/<table>``): one box, live and editable, nothing else. */
export class PopPanelPage {
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
    this.host.classList.toggle('hand', handMode());
    this.box = makeBox(this.item, { ctx: this.ctx, place: 'pop', adhoc: () => handMode(),
      edit: (change) => {                        // (a window of its own: its choice lives in its address)
        this.item = changed(this.item, change);
        this.box.show(this.item);
        if (this.ctx.popChanged) this.ctx.popChanged(this.item);
        hub.refresh();
      } });
    this.host.appendChild(this.box.el);
    await hub.refresh();
    if (this.box.entry && this.ctx.setTitle) this.ctx.setTitle(this.box.titleEl.textContent);
  }

  refresh() {
    return hub.refresh();
  }

  findCell(ref) {
    return this.box ? this.box.findCell(ref) : null;
  }

  destroy() {
    if (this.box) this.box.destroy();
  }
}
