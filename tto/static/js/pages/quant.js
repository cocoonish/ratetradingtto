// Quant: the desk's statistical signals.  "Sinyaller" lists every signal by group - Konsensüs first (tto/quantcons.py: an
// instrument three or more families agree on, a view of their lines), G10 spot, G10 opsiyon, TRY OIS
// (≤ 2Y first), DİBS, VİOP, Offshore ("offshore limiti") and Diğer, the buttons above the list -, within a group the
// confident ones by their expectancy (the Beklenen K/Z at their calibrated levels, tto/quantlevels.py), then the ones a
// gate holds ("düşük güven", with the reason - a line whose levels lost money in the past among them; never logged nor
// alerted); every line's Ödül / risk and İsabet (its levels' record, the trade count); a click draws the signal's
// series with its ±z bands and entry / target / stop; below it the backtest at the calibrated levels (k / m per group),
// the signal log with each family's hit rate, the alert subscription (families,
// groups) and the desk's settings.  The analysis pages (Korelasyon, PCA / RV, Çiftler, Rejim & Momentum, FX, Makro,
// Model) are in quantviews.js.
//
// Everything is computed on the server in a thread of its own (tto/quant.py): a page only reads the cached result.
// The live stream carries the result's version and the last alert's number (quantEvent): a quant page reloads when
// the version moves, a new alert of a family the user subscribed to comes up as a toast.
import { api } from '../api.js';
import { h, clear, errorToast, toast } from '../ui.js';
import { isoToTr } from '../format.js';
import { quantView } from './quantviews.js';
import { fitPage } from './quantfit.js';
import { PATH_PAGES } from './quantpath.js';          // İma Patikası, TCMB WIRP
import { LEAD_PAGES } from './quantlead.js';          // Öncü-Takipçi
import { VIOP_PAGES } from './quantviop.js';          // VİOP
import { TREND_PAGES } from './quanttrend.js';        // Trend
import { SIRA_PAGES } from './quantsira.js';          // Carry + momentum
import { ML_PAGES } from './quantml.js';              // Makine öğrenmesi
import { OPTSPOT_PAGES } from './quantoptspot.js';    // Opsiyon → spot
import { DIBSSW_PAGES } from './quantdibssw.js';      // DİBS switch
import { QuantPage, GridBox, SignalChart, panel, signalRows, SIGNAL_HEAD, LOW, T, N, Z, seg, pref, keep, fmt, sgn, pct, isNum, live } from './quantbase.js';
import { boxTools } from '../pagebox.js';

// ------------------------------------------------------------------------------------------------ Sinyaller
const FAMILY_PREF = 'tto.quant.family', ASSET_PREF = 'tto.quant.asset', GROUP_PREF = 'tto.quant.group';

class SignalsPage extends QuantPage {
  constructor(host, ctx) {
    super(host, ctx, 'signals');
    this.family = pref(FAMILY_PREF, '');
    this.asset = pref(ASSET_PREF, '');
    this.group = pref(GROUP_PREF, '');
  }

  query() {
    return { family: this.family || undefined, asset: this.asset || undefined, group: this.group || undefined };
  }

