// Generic workbook page: a set of panels (tables and charts) defined by a view on the server.
// A page with many tables comes in tabs ("sections" of the view): one group of tables at a time, the
// calculators first; the search box and "Tümü" look across all of them.  A calculator may be opened again as temporary
// copies ("Geçici kopya aç" in its "+ Launchpad" menu): "… · kopya 2" right under it, with inputs of its own.
import { openAddIsin, bondCardLinks, bondFlags } from '../bonds.js';
import { api } from '../api.js';
import { h, clear, toast, errorToast, confirmDialog, menu, fitOneLine, watchWidth, foldNote, waiting } from '../ui.js';
import { dayTime } from '../mine.js';
import { Grid, copyGrid, findCell, reviveEditor, trackWrite } from '../grid.js';
import { Chart, chartTable } from '../chart.js';
import { openQuoteMessage, openTradeDialog } from '../quote.js';
import { bookBulkForward } from './blotterentry.js';
import { bookHedge } from '../hedgeislem.js';
import { quoteButton, quoteRowItems, quoteRows } from '../kotasyon.js';
import { addButton, loadLayout } from '../layout.js';

const ALL = '*';

function pref(key, fallback) {
  try {
    const v = localStorage.getItem(key);
    return v === null ? fallback : v;
  } catch (e) { return fallback; }
}

function setPref(key, value) {
  try { localStorage.setItem(key, value); } catch (e) { /* ignore */ }
}

/** "Elle değer" stays on while the browser tab is open, on every page; a new session starts with it off. */
function handMode() {
  try { return sessionStorage.getItem('tto.adhoc') === '1'; } catch (e) { return false; }
}

function setHandMode(on) {
  try { sessionStorage.setItem('tto.adhoc', on ? '1' : '0'); } catch (e) { /* ignore */ }
}

/** Formula cells this user typed a value over: [ref, ...] of the tables on the page. */
function overridden(panels) {
  const refs = new Set();
  for (const p of panels) {
    const d = p.data;
    if (!d || !d.rows || !d.r || !d.c) continue;
    for (let i = 0; i < d.rows.length; i++) {
      const row = d.rows[i];
      for (let j = 0; j < row.length; j++) {
        const c = row[j];
        if (c && c.fx && c.m === 1 && !c.sk) refs.add(d.sheet + '!' + d.c[j] + d.r[i]);
      }
    }
  }
  return Array.from(refs);
}

export class ViewPage {
  constructor(host, viewId, ctx) {
    this.host = host;
    this.id = viewId;
    this.ctx = ctx;
    this.items = new Map();
    this.order = '';
    this.ids = [];
    this.sections = [];
    this.pinned = [];
    this.tab = pref('tto.sec.' + viewId, '');
    this.showAll = pref('tto.all.' + viewId, '0') === '1';
    this.adhoc = handMode();
    this.filter = '';
    this.book = null;
    this.dead = false;
    this.keepAlive = true;               // kept with the last pages opened: back in view as it was (tab, scroll)
    this.staleInputs = [];               // the page's market levels typed on an earlier day (checkStale)
    this.staleAt = 0;
  }

  async load() {
    clear(this.host);
    this.host.appendChild(waiting());              // (the page's first answer on its way: "Hesaplanıyor…")
    const data = await this.fetch();
    if (this.dead) return;
    this.build(data);
    this.checkStale(true);
  }

  /** The page: all of it, or (``extra``: {since, panels}) the panels asked for that changed since a generation. */
  fetch(extra) {
    return api.get('/api/view/' + encodeURIComponent(this.id), Object.assign(this.showAll ? { all: 1 } : {}, extra || {}));
  }

  signature(data) {
    const ids = data.ids || data.panels.map((p) => p.id + ':' + p.type);
    const cols = (stacks) => (stacks && stacks.length ? '[' + stacks.map((st) => st.join(',')).join('|') + ']' : '');
    return ids.join('|') + '#' + (data.sections || []).map((s) => s.id + '=' + s.panels.join(',') + cols(s.stacks)).join('|')
      + '#' + (data.pinned || []).join(',') + cols(data.pinned_stacks);
  }

  /** What a table shows right now (refreshed in place since the page was built): what a message or a trade is made of. */
  panelData(p, it) {
    const cur = this.items.get(p.id) || it;
    return (cur.grid && cur.grid.data) || cur.data || p.data;
  }

  /**
   * Bring the panels on the page up to date: only those in view (the open tab, the pinned ones, what the search
   * shows) are asked for, and of them only what changed since they were last drawn comes back.  Another tab's
   * panels are brought up to date when it is opened.
   */
  async refresh() {
    const ids = (this.placed || []).filter((id) => this.items.has(id));
    if (!ids.length || this.dead) return;
    this.checkStale();                                // (at most once a minute: the market levels typed on an earlier day)
    const since = Math.min(...ids.map((id) => this.items.get(id).gen || 0));
    const had = this.as;
    const data = await this.fetch({ since, panels: ids.join(','), as: had });
    if (this.dead) return;
    // (the generations are those of the page the server says this is: everybody's, or the user's own - with the user's
    // own decimals on it)
    const seen = (held) => {
      if (had !== undefined && data.as !== had) {
        // another page now (the user's decimals changed - no new generation for it): the other tabs' panels are of the one
        // before, asked for whole when their tab is opened
        for (const [id, it] of this.items) if (!ids.includes(id)) it.gen = 0;
      }
      this.as = data.as;
      for (const id of ids) {
        const it = this.items.get(id);
        if (!it || (held && held.has(id))) continue;     // (held back: asked for again next time)
        it.gen = Math.max(it.gen || 0, data.gen || 0);
        it.el.classList.remove('stale');                  // (as current as the server has it)
      }
    };
    if (data.unchanged) { seen(); return; }
    if (this.signature(data) !== this.order) { this.build(await this.fetch()); return; }    // the page changed shape
    const held = this.apply(data.panels);
    seen(held);
    this.showOverrides();
  }

  /** Panels that are not up to date with the latest generation, among those on the page now. */
  stale() {
    const gen = this.ctx.gen ? this.ctx.gen() : 0;
    return (this.placed || []).some((id) => { const it = this.items.get(id); return it && (it.gen || 0) < gen; });
  }

