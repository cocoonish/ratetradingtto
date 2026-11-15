// Bonds added to a list of a page by ISIN: typed / pasted, or picked from the desk's list of TRY government bonds.
import { api } from './api.js';
import { h, clear, modal, toast, errorToast, confirmDialog } from './ui.js';
import { isoToTr, num } from './format.js';

const KIND_ORDER = ['all', 'fixed', 'float', 'frn', 'cpi', 'bill', 'zero'];
const KIND_TEXT = { all: 'Tümü', fixed: 'Sabit', float: 'TLREF', frn: 'FRN', cpi: 'TÜFE', bill: 'Bono', zero: 'Kuponsuz' };

/**
 * ``opts``: {book, list (e.g. "DİBS RV!A5:A54"), name (the list's name in the catalog: dibs / asw / bulk; "evren":
 * Tüm Kâğıtlar, the desk's list itself), catalog (offer the TRY government bonds to pick from), title}.
 */
export async function openAddIsin(ctx, opts) {
  if (opts.name === 'evren') return openAddToList(ctx, opts);
  let cat = null;
  if (opts.catalog) {
    try { cat = await api.get('/api/bonds/catalog'); } catch (err) { errorToast(err); return; }
  }
  const m = modal({ title: opts.title || 'ISIN ile ekle', width: 860 });
  const text = h('textarea', { class: 'inp', id: 'isin-text', rows: '3', spellcheck: 'false',
    placeholder: 'ISIN yazın ya da yapıştırın (birkaç tane olabilir: boşluk, virgül ya da satırla ayırın) – örn. TRT150328T24' });
  m.body.appendChild(h('div', { class: 'field' }, h('label', null, 'ISIN'), text));
  const picked = new Set();
  let kind = 'all';
  const count = h('span', { class: 'muted', id: 'isin-count' });
  const update = () => {
    const typed = text.value.split(/[\s,;]+/).map((x) => x.trim().toUpperCase()).filter(Boolean);
    const n = new Set([...typed, ...picked]).size;
    count.textContent = n ? n + ' kâğıt eklenecek' : '';
    add.disabled = !n;
  };
  text.addEventListener('input', update);
  if (cat) {
    const find = h('input', { class: 'inp', type: 'search', id: 'isin-find', placeholder: 'Ara: 2028, 15.03, TRT13…', autocomplete: 'off' });
    const seg = h('div', { class: 'seg', id: 'isin-kind' });
    for (const k of KIND_ORDER) {
      if (k !== 'all' && !cat.bonds.some((b) => b.kind === k)) continue;
      const b = h('button', { type: 'button' }, KIND_TEXT[k]);
      b.dataset.v = k;
      b.classList.toggle('on', k === kind);
      b.addEventListener('click', () => { kind = k; for (const x of seg.children) x.classList.toggle('on', x === b); fill(); });
      seg.appendChild(b);
    }
    const table = h('table', { class: 'plain isins', id: 'isin-table' });
    const box = h('div', { class: 'isin-scroll' }, table);
    const fill = () => {
      const needle = find.value.trim().toUpperCase();
      clear(table).appendChild(h('tr', null, h('th', null, ''), h('th', { class: 'l' }, 'ISIN'), h('th', { class: 'l' }, 'Kâğıt'),
        h('th', { class: 'l' }, 'Tür'), h('th', null, 'Vade'), h('th', { class: 'l' }, 'Listede')));
      for (const b of cat.bonds) {
        if (kind !== 'all' && b.kind !== kind) continue;
        const hay = [b.isin, b.name, b.label, isoToTr(b.maturity), b.kind_text].join(' ').toUpperCase();
        if (needle && !hay.includes(needle)) continue;
        const inList = (b.lists || []).includes(opts.name);
        const cb = h('input', { type: 'checkbox', class: 'pick' });
        cb.checked = picked.has(b.isin) || inList;
        cb.disabled = inList;
        cb.addEventListener('change', () => { if (cb.checked) picked.add(b.isin); else picked.delete(b.isin); update(); });
        table.appendChild(h('tr', { class: inList ? 'have' : '' }, h('td', null, cb), h('td', { class: 'l mono' }, b.isin), h('td', { class: 'l' }, b.name),
          h('td', { class: 'l' }, b.kind_text), h('td', null, isoToTr(b.maturity)),
          h('td', { class: 'l muted' }, (b.lists || []).map((x) => ({ dibs: 'DİBS RV', asw: 'ASW', bulk: 'Bulk' }[x] || x)).join(', '))));
      }
    };
    find.addEventListener('input', fill);
    m.body.appendChild(h('div', { class: 'isin-tools' }, seg, find));
    m.body.appendChild(box);
    m.body.appendChild(h('p', { class: 'muted' }, 'Masanın Bloomberg listesindeki TRY devlet iç borçlanma senetleri (' + cat.bonds.length
      + ' kâğıt). İşaretlediğiniz ya da yazdığınız kâğıtlar listenin ilk boş satırlarına eklenir; listede olanlar atlanır.'));
    fill();
  }
  const add = h('button', { class: 'btn primary', type: 'button', id: 'isin-add', disabled: true }, 'Ekle');
  add.addEventListener('click', async () => {
    const typed = text.value.split(/[\s,;]+/).map((x) => x.trim().toUpperCase()).filter(Boolean);
    const values = [...new Set([...typed, ...picked])];
    if (!values.length) return;
    add.disabled = true;
    try {
      const res = await api.post('/api/list/add', { book: opts.book, list: opts.list, values });
      toast((res.added.length ? res.added.length + ' kâğıt eklendi' : 'Yeni kâğıt yok') + (res.skipped.length ? ' · ' + res.skipped.length + ' zaten listede' : '')
        + ' · ' + res.free + ' boş satır kaldı', 'ok', 4000);
      m.close();
      ctx.refreshNow();
    } catch (err) { errorToast(err); add.disabled = false; }
  });
  m.foot.appendChild(count);
  m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Vazgeç'));
  m.foot.appendChild(add);
  text.focus();
}

