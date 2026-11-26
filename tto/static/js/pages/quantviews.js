// The analyses behind the quant signals, one page each: Korelasyon, PCA / RV (curve PCA, PCA-neutral flies and spreads,
// FRA against the meeting path), Çiftler (cointegrated pairs, Kalman hedge ratios, VİOP calendar spreads), Rejim &
// Momentum (momentum board, policy-cycle curve signal, the regime of every series followed), FX Vol Primi & Carry
// (implied against realized and GARCH, EM carry / vol, forward premium), Makro Beta, Tahmin Modeli.  Every page lists
// its own signals at the top and draws a picked row's series below them (quantbase.js: SignalChart).
import { h, clear } from '../ui.js';
import { Chart } from '../chart.js';
import { isoToTr } from '../format.js';
import { QuantPage, GridBox, SignalChart, panel, SIGNALS_TABLE, T, N, Z, heatHex, seg, pref, keep, fmt, sgn, pct, isNum, REGIME, sideClass,
  BLUE, ORANGE, GREEN, PURPLE, RED, GREY } from './quantbase.js';
import { boxTools } from '../pagebox.js';

const ARROW = (s) => (s > 0 ? '↑' : s < 0 ? '↓' : '');

/** The frame of an analysis page (Düzen, 27.11.2026: the same order on every page): its signals, the card of a picked
 * row, its trade tables, its analysis, its secondary tables (folded on a long page: ``opts.jumps`` lists the panels
 * above them); the coverage and the status in a line above (their tables on Sinyaller). */
class AnalysisPage extends QuantPage {
  frame(title, panels, tools = [], opts = {}) {
    this.tools(tools);
    const page = this.pageEl();
    const sp = panel('quant-' + this.what + '-signals', title + ' · sinyaller', { wide: true });
    sp.note.textContent = 'Bu analizden çıkan sinyaller (elenenler gri, nedeniyle). Beklenen K/Z: FX\'te 1 mn baz döviz başına para, faizde bp (TL ipucunda). '
      + 'Satıra tıklayın: işlemin düz anlatımı (ne alınır / satılır, hangi fiyattan, hedefte ve stopta ne olur), seri ve giriş / hedef / stop aşağıda.';
    this.boxes.sig = new GridBox(sp, SIGNALS_TABLE, (sid, click) => this.pick(sid, click), { freeze: 1 });
    const cp = panel('quant-' + this.what + '-chart', 'Seçili seri', { wide: true, cls: 'qcardp' });
    this.chart = new SignalChart(cp.body);
    page.append(sp.el, cp.el);
    for (const p of panels) page.appendChild(p.el);
    this.host.appendChild(page);
    if (opts.jumps) this.addJumps(page);
  }

  fillSignals() {
    this.showSignals('Bu analizden şu an eşiği geçen sinyal yok.');
  }

  fill() {
    this.fillStatus();
    if (!this.data || !this.data.ready) return;
    this.fillSignals();
    this.fillPage();
  }

  afterPick() {
    this.fillSignals();
    if (this.fillPage) this.fillPage();
  }
}

// ------------------------------------------------------------------------------------------------ Korelasyon
class CorrPage extends AnalysisPage {
  constructor(host, ctx) {
    super(host, ctx, 'corr');
    this.window = Number(pref('tto.quant.corr.window', '60')) || 60;
    this.view = pref('tto.quant.corr.view', 'rho');
  }

  build() {
    this.winSeg = seg([[20, '20g'], [60, '60g'], [120, '120g']], this.window, (v) => { this.window = v; keep('tto.quant.corr.window', v); this.fillPage(); }, 'quant-corr-window');
    const viewSeg = seg([['rho', 'Korelasyon'], ['z', 'Kırılma z']], this.view, (v) => { this.view = v; keep('tto.quant.corr.view', v); this.fillPage(); }, 'quant-corr-view');
    this.heat = panel('quant-corr-heat', 'Günlük değişimlerin korelasyonu');
    this.heat.note.textContent = 'Değişimler: faizlerde bp, kurlarda ve endekslerde % (log), CDS\'te bp; iki serinin de kapanışı olan ardışık günler. Kırılma z: '
      + 'kısa pencerenin korelasyonunun (Fisher dönüşümüyle) kendi uzun dönem dağılımına göre yeri - son kısa pencere hariç, çakışmasın diye.';
    this.boxes.heat = new GridBox(this.heat, 'quant/corr/heat');
    this.pairs = panel('quant-corr-pairs', 'Çiftler · kırılma z sırasıyla');
    this.pairs.note.textContent = 'Sinyal: uzun dönem |ρ| eşiğin üstündeki çiftlerde |z| ≥ giriş. İşlem: son kısa pencerede ayrışan çiftin β ile yakınsaması.';
    this.boxes.pairs = new GridBox(this.pairs, 'quant/corr/pairs', (sid, click) => this.pick(sid, click));
    this.frame('Korelasyon', [this.pairs, this.heat], [h('span', { class: 'muted' }, 'Pencere'), this.winSeg, h('span', { class: 'muted' }, 'Göster'), viewSeg]);
  }

  fillPage() {
    const c = this.data.corr || {};
    if (!c.keys || !c.keys.length) {
      this.boxes.heat.set([], [], null, (c.why) || 'Korelasyon için yeterli seri yok');
      this.boxes.pairs.set([], [], null, 'Veri yok');
      return;
    }
    const w = String(c.windows && c.windows.includes(this.window) ? this.window : (c.windows || [60])[0]);
    const mat = this.view === 'z' ? c.z : (c.matrices || {})[w] || [];
    const rows = c.labels.map((lab, i) => [T(lab, { b: 1 })].concat(c.labels.map((_, j) => {
      const v = (mat[i] || [])[j];
      if (!isNum(v)) return { t: i === j ? '—' : '', k: '' };
      return { t: this.view === 'z' ? sgn(v, 1) : fmt(v, 2), v, k: 'n', heat: heatHex(this.view === 'z' ? v / 3 : v) || undefined,
        tip: c.labels[i] + ' ↔ ' + c.labels[j] + ' · ' + (this.view === 'z' ? 'kırılma z' : w + ' günlük ρ') + ' · ' + ((c.n || [])[i] || [])[j] + ' değişim' };
    })));
    this.boxes.heat.set([''].concat(c.labels.map((l) => ({ t: l, k: 's', b: 1, f: 'hd' }))), rows, null, 'Veri yok');
    this.heat.setTitle(this.view === 'z' ? 'Korelasyon kırılması · z (' + c.short + ' gün, uzun dönem dağılımına göre)' : 'Günlük değişimlerin korelasyonu · ' + w + ' gün');
    const pairs = (c.pairs || []).slice(0, 80);
    this.boxes.pairs.set(['A', 'B', 'Değişim', 'ρ ' + (c.windows || [])[0] + 'g', 'ρ ' + (c.windows || [])[1] + 'g', 'ρ ' + (c.windows || [])[2] + 'g', 'Uzun dönem ρ', 'Kırılma z', 'Yarı ömür', 'Sinyal'],
      pairs.map((p) => [T(p.a_label, { b: 1 }), T(p.b_label, { b: 1 }), N(p.n, 0)].concat((c.windows || []).map((x) => N((p.c || {})[String(x)], 2, { heat: heatHex((p.c || {})[String(x)]) })),
        [N(p.long, 2), Z(p.z, (this.data.settings || {}).entry_z), N(p.half_life, 1), T(p.signal ? 'izleniyor' : (isNum(p.long) && Math.abs(p.long) < c.min ? 'ilişki zayıf' : ''))])),
      pairs.map((p) => (p.signal ? 'corr:' + p.a + '|' + p.b : null)), 'Çift yok', this.picked);
  }
}

