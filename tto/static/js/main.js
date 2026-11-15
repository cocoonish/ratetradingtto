// Application shell: sign-in (name and password), navigation, live refresh (server-sent events), status bar.
import { api, session } from './api.js';
import { settings, setLang, num, isoToTr } from './format.js';
import { h, clear, toast, errorToast, debounce, menu, modal } from './ui.js';
import { configureGrid, clearSelection, findCell, selectionText } from './grid.js';
import { ViewPage } from './pages/view.js';
import { BlotterPage } from './pages/blotter.js';
import { BrokerPage } from './pages/broker.js';
import { openStatus } from './status.js';
import { VolPage } from './pages/vol.js';
import { WatchPage } from './pages/watch.js';
import { HeatPage } from './pages/heat.js';
import { openAlarmDialog, addToWatch, checkAlarms } from './alarms.js';
import { ExplorerPage } from './pages/explorer.js';
import { EodPage, MpcPage, SpreadsPage, SettingsPage } from './pages/history.js';
import { FxPage } from './pages/fx.js';
import { FxVolPage } from './pages/fxvol.js';
import { openRetEditor } from './ret.js';
import { setupFind } from './find.js';
import { openSpotEditor } from './spot.js';
import { openScenarios } from './scenarios.js';
import { UsersPage } from './pages/users.js';
import { BackupPage } from './pages/backup.js';
import { loadHiddenColumns } from './columns.js';
import { SocialPage } from './pages/social.js';
import { AgendaPage } from './pages/agenda.js';
import { setupDesk, startDesk, stopDesk, deskEvent, deskReconnected, paintNav as paintDeskNav } from './desk.js';
import { openRecon, checkBeforeArchive } from './recon.js';
import { quantPage, quantEvent } from './pages/quant.js';

const $ = (id) => document.getElementById(id);
const state = { pages: [], page: null, pageId: null, gen: 0, refreshing: false, dirty: false, users: {}, status: null,
  online: true, booted: false, pending: 0, chatMissing: 0, behind: false, headerGen: 0, headerAs: null };

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
  setInputs: (book, items) => api.post('/api/inputs', { book, items, adhoc: false, lenient: false }),
  displayName: (key) => state.users[key] || key || '',
  openRet: () => openRetEditor(ctx),
  /** A trade to enter, its fields filled from a quote (a matrix row, a chat line): opens Günlük İşlemler with them. */
  openTrade: (spec) => {
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
  if (state.page) { state.page.destroy(); state.page = null; state.pageId = null; }
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
  const [nav, status, users] = await Promise.all([api.get('/api/nav'), api.get('/api/status'), api.get('/api/users')]);
  await hiddenColumns;
  state.pages = nav.pages;
  for (const u of users.users) state.users[u.name] = u.display;
  applyStatus(status);
  state.gen = status.gen || 0;                         // (a generation heard later than this one: a change)
  checkAlarms();                                     // (what fired before: not again)
  buildNav();
  events.start();
  startDesk();
  loadHeader().catch(() => {});
  route();
  if (me.role === 'admin' && state.pending) {
    toast(state.pending + ' hesap isteği onay bekliyor (Araçlar → Kullanıcılar)', '', 6000);
  }
}

// ---------------------------------------------------------------------- navigation
function buildNav() {
  const nav = clear($('nav'));
  const groups = new Map();
  for (const p of state.pages) {
    const g = p.group || 'Diğer';
    if (!groups.has(g)) groups.set(g, []);
    groups.get(g).push(p);
  }
  if (!groups.has('Araçlar')) groups.set('Araçlar', []);
  if (session.role === 'admin') {                    // the sheet explorer, the accounts, the backup: administrators only
    groups.get('Araçlar').push({ id: 'explorer', title: 'Sayfa gezgini' });
    groups.get('Araçlar').push({ id: 'users', title: 'Kullanıcılar' });
    groups.get('Araçlar').push({ id: 'backup', title: 'Yedekleme' });
  }
  if (!groups.get('Araçlar').length) groups.delete('Araçlar');
  // the blotter belongs right under the desk overview
  const masa = groups.get('Masa');
  if (masa) masa.sort((a, b) => (a.id === 'masa' ? -1 : b.id === 'masa' ? 1 : 0));
  for (const [g, items] of groups) {
    const box = h('div', { class: 'nav-group' }, h('div', { class: 'gt' }, g));
    for (const p of items) {
      const a = h('a', { class: 'nav-item', href: '#/' + p.id, title: p.title }, h('span', { class: 'dot' }), h('span', { class: 'lbl' }, p.title));
      a.dataset.page = p.id;
      box.appendChild(a);
    }
    nav.appendChild(box);
  }
  ctx.setPending(state.pending);
  paintDeskNav();
  setChatMissing(state.chatMissing);
}

