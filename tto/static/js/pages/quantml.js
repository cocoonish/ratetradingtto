// Makine öğrenmesi (tto/quantml.py): the five-day direction of every line of the family's universe by shallow
// gradient-boosted trees, retrained every month and tested only on the month after.  The family's lines (only where
// the out-of-sample record holds), the chart of a picked one (its out-of-sample probability below as z(p)), every
// instrument with its record, whether it prints, today's probability and the three features behind it, and the
// features' share of the trees' gain per group.  Computed in the quant worker's thread; the page reads the result.
import { QuantPage, GridBox, SignalChart, panel, SIGNALS_TABLE, T, N, Z, heatHex, fmt, pct, sgn, isNum, sideClass } from './quantbase.js';

const EFFECT_TIP = '↑: bugünkü tahmini yükselişe (yukarı tarafa: AL, pay, steepener, vol al), ↓: düşüşe iten veri; büyüklük sırasıyla';

class MlPage extends QuantPage {
  constructor(host, ctx) { super(host, ctx, 'ml'); }

  build() {
    this.tools([]);
    const page = this.pageEl();
    const sp = panel('quant-ml-signals', 'Makine öğrenmesi · sinyaller', { wide: true });
    sp.note.textContent = 'Yalnızca örneklem dışı kaydı tutan (isabet ≥ model eşiği, en az test sayısı) ve bugünkü olasılığı girişi geçen '
      + 'enstrümanlar. İşlem satırı: yön, enstrüman, büyüklük, olasılık, isabet (test). Satıra tıklayın: kartta düz anlatım ve tahmini en çok '
      + 'oynatan üç veri; grafikte serinin altında örneklem dışı olasılık gün gün (z(p) = (p − 0,5) ÷ 0,05).';
    this.boxes.sig = new GridBox(sp, SIGNALS_TABLE, (sid, click) => this.pick(sid, click), { freeze: 1 });
    const cp = panel('quant-ml-chart', 'Seçili seri', { wide: true, cls: 'qcardp' });
    this.chart = new SignalChart(cp.body);
    this.table = panel('quant-ml-table', 'Enstrümanlar · önümüzdeki 5 iş gününün yönü');
    this.boxes.table = new GridBox(this.table, 'quant/ml/table', (sid, click) => this.pick(sid, click), { freeze: 1 });
    this.feats = panel('quant-ml-features', 'Verilerin payı · grup başına');
    this.feats.note.textContent = 'Bugün işleyen modellerin (her enstrümanın bu ayki modeli) ağaçlarındaki bölünmelerin kazancı, veri başına: '
      + 'her modelinki %100\'e ölçeklenir, sütun grubun modellerinin ortalaması; ortak model (TRY OIS düz vadeleri) kendi sütununda, bir model. '
      + 'Sürücüler (UST, DXY, EM FX, Brent, CDS, opsiyonlar, TLREF, PPK adımı, VİOP farkı) bir gün öncesinden: kapanışları TRY kapanışından '
      + 'sonra gelir. Opsiyonlar: G10 enstrümanı kendi paritesinin 25D RR 3A\'sını, diğerleri USDTRY\'nin 25D RR 3A\'sını ve ATM vol 1A\'sını '
      + 've G10 paritelerinin RR ortalamasını (küresel risk) okur.';
    this.boxes.feats = new GridBox(this.feats, 'quant/ml/features');
    page.append(sp.el, cp.el, this.table.el, this.feats.el);
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
    this.showSignals('Şu an basılan satır yok: örneklem dışı isabet, test sayısı ve bugünkü olasılık birlikte tutmalı (aşağıdaki tabloda her '
      + 'enstrümanın nedeni).');
  }