  /** New data of panels, drawn in place; returns the ids of those held back (a cell of theirs is being typed into). */
  apply(panels) {
    const held = new Set();
    for (const p of panels) {
      const it = this.items.get(p.id);
      if (!it) continue;
      if (typeof p.title === 'string' && p.title !== it.title && it.titleEl) {
        // a caption the workbook works out from what is typed (the auction's "KÂĞIT 1 · 15.03.28 · TRT…") follows it
        it.title = p.title;
        it.titleEl.textContent = p.title;
        it.titleEl.title = p.title;
      }
      // (a note that says what is drawn - the ASW history's offshore days - follows it too)
      if (typeof p.note === 'string' && it.noteEl && p.note !== it.note) { this.setNote(it, p.note, p.tw); this.dedupeNotes(); }
      if (p.type === 'chart') {
        const data = it.choice && p.choice ? it.choice.take(p.choice) : p.data;      // (drawn several ways: the user's way)
        it.data = data;
        if (it.pick && p.pick) it.pick.set(p.pick.value);              // (chosen elsewhere too: Parametreler, another tab)
        if (!it.el.isConnected) { it.stale = true; continue; }       // drawn when its tab is opened
        if (it.chart && data) it.chart.update(data);
        if (it.tableGrid && data) it.tableGrid.update(chartTable(data), false);
      } else if (it.grid && p.data) {
        if (it.grid.update(p.data, true) === false) { held.add(p.id); continue; }
        it.data = p.data;
        // (a temporary copy's strip of inputs above it)
        (p.lead || []).forEach((l, k) => { const g = (it.leads || [])[k]; if (g && l.data && g.update(l.data, true) === false) held.add(p.id); });
        if (it.grow) it.grow();
        if (it.limit) it.limit();
      }
    }
    return held;
  }

  destroy() {
    this.dead = true;
    for (const it of this.items.values()) if (it.chart) it.chart.destroy();
    this.items.clear();
  }

  /**
   * Back in view (kept with the last pages opened): the tab, the search and the scroll are as they were; "Elle değer"
   * follows what it is now, and the panels older than the latest generation are dimmed until the refresh that follows.
   */
  revive() {
    const hand = handMode();
    if (hand !== this.adhoc) this.setHand(hand, true);
    if (!this.ctx.gen) return;
    const gen = this.ctx.gen();
    for (const id of this.placed || []) {
      const it = this.items.get(id);
      if (it && (it.gen || 0) < gen) it.el.classList.add('stale');
    }
  }

  /** "Elle değer" on or off on this page (``quiet``: no toast - it follows another page's switch). */
  setHand(on, quiet) {
    this.adhoc = !!on;
    setHandMode(this.adhoc);
    if (this.handBtn) this.handBtn.classList.toggle('on', this.adhoc);
    this.host.classList.toggle('hand', this.adhoc);
    for (const it of this.items.values()) if (it.grid && !it.copy) it.grid.opts.adhoc = this.adhoc;       // (never in a copy)
    if (quiet) return;
    if (this.ctx.handChanged) this.ctx.handChanged(this.adhoc);
    toast(this.adhoc ? 'Elle değer açık: her hücreye yazabilirsiniz (yalnızca sizde değişir; silince formül geri gelir)' : 'Elle değer kapalı', '', 3600);
  }

