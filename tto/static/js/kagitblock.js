// Kâğıt Fiyatlama's block of one bond (tto/kagitfiyat.py): its fair, the projection (Öngörülen) at the horizon chosen, the
// fair values on DİBS Trading's two ASW curves (OIS'e göre, FX swap'a göre), the quote around the fair, the good levels, the
// market now against them, the context and how the price was built - what the page shows in a row and the bond's card in
// a block.
import { h, clear, toast, errorToast, copyText } from './ui.js';
import { num, parseNumber } from './format.js';
import { api } from './api.js';
import { quoteLang } from './kotasyon.js';

export const isNum = (v) => typeof v === 'number' && isFinite(v);
/** A yield (per cent) as the DİBS pages show it: 37,69. */
export const yld = (v) => (isNum(v) ? num(v, 2, false) : '–');
/** A clean price: 98,452. */
export const px = (v) => (isNum(v) ? num(v, 3, false) : '–');
/** bp with its sign: +8, −42. */
export const bp = (v) => {
  if (!isNum(v)) return '–';
  const r = Math.round(v);
  return (r > 0 ? '+' : r < 0 ? '−' : '') + num(Math.abs(r), 0);
};
/** A distance in σ: +1,2σ. */
export const sig = (v) => (isNum(v) ? (v > 0.049 ? '+' : v < -0.049 ? '−' : '') + num(Math.abs(v), 1, false) + 'σ' : '–');
export const day = (iso) => (iso ? iso.slice(8, 10) + '.' + iso.slice(5, 7) + '.' + iso.slice(0, 4) : '');
const short = (iso) => (iso ? iso.slice(8, 10) + '.' + iso.slice(5, 7) : '');

/** The backtest of the good levels as a short text: "isabet %67 (9)"; none: "isabet – (0)". */
export function hitText(bt) {
  if (!bt || !bt.n) return 'isabet – (0)';
  return 'isabet %' + Math.round(bt.hit * 100) + ' (' + bt.n + ')';
}

export function hitTip(bt, rules) {
  const r = rules || {};
  const n = r.revert || 5;
  const part = (x, what) => (x && x.n ? what + ': %' + Math.round(x.hit * 100) + ' (' + x.n + '), ort. ' + bp(x.avg) + ' bp' : what + ': yok');
  return 'Geçmişte kapanış adilin ±' + (r.band || 2) + 'σ ötesindeyken (σ o günkü: önceki ' + (r.window || 60) + ' hatadan, taban kovanın), '
    + n + ' kapanış sonra adile olan fark kapanmış mı - fark o günün tabanlarına göre, sinyalin önceki günkü farklarıyla ölçülür '
    + '(kâğıt tabanlarına karşı: tabanlarla hedge\'li işlemin kazancı, bp)'
    + (bt && bt.n ? '\nToplam: %' + Math.round(bt.hit * 100) + ' (' + bt.n + '), adile doğru ortalama ' + bp(bt.avg) + ' bp' : '')
    + '\n' + part(bt && bt.cheap, 'Ucuzken (Al)') + '\n' + part(bt && bt.rich, 'Pahalıyken (Sat)');
}

export function sigmaTip(s, row) {
  if (!s) return '';
  const floor = 'kovanın (' + (row.bucket_text || '') + ') tabanı ' + num(s.floor, 0) + ' bp';
  if (s.short) return 'σ = ' + floor + ': geçmiş kısa (' + s.n + ' sonraki-gün hatası; ölçmek için en az 20 gerekir)';
  return 'σ: son ' + s.n + ' kapanışta sonraki-gün hatasının sapması ' + num(s.sd, 1, false) + ' bp'
    + (s.floored ? ' → ' + floor + ' kullanıldı' : ' (' + floor + ')');
}

/** The market now: one quote against fair - "37,85 · +1,2σ" and AL / SAT. */
export function quoteText(m) {
  return yld(m.yield) + ' · ' + sig(m.z);
}

const SRC = { broker: 'Broker', bbg: 'Bloomberg' };
const SIDE = { bid: 'bid', ask: 'offer' };

