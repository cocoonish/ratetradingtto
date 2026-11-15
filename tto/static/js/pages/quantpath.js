// İma Patikası and TCMB WIRP (tto/quantpath.py): the implied MPC / FOMC path as a mixture of discrete decisions on
// each bank's grid (PPK 50 bp, FOMC 25 bp - desk settings).  İma Patikası: every meeting's two grid outcomes, the
// discrete paths two consecutive meetings allow with their probability ranges and the P&L per DV01 of the
// meeting-dated OIS periods under each, the path's kinks against their own history, the calibration of the priced
// bigger move.  TCMB WIRP (Bloomberg's WIRP, CME's FedWatch): per meeting the implied rate, the moves priced, ease /
// hold / hike, the rate buckets after a meeting (bars), the conditional matrix, and how the next meetings'
// probabilities moved.  Both pages switch between the TCMB and the Fed; the server computes everything in the quant
// worker's thread, a page reads the result.
import { api } from '../api.js';
import { h, clear, errorToast, toast } from '../ui.js';
import { Chart } from '../chart.js';
import { isoToTr } from '../format.js';
import { QuantPage, GridBox, SignalChart, panel, signalRows, SIGNAL_HEAD, T, N, Z, heatHex, seg, pref, keep, fmt, sgn, pct, isNum,
  BLUE, ORANGE, GREEN, PURPLE, GREY } from './quantbase.js';

const BANK_PREF = 'tto.quant.path.bank';
const BANKS = [['try', 'TCMB · PPK'], ['usd', 'Fed · FOMC']];
const OWN_SETTINGS = ['path_grid_try', 'path_grid_usd', 'path_policy'];
const serialOf = (iso) => Math.round(Date.UTC(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10)) / 86400000) + 25569;
const bp = (v) => (isNum(v) ? (Math.abs(v - Math.round(v)) < 0.05 ? sgn(Math.round(v), 0) : sgn(v, 1)) : '');
const outcome = (v, p) => (isNum(v) ? (Math.abs(v) < 0.05 ? '0' : sgn(v, 0)) + ' · ' + pct(p) : '');
const daysTo = (iso, from) => Math.round((serialOf(iso) - serialOf(from)));

/** What the two pages share: the bank toggle, the replay note, the desk's grid / policy-rate settings, the status. */
class PathBase extends QuantPage {
  constructor(host, ctx, what) {
    super(host, ctx, what);
    this.bank = pref(BANK_PREF, 'try') === 'usd' ? 'usd' : 'try';
    this.charts = {};
  }

  frame(title, panels, withSignals) {
    this.bankSeg = seg(BANKS, this.bank, (v) => { this.bank = v; keep(BANK_PREF, v); this.picked = null; this.fillPage(); }, 'quant-' + this.what + '-bank');
    this.tools([h('span', { class: 'muted' }, 'Merkez bankası'), this.bankSeg]);
    this.modeNote = h('div', { class: 'banner hidden', id: 'quant-' + this.what + '-mode' });
    this.host.appendChild(this.modeNote);
    const page = h('div', { class: 'volpage quantpage' });
    if (withSignals) {
      const sp = panel('quant-' + this.what + '-signals', title + ' · sinyaller');
      sp.note.textContent = 'Kinkler (İma patikası ayrıklığı) ve büyük adımın sistematik yanlış fiyatlanması (İma kalibrasyonu); elenenler gri. '
        + 'Satıra tıklayın: seri ve giriş / hedef / stop aşağıda; senaryo K/Z ve tez sinyalin notunda.';
      this.boxes.sig = new GridBox(sp, 'quant/' + this.what + '/signals', (sid) => this.pick(sid));
      const cp = panel('quant-' + this.what + '-chart', 'Seçili seri');
      this.chart = new SignalChart(cp.body);
      page.append(sp.el, cp.el);
    }
    for (const p of panels) page.appendChild(p.el);
    this.setPanel = panel('quant-' + this.what + '-settings', 'Izgara ve politika faizi · masa ayarı (herkes için)', { cls: 'aux' });
    page.appendChild(this.setPanel.el);
    this.addStatus(page);
    this.host.appendChild(page);
    this.loadSettings().catch(() => {});
  }

