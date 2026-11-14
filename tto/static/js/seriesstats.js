// Where a value stands in its own past, the way the tables next to a drawn series work it out (serieschart.js draws
// it; nothing here touches the page, so the tests run it as it is):
//   rule 'macro' - the workbook's macro block (FX Vol İzleme, Gün Sonu Matrisi; tto.fx.stats): the closes laid on the
//                  week days up to yesterday, a missing day taking the previous close for at most five days; the value
//                  now against the last ``window`` of them; percentile = the share at or below it; z wants two closes.
//   rule 'raw'   - İzleme · Alarmlar (tto.watch.Watch.zinfo): the closes as they are, the last ``window`` before
//                  today; percentile = the share strictly below; z wants 15 closes over a month, 20 over anything longer.

export const MAX_STALE = 5;                // week days a close is carried forward (tto.history.MAX_STALE)
export const CHART_MIN = 20;               // closes a day's z needs before the z chart shows it
const DAY = 86400000;
const isNum = (v) => typeof v === 'number' && isFinite(v);
const toMs = (iso) => Date.UTC(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10));
const toIso = (ms) => new Date(ms).toISOString().slice(0, 10);

function meanSd(xs) {
  const n = xs.length;
  if (n < 2) return null;
  const m = xs.reduce((a, b) => a + b, 0) / n;
  const v = xs.reduce((a, b) => a + (b - m) * (b - m), 0) / (n - 1);
  return v > 0 ? [m, Math.sqrt(v)] : null;
}

/** The closes the statistics run on, ``[[iso, value], ...]`` before ``today``: as they are (rule 'raw'), or along the
 * week days from ``from`` (or the first close) to the day before today, gaps of up to five days carried (rule 'macro'). */
export function basis(points, rule, today, from) {
  const pts = (points || []).filter((p) => p && isNum(p[1]) && (!today || p[0] < today)).sort((a, b) => (a[0] < b[0] ? -1 : 1));
  if (rule !== 'macro' || !pts.length) return pts;
  const by = new Map(pts.map((p) => [p[0], p[1]]));
  const start = from && from > pts[0][0] ? from : pts[0][0];
  const end = today ? toMs(today) - DAY : toMs(pts[pts.length - 1][0]);
  const out = [];
  let last = null, age = 0;
  for (let t = toMs(start); t <= end; t += DAY) {
    const wd = new Date(t).getUTCDay();
    if (wd === 0 || wd === 6) continue;
    const iso = toIso(t);
    const v = by.get(iso);
    if (v !== undefined) { last = v; age = 0; } else if (last !== null && ++age > MAX_STALE) last = null;
    if (last !== null) out.push([iso, last]);
  }
  return out;
}

/** Closes a z-score needs at least (rule 'raw': tto.watch.min_closes). */
export function need(rule, w) {
  return rule === 'raw' ? (w <= 20 ? 15 : 20) : 2;
}

/** Where ``value`` stands among the last ``w`` of ``closes`` (values): mean, std, z, percentile, range - or null. */
export function standing(closes, value, w, rule = 'macro') {
  const win = w && w < closes.length ? closes.slice(-w) : closes.slice();
  if (!isNum(value) || win.length < need(rule, w)) return null;
  const ms = meanSd(win);
  if (!ms) return null;
  const [mean, sd] = ms;
  const below = win.filter((x) => (rule === 'raw' ? x < value : x <= value)).length;
  return { mean, sd, z: (value - mean) / sd, pct: below / win.length, min: Math.min(...win), max: Math.max(...win), n: win.length };
}

/** z of every close against the ``w`` closes before it (null while there are fewer than ``least``). */
export function rollingZ(values, w, least = CHART_MIN) {
  const out = [];
  for (let i = 0; i < values.length; i++) {
    const win = values.slice(Math.max(0, i - w), i);
    const ms = win.length >= Math.min(least, w) ? meanSd(win) : null;
    out.push(ms ? (values[i] - ms[0]) / ms[1] : null);
  }
  return out;
}
