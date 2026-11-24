// What stands behind the badge of the top bar: where the market data comes from, how the Bloomberg session is
// doing - and which tickers Bloomberg says it does not know, with the cells of the workbooks that ask for them.
import { api, session } from './api.js';
import { h, clear, modal, toast, errorToast, copyText } from './ui.js';
import { Grid, plainData, copyGrid } from './grid.js';
import { num } from './format.js';

function line(label, value, cls, id) {
  return h('div', { class: 'stline' + (cls ? ' ' + cls : ''), id: id || null }, h('span', { class: 'l' }, label), h('span', { class: 'v' }, value));
}

function clock(t) {
  if (!t) return '—';
  const d = new Date(t * 1000);
  return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0') + ':' + String(d.getSeconds()).padStart(2, '0');
}

/** A link to where a cell is shown: its page and table, or the sheet explorer (administrators) when no page shows it. */
function cellLink(c, close) {
  const text = c.sheet + '!' + c.ref;
  if (!c.page && session.role !== 'admin') return h('span', { title: c.book_title + ' · ' + text }, text);
  const a = h('a', { href: c.page ? '#/' + c.page + (c.panel ? '?p=' + encodeURIComponent(c.panel) : '') : '#/explorer', title: c.book_title + ' · ' + text }, text);
  a.addEventListener('click', () => {
    if (!c.page) {
      try { sessionStorage.setItem('tto.explorer', JSON.stringify({ book: c.book, sheet: c.sheet, range: c.ref })); } catch (e) { /* ignore */ }
    }
    close();
  });
  return a;
}

/** Where today's Bloomberg hits went (``/api/market/usage``): by kind, the top sheets (a link to the page that shows
 * one), the top fields - the desk sees the cost of each part of the dashboard. */
function fillUsage(box, u, close) {
  clear(box);
  box.appendChild(h('h3', null, 'Bugünkü veri istekleri nereye gitti · ' + num(u.hits || 0, 0)
    + (u.budget ? ' / ' + num(u.budget, 0) + ' bütçe (%' + num(u.used || 0, 1) + ')' : '')));
  if (!u.hits) {
    box.appendChild(h('div', { class: 'muted' }, 'Bugün Bloomberg\'e henüz istek gitmedi.'));
    return;
  }
  const pct = (n) => '%' + num(100 * n / u.hits, 1);
  const table = (id, head, rows) => h('table', { class: 'plain', id }, h('tr', null, ...head.map((x, i) => h('th', { class: i ? '' : 'l' }, x))), ...rows);
  const kinds = table('usage-kinds', ['Ne için', 'İstek', 'Pay'], (u.kinds || []).map((k) => h('tr', null,
    h('td', { class: 'l' }, k.label), h('td', null, num(k.hits, 0)), h('td', null, pct(k.hits)))));
  const sheets = table('usage-sheets', ['Sayfa (ilk 10)', 'İstek'], (u.sheets || []).map((s) => {
    const name = s.book_title + (s.sheet ? ' › ' + s.sheet : '');
    let cell = name;
    if (s.page) {
      cell = h('a', { href: '#/' + s.page }, name);
      cell.addEventListener('click', close);
    }
    return h('tr', null, h('td', { class: 'l' }, cell), h('td', null, num(s.hits, 0)));
  }));
  const fields = table('usage-fields', ['Alan (ilk 10)', 'İstek'], (u.fields || []).map((f) => h('tr', null,
    h('td', { class: 'l mono' }, f.field), h('td', null, num(f.hits, 0)))));
  box.appendChild(h('div', { class: 'usage-grid' }, kinds, sheets, fields));
  box.appendChild(h('div', { class: 'muted note' }, 'Önce önbellek (masa, 24.11.2026): bugün cevabı gelen bir değer bugün bir daha '
    + 'istenmez - yeniden başlatmada da. Fiyatlar abonelikle akar (ücretsiz); akmayan bir kota en çok 15 dakikada bir, değeri olmayan '
    + '3 saatte bir sorulur. 5G / 1A değişim, son işlem tarihi, aralık en düşük / en yüksek ve bugünü içeren BDH akıştan güncellenir. '
    + 'Sorgu saatleri dışında, hafta sonu ve tatilde hiçbir şey yeniden sorulmaz. Günlük bütçenin %70\'inden sonra yalnızca sayfaların '
    + 'hiç almadığı ilk değerler, %100\'de hiçbir yeni istek gitmez.'));
}

