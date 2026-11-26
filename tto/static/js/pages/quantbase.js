// What the quant pages share (quant.js: Sinyaller; quantviews.js: the analysis pages): cell helpers, a table in a panel
// whose rows can be picked, the chart of one signal (its series with ±z bands and entry / target / stop) and the page
// frame - load, a refresh when the server's result moved, the status and data-coverage tables.
import { api } from '../api.js';
import { h, clear, errorToast, toast } from '../ui.js';
import { Grid, plainData, copyGrid } from '../grid.js';
import { toolsOf } from '../columns.js';
import { Chart } from '../chart.js';
import { num, isoToTr } from '../format.js';
import { readLine, isInfo } from './quantread.js';
import { bookLine } from './trades.js';

export const BLUE = '4F81BD', GREY = '7F7F7F', PURPLE = '8064A2', GREEN = '9BBB59', RED = 'C0504D', ORANGE = 'F79646';
export const isNum = (v) => typeof v === 'number' && isFinite(v);
export const sgn = (v, d = 2) => (isNum(v) ? (v > 0 ? '+' : '') + num(v, d, false) : '');
export const fmt = (v, d = 2) => (isNum(v) ? num(v, d, false) : '');
export const pct = (v, d = 0) => (isNum(v) ? num(v * 100, d, false) + '%' : '');
const serialOf = (iso) => Math.round(Date.UTC(+iso.slice(0, 4), +iso.slice(5, 7) - 1, +iso.slice(8, 10)) / 86400000) + 25569;

export const REGIME = { MR: 'Ortalamaya dönüş', Trend: 'Trend', 'Nötr': 'Nötr' };

/** What a signal a gate holds is called: it stays in the lists, after the confident ones, never logged nor alerted. */
export const LOW = 'düşük güven';

/** A signal's place in the Sinyaller list (tto/quantuniv.py): its group, TRY OIS's end ("≤ 2Y" / "uzun") and the tag
 * of an Offshore line ("offshore limiti"). */
export function groupText(s) {
  return [s.group || '', s.tier || '', s.tag || ''].filter(Boolean).join(' · ');
}

/** Money as the desk says it (the server's sentences say it the same way): "+525 bin TRY", "4,2 bin USD", "-1.800 bin
 * TL" - thousands, 10 mn and over in mn. */
export function money(v, ccy, sign = true) {
  if (!isNum(v)) return '';
  const a = Math.abs(v);
  const t = a >= 1e7 ? num(a / 1e6, 1) + ' mn' : (a >= 1e3 ? num(a / 1e3, a < 1e4 ? 1 : 0) + ' bin' : num(a, 0));
  const s = /[1-9]/.test(t) ? (v > 0 && sign ? '+' : (v < 0 ? '-' : '')) : '';
  return s + t + (ccy ? ' ' + ccy : '');
}

/** A rate in % - a traded level, a leg's rate, a family's own level in % - has three decimals, so that the move between
 * two of them reads as the bp gap beside them does (the desk, 25.11.2026: "3 decimal"; tto/quantfam.py RATE_DIGITS). */
export const RATE_DIGITS = 3;

/** A level as the desk writes it: a rate "%38,500" (RATE_DIGITS, whatever ``digits`` says), a spread "+3,0 bp", anything
 * else with its unit. */
export function levelText(v, unit, digits = 2) {
  if (!isNum(v)) return '—';
  if (unit === '%') return '%' + num(v, RATE_DIGITS);
  if (unit === 'bp') return sgn(v, 1) + ' bp';
  return fmt(v, digits) + (unit ? ' ' + unit : '');
}

/** A level's quote on the desk's own sheet, beside it - when the signal carries one (``info.sheet``: a fly of the
 * universe, the OIS sheet's 2·body − wings, tto/quantuniv.py): " (OIS sayfasında -25,0)". */
export function sheetText(s, v) {
  const sh = (s && s.info && s.info.sheet) || null;
  if (!sh || !isNum(v) || !isNum(sh.factor)) return '';
  return ' (' + (sh.where || 'OIS sayfasında') + ' ' + sgn(v * sh.factor, 1) + ')';
}

// ------------------------------------------------------------------------------------------------ a model's level, traded
// A line whose level is the model's own - a gap to the PPK path, a residual of a fit, a premium over realized vol - says
// entry / target / stop in the traded instrument's own level (``s.quote``, tto/quantfam.py inst_quote: the FRA's rate …),
// the model's gap beside each (the desk, 24.11.2026: "6x9 net bir seviye değil mi, bps olarak yazdıklarını anlayamadım").
const GAP_UNIT = { vol: 'vol puanı' };

/** The instrument's level as the desk writes it: a rate "%38,720", a vol "14,20 vol", a price "42,8150". */
export function quoteText(q, v) {
  return levelText(v, q.unit, isNum(q.digits) ? q.digits : 2);
}

/** The model's gap beside it: "+6,9 bp patikanın üstünde", "-2,00 vol puanı gerçekleşen vol'ün altında", "0,0 bp: patikada". */
export function gapText(q, v) {
  const g = (q && q.gap) || {};
  if (!isNum(v)) return '—';
  const d = isNum(g.digits) ? g.digits : 1;
  const unit = GAP_UNIT[g.unit] || g.unit || '';
  if (Number(v.toFixed(d)) === 0) return (num(0, d, false) + ' ' + unit + ': ' + (g.at || '')).replace('  ', ' ');
  return (sgn(v, d) + ' ' + unit + ' ' + (g.of || '') + ' ' + (v > 0 ? 'üstünde' : 'altında')).replace('  ', ' ');
}

/** The gap at entry, target and stop in one: "patika farkı +6,9 / +0,1 / +7,9 bp". */
export function gapsText(q) {
  const g = (q && q.gap) || {};
  const d = isNum(g.digits) ? g.digits : 1;
  return ((g.name || 'fark') + ' ' + ['entry', 'target', 'stop'].map((k) => (isNum(g[k]) ? sgn(g[k], d) || num(0, d, false) : '—')).join(' / ')
    + ' ' + (GAP_UNIT[g.unit] || g.unit || '')).trim();
}

/** A level of the model's own (the signal's units) as the instrument's level, the gap beside it: "%38,720 (+6,9 bp
 * patikanın üstünde)"; a VİOP contract's price after its rate ("%38,400 · fiyat 42,8150 (…)"). */
export function quoteLevel(q, v) {
  if (!isNum(v)) return '—';
  const alt = q.alt || null;
  return quoteText(q, q.base + q.scale * v) + (alt && isNum(alt.base) ? ' · ' + alt.label + ' ' + quoteText(alt, alt.base + alt.scale * v) : '')
    + ' (' + gapText(q, v) + ')';
}

/** A signal's expected P&L as one cell: FX in money per 1 mn of the base currency, a rates package in bp (its TL in
 * the tooltip), anything else in its own unit. */
export function pnlCell(s) {
  const mo = s.money || {};
  const pu = s.pnl_unit || '';
  // (a line at its calibrated levels: its expectancy is the record's - its trades at those levels - × σ now)
  const lv = s.levels || {};
  const rec = lv.ok && isNum(lv.exp) ? ' · seviyelerle işlem başına ' + sgn(lv.exp, 2) + 'σ (' + (lv.n || 0) + ' işlem, ' + (lv.oos ? 'örneklem dışı' : 'örneklem içi') + ')' : '';
  if (s.px && isNum(mo.total)) {
    return { t: money(mo.total, mo.ccy) + ' / 1 mn ' + mo.base, v: mo.total, k: 'n',
      tip: 'Tutma boyunca beklenen K/Z, 1 mn ' + mo.base + ' başına (' + s.px.inst + ', notional × fiyat hareketi)'
        + (s.px.tenor ? ': forward primi (carry) ' + money(mo.carry, mo.ccy) + ', kur hareketi ' + money(mo.move, mo.ccy) : '')
        + (isNum(s.pnl_try) && mo.ccy !== 'TRY' ? ' · ≈ ' + money(s.pnl_try, 'TRY') : '') + ' · nominalin ' + sgn(s.exp_pnl, 2) + '%\'si' + rec };
  }
  if (!isNum(s.exp_pnl)) return { t: '', k: '' };
  if (isNum(mo.per_unit) && isNum(mo.total)) {
    // (a line of linear money - an option's vega, a swap's points: the money, its units in the tooltip)
    return { t: money(mo.total, mo.ccy), v: mo.total, k: 'n', tip: 'Tutma boyunca beklenen K/Z: ' + sgn(s.exp_pnl, 2) + ' ' + (pu === 'vol' ? 'vol puanı' : pu)
      + ' × ' + num(mo.per_unit, 0) + ' ' + mo.ccy + ((s.info || {}).size ? ' (' + s.info.size + ')' : '') + (isNum(s.sigma_h) ? ' · ufuk σ ' + fmt(s.sigma_h, 2) + ' ' + pu : '') + rec };
  }
  const tip = 'Tutma boyunca beklenen K/Z' + (pu === 'bp' ? ', carry + roll dahil' : '')
    + (pu === 'bp' && isNum(mo.total) ? ' · ≈ ' + money(mo.total, 'TL') + ' (ana bacak ' + num(mo.dv01_usd, 0) + ' $ DV01 = ' + num(mo.per_bp, 0) + ' TL / bp)' : '')
    + (isNum(s.sigma_h) ? ' · ufuk σ ' + fmt(s.sigma_h, 2) + ' ' + pu : '') + rec;
  return { t: sgn(s.exp_pnl, 2) + (pu ? ' ' + pu : ''), v: s.exp_pnl, k: 'n', tip };
}