  /** The tables of the bank shown. */
  bankData() {
    const d = (this.data || {})[this.what] || {};
    return (d.banks || {})[this.bank] || {};
  }

  fill() {
    this.fillStatus();
    if (!this.data || !this.data.ready) return;
    const replay = this.data.mode === 'replay';
    this.modeNote.classList.toggle('hidden', !replay);
    this.modeNote.textContent = replay ? 'Kayıtlı veri modu: patika dosyanın kaydettiği kotalardan ve tarihçenin kayıtlı ayından hesaplanır. Canlıda '
      + 'Bloomberg kotaları sürer: TCMB patikası tarihçenin PPK hesabından (15 dakikada bir yeniden), Fed patikası SOFR_FOMC tablosundan (dakikada bir).' : '';
    if (this.boxes.sig) this.fillSignals();
    this.fillPage();
  }

  afterPick() {
    if (this.boxes.sig) this.fillSignals();
    this.fillPage();
  }

  fillSignals() {
    const list = this.data.signals || [];
    this.boxes.sig.set(SIGNAL_HEAD.concat(['Bileşik / neden', 'Saat']), list.map((s) => {
      const row = signalRows([s], { gated: !!s.gated })[0];
      if (s.gated) for (const c of row) if (c && typeof c === 'object') c.cls = ((c.cls || '') + ' soft').trim();
      return row;
    }), list.map((s) => s.id), 'Bu analizden şu an eşiği geçen sinyal yok (kinkin kendi geçmişi en az 40 gün, kalibrasyon en az 8 toplantı ister).',
    this.picked);
  }

  async loadSettings() {
    const d = await api.get('/api/quant/settings');
    if (this.dead) return;
    const p = this.setPanel;
    clear(p.body);
    const form = h('div', { class: 'qsettings' });
    const inputs = {};
    for (const k of OWN_SETTINGS) {
      if (!(d.labels || {})[k]) continue;
      const inp = h('input', { class: 'inp', id: 'quant-' + this.what + '-set-' + k, value: String((d.values || {})[k]),
        title: d.limits && d.limits[k] ? 'aralık ' + d.limits[k][0] + ' – ' + d.limits[k][1] : '' });
      inputs[k] = inp;
      form.appendChild(h('label', { class: 'field' }, h('span', null, d.labels[k]), inp));
    }
    const save = h('button', { class: 'btn primary', type: 'button', id: 'quant-' + this.what + '-settings-save' }, 'Kaydet ve yeniden hesapla');
    save.addEventListener('click', async () => {
      const values = {};
      for (const [k, inp] of Object.entries(inputs)) values[k] = inp.value;
      try {
        await api.post('/api/quant/settings', { values });
        toast('Ayarlar kaydedildi: analizler yeniden hesaplanıyor', 'ok', 3000);
        this.poll();
      } catch (e) { errorToast(e); }
    });
    p.body.append(form, h('div', { class: 'qrow' }, save));
    p.note.textContent = 'Izgara: bankanın adım katı (TCMB 50, Fed 25 bp). Politika faizi (elle) 0 iken Masa sayfasındaki "Politika faizi %" (Q155) okunur; '
      + 'WIRP faizleri buna, TLREF ile farkı sabit tutularak çevrilir. Sinyaller sayfasındaki masa ayarlarıyla aynı ayarlardır.'
      + (d.by ? ' Son değiştiren: ' + this.ctx.displayName(d.by) + ' (' + d.at + ').' : '');
  }
}

// ------------------------------------------------------------------------------------------------ İma Patikası
class PathPage extends PathBase {
  constructor(host, ctx) { super(host, ctx, 'path'); }

