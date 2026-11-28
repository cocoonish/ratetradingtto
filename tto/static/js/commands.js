// Ctrl+K commands: beside finding tables (find.js), the box understands a few commands - shown first as one types, Enter
// runs them, Esc leaves.  A command never saves anything by itself: it opens a dialog (RET - "ret yayınla" on the fair
// value tab: publishing is the user's "Kopyala ve yayınla"), fills a form for the user to save (Günlük İşlemler, Trades,
// the trading list's "+ ISIN ekle"), loads a saved scenario after a confirmation naming it, or opens a page / launchpad.
// Turkish and ASCII spellings alike (ı/i, ş/s, ğ/g …), any case:
//
//   ret · ret yayınla · ret elle          the RET dialog (yayınla / adil: the fair value tab; elle / gir: the manual one)
//   işlem gir <parite> <vade> <tutar>     Günlük İşlemler's forward form: "işlem gir usdtry 1m 10mn", "işlem gir eurtry 3a 5m"
//                                         (the value date: the tenor from the pair's own spot, as the form reads a shortcut)
//   işlem gir [ois] <enstrüman> <yön> …   its OIS form (the desk, 28.11.2026, A4): "işlem gir ois 2y rec 10k", "1y2y steepener",
//                                         "1y/2y/3y rec gövde", "9x12 pay", "dec mpc pay", "@35,50" a level, "dv01 5k" / "500m tl"
//   işlem gir dibs <kâğıt> <tutar> <yön>  its bond form: "işlem gir dibs mar28 50m al" (an ISIN, "mar28", "15.03.28": the server
//                                         finds the ISIN); every suggestion names the book - Günlük İşlemler is the position
//   fiyatla <ürün> …                      Fiyatlama filled through its address (#/fiyatlama?asset=…&end=…: the page reads it):
//                                         "fiyatla ois 2y3m rec 10k", "fiyatla fra 12x15", "fiyatla usdtry 3m al 10m"
//   trade <ürün> …                        the Trades form: "trade ois 1y 5mn", "trade dibs TRT150328T24 10m", "trade spot usdtry 5m"
//   kâğıt ekle <ISIN …>                   the trading list's "+ ISIN ekle" with the ISINs in it (one or many)
//   senaryo <ad>                          a saved scenario loaded (asked first); S1 / S2 / S3 (piyasa): the RET fair value's view
//   sayfa <ad> · launchpad <ad>           a page; one of the user's launchpads
//
// ``parseCommand(text, env)`` reads the text alone (no DOM, nothing asked of the server: this module imports format.js
// only - tests/test_commands.py runs it under Node): null when it is no command, else the suggestions - {cmd, label, note,
// …} to run, {error, label} what was expected, {complete, label} a command's template (Enter writes it into the box).
// commandrun.js does them.
import { parseAmount, pairOf } from './format.js';

/** "İşlem Gİr" -> "islem gir": lower case the Turkish way, then the letters without their marks (ı ş ğ ü ö ç â î û). */
export function fold(s) {
  return String(s || '').toLocaleLowerCase('tr').replace(/ı/g, 'i').normalize('NFD').replace(/[̀-ͯ]/g, '');
}

/** The commands as the box offers them while their first word is being typed (Enter writes ``full`` into the box). */
const COMMANDS = [
  { word: 'ret', full: 'ret ', text: 'ret · ret yayınla · ret elle', note: 'RET penceresi (yayınla: adil değer sekmesi)' },
  { word: 'islem', full: 'işlem gir ', text: 'işlem gir <parite | ois | dibs> …',
    note: 'Günlük İşlemler formu (pozisyon), örn. işlem gir usdtry 1m 10mn · işlem gir ois 2y rec 10k · işlem gir dibs mar28 50m al' },
  { word: 'fiyatla', full: 'fiyatla ', text: 'fiyatla <ois | fra | xccy | parite> …', note: 'Fiyatlama dolu açılır, örn. fiyatla ois 2y3m rec 10k' },
  { word: 'trade', full: 'trade ', text: 'trade <ürün> <vade | ISIN | parite> <tutar>', note: 'Trades formu (izleme, pozisyona girmez), örn. trade ois 1y 5mn' },
  { word: 'kagit', full: 'kâğıt ekle ', text: 'kâğıt ekle <ISIN …>', note: 'trading listesine "+ ISIN ekle", örn. kâğıt ekle TRT150328T24' },
  { word: 'senaryo', full: 'senaryo ', text: 'senaryo <ad>', note: 'kayıtlı senaryoyu yükle · S1 / S2 / S3: RET adil değer görünümü' },
  { word: 'sayfa', full: 'sayfa ', text: 'sayfa <ad>', note: 'bir sayfayı aç, örn. sayfa ois' },
  { word: 'launchpad', full: 'launchpad ', text: 'launchpad <ad>', note: 'launchpad\'lerinizden birini aç' },
];

