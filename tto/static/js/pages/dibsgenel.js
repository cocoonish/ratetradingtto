// DİBS RV · Genel (tto/dibsgenel.py): the trading list's bonds at a glance - the zero-coupon curve (Nelson-Siegel) fitted
// to the fixed coupon bonds now, the yield curve, DİBS ASW's two ASW charts, DİBS RV's switch / pair table and DİBS ASW's
// history as their own pages draw them (/api/panels) - and a link to the bond table's one home, DİBS Trading's summary
// (the desk, 28.11.2026: "kagit kismi cok duzensiz ve her sey her yerde gibi"; Genel's table moved there, its columns
// under "Sütunlar" → RV).  Nothing is typed here: the inputs are the hesap tablosu tabs' - a click on one shown here (a
// setting, a cell of the switch table) opens it there, selected.
import { api } from '../api.js';
import { h, clear, foldNote } from '../ui.js';
import { Grid } from '../grid.js';
import { Chart } from '../chart.js';
import { num } from '../format.js';

const TAB_TITLE = { dibs: 'RV hesap tablosu', asw: 'ASW hesap tablosu' };

/** An input of another tab opened there: the page, the panel in view, then the cell selected once the page is ready. */
export function openInput(ctx, view, panel, ref) {
  ctx.goto(view, panel);
  if (!ref) return;
  const t0 = Date.now();
  const tick = () => {
    const st = window.tto && window.tto.state;
    const ready = st && st.pageId === view && st.page && st.page.ready;
    const td = ready && window.tto.findCell ? window.tto.findCell(ref) : null;
    if (td) {
      td.scrollIntoView({ block: 'center', inline: 'nearest' });
      td.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, button: 0 }));
      document.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
      return;
    }
    if (Date.now() - t0 < 10000) setTimeout(tick, 120);
  };
  setTimeout(tick, 60);
}

/** A panel of the page: its note two lines, "devamı" the rest (B2, 28.11.2026; ``setNote`` keeps the fold's button). */
function panel(id, title, opts = {}) {
  const body = h('div', { class: 'body' }, h('div', { class: 'empty dg-wait' }, 'hesaplanıyor…'));
  const text = h('span', { class: 'dg-note-text' }, opts.note || '');
  const note = h('div', { class: 'note' + (opts.note ? '' : ' hidden') }, text);
  foldNote(note);
  const el = h('section', { class: 'panel' + (opts.wide ? ' wide' : '') + (opts.chart ? ' chart' : ''), id },
    h('header', null, h('h2', null, title), opts.link || null), body, note);
  const setNote = (t) => { text.textContent = t || ''; note.classList.toggle('hidden', !t); };
  return { el, body, note, setNote, title: el.querySelector('h2') };
}

export class DibsGenelPage {
  constructor(host, ctx) {
    this.host = host;
    this.ctx = ctx;
    this.charts = {};
    this.mirrorGrids = {};
    this.mirrorHave = {};                                  // key -> {gen, as}: what the browser has of a mirrored panel
    this.folds = {};                                       // key -> {all, btn}: a mirrored list's rows folded or all shown
    this.build();
  }

  build() {
    const tools = h('div', { class: 'page-tools dg-tools' });
    this.fitLine = h('span', { class: 'dg-fit', id: 'dg-fit' }, h('span', { class: 'muted' }, 'Sıfır kupon eğrisi hesaplanıyor…'));
    this.info = h('span', { class: 'muted', id: 'dg-info' });
    tools.append(this.fitLine, h('span', { class: 'grow' }), this.info);
    this.host.appendChild(tools);
    this.settings = h('div', { class: 'chips dg-settings', id: 'dg-settings' });
    this.host.appendChild(this.settings);
    // the bond table's one home: DİBS Trading's summary (Genel's table moved there - its columns under Sütunlar → RV)
    this.trading = h('div', { class: 'dg-trading', id: 'dg-trading' }, h('span', { class: 'muted' }, 'hesaplanıyor…'));
    this.host.appendChild(this.trading);
    const panels = h('div', { class: 'panels' });
    this.yield = panel('dg-yield', 'Getiri eğrisi', { wide: true, chart: true });
    this.aswOis = panel('dg-asw-ois', 'ASW · OIS', { chart: true });
    this.aswFx = panel('dg-asw-fx', 'ASW · FX swap', { chart: true });
    this.sw = panel('dg-switch', 'Switch / pair', { wide: true, link: this.tabLink('dibs', 'B4') });
    this.histSel = panel('dg-hist-sel', 'ASW geçmişi · seçili kâğıtlar', { link: this.tabLink('asw', 'sel') });
    this.hist = panel('dg-hist', 'ASW geçmişi', { chart: true, link: this.tabLink('asw', 'chart1') });
    for (const p of [this.yield, this.aswOis, this.aswFx, this.sw, this.histSel, this.hist]) panels.appendChild(p.el);
    this.host.appendChild(panels);
    this.mirrorPanels = { asw_ois: this.aswOis, asw_fx: this.aswFx, switch: this.sw, hist_sel: this.histSel, hist: this.hist };
  }