  build() {
    this.meet = panel('quant-path-meetings', 'Toplantı başına ima · ızgaraya ayrışım');
    this.meet.note.textContent = 'Adım: toplantı sonrası ima seviyesi − bir öncekinin (ilk toplantıda patikanın başladığı seviye: TLREF / stub O/N). Her adım iki yanındaki '
      + 'ızgara katının karışımıdır: −40 = %80 −50 + %20 0. Kümülatif bugünkü seviyeye göre; fiyatlanan adım = kümülatif ÷ ızgara.';
    this.boxes.meet = new GridBox(this.meet, 'quant/path/meetings');
    this.pairs = panel('quant-path-pairs', 'Ardışık toplantılar · tutarlı kesikli patikalar ve toplantı tarihli OIS K/Z');
    this.pairs.note.textContent = 'Patikalar: ızgarada, ardışık iki toplantıda yön değiştirmeyen, toplamı ima toplamın iki yanındaki ızgara katı olan karar çiftleri '
      + '(böyle bir karışım iki adımı veremiyorsa her toplantının kendi iki sonucu: "en yakın"). Olasılık aralığı: iki ima adımı veren bütün karışımlar içinde en az / en çok. '
      + 'K/Z: toplantı tarihli OIS receive, bp / DV01 - 1. dönem iki toplantı arası (ilk çiftten sonra bir önceki döneme karşı), 2. dönem ikinci toplantıdan sonrası.';
    this.boxes.pairs = new GridBox(this.pairs, 'quant/path/pairs');
    this.kinks = panel('quant-path-kinks', 'Kinkler · dönemin komşularının ortalamasına göre');
    this.kinks.note.textContent = 'Kink = C_k − (C_k−1 + C_k+1) ÷ 2 = −(ikinci fark) ÷ 2: + ise dönem eşit adımlı patikaya göre ucuz (receive), − pahalı (pay). Zikzak: ikinci fark '
      + 'ardışık toplantılarda yön değiştiriyor (en az ızgaranın beşte biri). z: aynı toplantının önceki günlerdeki kinkine göre; en az 40 günle sinyal (fly: +1 dönem, −½ komşular).';
    this.boxes.kinks = new GridBox(this.kinks, 'quant/path/kinks', (sid) => this.pick(sid));
    this.cal = panel('quant-path-calib', 'Kalibrasyon · büyük adım şu olasılıkla fiyatlandığında ne oldu?');
    this.boxes.cal = new GridBox(this.cal, 'quant/path/calib');
    this.calm = panel('quant-path-calib-meetings', 'Kalibrasyon · toplantı toplantı', { cls: 'aux' });
    this.boxes.calm = new GridBox(this.calm, 'quant/path/calib-meetings');
    this.frame('İma Patikası', [this.meet, this.pairs, this.kinks, this.cal, this.calm], true);
  }

