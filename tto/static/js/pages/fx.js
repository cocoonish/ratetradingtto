// Spot / FX: one currency pair's option market.  The pairs' spots and main vols at the top; the pair opened below
// it: its vol surface as Bloomberg quotes it (ATM, 25- and 10-delta risk reversals and butterflies, by tenor) with
// the forwards (USDTRY: the Forward page's offshore curve), the smile fitted through each tenor's quotes, and what
// that says about the spot - the implied path with its cloud of percentiles, the probabilities of being above /
// below / between price levels at every tenor, and each tenor's smile and density.  One standard deviation up and
// down is read off the distribution, the skew included (the ATM vol alone gives a symmetric ±1σ).  A row of the surface
// clicked draws that tenor through time: its quotes and its skew (25D RR / ATM) with the z-score.  A quote can be typed
// over (one's own view, back to Bloomberg with an empty value).
import { api } from '../api.js';
import { h, clear, errorToast, toast, promptDialog } from '../ui.js';
import { Grid, plainData, copyGrid } from '../grid.js';
import { toolsOf } from '../columns.js';
import { Chart } from '../chart.js';
import { FanChart, serialOfIso } from '../fan.js';
import { num, isoToTr, parseNumber } from '../format.js';
import { SeriesView } from '../serieschart.js';

const MODELS = [['svi', 'SVI', 'Arbitrajsız SVI: beş kotaya en küçük kareler (önerilen)'],
  ['sabr', 'SABR', 'SABR (β = 1): ATM tam, diğerleri en küçük kareler — USDTRY gibi çarpık smile\'ı tutamayabilir'],
  ['vv', 'Vanna-Volga', '25D pillar\'lardan Vanna-Volga — 10D kotalar kullanılmaz']];
const BANDS = [['0.01', '0.99'], ['0.05', '0.95'], ['0.1', '0.9'], ['0.25', '0.75']];
const MODES = [['above', 'Üstünde', 'Vade sonunda seviyenin üstünde olma olasılığı'],
  ['below', 'Altında', 'Vade sonunda seviyenin altında olma olasılığı'],
  ['between', 'Aralıkta', 'Vade sonunda iki seviye arasında olma olasılığı']];
const HORIZONS = [['3M', '3A'], ['6M', '6A'], ['1Y', '1Y'], ['2Y', '2Y']];
const KINDS = [['ATM', 'ATM'], ['RR25', '25D RR'], ['BF25', '25D BF'], ['RR10', '10D RR'], ['BF10', '10D BF']];
const KIND_NAME = Object.fromEntries(KINDS);
const BLUE = '4F81BD', ORANGE = 'F79646', PURPLE = '8064A2';
const REFRESH_MS = 12000;

const isNum = (v) => typeof v === 'number' && isFinite(v);

function pref(key, fallback) {
  try { const v = localStorage.getItem(key); return v === null ? fallback : v; } catch (e) { return fallback; }
}

function keep(key, value) {
  try { localStorage.setItem(key, String(value)); } catch (e) { /* not kept */ }
}

function seg(options, value, onChange, id) {
  const el = h('div', { class: 'seg', id });
  const set = (v) => { for (const b of el.children) b.classList.toggle('on', b.dataset.v === String(v)); };
  for (const [v, label, title] of options) {
    const b = h('button', { type: 'button', title: title || '' }, label);
    b.dataset.v = String(v);
    b.addEventListener('click', () => { set(v); onChange(v); });
    el.appendChild(b);
  }
  set(value);
  return el;
}

/** A panel whose body can be folded away (remembered per browser). */
function panel(id, title, tools, ...body) {
  const key = 'tto.fx.fold.' + id;
  const sec = h('section', { class: 'panel wide fxpanel', id });
  const fold = h('button', { class: 'iconbtn fold', type: 'button', title: 'Aç / kapat' }, '▾');
  const head = h('header', null, fold, h('h2', null, title), h('span', { class: 'grow' }), ...(tools || []));
  const inner = h('div', { class: 'body fxbody' }, ...body);
  const setFold = (on) => { sec.classList.toggle('collapsed', on); fold.textContent = on ? '▸' : '▾'; };
  fold.addEventListener('click', () => { const on = !sec.classList.contains('collapsed'); setFold(on); keep(key, on ? '1' : '0'); });
  setFold(pref(key, '0') === '1');
  sec.appendChild(head);
  sec.appendChild(inner);
  sec.titleEl = head.querySelector('h2');
  return sec;
}

const vol = (v, d = 2) => (isNum(v) ? num(v, d, false) : '');
const cellNum = (v, d, extra) => (isNum(v) ? Object.assign({ t: num(v, d, false), v, k: 'n' }, extra || {}) : Object.assign({ t: '', k: '' }, extra || {}));

export class FxPage {
  constructor(host, ctx) {
    this.host = host;
    this.ctx = ctx;
    this.pair = pref('tto.fx.pair', 'USDTRY');
    this.model = pref('tto.fx.model', 'svi');
    this.mode = pref('tto.fx.mode', 'above');
    this.horizon = pref('tto.fx.horizon', '1Y');
    this.tenor = pref('tto.fx.tenor', '3M');
    this.histTenor = pref('tto.fx.histtenor', this.tenor);           // the tenor drawn through time
    this.showLevels = pref('tto.fx.levels.on', '1') === '1';
    this.bandsOn = new Set((pref('tto.fx.bands', '0.05,0.25') || '').split(',').filter(Boolean));
    this.grids = {};
    this.charts = {};
    this.loaded = 0;
  }

  levelsKey() { return 'tto.fx.levels.' + this.pair; }