/** Bonds onto the desk's list (Tüm Kâğıtlar), for everyone: Bloomberg says what each is, and it goes into its group. */
async function openAddToList(ctx, opts) {
  const m = modal({ title: opts.title || 'Tüm Kâğıtlar\'a kâğıt ekle', width: 640 });
  const text = h('textarea', { class: 'inp', id: 'isin-text', rows: '3', spellcheck: 'false',
    placeholder: 'ISIN yazın ya da yapıştırın (birkaç tane olabilir: boşluk, virgül ya da satırla ayırın) – örn. TRT150328T24' });
  m.body.appendChild(h('div', { class: 'field' }, h('label', null, 'ISIN'), text));
  m.body.appendChild(h('p', { class: 'muted' }, 'Kâğıdın türü (bono, kuponsuz, sabit kuponlu, TLREF, FRN, TÜFE), vadesi ve kuponu '
    + 'Bloomberg\'den bulunur; kâğıt kendi grubuna, vadesine göre girer. Liste masanındır: herkes görür. Döviz cinsi kâğıt alınmaz.'));
  const add = h('button', { class: 'btn primary', type: 'button', id: 'isin-add', disabled: true }, 'Ekle');
  const codes = () => [...new Set(text.value.split(/[\s,;]+/).map((x) => x.trim().toUpperCase()).filter(Boolean))];
  text.addEventListener('input', () => { add.disabled = !codes().length; });
  add.addEventListener('click', async () => {
    const values = codes();
    if (!values.length) return;
    add.disabled = true;
    add.textContent = 'Bloomberg\'e soruluyor…';
    try {
      const res = await api.post('/api/bonds/list/add', { values });
      const parts = [];
      if (res.added.length) {
        parts.push(res.added.length + ' kâğıt eklendi: ' + res.added.map((b) => b.label + (b.kind_text ? ' (' + b.kind_text + ')' : '')).join(', '));
      }
      if (res.waiting.length) parts.push(res.waiting.length + ' kâğıdın türü Bloomberg\'den bekleniyor');
      if (res.skipped.length) parts.push(res.skipped.length + ' zaten listede');
      if (res.refused.length) parts.push('alınmadı: ' + res.refused.map((x) => x.isin + ' (' + x.text + ')').join(', '));
      toast(parts.join(' · ') || 'Yeni kâğıt yok', res.refused.length || res.waiting.length ? 'warn' : 'ok', res.refused.length ? 9000 : 5000);
      m.close();
      ctx.refreshNow();
    } catch (err) { errorToast(err); add.disabled = false; add.textContent = 'Ekle'; }
  });
  m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Vazgeç'));
  m.foot.appendChild(add);
  text.focus();
}

