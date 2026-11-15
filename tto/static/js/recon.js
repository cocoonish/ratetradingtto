// Chat ↔ Günlük İşlemler: the desk's own trades said in the broker chat (lines of "Biz") next to the blotter -
// entered or not.  A chat trade is in the blotter when a trade of the same instrument at the same level was entered
// within a quarter of an hour of the time the chat says, or when it was opened from the chat line itself ("İşlem
// gir": the line is in its note); a pair can be made or undone by hand, a line ignored - for everyone.  What is left
// is "not entered": the badge on Broker Chat in the menu, and a warning before the day's archive.
import { api } from './api.js';
import { h, clear, errorToast, modal } from './ui.js';
import { isoToTr } from './format.js';
import { level, tradeKind, chatTradeDialog } from './pages/broker.js';

const STATE = {
  auto: ['Girildi', 'ok', 'Aynı enstrüman, aynı seviye, chat\'teki saatin ±15 dakikası içinde girilmiş'],
  linked: ['Girildi', 'ok', 'Bu chat satırından "İşlem gir" ile açılıp kaydedilmiş (notunda satır var) – saatine bakılmaz'],
  manual: ['Elle eşleştirildi', 'ok', 'Bir kullanıcı bu kayıtla eşleştirdi'],
  ignored: ['Yok sayıldı', 'neu', 'Bir kullanıcı girilmeyecek diye işaretledi'],
  missing: ['Girilmedi', 'warn', 'Günlük İşlemler\'de aynı enstrüman ve seviyede, chat\'teki saatin ±15 dakikası içinde girilmiş kayıt yok'],
  noform: ['Formu yok', 'neu', 'Günlük İşlemler\'de bu ürünün formu yok (cross currency, IRS, switch, O/N – T/N, listede olmayan vade …): sayılmaz'],
};

/** "+3 dk", "−1 sa 5 dk": how long after the chat's time the trade was entered. */
function gapText(s) {
  if (typeof s !== 'number') return '';
  const a = Math.round(Math.abs(s) / 60);
  return (s < 0 ? '−' : '+') + (a < 60 ? a + ' dk' : Math.floor(a / 60) + ' sa ' + (a % 60) + ' dk');
}

/** The trade of a chat line: "18M @ 35,14", "MPC Ara26 @ 36,75", "DİBS 15.03.28 @ 100,550". */
function what(item) {
  const q = item.q || {};
  const inst = q.product === 'OIS' ? q.label : (q.product === 'DIBS' ? 'DİBS ' + q.label : q.product + ' ' + q.label);
  return inst + (typeof q.price === 'number' ? ' @ ' + level(q.price, q.unit) : '');
}

function query(date, to) {
  if (to && to !== date) return { date, to };
  return date ? { date } : null;
}

/**
 * The list: every trade line of the desk in the chat of a day (today when none is given) or a period, what it is in
 * the blotter and what can be done with it.  ``ctx.refreshNow`` is called after a change (the menu's badge follows).
 */
