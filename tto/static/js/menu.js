// The menu on the left: the pages in their groups (the server's /api/nav, in the menu's order - tto/navmenu.py, the
// desk's reorganization of 28.11.2026), the pages of one menu entry as its tabs (a page of the nav names its entry:
// ``menu``, ``menu_title``, ``tab``; İşlemler is Günlük İşlemler · Trades · Broker Chat, quant's Sinyaller its seven
// pages …) - and each user's own menu: the entries they took out of it ("Menüyü düzenle…", kept with the account:
// layout.hidden_pages).  A page keeps its own address (#/mpc opens OIS · PPK on "PPK geçmişi"), an entry with tabs leads
// to its tab opened last; a page out of the menu still opens from Ctrl+K and from a link.  Every entry says what it is in
// one line (its hint: the tooltip).  A group's title folds it (remembered per user in this browser; Araçlar folded until
// opened): a folded group still shows the page on screen and an entry with a count (Sosyal's messages, Ajanda's late
// items, Broker Chat's trades not entered - on the entry that holds the page: navItemOf).
import { h, clear, modal, toast } from './ui.js';
import { session } from './api.js';
import { hiddenPages, setHiddenPages } from './layout.js';

const ADMIN_PAGES = [
  { id: 'explorer', title: 'Sayfa gezgini', hint: 'Sayfa gezgini — çalışma kitaplarının bütün sayfaları (yöneticiler)' },
  { id: 'users', title: 'Kullanıcılar', hint: 'Kullanıcılar — hesaplar ve hesap istekleri (yöneticiler)' },
  { id: 'backup', title: 'Yedekleme', hint: 'Yedekleme — veritabanının yedekleri (yöneticiler)' }];
const TAB_KEY = 'tto.menu.tab.';
const FOLD_KEY = 'tto.menu.fold.';
/** The groups folded until the user opens them (the desk, 28.11.2026: Araçlar last and folded). */
export const FOLD_DEFAULT = new Set(['Araçlar']);
let painted = null;                       // the hidden entries the menu on screen was drawn with

/** The entries of a group's pages: a page, or one entry for the pages that name the same ``menu`` (its tabs). */
function entries(pages) {
  const out = [];
  const byMenu = new Map();
  for (const p of pages) {
    if (!p.menu) { out.push({ id: p.id, title: p.title, hint: p.hint || '' }); continue; }
    let e = byMenu.get(p.menu);
    if (!e) {
      e = { id: p.menu, title: p.menu_title || p.title, hint: p.menu_hint || '', tabs: [] };
      byMenu.set(p.menu, e);
      out.push(e);
    }
    e.tabs.push({ id: p.id, title: p.tab || p.title, hint: p.hint || '' });
  }
  return out;
}

/** The menu as groups of entries, [{group, entries: [{id, title, hint, tabs?}]}]: the user's launchpads first, then the
 *  server's groups in its order (Araçlar last), the administrators' pages for them only. */
export function menuModel(pages, admin) {
  const groups = new Map();
  for (const p of pages) {
    const g = p.group || 'Diğer';
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g).push(p);
  }
  if (admin) {
    if (!groups.has('Araçlar')) groups.set('Araçlar', []);
    groups.get('Araçlar').push(...ADMIN_PAGES);   // the sheet explorer, the accounts, the backup
  }
  if (groups.has('Araçlar')) {                    // (last, whatever came after it)
    const tools = groups.get('Araçlar');
    groups.delete('Araçlar');
    if (tools.length) groups.set('Araçlar', tools);
  }
  const out = [{ group: null, entries: [{ id: 'launchpad', title: 'Launchpad', hint: 'Launchpad — kendi tablo sayfalarınız' }] }];
  for (const [group, list] of groups) out.push({ group, entries: entries(list) });
  return out;
}

/** Whether this user folded a group of the menu (in this browser); a group never chosen: its default. */
export function groupFolded(group) {
  let v = null;
  try { v = localStorage.getItem(FOLD_KEY + (session.user || '') + '.' + group); } catch (e) { v = null; }
  return v === '1' || (v !== '0' && FOLD_DEFAULT.has(group));
}

function setGroupFolded(group, on) {
  try { localStorage.setItem(FOLD_KEY + (session.user || '') + '.' + group, on ? '1' : '0'); } catch (e) { /* not kept */ }
}