  async load() {
    clear(this.host);
    this.host.appendChild(h('div', { class: 'loading' }, 'Vol yüzeyi kuruluyor…'));
    const [board, surf] = await Promise.all([this.fetchBoard(), this.fetchSurface()]);
    if (this.dead) return;
    this.board = board;
    this.surf = surf;
    this.loaded = Date.now();
    this.build();
    this.fill();
    this.loadTenor();
  }

  /** Quotes still on their way (the first answers of Bloomberg): the page is refreshed sooner. */
  waiting() {
    const s = this.surf, b = this.board;
    return !!((s && s.rows.some((r) => r.ATM_why === 'bekleniyor')) || (b && b.rows.some((r) => r.spot_why === 'bekleniyor')));
  }

  async refresh() {
    if (this.busy || Date.now() - this.loaded < (this.waiting() ? 2500 : REFRESH_MS)) return;
    this.busy = true;
    try {
      const [board, surf] = await Promise.all([this.fetchBoard(), this.fetchSurface()]);
      if (this.dead) return;
      this.board = board;
      this.surf = surf;
      this.loaded = Date.now();
      this.fill();
      this.loadTenor();
    } finally { this.busy = false; }
  }

  destroy() {
    this.dead = true;
    for (const c of Object.values(this.charts)) if (c) c.destroy();
    if (this.sv) this.sv.destroy();
  }

  fetchBoard() { return api.get('/api/fx/board'); }

  fetchSurface() {
    const text = pref(this.levelsKey(), '');
    const levels = text.split(/[\s;]+/).map((s) => parseNumber(s, true)).filter((v) => isNum(v) && v > 0);
    return api.post('/api/fx/surface', { pair: this.pair, model: this.model, levels });
  }

  async reload() {
    const seq = (this.seq = (this.seq || 0) + 1);
    try {
      const surf = await this.fetchSurface();
      if (this.dead || seq !== this.seq) return;
      this.surf = surf;
      this.loaded = Date.now();
      this.fill();
      this.loadTenor();
    } catch (err) { errorToast(err); }
  }

