// Application shell: sign-in (name and password), navigation, live refresh (server-sent events), status bar.
import { api, session } from './api.js';
import { settings, setLang, num, isoToTr } from './format.js';
import { h, clear, toast, errorToast, debounce, menu, closeMenu, modal, inFormControl, fitOneLine, watchWidth } from './ui.js';
import { configureGrid, clearSelection, findCell, selectionText, trackWrite } from './grid.js';
import { ViewPage } from './pages/view.js';
import { BlotterPage } from './pages/blotter.js';
import { TradesPage } from './pages/trades.js';
import { BrokerPage } from './pages/broker.js';
import { openStatus } from './status.js';
import { VolPage } from './pages/vol.js';
import { WatchPage } from './pages/watch.js';
import { HeatPage } from './pages/heat.js';
import { openAlarmDialog, addToWatch, checkAlarms } from './alarms.js';
import { followWarns } from './bonds.js';
import { ExplorerPage } from './pages/explorer.js';
import { EodPage, MpcPage, SpreadsPage, SettingsPage } from './pages/history.js';
import { FxPage } from './pages/fx.js';
import { FxVolPage } from './pages/fxvol.js';
import { PricingPage } from './pages/pricing.js';
import { SwaptionPage } from './pages/swaption.js';
import { openRetEditor } from './ret.js';
import { setupFind } from './find.js';
import { openSpotEditor } from './spot.js';
import { openScenarios } from './scenarios.js';
import { UsersPage } from './pages/users.js';
import { BackupPage } from './pages/backup.js';
import { loadHiddenColumns } from './columns.js';
import { onDecimalsChanged } from './decimals.js';
import { SocialPage } from './pages/social.js';
import { AgendaPage } from './pages/agenda.js';
import { setupDesk, startDesk, stopDesk, deskEvent, deskReconnected, paintNav as paintDeskNav } from './desk.js';
import { startPresence, stopPresence, presenceEvent } from './presence.js';
import { openRecon, checkBeforeArchive } from './recon.js';
import { quantPage, quantEvent } from './pages/quant.js';
import { DibsGenelPage } from './pages/dibsgenel.js';
import { KagitFiyatPage } from './pages/kagitfiyat.js';
import { FiyatYuklemePage } from './pages/fiyatyukleme.js';
import { BugunPage } from './pages/bugun.js';
import { parseCommand, fold } from './commands.js';
import { runCommand, fillTradesForm, waitFor, TRADING_LIST } from './commandrun.js';
import { openAddIsin } from './bonds.js';
import { LaunchpadPage, PopPanelPage } from './pages/launchpad.js';
import { hub } from './boxes.js';
import { Drawer } from './drawer.js';
import { loadLayout, clearLayout, onLayout, launchpads, favs, toggleFav, landing, setLanding, pinToDrawer, addMenu, compact,
  setCompact } from './layout.js';
import './pageboxes.js';                          // (the boxes of the dashboard's own pages join the launchpad's kinds)
import { boxEvent, PopBoxPage, popBoxHash, popBoxItem } from './pagebox.js';
import { paintMenu, menuChanged, openedPage, pageTabs, editMenu } from './menu.js';
import { showProgress, openProgress } from './hesap.js';
import { setupProp, stopProp } from './prop.js';

const $ = (id) => document.getElementById(id);
const state = { pages: [], page: null, pageId: null, gen: 0, refreshing: false, dirty: false, users: {}, status: null,
  online: true, booted: false, pending: 0, chatMissing: 0, behind: false, headerGen: 0, headerAs: null, popKey: null };

// A window of its own (``#/pop/<page>/<table>``, ``#/pop/launchpad/<name>``): a light shell - no menu, no header strip,
// no alarms or desktop notifications (those are the main window's), the live stream shared with the other tabs.
const POP = /^#\/?pop\//.test(window.location.hash || '');

function store(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, value);
  } catch (e) { /* storage unavailable */ }
  return null;
}

const ctx = {
  refreshNow: () => { runRefresh(); pollStatus(); },
  /** The latest generation the server announced (a panel drawn from an older one is not up to date). */
  gen: () => state.gen,
  /** Bring the page up to date now (a tab opened whose panels were not, while another was). */
  refreshPage: () => { runRefresh(); },
  setInputs: (book, items) => trackWrite(api.post('/api/inputs', { book, items, adhoc: false, lenient: false })),
  displayName: (key) => state.users[key] || key || '',
  openRet: (opts) => openRetEditor(ctx, opts),
  /** "Open the form with these values": a trade to enter, its fields filled from a quote (a matrix row, a chat line, a
   *  price right-clicked) - Günlük İşlemler opens with them and saves nothing (the spec: BlotterPage.takePrefill).  In a
   *  window of its own, the main window's form. */
  openTrade: (spec) => {
    if (POP) { tradeInMain(spec); return; }
    try { sessionStorage.setItem('tto.trade.prefill', JSON.stringify(spec)); } catch (e) { /* ignore */ }
    if (state.pageId === 'blotter' && state.page && state.page.takePrefill) state.page.takePrefill();
    else window.location.hash = '#/blotter';
  },
  /** Open a page and bring one of its panels into view (the workbook's "go to" hyperlinks). */
  goto: (pageId, panelId) => {
    const hash = '#/' + pageId + (panelId ? '?p=' + encodeURIComponent(panelId) : '');
    if (window.location.hash === hash) route();
    else window.location.hash = hash;
  },
  /** The desk's trades of the broker chat next to Günlük İşlemler (a day, a period; today when none is given). */
  openRecon: (date, to) => openRecon(ctx, date, to),
  /** Before the day's archive: the desk's chat trades not in the blotter, if any - true when it is to be downloaded. */
  checkArchive: (date, to) => checkBeforeArchive(ctx, date, to),
  /** The title of the page (a launchpad names the one on screen). */
  setTitle: (text) => {
    $('page-title').textContent = text;
    document.title = text + ' · TTO Masa';
  },
  /** A table pinned to the side drawer (which opens to show it). */
  pinToDrawer: (src) => pinToDrawer(src).then(() => { if (drawer) drawer.setOpen(true); }, () => {}),
  /** "+ Launchpad"'s menu for a table shown elsewhere (the drawer). */
  addToLaunchpadMenu: (box) => {
    const r = box.el.getBoundingClientRect();
    addMenu(r.left + 20, r.top + 30, Object.assign({}, box.item, { id: undefined }), { pop: (src) => openPop(src) });
  },
  /** A table, or a launchpad, in a window of its own. */
  popOut: (src) => openPop(src),
  popLaunchpad: (name) => openWindow('#/pop/launchpad/' + encodeURIComponent(name), 'tto-pop-lp-' + name),
  /** Another launchpad: its own address (back / forward, a bookmark). */
  openLaunchpad: (name) => { window.location.hash = '#/launchpad/' + encodeURIComponent(name); },
  /** "Elle değer" (on every page while the tab is open): what is on screen elsewhere follows. */
  handMode: () => { try { return sessionStorage.getItem('tto.adhoc') === '1'; } catch (e) { return false; } },
  handChanged: (on) => {
    hub.setAdhoc(on);
    if (drawer) drawer.hand(on);
  },
  /** In a window of its own, a table's page opens in the main window. */
  gotoSource: POP ? (view, panel) => openInMain('#/' + view + (panel ? '?p=' + encodeURIComponent(panel) : '')) : null,
  /** A page opened (when it is not on screen) and ready: the page, or null after ``ms``. */
  pageReady: (id, ms = 20000) => {
    if (state.pageId !== id) ctx.goto(id);
    return waitFor(() => (state.pageId === id && state.page && state.page.ready ? state.page : null), ms);
  },
  /** Ctrl+K "trade …": the Trades page's "Yeni işlem" form filled as the user would type it - nothing saved. */
  openTradesForm: async (spec) => {
    const page = await ctx.pageReady('trades');
    if (!page || !page.openForm) { toast('Trades sayfası açılamadı', 'err'); return; }
    page.openForm(null);
    await fillTradesForm(spec || {});
  },
  /** Ctrl+K "kâğıt ekle …": the trading list's "+ ISIN ekle" with these ISINs in it - "Ekle" is the user's. */
  openAddIsin: (isins) => openAddIsin(ctx, Object.assign({ values: isins || [] }, TRADING_LIST)),
  /** How many account requests wait (the badge on "Kullanıcılar" in the menu). */
  setPending: (n) => {
    state.pending = n || 0;
    const item = document.querySelector('#nav .nav-item[data-page="users"]');
    if (!item) return;
    const old = item.querySelector('.nav-count');
    if (old) old.remove();
    if (state.pending) item.appendChild(h('span', { class: 'nav-count', title: 'Onay bekleyen hesap isteği' }, String(state.pending)));
  },
};

