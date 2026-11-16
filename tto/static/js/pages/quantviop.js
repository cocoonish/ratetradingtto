// VİOP (tto/quantviop.py): Borsa İstanbul's USDTRY futures against spot - the TRY rate each contract implies (at the
// bid, the ask and the mid), its spread over the OIS of the same days and over offshore, its fair rate and the signal
// (Buy VİOP / Sell spot when the rate is below its normal spread, the other way above), the order levels for today
// and for the week with the probability that each is reached (and the futures price it stands for), the calendar
// (month and quarter ends, weekdays, the days to expiry), the intraday profile of the 5-minute bars, how the levels
// held on the history.  Computed in the quant worker's thread; the levels with the values now when the page reads.
import { h } from '../ui.js';
import { QuantPage, GridBox, SignalChart, panel, signalRows, SIGNAL_HEAD, T, N, Z, seg, pref, keep, fmt, sgn, pct, isNum } from './quantbase.js';

const PICK_PREF = 'tto.quant.viop.contract';
const DAYS_TR = ['Pzt', 'Sal', 'Çar', 'Per', 'Cum'];
const hm = (m) => String(Math.floor(m / 60)).padStart(2, '0') + ':' + String(m % 60).padStart(2, '0');
const kname = (k) => (k === 0 ? 'ay sonu' : (k < 0 ? 'ay sonu ' + k : 'ay başı +' + k));

class ViopPage extends QuantPage {
  constructor(host, ctx) {
    super(host, ctx, 'viop');
    this.contract = pref(PICK_PREF, '');
  }