const SIDE_FX = { al: 'B', alis: 'B', alim: 'B', buy: 'B', long: 'B', sat: 'S', satis: 'S', satim: 'S', sell: 'S', short: 'S' };
const SIDE_RATE = { rec: 'receive', receive: 'receive', receiver: 'receive', pay: 'pay', payer: 'pay' };
// Günlük İşlemler's OIS: the words of a side (a spread's and a fly's too), the words that say the product, the meetings'
// months (an MPC period "dec mpc": the one from the next December decision), the form's tenors (blotter.OIS_TENORS)
const OIS_SIDE_WORDS = { rec: 'rec', receive: 'rec', receiver: 'rec', pay: 'pay', payer: 'pay', steepener: 'steep', steep: 'steep',
  stp: 'steep', flattener: 'flat', flat: 'flat', flt: 'flat' };
const OIS_WORDS = { ois: 'ois', tryois: 'ois', fra: 'fra', mpc: 'mpc', ppk: 'mpc' };
const BOND_WORDS = { dibs: 1, tahvil: 1, bono: 1, kagit: 1 };
const BODY_WORDS = { govde: 1, body: 1 };
const MONTHS = { jan: 1, oca: 1, ocak: 1, feb: 2, sub: 2, subat: 2, mar: 3, mart: 3, apr: 4, nis: 4, nisan: 4, may: 5, mayis: 5,
  jun: 6, haz: 6, haziran: 6, jul: 7, tem: 7, temmuz: 7, aug: 8, agu: 8, agustos: 8, sep: 9, sept: 9, eyl: 9, eylul: 9,
  oct: 10, eki: 10, ekim: 10, nov: 11, kas: 11, kasim: 11, dec: 12, ara: 12, aralik: 12 };
const MONTH_TEXT = ['Ocak', 'Şubat', 'Mart', 'Nisan', 'Mayıs', 'Haziran', 'Temmuz', 'Ağustos', 'Eylül', 'Ekim', 'Kasım', 'Aralık'];
const OIS_TENORS = ['ON', '1W', '2W', '1M', '2M', '3M', '6M', '9M', '1Y', '15M', '18M', '21M', '2Y', '3Y', '4Y', '5Y', '6Y', '7Y', '8Y',
  '9Y', '10Y'];
const OIS_SIDE_TEXT = { 'PAY K+1 / REC K': 'PAY k+1 / REC k', 'REC K+1 / PAY K': 'REC k+1 / PAY k' };
// Fiyatlama's instruments (tto/pricing.py ASSETS) and how they are said
const PRICING_ASSETS = { ois: 'ois', tryois: 'ois', fra: 'fra', xccy: 'xccy', ccs: 'xccy', fx: 'fx', forward: 'fx', fwd: 'fx' };
const PRICING_TEXT = { ois: 'TRY OIS', fra: 'FRA', xccy: 'XCCY', fx: 'FX forward' };
const CALL_PUT = { call: 'call', put: 'put' };
const PRODUCTS = { ois: 'ois', tryois: 'ois', sofr: 'sofr', usdois: 'sofr', dibs: 'dibs', tahvil: 'dibs', bono: 'dibs', spot: 'fxspot',
  fxspot: 'fxspot', fx: 'fxspot', opsiyon: 'fxopt', opt: 'fxopt', option: 'fxopt', fxopt: 'fxopt' };
const PRODUCT_TEXT = { ois: 'TRY OIS', sofr: 'SOFR', dibs: 'DİBS', fxspot: 'FX spot', fxopt: 'FX opsiyon' };
const RET_TABS = { yayinla: 'fair', yayin: 'fair', adil: 'fair', fair: 'fair', elle: 'manual', gir: 'manual', giris: 'manual', manual: 'manual' };
const ISIN = /^[A-Z]{2}[A-Z0-9]{9}\d$/;
const PPK = ['S1', 'S2', 'S3'];

/** A value date typed the desk's way (tto/shortcuts.py): a tenor (1m, 3a, 1y, 2h), ON / TN / SN, ay sonu, IMM, +5 - or a
 *  date.  Returns the text to put in the form, or null. */
export function tenorOf(token) {
  const s = fold(token).replace(/\s+/g, '');
  if (/^\d{1,3}(a|ay|m|y|yil|h|w)$/.test(s)) return s.toUpperCase().replace('YIL', 'Y').replace('AY', 'A');
  if (/^(on|o\/n|tn|t\/n|sn|s\/n)$/.test(s)) return s.toUpperCase();
  if (/^(aysonu|eom)$/.test(s)) return 'ay sonu';
  if (s === 'imm') return 'IMM';
  if (/^\+\d{1,3}$/.test(s)) return s;
  if (/^\d{1,2}[./-]\d{1,2}([./-]\d{2,4})?$/.test(s)) return token;
  return null;
}

/** An amount typed the desk's way ("10mn", "5m", "500k", "2,5m"): the text as typed, or null. */
function amountOf(token) {
  return /\d/.test(token) && parseAmount(token) !== null ? token : null;
}

const tokens = (text) => String(text || '').trim().split(/\s+/).filter(Boolean);
const err = (label, error) => [{ error: error || label, label }];