  // ------------------------------------------------------------------ layout
  build() {
    clear(this.host);
    this.grids = {};
    for (const c of Object.values(this.charts)) if (c) c.destroy();
    if (this.sv) { this.sv.destroy(); this.sv = null; }
    this.charts = {};
    this.tenorData = null;
    this.tenorKey = '';
    this.modelSeg = seg(MODELS, this.model, (v) => { this.model = v; keep('tto.fx.model', v); this.reload(); }, 'fx-model');
    this.ownBtn = h('button', { class: 'btn hidden', type: 'button', id: 'fx-own',
      title: 'Bu paritede kendi yazdığınız kotaları silip Bloomberg\'e dönün' });
    this.ownBtn.addEventListener('click', () => this.clearOwn());
    this.info = h('span', { class: 'muted', id: 'fx-info' });
    this.host.appendChild(h('div', { class: 'page-tools' }, h('span', { class: 'muted' }, 'Smile'), this.modelSeg, this.ownBtn,
      h('span', { class: 'grow' }), this.info));
    this.banner = h('div', { class: 'banner hidden', id: 'fx-banner' });
    this.host.appendChild(this.banner);

    // ---- the pairs
    this.boardBody = h('div');
    const copyB = h('button', { class: 'iconbtn', type: 'button', title: 'Tabloyu kopyala' }, 'Kopyala');
    copyB.addEventListener('click', () => this.grids.board && copyGrid(this.grids.board));
    this.host.appendChild(panel('fx-board', 'Pariteler · spot ve vol (satıra tıklayınca parite açılır)', [h('div', { class: 'tools' }, copyB)],
      this.boardBody));

    // ---- the surface
    this.surfBody = h('div');
    this.surfNote = h('div', { class: 'note' });
    const copyS = h('button', { class: 'iconbtn', type: 'button', title: 'Tabloyu kopyala' }, 'Kopyala');
    copyS.addEventListener('click', () => this.grids.surf && copyGrid(this.grids.surf));
    this.surfPanel = panel('fx-surface', 'Vol yüzeyi', [h('div', { class: 'tools' }, copyS)], this.surfBody, this.surfNote);
    this.host.appendChild(this.surfPanel);

    // ---- one tenor through time: its quotes and its skew (a row of the surface clicked)
    this.histSeg = h('span');
    this.histHosts = { atm: h('div', { class: 'volchart' }), rrbf: h('div', { class: 'volchart' }) };
    this.histTitles = { atm: h('div', { class: 'ct' }), rrbf: h('div', { class: 'ct' }) };
    this.svHost = h('div', { class: 'fxtenor' });
    this.histNote = h('div', { class: 'note' }, 'Vol yüzeyinde bir satıra tıklayınca o vadenin son bir yılı çizilir (smile ve yoğunluk da o vadeye geçer). '
      + 'Skew = 25D RR / ATM: risk reversal bölü aynı vadenin ATM vol\'ü (oran); kapanışları iki serinin aynı günkü kapanışlarından. '
      + 'Alttaki grafiklerde seviye, seçili pencerenin ortalaması ve ±2σ bandı, her günün kendinden önceki pencereye göre z-skoru (son nokta bugünkü canlı değer).');
    this.histPanel = panel('fx-tenor', 'Vade geçmişi', [h('span', { class: 'muted' }, 'Vade'), this.histSeg],
      h('div', { class: 'volcharts' }, h('div', null, this.histTitles.atm, this.histHosts.atm), h('div', null, this.histTitles.rrbf, this.histHosts.rrbf)),
      this.svHost, this.histNote);
    this.host.appendChild(this.histPanel);
    this.sv = new SeriesView(this.svHost, { rule: 'macro', prefKey: 'tto.fx.series.window', height: 220, hint: 'Vol yüzeyinde bir satıra tıklayın.' });

    // ---- the cloud
    this.fanHost = h('div', { class: 'fanhost' });
    this.fanNote = h('div', { class: 'note' });
    const hz = seg(HORIZONS.map(([v, t]) => [v, t, 'Grafiğin sağ ucu: ' + t]), this.horizon, (v) => { this.horizon = v; keep('tto.fx.horizon', v); this.fillFan(); }, 'fx-horizon');
    const bands = h('div', { class: 'seg', id: 'fx-bands' });
    for (const [lo, hi] of BANDS) {
      const b = h('button', { type: 'button', title: 'Bandı göster / gizle' }, '%' + Math.round(lo * 100) + '–' + Math.round(hi * 100));
      b.dataset.v = lo;
      b.classList.toggle('on', this.bandsOn.has(lo));
      b.addEventListener('click', () => {
        if (this.bandsOn.has(lo)) this.bandsOn.delete(lo); else this.bandsOn.add(lo);
        b.classList.toggle('on', this.bandsOn.has(lo));
        keep('tto.fx.bands', [...this.bandsOn].join(','));
        this.fillFan();
      });
      bands.appendChild(b);
    }
    const lvBtn = h('button', { type: 'button', title: 'Olasılık tablosundaki seviyeleri grafikte çiz' }, 'Seviyeler');
    lvBtn.classList.toggle('on', this.showLevels);
    lvBtn.addEventListener('click', () => { this.showLevels = !this.showLevels; lvBtn.classList.toggle('on', this.showLevels); keep('tto.fx.levels.on', this.showLevels ? '1' : '0'); this.fillFan(); });
    this.fanPanel = panel('fx-fan', 'İma edilen yol ve olasılık bulutu', [h('span', { class: 'muted' }, 'Ufuk'), hz, bands,
      h('div', { class: 'seg' }, lvBtn)], this.fanHost, this.fanNote);
    this.host.appendChild(this.fanPanel);

    // ---- the probability matrix
    this.levelsInput = h('input', { class: 'inp fxlevels', id: 'fx-levels', spellcheck: 'false', autocomplete: 'off',
      placeholder: 'Seviyeler (boş: otomatik), örn. 50 52 55 60' });
    this.levelsInput.value = pref(this.levelsKey(), '');
    const apply = () => { keep(this.levelsKey(), this.levelsInput.value.trim()); this.reload(); };
    this.levelsInput.addEventListener('keydown', (e) => { if (e.key === 'Enter') apply(); });
    this.levelsInput.addEventListener('change', apply);
    const modeSeg = seg(MODES, this.mode, (v) => { this.mode = v; keep('tto.fx.mode', v); this.fillMatrix(); }, 'fx-mode');
    const copyM = h('button', { class: 'iconbtn', type: 'button', title: 'Tabloyu kopyala' }, 'Kopyala');
    copyM.addEventListener('click', () => this.grids.matrix && copyGrid(this.grids.matrix));
    this.matrixBody = h('div');
    this.matrixNote = h('div', { class: 'note' });
    this.matrixPanel = panel('fx-matrix', 'Olasılık matrisi · vade × seviye', [this.levelsInput, modeSeg, h('div', { class: 'tools' }, copyM)],
      this.matrixBody, this.matrixNote);
    this.host.appendChild(this.matrixPanel);

    // ---- one tenor: smile and density
    this.tenorSeg = h('span');
    this.smileHost = h('div', { class: 'volchart' });
    this.densHost = h('div', { class: 'volchart' });
    this.smileTitle = h('div', { class: 'ct' });
    this.densTitle = h('div', { class: 'ct' });
    this.smilePanel = panel('fx-smile', 'Smile ve yoğunluk', [h('span', { class: 'muted' }, 'Vade'), this.tenorSeg],
      h('div', { class: 'volcharts' }, h('div', null, this.smileTitle, this.smileHost), h('div', null, this.densTitle, this.densHost)));
    this.host.appendChild(this.smilePanel);

    // ---- how it is done
    this.host.appendChild(panel('fx-method', 'Yöntem', null, h('div', { class: 'fxmethod' },
      h('p', null, 'Kotalar Bloomberg\'den: ATM (', h('code', null, 'USDTRYV1M BGN Curncy'), '), 25D / 10D risk reversal (', h('code', null, '25R'), ', ',
        h('code', null, '10R'), ') ve butterfly (', h('code', null, '25B'), ', ', h('code', null, '10B'), '). Butterfly market (broker) strangle\'dır: smile, ATM + BF tek vol\'le fiyatlanan strangle\'ı aynı fiyatlar; RR smile\'ın kendi delta strike\'larındaki vol farkıdır. ATM = delta-neutral straddle.'),
      h('p', null, 'Smile: SVI (toplam varyans, log-moneyness) beş kotaya en küçük kareler ile, Gatheral\'ın kelebek arbitrajı koşulu ve Lee kanat sınırı ceza olarak — yoğunluk hiçbir yerde negatif olmaz. USDTRY\'nin orta kotaları kendi aralarında arbitrajsız olmayabilir; o zaman en yakın arbitrajsız smile alınır ve sapma "Uyum" sütununda vol olarak yazar. SABR ve Vanna-Volga karşılaştırma içindir.'),
      h('p', null, '↑1σ / ↓1σ: vade sonundaki spotun %84 yüzdeliği − forward ve forward − %16 yüzdeliği, yani normal dağılımın bir standart sapmasına denk gelen olasılıklar, '
        + 'smile\'ın çarpıklığıyla (skew) birlikte; yalnız ATM vol\'le hesaplanan ±1σ (spot × ATM × √T) simetriktir ve karşılaştırma için hücrenin ipucunda yazar. '
        + 'Dağılımın ortalaması forward\'dır: USDTRY gibi uzun bir sağ kuyruk (devalüasyon sıçraması) taşıyan bir paritede gövde forward\'ın altında kalır, '
        + '↑1σ küçülür (eksi bile olabilir: %84 yüzdelik forward\'ın altında) ve ↓1σ büyür; kuyruğun kendisi %95 / %99 yüzdeliklerinde görünür.'),
      h('p', null, 'Dağılım risk-nötrdür (forward ölçüsü): vade sonundaki spotun beklenen değeri forward\'dır, yani USDTRY\'de bulutun merkezi faiz farkı kadar yukarıdadır — gerçek dünya olasılığı değil, opsiyon piyasasının fiyatladığıdır. P(S > K) = N(d2) − F·n(d1)·√T·σ\'(K) (Breeden–Litzenberger).'),
      h('p', null, 'Forward: USDTRY Forward sayfasının offshore eğrisinden (ICAP ima TRY faizi ve USD OIS, "Serbest forward" formülü); EURTRY = EURUSD × USDTRY; diğerleri Bloomberg spot + forward puanı. Delta: primli delta USD karşısı olmayan pariteler ve USDxxx için; G10\'da 1Y\'ye kadar spot, sonrası forward delta; USDTRY ve EURTRY her vadede forward delta.'))));
  }