// ------------------------------------------------------------------------------------------------ PCA / RV
class PcaPage extends AnalysisPage {
  constructor(host, ctx) { super(host, ctx, 'pca'); this.charts = {}; }

  build() {
    this.factors = panel('quant-pca-factors', 'TRY OIS eğrisi · temel bileşenler');
    this.factors.note.textContent = 'Günlük değişimlerin (bp) kovaryansından Jacobi ile: PC1 seviye, PC2 eğim, PC3 eğrilik. Bugünkü skor: bugünkü hareketin bileşene '
      + 'izdüşümü, z = skor ÷ √λ; seviye z: bileşenin seviyesinin penceredeki yeri.';
    this.boxes.factors = new GridBox(this.factors, 'quant/pca/factors');
    this.loadChartHost = h('div', { class: 'volchart' });
    this.loadings = panel('quant-pca-loadings', 'Yükler (vade başına)', { top: this.loadChartHost, wide: true });
    this.boxes.loadings = new GridBox(this.loadings, 'quant/pca/loadings');
    this.dyn = panel('quant-pca-windows', 'Dinamik PCA · 60 / 120 / 250 günlük pencereler');
    this.dyn.note.textContent = 'Her pencerede günlük değişimlerin PCA\'sı (risk bileşenleri) ve seviyelerin PCA\'sı (eğrinin pencerede kaydığı yönler). Kararlılık: '
      + 'iki pencerenin aynı bileşen yüklerinin |kosinüsü| (1: aynı şekil) ve bir vadenin yükünün en büyük değişimi. Sinyaller, en az gözlem kadar kapanışı olan en uzun pencereyi kullanır (yazar).';
    this.boxes.dyn = new GridBox(this.dyn, 'quant/pca/windows');
    this.stab = panel('quant-pca-stability', 'Yüklerin kararlılığı (PC1–PC3, pencere çiftleri)', { cls: 'aux', folded: true });
    this.boxes.stab = new GridBox(this.stab, 'quant/pca/stability');
    this.loadw = panel('quant-pca-loadw', 'Yükler pencere pencere', { cls: 'aux', folded: true });
    this.boxes.loadw = new GridBox(this.loadw, 'quant/pca/loadw');
    this.resid = panel('quant-pca-resid', 'Zengin / ucuz · seviye-PCA\'sının PC1–PC2\'sine nötr paket');
    this.resid.note.textContent = 'Kalıntı: tenor ve iki komşusundan, seviyelerin PCA\'sının ilk iki bileşenine nötr paket (DV01 ağırlıklı), pencerenin ortalamasına göre (bp); '
      + '+ ise tenor ucuz (receive), − ise pahalı (pay). Seviye-PCA\'sı neden: bir döngü (indirim / artırım) eğriyi seviyelerin kaydığı yönlerde taşır; o yönler '
      + 'çıkarılınca kalan kalıntı döngüyle trend yapmaz. Değişimlerin PCA\'sına göre kalıntı (eski hali) döngünün yönüyle günlük risk bileşenleri aynı olmadığı '
      + 'için trendin bir kısmını taşır; kayan ortalamaya göre kalıntı ise trende gecikir. Diğer pencerelerin z\'si yanında.';
    this.boxes.resid = new GridBox(this.resid, 'quant/pca/resid', (sid, click) => this.pick(sid, click));
    this.rv = panel('quant-pca-rv', 'Fly ve spread\'ler · klasik (DV01 1:1 / 50/50) ve PCA ağırlıklı yan yana');
    this.rv.note.textContent = 'Klasik: masanın usulü, spread 1:1 (uzun bacak +1, kısa −1), fly 50/50 (gövde 1, kanatlar −0,5) - DV01 cinsinden, paralel kaymaya nötr. '
      + 'PCA ağırlıklı: spread PC1\'e nötr (uzun bacak 1), fly PC1 ve PC2\'ye nötr (gövde 1). Net DV01: Σ ağırlık × paket DV01\'i (TL/bp). PC1 / PC2 / PC3: '
      + 'bileşenin 1σ\'luk (günlük) hareketinde paketin hareketi (bp) = Σ ağırlık × yük × √λ - klasik fly\'ın gizli seviye / eğim maruziyetini, PCA fly\'ın sıfır olmayan '
      + 'net DV01\'ini gösterir. Nominal, masa ayarındaki paket DV01\'i için. Carry + roll: Carry & Roll sayfasının vade motorundan, ufuk A, haftalık. İkisi ayrı sinyal verebilir.';
    this.boxes.rv = new GridBox(this.rv, 'quant/pca/rv', (sid, click) => this.pick(sid, click), { freeze: 1 });
    this.fra = panel('quant-pca-fra', 'FRA / OIS forward\'ları · toplantı tarihli PPK patikasına göre');
    this.fra.note.textContent = 'Eğri forward\'ı: OIS kotalarından masanın konvansiyonuyla (≤ 3A tek ödeme, uzunlar üç ayda bir kupon) çözülen iskonto, '
      + 'log-doğrusal. Patika: tarihçenin PPK hesabı, aynı günün kotalarından (çözücünün taban seviyesinden başlar, her toplantının ertesi iş günü yeni '
      + 'seviye, iş günü bileşik). Patika kotaları yeniden ürettiği için fark normalde çözücünün toleransı içindedir; aşınca sinyal: + ise uzak bacak ucuz (FRA receive).';
    this.boxes.fra = new GridBox(this.fra, 'quant/pca/fra', (sid, click) => this.pick(sid, click));
    this.tenors = panel('quant-pca-tenors', 'Patikanın kotaları yeniden üretmesi · kota − patikanın par faizi (aynı gün, aynı konvansiyon)');
    this.boxes.tenors = new GridBox(this.tenors, 'quant/pca/tenors');
    this.periods = panel('quant-pca-periods', 'Toplantı dönemleri · patikanın seviyesi ve fiyatlanan adım', { cls: 'aux', folded: true });
    this.periods.note.textContent = 'Her dönem bir kararın ertesi gününden sonrakinin ertesi gününe (toplantı tarihli OIS gibi): patikanın o dönemki gecelik seviyesi '
      + 've bir önceki seviyeye göre fiyatlanan adım (bp).';
    this.boxes.periods = new GridBox(this.periods, 'quant/pca/periods');
    this.frame('PCA / RV', [this.resid, this.rv, this.fra, this.factors, this.dyn, this.tenors, this.loadings, this.periods, this.stab, this.loadw], [], { jumps: true });
  }

