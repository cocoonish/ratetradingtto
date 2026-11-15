// Öncü-Takipçi (tto/quantlead.py): who moves first - offshore or onshore OIS, the USDTRY swap points or OIS, VİOP or
// OIS, USDTRY / EURTRY or the OIS front end, the 1Y or the 2Y / 5Y.  The scan (leader, follower, lag, β, Granger F, R²,
// stability, how the rule went before), the cross-correlations at lags −5 … +5, the followers that have not caught up
// (signals), and the same scan on intraday bars when the dashboard has them.  Computed in the quant worker's thread.
import { h } from '../ui.js';
import { QuantPage, GridBox, SignalChart, panel, signalRows, SIGNAL_HEAD, T, N, Z, heatHex, fmt, pct, isNum } from './quantbase.js';

const pval = (p) => (isNum(p) ? (p < 0.001 ? '<0,001' : fmt(p, 3)) : '');

class LeadPage extends QuantPage {
  constructor(host, ctx) { super(host, ctx, 'lead'); }

  build() {
    this.tools([]);
    const page = h('div', { class: 'volpage quantpage' });
    const sp = panel('quant-lead-signals', 'Öncü-Takipçi · sinyaller');
    sp.note.textContent = 'Lider son ℓ + 1 günde en az k σ oynadı, takipçi henüz yetişmedi: beklenen yetişme = β × liderin hareketi − takipçinin aynı günlerdeki '
      + 'hareketi; z = yetişme ÷ σ (β\'nın hatası ve takipçinin kendi gürültüsü). Giriş takipçinin şimdiki seviyesi, hedef yetişme, stop bir σ. Tez notta.';
    this.boxes.sig = new GridBox(sp, 'quant/lead/signals', (sid) => this.pick(sid));
    const cp = panel('quant-lead-chart', 'Seçili seri');
    this.chart = new SignalChart(cp.body);
    this.scan = panel('quant-lead-pairs', 'Öncü-takipçi taraması · günlük değişimler');
    this.scan.note.textContent = 'Değişimler: faizlerde bp, kurlarda % (log), swap puanında puan; ikisinin de kapanışı olan günler. Kim önde: '
      + 'çapraz korelasyonların asimetrisi, z = (r(+l) − r(−l)) ÷ √(2 ÷ n), bakılan gecikmeler üzerinden %5 (Bonferroni) - yalnızca ortak hareketi '
      + 'paylaşan iki seride iki yön aynıdır; liderin Granger testi de (takipçi kendi gecikmeleriyle, liderinkiler eklenince F) p < %5 olmalı. β: '
      + 'takipçinin ℓ gün içindeki toplam tepkisi (Σ b₀ … b_ℓ). Kararlılık: ℓ\'deki asimetri son 60 / 120 / 250 günde aynı işaret ve |z| ≥ 2 - her '
      + 'pencerede tutmayan öncülüğün sinyali elenir. Olay / isabet: liderin k σ hareketlerinden sonra takipçinin beklenen yöne gitme oranı ve '
      + 'beklenenin gelen kısmı (örneklem içi).';
    this.boxes.scan = new GridBox(this.scan, 'quant/lead/pairs', (sid) => this.pick(sid));
    this.xc = panel('quant-lead-xcorr', 'Çapraz korelasyonlar · x_t ile y_t+k', { cls: 'aux' });
    this.xc.note.textContent = 'k > 0: x (soldaki) önde; k < 0: y önde; k = 0 aynı gün. Liderin seçilen gecikmesi kalın.';
    this.boxes.xc = new GridBox(this.xc, 'quant/lead/xcorr');
    this.bars = panel('quant-lead-intraday', 'Gün içi · 1 ve 5 dakikalık barlar');
    this.bars.note.textContent = 'Aynı analiz canlı akışın dakikalık barlarında (gecikmeler bar cinsinden).';
    this.boxes.bars = new GridBox(this.bars, 'quant/lead/intraday');
    page.append(sp.el, cp.el, this.scan.el, this.xc.el, this.bars.el);
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
    this.boxes.sig.set(SIGNAL_HEAD.concat(['Bileşik / neden', 'Saat']), list.map((s) => {
      const row = signalRows([s], { gated: !!s.gated })[0];
      if (s.gated) for (const c of row) if (c && typeof c === 'object') c.cls = ((c.cls || '') + ' soft').trim();
      return row;
    }), list.map((s) => s.id), 'Şu an yetişmemiş takipçi yok (liderin en az k σ hareketi ve |z| ≥ giriş gerekli).', this.picked);
  }