  // ------------------------------------------------------------------ fill
  fill() {
    this.fillBoard();
    this.fillSurface();
    this.fillFan();
    this.fillMatrix();
    this.fillSmile();
  }

  setGrid(id, body, header, rows, empty, onRow) {
    if (!rows.length) {
      clear(body);
      this.grids[id] = null;
      body.appendChild(h('div', { class: 'empty' }, empty));
      return null;
    }
    const data = plainData(header, rows);
    if (this.grids[id]) this.grids[id].replace(data);
    else {
      clear(body);
      const g = new Grid({ data, editable: false, name: 'fx/' + id, tools: toolsOf(body) });
      if (onRow) {
        g.el.classList.add('pickable');
        g.el.addEventListener('click', (e) => {
          const td = e.target.closest('td');
          if (!td || td.__i === undefined || td.__i < 1) return;
          onRow(td.__i - 1, td.__j, e);
        });
      }
      this.grids[id] = g;
      body.appendChild(g.el);
    }
    return this.grids[id];
  }

  fillBoard() {
    const rows = this.board.rows || [];
    const cells = rows.map((r) => {
      const pick = r.pair === this.pair ? ' pick' : '';
      const d = r.decimals || 4;
      const c = (v, dd) => cellNum(v, dd, { cls: pick.trim() });
      return [{ t: r.pair, k: 's', b: 1, cls: pick.trim(), tip: r.group }, { t: r.group, k: 's', cls: (pick + ' muted').trim() },
        isNum(r.spot) ? { t: num(r.spot, d, false), v: r.spot, k: 'n', b: 1, cls: pick.trim() } : { t: r.spot_why || '', k: 's', cls: (pick + ' soft').trim() },
        isNum(r.chg) ? { t: (r.chg > 0 ? '+' : '') + num(r.chg, 2, false) + '%', v: r.chg, k: 'n', cls: pick.trim(),
          tip: 'Son kapanışa göre' } : { t: '', k: '', cls: pick.trim() },
        c(r.ATM_1W, 2), c(r.ATM_1M, 2), c(r.ATM_3M, 2), c(r.ATM_1Y, 2), c(r.RR25_1M, 2), c(r.RR25_3M, 2), c(r.BF25_1M, 2), c(r.RR10_1M, 2),
        cellNum(r.up_1m, d, { cls: pick.trim(), tip: '1 ayda 1σ yukarı, skew dahil: 1M dağılımının %84 yüzdeliği − forward'
          + (isNum(r.move_1m) ? '\nYalnız ATM ile ±1σ: ' + num(r.move_1m, d, false) : '') }),
        cellNum(r.down_1m, d, { cls: pick.trim(), tip: '1 ayda 1σ aşağı, skew dahil: forward − 1M dağılımının %16 yüzdeliği'
          + (isNum(r.move_1m) ? '\nYalnız ATM ile ±1σ: ' + num(r.move_1m, d, false) : '') }),
        cellNum(r.breakeven, d, { cls: pick.trim(), tip: 'Günlük başabaş hareket: spot × ATM 1M / √252' })];
    });
    this.setGrid('board', this.boardBody, ['Parite', 'Grup', 'Spot', 'Gün %', 'ATM 1W', 'ATM 1M', 'ATM 3M', 'ATM 1Y', '25D RR 1M', '25D RR 3M',
      '25D BF 1M', '10D RR 1M', '1M ↑1σ', '1M ↓1σ', 'Başabaş / gün'], cells, 'Parite yok', (i, j) => {
      const r = rows[i];
      // a vol of the board clicked: its tenor is the one drawn through time below
      const t = { 4: '1W', 5: '1M', 6: '3M', 7: '1Y', 8: '1M', 9: '3M', 10: '1M', 11: '1M' }[j];
      if (t && t !== this.histTenor) {
        this.histTenor = t;
        keep('tto.fx.histtenor', t);
        if (r && r.pair === this.pair) { this.markSurface(); this.loadTenor(); }
      }
      if (!r || r.pair === this.pair) return;
      this.pair = r.pair;
      keep('tto.fx.pair', r.pair);
      this.levelsInput.value = pref(this.levelsKey(), '');
      this.fillBoard();
      this.reload();
    });
  }