/** "N işlem girilmedi" on Broker Chat in the menu: today's trades of the desk said in the chat and not in Günlük
 * İşlemler (from the status).  A click opens their list, wherever one is. */
function setChatMissing(n) {
  state.chatMissing = n || 0;
  const item = document.querySelector('#nav .nav-item[data-page="broker"]');
  if (!item) return;
  const old = item.querySelector('.nav-count.chat');
  if (old) old.remove();
  if (!state.chatMissing) return;
  const badge = h('span', { class: 'nav-count chat', id: 'nav-chat-missing', role: 'button',
    title: state.chatMissing + ' işlem chat\'te var, Günlük İşlemler\'de yok – listeyi açmak için tıklayın' },
  h('b', null, String(state.chatMissing)), h('span', { class: 'txt' }, ' işlem girilmedi'));
  badge.addEventListener('click', (e) => { e.preventDefault(); e.stopPropagation(); openRecon(ctx).catch(errorToast); });
  item.appendChild(badge);
}

// ---------------------------------------------------------------------- sign-in
// One card, three forms: sign in; ask for an account (an administrator approves it); and - while the dashboard has
// no administrator, on the dashboard's own computer only - create the first administrator.
const signin = { mode: 'login' };

function setLoginMode(mode) {
  signin.mode = mode;
  const ask = mode === 'request';
  const setup = mode === 'setup';
  $('login-title').textContent = setup ? 'İlk yönetici hesabı' : ask ? 'Hesap isteği' : 'Giriş';
  $('login-hint').textContent = setup
    ? 'Bu dashboard\'un henüz yöneticisi yok. Yönetici hesabınızın adını ve şifresini belirleyin – bu adım yalnızca '
      + 'dashboard\'un çalıştığı bilgisayardan yapılabilir.'
    : ask
      ? 'İsminizi ve bir şifre yazın; bir yönetici onaylayınca bu isim ve şifreyle girersiniz. Daha önce isminizle giriyorduysanız '
        + 'aynı ismi yazın: girdileriniz ve senaryolarınız korunur.'
      : 'İsminiz ve şifrenizle girin.';
  $('login-pass').setAttribute('autocomplete', mode === 'login' ? 'current-password' : 'new-password');
  $('login-pass2').classList.toggle('hidden', mode === 'login');
  $('login-note').classList.toggle('hidden', !ask);
  $('login-submit').textContent = setup ? 'Yönetici hesabını oluştur' : ask ? 'İsteği gönder' : 'Giriş';
  $('login-switch').textContent = ask ? 'Hesabınız var mı? Giriş yapın' : 'Hesabınız yok mu? Hesap isteyin';
  $('login-switch').parentElement.classList.toggle('hidden', setup);
  $('login-err').textContent = '';
  $('login-ok').textContent = '';
}

async function showLogin(message) {
  session.user = null;
  session.display = null;
  session.role = null;
  events.stop();
  stopDesk();
  stopPresence();
  stopProp();                                          // (the Prop panel: closed, what was typed forgotten)
  dropKept();
  if (state.page) { state.page.destroy(); state.page = null; state.pageId = null; }
  if (drawer) drawer.stop();
  clearLayout();
  scenarios.names = null;                              // (Ctrl+K's: the next user's own)
  scenarios.at = 0;
  $('app').classList.add('hidden');
  // the card is ready at once; what is typed into it while the server answers stays (a busy server answers late)
  setLoginMode('login');
  $('login-err').textContent = message || '';
  $('login-pass').value = '';
  $('login-pass2').value = '';
  const name = $('login-name');
  if (!name.value) name.value = store('tto.user') || '';
  $('login').classList.remove('hidden');
  (name.value ? $('login-pass') : name).focus();
  let st = { user: null, setup: false, local: false };
  try { st = await api.get('/api/auth'); } catch (e) { /* the form still works; the server says what is wrong */ }
  if (st.user) { await enter(st.user); return; }               // still signed in (this browser's session is valid)
  if (st.setup && st.local) setLoginMode('setup');
  else if (st.setup && !message) {
    $('login-err').textContent = 'Bu dashboard\'un henüz yöneticisi yok: ilk yönetici, dashboard\'un çalıştığı bilgisayardaki '
      + 'tarayıcıdan oluşturulur.';
  }
}

async function submitLogin() {
  const mode = signin.mode;
  const name = $('login-name').value.trim();
  const password = $('login-pass').value;
  $('login-err').textContent = '';
  $('login-ok').textContent = '';
  if (!name) { $('login-err').textContent = 'İsminizi yazın'; $('login-name').focus(); return; }
  if (!password) { $('login-err').textContent = 'Şifrenizi yazın'; $('login-pass').focus(); return; }
  if (mode !== 'login' && password !== $('login-pass2').value) {
    $('login-err').textContent = 'İki şifre aynı değil';
    $('login-pass2').focus();
    return;
  }
  const btn = $('login-submit');
  btn.disabled = true;
  try {
    if (mode === 'request') {
      const res = await api.post('/api/account-request', { name, password, note: $('login-note').value });
      store('tto.user', res.display);
      setLoginMode('login');
      $('login-pass').value = '';
      $('login-pass2').value = '';
      $('login-note').value = '';
      $('login-ok').textContent = 'İsteğiniz yöneticiye iletildi. Onaylanınca bu isim ve şifreyle girebilirsiniz.';
      return;
    }
    const res = await api.post(mode === 'setup' ? '/api/setup' : '/api/login', { name, password });
    store('tto.user', res.display);
    $('login-pass').value = '';
    $('login-pass2').value = '';
    await enter(res);
    if (mode === 'setup') toast('Yönetici hesabınız oluşturuldu. Kullanıcılar: Araçlar → Kullanıcılar.', 'ok', 6000);
  } catch (err) {
    $('login-err').textContent = err.message;
  } finally {
    btn.disabled = false;
  }
}

async function signOut() {
  try { await api.post('/api/logout'); } catch (e) { /* signed out on this side either way */ }
  showLogin('');
}

function openPasswordDialog() {
  const m = modal({ title: 'Şifremi değiştir', width: 420 });
  const field = (label, auto) => {
    const input = h('input', { class: 'inp', type: 'password', autocomplete: auto, style: { width: '100%' } });
    m.body.appendChild(h('div', { class: 'field' }, h('label', null, label), input));
    return input;
  };
  const old = field('Mevcut şifre', 'current-password');
  const a = field('Yeni şifre (en az 8 karakter)', 'new-password');
  const b = field('Yeni şifre (tekrar)', 'new-password');
  const err = h('div', { class: 'errtxt' });
  m.body.appendChild(err);
  const save = async () => {
    if (a.value !== b.value) { err.textContent = 'İki yeni şifre aynı değil'; b.focus(); return; }
    try {
      await api.post('/api/password', { old: old.value, new: a.value });
      m.close();
      toast('Şifreniz değişti', 'ok');
    } catch (e) { err.textContent = e.message; }
  };
  b.addEventListener('keydown', (e) => { if (e.key === 'Enter') save(); });
  m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Vazgeç'));
  m.foot.appendChild(h('button', { class: 'btn primary', type: 'button', onclick: save }, 'Kaydet'));
  old.focus();
}