/** A line's calibrated levels in its cells (tto/quantlevels.py): Ödül / risk and İsabet with the levels in the tooltip
 * - "stop 1,20σ · hedef 1,80σ · ödül / risk 1,50 · isabet %57 (46 işlem, örneklem dışı) · işlem başına +0,21σ" -, or
 * why the line has none (its family's own levels: VİOP's order levels, an intraday family's …). */
export function levelCells(s, rr) {
  const lv = s.levels || null;
  const ok = !!(lv && lv.ok);
  const why = lv ? (ok ? lv.text || '' : lv.why || '') : '';
  const rrCell = N(rr, 2, { tip: (ok ? 'Ödül ÷ risk (geçmiş işlemlerden ayarlı seviyeler): ' + why : 'Ödül ÷ risk (hedefe ve stoba uzaklık)' + (why ? ' · ' + why : ''))
    + (isNum(s.exp_r) ? ' · beklenen ÷ risk ' + fmt(s.exp_r, 2) : '') });
  const hit = ok && isNum(lv.hit) ? T(pct(lv.hit) + ' (' + (lv.n || 0) + ')', { tip: why + (lv.oos ? '' : ' · örneklem dışı işlem az: bugünkü seviyelerin örneklem içi kaydı') })
    : T('—', { tip: why || 'seviye kalibrasyonu yok', cls: 'soft' });
  return [rrCell, hit];
}

/** A number cell: text, value, an optional class and tooltip. */
export function N(v, d = 2, opts = {}) {
  if (!isNum(v)) return { t: opts.empty || '', k: '' };
  return Object.assign({ t: (opts.sign ? sgn(v, d) : fmt(v, d)) + (opts.unit ? ' ' + opts.unit : ''), v, k: 'n' }, opts.cls ? { cls: opts.cls } : {},
    opts.tip ? { tip: opts.tip } : {}, opts.heat ? { heat: opts.heat } : {}, opts.b ? { b: 1 } : {});
}

export function T(t, opts = {}) {
  return Object.assign({ t: t == null ? '' : String(t), k: 's' }, opts);
}

/** A z cell: bold past the entry threshold. */
export function Z(v, entry = 2, opts = {}) {
  if (!isNum(v)) return { t: '', k: '' };
  return Object.assign({ t: sgn(v, 2), v, k: 'n', cls: Math.abs(v) >= entry ? 'thru' : '' }, opts.heat ? { heat: heatHex(v / 3) } : {},
    opts.tip ? { tip: opts.tip } : {});
}

/** Red up, blue down, deeper as |t| nears 1 (a hex colour; the grid takes its strength from the colour's chroma). */
export function heatHex(t) {
  if (!isNum(t) || Math.abs(t) < 0.02) return null;
  const a = Math.min(1, Math.abs(t));
  const base = t > 0 ? [230, 103, 103] : [57, 135, 229];
  return base.map((c) => Math.round(128 + (c - 128) * a).toString(16).padStart(2, '0')).join('').toUpperCase();
}

export function seg(options, value, onChange, id) {
  const el = h('div', { class: 'seg', id });
  const set = (v) => { for (const b of el.children) b.classList.toggle('on', b.dataset.v === String(v)); };
  for (const [v, label, title] of options) {
    const b = h('button', { type: 'button', title: title || '' }, label);
    b.dataset.v = String(v);
    b.addEventListener('click', () => { set(v); onChange(v); });
    el.appendChild(b);
  }
  el.set = set;
  set(value);
  return el;
}

export function pref(key, fallback) {
  try { const v = localStorage.getItem(key); return v === null ? fallback : v; } catch (e) { return fallback; }
}

export function keep(key, value) {
  try { localStorage.setItem(key, String(value)); } catch (e) { /* not kept */ }
}

// ------------------------------------------------------------------------------------------------ the pages' layout
// (Düzen, 27.11.2026 - the desk: "Hepsini yap"): a panel is as wide as its table, narrow ones side by side (``wide``: the
// whole row - the signal list, the card, a panel with a chart); every panel folds (▾ / ▸ among its tools, its title
// while folded; the choice kept in the browser), a long page's secondary panels folded until opened (``folded``); an
// empty panel is its title and its reason (``qempty``); the long pages list their panels in a jump bar.
const FOLD_PREF = 'tto.quant.fold.';

/**
 * A panel with a title, its tools (copy, fold), a body and its two explanations: ``{el, body, note, read, tools,
 * setTitle, toggle}``. ``read``, above the body, says in the desk's words what the table tells and which number means a
 * trade (``quantread.js``); ``note``, below it, how it is computed - labelled "Yöntem" when the panel has a read line,
 * unless its note is live information rather than a method (``isInfo``). ``opts.wide``: the page's whole width (else as
 * wide as its table); ``opts.folded``: folded until the user opens it (their choice kept, either way).
 */
export function panel(id, title, opts = {}) {
  const body = h('div', { class: 'body' });
  const said = readLine(id);
  const read = h('div', { class: 'qread', id: id + '-read' }, said || null);
  const note = h('div', { class: 'muted qnote' + (said && !isInfo(id) ? ' qmethod' : '') });
  const head = h('h2', { title }, title);                  // (a narrow panel's title may end in "…": whole in its tooltip)
  const tools = h('div', { class: 'tools' });
  const key = FOLD_PREF + id;
  const folded = pref(key, opts.folded ? '1' : '0') === '1';
  const fold = h('button', { class: 'iconbtn qfold', type: 'button', title: 'Daralt / aç' }, folded ? '▸' : '▾');
  tools.appendChild(fold);
  const header = h('header', null, head, h('span', { class: 'grow' }), ...(opts.right || []), tools);
  const el = h('section', { class: 'panel ' + (opts.wide ? 'wide' : 'fit') + (opts.cls ? ' ' + opts.cls : '') + (folded ? ' collapsed' : ''), id },
    header, read, opts.top || null, body, note);
  const toggle = (now) => {
    el.classList.toggle('collapsed', now);
    fold.textContent = now ? '▸' : '▾';
    keep(key, now ? '1' : '0');
  };
  fold.addEventListener('click', () => toggle(!el.classList.contains('collapsed')));
  // (a folded panel opens from its title too: the tools show only under the pointer)
  header.addEventListener('click', (e) => {
    if (el.classList.contains('collapsed') && !e.target.closest('button, select, input, a, label')) toggle(false);
  });
  el.__open = () => { if (el.classList.contains('collapsed')) toggle(false); };
  return { el, body, note, read, tools, setTitle: (t) => { head.textContent = t; head.title = t; }, toggle };
}

/** Bring a panel of the page into view, opened if it was folded (a jump link, ``#/quant?p=<panel id>``). */
export function showPanel(el) {
  if (!el) return;
  if (el.__open) el.__open();
  el.scrollIntoView({ block: 'start', behavior: 'smooth' });
  el.classList.remove('focus');
  void el.offsetWidth;                                     // (the mark again, when it is still on)
  el.classList.add('focus');
}

/** A long page's panels as links above them: a click opens the panel (folded ones say ▸) and brings it into view. */
export function jumpBar(page, id) {
  const bar = h('nav', { class: 'qjump', id: id || null, 'aria-label': 'Bu sayfadaki tablolar' });
  const panels = [...page.querySelectorAll(':scope > section.panel')];
  const titles = panels.map((el) => ((el.querySelector(':scope > header h2') || {}).textContent || el.id).split(' · '));
  const first = titles.map((t) => t[0]);
  panels.forEach((el, i) => {
    // (a title's first part; two panels starting alike - "Sinyal kaydı · …" - with their second part too)
    const name = first.indexOf(first[i]) !== first.lastIndexOf(first[i]) ? titles[i].slice(0, 2).join(' · ') : first[i];
    const a = h('a', { href: '#', title: 'Tabloya git' + (el.classList.contains('collapsed') ? ' (açılır)' : '') },
      name + (el.classList.contains('collapsed') ? ' ▸' : ''));
    a.dataset.panel = el.id;
    a.addEventListener('click', (e) => { e.preventDefault(); showPanel(el); a.textContent = name; });
    bar.appendChild(a);
  });
  return bar;
}

/** The name the 19 signal lists share for their columns (the desk, Düzen 27.11.2026: one "Sütunlar" choice for all of
 * them - the Sinyaller list's, its box's and every analysis page's; the server hides the secondary statistics of a user
 * who never chose: Service.DEFAULT_HIDDEN_COLUMNS). */
export const SIGNALS_TABLE = 'quant/signals';

/**
 * A table of the dashboard's grid in a panel body: rows can be clicked (``onPick(key, true)``), the picked one is
 * marked, the copy button puts it on the clipboard (Excel). ``opts.freeze``: its first columns stay in view while it
 * scrolls sideways (the identifier: the trade, the bond, the contract). With no rows the panel is its title and the
 * reason (``qempty``).
 */
export class GridBox {
  constructor(p, name, onPick, opts = {}) {
    this.p = p;
    this.name = name;
    this.onPick = onPick;
    this.freeze = opts.freeze || 0;
    this.grid = null;
    this.keys = [];
    const copy = h('button', { class: 'iconbtn', type: 'button', title: 'Tabloyu kopyala (Excel\'e yapıştırılabilir)' }, 'Kopyala');
    copy.addEventListener('click', () => { if (this.grid) copyGrid(this.grid); });
    p.tools.insertBefore(copy, p.tools.querySelector('.qfold'));
  }

