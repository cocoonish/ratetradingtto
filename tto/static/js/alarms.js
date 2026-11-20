// Watching anything and alarms on it: the "Ekle…" window (a VİOP contract, a bond, an OIS tenor, offshore, the
// desk strip, a free expression of them, any cell), and telling the user an alarm fired - on whatever page is
// open: a toast that stays a while, a short tone, and the browser's own notification when it is allowed.
// The desk's alarms (set by an administrator, and the system's own: the data feed, TLREF, the database) ring for
// everyone: their toast has "Gördüm, ben bakıyorum", and the top bar counts the ones nobody answered.  Muting one is
// personal: it stays silent (and uncounted) for the one who muted it, and rings for everyone else.
import { api, session } from './api.js';
import { h, clear, modal, toast, errorToast, menu } from './ui.js';

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
export async function openWatchDialog(ctx, { subject = null, label = '', hint = '', focus = 'watch', kind = null, mode = 'level', desk = false } = {}) {
  let cat;
  try { cat = await catalog(); } catch (err) { errorToast(err); return; }
  const fixed = !!subject;
  const m = modal({ title: desk ? 'Masa alarmı kur (herkese)' : (focus === 'alarm' ? 'Alarm kur' : 'İzle · alarm kur'), width: 640 });
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

  // ---------------------------------------------------------------- the alarm: on a level, on a move, on a z-score
  const segOf = (id, items, value, onPick) => {
    const el = h('div', { class: 'seg', id });
    for (const [v, t, tip] of items) {
      const b = h('button', { type: 'button', title: tip || null }, t);
      b.dataset.v = v;
      b.classList.toggle('on', v === value);
      b.addEventListener('click', () => { for (const x of el.children) x.classList.toggle('on', x === b); onPick(v); });
      el.appendChild(b);
    }
    return el;
  };
  let amode = ['level', 'move', 'z'].includes(mode) ? mode : 'level';
  let op = '>=';
  let dir = 'any';
  let zdays = 60;
  let zop = '>=';
  const modeSeg = segOf('alarm-mode', [['level', 'Seviye', 'Seviyeye gelince'], ['move', 'Hareket', 'Belli bir hareket yapınca (açılıştan, şimdiden, referanstan ya da son dakikalarda)'],
    ['z', 'z-skoru', 'Kendi geçmişine göre alışılmadık bir yere gelince']], amode, (v) => { amode = v; drawAlarm(); });
  const opSeg = segOf('alarm-op', OPS, op, (v) => { op = v; });
  const level = h('input', { class: 'inp num', id: 'alarm-level', inputmode: 'decimal', placeholder: 'seviye' });
  level.addEventListener('input', () => { state.typedLevel = true; });
  const unit = h('span', { class: 'unit muted', id: 'alarm-unit' });
  const from = h('select', { class: 'inp', id: 'alarm-from' },
    h('option', { value: 'open' }, 'açılıştan (bugün görülen ilk değer)'), h('option', { value: 'set' }, 'şimdiki seviyeden'),
    h('option', { value: 'ref' }, 'izleme referansından (⟲)'), h('option', { value: 'window' }, 'son … dakika içinde'));
  const minutes = h('input', { class: 'inp num', id: 'alarm-minutes', inputmode: 'numeric', value: '10' });
  const minutesBox = h('div', { class: 'lvl' }, minutes, h('span', { class: 'unit muted' }, 'dk'));
  const dirSeg = segOf('alarm-dir', [['up', '↑ yukarı'], ['down', '↓ aşağı'], ['any', '± iki yön']], dir, (v) => { dir = v; });
  const size = h('input', { class: 'inp num', id: 'alarm-size', inputmode: 'decimal', value: '10' });
  const sizeUnit = h('span', { class: 'unit muted', id: 'alarm-size-unit' }, 'bp');
  const zdaysSeg = segOf('alarm-zdays', [['20', '20 gün'], ['60', '60 gün'], ['250', '250 gün']], '60', (v) => { zdays = Number(v); showZ(); });
  const zopSeg = segOf('alarm-zop', OPS, zop, (v) => { zop = v; });
  const zlevel = h('input', { class: 'inp num', id: 'alarm-z', inputmode: 'decimal', value: '2' });
  const zinfo = h('span', { class: 'muted', id: 'alarm-zinfo' });
  const note = h('input', { class: 'inp', id: 'alarm-note', placeholder: 'not (isteğe bağlı): örn. "spread 250 üstünde öde"', maxlength: '200' });
  const both = h('input', { type: 'checkbox', id: 'alarm-watch-too', checked: (!fixed && !desk) || null });
  // an administrator sets an alarm for the whole desk: read on the market's values, it rings on every screen
  const forDesk = h('input', { type: 'checkbox', id: 'alarm-desk', checked: desk || null });
  const modeBox = h('div', { class: 'pick-mode' });
  const help = h('p', { class: 'muted' });
  const alarmBox = h('div', { class: 'pick-alarm' }, field('Alarm', modeSeg), modeBox, field('Not', note),
    h('label', { class: 'check' }, both, ' Alarmı kurarken izleme listesine de ekle'),
    session.role === 'admin' ? h('label', { class: 'check', title: 'Piyasanın değerleriyle (kimsenin senaryosuyla değil) denetlenir; çalınca '
      + 'herkesin ekranında uyarı çıkar, biri "Gördüm" deyince herkes görür.' }, forDesk, ' Masa alarmı: herkese çalar') : null, help);
  m.body.appendChild(alarmBox);
  function showZ() {
    const z = state.preview && state.preview.z ? state.preview.z[String(zdays)] : null;
    zinfo.textContent = !z ? '' : (z.z_text ? 'şu an z = ' + z.z_text + ' · ' + z.n + ' kapanış' + (z.source ? ' (' + z.source + ')' : '')
      : 'geçmiş yetersiz: ' + (z.n || 0) + ' / ' + z.need + ' kapanış (izlenen kalemlerin kapanışı her gün kaydedilir)');
  }
  function drawAlarm() {
    clear(modeBox);
    if (amode === 'level') {
      modeBox.appendChild(h('div', { class: 'pick-row' }, field('Koşul', opSeg), field('Seviye', h('div', { class: 'lvl' }, level, unit))));
      help.textContent = 'Seviye gösterildiği gibi yazılır: faizde 35,50 (= %35,50), spread\'de bp (250), fiyatta fiyat. Alarm bir kez çalar; Alarmlar listesinden yeniden kurulur.';
    } else if (amode === 'move') {
      modeBox.appendChild(h('div', { class: 'pick-row' }, field('Nereden', from), from.value === 'window' ? field('Süre', minutesBox) : null));
      modeBox.appendChild(h('div', { class: 'pick-row' }, field('Yön', dirSeg), field('Hareket', h('div', { class: 'lvl' }, size, sizeUnit))));
      help.textContent = 'Hareket faiz ve spread\'lerde bp, fiyat ve kurda kendi biriminde yazılır. Açılış: dashboard\'un bugün gördüğü ilk değer; '
        + 'şimdiki seviye: alarm kurulduğu an (yeniden kurulunca o an); referans: izleme listesinde ⟲ ile alınan seviye; '
        + 'son N dakika: o süre içindeki en düşük ya da en yüksekten bu yana.';
    } else {
      modeBox.appendChild(h('div', { class: 'pick-row' }, field('Geçmiş', zdaysSeg), field('Koşul', zopSeg), field('z', h('div', { class: 'lvl' }, zlevel))));
      modeBox.appendChild(zinfo);
      help.textContent = 'z = (şimdi − ortalama) ÷ standart sapma; son 20 / 60 / 250 günlük kapanışa göre. 2 ve üstü alışılmadık yüksek, −2 ve altı alışılmadık düşük. '
        + 'OIS, TLREF ve offshore için tarihçe deposu, diğerleri için dashboard\'un her gün kaydettiği kapanışlar kullanılır.';
      showZ();
    }
  }
  from.addEventListener('change', drawAlarm);
  // a watch list's reference (⟲) is one user's: the desk's alarm moves from the open, from now or within minutes
  const deskFrom = () => {
    const ref = from.querySelector('option[value="ref"]');
    ref.disabled = forDesk.checked;
    if (forDesk.checked && from.value === 'ref') { from.value = 'open'; drawAlarm(); }
  };
  forDesk.addEventListener('change', deskFrom);
  deskFrom();
  drawAlarm();

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
    sizeUnit.textContent = p.move_unit || '';
    if (p.since_open_text) now.appendChild(h('span', { class: 'muted' }, ' · açılıştan ' + p.since_open_text));
    if (p.z && p.z['60'] && p.z['60'].z_text) now.appendChild(h('span', { class: 'muted' }, ' · z(60g) ' + p.z['60'].z_text));
    showZ();
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
    const box = amode === 'level' ? level : (amode === 'move' ? size : zlevel);
    if (!levelOf(box.value)) { box.focus(); toast(amode === 'move' ? 'Alarm için hareketin büyüklüğünü yazın' : 'Alarm için bir seviye yazın', 'warn'); return; }
    alarmBtn.disabled = true;
    try {
      const cellHint = state.preview && state.preview.subject.kind === 'cell' ? hint : '';
      const body = { subject: s, label: name.value.trim() || cellHint, note: note.value, level: levelOf(box.value),
        mode: amode === 'move' ? from.value : amode, op: amode === 'level' ? op : (amode === 'z' ? zop : dir), minutes: minutes.value, days: zdays,
        desk: session.role === 'admin' && forDesk.checked };
      const res = await api.post('/api/alarms/add', body);
      if (both.checked) await api.post('/api/watch/add', { subject: s, label: name.value.trim(), hint });
      askPermission();
      const what = (res.alarm && res.alarm.label) || name.value;
      const head = body.desk ? 'Masa alarmı kuruldu' : 'Alarm kuruldu';
      toast(res.already ? head + ' – koşul şu an zaten sağlanıyor: hemen çalar' : head + ': ' + what + ' · ' + (res.condition || ''), res.already ? 'warn' : 'ok', 5000);
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
  // the alarm's box takes the focus, its value selected - unless the user is on another field of the window by now: the
  // value of now may come after they started typing there (their keys stay where they type them)
  if (focus === 'alarm') {
    const box = amode === 'move' ? size : (amode === 'z' ? zlevel : level);
    const at = document.activeElement;
    if (!at || at === box || !m.box.contains(at)) { box.focus(); box.select(); }
  }
}

/** "Alarm kur…" on a cell (right click) or on a watched item. */
export function openAlarmDialog(ctx, { book, ref, label, subject, mode }) {
  return openWatchDialog(ctx, { subject: subject || { kind: 'cell', book: book || 'tto', ref }, hint: label, focus: 'alarm', mode });
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

/** "İzlemeye ekle" for a subject (a point of the heat map). */
export async function watchSubject(ctx, subject, label = '') {
  try {
    const res = await api.post('/api/watch/add', { subject, label });
    toast(res.added ? 'İzleme listesine eklendi: ' + ((res.item && res.item.label) || label) : 'Zaten izleme listesinde', 'ok');
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
let silentSaid = false;
/** A short two-note tone (the alarms', the agenda's recurring items').  Chrome / Edge play no sound on a page nobody has
 * clicked or typed on yet (the autoplay rule): an AudioContext made then starts "suspended" and stays silent for the
 * page's whole life, even after a click (the desk, 20.11.2026: "Yeni sinyal gelince de ötüyordu makine, bugün görmedim" -
 * the context was made at the first ring of a tab not yet clicked).  So before the page's first click or key no context
 * is made and the page says once why it is silent; after it, the context is made - or resumed - when a tone is due. */
export function tone() {
  try {
    const ua = navigator.userActivation;
    if (ua && !ua.hasBeenActive) {
      if (!silentSaid) {
        silentSaid = true;
        toast('🔇 Bu sekmede alarm sesi kapalı: tarayıcı, sayfaya bir kez tıklanana kadar ses çaldırmıyor - ses için sayfaya bir kez tıklayın',
          'warn', 15000);
      }
      return;
    }
    audio = audio || new (window.AudioContext || window.webkitAudioContext)();
    if (audio.state === 'suspended') audio.resume().catch(() => {});
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

const seen = { last: null, desk: null };
const deskToasts = new Map();             // the firing's number in the day's log -> its toast on this page

/** A desktop notification; ``tag`` names the firing, so that the same one shown by two windows of the dashboard (two
 *  tabs both hear the alarm) is one notification, not two. */
export function notify(title, body, tag) {
  try {
    if (window.Notification && Notification.permission === 'granted') new Notification(title, tag ? { body, tag } : { body });
  } catch (x) { /* no notification */ }
}

/** "Gördüm, ben bakıyorum": a desk alarm's firing answered for everyone. */
export async function ackDesk(seq) {
  return api.post('/api/alarms/ack', { seq });
}

/** Mute a desk alarm (an id, or "sys:feed" …) for oneself: 15 / 30 / 60 / 120 minutes, "gün", 0 = lift.  It still
 * rings for everyone else. */
export async function muteDesk(alarm, minutes) {
  return api.post('/api/alarms/mute', { alarm, minutes });
}

/** The choices of a mute (for oneself only), as a menu under (x, y). */
export function muteMenu(x, y, alarm, muted, after) {
  const pick = (minutes) => muteDesk(alarm, minutes).then((r) => {
    toast(minutes ? 'Sizin için susturuldu · bitiş ' + (r.until || '').slice(11, 16) + ' (başkalarına çalmaya devam eder)'
      : 'Susturma kaldırıldı', 'ok');
    if (minutes) {                                   // muted: its toast on this screen goes too
      for (const [seq, el] of deskToasts) if (el.dataset.alarm === alarm) { el.remove(); deskToasts.delete(seq); }
    }
    if (after) after();
  }).catch(errorToast);
  menu(x, y, [{ header: 'Yalnızca benim için sustur' }, ...[15, 30, 60, 120].map((n) => ({ label: n + ' dakika', action: () => pick(n) })),
    { label: 'Gün sonuna kadar', action: () => pick('gün') }].concat(muted ? [{ sep: true }, { label: 'Susturmayı kaldır', action: () => pick(0) }] : []));
}

function deskCounter(open) {
  const b = document.getElementById('desk-alarm');
  if (!b) return;
  const n = (open || []).length;
  b.classList.toggle('hidden', !n);
  b.textContent = '🔔 ' + n + ' masa alarmı';
  b.title = n ? 'Kimsenin "Gördüm" demediği masa alarmları:\n' + open.map((e) => e.at + ' · ' + e.label + (e.text ? ': ' + e.text : '')).join('\n')
    + '\nTıklayın: İzleme · Alarmlar → Masa alarmları' : '';
  if (!b.dataset.bound) {
    b.dataset.bound = '1';
    b.addEventListener('click', () => { window.location.hash = '#/watch?p=watch-desk'; });
  }
}

function deskToast(e) {
  const ack = h('button', { class: 'btn sm', type: 'button', title: 'Herkese "ben bakıyorum" der' }, 'Gördüm, ben bakıyorum');
  const body = h('span', { class: 'desk-text' }, '🔔 MASA ALARMI · ' + e.label + (e.text ? ': ' + e.text : '') + ' · ' + e.at
    + (e.note ? ' · ' + e.note : ''));
  const el = toast(h('span', null, body, ' ', ack), 'alarm desk', 120000);
  el.dataset.seq = String(e.seq);
  el.dataset.alarm = e.alarm;
  ack.addEventListener('click', async (ev) => {
    ev.stopPropagation();
    ack.disabled = true;
    try { answered(el, await ackDesk(e.seq).then((r) => r.entry)); } catch (err) { errorToast(err); ack.disabled = false; }
  });
  el.addEventListener('click', () => { el.remove(); deskToasts.delete(e.seq); });
  deskToasts.set(e.seq, el);
  notify('TTO masa alarmı · ' + e.label, e.text || '', 'tto-desk-' + e.seq + '-' + (e.at || ''));
}

/** A firing someone answered: its toast says who, and goes a little later. */
function answered(el, entry) {
  if (!el || !entry) return;
  const btn = el.querySelector('button');
  if (btn) btn.remove();
  el.classList.add('answered');
  el.appendChild(h('div', { class: 'desk-ack' }, entry.ack_name ? '✓ Gördüm – ' + entry.ack_name + ' bakıyor (' + entry.ack_at + ')' : '✓ kapandı'));
  setTimeout(() => el.remove(), 8000);
  deskToasts.delete(entry.seq);
}

/** What fired since the last look: told once each (the first look of a session only learns where it stands).  One
 * look at a time: generations arriving in a burst (a live tick, an alarm, an answer) asked two looks at once, and both
 * showed what fired - the same alarm twice, one of its toasts left with the "Gördüm" button after the answer. */
let looking = null;
let lookAgain = false;
export async function checkAlarms() {
  if (looking) { lookAgain = true; return looking; }
  looking = (async () => {
    let fired = [];
    do {
      lookAgain = false;
      fired = fired.concat(await lookOnce());
    } while (lookAgain);
    return fired;
  })();
  try { return await looking; } finally { looking = null; }
}

async function lookOnce() {
  let res;
  try {
    res = await api.get('/api/alarms/fired', { since: seen.last == null ? 0 : seen.last, desk: seen.desk == null ? 0 : seen.desk });
  } catch (e) { return []; }
  const d = res.desk || { events: [], last: 0, open: [] };
  deskCounter((d.open || []).filter((e) => !e.muted));      // what this user muted for themselves is not counted
  if (seen.last == null) { seen.last = res.last; seen.desk = d.last; return []; }
  const op = Object.fromEntries(OPS.map(([v, t]) => [v, t]));
  for (const e of res.fired) {
    const cond = e.mode && e.mode !== 'level' ? (e.measure_text ? e.measure_text + ', ' : '') + (e.condition || '')
      : (op[e.op] || e.op) + ' ' + (e.level_text || e.level);
    const text = '🔔 ' + e.label + ': ' + (e.value_text || e.value) + '  (' + cond + ') · ' + e.time + (e.note ? ' · ' + e.note : '');
    const el = toast(text, 'alarm', 15000);
    el.addEventListener('click', () => el.remove());
    notify('TTO alarm · ' + e.label, text.slice(2), 'tto-alarm-' + (e.id || '') + '-' + (e.seq || '') + '-' + (e.time || ''));
  }
  // the desk's: a firing for everyone, an answer, a condition that ended - silent for this user when they muted it
  let rang = res.fired.length > 0;
  for (const e of d.events) {
    if (e.muted) continue;
    if (e.kind === 'fired' && !deskToasts.has(e.seq)) { deskToast(e); rang = true; }
    else if (e.kind === 'resolved') {
      for (const [seq, el] of deskToasts) if (el.dataset.alarm === e.alarm) answered(el, { seq });
      toast('✓ ' + e.label + ': ' + (e.text || 'düzeldi') + ' · ' + e.at, 'ok', 6000);
    }
  }
  // toasts of firings that are no longer open: answered here or on another screen, closed
  const open = new Set((d.open || []).map((e) => e.seq));
  for (const [seq, el] of deskToasts) {
    if (open.has(seq)) continue;
    const ack = d.events.find((x) => x.kind === 'ack' && x.ref === seq);
    answered(el, ack ? { seq, ack_name: ack.by_name, ack_at: ack.at } : { seq });
  }
  if (rang) tone();
  seen.last = Math.max(seen.last, res.last || 0);
  seen.desk = d.last < seen.desk ? d.last : Math.max(seen.desk, d.last || 0);     // a new day starts its log again
  return res.fired;
}
