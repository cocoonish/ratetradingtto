// Fiyatlama: one instrument at any start and maturity - TRY OIS, FRA, XCCY, FX forward - priced on the desk's TRY curves
// both ways (the user's own "Eğri interpolasyonu" first, the other beside): the mid, the DV01 bucket by bucket (each
// pillar's quote +1 bp, the curve built again on the same method; beside each bucket its quote, the hedge's rate) and,
// with a price typed, the NPV (tto/pricing.py).
// The price box holds what "Fiyat tipi" says: a rate (an FX forward's outright or points) - or an NPV in TL or $ or an
// upfront in bp, and the rate that prices to it is solved on the user's curve.  "Toplu fiyatlama" prices a list of lines
// the same way, off the same curves.  What is typed is the user's own - kept with the account, per asset (switching back
// finds it); the numbers follow the market: every refresh asks again.
import { api } from '../api.js';
import { h, clear, errorToast } from '../ui.js';
import { num, pct, serialDate } from '../format.js';

const ASSETS = [
  ['ois', 'TRY OIS', 'Sabit ↔ TLREF, spot ya da ileri başlangıçlı; 3 aya kadar tek ödeme, sonra çeyreklik (ACT/365)'],
  ['fra', 'FRA', 'OIS forward\'ı: başlangıç × bitiş, ikisi de OIS spot\'undan (12x15, 1Yx18M ya da tarih)'],
  ['xccy', 'XCCY', 'TRY sabit (yıllık ACT/360) ↔ USD değişken, offshore eğride; kuponlar vadeden geriye, kısa dönem başta'],
  ['fx', 'FX forward', 'USDTRY / EURTRY outright ve puan: offshore TRY eğrisi ve USD (EUR) OIS faizi'],
];
const METHOD = { boot: 'Bootstrap (Murex)', ppk: 'PPK basamak' };
// what the price box holds ("Fiyat tipi"), a swap's and an FX forward's: [kind, button, tip, placeholder]
const KINDS = {
  rate: [['rate', 'Faiz', 'Sabit oran, % (35,10 = %35,10)', 'boş: mid'],
    ['npv_tl', 'NPV TL', 'NPV (TL, + lehine) yazın: o NPV\'yi veren sabit faiz eğrinizde çözülür', 'örn. 1.000.000'],
    ['npv_usd', 'NPV $', 'NPV ($, + lehine; OIS_MAIN!D2\'deki USDTRY ile) yazın: o NPV\'yi veren sabit faiz', 'örn. 25.000'],
    ['upfront', 'Peşin bp', 'Peşin, nominalin bp\'si (%0,5 = 50 bp; + lehine): o peşini veren sabit faiz', 'örn. 25']],
  fx: [['outright', 'Outright', 'Forward kur (outright)', 'boş: mid'],
    ['points', 'Puan', 'Swap puanı: forward = spot + puan / 10.000', 'örn. 290.000'],
    ['npv_tl', 'NPV TL', 'NPV (TL, + lehine) yazın: o NPV\'yi veren forward kur eğrinizde çözülür', 'örn. 1.000.000'],
    ['npv_usd', 'NPV $', 'NPV ($, + lehine; OIS_MAIN!D2\'deki USDTRY ile) yazın: o NPV\'yi veren forward kur', 'örn. 25.000']],
};
// what the Toplu box shows when empty, a swap's and an FX forward's
const BULK_PLACEHOLDER = {
  rate: '1Y\n2Y3M\n12x15\n04.05.2027 04.05.2028\n2Y 38,50',
  fx: '1M\n18M\n04.05.2028\n1Y 62,50',
};
const isNum = (v) => typeof v === 'number' && isFinite(v);
const signed = (v, d) => (isNum(v) ? (v > 0 && Number(v.toFixed(d)) !== 0 ? '+' : '') + num(Number(v.toFixed(d)) === 0 ? 0 : v, d) : '–');
const tone = (v, d) => (isNum(v) && Number(v.toFixed(d)) !== 0 ? (v > 0 ? 'pos' : 'neg') : '');
// a TRY rate (a swap's mid, a bucket's quote, the rate an NPV gives) reads with two decimals - the desk's rule of 25.11.2026
// for the pricing tables' TRY rates, here since 27.11.2026 ("Hepsini yap"); an FX forward's outright keeps four, a USD / EUR
// rate its own.  How it reads only: every number is priced on the full value.
const TRY_DIGITS = 2;