/** Join "ay" "sonu" (the month end typed in two words) into one token. */
function joinMonthEnd(raw) {
  const out = [];
  for (let i = 0; i < raw.length; i++) {
    if (fold(raw[i]) === 'ay' && i + 1 < raw.length && fold(raw[i + 1]) === 'sonu') { out.push('ay sonu'); i += 1; } else out.push(raw[i]);
  }
  return out;
}

// ---------------------------------------------------------------------- the commands
function parseRet(args) {
  if (!args.length) return [{ cmd: 'ret', tab: null, label: 'RET penceresini aç', note: 'RET faizleri' }];
  const tab = RET_TABS[fold(args.join(''))] || (args.length === 2 && fold(args[0]) === 'adil' ? 'fair' : null);
  if (!tab) return err('ret: "' + args.join(' ') + '" okunamadı', '"ret", "ret yayınla" ya da "ret elle" bekleniyor');
  return tab === 'fair'
    ? [{ cmd: 'ret', tab, label: 'RET penceresi · adil değer sekmesi', note: 'yayınlamak için "Kopyala ve yayınla" sizin' }]
    : [{ cmd: 'ret', tab, label: 'RET penceresi · elle giriş', note: 'RET faizlerini girin, kaydedin' }];
}

/** "işlem gir …": Günlük İşlemler's form - a bond (dibs / an ISIN / "mar28" first), an OIS (ois / fra / mpc first, or a
 *  rate's side, a FRA, a meeting, tenors with a "/" anywhere), else an FX forward (a pair first). */
function parseBlotter(args) {
  if (!args.length) return parseForward(args);
  const first = fold(args[0]);
  if (BOND_WORDS[first]) return parseBondTrade(args.slice(1));
  if (ISIN.test(args[0].toUpperCase()) || bondRef(args[0])) return parseBondTrade(args);
  if (OIS_WORDS[first] || args.some((t) => {
    const f = fold(t);
    return OIS_SIDE_WORDS[f] || f === 'mpc' || f === 'ppk' || fraMonths(f) || slashTenors(t);
  })) return parseOisTrade(args);
  return parseForward(args);
}

/** A bond as the desk names it - "mar28", "eyl29", "15.03.28", "15/3/2028" - (or null): the server finds its ISIN
 *  (blotter.bond_isin: the broker chat's reading). */
function bondRef(token) {
  const f = fold(token);
  const m = /^([a-z]{3,9})'?(\d{2})$/.exec(f);
  if (m && MONTHS[m[1]]) return token;
  return /^\d{1,2}[./]\d{1,2}[./](\d{2}|\d{4})$/.test(f) ? token : null;
}

/** A tenor as the OIS form lists it - "3a" 3M, "12m" 1Y, "2h" 2W, "on" ON - or null (a tenor the form does not list). */
export function oisTenor(token) {
  const s = fold(token).replace(/\s+/g, '');
  if (s === 'on' || s === 'o/n') return 'ON';
  let m = /^(\d{1,3})(h|w)$/.exec(s);
  if (m) return OIS_TENORS.includes(m[1] + 'W') ? m[1] + 'W' : null;
  m = /^(\d{1,3})(a|ay|m|y|yil)$/.exec(s);
  if (!m) return null;
  const months = Number(m[1]) * (m[2] === 'y' || m[2] === 'yil' ? 12 : 1);
  const t = months % 12 === 0 ? months / 12 + 'Y' : months + 'M';
  return OIS_TENORS.includes(t) ? t : null;
}

/** Two or three tenors written with "/" ("1y/2y", "2m/3m/6m": a spread, a fly) - not a date ("15/12/2026"). */
function slashTenors(token) {
  const parts = fold(token).split('/');
  return parts.length >= 2 && parts.length <= 3 && parts.every((x) => /^(\d{1,3}(a|ay|m|y|yil|h|w)|on)$/.test(x));
}

/** The months of a FRA's leg: "spot" 0, "9" / "9m" / "9a" 9, "1y" 12 (null otherwise). */
function legMonths(s) {
  if (s === 'spot' || s === '0') return 0;
  const m = /^(\d{1,3})(a|ay|m|y|yil)?$/.exec(s);
  return m ? Number(m[1]) * (m[2] === 'y' || m[2] === 'yil' ? 12 : 1) : null;
}

/** A FRA as the desk writes it: "9x12" (start × end), or a start and its length together as OIS · PPK's lists name it
 *  ("1y1y", "18m6m", "spot3m") - {months: [start, end], joined} or null.  ``joined``: two tenors written as one word, a
 *  spread with a spread's side ("1y2y steepener"). */
function fraMonths(f) {
  let m = /^(spot|\d{1,3}(?:a|ay|m|y|yil)?)x(\d{1,3}(?:a|ay|m|y|yil)?)$/.exec(f);
  if (m) {
    const a = legMonths(m[1]), b = legMonths(m[2]);
    return a !== null && b !== null ? { months: [a, b] } : null;
  }
  m = /^(spot|\d{1,3}(?:a|m|y))(\d{1,3}(?:a|m|y))$/.exec(f);
  if (!m) return null;
  const a = legMonths(m[1]), n = legMonths(m[2]);
  return a !== null && n !== null ? { months: [a, a + n], joined: [m[1], m[2]] } : null;
}