/** ✕ in Tüm Kâğıtlar: the bond off the desk's list, for everyone (and off the trading list when it is on it). */
async function unlist(ctx, td) {
  const code = ((td.title || '').match(/[A-Z]{2}[A-Z0-9]{9}\d/) || [])[0];
  if (!code) return;
  const row = td.closest('tr');
  const starred = !!(row && row.querySelector('td.flag.on'));
  const ok = await confirmDialog('Listeden çıkar', code + ' Tüm Kâğıtlar listesinden çıkarılsın mı? Liste masanındır: kâğıt herkesin '
    + 'listesinden kalkar' + (starred ? ' ve trading listesinden (DİBS RV, DİBS Trading) de çıkar.' : '.') + ' + ISIN ekle ile geri eklenebilir.', 'Çıkar', true);
  if (!ok) return;
  td.classList.add('busy');
  try {
    const res = await api.post('/api/bonds/list/remove', { isin: code });
    toast(res.removed ? code + ' listeden çıkarıldı' + (res.trading ? ' (trading listesinden de)' : '') : code + ' listede değil', 'ok');
    ctx.refreshNow();
  } catch (err) { errorToast(err); } finally { td.classList.remove('busy'); }
}

const SIDE = { ask: 'offer alındı', bid: "bid'e verildi" };
const EVENT_TEXT = { quote: 'Kota', trade: 'İşlem', ref: 'Ref', interest: 'İlgi', level: 'Seviye', note: 'Not' };

/** A bond's card: what it is, its prices on each value date with the last trades, the implied repo, its row of
 * DİBS RV and today's Broker Chat - everything the dashboard has on it, in one window. */