  set(header, rows, keys, empty, picked) {
    this.keys = keys || [];
    const body = this.p.body;
    this.p.el.classList.toggle('qempty', !rows.length);
    if (!rows.length) {
      clear(body);
      this.grid = null;
      body.appendChild(h('div', { class: 'empty' }, empty || 'Veri yok'));
      return;
    }
    const marked = rows.map((row, i) => (picked && this.keys[i] === picked
      ? row.map((c) => (c && typeof c === 'object' ? (c.sk ? c : Object.assign({}, c, { cls: ((c.cls || '') + ' pick').trim() })) : { t: c == null ? '' : String(c), k: 's', cls: 'pick' }))
      : row));
    const data = plainData(header, marked);
    // (the grid's frozen panes - a workbook table's freeze - for a table of our own: the identifier column)
    if (this.freeze) data.fz = this.freeze;
    if (this.grid) { this.grid.replace(data); return; }
    clear(body);
    const g = new Grid({ data, editable: false, name: this.name, tools: toolsOf(body), freeze: this.freeze || undefined });
    if (this.onPick) {
      g.el.classList.add('pickable');
      g.el.addEventListener('click', (e) => {
        if (e.target.closest('button')) return;
        const td = e.target.closest('td');
        if (!td || td.__i === undefined || td.__i < 1) return;
        const k = this.keys[td.__i - 1];
        if (k) this.onPick(k, true);
      });
    }
    this.grid = g;
    body.appendChild(g.el);
  }
}

// ------------------------------------------------------------------------------------------------ one signal, drawn
/** The series of a signal (or of any monitor): the level with its window mean, ±entry and ±stop bands (in z), the
 * entry / target / stop lines; below it the score day by day against ±entry and ±stop. */
export class SignalChart {
  /** opts.ids: false - the card without the page's element ids (a box's card beside the page's own) */
  constructor(host, opts = {}) {
    this.host = host;
    this.ids = opts.ids !== false;
    this.charts = {};
    this.el = h('div', { class: 'seriesview qchart' });
    this.titleEl = h('div', { class: 'ct svtitle' });
    this.statEl = h('div', { class: 'muted svstat' });
    this.levelHead = h('div', { class: 'ct' });
    this.zHead = h('div', { class: 'ct' });
    this.levelHost = h('div', { class: 'volchart' });
    this.zHost = h('div', { class: 'volchart' });
    this.zBox = h('div', null, this.zHead, this.zHost);
    this.plots = h('div', { class: 'volcharts svcharts' }, h('div', null, this.levelHead, this.levelHost), this.zBox);
    this.details = h('div', { class: 'qdetails' });
    this.lead = h('div', { class: 'qlead' });                   // the signal in plain words: first, above the charts
    this.empty = h('div', { class: 'empty' }, 'Bir sinyale ya da satıra tıklayın: serisi, ±z bantları ve giriş / hedef / stop burada çizilir.');
    this.el.append(this.titleEl, this.statEl, this.lead, this.plots, this.details, this.empty);
    this.plots.classList.add('hidden');
    host.appendChild(this.el);
  }

  destroy() {
    for (const c of Object.values(this.charts)) if (c) c.destroy();
    this.charts = {};
    this.el.remove();
  }

  /** An element's id on the page's card; none on a box's (the page may be on screen beside it). */
  id(name) {
    return this.ids ? name : null;
  }

  loading(title) {
    this.titleEl.textContent = title || '';
    clear(this.lead);
    clear(this.details);
    this.empty.textContent = 'Yükleniyor…';
    this.empty.classList.remove('hidden');
    this.plots.classList.add('hidden');
    this.mark(false);
  }

  /** No line to draw (the page has none now): the card is its title and why - a click on a row draws one. */
  idle(text) {
    this.titleEl.textContent = '';
    this.statEl.textContent = '';
    clear(this.lead);
    clear(this.details);
    this.empty.textContent = text;
    this.empty.classList.remove('hidden');
    this.plots.classList.add('hidden');
    this.mark(true);
  }

  /** The card's panel (on a page) as empty - its title and the reason - or not. */
  mark(empty) {
    const p = this.host.closest ? this.host.closest('.panel') : null;
    if (p) p.classList.toggle('qempty', empty);
  }

  show(d) {
    this.mark(false);
    const m = d.monitor || {};
    const s = d.signal;
    const hist = d.history || {};
    const cfg = d.settings || {};
    const days = hist.days || [];
    const vals = hist.values || [];
    this.titleEl.textContent = (m.family_label ? m.family_label + ' · ' : '') + (s ? s.expression : m.name || '');
    clear(this.details);
    clear(this.lead);
    if (s) this.lead.appendChild(this.plainBlock(s));
    if (days.length < 2) {
      this.plots.classList.add('hidden');
      this.empty.classList.remove('hidden');
      this.empty.textContent = 'Bu serinin geçmişi yok.';
      return;
    }
    this.empty.classList.add('hidden');
    this.plots.classList.remove('hidden');
    const digits = isNum(m.digits) ? m.digits : 2;
    const entryZ = isNum(m.entry) ? m.entry : (cfg.entry_z || 2);
    const stopZ = cfg.stop_z || 3.5;
    const fisher = hist.transform === 'fisher';
    const fw = (x) => (fisher ? 0.5 * Math.log((1 + x) / (1 - x)) : x);
    const inv = (x) => (fisher ? Math.tanh(x) : x);
    const allDays = days.slice();
    const allVals = vals.slice();
    if (isNum(m.level) && d.today && d.today > days[days.length - 1]) { allDays.push(d.today); allVals.push(m.level); }
    const flat = (v) => allDays.map(() => (isNum(v) ? v : null));
    // (an FX signal's series is not the price it trades at: its legend says so)
    const series = [{ name: m.series_label ? 'analiz serisi' : (m.name || 'seri'), kind: 'line', color: BLUE, data: allVals, marker: false }];
    const mr = isNum(hist.mean) && isNum(hist.sd) && m.mode !== 'drift';
    if (mr) {
      const mu = fw(hist.mean);
      series.push({ name: 'ortalama', kind: 'line', color: GREY, data: flat(hist.mean), marker: false });
      series.push({ name: '±' + num(entryZ, 1, false) + 'σ (giriş)', kind: 'line', color: GREY, dash: true, data: flat(inv(mu + entryZ * hist.sd)), marker: false });
      series.push({ name: '−giriş', kind: 'line', color: GREY, dash: true, data: flat(inv(mu - entryZ * hist.sd)), marker: false, legend: 0 });
      series.push({ name: '±' + num(stopZ, 1, false) + 'σ (stop)', kind: 'line', color: RED, dash: true, data: flat(inv(mu + stopZ * hist.sd)), marker: false });
      series.push({ name: '−stop', kind: 'line', color: RED, dash: true, data: flat(inv(mu - stopZ * hist.sd)), marker: false, legend: 0 });
    }
    if (s) {
      series.push({ name: 'giriş (şimdi)', kind: 'line', color: PURPLE, data: flat(s.entry), marker: false });
      series.push({ name: 'hedef', kind: 'line', color: GREEN, data: flat(s.target), marker: false });
      series.push({ name: 'stop', kind: 'line', color: ORANGE, data: flat(s.stop), marker: false });
    }
    const x = { type: 'date', values: allDays.map(serialOf), format: 'mmm yy' };
    const unit = m.unit || '';
    const level = { title: m.name, cats: allDays.map(isoToTr), x, auto: 'fit', decimals: digits, y_title: unit, aspect: 0.42, series };
    // (an FX signal's series is the analysis' own - its trade is told in prices below)
    this.levelHead.textContent = (m.series_label ? 'Analiz serisi: ' + m.series_label : 'Seviye' + (unit ? ' (' + unit + ')' : ''))
      + (mr ? ' · ortalama, ±giriş ve ±stop bantları penceresinin σ\'sıyla' : '');
    if (this.charts.level) this.charts.level.update(level); else this.charts.level = new Chart(this.levelHost, level, { height: 250 });
    const zs = (hist.z || []).slice();
    const hasZ = zs.some(isNum);
    this.zBox.classList.toggle('hidden', !hasZ);
    if (hasZ) {
      const zDays = days.slice();
      if (isNum(m.z) && d.today && d.today > days[days.length - 1]) { zDays.push(d.today); zs.push(m.z); }
      const zf = (v) => zDays.map(() => v);
      const zspec = { title: (m.score_name || 'z'), cats: zDays.map(isoToTr), x: { type: 'date', values: zDays.map(serialOf), format: 'mmm yy' },
        auto: 'fit', decimals: 2, y_title: m.score_name || 'z', aspect: 0.42,
        series: [{ name: m.score_name || 'z', kind: 'line', color: PURPLE, data: zs, marker: false },
          { name: '±giriş', kind: 'line', color: GREY, dash: true, data: zf(entryZ), marker: false },
          { name: '−giriş', kind: 'line', color: GREY, dash: true, data: zf(-entryZ), marker: false, legend: 0 },
          { name: '±stop', kind: 'line', color: RED, dash: true, data: zf(stopZ), marker: false },
          { name: '−stop', kind: 'line', color: RED, dash: true, data: zf(-stopZ), marker: false, legend: 0 }] };
      this.zHead.textContent = (m.score_name || 'z') + ' · gün gün';
      if (this.charts.z) this.charts.z.update(zspec); else this.charts.z = new Chart(this.zHost, zspec, { height: 250 });
    }
    // (a level of the model's own: the traded instrument's level first, the gap beside it - "Şimdi 6x9 FRA %38,720 (+6,9 bp …)")
    const sq = s && !s.px && s.quote ? s.quote : null;
    this.statEl.textContent = 'Şimdi ' + (sq ? sq.inst + ' ' + quoteLevel(sq, m.level) : fmt(m.level, digits) + (unit ? ' ' + unit : '') + sheetText(s || m, m.level))
      + ' · ' + (m.score_name || 'z') + ' ' + sgn(m.z, 2)
      + (isNum(m.half_life) ? ' · yarı ömür ' + fmt(m.half_life, 1) + ' gün' : '')
      + (m.regime && m.regime.tag ? ' · rejim ' + (REGIME[m.regime.tag] || m.regime.tag) : '')
      + ' · ' + isoToTr(days[0]) + ' – ' + isoToTr(days[days.length - 1]) + ' · ' + days.length + ' gün';
    this.fillDetails(d);
  }

