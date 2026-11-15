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
  await page.waitForFunction((x) => window.tto.state.pageId === x && window.tto.state.page && window.tto.state.page.ready, id, { timeout: 90000 });
  await page.waitForTimeout(150);
}

/** Open a tab of the page ('*' = "Tümü": every table of the page). */
async function tab(page, id) {
  await page.evaluate((t) => window.tto.state.page.setTab(t), id);
  await page.waitForTimeout(500);                 // charts of the tab are drawn when they come on the page
}

const panelsOnPage = (page) => page.evaluate(() => [...document.querySelectorAll('#content .panel')].map((p) => p.dataset.panel));

async function cellText(page, ref) {
  return page.evaluate((r) => { const td = window.tto.findCell(r); return td ? td.textContent : null; }, ref);
}

async function cellHandle(page, ref) {
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
      tabs0.join(' ') === 'calc! fwd ret bulk curves off tick *' && on0.slice(0, 5).join(' ') === 'B1 B7 B8 B9 B10' && !on0.includes('B19') && !on0.includes('B15'), [tabs0, on0]);
    const caps = await page.evaluate(() => [...document.querySelectorAll('.panels.pinned .panel[data-panel="B1"] tr.hd td')].map((td) => td.textContent));
    check('the value date strip names its cells', caps.join('|') === '|Valör tarihi|USDTRY spot|EURTRY spot|USDTRY spot valörü|EURTRY spot valörü', caps);
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
    check('"Tümü" lists the tabs one after the other', await page.locator('#content .secthead').count() === 7);
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
    check('a user has no sheet explorer', (await pageB.locator('#nav .nav-item[data-page=explorer]').count()) === 0);
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
    check('saved: the board shows where every instrument stands (the pulled offer is gone, the trade is the last one)',
      chatBoard.length === 7 && chat18[3] === '35,10' && chat18[4] === '' && chat18[5] === '13:55:37' && chat18[6] === '35,14'
      && JSON.stringify(chatBoard.map((r) => r[1])) === JSON.stringify(['6M', '18M', '1Y–5Y', '3Y–5Y', '2Y–3Y–4Y', '9x12', '1Y']) && chatBoard[6][0] === 'XCCY', chatBoard);
    check('the board compares with the dashboard\'s own curve (model, difference in bp)',
      Math.abs(trNumber(chat18[8]) - model18.mid) < 0.006 && Math.abs(trNumber(chat18[9].replace('+', '')) - model18.bid_diff) < 0.06 && chatBoard[6][8] === '', [chat18, model18]);
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
      sw[0] === 'DİBS' && sw[2] === 'Switch (bp)' && sw[3] === '-45' && sw[4] === '-40' && /^-?\d+,\d$/.test(sw[8]) && /bp (eğri|ekran) · uzun (ucuz|pahalı)/.test(sw[12]), sw);
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
    await api(page, 'ayşe yilmaz', 'POST', '/api/reset', { book: 'tto', refs: ['VIOP!C16', 'VIOP!C17', 'VIOP!D16', 'VIOP!D17'] });
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
    check('the forward quote matrices follow the forward pricing table: USDTRY, EURTRY, then the way back of each',
      await order(['B14', 'EKF1', 'EKF5', 'EKF2', 'EKF6']));
    const ois1m = trNumber(await cellText(page, 'EK_FWD!L5'));
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
    check('gold tab: the VİOP gold tables, the calculator, then spot / source, swap rate curve and forwards',
      await order(['B9', 'B10', 'B11', 'XAU4', 'XAU1', 'XAU2', 'XAU3', 'B11b']), await panelsOnPage(page));
    await tab(page, 'calc');
    check('the gold calculator is with the calculators as well', (await panelsOnPage(page)).join(' ') === 'B8 XAU4');
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
    check('header strip: "Spot kaynağı" says where the spot comes from', /Spot kaynağı/.test(spotKpi) && /MANUEL/.test(spotKpi), spotKpi);
    await page.click('#kpi-spot');
    await page.waitForSelector('#spot-bid');
    const dlg = { bid: await page.inputValue('#spot-bid'), ask: await page.inputValue('#spot-ask'), src: await page.textContent('#spot-source') };
    check('a click on it opens the manual spot: the two cells of the VİOP sheet', dlg.bid === '49,997' && dlg.ask === '49,9975' && dlg.src === 'MANUEL', dlg);
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
    await page.click('#kpi-spot');                           // put the file's own manual spot back
    await page.waitForSelector('#spot-bid');
    await page.fill('#spot-bid', '49,997');
    await page.fill('#spot-ask', '49,9975');
    await page.keyboard.press('Enter');
    await page.waitForSelector('#spot-bid', { state: 'detached' });
    await waitCell(page, 'VIOP!AA9', 't.trim() === "49,9970"');

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
    check('the history of the recorded month is filled in the background', hist.phase === 'idle' && hist.mpc_days === 21 && hist.series === 8 && !hist.error, hist);
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
      && series.some((r) => r[2] === 'TYSOA Curncy' && r[7] === 'yedek kaynak') && series.length === 118, rowOf(series, 'TLREF'));
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
    await shot(page, '15-settings');

    // ------------------------------------------------------------------ bonds: the chat, the screen, the lists
    console.log('bonds');
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
    check('DİBS RV: the day\'s broker chat next to each bond - bid, ask, the time, the yield of the mid against the screen',
      rvBroker.head.join('|') === 'Broker bid|Broker ask|Son işlem|Saat|Broker getiri %|Broker − ekran (bp)'
      && rvBroker.bond[0] === '100,550' && rvBroker.bond[1] === '100,575' && rvBroker.bond[3] === '10:25' && /^3\d,\d\d$/.test(rvBroker.bond[4])
      && /^[+-]?\d+$/.test(rvBroker.bond[5]), rvBroker);
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
      && /Broker Chat · bugün/.test(cardText) && /BIST bileşik getiri/.test(cardText) && /Sinyal/.test(cardText), cardText.slice(0, 300));
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
    check('Ctrl+K lists the tables of every page by name', hits.length >= 6 && hits.some((x) => /^Interest 2 SP · TRY faizi.* @ Forward › Hesaplayıcılar$/.test(x)), hits);
    await page.fill('#find', 'faizden fiyat');
    await page.waitForFunction(() => document.querySelectorAll('.findlist .hit').length === 1);
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => window.tto.state.pageId === 'viop' && window.tto.state.page && window.tto.state.page.ready, null, { timeout: 90000 });
    await page.waitForTimeout(600);
    check('Enter goes to the table: its page, its tab', (await panelsOnPage(page)).includes('XAU4')
      && await page.evaluate(() => document.querySelector('.viewtabs button.on').dataset.tab) === 'calc');

    // ------------------------------------------------------------------ every page renders
    console.log('all pages');
    const ids = await page.evaluate(() => [...document.querySelectorAll('#nav .nav-item')].map((a) => a.dataset.page));
    for (const id of ids) {
      await open(page, id);
      const n = await page.locator('#content table.grid, #content table.plain, #content table.heat').count();
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
