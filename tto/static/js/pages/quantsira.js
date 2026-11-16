// Carry + momentum (tto/quantsira.py): the universe's instruments ranked set by set, one basket a set rebalanced every
// Monday's close - G10 spot (best three currencies long, worst three short against USD), G10 vol (the richest premiums
// sold, the cheapest bought), TRY OIS to 2Y (receive two, pay two), TRY OIS spreads and flies (the three strongest, each
// its own way), DİBS (buy three, sell three).  Each set: its basket's card (legs and sizes, the week's expected P&L, target,
// stop, the P&L so far, the backtest, the next rebalance) and its ranking; the family's lines (each leg a line of the
// Sinyaller list) and the chart of a picked one; the backtest per set.  Computed in the quant worker's thread.
import { h, clear } from '../ui.js';
import { isoToTr } from '../format.js';
import { QuantPage, GridBox, SignalChart, panel, signalRows, SIGNAL_HEAD, T, N, fmt, sgn, pct, isNum, money, levelText } from './quantbase.js';

// a set's panel: its id on the page (literal: quantread.js has a read line for each) and its title
const SET_TITLES = {
  g10: 'G10 spot sepeti · carry + 3 aylık momentum, para birimleri USD\'ye karşı',
  vol: 'G10 vol sepeti · 3A ATM ima − gerçekleşen vol ve vol momentumu',
  ois: 'TRY OIS sepeti · 2 yıla kadar vadeler, carry + roll ÷ oynaklık ve momentum',
  spread: 'TRY OIS spread sepeti · her biri kendi yönünde',
  fly: 'TRY OIS fly sepeti · her biri kendi yönünde',
  dibs: 'DİBS sepeti · carry + roll ÷ oynaklık, eğriye göre ucuzluk ve momentum',
};

class SiraPage extends QuantPage {
  constructor(host, ctx) { super(host, ctx, 'sira'); }

  build() {
    this.tools();
    const page = h('div', { class: 'volpage quantpage' });
    const sp = panel('quant-' + this.what + '-signals', 'Carry + momentum · sepetlerin satırları');
    sp.note.textContent = 'Her sepetin her bacağı bir satır (Sinyaller listesinde de, kendi grubunda): ne yapılacağı ve büyüklüğü, giriş / hedef / stop '
      + 'bacağın kendi fiyatıyla, beklenen K/Z haftalık (FX\'te 1 mn baz döviz başına). "sıra" 2 sepetin o tarafının en güçlüsü, 1 en zayıfı; '
      + 'kapı yok: bir sepetin bacakları her zaman satırdır. Satıra tıklayın: işlemin düz anlatımı ve serisi aşağıda.';
    this.boxes.sig = new GridBox(sp, 'quant/sira/signals', (sid) => this.pick(sid));
    const cp = panel('quant-' + this.what + '-chart', 'Seçili satır');
    this.chart = new SignalChart(cp.body);
    page.append(sp.el, cp.el);
    // (one panel a set, each id literal)
    this.sets = {};
    const add = (id, p) => {
      const card = h('div', { class: 'qbasket', id: p.el.id + '-card' });
      p.el.insertBefore(card, p.body);
      this.sets[id] = { p, card, box: new GridBox(p, 'quant/sira/' + id, (sid) => this.pick(sid)) };
      page.appendChild(p.el);
    };
    add('g10', panel('quant-sira-g10', SET_TITLES.g10));
    add('vol', panel('quant-sira-vol', SET_TITLES.vol));
    add('ois', panel('quant-sira-ois', SET_TITLES.ois));
    add('spread', panel('quant-sira-spread', SET_TITLES.spread));
    add('fly', panel('quant-sira-fly', SET_TITLES.fly));
    add('dibs', panel('quant-sira-dibs', SET_TITLES.dibs));
    this.bt = panel('quant-sira-backtest', 'Geri test · her pazartesi kurulup bir hafta tutulan sepetler');
    this.bt.note.textContent = 'Yürüyen pencere, ileriye bakış yok: geçmişin her pazartesi kapanışında sepet yalnız o kapanışa kadarki verilerle kurulur, '
      + 'bir sonraki pazartesi kapanışına kadar tutulur. K/Z parayla (bacakların hareketi; faiz bacaklarında o günün carry + roll\'u, FX\'te forward primi '
      + 'dahil, straddle\'larda teta / gama), riski haftanın önceden bilinen σ\'sı (son 60 günün sepet K/Z\'si) - Sharpe bu risk birimiyle, ×√52. '
      + 'Sinyaller sayfasının geri test tablosu aileyi bu haftalık geri testle verir.';
    this.boxes.bt = new GridBox(this.bt, 'quant/sira/backtest');
    page.appendChild(this.bt.el);
    this.addStatus(page);
    this.host.appendChild(page);
  }