function pageTitle(id) {
  if (id === 'explorer') return 'Sayfa gezgini';
  if (id === 'users') return 'Kullanıcılar';
  if (id === 'backup') return 'Yedekleme';
  const p = state.pages.find((x) => x.id === id);
  return p ? p.title : id;
}

function route() {
  // "#/ois" opens a page, "#/ois?p=B4" also brings that panel into view
  const raw = (window.location.hash || '').replace(/^#\/?/, '');
  const cut = raw.indexOf('?');
  let id = decodeURIComponent(cut < 0 ? raw : raw.slice(0, cut));
  const panel = cut < 0 ? null : new URLSearchParams(raw.slice(cut + 1)).get('p');
  const admin = session.role === 'admin';
  const known = ((id === 'explorer' || id === 'users' || id === 'backup') && admin) || state.pages.some((p) => p.id === id);
  if (!known) id = state.pages.some((p) => p.id === 'masa') ? 'masa' : (state.pages[0] ? state.pages[0].id : (admin ? 'explorer' : 'masa'));
  if (id !== state.pageId) openPage(id, panel);
  else if (panel && state.page && state.page.ready && state.page.focusPanel) state.page.focusPanel(panel);
}

async function openPage(id, panel) {
  if (state.page) state.page.destroy();
  clearSelection();
  state.pageId = id;
  store('tto.page', id);
  for (const a of document.querySelectorAll('#nav .nav-item')) a.classList.toggle('active', a.dataset.page === id);
  paintDeskNav();
  $('page-title').textContent = pageTitle(id);
  document.title = pageTitle(id) + ' · TTO Masa';
  const host = clear($('content'));
  host.scrollTop = 0;
  let page;
  if (id === 'blotter') page = new BlotterPage(host, ctx);
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
  else if (id === 'social') page = new SocialPage(host, ctx);
  else if (id === 'agenda') page = new AgendaPage(host, ctx);
  else if (id === 'quant' || id.startsWith('quant-')) page = quantPage(id, host, ctx);
  else page = new ViewPage(host, id, ctx);
  state.page = page;
  try {
    await page.load();
    page.ready = true;
    if (panel && state.page === page && page.focusPanel) page.focusPanel(panel);
  } catch (err) {
    if (state.page !== page) return;
    clear(host);
    const retry = h('button', { class: 'btn', type: 'button' }, 'Tekrar dene');
    retry.addEventListener('click', () => { state.pageId = null; openPage(id); });
    host.appendChild(h('div', { class: 'banner' }, 'Sayfa yüklenemedi: ' + err.message + ' ', retry));
  }
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
      const jobs = [loadHeader()];
      if (page && page.ready) jobs.push(page.refresh());
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
  checkAlarms();
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
      if (typeof m.gen === 'number') { onGen(m.gen); deskEvent(m.desk); quantEvent(m.quant); }
      else if (m.online === false) setOnline(false);
      else if (m.online === true) { deskReconnected(); onBack(); }
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
      if (this.chan) this.chan.postMessage({ gen: msg.gen, desk: msg.desk, quant: msg.quant });
      onGen(msg.gen);
      deskEvent(msg.desk);                 // the chat, the reports, the agenda: their own counters (no new generation)
      quantEvent(msg.quant);               // the quant signals: a new result, a signal alert
    };
    es.onerror = () => {
      if (this.chan) this.chan.postMessage({ online: false });
      setOnline(false);
    };
    es.onopen = () => {
      if (this.chan) this.chan.postMessage({ online: true });
      deskReconnected();                   // (its first counters: news of everything)
      onBack();
    };
  },

  close() {
    if (this.es) { this.es.close(); this.es = null; }
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
      // Bloomberg says its event queue is filling up: prices may arrive late (and are asked again if any were dropped)
      if (p.slow) badge.classList.add('slow');
      $('mode-text').textContent = p.slow ? 'CANLI · Bloomberg kuyruğu doluyor'
        : p.pending ? 'CANLI · ' + p.pending + ' veri bekleniyor' : 'CANLI · Bloomberg';
      badge.title = 'Bloomberg (blpapi) canlı veri · ' + (p.subscriptions || 0) + ' abonelik'
        + (p.subscriptions_invalid ? ' (' + p.subscriptions_invalid + ' ticker Bloomberg\'de yok: abone olunmadı – hangileri olduğu için tıklayın)' : '')
        + ' · bugün ' + (p.hits_today || 0) + ' veri isteği'
        + (p.isolated ? ' · oturum ayrı süreçte' + (p.restarts ? ' (' + p.restarts + ' kez yeniden başladı)' : '') : ' · oturum dashboard sürecinde')
        + (p.events_dropped || p.messages_lost
          ? ' · KUYRUK TAŞTI: ' + (p.events_dropped || p.messages_lost) + ' olay düştü, ' + (p.resyncs || 0) + ' değer yeniden istendi' : '')
        + (p.limit_reached ? ' · GÜNLÜK LİMİT KORUMASI DEVREDE' : '') + (p.error ? ' · ' + p.error : '');
    }
  } else {
    badge.classList.add('replay');
    $('mode-text').textContent = 'KAYITLI VERİ';
    badge.title = status.note || 'Excel dosyasındaki son kayıtlı piyasa verisiyle çalışıyor';
  }
  $('asof').textContent = status.today ? 'Değerleme: ' + isoToTr(status.today) : '';
  // RET curve freshness: typed by the desk, so remind when it was not loaded today
  const ret = status.ret;
  const fresh = !!(ret && ret.updated_at && status.server_date && ret.updated_at.slice(0, 10) === status.server_date);
  $('btn-ret').classList.toggle('stale', !fresh);
  $('btn-ret').title = ret && ret.updated_at
    ? 'RET faizleri · son yükleme ' + ret.updated_at + (ret.updated_by ? ' (' + ctx.displayName(ret.updated_by) + ')' : '')
      + (fresh ? '' : ' – bugün güncellenmedi')
    : 'RET faizleri bugün yüklenmedi – dosyadaki eski değerler kullanılıyor. Tıklayıp Excel\'den yapıştırın.';
  $('foot-ver').textContent = 'port ' + status.port;
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

