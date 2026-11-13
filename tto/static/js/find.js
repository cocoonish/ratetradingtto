// "Tablo bul": every table of every page by its name, from wherever you are (Ctrl+K).
// The workbook keeps a hundred-odd tables on a dozen sheets; here you type "interest" or "ret" and go.
import { h, clear } from './ui.js';

const MAX = 14;
const low = (s) => String(s || '').toLocaleLowerCase('tr').replace(/ı/g, 'i');      // "interest" finds "Interest"

/** pages: [{id, title, group, tables: [{id, title, tab}]}] -> [{page, panel, text, where}] best first. */
export function findTables(pages, query) {
  const words = low(query).split(/\s+/).filter(Boolean);
  if (!words.length) return [];
  const out = [];
  for (const p of pages) {
    const pt = low(p.title);
    if (words.every((w) => pt.includes(w))) out.push({ page: p.id, panel: null, text: p.title, where: 'sayfa', score: 0 });
    for (const t of p.tables || []) {
      const title = low(t.title);
      const all = pt + ' ' + low(t.tab) + ' ' + title;
      if (!words.every((w) => all.includes(w))) continue;
      const inTitle = words.every((w) => title.includes(w));
      out.push({ page: p.id, panel: t.id, text: t.title, where: p.title + (t.tab ? ' › ' + t.tab : ''),
        score: (inTitle ? 1 : 3) + (title.startsWith(words[0]) ? 0 : 1) });
    }
  }
  out.sort((a, b) => a.score - b.score);
  return out.slice(0, MAX);
}

export function setupFind(box, getPages, goto) {
  const input = box.querySelector('input');
  const list = h('div', { class: 'findlist hidden', role: 'listbox' });
  box.appendChild(list);
  let hits = [];
  let cur = 0;
  const close = () => { list.classList.add('hidden'); };
  const pick = (k) => {
    const x = hits[k];
    if (!x) return;
    close();
    input.value = '';
    input.blur();
    goto(x.page, x.panel);
  };
  const paint = () => {
    clear(list);
    if (!input.value.trim()) { close(); return; }
    if (!hits.length) list.appendChild(h('div', { class: 'none' }, 'Eşleşen tablo yok'));
    hits.forEach((x, k) => {
      const row = h('div', { class: 'hit' + (k === cur ? ' on' : ''), role: 'option' }, h('span', { class: 't' }, x.text), h('span', { class: 'w' }, x.where));
      row.addEventListener('mousedown', (e) => { e.preventDefault(); pick(k); });
      list.appendChild(row);
    });
    list.classList.remove('hidden');
  };
  input.addEventListener('input', () => { hits = findTables(getPages(), input.value); cur = 0; paint(); });
  input.addEventListener('focus', () => { if (input.value.trim()) { hits = findTables(getPages(), input.value); paint(); } });
  input.addEventListener('blur', () => setTimeout(close, 120));
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); cur = Math.min(hits.length - 1, cur + 1); paint(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); cur = Math.max(0, cur - 1); paint(); }
    else if (e.key === 'Enter') { e.preventDefault(); pick(cur); }
    else if (e.key === 'Escape') { e.preventDefault(); input.value = ''; close(); input.blur(); }
    e.stopPropagation();
  });
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && !e.altKey && (e.key === 'k' || e.key === 'K')) { e.preventDefault(); input.focus(); input.select(); }
  });
}
