// Small DOM helpers: element builder, toasts, modals, context menus.

export function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  if (attrs) {
    for (const k of Object.keys(attrs)) {
      const v = attrs[k];
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'dataset') Object.assign(el.dataset, v);
      else if (k === 'style' && typeof v === 'object') Object.assign(el.style, v);
      else if (k.startsWith('on') && typeof v === 'function') el.addEventListener(k.slice(2), v);
      else if (k === 'value') el.value = v;
      else if (v === true) el.setAttribute(k, '');
      else el.setAttribute(k, v);
    }
  }
  append(el, children);
  return el;
}

export function append(el, children) {
  for (const c of children) {
    if (c === null || c === undefined || c === false) continue;
    if (Array.isArray(c)) append(el, c);
    else if (c instanceof Node) el.appendChild(c);
    else el.appendChild(document.createTextNode(String(c)));
  }
}

/**
 * Empty ``el``: all its children at once.  (One at a time, a box holding the focused control - a list's select just
 * changed, a spread just typed - was laid out half emptied: Chrome blurs a focused control taken out of the page and
 * lays the page out right then, and by then the children above it were gone; the box's scroll, or the page's, was
 * clamped or anchored to that shorter content, and the page jumped when the box was drawn again.)
 */
export function clear(el) {
  el.textContent = '';
  return el;
}

export function debounce(fn, ms) {
  let t = null;
  const wrapped = (...args) => {
    if (t) clearTimeout(t);
    t = setTimeout(() => { t = null; fn(...args); }, ms);
  };
  wrapped.cancel = () => { if (t) clearTimeout(t); t = null; };
  return wrapped;
}

export function toast(message, kind = '', ms = 3800) {
  const box = document.getElementById('toasts');
  const el = h('div', { class: 'toast ' + kind }, message);
  box.appendChild(el);
  setTimeout(() => el.remove(), ms);
  return el;
}

export function errorToast(err) {
  toast(err && err.message ? err.message : String(err), 'err', 6000);
}

let openMenu = null;
export function closeMenu() {
  if (openMenu) { openMenu.remove(); openMenu = null; }
}

/**
 * items: [{label, action, header, sep, disabled, id, title}]; {check: true, on, label, sub, id, action(on)} is a line with a
 * tick box (``id``: the box's) that leaves the menu open (several in a row can be changed); its action returns false to
 * refuse the change.  {choices: [{label, action, on, title, value}], label, id, title} is a line of small buttons side by
 * side (``Ondalık: 0 1 2 3 …``; ``on``: the one in use, ``value``: the button's data-v) - a click acts and closes the menu.
 * {node: Element} is put in as it is (the colours of a page's cells: a legend).  ``cls``: a class of the menu's own.
 */
export function menu(x, y, items, cls) {
  closeMenu();
  const el = h('div', { class: 'menu' + (cls ? ' ' + cls : ''), role: 'menu' });
  for (const it of items) {
    if (!it) continue;
    if (it.sep) { el.appendChild(h('div', { class: 'sep' })); continue; }
    if (it.header) { el.appendChild(h('div', { class: 'mh' }, it.header)); continue; }
    if (it.node) { el.appendChild(it.node); continue; }
    if (it.choices) {
      const row = h('div', { class: 'mrow', id: it.id || null, title: it.title || null }, h('span', { class: 't' }, it.label));
      for (const c of it.choices) {
        const b = h('button', { type: 'button', class: c.on ? 'on' : null, title: c.title || null, disabled: !!c.disabled }, c.label);
        if (c.value !== undefined) b.dataset.v = String(c.value);
        b.addEventListener('click', () => { closeMenu(); c.action(); });
        row.appendChild(b);
      }
      el.appendChild(row);
      continue;
    }
    if (it.check) {
      const box = h('input', { type: 'checkbox', disabled: !!it.disabled, id: it.id || null });
      box.checked = !!it.on;
      box.addEventListener('change', () => { if (it.action(box.checked) === false) box.checked = !box.checked; });
      el.appendChild(h('label', { class: 'mcheck', title: it.title || null }, box, h('span', { class: 't' }, it.label),
        it.sub ? h('span', { class: 'sub' }, it.sub) : null));
      continue;
    }
    const b = h('button', { type: 'button', disabled: !!it.disabled, id: it.id || null, title: it.title || null }, it.label);
    b.addEventListener('click', () => { closeMenu(); it.action(); });
    el.appendChild(b);
  }
  el.style.maxHeight = '60vh';
  el.style.overflowY = 'auto';
  document.body.appendChild(el);
  const r = el.getBoundingClientRect();
  el.style.left = Math.max(4, Math.min(x, window.innerWidth - r.width - 6)) + 'px';
  el.style.top = Math.max(4, Math.min(y, window.innerHeight - r.height - 6)) + 'px';
  openMenu = el;
  return el;
}