  build(data) {
    for (const it of this.items.values()) if (it.chart) it.chart.destroy();
    this.items.clear();
    this.book = data.book;
    this.order = this.signature(data);
    this.ids = data.panels.map((p) => p.id);
    this.gen = data.gen || 0;
    this.as = data.as;
    this.sections = data.sections || [];
    this.pinned = data.pinned || [];
    this.pinnedStacks = data.pinned_stacks || [];
    if (this.sections.length && this.tab !== ALL && !this.sections.some((s) => s.id === this.tab)) this.tab = this.sections[0].id;
    clear(this.host);
    this.host.classList.toggle('hand', this.adhoc);

    const search = h('input', { class: 'inp', type: 'search', placeholder: this.sections.length ? 'Tablo ara (tüm sekmelerde)…' : 'Tablo ara…',
      style: { width: '210px' }, value: this.filter });
    search.addEventListener('input', () => { this.filter = search.value; this.applyFilter(); });
    this.searchBox = search;
    const allBtn = h('button', { class: 'btn sm' + (this.showAll ? ' on' : ''), type: 'button',
      title: 'Excel\'de gizli sütunları, grafik verisi ve ara hesap tablolarını da göster' }, 'Yardımcı tablolar');
    allBtn.addEventListener('click', () => this.toggleAll());
    // Excel lets you type over anything; here that is a mode, so that a formula is never lost by accident
    const handBtn = h('button', { class: 'btn sm' + (this.adhoc ? ' on' : ''), type: 'button', id: 'hand-mode',
      title: 'Açıkken bu sayfadaki her hücreye – formül olanlara da – kendi değerinizi yazabilirsiniz (Bloomberg\'den gelmeyen bir fiyat, '
        + 'denemek istediğiniz bir spot…). Yalnızca sizin görünümünüz değişir; hücreyi silince (Delete) formül geri gelir.' }, 'Elle değer');
    this.handBtn = handBtn;
    handBtn.addEventListener('click', () => this.setHand(!this.adhoc));
    const resetBtn = h('button', { class: 'btn sm', type: 'button', title: 'Bu çalışma kitabındaki kişisel girdilerimi sil' }, 'Girdilerimi sıfırla');
    resetBtn.addEventListener('click', async () => {
      const ok = await confirmDialog('Girdileri sıfırla',
        'Bu çalışma kitabındaki tüm kişisel girdileriniz silinir ve dosyadaki varsayılan değerlere dönülür. Kayıtlı senaryolarınız etkilenmez.', 'Sıfırla');
      if (!ok) return;
      try {
        const res = await trackWrite(api.post('/api/reset', { book: this.book }));
        toast((res.reset || 0) + ' girdi sıfırlandı', 'ok');
        this.ctx.refreshNow();
      } catch (err) { errorToast(err); }
    });
    this.overChip = h('button', { class: 'btn sm warnchip hidden', type: 'button', id: 'hand-values',
      title: 'Bu sayfada formülün yerine elle yazdığınız değerler var. Tıklayın: hepsi formüle döner.' });
    this.overChip.addEventListener('click', () => this.restoreFormulas());
    // the market levels of this page typed on an earlier day (the desk, 28.11.2026 - A7): "N girdi dünden · temizle"
    this.staleChip = h('button', { class: 'btn sm warnchip hidden', type: 'button', id: 'stale-inputs' });
    this.staleChip.addEventListener('click', () => this.clearStale());
    this.paintStale();
    // what the colours of the cells mean: one click away, behind "?" (the desk, 27.11.2026: a lighter top of the page) -
    // and how long the page took, said there
    const legend = h('div', { class: 'legend' },
      h('span', null, h('i', { class: 'sw-in' }), 'kişisel girdi'),
      h('span', { title: 'Piyasadan ya da başka bir hücreden dolan girdi: üzerine yazabilirsiniz, silince otomatik değer geri gelir' },
        h('i', { class: 'sw-auto' }), 'otomatik (üzerine yazılabilir)'),
      h('span', null, h('i', { class: 'sw-sh' }), 'ortak girdi (herkes görür)'),
      h('span', { title: 'Sarı ya da yeşil bir hücreye = yazıp başka bir hücreye tıklayın - bu tablonun, sayfanın başka bir '
        + 'tablosunun ya da sekmesinin, yan panelin: adresi formüle eklenir (=C60+7). Değer canlıdır: okuduğu hücre değişince '
        + 'kendiliğinden güncellenir. F2 ya da üzerine gelmek formülü gösterir; silmek formülü de kaldırır. Bloomberg işlevleri '
        + 'kullanılamaz.' }, h('i', { class: 'sw-ff' }, 'ƒ'), 'formüllü girdi'),
      h('span', null, h('i', { class: 'sw-hand' }), 'formül yerine elle değer'),
      h('span', { title: 'İki yönlü tablo: bir satırın değerlerinden (spread, TRY %, puan, fwd …) hangisini yazarsanız o kalır, '
        + 'diğerleri ondan hesaplanır. Silince satır varsayılana döner.' }, h('i', { class: 'sw-anchor' }, '✎'), 'iki yönlü: yazılan'));
    const legendBtn = h('button', { class: 'btn sm legend-chip', type: 'button', id: 'legend-chip',
      title: 'Hücre renkleri: kişisel / ortak girdi, otomatik, formüllü, elle değer, iki yönlü' }, '?');
    legendBtn.addEventListener('click', () => {
      const r = legendBtn.getBoundingClientRect();
      menu(r.right - 290, r.bottom + 4, [{ header: 'Hücre renkleri' }, { node: legend },
        { node: h('div', { class: 'mh legend-ms' }, 'Sayfa ' + data.ms + ' ms\'de hesaplandı') }], 'legend-pop');
    });
    // a page in tabs has its tools at the tab bar's empty right end (the desk, 28.11.2026 - B3: one row less above the
    // tables, and in sight with the tab bar while the page scrolls); a page without tabs keeps them on a row of their own
    const tools = h('div', { class: 'page-tools' }, search, allBtn, handBtn, resetBtn, this.overChip, this.staleChip,
      h('span', { class: 'grow' }), legendBtn);
    if (!this.sections.length) this.host.appendChild(tools);

    if (data.links && data.links.length) {
      // the workbook's own "go to" links: other pages, straight to the table they point at - on one line, "+N" the rest
      // (opened, they stay so in this browser)
      const bar = h('div', { class: 'shortcuts one' + (pref('tto.kisayol.open', '0') === '1' ? ' open' : '') },
        h('span', { class: 'lbl' }, 'Kısayollar'));
      const chips = [];
      for (const l of data.links) {
        const a = h('a', { class: 'chip', href: '#/' + l.page + (l.panel ? '?p=' + encodeURIComponent(l.panel) : ''),
          title: 'Excel\'deki köprü: ' + l.ref }, l.label);
        a.addEventListener('click', (e) => { e.preventDefault(); this.ctx.goto(l.page, l.panel); });
        bar.appendChild(a);
        chips.push(a);
      }
      const more = h('button', { class: 'shortcut-more', type: 'button', id: 'shortcuts-more', title: 'Bütün kısayollar / tek satır' });
      bar.appendChild(more);
      const fit = () => fitOneLine(bar, chips, more, 'daha az');
      more.addEventListener('click', () => {
        const open = bar.classList.toggle('open');
        setPref('tto.kisayol.open', open ? '1' : '0');
        fit();
      });
      watchWidth(bar, fit);
      this.host.appendChild(bar);
    }
    if (data.note) this.host.appendChild(h('div', { class: 'banner' }, data.note));

    for (const p of data.panels) this.panel(p);              // built once; the tabs only decide which are on the page
    this.pinWrap = h('div', { class: 'panels pinned' });
    this.tabBar = h('div', { class: 'viewtabs', role: 'tablist' });
    this.tabBtns = new Map();
    for (const s of this.sections) this.tabBtns.set(s.id, this.tabButton(s.id, s.title, s.panels.length));
    if (this.sections.length) this.tabBtns.set(ALL, this.tabButton(ALL, 'Tümü', this.ids.length));
    // the tab's note: one line, "devamı" the rest (the desk, 28.11.2026 - B2: a tab's note took several lines over its
    // tables)
    this.secText = h('span', { class: 'sn-text' });
    this.secNote = h('div', { class: 'secnote hidden' }, this.secText);
    this.secFold = foldNote(this.secNote);
    this.wrap = h('div', { class: 'panels' });
    if (this.pinned.length) this.host.appendChild(this.pinWrap);
    if (this.sections.length) this.host.appendChild(h('div', { class: 'tabline' }, this.tabBar, tools));
    this.host.appendChild(this.secNote);
    this.host.appendChild(this.wrap);
    this.layout();
    this.showOverrides();
  }

  tabButton(id, title, count) {
    const b = h('button', { type: 'button', role: 'tab', title: count + ' tablo' }, title, h('span', { class: 'n' }, String(count)));
    b.dataset.tab = id;
    b.addEventListener('click', () => this.setTab(id));
    this.tabBar.appendChild(b);
    return b;
  }

  setTab(id) {
    if (this.filter) { this.filter = ''; if (this.searchBox) this.searchBox.value = ''; }
    this.tab = id;
    setPref('tto.sec.' + this.id, id);
    this.layout();
  }