export async function openBondCard(ctx, isin) {
  let d;
  try { d = await api.get('/api/bond/' + encodeURIComponent(isin)); } catch (err) { errorToast(err); return; }
  const m = modal({ title: d.label + ' · ' + d.isin, width: 980 });
  m.box.classList.add('bondcard');
  const px = (v, unit) => (typeof v === 'number' ? num(v, unit === 'yld' ? 2 : 3, false) : '');
  const facts = [d.kind_text, d.kind === 'fixed' && typeof d.coupon === 'number' ? 'kupon %' + num(d.coupon, 2, false) : (d.name || ''),
    d.maturity ? 'vade ' + isoToTr(d.maturity) : '', typeof d.days === 'number' ? d.days + ' gün (' + num(d.years, 2, false) + ' yıl)' : '']
    .filter(Boolean).join(' · ');
  m.body.appendChild(h('p', { class: 'facts' }, facts || 'Masanın DİBS listesinde olmayan bir kâğıt'));
  const section = (title, el) => { m.body.appendChild(h('h3', null, title)); m.body.appendChild(el); };
  // ``left``: the columns of text (the others are numbers, right-aligned)
  const table = (heads, rows, cls, left = [0]) => {
    const t = h('table', { class: 'plain ' + (cls || '') });
    const side = (i) => (left.includes(i) ? 'l' : '');
    t.appendChild(h('tr', null, ...heads.map((x, i) => h('th', { class: side(i) }, x))));
    for (const r of rows) t.appendChild(h('tr', null, ...r.map((x, i) => (x instanceof Node ? x : h('td', { class: side(i) }, x == null ? '' : String(x))))));
    return t;
  };
  if (d.live && d.live.length) {
    // a bid / ask that is no live quote (no order stands: its size is empty) is "–", the reason and Bloomberg's figure in the tip
    const quote = (t, tip) => (t === '–' ? h('td', { class: 'soft', title: tip || null }, '–') : t);
    const rows = d.live.map((g) => [g.cap + ' · ' + g.src, g.date, g.bid_size, quote(g.bid, g.bid_tip), quote(g.ask, g.ask_tip), g.ask_size, g.last,
      g.seen ? h('td', { class: 'fresh', title: "Dashboard'un bu valörde işlem gördüğü an" }, 'bugün ' + g.seen) : g.when, g.vol]);
    if (d.extra && (d.extra.bid || d.extra.ask)) {
      rows.push(['Ek kaynak · ' + d.extra.src, '', d.extra.bid_size, quote(d.extra.bid, d.extra.bid_tip), quote(d.extra.ask, d.extra.ask_tip),
        d.extra.ask_size, '', '', '']);
    }
    section('Valörler (Bloomberg)', table(['Valör · kaynak', 'Tarih', 'Bid boyutu', 'Bid', 'Ask', 'Ask boyutu', 'Son işlem', 'Son işlem', 'Hacim'],
      rows, 'nums'));
    const repo = (d.repo || []).filter((x) => x.t);
    if (repo.length) m.body.appendChild(h('p', { class: 'muted' }, 'İma O/N repo: ' + repo.map((x) => x.name + ' ' + x.t).join(' · ')));
    if (d.repo_note) m.body.appendChild(h('p', { class: 'muted', id: 'card-repo-note' }, 'İma O/N repo: ' + d.repo_note));
  }
  if (d.board) {
    // the Broker Chat board's rules: the best fresh bid / offer; a stale one greyed, its broker and age beside it
    const imp = d.board.implied || {};
    const stale = d.board.stale || {};
    const tips = d.board.tips || {};
    const cell = (k, cls) => h('td', { class: (cls || '') + (stale[k] ? ' soft stale' : ''), title: tips[k] || null }, d.board[k] || '');
    section('Broker Chat · bugün', table(['', 'Bid', 'Ask', 'Son işlem', 'Kimde · yaş', 'Getiri (ima)'],
      [['Tahta', cell('bid'), cell('ask'), cell('last'), cell('who', 'l'),
        [imp.bid, imp.ask].some((v) => typeof v === 'number') ? px(imp.bid, 'yld') + ' / ' + px(imp.ask, 'yld') : px(imp.last, 'yld')]], 'nums', [0, 4]));
  }
  if (d.chat && d.chat.length) {
    // a quote that no longer stands (said again, withdrawn, traded away, before a reset) or is stale: greyed
    const STATE = { fresh: 'geçerli', stale: 'bayat', gone: 'geçmiş' };
    const TIP = { fresh: 'Tahtada duruyor', stale: 'Tahtada duruyor ama bayat: en iyi fiyat sayılmaz',
      gone: 'Artık durmuyor: sonra yeni kota, geri çekildi, işlem gördü ya da tahta sıfırlandı' };
    const t = table(['Saat', 'Kim', 'Mesaj', 'Olay', 'Bid', 'Ask', 'Fiyat', 'Durum'],
      d.chat.map((q) => [q.time, q.who, h('td', { class: 'l said', title: q.raw }, q.raw),
        (EVENT_TEXT[q.event] || q.event) + (q.event === 'trade' && SIDE[q.side] ? ' · ' + SIDE[q.side] : ''),
        px(q.bid, q.unit), px(q.ask, q.unit), px(q.price, q.unit),
        q.state ? h('td', { class: 'l', title: TIP[q.state] }, STATE[q.state] + (q.age ? ' · ' + q.age : '')) : '']), 'nums chat', [0, 1, 2, 3, 7]);
    d.chat.forEach((q, i) => { if (q.state === 'stale' || q.state === 'gone') t.rows[i + 1].classList.add('soft'); });
    m.body.appendChild(t);
  }
  if (d.tape && d.tape.length) {
    section('Bugünün işlemleri', table(['Saat', 'Fiyat', 'Getiri %', 'Taraf', 'Valör', 'Kim', 'Not'],
      d.tape.map((x) => [x.time, px(x.price, x.unit), px(x.yield, 'yld'), SIDE[x.side] || '', x.settle, x.who, x.note]), 'nums', [0, 3, 4, 5, 6]));
  }
  if (d.rv && d.rv.length) {
    const grid = h('div', { class: 'kv' });
    // ``soft``: worked out of a price that is no live quote (the tip says which)
    for (const x of d.rv) {
      grid.appendChild(h('div', null, h('span', { class: 'k' }, x.name),
        h('span', { class: 'v' + (x.c ? ' ' + x.c : '') + (x.soft ? ' soft' : ''), title: x.tip || null }, x.t)));
    }
    section('DİBS RV', grid);
  } else {
    m.body.appendChild(h('p', { class: 'muted' }, 'Kâğıt DİBS RV listesinde değil: getiri, ASW ve canlı valör fiyatları için listeye ekleyin.'));
  }
  if (!d.rv || !d.rv.length) {
    const add = h('button', { class: 'btn', type: 'button' }, 'DİBS RV listesine ekle');
    add.addEventListener('click', async () => {
      try {
        const res = await api.post('/api/list/add', { book: 'tto', list: 'DİBS RV!A5:A54', values: [d.isin] });
        toast(res.added.length ? 'Listeye eklendi' : 'Zaten listede', 'ok');
        m.close();
        ctx.refreshNow();
      } catch (err) { errorToast(err); }
    });
    m.foot.appendChild(add);
  }
  m.foot.appendChild(h('button', { class: 'btn primary', type: 'button', onclick: () => m.close() }, 'Kapat'));
}