function seg(id, items, onPick) {
  const box = h('div', { class: 'seg', id, role: 'group' });
  for (const [v, label, tip] of items) {
    const b = h('button', { type: 'button', title: tip || null }, label);
    b.dataset.v = v;
    b.addEventListener('click', () => onPick(v));
    box.appendChild(b);
  }
  return box;
}

function pickSeg(box, v) {
  for (const b of box.children) b.classList.toggle('on', b.dataset.v === v);
}

function tile(label, value, opts = {}) {
  const el = h('div', { class: 'q' + (opts.big ? ' big' : '') + (opts.tone ? ' ' + opts.tone : '') },
    h('div', { class: 'l' }, label), h('div', { class: 'v' }, value));
  if (opts.title) el.title = opts.title;
  if (opts.id) el.id = opts.id;
  return el;
}

function field(label, control, id) {
  return h('div', { class: 'field', id: id || null }, h('label', null, label), control);
}

export class PricingPage {
  constructor(host, ctx) {
    this.host = host;
    this.ctx = ctx;
    this.data = null;
    this.seq = 0;
    this.build();
  }

  build() {
    const send = (fields) => this.send(fields);
    this.assetSeg = seg('pr-asset', ASSETS, (v) => send({ asset: v }));
    this.pairSeg = seg('pr-pair', [['USDTRY', 'USDTRY'], ['EURTRY', 'EURTRY']], (v) => send({ pair: v }));
    this.sideSeg = seg('pr-side', [], (v) => send({ side: v }));
    this.sizeKindSeg = seg('pr-size-kind', [], (v) => send({ size_kind: v }));
    this.priceKindSeg = seg('pr-price-kind', [], (v) => send({ price_kind: v }));
    const text = (id, key, placeholder, cls) => {
      const el = h('input', { type: 'text', id, class: 'inp' + (cls ? ' ' + cls : ''), placeholder, autocomplete: 'off', spellcheck: 'false' });
      const commit = () => {
        const inputs = this.data && this.data.inputs;
        const kept = inputs ? inputs.by[inputs.asset][key] : undefined;
        if (el.value.trim() === (kept || '')) return;
        this.sent = { key, value: el.value.trim() };      // (the box takes back what the server keeps: "12x15" → 12 and 15)
        send({ [key]: el.value.trim() });
      };
      el.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); commit(); } });
      el.addEventListener('change', commit);
      return el;
    };
    this.startIn = text('pr-start', 'start', 'Spot');
    this.endIn = text('pr-end', 'end', '1Y, 18M, 2Y3M ya da tarih');
    this.sizeIn = text('pr-size', 'size', '1000', 'num');
    this.priceIn = text('pr-price', 'price', 'boş: mid', 'num');
    this.startField = field('Başlangıç', this.startIn, 'pr-start-field');
    this.endLabel = h('label', null, 'Vade');
    this.pairField = field('Parite', this.pairSeg, 'pr-pair-field');
    this.priceKindField = field('Fiyat tipi', this.priceKindSeg, 'pr-price-kind-field');
    this.curveInfo = h('span', { class: 'muted', id: 'pr-curve' });
    this.stamp = h('span', { class: 'muted', id: 'pr-stamp' });
    const form = h('section', { class: 'panel wide', id: 'pr-form' },
      h('header', null, h('h2', null, 'Fiyatlama · kırık vade, DV01 kovaları, NPV'), this.curveInfo, this.stamp),
      h('div', { class: 'pr-fields' },
        field('Enstrüman', this.assetSeg), this.pairField, this.startField,
        h('div', { class: 'field' }, this.endLabel, this.endIn),
        field('Yön', this.sideSeg), field('Büyüklük', h('div', { class: 'pr-pair' }, this.sizeKindSeg, this.sizeIn)),
        field('Fiyat (isteğe bağlı)', this.priceIn), this.priceKindField),
      this.errorLine = h('div', { class: 'errtxt pr-error', id: 'pr-error' }));
    this.head = h('div', { class: 'pr-head', id: 'pr-head' });
    this.tiles = h('div', { class: 'quote pr-tiles', id: 'pr-tiles' });
    this.bucketBody = h('div', { class: 'body' });
    this.bucketPanel = h('section', { class: 'panel', id: 'pr-buckets-panel' },
      h('header', null, h('h2', null, 'DV01 kovaları ($ / bp)')), this.bucketBody,
      this.bucketNote = h('div', { class: 'note' }));
    this.schedBody = h('div', { class: 'body' });
    this.schedTitle = h('h2', null, 'Ödeme takvimi');
    this.schedPanel = h('section', { class: 'panel fit', id: 'pr-schedule-panel' }, h('header', null, this.schedTitle), this.schedBody);
    this.notes = h('div', { class: 'body pr-notes', id: 'pr-notes' });
    this.notesPanel = h('section', { class: 'panel wide', id: 'pr-notes-panel' }, h('header', null, h('h2', null, 'Konvansiyonlar ve hesap')), this.notes);
    // the instrument's numbers - the tiles, the schedule - and Toplu fiyatlama in one column beside the DV01 buckets: the
    // bulk list on the first screen (the desk's layout review, 27.11.2026: "Hepsini yap")
    this.result = h('div', { class: 'pr-result', id: 'pr-result' },
      h('section', { class: 'panel wide pr-summary' }, h('div', { class: 'pad' }, this.head, this.tiles)),
      this.schedPanel);
    // Toplu fiyatlama: a list of lines priced as the instrument above, off the same curves (its own errors line by line)
    this.bulkIn = h('textarea', { id: 'pr-bulk', class: 'inp pr-bulk-in', rows: '6', spellcheck: 'false', autocomplete: 'off' });
    this.bulkDirty = false;                   // (typed and not sent yet: a refresh leaves it alone)
    this.bulkIn.addEventListener('input', () => { this.bulkDirty = true; });
    this.bulkIn.addEventListener('change', () => this.sendBulk());
    this.bulkIn.addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); this.sendBulk(); } });
    const run = h('button', { type: 'button', class: 'btn primary', id: 'pr-bulk-run', title: 'Satırları fiyatla (Ctrl+Enter)' }, 'Fiyatla');
    run.addEventListener('click', () => this.sendBulk());
    this.bulkHint = h('div', { class: 'muted small', id: 'pr-bulk-hint' });
    this.bulkInfo = h('span', { class: 'muted', id: 'pr-bulk-info' });
    this.bulkBody = h('div', { class: 'body', id: 'pr-bulk-body' });
    this.bulkNote = h('div', { class: 'note', id: 'pr-bulk-note' });
    this.bulkPanel = h('section', { class: 'panel wide', id: 'pr-bulk-panel' },
      h('header', null, h('h2', null, 'Toplu fiyatlama'), this.bulkInfo),
      h('div', { class: 'pr-bulk-form' }, this.bulkIn, h('div', { class: 'pr-bulk-side' }, run, this.bulkHint)),
      this.bulkBody, this.bulkNote);
    const main = h('div', { class: 'pr-main', id: 'pr-main' }, this.bucketPanel,
      h('div', { class: 'pr-col', id: 'pr-col' }, this.result, this.bulkPanel));
    this.host.appendChild(h('div', { class: 'panels pricing', id: 'pricing' }, form, main, this.notesPanel));
  }

  /** The Toplu box sent as it is (the server keeps it with the account, per asset, and prices every line) - once: leaving
   * the box for "Fiyatla" sends it, the click does not send it again. */
  sendBulk() {
    const text = this.bulkIn.value;
    const now = Date.now();
    if (this.lastBulk && this.lastBulk.text === text && now - this.lastBulk.at < 1500) return;
    this.lastBulk = { text, at: now };
    this.bulkDirty = false;
    this.send({ bulk: text });
  }

  async load() {
    this.apply(await api.get('/api/pricing'));
  }

  async refresh() {
    if (this.sending) return;
    const seq = ++this.seq;
    const d = await api.get('/api/pricing');
    if (seq === this.seq && !this.sending) this.apply(d);
  }

  async send(fields) {
    const seq = ++this.seq;
    this.sending = true;
    try {
      const d = await api.post('/api/pricing', fields);
      if (seq === this.seq) this.apply(d);
    } catch (err) {
      errorToast(err);
    } finally {
      this.sending = false;
    }
  }

  /** The inputs as kept (a box being typed into is left alone) and the numbers. */
  fill(inputs) {
    const asset = inputs.asset;
    const f = inputs.by[asset];
    const fx = asset === 'fx';
    pickSeg(this.assetSeg, asset);
    this.pairField.classList.toggle('hidden', !fx);
    this.startField.classList.toggle('hidden', fx);
    pickSeg(this.pairSeg, f.pair || 'USDTRY');
    const kinds = KINDS[fx ? 'fx' : 'rate'];
    const kind = kinds.some((k) => k[0] === f.price_kind) ? f.price_kind : kinds[0][0];
    this.relabel(this.priceKindSeg, kinds, (v) => this.send({ price_kind: v }));
    pickSeg(this.priceKindSeg, kind);
    const ccy = fx ? (f.pair === 'EURTRY' ? 'EUR' : 'USD') : 'TL';
    const sides = fx ? [['AL', 'AL', ccy + ' alış (vadede ' + ccy + ' alınır)'], ['SAT', 'SAT', ccy + ' satış']]
      : [['PAY', 'PAY', (asset === 'xccy' ? 'TRY sabit öde' : 'Sabit öde') + ' (faiz yükselince kazanır)'],
        ['RECEIVE', 'RECEIVE', (asset === 'xccy' ? 'TRY sabit al' : 'Sabit al') + ' (faiz düşünce kazanır)']];
    this.relabel(this.sideSeg, sides, (v) => this.send({ side: v }));
    this.relabel(this.sizeKindSeg, fx ? [['amount', 'Tutar (' + ccy + ')'], ['dv01', 'DV01 ($)']] : [['nominal', 'Nominal (TL)'], ['dv01', 'DV01 ($)']],
      (v) => this.send({ size_kind: v }));
    pickSeg(this.sideSeg, f.side);
    pickSeg(this.sizeKindSeg, f.size_kind);
    this.endLabel.textContent = fx ? 'Valör' : asset === 'fra' ? 'Bitiş' : 'Vade';
    this.startIn.placeholder = asset === 'fra' ? '12, 1Y ya da 12x15' : 'Spot';
    this.endIn.placeholder = asset === 'fra' ? '15, 18M ya da tarih' : '1Y, 18M, 2Y3M ya da tarih';
    const k = kinds.find((x) => x[0] === kind);
    this.priceIn.placeholder = k[3];
    this.priceIn.title = k[2];
    // a box being typed into is left alone - unless what is in it is what was just sent (the server's reading replaces it)
    for (const [el, key] of [[this.startIn, 'start'], [this.endIn, 'end'], [this.sizeIn, 'size'], [this.priceIn, 'price']]) {
      const sent = this.sent && this.sent.key === key && el.value.trim() === this.sent.value;
      if (document.activeElement !== el || sent) el.value = f[key] || '';
    }
    this.bulkIn.placeholder = BULK_PLACEHOLDER[fx ? 'fx' : 'rate'];
    if (!this.bulkDirty) this.bulkIn.value = f.bulk || '';
  }

  relabel(box, items, onPick) {
    const key = items.map((x) => x[0] + x[1]).join('|');
    if (box.dataset.key === key) return;
    box.dataset.key = key;
    clear(box);
    for (const [v, label, tip] of items) {
      const b = h('button', { type: 'button', title: tip || null }, label);
      b.dataset.v = v;
      b.addEventListener('click', () => onPick(v));
      box.appendChild(b);
    }
  }

  apply(d) {
    this.data = d;
    if (d.inputs) this.fill(d.inputs);
    this.curveInfo.textContent = d.curve_text ? 'Eğriniz: ' + d.curve_text + ' (Ayarlar → Eğri interpolasyonu)' : '';
    this.stamp.textContent = new Date().toLocaleTimeString('tr-TR');
    this.errorLine.textContent = d.error || '';
    this.result.classList.toggle('stale', !!d.error);
    this.bucketPanel.classList.toggle('stale', !!d.error);
    this.notesPanel.classList.toggle('stale', !!d.error);
    this.drawBulk(d);                         // (the lines have their own errors: priced whatever the instrument above says)
    if (d.error || !d.label) return;          // (the last numbers stay on the page, dimmed, under the message)
    this.drawHead(d);
    this.drawTiles(d);
    this.drawBuckets(d);
    this.drawSchedule(d);
    this.drawNotes(d);
  }

  drawHead(d) {
    clear(this.head);
    const when = serialDate(d.start) + ' → ' + serialDate(d.end) + ' · ' + num(d.days, 0) + ' gün';
    this.head.append(h('b', { id: 'pr-label' }, d.label + ' · ' + d.side), h('span', { class: 'muted' }, '  ' + when));
  }

  drawTiles(d) {
    const box = clear(this.tiles);
    const [m1, m2] = d.methods;
    const fx = d.asset === 'fx';
    const rate = (v) => (isNum(v) ? (fx ? num(v, 4) : pct(v, TRY_DIGITS)) : '–');
    box.appendChild(tile((fx ? 'Outright · ' : 'Mid · ') + METHOD[m1], rate(d.mid[m1]), { big: true, id: 'pr-mid',
      title: 'Eğriniz (' + METHOD[m1] + ') ile mid' }));
    box.appendChild(tile((fx ? 'Outright · ' : 'Mid · ') + METHOD[m2], rate(d.mid[m2]), { id: 'pr-mid-other',
      title: 'Öbür yöntemle aynı enstrüman: iki eğri kotalı vadelerde aynı, aralarında ayrılır' }));
    box.appendChild(tile('PPK − Bootstrap (' + (fx ? 'puan' : 'bp') + ')', signed(d.diff, fx ? 1 : 2), { id: 'pr-diff' }));
    if (fx) {
      box.appendChild(tile('Puan', num(d.fx.points[m1], 1), { id: 'pr-points', title: '(F − spot) · 10.000 · ' + METHOD[m1] + '; ' + METHOD[m2] + ': ' + num(d.fx.points[m2], 1) }));
      box.appendChild(tile('Spot', num(d.fx.spot, 4), { title: 'Spot valörü ' + serialDate(d.fx.spot_date) }));
      box.appendChild(tile(d.fx.ccy + ' faizi', pct(d.fx.ccy_rate, 3), { title: d.fx.ccy + ' OIS, valöre günlere göre doğrusal (Forward sayfası)' }));
    }
    const sz = d.size;
    const sizeLabel = fx ? 'Tutar (' + d.fx.ccy + ')' : 'Nominal (TL)';
    box.appendChild(tile(sizeLabel, num(sz.size, 0), { id: 'pr-size-out',
      title: sz.kind === 'dv01' ? 'DV01 ' + num(sz.typed, 0) + ' $ → ' + sz.rule : 'Yazılan büyüklük' }));
    const tot = d.buckets.total;
    box.appendChild(tile('DV01 toplam ($)', signed(tot[m1], 0), { id: 'pr-dv01', tone: tone(tot[m1], 0),
      title: METHOD[m1] + ': kovaların toplamı (her kota +1 bp). ' + METHOD[m2] + ': ' + signed(tot[m2], 0) + ' $. Büyüklüğün DV01\'i (annuity kuralı): '
        + num(sz.dv01, 0) + ' $ - kırık vadede kova toplamı ondan biraz ayrılabilir (kotalar 1 bp kayınca bu enstrümanın fiyatı tam 1 bp oynamaz)' }));
    if (d.npv) {
      const n = d.npv;
      const from = n.from;
      if (from) {
        // an NPV / upfront typed: the rate (outright) that prices to it on the user's curve - every number below is at it
        const typedText = from.kind === 'upfront' ? signed(from.typed, 2) + ' bp' : signed(from.typed, 0) + (from.kind === 'npv_usd' ? ' $' : ' TL');
        box.appendChild(tile((fx ? 'Outright' : 'Faiz') + ' ← ' + from.text + ' · ' + METHOD[m1], rate(n.level), { big: true, id: 'pr-implied',
          title: 'Yazılan ' + from.text + ' ' + typedText + ': eğrinizde (' + METHOD[m1] + ') bunu veren ' + (fx ? 'forward kur' : 'sabit faiz')
            + ' - NPV, DV01 kovaları ve Fiyat − mid bu ' + (fx ? 'kurda' : 'faizde') + '. ' + METHOD[m2] + ' eğrisinde aynı NPV: ' + rate(from.level[m2]) }));
      }
      box.appendChild(tile('NPV (TL)', signed(n.tl[m1], 0), { id: 'pr-npv-tl', tone: tone(n.tl[m1], 0),
        title: METHOD[m1] + '. ' + METHOD[m2] + ': ' + signed(n.tl[m2], 0) + ' TL. + lehine, − aleyhine' }));
      box.appendChild(tile('NPV ($)', signed(n.usd[m1], 0), { id: 'pr-npv-usd', tone: tone(n.usd[m1], 0),
        title: METHOD[m2] + ': ' + signed(n.usd[m2], 0) + ' $ (USDTRY ' + num(d.usdtry, 4) + ')' }));
      if (n.upfront) {
        box.appendChild(tile('Peşin (bp)', signed(n.upfront[m1], 2), { id: 'pr-upfront', tone: tone(n.upfront[m1], 2),
          title: 'NPV / nominal · 10.000: swap\'ın değeri nominalin bp\'si olarak (+ lehine: karşılığında bu peşini siz ödersiniz). '
            + METHOD[m2] + ': ' + signed(n.upfront[m2], 2) + ' bp' }));
      }
      box.appendChild(tile('Fiyat − mid (' + n.unit + ')', signed(n.dist[m1], fx ? 1 : 2), { id: 'pr-dist',
        title: (from ? 'Çözülen fiyat ' : 'Yazılan fiyat ') + rate(n.level) + ' · ' + METHOD[m2] + ' mid\'ine: ' + signed(n.dist[m2], fx ? 1 : 2) }));
    }
  }

  drawBuckets(d) {
    const [m1, m2] = d.methods;
    // each bucket's quote: the rate its +1 bp moves, the hedge's - one column, both curves give it back at its maturity
    const off = d.family === 'off';
    const quoteTip = off
      ? 'Kovanın offshore kotası - eğrinin kurulduğu, +1 bp\'nin kaydırdığı kota: TRYI (FX swap ima) tek dönem basit ACT/360, XCCY yıllık ACT/360 par'
      : 'Kovanın OIS kotası - eğrinin kurulduğu, +1 bp\'nin kaydırdığı kota: 3 aya kadar tek dönem basit, sonra çeyreklik par, ACT/365';
    const t = h('table', { class: 'plain', id: 'pr-buckets' },
      h('tr', null, h('th', { class: 'l' }, 'Kova'), h('th', { id: 'pr-buckets-quote', title: quoteTip }, off ? 'Offshore kotası' : 'OIS kotası'),
        h('th', { title: 'Eğriniz' }, METHOD[m1]), h('th', null, METHOD[m2])));
    for (const r of d.buckets.rows) {
      const tr = h('tr', { class: r.pillar ? null : 'soft' });
      tr.dataset.bucket = r.name;
      tr.appendChild(h('td', { class: 'l', title: r.pillar ? (isNum(r.day) ? 'Kotanın günü: ' + serialDate(d.spot + r.day) : '') : d.texts.short }, r.name));
      tr.appendChild(isNum(r.quote) ? h('td', { class: 'pr-quote' }, pct(r.quote, TRY_DIGITS))
        : h('td', { class: 'pr-quote soft', title: d.texts.short || null }, '–'));
      for (const m of [m1, m2]) {
        const v = r.dv01[m];
        tr.appendChild(r.pillar ? h('td', { class: tone(v, 2) === 'pos' ? 'buy' : tone(v, 2) === 'neg' ? 'sell' : null }, signed(v, 2))
          : h('td', { class: 'soft', title: d.texts.short }, '–'));
      }
      t.appendChild(tr);
    }
    const tot = d.buckets.total;
    t.appendChild(h('tr', { class: 'pkg', id: 'pr-buckets-total' }, h('td', null, 'Toplam'), h('td', null, ''),
      h('td', { style: { textAlign: 'right' } }, signed(tot[m1], 2)), h('td', { style: { textAlign: 'right' } }, signed(tot[m2], 2))));
    clear(this.bucketBody).appendChild(t);
    this.bucketNote.textContent = (d.family === 'ois' ? 'OIS kovaları (masanınki): her kota +1 bp, eğri aynı yöntemle yeniden. '
      : 'Offshore eğrinin kotaları (FX swap ≤9A, XCCY 1Y–10Y): her kota +1 bp, eğri aynı yöntemle yeniden. ')
      + 'Kota: kovanın piyasa kotası - hedge\'in yapılacağı faiz (iki eğri de onu kendi vadesinde aynen verir). '
      + '+ = faizler yükselince kazanır.';
  }

  drawSchedule(d) {
    const [m1, m2] = d.methods;
    const body = clear(this.schedBody);
    if (d.asset === 'fx') {
      this.schedTitle.textContent = 'Valör ve iskonto';
      const rows = [['Spot valörü', serialDate(d.fx.spot_date)], ['Valör', serialDate(d.end)], ['Gün', num(d.days, 0)],
        ['Spot', num(d.fx.spot, 4)], [d.fx.ccy + ' faizi (ACT/360)', pct(d.fx.ccy_rate, 4)],
        ['DF TRY · ' + METHOD[m1], num(d.fx.df[m1], 6)], ['DF TRY · ' + METHOD[m2], num(d.fx.df[m2], 6)],
        ['Outright · ' + METHOD[m1], num(d.mid[m1], 4)], ['Puan · ' + METHOD[m1], num(d.fx.points[m1], 1)],
        ['Outright · ' + METHOD[m2], num(d.mid[m2], 4)], ['Puan · ' + METHOD[m2], num(d.fx.points[m2], 1)]];
      const t = h('table', { class: 'plain', id: 'pr-schedule' });
      for (const [k, v] of rows) t.appendChild(h('tr', null, h('td', { class: 'l' }, k), h('td', null, v)));
      body.appendChild(t);
      return;
    }
    const basis = d.asset === 'xccy' ? 'ACT/360' : 'ACT/365';
    this.schedTitle.textContent = 'Ödeme takvimi · ' + d.schedule.length + ' kupon, ' + basis + ' (vadeden geriye, kısa dönem başta)';
    const t = h('table', { class: 'plain', id: 'pr-schedule' },
      h('tr', null, h('th', null, '#'), h('th', null, 'Dönem başı'), h('th', null, 'Ödeme'), h('th', null, 'Gün'), h('th', null, 'τ'),
        h('th', null, 'DF · ' + METHOD[m1]), h('th', null, 'DF · ' + METHOD[m2])));
    d.schedule.forEach((lg, i) => {
      t.appendChild(h('tr', null, h('td', null, String(i + 1)), h('td', null, serialDate(lg.start)), h('td', null, serialDate(lg.pay)),
        h('td', null, num(lg.days, 0)), h('td', null, num(lg.tau, 6)), h('td', null, num(lg.df[m1], 6)), h('td', null, num(lg.df[m2], 6))));
    });
    t.appendChild(h('tr', { class: 'pkg' }, h('td', null, 'Annuity'), h('td', null, ''), h('td', null, ''), h('td', null, ''), h('td', null, ''),
      h('td', { style: { textAlign: 'right' } }, num(d.annuity[m1], 6)), h('td', { style: { textAlign: 'right' } }, num(d.annuity[m2], 6))));
    body.appendChild(t);
  }

  drawNotes(d) {
    const box = clear(this.notes);
    const line = (text, cls) => box.appendChild(h('p', { class: cls || null }, text));
    for (const n of d.notes || []) line(n, 'pr-warn');
    line(d.texts.conventions);
    line(d.texts.dv01);
    if (d.texts.short) line(d.texts.short);
    if (d.npv) line(d.texts.npv);
    if (d.texts.price) line(d.texts.price);
    if (d.size.kind === 'dv01') line('Büyüklük: DV01 ' + num(d.size.typed, 0) + ' $ → ' + d.size.rule + '.');
    for (const e of d.errors || []) line(e, 'pr-warn');
  }

  /** Toplu fiyatlama: one row a line - the mid on both curves, the annuity (an FX forward's points), the size and its
   * DV01 and, with a price on the line, the NPV (or the rate an NPV / upfront gives) - or the line's own error. */
  drawBulk(d) {
    const b = d.bulk;
    const body = clear(this.bulkBody);
    if (!b) {
      this.bulkInfo.textContent = '';
      this.bulkHint.textContent = '';
      this.bulkNote.textContent = '';
      return;
    }
    const fx = b.asset === 'fx';
    const [m1, m2] = b.methods;
    const asset = (ASSETS.find((a) => a[0] === b.asset) || [0, b.asset])[1];
    const size = b.size_kind === 'dv01' ? 'DV01 ' + b.size + ' $' : (fx ? 'tutar ' : 'nominal ') + b.size;
    this.bulkInfo.textContent = asset + ' · ' + b.side + ' · ' + size + ' · fiyat tipi ' + b.kind_text + ' · ' + (b.family === 'off' ? 'offshore' : 'OIS')
      + ' eğrisi, ' + METHOD[m1] + ' önde';
    this.bulkHint.textContent = b.hint;
    this.bulkNote.textContent = b.text;
    if (!b.rows.length) {
      body.appendChild(h('div', { class: 'muted pad', id: 'pr-bulk-empty' }, 'Satır yok: kutuya her satıra bir enstrüman yazın ya da yapıştırın, sonra "Fiyatla".'));
      return;
    }
    const priced = b.rows.some((r) => r.npv);
    const solved = b.rows.some((r) => r.npv && r.npv.from);
    const rate = (v) => (isNum(v) ? (fx ? num(v, 4) : pct(v, TRY_DIGITS)) : '–');
    const other = (what, v) => what + ' · ' + METHOD[m2] + ': ' + v;
    const heads = [['#', ''], ['Satır', 'l'], [fx ? 'Valör' : 'Enstrüman', 'l'], [(fx ? 'Outright · ' : 'Mid · ') + METHOD[m1], ''],
      [(fx ? 'Outright · ' : 'Mid · ') + METHOD[m2], ''], ['PPK − Bootstrap (' + (fx ? 'puan' : 'bp') + ')', ''],
      [fx ? 'Puan' : 'Annuity', ''], [fx ? 'Tutar' : 'Nominal (TL)', ''], ['DV01 ($)', '']];
    if (priced) {
      heads.push(['Fiyat', '']);
      if (solved) heads.push([(fx ? 'Outright ← ' : 'Faiz ← ') + b.kind_text, '']);
      heads.push(['NPV (TL)', ''], ['NPV ($)', '']);
      if (!fx) heads.push(['Peşin (bp)', '']);
      heads.push(['Fiyat − mid (' + (fx ? 'puan' : 'bp') + ')', '']);
    }
    const t = h('table', { class: 'plain', id: 'pr-bulk-table' },
      h('tr', null, ...heads.map(([text, cls]) => h('th', { class: cls || null }, text))));
    b.rows.forEach((r, i) => {
      const tr = h('tr', { class: r.error ? 'err' : null });
      tr.dataset.line = String(i);
      tr.appendChild(h('td', { class: 'muted' }, String(r.n)));
      tr.appendChild(h('td', { class: 'l mono' }, r.line));
      if (r.error) {
        tr.appendChild(h('td', { class: 'l errtxt', colspan: String(heads.length - 2) }, r.error));
        t.appendChild(tr);
        return;
      }
      const when = serialDate(r.start) + ' → ' + serialDate(r.end) + ' · ' + num(r.days, 0) + ' gün';
      tr.appendChild(h('td', { class: 'l', title: when }, fx ? serialDate(r.end) : r.label));
      tr.appendChild(h('td', null, rate(r.mid[m1])));
      tr.appendChild(h('td', null, rate(r.mid[m2])));
      tr.appendChild(h('td', null, signed(r.diff, fx ? 1 : 2)));
      tr.appendChild(fx ? h('td', { title: other('Puan', num(r.points[m2], 1)) }, num(r.points[m1], 1))
        : h('td', { title: other('Annuity', num(r.annuity[m2], 6)) }, num(r.annuity[m1], 6)));
      tr.appendChild(h('td', null, num(r.size, 0)));
      tr.appendChild(h('td', { class: tone(r.dv01[m1], 0) === 'pos' ? 'buy' : tone(r.dv01[m1], 0) === 'neg' ? 'sell' : null,
        title: 'Büyüklüğün DV01\'i (+ = faizler yükselince kazanır). ' + other('DV01', signed(r.dv01[m2], 0)) }, signed(r.dv01[m1], 0)));
      if (priced) {
        const n = r.npv;
        tr.appendChild(h('td', { class: 'mono' }, r.price || ''));
        if (solved) {
          tr.appendChild(h('td', { title: n && n.from ? other(fx ? 'Outright' : 'Faiz', rate(n.from.level[m2])) : null }, n && n.from ? rate(n.level) : ''));
        }
        const cell = (v, d, title) => h('td', { class: tone(v, d) || null, title: title || null }, n ? signed(v, d) : '');
        tr.appendChild(cell(n && n.tl[m1], 0, n ? other('NPV', signed(n.tl[m2], 0) + ' TL') : null));
        tr.appendChild(cell(n && n.usd[m1], 0, n ? other('NPV', signed(n.usd[m2], 0) + ' $') : null));
        if (!fx) tr.appendChild(cell(n && n.upfront[m1], 2, n ? other('Peşin', signed(n.upfront[m2], 2) + ' bp') : null));
        tr.appendChild(cell(n && n.dist[m1], fx ? 1 : 2, n ? other('Fiyat − mid', signed(n.dist[m2], fx ? 1 : 2)) : null));
      }
      t.appendChild(tr);
    });
    body.appendChild(t);
    if (b.left_out) body.appendChild(h('div', { class: 'muted pad' }, b.left_out + ' satır daha var: en çok ' + b.rows.length + ' satır fiyatlanır.'));
  }

  destroy() {}
}
