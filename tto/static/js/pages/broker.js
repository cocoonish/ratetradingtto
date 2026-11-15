// Broker Chat: what the brokers write about TRY rates, pasted or typed as it stands.  Every line is read
// (outright / spread / fly / FRA, one side or two, a level without its big figure, trades, refs ...), kept with
// its time and sender, and shown twice: as a board of where every instrument stands - next to the dashboard's
// own curve - and as the chat in the order it was said.  Shared by every user, like the blotter.
import { api } from '../api.js';
import { h, clear, toast, errorToast, confirmDialog, debounce, modal } from '../ui.js';
import { Grid, plainData, copyGrid } from '../grid.js';
import { num, isoToTr } from '../format.js';

const KIND = { outright: 'Outright', spread: 'Spread', fly: 'Fly', fra: 'FRA', fwd: 'Forward', switch: 'Switch' };
const EVENT = { quote: 'Kota', trade: 'İşlem', ref: 'Ref', interest: 'İlgi', level: 'Seviye', note: 'Not', text: 'Metin' };
const FLAG = {
  abbr: ['tamamlandı', '', 'Büyük rakam yazılmamış ("90 bid", "90/10"): kotanın öbür tarafından, bu enstrümanın son seviyesinden ya da eğriden tamamlandı'],
  ambiguous: ['belirsiz', 'warn', 'İki türlü okunabilir ("36": 35,36 mı 36,00 mı?; referans iki büyük rakamın ortasında) – yakın olan alındı; yanlışsa seviyeyi tam yazın'],
  'no-ref': ['büyük rakam yok', 'warn', 'Seviyeyi tamamlayacak bir referans yok (bu enstrüman için ne önceki kota, ne eğri, ne tarihçede kapanış) – yazıldığı gibi alındı'],
  'side?': ['taraf?', 'warn', 'Eğik çizgi ile kelime uyuşmuyor ("12/ offer") – eğik çizgiye uyuldu'],
  crossed: ['bid > ask', 'warn', 'Bid ask\'ten yüksek okundu (getiriyle kotede: bid getirisi ask\'inkinden düşük)'],
  standing: ['kotadan', '', 'Mesajda fiyat yok ("taken", "given"): o an duran offer / bid seviyesi alındı'],
  'bond?': ['kâğıt?', 'warn', 'O ay için birden çok kâğıt var ("mar28": 08.03.28 ve 15.03.28; "jan30": 02.01.30 FRN ve 09.01.30 TLREF): fiyatı ekrandakine en yakın olan, ekran yoksa kuponu en yüksek olan (gösterge) alındı – yanlışsa tarihi ya da türü yazın (15/3/28, "jan30 tlref", "jan30 frn")'],
  near: ['yakın kâğıttan', 'warn', 'Bu kâğıdın ne ekran fiyatı ne önceki kotası var: büyük rakamı vadesi en yakın aynı tür kâğıttan (TLREF\'ten TLREF, FRN\'den FRN, bonodan bono) alındı'],
  nobond: ['kâğıt yok', 'warn', 'Masanın DİBS listesinde bu vadede bu türden kâğıt yok (tür yazılmışsa yalnız o tür aranır: "mar28 zc", "dec26 tlref").'],
  notfixed: ['sabit kuponlu değil', '', 'Ay ve yıl tek başına önce sabit kuponlu kâğıt demektir; bu ayda sabit kuponlu olmadığı için ayın öbür kâğıdı alındı '
    + '(önce TLREF / FRN, sonra TÜFE, sonra bono / kuponsuz; birden çoksa ekrandaki fiyata en yakın olan) – yanlışsa türü yazın ("jun29 cpi", "jan30 frn").'],
  par: ['100\'e göre', 'warn', 'Bu kâğıdın ne ekran fiyatı ne önceki kotası var, yakınında fiyatı bilinen aynı tür kâğıt da yok: TLREF / FRN / TÜFE kâğıdı 100 civarı sayılarak tamamlandı – yanlışsa fiyatı tam yazın'],
};

/** What a flag says, with what it was about (the bond a big figure was taken from). */
function flagTip(q, f) {
  const x = FLAG[f];
  if (!x) return f;
  return x[0] + ': ' + x[2] + (f === 'near' && q.ref_from ? ' (' + q.ref_from + ')' : '');
}

/** An instrument's name: "18M", "XCCY 2Y", "DİBS 15.03.28 · T1" (a bond with its value date when said). */
function instText(q) {
  if (q.product === 'OIS') return q.label;
  if (q.product === 'DIBS') return 'DİBS ' + q.label + (q.settle ? ' · ' + q.settle : '');
  return q.product + ' ' + q.label;
}

// ---------------------------------------------------------------- a line as a trade (Günlük İşlemler)
/** Günlük İşlemler's sides of an OIS strategy: [the buy (paying the rate, the spread or the fly's body), the sale]. */
const OIS_SIDES = {
  outright: [['PAY', 'PAY'], ['RECEIVE', 'RECEIVE']],
  fra: [['PAY', 'PAY'], ['RECEIVE', 'RECEIVE']],
  spread: [['STEEPENER', 'STEEPENER (spread öde)'], ['FLATTENER', 'FLATTENER (spread al)']],
  fly: [['PAY GÖVDE', 'PAY GÖVDE (fly öde)'], ['REC GÖVDE', 'REC GÖVDE (fly al)']],
};

/** What Günlük İşlemler books a chat line as: 'ois', 'fwd' (an FX swap's points, one dated tenor), 'bond' - or
 * null (a product without a form there: cross currency, IRS, O/N - T/N swaps). */
export function tradeKind(q) {
  if (!q || !q.ok) return null;
  if (q.product === 'OIS' && OIS_SIDES[q.kind === 'fwd' ? 'fra' : q.kind]) return 'ois';
  if (q.product === 'FX' && q.kind === 'outright' && /^\d+[WMY]$/i.test(String((q.tenors || [])[0] || ''))) return 'fwd';
  if (q.product === 'DIBS' && q.kind !== 'switch') return 'bond';
  return null;
}

/** The levels of a line one deals at: [[key, caption, value]] - the trade's, the bid, the ask. */
export function tradeLevels(q) {
  const out = [];
  if (q.event === 'trade' && typeof q.price === 'number') out.push(['price', 'İşlem', q.price]);
  if (typeof q.bid === 'number') out.push(['bid', 'Bid', q.bid]);
  if (typeof q.ask === 'number') out.push(['ask', 'Ask', q.ask]);
  if (!out.length && typeof q.price === 'number') out.push(['price', 'Seviye', q.price]);
  return out;
}

/** Our side at a level: true = we buy (pay the rate, pay the spread or the fly's body, buy the currency forward, buy
 * the bond), false = we sell, null = the line does not say.  Our own quote dealt on: its bid makes us the buyer, its
 * ask the seller; a broker's quote dealt on: we sell at its bid, buy at its ask; a trade: the offer lifted is a buy,
 * the bid hit a sale. */
export function tradeBuys(q, key) {
  if (key === 'bid') return q.party === 'biz';
  if (key === 'ask') return q.party !== 'biz';
  if (q.side === 'ask') return true;
  if (q.side === 'bid') return false;
  return null;
}

/** The words of the two sides, as Günlük İşlemler shows them: [buy, sell]. */
export function tradeSideNames(q) {
  const kind = tradeKind(q);
  if (kind === 'ois') return OIS_SIDES[q.kind === 'fwd' ? 'fra' : q.kind].map((x) => x[1]);
  if (kind === 'fwd') return ['Alış (USD al)', 'Satış (USD sat)'];
  return ['Alış', 'Satış'];
}

/** The trade to fill Günlük İşlemler with (``ctx.openTrade``): the line at one of its levels, on one side. */
export function tradeSpec(q, key, buy) {
  const kind = tradeKind(q);
  const lv = tradeLevels(q).find((x) => x[0] === key) || tradeLevels(q)[0];
  const text = lv ? level(lv[2], q.unit) : '';
  const note = ('Chat ' + [q.time, q.sender].filter(Boolean).join(' ') + ': ' + (q.raw || '')).slice(0, 160);
  const cpt = q.party === 'broker' ? (q.source || '') : '';
  const months = q.months || [];
  if (kind === 'ois') {
    const strategy = q.kind === 'fwd' ? 'fra' : q.kind;
    const pair = OIS_SIDES[strategy];
    const span = q.kind === 'fra' ? [months[0], months[1]] : (q.kind === 'fwd' ? [months[0], months[0] + months[1]] : null);
    return { kind: 'ois', strategy, side: buy === null ? null : pair[buy ? 0 : 1][0], tenors: q.tenors || [], months: span, level: text, note, cpt };
  }
  if (kind === 'fwd') {
    return { kind: 'fwd', pair: 'USDTRY', dir: buy === null ? null : (buy ? 'B' : 'S'), basis: 'SP', date: (q.tenors || [])[0] || '', value: text, note, cpt };
  }
  if (kind === 'bond') {
    return { kind: 'bond', dir: buy === null ? null : (buy ? 'B' : 'S'), instrument: q.isin || q.label || '',
      price: q.unit === 'px' ? text : '', note: q.unit === 'px' ? note : (note + ' · getiri ' + text).slice(0, 180) };
  }
  return null;
}

