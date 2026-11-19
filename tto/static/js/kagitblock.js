// Kâğıt Fiyatlama's block of one bond (tto/kagitfiyat.py): its fair, the projection (Öngörülen) at the horizon chosen, the
// fair values on DİBS Trading's two ASW curves (OIS'e göre, FX swap'a göre), the quote around the fair, the good levels, the
// market now against them, the context and how the price was built - what the page shows in a row and the bond's card in
// a block.
import { h, clear } from './ui.js';
import { num } from './format.js';

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

/** The block of one bond (the card's; ``row``: an answer's row of /api/kagit-fiyat, ``projection``: its "projection"). */
export function kagitBlock(row, rules, projection) {
  const box = h('div', { class: 'kf-block', id: 'kf-card' });
  const draw = (hz) => {
    clear(box);
    fillBlock(box, row, rules, projection, hz, draw);
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