  destroy() {
    super.destroy();
  }

  fillPage() {
    const p = this.data.pca || {};
    const entry = (this.data.settings || {}).entry_z || 2;
    if (!p.ok) {
      this.boxes.factors.set([], [], null, p.why || 'PCA için veri yok');
      this.boxes.loadings.set([], [], null, '—');
      this.boxes.resid.set([], [], null, '—');
    } else {
      const today = p.today || {};
      this.boxes.factors.set(['Bileşen', 'Açıklanan', 'Varyans (bp²)', 'Bugünkü skor (bp)', 'Skor z', 'Seviye z'], (p.names || []).map((name, k) => [T(name, { b: 1 }),
        { t: pct((p.explained || [])[k], 1), v: (p.explained || [])[k], k: 'n' }, N((p.values || [])[k], 1), N((today.scores || [])[k], 1, { sign: true }),
        Z((today.z || [])[k], entry), Z((today.level_z || [])[k], entry)]), null, '—');
      this.boxes.loadings.set(['Vade', 'PC1', 'PC2', 'PC3'], (p.rows || []).map((r) => [T(r.label, { b: 1 })].concat((r.loadings || []).map((v) => N(v, 3, { sign: true })))), null, '—');
      const spec = { title: 'Yükler', cats: p.labels, auto: 'fit', decimals: 2, y_title: 'yük', aspect: 0.3,
        series: (p.vectors || []).map((v, k) => ({ name: (p.names || [])[k], kind: 'line', color: [BLUE, ORANGE, GREEN][k], data: v, marker: true })) };
      if (this.charts.load) this.charts.load.update(spec); else this.charts.load = new Chart(this.loadChartHost, spec, { height: 220 });
      const rows = p.rows || [];
      this.factors.setTitle('TRY OIS eğrisi · temel bileşenler (' + (p.window || '') + ' günlük pencere)');
      const zw = (r, w) => (r.z_windows || {})[String(w)];
      this.boxes.resid.set(['Vade', 'Pencere', 'Kalıntı (bp)', 'z', 'z (60 g)', 'z (120 g)', 'Yarı ömür (g)', 'Rejim', 'Hedge'], rows.map((r) => [T(r.label, { b: 1 }),
        T(isNum(r.window) ? r.window + ' g' : ''), N(r.resid, 1, { sign: true }), Z(r.z, entry), Z(zw(r, 60), entry), Z(zw(r, 120), entry), N(r.half_life, 1),
        T(REGIME[r.regime] || '—'), T((r.hedge || []).map((x) => x.key.split(':')[1] + ' ' + sgn(x.weight, 2)).join(' · '))]), rows.map((r) => 'pca:' + r.key), '—', this.picked);
      const wins = p.windows || [];
      this.boxes.dyn.set(['Pencere', 'İlk', 'Son', 'PC1 açıklanan', 'PC2', 'PC3', 'Seviye-PCA PC1', 'PC2', 'PC3', 'Sinyallerin penceresi'], wins.map((w) => [T(w.window + ' gün', { b: 1 }),
        T(isoToTr(w.first)), T(isoToTr(w.last))].concat((w.explained || []).slice(0, 3).map((x) => T(pct(x, 1))), (w.lvl_explained || []).slice(0, 3).map((x) => T(pct(x, 1))),
        [T(w.window === p.window ? '●' : '')])), null, 'Pencere yok');
      const st = p.stability || [];
      const pairs = [[60, 120], [120, 250], [60, 250]];
      this.boxes.stab.set(['Bileşen'].concat(...pairs.map(([a, b]) => [a + '↔' + b + ' |cos|', a + '↔' + b + ' en büyük Δ yük'])), st.map((r) => [T('PC' + r.pc, { b: 1 })]
        .concat(...pairs.map(([a, b]) => {
          const x = (r.pairs || []).find((q) => q.a === a && q.b === b) || {};
          return [N(x.cos, 3, { cls: isNum(x.cos) && x.cos < 0.9 ? 'thru' : '' }), N(x.max_move, 3)];
        }))), null, 'Karşılaştırılacak pencere yok');
      const tenors = (p.labels || []).map((l, i) => [l, (p.keys || [])[i]]);
      this.boxes.loadw.set(['Vade'].concat(...[1, 2, 3].map((c) => wins.map((w) => 'PC' + c + ' ' + w.window + 'g'))), tenors.map(([l, k]) => [T(l, { b: 1 })]
        .concat(...[0, 1, 2].map((c) => wins.map((w) => N(((w.loadings || {})[k] || [])[c], 3, { sign: true }))))), null, '—');
    }
    const rv = (this.data.rv || {}).rows || [];
    const rvRows = [];
    const rvKeys = [];
    for (const r of rv) {
      if (!r.versions) {
        rvRows.push([T(r.label, { b: 1 }), T(''), T(r.error || '', { cls: 'soft' })].concat(Array(10).fill(T(''))));
        rvKeys.push(null);
        continue;
      }
      for (const ver of ['klasik', 'pca']) {
        const v = r.versions[ver] || {};
        const ex = v.exposures || [];
        rvRows.push([T(v.name || r.label, { b: 1 }), T(ver === 'klasik' ? (r.kind === 'fly' ? 'klasik 50/50' : '1:1') : 'PCA ağırlıklı'),
          T((v.legs || []).map((l) => l.key.split(':')[1] + ' ' + sgn(l.weight, 2) + (isNum(l.notional) ? ' (' + fmt(l.notional, 1) + ' mn)' : '')).join(' · ') || v.error || ''),
          N(v.net_dv01, 0, { sign: true }), N(ex[0], 2, { sign: true }), N(ex[1], 2, { sign: true }), N(ex[2], 2, { sign: true }),
          N(v.level, 1), Z(v.z, entry), N(v.half_life, 1), N(v.carry, 2, { sign: true, tip: 'Paketin yükselişi (pay) için' }), T(REGIME[v.regime] || '—'),
          T(ver === 'klasik' ? (r.compare || '') : '', { cls: 'soft' })]);
        rvKeys.push(v.sid || null);
      }
    }
    this.boxes.rv.set(['Paket', 'Sürüm', 'Bacaklar (DV01 ağırlığı)', 'Net DV01 (TL/bp)', 'PC1 1σ (bp)', 'PC2 1σ (bp)', 'PC3 1σ (bp)', 'Seviye (bp)', 'z',
      'Yarı ömür (g)', 'Carry / hf (bp)', 'Rejim', 'Fark'], rvRows, rvKeys, 'Paket yok (Masa ayarları: PCA-nötr spread ve fly\'lar)', this.picked);
    const fra = this.data.frapath || {};
    const minBp = isNum(fra.min_bp) ? fra.min_bp : 5;
    this.boxes.fra.set(['Dönem', 'Eğri fwd %', 'Patika fwd %', 'Fark (bp)', 'z', 'Yarı ömür (g)', 'Gün'], (fra.rows || []).map((r) => [T(r.bucket, { b: 1 }),
      N(r.now && r.now.curve, 3), N(r.now && r.now.path, 3), N(r.now ? r.now.dev : r.dev, 1, { sign: true, cls: Math.abs((r.now ? r.now.dev : r.dev) || 0) < minBp ? 'soft' : '' }),
      Z(r.z, entry), N(r.half_life, 1), N(r.n, 0)]),
    (fra.rows || []).map((r) => r.sid || null), fra.why || 'Toplantı fiyatlama tarihçesi yok', this.picked);
    this.fra.setTitle('FRA / OIS forward\'ları · toplantı tarihli PPK patikasına göre' + (fra.live ? ' (bugünün patikası, canlı kotalar)'
      : (fra.last_day ? ' (son hesaplanan gün: ' + isoToTr(fra.last_day) + ')' : '')));
    this.tenors.note.textContent = (fra.convention || '') + ' Fark ' + fmt(minBp, 0) + ' bp\'yi aşmıyorsa patika kotaları yeniden üretiyor demektir.';
    this.boxes.tenors.set(['Vade', 'Konvansiyon', 'Kota %', 'Patika par %', 'Fark (bp)', 'En büyük |fark| (60 gün)', 'Gün'], (fra.tenors || []).map((r) => [T(r.label, { b: 1 }),
      T(r.convention || ''), N(r.quote, 3), N(r.path, 3), N(r.dev, 1, { sign: true, cls: Math.abs(r.dev || 0) >= minBp ? 'thru' : '' }), N(r.max_abs, 1), N(r.n, 0)]), null,
    'Patika yok (tarihçenin toplantı fiyatlama hesabı gerekli)');
    const per = fra.periods || [];
    this.boxes.periods.set(['Toplantı', 'Dönem', 'Patika %', 'Fiyatlanan adım (bp)', 'Dönem forward\'ı %'], per.map((r) => [T(isoToTr(r.meeting), { b: 1 }),
      T(isoToTr(r.start) + ' – ' + isoToTr(r.end)), N(r.path, 3), N(r.step, 1, { sign: true }), N(r.fwd, 3)]), null,
    fra.live ? 'Patikada dönem yok' : 'Bugünün patikası henüz yok (tarihçenin bugünkü PPK hesabından sonra)');
  }
}