/** How an OIS size is said: a DV01 ($/bp) under a million, a nominal (TL) from it - "dv01" / "nom" / "tl" beside it say it. */
function sizeOf(text, mode) {
  const x = parseAmount(text);
  return { size: text, sizeMode: mode || (x !== null && x >= 1e6 ? 'nominal' : 'dv01') };
}

function parseOisTrade(args) {
  const spec = { kind: 'ois' };
  let product = null;
  let side = null;
  let body = false;
  let month = null;
  let fra = null;
  let tenors = [];
  let mode = null;
  const said = [];
  const want = ' bekleniyor - örn. işlem gir ois 2y rec 10k · 1y2y steepener · 9x12 pay · dec mpc pay · @35,50';
  for (let i = 0; i < args.length; i++) {
    const t = args[i];
    const f = fold(t);
    if (OIS_WORDS[f] && !product) { product = OIS_WORDS[f]; continue; }
    if (OIS_SIDE_WORDS[f] && !side) { side = OIS_SIDE_WORDS[f]; continue; }
    if (BODY_WORDS[f]) { body = true; continue; }
    if (f === 'spread' && product === 'mpc') { product = 'mpcspread'; continue; }
    if (MONTHS[f] && month === null) { month = MONTHS[f]; continue; }
    if (f === 'dv01') { mode = 'dv01'; continue; }
    if (f === 'nom' || f === 'nominal' || f === 'tl') { mode = 'nominal'; continue; }
    if (/^@/.test(t) || /%$/.test(t) || /^%/.test(t) || /bp$/.test(f)) {
      const level = t.replace(/^@/, '').replace(/bp$/i, '');
      if (parseAmount(level.replace(/%$/, '').replace(/^%/, '')) === null && !/^[+-−]?[\d.,]+%?$/.test(level)) {
        return err('işlem gir: "' + t + '" seviye değil', '"' + t + '" seviye olarak okunamadı: @35,50, 35,50% ya da -125bp' + want);
      }
      spec.level = level;
      continue;
    }
    const fm = fraMonths(f);
    if (fm && !fra && !tenors.length) { fra = fm; continue; }
    if (slashTenors(t) && !tenors.length && !fra) {
      const parts = t.split('/').map(oisTenor);
      if (parts.length < 2 || parts.length > 3 || parts.some((x) => !x)) {
        return err('işlem gir: "' + t + '" okunamadı', '"' + t + '": iki ya da üç OIS vadesi (1y/2y, 2m/3m/6m)' + want);
      }
      tenors = parts;
      continue;
    }
    const tenor = oisTenor(t);
    if (tenor && !fra && tenors.length < 3) { tenors.push(tenor); continue; }
    // a tenor the form does not list ("4m", "12y") is no size: a size is said with its unit (10k, 500m, 1b) or in full
    const tl = tenorOf(t);
    const tenorLike = !!tl && /^\d/.test(tl) && parseInt(tl, 10) * (/Y$/.test(tl) ? 12 : 1) <= 120;
    if (!spec.size && /\d/.test(t) && parseAmount(t) !== null && !tenorLike) { Object.assign(spec, sizeOf(t, mode)); continue; }
    return err('işlem gir: "' + t + '" okunamadı', '"' + t + '" okunamadı: ' + (tenorLike
      ? tl + ' OIS formunun vadelerinden değil (' + OIS_TENORS.join(', ') + ')' : 'vade, yön, tutar ya da seviye') + want);
  }
  if (spec.size && mode) spec.sizeMode = mode;
  // what was traded: a meeting period, a FRA, a spread or a fly by its tenors, an outright
  let st;
  if (product === 'mpc' || product === 'mpcspread' || (month !== null && !tenors.length && !fra)) {
    if (month === null) return err('işlem gir: hangi toplantı?', 'toplantının ayı bekleniyor (dec mpc, aralık mpc, mpc ocak)' + want);
    st = product === 'mpcspread' ? 'mpcspread' : 'mpc';
    spec.mpc_month = month;
    said.push((st === 'mpc' ? 'MPC ' : 'MPC spread ') + MONTH_TEXT[month - 1] + ' toplantısından');
  } else if (fra && fra.joined && (side === 'steep' || side === 'flat')) {
    st = 'spread';                                          // "1y2y steepener": two tenors written as one word
    tenors = fra.joined.map(oisTenor);
    if (tenors.some((x) => !x)) return err('işlem gir: vade okunamadı', '"' + fra.joined.join('') + '" iki OIS vadesi değil' + want);
    spec.tenors = tenors;
    said.push(tenors.join('/'));
  } else if (fra || product === 'fra') {
    if (!fra) return err('işlem gir: FRA bekleniyor', 'FRA bekleniyor: 9x12, 1y1y, 18m6m' + want);
    const [a, b] = fra.months;
    if (a % 3 || b % 3 || b <= a || b > 120) {
      return err('işlem gir: FRA ayları', 'FRA ayları 3\'ün katı olmalı (0 ≤ başlangıç < bitiş ≤ 120): ' + a + 'x' + b);
    }
    st = 'fra';
    spec.months = fra.months;
    said.push('FRA ' + (a ? a : 'Spot') + 'x' + b);
  } else if (tenors.length) {
    st = ['outright', 'spread', 'fly'][tenors.length - 1];
    spec.tenors = tenors;
    said.push(tenors.join('/'));
  } else {
    return err('işlem gir: OIS vadesi bekleniyor', 'OIS vadesi bekleniyor' + want);
  }
  spec.strategy = st;
  // the side in the strategy's words: a spread's needs steepener / flattener, a fly's rec / pay (the body), a meeting
  // spread's pay / rec (the later period)
  if (side) {
    const words = { outright: { rec: 'RECEIVE', pay: 'PAY' }, fra: { rec: 'RECEIVE', pay: 'PAY' }, mpc: { rec: 'RECEIVE', pay: 'PAY' },
      spread: { steep: 'STEEPENER', flat: 'FLATTENER' }, fly: { rec: 'REC GÖVDE', pay: 'PAY GÖVDE' },
      mpcspread: { pay: 'PAY K+1 / REC K', rec: 'REC K+1 / PAY K' } }[st];
    if (!words[side]) {
      return err('işlem gir: yön', (st === 'spread' ? 'spread\'in yönü steepener ya da flattener' : 'yön rec ya da pay') + ' bekleniyor');
    }
    spec.side = words[side];
  } else if (body) return err('işlem gir: yön', 'gövdenin yönü bekleniyor: rec gövde ya da pay gövde');
  const parts = ['TRY OIS'].concat(said, spec.side ? [OIS_SIDE_TEXT[spec.side] || spec.side] : ['yön yok'],
    spec.level ? ['@ ' + spec.level] : [], spec.size ? [(spec.sizeMode === 'nominal' ? 'nominal ' + spec.size + ' TL' : 'DV01 ' + spec.size + ' $/bp')] : []);
  return [{ cmd: 'blotter', spec, label: 'Günlük İşlemler: ' + parts.join(' · '),
    note: 'pozisyona girer · form dolar' + (spec.side ? '' : ', yönü seçin') + ', kaydetmek sizin' }];
}