  build() {
    this.contractHost = h('span', { class: 'qtools' });
    this.tools([h('span', { class: 'muted' }, 'Kontrat'), this.contractHost]);
    this.modeNote = h('div', { class: 'banner hidden', id: 'quant-viop-mode' });
    this.host.appendChild(this.modeNote);
    const page = h('div', { class: 'volpage quantpage' });
    const sp = panel('quant-viop-signals', 'VİOP · sinyaller');
    sp.note.textContent = 'Kontratın ima TRY faizinin aynı vadenin OIS\'ine farkı, sabit vadeli geçmişteki normaline göre: farkı normalin altındaysa ima '
      + 'faiz ucuz - vadeli al, spot sat (Buy VİOP / Sell spot); üstündeyse tersi. Bacaklar ana bacağın DV01\'iyle (Ayarlar: 1.000 $), kontrat 1.000 $.';
    this.boxes.sig = new GridBox(sp, 'quant/viop/signals', (sid) => this.pick(sid));
    const cp = panel('quant-viop-chart', 'Seçili seri');
    this.chart = new SignalChart(cp.body);
    this.table = panel('quant-viop-contracts', 'Kontratlar · canlı');
    this.table.note.textContent = 'İma TRY % = ((fiyat / spot) · (1 + USD · g/360) − 1) · 360/g, g valörden vadeye gün (VİOP sayfasının formülü). Alış = ask '
      + 'fiyatının, satış = bid fiyatının ima faizi. OIS 360 günlük (VİOP sayfasının satır 77\'si gibi), offshore olduğu gibi (ICAP). Adil = OIS + farkın '
      + 'penceredeki ortalaması (sabit vadeli seriden, kontratın gününde). 1.000 $ DV01: ima faizin 1 bp\'si 1.000 $ olan pozisyon.';
    this.boxes.table = new GridBox(this.table, 'quant/viop/contracts', (sid) => this.pick(sid));
    this.levels = panel('quant-viop-levels', 'Emir seviyeleri');
    this.levels.note.textContent = 'Bugün (kalan seans) ve bu hafta (Cuma kapanışına kadar): alış emri ask ima faizinin en düşük noktasına, satış emri bid ima '
      + 'faizinin en yüksek noktasına göre - o seviyenin görülme olasılığı. Model: sürüklenmeli Brown hareketi (yansıma ilkesi); sürüklenme adil değere çekilme '
      + '(yarı ömürle), vadeye doğru kayma ve geçmişte belirgin ay sonu etkisi; varyans gün içi barların saat profili (geçmişin günlük oynaklığına ölçekli), '
      + 'geçmişte tutturma kalibrasyonuyla (c × σ). Fiyat: o ima faizin şimdiki spot ve USD faiziyle vadeli fiyatı.';
    this.levelsBody = h('div', { class: 'qcols' });
    this.levels.body.appendChild(this.levelsBody);
    this.cal = panel('quant-viop-calendar', 'Takvim etkileri · VİOP − OIS farkının günlük değişimi (1 aylık sabit vade)', { cls: 'aux' });
    this.cal.note.textContent = 'Ay sonuna kalan iş günü (0 = ayın son iş günü, + = yeni ayın ilk günleri) ve haftanın günü: ortalama değişim (bp), t, gün sayısı. '
      + '|t| ≥ 2 olan ay sonu etkileri seviye tahmininin sürüklenmesine girer.';
    this.boxes.cal = new GridBox(this.cal, 'quant/viop/calendar');
    this.expiry = panel('quant-viop-expiry', 'Vadeye yakınlık · ima faizin günlük oynaklığı', { cls: 'aux' });
    this.boxes.expiry = new GridBox(this.expiry, 'quant/viop/expiry');
    this.intra = panel('quant-viop-intraday', 'Gün içi · 5 dakikalık barlar (Bloomberg)', { cls: 'aux' });
    this.intra.note.textContent = 'Ön kontratın işlemleri ve USDTRY orta kuru: yarım saatlik dilimde barın oynaklığı ve ima faizin günün ortalamasından '
      + 'ortalama uzaklığı (− = o saatlerde genellikle daha düşük: alış için iyi). Barlar canlı modda, geçmiş günler için bir kez istenir.';
    this.boxes.intra = new GridBox(this.intra, 'quant/viop/intraday');
    this.boxes.days = new GridBox(this.intra, 'quant/viop/days');
    this.calib = panel('quant-viop-calibration', 'Seviyeler geçmişte nasıl tuttu', { cls: 'aux' });
    this.calib.note.textContent = 'Haftalık: geçmişin her kapanışında o haftanın kalanı için verilen seviyeler, gelen kapanışlara karşı (1 ve 3 aylık sabit '
      + 'vade). c: isabet oranlarını olasılıklara en çok yaklaştıran σ çarpanı (canlı seviyelerde kullanılır). Gün içi: barlı günlerde saat 11:00\'de verilen '
      + 'seviyeler, günün kalanına karşı.';
    this.boxes.calib = new GridBox(this.calib, 'quant/viop/calibration');
    this.ranges = panel('quant-viop-ranges', 'Günlük aralık · fiyat (en yüksek − en düşük)', { cls: 'aux' });
    this.boxes.ranges = new GridBox(this.ranges, 'quant/viop/ranges');
    this.data_ = panel('quant-viop-data', 'Veri · kontratların Bloomberg geçmişi', { cls: 'aux' });
    this.boxes.data = new GridBox(this.data_, 'quant/viop/data');
    page.append(sp.el, cp.el, this.table.el, this.levels.el, this.cal.el, this.expiry.el, this.intra.el, this.calib.el, this.ranges.el, this.data_.el);
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
    }), list.map((s) => s.id), 'Şu an VİOP sinyali yok (|z| ≥ giriş gerekli).', this.picked);
  }

  fillPage() {
    const v = this.data.viop || {};
    const replay = this.data.mode === 'replay';
    this.modeNote.textContent = replay ? 'Kayıtlı veri modu: VİOP kontratlarının Bloomberg geçmişi ve 5 dakikalık barlar yok - kontratlar ve seviyeler '
      + 'canlı modda, geçmiş dolunca hesaplanır.' : '';
    this.modeNote.classList.toggle('hidden', !replay);
    const live = v.live || {};
    const rows = live.rows || [];
    if (rows.length && !rows.some((r) => r.ticker === this.contract)) this.contract = rows[0].ticker;
    this.contractHost.replaceChildren(rows.length ? seg(rows.map((r) => [r.ticker, r.name]), this.contract,
      (t) => { this.contract = t; keep(PICK_PREF, t); this.fillPage(); }, 'quant-viop-contract') : h('span', { class: 'muted' }, '—'));
    const entry = (this.data.settings || {}).entry_z || 2;
    this.boxes.table.set(['Kontrat', 'Vade', 'Gün', 'Alış ima % (ask)', 'Satış ima % (bid)', 'Orta %', 'OIS % (360)', 'VİOP − OIS (bp)', 'Normal fark (bp)',
      'Adil ima %', 'z', 'Yarı ömür (g)', 'Offshore %', 'VİOP − offshore (bp)', '1.000 $ DV01: kontrat', 'Not'], rows.map((r) => [
      T(r.name, { b: r.ticker === this.contract ? 1 : 0 }), T(r.expiry || ''), N(r.g, 0), N(r.ask, 2), N(r.bid, 2), N(r.mid, 2), N(r.ois, 2),
      N(r.basis, 1, { sign: true }), N(r.mean_basis, 1, { sign: true }), N(r.fair, 2), Z(r.z, entry), N(r.half_life, 1), N(r.off, 2),
      N(r.vs_off, 1, { sign: true }), N((r.size || {}).contracts, 0), T(r.n_cm ? (r.source || '') : 'geçmiş yok', { cls: 'soft' })]),
    rows.map((r) => r.sid || null), live.why || v.why || 'Canlı VİOP kotası yok', this.picked);
    this.fillLevels(rows.find((r) => r.ticker === this.contract));
    const cal = v.calendar || {};
    const me = cal.month_end || [];
    const qe = cal.quarter_end || [];
    this.boxes.cal.set(['Gün', 'Ortalama (bp)', 't', 'n', 'Çeyrek sonu (bp)', 't', 'n'], me.map((r, i) => [T(kname(r.k)), N(r.mean, 2, { sign: true }),
      N(r.t, 1, { sign: true, cls: isNum(r.t) && Math.abs(r.t) >= 2 ? 'thru' : '' }), N(r.n, 0), N((qe[i] || {}).mean, 2, { sign: true }),
      N((qe[i] || {}).t, 1, { sign: true }), N((qe[i] || {}).n, 0)]).concat((cal.weekday || []).map((r) => [T(DAYS_TR[r.w] || ''), N(r.mean, 2, { sign: true }),
      N(r.t, 1, { sign: true }), N(r.n, 0), T(''), T(''), T('')])), null, 'Takvim için geçmiş yok');
    this.boxes.expiry.set(['Vadeye gün', 'İma faiz σ (bp / gün)', 'VİOP − OIS σ (bp / gün)', 'Gün'], (v.expiry || []).map((r) => [
      T(r.from + ' – ' + r.to), N(r.sd_implied, 1), N(r.sd_basis, 1), N(r.n, 0)]), null, 'Vadeye göre oynaklık için geçmiş yok');
    const intra = v.intraday || {};
    this.boxes.intra.set(['Yarım saat', 'Bar σ (bp)', 'Ortalamadan uzaklık (bp)', 'Bar'], (intra.shape || []).map((r) => [
      T(hm(r.from) + '–' + hm(r.from + 30)), N(isNum(r.var) ? Math.sqrt(r.var) * 100 : null, 2), N(r.level_bp, 1, { sign: true }), N(r.n, 0)]),
    null, intra.days ? 'Profil için bar az' : 'Gün içi bar yok (canlı modda Bloomberg\'den istenir)');
    this.boxes.days.set(['Gün', 'En düşük %', 'Saat', 'En yüksek %', 'Saat', 'Kapanış %'], (intra.ranges || []).slice(-10).reverse().map((r) => [
      T(r.day), N(r.low, 2), T(r.low_at), N(r.high, 2), T(r.high_at), N(r.close, 2)]), null, 'Barlı gün yok');
    const calib = v.calibration || {};
    const crow = [];
    for (const G of ['30', '91']) {
      const c = calib[G] || {};
      for (const r of c.rows || []) crow.push([T(G + ' gün'), T(pct(r.p)), T(pct(r.buy)), T(pct(r.buy_fit)), T(pct(r.sell)), T(pct(r.sell_fit)), N(c.c, 2), N(c.n, 0)]);
    }
    const ic = (intra.calibration || {});
    for (const r of ic.rows || []) crow.push([T('gün içi ' + (ic.at || '')), T(pct(r.p)), T(pct(r.buy)), T(''), T(pct(r.sell)), T(''), T(''), N(ic.n, 0)]);
    this.boxes.calib.set(['Seri', 'Olasılık', 'Alış isabeti', 'c ile', 'Satış isabeti', 'c ile', 'c', 'Örnek'], crow, null,
      'Kalibrasyon için geçmiş az (en az 80 gün)');
    this.boxes.ranges.set(['Kontrat', 'Ort. aralık (20 gün)', 'En büyük', 'Gün', 'USDTRY ort. aralık', 'Gün'], (v.ranges || []).map((r) => [
      T(r.name), N(r.range, 4), N(r.range_max, 4), N(r.n, 0), N(r.spot_range, 4), N(r.spot_n, 0)]), null, 'Aralık için en yüksek / en düşük yok');
    const fetch = v.bars_fetch || {};
    this.data_.setTitle('Veri · kontratların Bloomberg geçmişi' + (isNum(fetch.asked) ? ' · son bar isteği: ' + fetch.asked + (fetch.why ? ' (' + fetch.why + ')' : '') : ''));
    this.boxes.data.set(['Kontrat', 'Vade', 'Durum', 'Kapanış günü', 'İma faiz günü', 'En yüksek / düşük günü'], (v.history || []).map((r) => [
      T(r.name + ' · ' + r.ticker), T(r.expiry), T(r.expired ? 'vadesi geçti' : 'işlemde'), N(r.days, 0), N(r.rates, 0), N(r.highs, 0)]),
    null, 'Kontrat yok');
  }

  fillLevels(r) {
    const host = this.levelsBody;
    host.replaceChildren();
    if (!r) { host.appendChild(h('div', { class: 'empty' }, 'Kontrat seçin')); return; }
    this.levels.setTitle('Emir seviyeleri · ' + r.name + ' · alış ' + fmt(r.ask, 2) + ' / satış ' + fmt(r.bid, 2)
      + (isNum(r.fair) ? ' · adil ' + fmt(r.fair, 2) : '') + (isNum(r.calibration_c) ? ' · c ' + fmt(r.calibration_c, 2) : ''));
    // where the levels start and whose σ they use, when not the contract's own quotes and history
    const from = [];
    if (r.levels_from && r.levels_from !== 'kota') from.push('Başlangıç: ' + r.levels_from + (isNum(r.ref) ? ' (' + fmt(r.ref, 2) + ')' : ''));
    if (r.sd_from) from.push('Oynaklık: ' + r.sd_from + ' kontratından (bu kontratın kendi geçmişi az)');
    for (const [which, title] of [['today', 'Bugün (kalan seans)'], ['week', 'Bu hafta (Cuma kapanışına)']]) {
      const part = r[which] || {};
      const box = h('div', { class: 'qlevels' });
      box.appendChild(h('div', { class: 'qsub' }, title + (isNum(part.days) ? ' · ' + fmt(part.days, 1) + ' gün' : '')
        + (isNum(part.sigma_bp) ? ' · σ ' + fmt(part.sigma_bp, 1) + ' bp' : '') + (isNum(part.drift_bp) ? ' · beklenen kayma ' + sgn(part.drift_bp, 1) + ' bp' : '')));
      if (!part.buy && !part.sell) {
        // the reason, as the server gives it: no history for the σ, no quote and no trade, the session over
        const why = part.why || r.levels_why || (which === 'today' ? 'seans kapalı ya da oynaklık için geçmiş yok' : 'oynaklık için geçmiş yok');
        box.appendChild(h('div', { class: 'empty' }, 'Seviye yok: ' + why));
      } else {
        const tbl = h('table', { class: 'plain qlegs' }, h('tr', null, h('th', null, 'Olasılık'), h('th', null, 'Alış emri ima %'), h('th', null, 'Fiyat'),
          h('th', null, 'bp'), h('th', null, 'Satış emri ima %'), h('th', null, 'Fiyat'), h('th', null, 'bp')));
        const buy = part.buy || [];
        const sell = part.sell || [];
        for (let i = 0; i < Math.max(buy.length, sell.length); i++) {
          const b = buy[i] || {};
          const s = sell[i] || {};
          tbl.appendChild(h('tr', null, h('td', null, pct(b.p || s.p)), h('td', { class: 'n' }, fmt(b.level, 2)), h('td', { class: 'n' }, fmt(b.price, 4)),
            h('td', { class: 'n' }, sgn(b.move_bp, 1)), h('td', { class: 'n' }, fmt(s.level, 2)), h('td', { class: 'n' }, fmt(s.price, 4)),
            h('td', { class: 'n' }, sgn(s.move_bp, 1))));
        }
        box.appendChild(tbl);
        box.appendChild(h('div', { class: 'muted' }, 'Sürüklenme: adil değere çekilme ' + sgn(part.pull_bp, 1) + ' bp, vade kayması '
          + sgn((r.roll_bp_day || 0) * (part.days || 0), 1) + ' bp, takvim ' + sgn(part.season_bp, 1) + ' bp.'));
        if (from.length) box.appendChild(h('div', { class: 'muted qfrom' }, from.join(' · ') + '.'));
      }
      host.appendChild(box);
    }
  }
}

/** The pages of this module by id (quant.js asks here first). */
export const VIOP_PAGES = { 'quant-viop': ViopPage };