// ------------------------------------------------------------------------------------------------ Çiftler
class PairsPage extends AnalysisPage {
  constructor(host, ctx) { super(host, ctx, 'pairs'); }

  build() {
    this.pairs = panel('quant-pairs-table', 'Eşbütünleşme taraması · Engle-Granger ve Kalman');
    this.pairs.note.textContent = 'y = α + β·x (son pencere), kalıntıya ADF (gecikme AIC ile, MacKinnon 2010 kritik değerleri, iki değişken). Geçer: ADF %5 ve |t(β)| ≥ 2. '
      + 'Spread (bp) = y − α − β·x; z pencereye göre. Kalman: β_t rastgele yürüyüş, kalıntı bir gün önceki β ile; ADF (tek seri) geçerse sinyal.';
    this.boxes.pairs = new GridBox(this.pairs, 'quant/pairs/table', (sid, click) => this.pick(sid, click), { freeze: 1 });
    this.cal = panel('quant-pairs-viop', 'VİOP takvim spread\'leri · faiz paritesine göre adil değer');
    this.cal.note.textContent = 'İki vade arasındaki ima TRY forward faizi (VİOP fiyatlarından) − aynı tarihler için OIS forward\'ı (bp). VİOP geçmişi sayfasındaki '
      + 'kontratlar ve "Geçmiş" gün sayısı kadar (en çok 240 iş günü); kayıtlı veri modunda VİOP geçmişi yoktur.';
    this.boxes.cal = new GridBox(this.cal, 'quant/pairs/viop', (sid, click) => this.pick(sid, click));
    this.frame('Çiftler', [this.pairs, this.cal]);
  }

  fillPage() {
    const entry = (this.data.settings || {}).entry_z || 2;
    const rows = (this.data.pairs || {}).rows || [];
    this.boxes.pairs.set(['Çift', 'Grup', 'Gün', 'β', 't(β)', 'R²', 'ADF', '%5 kritik', 'Geçti', 'Spread (bp)', 'z', 'Yarı ömür', 'Kalman β', 'Kalman z', 'Kalman ADF'],
      rows.map((r) => [T(r.label, { b: 1 }), T(r.group), N(r.n, 0), N(r.beta, 3), N(r.t_beta, 1), N(r.r2, 2), N(r.adf, 2), N(r.crit5, 2),
        T(r.error ? r.error : (r.passes ? '✓' : '—'), { cls: r.passes ? 'thru' : 'soft' }), N(r.spread, 1, { sign: true }), Z(r.z, entry), N(r.half_life, 1),
        N(r.k_beta, 3), Z(r.k_z, entry), T(isNum(r.k_adf) ? fmt(r.k_adf, 2) + (r.k_passes ? ' ✓' : '') : '')]),
      rows.map((r) => r.sid || r.k_sid || null), 'Çift yok', this.picked);
    const cal = (this.data.viopcal || {}).rows || [];
    this.boxes.cal.set(['Takvim', 'Gün', 'Fark (bp)', 'z', 'Yarı ömür (g)'], cal.map((r) => [T(r.label, { b: 1 }), N(r.n, 0), N(r.dev, 1, { sign: true }), Z(r.z, entry),
      N(r.half_life, 1)]), cal.map((r) => r.sid || null), 'VİOP geçmişi yok (kayıtlı veri modunda yalnızca canlı nokta vardır)', this.picked);
  }
}

// ------------------------------------------------------------------------------------------------ Rejim & Momentum
class RegimePage extends AnalysisPage {
  constructor(host, ctx) { super(host, ctx, 'regime'); }

