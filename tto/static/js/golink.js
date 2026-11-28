// A cell of the dashboard's own that leads to a table: Masa's Kontrol chips (the desk, 28.11.2026: "Kontrol nedenine
// götürsün" - tto/service.py ``_kontrol_chips``).  The server gives such a cell the classes "golink" and
// "go:#/<page>?p=<panel>"; a click on it opens that page with the table in view, the same address a page's KISAYOLLAR use.

/** The address a cell leads to ("#/ois?p=B3"), or "" - read off its "go:" class. */
export function goTarget(el) {
  if (!el || !el.classList || !el.classList.contains('golink')) return '';
  for (const c of el.classList) if (c.startsWith('go:#/')) return c.slice(3);
  return '';
}

let ready = false;

/** Follow the links of every table, wherever it is drawn (a page, a launchpad, the side drawer): one listener for the
 *  document, set once. */
export function setupGoLinks() {
  if (ready || typeof document === 'undefined' || !document.addEventListener) return;
  ready = true;
  document.addEventListener('click', (e) => {
    if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey || e.altKey) return;     // (a selection being made)
    const td = e.target && e.target.closest ? e.target.closest('td.golink') : null;
    const go = goTarget(td);
    if (go) window.location.hash = go;
  });
}