/** A group's title folds it and opens it again (a click, Enter or Space); its entries' count is said while it is folded. */
function foldable(box, title, group, n) {
  title.setAttribute('role', 'button');
  title.tabIndex = 0;
  title.dataset.n = String(n);
  const set = (on) => {
    box.classList.toggle('folded', on);
    title.setAttribute('aria-expanded', String(!on));
    title.title = group + (on ? ': ' + n + ' giriş - açmak için tıklayın' : ': daraltmak için tıklayın');
  };
  set(groupFolded(group));
  const flip = () => { const on = !box.classList.contains('folded'); setGroupFolded(group, on); set(on); };
  title.addEventListener('click', flip);
  title.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); flip(); } });
}

/** The menu entry with tabs a page is one of (null: a page of its own). */
export function menuEntryOf(id, pages) {
  const p = pages.find((x) => x.id === id);
  if (!p || !p.menu) return null;
  return entries(pages.filter((x) => x.menu === p.menu))[0];
}

/** The tab of an entry opened last in this browser (its first one before that). */
export function lastTab(entry) {
  let id = null;
  try { id = localStorage.getItem(TAB_KEY + entry.id); } catch (e) { id = null; }
  return entry.tabs.some((t) => t.id === id) ? id : entry.tabs[0].id;
}

/** Whether an entry is out of this user's menu: its id taken out - or, for an entry whose pages were entries of their
 *  own before (28.11.2026), every one of its pages taken out then. */
export function entryHidden(e, out) {
  return out.has(e.id) || (!!e.tabs && e.tabs.length > 0 && e.tabs.every((t) => out.has(t.id)));
}