  build() {
    this.mom = panel('quant-regime-momentum', 'Momentum panosu');
    this.mom.note.textContent = '1H / 1A / 3A: değişim ÷ (günlük vol × √gün); skor üçünün ortalaması. FX: spot değil, forward pozisyonunun getirisi (kur değişimi − '
      + 'forward primi: + ise kur forward\'ların fiyatladığından hızlı gidiyor) - forward primi aleyhine bir işlem, beklenen kazancı onu tamponla karşılamıyorsa '
      + 'elenir; sinyal kartında işlem forward\'ın kuruyla ve 1 mn baz döviz başına K/Z ile. Sıra: eğri, FX ve küresel gruplar içinde. '
      + 'Ortalamalar: hızlı / yavaş hareketli ortalama (↑ hızlı üstte) ve kaç gündür. Sinyal: |skor| ≥ momentum eşiği, ortalamalar aynı yönde, rejim trend (nötrde yarım ağırlık).';
    this.boxes.mom = new GridBox(this.mom, 'quant/regime/momentum', (sid, click) => this.pick(sid, click), { freeze: 1 });
    this.cycle = panel('quant-regime-cycle', 'PPK döngüsü · eğim davranışı');
    this.cycle.note.textContent = 'Faz: TLREF\'in son 63 iş günündeki değişimi ≤ −eşik indirim, ≥ +eşik artırım, arası sabit. Her fazda eğimin sonraki ufuk boyunca değişimi; '
      + 't Newey-West ile (çakışan gözlemler). Küçük örneklem: n çakışan gözlem ≈ n ÷ ufuk bağımsız dönem; az dönemle Newey-West t\'si şişer, eşik o örneklemin '
      + 'benzetimle bulunan %5 kritik değeri (2 dönemde ≈ 7,8, 5 dönemde ≈ 3,8, 20 dönemde ≈ 2,6). Bugünkü fazda |t| bu eşiği geçerse steepener / flattener sinyali.';
    this.boxes.cycle = new GridBox(this.cycle, 'quant/regime/cycle');
    this.reg = panel('quant-regime-table', 'İzlenen serilerin rejimi', { cls: 'aux' });
    this.reg.note.textContent = 'Varyans oranı VR(q) (Lo-MacKinlay, değişen varyansa dayanıklı z): z ≤ −1,645 ortalamaya dönüş, ≥ +1,645 trend, arası nötr. H: varyans-zaman '
      + 'Hurst üsteli (0,5 rastgele yürüyüş). Vol yüzdelik: bugünkü 20 günlük vol\'ün penceredeki yeri.';
    this.boxes.reg = new GridBox(this.reg, 'quant/regime/table', (sid, click) => this.pick(sid, click));
    this.frame('Rejim & Momentum', [this.mom, this.cycle, this.reg]);
  }

  fillPage() {
    const st = this.data.settings || {};
    const rows = (this.data.momentum || {}).rows || [];
    this.boxes.mom.set(['Enstrüman', 'Grup', 'Seviye', '1H', '1A', '3A', 'Skor', 'Sıra', 'Ortalamalar', 'Rejim', 'H', 'VR z', 'Vol yüzd.', 'Carry % / yıl (long)'],
      rows.map((r) => (r.error ? [T(r.label, { b: 1 }), T(r.group), T(r.error, { cls: 'soft' }), T(''), T(''), T(''), T(''), T(''), T(''), T(''), T(''), T(''), T(''),
        N(r.carry, 1, { sign: true })]
        : [T(r.label + (r.key.startsWith('XR:') ? ' · forward' : ''), { b: 1, tip: r.key.startsWith('XR:') ? 'Forward pozisyonunun birikimli getirisi (%): kur değişimi − forward primi' : '' }),
          T(r.group), N(r.level, r.unit === '%' ? 3 : 4), N(r.w1, 2, { sign: true }),
          N(r.m1, 2, { sign: true }), N(r.m3, 2, { sign: true }), Z(r.score, st.mom_entry || 1.5), T(r.rank ? r.rank + '/' + r.of : ''),
          T(ARROW(r.state) + ' ' + (r.since || 0) + 'g'), T(REGIME[r.regime] || '—'), N(r.hurst, 2), N(r.vr_z, 2, { sign: true }), T(pct(r.vol_pct)),
          N(r.carry, 1, { sign: true })])), rows.map((r) => (r.error ? null : 'momentum:' + r.key)), 'Momentum için geçmiş yok', this.picked);
    const cy = this.data.cycle || {};
    const crow = [];
    for (const r of cy.rows || []) {
      for (const ph of ['indirim', 'sabit', 'artırım']) {
        const s = (r.stats || {})[ph] || {};
        const thr = Math.max(st.cycle_t || 2, isNum(s.cv) ? s.cv : 0);
        crow.push([T(r.slope, { b: 1 }), T(ph + (ph === cy.phase ? ' (bugün)' : ''), { b: ph === cy.phase ? 1 : 0 }), N(s.mean, 1, { sign: true }), Z(s.t, thr),
          N(s.sd, 1), N(s.n, 0), N(s.periods, 1), T(isNum(s.cv) ? fmt(s.cv, 2) : (s.n ? 'test yok' : ''), { cls: isNum(s.cv) ? '' : 'soft' }), N(r.level, 1)]);
      }
    }
    this.boxes.cycle.set(['Eğim', 'Faz', 'Ort. değişim (bp, ufukta)', 't (NW)', 'σ', 'Gözlem', 'Bağımsız dönem', 'Eşik |t|', 'Bugün (bp)'], crow, null,
      cy.why || 'TLREF / eğim geçmişi yok');
    this.cycle.setTitle('PPK döngüsü · bugünkü faz: ' + (cy.phase || '—') + (cy.counts ? ' (gün: indirim ' + cy.counts['indirim'] + ', sabit ' + cy.counts['sabit']
      + ', artırım ' + cy.counts['artırım'] + ')' : ''));
    const reg = this.data.regime || [];
    this.boxes.reg.set(['Aile', 'Seri', 'Rejim', 'VR', 'VR z', 'H', 'Vol yüzd.', 'Gün'], reg.map((r) => [T(r.family), T(r.name, { b: 1 }), T(REGIME[r.tag] || '—'),
      N(r.vr, 2), N(r.vr_z, 2, { sign: true }), N(r.hurst, 2), T(pct(r.vol_pct) + (r.vol_tag ? ' · ' + r.vol_tag : '')), N(r.n, 0)]), reg.map((r) => r.sid), 'Seri yok', this.picked);
  }
}

// ------------------------------------------------------------------------------------------------ FX vol premium, EM carry, forward premium
class FxPage extends AnalysisPage {
  constructor(host, ctx) { super(host, ctx, 'fx'); }

