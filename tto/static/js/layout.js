// Each user's own arrangement of the dashboard: launchpads (named pages of tables picked from any page), the side drawer,
// the favourite pages of the top bar and the page the dashboard opens on.  Kept with the account on the server
// (/api/layout), so any computer shows the same and an update keeps it; the other windows of this browser (a pop-out,
// another tab) hear of a change at once.
import { api, session } from './api.js';
import { h, toast, menu, promptDialog } from './ui.js';

export const WIDTHS = [[3, '¼'], [4, '⅓'], [6, '½'], [8, '⅔'], [12, 'Tam']];
export const DEFAULT_W = 6;

export const layout = { data: null };
const listeners = new Set();
const chan = typeof window.BroadcastChannel === 'function' ? new BroadcastChannel('tto-layout') : null;
let pending = 0;                  // saves on their way: an answer is put in place only when it is the last one

const EMPTY = () => ({ launchpads: [], drawer: [], favs: [], landing: '', hidden_pages: [], rev: 0 });

function emit() {
  for (const fn of listeners) {
    try { fn(layout.data); } catch (e) { console.warn('layout listener', e); }
  }
}

/** Called with the layout whenever it changes (here, in another window, from the server); returns the unsubscribe. */
export function onLayout(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** The signed-in user's layout (on signing in, when another window changed it, when a launchpad is opened: it may have
 *  changed on another computer).  A change of this window on its way is not overwritten by an older answer. */
export async function loadLayout() {
  try {
    const res = await api.get('/api/layout');
    if (pending) return layout.data;
    layout.data = res;
  } catch (e) {
    layout.data = layout.data || EMPTY();
    if (e.status !== 401) toast('Launchpad / yan panel düzeniniz okunamadı: ' + e.message, 'err', 6000);
  }
  emit();
  return layout.data;
}

export function clearLayout() {
  layout.data = null;
}

// a change made just before the page goes (a reload, the window closed): what was not answered yet goes with it
window.addEventListener('pagehide', () => {
  if (!pending || !unsaved || !navigator.sendBeacon) return;
  try { navigator.sendBeacon('/api/layout', new Blob([JSON.stringify(unsaved)], { type: 'application/json' })); } catch (e) { /* gone */ }
});

if (chan) {
  chan.onmessage = (e) => {
    const m = e.data || {};
    if (session.user && m.user === session.user && m.rev !== (layout.data && layout.data.rev) && !pending) loadLayout();
  };
}

/** Replace parts of the layout ({launchpads?, drawer?, favs?, landing?}): on screen at once, saved one after the other. */
let queue = Promise.resolve();
let unsaved = null;               // the parts of the saves still on their way: sent once more if the page goes now
export function saveLayout(parts) {
  layout.data = Object.assign({}, layout.data || EMPTY(), JSON.parse(JSON.stringify(parts)));
  emit();
  const body = JSON.parse(JSON.stringify(parts));
  unsaved = Object.assign({}, unsaved || {}, body);
  pending += 1;
  const job = queue.then(() => api.post('/api/layout', body)).then((res) => {
    pending -= 1;
    if (!pending) {
      unsaved = null;
      layout.data = res;
      emit();
    }
    if (chan) chan.postMessage({ user: session.user, rev: res.rev });
    return res;
  }, (err) => {
    pending -= 1;
    if (err.status !== 401) toast('Düzeniniz kaydedilemedi: ' + err.message, 'err', 7000);
    return loadLayout().then(() => { throw err; });            // (said here: a caller only stops)
  });
  queue = job.catch(() => null);
  return job;
}

// ---------------------------------------------------------------------- launchpads
export function launchpads() {
  return (layout.data && layout.data.launchpads) || [];
}

const nameKey = (s) => String(s || '').replace(/I/g, 'ı').replace(/İ/g, 'i').toLocaleLowerCase('tr');

export function findLaunchpad(name) {
  const k = nameKey(name);
  return launchpads().find((lp) => nameKey(lp.name) === k) || null;
}

/** A copy of the launchpads with ``fn`` applied to the one named (``fn`` changes it in place), saved. */
export function changeLaunchpad(name, fn) {
  const all = JSON.parse(JSON.stringify(launchpads()));
  const lp = all.find((x) => nameKey(x.name) === nameKey(name));
  if (!lp) return null;
  fn(lp, all);
  return saveLayout({ launchpads: all });
}

export function newId() {
  return Math.random().toString(36).slice(2, 8) + Date.now().toString(36).slice(-4);
}

/** A launchpad name nobody of this user's has yet: "Launchpad 2" ... */
export function freeName(base = 'Launchpad') {
  if (!findLaunchpad(base)) return base;
  for (let n = 2; n < 999; n++) if (!findLaunchpad(base + ' ' + n)) return base + ' ' + n;
  return base + ' ' + Date.now();
}

/** Ask for a name and make a launchpad (with ``items``); the name made, or null. */
export async function createLaunchpad(items = [], suggested = '') {
  const name = await promptDialog('Yeni launchpad', 'Adı', suggested || freeName());
  if (!name) return null;
  if (findLaunchpad(name)) { toast('Bu adla bir launchpad zaten var: ' + name, 'err'); return null; }
  if (launchpads().length >= 24) { toast('En fazla 24 launchpad olabilir', 'err'); return null; }
  try { await saveLayout({ launchpads: launchpads().concat([{ name, items }]) }); } catch (e) { return null; }
  return name;
}

// an item of another kind than a table (a box of one of the dashboard's own pages): its type and its options name it
const typed = (x) => !!x && !!x.type && x.type !== 'table';
const COMMON = ['id', 'type', 'title', 'w', 'h', 'collapsed'];

