// "Tablo bul": every table of every page by its name, from wherever you are (Ctrl+K).
// The workbook keeps a hundred-odd tables on a dozen sheets; here you type "interest" or "ret" and go - or put the table
// on a launchpad, or pin it to the side drawer, without going there.  Empty, the box lists the pages opened lately.
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

/**
 * opts: {recent(): [{id, title}] - the pages opened lately; add(src, x, y) - "+ Launchpad"'s menu for a table;
 *        pin(src) - the table to the side drawer}.  On a table: Ctrl+Enter puts it on a launchpad, Shift+Enter pins it.
 */
export function setupFind(box, getPages, goto, opts = {}) {
  const input = box.querySelector('input');
  const list = h('div', { class: 'findlist hidden', role: 'listbox' });
  box.appendChild(list);
  let hits = [];
  let cur = 0;
  const close = () => { list.classList.add('hidden'); };
  const done = () => { close(); input.value = ''; input.blur(); };
  const pick = (k) => {
    const x = hits[k];
    if (!x) return;
    done();
    goto(x.page, x.panel);
  };
  const src = (x) => ({ view: x.page, panel: x.panel });
  const addAt = (x, el) => {
    if (!opts.add) return;
    const r = el.getBoundingClientRect();
    opts.add(src(x), r.right - 220, r.bottom + 2);
  };
  const recentHits = () => (opts.recent ? opts.recent() : []).slice(0, 8)
    .map((p) => ({ page: p.id, panel: null, text: p.title, where: 'son açılan', recent: true }));
  const paint = () => {
    clear(list);
    const empty = !input.value.trim();
    if (empty && !hits.length) { close(); return; }
    if (empty) list.appendChild(h('div', { class: 'fh' }, 'Son açılan sayfalar'));
    else if (!hits.length) list.appendChild(h('div', { class: 'none' }, 'Eşleşen tablo yok'));
    hits.forEach((x, k) => {
      const row = h('div', { class: 'hit' + (k === cur ? ' on' : '') + (x.recent ? ' recent' : ''), role: 'option' },
        h('span', { class: 't' }, x.text), h('span', { class: 'w' }, x.where));
      if (x.panel && (opts.add || opts.pin)) {
        const acts = h('span', { class: 'acts' });
        if (opts.add) {
          const b = h('button', { class: 'act', type: 'button', title: 'Bir launchpad\'e ekleyin (Ctrl+Enter)' }, 'Launchpad\'e ekle');
          b.dataset.act = 'launchpad';
          b.addEventListener('mousedown', (e) => { e.preventDefault(); e.stopPropagation(); });
          b.addEventListener('click', (e) => { e.stopPropagation(); addAt(x, row); close(); });
          acts.appendChild(b);
        }
        if (opts.pin) {
          const b = h('button', { class: 'act', type: 'button', title: 'Her sayfada sağda dursun (Shift+Enter)' }, 'Yan panele sabitle');
          b.dataset.act = 'pin';
          b.addEventListener('mousedown', (e) => { e.preventDefault(); e.stopPropagation(); });
          b.addEventListener('click', (e) => { e.stopPropagation(); done(); opts.pin(src(x)); });
          acts.appendChild(b);
        }
        row.appendChild(acts);
      }
      row.addEventListener('mousedown', (e) => { e.preventDefault(); pick(k); });
      list.appendChild(row);
    });
    list.classList.remove('hidden');
  };
  const search = () => {
    hits = input.value.trim() ? findTables(getPages(), input.value) : recentHits();
    cur = 0;
    paint();
  };
  input.addEventListener('input', search);
  input.addEventListener('focus', search);
  input.addEventListener('blur', () => setTimeout(close, 120));
  input.addEventListener('keydown', (e) => {
    if (e.key === 'ArrowDown') { e.preventDefault(); cur = Math.min(hits.length - 1, cur + 1); paint(); }
    else if (e.key === 'ArrowUp') { e.preventDefault(); cur = Math.max(0, cur - 1); paint(); }
    else if (e.key === 'Enter') {
      e.preventDefault();
      const x = hits[cur];
      if (x && x.panel && (e.ctrlKey || e.metaKey) && opts.add) {
        const row = list.querySelectorAll('.hit')[cur];
        addAt(x, row || input);
        close();
      } else if (x && x.panel && e.shiftKey && opts.pin) {
        done();
        opts.pin(src(x));
      } else pick(cur);
    }
    else if (e.key === 'Escape') { e.preventDefault(); input.value = ''; close(); input.blur(); }
    e.stopPropagation();
  });
  document.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && !e.altKey && (e.key === 'k' || e.key === 'K')) { e.preventDefault(); input.focus(); input.select(); }
  });
}
