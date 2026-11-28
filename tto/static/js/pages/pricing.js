// Fiyatlama: one instrument at any start and maturity - TRY OIS, FRA, XCCY, FX forward - priced on the desk's TRY curves
// both ways (the user's own "Eğri interpolasyonu" first, the other beside): the mid, the DV01 bucket by bucket (each
// pillar's quote +1 bp, the curve built again on the same method; beside each bucket its quote, the hedge's rate) and,
// with a price typed, the NPV (tto/pricing.py).
// The price box holds what "Fiyat tipi" says: a rate (an FX forward's outright or points) - or an NPV in TL or $ or an
// upfront in bp, and the rate that prices to it is solved on the user's curve.  "Toplu fiyatlama" prices a list of lines
// the same way, off the same curves.  What is typed is the user's own - kept with the account, per asset (switching back
// finds it); the numbers follow the market: every refresh asks again.
//
// 28.11.2026 (the desk: "Bir de fiyatlama kisminda forward gelsin istiyorum ... done diye gunluk islemlere alabilmeliyim
// veya done olmadiysa da hit ratiosunu takip edebilmeliyim"; and "C - 2-3-…", A1):
// - an FX forward gets the forward card: every source at the value date (RET, OIS + spread by FORWARD KOTASYON's rule,
//   the offshore market, VİOP when a contract is near) - TRY rate, outright, points, the difference to the source picked -,
//   the ladder (the standard tenors and the PPK meetings around the value date), "Kotasyon kopyala", "Done → Günlük
//   İşlemler" (its form filled) and "Done değil" - each logged in the quote log (tto/quotelog.py), whose hit ratio is on
//   the page ("Kotasyon defteri");
// - a TRY OIS / FRA gets "Bu işlemi hedge'le" under its buckets (each bucket's opposite TRY OIS, one "Hepsine işlem gir")
//   and "Pozisyona ekle (deneme)": DV01 Risk's buckets + this trade, before and after - nothing saved;
// - "İşlem gir ▾" on the result (Günlük İşlemler / Trades) and "İşleme al" on every Toplu line;
// - the page opens with fields from its address (``#/fiyatlama?asset=ois&end=2Y3M&side=PAY&size=1000&size_kind=dv01`` -
//   the names of the inputs: asset, pair, start, end, side, size, size_kind, price, price_kind, source, client);
// - "hesaplanıyor…" until the first answer, and what is missing said where the numbers would be.
import { api } from '../api.js';
import { h, clear, errorToast, toast, menu, copyText, foldNote } from '../ui.js';
import { num, pct, serialDate } from '../format.js';
import { quoteLang } from '../kotasyon.js';
import { mountQuoteLog, setQuoteStatus, tradeOfQuote } from '../quotelog.js';
import { waitFor } from '../commandrun.js';
import { openBulk } from './blotterentry.js';

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
// the page's inputs an address may carry (#/fiyatlama?asset=ois&end=2Y3M …): the names the server keeps them under
const PARAMS = ['asset', 'pair', 'start', 'end', 'side', 'size', 'size_kind', 'price', 'price_kind', 'source', 'client'];
const isNum = (v) => typeof v === 'number' && isFinite(v);
const signed = (v, d) => (isNum(v) ? (v > 0 && Number(v.toFixed(d)) !== 0 ? '+' : '') + num(Number(v.toFixed(d)) === 0 ? 0 : v, d) : '–');
const tone = (v, d) => (isNum(v) && Number(v.toFixed(d)) !== 0 ? (v > 0 ? 'pos' : 'neg') : '');
// a TRY rate (a swap's mid, a bucket's quote, the rate an NPV gives) reads with two decimals - the desk's rule of 25.11.2026
// for the pricing tables' TRY rates, here since 27.11.2026 ("Hepsini yap"); an FX forward's outright keeps four, a USD / EUR
// rate its own.  How it reads only: every number is priced on the full value.
const TRY_DIGITS = 2;
const WAIT = 'hesaplanıyor…';

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

/** A panel's note folded to two lines ("devamı"; ui.js foldNote - the page owner's part of B2): {el, set(text)}. */
function foldable(id) {
  const text = h('span', { class: 'note-text' });
  const el = h('div', { class: 'note', id: id || null }, text);
  const fold = foldNote(el);
  return { el, set: (t) => { text.textContent = t || ''; el.classList.toggle('hidden', !t); fold.check(); } };
}

function waiting(text, id) {
  return h('div', { class: 'muted pad pr-wait', id: id || null }, text || WAIT);
}

/** The fields an address asks for (``#/fiyatlama?asset=ois&end=2Y3M``) - null when it asks for none. */
export function hashFields(hash) {
  const raw = String(hash || '');
  const cut = raw.indexOf('?');
  if (cut < 0) return null;
  const q = new URLSearchParams(raw.slice(cut + 1));
  const out = {};
  for (const k of PARAMS) {
    if (!q.has(k)) continue;
    const v = q.get(k);
    out[k] = k === 'asset' ? v.toLowerCase() : (k === 'side' || k === 'pair' ? v.toUpperCase() : v);
  }
  return Object.keys(out).length ? out : null;
}

// ---------------------------------------------------------------------------------------------- İşlem gir (A1)
/** A rate (a decimal) as the forms take it: per cent, four decimals, in the user's number format. */
const rateText = (v) => (isNum(v) ? num(v * 100, 4, false) : '');
/** The server's trade spec (tto/pricing.py ``trade_specs``) as Günlük İşlemler's form takes it (``ctx.openTrade``). */
function blotterSpec(spec, note) {
  if (!spec) return null;
  const out = Object.assign({}, spec, { note: note || spec.note || '' });
  if (spec.kind === 'fwd') {
    out.value = isNum(spec.value) ? num(spec.value, 4, false) : '';
    if (isNum(spec.amount)) out.amount = num(spec.amount, 0, false); else delete out.amount;
  } else {
    out.level = rateText(spec.level);
    if (isNum(spec.size)) out.size = num(spec.size, Number.isInteger(spec.size) ? 0 : 2, false); else delete out.size;
  }
  return out;
}

