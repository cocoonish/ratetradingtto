// The fitted-model pages of the quant package (tto/quantcurve.py, tto/quantopt.py): Eğri Adil Değeri - the
// Nelson-Siegel-Svensson fits of the TRY OIS curve and of DİBS, each point's rich / cheap with its z, the bonds' carry
// + roll and the best bond to receive / pay with - and Opsiyon - the USDTRY / EURUSD vol surface (ATM term structure,
// 25D / 10D risk reversals and butterflies), its signals, the smile's distribution against the forward next to how
// often the spot ended that far from it.  Each lists its own signals at the top and draws a picked row's series below
// them, like the analysis pages of quantviews.js.
import { h, clear } from '../ui.js';
import { Chart } from '../chart.js';
import { isoToTr } from '../format.js';
import { QuantPage, GridBox, SignalChart, panel, signalRows, SIGNAL_HEAD, T, N, Z, fmt, sgn, pct, isNum, REGIME,
  BLUE, ORANGE, GREEN, PURPLE, RED, GREY } from './quantbase.js';

const KIND = { fixed: 'Sabit', bill: 'Bono' };
const CONV = { simple: 'basit', compound: 'bileşik' };

/** The frame of a page: its signals, the chart of a picked row, its panels, the status (as quantviews.js's). */
class FitPage extends QuantPage {
  frame(title, panels) {
    this.tools([]);
    const page = h('div', { class: 'volpage quantpage' });
    const sp = panel('quant-' + this.what + '-signals', title + ' · sinyaller');
    sp.note.textContent = 'Bu analizden çıkan sinyaller (elenenler gri, nedeniyle). Satıra tıklayın: seri ve giriş / hedef / stop aşağıda.';
    this.boxes.sig = new GridBox(sp, 'quant/' + this.what + '/signals', (sid) => this.pick(sid));
    const cp = panel('quant-' + this.what + '-chart', 'Seçili seri');
    this.chart = new SignalChart(cp.body);
    page.append(sp.el, cp.el);
    for (const p of panels) page.appendChild(p.el);
    this.addStatus(page);
    this.host.appendChild(page);
  }

  fillSignals() {
    const list = this.data.signals || [];
    this.boxes.sig.set(SIGNAL_HEAD.concat(['Bileşik / neden', 'Saat']), list.map((s) => {
      const row = signalRows([s], { gated: !!s.gated })[0];
      if (s.gated) for (const c of row) if (c && typeof c === 'object') c.cls = ((c.cls || '') + ' soft').trim();
      return row;
    }), list.map((s) => s.id), 'Bu analizden şu an eşiği geçen sinyal yok.', this.picked);
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

  /** A chart in ``host`` drawn (or redrawn) from ``spec``; nothing drawn without a series. */
  draw(name, host, spec) {
    if (!spec.series.some((s) => (s.data || []).some(isNum))) {
      if (this.charts[name]) { this.charts[name].destroy(); this.charts[name] = null; }
      clear(host);
      return;
    }
    if (this.charts[name]) this.charts[name].update(spec); else this.charts[name] = new Chart(host, spec, { height: 240 });
  }
}

// ------------------------------------------------------------------------------------------------ Eğri Adil Değeri
/** The fit in a line: its zero rates at round maturities (what the curve says), τ1 / τ2, then the β (few noisy points
 * can drive the β far apart while the curve inside them stays put). */
const params = (p) => (p ? 'Sıfır (sürekli) ' + Object.entries(p.zero || {}).map(([k, v]) => k + ' ' + fmt(v, 2) + '%').join(' · ')
  + ' · τ1 ' + fmt(p.tau1, 2) + ' · τ2 ' + fmt(p.tau2, 2) + ' yıl (β0 ' + fmt(p.b0, 1) + ' · β1 ' + sgn(p.b1, 1) + ' · β2 ' + sgn(p.b2, 1)
  + ' · β3 ' + sgn(p.b3, 1) + ')' : '');

class CurvePage extends FitPage {
  constructor(host, ctx) { super(host, ctx, 'curve'); this.charts = {}; }

