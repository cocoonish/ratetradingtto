// RET faizleri · Adil değer: the desk's rule-based RET (tto/retfair.py) beside the published one.  Per tenor a base
// (OIS / VİOP / offshore mid, or a blend), the trader's offset, the flow adjustments accepted from suggestions and a
// fixed width give "Şimdiki" - the base setting the mid, the bid or the ask ("Tabana göre"); "Kopyala ve yayınla" copies
// it and writes it as the desk's RET.  The settings are the desk's (shared): every change goes to the server and into the
// log with who and when.  "Senaryo" is the user's own: the market, or a PPK scenario of the OIS page in their own
// calculation; a table puts every tenor under the market and each scenario side by side.
import { api } from './api.js';
import { h, clear, toast, errorToast, copyText } from './ui.js';
import { num, parseNumber, isoToTr } from './format.js';

const BASES = [['ois', 'OIS mid'], ['viop', 'VİOP mid'], ['off', 'Offshore mid'], ['blend', 'Karma']];
const BASE_NAME = { ois: 'OIS mid', viop: 'VİOP mid', off: 'offshore mid', blend: 'karma' };
const ANCHORS = [['bid', 'Bid', 'Taban + spread + akış bid\'i belirler (5 bp ızgarası), ask = bid + genişlik'],
  ['mid', 'Mid', 'Taban + spread + akış mid\'i belirler: bid = mid − genişlik / 2 (5 bp ızgarası), ask = bid + genişlik'],
  ['ask', 'Ask', 'Taban + spread + akış ask\'ı belirler (5 bp ızgarası), bid = ask − genişlik']];
const MARKET = 'piyasa';
const POLL_MS = 5000;

function pct(v, digits) {
  return typeof v === 'number' ? num(v * 100, digits === undefined ? 2 : digits, false) : '';
}

/** A signed number of bp: +5, −10 (one decimal when it has one). */
function sbp(v) {
  if (typeof v !== 'number' || !isFinite(v)) return '';
  const r = Math.round(v * 10) / 10;
  const text = num(Math.abs(r), Math.abs(r - Math.round(r)) > 1e-9 ? 1 : 0, false);
  return (r > 0 ? '+' : r < 0 ? '−' : '') + text;
}

/** A distance in whole bp with its sign: +210, −60. */
function ibp(v) {
  return typeof v === 'number' && isFinite(v) ? sbp(Math.round(v)) : '';
}

function pair(x) {
  return x && typeof x.bid === 'number' && typeof x.ask === 'number' ? pct(x.bid) + ' / ' + pct(x.ask) : '—';
}

function trDate() {
  const d = new Date();
  return String(d.getDate()).padStart(2, '0') + '.' + String(d.getMonth() + 1).padStart(2, '0') + '.' + d.getFullYear();
}

function store(key, value) {
  try {
    if (value === undefined) return localStorage.getItem(key);
    localStorage.setItem(key, value);
  } catch (e) { /* storage unavailable */ }
  return null;
}

/**
 * The "Adil değer" part of the RET dialog.  ``retText(rows, kind, date)`` makes the clipboard text (the dialog's own
 * table / message formats); ``onPublished()`` is told after a publish (the manual part shows the new curve).
 */