/** A bond's ISIN and what it is, for the tip of its name. */
function instTip(q) {
  if (q.product !== 'DIBS') return '';
  if (q.kind === 'switch') {
    return 'Switch: ' + (q.legs || []).map((l) => l.label + (l.isin ? ' (' + l.isin + ')' : '')).join(' → ')
      + ' · seviye: uzun vadelinin getirisi − kısanınki (bp)' + (q.alts && q.alts.length ? ' · öbür aday: ' + q.alts.join(', ') : '');
  }
  return [q.isin, q.alts && q.alts.length ? 'öbür aday: ' + q.alts.join(', ') : '', q.settle ? 'valör ' + q.settle.replace('T', 'T+') : '']
    .filter(Boolean).join(' · ');
}
const KNOWN = 'Bu satır zaten kayıtlı – yeniden eklenmez';
const PARTY = { biz: 'Biz', broker: 'Broker' };

/** A small Broker / Biz switch (an empty value: not said yet). */
function partySeg(value, onChange, id) {
  const el = h('div', { class: 'seg party', id: id || null });
  for (const [v, label, title] of [['broker', 'Broker', 'Broker\'ın fiyatı: piyasa'], ['biz', 'Biz', 'Bizim masanın fiyatı']]) {
    const b = h('button', { type: 'button', title }, label);
    b.dataset.v = v;
    b.classList.toggle('on', v === value);
    b.addEventListener('click', () => { for (const x of el.children) x.classList.toggle('on', x === b); onChange(v); });
    el.appendChild(b);
  }
  return el;
}

/** Whose a line is, as a short word: "Biz", or the broker's house (or "Broker"). */
function owner(q) {
  if (q.party === 'biz') return 'Biz';
  if (q.party === 'broker') return q.source || 'Broker';
  return q.source || '';
}
const EXAMPLES = [
  ['12:15:38 18m ois 35.03/35.23', 'outright, iki taraf'],
  ['12:10:07 18m ois /35.23 offer', 'yalnızca offer (bid yok)'],
  ['6m OIS 90 bid', 'büyük rakam tamamlanır: 35,90'],
  ['18m ois 10/14', '35,10 / 35,14'],
  ['6m ois 90/10', 'rakamı aşan kota: 35,90 / 36,10'],
  ['10:29:57 1y5y ois -64/-60', 'spread (5Y − 1Y, bp) – "v" yazılmasa da FRA değil spread'],
  ['1v5y ois -62 bid', 'spread, "v" ile'],
  ['12:18:04 2y3y4y ois 12/ bid', 'fly (2×3Y − 2Y − 4Y, bp)'],
  ['12:11:55 9x12m ois fra 33.80/34.10', 'FRA ("9x12" ya da "fra" kelimesi)'],
  ['18m ois taken at 14', 'işlem: offer 35,14\'ten alındı'],
  ['ref 18m ois offer', 'offer geri çekildi'],
  ['2yr ois 35.46, oco with 18m 35.14 offer', 'iki offer, biri öbürünü iptal eder'],
  ['1yr x 38.60/80', 'cross-currency ("x")'],
  ['t/n 375/90', 'FX swap puanı (o/n, t/n, s/n): 375 / 390 – yanında ima TRY faizi'],
  ['fx 2m 25 500/', 'FX swap 2M, puan (binler boşlukla ya da noktayla: 25.500)'],
  ['15/3/28 550/575', 'DİBS (vade tarihiyle): 100,550 / 100,575 – rakam ekran fiyatından'],
  ['mar28 .400/475 · Jan30 tlref 98.650/750', 'DİBS (ay ve yılla; tlref, cpi, zc türü söyler)'],
  ['06/01/2027.t1 31.450', 'ihale fiyat listesi: seviye (bono / kuponsuzda getiri)'],
  ['mar28 vs jul30 switch -45/-40', 'switch: iki kâğıt, uzun vadelinin getirisi − kısanınki (bp); yanında ekrana ve ASW eğrisine göre ucuz / pahalı'],
];

/** A level as it is quoted: per cent with at least two decimals, basis points with as many as were typed. */
export function level(v, unit) {
  if (typeof v !== 'number' || !isFinite(v)) return '';
  if (unit === 'px') return num(v, 3, false);                     // a bond's price: three decimals, as the desk quotes it
  let d = unit === 'pct' || unit === 'yld' ? 2 : 0;
  const most = unit === 'pct' || unit === 'yld' ? 4 : 2;
  while (d < most && Math.abs(v * 10 ** d - Math.round(v * 10 ** d)) > 1e-7) d += 1;
  return num(v, d, false);
}

function pref(key, fallback) {
  try { const v = localStorage.getItem(key); return v === null ? fallback : v; } catch (e) { return fallback; }
}

function fold(text) {
  return String(text || '').toLocaleLowerCase('tr').replace(/ı/g, 'i');
}

function isoDay(d) {
  return d.getFullYear() + '-' + String(d.getMonth() + 1).padStart(2, '0') + '-' + String(d.getDate()).padStart(2, '0');
}

/** What happened, in the desk's words. */
export function eventText(q) {
  const side = q.side === 'bid' ? 'bid' : (q.side === 'ask' ? 'offer' : '');
  if (q.event === 'trade') return 'İşlem' + (q.side === 'ask' ? ' · offer alındı' : (q.side === 'bid' ? ' · bid\'e verildi' : ''));
  if (q.event === 'ref') return 'Ref' + (side ? ' · ' + side : '');
  if (q.event === 'interest') return 'İlgi' + (side ? ' · ' + side : '');
  return EVENT[q.event] || q.event || '';
}

function kindText(q) {
  if (q.ok === false) return '';
  if (q.product === 'FX') return 'FX swap (puan)';
  if (q.product === 'DIBS' && q.kind === 'switch') return 'Switch (bp)';
  if (q.product === 'DIBS') return q.unit === 'yld' ? 'DİBS (getiri)' : 'DİBS (fiyat)';
  return (KIND[q.kind] || q.kind || '') + (q.unit === 'bp' ? ' (bp)' : '');
}

/** The TRY rate an FX swap quote in points stands for: "31,31 / 31,67" (bid / ask), or the trade's / the last one's. */
function impliedText(q, last) {
  const m = q.implied;
  if (!m) return '';
  if (m.kind === 'switch') {
    // the longer bond's cheapness against the shorter one at the level said: on the fitted ASW curve, else the screen
    const v = typeof m.vs_curve === 'number' ? m.vs_curve : m.vs_screen;
    if (typeof v !== 'number') return '';
    return (v > 0 ? '+' : '') + num(v, 1, false) + ' bp ' + (typeof m.vs_curve === 'number' ? 'eğri' : 'ekran') + ' · uzun ' + (v >= 0 ? 'ucuz' : 'pahalı');
  }
  const r = (v) => (typeof v === 'number' ? num(v, 2, false) : '');
  if (typeof m.bid === 'number' || typeof m.ask === 'number') return r(m.bid) + ' / ' + r(m.ask);
  return r(last ? m.last : m.price);
}

