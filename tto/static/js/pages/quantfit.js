// The fitted-model pages of the quant package (tto/quantcurve.py, tto/quantopt.py): Eğri Adil Değeri - the
// Nelson-Siegel-Svensson fits of the TRY OIS curve and of DİBS, each point's rich / cheap with its z, the bonds' carry
// + roll and the best bond to receive / pay with - and Opsiyon - the USDTRY / EURUSD vol surface (ATM term structure,
// 25D / 10D risk reversals and butterflies), its signals, the smile's distribution against the forward next to how
// often the spot ended that far from it.  Each lists its own signals at the top and draws a picked row's series below
// them, like the analysis pages of quantviews.js.
import { api } from '../api.js';
import { h, clear, copyText, errorToast, toast } from '../ui.js';
import { Chart } from '../chart.js';
import { isoToTr } from '../format.js';
import { QuantPage, GridBox, SignalChart, panel, signalRows, SIGNAL_HEAD, T, N, Z, fmt, sgn, pct, isNum, REGIME, pref, keep,
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
    this.quotes = new BondQuote(this);
    this.frame('Eğri Adil Değeri', [this.ois, this.bonds, this.best, this.quotes.quote, this.quotes.sw]);
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
    this.quotes.fill(d);
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

// ------------------------------------------------------------------------------------------------ quotes from the fair curve
const QUOTE_PREF = 'tto.quant.quote.isin', SWITCH_PREF = 'tto.quant.switch';
const SPREADS = [['short_until', 'kısa ≤', 'yıl'], ['short', '', 'bp'], ['mid', '· orta', 'bp'], ['long_from', '· uzun ≥', 'yıl'], ['long', '', 'bp']];

/**
 * Two sections of Eğri Adil Değeri: a two-way quote of any fixed-coupon DİBS from the fair curve (the NSS fair yield
 * and price ± the desk's half spread of the bond's maturity bucket, the market next to it) and a switch A → B (sell A,
 * buy B, DV01-neutral: the pickup against the curve, the carry + roll difference, the z of the switch).  The numbers
 * are the server's (/api/quant/quote, /api/quant/switch) on the latest fit; "Kopyala" copies the line to send.
 */
class BondQuote {
  constructor(page) {
    this.page = page;
    this.isin = pref(QUOTE_PREF, '');
    [this.a, this.b] = (pref(SWITCH_PREF, '') + '|').split('|');
    this.listed = '';
    // the quote
    this.bondSel = h('select', { class: 'inp', id: 'quant-quote-bond', title: 'DİBS RV listesindeki sabit kuponlu kâğıtlar' });
    this.typed = h('input', { class: 'inp', id: 'quant-quote-isin', placeholder: 'ya da ISIN', style: { width: '140px' },
      title: 'Listede olmayan bir sabit kuponlu DİBS (kataloğun kuponu ve vadesiyle)' });
    const go = h('button', { class: 'btn', type: 'button', id: 'quant-quote-go' }, 'Kotasyon');
    this.copyQuote = h('button', { class: 'btn primary', type: 'button', id: 'quant-quote-copy', title: 'Kotasyonu tek satır mesaj olarak kopyala' }, 'Kopyala');
    this.inputs = {};
    const fields = [h('span', { class: 'muted' }, 'Yarım spread:')];
    for (const [k, before, unit] of SPREADS) {
      const inp = h('input', { class: 'inp num', id: 'quant-quote-' + k, style: { width: '52px' } });
      this.inputs[k] = inp;
      fields.push(h('span', { class: 'muted' }, before), inp, h('span', { class: 'muted' }, unit));
    }
    const save = h('button', { class: 'btn', type: 'button', id: 'quant-quote-save', title: 'Masanın ortak ayarı: herkesin kotasyonunu değiştirir' }, 'Kaydet');
    this.quoteBar = h('div', { class: 'qform' }, this.bondSel, this.typed, go, h('span', { class: 'grow' }), ...fields, save, this.copyQuote);
    this.quote = panel('quant-curve-quote', 'Adil eğriden kotasyon', { top: this.quoteBar });
    this.quoteBox = new GridBox(this.quote, 'quant/curve/quote');
    // the switch
    this.aSel = h('select', { class: 'inp', id: 'quant-switch-a', title: 'Satılan kâğıt (A)' });
    this.bSel = h('select', { class: 'inp', id: 'quant-switch-b', title: 'Alınan kâğıt (B)' });
    this.copySwitch = h('button', { class: 'btn primary', type: 'button', id: 'quant-switch-copy', title: 'Switch\'i tek satır mesaj olarak kopyala' }, 'Kopyala');
    this.swBar = h('div', { class: 'qform' }, h('span', { class: 'muted' }, 'Sat (A)'), this.aSel, h('span', { class: 'muted' }, '→ al (B)'), this.bSel,
      h('span', { class: 'grow' }), this.copySwitch);
    this.sw = panel('quant-curve-switch', 'Switch · A sat / B al (DV01 nötr)', { top: this.swBar });
    this.swBox = new GridBox(this.sw, 'quant/curve/switch');
    // events
    this.bondSel.addEventListener('change', () => { this.typed.value = ''; this.isin = this.bondSel.value; keep(QUOTE_PREF, this.isin); this.loadQuote(); });
    const typed = () => { const v = this.typed.value.trim().toUpperCase(); if (v) { this.isin = v; keep(QUOTE_PREF, v); this.loadQuote(); } };
    go.addEventListener('click', typed);
    this.typed.addEventListener('keydown', (e) => { if (e.key === 'Enter') typed(); });
    save.addEventListener('click', () => this.saveSpreads());
    this.copyQuote.addEventListener('click', () => { if (this.quoteLine) copyText(this.quoteLine, 'Kotasyon kopyalandı'); });
    const swChanged = () => { this.a = this.aSel.value; this.b = this.bSel.value; keep(SWITCH_PREF, this.a + '|' + this.b); this.loadSwitch(); };
    this.aSel.addEventListener('change', swChanged);
    this.bSel.addEventListener('change', swChanged);
    this.copySwitch.addEventListener('click', () => { if (this.switchLine) copyText(this.switchLine, 'Switch kopyalandı'); });
    this.loadSpreads().catch(() => {});
  }

  /** The page's data moved: the lists of bonds, then the quote and the switch again (live values). */
  fill(d) {
    const rows = ((d && d.rows) || []).filter((r) => r.kind === 'fixed');
    const key = rows.map((r) => r.isin).join(',');
    if (key !== this.listed) {
      this.listed = key;
      for (const sel of [this.bondSel, this.aSel, this.bSel]) {
        clear(sel);
        for (const r of rows) sel.appendChild(h('option', { value: r.isin }, r.label + ' · ' + r.isin));
      }
      const has = (isin) => rows.some((r) => r.isin === isin);
      if (!this.isin && rows.length) this.isin = rows[Math.floor(rows.length / 2)].isin;
      if (!has(this.a) && rows.length) this.a = rows[0].isin;
      if (!has(this.b) && rows.length) this.b = rows[rows.length - 1].isin;
    }
    if (has2(rows, this.isin)) { this.bondSel.value = this.isin; this.typed.value = ''; } else if (this.isin) this.typed.value = this.isin;
    this.aSel.value = this.a;
    this.bSel.value = this.b;
    if (this.isin) this.loadQuote();
    if (this.a && this.b) this.loadSwitch();
  }

  async loadSpreads() {
    const d = await api.get('/api/quant/quote_spreads');
    for (const [k, inp] of Object.entries(this.inputs)) inp.value = isNum(d.values[k]) ? fmt(d.values[k], 1) : '';
    this.spreadNote = d.values.by ? 'Son değiştiren: ' + this.page.ctx.displayName(d.values.by) + ' (' + d.values.at + ').' : '';
  }

  async saveSpreads() {
    const values = {};
    for (const [k, inp] of Object.entries(this.inputs)) values[k] = inp.value;
    try {
      await api.post('/api/quant/quote_spreads', { values });
      toast('Yarım spread\'ler kaydedildi (masanın ortak ayarı)', 'ok', 2500);
      await this.loadSpreads();
      this.loadQuote();
      this.loadSwitch();
    } catch (e) { errorToast(e); }
  }

  async loadQuote() {
    const isin = this.isin;
    if (!isin) return;
    let q;
    try {
      q = await api.get('/api/quant/quote', { isin });
    } catch (e) { if (!e.network) errorToast(e); return; }
    if (this.page.dead || isin !== this.isin) return;
    this.quoteLine = q.ok ? q.line : '';
    this.copyQuote.disabled = !q.ok;
    if (!q.ok) {
      this.quoteBox.set([], [], null, q.why || 'Kotasyon yok');
      this.quote.note.textContent = '';
      return;
    }
    const row = (name, x, b) => [T(name, { b: 1 }), N(x.yield, 3, { b }), N(x.compound, 3), N(x.clean, 3, { b }), N(x.dirty, 3), N(x.dv01, 1)];
    const rows = [row('Alış (bid)', q.bid, 1), row('Adil (NSS)', q.fair, 0), row('Satış (ask)', q.ask, 1)];
    if (q.market) rows.push(row('Piyasa' + (q.market.live ? ' (canlı)' : ' (son kapanış)'), q.market, 0));
    this.quoteBox.set(['', 'Getiri % (basit)', 'Bileşik %', 'Temiz', 'Kirli', 'DV01 (TL / bp, 1mn)'], rows, null, '—');
    this.quote.setTitle('Adil eğriden kotasyon · ' + q.label + ' (' + q.isin + ')');
    this.quote.note.textContent = 'Valör ' + isoToTr(q.value_date) + ' · işlemiş faiz ' + fmt(q.accrued, 4) + ' · kupon %' + fmt(q.coupon, 2) + ' · '
      + fmt(q.years, 2) + ' yıl, ' + q.bucket + ' vade: yarım spread ' + fmt(q.half_bp, 1) + ' bp (alış = adil + yarım, satış = adil − yarım; basit getiri, '
      + 'BIST kuralı). ' + (isNum(q.distance) ? 'Piyasa adilden ' + sgn(q.distance, 1) + ' bp' + (isNum(q.z) ? ' (z ' + sgn(q.z, 2) + ')' : '') + ' · ' : '')
      + (isNum(q.total_1m) ? 'carry + roll ayda ' + sgn(q.total_1m, 1) + ' bp · ' : '') + (q.listed ? '' : 'listede değil: kataloğun kuponu ve vadesiyle · ')
      + (this.spreadNote || '');
  }

  async loadSwitch() {
    const a = this.a, b = this.b;
    if (!a || !b) return;
    let s;
    try {
      s = await api.get('/api/quant/switch', { a, b });
    } catch (e) { if (!e.network) errorToast(e); return; }
    if (this.page.dead || a !== this.a || b !== this.b) return;
    this.switchLine = s.ok ? s.line : '';
    this.copySwitch.disabled = !s.ok;
    if (!s.ok) {
      this.swBox.set([], [], null, s.why || 'Switch yok');
      this.sw.note.textContent = '';
      return;
    }
    const entry = (this.page.data.settings || {}).entry_z || 2;
    const leg = (name, x, nominal) => [T(name, { b: 1 }), T(x.label, { b: 1, tip: x.isin }), N(nominal, 2), N(x.market ? x.market.yield : null, 3), N(x.fair.yield, 3),
      N(x.distance, 1, { sign: true }), Z(x.z, entry), N(x.total_1w, 1, { sign: true }), N(x.total_1m, 1, { sign: true }), N((x.market || x.fair).dv01, 1)];
    const rows = [leg('Sat (A)', s.a, 1), leg('Al (B)', s.b, s.ratio),
      [T('Switch (B − A)', { b: 1 }), T(''), T(''), N(s.level, 1, { sign: true, unit: 'bp', tip: 'Piyasa getiri farkı' }), T(''),
        N(s.pickup, 1, { sign: true, b: 1, tip: 'B\'nin adil eğriye göre farkı − A\'nınki: + ise B daha ucuz' }), Z(s.z, entry, { tip: 'Bu farkın geçmişine göre' }),
        N(s.cr_1w, 1, { sign: true }), N(s.cr_1m, 1, { sign: true, b: 1 }), T('')]];
    this.swBox.set(['', 'Kâğıt', 'Nominal (mn)', 'Getiri %', 'Adil %', 'Eğriye göre (bp)', 'z', 'C+R 1H (bp)', 'C+R 1A (bp)', 'DV01 (TL / bp, 1mn)'], rows, null, '—');
    this.sw.note.textContent = s.line + ' · Nominal: 1mn A için B (aynı DV01). Eğriye göre fark ve carry + roll bp (÷ DV01); z: B − A eğri farkının '
      + (isNum(s.n) ? 'son ' + s.n + ' günlük geçmişine göre' + (isNum(s.half_life) ? ', yarı ömür ' + fmt(s.half_life, 1) + ' gün' : '') : 'geçmişi yok') + '.';
  }
}

const has2 = (rows, isin) => rows.some((r) => r.isin === isin);

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