  build() {
    this.famSel = h('select', { class: 'inp', id: 'quant-family', title: 'Aileye göre süz' });
    this.assetSel = h('select', { class: 'inp', id: 'quant-asset', title: 'Varlığa göre süz' });
    this.famSel.addEventListener('change', () => { this.family = this.famSel.value; keep(FAMILY_PREF, this.family); this.refresh(true); });
    this.assetSel.addEventListener('change', () => { this.asset = this.assetSel.value; keep(ASSET_PREF, this.asset); this.refresh(true); });
    this.tools([h('span', { class: 'muted' }, 'Aile'), this.famSel, h('span', { class: 'muted' }, 'Varlık'), this.assetSel]);
    const page = h('div', { class: 'volpage quantpage' });
    // the groups above the list, in its order: a button each (its lines), "Tümü" all of them
    this.groupBar = h('div', { class: 'seg qgroups', id: 'quant-groups', role: 'tablist' });
    const list = panel('quant-signals', 'Sinyaller', { top: this.groupBar });
    list.note.textContent = 'En üstte Konsensüs: aynı enstrümanda üç ya da daha fazla ailenin güvenli satırı aynı yöndeyse tek satır (seviyeler en iyi örneklem '
      + 'dışı kayıtlı ailenin, büyüklük ailelerinkinin medyanı; kendi kaydı ve alarmı yok, aileler kendi satırlarıyla durur). '
      + 'Sıra: gruplar (G10 spot, G10 opsiyon, TRY OIS - önce ≤ 2Y, sonra uzun uç -, DİBS, VİOP, Offshore, Diğer); grubun içinde önce '
      + 'kapılardan geçenler beklenen K/Z\'ye göre (TL, satırın kendi büyüklüğüyle), sonra "düşük güven" olanlar (bir kapıya takıldı ya da seviyeleri geçmişte '
      + 'zarar ettirdi; neden son sütunda, kayda ve alarma düşmez). Hedef / stop: ailenin geçmiş işlemlerinden ayarlı seviyeler - tutmanın σ\'sının katları, '
      + 'ödül / risk ≥ 1; İsabet: o seviyelerle geçmiş işlemlerin (örneklem dışı) hedefe ya da süre sonunda kârda kapanan payı, parantezde işlem sayısı. Bileşik = |z| '
      + '(masanın ölçeğinde, en çok stop eşiği) × rejim uyumu (1 / 0,5 / 0) × yarı ömür uyumu (ufkun içindeyse 1, iki katına kadar ufuk ÷ yarı ömür, ötesi '
      + 'elenir) × carry yönü (işlemin aleyhineyse 0,5). Uyum: aynı bacağı aynı yönde isteyen diğer aile sayısı (− ile ters yönde olanlar). Offshore satırları '
      + '"offshore limiti" taşır: masanın offshore işlem limiti dar. FX: giriş / hedef / stop işlem yapılan forward\'ın kuru (ufkun sonu valörlü; Birim '
      + 'sütununda hangisi), beklenen K/Z 1 mn baz döviz başına kote para biriminde (USDTRY: TRY, EURUSD: USD); faiz: bp (TL karşılığı ipucunda, ana bacak '
      + 'DV01\'iyle). Satıra tıklayın: işlemin düz anlatımı, seri, bantlar ve giriş / hedef / stop aşağıda. Backtest değildir.';
    this.boxes.signals = new GridBox(list, 'quant/signals', (sid) => this.pick(sid));
    // the list on a launchpad, in the side drawer, in a window of its own - with this page's filter
    list.tools.append(...boxTools(() => ({ type: 'quant-signals', family: this.family || undefined, asset: this.asset || undefined,
      group: this.group || undefined, w: 12 }), this.ctx));
    const chartPanel = panel('quant-chart', 'Seçili sinyal');
    this.chart = new SignalChart(chartPanel.body);
    this.btPanel = panel('quant-backtest', 'Geri test · aynı kurallarla yürüyen pencere (son yıl), ayarlı seviyelerle');
    this.btPanel.note.textContent = 'Her ' + 10 + ' iş gününde bütün aileler yalnızca o güne kadarki kapanışlarla yeniden kurulur, aradaki günler o günün kapanışıyla '
      + 'canlıdaki kurallarla (eşik, kapılar) puanlanır; sinyal olan gün kapanıştan girilir - ileriye bakış yok. Her işlemin tutma süresi boyunca yolu '
      + 'kaydedilir (tutmanın σ\'sı cinsinden: girişte bilinen günlük σ × √tutma). Seviyeler: her ay, o ay başlamadan biten işlemlerle seçilir - stop '
      + 'kazanan işlemlerin %70 / %80 / %90\'ının hiç gitmediği yer (MAE), hedef işlemlerin en iyi noktalarının (MFE) dağılımından ya da stopun 1 / 1,5 / 2 '
      + 'katı (ortalamaya dönüş ailelerinde adil değer de), işlem başına beklenen K/Z en yüksek olan, ödül / risk ≥ 1 ve en az 30 işlemle (grupta az ise '
      + 'ailenin tüm grupları). Trend: hedef yok, iz süren stop. Carry + momentum: sepetin kendi haftalık σ\'sıyla. Satırlar: her ayın işlemleri o ayın '
      + 'seviyeleriyle (örneklem dışı) - isabet: hedefe ya da süre sonunda kârda kapananların payı; K/Z σ: tutmanın σ\'sı cinsinden; TL: paket DV01\'iyle ya '
      + 'da 1 mn baz döviz başına. "Seviyeler" sütunu bugünkü stop / hedef katlarıdır. Kendi seviyesiyle kalan aile (VİOP, gün içi …) kendi kurallarıyla. '
      + 'Günde bir kez, ayrı iş parçacığında hesaplanır.';
    this.boxes.bt = new GridBox(this.btPanel, 'quant/backtest');
    const hits = panel('quant-hits', 'Sinyal kaydı · aile başına isabet');
    hits.note.textContent = 'Her sinyal giriş eşiğini geçtiği an kaydedilir ve izlenir: hedef, stop ya da kayıt süresi (iş günü) dolunca kapanır. '
      + 'İsabet = (hedef + süresi dolup kârda kapananlar) ÷ kapananlar; K/Z σ: kapanıştaki kâr / zarar, sinyalin σ\'sı cinsinden. Canlı takip – backtest değildir.';
    this.boxes.hits = new GridBox(hits, 'quant/hits');
    const log = panel('quant-log', 'Sinyal kaydı · son girişler', { cls: 'aux' });
    this.boxes.log = new GridBox(log, 'quant/log', (sid) => this.pick(sid));
    this.subPanel = panel('quant-subscribe', 'Sinyal alarmı aboneliği', { cls: 'aux' });
    this.setPanel = panel('quant-settings', 'Masa ayarları (herkes için)', { cls: 'aux' });
    page.append(list.el, chartPanel.el, this.btPanel.el, hits.el, log.el, this.subPanel.el, this.setPanel.el);
    this.addStatus(page);
    this.host.appendChild(page);
    this.loadSubscription().catch(() => {});
    this.loadSettings().catch(() => {});
    this.loadLog().catch(() => {});
  }

