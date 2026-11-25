// The number of decimals each user sees in the tables of the workbook pages (the desk, 25.11.2026: "İstediğim şeyleri
// seçip sağ tıklayıp decimal formatını yapabilmeliyim"): a right click on a selection holding numbers - "Ondalık: 0 1 2
// …", "Ondalık artır" / "Ondalık azalt" (Excel's buttons), "Ondalığı varsayılana döndür".  Only the decimals change (a
// percent stays a percent, the thousands separators, a negative's look, a suffix); dates, times and text are left alone.
// Kept with the account on the server (tto/decimals.py), which puts it on the cells it sends this user (``dp``: the
// decimals set; ``dpc``: in a temporary copy, set in the copy itself): a reload, another computer shows the same, nobody
// else's view changes.  A display setting: the values, what is typed, "Tam hassasiyetle kopyala" are as they were;
// "Kopyala" copies what is shown.  A cell keeps its setting where it is when the rows of a list move.
import { api } from './api.js';
import { settings } from './format.js';
import { toast } from './ui.js';

export const MAX_DECIMALS = 10;                    // (tto/xl/numfmt.py MAX_DECIMALS)
const CHOICES = [0, 1, 2, 3, 4, 5, 6];

let changed = () => {};

/** ``fn()`` after this user's decimals changed: what is on screen is asked for again (main.js: the refresh). */
export function onDecimalsChanged(fn) {
  changed = fn;
}

/** How many decimals a number's text shows - its digits after the decimal separator of the number format in use
 *  ("35,550%" 3, "1.234" 0 in Turkish, "6,27M" 2); null when it shows no digit (an accounting zero's "-"). */
export function shownDecimals(text, lang = settings.lang) {
  const m = (lang === 'en' ? /\d[\d,]*(?:\.(\d*))?/ : /\d[\d.]*(?:,(\d*))?/).exec(String(text || ''));
  if (!m) return null;
  return m[1] ? m[1].length : 0;
}

/**
 * The cells of a selection a number of decimals is for: [{ref, cell, n}] (``n``: the decimals it shows now, null: none) -
 * its numbers, and the formula or input cells that show no value yet (empty, an error: a number may come there); never a
 * date, a time or a text, nor a column the user hid, nor a column the dashboard adds to a table (no cell of a sheet).
 */
function targets(grid, s) {
  const out = [];
  for (let i = s.top; i <= s.bottom; i++) {
    for (let j = s.left; j <= s.right; j++) {
      if (grid.colHidden(j)) continue;
      const c = grid.cell(i, j);
      const ref = c && !c.sk ? grid.ref(i, j) : null;
      if (!ref) continue;
      if (c.k === 'n') out.push({ ref, cell: c, n: shownDecimals(c.t) });
      else if (c.dp !== undefined || ((c.k === '' || c.k === 'e') && (c.fx || c.i))) out.push({ ref, cell: c, n: null });
    }
  }
  return out;
}

const pairs = (list, fn) => {
  const o = {};
  for (const t of list) o[t.ref] = fn(t);
  return o;
};

async function send(grid, body, said) {
  try {
    const res = await api.post('/api/decimals', Object.assign({ book: grid.book, copy: grid.opts.copy || null }, body));
    toast(said(res) + (res.skipped ? ' · ' + res.skipped + ' tarih / metin hücresi atlandı' : '') + ' · yalnız sizin görünümünüz',
      'ok', 3000);
    changed();
  } catch (err) {
    toast(err.message || String(err), 'err', 6000);
  }
}

/** What a right click on a selection (``s``) of a table of a workbook page offers: [] when it holds no number. */
export function decimalItems(grid, s) {
  const all = targets(grid, s);
  if (!all.some((t) => t.cell.k === 'n' || t.cell.dp !== undefined)) return [];
  const copy = grid.opts.copy || null;
  const shown = all.filter((t) => t.n !== null);
  const same = shown.length && shown.every((t) => t.n === shown[0].n) ? shown[0].n : null;
  // (in a copy: what was set in the copy itself - the table's own setting is the table's)
  const mine = all.filter((t) => t.cell.dp !== undefined && (!copy || t.cell.dpc));
  const step = (by) => {
    const moved = shown.filter((t) => t.n + by >= 0 && t.n + by <= MAX_DECIMALS);
    send(grid, { set: pairs(moved, (t) => t.n + by) },
      () => moved.length + ' hücrenin ondalığı ' + (by > 0 ? 'artırıldı' : 'azaltıldı'));
  };
  return [
    { sep: true },
    { label: 'Ondalık', id: 'menu-decimals', title: 'Seçili sayıların ondalık basamak sayısı – yalnız sizin görünümünüz; '
      + 'değerler, hesaplar ve "Tam hassasiyetle kopyala" değişmez',
    choices: CHOICES.map((n) => ({ label: String(n), value: n, on: n === same, title: n + ' ondalık',
      action: () => send(grid, { set: pairs(all, () => n) }, (res) => res.set + ' hücre: ' + n + ' ondalık') })) },
    { label: 'Ondalık artır', disabled: !shown.some((t) => t.n < MAX_DECIMALS), action: () => step(1) },
    { label: 'Ondalık azalt', disabled: !shown.some((t) => t.n > 0), action: () => step(-1) },
    mine.length ? { label: copy ? 'Ondalığı tablonunkine döndür' : 'Ondalığı varsayılana döndür',
      action: () => send(grid, { reset: mine.map((t) => t.ref) },
        (res) => res.reset + (copy ? ' hücre tablodaki ondalığına döndü' : ' hücre varsayılan ondalığına döndü')) } : null,
  ];
}

/** A cell's tooltip line for the decimals this user set ('' for none). */
export function decimalsTip(cell) {
  if (cell.dp === undefined || cell.k !== 'n') return '';
  return 'Ondalık: ' + cell.dp + (cell.dpc ? ' (bu kopyada)' : '') + ' – sizin görünümünüz';
}
