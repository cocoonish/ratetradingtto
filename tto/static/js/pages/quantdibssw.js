// DİBS switch (tto/quantdibssw.py): Carry + momentum's DİBS basket as switches - every Monday's close the trading list's
// fixed-coupon bonds and bills ranked on their carry + roll over a month and their one-month momentum, the best bought
// against the worst of a similar duration (the longer at most 1,5 × the shorter's modified duration), DV01-balanced, at
// most three switches a week, no bond twice. The page: the family's lines (each a line of the Sinyaller list, group DİBS)
// and the chart of a picked one; this week's switches with their sizes, C+R, momentum, target / stop and the P&L since the
// rebalance; the ranking of the bonds; the bonds left out and why; the backtest of the weekly switches. A tab of Faiz.
import { h, clear } from '../ui.js';
import { isoToTr } from '../format.js';
import { QuantPage, GridBox, SignalChart, panel, SIGNALS_TABLE, RATE_DIGITS, T, N, fmt, sgn, pct, isNum, money, sideClass } from './quantbase.js';

const KIND = { S: 'Sabit', B: 'Bono', T: 'TLREF', F: 'FRN', E: 'TÜFE' };
const mn = (v) => (isNum(v) ? fmt(v / 1e6, Math.abs(v / 1e6 - Math.round(v / 1e6)) < 0.05 ? 0 : 1) + ' mn' : '');

class DibsSwitchPage extends QuantPage {
  constructor(host, ctx) { super(host, ctx, 'dibssw'); }

  build() {
    this.tools();
    const page = this.pageEl();
    const sp = panel('quant-' + this.what + '-signals', 'DİBS switch · bu haftanın satırları', { wide: true });
    sp.note.textContent = 'Her switch bir satır (Sinyaller listesinde de, DİBS grubunda): AL / SAT kâğıtlar ve nominalleri, aylık carry + roll farkı, '
      + 'son bir ayın getiri hareketi, hedef ve stop getiri farkının işlem yönündeki hareketi olarak (bp), beklenen K/Z TL. Giriş / hedef / stop '
      + 'sütunları çiftin kendi serisinde (kısa vadeli kâğıdın getirisi − uzun vadelininki); "sıra" 2 haftanın en güçlü switch\'i, 1 en zayıfı. '
      + 'Kapı yok: yalnız geçmiş kaydı zarar ettiren seviyeler satırı "düşük güven" yapar. Satıra tıklayın: düz anlatımı ve serisi aşağıda.';
    this.boxes.sig = new GridBox(sp, SIGNALS_TABLE, (sid, click) => this.pick(sid, click), { freeze: 1 });
    const cp = panel('quant-' + this.what + '-chart', 'Seçili switch', { wide: true, cls: 'qcardp' });
    this.chart = new SignalChart(cp.body);
    this.swPanel = panel('quant-dibssw-switches', 'Bu haftanın switch\'leri · DV01 dengeli, nominaller masanın yuvarlamasıyla');
    this.head = h('div', { class: 'qsentence', id: 'quant-dibssw-head' });
    this.swPanel.el.insertBefore(this.head, this.swPanel.body);
    this.boxes.sw = new GridBox(this.swPanel, 'quant/dibssw/switches', (sid, click) => this.pick(sid, click), { freeze: 1 });
    this.bondPanel = panel('quant-dibssw-bonds', 'Sıralama · trading listesinin sabit kuponluları ve bonoları (haftanın kuruluş kapanışında)');
    this.boxes.bonds = new GridBox(this.bondPanel, 'quant/dibssw/bonds', null, { freeze: 2 });
    this.outPanel = panel('quant-dibssw-out', 'Evrenin dışında kalan kâğıtlar', { cls: 'aux', folded: true });
    this.boxes.out = new GridBox(this.outPanel, 'quant/dibssw/out');
    this.btPanel = panel('quant-dibssw-backtest', 'Geri test · her pazartesi kurulup bir hafta tutulan switch\'ler');
    this.btCard = h('div', { class: 'qsentence', id: 'quant-dibssw-record' });
    this.btPanel.el.insertBefore(this.btCard, this.btPanel.body);
    this.boxes.bt = new GridBox(this.btPanel, 'quant/dibssw/backtest');
    this.btPanel.note.textContent = 'Yürüyen pencere, ileriye bakış yok: geçmişin her pazartesi kapanışında switch\'ler yalnız o kapanışa kadarki verilerle kurulur, '
      + 'bir sonraki pazartesi kapanışına kadar tutulur. K/Z getiri farkının işlem yönündeki hareketi artı carry + roll\'un günlük payı (aylık ÷ 21), AL '
      + 'bacağının DV01\'iyle TL; riski switch\'in haftalık σ\'sı (girişten önceki 60 günün getiri farkı değişimleri × √5). Hedef ve stop bu işlemlerden ay '
      + 'ay ayarlanır (en az 30 işlem, ödül / risk ≥ 1). Tabloda son 26 hafta.';
    page.append(sp.el, cp.el, this.swPanel.el, this.bondPanel.el, this.btPanel.el, this.outPanel.el);
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
    const t = this.data.dibssw || {};
    // (a switch is a line whatever its gates say: none greyed)
    this.showSignals(t.why ? 'Bu hafta switch yok: nedeni aşağıda, "Bu haftanın switch\'leri" başlığının altında.'
      : 'Bu hafta switch yok: süresi benzer, skoru yeterince ayrışan kâğıt çifti yok.', false);
  }