  fillDetails(d) {
    const m = d.monitor || {};
    const s = d.signal;
    const box = this.details;
    if (s) {
      const pu = s.pnl_unit || '';
      // every package that trades the signal, leg by leg: what to do, on what, how much (the main leg's DV01 the
      // setting's, 1.000 $ by default) - a signal without packages of its own: its legs
      const legTable = (legs) => {
        const t = h('table', { class: 'plain qlegs' }, h('tr', null, h('th', null, 'İşlem'), h('th', null, 'Enstrüman'), h('th', null, 'Nominal (mn TL)'),
          h('th', null, 'DV01 ($/bp)'), h('th', null, 'DV01 (TL/bp)'), h('th', null, 'Ağırlık')));
        for (const l of legs || []) {
          t.appendChild(h('tr', null, h('td', null, h('b', null, l.action || '')), h('td', null, l.name || l.text || ''),
            h('td', { class: 'n' }, num(l.notional, 1)), h('td', { class: 'n' }, num(l.dv01_usd, 0)),
            h('td', { class: 'n' }, num(l.dv01, 0)), h('td', { class: 'n' }, fmt(l.weight, 2))));
        }
        return t;
      };
      const packs = h('div', { class: 'qpacks' });
      const plist = (s.packages && s.packages.length) ? s.packages : [{ name: '', legs: s.legs }];
      for (const pk of plist) {
        const bits = [];
        if (isNum(pk.carry_week)) bits.push('carry + roll ' + sgn(pk.carry_week, 2) + ' ' + (pu || 'bp') + ' / hafta');
        if (isNum(pk.exp_pnl)) {
          bits.push('beklenen ' + sgn(pk.exp_pnl, 2) + ' ' + pu + (pu === 'bp' && isNum((s.money || {}).per_bp) ? ' ≈ ' + money(pk.exp_pnl * s.money.per_bp, 'TL') : '')
            + ' (tutma boyunca, carry + roll dahil)');
        }
        const box1 = h('div', { class: 'qpack' });
        if (pk.name) box1.appendChild(h('div', { class: 'qpack-head' }, h('b', null, pk.name), bits.length ? ' · ' + bits.join(' · ') : ''));
        box1.appendChild(legTable(pk.legs));
        if (pk.note) box1.appendChild(h('div', { class: 'qpack-note muted' }, pk.note));
        packs.appendChild(box1);
      }
      const p = s.parts || {};
      const fx = s.fx || null;
      // (the trade in desk words, its prices, the sentence and the money are above the charts: plainBlock)
      const lines = [
        ['Tez', s.thesis || ''],
        ['Skor', (s.score_name || 'z') + ' ' + sgn(s.z, 2) + (s.daily ? '' : ' (giriş ' + fmt(s.entry_z, 2) + ')') + ' · ' + (s.gated ? LOW : s.strength)],
        ['Yarı ömür · tutma', (isNum(s.half_life) ? fmt(s.half_life, 1) + ' ' + (s.horizon_unit || 'gün') : '—') + ' · ' + (isNum(s.hold) ? fmt(s.hold, 0) + ' ' + (s.horizon_unit || 'gün') : '—')],
        [fx ? 'Forward primi' : 'Carry + roll / hafta', fx ? (isNum(s.carry_yr) ? 'yıllık %' + sgn(s.carry_yr, 1) + ' (sürekli bileşik, en kısa forward), işlemin '
          + (s.carry_yr >= 0 ? 'lehine' : 'aleyhine')
          + (isNum((s.money || {}).carry) && s.px && s.px.tenor ? ' · ufukta ' + money(s.money.carry, s.money.ccy) + ' / 1 mn ' + s.money.base : '')
          + (fx.tenors && fx.tenors.length ? ' · forward\'lar ' + fx.tenors.join(' / ') : '') + (isNum(fx.spot) ? ' · spot ' + fmt(fx.spot, s.px ? s.px.digits : 4) : '')
          + (isNum(fx.fwd_h) ? ' · ufkun forward\'ı ' + fmt(fx.fwd_h, s.px ? s.px.digits : 4) : '') : 'forward yok: carry bilinmiyor')
          : (isNum(s.carry_week) ? sgn(s.carry_week, 2) + ' ' + (pu || 'bp') : '—')],
        ['Rejim', (s.regime || '—') + (s.regime_info && isNum(s.regime_info.vr_z) ? ' (VR ' + fmt(s.regime_info.vr, 2) + ', z ' + sgn(s.regime_info.vr_z, 2)
          + (isNum(s.regime_info.hurst) ? ', H ' + fmt(s.regime_info.hurst, 2) : '') + (isNum(s.regime_info.vol_pct) ? ', vol yüzdelik ' + pct(s.regime_info.vol_pct) : '') + ')' : '')],
        ['Geri test', s.bt ? s.bt.text + (isNum(s.bt.sharpe) ? ' · Sharpe ' + fmt(s.bt.sharpe, 2) : '')
          + (isNum(s.bt.max_dd) ? ' · en büyük düşüş ' + fmt(s.bt.max_dd, 1) + 'σ' : '') + (s.bt.scope === 'tür' ? ' (bu tür)' : '') : 'henüz yok'],
        ['Uyum', s.agree + ' aile aynı yönde' + (s.agree_with && s.agree_with.length ? ' (' + s.agree_with.join(', ') + ')' : '')
          + (s.conflict ? ' · ' + s.conflict + ' ters (' + (s.conflict_with || []).join(', ') + ')' : '')],
        ['Bileşik', fmt(s.composite, 2) + ' = |z| ' + fmt(p.z, 2) + ' × rejim ' + fmt(p.regime, 2) + ' × yarı ömür ' + fmt(p.hl, 2) + ' × carry ' + fmt(p.carry, 2)
          + (s.gated ? ' · ' + LOW + ': ' + s.gated : '')],
      ];
      // an FX trade is told in prices; the series the analysis scores (and the chart draws) is its own
      if (s.px) {
        lines.push(['Analiz serisi', fmt(s.entry, s.digits) + ' / ' + fmt(s.target, s.digits) + ' / ' + fmt(s.stop, s.digits) + (s.unit ? ' ' + s.unit : '')
          + ' (giriş / hedef / stop) · ' + (m.series_label || m.name || '') + (isNum(s.exp_pnl) ? ' · beklenen ' + sgn(s.exp_pnl, 2) + ' ' + pu : '')
          + (isNum(s.carry_h) ? ' (içinde forward primi ' + sgn(s.carry_h, 2) + ' ' + pu + ')' : '')
          + (isNum(s.sigma_h) ? ' · ufuk σ ' + fmt(s.sigma_h, 2) + ' ' + pu : '')]);
      } else if (s.quote) {
        // ... and a level of the model's own in the traded instrument's (above): the model's own numbers - its gap - here,
        // what the instrument's are made of (the model's value now: the path's forward …)
        const q = s.quote;
        lines.push(['Model farkı', [s.entry, s.target, s.stop].map((v) => sgn(v, s.digits) || '—').join(' / ') + (s.unit ? ' ' + s.unit : '')
          + ' (giriş / hedef / stop) · ' + ((q.gap || {}).name || '') + ' · ' + q.inst + ' = ' + (q.model || 'model') + ' + fark'
          + (q.held ? ' · ' + q.held : '')]);
      }
      const kv = h('table', { class: 'plain qkv' });
      for (const [k, v] of lines) kv.appendChild(h('tr', null, h('th', null, k), h('td', null, v)));
      const gates = h('table', { class: 'plain qgates' }, h('tr', null, h('th', null, 'Kapı'), h('th', null, ''), h('th', null, 'Neden')));
      for (const g of s.gates || []) {
        gates.appendChild(h('tr', { class: g.ok ? 'ok' : 'fail' }, h('td', null, g.name), h('td', { class: g.ok ? 'thru' : 'soft' }, g.ok ? '✓' : '✗'), h('td', null, g.text || '')));
      }
      box.append(h('div', { class: 'qcols' }, kv, h('div', null, packs, gates)));
    }
    const info = m.info || {};
    const extra = [];
    if (info.ou && isNum(info.ou.b)) extra.push('OU: b ' + fmt(info.ou.b, 3) + (isNum(info.ou.mu) ? ', μ ' + fmt(info.ou.mu, 2) : '') + (isNum(info.ou.sigma_eq) ? ', σ_eq ' + fmt(info.ou.sigma_eq, 2) : ''));
    if (isNum(info.beta)) extra.push('β ' + fmt(info.beta, 3) + (isNum(info.static_beta) ? ' (statik ' + fmt(info.static_beta, 3) + ', statik z ' + sgn(info.static_z, 2) + ')' : '')
      + (isNum(info.adf) ? ' · ADF ' + fmt(info.adf, 2) + ' (%5 kritik ' + fmt(info.crit5, 2) + ')' : ''));
    if (isNum(info.hit_rate)) extra.push('Model: yukarı olasılığı ' + pct(info.p, 1) + ' · doğrulama isabeti ' + pct(info.hit_rate, 1) + ' (' + info.n_test + ' test, log-loss ' + fmt(info.log_loss, 3) + ')');
    if (info.garch && isNum(info.garch.alpha)) extra.push('GARCH(1,1): α ' + fmt(info.garch.alpha, 3) + ', β ' + fmt(info.garch.beta, 3) + ', uzun dönem vol ' + fmt(Math.sqrt(252 * info.garch.long_var), 2));
    if (info.phase) extra.push('Faz: ' + info.phase + ' · ortalama ' + sgn(info.mean, 1) + ' bp · n ' + info.n + ' · t ' + sgn(info.t, 2)
      + (isNum(info.periods) ? ' · ' + fmt(info.periods, 1) + ' bağımsız dönem, eşik ' + fmt(info.cv, 2) : ''));
    if (isNum(info.net_dv01)) extra.push((info.version === 'klasik' ? 'Klasik' : 'PCA ağırlıklı') + ': net DV01 ' + sgn(info.net_dv01, 0) + ' TL/bp · 1σ PC1 / PC2 / PC3 '
      + (info.exposures || []).map((x) => sgn(x, 2)).join(' / ') + ' bp');
    if (info.compare) extra.push('Fark: ' + info.compare);
    if (isNum(info.window)) extra.push('Pencere: ' + info.window + ' gün');
    if (m.note) extra.push(m.note);
    for (const t of extra) box.appendChild(h('div', { class: 'muted qline' }, t));
    this.fillRationale(d);
  }