function impliedTip(q) {
  const m = q.implied;
  if (!m) return '';
  if (m.kind === 'switch') {
    const legs = (m.legs || []).map((l) => l.label + ' getiri ' + num(l.yield, 2, false) + '%' + (typeof l.rv === 'number' ? ', eğriye göre ' + num(l.rv, 1, false) + ' bp' : ''));
    return 'DİBS RV ekranı: ' + legs.join(' · ') + ' → ekrandaki switch ' + num(m.screen, 1, false) + ' bp'
      + (typeof m.rv === 'number' ? ', uzunun kısaya göre ucuzluğu (ASW eğrisi) ' + num(m.rv, 1, false) + ' bp' : '')
      + '. Söylenen seviye ' + num(m.at, 1, false) + ' bp: ekrandan ' + num(m.vs_screen, 1, false) + ' bp'
      + (typeof m.vs_curve === 'number' ? '; eğriye göre ' + num(m.vs_curve, 1, false) + ' bp' : '')
      + '. Artı: uzun vadeli kâğıt ucuz (uzunu al, kısayı sat).';
  }
  if (m.kind === 'bond') {
    return 'Fiyatın ima ettiği getiri (DİBS RV ekranından): ekran ' + num(m.screen, 3, false) + ' · getiri ' + num(m.screen_yield, 2, false)
      + '% · mod. süre ' + num(m.mod_dur, 2, false) + ' – getiri − (fiyat − ekran) / (ekran · süre)';
  }
  return 'FX swap puanının ima ettiği TRY faizi (ACT/360): ' + q.label + ' · ' + num(m.days, 0) + ' gün · USD ' + num(m.usd, 3, false)
    + '% · spot ' + num(m.spot, 4, false) + ' – Forward sayfasının spot, vade günü ve USD faiziyle; bid tarafı USD ask\'iyle, ask tarafı USD bid\'iyle';
}

/** The log's columns (after the date column of a range) and what each one sorts by. */
const LOG_COLUMNS = ['time', 'sender', 'party', 'raw', 'label', 'kind', 'bid', 'ask', 'price', 'event', 'model', 'note', 'implied'];
const LOG_SORT = {
  time: (q) => (q.date || '') + ' ' + (q.time || ''),
  sender: (q) => q.sender || '',
  party: (q) => (q.party === 'biz' ? 'Biz' : (q.source || (q.party ? 'Broker' : ''))),
  raw: (q) => q.raw || '',
  label: (q) => (q.ok ? instText(q) : ''),
  kind: (q) => (q.ok ? (KIND[q.kind] || q.kind || '') : ''),
  bid: (q) => (typeof q.bid === 'number' ? q.bid : null),
  ask: (q) => (typeof q.ask === 'number' ? q.ask : null),
  price: (q) => (q.ok && typeof q.price === 'number' ? q.price : null),
  event: (q) => eventText(q),
  model: (q) => (q.ok && typeof q.model === 'number' ? q.model : null),
  note: (q) => q.note || '',
  implied: (q) => (q.implied ? (typeof q.implied.bid === 'number' ? q.implied.bid : (typeof q.implied.ask === 'number' ? q.implied.ask : q.implied.price)) : null),
};

export class BrokerPage {
  constructor(host, ctx) {
    this.host = host;
    this.ctx = ctx;
    this.date = null;
    this.to = null;
    this.data = null;
    this.grids = {};
    this.same = {};
    this.draft = '';
    this.product = 'all';         // board: all / OIS / XCCY
    this.only = null;             // log: one instrument ({key, label}) ...
    this.find = '';               // ... and / or a search text
    this.quotesOnly = false;
    this.partyFilter = 'all';     // log: every line, the brokers' or ours
    this.picked = new Set();      // log: the lines ticked (to delete them together)
    this.logSort = (() => { try { return JSON.parse(localStorage.getItem('tto.broker.sort') || 'null'); } catch (e) { return null; } })();
    this.pasteParty = pref('tto.broker.party', 'broker');      // whose the lines of a paste are when no name says it
    this.seq = 0;
    this.parsed = null;
    this.preview = debounce(() => this.doPreview(), 240);
  }

  query() {
    if (!this.date) return null;
    return this.to && this.to !== this.date ? { date: this.date, to: this.to } : { date: this.date };
  }

  async load() {
    clear(this.host);
    this.host.appendChild(h('div', { class: 'loading' }, 'Yükleniyor…'));
    const data = await api.get('/api/broker', this.query());
    if (this.dead) return;
    this.data = data;
    this.date = data.date;
    this.to = data.ranged ? data.to : null;
    this.build();
    this.fill();
    if (this.draft.trim()) this.doPreview();
  }

  async refresh() {
    const data = await api.get('/api/broker', this.query());
    if (this.dead) return;
    this.data = data;
    this.fill();
  }

  destroy() {
    this.dead = true;
    this.preview.cancel();
    if (this.text) this.draft = this.text.value;
  }

  /** Show one day (``to`` empty) or every day of a period. */
  show(from, to) {
    if (!from) return;
    if (to && to < from) { const x = from; from = to; to = x; }
    if (this.text) this.draft = this.text.value;
    this.date = from;
    this.to = to && to !== from ? to : null;
    this.load().catch(errorToast);
  }

