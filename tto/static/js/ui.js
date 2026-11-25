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
 * items: [{label, action, header, sep, disabled}]; {check: true, on, label, sub, id, action(on)} is a line with a tick
 * box (``id``: the box's) that leaves the menu open (several in a row can be changed); its action returns false to refuse
 * the change.
 */
export function menu(x, y, items) {
  closeMenu();
  const el = h('div', { class: 'menu', role: 'menu' });
  for (const it of items) {
    if (!it) continue;
    if (it.sep) { el.appendChild(h('div', { class: 'sep' })); continue; }
    if (it.header) { el.appendChild(h('div', { class: 'mh' }, it.header)); continue; }
    if (it.check) {
      const box = h('input', { type: 'checkbox', disabled: !!it.disabled, id: it.id || null });
      box.checked = !!it.on;
      box.addEventListener('change', () => { if (it.action(box.checked) === false) box.checked = !box.checked; });
      el.appendChild(h('label', { class: 'mcheck', title: it.title || null }, box, h('span', { class: 't' }, it.label),
        it.sub ? h('span', { class: 'sub' }, it.sub) : null));
      continue;
    }
    const b = h('button', { type: 'button', disabled: !!it.disabled }, it.label);
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

/** True when keyboard / clipboard events should be left to a form control. */
export function inFormControl(target) {
  if (!target || !target.tagName) return false;
  const t = target.tagName;
  return t === 'INPUT' || t === 'TEXTAREA' || t === 'SELECT' || target.isContentEditable;
}