function parseBondTrade(args) {
  const spec = { kind: 'bond' };
  for (const t of args) {
    const f = fold(t);
    if (SIDE_FX[f] && !spec.dir) { spec.dir = SIDE_FX[f]; continue; }
    if (!spec.instrument && (ISIN.test(t.toUpperCase()) || bondRef(t))) { spec.instrument = ISIN.test(t.toUpperCase()) ? t.toUpperCase() : t; continue; }
    if (/^@/.test(t) && !spec.price && parseAmount(t.slice(1)) !== null) { spec.price = t.slice(1); continue; }
    if (!spec.amount && amountOf(t)) { spec.amount = t; continue; }
    return err('işlem gir: "' + t + '" okunamadı', '"' + t + '" okunamadı: ' + (spec.instrument ? 'tutar (50m), al / sat ya da @fiyat'
      : 'kâğıt (ISIN, mar28 ya da 15.03.28)') + ' bekleniyor - örn. işlem gir dibs mar28 50m al');
  }
  if (!spec.instrument) return err('işlem gir: kâğıt bekleniyor', 'kâğıt bekleniyor: ISIN, mar28 ya da 15.03.28 - örn. işlem gir dibs mar28 50m al');
  const parts = ['DİBS ' + spec.instrument, spec.dir ? (spec.dir === 'B' ? 'alış' : 'satış') : 'yön yok', spec.amount ? spec.amount + ' nominal' : 'tutar yok']
    .concat(spec.price ? ['@ ' + spec.price] : []);
  return [{ cmd: 'blotter', spec, label: 'Günlük İşlemler: ' + parts.join(' · '),
    note: 'pozisyona girer · form dolar' + (ISIN.test(spec.instrument) ? '' : ' (ISIN\'i sunucu bulur)') + ', kaydetmek sizin' }];
}

/** "fiyatla …": Fiyatlama opened with the instrument filled - through its address (#/fiyatlama?asset=…: the page takes it,
 *  as the user would type it into its boxes; nothing kept until then).  The parameters are /api/pricing's fields: asset,
 *  pair, start, end, side, size_kind, size, price, price_kind. */
