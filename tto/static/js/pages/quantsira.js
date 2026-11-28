// Carry + momentum (tto/quantsira.py): the universe's instruments ranked set by set, one basket a set rebalanced every
// Monday's close - G10 spot (best three currencies long, worst three short against USD), G10 vol (the richest premiums
// sold, the cheapest bought), TRY OIS to 2Y (receive two, pay two), TRY OIS spreads and flies (the three strongest, each
// its own way), DİBS (buy three, sell three).  Each set: its basket's card (legs and sizes, the week's expected P&L, target,
// stop, the P&L so far, the backtest, the next rebalance) and its ranking; the family's lines (each leg a line of the
// Sinyaller list) and the chart of a picked one; the backtest per set.  Computed in the quant worker's thread.
import { h, clear } from '../ui.js';
import { isoToTr } from '../format.js';
import { QuantPage, GridBox, SignalChart, panel, SIGNALS_TABLE, T, N, fmt, sgn, pct, isNum, money, levelText, sideClass, seg, pref, keep } from './quantbase.js';

// the six sets: their name in the switch, the ranking's title, and what the ranking tells (its read line - Düzen,
// 28.11.2026: the six baskets in one table, one ranking at a time under it - 5,6 screens were ~2)
const SETS = ['g10', 'vol', 'ois', 'spread', 'fly', 'dibs'];
const SET_NAMES = { g10: 'G10 spot', vol: 'G10 vol', ois: 'TRY OIS', spread: 'Spread', fly: 'Fly', dibs: 'DİBS' };
const SET_TITLES = {
  g10: 'G10 spot sepeti · carry + 3 aylık momentum, para birimleri USD\'ye karşı',
  vol: 'G10 vol sepeti · 3A ATM ima − gerçekleşen vol ve vol momentumu',
  ois: 'TRY OIS sepeti · 2 yıla kadar vadeler, carry + roll ÷ oynaklık ve momentum',
  spread: 'TRY OIS spread sepeti · her biri kendi yönünde',
  fly: 'TRY OIS fly sepeti · her biri kendi yönünde',
  dibs: 'DİBS sepeti · carry + roll ÷ oynaklık, eğriye göre ucuzluk ve momentum',
};
const SET_READS = {
  g10: 'Bu haftanın G10 spot sepeti: carry\'si ve son 3 ayın getirisi (carry dahil) en yüksek üç para birimi USD\'ye karşı alınır, en düşük üçü satılır. "Sepette" AL / SAT yazan satır işlemdir (JPY alınacaksa USDJPY SAT), "Bileşik" sırayı verir; sepet pazartesi kapanışında yenilenir.',
  vol: 'Bu haftanın G10 vol sepeti: ima vol\'ü gerçekleşenin en çok üstünde olan ve son 3 ayda en çok düşen üç paritede straddle satılır (vol sat), en ucuz üçünde alınır (vol al), her biri 10.000 $ vega. "Prim" ima − gerçekleşen vol puanıdır; sepet pazartesi kapanışında yenilenir.',
  ois: 'Bu haftanın TRY OIS sepeti (2 yıla kadar): haftalık carry + roll\'u oynaklığına göre en yüksek ve faizi son 3 ayda en çok düşen iki vade receive, en kötü iki vade pay edilir, her biri 1.000 $ DV01. "Sepette" yazan satır işlemdir; sepet pazartesi kapanışında yenilenir.',
  spread: 'Spread\'ler kendi yönünde: "Skor" artıysa steepener (uzun vadeyi pay, kısayı receive), eksiyse flattener; mutlak değeri en büyük üç spread 1.000 $ DV01 ile işlem olur. Skor carry + roll\'u oynaklığa göre ve son 3 ayın hareketini birlikte sayar.',
  fly: 'Fly\'lar kendi yönünde: "Skor" artıysa gövdeyi pay edip kanatları receive edersin, eksiyse gövde receive / kanatlar pay; mutlak değeri en büyük üç fly 1.000 $ DV01 (50/50) ile işlem olur. Skor carry + roll\'u oynaklığa göre ve son 3 ayın hareketini birlikte sayar.',
  dibs: 'Bu haftanın DİBS sepeti: carry + roll\'u oynaklığına göre yüksek, eğriye göre her zamankinden ucuz ("Ucuzluk z" artı) ve getirisi son 3 ayda düşen üç kâğıt alınır, tersi üçü satılır, her biri 1.000 $ DV01. "Sepette" AL / SAT yazan satır işlemdir.',
};
const SET_PREF = 'tto.quant.sira.set';

class SiraPage extends QuantPage {
  constructor(host, ctx) {
    super(host, ctx, 'sira');
    this.set = SETS.includes(pref(SET_PREF, 'g10')) ? pref(SET_PREF, 'g10') : 'g10';
  }