/** The line of the menu that leads to a page: its own entry, or the entry it is a tab of (null: not in the menu). */
export function navItemOf(id, root) {
  const nav = root || document.getElementById('nav');
  if (!nav) return null;
  const esc = String(id).replace(/["\\]/g, '\\$&');
  return nav.querySelector('.nav-item[data-page="' + esc + '"]') || nav.querySelector('.nav-item[data-tabs~="' + esc + '"]');
}

/** An entry's tooltip: its hint, and its tabs. */
function entryTitle(e) {
  const tabs = e.tabs ? 'Sekmeler: ' + e.tabs.map((t) => t.title).join(' · ') : '';
  return [e.hint || e.title, tabs].filter(Boolean).join('\n');
}

/** Draw the menu into ``nav``: the user's hidden entries left out (a group with none left goes with them). */
export function paintMenu(nav, pages, admin, current) {
  clear(nav);
  const hidden = hiddenPages();
  const out = new Set(hidden);
  for (const { group, entries: list } of menuModel(pages, admin)) {
    const shown = list.filter((e) => !entryHidden(e, out));
    if (!shown.length) continue;
    const title = group ? h('div', { class: 'gt' }, group) : null;
    const box = h('div', { class: 'nav-group' + (group ? '' : ' nav-own') }, title);
    if (group) box.dataset.group = group;
    if (title) foldable(box, title, group, shown.length);
    for (const e of shown) {
      const a = h('a', { class: 'nav-item', href: '#/' + (e.tabs ? lastTab(e) : e.id), title: entryTitle(e) },
        h('span', { class: 'dot' }), h('span', { class: 'lbl' }, e.title));
      a.dataset.page = e.id;
      if (e.tabs) a.dataset.tabs = e.tabs.map((t) => t.id).join(' ');
      box.appendChild(a);
    }
    nav.appendChild(box);
  }
  painted = hidden.join('|');
  markMenu(nav, current);
}

/** Whether the user's hidden entries changed since the menu was drawn (another window, another computer). */
export function menuChanged() {
  return painted !== null && painted !== hiddenPages().join('|');
}

/** The entry of the page on screen lit (an entry with tabs: when the page is one of them). */
export function markMenu(nav, id) {
  for (const a of nav.querySelectorAll('.nav-item')) {
    a.classList.toggle('active', a.dataset.page === id || (!!a.dataset.tabs && a.dataset.tabs.split(' ').includes(id)));
  }
}

/** A page opened: its entry lit; a tab of an entry is remembered as the entry's last (the entry leads there now). */
export function openedPage(nav, id, pages) {
  const e = menuEntryOf(id, pages);
  if (e) {
    try { localStorage.setItem(TAB_KEY + e.id, id); } catch (x) { /* not kept */ }
    for (const a of nav.querySelectorAll('.nav-item')) if (a.dataset.page === e.id) a.href = '#/' + id;
  }
  markMenu(nav, id);
}

/** The tabs of a page whose menu entry has several (İşlemler, OIS · PPK, quant's Sinyaller …): a strip over the page -
 *  null otherwise.  Each tab's tooltip: its hint. */
export function pageTabs(id, pages) {
  const e = menuEntryOf(id, pages);
  if (!e) return null;
  const strip = h('div', { class: 'viewtabs pagetabs', id: 'page-tabs', role: 'tablist' });
  for (const t of e.tabs) {
    const b = h('button', { type: 'button', role: 'tab', class: t.id === id ? 'on' : null, title: t.hint || (e.title + ' › ' + t.title) }, t.title);
    b.dataset.page = t.id;
    b.addEventListener('click', () => { if (t.id !== id) window.location.hash = '#/' + t.id; });
    strip.appendChild(b);
  }
  return strip;
}

/** "Menüyü düzenle…": every entry of the menu with a tick; the ones not ticked leave this user's menu - Ctrl+K and links
 *  still open them.  Kept with the account (any computer shows the same menu). */
export function editMenu(pages, admin) {
  const was = hiddenPages();
  const wasSet = new Set(was);
  const m = modal({ title: 'Menüyü düzenle', width: 620 });
  m.box.classList.add('menu-edit');
  m.body.appendChild(h('p', { class: 'muted', style: { margin: '0 0 10px' } }, 'İşaretini kaldırdığınız sayfalar menünüzden çıkar; '
    + 'Ctrl+K ve bağlantılarla yine açılır. Hesabınızla saklanır: girdiğiniz her bilgisayarda aynı.'));
  const boxes = [];
  const groups = h('div', { class: 'menu-edit-groups', id: 'menu-edit' });
  for (const { group, entries: list } of menuModel(pages, admin)) {
    const sec = h('div', { class: 'menu-edit-group' }, h('div', { class: 'mh' }, group || 'Kendi sayfalarınız'));
    for (const e of list) {
      const b = h('input', { type: 'checkbox' });
      b.checked = !entryHidden(e, wasSet);
      b.dataset.page = e.id;
      boxes.push(b);
      sec.appendChild(h('label', { class: 'check', title: entryTitle(e) }, b,
        ' ' + e.title, e.tabs ? h('span', { class: 'muted' }, ' · ' + e.tabs.length + ' sekme') : null));
    }
    groups.appendChild(sec);
  }
  m.body.appendChild(groups);
  const all = h('button', { class: 'btn', type: 'button', id: 'menu-edit-all', title: 'Bütün sayfalar menüde' }, 'Hepsini göster');
  all.addEventListener('click', () => { for (const b of boxes) b.checked = true; });
  const save = h('button', { class: 'btn primary', type: 'button', id: 'menu-edit-save' }, 'Kaydet');
  save.addEventListener('click', () => {
    const listed = new Set(boxes.map((b) => b.dataset.page));
    const tabsOf = new Map();
    for (const { entries: list } of menuModel(pages, admin)) for (const e of list) if (e.tabs) tabsOf.set(e.id, e.tabs.map((t) => t.id));
    // (an entry this menu does not list - another version's page - stays as it was; a page that is a tab now goes with
    // its entry's tick: shown, its old mark goes too)
    const shown = new Set(boxes.filter((b) => b.checked).flatMap((b) => tabsOf.get(b.dataset.page) || []));
    const ids = was.filter((x) => !listed.has(x) && !shown.has(x)).concat(boxes.filter((b) => !b.checked).map((b) => b.dataset.page));
    m.close();
    const n = boxes.filter((b) => !b.checked).length;
    setHiddenPages([...new Set(ids)]).then(() => toast(n ? n + ' giriş menünüzden çıktı (Ctrl+K ile yine açılır)' : 'Bütün sayfalar menünüzde', 'ok', 3000), () => {});
  });
  m.foot.append(all, h('span', { class: 'grow' }), h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Vazgeç'), save);
}