/** ▸ in a table of bonds opens the card of the bond of its row (the ISIN is in the cell's tip). */
export function bondCardLinks(ctx, el) {
  el.addEventListener('click', (e) => {
    const td = e.target.closest('td.cardlink');
    if (!td) return;
    const code = ((td.title || '').match(/[A-Z]{2}[A-Z0-9]{9}\d/) || [])[0];
    if (code) openBondCard(ctx, code);
  });
}

/** ☆ / ★ in a table of bonds: onto / off the trading list (DİBS RV and DİBS Trading), for everyone; ✕ (Tüm Kâğıtlar):
 * off the desk's list. */
export function bondFlags(ctx, el) {
  el.addEventListener('click', async (e) => {
    const off = e.target.closest('td.unlist');
    if (off) {
      if (!off.classList.contains('busy')) unlist(ctx, off).catch(errorToast);
      return;
    }
    const td = e.target.closest('td.flag');
    if (!td || td.classList.contains('busy')) return;
    const code = ((td.title || '').match(/[A-Z]{2}[A-Z0-9]{9}\d/) || [])[0];
    if (!code) return;
    const on = !td.classList.contains('on');
    td.classList.add('busy');
    try {
      const res = await api.post('/api/bonds/flag', { isin: code, on });
      toast(on ? (res.added ? code + ' trading listesine eklendi' : code + ' zaten listede') : code + ' trading listesinden çıkarıldı', 'ok');
      ctx.refreshNow();
    } catch (err) { errorToast(err); } finally { td.classList.remove('busy'); }
  });
}