  build() {
    this.tools();
    const page = this.pageEl();
    const sp = panel('quant-' + this.what + '-signals', 'Carry + momentum · sepetlerin satırları', { wide: true });
    sp.note.textContent = 'Her sepetin her bacağı bir satır (Sinyaller listesinde de, kendi grubunda): ne yapılacağı ve büyüklüğü, giriş / hedef / stop '
      + 'bacağın kendi fiyatıyla, beklenen K/Z haftalık (FX\'te 1 mn baz döviz başına). "sıra" 2 sepetin o tarafının en güçlüsü, 1 en zayıfı; '
      + 'kapı yok: bir sepetin bacakları her zaman satırdır. Satıra tıklayın: işlemin düz anlatımı ve serisi aşağıda.';
    this.boxes.sig = new GridBox(sp, SIGNALS_TABLE, (sid, click) => this.pick(sid, click), { freeze: 1 });
    const cp = panel('quant-' + this.what + '-chart', 'Seçili satır', { wide: true, cls: 'qcardp' });
    this.chart = new SignalChart(cp.body);
    page.append(sp.el, cp.el);
    // the six baskets in one table - a row each: when it was made, its week's expected P&L, target, stop, record, the P&L
    // so far; a row's click shows its ranking and legs below (Düzen, 28.11.2026)
    this.baskets = panel('quant-sira-baskets', 'Sepetler · bu hafta (altı sepet, sepet başına bir satır)');
    this.baskets.note.textContent = 'Beklenen K/Z: ayarlı seviyelerle (yoksa geri testin) haftalık ortalaması × sepetin kuruluştaki riski; hedef / stop sepetin haftalık '
      + 'σ\'sının katları (ayarlı değilse 2σ stop). Şimdiye kadar: bacakların kuruluştan bu yana K/Z\'si (faizde carry + roll, FX\'te forward primi dahil). '
      + 'Net: dolar-, vega- ya da DV01-nötr sepetin kalan net pozisyonu. Satıra tıklayın: sepetin sıralaması ve bacakları altta.';
    this.boxes.baskets = new GridBox(this.baskets, 'quant/sira/baskets', (id) => this.showSet(id), { freeze: 1 });
    page.appendChild(this.baskets.el);
    // ... and one ranking at a time: the set chosen (its switch in the header), its legs folded under it
    this.setSeg = seg(SETS.map((id) => [id, SET_NAMES[id], SET_TITLES[id]]), this.set, (v) => this.showSet(v), 'quant-sira-set');
    this.rank = panel('quant-sira-ranking', 'Sıralama · ' + SET_TITLES[this.set], { right: [this.setSeg] });
    this.card = h('div', { class: 'qbasket', id: 'quant-sira-ranking-card' });
    this.rank.el.insertBefore(this.card, this.rank.body);
    this.boxes.rank = new GridBox(this.rank, 'quant/sira/' + this.set, (sid, click) => this.pick(sid, click));
    page.appendChild(this.rank.el);
    this.bt = panel('quant-sira-backtest', 'Geri test · her pazartesi kurulup bir hafta tutulan sepetler');
    this.bt.note.textContent = 'Yürüyen pencere, ileriye bakış yok: geçmişin her pazartesi kapanışında sepet yalnız o kapanışa kadarki verilerle kurulur, '
      + 'bir sonraki pazartesi kapanışına kadar tutulur. K/Z parayla (bacakların hareketi; faiz bacaklarında o günün carry + roll\'u, FX\'te forward primi '
      + 'dahil, straddle\'larda teta / gama), riski haftanın önceden bilinen σ\'sı (son 60 günün sepet K/Z\'si) - Sharpe bu risk birimiyle, ×√52. '
      + 'Sinyaller sayfasının geri test tablosu aileyi bu haftalık geri testle verir.';
    this.boxes.bt = new GridBox(this.bt, 'quant/sira/backtest');
    page.appendChild(this.bt.el);
    this.host.appendChild(page);
    this.addJumps(page);
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
    // (a basket's legs are lines whatever their gates say: none greyed)
    this.showSignals('Bu hafta sepet yok: geçmiş yetersiz (aşağıda her sepetin nedeni).', false);
  }

  /** The set shown below the baskets' table (a row's click, the switch in the ranking's header; kept in the browser). */
  showSet(id) {
    if (!SETS.includes(id)) return;
    this.set = id;
    keep(SET_PREF, id);
    this.setSeg.set(id);
    this.boxes.rank.name = 'quant/sira/' + id;           // (each set's columns its own choice: the grid made again with its name)
    this.boxes.rank.grid = null;
    if (this.data && this.data.ready) this.fillPage();
  }