/** Trades' "Yeni işlem" form filled as the user would type it (tto/static/js/commandrun.js's fillTradesForm, with the
 * structure, the start, the FRA and the rate too): nothing is saved. */
async function fillTrades(ctx, spec, note) {
  const page = await ctx.pageReady('trades');
  if (!page || !page.openForm) { toast('Trades sayfası açılamadı', 'err'); return; }
  page.openForm(null);
  const form = await waitFor(() => document.getElementById('trade-form'), 4000);
  if (!form) { toast('Trades formu açılamadı', 'err'); return; }
  const click = (sel) => { const b = form.querySelector(sel); if (b && !b.classList.contains('on')) b.click(); return !!b; };
  const type = (name, value) => {
    const el = form.querySelector('#tf-' + name);
    if (!el || value === undefined || value === null || value === '') return;
    el.value = value;
    el.dispatchEvent(new Event('input', { bubbles: true }));
  };
  click('#tf-product button[data-v="' + spec.product + '"]');
  await waitFor(() => { const d = form.querySelector('#tf-trade_date'); return d && d.value ? d : null; }, 4000);
  if (spec.structure) click('#tf-structure button[data-v="' + spec.structure + '"]');
  if (spec.side) click('#tf-side button[data-v="' + spec.side + '"]');
  type('fra', spec.fra);
  type('value_date', spec.value_date);
  type('end_date', spec.end_date);
  type('price', rateText(spec.price));
  if (isNum(spec.dv01)) type('dv01', num(spec.dv01, 0, false));
  if (isNum(spec.notional)) type('notional', num(spec.notional, 0, false));
  type('note', note || spec.note || '');
  toast('Trades formu Fiyatlama\'dan dolduruldu: kontrol edip "İşlemi kaydet"', 'ok', 4000);
}

