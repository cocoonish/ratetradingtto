// Application shell: login by name, navigation, live refresh (server-sent events), status bar.
import { api, session } from './api.js';
import { settings, setLang, num, isoToTr } from './format.js';
import { h, clear, toast, errorToast, debounce, menu } from './ui.js';
import { configureGrid, clearSelection, findCell, selectionText } from './grid.js';
import { ViewPage } from './pages/view.js';
import { BlotterPage } from './pages/blotter.js';
import { ExplorerPage } from './pages/explorer.js';
import { openRetEditor } from './ret.js';
import { openScenarios } from './scenarios.js';

const $ = (id) => document.getElementById(id);
const state = { pages: [], page: null, pageId: null, gen: 0, refreshing: false, dirty: false, users: {}, status: null, es: null,
  online: true, booted: false };

function store(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    if (value === null) localStorage.removeItem(key); else localStorage.setItem(key, value);
  } catch (e) { /* storage unavailable */ }
  return null;
}

const ctx = {
  refreshNow: () => { runRefresh(); pollStatus(); },
  displayName: (key) => state.users[key] || key || '',
};

// ---------------------------------------------------------------------- login
async function showLogin(message) {
  session.user = null;
  session.display = null;
  if (state.es) { state.es.close(); state.es = null; }
  if (state.page) { state.page.destroy(); state.page = null; state.pageId = null; }
  $('app').classList.add('hidden');
  $('login').classList.remove('hidden');
  $('login-err').textContent = message || '';
  const name = $('login-name');
  name.value = store('tto.user') || '';
  name.focus();
  name.select();
  const known = clear($('login-known'));
  try {
    const res = await api.get('/api/users');
    for (const u of res.users.slice(0, 24)) {
      const b = h('button', { type: 'button' }, u.display);
      b.addEventListener('click', () => doLogin(u.display));
      known.appendChild(b);
    }
  } catch (e) { /* the list is a convenience only */ }
}

async function doLogin(name) {
  try {
    const res = await api.post('/api/login', { name });
    store('tto.user', res.display);
    await enter(res);
    if (res.new) toast('Hoş geldiniz, ' + res.display + '. Girdileriniz ve senaryolarınız bu isimle saklanacak.', 'ok', 5000);
  } catch (err) {
    $('login-err').textContent = err.message;
  }
}

async function enter(login) {
  session.user = login.user;
  session.display = login.display;
  $('login').classList.add('hidden');
  $('app').classList.remove('hidden');
  $('user-name').textContent = login.display;
  $('user-av').textContent = (login.display.trim()[0] || '?').toLocaleUpperCase('tr');
  const [nav, status, users] = await Promise.all([api.get('/api/nav'), api.get('/api/status'), api.get('/api/users')]);
  state.pages = nav.pages;
  for (const u of users.users) state.users[u.name] = u.display;
  applyStatus(status);
  buildNav();
  connectEvents();
  loadHeader().catch(() => {});
  route();
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
  groups.get('Araçlar').push({ id: 'explorer', title: 'Sayfa gezgini' });
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
}

function pageTitle(id) {
  if (id === 'explorer') return 'Sayfa gezgini';
  const p = state.pages.find((x) => x.id === id);
  return p ? p.title : id;
}