function parsePricing(args) {
  if (!args.length) return [{ cmd: 'page', id: 'fiyatlama', label: 'Fiyatlama\'yı aç', note: 'fiyatla <ois | fra | xccy | parite> … formu doldurur' }];
  const q = {};
  const dates = [];
  let mode = null;
  const want = ' bekleniyor - örn. fiyatla ois 2y3m rec 10k · fiyatla fra 12x15 · fiyatla usdtry 3m al 10m';
  for (const t of joinMonthEnd(args)) {
    const f = fold(t);
    if (PRICING_ASSETS[f] && !q.asset) { q.asset = PRICING_ASSETS[f]; continue; }
    if (!q.pair && /^[a-z/]+$/.test(f) && f.length <= 7 && pairOf(t) && (pairOf(t) === 'USDTRY' || pairOf(t) === 'EURTRY')) {
      q.pair = pairOf(t);
      q.asset = q.asset || 'fx';
      continue;
    }
    if (SIDE_RATE[f] && !q.side) { q.side = SIDE_RATE[f] === 'receive' ? 'RECEIVE' : 'PAY'; continue; }
    if (SIDE_FX[f] && !q.side) { q.side = SIDE_FX[f] === 'B' ? 'AL' : 'SAT'; continue; }
    if (f === 'dv01') { mode = 'dv01'; continue; }
    if (f === 'nom' || f === 'nominal' || f === 'tl') { mode = 'nominal'; continue; }
    if (/^@/.test(t) || /%$/.test(t)) { q.price = t.replace(/^@/, ''); continue; }
    const fm = fraMonths(f);
    if (fm && !fm.joined && !dates.length) { dates.push(String(fm.months[0]), String(fm.months[1])); q.asset = q.asset || 'fra'; continue; }
    // a maturity (a value date) - and before it a start: a swap's forward start, not an FX forward's; once there is a date, a
    // "10m" is the size
    const dateLike = /^(\d{1,3}[dwmyah])+$/.test(f) || /^(on|tn|sn|spot)$/.test(f) || /^\d{1,2}[./-]\d{1,2}([./-]\d{2,4})?$/.test(f)
      || f === 'ay sonu' || f === 'imm';
    const second = dates.length === 1 && q.asset !== 'fx' && !(parseAmount(t) !== null && /\d$|[mkb]$/.test(f) && !/[ywd]$/.test(f));
    if (dateLike && (!dates.length || second)) { dates.push(t.toUpperCase()); continue; }
    if (!q.size && /\d/.test(t) && parseAmount(t) !== null) { q.size = t; continue; }
    return err('fiyatla: "' + t + '" okunamadı', '"' + t + '" okunamadı: ürün, vade, yön, tutar ya da @fiyat' + want);
  }
  q.asset = q.asset || 'ois';
  if (dates.length === 1) q.end = dates[0];
  else if (dates.length === 2) Object.assign(q, { start: dates[0], end: dates[1] });
  // what the page kept from before must not stay under the new instrument: a swap without a start starts at spot, a price
  // is the one said or none (and read as a rate / an outright, whatever the box held before)
  if (dates.length === 1 && q.asset !== 'fx' && q.asset !== 'fra') q.start = '';
  if (q.price) q.price_kind = q.asset === 'fx' ? 'outright' : 'rate';
  else q.price = '';
  if (q.size) {
    const x = parseAmount(q.size);
    q.size_kind = mode || (q.asset === 'fx' ? 'amount' : (x !== null && x >= 1e6 ? 'nominal' : 'dv01'));
  }
  if (q.side && (q.asset === 'fx') !== (q.side === 'AL' || q.side === 'SAT')) {
    return err('fiyatla: yön', q.asset === 'fx' ? 'forward\'ın yönü al ya da sat' : 'yön rec ya da pay' + want);
  }
  const keys = ['asset', 'pair', 'start', 'end', 'side', 'size_kind', 'size', 'price', 'price_kind'];
  const query = keys.filter((k) => q[k] !== undefined).map((k) => k + '=' + encodeURIComponent(q[k])).join('&');
  const parts = [PRICING_TEXT[q.asset] + (q.pair && q.pair !== 'USDTRY' ? ' ' + q.pair : (q.asset === 'fx' ? ' USDTRY' : ''))]
    .concat(q.start ? [q.start + ' → ' + q.end] : (q.end ? [q.end] : []), q.side ? [q.side] : [],
      q.size ? [(q.size_kind === 'dv01' ? 'DV01 ' : '') + q.size + (q.size_kind === 'nominal' ? ' TL' : '')] : [], q.price ? ['@ ' + q.price] : []);
  return [{ cmd: 'page', id: 'fiyatlama?' + query, label: 'Fiyatlama: ' + parts.join(' · '), note: 'Fiyatlama dolu açılır · hiçbir şey kaydedilmez' }];
}

function parseForward(args) {
  let pair = null;
  let date = null;
  let amount = null;
  let dir = null;
  for (const t of joinMonthEnd(args)) {
    const f = fold(t);
    if (SIDE_FX[f] && !dir) { dir = SIDE_FX[f]; continue; }
    if (!pair) {
      const p = /^[a-z/]+$/.test(f) ? pairOf(t) : null;
      if (!p) return err('işlem gir: parite bekleniyor', '"' + t + '" parite değil: işlem gir <parite> <vade> <tutar> (örn. işlem gir usdtry 1m 10mn)');
      pair = p;
      continue;
    }
    if (!date && tenorOf(t)) { date = tenorOf(t); continue; }
    if (!amount && amountOf(t)) { amount = amountOf(t); continue; }
    return err('işlem gir: "' + t + '" okunamadı', '"' + t + '" ' + (!date ? 'vade olarak okunamadı: 1m, 3a, 1y, 2h, on, tn, ay sonu, imm, +5 ya da tarih'
      : (!amount ? 'tutar olarak okunamadı: 10mn, 5m, 500k' : 'fazla')) + ' bekleniyor - işlem gir <parite> <vade> <tutar>');
  }
  if (!pair) return [{ cmd: 'page', id: 'blotter', label: 'Günlük İşlemler\'i aç', note: 'işlem gir <parite> <vade> <tutar> formu doldurur' }];
  const spec = { kind: 'fwd', pair, basis: 'RET_MID' };
  if (date) spec.date = date;
  if (amount) spec.amount = amount;
  if (dir) spec.dir = dir;
  const parts = [pair, dir ? (dir === 'B' ? 'alış' : 'satış') : null, date ? 'valör ' + date : 'vade yok', amount ? amount + ' ' + pair.slice(0, 3) : 'tutar yok'];
  return [{ cmd: 'blotter', spec, label: 'Günlük İşlemler: ' + parts.filter(Boolean).join(' · '),
    note: (date ? 'valör ' + pair + ' spot\'undan · ' : '') + 'form dolar, kaydetmek sizin' }];
}