  build() {
    this.sum = panel('quant-fx-summary', 'Parite özeti · carry, beklenen kayma, tampon, karar');
    this.sum.note.textContent = 'Carry (long): baz dövizi forward\'la alanın forward priminden yıllık kazancı (+) ya da ödediği (−): (ln S − ln F) × 365 / gün, '
      + 'sürekli bileşik, en kısa forward\'tan (USDTRY: 1A / 3A / 6A / 1Y de); USDTRY\'de forward spotun üstünde: long TRY faizini öder. '
      + 'Beklenen kayma: günlük log getirilerin EWMA\'sı (λ 0,97) yıllık, kendi kesinliğiyle sıfıra doğru küçültülmüş (gürültü olan kayma tahmin sayılmaz; ağırlık '
      + 'sütunda). Beklenen getiri (long): kayma + carry. Tampon: carry\'yi alan tarafın beklenen getirisi (− ise kayma carry\'yi yiyor). Karar: beklenen getiri ÷ vol '
      + 'masa eşiğini geçerse ilgili para birimi long / short, yoksa nötr. Forward\'ı olmayan pariteye carry uydurulmaz.';
    this.boxes.sum = new GridBox(this.sum, 'quant/fx/summary', null, { freeze: 1 });
    this.sum.tools.append(...boxTools(() => ({ type: 'fx-summary', w: 12 }), this.ctx));
    this.vol = panel('quant-fx-vol', 'İma − gerçekleşen vol ve GARCH tahmini (3M ATM)');
    this.vol.note.textContent = 'Gerçekleşen: günlük log getirilerin σ\'sı × √252, 21 / 63 / 126 gün. Vol primi = ima − 63 günlük; GARCH(1,1) (ızgara üzerinde en çok olabilirlik, '
      + 'uzun dönem varyans hedefli) önümüzdeki 63 iş gününün ortalama vol\'ü; EWMA λ 0,94. + z: vol pahalı (sat), − z: ucuz (al). Skew β: 25D RR\'nin spotun %1\'lik '
      + 'hareketine tepkisi (vol puanı, 63 gün).';
    this.boxes.vol = new GridBox(this.vol, 'quant/fx/vol', (sid, click) => this.pick(sid, click), { freeze: 1 });
    this.carry = panel('quant-fx-carry', 'EM carry / risk sıralaması');
    this.carry.note.textContent = 'Carry: 3M forward\'ın ima ettiği yıllık getiri farkı (USD\'ye karşı, %); carry / vol = carry ÷ ATM 3M vol. TRY göreli: TRY\'nin carry / vol\'ü '
      + '− EM sepetinin ortalaması; z kendi geçmişine göre (+ ise TRY carry\'si göreli cazip).';
    this.boxes.carry = new GridBox(this.carry, 'quant/fx/carry', (sid, click) => this.pick(sid, click));
    this.fwd = panel('quant-fx-fwd', 'Forward primi · carry zamanlaması');
    this.fwd.note.textContent = 'İma değer kaybı: (F/S − 1) × 365 / gün; beklenen kayma: günlük getirilerin EWMA\'sı (λ 0,97) yıllık; gerçekleşen: vade kadar geriye. '
      + 'Tampon = ima − beklenen; + z: forward kaybı fazla fiyatlıyor → carry (TRY al), − z: tersi. USDTRY trendde ise sinyal bekletilir.';
    this.boxes.fwd = new GridBox(this.fwd, 'quant/fx/fwd', (sid, click) => this.pick(sid, click));
    this.frame('FX Vol Primi & Carry', [this.sum, this.vol, this.carry, this.fwd]);
  }

  fillPage() {
    const entry = (this.data.settings || {}).entry_z || 2;
    const fs = this.data.fxsum || {};
    this.boxes.sum.set(FX_SUMMARY_HEAD, fxSummaryRows(fs), null, fs.why || 'Spot / forward tarihçesi yok');
    const rows = (this.data.vol || {}).rows || [];
    this.boxes.vol.set(['Parite', 'İma', 'Gerç. 21g', 'Gerç. 63g', 'Gerç. 126g', 'Prim', 'Prim z', 'EWMA', 'GARCH', 'α', 'β', 'İma − GARCH', 'z', 'Skew β (t)'],
      rows.map((r) => [T(r.pair, { b: 1 }), N(r.iv, 2), N(r.rv21, 2), N(r.rv63, 2), N(r.rv126, 2), N(r.vrp, 2, { sign: true }), Z(r.vrp_z, entry), N(r.ewma, 2), N(r.garch, 2),
        N(r.garch_fit && r.garch_fit.alpha, 3), N(r.garch_fit && r.garch_fit.beta, 3), N(r.vf, 2, { sign: true }), Z(r.vf_z, entry),
        T(isNum(r.skew_beta) ? sgn(r.skew_beta, 3) + ' (' + fmt(r.skew_t, 1) + ')' : '')]), rows.map((r) => r.vrp_sid || r.vf_sid || null),
      'Vol geçmişi yok: spot ve ATM 3M vol tarihçesi gerekli', this.picked);
    const cr = (this.data.emcarry || {}).rows || [];
    this.boxes.carry.set(['Sıra', 'Para birimi', 'Carry %', 'Vol %', 'Carry / vol', 'z (kendi)', 'Δ 1A', 'TRY göreli', 'Göreli z'], cr.map((r) => [N(r.rank, 0),
      T(r.ccy, { b: 1 }), N(r.carry, 2), N(r.vol, 2), N(r.cv, 3), Z(r.z, entry), N(r.m1, 3, { sign: true }), N(r.rel, 3, { sign: true }), Z(r.rel_z, entry)]),
    cr.map((r) => (r.ccy === 'TRY' ? 'emcarry:TRY' : null)), 'Carry için spot, forward puanı ve vol tarihçesi gerekli', this.picked);
    const fw = (this.data.fwdprem || {}).rows || [];
    this.boxes.fwd.set(['Parite', 'Vade', 'İma kayıp %', 'Gerçekleşen %', 'Beklenen %', 'Tampon', 'z', 'Yarı ömür (g)', 'Gün'], fw.map((r) => [T(r.pair, { b: 1 }), T(r.tenor),
      N(r.implied, 2), N(r.realized, 2, { sign: true }), N(r.forecast, 2, { sign: true }), N(r.cushion, 2, { sign: true }), Z(r.z, entry), N(r.half_life, 1), N(r.n, 0)]),
    fw.map((r) => r.sid || null), 'Forward puanı tarihçesi yok', this.picked);
  }
}

/** The pair summary's caption row and rows (the page's and its box's). */
export const FX_SUMMARY_HEAD = ['Parite', 'Grup', 'Spot', 'Carry % / yıl (long)', 'Forward\'lar', 'Beklenen kayma % / yıl', 'Kayma ağırlığı',
  'Beklenen getiri (long) % / yıl', 'Tampon (carry tarafı)', 'Vol', 'Getiri / vol', 'Karar'];

