// Bonds added to a list of a page by ISIN: typed / pasted, or picked from the desk's list of TRY government bonds.
import { api } from './api.js';
import { h, clear, modal, toast, errorToast } from './ui.js';
import { isoToTr } from './format.js';

const KIND_ORDER = ['all', 'fixed', 'float', 'cpi', 'bill', 'zero'];
const KIND_TEXT = { all: 'Tümü', fixed: 'Sabit', float: 'TLREF', cpi: 'TÜFE', bill: 'Bono', zero: 'Kuponsuz' };

/**
 * ``opts``: {book, list (e.g. "DİBS RV!A5:A54"), name (the list's name in the catalog: dibs / asw / bulk),
 * catalog (offer the TRY government bonds to pick from), title}.
 */
export async function openAddIsin(ctx, opts) {
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