export class PricingPage {
  constructor(host, ctx) {
    this.host = host;
    this.ctx = ctx;
    this.data = null;
    this.seq = 0;
    this.priced = false;                     // (numbers drawn at least once: an error dims them, else says why)
    this.lastQuote = null;                   // the forward card's last quote logged: {id, key, quote}
    this.trialOpen = false;
    this.build();
    this.onHash = () => {
      const f = hashFields(window.location.hash);
      if (!f || !/^#\/?fiyatlama/.test(window.location.hash)) return;
      this.clearHash();
      this.send(f);
    };
    window.addEventListener('hashchange', this.onHash);
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
    // B7: until the first answer the page says it is calculating (the panels below are empty till then)
    this.loading = h('div', { class: 'banner pr-loading', id: 'pr-loading' }, 'Fiyatlama ' + WAIT);
    this.head = h('div', { class: 'pr-head', id: 'pr-head' });
    // "İşlem gir ▾": the instrument into Günlük İşlemler's or Trades' form (A1)
    this.tradeBtn = h('button', { class: 'btn sm', type: 'button', id: 'pr-trade', title: 'Fiyatlanan işlemi Günlük İşlemler\'e ya da Trades\'e gir '
      + '(form dolu açılır, kaydetmek sizde)' }, 'İşlem gir ▾');
    this.tradeBtn.addEventListener('click', () => this.tradeMenu(this.tradeBtn, this.data && this.data.trade, this.data && this.data.label));
    this.tiles = h('div', { class: 'quote pr-tiles', id: 'pr-tiles' }, waiting());
    this.bucketBody = h('div', { class: 'body' }, waiting());
    this.bucketPanel = h('section', { class: 'panel', id: 'pr-buckets-panel' },
      h('header', null, h('h2', null, 'DV01 kovaları ($ / bp)')), this.bucketBody,
      (this.bucketNote = foldable('pr-buckets-note')).el);
    // C3: each bucket's opposite TRY OIS, and DV01 Risk's buckets + this trade (nothing saved)
    this.hedgeAll = h('button', { class: 'btn sm', type: 'button', id: 'pr-hedge-all', title: 'Bütün hedge\'leri Günlük İşlemler\'in "Excel\'den yapıştır" '
      + 'penceresinde OIS olarak aç (önizleme, kaydetmek sizde)' }, 'Hepsine işlem gir');
    this.hedgeAll.addEventListener('click', () => this.bookHedges());
    this.trialBtn = h('button', { class: 'btn sm', type: 'button', id: 'pr-trial-btn', title: 'DV01 Risk\'in kovaları + bu işlem: önce / sonra '
      + 'toplam DV01, VaR, PPK karar riski - hiçbir şey kaydedilmez' }, 'Pozisyona ekle (deneme)');
    this.trialBtn.addEventListener('click', () => this.openTrial());
    this.hedgeBody = h('div', { class: 'body', id: 'pr-hedge-body' });
    this.hedgeNote = foldable('pr-hedge-note');
    this.hedgePanel = h('section', { class: 'panel hidden', id: 'pr-hedge-panel' },
      h('header', null, h('h2', null, 'Bu işlemi hedge\'le'), this.hedgeAll, this.trialBtn), this.hedgeBody, this.hedgeNote.el);
    this.trialBody = h('div', { class: 'body', id: 'pr-trial' });
    const trialClose = h('button', { class: 'btn sm', type: 'button', id: 'pr-trial-close', title: 'Kapat' }, '×');
    trialClose.addEventListener('click', () => { this.trialOpen = false; this.trialPanel.classList.add('hidden'); });
    this.trialPanel = h('section', { class: 'panel hidden', id: 'pr-trial-panel' },
      h('header', null, h('h2', null, 'Pozisyona ekle (deneme) · DV01 Risk + bu işlem'), trialClose), this.trialBody,
      (this.trialNote = foldable('pr-trial-note')).el);
    this.schedBody = h('div', { class: 'body' }, waiting());
    this.schedTitle = h('h2', null, 'Ödeme takvimi');
    this.schedPanel = h('section', { class: 'panel fit', id: 'pr-schedule-panel' }, h('header', null, this.schedTitle), this.schedBody);
    this.notes = h('div', { class: 'body pr-notes', id: 'pr-notes' });
    this.notesPanel = h('section', { class: 'panel wide', id: 'pr-notes-panel' }, h('header', null, h('h2', null, 'Konvansiyonlar ve hesap')), this.notes);
    // the instrument's numbers - the tiles, the schedule - and Toplu fiyatlama in one column beside the DV01 buckets: the
    // bulk list on the first screen (the desk's layout review, 27.11.2026: "Hepsini yap")
    this.result = h('div', { class: 'pr-result', id: 'pr-result' },
      h('section', { class: 'panel wide pr-summary' }, h('div', { class: 'pad' }, h('div', { class: 'pr-headline' }, this.head, this.tradeBtn), this.tiles)),
      this.schedPanel);
    // Toplu fiyatlama: a list of lines priced as the instrument above, off the same curves (its own errors line by line)
    this.bulkIn = h('textarea', { id: 'pr-bulk', class: 'inp pr-bulk-in', rows: '6', spellcheck: 'false', autocomplete: 'off' });
    this.bulkDirty = false;                   // (typed and not sent yet: a refresh leaves it alone)
    this.bulkIn.addEventListener('input', () => { this.bulkDirty = true; });
    this.bulkIn.addEventListener('change', () => this.sendBulk());
    this.bulkIn.addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); this.sendBulk(); } });
    const run = h('button', { type: 'button', class: 'btn primary', id: 'pr-bulk-run', title: 'Satırları fiyatla (Ctrl+Enter)' }, 'Fiyatla');
    run.addEventListener('click', () => this.sendBulk());
    this.bulkBook = h('button', { type: 'button', class: 'btn sm', id: 'pr-bulk-book', title: 'Fiyatlanan satırları Günlük İşlemler\'in "Excel\'den '
      + 'yapıştır" penceresinde aç (önizleme; kaydetmek sizde) - tek satır için satırdaki "İşleme al"' }, 'Tümünü işleme al');
    this.bulkBook.addEventListener('click', () => this.bookBulk());
    this.bulkHint = h('div', { class: 'muted small', id: 'pr-bulk-hint' });
    this.bulkInfo = h('span', { class: 'muted', id: 'pr-bulk-info' });
    this.bulkBody = h('div', { class: 'body', id: 'pr-bulk-body' });
    this.bulkNote = foldable('pr-bulk-note');
    this.bulkPanel = h('section', { class: 'panel wide', id: 'pr-bulk-panel' },
      h('header', null, h('h2', null, 'Toplu fiyatlama'), this.bulkInfo, this.bulkBook),
      h('div', { class: 'pr-bulk-form' }, this.bulkIn, h('div', { class: 'pr-bulk-side' }, run, this.bulkHint)),
      this.bulkBody, this.bulkNote.el);
    // F: the forward card - every source at the value date, the ladder, the quote (an FX forward only)
    this.buildCard();
    const left = h('div', { class: 'pr-left', id: 'pr-left' }, this.bucketPanel, this.hedgePanel, this.trialPanel);
    const main = h('div', { class: 'pr-main', id: 'pr-main' }, left,
      h('div', { class: 'pr-col', id: 'pr-col' }, this.result, this.bulkPanel));
    // C2: the quotes given and the hit ratio, the desk's (tto/quotelog.py)
    this.qlBody = h('div', { class: 'body', id: 'pr-quotelog' });
    this.qlPanel = h('section', { class: 'panel wide', id: 'pr-quotelog-panel' },
      h('header', null, h('h2', null, 'Kotasyon defteri · verilen kotalar ve isabet (müşteri / ürün)')), this.qlBody);
    this.host.appendChild(h('div', { class: 'panels pricing', id: 'pricing' }, form, this.loading, this.card, main, this.qlPanel, this.notesPanel));
    this.qlog = mountQuoteLog(this.qlBody, this.ctx, { id: 'pr-ql', days: 1 });
  }

  buildCard() {
    this.cardInfo = h('span', { class: 'muted', id: 'pr-fwd-info' });
    this.cardSources = h('div', { class: 'body', id: 'pr-fwd-sources-box' }, waiting());
    this.clientIn = h('input', { type: 'text', class: 'inp', id: 'pr-fwd-client', placeholder: 'müşteri (isabet için)', autocomplete: 'off',
      spellcheck: 'false', maxlength: '40' });
    const keepClient = () => {
      const f = this.data && this.data.inputs && this.data.inputs.by.fx;
      if (f && (f.client || '') === this.clientIn.value.trim()) return;
      this.send({ client: this.clientIn.value.trim() });
    };
    this.clientIn.addEventListener('change', keepClient);
    this.clientIn.addEventListener('keydown', (e) => { if (e.key === 'Enter') { e.preventDefault(); keepClient(); } });
    const btn = (id, label, title, fn, cls) => {
      const b = h('button', { class: 'btn' + (cls ? ' ' + cls : ''), type: 'button', id, title }, label);
      b.addEventListener('click', fn);
      return b;
    };
    this.copyBtn = btn('pr-fwd-copy', 'Kotasyon kopyala', 'Seçili kaynağın bid / ask kotasyonunu panoya kopyala ve kotasyon defterine yaz (açık)',
      () => this.quoteAction('open'), 'primary');
    this.doneBtn = btn('pr-fwd-done', 'Done → Günlük İşlemler', 'Müşteri işlem yaptı: kota done olur, Günlük İşlemler\'in FX forward formu '
      + 'kotlanan seviyeden dolu açılır (parite, yön, tutar, valör, fiyat)', () => this.quoteAction('done'));
    this.notDoneBtn = btn('pr-fwd-notdone', 'Done değil', 'Müşteri işlem yapmadı: kota "done değil" olur (isabet oranına girer)',
      () => this.quoteAction('not_done'));
    this.cardStatus = h('span', { class: 'muted', id: 'pr-fwd-status' });
    this.ladderBody = h('div', { class: 'body', id: 'pr-fwd-ladder-box' });
    this.cardNote = foldable('pr-fwd-note');
    // the sources and the quote's buttons on the left, the ladder beside them (one screen at 1600 px; a narrow window
    // puts the ladder under them)
    this.card = h('section', { class: 'panel wide hidden', id: 'pr-fwd-card' },
      h('header', null, h('h2', null, 'Forward · kaynaklar bu valörde'), this.cardInfo),
      h('div', { class: 'pr-fwd-grid' },
        h('div', { class: 'pr-fwd-left' }, this.cardSources,
          h('div', { class: 'pr-fwd-actions', id: 'pr-fwd-actions' }, field('Müşteri', this.clientIn), this.copyBtn, this.doneBtn, this.notDoneBtn),
          h('div', { class: 'pr-fwd-status' }, this.cardStatus), this.cardNote.el),
        h('div', { class: 'pr-fwd-right' },
          h('div', { class: 'pr-fwd-sub' }, 'Vade merdiveni · valörün iki yanındaki vadeler ve aradaki PPK toplantıları (mid; bid / ask ipucunda)'),
          this.ladderBody)));
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

  clearHash() {
    try { window.history.replaceState(null, '', '#/fiyatlama'); } catch (e) { /* ignore */ }
  }

  async load() {
    // an address with fields (Ctrl+K "fiyatla …", a link): they are typed in, then the page is priced
    const fields = hashFields(window.location.hash);
    if (fields) {
      this.clearHash();
      this.apply(await api.post('/api/pricing', fields));
      return;
    }
    this.apply(await api.get('/api/pricing'));
  }

  async refresh() {
    if (this.sending) return;
    const seq = ++this.seq;
    const d = await api.get('/api/pricing');
    if (seq === this.seq && !this.sending) this.apply(d);
    // (a refresh comes with every market tick: the quote log at most every 15 s - at once after a quote of this page)
    if (this.qlog && Date.now() - (this.qlogAt || 0) > 15000) {
      this.qlogAt = Date.now();
      this.qlog.refresh();
    }
  }

  async send(fields) {
    const seq = ++this.seq;
    this.sending = true;
    this.stamp.textContent = WAIT;
    try {
      const d = await api.post('/api/pricing', fields);
      if (seq === this.seq) this.apply(d);
    } catch (err) {
      errorToast(err);
      this.stamp.textContent = '';
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
    if (fx && document.activeElement !== this.clientIn) this.clientIn.value = f.client || '';
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
    this.loading.classList.add('hidden');
    if (d.inputs) this.fill(d.inputs);
    this.curveInfo.textContent = d.curve_text ? 'Eğriniz: ' + d.curve_text + ' (Ayarlar → Eğri interpolasyonu)' : '';
    this.stamp.textContent = new Date().toLocaleTimeString('tr-TR');
    this.errorLine.textContent = d.error || '';
    this.result.classList.toggle('stale', !!d.error);
    this.bucketPanel.classList.toggle('stale', !!d.error);
    this.notesPanel.classList.toggle('stale', !!d.error);
    this.card.classList.toggle('stale', !!d.error);
    this.hedgePanel.classList.toggle('stale', !!d.error);
    this.drawBulk(d);                         // (the lines have their own errors: priced whatever the instrument above says)
    const asset = (d.inputs && d.inputs.asset) || d.asset;
    this.card.classList.toggle('hidden', asset !== 'fx');
    this.hedgePanel.classList.remove('hidden');
    if (d.error || !d.label) {                // (the last numbers stay on the page, dimmed, under the message)
      if (!this.priced) this.unpriced(d.error || (d.available === false ? 'TRY eğrileri yok' : 'fiyatlanacak işlem yok'));
      return;
    }
    this.priced = true;
    this.drawHead(d);
    this.drawTiles(d);
    this.drawBuckets(d);
    this.drawSchedule(d);
    this.drawNotes(d);
    this.drawCard(d);
    this.drawHedges(d);
    // (the trial again when the instrument changed, else at most every 10 s: it evaluates DV01 Risk once more)
    const key = JSON.stringify([d.inputs, d.label]);
    if (this.trialOpen && (key !== this.trialKey || Date.now() - (this.trialAt || 0) > 10000)) this.loadTrial();
  }

  /** B7: no numbers yet and the inputs cannot be priced - each panel says so instead of staying empty. */
  unpriced(why) {
    const say = 'Fiyat yok: ' + why;
    clear(this.tiles).appendChild(waiting(say, 'pr-unpriced'));
    clear(this.bucketBody).appendChild(waiting(say));
    clear(this.schedBody).appendChild(waiting(say));
    clear(this.cardSources).appendChild(waiting(say));
    clear(this.ladderBody);
    clear(this.hedgeBody).appendChild(waiting(say));
  }

  drawHead(d) {
    clear(this.head);
    const when = serialDate(d.start) + ' → ' + serialDate(d.end) + ' · ' + num(d.days, 0) + ' gün';
    this.head.append(h('b', { id: 'pr-label' }, d.label + ' · ' + d.side), h('span', { class: 'muted' }, '  ' + when));
    const t = d.trade || {};
    this.tradeBtn.disabled = !(t.blotter || t.trades);
    this.tradeBtn.title = this.tradeBtn.disabled ? ((t.why || {}).blotter || 'işlem girilemiyor')
      : 'Fiyatlanan işlemi gir: ' + (t.level_from === 'fiyat' ? 'yazılan (ya da çözülen) fiyattan' : 'eğrinizin mid\'inden') + ' - form dolu açılır, kaydetmek sizde';
  }

  /** "İşlem gir ▾": Günlük İşlemler or Trades, the form filled with ``trade`` (tto/pricing.py ``trade_specs``). */
  tradeMenu(anchor, trade, label) {
    if (!trade) return;
    const r = anchor.getBoundingClientRect();
    const why = trade.why || {};
    const from = trade.level_from === 'fiyat' ? 'yazılan fiyattan' : 'mid\'den';
    menu(r.left, r.bottom + 2, [
      { header: 'İşlem gir (' + from + ') · ' + (label || '') },
      trade.blotter ? { id: 'pr-trade-blotter', label: 'Günlük İşlemler', action: () => this.ctx.openTrade(Object.assign(blotterSpec(trade.blotter),
        { said: 'İşlem Fiyatlama\'dan dolduruldu: kontrol edip kaydedin' })) }
        : { id: 'pr-trade-blotter', label: 'Günlük İşlemler · ' + (why.blotter || 'yok'), disabled: true },
      trade.trades ? { id: 'pr-trade-trades', label: 'Trades (izlenen işlemler)', action: () => fillTrades(this.ctx, trade.trades, trade.note).catch(errorToast) }
        : { id: 'pr-trade-trades', label: 'Trades · ' + (why.trades || 'yok'), disabled: true },
    ]);
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
    this.bucketNote.set((d.family === 'ois' ? 'OIS kovaları (masanınki): her kota +1 bp, eğri aynı yöntemle yeniden. '
      : 'Offshore eğrinin kotaları (FX swap ≤9A, XCCY 1Y–10Y): her kota +1 bp, eğri aynı yöntemle yeniden. ')
      + 'Kota: kovanın piyasa kotası - hedge\'in yapılacağı faiz (iki eğri de onu kendi vadesinde aynen verir). '
      + '+ = faizler yükselince kazanır.');
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

  // ------------------------------------------------------------------------------------------ the forward card (F)
  drawCard(d) {
    if (d.asset !== 'fx') return;
    const c = d.card;
    if (!c) { clear(this.cardSources).appendChild(waiting()); clear(this.ladderBody); return; }
    if (c.error) { clear(this.cardSources).appendChild(h('div', { class: 'errtxt pad', id: 'pr-fwd-error' }, c.error)); clear(this.ladderBody); return; }
    const ccy = c.ccy;
    this.cardInfo.textContent = c.pair + ' · valör ' + serialDate(c.valor) + ' · ' + num(c.days, 0) + ' gün · spot ' + num(c.spot.bid, 4)
      + ' / ' + num(c.spot.ask, 4) + ' · ' + ccy + ' %' + num((c.ccy_rate || 0) * 100, 2) + ' · OIS eğrisi ' + c.curve + ' · ' + c.mode;
    const two = (q, digits, scale, signedDigits) => {
      if (!q) return '–';
      const f = (v) => (isNum(v) ? (signedDigits !== undefined ? signed(v * (scale || 1), signedDigits) : num(v * (scale || 1), digits)) : '–');
      if (!isNum(q.bid) && !isNum(q.ask)) return isNum(q.mid) ? f(q.mid) + ' (mid)' : '–';
      return f(q.bid) + ' / ' + f(q.ask);
    };
    const t = h('table', { class: 'plain', id: 'pr-fwd-sources' },
      h('tr', null, h('th', { class: 'l' }, 'Kaynak'), h('th', null, 'TRY % (bid / ask)'), h('th', null, 'Outright'), h('th', null, 'Puan'),
        h('th', { title: 'Kaynağın puanı − seçili kaynağın (bid / ask; yalnız mid olanda mid)' }, 'Fark (puan)'),
        h('th', { title: 'Kaynağın TRY faizi − seçili kaynağın, bp' }, 'Fark (bp)'), h('th', { class: 'l' }, '')));
    for (const s of c.sources) {
      const on = s.id === c.picked;
      const tr = h('tr', { class: 'pr-src' + (on ? ' on' : '') + (s.available ? '' : ' soft') });
      tr.dataset.source = s.id;
      const mark = h('td', { class: 'l', title: s.note }, (on ? '● ' : '○ ') + s.name);
      tr.appendChild(mark);
      if (!s.available) {
        tr.appendChild(h('td', { class: 'l muted', colspan: '6' }, s.why || 'yok'));
      } else {
        const tip = (q, d2, scale) => (q && isNum(q.mid) ? 'mid ' + num(q.mid * (scale || 1), d2) : '');
        tr.appendChild(h('td', { title: tip(s.try, 3, 100) }, two(s.try, TRY_DIGITS, 100)));
        tr.appendChild(h('td', { title: tip(s.fwd, 4) }, two(s.fwd, 4)));
        tr.appendChild(h('td', { title: tip(s.pts, 1) }, two(s.pts, 0)));
        const diff = s.diff || null;
        const dd = (k) => (diff ? (isNum(diff[k].bid) || isNum(diff[k].ask) ? diff[k] : { mid: diff[k].mid }) : null);
        tr.appendChild(h('td', null, on ? '' : two(dd('pts'), 0, 1, 0)));
        tr.appendChild(h('td', null, on ? '' : two(dd('bp'), 1, 1, 1)));
        // what the row stands on, short (the whole in its tip): the matrix's row or the spread, the contract, a mid only
        let extra = '';
        let more = '';
        if (s.id === 'ois' && s.row) { extra = s.row + ' satırı'; more = 'FORWARD KOTASYON\'un ' + s.row + ' satırı, yazdıklarınız dahil'; }
        else if (s.id === 'ois' && s.spread) { extra = 'spread ' + num(s.spread.bid, 0) + ' / ' + num(s.spread.ask, 0); more = 'OIS (' + c.curve + ') + spread bid / ask, bp (' + c.mode + ')'; }
        else if (s.id === 'viop' && s.contract) {
          extra = s.contract.name + ' (' + signed(s.gap, 0) + ' g)';
          more = s.contract.name + ' · vade ' + serialDate(s.contract.expiry) + ' (valöre ' + signed(s.gap, 0) + ' gün) · fiyat ' + num(s.contract.px_bid, 3) + ' / '
            + num(s.contract.px_ask, 3) + ' · ima TRY ' + num(s.contract.try_bid * 100, 2) + ' / ' + num(s.contract.try_ask * 100, 2);
        } else if (s.id === 'off' && !s.implied) { extra = 'eğri mid'; more = 'FX swap ima bu valöre ulaşmıyor: bid / ask yok, Fiyatlama\'nın offshore eğrisinin mid\'i'; }
        tr.appendChild(h('td', { class: 'l muted small', title: more || null }, extra));
        tr.addEventListener('click', () => { if (!on) this.send({ source: s.id }); });
        tr.title = on ? 'Seçili kaynak: kotasyon ve Done bunun fiyatıyla' : 'Tıklayınca seçili kaynak bu olur';
      }
      t.appendChild(tr);
    }
    clear(this.cardSources).appendChild(t);
    const q = c.sources.find((s) => s.id === c.picked) || {};
    const lvl = c.deal.level;
    this.doneBtn.disabled = !isNum(lvl);
    this.doneBtn.title = isNum(lvl) ? 'Müşteri işlem yaptı: kota done olur, Günlük İşlemler\'in FX forward formu dolu açılır - '
      + (c.deal.side === 'AL' ? ccy + ' alış, bid' : ccy + ' satış, ask') + ' ' + num(lvl, 4) + ' (' + q.name + ')' : 'Seçili kaynağın fiyatı yok';
    this.drawLadder(c);
    this.cardNote.set(c.sources.map((s) => s.name + ': ' + s.note).join('  ·  '));
    if (this.lastQuote && this.lastQuote.key !== this.quoteKey(d)) this.cardStatus.textContent = '';
  }

  drawLadder(c) {
    const ids = ['ret', 'ois', 'off', 'viop'];
    const names = c.sources_text || {};
    const head = [h('th', { class: 'l' }, 'Vade'), h('th', null, 'Valör'), h('th', null, 'Gün')];
    for (const s of ids) head.push(h('th', { title: names[s] + ': TRY faizi (ACT/360 basit), mid' }, (names[s] || s) + ' %'), h('th', null, 'puan'));
    const t = h('table', { class: 'plain', id: 'pr-fwd-ladder' }, h('tr', null, ...head));
    for (const r of c.ladder) {
      const kind = r.kinds.includes('valor') ? 'valor' : r.kinds.includes('mpc') ? 'mpc' : 'tenor';
      const tr = h('tr', { class: 'pr-lad ' + kind });
      tr.dataset.kind = kind;
      tr.dataset.date = String(r.date);
      const tip = r.mpc ? r.mpc + (isNum(r.step) ? ' · ima adım ' + signed(r.step, 1) + ' bp' : '') : '';
      tr.append(h('td', { class: 'l', title: tip }, r.label + (r.viop ? ' · VİOP ' + r.viop : '')), h('td', null, serialDate(r.date)), h('td', null, num(r.days, 0)));
      for (const s of ids) {
        const v = r.by[s];
        if (!v) { tr.append(h('td', { class: 'soft' }, '–'), h('td', { class: 'soft' }, '–')); continue; }
        const bt = (q, n, scale) => (isNum(q.bid) ? 'bid / ask ' + num(q.bid * scale, n) + ' / ' + num(q.ask * scale, n) : '');
        tr.append(h('td', { title: bt(v.try, 2, 100) }, isNum(v.try.mid) ? num(v.try.mid * 100, TRY_DIGITS) : '–'),
          h('td', { title: bt(v.pts, 0, 1) }, isNum(v.pts.mid) ? num(v.pts.mid, 0) : '–'));
      }
      t.appendChild(tr);
    }
    clear(this.ladderBody).appendChild(t);
  }

  quoteKey(d) {
    const c = (d && d.card) || {};
    return [d && d.label, c.picked, c.deal && c.deal.side, c.deal && c.deal.amount, c.deal && c.deal.level].join('|');
  }

  /** "Kotasyon kopyala" (status open), "Done → Günlük İşlemler" (done: the form filled at the quoted level) or "Done
   * değil": the quote logged (tto/quotelog.py) - the last one copied of the same card updated, else a new one. */
  async quoteAction(status) {
    const d = this.data;
    if (!d || !d.card || d.card.error) return;
    const client = this.clientIn.value.trim();
    const key = this.quoteKey(d);
    let quote = null;
    try {
      if (status === 'open' || !this.lastQuote || this.lastQuote.key !== key) {
        const res = await api.post('/api/pricing/quote', { client, language: quoteLang(), status });
        quote = res.quote;
        if (status === 'open') {
          const ok = await copyText(res.text, 'Kotasyon kopyalandı · kota #' + res.id + ' (açık)');
          if (!ok) toast('Panoya kopyalanamadı: kota #' + res.id + ' kotasyon defterinde', 'warn');
        }
        this.lastQuote = { id: res.id, key, quote };
      } else {
        quote = await setQuoteStatus(this.lastQuote.id, Object.assign({ status }, client ? { client } : {}));
        if (!quote) return;
        this.lastQuote.quote = quote;
      }
    } catch (err) {
      errorToast(err);
      return;
    }
    const word = { open: 'açık', done: 'done', not_done: 'done değil' }[status];
    this.cardStatus.textContent = 'Kota #' + quote.id + ' · ' + word + (quote.client ? ' · ' + quote.client : '') + ' · ' + (quote.levels && quote.levels.text || '');
    if (this.qlog) this.qlog.refresh();
    if (status === 'done') {
      const spec = tradeOfQuote(quote);
      if (spec) this.ctx.openTrade(spec);
      else toast('Kota done; işlem formu doldurulamadı (seviye yok)', 'warn');
    } else if (status === 'not_done') {
      toast('Kota #' + quote.id + ': done değil', 'ok');
    }
  }

  // ------------------------------------------------------------------------------------------ hedge (C3)
  drawHedges(d) {
    const hd = d.hedges;
    const body = clear(this.hedgeBody);
    this.hedgeRows = [];
    if (!hd) { body.appendChild(waiting()); return; }
    this.hedgeNote.set(hd.text || '');
    const rows = (hd.rows || []).filter((r) => !r.error && r.nominal > 0);
    this.hedgeAll.disabled = !rows.length;
    this.trialBtn.disabled = false;
    if (hd.family !== 'ois') { body.appendChild(h('div', { class: 'muted pad', id: 'pr-hedge-none' }, hd.text)); return; }
    if (!(hd.rows || []).length) { body.appendChild(h('div', { class: 'muted pad', id: 'pr-hedge-none' }, 'Hedge edilecek DV01 yok.')); return; }
    const t = h('table', { class: 'plain', id: 'pr-hedges' },
      h('tr', null, h('th', { class: 'l' }, 'Kova'), h('th', null, 'Kota'), h('th', null, 'Kova DV01 ($)'), h('th', { class: 'l' }, 'Hedge'),
        h('th', null, 'Nominal (TL)'), h('th', null, 'Hedge DV01 ($)'), h('th', null, 'Kalan ($)'), h('th', null, '')));
    for (const r of hd.rows) {
      const tr = h('tr');
      tr.dataset.bucket = r.bucket;
      if (r.error) {
        tr.append(h('td', { class: 'l' }, r.bucket), h('td', { class: 'l errtxt', colspan: '7' }, r.error));
        t.appendChild(tr);
        continue;
      }
      const go = h('button', { class: 'btn sm', type: 'button', title: 'Bu hedge\'i Günlük İşlemler\'de aç (form dolu, kaydetmek sizde)' }, 'İşlem gir');
      go.addEventListener('click', () => this.ctx.openTrade({ kind: 'ois', strategy: 'outright', side: r.side, tenors: [r.tenor],
        level: rateText(r.quote), size: num(r.nominal, 0, false), sizeMode: 'nominal', note: 'Fiyatlama hedge · ' + d.label,
        said: 'Hedge Fiyatlama\'dan dolduruldu: kontrol edip kaydedin' }));
      tr.append(h('td', { class: 'l' }, r.bucket), h('td', null, isNum(r.quote) ? pct(r.quote, TRY_DIGITS) : '–'),
        h('td', { class: tone(r.dv01, 0) === 'pos' ? 'buy' : 'sell' }, signed(r.dv01, 0)),
        h('td', { class: 'l' }, r.side + ' ' + r.tenor), h('td', null, num(r.nominal, 0)), h('td', null, signed(r.hedge_dv01, 0)),
        h('td', null, signed(r.left, 0)), h('td', null, go));
      this.hedgeRows.push(r);
      t.appendChild(tr);
    }
    t.appendChild(h('tr', { class: 'pkg', id: 'pr-hedges-total' }, h('td', null, 'Kalan toplam'), h('td', { colspan: '5' }, ''),
      h('td', null, signed(hd.left, 0)), h('td', null, '')));
    body.appendChild(t);
  }

  /** "Hepsine işlem gir": every hedge into Günlük İşlemler's "Excel'den yapıştır" (OIS), the preview's to save. */
  bookHedges() {
    const d = this.data;
    const rows = (this.hedgeRows || []).filter((r) => r.nominal > 0);
    if (!d || !rows.length) return;
    const lines = [['Yön', 'Vade', 'Faiz', 'Nominal', 'Not'].join('\t')].concat(rows.map((r) => [r.side === 'PAY' ? 'B' : 'S', r.tenor,
      rateText(r.quote) + '%', num(r.nominal, 0), 'Fiyatlama hedge · ' + d.label].join('\t')));
    openBulk({ ctx: this.ctx }, { kind: 'ois', text: lines.join('\n'), said: d.label + ' için ' + rows.length + ' hedge (Fiyatlama · Bu işlemi '
      + 'hedge\'le): her kovanın karşı TRY OIS\'i, kovanın kotasından. Önizlemeye bakıp kaydedin.' });
  }

  // ------------------------------------------------------------------------------------------ Pozisyona ekle (deneme)
  openTrial() {
    this.trialOpen = true;
    this.trialPanel.classList.remove('hidden');
    clear(this.trialBody).appendChild(waiting());
    this.loadTrial();
    this.trialPanel.scrollIntoView({ block: 'nearest' });
  }

  async loadTrial() {
    if (this.trialBusy) return;
    this.trialBusy = true;
    this.trialAt = Date.now();
    this.trialKey = this.data ? JSON.stringify([this.data.inputs, this.data.label]) : null;
    try {
      const t = await api.get('/api/pricing/trial');
      if (this.trialOpen) this.drawTrial(t);
    } catch (err) {
      clear(this.trialBody).appendChild(h('div', { class: 'errtxt pad' }, err.message));
    } finally {
      this.trialBusy = false;
    }
  }

  drawTrial(t) {
    const body = clear(this.trialBody);
    if (!t.available) { body.appendChild(h('div', { class: 'muted pad', id: 'pr-trial-none' }, t.error || 'deneme yok')); return; }
    this.trialNote.set(t.text);
    const tl = (v) => (isNum(v) ? num(v, 0) : '–');
    body.appendChild(h('div', { class: 'quote pr-tiles', id: 'pr-trial-tiles' },
      tile('İşlem · ' + t.label + ' · ' + t.side, signed(t.deal_total, 0) + ' TL/bp', { title: 'Kolon: ' + t.columns + ' · USDTRY ' + num(t.usdtry, 4) }),
      tile('Pozisyon toplam DV01 (TL/bp) önce', signed(t.total.before, 0), { id: 'pr-trial-before' }),
      tile('… sonra', signed(t.total.after, 0), { id: 'pr-trial-after', tone: tone(t.total.after, 0) })));
    const v = h('table', { class: 'plain', id: 'pr-trial-var' }, h('tr', null, h('th', { class: 'l' }, 'VaR'), h('th', null, 'DV01 önce'),
      h('th', null, 'DV01 sonra'), h('th', null, 'VaR önce (TL)'), h('th', null, 'VaR sonra (TL)')));
    for (const r of t.var) {
      v.appendChild(h('tr', null, h('td', { class: 'l' }, r.name), h('td', null, signed(r.dv01, 0)), h('td', null, signed(r.dv01_after, 0)),
        h('td', null, tl(r.var)), h('td', null, tl(r.var_after))));
    }
    body.appendChild(v);
    if (t.var.every((r) => !isNum(r.var_after)) && t.var_status) body.appendChild(h('div', { class: 'muted pad' }, 'VaR: ' + t.var_status));
    const p = h('table', { class: 'plain', id: 'pr-trial-ppk' }, h('tr', null, h('th', { class: 'l' }, 'PPK karar riski'), h('th', null, 'Tarih'),
      h('th', null, 'Karar riski önce'), h('th', null, 'sonra'), h('th', null, '25 bp sürpriz P&L önce'), h('th', null, 'sonra')));
    for (const r of t.ppk.slice(0, 9)) {
      p.appendChild(h('tr', null, h('td', { class: 'l' }, r.name), h('td', null, serialDate(r.date)),
        h('td', null, isNum(r.decision) ? signed(r.decision, 0) : '–'), h('td', null, isNum(r.decision_after) ? signed(r.decision_after, 0) : '–'),
        h('td', null, signed(r.pnl25, 0)), h('td', null, signed(r.pnl25_after, 0))));
    }
    body.appendChild(p);
    const b = h('table', { class: 'plain', id: 'pr-trial-buckets' }, h('tr', null, h('th', { class: 'l' }, 'DV01 Risk kovası'), h('th', null, 'Önce'),
      h('th', null, 'Bu işlem'), h('th', null, 'Sonra')));
    for (const r of t.buckets) {
      if (Math.abs(r.before) < 0.5 && Math.abs(r.deal) < 0.5) continue;
      const tr = h('tr', null, h('td', { class: 'l' }, r.name), h('td', null, signed(r.before, 0)), h('td', null, signed(r.deal, 0)), h('td', null, signed(r.after, 0)));
      tr.dataset.bucket = r.name;
      b.appendChild(tr);
    }
    body.appendChild(b);
    body.appendChild(h('div', { class: 'muted pad', id: 'pr-trial-saved' }, 'Hiçbir şey kaydedilmedi: DV01 Risk sayfası ve girdileriniz aynı.'));
  }

  // ------------------------------------------------------------------------------------------ Toplu fiyatlama
  /** "Tümünü işleme al": the priced lines into "Excel'den yapıştır" (an FX forward's as FX Forward, a spot TRY OIS's as OIS;
   * an FRA or a forward start one by one with its own "İşleme al", an XCCY never). */
  bookBulk() {
    const b = this.data && this.data.bulk;
    if (!b) return;
    const rows = b.rows.filter((r) => !r.error && r.trade && r.trade.blotter);
    if (b.asset === 'fx') {
      const lines = [['Parite', 'Yön', 'Tutar', 'Valör', 'Forward kur', 'Not'].join('\t')].concat(rows.map((r) => {
        const s = r.trade.blotter;
        return [s.pair, s.dir, num(s.amount, 0), s.date, num(s.value, 4), r.trade.note].join('\t');
      }));
      if (!rows.length) { toast('İşleme alınacak satır yok', 'warn'); return; }
      openBulk({ ctx: this.ctx }, { kind: 'fwd', text: lines.join('\n'), said: 'Toplu fiyatlama\'dan ' + rows.length + ' FX forward (her satırın '
        + (rows.some((r) => r.trade.level_from === 'fiyat') ? 'yazılan fiyatı, yoksa ' : '') + 'mid\'i). Önizlemeye bakıp kaydedin.' });
      return;
    }
    const outright = rows.filter((r) => r.trade.blotter.strategy === 'outright');
    if (!outright.length) { toast(rows.length ? 'FRA / ileri başlangıçlı satırlar tek tek "İşleme al" ile girilir' : 'İşleme alınacak satır yok', 'warn'); return; }
    const dv = outright[0].trade.blotter.sizeMode === 'dv01';
    const lines = [['Yön', 'Vade', 'Faiz', dv ? 'DV01 USD' : 'Nominal', 'Not'].join('\t')].concat(outright.map((r) => {
      const s = r.trade.blotter;
      return [s.side === 'PAY' ? 'B' : 'S', s.tenors[0], rateText(s.level) + '%', num(s.size, 0), r.trade.note].join('\t');
    }));
    const left = rows.length - outright.length;
    openBulk({ ctx: this.ctx }, { kind: 'ois', text: lines.join('\n'), said: 'Toplu fiyatlama\'dan ' + outright.length + ' TRY OIS'
      + (left ? ' (' + left + ' FRA / ileri başlangıçlı satır tek tek "İşleme al" ile)' : '') + '. Önizlemeye bakıp kaydedin.' });
  }

  /** Toplu fiyatlama: one row a line - the mid on both curves, the annuity (an FX forward's points), the size and its
   * DV01 and, with a price on the line, the NPV (or the rate an NPV / upfront gives) - or the line's own error; and its
   * "İşleme al". */
  drawBulk(d) {
    const b = d.bulk;
    const body = clear(this.bulkBody);
    if (!b) {
      this.bulkInfo.textContent = '';
      this.bulkHint.textContent = '';
      this.bulkNote.set('');
      this.bulkBook.disabled = true;
      return;
    }
    const fx = b.asset === 'fx';
    const [m1, m2] = b.methods;
    const asset = (ASSETS.find((a) => a[0] === b.asset) || [0, b.asset])[1];
    const size = b.size_kind === 'dv01' ? 'DV01 ' + b.size + ' $' : (fx ? 'tutar ' : 'nominal ') + b.size;
    this.bulkInfo.textContent = asset + ' · ' + b.side + ' · ' + size + ' · fiyat tipi ' + b.kind_text + ' · ' + (b.family === 'off' ? 'offshore' : 'OIS')
      + ' eğrisi, ' + METHOD[m1] + ' önde';
    this.bulkHint.textContent = b.hint;
    this.bulkNote.set(b.text);
    this.bulkBook.disabled = b.asset === 'xccy' || !b.rows.some((r) => !r.error);
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
    heads.push(['İşlem', 'l']);
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
      // İşleme al (A1): the line into Günlük İşlemler's form - at its price, else at the mid
      const spec = r.trade && r.trade.blotter;
      const acts = h('td', { class: 'l' });
      if (spec) {
        const go = h('button', { class: 'btn sm', type: 'button', title: 'Satırı Günlük İşlemler\'de aç (' + (r.trade.level_from === 'fiyat' ? 'satırın fiyatından' : 'mid\'den')
          + '; form dolu, kaydetmek sizde)' }, 'İşleme al');
        go.dataset.act = 'book';
        go.addEventListener('click', () => this.ctx.openTrade(Object.assign(blotterSpec(spec, r.trade.note),
          { said: 'Toplu fiyatlama satırı dolduruldu: kontrol edip kaydedin' })));
        acts.appendChild(go);
      } else if (r.trade) {
        acts.appendChild(h('span', { class: 'muted small', title: (r.trade.why || {}).blotter || '' }, '–'));
      }
      tr.appendChild(acts);
      t.appendChild(tr);
    });
    body.appendChild(t);
    if (b.left_out) body.appendChild(h('div', { class: 'muted pad' }, b.left_out + ' satır daha var: en çok ' + b.rows.length + ' satır fiyatlanır.'));
  }

  destroy() {
    window.removeEventListener('hashchange', this.onHash);
    if (this.qlog) this.qlog.destroy();
  }
}
