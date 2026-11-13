// RET faizleri: the desk's TRY RET bid / ask curve.  Typed or pasted from Excel, stored on the server
// (shared by everyone, kept across restarts) with a history of every upload.
import { api } from './api.js';
import { h, clear, modal, toast, errorToast, copyText } from './ui.js';
import { num, raw, parseNumber } from './format.js';

const ALIASES = { 'O/N': 'ON', 'T/N': 'TN', '12M': '1Y', '24M': '2Y', '1.5Y': '18M', '1,5Y': '18M', '1H': '1W', '2H': '2W', '3H': '3W',
  '1A': '1M', '2A': '2M', '3A': '3M', '4A': '4M', '5A': '5M', '6A': '6M', '9A': '9M', '18A': '18M' };

function tenorKey(text) {
  const t = String(text || '').toUpperCase().replace(/\s+/g, '');
  return ALIASES[t] || t;
}

function shown(v) {
  return typeof v === 'number' ? raw(Number((v * 100).toPrecision(12))) : '';
}

/** A typed rate as percent: 34,45 and 0,3445 are the same rate. */
function percent(text) {
  const x = parseNumber(text, true);
  if (x === null) return null;
  return Math.abs(x) < 1 ? x * 100 : x;
}

/**
 * The curve as text to send: ``rows`` = [{tenor, days, bid, ask}] with bid / ask as typed.
 * 'table' is tab separated (Excel takes it as cells), 'message' is lined up for a chat window.
 */
export function retText(rows, kind, date) {
  const fmt = (t) => { const x = percent(t); return x === null ? '' : num(x, 2, false); };
  const filled = rows.filter((r) => fmt(r.bid) || fmt(r.ask));
  if (kind === 'table') {
    return ['Vade\tGün\tBid\tAsk'].concat(filled.map((r) => [r.tenor, typeof r.days === 'number' ? String(r.days) : '', fmt(r.bid), fmt(r.ask)].join('\t')))
      .join('\r\n');
  }
  const w = Math.max(...filled.map((r) => r.tenor.length), 2);
  return ['TRY RET' + (date ? ' · ' + date : '')].concat(filled.map((r) => r.tenor.padEnd(w + 2) + fmt(r.bid) + ' / ' + fmt(r.ask))).join('\n');
}

/**
 * Clipboard text -> [{tenor?, bid, ask}] rows.  Accepts "tenor ⇥ bid ⇥ ask", "tenor ⇥ gün ⇥ bid ⇥ ask",
 * plain "bid ⇥ ask" columns (assigned in order from the focused row) and a single column of mids.
 */
export function parseRetClipboard(text, tenors) {
  const lines = text.replace(/\r\n/g, '\n').replace(/\r/g, '\n').split('\n').filter((l) => l.trim() !== '');
  const out = [];
  for (const line of lines) {
    const parts = line.split('\t').map((x) => x.trim());
    let tenor = null;
    const nums = [];
    for (const part of parts) {
      if (tenor === null && tenors.includes(tenorKey(part))) { tenor = tenorKey(part); continue; }
      const x = parseNumber(part, true);
      if (x !== null) nums.push(part);
    }
    if (!nums.length) continue;                      // header line or text
    const bid = nums.length >= 2 ? nums[nums.length - 2] : nums[0];
    const ask = nums.length >= 2 ? nums[nums.length - 1] : nums[0];
    out.push({ tenor, bid, ask });
  }
  return out;
}

/**
 * The curve after a shift.  ``rows`` = [{tenor, bid, ask}] as typed, ``shifts`` = {tenor: bp}, ``sides`` = which of
 * 'bid' / 'ask' move.  A tenor without a shift keeps what it has - that is how some maturities are held while the
 * others move.  Returns [{tenor, bid, ask, moved}] with bid / ask as text in percent.
 */
export function shiftedRows(rows, shifts, sides) {
  return rows.map((r) => {
    const bp = shifts && typeof shifts[r.tenor] === 'number' ? shifts[r.tenor] : 0;
    const out = { tenor: r.tenor, bid: r.bid, ask: r.ask, moved: false };
    if (!bp) return out;
    for (const k of sides) {
      const x = percent(r[k]);
      if (x === null) continue;
      out[k] = raw(Number((x + bp / 100).toPrecision(12)));
      out.moved = true;
    }
    return out;
  });
}

