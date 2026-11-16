// The menu on the left: the pages in their groups (the server's /api/nav), the pages of one menu entry as its tabs - quant's
// fifteen pages are four entries, Sinyaller, Faiz, FX and VİOP (a page of the nav names its entry: ``menu``,
// ``menu_title``, ``tab``) - and each user's own menu: the entries they took out of it ("Menüyü düzenle…", kept with the
// account: layout.hidden_pages).  A page keeps its own address (#/quant-pca opens Faiz on "PCA / RV"), an entry with tabs
// leads to its tab opened last; a page out of the menu still opens from Ctrl+K and from a link.
import { h, clear, modal, toast } from './ui.js';
import { hiddenPages, setHiddenPages } from './layout.js';

const ADMIN_PAGES = [{ id: 'explorer', title: 'Sayfa gezgini' }, { id: 'users', title: 'Kullanıcılar' }, { id: 'backup', title: 'Yedekleme' }];
const TAB_KEY = 'tto.menu.tab.';
let painted = null;                       // the hidden entries the menu on screen was drawn with

/** The entries of a group's pages: a page, or one entry for the pages that name the same ``menu`` (its tabs). */
function entries(pages) {
  const out = [];
  const byMenu = new Map();
  for (const p of pages) {
    if (!p.menu) { out.push({ id: p.id, title: p.title }); continue; }
    let e = byMenu.get(p.menu);
    if (!e) {
      e = { id: p.menu, title: p.menu_title || p.title, tabs: [] };
      byMenu.set(p.menu, e);
      out.push(e);
    }
    e.tabs.push({ id: p.id, title: p.tab || p.title });
  }
  return out;
}

/** The menu as groups of entries, [{group, entries: [{id, title, tabs?}]}]: the user's launchpads first, the blotter right
 *  under the desk overview, the administrators' pages for them only. */
export function menuModel(pages, admin) {
  const groups = new Map();
  for (const p of pages) {
    const g = p.group || 'Diğer';
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g).push(p);
  }
  if (!groups.has('Araçlar')) groups.set('Araçlar', []);
  if (admin) groups.get('Araçlar').push(...ADMIN_PAGES);   // the sheet explorer, the accounts, the backup
  if (!groups.get('Araçlar').length) groups.delete('Araçlar');
  const masa = groups.get('Masa');
  if (masa) masa.sort((a, b) => (a.id === 'masa' ? -1 : b.id === 'masa' ? 1 : 0));
  const out = [{ group: null, entries: [{ id: 'launchpad', title: 'Launchpad', hint: 'Launchpad: kendi tablo sayfalarınız' }] }];
  for (const [group, list] of groups) out.push({ group, entries: entries(list) });
  return out;
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

/** Draw the menu into ``nav``: the user's hidden entries left out (a group with none left goes with them). */
export function paintMenu(nav, pages, admin, current) {
  clear(nav);
  const hidden = hiddenPages();
  const out = new Set(hidden);
  for (const { group, entries: list } of menuModel(pages, admin)) {
    const shown = list.filter((e) => !out.has(e.id));
    if (!shown.length) continue;
    const box = h('div', { class: 'nav-group' + (group ? '' : ' nav-own') }, group ? h('div', { class: 'gt' }, group) : null);
    for (const e of shown) {
      const a = h('a', { class: 'nav-item', href: '#/' + (e.tabs ? lastTab(e) : e.id), title: e.hint || e.title },
        h('span', { class: 'dot' }), h('span', { class: 'lbl' }, e.title));
      a.dataset.page = e.id;
      if (e.tabs) {
        a.dataset.tabs = e.tabs.map((t) => t.id).join(' ');
        a.title = e.title + ': ' + e.tabs.map((t) => t.title).join(', ');
      }
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

/** The tabs of a page whose menu entry has several (quant's Sinyaller, Faiz, FX): a strip over the page - null otherwise. */
export function pageTabs(id, pages) {
  const e = menuEntryOf(id, pages);
  if (!e) return null;
  const strip = h('div', { class: 'viewtabs pagetabs', id: 'page-tabs', role: 'tablist' });
  for (const t of e.tabs) {
    const b = h('button', { type: 'button', role: 'tab', class: t.id === id ? 'on' : null, title: e.title + ' › ' + t.title }, t.title);
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
      b.checked = !was.includes(e.id);
      b.dataset.page = e.id;
      boxes.push(b);
      sec.appendChild(h('label', { class: 'check', title: e.tabs ? 'Sekmeleri: ' + e.tabs.map((t) => t.title).join(', ') : null }, b,
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
    // (an entry this menu does not list - another version's page - stays as it was)
    const ids = was.filter((x) => !listed.has(x)).concat(boxes.filter((b) => !b.checked).map((b) => b.dataset.page));
    m.close();
    const n = boxes.filter((b) => !b.checked).length;
    setHiddenPages(ids).then(() => toast(n ? n + ' sayfa menünüzden çıktı (Ctrl+K ile yine açılır)' : 'Bütün sayfalar menünüzde', 'ok', 3000), () => {});
  });
  m.foot.append(all, h('span', { class: 'grow' }), h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Vazgeç'), save);
}