  /** Put the panels of the open tab (or what the search finds, in every tab) on the page. */
  layout() {
    const low = (t) => String(t || '').toLocaleLowerCase('tr').replace(/ı/g, 'i');       // "interest" finds "Interest"
    const q = low(this.filter.trim());
    const hit = (it) => !q || low(it.title).includes(q);
    const placed = [];
    const place = (host, id) => {
      const it = this.items.get(id);
      if (!it) return false;
      host.appendChild(it.el);
      placed.push(id);
      if (it.stale && it.chart && it.data) { it.stale = false; it.chart.update(it.data); }
      return true;
    };
    // the panels of ``ids`` in their order; a column of the view (``stacks``: small panels one under the other beside a
    // tall one - the desk, 27.11.2026) at the place of its first panel, with those of its panels that are in ``ids``
    const placeAll = (host, ids, stacks) => {
      const stackOf = new Map();
      for (const st of stacks || []) for (const sid of st) if (!stackOf.has(sid)) stackOf.set(sid, st);
      const done = new Set();
      let n = 0;
      for (const id of ids) {
        const st = stackOf.get(id);
        if (!st) { n += place(host, id) ? 1 : 0; continue; }
        if (done.has(st)) continue;
        done.add(st);
        const col = h('div', { class: 'stack' });
        for (const sid of st) if (ids.includes(sid)) n += place(col, sid) ? 1 : 0;
        if (!col.children.length) continue;
        col.classList.toggle('wide', [...col.children].some((c) => c.classList.contains('wide')));
        host.appendChild(col);
      }
      return n;
    };
    while (this.wrap.firstChild) this.wrap.removeChild(this.wrap.firstChild);
    while (this.pinWrap.firstChild) this.pinWrap.removeChild(this.pinWrap.firstChild);
    placeAll(this.pinWrap, this.pinned, this.pinnedStacks);
    let shown = 0;
    let note = '';
    if (!this.sections.length) {
      shown += placeAll(this.wrap, this.ids.filter((id) => hit(this.items.get(id))), []);
    } else if (q || this.tab === ALL) {
      const placed = new Set(this.pinned);
      for (const s of this.sections) {
        const ids = s.panels.filter((id) => !placed.has(id) && this.items.has(id) && hit(this.items.get(id)));
        if (!ids.length) continue;
        const head = h('div', { class: 'secthead' }, s.title, h('span', { class: 'n' }, String(ids.length)));
        this.wrap.appendChild(head);
        for (const id of ids) placed.add(id);
        shown += placeAll(this.wrap, ids, s.stacks);
      }
    } else {
      const s = this.sections.find((x) => x.id === this.tab) || this.sections[0];
      note = s.note || '';
      shown += placeAll(this.wrap, s.panels.filter((id) => this.pinned.indexOf(id) < 0), s.stacks);
    }
    if (!shown) this.wrap.appendChild(h('div', { class: 'empty' }, q ? 'Aramayla eşleşen tablo yok' : 'Bu sekmede tablo yok'));
    for (const [id, b] of this.tabBtns) b.classList.toggle('on', !q && id === this.tab);
    this.tabBar.classList.toggle('searching', !!q);
    const said = q ? 'Arama sonucu: tüm sekmelerdeki eşleşen tablolar' : note;
    if (this.secText.textContent !== said) {
      this.secText.textContent = said;
      this.secNote.classList.remove('open');           // (another tab's note: folded to its line again)
      this.secFold.more.textContent = 'devamı';
    }
    this.secNote.classList.toggle('hidden', !said);
    this.secFold.check();
    this.placed = placed;
    this.dedupeNotes();
    reviveEditor();                    // (a cell typed into whose table left the page: its editor goes on in a bar of its own)
    // a tab whose panels were not brought up to date while another was open: now - shown dimmed until then, so that
    // nobody reads a number from before the change
    if (this.stale() && this.ctx.refreshPage) {
      const gen = this.ctx.gen();
      for (const id of placed) { const it = this.items.get(id); if (it && (it.gen || 0) < gen) it.el.classList.add('stale'); }
      this.ctx.refreshPage();
    }
  }

  toggleAll() {
    this.showAll = !this.showAll;
    setPref('tto.all.' + this.id, this.showAll ? '1' : '0');
    return this.load().catch(errorToast);
  }

  /** Make sure a panel is on the page: open the tab that holds it. */
  showPanel(panelId) {
    const it = this.items.get(panelId);
    if (!it) return false;
    if (this.filter) { this.filter = ''; if (this.searchBox) this.searchBox.value = ''; this.layout(); }
    if (!it.el.isConnected) {
      const s = this.sections.find((x) => x.panels.indexOf(panelId) >= 0);
      this.setTab(s ? s.id : ALL);
    }
    return it.el.isConnected;
  }

  /** Bring a panel into view (opening its tab, and the panel if it is collapsed) and mark it for a moment. */
  focusPanel(panelId) {
    const it = this.items.get(panelId);
    if (!it || !this.showPanel(panelId)) return false;
    if (it.el.classList.contains('collapsed') && it.toggle) it.toggle(false);
    it.el.scrollIntoView({ block: 'start', behavior: 'smooth' });
    it.el.classList.remove('focus');
    void it.el.offsetWidth;                       // restart the highlight
    it.el.classList.add('focus');
    return true;
  }

  /** The <td> of a workbook cell wherever it is on this page; the tab that holds it is opened.  (A temporary copy shows
   *  the same cells: never its own.) */
  findCell(ref) {
    for (const [id, it] of this.items) {
      if (!it.grid || it.copy) continue;
      const td = findCell(ref, it.el);
      if (td) { this.showPanel(id); return td; }
    }
    return null;
  }

  applyFilter() {
    this.layout();
  }

  showOverrides() {
    // (every panel's data as it is now: the ones refreshed and the ones of other tabs - a copy's own values are its own)
    this.overRefs = overridden([...this.items.values()].filter((it) => !it.copy).map((it) => ({ data: (it.grid && it.grid.data) || it.data })));
    const n = this.overRefs.length;
    this.overChip.classList.toggle('hidden', !n);
    this.overChip.textContent = n ? n + ' formül yerine elle değer · formüle dön' : '';
  }

  async restoreFormulas() {
    const refs = this.overRefs || [];
    if (!refs.length) return;
    const ok = await confirmDialog('Formüllere dön', 'Bu sayfada formülün yerine elle yazdığınız ' + refs.length
      + ' değer silinir ve hücreler yeniden hesaplanır (' + refs.slice(0, 6).join(', ') + (refs.length > 6 ? ' …' : '') + '). Diğer girdileriniz kalır.', 'Formüllere dön');
    if (!ok) return;
    try {
      const res = await trackWrite(api.post('/api/reset', { book: this.book, refs }));
      toast((res.reset || 0) + ' hücre formüle döndü', 'ok');
      this.ctx.refreshNow();
    } catch (err) { errorToast(err); }
  }

  /**
   * The market levels on this page typed on an earlier day (the desk, 28.11.2026 - A7: a spot, a spread, a meeting's
   * rate, a quote, a pasted DV01 left from yesterday - tto/myinputs.py; never a setting): the user's own and the desk's
   * (the manual spot), from /api/my-inputs - asked when the page is built and then at most once a minute (``force``: now).
   */
  async checkStale(force) {
    const now = Date.now();
    if (!force && this.staleAt && now - this.staleAt < 60000) return;
    this.staleAt = now;
    let data;
    try { data = await api.get('/api/my-inputs'); } catch (err) { return; }
    if (this.dead) return;
    const here = (x) => x.old && x.market && (x.pages || []).some((p) => p.view === this.id);
    this.staleInputs = (data.inputs || []).filter(here).concat((data.desk || []).filter(here));
    this.paintStale();
  }

  paintStale() {
    if (!this.staleChip) return;
    const items = this.staleInputs || [];
    const n = items.length;
    this.staleChip.classList.toggle('hidden', !n);
    this.staleChip.textContent = n ? n + ' girdi dünden · temizle' : '';
    this.staleChip.title = n ? 'Bu sayfada bugünden önce yazılmış piyasa girdileri (ayarlar değil):\n'
      + items.slice(0, 12).map((x) => '• ' + x.market + ' · ' + x.ref + ' = ' + x.value + ' · ' + dayTime(x.at)
        + (x.shared ? ' · ortak' + (x.by ? ' (' + this.ctx.displayName(x.by) + ')' : '') : '')).join('\n')
      + (n > 12 ? '\n…' : '') + '\nTıklayın: silinir, hücreler varsayılanına (formülüne / piyasaya) döner.' : '';
  }

