// Opsiyon → spot (tto/quantoptspot.py), a tab of FX: the option market's signals - the 25-delta risk reversal's weekly
// moves and level, its divergence from the spot, the ATM vol rising with it - as spot AL / SAT lines where they have led
// the spot out of sample; the butterfly scales the levels.  The family's lines (only where a pair's record holds), the
// chart of a picked one (its out-of-sample probability below as z(p)), every pair with today's quotes, their moves and
// the signals' z's, the forecast, whether it prints and why, and every signal's own out-of-sample record - pooled and
// per pair - so the desk sees which option signals lead the spot, and which way.  Computed in the quant worker's thread.
import { QuantPage, GridBox, SignalChart, panel, SIGNALS_TABLE, groupText, T, N, Z, fmt, pct, sgn, isNum, sideClass } from './quantbase.js';
import { h } from '../ui.js';

const SIG_TIP = {
  drr1: '25D RR 1A\'nın 5 kapanışlık değişimi ÷ kendi 5 günlük değişimlerinin σ\'sı (son 250 kapanış)',
  drr3: '25D RR 3A\'nın 5 kapanışlık değişimi ÷ kendi 5 günlük değişimlerinin σ\'sı (son 250 kapanış)',
  rrz: '25D RR 3A\'nın seviyesi, son 250 kapanışın ortalamasına göre z',
  div: 'RR spotu geçti mi: RR\'ın 5 günlük değişimi − β × spotun 5 günlük değişimi (β günlük hareketlerden), kalıntının σ\'sına bölünmüş',
  vrr: 'ATM vol 5 günde arttıysa (z, yalnız artış) × RR değişiminin z\'si: vol ve skew birlikte, gerilimli yön',
};

/** A vol move with its z: "+1,2 (z +2,1)". */
function move(v, z) {
  if (!isNum(v)) return '';
  return sgn(v, 2) + (isNum(z) ? ' (z ' + sgn(z, 1) + ')' : '');
}

class OptSpotPage extends QuantPage {
  constructor(host, ctx) { super(host, ctx, 'optspot'); }

  build() {
    this.tools([]);
    const page = this.pageEl();
    const sp = panel('quant-optspot-signals', 'Opsiyon → spot · sinyaller', { wide: true });
    sp.note.textContent = 'Yalnızca örneklem dışı kaydı tutan (isabet ≥ model eşiği, en az test sayısı) ve bugünkü olasılığı girişi geçen pariteler. '
      + 'İşlem satırı: işlemi açan opsiyon sinyali, yön, parite, büyüklük, isabet (test). Satıra tıklayın: kartta düz anlatım ve tahmini en çok '
      + 'oynatan sinyaller; grafikte spotun altında örneklem dışı olasılık gün gün (z(p) = (p − 0,5) ÷ 0,05).';
    this.boxes.sig = new GridBox(sp, SIGNALS_TABLE, (sid, click) => this.pick(sid, click), { freeze: 1 });
    const cp = panel('quant-optspot-chart', 'Seçili parite', { wide: true, cls: 'qcardp' });
    this.chart = new SignalChart(cp.body);
    this.pairs = panel('quant-optspot-pairs', 'Pariteler · bugünkü opsiyon sinyalleri ve önümüzdeki 5 iş günü');
    // (19 columns: the pair stays in view while the table scrolls sideways at 1366)
    this.boxes.pairs = new GridBox(this.pairs, 'quant/optspot/pairs', (sid, click) => this.pick(sid, click), { freeze: 1 });
    this.leads = panel('quant-optspot-leads', 'Opsiyon sinyalleri spotu öncülüyor mu? · örneklem dışı kayıt');
    this.boxes.leads = new GridBox(this.leads, 'quant/optspot/leads');
    page.append(sp.el, cp.el, this.pairs.el, this.leads.el);
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
    this.showSignals('Şu an basılan satır yok: paritenin örneklem dışı isabeti, test sayısı ve bugünkü olasılık birlikte tutmalı '
      + '(aşağıdaki tabloda her paritenin nedeni).');
  }