  tabLink(view, panelId) {
    const a = h('a', { href: '#/' + view + '?p=' + encodeURIComponent(panelId), class: 'hc', title: TAB_TITLE[view] + ' sekmesinde aç: girdiler orada yazılır' },
      TAB_TITLE[view] + ' →');
    return a;
  }

  async load() { await this.refresh(); }

  async refresh() {
    const d = await api.get('/api/dibs/genel');
    this.data = d;
    if (!d.ok) {
      clear(this.trading).appendChild(h('div', { class: 'empty' }, d.why || 'Veri yok'));
      return;
    }
    this.drawFit(d);
    this.drawSettings(d.settings || []);
    this.drawTrading(d.trading || {});
    this.drawChart('yield', this.yield, d.chart);
    this.yield.title.textContent = d.chart.title || 'Getiri eğrisi';
    this.yield.setNote('Her kâğıt kalan vadesinde bileşik getirisiyle (DİBS RV!T); kırmızı çizgi uydurulan sıfır kupon eğrisinin par '
      + 'getirisi (eğride temiz fiyatı 100 olan kâğıdın getirisi), kesik çizgi zero faizi (ikisi de yıllık bileşik); yeşil DİBS RV\'nin '
      + 'kâğıdın vadesindeki OIS par faizi (X). Kâğıtların bu eğriye göre model getirisi, ucuz / pahalısı ve adil fiyatı DİBS Trading\'in '
      + 'özetinde (Sıfır kupon eğrisi sütunları).');
    await this.loadMirrors(d.mirrors || []);
  }

  /** The link to the bond table's one home: DİBS Trading's summary, how many bonds of which kind it lists, the RV view. */
  drawTrading(t) {
    clear(this.trading);
    const kinds = (t.kinds || []).map((k) => k.title + ' ' + k.n).join(' · ');
    const go = h('a', { href: '#/' + (t.view || 'dibslive') + '?p=' + encodeURIComponent(t.panel || 'L0'), class: 'btn sm', id: 'dg-trading-link',
      title: 'Kâğıt tablosunun tek evi: DİBS Trading → Trading listesi · özet. Sütunlar → Görünüm: Trading / RV / Risk / Tümü' },
    (t.title || 'Trading listesi · özet') + ' →');
    go.addEventListener('click', (e) => { e.preventDefault(); this.ctx.goto(t.view || 'dibslive', t.panel || 'L0'); });
    this.trading.append(h('b', null, 'Kâğıt tablosu: '), go,
      h('span', { class: 'muted' }, ' DİBS Trading\'de, ' + (t.n || 0) + ' kâğıt' + (kinds ? ' (' + kinds + ')' : '')
        + ' · OIS ve FX swap ASW\'si, eğriler, adil getiri / fiyat, ucuz / pahalı, sinyal ve sıfır kupon eğrisi orada: Sütunlar → Görünüm: '
        + (t.preset || 'RV')));
  }

