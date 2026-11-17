// Ctrl+K commands done (commands.js reads them): a dialog opened, a form filled - Günlük İşlemler, Trades, the trading list's
// "+ ISIN ekle" -, a saved scenario loaded after a confirmation naming it, the RET fair value's scenario view set (the
// user's own), a page or a launchpad opened.  Nothing here saves a trade or publishes a RET: the form's own button does.
import { api } from './api.js';
import { toast, confirmDialog } from './ui.js';

/** The trading list's "+ ISIN ekle" (DİBS RV!A5:A54 - its page's ``add`` definition, tto/views/60_dibs.json). */
export const TRADING_LIST = { book: 'tto', list: 'DİBS RV!A5:A54', name: 'dibs', catalog: true,
  title: 'DİBS RV listesine kâğıt ekle (trading listesi: DİBS ASW listesine de eklenir)' };

/**
 * Run a suggestion.  ``ctx``: the shell's (main.js) - openRet(opts), openTrade(spec) (Günlük İşlemler), openTradesForm(spec),
 * openAddIsin(isins), goto(page), openLaunchpad(name), refreshNow().  Nothing here saves a trade or publishes a RET.
 */
export async function runCommand(c, ctx) {
  if (!c || c.error || c.complete !== undefined) return;
  if (c.cmd === 'ret') { ctx.openRet(c.tab ? { tab: c.tab } : undefined); return; }
  if (c.cmd === 'blotter') {
    ctx.openTrade(Object.assign({ said: 'İşlem Ctrl+K\'den dolduruldu: kontrol edip kaydedin' }, c.spec));
    return;
  }
  if (c.cmd === 'trades') { await ctx.openTradesForm(c.spec); return; }
  if (c.cmd === 'isin') { await ctx.openAddIsin(c.isins); return; }
  if (c.cmd === 'retview') {
    await api.post('/api/ret/fair/view', { scenario: c.code });
    ctx.openRet({ tab: 'fair' });
    toast(c.code === 'piyasa' ? 'RET adil değer: piyasa görünümü' : 'RET adil değer: PPK senaryosu ' + c.code + ' (sizin görünümünüz)', 'ok');
    return;
  }
  if (c.cmd === 'scenario') {
    if (!(await confirmDialog('Senaryoyu yükle', '"' + c.name + '" senaryosu yüklensin mi? Kişisel girdileriniz bu senaryonunkilerle değişir '
      + '(kayıtlı senaryolarınız kalır).', 'Yükle'))) return;
    const res = await api.post('/api/scenarios/load', { name: c.name });
    toast('"' + c.name + '" yüklendi (' + res.cells + ' hücre)', 'ok');
    ctx.refreshNow();
    return;
  }
  if (c.cmd === 'page') { ctx.goto(c.id); return; }
  if (c.cmd === 'launchpad') ctx.openLaunchpad(c.name);
}

/**
 * The Trades page's "Yeni işlem" form (just opened) filled as the user would type it: the product chosen, then each box
 * written (its own input event - the form's defaults, sizing and preview follow), the sides clicked.  Nothing is saved.
 * ``spec``: {product, side, call_put, tenor (an OIS / SOFR's end, an option's expiry), notional, dv01, isin, pair}.
 */
export async function fillTradesForm(spec) {
  const form = await waitFor(() => document.getElementById('trade-form'), 4000);
  if (!form) throw new Error('Trades formu açılamadı');
  const click = (sel) => { const b = form.querySelector(sel); if (b && !b.classList.contains('on')) b.click(); return !!b; };
  const type = (name, value) => {
    const el = form.querySelector('#tf-' + name);              // (looked up again: a pair typed lays the form out anew)
    if (!el || value === undefined || value === null) return;
    el.value = value;
    el.dispatchEvent(new Event('input', { bubbles: true }));
  };
  if (spec.product) click('#tf-product button[data-v="' + spec.product + '"]');
  if (spec.pair) type('pair', spec.pair);
  if (spec.isin) type('isin', spec.isin);
  if (spec.side) click('#tf-side button[data-v="' + spec.side + '"]');
  if (spec.call_put) click('#tf-call_put button[data-v="' + spec.call_put + '"]');
  if (spec.tenor) type(spec.product === 'fxopt' ? 'expiry' : 'end_date', spec.tenor);
  if (spec.dv01) type('dv01', spec.dv01);
  if (spec.notional) type('notional', spec.notional);
  toast('Trades formu Ctrl+K\'den dolduruldu: kontrol edip "İşlemi kaydet"', 'ok', 4000);
}

/** ``fn()`` until it gives something (every 50 ms), at most ``ms``. */
export function waitFor(fn, ms) {
  return new Promise((resolve) => {
    const until = Date.now() + ms;
    const look = () => {
      const got = fn();
      if (got || Date.now() > until) { resolve(got || null); return; }
      setTimeout(look, 50);
    };
    look();
  });
}