  focusPanel(p) {
    if (p && p.startsWith('sig:')) this.pick(p.slice(4));
  }

  afterPick() {
    this.fill();
  }

  /** The group buttons: "Tümü" and every group with its lines (confident + düşük güven), the chosen one lit. */
  fillGroups(groups) {
    const total = groups.reduce((a, g) => a + (g.n || 0), 0);
    const items = [{ id: '', slug: 'all', label: 'Tümü', n: total }].concat(groups);
    if (this.groupBar.children.length !== items.length) {
      clear(this.groupBar);
      for (const g of items) {
        const b = h('button', { type: 'button', id: 'quant-group-' + g.slug, role: 'tab' });
        b.dataset.group = g.id;
        b.addEventListener('click', () => { this.group = g.id; keep(GROUP_PREF, this.group); this.refresh(true); });
        this.groupBar.appendChild(b);
      }
    }
    items.forEach((g, i) => {
      const b = this.groupBar.children[i];
      b.textContent = g.label + ' (' + (g.n || 0) + ')';
      b.title = g.id ? g.label + ': ' + (g.live || 0) + ' sinyal, ' + ((g.n || 0) - (g.live || 0)) + ' ' + LOW + (g.tag ? ' · ' + g.tag : '') : 'Bütün gruplar';
      b.classList.toggle('on', g.id === this.group);
      b.setAttribute('aria-selected', g.id === this.group ? 'true' : 'false');
    });
  }