  fillPage() {
    const d = this.data.ml || {};
    const st = d.settings || {};
    const entry = st.entry_z || (this.data.settings || {}).entry_z || 2;
    const rows = d.rows || [];
    this.table.setTitle('Enstrümanlar · önümüzdeki ' + (st.horizon || 5) + ' iş gününün yönü · ' + (d.valid || 0) + ' / ' + (d.lines || rows.length)
      + ' enstrümanın kaydı tutuyor');
    this.table.note.textContent = 'Gradyan artırmalı ağaçlar, lojistik kayıp: ' + (st.trees || '') + ' ağaç, derinlik ' + (st.depth || '') + ', öğrenme '
      + fmt(st.rate, 2) + ', her ağaç satırların %' + fmt((st.subsample || 0) * 100, 0) + '\'i ve verilerin %' + fmt((st.colsample || 0) * 100, 0) + '\'si, '
      + 'yaprakta en az ' + (st.min_leaf || '') + ' satır, L2 ' + fmt(st.l2, 0) + ', her veri eğitim satırlarının ' + (st.bins || '') + ' kantiline bölünür. '
      + 'Hedef: önümüzdeki ' + (st.horizon || 5) + ' kapanışta yukarı tarafın K/Z\'sinin işareti (FX\'te forward primi dahil). Yeniden eğitim aylık: her '
      + 'takvim ayının modeli yalnızca o ay başlamadan etiketi bilinen satırlarla kurulur ve yalnızca o ayın günlerini tahmin eder (ileriye bakış yok; '
      + 'en az ' + (st.min_train || '') + ' gün). ' + (st.pools || []).map((p) => p.label + ': ' + p.lines.length + ' vade tek modelde, her ayın '
      + 'modeli bütün vadelerin o ay başlamadan etiketi bilinen satırlarıyla kurulur (her satır kendi vadesinin günü, vade bir veri); her vadenin '
      + 'kaydı kendi günlerinden. ').join('') + 'İsabet ve log-loss etiketi bilinen bütün örneklem dışı günlerden; Test = gün ÷ ' + (st.horizon || 5)
      + ' (ufuklar örtüşür). Basılır: isabet ≥ %' + fmt((st.model_hit || 0.55) * 100, 0) + ', en az ' + (st.model_min_tests || 40) + ' test ve olasılık ≥ %'
      + fmt((st.p_entry || 0.6) * 100, 0) + ' (z(p) = (p − 0,5) ÷ 0,05 ≥ giriş). Hedef (2p − 1) × ortalama |' + (st.horizon || 5) + ' günlük K/Z|, stop 1,5σ ('
      + (st.horizon || 5) + ' gün). Geri test sütunu: olasılığı girişi geçen her örneklem dışı günün ' + (st.horizon || 5)
      + ' günlük K/Z\'si (isabet ve Sharpe; birimi enstrümanın).' + (d.timing ? ' Son eğitim: ' + d.timing.fitted + ' model kuruldu, ' + d.timing.cached
      + ' önbellekten, ' + fmt((d.timing.total_ms || 0) / 1000, 1) + ' sn.' : '');
    const hitMin = st.model_hit || 0.55;
    this.boxes.table.set(['Enstrüman', 'Grup', 'Kapanış', 'Test', 'İsabet', 'Taban oran', 'Log-loss', 'Basılıyor', 'Olasılık', 'z(p)', 'En etkili veriler (bugün)',
      'Geri test', 'Aylık model'], rows.map((r) => {
      const top = (r.top || []).map((w) => w.text + ' ' + (w.effect > 0 ? '↑' : '↓')).join(' · ');
      const bt = r.trades ? r.trades + ' gün · ' + pct(r.trade_hit) + (isNum(r.sharpe) ? ' · Sharpe ' + sgn(r.sharpe, 2) : '') : '';
      return [T(r.label, { b: 1 }), T([r.group, r.tier, r.tag].filter(Boolean).join(' · '), r.tag ? { cls: 'qtag' } : {}), N(r.n, 0),
        N(r.tests, 0, { tip: isNum(r.days) ? r.days + ' örneklem dışı gün; ' + (st.horizon || 5) + ' günlük ufuklar örtüştüğü için bağımsız test = gün ÷ ' + (st.horizon || 5) : '' }),
        { t: pct(r.hit, 1), v: r.hit, k: isNum(r.hit) ? 'n' : '', cls: isNum(r.hit) && r.hit >= hitMin ? 'thru' : '' }, T(pct(r.base, 0)), N(r.log_loss, 3),
        T(r.prints ? '✓' : (r.why || '—'), { cls: r.prints ? 'thru' : 'soft' }),
        T(isNum(r.prob) ? (r.verb ? r.verb + ' ' : '') + '%' + fmt(r.prob * 100, 0) : '', Object.assign({ tip: isNum(r.p) ? 'yukarı olasılığı %' + fmt(r.p * 100, 1) : '' },
          sideClass(r.verb) ? { cls: sideClass(r.verb) } : {})),
        Z(r.z, entry), T(top, { tip: EFFECT_TIP }), T(bt, { tip: 'Örneklem dışı tahminlerin olasılığı girişi geçtiği günler, ' + (st.horizon || 5) + ' günlük K/Z (' + (r.unit || '') + ')' }),
        r.pool ? { t: (r.months || 0) + ' · ortak', v: r.months, k: 'n', tip: r.pool + (r.first ? '; ilk test ayı ' + r.first.slice(0, 7) : '') }
          : N(r.months, 0, { tip: r.first ? 'ilk test ayı ' + r.first.slice(0, 7) : '' })];
    }), rows.map((r) => r.sid || null), d.why || 'Hesap bekleniyor', this.picked);
    const g = d.groups || {};
    const groups = g.groups || [];
    this.boxes.feats.set(['Veri'].concat(groups.map((x) => x + (g.models && g.models[x] ? ' (' + g.models[x] + ')' : ''))), (g.rows || []).map((r) => [T(r.label, { b: 1 })]
      .concat(groups.map((x) => {
        const v = (r.shares || {})[x];
        return isNum(v) ? { t: pct(v, 1), v, k: 'n', heat: heatHex(Math.min(1, v * 5)) || undefined } : T('');
      }))), null, 'Bugün işleyen model yok (geçmiş kısa)');
  }
}

/** The pages of this module by id (quant.js asks here first). */
export const ML_PAGES = { 'quant-ml': MlPage };