export function fxSummaryRows(fs) {
  const term = (r) => Object.entries(r.term || {}).map(([t, v]) => t + ' ' + sgn(v, 1)).join(' · ');
  return ((fs || {}).rows || []).map((r) => [T(r.pair, { b: 1 }), T(r.group), N(r.spot, 4), N(r.carry_long, 1, { sign: true }),
    T(term(r)), N(r.drift, 1, { sign: true, tip: isNum(r.drift_raw) ? 'küçültülmeden: ' + sgn(r.drift_raw, 1) : '' }), T(pct(r.drift_w)), N(r.exp_long, 1, { sign: true }),
    N(r.buffer, 1, { sign: true, cls: isNum(r.buffer) && r.buffer < 0 ? 'soft' : '' }), T(isNum(r.vol) ? fmt(r.vol, 1) + ' (' + r.vol_src + ')' : ''),
    N(r.sharpe, 2, { sign: true }), T(r.verdict || '', { b: 1, cls: r.verdict && r.verdict.endsWith('long') ? 'thru' : (r.verdict === 'nötr' ? 'soft' : '') })]);
}

// ------------------------------------------------------------------------------------------------ Makro beta
class MacroPage extends AnalysisPage {
  constructor(host, ctx) { super(host, ctx, 'macro'); this.charts = {}; }

  build() {
    this.betas = panel('quant-macro-betas', 'TRY eğrisi · küresel sürücülere betalar');
    this.betas.note.textContent = 'Günlük değişimlerin (bp) EKK regresyonu, ortak günlerde (kapanış saatleri farklı: betalar biraz küçük çıkar). Bugün: hareket = α + Σ β × '
      + 'sürücünün değişimi (küresel) + TRY\'ye özgü kalıntı; z = kalıntı ÷ σ. Canlı değer yoksa son kapanış günü.';
    this.boxes.betas = new GridBox(this.betas, 'quant/macro/betas', (sid, click) => this.pick(sid, click));
    this.attrHost = h('div', { class: 'volchart' });
    this.attr = panel('quant-macro-attr', 'Bugünkü hareketin ayrıştırılması (bp)', { top: this.attrHost, wide: true });
    this.boxes.attr = new GridBox(this.attr, 'quant/macro/attr', (sid, click) => this.pick(sid, click));
    this.frame('Makro Beta', [this.betas, this.attr]);
  }

  fillPage() {
    const m = this.data.macro || {};
    const entry = (this.data.settings || {}).entry_z || 2;
    const labels = m.driver_labels || [];
    const rows = m.rows || [];
    this.boxes.betas.set(['Hedef', 'Gün', 'R²', 'σ', 'Geri dönüş β (t)'].concat(labels.map((l) => 'β ' + l)), rows.map((r) => [T(r.label, { b: 1 }), N(r.n, 0), N(r.r2, 2),
      N(r.sigma, r.unit === '%' ? 3 : 1, { unit: r.unit || 'bp' }), T(isNum(r.rev_beta) ? sgn(r.rev_beta, 2) + ' (' + fmt(r.rev_t, 1) + ')' : '',
        { tip: 'Kalıntının ertesi hafta geri dönen payı: sonraki 5 günün hareketinin bugünkü kalıntıya regresyonu (− ise geri döner)' })]
      .concat(labels.map((_, i) => (r.betas ? N(r.betas[i], 3, { sign: true, tip: 't = ' + fmt((r.t || [])[i], 1), cls: isNum((r.t || [])[i]) && Math.abs(r.t[i]) >= 2 ? 'thru' : '' })
        : T(r.error || '', { cls: 'soft' }))))), rows.map((r) => 'macro:' + r.key), m.why || 'Veri yok', this.picked);
    this.boxes.attr.set(['Vade', 'Ne zaman', 'Hareket', 'Küresel', 'TRY\'ye özgü', 'z'].concat(labels), rows.filter((r) => r.today).map((r) => [T(r.label, { b: 1 }), T(r.today.when),
      N(r.today.dy, 1, { sign: true }), N(r.today.global, 1, { sign: true }), N(r.today.resid, 1, { sign: true }), Z(r.z, entry)]
      .concat((r.today.parts || []).map((v) => N(v, 1, { sign: true })))), rows.filter((r) => r.today).map((r) => 'macro:' + r.key), 'Bugün için ayrıştırma yok', this.picked);
    const withToday = rows.filter((r) => r.today);
    if (withToday.length) {
      const colors = [BLUE, ORANGE, GREEN, PURPLE, GREY, '4BACC6'];
      const series = labels.map((l, i) => ({ name: l, kind: 'bar', stacked: true, color: colors[i % colors.length], data: withToday.map((r) => (r.today.parts || [])[i]) }));
      series.push({ name: 'TRY\'ye özgü', kind: 'bar', stacked: true, color: RED, data: withToday.map((r) => r.today.resid) });
      const spec = { title: 'Ayrıştırma', cats: withToday.map((r) => r.label), auto: 'fit', decimals: 1, y_title: 'bp', aspect: 0.3, series };
      if (this.charts.attr) this.charts.attr.update(spec); else this.charts.attr = new Chart(this.attrHost, spec, { height: 240 });
    }
  }
}

// ------------------------------------------------------------------------------------------------ the forecast model
class ModelPage extends AnalysisPage {
  constructor(host, ctx) { super(host, ctx, 'model'); }

  build() {
    this.table = panel('quant-model-table', 'Gelecek haftanın yönü · L2 lojistik regresyon, kayan pencereli doğrulama');
    this.table.note.textContent = 'Özellikler (her gün yalnızca o güne kadarki kapanışlarla): 60 günlük z, 1H ve 1A momentum (vol ile ölçekli), carry, rejim (değişimlerin '
      + 'birinci derece otokorelasyonu), vol (20 / 120 günlük oranının logu); eğitim penceresinin kendi ortalamasıyla standartlaştırılır. Doğrulama: her hafta bir test '
      + 'noktası, model yalnızca etiketi o güne kadar bilinen örneklerle (dört haftada bir yeniden) kurulur - ileriye bakış yok. Sinyal: doğrulanmış isabet ≥ eşik, '
      + 'yeterli test noktası ve z = (p − 0,5) ÷ 0,05 girişin üstünde.';
    this.boxes.table = new GridBox(this.table, 'quant/model/table', (sid, click) => this.pick(sid, click));
    this.frame('Tahmin Modeli', [this.table]);
  }

