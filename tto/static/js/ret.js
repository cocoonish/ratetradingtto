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

export async function openRetEditor(ctx) {
  let data;
  try { data = await api.get('/api/ret'); } catch (err) { errorToast(err); return; }
  const tenors = data.rows.map((r) => r.tenor);
  const m = modal({ title: 'RET faizleri (TRY RET bid / ask)', width: 760 });
  const inputs = {};
  const meta = h('div', { class: 'muted' });
  const setMeta = (mt) => {
    meta.textContent = mt && mt.updated_at ? 'Son güncelleme: ' + mt.updated_at + (mt.updated_by ? ' · ' + (ctx.displayName(mt.updated_by)) : '')
      : 'Henüz yükleme yapılmadı – dosyadaki değerler kullanılıyor';
  };
  setMeta(data.meta);
  const table = h('table', { class: 'plain ret' });
  table.appendChild(h('thead', null, h('tr', null, h('th', { class: 'l' }, 'Vade'), h('th', null, 'Gün'), h('th', null, 'Bid (%)'), h('th', null, 'Ask (%)'),
    h('th', null, 'Mid (%)'))));
  const tbody = h('tbody');
  const mids = {};
  const updateMid = (t) => {
    const b = parseNumber(inputs[t].bid.value, true), a = parseNumber(inputs[t].ask.value, true);
    const pc = (x) => (Math.abs(x) < 1 ? x * 100 : x);
    mids[t].textContent = b !== null && a !== null ? num((pc(b) + pc(a)) / 2, 3, false) : '';
  };
  const fillRows = (rows) => {
    for (const r of rows) {
      const t = tenorKey(r.tenor);
      if (!inputs[t]) continue;
      inputs[t].bid.value = typeof r.bid === 'number' ? shown(r.bid) : (r.bid || '');
      inputs[t].ask.value = typeof r.ask === 'number' ? shown(r.ask) : (r.ask || '');
      updateMid(t);
    }
  };
  for (const r of data.rows) {
    const bid = h('input', { type: 'text', class: 'inp num', autocomplete: 'off' });
    const ask = h('input', { type: 'text', class: 'inp num', autocomplete: 'off' });
    bid.dataset.tenor = r.tenor;
    ask.dataset.tenor = r.tenor;
    inputs[r.tenor] = { bid, ask };
    mids[r.tenor] = h('td', { class: 'muted' });
    bid.addEventListener('input', () => updateMid(r.tenor));
    ask.addEventListener('input', () => updateMid(r.tenor));
    tbody.appendChild(h('tr', null, h('td', { class: 'l' }, h('b', null, r.tenor)), h('td', { class: 'muted' }, typeof r.days === 'number' ? num(r.days, 0) : ''),
      h('td', null, bid), h('td', null, ask), mids[r.tenor]));
  }
  table.appendChild(tbody);
  fillRows(data.rows);

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
      n += 1;
    }
    toast(n + ' vade yapıştırıldı – kontrol edip "Kaydet"e basın', 'ok', 3200);
  };
  m.box.addEventListener('paste', onPaste);

  // ---- change the whole curve at once, and take it along
  const current = () => data.rows.map((r) => ({ tenor: r.tenor, days: r.days, bid: inputs[r.tenor].bid.value.trim(), ask: inputs[r.tenor].ask.value.trim() }));
  let saved = JSON.stringify(current());
  const shiftInp = h('input', { type: 'text', class: 'inp num', id: 'ret-shift', placeholder: 'bp, örn. 25 ya da -50', autocomplete: 'off', style: { width: '150px' } });
  const shift = (sides) => {
    const bp = parseNumber(shiftInp.value, true);
    if (bp === null || bp === 0) { toast('Kaydırma miktarını baz puan olarak yazın (örn. 25 ya da -50)', 'err'); shiftInp.focus(); return; }
    let n = 0;
    for (const t of tenors) {
      for (const k of sides) {
        const x = percent(inputs[t][k].value);
        if (x === null) continue;
        inputs[t][k].value = raw(Number((x + bp / 100).toPrecision(12)));
        n += 1;
      }
      updateMid(t);
    }
    toast(n + ' faiz ' + (bp > 0 ? '+' : '') + raw(bp) + ' bp kaydırıldı – uygulamak için "Kaydet"e basın', 'ok', 3600);
  };
  const shiftBtn = (label, sides, id) => {
    const b = h('button', { class: 'btn sm', type: 'button', id }, label);
    b.addEventListener('click', () => shift(sides));
    return b;
  };
  const copyBtn = (label, kind, id, title) => {
    const b = h('button', { class: 'btn sm', type: 'button', id, title }, label);
    b.addEventListener('click', () => {
      const today = new Date();
      const date = String(today.getDate()).padStart(2, '0') + '.' + String(today.getMonth() + 1).padStart(2, '0') + '.' + today.getFullYear();
      const unsaved = JSON.stringify(current()) !== saved;
      copyText(retText(current(), kind, date), unsaved ? 'Kopyalandı – dikkat: tablodaki değerler henüz kaydedilmedi' : 'RET faizleri kopyalandı');
    });
    return b;
  };
  const tools = h('div', { class: 'ret-tools' },
    h('span', { class: 'muted' }, 'Tümünü kaydır'), shiftInp, shiftBtn('Bid + Ask', ['bid', 'ask'], 'ret-shift-both'), shiftBtn('Bid', ['bid'], 'ret-shift-bid'),
    shiftBtn('Ask', ['ask'], 'ret-shift-ask'), h('span', { class: 'grow' }),
    copyBtn('Kopyala (tablo)', 'table', 'ret-copy', 'Vade · gün · bid · ask: Excel\'e ya da e-postaya yapıştırılabilir tablo'),
    copyBtn('Kopyala (mesaj)', 'message', 'ret-copy-msg', 'Sohbet penceresine atılacak hizalı metin: "1M   34,45 / 34,65"'));
  shiftInp.addEventListener('keydown', (e) => { if (e.key === 'Enter') shift(['bid', 'ask']); });

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
    'Değerler yüzde (34,45) ya da oran (0,3445) olabilir. Tek tek değiştirebilir ya da tüm eğriyi baz puanla kaydırabilirsiniz. ',
    'Kaydedilen eğri tüm kullanıcılar için geçerlidir ve sunucu yeniden başlasa da saklanır.'));
  m.body.appendChild(tools);
  m.body.appendChild(h('div', { class: 'ret-layout' }, h('div', null, table, meta), hist));
  const save = h('button', { class: 'btn primary', type: 'button' }, 'Kaydet');
  save.addEventListener('click', async () => {
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