  /** "temizle": the stale levels of the page taken back to their defaults (asked first; the desk's own for everybody). */
  async clearStale() {
    const items = this.staleInputs || [];
    if (!items.length) return;
    const shared = items.filter((x) => x.shared).length;
    const ok = await confirmDialog('Dünden kalan girdiler', items.length + ' piyasa girdisi bugünden önce yazılmış ('
      + items.slice(0, 6).map((x) => x.market + ' ' + x.ref + ', ' + dayTime(x.at)).join('; ') + (items.length > 6 ? ' …' : '')
      + '). Silinir; hücreler varsayılanına - formülüne, piyasaya - döner.'
      + (shared ? ' ' + shared + ' tanesi masanın ortak girdisi (manuel spot): herkes için döner.' : ''), 'Temizle');
    if (!ok) return;
    try {
      const groups = new Map();
      for (const x of items) {
        const k = x.book + '|' + (x.shared ? '1' : '');
        if (!groups.has(k)) groups.set(k, { book: x.book, shared: !!x.shared, refs: [] });
        groups.get(k).refs.push(x.ref);
      }
      let n = 0;
      for (const g of groups.values()) n += ((await trackWrite(api.post('/api/reset', g))) || {}).reset || 0;
      toast(n + ' girdi temizlendi: varsayılanına döndü', 'ok', 3200);
      this.ctx.refreshNow();
    } catch (err) { errorToast(err); }
    this.checkStale(true);
  }

  /**
   * A table with more rows than are in use (a list, a bulk pricing): the rows after the last filled one stay
   * out of the way but ``extra`` empty ones; "+ Satır" opens one more, "Tümü" all of them.
   */
  growable(it, p, head) {
    const key = 'tto.grow.' + this.id + '.' + p.id;
    let extra = Math.max(1, Number(pref(key, String(p.grow.extra || 1))) || 1);
    let all = false;
    const more = h('button', { class: 'iconbtn grow-more', type: 'button', title: 'Bir boş satır daha göster' }, '+ Satır');
    const every = h('button', { class: 'iconbtn grow-all', type: 'button', title: 'Bütün satırları göster / yalnızca dolu olanları' }, 'Tümü');
    head.appendChild(more);
    head.appendChild(every);
    it.grow = () => {
      const g = it.grid;
      const d = g && g.data;
      if (!d || !d.c || !d.r) return;
      const k = d.c.indexOf(p.grow.key);
      const first = p.grow.first || 1;
      let last = first - 1;
      for (let i = 0; i < d.r.length; i++) {
        const cell = (d.rows[i] || [])[k];
        if (d.r[i] >= first && d.r[i] <= (p.grow.last || Infinity) && cell && String(cell.t || '').trim()) last = Math.max(last, d.r[i]);
      }
      const upto = last + extra;
      const trs = [...g.el.querySelectorAll('tbody > tr')].filter((tr) => !tr.classList.contains('axisrow'));
      let hidden = 0;
      trs.forEach((tr, i) => {
        const r = d.r[i];
        const hide = !all && typeof r === 'number' && r > upto && r <= (p.grow.last || Infinity);       // a note below the rows stays
        tr.classList.toggle('grow-hidden', hide);
        if (hide) hidden += 1;
      });
      more.disabled = all || !hidden;
      every.textContent = all ? 'Dolu satırlar' : 'Tümü (' + trs.length + ')';
    };
    more.addEventListener('click', () => { extra += 1; setPref(key, String(extra)); it.grow(); });
    every.addEventListener('click', () => { all = !all; it.grow(); });
    it.grow();
  }

  /**
   * A long table that opens on its first rows (the view's ``"limit": {"rows": n}``; the desk, 27.11.2026: one scrollbar -
   * the PPK table's 82 meetings opened on 24): the first n rows under its captions, "Tümü (N)" in its header the rest -
   * kept so in this browser, as the tabs and the folded panels are (a temporary copy as its table).
   */
  limitable(it, p, head) {
    const n = Math.max(1, Math.floor(Number(p.limit.rows)) || 1);
    const key = 'tto.limit.' + this.id + '.' + (p.copy ? p.copy.of : p.id);
    let all = pref(key, '0') === '1';
    const btn = h('button', { class: 'iconbtn limit-all', type: 'button' });
    btn.dataset.action = 'limit';
    head.appendChild(btn);
    it.limit = () => {
      const g = it.grid;
      if (!g || !g.data) return;
      const heads = new Set(g.heads);
      const trs = [...g.el.querySelectorAll('tbody > tr')].filter((tr) => !tr.classList.contains('axisrow'));
      let k = 0;
      trs.forEach((tr, i) => {
        if (heads.has(i)) return;                        // (the captions stay)
        k += 1;
        tr.classList.toggle('limit-hidden', !all && k > n);
      });
      btn.classList.toggle('hidden', k <= n);
      btn.textContent = all ? 'İlk ' + n : 'Tümü (' + k + ')';
      btn.title = all ? 'Yalnız ilk ' + n + ' satırı göster' : 'Bütün ' + k + ' satırı göster (ilk ' + n + ' gösteriliyor)';
    };
    btn.addEventListener('click', () => { all = !all; setPref(key, all ? '1' : '0'); it.limit(); });
    it.limit();
  }

  /** A panel's note: its own words, then each two-way group's note (tto/twoway.py; ``tw``: those of ``note``, at its end) -
   *  one a table above it on screen says already is left out there (dedupeNotes); two lines of it, "devamı" the rest. */
  setNote(it, note, tw) {
    const el = it.noteEl;
    const more = it.noteFold.more;
    const parts = Array.isArray(tw) ? tw.filter((t) => typeof t === 'string' && t) : [];
    const joined = parts.join(' ');
    const split = !!joined && note.endsWith(joined);
    const own = split ? note.slice(0, note.length - joined.length).trim() : note;
    while (el.firstChild && el.firstChild !== more) el.removeChild(el.firstChild);
    if (own) el.insertBefore(document.createTextNode(own), more);
    it.note = note;
    it.noteOwn = !!own;
    it.tw = split ? parts : [];
    it.twEls = it.tw.map((t, k) => el.insertBefore(h('span', { class: 'tw' }, (own || k ? ' ' : '') + t), more));
    it.noteFold.check();
  }

  /**
   * A two-way group's note (tto/twoway.py) under the first table on screen that shows the group; the tables after it (the
   * same calculator's other tables, a temporary copy, the page's other tab when "Tümü" shows them all) leave it out - one
   * note a page, not four (the desk, 27.11.2026).  A folded panel says nothing: the next one on screen says it.
   */
  dedupeNotes() {
    const seen = new Set();
    const notes = [];
    for (const el of this.host.querySelectorAll('section.panel')) {
      const it = this.items.get(el.dataset.panel);
      if (!it || it.el !== el || !it.noteEl) continue;
      const shut = el.classList.contains('collapsed');
      let says = it.noteOwn;
      (it.twEls || []).forEach((span, k) => {
        const dup = !shut && seen.has(it.tw[k]);
        if (!shut) seen.add(it.tw[k]);
        span.classList.toggle('dup', dup);
        if (!dup) says = true;
      });
      it.noteEl.classList.toggle('empty', !says);
      if (!it.noteEl.classList.contains('open')) notes.push(it.noteEl);
    }
    // longer than its two lines? - all measured first, then marked: the page laid out once, not once a note
    const long = notes.map((n) => n.scrollHeight > n.clientHeight + 2);
    notes.forEach((n, k) => n.classList.toggle('long', long[k]));
  }