  fillPage() {
    const md = this.data.model || {};
    const st = this.data.settings || {};
    const feats = md.features || [];
    const rows = md.rows || [];
    // (the same columns as Makine öğrenmesi's under the same names: "Basılıyor" ✓ or why not, "Olasılık (yukarı)")
    this.boxes.table.set(['Enstrüman', 'Test', 'İsabet', 'Taban oran', 'Log-loss', 'Olasılık (yukarı)', 'Basılıyor'].concat(feats.map((f) => 'β ' + f)),
      rows.map((r) => [T(r.label, { b: 1 }), N(r.n_test, 0), { t: pct(r.hit_rate, 1), v: r.hit_rate, k: 'n', cls: isNum(r.hit_rate) && r.hit_rate >= (st.model_hit || 0.55) ? 'thru' : '' },
        T(pct(r.base_rate, 1)), N(r.log_loss, 3), T(pct(r.p, 1)), T(r.error || (r.valid ? '✓' : (r.why || '—')), { cls: r.valid ? 'thru' : 'soft' })]
        .concat(feats.map((_, i) => N(r.coef ? r.coef[i + 1] : null, 2, { sign: true })))), rows.map((r) => (r.valid ? 'model:' + r.key : null)), 'Model için geçmiş yok', this.picked);
  }
}

// ------------------------------------------------------------------------------------------------ Gün İçi
class IntradayPage extends AnalysisPage {
  constructor(host, ctx) { super(host, ctx, 'intraday'); }

  build() {
    this.st = panel('quant-intraday-bars', 'Gün içi barlar · dashboard\'un zaten okuduğu canlı değerlerden');
    this.st.note.textContent = 'Bloomberg\'e ayrı istek yok: quant iş parçacığı dakikada bir okuduğu canlı değerleri (OIS / offshore kotaları, FX spotları, USDTRY 1A '
      + 'puanı) canlı modda, iş günü 09:30 – 18:00 arasında dakikalık kapanış olarak saklar (son 20 işlem günü, küçük bir SQLite dosyası); 5 dakikalık barlar bunlardan. '
      + 'Gün içi sinyaller dakikada bir yenilenir, kendi ufukları (bar) ve stop\'larıyla; seans sonunda kapanır, gece taşınmaz. PPK günü 13:45 – 15:30 arası ortalamaya '
      + 'dönüş sinyali verilmez; 17:00\'den sonra yeni gün içi işlem yok.';
    this.boxes.st = new GridBox(this.st, 'quant/intraday/bars');
    this.z = panel('quant-intraday-z', 'Gün içi z ve açılış aralığı');
    this.z.note.textContent = 'Uzaklık: seviyenin günün son 60 dakikalık ortalamasına uzaklığı (faizde bp, kurda %), z son 20 günün 5 dakikalık dağılımına göre; '
      + 'yarı ömür bar (5 dk) cinsinden. Açılış aralığı: ilk 30 dakika; skor (seviye − orta) ÷ yarı genişlik, ±1,5 kırılım; kırılım sayısı ve kapanışa kadar ortalama devamı '
      + 'son günlerden.';
    this.boxes.z = new GridBox(this.z, 'quant/intraday/z', (sid, click) => this.pick(sid, click));
    this.rv = panel('quant-intraday-rv', 'Gün içi RV · spread\'ler 5 dakikalık barlarda');
    this.boxes.rv = new GridBox(this.rv, 'quant/intraday/rv', (sid, click) => this.pick(sid, click));
    this.path = panel('quant-intraday-path', 'USDTRY · carry\'nin ima ettiği gün içi patika');
    this.path.note.textContent = 'Patika: günün açılışından forward priminin dakika dakika ima ettiği değer kaybıyla; fark (%, log) bar gürültüsü × √bar ile z. '
      + '+ ise spot patikanın önünde (sat), − ise gerisinde (al).';
    this.boxes.path = new GridBox(this.path, 'quant/intraday/path', (sid, click) => this.pick(sid, click));
    this.frame('Gün İçi', [this.z, this.rv, this.path, this.st]);
  }

  fillPage() {
    const d = this.data.intraday || {};
    const entry = (this.data.settings || {}).entry_z || 2;
    const s = d.stats || {};
    this.boxes.st.set(['Durum', 'Değer'], [[T('Bar kaydı'), T(d.ok ? s.days + ' gün · ' + s.rows + ' dakika kapanışı' : (d.why || '—'), { cls: d.ok ? '' : 'soft' })],
      [T('Son bar'), T(s.last || '—')], [T('Bugün PPK günü'), T(d.meeting_day ? 'evet (13:45 – 15:30 ortalamaya dönüş yok)' : 'hayır')]], null, '—');
    const zr = d.z || [];
    this.boxes.z.set(['Seri', 'Son', 'Uzaklık', 'z', 'Yarı ömür (bar)', 'Aralık alt', 'Aralık üst', 'Aralık skoru', 'Kırılım (gün)', 'Ort. devam'], zr.map((r) => [T(r.label, { b: 1 }),
      N(r.last, 4), N(r.dev, 2, { sign: true, unit: r.unit }), Z(r.z, entry), N(r.half_life, 1), N(r.or_low, 4), N(r.or_high, 4), Z(r.or_score, 1.5), N(r.breaks, 0),
      N(r.cont, 2, { sign: true, unit: r.unit })]), zr.map((r) => r.sid || null), d.why || 'Gün içi bar yok', this.picked);
    const rv = d.rv || [];
    this.boxes.rv.set(['Spread', 'Şimdi (bp)', 'Ortalama', 'σ', 'z', 'Yarı ömür (bar)'], rv.map((r) => [T(r.name, { b: 1 }), N(r.now, 1), N(r.mean, 1), N(r.sd, 2), Z(r.z, entry),
      N(r.half_life, 1)]), rv.map((r) => r.sid || null), d.why || 'Gün içi bar yok', this.picked);
    const p = d.path;
    this.boxes.path.set(['Açılış', 'Spot', 'Patika', 'Fark %', 'z', 'Carry % / yıl (long)', 'Bar σ %'], p ? [[N(p.open, 4), N(p.spot, 4), N(p.path, 4), N(p.dev, 3, { sign: true }),
      Z(p.z, entry), N(p.carry, 1, { sign: true }), N(p.sigma_bar, 3)]] : [], p ? [p.sid] : [], d.why || 'USDTRY barı ya da forward yok', this.picked);
  }
}

const PAGES = { 'quant-corr': CorrPage, 'quant-pca': PcaPage, 'quant-pairs': PairsPage, 'quant-regime': RegimePage, 'quant-fx': FxPage, 'quant-macro': MacroPage,
  'quant-model': ModelPage, 'quant-intraday': IntradayPage };

export function quantView(id, host, ctx) {
  const P = PAGES[id] || CorrPage;
  return new P(host, ctx);
}