  fillPage() {
    const d = this.data.lead || {};
    const entry = (this.data.settings || {}).entry_z || 2;
    const rows = d.rows || [];
    this.scan.setTitle('Öncü-takipçi taraması · günlük değişimler · ' + rows.length + ' çift · k ' + fmt(d.k, 1) + ' σ · en çok ' + (d.lags || 5) + ' gün');
    this.boxes.scan.set(['Grup', 'Çift', 'Lider → takipçi', 'Gecikme (g)', 'Asimetri z', 'β', '± se', 't', 'Granger F (p)', 'R²', 'Kararlılık', 'Olay', 'İsabet',
      'Gelen / beklenen', 'Lider hareketi (σ)', 'Beklenen yetişme', 'z', 'Gün', 'Not'], rows.map((r) => {
      const lead = !!r.leader;
      const ev = r.events || {};
      const now = r.now || {};
      return [T(r.group), T(r.x_label + ' ↔ ' + r.y_label), T(lead ? r.leader_label + ' → ' + r.follower_label : '—', { b: lead ? 1 : 0 }), lead ? N(r.lag, 0) : T('—'),
        N(r.asym_z, 2, { sign: true }), N(r.beta, 3, { sign: true }), N(r.se, 3), N(r.t, 1, { sign: true }), T(lead ? fmt(r.F, 1) + ' (' + pval(r.p) + ')' : ''), N(r.r2, 2), T(r.stable || ''),
        N(ev.n, 0), T(isNum(ev.hit_rate) ? pct(ev.hit_rate) : ''), T(isNum(ev.ratio) ? pct(ev.ratio) : ''),
        N(now.k_moved, 1, { sign: true, cls: r.event ? 'thru' : '' }), N(now.catch_up, 1, { sign: true }), Z(r.z, entry), N(r.n, 0), T(r.why || '', { cls: 'soft' })];
    }), rows.map((r) => r.sid || null), d.why || 'Aday çift yok', this.picked);
    const lags = [];
    for (let k = -(d.lags || 5); k <= (d.lags || 5); k++) lags.push(k);
    this.boxes.xc.set(['x', 'y'].concat(lags.map((k) => ({ t: (k > 0 ? '+' : '') + k, k: 's', b: 1, f: 'hd' }))), rows.filter((r) => r.xcorr).map((r) => {
      const chosen = r.leader ? (r.leader === r.x ? r.lag : -r.lag) : null;
      return [T(r.x_label, { b: 1 }), T(r.y_label)].concat(lags.map((k) => {
        const v = (r.xcorr || {})[String(k)];
        return isNum(v) ? { t: fmt(v, 2), v, k: 'n', heat: heatHex(v) || undefined, b: k === chosen ? 1 : 0 } : { t: '', k: '' };
      }));
    }), null, 'Çapraz korelasyon için geçmiş yok');
    const bars = d.intraday || {};
    if (!bars.ok) {
      this.boxes.bars.set([], [], null, bars.why || 'gün içi barlar yok');
    } else {
      this.boxes.bars.set(['Bar (dk)', 'x', 'y', 'Lider', 'Gecikme (bar)', 'β', 't', 'Granger F (p)', 'R²', 'Kararlılık', 'Bar', 'Not'], (bars.rows || []).map((r) => [
        N(r.minutes, 0), T(r.x), T(r.y), T(r.leader || '—', { b: 1 }), N(r.lag, 0), N(r.beta, 3, { sign: true }), N(r.t, 1, { sign: true }),
        T(isNum(r.F) ? fmt(r.F, 1) + ' (' + pval(r.p) + ')' : ''), N(r.r2, 2), T(r.stable || ''), N(r.n, 0), T(r.why || '', { cls: 'soft' })]),
      null, 'Barlarda aday çift yok');
    }
  }
}

/** The pages of this module by id (quant.js asks here first). */
export const LEAD_PAGES = { 'quant-lead': LeadPage };