  fill() {
    this.fillStatus();
    if (!this.data || !this.data.ready) return;
    this.fillSignals();
    this.fillPage();
  }

  afterPick() {
    this.fillSignals();
    this.fillPage();
  }

  fillSignals() {
    const list = this.data.signals || [];
    this.boxes.sig.set(SIGNAL_HEAD.concat(['Bileşik / neden', 'Saat']), list.map((s) => signalRows([s], { gated: !!s.gated })[0]),
      list.map((s) => s.id), 'Bu hafta sepet yok: geçmiş yetersiz (aşağıda her sepetin nedeni).', this.picked);
  }

  fillPage() {
    const tab = this.data.sira || {};
    const sets = tab.sets || [];
    for (const s of sets) {
      const own = this.sets[s.id];
      if (!own) continue;
      own.p.note.textContent = s.note || '';
      this.fillCard(own.card, s);
      this.fillRanking(own.box, s);
    }
    this.boxes.bt.set(['Sepet', 'Hafta', 'İsabet', 'Sharpe', 'Ort. haftalık K/Z', 'Ort. K/Z (risk birimi)', 'En büyük düşüş σ', 'İlk', 'Son'],
      sets.map((s) => {
        const b = s.backtest || {};
        return [T(s.name, { b: 1 }), N(b.trades, 0), T(b.trades ? pct(b.hit) : ''), N(b.sharpe, 2, { sign: true }),
          T(isNum(b.avg) ? money(b.avg, s.ccy) : ''), N(b.mean_r, 2, { sign: true }), N(b.max_dd, 1), T(isoToTr(b.first)), T(isoToTr(b.last))];
      }), null, 'Geri test yok');
  }

