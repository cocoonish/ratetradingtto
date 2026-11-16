// Browser end-to-end test of the dashboard (Playwright + Chromium).
//
//   node tests/e2e/e2e.js http://localhost:1057 [screenshot-dir]
//
// The server must run in replay mode on a fresh data directory (tests/test_e2e.py does that).
const { chromium, request } = require('playwright');

const BASE = process.argv[2] || 'http://localhost:1057';
const SHOTS = process.argv[3] || null;
const results = [];
let failures = 0;

function check(name, cond, detail) {
  results.push({ name, ok: !!cond, detail });
  if (!cond) failures += 1;
  console.log((cond ? '  ok   ' : '  FAIL ') + name + (detail !== undefined && !cond ? '  -> ' + JSON.stringify(detail) : ''));
}

function trNumber(text) {
  // "517.371.847,91" -> 517371847.91 ; "34,60%" -> 34.6
  const s = String(text).replace('%', '').replace(/\./g, '').replace(',', '.').trim();
  return Number(s);
}

// the accounts are made by tests/test_e2e.py before the server starts (Ayşe Yılmaz: administrator), all with this password
const PASSWORD = process.env.TTO_E2E_PASSWORD || 'e2e-sifre-1';
const signedIn = {};                 // user key -> the page signed in as that user (its cookie is the session)

function keyOf(name) {
  return name.trim().split(/\s+/).join(' ').toLowerCase().replace(/̇/g, '').replace(/ı/g, 'i');
}

async function login(page, name) {
  await page.goto(BASE + '/');
  await page.waitForSelector('#login:not(.hidden)');
  await page.fill('#login-name', name);
  await page.fill('#login-pass', PASSWORD);
  await page.click('#login-form button[type=submit]');
  await page.waitForSelector('#app:not(.hidden)');
  await page.waitForFunction(() => document.querySelectorAll('#nav .nav-item').length > 5);
  signedIn[keyOf(name)] = page;
}

async function open(page, id) {
  await page.evaluate((x) => { window.location.hash = '#/' + x; }, id);
  // (one of the last pages opened comes back at once, as it was left, and is brought up to date: wait for that too)
  await page.waitForFunction((x) => window.tto.state.pageId === x && window.tto.state.page && window.tto.state.page.ready
    && !window.tto.state.refreshing, id.split('/')[0], { timeout: 90000 });
  await page.waitForTimeout(150);
}

/** Open a tab of the page ('*' = "Tümü": every table of the page). */
async function tab(page, id) {
  await page.evaluate((t) => window.tto.state.page.setTab(t), id);
  await page.waitForTimeout(500);                 // charts of the tab are drawn when they come on the page
}

const panelsOnPage = (page) => page.evaluate(() => [...document.querySelectorAll('#content .panel')].map((p) => p.dataset.panel));

/** A tab opened to find a cell may show its panels from before the last change for a moment (dimmed): wait. */
async function fresh(page) {
  await page.waitForFunction(() => !document.querySelector('#content .panel.stale'), null, { timeout: 30000 });
}

async function cellText(page, ref) {
  const found = await page.evaluate((r) => !!window.tto.findCell(r), ref);
  if (found) await fresh(page);
  return page.evaluate((r) => { const td = window.tto.findCell(r); return td ? td.textContent : null; }, ref);
}

async function cellHandle(page, ref) {
  if (await page.evaluate((r) => !!window.tto.findCell(r), ref)) await fresh(page);      // (its tab may have opened)
  const h = await page.evaluateHandle((r) => window.tto.findCell(r), ref);
  const el = h.asElement();
  if (!el) throw new Error('cell not on screen: ' + ref);
  await el.scrollIntoViewIfNeeded();
  return el;
}

async function typeInto(page, ref, text) {
  const el = await cellHandle(page, ref);
  await el.click();
  await page.keyboard.press('Enter');
  await page.waitForSelector('td.editing input');
  await page.keyboard.press('Control+a');
  await page.keyboard.type(text);
  await page.keyboard.press('Enter');
}

async function waitCell(page, ref, pred, timeout = 20000) {
  await page.waitForFunction(([r, p]) => {
    const td = window.tto.findCell(r);
    // eslint-disable-next-line no-new-func
    return td && new Function('t', 'return ' + p)(td.textContent);
  }, [ref, pred], { timeout });
}

const apiSessions = {};               // user key -> a sign-in of its own, for a user whose page was closed

async function api(page, user, method, path, body) {
  // the request goes with the session of that user's page - or, that page closed, with a sign-in of its own
  let as = signedIn[user] ? signedIn[user].request : page.request;
  if (signedIn[user] && signedIn[user].isClosed()) {
    if (!apiSessions[user]) {
      apiSessions[user] = await request.newContext();
      await apiSessions[user].post(BASE + '/api/login', { data: { name: user, password: PASSWORD } });
    }
    as = apiSessions[user];
  }
  const res = await as.fetch(BASE + path, { method, headers: { 'Content-Type': 'application/json' },
    data: body === undefined ? undefined : JSON.stringify(body) });
  return { status: res.status(), json: await res.json().catch(() => null) };
}

async function shot(page, name) {
  if (SHOTS) await page.screenshot({ path: SHOTS + '/' + name + '.png' });
}