async function enter(me) {
  session.user = me.user;
  session.display = me.display;
  session.role = me.role;
  state.pending = me.pending || 0;
  state.headerGen = 0;
  $('login').classList.add('hidden');
  $('app').classList.remove('hidden');
  $('user-name').textContent = me.display;
  $('user-av').textContent = (me.display.trim()[0] || '?').toLocaleUpperCase('tr');
  const hiddenColumns = loadHiddenColumns();          // the columns this user hid: in hand before a table is drawn
  const own = loadLayout();                            // launchpads, the drawer, favourites, the landing page
  const [nav, status, users] = await Promise.all([api.get('/api/nav'), api.get('/api/status'), api.get('/api/users')]);
  await hiddenColumns;
  await own;
  state.pages = nav.pages;
  for (const u of users.users) state.users[u.name] = u.display;
  applyStatus(status);
  state.gen = status.gen || 0;                         // (a generation heard later than this one: a change)
  if (!POP) checkAlarms();                           // (what fired before: not again)
  buildNav();
  events.start();
  startPresence(POP);                                // (who is online: the chip; this window's input is told)
  if (!POP) {
    startDesk();
    loadHeader().catch(() => {});
    drawer.start();
    paintFavs();
    // opened without an address: the user's own landing page (a page, or one of their launchpads)
    const land = landing();
    if (land && !/^#\/?[^/?]/.test(window.location.hash || '')) {
      const path = land.startsWith('launchpad/') ? 'launchpad/' + encodeURIComponent(land.slice(10)) : land;
      history.replaceState(null, '', '#/' + path);
    }
  }
  route();
  if (me.role === 'admin' && state.pending) {
    toast(state.pending + ' hesap isteği onay bekliyor (Araçlar → Kullanıcılar)', '', 6000);
  }
}

// ---------------------------------------------------------------------- navigation
function buildNav() {
  // (menu.js: the launchpads first, the groups, quant's pages as four entries with tabs, the user's own menu)
  paintMenu($('nav'), state.pages, session.role === 'admin', state.pageId);
  ctx.setPending(state.pending);
  paintDeskNav();
  setChatMissing(state.chatMissing);
}

function pageTitle(id) {
  if (id === 'launchpad') return 'Launchpad';
  if (id === 'explorer') return 'Sayfa gezgini';
  if (id === 'users') return 'Kullanıcılar';
  if (id === 'backup') return 'Yedekleme';
  const p = state.pages.find((x) => x.id === id);
  return p ? p.title : id;
}

/** The address: "#/ois?p=B4" -> {parts: ['ois'], query}; "#/launchpad/Sabah" -> ['launchpad', 'Sabah'] (each part decoded:
 *  a launchpad's name may hold a slash). */