  fillPage() {
    const tab = this.data.sira || {};
    const sets = tab.sets || [];
    this.fillBaskets(sets);
    const s = sets.find((x) => x.id === this.set) || null;
    this.rank.setTitle('Sıralama · ' + SET_TITLES[this.set]);
    this.rank.read.textContent = SET_READS[this.set] || '';
    this.rank.note.textContent = (s && s.note) || '';
    this.rank.el.classList.toggle('qsaid', !!s && !s.ok);   // (the card says why there is no basket: the ranking says no more)
    this.fillCard(this.card, s);
    if (s) this.fillRanking(this.boxes.rank, s); else this.boxes.rank.set([], [], null, 'Sepet yok');
    this.boxes.bt.set(['Sepet', 'Hafta', 'İsabet', 'Sharpe', 'Ort. haftalık K/Z', 'Ort. K/Z (risk birimi)', 'En büyük düşüş σ', 'İlk', 'Son'],
      sets.map((x) => {
        const b = x.backtest || {};
        return [T(x.name, { b: 1 }), N(b.trades, 0), T(b.trades ? pct(b.hit) : ''), N(b.sharpe, 2, { sign: true }),
          T(isNum(b.avg) ? money(b.avg, x.ccy) : ''), N(b.mean_r, 2, { sign: true }), N(b.max_dd, 1), T(isoToTr(b.first)), T(isoToTr(b.last))];
      }), null, 'Geri test yok');
  }

  /** The six baskets in one table: a row each - its formation and the next rebalance, the week's expected P&L, target
   * and stop (the multiples of its weekly σ in the tooltip), its levels' record, the P&L so far, the net, its legs; a
   * set without a basket this week says why on its row. */
  fillBaskets(sets) {
    const rows = sets.map((s) => {
      const b = s.basket;
      const name = T(s.name, { b: 1, tip: SET_TITLES[s.id] || s.name });
      // (no basket: its reason across the row, its legs 0 - a number, so the grid never reads the row as a caption)
      if (!s.ok || !b) {
        return [name, { t: s.why || 'Bu hafta sepet yok.', k: 's', cls: 'soft qwrap', cs: 8 }].concat(Array(7).fill({ sk: 1, t: '', k: '' }),
          [N(0, 0, { tip: 'bu hafta sepet yok' })]);
      }
      const ccy = s.ccy;
      const lvs = s.levels || {};
      const bt = s.backtest || {};
      const multiples = lvs.ok ? 'hedef ' + fmt(lvs.m, 2) + 'σ, stop ' + fmt(lvs.k, 2) + 'σ' : 'stop 2σ (ayarlı seviye yok)';
      return [name, T(b.formed_text + ' → ' + s.next_text, { tip: b.formed_text + ' kapanışında kuruldu · sonraki dengeleme ' + s.next_text + ' kapanışı' }),
        T(isNum(b.exp) ? money(b.exp, ccy) : '—', { b: 1, tip: isNum(b.exp) ? (lvs.ok ? 'Ayarlı seviyelerle haftalık ortalama × sepetin kuruluştaki riski'
          : 'Geri testin haftalık ortalaması × sepetin kuruluştaki riski') : 'geri test kısa (' + (bt.trades || 0) + ' hafta): beklenti yok' }),
        T(isNum(b.target) ? money(b.target, ccy) : '—', { tip: multiples + ' · haftalık σ ' + money(b.risk, ccy, false) }),
        T(money(b.stop, ccy), { tip: multiples + ' · haftalık σ ' + money(b.risk, ccy, false) }),
        N(lvs.ok ? b.rr : null, 2, { empty: '—', tip: lvs.ok ? '' : (lvs.why || 'seviye kalibrasyonu yok') }),
        T(lvs.ok && isNum(lvs.hit) ? pct(lvs.hit) + ' (' + (lvs.n || 0) + ')' : '—', { cls: lvs.ok ? (isNum(lvs.exp) && lvs.exp < 0 ? 'soft' : '') : 'soft',
          tip: lvs.ok ? (lvs.n || 0) + ' hafta, ' + (lvs.oos ? 'örneklem dışı' : 'örneklem içi') + (isNum(lvs.exp) && lvs.exp < 0 ? ' · bu seviyelerle bile zarar ettirdi: düşük güven' : '')
            : (lvs.why || 'seviye kalibrasyonu yok') }),
        T(money(isNum(b.so_far_now) ? b.so_far_now : b.so_far, ccy) || '0 ' + ccy),
        T(s.mode === 'ls' ? fmt(b.net, 0) + ' ' + b.net_unit : '—', { tip: s.mode === 'ls' ? (s.id === 'g10' ? 'dolar-nötr' : s.id === 'vol' ? 'vega-nötr' : 'DV01-nötr') : 'her biri kendi yönünde' }),
        T(String((s.legs || []).length), { tip: (s.legs || []).map((l) => l.line).join('\n') })];
    });
    this.boxes.baskets.set(['Sepet', 'Kuruldu → sonraki', 'Beklenen K/Z (hafta)', 'Hedef', 'Stop', 'Ödül / risk', 'İsabet', 'Şimdiye kadar', 'Net', 'Bacak'],
      rows, sets.map((s) => s.id), 'Sepet yok', this.set);
  }