  fillSurface() {
    const s = this.surf;
    const d = (s.pair_info && s.pair_info.decimals) || 4;
    this.surfPanel.titleEl.textContent = s.pair + ' · vol yüzeyi (' + (s.source || 'BGN') + ')';
    const own = s.rows.reduce((n, r) => n + (r.own || []).length, 0);
    this.ownBtn.classList.toggle('hidden', !own);
    this.ownBtn.textContent = own + ' kota sizin · Bloomberg\'e dön';
    const src = s.forward_source === 'offshore' ? 'Forward: offshore eğrisi (Forward sayfası, ICAP ima TRY + USD OIS)'
      : s.forward_source === 'cross' ? 'Forward: ' + (s.legs || []).join(' × ') : 'Forward: Bloomberg spot + forward puanı';
    this.info.textContent = s.pair + ' · spot ' + (isNum(s.spot) ? num(s.spot, d, false) : '–') + (s.spot_date ? ' · spot valörü ' + isoToTr(s.spot_date) : '')
      + ' · ' + src + ' · ' + (s.pair_info ? s.pair_info.convention : '');
    const missing = s.rows.filter((r) => !isNum(r.ATM)).length;
    const arb = s.rows.filter((r) => r.check && r.check.arbitrage).map((r) => r.tenor);
    const msgs = [];
    if (missing === s.rows.length) msgs.push('Bu parite için vol kotası gelmedi (' + (s.rows[0].ATM_why || 'veri yok') + '). Kayıtlı veri modunda Bloomberg yoktur; kotaları tablodaki hücrelere çift tıklayarak elle yazabilirsiniz.');
    if (arb.length) msgs.push('Seçili model ' + arb.join(', ') + ' vadesinde arbitrajlı (negatif yoğunluk): bu vadelerin olasılıkları güvenilmez — SVI\'ye dönün.');
    this.banner.classList.toggle('hidden', !msgs.length);
    this.banner.textContent = msgs.join(' ');
    const quote = (r, kind) => {
      const v = r[kind], mine = (r.own || []).includes(kind);
      const tip = (mine ? 'Sizin değeriniz · Bloomberg: ' + (isNum(r[kind + '_bbg']) ? num(r[kind + '_bbg'], 3, false) : '–') : r[kind + '_ticker']
        + (isNum(v) ? '' : ' · ' + (r[kind + '_why'] || 'veri yok'))) + '\nÇift tık: kendi değerinizi yazın';
      return isNum(v) ? { t: num(v, 3, false), v, k: 'n', cls: mine ? 'own' : '', tip } : { t: '–', k: 's', cls: 'soft', tip };
    };
    const pt = (r, name) => {
      const p = r.points_smile && r.points_smile[name];
      return p ? { t: num(p.vol, 2, false), v: p.vol, k: 'n', tip: name + ' strike: ' + num(p.strike, d, false) } : { t: '', k: '' };
    };
    const rows = s.rows.map((r) => {
      const fit = r.fit ? Math.max(...Object.values(r.fit).filter(isNum).map(Math.abs)) : null;
      const fitTip = r.fit ? Object.entries(r.fit).map(([k, v]) => k + ': ' + (isNum(v) ? (v > 0 ? '+' : '') + num(v, 3, false) : '–')).join('\n') : '';
      const fwdMine = (r.own || []).includes('FWD');
      const q = r.q || {};
      return [{ t: r.tenor, k: 's', b: 1 }, { t: r.date ? isoToTr(r.date) : '', k: 's', tip: 'Teslim (valör) tarihi' }, cellNum(r.days, 0),
        isNum(r.fwd) ? { t: num(r.fwd, d, false), v: r.fwd, k: 'n', b: 1, cls: fwdMine ? 'own' : '',
          tip: (fwdMine ? 'Sizin forward\'ınız' : (isNum(r.points) ? 'Puan ' + num(r.points, 2, false) : s.forward_source === 'offshore' ? 'Offshore eğrisinden' : '')) + '\nÇift tık: kendi değerinizi yazın' }
          : { t: '–', k: 's', cls: 'soft', tip: 'Forward yok · çift tık: yazın' },
        quote(r, 'ATM'), quote(r, 'RR25'), quote(r, 'BF25'), quote(r, 'RR10'), quote(r, 'BF10'),
        pt(r, '10P'), pt(r, '25P'), pt(r, '25C'), pt(r, '10C'),
        cellNum(r.up_1s, d, { tip: '1σ yukarı, skew dahil: dağılımın %84 yüzdeliği − forward' + (isNum(r.move_1sd) ? '\nYalnız ATM ile ±1σ (spot × ATM × √T): ' + num(r.move_1sd, d, false) : '') }),
        cellNum(r.down_1s, d, { tip: '1σ aşağı, skew dahil: forward − dağılımın %16 yüzdeliği' + (isNum(r.move_1sd) ? '\nYalnız ATM ile ±1σ (spot × ATM × √T): ' + num(r.move_1sd, d, false) : '') }),
        cellNum(q['0.05'], d), cellNum(q['0.5'], d, { b: 1 }), cellNum(q['0.95'], d),
        isNum(fit) ? { t: num(fit, 2, false), v: fit, k: 'n', cls: fit > 0.5 ? 'thru' : 'soft', tip: 'Kotalardan sapma (vol puanı)\n' + fitTip + (r.note ? '\n' + r.note : '') }
          : { t: r.error || '', k: 's', cls: 'soft' },
        r.check ? { t: r.check.arbitrage ? 'arbitraj!' : '✓', k: 's', cls: r.check.arbitrage ? 'thru' : 'soft',
          tip: 'Yoğunluk ' + (r.check.arbitrage ? 'bir yerde negatif' : 'hiçbir yerde negatif değil') + ' · toplam ' + num(r.check.mass, 4, false)
            + ' · E[S]/F − 1 = ' + num(r.check.mean_error * 1e4, 2, false) + ' bp' + (r.delta ? '\nDelta: ' + r.delta + (r.df_note ? ' (' + r.df_note + ')' : '') : '') } : { t: '', k: '' }];
    });
    const marked = rows.map((row, i) => (s.rows[i].tenor === this.histTenor
      ? row.map((c) => Object.assign({}, c, { cls: ((c.cls || '') + ' pick').trim() })) : row));
    const g = this.setGrid('surf', this.surfBody, ['Vade', 'Teslim', 'Gün', 'Forward', 'ATM', '25D RR', '25D BF', '10D RR', '10D BF', '10P', '25P', '25C', '10C',
      '↑1σ', '↓1σ', '%5', 'Medyan', '%95', 'Uyum', 'Yoğunluk'], marked, 'Vade yok', (i) => {
      const r = this.surf.rows[i];
      if (r) this.setTenor(r.tenor);
    });
    if (g && !g.el.__fxedit) {
      g.el.__fxedit = true;
      g.el.addEventListener('dblclick', (e) => {
        const td = e.target.closest('td');
        if (!td || td.__i === undefined || td.__i < 1) return;
        const col = { 3: 'FWD', 4: 'ATM', 5: 'RR25', 6: 'BF25', 7: 'RR10', 8: 'BF10' }[td.__j];
        const r = this.surf.rows[td.__i - 1];
        if (col && r) this.typeQuote(r, col);
      });
    }
    this.surfNote.textContent = 'Vol\'ler vol puanı (%). 10P … 10C: smile\'ın kendi delta strike\'larındaki vol (üzerine gelince strike). ↑1σ / ↓1σ: vade sonunda spotun '
      + 'forward\'dan bir standart sapma yukarı / aşağı hareketi, skew dahil (dağılımın %84 ve %16 yüzdelikleri; yalnız ATM ile simetrik ±1σ üzerine gelince). '
      + 'USDTRY\'de ↑1σ küçük, hatta eksi çıkabilir: büyük yukarı sıçrama kuyruğu ortalamayı (forward\'ı) dağılımın gövdesinin üstüne çeker. %5 / Medyan / %95: '
      + 'risk-nötr dağılımın yüzdelikleri. Uyum: modelin kotalardan en büyük sapması (vol puanı; ayrıntı üzerine gelince). Satıra tıklayınca o vadenin geçmişi "Vade geçmişi"nde çizilir. '
      + 'Bir kotayı ya da forward\'ı değiştirmek için çift tıklayın: değer yalnız sizin görünümünüzü değiştirir, boş bırakınca Bloomberg\'e döner.';
  }