  /** A basket's card: when it was made and the next rebalance, the week's expected P&L, target and stop, the P&L so far,
   * the backtest, the legs with their sizes, entries and P&L so far. */
  fillCard(card, s) {
    clear(card);
    const b = s.basket;
    if (!s.ok || !b) {
      card.appendChild(h('div', { class: 'empty' }, s.why || 'Bu hafta sepet yok.'));
      return;
    }
    const ccy = s.ccy;
    const bt = s.backtest || {};
    const head = h('div', { class: 'qsentence' }, h('b', null, s.name), ' · ' + b.formed_text + ' kapanışında kuruldu · sonraki dengeleme ' + s.next_text + ' kapanışı');
    const kv = h('table', { class: 'plain qkv' });
    const line = (k, v, id) => kv.appendChild(h('tr', null, h('th', null, k), h('td', id ? { id } : null, v)));
    line('Beklenen K/Z (hafta)', isNum(b.exp) ? money(b.exp, ccy) + ' (geri testin haftalık ortalaması × sepetin kuruluştaki riski)'
      : 'geri test kısa (' + (bt.trades || 0) + ' hafta): beklenti yok', card.id + '-exp');
    line('Hedef / stop', (isNum(b.target) ? money(b.target, ccy) : '—') + ' / ' + money(b.stop, ccy) + ' (2σ, haftalık σ ' + money(b.risk, ccy, false) + ')');
    line('Şimdiye kadar', money(isNum(b.so_far_now) ? b.so_far_now : b.so_far, ccy) || '0 ' + ccy, card.id + '-sofar');
    line('Geri test', bt.trades ? bt.trades + ' hafta · isabet ' + pct(bt.hit) + ' · Sharpe ' + sgn(bt.sharpe, 2) + (isNum(bt.max_dd) ? ' · en büyük düşüş ' + fmt(bt.max_dd, 1) + 'σ' : '')
      + ' · ' + isoToTr(bt.first) + ' – ' + isoToTr(bt.last) : 'henüz hafta yok');
    if (s.mode === 'ls') line('Net', fmt(b.net, 0) + ' ' + b.net_unit + (s.id === 'g10' ? ' (dolar-nötr)' : s.id === 'vol' ? ' (vega-nötr)' : ' (DV01-nötr)'));
    const legs = h('table', { class: 'plain qlegs', id: card.id.replace(/-card$/, '-legs') }, h('tr', null, ...['İşlem', 'Büyüklük', 'Giriş (kuruluş)', 'Şimdi',
      'K/Z şimdiye kadar', 'Beklenen (hafta)', 'Stop (2σ)'].map((x, i) => h('th', { class: i ? '' : 'l' }, x))));
    for (const l of s.legs || []) {
      const lv = (v) => levelText(v, l.unit, l.digits);
      legs.appendChild(h('tr', null, h('td', { class: 'l ' + (l.side > 0 ? 'buy' : 'sell') }, l.line.split(' · ')[0]), h('td', null, l.size),
        h('td', null, lv(l.entry)), h('td', null, lv(l.now)), h('td', null, money(isNum(l.so_far_now) ? l.so_far_now : l.so_far, ccy) || '0'),
        h('td', null, isNum(l.exp) ? money(l.exp, ccy) : '—'), h('td', null, money(l.stop, ccy))));
    }
    card.append(h('div', { class: 'qplain' }, head, h('div', { class: 'qcols' }, kv, legs)));
  }

  /** A set's ranking at the basket's close: carry, momentum (DİBS: cheapness too), the composite, the rank, the side. */
  fillRanking(box, s) {
    const cols = s.cols || {};
    const dibs = s.id === 'dibs', vol = s.id === 'vol', fx = s.id === 'g10';
    const head = ['Sıra', 'Enstrüman', cols.carry || 'Carry'].concat(fx ? [] : vol ? ['İma', 'Gerçekleşen'] : ['Carry / vol'], [cols.mom || 'Momentum'],
      dibs ? ['Ucuzluk z'] : [], [s.mode === 'best' ? 'Skor (+ ' + (cols.way || '') + ')' : 'Bileşik', 'Sepette', 'Büyüklük', 'sıra']);
    const rows = (s.rows || []).map((r) => [N(r.rank, 0), T(r.label + (r.tier === 'uzun' ? ' · uzun' : ''), { b: 1 }), N(r.carry, 2, { sign: true })]
      .concat(fx ? [] : vol ? [N(r.iv, 2), N(r.rv, 2)] : [N(r.cv, 2, { sign: true })], [N(r.mom, 2, { sign: true })], dibs ? [N(r.cheap, 2, { sign: true })] : [],
        [N(r.composite, 2, { sign: true, b: 1 }), T(r.verb || '', { b: 1, cls: r.side > 0 ? 'thru' : r.side < 0 ? 'thru' : 'soft' }), T(r.size || ''),
          N(r.z, 2, { sign: true })]));
    box.set(head, rows, (s.rows || []).map((r) => r.sid), s.why || 'Sıralama yok', this.picked);
  }
}

/** The pages of this module by id (quant.js asks here first). */
export const SIRA_PAGES = { 'quant-sira': SiraPage };