  build() {
    this.oisChart = h('div', { class: 'volchart' });
    this.ois = panel('quant-curve-ois', 'TRY OIS · NSS uyumu', { top: this.oisChart });
    this.boxes.ois = new GridBox(this.ois, 'quant/curve/ois', (sid) => this.pick(sid));
    this.bondChart = h('div', { class: 'volchart' });
    this.bonds = panel('quant-curve-dibs', 'DİBS · NSS uyumu (sabit kuponlu ve bonolar)', { top: this.bondChart });
    this.boxes.bonds = new GridBox(this.bonds, 'quant/curve/dibs', (sid) => this.pick(sid));
    this.best = panel('quant-curve-best', 'Receive / pay için en iyi kâğıt');
    this.best.note.textContent = 'Puan = z × (1 aylık carry + roll) ÷ σ (kâğıdın 1 aylık getiri oynaklığı): z ile carry aynı yönü gösterdiğinde artı. '
      + 'Receive (al): ucuz (z > 0) ve carry\'si artı; pay (sat): pahalı (z < 0) ve carry\'si eksi (açığa satış onu kazanır). Carry\'si z\'ye ters olan '
      + 'kâğıt kendi tarafında eksi puanla sonda.';
    this.boxes.best = new GridBox(this.best, 'quant/curve/best', (sid) => this.pick(sid));
    this.frame('Eğri Adil Değeri', [this.ois, this.bonds, this.best]);
  }