  /** The chosen basket under its ranking: its line, and its legs - sizes, entries at the formation, now, the P&L so far -
   * folded (each leg is a line of the list above). */
  fillCard(card, s) {
    clear(card);
    if (!s) return;
    const b = s.basket;
    if (!s.ok || !b) {
      // (the reason once: on the set's row of the baskets' table above)
      card.appendChild(h('div', { class: 'empty' }, 'Bu hafta ' + (s.name || 'sepet') + ' yok: nedeni yukarıdaki Sepetler tablosunda.'));
      return;
    }
    const ccy = s.ccy;
    const legs = h('table', { class: 'plain qlegs', id: 'quant-sira-ranking-legs' }, h('tr', null, ...['İşlem', 'Büyüklük', 'Giriş (kuruluş)', 'Şimdi',
      'K/Z şimdiye kadar', 'Beklenen (hafta)', 'Hedef', 'Stop'].map((x, i) => h('th', { class: i ? '' : 'l' }, x))));
    for (const l of s.legs || []) {
      const lv = (v) => levelText(v, l.unit, l.digits);
      legs.appendChild(h('tr', null, h('td', { class: 'l ' + (l.side > 0 ? 'buy' : 'sell') }, l.line.split(' · ')[0]), h('td', null, l.size),
        h('td', null, lv(l.entry)), h('td', null, lv(l.now)), h('td', null, money(isNum(l.so_far_now) ? l.so_far_now : l.so_far, ccy) || '0'),
        h('td', null, isNum(l.exp) ? money(l.exp, ccy) : '—'), h('td', null, isNum(l.target) ? money(l.target, ccy) : '—'), h('td', null, money(l.stop, ccy))));
    }
    // (each leg is a line of the list above; its entry at the basket's close and its P&L so far here, one click away)
    const legsBox = h('details', { class: 'qlegsfold' }, h('summary', null, 'Bacaklar (' + (s.legs || []).length + ') · kuruluştaki giriş, şimdi, şimdiye kadar K/Z'), legs);
    card.append(h('div', { class: 'qsentence' }, h('b', null, s.name), ' · ' + b.formed_text + ' kapanışında kuruldu · sonraki dengeleme ' + s.next_text
      + ' kapanışı · beklenen ' + (isNum(b.exp) ? money(b.exp, ccy) : '—') + ' (hafta)'), legsBox);
  }

  /** A set's ranking at the basket's close: carry, momentum (DİBS: cheapness too), the composite, the rank, the side. */
  fillRanking(box, s) {
    const cols = s.cols || {};
    const dibs = s.id === 'dibs', vol = s.id === 'vol', fx = s.id === 'g10';
    const head = ['Sıra', 'Enstrüman', cols.carry || 'Carry'].concat(fx ? [] : vol ? ['İma', 'Gerçekleşen'] : ['Carry / vol'], [cols.mom || 'Momentum'],
      dibs ? ['Ucuzluk z'] : [], [s.mode === 'best' ? 'Skor (+ ' + (cols.way || '') + ')' : 'Bileşik', 'Sepette', 'Büyüklük', 'sıra']);
    const rows = (s.rows || []).map((r) => [N(r.rank, 0), T(r.label + (r.tier === 'uzun' ? ' · uzun' : ''), { b: 1 }), N(r.carry, 2, { sign: true })]
      .concat(fx ? [] : vol ? [N(r.iv, 2), N(r.rv, 2)] : [N(r.cv, 2, { sign: true })], [N(r.mom, 2, { sign: true })], dibs ? [N(r.cheap, 2, { sign: true })] : [],
        [N(r.composite, 2, { sign: true, b: 1 }), T(r.verb || '', { b: 1, cls: sideClass(r.verb) || (r.side ? 'thru' : 'soft') }), T(r.size || ''),
          N(r.z, 2, { sign: true })]));
    box.set(head, rows, (s.rows || []).map((r) => r.sid), s.ok ? (s.why || 'Sıralama yok') : 'Sıralama yok', this.picked);
  }
}

/** The pages of this module by id (quant.js asks here first). */
export const SIRA_PAGES = { 'quant-sira': SiraPage };