  // ------------------------------------------------------------------ layout
  build() {
    clear(this.host);
    this.grids = {};
    this.same = {};
    const d = this.data;
    this.dateSel = h('select', { class: 'inp', id: 'broker-day' });
    this.dateSel.addEventListener('change', () => { if (this.dateSel.value) this.show(this.dateSel.value, null); });
    this.fromInp = h('input', { type: 'date', class: 'inp', id: 'broker-from', title: 'Başlangıç günü' });
    this.toInp = h('input', { type: 'date', class: 'inp', id: 'broker-to', title: 'Bitiş günü' });
    const go = h('button', { class: 'btn sm primary', type: 'button', id: 'broker-range' }, 'Göster');
    go.addEventListener('click', () => {
      if (!this.fromInp.value || !this.toInp.value) { toast('Aralığın iki tarihini de seçin', 'err'); return; }
      this.show(this.fromInp.value, this.toInp.value);
    });
    for (const el of [this.fromInp, this.toInp]) el.addEventListener('keydown', (e) => { if (e.key === 'Enter') go.click(); });
    const preset = (label, title, fn) => {
      const b = h('button', { class: 'btn sm', type: 'button', title }, label);
      b.addEventListener('click', () => { const [a, z] = fn(new Date()); this.show(isoDay(a), isoDay(z)); });
      return b;
    };
    const range = h('span', { class: 'rangebox' }, h('span', { class: 'muted' }, 'Aralık'), this.fromInp, h('span', { class: 'muted' }, '–'), this.toInp, go,
      preset('Bu hafta', 'Pazartesiden bugüne', (t) => { const a = new Date(t); a.setDate(t.getDate() - ((t.getDay() + 6) % 7)); return [a, t]; }),
      preset('Son 30 gün', 'Otuz gün öncesinden bugüne', (t) => { const a = new Date(t); a.setDate(t.getDate() - 30); return [a, t]; }));
    this.todayBtn = h('button', { class: 'btn sm', type: 'button', id: 'broker-today', title: 'Bugünün chat\'ine dön' }, 'Bugün');
    this.todayBtn.addEventListener('click', () => this.show(this.data.today, null));
    this.exportBtn = h('button', { class: 'btn sm', type: 'button', id: 'broker-export',
      title: 'Görüntülenen günün / aralığın tahtasını ve bütün kayıtlarını Excel dosyası olarak indir (BrokerChat_yyyy.aa.gg.xlsx)' }, 'Excel (.xlsx)');
    this.exportBtn.addEventListener('click', async () => {
      this.exportBtn.disabled = true;
      try {
        const res = await api.download('/api/broker/export', { date: this.date || undefined, to: this.to || undefined }, 'BrokerChat.xlsx');
        toast(res.name + ' indirildi', 'ok', 3200);
      } catch (err) { errorToast(err); } finally { this.exportBtn.disabled = false; }
    });
    const people = h('button', { class: 'btn sm', type: 'button', id: 'broker-people',
      title: 'Chat\'lerde yazan isimler: hangisi bizim masa, hangisi hangi broker – herkes için kaydedilir' }, 'İsimler · kaynaklar');
    people.addEventListener('click', () => this.openPeople().catch(errorToast));
    this.host.appendChild(h('div', { class: 'page-tools' }, h('span', { class: 'muted' }, 'Gün'), this.dateSel, this.todayBtn, range, this.exportBtn, people,
      h('span', { class: 'grow' }), h('span', { class: 'muted' }, 'Kaydedilen kotalar tüm kullanıcılarda anında görünür')));
    this.dayNote = h('div', { class: 'banner hidden' });
    this.host.appendChild(this.dayNote);

    // ---- entry: paste or type, see how it is read, keep it
    this.text = h('textarea', { id: 'broker-text', class: 'inp chatbox', rows: '9', spellcheck: 'false', autocomplete: 'off',
      placeholder: 'Chat\'i buraya yapıştırın ya da yazın – her satır bir mesaj:\n\n12:15:38 18m ois 35.03/35.23\n12:10:07 18m ois /35.23 offer\n'
        + '10:29:57 1y5y ois -64/-60\n12:18:04 2y3y4y ois 12/ bid\n12:11:55 9x12m ois fra 33.80/34.10\n6m OIS 90 bid' });
    this.text.value = this.draft;
    this.text.addEventListener('input', () => { this.draft = this.text.value; this.preview(); });
    this.text.addEventListener('keydown', (e) => { if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) { e.preventDefault(); this.save(); } });
    this.source = h('input', { type: 'text', id: 'broker-source', class: 'inp', maxlength: '40', placeholder: 'örn. Tullett', list: 'broker-sources',
      autocomplete: 'off', title: 'İsmi listede olmayan satırların kaynağı (kurum) – her satırla birlikte saklanır. Listedeki isimler kendi kaynağıyla gelir.' });
    this.source.addEventListener('input', () => this.preview());
    this.partyBox = partySeg(this.pasteParty, (v) => {
      this.pasteParty = v;
      try { localStorage.setItem('tto.broker.party', v); } catch (e) { /* ignore */ }
      this.preview();
    }, 'broker-party');
    this.partyBox.title = 'İsmi listede olmayan (ya da hiç ismi olmayan) satırlar kimin: broker fiyatı mı, bizim fiyatımız mı';
    this.namesBox = h('div', { class: 'chatnames hidden', id: 'broker-names' });
    try { this.source.value = localStorage.getItem('tto.broker.source') || ''; } catch (e) { /* ignore */ }
    this.sources = h('datalist', { id: 'broker-sources' });
    this.entryDate = h('input', { type: 'date', id: 'broker-date', class: 'inp',
      title: 'Kotaların günü. Chat\'in içinde tarih satırı varsa o geçerlidir.' });
    this.entryDate.value = d.ranged ? d.today : d.date;
    this.entryDate.addEventListener('change', () => this.preview());
    this.keepTexts = h('input', { type: 'checkbox', id: 'broker-texts' });
    let keep = true;
    try { keep = localStorage.getItem('tto.broker.texts') !== '0'; } catch (e) { /* ignore */ }
    this.keepTexts.checked = keep;
    this.keepTexts.addEventListener('change', () => {
      try { localStorage.setItem('tto.broker.texts', this.keepTexts.checked ? '1' : '0'); } catch (e) { /* ignore */ }
      this.showPreview();
    });
    this.previewBox = h('div', { class: 'chatpreview', id: 'broker-preview' });
    this.summary = h('span', { class: 'muted', id: 'broker-summary' });
    this.saveBtn = h('button', { class: 'btn primary', type: 'button', id: 'broker-save', title: 'Kaydet (Ctrl+Enter)' }, 'Kaydet');
    this.saveBtn.addEventListener('click', () => this.save());
    const wipe = h('button', { class: 'btn', type: 'button', id: 'broker-clear' }, 'Temizle');
    wipe.addEventListener('click', () => { this.text.value = ''; this.draft = ''; this.parsed = null; this.showPreview(); this.text.focus(); });
    const help = h('details', { class: 'chathelp' }, h('summary', null, 'Nasıl okunur?'),
      h('table', { class: 'plain' }, EXAMPLES.map(([line, what]) => h('tr', null, h('td', { class: 'l mono' }, line), h('td', { class: 'l' }, what)))),
      h('div', { class: 'muted pad0' }, 'Saat satırın başında, sonunda ya da (telefondaki gibi) alt satırda olabilir; saat yoksa girildiği an yazılır. '
        + 'İsim satırı ya da "İSİM: mesaj" göndereni belirler. Aynı chat ikinci kez yapıştırılırsa yalnızca yeni satırlar eklenir.'));
    const entry = h('div', { class: 'card entry' }, h('header', null, h('h2', null, 'Chat\'ten ekle')),
      h('div', { class: 'pad form' }, this.text,
        h('div', { class: 'chatrow' },
          h('div', { class: 'field' }, h('label', { for: 'broker-source' }, 'Kaynak'), this.source, this.sources),
          h('div', { class: 'field party' }, h('label', null, 'Taraf'), this.partyBox),
          h('div', { class: 'field' }, h('label', { for: 'broker-date' }, 'Tarih'), this.entryDate),
          h('label', { class: 'check', title: 'Kapalıyken yalnızca enstrüman içeren satırlar saklanır' }, this.keepTexts, ' Metin satırlarını da sakla')),
        this.namesBox,
        this.previewBox,
        h('div', { class: 'chatrow actions' }, this.summary, h('span', { class: 'grow' }), wipe, this.saveBtn),
        help));

