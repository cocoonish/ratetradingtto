// "Prop" in the top bar (tto/prop.py): a position-size calculator and, below it, the prop risk of a Trades tab - on every
// page, to look at only: nothing is booked or sent; the one thing kept is the user's own daily loss limit (server-side).
// The calculator asks the server as its inputs change (debounced): the direction from the stop against the entry, the
// size rounded down to 1M, the real loss at it, the loss of 1M.  Two-way (the desk, 24.11.2026: "tüm tablolar bu şekilde
// olmalı"): the size may be typed instead of the loss - of the two, the one typed last stands (✎, bold) and the other
// shows what it gives (greyed); Delete on it: nothing typed again.  The risk: the loss if every stop is hit, the tab's
// "Günlük" K/Z (its last "MTM yenile", as the Trades page shows it), the limit and the room left - asked when the panel
// opens, on its buttons and once a minute while it is open.
import { api } from './api.js';
import { num } from './format.js';
import { h, clear, debounce, toast, errorToast } from './ui.js';

const $ = (id) => document.getElementById(id);
/** the risk is asked again this often while the panel is open (ms) */
const RISK_EVERY = 60000;
const SCOPE_KEY = 'tto.prop.scope';
const UNIT_TEXT = { bp: 'bp', pip: 'pip', puan: 'puan', '%': '% prim' };

const pp = {
  el: null,            // the panel (built once, kept while signed in)
  open: false,
  pairs: [],           // the desk's pairs that have a price: [{pair, mid, how, decimals, pip}]
  limit: null,         // the user's daily loss limit {amount, ccy}
  calc: null,          // the calculator's last answer
  risk: null,          // the last risk answer
  ccy: 'TRY',          // the loss's currency - the panel's: the risk is shown in it too
  anchor: null,        // of the loss and the size, the one typed last ('loss' / 'size'; null: neither)
  scope: 'personal',
  ticket: 0,           // the calculator's latest request
  rticket: 0,          // the risk's latest request
  timer: null,
};

function remember(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    localStorage.setItem(key, value);
  } catch (e) { /* storage unavailable */ }
  return null;
}

const money = (v) => (typeof v === 'number' ? num(v, 0) : '—');
const signed = (v) => (typeof v === 'number' ? (v > 0 ? '+' : '') + num(v, 0) : '—');
const k = () => pp.ccy.toLowerCase();

// ---------------------------------------------------------------------- the panel
function seg(id, items, value, onPick) {
  const el = h('span', { class: 'seg', id });
  for (const [v, label, tip] of items) {
    const b = h('button', { type: 'button', title: tip || null, class: v === value ? 'on' : null }, label);
    b.dataset.v = v;
    b.addEventListener('click', () => {
      for (const x of el.children) x.classList.toggle('on', x === b);
      onPick(v);
    });
    el.appendChild(b);
  }
  return el;
}

function field(label, input, extra) {
  return h('label', { class: 'pp-field' }, h('span', { class: 'lbl' }, label), input, extra || null);
}