  fillPage() {
    const b = this.bankData();
    const entry = (this.data.settings || {}).entry_z || 2;
    this.bankSeg.set(this.bank);
    this.meet.setTitle('Toplantı başına ima · ızgaraya ayrışım · ' + (b.label || '') + (b.ok ? ' · ' + isoToTr(b.day) + ' · ızgara ' + fmt(b.grid, 0) + ' bp'
      + (b.live ? ' ●' : '') : ''));
    if (!b.ok) {
      for (const k of ['meet', 'pairs', 'kinks', 'cal', 'calm']) this.boxes[k].set([], [], null, b.why || 'Patika yok');
      return;
    }
    const rate = this.bank === 'try' ? 'TLREF' : 'SOFR';
    this.boxes.meet.set(['Toplantı', 'Gün', rate + ' sonrası %', 'Adım (bp)', 'Alt sonuç · olasılık', 'Üst sonuç · olasılık', 'Büyük adım', 'Olasılığı',
      'Kümülatif (bp)', 'Fiyatlanan adım'], (b.rows || []).map((r) => [T(isoToTr(r.meeting), { b: 1 }), N(daysTo(r.meeting, b.day), 0), N(r.level, 3),
      N(r.step, 1, { sign: true, b: 1 }), T(outcome(r.lo, r.p_lo)), T(outcome(r.hi, r.p_hi)), T(bp(r.big)), T(pct(r.p_big)), N(r.cum, 1, { sign: true }),
      N(r.moves, 2, { sign: true })]), null, 'Toplantı yok');
    this.meet.note.title = 'Başlangıç ' + fmt(b.base, 4) + ' %' + (isNum(b.fixing) ? ' · fixing ' + fmt(b.fixing, 4) + ' %' : '')
      + (b.status ? ' · çalışma kitabının durumu: ' + b.status : '');
    const prow = [];
    for (const p of b.pairs || []) {
      (p.paths || []).forEach((q, i) => {
        prow.push([i ? T('') : T(isoToTr(p.first) + ' → ' + isoToTr(p.second), { b: 1 }),
          i ? T('') : T(bp(p.d1) + ' / ' + bp(p.d2) + ' (toplam ' + bp(p.total) + ')'), i ? T('') : T(p.support + (p.against_previous ? ' · önceki döneme karşı' : '')),
          T(bp(q.a1) + ' / ' + bp(q.a2), { b: 1 }), T(q.name), T(pct(q.p_min)), T(pct(q.p_max)), N(q.pnl1, 1, { sign: true, b: 1 }), N(q.pnl2, 1, { sign: true }),
          T(q.reading, { tip: q.reading })]);
      });
    }
    this.boxes.pairs.set(['Toplantılar', 'İma adımlar (bp)', 'Destek', 'Patika', 'Ad', 'Olasılık en az', 'En çok', '1. dönem K/Z', '2. dönem K/Z', 'Okuma'],
      prow, null, 'Ardışık toplantı yok');
    const ks = b.kinks || [];
    this.boxes.kinks.set(['Toplantı', 'Dönem', 'Kink (bp)', 'İkinci fark (bp)', 'Zikzak', 'z', 'Ortalama (bp)', 'Gün', 'Yarı ömür (g)'], ks.map((k) => [
      T(isoToTr(k.meeting), { b: 1 }), T(isoToTr(k.meeting) + ' – ' + isoToTr(k.next)), N(k.d, 1, { sign: true, b: 1 }), N(k.second, 1, { sign: true }),
      T(k.zigzag ? 'zikzak' : ''), Z(k.z, entry), N(k.mean, 1, { sign: true }), N(k.n, 0, { cls: k.n < 40 ? 'soft' : '' }), N(k.half_life, 1)]),
    ks.map((k) => k.sid || null), 'Kink için en az üç toplantı gerekli', this.picked);
    const cal = b.calibration || {};
    this.boxes.cal.set(['Fiyatlanan olasılık', 'Gün', 'Toplantı', 'Ortalama fiyat', 'Gerçekleşen', '%90 aralık (toplantı sayısıyla)'], (cal.buckets || []).map((x) => [
      T(pct(x.lo) + ' – ' + pct(x.hi), { b: 1 }), N(x.days, 0), N(x.meetings, 0), T(pct(x.priced)), T(pct(x.freq), { b: 1 }),
      T(isNum(x.ci_lo) ? pct(x.ci_lo) + ' – ' + pct(x.ci_hi) : '')]), null, 'Kalibrasyon için geçmiş yok');
    const small = (cal.n || 0) < (cal.min_meetings || 8);
    this.cal.note.textContent = 'Toplantı sıradaki toplantıyken (en çok ' + (cal.window || 20) + ' iş günü önce) büyük adıma (iki ızgara sonucundan sıfırdan uzak olanı) '
      + 'verilen olasılık ile kararın ' + (this.bank === 'try' ? 'TLREF fixinginden (toplantı günü → ertesi fixing, ızgaraya yuvarlanmış; ızgaradan üçte bir adımdan '
      + 'fazla sapan değişim karar sayılmaz)' : 'Fed üst bandının günlük anlık görüntülerinden') + ' okunan sonucu. ' + (cal.n || 0) + ' toplantı, ' + (cal.days || 0) + ' gün'
      + (isNum(cal.bias) ? '; ortalama fark (gerçekleşen − fiyat) ' + sgn(cal.bias * 100, 1) + ' puan, z ' + sgn(cal.z, 2) : '')
      + (small ? ' · ÖRNEKLEM KÜÇÜK: aralıklar geniş, en az ' + (cal.min_meetings || 8) + ' toplantı olmadan sinyal yok.' : '.')
      + (cal.outside ? ' ' + cal.outside + ' gün kararın iki ızgara sonucunun dışında kaldı.' : '');
    this.boxes.calm.set(['Toplantı', 'Gün', 'Son fiyat günü', 'Son ima adım (bp)', 'Büyük adım', 'Olasılığı (son)', 'Olasılığı (ort.)', 'Karar (bp)', 'Fixing değişimi (bp)',
      'Büyük adım oldu mu'], (cal.meetings || []).map((m) => [T(isoToTr(m.meeting), { b: 1 }), N(m.days, 0), T(isoToTr(m.last_day)), N(m.last_step, 1, { sign: true }),
      T(bp(m.big)), T(pct(m.p_last)), T(pct(m.p_mean)), T(bp(m.decided), { b: 1 }), N(m.change, 1, { sign: true }),
      T(m.hit ? 'evet' : 'hayır', { cls: m.hit ? 'thru' : '' })]), null, 'Gerçekleşen kararı bilinen toplantı yok');
  }
}