export function fairPane(ctx, { retText, signedBp, onPublished, onClose }) {
  const el = h('div', { id: 'ret-pane-fair', class: 'retfair-pane hidden' });
  let data = null;
  let timer = null;
  let busy = false;
  let visible = false;
  let built = false;
  const rows = {};                       // tenor -> {tr, cells ...}
  const dirty = new Set();               // offset boxes being typed in
  const selected = new Set();
  let fmt = store('tto.ret.fair.fmt') === 'message' ? 'message' : 'table';

  // ---------------------------------------------------------------- the top: the banner, publish, where to go
  const banner = h('div', { class: 'banner retfair-banner hidden', id: 'retfair-banner' });
  const meta = h('span', { class: 'muted', id: 'retfair-meta' });
  const fmtSeg = h('div', { class: 'seg', id: 'retfair-fmt' });
  for (const [id, kind, label, title] of [['retfair-fmt-table', 'table', 'Tablo', 'Vade · gün · bid · ask: Excel\'e yapıştırılacak tablo'],
    ['retfair-fmt-msg', 'message', 'Mesaj', 'Sohbet penceresine atılacak hizalı metin']]) {
    const b = h('button', { type: 'button', id, title, class: fmt === kind ? 'on' : '' }, label);
    b.addEventListener('click', () => {
      fmt = kind;
      store('tto.ret.fair.fmt', kind);
      for (const x of fmtSeg.children) x.classList.toggle('on', x === b);
    });
    fmtSeg.appendChild(b);
  }
  const publishBtn = h('button', { class: 'btn sm primary', type: 'button', id: 'retfair-publish',
    title: 'Şimdiki eğriyi panoya kopyalar (seçili biçimde) ve masanın RET\'i olarak yazar: RET\'i okuyan bütün tablolar izler, '
      + 'RET geçmişine kim / ne zaman / ne yazılır, "bugün yüklenmedi" uyarısı kalkar. Şimdiki değeri olmayan vade yayınlanan değerinde kalır.' },
  'Kopyala ve yayınla');
  publishBtn.addEventListener('click', () => publish());
  const posLink = h('button', { class: 'btn sm', type: 'button', id: 'retfair-position-link',
    title: 'Günlük İşlemler sayfasındaki "Pozisyon ve maliyet" tablosu: RET vadelerine göre net TRY satış / alış, maliyet ve K/Z' },
  'Pozisyon ve maliyet →');
  posLink.addEventListener('click', () => {
    if (onClose) onClose();
    window.location.hash = '#/blotter?p=position';
  });
  // the user's own "Senaryo": the market, or a PPK scenario of the OIS page (its name from the SENARYOLAR table)
  const scenSel = h('select', { class: 'inp', id: 'retfair-scenario',
    title: 'Adil değeri hangi eğriyle görüyorsunuz: piyasa (masanın Şimdiki\'si) ya da OIS · PPK senaryolarından biri - sizin adımlarınız ve adlarınızla. '
      + 'Seçim sizin (kişisel), hatırlanır; spread, taban, genişlik ve akış masanın kalır.' });
  scenSel.addEventListener('change', () => {
    const code = scenSel.value;
    queue = queue.then(async () => {
      busy = true;
      try { render(await api.post('/api/ret/fair/view', { scenario: code })); } catch (err) { errorToast(err); } finally { busy = false; }
    });
  });
  const scenLabel = h('span', { class: 'retfair-scen-label', id: 'retfair-scen-label' });
  const scenNote = h('div', { class: 'muted retfair-scen-note hidden', id: 'retfair-scen-note' });
  el.appendChild(banner);
  el.appendChild(h('div', { class: 'ret-tools retfair-top' }, fmtSeg, publishBtn, meta, h('span', { class: 'sep' }),
    h('span', { class: 'muted' }, 'Senaryo'), scenSel, scenLabel, h('span', { class: 'grow' }), posLink));
  el.appendChild(scenNote);

  // ---------------------------------------------------------------- many tenors at once
  const selCount = h('span', { class: 'muted', id: 'retfair-selcount' });
  const bulkBp = h('input', { type: 'text', class: 'inp num', id: 'retfair-bulk-bp', placeholder: 'bp', autocomplete: 'off', style: { width: '78px' } });
  const bulkSet = h('button', { class: 'btn sm', type: 'button', id: 'retfair-bulk-set', title: 'Seçili vadelerin tabana spread\'ini bu baz puan yap' }, 'Spread yaz');
  const bulkShift = h('button', { class: 'btn sm', type: 'button', id: 'retfair-bulk-shift', title: 'Seçili vadelerin tabana spread\'ine bu kadar baz puan ekle (− ile azalt)' }, 'Kaydır');
  const fromPub = h('button', { class: 'btn sm', type: 'button', id: 'retfair-from-pub',
    title: 'Seçili vadelerin tabana spread\'ini, Şimdiki yayınlanan RET\'e eşit olacak şekilde ayarla: yayınlanan mid (Mid vadesi), bid (Bid) '
      + 'ya da ask (Ask) − taban − akış. Spread masanın: her zaman piyasa tabanıyla (senaryo görünümünde de).' }, 'Yayınlanandan al');
  const bulkBase = h('select', { class: 'inp', id: 'retfair-bulk-base' });
  for (const [v, label] of BASES) bulkBase.appendChild(h('option', { value: v }, label));
  const bulkBaseGo = h('button', { class: 'btn sm', type: 'button', id: 'retfair-bulk-base-apply', title: 'Seçili vadelerin tabanını değiştir (tabana spread aynı kalır)' }, 'Tabanı uygula');
  const target = () => (selected.size ? [...selected] : 'all');
  const bulkNumber = () => {
    const x = parseNumber(bulkBp.value, true);
    if (x === null) { toast('Baz puanı yazın (örn. -60 ya da 5)', 'err'); bulkBp.focus(); }
    return x;
  };
  bulkSet.addEventListener('click', () => { const x = bulkNumber(); if (x !== null) send('/api/ret/fair/tenors', { tenors: target(), offset: x }); });
  bulkShift.addEventListener('click', () => { const x = bulkNumber(); if (x !== null) send('/api/ret/fair/tenors', { tenors: target(), shift: x }); });
  fromPub.addEventListener('click', () => send('/api/ret/fair/tenors', { tenors: target(), from_published: true }));
  bulkBaseGo.addEventListener('click', () => send('/api/ret/fair/tenors', { tenors: target(), base: bulkBase.value }));
  // which quote the base sets, for the selected tenors (none selected: all) - one click
  const bulkAnchor = h('div', { class: 'seg retfair-anchors', id: 'retfair-bulk-anchor' });
  for (const [a, label, title] of ANCHORS) {
    const b = h('button', { type: 'button', title: 'Seçili vadeler (seçim yoksa hepsi): ' + title }, label);
    b.dataset.anchor = a;
    b.addEventListener('click', () => send('/api/ret/fair/tenors', { tenors: target(), anchor: a }));
    bulkAnchor.appendChild(b);
  }
  const paintBulkAnchor = () => {
    // lit when every tenor it would change is set so already
    const rowsOf = data ? data.rows.filter((r) => !selected.size || selected.has(r.tenor)) : [];
    const one = rowsOf.length && rowsOf.every((r) => r.anchor === rowsOf[0].anchor) ? rowsOf[0].anchor : null;
    for (const b of bulkAnchor.children) b.classList.toggle('on', b.dataset.anchor === one);
  };
  el.appendChild(h('div', { class: 'ret-tools retfair-bulk' }, selCount, bulkBp, bulkSet, bulkShift, fromPub,
    h('span', { class: 'sep' }), h('span', { class: 'muted' }, 'Taban'), bulkBase, bulkBaseGo,
    h('span', { class: 'sep' }), h('span', { class: 'muted', title: 'Taban + spread + akış hangi kotayı belirler' }, 'Tabana göre'), bulkAnchor));

  // ---------------------------------------------------------------- the main table
  const allBox = h('input', { type: 'checkbox', id: 'retfair-sel-all', title: 'Hepsini seç / bırak' });
  allBox.addEventListener('change', () => {
    selected.clear();
    if (allBox.checked && data) for (const r of data.rows) selected.add(r.tenor);
    for (const t of Object.keys(rows)) rows[t].sel.checked = selected.has(t);
    paintSel();
  });
  const table = h('table', { class: 'plain retfair', id: 'retfair-table' });
  table.appendChild(h('thead', null, h('tr', null, h('th', null, allBox), h('th', { class: 'l' }, 'Vade'), h('th', null, 'Gün'),
    h('th', { class: 'l' }, 'Taban'),
    h('th', { title: 'Taban + spread + akış hangi kotayı belirler: Bid (ask = bid + genişlik), Mid (bid = mid − genişlik / 2) ya da Ask (bid = ask − genişlik). Masanın, herkes için.' }, 'Tabana göre'),
    h('th', { title: 'Tabana spread: tabanın üstüne / altına baz puan (masanın, herkes için). Enter ile kaydedilir.' }, 'Tabana spread (bp)'),
    h('th', { title: 'Kabul edilen akış önerileri: spread\'den ayrı durur, genişliğe dokunmaz, kaldırılana kadar kalır (× ile)' }, 'Akış (bp)'),
    h('th', { class: 'l' }, 'Formül'), h('th', { title: 'Seçili tabanın mid\'i (basit ACT/360, RET\'in kendi tarihleri arası)' }, 'Taban mid %'),
    h('th', { title: 'Sabit bid–ask genişliği (bp): yalnızca Ekstra ayarlar\'da değişir' }, 'Genişlik'),
    h('th', { title: 'Taban + spread + akış: bid 5 bp\'lik ızgaraya yuvarlanır, ask = bid + genişlik. Ham değer bir adımı histerezisten fazla geçince değişir.' }, 'Şimdiki bid / ask'),
    h('th', { title: 'Masanın şu an yayınlanan RET\'i (RET faizleri)' }, 'Yayınlanan bid / ask'), h('th', null, 'Fark (bp)'))));
  const tbody = h('tbody');
  table.appendChild(tbody);
  const hint = h('div', { class: 'muted retfair-hint', id: 'retfair-hint' });
  el.appendChild(h('div', { class: 'retfair-scroll' }, table));
  el.appendChild(hint);

  // ---------------------------------------------------------------- every tenor under the market and each scenario
  const scenHead = h('thead');
  const scenBody = h('tbody');
  const scenTable = h('table', { class: 'plain retfair-scen', id: 'retfair-scen-table' }, scenHead, scenBody);
  el.appendChild(h('h3', { class: 'retfair-h' }, 'Senaryolara göre adil değer · bid / ask (Piyasa: masanın Şimdiki\'si; senaryolar sizin adımlarınızla, histerezissiz)'));
  el.appendChild(h('div', { class: 'retfair-scroll' }, scenTable));

  // ---------------------------------------------------------------- "Neredeyim"
  const whereBody = h('tbody');
  const wherePub = h('th', { title: 'Kuralın belirlediği yayınlanan taraf: Bid ve Mid vadelerinde bid, Ask vadelerinde ask' }, 'Yayınlanan bid');
  const whereTable = h('table', { class: 'plain retfair-where', id: 'retfair-where' },
    h('thead', null, h('tr', null, h('th', { class: 'l' }, 'Vade'), wherePub,
      h('th', { title: 'Yayınlanan bid − OIS mid (bp)' }, 'OIS mid\'e'), h('th', { title: 'Yayınlanan bid − VİOP mid (bp)' }, 'VİOP mid\'e'),
      h('th', { title: 'Yayınlanan bid − offshore mid (bp)' }, 'Offshore mid\'e'),
      h('th', { title: 'Taban OIS mid olsa, bugünkü spread ve akışla RET (bid / ask)' }, 'OIS ile'), h('th', null, 'VİOP ile'),
      h('th', null, 'Offshore ile'), h('th', null, 'Karma ile'))), whereBody);
  el.appendChild(h('h3', { class: 'retfair-h' }, 'Neredeyim · yayınlanan RET tabanlara göre ve taban değişirse RET'));
  el.appendChild(h('div', { class: 'retfair-scroll' }, whereTable));

  // ---------------------------------------------------------------- the flows and the suggestions
  const flowNote = h('div', { class: 'muted', id: 'retfair-flow-note' });
  const flowBody = h('tbody');
  const flowTable = h('table', { class: 'plain retfair-flows', id: 'retfair-flows' });
  const flowHead = h('thead');
  flowTable.appendChild(flowHead);
  flowTable.appendChild(flowBody);
  const suggBox = h('div', { class: 'retfair-suggs', id: 'retfair-suggestions' });
  el.appendChild(h('h3', { class: 'retfair-h' }, 'Akış · Günlük İşlemler\'deki forward\'lar (yalnızca masanın kendi işlemleri)'));
  el.appendChild(flowNote);
  el.appendChild(h('div', { class: 'retfair-scroll' }, flowTable));
  el.appendChild(suggBox);

  // ---------------------------------------------------------------- "Ekstra ayarlar" (administrators)
  const adminBox = h('details', { class: 'retfair-admin', id: 'retfair-admin' });
  const adminNote = h('div', { class: 'muted', id: 'retfair-admin-note' });
  const widthGrid = h('div', { class: 'retfair-widths' });
  const field = (label, id, title) => {
    const inp = h('input', { type: 'text', class: 'inp num', id, autocomplete: 'off', style: { width: '76px' } });
    return [h('label', { class: 'retfair-field', title }, h('span', null, label), inp), inp];
  };
  const [fHyst, hyst] = field('Histerezis (bp)', 'retfair-hyst', 'Ham değer bir 5 bp adımını bu kadar baz puandan fazla geçmedikçe Şimdiki değişmez');
  const [fSens, sens] = field('Akış hassasiyeti (bp / 100 mn USD)', 'retfair-sens', 'Bugünkü net akışın normalinin üstündeki her 100 mn USD\'si için kaç bp öneri');
  const [fLook, look] = field('Geriye bakış (iş günü)', 'retfair-look', 'Normal akış ve "son N gün" tablosu için kaç iş günü');
  const [fMargin, margin] = field('Asgari marj (bp)', 'retfair-margin', 'Bir öneri RET ask\'ı akışın maliyeti + bu marjın altına indirmez');
  const [fbO, bO] = field('Karma: OIS %', 'retfair-blend-ois', 'Karma tabanın varsayılan ağırlıkları');
  const [fbV, bV] = field('VİOP %', 'retfair-blend-viop', '');
  const [fbF, bF] = field('Offshore %', 'retfair-blend-off', '');
  const adminSave = h('button', { class: 'btn sm primary', type: 'button', id: 'retfair-admin-save' }, 'Ayarları kaydet');
  const widthInputs = {};
  adminSave.addEventListener('click', () => {
    const widths = {};
    for (const [t, inp] of Object.entries(widthInputs)) {
      const x = parseNumber(inp.value, true);
      if (x === null) { toast(t + ' genişliği anlaşılamadı', 'err'); inp.focus(); return; }
      widths[t] = x;
    }
    const n = (inp) => parseNumber(inp.value, true);
    send('/api/ret/fair/settings', { widths, hysteresis: n(hyst), sensitivity: n(sens), lookback: n(look), margin: n(margin),
      blend: { ois: n(bO) || 0, viop: n(bV) || 0, off: n(bF) || 0 } }, 'Ekstra ayarlar kaydedildi');
  });
  adminBox.appendChild(h('summary', null, 'Ekstra ayarlar'));
  adminBox.appendChild(adminNote);
  adminBox.appendChild(h('div', { class: 'retfair-fields' }, fHyst, fSens, fLook, fMargin, fbO, fbV, fbF));
  adminBox.appendChild(h('div', { class: 'muted' }, 'Bid–ask genişlikleri (bp, 5\'in katı):'));
  adminBox.appendChild(widthGrid);
  adminBox.appendChild(h('div', { class: 'retfair-admin-foot' }, adminSave));
  el.appendChild(adminBox);

  // ---------------------------------------------------------------- the log
  const logBox = h('details', { class: 'retfair-log', id: 'retfair-log' });
  const logList = h('div', { class: 'retfair-loglist' });
  logBox.appendChild(h('summary', null, 'Değişiklik geçmişi (kim, ne zaman, ne)'));
  logBox.appendChild(logList);
  el.appendChild(logBox);

  // ---------------------------------------------------------------- talking to the server
  // changes go one after another (two offsets typed in quick succession both arrive); a reading waits for them
  let queue = Promise.resolve();
  function send(path, body, okText) {
    queue = queue.then(async () => {
      busy = true;
      try {
        const res = await api.post(path, body);
        if (okText) toast(okText, 'ok');
        // a tenor this change touched shows what the server has now, even where something was being typed
        for (const t of Object.keys(rows)) if (body && body.tenors && (body.tenors === 'all' || body.tenors.includes(t))) dirty.delete(t);
        render(res);
        if (ctx.refreshNow) ctx.refreshNow();
      } catch (err) {
        errorToast(err);
        if (err.status === 409) { busy = false; await load(); }
      } finally { busy = false; }
    });
    return queue;
  }

  async function load() {
    if (busy) return;
    try {
      const res = await api.get('/api/ret/fair');
      render(res);
    } catch (err) { if (!data) errorToast(err); }
  }

  function paintSel() {
    const n = selected.size;
    selCount.textContent = n ? n + ' vade seçili' : 'Seçim yok: tüm vadeler';
    allBox.checked = !!data && n === data.rows.length;
    paintBulkAnchor();
  }

  // ---------------------------------------------------------------- one tenor's row
  function makeRow(r) {
    const t = r.tenor;
    const sel = h('input', { type: 'checkbox', class: 'retfair-sel' });
    sel.dataset.tenor = t;
    sel.addEventListener('change', () => { if (sel.checked) selected.add(t); else selected.delete(t); paintSel(); });
    const base = h('select', { class: 'inp retfair-base' });
    base.dataset.tenor = t;
    for (const [v, label] of BASES) base.appendChild(h('option', { value: v }, label));
    base.addEventListener('change', () => {
      if (base.value === 'blend') editWeights(t, null);
      else send('/api/ret/fair/tenors', { tenors: [t], base: base.value });
    });
    const wBtn = h('button', { class: 'iconbtn retfair-weights hidden', type: 'button', title: 'Karma ağırlıkları' }, '⚖');
    wBtn.dataset.tenor = t;
    wBtn.addEventListener('click', () => editWeights(t, (data.rows.find((x) => x.tenor === t) || {}).weights));
    const off = h('input', { type: 'text', class: 'inp num retfair-off', autocomplete: 'off', placeholder: '—' });
    off.dataset.tenor = t;
    const commit = () => {
      if (!dirty.has(t)) return;
      const text = off.value.trim();
      const x = text === '' ? null : parseNumber(text, true);
      if (text !== '' && x === null) { toast(t + ': tabana spread anlaşılamadı', 'err'); return; }
      dirty.delete(t);
      send('/api/ret/fair/tenors', { tenors: [t], offset: x });
    };
    off.addEventListener('input', () => dirty.add(t));
    off.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); commit(); }
      if (e.key === 'Escape' && dirty.has(t)) { e.stopPropagation(); dirty.delete(t); paintRow(data.rows.find((x) => x.tenor === t)); }
    });
    off.addEventListener('change', commit);
    const flow = h('span', { class: 'retfair-flow' });
    const flowX = h('button', { class: 'iconbtn retfair-flow-x hidden', type: 'button', title: 'Bu vadenin akış ayarını kaldır' }, '×');
    flowX.dataset.tenor = t;
    flowX.addEventListener('click', () => send('/api/ret/fair/flow', { remove: t }, t + ': akış ayarı kaldırıldı'));
    // "Tabana göre": Bid / Mid / Ask - which quote base + spread + flow sets (one click; the desk's)
    const anchor = h('div', { class: 'seg retfair-anchors retfair-anchor' });
    anchor.dataset.tenor = t;
    for (const [a, label, title] of ANCHORS) {
      const b = h('button', { type: 'button', title: t + ': ' + title }, label);
      b.dataset.anchor = a;
      b.dataset.tenor = t;
      b.addEventListener('click', () => { if (!b.classList.contains('on')) send('/api/ret/fair/tenors', { tenors: [t], anchor: a }); });
      anchor.appendChild(b);
    }
    const cells = {
      sel, base, wBtn, off, flow, flowX, anchor,
      days: h('td', { class: 'muted' }), formula: h('td', { class: 'l retfair-formula' }), mid: h('td'), width: h('td', { class: 'muted' }),
      now: h('td', { class: 'retfair-now' }), pub: h('td', { class: 'retfair-pub' }), diff: h('td', { class: 'retfair-diff' }),
    };
    cells.tr = h('tr', null, h('td', null, sel), h('td', { class: 'l' }, h('b', null, t)), cells.days, h('td', { class: 'l' }, base, wBtn),
      h('td', null, anchor), h('td', null, off), h('td', null, flow, flowX), cells.formula, cells.mid, cells.width, cells.now, cells.pub, cells.diff);
    cells.tr.dataset.tenor = t;
    for (const k of ['now', 'pub', 'diff', 'formula']) cells[k].dataset.tenor = t;
    rows[t] = cells;
    tbody.appendChild(cells.tr);
  }

  function paintRow(r) {
    if (!r) return;
    const c = rows[r.tenor];
    c.days.textContent = typeof r.days === 'number' ? num(r.days, 0) : '';
    if (document.activeElement !== c.base && weighing !== r.tenor) c.base.value = r.base;
    c.wBtn.classList.toggle('hidden', r.base !== 'blend');
    if (!dirty.has(r.tenor) && document.activeElement !== c.off) c.off.value = typeof r.offset === 'number' ? sbp(r.offset).replace('−', '-') : '';
    c.flow.textContent = r.flow ? sbp(r.flow) : '';
    c.flow.title = (r.flow_log || []).map((x) => x.at + ' · ' + ctx.displayName(x.by) + ' · ' + sbp(x.bp) + ' bp · ' + x.why).join('\n');
    c.flowX.classList.toggle('hidden', !r.flow);
    for (const b of c.anchor.children) b.classList.toggle('on', b.dataset.anchor === (r.anchor || 'mid'));
    c.formula.textContent = r.formula;
    c.mid.textContent = typeof r.base_mid === 'number' ? pct(r.base_mid, 3) : '—';
    const scen = data.scenario && data.scenario.code !== MARKET ? data.scenario : null;
    c.mid.title = (scen ? 'Senaryo ' + scen.name + ' (OIS: senaryonun eğrisi; VİOP ve offshore: piyasa + senaryo − ima yol)\n' : '')
      + BASES.slice(0, 3).map(([b, label]) => label + ': ' + (typeof r.mids[b] === 'number' ? pct(r.mids[b], 3) + '%' : (r.why[b] || 'yok'))
        + (scen && r.market_mids && typeof r.market_mids[b] === 'number' ? ' (piyasa ' + pct(r.market_mids[b], 3) + '%)' : '')).join('\n')
      + (r.start ? '\n' + isoToTr(r.start) + ' → ' + isoToTr(r.end) : '');
    c.mid.classList.toggle('muted', typeof r.base_mid !== 'number');
    c.width.textContent = typeof r.width === 'number' ? num(r.width, 0) : '';
    c.pub.textContent = pair(r.pub);
    clear(c.now);
    c.now.className = 'retfair-now';
    if (r.now) {
      c.now.textContent = pair(r.now);
      const d = r.diff ? (r.diff.bid || r.diff.ask) : 0;
      if (r.update) c.now.classList.add(d > 0 ? 'up' : d < 0 ? 'down' : 'chg');
      const grid = scen ? ' → 5 bp ızgarası (senaryo görünümü: histerezis yok)' : ' → 5 bp ızgarası (histerezis ' + num(data.settings.hysteresis, 1) + ' bp)';
      c.now.title = r.anchor === 'bid' ? 'Ham bid ' + pct(r.raw, 4) + '% (taban + spread + akış)' + grid + '; ask = bid + genişlik'
        : r.anchor === 'ask' ? 'Ham ask ' + pct(r.raw, 4) + '% (taban + spread + akış)' + grid + '; bid = ask − genişlik'
          : 'Ham mid ' + pct(r.raw_mid, 4) + '% · ham bid ' + pct(r.raw_bid, 4) + '%' + grid;
      c.diff.textContent = r.diff ? (r.diff.bid === r.diff.ask ? sbp(r.diff.bid) : sbp(r.diff.bid) + ' / ' + sbp(r.diff.ask)) : '';
    } else {
      c.now.textContent = '—';
      c.now.classList.add('muted');
      c.now.title = r.now_why || '';
      c.diff.textContent = '';
    }
    c.tr.classList.toggle('upd', !!r.update && !!r.now);
    c.sel.checked = selected.has(r.tenor);
  }

  let weighing = null;                   // the tenor whose blend weights are being typed (its base box is left alone)
  function closeWeights() {
    const tr = tbody.querySelector('tr.retfair-wrow');
    if (tr) tr.remove();
    weighing = null;
  }

  function editWeights(t, current) {
    // a small form under the row: the three weights of the blend (they need not add up to 100)
    closeWeights();
    weighing = t;
    const w = current || (data.settings && data.settings.blend) || { ois: 50, viop: 25, off: 25 };
    const inp = {};
    const box = h('div', { class: 'retfair-wform', id: 'retfair-wform' }, h('b', null, t + ' karma ağırlıkları'));
    for (const [b, label] of BASES.slice(0, 3)) {
      inp[b] = h('input', { type: 'text', class: 'inp num', value: num(w[b] || 0, Number.isInteger(w[b] || 0) ? 0 : 2, false), style: { width: '60px' } });
      inp[b].dataset.base = b;
      box.appendChild(h('label', null, label + ' ', inp[b]));
    }
    const ok = h('button', { class: 'btn sm primary', type: 'button', id: 'retfair-wform-ok' }, 'Uygula');
    const no = h('button', { class: 'btn sm', type: 'button' }, 'Vazgeç');
    ok.addEventListener('click', () => {
      const weights = {};
      for (const b of Object.keys(inp)) weights[b] = parseNumber(inp[b].value, true) || 0;
      closeWeights();
      send('/api/ret/fair/tenors', { tenors: [t], base: 'blend', weights });
    });
    no.addEventListener('click', () => { closeWeights(); paintRow(data.rows.find((x) => x.tenor === t)); });
    box.appendChild(ok);
    box.appendChild(no);
    rows[t].tr.after(h('tr', { class: 'retfair-wrow' }, h('td', { colspan: '13' }, box)));
    inp.ois.focus();
  }

  // ---------------------------------------------------------------- painting everything
  function render(res) {
    data = res;
    if (!built) {
      for (const r of res.rows) makeRow(r);
      built = true;
    }
    for (const r of res.rows) {
      if (!rows[r.tenor]) makeRow(r);
      paintRow(r);
    }
    paintSel();
    const scen = res.scenario && res.scenario.code !== MARKET ? res.scenario : null;
    const ups = res.updates || [];
    banner.textContent = ups.length ? (scen ? scen.name + ' senaryosunda RET güncellemesi: ' : 'RET güncellemesi var: ') + ups.join(', ') : '';
    banner.classList.toggle('hidden', !ups.length);
    const m = res.meta;
    meta.textContent = m && m.updated_at ? 'Yayınlanan: ' + m.updated_at + (m.updated_by ? ' · ' + ctx.displayName(m.updated_by) : '') : 'Yayınlanan: dosyadaki RET';
    paintScenario(res, scen);
    const noOffset = res.rows.filter((r) => typeof r.offset !== 'number').length;
    hint.textContent = (noOffset ? noOffset + ' vadenin tabana spread\'i yok (Şimdiki "—"): yazın ya da "Yayınlanandan al". ' : '')
      + 'Taban mid: RET\'in kendi tarihleri arası basit ACT/360 (spot ' + (res.spot ? isoToTr(res.spot) : '—') + '; ON spot\'tan önceki gün). '
      + 'VİOP mid: kontratların ima faizinin bid–ask ortası, vadeye tarihle doğrusal (kontratların arasında; dışında yok). '
      + 'Tabana göre: Bid ya da Ask seçilen vadede taban + spread + akış o kotayı belirler, diğeri genişlik kadar ötede.';
    paintWhere(res);
    paintFlows(res);
    paintAdmin(res);
    paintLog(res);
  }

  // ---------------------------------------------------------------- the user's scenario and the comparison
  function paintScenario(res, scen) {
    const list = res.scenarios || [{ code: MARKET, name: 'Piyasa (bootstrap)' }];
    if (scenSel.options.length !== list.length || [...scenSel.options].some((o, i) => o.value !== list[i].code || o.textContent !== list[i].name)) {
      clear(scenSel);
      for (const s of list) scenSel.appendChild(h('option', { value: s.code }, s.name));
    }
    if (document.activeElement !== scenSel) scenSel.value = res.scenario ? res.scenario.code : MARKET;
    scenLabel.textContent = 'Senaryo: ' + (res.scenario ? res.scenario.name : 'Piyasa (bootstrap)');
    scenLabel.classList.toggle('on', !!scen);
    scenNote.classList.toggle('hidden', !scen);
    scenNote.textContent = scen ? 'Senaryo ' + scen.name + ': OIS tabanı senaryonun eğrisinden (Masa\'nın "Tarih arası faiz"i RET\'in tarihleriyle), '
      + 'VİOP ve offshore tabanı piyasa + (senaryo − ima yol); spread, taban seçimi, genişlik ve akış masanın. Histerezis yok (5 bp ızgarası). '
      + 'Bu görünüm sizin: "Kopyala ve yayınla" gördüğünüzü yazar ve geçmişe hangi senaryodan olduğunu not eder.'
      + (res.scenario.why ? ' · ' + res.scenario.why : '') : '';
    // every tenor under the market and each scenario: bid / ask, and how far the bid is from the market's
    clear(scenHead);
    clear(scenBody);
    scenHead.appendChild(h('tr', null, h('th', { class: 'l' }, 'Vade'), h('th', null, 'Yayınlanan'),
      ...list.map((s) => { const th = h('th', { class: res.scenario && res.scenario.code === s.code ? 'cur' : '' }, s.name); th.dataset.scen = s.code; return th; })));
    for (const e of res.compare || []) {
      const base = e[MARKET];
      const tr = h('tr', null, h('td', { class: 'l' }, h('b', null, e.tenor)), h('td', { class: 'muted' }, pair(e.pub)));
      for (const s of list) {
        const x = e[s.code];
        const td = h('td', { class: (res.scenario && res.scenario.code === s.code ? 'cur' : '') + (x ? '' : ' muted') });
        td.dataset.tenor = e.tenor;
        td.dataset.scen = s.code;
        td.textContent = x ? pair(x) : '—';
        if (x && s.code !== MARKET && base && typeof base.bid === 'number') {
          const d = (x.bid - base.bid) * 10000;
          if (Math.abs(d) >= 0.05) td.appendChild(h('span', { class: 'retfair-scen-d ' + (d > 0 ? 'pos' : 'neg') }, ' ' + sbp(d)));
          td.title = s.name + ' − Piyasa: bid ' + sbp(d) + ' bp';
        } else if (!x) td.title = (e.why && e.why[s.code]) || '';
        tr.appendChild(td);
      }
      tr.dataset.tenor = e.tenor;
      scenBody.appendChild(tr);
    }
  }

  function paintWhere(res) {
    clear(whereBody);
    // the published side the rule sets: the bid (Bid, Mid) or the ask (Ask)
    const anyAsk = res.rows.some((r) => r.where_side === 'ask');
    wherePub.textContent = anyAsk ? 'Yayınlanan (bid / ask)' : 'Yayınlanan bid';
    for (const r of res.rows) {
      const side = r.where_side === 'ask' ? 'ask' : 'bid';
      const pv = r.pub[side];
      const cell = (b) => {
        const v = r.where[b];
        return h('td', { class: typeof v === 'number' ? (v > 0 ? 'pos' : v < 0 ? 'neg' : '') : 'muted', title: r.why[b] || '' },
          typeof v === 'number' ? ibp(v) + ' bp' : '—');
      };
      const wi = (b) => h('td', { class: r.base === b ? 'cur' : '' }, r.whatif && r.whatif[b] ? pair(r.whatif[b]) : '—');
      const tr = h('tr', null, h('td', { class: 'l' }, h('b', null, r.tenor)),
        h('td', null, (anyAsk ? side + ' ' : '') + (typeof pv === 'number' ? pct(pv) : '—')),
        cell('ois'), cell('viop'), cell('off'), wi('ois'), wi('viop'), wi('off'), wi('blend'));
      tr.dataset.tenor = r.tenor;
      tr.title = r.tenor + ' ' + side + ' ' + (typeof pv === 'number' ? pct(pv) : '—') + ': '
        + ['ois', 'viop', 'off'].map((b) => BASE_NAME[b] + '\'e ' + (typeof r.where[b] === 'number' ? ibp(r.where[b]) + ' bp' : '—')).join(' · ');
      whereBody.appendChild(tr);
    }
  }

  function paintFlows(res) {
    const f = res.flows || {};
    clear(flowHead);
    clear(flowBody);
    const n = f.lookback || 0;
    flowHead.appendChild(h('tr', null, h('th', { class: 'l' }, 'Vade'),
      h('th', { title: '+ net TRY sattık (vadeli USD alışı, RET bid\'inde) · − net TRY aldık (vadeli USD satışı, RET ask\'ında)' }, 'Bugün net (mn USD)'),
      h('th', { title: 'Bugünkü net tarafın işlemlerinin ağırlıklı ortalama TRY faizi' }, 'Ort. (maliyet) %'),
      h('th', { title: 'Önceki ' + n + ' iş gününde günlük net akışın ortalama büyüklüğü' }, 'Normal (mn)'), h('th', null, 'Kat'),
      h('th', null, 'Son ' + n + ' gün + bugün net (mn)'), h('th', null, 'Ort. %'),
      h('th', { title: 'RET\'in akışın işlendiği tarafı (TRY sattıkta bid, aldıkta ask) − maliyet' }, 'RET − maliyet (bp)'),
      h('th', null, 'OIS − maliyet'), h('th', null, 'VİOP − maliyet'), h('th', null, 'Off − maliyet')));
    const mn = (x) => (typeof x === 'number' ? (x > 0 ? '+' : x < 0 ? '−' : '') + num(Math.abs(x) / 1e6, 1) : '');
    for (const e of f.table || []) {
      const t = e.today || {}, w = e.window || {};
      const tr = h('tr', null, h('td', { class: 'l' }, h('b', null, e.tenor)),
        h('td', { class: typeof t.net === 'number' ? (t.net > 0 ? 'pos' : 'neg') : '' }, mn(t.net)),
        h('td', null, typeof t.cost === 'number' ? pct(t.cost) : ''), h('td', { class: 'muted' }, num(e.normal / 1e6, 1)),
        h('td', null, typeof e.ratio === 'number' ? num(e.ratio, 1) : (t.net ? 'yeni' : '')),
        h('td', null, mn(w.net)), h('td', null, typeof w.cost === 'number' ? pct(w.cost) : ''),
        h('td', null, typeof e.vs_ret === 'number' ? ibp(e.vs_ret) : ''),
        ...['ois', 'viop', 'off'].map((b) => h('td', { class: 'muted' }, e.vs && typeof e.vs[b] === 'number' ? ibp(e.vs[b]) : '')));
      tr.dataset.tenor = e.tenor;
      flowBody.appendChild(tr);
    }
    flowNote.textContent = (f.table && f.table.length ? '' : 'Bugün ve önceki ' + n + ' iş gününde TRY\'ye karşı forward yok. ')
      + 'Kaynak yalnızca Günlük İşlemler (Broker Chat ve BIST swap kotaları değil). Öneriler kendiliğinden uygulanmaz: "Kabul et" '
      + 'vadeye bir akış ayarı ekler.';
    clear(suggBox);
    for (const s of f.suggestions || []) {
      const b = h('button', { class: 'btn sm primary retfair-accept', type: 'button', title: 'Öneriyi akış ayarı olarak ekle (spread ve genişlik değişmez)' }, 'Kabul et');
      b.dataset.id = s.id;
      b.disabled = !s.ok;
      b.addEventListener('click', () => send('/api/ret/fair/flow', { accept: s.id }, 'Akış ayarı eklendi'));
      const card = h('div', { class: 'retfair-sugg' + (s.ok ? '' : ' blocked') }, h('span', { class: 'txt' }, s.text), s.ok ? b : null);
      card.dataset.id = s.id;
      suggBox.appendChild(card);
    }
  }

  function paintAdmin(res) {
    const s = res.settings || {};
    const can = !!res.admin;
    adminNote.textContent = (can ? 'Bu ayarlar masanın: değiştirdiğinizde herkes için geçerli olur ve geçmişe yazılır.'
      : 'Ekstra ayarları yalnızca yöneticiler değiştirebilir (görüntüleme).')
      + ((res.width_notes || []).length ? ' · İlk kurulumda 5 bp\'nin katı olmayan genişlikler yuvarlandı: ' + res.width_notes.join(', ') : '');
    const setVal = (inp, v) => { if (document.activeElement !== inp) inp.value = typeof v === 'number' ? num(v, Number.isInteger(v) ? 0 : 2, false) : ''; };
    setVal(hyst, s.hysteresis);
    setVal(sens, s.sensitivity);
    setVal(look, s.lookback);
    setVal(margin, s.margin);
    setVal(bO, (s.blend || {}).ois);
    setVal(bV, (s.blend || {}).viop);
    setVal(bF, (s.blend || {}).off);
    if (!widthGrid.children.length) {
      for (const r of res.rows) {
        const inp = h('input', { type: 'text', class: 'inp num retfair-width', autocomplete: 'off', style: { width: '52px' } });
        inp.dataset.tenor = r.tenor;
        widthInputs[r.tenor] = inp;
        widthGrid.appendChild(h('label', null, h('span', null, r.tenor), inp));
      }
    }
    for (const [t, inp] of Object.entries(widthInputs)) setVal(inp, (s.widths || {})[t]);
    for (const inp of [hyst, sens, look, margin, bO, bV, bF, ...Object.values(widthInputs)]) inp.disabled = !can;
    adminSave.disabled = !can;
  }

  function paintLog(res) {
    clear(logList);
    for (const x of res.log || []) {
      logList.appendChild(h('div', { class: 'retfair-logrow' }, h('span', { class: 'muted' }, x.ts + ' · ' + (x.user ? ctx.displayName(x.user) : 'sistem')), ' ', x.text));
    }
    if (!(res.log || []).length) logList.appendChild(h('div', { class: 'muted' }, 'Kayıt yok'));
  }

  // ---------------------------------------------------------------- "Kopyala ve yayınla"
  async function publish() {
    if (!data || publishBtn.disabled) return;
    // what is on the screen at the click: copied and published, the same numbers
    const curve = data.rows.map((r) => {
      const x = r.now || r.pub;
      return { tenor: r.tenor, days: r.days, bid: x.bid, ask: x.ask };
    }).filter((r) => typeof r.bid === 'number' && typeof r.ask === 'number');
    if (!curve.length) { toast('Yayınlanacak eğri yok', 'err'); return; }
    const kept = data.rows.filter((r) => !r.now).map((r) => r.tenor);
    publishBtn.disabled = true;
    // the clipboard first (the click is still the browser's gesture), then the desk's RET (after a change still on its way)
    const text = retText(curve.map((r) => ({ tenor: r.tenor, days: r.days, bid: num(r.bid * 100, 4, false), ask: num(r.ask * 100, 4, false) })), fmt, trDate());
    await copyText(text, 'Kopyalandı · yayınlanıyor…');
    const scen = data.scenario && data.scenario.code !== MARKET ? data.scenario.code : null;
    queue = queue.then(async () => {
      busy = true;
      try {
        const res = await api.post('/api/ret/fair/publish', { rows: curve.map((r) => ({ tenor: r.tenor, bid: r.bid, ask: r.ask })), scenario: scen });
        // which tenors moved against the RET published before, and by how much (bp)
        const moves = (res.moved || []).map((x) => x.tenor + ' ' + signedBp(x.bid) + ' / ' + signedBp(x.ask)).join(' · ');
        toast('RET yayınlandı ve kopyalandı' + (res.source ? ' (' + res.source + ')' : '') + ': ' + (moves || 'değişen vade yok')
          + ' (' + curve.length + ' vade' + (kept.length ? '; Şimdiki\'si olmayan ' + kept.join(', ') + ' yayınlanan değerinde' : '') + ')', 'ok', 7000);
        render(res);
        if (onPublished) onPublished();
        if (ctx.refreshNow) ctx.refreshNow();
      } catch (err) {
        errorToast(err);
        toast('Dikkat: eğri panoya kopyalandı ama yayınlanamadı', 'err', 7000);
      } finally { busy = false; publishBtn.disabled = false; }
    });
    return queue;
  }

  return {
    el,
    show() {
      visible = true;
      el.classList.remove('hidden');
      load();
      if (!timer) timer = setInterval(() => { if (visible && !document.hidden) load(); }, POLL_MS);
    },
    hide() {
      visible = false;
      el.classList.add('hidden');
    },
    destroy() {
      visible = false;
      if (timer) clearInterval(timer);
      timer = null;
    },
    reload: load,
  };
}