function parseTrade(args) {
  if (!args.length) return [{ cmd: 'trades', spec: {}, label: 'Trades: yeni işlem formu', note: 'trade <ürün> … ile doldurulur' }];
  const product = PRODUCTS[fold(args[0])];
  if (!product) return err('trade: ürün bekleniyor', '"' + args[0] + '" ürün değil: ois, sofr, dibs, spot ya da opsiyon bekleniyor (örn. trade ois 1y 5mn)');
  const spec = { product };
  const said = [PRODUCT_TEXT[product]];
  const rest = joinMonthEnd(args.slice(1));
  for (let i = 0; i < rest.length; i++) {
    const t = rest[i];
    const f = fold(t);
    const rate = product === 'ois' || product === 'sofr';
    if (rate && SIDE_RATE[f] && !spec.side) { spec.side = SIDE_RATE[f]; said.push(spec.side.toUpperCase()); continue; }
    if (!rate && SIDE_FX[f] && !spec.side) { spec.side = SIDE_FX[f]; said.push(spec.side === 'B' ? 'alış' : 'satış'); continue; }
    if (product === 'fxopt' && CALL_PUT[f] && !spec.call_put) { spec.call_put = CALL_PUT[f]; said.push(f.toUpperCase()); continue; }
    if (rate && f === 'dv01' && i + 1 < rest.length && amountOf(rest[i + 1]) && !spec.dv01) {
      spec.dv01 = rest[i + 1]; said.push('DV01 ' + rest[i + 1]); i += 1; continue;
    }
    if (product === 'dibs' && !spec.isin && ISIN.test(t.toUpperCase())) { spec.isin = t.toUpperCase(); said.push(spec.isin); continue; }
    if ((product === 'fxspot' || product === 'fxopt') && !spec.pair && /^[a-z/]+$/.test(f) && pairOf(t)) { spec.pair = pairOf(t); said.push(spec.pair); continue; }
    if ((rate || product === 'fxopt') && !spec.tenor && tenorOf(t)) { spec.tenor = tenorOf(t); said.push((rate ? '' : 'vade ') + spec.tenor); continue; }
    if (!spec.notional && amountOf(t)) { spec.notional = amountOf(t); said.push(t); continue; }
    const want = { ois: 'vade (1y), tutar (5mn), rec / pay', sofr: 'vade (1y), tutar (5mn), rec / pay', dibs: 'ISIN, tutar (10m), al / sat',
      fxspot: 'parite (usdtry), tutar (5m), al / sat', fxopt: 'parite, vade (1a), tutar, call / put, al / sat' }[product];
    return err('trade: "' + t + '" okunamadı', '"' + t + '" okunamadı: trade ' + fold(args[0]) + ' için ' + want + ' bekleniyor');
  }
  return [{ cmd: 'trades', spec, label: 'Trades formu: ' + said.join(' · '), note: 'izleme, pozisyona girmez · form dolar, kaydetmek sizin' }];
}

function parseIsins(args) {
  const codes = args.join(' ').split(/[\s,;]+/).filter(Boolean).map((x) => x.toUpperCase());
  if (!codes.length) return [{ cmd: 'isin', isins: [], label: 'Trading listesine kâğıt ekle', note: '"+ ISIN ekle" penceresi' }];
  const bad = codes.find((x) => !ISIN.test(x));
  if (bad) return err('kâğıt ekle: "' + bad + '" ISIN değil', '"' + bad + '" ISIN değil: 12 karakter bekleniyor (örn. TRT150328T24)');
  const isins = [...new Set(codes)];
  return [{ cmd: 'isin', isins, label: 'Trading listesine ekle: ' + isins.join(', '), note: '"+ ISIN ekle" dolar, "Ekle" sizin' }];
}

