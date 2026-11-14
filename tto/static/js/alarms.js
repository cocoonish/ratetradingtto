// Watching anything and alarms on it: the "Ekle…" window (a VİOP contract, a bond, an OIS tenor, offshore, the
// desk strip, a free expression of them, any cell), and telling the user an alarm fired - on whatever page is
// open: a toast that stays a while, a short tone, and the browser's own notification when it is allowed.
import { api } from './api.js';
import { h, clear, modal, toast, errorToast } from './ui.js';

export const OPS = [['>=', '≥', 'Seviyeye ulaşınca ya da üstüne çıkınca'], ['<=', '≤', 'Seviyeye inince ya da altına düşünce'],
  ['x', 'kesişir', 'Seviyeyi hangi yönde olursa olsun geçince']];

const KINDS = [['viop', 'VİOP'], ['bond', 'Kâğıt'], ['ois', 'OIS'], ['off', 'Offshore'], ['masa', 'Masa'], ['expr', 'İfade'], ['cell', 'Hücre']];
const EXAMPLES = ['[OIS 2Y] - [OIS 1Y]', '2*[OIS 5Y] - [OIS 2Y] - [OIS 10Y]', '[VİOP 1. kontrat OIS − VİOP] - [VİOP 2. kontrat OIS − VİOP]',
  '[15.03.28 ASW] - [13.09.28 ASW]', '[15.03.28 getiri] - [OIS 2Y]', "'DİBS RV'!Z8 - 'DİBS RV'!Z9"];
const SIDES = [['bid', 'bid'], ['mid', 'orta'], ['ask', 'ask']];

let catalogCache = null;
async function catalog() {
  if (!catalogCache || Date.now() - catalogCache.at > 60000) catalogCache = { at: Date.now(), data: await api.get('/api/watch/catalog') };
  return catalogCache.data;
}

function select(id, options, value) {
  const s = h('select', { class: 'inp', id });
  for (const o of options) {
    if (o.group) {
      const g = h('optgroup', { label: o.group });
      for (const x of o.items) g.appendChild(h('option', { value: x.value, disabled: x.disabled || null }, x.text));
      s.appendChild(g);
    } else s.appendChild(h('option', { value: o.value, disabled: o.disabled || null }, o.text));
  }
  if (value !== undefined && value !== null) s.value = String(value);
  return s;
}

/** The level as typed (35,80 · 250 · -12,5) - the server reads it the same way. */
function levelOf(text) { return String(text || '').trim(); }

/**
 * Watch something, or set an alarm on it.  ``subject`` given (right click on a cell, the bell of a watched item):
 * that subject; none: the user picks what (VİOP · Kâğıt · OIS · Offshore · Masa · İfade · Hücre).
 */