// ------------------------------------------------------------------------------------------------ TCMB WIRP
class WirpPage extends PathBase {
  constructor(host, ctx) { super(host, ctx, 'wirp'); this.meeting = null; }

  build() {
    this.head = panel('quant-wirp-head', 'Politika faizi ve patika');
    this.boxes.head = new GridBox(this.head, 'quant/wirp/head');
    this.table = panel('quant-wirp-table', 'WIRP · toplantı başına');
    this.table.note.textContent = 'İma faiz: politika faizi + toplantıya kadar kümülatif ima hareket (politika faizi ile patikanın O/N faizi - TLREF, SOFR - arasındaki '
      + 'fark sabit). İndirim / sabit / artırım: toplantı sonrası faizin bugünküne göre (FedWatch gibi). Bu toplantıda: adımın iki ızgara sonucu. Satıra tıklayın: '
      + 'o toplantının faiz olasılıkları aşağıda.';
    this.boxes.table = new GridBox(this.table, 'quant/wirp/table', (m) => { this.meeting = m; this.fillPage(); });
    this.barHost = h('div', { class: 'volchart' });
    this.bars = panel('quant-wirp-bars', 'Toplantı sonrası faiz olasılıkları');
    this.bars.body.appendChild(this.barHost);
    this.matrix = panel('quant-wirp-matrix', 'Koşullu toplantı olasılıkları (%)');
    this.matrix.note.textContent = 'Her toplantının adımı iki ızgara sonucuna bölünür ve adımlar beklenen patika verildiğinde bağımsız sayılır: bir toplantı sonrasının '
      + 'dağılımı öncekinin bu toplantının iki noktalı adımıyla evrişimi (FedWatch\'ın ağacı). Son sütun kontrol: matrisin beklenen değeri − ima (bp; 0 olmalı).';
    this.boxes.matrix = new GridBox(this.matrix, 'quant/wirp/matrix', (m) => { this.meeting = m; this.fillPage(); });
    this.histHost = h('div', { class: 'volchart' });
    this.hist = panel('quant-wirp-history', 'Sıradaki toplantıların olasılıkları · son haftalar', { top: this.histHost });
    this.hist.note.textContent = 'Aynı toplantı için geçmiş günlerin fiyatlaması, bugünkü faiz kovalarında (aradaki kararlar TLREF / üst bandın ızgaraya yuvarlanmış '
      + 'değişiminden). Grafik: bu toplantıların ima adımı (bp) gün gün.';
    this.boxes.hist = new GridBox(this.hist, 'quant/wirp/history');
    this.frame('TCMB WIRP', [this.head, this.table, this.bars, this.matrix, this.hist], false);
  }

