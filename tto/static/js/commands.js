// Ctrl+K commands: beside finding tables (find.js), the box understands a few commands - shown first as one types, Enter
// runs them, Esc leaves.  A command never saves anything by itself: it opens a dialog (RET - "ret yayınla" on the fair
// value tab: publishing is the user's "Kopyala ve yayınla"), fills a form for the user to save (Günlük İşlemler, Trades,
// the trading list's "+ ISIN ekle"), loads a saved scenario after a confirmation naming it, or opens a page / launchpad.
// Turkish and ASCII spellings alike (ı/i, ş/s, ğ/g …), any case:
//
//   ret · ret yayınla · ret elle          the RET dialog (yayınla / adil: the fair value tab; elle / gir: the manual one)
//   işlem gir <parite> <vade> <tutar>     Günlük İşlemler's forward form: "işlem gir usdtry 1m 10mn", "işlem gir eurtry 3a 5m"
//                                         (the value date: the tenor from the pair's own spot, as the form reads a shortcut)
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
  { word: 'islem', full: 'işlem gir ', text: 'işlem gir <parite> <vade> <tutar>', note: 'Günlük İşlemler formu, örn. işlem gir usdtry 1m 10mn' },
  { word: 'trade', full: 'trade ', text: 'trade <ürün> <vade | ISIN | parite> <tutar>', note: 'Trades formu, örn. trade ois 1y 5mn' },
  { word: 'kagit', full: 'kâğıt ekle ', text: 'kâğıt ekle <ISIN …>', note: 'trading listesine "+ ISIN ekle", örn. kâğıt ekle TRT150328T24' },
  { word: 'senaryo', full: 'senaryo ', text: 'senaryo <ad>', note: 'kayıtlı senaryoyu yükle · S1 / S2 / S3: RET adil değer görünümü' },
  { word: 'sayfa', full: 'sayfa ', text: 'sayfa <ad>', note: 'bir sayfayı aç, örn. sayfa ois' },
  { word: 'launchpad', full: 'launchpad ', text: 'launchpad <ad>', note: 'launchpad\'lerinizden birini aç' },
];

const SIDE_FX = { al: 'B', alis: 'B', alim: 'B', buy: 'B', long: 'B', sat: 'S', satis: 'S', satim: 'S', sell: 'S', short: 'S' };
const SIDE_RATE = { rec: 'receive', receive: 'receive', receiver: 'receive', pay: 'pay', payer: 'pay' };
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

function parseBlotter(args) {
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
  return [{ cmd: 'trades', spec, label: 'Trades formu: ' + said.join(' · '), note: 'form dolar, kaydetmek sizin' }];
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