function parseHash() {
  const raw = (window.location.hash || '').replace(/^#\/?/, '');
  const cut = raw.indexOf('?');
  const path = cut < 0 ? raw : raw.slice(0, cut);
  const parts = path.split('/').map((x) => { try { return decodeURIComponent(x); } catch (e) { return x; } });
  return { parts, query: new URLSearchParams(cut < 0 ? '' : raw.slice(cut + 1)) };
}

function route() {
  if (POP) { routePop(); return; }
  // "#/ois" opens a page, "#/ois?p=B4" also brings that panel into view; "#/launchpad/<name>" one of the user's launchpads
  const { parts, query } = parseHash();
  let id = parts[0] || '';
  let sub = id === 'launchpad' ? parts.slice(1).join('/') || null : null;
  const panel = query.get('p');
  const admin = session.role === 'admin';
  const known = id === 'launchpad' || ((id === 'explorer' || id === 'users' || id === 'backup') && admin) || state.pages.some((p) => p.id === id);
  if (!known) {
    id = state.pages.some((p) => p.id === 'masa') ? 'masa' : (state.pages[0] ? state.pages[0].id : (admin ? 'explorer' : 'masa'));
    sub = null;
  }
  if (id !== state.pageId) openPage(id, panel, sub);
  else if (id === 'launchpad' && sub && state.page && state.page.select) state.page.select(sub);
  else if (panel && state.page && state.page.ready && state.page.focusPanel) state.page.focusPanel(panel);
}

// ---------------------------------------------------------------------- the last pages opened, kept
// A page of tables (a workbook page, the launchpad) is not destroyed when another is opened: the last KEEP stay as they
// are - their tab, their search, their scroll - out of the document, and come back at once (brought up to date then).
// The dashboard's own pages (blotter, broker chat, quant ...) are made again each time, as before.
const KEEP = 4;
const kept = new Map();                  // page id -> {page, host, scroll}; the oldest first

function dropKept() {
  for (const k of kept.values()) if (k.page !== state.page) k.page.destroy();
  kept.clear();
}

/** The page on screen goes out of view: kept (out of the document, its scroll noted) or destroyed. */
function leavePage() {
  const page = state.page;
  if (!page) return;
  const k = kept.get(state.pageId);
  if (k && k.page === page && page.ready) {
    k.scroll = $('content').scrollTop;
    k.host.remove();
  } else {
    if (k && k.page === page) kept.delete(state.pageId);
    page.destroy();
  }
  state.page = null;
}

/** The pages opened lately, the latest first (Ctrl+K lists them; a reload of the tab keeps them). */
const recent = (() => {
  try { const v = JSON.parse(sessionStorage.getItem('tto.recent') || '[]'); return Array.isArray(v) ? v.slice(0, 8) : []; } catch (e) { return []; }
})();
function noteRecent(id) {
  const i = recent.indexOf(id);
  if (i >= 0) recent.splice(i, 1);
  recent.unshift(id);
  if (recent.length > 8) recent.length = 8;
  try { sessionStorage.setItem('tto.recent', JSON.stringify(recent)); } catch (e) { /* storage unavailable */ }
}

async function openPage(id, panel, sub) {
  leavePage();
  clearSelection();
  state.pageId = id;
  store('tto.page', id);
  noteRecent(id);
  openedPage($('nav'), id, state.pages);
  paintDeskNav();
  paintFavs();
  $('page-title').textContent = pageTitle(id);
  document.title = pageTitle(id) + ' · TTO Masa';
  const content = clear($('content'));
  const back = kept.get(id);
  if (back && back.page.ready) {
    // back in view as it was left: the tab, the search, the scroll; what changed meanwhile comes now - under the tabs of
    // its menu entry, when it is one of them (DİBS RV's sheets: a page kept, the strip drawn again over it)
    kept.delete(id);
    kept.set(id, back);
    const backTabs = pageTabs(id, state.pages);
    if (backTabs) content.appendChild(backTabs);
    content.appendChild(back.host);
    content.scrollTop = back.scroll || 0;
    state.page = back.page;
    if (back.page.revive) back.page.revive(sub);
    runRefresh();
    if (panel && back.page.focusPanel) back.page.focusPanel(panel);
    return;
  }
  if (back) { kept.delete(id); back.page.destroy(); }
  content.scrollTop = 0;
  // a page that is kept gets a host of its own (out of the document while another is on screen); the others draw
  // into #content itself, as before
  const keepable = id === 'launchpad' || !(state.pages.find((p) => p.id === id) || { custom: true }).custom;
  const tabs = pageTabs(id, state.pages);          // a page of a menu entry with tabs (quant's Faiz …): the tabs over it
  if (tabs) content.appendChild(tabs);
  const host = keepable || tabs ? content.appendChild(h('div', { class: 'pagehost' })) : content;
  let page;
  if (id === 'launchpad') page = new LaunchpadPage(host, ctx, { name: sub });
  else if (id === 'blotter') page = new BlotterPage(host, ctx);
  else if (id === 'trades') page = new TradesPage(host, ctx);
  else if (id === 'broker') page = new BrokerPage(host, ctx);
  else if (id === 'vol') page = new VolPage(host, ctx);
  else if (id === 'watch') page = new WatchPage(host, ctx);
  else if (id === 'heat') page = new HeatPage(host, ctx);
  else if (id === 'explorer') page = new ExplorerPage(host, ctx);
  else if (id === 'users') page = new UsersPage(host, ctx);
  else if (id === 'backup') page = new BackupPage(host, ctx);
  else if (id === 'eod') page = new EodPage(host, ctx);
  else if (id === 'mpc') page = new MpcPage(host, ctx);
  else if (id === 'spreads') page = new SpreadsPage(host, ctx);
  else if (id === 'settings') page = new SettingsPage(host, ctx);
  else if (id === 'fx') page = new FxPage(host, ctx);
  else if (id === 'fxvol') page = new FxVolPage(host, ctx);
  else if (id === 'fiyatlama') page = new PricingPage(host, ctx);
  else if (id === 'swaption') page = new SwaptionPage(host, ctx);
  else if (id === 'social') page = new SocialPage(host, ctx);
  else if (id === 'agenda') page = new AgendaPage(host, ctx);
  else if (id === 'quant' || id.startsWith('quant-')) page = quantPage(id, host, ctx);
  else if (id === 'dibs-genel') page = new DibsGenelPage(host, ctx);
  else if (id === 'kagit-fiyat') page = new KagitFiyatPage(host, ctx);
  else if (id === 'fiyat-yukleme') page = new FiyatYuklemePage(host, ctx);
  else if (id === 'bugun') page = new BugunPage(host, ctx);
  else page = new ViewPage(host, id, ctx);
  state.page = page;
  if (page.keepAlive && host !== content) {
    kept.set(id, { page, host, scroll: 0 });
    while (kept.size > KEEP) {
      const [oldest, k] = kept.entries().next().value;
      kept.delete(oldest);
      if (k.page !== state.page) k.page.destroy();
    }
  }
  try {
    await page.load();
    page.ready = true;
    if (panel && state.page === page && page.focusPanel) page.focusPanel(panel);
  } catch (err) {
    const k = kept.get(id);
    if (k && k.page === page) kept.delete(id);
    if (state.page !== page) { page.destroy(); return; }
    clear(host);
    const retry = h('button', { class: 'btn', type: 'button' }, 'Tekrar dene');
    retry.addEventListener('click', () => { state.pageId = null; openPage(id, null, sub); });
    host.appendChild(h('div', { class: 'banner' }, 'Sayfa yüklenemedi: ' + err.message + ' ', retry));
  }
}

// ---------------------------------------------------------------------- a window of its own
function openWindow(hash, name) {
  const w = window.open('/' + hash, String(name).replace(/[^A-Za-z0-9_-]/g, '_').slice(0, 80), 'popup=yes,width=980,height=680');
  if (!w) toast('Tarayıcı ayrı pencereyi engelledi: bu adres için açılır pencerelere izin verin', 'err', 7000);
  else w.focus();
  return w;
}

/** A table (with its part, its name) in a window of its own: "#/pop/<page>/<table>?part={rows, cols, all, title}". */
function openPop(src) {
  if (src.type && src.type !== 'table') return openWindow(popBoxHash(src), 'tto-pop-' + popBoxHash(src));      // a box of a page
  const part = {};
  if (src.rows && src.rows.length) part.rows = src.rows;
  if (src.cols && src.cols.length) part.cols = src.cols;
  if (src.all) part.all = true;
  if (src.title) part.title = src.title;
  const q = Object.keys(part).length ? '?part=' + encodeURIComponent(JSON.stringify(part)) : '';
  return openWindow('#/pop/' + encodeURIComponent(src.view) + '/' + encodeURIComponent(src.panel) + q,
    'tto-pop-' + src.view + '-' + src.panel + (q ? '-' + Date.now().toString(36) : ''));
}

/** From a window of its own: a trade filled in the main window's Günlük İşlemler (the one that opened it, while it is
 *  there), else in a new tab (it starts with a copy of this window's session storage). */
function tradeInMain(spec) {
  const main = window.opener && !window.opener.closed ? window.opener : null;
  try {
    if (main && main.tto && main.tto.openTrade) { main.tto.openTrade(spec); main.focus(); return; }
  } catch (e) { /* not reachable: a new tab */ }
  try { sessionStorage.setItem('tto.trade.prefill', JSON.stringify(spec)); } catch (e) { /* ignore */ }
  window.open('/#/blotter', '_blank');
}

/** From a window of its own: a page in the main window (the one that opened it, while it is there). */
function openInMain(hash) {
  const main = window.opener && !window.opener.closed ? window.opener : null;
  if (main) {
    try { main.location.hash = hash; main.focus(); return; } catch (e) { /* not reachable: a new tab */ }
  }
  window.open('/' + hash, '_blank');
}

function routePop() {
  const key = window.location.hash;
  if (state.page && state.popKey === key) return;
  state.popKey = key;
  if (state.page) { state.page.destroy(); state.page = null; }
  const { parts, query } = parseHash();
  const host = clear($('content'));
  let page = null;
  if (parts[1] === 'launchpad' && parts.length > 2) {
    state.pageId = 'launchpad';
    page = new LaunchpadPage(host, ctx, { pop: true, name: parts.slice(2).join('/') });
  } else if (parts[1] === 'calc' && parts[2]) {          // a calc sheet of the user's (calc.js): "#/pop/calc/<sheet>?t=<name>"
    state.pageId = 'pop';
    const item = { type: 'calc', id: 'pop', sheet: parts[2], w: 12, h: 'auto' };
    if (query.get('t')) item.title = query.get('t');
    page = new PopPanelPage(host, ctx, item);
  } else if (parts[1] === 'box' && parts[2]) {
    state.pageId = 'pop';
    page = new PopBoxPage(host, ctx, popBoxItem(parts[2], query));
  } else if (parts[1] && parts[2]) {
    let part = {};
    try { part = JSON.parse(query.get('part') || '{}') || {}; } catch (e) { part = {}; }
    const item = { type: 'table', id: 'pop', view: parts[1], panel: parts[2], w: 12, h: 'auto' };
    if (Array.isArray(part.rows) && part.rows.length) item.rows = part.rows;
    if (Array.isArray(part.cols) && part.cols.length) item.cols = part.cols;
    if (part.all) item.all = true;
    if (typeof part.title === 'string' && part.title) item.title = part.title;
    state.pageId = 'pop';
    page = new PopPanelPage(host, ctx, item);
  }
  ctx.setTitle('TTO');
  if (!page) {
    host.appendChild(h('div', { class: 'banner' }, 'Bu pencerede gösterilecek bir tablo yok.'));
    return;
  }
  state.page = page;
  page.load().then(() => { page.ready = true; }).catch((err) => {
    if (state.page !== page) return;
    clear(host);
    host.appendChild(h('div', { class: 'banner' }, 'Yüklenemedi: ' + err.message));
  });
}

// ---------------------------------------------------------------------- Ctrl+K commands: what they are read against
const scenarios = { names: null, at: 0, asking: false };

/** The pages (the administrators' too, for them), the user's launchpads and saved scenarios - these asked for when a
 *  "senaryo" command is typed and what was read is 30 s old (``onRead``: the box reads the text again with them). */
function commandEnv(text, onRead) {
  if (/^\s*sen/.test(fold(text)) && !scenarios.asking && Date.now() - scenarios.at > 30000) {
    scenarios.asking = true;
    api.get('/api/scenarios').then((r) => {
      scenarios.names = (r.scenarios || []).map((s) => s.name);
      scenarios.at = Date.now();
      onRead();
    }, () => {}).finally(() => { scenarios.asking = false; });
  }
  const admin = session.role === 'admin';
  const own = admin ? [['explorer', 'Sayfa gezgini'], ['users', 'Kullanıcılar'], ['backup', 'Yedekleme']].map(([id, title]) => ({ id, title, group: 'Araçlar' })) : [];
  return { pages: (state.pages || []).concat(own), launchpads: launchpads().map((l) => l.name), scenarios: scenarios.names };
}

// ---------------------------------------------------------------------- favourite pages (★), the landing page
// (one line of the top bar: the ones past its end behind "+N", a menu of them - the desk, 27.11.2026)
let favChips = [];
let favMore = null;
const fitFavs = () => { if (favMore && favMore.isConnected) fitOneLine($('favs'), favChips, favMore); };

function paintFavs() {
  const box = $('favs');
  if (!box) return;
  clear(box);
  const mine = favs().filter((id) => id === 'launchpad' || state.pages.some((p) => p.id === id)
    || (session.role === 'admin' && (id === 'explorer' || id === 'users' || id === 'backup')));
  favChips = [];
  for (const id of mine) {
    const a = h('a', { class: 'fav' + (id === state.pageId ? ' on' : ''), href: '#/' + id, title: pageTitle(id) }, pageTitle(id));
    a.dataset.page = id;
    box.appendChild(a);
    favChips.push(a);
  }
  favMore = h('button', { class: 'fav-more hidden', type: 'button', id: 'favs-more', title: 'Diğer favorileriniz' });
  favMore.addEventListener('click', () => {
    const r = favMore.getBoundingClientRect();
    menu(r.left, r.bottom + 4, favChips.filter((a) => a.classList.contains('ovfl'))
      .map((a) => ({ label: a.textContent, action: () => { window.location.hash = '#/' + a.dataset.page; } })));
  });
  box.appendChild(favMore);
  box.classList.toggle('hidden', !mine.length);
  fitFavs();
  const star = $('btn-fav');
  const on = !!state.pageId && favs().includes(state.pageId);
  star.textContent = on ? '★' : '☆';
  star.classList.toggle('on', on);
  star.title = on ? 'Favorilerinizden çıkarın (üst şerit)' : 'Bu sayfayı üst şeritteki favorilerinize ekleyin';
}

/** "Açılış sayfası": the page (or launchpad) the dashboard opens on when no address is given. */
function openLandingDialog() {
  const m = modal({ title: 'Açılış sayfası', width: 440 });
  const sel = h('select', { class: 'inp', id: 'landing-select', style: { width: '100%' } });
  sel.appendChild(h('option', { value: '' }, 'Varsayılan (Masa)'));
  // the morning screen offered first (bugun.js): what wants attention, on one page
  if (state.pages.some((p) => p.id === 'bugun')) sel.appendChild(h('option', { value: 'bugun' }, 'Bugün · sabah ekranı'));
  const lps = launchpads();
  if (lps.length) {
    const g = h('optgroup', { label: 'Launchpad\'leriniz' });
    for (const lp of lps) g.appendChild(h('option', { value: 'launchpad/' + lp.name }, lp.name));
    sel.appendChild(g);
  }
  const g = h('optgroup', { label: 'Sayfalar' });
  for (const p of state.pages) if (p.id !== 'bugun') g.appendChild(h('option', { value: p.id }, p.title + (p.group ? ' · ' + p.group : '')));
  sel.appendChild(g);
  sel.value = landing();
  if (sel.value !== landing()) sel.value = '';
  m.body.appendChild(h('p', { class: 'muted', style: { margin: '0 0 10px' } }, 'Dashboard\'u adres yazmadan (yalnızca sunucunun adresiyle) açtığınızda '
    + 'gelen sayfa. Hesabınızla saklanır: girdiğiniz her bilgisayarda aynı.'));
  m.body.appendChild(sel);
  m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Vazgeç'));
  m.foot.appendChild(h('button', { class: 'btn primary', type: 'button', id: 'landing-save', onclick: () => {
    const v = sel.value;
    const label = sel.options[sel.selectedIndex] ? sel.options[sel.selectedIndex].text : '';
    m.close();
    setLanding(v).then(() => toast(v ? 'Açılış sayfanız: ' + label : 'Açılış sayfası: Masa', 'ok'), () => {});
  } }, 'Kaydet'));
  sel.focus();
}

// ---------------------------------------------------------------------- live refresh
async function runRefresh() {
  // a browser tab that is not in view does not ask: it catches up when it is looked at again
  if (document.hidden) { state.behind = true; return; }
  if (state.refreshing) { state.dirty = true; return; }
  state.refreshing = true;
  try {
    do {
      state.dirty = false;
      const page = state.page;
      const jobs = POP ? [] : [loadHeader()];
      if (page && page.ready) jobs.push(page.refresh());
      // the boxes of the side drawer (and of a launchpad being opened): one request for all of them - a launchpad's
      // or a pop-out's own refresh is that request (asked for once, not twice)
      if (!(page && page.ready && page.usesHub)) jobs.push(hub.refresh());
      await Promise.all(jobs);
    } while (state.dirty);
  } catch (err) {
    if (!err.network && err.status !== 401) console.warn('refresh failed', err);
  } finally {
    state.refreshing = false;
  }
}

// ---------------------------------------------------------------------- one live stream per browser
// Every tab used to keep its own stream of generations (EventSource): a browser opens at most 6 connections to one
// server (HTTP/1.1), so the 7th tab of the dashboard waited for nothing.  One tab in view keeps the stream and passes
// each generation on to the others (BroadcastChannel); which one is agreed through localStorage (the dashboard is
// plain HTTP on the desk's network: Web Locks need HTTPS).  A tab out of view never takes the stream and hands it to
// one in view; with every tab out of view one of them keeps it (alarms still come).  A browser without BroadcastChannel or
// localStorage: each tab its own stream, closed while the tab is out of view.
const LEAD_KEY = 'tto.events.lead';
const LEAD_MS = 3500;                                // a leader not heard of for this long is gone

function readLead() {
  try { return JSON.parse(localStorage.getItem(LEAD_KEY) || 'null'); } catch (e) { return null; }
}

function writeLead(v) {
  try { localStorage.setItem(LEAD_KEY, JSON.stringify(v)); } catch (e) { /* storage unavailable */ }
}

/** A generation heard (from this tab's stream or another tab's). */
function onGen(gen) {
  setOnline(true);
  if (typeof gen !== 'number' || gen === state.gen) return;
  state.gen = gen;
  runRefresh();
  if (!POP) checkAlarms();                 // (a window of its own leaves alarms and notifications to the main one)
}

/** The stream is back (after the server or the network was gone): what changed meanwhile, once. */
function onBack() {
  if (!state.online) {
    api.get('/api/status').then(applyStatus).catch(() => {});
    runRefresh();
  }
  setOnline(true);
}

const events = {
  id: Math.random().toString(36).slice(2) + Date.now().toString(36),
  es: null,
  chan: null,
  timer: null,
  leading: false,
  shared: false,

  start() {
    this.stop();
    let storage = false;
    try { localStorage.setItem(LEAD_KEY + '.t', '1'); localStorage.removeItem(LEAD_KEY + '.t'); storage = true; } catch (e) { storage = false; }
    this.shared = storage && typeof window.BroadcastChannel === 'function';
    if (!this.shared) { if (!document.hidden) this.open(); return; }
    this.chan = new BroadcastChannel('tto-events');
    this.chan.onmessage = (e) => {
      const m = e.data || {};
      if (typeof m.gen === 'number') { onGen(m.gen); boxEvent(m); if (!POP) { deskEvent(m.desk); quantEvent(m.quant); presenceEvent(m.presence); } }
      else if (m.online === false) setOnline(false);
      else if (m.online === true) { if (!POP) deskReconnected(); onBack(); }
      else if (m.decimals) runRefresh();         // (the user's decimals changed in another tab: its tables come whole)
    };
    this.timer = setInterval(() => this.tick(), 1000);
    window.addEventListener('pagehide', this.bye);
    this.tick();
  },

  /** Every second: the leader says it is still there; a tab in view takes the stream when nobody (in view) has it. */
  tick() {
    const now = Date.now();
    const cur = readLead();
    if (this.leading) {
      if (cur && cur.id !== this.id && cur.until > now) { this.lead(false); return; }      // another tab took it
      writeLead({ id: this.id, until: now + LEAD_MS, hidden: document.hidden });
      return;
    }
    // a tab in view takes the stream when nobody has it or its holder is out of view; a tab out of view only when
    // nobody (in view) took it for a while - so that alarms still come with every tab out of view
    const take = document.hidden ? (!cur || cur.until < now - LEAD_MS) : (!cur || cur.until < now || cur.hidden);
    if (take) {
      writeLead({ id: this.id, until: now + LEAD_MS, hidden: document.hidden });
      setTimeout(() => {                                // two tabs at once: the one written last leads
        const c = readLead();
        if (!this.leading && this.chan && c && c.id === this.id) this.lead(true);
      }, 150);
    }
  },

  lead(on) {
    this.leading = on;
    if (on) this.open(); else this.close();
  },

  open() {
    this.close();
    const es = new EventSource('/api/events');
    this.es = es;
    es.onmessage = (e) => {
      let msg = null;
      try { msg = JSON.parse(e.data); } catch (x) { return; }
      if (this.chan) this.chan.postMessage({ gen: msg.gen, desk: msg.desk, quant: msg.quant, broker: msg.broker, presence: msg.presence });
      onGen(msg.gen);
      boxEvent(msg);                       // the boxes of the quant pages: the results' version (a window of its own too)
      if (POP) return;
      deskEvent(msg.desk);                 // the chat, the reports, the agenda: their own counters (no new generation)
      quantEvent(msg.quant);               // the quant signals: a new result, a signal alert
      presenceEvent(msg.presence);         // who is online: the chip's counts, the open list when somebody's state changed
    };
    es.onerror = () => {
      if (this.chan) this.chan.postMessage({ online: false });
      setOnline(false);
    };
    es.onopen = () => {
      if (this.chan) this.chan.postMessage({ online: true });
      if (!POP) deskReconnected();         // (its first counters: news of everything)
      onBack();
    };
  },

  close() {
    if (this.es) { this.es.close(); this.es = null; }
  },

  /** A word to the dashboard's other tabs and windows of this browser (no generation: ``{decimals: true}``). */
  tell(msg) {
    if (!this.chan) return;
    try { this.chan.postMessage(msg); } catch (e) { /* closed meanwhile */ }
  },

  /** The tab came into view or went out of it. */
  visible() {
    if (!session.user) return;
    if (!this.shared) {
      if (document.hidden) this.close();
      else if (!this.es) this.open();
      return;
    }
    this.tick();
  },

  bye: () => {
    const cur = readLead();
    if (events.leading && cur && cur.id === events.id) {
      try { localStorage.removeItem(LEAD_KEY); } catch (e) { /* storage unavailable */ }
    }
  },

  stop() {
    if (this.timer) { clearInterval(this.timer); this.timer = null; }
    this.bye();
    this.close();
    this.leading = false;
    if (this.chan) { this.chan.close(); this.chan = null; }
    window.removeEventListener('pagehide', this.bye);
  },
};

function setOnline(on) {
  if (state.online === on) return;
  state.online = on;
  applyStatus(state.status);
}

function applyStatus(status) {
  if (!status) return;
  state.status = status;
  if (typeof status.chat_missing === 'number' && status.chat_missing !== state.chatMissing) setChatMissing(status.chat_missing);
  const badge = $('mode-badge');
  badge.classList.remove('live', 'replay', 'slow', 'stale');
  // how fresh the prices are (the server works it out: the helper's heartbeat, the age of the last tick in market hours)
  const feed = (status.ops && status.ops.feed) || {};
  if (!state.online) {
    $('mode-text').textContent = 'Bağlantı yok';
    badge.title = 'Sunucuya ulaşılamıyor – yeniden bağlanılıyor';
  } else if (status.mode === 'live') {
    const p = status.provider || {};
    if (p.connected === false) {
      $('mode-text').textContent = 'Bloomberg bağlantısı yok';
      badge.title = (p.error || 'Bloomberg bağlantısı koptu') + ' – yeniden bağlanılıyor';
    } else if (feed.state === 'stale' || feed.state === 'silent') {
      // prices that stopped must not look live: "as of" the last tick (or the helper's last word)
      badge.classList.add('live', 'stale');
      $('mode-text').textContent = 'BAYAT VERİ · ' + (feed.as_of || '—') + ' itibarıyla';
      badge.title = (feed.reason || 'Veri akmıyor') + (p.error ? ' · ' + p.error : '')
        + ' · ayrıntı için tıklayın';
    } else {
      badge.classList.add('live');
      // Bloomberg says its event queue is filling up: prices may arrive late (and are asked again if any were dropped);
      // Bloomberg's own daily limit, or the dashboard's daily budget used up: nothing new is asked, the streams flow
      const capped = !!p.bbg_limit || (p.tier || 0) >= 2;
      if (p.slow || capped) badge.classList.add('slow');
      $('mode-text').textContent = p.bbg_limit ? 'CANLI · Bloomberg limiti doldu' : capped ? 'CANLI · günlük bütçe doldu'
        : p.slow ? 'CANLI · Bloomberg kuyruğu doluyor'
          : p.pending ? 'CANLI · ' + p.pending + ' veri bekleniyor' : 'CANLI · Bloomberg';
      const used = p.budget ? Math.round(100 * (p.hits_today || 0) / p.budget) : null;
      badge.title = 'Bloomberg (blpapi) canlı veri · ' + (p.subscriptions || 0) + ' abonelik'
        + (p.subscriptions_invalid ? ' (' + p.subscriptions_invalid + ' ticker Bloomberg\'de yok: abone olunmadı – hangileri olduğu için tıklayın)' : '')
        + ' · bugün ' + (p.hits_today || 0) + ' veri isteği' + (used !== null ? ' (günlük bütçenin %' + used + '\'i)' : '')
        + (p.quiet ? ' · sorgu saatleri dışında: yenileme yok, abonelikler akıyor' : '')
        + (p.isolated ? ' · oturum ayrı süreçte' + (p.restarts ? ' (' + p.restarts + ' kez yeniden başladı)' : '') : ' · oturum dashboard sürecinde')
        + (p.events_dropped || p.messages_lost
          ? ' · KUYRUK TAŞTI: ' + (p.events_dropped || p.messages_lost) + ' olay düştü, ' + (p.resyncs || 0) + ' değer yeniden istendi' : '')
        + (p.bbg_limit ? ' · BLOOMBERG GÜNLÜK LİMİTİ DOLDU – yarın yeniden; son değerler gösteriliyor'
          : p.limit_reached ? ' · GÜNLÜK LİMİT KORUMASI DEVREDE' : '') + (p.error ? ' · ' + p.error : '');
      // past 70 % of the day's budget, or Bloomberg's own limit: the administrators hear it once a day (this browser)
      if (session.role === 'admin' && (p.bbg_limit || (p.tier || 0) >= 1)) {
        const mark = 'tto.bbg-warned.' + (status.server_date || '') + (p.bbg_limit ? '.limit' : (p.tier >= 2 ? '.full' : '.70'));
        let told = false;
        try { told = !!localStorage.getItem(mark); localStorage.setItem(mark, '1'); } catch (e) { told = !!state[mark]; state[mark] = true; }
        if (!told) {
          toast(p.bbg_limit ? 'Bloomberg günlük limiti doldu – yarın yeniden. Yeni istek gönderilmiyor, son değerler gösteriliyor (rozete tıklayın).'
            : p.tier >= 2 ? 'Günlük Bloomberg bütçesi doldu (%' + used + '): yeni istek gönderilmiyor (rozete tıklayın: nereye gittiği).'
              : 'Günlük Bloomberg bütçesinin %' + used + '\'i kullanıldı: artık yalnızca sayfaların hiç almadığı ilk değerler isteniyor (rozete tıklayın).',
          'err', 15000);
        }
      }
    }
  } else {
    badge.classList.add('replay');
    $('mode-text').textContent = 'KAYITLI VERİ';
    badge.title = status.note || 'Excel dosyasındaki son kayıtlı piyasa verisiyle çalışıyor';
  }
  // (the word goes below 1500 px: the date stays, its title says what it is)
  clear($('asof'));
  if (status.today) $('asof').append(h('span', { class: 'lbl' }, 'Değerleme: '), isoToTr(status.today));
  $('asof').title = status.today ? 'Değerleme tarihi: ' + isoToTr(status.today) : '';
  // RET curve freshness: typed by the desk, so remind when it was not loaded today
  const ret = status.ret;
  const fresh = !!(ret && ret.updated_at && status.server_date && ret.updated_at.slice(0, 10) === status.server_date);
  $('btn-ret').classList.toggle('stale', !fresh);
  $('btn-ret').title = ret && ret.updated_at
    ? 'RET faizleri · son yükleme ' + ret.updated_at + (ret.updated_by ? ' (' + ctx.displayName(ret.updated_by) + ')' : '')
      + (fresh ? '' : ' – bugün güncellenmedi')
    : 'RET faizleri bugün yüklenmedi – dosyadaki eski değerler kullanılıyor. Tıklayıp Excel\'den yapıştırın.';
  // the fair value RET differs from the published one: "RET güncellemesi var: 1M, 2M" - a pill on the RET button, its
  // tenors (a click opens the fair value tab)
  const ups = (status.ret_fair && status.ret_fair.updates) || [];
  $('ret-upd').classList.toggle('hidden', !ups.length);
  $('ret-upd').textContent = ups.length ? '↻ ' + (ups.length > 3 ? ups.slice(0, 3).join(', ') + ' +' + (ups.length - 3) : ups.join(', ')) : '';
  $('ret-upd').title = ups.length ? 'RET güncellemesi var: ' + ups.join(', ') + ' – adil değer yayınlanandan farklı. Bakmak ve "Kopyala ve yayınla" için tıklayın.' : '';
  $('foot-ver').textContent = 'port ' + status.port;
  // a long calculation under way (the quant fit, the ML models, the backtest, the history sync): "Hesap" in the top bar
  if (status.progress && !POP) showProgress(status.progress);
  if (status.note && !state.noteShown) {
    state.noteShown = true;
    toast(status.note, 'err', 9000);
  }
  // the database file failed its check at the start: everyone hears it once (the badge's window says more)
  const chk = status.ops && status.ops.db && status.ops.db.check;
  if (chk && chk.ok === false && !state.dbShown) {
    state.dbShown = true;
    toast('Veritabanı denetimi başarısız: ' + (chk.problems || []).slice(0, 2).join('; ') + ' – yöneticiye haber verin (ayrıntı: rozete tıklayın).', 'err', 20000);
  }
}

function pollStatus() {
  if (!session.user || document.hidden) return;
  api.get('/api/status').then(applyStatus).catch(() => {});
}

/** "Eğri: PPK basamak" in the top bar while the user's TRY curves are read the PPK way (Ayarlar → Eğri interpolasyonu):
 * their own setting - colleagues on Bootstrap see other numbers.  Nothing on Bootstrap (the header says nothing of it). */
function paintInterp(info) {
  const b = $('interp-badge');
  if (!b) return;
  b.classList.toggle('hidden', !info);
  if (!info) return;
  $('interp-text').textContent = info.label || 'Eğri: PPK basamak';
  b.title = (info.tip || '') + '\nTıklayın: Ayarlar → Eğri interpolasyonu';
  b.classList.toggle('warn', !info.on);
}

async function loadHeader() {
  // only when it changed since the strip was drawn (the same strip for everybody without inputs of their own)
  const res = await api.get('/api/header', state.headerGen ? { since: state.headerGen, as: state.headerAs } : null);
  state.headerAs = res.as;
  if (res.unchanged) return;
  state.headerGen = res.gen || 0;
  paintInterp(res.interp);
  const box = $('kpis');
  const items = res.items || [];
  if (box.children.length !== items.length) {
    clear(box);
    for (const it of items) {
      const el = h('div', { class: 'kpi' }, h('div', { class: 'l' }, it.label), h('div', { class: 'v' }, it.text));
      if (it.edit === 'spot') {                       // the manual spot of the VİOP sheet: typed from any page
        el.classList.add('edit');
        el.id = 'kpi-spot';
        el.tabIndex = 0;
        el.setAttribute('role', 'button');
        el.title = 'Manuel spot gir / Bloomberg spotuna dön';
        el.addEventListener('click', () => openSpotEditor(ctx));
        el.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); openSpotEditor(ctx); } });
      }
      box.appendChild(el);
    }
    return;
  }
  items.forEach((it, i) => {
    const el = box.children[i];
    el.firstChild.textContent = it.label;
    if (el.lastChild.textContent !== it.text) el.lastChild.textContent = it.text;
  });
}