export function marketTip(m) {
  const what = (m.src === 'broker' ? 'Broker Chat tahtası, en iyi taze ' + SIDE[m.side] + (m.who ? ' (' + m.who + ')' : '')
    : 'Bloomberg canlı ' + m.side + ' (DİBS RV)');
  return what + (isNum(m.price) ? ': fiyat ' + px(m.price) + ' → getiri ' : ': getiri ') + yld(m.yield) + ' (bileşik) · adilden ' + sig(m.z)
    + (m.signal === 'AL' ? '\nAL: offer adil + 2σ ya da üstünde (ucuz)' : m.signal === 'SAT' ? '\nSAT: bid adil − 2σ ya da altında (pahalı)' : '');
}

// ------------------------------------------------------------------ Öngörülen: the horizon and the projection
const HORIZON_KEY = 'tto.kf.ufuk';

/** The horizon (closes) the viewer last chose (kept in this browser), else the page's default (the best record). */
export function horizonOf(projection) {
  const hs = ((projection || {}).horizons || []).map((x) => x.h);
  let saved = null;
  try { saved = Number(window.localStorage.getItem(HORIZON_KEY)); } catch (err) { saved = null; }
  if (hs.includes(saved)) return saved;
  return (projection || {}).default || hs[hs.length - 1] || 20;
}

export function setHorizon(hz) {
  try { window.localStorage.setItem(HORIZON_KEY, String(hz)); } catch (err) { /* (a private window: this page only) */ }
}

/** The horizon switch: 1 hafta / 2 hafta / 1 ay (``idp``: the buttons' id prefix, "kf-ufuk-" + closes). */
export function horizonSwitch(projection, current, onPick, idp) {
  const box = h('span', { class: 'seg kf-ufuk', title: 'Öngörülen getirinin ufku (iş günü): seçim bu tarayıcıda kalır' });
  for (const x of (projection || {}).horizons || []) {
    const b = h('button', { type: 'button', class: x.h === current ? 'on' : null, id: idp + x.h,
      title: x.text + ': ' + x.h + ' iş günü sonra, ' + day(x.day) }, x.text);
    b.addEventListener('click', () => { setHorizon(x.h); onPick(x.h); });
    box.appendChild(b);
  }
  return box;
}

/** A bond's projection at a horizon (``row.proj``'s), or null. */
export function projAt(row, hz) {
  const p = row && row.proj;
  return p && p.h ? p.h[String(hz)] || null : null;
}

/** A signed TL amount: +12.345. */
export const tl = (v) => (isNum(v) ? (Math.round(v) > 0 ? '+' : Math.round(v) < 0 ? '−' : '') + num(Math.abs(Math.round(v)), 0) : '–');

/** The model in a word: "M4" / "eğri ve fark değişmezse". */
export const modelShort = (e) => (e.model === 'M2' ? 'eğri+fark sabit' : e.model + (e.window ? '/' + e.window : ''));

/** How the projection was made and its record (a tooltip / the line under the bond). */
export function projTip(e, p) {
  if (!e) return '';
  const parts = [];
  if (e.why) parts.push(e.why + ' → eğri ve fark değişmezse gösteriliyor');
  if (e.line) parts.push(e.line);
  if (!e.beat) parts.push('Bu vadede ve ufukta hiçbir model "değişmez"i %5 yenemedi: öngörülen, eğri ve fark değişmezse');
  parts.push(e.record);
  if (p && p.from === 'kapanış') parts.push('Ekranda getiri yok: şimdiki getiri komşu eğri şimdi + son kapanıştaki fark');
  return parts.join('\n');
}

/** "OIS'e göre" / "FX swap'a göre": DİBS Trading's fair yield and price of the bond on that ASW curve. */
export function aswTip(side, name) {
  if (!side) return '';
  return side.why ? side.why : name + ' (DİBS Trading ile aynı): ' + (side.tip || '');
}

/** The curve price of a bond in a line (the main table's Piyasa / Eğri / Fiyat): the answer and its label first. */
export function curveLine(c) {
  const p = c.price;
  const line = h('p', { class: 'kf-curve-line', id: 'kf-card-curve', title: p ? (p.how || '') : (c.why || '') }, h('b', null, 'Eğri fiyatı: '));
  if (!p) {
    line.appendChild(h('span', { class: 'muted' }, c.why || 'fiyatı yok'));
    return line;
  }
  line.append(h('b', null, yld(p.yield) + ' · ' + px(p.clean)), ' (' + p.label + ', valör ' + day(c.value_date) + ')',
    h('span', { class: 'muted' }, ' · piyasa ' + (c.market ? yld(c.market.yield) + ' · ' + px(c.market.clean) : '—')
      + ' · eğri ' + (c.curve ? (c.curve.base && c.curve.base !== 'eğri' ? '(taban: ' + c.curve.base + ') ' : '') + yld(c.curve.yield) + ' · ' + px(c.curve.clean) : '—')
      + (isNum(c.diff) ? ' · fark ' + bp(c.diff) + ' bp' : '')));
  return line;
}