  /** The signal as the desk reads it: the trade in desk words, entry / target / stop in the instrument's own price (FX:
   * the forward of the holding, with the spot; a level of the model's own: the traded instrument's - the FRA's rate -,
   * the model's gap beside it), the plain sentence (the server's, from the signal's own numbers) and
   * the money - FX per 1 mn of the base currency (its forward premium's part and the spot's), a rates package in bp and
   * TL of its main leg's DV01 - at the horizon, at the target and at the stop. */
  plainBlock(s) {
    const px = s.px || null;
    const q = px ? null : (s.quote || null);
    const mo = s.money || {};
    const pu = s.pnl_unit || '';
    const lv = (v) => levelText(v, s.unit, s.digits) + sheetText(s, v);       // (a fly: the OIS sheet's quote beside it)
    const span = isNum(s.hold) ? fmt(s.hold, 0) + ' ' + (s.horizon_unit === 'bar' ? 'bar (5 dk)' : 'iş günü') : 'ufuk';
    // every leg with its nominal and DV01 ($ and TL a bp) where they are known: the trade's tooltip
    const legs = s.legs || [];
    const sizedLegs = legs.some((l) => isNum(l.dv01_usd)) ? legs.map((l) => l.action + ' ' + l.name + (isNum(l.dv01_usd) ? ' ('
      + (isNum(l.notional) ? num(l.notional, 1) + ' mn TL · ' : '') + 'DV01 ' + num(l.dv01_usd, 0) + ' $' + (isNum(l.dv01) ? ' / ' + num(l.dv01, 0) + ' TL' : '') + ')' : '')).join(' · ') : '';
    const rows = [];
    const trade = h('td', { id: this.id('quant-sig-trade'), title: sizedLegs || s.expression || null }, h('b', null, s.trade_tr || s.expression || ''));
    if (px) trade.append(' · ' + ((s.info || {}).size || '1 mn ' + mo.base));      // (a universe line's own size: Trend's "1,4 mn EUR")
    else if (isNum(mo.per_bp)) trade.append(' · ana bacak ' + num(mo.dv01_usd, 0) + ' $ DV01 = ' + num(mo.per_bp, 0) + ' TL / bp');
    else if (isNum(mo.per_unit) && (s.info || {}).size) trade.append(' · ' + s.info.size);
    rows.push(['İşlem', trade]);
    // "İşleme al": the Trades form filled from this line (or, disabled, why Trades cannot book it)
    rows.push(['Trades', h('td', { class: 'qbook' }, bookButton(s, this.id('quant-sig-book')))]);
    // its place in the list: the group, TRY OIS's end, an Offshore line's "offshore limiti"; a gate's hold: "düşük güven"
    if (s.group) {
      rows.push(['Grup', h('td', { id: this.id('quant-sig-group'), class: s.tag ? 'qtag' : null }, groupText(s)
        + (s.gated ? ' · ' + LOW + ' (' + s.gated + ')' : ''))]);
    }
    const d = px ? px.digits : s.digits;
    // (a level of the model's own: the traded instrument's levels - the FRA's rate -, the model's gap at each beside them,
    // what they are held on - "hedef / stop bugünkü PPK patikasıyla" -; a VİOP contract's prices after them)
    const alt = q && q.alt ? q.alt : null;
    rows.push(['Giriş / hedef / stop', h('td', { id: this.id('quant-sig-prices') }, px
      ? fmt(px.entry, d) + ' / ' + fmt(px.target, d) + ' / ' + fmt(px.stop, d) + ' · ' + px.inst + ' (giriş: ' + px.note
        + (px.tenor ? ' · spot ' + fmt(px.spot, d) : '') + ')' + (isNum(px.spot_exp) ? ' · ' + span + ' sonra beklenen kur ' + fmt(px.spot_exp, d) : '')
      : q ? quoteText(q, q.entry) + ' / ' + quoteText(q, q.target) + ' / ' + quoteText(q, q.stop) + ' · ' + q.inst + ' (' + gapsText(q)
          + (q.note ? '; ' + q.note : '') + ')' + (alt ? ' · ' + alt.label + ' ' + [alt.entry, alt.target, alt.stop].map((v) => quoteText(alt, v)).join(' / ') : '')
        : lv(s.entry) + ' / ' + lv(s.target) + ' / ' + lv(s.stop) + (s.instrument ? ' · ' + s.instrument : ''))]);
    let pnl = '—';
    let tip = null;
    if (px && isNum(mo.total)) {
      const eq = [];
      if (mo.ccy !== 'TRY' && isNum(mo.try_per)) eq.push(money(mo.total * mo.try_per, 'TRY'));
      if (mo.ccy !== 'USD' && mo.ccy !== 'TRY' && isNum(mo.usd_per)) eq.push(money(mo.total * mo.usd_per, 'USD'));
      pnl = money(mo.total, mo.ccy) + ' / 1 mn ' + mo.base + (eq.length ? ' (≈ ' + eq.join(' · ') + ')' : '')
        + (px.tenor ? ' · forward primi (carry) ' + money(mo.carry, mo.ccy) + ' · kur hareketi ' + money(mo.move, mo.ccy) : '');
      tip = span + ' boyunca: 1 mn ' + mo.base + ' × fiyat hareketi (' + fmt(px.entry, d) + ' → ' + fmt(px.exit, d) + '); nominalin ' + sgn(s.exp_pnl, 2) + '%\'si'
        + (isNum(s.sigma_h) ? ' · ufuk σ ' + fmt(s.sigma_h, 2) + '%' : '');
    } else if (pu === 'bp' && isNum(s.exp_pnl)) {
      const bp = mo.bp || {};
      pnl = sgn(s.exp_pnl, 2) + ' bp' + (isNum(mo.total) ? ' ≈ ' + money(mo.total, 'TL') : '')
        + (isNum(bp.carry) ? ' · carry + roll ' + sgn(bp.carry, 2) + ' bp · hareket ' + sgn(bp.move, 2) + ' bp' : '')
        + (isNum(s.sigma_h) ? ' · ufuk σ ' + fmt(s.sigma_h, 2) + ' bp' : '');
      tip = span + ' boyunca';
    } else if (isNum(mo.per_unit) && isNum(s.exp_pnl)) {
      pnl = sgn(s.exp_pnl, 2) + ' ' + (pu === 'vol' ? 'vol puanı' : pu) + (isNum(mo.total) ? ' ≈ ' + money(mo.total, mo.ccy) : '');
      tip = span + ' boyunca, ' + num(mo.per_unit, 0) + ' ' + mo.ccy + ' / ' + (pu === 'vol' ? 'vol puanı' : pu) + (isNum(s.sigma_h) ? ' · ufuk σ ' + fmt(s.sigma_h, 2) + ' ' + pu : '');
    } else if (isNum(s.exp_pnl)) {
      pnl = sgn(s.exp_pnl, 2) + ' ' + (pu === 'vol' ? 'vol puanı' : pu);
      tip = span + ' boyunca' + (isNum(s.sigma_h) ? ' · ufuk σ ' + fmt(s.sigma_h, 2) + ' ' + pu : '');
    }
    rows.push(['Beklenen K/Z', h('td', { id: this.id('quant-sig-pnl'), title: tip }, pnl)]);
    const rr = isNum(s.rr) ? s.rr : (isNum(mo.target) && isNum(mo.stop) && mo.stop < 0 ? mo.target / -mo.stop : null);
    let ends = '';
    // (a level of the model's own: the instrument's level at the target and the stop first - "hedefte (%38,652) 6,8 bp …")
    const at = (k) => (q && isNum(q[k]) ? '(' + quoteText(q, q[k]) + ') ' : '');
    if (px && (isNum(mo.target) || isNum(mo.stop))) {
      ends = 'hedefte ' + (money(mo.target, mo.ccy) || '—') + ' · stopta ' + (money(mo.stop, mo.ccy) || '—') + ' (1 mn ' + mo.base + ')';
    } else if (isNum(mo.per_bp) && mo.bp && (isNum(mo.bp.target) || isNum(mo.bp.stop))) {
      ends = 'hedefte ' + at('target') + (isNum(mo.bp.target) ? fmt(mo.bp.target, 1) + ' bp ≈ ' + money(mo.target, 'TL') : '—')
        + ' · stopta ' + at('stop') + (isNum(mo.bp.stop) ? fmt(Math.abs(mo.bp.stop), 1) + ' bp ≈ ' + money(mo.stop, 'TL') : '—');
    } else if (isNum(mo.per_unit) && (isNum(mo.target) || isNum(mo.stop))) {
      ends = 'hedefte ' + at('target') + (money(mo.target, mo.ccy) || '—') + ' · stopta ' + at('stop') + (money(mo.stop, mo.ccy) || '—');
    } else if (isNum(s.reward) || isNum(s.risk)) {
      ends = 'hedefe ' + at('target') + (isNum(s.reward) ? fmt(s.reward, 2) + ' ' + pu : '—') + ' · stopa ' + at('stop') + (isNum(s.risk) ? fmt(s.risk, 2) + ' ' + pu : '—');
    }
    if (ends && isNum(rr)) ends += ' · ödül / risk ' + fmt(rr, 2);
    if (ends && isNum(s.exp_r)) ends += ' · beklenen / risk ' + fmt(s.exp_r, 2);
    if (ends && s.trail) ends += ' · iz süren stop (en iyi seviyeden geri gelirse)';
    rows.push(['Hedefte / stopta', h('td', { id: this.id('quant-sig-ends') }, ends || '—')]);
    // the levels: calibrated on the family's past trades (their multiples of the holding's σ and the record they had), or why not
    const lvs = s.levels || null;
    if (lvs) {
      rows.push(['Seviyeler', h('td', { id: this.id('quant-sig-levels'), class: lvs.ok ? null : 'soft' }, lvs.ok
        ? (lvs.text || '') + (isNum(lvs.money) ? ' · işlem başına ≈ ' + money(lvs.money, lvs.ccy || '') : '')
        : (lvs.why || 'kendi seviyeleri'))]);
    }
    const t = h('table', { class: 'plain qkv qtradekv' });
    for (const [k, td] of rows) t.appendChild(h('tr', null, h('th', null, k), td));
    return h('div', { class: 'qplain' }, s.plain ? h('div', { class: 'qsentence', id: this.id('quant-sig-plain') }, s.plain) : null, t);
  }