  fillPage() {
    const b = this.bankData();
    this.bankSeg.set(this.bank);
    const name = this.bank === 'try' ? 'TCMB' : 'Fed';
    this.table.setTitle('WIRP · ' + name + ' · toplantı başına' + (b.ok ? ' · ' + isoToTr(b.day) + (b.live ? ' ●' : '') : ''));
    if (!b.ok) {
      for (const k of ['head', 'table', 'matrix', 'hist']) this.boxes[k].set([], [], null, b.why || 'Patika yok');
      this.drawBars(null, b);
      return;
    }
    const pol = b.policy || {};
    const rateName = this.bank === 'try' ? 'TLREF' : 'SOFR';
    const hasRate = isNum(pol.rate);
    this.boxes.head.set(['', 'Değer', 'Kaynak / not'], [
      [T('Politika faizi' + (this.bank === 'usd' ? ' (üst bant)' : ''), { b: 1 }), hasRate ? N(pol.rate, 2, { unit: '%', b: 1 }) : T('yok'),
        T(hasRate ? pol.source : (this.bank === 'try' ? 'Masa ayarına (Politika faizi, elle) ya da Masa sayfasındaki Q155\'e girin: kovalar o zaman faiz olur' : 'FDTR yok'))],
      [T('Patikanın başladığı ' + rateName, { b: 1 }), N(b.base, 4, { unit: '%' }), T(isNum(pol.fixing) ? 'fixing ' + fmt(pol.fixing, 4) + ' %' : '')],
      [T('Fark: politika − ' + rateName, { b: 1 }), N(pol.spread, 1, { sign: true, unit: 'bp' }), T(this.bank === 'usd' ? 'bandın ortası − SOFR; ' + 'sabit tutulur'
        : 'sabit tutulur: ima politika faizi = bugünkü + kümülatif ima hareket')],
      [T('Izgara', { b: 1 }), N(b.grid, 0, { unit: 'bp' }), T('masa ayarı')],
      [T('Kontrol', { b: 1 }), N(b.check, 6, { unit: 'bp' }), T('matrisin beklenen değeri − ima patika, en büyük mutlak fark')]], null, '—');
    const rows = b.rows || [];
    if (!this.meeting || !rows.some((r) => r.meeting === this.meeting)) this.meeting = rows.length ? rows[0].meeting : null;
    const sel = rows.find((r) => r.meeting === this.meeting);
    this.boxes.table.set(['Toplantı', 'İma faiz %', 'İma ' + rateName + ' %', 'Bugüne göre (bp)', 'Önceki toplantıya göre (bp)', 'Fiyatlanan adım', 'Bu toplantıda',
      'İndirim', 'Sabit', 'Artırım'], rows.map((r) => [T(isoToTr(r.meeting), { b: 1 }), hasRate ? N(r.rate, 3, { b: 1 }) : T('—'), N(r.level, 3),
      N(r.cum, 1, { sign: true }), N(r.step, 1, { sign: true }), N(r.moves, 2, { sign: true }),
      T(outcome(r.lo, r.p_lo) + '  ' + outcome(r.hi, r.p_hi)), T(pct(r.ease, 1)), T(pct(r.hold, 1)), T(pct(r.hike, 1))]),
    rows.map((r) => r.meeting), 'Toplantı yok', this.meeting);
    const buckets = b.buckets || [];
    this.boxes.matrix.set([this.bank === 'usd' ? 'Toplantı · hedef aralık (bp)' : 'Toplantı · politika faizi %'].concat(buckets.map((x) => ({ t: x.label, k: 's', b: 1, f: 'hd' })),
      ['E[faiz] − ima (bp)']), rows.map((r) => [T(isoToTr(r.meeting), { b: 1 })].concat((r.matrix || []).map((p, i) => (p >= 0.0005
      ? { t: fmt(p * 100, 1), v: p * 100, k: 'n', heat: heatHex(-p) || undefined, b: buckets[i] && buckets[i].k === 0 ? 1 : 0 } : { t: '', k: '' })),
    [N(r.check, 6)])), rows.map((r) => r.meeting), 'Toplantı yok', this.meeting);
    this.drawBars(sel, b);
    this.fillHistory(b);
  }