/** The block of one bond (the card's; ``row``: an answer's row of /api/kagit-fiyat - none for a bond off the trading list -,
 * ``projection``: its "projection", ``curve``: its row of the main table, the curve price). */
export function kagitBlock(row, rules, projection, curve) {
  const box = h('div', { class: 'kf-block', id: 'kf-card' });
  const draw = (hz) => {
    clear(box);
    if (curve) box.appendChild(curveLine(curve));
    if (row) fillBlock(box, row, rules, projection, hz, draw);
    else box.appendChild(h('p', { class: 'muted', id: 'kf-card-why' }, 'Adil, kota, iyi seviyeler ve öngörülen yalnız trading listesindeki kâğıtlar için'));
  };
  draw(horizonOf(projection));
  return box;
}

function fillBlock(box, row, rules, projection, hz, redraw) {
  const asw = row.asw || {};
  const kv = h('div', { class: 'kv kf-kv' });
  const item = (k, v, tip, id, cls) => kv.appendChild(h('div', { id: id || null }, h('span', { class: 'k' }, k),
    h('span', { class: 'v' + (cls ? ' ' + cls : ''), title: tip || null }, v)));
  const aswItems = () => {
    for (const [key, name] of [['ois', "OIS'e göre"], ['fx', "FX swap'a göre"]]) {
      const a = asw[key];
      if (!a) continue;
      item(name + ' adil getiri / fiyat', a.why ? '–' : yld(a.yield) + ' / ' + px(a.price), aswTip(a, name), 'kf-card-' + key, a.soft || a.why ? 'soft' : '');
    }
  };
  if (!row.priced) {
    box.appendChild(h('p', { class: 'muted kf-why', id: 'kf-card-why' }, 'Fiyatlanmadı: ' + (row.why || '')));
    aswItems();
    if (kv.children.length) box.appendChild(kv);
    return;
  }
  const f = row.fair, q = row.quote, lv = row.levels, s = row.sigma || {};
  item('Adil getiri (bileşik / basit)', yld(f.yield) + ' / ' + yld(f.simple), 'BIST bileşik ve basit getiri (DİBS RV!T / S gibi)', 'kf-card-fair', 'b');
  item('Adil fiyat (temiz)', px(f.clean) + (row.value_date ? ' · valör ' + day(row.value_date) : ''), 'Adil getirinin DİBS RV\'nin valöründeki temiz fiyatı', 'kf-card-price');
  const e = projAt(row, hz);
  const p = row.proj || {};
  const sw = h('div', { class: 'kf-card-ufuk' }, h('span', { class: 'k' }, 'Öngörülen ufku '),
    horizonSwitch(projection, hz, (x) => redraw(x), 'kf-card-ufuk-'));
  if (e && isNum(e.yield)) {
    const tip = projTip(e, p);
    item('Öngörülen getiri (bileşik / basit)', yld(e.yield) + ' / ' + yld(e.simple), tip, 'kf-card-proj', 'b');
    item('Öngörülen fiyat (temiz)', px(e.clean) + ' · valör ' + day(e.value_date), 'Öngörülen getirinin ufkun valöründeki temiz fiyatı', 'kf-card-proj-price');
    item('Değişim (bp · K/Z 1 mn)', bp(e.bp) + ' bp · ' + tl(e.pnl) + ' TL', 'Şimdiki getiriden öngörülene (bileşik, bp) ve 1 mn nominal alışın bu değişimden '
      + 'K/Z\'si: ufkun valöründe iki getirinin temiz fiyat farkı × 10.000 (taşıma ve fonlama dahil değil)', 'kf-card-proj-chg', e.bp < 0 ? 'pos' : e.bp > 0 ? 'neg' : '');
    item('Model', (e.model === 'M2' ? '' : e.model + ' · ') + e.model_text, tip, 'kf-card-proj-model', e.beat && !e.why ? '' : 'soft');
  } else {
    item('Öngörülen', '–', (e && e.why) || p.why || 'öngörülen yok', 'kf-card-proj', 'soft');
  }
  aswItems();
  item('Kotan (bid / ask getiri)', yld(q.bid.yield) + ' / ' + yld(q.ask.yield), 'Adil ± genişliğin yarısı; genişlik ' + num(q.width, 1, false)
    + ' bp (kovanın, yöneticiler değiştirir) · fiyat ' + px(q.bid.clean) + ' / ' + px(q.ask.clean), 'kf-card-quote');
  item('Kotan (bid / ask fiyat)', px(q.bid.clean) + ' / ' + px(q.ask.clean), '', 'kf-card-quote-px');
  item('Al ≥ (getiri · fiyat)', yld(lv.buy.yield) + ' · ' + px(lv.buy.clean), 'Adil + 2σ: getiri bunun üstündeyse ucuz - al', 'kf-card-buy', 'pos');
  item('Sat ≤ (getiri · fiyat)', yld(lv.sell.yield) + ' · ' + px(lv.sell.clean), 'Adil − 2σ: getiri bunun altındaysa pahalı - sat', 'kf-card-sell', 'neg');
  item('Gürültü (±1σ)', yld(lv.noise[0].yield) + ' – ' + yld(lv.noise[1].yield), 'Bu bantta kalan fark gürültü', 'kf-card-noise');
  item('σ', num(s.sigma, 0) + ' bp' + (s.short ? ' (taban)' : ''), sigmaTip(s, row), 'kf-card-sigma');
  item('Geri test', hitText(row.backtest), hitTip(row.backtest, rules), 'kf-card-hit');
  if (row.context && isNum(row.context.now)) {
    item('Komşu eğriye fark (şimdi · 20 gün medyan)', bp(row.context.now) + ' · ' + bp(row.context.median) + ' bp',
      'Kâğıdın şimdiki getirisi − komşu eğri (bp), son ' + (row.context.n || 0) + ' kapanıştaki medyanının yanında', 'kf-card-ctx');
  }
  if (isNum(row.z)) item('Ekran getirisi', yld(row.yield) + ' · ' + sig(row.z), 'DİBS RV!T şimdi, adilden σ cinsinden uzaklığı', 'kf-card-now');
  box.appendChild(sw);
  box.appendChild(kv);
  const mk = row.market || [];
  const mline = h('p', { class: 'kf-mkt', id: 'kf-card-market' }, h('b', null, 'Piyasa şimdi: '));
  if (!mk.length) mline.appendChild(h('span', { class: 'muted' }, 'taze broker kotası ve canlı Bloomberg kotası yok'));
  mk.forEach((m, i) => {
    if (i) mline.appendChild(document.createTextNode(' · '));
    mline.appendChild(h('span', { title: marketTip(m), class: m.signal ? 'kf-sig ' + (m.signal === 'AL' ? 'pos' : 'neg') : '' },
      SRC[m.src] + ' ' + SIDE[m.side] + ' ' + quoteText(m) + (m.signal ? ' ' + m.signal : '')));
  });
  box.appendChild(mline);
  box.appendChild(h('p', { class: 'kf-howline', id: 'kf-card-how' }, h('b', null, 'Nasıl fiyatlandı: '), row.line || ''));
  if (e) {
    box.appendChild(h('p', { class: 'kf-howline', id: 'kf-card-proj-how' }, h('b', null, 'Öngörülen: '), e.line || e.why || '',
      h('br'), h('span', { class: 'muted' }, e.record + (e.why && e.line ? ' · ' + e.why : ''))));
  }
  if (row.note) box.appendChild(h('p', { class: 'muted kf-note', id: 'kf-card-note' }, row.note));
}