  panel(p) {
    const key = 'tto.col.' + this.id + '.' + p.id;
    const collapsed = pref(key, p.collapsed ? '1' : '0') === '1';
    const el = h('section', { class: 'panel vpanel' + (p.wide ? ' wide' : '') + (p.full ? ' full' : '') + (p.fit ? ' fit' : '')
      + (p.type === 'chart' ? ' chart' : '') + (p.type === 'notes' ? ' notes' : '')
      + (p.hidden ? ' aux' : '') + (collapsed ? ' collapsed' : '') + (p.copy ? ' copy' : '') });
    el.dataset.panel = p.id;
    if (p.copy) { el.dataset.copy = p.copy.id; el.dataset.copyOf = p.copy.of; }       // a temporary copy of the table p.copy.of
    const it = { el, title: p.title || '', data: p.data, gen: this.gen || 0, copy: p.copy || null };
    const body = h('div', { class: 'body' });
    const tools = h('div', { class: 'tools' });
    const title = h('h2', { title: p.title || '' }, p.title || '');
    it.titleEl = title;
    // the panel is as wide as its table, not its title (the desk, 27.11.2026): the header takes the panel's width and never
    // sets it - the title wraps to two lines at most (all of it in its tooltip), the tools come over the title's end on
    // hover, the header's buttons go under the title when there is no room beside it.  ▾ / ▸ folds it (every panel, the
    // pinned ones too; each browser remembers it)
    const fold = h('button', { class: 'fold', type: 'button', title: 'Daralt / aç', 'aria-expanded': collapsed ? 'false' : 'true' },
      collapsed ? '▸' : '▾');
    fold.dataset.action = 'fold';
    // (the sheet's range on the title's line, under the tools while they show)
    const ttl = h('div', { class: 'ttl' }, title, p.range && p.data ? h('span', { class: 'rng' }, p.range) : null, tools);
    const head = h('header', { class: 'vhead' }, fold, ttl);
    if (p.action === 'add-isin' && p.add) {
      // a list of bonds: add by ISIN (typed, or picked from the TRY government bonds)
      const b = h('button', { class: 'btn sm', type: 'button', title: p.add.title || 'ISIN ile ekle' }, '+ ISIN ekle');
      b.dataset.action = 'add-isin';
      b.addEventListener('click', () => openAddIsin(this.ctx, { book: p.add.book || this.book, list: p.add.ref, name: p.add.name,
        catalog: !!p.add.catalog, title: p.add.title }).catch(errorToast));
      head.appendChild(b);
    }
    if (p.quote && p.data) {
      // the rows of the table as a message for a broker or a client (Kota mesajı)
      const b = h('button', { class: 'btn sm', type: 'button', title: 'Seçtiğiniz satırların bid / ask\'ını sohbete atılacak metin olarak kopyalayın' }, 'Kota mesajı');
      b.dataset.action = 'quote';
      b.addEventListener('click', () => openQuoteMessage(this.id, Object.assign({}, p, { data: this.panelData(p, it) })));
      head.appendChild(b);
    }
    if (p.client_quote && p.data && !p.copy) {
      // "Kotasyon kopyala": the table's prices as a quote for a client (Türkçe / English), one row of it on a right click
      // (not on a temporary copy: the quote is built from the table itself, not from the copy's own inputs)
      head.appendChild(quoteButton(this.id, p));
    }
    if (p.trade && p.data && this.ctx.openTrade) {
      // a row of the table as a trade: Günlük İşlemler with its fields filled
      const b = h('button', { class: 'btn sm', type: 'button', title: 'Bir satırı seçin: Günlük İşlemler parite, yön, valör ve swap puanı dolu açılır' }, 'İşlem gir');
      b.dataset.action = 'trade';
      b.addEventListener('click', () => openTradeDialog(this.id, Object.assign({}, p, { data: this.panelData(p, it) }), this.ctx));
      head.appendChild(b);
    }
    if (p.action === 'ret' && this.ctx.openRet) {
      // the desk's RET curve: the editor (paste, shift, copy to send) is one click from the table
      const b = h('button', { class: 'btn sm', type: 'button', title: 'RET faizlerini değiştir, kaydır ya da göndermek için kopyala' }, 'RET faizlerini düzenle / kopyala');
      b.dataset.action = 'ret';
      b.addEventListener('click', () => this.ctx.openRet());
      head.appendChild(b);
    }
    if (p.action === 'toplu-islem' && p.data && !p.copy) {
      // TOPLU FORWARD: its rows with a Tutar into Günlük İşlemler's "Excel'den yapıştır" - preview, then "N satırı kaydet"
      const b = h('button', { class: 'btn sm', type: 'button',
        title: 'Tutar\'ı yazılı her satırı Günlük İşlemler\'in "Excel\'den yapıştır" penceresinde FX Forward olarak açar (Parite boşsa USDTRY; '
          + 'fiyat satırın gösterdiği): önizlemeden sonra "N satırı kaydet". Kaydedilen satırların Tutar\'ı silinir.' }, 'İşleme al');
      b.dataset.action = 'toplu-islem';
      b.addEventListener('click', () => { bookBulkForward(this.ctx); });
      head.appendChild(b);
    }
    if (p.action === 'hedge-islem' && p.data && !p.copy) {
      // DV01 Risk's "Hedge'i işle" (K5, 28.11.2026: A3): the hedge recommender's rows into Günlük İşlemler's
      // "Excel'den yapıştır" on OIS - its preview, then "N satırı kaydet" (hedgeislem.js)
      const b = h('button', { class: 'btn sm', type: 'button', title: 'Önerinin her satırını (aktif, yönü ve yuvarlanmış '
        + 'nominali olan) Günlük İşlemler\'in "Excel\'den yapıştır" penceresinde OIS olarak açar: vadeli OIS vadesiyle, FRA iki '
        + 'tarih arası OIS olarak. Önizlemeden sonra "N satırı kaydet".' }, 'Hedge\'i işle');
      b.dataset.action = 'hedge-islem';
      b.addEventListener('click', () => { bookHedge(this.ctx); });
      head.appendChild(b);
    }
    if (p.type === 'chart' && p.pick && !p.copy && this.ctx.setInputs) {
      // what the chart is drawn against (the ASW history: OIS / Offshore / İkisi) - the user's own cell behind it
      it.pick = this.chartPick(p.id, p.pick);
      head.appendChild(it.pick.el);
    }
    if (p.type === 'chart' && p.data && p.choice && p.choice.items) {
      // a chart sent drawn several ways (the interpolation chart: its horizon, OIS / Offshore): the way the user picked
      it.choice = this.chartChoice(p, it);
      it.data = it.choice.data();
      head.appendChild(it.choice.el);
    }
    el.appendChild(head);
    el.appendChild(body);

    if (p.error) {
      body.appendChild(h('div', { class: 'err' }, p.error));
    } else if (p.type === 'image') {
      const img = h('img', { class: 'sheet-image', src: p.src, alt: p.title || 'Resim', loading: 'lazy' });
      if (p.width) img.style.maxWidth = p.width + 'px';
      body.appendChild(img);
    } else if (p.type === 'chart') {
      if (p.data) {
        const chartHost = h('div');
        const tableHost = h('div', { class: 'hidden' });
        body.appendChild(chartHost);
        body.appendChild(tableHost);
        if (it.choice) body.appendChild(it.choice.body);            // (the way picked: its line and table under the chart)
        it.chart = new Chart(chartHost, it.data);
        const tb = h('button', { class: 'iconbtn', type: 'button', title: 'Grafiğin verisini tablo olarak göster' }, 'Tablo');
        tb.addEventListener('click', () => {
          const showTable = tableHost.classList.contains('hidden');
          if (showTable && !it.tableGrid) {
            it.tableGrid = new Grid({ data: chartTable(it.data), editable: false });
            tableHost.appendChild(it.tableGrid.el);
          }
          tableHost.classList.toggle('hidden', !showTable);
          chartHost.classList.toggle('hidden', showTable);
          body.classList.toggle('tbl', showTable);           // (a chart is never cut: its table is, as any table)
          tb.textContent = showTable ? 'Grafik' : 'Tablo';
        });
        tools.appendChild(tb);
      } else {
        body.appendChild(h('div', { class: 'chart-empty' }, 'Grafik bulunamadı'));
      }
    } else if (p.data) {
      const copy = p.copy ? p.copy.id : null;
      if (p.lead && p.lead.length) {
        // a temporary copy's strip of inputs it is computed from (the dates of TARİH ARASI FORWARD): the copy's own too
        it.leads = p.lead.map((l) => {
          const g = l.data ? new Grid({ book: this.book, data: l.data, editable: true, adhoc: false, copy, decimals: true }) : null;
          body.appendChild(h('div', { class: 'copy-lead' }, l.title ? h('div', { class: 'lead-title' }, l.title) : null,
            g ? g.el : h('div', { class: 'err' }, l.error || 'Tablo okunamadı')));
          return g;
        });
      }
      // each user hides columns of their own: by the page and the table, a column by its letter in the sheet (a copy: as
      // its table); a copy takes what is typed into its own inputs, never "Elle değer"; each user's own decimals; a
      // table drawn anew (another column order) hides again the rows "+ Satır" / "Tümü" hid
      it.grid = new Grid({ book: this.book, data: p.data, editable: true, adhoc: copy ? false : this.adhoc, copy, decimals: true,
        name: p.type === 'notes' ? null : 'v/' + this.id + '/' + (p.copy ? p.copy.of : p.id), order: true, tools,
        wrap: p.type !== 'notes', onBuild: () => { if (it.grow) it.grow(); if (it.limit) it.limit(); },
        rowItems: !copy && quoteRows(p.client_quote) ? (i) => quoteRowItems(this.id, p, it.grid, i) : null });
      body.appendChild(it.grid.el);
      // (the label of the columns the user hid: on the header's line of buttons, never under the tools)
      if (tools.__columns && tools.__columns.chip) head.appendChild(tools.__columns.chip);
      if (p.data.hc) {
        // Excel hides some columns of this table: say so, one click shows them
        const more = h('button', { class: 'iconbtn hc', type: 'button',
          title: 'Bu tabloda Excel\'de gizli ' + p.data.hc + ' sütun var. Göstermek için tıklayın (Yardımcı tablolar).' },
        '+' + p.data.hc + ' gizli sütun');
        more.addEventListener('click', () => this.toggleAll());
        head.appendChild(more);
      }
      const cp = h('button', { class: 'iconbtn', type: 'button', title: 'Tüm tabloyu kopyala (Excel\'e yapıştırılabilir)' }, 'Kopyala');
      cp.addEventListener('click', () => copyGrid(it.grid, false));
      tools.appendChild(cp);
      if (p.grow) this.growable(it, p, head);
      if (p.limit && p.limit.rows) this.limitable(it, p, head);
      if (p.card === 'bond') bondCardLinks(this.ctx, it.grid.el);            // ▸ opens the bond's card
      if (p.flags === 'dibs') bondFlags(this.ctx, it.grid.el);                // ☆ / ★: onto / off the trading list
    }
    if (p.type !== 'image' && !p.error && (p.data || p.type === 'chart')) {
      // the table on a launchpad, in the side drawer, in a window of its own (its key everywhere: page / table - a
      // temporary copy's own id); a calculator whose inputs are the user's own: "Geçici kopya aç" in the same menu
      const src = () => ({ view: this.id, panel: p.id, all: this.showAll || undefined, w: p.wide ? 12 : undefined });
      const acts = { pin: this.ctx.pinToDrawer, pop: this.ctx.popOut, copy: p.copyable ? () => this.openCopy(p) : null };
      tools.appendChild(addButton(src, acts));
      if (this.ctx.popOut) {
        const pop = h('button', { class: 'iconbtn', type: 'button', title: 'Ayrı pencerede aç (menüsüz, canlı – ikinci ekran için)' }, '⧉');
        pop.dataset.action = 'popout';
        pop.addEventListener('click', () => this.ctx.popOut(src()));
        tools.appendChild(pop);
      }
    }
    if (p.copy) {
      const rs = h('button', { class: 'iconbtn', type: 'button',
        title: 'Kopyanın kendi girdilerini sil: kopya tablonun değerlerini gösterir (tablonun kendisi değişmez)' }, 'Sıfırla');
      rs.dataset.action = 'copy-reset';
      rs.addEventListener('click', () => this.resetCopy(p));
      tools.appendChild(rs);
    }
    it.toggle = (now) => {
      el.classList.toggle('collapsed', now);
      fold.textContent = now ? '▸' : '▾';
      fold.setAttribute('aria-expanded', now ? 'false' : 'true');
      setPref(key, now ? '1' : '0');
      this.dedupeNotes();                         // (a folded panel's note is out of sight: the next one on screen says it)
    };
    fold.addEventListener('click', () => it.toggle(!el.classList.contains('collapsed')));
    if (p.copy) {
      const x = h('button', { class: 'iconbtn copy-x', type: 'button', title: 'Geçici kopyayı kapat (kopyaya yazılan değerler silinir)' }, '×');
      x.dataset.action = 'copy-close';
      x.addEventListener('click', () => this.closeCopy(p));
      tools.appendChild(x);
    }
    if (p.note) {
      // two lines of it, "devamı" the rest; a folded panel hides it (app.css)
      it.noteEl = h('div', { class: 'note' });
      it.noteFold = foldNote(it.noteEl);
      this.setNote(it, p.note, p.tw);
      el.appendChild(it.noteEl);
    }
    this.items.set(p.id, it);
    return el;
  }

