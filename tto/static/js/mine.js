// The top bar's personal-state badge (the desk, 28.11.2026 - A6, "Sayıların masanınkinden farklı işareti"): what makes
// this user's numbers differ from the desk's, on every page - TLREF's normalization switched on (OIS · PPK; on PPK
// basamak the curve badge says it already) and the values typed over a workbook formula ("Elle değer": how many; a click
// lists them with their page, each back to its formula - or all of them).  The header's answer carries both (``mine``,
// ``hand``: tto/service.py); the list is /api/my-inputs' ``hand`` items.
import { api } from './api.js';
import { h, clear, modal, toast, errorToast, confirmDialog } from './ui.js';
import { trackWrite } from './grid.js';

const NORM_TIP = 'TLREF normalleşmesi sizde açık (OIS · PPK → Parametreler): Masa, forward kotasyon, RET, carry, DV01 ve '
  + 'Broker Chat\'in PPK adımı bununla hesaplanır - normalleşmesi kapalı olan masa arkadaşlarınız başka sayılar görür.';

/** The badge as the header says it: ``norm`` (the normalization on, not said by the curve badge), ``hand`` (how many values
 *  typed over formulas).  Hidden when neither. */
export function paintMine(state) {
  const b = document.getElementById('mine-badge');
  const t = document.getElementById('mine-text');
  if (!b || !t) return;
  const parts = [];
  if (state.norm) parts.push('Normalleşme açık');
  if (state.hand) parts.push(state.hand + ' elle değer');
  b.classList.toggle('hidden', !parts.length);
  t.textContent = parts.join(' · ');
  b.title = 'Sayılarınız masanınkinden farklı olabilir:'
    + (state.norm ? '\n• ' + NORM_TIP : '')
    + (state.hand ? '\n• ' + state.hand + ' hücrede formülün yerine elle yazdığınız değer var ("Elle değer").' : '')
    + '\nListe ve "formüle dön" için tıklayın.';
}

/** The list: the normalization (where to switch it), the values typed over formulas - their page, the cell, the value
 *  and when it was typed; "Git" opens the page on its table, "Formüle dön" takes one back, "Hepsini formüle döndür" all. */
export async function openMine(ctx, state) {
  const m = modal({ title: 'Kişisel durumunuz · masanınkinden farklı olan', width: 760 });
  const body = h('div', { id: 'mine-list' });
  m.body.appendChild(body);
  m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Kapat'));
  const fill = async () => {
    clear(body);
    if (state.norm) {
      const go = h('button', { class: 'btn sm', type: 'button', id: 'mine-norm-go' }, 'OIS · PPK → Parametreler');
      go.addEventListener('click', () => { m.close(); ctx.goto('ois', 'B1'); });
      body.appendChild(h('div', { class: 'mine-sec', id: 'mine-norm' }, h('b', null, 'TLREF normalleşmesi açık'),
        h('p', { class: 'muted' }, NORM_TIP), go));
    }
    let data;
    try { data = await api.get('/api/my-inputs'); } catch (err) { errorToast(err); return; }
    const hand = (data.inputs || []).filter((x) => x.hand);
    const sec = h('div', { class: 'mine-sec', id: 'mine-hand' }, h('b', null, 'Formül yerine elle değer (' + hand.length + ')'));
    body.appendChild(sec);
    if (!hand.length) {
      sec.appendChild(h('p', { class: 'muted' }, 'Hiçbir formülün yerine elle değer yazmadınız.'));
      return;
    }
    const table = h('table', { class: 'plain mine-table' });
    table.appendChild(h('thead', null, h('tr', null, h('th', { class: 'l' }, 'Sayfa'), h('th', { class: 'l' }, 'Hücre'),
      h('th', null, 'Değer'), h('th', { class: 'l' }, 'Yazıldı'), h('th', null, ''))));
    const tb = h('tbody');
    for (const x of hand) {
      const pg = (x.pages || [])[0];
      const go = h('button', { class: 'btn sm', type: 'button', disabled: !pg, title: pg ? 'Sayfasında, tablosunda aç' : 'Hiçbir sayfa göstermiyor' }, 'Git');
      go.addEventListener('click', () => { m.close(); if (pg) ctx.goto(pg.view, pg.panel); });
      const back = h('button', { class: 'btn sm', type: 'button', title: 'Bu hücre formülüne döner' }, 'Formüle dön');
      back.dataset.ref = x.ref;
      back.addEventListener('click', async () => {
        try {
          await trackWrite(api.post('/api/reset', { book: x.book, refs: [x.ref] }));
          toast(x.ref + ' formülüne döndü', 'ok', 2400);
          ctx.refreshNow();
          await fill();
        } catch (err) { errorToast(err); }
      });
      tb.appendChild(h('tr', null, h('td', { class: 'l' }, pg ? ctx.pageTitle(pg.view) : '—'), h('td', { class: 'l mono' }, x.ref),
        h('td', null, x.value === null ? '(boş)' : String(x.value)), h('td', { class: 'l muted' }, dayTime(x.at)), h('td', null, go, ' ', back)));
    }
    table.appendChild(tb);
    sec.appendChild(h('div', { class: 'mine-scroll' }, table));
    const all = h('button', { class: 'btn sm danger', type: 'button', id: 'mine-hand-all' }, 'Hepsini formüle döndür');
    all.addEventListener('click', async () => {
      if (!(await confirmDialog('Formüllere dön', hand.length + ' hücrede formülün yerine yazdığınız değer silinir; hücreler '
        + 'yeniden hesaplanır. Diğer girdileriniz kalır.', 'Formüllere dön'))) return;
      try {
        const books = new Map();
        for (const x of hand) { if (!books.has(x.book)) books.set(x.book, []); books.get(x.book).push(x.ref); }
        let n = 0;
        for (const [book, refs] of books) n += ((await trackWrite(api.post('/api/reset', { book, refs }))) || {}).reset || 0;
        toast(n + ' hücre formüle döndü', 'ok');
        ctx.refreshNow();
        await fill();
      } catch (err) { errorToast(err); }
    });
    sec.appendChild(all);
  };
  await fill();
}

/** "2026-11-27 17:02:11" -> "27.11 17:02" (empty: "—"). */
export function dayTime(at) {
  const m = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(String(at || ''));
  return m ? m[3] + '.' + m[2] + ' ' + m[4] + ':' + m[5] : '—';
}