function build() {
  const inp = (id, ph, tip) => h('input', { class: 'inp', id, type: 'text', autocomplete: 'off', spellcheck: 'false', placeholder: ph, title: tip });
  const pair = inp('prop-pair', 'USDTRY', 'Masanın FX listesinden, fiyatı olan bir parite (büyük / küçük harf fark etmez)');
  pair.setAttribute('list', 'prop-pairs');
  const entry = inp('prop-entry', 'canlı orta kur', 'Boş: panodaki canlı orta kur; yazılırsa o');
  const stop = inp('prop-stop', 'stop kuru', 'Stop seviyesi: girişin altında long, üstünde short');
  const loss = inp('prop-loss', '500k, 1mn', 'Göze aldığınız kayıp: 500k, 1mn, 2,5mn - büyüklük ondan (1M\'e aşağı yuvarlanır)');
  const size = inp('prop-size-in', '2m, 5m', 'Büyüklük (baz döviz): 2m, 2,5m - yazarsanız stoptaki kayıp ondan hesaplanır. Kayıp ve büyüklükten '
    + 'son yazdığınız kalır, öbürü ondan hesaplanır');
  const ccy = seg('prop-ccy', [['TRY', 'TRY', 'Kayıp TL; risk de TL gösterilir'], ['USD', 'USD', 'Kayıp USD; risk de USD gösterilir']], pp.ccy, (v) => {
    pp.ccy = v;
    askCalc();
    paintRisk();
  });
  for (const x of [pair, entry, stop, loss, size]) {
    x.addEventListener('input', () => {
      if (x === loss || x === size) typed(x === loss ? 'loss' : 'size');
      askCalc();
    });
    x.addEventListener('keydown', (e) => { if (e.key === 'Enter') { askCalc.cancel(); calcNow(); } });
  }
  pair.addEventListener('change', () => paintMid());
  pair.addEventListener('input', () => paintMid());
  const scope = seg('prop-scope', [['personal', 'Kişisel', 'Trades\'teki kişisel işlemleriniz'], ['desk', 'Masa', 'Trades\'teki masa işlemleri']],
    pp.scope, (v) => {
      pp.scope = v;
      remember(SCOPE_KEY, v);
      loadRisk();
    });
  const limit = h('input', { class: 'inp', id: 'prop-limit', type: 'text', autocomplete: 'off', placeholder: 'ör. 1mn',
    title: 'Günlük kayıp limitiniz: yalnız siz görür ve değiştirirsiniz. Boş bırakıp kaydederseniz limit kalkar.' });
  limit.addEventListener('keydown', (e) => { if (e.key === 'Enter') saveLimit(); });
  const limitCcy = h('select', { class: 'inp', id: 'prop-limit-ccy' }, h('option', { value: 'TRY' }, 'TRY'), h('option', { value: 'USD' }, 'USD'));
  const el = h('div', { class: 'prop-pop hidden', id: 'prop-panel', role: 'dialog', 'aria-label': 'Prop' },
    h('div', { class: 'pp-head' }, h('b', null, 'Prop'), h('span', { class: 'muted' }, ' · pozisyon büyüklüğü ve risk · yalnız görmek için, hiçbir şey kaydedilmez'),
      h('span', { class: 'spacer' }),
      h('button', { class: 'iconbtn', id: 'prop-close', type: 'button', title: 'Kapat (Esc)', onclick: () => closePanel() }, '✕')),
    h('div', { class: 'pp-form' },
      field('Parite', pair, h('datalist', { id: 'prop-pairs' })),
      field('Giriş', entry, h('span', { class: 'pp-mid muted', id: 'prop-mid' })),
      field('Stop', stop),
      field('Kayıp', loss, ccy),
      field('Büyüklük', size, h('span', { class: 'pp-mid muted', id: 'prop-size-base' }))),
    h('div', { class: 'errtxt', id: 'prop-err' }),
    h('div', { class: 'pp-out', id: 'prop-result' }),
    h('div', { class: 'pp-risk' },
      h('div', { class: 'pp-rhead' }, h('b', null, 'Prop risk'), scope, h('span', { class: 'spacer' }),
        h('button', { class: 'btn sm', id: 'prop-refresh', type: 'button', title: 'Stop mesafelerini ve K/Z\'ı şimdi yeniden oku', onclick: () => loadRisk() }, 'Yenile')),
      h('div', { class: 'pp-line', id: 'prop-line' }),
      h('div', { class: 'pp-pnl muted', id: 'prop-pnl-note' }),
      h('div', { id: 'prop-stops-box' }),
      h('div', { id: 'prop-nostop' }),
      h('div', { class: 'pp-limit' }, h('span', { class: 'lbl' }, 'Günlük kayıp limitim'), limit, limitCcy,
        h('button', { class: 'btn sm', id: 'prop-limit-save', type: 'button', onclick: () => saveLimit() }, 'Kaydet'),
        h('span', { class: 'muted' }, 'yalnız siz görürsünüz')),
      h('div', { class: 'pp-note muted' }, 'Kalan = limit − bugünkü zarar (kâr alan açmaz) − stoplardaki kayıp. Stoptaki kayıp şimdiki piyasadan, '
        + 'işlemin kendi seviyesinde ve değerlemesinin duyarlılığıyla: FX spot tutar × kur farkı; OIS / SOFR / FRA DV01 × bp; spread / fly '
        + 'seviyenin DV01\'i × bp; DİBS getiriyle DV01 × bp, fiyatla nominal × fiyat farkı / 100; opsiyonun stopu prim tutarıdır, kayıp prim '
        + 'farkı (delta ile karşılık gelen spot yaklaşıktır). Geçilmiş stop Stoplar\'a eklenmez: ötesindeki kayıp zaten K/Z\'dedir. '
        + 'Seviyeler alarmlar gibi Bootstrap (Murex) eğrisiyle; Bugün K/Z, Trades sayfasındaki "Günlük" (son MTM yenile).')));
  document.body.appendChild(el);
  pp.el = el;
}