  /** The tenor in focus (a row of the surface clicked, the smile's tenor chosen): its smile and its past. */
  setTenor(t) {
    if (!t) return;
    const smileOk = this.surf && this.surf.rows.some((r) => r.tenor === t && r.curve && r.curve.length);
    if (smileOk && t !== this.tenor) { this.tenor = t; keep('tto.fx.tenor', t); this.fillSmile(); }
    if (t === this.histTenor && this.tenorData) return;
    this.histTenor = t;
    keep('tto.fx.histtenor', t);
    this.markSurface();
    this.loadTenor();
  }

  /** Mark the drawn tenor's row of the surface (in place: a double click on it must still find its cell). */
  markSurface() {
    const g = this.grids.surf;
    if (!g || !g.tds || !this.surf) return;
    g.tds.slice(1).forEach((line, i) => {
      const on = !!(this.surf.rows[i] && this.surf.rows[i].tenor === this.histTenor);
      for (const td of line) if (td) td.classList.toggle('pick', on);
    });
  }

  async loadTenor() {
    if (!this.sv || !this.histPanel) return;
    const pair = this.surf ? this.surf.pair : this.pair;
    const tenor = this.histTenor;
    const key = pair + '|' + tenor;
    const seq = (this.tseq = (this.tseq || 0) + 1);
    if (this.tenorKey !== key) this.sv.loading(pair + ' 25D RR / ATM ' + tenor);
    try {
      const d = await api.get('/api/fx/tenor', { pair, tenor });
      if (this.dead || seq !== this.tseq) return;
      this.tenorData = d;
      this.tenorKey = key;
      this.fillTenor();
    } catch (err) {
      if (!this.dead && seq === this.tseq) this.sv.show({ title: pair + ' 25D RR / ATM ' + tenor, points: [], why: (err && err.message) || 'Geçmiş alınamadı' });
    }
  }