export async function openRecon(ctx, date, to) {
  const m = modal({ title: 'Chat ↔ Günlük İşlemler', width: 1080 });
  m.box.id = 'chat-recon';
  const head = h('div', { class: 'muted recon-note' });
  const body = h('div', { class: 'recon-body' });
  m.body.appendChild(head);
  m.body.appendChild(body);
  m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Kapat'));
  let data = null;
  const load = async () => {
    data = await api.get('/api/broker/recon', query(date, to));
    draw();
  };
  const act = async (item, action, trade) => {
    try {
      await api.post('/api/broker/recon', { quote: item.id, action, trade: trade === undefined ? null : trade });
      ctx.refreshNow();
      await load();
    } catch (err) { errorToast(err); }
  };
  const draw = () => {
    clear(head);
    clear(body);
    const items = data.items || [];
    head.textContent = (data.ranged ? isoToTr(data.date) + ' – ' + isoToTr(data.to) : isoToTr(data.date)) + ' · masanın chat\'teki işlemleri (Taraf: Biz) '
      + 'Günlük İşlemler\'de: aynı enstrüman ve seviye, chat\'teki saatin ±' + Math.round((data.window || 900) / 60) + ' dakikası içinde girilen kayıt; '
      + '"İşlem gir" ile açılan kayıt notundaki satırla eşleşir. Elle eşleştirme ve "yok say" herkes için geçerlidir.'
      + (data.missing ? ' · ' + data.missing + ' işlem girilmedi' : '');
    if (!items.length) {
      body.appendChild(h('div', { class: 'empty' }, 'Chat\'te masanın (Biz) işlem satırı yok. Bir satırın bizim olduğunu "İsimler · kaynaklar"daki taraf '
        + 'ya da yapıştırırken seçilen "Biz" söyler.'));
      return;
    }
    const table = h('table', { class: 'plain recon', id: 'chat-recon-table' },
      h('tr', null, ['Saat', 'Kimden', 'Mesaj', 'İşlem', 'Durum', 'Günlük İşlemler', ''].map((t) => h('th', { class: 'l' }, t))));
    for (const item of items) {
      const st = STATE[item.state] || [item.state, 'neu', ''];
      const acts = h('td', { class: 'l acts' });
      const btn = (label, title, fn, cls, id) => {
        const b = h('button', { class: 'btn sm' + (cls ? ' ' + cls : ''), type: 'button', title, id: id || null }, label);
        b.addEventListener('click', fn);
        acts.appendChild(b);
      };
      if (item.state === 'missing') {
        if (item.date === data.today && tradeKind(item.q)) {
          btn('⇢ Gir', 'Günlük İşlemler\'i bu satırla dolu aç: seviye ve yön seçilir, tutarı yazıp kaydedin', () => { m.close(); chatTradeDialog(item.q, ctx); },
            'primary', 'recon-enter-' + item.id);
        }
        const free = (data.entries || []).filter((e) => !e.taken && e.date === item.date);
        if (free.length) {
          const pick = h('select', { class: 'inp', title: 'Bu chat satırının işlemi olan kayıt', id: 'recon-pick-' + item.id },
            h('option', { value: '' }, 'kayıt seçin…'), free.map((e) => h('option', { value: String(e.id) }, e.time + ' · ' + e.label)));
          acts.appendChild(pick);
          btn('Eşleştir', 'Seçilen kaydı bu satırın işlemi say', () => { if (pick.value) act(item, 'match', Number(pick.value)); }, '', 'recon-match-' + item.id);
        }
        btn('Yok say', 'Bu satır Günlük İşlemler\'e girilmeyecek (örn. iptal oldu, başka yerde tutuluyor)', () => act(item, 'ignore'), '', 'recon-ignore-' + item.id);
      } else if ((item.state === 'auto' || item.state === 'linked') && item.entry) {
        btn('Yanlış eşleşme', 'Bu kayıt bu satırın işlemi değil: ayır (satır girilmemiş sayılır, başka bir kayıtla eşleşebilir)',
          () => act(item, 'reject', item.entry.id), '', 'recon-reject-' + item.id);
      } else if (item.state === 'manual' || item.state === 'ignored') {
        btn('Geri al', 'Elle yapılanı geri al', () => act(item, 'undo'), '', 'recon-undo-' + item.id);
      }
      const entry = item.entry ? (data.ranged ? isoToTr(item.entry.date).slice(0, 5) + ' ' : '') + item.entry.time + ' · ' + item.entry.label
        + (typeof item.gap === 'number' ? ' (' + gapText(item.gap) + ')' : '') : '';
      table.appendChild(h('tr', { class: 'st-' + item.state, 'data-id': String(item.id) },
        h('td', { class: 'l' }, (data.ranged ? isoToTr(item.date).slice(0, 5) + ' ' : '') + (item.time || '')),
        h('td', { class: 'l' }, [item.sender, item.source].filter(Boolean).join(' · ')),
        h('td', { class: 'l said', title: item.raw || '' }, item.raw || ''), h('td', { class: 'l b' }, what(item)),
        h('td', { class: 'l state' }, h('span', { class: 'pill ' + st[1], title: st[2] + (item.by ? ' · ' + ctx.displayName(item.by) : '') }, st[0])),
        h('td', { class: 'l' }, entry), acts));
    }
    body.appendChild(table);
  };
  try { await load(); } catch (err) { m.close(); errorToast(err); }
  return m;
}

/**
 * Before the day's archive is downloaded: the desk's chat trades not in the blotter, if any - with the list, and
 * "download anyway" or not.  Resolves to true when the archive is to be downloaded; a check that cannot be made does
 * not stand in its way.
 */
export async function checkBeforeArchive(ctx, date, to) {
  let data = null;
  try { data = await api.get('/api/broker/recon', query(date, to)); } catch (e) { return true; }
  const miss = (data.items || []).filter((x) => x.state === 'missing');
  if (!miss.length) return true;
  return new Promise((resolve) => {
    let done = false;
    const m = modal({ title: 'Girilmemiş işlem var', width: 640, onClose: () => { if (!done) resolve(false); } });
    const finish = (v) => { done = true; m.close(); resolve(v); };
    m.box.id = 'archive-warn';
    m.body.appendChild(h('p', { style: { margin: '0 0 8px' } }, 'Chat\'te masanın ' + miss.length + ' işlemi Günlük İşlemler\'de görünmüyor. '
      + 'Arşivden önce girin; girilmeyecekse listede "Yok say"ın.'));
    m.body.appendChild(h('ul', { class: 'recon-miss' }, miss.slice(0, 12).map((x) => h('li', null,
      [(data.ranged ? isoToTr(x.date) + ' ' : '') + (x.time || ''), x.sender, x.source, what(x)].filter(Boolean).join(' · ')))));
    if (miss.length > 12) m.body.appendChild(h('div', { class: 'muted' }, '… ve ' + (miss.length - 12) + ' satır daha'));
    m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => finish(false) }, 'Vazgeç'));
    m.foot.appendChild(h('button', { class: 'btn', type: 'button', id: 'archive-warn-list', onclick: () => { finish(false); openRecon(ctx, date, to); } },
      'Listeyi aç'));
    m.foot.appendChild(h('button', { class: 'btn primary', type: 'button', id: 'archive-warn-go', onclick: () => finish(true) }, 'Yine de indir'));
  });
}
