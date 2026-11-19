// Kâğıt Fiyatlama's block of one bond (tto/kagitfiyat.py): its fair, the quote around it, the good levels, the market now
// against them, the context and how the price was built - what the page shows in a row and the bond's card in a block.
import { h } from './ui.js';
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

/** The block of one bond (the card's; ``row``: an answer's row of /api/kagit-fiyat). */
export function kagitBlock(row, rules) {
  const box = h('div', { class: 'kf-block', id: 'kf-card' });
  if (!row.priced) {
    box.appendChild(h('p', { class: 'muted kf-why', id: 'kf-card-why' }, 'Fiyatlanmadı: ' + (row.why || '')));
    return box;
  }
  const f = row.fair, q = row.quote, lv = row.levels, s = row.sigma || {};
  const kv = h('div', { class: 'kv kf-kv' });
  const item = (k, v, tip, id, cls) => kv.appendChild(h('div', { id: id || null }, h('span', { class: 'k' }, k),
    h('span', { class: 'v' + (cls ? ' ' + cls : ''), title: tip || null }, v)));
  item('Adil getiri (bileşik / basit)', yld(f.yield) + ' / ' + yld(f.simple), 'BIST bileşik ve basit getiri (DİBS RV!T / S gibi)', 'kf-card-fair', 'b');
  item('Adil fiyat (temiz)', px(f.clean) + (row.value_date ? ' · valör ' + day(row.value_date) : ''), 'Adil getirinin DİBS RV\'nin valöründeki temiz fiyatı', 'kf-card-price');
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
  if (row.note) box.appendChild(h('p', { class: 'muted kf-note', id: 'kf-card-note' }, row.note));
  return box;
}

export { short as shortDay };