function place() {
  const btn = $('prop-btn');
  if (!pp.open || !pp.el || !btn) return;
  const r = btn.getBoundingClientRect();
  const w = pp.el.offsetWidth;
  pp.el.style.top = Math.round(r.bottom + 6) + 'px';
  pp.el.style.left = Math.max(6, Math.min(Math.round(r.right - w), window.innerWidth - w - 6)) + 'px';
}

async function openPanel() {
  if (!pp.el) build();
  pp.open = true;
  pp.el.classList.remove('hidden');
  $('prop-btn').setAttribute('aria-expanded', 'true');
  place();
  $('prop-pair').focus();
  clearInterval(pp.timer);
  pp.timer = setInterval(() => { if (!document.hidden) loadRisk(); }, RISK_EVERY);
  try {
    const st = await api.get('/api/prop');
    if (!pp.open) return;
    pp.pairs = st.pairs || [];
    pp.limit = st.limit;
    const list = clear($('prop-pairs'));
    for (const p of pp.pairs) list.appendChild(h('option', { value: p.pair }, p.pair + ' · ' + num(p.mid, p.decimals)));
    paintLimit();
    paintMid();
  } catch (e) {
    if (!pp.open || !pp.el) return;                  // (signed out meanwhile)
    $('prop-err').textContent = e.message;
  }
  loadRisk();
  askCalc();
}

function closePanel() {
  if (!pp.open) return;
  pp.open = false;
  clearInterval(pp.timer);
  pp.timer = null;
  if (pp.el) pp.el.classList.add('hidden');
  const btn = $('prop-btn');
  if (btn) btn.setAttribute('aria-expanded', 'false');
}

function pairInfo() {
  const typed = ($('prop-pair').value || '').replace(/[^A-Za-z]/g, '').toUpperCase();
  return pp.pairs.find((p) => p.pair === typed) || null;
}

/** The live mid of the pair typed, beside the entry (the entry's default). */
function paintMid() {
  if (!pp.el) return;
  const p = pairInfo();
  $('prop-mid').textContent = p ? 'canlı ' + num(p.mid, p.decimals) : '';
  $('prop-mid').title = p ? 'Panodaki orta kur (' + p.how + '); giriş boşsa bu kullanılır' : '';
  $('prop-entry').placeholder = p ? num(p.mid, p.decimals) : 'canlı orta kur';
}

// ---------------------------------------------------------------------- the calculator
const askCalc = debounce(() => calcNow(), 300);

/** The loss or the size typed into (two-way): it is the one that stands; the other's own value goes - it shows what the
 *  typed one gives.  Emptied: nothing typed (or the other, if it still holds a value of its own). */
function typed(which) {
  const box = $(which === 'loss' ? 'prop-loss' : 'prop-size-in');
  const other = $(which === 'loss' ? 'prop-size-in' : 'prop-loss');
  if (box.value.trim()) {
    pp.anchor = which;
    other.value = '';
  } else if (pp.anchor === which) {
    pp.anchor = other.value.trim() ? (which === 'loss' ? 'size' : 'loss') : null;
  }
  markAnchor();
}