export async function openWatchDialog(ctx, { subject = null, label = '', hint = '', focus = 'watch', kind = null } = {}) {
  let cat;
  try { cat = await catalog(); } catch (err) { errorToast(err); return; }
  const fixed = !!subject;
  const m = modal({ title: focus === 'alarm' ? 'Alarm kur' : 'İzle · alarm kur', width: 640 });
  m.box.classList.add('pick');
  const state = { kind: kind || (fixed ? subject.kind : 'viop'), preview: null, typedLevel: false, exprText: '' };

  // ---------------------------------------------------------------- what
  const seg = h('div', { class: 'seg kinds', id: 'pick-kind' });
  for (const [k, t] of KINDS) {
    const b = h('button', { type: 'button' }, t);
    b.dataset.k = k;
    b.addEventListener('click', () => { state.kind = k; draw(); });
    seg.appendChild(b);
  }
  const form = h('div', { class: 'pick-form', id: 'pick-form' });
  const now = h('div', { class: 'pick-now', id: 'pick-now' });
  const name = h('input', { class: 'inp', id: 'pick-label', maxlength: '60', value: fixed ? label || '' : '' });
  if (!fixed) {
    m.body.appendChild(seg);
    m.body.appendChild(form);
  }
  m.body.appendChild(now);
  m.body.appendChild(h('div', { class: 'field' }, h('label', null, 'Ad (boşsa önerilen ad)'), name));

  // the controls of each kind
  const viopOpts = [{ group: 'Kontrat', items: cat.viop.map((c) => ({ value: 't:' + c.ticker, text: c.short + (c.due ? ' · ' + c.due : '') })) },
    { group: 'Sırayla (kontrat dönünce kayar)', items: [1, 2, 3, 4].map((p) => ({ value: 'p:' + p, text: p + '. kontrat' })) }];
  const viop = select('pick-viop', viopOpts, cat.viop.length ? 't:' + cat.viop[0].ticker : 'p:1');
  const viopMetric = select('pick-viop-metric', cat.viop_metrics.map((x) => ({ value: x.id, text: x.label + (x.show === 'bp' ? ' (bp)' : (x.show === 'pct' ? ' (%)' : '')) })), 'ois');
  const listed = cat.bonds.filter((b) => b.listed), others = cat.bonds.filter((b) => !b.listed);
  const bond = select('pick-bond', [{ group: 'Trading listesi (★)', items: listed.map((b) => ({ value: b.isin, text: b.label + ' · ' + b.isin })) },
    { group: 'Diğer kâğıtlar', items: others.map((b) => ({ value: b.isin, text: b.label + ' · ' + b.isin })) }], (listed[0] || others[0] || {}).isin);
  const bondMetric = h('select', { class: 'inp', id: 'pick-bond-metric' });
  const fillBondMetrics = () => {
    const isListed = listed.some((b) => b.isin === bond.value);
    const keep = bondMetric.value || 'asw';
    clear(bondMetric);
    for (const x of cat.bond_metrics) {
      const off = x.listed_only && !isListed;
      bondMetric.appendChild(h('option', { value: x.id, disabled: off || null }, x.label + (x.show === 'bp' ? ' (bp)' : (x.show === 'pct' ? ' (%)' : '')) + (off ? ' – ★ listede değil' : '')));
    }
    const ok = cat.bond_metrics.find((x) => x.id === keep && !(x.listed_only && !isListed));
    bondMetric.value = ok ? keep : (isListed ? 'asw' : 'bid');
  };
  fillBondMetrics();
  bond.addEventListener('change', fillBondMetrics);
  const ois = select('pick-ois', cat.ois.map((t) => ({ value: t, text: t === 'TLREF' ? 'TLREF (O/N)' : 'OIS ' + t })), '1Y');
  const off = select('pick-off', cat.off.map((t) => ({ value: t, text: t })), '1M');
  const offSide = select('pick-off-side', SIDES.map(([v, t]) => ({ value: v, text: t })), 'mid');
  const masa = select('pick-masa', cat.masa.map((x) => ({ value: x.key, text: x.label })), cat.masa[0] && cat.masa[0].key);
  const expr = h('input', { class: 'inp mono', id: 'pick-expr', placeholder: '[OIS 2Y] - [OIS 1Y]', spellcheck: 'false' });
  const ref = h('input', { class: 'inp mono', id: 'pick-ref', placeholder: "örn. Forward!F2 ya da 'DİBS RV'!Z8", spellcheck: 'false' });

  const row = (...fields) => h('div', { class: 'pick-row' }, ...fields);
  const field = (t, el) => h('div', { class: 'field' }, h('label', null, t), el);
  const forms = {
    viop: () => [row(field('Kontrat', viop), field('Ölçü', viopMetric)),
      h('p', { class: 'muted' }, 'OIS − VİOP: kontratın vadesindeki OIS ile VİOP ima TRY faizinin (bid/ask ortası) farkı, bp. '
        + '"1. kontrat" vade dolunca bir sonrakine geçer; kontratın kendisi seçilirse o kontrat izlenir.')],
    bond: () => [row(field('Kâğıt', bond), field('Ölçü', bondMetric)),
      h('p', { class: 'muted' }, 'ASW, getiri, pahalı/ucuz, Z-spread, carry DİBS RV\'den gelir: kâğıt trading listesinde (★) olmalı. '
        + 'Kâğıt listede yer değiştirse de ISIN\'iyle izlenir.')],
    ois: () => [row(field('Vade', ois))],
    off: () => [row(field('Vade', off), field('Taraf', offSide)),
      h('p', { class: 'muted' }, 'Forward sayfasındaki FX swap ima TRY faizi (offshore).')],
    masa: () => [row(field('Masa özeti', masa))],
    expr: () => [field('İfade', expr),
      h('p', { class: 'muted' }, 'Köşeli parantezde adlar ([OIS 2Y], [VİOP A1Z6 OIS − VİOP], [15.03.28 ASW], [Offshore 3M], [TLREF]…), '
        + 'hücre adresleri, sayılar, + − * / ve parantez. Faizlerin farkı (spread, fly) bp olarak gösterilir. '
        + 'Diğer sekmelerde seçip "İfadeye ekle" de denebilir.'),
      h('div', { class: 'pick-examples' }, 'Örnek: ', ...EXAMPLES.map((x) => {
        const a = h('button', { type: 'button', class: 'linkbtn' }, x);
        a.addEventListener('click', () => { expr.value = x; changed(); });
        return a;
      }))],
    cell: () => [field('Hücre (sayfa!adres)', ref),
      h('p', { class: 'muted' }, 'Bir tablodaki hücreye sağ tıklamak daha kolay. DİBS RV, VİOP, OIS ve Forward\'daki hücreler gösterdikleri şey olarak izlenir '
        + '(kâğıt, kontrat, vade); diğerleri hücre olarak.')],
  };

  const current = () => {
    if (fixed) return subject;
    switch (state.kind) {
      case 'viop': return viop.value.startsWith('t:') ? { kind: 'viop', ticker: viop.value.slice(2), metric: viopMetric.value }
        : { kind: 'viop', position: Number(viop.value.slice(2)), metric: viopMetric.value };
      case 'bond': return { kind: 'bond', isin: bond.value, metric: bondMetric.value };
      case 'ois': return { kind: 'ois', tenor: ois.value };
      case 'off': return { kind: 'off', tenor: off.value, side: offSide.value };
      case 'masa': return { kind: 'masa', key: masa.value };
      case 'expr': return expr.value.trim() ? { kind: 'expr', text: expr.value.trim() } : null;
      default: return ref.value.trim() ? { kind: 'cell', book: 'tto', ref: ref.value.trim() } : null;
    }
  };

  // ---------------------------------------------------------------- the alarm
  let op = '>=';
  const opSeg = h('div', { class: 'seg', id: 'alarm-op' });
  for (const [v, t, tip] of OPS) {
    const b = h('button', { type: 'button', title: tip }, t);
    b.dataset.v = v;
    b.classList.toggle('on', v === op);
    b.addEventListener('click', () => { op = v; for (const x of opSeg.children) x.classList.toggle('on', x === b); });
    opSeg.appendChild(b);
  }
  const level = h('input', { class: 'inp num', id: 'alarm-level', inputmode: 'decimal', placeholder: 'seviye' });
  level.addEventListener('input', () => { state.typedLevel = true; });
  const unit = h('span', { class: 'unit muted', id: 'alarm-unit' });
  const note = h('input', { class: 'inp', id: 'alarm-note', placeholder: 'not (isteğe bağlı): örn. "spread 250 üstünde öde"', maxlength: '200' });
  const both = h('input', { type: 'checkbox', id: 'alarm-watch-too', checked: !fixed || null });
  const alarmBox = h('div', { class: 'pick-alarm' },
    h('div', { class: 'pick-row' }, field('Alarm koşulu', opSeg), field('Seviye', h('div', { class: 'lvl' }, level, unit))),
    field('Not', note),
    h('label', { class: 'check' }, both, ' Alarmı kurarken izleme listesine de ekle'),
    h('p', { class: 'muted' }, 'Seviye gösterildiği gibi yazılır: faizde 35,50 (= %35,50), spread\'de bp (250), fiyatta fiyat. Alarm bir kez çalar; Alarmlar listesinden yeniden kurulur.'));
  m.body.appendChild(alarmBox);

  // ---------------------------------------------------------------- preview
  let seq = 0;
  async function changed() {
    const s = current();
    const mine = ++seq;
    clear(now);
    if (!s) { now.appendChild(h('span', { class: 'muted' }, state.kind === 'expr' ? 'Bir ifade yazın.' : 'Bir hücre adresi yazın.')); state.preview = null; return; }
    let p;
    try { p = await api.post('/api/watch/preview', { subject: s }); } catch (err) {
      if (mine !== seq) return;
      state.preview = null;
      now.appendChild(h('span', { class: 'errtxt' }, err.message || String(err)));
      return;
    }
    if (mine !== seq) return;
    state.preview = p;
    name.placeholder = p.subject.kind === 'cell' && hint ? hint : p.label;
    now.appendChild(h('span', { class: 'muted' }, 'Şimdi: '));
    now.appendChild(h('b', { class: 'v' }, p.text || '–'));
    now.appendChild(h('span', { class: 'muted' }, ' · ' + p.label + (p.detail ? ' · ' + p.detail : '')));
    unit.textContent = p.unit || '';
    if (!state.typedLevel && typeof p.value === 'number') {
      const d = p.show === 'bp' ? 1 : (p.show === 'pct' ? 2 : (p.show === 'px' ? 3 : 4));
      level.value = p.value.toFixed(d).replace('.', ',');
    }
    if (fixed) m.box.querySelector('header h2').textContent = (focus === 'alarm' ? 'Alarm kur · ' : 'İzle · ') + p.label;
  }
  for (const el of [viop, viopMetric, bond, bondMetric, ois, off, offSide, masa]) el.addEventListener('change', () => { state.typedLevel = false; changed(); });
  let tmr = null;
  for (const el of [expr, ref]) el.addEventListener('input', () => { clearTimeout(tmr); tmr = setTimeout(() => { state.typedLevel = false; changed(); }, 300); });

  function draw() {
    for (const b of seg.children) b.classList.toggle('on', b.dataset.k === state.kind);
    clear(form);
    for (const el of forms[state.kind]()) form.appendChild(el);
    toExpr.classList.toggle('hidden', state.kind === 'expr' || state.kind === 'cell');
    state.typedLevel = false;
    changed();
    const first = form.querySelector('input, select');
    if (first && (state.kind === 'expr' || state.kind === 'cell')) first.focus();
  }

  // ---------------------------------------------------------------- what to do
  const toExpr = h('button', { class: 'btn', type: 'button', id: 'pick-toexpr', title: 'Seçili olanı ifadeye ad olarak ekle' }, 'İfadeye ekle');
  toExpr.addEventListener('click', () => {
    if (!state.preview) return;
    const piece = '[' + (state.preview.name || state.preview.label) + ']';
    const cur = expr.value.trim();
    expr.value = cur ? cur + (/[-+*/(]$/.test(cur) ? ' ' : ' - ') + piece : piece;
    state.kind = 'expr';
    draw();
  });
  const watchBtn = h('button', { class: 'btn' + (focus === 'alarm' ? '' : ' primary'), type: 'button', id: 'pick-watch' }, 'İzlemeye ekle');
  watchBtn.addEventListener('click', async () => {
    const s = current();
    if (!s) return;
    watchBtn.disabled = true;
    try {
      const res = await api.post('/api/watch/add', { subject: s, label: name.value.trim(), hint });
      toast(res.added ? 'İzleme listesine eklendi: ' + ((res.item && res.item.label) || name.value || '') : 'Zaten izleme listesinde', 'ok');
      m.close();
      if (ctx && ctx.refreshNow) ctx.refreshNow();
    } catch (err) { errorToast(err); watchBtn.disabled = false; }
  });
  const alarmBtn = h('button', { class: 'btn' + (focus === 'alarm' ? ' primary' : ''), type: 'button', id: 'alarm-save' }, 'Alarm kur');
  alarmBtn.addEventListener('click', async () => {
    const s = current();
    if (!s) return;
    if (!levelOf(level.value)) { level.focus(); toast('Alarm için bir seviye yazın', 'warn'); return; }
    alarmBtn.disabled = true;
    try {
      const cellHint = state.preview && state.preview.subject.kind === 'cell' ? hint : '';
      const res = await api.post('/api/alarms/add', { subject: s, op, level: levelOf(level.value), label: name.value.trim() || cellHint, note: note.value });
      if (both.checked) await api.post('/api/watch/add', { subject: s, label: name.value.trim(), hint });
      askPermission();
      const what = (res.alarm && res.alarm.label) || name.value;
      toast(res.already ? 'Alarm kuruldu – koşul şu an zaten sağlanıyor: hemen çalar' : 'Alarm kuruldu: ' + what, res.already ? 'warn' : 'ok', 5000);
      m.close();
      if (ctx && ctx.refreshNow) ctx.refreshNow();
    } catch (err) { errorToast(err); alarmBtn.disabled = false; }
  });
  level.addEventListener('keydown', (e) => { if (e.key === 'Enter') alarmBtn.click(); });
  m.foot.appendChild(toExpr);
  m.foot.appendChild(h('span', { class: 'grow' }));
  m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Vazgeç'));
  m.foot.appendChild(watchBtn);
  m.foot.appendChild(alarmBtn);
  if (fixed) { toExpr.classList.add('hidden'); await changed(); } else draw();
  if (focus === 'alarm') { level.focus(); level.select(); }
}

/** "Alarm kur…" on a cell (right click) or on a watched item. */
export function openAlarmDialog(ctx, { book, ref, label, subject }) {
  return openWatchDialog(ctx, { subject: subject || { kind: 'cell', book: book || 'tto', ref }, hint: label, focus: 'alarm' });
}

/** "İzlemeye ekle" on a cell: a cell of a table that names a bond, a VİOP contract, an OIS or offshore tenor is
 * watched as that thing (named as the desk calls it). */
export async function addToWatch(ctx, { book, ref, label }) {
  try {
    const res = await api.post('/api/watch/add', { book, ref, hint: label });
    toast(res.added ? 'İzleme listesine eklendi: ' + ((res.item && res.item.label) || label || ref) : 'Zaten izleme listesinde', 'ok');
    if (ctx && ctx.refreshNow) ctx.refreshNow();
  } catch (err) { errorToast(err); }
}

/** The browser's notifications: asked for once, when the first alarm is set (a click is needed to ask). */
export function askPermission() {
  try {
    if (window.Notification && Notification.permission === 'default') Notification.requestPermission();
  } catch (e) { /* not available */ }
}

let audio = null;
function tone() {
  try {
    audio = audio || new (window.AudioContext || window.webkitAudioContext)();
    const t0 = audio.currentTime;
    for (const [at, f] of [[0, 880], [0.18, 1175]]) {
      const o = audio.createOscillator();
      const g = audio.createGain();
      o.frequency.value = f;
      g.gain.setValueAtTime(0.0001, t0 + at);
      g.gain.exponentialRampToValueAtTime(0.18, t0 + at + 0.02);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + at + 0.16);
      o.connect(g).connect(audio.destination);
      o.start(t0 + at);
      o.stop(t0 + at + 0.17);
    }
  } catch (e) { /* no sound */ }
}

const seen = { last: null };

/** What fired since the last look: told once each (the first look of a session only learns where it stands). */
export async function checkAlarms() {
  let res;
  try { res = await api.get('/api/alarms/fired?since=' + (seen.last == null ? 0 : seen.last)); } catch (e) { return []; }
  if (seen.last == null) { seen.last = res.last; return []; }
  const op = Object.fromEntries(OPS.map(([v, t]) => [v, t]));
  for (const e of res.fired) {
    const text = '🔔 ' + e.label + ': ' + (e.value_text || e.value) + '  (' + (op[e.op] || e.op) + ' ' + (e.level_text || e.level) + ') · ' + e.time
      + (e.note ? ' · ' + e.note : '');
    const el = toast(text, 'alarm', 15000);
    el.addEventListener('click', () => el.remove());
    try {
      if (window.Notification && Notification.permission === 'granted') new Notification('TTO alarm · ' + e.label, { body: text.slice(2) });
    } catch (x) { /* no notification */ }
  }
  if (res.fired.length) tone();
  seen.last = Math.max(seen.last, res.last || 0);
  return res.fired;
}
