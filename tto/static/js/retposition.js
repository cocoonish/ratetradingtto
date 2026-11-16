// Günlük İşlemler · "Pozisyon ve maliyet": the desk's forwards per RET tenor - today's net TRY sold / bought, its cost
// (the volume-weighted rate of the net side), its P&L against the published RET mid and the OIS mid in TL, and the same
// over the last days.  The server's aggregation is the RET dialog's flow suggestions' own (tto/retflow.py): one
// implementation.  The source is the blotter's own trades only - never Broker Chat, never BIST swap quotes.
import { api } from './api.js';
import { h, clear } from './ui.js';
import { Grid, plainData, copyGrid } from './grid.js';
import { toolsOf } from './columns.js';
import { num, pct, isoToTr } from './format.js';

const REFRESH_MS = 4000;                 // at most this often (the blotter refreshes with every generation)

/** An amount in mn USD (one decimal); ``avg``: the average rate of that side, in the cell's tip. */
function amount(v, avg) {
  if (typeof v !== 'number') return { t: '', k: '' };
  const c = { t: num(v / 1e6, 1), v, k: 'n' };
  if (typeof avg === 'number') c.tip = 'Ortalama TRY faizi ' + pct(avg, 3);
  return c;
}

function signedAmount(v) {
  return typeof v === 'number' ? { t: (v > 0 ? '+' : '') + num(v / 1e6, 1), v, k: 'n', cls: v > 0 ? 'buy' : (v < 0 ? 'sell' : '') } : { t: '', k: '' };
}

function rate(v) {
  return typeof v === 'number' ? { t: pct(v, 3), v, k: 'n' } : { t: '', k: '' };
}

function pnl(v) {
  return typeof v === 'number' ? { t: (v > 0 ? '+' : '') + num(v, 0), v, k: 'n', cls: v > 0 ? 'buy' : (v < 0 ? 'sell' : '') } : { t: '', k: '' };
}

export class PositionPanel {
  constructor(ctx) {
    this.ctx = ctx;
    this.grid = null;
    this.last = 0;
    this.wanted = false;                 // brought into view once it is drawn (a link from the RET dialog)
    this.body = h('div', { class: 'body' });
    this.count = h('span', { class: 'muted' });
    this.note = h('div', { class: 'note', id: 'blotter-position-note' });
    const cp = h('button', { class: 'iconbtn', type: 'button', title: 'Tabloyu kopyala (Excel\'e yapıştırılabilir)' }, 'Kopyala');
    cp.addEventListener('click', () => { if (this.grid) copyGrid(this.grid); });
    const toRet = h('button', { class: 'iconbtn', type: 'button', id: 'blotter-position-ret', title: 'RET faizleri · Adil değer: akış önerileri bu tablonun akışından' },
      'RET adil değer →');
    toRet.addEventListener('click', () => { if (ctx.openRet) ctx.openRet({ tab: 'fair' }); });
    this.tools = h('div', { class: 'tools' }, toRet, cp);
    this.el = h('section', { class: 'panel wide position', id: 'blotter-position' },
      h('header', null, h('h2', null, 'Pozisyon ve maliyet · RET vadeleri (mn USD, K/Z TL)'), this.count, this.tools), this.body, this.note);
  }

  async refresh(force) {
    const now = Date.now();
    if (!force && now - this.last < REFRESH_MS) {
      // asked again too soon: once more when the time is up (what changed in between is not left out)
      if (!this.later) this.later = setTimeout(() => { this.later = null; if (this.el.isConnected) this.refresh(true); }, REFRESH_MS - (now - this.last));
      return;
    }
    this.last = now;
    let d;
    try {
      d = await api.get('/api/ret/position');
    } catch (err) {
      clear(this.body);
      this.grid = null;
      this.body.appendChild(h('div', { class: 'err' }, 'Pozisyon okunamadı: ' + err.message));
      return;
    }
    this.paint(d);
  }

