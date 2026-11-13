// What stands behind the badge of the top bar: where the market data comes from, how the Bloomberg session is
// doing - and which tickers Bloomberg says it does not know, with the cells of the workbooks that ask for them.
import { api } from './api.js';
import { h, clear, modal, toast, errorToast, copyText } from './ui.js';
import { Grid, plainData, copyGrid } from './grid.js';
import { num } from './format.js';

function line(label, value, cls) {
  return h('div', { class: 'stline' + (cls ? ' ' + cls : '') }, h('span', { class: 'l' }, label), h('span', { class: 'v' }, value));
}

function clock(t) {
  if (!t) return '—';
  const d = new Date(t * 1000);
  return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0') + ':' + String(d.getSeconds()).padStart(2, '0');
}

/** A link to where a cell is shown: its page and table, or the sheet explorer when no page shows it. */
function cellLink(c, close) {
  const text = c.sheet + '!' + c.ref;
  const a = h('a', { href: c.page ? '#/' + c.page + (c.panel ? '?p=' + encodeURIComponent(c.panel) : '') : '#/explorer', title: c.book_title + ' · ' + text }, text);
  a.addEventListener('click', () => {
    if (!c.page) {
      try { sessionStorage.setItem('tto.explorer', JSON.stringify({ book: c.book, sheet: c.sheet, range: c.ref })); } catch (e) { /* ignore */ }
    }
    close();
  });
  return a;
}