document.addEventListener('mousedown', (e) => {
  if (openMenu && !openMenu.contains(e.target)) closeMenu();
}, true);
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape' && openMenu) { closeMenu(); e.stopPropagation(); }
}, true);
window.addEventListener('blur', closeMenu);

/** Modal dialog. Returns {el, body, foot, close}. */
export function modal({ title, width, onClose }) {
  const body = h('div', { class: 'mbody' });
  const foot = h('div', { class: 'mfoot' });
  const box = h('div', { class: 'modal', role: 'dialog', 'aria-modal': 'true' });
  if (width) box.style.width = 'min(' + width + 'px, 94vw)';
  const back = h('div', { class: 'modal-back' }, box);
  const close = () => {
    back.remove();
    document.removeEventListener('keydown', onKey, true);
    if (onClose) onClose();
  };
  const onKey = (e) => {
    if (e.key === 'Escape' && !openMenu) { e.stopPropagation(); close(); }
  };
  box.appendChild(h('header', null, h('h2', null, title),
    h('button', { class: 'iconbtn', type: 'button', title: 'Kapat', onclick: close }, '✕')));
  box.appendChild(body);
  box.appendChild(foot);
  back.addEventListener('mousedown', (e) => { if (e.target === back) close(); });
  document.addEventListener('keydown', onKey, true);
  document.body.appendChild(back);
  return { el: back, box, body, foot, close };
}

export function confirmDialog(title, message, okLabel = 'Tamam', danger = false) {
  return new Promise((resolve) => {
    let done = false;
    const m = modal({ title, width: 420, onClose: () => { if (!done) resolve(false); } });
    m.body.appendChild(h('p', { style: { margin: '0' } }, message));
    m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Vazgeç'));
    const ok = h('button', { class: 'btn primary' + (danger ? ' danger-solid' : ''), type: 'button',
      onclick: () => { done = true; m.close(); resolve(true); } }, okLabel);
    m.foot.appendChild(ok);
    ok.focus();
  });
}

export function promptDialog(title, label, initial = '') {
  return new Promise((resolve) => {
    let done = false;
    const m = modal({ title, width: 420, onClose: () => { if (!done) resolve(null); } });
    const input = h('input', { class: 'inp', style: { width: '100%' }, value: initial, maxlength: '60' });
    const finish = () => { done = true; const v = input.value.trim(); m.close(); resolve(v || null); };
    m.body.appendChild(h('div', { class: 'field' }, h('label', null, label), input));
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') finish(); });
    m.foot.appendChild(h('button', { class: 'btn', type: 'button', onclick: () => m.close() }, 'Vazgeç'));
    m.foot.appendChild(h('button', { class: 'btn primary', type: 'button', onclick: finish }, 'Kaydet'));
    input.focus();
    input.select();
  });
}

/** Put text on the clipboard (also where the Clipboard API is not allowed: plain http on the desk network). */
export async function copyText(text, message = 'Kopyalandı') {
  let ok = false;
  try {
    if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(text); ok = true; }
  } catch (e) { ok = false; }
  if (!ok) {
    const ta = h('textarea', { style: { position: 'fixed', left: '-9999px', top: '0' } });
    ta.value = text;
    document.body.appendChild(ta);
    ta.select();
    try { ok = document.execCommand('copy'); } catch (e) { ok = false; }
    document.body.removeChild(ta);
  }
  toast(ok ? message : 'Kopyalanamadı', ok ? 'ok' : 'err', ok ? 2200 : 4000);
  return ok;
}