    // ---- board: where every instrument stands
    const seg = h('div', { class: 'seg', id: 'broker-product' });
    for (const [v, label] of [['all', 'Tümü'], ['OIS', 'OIS'], ['XCCY', 'XCCY'], ['FX', 'FX swap'], ['DIBS', 'DİBS']]) {
      const b = h('button', { type: 'button' }, label);
      b.dataset.v = v;
      b.addEventListener('click', () => { this.product = v; this.fill(); });
      seg.appendChild(b);
    }
    this.productSeg = seg;
    const resetBtn = h('button', { class: 'btn sm', type: 'button', id: 'broker-reset',
      title: 'Tahtadaki bütün kotaları şu andan itibaren sıfırla – kayıttaki satırlar silinmez; sonra söylenenler tahtaya yeniden gelir' }, 'Tahtayı sıfırla');
    resetBtn.addEventListener('click', () => this.reset(null));
    this.resetInfo = h('span', { class: 'muted resetinfo', id: 'broker-reset-info' });
    this.board = this.panel('board', 'Tahta · son durum', [seg, this.resetInfo, resetBtn],
      'Bid / ask: en son söylenen kota (geri çekilen taraf boş). Model: dashboard\'un kendi TRY OIS eğrisi (sizin senaryonuzla); '
      + 'farklar baz puan – bid model\'in üstünde ya da ask model\'in altındaysa vurgulanır.');
    // ---- log: the chat in the order it was said
    this.findInp = h('input', { type: 'search', class: 'inp', id: 'broker-find', placeholder: 'Ara: 18m, spread, isim…', autocomplete: 'off' });
    this.findInp.value = this.find;
    this.findInp.addEventListener('input', () => { this.find = this.findInp.value; this.fillLog(); });
    this.onlyBtn = h('button', { class: 'btn sm on hidden', type: 'button', id: 'broker-only', title: 'Enstrüman süzgecini kaldır' });
    this.onlyBtn.addEventListener('click', () => { this.only = null; this.fillLog(); });
    this.quotesBox = h('input', { type: 'checkbox', id: 'broker-quotes' });
    this.quotesBox.checked = this.quotesOnly;
    this.quotesBox.addEventListener('change', () => { this.quotesOnly = this.quotesBox.checked; this.fillLog(); });
    const whose = h('div', { class: 'seg', id: 'broker-whose' });
    for (const [v, label] of [['all', 'Tümü'], ['broker', 'Broker'], ['biz', 'Biz']]) {
      const b = h('button', { type: 'button' }, label);
      b.dataset.v = v;
      b.classList.toggle('on', v === this.partyFilter);
      b.addEventListener('click', () => { this.partyFilter = v; for (const x of whose.children) x.classList.toggle('on', x === b); this.fillLog(); });
      whose.appendChild(b);
    }
    this.delPicked = h('button', { class: 'btn sm danger hidden', type: 'button', id: 'broker-del-picked' });
    this.delPicked.addEventListener('click', () => this.removePicked());
    this.log = this.panel('log', 'Kayıt · söylendiği sırayla', [this.delPicked, this.onlyBtn, whose, this.findInp,
      h('label', { class: 'check' }, this.quotesBox, ' Yalnızca kotalar')]);
    // entry and board side by side, the chat itself across the page below them
    this.host.appendChild(h('div', { class: 'broker' }, h('div', { class: 'entrycol' }, entry), h('div', { class: 'boardcol' }, this.board.el),
      h('div', { class: 'logcol' }, this.log.el)));
    this.showPreview();
  }

  panel(id, title, extra, hint) {
    const body = h('div', { class: 'body' });
    const count = h('span', { class: 'muted' });
    const cp = h('button', { class: 'iconbtn', type: 'button', title: 'Tabloyu kopyala (Excel\'e yapıştırılabilir)' }, 'Kopyala');
    cp.addEventListener('click', () => { if (this.grids[id]) copyGrid(this.grids[id]); });
    const head = h('header', null, h('h2', { title: hint || '' }, title), count, h('span', { class: 'grow' }), extra, h('div', { class: 'tools' }, cp));
    const el = h('section', { class: 'panel wide', id: 'broker-' + id + '-panel' }, head, body);
    return { el, body, count };
  }

  /**
   * ``same``: a text that stays the same as long as the table lists the same things.  Then only numbers that
   * follow the market (the model, the differences) can have moved: they are patched in place, and a selection
   * or a tooltip being read is left alone.  Anything else rebuilds the table (its row buttons belong to rows).
   */
  setGrid(id, sec, header, rows, countText, emptyText, same) {
    sec.count.textContent = countText || '';
    if (!rows.length) {
      clear(sec.body);
      this.grids[id] = null;
      this.same[id] = null;
      sec.body.appendChild(h('div', { class: 'empty' }, emptyText));
      return;
    }
    const data = plainData(header, rows);
    if (this.grids[id] && this.same[id] === same) {
      this.grids[id].update(data, true);
    } else if (this.grids[id]) {
      this.grids[id].replace(data);
    } else {
      clear(sec.body);
      this.grids[id] = new Grid({ data, editable: false });
      sec.body.appendChild(this.grids[id].el);
    }
    this.same[id] = same;
  }

  // ------------------------------------------------------------------ what is kept
  fill() {
    const d = this.data;
    clear(this.dateSel);
    const seen = new Set();
    const add = (iso, label) => { if (!seen.has(iso)) { seen.add(iso); this.dateSel.appendChild(h('option', { value: iso }, label)); } };
    if (d.ranged) this.dateSel.appendChild(h('option', { value: '' }, 'Aralık: ' + isoToTr(d.date) + ' – ' + isoToTr(d.to)));
    add(d.today, isoToTr(d.today) + ' (bugün)');
    for (const x of d.dates) add(x.date, isoToTr(x.date) + ' · ' + x.count + ' satır');
    if (!d.ranged) add(d.date, isoToTr(d.date));
    this.dateSel.value = d.ranged ? '' : d.date;
    this.fromInp.value = d.date;
    this.toInp.value = d.to || d.date;
    this.todayBtn.classList.toggle('hidden', d.is_today);
    this.dayNote.textContent = d.is_today ? '' : (d.ranged
      ? 'Aralık: ' + isoToTr(d.date) + ' – ' + isoToTr(d.to) + ' · ' + d.rows.length + ' satır. Tahta, aralığın sonundaki durumu gösterir.'
      : 'Geçmiş gün: ' + isoToTr(d.date) + '. Buraya eklenen chat bu güne yazılır (ya da "Tarih" kutusundaki güne).');
    this.dayNote.classList.toggle('hidden', d.is_today);
    clear(this.sources);
    for (const s of new Set(d.rows.map((q) => q.source).filter(Boolean))) this.sources.appendChild(h('option', { value: s }));

    // ---- board
    for (const b of this.productSeg.children) b.classList.toggle('on', b.dataset.v === this.product);
    const when = (stamp) => {
      if (!stamp) return '';
      const [day, time] = stamp.split(' ');
      return d.ranged ? isoToTr(day).slice(0, 5) + ' ' + (time || '') : (time || day);
    };
    const side = (v, unit, stamp, name) => (typeof v === 'number' ? { t: level(v, unit), v, k: 'n', tip: name + ': ' + when(stamp) } : { t: '', k: '', tip: stamp ? name + ' yok: ' + when(stamp) : '' });
    const diff = (v, through, unit) => (typeof v === 'number' ? { t: (v > 0 ? '+' : '') + num(v, unit === 'px' ? 3 : 1, false), v, k: 'n', cls: through ? 'thru' : '',
      tip: (unit === 'px' ? 'DİBS: fiyat farkı (puan), bp değil – ekran fiyatına göre' : (unit === 'yld' ? 'Bono: getiri farkı (bp)' : ''))
        + (through ? (unit === 'px' || unit === 'yld' ? '\n' : '') + 'Kota model seviyesinin öbür tarafında' : '') } : { t: '', k: '' });
    const board = d.board.filter((r) => this.product === 'all' || r.product === this.product);
    const ours = (r) => (typeof r.our_bid === 'number' || typeof r.our_ask === 'number'
      ? { t: (typeof r.our_bid === 'number' ? level(r.our_bid, r.unit) : '') + ' / ' + (typeof r.our_ask === 'number' ? level(r.our_ask, r.unit) : ''),
        k: 's', cls: 'ours', tip: 'Bizim son kotamız · ' + when(r.our_time) } : { t: '', k: '' });
    this.setGrid('board', this.board,
      ['Ürün', 'Enstrüman', 'Tür', 'Bid', 'Ask', 'Saat', 'Son işlem', 'Bizim kota', 'Model', 'Bid − model (bp)', 'Ask − model (bp)', 'Son mesaj', 'TRY % / getiri (ima)', '', ''],
      board.map((r) => [r.product === 'DIBS' ? 'DİBS' : r.product, { t: r.label, k: 's', b: 1, tip: r.isin || '' }, kindText(r),
        side(r.bid, r.unit, r.bid_time, 'Bid'), side(r.ask, r.unit, r.ask_time, 'Ask'),
        when(r.time), typeof r.last === 'number' ? { t: level(r.last, r.unit) + (r.last_by === 'biz' ? ' · biz' : ''), v: r.last, k: 'n',
          cls: r.last_side === 'ask' ? 'buy' : (r.last_side === 'bid' ? 'sell' : ''),
          tip: when(r.last_time) + (r.last_side === 'ask' ? ' · offer alındı' : (r.last_side === 'bid' ? ' · bid\'e verildi' : ''))
            + (r.last_by === 'biz' ? ' · bizim işlemimiz' : '') } : { t: '', k: '' },
        ours(r),
        typeof r.mid === 'number' ? { t: num(r.mid, r.unit === 'px' ? 3 : (r.unit === 'pct' || r.unit === 'yld' ? 2 : 1), false), v: r.mid, k: 'n', cls: 'soft',
          tip: r.product === 'DIBS' ? 'DİBS RV ekranındaki ' + (r.unit === 'yld' ? 'getiri' : 'temiz fiyat') : '' } : { t: '', k: '' },
        // through the model: a bid above it, an ask below it - in yield the other way round (a bid's yield below the model's)
        diff(r.bid_diff, r.unit === 'yld' ? r.bid_diff < 0 : r.bid_diff > 0, r.unit), diff(r.ask_diff, r.unit === 'yld' ? r.ask_diff > 0 : r.ask_diff < 0, r.unit),
        { t: r.said || '', k: 's', cls: 'said short', tip: r.said || '' },
        r.implied ? { t: impliedText(r) || impliedText(r, true), k: 's', cls: 'soft', tip: impliedTip(r) } : { t: '', k: '' },
        { t: '', k: '', cls: 'act', act: { label: '≡', title: r.label + ' için söylenenlerin hepsini aşağıda göster', fn: () => this.showOnly(r) } },
        { t: '', k: '', cls: 'act', act: { label: '⟲', title: r.label + ' kotasını sıfırla (şu ana kadar söylenenler tahtadan kalkar)', fn: () => this.reset(r) } }]),
      d.board.length ? board.length + ' enstrüman' : '', d.board.length ? 'Bu üründe kota yok' : 'Henüz kota yok – soldaki kutuya chat\'i yapıştırın',
      JSON.stringify([d.ranged, board.map((r) => [r.key, r.bid, r.ask, r.last, r.last_side, r.last_by, r.bid_time, r.ask_time, r.last_time, r.time, r.said,
        r.our_bid, r.our_ask, r.our_time, typeof r.mid === 'number', impliedText(r)])]));
    // resets of the board in what is shown, the last one can be taken back
    clear(this.resetInfo);
    const resets = d.resets || [];
    if (resets.length) {
      const last = resets[resets.length - 1];
      const undo = h('button', { class: 'linkbtn', type: 'button', id: 'broker-reset-undo', title: 'Son sıfırlamayı geri al' }, 'geri al');
      undo.addEventListener('click', () => this.reset(null, true, last.at.slice(0, 10)));
      this.resetInfo.append('Sıfırlandı: ' + resets.slice(-3).map((x) => (d.ranged ? isoToTr(x.at.slice(0, 10)).slice(0, 5) + ' ' : '') + x.at.slice(11, 16)
        + (x.key === '*' ? '' : ' (' + (x.label || 'tek') + ')')).join(', ') + ' · ', undo);
    }
    this.fillLog();
  }

  async reset(r, undo, day) {
    const d = this.data;
    if (!undo) {
      const ok = await confirmDialog('Tahtayı sıfırla', (r ? r.label + ' için' : 'Tahtadaki') + ' şu ana kadar söylenen kotalar tahtadan kalkar; kayıttaki satırlar '
        + 'silinmez, sonra söylenenler tahtaya yeniden gelir. ' + (d.is_today ? '' : 'Bugün olmayan bir günde o günün tamamı sıfırlanır. ') + 'Devam edilsin mi?', 'Sıfırla');
      if (!ok) return;
    }
    try {
      await api.post('/api/broker/reset', { date: day || (d.ranged ? d.to : d.date), key: r ? r.key : null, undo: !!undo });
      toast(undo ? 'Sıfırlama geri alındı' : (r ? r.label + ' sıfırlandı' : 'Tahta sıfırlandı') , 'ok');
      this.ctx.refreshNow();
    } catch (err) { errorToast(err); }
  }

  updatePicked() {
    const ids = new Set((this.data.rows || []).map((q) => q.id));
    for (const id of [...this.picked]) if (!ids.has(id)) this.picked.delete(id);
    const n = this.picked.size;
    this.delPicked.textContent = 'Seçilenleri sil (' + n + ')';
    this.delPicked.classList.toggle('hidden', !n);
  }

  async removePicked() {
    const ids = [...this.picked];
    if (!ids.length) return;
    const ok = await confirmDialog('Seçilenleri sil', ids.length + ' satır silinsin mi? Silinen satırlar tüm kullanıcılardan kalkar.', 'Sil', true);
    if (!ok) return;
    try {
      const res = await api.post('/api/broker/delete', { ids });
      this.picked.clear();
      toast(res.deleted + ' satır silindi', 'ok');
      this.ctx.refreshNow();
    } catch (err) { errorToast(err); }
  }

  showOnly(r) {
    this.only = { key: r.key, label: instText(r) };
    this.fillLog();
    this.log.el.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }

  /** The order of the log: a column and a direction (the time, oldest first, unless a caption was clicked). */
  logOrder(rows) {
    const s = this.logSort || { key: 'time', dir: 1 };
    const key = LOG_SORT[s.key] || LOG_SORT.time;
    const time = LOG_SORT.time;
    return rows.map((q, i) => [q, i]).sort((a, b) => {
      const x = key(a[0]), y = key(b[0]);
      let c = 0;
      if (x === y) c = 0;
      else if (x === null || x === undefined || x === '') c = 1;                  // empty cells last, whichever way
      else if (y === null || y === undefined || y === '') c = -1;
      else c = (typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y), 'tr')) * s.dir;
      if (!c) c = time(a[0]).localeCompare(time(b[0])) * (s.key === 'time' ? s.dir : 1) || a[1] - b[1];
      return c;
    }).map((x) => x[0]);
  }

  /** Tick every line shown (or, when they all are, none). */
  pickAll() {
    const shown = this.shownIds || [];
    const all = shown.length > 0 && shown.every((id) => this.picked.has(id));
    for (const id of shown) { if (all) this.picked.delete(id); else this.picked.add(id); }
    this.fillLog();
  }

  sortLog(column) {
    const key = LOG_COLUMNS[column];
    if (!key) return;
    const s = this.logSort || { key: 'time', dir: 1 };
    this.logSort = { key, dir: s.key === key ? -s.dir : (key === 'time' ? -1 : 1) };
    try { localStorage.setItem('tto.broker.sort', JSON.stringify(this.logSort)); } catch (e) { /* private window */ }
    this.fillLog();
  }

  fillLog() {
    const d = this.data;
    const needle = fold(this.find).trim();
    this.onlyBtn.classList.toggle('hidden', !this.only);
    this.onlyBtn.textContent = this.only ? 'Yalnızca ' + this.only.label + ' ✕' : '';
    const kept = d.rows.filter((q) => {
      if (this.only && q.key !== this.only.key) return false;
      if (this.quotesOnly && !q.ok) return false;
      if (this.partyFilter === 'biz' && q.party !== 'biz') return false;
      if (this.partyFilter === 'broker' && q.party === 'biz') return false;
      if (!needle) return true;
      return fold([q.raw, q.label, q.product, KIND[q.kind], q.sender, q.source, eventText(q), q.note].join(' ')).includes(needle);
    });
    const rows = this.logOrder(kept);
    this.shownIds = rows.map((q) => q.id);
    const s = this.logSort || { key: 'time', dir: 1 };
    const arrow = (key) => (s.key === key ? (s.dir > 0 ? ' ▲' : ' ▼') : '');
    const dayHead = (d.ranged ? ['Tarih' + arrow('time')] : []);
    const allOn = rows.length > 0 && rows.every((q) => this.picked.has(q.id));
    const lv = (q, v) => (typeof v === 'number' ? { t: level(v, q.unit), v, k: 'n' } : { t: '', k: '' });
    const stamp = (q) => 'Giren: ' + (this.ctx.displayName(q.created_by) || '?') + (q.created_at ? ' · ' + q.created_at.replace('T', ' ').slice(0, 19) : '')
      + (q.timed === false ? '\nMesajda saat yoktu: girildiği an yazıldı' : '');
    this.setGrid('log', this.log,
      [allOn ? '☑' : '☐'].concat(dayHead).concat(['Saat' + (d.ranged ? '' : arrow('time')), 'Kimden' + arrow('sender'), 'Taraf' + arrow('party'), 'Mesaj' + arrow('raw'),
        'Enstrüman' + arrow('label'), 'Tür' + arrow('kind'), 'Bid' + arrow('bid'), 'Ask' + arrow('ask'), 'İşlem / seviye' + arrow('price'),
        'Olay' + arrow('event'), 'Model (girişte)' + arrow('model'), 'Not' + arrow('note'), 'TRY % / getiri (ima)' + arrow('implied'), '']),
      rows.map((q) => [{ t: '', k: '', cls: 'tick', chk: { on: this.picked.has(q.id), title: 'Seç (seçilenleri birlikte silmek için)',
        fn: (on) => { if (on) this.picked.add(q.id); else this.picked.delete(q.id); this.updatePicked(); } } }]
        .concat(d.ranged ? [{ t: isoToTr(q.date), k: 's' }] : []).concat([
        { t: q.time, k: 's', cls: q.timed === false ? 'soft' : '', tip: stamp(q) },
        q.sender || '', { t: owner(q), k: 's', cls: q.party === 'biz' ? 'ours' : '', tip: q.party ? (q.party === 'biz' ? 'Bizim fiyatımız' : 'Broker fiyatı') : 'Taraf belli değil' },
        { t: q.raw || '', k: 's', cls: 'said', tip: q.raw || '' },
        q.ok ? { t: instText(q), k: 's', b: 1, tip: instTip(q) } : '', kindText(q),
        lv(q, q.bid), lv(q, q.ask), q.ok && typeof q.price === 'number' ? { t: level(q.price, q.unit), v: q.price, k: 'n',
          cls: q.event === 'trade' ? (q.side === 'ask' ? 'buy' : (q.side === 'bid' ? 'sell' : '')) : '' } : { t: '', k: '' },
        { t: eventText(q) + (q.oco ? ' · OCO' : '') + ((q.flags || []).some((f) => FLAG[f] && FLAG[f][1] === 'warn') ? ' ⚠' : ''), k: 's', cls: q.ok ? '' : 'soft',
          tip: (q.flags || []).map((f) => flagTip(q, f)).join('\n') },
        q.ok && typeof q.model === 'number' ? { t: num(q.model, q.unit === 'px' ? 3 : (q.unit === 'pct' || q.unit === 'yld' ? 2 : 1), false), v: q.model, k: 'n', cls: 'soft',
          tip: 'Satır girildiği anda dashboard eğrisinin bu enstrüman için verdiği seviye' } : { t: '', k: '' },
        q.note || '',
        q.implied ? { t: impliedText(q), k: 's', cls: 'soft', tip: impliedTip(q) } : { t: '', k: '' },
        { t: '', k: '', cls: 'act', act: (this.canTrade(q) ? [{ id: 'trade', label: '⇢', title: 'İşlem gir: Günlük İşlemler bu satırın enstrümanı, seviyesi ve '
          + 'yönüyle dolu açılır', fn: () => this.openTrade(q) }] : []).concat([{ id: 'del', label: '✕', title: 'Satırı sil', fn: () => this.remove(q) }]) }])),
      d.rows.length ? (rows.length === d.rows.length ? rows.length + ' satır' : rows.length + ' / ' + d.rows.length + ' satır') : '',
      d.rows.length ? 'Süzgece uyan satır yok' : (d.ranged ? 'Bu aralıkta kayıt yok' : 'Bu gün için kayıt yok'),
      JSON.stringify([d.ranged, s, allOn, rows.map((q) => q.id + q.party + q.source + (this.picked.has(q.id) ? '+' : ''))]));
    this.updatePicked();
    const g = this.grids.log;
    if (g && !g.el.__sortable) {
      g.el.__sortable = true;
      g.el.classList.add('sortable');
      g.el.addEventListener('click', (e) => {
        const td = e.target.closest('td');
        if (!td || td.__i !== 0) return;                                          // the captions
        if (td.__j === 0) { this.pickAll(); return; }                              // the tick box column: all shown / none
        this.sortLog(td.__j - 1 - (this.data.ranged ? 1 : 0));
      });
    }
    // the newest line in view, as in the chat itself, while the log runs oldest first
    const last = rows.length ? rows[rows.length - 1].id : null;
    if (g && last !== this.logLast) {
      this.logLast = last;
      if (s.key === 'time' && s.dir > 0) {
        const scroller = g.el.closest('.body') || g.el;
        if (scroller.scrollHeight > scroller.clientHeight) scroller.scrollTop = scroller.scrollHeight;
      }
    }
  }

  /** A line one can book: a trade, or a quote of ours (a client dealt on it), of a product Günlük İşlemler takes. */
  canTrade(q) {
    return !!(this.ctx.openTrade && tradeKind(q) && tradeLevels(q).length && (q.event === 'trade' || q.party === 'biz'));
  }

  /** "İşlem gir": the level and our side, then Günlük İşlemler with the trade filled - the amount is left to type. */
  openTrade(q) {
    const levels = tradeLevels(q);
    if (!levels.length) return;
    const names = tradeSideNames(q);
    let key = levels[0][0];
    let buy = tradeBuys(q, key);
    let byHand = false;
    const m = modal({ title: 'İşlem gir · ' + instText(q), width: 500 });
    m.box.id = 'chat-trade';
    const lvBox = h('div', { class: 'seg', id: 'chat-trade-level' });
    const sideBox = h('div', { class: 'seg', id: 'chat-trade-side' });
    const why = h('div', { class: 'muted', id: 'chat-trade-why' });
    const go = h('button', { class: 'btn primary', type: 'button', id: 'chat-trade-open' }, 'Günlük İşlemler\'de aç');
    const whyText = () => {
      if (byHand) return 'Yön elle seçildi.';
      if (key === 'bid') return q.party === 'biz' ? 'Bizim kotamız: bid\'imize satıldı → biz ' + names[0] : 'Broker kotası: bid\'e verdik → biz ' + names[1];
      if (key === 'ask') return q.party === 'biz' ? 'Bizim kotamız: offer\'ımız alındı → biz ' + names[1] : 'Broker kotası: offer\'ı aldık → biz ' + names[0];
      if (q.side === 'ask') return 'İşlem: offer alındı → ' + names[0] + (q.party === 'biz' ? '' : ' (bizim tarafımızsa)');
      if (q.side === 'bid') return 'İşlem: bid\'e verildi → ' + names[1] + (q.party === 'biz' ? '' : ' (bizim tarafımızsa)');
      return 'Satır yönü söylemiyor: yönü seçin.';
    };
    const render = () => {
      clear(lvBox);
      for (const [k, caption, v] of levels) {
        const b = h('button', { type: 'button', class: k === key ? 'on' : '' }, caption + ' ' + level(v, q.unit));
        b.dataset.v = k;
        b.addEventListener('click', () => { key = k; if (!byHand) buy = tradeBuys(q, k); render(); });
        lvBox.appendChild(b);
      }
      clear(sideBox);
      for (const [v, label] of [[true, names[0]], [false, names[1]]]) {
        const b = h('button', { type: 'button', class: (buy === v ? 'on ' : '') + (v ? 'buy' : 'sell') }, label);
        b.dataset.v = v ? 'buy' : 'sell';
        b.addEventListener('click', () => { buy = v; byHand = true; render(); });
        sideBox.appendChild(b);
      }
      why.textContent = whyText();
      go.disabled = buy === null;
    };
    go.addEventListener('click', () => {
      const spec = tradeSpec(q, key, buy);
      if (!spec) return;
      m.close();
      this.ctx.openTrade(spec);
    });
    m.body.appendChild(h('div', { class: 'muted said' }, [q.time, q.sender].filter(Boolean).join(' · ') + ' — ' + (q.raw || '')));
    m.body.appendChild(h('div', { class: 'row' }, h('div', { class: 'field' }, h('label', null, 'Seviye'), lvBox),
      h('div', { class: 'field' }, h('label', null, 'Bizim yönümüz'), sideBox)));
    m.body.appendChild(why);
    m.body.appendChild(h('div', { class: 'muted' }, 'Günlük İşlemler\'de enstrüman, seviye, yön ve not dolu açılır; tutarı yazıp kaydedin.'));
    m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Kapat'));
    m.foot.appendChild(go);
    render();
    return m;
  }

  async remove(q) {
    const ok = await confirmDialog('Satırı sil', q.time + ' · ' + (q.raw || '') + ' silinsin mi? Silinen satır tüm kullanıcılardan kalkar.', 'Sil', true);
    if (!ok) return;
    try {
      await api.del('/api/broker/' + q.id);
      toast('Satır silindi', 'ok');
      this.ctx.refreshNow();
    } catch (err) { errorToast(err); }
  }

  // ------------------------------------------------------------------ entry
  async doPreview() {
    const text = this.text.value;
    const seq = ++this.seq;
    if (!text.trim()) { this.parsed = null; this.showPreview(); return; }
    try {
      const res = await api.post('/api/broker/parse', { text, date: this.entryDate.value || null, source: this.source.value.trim(), party: this.pasteParty });
      if (this.dead || seq !== this.seq) return;
      this.parsed = res;
    } catch (err) {
      if (this.dead || seq !== this.seq) return;
      this.parsed = { error: err.message, rows: [] };
    }
    this.showPreview();
  }

  showPreview() {
    const p = this.parsed;
    clear(this.previewBox);
    this.summary.textContent = '';
    this.summary.className = 'muted';
    if (!p || p.error) this.fillNames([]);
    if (!p) { this.saveBtn.disabled = !this.text.value.trim(); return; }
    if (p.error) { this.previewBox.appendChild(h('div', { class: 'errtxt' }, p.error)); return; }
    const keep = this.keepTexts.checked;
    const rows = p.rows.filter((q) => q.ok || keep);
    const pill = (text, cls, title) => h('span', { class: 'pill ' + (cls || 'neu'), title: title || '' }, text);
    this.fillNames(p.senders || []);
    const table = h('table', { class: 'plain chat' }, h('tr', null, h('th', { class: 'l' }, 'Saat'), h('th', { class: 'l' }, 'Kimin'), h('th', { class: 'l' }, 'Enstrüman'),
      h('th', null, 'Bid'), h('th', null, 'Ask'), h('th', { title: 'İşlem fiyatı ya da tarafı söylenmemiş seviye' }, 'Fiyat'), h('th', { class: 'l' }, 'Olay')));
    for (const q of rows) {
      const marks = [];
      // a completed big figure is marked on the numbers themselves; what may be wrong gets a label
      for (const f of q.flags || []) { const x = FLAG[f]; if (x && x[1] === 'warn') marks.push(pill(x[0], x[1], flagTip(q, f).slice(x[0].length + 2))); }
      const short = (q.flags || []).find((f) => f === 'abbr' || f === 'ambiguous' || f === 'standing');
      const numCell = (v, cls) => h('td', { class: (cls || '') + (short && typeof v === 'number' ? ' abbr' : ''),
        title: short && typeof v === 'number' ? FLAG[short === 'standing' ? 'standing' : 'abbr'][2] : '' }, level(v, q.unit));
      if (q.oco) marks.push(pill('OCO', 'neu', 'Biri yapılırsa öbürü iptal'));
      const time = h('td', { class: 'l' + (q.timed ? '' : ' soft'), title: q.timed ? '' : 'Mesajda saat yok: kaydedildiği an yazılır' }, q.timed ? q.time : 'şimdi');
      const whose = h('td', { class: 'l whose' + (q.party === 'biz' ? ' ours' : ''), title: (q.sender ? q.sender + ' · ' : '') + (q.party === 'biz' ? 'bizim fiyatımız' : (q.party ? 'broker fiyatı' : 'taraf belli değil')) },
        owner(q) || '?');
      if (!q.ok) {
        table.appendChild(h('tr', { class: 'txt' + (q.dup ? ' dup' : ''), title: q.dup ? KNOWN : '' }, time, whose, h('td', { class: 'l said', colspan: '4', title: q.raw }, q.raw),
          h('td', { class: 'l what soft' }, 'Metin', marks)));
        continue;
      }
      const who = [q.sender, q.raw].filter(Boolean).join(': ');
      table.appendChild(h('tr', { class: q.dup ? 'dup' : '', title: q.dup ? KNOWN : who }, time, whose,
        h('td', { class: 'l', title: instTip(q) }, h('b', null, instText(q)),
          q.kind === 'outright' ? null : h('span', { class: 'kind' }, (KIND[q.kind] || q.kind).toLowerCase() + (q.unit === 'bp' ? ' · bp' : ''))),
        numCell(q.bid), numCell(q.ask), numCell(q.price, q.event === 'trade' ? (q.side === 'ask' ? 'buy' : (q.side === 'bid' ? 'sell' : '')) : ''),
        h('td', { class: 'l what', title: impliedTip(q) }, eventText(q) + (q.implied ? ' · TRY ' + (impliedText(q) || '') + '%' : '') + (q.note ? ' · ' + q.note : ''), marks)));
    }
    if (rows.length) this.previewBox.appendChild(table);
    const fresh = rows.filter((q) => !q.dup);
    const quotes = fresh.filter((q) => q.ok).length;
    const parts = [quotes + ' kota'];
    if (fresh.length - quotes) parts.push((fresh.length - quotes) + ' metin satırı');
    if (rows.length - fresh.length) parts.push((rows.length - fresh.length) + ' satır zaten kayıtlı');
    const warn = rows.some((q) => (q.flags || []).some((f) => FLAG[f] && FLAG[f][1] === 'warn'));
    this.summary.textContent = rows.length ? parts.join(' · ') + (warn ? ' – işaretli satırlara bakın' : '') : 'Okunacak satır yok';
    if (warn) this.summary.className = 'warn-text';
    this.saveBtn.disabled = !fresh.length;
  }

  // ------------------------------------------------------------------ who is who
  /** The names of the paste: each with Broker / Biz and its house - changed here, kept for everyone. */
  fillNames(senders) {
    clear(this.namesBox);
    this.namesBox.classList.toggle('hidden', !senders.length);
    if (!senders.length) return;
    const fresh = senders.filter((s) => !s.known).length;
    this.namesBox.appendChild(h('div', { class: 'head' }, h('b', null, 'Bu chat\'teki isimler'),
      h('span', { class: fresh ? 'warn-text' : 'muted' }, fresh ? ' · ' + fresh + ' yeni isim: taraf ve kaynağını seçin, herkes için kaydedilir'
        : ' · hepsi listede')));
    for (const s of senders) {
      const src = h('input', { type: 'text', class: 'inp', maxlength: '40', placeholder: 'kaynak (örn. Tullett)', list: 'broker-sources', value: s.source || '' });
      const save = (party) => this.savePeople([{ name: s.name, source: src.value.trim(), party: party || s.party || '' }]);
      src.addEventListener('change', () => save());
      const seg = partySeg(s.party, (v) => { s.party = v; save(v); });
      this.namesBox.appendChild(h('div', { class: 'namerow' + (s.known ? '' : ' fresh') }, h('span', { class: 'nm', title: s.lines + ' satır' }, s.name),
        seg, src, s.known ? null : h('span', { class: 'pill warn' }, 'yeni')));
    }
  }

  async savePeople(items) {
    try {
      await api.post('/api/broker/people', { people: items });
      toast('İsim listesi kaydedildi', 'ok', 1800);
      this.doPreview();
      this.ctx.refreshNow();
    } catch (err) { errorToast(err); }
  }

  /** Every name: those of the list and every sender of the kept chats. */
  async openPeople() {
    const data = await api.get('/api/broker/people');
    const m = modal({ title: 'İsimler · kaynaklar', width: 760 });
    m.body.appendChild(h('div', { class: 'muted', style: { marginBottom: '8px', fontSize: '12px' } }, 'Chat\'lerde yazan her isim için: bizim masa mı, broker mı – ve hangi kurum. '
      + 'Yapıştırılan chat\'te bu isimlerin satırları kendiliğinden bu taraf ve kaynakla kaydedilir; kayıtlı satırlar da yeni listeyle gösterilir. Herkes için geçerlidir.'));
    const dl = h('datalist', { id: 'broker-people-sources' }, data.sources.map((x) => h('option', { value: x })));
    const table = h('table', { class: 'plain people', id: 'broker-people-table' }, h('tr', null, h('th', { class: 'l' }, 'İsim'), h('th', { class: 'l' }, 'Taraf'),
      h('th', { class: 'l' }, 'Kaynak'), h('th', null, 'Satır'), h('th', { class: 'l' }, 'Son')));
    const edits = [];
    const addRow = (p) => {
      const state = { name: p.name, party: p.party || '', source: p.source || '' };
      const nameCell = p.name ? h('td', { class: 'l b' }, p.name) : h('td', { class: 'l' });
      if (!p.name) {
        const inp = h('input', { type: 'text', class: 'inp', placeholder: 'İSİM SOYİSİM', maxlength: '60' });
        inp.addEventListener('input', () => { state.name = inp.value.trim(); });
        nameCell.appendChild(inp);
      }
      const src = h('input', { type: 'text', class: 'inp', maxlength: '40', list: 'broker-people-sources', value: state.source, placeholder: 'kaynak' });
      src.addEventListener('input', () => { state.source = src.value.trim(); });
      const clr = h('button', { class: 'iconbtn', type: 'button', title: 'Listeden çıkar' }, '✕');
      const seg = partySeg(state.party, (v) => { state.party = v; });
      clr.addEventListener('click', () => { state.party = ''; state.source = ''; src.value = ''; for (const b of seg.children) b.classList.remove('on'); });
      table.appendChild(h('tr', { class: p.known ? '' : 'fresh' }, nameCell, h('td', { class: 'l' }, seg), h('td', { class: 'l' }, src, clr),
        h('td', null, p.lines ? String(p.lines) : ''), h('td', { class: 'l' }, p.last ? isoToTr(p.last) : '')));
      edits.push(state);
    };
    for (const p of data.people) addRow(p);
    const more = h('button', { class: 'btn sm', type: 'button' }, '+ İsim ekle');
    more.addEventListener('click', () => addRow({ name: '', party: 'broker', source: '', known: false }));
    m.body.appendChild(dl);
    m.body.appendChild(h('div', { class: 'reftable' }, table));
    m.body.appendChild(h('div', { style: { marginTop: '8px' } }, more));
    const ok = h('button', { class: 'btn primary', type: 'button', id: 'broker-people-save' }, 'Kaydet');
    ok.addEventListener('click', async () => {
      ok.disabled = true;
      try {
        await api.post('/api/broker/people', { people: edits.filter((x) => x.name) });
        toast('İsim listesi kaydedildi', 'ok');
        m.close();
        this.doPreview();
        this.ctx.refreshNow();
      } catch (err) { errorToast(err); ok.disabled = false; }
    });
    m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Vazgeç'));
    m.foot.appendChild(ok);
    return m;
  }

  async save() {
    const text = this.text.value;
    if (!text.trim() || this.saving) return;
    this.saving = true;
    this.saveBtn.disabled = true;
    try {
      const source = this.source.value.trim();
      const res = await api.post('/api/broker', { text, date: this.entryDate.value || null, source, texts: this.keepTexts.checked, party: this.pasteParty });
      try { localStorage.setItem('tto.broker.source', source); } catch (e) { /* ignore */ }
      toast(res.saved + ' satır kaydedildi' + (res.skipped ? ' · ' + res.skipped + ' satır zaten kayıtlıydı' : ''), res.saved ? 'ok' : '', 3600);
      this.text.value = '';
      this.draft = '';
      this.parsed = null;
      this.seq += 1;
      this.showPreview();
      // show where the lines went when that is not what is on screen
      const days = res.dates || [];
      const inView = days.every((x) => x >= this.date && x <= (this.to || this.date));
      if (days.length && !inView) this.show(days[0], days.length > 1 ? days[days.length - 1] : null);
      else this.ctx.refreshNow();
    } catch (err) {
      errorToast(err);
      this.saveBtn.disabled = false;
    } finally { this.saving = false; }
  }
}