  fillTenor() {
    const d = this.tenorData;
    if (!d || !this.histPanel) return;
    this.histPanel.titleEl.textContent = d.pair + ' ' + d.tenor + ' · geçmiş: ATM, risk reversal, butterfly ve skew (25D RR / ATM)';
    clear(this.histSeg);
    const tenors = this.surf ? this.surf.rows.map((r) => r.tenor) : [d.tenor];
    this.histSeg.appendChild(seg(tenors.map((t) => [t, t]), d.tenor, (v) => this.setTenor(v), 'fx-hist-tenor'));
    // every quote on one date axis, the value now as the last point
    const live = d.live || {};
    const days = [...new Set([].concat(...Object.values(d.series).map((pts) => pts.map((p) => p[0]))))].sort();
    const now = Object.values(live).some(isNum) && d.today && (!days.length || d.today > days[days.length - 1]);
    if (now) days.push(d.today);
    const idx = new Map(days.map((x, i) => [x, i]));
    const line = (k, color, dash) => {
      const data = days.map(() => null);
      for (const [day, v] of d.series[k] || []) data[idx.get(day)] = v;
      if (now && isNum(live[k])) data[days.length - 1] = live[k];
      return { name: KIND_NAME[k], kind: 'line', color, data, marker: false, dash: !!dash };
    };
    const x = { type: 'date', values: days.map(serialOfIso), format: 'mmm yy' };
    const cats = days.map(isoToTr);
    const specs = {
      atm: { title: d.pair + ' ATM ' + d.tenor, cats, x, auto: 'fit', decimals: 2, y_title: 'vol %', aspect: 0.45, series: [line('ATM', BLUE)] },
      rrbf: { title: d.pair + ' RR ve BF ' + d.tenor, cats, x, auto: 'fit', decimals: 2, y_title: 'vol %', aspect: 0.45,
        series: [line('RR25', BLUE), line('RR10', BLUE, true), line('BF25', ORANGE), line('BF10', ORANGE, true)] },
    };
    this.histTitles.atm.textContent = 'ATM ' + d.tenor + ' (vol %)';
    this.histTitles.rrbf.textContent = 'Risk reversal ve butterfly ' + d.tenor + ' (25D düz, 10D kesikli)';
    for (const k of ['atm', 'rrbf']) {
      const host = this.histHosts[k];
      const empty = !specs[k].series.some((sr) => sr.data.some(isNum));
      if (empty) {
        if (this.charts['h' + k]) { this.charts['h' + k].destroy(); this.charts['h' + k] = null; }
        clear(host);
        host.appendChild(h('div', { class: 'chart-empty' }, 'Tarihçe yok'));
        continue;
      }
      if (host.firstChild && host.firstChild.classList && host.firstChild.classList.contains('chart-empty')) clear(host);
      if (this.charts['h' + k]) this.charts['h' + k].update(specs[k]); else this.charts['h' + k] = new Chart(host, specs[k], { height: 220 });
    }
    this.sv.show({ title: d.pair + ' 25D RR / ATM ' + d.tenor, points: d.skew, live: d.skew_live, today: d.today, from: d.from, digits: 3, unit: '', axis: 'RR/ATM',
      note: '25D RR ÷ ATM', why: 'Bu vadenin 25D RR ve ATM kapanışları yok (tarihçe henüz inmemiş olabilir).' });
  }

  async typeQuote(r, kind) {
    const name = kind === 'FWD' ? 'forward' : (KINDS.find((k) => k[0] === kind) || [kind, kind])[1] + ' vol';
    const bbg = kind === 'FWD' ? null : r[kind + '_bbg'];
    const cur = kind === 'FWD' ? r.fwd : r[kind];
    const v = await promptDialog(this.surf.pair + ' ' + r.tenor + ' · ' + name,
      'Kendi değeriniz' + (kind === 'FWD' ? '' : ' (vol puanı; Bloomberg: ' + (isNum(bbg) ? num(bbg, 3, false) : '–') + ')') + ' — boş: Bloomberg',
      isNum(cur) ? num(cur, kind === 'FWD' ? 4 : 3, false) : '');
    if (v === null && !(r.own || []).includes(kind)) return;
    const value = v === null ? '' : parseNumber(v, true);
    if (value !== '' && !isNum(value)) { toast('Sayı anlaşılamadı: ' + v, 'err'); return; }
    try {
      await api.post('/api/fx/override', { pair: this.surf.pair, tenor: r.tenor, kind, value });
      this.reload();
    } catch (err) { errorToast(err); }
  }

  async clearOwn() {
    try {
      await api.post('/api/fx/override', { pair: this.surf.pair, clear: true });
      toast('Bloomberg kotalarına dönüldü', 'ok');
      this.reload();
    } catch (err) { errorToast(err); }
  }

  fillFan() {
    const s = this.surf;
    if (!s) return;
    const today = serialOfIso(s.today);
    const horizonTenor = { '3M': '3M', '6M': '6M', '1Y': '1Y', '2Y': '2Y' }[this.horizon];
    const points = s.rows.filter((r) => r.q && r.date && isNum(r.fwd)).map((r) => ({ x: serialOfIso(r.date), label: r.tenor, fwd: r.fwd, q: r.q }));
    const hz = (s.rows.find((r) => r.tenor === horizonTenor) || {}).date;
    const data = {
      today, spot: s.spot, hist: (s.spot_history || []).map(([day, v]) => [serialOfIso(day), v]), points,
      bands: BANDS.filter(([lo]) => this.bandsOn.has(lo)), median: true,
      levels: this.showLevels ? (s.levels || []) : [], decimals: (s.pair_info && s.pair_info.decimals) || 4,
      horizon: hz ? serialOfIso(hz) : (points.length ? points[points.length - 1].x : today + 365),
    };
    if (this.charts.fan) this.charts.fan.update(data);
    else this.charts.fan = new FanChart(this.fanHost, data, { height: 400 });
    this.fanPanel.titleEl.textContent = s.pair + ' · ima edilen yol ve olasılık bulutu';
    this.fanNote.textContent = 'Kesikli çizgi forward patikası (ima edilen yol), mavi çizgi medyan; bantlar vade sonundaki spotun risk-nötr dağılımının yüzdelik aralıkları '
      + '(her vadede, aralarında doğrusal). Geçmiş: spotun son kapanışları (tarihçe). Üzerine gelince o tarihteki değerler.';
  }