  fillPage() {
    const entry = (this.data.settings || {}).entry_z || 2;
    const c = this.data.curve || {};
    if (!c.ok) {
      this.boxes.ois.set([], [], null, c.why || 'OIS eğrisi için veri yok');
      this.draw('ois', this.oisChart, { series: [] });
    } else {
      const rows = c.rows || [];
      this.boxes.ois.set(['Vade', 'Kota %', 'NSS par %', 'Fark (bp)', 'z', 'Yarı ömür (g)', 'Rejim', 'Sıfır %', 'Fwd %', 'Gün', 'Hedge'],
        rows.map((r) => [T(r.label, { b: 1 }), N(r.par, 3, { tip: r.live ? 'canlı' : 'son kapanış' }), N(r.fit, 3), N(r.resid, 1, { sign: true, b: 1 }), Z(r.z, entry),
          N(r.half_life, 1), T(REGIME[r.regime] || '—'), N(r.zero, 3), N(r.fwd, 3), N(r.n, 0),
          T((r.hedge || []).map((x) => x.key.split(':')[1] + ' ' + sgn(x.weight, 2)).join(' · '))]),
        rows.map((r) => r.sid || null), '—', this.picked);
      this.ois.note.textContent = 'Kotalar Excel\'in OIS kuralıyla (Motor: ' + (c.conv || '') + ') NSS\'e uydurulur; fark = kota − NSS par (bp): + ucuz '
        + '(receive), − pahalı (pay). τ\'lar son kapanışta aranır (' + isoToTr(c.tau_day) + '), pencerenin her günü ve canlı nokta aynı τ ile. '
        + params(c.params) + ' · RMSE ' + fmt(c.rmse, 1) + ' bp, ' + c.n + ' vade, ' + (c.days || 0) + ' gün geçmiş. Sıfır ve forward sürekli bileşik '
        + '(ACT/365). Hedge: paketi uyumun seviye ve eğim faktörlerine nötr yapan iki komşu vade (DV01 ağırlığı).';
      const cv = c.curve || {};
      this.draw('ois', this.oisChart, { scatter: true, title: 'TRY OIS', x_title: 'vade (yıl)', y_title: '%', decimals: 2, aspect: 0.3, auto: 'fit',
        series: [{ name: 'kota (par)', kind: 'line', color: BLUE, x: rows.map((r) => r.t), data: rows.map((r) => r.par), noline: true },
          { name: 'NSS par', kind: 'line', color: ORANGE, x: rows.map((r) => r.t), data: rows.map((r) => r.fit), marker: false },
          { name: 'NSS sıfır', kind: 'line', color: GREEN, x: cv.t || [], data: cv.zero || [], marker: false },
          { name: 'NSS forward', kind: 'line', color: PURPLE, dash: true, x: cv.t || [], data: cv.fwd || [], marker: false }] });
    }
    const d = this.data.dibsfv || {};
    if (!d.ok) {
      this.boxes.bonds.set([], [], null, d.why || 'DİBS için veri yok');
      this.boxes.best.set([], [], null, '—');
      this.draw('bonds', this.bondChart, { series: [] });
      return;
    }
    const rows = d.rows || [];
    this.boxes.bonds.set(['Kâğıt', 'Tip', 'Vade', 'Kupon %', 'Getiri %', 'Kural', 'Model %', 'Fark (bp)', 'z', 'Kesit z', 'Yarı ömür (g)', 'Gün',
      'OIS\'e göre (bp)', 'ASW (Excel)', 'P/U (Excel, bp)', 'Mod. süre', 'C 1H', 'R 1H', 'C 1A', 'R 1A', 'C+R 1A', 'σ 1A (bp)', 'C+R / σ', 'Puan',
      'Fonlama'],
    rows.map((r) => [T(r.label, { b: 1, tip: r.isin + (!r.fitted ? '\nuyum dışı (bono): eğriye göre ölçülür, eğriyi biçimlendirmez'
      : (r.weight < 1 ? '\nuyumda ağırlığı ' + fmt(r.weight, 2) + ' (uzak nokta)' : '')) }), T((KIND[r.kind] || r.kind) + (r.fitted ? '' : ' ·')),
      T(isoToTr(r.maturity)), N(r.coupon, 2), N(r.yield, 3, { tip: r.live ? 'canlı (DİBS RV)' : 'son kapanış' }), T(CONV[r.conv] || r.conv), N(r.model, 3),
      N(r.resid, 1, { sign: true, b: 1, cls: r.fitted && r.weight < 1 ? 'soft' : '' }), Z(r.z, entry), N(r.cs_z, 2, { sign: true, tip: 'Bugünkü farkların kesitine göre' }),
      N(r.half_life, 1), N(r.n, 0, { tip: 'Farkın geçmişi: uyumun kurulduğu gün sayısı (tarihçenin DİBS kapanışları)' }),
      N(r.ois_spread, 1, { sign: true }), N(r.wb_asw, 1, { sign: true }),
      N(r.wb_rc, 1, { sign: true, tip: 'DİBS RV\'nin kendi pahalı / ucuzu: ASW\'nin a + b·t + c·t² uyumuna göre (+ ucuz)' }), N(r.mod_dur, 2),
      N(r.carry_1w, 1, { sign: true }), N(r.roll_1w, 1, { sign: true }), N(r.carry_1m, 1, { sign: true }), N(r.roll_1m, 1, { sign: true }),
      N(r.total_1m, 1, { sign: true, b: 1 }), N(r.sigma_1m, 1), N(r.cpr, 2, { sign: true }), N(r.score, 2, { sign: true, b: 1 }), T(r.funding || '')]),
    rows.map((r) => r.sid || null), '—', this.picked);
    const f = d.funding || {};
    this.bonds.note.textContent = 'Sabit kuponlu kâğıtlar ve bonolar (TLREF, FRN ve TÜFE dışarıda), DİBS RV\'nin BIST kuralıyla (kupon c/f, 364/f günde bir; '
      + 'getiri yılda f kez bileşik, bono basit). Eğri sabit kuponlulara uydurulur (sayfanın kendi ASW uyumu gibi); bonolar (·) ona göre ölçülür, '
      + 'eğriyi biçimlendirmez. Fark = getiri − model fiyatın getirisi (bp, kâğıdın kendi kuralıyla): + ucuz (al), − pahalı (sat); '
      + 'uzaktaki bir kâğıt uyumda ağırlıksızlaşır (Huber), komşularını bükmesin. OIS\'e göre: aynı nakit akışları OIS uyumuyla - getiri farkı (bp); '
      + 'yanında DİBS RV\'nin kendi ASW\'si ve pahalı / ucuzu (ASW\'nin karesel uyumuna göre). '
      + 'Carry (C) ve roll (R), bp (÷ DV01): C = getiri sabitken fiyat + ödenen kupon − fonlanan kirli fiyat; R = eğri yerinde kalırken (kâğıdın '
      + 'eğriye göre farkı sabit) − getiri sabitken fiyat. Fonlama: satırın reposu, yoksa OIS uyumunun vadeye kadarki faizi ('
      + (f.source || '—') + (isNum(f.rate_1m) ? ', 1A ' + fmt(f.rate_1m, 2) + '% sürekli' : '') + '), yoksa TLREF. ' + params(d.params) + ' · RMSE '
      + fmt(d.rmse, 1) + ' bp, ' + d.n + ' kâğıt, ' + (d.days || 0) + ' gün geçmiş.';
    const pick = ['Yön', 'Kâğıt', 'Vade', 'Fark (bp)', 'z', 'C+R 1A (bp)', 'σ 1A (bp)', 'C+R / σ', 'Puan'];
    const best = (side, list) => list.map((r) => [T(side, { b: 1 }), T(r.label, { b: 1 }), T(isoToTr(r.maturity)), N(r.resid, 1, { sign: true }), Z(r.z, entry),
      N(r.total_1m, 1, { sign: true }), N(r.sigma_1m, 1), N(r.cpr, 2, { sign: true }), N(r.score, 2, { sign: true, b: 1 })]);
    const rec = d.receive || [], pay = d.pay || [];
    this.boxes.best.set(pick, best('Receive (al)', rec).concat(best('Pay (sat)', pay)), rec.concat(pay).map((r) => r.sid || null),
      'Sıralama için kâğıtların z\'si ve oynaklığı gerekli (tarihçede en az ' + ((this.data.settings || {}).min_obs || 120) + ' gün)', this.picked);
    const bySpan = rows.slice().sort((a, b) => a.years - b.years);
    this.draw('bonds', this.bondChart, { scatter: true, title: 'DİBS', x_title: 'vade (yıl)', y_title: '%', decimals: 2, aspect: 0.3, auto: 'fit',
      series: [{ name: 'getiri', kind: 'line', color: BLUE, x: bySpan.map((r) => r.years), data: bySpan.map((r) => r.yield), noline: true, labels: bySpan.map((r) => r.label) },
        { name: 'NSS model', kind: 'line', color: ORANGE, x: bySpan.map((r) => r.years), data: bySpan.map((r) => r.model), marker: false },
        { name: 'OIS uyumuyla', kind: 'line', color: GREY, dash: true, x: bySpan.map((r) => r.years), data: bySpan.map((r) => r.ois_yield), marker: false }] });
  }
}

// ------------------------------------------------------------------------------------------------ Opsiyon
/** A number cell that shows "—" without a value (a row of bold labels alone would read as a header row). */
const V = (v, d, opts = {}) => N(v, d, Object.assign({ empty: '—' }, opts));

const QUOTES = [['ATM', 'ATM'], ['RR25', '25D RR'], ['BF25', '25D BF'], ['RR10', '10D RR'], ['BF10', '10D BF']];

class OptPage extends FitPage {
  constructor(host, ctx) { super(host, ctx, 'opt'); this.charts = {}; }