/** The typed one bold with ✎; the other's placeholder what the typed one gives (or its hint). */
function markAnchor() {
  if (!pp.el) return;
  for (const [id, which] of [['prop-loss', 'loss'], ['prop-size-in', 'size']]) {
    const box = $(id);
    const on = pp.anchor === which;
    box.classList.toggle('tw-anchor', on);
    box.closest('.pp-field').classList.toggle('tw-anchored', on);
  }
  const c = pp.calc;
  const loss = $('prop-loss'), size = $('prop-size-in');
  loss.placeholder = c && pp.anchor === 'size' && typeof c.loss === 'number' ? num(c.loss, 0) : '500k, 1mn';
  size.placeholder = c && pp.anchor === 'loss' ? (c.lots ? c.lots + 'm' : '0') : '2m, 5m';
  $('prop-size-base').textContent = c ? c.base : '';
}

async function calcNow() {
  if (!pp.el) return;
  const q = { pair: $('prop-pair').value.trim(), entry: $('prop-entry').value.trim(), stop: $('prop-stop').value.trim(), ccy: pp.ccy };
  if (pp.anchor === 'size') q.size = $('prop-size-in').value.trim();
  else q.loss = $('prop-loss').value.trim();
  const ticket = ++pp.ticket;
  if (!q.pair || !q.stop || !(q.loss || q.size)) {
    pp.calc = null;
    $('prop-err').textContent = '';
    paintCalc('Pariteyi, stopu ve göze aldığınız kaybı yazın: büyüklük 1M\'e aşağı yuvarlanır, gerçek kayıp hiçbir zaman yazdığınızı geçmez. '
      + 'Ya da büyüklüğü yazın: stoptaki kayıp ondan hesaplanır.');
    return;
  }
  try {
    const res = await api.get('/api/prop/size', q);
    if (ticket !== pp.ticket || !pp.el) return;
    pp.calc = res;
    $('prop-err').textContent = '';
    paintCalc();
  } catch (e) {
    if (ticket !== pp.ticket || !pp.el) return;
    pp.calc = null;
    $('prop-err').textContent = e.message;
    paintCalc();
  }
}

/** The share of today's room the real loss would use (both in the panel's currency) - with a limit and a known K/Z. */
function shareLine(c) {
  const r = pp.risk;
  if (!c || !c.real_loss || !r || !r.limit) return null;
  const room = r.room ? r.room[k()] : null;
  const loss = c.real_loss[k()];
  if (typeof room !== 'number' || typeof loss !== 'number') {
    return h('div', { class: 'pp-share muted', id: 'prop-share' }, 'Kalan alan: ' + ((r.room && r.room.why) || 'bilinmiyor'));
  }
  if (room <= 0) return h('div', { class: 'pp-share neg', id: 'prop-share' }, 'Bugün kalan alan yok (' + money(room) + ' ' + pp.ccy + ')');
  const pct = loss / room * 100;
  return h('div', { class: 'pp-share' + (pct > 100 ? ' neg' : ''), id: 'prop-share' },
    pct > 100 ? 'Bugün kalan alanı aşıyor: ' : 'Bugün kalan alandaki payı: ', h('b', null, '%' + num(pct, pct < 10 ? 1 : 0)),
    h('span', { class: 'muted' }, ' (kalan ' + money(room) + ' ' + pp.ccy + ', ' + r.scope_text + ')'));
}