// ---------------------------------------------------------------------- status bar
let cellTicket = 0;
const fetchCell = debounce(async (book, ref, ticket, copy) => {
  try {
    const info = await api.get('/api/cell', copy ? { book, ref, copy } : { book, ref });
    if (ticket !== cellTicket) return;
    // (an input typed as a formula: its formula, as Excel's formula bar shows it)
    let text = (info.input && info.input.formula) || info.formula || '';
    if (!text && info.cell) text = info.cell.t || '';
    const inp = info.input;
    if (inp && inp.copy) {
      // a cell of a temporary copy: its own value, the table's, or read-only there (why)
      text += (text ? '   ·   ' : '') + 'kopya ' + inp.copy + ' · ' + (inp.readonly ? 'salt okunur – ' + inp.readonly
        : inp.own ? 'kopyanın kendi girdisi' : 'tablonun değerini izliyor') + (inp.label ? ' – ' + inp.label : '');
    } else if (inp) text += (text ? '   ·   ' : '') + (inp.scope === 'shared' ? 'ortak girdi' : 'kişisel girdi')
      + (inp.label ? ' – ' + inp.label : '') + (inp.error ? '   ·   ' + inp.error : '');
    // a two-way table's cell (tto/twoway.py): what was typed in its row, if anything
    const tw = inp && inp.twoway;
    if (tw) text += '   ·   iki yönlü: ' + (!tw.anchor ? 'satırda yazılan yok (varsayılan)'
      : tw.anchor.ref === info.ref ? 'yazdığınız değer' : 'yazılan ' + tw.anchor.member + ' · ' + tw.anchor.ref + ', bu ondan hesaplanır');
    $('sb-fx').textContent = text;
    $('sb-fx').title = text;
  } catch (e) { /* the formula bar is informative only */ }
}, 140);