  build() {
    this.surface = panel('quant-opt-surface', 'Vol yüzeyi · ATM, 25D / 10D risk reversal ve butterfly (vol puanı)');
    this.surface.note.textContent = 'Canlı değer (yoksa son kapanış) ve z\'si (tahmin penceresine göre). RR / ATM ve BF / ATM, seviyenin ATM vol\'ün kendi '
      + 'hareketinden gelen kısmını ayırır. Sinyaller: 25D RR (skew) ve 25D / 10D BF (kanatlar) - + z pahalı (sat), − z ucuz (al).';
    this.boxes.surface = new GridBox(this.surface, 'quant/opt/surface', (sid) => this.pick(sid));
    this.tsChart = h('div', { class: 'volchart' });
    this.ts = panel('quant-opt-ts', 'ATM vade yapısı', { top: this.tsChart });
    this.ts.note.textContent = 'Eğim = uzun vade ATM vol − kısa vade (vol puanı); 1Y − 1M\'nin z\'si sinyaldir: + ise eğim pahalı (1Y sat / 1M al).';
    this.boxes.ts = new GridBox(this.ts, 'quant/opt/ts', (sid) => this.pick(sid));
    this.probs = panel('quant-opt-probs', 'Smile\'ın ima ettiği dağılım · forward\'a göre ±X% olasılığı ve gerçekleşen sıklık');
    this.probs.note.textContent = 'Hareketler forward\'dan ölçülür (carry dahil: USDTRY\'nin forward\'ı spotun epey üstündedir). İma: SVI smile\'ından '
      + 'Breeden-Litzenberger, P(S > F·(1+X)) ve P(S < F·(1−X)) (forward ölçüsü). Gerçekleşen: tarihçedeki her gün o vadenin forward\'ı ve vade sonraki spot - '
      + 'S/F − 1\'in X\'i aştığı günlerin payı; pencereler çakışır, n gün ≈ n ÷ vadedeki iş günü bağımsız gözlem (± standart hata ondan). '
      + 'Fark + ise opsiyonlar o kuyruğu geçmişe göre pahalı fiyatlıyor.';
    this.boxes.probs = new GridBox(this.probs, 'quant/opt/probs');
    this.smile = panel('quant-opt-smile', 'Smile uyumu ve dağılımın yüzdelikleri', { cls: 'aux' });
    this.smile.note.textContent = 'SVI (Gatheral) beş kotaya, paritenin delta kuralıyla (USDTRY primli forward delta, EURUSD spot delta); kelebek ve kanat '
      + 'koşulları ceza olarak - yoğunluk hiç eksiye düşmez. Artıklar vol puanı (kotalar kendi aralarında tutarsızsa en yakın arbitrajsız smile). '
      + 'Yüzdelikler forward\'a göre %. Gerçekleşen ort.: S/F − 1\'in ortalaması (forward\'ın sapması, carry getirisi).';
    this.boxes.smile = new GridBox(this.smile, 'quant/opt/smile');
    this.frame('Opsiyon', [this.surface, this.ts, this.probs, this.smile]);
  }