function paintCalc(hint) {
  const box = clear($('prop-result'));
  const c = pp.calc;
  markAnchor();
  if (!c) {
    if (hint) box.appendChild(h('div', { class: 'muted' }, hint));
    return;
  }
  const dist = num(c.distance, c.decimals) + ' · %' + num(c.distance_pct, 2)
    + (typeof c.kurus === 'number' ? ' · ' + num(c.kurus, 2) + ' kuruş' : '') + ' · ' + num(c.pips, 0) + ' pip';
  box.appendChild(h('div', { class: 'pp-dir ' + c.direction, id: 'prop-dir' }, c.direction_text,
    h('span', { class: 'muted' }, '  giriş ' + num(c.entry, c.decimals) + (c.entry_typed ? '' : ' (canlı)') + ' → stop ' + num(c.stop, c.decimals) + ' · mesafe ' + dist)));
  const ccy = c.loss_ccy;
  const other = ccy === 'TRY' ? 'usd' : 'try';
  const alt = (m) => (typeof m[other] === 'number' ? ' · ' + money(m[other]) + ' ' + other.toUpperCase() : '');
  if (c.anchor === 'size') {
    // the size typed (as it is): the loss it makes at the stop
    box.appendChild(h('div', { class: 'pp-size', id: 'prop-size' }, 'Büyüklük ', h('b', null, num(c.lots, 2).replace(/,?0+$/, '') + 'M ' + c.base),
      h('span', { class: 'muted' }, ' (yazılan)')));
    box.appendChild(h('div', { class: 'pp-real', id: 'prop-real' }, 'Stopta kayıp ', h('b', null, money(c.real_loss.ccy) + ' ' + ccy),
      h('span', { class: 'muted' }, alt(c.real_loss))));
  } else if (c.under_1m) {
    box.appendChild(h('div', { class: 'pp-size', id: 'prop-size' }, 'Büyüklük ', h('b', null, '0'), h('span', { class: 'muted' }, ' (ham ' + num(c.size_raw / 1e6, 2) + 'M)')));
    box.appendChild(h('div', { class: 'pp-real neg', id: 'prop-real' }, '1M bile ' + money(c.loss) + ' ' + ccy + ' kaybı aşıyor: 1M\'de kayıp ',
      h('b', null, money(c.per_1m.ccy) + ' ' + ccy), h('span', { class: 'muted' }, alt(c.per_1m))));
  } else {
    box.appendChild(h('div', { class: 'pp-size', id: 'prop-size' }, 'Büyüklük ', h('b', null, c.lots + 'M ' + c.base),
      h('span', { class: 'muted' }, ' (ham ' + num(c.size_raw / 1e6, 2) + 'M, 1M\'e aşağı)')));
    box.appendChild(h('div', { class: 'pp-real', id: 'prop-real' }, 'Gerçek kayıp ', h('b', null, money(c.real_loss.ccy) + ' ' + ccy),
      h('span', { class: 'muted' }, alt(c.real_loss))));
  }
  box.appendChild(h('div', { class: 'pp-per', id: 'prop-per1m' }, '1M başına ' + money(c.per_1m.ccy) + ' ' + ccy, h('span', { class: 'muted' }, alt(c.per_1m))));
  const share = shareLine(c);
  if (share) box.appendChild(share);
  place();                                   // (the top bar may have wrapped meanwhile: the panel stays under its button)
}

// ---------------------------------------------------------------------- the risk
async function loadRisk() {
  if (!pp.open) return;
  const ticket = ++pp.rticket;
  try {
    const r = await api.get('/api/prop/risk', { scope: pp.scope });
    if (ticket !== pp.rticket || !pp.open) return;
    pp.risk = r;
    pp.limit = r.limit ? { amount: r.limit.amount, ccy: r.limit.ccy } : null;
  } catch (e) {
    if (ticket !== pp.rticket || !pp.el) return;
    pp.risk = null;
    $('prop-line').textContent = 'Risk okunamadı: ' + e.message;
    return;
  }
  paintRisk();
  if (pp.calc) paintCalc();                          // (the share of the room it would use)
}

function levelText(row, v) {
  if (typeof v !== 'number') return '—';
  const d = typeof row.digits === 'number' ? row.digits : 2;
  if (row.level_short === '%' || row.level_short === 'getiri %') return '%' + num(v, d);
  if (row.level_short === 'bp') return num(v, 1);
  return num(v, d);
}

function distText(row) {
  if (typeof row.to_stop !== 'number') return '—';
  const unit = UNIT_TEXT[row.unit] || row.unit || '';
  const digits = row.unit === 'bp' ? 1 : row.unit === 'puan' ? 3 : 0;
  return num(row.to_stop, digits) + ' ' + unit;
}

function sensText(row) {
  const s = row.sens;
  if (!s) return '';
  if (s.kind === 'dv01') return 'DV01 ' + num(s.dv01, 0) + ' ' + s.ccy + '/bp';
  if (s.kind === 'nominal') return 'nominal / 100 = ' + num(s.per, 0) + ' ' + s.ccy + ' / fiyat puanı';
  if (s.kind === 'size') return 'tutar ' + num(s.per, 0) + ' ' + (s.base || '');
  return 'prim farkı (' + s.ccy + ')';
}