export { short as shortDay };

// ------------------------------------------------------------------ the desk's quote: copied, logged (A14, 28.11.2026)
/**
 * A quote given, into the day's quote log (Günlük İşlemler · "Verilen kotalar": done / not done, the hit ratio) - when the
 * dashboard has it (``POST /api/quote-log``); without it nothing happens: the copy is the user's either way.
 */
export function logQuote(entry) {
  return api.post('/api/quote-log', Object.assign({ product: 'DİBS', status: 'open' }, entry)).catch(() => null);
}

/** The desk's quote of bonds (Kâğıt Fiyatlama's "Kotan": fair ± half the bucket's width) as a message: a line a bond. */
export function deskQuoteText(rows, lang, day0) {
  const en = lang === 'en';
  const n = (v, d) => (isNum(v) ? (en ? v.toFixed(d) : num(v, d, false)) : '–');
  const head = (en ? 'TRY govt bonds · our quote' : 'DİBS · masanın kotası') + (day0 ? ' · ' + day0 : '')
    + (en ? ' · yield % (compound) bid / ask · clean price' : ' · bileşik getiri % bid / ask · temiz fiyat');
  const w = Math.max(8, ...rows.map((r) => (r.label || r.isin).length));
  return [head].concat(rows.map((r) => (r.label || r.isin).padEnd(w + 2) + n(r.quote.bid.yield, 2) + ' / ' + n(r.quote.ask.yield, 2)
    + '   ' + n(r.quote.bid.clean, 3) + ' / ' + n(r.quote.ask.clean, 3) + (r.valor ? '   ' + (en ? 'value ' : 'valör ') + r.valor : ''))).join('\n');
}