async function loadHeader() {
  // only when it changed since the strip was drawn (the same strip for everybody without inputs of their own)
  const res = await api.get('/api/header', state.headerGen ? { since: state.headerGen, as: state.headerAs } : null);
  state.headerAs = res.as;
  if (res.unchanged) return;
  state.headerGen = res.gen || 0;
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
const fetchCell = debounce(async (book, ref, ticket) => {
  try {
    const info = await api.get('/api/cell', { book, ref });
    if (ticket !== cellTicket) return;
    let text = info.formula || '';
    if (!text && info.cell) text = info.cell.t || '';
    if (info.input) text += (text ? '   ·   ' : '') + (info.input.scope === 'shared' ? 'ortak girdi' : 'kişisel girdi')
      + (info.input.label ? ' – ' + info.input.label : '');
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
    $('sb-fx').textContent = info.cell ? (info.cell.t || '') : '';
    fetchCell(info.book, info.focusRef, cellTicket);
  } else {
    fetchCell.cancel();
    $('sb-fx').textContent = info.rows + ' satır × ' + info.cols + ' sütun seçili';
  }
}

// ---------------------------------------------------------------------- boot
function applyLangButton() {
  $('btn-lang').textContent = settings.lang === 'en' ? '1,234.56' : '1.234,56';
}

/** Changed cells flash green / red for a moment; some find it tiring: it can be turned off (per browser). */
function applyFlash(on) {
  document.body.classList.toggle('noflash', !on);
  const b = $('btn-flash');
  b.classList.toggle('off', !on);
  b.setAttribute('aria-pressed', on ? 'true' : 'false');
  b.title = on ? 'Değişen hücreler yanıp sönüyor – kapatmak için tıklayın' : 'Yanıp sönme kapalı – açmak için tıklayın';
}

function boot() {
  if (state.booted) return;
  state.booted = true;
  setLang(store('tto.lang') || 'tr');
  applyLangButton();
  applyFlash(store('tto.flash') !== '0');
  if (store('tto.nav') === '1') $('app').classList.add('nav-collapsed');

  session.onUnauthorized = () => { showLogin('Oturumunuz sona erdi – tekrar giriş yapın.'); };
  const after = (res) => { runRefresh(); return res; };
  configureGrid({
    setInputs: (book, items, adhoc, lenient) => api.post('/api/inputs', { book, items, adhoc: !!adhoc, lenient: !!lenient }).then(after),
    paste: (book, anchor, text, adhoc) => api.post('/api/paste', { book, anchor, text, adhoc: !!adhoc }).then(after),
    reset: (book, refs, shared) => api.post('/api/reset', { book, refs, shared: !!shared }).then(after),
    // right click on a cell: watch it, or set an alarm on it
    watch: (book, ref, label) => addToWatch(ctx, { book, ref, label }),
    alarm: (book, ref, label, text) => openAlarmDialog(ctx, { book, ref, label, text }),
    onSelect,
  });

  $('login-form').addEventListener('submit', (e) => { e.preventDefault(); submitLogin(); });
  $('login-switch').addEventListener('click', (e) => {
    e.preventDefault();
    setLoginMode(signin.mode === 'request' ? 'login' : 'request');
    $('login-name').focus();
  });
  $('btn-theme').addEventListener('click', () => {
    const cur = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
    const next = cur === 'light' ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', next);
    store('tto.theme', next);
  });
  $('btn-flash').addEventListener('click', () => {
    const on = document.body.classList.contains('noflash');
    store('tto.flash', on ? '1' : '0');
    applyFlash(on);
    toast(on ? 'Değişen hücreler yeniden yanıp sönecek' : 'Yanıp sönme kapatıldı', '', 2200);
  });
  $('mode-badge').addEventListener('click', () => openStatus(state.status).catch(errorToast));
  $('btn-lang').addEventListener('click', () => {
    setLang(settings.lang === 'en' ? 'tr' : 'en');
    store('tto.lang', settings.lang);
    applyLangButton();
    toast(settings.lang === 'en' ? 'Sayı biçimi: 1,234.56 (İngilizce Excel)' : 'Sayı biçimi: 1.234,56 (Türkçe Excel)', '', 2600);
    const id = state.pageId;
    state.pageId = null;
    state.headerGen = 0;                            // (another number format: the whole strip again)
    loadHeader().catch(() => {});
    if (id) openPage(id);
  });
  $('btn-collapse').addEventListener('click', () => {
    const on = $('app').classList.toggle('nav-collapsed');
    store('tto.nav', on ? '1' : '0');
  });
  $('btn-ret').addEventListener('click', () => openRetEditor(ctx));
  setupFind($('findbox'), () => state.pages || [], (page, panel) => ctx.goto(page, panel));
  $('btn-scen').addEventListener('click', () => openScenarios(ctx));
  setupDesk({ page: () => state.page, pageId: () => state.pageId, where: () => ({ id: state.pageId, title: pageTitle(state.pageId) }) });
  $('btn-user').addEventListener('click', (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    menu(r.left, r.bottom + 4, [
      { header: session.display + (session.role === 'admin' ? ' · yönetici' : '') },
      { label: 'Senaryolarım', action: () => openScenarios(ctx) },
      { label: 'Şifremi değiştir', action: () => openPasswordDialog() },
    ].concat(session.role === 'admin' ? [{ label: 'Kullanıcılar', action: () => { window.location.hash = '#/users'; } }] : [],
      [{ sep: true }, { label: 'Çıkış', action: () => signOut() }]));
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
// (a cell of a tab that is not open is found as well: the page opens its tab)
function findCellAnywhere(ref) {
  return findCell(ref) || (state.page && state.page.findCell ? state.page.findCell(ref) : null);
}

window.tto = { findCell: findCellAnywhere, selectionText, state, events, refresh: () => runRefresh() };

boot();