  /** "Gerekçe": the past days most like today and what followed them, and what would undo the signal. */
  fillRationale(d) {
    const r = d.rationale;
    if (!r) return;
    const box = h('div', { class: 'qrationale' }, h('div', { class: 'ct' }, 'Gerekçe'));
    const sm = r.summary;
    const s = d.signal || {};
    const unit = (sm && sm.unit) || s.pnl_unit || '';
    if (sm) {
      // the outcomes in money too, where the signal tells its P&L in money: FX per 1 mn of the base, a package in TL
      const mm = sm.money || null;
      const per = mm ? (mm.base ? ' / 1 mn ' + mm.base : '') : '';
      const inMoney = (k) => (mm && isNum(mm[k]) ? ' (≈ ' + money(mm[k], mm.ccy) + per + ')' : '');
      box.appendChild(h('div', { class: 'qline' }, 'Bugüne en çok benzeyen ' + sm.n + ' gün (z, eğim, rejim, vol' + ((r.features || []).includes('carry') ? ', carry' : '')
        + '; en az bir hafta arayla): ' + sm.hits + '\'inde ' + fmt(sm.hold, 0) + ' iş günü sonra işlemin yönünde kâr (' + pct(sm.share) + '); ortalama ' + sgn(sm.mean, 2) + ' '
        + unit + inMoney('mean') + ', medyan ' + sgn(sm.median, 2) + inMoney('median') + ', çeyrekler ' + sgn(sm.q25, 2) + ' / ' + sgn(sm.q75, 2)
        + (sm.carry_in ? ' (forward pozisyonunun getirisi: kur hareketi + forward primi)' : ' (fiyat hareketi; carry ayrıca)') + '.'));
      const t = h('table', { class: 'plain qanalogs' }, h('tr', null, ...['Gün', 'z', 'Eğim', 'Rejim (ρ)', 'Vol', (r.features || []).includes('carry') ? 'Carry' : null, 'Uzaklık',
        'Sonra (' + unit + ')', mm ? 'Sonra (' + mm.ccy + per + ')' : null].filter((x) => x !== null).map((x) => h('th', null, x))));
      for (const a of r.analogs || []) {
        const f = a.features || [];
        const cells = [isoToTr(a.day), sgn(f[0], 2), sgn(f[1], 2), sgn(f[2], 2), sgn(f[3], 2)];
        if ((r.features || []).includes('carry')) cells.push(sgn(f[4], 1));
        cells.push(fmt(a.distance, 2), sgn(a.outcome, 2));
        if (mm) cells.push(money(a.money, ''));
        t.appendChild(h('tr', { class: isNum(a.outcome) && a.outcome > 0 ? 'ok' : 'fail' }, ...cells.map((c, i) => h('td', { class: i ? 'n' : '' }, c))));
      }
      box.appendChild(t);
    } else if (r.why) {
      box.appendChild(h('div', { class: 'muted qline' }, r.why));
    }
    if ((r.invalidation || []).length) {
      box.appendChild(h('div', { class: 'ct' }, 'Geçersiz kılanlar'));
      const ul = h('ul', { class: 'qinvalid' });
      for (const x of r.invalidation) ul.appendChild(h('li', null, x));
      box.appendChild(ul);
    }
    this.details.appendChild(box);
  }
}

// ------------------------------------------------------------------------------------------------ "İşleme al"
// Every AL / SAT line Trades can book - TRY OIS outright / 1:1 spread / 50/50 fly / FRA / PPK period, a DİBS bond, an FX
// spot - opens the Trades form filled from it (tto/tradequant.py; the server says which: ``s.book``); the others say why not.
const BOOK_TIP = 'Trades formunu bu satırla doldur: ürün, bacaklar, yön, DV01\'den nominal, giriş (şimdiki seviye), hedef ve stop - kaydedene kadar hiçbir şey kaydolmaz';

/** The list's cell: the button, or a dash with the reason in its tooltip. */
export function bookCell(s) {
  const b = s.book || {};
  if (b.ok) return { t: '', k: '', cls: 'act', act: { id: 'book', label: 'İşleme al', title: BOOK_TIP, fn: () => bookLine(s) } };
  return T('—', { cls: 'soft', tip: 'Trades\'e alınamaz: ' + (b.why || 'bilinmiyor') });
}

/** The card's button (disabled, with the reason, for a line Trades cannot book). */
export function bookButton(s, id) {
  const b = s.book || {};
  const el = h('button', { class: 'btn sm', type: 'button', id: id || null, disabled: !b.ok, title: b.ok ? BOOK_TIP : 'Trades\'e alınamaz: ' + (b.why || 'bilinmiyor') },
    'İşleme al');
  if (b.ok) el.addEventListener('click', () => bookLine(s));
  return el;
}

/** The rows of a signal table (the ranked list, and each analysis page's own signals). */
/** The gates of a signal in one line: ✓ passed, ✗ failed (the tooltip says why). */
/** A signal's family backtest in a cell: trades · hit rate · average P&L in σ. */
export function btShort(bt) {
  if (!bt || !bt.trades) return '';
  return bt.trades + ' · ' + pct(bt.hit) + ' · ' + sgn(bt.avg_sigma, 1) + 'σ';
}

export function gateText(s) {
  return (s.gates || []).map((g) => (g.ok ? '✓' : '✗') + ' ' + g.name).join(' · ');
}

/** Which way a trade's words go, for its colour - AL green, SAT red, as Günlük İşlemler's RECEIVE / PAY (Düzen,
 * 27.11.2026): the first word of the trade (AL / Buy / receive / vol al … - after a Trend line's "YENİ · " and an option
 * line's "… → "); "" for a trade both ways at once (a steepener, a switch "AL A / SAT B") or no trade. */