function onSelect(info) {
  cellTicket += 1;
  if (!info) {
    $('sb-addr').textContent = '—';
    $('sb-fx').textContent = '';
    $('sb-stat').textContent = '';
    return;
  }
  $('sb-addr').textContent = info.label || (info.rows + ' × ' + info.cols);
  clear($('sb-stat'));
  if (info.n > 1) {
    $('sb-stat').appendChild(h('span', null, 'Toplam ', h('b', null, num(info.sum, 4)), '  ·  Ortalama ', h('b', null, num(info.avg, 4)),
      '  ·  Adet ', h('b', null, String(info.n))));
  }
  if (info.single && info.book && info.focusRef) {
    $('sb-fx').textContent = info.cell ? (info.cell.ff || info.cell.t || '') : '';
    fetchCell(info.book, info.focusRef, cellTicket, info.copy);
  } else {
    fetchCell.cancel();
    $('sb-fx').textContent = info.rows + ' satır × ' + info.cols + ' sütun seçili';
  }
}

// ---------------------------------------------------------------------- boot
/** Changed cells flash green / red for a moment; some find it tiring: it can be turned off (per browser; the user's menu). */
function applyFlash(on) {
  document.body.classList.toggle('noflash', !on);
}

/** The light / dark theme (per browser; the user's menu). */
function toggleTheme() {
  const cur = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
  const next = cur === 'light' ? 'dark' : 'light';
  document.documentElement.setAttribute('data-theme', next);
  store('tto.theme', next);
}