  /**
   * A chart's small selector ({ref, book, value, options, default}: the ASW history against OIS / Offshore / İkisi): a
   * click writes the user's own cell behind it (the same cell Parametreler shows; the default leaves it to the workbook)
   * and the chart comes back drawn so.  Kept per user, as the page's other choices.
   */
  chartPick(pid, pick) {
    const cell = pick.ref.split('!').pop();
    const el = h('div', { class: 'seg small chart-pick', id: 'chart-pick-' + pid, role: 'group',
      title: 'Grafik neye göre çizilsin - sizin seçiminiz (Parametreler\'de ' + cell + ')' });
    const btns = new Map();
    let value = pick.value;
    const paint = (v) => {
      value = v;
      for (const [o, b] of btns) b.classList.toggle('on', o === v);
    };
    for (const o of pick.options) {
      const b = h('button', { type: 'button' }, o);
      b.dataset.pick = o;
      b.addEventListener('click', async () => {
        if (o === value) return;
        const was = value;
        paint(o);
        try {
          if (o === pick.default) await trackWrite(api.post('/api/reset', { book: pick.book, refs: [pick.ref] }));
          else await this.ctx.setInputs(pick.book, [{ ref: pick.ref, value: o }]);
          this.ctx.refreshNow();
        } catch (err) { paint(was); errorToast(err); }
      });
      btns.set(o, b);
      el.appendChild(b);
    }
    paint(value);
    return { el, set: paint };
  }