/**
 * A row of chips on one line (a page's KISAYOLLAR, the top bar's favourites): the ones past its end are taken out of view
 * and ``more`` says how many ("+N"; hidden when all fit) - a click on it is the caller's (the rest in a menu, the row
 * opened).  A row with the class ``open`` shows them all (``more`` then reads ``less``).  Returns the chips left out.
 * Called again whenever the row's width changes (``watchWidth``).
 */
export function fitOneLine(box, items, more, less = '−') {
  for (const x of items) x.classList.remove('ovfl');
  more.classList.remove('hidden');
  if (box.classList.contains('open')) { more.textContent = less; return []; }
  const b = box.getBoundingClientRect();
  if (!b.width) return [];                                          // (not laid out: out of the page, or hidden)
  if (!items.length || items[items.length - 1].getBoundingClientRect().right <= b.right) {
    more.classList.add('hidden');                                   // (all of them fit)
    return [];
  }
  more.textContent = '+' + items.length;                          // (its widest: the room it needs)
  const room = b.right - more.getBoundingClientRect().width - 8;
  const out = items.filter((x) => x.getBoundingClientRect().right > room);
  for (const x of out) x.classList.add('ovfl');
  more.textContent = '+' + out.length;
  return out;
}

/** ``fn`` whenever ``el``'s width changes (and once when it is first laid out): a row fitted to one line. */
export function watchWidth(el, fn) {
  let w = -1;
  const run = () => {
    const now = Math.round(el.getBoundingClientRect().width);
    if (now === w) return;
    w = now;
    fn();
  };
  if (window.ResizeObserver) new ResizeObserver(run).observe(el);
  else window.addEventListener('resize', run);
  return run;
}

/**
 * A panel's note folded to two lines (the desk, 27.11.2026): "devamı" opens the rest, "kısalt" folds it again - shown
 * only when the note is longer than that.  ``el``: the note's element (its text already in it).  Returns ``check``: call
 * it when the text changed.
 */
export function foldNote(el) {
  el.classList.add('clamp');
  const more = h('button', { class: 'note-more', type: 'button', title: 'Notun tamamını göster / kısalt' }, 'devamı');
  more.addEventListener('click', (e) => {
    e.stopPropagation();
    const open = el.classList.toggle('open');
    more.textContent = open ? 'kısalt' : 'devamı';
    if (!open) check();
  });
  el.appendChild(more);
  const check = () => {
    if (el.classList.contains('open')) return;
    el.classList.toggle('long', el.scrollHeight > el.clientHeight + 2);
  };
  if (noteSizes) noteSizes.observe(el);
  return { more, check };
}

// the notes laid out anew (a tab opened, a panel unfolded, the window resized): longer than two lines or not - all of
// them measured first, then marked (one layout of the page, not one a note)
const noteSizes = window.ResizeObserver ? new ResizeObserver((entries) => {
  const els = entries.map((e) => e.target).filter((el) => !el.classList.contains('open'));
  const over = els.map((el) => el.scrollHeight > el.clientHeight + 2);
  els.forEach((el, k) => { if (el.classList.contains('long') !== over[k]) el.classList.toggle('long', over[k]); });
}) : null;

/**
 * A page, a panel or a box waiting for its first answer (the desk, 28.11.2026 - B7: "Boş, sıfır ve yükleniyor ayrı
 * okunsun"): "Hesaplanıyor…" with a small turning mark - never an empty table, nor zeros that read as numbers.  Put it
 * where the content comes; the content replaces it.  ``text``: another word for the wait ("Vol yüzeyi kuruluyor…").
 */
export function waiting(text) {
  return h('div', { class: 'loading waiting', role: 'status', 'aria-live': 'polite' }, h('span', { class: 'spin', 'aria-hidden': 'true' }),
    text || 'Hesaplanıyor…');
}

/** True when keyboard / clipboard events should be left to a form control. */
export function inFormControl(target) {
  if (!target || !target.tagName) return false;
  const t = target.tagName;
  return t === 'INPUT' || t === 'TEXTAREA' || t === 'SELECT' || target.isContentEditable;
}