  fillPage() {
    const t = this.data.dibssw || {};
    const st = t.settings || {};
    clear(this.head);
    this.head.append(t.ok ? h('b', null, 'Switch\'ler ' + t.formed_text + ' kapanışında kuruldu') : h('b', null, t.why || 'Bu hafta sıralama yok'),
      ' · sonraki dengeleme ' + (t.next_text || '') + ' kapanışı · AL bacağı ' + fmt(st.dv01_usd, 0) + ' $ DV01 (' + fmt(st.tl, 0) + ' TL / bp), nominaller '
      + mn(st.round_tl) + ' TL\'ye yuvarlı · süre bandı: uzunun süresi kısanınkinin en çok ' + fmt(st.dur_ratio, 1) + ' katı · haftada en çok '
      + (st.max_switches || 3) + ' switch, skor farkı en az ' + fmt(st.min_gap, 1));
    const lv = t.level_line || {};
    const sw = t.switches || [];
    // (the reason, when there is no ranking, once: in the head line above; the switches' and the backtest's tables say no more)
    this.swPanel.el.classList.toggle('qsaid', !t.ok);
    this.btPanel.el.classList.toggle('qsaid', !t.ok);
    this.boxes.sw.set(['Switch', 'Giriş → şimdi (getiri farkı, bp)', 'Hedef (bp, lehte)', 'Stop (bp, aleyhte)', 'Beklenen', 'Ödül / risk', 'İsabet', '#',
      'Nominal AL / SAT', 'DV01 AL / SAT (TL)', 'Süre AL / SAT', 'Hareket (bp, lehte)', 'σ hafta (bp)', 'Skor farkı', 'C+R bp / ay', 'Momentum 1A bp'],
    sw.map((s) => {
      const z = s.size || {};
      const lvs = s.levels || {};
      return [T('AL ' + s.al_label + ' / SAT ' + s.sat_label, { b: 1, tip: (s.line || '') + '\nAL ' + s.al + ' · SAT ' + s.sat }),
        T(sgn(s.level_formed, 1) + ' → ' + (isNum(s.now) ? sgn(s.now, 1) : '—')),
        T(isNum(s.target_bp) ? '+' + fmt(s.target_bp, 1) : '—'), T(isNum(s.stop_bp) ? '-' + fmt(s.stop_bp, 1) : '—'),
        T(isNum(s.exp_try) ? money(s.exp_try, 'TL') : '—'),
        N(s.rr, 2), T(lvs.ok && isNum(lvs.hit) ? pct(lvs.hit) + ' (' + (lvs.n || 0) + ')' : '—', { tip: lvs.text || lvs.why || '', cls: s.gated ? 'soft' : '' }),
        N(s.rank, 0),
        T(s.size_text || ''), T(isNum(z.dv01_al) ? fmt(z.dv01_al, 0) + ' / ' + fmt(z.dv01_sat, 0) : '', { tip: isNum(z.gap) ? 'DV01 farkı (yuvarlamadan) %' + fmt(Math.abs(z.gap) * 100, 1) : '' }),
        T(fmt(s.dur_al, 2) + ' / ' + fmt(s.dur_sat, 2)), N(s.so_far, 1, { sign: true }), N(s.sigma_h, 1), N(s.gap, 2),
        N(s.cr, 1, { sign: true, tip: isNum(s.cr_sheet) ? 'DİBS RV\'nin C+R\'ı (AO, ufkuna göre aylık); tarihçeden ' + sgn(s.cr_hist, 1) : 'tarihçeden: fonlama 1 aylık OIS, eğride yuvarlanma' }),
        N(s.mom, 1, { sign: true, tip: 'AL kâğıdının getirisi son bir ayda SAT\'ınkine göre bu kadar düştü (artı: lehte)' })];
    }), sw.map((s) => s.sid), t.ok ? 'Bu hafta switch yok: süre bandında skor farkı ' + fmt(st.min_gap, 1) + '\'i geçen çift yok.' : 'Switch yok.', this.picked);
    this.swPanel.note.textContent = (t.note || '') + ' Seviyeler: ' + (lv.text || lv.why || '') + '.';
    const bonds = t.bonds || [];
    this.boxes.bonds.set(['Sıra', 'Kâğıt', 'ISIN', 'Tür', 'Süre', 'Getiri % (basit)', 'Fonlama % (1A)', 'Carry bp / ay', 'Roll bp / ay', 'C+R bp / ay',
      'C+R DİBS RV', 'Momentum 1A bp', 'z C+R', 'z momentum', 'Bileşik', 'Switch\'te'],
    bonds.map((b) => [N(b.rank, 0), T(b.label, { b: 1 }), T(b.isin, { cls: 'soft' }), T(KIND[b.kind] || b.kind), N(b.dur, 2), N(b.y, RATE_DIGITS), N(b.f, RATE_DIGITS),
      N(b.carry, 1, { sign: true }), N(b.roll, 1, { sign: true }), N(b.cr, 1, { sign: true, b: 1 }), N(b.cr_sheet, 1, { sign: true, tip: 'DİBS RV!AO, ufkuna göre aylık' }),
      N(b.mom, 1, { sign: true }), N(b.z_cr, 2, { sign: true }), N(b.z_mom, 2, { sign: true }), N(b.comp, 2, { sign: true, b: 1 }),
      T(b.side || '', { b: 1, cls: sideClass(b.side) || 'soft' })]), null, t.ok ? 'Sıralama yok' : 'Sıralama yok: nedeni yukarıda.');
    this.bondPanel.note.textContent = 'Getiri: BIST basit getiri (DİBS RV!S gibi; tarihçesi bileşikse çevrilir). Carry: (getiri − fonlama) × 30/365 ÷ modifiye süre; '
      + 'roll: o kapanışın sabit kuponlulara uydurulan eğrisinde (Nelson-Siegel) bir ay kısalmanın getiri farkı - ikisi de kâğıdın DV01\'i cinsinden, '
      + 'tutan için. Momentum: −(getiri − 21 kapanış önceki), bp. z\'ler o kapanıştaki kâğıtlar arasında; bileşik = z C+R + z momentum.';
    const out = t.out || [];
    this.boxes.out.set(['Kâğıt', 'ISIN', 'Tür', 'Neden'], out.map((o) => [T(o.label, { b: 1 }), T(o.isin, { cls: 'soft' }), T(KIND[o.kind] || o.kind || ''), T(o.why, { cls: 'soft' })]),
      null, 'Trading listesinin bütün kâğıtları evrende.');
    const b = t.stats || {};
    clear(this.btCard);
    this.btCard.append(b.trades ? b.trades + ' switch (' + (b.weeks || 0) + ' hafta) · isabet ' + pct(b.hit) + ' · ort. ' + sgn(b.avg_sigma, 2) + 'σ · '
      + (isNum(b.avg) ? sgn(b.avg, 1) + ' bp' : '') + (isNum(b.avg_try) ? ' · ' + money(b.avg_try, 'TL') : '') + ' · Sharpe ' + sgn(b.sharpe, 2)
      + ' · en büyük düşüş ' + fmt(b.max_dd, 1) + 'σ · ' + isoToTr(b.first) + ' – ' + isoToTr(b.last) + ' · seviyeler: ' + (lv.text || lv.why || '')
      : 'Geri testte switch yok' + (t.why ? ' (nedeni yukarıda).' : ': geçmiş kısa.'));
    this.boxes.bt.set(['Kuruluş', 'Bitiş', 'Switch\'ler', 'Adet', 'K/Z (bp)', 'K/Z (TL)'],
      (t.weeks || []).slice().reverse().map((w) => [T(isoToTr(w.day)), T(isoToTr(w.end)), T(w.text || '—'), N(w.n, 0), N(w.pnl, 1, { sign: true }),
        T(isNum(w.pnl_try) ? money(w.pnl_try, 'TL') : '')]), null, 'Geri test yok');
  }
}

/** The pages of this module by id (quant.js asks here first). */
export const DIBSSW_PAGES = { 'quant-dibssw': DibsSwitchPage };