  /**
   * A chart the server sends drawn several ways ({groups: [{id, title, options, default}], items: {"3Y|OIS|Faiz": {data,
   * strip, line}}}: the interpolation chart's horizon, OIS / Offshore and rates / discount factors): small selectors on its
   * header draw the way picked at once, with its line and its table (``strip``) under the chart.  Each user's own choice,
   * kept in the browser as the page's tab is (a group added later: its default for a choice kept before it).  ``body``:
   * the line and the table, for the panel to place; ``data()``: the chart of the way picked; ``take(choice)``: every way as
   * it is now (a refresh), the way picked's chart back.
   */
  chartChoice(p, it) {
    const key = 'tto.pick.' + this.id + '.' + p.id;
    let src = p.choice;
    const kept = String(pref(key, '')).split('|');
    const value = src.groups.map((g, k) => (g.options.indexOf(kept[k]) >= 0 ? kept[k] : g.default));
    const el = h('div', { class: 'chart-choice', id: 'chart-choice-' + p.id });
    const line = h('div', { class: 'chart-line' });
    const strip = h('div', { class: 'chart-strip' });
    const body = h('div', { class: 'chart-extra' }, line, strip);
    let grid = null;
    const item = () => src.items[value.join('|')] || src.items[src.groups.map((g) => g.default).join('|')] || {};
    const extra = () => {
      const x = item();
      line.textContent = x.line || '';
      if (x.strip && grid) grid.update(x.strip, false);
      else if (x.strip) { grid = new Grid({ data: x.strip, editable: false }); strip.appendChild(grid.el); }
      strip.classList.toggle('hidden', !x.strip);
    };
    const segs = src.groups.map((g, k) => {
      const seg = h('div', { class: 'seg small chart-pick', role: 'group', title: g.title || '' });
      seg.dataset.group = g.id;
      for (const o of g.options) {
        const b = h('button', { type: 'button' }, o);
        b.dataset.pick = o;
        b.addEventListener('click', () => {
          if (value[k] === o) return;
          value[k] = o;
          setPref(key, value.join('|'));
          paint();
          extra();
          it.data = item().data || null;
          if (it.chart && it.data) it.chart.update(it.data);
          if (it.tableGrid && it.data) it.tableGrid.update(chartTable(it.data), false);
        });
        seg.appendChild(b);
      }
      el.appendChild(seg);
      return seg;
    });
    const paint = () => segs.forEach((seg, k) => { for (const b of seg.children) b.classList.toggle('on', b.dataset.pick === value[k]); });
    paint();
    extra();
    return {
      el,
      body,
      data: () => item().data || null,
      take: (choice) => {
        if (choice && choice.items) src = choice;
        extra();
        return item().data || null;
      },
    };
  }

  // ------------------------------------------------------------------ temporary copies of a calculator
  /** "Geçici kopya aç": the table once more, right under it, with inputs of its own (kept until it is closed: ×). */
  async openCopy(p) {
    try {
      const res = await api.post('/api/copies/open', { view: this.id, panel: p.id });
      toast('"' + (p.title || p.id) + ' · kopya ' + res.copy.n + '" açıldı: kendi girdileriyle, yalnızca sizde', 'ok', 4200);
      await this.rebuild(res.copy.pid);
    } catch (err) { errorToast(err); }
  }

  /** ×: the copy goes, with what was typed into it (asked first when anything was). */
  async closeCopy(p) {
    const it = this.items.get(p.id);
    const grids = it ? [it.grid].concat(it.leads || []).filter(Boolean) : [];
    const typed = grids.some((g) => g.data && g.data.rows.some((row) => row.some((c) => c && c.m === 1)));
    if (typed && !(await confirmDialog('Geçici kopyayı kapat', '"' + (it.title || p.title) + '" kapatılır; kopyaya yazdığınız değerler '
      + 'silinir. Tablonun kendisi değişmez.', 'Kapat'))) return;
    try {
      const res = await api.post('/api/copies/close', { copy: p.copy.id });
      toast('Kopya ' + p.copy.n + ' kapatıldı' + (res.layout ? ' (launchpad / yan paneldeki kutusu da)' : ''), 'ok', 2600);
      if (res.layout) loadLayout();
      await this.rebuild();
    } catch (err) { errorToast(err); }
  }

  /** "Sıfırla" of a copy: its own values go - it shows the table's again. */
  async resetCopy(p) {
    try {
      const res = await api.post('/api/copies/reset', { copy: p.copy.id });
      toast((res.reset || 0) + ' değer silindi: kopya ' + p.copy.n + ' tablonun değerlerini gösteriyor', 'ok', 2600);
      this.ctx.refreshNow();
    } catch (err) { errorToast(err); }
  }

  /** The page as the server has it now (a copy opened or closed), on the tab it was; ``focus``: a panel to bring into view. */
  async rebuild(focus) {
    const data = await this.fetch();
    if (this.dead) return;
    this.build(data);
    if (focus) this.focusPanel(focus);
  }
}