/** Copy the desk's quote of these bonds (each logged as a quote given). */
export async function copyDeskQuote(rows, page, day0) {
  const priced = rows.filter((r) => r && r.priced && r.quote);
  if (!priced.length) { toast('Kotası olan kâğıt yok (adil kurulamadı)', 'warn'); return false; }
  const lang = quoteLang();
  const ok = await copyText(deskQuoteText(priced, lang, day0), 'Masanın kotası kopyalandı (' + priced.length + ' kâğıt)');
  if (ok) {
    for (const r of priced) {
      logQuote({ instrument: r.isin, levels: { bid: r.quote.bid.yield, ask: r.quote.ask.yield, mid: r.fair.yield },
        source: 'Kâğıt Fiyatlama · masanın kotası (' + (r.label || r.isin) + ', ' + num(r.quote.width, 1, false) + ' bp)', page });
    }
  }
  return ok;
}

// ------------------------------------------------------------------ AL / SAT as alarms (C13, 28.11.2026)
/**
 * "Piyasa AL / SAT'a gelince alarm": two alarms of the user's on the bond's screen yield (DİBS RV!T) against Kâğıt
 * Fiyatlama's levels, by their names ("[12.09.29 getiri] − [12.09.29 AL] ≥ 0 bp" - the AL level follows the fair as it
 * moves), so the page need not be open.
 */
export function alarmButton(row, idp) {
  const b = h('button', { class: 'btn sm kf-alarm', type: 'button', id: (idp || 'kf-alarm-') + row.isin,
    title: 'İki alarm kurar (İzleme · Alarmlar): ekran getirisi AL seviyesine (adil + 2σ, ucuz) çıkınca ve SAT seviyesine (adil − 2σ, '
      + 'pahalı) inince. Seviyeler Kâğıt Fiyatlama\'nın - adil oynadıkça onlar da oynar; alarm adlarında [' + (row.label || row.isin)
      + ' adil / AL / SAT]' }, 'Piyasa AL / SAT\'a gelince alarm');
  b.addEventListener('click', async () => {
    b.disabled = true;
    const name = row.label || row.isin;
    const sets = [['AL', '>=', 'ucuz: al'], ['SAT', '<=', 'pahalı: sat']];
    try {
      for (const [lvl, op, what] of sets) {
        await api.post('/api/alarms/add', { subject: { kind: 'expr', text: '[' + row.isin + ' getiri] - [' + row.isin + ' ' + lvl + ']' },
          op, level: 0, label: name + ' ' + lvl + ' seviyesinde', note: 'Kâğıt Fiyatlama: ekran getirisi ' + lvl + ' seviyesine geldi (' + what + ')' });
      }
      toast(name + ': AL ve SAT alarmları kuruldu (İzleme · Alarmlar)', 'ok', 5000);
    } catch (err) { errorToast(err); } finally { b.disabled = false; }
  });
  return b;
}

// ------------------------------------------------------------------ the quote ticket at any value date (C10, 28.11.2026)
const TICKET_PREF = 'tto.kf.fis';                     // the ticket's last nominal, centre and value date (this browser)

function ticketPref() {
  try { return JSON.parse(window.localStorage.getItem(TICKET_PREF) || '{}') || {}; } catch (e) { return {}; }
}

function setTicketPref(p) {
  try { window.localStorage.setItem(TICKET_PREF, JSON.stringify(p)); } catch (e) { /* (a private window: this page only) */ }
}