function parseScenario(args, env) {
  const name = args.join(' ').trim();
  const f = fold(name);
  const saved = env.scenarios || [];
  const out = [];
  const ppk = PPK.find((c) => fold(c) === f) || (f === 'piyasa' ? 'piyasa' : null);
  if (ppk) {
    out.push({ cmd: 'retview', code: ppk, label: ppk === 'piyasa' ? 'RET adil değer: piyasa görünümü' : 'RET adil değer: PPK senaryosu ' + ppk,
      note: 'sizin görünümünüz (masanınkini değiştirmez)' });
  }
  const exact = saved.filter((s) => fold(s) === f);
  const near = f ? saved.filter((s) => fold(s) !== f && fold(s).includes(f)) : saved;
  for (const s of exact.concat(near).slice(0, 6)) {
    out.push({ cmd: 'scenario', name: s, label: 'Senaryoyu yükle: ' + s, note: 'sorulur; kişisel girdileriniz onunkilerle değişir' });
  }
  if (!f) {
    for (const c of PPK) out.push({ cmd: 'retview', code: c, label: 'RET adil değer: PPK senaryosu ' + c, note: 'sizin görünümünüz' });
    // (said after what can be done: Enter runs the first)
    if (!saved.length && env.scenarios) out.push({ error: 'Kayıtlı senaryonuz yok: Senaryolar\'dan kaydedin', label: 'Kayıtlı senaryonuz yok: Senaryolar\'dan kaydedin' });
    return out;
  }
  if (!out.length) {
    if (env.scenarios === null || env.scenarios === undefined) return err('senaryolarınız okunuyor…', 'senaryolarınız okunuyor, bir an sonra tekrar deneyin');
    return err('böyle bir senaryonuz yok: "' + name + '"', '"' + name + '" adlı senaryonuz yok' + (saved.length ? ' (senaryolarınız: '
      + saved.slice(0, 6).join(', ') + (saved.length > 6 ? ' …' : '') + ')' : '') + ' · S1 / S2 / S3: RET adil değer görünümü');
  }
  return out;
}

function parsePage(args, env) {
  const words = fold(args.join(' ')).split(/\s+/).filter(Boolean);
  if (!words.length) return [{ complete: 'sayfa ', label: 'sayfa <ad>', note: 'bir sayfayı aç, örn. sayfa ois' }];
  const pages = (env.pages || []).map((p) => ({ p, t: fold(p.title) + ' ' + fold(p.id) }));
  const hits = pages.filter((x) => words.every((w) => x.t.includes(w)));
  hits.sort((a, b) => (b.t.startsWith(words[0]) ? 1 : 0) - (a.t.startsWith(words[0]) ? 1 : 0));
  if (!hits.length) return err('böyle bir sayfa yok: "' + args.join(' ') + '"', '"' + args.join(' ') + '" adlı bir sayfa yok');
  return hits.slice(0, 4).map((x) => ({ cmd: 'page', id: x.p.id, label: 'Sayfayı aç: ' + x.p.title, note: x.p.group || 'sayfa' }));
}

function parseLaunchpad(args, env) {
  const name = args.join(' ').trim();
  const f = fold(name);
  const all = env.launchpads || [];
  if (!f) {
    return [{ cmd: 'page', id: 'launchpad', label: 'Launchpad\'lerim', note: 'launchpad sayfası' }]
      .concat(all.slice(0, 6).map((n) => ({ cmd: 'launchpad', name: n, label: 'Launchpad: ' + n, note: 'launchpad\'iniz' })));
  }
  const exact = all.filter((n) => fold(n) === f);
  const near = all.filter((n) => fold(n) !== f && fold(n).includes(f));
  const hits = exact.concat(near);
  if (!hits.length) return err('böyle bir launchpad yok: "' + name + '"', '"' + name + '" adlı launchpad\'iniz yok' + (all.length ? ' (launchpad\'leriniz: ' + all.slice(0, 6).join(', ') + ')' : ''));
  return hits.slice(0, 4).map((n) => ({ cmd: 'launchpad', name: n, label: 'Launchpad: ' + n, note: 'launchpad\'iniz' }));
}

/**
 * The text of the box read as a command: null when it is none (the box finds tables then), else the suggestions to show
 * first.  ``env``: {pages: [{id, title, group}], launchpads: [name], scenarios: [name] | null (not read yet)}.
 */
export function parseCommand(text, env = {}) {
  const raw = tokens(text);
  if (!raw.length) return null;
  const first = fold(raw[0]);
  const second = raw.length > 1 ? fold(raw[1]) : '';
  const args = raw.slice(1);
  if (first === 'ret') return parseRet(args);
  if (first === 'islem') return parseBlotter(second === 'gir' ? raw.slice(2) : args);
  if (first === 'fiyatla') return parsePricing(args);
  if (first === 'trade') return parseTrade(args);
  if (first === 'kagit' && second === 'ekle') return parseIsins(raw.slice(2));
  if (first === 'senaryo') return parseScenario(args, env);
  if (first === 'sayfa') return parsePage(args, env);
  if (first === 'launchpad') return parseLaunchpad(args, env);
  // a command's first word being typed: its template (Enter writes it into the box) - "kâğıt" too, before its "ekle"
  if (raw.length === 1 && !/\s$/.test(String(text)) && first.length >= 2) {
    const tpl = COMMANDS.filter((c) => c.word.startsWith(first) && (c.word !== first || c.word === 'kagit'));
    if (tpl.length) return tpl.map((c) => ({ complete: c.full, label: c.text, note: c.note }));
  }
  return null;
}