  paint(d) {
    const n = d.lookback || 0;
    const header = ['Vade',
      { t: 'TRY sattık', tip: 'Bugün · vadeli USD alışı: masa TL faizini öder (RET bid\'i), payer. mn USD; ortalama faiz hücrenin ipucunda.' },
      { t: 'TRY aldık', tip: 'Bugün · vadeli USD satışı: masa TL faizini alır (RET ask\'ı), receiver. mn USD; ortalama faiz hücrenin ipucunda.' },
      { t: 'Net', tip: 'Bugün · mn USD: + net TRY sattık, − net TRY aldık' },
      { t: 'Maliyet %', tip: 'Bugün · net tarafın işlemlerinin tutarla ağırlıklı ortalama TRY faizi' },
      { t: 'K/Z RET mid', tip: 'Bugün · TL. Her işlem: DV01 (TL, payer +) × (yayınlanan RET mid\'inin işlemin gününde değeri − işlemin faizi). + masanın lehine' },
      { t: 'K/Z OIS mid', tip: 'Bugün · TL. Aynısı OIS mid zero faizine göre (spot → spot + işlemin günü, basit ACT/360)' },
      { t: n + ' gün net', tip: 'Önceki ' + n + ' iş günü ve bugün · mn USD' }, { t: 'Maliyet %', tip: 'Önceki ' + n + ' iş günü ve bugün' },
      { t: 'K/Z RET mid', tip: 'Önceki ' + n + ' iş günü ve bugün · TL' }, { t: 'K/Z OIS mid', tip: 'Önceki ' + n + ' iş günü ve bugün · TL' }];
    const line = (label, t, w, bold) => [{ t: label, k: 's', b: bold ? 1 : 0 },
      amount(t && t.sold, t && t.sold_avg), amount(t && t.bought, t && t.bought_avg), signedAmount(t && t.net), rate(t && t.cost),
      pnl(t && t.pnl_ret), pnl(t && t.pnl_ois), signedAmount(w && w.net), rate(w && w.cost), pnl(w && w.pnl_ret), pnl(w && w.pnl_ois)];
    const rows = (d.rows || []).map((r) => line(r.tenor, r.today, r.window, true));
    if (rows.length) {
      const tt = (d.total || {}).today, tw = (d.total || {}).window;
      const none = { t: '', k: '' };
      rows.push([{ t: 'Toplam', k: 's', b: 1 }, amount(tt && tt.sold), amount(tt && tt.bought), signedAmount(tt && tt.net), none,
        pnl(tt && tt.pnl_ret), pnl(tt && tt.pnl_ois), signedAmount(tw && tw.net), none, pnl(tw && tw.pnl_ret), pnl(tw && tw.pnl_ois)]);
    }
    this.count.textContent = rows.length ? (rows.length - 1) + ' vade · ' + isoToTr(d.today) : '';
    this.note.textContent = 'Yalnızca Günlük İşlemler\'deki TRY\'ye karşı forward\'lar (Broker Chat ve BIST swap kotaları değil; OIS ve tahvil TRY satmaz / almaz). '
      + 'Tutar USD karşılığı; bir işlem vadesinin iki yanındaki RET vadesine gün oranında bölünür (sayfanın forward kovaları gibi, TN hariç). '
      + 'Son ' + n + ' iş günü: ' + (d.days && d.days.length ? isoToTr(d.days[d.days.length - 1]) + ' – ' + isoToTr(d.days[0]) : '—') + ' (+ bugün).';
    if (!rows.length) {
      clear(this.body);
      this.grid = null;
      this.body.appendChild(h('div', { class: 'empty' }, 'Bugün ve önceki ' + n + ' iş gününde TRY\'ye karşı forward yok'));
    } else {
      const data = plainData(header, rows);
      if (this.grid) {
        this.grid.replace(data);
      } else {
        clear(this.body);
        this.grid = new Grid({ data, editable: false, name: 'blotter/position', tools: toolsOf(this.body) });
        this.body.appendChild(this.grid.el);
      }
    }
    if (this.wanted) { this.wanted = false; this.el.scrollIntoView({ block: 'start' }); }
  }

  /** Bring the panel into view (``#/blotter?p=position``). */
  focus() {
    if (this.grid || this.body.children.length) this.el.scrollIntoView({ block: 'start' });
    else this.wanted = true;
  }
}