  fillPage() {
    const d = this.data.optspot || {};
    const st = d.settings || {};
    const md = d.model || {};
    const entry = st.entry_z || (this.data.settings || {}).entry_z || 2;
    const rows = d.rows || [];
    const hitMin = st.model_hit || 0.55;
    this.pairs.setTitle('Pariteler · bugünkü opsiyon sinyalleri ve önümüzdeki ' + (st.horizon || 5) + ' iş günü · ' + (d.valid || 0) + ' / '
      + (d.lines || 0) + ' paritenin kaydı tutuyor');
    this.pairs.note.textContent = 'Sinyaller (her biri kendi geçmişine göre z, pencere bugünden önceki ' + (st.window || 250) + ' kapanış, en az '
      + (st.min_window || 60) + '): 25D RR 1A ve 3A\'nın 1 haftalık değişimi, 25D RR 3A\'nın 1 yıla göre seviyesi, RR – spot ayrışması (RR\'ın '
      + 'değişimi − β × spotun değişimi), ATM vol artışı × RR yönü. Hedef: önümüzdeki ' + (st.horizon || 5) + ' kapanışın carry\'li getirisi ÷ '
      + 'opsiyonların ima ettiği 1 haftalık σ (ATM 1A × √(5/252)). Model: bütün paritelerde birlikte ridge - ortak katsayı + paritenin kendi '
      + 'sapması (' + fmt(st.l_pair / (st.l_shared || 1), 0) + ' kat cezalı), parite sabiti tahmine girmez; aylık yeniden eğitim, her ayın modeli '
      + 'yalnız o ay başlamadan etiketi bilinen satırlarla (en az ' + (st.min_train || 300) + '), yalnız o ayda test. Olasılık Φ(c × μ ÷ s): c '
      + 'paritenin örneklem dışı tahminlerinin gerçekleşen payı (0 – 1). İsabet ve test etiketi bilinen örneklem dışı günlerden (test = gün ÷ '
      + (st.horizon || 5) + '). Basılır: isabet ≥ %' + fmt(hitMin * 100, 0) + ', en az ' + (st.model_min_tests || 40) + ' test ve olasılık ≥ %'
      + fmt((st.p_entry || 0.6) * 100, 0) + '. Seviyeler: σ = ATM × √(5/252) × BF çarpanı, hedef ' + fmt(st.t_mult, 2) + 'σ, stop ' + fmt(st.s_mult, 0)
      + 'σ, 5 gün; büyüklük haftalık 1σ riski ' + fmt((st.risk_usd || 0) / 1000, 0) + ' bin USD\'ye. BF çarpanı geçmişten: kanatlar pahalıyken haftalar ne '
      + 'kadar büyüktü (' + (isNum(md.bf_ratio) && md.bf_ratio ? 'BF z +1\'de varyans ×' + fmt(1 + md.bf_ratio, 2) + ', t ' + fmt(md.bf_t, 1) : 'kanıt yok: ×1')
      + '). Geri test: olasılığın girişi geçtiği her örneklem dışı günde açılan işlem (hedef, stop ya da 5. kapanış).'
      + (d.timing ? ' Son hesap: ' + d.timing.pairs + ' parite, ' + d.timing.rows + ' satır, ' + d.timing.models + ' aylık model, '
        + fmt((d.timing.total_ms || 0) / 1000, 2) + ' sn.' : '');
    this.boxes.pairs.set(['Parite', 'Grup', 'Spot', 'ATM 1A (1 hf)', '25D RR 1A (1 hf)', '25D RR 3A (1 hf)', 'RR seviye z', 'RR – spot z', 'Vol × RR',
      'BF 3A z (×)', 'Olasılık', 'z(p)', 'Basılıyor', 'İşlemi açan sinyal', 'Test', 'İsabet', 'c', 'Geri test', 'Büyüklük'], rows.map((r) => {
      const x = r.x || {};
      const bt = r.trades ? r.trades + ' işlem · ' + pct(r.trade_hit) + (isNum(r.avg_sigma) ? ' · ' + sgn(r.avg_sigma, 2) + 'σ' : '') : '';
      return [T(r.label, { b: 1 }), T(groupText(r), r.tag ? { cls: 'qtag', tip: r.tag + ': masanın offshore işlem limiti dar' } : {}),
        N(r.spot, r.spot > 10 ? 3 : 5), T(move(r.atm_ch, null), { tip: isNum(r.atm) ? 'ATM ' + (r.atm_tenor || '') + ' ' + fmt(r.atm, 2) + ' vol' : '' }),
        T(move(r.rr1_ch, x.drr1), { tip: (isNum(r.rr1) ? '25D RR 1A ' + sgn(r.rr1, 2) + ' vol · ' : '') + SIG_TIP.drr1 }),
        T(move(r.rr3_ch, x.drr3), { tip: (isNum(r.rr3) ? '25D RR 3A ' + sgn(r.rr3, 2) + ' vol · ' : '') + SIG_TIP.drr3 }),
        Z(x.rrz, entry, { tip: SIG_TIP.rrz }), Z(x.div, entry, { tip: SIG_TIP.div }), Z(x.vrr, entry, { tip: SIG_TIP.vrr }),
        T(isNum(r.bfz) ? sgn(r.bfz, 1) + (isNum(r.f_bf) && Math.abs(r.f_bf - 1) > 0.005 ? ' (×' + fmt(r.f_bf, 2) + ')' : '') : '',
          { tip: 'Kanatlar: 25D BF 3A\'nın 1 yıla göre z\'si; yön vermez, seviyeleri çarpanla genişletir / daraltır' }),
        T(isNum(r.prob) ? (r.verb ? r.verb + ' ' : '') + '%' + fmt(r.prob * 100, 0) : '', Object.assign({ tip: isNum(r.mu) ? 'μ ' + sgn(r.mu, 2) + 'σ (haftanın)' : '' },
          sideClass(r.verb) ? { cls: sideClass(r.verb) } : {})),
        Z(r.z, entry), T(r.prints ? '✓' : (r.why || '—'), { cls: r.prints ? 'thru' : 'soft' }), T(r.driver || '', { tip: r.driver || '' }),
        N(r.tests, 0, { tip: isNum(r.days) ? r.days + ' örneklem dışı gün; 5 günlük ufuklar örtüştüğü için test = gün ÷ 5' : '' }),
        { t: pct(r.hit, 1), v: r.hit, k: isNum(r.hit) ? 'n' : '', cls: isNum(r.hit) && r.hit >= hitMin ? 'thru' : '' },
        N(r.cal, 2, { tip: 'Örneklem dışı tahminlerin gerçekleşen payı: olasılık ve beklenen hareket bununla küçülür' }),
        T(bt, { tip: 'Olasılığın girişi geçtiği örneklem dışı günlerde açılan işlemler: isabet ve ortalama K/Z (haftanın σ\'sı)' }), T(r.size || '')];
    }), rows.map((r) => r.sid || null), d.why || 'Hesap bekleniyor', this.picked);
    const sig = d.signals || [];
    const any = sig.some((s) => s.days);
    this.leads.note.textContent = 'Her sinyal, eğitim satırlarının seçtiği yönde (her ayın modeli: paritelerin kendi içindeki eğimin işareti; havuz '
      + 'için toplamı) yalnız sonraki ayda oynanır: momentum = opsiyonun yönünde (call\'lar pahalanınca spot al), ters = tersine. İsabet ve test '
      + 'sinyalin bir şey söylediği bütün örneklem dışı günlerden (test = gün ÷ 5); Güçlüyken: |z| ≥ ' + fmt(st.active || 1, 0) + ' günleri, ortalama '
      + 'hareket o yönde haftanın σ\'sı. IC: sinyal (yönüyle) ile gerçekleşen getirinin korelasyonu. Öncü: isabet ≥ %' + fmt(hitMin * 100, 0) + ' ve '
      + 'en az ' + (st.model_min_tests || 40) + ' test. Paritelerde: kendi kaydı tutan pariteler, kendi yönüyle; Ters yönlü: bu ay yönü havuzunkinin '
      + 'tersi olan pariteler (modelde kendi sapmaları taşır).';
    this.boxes.leads.set(['Sinyal', 'Yön (havuz)', 'Aylar', 'İsabet', 'Test', 'Güçlüyken isabet', 'Güçlüyken hareket (σ)', 'IC', 'Öncü', 'Paritelerde',
      'Ters yönlü'], any ? sig.map((s) => [T(s.label, { b: 1, tip: SIG_TIP[s.name] || '' }), T(s.sign_text, { b: s.sign ? 1 : 0 }),
      T(s.months ? s.months_same + ' / ' + s.months : ''), { t: pct(s.hit, 1), v: s.hit, k: isNum(s.hit) ? 'n' : '', cls: s.leads ? 'thru' : '' },
      N(s.tests, 0), T(isNum(s.strong_hit) ? pct(s.strong_hit, 1) + ' (' + s.strong_days + ' gün)' : ''), N(s.strong_move, 2, { sign: true }),
      N(s.ic, 3, { sign: true }), T(s.leads ? '✓' : '—', { cls: s.leads ? 'thru' : 'soft' }), T(s.pairs_text || '—'),
      T((s.against || []).join(' · ') || '—')]) : [], null, 'Örneklem dışı kayıt yok: opsiyon geçmişi kısa (bir aylık modelin en az '
      + (st.min_train || 300) + ' etiketli satırı gerekir).');
  }
}

/** The pages of this module by id (quant.js asks here first). */
export const OPTSPOT_PAGES = { 'quant-optspot': OptSpotPage };