  drawFit(d) {
    const f = d.fit || {};
    clear(this.fitLine);
    if (!f.ok) {
      this.fitLine.appendChild(h('span', { class: 'soft' }, 'Sıfır kupon eğrisi uydurulamadı: ' + (f.why || '')));
    } else {
      const pct = (v) => num(v, 2, false) + '%';
      const beta = f.beta.map((b, i) => 'β' + i + ' ' + num(b, 2, false)).join(' · ');
      const tau = (f.tau || []).map((t, i) => 'τ' + (i + 1) + ' ' + num(t, 2, false)).join(' · ');
      const zero = Object.entries(f.zero || {}).map(([k, v]) => k + ' ' + pct(v)).join(' · ');
      const bills = f.n_bills || 0;
      this.fitLine.append(h('b', null, 'Sıfır kupon eğrisi (' + (f.model || '') + ', canlı): '),
        h('span', { title: 'Uydurmanın kalıntılarının karekök ortalaması (uydurulan sabit kuponlular, basit getiri)' }, 'RMSE ' + num(f.rmse, 1, false) + ' bp'),
        typeof f.loo === 'number' ? h('span', { title: 'Birini dışarıda bırak: uydurulan her kâğıt, eğri o olmadan yeniden uydurulunca (τ aynı) eğriden ne kadar uzak - '
          + 'eğrinin görmediği bir kâğıdı ne kadar tutturduğu (karekök ortalaması)' }, ' · LOO RMSE ' + num(f.loo, 1, false) + ' bp') : '',
        ' · ' + f.n_fit + ' sabit kuponluya uyduruldu' + (bills ? ', ' + bills + ' bono eğriye göre ölçüldü (uydurmaya girmez)' : '')
        + (f.down ? ' · ' + f.down + ' kâğıdın ağırlığı düşürüldü (Huber)' : '') + ' · ',
        h('span', { title: 'β yüzde, τ yıl; eğrinin kendi faizleri yanında' }, beta + ' · ' + tau),
        zero ? ' · zero ' + zero : '');
    }
    this.info.textContent = 'FX swap ima eğrisi: ' + (d.fx && d.fx.swapped ? d.fx.swapped + ' vade fiyatlı' : 'fiyat yok') + ' · ' + (d.time || '');
    this.info.title = d.fx ? d.fx.curve : '';
  }

  drawSettings(items) {
    clear(this.settings);
    this.settings.appendChild(h('span', { class: 'lbl' }, 'RV hesap tablosunun ayarları'));
    for (const s of items) {
      const a = h('a', { href: '#/' + s.view + '?p=' + encodeURIComponent(s.panel), class: 'chip dg-set', title: s.ref + ': RV hesap tablosunda yazılır (tıklayınca orada açılır)' },
        s.label + ': ', h('b', null, s.t || '—'));
      a.dataset.ref = s.ref;
      a.addEventListener('click', (e) => { e.preventDefault(); openInput(this.ctx, s.view, s.panel, s.ref); });
      this.settings.appendChild(a);
    }
  }

  drawChart(key, p, data) {
    if (!data) return;
    if (this.charts[key]) { this.charts[key].update(data); return; }
    clear(p.body);
    const host = h('div');
    p.body.appendChild(host);
    this.charts[key] = new Chart(host, data);
  }

  async loadMirrors(mirrors) {
    if (!mirrors.length) return;
    let res;
    try {
      // (asked as a launchpad asks: since the generation it has them of - a panel that did not change comes back "unchanged")
      res = await api.post('/api/panels', { items: mirrors.map((m) => Object.assign({ view: m.view, panel: m.panel, key: m.key },
        this.mirrorHave[m.key] ? { since: this.mirrorHave[m.key].gen, as: this.mirrorHave[m.key].as } : {})) });
    } catch (err) { console.warn('DİBS RV · Genel: hesap tablosu panelleri alınamadı', err); return; }
    for (const m of mirrors) {
      const p = this.mirrorPanels[m.key];
      const ans = (res.panels || {})[m.key];
      if (!p || !ans || ans.unchanged) continue;
      if (ans.missing) {
        delete this.mirrorHave[m.key];
        clear(p.body).appendChild(h('div', { class: 'empty' }, ans.error || 'Tablo bulunamadı'));
        continue;
      }
      const e = ans.entry;
      if (!e) continue;
      if (typeof ans.gen === 'number' && ans.as) this.mirrorHave[m.key] = { gen: ans.gen, as: ans.as };
      p.title.textContent = e.title || m.title;
      if (e.note) p.setNote(e.note);
      if (e.type === 'chart') this.drawChart(m.key, p, e.data);
      else this.drawMirror(m, p, e, ans.book);
    }
  }