(async () => {
  const browser = await chromium.launch();
  const ctxA = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
  await ctxA.grantPermissions(['clipboard-read', 'clipboard-write'], { origin: BASE });
  const page = await ctxA.newPage();
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error' && !/401|404|400/.test(m.text())) errors.push('console: ' + m.text()); });
  page.on('pageerror', (e) => errors.push('pageerror: ' + e.message));

  try {
    // ------------------------------------------------------------------ login
    console.log('login');
    await page.goto(BASE + '/');
    await page.waitForSelector('#login:not(.hidden)');
    check('nothing but the sign-in without a session', (await api(page, 'nobody', 'GET', '/api/status')).status === 401);
    await page.fill('#login-name', 'Ayşe Yılmaz');
    await page.fill('#login-pass', 'yanlis-sifre');
    await page.click('#login-form button[type=submit]');
    await page.waitForFunction(() => document.getElementById('login-err').textContent.length > 0);
    check('a wrong password is refused', /hatalı/.test(await page.textContent('#login-err')));
    await login(page, 'Ayşe Yılmaz');
    check('user chip shows the name', (await page.textContent('#user-name')) === 'Ayşe Yılmaz');
    check('an administrator has the Kullanıcılar page', (await page.locator('#nav .nav-item[data-page=users]').count()) === 1);
    await page.waitForFunction(() => document.querySelectorAll('.kpi').length >= 5);
    check('KPI strip is filled', (await page.locator('.kpi').count()) >= 5);
    check('mode badge says replay data', /KAYITLI/.test(await page.textContent('#mode-text')));
    check('nav lists the pages', (await page.locator('#nav .nav-item').count()) >= 20);
    await shot(page, '01-masa');

    // ------------------------------------------------------------------ editing an input
    console.log('forward page: edit, copy, paste');
    await open(page, 'forward');
    // a long page comes in tabs: the calculators first, the value date they read pinned above the tabs
    const tabs0 = await page.evaluate(() => [...document.querySelectorAll('.viewtabs button')].map((b) => b.dataset.tab + (b.classList.contains('on') ? '!' : '')));
    const on0 = await panelsOnPage(page);
    check('forward page opens on the calculators, the value date pinned above the tabs',
      tabs0.join(' ') === 'calc! fwd kot ret bulk curves off tick *' && on0.slice(0, 5).join(' ') === 'B1 B7 B8 B9 B10' && !on0.includes('B19') && !on0.includes('B15'), [tabs0, on0]);
    const caps = await page.evaluate(() => [...document.querySelectorAll('.panels.pinned .panel[data-panel="B1"] tr.hd td')].map((td) => td.textContent));
    check('the value date strip names its cells - each spot date with Bloomberg\'s beside it', caps.join('|')
      === '|Valör tarihi|USDTRY spot|EURTRY spot|USDTRY spot valörü|Bloomberg valörü|EURTRY spot valörü|Bloomberg valörü', caps);
    await page.click('.viewtabs button[data-tab="ret"]');
    const onRet = await panelsOnPage(page);
    check('a tab shows its own tables (and the pinned one)', onRet.join(' ') === 'B1 B19 B20 B26', onRet);
    check('the RET table has the button of the RET editor', await page.locator('.panel[data-panel="B19"] header button[data-action="ret"]').count() === 1);
    await page.fill('.page-tools input[type=search]', 'interest');
    const found = await panelsOnPage(page);
    check('the search box looks in every tab', found.join(' ') === 'B1 B7 B8 B9 B10', found);
    await page.fill('.page-tools input[type=search]', '');
    await page.reload();
    await page.waitForFunction(() => window.tto && window.tto.state.pageId === 'forward' && window.tto.state.page && window.tto.state.page.ready, null, { timeout: 90000 });
    check('the open tab is remembered', (await panelsOnPage(page)).join(' ') === 'B1 B19 B20 B26');
    await tab(page, '*');
    check('forward page has many tables', (await page.locator('table.grid').count()) >= 20);
    check('"Tümü" lists the tabs one after the other', await page.locator('#content .secthead').count() === 8);
    await tab(page, 'calc');
    // (EK_FWD!E50: RET bid of the USDTRY table of the "Forward fiyatları" tab - the sheet's Forward!D33)
    check('a cell of another tab is found - its tab opens', (await cellText(page, 'EK_FWD!E50')) !== null
      && (await page.evaluate(() => document.querySelector('.viewtabs button.on').dataset.tab)) === 'fwd');
    const before = await cellText(page, 'EK_FWD!E50');
    await typeInto(page, 'Forward!D2', '15.12.2026');
    await waitCell(page, 'Forward!D2', "t.trim() === '15.12.2026'");
    await page.waitForFunction(([r, b]) => { const td = window.tto.findCell(r); return td && td.textContent !== b; }, ['EK_FWD!E50', before]);
    const retBid = trNumber(await cellText(page, 'EK_FWD!E50'));
    const q = await api(page, 'ayşe yilmaz', 'POST', '/api/blotter/quote/forward', { value_date: '15.12.2026', basis: 'RET_BID', amount: 1000000 });
    check('typed value date reprices the RET forward (sheet = pricing API)', Math.abs(retBid - q.json.forward) < 6e-5, [retBid, q.json.forward]);
    check('edited cell is marked as personal input', await page.evaluate(() => window.tto.findCell('Forward!D2').classList.contains('mod')));

    // ------------------------------------------------------------------ a value of my own over a formula ("Elle değer")
    const e33 = (await cellText(page, 'EK_FWD!F50')).trim();             // RET mid of the USDTRY table: a formula
    await (await cellHandle(page, 'EK_FWD!F50')).click();
    await page.keyboard.press('Enter');
    await page.waitForTimeout(200);
    check('a formula is not typed over by accident', await page.locator('td.editing').count() === 0);
    await page.click('#hand-mode');
    await typeInto(page, 'EK_FWD!F50', '55');
    await waitCell(page, 'EK_FWD!F50', "t.trim() === '55,0000'");
    check('with "Elle değer" on, a value typed over a formula is shown as mine',
      await page.evaluate(() => { const td = window.tto.findCell('EK_FWD!F50'); return td.classList.contains('hand') && td.classList.contains('in'); }));
    await page.waitForFunction(() => /^1 formül yerine elle değer/.test(document.getElementById('hand-values').textContent), null, { timeout: 15000 });
    check('the page says how many formulas are replaced', await page.locator('#hand-values:not(.hidden)').count() === 1);
    await (await cellHandle(page, 'EK_FWD!F50')).click();
    await page.keyboard.press('Delete');
    await waitCell(page, 'EK_FWD!F50', 't.trim() === "' + e33 + '"');
    check('deleting the value brings the formula back', await page.evaluate(() => !window.tto.findCell('EK_FWD!F50').classList.contains('in')));
    await typeInto(page, 'EK_FWD!F50', '56');
    await waitCell(page, 'EK_FWD!F50', "t.trim() === '56,0000'");
    await page.waitForSelector('#hand-values:not(.hidden)');
    await page.click('#hand-values');
    await page.click('.modal .mfoot .btn.primary');
    await waitCell(page, 'EK_FWD!F50', 't.trim() === "' + e33 + '"');
    await page.waitForSelector('#hand-values.hidden', { state: 'attached' });
    check('"formüle dön" restores every replaced formula of the page', true);
    await page.click('#hand-mode');
    // the calculators take spot, dates and the foreign rate by hand; blanking returns to the market
    const sp0 = (await cellText(page, 'Forward!AH11')).trim();
    check('a calculator input the sheet fills by itself is marked as such', await page.evaluate(() => window.tto.findCell('Forward!AH8').classList.contains('auto')));
    await typeInto(page, 'Forward!AH8', '50,50');
    await page.waitForFunction((b) => { const td = window.tto.findCell('Forward!AH11'); return td && td.textContent.trim() !== b; }, sp0, { timeout: 15000 });
    check('a calculator priced at a spot typed by hand',
      await page.evaluate(() => { const td = window.tto.findCell('Forward!AH8'); return td.classList.contains('hand') && td.textContent.trim() === '50,5000'; }));
    await (await cellHandle(page, 'Forward!AH8')).click();
    await page.keyboard.press('Delete');
    await waitCell(page, 'Forward!AH11', 't.trim() === "' + sp0 + '"');
    check('blanking it returns to the market spot', await page.evaluate(() => window.tto.findCell('Forward!AH8').classList.contains('auto')));

    // ------------------------------------------------------------------ copy to Excel
    await (await cellHandle(page, 'EK_FWD!A46')).click();
    await (await cellHandle(page, 'EK_FWD!D50')).click({ modifiers: ['Shift'] });
    await page.keyboard.press('Control+c');
    await page.waitForTimeout(200);
    const copied = await page.evaluate(() => navigator.clipboard.readText());
    const lines = copied.split('\r\n');
    check('copy gives one line per row', lines.length === 5, lines.length);
    check('copy is tab separated', lines.every((l) => l.split('\t').length === 4), copied);
    check('copy keeps the header text', lines[0] === 'Eğri\tTRY bid %\tTRY mid %\tTRY ask %', lines[0]);
    check('copied numbers use the Turkish decimal comma', /^RET\t\d+,\d{4}\t\d+,\d{4}\t\d+,\d{4}$/.test(lines[4]), lines[4]);
    check('status bar shows the selected range', /EK_FWD!A46:D50/.test(await page.textContent('#sb-addr')));
    check('status bar sums the numbers', /Toplam/.test(await page.textContent('#sb-stat')));

    // full precision copy
    await (await cellHandle(page, 'EK_FWD!E50')).click();
    await page.keyboard.press('Control+Shift+C');
    await page.waitForTimeout(200);
    const full = await page.evaluate(() => navigator.clipboard.readText());
    check('full precision copy has more digits', full.replace(/[^0-9]/g, '').length >= 10, full);

    // ------------------------------------------------------------------ paste RET from Excel
    await page.evaluate(() => navigator.clipboard.writeText('35,10%\t35,30%\r\n35,20%\t35,40%\r\n34,50%\t34,70%\r\n'));
    await (await cellHandle(page, 'Forward!W33')).click();
    await page.keyboard.press('Control+v');
    await waitCell(page, 'Forward!W33', "t.trim() === '35,10%'");
    check('pasted RET bid shows in the sheet', (await cellText(page, 'Forward!W34')).trim() === '35,20%');
    check('pasted RET ask shows in the sheet', (await cellText(page, 'Forward!X35')).trim() === '34,70%');
    const ret1 = await api(page, 'ayşe yilmaz', 'GET', '/api/ret');
    check('RET curve stored on the server', Math.abs(ret1.json.rows[0].bid - 0.351) < 1e-12 && Math.abs(ret1.json.rows[2].ask - 0.347) < 1e-12, ret1.json.rows.slice(0, 3));
    const hist1 = await api(page, 'ayşe yilmaz', 'GET', '/api/ret/history');
    check('RET upload is in the history', hist1.json.history.length === 1 && hist1.json.history[0].user === 'ayşe yilmaz');
    await shot(page, '02-forward');

    // ------------------------------------------------------------------ the forward pricing tab
    await tab(page, 'fwd');
    const onFwd = await panelsOnPage(page);
    check('forward pricing: USDTRY and EURTRY one below the other, then the free forwards and the TRY rates by tenor',
      onFwd.join(' ') === 'B1 FR1 FR2 FR3 FR4 B16 B18', onFwd);
    check('the USDTRY table shows the TRY mid and the daily swap points', (await cellText(page, 'EK_FWD!C46')) === 'TRY mid %'
      && (await cellText(page, 'EK_FWD!L46')) === 'P/gün mid' && trNumber(await cellText(page, 'EK_FWD!L50')) > 0);
    // "Elle": a curve from the list, then a spread to its mid
    const oisMid = trNumber(await cellText(page, 'EK_FWD!C48'));
    await (await cellHandle(page, 'EK_FWD!B52')).click();
    await page.keyboard.press('Enter');
    await page.click('.menu button:text-is("OIS")');
    await waitCell(page, 'EK_FWD!B52', "t.trim() === 'OIS'");
    await typeInto(page, 'EK_FWD!F52', '25');
    await waitCell(page, 'EK_FWD!C51', 'Math.abs(Number(t.replace(".", "").replace(",", ".")) - ' + (oisMid + 0.25) + ') < 0.00011');
    check('"Elle" prices the chosen curve plus a spread - the EURTRY table too', Math.abs(trNumber(await cellText(page, 'EK_FWD!C62')) - (oisMid + 0.25)) < 0.00011,
      [await cellText(page, 'EK_FWD!C62'), oisMid]);
    // the free forward list: an end date is enough - spot and both rates come from the curves; the next row opens
    check('the free forward list shows its first empty rows only', await page.evaluate(() => {
      const rows = [...document.querySelectorAll('.panel[data-panel="FR3"] tbody tr')];
      return rows.filter((tr) => tr.classList.contains('grow-hidden')).length === 7;
    }));
    await typeInto(page, 'EK_FWD!C68', '15.12.2026');
    await waitCell(page, 'EK_FWD!I68', 't.trim() !== ""');
    const fwdSpot = trNumber(await cellText(page, 'EK_FWD!E68'));
    check('a free forward from the spot: the spot, the major and the minor rate filled by themselves',
      Math.abs(fwdSpot - trNumber(await cellText(page, 'EK_FWD!F45'))) < 1e-9 && trNumber(await cellText(page, 'EK_FWD!F68')) > 0
      && Math.abs(trNumber(await cellText(page, 'EK_FWD!G68')) - trNumber(await cellText(page, 'EK_FWD!M68'))) < 0.006
      && trNumber(await cellText(page, 'EK_FWD!I68')) > fwdSpot);
    const curves68 = [];
    for (const c of ['J68', 'K68', 'L68', 'M68']) curves68.push(trNumber(await cellText(page, 'EK_FWD!' + c)));
    check('the four TRY curves stand beside it at its end date', curves68.every((x) => x > 0), curves68);
    await typeInto(page, 'EK_FWD!G68', '30');
    await waitCell(page, 'EK_FWD!G68', "t.trim() === '30,0000'");
    const days68 = trNumber(await cellText(page, 'EK_FWD!D68'));
    const major68 = trNumber(await cellText(page, 'EK_FWD!F68'));
    await waitCell(page, 'EK_FWD!I68', 'Math.abs(Number(t.replace(".", "").replace(",", ".")) - ' +
      (fwdSpot * (1 + 0.30 * days68 / 360) / (1 + major68 / 100 * days68 / 360)) + ') < 0.0002');
    check('a minor rate typed over the curve prices the forward', true);
    check('the TRY rates by tenor: VİOP has none at 2Y, the others do', (await cellText(page, 'EK_FWD!F92')).trim() === ''
      && trNumber(await cellText(page, 'EK_FWD!E92')) > 0);
    await shot(page, '02b-forward-pricing');
    // "Kota mesajı": the rows of a table as lines to send - the set of columns and the rows picked are remembered
    await page.click('.panel[data-panel="FR1"] button[data-action="quote"]');
    await page.waitForSelector('#quote-dialog #quote-text');
    await page.click('#quote-set button[data-v="pts"]');
    let qlines = (await page.inputValue('#quote-text')).split('\n');
    check('"Kota mesajı": the swap points of the USDTRY table, a curve a line, the value date in the heading',
      /^USDTRY · puan · \d\d\.\d\d\.\d{4}$/.test(qlines[0]) && qlines.length === 6 && /^Offshore\s+[\d.]+ \/ [\d.]+$/.test(qlines[1]), qlines);
    await page.click('#quote-rows input[data-key="48"]');
    qlines = (await page.inputValue('#quote-text')).split('\n');
    check('... a row left out leaves the message', qlines.length === 5 && !qlines.some((l) => l.startsWith('OIS ')), qlines);
    await page.click('#quote-dialog button:text-is("Kapat")');
    // "İşlem gir": a row and a side - Günlük İşlemler opens with the pair, the side, the value date and the swap points
    const fwdValue = (await cellText(page, 'EK_FWD!B45')).trim();
    const offAsk = (await cellText(page, 'EK_FWD!J47')).trim();
    await page.click('.panel[data-panel="FR1"] button[data-action="trade"]');
    await page.waitForSelector('#trade-dialog');
    await page.click('#trade-rows input[data-key="47"]');
    await page.click('#trade-dir button[data-v="S"]');
    check('the trade dialog says what will be filled', (await page.textContent('#trade-summary')).includes('swap puanı ' + offAsk),
      [await page.textContent('#trade-summary'), offAsk, fwdValue]);
    await page.click('#trade-open');
    await page.waitForFunction(() => window.tto.state.pageId === 'blotter' && window.tto.state.page && window.tto.state.page.fwd
      && window.tto.state.page.fwd.date && window.tto.state.page.fwd.date.value !== '', null, { timeout: 30000 });
    const fwdFilled = await page.evaluate(() => { const f = window.tto.state.page.fwd; return [f.pair, f.dir, f.basis, f.date.value, f.manual.value, f.note.value]; });
    await page.waitForFunction(() => /\d/.test((document.querySelector('.entry .pad:not(.hidden) .quotebox [data-k="fwd-forward"] .v') || {}).textContent || ''), null, { timeout: 20000 });
    check('... Günlük İşlemler opens on the forward: USDTRY sold at the ask points of the offshore row, the table\'s value date',
      JSON.stringify(fwdFilled.slice(0, 5)) === JSON.stringify(['USDTRY', 'S', 'SP', fwdValue, offAsk]) && /^Kota: Offshore/.test(fwdFilled[5]), [fwdFilled, fwdValue, offAsk]);
    await open(page, 'forward');
    await tab(page, 'fwd');

    // ------------------------------------------------------------------ RET editor dialog
    console.log('RET editor');
    await page.click('#btn-ret');
    await page.waitForSelector('.modal table.ret');
    const firstBid = await page.inputValue('.modal table.ret tbody tr:nth-child(1) td:nth-child(3) input');
    check('editor shows the stored curve in percent', firstBid === '35,1', firstBid);
    await page.evaluate(() => navigator.clipboard.writeText('Vade\tBid\tAsk\r\n1M\t34,00\t34,20\r\n3M\t35,1\t35,6\r\n1Y\t0,381\t0,392\r\n'));
    await page.click('.modal table.ret tbody tr:nth-child(1) td:nth-child(3) input');
    await page.keyboard.press('Control+v');
    await page.waitForFunction(() => document.querySelector('.modal table.ret tbody tr:nth-child(6) td:nth-child(3) input').value === '34,00');
    await shot(page, '03-ret-editor');
    await page.click('.modal .mfoot .btn.primary');
    await page.waitForFunction(() => /RET faizleri kaydedildi/.test(document.getElementById('toasts').textContent));
    const ret2 = await api(page, 'ayşe yilmaz', 'GET', '/api/ret');
    const byTenor = Object.fromEntries(ret2.json.rows.map((r) => [r.tenor, r]));
    check('pasted 1M row saved (34,00 / 34,20)', Math.abs(byTenor['1M'].bid - 0.34) < 1e-12 && Math.abs(byTenor['1M'].ask - 0.342) < 1e-12, byTenor['1M']);
    check('pasted 3M row saved (35,1 / 35,6)', Math.abs(byTenor['3M'].bid - 0.351) < 1e-12 && Math.abs(byTenor['3M'].ask - 0.356) < 1e-12, byTenor['3M']);
    check('fractions are accepted too (0,381 / 0,392)', Math.abs(byTenor['1Y'].bid - 0.381) < 1e-12 && Math.abs(byTenor['1Y'].ask - 0.392) < 1e-12, byTenor['1Y']);
    check('rows that were not pasted keep their value', Math.abs(byTenor['ON'].bid - 0.351) < 1e-12, byTenor['ON']);
    await page.click('.modal .mfoot .btn:not(.primary)');
    await waitCell(page, 'Forward!W38', "t.trim() === '34,00%'");
    check('sheet follows the editor', (await cellText(page, 'Forward!X40')).trim() === '35,60%');
    // change the whole curve at once, and take it along to send
    await page.click('.panel[data-panel="B19"] header button[data-action="ret"]');
    await page.waitForSelector('#ret-shift');
    const bidBefore = await page.inputValue('.modal table.ret tbody tr:nth-child(1) td:nth-child(3) input');
    const retRows = () => page.evaluate(() => [...document.querySelectorAll('.modal table.ret tbody tr')].map((tr) => ({
      tenor: tr.children[0].textContent, bid: tr.children[2].querySelector('input').value, ask: tr.children[3].querySelector('input').value,
      spread: tr.children[5].textContent, bp: tr.children[6].querySelector('input').value, next: tr.children[7].textContent })));
    const ret0 = await retRows();
    check('the RET editor shows every maturity\'s bid-ask spread in bp', ret0.every((r) => !r.bid || !r.ask
      || Math.abs(trNumber(r.spread) - Math.round((trNumber(r.ask) - trNumber(r.bid)) * 1000) / 10) < 0.051), ret0.map((r) => r.spread));
    const onAsk = '.modal table.ret tbody tr:nth-child(1) td:nth-child(4) input';
    await page.fill(onAsk, (trNumber(ret0[0].ask) + 0.1).toFixed(2).replace('.', ','));
    const retWider = await retRows();
    const bpTr = (x) => (Math.abs(x - Math.round(x)) > 1e-9 ? x.toFixed(1).replace('.', ',') : String(Math.round(x)));
    check('... a changed side shows the spread before and now', retWider[0].spread === ret0[0].spread + ' → ' + bpTr(trNumber(ret0[0].spread) + 10), [ret0[0], retWider[0]]);
    await page.fill(onAsk, ret0[0].ask);
    check('... and back to one number when it is the same again', (await retRows())[0].spread === ret0[0].spread);
    await page.fill('#ret-shift', '25');
    const retShown = await retRows();
    check('"Tümünü kaydır" shows next to every maturity by how much it moves and what it becomes',
      retShown.length === 15 && retShown.every((r) => r.bp === '25') && retShown[5].next === '34,25 / 34,45' && retShown[0].bid === ret0[0].bid, retShown.slice(0, 6));
    // hold the overnight rate: blank its box; give 1W an amount of its own - neither follows "Tümünü kaydır" any more
    await page.fill('.modal table.ret tbody tr:nth-child(1) input.ret-bp', '');
    await page.fill('.modal table.ret tbody tr:nth-child(3) input.ret-bp', '10');
    await page.fill('#ret-shift', '30');
    const retHeld = await retRows();
    check('a maturity blanked in its own row is held, one typed by hand keeps its amount',
      retHeld[0].bp === '' && retHeld[0].next === 'sabit' && retHeld[2].bp === '10' && retHeld[1].bp === '30' && retHeld[5].next === '34,3 / 34,5'
      && (await page.textContent('#ret-pending')) === '14 vade kayacak · 1 vade sabit', [retHeld.slice(0, 3), await page.textContent('#ret-pending')]);
    await page.click('#ret-side-bid');
    check('the side that moves can be the bid alone (and the spread it leaves)', /^34,3 \/ 34,2 · spread [-−]?\d/.test((await retRows())[5].next), (await retRows())[5]);
    await page.click('#ret-side-both');
    await page.fill('#ret-shift', '25');
    await page.click('.modal .mfoot .btn.primary');                       // "Kaydet" with a shift that is only previewed
    await page.waitForFunction(() => /henüz uygulanmadı/.test(document.getElementById('toasts').textContent));
    check('a shift that is only previewed is not saved by accident', (await retRows())[5].ask === ret0[5].ask);
    await page.click('#ret-shift-apply');
    const retAfter = await retRows();
    const bidBefore2 = ret0[1].bid, bidAfter = retAfter[1].bid;
    check('"Uygula" moves the others and leaves the held maturity where it was', retAfter[0].bid === bidBefore && retAfter[0].ask === ret0[0].ask
      && trNumber(bidAfter) === trNumber(bidBefore2) + 0.25 && trNumber(retAfter[2].bid) === trNumber(ret0[2].bid) + 0.10
      && retAfter[5].ask === '34,45' && retAfter.every((r) => r.bp === '' && r.next === ''), [ret0.slice(0, 3), retAfter.slice(0, 3)]);
    await page.click('#ret-copy-msg');
    await page.waitForTimeout(300);
    const msg = (await page.evaluate(() => navigator.clipboard.readText())).replace(/\r\n/g, '\n');   // Windows: CRLF
    check('"Kopyala (mesaj)": the curve as text for a chat window', /^TRY RET · \d\d\.\d\d\.\d{4}\n/.test(msg) && msg.includes('\n1M   34,25 / 34,45\n'), msg.slice(0, 160));
    await page.click('#ret-copy');
    await page.waitForTimeout(300);
    const tsv = (await page.evaluate(() => navigator.clipboard.readText())).split('\r\n');
    check('"Kopyala (tablo)": tenor, days, bid, ask as cells', tsv[0] === 'Vade\tGün\tBid\tAsk' && tsv.includes('1M\t30\t34,25\t34,45') && tsv.length === 16, tsv.slice(0, 7));
    await page.click('.modal .mfoot .btn:not(.primary)');                 // closed without saving: the sheet keeps the stored curve
    check('nothing changes until the curve is saved', (await cellText(page, 'Forward!W38')).trim() === '34,00%');

    // ------------------------------------------------------------------ scenarios
    console.log('scenarios');
    await page.click('#btn-scen');
    await page.waitForSelector('.modal input[placeholder^="Senaryo adı"]');
    await page.fill('.modal input[placeholder^="Senaryo adı"]', 'E2E senaryo');
    await page.click('.modal .btn.primary');
    await page.waitForFunction(() => /E2E senaryo/.test(document.querySelector('.modal table.plain')?.textContent || ''));
    await page.keyboard.press('Escape');
    await typeInto(page, 'Forward!D2', '01.03.2027');
    await waitCell(page, 'Forward!D2', "t.trim() === '01.03.2027'");
    await page.click('#btn-scen');
    await page.waitForSelector('.modal table.plain .btn.primary');
    await page.click('.modal table.plain .btn.primary');             // Yükle
    await page.keyboard.press('Escape');
    await waitCell(page, 'Forward!D2', "t.trim() === '15.12.2026'");
    check('loading a scenario restores the personal inputs', true);
    const sc = await api(page, 'ayşe yilmaz', 'GET', '/api/scenarios');
    check('scenario is stored under the user', sc.json.scenarios.length === 1 && sc.json.scenarios[0].name === 'E2E senaryo');

    // ------------------------------------------------------------------ blotter
    console.log('blotter');
    await open(page, 'blotter');
    await page.fill('.form input[placeholder^="örn. 10m"]', '10m');
    await page.fill('.form input[placeholder="gg.aa.yyyy"]', '15.12.2026');
    await page.waitForSelector('.quote .q.big');
    await page.waitForFunction(() => /\d/.test(document.querySelector('.quote .q.big .v').textContent));
    const tiles = await page.evaluate(() => [...document.querySelectorAll('.quotebox .q')].map((x) => [x.querySelector('.l').textContent, x.querySelector('.v').textContent]));
    const tl = trNumber(tiles[0][1]), fwd = trNumber(tiles[1][1]);
    const qm = await api(page, 'ayşe yilmaz', 'POST', '/api/blotter/quote/forward', { value_date: '15.12.2026', basis: 'RET_MID', amount: 10000000 });
    check('TL amount = amount × forward (RET mid)', Math.abs(tl - 10000000 * qm.json.forward) < 0.006, [tl, 10000000 * qm.json.forward]);
    check('forward tile shows the RET mid forward', Math.abs(fwd - qm.json.forward) < 6e-5, [fwd, qm.json.forward]);
    const dvTile = await page.evaluate(() => { const q = document.querySelector('.entry .pad:not(.hidden) .quotebox [data-k="dv01-tl"] .v'); return q ? q.textContent : null; });
    check('the forward being typed shows its DV01 (the sheet\'s "Forward DV01" block)', dvTile !== null && dvTile[0] === '+'
      && Math.abs(trNumber(dvTile.slice(1)) - qm.json.dv01.tl) < 1, [dvTile, qm.json.dv01]);
    await page.click('.entry .pad:not(.hidden) .row.actions .btn.primary');
    await page.waitForFunction(() => document.querySelectorAll('.lists .panel:nth-child(1) table.grid tr').length === 2);
    check('saved forward appears in the list', true);

    // manual forward rate
    await page.fill('.form input[placeholder^="örn. 10m"]', '2.500.000');
    await page.click('.seg button[data-v="FWD"]');
    await page.fill('.form input[placeholder="örn. 52,1000"]', '52,10');
    await page.waitForFunction(() => /130\.250\.000,00/.test(document.querySelector('.quote .q.big .v')?.textContent || ''));
    check('manual forward rate: 2.500.000 × 52,10 = 130.250.000,00 TL', true);
    await page.click('.seg button[data-v="S"]');
    await page.click('.entry .pad:not(.hidden) .row.actions .btn.primary');
    await page.waitForFunction(() => document.querySelectorAll('.lists .panel:nth-child(1) table.grid tr').length === 3);

    // OIS spread
    await page.click('.entry .tabs button:nth-child(2)');
    await page.click('.seg button[data-v="spread"]');
    await page.click('.seg button[data-v="FLATTENER"]');
    await page.waitForFunction(() => /Piyasa mid/.test(document.querySelector('.entry .pad:not(.hidden) .echo')?.textContent || ''));
    await page.fill('input[placeholder="örn. -125"]', '25');
    await page.waitForFunction(() => document.querySelectorAll('.entry .pad:not(.hidden) .quotebox .q').length >= 5);
    const oisTiles = await page.evaluate(() => [...document.querySelectorAll('.entry .pad:not(.hidden) .quotebox .q')].map((x) => x.textContent));
    check('OIS spread quote shows a cost in bp', /bp/.test(oisTiles[0]), oisTiles);
    const legRows = await page.locator('.entry .pad:not(.hidden) .quotebox table.grid tr').count();
    check('spread expands into two legs', legRows === 3, legRows);
    await page.click('.entry .pad:not(.hidden) .row.actions .btn.primary');
    await page.waitForFunction(() => document.querySelectorAll('.lists .panel:nth-child(2) table.grid tr').length === 3);
    check('OIS legs are booked', true);
    const netTile = await page.evaluate(() => (document.querySelector('.entry .pad:not(.hidden) .quotebox [data-k="dv01-net"] .v') || {}).textContent || null);
    check('the OIS being typed shows its net DV01', netTile !== null && /^[+-]?\d/.test(netTile), netTile);
    const risk = await page.evaluate(() => [...document.querySelectorAll('.riskbar .q')].map((q) => q.dataset.k + '=' + q.querySelector('.v').textContent));
    const fwdHead = await page.evaluate(() => [...document.querySelectorAll('.lists .panel:nth-child(1) table.grid tr:first-child td')].map((td) => td.textContent));
    check('saved trades carry their DV01, summed above the lists',
      risk.length === 4 && /^risk-total=[+-]\d/.test(risk[0]) && /^risk-fwd=[+-]\d/.test(risk[1]) && fwdHead.includes('DV01 (TL)') && fwdHead.includes('DV01 ($)'), [risk, fwdHead]);
    // a period instead of a day
    await page.click('.rangebox button:has-text("Son 30 gün")');
    await page.waitForFunction(() => window.tto.state.page && window.tto.state.page.data && window.tto.state.page.data.ranged, null, { timeout: 20000 });
    await page.waitForFunction(() => (document.querySelector('.lists .panel:nth-child(1) table.grid tr td') || {}).textContent === 'Tarih');
    check('a period up to today lists the trades of its days with their date and keeps today\'s entry form',
      await page.locator('.entry.hidden').count() === 0 && /^Aralık: /.test(await page.textContent('#content .banner:not(.hidden)'))
      && /bugüne .* yazılır/.test(await page.textContent('#content .banner:not(.hidden)'))
      && await page.locator('.lists .panel:nth-child(1) table.grid tr').count() === 3 && await page.locator('.lists td.act button').count() >= 2);
    await page.evaluate(() => window.tto.state.page.show('2026-10-01', '2026-10-31'));
    await page.waitForFunction(() => window.tto.state.page.data && window.tto.state.page.data.to === '2026-10-31', null, { timeout: 20000 });
    check('... a period that ends before today is to look at only', await page.locator('.entry.hidden').count() === 1 && !(await page.evaluate(() => window.tto.state.page.data.can_enter)));
    await page.click('.rangebox button:has-text("Son 30 gün")');
    await page.waitForFunction(() => window.tto.state.page.data && window.tto.state.page.data.can_enter && window.tto.state.page.data.ranged, null, { timeout: 20000 });
    const [period] = await Promise.all([page.waitForEvent('download'), page.click('button:has-text("Gün sonu arşivi")')]);
    check('the period downloads as one file', /^Blotter_\d{4}\.\d{2}\.\d{2}-\d{4}\.\d{2}\.\d{2}\.xlsx$/.test(period.suggestedFilename()), period.suggestedFilename());
    await page.click('#blotter-today');
    await page.waitForFunction(() => window.tto.state.page && window.tto.state.page.data && window.tto.state.page.data.is_today, null, { timeout: 20000 });
    await page.waitForFunction(() => document.querySelectorAll('.lists .panel:nth-child(1) table.grid tr').length === 3);
    check('"Bugün" returns to the day and its entry form', await page.locator('.entry.hidden').count() === 0 && await page.locator('.lists td.act button').count() >= 2);
    await shot(page, '04-blotter');

    // ------------------------------------------------------------------ second user: shared vs personal
    console.log('second user');
    const ctxB = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
    const pageB = await ctxB.newPage();
    pageB.on('pageerror', (e) => errors.push('pageerror(B): ' + e.message));
    await login(pageB, 'Mehmet');
    check('a user has no Kullanıcılar page', (await pageB.locator('#nav .nav-item[data-page=users]').count()) === 0);
    check('the Yedekleme page is for administrators: not in the menu of a user, in the menu of the administrator',
      (await pageB.locator('#nav .nav-item[data-page=backup]').count()) === 0 && (await page.locator('#nav .nav-item[data-page=backup]').count()) === 1);
    check('a user has no sheet explorer', (await pageB.locator('#nav .nav-item[data-page=explorer]').count()) === 0);
    check('the Motor page is for administrators: not in the menu of a user, in the menu of the administrator',
      (await pageB.locator('#nav .nav-item[data-page=motor]').count()) === 0 && (await page.locator('#nav .nav-item[data-page=motor]').count()) === 1);
    await open(pageB, 'blotter');
    await pageB.waitForFunction(() => document.querySelectorAll('.lists .panel:nth-child(1) table.grid tr').length === 3);
    check('another user sees the saved forwards', true);
    check('another user sees who saved them', /Ayşe Yılmaz/.test(await pageB.textContent('.lists .panel:nth-child(1)')));
    await open(pageB, 'forward');
    check('shared RET curve is the same for the other user', (await cellText(pageB, 'Forward!W38')).trim() === '34,00%');
    check('personal inputs are not shared', (await cellText(pageB, 'Forward!D2')).trim() !== '15.12.2026', await cellText(pageB, 'Forward!D2'));

    // live update: A deletes a trade while B watches the blotter
    await open(pageB, 'blotter');
    page.once('dialog', (d) => d.accept());
    await page.click('.lists .panel:nth-child(1) table.grid td.act button');
    await page.waitForSelector('.modal .mfoot .btn.primary');
    await page.click('.modal .mfoot .btn.primary');
    await pageB.waitForFunction(() => document.querySelectorAll('.lists .panel:nth-child(1) table.grid tr').length === 2, null, { timeout: 15000 });
    check('deleting a trade updates the other user\'s screen live', true);
    await ctxB.close();

    // ------------------------------------------------------------------ broker chat
    console.log('broker chat');
    // the board's stale limit: a day here, so that what the chat below said earlier today is still a best price whenever this
    // runs (the limit itself is checked further down)
    await api(page, 'ayşe yilmaz', 'POST', '/api/broker/settings', { stale_minutes: 1440 });
    await open(page, 'broker');
    check('Broker Chat is a page of the desk, next to the blotter',
      await page.evaluate(() => { const a = [...document.querySelectorAll('#nav .nav-item')].map((x) => x.dataset.page); return a.indexOf('broker') === a.indexOf('blotter') + 1; })
      && /Henüz kota yok/.test(await page.textContent('#broker-board-panel')) && await page.isDisabled('#broker-save'));
    const CHAT = ['10:23:58 3y5y ois /-75 offer', '10:29:57 1y5y ois -64/-60', '12:11:55 9x12m ois fra 33.80/34.10', '12:15:38 18m ois 35.03/35.23',
      '12:18:04 2y3y4y ois 12/ bid', 'MIKE REES', '18m ois 10/14', '13:33:59', '18m ois taken at 14', '13:41:09', 'ref 18m ois offer', '13:55:37',
      'EVREN DIKME', '6m OIS 35.88 bid', '16:40:10', '6m OIS 90 bid', '16:48:21', '1yr x 38.60/80 , bid nl', '17:00:01', 'selam', '17:00:05'].join('\n');
    const brokerBoard = () => page.evaluate(() => [...document.querySelectorAll('#broker-board-panel table.grid tr')].slice(1).map((tr) => [...tr.children].map((td) => td.textContent)));
    // the log's lines without the tick box, with whose line it is (Taraf) moved to the end
    const brokerLog = () => page.evaluate(() => [...document.querySelectorAll('#broker-log-panel table.grid tr')].slice(1).map((tr) => {
      const cells = [...tr.children].map((td) => td.textContent).slice(1);
      const whose = cells.splice(window.tto.state.page.data.ranged ? 3 : 2, 1)[0];
      return cells.concat([whose]);
    }));
    await page.fill('#broker-source', 'Tullett');
    await page.fill('#broker-text', CHAT);
    await page.waitForFunction(() => document.querySelectorAll('#broker-preview table tr').length === 13, null, { timeout: 20000 });
    // the preview's lines without whose line it is (checked on its own below)
    const chatSeen = await page.evaluate(() => [...document.querySelectorAll('#broker-preview table tr')].slice(1).map((tr) => [...tr.children].map((td) => td.textContent)
      .filter((_, k) => k !== 1)));
    const chatWhose = await page.evaluate(() => [...document.querySelectorAll('#broker-preview table tr')].slice(1).map((tr) => tr.children[1].textContent));
    check('a pasted chat is read while it is typed: time, instrument, bid, ask',
      JSON.stringify(chatSeen[0].slice(0, 4)) === JSON.stringify(['10:23:58', '3Y–5Yspread · bp', '', '-75'])
      && JSON.stringify(chatSeen[1].slice(0, 4)) === JSON.stringify(['10:29:57', '1Y–5Yspread · bp', '-64', '-60'])
      && JSON.stringify(chatSeen[2].slice(0, 4)) === JSON.stringify(['12:11:55', '9x12fra', '33,80', '34,10'])
      && JSON.stringify(chatSeen[3].slice(0, 4)) === JSON.stringify(['12:15:38', '18M', '35,03', '35,23'])
      && JSON.stringify(chatSeen[4].slice(0, 4)) === JSON.stringify(['12:18:04', '2Y–3Y–4Yfly · bp', '12', '']), chatSeen.slice(0, 5));
    check('the big figure of a shortened level is completed, a trade and a ref are told apart, the time under the message is its time',
      JSON.stringify(chatSeen[5].slice(0, 4)) === JSON.stringify(['13:33:59', '18M', '35,10', '35,14'])
      && chatSeen[6][0] === '13:41:09' && chatSeen[6][4] === '35,14' && /^İşlem · offer alındı/.test(chatSeen[6][5])
      && /^Ref · offer/.test(chatSeen[7][5]) && chatSeen[9][2] === '35,90' && chatSeen[9][0] === '16:48:21'
      && JSON.stringify(chatSeen[10].slice(0, 4)) === JSON.stringify(['17:00:01', 'XCCY 1Y', '38,60', '38,80']) && /bid nl/.test(chatSeen[10][5])
      && chatSeen[11][1] === 'selam', chatSeen.slice(5));
    check('the preview says whose every line is (no list of names yet: the source typed for the paste)', chatWhose.every((w) => w === 'Tullett'), chatWhose);
    check('the preview says what will be kept', (await page.textContent('#broker-summary')).trim() === '11 kota · 1 metin satırı', await page.textContent('#broker-summary'));
    await page.click('#broker-save');
    await page.waitForFunction(() => document.querySelectorAll('#broker-log-panel table.grid tr').length === 13, null, { timeout: 20000 });
    let chatBoard = await brokerBoard();
    const chatKept = await api(page, 'ayşe yilmaz', 'GET', '/api/broker');
    const chat18 = chatBoard.find((r) => r[0] === 'OIS' && r[1] === '18M') || [];
    const model18 = chatKept.json.board.find((r) => r.key === 'OIS:outright:18M');
    check('saved: the board shows where every instrument stands - the best bid with its broker, the offer lifted and pulled is gone, the trade is the last one',
      chatBoard.length === 7 && chat18[3] === '35,10' && /^Tullett · (şimdi|\d+ dk|\d+ sa \d+ dk)$/.test(chat18[4]) && chat18[5] === '' && chat18[6] === ''
      && chat18[7] === '13:55:37' && chat18[8] === '35,14'
      && JSON.stringify(chatBoard.map((r) => r[1])) === JSON.stringify(['6M', '18M', '1Y–5Y', '3Y–5Y', '2Y–3Y–4Y', '9x12', '1Y']) && chatBoard[6][0] === 'XCCY', chatBoard);
    check('the board compares with the dashboard\'s own curve (model, difference in bp)',
      Math.abs(trNumber(chat18[10]) - model18.mid) < 0.006 && Math.abs(trNumber(chat18[11].replace('+', '')) - model18.best_bid_diff) < 0.06 && chatBoard[6][10] === '',
      [chat18, model18]);
    let chatLog = await brokerLog();
    check('the chat is kept line by line with its time, sender and source',
      chatLog.length === 12 && chatLog[0][0] === '10:23:58' && chatLog[0][2] === '3y5y ois /-75 offer' && chatLog[5][1] === 'MIKE REES' && chatLog[5][13] === 'Tullett'
      && chatLog[5][0] === '13:33:59'
      && chatLog[11][2] === 'selam' && /Metin/.test(chatLog[11][8]) && chatKept.json.rows.every((q) => q.created_by === 'ayşe yilmaz' && q.source === 'Tullett')
      && (await page.inputValue('#broker-text')) === '', chatLog);
    await page.fill('#broker-text', CHAT);
    await page.waitForFunction(() => /zaten kayıtlı/.test(document.querySelector('#broker-summary').textContent), null, { timeout: 20000 });
    check('the same chat pasted again adds nothing', (await page.textContent('#broker-summary')).trim() === '0 kota · 12 satır zaten kayıtlı' && await page.isDisabled('#broker-save'),
      await page.textContent('#broker-summary'));
    await page.click('#broker-clear');
    // one instrument, a search, quotes only
    await page.evaluate(() => { const tr = [...document.querySelectorAll('#broker-board-panel table.grid tr')].find((x) => x.children[1].textContent === '18M'); tr.querySelector('td.act button').click(); });
    await page.waitForFunction(() => document.querySelectorAll('#broker-log-panel table.grid tr').length === 5);
    chatLog = await brokerLog();
    check('the board\'s row button lists what was said about one instrument', chatLog.every((r) => r[3] === '18M') && /^Yalnızca 18M/.test(await page.textContent('#broker-only')), chatLog);
    await page.click('#broker-only');
    await page.fill('#broker-find', 'fly');
    await page.waitForFunction(() => document.querySelectorAll('#broker-log-panel table.grid tr').length === 2);
    check('the log can be searched', (await brokerLog())[0][3] === '2Y–3Y–4Y');
    await page.fill('#broker-find', '');
    await page.check('#broker-quotes');
    await page.waitForFunction(() => document.querySelectorAll('#broker-log-panel table.grid tr').length === 12);
    await page.uncheck('#broker-quotes');
    await page.click('#broker-product button[data-v="XCCY"]');
    await page.waitForFunction(() => document.querySelectorAll('#broker-board-panel table.grid tr').length === 2);
    check('the board can be narrowed to a product', (await brokerBoard())[0][0] === 'XCCY');
    await page.click('#broker-product button[data-v="all"]');
    // another user adds a line: it is on this screen at once
    const chatAdded = await api(page, 'mehmet', 'POST', '/api/broker', { text: '17:10:00 5y ois 34.50/34.70', source: 'ICAP' });
    await page.waitForFunction(() => [...document.querySelectorAll('#broker-board-panel table.grid tr')].some((tr) => tr.children[1].textContent === '5Y'), null, { timeout: 15000 });
    chatLog = await brokerLog();
    check('a line another user keeps shows up live', chatAdded.json.saved === 1 && chatLog.length === 13 && chatLog[12][13] === 'ICAP' && chatLog[12][5] === '34,50', chatLog[12]);
    // delete a line
    await page.evaluate(() => { const tr = [...document.querySelectorAll('#broker-log-panel table.grid tr')].find((x) => x.children[4].textContent === 'selam'); tr.querySelector('td.act button').click(); });
    await page.waitForSelector('.modal .mfoot .btn.primary');
    await page.click('.modal .mfoot .btn.primary');
    await page.waitForFunction(() => document.querySelectorAll('#broker-log-panel table.grid tr').length === 13, null, { timeout: 15000 });
    check('a line can be deleted', !(await brokerLog()).some((r) => r[2] === 'selam'));
    // typed by hand, no time: the moment it is entered; Ctrl+Enter keeps it
    await page.fill('#broker-text', '2y ois 35.26/35.46');
    await page.waitForFunction(() => document.querySelectorAll('#broker-preview table tr').length === 2);
    const typedRow = await page.evaluate(() => [...document.querySelectorAll('#broker-preview table tr')][1].children[0].textContent);
    await page.focus('#broker-text');
    await page.keyboard.press('Control+Enter');
    await page.waitForFunction(() => [...document.querySelectorAll('#broker-board-panel table.grid tr')].some((tr) => tr.children[1].textContent === '2Y'), null, { timeout: 15000 });
    const typedKept = (await api(page, 'ayşe yilmaz', 'GET', '/api/broker')).json.rows.find((q) => q.raw === '2y ois 35.26/35.46');
    check('a quote typed without a time gets the time it was entered', typedRow === 'şimdi' && typedKept.timed === false && /^\d\d:\d\d:\d\d$/.test(typedKept.time), [typedRow, typedKept]);
    const [chatFile] = await Promise.all([page.waitForEvent('download'), page.click('#broker-export')]);
    check('the day downloads as a workbook', /^BrokerChat_\d{4}\.\d{2}\.\d{2}\.xlsx$/.test(chatFile.suggestedFilename()), chatFile.suggestedFilename());
    await page.click('#content .rangebox button:has-text("Son 30 gün")');
    await page.waitForFunction(() => window.tto.state.page && window.tto.state.page.data && window.tto.state.page.data.ranged, null, { timeout: 20000 });
    await page.waitForFunction(() => /^Tarih/.test((document.querySelectorAll('#broker-log-panel table.grid tr:first-child td')[1] || {}).textContent || ''));
    check('a period lists every day\'s chat with its date', /^Aralık: /.test(await page.textContent('#content .banner:not(.hidden)')) && (await brokerLog()).length === 13
      && (await brokerLog()).every((r) => /^\d\d\.\d\d\.\d{4}$/.test(r[0])));
    await page.click('#broker-today');
    await page.waitForFunction(() => window.tto.state.page && window.tto.state.page.data && window.tto.state.page.data.is_today, null, { timeout: 20000 });
    // the log sorts by a caption: the time newest first, then by sender; the time oldest first again
    const logCaption = (k) => page.click('#broker-log-panel table.grid tr:first-child td:nth-child(' + k + ')');
    await logCaption(2);
    await page.waitForFunction(() => /▼/.test(document.querySelectorAll('#broker-log-panel table.grid tr:first-child td')[1].textContent));
    chatLog = await brokerLog();
    check('the log sorts by its captions: the newest line first', chatLog[0][0] >= chatLog[1][0] && chatLog[1][0] >= chatLog[chatLog.length - 1][0], chatLog.map((r) => r[0]));
    await logCaption(3);
    await page.waitForFunction(() => /▲/.test(document.querySelectorAll('#broker-log-panel table.grid tr:first-child td')[2].textContent));
    chatLog = await brokerLog();
    check('... by sender', chatLog.map((r) => r[1]).filter(Boolean).every((x, i, a) => i === 0 || a[i - 1].localeCompare(x, 'tr') <= 0), chatLog.map((r) => r[1]));
    await logCaption(2);
    await logCaption(2);
    await page.waitForFunction(() => /▲/.test(document.querySelectorAll('#broker-log-panel table.grid tr:first-child td')[1].textContent));
    // lines ticked are deleted together
    const nLog = (await brokerLog()).length;
    const ticks = page.locator('#broker-log-panel input.pick');
    await ticks.nth(0).check();
    await ticks.nth(1).check();
    check('ticked lines: the delete button counts them', (await page.textContent('#broker-del-picked')) === 'Seçilenleri sil (2)' && await page.isVisible('#broker-del-picked'));
    await page.click('#broker-del-picked');
    await page.click('.modal .mfoot .btn.primary');
    await page.waitForFunction((n) => document.querySelectorAll('#broker-log-panel table.grid tr').length - 1 === n - 2, nLog, { timeout: 15000 });
    check('... and go together', (await brokerLog()).length === nLog - 2 && await page.isHidden('#broker-del-picked'));
    // the board is reset (the log keeps every line) and the reset taken back
    const boardBefore = (await brokerBoard()).map((r) => r[1]);
    await page.waitForFunction(() => !document.querySelector('.modal'), null, { timeout: 10000 });     // the delete's dialog is gone
    await page.click('#broker-reset');
    await page.click('.modal .mfoot .btn.primary');
    const cleared = await page.waitForFunction(() => !document.querySelector('#broker-board-panel table.grid'), null, { timeout: 15000 }).then(() => true, () => false);
    check('"Tahtayı sıfırla" clears the board, the log stays', cleared && (await brokerLog()).length === nLog - 2
      && /Sıfırlandı: \d\d:\d\d/.test(await page.textContent('#broker-reset-info')),
    { board: await brokerBoard(), info: await page.textContent('#broker-reset-info'), data: await page.evaluate(() => JSON.stringify({ resets: window.tto.state.page.data.resets,
      times: window.tto.state.page.data.rows.map((q) => q.date + ' ' + q.time), today: window.tto.state.page.data.today })) });
    await page.click('#broker-reset-undo');
    await page.waitForFunction(() => document.querySelectorAll('#broker-board-panel table.grid tr').length > 1, null, { timeout: 15000 });
    check('... and the reset can be taken back', JSON.stringify((await brokerBoard()).map((r) => r[1])) === JSON.stringify(boardBefore), boardBefore);
    // a switch of two bonds: one instrument, the spread of their yields; the screen's switch and the fitted curve beside it
    await api(page, 'ayşe yilmaz', 'POST', '/api/broker', { text: '17:20:00 mar28 vs jul30 switch -45/-40', source: 'Tullett' });
    await page.waitForFunction(() => [...document.querySelectorAll('#broker-board-panel table.grid tr')].some((tr) => /15\.03\.28 \/ 10\.07\.30/.test(tr.children[1].textContent)),
      null, { timeout: 15000 });
    const sw = (await brokerBoard()).find((r) => /15\.03\.28 \/ 10\.07\.30/.test(r[1]));
    check('a switch of two bonds is one instrument on the board: bid / ask in bp, the screen\'s switch as its model, where it stands on the curve',
      sw[0] === 'DİBS' && sw[2] === 'Switch (bp)' && sw[3] === '-45' && sw[5] === '-40' && /^-?\d+,\d$/.test(sw[10]) && /bp (eğri|ekran) · uzun (ucuz|pahalı)/.test(sw[14]), sw);
    // a trade of the chat as the desk's: "⇢" on its line, the level and our side, then Günlük İşlemler filled
    const tradeLine = () => [...document.querySelectorAll('#broker-log-panel table.grid tr')].find((x) => x.querySelector('td.act button[data-act="trade"]'));
    check('a trade line of the chat has the "İşlem gir" button, a quote of the brokers has not',
      await page.evaluate((f) => { const tr = (new Function('return ' + f))()(); return !!tr && /18m ois taken at 14/.test(tr.textContent)
        && [...document.querySelectorAll('#broker-log-panel table.grid tr')].filter((x) => x.querySelector('td.act button[data-act="trade"]')).length === 1; }, tradeLine.toString()));
    await page.evaluate((f) => (new Function('return ' + f))()().querySelector('td.act button[data-act="trade"]').click(), tradeLine.toString());
    await page.waitForSelector('#chat-trade');
    const chatWhy = await page.textContent('#chat-trade-why');
    check('the level is the trade\'s and the side the line\'s: the offer lifted is a payer',
      /^İşlem: offer alındı → PAY/.test(chatWhy) && (await page.getAttribute('#chat-trade-side button.on', 'data-v')) === 'buy', chatWhy);
    await page.click('#chat-trade-open');
    await page.waitForFunction(() => window.tto.state.pageId === 'blotter' && window.tto.state.page && window.tto.state.page.ois && window.tto.state.page.ois.level
      && window.tto.state.page.ois.level.value !== '', null, { timeout: 30000 });
    const oisFilled = await page.evaluate(() => { const o = window.tto.state.page.ois; return [o.strategy, o.side, o.f.tenor && o.f.tenor.value, o.level.value, o.note.value, o.cpt.value]; });
    check('... Günlük İşlemler opens on the OIS with the tenor, the level, the side, the broker and the line as its note',
      JSON.stringify(oisFilled.slice(0, 4)) === JSON.stringify(['outright', 'PAY', '18M', '35,14']) && /^Chat 13:41:09 MIKE REES: 18m ois taken at 14/.test(oisFilled[4])
      && oisFilled[5] === 'Tullett', oisFilled);
    await open(page, 'broker');
    await shot(page, '04b-broker');
    // a meeting-dated OIS: "mpc1" is the first meeting ahead - a row of its own with the MPC OIS bootstrap and the implied step;
    // its trade opens the blotter's MPC form with the two days of the meeting
    const mpcSaved = await api(page, 'ayşe yilmaz', 'POST', '/api/broker', { text: '17:30:00 mpc1 3650/3700\n17:31:00 mpc1 paid 36.75', source: 'Tullett' });
    await page.waitForFunction(() => [...document.querySelectorAll('#broker-board-panel table.grid tr')].some((tr) => /^MPC /.test(tr.children[1].textContent)),
      null, { timeout: 15000 });
    const mpcRow = (await brokerBoard()).find((r) => /^MPC /.test(r[1]));
    const mpcKept = (await api(page, 'ayşe yilmaz', 'GET', '/api/broker')).json.board.find((r) => r.kind === 'mpc') || {};
    check('a meeting-dated OIS ("mpc1") is a board row of its own: the MPC OIS bootstrap as its model, the implied step beside it',
      mpcSaved.json.saved === 2 && mpcRow[2] === 'MPC (PPK)' && mpcRow[3] === '36,50' && mpcRow[5] === '37,00' && mpcRow[8] === '36,75'
      && /^\d\d,\d\d$/.test(mpcRow[10]) && /^adım [+-]?\d+ \/ [+-]?\d+ bp · model [+-]?\d+$/.test(mpcRow[14]) && /^\d{4}-\d\d-\d\d$/.test((mpcKept.mpc || {}).start || ''),
      [mpcRow, mpcKept.mpc]);
    await page.evaluate(() => { const tr = [...document.querySelectorAll('#broker-log-panel table.grid tr')].find((x) => /mpc1 paid 36\.75/.test(x.textContent));
      tr.querySelector('td.act button[data-act="trade"]').click(); });
    await page.waitForSelector('#chat-trade');
    await page.click('#chat-trade-open');
    await page.waitForFunction(() => window.tto.state.pageId === 'blotter' && window.tto.state.page && window.tto.state.page.ois
      && window.tto.state.page.ois.strategy === 'mpc' && window.tto.state.page.ois.level.value !== '', null, { timeout: 30000 });
    const mpcFilled = await page.evaluate(() => { const o = window.tto.state.page.ois; return [o.strategy, o.side, o.f.start.value, o.f.end.value, o.level.value]; });
    const serialOf = (iso) => String(Math.round((Date.parse(iso) - Date.UTC(1899, 11, 30)) / 86400000));
    check('... and its "İşlem gir" opens the blotter\'s MPC form with the meeting\'s two days, the level and PAY',
      JSON.stringify(mpcFilled) === JSON.stringify(['mpc', 'PAY', serialOf(mpcKept.mpc.start), serialOf(mpcKept.mpc.end), '36,75']), [mpcFilled, mpcKept.mpc]);
    await open(page, 'broker');
    // a trade of the desk said in the chat and not entered: "N işlem girilmedi" on Broker Chat in the menu, its list ("Yok say" and
    // back), the warning before the day's archive; entered from the list ("⇢ Gir") it is in the blotter and the badge goes
    const deskLine = await api(page, 'ayşe yilmaz', 'POST', '/api/broker', { text: '18m ois paid 35.20', party: 'biz' });
    await page.waitForSelector('#nav-chat-missing', { timeout: 30000 });
    check('a trade of the desk in the chat that is not in the blotter: "1 işlem girilmedi" on Broker Chat in the menu',
      deskLine.json.saved === 1 && (await page.textContent('#nav-chat-missing')).trim() === '1 işlem girilmedi'
      && await page.evaluate(() => !!document.querySelector('#nav .nav-item[data-page="broker"] #nav-chat-missing')), await page.textContent('#nav-chat-missing'));
    await page.click('#nav-chat-missing');
    await page.waitForSelector('#chat-recon-table');
    await shot(page, '04c-chat-recon');
    const reconRow = () => page.evaluate(() => [...document.querySelectorAll('#chat-recon-table tr')].slice(1).map((tr) => [tr.dataset.id]
      .concat([...tr.children].map((td) => td.textContent))).find((r) => r[3] === '18m ois paid 35.20'));
    let deskRow = await reconRow();
    check('... a click on it lists the line: its trade, "Girilmedi"', !!deskRow && deskRow[4] === '18M @ 35,20' && deskRow[5] === 'Girilmedi', deskRow);
    const deskId = deskRow[0];
    await page.click('#recon-ignore-' + deskId);
    await page.waitForFunction(() => /Yok sayıldı/.test(document.querySelector('#chat-recon-table').textContent) && !document.querySelector('#nav-chat-missing'),
      null, { timeout: 15000 });
    await page.click('#recon-undo-' + deskId);
    await page.waitForSelector('#nav-chat-missing', { timeout: 15000 });
    await page.waitForFunction(() => [...document.querySelectorAll('#chat-recon-table tr')].some((tr) => /18m ois paid 35\.20/.test(tr.textContent)
      && /Girilmedi/.test(tr.textContent)), null, { timeout: 15000 });
    deskRow = await reconRow();
    check('... "Yok say" takes it off the count, "Geri al" brings it back', deskRow[5] === 'Girilmedi', deskRow);
    await page.click('#chat-recon .mfoot .btn');
    await open(page, 'blotter');
    await page.click('button:has-text("Gün sonu arşivi")');
    await page.waitForSelector('#archive-warn');
    const archiveWarn = await page.textContent('#archive-warn');
    check('the day\'s archive warns of it first', /masanın 1 işlemi Günlük İşlemler'de görünmüyor/.test(archiveWarn) && /18M @ 35,20/.test(archiveWarn), archiveWarn);
    await page.click('#archive-warn-list');
    await page.waitForSelector('#recon-enter-' + deskId);
    await page.click('#recon-enter-' + deskId);
    await page.waitForSelector('#chat-trade');
    await page.click('#chat-trade-open');
    await page.waitForFunction(() => window.tto.state.page && window.tto.state.page.ois && window.tto.state.page.ois.level.value === '35,20'
      && window.tto.state.page.ois.f.tenor && window.tto.state.page.ois.f.tenor.value === '18M', null, { timeout: 20000 });
    await page.click('.entry .pad:not(.hidden) .row.actions .btn.primary');
    await page.waitForFunction(() => !document.querySelector('#nav-chat-missing'), null, { timeout: 20000 });
    const reconAfter = (await api(page, 'ayşe yilmaz', 'GET', '/api/broker/recon')).json.items.find((x) => x.raw === '18m ois paid 35.20') || {};
    check('... "⇢ Gir" in the list fills Günlük İşlemler; saved, the line is entered and the badge goes', ['linked', 'auto'].includes(reconAfter.state), reconAfter);
    const [deskArchive] = await Promise.all([page.waitForEvent('download'), page.click('button:has-text("Gün sonu arşivi")')]);
    check('... and the archive downloads without a word', /^Blotter_\d{4}\.\d{2}\.\d{2}\.xlsx$/.test(deskArchive.suggestedFilename()), deskArchive.suggestedFilename());
    await open(page, 'broker');
    // the best price, broker by broker: a quote older than the stale limit is never the best - it stays greyed in its broker's row
    // with its age; every best price says whose it is and how old (the desk's limit typed on the board: 10 minutes)
    const halfHourAgo = new Date(Date.now() - 30 * 60000);
    if (halfHourAgo.toDateString() === new Date().toDateString()) {          // (just after midnight there was no half an hour ago today)
      await page.fill('#broker-stale', '10');
      await page.dispatchEvent('#broker-stale', 'change');
      await page.waitForFunction(() => window.tto.state.page.data && window.tto.state.page.data.stale_minutes === 10, null, { timeout: 15000 });
      await api(page, 'ayşe yilmaz', 'POST', '/api/broker', { text: halfHourAgo.toTimeString().slice(0, 8) + ' 7y ois 33.10/33.30', source: 'ICAP' });
      await api(page, 'ayşe yilmaz', 'POST', '/api/broker', { text: '7y ois 33.05/33.40', source: 'BGC' });
      // (both houses on the board: ICAP's stale quote alone has a row of its own already)
      await page.waitForFunction(() => [...document.querySelectorAll('#broker-board-panel table.grid tr')].some((tr) => tr.children[1].textContent === '↳ BGC'),
        null, { timeout: 20000 });
      const board7 = await brokerBoard();
      const at7 = board7.findIndex((r) => r[1] === '7Y');
      const [row7, bgc7, icap7] = board7.slice(at7, at7 + 3);
      const icapGrey = await page.evaluate(() => [...document.querySelectorAll('#broker-board-panel table.grid tr')].find((tr) => tr.children[1].textContent === '↳ ICAP')
        .children[3].classList.contains('stale'));
      check('the best price is a fresh one, with its broker and age: ICAP\'s better 33,10 / 33,30 is half an hour old - greyed in its own row, never the best',
        row7[3] === '33,05' && /^BGC · (şimdi|1 dk)$/.test(row7[4]) && row7[5] === '33,40' && /^BGC · (şimdi|1 dk)$/.test(row7[6])
        && bgc7[1] === '↳ BGC' && bgc7[3] === '33,05' && icap7[1] === '↳ ICAP' && icap7[3] === '33,10' && /^bayat · 3\d dk$/.test(icap7[4]) && icapGrey,
        [row7, bgc7, icap7]);
      await shot(page, '04d-broker-best');
    }
    await api(page, 'ayşe yilmaz', 'POST', '/api/broker/settings', { stale_minutes: 10 });

    // ------------------------------------------------------------------ blotter: other pairs, swap points, meeting-dated OIS
    console.log('blotter: pairs, swap points, MPC');
    await open(page, 'blotter');
    const fxTile = (k) => page.evaluate((key) => (document.querySelector('.entry .pad:not(.hidden) .quotebox [data-k="' + key + '"] .v') || {}).textContent || '', k);
    const fxRows = () => page.evaluate(() => [...document.querySelectorAll('.lists .panel:nth-child(1) table.grid tr')].map((tr) => [...tr.children].map((td) => td.textContent)));
    const fxBefore = (await fxRows()).length;
    await page.click('#fwd-pair button[data-v="EURTRY"]');
    await page.click('.entry .pad:not(.hidden) .seg button[data-v="B"]');
    await page.click('.entry .pad:not(.hidden) .seg button[data-v="RET_MID"]');
    await page.fill('.form input[placeholder^="örn. 10m"]', '5m');
    await page.fill('.form input[placeholder="gg.aa.yyyy"]', '15.12.2026');
    const eurQ = await api(page, 'ayşe yilmaz', 'POST', '/api/blotter/quote/forward', { pair: 'EURTRY', value_date: '15.12.2026', basis: 'RET_MID', amount: 5000000 });
    const fxForwardIs = (f) => page.waitForFunction((want) => {
      const el = document.querySelector('.entry .pad:not(.hidden) .quotebox [data-k="fwd-forward"] .v');
      return !!el && Math.abs(Number(el.textContent.replace(',', '.')) - want) < 6e-5;
    }, f, { timeout: 15000 });
    await fxForwardIs(eurQ.json.forward);
    const eurLabels = await page.evaluate(() => [...document.querySelectorAll('.entry .pad:not(.hidden) .field > label')].map((l) => l.textContent).join('|')
      + '|' + [...document.querySelectorAll('.entry .pad:not(.hidden) .seg button')].map((b) => b.textContent).join('|'));
    check('EURTRY forward: the sheet\'s own EURTRY table, in EUR', eurQ.json.pair === 'EURTRY' && Math.abs(trNumber(await fxTile('fwd-total')) - 5e6 * eurQ.json.forward) < 0.006
      && /Tutar \(EUR\)/.test(eurLabels) && /Alış \(EUR al\)/.test(eurLabels), [await fxTile('fwd-total'), eurQ.json.forward, eurLabels.slice(0, 200)]);
    await page.click('.entry .pad:not(.hidden) .seg button[data-v="SP"]');
    await page.fill('.form input[placeholder="örn. 17.400"]', '22.500');
    await fxForwardIs(eurQ.json.spot + 2.25);
    check('swap points: forward = spot + points / 10.000', (await fxTile('fwd-points')).trim() === '22.500', [await fxTile('fwd-points'), await fxTile('fwd-forward')]);
    await page.click('.entry .pad:not(.hidden) .row.actions .btn.primary');
    await page.waitForFunction((n) => document.querySelectorAll('.lists .panel:nth-child(1) table.grid tr').length === n + 1, fxBefore, { timeout: 15000 });
    // a currency the workbook has no curve for: typed by hand
    await page.click('#fwd-pair button[data-v="OTHER"]');
    await page.fill('#fwd-code', 'gbp');
    await page.fill('#fwd-spot', '63,00');
    await page.fill('.form input[placeholder="örn. 17.400"]', '20.000');
    await page.fill('.form input[placeholder^="örn. 10m"]', '2m');
    await page.waitForFunction(() => /^65,0000$/.test(((document.querySelector('.entry .pad:not(.hidden) .quotebox [data-k="fwd-forward"] .v') || {}).textContent || '').trim()), null, { timeout: 15000 });
    const gbpBases = await page.evaluate(() => [...document.querySelectorAll('.entry .pad:not(.hidden) .seg button')]
      .filter((b) => !b.classList.contains('hidden') && ['RET_BID', 'RET_MID', 'RET_ASK', 'TRY', 'FWD', 'SP'].includes(b.dataset.v)).map((b) => b.dataset.v).join(','));
    check('another currency: a pair typed, spot and points by hand', (await fxTile('fwd-total')).trim() === '130.000.000,00' && gbpBases === 'FWD,SP'
      && /Tutar \(GBP\)/.test(await page.textContent('.entry .pad:not(.hidden)')), [await fxTile('fwd-total'), gbpBases]);
    await page.click('.entry .pad:not(.hidden) .row.actions .btn.primary');
    await page.waitForFunction((n) => document.querySelectorAll('.lists .panel:nth-child(1) table.grid tr').length === n + 2, fxBefore, { timeout: 15000 });
    const fxList = await fxRows();
    const fxCol = (name) => fxList[0].indexOf(name);
    const fxNew = fxList.slice(-2);
    const fxCost = await page.evaluate(() => [...document.querySelectorAll('.lists .panel:nth-child(4) table.grid tr')].map((tr) => tr.children[0].textContent));
    check('the forwards are listed with their pair and points, and costed by pair', fxNew[0][fxCol('Parite')] === 'EURTRY' && fxNew[1][fxCol('Parite')] === 'GBPTRY'
      && fxNew[0][fxCol('Swap puanı')] === '22.500' && fxNew[1][fxCol('Forward')] === '65,0000' && fxNew[0][fxCol('Fiyatlama')] === 'Swap puanı'
      && /^\+/.test(fxNew[0][fxCol('DV01 ($)')]) && fxCost[0] === 'Parite' && fxCost.includes('EURTRY') && fxCost.includes('GBPTRY'), [fxNew, fxCost]);
    // a meeting-dated OIS
    await page.click('.entry .tabs button:nth-child(2)');
    await page.click('.entry .pad:not(.hidden) .seg button[data-v="mpc"]');
    await page.waitForSelector('#ois-mpc-start');
    const mpcMarket = (await api(page, 'ayşe yilmaz', 'GET', '/api/blotter/ois-market')).json.mpc;
    await page.waitForFunction(() => /Piyasa mid/.test(document.querySelector('.entry .pad:not(.hidden) .echo')?.textContent || ''));
    const mpcOptions = await page.evaluate(() => [[...document.querySelectorAll('#ois-mpc-start option')].map((o) => o.textContent), document.querySelector('#ois-mpc-end').selectedOptions[0].textContent]);
    check('MPC: from spot or a meeting\'s effective day to a later meeting\'s, at the sheet\'s market level',
      mpcOptions[0][0] === 'Spot · ' + mpcMarket.spot_text && mpcOptions[0][1] === 'MPC1 · ' + mpcMarket.dates[0].text && mpcOptions[1] === 'MPC2 · ' + mpcMarket.dates[1].text
      && Math.abs(trNumber((await page.textContent('.entry .pad:not(.hidden) .echo')).replace('Piyasa mid:', '').replace('kullan', '')) - mpcMarket.dates[0].market * 100) < 6e-5,
      [mpcOptions[0].slice(0, 3), mpcOptions[1], await page.textContent('.entry .pad:not(.hidden) .echo')]);
    await page.fill('input[placeholder="örn. 37,25"]', '35,90');
    await page.waitForFunction(() => document.querySelectorAll('.entry .pad:not(.hidden) .quotebox table.grid tr').length === 2);
    const mpcLeg = await page.evaluate(() => [...document.querySelectorAll('.entry .pad:not(.hidden) .quotebox table.grid tr')][1].textContent);
    const oisBefore = await page.locator('.lists .panel:nth-child(2) table.grid tr').count();
    await page.click('.entry .pad:not(.hidden) .row.actions .btn.primary');
    await page.waitForFunction((n) => document.querySelectorAll('.lists .panel:nth-child(2) table.grid tr').length === n + 1, oisBefore, { timeout: 15000 });
    const oisList = await page.evaluate(() => [...document.querySelectorAll('.lists .panel:nth-child(2) table.grid tr')].map((tr) => [...tr.children].map((td) => td.textContent)));
    const dvCol = oisList[0].indexOf('DV01 ($)'), sideCol = oisList[0].indexOf('Yön');
    check('the meeting-dated swap is one leg named by its dates', /^MPCPAYMPC \d\d\.\d\d\.\d\d–\d\d\.\d\d\.\d\d35,9000%/.test(mpcLeg)
      && /^MPC \d\d\.\d\d\.\d\d–/.test(oisList[oisList.length - 1][oisList[0].indexOf('Vade')]), [mpcLeg, oisList[oisList.length - 1]]);
    check('DV01 sign: a payer is plus and a receiver minus, leg by leg',
      oisList.slice(1).every((r) => (r[sideCol] === 'PAY' ? /^\+/.test(r[dvCol]) : /^-/.test(r[dvCol]))) && oisList.slice(1).some((r) => r[sideCol] === 'RECEIVE'), oisList.map((r) => [r[sideCol], r[dvCol]]));
    await page.click('.entry .tabs button:nth-child(1)');
    await page.click('#fwd-pair button[data-v="USDTRY"]');
    await shot(page, '04c-blotter-pairs');

    // ------------------------------------------------------------------ realized vol · carry
    console.log('realized vol, carry / vol');
    await open(page, 'vol');
    await page.waitForFunction(() => /22 gün/.test(document.getElementById('vol-history').textContent), null, { timeout: 60000 });
    const volTable = () => page.evaluate(() => [...document.querySelectorAll('#vol-panel table.grid tr')].map((tr) => [...tr.children].map((td) => td.textContent)));
    await page.fill('#vol-items', '1y, 3m6m, 3m6m1y, 9x12, 2y3y4y, abc');
    await page.waitForFunction(() => document.querySelectorAll('#vol-panel table.grid tr').length === 7 && document.querySelector('#vol-panel table.grid tr:nth-child(2) td').textContent === '1Y', null, { timeout: 20000 });
    const volApi = (await api(page, 'ayşe yilmaz', 'POST', '/api/vol', { text: '1y, 3m6m', window: 20 })).json;
    let vt = await volTable();
    check('realized vol of what is typed: outright, spread, fly, FRA - bp a day over 10 / 20 / 60 … days',
      JSON.stringify(vt.slice(1, 5).map((r) => r[0] + '/' + r[1])) === JSON.stringify(['1Y/Outright', '3M–6M/Spread (bp)', '3M–6M–1Y/Fly (bp)', '9x12/FRA'])
      && Math.abs(trNumber(vt[1][6]) - volApi.rows[0].vols['20'].d) < 0.06 && Math.abs(trNumber(vt[2][5]) - volApi.rows[1].vols['10'].d) < 0.06
      && Math.abs(trNumber(vt[1][2]) - volApi.rows[0].level) < 0.006 && vt[1][10] === String(volApi.rows[0].n), [vt.slice(0, 5), volApi.rows[0].vols]);
    check('what has no history, or is no instrument, says so', /geçmişi yok: 2Y, 3Y, 4Y/.test(vt[5].join(' ')) && /anlaşılamadı/.test(vt[6].join(' '))
      && /Tarihçe kısa/.test(await page.textContent('#vol-banner')), vt.slice(5));
    await page.click('#vol-unit button[data-v="1"]');
    await page.waitForFunction(() => /yıllık/.test(document.querySelector('#vol-panel table.grid tr td:nth-child(6)').textContent));
    vt = await volTable();
    check('a year\'s volatility is a day\'s × √252', Math.abs(trNumber(vt[1][6]) - volApi.rows[0].vols['20'].d * Math.sqrt(252)) < 0.06, vt[1]);
    await page.click('#vol-unit button[data-v="0"]');
    await page.evaluate(() => { [...document.querySelectorAll('#vol-panel table.grid tr')][2].querySelector('td.act button').click(); });
    await page.waitForFunction(() => /^3M–6M · seviye/.test(document.querySelector('#vol-panel .volcharts .ct').textContent));
    await page.click('#vol-window button[data-v="10"]');
    await page.waitForFunction(() => /kayan 10 günlük/.test(document.querySelectorAll('#vol-panel .volcharts .ct')[1].textContent), null, { timeout: 20000 });
    check('the history of the picked instrument: its level and its rolling volatility', await page.locator('#vol-panel .volcharts svg.chart').count() === 2
      && await page.locator('#vol-panel .volcharts svg.chart path').count() >= 2);
    // carry against it
    await page.waitForFunction(() => document.querySelectorAll('#carry-panel table.grid tr').length === 35, null, { timeout: 20000 });
    const carryApi = (await api(page, 'ayşe yilmaz', 'GET', '/api/vol/carry?kind=fly&window=10')).json;
    const carryRows = () => page.evaluate(() => [...document.querySelectorAll('#carry-panel table.grid tr')].map((tr) => [...tr.children].map((td) => td.textContent)));
    let ct = await carryRows();
    const best = carryApi.rows.filter((r) => typeof r.ratio_b === 'number').sort((a, b) => Math.abs(b.ratio_b) - Math.abs(a.ratio_b))[0];
    check('flies: the sheet\'s carry + roll against the volatility of the same horizon, the best ratio first',
      ct[0][2] === 'C+R 3 ay (bp)' && ct[1][0] === best.label && Math.abs(trNumber(ct[1][5].replace('+', '')) - best.ratio_b) < 0.006
      && Math.abs(trNumber(ct[1][4]) - best.vol * Math.sqrt(carryApi.horizons.b.days)) < 0.06, [ct.slice(0, 3), best]);
    check('flies: the z-scores of today\'s level against 3 months, 6 months and a year of closes',
      JSON.stringify(ct[0].slice(7, 10)) === JSON.stringify(['z 3a', 'z 6a', 'z 1y']) && ct.slice(1).some((r) => /^[+-]?\d+,\d\d$/.test(r[7])), ct[0]);
    const dotsB = await page.locator('#carry-panel svg.chart circle.mk').count();
    await page.click('#carry-horizon button[data-v="a"]');
    await page.waitForFunction(() => document.querySelector('#carry-panel table.grid tr td:nth-child(3)').textContent === 'C+R 1 ay (bp)');
    const dotsA = await page.locator('#carry-panel svg.chart circle.mk').count();
    check('the carry / vol chart: one labelled point per fly that has a history, for either horizon',
      dotsB === carryApi.rows.filter((r) => typeof r.ratio_b === 'number').length && dotsA === carryApi.rows.filter((r) => typeof r.ratio_a === 'number').length && dotsA > dotsB
      && await page.locator('#carry-panel svg.chart .pt-labels text').count() >= 2, [dotsA, dotsB]);
    await page.click('#carry-kind button[data-v="spread"]');
    await page.waitForFunction(() => document.querySelectorAll('#carry-panel table.grid tr').length === 121, null, { timeout: 20000 });
    check('the same for the sheet\'s spreads', /spread/.test(await page.textContent('#carry-panel h2')));
    await page.click('#carry-kind button[data-v="list"]');
    await page.waitForFunction(() => /yazdıklarınız/.test(document.querySelector('#carry-panel h2').textContent)
      && document.querySelectorAll('#carry-panel table.grid tr').length === 7, null, { timeout: 20000 });
    ct = await carryRows();
    check('"Listem": the carry of the instruments typed above, in their order - a FRA has none',
      JSON.stringify(ct.slice(1).map((r) => r[0])) === JSON.stringify(['1Y', '3M–6M', '3M–6M–1Y', '9x12', '2Y–3Y–4Y', 'abc'])
      && /carry yalnız OIS/.test(ct[4].join(' ')) && /^[+-]?\d+,\d$/.test(ct[1][2]) && /TLREF: .*bootstrap/i.test(await page.textContent('#carry-panel')), ct);
    await page.click('#carry-kind button[data-v="fly"]');
    await page.click('#carry-horizon button[data-v="b"]');
    await shot(page, '04d-vol');

    // ------------------------------------------------------------------ number format + theme
    console.log('number format, theme, explorer');
    await open(page, 'forward');
    await page.click('#btn-lang');
    await page.waitForFunction(() => window.tto.state.page && window.tto.state.page.ready && /\d\.\d{4}/.test(window.tto.findCell('EK_FWD!E50')?.textContent || ''));
    check('English number format shows a decimal point', /^\d+\.\d{4}$/.test((await cellText(page, 'EK_FWD!E50')).trim()), await cellText(page, 'EK_FWD!E50'));
    await page.click('#btn-lang');
    await page.waitForFunction(() => window.tto.state.page && window.tto.state.page.ready && /\d,\d{4}/.test(window.tto.findCell('EK_FWD!E50')?.textContent || ''));
    await page.click('#btn-theme');
    check('theme toggles to light', (await page.evaluate(() => document.documentElement.getAttribute('data-theme'))) === 'light');
    await shot(page, '05-forward-light');
    await page.click('#btn-theme');

    // ------------------------------------------------------------------ explorer + formula bar
    await open(page, 'explorer');
    await page.waitForSelector('table.grid.addr');
    await page.selectOption('.page-tools select:nth-of-type(2)', 'OIS_MAIN');
    await page.waitForFunction(() => window.tto.findCell('OIS_MAIN!C9') !== null);
    await (await cellHandle(page, 'OIS_MAIN!C9')).click();
    await page.waitForFunction(() => document.getElementById('sb-fx').textContent.startsWith('='), null, { timeout: 10000 });
    check('status bar shows the Excel formula of the cell', true);

    // ------------------------------------------------------------------ copying a table (the VİOP sheet's USD OIS curve)
    await open(page, 'viop');
    await page.evaluate(() => window.tto.state.page.focusPanel('B2'));
    await page.waitForFunction(() => { const it = window.tto.state.page.items.get('B2'); return !!(it && it.grid && it.grid.data); }, null, { timeout: 20000 });
    await page.hover('.panel[data-panel="B2"]');
    await page.click('.panel[data-panel="B2"] .tools .iconbtn');
    await page.waitForTimeout(250);
    const yp = await page.evaluate(() => navigator.clipboard.readText());
    check('"Kopyala" on a table puts a TSV block on the clipboard', yp.split('\r\n').length >= 20 && yp.includes('\t'), yp.slice(0, 120));
    check('the copy has the columns Excel shows (the hidden ticker column stays out)',
      yp.split('\r\n')[0] === '\tMaturity\tBid\tMid\tAsk', yp.split('\r\n')[0]);
    await shot(page, '06-viop-copy');

    // ------------------------------------------------------------------ charts as Excel defines them
    console.log('charts');
    const fns = await page.evaluate(async () => {
      const m = await import('/static/js/chart.js');
      return {
        fam: ['C0504D', '8064A2', 'F79646', '1F497D', '9BBB59', '4BACC6', '7F7F7F', 'zz'].map(m.colorFamily),
        cols: m.seriesColors([{ color: 'C0504D' }, { color: 'C0504D' }, { color: 'BE4B48' }, {}, {}]),
        excel: m.valueScale({}, 0.30, 0.42, 300), near: m.valueScale({}, 0.38, 0.42, 300),
        fit: m.valueScale({ auto: 'fit' }, 0.30, 0.42, 300), fixed: m.valueScale({ ymin: 0.25 }, 0.28, 0.51, 200),
        unit: m.valueScale({ ymin: 0.3, ymax: 0.42, major_unit: 0.01 }, 0.31, 0.40, 330), mixed: m.valueScale({}, -80, 20, 300),
        date: m.formatAxisDate(46388, 'mmm yy'), date2: m.formatAxisDate(46388, 'dd.mm.yyyy'),
      };
    });
    check('Excel colours map to their colour family', JSON.stringify(fns.fam) === JSON.stringify(['red', 'purple', 'orange', 'blue', 'green', 'cyan', 'ink', null]), fns.fam);
    check('the same workbook colour keeps one tone, another colour of a taken family takes the next free one',
      JSON.stringify(fns.cols) === JSON.stringify(['var(--c-red)', 'var(--c-red)', 'var(--c-blue)', 'var(--c-green)', 'var(--c-purple)']), fns.cols);
    check('automatic axis follows Excel: from zero unless the data sit in the top sixth of their maximum',
      fns.excel.lo === 0 && fns.near.lo > 0.3 && fns.near.lo < 0.38 && fns.near.hi >= 0.42, [fns.excel, fns.near]);
    check('a chart that is not from the workbook fits its data', fns.fit.lo > 0.2 && fns.fit.lo <= 0.3 && fns.fit.hi >= 0.42, fns.fit);
    check('ticks start at a fixed minimum and keep the fixed unit',
      fns.fixed.lo === 0.25 && fns.fixed.ticks[0] === 0.25 && fns.fixed.hi >= 0.51 && fns.unit.ticks.length === 13 && fns.unit.hi === 0.42, [fns.fixed, fns.unit]);
    check('an axis over both signs keeps zero as a tick', fns.mixed.lo <= -80 && fns.mixed.hi >= 20 && fns.mixed.ticks.includes(0), fns.mixed);
    check('date axis labels use month names', fns.date === 'Oca 27' && fns.date2 === '01.01.2027', [fns.date, fns.date2]);

    const chartInfo = () => page.evaluate(() => [...document.querySelectorAll('.panel.chart')].map((p) => {
      const svg = p.querySelector('svg.chart');
      const box = svg.getBoundingClientRect();
      return {
        title: p.querySelector('h2').textContent,
        keys: [...p.querySelectorAll('.chart-legend .key')].map((k) => k.textContent),
        strokes: [...new Set([...svg.querySelectorAll('path[fill="none"]')].map((x) => x.style.stroke))],
        dashed: svg.querySelectorAll('path[stroke-dasharray]').length, curved: [...svg.querySelectorAll('path[fill="none"]')].filter((x) => x.getAttribute('d').includes(' C')).length,
        markers: svg.querySelectorAll('circle.mk').length, boxes: svg.querySelectorAll('rect[rx="1.5"]').length,
        areas: svg.querySelectorAll('path[fill-opacity]').length, bars: [...svg.querySelectorAll('path')].filter((x) => x.getAttribute('d').endsWith('Z') && !x.hasAttribute('fill-opacity')).length,
        height: Math.round(box.height), width: Math.round(box.width),
        y: [...svg.querySelectorAll('text[text-anchor="end"]')].map((t) => t.textContent),
        x: [...svg.querySelectorAll('text[text-anchor="middle"]:not(.ttl)')].map((t) => t.textContent),
        titles: [...svg.querySelectorAll('text.ttl')].map((t) => t.textContent),
      };
    }));
    await open(page, 'masa');
    await tab(page, '*');
    const mc = await chartInfo();
    check('desk page draws the six charts of the workbook', mc.length === 6, mc.map((c) => c.title));
    check('"Oranlar": legend, Excel colours (RET red / purple dashes, ICAP orange, OIS blue, VİOP green), markers',
      JSON.stringify(mc[0].keys) === JSON.stringify(['RET bid', 'RET ask', 'ICAP', 'OIS zero', 'VİOP'])
      && JSON.stringify(mc[0].strokes) === JSON.stringify(['var(--c-red)', 'var(--c-purple)', 'var(--c-orange)', 'var(--c-blue)', 'var(--c-green)'])
      && mc[0].dashed === 2 && mc[0].markers > 35 && mc[0].curved === 0, mc[0]);
    check('value axis starts at the minimum fixed in Excel, with the format\'s decimals', mc[0].y[0] === '25,0%' && mc[0].y[1] === '30,0%', mc[0].y);
    check('"RET bid–ask": 30–42 % in steps of 1 % and the bid–ask boxes',
      mc[2].y.length === 13 && mc[2].y[0] === '30%' && mc[2].y[12] === '42%' && mc[2].boxes === 8, { y: mc[2].y, boxes: mc[2].boxes });
    check('"RET bandı": one legend key for the band, drawn as two washes', mc[3].keys.length === 4 && mc[3].keys[0] === 'RET bid–ask bandı' && mc[3].areas === 2, mc[3].keys);
    check('"3M FRA eğrisi": every fourth label, as in Excel', JSON.stringify(mc[4].x) === JSON.stringify(['Spot', '1Y', '2Y', '3Y', '4Y', '5Y', '6Y', '7Y', '8Y', '9Y']), mc[4].x);
    check('chart height follows the shape of the chart in Excel', mc[2].height > mc[0].height + 80 && mc[0].height >= 230 && mc[2].height <= 400, mc.map((c) => c.height));
    await shot(page, '07-charts-masa');

    await open(page, 'ois');
    await tab(page, '*');
    const oc = await chartInfo();
    const tlref = oc.find((c) => c.title.startsWith('TLREF'));
    check('TLREF path is on a date axis labelled by month, smoothed, with its axis title',
      tlref.x.length >= 5 && tlref.x.every((t) => /^(Oca|Şub|Mar|Nis|May|Haz|Tem|Ağu|Eyl|Eki|Kas|Ara) \d\d$/.test(t)) && tlref.curved === 4
      && tlref.titles.includes('TLREF') && tlref.y[0] === '25%', tlref);
    check('scenario lines keep Excel\'s blue / red / green / purple',
      JSON.stringify(tlref.strokes) === JSON.stringify(['var(--c-blue)', 'var(--c-red)', 'var(--c-green)', 'var(--c-purple)']), tlref.strokes);
    const steps = oc.find((c) => c.title.startsWith('Toplantı başı'));
    const carry = oc.find((c) => c.title.startsWith('Carry + roll'));
    check('bar charts: clustered steps and the stacked carry + roll', steps.bars > 30 && steps.keys.length === 4 && carry.keys.length === 2 && carry.bars >= 16, [steps.bars, carry.bars]);
    // tooltip: nearest date on the date axis, every series with its value
    const pathSvg = page.locator('.panel.chart', { hasText: 'TLREF patikası' }).locator('svg.chart');
    await pathSvg.scrollIntoViewIfNeeded();
    const tb = await pathSvg.boundingBox();
    await page.mouse.move(tb.x + tb.width * 0.55, tb.y + tb.height * 0.45);
    await page.waitForSelector('.chart-tip');
    const tip = await page.evaluate(() => ({ head: document.querySelector('.chart-tip .t').textContent, rows: [...document.querySelectorAll('.chart-tip .r')].map((r) => r.textContent) }));
    check('hovering a chart shows the date and all four values', /^\d\d\.\d\d\.\d{4}$/.test(tip.head) && tip.rows.length === 4 && tip.rows.every((r) => /%$/.test(r)), tip);
    const stepSvg = page.locator('.panel.chart', { hasText: 'Toplantı başı adım' }).locator('svg.chart');
    await stepSvg.scrollIntoViewIfNeeded();
    const bb = await stepSvg.boundingBox();
    await page.mouse.move(bb.x + bb.width * 0.5, bb.y + bb.height * 0.5);
    await page.waitForFunction(() => [...document.querySelectorAll('svg.chart .band')].some((b) => b.getAttribute('visibility') === 'visible'));
    check('hovering a bar chart marks the category', /^MPC\d+$|^Spot$/.test(await page.textContent('.chart-tip .t')));
    await page.mouse.move(5, 5);
    await shot(page, '08-charts-ois');
    // a quote message of the par curve: mid ± half the width typed
    await page.click('.panel[data-panel="B3"] button[data-action="quote"]');
    await page.waitForSelector('#quote-dialog #quote-width');
    await page.fill('#quote-width', '10');
    const parMsg = (await page.inputValue('#quote-text')).split('\n');
    const par1y = parMsg.find((l) => l.startsWith('1Y ')) || '';
    const par1yParts = par1y.replace(/^1Y\s+/, '').split(' / ').map(trNumber);
    check('"Kota mesajı" of the OIS curve: the par rate ± half the width typed (bp)', parMsg[0] === 'TRY OIS · par' && par1yParts.length === 2
      && Math.abs(par1yParts[1] - par1yParts[0] - 0.1) < 1e-9, parMsg);
    await page.click('#quote-dialog button:text-is("Kapat")');

    // ------------------------------------------------------------------ what else the workbook has
    console.log('workbook extras');
    const notes = await page.evaluate(() => [...document.querySelectorAll('td.nt')].map((td) => td.title));
    check('cell comments of the workbook are tooltips on their cells', notes.length === 6 && notes.includes('1 = OIS ima patikası, 0 = TLREF sabit'), notes);
    await open(page, 'masa');
    check('the desk page has the workbook\'s shortcuts (29 of its 30: the sheet without a page is not offered)',
      await page.locator('.shortcuts .chip').count() === 29 && await page.locator('.shortcuts .chip', { hasText: 'YP DİBS' }).count() === 0);
    await page.locator('.shortcuts .chip', { hasText: 'Matrisler' }).click();
    await page.waitForFunction(() => window.tto.state.pageId === 'viop' && window.tto.state.page && window.tto.state.page.ready, null, { timeout: 90000 });
    await page.waitForTimeout(900);
    const hit = await page.evaluate(() => {
      const el = document.querySelector('.panel[data-panel="B17"]');
      return { top: el.getBoundingClientRect().top, open: !el.classList.contains('collapsed'), hash: window.location.hash,
        folded: document.querySelectorAll('.panel.collapsed').length };
    });
    check('a shortcut opens the page at the table it points to (and unfolds it)', hit.hash === '#/viop?p=B17' && hit.open && hit.top < 400 && hit.top > 0, hit);
    check('tables Excel keeps folded start folded', hit.folded >= 14, hit.folded);
    await page.evaluate(() => window.tto.state.page.items.get('B17').toggle(true));

    // the USD OIS curve of the VİOP sheet: Excel hides its ticker column
    await open(page, 'viop');
    await page.evaluate(() => window.tto.state.page.focusPanel('B2'));
    await page.waitForFunction(() => { const it = window.tto.state.page.items.get('B2'); return !!(it && it.grid && it.grid.data); }, null, { timeout: 20000 });
    const ypCols = () => page.evaluate(() => window.tto.state.page.items.get('B2').grid.data.c.join(''));
    check('columns hidden in Excel are not shown', await ypCols() === 'BDEFG' && /1 gizli sütun/.test(await page.textContent('.panel[data-panel="B2"] .hc')));
    // a block copied in Excel (B16:D17) carries the hidden column: days (formula) | Ticker | Maturity
    await page.evaluate(async () => {
      const g = window.tto.state.page.items.get('B2').grid;
      const mod = await import('/static/js/grid.js');
      const i = g.data.r.indexOf(16), j = g.data.c.indexOf('B');
      await mod.pasteText(g, { grid: g, top: i, left: j, bottom: i, right: j }, '7\tUSSO2Z\t2W\r\n14\tUSSO1Z\t1W');
    });
    await page.waitForFunction(() => { const td = window.tto.findCell('VIOP!D16'); return td && td.textContent === '2W'; }, null, { timeout: 15000 });
    check('a block pasted from Excel keeps Excel\'s layout across the hidden columns', await cellText(page, 'VIOP!D17') === '1W');
    await page.click('.panel[data-panel="B2"] .hc');
    await page.waitForFunction(() => window.tto.findCell('VIOP!C16') !== null, null, { timeout: 15000 });
    check('"gizli sütun" shows them - with the value that was pasted into the hidden input',
      await ypCols() === 'BCDEFG' && await cellText(page, 'VIOP!C16') === 'USSO2Z' && await cellText(page, 'VIOP!C17') === 'USSO1Z',
      [await ypCols(), await cellText(page, 'VIOP!C16')]);
    await page.click('.page-tools button:has-text("Yardımcı tablolar")');
    await page.waitForFunction(() => window.tto.findCell('VIOP!C16') === null, null, { timeout: 15000 });
    // the curve as it was
    // (the curve's tickers and maturities are the desk's: back to the file's for everyone)
    await api(page, 'ayşe yilmaz', 'POST', '/api/reset', { book: 'tto', refs: ['VIOP!C16', 'VIOP!C17', 'VIOP!D16', 'VIOP!D17'], shared: true });
    await page.waitForFunction(() => { const td = window.tto.findCell('VIOP!D16'); return td && td.textContent === '1W'; }, null, { timeout: 15000 });

    await open(page, 'dibs');
    const frozen = await page.evaluate(() => {
      const p = document.querySelector('.panel[data-panel="B3"]');
      const row = [...p.querySelectorAll('tr')][5];
      const at = () => [...row.querySelectorAll('td.fz')].map((td) => Math.round(td.getBoundingClientRect().left));
      const before = at();
      p.querySelector('.body').scrollLeft = 700;
      return { before, after: at(), scrolled: p.querySelector('.body').scrollLeft };
    });
    check('columns frozen in Excel stay in view when the table scrolls sideways',
      frozen.before.length === 3 && frozen.scrolled > 300 && JSON.stringify(frozen.before) === JSON.stringify(frozen.after), frozen);

    await open(page, 'usd');
    await tab(page, '*');
    const bars = await page.evaluate(() => [...document.querySelectorAll('td.bar')].map((td) => parseFloat(td.style.getPropertyValue('--bar'))));
    // four rules of ten cells each; a cell without a number has no bar
    check('data bars of the USD sheet are drawn', bars.length >= 30 && bars.length <= 40 && Math.max(...bars) === 90 && Math.min(...bars) >= 10, bars.length);
    // "Mobil MK", "YP DIBS", "Ivır Zıvır" and "USDTRY IYIX" are taken out as the workbook loads: no page, not in the
    // sheet explorer
    const gone = await page.evaluate(async () => {
      const pic = await fetch('/api/image?book=tto&sheet=' + encodeURIComponent('Ivır Zıvır') + '&i=0');
      const sheets = (await (await fetch('/api/sheets?book=tto')).json()).sheets.map((x) => x.name);
      return { nav: [...document.querySelectorAll('#nav .nav-item')].map((a) => a.dataset.page), pic: pic.status, sheets };
    });
    check('the four sheets the desk dropped are gone: no page, not in the sheet explorer',
      !['ivir', 'mobil', 'ypdibs', 'iyix'].some((p) => gone.nav.includes(p)) && gone.pic === 404
      && !['MOBIL MK', 'YP DIBS', 'Ivır Zıvır', 'USDTRY IYIX'].some((s) => gone.sheets.includes(s)) && gone.sheets.includes('MASA')
      && gone.nav.includes('ihale'), gone);

    // the Treasury auction: a nominal typed the way the desk says it; the table's title (worked out from the bond)
    // follows what is typed without a reload
    await open(page, 'ihale');
    const auctionTitle = () => page.textContent('.panel[data-panel="H1"] header h2');
    const title0 = await auctionTitle();
    await typeInto(page, 'EK_IHALE!B10', '35m');
    await waitCell(page, 'EK_IHALE!B10', "t.replace(/[.,\\s]/g, '') === '35000000'");
    await waitCell(page, 'EK_IHALE!B15', "t.replace(/[.,\\s]/g, '') === '35000000'");
    check('a nominal typed as "35m" is 35 million, and the total counts it', true);
    await page.click('#hand-mode');
    await typeInto(page, 'EK_IHALE!C7', 'DENEME');          // the bond's name by hand (no Bloomberg in replay)
    await page.waitForFunction(() => document.querySelector('.panel[data-panel="H1"] header h2').textContent.includes('DENEME'), null, { timeout: 20000 });
    await (await cellHandle(page, 'EK_IHALE!C7')).click();
    await page.keyboard.press('Delete');
    await page.waitForFunction((t) => document.querySelector('.panel[data-panel="H1"] header h2').textContent === t, title0, { timeout: 20000 });
    check('the auction table\'s title follows the bond typed, and back, without a reload', title0 === 'KÂĞIT 1', title0);
    await page.click('#hand-mode');
    await (await cellHandle(page, 'EK_IHALE!B10')).click();
    await page.keyboard.press('Delete');
    await waitCell(page, 'EK_IHALE!B10', "t.trim() === ''");

    await open(page, 'blotter');
    const [download] = await Promise.all([page.waitForEvent('download'), page.click('button:has-text("Gün sonu arşivi")')]);
    const saved = await download.path();
    const size = require('fs').statSync(saved).size;
    check('"Gün sonu arşivi" downloads the day as Blotter_yyyy.mm.dd.xlsx', /^Blotter_\d{4}\.\d{2}\.\d{2}\.xlsx$/.test(download.suggestedFilename()) && size > 4000,
      [download.suggestedFilename(), size]);

    // ------------------------------------------------------------------ the dashboard's own tables
    console.log('own tables: forward quotes from OIS + spread, gold from the swap rate, BIST swap, ASW');
    const order = (ids) => page.evaluate((want) => {
      const all = [...document.querySelectorAll('#content .panel')].map((p) => p.dataset.panel);
      const at = all.indexOf(want[0]);
      return at >= 0 && want.every((id, k) => all[at + k] === id);
    }, ids);
    const pick = async (ref, label) => {                       // a drop-down cell: Enter opens its list
      const el = await cellHandle(page, ref);
      await el.click();
      await page.keyboard.press('Enter');
      await page.click('.menu button:text-is("' + label + '")');
    };
    await open(page, 'masa');
    await tab(page, 'fwd');
    check('the desk page keeps a summary of the USDTRY and the EURTRY quote matrix (the matrices live on the Forward page), the date-to-date forward\'s inputs above it',
      (await panelsOnPage(page)).join(' ') === 'EKS EKSE B10D B10 B22' && (await cellText(page, 'EK_FWD!D4')).trim() === '-150', await panelsOnPage(page));
    // each spread with the TRY rate it makes beside it: Spread bid | TRY bid % | Spread ask | TRY ask % (OIS + spread)
    const headOf = (id) => page.$$eval('#content .panel[data-panel="' + id + '"] tr', (trs) => {
      const head = trs.find((tr) => /Spread bid/.test(tr.textContent || ''));
      return head ? [...head.children].map((td) => (td.textContent || '').trim()) : [];
    }).catch(() => []);
    const spreadsAndRates = (head) => head.indexOf('Spread bid') >= 0
      && head.slice(head.indexOf('Spread bid'), head.indexOf('Spread bid') + 4).join(' | ') === 'Spread bid | TRY bid % | Spread ask | TRY ask %';
    const eksHead = await headOf('EKS');
    const ekseHead = await headOf('EKSE');
    const tryBidDesk = trNumber(await cellText(page, 'EK_FWD!M5'));
    const tryBidDeskEur = trNumber(await cellText(page, 'EK_FWD!M104'));
    check('the desk\'s forward summary shows each spread\'s TRY rate beside it: Spread bid | TRY bid % | Spread ask | TRY ask %',
      spreadsAndRates(eksHead), { head: eksHead });
    check('... EURTRY\'s too, its 1M from the EURTRY spot date with an EURTRY forward above its spot', spreadsAndRates(ekseHead)
      && (await cellText(page, 'EK_FWD!A104')).trim() === '1M' && trNumber(await cellText(page, 'EK_FWD!K104')) > trNumber(await cellText(page, 'EK_FWD!G104')),
    { head: ekseHead, k: await cellText(page, 'EK_FWD!K104'), g: await cellText(page, 'EK_FWD!G104') });
    // the date-to-date forward: its start / end dates and spread typed right above it, in this tab
    const days0 = (await cellText(page, 'MASA!G60')).trim();
    await typeInto(page, 'MASA!E60', '01.03.2027');
    await typeInto(page, 'MASA!C60', '01.12.2026');
    await waitCell(page, 'MASA!G60', "t.trim() === '90'");
    check('the date-to-date forward takes its dates in the forward tab (01.12.2026 → 01.03.2027: 90 days), the tab left as it was',
      (await panelsOnPage(page)).join(' ') === 'EKS EKSE B10D B10 B22', { days0, panels: await panelsOnPage(page) });
    for (const ref of ['MASA!C60', 'MASA!E60']) {
      await (await cellHandle(page, ref)).click();
      await page.keyboard.press('Delete');
    }
    await waitCell(page, 'MASA!G60', 't.trim() === ' + JSON.stringify(days0));
    // ------------------------------------------------------------------ a formula in an input cell, as in Excel
    // "=" in the broken-date converter's value date (KIRIK VADE & KARŞILIK: MASA!C171), a plain click on the start date of
    // the table above (MASA!C60): its address goes in; "+7", Enter - the value date is the start date + 7, live, with a ƒ
    const cellSerial = async (ref) => (await api(page, 'ayşe yilmaz', 'GET', '/api/cell?book=tto&ref=' + encodeURIComponent(ref))).json.cell.v;
    const dayText = (serial) => {                              // an Excel day number as the dashboard writes it (dd.mm.yyyy)
      const t = new Date(Math.round((serial - 25569) * 86400000));
      return String(t.getUTCDate()).padStart(2, '0') + '.' + String(t.getUTCMonth() + 1).padStart(2, '0') + '.' + t.getUTCFullYear();
    };
    const c171 = (await cellText(page, 'MASA!C171')).trim();
    const c60 = await cellSerial('MASA!C60');
    await (await cellHandle(page, 'MASA!C171')).click();
    await page.keyboard.type('=');
    await (await cellHandle(page, 'MASA!C60')).click();
    const pointedIn = await page.inputValue('td.editing input');
    await page.keyboard.type('+7');
    await page.keyboard.press('Enter');
    await waitCell(page, 'MASA!C171', 't.trim() === ' + JSON.stringify(dayText(c60 + 7)));
    const fx171 = () => page.evaluate(() => { const td = window.tto.findCell('MASA!C171'); return { ff: td.classList.contains('ff'), title: td.title }; });
    const mark1 = await fx171();
    check('an input takes a formula as in Excel: "=" in the value date, a plain click on the start date of another table (its address goes in: =C60), '
      + '"+7", Enter - the start date + 7 shows with a small ƒ, the formula on hover', pointedIn === '=C60' && mark1.ff
      && mark1.title.startsWith('Formül: =C60+7'), { pointedIn, mark1, c60, c171 });
    await typeInto(page, 'MASA!C60', '01.12.2026');
    await waitCell(page, 'MASA!C171', "t.trim() === '08.12.2026'");
    check('... live: the start date typed again (01.12.2026), the value date follows by itself (08.12.2026)', true);
    await (await cellHandle(page, 'MASA!C171')).click();
    await page.keyboard.press('F2');
    await page.waitForSelector('td.editing input');
    const f2 = await page.inputValue('td.editing input');
    // Ctrl+click puts a reference in wherever the caret is: here over the "7" picked by Shift+←
    await page.keyboard.press('Shift+ArrowLeft');
    await (await cellHandle(page, 'MASA!G60')).click({ modifiers: ['Control'] });
    const ctrlIn = await page.inputValue('td.editing input');
    await page.keyboard.press('Enter');
    const e60 = (await cellText(page, 'MASA!E60')).trim();
    await waitCell(page, 'MASA!C171', 't.trim() === ' + JSON.stringify(e60));
    check('... F2 shows the formula (=C60+7); Ctrl+click on the days (MASA!G60) in the middle of it puts the reference in (=C60+G60 → the end date)',
      f2 === '=C60+7' && ctrlIn === '=C60+G60' && (await fx171()).title.startsWith('Formül: =C60+G60'), { f2, ctrlIn, e60 });
    // after a finished reference a plain click ends the typing, as before; a Bloomberg function is refused with the reason
    await (await cellHandle(page, 'MASA!C171')).click();
    await page.keyboard.press('F2');
    await (await cellHandle(page, 'MASA!E60')).click();
    const ended = await page.locator('td.editing').count() === 0;
    await (await cellHandle(page, 'MASA!C171')).click();
    await page.keyboard.type('=BDP("USDTRY Curncy";"PX_LAST")');
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => /BDP Bloomberg'den veri ister: girdi formüllerinde/.test(document.getElementById('toasts').textContent), null, { timeout: 15000 });
    await page.waitForSelector('td.editing input');
    const refusedIn = await page.inputValue('td.editing input');
    await page.keyboard.press('Escape');
    check('... a plain click after a finished reference ends the typing; a Bloomberg function is refused with the reason (the daily data limit), '
      + 'the cell typed into again, its formula kept', ended && refusedIn === '=BDP("USDTRY Curncy";"PX_LAST")'
      && (await cellText(page, 'MASA!C171')).trim() === e60 && (await fx171()).title.startsWith('Formül: =C60+G60'), { ended, refusedIn });
    // a refused formula left with a click on another cell: said, with the formula - the editor is not pulled back to it
    await (await cellHandle(page, 'MASA!C171')).click();
    await page.keyboard.type('=FOO(1)');
    await (await cellHandle(page, 'MASA!E60')).click();
    await page.waitForFunction(() => /=FOO\(1\) kaydedilmedi/.test(document.getElementById('toasts').textContent), null, { timeout: 15000 });
    await page.waitForTimeout(500);
    const away = await page.evaluate(() => ({ editing: !!document.querySelector('td.editing'), addr: document.getElementById('sb-addr').textContent,
      focus: document.activeElement ? document.activeElement.tagName : '' }));
    check('... a refused formula left with a click on another cell: the toast says so with the formula, the selection stays on the clicked cell',
      !away.editing && away.addr === 'MASA!E60' && away.focus !== 'INPUT' && (await fx171()).title.startsWith('Formül: =C60+G60'), away);
    // a cell of another tab: "=", the tab "Faiz · PPK" opened - the formula goes on in a bar of its own -, a click on the
    // survey month there (MASA!S155, the desk's input), "+1", Enter
    const s155 = await cellSerial('MASA!S155');
    await (await cellHandle(page, 'MASA!C171')).click();
    await page.keyboard.type('=');
    await page.click('.viewtabs button[data-tab="rates"]');
    await page.waitForSelector('#grid-fx:not(.hidden) input');
    const docked = await page.inputValue('#grid-fx input');
    await (await cellHandle(page, 'MASA!S155')).click();
    const pointedTab = await page.inputValue('#grid-fx input');
    await page.keyboard.type('+1');
    await page.keyboard.press('Enter');
    await page.waitForSelector('#grid-fx', { state: 'hidden' });
    await waitCell(page, 'MASA!C171', 't.trim() === ' + JSON.stringify(dayText(s155 + 1)));
    check('... a cell of another tab: the formula goes on in a bar of its own while the tab is open (=S155), "+1", Enter - the survey month + 1 day',
      docked === '=' && pointedTab === '=S155' && (await fx171()).title.startsWith('Formül: =S155+1'), { docked, pointedTab, s155 });
    await shot(page, '09a-masa-input-formula');
    for (const ref of ['MASA!C171', 'MASA!C60']) {
      await (await cellHandle(page, ref)).click();
      await page.keyboard.press('Delete');
    }
    await waitCell(page, 'MASA!C171', 't.trim() === ' + JSON.stringify(c171));
    check('... Delete takes the formula with the value: the value date is the workbook\'s again, without ƒ',
      !(await fx171()).ff && !(await api(page, 'ayşe yilmaz', 'GET', '/api/my-inputs')).json.inputs.some((x) => x.formula));
    // every table's inputs in its own tab: on the desk page's VİOP tab DEALS' contract limit and the targets (the VİOP
    // page's cells) sit right above their tables
    await tab(page, 'viop');
    check('the desk page\'s VİOP tab: DEALS\' contract limit and the targets right above their tables',
      (await panelsOnPage(page)).join(' ') === 'B15 B16D B16 B17D B17', await panelsOnPage(page));
    const second0 = (await cellText(page, 'MASA!Q112')).trim();
    await typeInto(page, 'VIOP!W321', '1');
    await waitCell(page, 'MASA!Q112', "t.trim() === ''");
    check('a contract limit typed above DEALS (1: the first contract only) leaves one pair in each list',
      second0 === 'Spot' && (await cellText(page, 'MASA!Q111')).trim() === 'Spot' && (await cellText(page, 'MASA!Q116')).trim() === '',
      { second0, first: await cellText(page, 'MASA!Q111') });
    await api(page, 'ayşe yilmaz', 'POST', '/api/reset', { book: 'tto', refs: ['VIOP!W321'] });
    await waitCell(page, 'MASA!Q112', 't.trim() === ' + JSON.stringify(second0));
    await shot(page, '09-masa-viop-inputs');
    // the OIS page's parameters stay above its tabs: the DV01 per leg typed with the best trades open sizes them
    const mn = (t) => parseFloat(String(t).replace(/\./g, '').replace(',', '.'));          // "6.265M" -> 6265
    await open(page, 'ois');
    await tab(page, 'best');
    const bestTab = await panelsOnPage(page);
    const nom0 = (await cellText(page, 'OIS_MAIN!F30')).trim();
    await typeInto(page, 'OIS_MAIN!F2', '2000');
    await waitCell(page, 'OIS_MAIN!F30', 't.trim() !== ' + JSON.stringify(nom0));
    const nom1 = (await cellText(page, 'OIS_MAIN!F30')).trim();
    check('the OIS page\'s parameters stay above every tab: the DV01 per leg typed on the best trades\' tab doubles their nominals',
      bestTab[0] === 'B1' && bestTab.slice(1, 4).join(' ') === 'B9 B10 B11' && Math.abs(mn(nom1) - 2 * mn(nom0)) <= 0.02 * mn(nom1),
      { bestTab, nom0, nom1 });
    await api(page, 'ayşe yilmaz', 'POST', '/api/reset', { book: 'tto', refs: ['OIS_MAIN!F2'] });
    await waitCell(page, 'OIS_MAIN!F30', 't.trim() === ' + JSON.stringify(nom0));
    await shot(page, '09b-ois-parameters-pinned');
    await open(page, 'forward');
    await tab(page, 'kot');
    check('the forward quote matrices: USDTRY, EURTRY, then the way back of each - the Forward page\'s "Kotasyon" tab',
      await order(['EKF1', 'EKF5', 'EKF2', 'EKF6']));
    const ois1m = trNumber(await cellText(page, 'EK_FWD!L5'));
    check('... and the desk\'s TRY rate is the matrix\'s OIS + the spread (1M bid: OIS − 150 bp)', Math.abs(tryBidDesk - (ois1m - 1.5)) < 0.011,
      { tryBidDesk, ois1m });
    const ois1mEur = trNumber(await cellText(page, 'EK_FWD!L104'));
    check('... EURTRY\'s as well (its 1M bid: OIS − 150 bp)', Math.abs(tryBidDeskEur - (ois1mEur - 1.5)) < 0.011, { tryBidDeskEur, ois1mEur });
    check('matrix starts from the desk spread (−150 bp on both sides)',
      (await cellText(page, 'EK_FWD!D4')).trim() === '-150' && Math.abs(trNumber(await cellText(page, 'EK_FWD!M5')) - (ois1m - 1.5)) < 0.011);
    await typeInto(page, 'EK_FWD!D4', '-300');
    await waitCell(page, 'EK_FWD!M5', 'Math.abs(Number(t.replace(",", ".")) - ' + (ois1m - 3) + ') < 0.011');
    const fq = {};
    for (const c of ['D5', 'E5', 'H5', 'I5', 'M5', 'N5', 'J5', 'K5']) fq[c] = trNumber(await cellText(page, 'EK_FWD!' + c));
    check('a bid spread of −300 bp moves the bid side only', fq.D5 === -300 && fq.E5 === -150 && Math.abs(fq.N5 - (ois1m - 1.5)) < 0.011, fq);
    check('bid points are below ask points, forwards follow', fq.H5 < fq.I5 - 500 && fq.J5 < fq.K5, fq);
    const ois3m = trNumber(await cellText(page, 'EK_FWD!L7'));
    await typeInto(page, 'EK_FWD!E7', '-25');                  // one date with its own ask spread
    await waitCell(page, 'EK_FWD!N7', 'Math.abs(Number(t.replace(",", ".")) - ' + (ois3m - 0.25) + ') < 0.011');
    check('a date can carry its own spread', (await cellText(page, 'EK_FWD!E7')).trim() === '-25' && (await cellText(page, 'EK_FWD!E8')).trim() === '-150'
      && Math.abs(trNumber(await cellText(page, 'EK_FWD!N8')) - (trNumber(await cellText(page, 'EK_FWD!L8')) - 1.5)) < 0.011);
    await pick('EK_FWD!B2', 'Bootstrap');
    await waitCell(page, 'EK_FWD!B2', 't.trim() === "Bootstrap"');
    const boot = trNumber(await cellText(page, 'EK_FWD!L5'));
    check('the OIS curve is chosen from a list', Math.abs(boot - ois1m) > 0.001 && Math.abs(boot - ois1m) < 0.5, [ois1m, boot]);
    // the way back: the points the matrix shows, typed by hand, read the same spread
    const pts = (await cellText(page, 'EK_FWD!H5')).trim();
    await typeInto(page, 'EK_FWD!D20', pts);
    await waitCell(page, 'EK_FWD!K20', 't.trim() !== ""');
    check('points typed by hand show their spread over OIS', Math.abs(trNumber(await cellText(page, 'EK_FWD!K20')) + 300) <= 1, await cellText(page, 'EK_FWD!K20'));
    // EURTRY: the same matrix, taking the USDTRY one's curve and spreads until it is given its own
    check('the EURTRY matrix follows the USDTRY one\'s curve and spreads', (await cellText(page, 'EK_FWD!B101')).trim() === 'Bootstrap'
      && (await cellText(page, 'EK_FWD!D103')).trim() === '-300' && (await cellText(page, 'EK_FWD!E103')).trim() === '-150',
      [await cellText(page, 'EK_FWD!B101'), await cellText(page, 'EK_FWD!D103'), await cellText(page, 'EK_FWD!E103')]);
    const eurOis = trNumber(await cellText(page, 'EK_FWD!L104'));
    await typeInto(page, 'EK_FWD!E103', '-50');
    await waitCell(page, 'EK_FWD!N104', 'Math.abs(Number(t.replace(",", ".")) - ' + (eurOis - 0.5) + ') < 0.011');
    check('an EURTRY spread of its own leaves the USDTRY matrix as it is', (await cellText(page, 'EK_FWD!E4')).trim() === '-150',
      await cellText(page, 'EK_FWD!E4'));
    const eurPts = (await cellText(page, 'EK_FWD!I104')).trim();
    await typeInto(page, 'EK_FWD!E119', eurPts);
    await waitCell(page, 'EK_FWD!L119', 't.trim() !== ""');
    check('EURTRY points typed by hand show their spread over OIS', Math.abs(trNumber(await cellText(page, 'EK_FWD!L119')) + 50) <= 1,
      await cellText(page, 'EK_FWD!L119'));
    await shot(page, '10-forward-quotes');

    await open(page, 'viop');
    await tab(page, 'gold');
    check('gold tab: the VİOP gold tables, the calculator, then spot / source, swap rate curve and forwards (the Forward page\'s date above them)',
      await order(['B9', 'B10', 'B11', 'XAU4', 'XAU1', 'XAU2', 'XAU3D', 'XAU3', 'B11b']), await panelsOnPage(page));
    await tab(page, 'calc');
    check('the gold calculator is with the calculators as well (Interest 2 SP: Forward page)', (await panelsOnPage(page)).join(' ') === 'XAU4');
    await tab(page, 'gold');
    check('gold swap rate tickers are Bloomberg\'s XAUSR… roots with the yellow key next to them',
      (await cellText(page, 'EK_XAU!D16')).trim() === 'XAUSR1W' && (await cellText(page, 'EK_XAU!D17')).trim() === 'XAUSR1M'
      && (await cellText(page, 'EK_XAU!D22')).trim() === 'XAUSR12M' && (await cellText(page, 'EK_XAU!B12')).trim() === 'Curncy');
    const xau0 = (await cellText(page, 'VIOP!M58')).trim();
    check('offline the gold forward is the BFXFORWARD value Excel saved',
      xau0 === '3.971,85' && (await cellText(page, 'EK_XAU!J27')).trim() === '3.971,8535' && (await cellText(page, 'EK_XAU!C11')).trim() === 'Spot yok → BFXFORWARD'
      && (await cellText(page, 'EK_XAU!K27')).trim() === 'BFXFORWARD', xau0);
    await typeInto(page, 'EK_XAU!B5', '3950,10');
    await typeInto(page, 'EK_XAU!C5', '3950,60');
    await typeInto(page, 'EK_XAU!F17', '4,10');
    await waitCell(page, 'EK_XAU!C11', 't.trim() === "Swap faizi · 1 vade"');
    await waitCell(page, 'VIOP!M58', 't.trim() !== "' + xau0 + '"');
    const gold = { m58: await cellText(page, 'VIOP!M58'), src: await cellText(page, 'EK_XAU!K27'),
      usdtry: trNumber(await cellText(page, 'VIOP!M55')), fwd: trNumber(await cellText(page, 'EK_XAU!J27')), viop: trNumber(await cellText(page, 'VIOP!M57')) };
    check('typed spot and gold swap rate: the VİOP XAUTRY table runs on spot·(1 + swap·days/360), no USD rate in it',
      Math.abs(trNumber(gold.m58) - gold.fwd) < 0.006 && gold.src.trim() === 'Swap faizi' && Math.abs(gold.fwd - 3950.6 * (1 + 0.041 * 57 / 360)) < 0.01, gold);
    check('implied USDTRY = VİOP gold ÷ XAUUSD forward × 31,1035', Math.abs(gold.usdtry - gold.viop / gold.fwd * 31.1035) < 0.0006, gold);
    const theo = trNumber(await cellText(page, 'EK_XAU!B53'));
    await typeInto(page, 'EK_XAU!B46', '40');                  // "price it at this TRY rate"
    await waitCell(page, 'EK_XAU!B46', 't.trim() === "40,00"');
    const theo40 = trNumber(await cellText(page, 'EK_XAU!B53'));
    const fwd40 = 49.9977 * (1 + 0.40 / 360 * 57) / (1 + 0.0396429 / 360 * 57);
    check('gold calculator: theoretical XAUTRY at a typed TRY rate', theo40 > theo + 40
      && Math.abs(theo40 - trNumber(await cellText(page, 'EK_XAU!B48')) * fwd40 / 31.1035) < 0.02, [theo, theo40]);
    await shot(page, '11-gold-swap-rate');
    const ctxC = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
    const pageC = await ctxC.newPage();
    pageC.on('pageerror', (e) => errors.push('pageerror(C): ' + e.message));
    await login(pageC, 'Zeynep');
    await open(pageC, 'viop');
    check('spot and swap rate are desk inputs: another user sees the same forward', (await cellText(pageC, 'VIOP!M58')).trim() === gold.m58.trim(), await cellText(pageC, 'VIOP!M58'));
    check('the calculator rate is personal', (await cellText(pageC, 'EK_XAU!B46')).trim() !== '40,00', await cellText(pageC, 'EK_XAU!B46'));
    // the free column: dates, rate, gold forward and a price of my own
    await typeInto(page, 'EK_XAU!E41', '15.01.2027');
    await typeInto(page, 'EK_XAU!E46', '36');
    await typeInto(page, 'EK_XAU!E48', '3990');
    await typeInto(page, 'EK_XAU!E54', '6900');
    await waitCell(page, 'EK_XAU!E58', 't.trim() !== ""');
    const freeTeo = trNumber(await cellText(page, 'EK_XAU!E53')), freeFwd = trNumber(await cellText(page, 'EK_XAU!E50'));
    check('gold calculator, free column: price from a rate and the rate a price implies, all typed by hand',
      Math.abs(freeTeo - 3990 * freeFwd / 31.1035) < 0.02 && trNumber(await cellText(page, 'EK_XAU!E58')) > trNumber(await cellText(page, 'EK_XAU!E46')),
      [freeTeo, freeFwd, await cellText(page, 'EK_XAU!E58')]);
    // the history of the implied rate and of the spread over OIS (offline only today's point is there)
    await tab(page, 'basis');
    const vh = await page.evaluate(() => ({ panels: [...document.querySelectorAll('#content .panel')].map((p) => p.dataset.panel).slice(0, 4),
      rate: [...document.querySelectorAll('.panel[data-panel="VH2"] .chart-legend .key')].map((k) => k.textContent),
      basis: [...document.querySelectorAll('.panel[data-panel="VH3"] .chart-legend .key')].map((k) => k.textContent),
      charts: document.querySelectorAll('.panel[data-panel="VH2"] svg.chart, .panel[data-panel="VH3"] svg.chart').length,
      days: (window.tto.findCell('EK_VIOP!B8') || {}).textContent }));
    check('VİOP history tab: the contracts to draw, then the implied rate and the spread over OIS through time',
      vh.panels.join(' ') === 'VH1 VH2 VH3 B34' && vh.charts === 2 && vh.rate.length === 4 && vh.rate[0] === '30.11.26 · A1X6'
      && vh.basis.join() === vh.rate.join() && vh.days.trim() === '120', vh);
    await pick('EK_VIOP!F3', '6');
    await page.waitForFunction(() => document.querySelectorAll('.panel[data-panel="VH2"] .chart-legend .key').length === 5, null, { timeout: 20000 });
    check('a contract picked for a free line is drawn in both charts',
      await page.evaluate(() => [...document.querySelectorAll('.panel[data-panel="VH3"] .chart-legend .key')].map((k) => k.textContent).pop()) === '30.04.27 · A1J7');
    await ctxC.close();
    await pick('EK_XAU!B11', 'BFXFORWARD');
    await waitCell(page, 'VIOP!M58', 't.trim() === "' + xau0 + '"');
    check('the source can be switched back to BFXFORWARD', (await cellText(page, 'EK_XAU!C11')).trim() === 'BFXFORWARD (seçildi)');
    await pick('EK_XAU!B11', 'Otomatik');
    await waitCell(page, 'EK_XAU!C11', 't.trim() === "Swap faizi · 1 vade"');

    // ---- the manual spot: first table of the main page and of the VİOP page, and behind the header strip
    const firstPanel = () => page.evaluate(() => {
      const first = [...document.querySelectorAll('#content .panel')].find((p) => !p.classList.contains('hidden') && p.querySelector('table.grid'));
      return first ? first.querySelector('header h2').textContent : '';
    });
    await open(page, 'viop');
    await tab(page, 'main');
    check('VİOP page: the manual spot is the first table', /^Manuel spot/.test(await firstPanel()), await firstPanel());
    await open(page, 'masa');
    await tab(page, 'over');
    check('main page: the manual spot is the first table', /^Manuel spot/.test(await firstPanel()), await firstPanel());
    const spotKpi = await page.evaluate(() => (document.querySelector('#kpi-spot') || {}).textContent || '');
    // the file's manual spot (49,997 / 49,9975 of the day it was saved) is nobody's today: the desk starts on Bloomberg's
    check('header strip: "Spot kaynağı" says where the spot comes from - Bloomberg', /Spot kaynağı/.test(spotKpi) && /BBG/.test(spotKpi), spotKpi);
    await page.click('#kpi-spot');
    await page.waitForSelector('#spot-bid');
    const dlg = { bid: await page.inputValue('#spot-bid'), ask: await page.inputValue('#spot-ask'), src: await page.textContent('#spot-source') };
    check('a click on it opens the manual spot: the two cells of the VİOP sheet, empty', dlg.bid === '' && dlg.ask === '' && dlg.src === 'BBG', dlg);
    await page.fill('#spot-bid', '50,40');
    await page.fill('#spot-ask', '50,30');
    await page.click('.modal .btn.primary');
    await page.waitForFunction(() => [...document.querySelectorAll('.toast')].some((t) => /Bid, ask/.test(t.textContent)));
    check('manual spot: a bid above the ask is refused', await page.isVisible('#spot-bid'));
    await page.fill('#spot-bid', '49,90');
    await page.fill('#spot-ask', '49,91');
    await page.keyboard.press('Enter');
    await page.waitForSelector('#spot-bid', { state: 'detached' });
    await waitCell(page, 'VIOP!AA9', 't.trim() === "49,9000"');
    check('manual spot typed in the dialog is in the cells (and stays "MANUEL")', (await cellText(page, 'VIOP!AA10')).trim() === '49,9100'
      && /MANUEL/.test(await page.evaluate(() => document.querySelector('#kpi-spot').textContent)), await cellText(page, 'VIOP!AA10'));
    await page.click('#kpi-spot');
    await page.waitForSelector('#spot-bid');
    await page.click('.modal .mfoot .btn:has-text("Bloomberg")');
    await page.waitForSelector('#spot-bid', { state: 'detached' });
    await page.waitForFunction(() => /BBG/.test(document.querySelector('#kpi-spot').textContent));
    await waitCell(page, 'VIOP!AA9', 't.trim() === ""');
    check('"Bloomberg\'e dön" empties the two cells: the source is Bloomberg again', (await cellText(page, 'VIOP!AA9')).trim() === ''
      && (await cellText(page, 'VIOP!AA10')).trim() === '', [await cellText(page, 'VIOP!AA9'), await cellText(page, 'VIOP!AA10')]);

    await open(page, 'borsa');
    const borsa = await page.evaluate(() => {
      const num = (ref) => { const td = window.tto.findCell(ref); return td ? Number(td.textContent.replace('%', '').replace(/\./g, '').replace(',', '.')) : NaN; };
      const heads = [...document.querySelectorAll('.panel[data-panel="t0"] table.grid td')].map((td) => td.textContent.trim());
      return { banner: (document.querySelector('#content .banner') || {}).textContent || '', heads: heads.filter((t) => /O\/N|SP \/ gün/.test(t)),
        days: num('bu!E11'), bid: num('bu!H11'), on: num('bu!O11'), ask: num('bu!M11'), onAsk: num('bu!P11') };
    });
    check('Borsa swap page says its offline quotes are examples', /ÖRNEK/.test(borsa.banner), borsa.banner.slice(0, 80));
    check('BIST swap table has the per-day points and the O/N equivalents', JSON.stringify(borsa.heads) === JSON.stringify(['BID SP / gün', 'ASK SP / gün', 'BID O/N', 'ASK O/N']), borsa.heads);
    check('O/N equivalent is below the simple rate of a longer maturity', borsa.days > 1 && borsa.on > 20 && borsa.on < borsa.bid && borsa.onAsk < borsa.ask, borsa);
    const bist = await page.evaluate(() => ['t0', 't1'].map((id) => {
      const cells = [...document.querySelectorAll('.panel[data-panel="' + id + '"] table.grid td')].map((td) => td.textContent.trim());
      const note = (document.querySelector('.panel[data-panel="' + id + '"] .note') || {}).textContent || '';
      return { errors: cells.filter((t) => t.startsWith('#')), n: cells.length, note };
    }));
    check('BIST swap tables hold quotes only: no error cells, and the rule is written under the table',
      bist.every((b) => b.errors.length === 0 && b.n > 60) && /miktarı \(size\) sıfırdan büyük/.test(bist[0].note), bist.map((b) => [b.errors.slice(0, 3), b.n]));
    // each quote against the TRY workbook's OIS and offshore mid curves: six columns of the dashboard's own on the right
    const spreadHeads = ['OIS mid zero %', 'Offshore mid zero %', 'BID − OIS mid (bp)', 'ASK − OIS mid (bp)', 'BID − Off mid (bp)', 'ASK − Off mid (bp)'];
    const spread = await page.evaluate((want) => ['t0', 't1'].map((id) => {
      const rows = [...document.querySelectorAll('.panel[data-panel="' + id + '"] table.grid tr')].map((tr) => [...tr.querySelectorAll('td')]);
      const head = rows.find((r) => r.some((td) => td.textContent.trim() === want[0])) || [];
      const texts = head.map((td) => td.textContent.trim());
      const at = ['BID %', 'ASK %'].concat(want).map((t) => texts.indexOf(t));
      const body = rows.filter((r) => r !== head && r.length === head.length && r.some((td) => td.textContent.trim()));
      return { last: texts.slice(-6), rows: body.map((r) => at.map((j) => (j >= 0 ? r[j].textContent.trim() : null))),
        tip: body.length && at[2] >= 0 ? body[0][at[2]].title : '' };
    }), spreadHeads);
    check('BIST swap tables end in the spreads to the OIS and the offshore mid (both tables)',
      spread.every((s) => JSON.stringify(s.last) === JSON.stringify(spreadHeads) && s.rows.length >= 5), spread.map((s) => [s.last, s.rows.length]));
    const bp = (t) => (t === '' || t === null ? NaN : trNumber(t));
    check('each quote\'s spread is its BID % / ASK % less the mid zero rate, in bp (a one-sided quote: its own side only)',
      spread.every((s) => s.rows.every(([bid, ask, ois, off, bidOis, askOis, bidOff, askOff]) => {
        const zo = bp(ois), zf = bp(off);
        const side = (rate, a, b) => (rate === '' ? a === '' && b === ''
          : Math.abs(bp(a) - (bp(rate) - zo) * 100) <= 1.51 && Math.abs(bp(b) - (bp(rate) - zf) * 100) <= 1.51);
        return zo > 10 && zo < 80 && zf > 10 && zf < 80 && side(bid, bidOis, bidOff) && side(ask, askOis, askOff);
      })) && spread.some((s) => s.rows.some((r) => r[0] === '' || r[1] === '')), spread.map((s) => s.rows.slice(0, 3)));
    check('a T+0 quote says how it reaches the OIS spot (TLREF), and the note says what the spreads are',
      /Spot öncesi/.test(spread[0].tip) && /TLREF/.test(spread[0].tip) && !/Spot öncesi/.test(spread[1].tip)
      && /OIS mid zero/.test(bist[0].note) && /TLREF/.test(bist[0].note), [spread[0].tip, spread[1].tip, bist[0].note.slice(0, 80)]);

    await open(page, 'asw');
    const asw = await page.evaluate(() => [...document.querySelectorAll('.panel.chart')].map((p) => {
      const svg = p.querySelector('svg.chart');
      return { title: p.querySelector('header h2').textContent, markers: svg ? svg.querySelectorAll('circle.mk').length : 0,
        labels: svg ? [...svg.querySelectorAll('text.pt')].map((t) => t.textContent) : [], paths: svg ? svg.querySelectorAll('path').length : 0,
        titles: svg ? [...svg.querySelectorAll('text.ttl')].map((t) => t.textContent) : [], wide: p.classList.contains('wide') };
    }));
    check('ASW page draws the workbook\'s XY chart: one marker per bond, labelled, and the fitted curve',
      asw.length === 2 && asw[0].title === 'DİBS ASW — kalan vade' && asw[0].markers >= 15 && asw[0].labels.length >= 10
      && asw[0].labels.every((t) => /^[A-ZŞÇÖÜİa-zşçöüığ]{3}\d\d/.test(t)) && asw[0].titles.includes('ASW (bp)') && asw[0].titles.includes('Kalan vade (yıl)'), asw[0]);
    const aswSvg = page.locator('.panel.chart', { hasText: 'DİBS ASW — kalan vade' }).locator('svg.chart');
    await aswSvg.scrollIntoViewIfNeeded();
    const ab = await aswSvg.boundingBox();
    await page.mouse.move(ab.x + ab.width * 0.3, ab.y + ab.height * 0.5);
    await page.waitForSelector('.chart-tip');
    const atip = await page.evaluate(() => ({ head: document.querySelector('.chart-tip .t').textContent, rows: [...document.querySelectorAll('.chart-tip .r')].map((r) => r.textContent) }));
    check('hovering the XY chart names the nearest bond and its spread', atip.head.length > 0 && atip.rows.length >= 1 && atip.rows.some((r) => /\d/.test(r)), atip);
    await page.mouse.move(5, 5);
    check('ASW table has the bonds of the recorded day', (await cellText(page, 'ASW!B7')).trim() === 'TRB100227T13' && /^-?\d+/.test((await cellText(page, 'ASW!R9')).trim()));
    await shot(page, '12-asw');

    // ------------------------------------------------------------------ history: matrix, meeting pricing, calendar
    console.log('history: end-of-day matrix, meeting pricing, calendar');
    // the server fills the history of the recorded month in the background (about a minute after its start)
    let hist = null;
    for (let i = 0; i < 200; i++) {
      hist = (await api(page, 'ayşe yilmaz', 'GET', '/api/history/status')).json;
      if (hist.phase === 'idle' && hist.mpc_days >= 21) break;
      await page.waitForTimeout(2000);
    }
    // (8 series of the workbook, and 9 of the quant package's that the file recorded too: USDTRY, its swap points, USD OIS
    // 3M - and USD OIS 1M / 6M / 1Y of the VİOP page)
    check('the history of the recorded month is filled in the background', hist.phase === 'idle' && hist.mpc_days === 21 && hist.series === 8 + 9 && !hist.error, hist);
    const rowsOf = (panel) => page.evaluate((p) => [...document.querySelectorAll('.panel[data-panel="' + p + '"] table.grid tr')]
      .map((tr) => [...tr.children].map((td) => td.textContent.trim())), panel);
    const rowOf = (rows, label) => rows.find((r) => r[0] === label || r[0].startsWith(label)) || [];

    await open(page, 'eod');
    let curve = await rowsOf('curve');
    check('matrix: TLREF and the OIS tenors with their 1 day / 1 week / 1 month changes',
      JSON.stringify(rowOf(curve, 'TLREF').slice(0, 5)) === JSON.stringify(['TLREF', '35,816', '0,0', '-5,5', '-100,7'])
      && JSON.stringify(rowOf(curve, '1M').slice(0, 5)) === JSON.stringify(['1M', '36,350', '+5,0', '0,0', '-80,0']), [rowOf(curve, 'TLREF'), rowOf(curve, '1M')]);
    check('matrix: offshore next to the OIS tenor (XCCY 1Y)', JSON.stringify(rowOf(curve, '1Y').slice(5)) === JSON.stringify(['39,350', '-8,0', '-60,0', '+55,0']), rowOf(curve, '1Y'));
    check('matrix says what the changes are measured against', /03\.11\.2026 kapanışı · Δ1G 02\.11 · Δ1H 27\.10 · Δ1A 05\.10/.test(await page.textContent('.page-tools')));
    const tipOf = await page.evaluate(() => {
      const tr = [...document.querySelectorAll('.panel[data-panel="curve"] table.grid tr')].find((r) => r.children[0].textContent.trim() === '1M');
      return { title: tr.children[2].title, heat: tr.children[4].style.backgroundColor };
    });
    check('a change shows the earlier close on hover and is shaded by its size', /^02\.11\.2026: 36,300$/.test(tipOf.title) && /rgba/.test(tipOf.heat), tipOf);
    const mpcRows = await rowsOf('mpc');
    check('matrix: what is priced for the meetings, the first one marked', mpcRows.length === 10 && mpcRows[2][0] === '10.12.2026 · ilk'
      && /^-\d+,\d$/.test(mpcRows[2][1]) && /^[+-]?\d+,\d$/.test(mpcRows[2][2]) && /^3\d,\d{3}$/.test(mpcRows[2][5]), mpcRows[2]);
    const bondRows = await rowsOf('dibs');
    check('matrix: the bonds of DİBS RV by maturity with the workbook\'s own yield', bondRows.length === 20 && bondRows[1][0] === 'TRB100227T13'
      && bondRows[1][2] === '10.02.2027' && /^3\d,\d{3}$/.test(bondRows[1][10]) && bondRows[1][4] === '', bondRows[1]);
    check('matrix says that offline there is no bond history', /DİBS geçmişi yok/.test(await page.textContent('.panel[data-panel="dibs"] .note')));
    await shot(page, '13-eod');
    await page.selectOption('.page-tools select', '2026-10-23');
    await page.waitForFunction(() => /23\.10\.2026 kapanışı/.test(document.querySelector('.page-tools').textContent));
    curve = await rowsOf('curve');
    check('matrix of an earlier day: the cut of 22 October arrives in the fixing', rowOf(curve, 'TLREF')[2] === '-102,7' && rowOf(curve, 'TLREF')[1] === '35,850', rowOf(curve, 'TLREF'));
    await page.selectOption('.page-tools select', '2026-10-22');
    await page.waitForFunction(() => /PPK günü/.test(document.querySelector('.panel[data-panel="mpc"] .note').textContent));
    check('matrix on the day of a meeting says how the steps are measured', (await rowsOf('mpc'))[2][0] === '10.12.2026 · ilk');
    await (await page.locator('.panel[data-panel="curve"] .tools button', { hasText: 'Kopyala' })).click({ force: true });
    await page.waitForTimeout(200);
    const eodCopy = await page.evaluate(() => navigator.clipboard.readText());
    check('the matrix can be copied to Excel', eodCopy.split('\r\n').length >= 9 && /^1M\t\d\d,\d{3}\t/m.test(eodCopy), eodCopy.slice(0, 160));

    await open(page, 'mpc');
    const mp = async () => page.evaluate(() => {
      const svg = document.querySelector('.panel[data-panel="chart"] svg.chart');
      return { keys: [...document.querySelectorAll('.panel[data-panel="chart"] .chart-legend .key')].map((k) => k.textContent),
        lines: svg ? svg.querySelectorAll('path[fill="none"]').length : 0, titles: svg ? [...svg.querySelectorAll('text.ttl')].map((t) => t.textContent) : [],
        chips: [...document.querySelectorAll('.chips .chip')].map((c) => c.textContent + (c.classList.contains('on') ? '*' : '') + (c.classList.contains('past') ? '!' : '')),
        head: document.querySelector('.panel[data-panel="chart"] header h2').textContent, banner: (document.querySelector('#content .banner') || {}).textContent || '' };
    });
    let m1 = await mp();
    check('meeting pricing: one line per chosen meeting - the one held on 22 October and the next four',
      JSON.stringify(m1.keys) === JSON.stringify(['22.10.2026 (yapıldı)', '10.12.2026', '21.01.2027', '18.03.2027', '22.04.2027']) && m1.lines >= 5
      && m1.chips.length === 9 && m1.chips[0] === '22.10.2026*!' && m1.chips[5] === '10.06.2027', m1);
    check('meeting pricing: the period and the measure are in the caption', m1.head === 'Toplantı fiyatlaması · Adım (bp) · 05.10.2026 – 03.11.2026' && m1.titles.includes('Adım (bp)'), m1.head);
    check('meeting pricing says that the recorded data are partial', /eksik OIS kotası/.test(m1.banner), m1.banner.slice(0, 90));
    await page.click('.chips .chip:has-text("10.06.2027")');
    await page.click('.chips .chip:has-text("22.10.2026")');
    m1 = await mp();
    check('a meeting is added to / taken out of the chart by its chip', JSON.stringify(m1.keys) === JSON.stringify(['10.12.2026', '21.01.2027', '18.03.2027', '22.04.2027', '10.06.2027']), m1.keys);
    await page.click('.seg button:has-text("Seviye (%)")');
    m1 = await mp();
    check('the measure can be switched to the implied level', m1.titles.includes('Seviye (%)') && /Seviye \(%\)/.test(m1.head), m1.titles);
    const mpSvg = page.locator('.panel[data-panel="chart"] svg.chart');
    const mb = await mpSvg.boundingBox();
    await page.mouse.move(mb.x + mb.width * 0.6, mb.y + mb.height * 0.5);
    await page.waitForSelector('.chart-tip');
    const mtip = await page.evaluate(() => ({ head: document.querySelector('.chart-tip .t').textContent, rows: [...document.querySelectorAll('.chart-tip .r')].map((r) => r.textContent) }));
    check('hovering the time series shows the day and the level of every meeting', /^\d\d\.\d\d$/.test(mtip.head) && mtip.rows.length === 5 && mtip.rows.every((r) => /3\d,\d+/.test(r)), mtip);
    await page.mouse.move(5, 5);
    await page.click('.seg button:has-text("Adım (bp)")');
    const meet = await rowsOf('meetings');
    const held = rowOf(meet, '22.10.2026');
    check('meetings table: the next meeting with its changes', rowOf(meet, '10.12.2026')[1] === 'MPC1 · 37 gün' && /^-\d+,\d$/.test(rowOf(meet, '10.12.2026')[2])
      && /^[+-]?\d+,\d$/.test(rowOf(meet, '10.12.2026')[3]), rowOf(meet, '10.12.2026'));
    check('meetings table: the meeting that was held - last pricing, what TLREF did, the surprise',
      held[1] === 'yapıldı' && /^-\d+,\d$/.test(held[2]) && held[14] === '-102,7' && /^[+-]?\d+,\d$/.test(held[15]) && held[13] === '21.10.2026', held);
    const daily = await rowsOf('daily');
    check('daily history: newest first, the day of the meeting marked', daily[1][0] === '03.11.2026' && daily[1][1] === '35,8159' && daily[1][2] === '6'
      && daily.some((r) => r[0] === '22.10.2026 · PPK') && daily.length === 22, [daily[1], daily.length]);
    check('daily history: what the workbook\'s own status says about each day', daily[0][3] === 'Durum' && daily.slice(1).every((r) => r[3] === 'eksik'),
      daily.slice(0, 3).map((r) => r[3]));
    await shot(page, '14-mpc');

    // ------------------------------------------------------------------ spreads over OIS, day by day
    await open(page, 'spreads');
    const offSpread = await rowsOf('spread-off');
    const viopSpread = await rowsOf('spread-viop');
    const x1y = rowOf(offSpread, '1Y');
    check('spread history: offshore − OIS tenor by tenor - today\'s level and the cross-currency 1Y against the closes of the recorded month',
      offSpread[0][4] === 'Spread' && offSpread[0][10] === 'z 60g' && offSpread.length >= 8 && x1y[1] === 'XCCY' && /^-?\d+,\d$/.test(x1y[4])
      && /^[+-]?\d+,\d$/.test(x1y[5]) && Number(x1y[14]) > 15, [offSpread[0], x1y]);
    check('... VİOP − OIS contract by contract (the VİOP history\'s contracts, one added on the VİOP page earlier)', viopSpread.length === 6
      && viopSpread.slice(1).every((r) => /^-?\d+,\d$/.test(r[4])), viopSpread);
    await page.click('#spread-window button[data-v="20"]');
    check('... the statistics window: 20 closes', (await rowsOf('spread-off'))[0][10] === 'z 20g' && /^[+-]?\d+,\d\d$/.test(rowOf(await rowsOf('spread-off'), '1Y')[10]),
      rowOf(await rowsOf('spread-off'), '1Y'));
    await page.evaluate(() => { const tr = [...document.querySelectorAll('.panel[data-panel="spread-viop"] table.grid tr')][1]; tr.querySelector('td.act button').click(); });
    await page.waitForFunction(() => /^VİOP .* − OIS \(bp\)/.test(document.querySelector('.panel[data-panel="spread-chart"] h2').textContent));
    check('a spread picked is drawn', await page.locator('.panel[data-panel="spread-chart"] svg.chart').count() === 1);
    // ... a click on a row's tenor draws that one too, its row marked
    await page.evaluate(() => [...document.querySelectorAll('.panel[data-panel="spread-off"] table.grid td.chartlink')].find((td) => td.textContent === '1Y').click());
    await page.waitForFunction(() => /^Offshore 1Y − OIS \(bp\)/.test(document.querySelector('.panel[data-panel="spread-chart"] h2').textContent));
    check('a click on a tenor draws its spread and marks its row', await page.evaluate(() => [...document.querySelectorAll(
      '.panel[data-panel="spread-off"] table.grid td.chartlink.pick, .panel[data-panel="spread-viop"] table.grid td.chartlink.pick')].map((td) => td.textContent).join() === '1Y'));
    await page.click('#spread-window button[data-v="60"]');
    await shot(page, '14b-spreads');

    await open(page, 'settings');
    const calRows = () => page.evaluate(() => [...document.querySelectorAll('.set-table tr')].slice(1).map((tr) => [tr.children[0].textContent,
      tr.querySelector('input.date').value, tr.children[3].textContent, tr.children[4].textContent, tr.className.trim()]));
    let cal = await calRows();
    check('settings: the calendar lists the meetings held (archive) and the 80 of the OIS page',
      cal.length === 95 && cal[14][1] === '22.10.2026' && cal[14][2] === 'geçti' && cal[14][3] === 'arşiv'
      && JSON.stringify(cal[15].slice(0, 4)) === JSON.stringify(['1', '10.12.2026', '37 gün', 'OIS listesi · MPC1 (P10)']), [cal[14], cal[15]]);
    check('settings: nothing to roll while no meeting of the list has passed', await page.isDisabled('button:has-text("Geçen toplantıları arşivle")')
      && await page.isDisabled('.set-actions button.primary'));
    const second = page.locator('.set-table tr').nth(17).locator('input.date');
    await second.fill('28.01.2027');
    await second.press('Enter');
    await page.waitForFunction(() => document.querySelectorAll('.set-table tr.changed').length === 1);
    cal = await calRows();
    check('settings: a corrected date is marked until it is saved', cal[16][1] === '28.01.2027' && /önce 21\.01\.2027/.test(cal[16][3]) && cal[16][4] === 'changed', cal[16]);
    await page.click('.set-actions button.primary');
    await page.waitForFunction(() => document.querySelectorAll('.set-table tr.changed').length === 0 && document.querySelector('.set-actions button.primary').disabled);
    check('settings: the saved calendar is the calendar of the OIS page', (await api(page, 'ayşe yilmaz', 'GET', '/api/calendar')).json.meetings[16].date === '2027-01-28');
    await open(page, 'ois');
    check('the meeting date typed in the settings is on the OIS page', (await cellText(page, 'OIS_MAIN!P11')).trim() === '28.01.2027', await cellText(page, 'OIS_MAIN!P11'));
    await open(page, 'settings');
    const again = page.locator('.set-table tr').nth(17).locator('input.date');
    await again.fill('32.01.2027');
    await again.press('Enter');
    check('settings: a date that is none is refused', await again.evaluate((el) => el.classList.contains('bad')));
    await again.fill('21.01.2027');
    await again.press('Enter');
    await page.waitForFunction(() => document.querySelectorAll('.set-table tr.changed').length === 1);
    await page.click('.set-actions button.primary');
    await page.waitForFunction(() => document.querySelector('.set-actions button.primary').disabled);
    await open(page, 'ois');
    check('... and back again', (await cellText(page, 'OIS_MAIN!P11')).trim() === '21.01.2027');
    await open(page, 'settings');
    const series = await rowsOf('series');
    check('settings: which series have history (TLREF, the recorded OIS tenors) and which have none',
      JSON.stringify(rowOf(series, 'TLREF').slice(0, 8)) === JSON.stringify(['TLREF', 'TLREF', 'BISTTREF Index', 'PX_LAST', '30.10.2025', '02.11.2026', '253', 'var'])
      && series.some((r) => r[2] === 'TYSO10 GFOF Curncy' && r[7] === 'geçmiş yok') && series.some((r) => r[2] === 'TYSOA GFOF Curncy' && /yedek kullanılır/.test(r[7]))
      && series.some((r) => r[2] === 'TYSOA Curncy' && r[7] === 'yedek kaynak')
      // (+ the quant package's: 22 pairs, the global drivers, the option surfaces, the VİOP page's five - and its contracts:
      // the six listed and 24 expired months, close / high / low, an expired one with its two-digit-year ticker beside)
      && series.length === 118 + 121 + 3 * (6 + 24) + 3 * 24
      && series.some((r) => r[2] === 'USGG10YR Index' && r[0] === 'Quant'), { tlref: rowOf(series, 'TLREF'), rows: series.length });
    // the order of the pricing sources: for everyone, live pages and history alike
    const srcInputs = (curve) => page.evaluate((c) => [...document.querySelectorAll('#sources-table input[data-curve="' + c + '"]')].map((i) => i.value), curve);
    check('settings: the pricing sources - OIS GFOF, offshore and XCCY ICPL, the workbook\'s BGN ticker last',
      JSON.stringify([await srcInputs('ois'), await srcInputs('off'), await srcInputs('xccy')]) === JSON.stringify([['GFOF', '', '', ''], ['ICPL', '', '', ''], ['ICPL', '', '', '']])
      && await page.locator('.panel[data-panel="sources-used"] table.grid tr').count() === 40);
    await page.locator('#sources-table input[data-curve="off"]').nth(1).fill('bgn');
    await page.click('#sources-save');
    await page.waitForFunction(() => document.querySelectorAll('#sources-table input[data-curve="off"]')[1].value === 'BGN', null, { timeout: 15000 });
    check('settings: a source added to a curve is kept', JSON.stringify((await api(page, 'ayşe yilmaz', 'GET', '/api/sources')).json.curves[1].sources) === '["ICPL","BGN"]');
    await page.click('#sources-default');
    await page.click('#sources-save');
    await page.waitForFunction(() => document.querySelectorAll('#sources-table input[data-curve="off"]')[1].value === '', null, { timeout: 15000 });
    check('settings: the state of the history', /Excel dosyasındaki kayıtlı geçmiş/.test(await page.textContent('.panel[data-panel="history"] .set-info')));
    // the carry: the TLREF path (Bootstrap at first) and the horizons, each user's own
    check('settings: the carry is computed on the bootstrapped curve at first', (await page.inputValue('#carry-path')) === 'Bootstrap'
      && /bootstrap/i.test(await page.textContent('#carry-info')), await page.textContent('#carry-info'));
    await page.selectOption('#carry-path', 'S2');
    await page.fill('#carry-a', '2');
    await page.click('#carry-save');
    await page.waitForFunction(() => /S2/.test(document.getElementById('carry-info').textContent), null, { timeout: 20000 });
    const carrySet = (await api(page, 'ayşe yilmaz', 'GET', '/api/carry')).json;
    check('... a path and a horizon of one\'s own are kept', carrySet.path === 'S2' && carrySet.a === 2, carrySet);
    await page.selectOption('#carry-path', 'Bootstrap');
    await page.fill('#carry-a', '1');
    await page.click('#carry-save');
    await page.waitForFunction(() => /bootstrap/i.test(document.getElementById('carry-info').textContent), null, { timeout: 20000 });
    // the holidays: a list per currency - TRY of both TRY workbooks, USD and EUR of the FX value dates -, one tab each;
    // the SIFMA holidays and the FOMC meetings beside them
    const holText = await page.inputValue('#holidays-text');
    const holTabs = () => page.evaluate(() => [...document.querySelectorAll('#holidays-ccy button')].map((b) => b.textContent + (b.classList.contains('on') ? '!' : '')));
    check('settings: the TR holidays of both workbooks in one list, with the US (SIFMA) holidays and the FOMC meetings',
      /^01\.01\.2026$/m.test(holText) && /^29\.10\.2026\tCumhuriyet$/m.test(holText) && holText.split('\n').length === 152
      && /FOMC toplantıları: 09\.12\.2026/.test(await page.textContent('#holidays-other')), holText.split('\n').slice(0, 3));
    check('... one tab per currency, TRY first', (await holTabs()).join(' ') === 'TRY! USD EUR', await holTabs());
    await page.fill('#holidays-text', holText + '\n31.12.2026\tDeneme tatili');
    await page.click('#holidays-ccy button[data-ccy="USD"]');
    const usdText = await page.inputValue('#holidays-text');
    check('... the USD list: the Fed\'s holidays - Thanksgiving, no Good Friday, nothing for 4 July 2026 (a Saturday)',
      /^26\.11\.2026\tThanksgiving$/m.test(usdText) && !/^03\.04\.2026/m.test(usdText) && !/^0[34]\.07\.2026/m.test(usdText)
      && usdText.split('\n').length === 212 && /212 USD tatili \(en çok 260\)/.test(await page.textContent('#holidays-info'))
      && (await holTabs()).join(' ') === 'TRY • USD! EUR' && await page.locator('#holidays-save').isDisabled(), [usdText.split('\n').slice(0, 2), await holTabs()]);
    await page.locator('.panel[data-panel="holidays"]').scrollIntoViewIfNeeded();
    await shot(page, '15-settings-usd-holidays');
    await page.click('#holidays-ccy button[data-ccy="EUR"]');
    const eurText = await page.inputValue('#holidays-text');
    check('... the EUR list: TARGET2 - Good Friday and Easter Monday', /^03\.04\.2026\tGood Friday$/m.test(eurText)
      && /^06\.04\.2026\tEaster Monday$/m.test(eurText) && eurText.split('\n').length === 98, eurText.split('\n').slice(0, 2));
    await page.fill('#holidays-text', eurText + '\n05.11.2026\tAB deneme');
    await page.click('#holidays-save');
    await page.waitForFunction(() => /99 EUR tatili/.test(document.getElementById('holidays-info').textContent), null, { timeout: 20000 });
    const eurSaved = (await api(page, 'ayşe yilmaz', 'GET', '/api/holidays')).json;
    check('... a day added to the EUR list is written for everyone (the TRY list typed into is not saved with it)',
      eurSaved.lists.EUR.items.some((x) => x.date === '2026-11-05' && x.name === 'AB deneme') && eurSaved.lists.TRY.items.length === 152
      && eurSaved.lists.USD.items.length === 212, [eurSaved.lists.EUR.items.length, eurSaved.lists.TRY.items.length]);
    await page.click('#holidays-ccy button[data-ccy="TRY"]');
    check('... back on TRY, what was typed is still there', (await page.inputValue('#holidays-text')).endsWith('31.12.2026\tDeneme tatili')
      && !(await page.locator('#holidays-save').isDisabled()));
    await page.click('#holidays-save');
    await page.waitForFunction(() => /153 TR tatili/.test(document.getElementById('holidays-info').textContent), null, { timeout: 20000 });
    const holSaved = (await api(page, 'ayşe yilmaz', 'GET', '/api/holidays')).json;
    check('... a day added is written for everyone', holSaved.tr.some((x) => x.date === '2026-12-31' && x.name === 'Deneme tatili'), holSaved.tr.length);
    await shot(page, '15-settings');
    // the EURTRY spot date skips the day added to the EUR list (05.11.2026: the 6th); USDTRY and Bloomberg's own stay
    await open(page, 'forward');
    await waitCell(page, 'Forward!K2', "t === '06.11.2026'");
    check('forward: the EURTRY spot date follows the EUR list, USDTRY and Bloomberg\'s dates beside them do not',
      (await cellText(page, 'Forward!I2')) === '04.11.2026' && (await cellText(page, 'Forward!J2')) === '4.11.2026'
      && (await cellText(page, 'Forward!L2')) === '5.11.2026', [await cellText(page, 'Forward!I2'), await cellText(page, 'Forward!L2')]);
    // the files' own lists again (nothing stored): the pages after this one see the holidays they always did
    await api(page, 'ayşe yilmaz', 'POST', '/api/reset', { book: 'tto', refs: ['Motor!A361:B523'], shared: true });
    await api(page, 'ayşe yilmaz', 'POST', '/api/reset', { book: 'asw', refs: ['ASW!LR2:LR200'], shared: true });
    await api(page, 'ayşe yilmaz', 'POST', '/api/reset', { book: 'tto', refs: ['EK_TATIL!A5:E264'], shared: true });
    const holBack = (await api(page, 'ayşe yilmaz', 'GET', '/api/holidays')).json;
    check('... and the lists of the files come back', holBack.tr.length === 152 && holBack.lists.EUR.items.length === 98
      && holBack.lists.USD.items.length === 212);
    await waitCell(page, 'Forward!K2', "t === '05.11.2026'");

    // ------------------------------------------------------------------ bonds: the chat, the screen, the lists
    console.log('bonds');
    // (the morning's chat is pasted now: the desk's stale limit a day long while it is read, so its quotes stand fresh)
    await api(page, 'ayşe yilmaz', 'POST', '/api/broker/settings', { stale_minutes: 1440 });
    await open(page, 'broker');
    await page.fill('#broker-source', 'ICAP');
    await page.fill('#broker-text', '09:14:59 Auction prices:\n15/03/2028.t1   100.650\n10:25:28 15/3/28 550/575\n'
      + '13:36:12 13/10/27 tlref  100.650/.800\n17:29:21 jan28 tlref .725 trading');
    await page.waitForFunction(() => document.querySelectorAll('#broker-preview table tr').length === 6, null, { timeout: 20000 });
    const bondSeen = await page.evaluate(() => [...document.querySelectorAll('#broker-preview table tr')].slice(1).map((tr) => [...tr.children].map((td) => td.textContent)));
    check('broker chat: bond quotes are read with their ISIN, the lines of an auction list under its heading',
      bondSeen.length === 5 && bondSeen[1][0] === '09:14:59' && bondSeen[1][2] === 'DİBS 15.03.28 · T1' && bondSeen[1][5] === '100,650'
      && /Auction prices/.test(bondSeen[1][6]) && bondSeen[2][2] === 'DİBS 15.03.28' && bondSeen[2][3] === '100,550' && bondSeen[2][4] === '100,575'
      && /TRY 3\d,\d\d \/ 3\d,\d\d%/.test(bondSeen[2][6]), bondSeen);
    check('broker chat: a floater nobody priced takes the big figure of the floater next to it, and says so',
      bondSeen[4][2] === 'DİBS 19.01.28 TLREF' && bondSeen[4][5] === '100,725' && /yakın kâğıttan/.test(bondSeen[4][6]), bondSeen[4]);
    await page.click('#broker-save');
    await page.waitForFunction(() => window.tto.state.page.data.board.some((r) => r.isin === 'TRT190128T14'), null, { timeout: 20000 });
    await open(page, 'dibs');
    const rvBroker = await page.evaluate(() => {
      const p = document.querySelector('.panel[data-panel="B3"]');
      const rows = [...p.querySelectorAll('table.grid tr')].map((tr) => [...tr.children].map((td) => td.textContent));
      const head = rows.find((r) => r.includes('Broker bid')) || [];
      const bond = rows.find((r) => r[0] === 'TRT150328T24') || [];
      return { head: head.slice(-7, -1), bond: bond.slice(-7, -1) };          // the dashboard's own columns, on the right (▸ last)
    });
    check('DİBS RV: the day\'s broker chat next to each bond - the best bid and ask, whose and how old, the yield of the mid against the screen',
      rvBroker.head.join('|') === 'Broker bid|Broker ask|Son işlem|Kimde · yaş|Broker getiri %|Broker − ekran (bp)'
      && rvBroker.bond[0] === '100,550' && rvBroker.bond[1] === '100,575' && /^ICAP · (şimdi|\d+ dk|\d+ sa \d+ dk)$/.test(rvBroker.bond[3])
      && /^3\d,\d\d$/.test(rvBroker.bond[4]) && /^[+-]?\d+$/.test(rvBroker.bond[5]), rvBroker);
    // the board's rules there too: a quote older than the desk's stale limit (10 minutes) never looks current - greyed, "bayat" with
    // its broker and age, and no yield nor distance from the screen of it
    const rvHalfHourAgo = new Date(Date.now() - 30 * 60000);
    if (rvHalfHourAgo.toDateString() === new Date().toDateString()) {      // (just after midnight there was no half an hour ago today)
      await api(page, 'ayşe yilmaz', 'POST', '/api/broker/settings', { stale_minutes: 10 });
      await api(page, 'ayşe yilmaz', 'POST', '/api/broker', { text: rvHalfHourAgo.toTimeString().slice(0, 8) + ' 16/4/31 94.000/94.200', source: 'BGC' });
      await open(page, 'broker');
      await open(page, 'dibs');
      await fresh(page);                                                  // (the page kept from before is dimmed until current)
      // (a change made through the API reaches this tab with the next generation - within a second: the page kept from
      // before shows until then)
      await page.waitForFunction(() => {
        const tr = [...document.querySelectorAll('.panel[data-panel="B3"] table.grid tr')].find((x) => (x.children[0] || {}).textContent === 'TRT160431T35');
        return !!tr && /BGC/.test(tr.textContent);
      }, null, { timeout: 20000 }).catch(() => {});
      const rvStale = await page.evaluate(() => {
        const tr = [...document.querySelectorAll('.panel[data-panel="B3"] table.grid tr')].find((x) => (x.children[0] || {}).textContent === 'TRT160431T35');
        const cells = tr ? [...tr.children].slice(-7, -1) : [];
        return { text: cells.map((td) => td.textContent), grey: cells.map((td) => td.classList.contains('stale')) };
      });
      check('... a quote half an hour old: greyed, "bayat" with its broker and age, no yield and no distance from the screen',
        rvStale.text[0] === '94,000' && rvStale.text[1] === '94,200' && rvStale.grey[0] && rvStale.grey[1] && rvStale.grey[3]
        && /^bayat · BGC · 3\d dk$/.test(rvStale.text[3]) && rvStale.text[4] === 'bayat' && rvStale.text[5] === '', rvStale);
      // (the limit stays the desk's 10 minutes: what follows reads the levels, a stale one shows its level too, greyed)
    }
    // a bond added from the catalog of the desk's list
    const rvIsins = () => page.evaluate(() => [...document.querySelectorAll('.panel[data-panel="B3"] table.grid tr')].map((tr) => (tr.children[0] || {}).textContent).filter((t) => /^TR/.test(t || '')));
    const rvBefore = await rvIsins();
    await page.click('.panel[data-panel="B3"] button[data-action="add-isin"]');
    await page.waitForSelector('#isin-table tr:nth-child(5)');
    const catalog = await page.evaluate(() => ({ rows: document.querySelectorAll('#isin-table tr').length - 1, have: document.querySelectorAll('#isin-table tr.have').length }));
    check('DİBS RV: "+ ISIN ekle" lists the desk\'s 77 TRY government bonds, the ones listed already ticked',
      catalog.rows === 77 && catalog.have === rvBefore.length, { catalog, listed: rvBefore.length });
    await page.click('#isin-kind button[data-v="frn"]');
    await page.fill('#isin-find', '2030');
    await page.locator('#isin-table tr:not(.have) input.pick').first().check();
    await page.fill('#isin-text', 'TRT999999T99');
    await page.click('#isin-add');
    await page.waitForTimeout(600);
    check('... an ISIN whose check digit is wrong is refused, nothing is added', /kontrol hanesi/.test(await page.textContent('#toasts'))
      && (await page.locator('#isin-table').count()) === 1 && (await rvIsins()).length === rvBefore.length);
    await page.fill('#isin-text', 'TRT280432T14');
    await page.click('#isin-add');
    await page.waitForFunction((n) => [...document.querySelectorAll('.panel[data-panel="B3"] table.grid tr')]
      .filter((tr) => /^TR/.test((tr.children[0] || {}).textContent || '')).length === n + 2, rvBefore.length, { timeout: 30000 });
    const rvAfter = await rvIsins();
    check('... an FRN picked and an ISIN typed go to the first empty rows of the list, for everyone',
      rvAfter.length === rvBefore.length + 2 && rvAfter.includes('TRT280432T14') && /2 kâğıt eklendi/.test(await page.textContent('#toasts'))
      && (await api(page, 'mehmet demir', 'GET', '/api/bonds/catalog')).json.bonds.find((b) => b.isin === 'TRT280432T14').lists.includes('dibs'), rvAfter.slice(-3));
    // tables that grow: the rows in use and one more, "+ Satır" for another
    await open(page, 'bulk');
    const bulkShown = () => page.evaluate(() => [...document.querySelectorAll('.panel[data-panel="B1"] table.grid tbody > tr')].filter((tr) => !tr.classList.contains('grow-hidden')).length);
    const bulkAll = await page.evaluate(() => document.querySelectorAll('.panel[data-panel="B1"] table.grid tbody > tr').length);
    const shown0 = await bulkShown();
    await page.click('.panel[data-panel="B1"] .grow-more');
    const shown1 = await bulkShown();
    check('Bulk Bond: 50 bond rows, the page shows the ones in use and one more; "+ Satır" opens another',
      bulkAll >= 52 && shown0 < bulkAll && shown1 === shown0 + 1, { bulkAll, shown0, shown1 });
    await open(page, 'forward');
    await tab(page, 'bulk');
    const fwdShown = () => page.evaluate(() => [...document.querySelectorAll('.panel[data-panel="BK1"] table.grid tbody > tr')].filter((tr) => !tr.classList.contains('grow-hidden')).length);
    const fwd0 = await fwdShown();
    const fwdAll = await page.evaluate(() => document.querySelectorAll('.panel[data-panel="BK1"] table.grid tbody > tr').length);
    await page.click('.panel[data-panel="BK1"] .grow-all');
    check('Forward: the bulk table has 100 value dates; the filled ones and one more are shown, "Tümü" shows every row',
      fwdAll >= 100 && fwd0 < 40 && (await fwdShown()) === fwdAll, { fwd0, fwdAll });
    await page.click('.panel[data-panel="BK1"] .grow-all');
    check('... and back to the filled ones', (await fwdShown()) === fwd0);
    // DİBS Canlı: the value dates side by side, the day's tape, the bond's card
    await open(page, 'dibslive');
    await page.waitForSelector('.panel[data-panel="L1"] table.grid');
    const liveRow = await page.evaluate(() => {
      const rows = [...document.querySelectorAll('.panel[data-panel="L1"] table.grid tr')].map((tr) => [...tr.children].map((td) => td.textContent));
      const head = rows.find((r) => r.includes('T1 bid')) || [];
      const bond = rows.find((r) => r[0] === 'TRT150328T24') || [];
      const at = (name) => bond[head.indexOf(name)];
      return { label: bond[1], t1: [at('T1 bid'), at('T1 ask'), at('T1 son işlem'), at('T1 son işlem günü')], t0: at('T0 bid'),
        broker: [at('Broker bid'), at('Broker ask')], card: bond[bond.length - 1],
        sources: (rows.find((r) => r.includes('ISL0')) || []).filter((x) => /^(ISL[0-9N]|BGN)$/.test(x)) };
    });
    check('DİBS Canlı: every bond on T0 / T1 / T2 (sources ISL0 / ISL1 / ISLN and BGN), the RV value date from the recorded file, the chat\'s quotes on the right',
      liveRow.label === '15.03.28' && JSON.stringify(liveRow.t1) === '["100,100","100,125","100,200","03.11.2026"]' && liveRow.t0 === ''
      && JSON.stringify(liveRow.broker) === '["100,550","100,575"]' && liveRow.card === '▸' && liveRow.sources.join(',') === 'ISL0,ISL1,ISLN,BGN', liveRow);
    const tapeRows = await page.evaluate(() => [...document.querySelectorAll('.panel[data-panel="L3"] table.grid tr')].map((tr) => [...tr.children].map((td) => td.textContent)));
    check('DİBS Canlı: the day\'s bond trades, newest first, with who said them',
      tapeRows[0][0] === 'Saat' && tapeRows.length >= 2 && tapeRows[1][1] === '19.01.28 TLREF' && tapeRows[1][3] === '100,725' && /ICAP/.test(tapeRows[1][7]), tapeRows.slice(0, 3));
    await page.click('.panel[data-panel="L1"] table.grid td.cardlink[title$="TRT150328T24"]');
    await page.waitForSelector('.modal.bondcard');
    const cardText = await page.textContent('.modal.bondcard');
    check('the bond card: what it is, its value dates, the board, the chat and its row of DİBS RV',
      /15\.03\.28 · TRT150328T24/.test(cardText) && /Sabit · kupon %36,80 · vade 15\.03\.2028/.test(cardText) && /T1 · ISL1/.test(cardText)
      && /Broker Chat · bugün/.test(cardText) && /BIST bileşik getiri/.test(cardText) && /Sinyal/.test(cardText) && /Bid boyutu/.test(cardText),
      cardText.slice(0, 300));
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => !document.querySelector('.modal.bondcard'));
    await open(page, 'dibs');
    await page.click('.panel[data-panel="B3"] table.grid td.cardlink[title$="TRT160431T35"]');
    await page.waitForSelector('.modal.bondcard');
    check('... and from DİBS RV too', /16\.04\.31 · TRT160431T35/.test(await page.textContent('.modal.bondcard header')));
    await page.keyboard.press('Escape');
    // Tüm Kâğıtlar: every bond kind by kind; ☆ puts one on the trading list, ★ takes it off
    await open(page, 'kagitlar');
    await page.waitForSelector('.panel[data-panel="U1"] table.grid');
    const uni = await page.evaluate(() => {
      const rows = [...document.querySelectorAll('.panel[data-panel="U1"] table.grid tr')].map((tr) => [...tr.children].map((td) => td.textContent));
      return { bonds: rows.filter((r) => /^TR[A-Z0-9]{9}\d$/.test(r[0])).length, captions: rows.filter((r) => /· \d+ kâğıt$/.test(r[0])).map((r) => r[0]),
        stars: document.querySelectorAll('.panel[data-panel="U1"] td.flag.on').length, open: document.querySelectorAll('.panel[data-panel="U1"] td.flag:not(.on)').length };
    });
    check('Tüm Kâğıtlar: the 77 bonds of the desk\'s list kind by kind (TLREF and FRN apart), the ones on the trading list starred',
      uni.bonds === 77 && uni.captions.length === 6 && uni.captions.includes('FRN · 9 kâğıt') && uni.stars >= 19 && uni.stars + uni.open === 77, uni);
    const flagOf = (panel, isin) => '.panel[data-panel="' + panel + '"] table.grid td.flag[title$="' + isin + '"]';
    await page.click(flagOf('U1', 'TRT130127T11'));
    await page.waitForFunction((sel) => { const td = document.querySelector(sel); return td && td.classList.contains('on'); }, flagOf('U1', 'TRT130127T11'), { timeout: 20000 });
    await open(page, 'dibslive');
    await page.waitForSelector('.panel[data-panel="L0"] table.grid');
    const summaryRows = () => page.evaluate(() => [...document.querySelectorAll('.panel[data-panel="L0"] table.grid tr')].map((tr) => [...tr.children].map((td) => td.textContent)));
    const inSummary = (await summaryRows()).filter((r) => r[2] === 'TRT130127T11');
    check('☆ puts a bond on the trading list: DİBS Trading has it in its summary, under its kind',
      inSummary.length === 1 && inSummary[0][1] === '13.01.27 TLREF' && (await summaryRows()).some((r) => /^TLREF'e endeksli · \d+$/.test(r[0])), inSummary);
    await page.click(flagOf('L0', 'TRT130127T11'));
    const unstarred = await page.waitForFunction(() => ![...document.querySelectorAll('.panel[data-panel="L0"] table.grid tr')]
      .some((tr) => tr.children[2] && tr.children[2].textContent === 'TRT130127T11'), null, { timeout: 20000 }).then(() => true, () => false);
    check('... and ★ takes it off', unstarred && !(await api(page, 'ayşe yilmaz', 'GET', '/api/bonds/catalog')).json.bonds.find((b) => b.isin === 'TRT130127T11').lists.includes('dibs'));
    // "+ ISIN ekle" on Tüm Kâğıtlar: onto the desk's list, its kind from Bloomberg (offline it waits for it); ✕ takes it off
    await open(page, 'kagitlar');
    await page.waitForSelector('.panel[data-panel="U1"] table.grid');
    await page.click('.panel[data-panel="U1"] button[data-action="add-isin"]');
    await page.fill('#isin-text', 'TRT080931T14');
    await page.click('#isin-add');
    const unlistOf = (isin) => '.panel[data-panel="U1"] table.grid td.unlist[title$="' + isin + '"]';
    await page.waitForSelector(unlistOf('TRT080931T14'), { timeout: 30000 });
    const firstCells = await page.evaluate(() => [...document.querySelectorAll('.panel[data-panel="U1"] table.grid tr')].map((tr) => (tr.children[0] || {}).textContent || ''));
    check('Tüm Kâğıtlar: "+ ISIN ekle" puts a new bond on the desk\'s list, for everyone (offline its kind waits for Bloomberg)',
      firstCells.includes('Türü bekleniyor (Bloomberg) · 1 kâğıt') && firstCells.includes('TRT080931T14') && /bekleniyor/.test(await page.textContent('#toasts'))
      && (await api(page, 'mehmet demir', 'GET', '/api/bonds/catalog')).json.bonds.some((b) => b.isin === 'TRT080931T14'), firstCells.slice(-6));
    await page.click(unlistOf('TRT080931T14'));
    await page.click('.modal button.btn.primary');
    const unlisted = await page.waitForFunction((sel) => !document.querySelector(sel), unlistOf('TRT080931T14'), { timeout: 20000 }).then(() => true, () => false);
    check('... and ✕ takes it off the list, for everyone', unlisted
      && !(await api(page, 'mehmet demir', 'GET', '/api/bonds/catalog')).json.bonds.some((b) => b.isin === 'TRT080931T14'));

    // ------------------------------------------------------------------ watch list and alarms
    console.log('watch list and alarms');
    await open(page, 'watch');
    await page.click('#watch-preset');
    await page.click('.menu >> text=TRY OIS eğrisi');
    await page.waitForFunction(() => document.querySelectorAll('#watch-table tr').length === 10, null, { timeout: 20000 });
    const watchRows = await page.evaluate(() => [...document.querySelectorAll('#watch-table tr')].slice(1).map((tr) => [...tr.children].map((td) => td.textContent)));
    check('İzleme: the OIS curve in one click - the level now, the open, the change of the day',
      watchRows.length === 9 && watchRows[3][0] === 'OIS 1Y' && /^3\d,\d\d%$/.test(watchRows[3][1]) && watchRows[3][1] === watchRows[3][2] && watchRows[3][3] === '0,0 bp', watchRows[3]);
    await open(page, 'dibs');
    await (await cellHandle(page, 'DİBS RV!T8')).click({ button: 'right' });
    await page.click('.menu >> text=İzlemeye ekle');
    await page.waitForFunction(() => /İzleme listesine eklendi/.test(document.getElementById('toasts').textContent), null, { timeout: 10000 });
    await open(page, 'watch');
    const watched = await page.evaluate(() => [...document.querySelectorAll('#watch-table tr')].pop().children[0].textContent);
    check('... and any cell from its right-click menu (a bond\'s yield: the bond, named as the desk calls it)', watched === '15.03.28 getiri', watched);
    const oneY = await page.evaluate(() => [...document.querySelectorAll('#watch-table tr')].findIndex((tr) => tr.children[0].textContent === 'OIS 1Y'));
    await page.click('#watch-table tr:nth-child(' + (oneY + 1) + ') button[title="Bu kaleme alarm kur"]');
    await page.waitForSelector('#alarm-level');
    await page.fill('#alarm-level', '30,00');
    await page.click('#alarm-save');
    await page.waitForFunction(() => /🔔 OIS 1Y/.test(document.getElementById('toasts').textContent), null, { timeout: 20000 });
    await page.waitForSelector('#fired-table', { timeout: 20000 });
    check('an alarm that fires is told on the page that is open (and listed with the ones of the day)',
      /≥ 30,00%/.test(await page.textContent('#toasts')) && /OIS 1Y/.test(await page.textContent('#fired-table'))
      && /çaldı/.test(await page.textContent('#alarm-table')));
    // anything: a VİOP contract's OIS − VİOP spread, a bond's ASW, an expression built of them
    const openPick = async () => {
      await page.click('#watch-add');
      await page.waitForSelector('#pick-kind button.on');
    };
    const pickNow = (re) => page.waitForFunction((r) => new RegExp(r).test(document.getElementById('pick-now').textContent), re, { timeout: 20000 });
    await openPick();
    await page.selectOption('#pick-viop', 't:A1Z6 Curncy');
    await pickNow('VİOP A1Z6 OIS − VİOP');
    const viopNow = await page.textContent('#pick-now');
    await page.fill('#alarm-level', '250');
    await page.click('#alarm-save');
    await page.waitForFunction(() => /Alarm kuruldu: VİOP A1Z6 OIS − VİOP/.test(document.getElementById('toasts').textContent), null, { timeout: 20000 });
    let watchNow = (await api(page, 'ayşe yilmaz', 'GET', '/api/watch')).json;
    const viopAlarm = watchNow.alarms.find((a) => a.label === 'VİOP A1Z6 OIS − VİOP');
    check('Ekle: a VİOP contract\'s OIS − VİOP spread, its value shown as it is picked - an alarm at 250 bp (and watched)',
      /Şimdi: 2\d\d,\d bp/.test(viopNow) && viopAlarm && viopAlarm.level_text === '250,0 bp' && viopAlarm.active
      && watchNow.items.some((i) => i.label === 'VİOP A1Z6 OIS − VİOP' && / bp$/.test(i.now)), [viopNow, viopAlarm]);
    await openPick();
    await page.click('#pick-kind button[data-k="bond"]');
    await page.selectOption('#pick-bond', 'TRT150328T24');
    await page.selectOption('#pick-bond-metric', 'asw');
    await pickNow('15.03.28 ASW');
    await page.click('#alarm-op button[data-v="<="]');
    await page.fill('#alarm-level', '-60');
    await page.click('#alarm-save');
    await page.waitForFunction(() => /🔔 15.03.28 ASW/.test(document.getElementById('toasts').textContent), null, { timeout: 20000 });
    check('... a bond\'s ASW at or below a level (here already: it fires at once)', /15.03.28 ASW: -\d+,\d bp {2}\(≤ -60,0 bp\)/.test(await page.textContent('#toasts')),
      await page.textContent('#toasts'));
    await openPick();
    await page.click('#pick-kind button[data-k="ois"]');
    await page.selectOption('#pick-ois', '2Y');
    await pickNow('OIS 2Y');
    await page.click('#pick-toexpr');
    await page.waitForSelector('#pick-expr');
    const exprStart = await page.inputValue('#pick-expr');
    await page.fill('#pick-expr', exprStart + ' -');
    await page.waitForFunction(() => /yarım/.test(document.getElementById('pick-now').textContent), null, { timeout: 20000 });
    await page.fill('#pick-expr', exprStart + ' - [OIS 1Y]');
    await pickNow('Şimdi: -?\\d+,\\d bp');
    const exprNow = await page.textContent('#pick-now b.v');
    await page.click('#pick-watch');
    await page.waitForFunction(() => [...document.querySelectorAll('#watch-table tr')].some((tr) => tr.children[0].textContent === '[OIS 2Y] - [OIS 1Y]'), null, { timeout: 20000 });
    const exprRow = await page.evaluate(() => [...[...document.querySelectorAll('#watch-table tr')].find((tr) => tr.children[0].textContent === '[OIS 2Y] - [OIS 1Y]').children].map((td) => td.textContent));
    check('... and anything built of them: picked, then "İfadeye ekle", then written on - a spread of rates told in bp',
      exprStart === '[OIS 2Y]' && exprRow[1] === exprNow && / bp$/.test(exprNow), [exprStart, exprNow, exprRow]);
    // the z-score of each item against its past (20 / 60 / 250 closes) and an alarm on it
    const zHead = () => page.evaluate(() => [...document.querySelectorAll('#watch-table tr:first-child th')].map((x) => x.textContent).find((t) => /^z \(/.test(t)));
    const zOf = (label) => page.evaluate((l) => {
      const tr = [...document.querySelectorAll('#watch-table tr')].find((x) => x.children[0].textContent === l);
      return tr ? tr.querySelector('td.z').textContent : null;
    }, label);
    const z60 = await zOf('OIS 1Y');
    await page.click('#watch-zdays button[data-v="20"]');
    await page.waitForFunction(() => /z \(20g\)/.test(document.getElementById('watch-table').textContent), null, { timeout: 15000 });
    check('İzleme: each item\'s z-score against its own past - 60 closes, or 20 / 250 picked', (await zHead()) === 'z (20g)' && /^−?\d+,\d\d$/.test(z60)
      && /^−?\d+,\d\d$/.test(await zOf('OIS 1Y')), [z60, await zOf('OIS 1Y')]);
    await page.click('#watch-zdays button[data-v="60"]');
    await openPick();
    await page.click('#pick-kind button[data-k="ois"]');
    await page.selectOption('#pick-ois', '1Y');
    await pickNow('OIS 1Y');
    await page.click('#alarm-mode button[data-v="z"]');
    await page.click('#alarm-zdays button[data-v="20"]');
    const zInfo = await page.textContent('#alarm-zinfo');
    await page.fill('#alarm-z', '5');
    await page.click('#alarm-save');
    await page.waitForFunction(() => /z\(20g\) ≥ 5,00/.test(document.getElementById('watch-alarms').textContent), null, { timeout: 20000 });
    check('... an alarm on the z-score (the window\'s closes and z now shown as it is set)', /^şu an z = −?\d+,\d\d · \d+ kapanış/.test(zInfo), zInfo);
    // the desk's alarms: an administrator sets one for everyone; it rings on every open page; one answer is everyone's
    await page.click('#desk-add');
    await page.waitForSelector('#alarm-desk');
    const deskTicked = await page.isChecked('#alarm-desk');
    await page.click('#pick-kind button[data-k="ois"]');
    await page.selectOption('#pick-ois', '1Y');
    await pickNow('OIS 1Y');
    await page.fill('#alarm-level', '30,00');
    await page.click('#alarm-save');
    await page.waitForFunction(() => /MASA ALARMI · OIS 1Y/.test(document.getElementById('toasts').textContent), null, { timeout: 20000 });
    await page.waitForFunction(() => !document.getElementById('desk-alarm').classList.contains('hidden'), null, { timeout: 15000 });
    const deskCounter = await page.textContent('#desk-alarm');
    const deskOthers = (await api(page, 'mehmet', 'GET', '/api/alarms/fired?since=0&desk=0')).json.desk;
    check('Masa alarmı: set by an administrator for everyone ("Masa alarmı kur…" ticks the box) - it rings with "Gördüm, ben bakıyorum", the top bar counts it, everyone has it open',
      deskTicked && deskCounter === '🔔 1 masa alarmı' && deskOthers.open.length === 1 && deskOthers.open[0].label === 'OIS 1Y', [deskTicked, deskCounter, deskOthers.open]);
    await page.click('.toast.alarm.desk button');
    await page.waitForFunction(() => /✓ Gördüm – Ayşe Yılmaz bakıyor/.test(document.getElementById('toasts').textContent), null, { timeout: 15000 });
    await page.waitForFunction(() => document.getElementById('desk-alarm').classList.contains('hidden'), null, { timeout: 15000 });
    await page.waitForFunction(() => /Ayşe Yılmaz bakıyor/.test((document.getElementById('desk-table') || {}).textContent || ''), null, { timeout: 15000 });
    const deskAfter = (await api(page, 'mehmet', 'GET', '/api/watch')).json.desk;
    check('... one answer is everyone\'s: "✓ Gördüm – Ayşe Yılmaz bakıyor", no longer counted, in the day\'s log',
      deskAfter.open.length === 0 && deskAfter.alarms[0].entry.ack_name === 'Ayşe Yılmaz' && deskAfter.log.some((e) => e.kind === 'ack'), deskAfter.open);
    // muting is personal: Ayşe mutes it for herself; re-armed, it fires for everyone - and stays silent for her only
    await page.click('#desk-table button[title^="Yalnızca benim için sustur"]');
    await page.click('.menu >> text=15 dakika');
    await page.waitForFunction(() => /Sizin için susturuldu/.test(document.getElementById('toasts').textContent), null, { timeout: 15000 });
    await page.waitForFunction(() => /sizin için susturuldu/.test((document.getElementById('desk-table') || {}).textContent || ''), null, { timeout: 15000 });
    await page.click('#desk-table button[title="Aynı koşulla herkese yeniden kur"]');
    let forMehmet = null;
    for (let i = 0; i < 60; i++) {
      forMehmet = (await api(page, 'mehmet', 'GET', '/api/alarms/fired?since=0&desk=0')).json.desk;
      if (forMehmet.open.length === 1) break;
      await page.waitForTimeout(500);
    }
    await page.waitForTimeout(2500);                      // the page has looked at what fired by now (a new generation)
    const forAyse = (await api(page, 'ayşe yilmaz', 'GET', '/api/alarms/fired?since=0&desk=0')).json.desk;
    const silent = await page.evaluate(() => document.getElementById('desk-alarm').classList.contains('hidden')
      && document.querySelectorAll('.toast.alarm.desk:not(.answered)').length === 0);
    const mutedLine = (await api(page, 'mehmet', 'GET', '/api/watch')).json.desk.log.find((e) => e.kind === 'mute');
    check('... muting is personal: muted by Ayşe for herself, it fires again for everyone (open for Mehmet) - for her no toast, not counted; the log says she muted it for herself',
      forMehmet.open.length === 1 && forMehmet.open[0].muted === false && forAyse.open.length === 1 && forAyse.open[0].muted === true && silent
      && mutedLine && mutedLine.by_name === 'Ayşe Yılmaz' && /^kendisi için 15 dk susturdu/.test(mutedLine.text), [forMehmet.open, forAyse.open, silent, mutedLine]);
    await page.locator('#watch-desk').scrollIntoViewIfNeeded();
    await shot(page, 'masa-alarmlari');

    // ------------------------------------------------------------------ the heat map of the curves
    console.log('heat map');
    await open(page, 'heat');
    await page.waitForSelector('table.heat[data-panel="curve"]');
    const heatRows = await page.evaluate(() => [...document.querySelectorAll('table.heat th.row')].map((x) => x.textContent).filter(Boolean));
    const heatOf = (label) => page.evaluate((l) => {
      const td = [...document.querySelectorAll('table.heat td.hc')].find((x) => x.title.split('\n')[0] === l);
      return td ? { chg: td.querySelector('.c').textContent, level: td.querySelector('.l').textContent, bg: td.style.background } : null;
    }, label);
    check('Eğri Hareketi: OIS, offshore and their difference by tenor, the VİOP contracts, the bonds - each point\'s level and change',
      JSON.stringify(heatRows.slice(0, 5)) === JSON.stringify(['OIS', 'Offshore', 'Offshore − OIS', 'OIS − VİOP', 'ima TRY'])
      && (await heatOf('OIS 1Y')).level === '35,55' && (await heatOf('VİOP A1Z6 OIS − VİOP')) !== null, heatRows);
    await page.click('#heat-basis button[data-v="open"]');
    await page.waitForFunction(() => /açılıştan/.test(document.getElementById('heat-info').textContent), null, { timeout: 15000 });
    await page.click('#heat-ref');
    await page.waitForFunction(() => /referanstan \(\d\d:\d\d:\d\d\)/.test(document.getElementById('heat-info').textContent), null, { timeout: 15000 });
    check('... against the open, or against a reference taken on purpose (no move since: 0,0)', (await heatOf('OIS 2Y')).chg === '0,0'
      && /−\d+ bp/.test(await page.textContent('#heat-legend')), await heatOf('OIS 2Y'));
    // a locator, found again when the live map redraws itself between finding the point and clicking it
    await page.locator('table.heat[data-panel="curve"] td.hc[title^="OIS 2Y\\A"]').first().click();
    await page.click('.menu >> text=Hareket alarmı…');
    await page.waitForSelector('#alarm-from');
    await page.selectOption('#alarm-from', 'window');
    await page.fill('#alarm-minutes', '15');
    await page.click('#alarm-dir button[data-v="up"]');
    await page.fill('#alarm-size', '3');
    await page.click('#alarm-save');
    await page.waitForFunction(() => /Alarm kuruldu: OIS 2Y · 15 dk içinde ↑ 3,0 bp/.test(document.getElementById('toasts').textContent), null, { timeout: 20000 });
    const moveAlarm = (await api(page, 'ayşe yilmaz', 'GET', '/api/watch')).json.alarms.find((a) => a.mode === 'window');
    check('... a point clicked: a move alarm on it (within the last 15 minutes, 3 bp up)', moveAlarm && moveAlarm.minutes === 15
      && moveAlarm.condition === '15 dk içinde ↑ 3,0 bp' && moveAlarm.active, moveAlarm);
    await open(page, 'watch');
    await page.fill('#notes-text', 'Sabah toplantısı: 1Y 35,50 üstü alıcı yok');
    await page.click('#notes-save');
    await page.waitForFunction(() => /Son kaydeden/.test(document.getElementById('notes-info').textContent), null, { timeout: 10000 });
    check('the desk\'s notes of the day are kept for everyone',
      (await api(page, 'mehmet', 'GET', '/api/watch')).json.notes.text === 'Sabah toplantısı: 1Y 35,50 üstü alıcı yok');

    // ------------------------------------------------------------------ find a table from anywhere
    console.log('table search');
    await page.keyboard.press('Control+k');
    await page.keyboard.type('interest');
    await page.waitForSelector('.findlist .hit');
    const hits = await page.evaluate(() => [...document.querySelectorAll('.findlist .hit')].map((x) => x.querySelector('.t').textContent + ' @ ' + x.querySelector('.w').textContent));
    // each calculator once, at its home: the copies on the Calculators and VİOP pages are helper tables, not offered
    check('Ctrl+K lists the tables of every page by name', hits.length === 4 && hits.every((x) => / @ Forward › Hesaplayıcılar$/.test(x))
      && hits.some((x) => /^Interest 2 SP · TRY faizi.* @ Forward › Hesaplayıcılar$/.test(x)), hits);
    await page.fill('#find', 'faizden fiyat');
    await page.waitForFunction(() => document.querySelectorAll('.findlist .hit').length === 1);
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => window.tto.state.pageId === 'viop' && window.tto.state.page && window.tto.state.page.ready, null, { timeout: 90000 });
    await page.waitForTimeout(600);
    check('Enter goes to the table: its page, its tab', (await panelsOnPage(page)).includes('XAU4')
      && await page.evaluate(() => document.querySelector('.viewtabs button.on').dataset.tab) === 'calc');

    // ------------------------------------------------------------------ the columns each user hides
    console.log('hidden columns');
    const rv = '.panel[data-panel="B3"]';
    const colHidden = (sel, j) => page.evaluate(([s, k]) => {
      const g = document.querySelector(s + ' table.grid').__grid;
      return g.tds.every((line) => !line[k] || line[k].hidden);
    }, [sel, j]);
    const hiddenOf = async (user, table) => ((await api(page, user, 'GET', '/api/columns')).json.tables || {})[table];
    await open(page, 'dibs');
    await tab(page, '*');
    await page.locator(rv + ' tr.hd td', { hasText: 'Kaynak (boş = genel)' }).click({ button: 'right' });
    await page.click('.menu >> text=Sütunu gizle: Kaynak (boş = genel)');
    await page.waitForFunction((s) => !document.querySelector(s + ' .colschip').classList.contains('hidden'), rv);
    check('DİBS RV: a right click on a caption hides its column, the header says so',
      await colHidden(rv, 1) && await page.textContent(rv + ' .colschip') === 'Gizlediğiniz 1 sütun');
    check('... kept with this user\'s account (by the table and the sheet\'s column), nobody else\'s view changes',
      JSON.stringify(await hiddenOf('ayşe yilmaz', 'v/dibs/B3')) === '["B"]' && (await hiddenOf('mehmet', 'v/dibs/B3')) === undefined);
    await (await cellHandle(page, 'DİBS RV!A4')).click();
    await (await cellHandle(page, 'DİBS RV!D6')).click({ modifiers: ['Shift'] });
    const visibleCopy = (await page.evaluate(() => window.tto.selectionText(false))).split('\r\n');
    check('... a copy takes what is on screen', visibleCopy[0] === 'ISIN\tAd\tTip (S/T/F/E/B)' && visibleCopy.every((l) => l.split('\t').length === 3), visibleCopy);
    await (await cellHandle(page, 'DİBS RV!A6')).click();
    await page.keyboard.press('ArrowRight');
    check('... the arrow keys step over it', await page.evaluate(() => document.querySelector('#content td.cur').__j) === 2);
    await page.reload();
    await page.waitForFunction(() => window.tto && window.tto.state.pageId === 'dibs' && window.tto.state.page && window.tto.state.page.ready, null, { timeout: 90000 });
    await page.waitForSelector(rv + ' table.grid');
    check('... and stays hidden when the page is opened again', await colHidden(rv, 1));
    await page.click(rv + ' .colschip');
    await page.locator('.menu label.mcheck').filter({ has: page.locator('.t', { hasText: /^Ad$/ }) }).locator('input').click();
    await page.waitForFunction((s) => document.querySelector(s + ' .colschip').textContent === 'Gizlediğiniz 2 sütun', rv);
    check('"Sütunlar": every column with a tick - untick one and it goes (the list stays open)',
      await colHidden(rv, 2) && await page.locator('.menu label.mcheck').count() >= 60
      && JSON.stringify(await hiddenOf('ayşe yilmaz', 'v/dibs/B3')) === '["B","C"]');
    await page.click('.menu >> text=Tümünü göster');
    await page.waitForFunction((s) => document.querySelector(s + ' .colschip').classList.contains('hidden'), rv);
    check('... "Tümünü göster" brings every column back', !(await colHidden(rv, 1)) && !(await colHidden(rv, 2))
      && (await hiddenOf('ayşe yilmaz', 'v/dibs/B3')) === undefined);
    // a table of the dashboard's own: a column by its caption, across pages
    await open(page, 'eod');
    const eodCurve = '.panel[data-panel="curve"]';
    await page.locator(eodCurve + ' tr.hd2 td', { hasText: /^Δ1G bp$/ }).first().click({ button: 'right' });       // TRY OIS's
    await page.click('.menu >> text=/^Sütunu gizle/');
    await open(page, 'masa');
    await open(page, 'eod');
    check('Gün Sonu: the column hidden is still hidden when the page is opened again, named by its caption',
      await colHidden(eodCurve, 2) && JSON.stringify(await hiddenOf('ayşe yilmaz', 'h/curve')) === '["TRY OIS · par (%) · Δ1G bp"]',
      await hiddenOf('ayşe yilmaz', 'h/curve'));
    await page.click(eodCurve + ' .colschip');
    await page.click('.menu >> text=Tümünü göster');
    // a list built by hand (İzleme): a right click on its caption; the list is drawn again on every refresh
    await open(page, 'watch');
    await page.locator('#watch-table th', { hasText: /^Bant$/ }).click({ button: 'right' });
    await page.click('.menu >> text=Sütunu gizle: Bant');
    await page.evaluate(() => window.tto.refresh());
    await page.waitForTimeout(600);
    const bant = await page.evaluate(() => {
      const t = document.getElementById('watch-table');
      const j = [...t.rows[0].cells].findIndex((c) => c.textContent === 'Bant');
      return { j, hidden: [...t.rows].every((r) => r.cells[j].hidden) };
    });
    check('İzleme: a column of the list stays hidden when the list is drawn again', bant.j > 0 && bant.hidden, bant);
    await page.locator('#watch-table th', { hasText: /^Ad$/ }).click({ button: 'right' });
    await page.click('.menu >> text=Gizlediğiniz sütunları göster (1)');
    check('... and comes back from the same menu', !(await page.evaluate(() => [...document.getElementById('watch-table').rows[0].cells].some((c) => c.hidden))));

    // ------------------------------------------------------------------ the desk's own: Hata / Öneri, Sosyal, Ajanda
    console.log('reports, chat, agenda');
    const ctxD = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
    const pageD = await ctxD.newPage();
    pageD.on('pageerror', (e) => errors.push('pageerror(D): ' + e.message));
    await login(pageD, 'Mehmet');
    check('no report open: no "!" for the administrator', await page.isHidden('#fb-alert'));
    await open(pageD, 'social');
    await pageD.click('#btn-feedback');
    await pageD.waitForSelector('#fb-text');
    await pageD.click('#fb-kind button[data-v="idea"]');
    await pageD.fill('#fb-text', 'Forward sayfasına 2Y satırı için kısayol olsun');
    await pageD.click('#fb-send');
    await pageD.waitForFunction(() => /yöneticilere iletildi/.test(document.getElementById('toasts').textContent), null, { timeout: 15000 });
    await page.waitForSelector('#fb-alert:not(.hidden)', { timeout: 15000 });
    check('a report comes to the administrator as a "!" at once - never to a user, who cannot list them either',
      await pageD.isHidden('#fb-alert') && (await api(page, 'mehmet', 'GET', '/api/feedback')).status === 403);
    await page.click('#btn-feedback');
    await page.waitForSelector('#fb-list .fb-item');
    const report = await page.textContent('#fb-list .fb-item');
    check('the administrator sees what, by whom, from which page', /2Y satırı için kısayol/.test(report) && /Öneri/.test(report)
      && /Mehmet/.test(report) && /Sosyal/.test(report), report);
    await page.click('#fb-list .fb-item .btn.primary');
    await page.waitForSelector('#fb-list details.fb-done .fb-item', { state: 'attached', timeout: 15000 });
    check('"İlgilenildi": the report leaves the badge and goes to the history', await page.isHidden('#fb-alert')
      && /İlgilenildi: Ayşe Yılmaz/.test(await page.textContent('#fb-list details.fb-done')));
    await page.keyboard.press('Escape');
    // Sosyal: two traders, each line on the other's screen at once
    await open(page, 'social');
    const chatTexts = (p) => p.evaluate(() => [...document.querySelectorAll('#chat-log .msg .mt')].map((x) => x.textContent));
    await pageD.fill('#chat-text', 'Günaydın, 2Y OIS alıcı var mı?');
    await pageD.press('#chat-text', 'Enter');
    await page.waitForFunction(() => /alıcı var mı/.test(document.getElementById('chat-log').textContent), null, { timeout: 15000 });
    await page.fill('#chat-text', 'Var: 35,10');
    await page.press('#chat-text', 'Shift+Enter');
    await page.type('#chat-text', '5Y da bakarım');
    await page.press('#chat-text', 'Enter');
    await pageD.waitForFunction(() => /5Y da bakarım/.test(document.getElementById('chat-log').textContent), null, { timeout: 15000 });
    const seenD = await chatTexts(pageD);
    check('a chat line shows up on the other trader\'s screen at once, with its name and time (and its second line)',
      seenD.slice(-2).join('|') === 'Günaydın, 2Y OIS alıcı var mı?|Var: 35,10\n5Y da bakarım'
      && /Ayşe Yılmaz/.test(await pageD.textContent('#chat-log .msg:last-child .who')) && /\d\d:\d\d/.test(await pageD.textContent('#chat-log .msg:last-child time')), seenD);
    await pageD.fill('#chat-text', '<img src=x onerror="window.hacked=1"> sağ ol');
    await pageD.press('#chat-text', 'Enter');
    await page.waitForFunction(() => /sağ ol/.test(document.getElementById('chat-log').textContent), null, { timeout: 15000 });
    check('what is written is shown as text, never as page code', await page.evaluate(() => !document.querySelector('#chat-log img') && !window.hacked));
    await open(page, 'masa');
    await pageD.fill('#chat-text', 'PPK 14:00\'te');
    await pageD.press('#chat-text', 'Enter');
    await page.waitForSelector('#nav .nav-item[data-page="social"] .nav-count', { timeout: 15000 });
    check('on another page the menu counts the messages not read', (await page.textContent('#nav .nav-item[data-page="social"] .nav-count')) === '1');
    await open(page, 'social');
    check('... and the count goes when the chat is read', await page.locator('#nav .nav-item[data-page="social"] .nav-count').count() === 0);
    await pageD.hover('#chat-log .msg.mine:last-child');
    await pageD.click('#chat-log .msg.mine:last-child .del');
    await pageD.click('.modal .mfoot .btn.primary');
    await page.waitForFunction(() => !/PPK 14:00/.test(document.getElementById('chat-log').textContent), null, { timeout: 15000 });
    check('a message taken back by its writer goes from every screen', (await chatTexts(page)).length === 3);
    // Ajanda: a deadline in ten minutes is told; one not met comes first; one's own item is nobody else's
    await open(page, 'agenda');
    await open(pageD, 'agenda');
    const soon = await page.evaluate(() => {
      const p = (n) => String(n).padStart(2, '0');
      const iso = (d) => d.getFullYear() + '-' + p(d.getMonth() + 1) + '-' + p(d.getDate());
      const now = new Date();
      const at = new Date(now.getTime() + 10 * 60000);
      return { today: iso(now) === iso(at), day: iso(at), time: p(at.getHours()) + ':' + p(at.getMinutes()),
        yesterday: iso(new Date(now.getFullYear(), now.getMonth(), now.getDate() - 1)),
        tomorrow: iso(new Date(now.getFullYear(), now.getMonth(), now.getDate() + 1)) };
    });
    if (soon.today) await page.click('#agenda-today'); else await page.fill('#agenda-day', soon.day);
    await page.fill('#agenda-time', soon.time);
    await page.fill('#agenda-text', 'İhale sonuçlarını masaya ilet');
    await page.check('#agenda-deadline');
    await page.click('#agenda-add');
    await page.waitForFunction(() => /Deadline yaklaşıyor \(\d+ dk\): .*İhale sonuçlarını masaya ilet/.test(document.getElementById('toasts').textContent), null, { timeout: 15000 });
    check('a deadline coming within 15 minutes is told on the screen', true);
    await pageD.waitForFunction(() => /İhale sonuçlarını/.test(document.getElementById('agenda-list').textContent), null, { timeout: 15000 });
    check('the desk\'s item is on the other trader\'s agenda at once, marked a deadline',
      /Deadline/.test(await pageD.textContent('#agenda-list tr[data-id]:has-text("İhale sonuçlarını")')));
    const late = await api(page, 'ayşe yilmaz', 'POST', '/api/agenda', { day: soon.yesterday, text: 'Aylık rapor', deadline: true });
    await page.fill('#agenda-day', soon.tomorrow);
    await page.fill('#agenda-time', '09:30');
    await page.fill('#agenda-text', 'Kendi notum: bankayı ara');
    await page.click('#agenda-scope button[data-v="own"]');
    await page.click('#agenda-add');
    await page.waitForFunction(() => /bankayı ara/.test(document.getElementById('agenda-list').textContent)
      && document.querySelector('#agenda-list .agenda-day.late'), null, { timeout: 15000 });
    const groups = await page.evaluate(() => [...document.querySelectorAll('#agenda-list .agenda-day')].map((s) => s.dataset.group));
    check('a deadline not met comes first, then today, then the days ahead', late.status === 200 && groups[0] === 'late' && groups[1] === 'today'
      && /Aylık rapor/.test(await page.textContent('#agenda-list .agenda-day.late')), groups);
    await page.waitForSelector('#nav .nav-item[data-page="agenda"] .nav-count.alert', { timeout: 15000 });
    check('the menu counts today\'s items and the deadline not met (red)',
      Number(await page.textContent('#nav .nav-item[data-page="agenda"] .nav-count')) >= 1);
    await pageD.waitForFunction(() => /Aylık rapor/.test(document.getElementById('agenda-list').textContent), null, { timeout: 15000 });
    check('one\'s own item is nobody else\'s', !/bankayı ara/.test(await pageD.textContent('#agenda-list')));
    await pageD.check('#agenda-list .agenda-day.late tr[data-id] input[type=checkbox]');
    await page.waitForFunction(() => !document.querySelector('#agenda-list .agenda-day.late'), null, { timeout: 15000 });
    check('ticked off by another trader: no longer late, on every screen', true);
    // Ajanda, recurring: a deadline "Her iş günü" a few minutes ahead ("Seçili günler" with that day when it is not a
    // business day of the desk's calendar) - its alarm on another page, once per browser however many windows, "Ertele"
    // for oneself, "Bugün tamam" for that day only; the rule under "Tekrarlayan işler", paused, deleted
    console.log('agenda: recurring items');
    await open(pageD, 'social');
    const page2 = await ctxA.newPage();                       // a second window of Ayşe's browser, on another page
    await page2.goto(BASE + '/#/social');
    await page2.waitForFunction(() => window.tto && window.tto.state.pageId === 'social' && window.tto.state.page
      && window.tto.state.page.ready, null, { timeout: 90000 });
    const shut = new Set((await api(page, 'ayşe yilmaz', 'GET', '/api/holidays')).json.tr.map((x) => x.date));
    const rep = await page.evaluate(() => {
      const p = (n) => String(n).padStart(2, '0');
      const at = new Date(Date.now() + 4 * 60000);
      return { day: at.getFullYear() + '-' + p(at.getMonth() + 1) + '-' + p(at.getDate()), time: p(at.getHours()) + ':' + p(at.getMinutes()),
        dow: ((at.getDay() + 6) % 7) + 1 };
    });
    const businessDay = rep.dow <= 5 && !shut.has(rep.day);
    const REP = 'Swap limitlerini kontrol et (tekrar)';
    await page.fill('#agenda-day', soon.tomorrow);
    await page.selectOption('#agenda-repeat', 'daily');
    const fromDay = await page.textContent('#agenda-repeat-row');
    await page.click('#agenda-today');
    check('repeating, the day field is the first day - said beside it', /başlangıç \d\d\.\d\d\.\d{4}/.test(fromDay)
      && /bugünden başlar/.test(await page.textContent('#agenda-repeat-row')), fromDay);
    await page.fill('#agenda-time', rep.time);
    await page.fill('#agenda-text', REP);
    await page.check('#agenda-deadline');
    await page.click('#agenda-scope button[data-v="shared"]');              // (the item before was one's own)
    await page.selectOption('#agenda-repeat', businessDay ? 'workdays' : 'weekdays');
    if (!businessDay) await page.check('#agenda-weekdays input[data-d="' + rep.dow + '"]');
    check('Tekrar: the days of the week only for "Seçili günler", an end day for any repeat',
      await page.isVisible('#agenda-weekdays') === !businessDay && await page.isVisible('#agenda-end'));
    await page.click('#agenda-add');
    await page.waitForFunction(() => !document.getElementById('agenda-text').value && document.querySelector('#agenda-rules tr[data-rule]'),
      null, { timeout: 15000 });
    const repRule = (await api(page, 'ayşe yilmaz', 'GET', '/api/agenda')).json.rules.find((r) => r.text === REP);
    const repRow = '#agenda-rules tr[data-rule="' + (repRule && repRule.id) + '"]';
    check('a recurring item: under "Tekrarlayan işler" with how it repeats and when it comes next, the form back to "Bir kez"',
      !!repRule && repRule.repeat === (businessDay ? 'workdays' : 'weekdays') && repRule.time === rep.time && repRule.deadline && repRule.shared
      && /Bugün|Yarın/.test(await page.textContent(repRow + ' td.next')) && (await page.inputValue('#agenda-repeat')) === 'once', repRule);
    check('... and its day on the agenda among the day\'s items, marked as recurring',
      /↻/.test(await page.textContent('#agenda-list tr[data-rule="' + repRule.id + '"]')));
    const alarmOn = (p) => p.locator('#toasts .toast.agenda-alarm', { hasText: REP });
    await pageD.waitForFunction((t) => [...document.querySelectorAll('#toasts .toast.agenda-alarm')].some((x) => x.textContent.includes(t)
      && x.querySelector('.ag-snooze') && x.querySelector('.ag-done')), REP, { timeout: 20000 });
    check('its alarm comes on another page (another trader\'s), with "Ertele 10 dk" and "Bugün tamam"',
      /Deadline yaklaşıyor \(\d+ dk\)/.test(await alarmOn(pageD).first().textContent()));
    for (let i = 0; i < 40 && (await alarmOn(page).count()) + (await alarmOn(page2).count()) === 0; i++) await page.waitForTimeout(500);
    await page2.waitForTimeout(2500);                          // (the other window had its chance too)
    const onA = await alarmOn(page).count();
    const onA2 = await alarmOn(page2).count();
    check('two windows of one browser: the alarm in one of them only', onA + onA2 === 1, { onA, onA2 });
    await alarmOn(onA ? page : page2).locator('.ag-snooze').click();
    await (onA ? page : page2).waitForFunction((t) => ![...document.querySelectorAll('#toasts .toast.agenda-alarm')].some((x) => x.textContent.includes(t)),
      REP, { timeout: 15000 });
    await pageD.waitForTimeout(1500);
    const deskA = (await api(page, 'ayşe yilmaz', 'GET', '/api/desk')).json;
    check('"Ertele 10 dk": gone for the one who put it off - told again in 10 minutes - and still there for the other trader',
      !deskA.alarms.some((x) => x.rule === repRule.id) && deskA.next > 0 && deskA.next <= 600 && await alarmOn(pageD).count() === 1, deskA);
    await alarmOn(pageD).locator('.ag-done').click();
    await pageD.waitForFunction((t) => ![...document.querySelectorAll('#toasts .toast.agenda-alarm')].some((x) => x.textContent.includes(t)),
      REP, { timeout: 15000 });
    await page.waitForSelector('#agenda-list tr[data-rule="' + repRule.id + '"].done', { timeout: 15000 });
    const after = (await api(page, 'mehmet', 'GET', '/api/agenda')).json;
    const repDay = after.items.find((x) => x.rule === repRule.id && x.day === rep.day);
    const repNext = after.rules.find((r) => r.id === repRule.id).next;
    check('"Bugün tamam": that day done (by whom) on every screen - the next day still to come',
      !!repDay && repDay.done && repDay.done_by === 'Mehmet' && /Mehmet/.test(await page.textContent('#agenda-list tr[data-rule="' + repRule.id + '"]'))
      && !!repNext && repNext.day > rep.day, { repDay, repNext });
    await page.click(repRow + ' .rule-pause');
    await page.waitForSelector(repRow + '.paused', { timeout: 15000 });
    check('paused under "Tekrarlayan işler": said so, nothing comes next',
      /Duraklatıldı/.test(await page.textContent(repRow)) && (await api(page, 'ayşe yilmaz', 'GET', '/api/agenda')).json.rules
        .find((r) => r.id === repRule.id).paused);
    await page.click(repRow + ' .rule-del');
    await page.click('.modal .mfoot .btn.primary');
    await page.waitForSelector(repRow, { state: 'detached', timeout: 15000 });
    check('... and deleted', !(await api(page, 'ayşe yilmaz', 'GET', '/api/agenda')).json.rules.some((r) => r.id === repRule.id));
    await page2.close();
    await ctxD.close();

    // ------------------------------------------------------------------ the daily backup: the administrators' page
    console.log('backup');
    await open(page, 'backup');
    const bk0 = (await api(page, 'ayşe yilmaz', 'GET', '/api/admin/backup')).json;
    const sep = bk0.dir.includes('\\') ? '\\' : '/';
    check('Yedekleme: 17:30 by default, the data folder\'s backups, no second copy here (a checkout) - said, with a hint to choose one',
      (await page.inputValue('#bk-time')) === '17:30' && (await page.inputValue('#bk-dir')) === bk0.dir && (await page.inputValue('#bk-copy')) === ''
      && await page.isVisible('#bk-copy-hint') && /İkinci kopya seçilmedi/.test(await page.textContent('#bk-copy-hint'))
      && /varsayılan/.test(await page.textContent('#bk-sources tr[data-key="time"]')), bk0);
    await page.fill('#bk-dir', 'yedekler');
    await page.fill('#bk-copy', bk0.dir + sep + 'OneDrive' + sep + 'tto-yedek');
    await page.click('#bk-save');
    await page.waitForFunction(() => document.getElementById('bk-dir-err').textContent && document.getElementById('bk-copy-err').textContent,
      null, { timeout: 15000 });
    check('a relative folder is refused next to its field', /Tam yol/.test(await page.textContent('#bk-dir-err')));
    check('... a folder OneDrive synchronises too, saying why - and nothing is saved',
      /OneDrive/.test(await page.textContent('#bk-copy-err')) && /Bloomberg verisi ve şifre özetleri/.test(await page.textContent('#bk-copy-err'))
      && (await api(page, 'ayşe yilmaz', 'GET', '/api/admin/backup')).json.source.dir === 'default');
    const chosenDir = bk0.dir + '-secilen';
    const chosenCopy = bk0.dir + '-kopya';
    await page.fill('#bk-time', '17:45');
    await page.fill('#bk-dir', chosenDir);
    await page.fill('#bk-copy', chosenCopy);
    await page.click('#bk-save');
    await page.waitForFunction(() => /yönetici seçimi/.test(document.querySelector('#bk-sources tr[data-key="dir"]').textContent), null, { timeout: 15000 });
    check('folders that are fine: saved, before the command line / defaults, the errors gone, the hint too',
      /17:45/.test(await page.textContent('#bk-sources tr[data-key="time"]')) && (await page.textContent('#bk-dir-err')) === ''
      && /Kaydeden: Ayşe Yılmaz/.test(await page.textContent('#bk-saved')) && !(await page.isVisible('#bk-copy-hint')));
    const bk1 = (await api(page, 'ayşe yilmaz', 'GET', '/api/admin/backup')).json;       // (the folders as the server wrote them down)
    await page.click('#bk-now');
    await page.waitForFunction(() => /İkinci kopya yazıldı/.test(document.getElementById('bk-result').textContent), null, { timeout: 60000 });
    const bkDone = await page.textContent('#bk-result');
    check('a backup now: the file, its size, its second copy written - in the folders just chosen',
      /tto-\d{4}-\d{2}-\d{2}\.db/.test(bkDone) && /MB/.test(bkDone) && bk1.source.dir === 'saved' && bkDone.includes(bk1.dir)
      && bkDone.includes(bk1.copy_dir), [bkDone, bk1.dir, bk1.copy_dir]);
    check('... the newest backups of each folder are listed', (await page.locator('#bk-list tr').count()) === 2
      && (await page.locator('#bk-copies tr').count()) === 2);
    // the chosen folder cannot be written (its drive is gone: a file where it was): the backup goes to the dashboard's
    // own folder, its second copy is made from it - the page and the status say so; the folder back, the next backup
    // reaches it and the page says the day is there too
    const fs = require('fs');
    fs.rmSync(bk1.dir, { recursive: true, force: true });
    fs.writeFileSync(bk1.dir, 'surucu yok');
    await page.click('#bk-now');
    await page.waitForFunction(() => /henüz ulaşmadı/.test((document.getElementById('bk-fallback') || {}).textContent || ''), null, { timeout: 60000 });
    const bkFell = await page.textContent('#bk-result');
    const fellStatus = (await api(page, 'ayşe yilmaz', 'GET', '/api/status')).json.ops.db.backup.fallback;
    check('the chosen folder cannot be written: the backup goes to the dashboard\'s own folder, the second copy from it, the status says so',
      /yazılamadı/.test(bkFell) && /İkinci kopya yazıldı/.test(bkFell) && (await page.locator('#bk-own tr').count()) >= 2
      && fellStatus && fellStatus.waiting.length === 1, [bkFell, fellStatus]);
    fs.rmSync(bk1.dir, { force: true });
    await page.click('#bk-now');
    await page.waitForFunction(() => /seçilen klasörde de/.test((document.getElementById('bk-fallback') || {}).textContent || ''), null, { timeout: 60000 });
    check('... the folder back: the next backup reaches it, the page says the day is there too',
      !(await api(page, 'ayşe yilmaz', 'GET', '/api/status')).json.ops.db.backup.fallback.waiting.length);
    const esc = (s) => JSON.stringify(s).slice(1, -1);
    const userStatus = JSON.stringify((await api(page, 'mehmet', 'GET', '/api/status')).json);
    const userCalls = [await api(page, 'mehmet', 'GET', '/api/admin/backup'), await api(page, 'mehmet', 'POST', '/api/admin/backup', { values: { time: '18:00' } }),
      await api(page, 'mehmet', 'POST', '/api/admin/backup/now', {})];
    check('a user gets 403 from the backup settings and from a backup now, and the status names none of the folders',
      userCalls.every((r) => r.status === 403) && !userStatus.includes(esc(bk1.dir)) && !userStatus.includes(esc(bk1.copy_dir)),
      userCalls.map((r) => r.status));
    await page.click('#bk-reset');
    await page.click('.modal .mfoot .btn.primary');
    await page.waitForFunction(() => /varsayılan/.test(document.querySelector('#bk-sources tr[data-key="dir"]').textContent), null, { timeout: 15000 });
    check('"Varsayılanlara dön": the defaults again, the backups taken stay where they are',
      (await page.inputValue('#bk-time')) === '17:30' && (await page.inputValue('#bk-dir')) === bk0.dir && await page.isVisible('#bk-copy-hint')
      && (await api(page, 'ayşe yilmaz', 'GET', '/api/admin/backup')).json.saved === null);
    await shot(page, '30-backup');

    // ------------------------------------------------------------------ one live stream per browser, however many tabs
    console.log('many tabs');
    await open(page, 'forward');
    const streamsBefore = (await api(page, 'ayşe yilmaz', 'GET', '/api/status')).json.streams;
    const tabs = [];
    for (let i = 0; i < 7; i++) {
      const p = await ctxA.newPage();
      await p.goto(BASE + '/#/calc');
      await p.waitForFunction(() => window.tto && window.tto.state.pageId === 'calc' && window.tto.state.page && window.tto.state.page.ready,
        null, { timeout: 90000 });
      tabs.push(p);
    }
    check('8 tabs of one browser: every one opens its page (the 7th is not left waiting for a connection)', tabs.length === 7);
    await page.waitForTimeout(2500);
    const streamsDuring = (await api(page, 'ayşe yilmaz', 'GET', '/api/status')).json.streams;
    check('... with one live stream between them, not one each', streamsDuring === streamsBefore, { streamsBefore, streamsDuring });
    const asked = [];
    page.on('request', (r) => { if (r.url().includes('/api/view/forward')) asked.push(r.url()); });
    await api(page, 'ayşe yilmaz', 'POST', '/api/inputs', { book: 'tto', items: [{ ref: 'Forward!D2', value: '17.12.2026' }] });
    const genNow = (await api(page, 'ayşe yilmaz', 'GET', '/api/status')).json.gen;
    for (const p of [page].concat(tabs)) {
      await p.waitForFunction((g) => window.tto.state.gen >= g, genNow, { timeout: 15000 });
    }
    check('... a change reaches every tab', true);
    await page.waitForFunction(() => !window.tto.state.refreshing, null, { timeout: 15000 });
    check('a refresh asks only for the open tab\'s panels, and only what changed since',
      asked.length > 0 && asked.every((u) => u.includes('since=') && u.includes('panels=')), asked.slice(0, 3));
    await api(page, 'ayşe yilmaz', 'POST', '/api/reset', { book: 'tto', refs: ['Forward!D2'] });
    for (const p of tabs) await p.close();

    // ------------------------------------------------------------------ quant signals
    console.log('quant signals');
    await open(page, 'quant');
    await page.waitForSelector('#quant-signals', { timeout: 30000 });
    // the analyses run in their own thread a few seconds after the start: the page asks until the first result is there
    await page.waitForFunction(() => /^Hesap /.test((document.getElementById('quant-status') || {}).textContent || ''), null, { timeout: 90000 });
    const quantTables = await page.locator('#content .quantpage table.grid').count();
    const deskAlarm = await page.locator('#quant-settings select#quant-set-desk_alarm').inputValue();
    check('the Sinyaller page renders: signals, log, subscription, settings (desk alarms from Güçlü), status tables', quantTables >= 2
      && await page.locator('#quant-subscribe input#quant-sub-on').count() === 1 && await page.locator('#quant-settings input#quant-set-entry_z').count() === 1
      && deskAlarm === 'Güçlü', { tables: quantTables, deskAlarm });
    const qs = await api(page, 'ayşe yilmaz', 'GET', '/api/quant/status');
    check('the quant analyses answer from their own thread', qs.status === 200 && qs.json.ready === true && qs.json.fits >= 1, qs.json);
    check('the desk settings carry the FX pair list, the carry margin and the backtest floor (off)',
      await page.locator('#quant-settings input#quant-set-fx_pairs').count() === 1 && await page.locator('#quant-settings input#quant-set-carry_margin').count() === 1
      && await page.locator('#quant-settings select#quant-set-bt_mute').inputValue() === 'kapalı');
    const bt = await api(page, 'ayşe yilmaz', 'GET', '/api/quant/backtest');
    check('the backtest panel and its API are there', bt.status === 200 && await page.locator('#quant-backtest').count() === 1, bt.json);
    // a signal in plain words: the card's sentence (the server writes it from the signal's own numbers), the trade in desk
    // words with the instrument's prices, the money - FX per 1 mn of the base currency split into the forward premium and
    // the spot's move, a rates package in bp and TL - and the list's expected P&L with its unit. The recorded month has too
    // few closes for a signal: the card and the rows are drawn from an FX and a rates signal as the server sends them.
    const sigApi = await api(page, 'ayşe yilmaz', 'GET', '/api/quant/signals');
    const served = ((sigApi.json || {}).signals || []).concat((sigApi.json || {}).gated || []);
    const FX_PLAIN = 'Bugün 3 aylık USDTRY forward\'ını satıp ~63 iş günü tutarsan (giriş 44,1250) ve kur o sürede beklenen seviyeye gelirse (43,6000), '
      + '1 mn USD başına ~525 bin TRY kazanırsın: forward priminden (carry) +2.325 bin TRY, kur hareketinden -1.800 bin TRY (spot 41,8000 → 43,6000). '
      + 'Hedefte (43,6000) ~525 bin TRY kâr, stopta (44,6000) ~475 bin TRY zarar.';
    const card = await page.evaluate(async (plain) => {
      const q = await import('/static/js/pages/quantbase.js');
      const base = { family: 'fwdprem', family_label: 'Forward primi', asset: 'FX', z: 2.6, entry_z: 2, strength: 'Güçlü', gates: [], legs: [], agree: 0,
        conflict: 0, parts: { z: 2.6, regime: 1, hl: 1, carry: 1 }, composite: 2.6, hold: 63, horizon_unit: 'gün', bt: null };
      const fx = Object.assign({}, base, { id: 'fwdprem:USDTRY:3M', expression: 'Sell USDTRY 3M forward', direction: -1, unit: '%', digits: 2, entry: 3.1,
        target: 0.4, stop: 6.9, pnl_unit: '%', exp_pnl: 1.19, carry_yr: 22.6, plain, trade_tr: 'USDTRY 3A forward sat', pnl_try: 525000,
        legs: [{ key: 'FX:USDTRY', name: 'USDTRY 3M forward', action: 'Sell', side: -1, weight: 1, text: 'Sell USDTRY 3M forward' }],
        fx: { pair: 'USDTRY', spot: 41.8, fwd_h: 44.125, tenors: ['1M', '3M'] },
        px: { pair: 'USDTRY', inst: 'USDTRY 3A forward', label: 'USDTRY 3A fwd', tenor: '3A', days: 91.25, note: 'bugünkü 3A forward', digits: 4, unit: 'TRY',
          entry: 44.125, target: 43.6, stop: 44.6, exit: 43.6, spot: 41.8, spot_exp: 43.6, fwd_h: 44.125 },
        money: { ccy: 'TRY', base: 'USD', notional: 1e6, total: 525000, carry: 2325000, move: -1800000, target: 525000, stop: -475000, try_per: 1, usd_per: 1 / 41.8 } });
      const rate = Object.assign({}, base, { id: 'pca:OIS:2Y', family: 'pca', family_label: 'PCA kalıntısı', asset: 'TRY OIS', expression: 'Receive 2Y OIS (PC1–PC2 hedge\'li)',
        instrument: '2Y OIS (PC1–PC2 hedge\'li)', direction: -1, unit: 'bp', digits: 1, entry: 3, target: 0, stop: 3.5, pnl_unit: 'bp', exp_pnl: 5.08, rr: 6,
        reward: 3, risk: 0.5, carry_week: 1, trade_tr: 'sabit faiz alınan (receive): 2Y OIS (değişken bacak TLREF)', plain: 'Sabit faiz alınan (receive): 2Y OIS …',
        money: { ccy: 'TL', per_bp: 40000, dv01_usd: 1000, total: 203200, carry: 103200, move: 100000, target: 120000, stop: -20000,
          bp: { total: 5.08, carry: 2.58, move: 2.5, target: 3, stop: -0.5 } } });
      const read = (s) => {
        // (what a click on a row does: the card's show(); a one-day history draws no chart - the sentence and the trade
        // are above the charts and come all the same)
        const host = document.createElement('div');
        const c = new q.SignalChart(host);
        c.show({ monitor: { name: s.instrument || 'USDTRY 3M forward' }, signal: s, history: { days: ['2026-11-02'], values: [1] }, settings: {}, rationale: null });
        const text = (sel) => (host.querySelector(sel) || {}).textContent || '';
        const out = { plain: text('#quant-sig-plain'), trade: text('#quant-sig-trade'), prices: text('#quant-sig-prices'), pnl: text('#quant-sig-pnl'), ends: text('#quant-sig-ends') };
        c.destroy();
        return out;
      };
      const rows = q.signalRows([fx, rate]);
      const col = (name) => q.SIGNAL_HEAD.indexOf(name);
      return { fx: read(fx), rate: read(rate), cells: rows.map((r) => r[col('Beklenen K/Z')].t), entry: rows[0][col('Giriş')].t, unit: rows[0][col('Birim')].t };
    }, FX_PLAIN);
    check('a signal card says an FX trade plainly: the sentence, "USDTRY 3A forward sat" at the forward\'s price, the money per 1 mn USD split into the forward premium and the spot\'s move',
      card.fx.plain === FX_PLAIN && card.fx.trade === 'USDTRY 3A forward sat · 1 mn USD'
      && card.fx.prices.startsWith('44,1250 / 43,6000 / 44,6000 · USDTRY 3A forward (giriş: bugünkü 3A forward · spot 41,8000)')
      && card.fx.pnl === '+525 bin TRY / 1 mn USD · forward primi (carry) +2.325 bin TRY · kur hareketi -1.800 bin TRY'
      && card.fx.ends === 'hedefte +525 bin TRY · stopta -475 bin TRY (1 mn USD) · ödül / risk 1,11', card.fx);
    check('... a rates package in bp and TL: what is received / paid, at the target and the stop; the list\'s expected P&L in money (FX) or bp',
      card.rate.trade === 'sabit faiz alınan (receive): 2Y OIS (değişken bacak TLREF) · ana bacak 1.000 $ DV01 = 40.000 TL / bp'
      && card.rate.pnl === '+5,08 bp ≈ +203 bin TL · carry + roll +2,58 bp · hareket +2,50 bp'
      && card.rate.ends === 'hedefte 3,0 bp ≈ +120 bin TL · stopta 0,5 bp ≈ -20 bin TL · ödül / risk 6,00' && card.rate.prices.startsWith('+3,0 bp / 0,0 bp / +3,5 bp')
      && card.cells[0] === '+525 bin TRY / 1 mn USD' && card.cells[1] === '+5,08 bp' && card.entry === '44,1250' && card.unit === 'USDTRY 3A fwd', card);
    check('... and every signal the server gives carries its trade in desk words and its sentence', sigApi.status === 200
      && served.every((s) => s.trade_tr && typeof s.plain === 'string' && s.plain.length > 0), served.length);
    await shot(page, 'quant-signals');
    await open(page, 'quant-pca');
    await page.waitForSelector('#quant-pca-windows', { timeout: 30000 });
    check('PCA / RV shows the dynamic PCA, both fly conventions and the path\'s fit', await page.locator('#quant-pca-stability').count() === 1
      && /klasik/.test(await page.textContent('#quant-pca-rv')) && /Konvansiyon|Patika yok/.test(await page.textContent('#quant-pca-tenors')));
    // each table's read line (quantread.js): right under its title, in the desk's words; its method note below it as "Yöntem"
    const pcaRead = await page.evaluate(() => [...document.querySelectorAll('section.panel[id^="quant-pca-"]')].map((p) => {
      const r = p.querySelector(':scope > .qread'), n = p.querySelector(':scope > .qnote');
      return { id: p.id, read: r ? r.textContent : '', under: !!r && (r.previousElementSibling || {}).tagName === 'HEADER' && getComputedStyle(r).display !== 'none',
        method: n && n.classList.contains('qmethod') && n.textContent ? getComputedStyle(n, '::before').content : null };
    }));
    check('every PCA / RV table says under its title what it tells and which number is a trade, its method below it as "Yöntem"',
      pcaRead.length >= 12 && pcaRead.every((p) => p.read.length >= 40 && p.under)
      && pcaRead.filter((p) => p.method !== null).length >= 6 && pcaRead.every((p) => p.method === null || p.method === '"Yöntem: "'), pcaRead);
    await open(page, 'quant-fx');
    await page.waitForSelector('#quant-fx-summary', { timeout: 30000 });
    check('the FX page starts with the per-pair carry summary', /Carry % \/ yıl|tarihçesi yok/.test(await page.textContent('#quant-fx-summary')));
    await open(page, 'quant-intraday');
    await page.waitForSelector('#quant-intraday-bars', { timeout: 30000 });
    check('Gün İçi says replay mode has no bars', /Kayıtlı veri modunda gün içi bar yok/.test(await page.textContent('#quant-intraday-bars')));
    // curve fair value: the NSS fits of the OIS quotes and of the DİBS RV list's fixed-coupon bonds and bills (today's
    // quotes of the workbook; the recorded data has no DİBS history, so no z yet)
    await open(page, 'quant-curve');
    await page.waitForSelector('#quant-curve-ois table.grid', { timeout: 60000 });
    const qcv = await api(page, 'ayşe yilmaz', 'GET', '/api/quant/curve');
    const oisRows = await page.locator('#quant-curve-ois table.grid tbody tr:not(.hd)').count();
    const dibsRows = await page.locator('#quant-curve-dibs table.grid tbody tr:not(.hd)').count();
    const cv = (qcv.json || {}).curve || {}, dv = (qcv.json || {}).dibsfv || {};
    check('Eğri Adil Değeri: every OIS tenor against its NSS fit (bp), every fixed-coupon bond and bill against the DİBS fit, with carry + roll',
      qcv.status === 200 && cv.ok && cv.rows.length >= 12 && oisRows === cv.rows.length && cv.rmse < 50 && dv.ok && dv.rows.length >= 6
      && dibsRows === dv.rows.length && dv.rows.every((r) => (r.kind === 'fixed' || r.kind === 'bill') && r.total_1m !== null)
      && await page.locator('#quant-curve-ois svg.chart').count() === 1,
    { ois: oisRows, dibs: dibsRows, rmse: cv.rmse, why: cv.why || dv.why });
    // a two-way quote of a fixed-coupon bond from the fair curve, and a switch between two of them
    await page.waitForFunction(() => document.querySelectorAll('#quant-curve-quote table.grid tbody tr:not(.hd)').length >= 4
      && document.querySelectorAll('#quant-curve-switch table.grid tbody tr:not(.hd)').length === 3, null, { timeout: 30000 });
    const quoteRows = await page.evaluate(() => [...document.querySelectorAll('#quant-curve-quote table.grid tbody tr:not(.hd)')].map((tr) => tr.children[0].textContent));
    const swq = await api(page, 'ayşe yilmaz', 'GET', '/api/quant/switch?a=TRT150328T24&b=TRT160431T35');
    check('Eğri Adil Değeri: a bond quoted from the fair curve (bid / fair / ask, the market) and a DV01-neutral switch',
      quoteRows.join('|').startsWith('Alış (bid)|Adil (NSS)|Satış (ask)|Piyasa') && swq.status === 200 && swq.json.ok
      && Math.abs(swq.json.ratio * swq.json.b.market.dv01 - swq.json.a.market.dv01) < 1e-6
      && /^Switch: 15\.03\.28 sat \/ 16\.04\.31 al/.test(swq.json.line), { quoteRows, sw: swq.json && (swq.json.line || swq.json.why) });
    await shot(page, 'quant-curve');
    // options: the vol surface of USDTRY and EURUSD by tenor and the smile's probabilities (the recorded data has no vol
    // quotes: the rows are there, empty, and the smile says why)
    await open(page, 'quant-opt');
    await page.waitForSelector('#quant-opt-surface table.grid', { timeout: 60000 });
    const qop = await api(page, 'ayşe yilmaz', 'GET', '/api/quant/opt');
    const surfRows = await page.locator('#quant-opt-surface table.grid tbody tr:not(.hd)').count();
    const op = (qop.json || {}).opt || {};
    check('Opsiyon: the surface by pair and tenor, the probability table, and why a smile is missing',
      qop.status === 200 && op.ok && op.pairs.length === 2 && surfRows === 10
      && op.pairs.every((p) => p.smiles.length === 2 && p.smiles.every((s) => s.probs.length === 3 && (s.model || s.why))),
    { rows: surfRows, smiles: op.pairs && op.pairs.map((p) => p.smiles.map((s) => s.model || s.why)) });
    await shot(page, 'quant-opt');

    // ------------------------------------------------------------------ the implied path on its grid, the WIRP (quantpath.py)
    console.log('implied path, WIRP');
    await api(page, 'ayşe yilmaz', 'POST', '/api/quant/recompute', {});          // (a fit with the recorded month of meeting pricing)
    await open(page, 'quant-path');
    await page.waitForSelector('#quant-path-meetings', { timeout: 30000 });
    await page.waitForFunction(() => document.querySelectorAll('#quant-path-meetings table.grid tr:not(.hd)').length >= 3, null, { timeout: 90000 });
    const pathApi = await api(page, 'ayşe yilmaz', 'GET', '/api/quant/path');
    const pb = ((pathApi.json || {}).path || {}).banks || {};
    const pt = pb.try || {};
    check('İma Patikası: every TCMB meeting a mix of its two 50 bp outcomes, consecutive pairs with their discrete paths, kinks, calibration',
      pathApi.status === 200 && pt.ok && pt.grid === 50 && pt.rows.length >= 3 && pt.rows.every((r) => Math.abs(r.p_lo * r.lo + r.p_hi * r.hi - r.step) < 1e-6)
      && pt.pairs.length >= 1 && pt.pairs[0].paths.every((q) => q.p_min <= q.p_max) && pt.kinks.length >= 1 && pt.calibration.n >= 0
      && await page.locator('#quant-path-pairs table.grid').count() === 1 && await page.locator('#quant-path-kinks table.grid').count() === 1
      && await page.locator('#quant-path-calib table.grid').count() === 1, { rows: (pt.rows || []).length, why: pt.why });
    check('... the replay note: live quotes drive it', await page.locator('#quant-path-mode:not(.hidden)').count() === 1);
    await page.click('#quant-path-bank button[data-v="usd"]');
    await page.waitForFunction(() => /Fed · FOMC/.test((document.querySelector('#quant-path-meetings h2') || {}).textContent || ''), null, { timeout: 10000 });
    const usdRows = await page.locator('#quant-path-meetings table.grid tr:not(.hd)').count();
    check('... the Fed from the USD workbook\'s FOMC table: ten meetings on a 25 bp grid', usdRows === 10 && pb.usd && pb.usd.ok && pb.usd.grid === 25, { usdRows });
    await shot(page, 'quant-path');
    await page.click('#quant-path-bank button[data-v="try"]');                 // (the choice is kept in the browser: TCMB again)
    await open(page, 'quant-wirp');
    await page.waitForSelector('#quant-wirp-matrix table.grid', { timeout: 30000 });
    const wirpApi = await api(page, 'ayşe yilmaz', 'GET', '/api/quant/wirp');
    const wb = ((wirpApi.json || {}).wirp || {}).banks || {};
    const wt = wb.try || {};
    check('TCMB WIRP: ease / hold / hike per meeting, the matrix\'s expected path is the implied one, the policy rate from Masa (Q155) and its spread to TLREF',
      wirpApi.status === 200 && wt.ok && wt.check < 1e-6 && wt.policy && wt.policy.rate === 36 && typeof wt.policy.spread === 'number'
      && wt.rows.every((r) => Math.abs(r.ease + r.hold + r.hike - 1) < 1e-9)
      && await page.locator('#quant-wirp-table table.grid tr:not(.hd)').count() === wt.rows.length
      && await page.locator('#quant-wirp-bars svg.chart').count() === 1, { check: wt.check, policy: wt.policy });
    await page.locator('#quant-wirp-table table.grid tr:not(.hd)').nth(1).locator('td').first().click();
    const secondMeeting = (wt.rows[1] || {}).meeting || '';
    await page.waitForFunction((d) => ((document.querySelector('#quant-wirp-bars h2') || {}).textContent || '').startsWith(d),
      secondMeeting.split('-').reverse().join('.'), { timeout: 10000 });
    check('... a click on a meeting draws its rate buckets', true);
    await page.click('#quant-wirp-bank button[data-v="usd"]');
    await page.waitForFunction(() => /Fed/.test((document.querySelector('#quant-wirp-table h2') || {}).textContent || ''), null, { timeout: 10000 });
    check('... the Fed beside it: target ranges in bp from the FDTR upper bound', wb.usd && wb.usd.ok && wb.usd.policy.rate === 4
      && wb.usd.buckets.every((b) => /^\d+–\d+$/.test(b.label)) && await page.locator('#quant-wirp-matrix table.grid tr:not(.hd)').count() === wb.usd.rows.length);
    await shot(page, 'quant-wirp');
    await page.click('#quant-wirp-bank button[data-v="try"]');

    // ------------------------------------------------------------------ lead-lag (quantlead.py)
    console.log('lead-lag');
    await open(page, 'quant-lead');
    await page.waitForSelector('#quant-lead-pairs table.grid', { timeout: 30000 });
    const leadApi = await api(page, 'ayşe yilmaz', 'GET', '/api/quant/lead');
    const lr = ((leadApi.json || {}).lead || {}).rows || [];
    check('Öncü-Takipçi: every candidate pair listed (the recorded month is short: each says why), no intraday bars yet',
      leadApi.status === 200 && lr.length >= 4 && lr.every((r) => r.leader || r.why)
      && await page.locator('#quant-lead-pairs table.grid tr:not(.hd)').count() === lr.length
      && /gün içi barlar yok/.test(await page.textContent('#quant-lead-intraday')), { rows: lr.length });
    await shot(page, 'quant-lead');
    // the DİBS RV list's bonds are candidates too, named by maturity (VİOP's daily pairs need the VİOP history sheet's
    // closes, which replay does not have: none here); the group filter narrows the tables and is remembered
    const nDibs = lr.filter((r) => r.group === 'DİBS ↔ OIS').length;
    const nViop = lr.filter((r) => String(r.group).startsWith('VİOP')).length;
    await page.click('#quant-lead-group button[data-v="DİBS"]');
    await page.waitForFunction((n) => document.querySelectorAll('#quant-lead-pairs table.grid tr:not(.hd)').length === n, nDibs, { timeout: 10000 }).catch(() => null);
    const dibsShown = await page.locator('#quant-lead-pairs table.grid tr:not(.hd)').count();
    const dibsText = await page.textContent('#quant-lead-pairs');
    await page.click('#quant-lead-group button[data-v="VİOP"]');
    await page.waitForFunction((n) => document.querySelectorAll('#quant-lead-pairs table.grid tr:not(.hd)').length === n, nViop, { timeout: 10000 }).catch(() => null);
    const viopShown = await page.locator('#quant-lead-pairs table.grid tr:not(.hd)').count();
    const remembered = await page.evaluate(() => { try { return localStorage.getItem('tto.quant.lead.group'); } catch (e) { return null; } });
    await page.click('#quant-lead-group button[data-v=""]');
    await page.waitForFunction((n) => document.querySelectorAll('#quant-lead-pairs table.grid tr:not(.hd)').length === n, lr.length, { timeout: 10000 }).catch(() => null);
    const dibsLabels = lr.filter((r) => r.group === 'DİBS ↔ OIS').map((r) => r.x_label);
    check('Öncü-Takipçi: the DİBS RV list\'s bonds among the pairs, each by its maturity; the group filter shows a group\'s rows (VİOP: none in replay), "Tümü" all again',
      nDibs >= 1 && dibsShown === nDibs && /DİBS ↔ OIS/.test(dibsText) && viopShown === nViop && /VİOP/.test(remembered || '')
      && dibsLabels.every((t) => /\d\d\.\d\d\.\d\d/.test(t)) && new Set(dibsLabels).size === dibsLabels.length
      && await page.locator('#quant-lead-pairs table.grid tr:not(.hd)').count() === lr.length, { nDibs, nViop, dibsShown, viopShown, remembered });

    // ------------------------------------------------------------------ VİOP (quantviop.py)
    console.log('VİOP');
    await open(page, 'quant-viop');
    await page.waitForSelector('#quant-viop-contracts table.grid', { timeout: 30000 });
    const viopApi = await api(page, 'ayşe yilmaz', 'GET', '/api/quant/viop');
    const vq = (viopApi.json || {}).viop || {};
    const vrows = (vq.live || {}).rows || [];
    const vShown = await page.locator('#quant-viop-contracts table.grid tr:not(.hd)').count();
    const vText = await page.textContent('#quant-viop-contracts');
    const vLevels = await page.textContent('#quant-viop-levels');
    // the VİOP sheet's twelve contracts (L1:W1) with the TRY rates their live bid and ask imply (the sheet's rows 13 and
    // 25); the recorded data has no Bloomberg history of them: no fair value, no order levels - the page says why
    check('VİOP: the VİOP sheet\'s twelve contracts with the implied rates of their live ask / bid; replay has no history - no fair value, no levels, and the page says so',
      viopApi.status === 200 && vrows.length === 12 && vShown === vrows.length && vrows[0].ticker === 'A1X6 Curncy' && vrows[11].ticker === 'A1V7 Curncy'
      && vrows.every((r) => typeof r.bid === 'number' && typeof r.ask === 'number' && r.bid < r.ask && r.fair == null && !r.today && !r.week)
      && /Kas26/.test(vText) && /Eki27/.test(vText) && /33,83/.test(vText) && /33,58/.test(vText) && /geçmiş yok/.test(vText)
      && /Seviye yok: oynaklık için geçmiş yok/.test(vLevels) && await page.locator('#quant-viop-mode:not(.hidden)').count() === 1,
    { rows: vrows.length, shown: vShown, why: vq.why || (vq.live || {}).why, first: vrows[0] });
    // the contract selector: the levels panel is the chosen contract's (its ask / bid implied rates in the title), the
    // choice kept in the browser
    const levelsTitle = () => page.evaluate(() => (document.querySelector('#quant-viop-levels h2') || {}).textContent || '');
    const firstTitle = await levelsTitle();
    await page.click('#quant-viop-contract button[data-v="A1Z6 Curncy"]');
    await page.waitForFunction(() => /Ara26/.test((document.querySelector('#quant-viop-levels h2') || {}).textContent || ''), null, { timeout: 10000 }).catch(() => null);
    const secondTitle = await levelsTitle();
    const keptContract = await page.evaluate(() => { try { return localStorage.getItem('tto.quant.viop.contract'); } catch (e) { return null; } });
    check('... the contract selector switches the levels panel to the contract chosen and is remembered',
      /^Emir seviyeleri · Kas26 · alış 33,83 \/ satış 33,58/.test(firstTitle) && /^Emir seviyeleri · Ara26 · alış 34,09 \/ satış 33,98/.test(secondTitle)
      && keptContract === 'A1Z6 Curncy' && await page.locator('#quant-viop-contract button.on[data-v="A1Z6 Curncy"]').count() === 1,
    { firstTitle, secondTitle, keptContract });
    await shot(page, 'quant-viop');
    await page.click('#quant-viop-contract button[data-v="A1X6 Curncy"]');          // (the choice is kept in the browser: the front again)

    // ------------------------------------------------------------------ launchpad, side drawer, pop-out, fast switching
    console.log('launchpad and navigation');
    const boxKeys = () => page.evaluate(() => [...document.querySelectorAll('#lp-grid .lp-item')].map((x) => x.dataset.key + ':' + x.dataset.w));
    const layoutOf = async (user) => (await api(page, user, 'GET', '/api/layout')).json;
    // (a change is on screen at once and saved right after: the server's copy is waited for)
    const savedLayout = async (pred) => {
      for (let i = 0; i < 60; i++) {
        const l = await layoutOf('ayşe yilmaz');
        if (pred(l)) return l;
        await page.waitForTimeout(250);
      }
      return layoutOf('ayşe yilmaz');
    };
    // a table from its page onto a new launchpad: "+ Launchpad" in its header
    await open(page, 'forward');
    await tab(page, 'calc');
    await page.hover('#content .panel[data-panel="B1"]');
    await page.click('#content .panel[data-panel="B1"] .tools button[data-action="launchpad"]');
    await page.click('.menu >> text=+ Yeni launchpad…');
    await page.fill('.modal input', 'Sabah');
    await page.click('.modal .btn.primary');
    await page.waitForFunction(() => /"Sabah" launchpad/.test(document.getElementById('toasts').textContent), null, { timeout: 15000 });
    await open(page, 'launchpad');
    await page.waitForSelector('#lp-grid .lp-item[data-key="forward/B1"] table.grid', { timeout: 30000 });
    const lpTabs = await page.evaluate(() => [...document.querySelectorAll('#lp-tabs .lp-tab')].map((b) => b.dataset.name + (b.classList.contains('on') ? '!' : '')));
    check('Launchpad: first in the menu; a table added from its page ("+ Launchpad" → a new one) is on it, live',
      lpTabs.join(',') === 'Sabah!' && await page.evaluate(() => document.querySelector('#nav .nav-item').dataset.page) === 'launchpad'
      && /^Launchpad · Sabah/.test(await page.textContent('#page-title')), lpTabs);
    // another one from a Ctrl+K result
    await page.keyboard.press('Control+k');
    await page.keyboard.type('interest');
    await page.waitForSelector('.findlist .hit .act[data-act="launchpad"]');
    await page.hover('.findlist .hit >> nth=0');
    await page.click('.findlist .hit >> nth=0 >> .act[data-act="launchpad"]');
    await page.click('.menu >> text=Sabah');
    await page.waitForFunction(() => document.querySelectorAll('#lp-grid .lp-item table.grid').length === 2, null, { timeout: 30000 });
    const twoKeys = await boxKeys();
    check('... and one from a Ctrl+K result ("Launchpad\'e ekle" beside the hit)', twoKeys.length === 2 && /^forward\/B\d+:6$/.test(twoKeys[1]), twoKeys);
    // its width (the item's menu) and its place (dragged by its handle before the first): kept after a reload
    await page.click('#lp-grid .lp-item >> nth=0 >> button[data-action="item-menu"]');
    await page.click('.menu >> text=Tam');
    await page.waitForFunction(() => document.querySelector('#lp-grid .lp-item').dataset.w === '12');
    await page.locator('#lp-grid .lp-item >> nth=1 >> .lp-drag').dragTo(page.locator('#lp-grid .lp-item >> nth=0'), { targetPosition: { x: 14, y: 14 } });
    await page.waitForFunction(() => document.querySelectorAll('#lp-grid .lp-item')[1].dataset.key === 'forward/B1', null, { timeout: 10000 });
    await savedLayout((l) => l.launchpads[0].items[1].panel === 'B1' && l.launchpads[0].items[1].w === 12);
    await page.reload();
    await page.waitForFunction(() => window.tto && window.tto.state.pageId === 'launchpad' && window.tto.state.page && window.tto.state.page.ready, null, { timeout: 90000 });
    await page.waitForFunction(() => document.querySelectorAll('#lp-grid .lp-item table.grid').length === 2, null, { timeout: 30000 });
    const kept = await boxKeys();
    const lay1 = await layoutOf('ayşe yilmaz');
    check('the order (drag and drop) and the width (¼ ⅓ ½ ⅔ tam) are kept after a reload - with the account, on the server',
      kept[0] === twoKeys[1] && kept[1] === 'forward/B1:12' && lay1.launchpads[0].items.map((x) => x.panel).join(',') === twoKeys[1].split(/[/:]/)[1] + ',B1', { kept, lay1 });
    await shot(page, '40-launchpad');
    // a value typed on the launchpad is the source page's value (the same cell of the same book)
    await typeInto(page, 'Forward!D2', '16.12.2026');
    await waitCell(page, 'Forward!D2', "t.trim() === '16.12.2026'");
    await open(page, 'forward');
    await waitCell(page, 'Forward!D2', "t.trim() === '16.12.2026'");
    check('a value typed on the launchpad shows on its page', (await cellText(page, 'Forward!D2')).trim() === '16.12.2026');
    await api(page, 'ayşe yilmaz', 'POST', '/api/reset', { book: 'tto', refs: ['Forward!D2'] });
    // a part of a table: the columns picked (the server cuts them out)
    await open(page, 'launchpad');
    await page.click('#lp-grid .lp-item[data-key="forward/B1"] button[data-action="item-menu"]');
    await page.click('.menu >> text=Satırlar ve sütunlar…');
    await page.waitForSelector('.lp-picker .lp-pick input');
    await page.locator('.lp-picker .lp-pick-side >> nth=1 >> .lp-pick input >> nth=6').uncheck();
    await page.locator('.lp-picker .lp-pick-side >> nth=1 >> .lp-pick input >> nth=7').uncheck();
    await page.click('#lp-pick-save');
    await page.waitForFunction(() => { const b = document.querySelector('#lp-grid .lp-item[data-key="forward/B1"] table.grid'); return b && b.__grid.data.c.length === 6; }, null, { timeout: 20000 });
    const partOf = (l) => (l.launchpads[0].items.find((x) => x.panel === 'B1') || {}).cols || [];
    const part = partOf(await savedLayout((l) => partOf(l).length === 6));
    check('a part of a table: the columns picked, kept with the item and cut out on the server', part.join(',') === 'C,D,F,G,I,J', part);
    // the column order (per user, per table): on DİBS RV's table, then the same order wherever the table is drawn
    await open(page, 'dibs');
    await tab(page, '*');
    const rvSel = '#content .panel[data-panel="B3"]';
    const rvCols = () => page.evaluate((s) => document.querySelector(s + ' table.grid').__grid.data.c.slice(0, 4).join(','), rvSel);
    await page.hover(rvSel);
    await page.click(rvSel + ' .tools .colsbtn');
    await page.click('.menu >> text=Sütun sırası…');
    await page.click('#colorder-list .co >> nth=0 >> button[data-act="down"]');
    await page.click('#colorder-list .co >> nth=1 >> button[data-act="down"]');
    await page.click('#colorder-save');
    await page.waitForFunction((s) => document.querySelector(s + ' table.grid').__grid.data.c.slice(0, 3).join(',') === 'B,C,A', rvSel, { timeout: 10000 });
    await page.reload();
    await page.waitForFunction(() => window.tto && window.tto.state.pageId === 'dibs' && window.tto.state.page && window.tto.state.page.ready, null, { timeout: 90000 });
    await page.waitForSelector(rvSel + ' table.grid');
    const colOrder = ((await api(page, 'ayşe yilmaz', 'GET', '/api/columns')).json.order || {})['v/dibs/B3'] || [];
    check('a column order of one\'s own ("Sütun sırası…"): kept after a reload, with the account; a cell keeps its reference',
      await rvCols() === 'B,C,A,D' && colOrder.slice(0, 3).join(',') === 'B,C,A'
      && await page.evaluate(() => { const td = window.tto.findCell('DİBS RV!A6'); return !!td && td.__j === 2; }), { cols: await rvCols(), colOrder });
    // the same table on the launchpad (a part of it): the user's order over its columns
    await api(page, 'ayşe yilmaz', 'POST', '/api/layout', { launchpads: (await layoutOf('ayşe yilmaz')).launchpads.map((lp) => Object.assign({}, lp,
      { items: lp.items.concat([{ view: 'dibs', panel: 'B3', w: 12, h: 360, cols: ['A', 'C', 'D', 'E'] }]) })) });
    await open(page, 'launchpad');
    await page.waitForSelector('#lp-grid .lp-item[data-key="dibs/B3"] table.grid', { timeout: 30000 });
    const boxCols = await page.evaluate(() => document.querySelector('#lp-grid .lp-item[data-key="dibs/B3"] table.grid').__grid.data.c.join(','));
    check('... and on the launchpad (its part A C D E as C A D E), a fixed height scrolling inside', boxCols === 'C,A,D,E'
      && await page.evaluate(() => document.querySelector('#lp-grid .lp-item[data-key="dibs/B3"] .body').getBoundingClientRect().height <= 362), boxCols);
    await open(page, 'dibs');
    await page.hover(rvSel);
    await page.click(rvSel + ' .tools .colsbtn');
    await page.click('.menu >> text=Excel sırasına dön');
    await page.waitForFunction((s) => document.querySelector(s + ' table.grid').__grid.data.c.slice(0, 3).join(',') === 'A,B,C', rvSel, { timeout: 10000 });
    // a favourite page in the top bar
    await open(page, 'forward');
    await page.click('#btn-fav');
    await page.waitForSelector('#favs a.fav[data-page="forward"]');
    await open(page, 'dibs');
    await page.click('#favs a.fav[data-page="forward"]');
    await page.waitForFunction(() => window.tto.state.pageId === 'forward');
    check('★ a favourite page in the top bar (kept with the account), one click away',
      JSON.stringify((await layoutOf('ayşe yilmaz')).favs) === '["forward"]' && await page.textContent('#btn-fav') === '★');
    await page.click('#btn-fav');
    await page.waitForFunction(() => !document.querySelector('#favs a.fav'));
    // the landing page ("Açılış sayfası…" in the user menu): the dashboard opened without an address goes there
    await page.click('#btn-user');
    await page.click('.menu >> text=Açılış sayfası…');
    await page.selectOption('#landing-select', 'launchpad/Sabah');
    await page.click('#landing-save');
    await page.waitForFunction(() => /Açılış sayfanız/.test(document.getElementById('toasts').textContent), null, { timeout: 10000 });
    await page.goto(BASE + '/');
    await page.waitForFunction(() => window.tto && window.tto.state.pageId === 'launchpad' && window.tto.state.page && window.tto.state.page.ready, null, { timeout: 90000 });
    check('the landing page opens when the dashboard is opened without an address (one of the user\'s launchpads)',
      decodeURIComponent(await page.evaluate(() => window.location.hash)) === '#/launchpad/Sabah' && (await layoutOf('ayşe yilmaz')).landing === 'launchpad/Sabah');
    await api(page, 'ayşe yilmaz', 'POST', '/api/layout', { landing: '' });
    // the side drawer: a table pinned stays on every page (Alt+Y closes / opens it)
    await open(page, 'forward');
    await tab(page, 'calc');
    await page.hover('#content .panel[data-panel="B7"]');
    await page.click('#content .panel[data-panel="B7"] .tools button[data-action="launchpad"]');
    await page.click('.menu >> text=Yan panele sabitle');
    await page.waitForSelector('#drawer:not(.hidden) .lp-item[data-key="forward/B7"] table.grid', { timeout: 30000 });
    await open(page, 'dibs');
    const inDrawer = await page.locator('#drawer .lp-item[data-key="forward/B7"] table.grid').count();
    await page.keyboard.press('Alt+y');
    await page.waitForSelector('#drawer.hidden', { state: 'attached' });
    await page.keyboard.press('Alt+y');
    await page.waitForSelector('#drawer:not(.hidden) .lp-item[data-key="forward/B7"]');
    check('the side drawer: a table pinned from its page stays beside every page; Alt+Y closes and opens it',
      inDrawer === 1 && (await layoutOf('ayşe yilmaz')).drawer.length === 1 && await page.evaluate(() => document.getElementById('app').classList.contains('drawer-open')));
    await shot(page, '41-drawer');
    await page.click('#drawer .lp-item[data-key="forward/B7"] button[data-action="unpin"]');
    await page.waitForFunction(() => !document.querySelector('#drawer .lp-item'));
    await page.click('#dr-close');
    // back / forward: the page comes back with its tab and its scroll
    await open(page, 'forward');
    await tab(page, '*');
    await page.evaluate(() => { document.getElementById('content').scrollTop = 400; window.__keptPage = window.tto.state.page; });
    const top0 = await page.evaluate(() => document.getElementById('content').scrollTop);
    await open(page, 'dibs');
    await page.click('#page-title');
    await page.keyboard.press('Alt+ArrowLeft');
    await page.waitForFunction(() => window.tto.state.pageId === 'forward' && !window.tto.state.refreshing, null, { timeout: 30000 });
    const back = await page.evaluate(() => ({ same: window.tto.state.page === window.__keptPage, tab: document.querySelector('.viewtabs button.on').dataset.tab,
      top: document.getElementById('content').scrollTop }));
    await page.keyboard.press('Alt+ArrowRight');
    await page.waitForFunction(() => window.tto.state.pageId === 'dibs', null, { timeout: 30000 });
    check('Alt+← / Alt+→: back to the page kept as it was left - its tab, its scroll - and forward again',
      back.same && back.tab === '*' && top0 > 0 && Math.abs(back.top - top0) < 2 && (await page.evaluate(() => window.tto.kept().length)) <= 4, { back, top0 });
    // a window of its own: a table (⧉) and a launchpad, live, without the menu or alarms
    await open(page, 'forward');
    await tab(page, 'calc');
    await page.hover('#content .panel[data-panel="B1"]');
    const [pop] = await Promise.all([ctxA.waitForEvent('page'), page.click('#content .panel[data-panel="B1"] .tools button[data-action="popout"]')]);
    pop.on('pageerror', (e) => errors.push('pageerror(pop): ' + e.message));
    const popAsked = [];
    pop.on('request', (r) => { if (r.url().includes('/api/')) popAsked.push(r.url().replace(BASE, '')); });
    await pop.waitForSelector('.lp-item[data-key="forward/B1"] table.grid', { timeout: 60000 });
    await api(page, 'ayşe yilmaz', 'POST', '/api/inputs', { book: 'tto', items: [{ ref: 'Forward!D2', value: '18.12.2026' }] });
    await pop.waitForFunction(() => { const t = window.tto.findCell('Forward!D2'); return t && t.textContent.trim() === '18.12.2026'; }, null, { timeout: 30000 });
    check('a pop-out window (⧉) shows the table without the menu and keeps up live - one request per refresh, no alarm checks',
      await pop.evaluate(() => window.tto.pop && getComputedStyle(document.getElementById('side')).display === 'none' && !document.querySelector('#kpis .kpi'))
      && popAsked.some((u) => u.startsWith('/api/panels')) && !popAsked.some((u) => /\/api\/(alarms|view|header)/.test(u)), popAsked.slice(0, 10));
    await shot(pop, '42-popout');
    await api(page, 'ayşe yilmaz', 'POST', '/api/reset', { book: 'tto', refs: ['Forward!D2'] });
    await pop.close();
    await open(page, 'launchpad');
    const [popLp] = await Promise.all([ctxA.waitForEvent('page'), page.click('#lp-pop')]);
    popLp.on('pageerror', (e) => errors.push('pageerror(pop lp): ' + e.message));
    await popLp.waitForFunction(() => document.querySelectorAll('#lp-grid .lp-item table.grid').length === 3, null, { timeout: 60000 });
    check('... and a whole launchpad in a window of its own', decodeURIComponent(await popLp.evaluate(() => window.location.hash)) === '#/pop/launchpad/Sabah'
      && await popLp.locator('#lp-tabs').count() === 0);
    await popLp.close();
    // a table the user may not see (an administrators' page), or one that is gone: said in its box, the page goes on
    const ctxE = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
    const pageE = await ctxE.newPage();
    pageE.on('pageerror', (e) => errors.push('pageerror(E): ' + e.message));
    await login(pageE, 'Zeynep');
    await pageE.request.fetch(BASE + '/api/layout', { method: 'POST', headers: { 'Content-Type': 'application/json' },
      data: JSON.stringify({ launchpads: [{ name: 'Benim', items: [{ view: 'motor', panel: 'B1' }, { view: 'forward', panel: 'YOK' }, { view: 'forward', panel: 'B1' }] }] }) });
    await pageE.evaluate(() => { window.location.hash = '#/launchpad'; });
    await pageE.waitForSelector('#lp-grid .lp-item[data-key="forward/B1"] table.grid', { timeout: 60000 });
    await pageE.waitForFunction(() => document.querySelectorAll('#lp-grid .lp-item.missing .lp-missing b').length === 2, null, { timeout: 30000 });
    const missing = await pageE.evaluate(() => [...document.querySelectorAll('#lp-grid .lp-item.missing .lp-missing b')].map((b) => b.textContent));
    check('a table that is not there any more, or not the user\'s to see, says so in its box ("erişim yok" / "artık yok"); the rest works',
      missing.join('|') === 'Erişim yok|Bu tablo artık yok', missing);
    await ctxE.close();

    // ------------------------------------------------------------------ a personal calc sheet
    console.log('personal calc sheet');
    const calcCell = (a, root = '#lp-grid') => root + ' .calc-box td[data-a="' + a + '"]';
    const calcText = (a, root = '#lp-grid') => page.textContent(calcCell(a, root));
    const waitCalc = (a, t, root = '#lp-grid') => page.waitForFunction(([s, x]) => { const td = document.querySelector(s); return !!td && td.textContent === x; },
      [calcCell(a, root), t], { timeout: 30000 });
    const typeCalc = async (a, text, root = '#lp-grid') => { await page.click(calcCell(a, root)); await page.keyboard.type(text); await page.keyboard.press('Enter'); };
    await open(page, 'launchpad');
    await page.click('#lp-calc');
    await page.waitForSelector(calcCell('B1'), { timeout: 30000 });
    const calcSheet = await page.evaluate(() => document.querySelector('#lp-grid .calc-box').dataset.sheet);
    await typeCalc('B1', '=MASA!I60+25');
    await waitCalc('B1', '-125');
    await page.click(calcCell('B1'));
    const calcFx = await page.inputValue('#lp-grid .calc-box .calc-fx');
    check('a calc sheet of one\'s own on a launchpad (+ Hesap tablosu): =MASA!I60+25 shows -125 (the desk\'s spread -150 + 25), the formula bar the formula',
      calcFx === '=MASA!I60+25' && (await savedLayout((l) => l.launchpads[0].items.some((x) => x.type === 'calc' && x.sheet === calcSheet)))
        .launchpads[0].items.some((x) => x.type === 'calc'), calcFx);
    await typeCalc('A1', '10');
    await page.keyboard.type('=A1*2');
    await page.keyboard.press('Enter');
    await page.keyboard.type('=SUM(A1:A2)+B1');
    await page.keyboard.press('Enter');
    await waitCalc('A3', '-95');
    check('... formulas over its own cells: 10, =A1*2, =SUM(A1:A2)+B1 (Enter moves down, as in Excel)',
      [await calcText('A1'), await calcText('A2'), await calcText('A3')].join('|') === '10|20|-95');
    await page.evaluate(() => navigator.clipboard.writeText('1,5\t2\r\n3\t4\r\n'));
    await page.click(calcCell('C3'));
    await page.keyboard.press('Control+v');
    await waitCalc('D4', '4');
    const pasted = [await calcText('C3'), await calcText('D3'), await calcText('C4'), await calcText('D4')].join('|');
    check('... a 2 × 2 block pasted from Excel lands cell by cell', pasted === '1,5|2|3|4', pasted);
    await typeCalc('A5', '=BDP("USDTRY Curncy";"PX_LAST")');
    await page.waitForFunction(() => /BDP Bloomberg'den veri ister/.test(document.getElementById('toasts').textContent), null, { timeout: 15000 });
    const refusedText = await page.inputValue('#lp-grid .calc-box .calc-edit');
    await page.keyboard.press('Escape');
    const calcNow = async () => (await api(page, 'ayşe yilmaz', 'POST', '/api/calc/eval', { items: [{ key: 'k', sheet: calcSheet }] })).json.sheets.k;
    const calcKept = await calcNow();
    check('... a Bloomberg function is refused with the reason (the daily data limit) and nothing is kept; the cell is typed into again',
      refusedText === '=BDP("USDTRY Curncy";"PX_LAST")' && !calcKept.cells.A5 && (await calcText('A5')) === '', { refusedText, a5: calcKept.cells.A5 });
    // the same sheet in the side drawer; the spread changed on Masa's own page: the sheet follows, live
    await page.hover('#lp-grid .calc-box');
    await page.click('#lp-grid .calc-box button[data-action="item-menu"]');
    await page.click('.menu >> text=Yan panele sabitle');
    await waitCalc('B1', '-125', '#drawer');
    await open(page, 'masa');
    await typeInto(page, 'MASA!I60', '-100');
    await waitCalc('B1', '-75', '#drawer');
    await waitCalc('A3', '-45', '#drawer');
    check('... pinned to the side drawer (the same sheet): Masa\'s spread typed on its page (-100) - the sheet follows at once (-75)',
      (await calcText('B1', '#drawer')) === '-75' && (await layoutOf('ayşe yilmaz')).drawer.some((x) => x.type === 'calc' && x.sheet === calcSheet));
    // while a formula is typed, Ctrl+click on a cell of the page's table puts its reference in
    await page.click(calcCell('C1', '#drawer'));
    await page.keyboard.type('=');
    await (await cellHandle(page, 'MASA!I60')).click({ modifiers: ['Control'] });
    const pointed = await page.inputValue('#drawer .calc-box .calc-edit');
    await page.keyboard.type('*2');
    await page.keyboard.press('Enter');
    await waitCalc('C1', '-200', '#drawer');
    check('... Ctrl+click on the page\'s cell while typing a formula puts its reference in (=MASA!I60*2 → -200)', pointed === '=MASA!I60', pointed);
    // ... a plain click too where a reference may go (after = or an operator: Excel's pointing); in a finished formula a
    // plain click ends the typing instead
    await page.click(calcCell('E1', '#drawer'));
    await page.keyboard.type('=');
    await (await cellHandle(page, 'MASA!I60')).click();
    await page.keyboard.type('+');
    await (await cellHandle(page, 'MASA!I60')).click();
    const pointedPlain = await page.inputValue('#drawer .calc-box .calc-edit');
    await page.keyboard.press('Enter');
    await waitCalc('E1', '-200', '#drawer');
    await page.click(calcCell('F1', '#drawer'));
    await page.keyboard.type('=A1');
    await (await cellHandle(page, 'MASA!I60')).click();
    await waitCalc('F1', '10', '#drawer');
    check('... a plain click on the page\'s cell after = or an operator puts it in as well (=MASA!I60+MASA!I60 → -200); after a finished '
      + 'formula it ends the typing (=A1 → 10)', pointedPlain === '=MASA!I60+MASA!I60' && !(await page.$('#drawer .calc-box .calc-edit')), pointedPlain);
    await api(page, 'ayşe yilmaz', 'POST', '/api/reset', { book: 'tto', refs: ['MASA!I60'] });
    await waitCalc('C1', '-300', '#drawer');
    // a reload keeps everything (kept with the account, on the server)
    await page.reload();
    await page.waitForFunction(() => window.tto && window.tto.state.pageId === 'masa' && window.tto.state.page && window.tto.state.page.ready, null, { timeout: 90000 });
    await waitCalc('C1', '-300', '#drawer');
    await open(page, 'launchpad');
    await waitCalc('B1', '-125');
    const afterReload = [await calcText('A1'), await calcText('A3'), await calcText('B1'), await calcText('C3'), await calcText('D4'), await calcText('C1')].join('|');
    check('... a reload keeps the sheet - on the launchpad and in the drawer', afterReload === '10|-95|-125|1,5|4|-300', afterReload);
    await shot(page, '43-calc');
    await page.click('#drawer .calc-box button[data-action="unpin"]');
    await page.waitForFunction(() => !document.querySelector('#drawer .calc-box'));
    await page.click('#dr-close');
    // ------------------------------------------------------------------ the boxes of the dashboard's own pages
    console.log('page boxes');
    const KINDS = ['quant-signals', 'viop-levels', 'viop-contracts', 'broker-board', 'watch-list', 'wirp', 'fx-summary'];
    await api(page, 'ayşe yilmaz', 'POST', '/api/layout', { launchpads: (await layoutOf('ayşe yilmaz')).launchpads.concat([{ name: 'Kutular',
      items: KINDS.map((type) => ({ type, w: type === 'quant-signals' || type === 'broker-board' ? 12 : 6 })) }]) });
    // (made through the API: the page reads its layout again - as it does when another window changes it)
    await page.evaluate(async () => { await (await import('/static/js/layout.js')).loadLayout(); });
    await page.evaluate(() => { window.location.hash = '#/launchpad/Kutular'; });
    await page.waitForFunction(() => window.tto.state.pageId === 'launchpad' && window.tto.state.page && window.tto.state.page.ready
      && window.tto.state.page.name === 'Kutular', null, { timeout: 60000 });
    await page.waitForFunction((n) => { const b = [...document.querySelectorAll('#lp-grid .lp-item')]; return b.length === n && b.every((x) => x.dataset.version); },
      KINDS.length, { timeout: 90000 });
    const boxesNow = () => page.evaluate(() => Object.fromEntries([...document.querySelectorAll('#lp-grid .lp-item')].map((el) => [el.dataset.type, {
      v: Number(el.dataset.version), title: el.querySelector('h2').textContent, src: el.querySelector('.lp-src').textContent, text: el.querySelector('.body').textContent,
      rows: el.querySelectorAll('.body table.grid tr:not(.hd)').length, plain: el.querySelectorAll('.body table.plain tr').length }])));
    const bx = await boxesNow();
    const boardNow = (await api(page, 'ayşe yilmaz', 'GET', '/api/broker?part=board')).json;
    const itemsNow = (await api(page, 'ayşe yilmaz', 'GET', '/api/watch?part=items')).json;
    const wirpNow = (await api(page, 'ayşe yilmaz', 'GET', '/api/quant/box?of=wirp')).json;
    check('page boxes: the seven kinds on a launchpad, each drawn from a light part of its page - VİOP\'s twelve contracts and the front one\'s levels, '
      + 'the board\'s instruments, the watch list, TCMB\'s meetings, the live signals, the pair summary',
      bx['viop-contracts'].rows === 12 && /^Emir seviyeleri · Kas26 · alış 33,83 \/ satış 33,58.* · ön vade$/.test(bx['viop-levels'].title)
      && /Seviye yok: oynaklık için geçmiş yok/.test(bx['viop-levels'].text) && bx['broker-board'].rows === boardNow.board.length && boardNow.board.length >= 5
      && !('rows' in boardNow) && bx['watch-list'].plain === itemsNow.items.length + 1 && itemsNow.items.length >= 1
      && bx.wirp.rows === wirpNow.banks.try.rows.length && wirpNow.banks.try.rows.length >= 3 && !('matrix' in wirpNow.banks.try.rows[0])
      && (bx['quant-signals'].rows > 0 || /eşiği geçen sinyal yok/.test(bx['quant-signals'].text))
      && (bx['fx-summary'].rows > 0 || /tarihçesi yok/.test(bx['fx-summary'].text))
      && bx.wirp.src === 'Quant › TCMB WIRP' && bx['watch-list'].src === 'İzleme · Alarmlar', bx);
    // each keeps up by itself: the quant ones when the results' version moves, the board when Broker Chat changes (its own
    // count in the live stream, not every generation), the watch list with the generation
    const boxAsks = [];
    const noteBoxAsk = (r) => { if (/\/api\/(quant\/box|broker\?|watch\?)/.test(r.url())) boxAsks.push(r.url().replace(BASE, '')); };
    page.on('request', noteBoxAsk);
    await api(page, 'ayşe yilmaz', 'POST', '/api/quant/recompute', {});
    await api(page, 'ayşe yilmaz', 'POST', '/api/broker', { text: '8y ois 32.10/32.40', source: 'ICAP' });
    const chatCount = (await api(page, 'ayşe yilmaz', 'GET', '/api/broker?part=board')).json.changes;
    const added = await api(page, 'ayşe yilmaz', 'POST', '/api/watch/add', { subject: { kind: 'expr', text: '[OIS 9Y] - [OIS 8Y]' }, label: 'Kutu 9s8s' });
    await page.evaluate(async () => { window.__boxStream = (await import('/static/js/pagebox.js')).stream; });
    await page.waitForFunction(([before, n]) => {
      const v = (t) => Number((document.querySelector('#lp-grid .lp-item[data-type="' + t + '"]') || { dataset: {} }).dataset.version);
      const text = (t) => (document.querySelector('#lp-grid .lp-item[data-type="' + t + '"] .body') || {}).textContent || '';
      return ['quant-signals', 'viop-levels', 'viop-contracts', 'wirp', 'fx-summary'].every((t) => v(t) > before[t].v)
        && /32,10/.test(text('broker-board')) && v('broker-board') === n && window.__boxStream.chat === n && /Kutu 9s8s/.test(text('watch-list'));
    }, [bx, chatCount], { timeout: 60000 }).catch(() => null);
    page.off('request', noteBoxAsk);
    const bx2 = await boxesNow();
    const streamChat = await page.evaluate(() => window.__boxStream.chat);
    check('... and refreshes: a new result (the version) brings the quant boxes again - VİOP\'s two in one request -, a chat line the board (Broker Chat\'s '
      + 'own count in the live stream), an item the watch list',
      ['quant-signals', 'viop-levels', 'viop-contracts', 'wirp', 'fx-summary'].every((t) => bx2[t].v > bx[t].v) && /32,10/.test(bx2['broker-board'].text)
      && typeof chatCount === 'number' && bx2['broker-board'].v === chatCount && streamChat === chatCount
      && /Kutu 9s8s/.test(bx2['watch-list'].text) && boxAsks.filter((u) => u.includes('of=viop')).length < boxAsks.filter((u) => u.includes('/api/quant/box')).length,
    { v: Object.fromEntries(Object.entries(bx2).map(([k, x]) => [k, [bx[k].v, x.v]])), asks: boxAsks.slice(0, 12) });
    if (added.json && added.json.item) await api(page, 'ayşe yilmaz', 'POST', '/api/watch/remove', { id: added.json.item.id });
    await shot(page, '43-page-boxes');
    // a click on a signal opens its card over the box - the Sinyaller page's card, without the page's element ids - and
    // "Sinyaller sayfasında aç" there (the recorded month has no signal: one is served to the box and to the card here)
    const FAKE = { id: 'pca:OIS:2Y', family: 'pca', family_label: 'PCA kalıntısı', asset: 'TRY OIS', expression: 'Receive 2Y OIS (kutu)', instrument: '2Y OIS',
      direction: -1, unit: 'bp', digits: 1, entry: 3, target: 0, stop: 3.5, pnl_unit: 'bp', exp_pnl: 5.08, rr: 6, reward: 3, risk: 0.5, carry_week: 1, z: 2.6,
      entry_z: 2, strength: 'Güçlü', gates: [], legs: [], agree: 0, conflict: 0, parts: { z: 2.6, regime: 1, hl: 1, carry: 1 }, composite: 2.6, hold: 13,
      horizon_unit: 'gün', bt: null, trade_tr: 'sabit faiz alınan (receive): 2Y OIS', plain: 'Kutudaki sinyalin düz anlatımı.',
      money: { ccy: 'TL', per_bp: 40000, dv01_usd: 1000, total: 203200, carry: 103200, move: 100000, target: 120000, stop: -20000,
        bp: { total: 5.08, carry: 2.58, move: 2.5, target: 3, stop: -0.5 } } };
    const serve = (body) => (route) => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(body) });
    const signalsBox = (u) => u.pathname === '/api/quant/box' && u.searchParams.get('of') === 'signals';
    const signalCard = (u) => u.pathname === '/api/quant/signal';
    await page.route(signalsBox, serve({ of: 'signals', ready: true, version: 9999, entry_z: 2, signals: [FAKE], families: [], assets: [] }));
    await page.route(signalCard, serve({ monitor: { name: '2Y OIS' }, signal: FAKE, history: { days: ['2026-11-02'], values: [1] }, settings: {}, rationale: null }));
    await page.evaluate(() => document.querySelector('#lp-grid .lp-item[data-type="quant-signals"]').__box.refreshOwn(true));
    await page.waitForSelector('#lp-grid .lp-item[data-type="quant-signals"] table.grid', { timeout: 15000 });
    await page.locator('#lp-grid .lp-item[data-type="quant-signals"] table.grid tr:not(.hd) td').nth(3).click();
    await page.waitForSelector('.modal.qcard .qsentence', { timeout: 15000 });
    const cardOver = await page.evaluate(() => ({ title: document.querySelector('.modal.qcard header h2').textContent, plain: document.querySelector('.modal.qcard .qsentence').textContent,
      ids: document.querySelectorAll('[id^="quant-sig-"]').length }));
    await page.click('.modal.qcard .mfoot button:not(.primary)');
    await page.waitForFunction(() => window.tto.state.pageId === 'quant' && window.tto.state.page && window.tto.state.page.ready, null, { timeout: 30000 });
    await page.waitForFunction(() => /Kutudaki sinyalin/.test((document.getElementById('quant-sig-plain') || {}).textContent || ''), null, { timeout: 15000 }).catch(() => null);
    const cardOnPage = await page.evaluate(() => (document.getElementById('quant-sig-plain') || {}).textContent || '');
    await page.unroute(signalsBox);
    await page.unroute(signalCard);
    check('a signal clicked in the box: its card over the box (the sentence; no element id of the page\'s card), "Sinyaller sayfasında aç" on the page',
      cardOver.title === 'Receive 2Y OIS (kutu)' && cardOver.plain === FAKE.plain && cardOver.ids === 0 && cardOnPage === FAKE.plain, { cardOver, cardOnPage });
    await page.evaluate(() => { window.location.hash = '#/launchpad/Kutular'; });
    await page.waitForFunction(() => window.tto.state.pageId === 'launchpad' && window.tto.state.page && window.tto.state.page.ready, null, { timeout: 60000 });
    // an option of a box (the levels' contract): kept with the item, the same answer drawn again
    await page.click('#lp-grid .lp-item[data-type="viop-levels"] button[data-action="item-menu"]');
    await page.click('.menu >> text=Ara26 · A1Z6 Curncy');
    await page.waitForFunction(() => /^Emir seviyeleri · Ara26/.test(document.querySelector('#lp-grid .lp-item[data-type="viop-levels"] h2').textContent), null, { timeout: 10000 });
    const levelsItem = (l) => (l.launchpads.find((x) => x.name === 'Kutular') || { items: [] }).items.find((x) => x.type === 'viop-levels') || {};
    check('a box\'s own option (VİOP levels: Ara26 instead of the front one) is kept with the item',
      levelsItem(await savedLayout((l) => levelsItem(l).contract === 'A1Z6 Curncy')).contract === 'A1Z6 Curncy');
    // on its own page a box's panel has a table's controls: "+ Launchpad" → the side drawer
    await open(page, 'quant-viop');
    await page.waitForSelector('#quant-viop-contracts table.grid', { timeout: 30000 });
    await page.hover('#quant-viop-contracts');
    await page.click('#quant-viop-contracts .tools button[data-action="launchpad"]');
    await page.click('.menu >> text=Yan panele sabitle');
    await page.waitForSelector('#drawer:not(.hidden) .lp-item[data-type="viop-contracts"] table.grid', { timeout: 30000 });
    const pinnedV = await page.evaluate(() => Number(document.querySelector('#drawer .lp-item[data-type="viop-contracts"]').dataset.version));
    const viopIds = await page.evaluate(() => [...document.querySelectorAll('[id^="quant-viop"]')].map((el) => el.id).filter((id, i, all) => all.indexOf(id) !== i));
    await api(page, 'ayşe yilmaz', 'POST', '/api/quant/recompute', {});
    await page.waitForFunction((v) => Number((document.querySelector('#drawer .lp-item[data-type="viop-contracts"]') || { dataset: {} }).dataset.version) > v,
      pinnedV, { timeout: 30000 }).catch(() => null);
    const drawerBox = (await layoutOf('ayşe yilmaz')).drawer.find((x) => x.type === 'viop-contracts');
    check('"+ Launchpad" on the page\'s own panel → "Yan panele sabitle": the box beside the page, live, and no element id twice',
      !!drawerBox && drawerBox.w === 12 && viopIds.length === 0
      && await page.evaluate((v) => Number(document.querySelector('#drawer .lp-item[data-type="viop-contracts"]').dataset.version) > v, pinnedV), { drawerBox, viopIds });
    await page.click('#drawer .lp-item[data-type="viop-contracts"] button[data-action="unpin"]');
    await page.waitForFunction(() => !document.querySelector('#drawer .lp-item'));
    await page.click('#dr-close');
    // ... and ⧉: the Sinyaller page's list in a window of its own, keeping up with the results
    await open(page, 'quant');
    await page.waitForSelector('#quant-signals', { timeout: 30000 });
    await page.hover('#quant-signals');
    const [popBox] = await Promise.all([ctxA.waitForEvent('page'), page.click('#quant-signals .tools button[data-action="popout"]')]);
    popBox.on('pageerror', (e) => errors.push('pageerror(pop box): ' + e.message));
    const popBoxAsked = [];
    popBox.on('request', (r) => { if (r.url().includes('/api/')) popBoxAsked.push(r.url().replace(BASE, '')); });
    await popBox.waitForSelector('.lp-item[data-type="quant-signals"][data-version]', { timeout: 60000 });
    const popV = await popBox.evaluate(() => Number(document.querySelector('.lp-item[data-type="quant-signals"]').dataset.version));
    await api(page, 'ayşe yilmaz', 'POST', '/api/quant/recompute', {});
    await popBox.waitForFunction((v) => Number(document.querySelector('.lp-item[data-type="quant-signals"]').dataset.version) > v, popV, { timeout: 30000 }).catch(() => null);
    check('⧉ on the page\'s panel: the box in a window of its own (#/pop/box/…), without the menu, brought again when the version moves - its own part only',
      /^#\/pop\/box\/quant-signals/.test(await popBox.evaluate(() => window.location.hash))
      && await popBox.evaluate(() => getComputedStyle(document.getElementById('side')).display === 'none')
      && await popBox.evaluate((v) => Number(document.querySelector('.lp-item[data-type="quant-signals"]').dataset.version) > v, popV)
      && popBoxAsked.some((u) => u.startsWith('/api/quant/box?')) && !popBoxAsked.some((u) => /\/api\/(alarms|view|header|quant\/signals)/.test(u)), popBoxAsked.slice(0, 10));
    await shot(popBox, '44-pop-box');
    await popBox.close();

    // ------------------------------------------------------------------ the quant menu: four entries with tabs
    console.log('quant menu');
    const quantMenu = await page.evaluate(() => {
      const g = [...document.querySelectorAll('#nav .nav-group')].find((x) => (x.querySelector('.gt') || {}).textContent === 'Quant');
      return g ? [...g.querySelectorAll('.nav-item')].map((a) => a.textContent.trim() + ':' + (a.dataset.tabs || '').split(' ').filter(Boolean).length) : null;
    });
    check('the quant menu: four entries - Sinyaller (3 tabs), Faiz (8), FX (3), VİOP', JSON.stringify(quantMenu) === '["Sinyaller:3","Faiz:8","FX:3","VİOP:0"]', quantMenu);
    await open(page, 'quant-regime');                                       // an address of before
    const onTab = () => page.evaluate(() => ({ tabs: [...document.querySelectorAll('#page-tabs button')].map((b) => b.textContent),
      on: [...document.querySelectorAll('#page-tabs button.on')].map((b) => b.dataset.page), lit: [...document.querySelectorAll('#nav .nav-item.active')].map((a) => a.dataset.page) }));
    const regime = await onTab();
    check('an old address (#/quant-regime) opens Faiz on its tab: eight tabs, "Rejim" on, Faiz lit in the menu',
      regime.tabs.join(',') === 'PCA / RV,Çiftler,Korelasyon,Rejim,Eğri Adil Değeri,İma Patikası,TCMB WIRP,Öncü-Takipçi'
      && regime.on.join() === 'quant-regime' && regime.lit.join() === 'quant.faiz' && await page.locator('#quant-regime-signals').count() === 1, regime);
    await page.click('#page-tabs button[data-page="quant-corr"]');
    await page.waitForFunction(() => window.tto.state.pageId === 'quant-corr' && window.tto.state.page.ready, null, { timeout: 30000 });
    await open(page, 'forward');
    await page.click('#nav .nav-item[data-page="quant.faiz"]');
    await page.waitForFunction(() => window.tto.state.pageId === 'quant-corr' && window.tto.state.page && window.tto.state.page.ready, null, { timeout: 30000 }).catch(() => null);
    const back2 = await onTab();
    await page.reload();
    await page.waitForFunction(() => window.tto && window.tto.state.page && window.tto.state.page.ready, null, { timeout: 90000 });
    const hrefAfter = await page.evaluate(() => document.querySelector('#nav .nav-item[data-page="quant.faiz"]').getAttribute('href'));
    check('a tab clicked opens its page (its own address); the entry leads back to the tab opened last, after a reload too',
      back2.on.join() === 'quant-corr' && back2.lit.join() === 'quant.faiz' && hrefAfter === '#/quant-corr', { back2, hrefAfter });
    // a signal's own page link and Ctrl+K still lead to a page of the menu's tabs
    await open(page, 'forward');
    await page.keyboard.press('Control+k');
    await page.keyboard.type('Opsiyon');
    await page.waitForSelector('.findlist .hit');
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => window.tto.state.pageId === 'quant-opt' && window.tto.state.page && window.tto.state.page.ready, null, { timeout: 30000 }).catch(() => null);
    check('Ctrl+K finds a page by its own title and opens it on its tab (Opsiyon: FX lit)', (await onTab()).on.join() === 'quant-opt' && (await onTab()).lit.join() === 'quant.fx');

    // ------------------------------------------------------------------ each user's own menu
    console.log('own menu');
    await page.click('#btn-user');
    await page.click('.menu >> text=Menüyü düzenle…');
    await page.waitForSelector('#menu-edit');
    const editable = await page.evaluate(() => [...document.querySelectorAll('#menu-edit input')].map((b) => b.dataset.page));
    await page.locator('#menu-edit input[data-page="heat"]').uncheck();
    await page.locator('#menu-edit input[data-page="quant.fx"]').uncheck();
    await page.click('#menu-edit-save');
    await page.waitForFunction(() => !document.querySelector('#nav .nav-item[data-page="heat"]') && !document.querySelector('#nav .nav-item[data-page="quant.fx"]'),
      null, { timeout: 10000 });
    const hiddenSaved = await savedLayout((l) => (l.hidden_pages || []).length === 2);
    check('"Menüyü düzenle…": a page and a quant entry out of the menu (an administrator\'s pages listed for her), kept with the account',
      JSON.stringify(hiddenSaved.hidden_pages) === '["heat","quant.fx"]' && editable.includes('users') && editable.includes('quant.faiz')
      && editable.includes('launchpad') && !editable.includes('quant-pca'), { hidden: hiddenSaved.hidden_pages, editable: editable.length });
    await page.keyboard.press('Control+k');
    await page.keyboard.type('Eğri Hareketi');
    await page.waitForSelector('.findlist .hit');
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => window.tto.state.pageId === 'heat' && window.tto.state.page && window.tto.state.page.ready, null, { timeout: 30000 }).catch(() => null);
    const heatOpen = await page.evaluate(() => window.tto.state.pageId);
    await page.reload();
    await page.waitForFunction(() => window.tto && window.tto.state.page && window.tto.state.page.ready, null, { timeout: 90000 });
    check('... a hidden page still opens from Ctrl+K (and its own address); after a reload the menu is still the user\'s',
      heatOpen === 'heat' && await page.evaluate(() => window.tto.state.pageId) === 'heat' && await page.locator('#nav .nav-item[data-page="heat"]').count() === 0
      && await page.locator('#nav .nav-item[data-page="quant.fx"]').count() === 0, heatOpen);
    // another user's menu is their own: Zeynep sees every page; an administrator's pages are not in hers to list
    const ctxM = await browser.newContext({ viewport: { width: 1400, height: 900 } });
    const pageM = await ctxM.newPage();
    pageM.on('pageerror', (e) => errors.push('pageerror(M): ' + e.message));
    await login(pageM, 'Zeynep');
    await pageM.click('#btn-user');
    await pageM.click('.menu >> text=Menüyü düzenle…');
    await pageM.waitForSelector('#menu-edit');
    const hers = await pageM.evaluate(() => ({ nav: !!document.querySelector('#nav .nav-item[data-page="heat"]'),
      users: !!document.querySelector('#menu-edit input[data-page="users"]') }));
    check('... another user\'s menu is their own; the administrators\' pages stay theirs', hers.nav && !hers.users, hers);
    await ctxM.close();
    await page.click('#btn-user');
    await page.click('.menu >> text=Menüyü düzenle…');
    await page.waitForSelector('#menu-edit');
    await page.click('#menu-edit-all');
    await page.click('#menu-edit-save');
    await page.waitForFunction(() => !!document.querySelector('#nav .nav-item[data-page="heat"]') && !!document.querySelector('#nav .nav-item[data-page="quant.fx"]'),
      null, { timeout: 10000 });
    check('"Hepsini göster": the pages back in the menu', (await savedLayout((l) => !(l.hidden_pages || []).length)).hidden_pages.length === 0);

    // ------------------------------------------------------------------ every page renders
    console.log('all pages');
    // (an entry with tabs: each of its pages)
    const ids = await page.evaluate(() => [...document.querySelectorAll('#nav .nav-item')].flatMap((a) => (a.dataset.tabs ? a.dataset.tabs.split(' ') : [a.dataset.page])));
    for (const id of ids) {
      await open(page, id);
      const n = await page.locator('#content table.grid, #content table.plain, #content table.heat, #content .chatlog').count();
      const bad = await page.locator('#content .panel .err').count();
      check('page "' + id + '" renders tables without panel errors', n >= 1 && bad === 0, { tables: n, errors: bad });
    }
    check('no JavaScript errors in the browser', errors.length === 0, errors);
  } catch (err) {
    failures += 1;
    console.log('  FAIL (exception) ' + (err && err.stack ? err.stack : err));
    try { await shot(page, 'failure'); } catch (e) { /* ignore */ }
  }
  await browser.close();
  console.log('\n' + results.filter((r) => r.ok).length + ' passed, ' + failures + ' failed');
  process.exit(failures ? 1 : 0);
})();