const FEED = { ok: 'akıyor', stale: 'BAYAT', silent: 'BAYAT (yardımcı süreç sessiz)', down: 'bağlantı yok', replay: 'kayıtlı veri' };

export async function openStatus(status) {
  const st = status || {};
  const p = st.provider || {};
  const ops = st.ops || {};
  const feed = ops.feed || {};
  const m = modal({ title: 'Veri kaynağı', width: 1100 });
  m.box.classList.add('statusbox');
  const head = h('div', { class: 'stgrid' });
  if (st.mode === 'live') {
    head.appendChild(line('Veri', (FEED[feed.state] || feed.state || '—') + (feed.as_of ? ' · ' + feed.as_of + ' itibarıyla' : '')
      + (feed.reason ? ' – ' + feed.reason : ''), feed.state === 'ok' ? '' : 'bad'));
    if (p.isolated) {
      head.appendChild(line('Yardımcı süreç son ses', clock(p.heard) + (p.silent_restarts ? ' · sessiz kaldığı için bugün ' + p.silent_restarts
        + ' kez yeniden başlatıldı' : ''), p.silent_restarts ? 'warn' : ''));
    }
    head.appendChild(line('Bağlantı', p.connected === false ? 'YOK – yeniden bağlanılıyor' : 'Bloomberg ' + (p.host || ''), p.connected === false ? 'bad' : ''));
    head.appendChild(line('Abonelik', num(p.subscriptions || 0, 0) + (p.subscriptions_failed ? ' · ' + p.subscriptions_failed + ' başarısız' : '')));
    head.appendChild(line('Bloomberg\'in tanımadığı', num(p.subscriptions_invalid || 0, 0) + ' ticker (abone olunmadı)', p.subscriptions_invalid ? 'warn' : ''));
    head.appendChild(line('Bekleyen veri', num(p.pending || 0, 0)));
    // cache first (24.11.2026): the day's budget in %, Bloomberg's own daily limit, the hours Bloomberg is asked in
    const used = p.budget ? 100 * (p.hits_today || 0) / p.budget : null;
    head.appendChild(line('Bugünkü veri isteği', num(p.hits_today || 0, 0)
      + (used !== null ? ' · günlük bütçenin %' + num(used, 1) + '\'i (bütçe ' + num(p.budget, 0) + ')' : '')
      + (p.tier >= 2 && !p.bbg_limit ? ' · BÜTÇE DOLDU: yeni istek gönderilmiyor' : p.tier === 1 ? ' · %70 geçildi: yalnızca sayfaların hiç almadığı ilk değerler isteniyor' : '')
      + (p.limit_reached && !p.budget ? ' · GÜNLÜK LİMİT KORUMASI' : ''),
    p.tier >= 2 || p.limit_reached ? 'bad' : (p.tier === 1 ? 'warn' : ''), 'status-hits'));
    if (p.bbg_limit) {
      head.appendChild(line('Bloomberg limiti', 'Bloomberg günlük limiti doldu – yarın yeniden (' + p.bbg_limit + (p.bbg_limit_text ? ': ' + p.bbg_limit_text : '')
        + '). Yeni istek gönderilmiyor, son değerler gösteriliyor; abonelikler akmaya devam ediyor.', 'bad', 'status-bbg-limit'));
    }
    if (p.desk) {
      head.appendChild(line('Bloomberg sorgu saatleri', p.desk.open + '–' + p.desk.close + ' (hafta içi, TR tatilleri hariç)'
        + (p.quiet ? ' · ŞİMDİ SESSİZ SAAT: yenileme ve sorgu yok, abonelikler akıyor' : ''), p.quiet ? 'warn' : '', 'status-desk'));
    }
    const polled = p.polled || {};
    if (polled.value || polled.empty || polled.stopped || p.fed) {
      head.appendChild(line('Akmayan kotalar', (polled.value || 0) + ' alan en çok ' + Math.round((p.poll_every || 900) / 60) + ' dk\'da bir, '
        + (polled.empty || 0) + ' boş alan ' + Math.round((p.poll_empty || 10800) / 3600) + ' saatte bir sorgulanıyor'
        + (polled.stopped ? ', akışı kesilen ' + polled.stopped + ' alan saatte bir' : '')
        + (p.fed ? ' · ' + p.fed + ' alan (5G / 1A değişim, son işlem tarihi, aralık en düşük / en yüksek, bugünkü BDH noktası) akıştan güncelleniyor' : ''),
      '', 'status-polled'));
    }
    head.appendChild(line('Tick', num(p.ticks || 0, 0) + ' · son ' + clock(p.last_tick)));
    head.appendChild(line('Oturum', p.isolated ? 'ayrı süreçte' + (p.restarts ? ' (' + p.restarts + ' kez yeniden başladı)' : '') : 'dashboard sürecinde'));
    if (p.events_dropped || p.messages_lost) head.appendChild(line('Kuyruk', (p.events_dropped || p.messages_lost) + ' olay düştü, ' + (p.resyncs || 0) + ' değer yeniden istendi', 'warn'));
    if (p.error) head.appendChild(line('Son hata', p.error, 'bad'));
  } else {
    head.appendChild(line('Veri', 'Kayıtlı veri (Excel dosyalarındaki son piyasa verisi)'));
    if (st.note) head.appendChild(line('Not', st.note, 'warn'));
  }
  // the dashboard itself: the calculation thread's queue, the last fault a background loop survived, the log
  const eng = ops.engine || {};
  head.appendChild(line('Hesap motoru', (eng.queue || 0) + ' iş bekliyor' + (eng.busy ? ' · şu anki iş ' + num(eng.busy, 1) + ' sn\'dir sürüyor' : ''),
    (eng.queue || 0) > 20 || (eng.busy || 0) > 30 ? 'warn' : ''));
  const le = ops.last_error;
  head.appendChild(line('Son hata (dashboard)', le ? le.at + ' · ' + le.where + ' · ' + le.text + (le.count > 1 ? ' (toplam ' + le.count + ')' : '') : 'yok',
    le ? 'warn' : ''));
  if (ops.log) head.appendChild(line('Günlük dosyası', ops.log));
  // the database: its check at the start, the daily backups
  const db = ops.db || {};
  const chk = db.check;
  if (chk) {
    head.appendChild(line('Veritabanı denetimi', chk.ok ? 'tamam (açılışta, ' + num(chk.seconds, 2) + ' sn)'
      : 'BAŞARISIZ: ' + (chk.problems || []).slice(0, 3).join('; ') + ' – en son yedeğe dönüp okunabilenleri geri almak için README: "Veritabanı bozulursa"', chk.ok ? '' : 'bad'));
  }
  // the data folder (datadir.py): on a network drive the database can be damaged (red), and the lock that keeps one
  // dashboard per data folder
  const fold = db.folder || {};
  if (fold.network) {
    const net = line('Veri klasörü', fold.warning + ' (bu açılışta günlük kipi: ' + (fold.journal || '?').toUpperCase() + ')', 'bad');
    net.id = 'status-dbfolder';
    head.appendChild(net);
  } else if (fold.journal) {
    const own = line('Veri klasörü', 'bilgisayarın kendi diskinde (günlük kipi: ' + fold.journal.toUpperCase() + ')');
    own.id = 'status-dbfolder';
    head.appendChild(own);
  }
  const lk = fold.lock;
  if (lk) {
    const lost = lk.lost;
    const text = lost
      ? 'BAŞKA BİR DASHBOARD\'A GEÇTİ (' + (lost.host || '?') + (lost.started ? ', açılışı ' + lost.started : '') + ') – bu dashboard kapanıyor'
      : 'bu dashboard tutuyor · ' + lk.host + ' · açılışı ' + lk.since + (lk.beat ? ' · son işaret ' + lk.beat.slice(11) : '')
        + (lk.failing ? ' · ' + lk.failing.slice(11) + ' itibarıyla YAZILAMIYOR (veri klasörüne ulaşılamıyor)' : '')
        + (lk.took_over ? ' · açılışta eski kilit devralındı (' + (lk.took_over.host || '?') + ': ' + lk.took_over.why + ')' : '');
    const el = line('Tek dashboard kilidi', text, lost || lk.failing ? 'bad' : '');
    el.id = 'status-dblock';
    head.appendChild(el);
  }
  const bk = db.backup || {};
  if (bk.dir) {
    const last = bk.last;
    head.appendChild(line('Son yedek', (last ? last.at + ' · ' + num(last.bytes / 1048576, 1) + ' MB' : 'henüz yok')
      + ' · ' + (bk.count || 0) + ' / ' + (bk.keep || 30) + ' yedek · her gün ' + (bk.time || '') + ' · ' + bk.dir
      + (bk.error ? ' · SON DENEME BAŞARISIZ (' + bk.error.at + '): ' + bk.error.text : ''), bk.error ? 'bad' : (last ? '' : 'warn')));
    // the chosen folder could not be written: the day's backup went to the dashboard's own folder - reached it since?
    const fb = bk.fallback;
    if (fb) {
      const waiting = (fb.waiting || []).length;
      const day = fb.today ? 'bugünkü yedek' : fb.day + ' yedeği';
      head.appendChild(line('Seçilen klasöre yazılamadı', waiting
        ? (waiting > 1 ? waiting + ' günün yedeği' : day) + ' dashboard\'un kendi klasörüne alındı (' + fb.at + ' · ' + fb.dir + ') – seçilen klasöre '
          + 'henüz ulaşmadı, yarım saatte bir denenir' + (fb.error ? ' (son deneme ' + fb.error.at + ': ' + fb.error.text + ')' : '')
        : day + ' önce dashboard\'un kendi klasörüne alındı (' + fb.at + '), ' + fb.reached_at + ' itibarıyla seçilen klasörde',
      waiting ? 'bad' : 'warn'));
    }
    // its second copy on another drive or share: a failure does not stop the backup; two days in a row: an alarm
    const cp = bk.copy;
    if (cp) {
      head.appendChild(line('İkinci kopya', (cp.last ? cp.last.at + ' · ' : '') + (cp.count || 0) + ' / ' + (bk.keep || 30) + ' kopya · ' + cp.dir
        + (cp.error ? ' · ALINAMADI' + (cp.failed_nights > 1 ? ' (' + cp.failed_nights + ' gündür)' : '') + ': ' + cp.error.text : ''),
        cp.error ? (cp.failed_nights > 1 ? 'bad' : 'warn') : (cp.last ? '' : 'warn')));
    } else {
      head.appendChild(line('İkinci kopya', 'seçilmedi – yedekler tek klasörde'));
    }
    // (the folders are the administrators' to see - and to choose)
    const go = h('a', { href: '#/backup', id: 'status-backup' }, 'Araçlar → Yedekleme');
    go.addEventListener('click', () => m.close());
    head.appendChild(line('Yedek ayarları', go));
  }
  m.body.appendChild(head);
  if (st.mode === 'live') {
    // where today's hits went: by kind, the top sheets and fields (asked when the window opens)
    const usage = h('div', { class: 'unknown', id: 'status-usage' }, h('div', { class: 'loading' }, 'Bugünkü isteklerin dağılımı yükleniyor…'));
    m.body.appendChild(usage);
    api.get('/api/market/usage').then((u) => fillUsage(usage, u, () => m.close())).catch((err) => {
      clear(usage);
      usage.appendChild(h('div', { class: 'errtxt' }, err.message));
    });
  }

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