  /** A table of a hesap tablosu tab, read-only: a click on one of its inputs opens it in its tab. */
  drawMirror(m, p, e, book) {
    const g = this.mirrorGrids[m.key];
    if (g) { if (!g.update(e.data)) g.replace(e.data); this.foldRows(m, p, g, e.grow); return; }
    clear(p.body);
    const grid = new Grid({ book, data: e.data, editable: false });
    grid.el.classList.add('dg-mirror');
    grid.el.dataset.view = m.view;
    grid.el.addEventListener('click', (ev) => {
      const td = ev.target.closest('td');
      if (!td || td.__i === undefined) return;
      const cell = grid.cell(td.__i, td.__j);
      const ref = grid.ref(td.__i, td.__j);
      if (cell && cell.i && ref) openInput(this.ctx, m.view, m.panel, ref);
    });
    this.mirrorGrids[m.key] = grid;
    p.body.appendChild(grid.el);
    // (no row in use: one line instead of the empty table - "Genel'de switch yokken 1676×227 boş tablo yerine tek satır",
    // the desk's 28.11.2026; "Tümü (N)" shows the table, a click on one of its inputs opens it in its tab)
    const none = h('div', { class: 'muted dg-none hidden', id: 'dg-none-' + m.key });
    p.body.appendChild(none);
    const hint = h('div', { class: 'muted dg-hint' }, 'Salt okunur: girdiler (altı çizili hücreler) ' + TAB_TITLE[m.view]
      + ' sekmesinde yazılır - tıklayınca orada açılır.');
    p.body.appendChild(hint);
    this.foldRows(m, p, grid, e.grow);
  }

  /**
   * A mirrored list's rows as its own tab shows them (27.11.2026, "Düzen"): the table's ``grow`` - the switch / pair
   * rows in use and one empty one (a pair is typed there, in its tab); "Tümü (N)" shows every row, "Dolu satırlar" folds
   * them again.  With no row in use the table is one line saying so (28.11.2026).  Display only: the rows are all there.
   */
  foldRows(m, p, grid, spec) {
    const d = grid.data;
    if (!spec || !d || !d.c || !d.r) return;
    const k = this.folds[m.key] || (this.folds[m.key] = { all: false, btn: null });
    if (!k.btn) {
      k.btn = h('button', { class: 'iconbtn grow-all dg-fold', type: 'button', id: 'dg-fold-' + m.key,
        title: 'Bütün satırları göster / yalnızca dolu olanları' });
      k.btn.addEventListener('click', () => { k.all = !k.all; this.foldRows(m, p, grid, spec); });
      p.el.querySelector('header').appendChild(k.btn);
    }
    const j = d.c.indexOf(spec.key);
    const first = spec.first || 1;
    const last = spec.last || Infinity;
    let filled = first - 1;
    d.r.forEach((r, i) => {
      const c = (d.rows[i] || [])[j];
      if (r >= first && r <= last && c && String(c.t || '').trim()) filled = Math.max(filled, r);
    });
    const upto = filled + Math.max(1, spec.extra || 1);
    const trs = [...grid.el.querySelectorAll('tbody > tr')];
    trs.forEach((tr, i) => {
      const r = d.r[i];
      tr.classList.toggle('grow-hidden', !k.all && typeof r === 'number' && r > upto && r <= last);
    });
    k.btn.textContent = k.all ? 'Dolu satırlar' : 'Tümü (' + trs.length + ')';
    const empty = filled < first && !k.all;
    const none = p.body.querySelector('.dg-none');
    grid.el.classList.toggle('hidden', empty);
    if (none) {
      none.classList.toggle('hidden', !empty);
      clear(none);
      if (empty) {
        none.append(m.title + ' yok: ' + TAB_TITLE[m.view] + ' sekmesinde yazılır ', this.tabLink(m.view, m.panel),
          ' · Tümü (' + trs.length + ') boş tabloyu gösterir');
      }
    }
  }

  destroy() {
    for (const c of Object.values(this.charts)) c.destroy();
    this.charts = {};
  }
}