  fillMatrix() {
    const s = this.surf;
    if (!s) return;
    const lv = s.levels || [];
    const d = (s.pair_info && s.pair_info.decimals) || 4;
    const shown = lv.map((L) => num(L, d > 2 ? 2 : d, false));
    this.matrixPanel.titleEl.textContent = s.pair + ' · olasılık matrisi (vade sonunda, risk-nötr)';
    if (!this.levelsInput.value.trim() && lv.length) this.levelsInput.placeholder = 'Otomatik: ' + shown.join(' ') + ' — kendi seviyelerinizi yazın';
    let header, rows;
    const pc = (p, tip) => (isNum(p) ? { t: num(p * 100, 1, false) + '%', v: p, k: 'n', bar: Math.round(p * 1000) / 10, bc: 'info', tip } : { t: '', k: '' });
    if (this.mode === 'between') {
      header = ['Vade', '< ' + shown[0]].concat(shown.slice(1).map((t, i) => shown[i] + ' – ' + t)).concat(['≥ ' + shown[shown.length - 1]]);
      rows = s.matrix.map((m) => {
        if (!m.above) return [{ t: m.tenor, k: 's', b: 1 }];
        const a = m.above;
        const out = [{ t: m.tenor, k: 's', b: 1 }, pc(isNum(a[0]) ? 1 - a[0] : null)];
        for (let i = 1; i < a.length; i++) out.push(pc(isNum(a[i - 1]) && isNum(a[i]) ? a[i - 1] - a[i] : null));
        out.push(pc(a[a.length - 1]));
        return out;
      });
    } else {
      const above = this.mode === 'above';
      header = ['Vade'].concat(shown.map((t) => (above ? '> ' : '< ') + t));
      rows = s.matrix.map((m) => [{ t: m.tenor, k: 's', b: 1 }].concat((m.above || lv.map(() => null)).map((p) => pc(isNum(p) ? (above ? p : 1 - p) : null))));
    }
    this.setGrid('matrix', this.matrixBody, header, lv.length ? rows : [], 'Seviye yok: yukarıya fiyat seviyeleri yazın');
    this.matrixNote.textContent = 'Her hücre, o vadenin sonunda spotun seviyenin ' + (this.mode === 'above' ? 'üstünde' : this.mode === 'below' ? 'altında' : 'iki değeri arasında')
      + ' olma olasılığı (opsiyon piyasasının fiyatladığı risk-nötr olasılık: forward\'ın faiz farkı dahil). Seviyeler '
      + (this.levelsInput.value.trim() ? 'sizin yazdıklarınız (bu parite için hatırlanır).' : 'otomatik: 1Y dağılımının %5–%95 aralığında yuvarlak adımlar.');
  }

  fillSmile() {
    const s = this.surf;
    if (!s) return;
    const good = s.rows.filter((r) => r.curve && r.curve.length);
    clear(this.tenorSeg);
    if (!good.length) {
      clear(this.smileHost);
      clear(this.densHost);
      for (const k of ['smile', 'dens']) { if (this.charts[k]) { this.charts[k].destroy(); this.charts[k] = null; } }
      this.smileHost.appendChild(h('div', { class: 'chart-empty' }, 'Smile yok'));
      return;
    }
    if (!good.some((r) => r.tenor === this.tenor)) this.tenor = good[Math.min(4, good.length - 1)].tenor;
    this.tenorSeg.appendChild(seg(good.map((r) => [r.tenor, r.tenor]), this.tenor, (v) => this.setTenor(v), 'fx-tenor'));
    const r = good.find((x) => x.tenor === this.tenor);
    const d = (s.pair_info && s.pair_info.decimals) || 4;
    const pts = Object.entries(r.points_smile || {}).filter(([, p]) => p);
    const ks = r.curve.map((c) => c[0]);
    const smile = { scatter: true, title: s.pair + ' ' + r.tenor + ' smile', auto: 'fit', decimals: 2, aspect: 0.55,
      x_title: 'strike', y_title: 'vol %',
      series: [{ name: 'smile (' + (r.model || '').toUpperCase() + ')', kind: 'scatter', color: BLUE, x: ks, data: r.curve.map((c) => c[1]) },
        { name: 'pillar\'lar', kind: 'scatter', noline: true, marker: true, color: ORANGE, x: pts.map(([, p]) => p.strike), data: pts.map(([, p]) => p.vol),
          labels: pts.map(([n]) => n) }] };
    const top = Math.max(...r.curve.map((c) => c[2]));
    const dens = { scatter: true, title: s.pair + ' ' + r.tenor + ' yoğunluk', auto: 'fit', decimals: 3, aspect: 0.55, x_title: 'vade sonunda spot', y_title: 'yoğunluk',
      series: [{ name: 'risk-nötr yoğunluk', kind: 'scatter', color: BLUE, x: ks, data: r.curve.map((c) => c[2]) },
        { name: 'forward', kind: 'scatter', color: PURPLE, dash: true, x: [r.fwd, r.fwd], data: [0, top] }]
        .concat(isNum(s.spot) ? [{ name: 'spot', kind: 'scatter', color: ORANGE, dash: true, x: [s.spot, s.spot], data: [0, top] }] : []) };
    this.smileTitle.textContent = r.tenor + ' smile · vol − strike (' + (r.delta === 'spot' ? 'spot' : 'forward') + ' delta' + (s.pair_info && s.pair_info.premium ? ', primli' : '') + ')';
    this.densTitle.textContent = r.tenor + ' · vade sonunda spotun dağılımı (' + isoToTr(r.date) + ', forward ' + num(r.fwd, d, false) + ')';
    if (this.charts.smile) this.charts.smile.update(smile); else this.charts.smile = new Chart(this.smileHost, smile, { height: 280 });
    if (this.charts.dens) this.charts.dens.update(dens); else this.charts.dens = new Chart(this.densHost, dens, { height: 280 });
  }
}