export async function openStatus(status) {
  const st = status || {};
  const p = st.provider || {};
  const m = modal({ title: 'Veri kaynağı', width: 1100 });
  m.box.classList.add('statusbox');
  const head = h('div', { class: 'stgrid' });
  if (st.mode === 'live') {
    head.appendChild(line('Bağlantı', p.connected === false ? 'YOK – yeniden bağlanılıyor' : 'Bloomberg ' + (p.host || ''), p.connected === false ? 'bad' : ''));
    head.appendChild(line('Abonelik', num(p.subscriptions || 0, 0) + (p.subscriptions_failed ? ' · ' + p.subscriptions_failed + ' başarısız' : '')));
    head.appendChild(line('Bloomberg\'in tanımadığı', num(p.subscriptions_invalid || 0, 0) + ' ticker (abone olunmadı)', p.subscriptions_invalid ? 'warn' : ''));
    head.appendChild(line('Bekleyen veri', num(p.pending || 0, 0)));
    head.appendChild(line('Bugünkü veri isteği', num(p.hits_today || 0, 0) + (p.limit_reached ? ' · GÜNLÜK LİMİT KORUMASI' : ''), p.limit_reached ? 'bad' : ''));
    head.appendChild(line('Tick', num(p.ticks || 0, 0) + ' · son ' + clock(p.last_tick)));
    head.appendChild(line('Oturum', p.isolated ? 'ayrı süreçte' + (p.restarts ? ' (' + p.restarts + ' kez yeniden başladı)' : '') : 'dashboard sürecinde'));
    if (p.events_dropped || p.messages_lost) head.appendChild(line('Kuyruk', (p.events_dropped || p.messages_lost) + ' olay düştü, ' + (p.resyncs || 0) + ' değer yeniden istendi', 'warn'));
    if (p.error) head.appendChild(line('Son hata', p.error, 'bad'));
  } else {
    head.appendChild(line('Veri', 'Kayıtlı veri (Excel dosyalarındaki son piyasa verisi)'));
    if (st.note) head.appendChild(line('Not', st.note, 'warn'));
  }
  m.body.appendChild(head);

  const box = h('div', { class: 'unknown' }, h('div', { class: 'loading' }, 'Bloomberg\'in tanımadıkları yükleniyor…'));
  m.body.appendChild(box);
  const dl = h('button', { class: 'btn', type: 'button', id: 'unknown-export', title: 'Gruplar ve bütün liste, hangi hücrenin istediğiyle (.xlsx)' }, 'Excel (.xlsx)');
  dl.addEventListener('click', async () => {
    dl.disabled = true;
    try {
      const res = await api.download('/api/market/unknown/export', {}, 'Bloomberg_tanimsiz.xlsx');
      toast(res.name + ' indirildi', 'ok', 3200);
    } catch (err) { errorToast(err); } finally { dl.disabled = false; }
  });
  const cp = h('button', { class: 'btn', type: 'button', id: 'unknown-copy' }, 'Listeyi kopyala');
  m.foot.appendChild(cp);
  m.foot.appendChild(dl);
  m.foot.appendChild(h('span', { class: 'grow' }));
  m.foot.appendChild(h('button', { class: 'btn primary', type: 'button', onclick: () => m.close() }, 'Kapat'));
  let data;
  try {
    data = await api.get('/api/market/unknown');
  } catch (err) {
    clear(box);
    box.appendChild(h('div', { class: 'errtxt' }, err.message));
    return m;
  }
  clear(box);
  const total = data.securities + data.fields;
  box.appendChild(h('h3', null, total ? 'Bloomberg\'in tanımadıkları · ' + data.securities + ' ticker' + (data.fields ? ', ' + data.fields + ' alan' : '')
    : 'Bloomberg\'in tanımadığı ticker yok'));
  if (!total) {
    box.appendChild(h('div', { class: 'muted' }, st.mode === 'live' ? 'Bloomberg\'in sorulan her ticker\'a bir cevabı var.' : 'Kayıtlı veride "Invalid Security" cevabı yok.'));
    cp.disabled = true;
    dl.disabled = true;
    return m;
  }
  box.appendChild(h('div', { class: 'muted note' }, 'Bloomberg bu ticker\'lar için "böyle bir menkul kıymet yok" ya da "alan yok / geçerli değil" dedi; bunlara abone '
    + 'olunmaz, her gün bir kez yeniden sorulur. Aynı biçimdeki ticker\'lar birlikte gösterilir (sayılar # ile). "Nerede": onu soran çalışma kitabı, '
    + 'sayfası ve dashboard sayfası; hücreye tıklayınca o tablo açılır.'));
  // ---- groups
  const groups = h('table', { class: 'plain unknown-groups', id: 'unknown-groups' }, h('tr', null, h('th', { class: 'l' }, 'Kalıp'), h('th', null, 'Adet'),
    h('th', { class: 'l' }, 'Cevap'), h('th', { class: 'l' }, 'Sayılar'), h('th', { class: 'l' }, 'Alanlar'), h('th', { class: 'l' }, 'Nerede'), h('th', { class: 'l' }, 'Açıklama')));
  for (const g of data.groups) {
    const where = h('td', { class: 'l' });
    g.where.forEach((w, i) => {
      if (i) where.appendChild(document.createTextNode(' · '));
      if (w.page) {
        const a = h('a', { href: '#/' + w.page }, w.book_title + ' › ' + w.sheet);
        a.addEventListener('click', () => m.close());
        where.appendChild(a);
      } else where.appendChild(document.createTextNode(w.book_title + ' › ' + w.sheet));
    });
    groups.appendChild(h('tr', null, h('td', { class: 'l mono', title: g.examples.join('\n') }, g.pattern, h('div', { class: 'muted ex' }, g.examples.slice(0, 3).join(' · '))),
      h('td', null, String(g.count)), h('td', { class: 'l' }, { security: 'Menkul kıymet yok', field: 'Alan yok', na: 'Alan geçerli değil' }[g.answer] || g.answer_text),
      h('td', { class: 'l' }, g.numbers || ''), h('td', { class: 'l' }, g.fields.join(', ')), where, h('td', { class: 'l notecol' }, g.note || '')));
  }
  box.appendChild(h('div', { class: 'reftable' }, groups));
  // ---- every ticker
  const rows = data.rows.map((r) => [{ t: r.security, k: 's', b: 1 }, r.api !== r.security ? r.api : '', { security: 'Menkul kıymet yok', field: 'Alan yok', na: 'Geçerli değil' }[r.answer] || r.answer_text,
    r.fields.join(', '), r.cells.length ? r.cells[0].book_title + ' › ' + r.cells[0].sheet : '',
    r.cells.map((c) => c.ref).join(', ') + (r.ncells > r.cells.length ? ' … (' + r.ncells + ')' : '')]);
  const grid = new Grid({ data: plainData(['Ticker', 'API\'ye giden', 'Cevap', 'Alanlar', 'Sayfa', 'Hücreler'], rows), editable: false });
  const det = h('details', { class: 'unknown-all' }, h('summary', null, 'Bütün liste (' + data.rows.length + ')'), h('div', { class: 'body' }, grid.el));
  box.appendChild(det);
  // the first cell of every ticker, to go to
  const jump = h('div', { class: 'muted jumps' });
  const firsts = data.rows.filter((r) => r.cells.length).slice(0, 12);
  if (firsts.length) {
    jump.appendChild(document.createTextNode('Hücreye git: '));
    firsts.forEach((r, i) => {
      if (i) jump.appendChild(document.createTextNode(' · '));
      jump.appendChild(cellLink(r.cells[0], () => m.close()));
    });
    box.appendChild(jump);
  }
  cp.addEventListener('click', () => {
    const lines = ['Ticker\tAPI\'ye giden\tCevap\tAlanlar\tÇalışma kitabı\tSayfa\tHücreler'].concat(data.rows.map((r) => [r.security, r.api, r.answer_text,
      r.fields.join(', '), r.cells.length ? r.cells[0].book_title : '', r.cells.length ? r.cells[0].sheet : '', r.cells.map((c) => c.ref).join(', ')].join('\t')));
    copyText(lines.join('\r\n'), data.rows.length + ' satır kopyalandı');
  });
  void copyGrid;
  return m;
}
