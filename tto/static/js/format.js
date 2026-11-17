// Locale-aware number / date formatting used by the client-rendered parts (blotter, charts, clipboard).

export const settings = { lang: 'tr' };

export function setLang(lang) {
  settings.lang = lang === 'en' ? 'en' : 'tr';
}

function seps() {
  return settings.lang === 'en' ? { dec: '.', grp: ',' } : { dec: ',', grp: '.' };
}

/** Fixed-decimal number with thousands separators; null / NaN -> ''. */
export function num(v, digits = 2, group = true) {
  if (v === null || v === undefined || typeof v !== 'number' || !isFinite(v)) return '';
  const { dec, grp } = seps();
  const neg = v < 0 || (Object.is(v, -0) && false);
  let s = Math.abs(v).toFixed(digits);
  let [ip, fp] = s.split('.');
  if (group) ip = ip.replace(/\B(?=(\d{3})+(?!\d))/g, grp);
  s = fp ? ip + dec + fp : ip;
  if (neg && /[1-9]/.test(s)) s = '-' + s;
  return s;
}

export function pct(v, digits = 2) {
  if (v === null || v === undefined || typeof v !== 'number' || !isFinite(v)) return '';
  return num(v * 100, digits, false) + '%';
}

/** Full precision (15 significant digits), no grouping - what Excel takes back without loss. */
export function raw(v) {
  if (typeof v !== 'number' || !isFinite(v)) return '';
  let s = Number(v.toPrecision(15)).toString();
  if (s.includes('e')) s = Number(v.toPrecision(15)).toFixed(12).replace(/0+$/, '').replace(/\.$/, '');
  return settings.lang === 'en' ? s : s.replace('.', ',');
}

/** Excel serial date -> dd.mm.yyyy */
export function serialDate(serial) {
  if (typeof serial !== 'number' || !isFinite(serial)) return '';
  const ms = Math.round((serial - 25569) * 86400000);
  const d = new Date(ms);
  const dd = String(d.getUTCDate()).padStart(2, '0');
  const mm = String(d.getUTCMonth() + 1).padStart(2, '0');
  return dd + '.' + mm + '.' + d.getUTCFullYear();
}

export function isoToTr(iso) {
  if (!iso) return '';
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso);
  return m ? m[3] + '.' + m[2] + '.' + m[1] : iso;
}

export function timeOf(stamp) {
  if (!stamp) return '';
  const m = /(\d{2}:\d{2})(:\d{2})?$/.exec(stamp);
  return m ? m[1] : stamp;
}

/**
 * Parse what a person typed ("35,55", "1.234,56", "1,234.56", "35%") -> number or null.
 * Follows the chosen number format like the server does: with Turkish format a lone "12.345" is twelve
 * thousand ... (as Turkish Excel reads it); `preferDecimal` (rates, prices) turns that reading off.
 */
export function parseNumber(text, preferDecimal = false) {
  if (typeof text !== 'string') return null;
  let s = text.trim().replace(/[\s\u00a0\u202f]/g, '');
  if (!s) return null;
  let pctFlag = false;
  if (s.endsWith('%')) { pctFlag = true; s = s.slice(0, -1); } else if (s.startsWith('%')) { pctFlag = true; s = s.slice(1); }
  if (s.startsWith('\u2212') || s.startsWith('\u2013')) s = '-' + s.slice(1);
  const dot = s.includes('.'), comma = s.includes(',');
  const en = settings.lang === 'en';
  if (dot && comma) {
    if (s.lastIndexOf(',') > s.lastIndexOf('.')) s = s.replace(/\./g, '').replace(',', '.');
    else s = s.replace(/,/g, '');
  } else if (comma) {
    if ((s.match(/,/g) || []).length > 1) {
      if (!/^[+-]?\d{1,3}(,\d{3})+$/.test(s)) return null;
      s = s.replace(/,/g, '');
    } else if (en && !preferDecimal && /^[+-]?[1-9]\d{0,2},\d{3}$/.test(s)) {
      s = s.replace(',', '');
    } else {
      s = s.replace(',', '.');
    }
  } else if (dot) {
    if ((s.match(/\./g) || []).length > 1) {
      if (!/^[+-]?\d{1,3}(\.\d{3})+$/.test(s)) return null;
      s = s.replace(/\./g, '');
    } else if (!en && !preferDecimal && /^[+-]?[1-9]\d{0,2}\.\d{3}$/.test(s)) {
      s = s.replace('.', '');
    }
  }
  if (!/^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/.test(s)) return null;
  const x = parseFloat(s);
  if (!isFinite(x)) return null;
  return pctFlag ? x / 100 : x;
}

/** Compact axis label for a chart value. */
export function axisNum(v, span) {
  const a = Math.abs(span);
  let digits = 0;
  if (a < 0.05) digits = 4; else if (a < 0.5) digits = 3; else if (a < 5) digits = 2; else if (a < 50) digits = 1;
  return num(v, digits, Math.abs(v) >= 10000);
}

/** "gbp" / "GBPTRY" / "gbp/try" -> "GBPTRY" (a currency alone is against TRY); null when it is not a pair. */
export function pairOf(text) {
  const s = String(text || '').replace(/[^A-Za-z]/g, '').toUpperCase();
  if (s.length === 3 && s !== 'TRY') return s + 'TRY';
  if (s.length === 6 && s.slice(0, 3) !== s.slice(3)) return s;
  return null;
}

/** "10m", "2,5 mio", "500k", "2mr", "1.000.000" -> number (null when not understood) - as the server reads it
 *  (tto/inputs.py parse_amount). */
export function parseAmount(text) {
  const m = /^\s*([+-]?[\d.,\s]+?)\s*(k|bin|m|mn|mln|mio|milyon|b|bn|mr|mlr|milyar)?\s*$/i.exec(text || '');
  if (!m) return null;
  const x = parseNumber(m[1]);
  if (x === null) return null;
  const u = (m[2] || '').toLowerCase();
  const mult = !u ? 1 : (u === 'k' || u === 'bin') ? 1e3 : (['b', 'bn', 'mr', 'mlr', 'milyar'].includes(u)) ? 1e9 : 1e6;
  return x * mult;
}