/**
 * The quote ticket of one bond (the bond card's Kâğıt Fiyatlama block): value date (T0 / T1 / T2 or a date), nominal, centre
 * (piyasa, Kâğıt Fiyatlama fiyatı, adil or a yield typed) and spread (bp, bid to ask) → bid / ask yields (compound, simple),
 * clean and dirty prices at that value date, the amounts, the nominal's DV01 and its OIS hedge (``GET
 * /api/kagit-fiyat?ticket=1``); "Kopyala" the quote to send (logged as a quote given), "İşlem gir" Günlük İşlemler filled.
 */
export function ticketBox(ctx, isin, opts = {}) {
  const pref = ticketPref();
  const box = h('div', { class: 'kf-ticket', id: 'kf-ticket' });
  const st = { valor: opts.valor || pref.valor || 'T1', nominal: pref.nominal || '10m', center: pref.center || '', level: '', spread: '' };
  const seg = h('span', { class: 'seg kf-ticket-valor', id: 'kf-ticket-valor', title: 'Valör: T0 bugün, T1 ertesi iş günü, T2 iki iş günü sonra (TRY tatilleri) - ya da bir tarih yazın' });
  const date = h('input', { class: 'inp kf-ticket-date', id: 'kf-ticket-date', placeholder: 'tarih', size: '9', title: 'Başka bir valör: tarih (gg.aa.yyyy)' });
  const nominal = h('input', { class: 'inp kf-ticket-nominal', id: 'kf-ticket-nominal', size: '9', value: st.nominal, title: 'Nominal (TL): 10m, 2,5mn, 500k ya da sayı' });
  const center = h('select', { class: 'inp kf-ticket-center', id: 'kf-ticket-center', title: 'Merkez: kotanın ortası' });
  const level = h('input', { class: 'inp kf-ticket-level hidden', id: 'kf-ticket-level', size: '6', placeholder: 'getiri %', title: 'Merkez bileşik getiri (%): 39,50' });
  const spread = h('input', { class: 'inp kf-ticket-spread', id: 'kf-ticket-spread', size: '5', placeholder: 'bp', title: 'Spread (bp, bid ile ask arası): boşsa kovanın kotasyon genişliği' });
  const out = h('div', { class: 'kf-ticket-out', id: 'kf-ticket-out' }, h('p', { class: 'muted' }, 'hesaplanıyor…'));
  const copy = h('button', { class: 'btn sm', type: 'button', id: 'kf-ticket-copy', disabled: true }, 'Kopyala');
  const buy = h('button', { class: 'btn sm', type: 'button', id: 'kf-ticket-buy', disabled: true, title: 'Günlük İşlemler: alış (masanın bid\'i), kâğıt, nominal ve temiz fiyat dolu' }, 'İşlem gir · alış (bid)');
  const sell = h('button', { class: 'btn sm', type: 'button', id: 'kf-ticket-sell', disabled: true, title: 'Günlük İşlemler: satış (masanın ask\'i), kâğıt, nominal ve temiz fiyat dolu' }, 'İşlem gir · satış (ask)');
  box.append(h('div', { class: 'kf-ticket-in' },
    h('label', { class: 'field inline' }, 'Valör', seg, date), h('label', { class: 'field inline' }, 'Nominal', nominal),
    h('label', { class: 'field inline' }, 'Merkez', center, level), h('label', { class: 'field inline' }, 'Spread (bp)', spread)), out,
  h('div', { class: 'kf-ticket-acts' }, copy, buy, sell));
  let last = null;
  let seq = 0;
  const fill = (t) => {
    // the value dates offered (T0 / T1 / T2: each its day) and the centres the bond has
    clear(seg);
    for (const v of t.valors || []) {
      const b = h('button', { type: 'button', class: v.key === st.valor ? 'on' : null, id: 'kf-ticket-' + v.key, title: v.date }, v.text);
      b.addEventListener('click', () => { st.valor = v.key; date.value = ''; run(); });
      seg.appendChild(b);
    }
    clear(center);
    for (const [k, name] of [['piyasa', 'Piyasa'], ['fiyat', 'Kâğıt Fiyatlama fiyatı'], ['adil', 'Adil'], ['yazilan', 'Yazılan getiri']]) {
      const c = (t.centers || {})[k];
      if (k !== 'yazilan' && !c) continue;
      center.appendChild(h('option', { value: k, selected: t.center.kind === k ? 'selected' : null },
        name + (c ? ' · ' + yld(c.yield) : '')));
    }
    level.classList.toggle('hidden', t.center.kind !== 'yazilan');
    if (!spread.value) spread.placeholder = num(t.width, 1, false) + ' bp';
    const tr = (name, f, d, id) => h('tr', { id: id || null }, h('th', { class: 'l' }, name), h('td', null, f(t.bid, d)), h('td', null, f(t.ask, d)));
    const v = (x, k, d) => (isNum(x[k]) ? num(x[k], d, k === 'amount') : '–');
    const tbl = h('table', { class: 'plain nums kf-ticket-table', id: 'kf-ticket-table' },
      h('tr', null, h('th', null, ''), h('th', null, 'Bid (alış)'), h('th', null, 'Ask (satış)')),
      tr('Bileşik getiri %', (x) => v(x, 'yield', 2), 2, 'kf-ticket-y'), tr('Basit getiri %', (x) => v(x, 'simple', 2), 2, 'kf-ticket-s'),
      tr('Temiz fiyat', (x) => v(x, 'clean', 3), 3, 'kf-ticket-c'), tr('Kirli fiyat', (x) => v(x, 'dirty', 3), 3, 'kf-ticket-d'),
      tr('Tutar (TL)', (x) => v(x, 'amount', 0), 0, 'kf-ticket-a'));
    const hedge = t.hedge || {};
    clear(out).append(tbl, h('p', { class: 'muted kf-ticket-line', id: 'kf-ticket-line' },
      'Valör ' + day(t.valor.date) + ' (' + t.valor.t + ') · merkez ' + t.center.name + ' ' + yld(t.center.yield)
      + ' · spread ' + num(t.spread, 1, false) + ' bp · DV01 ', h('b', { id: 'kf-ticket-dv01' }, isNum(t.dv01) ? num(t.dv01, 0) + ' TL' : '–'),
      ' · OIS hedge ', h('b', { id: 'kf-ticket-hedge', title: hedge.how || '' }, isNum(hedge.nominal) ? num(hedge.nominal, 0) + ' TL' : '–'),
      isNum(hedge.ratio) ? ' (oran ' + num(hedge.ratio, 3, false) + ')' : ''));
    out.title = t.center.how || '';
    copy.disabled = buy.disabled = sell.disabled = false;
  };
  const run = async () => {
    const my = ++seq;
    const q = { ticket: 1, isin, valor: date.value.trim() || st.valor, nominal: nominal.value.trim() || '10m', language: quoteLang() };
    if (center.value) q.center = center.value;
    if (center.value === 'yazilan') q.level = level.value.trim();
    if (spread.value.trim()) q.spread = String(parseNumber(spread.value.trim()));
    setTicketPref({ valor: st.valor, nominal: nominal.value.trim(), center: center.value || st.center });
    try {
      const t = await api.get('/api/kagit-fiyat', q);
      if (my !== seq) return;
      last = t;
      fill(t);
    } catch (err) {
      if (my !== seq) return;
      last = null;
      copy.disabled = buy.disabled = sell.disabled = true;
      clear(out).appendChild(h('p', { class: 'muted', id: 'kf-ticket-why' }, (err && err.message) || 'Fiyatlanmadı'));
    }
  };
  for (const el of [date, nominal, level, spread]) el.addEventListener('change', run);
  center.addEventListener('change', () => { level.classList.toggle('hidden', center.value !== 'yazilan'); if (center.value !== 'yazilan' || level.value.trim()) run(); });
  copy.addEventListener('click', async () => {
    if (!last) return;
    const ok = await copyText(last.text, 'Kotasyon kopyalandı');
    if (ok) {
      logQuote({ instrument: last.isin, size: last.nominal, levels: { bid: last.bid.yield, ask: last.ask.yield, mid: last.mid.yield },
        source: 'Kotasyon fişi · ' + last.label + ' · valör ' + day(last.valor.date), page: opts.page || 'kagit-fiyat' });
    }
  });
  const trade = (dir) => {
    if (!last || !ctx.openTrade) return;
    const side = dir === 'B' ? last.bid : last.ask;
    ctx.openTrade({ kind: 'bond', dir, instrument: last.isin, amount: String(Math.round(last.nominal)), price: num(side.clean, 3, false),
      note: 'Kotasyon fişi · valör ' + day(last.valor.date) + ' (' + last.valor.t + ') · getiri ' + yld(side.yield) + ' (bileşik)' });
  };
  buy.addEventListener('click', () => trade('B'));
  sell.addEventListener('click', () => trade('S'));
  run();
  return box;
}