  fill() {
    const d = this.data || {};
    this.fillStatus();
    if (!d.ready) {
      this.boxes.signals.set([], [], null, 'İlk hesap yapılıyor…');
      return;
    }
    if (this.group && !(d.groups || []).some((g) => g.id === this.group)) this.group = '';
    this.fillGroups(d.groups || []);
    const fams = d.families || [];
    if (this.famSel.options.length !== fams.length + 1) {
      clear(this.famSel);
      this.famSel.appendChild(h('option', { value: '' }, 'Tümü'));
      for (const f of fams) this.famSel.appendChild(h('option', { value: f.id }, f.label));
      clear(this.assetSel);
      this.assetSel.appendChild(h('option', { value: '' }, 'Tümü'));
      for (const a of d.assets || []) this.assetSel.appendChild(h('option', { value: a }, a));
    }
    this.famSel.value = this.family;
    this.assetSel.value = this.asset;
    for (const o of this.famSel.options) {
      const f = fams.find((x) => x.id === o.value);
      if (f) o.textContent = f.label + ' (' + f.live + ')';
    }
    // every line: the confident ones and, after them in their group, the ones a gate holds (grey, the reason last)
    const sig = d.signals || [];
    const rows = signalRows(sig, { rank: true, group: true }).map((row, i) => {
      if (sig[i].gated) for (const c of row) if (c && typeof c === 'object') c.cls = ((c.cls || '') + ' soft').trim();
      return row;
    });
    this.boxes.signals.set(['#', 'Grup'].concat(SIGNAL_HEAD, ['Bileşik / neden', 'Saat']), rows, sig.map((s) => s.id),
      (this.group ? this.group + ' grubunda' : 'Şu an') + ' eşiği geçen sinyal yok (giriş |z| ≥ ' + fmt((d.settings || {}).entry_z, 1) + ').', this.picked);
    const hitRows = (d.hits || []).map((f) => [T(f.label, { b: 1 }), N(f.n, 0), N(f.open, 0), N(f.target, 0), N(f.stop, 0), N(f.expired, 0), N(f.closed, 0),
      { t: isNum(f.hit_rate) ? pct(f.hit_rate) : '', v: f.hit_rate, k: 'n', b: 1 }, N(f.avg_pnl_sigma, 2, { sign: true }), N(f.avg_held, 1)]);
    this.boxes.hits.set(['Aile', 'Kayıt', 'Açık', 'Hedef', 'Stop', 'Süre doldu', 'Kapanan', 'İsabet', 'Ort. K/Z σ', 'Ort. gün'], hitRows, null,
      'Henüz kayıt yok: bir sinyal giriş eşiğini geçince burada izlenmeye başlar.');
    if (!this.picked && sig.length) this.pick(sig[0].id);
    this.loadLog().catch(() => {});
    this.loadBacktest().catch(() => {});
  }

  async loadBacktest() {
    if (Date.now() - (this.btAt || 0) < 60000) return;
    this.btAt = Date.now();
    const d = await api.get('/api/quant/backtest');
    if (this.dead) return;
    if (!d.ready) {
      this.boxes.bt.set([], [], null, d.running ? 'Geri test çalışıyor (ayrı iş parçacığında)…' : 'Geri test henüz yok: günün ilk tam hesabından sonra çalışır.');
      return;
    }
    // (a family at its calibrated levels: its out-of-sample record and today's k / m; one that keeps its own: its own trades and why)
    const rows = (d.rows || []).map((r) => [T(r.type ? '   ' + r.type : r.label, { b: r.type ? 0 : 1 }),
      T(r.levels || '', { cls: r.calibrated ? '' : 'soft', tip: r.levels || '' }), N(r.trades, 0), T(pct(r.hit)), N(r.avg_sigma, 2, { sign: true }),
      T(isNum(r.avg) ? sgn(r.avg, 2) + ' ' + (r.unit || '') : ''), N(isNum(r.avg_try) ? r.avg_try / 1000 : null, 1, { sign: true }), N(r.sharpe, 2, { sign: true }), N(r.max_dd, 1)]);
    this.boxes.bt.set(['Aile / grup', 'Seviyeler (bugün)', 'İşlem', 'İsabet', 'Ort. K/Z σ', 'Ort. K/Z', 'Ort. bin TL', 'Sharpe', 'En büyük düşüş σ'], rows, null, 'Geri testte işlem yok');
    this.btPanel.setTitle('Geri test · ' + isoToTr(d.first) + ' – ' + isoToTr(d.last) + ' · ' + d.n_trades + ' işlem · ' + d.refits + ' yeniden kurma'
      + (d.at ? ' · ' + d.at.slice(0, 16) : '') + (d.complete ? '' : ' (süre doldu, eksik)') + (d.running ? ' · yeniden çalışıyor' : ''));
  }

