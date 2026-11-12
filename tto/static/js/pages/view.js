// Generic workbook page: a set of panels (tables and charts) defined by a view on the server.
import { api } from '../api.js';
import { h, clear, toast, errorToast, confirmDialog } from '../ui.js';
import { Grid, copyGrid } from '../grid.js';
import { Chart, chartTable } from '../chart.js';

function pref(key, fallback) {
  try {
    const v = localStorage.getItem(key);
    return v === null ? fallback : v;
  } catch (e) { return fallback; }
}

function setPref(key, value) {
  try { localStorage.setItem(key, value); } catch (e) { /* ignore */ }
}

export class ViewPage {
  constructor(host, viewId, ctx) {
    this.host = host;
    this.id = viewId;
    this.ctx = ctx;
    this.items = new Map();
    this.order = '';
    this.showAll = pref('tto.all.' + viewId, '0') === '1';
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

  async refresh() {
    const data = await this.fetch();
    if (this.dead) return;
    const order = data.panels.map((p) => p.id + ':' + p.type).join('|');
    if (order !== this.order) { this.build(data); return; }
    for (const p of data.panels) {
      const it = this.items.get(p.id);
      if (!it) continue;
      if (p.type === 'chart') {
        it.data = p.data;
        if (it.chart && p.data) it.chart.update(p.data);
        if (it.tableGrid && p.data) it.tableGrid.update(chartTable(p.data), false);
      } else if (it.grid && p.data) {
        it.grid.update(p.data, true);
      }
    }
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
    this.order = data.panels.map((p) => p.id + ':' + p.type).join('|');
    clear(this.host);

    const search = h('input', { class: 'inp', type: 'search', placeholder: 'Tablo ara…', style: { width: '190px' }, value: this.filter });
    search.addEventListener('input', () => { this.filter = search.value; this.applyFilter(); });
    const allBtn = h('button', { class: 'btn sm' + (this.showAll ? ' on' : ''), type: 'button',
      title: 'Grafik verisi ve ara hesap tablolarını da göster' }, 'Yardımcı tablolar');
    allBtn.addEventListener('click', () => {
      this.showAll = !this.showAll;
      setPref('tto.all.' + this.id, this.showAll ? '1' : '0');
      this.load().catch(errorToast);
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
    this.host.appendChild(h('div', { class: 'page-tools' }, search, allBtn, resetBtn, h('span', { class: 'grow' }),
      h('span', { class: 'legend' },
        h('span', null, h('i', { class: 'sw-in' }), 'kişisel girdi'),
        h('span', null, h('i', { class: 'sw-sh' }), 'ortak girdi (herkes görür)'),
        h('span', { class: 'muted' }, data.ms + ' ms'))));

    if (data.note) this.host.appendChild(h('div', { class: 'banner' }, data.note));
    const wrap = h('div', { class: 'panels' });
    for (const p of data.panels) wrap.appendChild(this.panel(p));
    this.host.appendChild(wrap);
    this.applyFilter();
  }

  applyFilter() {
    const q = this.filter.trim().toLocaleLowerCase('tr');
    for (const it of this.items.values()) {
      const hit = !q || it.title.toLocaleLowerCase('tr').includes(q);
      it.el.classList.toggle('hidden', !hit);
    }
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
    head.appendChild(tools);
    el.appendChild(head);
    el.appendChild(body);

    if (p.error) {
      body.appendChild(h('div', { class: 'err' }, p.error));
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
      it.grid = new Grid({ book: this.book, data: p.data, editable: true });
      body.appendChild(it.grid.el);
      const cp = h('button', { class: 'iconbtn', type: 'button', title: 'Tüm tabloyu kopyala (Excel\'e yapıştırılabilir)' }, 'Kopyala');
      cp.addEventListener('click', () => copyGrid(it.grid, false));
      tools.appendChild(cp);
    }
    const col = h('button', { class: 'iconbtn', type: 'button', title: 'Daralt / aç' }, collapsed ? '▸' : '▾');
    col.addEventListener('click', () => {
      const now = !el.classList.contains('collapsed');
      el.classList.toggle('collapsed', now);
      col.textContent = now ? '▸' : '▾';
      setPref(key, now ? '1' : '0');
    });
    tools.appendChild(col);
    if (p.note) el.appendChild(h('div', { class: 'note' }, p.note));
    this.items.set(p.id, it);
    return el;
  }
}