function route() {
  let id = decodeURIComponent((window.location.hash || '').replace(/^#\/?/, ''));
  const known = id === 'explorer' || state.pages.some((p) => p.id === id);
  if (!known) id = state.pages.some((p) => p.id === 'masa') ? 'masa' : (state.pages[0] ? state.pages[0].id : 'explorer');
  if (id !== state.pageId) openPage(id);
}

async function openPage(id) {
  if (state.page) state.page.destroy();
  clearSelection();
  state.pageId = id;
  store('tto.page', id);
  for (const a of document.querySelectorAll('#nav .nav-item')) a.classList.toggle('active', a.dataset.page === id);
  $('page-title').textContent = pageTitle(id);
  document.title = pageTitle(id) + ' · TTO Masa';
  const host = clear($('content'));
  host.scrollTop = 0;
  let page;
  if (id === 'blotter') page = new BlotterPage(host, ctx);
  else if (id === 'explorer') page = new ExplorerPage(host, ctx);
  else page = new ViewPage(host, id, ctx);
  state.page = page;
  try {
    await page.load();
    page.ready = true;
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

function connectEvents() {
  if (state.es) state.es.close();
  const es = new EventSource('/api/events');
  state.es = es;
  es.onmessage = (e) => {
    let gen = 0;
    try { gen = JSON.parse(e.data).gen; } catch (x) { return; }
    setOnline(true);
    if (gen !== state.gen) {
      const first = state.gen === 0;
      state.gen = gen;
      if (!first) runRefresh();
    }
  };
  es.onerror = () => setOnline(false);
  es.onopen = () => {
    if (!state.online) {
      api.get('/api/status').then(applyStatus).catch(() => {});
      runRefresh();
    }
    setOnline(true);
  };
}

function setOnline(on) {
  if (state.online === on) return;
  state.online = on;
  applyStatus(state.status);
}

function applyStatus(status) {
  if (!status) return;
  state.status = status;
  const badge = $('mode-badge');
  badge.classList.remove('live', 'replay');
  if (!state.online) {
    $('mode-text').textContent = 'Bağlantı yok';
    badge.title = 'Sunucuya ulaşılamıyor – yeniden bağlanılıyor';
  } else if (status.mode === 'live') {
    const p = status.provider || {};
    if (p.connected === false) {
      $('mode-text').textContent = 'Bloomberg bağlantısı yok';
      badge.title = (p.error || 'Bloomberg bağlantısı koptu') + ' – yeniden bağlanılıyor';
    } else {
      badge.classList.add('live');
      $('mode-text').textContent = p.pending ? 'CANLI · ' + p.pending + ' veri bekleniyor' : 'CANLI · Bloomberg';
      badge.title = 'Bloomberg (blpapi) canlı veri · ' + (p.subscriptions || 0) + ' abonelik · bugün ' + (p.hits_today || 0)
        + ' veri isteği' + (p.limit_reached ? ' · GÜNLÜK LİMİT KORUMASI DEVREDE' : '') + (p.error ? ' · ' + p.error : '');
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
}

function pollStatus() {
  if (!session.user) return;
  api.get('/api/status').then(applyStatus).catch(() => {});
}

async function loadHeader() {
  const res = await api.get('/api/header');
  const box = $('kpis');
  const items = res.items || [];
  if (box.children.length !== items.length) {
    clear(box);
    for (const it of items) box.appendChild(h('div', { class: 'kpi' }, h('div', { class: 'l' }, it.label), h('div', { class: 'v' }, it.text)));
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

function boot() {
  if (state.booted) return;
  state.booted = true;
  setLang(store('tto.lang') || 'tr');
  applyLangButton();
  if (store('tto.nav') === '1') $('app').classList.add('nav-collapsed');

  session.onUnauthorized = () => { showLogin('Oturum bulunamadı – tekrar giriş yapın.'); };
  const after = (res) => { runRefresh(); return res; };
  configureGrid({
    setInputs: (book, items, adhoc) => api.post('/api/inputs', { book, items, adhoc: !!adhoc }).then(after),
    paste: (book, anchor, text, adhoc) => api.post('/api/paste', { book, anchor, text, adhoc: !!adhoc }).then(after),
    reset: (book, refs, shared) => api.post('/api/reset', { book, refs, shared: !!shared }).then(after),
    onSelect,
  });

  $('login-form').addEventListener('submit', (e) => { e.preventDefault(); doLogin($('login-name').value); });
  $('btn-theme').addEventListener('click', () => {
    const cur = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
    const next = cur === 'light' ? 'dark' : 'light';
    document.documentElement.setAttribute('data-theme', next);
    store('tto.theme', next);
  });
  $('btn-lang').addEventListener('click', () => {
    setLang(settings.lang === 'en' ? 'tr' : 'en');
    store('tto.lang', settings.lang);
    applyLangButton();
    toast(settings.lang === 'en' ? 'Sayı biçimi: 1,234.56 (İngilizce Excel)' : 'Sayı biçimi: 1.234,56 (Türkçe Excel)', '', 2600);
    const id = state.pageId;
    state.pageId = null;
    loadHeader().catch(() => {});
    if (id) openPage(id);
  });
  $('btn-collapse').addEventListener('click', () => {
    const on = $('app').classList.toggle('nav-collapsed');
    store('tto.nav', on ? '1' : '0');
  });
  $('btn-ret').addEventListener('click', () => openRetEditor(ctx));
  $('btn-scen').addEventListener('click', () => openScenarios(ctx));
  $('btn-user').addEventListener('click', (e) => {
    const r = e.currentTarget.getBoundingClientRect();
    menu(r.left, r.bottom + 4, [
      { header: session.display || '' },
      { label: 'Senaryolarım', action: () => openScenarios(ctx) },
      { sep: true },
      { label: 'Kullanıcı değiştir / çıkış', action: () => { store('tto.user', null); showLogin(''); } },
    ]);
  });
  window.addEventListener('hashchange', () => { if (session.user) route(); });
  setInterval(pollStatus, 15000);

  const saved = store('tto.user');
  if (saved) {
    api.post('/api/login', { name: saved }).then(enter).catch(() => showLogin(''));
  } else {
    showLogin('');
  }
}

// small debugging / testing surface
window.tto = { findCell, selectionText, state, refresh: () => runRefresh() };

boot();