  fillPage() {
    const o = this.data.opt || {};
    const entry = (this.data.settings || {}).entry_z || 2;
    const pairs = o.pairs || [];
    if (!o.ok) {
      for (const b of ['surface', 'ts', 'probs', 'smile']) this.boxes[b].set([], [], null, o.why || 'Vol verisi yok');
      return;
    }
    const sRows = [], sKeys = [];
    for (const p of pairs) {
      for (const r of p.surface || []) {
        const row = [T(p.pair, { b: 1 }), T(r.tenor, { b: 1 })];
        for (const [k] of QUOTES) {
          row.push(V(r[k], 2, { tip: r[k + '_live'] ? 'canlı' : (isNum(r[k]) ? 'son kapanış' : '') }), Z(r[k + '_z'], entry));
          if (k !== 'ATM') row.push(V(r[k + '_atm'], 2, { tip: k + ' / ATM' }));
        }
        sRows.push(row);
        sKeys.push(r.RR25_sid || r.BF25_sid || r.BF10_sid || null);
      }
    }
    const head = ['Parite', 'Vade'];
    for (const [k, label] of QUOTES) {
      head.push(label, 'z');
      if (k !== 'ATM') head.push(label + ' / ATM');
    }
    this.boxes.surface.set(head, sRows, sKeys, 'Vol kotası yok (yeni seriler canlıda tarihçeyle iki yıl geriye dolar)', this.picked);
    const tRows = [], tKeys = [];
    for (const p of pairs) {
      for (const s of p.slopes || []) {
        tRows.push([T(p.pair, { b: 1 }), T(s.name, { b: 1 }), V(s.value, 2, { sign: true }), Z(s.z, entry), V(s.half_life, 1), T(s.sid ? 'sinyal' : '')]);
        tKeys.push(s.sid || null);
      }
    }
    this.boxes.ts.set(['Parite', 'Eğim', 'Vol puanı', 'z', 'Yarı ömür (g)', ''], tRows, tKeys, 'ATM vol yok', this.picked);
    const tenors = ['1W', '1M', '3M', '6M', '1Y'];
    const colors = [BLUE, ORANGE, GREEN, PURPLE];
    this.draw('ts', this.tsChart, { title: 'ATM vol', cats: tenors, auto: 'fit', decimals: 2, y_title: 'vol', aspect: 0.25,
      series: pairs.map((p, i) => ({ name: p.pair, kind: 'line', color: colors[i % colors.length], marker: true,
        data: tenors.map((t) => ((p.surface || []).find((r) => r.tenor === t) || {}).ATM) })) });
    const pRows = [], mRows = [];
    for (const p of pairs) {
      for (const s of p.smiles || []) {
        const rl = s.realized || {};
        for (const pr of s.probs || []) {
          const se = (v) => (isNum(v) ? '± ' + pct(v, 1) : '');
          pRows.push([T(p.pair, { b: 1 }), T(s.tenor, { b: 1 }), V(s.F, 4), V(s.fwd_pct, 2, { sign: true, unit: '%' }), T('±' + fmt(pr.x, 0) + '%', { b: 1 }),
            { t: pct(pr.up, 1), v: pr.up, k: isNum(pr.up) ? 'n' : '', b: 1 }, { t: pct(pr.up_real, 1), v: pr.up_real, k: isNum(pr.up_real) ? 'n' : '', tip: se(pr.up_se) },
            V(isNum(pr.up) && isNum(pr.up_real) ? (pr.up - pr.up_real) * 100 : null, 1, { sign: true }),
            { t: pct(pr.down, 1), v: pr.down, k: isNum(pr.down) ? 'n' : '', b: 1 }, { t: pct(pr.down_real, 1), v: pr.down_real, k: isNum(pr.down_real) ? 'n' : '', tip: se(pr.down_se) },
            V(isNum(pr.down) && isNum(pr.down_real) ? (pr.down - pr.down_real) * 100 : null, 1, { sign: true }),
            T(isNum(rl.n) ? rl.n + ' (' + fmt(rl.n_eff, 0) + ')' : ''), T(s.why || '', { cls: 'soft' })]);
        }
        const fit = s.fit || {};
        const q = s.q || {};
        mRows.push([T(p.pair, { b: 1 }), T(s.tenor, { b: 1 }), T(s.model || (s.why || '—')), T(s.delta || ''), V(fit.ATM, 2, { sign: true }), V(fit.RR25, 2, { sign: true }),
          V(fit.BF25, 2, { sign: true }), V(fit.RR10, 2, { sign: true }), V(fit.BF10, 2, { sign: true }), T(s.arbitrage === true ? 'var' : (s.arbitrage === false ? 'yok' : '')),
          V(q['0.05'], 2, { sign: true }), V(q['0.25'], 2, { sign: true }), V(q['0.5'], 2, { sign: true }), V(q['0.75'], 2, { sign: true }), V(q['0.95'], 2, { sign: true }),
          V(rl.mean, 2, { sign: true, unit: '%' }), V(rl.sd, 2, { unit: '%' })]);
      }
    }
    this.boxes.probs.set(['Parite', 'Vade', 'Forward', 'Fwd − spot', 'Hareket', 'İma ↑', 'Gerçekleşen ↑', 'Fark ↑ (puan)', 'İma ↓', 'Gerçekleşen ↓',
      'Fark ↓ (puan)', 'Gün (bağımsız)', ''], pRows, null, 'Forward ve vol kotası yok', this.picked);
    this.boxes.smile.set(['Parite', 'Vade', 'Model', 'Delta', 'ATM art.', '25RR art.', '25BF art.', '10RR art.', '10BF art.', 'Arbitraj', '%5', '%25', '%50', '%75', '%95',
      'Gerçekleşen ort.', 'Gerçekleşen σ'], mRows, null, 'Smile yok', this.picked);
  }
}

const FIT_PAGES = { 'quant-curve': CurvePage, 'quant-opt': OptPage };

/** The page of ``id`` when it is one of this module's (else null: the caller's own). */
export function fitPage(id, host, ctx) {
  const P = FIT_PAGES[id];
  return P ? new P(host, ctx) : null;
}
