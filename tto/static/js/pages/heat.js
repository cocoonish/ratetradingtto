// Eğri Hareketi: a heat map of the curves - every point's change since the previous close, the day's open or a
// reference taken on purpose (the morning meeting): OIS, offshore and their difference by tenor, the VİOP contracts,
// the bonds of the trading list.  Red: up (a rate, a spread higher), blue: down; the deeper, the larger against the
// day's largest move.  A click on a point watches it or sets an alarm on it.
import { api } from '../api.js';
import { h, clear, toast, errorToast, menu } from '../ui.js';
import { openWatchDialog, watchSubject } from '../alarms.js';

const BASES = [['close', 'Önceki kapanış', 'Bir önceki iş gününün kapanışına göre (OIS, TLREF, offshore: tarihçe; diğerleri: dashboard\'un kaydettiği kapanış)'],
  ['open', 'Açılış', 'Dashboard\'un bugün gördüğü ilk değere göre'],
  ['ref', 'Referans', '"Referansı şimdi al" ile alınan seviyelere göre (ör. sabah toplantısı)']];
const KEY = 'tto.heat.basis';
const isNum = (v) => typeof v === 'number' && isFinite(v);

function savedBasis() {
  try { const v = localStorage.getItem(KEY); return BASES.some((b) => b[0] === v) ? v : 'close'; } catch (e) { return 'close'; }
}

function rgbOf(name) {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '128, 128, 128';
}

/** The colour of a move: red up, blue down, deeper as it nears the scale's end; nothing for no move. */
function paint(td, chg, cap) {
  if (!isNum(chg) || Math.abs(chg) < 0.05) { td.style.background = ''; return; }
  const t = Math.min(1, Math.abs(chg) / cap);
  const c = 'rgba(' + rgbOf(chg > 0 ? '--heat-up' : '--heat-down') + ', ' + (0.12 + 0.6 * t).toFixed(3) + ')';
  td.style.background = 'linear-gradient(' + c + ', ' + c + '), var(--heat-mid)';
}

export class HeatPage {
  constructor(host, ctx) {
    this.host = host;
    this.ctx = ctx;
    this.basis = savedBasis();
    this.data = null;
    this.build();
  }

  build() {
    const tools = h('div', { class: 'page-tools' });
    this.seg = h('div', { class: 'seg', id: 'heat-basis' });
    for (const [v, t, tip] of BASES) {
      const b = h('button', { type: 'button', title: tip }, t);
      b.dataset.v = v;
      b.classList.toggle('on', v === this.basis);
      b.addEventListener('click', () => {
        this.basis = v;
        try { localStorage.setItem(KEY, v); } catch (e) { /* not kept */ }
        for (const x of this.seg.children) x.classList.toggle('on', x === b);
        this.refresh();
      });
      this.seg.appendChild(b);
    }
    const ref = h('button', { class: 'btn', type: 'button', id: 'heat-ref', title: 'Şimdiki seviyeleri referans al (ör. sabah toplantısı); "Referans"a göre değişim o andan beri gösterilir' }, 'Referansı şimdi al');
    ref.addEventListener('click', () => this.takeRef());
    this.info = h('span', { class: 'muted', id: 'heat-info' });
    this.legend = h('span', { class: 'heat-legend', id: 'heat-legend' });
    tools.appendChild(h('span', { class: 'muted' }, 'Değişim:'));
    tools.appendChild(this.seg);
    tools.appendChild(ref);
    tools.appendChild(this.legend);
    tools.appendChild(this.info);
    this.host.appendChild(tools);
    this.box = h('div', { id: 'heat-panels' });
    this.host.appendChild(this.box);
  }

  async load() { await this.refresh(); }

  async refresh() {
    const d = await api.get('/api/heat?basis=' + this.basis);
    this.data = d;
    this.draw(d);
  }

  draw(d) {
    clear(this.legend);
    this.legend.appendChild(h('span', null, 'düştü −' + d.cap + ' bp'));
    this.legend.appendChild(h('span', { class: 'bar' }));
    this.legend.appendChild(h('span', null, '+' + d.cap + ' bp yükseldi'));
    const base = (BASES.find((b) => b[0] === d.basis) || BASES[0])[1].toLowerCase();
    this.info.textContent = d.basis === 'ref' && !d.ref_at ? 'Bugün referans alınmadı: "Referansı şimdi al"'
      : 'Değişim ' + (d.basis === 'ref' ? 'referanstan (' + d.ref_at + ')' : base + 'tan') + ' · ' + d.time;
    const box = clear(this.box);
    for (const p of d.panels) {
      const t = h('table', { class: 'heat', 'data-panel': p.id });
      t.appendChild(h('tr', null, h('th', { class: 'row' }, ''), ...p.cols.map((c) => h('th', { title: c.tip || null }, c.label))));
      for (const row of p.rows) {
        const tr = h('tr', null, h('th', { class: 'row' }, row.name));
        for (const c of row.cells) {
          if (!c) { tr.appendChild(h('td', { class: 'none' })); continue; }
          const has = isNum(c.chg);
          const td = h('td', { class: 'hc' + (has ? '' : ' nochg'),
            title: c.label + '\nŞimdi: ' + (c.now_text || '–') + (c.base_text ? '\n' + (d.basis === 'close' ? 'Önceki kapanış' + (c.base_day ? ' (' + c.base_day + ')' : '')
              : d.basis === 'open' ? 'Açılış' : 'Referans') + ': ' + c.base_text : '') + (has ? '\nDeğişim: ' + c.chg_text : '\nDeğişim: karşılaştıracak değer yok') },
          h('div', { class: 'c' }, has ? c.chg_text.replace(' bp', '') : '–'), h('div', { class: 'l' }, c.now_text || ''));
          paint(td, c.chg, d.cap);
          td.addEventListener('click', (e) => this.pick(c, e));
          tr.appendChild(td);
        }
        t.appendChild(tr);
      }
      const body = h('div', { class: 'body heat-wrap' }, t);
      box.appendChild(h('section', { class: 'panel wide', id: 'heat-' + p.id }, h('header', null, h('h2', null, p.title)), body));
    }
  }

  pick(c, e) {
    menu(e.clientX, e.clientY, [{ header: c.label },
      { label: 'İzlemeye ekle', action: () => watchSubject(this.ctx, c.subject) },
      { label: 'Alarm kur…', action: () => openWatchDialog(this.ctx, { subject: c.subject, focus: 'alarm' }) },
      { label: 'Hareket alarmı…', action: () => openWatchDialog(this.ctx, { subject: c.subject, focus: 'alarm', mode: 'move' }) }]);
    e.stopPropagation();
  }

  async takeRef() {
    try {
      const r = await api.post('/api/heat/ref', {});
      toast(r.count + ' noktanın referansı alındı (' + r.at + ')', 'ok');
      if (this.basis !== 'ref') {
        this.basis = 'ref';
        try { localStorage.setItem(KEY, 'ref'); } catch (x) { /* not kept */ }
        for (const x of this.seg.children) x.classList.toggle('on', x.dataset.v === 'ref');
      }
      this.ctx.refreshNow();
    } catch (err) { errorToast(err); }
  }

  destroy() {}
}