  async loadLog() {
    if (Date.now() - (this.logAt || 0) < 20000) return;
    this.logAt = Date.now();
    const d = await api.get('/api/quant/log');
    if (this.dead) return;
    const rows = (d.entries || []).slice(0, 120).map((e) => [T(isoToTr(e.day) + ' ' + (e.time || '')), T(e.family_label), T(e.expression, { b: 1 }), Z(e.z),
      N(e.level, e.digits), N(e.target, e.digits), N(e.stop, e.digits), T(e.status === 'open' ? 'açık' : e.status, { b: e.status !== 'open' ? 1 : 0 }),
      T(e.closed_day ? isoToTr(e.closed_day) : ''), N(e.closed_level, e.digits), N(e.pnl, 2, { sign: true }), N(e.pnl_sigma, 2, { sign: true }), N(e.held, 0)]);
    this.boxes.log.set(['Giriş', 'Aile', 'İşlem', 'z', 'Seviye', 'Hedef', 'Stop', 'Sonuç', 'Kapanış', 'Son seviye', 'K/Z', 'K/Z σ', 'Gün'], rows,
      (d.entries || []).slice(0, 120).map((e) => e.sid), 'Kayıt yok');
  }

  async loadSubscription() {
    const d = await api.get('/api/quant/subscription');
    if (this.dead) return;
    const p = this.subPanel;
    clear(p.body);
    const on = h('input', { type: 'checkbox', id: 'quant-sub-on' });
    on.checked = !!d.on;
    const fams = h('div', { class: 'qfams', id: 'quant-sub-families' });
    for (const f of d.all_families || []) {
      const box = h('input', { type: 'checkbox', value: f.id });
      box.checked = (d.families || []).includes(f.id);
      fams.appendChild(h('label', { class: 'check' }, box, ' ' + f.label));
    }
    // the list's groups: an alarm of the chosen groups only (none: every group)
    const groups = h('div', { class: 'qfams', id: 'quant-sub-groups' });
    for (const g of d.all_groups || []) {
      const box = h('input', { type: 'checkbox', value: g.id, id: 'quant-sub-group-' + g.slug });
      box.checked = (d.groups || []).includes(g.id);
      groups.appendChild(h('label', { class: 'check' }, box, ' ' + g.label));
    }
    let minimum = d.min || 'Zayıf';
    const strength = seg((d.strengths || ['Zayıf', 'Orta', 'Güçlü']).map((s) => [s, s]), minimum, (v) => { minimum = v; }, 'quant-sub-min');
    const save = h('button', { class: 'btn primary', type: 'button', id: 'quant-sub-save' }, 'Kaydet');
    save.addEventListener('click', async () => {
      try {
        const families = [...fams.querySelectorAll('input:checked')].map((x) => x.value);
        const chosen = [...groups.querySelectorAll('input:checked')].map((x) => x.value);
        await api.post('/api/quant/subscription', { on: on.checked, families, groups: chosen, min: minimum });
        toast(on.checked ? 'Sinyal alarmları size gelecek' : 'Sinyal alarmları kapatıldı', 'ok', 2500);
      } catch (e) { errorToast(e); }
    });
    p.body.append(h('div', { class: 'qform' }, h('label', { class: 'check' }, on, ' Bir sinyal giriş eşiğini geçince bana bildir'),
      h('div', { class: 'muted' }, 'Aileler (hiçbiri seçili değilse hepsi):'), fams,
      h('div', { class: 'muted' }, 'Gruplar (hiçbiri seçili değilse hepsi):'), groups,
      h('div', { class: 'qrow' }, h('span', { class: 'muted' }, 'En az güç'), strength, save)));
    p.note.textContent = 'Bildirim, dashboard açıkken ekranın köşesinde çıkar; tıklayınca sinyal açılır. Yalnızca kapılardan geçen sinyaller bildirilir '
      + '("düşük güven" olanlar hiç). Masa ayarlarındaki "masa alarmına düşen en az güç" '
      + 've üstündeki sinyaller ayrıca masa alarmı olarak herkese çalar (Gördüm / susturma, günün kaydı).';
  }