function paintRisk() {
  const r = pp.risk;
  if (!pp.el || !r) return;
  const c = k();
  const line = clear($('prop-line'));
  const cell = (id, label, v, cls, tip) => h('div', { class: 'pp-kpi', id, title: tip || null }, h('div', { class: 'l' }, label),
    h('div', { class: 'v ' + (cls || '') }, v));
  const pnl = r.pnl[c];
  // (no limit: no Limit, no Kalan - Bugün K/Z · Stoplar alone)
  if (r.limit) {
    line.appendChild(cell('prop-limit-v', 'Limit', money(r.limit[c]) + ' ' + pp.ccy, '', 'Kaydedilen: ' + money(r.limit.amount) + ' ' + r.limit.ccy));
  }
  line.appendChild(cell('prop-pnl-v', 'Bugün K/Z', typeof pnl === 'number' ? signed(pnl) + ' ' + pp.ccy + (r.pnl.missing ? ' *' : '') : '—',
    typeof pnl === 'number' ? (pnl < 0 ? 'neg' : 'pos') : 'muted', r.pnl.why || ('Trades\'teki "Günlük" (son MTM yenile)'
      + (r.pnl.missing ? ' · ' + r.pnl.missing + ' işlemin K/Z\'ı bilinmiyor (toplama girmedi)' : ''))));
  line.appendChild(cell('prop-stops-v', 'Stoplar', money(r.stops[c]) + ' ' + pp.ccy + (r.stops.unknown ? ' *' : ''), r.stops[c] ? 'neg' : '',
    r.stops.count + ' işlem stopa giderse' + (r.stops.unknown ? ' · ' + r.stops.unknown + ' işlem ölçülemedi (toplama girmedi)' : '')));
  if (r.limit) {
    const room = r.room[c];
    line.appendChild(cell('prop-room-v', 'Kalan', typeof room === 'number' ? money(room) + ' ' + pp.ccy : '—',
      typeof room === 'number' ? (room <= 0 ? 'neg' : 'pos') : 'muted', r.room.why || 'limit − bugünkü zarar − stoplar'));
  }
  // where today's K/Z comes from, and the way to take it
  const note = clear($('prop-pnl-note'));
  const mtmBtn = h('button', { class: 'btn sm', id: 'prop-mtm', type: 'button', title: 'Trades\'in "MTM yenile"si: bu sekmenin işlemlerini şimdi değerler',
    onclick: () => runMtm() }, 'MTM yenile');
  if (r.pnl.why) note.append(r.pnl.why + ' ', mtmBtn);
  else {
    note.append('K/Z: ' + r.scope_text + ' sekmesinin son MTM yenilemesi ' + (r.pnl.at || '').slice(11, 16)
      + (r.pnl.by_name ? ' (' + r.pnl.by_name + ')' : '') + (r.pnl.stale ? ' · işlemler sonradan değişti' : '')
      + (r.pnl.missing ? ' · ' + r.pnl.missing + ' işlemin K/Z\'ı bilinmiyor' : '') + ' ', mtmBtn);
  }
  // the trades with a stop
  const box = clear($('prop-stops-box'));
  if (!r.trades.length) {
    box.appendChild(h('div', { class: 'muted pp-empty' }, r.scope_text + ' sekmesinde stoplu açık işlem yok.'));
  } else {
    const body = h('tbody');
    for (const row of r.trades) {
      let lossCell;
      if (row.state === 'open') lossCell = h('td', { class: 'neg' }, money(row.loss[c]));
      else if (row.state === 'passed') lossCell = h('td', { class: 'muted', title: 'Stop geçildi: ötesindeki kayıp zaten K/Z\'de (MTM\'de); Stoplar\'a eklenmez' },
        'geçildi · ötesi ' + money(row.beyond[c]));
      else lossCell = h('td', { class: 'muted', title: row.why || '' }, row.state === 'unvalued' ? 'değerlenemedi' : 'okunamadı');
      const tip = [sensText(row), row.spot_at_stop ? '≈ spot ' + num(row.spot_at_stop, 4) + ' (' + row.approx + ')' : '', row.why || ''].filter(Boolean).join(' · ');
      body.appendChild(h('tr', { dataset: { id: row.id, state: row.state }, title: tip || null },
        h('td', { class: 'l' }, row.text),
        h('td', null, levelText(row, row.now) + ' → ' + levelText(row, row.stop)),
        h('td', null, row.state === 'open' || row.state === 'passed' ? distText(row) : '—'),
        h('td', { class: 'l muted' }, sensText(row) + (row.spot_at_stop ? ' · ≈ spot ' + num(row.spot_at_stop, 4) : '')),
        lossCell));
    }
    box.appendChild(h('table', { class: 'plain pp-table', id: 'prop-stops' },
      h('thead', null, h('tr', null, h('th', { class: 'l' }, 'Stoplu işlem'), h('th', null, 'Şimdi → stop'), h('th', null, 'Mesafe'),
        h('th', { class: 'l' }, 'Duyarlılık'), h('th', null, 'Stopta kayıp ' + pp.ccy))), body));
  }
  // the trades without a stop: their DV01, size or delta
  const ns = clear($('prop-nostop'));
  if (r.nostop.length) {
    const items = r.nostop.map((row) => {
      const e = row.exposure;
      const what = !e ? 'değer yok' : e.kind === 'dv01' ? 'DV01 ' + money(e.amount) + ' ' + e.ccy + '/bp'
        : e.kind === 'delta' ? 'delta ' + money(e.amount) + ' ' + e.ccy + ' (yaklaşık)' : e.kind === 'size' ? money(e.amount) + ' ' + e.ccy
          : money(e.amount) + ' ' + e.ccy;
      return h('li', { dataset: { id: row.id } }, row.text, h('span', { class: 'muted' }, ' · ' + what));
    });
    ns.appendChild(h('div', { class: 'pp-nostop' }, h('b', null, 'Stopsuz (' + r.nostop.length + ')'),
      h('span', { class: 'muted' }, ' · Stoplar\'a girmez'), h('ul', null, ...items)));
  }
  place();
}