export async function openRetEditor(ctx) {
  let data;
  try { data = await api.get('/api/ret'); } catch (err) { errorToast(err); return; }
  const tenors = data.rows.map((r) => r.tenor);
  const m = modal({ title: 'RET faizleri (TRY RET bid / ask)', width: 1040 });
  const inputs = {};                 // tenor -> {bid, ask, bp}
  const mids = {}, news = {}, lines = {}, spreads = {};
  const before = {};                 // tenor -> spread (bp) of the curve as it was opened (or last saved)
  const meta = h('div', { class: 'muted' });
  const setMeta = (mt) => {
    meta.textContent = mt && mt.updated_at ? 'Son güncelleme: ' + mt.updated_at + (mt.updated_by ? ' · ' + (ctx.displayName(mt.updated_by)) : '')
      : 'Henüz yükleme yapılmadı – dosyadaki değerler kullanılıyor';
  };
  setMeta(data.meta);
  const table = h('table', { class: 'plain ret' });
  table.appendChild(h('thead', null, h('tr', null, h('th', { class: 'l' }, 'Vade'), h('th', null, 'Gün'), h('th', null, 'Bid (%)'), h('th', null, 'Ask (%)'),
    h('th', null, 'Mid (%)'), h('th', { title: 'Ask − bid, baz puan: önce kayıtlı eğrinin, ok işaretinden sonra kutulardakinin (değiştirdiyseniz)' }, 'Spread (bp)'),
    h('th', { title: 'Bu vade kaç baz puan kayacak. "Tümünü kaydır" hepsini doldurur; bir vadeyi sabit tutmak için kutusunu silin ya da 0 yazın.' }, 'Kaydır (bp)'),
    h('th', { class: 'l' }, 'Yeni bid / ask'))));
  const tbody = h('tbody');
  const spreadOf = (bidText, askText) => {
    const b = percent(bidText), a = percent(askText);
    return b !== null && a !== null ? Math.round((a - b) * 100 * 10) / 10 : null;
  };
  const bpText = (x) => (x === null ? '—' : num(x, Math.abs(x - Math.round(x)) > 1e-9 ? 1 : 0, false));
  const updateSpread = (t) => {
    const now = spreadOf(inputs[t].bid.value, inputs[t].ask.value);
    const was = before[t] === undefined ? null : before[t];
    const el = clear(spreads[t]);
    if (was === now || (was !== null && now !== null && Math.abs(was - now) < 0.05)) {
      el.className = 'muted';
      el.textContent = now === null ? '' : bpText(now);
      return;
    }
    el.className = 'ret-spread changed';
    el.appendChild(h('span', { class: 'muted' }, bpText(was)));
    el.appendChild(document.createTextNode(' → '));
    el.appendChild(h('b', null, bpText(now)));
  };
  const updateMid = (t) => {
    const b = percent(inputs[t].bid.value), a = percent(inputs[t].ask.value);
    mids[t].textContent = b !== null && a !== null ? num((b + a) / 2, 3, false) : '';
    updateSpread(t);
  };

  // ---- shifting: every maturity shows by how much it will move; a maturity typed (or blanked) by hand is left alone
  //      by "Tümünü kaydır", which is how some are held while the rest moves
  let sides = ['bid', 'ask'];
  const own = new Set();
  const rowOf = (t) => ({ tenor: t, bid: inputs[t].bid.value.trim(), ask: inputs[t].ask.value.trim() });
  const bpOf = (t) => { const x = parseNumber(inputs[t].bp.value, true); return x === null ? 0 : x; };
  const preview = (t) => {
    const bp = bpOf(t);
    const el = news[t];
    clear(el);
    lines[t].classList.toggle('own', own.has(t));
    lines[t].classList.toggle('moved', bp !== 0);
    if (!bp) { el.className = 'l ret-new muted'; el.textContent = own.has(t) ? 'sabit' : ''; return; }
    const out = shiftedRows([rowOf(t)], { [t]: bp }, sides)[0];
    el.className = 'l ret-new';
    el.appendChild(h('span', { class: sides.includes('bid') ? 'chg' : '' }, out.bid || '—'));
    el.appendChild(document.createTextNode(' / '));
    el.appendChild(h('span', { class: sides.includes('ask') ? 'chg' : '' }, out.ask || '—'));
    if (sides.length === 1) {
      // one side moves: the spread changes with it
      const sp = spreadOf(out.bid, out.ask);
      el.appendChild(h('span', { class: 'muted' }, ' · spread ' + bpText(sp)));
    }
  };
  const pending = () => tenors.filter((t) => bpOf(t) !== 0);
  const fillRows = (rows) => {
    for (const r of rows) {
      const t = tenorKey(r.tenor);
      if (!inputs[t]) continue;
      inputs[t].bid.value = typeof r.bid === 'number' ? shown(r.bid) : (r.bid || '');
      inputs[t].ask.value = typeof r.ask === 'number' ? shown(r.ask) : (r.ask || '');
      updateMid(t);
      preview(t);
    }
  };
  for (const r of data.rows) {
    const t = r.tenor;
    const bid = h('input', { type: 'text', class: 'inp num', autocomplete: 'off' });
    const ask = h('input', { type: 'text', class: 'inp num', autocomplete: 'off' });
    const bp = h('input', { type: 'text', class: 'inp num ret-bp', autocomplete: 'off', placeholder: '—' });
    bid.dataset.tenor = t;
    ask.dataset.tenor = t;
    bp.dataset.tenor = t;
    inputs[t] = { bid, ask, bp };
    mids[t] = h('td', { class: 'muted' });
    spreads[t] = h('td', { class: 'muted' });
    spreads[t].dataset.tenor = t;
    news[t] = h('td', { class: 'l ret-new muted' });
    news[t].dataset.tenor = t;
    bid.addEventListener('input', () => { updateMid(t); preview(t); });
    ask.addEventListener('input', () => { updateMid(t); preview(t); });
    bp.addEventListener('input', () => { own.add(t); preview(t); showPending(); });
    lines[t] = h('tr', null, h('td', { class: 'l' }, h('b', null, t)), h('td', { class: 'muted' }, typeof r.days === 'number' ? num(r.days, 0) : ''),
      h('td', null, bid), h('td', null, ask), mids[t], spreads[t], h('td', null, bp), news[t]);
    tbody.appendChild(lines[t]);
  }
  table.appendChild(tbody);

  const onPaste = (e) => {
    const text = (e.clipboardData || window.clipboardData).getData('text/plain');
    if (!text || (!text.includes('\t') && !text.includes('\n'))) return;        // a single value: normal paste
    e.preventDefault();
    const rows = parseRetClipboard(text, tenors);
    if (!rows.length) { toast('Yapıştırılan metinde RET faizi bulunamadı', 'err'); return; }
    const labelled = rows.some((r) => r.tenor);
    let start = 0;
    const focusTenor = e.target && e.target.dataset ? e.target.dataset.tenor : null;
    if (!labelled && focusTenor) start = Math.max(0, tenors.indexOf(focusTenor));
    let k = 0, n = 0;
    for (const r of rows) {
      const t = r.tenor || tenors[start + k];
      if (!r.tenor) k += 1;
      if (!t || !inputs[t]) continue;
      inputs[t].bid.value = r.bid;
      inputs[t].ask.value = r.ask;
      updateMid(t);
      preview(t);
      n += 1;
    }
    toast(n + ' vade yapıştırıldı – kontrol edip "Kaydet"e basın', 'ok', 3200);
  };
  m.box.addEventListener('paste', onPaste);

  const current = () => data.rows.map((r) => ({ tenor: r.tenor, days: r.days, bid: inputs[r.tenor].bid.value.trim(), ask: inputs[r.tenor].ask.value.trim() }));
  let saved = '';
  const shiftInp = h('input', { type: 'text', class: 'inp num', id: 'ret-shift', placeholder: 'bp, örn. 25 ya da -50', autocomplete: 'off', style: { width: '128px' } });
  const pendingNote = h('span', { class: 'muted', id: 'ret-pending' });
  const applyBtn = h('button', { class: 'btn sm primary', type: 'button', id: 'ret-shift-apply',
    title: 'Önizlemedeki kaydırmayı bid / ask kutularına yaz (sonra "Kaydet")' }, 'Uygula');
  const clearBtn = h('button', { class: 'btn sm', type: 'button', id: 'ret-shift-clear', title: 'Kaydırmayı ve elle tutulan vadeleri temizle' }, 'Temizle');
  const showPending = () => {
    const n = pending().length;
    const held = tenors.filter((t) => own.has(t) && bpOf(t) === 0).length;
    applyBtn.disabled = !n;
    pendingNote.textContent = n ? n + ' vade kayacak' + (held ? ' · ' + held + ' vade sabit' : '') : (held ? held + ' vade sabit' : '');
  };
  const fillAll = () => {
    const bp = parseNumber(shiftInp.value, true);
    for (const t of tenors) {
      if (own.has(t)) continue;                      // typed in its own row: "Tümünü kaydır" does not touch it
      inputs[t].bp.value = bp !== null && bp !== 0 ? raw(bp) : '';
      preview(t);
    }
    showPending();
  };
  const clearShift = () => {
    shiftInp.value = '';
    own.clear();
    for (const t of tenors) { inputs[t].bp.value = ''; preview(t); }
    showPending();
  };
  const apply = () => {
    const shifts = {};
    for (const t of pending()) shifts[t] = bpOf(t);
    if (!Object.keys(shifts).length) { toast('Kaydırma miktarını baz puan olarak yazın (örn. 25 ya da -50)', 'err'); shiftInp.focus(); return; }
    let moved = 0, kept = 0;
    for (const r of shiftedRows(tenors.map(rowOf), shifts, sides)) {
      if (!r.moved) { if (r.bid || r.ask) kept += 1; continue; }
      inputs[r.tenor].bid.value = r.bid;
      inputs[r.tenor].ask.value = r.ask;
      updateMid(r.tenor);
      moved += 1;
    }
    clearShift();
    toast(moved + ' vade kaydırıldı' + (kept ? ', ' + kept + ' vade sabit kaldı' : '') + ' – uygulamak için "Kaydet"e basın', 'ok', 4200);
  };
  shiftInp.addEventListener('input', fillAll);
  shiftInp.addEventListener('keydown', (e) => { if (e.key === 'Enter') apply(); });
  applyBtn.addEventListener('click', apply);
  clearBtn.addEventListener('click', clearShift);
  const sideSeg = h('div', { class: 'seg' });
  for (const [id, label, which] of [['ret-side-both', 'Bid + Ask', ['bid', 'ask']], ['ret-side-bid', 'Bid', ['bid']], ['ret-side-ask', 'Ask', ['ask']]]) {
    const b = h('button', { type: 'button', id, class: which.length === 2 ? 'on' : '' }, label);
    b.addEventListener('click', () => {
      sides = which;
      for (const x of sideSeg.children) x.classList.toggle('on', x === b);
      for (const t of tenors) preview(t);
    });
    sideSeg.appendChild(b);
  }
  const copyBtn = (label, kind, id, title) => {
    const b = h('button', { class: 'btn sm', type: 'button', id, title }, label);
    b.addEventListener('click', () => {
      const today = new Date();
      const date = String(today.getDate()).padStart(2, '0') + '.' + String(today.getMonth() + 1).padStart(2, '0') + '.' + today.getFullYear();
      const note = pending().length ? 'Kopyalandı – dikkat: önizlemedeki kaydırma uygulanmadı (kutulardaki değerler kopyalandı)'
        : (JSON.stringify(current()) !== saved ? 'Kopyalandı – dikkat: tablodaki değerler henüz kaydedilmedi' : 'RET faizleri kopyalandı');
      copyText(retText(current(), kind, date), note);
    });
    return b;
  };
  const tools = h('div', { class: 'ret-tools' },
    h('span', { class: 'muted' }, 'Tümünü kaydır'), shiftInp, sideSeg, applyBtn, clearBtn, pendingNote, h('span', { class: 'grow' }),
    copyBtn('Kopyala (tablo)', 'table', 'ret-copy', 'Vade · gün · bid · ask: Excel\'e ya da e-postaya yapıştırılabilir tablo'),
    copyBtn('Kopyala (mesaj)', 'message', 'ret-copy-msg', 'Sohbet penceresine atılacak hizalı metin: "1M   34,45 / 34,65"'));

  // the spreads of the curve as it stands: what a change is shown against ("önceki → şimdi")
  const markSaved = () => { for (const t of tenors) { before[t] = spreadOf(inputs[t].bid.value, inputs[t].ask.value); updateSpread(t); } };
  fillRows(data.rows);
  markSaved();
  saved = JSON.stringify(current());
  showPending();

  const hist = h('div', { class: 'ret-hist' });
  const loadHistory = async () => {
    try {
      const res = await api.get('/api/ret/history');
      clear(hist);
      hist.appendChild(h('div', { class: 'field' }, h('label', null, 'Yükleme geçmişi')));
      if (!res.history.length) { hist.appendChild(h('div', { class: 'muted' }, 'Kayıt yok')); return; }
      for (const x of res.history) {
        const b = h('button', { class: 'btn sm', type: 'button', title: 'Bu kaydın değerlerini tabloya getir' },
          x.ts + (x.user ? ' · ' + ctx.displayName(x.user) : ''));
        b.addEventListener('click', () => { fillRows(x.rows); toast('Değerler tabloya getirildi – uygulamak için "Kaydet"e basın', '', 3200); });
        hist.appendChild(b);
      }
    } catch (err) { /* history is optional */ }
  };
  loadHistory();

  m.body.appendChild(h('p', { class: 'muted', style: { margin: '0 0 10px' } },
    'Excel\'de RET tablosunu (yalnızca bid–ask sütunları ya da vade etiketiyle birlikte) kopyalayın, aşağıdaki tabloda bir kutuya tıklayıp Ctrl+V ile yapıştırın. ',
    'Değerler yüzde (34,45) ya da oran (0,3445) olabilir. Kaydırma: "Tümünü kaydır"a baz puanı yazın – her vadenin yanında ne kadar kayacağı ve yeni ',
    'bid / ask görünür; sabit kalacak vadelerin "Kaydır" kutusunu silin (ya da farklı bir miktar yazın), sonra "Uygula". ',
    'Kaydedilen eğri tüm kullanıcılar için geçerlidir ve sunucu yeniden başlasa da saklanır.'));
  m.body.appendChild(tools);
  m.body.appendChild(h('div', { class: 'ret-layout' }, h('div', null, table, meta), hist));
  const save = h('button', { class: 'btn primary', type: 'button' }, 'Kaydet');
  save.addEventListener('click', async () => {
    if (pending().length) {
      toast('Önizlemedeki kaydırma henüz uygulanmadı: önce "Uygula"ya basın (ya da "Temizle")', 'err', 5000);
      return;
    }
    const rows = [];
    for (const t of tenors) {
      const bid = inputs[t].bid.value.trim(), ask = inputs[t].ask.value.trim();
      if (bid || ask) rows.push({ tenor: t, bid, ask });
    }
    save.disabled = true;
    try {
      const res = await api.post('/api/ret', { rows });
      if (res.errors && res.errors.length) toast(res.errors.join('; '), 'err', 7000);
      else toast('RET faizleri kaydedildi (' + res.applied + ' hücre)', 'ok');
      fillRows(res.ret.rows);
      markSaved();
      saved = JSON.stringify(current());
      setMeta(res.ret.meta);
      loadHistory();
      ctx.refreshNow();
    } catch (err) { errorToast(err); } finally { save.disabled = false; }
  });
  m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Kapat'));
  m.foot.appendChild(save);
  const first = inputs[tenors[0]];
  if (first) first.bid.focus();
}