  drawBars(sel, b) {
    if (!sel) {
      if (this.charts.bars) { this.charts.bars.destroy(); this.charts.bars = null; }
      clear(this.barHost);
      return;
    }
    // the buckets this meeting gives a probability, and every one between them and today's rate (the axis reads from it)
    const all = b.buckets || [];
    const idx = all.map((x, i) => i).filter((i) => (sel.matrix || [])[i] >= 0.0005 || all[i].k === 0);
    const lo = Math.min(...idx), hi = Math.max(...idx);
    const buckets = all.slice(lo, hi + 1);
    const probs = (sel.matrix || []).slice(lo, hi + 1);
    const cats = buckets.map((x) => x.label);
    const cur = buckets.map((x, i) => (x.k === 0 ? probs[i] * 100 : null));
    const other = buckets.map((x, i) => (x.k !== 0 ? probs[i] * 100 : null));
    this.bars.setTitle(isoToTr(sel.meeting) + ' toplantısı sonrası ' + (this.bank === 'usd' ? 'hedef aralık' : 'politika faizi') + ' olasılıkları (%) · ima '
      + (isNum(sel.rate) ? fmt(sel.rate, 3) + ' %' : bp(sel.cum) + ' bp'));
    const spec = { title: 'Olasılık', cats, auto: 'fit', decimals: 1, y_title: '%', aspect: 0.3,
      series: [{ name: 'bugünkü faiz', kind: 'bar', stacked: true, color: ORANGE, data: cur }, { name: 'diğer', kind: 'bar', stacked: true, color: BLUE, data: other }] };
    if (this.charts.bars) this.charts.bars.update(spec); else this.charts.bars = new Chart(this.barHost, spec, { height: 230 });
  }

  fillHistory(b) {
    const w = b;
    const hb = w.history_buckets || [];
    const rows = (w.history || []).map((x, i, all) => [i && all[i - 1].meeting === x.meeting ? T('') : T(isoToTr(x.meeting), { b: 1 }), T(x.lookback),
      T(x.day ? isoToTr(x.day) : 'gün yok', { cls: x.day ? '' : 'soft' }), N(x.step, 1, { sign: true }),
      T(isNum(x.step) ? outcome(x.lo, x.p_lo) + '  ' + outcome(x.hi, x.p_hi) : ''), isNum(x.rate) ? N(x.rate, 3) : N(x.cum, 1, { sign: true })]
      .concat(hb.map((bk, j) => {
        const p = x.matrix ? x.matrix[j] : null;
        return isNum(p) && p >= 0.0005 ? { t: fmt(p * 100, 1), v: p * 100, k: 'n', heat: heatHex(-p) || undefined } : { t: '', k: '' };
      })));
    this.boxes.hist.set(['Toplantı', 'Ne zaman', 'Gün', 'İma adım (bp)', 'Bu toplantıda', isNum((b.policy || {}).rate) ? 'İma faiz %' : 'Kümülatif (bp)']
      .concat(hb.map((x) => ({ t: x.label, k: 's', b: 1, f: 'hd' }))), rows, null, 'Geçmiş yok');
    const ch = w.chart || {};
    const days = ch.days || [];
    if (days.length >= 2) {
      const colors = [BLUE, ORANGE, GREEN, PURPLE];
      const series = (ch.series || []).map((s, k) => ({ name: isoToTr(s.meeting), kind: 'line', color: colors[k % colors.length], data: s.steps, marker: days.length < 25 }));
      const lo = Math.min(...(ch.series || []).flatMap((s) => s.steps.filter(isNum)), 0);
      const hi = Math.max(...(ch.series || []).flatMap((s) => s.steps.filter(isNum)), 0);
      const g = b.grid || 50;
      for (let k = Math.floor(lo / g); k <= Math.ceil(hi / g); k++) {
        series.push({ name: 'ızgara', kind: 'line', color: GREY, dash: true, data: days.map(() => k * g), marker: false, legend: k === Math.floor(lo / g) ? 1 : 0 });
      }
      const spec = { title: 'İma adım (bp)', cats: days.map(isoToTr), x: { type: 'date', values: days.map(serialOf), format: 'dd.mm' }, auto: 'fit', decimals: 0,
        y_title: 'bp', aspect: 0.3, series };
      this.histHost.classList.remove('hidden');
      if (this.charts.hist) this.charts.hist.update(spec); else this.charts.hist = new Chart(this.histHost, spec, { height: 220 });
    } else {
      this.histHost.classList.add('hidden');
    }
  }
}

/** The pages of this module by id (quant.js asks here first). */
export const PATH_PAGES = { 'quant-path': PathPage, 'quant-wirp': WirpPage };