/** The number format: 1.234,56 (Turkish Excel) or 1,234.56 (English) - every page drawn again in it (the user's menu). */
function toggleLang() {
  setLang(settings.lang === 'en' ? 'tr' : 'en');
  store('tto.lang', settings.lang);
  toast(settings.lang === 'en' ? 'Sayı biçimi: 1,234.56 (İngilizce Excel)' : 'Sayı biçimi: 1.234,56 (Türkçe Excel)', '', 2600);
  const id = state.pageId;
  const sub = id === 'launchpad' && state.page && state.page.name ? state.page.name : null;
  dropKept();                                     // (the pages kept were drawn in the other format)
  if (POP) { state.popKey = null; route(); return; }
  state.pageId = null;
  state.headerGen = 0;                            // (another number format: the whole strip again)
  loadHeader().catch(() => {});
  if (id) openPage(id, null, sub);
}

/** "Sıkışık görünüm" (the user menu): rows shorter and text a step smaller in every table - app.css does it all from one
 *  class on <html>.  Kept with the layout, so another computer, and every window of this browser, follows at once. */
function applyCompact() {
  document.documentElement.classList.toggle('compact', compact());
}

let drawer = null;

function boot() {
  if (state.booted) return;
  state.booted = true;
  if (POP) $('app').classList.add('pop');
  else drawer = new Drawer(ctx);
  setLang(store('tto.lang') || 'tr');
  applyFlash(store('tto.flash') !== '0');
  if (store('tto.nav') === '1') $('app').classList.add('nav-collapsed');

  session.onUnauthorized = () => { showLogin('Oturumunuz sona erdi – tekrar giriş yapın.'); };
  const after = (res) => {
    runRefresh();
    // ISINs of a list of bonds changed: what the rows held went with their bonds (moved / gone) and - the trading list -
    // what the DİBS ASW list and Tüm Kâğıtlar did with it, said once
    const said = [res && res.follow && res.follow.text, res && res.row_values && res.row_values.text].filter(Boolean);
    if (said.length) toast(said.join(' · '), followWarns(res) ? 'warn' : 'ok', 9000);
    return res;
  };
  configureGrid({
    // a temporary copy of a table (copy: its id) takes what is typed into its own inputs
    setInputs: (book, items, adhoc, lenient, copy) => (copy
      ? api.post('/api/copies/inputs', { copy, items, lenient: !!lenient })
      : api.post('/api/inputs', { book, items, adhoc: !!adhoc, lenient: !!lenient })).then(after),
    paste: (book, anchor, text, adhoc) => api.post('/api/paste', { book, anchor, text, adhoc: !!adhoc }).then(after),
    reset: (book, refs, shared, copy) => (copy
      ? api.post('/api/copies/reset', { copy, refs })
      : api.post('/api/reset', { book, refs, shared: !!shared })).then(after),
    // right click on a cell: watch it, or set an alarm on it
    watch: (book, ref, label) => addToWatch(ctx, { book, ref, label }),
    alarm: (book, ref, label, text) => openAlarmDialog(ctx, { book, ref, label, text }),
    // ... on a price: the server reads the row's instrument and dates, Günlük İşlemler opens with the trade filled
    trade: (price) => api.post('/api/trade/prefill', price).then((res) => ctx.openTrade(res.spec), errorToast),
    onSelect,
  });
  // this user's own decimals changed (a table's right click): the tables on screen come again - whole, the server's mark
  // of the setting changed - here and in the other tabs / windows of this browser
  onDecimalsChanged(() => { runRefresh(); events.tell({ decimals: true }); });

  $('login-form').addEventListener('submit', (e) => { e.preventDefault(); submitLogin(); });
  $('login-switch').addEventListener('click', (e) => {
    e.preventDefault();
    setLoginMode(signin.mode === 'request' ? 'login' : 'request');
    $('login-name').focus();
  });
  $('mode-badge').addEventListener('click', () => openStatus(state.status).catch(errorToast));
  $('interp-badge').addEventListener('click', () => ctx.goto('settings', 'interp'));
  $('hesap-ind').addEventListener('click', () => openProgress());
  if (!POP) setupProp();                            // "Prop": the calculator and the prop risk, on every page
  // the favourites on one line: fitted again whenever the room left for them changes - the window, the title, a badge or
  // "Hesap" coming and going (each of them watched: the bar itself keeps its width meanwhile)
  if (window.ResizeObserver) {
    const ro = new ResizeObserver(() => fitFavs());
    for (const id of ['top', 'page-title', 'favs', 'mode-badge', 'interp-badge', 'asof', 'desk-alarm', 'hesap-ind']) if ($(id)) ro.observe($(id));
  } else watchWidth($('top'), fitFavs);
  $('btn-collapse').addEventListener('click', () => {
    const on = $('app').classList.toggle('nav-collapsed');
    store('tto.nav', on ? '1' : '0');
  });
  $('btn-ret').addEventListener('click', () => openRetEditor(ctx));
  const openFair = (e) => { e.stopPropagation(); e.preventDefault(); openRetEditor(ctx, { tab: 'fair' }); };
  $('ret-upd').addEventListener('click', openFair);
  $('ret-upd').addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') openFair(e); });
  const finder = setupFind($('findbox'), () => state.pages || [], (page, panel) => ctx.goto(page, panel), {
    recent: () => recent.filter((id) => id !== state.pageId).map((id) => ({ id, title: pageTitle(id) })),
    add: (src, x, y) => addMenu(x, y, src, { pin: ctx.pinToDrawer, pop: ctx.popOut }),
    pin: (src) => ctx.pinToDrawer(src),
    // Ctrl+K commands (commands.js): read from the text alone - the user's saved scenarios asked for once a while
    commands: (text) => parseCommand(text, commandEnv(text, () => finder.refresh())),
    run: (c) => runCommand(c, ctx).catch(errorToast),
  });
  $('btn-scen').addEventListener('click', () => openScenarios(ctx));
  setupDesk({ page: () => state.page, pageId: () => state.pageId, where: () => ({ id: state.pageId, title: pageTitle(state.pageId) }) });
  $('btn-user').addEventListener('click', (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    menu(r.left, r.bottom + 4, [
      { header: session.display + (session.role === 'admin' ? ' · yönetici' : '') },
      { label: 'Launchpad\'lerim', action: () => { window.location.hash = '#/launchpad'; } },
      { label: 'Açılış sayfası…', action: () => openLandingDialog() },
      { label: 'Menüyü düzenle…', action: () => editMenu(state.pages, session.role === 'admin') },
      { check: true, id: 'menu-compact', on: compact(), label: 'Sıkışık görünüm',
        title: 'Satırlar daha alçak, yazılar bir boy küçük: bir ekrana daha çok tablo sığar. Hesabınızla saklanır.',
        action: (on) => {
          setCompact(on).catch(() => {                // (not saved: back as it is kept - the page and the tick box)
            const box = document.getElementById('menu-compact');
            if (box) box.checked = compact();
          });
        } },
      // (the top bar's 1.234,56 / ⚡ / ◐ until 27.11.2026: set once, so here - the bar stays one row on a laptop)
      { check: true, id: 'btn-lang', on: settings.lang === 'en', label: 'İngilizce sayı biçimi (1,234.56)',
        title: 'Sayılar 1,234.56 biçiminde okunur, gösterilir ve kopyalanır (İngilizce Excel); kapalıyken 1.234,56 (Türkçe Excel). '
          + 'Bu tarayıcıda saklanır.',
        action: () => { closeMenu(); toggleLang(); } },
      { check: true, id: 'btn-flash', on: !document.body.classList.contains('noflash'), label: 'Değişen hücreler yanıp sönsün',
        title: 'Değişen hücre bir an yeşil / kırmızı yanar; kapalıyken değer sessizce değişir. Bu tarayıcıda saklanır.',
        action: (on) => {
          store('tto.flash', on ? '1' : '0');
          applyFlash(on);
        } },
      { check: true, id: 'btn-theme', on: document.documentElement.getAttribute('data-theme') === 'light', label: 'Açık tema',
        title: 'Açık / koyu tema. Bu tarayıcıda saklanır.', action: () => { toggleTheme(); } },
      { label: 'Senaryolarım', action: () => openScenarios(ctx) },
      { label: 'Şifremi değiştir', action: () => openPasswordDialog() },
    ].concat(session.role === 'admin' ? [{ label: 'Kullanıcılar', action: () => { window.location.hash = '#/users'; } }] : [],
      [{ sep: true }, { label: 'Çıkış', action: () => signOut() }]));
  });
  $('btn-fav').addEventListener('click', () => {
    if (!state.pageId || POP) return;
    const id = state.pageId;
    const on = !favs().includes(id);
    toggleFav(id).then(() => toast(on ? '"' + pageTitle(id) + '" üst şeritteki favorilerinizde' : '"' + pageTitle(id) + '" favorilerden çıktı', 'ok', 2200), () => {});
  });
  onLayout(() => {
    applyCompact();                                 // (a window of its own too: the same tables)
    if (POP) return;
    paintFavs();
    if (menuChanged()) buildNav();                  // (the user's own menu changed: here, in another window, on another computer)
  });
  // Alt+← / Alt+→: the page before / after (the last ones opened come back at once, as they were left); Alt+Y: the drawer
  document.addEventListener('keydown', (e) => {
    if (!session.user || POP || !e.altKey || e.ctrlKey || e.metaKey || inFormControl(e.target)) return;      // (in a box of text: the browser's)
    if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault();
      if (e.key === 'ArrowLeft') history.back(); else history.forward();
    } else if ((e.key === 'y' || e.key === 'Y') && !e.shiftKey && drawer) {
      e.preventDefault();
      drawer.toggle();
    }
  });
  window.addEventListener('hashchange', () => { if (session.user) route(); });
  // back in view: what changed meanwhile is asked for once
  document.addEventListener('visibilitychange', () => {
    if (!session.user) return;
    events.visible();
    if (!document.hidden && state.behind) { state.behind = false; runRefresh(); }
  });
  setInterval(pollStatus, 15000);

  showLogin('');                                     // straight in when this browser's session is still valid
}

// small debugging / testing surface
// (a cell of a tab that is not open is found as well: the page opens its tab; the side drawer is looked at last - the
// same cell may be on the page and in the drawer)
function findCellAnywhere(ref) {
  return findCell(ref, document, $('drawer')) || (state.page && state.page.findCell ? state.page.findCell(ref) : null)
    || findCell(ref, $('drawer'));
}

// (a cell of a temporary copy: under the copy's own element - a selector, or the element - never found from the document)
const copyCell = (where, ref) => {
  const root = typeof where === 'string' ? document.querySelector(where) : where;
  return root ? findCell(ref, root) : null;
};

window.tto = { findCell: findCellAnywhere, copyCell, selectionText, state, events, refresh: () => runRefresh(), hub, pop: POP,
  kept: () => [...kept.keys()], drawer: () => drawer, openTrade: (spec) => ctx.openTrade(spec), progress: showProgress };

boot();