/** What makes a box of another kind the one it is: its type and its options ("viop-levels" of "front"). */
export function itemKey(it) {
  const own = Object.keys(it).filter((k) => !COMMON.includes(k) && it[k] !== undefined && it[k] !== null).sort();
  return it.type + ':' + JSON.stringify(own.map((k) => [k, it[k]]));
}

/** Whether ``it`` (of a launchpad, of the drawer) is the table - or the box - ``src`` names. */
function sameBox(it, src) {
  return typed(src) ? typed(it) && itemKey(it) === itemKey(src) : !typed(it) && it.view === src.view && it.panel === src.panel;
}

/** The item of a table of a page: {type: 'table', id, view, panel, w, h, all?} - or of a box of another kind (``src.type``):
 *  its options as they are. */
export function tableItem(src) {
  if (typed(src)) {
    const it = Object.assign({}, src, { id: newId(), w: src.w || DEFAULT_W, h: src.h || 'auto' });
    for (const k of Object.keys(it)) if (it[k] === undefined || it[k] === null) delete it[k];
    delete it.collapsed;
    return it;
  }
  const it = { type: 'table', id: newId(), view: src.view, panel: src.panel, w: src.w || DEFAULT_W, h: 'auto' };
  if (src.all) it.all = true;
  if (src.rows && src.rows.length) it.rows = src.rows.slice();
  if (src.cols && src.cols.length) it.cols = src.cols.slice();
  if (src.title) it.title = src.title;
  return it;
}

/** Put a table on a launchpad (made when ``name`` is null: asked for). */
export async function addToLaunchpad(src, name) {
  let target = name;
  if (!target) {
    target = await createLaunchpad([tableItem(src)]);
    if (target) toast('"' + target + '" launchpad\'i oluşturuldu, ' + (typed(src) ? 'kutu' : 'tablo') + ' eklendi', 'ok', 3200);
    return target;
  }
  const lp = findLaunchpad(target);
  if (!lp) return null;
  if (lp.items.length >= 60) { toast('Bir launchpad en fazla 60 tablo alır', 'err'); return null; }
  try { await changeLaunchpad(target, (x) => { x.items.push(tableItem(src)); }); } catch (e) { return null; }
  toast((typed(src) ? 'Kutu' : 'Tablo') + ' "' + lp.name + '" launchpad\'ine eklendi', 'ok', 2600);
  return lp.name;
}

// ---------------------------------------------------------------------- the side drawer
export function drawerItems() {
  return (layout.data && layout.data.drawer) || [];
}

/** Whether the drawer holds the whole table (or the box) ``src`` names. */
export function inDrawer(src) {
  return drawerItems().some((it) => sameBox(it, src) && !it.rows && !it.cols);
}

export function pinToDrawer(src) {
  if (drawerItems().length >= 24) { toast('Yan panel en fazla 24 tablo alır', 'err'); return null; }
  const it = tableItem(src);
  it.w = 12;
  return saveLayout({ drawer: drawerItems().concat([it]) });
}

export function unpinFromDrawer(src) {
  return saveLayout({ drawer: drawerItems().filter((it) => !(sameBox(it, src) && !it.rows && !it.cols)) });
}

// ---------------------------------------------------------------------- favourite pages, the landing page
export function favs() {
  return (layout.data && layout.data.favs) || [];
}

export function toggleFav(id) {
  const now = favs();
  return saveLayout({ favs: now.includes(id) ? now.filter((x) => x !== id) : now.concat([id]) });
}

export function landing() {
  return (layout.data && layout.data.landing) || '';
}

export function setLanding(where) {
  return saveLayout({ landing: where || '' });
}

/** The menu entries this user took out of their menu (a page's id, or a menu entry's whose pages are its tabs). */
export function hiddenPages() {
  return (layout.data && layout.data.hidden_pages) || [];
}

export function setHiddenPages(ids) {
  return saveLayout({ hidden_pages: ids });
}

// ---------------------------------------------------------------------- "+ Launchpad": where a table goes
/**
 * The menu of a table's "+ Launchpad" (and of a Ctrl+K result): the launchpads to put it on, a new one, the side
 * drawer, a window of its own.  ``src``: {view, panel, all?, title?}; ``acts``: {pin(src), pop(src)} of the shell.
 */
export function addMenu(x, y, src, acts) {
  const items = [{ header: 'Launchpad\'e ekle' }];
  for (const lp of launchpads()) {
    const has = lp.items.some((it) => sameBox(it, src));
    items.push({ label: lp.name + (has ? '  ✓ zaten var' : ''), action: () => addToLaunchpad(src, lp.name) });
  }
  items.push({ label: '+ Yeni launchpad…', action: () => addToLaunchpad(src, null) });
  items.push({ sep: true });
  const pinned = inDrawer(src);
  items.push({ label: pinned ? 'Yan panelden kaldır' : 'Yan panele sabitle', action: () => (pinned
    ? unpinFromDrawer(src) : acts && acts.pin ? acts.pin(src) : pinToDrawer(src)) });
  if (acts && acts.pop) items.push({ label: 'Ayrı pencerede aç', action: () => acts.pop(src) });
  return menu(x, y, items);
}

/** A small "+ Launchpad" button for a table's header. */
export function addButton(src, acts) {
  const b = h('button', { class: 'iconbtn lp-add', type: 'button', title: 'Bu tabloyu launchpad\'inize ya da yan panele ekleyin' }, '+ Launchpad');
  b.dataset.action = 'launchpad';
  b.addEventListener('click', (e) => {
    e.stopPropagation();
    const r = b.getBoundingClientRect();
    addMenu(r.left, r.bottom + 4, typeof src === 'function' ? src() : src, acts);
  });
  return b;
}