function paintLimit() {
  if (!pp.el) return;
  const l = pp.limit;
  if (document.activeElement !== $('prop-limit')) $('prop-limit').value = l ? num(l.amount, 0) : '';
  $('prop-limit-ccy').value = l ? l.ccy : pp.ccy;
}

async function saveLimit() {
  const amount = $('prop-limit').value.trim();
  try {
    const res = await api.post('/api/prop/limit', { amount, ccy: $('prop-limit-ccy').value });
    pp.limit = res.limit;
    $('prop-limit').blur();
    paintLimit();
    toast(res.limit ? 'Günlük kayıp limitiniz: ' + money(res.limit.amount) + ' ' + res.limit.ccy : 'Günlük kayıp limitiniz kaldırıldı', 'ok', 2600);
    loadRisk();
  } catch (e) { errorToast(e); }
}

async function runMtm() {
  const b = $('prop-mtm');
  if (b) b.disabled = true;
  try {
    await api.post('/api/trades/mtm', { scope: pp.scope });
    await loadRisk();
  } catch (e) { errorToast(e); } finally {
    if (b) b.disabled = false;
  }
}

// ---------------------------------------------------------------------- wiring (main.js)
/** Once at the start: the top bar's button, and what closes the panel (a click elsewhere, Esc). */
export function setupProp() {
  const btn = $('prop-btn');
  if (!btn || btn.dataset.wired) return;
  btn.dataset.wired = '1';
  const kept = remember(SCOPE_KEY);
  pp.scope = kept === 'desk' ? 'desk' : 'personal';
  btn.addEventListener('click', () => { if (pp.open) closePanel(); else openPanel(); });
  document.addEventListener('mousedown', (e) => {
    if (pp.open && pp.el && !pp.el.contains(e.target) && !btn.contains(e.target)) closePanel();
  }, true);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && pp.open) closePanel(); }, true);
  window.addEventListener('resize', place);
}

/** Signed out: the panel closes and forgets what was typed (the next user starts empty). */
export function stopProp() {
  closePanel();
  askCalc.cancel();
  if (pp.el) { pp.el.remove(); pp.el = null; }
  // (the answers still on their way are dropped: their tickets are old)
  Object.assign(pp, { pairs: [], limit: null, calc: null, risk: null, ccy: 'TRY', anchor: null, ticket: pp.ticket + 1, rticket: pp.rticket + 1 });
}