export function sideClass(text) {
  let t = String(text || '');
  const arrow = t.lastIndexOf('→');
  if (arrow >= 0) t = t.slice(arrow + 1);
  t = t.replace(/^\s*YENİ\s*·\s*/, '').trim().split(' · ')[0];
  const buy = /^(AL|Buy|Receive|receive|vol al|RR al|BF al)(\s|$|\()/, sell = /^(SAT|Sell|Pay|pay|vol sat|RR sat|BF sat)(\s|$|\()/;
  const side = buy.test(t) ? 'buy' : sell.test(t) ? 'sell' : '';
  if (side && / \/ (AL|SAT|Buy|Sell|Receive|Pay|receive|pay) /.test(t)) return '';      // (both ways: a switch's pair)
  return side;
}

/** A line's side for its colour: an FX line's by its direction (its trade is the instrument's price), else its words. */
export function tradeSide(s) {
  if (s.px && isNum(s.direction) && s.direction !== 0) return s.direction > 0 ? 'buy' : 'sell';
  return sideClass(s.line || s.expression || '');
}

/** The rows of a signal list. Every list starts with the trade (Düzen, 27.11.2026): İşlem (AL green / SAT red) · Giriş ·
 * Hedef · Stop · Beklenen K/Z · Ödül / risk · İsabet (n) - then the unit, "İşleme al", the score, the holding, the carry,
 * the record, the model; the secondary statistics last (hidden until "Sütunlar" shows them: SIGNALS_TABLE).
 * ``opts.rank`` a first column with the line's number, ``opts.group`` one with its group after the model (Sinyaller's
 * list and its box); a signal a gate holds says "düşük güven" for its strength and its reason in "Bileşik / neden". */
export function signalRows(list, opts = {}) {
  return list.map((s, i) => {
    const row = [];
    const pu = s.pnl_unit || '';
    const px = s.px || null;
    const q = px ? null : (s.quote || null);
    const mo = s.money || {};
    // an FX trade's entry / target / stop in the instrument's own price (the forward of the holding), the series' in its tooltip
    const at = px ? { tip: px.inst + ' · giriş: ' + px.note + (px.tenor ? ' · spot ' + fmt(px.spot, px.digits) : '') + ' · analiz serisi ' + fmt(s.entry, s.digits) + ' ' + (s.unit || '') }
      : {};
    // a level of the model's own in the traded instrument's (the FRA's rate …), the model's gap in its tooltip
    const lvCell = (k) => {
      const trail = k === 'target' && s.trail ? { empty: 'iz süren stop' } : {};
      if (px) return N(px[k], px.digits, Object.assign(k === 'entry' ? at : {}, trail));
      if (q) return N(q[k], q.digits, Object.assign({ tip: q.inst + ': ' + gapText(q, s[k]) + (k === 'entry' && q.note ? ' · ' + q.note : '') }, trail));
      return N(s[k], s.digits, Object.assign({ tip: sheetText(s, s[k]).trim() || undefined }, trail));
    };
    const rr = isNum(s.rr) ? s.rr : (px && isNum(mo.target) && isNum(mo.stop) && mo.stop < 0 ? mo.target / -mo.stop : null);
    const side = tradeSide(s);
    if (opts.rank) row.push({ t: String(i + 1), v: i + 1, k: 'n' });
    // (a systematic family's line - Trend's - in the plan's one-line format: "SAT USDTRY 1A forward · 1 mn USD · giriş … · model: Trend")
    row.push(T(s.line || s.expression, Object.assign({ b: 1, tip: (s.plain ? s.plain + '\n' : '') + (s.thesis ? s.thesis + '\n' : '')
      + (s.legs || []).map((l) => l.text).join('\n') + (s.note ? '\n' + s.note : '') }, side ? { cls: side } : {})),
      lvCell('entry'), lvCell('target'), lvCell('stop'),
      pnlCell(s),
      ...levelCells(s, rr),
      T(px ? px.label : q ? q.label : s.unit, px ? { tip: px.inst + ' (' + px.unit + ')' } : q ? { tip: q.inst + ' · ' + gapsText(q) } : {}),
      bookCell(s),
      Z(s.z, s.entry_z, { tip: (s.score_name || 'z') + ' · giriş eşiği ' + fmt(s.entry_z, 2) }),
      T(s.gated ? LOW : s.strength, Object.assign({ cls: 'qs-' + (s.gated ? 'elendi' : (s.strength || '').toLowerCase()) }, s.gated ? { tip: s.gated } : {})),
      T(isNum(s.hold) ? fmt(s.hold, 0) + (s.horizon_unit && s.horizon_unit !== 'gün' ? ' ' + s.horizon_unit : '') : ''),
      N(s.carry_week, 2, { sign: true, tip: s.fx ? 'Forward primi, işlemin yönünde, haftalık (%)' : 'Carry + roll, işlemin yönünde, haftalık (' + (pu || 'bp') + ')' }),
      N(s.carry_yr, 1, { sign: true, tip: 'FX: forward primi, işlemin yönünde, yıllık % (forward\'ların ima ettiği)' }),
      T(btShort(s.bt), { tip: s.bt ? s.bt.text + (isNum(s.bt.sharpe) ? ' · Sharpe ' + fmt(s.bt.sharpe, 2) : '')
        + (isNum(s.bt.max_dd) ? ' · en büyük düşüş ' + fmt(s.bt.max_dd, 1) + 'σ' : '') : 'geri test henüz yok' }),
      // (a line's model: its family, or a family's own name of it - "Carry + momentum · G10 spot sepeti")
      T(((s.info || {}).model || s.family_label) + (s.intraday ? ' · gün içi' : '')));
    if (opts.group) row.push(T(groupText(s), Object.assign({ tip: s.tag ? s.tag + ': masanın offshore işlem limiti dar' : (s.group || '') },
      s.tag ? { cls: 'qtag' } : {})));
    row.push(T(s.asset), N(s.half_life, 1), T(s.regime || '—'),
      T(s.agree + (s.conflict ? ' / −' + s.conflict : ''), { tip: (s.agree_with || []).join(', ') + (s.conflict ? '\nters: ' + s.conflict_with.join(', ') : '') }),
      T(gateText(s), { cls: 'qgate', tip: (s.gates || []).map((g) => (g.ok ? '✓ ' : '✗ ') + g.name + ': ' + (g.text || '')).join('\n') }));
    if (opts.gated || s.gated) row.push(T(s.gated, { cls: 'soft' }));
    else row.push(N(s.composite, 2, { b: 1, tip: '|z| ' + fmt(s.parts.z, 2) + ' × rejim ' + fmt(s.parts.regime, 2) + ' × yarı ömür ' + fmt(s.parts.hl, 2) + ' × carry ' + fmt(s.parts.carry, 2) }));
    row.push(T((s.live ? '● ' : '') + (s.time || ''), { tip: s.live ? 'canlı değerle' : 'son kapanışla' }));
    return row;
  });
}

// <SIGNAL_HEAD>
export const SIGNAL_HEAD = ["İşlem", "Giriş", "Hedef", "Stop", "Beklenen K/Z", "Ödül / risk", "İsabet", "Birim", "Trades", "z", "Güç", "Tutma",
  "Carry / hf", "Carry % / yıl", "Geri test", "Aile", "Varlık", "Yarı ömür (g)", "Rejim", "Uyum", "Kapılar"];
// </SIGNAL_HEAD>

/** A signal list's captions as ``signalRows`` gives its rows (``opts.rank`` "#" first, ``opts.group`` "Grup" after "Aile"),
 * the composite / reason and the time last. */
export function signalHead(opts = {}) {
  const head = SIGNAL_HEAD.slice();
  if (opts.group) head.splice(head.indexOf('Aile') + 1, 0, 'Grup');
  return (opts.rank ? ['#'] : []).concat(head, ['Bileşik / neden', 'Saat']);
}

/** Where the quant worker is (tto/progress.py: the status' ``progress`` while the fit or the backtest runs), for a line:
 *  ": Quant 14/26 · ML 240/480 · ~3 dk – şu an Makine öğrenmesi"; "" when nothing runs. */
export function progressText(pv) {
  if (!pv || !pv.busy) return '';
  const fit = (pv.jobs || []).find((j) => j.id === 'quant');
  return ': ' + pv.text + (fit && fit.step ? ' – şu an ' + fit.step : '');
}

/** A status table of the quant worker: what every page shows at the bottom (and the first thing before a result). */
export function statusRows(st) {
  st = st || {};
  const t = st.timing || {};
  const rows = [[T('Son tam hesap'), T(st.fit_at || 'henüz yok')], [T('Tam hesabın süresi'), N(st.fit_ms, 0, { unit: 'ms' })],
    [T('Son canlı yenileme'), T(st.live_at || '—')], [T('Canlı yenilemenin süresi'), N(st.live_ms, 0, { unit: 'ms' })],
    [T('Motor iş parçacığında geçen (son okuma)'), N(st.engine_ms, 1, { unit: 'ms', tip: 'Çalışma kitabından kısa okuma; hesapların kendisi ayrı iş parçacığında' })],
    [T('İzlenen enstrüman'), N(st.monitors, 0)], [T('Geçmişi dolan seri'), N(st.filling || 0, 0, { tip: 'İlk iki yıllık geçmişi henüz gelmemiş seriler (canlıda her tarihçe turunda birkaç seri)' })],
    [T('Durum'), T(st.phase === 'fit' ? 'hesaplanıyor' + (progressText(st.progress) || '…') : (st.error ? 'hata: ' + st.error : 'hazır'))]];
  for (const [k, v] of Object.entries(t)) rows.push([T('  · ' + k), N(v, 0, { unit: 'ms' })]);
  for (const [k, v] of Object.entries(st.errors || {})) rows.push([T('  ! ' + k), T(v, { cls: 'soft' })]);
  return rows;
}

/** A page's data coverage in a line (its series; Sinyaller: all of them): "Veri kapsamı: 12 seri · 2 kısa · son kapanış
 * 26.11.2026", the series that are short, filling or without history named in the tooltip with their days. */
export function coverageLine(cov, minObs) {
  const short = cov.filter((c) => c.state === 'var' && c.n < minObs);
  const filling = cov.filter((c) => c.state === 'geçmiş doluyor');
  const none = cov.filter((c) => c.state !== 'var' && c.state !== 'geçmiş doluyor');
  const last = cov.reduce((a, c) => (c.last && c.last > a ? c.last : a), '');
  const parts = [cov.length + ' seri'];
  if (short.length) parts.push(short.length + ' kısa');
  if (filling.length) parts.push(filling.length + ' doluyor');
  if (none.length) parts.push(none.length + ' geçmişsiz');
  const named = (lst, what) => (lst.length ? '\n' + what + ': ' + lst.slice(0, 12).map((c) => c.label + ' (' + c.n + ' gün)').join(', ')
    + (lst.length > 12 ? ' … +' + (lst.length - 12) : '') : '');
  return { text: 'Veri kapsamı: ' + parts.join(' · ') + (last ? ' · son kapanış ' + isoToTr(last) : ''),
    tip: 'Bu sayfanın analizlerinin okuduğu günlük kapanışlar (en az ' + minObs + ' gün)' + named(short, 'Kısa') + named(filling, 'Geçmişi doluyor')
      + named(none, 'Geçmişi yok') + '\nTıklayın: bütün serilerin tablosu (Sinyaller → Veri kapsamı).' };
}

// ------------------------------------------------------------------------------------------------ the shared page frame
export const live = { page: null, version: 0, alerts: null, busy: false };

/** What every quant page shares: load, a refresh when the server's result moved (or a minute passed), the status
 * table, the chart of a picked signal. */
export class QuantPage {
  constructor(host, ctx, what) {
    this.host = host;
    this.ctx = ctx;
    this.what = what;
    this.data = null;
    this.version = -1;
    this.loaded = 0;
    this.picked = null;
    this.boxes = {};
  }

  async load() {
    clear(this.host);
    this.host.appendChild(h('div', { class: 'loading' }, 'Yükleniyor…'));
    const d = await this.fetch();
    if (this.dead) return;
    this.data = d;
    this.version = d.version;
    this.loaded = Date.now();
    clear(this.host);
    this.build();
    this.fill();
    live.page = this;
    if (!d.ready) this.poll();
  }

  fetch() {
    return api.get('/api/quant/' + this.what, this.query ? this.query() : undefined);
  }

  async refresh(force) {
    if (this.busy || this.dead) return;
    if (!force && this.data && this.data.ready && live.version === this.version && Date.now() - this.loaded < 60000) return;
    this.busy = true;
    try {
      const d = await this.fetch();
      if (this.dead) return;
      this.data = d;
      this.version = d.version;
      this.loaded = Date.now();
      this.fill();
    } catch (err) {
      if (!err.network) console.warn('quant refresh failed', err);
    } finally { this.busy = false; }
  }

  /** No result yet (the first fit runs a few seconds after the start): ask again until there is one. */
  poll() {
    clearTimeout(this.timer);
    this.timer = setTimeout(async () => {
      if (this.dead) return;
      await this.refresh(true);
      if (!this.dead && !(this.data && this.data.ready)) this.poll();
    }, 3000);
  }

  destroy() {
    this.dead = true;
    clearTimeout(this.timer);
    if (live.page === this) live.page = null;
    if (this.chart) this.chart.destroy();
    for (const c of Object.values(this.charts || {})) if (c) c.destroy();
  }

  /** Tools row: the data coverage in a line, the status line and "Şimdi hesapla" (the coverage and status tables are
   * Sinyaller's, folded at its foot: Düzen, 27.11.2026). */
  tools(extra = []) {
    this.covLine = h('a', { class: 'muted qcov', id: 'quant-coverage-line', href: '#/quant?p=signals-coverage' });
    this.covLine.addEventListener('click', (e) => {
      const own = document.getElementById('signals-coverage');
      if (own && this.host.contains(own)) { e.preventDefault(); showPanel(own); }
    });
    this.statusLine = h('span', { class: 'muted', id: 'quant-status' });
    const again = h('button', { class: 'btn', type: 'button', id: 'quant-recompute', title: 'Bütün analizleri şimdi yeniden hesapla (ayrı iş parçacığında)' }, 'Şimdi hesapla');
    again.addEventListener('click', async () => {
      again.disabled = true;
      try {
        await api.post('/api/quant/recompute', {});
        toast('Hesap başladı: sonuç birkaç saniyede gelir', 'ok', 2500);
        this.poll();
      } catch (e) { errorToast(e); } finally { again.disabled = false; }
    });
    this.banner = h('div', { class: 'banner hidden', id: 'quant-banner' });
    this.host.appendChild(h('div', { class: 'page-tools' }, ...extra, h('span', { class: 'grow' }), this.covLine, this.statusLine, again));
    this.host.appendChild(this.banner);
  }

  /** The page's panels: a wrapping row (``.qpage``; ``.quantpage`` the quant look, shared with the card's box). */
  pageEl() {
    return h('div', { class: 'quantpage qpage' });
  }

  /** A long page: its panels in a jump bar above them (built once they are all on the page). */
  addJumps(page) {
    page.parentNode.insertBefore(jumpBar(page, 'quant-jump'), page);
  }

  /** ``#/quant…?p=<panel id>``: that panel opened and in view; ``sig:<id>`` a signal's card. */
  focusPanel(p) {
    if (!p) return;
    if (p.startsWith('sig:')) { this.pick(p.slice(4), true); return; }
    showPanel(this.host.querySelector('#' + CSS.escape(p)));
  }

  /** The page's own signal list (``this.boxes.sig``: the 19 lists share their columns, SIGNALS_TABLE) and, when nothing
   * is picked yet, its first line's card. ``soft``: a line a gate holds greyed (the families that keep every line,
   * Carry + momentum and DİBS switch, do not). */
  showSignals(empty, soft = true) {
    const list = (this.data && this.data.signals) || [];
    this.boxes.sig.set(signalHead(), list.map((s) => {
      const row = signalRows([s], { gated: !!s.gated })[0];
      if (soft && s.gated) for (const c of row) if (c && typeof c === 'object') c.cls = ((c.cls || '') + ' soft').trim();
      return row;
    }), list.map((s) => s.id), empty, this.picked);
    this.firstPick(list);
  }

  /** The first line's card, opened when the page shows (on every page: Düzen, 27.11.2026); with no line the card is its
   * title and why. ``list``: lines (``id``) or rows (``sid``). */
  firstPick(list, why) {
    if (!this.chart || this.picked) return;
    const first = (list || []).find((s) => s && (s.id || s.sid));
    if (first) { this.pick(first.id || first.sid); return; }
    this.chart.idle(why || 'Bu sayfada şu an sinyal yok: tablolardan bir satıra tıklayınca serisi ve seviyeleri burada çizilir.');
  }

  /** The card in view after a click on a row (the tables below it - Eğri's DİBS, PCA's - would update it off screen),
   * opened if folded; left where it is when its top is already in the upper part of the screen. */
  revealCard() {
    const card = this.chart && this.chart.host.closest ? this.chart.host.closest('.panel') : null;
    if (!card) return;
    if (card.__open) card.__open();
    const r = card.getBoundingClientRect();
    const vh = window.innerHeight || document.documentElement.clientHeight || 800;
    if (r.top >= 0 && r.top < vh * 0.6) return;
    card.scrollIntoView({ block: 'start', behavior: 'smooth' });
  }

  fillStatus() {
    const d = this.data || {};
    const st = d.status || {};
    if (this.statusLine) {
      this.statusLine.textContent = d.ready ? 'Hesap ' + (st.fit_at || '') + ' (' + fmt(st.fit_ms / 1000, 1) + ' sn)' + (st.live_at ? ' · canlı ' + st.live_at.slice(11, 16) : '')
        : 'İlk hesap yapılıyor…';
    }
    if (this.banner) {
      const errs = Object.entries(d.errors || {});
      const filling = st.filling || 0;
      this.banner.classList.toggle('hidden', !!d.ready && !errs.length && !filling);
      // (before the first result: where the fit is - its steps, the ML models, the time left - as the top bar's "Hesap")
      this.banner.textContent = !d.ready ? 'Analizler hesaplanıyor (ayrı iş parçacığında)' + progressText(st.progress) + '; sonuç gelince sayfa kendiliğinden dolar.'
        : [filling ? 'Geçmiş doluyor: ' + filling + ' seri henüz iki yıl geriye inmedi (canlıda her tarihçe turunda birkaç seri; '
          + 'Bloomberg\'in günlük veri limiti için). Analizler eldekiyle çalışır.' : ''].concat(errs.map(([k, v]) => k + ': ' + v)).filter(Boolean).join(' · ');
    }
    if (this.boxes.status) this.boxes.status.set(['Hesap', 'Değer'], statusRows(st), null, 'Durum yok');
    const cov = d.coverage || [];
    if (this.covLine) {
      const line = coverageLine(cov, (d.settings || {}).min_obs || 120);
      this.covLine.textContent = line.text;
      this.covLine.title = line.tip;
      this.covLine.classList.toggle('hidden', !cov.length);
    }
    if (this.boxes.coverage) {
      this.boxes.coverage.set(['Seri', 'Grup', 'Ticker', 'Gün', 'İlk', 'Son', 'Durum', 'Canlı'], cov.map((c) => [T(c.label, { b: 1 }), T(c.group), T(c.ticker),
        N(c.n, 0, { cls: c.n < ((d.settings || {}).min_obs || 120) ? 'soft' : '' }), T(isoToTr(c.first)), T(isoToTr(c.last)),
        T(c.state || '', { cls: c.state === 'var' ? '' : 'soft' }), T(c.live ? '●' : '')]), null, 'Kapsam bilgisi henüz yok');
    }
  }

  /** The status and the data coverage, once, at the foot of Sinyaller and folded (Düzen, 27.11.2026: on the other pages
   * the coverage line and the status line above them say it in a line, the line a link to these). */
  addStatus(parent) {
    const cov = panel(this.what + '-coverage', 'Veri kapsamı (günlük kapanışlar)', { cls: 'aux', folded: true });
    cov.note.textContent = 'Gün: analizlerin okuduğu kapanış sayısı (bugün hariç; bugün canlı değerdir). En az gözlemin altındakiler soluk. Yeni ticker\'lar canlı '
      + 'dashboard\'un tarihçe güncellemesiyle iki yıl geriye doldurulur (Ayarlar → tarihçe kapsamı). Bütün sayfaların serileri burada; her sayfa '
      + 'kendi serilerini üstteki "Veri kapsamı" satırında özetler.';
    this.boxes.coverage = new GridBox(cov, 'quant/' + this.what + '/coverage', null, { freeze: 1 });
    const st = panel(this.what + '-status', 'Hesap durumu', { cls: 'aux', folded: true });
    st.note.textContent = 'Analizler motor iş parçacığında değil, kendi iş parçacığında çalışır: yeni kapanışta tam hesap, dakikada en çok bir kez son noktanın canlı değerle yenilenmesi.';
    this.boxes.status = new GridBox(st, 'quant/' + this.what + '/status');
    parent.appendChild(cov.el);
    parent.appendChild(st.el);
  }

  /** Draw one monitor (a click on a signal or on a row that has one: ``click``, the card brought into view). */
  async pick(sid, click) {
    if (!sid || !this.chart) return;
    this.picked = sid;
    this.chart.loading('');
    if (click) this.revealCard();
    try {
      const d = await api.get('/api/quant/signal', { id: sid });
      if (this.dead || this.picked !== sid) return;
      this.chart.show(d);
      if (this.afterPick) this.afterPick();
    } catch (e) { errorToast(e); }
  }
}

