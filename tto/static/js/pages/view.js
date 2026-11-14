// Generic workbook page: a set of panels (tables and charts) defined by a view on the server.
// A page with many tables comes in tabs ("sections" of the view): one group of tables at a time, the
// calculators first; the search box and "Tümü" look across all of them.
import { openAddIsin, bondCardLinks, bondFlags } from '../bonds.js';
import { api } from '../api.js';
import { h, clear, toast, errorToast, confirmDialog } from '../ui.js';
import { Grid, copyGrid, findCell } from '../grid.js';
import { Chart, chartTable } from '../chart.js';
import { openQuoteMessage, openTradeDialog } from '../quote.js';

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
  }

  async load() {
    clear(this.host);
    this.host.appendChild(h('div', { class: 'loading' }, 'Hesaplanıyor…'));
    const data = await this.fetch();
    if (this.dead) return;
    this.build(data);
  }

  fetch() {
    return api.get('/api/view/' + encodeURIComponent(this.id), this.showAll ? { all: 1 } : null);
  }

  signature(data) {
    return data.panels.map((p) => p.id + ':' + p.type).join('|') + '#' + (data.sections || []).map((s) => s.id + '=' + s.panels.join(',')).join('|')
      + '#' + (data.pinned || []).join(',');
  }

  /** What a table shows right now (refreshed in place since the page was built): what a message or a trade is made of. */
  panelData(p, it) {
    const cur = this.items.get(p.id) || it;
    return (cur.grid && cur.grid.data) || cur.data || p.data;
  }

  async refresh() {
    const data = await this.fetch();
    if (this.dead) return;
    if (this.signature(data) !== this.order) { this.build(data); return; }
    for (const p of data.panels) {
      const it = this.items.get(p.id);
      if (!it) continue;
      if (p.type === 'chart') {
        it.data = p.data;
        if (!it.el.isConnected) { it.stale = true; continue; }       // drawn when its tab is opened
        if (it.chart && p.data) it.chart.update(p.data);
        if (it.tableGrid && p.data) it.tableGrid.update(chartTable(p.data), false);
      } else if (it.grid && p.data) {
        it.data = p.data;
        it.grid.update(p.data, true);
        if (it.grow) it.grow();
      }
    }
    this.showOverrides(data.panels);
  }

  destroy() {
    this.dead = true;
    for (const it of this.items.values()) if (it.chart) it.chart.destroy();
    this.items.clear();
  }

  build(data) {
    for (const it of this.items.values()) if (it.chart) it.chart.destroy();
    this.items.clear();
    this.book = data.book;
    this.order = this.signature(data);
    this.ids = data.panels.map((p) => p.id);
    this.sections = data.sections || [];
    this.pinned = data.pinned || [];
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
    handBtn.addEventListener('click', () => {
      this.adhoc = !this.adhoc;
      setHandMode(this.adhoc);
      handBtn.classList.toggle('on', this.adhoc);
      this.host.classList.toggle('hand', this.adhoc);
      for (const it of this.items.values()) if (it.grid) it.grid.opts.adhoc = this.adhoc;
      toast(this.adhoc ? 'Elle değer açık: her hücreye yazabilirsiniz (yalnızca sizde değişir; silince formül geri gelir)' : 'Elle değer kapalı', '', 3600);
    });
    const resetBtn = h('button', { class: 'btn sm', type: 'button', title: 'Bu çalışma kitabındaki kişisel girdilerimi sil' }, 'Girdilerimi sıfırla');
    resetBtn.addEventListener('click', async () => {
      const ok = await confirmDialog('Girdileri sıfırla',
        'Bu çalışma kitabındaki tüm kişisel girdileriniz silinir ve dosyadaki varsayılan değerlere dönülür. Kayıtlı senaryolarınız etkilenmez.', 'Sıfırla');
      if (!ok) return;
      try {
        const res = await api.post('/api/reset', { book: this.book });
        toast((res.reset || 0) + ' girdi sıfırlandı', 'ok');
        this.ctx.refreshNow();
      } catch (err) { errorToast(err); }
    });
    this.overChip = h('button', { class: 'btn sm warnchip hidden', type: 'button', id: 'hand-values',
      title: 'Bu sayfada formülün yerine elle yazdığınız değerler var. Tıklayın: hepsi formüle döner.' });
    this.overChip.addEventListener('click', () => this.restoreFormulas());
    this.host.appendChild(h('div', { class: 'page-tools' }, search, allBtn, handBtn, resetBtn, this.overChip, h('span', { class: 'grow' }),
      h('span', { class: 'legend' },
        h('span', null, h('i', { class: 'sw-in' }), 'kişisel girdi'),
        h('span', { title: 'Piyasadan ya da başka bir hücreden dolan girdi: üzerine yazabilirsiniz, silince otomatik değer geri gelir' },
          h('i', { class: 'sw-auto' }), 'otomatik (üzerine yazılabilir)'),
        h('span', null, h('i', { class: 'sw-sh' }), 'ortak girdi (herkes görür)'),
        h('span', null, h('i', { class: 'sw-hand' }), 'formül yerine elle değer'),
        h('span', { class: 'muted' }, data.ms + ' ms'))));

    if (data.links && data.links.length) {
      // the workbook's own "go to" links: other pages, straight to the table they point at
      const bar = h('div', { class: 'shortcuts' }, h('span', { class: 'lbl' }, 'Kısayollar'));
      for (const l of data.links) {
        const a = h('a', { class: 'chip', href: '#/' + l.page + (l.panel ? '?p=' + encodeURIComponent(l.panel) : ''),
          title: 'Excel\'deki köprü: ' + l.ref }, l.label);
        a.addEventListener('click', (e) => { e.preventDefault(); this.ctx.goto(l.page, l.panel); });
        bar.appendChild(a);
      }
      this.host.appendChild(bar);
    }
    if (data.note) this.host.appendChild(h('div', { class: 'banner' }, data.note));

    for (const p of data.panels) this.panel(p);              // built once; the tabs only decide which are on the page
    this.pinWrap = h('div', { class: 'panels pinned' });
    this.tabBar = h('div', { class: 'viewtabs', role: 'tablist' });
    this.tabBtns = new Map();
    for (const s of this.sections) this.tabBtns.set(s.id, this.tabButton(s.id, s.title, s.panels.length));
    if (this.sections.length) this.tabBtns.set(ALL, this.tabButton(ALL, 'Tümü', this.ids.length));
    this.secNote = h('div', { class: 'secnote hidden' });
    this.wrap = h('div', { class: 'panels' });
    if (this.pinned.length) this.host.appendChild(this.pinWrap);
    if (this.sections.length) this.host.appendChild(this.tabBar);
    this.host.appendChild(this.secNote);
    this.host.appendChild(this.wrap);
    this.layout();
    this.showOverrides(data.panels);
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
    const place = (host, id) => {
      const it = this.items.get(id);
      if (!it) return false;
      host.appendChild(it.el);
      if (it.stale && it.chart && it.data) { it.stale = false; it.chart.update(it.data); }
      return true;
    };
    while (this.wrap.firstChild) this.wrap.removeChild(this.wrap.firstChild);
    while (this.pinWrap.firstChild) this.pinWrap.removeChild(this.pinWrap.firstChild);
    for (const id of this.pinned) place(this.pinWrap, id);
    let shown = 0;
    let note = '';
    if (!this.sections.length) {
      for (const id of this.ids) if (hit(this.items.get(id))) shown += place(this.wrap, id) ? 1 : 0;
    } else if (q || this.tab === ALL) {
      const placed = new Set(this.pinned);
      for (const s of this.sections) {
        const ids = s.panels.filter((id) => !placed.has(id) && this.items.has(id) && hit(this.items.get(id)));
        if (!ids.length) continue;
        const head = h('div', { class: 'secthead' }, s.title, h('span', { class: 'n' }, String(ids.length)));
        this.wrap.appendChild(head);
        for (const id of ids) { placed.add(id); shown += place(this.wrap, id) ? 1 : 0; }
      }
    } else {
      const s = this.sections.find((x) => x.id === this.tab) || this.sections[0];
      note = s.note || '';
      for (const id of s.panels) if (this.pinned.indexOf(id) < 0) shown += place(this.wrap, id) ? 1 : 0;
    }
    if (!shown) this.wrap.appendChild(h('div', { class: 'empty' }, q ? 'Aramayla eşleşen tablo yok' : 'Bu sekmede tablo yok'));
    for (const [id, b] of this.tabBtns) b.classList.toggle('on', !q && id === this.tab);
    this.tabBar.classList.toggle('searching', !!q);
    this.secNote.textContent = q ? 'Arama sonucu: tüm sekmelerdeki eşleşen tablolar' : note;
    this.secNote.classList.toggle('hidden', !this.secNote.textContent);
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

  /** The <td> of a workbook cell wherever it is on this page; the tab that holds it is opened. */
  findCell(ref) {
    for (const [id, it] of this.items) {
      if (!it.grid) continue;
      const td = findCell(ref, it.el);
      if (td) { this.showPanel(id); return td; }
    }
    return null;
  }

  applyFilter() {
    this.layout();
  }

  showOverrides(panels) {
    this.overRefs = overridden(panels);
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
      const res = await api.post('/api/reset', { book: this.book, refs });
      toast((res.reset || 0) + ' hücre formüle döndü', 'ok');
      this.ctx.refreshNow();
    } catch (err) { errorToast(err); }
  }

  /**
   * A table with more rows than are in use (a list, a bulk pricing): the rows after the last filled one stay
   * out of the way but ``extra`` empty ones; "+ Satır" opens one more, "Tümü" all of them.
   */
  growable(it, p, head, tools) {
    const key = 'tto.grow.' + this.id + '.' + p.id;
    let extra = Math.max(1, Number(pref(key, String(p.grow.extra || 1))) || 1);
    let all = false;
    const more = h('button', { class: 'iconbtn grow-more', type: 'button', title: 'Bir boş satır daha göster' }, '+ Satır');
    const every = h('button', { class: 'iconbtn grow-all', type: 'button', title: 'Bütün satırları göster / yalnızca dolu olanları' }, 'Tümü');
    head.insertBefore(more, tools);
    head.insertBefore(every, tools);
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

  panel(p) {
    const key = 'tto.col.' + this.id + '.' + p.id;
    const collapsed = pref(key, p.collapsed ? '1' : '0') === '1';
    const el = h('section', { class: 'panel' + (p.wide ? ' wide' : '') + (p.type === 'chart' ? ' chart' : '') + (p.type === 'notes' ? ' notes' : '')
      + (p.hidden ? ' aux' : '') + (collapsed ? ' collapsed' : '') });
    el.dataset.panel = p.id;
    const it = { el, title: p.title || '', data: p.data };
    const body = h('div', { class: 'body' });
    const tools = h('div', { class: 'tools' });
    const title = h('h2', { title: p.title || '' }, p.title || '');
    const head = h('header', null, title);
    if (p.range && p.data) head.appendChild(h('span', { class: 'rng' }, p.range));
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
    head.appendChild(tools);
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
        it.chart = new Chart(chartHost, p.data);
        const tb = h('button', { class: 'iconbtn', type: 'button', title: 'Grafiğin verisini tablo olarak göster' }, 'Tablo');
        tb.addEventListener('click', () => {
          const showTable = tableHost.classList.contains('hidden');
          if (showTable && !it.tableGrid) {
            it.tableGrid = new Grid({ data: chartTable(it.data), editable: false });
            tableHost.appendChild(it.tableGrid.el);
          }
          tableHost.classList.toggle('hidden', !showTable);
          chartHost.classList.toggle('hidden', showTable);
          tb.textContent = showTable ? 'Grafik' : 'Tablo';
        });
        tools.appendChild(tb);
      } else {
        body.appendChild(h('div', { class: 'chart-empty' }, 'Grafik bulunamadı'));
      }
    } else if (p.data) {
      it.grid = new Grid({ book: this.book, data: p.data, editable: true, adhoc: this.adhoc });
      body.appendChild(it.grid.el);
      if (p.data.hc) {
        // Excel hides some columns of this table: say so, one click shows them
        const more = h('button', { class: 'iconbtn hc', type: 'button',
          title: 'Bu tabloda Excel\'de gizli ' + p.data.hc + ' sütun var. Göstermek için tıklayın (Yardımcı tablolar).' },
        '+' + p.data.hc + ' gizli sütun');
        more.addEventListener('click', () => this.toggleAll());
        head.insertBefore(more, tools);
      }
      const cp = h('button', { class: 'iconbtn', type: 'button', title: 'Tüm tabloyu kopyala (Excel\'e yapıştırılabilir)' }, 'Kopyala');
      cp.addEventListener('click', () => copyGrid(it.grid, false));
      tools.appendChild(cp);
      if (p.grow) this.growable(it, p, head, tools);
      if (p.card === 'bond') bondCardLinks(this.ctx, it.grid.el);            // ▸ opens the bond's card
      if (p.flags === 'dibs') bondFlags(this.ctx, it.grid.el);                // ☆ / ★: onto / off the trading list
    }
    const col = h('button', { class: 'iconbtn', type: 'button', title: 'Daralt / aç' }, collapsed ? '▸' : '▾');
    it.toggle = (now) => {
      el.classList.toggle('collapsed', now);
      col.textContent = now ? '▸' : '▾';
      setPref(key, now ? '1' : '0');
    };
    col.addEventListener('click', () => it.toggle(!el.classList.contains('collapsed')));
    tools.appendChild(col);
    if (p.note) el.appendChild(h('div', { class: 'note' }, p.note));
    this.items.set(p.id, it);
    return el;
  }
}