  async loadSettings() {
    const d = await api.get('/api/quant/settings');
    if (this.dead) return;
    const p = this.setPanel;
    clear(p.body);
    const form = h('div', { class: 'qsettings' });
    const inputs = {};
    for (const [k, label] of Object.entries(d.labels || {})) {
      const v = d.values[k];
      const choices = (d.choices || {})[k];
      const inp = choices ? h('select', { class: 'inp', id: 'quant-set-' + k }, choices.map((c) => h('option', { value: c }, c)))
        : h('input', { class: 'inp', id: 'quant-set-' + k, value: Array.isArray(v) ? v.join(', ') : String(v),
          title: d.limits[k] ? 'aralık ' + d.limits[k][0] + ' – ' + d.limits[k][1] : '' });
      if (choices) inp.value = String(v);
      if (k === 'rv_items' || k === 'fx_pairs') inp.classList.add('wide');
      inputs[k] = inp;
      form.appendChild(h('label', { class: 'field' }, h('span', null, label), inp));
    }
    const save = h('button', { class: 'btn primary', type: 'button', id: 'quant-settings-save' }, 'Kaydet ve yeniden hesapla');
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
    p.note.textContent = 'Masanın ortak ayarları: herkesin sinyallerini değiştirir.' + (d.by ? ' Son değiştiren: ' + this.ctx.displayName(d.by) + ' (' + d.at + ').' : '');
  }
}

// ------------------------------------------------------------------------------------------------ the factory, alerts
export function quantPage(id, host, ctx) {
  if (id === 'quant') return new SignalsPage(host, ctx);
  if (ML_PAGES[id]) return new ML_PAGES[id](host, ctx);          // Makine öğrenmesi (quantml.js)
  const own = PATH_PAGES[id] || LEAD_PAGES[id] || VIOP_PAGES[id] || TREND_PAGES[id] || SIRA_PAGES[id] || OPTSPOT_PAGES[id] || DIBSSW_PAGES[id];
  if (own) return new own(host, ctx);
  return fitPage(id, host, ctx) || quantView(id, host, ctx);
}

/** The live stream's quant counters: reload the open quant page when the result moved; show new alerts. */
export function quantEvent(q) {
  if (!q) return;
  if (isNum(q.version) && q.version !== live.version) {
    live.version = q.version;
    if (live.page && live.page.data) live.page.refresh(true);
  }
  if (!isNum(q.alerts)) return;
  if (live.alerts === null) { live.alerts = q.alerts; return; }            // what came before this page was opened is not new
  if (q.alerts <= live.alerts || live.busy) return;
  const since = live.alerts;
  live.busy = true;
  api.get('/api/quant/alerts', { since }).then((d) => {
    live.alerts = Math.max(live.alerts, d.last || 0);
    for (const a of d.alerts || []) {
      const el = toast('Sinyal · ' + a.family_label + ': ' + a.expression + ' (z ' + sgn(a.z, 2) + ', ' + a.strength + ')', 'ok', 12000);
      el.classList.add('qalert');
      el.title = 'Sinyali aç';
      el.addEventListener('click', () => { window.location.hash = '#/quant?p=' + encodeURIComponent('sig:' + a.sid); });
    }
  }).catch(() => {}).finally(() => { live.busy = false; });
}
