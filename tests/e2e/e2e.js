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

/** What lands on the clipboard by ``action`` (a mark is put there first; Windows line ends as \n). */
async function clipAfter(page, action) {
  await page.evaluate(() => navigator.clipboard.writeText('·'));
  await action();
  for (let k = 0; k < 150; k++) {
    const t = await page.evaluate(() => navigator.clipboard.readText());
    if (t !== '·') return t.replace(/\r\n/g, '\n');
    await page.waitForTimeout(100);
  }
  return '';
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
    // "Hesap" (tto/progress.py): right after the start the history fills the recorded month (its meeting-pricing days)
    // and the quant worker fits - the top bar says which and how far while one runs (a planted view is checked below)
    const prog0 = (await api(page, 'ayşe yilmaz', 'GET', '/api/progress')).json || {};
    if (prog0.busy) {
      const shown = await page.waitForFunction(() => {
        const b = document.getElementById('hesap-ind');
        return b && !b.classList.contains('hidden') ? b.textContent : null;
      }, null, { timeout: 20000 }).then((x) => x.jsonValue()).catch(() => null);
      check('"Hesap" in the top bar while a calculation runs (right after the start: the history\'s days, the quant fit) - which and how far',
        !!shown && /^Hesap(tarihçe|PPK geçmişi|Quant|ML|geri test) \d+/.test(shown), [shown, prog0.text]);
    } else console.log('  (nothing ran right after the start: "Hesap" is checked on a planted view below)');
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
    // "İşlem gir" on a price (right click): Masa's forward quote at its ask - the row's own value date, the points clicked, sold
    await open(page, 'masa');
    const quoteDate = (await cellText(page, 'EK_FWD!B7')).trim();
    const quoteAsk = (await cellText(page, 'EK_FWD!I7')).trim();
    await (await cellHandle(page, 'EK_FWD!I7')).click({ button: 'right' });
    await page.waitForSelector('.menu');
    const priceMenu = await page.$$eval('.menu button', (bs) => bs.map((b) => [b.textContent, b.disabled]));
    check('a price\'s right-click menu (Masa\'s forward quote, 3M ask points): "İşlem gir" first, watch / alarm / copy after it',
      priceMenu[0][0] === 'İşlem gir' && !priceMenu[0][1] && priceMenu.some((x) => x[0] === 'İzlemeye ekle') && priceMenu.some((x) => /^Kopyala/.test(x[0])), priceMenu);
    await page.click('.menu button:text-is("İşlem gir")');
    await page.waitForFunction(() => window.tto.state.pageId === 'blotter' && window.tto.state.page && window.tto.state.page.fwd
      && window.tto.state.page.fwd.date && window.tto.state.page.fwd.date.value !== '', null, { timeout: 30000 });
    const priceFwd = await page.evaluate(() => { const f = window.tto.state.page.fwd; return [f.pair, f.dir, f.basis, f.date.value, f.manual.value, f.note.value, f.amount.value, f.cpt.value]; });
    await page.waitForFunction(() => /\d/.test((document.querySelector('.entry .pad:not(.hidden) .quotebox [data-k="fwd-points"] .v') || {}).textContent || ''), null, { timeout: 20000 });
    check('... Günlük İşlemler opens filled: USDTRY, sold (ask), the row\'s value date, the ask points - no amount, no counterparty',
      JSON.stringify(priceFwd.slice(0, 5)) === JSON.stringify(['USDTRY', 'S', 'SP', quoteDate, quoteAsk]) && priceFwd[5] === 'Fiyat: 3M · Puan ask (Masa · FORWARD KOTASYON)'
      && priceFwd[6] === '' && priceFwd[7] === '' && (await page.textContent('.entry .pad:not(.hidden) .quotebox [data-k="fwd-points"] .v')).trim() === quoteAsk,
      [priceFwd, quoteDate, quoteAsk]);
    // an OIS quote (a par: a mid) fills an OIS outright - the tenor and the level; the side is the user's, nothing saved without it
    await open(page, 'ois');
    const quotePar = (await cellText(page, 'OIS_MAIN!B14')).trim();
    await (await cellHandle(page, 'OIS_MAIN!B14')).click({ button: 'right' });
    await page.click('.menu button:text-is("İşlem gir")');
    await page.waitForFunction(() => window.tto.state.pageId === 'blotter' && window.tto.state.page && window.tto.state.page.ois
      && window.tto.state.page.ois.level && window.tto.state.page.ois.level.value !== '', null, { timeout: 30000 });
    const priceOis = await page.evaluate(() => { const o = window.tto.state.page.ois; return [o.strategy, o.side, o.f.tenor && o.f.tenor.value, o.level.value,
      [...o.sideSeg.children].filter((b) => b.classList.contains('on')).length]; });
    check('an OIS quote (1Y par) fills an OIS outright: 1Y at the par, no side chosen', JSON.stringify(priceOis) === JSON.stringify(['outright', null, '1Y', quotePar, 0]),
      [priceOis, quotePar]);
    await page.waitForFunction(() => /Yönü seçin/.test((document.querySelector('.entry .pad:not(.hidden) .quotebox') || {}).textContent || ''), null, { timeout: 20000 });
    const tradesBefore = (await api(page, 'ayşe yilmaz', 'GET', '/api/blotter')).json.trades.length;
    await page.click('.entry .pad:not(.hidden) .row.actions .btn.primary');
    await page.waitForFunction(() => /Yönü seçin/.test(document.getElementById('toasts').textContent), null, { timeout: 10000 });
    check('... and is not saved until a side is chosen', (await api(page, 'ayşe yilmaz', 'GET', '/api/blotter')).json.trades.length === tradesBefore);
    // a MPC OIS row: the form's MPC strategy with the row's own two days (the rows move with the calendar)
    await open(page, 'ois');
    const mpcStart = (await cellText(page, 'OIS_MAIN!B85')).trim();
    const mpcEnd = (await cellText(page, 'OIS_MAIN!C85')).trim();
    await (await cellHandle(page, 'OIS_MAIN!D85')).click({ button: 'right' });
    await page.click('.menu button:text-is("İşlem gir")');
    await page.waitForFunction(() => window.tto.state.pageId === 'blotter' && window.tto.state.page && window.tto.state.page.ois
      && window.tto.state.page.ois.strategy === 'mpc' && window.tto.state.page.ois.level.value !== '', null, { timeout: 30000 });
    const priceMpc = await page.evaluate(() => { const o = window.tto.state.page.ois; const t = (s) => s.options[s.selectedIndex].textContent; return [t(o.f.start), t(o.f.end)]; });
    check('... a MPC OIS row: the MPC form with the row\'s own two days', priceMpc[0].endsWith(mpcStart) && priceMpc[1].endsWith(mpcEnd), [priceMpc, mpcStart, mpcEnd]);
    // no price, no "İşlem gir"; a price with no form (a VİOP contract) says why, greyed
    await open(page, 'masa');
    await (await cellHandle(page, 'EK_FWD!C7')).click({ button: 'right' });
    await page.waitForSelector('.menu');
    const noPrice = await page.$$eval('.menu button', (bs) => bs.map((b) => b.textContent));
    await page.keyboard.press('Escape');
    await (await cellHandle(page, 'MASA!D110')).click({ button: 'right' });
    await page.waitForSelector('.menu');
    const viopMenu = await page.$$eval('.menu button', (bs) => bs.map((b) => [b.textContent, b.disabled]));
    await page.keyboard.press('Escape');
    check('a cell that is no price (the days of a tenor) offers no "İşlem gir"; a VİOP contract\'s price greys it, saying why',
      !noPrice.some((x) => /İşlem gir/.test(x)) && noPrice.some((x) => /^Kopyala/.test(x)) && viopMenu.some((x) => /^İşlem gir · VİOP/.test(x[0]) && x[1]), [noPrice, viopMenu]);
    await open(page, 'forward');
    await tab(page, 'fwd');

    // ------------------------------------------------------------------ an amount as the desk says it; its quote
    // "5m" in the Forward DV01 block's amount (an amount input) is 5.000.000; "Kotasyon kopyala" puts the side, the dates,
    // the price and the amount on the clipboard
    await typeInto(page, 'Forward!O45', '5m');
    await waitCell(page, 'Forward!O45', '/5\\.000\\.000/.test(t)');
    check('"5m" typed in an amount input is 5.000.000', /^\$?\s*5\.000\.000$/.test((await cellText(page, 'Forward!O45')).trim()),
      await cellText(page, 'Forward!O45'));
    const dvQuote = (await clipAfter(page, () => page.click('.panel[data-panel="B18"] button[data-action="kotasyon"]'))).split('\n');
    check('"Kotasyon kopyala" on the Forward DV01 block: the pair, the side, the dates with the days, the outright and the amount',
      /^USDTRY forward · \d\d\.\d\d\.\d{4}$/.test(dvQuote[0]) && /^Yön\s+USD alış$/.test(dvQuote[1])
      && dvQuote.some((l) => /^Vade tarihi\s+\d\d\.\d\d\.\d{4} \(\d+ gün\)$/.test(l)) && dvQuote.some((l) => /^Outright\s+\d+,\d{4}$/.test(l))
      && dvQuote[dvQuote.length - 1].replace(/\s+/g, ' ') === 'Tutar 5.000.000 USD', dvQuote);
    await api(page, 'ayşe yilmaz', 'POST', '/api/reset', { book: 'tto', refs: ['Forward!O45'] });
    await waitCell(page, 'Forward!O45', '/1\\.000\\.000/.test(t)');

    // ------------------------------------------------------------------ RET editor dialog
    console.log('RET editor');
    await page.click('#btn-ret');
    await page.waitForSelector('.modal table.ret');
    const firstBid = await page.inputValue('.modal table.ret tbody tr:nth-child(1) td:nth-child(3) input');
    check('editor shows the stored curve in percent', firstBid === '35,1', firstBid);
    check('the curve as opened changes nothing: the line above the table says so, every Δ is 0',
      (await page.textContent('#ret-diff')) === 'Kayıtlı eğriyle aynı: değişen vade yok'
      && (await page.$$eval('.modal table.ret td.ret-delta', (tds) => tds.length === 30 && tds.every((td) => td.textContent === '0'))));
    const savedRet = Object.fromEntries((await api(page, 'ayşe yilmaz', 'GET', '/api/ret')).json.rows.map((r) => [r.tenor, r]));
    await page.evaluate(() => navigator.clipboard.writeText('Vade\tBid\tAsk\r\n1M\t34,00\t34,20\r\n3M\t35,1\t35,6\r\n1Y\t0,381\t0,392\r\n'));
    await page.click('.modal table.ret tbody tr:nth-child(1) td:nth-child(3) input');
    await page.keyboard.press('Control+v');
    await page.waitForFunction(() => document.querySelector('.modal table.ret tbody tr:nth-child(6) td:nth-child(3) input').value === '34,00');
    await shot(page, '03-ret-editor');
    // how much the paste changed, and where: Δ bid / Δ ask per tenor against the saved curve, coloured, the rows lit, a line
    const bpSigned = (x) => {
      const r = Math.round(x * 10) / 10;
      if (Math.abs(r) < 0.05) return '0';
      const a = Math.abs(r);
      return (r > 0 ? '+' : '−') + (Math.abs(a - Math.round(a)) > 1e-9 ? a.toFixed(1).replace('.', ',') : String(Math.round(a)));
    };
    const pastedRet = { '1M': [0.34, 0.342], '3M': [0.351, 0.356], '1Y': [0.381, 0.392] };
    const wantDelta = {};
    const wantMoved = [];
    for (const [t, [b, a]] of Object.entries(pastedRet)) {
      const d = [Math.round((b - savedRet[t].bid) * 1e6) / 100, Math.round((a - savedRet[t].ask) * 1e6) / 100];
      wantDelta[t] = d;
      if (d.some((x) => Math.abs(x) >= 0.05)) wantMoved.push(t + ' ' + bpSigned(d[0]) + ' / ' + bpSigned(d[1]));
    }
    const deltaCells = await page.$$eval('.modal table.ret td.ret-delta', (tds) => Object.fromEntries(tds.map((td) => [td.dataset.tenor + ':' + td.dataset.side,
      { t: td.textContent, up: td.classList.contains('up'), down: td.classList.contains('down'), lit: td.closest('tr').classList.contains('ret-chg') }])));
    const colourOk = (x, c) => (Math.abs(x) < 0.05 ? !c.up && !c.down : x > 0 ? c.up : c.down);
    check('pasting a RET: every tenor shows Δ bid / Δ ask in bp against the saved curve (up green, down red), changed rows lit, the others 0',
      wantMoved.length >= 2 && Object.entries(wantDelta).every(([t, d]) => deltaCells[t + ':bid'].t === bpSigned(d[0]) && deltaCells[t + ':ask'].t === bpSigned(d[1])
        && colourOk(d[0], deltaCells[t + ':bid']) && colourOk(d[1], deltaCells[t + ':ask']) && deltaCells[t + ':bid'].lit === d.some((x) => Math.abs(x) >= 0.05))
      && deltaCells['ON:bid'].t === '0' && !deltaCells['ON:bid'].lit && deltaCells['2M:ask'].t === '0', [wantDelta, deltaCells['1M:bid'], deltaCells['3M:ask']]);
    const diffText = await page.textContent('#ret-diff');
    const wantDiff = 'Değişen ' + wantMoved.length + ' vade: ' + wantMoved.join(' · ') + ' · ' + (15 - wantMoved.length) + ' vade aynı';
    check('... and the line above the table: "Değişen N vade: 1M … / … · … · M vade aynı"', diffText === wantDiff, [diffText, wantDiff]);
    await page.click('.modal .mfoot .btn.primary');
    await page.waitForFunction(() => /RET faizleri kaydedildi/.test(document.getElementById('toasts').textContent));
    await page.waitForFunction(() => /1M/.test((document.querySelector('.ret-hist .ret-hist-item .ret-hist-chg') || {}).textContent || ''), null, { timeout: 15000 }).catch(() => null);
    const histChg = await page.$eval('.ret-hist .ret-hist-item .ret-hist-chg', (e) => e.textContent).catch(() => null);
    check('the RET history keeps what the upload changed, tenor by tenor ("1M −45 / −45 · …")', histChg === wantMoved.join(' · '), [histChg, wantMoved]);
    // the same curve pasted over the saved one: nothing changes, and it says so
    await page.click('.modal table.ret tbody tr:nth-child(1) td:nth-child(3) input');
    await page.keyboard.press('Control+v');
    await page.waitForFunction(() => /kayıtlı eğriyle aynı, değişen vade yok/.test(document.getElementById('toasts').textContent), null, { timeout: 10000 }).catch(() => null);
    check('a pasted curve that changes nothing says so (the line and the toast)', (await page.textContent('#ret-diff')) === 'Kayıtlı eğriyle aynı: değişen vade yok'
      && /kayıtlı eğriyle aynı, değişen vade yok/.test(await page.textContent('#toasts')));
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
    // a date typed and the scenario loaded at once - the typed value's request held back 2 s on its way: the load waits
    // for the write in flight (grid.js pendingWrites) and goes after its answer - the scenario's date stands, on the page
    // and in the store (the server applies them in that order: tests/test_scenario_order.py)
    const sent = [];
    const pathOf = (r) => new URL(r.url()).pathname;                 // (the page's requests carry ?lang=…)
    const INPUTS = /\/api\/inputs(\?|$)/;
    await page.route(INPUTS, async (route) => {
      sent.push('yazı gönderildi');
      await new Promise((r) => setTimeout(r, 2000));
      await route.continue();
    });
    const onRes = (r) => { if (pathOf(r) === '/api/inputs') sent.push('yazı yanıtlandı'); };
    const onReq = (r) => { if (pathOf(r) === '/api/scenarios/load') sent.push('yükleme gönderildi'); };
    page.on('response', onRes);
    page.on('request', onReq);
    await typeInto(page, 'Forward!D2', '01.03.2027');
    await page.click('#btn-scen');
    await page.waitForSelector('.modal table.plain .btn.primary');
    const loaded = page.waitForResponse((r) => pathOf(r) === '/api/scenarios/load', { timeout: 20000 });
    await page.click('.modal table.plain .btn.primary');             // Yükle, while the date's write is held
    await loaded;
    await page.keyboard.press('Escape');
    page.off('response', onRes);
    page.off('request', onReq);
    await page.unroute(INPUTS);
    await waitCell(page, 'Forward!D2', "t.trim() === '15.12.2026'");
    await page.waitForTimeout(500);
    const mineD2 = (((await api(page, 'ayşe yilmaz', 'GET', '/api/my-inputs')).json || {}).inputs || []).find((x) => x.ref === 'Forward!D2');
    check('a date typed and a scenario loaded at once: the load waits for the write in flight - the scenario\'s date stands, on the page and stored',
      JSON.stringify(sent) === JSON.stringify(['yazı gönderildi', 'yazı yanıtlandı', 'yükleme gönderildi'])
      && (await cellText(page, 'Forward!D2')).trim() === '15.12.2026' && !!mineD2 && mineD2.value === 46371, { sent, mineD2 });

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

    // "Düzenle": a trade changed after it was entered.  A forward opened and left ("Vazgeç"): nothing changes, the form is back
    const fwdForm = () => page.evaluate(() => { const f = window.tto.state.page.fwd; return { amount: f.amount.value, date: f.date.value, basis: f.basis,
      dir: f.dir, manual: f.manual.value, title: document.querySelector('#blotter-entry-title').textContent }; });
    const fwdKept = await fwdForm();
    const beforeEdit = (await api(page, 'ayşe yilmaz', 'GET', '/api/blotter')).json.trades;
    await page.click('.lists .panel:nth-child(1) table.grid td.act button[data-act="edit"]');
    await page.waitForFunction(() => document.querySelector('#blotter-entry-title').textContent === 'İşlemi düzenle');
    const fwdEdit = await fwdForm();
    // the line over the quote says, before saving, how the edit is priced: nothing changed; the counterparty alone; the value
    // date - on today's market (marked)
    const pricingLine = (want) => page.waitForFunction((w) => {
      const el = document.querySelector('.entry .pad:not(.hidden) [data-k="edit-pricing"]');
      return el && el.textContent.startsWith(w);
    }, want, { timeout: 15000 }).then(() => page.evaluate(() => {
      const el = document.querySelector('.entry .pad:not(.hidden) [data-k="edit-pricing"]');
      return [el.textContent, el.classList.contains('today')];
    }));
    const fwdLines = [await pricingLine('Değişiklik yok')];
    await page.evaluate(() => { const el = window.tto.state.page.fwd.cpt; el.value = 'E2E KT'; el.dispatchEvent(new Event('input')); });
    fwdLines.push(await pricingLine('Yalnızca karşı taraf / not değişir'));
    await page.fill('#fwd-date', '16.12.2026');
    fwdLines.push(await pricingLine('Valör değişti'));
    await page.click('#fwd-edit-cancel');
    await page.waitForFunction(() => document.querySelector('#blotter-entry-title').textContent === 'Yeni işlem');
    const fwdBack = await fwdForm();
    check('"Düzenle" on a forward fills its form with the trade (amount, value date, pricing, side); "Vazgeç" gives the form back, the trade as it was',
      fwdEdit.amount === '10.000.000' && fwdEdit.date === '15.12.2026' && fwdEdit.basis === 'RET_MID' && fwdEdit.dir === 'B'
      && JSON.stringify(fwdBack) === JSON.stringify(fwdKept) && fwdKept.basis === 'FWD'
      && JSON.stringify((await api(page, 'ayşe yilmaz', 'GET', '/api/blotter')).json.trades) === JSON.stringify(beforeEdit), [fwdKept, fwdEdit, fwdBack]);
    check('... the form says before saving how it is priced: "Değişiklik yok", the counterparty alone (prices stay), a new value date on today\'s market (marked)',
      fwdLines[0][1] === false && fwdLines[1][0] === 'Yalnızca karşı taraf / not değişir: fiyat ve tutarlar aynı kalır' && fwdLines[1][1] === false
      && fwdLines[2][0] === 'Valör değişti: bugünkü piyasayla yeniden fiyatlanır' && fwdLines[2][1] === true, fwdLines);
    // the spread: its level changed from the page - the same legs (ids), the list, "Mid'e göre" and the cost table follow
    const legsOf = (trades) => trades.filter((t) => t.kind === 'ois' && t.strategy === 'spread');
    const spreadBefore = legsOf(beforeEdit);
    await page.click('.lists .panel:nth-child(2) table.grid td.act button[data-act="edit"]');
    await page.waitForFunction(() => !document.querySelector('#blotter-edit-note').classList.contains('hidden')
      && /bp/.test((document.querySelector('.entry .pad:not(.hidden) .quotebox [data-k="vs-mid-bp"] .v') || {}).textContent || ''), null, { timeout: 15000 });
    const editForm = await page.evaluate(() => {
      const pane = document.querySelector('.entry .pad:not(.hidden)');
      return { note: document.querySelector('#blotter-edit-note').textContent, save: pane.querySelector('.row.actions .btn.primary').textContent,
        cancel: !document.querySelector('#ois-edit-cancel').classList.contains('hidden'), level: window.tto.state.page.ois.level.value,
        fwdTab: document.querySelector('.entry .tabs button:nth-child(1)').disabled,
        strategies: [...pane.querySelectorAll('.seg button')].filter((b) => ['outright', 'spread', 'fly', 'fra', 'mpc'].includes(b.dataset.v) && !b.disabled).map((b) => b.dataset.v) };
    });
    check('"Düzenle" on the spread: the OIS form with its level and its strategy only, "Değişikliği kaydet" and "Vazgeç", the other products closed',
      /Düzenleniyor: FLATTENER 1Y\/2Y @ 25,00 bp/.test(editForm.note) && editForm.save === 'Değişikliği kaydet' && editForm.cancel && editForm.level === '25'
      && editForm.fwdTab && JSON.stringify(editForm.strategies) === '["spread"]', editForm);
    await shot(page, '04a-blotter-edit');
    // the new level 3 bp from the spread's mid, above it: in a FLATTENER's favour (the replay's 1Y/2Y mid is a round 30 bp - a
    // level at mid is "0,00", neither green nor red)
    const spreadMid = (await api(page, 'ayşe yilmaz', 'POST', '/api/blotter/quote/ois', { strategy: 'spread', side: 'FLATTENER', short: '1Y', long: '2Y', level: '25' })).json.info.market;
    const newLevel = Math.round(spreadMid) + (Math.round(spreadMid) + 3 === 25 ? 4 : 3);
    const newText = '@ ' + newLevel + ',00 bp';
    await page.fill('.entry .pad:not(.hidden) input[placeholder="örn. -125"]', String(newLevel));
    const qNew = (await api(page, 'ayşe yilmaz', 'POST', '/api/blotter/quote/ois', { strategy: 'spread', side: 'FLATTENER', short: '1Y', long: '2Y', level: String(newLevel) })).json;
    const bpOf = (t) => trNumber(String(t).replace('bp', '').replace('+', ''));
    await page.waitForFunction((want) => {
      const v = document.querySelector('.entry .pad:not(.hidden) .quotebox [data-k="vs-mid-bp"] .v');
      return v && Math.abs(Number(v.textContent.replace('bp', '').replace('+', '').replace(/\./g, '').replace(',', '.').trim()) - want) < 0.006;
    }, -qNew.info.cost_bp, { timeout: 15000 });
    const vsTile = await page.evaluate(() => [...document.querySelectorAll('.entry .pad:not(.hidden) .quotebox .q')].slice(0, 3)
      .map((q) => ({ l: q.querySelector('.l').textContent, v: q.querySelector('.v').textContent, cls: q.className, tip: q.title })));
    const vsNew = -qNew.info.cost_bp;
    check('the quote says "Mid\'e göre": the trade against mid, + better (green), − worse (red) - the cost turned round (bp, $, TL)',
      vsTile.map((x) => x.l).join('|') === 'Mid\'e göre (bp)|Mid\'e göre ($)|Mid\'e göre (TL)' && Math.abs(bpOf(vsTile[0].v) - vsNew) < 0.006
      && vsNew > 1 && /^\+/.test(vsTile[0].v) && /costpos/.test(vsTile[0].cls) && /costpos/.test(vsTile[1].cls)
      && Math.abs(trNumber(vsTile[1].v.replace('+', '')) + qNew.info.cost_usd) < 1 && /mid'den iyi \(lehine\)/.test(vsTile[0].tip), [vsTile, qNew.info]);
    const editPricedLine = await page.evaluate(() => {
      const el = document.querySelector('.entry .pad:not(.hidden) [data-k="edit-pricing"]');
      const labels = [...document.querySelectorAll('.entry .pad:not(.hidden) .quotebox .q .l')].map((x) => x.textContent);
      return [el ? el.textContent : null, el ? el.classList.contains('today') : null, labels.includes('Mid (işlem anı)'), labels.includes('Piyasa mid')];
    });
    check('... a level changed, the instrument the same: struck at the trade\'s own mid ("Mid (işlem anı)"), not on today\'s market',
      editPricedLine[0] === 'İşlem anının mid\'i ve eğrisiyle: mid\'e göre değer işlemin kendi mid\'ine göre' && editPricedLine[1] === false
      && editPricedLine[2] && !editPricedLine[3], editPricedLine);
    await page.click('.entry .pad:not(.hidden) .row.actions .btn.primary');
    await page.waitForFunction((x) => document.querySelector('.lists .panel:nth-child(2)').textContent.includes(x)
      && document.querySelector('#blotter-entry-title').textContent === 'Yeni işlem', newText, { timeout: 15000 });
    const spreadAfter = legsOf((await api(page, 'ayşe yilmaz', 'GET', '/api/blotter')).json.trades);
    const shortLeg = spreadAfter.find((t) => t.role === 'short'), longLeg = spreadAfter.find((t) => t.role === 'long');
    const editList = await page.evaluate((x) => {
      const rows = [...document.querySelectorAll('.lists .panel:nth-child(2) table.grid tr')];
      const head = [...rows[0].children].map((td) => td.textContent);
      const cells = [...rows.find((tr) => tr.textContent.includes(x)).children];
      const at = (name) => cells[head.indexOf(name)];
      const cost = [...document.querySelectorAll('.lists .panel:nth-child(5) table.grid tr')].map((tr) => [...tr.children].map((td) => td.textContent));
      return { head, timeCls: at('Saat').className, tip: at('Saat').title, vs: at('Mid\'e göre (bp)').textContent, vsCls: at('Mid\'e göre (bp)').className,
        cost, save: document.querySelector('.entry .pad:not(.hidden) .row.actions .btn.primary').textContent,
        cancel: document.querySelector('#ois-edit-cancel').classList.contains('hidden'), fwdTab: document.querySelector('.entry .tabs button:nth-child(1)').disabled };
    }, newText);
    const costHead = editList.cost[0] || [], twoYear = editList.cost.find((r) => r[0] === '2Y') || [];
    const vsAfter = -spreadAfter[0].cost_bp;
    check('... saved: the same legs (ids, entry time) at the new level, the list says it was edited (who, when, what it was), "Mid\'e göre" and the cost table follow',
      JSON.stringify(spreadAfter.map((t) => [t.id, t.created_at])) === JSON.stringify(spreadBefore.map((t) => [t.id, t.created_at]))
      && shortLeg.rate === spreadBefore.find((t) => t.role === 'short').rate && Math.abs(longLeg.rate - shortLeg.rate - newLevel / 1e4) < 1e-12
      && spreadAfter.every((t) => t.edits.length === 1 && t.edits[0].by === 'ayşe yilmaz') && /edited/.test(editList.timeCls)
      && /^Düzenlendi: \d\d:\d\d · Ayşe Yılmaz/.test(editList.tip) && /Önceki: İşlem FLATTENER 1Y\/2Y @ 25,00 bp/.test(editList.tip)
      && editList.head.includes('Mid\'e göre (bp)') && editList.head.includes('Mid\'e göre ($)') && !editList.head.includes('Maliyet (bp)')
      && Math.abs(bpOf(editList.vs) - vsAfter) < 0.006 && Math.abs(vsAfter - vsNew) < 0.006 && /^\+/.test(editList.vs) && /c-pos/.test(editList.vsCls)
      && Math.abs(trNumber(twoYear[costHead.indexOf('Ort. receive')]) - longLeg.rate * 100) < 6e-5
      && editList.save === 'İşlemi kaydet' && editList.cancel && !editList.fwdTab, { editList, spreadAfter, spreadBefore });
    // the counterparty alone, in the dialog a day gone by's trade opens with (opened here on today's first forward)
    const fwd1 = (await api(page, 'ayşe yilmaz', 'GET', '/api/blotter')).json.trades.find((t) => t.kind === 'fwd');
    await page.evaluate((id) => window.tto.state.page.editFields(window.tto.state.page.data.trades.find((t) => t.id === id)), fwd1.id);
    await page.waitForSelector('#blotter-fields-cpt');
    await page.fill('#blotter-fields-cpt', 'E2E KARŞI');
    await page.click('#blotter-fields-save');
    await page.waitForFunction(() => !document.querySelector('#blotter-fields'));
    const fwd1After = (await api(page, 'ayşe yilmaz', 'GET', '/api/blotter')).json.trades.find((t) => t.id === fwd1.id);
    const dealOf = (t) => JSON.stringify([t.forward, t.try_rate, t.spot, t.points, t.amount, t.tl, t.dv01, t.dv01_tl, t.value_date]);
    check('"Karşı taraf ve not" (the dialog of a day gone by\'s trade): the counterparty changes, the forward\'s prices and amounts stay',
      fwd1After.cpt === 'E2E KARŞI' && dealOf(fwd1After) === dealOf(fwd1) && fwd1After.edits.length === 1 && fwd1After.edits[0].priced === 'none',
      [fwd1, fwd1After]);
    // "Mid'e göre" for a PAY and a RECEIVE 67 bp either side of mid (the desk: a PAY under mid is in its favour), in the quote and
    // in the list: + better than mid (green), − worse (red)
    const mid1y = (await api(page, 'ayşe yilmaz', 'GET', '/api/blotter/ois-market')).json.tenors.find((r) => r.tenor === '1Y').par;
    await page.click('.entry .pad:not(.hidden) .seg button[data-v="outright"]');
    const vsSeen = [];
    for (const [side, bp, better] of [['PAY', -67, true], ['PAY', 67, false], ['RECEIVE', 67, true], ['RECEIVE', -67, false]]) {
      const level = ((mid1y + bp / 1e4) * 100).toFixed(4).replace('.', ',');
      const label = side + ' 1Y @ ' + level + '%';                  // (the quote's own label: its side and level)
      await page.click(`.entry .pad:not(.hidden) .seg button[data-v="${side}"]`);
      await page.fill('.entry .pad:not(.hidden) input[placeholder="örn. 37,25"]', level);
      await page.waitForFunction((l) => document.querySelector('.entry .pad:not(.hidden) .quotebox').textContent.includes(l)
        && !!document.querySelector('.entry .pad:not(.hidden) .quotebox [data-k="vs-mid-bp"]'), label, { timeout: 15000 });
      const t = await page.evaluate(() => { const q = document.querySelector('.entry .pad:not(.hidden) .quotebox [data-k="vs-mid-bp"]'); return [q.querySelector('.v').textContent, q.className]; });
      const rows = await page.locator('.lists .panel:nth-child(2) table.grid tr').count();
      await page.click('.entry .pad:not(.hidden) .row.actions .btn.primary');
      await page.waitForFunction((n) => document.querySelectorAll('.lists .panel:nth-child(2) table.grid tr').length === n + 1, rows, { timeout: 15000 });
      const row = await page.evaluate((l) => {
        const trs = [...document.querySelectorAll('.lists .panel:nth-child(2) table.grid tr')];
        const head = [...trs[0].children].map((td) => td.textContent);
        const cells = [...trs.find((tr) => tr.textContent.includes(l)).children];
        return [cells[head.indexOf('Mid\'e göre (bp)')].textContent, cells[head.indexOf('Mid\'e göre (bp)')].className];
      }, label);
      vsSeen.push({ side, better, tile: t, row });
    }
    check('"Mid\'e göre" on a PAY and a RECEIVE either side of mid: + (green) when better than mid, − (red) when worse - in the quote and in the list',
      vsSeen.every((x) => Math.abs(Math.abs(bpOf(x.tile[0])) - 67) < 0.011 && Math.abs(bpOf(x.row[0]) - bpOf(x.tile[0])) < 0.006
        && (x.better ? /^\+/.test(x.tile[0]) && /costpos/.test(x.tile[1]) && /^\+/.test(x.row[0]) && /c-pos/.test(x.row[1])
          : /^-/.test(x.tile[0]) && /costneg/.test(x.tile[1]) && /^-/.test(x.row[0]) && /c-neg/.test(x.row[1]))), vsSeen);
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

    // ------------------------------------------------------------------ "Benzerini gir" / "Ters işlem" (islem-kopya)
    // a trade's row actions fill the form from it - a new trade, never an edit; nothing is kept until "İşlemi kaydet".  What
    // this block saves it deletes again: the counts the checks below read stay as they were.
    {
      const ME = 'ayşe yilmaz';
      const serialText = (s) => { const d = new Date(Date.UTC(1899, 11, 30) + s * 86400000); return String(d.getUTCDate()).padStart(2, '0') + '.' + String(d.getUTCMonth() + 1).padStart(2, '0') + '.' + d.getUTCFullYear(); };
      const listedNow = async (q) => (await api(page, ME, 'GET', '/api/blotter' + (q || ''))).json.trades;
      const copyShown = (head) => page.waitForFunction((h) => { const el = document.querySelector('#blotter-copy-note'); return el && !el.classList.contains('hidden') && el.textContent.startsWith(h); }, head, { timeout: 15000 });
      const fwdNow = () => page.evaluate(() => { const p = window.tto.state.page, f = p.fwd; return { title: document.querySelector('#blotter-entry-title').textContent,
        note: document.querySelector('#blotter-copy-note').textContent, editing: !!p.editing, tab: p.tab, dir: f.dir, pair: f.pair, amount: f.amount.value, typed: f.typed,
        date: f.date.value, basis: f.basis, manual: f.manual.value, cpt: f.cpt.value }; });
      const oisNow = () => page.evaluate(() => { const p = window.tto.state.page, o = p.ois; return { title: document.querySelector('#blotter-entry-title').textContent,
        note: document.querySelector('#blotter-copy-note').textContent, editing: !!p.editing, tab: p.tab, strategy: o.strategy, side: o.side, level: o.level.value,
        size: o.size.value, sizeMode: o.sizeMode, tenors: ['tenor', 'short', 'long'].filter((k) => o.f[k]).map((k) => o.f[k].value), cpt: o.cpt.value, note2: o.note.value }; });
      const saveForm = async (n) => {
        await page.click('.entry .pad:not(.hidden) .row.actions .btn.primary');
        await page.waitForFunction((x) => window.tto.state.page.data.trades.length === x, n, { timeout: 15000 });
      };
      const before = await listedNow();
      const f0 = before.find((t) => t.kind === 'fwd');                 // (the forward list's first row)
      // a forward of today: "Benzerini gir" - its pair, side, amount as typed, value date, pricing, counterparty; no edit
      await page.click('.lists .panel:nth-child(1) table.grid td.act button[data-act="copy"]');
      await copyShown('Benzeri: ');
      const fSame = await fwdNow();
      check('"Benzerini gir" on today\'s forward fills the form as a new trade (not an edit): its pair, side, amount, value date, pricing, counterparty',
        fSame.title === 'Yeni işlem' && !fSame.editing && fSame.tab === 'fwd' && fSame.dir === f0.dir && fSame.pair === (f0.pair || 'USDTRY')
        && trNumber(fSame.amount) === f0.amount && fSame.date === serialText(f0.value_date) && fSame.basis === f0.basis && fSame.cpt === (f0.cpt || '')
        && /Aynı valör/.test(fSame.note), [fSame, f0]);
      await saveForm(before.length + 1);
      const fNew = (await listedNow()).filter((t) => t.kind === 'fwd').sort((x, y) => y.id - x.id)[0];
      const noteGone = await page.evaluate(() => document.querySelector('#blotter-copy-note').classList.contains('hidden'));
      check('... saved: a new trade with the same terms (pair, side, amount, value date, pricing, counterparty), the line over the form gone',
        fNew.id > f0.id && fNew.dir === f0.dir && fNew.amount === f0.amount && fNew.value_date === f0.value_date && fNew.basis === f0.basis
        && (fNew.pair || 'USDTRY') === (f0.pair || 'USDTRY') && fNew.cpt === (f0.cpt || '') && noteGone, [fNew, f0]);
      await api(page, ME, 'DELETE', '/api/blotter/trade/' + fNew.id);
      await page.waitForFunction((x) => window.tto.state.page.data.trades.length === x, before.length, { timeout: 15000 });
      // "Ters işlem": the other side, the same amount and value date
      await page.click('.lists .panel:nth-child(1) table.grid td.act button[data-act="reverse"]');
      await copyShown('Ters işlem: ');
      const fRev = await fwdNow();
      await saveForm(before.length + 1);
      const fBack = (await listedNow()).filter((t) => t.kind === 'fwd').sort((x, y) => y.id - x.id)[0];
      check('"Ters işlem" on the forward: the other side, the same amount and value date - saved as a new trade',
        !fRev.editing && fRev.dir === (f0.dir === 'B' ? 'S' : 'B') && trNumber(fRev.amount) === f0.amount && fRev.date === serialText(f0.value_date)
        && fBack.dir === fRev.dir && fBack.amount === f0.amount && fBack.value_date === f0.value_date && fBack.id !== f0.id, [fRev, fBack, f0]);
      await api(page, ME, 'DELETE', '/api/blotter/trade/' + fBack.id);
      await page.waitForFunction((x) => window.tto.state.page.data.trades.length === x, before.length, { timeout: 15000 });
      // the spread of today: "Ters işlem" - the other side, its tenors; no level (today's market: the mid offered)
      await page.evaluate(() => { const tr = [...document.querySelectorAll('.lists .panel:nth-child(2) table.grid tr')].find((x) => /FLATTENER 1Y\/2Y/.test(x.textContent));
        tr.querySelector('td.act button[data-act="reverse"]').click(); });
      await copyShown('Ters işlem: FLATTENER 1Y/2Y');
      await page.waitForFunction(() => /Piyasa mid/.test(window.tto.state.page.ois.marketHint.textContent), null, { timeout: 15000 });
      const sRev = await oisNow();
      check('"Ters işlem" on today\'s spread: STEEPENER on the same tenors, no level - the form offers today\'s mid',
        sRev.strategy === 'spread' && sRev.side === 'STEEPENER' && JSON.stringify(sRev.tenors) === '["1Y","2Y"]' && sRev.level === '' && !sRev.editing, sRev);
      // a day gone by's OIS (tests/test_e2e.py: PAY 1Y, 45 days back), listed in a period up to today - the form open
      const pastDay = process.env.TTO_E2E_PAST_DAY;
      const today = await page.evaluate(() => window.tto.state.page.data.today);
      await page.evaluate(([a, z]) => window.tto.state.page.show(a, z), [pastDay, today]);
      await page.waitForFunction((a) => { const d = window.tto.state.page.data; return d && d.ranged && d.date === a && d.can_enter; }, pastDay, { timeout: 20000 });
      const ranged = await listedNow('?date=' + pastDay + '&to=' + today);
      const old = ranged.find((t) => t.note === 'e2e geçmiş');
      const clickOld = (act) => page.evaluate(([a]) => { const tr = [...document.querySelectorAll('.lists .panel:nth-child(2) table.grid tr')].find((x) => x.textContent.includes('e2e geçmiş'));
        tr.querySelector('td.act button[data-act="' + a + '"]').click(); }, [act]);
      await clickOld('copy');
      await copyShown('Benzeri: PAY 1Y @ 38,0000%');
      const oSame = await oisNow();
      check('"Benzerini gir" on a day gone by\'s 1Y: the same tenor from today\'s spot - PAY 1Y, its nominal, counterparty and note',
        oSame.strategy === 'outright' && oSame.side === 'PAY' && JSON.stringify(oSame.tenors) === '["1Y"]' && oSame.sizeMode === 'nominal'
        && trNumber(oSame.size) === 150e6 && oSame.cpt === 'E2E ESKİ' && oSame.note2 === 'e2e geçmiş' && oSame.note.includes('(' + pastDay.split('-').reverse().join('.') + ')'), oSame);
      await clickOld('reverse');
      await copyShown('Ters işlem: PAY 1Y @ 38,0000%');
      await page.waitForFunction(() => !!window.tto.state.page.ois.marketHint.querySelector('button'), null, { timeout: 15000 });
      const oRev = await oisNow();
      const end = old.copy.ters.spec.tenors[0];
      const [dd, mm, yyyy] = end.split('.').map(Number);
      const [py, pm, pd] = pastDay.split('-').map(Number);
      const yearOn = (Date.UTC(yyyy, mm - 1, dd) - Date.UTC(py + 1, pm - 1, pd)) / 86400000;            // (its spot, then a business day)
      check('"Ters işlem" on it: RECEIVE to its own maturity (a broken date, 1Y from that day\'s spot), the same nominal, no level',
        oRev.strategy === 'outright' && oRev.side === 'RECEIVE' && JSON.stringify(oRev.tenors) === JSON.stringify([end]) && yearOn >= 1 && yearOn <= 6
        && trNumber(oRev.size) === 150e6 && oRev.level === '' && /kırık vade/.test(oRev.note), [oRev, end, yearOn]);
      // priced on today's market: at its mid, the leg the broken date - then saved: a new trade, the old one as it was
      const brokenMid = (await api(page, ME, 'POST', '/api/blotter/quote/ois', { strategy: 'outright', side: 'RECEIVE', tenor: end, level: '0' })).json.info.market;
      const midText = (brokenMid * 100).toFixed(4).replace('.', ',');
      await page.fill('.entry .pad:not(.hidden) input[placeholder="örn. 37,25"]', midText);
      await page.waitForFunction((l) => { const q = document.querySelector('.entry .pad:not(.hidden) .quotebox'); return q && q.textContent.includes(l) && !!q.querySelector('[data-k="vs-mid-bp"]'); },
        'RECEIVE ' + end + ' @ ' + midText + '%', { timeout: 15000 });
      const vsMidText = await page.evaluate(() => document.querySelector('.entry .pad:not(.hidden) .quotebox [data-k="vs-mid-bp"] .v').textContent);
      await saveForm(ranged.length + 1);
      const oNew = (await listedNow()).filter((t) => t.kind === 'ois').sort((x, y) => y.id - x.id)[0];
      const oldAfter = (await listedNow('?date=' + pastDay + '&to=' + today)).find((t) => t.id === old.id);
      const strip = (t) => JSON.stringify(Object.keys(t).filter((k) => k !== 'copy').sort().map((k) => [k, t[k]]));
      check('... at today\'s mid ("Mid\'e göre" 0) saved as today\'s trade: RECEIVE to that date, the same nominal - the day gone by\'s trade unchanged',
        oNew.tenor === end && oNew.dir === 'S' && oNew.nominal === 150e6 && oNew.trade_date === today && /^[-+]?0,00/.test(vsMidText)
        && strip(oldAfter) === strip(old), [oNew, vsMidText]);
      await api(page, ME, 'DELETE', '/api/blotter/trade/' + oNew.id);
      await page.click('#blotter-today');
      await page.waitForFunction((n) => { const d = window.tto.state.page.data; return d && d.is_today && d.trades.length === n; }, before.length, { timeout: 20000 });
    }

    // ------------------------------------------------------------------ a period's summary tables (islem-kopya, the desk:
    // "daha fazla tarihe bakarken bugündeki alttaki tablo gelmiyor") - the workbook's own tables over the trades shown
    {
      const ME = 'ayşe yilmaz';
      const pastDay = process.env.TTO_E2E_PAST_DAY;
      const today = await page.evaluate(() => window.tto.state.page.data.today);
      const payDv01 = (sheet, tenor) => {               // the OIS summary's "Pay DV01" (S) of a tenor
        const d = (sheet.find((p) => p.id === 'ois') || {}).data;
        if (!d) return null;
        const i = d.rows.findIndex((r) => r[d.c.indexOf('P')] && r[d.c.indexOf('P')].t === tenor);
        return i < 0 ? null : d.rows[i][d.c.indexOf('S')].v;
      };
      const todaySheet = (await api(page, ME, 'GET', '/api/blotter')).json.sheet;
      await page.evaluate(([a, z]) => window.tto.state.page.show(a, z), [pastDay, today]);
      await page.waitForFunction((a) => { const d = window.tto.state.page.data; return d && d.ranged && d.date === a; }, pastDay, { timeout: 20000 });
      await page.waitForFunction(() => !document.querySelector('#blotter-sheet-scope').classList.contains('hidden')
        && document.querySelectorAll('#content .panels .panel table.grid').length >= 4, null, { timeout: 20000 });
      const per = (await api(page, ME, 'GET', '/api/blotter?date=' + pastDay + '&to=' + today)).json;
      const shown = await page.evaluate(() => ({ scope: document.querySelector('#blotter-sheet-scope').textContent,
        title: !document.querySelector('#blotter-sheet-note').parentElement.classList.contains('hidden'),
        panels: [...document.querySelectorAll('#content .panels .panel h2')].map((x) => x.textContent),
        cost: [...document.querySelectorAll('.lists .panel:nth-child(5) table.grid tr')].map((tr) => tr.children[0].textContent) }));
      check('a period shows the workbook\'s summary tables under the lists, over its trades: the OIS summary\'s 1Y pays the day gone by\'s 1Y (3.500 $) beside today\'s, said over them',
        shown.title && shown.panels.length === 4 && /^Aralık /.test(shown.scope) && shown.scope.includes(per.trades.length + ' işlemin hepsi')
        && Math.abs(payDv01(per.sheet, '1Y') - payDv01(todaySheet, '1Y') - 3500) < 1e-6 && shown.cost.includes('1Y'), [shown, payDv01(per.sheet, '1Y'), payDv01(todaySheet, '1Y')]);
      // a day gone by on its own, with no archive (it was never today here): its own trade's tables, said so
      await page.evaluate((a) => window.tto.state.page.show(a, null), pastDay);
      await page.waitForFunction((a) => { const d = window.tto.state.page.data; return d && !d.ranged && d.date === a; }, pastDay, { timeout: 20000 });
      const one = (await api(page, ME, 'GET', '/api/blotter?date=' + pastDay)).json;
      const oneScope = await page.evaluate(() => document.querySelector('#blotter-sheet-scope').textContent);
      check('... a day gone by without its archive: the tables of its own trades (1Y pays 3.500 $), "gün sonu arşivi yok" said',
        payDv01(one.sheet, '1Y') === 3500 && /gün sonu arşivi yok - günün 1 işlemiyle/.test(oneScope), [oneScope, payDv01(one.sheet, '1Y')]);
      await page.click('#blotter-today');
      await page.waitForFunction(() => { const d = window.tto.state.page.data; return d && d.is_today; }, null, { timeout: 20000 });
      check('... today again: the sheet\'s own tables, nothing said over them',
        await page.evaluate(() => document.querySelector('#blotter-sheet-scope').classList.contains('hidden')));
    }

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
    await page.click('.lists .panel:nth-child(1) table.grid td.act button[data-act="del"]');
    await page.waitForSelector('.modal .mfoot .btn.primary');
    await page.click('.modal .mfoot .btn.primary');
    await pageB.waitForFunction(() => document.querySelectorAll('.lists .panel:nth-child(1) table.grid tr').length === 2, null, { timeout: 15000 });
    check('deleting a trade updates the other user\'s screen live', true);

    // who is online (tto/presence.py): the top bar's chip opens the desk's users - both signed in, each sees the other
    // online; Mehmet signs out and Ayşe's open list shows him offline at once, with when he was last seen
    await page.waitForSelector('#presence-chip:not(.hidden)', { timeout: 15000 });
    await pageB.waitForSelector('#presence-chip:not(.hidden)', { timeout: 15000 });
    await page.click('#presence-chip');
    await pageB.click('#presence-chip');
    const onlineRow = (p, user) => p.waitForSelector('#presence-list tr[data-user="' + user + '"][data-state="online"]', { timeout: 20000 })
      .then(() => true, () => false);
    const seesMehmet = await onlineRow(page, 'mehmet');
    const seesAyse = await onlineRow(pageB, 'ayşe yilmaz');
    const presenceRows = (p) => p.evaluate(() => ({ n: document.getElementById('presence-n').textContent,
      rows: [...document.querySelectorAll('#presence-list tr[data-user]')].map((r) => [r.dataset.user, r.dataset.state,
        r.querySelector('.pr-seen').textContent, r.querySelector('.pr-login').textContent, r.classList.contains('me')]) }));
    const prA = await presenceRows(page);
    const prB = await presenceRows(pageB);
    const prNames = prA.rows.map((r) => r[0]);
    check('who is online: two users signed in see each other online in the top bar chip\'s list (last seen "şimdi", a last login)',
      seesMehmet && seesAyse && +prA.n >= 2 && +prB.n >= 2 && ['ayşe yilmaz', 'mehmet', 'zeynep'].every((u) => prNames.includes(u))
      && prA.rows.some((r) => r[0] === 'ayşe yilmaz' && r[4]) && prB.rows.some((r) => r[0] === 'mehmet' && r[4])
      && prA.rows.filter((r) => r[1] === 'online').every((r) => r[2] === 'şimdi' && r[3] !== '—'), { prA, prB });
    await shot(page, '05-presence');
    await pageB.click('#btn-user');
    await pageB.click('.menu >> text=Çıkış');
    await pageB.waitForSelector('#login:not(.hidden)');
    const signedOut = await page.waitForSelector('#presence-list tr[data-user="mehmet"][data-state="offline"]', { timeout: 20000 })
      .then(() => page.evaluate(() => {
        const r = document.querySelector('#presence-list tr[data-user="mehmet"]');
        return { state: r.querySelector('.pr-state').textContent, seen: r.querySelector('.pr-seen').textContent };
      }), () => null);
    check('... Mehmet signs out: offline in Ayşe\'s open list at once, with a "son görülme"', !!signedOut
      && signedOut.state === 'çevrimdışı' && /^(şimdi|\d+ dk önce)$/.test(signedOut.seen), signedOut);
    await page.click('#presence-chip');                               // (the list closes)
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
    // a user who hides the "kimde" columns has the name of an instrument's single broker nowhere else: "Brokerlar" gives
    // that broker its own row too (at once); the columns shown again, the board is as it was
    const houseRows = () => page.evaluate(() => [...document.querySelectorAll('#broker-board-panel table.grid tr')]
      .filter((tr) => tr.children[1] && /^↳ /.test(tr.children[1].textContent)).length);
    const boardCols = (show) => page.evaluate((sh) => document.querySelector('#broker-board-panel table.grid').__grid.columns
      .change(['Bid · kimde', 'Ask · kimde'], sh), show);
    const housesBefore = await houseRows();
    const singles = (await brokerBoard()).filter((r, i, all) => !/^↳ /.test(r[1]) && !/^↳ /.test((all[i + 1] || [])[1] || '') && / · /.test(r[4] || r[6] || '')).length;
    await boardCols(false);
    const housesGrew = await page.waitForFunction((n) => [...document.querySelectorAll('#broker-board-panel table.grid tr')]
      .filter((tr) => tr.children[1] && /^↳ /.test(tr.children[1].textContent)).length === n, housesBefore + singles, { timeout: 15000 }).then(() => true, () => false);
    const housesHidden = await houseRows();
    await boardCols(true);
    const housesBack = await page.waitForFunction((n) => [...document.querySelectorAll('#broker-board-panel table.grid tr')]
      .filter((tr) => tr.children[1] && /^↳ /.test(tr.children[1].textContent)).length === n, housesBefore, { timeout: 15000 }).then(() => true, () => false);
    check('"kimde" columns hidden: "Brokerlar" gives each single broker its own row too; shown again, the board is as it was',
      singles > 0 && housesGrew && housesBack, { housesBefore, singles, housesHidden, after: await houseRows() });

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

    // ------------------------------------------------------------------ blotter: an amount in TRY, templates, rows pasted from Excel
    console.log('blotter: an amount in the second currency, templates, Excel paste');
    const trInt = (x) => Math.abs(x).toFixed(0).replace(/\B(?=(\d{3})+(?!\d))/g, '.');
    const trAmt = (x) => { const [i, d] = Math.abs(x).toFixed(2).split('.'); return i.replace(/\B(?=(\d{3})+(?!\d))/g, '.') + ',' + d; };
    const typedSide = () => page.evaluate(() => ['fwd-amount-field', 'fwd-quote-field'].map((id) => document.getElementById(id).className).join('|'));
    await page.click('.entry .tabs button:nth-child(1)');
    await page.click('#fwd-pair button[data-v="USDTRY"]');
    await page.click('.entry .pad:not(.hidden) .seg button[data-v="S"]');
    await page.click('.entry .pad:not(.hidden) .seg button[data-v="RET_MID"]');
    await page.fill('.form input[placeholder="gg.aa.yyyy"]', '15.12.2026');
    await page.fill('#fwd-quote-amount', '520m');
    const tryQ = (await api(page, 'ayşe yilmaz', 'POST', '/api/blotter/quote/forward', { value_date: '15.12.2026', basis: 'RET_MID', quote_amount: 520000000 })).json;
    await page.waitForFunction((want) => document.getElementById('fwd-amount').value === want, trInt(tryQ.amount), { timeout: 20000 });
    const tryTotal = await page.evaluate(() => { const q = document.querySelector('.entry .pad:not(.hidden) .quotebox [data-k="fwd-total"]'); return q ? [q.className, q.querySelector('.v').textContent] : null; });
    check('a USDTRY forward typed in TRY: the USD from the deal\'s forward to the dollar, the TRY marked as the one typed',
      tryQ.typed === 'quote' && tryQ.tl === 520e6 && Math.abs(tryQ.amount - 520e6 / tryQ.forward) < 0.006
      && /typed/.test((await typedSide()).split('|')[1]) && /calc/.test((await typedSide()).split('|')[0])
      && tryTotal && /typed/.test(tryTotal[0]) && tryTotal[1] === '520.000.000,00', [tryQ, await typedSide(), tryTotal]);
    const fxCount = (await fxRows()).length;
    await page.click('.entry .pad:not(.hidden) .row.actions .btn.primary');
    await page.waitForFunction((n) => document.querySelectorAll('.lists .panel:nth-child(1) table.grid tr').length === Math.max(n, 1) + 1, fxCount, { timeout: 15000 });
    const tryList = await fxRows();
    const tryRow = tryList[tryList.length - 1];
    const tryKept = (await api(page, 'ayşe yilmaz', 'GET', '/api/blotter')).json.trades.filter((t) => t.kind === 'fwd').pop();
    const typedMarked = await page.evaluate(() => { const rows = document.querySelectorAll('.lists .panel:nth-child(1) table.grid tr'); return [...rows[rows.length - 1].children].map((td) => td.className).join('|'); });
    check('... kept as a USD trade, the TRY typed beside it and marked in the list',
      tryKept.typed === 'quote' && tryKept.typed_amount === 520e6 && tryKept.amount === tryQ.amount && tryRow[tryList[0].indexOf('Tutar (döviz)')] === trInt(tryQ.amount)
      && tryRow[tryList[0].indexOf('Karşı tutar')] === '520.000.000,00' && /typed/.test(typedMarked.split('|')[tryList[0].indexOf('Karşı tutar')]), [tryKept, tryRow, typedMarked]);
    // typed in USD again: the TRY is the one worked out
    await page.fill('#fwd-amount', '10m');
    const usdQ = (await api(page, 'ayşe yilmaz', 'POST', '/api/blotter/quote/forward', { value_date: '15.12.2026', basis: 'RET_MID', amount: 10000000 })).json;
    await page.waitForFunction((want) => document.getElementById('fwd-quote-amount').value === want, trAmt(usdQ.tl), { timeout: 20000 });
    check('... typed in USD the TRY follows, and the mark moves', /typed/.test((await typedSide()).split('|')[0]) && /calc/.test((await typedSide()).split('|')[1]), await typedSide());

    // a template: what is on the form, any of its fields; one click fills the form again (nothing is saved)
    await page.click('#fwd-pair button[data-v="EURTRY"]');
    await page.fill('#fwd-quote-amount', '300m');
    await page.fill('.form input[placeholder="gg.aa.yyyy"]', '3M');
    await page.fill('.entry .pad:not(.hidden) input[placeholder="opsiyonel"]', 'GARANTI');
    await page.click('#tpl-save');
    await page.waitForSelector('#tpl-dialog');
    const tplParts = await page.evaluate(() => [...document.querySelectorAll('#tpl-parts input')].map((x) => x.dataset.part + (x.checked ? '+' : '-') + (x.disabled ? 'x' : '')).join(','));
    await page.fill('#tpl-name', 'E2E Garanti EUR 3A');
    await page.click('#tpl-ok');
    await page.waitForSelector('#blotter-templates .chip');
    const tplMine = (await api(page, 'ayşe yilmaz', 'GET', '/api/blotter/templates')).json.templates.find((t) => t.name === 'E2E Garanti EUR 3A') || {};
    check('"Şablon olarak kaydet": the fields on the form ticked (the note left out), kept as one\'s own',
      /^pair\+,dir\+,amount\+,date\+,basis\+,spot-x,cpt\+,note-/.test(tplParts) && !tplMine.shared
      && JSON.stringify(Object.entries(tplMine.spec || {}).sort()) === JSON.stringify(Object.entries({ kind: 'fwd', pair: 'EURTRY', dir: 'S', quote_amount: '300m', date: '3M',
        basis: 'RET_MID', cpt: 'GARANTI' }).sort()),
      [tplParts, tplMine]);
    await page.click('#fwd-pair button[data-v="USDTRY"]');
    await page.click('.entry .pad:not(.hidden) .seg button[data-v="B"]');
    await page.fill('#fwd-amount', '1m');
    await page.fill('.form input[placeholder="gg.aa.yyyy"]', '15.12.2026');
    await page.fill('.entry .pad:not(.hidden) input[placeholder="opsiyonel"]', '');
    const listBefore = (await fxRows()).length;
    await page.click('#blotter-templates .chip:has-text("E2E Garanti EUR 3A")');
    const tplFilled = await page.evaluate(() => { const f = window.tto.state.page.fwd; return [f.pair, f.dir, f.typed, f.quoteAmount.value, f.date.value, f.cpt.value, f.basis]; });
    await page.waitForFunction(() => /\d/.test(document.getElementById('fwd-amount').value), null, { timeout: 20000 });
    check('... a click on it fills the form - EURTRY, sold, 300m TRY typed, 3M, GARANTI - and saves nothing',
      JSON.stringify(tplFilled) === JSON.stringify(['EURTRY', 'S', 'quote', '300m', '3M', 'GARANTI', 'RET_MID']) && (await fxRows()).length === listBefore
      && /Tutar \(EUR\)/.test(await page.textContent('#fwd-amount-field')), tplFilled);
    // the desk's templates are an administrator's to publish; one's own is nobody else's
    await api(page, 'ayşe yilmaz', 'POST', '/api/blotter/templates', { name: 'E2E masa 1Y', kind: 'ois', spec: { strategy: 'outright', side: 'PAY', tenors: ['1Y'] }, shared: true });
    const theirs = (await api(page, 'mehmet', 'GET', '/api/blotter/templates')).json;
    const refused = await api(page, 'mehmet', 'POST', '/api/blotter/templates', { name: 'x', kind: 'fwd', spec: { dir: 'B' }, shared: true });
    check('... a user sees the desk\'s templates and not another\'s own, and cannot publish to the desk',
      theirs.templates.map((t) => t.name).join('|') === 'E2E masa 1Y' && !theirs.can_publish && refused.status === 403, [theirs, refused.status]);

    // rows copied from Excel: each checked as the form checks it, the valid ones kept together, the bad one left to fix
    const fxBefore2 = (await fxRows()).length;
    await page.click('#bulk-open');
    await page.waitForSelector('#bulk-dialog');
    await page.click('#bulk-kind button[data-v="fwd"]');
    await page.fill('#bulk-text', 'Yön\tTutar\tFaiz\tValör\nB\t3.000.000\t36,50%\t15.12.2026\nS\t2.000.000\t36,00%\t32.13.2026\nB\t1m\t36,25\t15.01.2027');
    await page.waitForFunction(() => document.querySelectorAll('#bulk-preview tr.line').length === 3, null, { timeout: 20000 });
    const bulkRows = await page.evaluate(() => [...document.querySelectorAll('#bulk-preview tr.line')].map((tr) => [tr.dataset.n, tr.className, tr.querySelector('td.st').textContent]));
    const bulkMap = await page.evaluate(() => [...document.querySelectorAll('#bulk-preview tr.map select')].map((s) => s.value).join(','));
    await shot(page, '04d-blotter-bulk');
    check('Excel paste: the header read, each row checked - the bad one says why - and "2 satırı kaydet"',
      bulkMap === 'dir,amount,try_rate,value_date' && await page.isChecked('#bulk-header') && bulkRows.map((r) => r[0]).join() === '2,3,4'
      && /good/.test(bulkRows[0][1]) && /bad/.test(bulkRows[1][1]) && /good/.test(bulkRows[2][1]) && /valör tarihi anlaşılamadı/.test(bulkRows[1][2])
      && /^✓ USDTRY alış 3\.000\.000 USD/.test(bulkRows[0][2]) && (await page.textContent('#bulk-save')) === '2 satırı kaydet', [bulkMap, bulkRows]);
    await page.click('#bulk-save');
    await page.waitForFunction((n) => document.querySelectorAll('.lists .panel:nth-child(1) table.grid tr').length === n + 2, fxBefore2, { timeout: 20000 });
    await page.waitForFunction(() => document.querySelectorAll('#bulk-preview tr.line').length === 1, null, { timeout: 20000 });
    const leftText = await page.inputValue('#bulk-text');
    const bulkAdded = (await fxRows()).slice(-2);
    const amountCol = (await fxRows())[0].indexOf('Tutar (döviz)');
    check('... the two good rows saved in one go, the bad one left in the box under its header',
      leftText === 'Yön\tTutar\tFaiz\tValör\nS\t2.000.000\t36,00%\t32.13.2026' && bulkAdded.map((r) => r[amountCol]).join('|') === '3.000.000|1.000.000', [leftText, bulkAdded]);
    await page.keyboard.press('Escape');
    await page.waitForSelector('#bulk-dialog', { state: 'detached' });

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
    // ------------------------------------------------------------------ a value date as the desk says it, the quote to send
    // "1A" in the free row's value date: one month from the USDTRY spot date - the 1M row's own date - is stored, and
    // the cell's tooltip says what was typed
    const b5 = (await cellText(page, 'EK_FWD!B5')).trim();
    await typeInto(page, 'EK_FWD!B11', '1A');
    await waitCell(page, 'EK_FWD!B11', 't.trim() === ' + JSON.stringify(b5));
    await page.waitForFunction(() => /Kısayol: 1A → /.test(window.tto.findCell('EK_FWD!B11').title || ''), null, { timeout: 10000 }).catch(() => {});
    const tip11 = await page.evaluate(() => window.tto.findCell('EK_FWD!B11').title);
    check('"1A" typed in a value-date input is the date a month from the spot date (the 1M row\'s own), the tooltip says what was typed',
      tip11.includes('Kısayol: 1A → ' + b5), { b5, tip11 });
    // "Kotasyon kopyala" on the desk's USDTRY forward table: Turkish - the pair, the date, bid / ask, the spot date and the
    // spot, then a caption line and a line for every priced row (the free row typed just now too)
    const b5n = await page.evaluate(() => window.tto.findCell('EK_FWD!H5').textContent.trim());
    const kq = (await clipAfter(page, () => page.click('.panel[data-panel="EKS"] button[data-action="kotasyon"]'))).split('\n');
    const kq1 = kq.find((l) => l.startsWith('1M ')) || '';
    check('"Kotasyon kopyala" on a forward table: the quote in Turkish on the clipboard, a line a priced row with its points, outright and rates',
      /^USDTRY forward · \d\d\.\d\d\.\d{4} · bid \/ ask$/.test(kq[0]) && /^Başlangıç\s+\d\d\.\d\d\.\d{4}$/.test(kq[1]) && /^Spot\s+\d+,\d{4} \/ \d+,\d{4}$/.test(kq[2])
      && kq.some((l) => /^Vade\s+Vade tarihi\s+Gün\s+Swap puanı\s+Outright\s+TRY faizi %\s+USD faizi %$/.test(l)) && kq1.includes(b5) && kq1.includes(b5n)
      && kq.filter((l) => /^(\d+M|\d\d\.\d\d\.\d{4})\s/.test(l)).length === 7 && kq.some((l) => l.startsWith(b5 + ' ')), { kq, b5, b5n });
    // its menu: English (remembered), then a row on its own by a right click
    const ke = (await clipAfter(page, async () => {
      await page.click('.panel[data-panel="EKS"] button[data-action="kotasyon-menu"]');
      await page.click('.menu button:has-text("English")');
    })).split('\n');
    check('... in English from its menu: dates as 04 Dec 2026, numbers as 51.2633, captions in English',
      /^USDTRY forward · \d\d [A-Z][a-z]{2} \d{4} · bid \/ ask$/.test(ke[0]) && ke.some((l) => /^Tenor\s+Maturity\s+Days\s+Swap points/.test(l))
      && /\d+\.\d{4} \/ \d+\.\d{4}/.test(ke.find((l) => l.startsWith('1M ')) || ''), ke);
    const k2 = (await clipAfter(page, async () => {
      await (await cellHandle(page, 'EK_FWD!H6')).click({ button: 'right' });
      await page.click('.menu button:has-text("Bu satırın kotasyonu")');
    })).split('\n');
    check('... a row\'s own quote from the right-click menu (2M, the language kept): a line a field',
      /^USDTRY forward 2M · \d\d [A-Z][a-z]{2} \d{4} · bid \/ ask$/.test(k2[0]) && k2.some((l) => /^Maturity\s+\d\d [A-Z][a-z]{2} \d{4} \(\d+ days\)$/.test(l))
      && k2.some((l) => /^Swap points\s+[\d,]+ \/ [\d,]+$/.test(l)), k2);
    await page.click('.panel[data-panel="EKS"] button[data-action="kotasyon-menu"]');
    await page.click('.menu button:has-text("Türkçe")');                       // (back to Turkish: it copies too)
    await page.waitForTimeout(300);
    await api(page, 'ayşe yilmaz', 'POST', '/api/reset', { book: 'tto', refs: ['EK_FWD!B11'] });
    await waitCell(page, 'EK_FWD!B11', 't.trim() === ""');
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
    // the interpolation chart beside the FRA lists: the overnight forward and the 3M FRA strip both ways as step lines
    // (Bootstrap - Murex's -, PPK basamak), the quoted tenors and the meetings marked, the strip's table under it; 1Y / 3Y /
    // 10Y and OIS / Offshore redraw it at once, the choice kept in the browser
    const interp = () => page.evaluate(() => {
      const p = document.querySelector('.panel[data-panel="interp"]');
      const svg = p.querySelector('svg.chart');
      const paths = [...svg.querySelectorAll('path[fill="none"]')];
      return { keys: [...p.querySelectorAll('.chart-legend .key')].map((k) => k.textContent), full: p.classList.contains('full'),
        on: [...p.querySelectorAll('#chart-choice-interp button.on')].map((b) => b.textContent),
        steps: paths.filter((x) => / H[\d.]+ V[\d.]+/.test(x.getAttribute('d'))).length, dashed: svg.querySelectorAll('path[stroke-dasharray]').length,
        strokes: [...new Set(paths.map((x) => x.style.stroke))], quotes: [...svg.querySelectorAll('text.vlab')].map((t) => t.textContent),
        lines: svg.querySelectorAll('line.vline').length, ticks: svg.querySelectorAll('line.vtick').length, line: p.querySelector('.chart-line').textContent,
        rows: [...p.querySelectorAll('.chart-strip table.grid tr')].map((tr) => [...tr.children].map((td) => td.textContent.trim())) };
    });
    const stripCols = (n) => page.waitForFunction((k) => document.querySelectorAll('.panel[data-panel="interp"] .chart-strip tr:first-child > *').length === k,
      n, { timeout: 15000 });
    const i0 = await interp();
    const b21 = (await api(page, 'ayşe yilmaz', 'GET', '/api/view/ois')).json.panels.find((x) => x.id === 'B21').data;
    const listFark = (label) => { const r = b21.rows.find((row) => row[0] && row[0].t === label); return r ? r[b21.c.indexOf('PPK fark')].t : null; };
    check('OIS · PPK: the interpolation chart right after the 15 best FRAs, the page\'s whole width - the overnight forward and the 3M FRA strip both ways as step lines (Bootstrap blue, PPK basamak orange, the strips dashed), 3Y OIS first',
      bestTab.join(' ') === 'B1 B9 B10 B11 interp chart2 chart5' && i0.full && i0.on.join() === '3Y,OIS,Faiz'
      && JSON.stringify(i0.keys) === JSON.stringify(['O/N · Bootstrap (Murex)', 'O/N · PPK basamak', '3A FRA · Bootstrap (Murex)', '3A FRA · PPK basamak'])
      && i0.steps === 4 && i0.dashed === 2 && i0.strokes.includes('var(--c-blue)') && i0.strokes.includes('var(--c-orange)'), { bestTab, i0 });
    check('... the quoted tenors as light lines with their names (1M … 3Y: 15M and 21M are no quotes), the meetings as ticks on the axis',
      i0.lines === 9 && ['6M', '9M', '1Y', '18M', '2Y', '3Y'].every((t) => i0.quotes.includes(t)) && !i0.quotes.includes('15M')
      && !i0.quotes.includes('21M') && i0.ticks >= 20, [i0.lines, i0.quotes, i0.ticks]);
    check('... the strip under it, an FRA a column: Bootstrap and PPK basamak (%), PPK − Bootstrap (bp) - the FRA list\'s own "PPK fark" (12x15 = 1Y3M, 15x18 = 15M3M); the same both ways up to 9x12 (both ends quoted)',
      i0.rows.length === 4 && i0.rows[0].length === 13 && i0.rows[0][1] === '0x3' && i0.rows[0][12] === '33x36'
      && JSON.stringify(i0.rows.slice(1).map((r) => r[0])) === JSON.stringify(['Bootstrap (Murex)', 'PPK basamak', 'PPK − Bootstrap (bp)'])
      && i0.rows[3].slice(1, 5).every((t) => t === '0,0') && i0.rows[3][5] === listFark('1Y3M') && i0.rows[3][6] === listFark('15M3M')
      && /^3Y · OIS · 3A FRA farkı \(PPK basamak − Bootstrap\): en çok /.test(i0.line), { rows: i0.rows, line: i0.line, list: [listFark('1Y3M'), listFark('15M3M')] });
    await page.click('#chart-choice-interp button[data-pick="1Y"]');
    await stripCols(5);
    const i1 = await interp();
    await page.click('#chart-choice-interp button[data-pick="Offshore"]');
    await page.waitForFunction(() => /offshore/.test(document.querySelector('.panel[data-panel="interp"] .chart-legend').textContent), null, { timeout: 15000 });
    const i2 = await interp();
    await page.click('#chart-choice-interp button[data-pick="10Y"]');
    await stripCols(41);
    const i3 = await interp();
    const keptPick = await page.evaluate(() => localStorage.getItem('tto.pick.ois.interp'));
    check('... 1Y / 3Y / 10Y and OIS / Offshore redraw it at once: 1Y four FRAs, all the same both ways (3M, 6M, 9M, 1Y are quotes); Offshore the offshore curve both ways (FX swap + XCCY, 3M forwards on ACT/360); 10Y forty quarters; the choice kept in the browser',
      i1.on.join() === '1Y,OIS,Faiz' && i1.rows[0].length === 5 && i1.rows[3].slice(1).every((t) => t === '0,0') && /her çeyrekte aynı/.test(i1.line)
      && i2.on.join() === '1Y,Offshore,Faiz' && i2.rows[0][0] === '3A forward (ACT/360)' && i2.quotes.includes('1W') && i2.steps === 4
      && JSON.stringify(i2.keys) === JSON.stringify(['O/N · Bootstrap (offshore)', 'O/N · PPK basamak (offshore)', '3A forward · Bootstrap (offshore)', '3A forward · PPK basamak (offshore)'])
      && i3.on.join() === '10Y,Offshore,Faiz' && i3.rows[0].length === 41 && i3.steps === 4 && keptPick === '10Y|Offshore|Faiz',
    { i1: [i1.on, i1.rows[3], i1.line], i2: [i2.on, i2.keys, i2.rows[0] && i2.rows[0][0], i2.quotes], i3: [i3.on, i3.rows[0] && i3.rows[0].length], keptPick });
    await page.click('#chart-choice-interp button[data-pick="3Y"]');
    await page.click('#chart-choice-interp button[data-pick="OIS"]');
    await stripCols(13);
    const isvg = page.locator('.panel[data-panel="interp"] svg.chart');
    await isvg.scrollIntoViewIfNeeded();
    const ib = await isvg.boundingBox();
    await page.mouse.move(ib.x + ib.width * 0.45, ib.y + ib.height * 0.5);
    await page.waitForSelector('.chart-tip');
    const itip = await page.evaluate(() => ({ head: document.querySelector('.chart-tip .t').textContent,
      rows: [...document.querySelectorAll('.chart-tip .r')].map((r) => r.textContent) }));
    await page.mouse.move(5, 5);
    check('... hovering it reads every line at that day: both O/N forwards, both FRAs (named: 12x15 …) and their differences in bp',
      /^\d\d\.\d\d\.\d{4}$/.test(itip.head) && itip.rows.filter((r) => /%$/.test(r)).length === 4 && itip.rows.filter((r) => / bp$/.test(r)).length === 2
      && itip.rows.some((r) => /^3A FRA · PPK basamak · \d+x\d+/.test(r)), itip);
    await shot(page, '09c-ois-interp');
    // the discount factors, the chart's third choice ("Bu enterpolasyondaki DF farkları da bir grafikte bana gösterilmeli"):
    // PPK basamak's DF against Bootstrap's day by day (bp), Bootstrap's own line at 0, the table of both at the quoted tenors
    await page.click('#chart-choice-interp button[data-pick="DF"]');
    await page.waitForFunction(() => /^DF · /.test((document.querySelector('.panel[data-panel="interp"] .chart-legend .key') || {}).textContent || ''),
      null, { timeout: 15000 });
    await stripCols(10);
    const i4 = await interp();
    const dfPick = await page.evaluate(() => localStorage.getItem('tto.pick.ois.interp'));
    const db = await isvg.boundingBox();
    await page.mouse.move(db.x + db.width * 0.45, db.y + db.height * 0.5);
    await page.waitForSelector('.chart-tip');
    const dtip = await page.evaluate(() => ({ head: document.querySelector('.chart-tip .t').textContent,
      rows: [...document.querySelectorAll('.chart-tip .r')].map((r) => r.textContent) }));
    await page.mouse.move(5, 5);
    check('... "DF" draws the discount factors instead: PPK basamak\'s against Bootstrap\'s (bp) day by day, Bootstrap\'s line at 0, the quoted tenors marked; the table both DFs and the difference at each quoted tenor - the same up to 1Y, apart at 18M, 2Y, 3Y; hovering reads that day\'s difference; the choice kept',
      i4.on.join() === '3Y,OIS,DF' && JSON.stringify(i4.keys) === JSON.stringify(['DF · Bootstrap (Murex)', 'DF · PPK basamak'])
      && i4.rows.length === 4 && i4.rows[0][0] === 'DF · kotalı vade' && i4.rows[0].slice(1).join() === '1M,2M,3M,6M,9M,1Y,18M,2Y,3Y'
      && i4.rows[3].slice(1, 7).every((t) => t === '0,00') && i4.rows[3].slice(7).every((t) => /\d/.test(t) && t !== '0,00')
      && /^3Y · OIS · DF farkı \(PPK basamak \/ Bootstrap − 1\): en yüksek /.test(i4.line) && i4.lines === 9 && dfPick === '3Y|OIS|DF'
      && /^\d\d\.\d\d\.\d{4}$/.test(dtip.head) && dtip.rows.some((r) => /^PPK \/ Bootstrap − 1.*\d bp$/.test(r)),
    { i4: [i4.on, i4.keys, i4.rows, i4.line, i4.lines], dfPick, dtip });
    await shot(page, '09d-ois-interp-df');
    await page.click('#chart-choice-interp button[data-pick="Faiz"]');
    await stripCols(13);
    await open(page, 'forward');
    await tab(page, 'kot');
    check('the forward quote matrices: USDTRY, EURTRY, then the ways back of each (by points, by a rate) - the Forward page\'s "Kotasyon" tab',
      await order(['EKF1', 'EKF5', 'EKF2', 'EKF8', 'EKF6', 'EKF9']));
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
    // the way back by a rate (FAİZ → SPREAD): the matrix's 1M bid TRY rate typed by hand reads its spread and its points
    const fzRate = (await cellText(page, 'EK_FWD!M5')).trim();
    const fzWant = { sp: trNumber(await cellText(page, 'EK_FWD!D5')), pts: trNumber(await cellText(page, 'EK_FWD!H5')), ois: trNumber(await cellText(page, 'EK_FWD!L5')) };
    await typeInto(page, 'EK_FWD!D133', fzRate);
    await waitCell(page, 'EK_FWD!I133', 't.trim() !== ""');
    const fz = { sp: trNumber(await cellText(page, 'EK_FWD!G133')), pts: trNumber(await cellText(page, 'EK_FWD!I133')), ois: trNumber(await cellText(page, 'EK_FWD!F133')) };
    check('a TRY rate typed by hand (FAİZ → SPREAD) reads its spread over OIS and its points: the matrix\'s 1M bid rate gives back its spread and points',
      Math.abs(fz.sp - fzWant.sp) <= 1 && Math.abs(fz.pts - fzWant.pts) <= 3 && Math.abs(fz.ois - fzWant.ois) < 0.006, { fzRate, fz, fzWant });
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

    // ---- VİOP Target: the curve of an FRA+bp row's FRA - the bootstrapped curve or a PPK scenario of the OIS page, by name
    console.log('VİOP target: the FRA\'s curve');
    const targetRow = ['VIOP!L331', 'VIOP!M331', 'VIOP!N331', 'VIOP!O331', 'VIOP!P331', 'VIOP!Z331', 'OIS_MAIN!V10'];
    await api(page, 'ayşe yilmaz', 'POST', '/api/inputs', { book: 'tto', items: [{ ref: 'VIOP!L331', value: 'Spot' },
      { ref: 'VIOP!M331', value: '31.12.2026' }, { ref: 'VIOP!N331', value: 'SHORT' }, { ref: 'VIOP!O331', value: 'FRA+bp' },
      { ref: 'VIOP!P331', value: '-150' }, { ref: 'OIS_MAIN!V10', value: '100' }] });           // S2: +100 bp at the first meeting
    await open(page, 'viop');
    await tab(page, 'main');
    await waitCell(page, 'VIOP!Z331', 't.trim() === "Bootstrap (piyasa)"');
    const titleOf = (ref) => page.evaluate((r) => { const td = window.tto.findCell(r); return td ? td.title : null; }, ref);
    const targetHead = () => page.$$eval('.panel[data-panel="B33"] table.grid tr', (trs) => {
      const head = trs.find((tr) => /Hedef tipi/.test(tr.textContent || ''));
      return head ? [...head.children].map((td) => (td.textContent || '').trim()) : [];
    });
    const fra0 = (await cellText(page, 'VIOP!W331')).trim(), rate0 = (await cellText(page, 'VIOP!Q331')).trim();
    const head0 = await targetHead(), tip0 = await titleOf('VIOP!W331');
    check('VİOP Target: "FRA eğrisi" right after "Hedef tipi", Bootstrap (piyasa) by default, and OIS FRA says it is that curve',
      head0.slice(head0.indexOf('Hedef tipi'), head0.indexOf('Hedef tipi') + 3).join(' | ') === 'Hedef tipi | FRA eğrisi | Hedef değer'
      && head0.includes('OIS FRA · Bootstrap (piyasa)') && tip0 === 'OIS FRA, Bootstrap (piyasa) eğrisinden', { head0, tip0, fra0 });
    await pick('VIOP!Z331', 'S2 · Hawkish');
    await waitCell(page, 'VIOP!W331', 't.trim() !== ' + JSON.stringify(fra0));
    const s2 = (await api(page, 'ayşe yilmaz', 'GET', '/api/cell?book=tto&ref=' + encodeURIComponent('EK_VFRA!R10'))).json.cell.v;
    const picked = { fra: trNumber(await cellText(page, 'VIOP!W331')), rate: trNumber(await cellText(page, 'VIOP!Q331')),
      head: (await cellText(page, 'VIOP!W330')).trim(), fraTip: await titleOf('VIOP!W331'), rateTip: await titleOf('VIOP!Q331'), s2 };
    check('... S2 picked: OIS FRA and Hedef faiz are S2\'s (Hedef faiz = FRA − 150 bp) and say "S2 · Hawkish"',
      Math.abs(picked.fra - s2 * 100) < 0.006 && Math.abs(picked.rate - (s2 * 100 - 1.5)) < 0.006 && Math.abs(picked.fra - trNumber(fra0)) > 0.05
      && picked.head === 'OIS FRA · S2 · Hawkish' && picked.fraTip.startsWith('OIS FRA, S2 · Hawkish eğrisinden (Bootstrap (piyasa): ' + fra0)
      && picked.rateTip === 'Hedef faiz = OIS FRA (S2 · Hawkish) − 150 bp', picked);
    await page.reload();
    await page.waitForFunction(() => window.tto && window.tto.state.pageId === 'viop' && window.tto.state.page && window.tto.state.page.ready, null, { timeout: 90000 });
    await tab(page, 'main');
    await waitCell(page, 'VIOP!Z331', 't.trim() === "S2 · Hawkish"');
    check('... the choice survives a reload', trNumber(await cellText(page, 'VIOP!W331')) === picked.fra
      && (await titleOf('VIOP!W331')) === picked.fraTip, [await cellText(page, 'VIOP!W331'), await titleOf('VIOP!W331')]);
    await pick('VIOP!Z331', 'Bootstrap (piyasa)');
    await waitCell(page, 'VIOP!W331', 't.trim() === ' + JSON.stringify(fra0));
    check('... back to Bootstrap (piyasa): the old OIS FRA and Hedef faiz', (await cellText(page, 'VIOP!Q331')).trim() === rate0
      && (await cellText(page, 'VIOP!W330')).trim() === 'OIS FRA · Bootstrap (piyasa)' && await titleOf('VIOP!W331') === tip0,
      [await cellText(page, 'VIOP!Q331'), rate0]);
    await api(page, 'ayşe yilmaz', 'POST', '/api/reset', { book: 'tto', refs: targetRow });
    await waitCell(page, 'VIOP!Z331', 't.trim() === ""');

    // ------------------------------------------------------------------ Masa: TOPLU TARİH ARASI FAİZ; VİOP Target: a far price
    console.log('Masa: bulk date-to-date rates; VİOP target: a far price');
    const cellV = async (ref) => (await api(page, 'ayşe yilmaz', 'GET', '/api/cell?book=tto&ref=' + encodeURIComponent(ref))).json.cell.v;
    await open(page, 'masa');
    await tab(page, 'rates');
    await page.waitForFunction(() => { const it = window.tto.state.page.items.get('TAF'); return !!(it && it.grid && it.grid.data); }, null, { timeout: 20000 });
    const tafRows = () => page.evaluate(() => [...document.querySelectorAll('.panel[data-panel="TAF"] table.grid tbody > tr')]
      .filter((tr) => !tr.classList.contains('grow-hidden')).length);
    const taf0 = await tafRows(), ratesTab = await panelsOnPage(page);
    // two pairs copied in Excel - start | end | spread, the second one's spread left empty (the general spread) - pasted on
    // the first row
    await page.evaluate(async () => {
      const g = window.tto.state.page.items.get('TAF').grid;
      const mod = await import('/static/js/grid.js');
      const i = g.data.r.indexOf(5), j = g.data.c.indexOf('B');
      await mod.pasteText(g, { grid: g, top: i, left: j, bottom: i, right: j }, '15.12.2026\t15.03.2027\t-100\r\n04.01.2027\t05.07.2027\t\r\n');
    });
    await waitCell(page, 'EK_TARIH!M6', 't.trim() !== ""');
    const bulkRow = async (r) => {
      const out = { v: {}, t: {} };
      for (const c of 'EFGHIJKLM') {
        out.v[c] = await cellV('EK_TARIH!' + c + r);
        out.t[c] = (await cellText(page, 'EK_TARIH!' + c + r)).trim();
      }
      return out;
    };
    const pastedRows = { 5: await bulkRow(5), 6: await bulkRow(6) };
    const taf1 = await tafRows();
    // the desk block (TARİH ARASI FAİZ, the same tab) with the same dates and spread: each curve's ACT/360 rate (D62:D68)
    // and MPC ima + spread (F62)
    const sameAsBlock = [];
    for (const [r, start, end, spread] of [[6, '04.01.2027', '05.07.2027', null], [5, '15.12.2026', '15.03.2027', '-100']]) {
      const items = [{ ref: 'MASA!C60', value: start }, { ref: 'MASA!E60', value: end }];
      if (spread !== null) items.push({ ref: 'MASA!I60', value: spread });
      await api(page, 'ayşe yilmaz', 'POST', '/api/inputs', { book: 'tto', items });
      await waitCell(page, 'MASA!E60', 't.trim() === ' + JSON.stringify(end));
      await fresh(page);
      const want = { v: { E: await cellV('MASA!G60'), M: await cellV('MASA!F62') }, t: { M: (await cellText(page, 'MASA!F62')).trim() } };
      for (const [k, c] of [...'FGHIJKL'].entries()) {
        want.v[c] = await cellV('MASA!D' + (62 + k));
        want.t[c] = (await cellText(page, 'MASA!D' + (62 + k))).trim();
      }
      const got = pastedRows[r];
      sameAsBlock.push({ r, ok: [...'EFGHIJKLM'].every((c) => typeof got.v[c] === 'number' && Math.abs(got.v[c] - want.v[c]) < 1e-12)
        && [...'FGHIJKLM'].every((c) => got.t[c] === want.t[c] && /%$/.test(got.t[c])), got, want });
    }
    check('Masa → Faiz · PPK: TOPLU TARİH ARASI FAİZ right after TARİH ARASI FAİZ, its empty rows out of the way; two pairs pasted from Excel '
      + 'fill two rows', ratesTab.slice(0, 2).join(' ') === 'B9 TAF' && taf0 < 10 && taf1 === taf0 + 2, { ratesTab, taf0, taf1 });
    check('... each pasted row is the desk block for the same dates and spread: days, every curve\'s ACT/360 rate and MPC ima + spread '
      + '(to 1e-12, and as shown)', sameAsBlock.every((x) => x.ok), sameAsBlock);
    await api(page, 'ayşe yilmaz', 'POST', '/api/reset', { book: 'tto', refs: ['MASA!C60', 'MASA!E60', 'MASA!I60', 'EK_TARIH!B5', 'EK_TARIH!C5',
      'EK_TARIH!D5', 'EK_TARIH!B6', 'EK_TARIH!C6', 'EK_TARIH!D6'] });
    await waitCell(page, 'EK_TARIH!M5', 't.trim() === ""');
    // VİOP Target: a row's own far limit price typed back with the type "Fiyat" gives its rate
    await api(page, 'ayşe yilmaz', 'POST', '/api/inputs', { book: 'tto', items: [{ ref: 'VIOP!L332', value: 'Spot' },
      { ref: 'VIOP!M332', value: '31.12.2026' }, { ref: 'VIOP!N332', value: 'SHORT' }, { ref: 'VIOP!O332', value: 'FRA+bp' },
      { ref: 'VIOP!P332', value: '-150' }] });
    await open(page, 'viop');
    await tab(page, 'main');
    await waitCell(page, 'VIOP!S332', 't.trim() !== ""');
    const asFra = { rate: await cellV('VIOP!Q332'), far: await cellV('VIOP!S332'), text: (await cellText(page, 'VIOP!Q332')).trim() };
    await pick('VIOP!O332', 'Fiyat');
    await waitCell(page, 'VIOP!O332', 't.trim() === "Fiyat"');
    const typedFar = String(asFra.far).replace('.', ',');
    await typeInto(page, 'VIOP!P332', typedFar);
    await waitCell(page, 'VIOP!P332', 't.trim() !== "-150"');
    await waitCell(page, 'VIOP!Q332', 't.trim() !== ""');
    const asPrice = { rate: await cellV('VIOP!Q332'), far: await cellV('VIOP!S332'), text: (await cellText(page, 'VIOP!Q332')).trim(),
      shown: (await cellText(page, 'VIOP!P332')).trim(), tip: await titleOf('VIOP!Q332'), curve: (await cellText(page, 'VIOP!Z332')).trim() };
    check('VİOP Target: type "Fiyat" and the row\'s own far limit price - the implied TRY rate is the row\'s rate (1e-9), the far limit the price, '
      + 'and it says so', Math.abs(asPrice.rate - asFra.rate) < 1e-9 && asPrice.text === asFra.text && Math.abs(asPrice.far - asFra.far) < 1e-9
      && /^\d\d,\d{4,}/.test(asPrice.shown) && asPrice.curve === '' && asPrice.tip.startsWith('Hedef faiz = uzak kontrat fiyatı '),
      { asFra, asPrice, typedFar });
    await api(page, 'ayşe yilmaz', 'POST', '/api/reset', { book: 'tto', refs: ['VIOP!L332', 'VIOP!M332', 'VIOP!N332', 'VIOP!O332', 'VIOP!P332'] });
    await waitCell(page, 'VIOP!Q332', 't.trim() === ""');

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
      return { id: p.dataset.panel, title: p.querySelector('header h2').textContent, markers: svg ? svg.querySelectorAll('circle.mk').length : 0,
        labels: svg ? [...svg.querySelectorAll('text.pt')].map((t) => t.textContent) : [], paths: svg ? svg.querySelectorAll('path').length : 0,
        titles: svg ? [...svg.querySelectorAll('text.ttl')].map((t) => t.textContent) : [], wide: p.classList.contains('wide'),
        table: [...p.querySelectorAll('header .tools button')].some((b) => b.textContent === 'Tablo') };
    }));
    check('ASW page draws the workbook\'s XY chart: one marker per bond, labelled, and the fitted curve',
      asw.length === 4 && asw[0].title === 'DİBS ASW — kalan vade' && asw[0].markers >= 15 && asw[0].labels.length >= 10
      && asw[0].labels.every((t) => /^[A-ZŞÇÖÜİa-zşçöüığ]{3}\d\d/.test(t)) && asw[0].titles.includes('ASW (bp)') && asw[0].titles.includes('Kalan vade (yıl)'), asw[0]);
    const aswSvg = page.locator('.panel.chart', { hasText: 'DİBS ASW — kalan vade' }).locator('svg.chart');
    await aswSvg.scrollIntoViewIfNeeded();
    const ab = await aswSvg.boundingBox();
    await page.mouse.move(ab.x + ab.width * 0.3, ab.y + ab.height * 0.5);
    await page.waitForSelector('.chart-tip');
    const atip = await page.evaluate(() => ({ head: document.querySelector('.chart-tip .t').textContent, rows: [...document.querySelectorAll('.chart-tip .r')].map((r) => r.textContent) }));
    check('hovering the XY chart names the nearest bond and its spread', atip.head.length > 0 && atip.rows.length >= 1 && atip.rows.some((r) => /\d/.test(r)), atip);
    await page.mouse.move(5, 5);
    // the same chart on the FX swap curve: a marker per bond (as many as the server's chart has), labelled as the OIS
    // chart, its own fitted curve dashed, the same tooltip and "Tablo"; and the FX swap implied curve beside OIS
    const aswView = (await api(page, 'ayşe yilmaz', 'GET', '/api/view/asw')).json;
    const fxSeries = aswView.panels.find((p) => p.id === 'chartfx').data.series;
    const fxc = asw.find((c) => c.id === 'chartfx');
    check('ASW page: the chart once more on the FX swap curve - every bond at its years with its FX ASW, labelled, the FX curve dashed',
      fxc && fxc.title === 'FX swap ima eğrisine göre ASW — kalan vade' && fxc.markers === fxSeries[0].x.length && fxc.markers === asw[0].markers
      && JSON.stringify(fxc.labels) === JSON.stringify(asw[0].labels) && fxc.titles.includes('ASW FX ima (bp)') && fxc.wide && fxc.table
      && fxSeries[1].dash === 1, { fxc, points: fxSeries[0].x.length });
    const fxSvg = page.locator('.panel[data-panel="chartfx"] svg.chart');
    await fxSvg.scrollIntoViewIfNeeded();
    const fb = await fxSvg.boundingBox();
    await page.mouse.move(fb.x + fb.width * 0.3, fb.y + fb.height * 0.5);
    await page.waitForSelector('.chart-tip');
    const ftip = await page.evaluate(() => ({ head: document.querySelector('.chart-tip .t').textContent, rows: [...document.querySelectorAll('.chart-tip .r')].map((r) => r.textContent) }));
    check('... hovering it names the nearest bond and its FX spread', ftip.head.length > 0 && ftip.rows.some((r) => /\d/.test(r)), ftip);
    await page.mouse.move(5, 5);
    const fxl = asw.find((c) => c.id === 'fxline');
    check('... and the FX swap implied TRY curve itself, tenor by tenor beside OIS', fxl && /FX swap ima TRY eğrisi/.test(fxl.title) && fxl.paths >= 2 && fxl.table, fxl);
    check('ASW table has the bonds of the recorded day', (await cellText(page, 'ASW!B7')).trim() === 'TRB100227T13' && /^-?\d+/.test((await cellText(page, 'ASW!R9')).trim()));
    const aswRows = await page.evaluate(() => [...document.querySelectorAll('.panel[data-panel="tbl"] table.grid tr')].map((tr) => [...tr.children].map((td) => td.textContent.trim())));
    const aswCaps = aswRows.filter((r) => /· \d+ kâğıt$/.test(r[0])).map((r) => r[0]);
    check('DİBS ASW table: its bonds only (no empty rows), kind by kind as the trading list has them',
      aswCaps.length === 3 && aswCaps[0] === 'Bono · 2 kâğıt' && aswRows.filter((r) => /^TR[A-Z0-9]{9}\d$/.test(r[0])).length === 19
      && !aswRows.some((r) => r[0] === ''), aswCaps);
    // the history chart against OIS (as before), the offshore curve or both: a small selector on the chart writes the
    // user's own "Geçmiş grafiği" (ASW!N3, Parametreler) - Offshore draws the same chart on the offshore calculation
    const pickState = () => page.evaluate(() => {
      const p = document.querySelector('.panel[data-panel="chart1"]');
      return { title: p.querySelector('header h2').textContent, on: [...p.querySelectorAll('#chart-pick-chart1 button.on')].map((b) => b.textContent),
        options: [...p.querySelectorAll('#chart-pick-chart1 button')].map((b) => b.textContent) };
    });
    const pick0 = await pickState();
    await page.click('#chart-pick-chart1 button[data-pick="Offshore"]');
    await page.waitForFunction(() => / offshore /.test(document.querySelector('.panel[data-panel="chart1"] header h2').textContent), null, { timeout: 30000 });
    const pick1 = await pickState();
    const n3 = (await cellText(page, 'ASW!N3')).trim();
    await page.click('#chart-pick-chart1 button[data-pick="OIS"]');
    await page.waitForFunction(() => !/offshore/.test(document.querySelector('.panel[data-panel="chart1"] header h2').textContent), null, { timeout: 30000 });
    const pick2 = await pickState();
    check('ASW history chart: OIS / Offshore / İkisi - the selector draws it on the offshore curve and back, the choice the user\'s own (ASW!N3)',
      JSON.stringify(pick0.options) === JSON.stringify(['OIS', 'Offshore', 'İkisi']) && pick0.on.join() === 'OIS'
      && pick0.title === 'ASW geçmişi (son nokta canlı)' && pick1.on.join() === 'Offshore'
      && pick1.title === 'ASW geçmişi · offshore eğrisine göre (son nokta canlı)' && n3 === 'Offshore'
      && pick2.on.join() === 'OIS' && pick2.title === pick0.title, { pick0, pick1, pick2, n3 });
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
    // (and the bonds' closes tests/test_e2e.py put in for Kâğıt Fiyatlama: TTO_E2E_SEEDED series)
    const seededSeries = Number(process.env.TTO_E2E_SEEDED || 0);
    check('the history of the recorded month is filled in the background', hist.phase === 'idle' && hist.mpc_days === 21
      && hist.series === 8 + 9 + seededSeries && !hist.error, { hist, seededSeries });
    // "Hesap" on a view as the server gives it - the fit, the ML models and the backtest at once (planted: the polls and the
    // status answer it), then the server's own answer
    const planted = { busy: true, eta_s: 180, eta: '~3 dk', text: 'Quant 14/26 · ML 240/480 · geri test 12/25 · ~3 dk', jobs: [
      { id: 'quant', name: 'Quant', title: 'Quant tam hesap', unit: 'adım', done: 14, total: 26, step: 'Makine öğrenmesi', since: '10:42:05', elapsed_s: 75,
        eta_s: 180, eta: '~3 dk', short: 'Quant 14/26' },
      { id: 'ml', name: 'ML', title: 'Makine öğrenmesi: modeller', unit: 'model', done: 240, total: 480, step: '', since: '10:42:31', elapsed_s: 49,
        eta_s: 150, eta: '~3 dk', short: 'ML 240/480' },
      { id: 'bt', name: 'geri test', title: 'Geri test', unit: 'yeniden kurma', done: 12, total: 25, step: 'Mart 2026 · 14.03.2026 kapanışıyla', since: '10:40:00',
        elapsed_s: 200, eta_s: 170, eta: '~3 dk', short: 'geri test 12/25' }] };
    const PROGRESS = /\/api\/progress(\?|$)/, STATUS = /\/api\/status(\?|$)/;      // (the page's requests carry ?lang=…)
    await page.route(PROGRESS, (r) => r.fulfill({ json: planted }));
    await page.route(STATUS, async (r) => {
      const res = await r.fetch();
      const j = await res.json();
      j.progress = planted;
      await r.fulfill({ response: res, json: j });
    });
    await page.evaluate((v) => window.tto.progress(v), planted);
    const ind = await page.evaluate(() => {
      const b = document.getElementById('hesap-ind');
      return { hidden: b.classList.contains('hidden'), text: (document.getElementById('hesap-text') || {}).textContent, tip: b.title };
    });
    check('"Hesap" in the top bar while something runs: each one\'s count and the time left ("Quant 14/26 · ML 240/480 · geri test 12/25 · ~3 dk")',
      !ind.hidden && ind.text === planted.text && ind.tip.startsWith('Quant tam hesap: 14 / 26 adım · şu an Makine öğrenmesi · 10:42:05\'ten beri · ~3 dk\n'), ind);
    await page.click('#hesap-ind');
    await page.waitForSelector('#hesap-list table tbody tr');
    const hesapRows = await page.$$eval('#hesap-list table tbody tr', (trs) => trs.map((tr) => [...tr.children].map((td) => td.textContent)));
    check('... a click lists each: its step, done / total, since when, how long so far, the time left', JSON.stringify(hesapRows) === JSON.stringify([
      ['Quant tam hesap', 'Makine öğrenmesi', '14 / 26 adım', '10:42:05', '1 dk 15 sn', '~3 dk'],
      ['Makine öğrenmesi: modeller', '', '240 / 480 model', '10:42:31', '49 sn', '~3 dk'],
      ['Geri test', 'Mart 2026 · 14.03.2026 kapanışıyla', '12 / 25 yeniden kurma', '10:40:00', '3 dk 20 sn', '~3 dk']]), hesapRows);
    await page.keyboard.press('Escape');
    await page.unroute(PROGRESS);
    await page.unroute(STATUS);
    let hesapGone = false;
    for (let i = 0; i < 40 && !hesapGone; i++) {
      const p = (await api(page, 'ayşe yilmaz', 'GET', '/api/progress')).json || {};
      hesapGone = !p.busy && await page.evaluate(() => document.getElementById('hesap-ind').classList.contains('hidden'));
      if (!hesapGone) await page.waitForTimeout(1500);
    }
    check('... and gone once nothing runs (the server\'s own answer, asked every few seconds while something ran)', hesapGone);
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
    // ---- everything typed for a meeting moves with it (tto/meetings.py): a step, an "Elle değer" and an alarm on 18.03.2027
    await api(page, 'ayşe yilmaz', 'POST', '/api/inputs', { book: 'tto', items: [{ ref: 'OIS_MAIN!U12', value: '-40' }] });
    await api(page, 'ayşe yilmaz', 'POST', '/api/inputs', { book: 'tto', adhoc: true, items: [{ ref: 'OIS_MAIN!R12', value: '77' }] });
    const mAlarm = (await api(page, 'ayşe yilmaz', 'POST', '/api/alarms/add', { book: 'tto', ref: 'OIS_MAIN!R12', op: '>=', level: '999' })).json.alarm;
    const calNow = (await api(page, 'ayşe yilmaz', 'GET', '/api/calendar')).json;
    const calDates = calNow.meetings.map((m) => m.date);
    const withExtra = calDates.slice(0, -1).concat(['2027-02-11']);           // an extraordinary meeting (80 rows: the last makes room)
    const stale = await api(page, 'ayşe yilmaz', 'POST', '/api/calendar', { dates: withExtra, version: 'eski' });
    check('calendar: a save over a calendar that changed meanwhile is refused (409, with the reason)', stale.status === 409
      && /değişti/.test(stale.json.error), stale);
    const ins = await api(page, 'ayşe yilmaz', 'POST', '/api/calendar', { dates: withExtra, version: calNow.version });
    await open(page, 'ois');
    await waitCell(page, 'OIS_MAIN!P13', 't.trim() === "18.03.2027"');
    const watchNow1 = (await api(page, 'ayşe yilmaz', 'GET', '/api/watch')).json.alarms.find((a) => a.id === mAlarm.id);
    const r12 = trNumber(await cellText(page, 'OIS_MAIN!R12')), r13 = trNumber(await cellText(page, 'OIS_MAIN!R13'));
    check('a meeting put in before 18.03.2027: its step, its "Elle değer" and its alarm show on its new row (13)',
      ins.status === 200 && (await cellText(page, 'OIS_MAIN!P12')).trim() === '11.02.2027' && trNumber(await cellText(page, 'OIS_MAIN!U13')) === -40
      && r13 === 77 && r12 !== 77 && (await cellText(page, 'OIS_MAIN!U12')).trim() === '' && mAlarm.subject.kind === 'meeting'
      && watchNow1.subject.date === '2027-03-18' && watchNow1.now === 77 && /OIS_MAIN!R13/.test(watchNow1.detail),
    { ins: ins.json && ins.json.note, r12, r13, alarm: watchNow1 });
    // ---- Delete over the dates: refused with the reason - the steps of the selection are cleared, no meeting leaves
    await (await cellHandle(page, 'OIS_MAIN!P13')).click();
    await (await cellHandle(page, 'OIS_MAIN!U13')).click({ modifiers: ['Shift'] });
    await page.keyboard.press('Delete');
    await page.waitForFunction(() => [...document.querySelectorAll('#toasts .toast')].some((t) => /toplantı tarihi silinmez/.test(t.textContent)),
      null, { timeout: 15000 });
    await waitCell(page, 'OIS_MAIN!U13', 't.trim() === ""');
    check('Delete over a selection with meeting dates: the dates are refused with where to remove a meeting, the steps cleared',
      (await cellText(page, 'OIS_MAIN!P13')).trim() === '18.03.2027' && /Toplantı takvimi/.test(await page.textContent('#toasts'))
      && (await api(page, 'ayşe yilmaz', 'GET', '/api/calendar')).json.meetings.length === calDates.length);
    // back as it was: the list, her "Elle değer" and the alarm
    const calBack = (await api(page, 'ayşe yilmaz', 'GET', '/api/calendar')).json;
    await api(page, 'ayşe yilmaz', 'POST', '/api/calendar', { dates: calDates, version: calBack.version });
    await api(page, 'ayşe yilmaz', 'POST', '/api/reset', { book: 'tto', refs: ['OIS_MAIN!R12', 'OIS_MAIN!U12'] });
    await api(page, 'ayşe yilmaz', 'POST', '/api/alarms/remove', { id: mAlarm.id });
    await waitCell(page, 'OIS_MAIN!P12', 't.trim() === "18.03.2027"');
    await open(page, 'settings');
    const series = await rowsOf('series');
    check('settings: which series have history (TLREF, the recorded OIS tenors) and which have none',
      JSON.stringify(rowOf(series, 'TLREF').slice(0, 8)) === JSON.stringify(['TLREF', 'TLREF', 'BISTTREF Index', 'PX_LAST', '30.10.2025', '02.11.2026', '253', 'var'])
      && series.some((r) => r[2] === 'TYSO10 GFOF Curncy' && r[7] === 'geçmiş yok') && series.some((r) => r[2] === 'TYSOA GFOF Curncy' && /yedek kullanılır/.test(r[7]))
      && series.some((r) => r[2] === 'TYSOA Curncy' && r[7] === 'yedek kaynak')
      // (+ the quant package's: 22 pairs, the global drivers, the option surfaces, the VİOP page's five, the G10 universe's
      // own 22 - and its contracts: the six listed and 24 expired months, close / high / low, an expired one with its
      // two-digit-year ticker beside; + the SOFR fixings of Trades' SOFR swaps, none recorded)
      && series.length === 118 + 143 + 3 * (6 + 24) + 3 * 24 + 1
      && series.some((r) => r[2] === 'SOFRRATE Index' && r[0] === 'SOFR fixing (Trades)' && r[7] === 'geçmiş yok')
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
    // the TRY curves between quoted tenors, one's own setting: on PPK basamak the top bar says so and a forward between two
    // quotes moves (Masa's broken date: the offshore curve's PPK node table), back on Bootstrap all as it was
    const curveV = async (ref) => ((await api(page, 'ayşe yilmaz', 'GET', '/api/cell?book=tto&ref=' + encodeURIComponent(ref))).json.cell || {}).v;
    const brokenBoot = await curveV('MASA!F173');
    check('settings: the curve between quoted tenors is Bootstrap (Murex) at first, no mark in the top bar',
      await page.locator('#interp-mode button.on[data-mode="boot"]').count() === 1 && await page.locator('#interp-badge.hidden').count() === 1
      && /Bootstrap \(Murex\)/.test(await page.textContent('#interp-status')), await page.textContent('#interp-info'));
    await page.click('#interp-mode button[data-mode="ppk"]');
    await page.waitForFunction(() => !document.getElementById('interp-badge').classList.contains('hidden'), null, { timeout: 30000 });
    const brokenPpk = await curveV('MASA!F173');
    check('... on PPK basamak the top bar says so, the setting is kept and a forward between quotes moves',
      /Eğri: PPK basamak/.test(await page.textContent('#interp-badge')) && await page.locator('#interp-mode button.on[data-mode="ppk"]').count() === 1
      && (await api(page, 'ayşe yilmaz', 'GET', '/api/interp')).json.mode === 'ppk'
      && typeof brokenPpk === 'number' && typeof brokenBoot === 'number' && Math.abs(brokenPpk - brokenBoot) > 1e-3, [brokenBoot, brokenPpk]);
    await shot(page, '15-settings-interp-ppk');
    await page.click('#interp-mode button[data-mode="boot"]');
    await page.waitForFunction(() => document.getElementById('interp-badge').classList.contains('hidden'), null, { timeout: 30000 });
    check('... back on Bootstrap: the mark goes and the number is as it was', (await curveV('MASA!F173')) === brokenBoot
      && (await api(page, 'ayşe yilmaz', 'GET', '/api/interp')).json.mode === 'boot', await curveV('MASA!F173'));
    // the desk's list of curve points: a table per curve (the PPK meetings greyed, the computed 18M XCCY), an
    // administrator adds a typed point with a note - the offshore curve is built on the list - and switches it off
    const cpRows = (curve) => page.evaluate((c) => [...document.querySelectorAll('#cp-table-' + c + ' tbody tr')].map((tr) => ({
      id: tr.dataset.id, cls: tr.className, cells: [...tr.children].map((td) => td.textContent.trim()) })), curve);
    await page.waitForSelector('#cp-table-ois tbody tr', { timeout: 20000 });
    const cpOis0 = await cpRows('ois'), cpOff0 = await cpRows('off');
    check('settings: Eğri noktaları - OIS 1M … 10Y and the offshore TRYI / XCCY points from the workbook, the computed 18M XCCY, the PPK meetings greyed among them; the list is the default',
      cpOis0.filter((r) => !/cp-ppk/.test(r.cls)).map((r) => r.cells[0]).join(' ') === '1M 2M 3M 6M 9M 1Y 18M 2Y 3Y 4Y 5Y 6Y 7Y 8Y 9Y 10Y'
      && cpOis0.some((r) => /cp-ppk/.test(r.cls) && r.cells[3] === 'takvimden') && cpOff0.some((r) => /cp-calc/.test(r.cls) && r.cells[0] === '18M')
      && cpOff0.filter((r) => !/cp-ppk/.test(r.cls)).length === 20 && /Liste varsayılan/.test(await page.textContent('#cp-status')),
    { ois: cpOis0.slice(0, 3), status: await page.textContent('#cp-status') });
    await page.selectOption('#cp-add-curve', 'off');
    await page.selectOption('#cp-add-kind', 'xccy');
    await page.fill('#cp-add-when', '2Y3M');
    await page.selectOption('#cp-add-source', 'typed');
    await page.fill('#cp-add-rate', '42,10');
    await page.fill('#cp-add-note', 'e2e aracı kotası');
    await page.click('#cp-add');
    await page.waitForFunction(() => [...document.querySelectorAll('#cp-table-off tbody tr')].some((tr) => /e2e aracı kotası/.test(tr.textContent)),
      null, { timeout: 30000 });
    const cpAdded = (await cpRows('off')).find((r) => /e2e aracı kotası/.test(r.cells.join(' ')));
    const cpApi = (await api(page, 'ayşe yilmaz', 'GET', '/api/curve-points')).json;
    check('... an administrator adds a 2Y3M XCCY typed at 42,10 % with its note: in the table (who added it), the offshore list differs, the curve is built on it',
      cpAdded && cpAdded.cells[0] === '2Y3M' && /^42,1000%/.test(cpAdded.cells[4]) && /Ayşe Yılmaz/.test(cpAdded.cells[6])
      && cpApi.custom.off === true && cpApi.custom.ois === false && /Liste varsayılandan farklı/.test(await page.textContent('#cp-status'))
      && (await curveV('EK_INTERP!N6')) === 1, { cpAdded, custom: cpApi.custom });
    await shot(page, '15b-settings-curve-points');
    await page.click('#cp-table-off tr[data-id="' + cpAdded.id + '"] input.cp-on');
    await page.waitForFunction(() => /Liste varsayılan:/.test((document.getElementById('cp-status') || {}).textContent || ''), null, { timeout: 30000 });
    const cpOffRow = (await cpRows('off')).find((r) => r.id === cpAdded.id);
    check('... switched off: the row stays with its note, the list is the default again, the curve the workbook\'s own',
      cpOffRow && /cp-off/.test(cpOffRow.cls) && /e2e aracı kotası/.test(cpOffRow.cells[5])
      && (await api(page, 'ayşe yilmaz', 'GET', '/api/curve-points')).json.custom.off === false && (await curveV('EK_INTERP!N6')) === 0
      && (await curveV('MASA!F173')) === brokenBoot, cpOffRow);
    // the holidays: a list per currency - TRY of both TRY workbooks, USD and EUR of the FX value dates -, one tab each;
    // the SIFMA holidays and the FOMC meetings beside them
    const holText = await page.inputValue('#holidays-text');
    const holTabs = () => page.evaluate(() => [...document.querySelectorAll('#holidays-ccy button')].map((b) => b.textContent + (b.classList.contains('on') ? '!' : '')));
    check('settings: the TR holidays of both workbooks in one list, with the US (SIFMA) holidays and the FOMC meetings',
      /^01\.01\.2026$/m.test(holText) && /^29\.10\.2026\tCumhuriyet$/m.test(holText) && holText.split('\n').length === 152
      && /FOMC toplantıları: 09\.12\.2026/.test(await page.textContent('#holidays-other')), holText.split('\n').slice(0, 3));
    check('... one tab per currency, TRY first', (await holTabs()).join(' ') === 'TRY! USD EUR', await holTabs());
    const holWhere = await page.textContent('#holidays-info');
    check('... the TRY list is written to three books: TRY (Motor), DİBS ASW and the Borsa Swap\'s copy (its T+1 value date)',
      /TRY \(Motor\) · DİBS ASW · Borsa Swap/.test(holWhere), holWhere);
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

    // ------------------------------------------------------------------ Fiyatlama: any start and maturity, both curves
    console.log('pricing');
    await open(page, 'fiyatlama');
    await page.waitForSelector('#pr-buckets');
    const prLabel = () => page.textContent('#pr-label');
    const prWait = (re) => page.waitForFunction((s) => new RegExp(s).test((document.getElementById('pr-label') || {}).textContent || ''),
      re, { timeout: 60000 });
    const prType = async (sel, value) => { await page.fill(sel, value); await page.press(sel, 'Enter'); };
    const prApi = async (who) => (await api(page, who || 'ayşe yilmaz', 'GET', '/api/pricing')).json;
    const prPct = (v) => (v * 100).toFixed(4).replace('.', ',') + '%';
    const prFix = (v, d) => (v > 0 ? '+' : '') + v.toFixed(d).replace('.', ',');
    const prBuckets = () => page.evaluate(() => Object.fromEntries([...document.querySelectorAll('#pr-buckets tr[data-bucket]')]
      .map((tr) => [tr.dataset.bucket, [...tr.children].slice(1).map((td) => td.textContent)])));
    const prMenu = await page.evaluate(() => window.tto.state.pages.filter((p) => p.group === 'TRY Faiz').map((p) => p.id));
    const prB0 = await prBuckets();
    check('Fiyatlama: in TRY Faiz right after OIS · PPK; it opens on a TRY OIS 1Y - both curves\' mids, the desk\'s OIS buckets ON … 10Y '
      + '(ON / 1W / 2W no quote of the curve: –)', prMenu[0] === 'ois' && prMenu[1] === 'fiyatlama' && /^TRY OIS 1Y · PAY/.test(await prLabel())
      && Object.keys(prB0).join(' ') === 'ON 1W 2W 1M 2M 3M 6M 9M 1Y 18M 2Y 3Y 4Y 5Y 6Y 7Y 8Y 9Y 10Y' && prB0.ON[0] === '–'
      && prB0['1Y'][0].startsWith('+') && prB0['5Y'][0] === '0,00', { prMenu, prB0 });
    // a 2Y3M XCCY received: its coupons counted back from the maturity, the short one first (the desk's rule)
    await page.click('#pr-asset button[data-v="xccy"]');
    await prWait('^XCCY');
    await prType('#pr-end', '2Y3M');
    await prWait('^XCCY 2Y3M');
    await page.click('#pr-side button[data-v="RECEIVE"]');
    await prWait('^XCCY 2Y3M · RECEIVE');
    const prX = await prApi();
    const prXSched = await page.evaluate(() => [...document.querySelectorAll('#pr-schedule tr')].slice(1, -1)
      .map((tr) => [...tr.children].map((td) => td.textContent)));
    const prXb = await prBuckets();
    check('... a 2Y3M XCCY received: three coupons back from the maturity, the short one first (3M, 12M, 12M; ACT/360), the mid both ways, '
      + 'the offshore curve\'s buckets (− for the receiver), the far ones 0', prXSched.length === 3
      && prXSched.map((r) => r[1] + '>' + r[2] + ':' + r[3]).join(' ') === '04.11.2026>04.02.2027:92 04.02.2027>04.02.2028:365 04.02.2028>05.02.2029:367'
      && (await page.textContent('#pr-mid .v')) === prPct(prX.mid.boot) && (await page.textContent('#pr-mid-other .v')) === prPct(prX.mid.ppk)
      && Math.abs(prX.mid.boot - 0.4062) < 0.001 && prXb['XCCY 2Y'][0].startsWith('-') && prXb['XCCY 5Y'][0] === '0,00' && prXb['XCCY 5Y'][1] === '0,00'
      && prX.buckets.total.boot < 0, { prXSched, mid: prX.mid, prXb });
    await shot(page, '16-fiyatlama-xccy');
    // a 12x15 FRA typed in one box, then a price: the NPV
    await page.click('#pr-asset button[data-v="fra"]');
    await prWait('^FRA');
    await prType('#pr-start', '12x15');
    await prWait('^FRA 12x15');
    await page.waitForFunction(() => document.getElementById('pr-start').value === '12', null, { timeout: 30000 });
    const prFb = await prBuckets();
    const prFraBoxes = [await page.inputValue('#pr-start'), await page.inputValue('#pr-end')];
    const prF = await prApi();
    const prList = (await api(page, 'ayşe yilmaz', 'GET', '/api/view/ois')).json.panels.find((x) => x.id === 'B21').data;
    const prListRow = prList.rows.find((row) => row[0] && row[0].t === '1Y3M');
    const prListMid = prListRow ? prListRow[prList.c.indexOf('B')].v : null;
    check('... a 12x15 FRA ("12x15" in one box: 12 and 15): on Bootstrap OIS · PPK\'s FRA list\'s 1Y3M, on PPK basamak ~70 bp lower; '
      + 'a payer\'s risk in 1Y (−) and 18M (+), none after', prFraBoxes.join('x') === '12x15' && Math.abs(prF.mid.boot - prListMid) < 1e-12
      && (await page.textContent('#pr-mid .v')) === prPct(prF.mid.boot) && (await page.textContent('#pr-mid-other .v')) === prPct(prF.mid.ppk)
      && (await page.textContent('#pr-diff .v')) === prFix(prF.diff, 2) && prF.diff < -50
      && prFb['1Y'][0].startsWith('-') && prFb['18M'][0].startsWith('+') && prFb['2Y'][0] === '0,00', { prFraBoxes, mid: prF.mid, prListMid, prFb });
    await prType('#pr-price', '35');
    await page.waitForSelector('#pr-npv-tl', { timeout: 60000 });
    const prN = await prApi();
    const prNpvText = await page.textContent('#pr-npv-tl .v');
    check('... a price typed (35 = %35, under mid): the NPV in TL and $, + for a payer under mid (Günlük İşlemler\'s "Mid\'e göre"), '
      + 'the price − mid in bp', prN.npv && prN.npv.tl.boot > 0 && /^\+/.test(prNpvText) && Math.abs(trNumber(prNpvText) - prN.npv.tl.boot) < 1
      && Math.abs(trNumber(await page.textContent('#pr-npv-usd .v')) - prN.npv.usd.boot) < 1
      && (await page.textContent('#pr-dist .v')) === prFix(prN.npv.dist.boot, 2) && prN.npv.dist.boot < 0, { prNpvText, npv: prN.npv });
    await shot(page, '16b-fiyatlama-fra-npv');
    // the inputs are the user's own: back on the page as left, another asset as it was left, another user's the defaults
    await open(page, 'ois');
    await open(page, 'fiyatlama');
    await page.waitForSelector('#pr-npv-tl', { timeout: 60000 });
    const prKept = [await prLabel(), await page.inputValue('#pr-price')];
    await page.click('#pr-asset button[data-v="xccy"]');
    await prWait('^XCCY 2Y3M · RECEIVE');
    const prOther = await prApi('mehmet');
    check('... the inputs are each user\'s own: back on the page the FRA and its price as left, the XCCY as it was; Mehmet\'s page his own',
      /^FRA 12x15 · PAY/.test(prKept[0]) && prKept[1] === '35' && prOther.label === 'TRY OIS 1Y', { prKept, prOther: prOther.label });
    // an FX forward: outright and points both ways
    await page.click('#pr-asset button[data-v="fx"]');
    await prWait('^USDTRY 18M');
    const prFx = await prApi();
    check('... an 18M USDTRY forward: the outright both ways and the points (Masa\'s broken-date block\'s at its own date)',
      (await page.textContent('#pr-mid .v')) === prFx.mid.boot.toFixed(4).replace('.', ',') && prFx.mid.boot > prFx.fx.spot
      && Math.abs(prFx.fx.points.boot - (prFx.mid.boot - prFx.fx.spot) * 1e4) < 1e-6
      && /^\+/.test(await page.textContent('#pr-dv01 .v')), { mid: prFx.mid, points: prFx.fx.points });
    await page.click('#pr-asset button[data-v="fra"]');
    await prWait('^FRA 12x15');

    // ------------------------------------------------------------------ Swaption: a TRY OIS swaption, to look at only
    console.log('swaption');
    await open(page, 'swaption');
    await page.waitForSelector('#swpt-options');
    const swptMenu = await page.evaluate(() => window.tto.state.pages.filter((p) => p.group === 'TRY Faiz').map((p) => p.id));
    const swptApi = async (q) => (await api(page, 'ayşe yilmaz', 'GET', '/api/swaption?' + new URLSearchParams(q).toString())).json;
    const swptLabel = (re) => page.waitForFunction((s) => new RegExp(s).test((document.getElementById('swpt-label') || {}).textContent || ''),
      re, { timeout: 60000 });
    const swptSource = (re) => page.waitForFunction((s) => new RegExp(s).test((document.querySelector('#swpt-vol-source .v') || {}).textContent || ''),
      re, { timeout: 60000 });
    const swptPct = (v) => (v * 100).toFixed(4).replace('.', ',') + '%';
    const swptTile = (id) => page.textContent('#' + id + ' .v');
    const swptReal = () => page.evaluate(() => Object.fromEntries([...document.querySelectorAll('#swpt-realized tr[data-window]')]
      .map((tr) => [tr.dataset.window, [...tr.children].map((td) => td.textContent)])));
    await page.click('#swpt-expiry-presets button[data-v="1Y"]');
    await page.click('#swpt-tenor-presets button[data-v="2Y"]');
    await swptLabel('^1Y × 2Y');
    const swpt0 = await swptApi({ expiry: '1Y', tenor: '2Y' });
    const swptR0 = await swptReal();
    const swptDates = await page.textContent('#swpt-dates');
    check('Swaption: in TRY Faiz right after Fiyatlama; 1Y × 2Y on Fiyatlama\'s TRY OIS 1Y × 3Y - the forward on both curves (yours first), '
      + 'the expiry 03.11.2027 (the business day before the start), 250 business days; the realized table\'s four windows say why there is '
      + 'no vol: the recorded closes stop at 1Y (18M, 2Y, 3Y missing)', swptMenu.slice(0, 3).join() === 'ois,fiyatlama,swaption'
      && swpt0.underlying === 'TRY OIS 1Y × 3Y' && (await swptTile('swpt-fwd')) === swptPct(swpt0.forward.boot)
      && (await swptTile('swpt-fwd-other')) === swptPct(swpt0.forward.ppk) && /opsiyon vadesi 03\.11\.2027/.test(swptDates) && /250 iş günü/.test(swptDates)
      && Object.keys(swptR0).join() === '20,60,120,250' && Object.values(swptR0).every((r) => r[2] === '–')
      && /18M, 2Y, 3Y/.test(await page.textContent('#swpt-novol')) && /18M, 2Y, 3Y/.test(await page.textContent('#swpt-realized-note')),
    { swptMenu, und: swpt0.underlying, swptDates, swptR0 });
    // a vol typed in bp/day: the other two units follow, every greek is filled, the payer's breakeven is K + its running premium
    await page.fill('#swpt-vol-day', '5');
    await page.press('#swpt-vol-day', 'Enter');
    await swptSource('yazılan');
    const swpt1 = await swptApi({ expiry: '1Y', tenor: '2Y', vol: '5', vol_unit: 'day' });
    const swptOpts = await page.evaluate(() => Object.fromEntries([...document.querySelectorAll('#swpt-options tr[data-row]')]
      .map((tr) => [tr.dataset.row, [...tr.children].slice(1).map((td) => td.textContent)])));
    const swptYear = trNumber(await swptTile('swpt-vol-year-out'));
    check('... a vol typed in bp/day (5): bp/year = 5 · √252 and % Black beside it; payer / receiver / straddle with premium, delta, gamma, '
      + 'vega (normal and Black) and theta; the payer\'s breakeven = K + its running premium', Math.abs(swptYear - 5 * Math.sqrt(252)) < 0.06
      && Math.abs(swpt1.vol.year - 5 * Math.sqrt(252)) < 1e-9 && (await swptTile('swpt-vol-black-out')) === (swpt1.vol.black * 100).toFixed(2).replace('.', ',') + '%'
      && ['tl', 'delta_tl', 'gamma_tl', 'vega_tl', 'vega_black_tl', 'theta_tl'].every((k) => swptOpts[k] && swptOpts[k].length === 3 && swptOpts[k].every((t) => /\d/.test(t)))
      && /^\+/.test(swptOpts.delta_tl[0]) && /^-/.test(swptOpts.delta_tl[1]) && /^-/.test(swptOpts.theta_tl[2])
      && Math.abs(swpt1.options.payer.breakeven - (swpt1.strike + swpt1.options.payer.running_bp * 1e-4)) < 1e-12
      && (await page.textContent('#swpt-be-payer')) === swptPct(swpt1.options.payer.breakeven),
    { swptYear, vol: swpt1.vol, swptOpts, be: swpt1.options.payer.breakeven });
    await shot(page, '16c-swaption');
    // the recorded month's closes reach 1Y: a 3M × 9M forward has realized vols, and the 60 changes' (the 21 there are) prices
    await page.click('#swpt-vol-reset');
    await swptSource('gerçekleşen');
    await page.fill('#swpt-expiry', '3M');
    await page.press('#swpt-expiry', 'Enter');
    await swptLabel('^3M × 2Y');
    await page.fill('#swpt-tenor', '9M');
    await page.press('#swpt-tenor', 'Enter');
    await swptLabel('^3M × 9M');
    const swpt2 = await swptApi({ expiry: '3M', tenor: '9M' });
    const swptR2 = await swptReal();
    check('... 3M × 9M (TRY OIS 3M × 1Y): realized vols from the recorded month - 20 changes full, 60 / 120 / 250 the 21 there are (*), '
      + 'bp/year = bp/day · √252; the 60\'s is the vol used, and its payer\'s breakeven K + p', swpt2.underlying === 'TRY OIS 3M × 1Y'
      && swptR2['20'][1] === '20' && swptR2['60'][1] === '21*' && swptR2['250'][1] === '21*'
      && Math.abs(trNumber(swptR2['20'][2]) - swpt2.realized.rows[0].day) < 0.006
      && Math.abs(trNumber(swptR2['60'][3]) - swpt2.realized.rows[1].day * Math.sqrt(252)) < 0.06
      && swpt2.vol.source === 'realized' && swpt2.vol.n === 21 && swpt2.vol.day === swpt2.realized.rows[1].day
      && trNumber(await swptTile('swpt-vol-day-out')) === Number(swpt2.vol.day.toFixed(2))
      && (await page.textContent('#swpt-be-payer')) === swptPct(swpt2.options.payer.breakeven), { swptR2, vol: swpt2.vol });
    // beyond 10Y: refused in Turkish beside the inputs, the tenors too long for the expiry dimmed
    await page.click('#swpt-expiry-presets button[data-v="5Y"]');
    await swptLabel('^5Y × 9M');
    const swptFar = await page.evaluate(() => [...document.querySelectorAll('#swpt-tenor-presets button.swpt-far')].map((b) => b.dataset.v).join());
    await page.click('#swpt-tenor-presets button[data-v="7Y"]');
    await page.waitForFunction(() => /10 yıl/.test(document.getElementById('swpt-error').textContent), null, { timeout: 30000 });
    check('... 5Y × 7Y: refused in Turkish (the TRY OIS curve ends at 10Y), 7Y and 10Y dimmed for a 5Y expiry, the last numbers kept dimmed',
      swptFar === '7Y,10Y' && /TRY OIS eğrisi 10Y'de biter/.test(await page.textContent('#swpt-error'))
      && await page.evaluate(() => document.getElementById('swpt-result').classList.contains('stale'))
      && (await api(page, 'ayşe yilmaz', 'GET', '/api/swaption?expiry=5Y&tenor=7Y')).status === 400, { swptFar });
    await page.click('#swpt-tenor-presets button[data-v="5Y"]');
    await swptLabel('^5Y × 5Y');

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
    // what a bond's row holds is the bond's: a manual clean price follows it when its ISIN goes to another row of the list
    const rvRowOf = (code) => page.evaluate((c) => {
      for (let r = 5; r <= 54; r++) { const td = window.tto.findCell('DİBS RV!A' + r); if (td && td.textContent.trim() === c) return r; }
      return 0;
    }, code);
    const moving = 'TRT081128T15';
    const fromRow = await rvRowOf(moving);
    const toRow = 1 + await page.evaluate(() => {
      let last = 0;
      for (let r = 5; r <= 54; r++) { const td = window.tto.findCell('DİBS RV!A' + r); if (td && td.textContent.trim()) last = r; }
      return last;
    });
    await typeInto(page, 'DİBS RV!N' + fromRow, '98,5');
    await waitCell(page, 'DİBS RV!N' + fromRow, '/^98,5/.test(t)');
    await typeInto(page, 'DİBS RV!A' + toRow, moving);
    await waitCell(page, 'DİBS RV!A' + toRow, 't.trim() === "' + moving + '"');
    await (await cellHandle(page, 'DİBS RV!A' + fromRow)).click();
    await page.keyboard.press('Delete');
    await waitCell(page, 'DİBS RV!N' + toRow, '/^98,5/.test(t)').catch(() => {});
    const followed = { from: fromRow, to: toRow, priceThere: await cellText(page, 'DİBS RV!N' + toRow),
      priceHere: await cellText(page, 'DİBS RV!N' + fromRow), said: await page.textContent('#toasts') };
    check('DİBS RV: a manual clean price follows its bond when the ISIN moves to another row of the list - the one who moved it is told',
      fromRow > 0 && /^98,5/.test(followed.priceThere) && followed.priceHere.trim() === ''
      && followed.said.includes(moving + ' satır ' + fromRow + ' → ' + toRow), followed);
    // back where it was (the price with it), then the price off
    await typeInto(page, 'DİBS RV!A' + fromRow, moving);
    await waitCell(page, 'DİBS RV!A' + fromRow, 't.trim() === "' + moving + '"');
    await (await cellHandle(page, 'DİBS RV!A' + toRow)).click();
    await page.keyboard.press('Delete');
    await waitCell(page, 'DİBS RV!N' + fromRow, '/^98,5/.test(t)').catch(() => {});
    const rvBack = { price: await cellText(page, 'DİBS RV!N' + fromRow), here: await cellText(page, 'DİBS RV!A' + fromRow),
      there: await cellText(page, 'DİBS RV!A' + toRow) };
    check('... and back with it to its row', /^98,5/.test(rvBack.price) && rvBack.here.trim() === moving && rvBack.there.trim() === '', rvBack);
    await (await cellHandle(page, 'DİBS RV!N' + fromRow)).click();
    await page.keyboard.press('Delete');
    await waitCell(page, 'DİBS RV!N' + fromRow, 't.trim() === ""').catch(() => {});
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
    // the way back in bulk: two value dates pasted, then the table's own USDTRY / EURTRY forwards pasted into the new
    // columns read back the TRY rate they were priced with (RET mid: no manual rate)
    await page.evaluate(() => navigator.clipboard.writeText('15.01.2027\r\n15.04.2027\r\n'));
    await (await cellHandle(page, 'EK_BULK!B5')).click();
    await page.keyboard.press('Control+v');
    await waitCell(page, 'EK_BULK!P6', 't.trim() !== ""');
    const bulkN = [(await cellText(page, 'EK_BULK!N5')).trim(), (await cellText(page, 'EK_BULK!N6')).trim()];
    const bulkP = [(await cellText(page, 'EK_BULK!P5')).trim(), (await cellText(page, 'EK_BULK!P6')).trim()];
    for (const [col, vals] of [['R', bulkN], ['T', bulkP]]) {
      await page.evaluate((t) => navigator.clipboard.writeText(t), vals.join('\r\n') + '\r\n');
      await (await cellHandle(page, 'EK_BULK!' + col + '5')).click();
      await page.keyboard.press('Control+v');
    }
    await waitCell(page, 'EK_BULK!U6', 't.trim() !== ""');
    const bulkBack = {};
    for (const c of ['G5', 'G6', 'S5', 'S6', 'U5', 'U6']) bulkBack[c] = trNumber(await cellText(page, 'EK_BULK!' + c));
    check('Toplu fiyatlama: two outrights pasted (the table\'s own USDTRY and EURTRY forwards) read back their implied TRY rate - the RET mid they were priced with',
      [5, 6].every((r) => Math.abs(bulkBack['S' + r] - bulkBack['G' + r]) < 0.01 && Math.abs(bulkBack['U' + r] - bulkBack['G' + r]) < 0.01)
      && bulkN.every((t) => /\d,\d{4}$/.test(t)), { bulkN, bulkP, bulkBack });
    // TOPLU FORWARD → işlem (the desk, 24.11.2026: "3 ekle"): a right click on a row's EURTRY fwd fills Günlük İşlemler's
    // form - EURTRY (the column's own pair), the row's valör, the outright clicked; no side, no amount
    await (await cellHandle(page, 'EK_BULK!P6')).click({ button: 'right' });
    await page.waitForSelector('.menu');
    const bulkMenu = await page.$$eval('.menu button', (bs) => bs.map((b) => b.textContent));
    await page.click('.menu button:text-is("İşlem gir")');
    await page.waitForFunction(() => window.tto.state.pageId === 'blotter' && window.tto.state.page && window.tto.state.page.fwd
      && window.tto.state.page.fwd.date && window.tto.state.page.fwd.date.value !== '', null, { timeout: 30000 });
    const bulkFwd = await page.evaluate(() => { const f = window.tto.state.page.fwd; return [f.pair, f.dir, f.basis, f.date.value, f.manual.value, f.amount.value]; });
    check('TOPLU FORWARD: a right click on a row\'s EURTRY fwd offers "İşlem gir" - Günlük İşlemler opens on EURTRY, the row\'s valör, that outright; no side, no amount',
      bulkMenu[0] === 'İşlem gir' && JSON.stringify(bulkFwd) === JSON.stringify(['EURTRY', null, 'FWD', '15.04.2027', bulkP[1], '']), [bulkMenu, bulkFwd, bulkP]);
    await open(page, 'blotter');
    const fxBefore3 = (await fxRows()).length;
    // ... and "İşleme al": Parite / Yön / Tutar typed on the rows (the outrights typed back taken off: RET mid prices them);
    // every row with a Tutar opens in "Excel'den yapıştır" on FX Forward at the price it shows, a Tutar without a valör is an
    // error row, a priced row without a Tutar is left out and said
    await open(page, 'forward');
    await tab(page, 'bulk');
    await api(page, 'ayşe yilmaz', 'POST', '/api/reset', { book: 'tto', refs: ['EK_BULK!R5:R6', 'EK_BULK!T5:T6'] });
    await waitCell(page, 'EK_BULK!S6', 't.trim() === ""');
    const typeOver = async (ref, text) => {                 // (a list cell: typed over, not picked from its menu)
      await (await cellHandle(page, ref)).click();
      await page.keyboard.type(text);
      await page.keyboard.press('Enter');
    };
    await (await cellHandle(page, 'EK_BULK!W5')).click();
    await page.keyboard.press('Enter');                     // the side's list: its items to pick
    await page.click('.menu button:text-is("AL")');
    await typeInto(page, 'EK_BULK!X5', '1m');
    await typeInto(page, 'EK_BULK!Y5', 'E2E BANKA');
    await typeOver('EK_BULK!V6', 'eur');
    await typeOver('EK_BULK!W6', 'Satış');
    await typeInto(page, 'EK_BULK!X6', '2,5mn');
    await typeInto(page, 'EK_BULK!B7', '15.07.2027');
    await waitCell(page, 'EK_BULK!N7', 't.trim() !== ""');
    await typeOver('EK_BULK!W8', 'al');
    await typeInto(page, 'EK_BULK!X8', '3m');
    await waitCell(page, 'EK_BULK!X8', 't.trim() !== ""');
    const typedBook = {};
    for (const c of ['V6', 'W5', 'W6', 'X5', 'X6', 'Y5']) typedBook[c] = (await cellText(page, 'EK_BULK!' + c)).trim();
    const bookN5 = (await cellText(page, 'EK_BULK!N5')).trim();
    const bookP6 = (await cellText(page, 'EK_BULK!P6')).trim();
    await page.click('.panel[data-panel="BK1"] button[data-action="toplu-islem"]');
    await page.waitForSelector('#bulk-dialog');
    await page.waitForFunction(() => document.querySelectorAll('#bulk-preview tr.line').length === 3, null, { timeout: 20000 });
    const bookRows = await page.evaluate(() => [...document.querySelectorAll('#bulk-preview tr.line')].map((tr) => [tr.className, tr.querySelector('td.st').textContent]));
    const bookSaid = await page.textContent('#bulk-source');
    const bookKinds = await page.evaluate(() => [...document.querySelectorAll('#bulk-kind button')].map((b) => b.dataset.v + (b.disabled ? '-' : '') + (b.classList.contains('on') ? '!' : '')));
    await shot(page, '04e-toplu-forward-islem');
    check('... "İşleme al": the rows with a Tutar in "Excel\'den yapıştır" on FX Forward - USDTRY at its row\'s forward (RET mid), EURTRY at its EURTRY fwd; the Tutar without a valör says so; the priced row without a Tutar is said left out',
      JSON.stringify(typedBook) === JSON.stringify({ V6: 'EURTRY', W5: 'AL', W6: 'SAT', X5: '1.000.000', X6: '2.500.000', Y5: 'E2E BANKA' })
      && /good/.test(bookRows[0][0]) && bookRows[0][1].startsWith('✓ USDTRY alış 1.000.000 USD · 15.01.2027 · forward ' + bookN5 + ' · TRY ')
      && /good/.test(bookRows[1][0]) && bookRows[1][1].startsWith('✓ EURTRY satış 2.500.000 EUR · 15.04.2027 · forward ' + bookP6 + ' · TRY ')
      && /bad/.test(bookRows[2][0]) && /valör yok/.test(bookRows[2][1]) && /Tutar'ı yazılı 3 satır · Tutar'ı boş 1 satır alınmadı/.test(bookSaid)
      && bookKinds.join() === 'fwd!,ois-,bond-' && (await page.textContent('#bulk-save')) === '2 satırı kaydet', { typedBook, bookRows, bookSaid, bookKinds, bookN5, bookP6 });
    await page.click('#bulk-save');
    await page.waitForFunction(() => /2 işlem kaydedildi; tutarları temizlendi/.test(document.getElementById('toasts').textContent), null, { timeout: 20000 });
    await page.waitForFunction(() => document.querySelectorAll('#bulk-preview tr.line').length === 1, null, { timeout: 20000 });
    const bookLeft = await page.inputValue('#bulk-text');
    await page.keyboard.press('Escape');
    await page.waitForSelector('#bulk-dialog', { state: 'detached' });
    await waitCell(page, 'EK_BULK!X6', 't.trim() === ""');
    const bookAfter = {};
    for (const c of ['X5', 'X6', 'X8', 'W5', 'V6', 'Y5', 'B5', 'N5']) bookAfter[c] = (await cellText(page, 'EK_BULK!' + c)).trim();
    const booked = (await api(page, 'ayşe yilmaz', 'GET', '/api/blotter')).json.trades.filter((t) => /^TOPLU FORWARD · /.test(t.note || ''));
    check('... "2 satırı kaydet": the two booked in one go, noted "TOPLU FORWARD · RET mid %"; their Tutar emptied in the table - valör, Parite, Yön, Karşı taraf and prices stay; the row to fix left in the box with its Tutar',
      booked.length === 2 && booked.every((t) => t.note === 'TOPLU FORWARD · RET mid %')
      && JSON.stringify(booked.map((t) => [t.pair, t.dir, t.amount, t.cpt]).sort()) === JSON.stringify([['EURTRY', 'S', 2500000, ''], ['USDTRY', 'B', 1000000, 'E2E BANKA']])
      && bookAfter.X5 === '' && bookAfter.X6 === '' && bookAfter.X8 === '3.000.000' && bookAfter.W5 === 'AL' && bookAfter.V6 === 'EURTRY'
      && bookAfter.Y5 === 'E2E BANKA' && bookAfter.B5 === '15.01.2027' && bookAfter.N5 === bookN5
      && /^Satır\tParite\tYön\tTutar\tValör/.test(bookLeft) && bookLeft.split('\n').length === 2 && /\t3\.000\.000\t/.test(bookLeft),
      { bookAfter, booked, bookLeft });
    await open(page, 'blotter');
    await page.waitForFunction((n) => document.querySelectorAll('.lists .panel:nth-child(1) table.grid tr').length === n + 2, fxBefore3, { timeout: 20000 });
    const bookList = (await fxRows()).slice(-2);
    const bookAmount = (await fxRows())[0].indexOf('Tutar (döviz)');
    check('... and they are in Günlük İşlemler\'s forward list today', bookList.map((r) => r[bookAmount]).join('|') === '1.000.000|2.500.000', bookList);
    // a second press: nothing booked twice - only the row still to fix
    await open(page, 'forward');
    await tab(page, 'bulk');
    await page.click('.panel[data-panel="BK1"] button[data-action="toplu-islem"]');
    await page.waitForSelector('#bulk-dialog');
    await page.waitForFunction(() => document.querySelectorAll('#bulk-preview tr.line').length === 1, null, { timeout: 20000 });
    const bookAgain = await page.evaluate(() => [...document.querySelectorAll('#bulk-preview tr.line')].map((tr) => tr.querySelector('td.st').textContent));
    await page.keyboard.press('Escape');
    await page.waitForSelector('#bulk-dialog', { state: 'detached' });
    check('... pressed again, only the row still to fix comes: the booked rows are not booked twice', bookAgain.length === 1 && /valör yok/.test(bookAgain[0]), bookAgain);
    await api(page, 'ayşe yilmaz', 'POST', '/api/reset', { book: 'tto', refs: ['EK_BULK!V5:Y8', 'EK_BULK!B7'] });
    // points -> rate (proposal #2): FORWARD STARTING SWAP's own "Manuel" FS points typed back read its TRY fwd-fwd %; ÇAPRAZ
    // FORWARD's own manual USDTRY forward typed back reads its TRY rate
    await typeInto(page, 'Forward!C167', '08.12.2026');
    await typeInto(page, 'Forward!C168', '08.03.2027');
    await typeInto(page, 'Forward!C169', '40,5');
    await waitCell(page, 'Forward!I179', 't.trim() !== ""');
    const fsPts = (await cellText(page, 'Forward!I179')).trim();
    await typeInto(page, 'Forward!I181', fsPts);
    await waitCell(page, 'Forward!E181', 't.trim() !== ""');
    const fsBack = { rate: trNumber(await cellText(page, 'Forward!E181')), ois: (await cellText(page, 'Forward!P181')).trim() };
    await (await cellHandle(page, 'Forward!C197')).click();          // (a drop-down cell: Enter opens its list)
    await page.keyboard.press('Enter');
    await page.click('.menu button:text-is("USD")');
    await waitCell(page, 'Forward!C197', 't.trim() === "USD"');
    await typeInto(page, 'Forward!F200', '41');
    await waitCell(page, 'Forward!Q200', 't.trim() !== ""');
    const crossFwd = (await cellText(page, 'Forward!Q200')).trim();
    await typeInto(page, 'Forward!R200', crossFwd);
    await waitCell(page, 'Forward!S200', 't.trim() !== ""');
    const crossBack = trNumber(await cellText(page, 'Forward!S200'));
    check('Forward starting swap: its own FS points typed back ("Elle puan → faiz") read its TRY fwd-fwd % and the bp over OIS mid; '
      + 'Çapraz forward: its own USDTRY forward typed back reads its TRY rate',
      Math.abs(fsBack.rate - 40.5) < 0.006 && /^[+−-]?\d/.test(fsBack.ois) && Math.abs(crossBack - 41) < 0.001, { fsPts, fsBack, crossFwd, crossBack });
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
    const listsOf = async (isin) => (await api(page, 'ayşe yilmaz', 'GET', '/api/bonds/catalog')).json.bonds.find((b) => b.isin === isin).lists;
    const offBoth = await listsOf('TRT130127T11');
    check('... and ★ takes it off - off the DİBS ASW list too', unstarred && !offBoth.includes('dibs') && !offBoth.includes('asw'), offBoth);
    // the summary's columns in groups, each bond's fair yield and price on DİBS RV's fitted ASW curves (OIS, FX swap)
    const sumRows = await summaryRows();
    const groupRow = sumRows[0];
    const capRow = sumRows[1];
    const mar28 = sumRows.find((r) => r[2] === 'TRT150328T24') || [];
    const fairAt = capRow.indexOf('Adil getiri %');
    check('DİBS Trading: the summary in groups (Fiyat · OIS\'e göre · FX swap\'a göre · Risk · Carry · Broker), each bond\'s fair yield and price',
      ['Fiyat', "OIS'e göre", "FX swap'a göre", 'Risk', 'Carry', 'Broker'].every((g) => groupRow.includes(g)) && fairAt > 0
      && capRow.lastIndexOf('Adil getiri %') > fairAt && /^\d+,\d\d%$/.test(mar28[fairAt]) && /^\d+,\d{3}$/.test(mar28[fairAt + 1])
      && capRow[2] === 'ISIN' && capRow[1] === 'Kâğıt', { groupRow, capRow, mar28 });
    const fairTip = await page.evaluate((i) => { const tr = [...document.querySelectorAll('.panel[data-panel="L0"] table.grid tr')]
      .find((x) => x.children[2] && x.children[2].textContent === 'TRT150328T24'); return tr ? tr.children[i].title : ''; }, fairAt);
    check('... a fair value says how it is made', /OIS ASW eğrisi/.test(fairTip) && /annuity/.test(fairTip), fairTip);
    // "+ ISIN ekle" on DİBS Trading: the bond goes onto the DİBS ASW list too (the toast says so); ★ takes it off both
    await page.click('.panel[data-panel="L1"] button[data-action="add-isin"]');
    await page.fill('#isin-text', 'TRT190128T14');
    await page.click('#isin-add');
    // (this bond's own toast, which comes with the add's answer: the ☆ step's "DİBS ASW'ye de eklendi: 13.01.27 TLREF" may
    // still be up, and waiting for that one opened DİBS ASW while the add was still writing the list)
    const toldAsw = await page.waitForFunction(() => /DİBS ASW'ye de eklendi: 19\.01\.28/.test(document.querySelector('#toasts').textContent), null,
      { timeout: 20000 }).then(() => true, () => false);
    await open(page, 'asw');
    await page.waitForSelector('.panel[data-panel="tbl"] table.grid');
    const onAsw = await page.evaluate(() => [...document.querySelectorAll('.panel[data-panel="tbl"] table.grid tr')]
      .some((tr) => tr.children[0] && tr.children[0].textContent.trim() === 'TRT190128T14'));
    check('a bond added on DİBS Trading ("+ ISIN ekle") is on the DİBS ASW list too, the toast says so', toldAsw && onAsw, { toldAsw, onAsw });
    await open(page, 'dibslive');
    await page.waitForSelector(flagOf('L0', 'TRT190128T14'));
    await page.click(flagOf('L0', 'TRT190128T14'));
    await page.waitForFunction(() => ![...document.querySelectorAll('.panel[data-panel="L0"] table.grid tr')]
      .some((tr) => tr.children[2] && tr.children[2].textContent === 'TRT190128T14'), null, { timeout: 20000 }).catch(() => {});
    const tradingGone = await listsOf('TRT190128T14');
    check('... and ★ off takes it off both lists', !tradingGone.includes('dibs') && !tradingGone.includes('asw'), tradingGone);
    // the value dates: the rows that hold no bond (DİBS RV's group separators, the unused rows) are not shown
    const liveIsins = await page.evaluate(() => [...document.querySelectorAll('.panel[data-panel="L1"] table.grid tr')].map((tr) => (tr.children[0] || {}).textContent || ''));
    const firstBond = liveIsins.findIndex((t) => /^TR[A-Z0-9]{9}\d$/.test(t));
    check('DİBS Trading · valörler: only the rows that hold a bond', firstBond > 0
      && liveIsins.slice(firstBond, firstBond + 19).every((t) => /^TR[A-Z0-9]{9}\d$/.test(t)), liveIsins);
    // DİBS RV: one menu entry (Tahvil) with three tabs - Genel, the RV and the ASW hesap tablosu; the old addresses as before
    const dibsMenu = await page.evaluate(() => {
      const a = document.querySelector('#nav .nav-item[data-page="tahvil.dibsrv"]');
      return { tabs: a ? a.dataset.tabs : null, label: a ? a.textContent : '',
        alone: ['dibs', 'asw', 'dibs-genel'].filter((x) => document.querySelector('#nav .nav-item[data-page="' + x + '"]')) };
    });
    check('Tahvil → DİBS RV: one menu entry with three tabs (Genel, RV hesap tablosu, ASW hesap tablosu), no separate entries',
      dibsMenu.tabs === 'dibs-genel dibs asw' && /DİBS RV/.test(dibsMenu.label) && dibsMenu.alone.length === 0, dibsMenu);
    await open(page, 'dibs-genel');
    await page.waitForFunction(() => document.querySelector('#dg-grid') && document.querySelectorAll('#dg-asw-fx svg.chart circle.mk').length > 0
      && document.querySelector('#dg-switch table.grid') && document.querySelectorAll('#dg-yield svg.chart circle.mk').length > 0, null, { timeout: 60000 });
    const gData = (await api(page, 'ayşe yilmaz', 'GET', '/api/dibs/genel')).json;
    const mirrors = (await api(page, 'ayşe yilmaz', 'POST', '/api/panels', { items: gData.mirrors.map((m) => ({ view: m.view, panel: m.panel, key: m.key })) })).json;
    const dgMarks = (data) => data.series.filter((x) => x.marker || x.noline).reduce((n, x) => n + x.x.length, 0);
    const genelSeen = await page.evaluate(() => {
      const rows = [...document.querySelectorAll('#dg-grid tr')].map((tr) => [...tr.children].map((td) => td.textContent));
      const n = (sel) => document.querySelectorAll(sel).length;
      return { tabs: [...document.querySelectorAll('#page-tabs button')].map((b) => b.textContent), on: [...document.querySelectorAll('#page-tabs button.on')].map((b) => b.dataset.page),
        lit: [...document.querySelectorAll('#nav .nav-item.active')].map((a) => a.dataset.page), groups: rows[0] || [],
        bonds: rows.filter((r) => /^TR[A-Z0-9]{9}\d$/.test(r[1] || '')).map((r) => r[1]),
        yieldMk: n('#dg-yield svg.chart circle.mk'), yieldPt: n('#dg-yield svg.chart text.pt'), oisMk: n('#dg-asw-ois svg.chart circle.mk'),
        fxMk: n('#dg-asw-fx svg.chart circle.mk'), histLines: n('#dg-hist svg.chart path'), fit: (document.querySelector('#dg-fit') || {}).textContent || '',
        sets: n('#dg-settings .dg-set') };
    });
    const gBonds = gData.table.isin.filter(Boolean);
    await shot(page, '12b-dibs-genel');
    check('DİBS RV · Genel: its three tabs, the entry lit, the table in its groups (OIS ASW · FX swap ASW on the FX swap ima eğrisi · sıfır kupon) with every bond of the trading list',
      genelSeen.tabs.join('|') === 'Genel|RV hesap tablosu|ASW hesap tablosu' && genelSeen.on.join() === 'dibs-genel' && genelSeen.lit.join() === 'tahvil.dibsrv'
      && genelSeen.groups.includes('OIS ASW') && genelSeen.groups.includes('Sıfır kupon eğrisi (NS)') && genelSeen.groups.some((g) => /^FX swap ASW · FX swap ima eğrisi \(TRYI 1–9A FX swap ima, TRYSAQ 1–10Y XCCY, 18A XCCY eğrisinden/.test(g))
      && genelSeen.bonds.length === gBonds.length && gBonds.length >= 19 && genelSeen.bonds.every((x) => gBonds.includes(x)) && /RMSE \d+,\d bp · LOO RMSE \d+,\d bp/.test(genelSeen.fit) && genelSeen.sets === 5,
    { genelSeen, gBonds: gBonds.length });
    check('... its three charts with their points: the yield curve (bonds and OIS), ASW · OIS and ASW · FX swap as DİBS ASW draws them',
      genelSeen.yieldMk === dgMarks(gData.chart) && gData.chart.series[0].x.length >= 15 && genelSeen.yieldPt >= 8
      && genelSeen.yieldPt <= gData.chart.series[0].x.length
      && genelSeen.oisMk === dgMarks(mirrors.panels.asw_ois.entry.data) && genelSeen.fxMk === dgMarks(mirrors.panels.asw_fx.entry.data) && genelSeen.fxMk > 10,
    { genelSeen, want: [dgMarks(gData.chart), dgMarks(mirrors.panels.asw_ois.entry.data), dgMarks(mirrors.panels.asw_fx.entry.data)] });
    // a setting shown on Genel opens in the RV hesap tablosu, its cell selected; a tab of the entry opens the sheet's page
    const selectedRef = () => page.evaluate(() => { const td = document.querySelector('#content table.grid td.cur'); const g = td && td.closest('table').__grid;
      return g ? g.ref(td.__i, td.__j) : null; });
    await page.click('#dg-settings .dg-set[data-ref="DİBS RV!P2"]');
    await page.waitForFunction(() => window.tto.state.pageId === 'dibs' && window.tto.state.page && window.tto.state.page.ready, null, { timeout: 60000 });
    await page.waitForFunction(() => !!document.querySelector('#content table.grid td.cur'), null, { timeout: 20000 }).catch(() => {});
    const setRef = await selectedRef();
    const rvTabs = await page.evaluate(() => ({ tabs: [...document.querySelectorAll('#page-tabs button')].map((b) => b.dataset.page),
      on: [...document.querySelectorAll('#page-tabs button.on')].map((b) => b.dataset.page), lit: [...document.querySelectorAll('#nav .nav-item.active')].map((a) => a.dataset.page) }));
    check('... a setting on Genel (Sinyal eşiği) opens in the RV hesap tablosu tab, its cell selected; #/dibs is that tab of the entry',
      setRef === 'DİBS RV!P2' && rvTabs.tabs.join() === 'dibs-genel,dibs,asw' && rvTabs.on.join() === 'dibs' && rvTabs.lit.join() === 'tahvil.dibsrv', { setRef, rvTabs });
    await open(page, 'dibs-genel');
    await page.waitForSelector('#dg-switch table.grid td.in');
    const swRef = await page.evaluate(() => { const td = document.querySelector('#dg-switch table.grid td.in'); const g = td.closest('table').__grid; return g.ref(td.__i, td.__j); });
    await page.click('#dg-switch table.grid td.in');
    await page.waitForFunction(() => window.tto.state.pageId === 'dibs' && window.tto.state.page && window.tto.state.page.ready, null, { timeout: 60000 });
    await page.waitForFunction((r) => { const td = document.querySelector('#content table.grid td.cur'); const g = td && td.closest('table').__grid;
      return g && g.ref(td.__i, td.__j) === r; }, swRef, { timeout: 20000 }).catch(() => {});
    check('... a cell of the switch / pair table shown on Genel is read-only there: a click opens it in the RV hesap tablosu, selected',
      /^DİBS RV!/.test(swRef || '') && await selectedRef() === swRef, { swRef, now: await selectedRef() });
    await open(page, 'asw');
    const aswTabs = await page.evaluate(() => [...document.querySelectorAll('#page-tabs button.on')].map((b) => b.dataset.page).join());
    check('... #/asw opens the ASW hesap tablosu tab as before', aswTabs === 'asw', aswTabs);
    // ------------------------------------------------------------------ Kâğıt Fiyatlama: one fair per bond, a quote, the good levels
    // (the recorded file has no bond history: tests/test_e2e.py put three days of closes of the trading list's bonds in the
    // database - the sheet's own compound yields, 26–28.08.2026, outside every window the other checks read; no OIS curve
    // those days, so the neighbours' curve alone, σ its floor: two next-day errors are too few to measure)
    console.log('kagit fiyatlama');
    await open(page, 'kagit-fiyat');
    await page.waitForSelector('#kf-table tr.kf-main', { timeout: 60000 });
    const kfApi = (await api(page, 'ayşe yilmaz', 'GET', '/api/kagit-fiyat')).json;
    const kfFmt = (v) => v.toFixed(2).replace('.', ',');
    // the main table (Eğri fiyatı, the desk's 20.11.2026: "curve'e göre fiyatı olmayanların da fiyatını bulmak içindi asıl"):
    // every fixed coupon bond, bill and zero coupon bond of the desk's list - Piyasa / Eğri / Fiyat with its label
    const kfMain = await page.evaluate(() => {
      const row = (isin) => { const tr = document.querySelector('#kf-table tr.kf-main[data-isin="' + isin + '"]');
        if (!tr) return {};
        const t = (c) => (tr.querySelector('td.kf-' + c) || {}).textContent;
        return { mkt: t('mkt-y'), src: t('mkt-src'), crv: t('crv-y'), px: t('px-y'), pxp: t('px-p'), label: t('px-label'), diff: t('diff'), toggle: t('toggle'),
          pxTip: (tr.querySelector('td.kf-px-y') || {}).title || '' };
      };
      return { fixed: row('TRT150328T24'), off: row('TRT240227T17'), zero: row('TRT060127T10'), n: document.querySelectorAll('#kf-table tr.kf-main').length,
        head: (document.getElementById('kf-head-line') || {}).textContent || '', others: (document.getElementById('kf-others') || {}).textContent || '',
        open: document.querySelectorAll('#kf-table tr.kf-detail:not(.kf-closed)').length };
    });
    const kfC = (isin) => (kfApi.curve_rows || []).find((r) => r.isin === isin) || {};
    const kfCF = kfC('TRT150328T24'), kfCO = kfC('TRT240227T17'), kfCZ = kfC('TRT060127T10');
    check('Kâğıt Fiyatlama: the main table - every fixed coupon bond, bill and zero coupon bond of the desk\'s list (off the trading list too), '
      + 'Piyasa / Eğri / Fiyat with its label: the trading list\'s bond at its market ("piyasa", market − Eğri in bp); off it, no history: a fixed '
      + 'coupon bond at the curve alone ("eğri"), a zero coupon bond at its bucket\'s base (OIS %75 + eğri %25) + the market-priced bills\' median '
      + 'spread ("eğri + akran farkı"), each with its typical error in the Fiyat tooltip; the floaters counted under it; the details closed',
      kfMain.n === (kfApi.curve_rows || []).length && kfMain.n >= 29 && /^Fiyatı olmayan kâğıtlara eğriden fiyat:/.test(kfMain.head)
      && kfMain.fixed.label === 'piyasa' && kfMain.fixed.px === kfFmt(kfCF.price.yield) && kfMain.fixed.mkt === kfFmt(kfCF.market.yield)
      && kfMain.fixed.crv === kfFmt(kfCF.curve.yield) && /DİBS RV bid \/ ask ortası/.test(kfMain.fixed.src) && /^[+−]?\d+$/.test(kfMain.fixed.diff)
      && kfMain.off.label === 'eğri' && kfMain.off.mkt === '—' && kfMain.off.px === kfFmt(kfCO.price.yield) && kfMain.off.px === kfMain.off.crv
      && kfCO.curve.base === 'eğri' && kfCO.base.text === 'OIS %75 + eğri %25' && /tipik hata ±\d+ bp/.test(kfMain.off.pxTip)
      && kfMain.zero.label === 'eğri + akran farkı' && kfMain.zero.crv === kfFmt(kfCZ.curve.yield) && kfCZ.curve.base === 'OIS %75 + eğri %25'
      && kfCZ.price.peers === 2 && Math.abs(kfCZ.price.yield - kfCZ.curve.yield - kfCZ.price.spread / 100) < 1e-9 && /tipik hata ±\d+ bp/.test(kfMain.zero.pxTip)
      && kfMain.off.pxp === kfCO.price.clean.toFixed(3).replace('.', ',') && /TLREF'e endeksli \d+/.test(kfMain.others) && kfMain.open === 0
      && /eğri \+ akran farkı \d+/.test(kfMain.others) && kfMain.fixed.toggle === '▸', { kfMain, fixed: kfCF.price, off: kfCO.price, zero: kfCZ.price });
    // ▸ opens a bond's details: the row the page showed before, unchanged (the checks below read it)
    await page.click('#kf-table tr.kf-main[data-isin="TRT150328T24"] td.kf-toggle');
    await page.waitForSelector('#kf-table tr.kf-row[data-isin="TRT150328T24"]', { timeout: 20000 }).catch(() => {});
    const kfOpened = await page.evaluate(() => ({ toggle: (document.querySelector('#kf-table tr.kf-main[data-isin="TRT150328T24"] td.kf-toggle') || {}).textContent,
      open: [...document.querySelectorAll('#kf-table tr.kf-detail:not(.kf-closed)')].map((tr) => tr.dataset.isin),
      off: (document.querySelector('#kf-table tr.kf-detail[data-isin="TRT240227T17"]') || {}).textContent || '' }));
    check('... ▸ opens a bond\'s details (the fair, Öngörülen, the quote, the levels, the market - the row as before); a bond off the trading '
      + 'list has none (said)', kfOpened.toggle === '▾' && kfOpened.open.join() === 'TRT150328T24' && /yalnız trading listesindeki/.test(kfOpened.off), kfOpened);
    // (each cell read by its class: the table's columns are grouped - fair, Öngörülen, OIS'e göre, FX swap'a göre, the quote…)
    const kfRead = () => page.evaluate(() => {
      const row = (isin) => { const tr = document.querySelector('#kf-table tr.kf-row[data-isin="' + isin + '"]');
        if (!tr) return {};
        const out = { all: [...tr.children].map((td) => td.textContent) };
        for (const k of ['fair', 'bid', 'ask', 'buy', 'sell', 'sigma', 'hit', 'proj', 'ois-y', 'fx-y']) {
          const td = tr.querySelector('td.kf-' + k);
          out[k] = td ? td.textContent : null;
        }
        out.simple = (tr.children[5] || {}).textContent;
        return out;
      };
      // the main table's Öngörülen (yield over price, the model) and OIS'e / FX swap'a göre (yield over price)
      const cols = (isin) => { const tr = document.querySelector('#kf-table tr.kf-main[data-isin="' + isin + '"]');
        if (!tr) return {};
        const out = {};
        for (const k of ['proj', 'ois', 'fx']) {
          const td = tr.querySelector('td.kf-m-' + k);
          const y = td && td.querySelector('.kf-2l-y'), p = td && td.querySelector('.kf-2l-p');
          Object.assign(out, { [k]: y ? y.textContent : (td || {}).textContent, [k + 'P']: p ? p.textContent : null, [k + 'Tip']: (td || {}).title || '' });
        }
        out.model = (tr.querySelector('td.kf-m-proj-model') || {}).textContent;
        return out;
      };
      const how = (isin) => (document.querySelector('#kf-table tr.kf-how[data-isin="' + isin + '"]') || {}).textContent || '';
      return { menu: window.tto.state.pages.filter((p) => p.group === 'Tahvil').map((p) => p.id), fixed: row('TRT150328T24'),
        cols: cols('TRT150328T24'), colsOff: cols('TRT240227T17'),
        mainGroups: [...document.querySelectorAll('#kf-table tr.kf-main-groups th')].map((th) => th.textContent),
        others: (document.getElementById('kf-others') || {}).textContent || '', how: how('TRT150328T24'), rows: document.querySelectorAll('#kf-table tr.kf-row').length,
        priced: document.querySelectorAll('#kf-table tr.kf-row:not(.kf-off)').length, info: document.getElementById('kf-info').textContent,
        width: (document.getElementById('kf-width-3y') || {}).tagName || '',
        groups: [...document.querySelectorAll('#kf-table tr.kf-groups th')].map((th) => th.textContent),
        ufuk: [...document.querySelectorAll('#kf-ufuk button')].map((b) => b.id + (b.classList.contains('on') ? '*' : '')) };
    });
    const kfSeen = await kfRead();
    const kfF = kfApi.rows.find((r) => r.isin === 'TRT150328T24') || {};
    check('Kâğıt Fiyatlama: first in Tahvil; every bond of the trading list in the details - a fixed coupon bond with its fair (compound, simple, price), '
      + 'its quote (bid / ask, 10 bp wide), the good levels (Al ≥ fair + 2σ, Sat ≤ fair − 2σ: the buy level\'s price under fair\'s), σ '
      + 'its 1–3Y floor (the history short), no backtest yet, and how it was priced; the TLREF floaters counted with why under the table',
      kfSeen.menu[0] === 'kagit-fiyat' && kfSeen.rows === kfApi.rows.filter((r) => r.kind === 'S' || r.kind === 'B').length && kfSeen.rows >= 15
      && kfSeen.priced >= 12
      && kfF.priced && kfSeen.fixed.fair === kfFmt(kfF.fair.yield) && kfSeen.fixed.simple === kfFmt(kfF.fair.simple)
      && kfSeen.fixed.bid === kfFmt(kfF.quote.bid.yield) && kfSeen.fixed.ask === kfFmt(kfF.quote.ask.yield) && kfF.quote.width === 10
      && kfSeen.fixed.buy === kfFmt(kfF.levels.buy.yield) && kfSeen.fixed.sell === kfFmt(kfF.levels.sell.yield)
      && kfF.levels.buy.yield > kfF.fair.yield && kfF.fair.yield > kfF.levels.sell.yield && kfF.levels.buy.clean < kfF.fair.clean
      && kfSeen.fixed.sigma === '23*' && kfF.sigma.short && kfSeen.fixed.hit === 'isabet – (0)'
      && kfSeen.how.startsWith('Nasıl fiyatlandı: ' + kfF.line) && /^Komşu eğri \d+,\d\d \+ 28\.08 kapanışındaki fark [+−]?\d+ bp = \d+,\d\d · %100 → adil \d+,\d\d · fiyat \d+,\d{3} \(valör 04\.11\)$/.test(kfF.line)
      && /TLREF'e endeksli \d+/.test(kfSeen.others) && /nominal eğriye göre fiyatlanmaz/.test(kfSeen.others)
      && /Geçmiş: 3 kapanış \(26\.08\.2026 – 28\.08\.2026\)/.test(kfSeen.info) && kfSeen.width === 'INPUT',
    { kfSeen, line: kfF.line, why: kfF.why });
    // Öngörülen (1 ay by default) and the two ASW curves' fair values, as DİBS Trading shows them
    const kfP = (hz) => ((kfF.proj || {}).h || {})[String(hz)] || {};
    const kfAsw = (k, i) => { const a = (kfF.asw || {})[k] || {}; return isFinite(a.yield) ? (i ? a.price.toFixed(3).replace('.', ',') : kfFmt(a.yield)) : '–'; };
    // (a main-table column: yield over price as the details' values; none: "—" alone)
    const kfAswCol = (c, k) => (kfAsw(k, 0) === '–' ? c[k] === '—' && c[k + 'P'] === null : c[k] === kfAsw(k, 0) && c[k + 'P'] === kfAsw(k, 1));
    check('... the main table\'s Öngörülen at 1 ay (the default: the best record): yield over the price at the horizon\'s value date, the '
      + 'model - here M2 in M4\'s place (three closes: the AR(1) cannot be measured), said, with Δ, K/Z and the record in its tooltip -; '
      + '"OIS\'e göre" / "FX swap\'a göre" yield over price - the details\' values; a bond off the trading list "—", said why; the details '
      + 'keep the fair and the how lines, no more these columns',
      kfSeen.mainGroups.some((g) => /^Öngörülen · 1 ay$/.test(g)) && kfSeen.mainGroups.includes("OIS'e göre") && kfSeen.mainGroups.includes("FX swap'a göre")
      && kfSeen.ufuk.join() === 'kf-ufuk-5,kf-ufuk-10,kf-ufuk-20*' && kfApi.projection.default === 20
      && kfSeen.cols.proj === kfFmt(kfP(20).yield) && kfSeen.cols.projP === kfP(20).clean.toFixed(3).replace('.', ',')
      && kfP(20).rule === 'M4' && kfP(20).model === 'M2' && /^M4 kurulamadı/.test(kfP(20).why) && kfSeen.cols.model === 'eğri+fark sabit'
      && kfSeen.cols.projTip.includes('geri test') && kfSeen.cols.projTip.includes('K/Z') && kfSeen.cols.projTip.includes('basit ' + kfFmt(kfP(20).simple))
      && kfSeen.how.includes('Öngörülen: ' + kfP(20).line) && kfAswCol(kfSeen.cols, 'ois') && kfAswCol(kfSeen.cols, 'fx') && kfSeen.cols.ois !== '—'
      && kfSeen.colsOff.proj === '—' && kfSeen.colsOff.ois === '—' && kfSeen.colsOff.fx === '—' && /yalnız trading listesindeki/.test(kfSeen.colsOff.projTip)
      && kfSeen.fixed.proj === null && kfSeen.fixed['ois-y'] === null && !kfSeen.groups.some((g) => /^Öngörülen/.test(g)),
    { cols: kfSeen.cols, off: kfSeen.colsOff, groups: kfSeen.mainGroups, ufuk: kfSeen.ufuk, p20: kfP(20), asw: kfF.asw });
    // the switch: 1 hafta - another value date, another projection (the table drawn again from the same answer)
    await page.click('#kf-ufuk-5');
    await page.waitForFunction((want) => { const td = document.querySelector('#kf-table tr.kf-main[data-isin="TRT150328T24"] td.kf-m-proj .kf-2l-y');
      return td && td.textContent === want; }, kfFmt(kfP(5).yield), { timeout: 20000 }).catch(() => {});
    const kfSeen5 = await kfRead();
    check('... the horizon switch (1 hafta / 2 hafta / 1 ay) changes the Öngörülen column at once: 1 hafta shows its own yield and price',
      kfSeen5.ufuk.join() === 'kf-ufuk-5*,kf-ufuk-10,kf-ufuk-20' && kfSeen5.mainGroups.some((g) => /^Öngörülen · 1 hafta$/.test(g))
      && kfSeen5.cols.proj === kfFmt(kfP(5).yield) && kfSeen5.cols.projP === kfP(5).clean.toFixed(3).replace('.', ',')
      && kfP(5).value_date < kfP(20).value_date && kfSeen5.cols.projP !== kfSeen.cols.projP,
    { p5: kfSeen5.cols, ufuk: kfSeen5.ufuk });
    await shot(page, '12c-kagit-fiyat');
    // the bond's card: the same block (Öngörülen at the horizon chosen on the page)
    await page.click('#kf-table tr.kf-row[data-isin="TRT150328T24"] td.cardlink');
    await page.waitForSelector('.modal.bondcard #kf-card #kf-card-how', { timeout: 30000 }).catch(() => {});
    const kfCardRead = () => page.evaluate(() => Object.fromEntries(['fair', 'how', 'buy', 'quote', 'proj', 'proj-price', 'proj-model', 'ois', 'fx', 'proj-how', 'curve']
      .map((k) => [k, (document.getElementById('kf-card-' + k) || {}).textContent || ''])));
    const kfCard = await kfCardRead();
    check('... the bond\'s card has the same block: its curve price line first (piyasa here), fair (compound / simple), the quote, the good '
      + 'levels and how it was priced',
      kfCard.curve.startsWith('Eğri fiyatı: ' + kfFmt(kfCF.price.yield)) && /\(piyasa, valör 04\.11\.2026\)/.test(kfCard.curve)
      && kfCard.fair.includes(kfFmt(kfF.fair.yield) + ' / ' + kfFmt(kfF.fair.simple)) && kfCard.how === 'Nasıl fiyatlandı: ' + kfF.line
      && kfCard.buy.includes(kfFmt(kfF.levels.buy.yield)) && kfCard.quote.includes(kfFmt(kfF.quote.bid.yield) + ' / ' + kfFmt(kfF.quote.ask.yield)), kfCard);
    await page.click('.modal.bondcard #kf-card-ufuk-20').catch(() => {});
    await page.waitForFunction((want) => ((document.getElementById('kf-card-proj') || {}).textContent || '').includes(want),
      kfFmt(kfP(20).yield) + ' / ' + kfFmt(kfP(20).simple), { timeout: 20000 }).catch(() => {});
    const kfCard20 = await kfCardRead();
    check('... and Öngörülen (at 1 hafta, the page\'s choice; its own switch to 1 ay), the model and record, and OIS\'e göre / FX swap\'a göre',
      kfCard.proj.includes(kfFmt(kfP(5).yield) + ' / ' + kfFmt(kfP(5).simple)) && kfCard20.proj.includes(kfFmt(kfP(20).yield) + ' / ' + kfFmt(kfP(20).simple))
      && kfCard20['proj-price'].includes(kfP(20).clean.toFixed(3).replace('.', ',')) && /eğri ve fark değişmezse/.test(kfCard20['proj-model'])
      && kfCard20['proj-how'].includes('geri test') && kfCard20.ois.includes(kfAsw('ois', 0) + ' / ' + kfAsw('ois', 1))
      && kfCard20.fx.includes(kfAsw('fx', 0)),
    { kfCard, kfCard20 });
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => !document.querySelector('.modal.bondcard'));
    // an administrator's width (1–3Y 12 bp): the quote follows; back to 10
    await page.fill('#kf-width-3y', '12');
    await page.click('#kf-widths-save');
    await page.waitForFunction(() => { const td = document.querySelector('#kf-table tr.kf-row[data-isin="TRT150328T24"] td.kf-quote-px');
      return td && /12,0 bp/.test(td.title || '') && !!document.getElementById('kf-log'); }, null, { timeout: 30000 }).catch(() => {});
    const kfWide = ((await api(page, 'ayşe yilmaz', 'GET', '/api/kagit-fiyat?isin=TRT150328T24')).json.rows || [])[0] || {};
    const kfLog = await page.evaluate(() => (document.getElementById('kf-log') || {}).textContent || '');
    check('... an administrator sets a bucket\'s width (1–3Y 12 bp): the quote is that wide, logged',
      kfWide.quote && kfWide.quote.width === 12 && Math.abs(kfWide.quote.bid.yield - kfWide.quote.ask.yield - 0.12) < 1e-9
      && /1–3Y 10,0 → 12,0 bp/.test(kfLog), { width: kfWide.quote && kfWide.quote.width, kfLog });
    await api(page, 'ayşe yilmaz', 'POST', '/api/kagit-fiyat/genislik', { widths: { '3y': 10 } });
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

    // ------------------------------------------------------------------ Kâğıt Fiyat Yükleme: the list, an auction text, Hesapla, an edit, Kaydet (txt)
    console.log('kagit fiyat yukleme');
    await open(page, 'fiyat-yukleme');
    await page.waitForSelector('#fy-list-table');
    const fyMenu = await page.evaluate(() => window.tto.state.pages.filter((p) => p.group === 'Tahvil').map((p) => p.id).slice(0, 2));
    await page.fill('#fy-add-text', 'TRB100227T13\nTRT130127T11');
    await page.click('#fy-add');
    await page.waitForFunction(() => document.querySelectorAll('#fy-list-table tr.fy-item').length === 2, null, { timeout: 20000 }).catch(() => {});
    const fyList = await page.evaluate(() => [...document.querySelectorAll('#fy-list-table tr.fy-item')].map((tr) => [...tr.children].slice(0, 5).map((td) => td.textContent).join('|')));
    check('Kâğıt Fiyat Yükleme: right after Kâğıt Fiyatlama in Tahvil; two bonds added as a pasted list, each with its description and maturity',
      fyMenu.join() === 'kagit-fiyat,fiyat-yukleme' && fyList.join(' / ') === 'TRB100227T13|10.02.27 Bono|TURKTB 0 02/10/27|10.02.2027|Bono / '
        + 'TRT130127T11|13.01.27 TLREF|TURKGB Float 01/13/27|13.01.2027|TLREF', { fyMenu, fyList });
    await page.click('#fy-mode-ihale');
    await page.fill('#fy-text', 'Auction prices:\n10/02/2027zc.t1   31.700\n13/01/27 TLREF.t1   100.500\n08/05/2030 cpi.t1   95.000\n** Min 50 mio, Increment 1 mio');
    await page.click('#fy-hesapla');
    await page.waitForSelector('#fy-table tr.fy-row', { timeout: 30000 }).catch(() => {});
    const fyRead = () => page.evaluate(() => {
      const row = (isin) => {
        const tr = document.querySelector('#fy-table tr.fy-row[data-isin="' + isin + '"]');
        if (!tr) return {};
        const v = (c) => (tr.querySelector('input.' + c) || {}).value;
        const t = (c) => (tr.querySelector('td.' + c) || {}).textContent;
        return { by: v('fy-bid-y'), ay: v('fy-ask-y'), bp: v('fy-bid-p'), ap: v('fy-ask-p'), t0y: t('fy-t0-y'), t0p: t('fy-t0-p'), write: t('fy-write'),
          edited: tr.classList.contains('fy-edited') };
      };
      const pre = document.getElementById('fy-txt') || {};
      return { bill: row('TRB100227T13'), tlref: row('TRT130127T11'), sum: (document.getElementById('fy-parse-sum') || {}).textContent || '',
        pick: document.querySelectorAll('#fy-pick-4 option').length, txt: pre.textContent || '', saved: (pre.dataset || {}).saved };
    });
    const fy1 = await fyRead();
    check('... the auction text read (2 lines recognised, the CPI line with two bonds that day offered the bonds near it to name), '
      + 'Hesapla: the bill at its auction yield ± 5 bp (written by its yields), the TLREF floater at the auction\'s price ± 0,05 (by its prices)',
      /^2 satır tanındı · 1 satır tanınamadı · 2 satır yok sayıldı/.test(fy1.sum) && fy1.pick >= 3
      && fy1.bill.t0y === '31,700' && fy1.bill.by === '31,750' && fy1.bill.ay === '31,650' && fy1.bill.write === 'getiri'
      && fy1.tlref.t0p === '100,500' && fy1.tlref.bp === '100,450' && fy1.tlref.ap === '100,550' && fy1.tlref.by === '' && fy1.tlref.write === 'fiyat'
      && fy1.txt === 'TRB100227T13,0,0,31.750,31.650\r\nTRT130127T11,100.450,100.550,0,0\r\n' && fy1.saved === '0', fy1);
    // an edit: the bill's bid yield 31,800 - its price follows (the server's conversion), the preview too
    const fyConv = (await api(page, 'ayşe yilmaz', 'POST', '/api/fiyat-yukleme/cevir', { isin: 'TRB100227T13', field: 'yield', value: 31.8 })).json || {};
    const fyBidY = '#fy-table tr.fy-row[data-isin="TRB100227T13"] input.fy-bid-y';
    await page.fill(fyBidY, '31,800');
    await page.press(fyBidY, 'Tab');
    await page.waitForFunction((want) => { const inp = document.querySelector('#fy-table tr.fy-row[data-isin="TRB100227T13"] input.fy-bid-p');
      return inp && inp.value === want; }, (fyConv.price || 0).toFixed(3).replace('.', ','), { timeout: 20000 }).catch(() => {});
    const fy2 = await fyRead();
    const fyWant = 'TRB100227T13,0,0,31.800,31.650\r\nTRT130127T11,100.450,100.550,0,0\r\n';
    check('... a cell edited (the bill\'s bid yield 31,800): its price follows by the server\'s conversion, the file\'s preview too',
      fy2.bill.by === '31,800' && fy2.bill.bp === (fyConv.price || 0).toFixed(3).replace('.', ',') && fy2.bill.edited && fy2.txt === fyWant, { fy2, fyConv });
    const [fyFile] = await Promise.all([page.waitForEvent('download', { timeout: 30000 }), page.click('#fy-kaydet')]);
    const fyText = require('fs').readFileSync(await fyFile.path(), 'latin1');
    await page.waitForFunction(() => (document.getElementById('fy-txt') || { dataset: {} }).dataset.saved === '1', null, { timeout: 20000 }).catch(() => {});
    const fy3 = await fyRead();
    check('... Kaydet (txt) downloads dibs_fiyat_20261103.txt: ISIN,fiyatbid,fiyatask,yieldbid,yieldask - the bill by its yields (as edited), '
      + 'the floater by its prices, the others 0, three decimals, CRLF; the page shows the same lines',
      fyFile.suggestedFilename() === 'dibs_fiyat_20261103.txt' && fyText === fyWant && fy3.txt === fyWant && fy3.saved === '1', { name: fyFile.suggestedFilename(), fyText, fy3 });
    // a Eurobond: its own default yield spreads (2 bp each); offline its facts cannot come from Bloomberg - refused, and why
    const fyEuro = (await api(page, 'ayşe yilmaz', 'POST', '/api/fiyat-yukleme/ekle', { isins: 'XS2987654329' })).json || {};
    const fyEuroDefs = await page.evaluate(() => ['euro-bid', 'euro-ask'].map((k) => (document.getElementById('fy-def-' + k) || {}).value));
    check('... a Eurobond\'s own default yield spreads (2,0 / 2,0 bp); added offline it is refused with the reason (its facts come from Bloomberg)',
      fyEuroDefs.join() === '2,0,2,0' && (fyEuro.added || []).length === 0 && /Eurobond'un bilgileri .*Bloomberg'den gelir/.test(((fyEuro.refused || [])[0] || {}).text || ''),
      { fyEuroDefs, fyEuro: fyEuro.refused });
    // Sabit fiyatlar: two rows pasted from Excel (ISIN | Bid | | Offer; FX DİBS, not in the catalog; a Turkish comma in one) -
    // their own table (the file line each gives), then as they are in Hesapla and in the file
    await page.fill('#fy-sabit-text', 'TRT191127F19\t99.483\t\t99.726\nTRT030327F17\t99,951\t\t100,152');
    await page.click('#fy-sabit-yapistir');
    await page.waitForFunction(() => document.querySelectorAll('#fy-sabit-table tr.fy-sabit-item').length === 2, null, { timeout: 20000 }).catch(() => {});
    const fySabitTbl = await page.evaluate(() => [...document.querySelectorAll('#fy-sabit-table tr.fy-sabit-item')].map((tr) => [tr.dataset.isin,
      (tr.querySelector('td.fy-name') || {}).textContent, tr.children[2].textContent, (tr.querySelector('td.fy-sabit-unit') || {}).textContent,
      (tr.querySelector('input.fy-sabit-bid') || {}).value, (tr.querySelector('input.fy-sabit-ask') || {}).value,
      (tr.querySelector('td.fy-sabit-line') || {}).textContent].join('|')));
    const fyRapor = await page.evaluate(() => (document.getElementById('fy-sabit-rapor') || {}).textContent || '');
    check('... Sabit fiyatlar: two rows pasted from Excel make their own table - the description ("döviz DİBS"), the maturity read from the '
      + 'ISIN, the unit, bid / offer in 3 decimals and the file line each gives',
      fySabitTbl.join(' / ') === 'TRT030327F17|döviz DİBS|03.03.2027|temiz fiyat|99,951|100,152|TRT030327F17,99.951,100.152,0,0 / '
        + 'TRT191127F19|döviz DİBS|19.11.2027|temiz fiyat|99,483|99,726|TRT191127F19,99.483,99.726,0,0' && /^2 kâğıt eklendi · 0 güncellendi · 0 satır/.test(fyRapor),
      { fySabitTbl, fyRapor });
    await page.click('#fy-hesapla');
    await page.waitForSelector('#fy-table tr.fy-row.fy-fixed[data-isin="TRT191127F19"]', { timeout: 30000 }).catch(() => {});
    const [fyFile2] = await Promise.all([page.waitForEvent('download', { timeout: 30000 }), page.click('#fy-kaydet')]);
    const fyText2 = require('fs').readFileSync(await fyFile2.path(), 'latin1');
    const fySabit = await page.evaluate(() => ({
      marks: [...document.querySelectorAll('#fy-table tr.fy-row.fy-fixed td.fy-sabit-mark')].map((td) => td.textContent),
      sabitle: document.querySelectorAll('#fy-table tr.fy-row:not(.fy-fixed) button.fy-sabitle').length }));
    const fyWant2 = 'TRB100227T13,0,0,31.750,31.650\r\nTRT130127T11,100.450,100.550,0,0\r\nTRT030327F17,99.951,100.152,0,0\r\nTRT191127F19,99.483,99.726,0,0\r\n';
    check('... and in Hesapla as they are ("sabit fiyat"; the computed rows have "Sabitle"); Kaydet writes their lines as pasted',
      fySabit.marks.join() === 'sabit fiyat,sabit fiyat' && fySabit.sabitle === 2 && fyText2 === fyWant2, { fySabit, fyText2 });
    // a bond with no price of its own (not in the auction text; off the trading list: no trade, no auction kept) - Kâğıt
    // Fiyatlama's curve price, marked "eğri fiyatı", the row's spreads on it, in İhale and in BBG mode
    await page.fill('#fy-add-text', 'TRT240227T17');
    await page.click('#fy-add');
    await page.waitForFunction(() => !!document.querySelector('#fy-list-table tr.fy-item[data-isin="TRT240227T17"]'), null, { timeout: 20000 }).catch(() => {});
    const fyCurveQ = ((await api(page, 'ayşe yilmaz', 'GET', '/api/kagit-fiyat?isin=TRT240227T17')).json.curve_rows || [])[0] || {};
    const fyCurveRead = () => page.evaluate(() => {
      const tr = document.querySelector('#fy-table tr.fy-row[data-isin="TRT240227T17"]');
      return tr ? { curve: tr.classList.contains('fy-curve'), mark: (tr.querySelector('b.fy-curve-mark') || {}).textContent || '',
        how: (tr.querySelector('td.fy-how') || {}).textContent || '', t0y: (tr.querySelector('td.fy-t0-y') || {}).textContent,
        by: (tr.querySelector('input.fy-bid-y') || {}).value, ay: (tr.querySelector('input.fy-ask-y') || {}).value } : {};
    });
    const fyN3 = (v) => v.toFixed(3).replace('.', ',');
    const fyCurve = {};
    for (const mode of ['ihale', 'bbg']) {
      await page.click('#fy-mode-' + mode);
      await page.click('#fy-hesapla');
      await page.waitForFunction((m) => { const tr = document.querySelector('#fy-table tr.fy-row.fy-curve[data-isin="TRT240227T17"]');
        const info = (document.getElementById('fy-result-info') || {}).textContent || '';
        return tr && info.startsWith(m === 'bbg' ? 'BBG' : 'İhale'); }, mode, { timeout: 30000 }).catch(() => {});
      fyCurve[mode] = await fyCurveRead();
    }
    const fyS = (fyCurveQ.alt || {}).simple;
    check('... a bond with no price of its own (not in the auction text; in BBG no trade and no auction kept) gets Kâğıt Fiyatlama\'s curve price, '
      + 'marked "eğri fiyatı" with how and its typical error, its spreads on it (± 5 bp) - in İhale and in BBG mode',
      typeof fyS === 'number' && (fyCurveQ.alt || {}).label === 'eğri'
      && ['ihale', 'bbg'].every((m) => fyCurve[m].curve && fyCurve[m].mark === 'eğri fiyatı' && /tipik hata ±\d+ bp/.test(fyCurve[m].how)
        && fyCurve[m].t0y === fyN3(fyS) && fyCurve[m].by === fyN3(fyS + 0.05) && fyCurve[m].ay === fyN3(fyS - 0.05))
      && /bugünkü ihale listesinde yok/.test(fyCurve.ihale.how) && /kayıtlı ihale fiyatı yok/.test(fyCurve.bbg.how), { fyCurve, fyS });
    // Mid or Bid/Ask (the desk, 23.11.2026: "... bid'i ve ask'i mid'den mi, bid/asktan mı almasını istediğimi de seçebilmeliyim.
    // Default mid"): a DİBS RV bond switched to Bid/Ask - its sides from DİBS RV's bid / ask (100,100 / 100,125), the spreads each
    // on its own side; the bill switched too, its bid equal to its ask: from the mid, said; kept with the list; "Tümü" sets all
    await page.fill('#fy-add-text', 'TRT150328T24');
    await page.click('#fy-add');
    const fyBaseSel = (isin) => '#fy-list-table tr.fy-item[data-isin="' + isin + '"] select.fy-base';
    await page.waitForSelector(fyBaseSel('TRT150328T24'), { timeout: 20000 }).catch(() => {});
    const fyBases = () => page.evaluate(() => [...document.querySelectorAll('#fy-list-table tr.fy-item')].map((tr) => tr.dataset.isin + ':'
      + (tr.querySelector('select.fy-base') || {}).value).join(' '));
    const fyBase0 = await fyBases();
    const fyAyar = () => page.waitForResponse((r) => pathOf(r) === '/api/fiyat-yukleme/ayar', { timeout: 20000 }).catch(() => null);
    for (const isin of ['TRT150328T24', 'TRB100227T13']) await Promise.all([fyAyar(), page.selectOption(fyBaseSel(isin), 'bidask')]);
    const fyKept = (((await api(page, 'ayşe yilmaz', 'GET', '/api/fiyat-yukleme')).json || {}).list || []).map((r) => r.isin + ':' + r.base).join(' ');
    await page.click('#fy-hesapla');
    await page.waitForFunction(() => /^Bid\/Ask: DİBS RV/.test(((document.querySelector('#fy-table tr.fy-row[data-isin="TRT150328T24"] td.fy-how') || {})
      .textContent) || ''), null, { timeout: 30000 }).catch(() => {});
    const fyBA = await page.evaluate(() => {
      const row = (isin) => {
        const tr = document.querySelector('#fy-table tr.fy-row[data-isin="' + isin + '"]');
        if (!tr) return {};
        const v = (c) => (tr.querySelector('input.' + c) || {}).value;
        return { bp: v('fy-bid-p'), ap: v('fy-ask-p'), by: v('fy-bid-y'), ay: v('fy-ask-y'), how: (tr.querySelector('td.fy-how') || {}).textContent || '',
          warn: tr.classList.contains('fy-warn') };
      };
      return { two: row('TRT150328T24'), bill: row('TRB100227T13'), info: (document.getElementById('fy-result-info') || {}).textContent || '' };
    });
    const fyNum = (s) => Number(String(s || '').replace(/\./g, '').replace(',', '.'));
    check('... Mid / Bid/Ask per bond (Mid until set, kept with the list by ISIN): a DİBS RV bond on Bid/Ask starts each side from DİBS RV\'s '
      + 'bid / ask (100,100 / 100,125), the 5 bp spreads on each side; the bill, its bid equal to its ask, from the mid and the row says why',
      fyBase0 === 'TRB100227T13:mid TRT240227T17:mid TRT150328T24:mid TRT130127T11:mid'
      && fyKept === 'TRB100227T13:bidask TRT240227T17:mid TRT150328T24:bidask TRT130127T11:mid'
      && fyBA.two.how.startsWith('Bid/Ask: DİBS RV bid 100,100 / ask 100,125 (valör 04.11.2026)')
      && fyNum(fyBA.two.bp) < 100.1 && fyNum(fyBA.two.bp) > 99.9 && fyNum(fyBA.two.ap) > 100.125 && fyNum(fyBA.two.ap) < 100.325
      && fyNum(fyBA.two.by) > fyNum(fyBA.two.ay) + 0.1 && fyBA.bill.warn && /Bid\/Ask seçili; bid = ask \(92,220\): canlı emir yok/.test(fyBA.bill.how)
      && /Bid\/Ask 2 kâğıt \(1 bid \/ ask'tan, 1 mid'den: satırda neden\)/.test(fyBA.info), { fyBase0, fyKept, fyBA });
    await Promise.all([fyAyar(), page.selectOption('#fy-base-all', 'mid')]);
    await page.waitForFunction(() => [...document.querySelectorAll('#fy-list-table select.fy-base')].every((s) => s.value === 'mid'), null, { timeout: 20000 }).catch(() => {});
    const fyAll = await fyBases();
    const fyAllKept = (((await api(page, 'ayşe yilmaz', 'GET', '/api/fiyat-yukleme')).json || {}).list || []).every((r) => r.base === 'mid');
    check('... and "Tümü" sets every bond of the list back to Mid at once (on the page and kept)',
      fyAll === 'TRB100227T13:mid TRT240227T17:mid TRT150328T24:mid TRT130127T11:mid' && fyAllKept
      && /Mid \/ Bid\/Ask değişti: yeniden Hesapla/.test(await page.evaluate(() => (document.getElementById('fy-result-info') || {}).textContent || '')),
      { fyAll, fyAllKept });

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
    // the alarm's sound (the desk, 20.11.2026: "Yeni sinyal gelince de ötüyordu makine, bugün görmedim"): Chrome / Edge play
    // nothing on a tab nobody has clicked yet, and a sound context made then stays silent for good. A fresh tab of the same
    // session (nothing evaluated on it before the ring: that would count as a click) - its sound contexts and toasts told by
    // the page itself on its console
    const sesPage = await ctxA.newPage();
    const sesLog = [];
    sesPage.on('console', (m) => sesLog.push(m.text()));
    await sesPage.addInitScript(() => {
      const Real = window.AudioContext;
      if (Real) {
        window.AudioContext = class extends Real {
          constructor(...a) { super(...a); console.log('tto-ses:yeni:' + this.state); setTimeout(() => console.log('tto-ses:sonra:' + this.state), 500); }
        };
      }
      document.addEventListener('DOMContentLoaded', () => {
        const box = document.getElementById('toasts');
        if (box) {
          new MutationObserver((ms) => ms.forEach((m) => m.addedNodes.forEach((n) => { if (n.nodeType === 1) console.log('tto-ses:toast:' + n.textContent); })))
            .observe(box, { childList: true });
        }
      });
    });
    const sesFirstLook = sesPage.waitForResponse((r) => r.url().includes('/api/alarms/fired'), { timeout: 30000 });
    await sesPage.goto(BASE + '/#/watch');
    await sesFirstLook;
    await sesPage.waitForTimeout(1500);
    const sesSaw = async (re) => {
      for (let i = 0; i < 80 && !sesLog.some((x) => re.test(x)); i++) await sesPage.waitForTimeout(250);
      return sesLog.some((x) => re.test(x));
    };
    const sesAlarm = async (tenor) => (await api(page, 'ayşe yilmaz', 'POST', '/api/alarms/add',
      { subject: { kind: 'ois', tenor }, op: '>=', level: '1', desk: true, label: 'Ses ' + tenor })).json.alarm;
    const sesA1 = await sesAlarm('2Y');
    const sesRang1 = await sesSaw(/^tto-ses:toast:.*MASA ALARMI · Ses 2Y/);
    const sesHint = await sesSaw(/^tto-ses:toast:🔇 Bu sekmede alarm sesi kapalı: .*sayfaya bir kez tıklayın/);
    const sesBefore = sesLog.filter((x) => x.startsWith('tto-ses:yeni:')).length;
    await sesPage.click('#page-title');
    const sesA2 = await sesAlarm('5Y');
    const sesRang2 = await sesSaw(/^tto-ses:toast:.*MASA ALARMI · Ses 5Y/);
    await sesSaw(/^tto-ses:sonra:/);
    const sesMade = sesLog.filter((x) => x.startsWith('tto-ses:yeni:'));
    const sesLater = sesLog.filter((x) => x.startsWith('tto-ses:sonra:'));
    check('Alarm sesi: a fresh tab nobody has clicked yet - the desk alarm rings (its toast) with "🔇 Bu sekmede alarm sesi kapalı … sayfaya '
      + 'bir kez tıklayın" once and makes no sound context (made then, it would stay silent for good); after one click the next alarm '
      + 'rings with one context, running',
      sesRang1 && sesHint && sesBefore === 0 && sesRang2 && sesMade.length === 1 && sesLater.length === 1 && sesLater[0] === 'tto-ses:sonra:running'
      && sesLog.filter((x) => x.includes('🔇')).length === 1, sesLog.filter((x) => x.startsWith('tto-ses:')));
    for (const a of [sesA1, sesA2]) if (a && a.id) await api(page, 'ayşe yilmaz', 'POST', '/api/alarms/remove', { id: a.id, desk: true });
    await sesPage.close();

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
    // (DİBS RV's own FX swap columns, BF:BJ on the offshore ICAP curve, are hidden until a user shows them: the desk reads
    // the FX swap side on DİBS ASW's FX swap implied curve - Genel's; the table's note says so)
    const fxCols = await page.evaluate((s) => { const g = document.querySelector(s + ' table.grid').__grid;
      return g.columns.cols.filter((c) => g.columns.hid.has(c.j)).map((c) => c.key); }, rv);
    check('DİBS RV: its own FX swap columns (BF:BJ) hidden by default, the note pointing to Genel\'s FX swap ASW',
      fxCols.join() === 'BF,BG,BH,BI,BJ' && await page.textContent(rv + ' .colschip') === 'Gizlediğiniz 5 sütun'
      && /^BF–BJ .*varsayılan olarak gizli.*Genel/.test(await page.textContent(rv + ' > .note')), fxCols);
    await page.locator(rv + ' tr.hd td', { hasText: 'Kaynak (boş = genel)' }).click({ button: 'right' });
    await page.click('.menu >> text=Sütunu gizle: Kaynak (boş = genel)');
    await page.waitForFunction((s) => document.querySelector(s + ' .colschip').textContent === 'Gizlediğiniz 6 sütun', rv);
    check('DİBS RV: a right click on a caption hides its column, the header says so',
      await colHidden(rv, 1) && await page.textContent(rv + ' .colschip') === 'Gizlediğiniz 6 sütun');
    check('... kept with this user\'s account (by the table and the sheet\'s column), nobody else\'s view changes',
      JSON.stringify(await hiddenOf('ayşe yilmaz', 'v/dibs/B3')) === '["BF","BG","BH","BI","BJ","B"]' && (await hiddenOf('mehmet', 'v/dibs/B3')) === undefined);
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
    await page.waitForFunction((s) => document.querySelector(s + ' .colschip').textContent === 'Gizlediğiniz 7 sütun', rv);
    check('"Sütunlar": every column with a tick - untick one and it goes (the list stays open)',
      await colHidden(rv, 2) && await page.locator('.menu label.mcheck').count() >= 60
      && JSON.stringify(await hiddenOf('ayşe yilmaz', 'v/dibs/B3')) === '["BF","BG","BH","BI","BJ","B","C"]');
    await page.click('.menu >> text=Tümünü göster');
    await page.waitForFunction((s) => document.querySelector(s + ' .colschip').classList.contains('hidden'), rv);
    check('... "Tümünü göster" brings every column back - the FX swap ones too, and that is kept (the default does not return)',
      !(await colHidden(rv, 1)) && !(await colHidden(rv, 2)) && JSON.stringify(await hiddenOf('ayşe yilmaz', 'v/dibs/B3')) === '[]');
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
    // a quant page while the fit runs (tto/progress.py): its banner and its status say where it is, not a bare "hesaplanıyor"
    const qprog = await page.evaluate(async () => {
      const q = await import('/static/js/pages/quantbase.js');
      const pv = { busy: true, text: 'Quant 14/26 · ML 240/480 · ~3 dk', jobs: [{ id: 'quant', step: 'Makine öğrenmesi' }, { id: 'ml', step: '' }] };
      const durum = (st) => q.statusRows(st).find((r) => r[0].t === 'Durum')[1].t;
      return { line: q.progressText(pv), idle: q.progressText({ busy: false, jobs: [] }), durum: durum({ phase: 'fit', progress: pv }),
        bare: durum({ phase: 'fit' }), ready: durum({ phase: 'idle' }) };
    });
    check('... a quant page while the fit runs says where it is: "hesaplanıyor: Quant 14/26 · ML 240/480 · ~3 dk – şu an Makine öğrenmesi"',
      qprog.line === ': Quant 14/26 · ML 240/480 · ~3 dk – şu an Makine öğrenmesi' && qprog.idle === ''
      && qprog.durum === 'hesaplanıyor: Quant 14/26 · ML 240/480 · ~3 dk – şu an Makine öğrenmesi' && qprog.bare === 'hesaplanıyor…' && qprog.ready === 'hazır', qprog);
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
    // "İşleme al" (tto/tradequant.py): a line Trades can book has the button in the list's "Trades" column and on its card;
    // one it cannot (a vol trade) a dash with the reason, the card's button disabled with it; the server says which for every line
    const booking = await page.evaluate(async () => {
      const q = await import('/static/js/pages/quantbase.js');
      const base = { family: 'trend', family_label: 'Trend', asset: 'TRY OIS', z: 2.4, entry_z: 2, strength: 'Güçlü', gates: [], agree: 0, conflict: 0,
        parts: { z: 2.4, regime: 1, hl: 1, carry: 1 }, composite: 2.4, hold: 10, horizon_unit: 'gün', bt: null, unit: '%', digits: 2, direction: -1,
        entry: 37.6, target: 37.2, stop: 37.9, pnl_unit: 'bp', expression: 'receive 2Y OIS', instrument: '2Y OIS', trade_tr: 'receive 2Y OIS', plain: '…',
        legs: [{ key: 'OIS:2Y', name: '2Y OIS', action: 'Receive', side: -1, weight: 1, dv01_usd: 1000, text: 'Receive 2Y OIS' }] };
      const yes = Object.assign({}, base, { id: 'trend:OIS:2Y', book: { ok: true, why: '', kind: 'outright' } });
      const no = Object.assign({}, base, { id: 'ml:FXV:EURUSD', asset: 'FX vol', unit: 'vol', legs: [],
        book: { ok: false, why: 'vol işlemi (opsiyon stratejisi): Trades\'e tek işlem olarak girilmez', kind: null } });
      const rows = q.signalRows([yes, no]);
      const col = q.SIGNAL_HEAD.indexOf('Trades');
      const card = (sg) => {
        const host = document.createElement('div');
        const c = new q.SignalChart(host);
        c.show({ monitor: { name: sg.instrument }, signal: sg, history: { days: ['2026-11-02'], values: [1] }, settings: {}, rationale: null });
        const b = host.querySelector('#quant-sig-book');
        const out = b ? { text: b.textContent, disabled: b.disabled, title: b.title } : null;
        c.destroy();
        return out;
      };
      return { at: col, head: q.SIGNAL_HEAD[col - 1], yes: rows[0][col].act ? rows[0][col].act.label : null, no: rows[1][col].t, noTip: rows[1][col].tip || '',
        cardYes: card(yes), cardNo: card(no) };
    });
    check('"İşleme al": a line Trades can book has the button in the list\'s "Trades" column and on its card; a vol line a dash and the reason (its card\'s button disabled with it)',
      booking.head === 'İşlem' && booking.yes === 'İşleme al' && booking.no === '—' && /vol işlemi/.test(booking.noTip) && booking.cardYes
      && booking.cardYes.text === 'İşleme al' && !booking.cardYes.disabled && booking.cardNo && booking.cardNo.disabled && /vol işlemi/.test(booking.cardNo.title), booking);
    check('... every line the server gives says whether Trades can book it', served.every((sg) => sg.book && typeof sg.book.ok === 'boolean'), served.length);
    // levels calibrated on what past trades did (tto/quantlevels.py): a line's Ödül / risk (≥ 1 by construction) and İsabet
    // with its trade count, the card's levels row - or, a line without them (no backtest yet in the recorded month, a family
    // that keeps its own: VİOP's order levels), its reason; every line the server gives carries the one or the other
    const LV_TEXT = 'stop 1,00σ · hedef 1,50σ · ödül / risk 1,50 · isabet %57 (46 işlem, örneklem dışı) · işlem başına +0,21σ';
    const VIOP_WHY = 'seviyeler ailenin kendi tasarımı: VİOP sayfasındaki emir seviyeleri (doluş olasılıklarıyla)';
    const lvl = await page.evaluate(async ({ lvText, viopWhy }) => {
      const q = await import('/static/js/pages/quantbase.js');
      const base = { family: 'pca', family_label: 'PCA kalıntısı', asset: 'TRY OIS', z: 2.6, entry_z: 2, strength: 'Güçlü', gates: [], legs: [], agree: 0,
        conflict: 0, parts: { z: 2.6, regime: 1, hl: 1, carry: 1 }, composite: 2.6, hold: 12, horizon_unit: 'gün', bt: null, unit: 'bp', digits: 1,
        direction: -1, pnl_unit: 'bp', expression: 'Receive 2Y OIS', instrument: '2Y OIS', trade_tr: 'sabit faiz alınan (receive): 2Y OIS', plain: '…' };
      const cal = Object.assign({}, base, { id: 'pca:OIS:2Y', entry: 3, target: 1.5, stop: 4, rr: 1.5, reward: 1.5, risk: 1, exp_pnl: 0.21,
        money: { ccy: 'TL', per_bp: 42000, dv01_usd: 1000, total: 8820, target: 63000, stop: -42000, bp: { total: 0.21, target: 1.5, stop: -1 } },
        levels: { ok: true, rule: 'fixed', k: 1, m: 1.5, rr: 1.5, hit: 0.57, n: 46, oos: true, exp: 0.21, money: 8820, ccy: 'TL', text: lvText } });
      const own = Object.assign({}, base, { id: 'viop:A1Z6', family: 'viop', family_label: 'VİOP adil değer', asset: 'VİOP', entry: 3, target: 0, stop: 3.5,
        rr: 6, reward: 3, risk: 0.5, exp_pnl: 1.2, money: {}, levels: { ok: false, own: true, why: viopWhy } });
      const rows = q.signalRows([cal, own]);
      const col = (n) => q.SIGNAL_HEAD.indexOf(n);
      const card = (s) => {
        const host = document.createElement('div');
        const c = new q.SignalChart(host);
        c.show({ monitor: { name: s.instrument }, signal: s, history: { days: ['2026-11-02'], values: [1] }, settings: {}, rationale: null });
        const t = (host.querySelector('#quant-sig-levels') || {}).textContent || '';
        c.destroy();
        return t;
      };
      return { rr: rows[0][col('Ödül / risk')].t, hit: rows[0][col('İsabet')].t, hitTip: rows[0][col('İsabet')].tip || '', rrTip: rows[0][col('Ödül / risk')].tip || '',
        ownHit: rows[1][col('İsabet')].t, ownTip: rows[1][col('İsabet')].tip || '', cardCal: card(cal), cardOwn: card(own),
        head: q.SIGNAL_HEAD.slice(q.SIGNAL_HEAD.indexOf('Beklenen K/Z'), q.SIGNAL_HEAD.indexOf('Beklenen K/Z') + 3).join(' | ') };
    }, { lvText: LV_TEXT, viopWhy: VIOP_WHY });
    check('a line at its calibrated levels shows Ödül / risk ≥ 1 and İsabet with its trades (the levels in the tooltip, the card\'s levels row); one without them its reason',
      lvl.head === 'Beklenen K/Z | Ödül / risk | İsabet' && lvl.rr === '1,50' && lvl.hit === '57% (46)' && lvl.hitTip === LV_TEXT && lvl.rrTip.includes(LV_TEXT)
      && lvl.cardCal.startsWith(LV_TEXT + ' · işlem başına ≈ ') && lvl.ownHit === '—' && lvl.ownTip === VIOP_WHY && lvl.cardOwn === VIOP_WHY, lvl);
    check('... and every line the server gives carries its levels: Ödül / risk ≥ 1 with the hit rate and expectancy, or the stated reason',
      served.every((s) => s.levels && ((s.levels.ok && s.rr >= 1 && typeof s.levels.hit === 'number' && typeof s.levels.exp === 'number')
        || (!s.levels.ok && typeof s.levels.why === 'string' && s.levels.why.length > 10))),
      served.map((s) => [s.id, s.levels && s.levels.ok, s.rr, s.levels && s.levels.why]));
    // the list by group (tto/quantuniv.py): the buttons above it in the list's order - Konsensüs first (tto/quantcons.py) -, one
    // group alone, the lines a gate holds ("düşük güven") after the confident ones of their group with their reason, an Offshore
    // line's "offshore limiti"; the separate panel of the gated signals is gone (they are in the list)
    const GROUPS = ['Konsensüs', 'G10 spot', 'G10 opsiyon', 'TRY OIS', 'DİBS', 'VİOP', 'Offshore', 'Diğer'];
    const GROUP_IDS = ['all', 'konsensus', 'g10-spot', 'g10-opsiyon', 'try-ois', 'dibs', 'viop', 'offshore', 'diger'].map((x) => 'quant-group-' + x);
    const groupBtns = await page.evaluate(() => [...document.querySelectorAll('#quant-groups button')].map((b) => ({ id: b.id, text: b.textContent, on: b.classList.contains('on') })));
    check('Sinyaller: the group buttons above the list in its order (Tümü, Konsensüs, G10 spot, G10 opsiyon, TRY OIS, DİBS, VİOP, Offshore, Diğer), Tümü on; no separate gated panel',
      groupBtns.map((b) => b.id).join() === GROUP_IDS.join() && /^Tümü \(\d+\)$/.test(groupBtns[0].text) && /^Konsensüs \(\d+\)$/.test(groupBtns[1].text)
      && /^G10 spot \(\d+\)$/.test(groupBtns[2].text) && /^Offshore \(\d+\)$/.test(groupBtns[7].text) && groupBtns[0].on && groupBtns.filter((b) => b.on).length === 1
      && await page.locator('#quant-gated').count() === 0 && await page.locator('#quant-signals > .seg.qgroups').count() === 1, groupBtns);
    const groupAsks = [];
    const onGroupAsk = (r) => { if (r.url().includes('/api/quant/signals')) groupAsks.push(r.url()); };
    page.on('request', onGroupAsk);
    await page.click('#quant-group-try-ois');
    await page.waitForFunction(() => document.querySelector('#quant-group-try-ois').classList.contains('on')
      && window.tto.state.page.data && window.tto.state.page.data.group === 'TRY OIS', null, { timeout: 20000 });
    const tryOnly = await page.evaluate(() => ({ group: window.tto.state.page.group, kept: localStorage.getItem('tto.quant.group'),
      all: (window.tto.state.page.data.signals || []).every((s) => s.group === 'TRY OIS'),
      empty: (document.querySelector('#quant-signals .empty') || {}).textContent || '', rows: document.querySelectorAll('#quant-signals table.grid tr:not(.hd)').length }));
    check('... a group button shows that group alone (asked of the server; its empty list says so), remembered by its name', tryOnly.group === 'TRY OIS'
      && tryOnly.kept === 'TRY OIS' && tryOnly.all
      && groupAsks.some((u) => /group=TRY(\+|%20)OIS/.test(u)) && (tryOnly.rows > 0 || /TRY OIS grubunda/.test(tryOnly.empty)), { tryOnly, groupAsks });
    await page.click('#quant-group-all');
    await page.waitForFunction(() => document.querySelector('#quant-group-all').classList.contains('on') && window.tto.state.page.data
      && window.tto.state.page.data.group === '', null, { timeout: 20000 });
    page.off('request', onGroupAsk);
    const listed = (await api(page, 'ayşe yilmaz', 'GET', '/api/quant/signals')).json || {};
    const ordered = (listed.signals || []).every((s, i, a) => i === 0 || s.priority > a[i - 1].priority
      || (s.priority === a[i - 1].priority && (!!s.gated >= !!a[i - 1].gated)));
    check('... the server\'s list: the groups in order (TRY OIS ≤ 2Y before its long end), the confident lines before the "düşük güven" ones of a group',
      ordered && (listed.signals || []).every((s) => GROUPS.includes(s.group)) && (listed.groups || []).map((g) => g.id).join() === GROUPS.join()
      && (listed.groups || []).find((g) => g.id === 'Offshore').tag === 'offshore limiti', (listed.signals || []).map((s) => [s.priority, !!s.gated]));
    const labels = await page.evaluate(async () => {
      const q = await import('/static/js/pages/quantbase.js');
      const base = { family: 'pca', family_label: 'PCA kalıntısı', z: 2.6, entry_z: 2, strength: 'Güçlü', gates: [], legs: [], agree: 0, conflict: 0,
        parts: { z: 2.6, regime: 1, hl: 1, carry: 1 }, composite: 2.6, hold: 10, horizon_unit: 'gün', bt: null, unit: 'bp', digits: 1, entry: 3, target: 0, stop: 4,
        direction: -1, pnl_unit: 'bp', exp_pnl: 1.2 };
      const ois = Object.assign({}, base, { id: 'x:ois', asset: 'TRY OIS', expression: 'Receive 2Y OIS', group: 'TRY OIS', tier: '≤ 2Y', tag: '', gated: '' });
      const off = Object.assign({}, base, { id: 'x:off', asset: 'Offshore', expression: 'Pay Offshore 3M', group: 'Offshore', tier: null, tag: 'offshore limiti',
        gated: 'yarı ömür 60 gün: ufkun (20 gün) 2 katından uzun', strength: 'elendi', composite: 0 });
      const rows = q.signalRows([ois, off], { rank: true, group: true });
      const head = ['#', 'Grup'].concat(q.SIGNAL_HEAD, ['Bileşik / neden', 'Saat']);
      const col = (n) => head.indexOf(n);
      const host = document.createElement('div');
      const c = new q.SignalChart(host);
      c.show({ monitor: { name: 'Offshore 3M' }, signal: off, history: { days: ['2026-11-02'], values: [1] }, settings: {}, rationale: null });
      const card = (host.querySelector('#quant-sig-group') || {}).textContent || '';
      c.destroy();
      return { g0: rows[0][1].t, g1: rows[1][1].t, cls1: rows[1][1].cls, s0: rows[0][col('Güç')].t, s1: rows[1][col('Güç')].t,
        c0: rows[0][col('Bileşik / neden')].t, why1: rows[1][col('Bileşik / neden')].t, card };
    });
    check('... a line says its group ("TRY OIS · ≤ 2Y"), an Offshore line "offshore limiti"; a gate\'s line "düşük güven" and its reason where the composite was, its card too',
      labels.g0 === 'TRY OIS · ≤ 2Y' && labels.g1 === 'Offshore · offshore limiti' && labels.cls1 === 'qtag' && labels.s0 === 'Güçlü' && labels.s1 === 'düşük güven'
      && labels.c0 === '2,60' && /^yarı ömür 60 gün/.test(labels.why1) && labels.card === 'Offshore · offshore limiti · düşük güven (yarı ömür 60 gün: ufkun (20 gün) 2 katından uzun)', labels);
    // a fly of the universe: its level the 50/50 package's, the OIS sheet's 2·body − wings quote beside it on the card
    const flyCard = await page.evaluate(async () => {
      const q = await import('/static/js/pages/quantbase.js');
      const s = { id: 'trend:OISF:6M/1Y/2Y', family: 'trend', family_label: 'Trend', asset: 'TRY OIS', expression: 'Pay 6M/1Y/2Y fly',
        instrument: '6M/1Y/2Y fly', z: 2.5, entry_z: 2, strength: 'Güçlü', gates: [], legs: [], agree: 0, conflict: 0,
        parts: { z: 2.5, regime: 1, hl: 1, carry: 1 }, composite: 2.5, hold: 10, horizon_unit: 'gün', bt: null, unit: 'bp', digits: 1,
        entry: -12.5, target: -8, stop: -15, direction: 1, pnl_unit: 'bp', exp_pnl: 3, group: 'TRY OIS', tier: '≤ 2Y', tag: '', gated: '',
        info: { sheet: { factor: 2, where: 'OIS sayfasında' } } };
      const host = document.createElement('div');
      const c = new q.SignalChart(host);
      c.show({ monitor: { name: '6M/1Y/2Y fly', info: s.info }, signal: s, history: { days: ['2026-11-02'], values: [1] }, settings: {}, rationale: null });
      const prices = (host.querySelector('#quant-sig-prices') || {}).textContent || '';
      c.destroy();
      const row = q.signalRows([s])[0];
      const col = (n) => q.SIGNAL_HEAD.indexOf(n);
      return { prices, tip: row[col('Giriş')].tip, entry: row[col('Giriş')].t };
    });
    check("... a fly's entry / target / stop on the card with the OIS sheet's quote beside them (2·body − wings), in the list's tooltip",
      flyCard.prices.startsWith('-12,5 bp (OIS sayfasında -25,0) / -8,0 bp (OIS sayfasında -16,0) / -15,0 bp (OIS sayfasında -30,0) · 6M/1Y/2Y fly')
      && flyCard.tip === '(OIS sayfasında -25,0)' && flyCard.entry === '-12,5', flyCard);
    check('... the alarm subscription chooses groups too, and knows the families on the universe (Trend, Carry + momentum, Makine öğrenmesi)',
      await page.locator('#quant-sub-groups input[type=checkbox]').count() === 7
      && /Trend/.test(await page.textContent('#quant-sub-families')) && /Carry \+ momentum/.test(await page.textContent('#quant-sub-families'))
      && /Makine öğrenmesi/.test(await page.textContent('#quant-sub-families')));
    await shot(page, 'quant-signals');
    // ------------------------------------------------------------------ Carry + momentum (quantsira.py)
    // a tab of Sinyaller: each set's basket card and ranking table under its read line, the backtest per set; the recorded
    // month is too short for a basket - each set says why; a leg as the server sends it, in the list in the plan's format
    console.log('quant carry + momentum');
    await open(page, 'quant-sira');
    await page.waitForSelector('#quant-sira-g10', { timeout: 30000 });
    await page.waitForFunction(() => window.tto.state.page && window.tto.state.page.data && window.tto.state.page.data.ready, null, { timeout: 90000 });
    const siraApi = await api(page, 'ayşe yilmaz', 'GET', '/api/quant/sira');
    const SIRA_SETS = ['quant-sira-g10', 'quant-sira-vol', 'quant-sira-ois', 'quant-sira-spread', 'quant-sira-fly', 'quant-sira-dibs'];
    const sira = await page.evaluate(() => ({
      tabs: [...document.querySelectorAll('#page-tabs button')].map((b) => b.textContent),
      on: [...document.querySelectorAll('#page-tabs button.on')].map((b) => b.dataset.page),
      panels: [...document.querySelectorAll('section.panel[id^="quant-sira-"]')].map((p) => {
        const r = p.querySelector(':scope > .qread');
        return { id: p.id, read: r ? r.textContent : '', under: !!r && (r.previousElementSibling || {}).tagName === 'HEADER',
          card: !!p.querySelector('.qbasket'), why: ((p.querySelector('.qbasket .empty') || {}).textContent || ''),
          table: !!p.querySelector('table.grid, .body > .empty') };
      }) }));
    const siraSets = ((siraApi.json || {}).sira || {}).sets || [];
    check('Carry + momentum: the fourth tab of Sinyaller; each set\'s basket card and ranking table under its read line, the backtest per set',
      sira.tabs.join(',') === 'Sinyaller,Gün içi,Model,Trend,Carry + momentum,Makine öğrenmesi' && sira.on.join() === 'quant-sira' && siraApi.status === 200 && siraSets.length === 6
      && SIRA_SETS.every((id) => sira.panels.some((p) => p.id === id && p.read.length >= 40 && p.under && p.card && p.table))
      && sira.panels.some((p) => p.id === 'quant-sira-backtest' && p.read.length >= 40 && p.under)
      && siraSets.every((s) => s.ok || (s.why && sira.panels.some((p) => p.id === 'quant-sira-' + s.id && p.why === s.why))), { sira, sets: siraSets.map((s) => [s.id, s.ok, s.why]) });
    const siraRow = await page.evaluate(async () => {
      const q = await import('/static/js/pages/quantbase.js');
      const leg = { id: 'sira:g10:FX:USDJPY', family: 'sira', family_label: 'Carry + momentum', asset: 'FX', group: 'G10 spot', tier: null, tag: '',
        expression: 'SAT USDJPY spot · 1,2 mn USD', z: -2, entry_z: 1, score_name: 'sıra', strength: 'Güçlü', gated: '', gates: [], legs: [], agree: 0,
        conflict: 0, parts: { z: 3.5, regime: 1, hl: 1, carry: 1 }, composite: 3.5, hold: 5, horizon_unit: 'gün', direction: -1, unit: '', digits: 3,
        entry: 150.25, target: 149.9, stop: 151.8, pnl_unit: '%', exp_pnl: 0.23,
        px: { pair: 'USDJPY', inst: 'USDJPY spot', label: 'USDJPY spot', tenor: null, digits: 3, unit: 'JPY', entry: 150.25, target: 149.9, stop: 151.8 },
        money: { ccy: 'JPY', base: 'USD', total: 350000, target: 350000, stop: -1550000 }, bt: { trades: 87, hit: 0.58, avg_sigma: 0.12, text: '' },
        info: { model: 'Carry + momentum · G10 spot sepeti' } };
      const head = ['#', 'Grup'].concat(q.SIGNAL_HEAD, ['Bileşik / neden', 'Saat']);
      const row = q.signalRows([leg], { rank: true, group: true })[0];
      const cell = (n) => row[head.indexOf(n)].t;
      return { fam: cell('Aile'), trade: cell('İşlem'), entry: cell('Giriş'), target: cell('Hedef'), stop: cell('Stop'), pnl: cell('Beklenen K/Z'),
        bt: cell('Geri test'), group: cell('Grup'), strength: cell('Güç') };
    });
    check('... a basket leg in the Sinyaller list in the plan\'s format: "SAT USDJPY spot · 1,2 mn USD", entry / target / stop in its price, the expected P&L, isabet and weeks, model: Carry + momentum · G10 spot sepeti',
      siraRow.fam === 'Carry + momentum · G10 spot sepeti' && siraRow.trade === 'SAT USDJPY spot · 1,2 mn USD' && siraRow.entry === '150,250'
      && siraRow.target === '149,900' && siraRow.stop === '151,800' && siraRow.pnl === '+350 bin JPY / 1 mn USD' && siraRow.bt === '87 · 58% · +0,1σ'
      && siraRow.group === 'G10 spot' && siraRow.strength === 'Güçlü', siraRow);
    await shot(page, 'quant-sira');
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
    // ------------------------------------------------------------------ Makine öğrenmesi (quantml.py): a tab of Sinyaller
    console.log('quant ml');
    await open(page, 'quant-ml');
    await page.waitForSelector('#quant-ml-table table.grid', { timeout: 60000 });
    const mlApi = await api(page, 'ayşe yilmaz', 'GET', '/api/quant/ml');
    const mlTab = (mlApi.json || {}).ml || {};
    const mlRows = mlTab.rows || [];
    const mlPage = await page.evaluate(() => ({
      tabs: [...document.querySelectorAll('#page-tabs button')].map((b) => b.textContent), on: [...document.querySelectorAll('#page-tabs button.on')].map((b) => b.dataset.page),
      lit: [...document.querySelectorAll('#nav .nav-item.active')].map((a) => a.dataset.page), rows: document.querySelectorAll('#quant-ml-table table.grid tr:not(.hd)').length,
      feats: document.querySelectorAll('#quant-ml-features table.grid tr:not(.hd)').length,
      read: ['quant-ml-signals', 'quant-ml-table', 'quant-ml-features'].map((id) => {
        const p = document.getElementById(id);
        const r = p && p.querySelector(':scope > .qread'), n = p && p.querySelector(':scope > .qnote');
        return { id, read: r ? r.textContent : '', under: !!r && (r.previousElementSibling || {}).tagName === 'HEADER',
          method: n && n.classList.contains('qmethod') && n.textContent ? getComputedStyle(n, '::before').content : null };
      }) }));
    check('Makine öğrenmesi is a tab of Sinyaller: every line of the family in its table, each table read in the desk\'s words under its title',
      mlApi.status === 200 && mlApi.json.ready && mlPage.tabs[0] === 'Sinyaller' && mlPage.tabs.includes('Makine öğrenmesi') && mlPage.on.join() === 'quant-ml'
      && mlPage.lit.join() === 'quant.sinyal' && mlRows.length >= 30 && mlPage.rows === mlRows.length
      && mlPage.read.every((r) => r.read.length >= 40 && r.under) && mlPage.read.find((r) => r.id === 'quant-ml-table').method === '"Yöntem: "',
      { tabs: mlPage.tabs, rows: mlRows.length, shown: mlPage.rows, read: mlPage.read });
    // the recorded month is far too short for a monthly walk-forward: no line prints and each instrument says why
    const mlSigs = ((await api(page, 'ayşe yilmaz', 'GET', '/api/quant/signals?family=ml')).json || {}).signals || [];
    const mlText = await page.textContent('#quant-ml-table');
    check('... on the recorded month no ML line prints: every instrument says why ("geçmiş kısa": its closes and the least it needs), the list says so',
      mlSigs.length === 0 && mlRows.every((r) => !r.prints && r.why) && mlRows.some((r) => /^geçmiş kısa \(\d+ kapanış; en az \d+\)$/.test(r.why))
      && /geçmiş kısa/.test(mlText) && /Şu an basılan satır yok/.test(await page.textContent('#quant-ml-signals')) && mlPage.feats === 0,
      mlRows.slice(0, 6).map((r) => r.key + ': ' + r.why));
    // a line as the server writes it (tests/test_quantml.py makes it from synthetic data): the list's İşlem is the plan's line
    const mlLine = await page.evaluate(async () => {
      const q = await import('/static/js/pages/quantbase.js');
      const s = { id: 'ml:FX:AUDUSD', family: 'ml', family_label: 'Makine öğrenmesi', asset: 'FX', expression: 'AL AUDUSD spot · 1 mn AUD · olasılık %65 · isabet %69 (64)',
        z: 2.98, entry_z: 2, score_name: 'z(p)', strength: 'Orta', gates: [], legs: [], agree: 0, conflict: 0, parts: { z: 2.98, regime: 1, hl: 1, carry: 1 }, composite: 2.98,
        hold: 5, horizon_unit: 'gün', bt: null, unit: '', digits: 5, entry: 0.63345, target: 0.63549, stop: 0.62282, direction: 1, pnl_unit: '%', exp_pnl: 0.32,
        group: 'G10 spot', tier: null, tag: '', gated: '' };
      const head = ['#', 'Grup'].concat(q.SIGNAL_HEAD, ['Bileşik / neden', 'Saat']);
      const row = q.signalRows([s], { rank: true, group: true })[0];
      return { family: row[head.indexOf('Aile')].t, trade: row[head.indexOf('İşlem')].t, group: row[head.indexOf('Grup')].t, z: row[head.indexOf('z')].t };
    });
    check('... and an ML line in the list: family "Makine öğrenmesi", the trade "AL AUDUSD spot · 1 mn AUD · olasılık %65 · isabet %69 (64)", its group',
      mlLine.family === 'Makine öğrenmesi' && mlLine.trade === 'AL AUDUSD spot · 1 mn AUD · olasılık %65 · isabet %69 (64)' && mlLine.group === 'G10 spot' && mlLine.z === '+2,98', mlLine);
    await shot(page, 'quant-ml');
    // curve fair value: the NSS fit of the OIS quotes and the NS fit of the DİBS RV list's fixed-coupon bonds, its bills
    // priced on it (today's quotes of the workbook; the recorded data has no DİBS history, so no z yet)
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
      quoteRows.join('|').startsWith('Alış (bid)|Adil (NS)|Satış (ask)|Piyasa') && swq.status === 200 && swq.json.ok
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
    // ------------------------------------------------------------------ Opsiyon → spot (quantoptspot.py): a tab of FX
    // (the recorded data keeps no vol history: every pair says why it has no line, the record table that it has none)
    console.log('quant optspot');
    await open(page, 'quant-optspot');
    await page.waitForSelector('#quant-optspot-pairs table.grid', { timeout: 60000 });
    const osApi = await api(page, 'ayşe yilmaz', 'GET', '/api/quant/optspot');
    const osRows = ((osApi.json || {}).optspot || {}).rows || [];
    const osPage = await page.evaluate(() => ({
      tabs: [...document.querySelectorAll('#page-tabs button')].map((b) => b.textContent), on: [...document.querySelectorAll('#page-tabs button.on')].map((b) => b.dataset.page),
      lit: [...document.querySelectorAll('#nav .nav-item.active')].map((a) => a.dataset.page),
      rows: document.querySelectorAll('#quant-optspot-pairs table.grid tr:not(.hd)').length,
      leads: document.querySelectorAll('#quant-optspot-leads table.grid tr:not(.hd)').length,
      leadsText: (document.getElementById('quant-optspot-leads') || {}).textContent || '',
      read: ['quant-optspot-signals', 'quant-optspot-pairs', 'quant-optspot-leads'].map((id) => {
        const p = document.getElementById(id);
        const r = p && p.querySelector(':scope > .qread'), n = p && p.querySelector(':scope > .qnote');
        return { id, read: r ? r.textContent : '', under: !!r && (r.previousElementSibling || {}).tagName === 'HEADER',
          method: n && n.classList.contains('qmethod') && n.textContent ? getComputedStyle(n, '::before').content : null };
      }) }));
    check('Opsiyon → spot is the fourth tab of FX: every pair in its table (USDTRY and EURTRY in Offshore), each table read in the desk\'s words under its title',
      osApi.status === 200 && osApi.json.ready && osPage.tabs.join(',') === 'FX,Makro,Opsiyon,Opsiyon → spot' && osPage.on.join() === 'quant-optspot'
      && osPage.lit.join() === 'quant.fx' && osRows.length === 9 && osPage.rows === 9
      && osRows.filter((r) => r.group === 'Offshore').map((r) => r.pair).join() === 'USDTRY,EURTRY'
      && osPage.read.every((r) => r.read.length >= 40 && r.under) && osPage.read.find((r) => r.id === 'quant-optspot-pairs').method === '"Yöntem: "',
      { tabs: osPage.tabs, rows: osRows.length, shown: osPage.rows, read: osPage.read });
    const osSigs = ((await api(page, 'ayşe yilmaz', 'GET', '/api/quant/signals?family=optspot')).json || {}).signals || [];
    check('... in the recorded data (no vol history) no line prints: every pair says why, the record table says it has none',
      osSigs.length === 0 && osRows.every((r) => !r.prints && r.why) && osRows.find((r) => r.pair === 'EURTRY').why.startsWith('opsiyon serisi yok')
      && osPage.leads === 0 && /Örneklem dışı kayıt yok/.test(osPage.leadsText) && /Şu an basılan satır yok/.test(await page.textContent('#quant-optspot-signals')),
      osRows.map((r) => r.pair + ': ' + r.why));
    // a line as the server writes it (tests/test_quantoptspot.py makes it from synthetic data): the option signal, then the trade
    const osLine = await page.evaluate(async () => {
      const q = await import('/static/js/pages/quantbase.js');
      const text = '25D RR 1A 1 haftada +1,2 vol (z +2,1; USD call\'ları pahalandı), spot henüz gelmedi → AL USDJPY spot · 1,1 mn USD · giriş 150,250 '
        + '· hedef 152,630 · stop 148,350 · beklenen +3,4 bin USD · isabet %57 (64)';
      const s = { id: 'optspot:FX:USDJPY', family: 'optspot', family_label: 'Opsiyon → spot', asset: 'FX', expression: text, line: text,
        z: 2.6, entry_z: 2, score_name: 'z(p)', strength: 'Orta', gates: [], legs: [], agree: 0, conflict: 0, parts: { z: 2.6, regime: 1, hl: 1, carry: 1 },
        composite: 2.6, hold: 5, horizon_unit: 'gün', bt: null, unit: '', digits: 3, entry: 150.25, target: 152.1, stop: 148.77, direction: 1,
        pnl_unit: '%', exp_pnl: 0.31, group: 'G10 spot', tier: null, tag: '', gated: '' };
      const head = ['#', 'Grup'].concat(q.SIGNAL_HEAD, ['Bileşik / neden', 'Saat']);
      const row = q.signalRows([s], { rank: true, group: true })[0];
      return { family: row[head.indexOf('Aile')].t, trade: row[head.indexOf('İşlem')].t, group: row[head.indexOf('Grup')].t };
    });
    check('... and an Opsiyon → spot line in the list: its family, the option signal behind the trade first, then the plan\'s line, its group',
      osLine.family === 'Opsiyon → spot' && osLine.trade.startsWith('25D RR 1A 1 haftada +1,2 vol')
      && osLine.trade.endsWith('→ AL USDJPY spot · 1,1 mn USD · giriş 150,250 · hedef 152,630 · stop 148,350 · beklenen +3,4 bin USD · isabet %57 (64)')
      && osLine.group === 'G10 spot', osLine);
    await shot(page, 'quant-optspot');
    // ------------------------------------------------------------------ DİBS switch (quantdibssw.py): a tab of Faiz
    // (the recorded month is too short for a ranking: the page says why; the bonds left out - the TLREF floaters - each with
    // its reason; a line as the server writes it, in the plan's format)
    console.log('quant dibs switch');
    await open(page, 'quant-dibssw');
    await page.waitForSelector('#quant-dibssw-switches', { timeout: 60000 });
    const swApi = await api(page, 'ayşe yilmaz', 'GET', '/api/quant/dibssw');
    const swTab = (swApi.json || {}).dibssw || {};
    await page.waitForFunction(() => document.querySelectorAll('#quant-dibssw-out table.grid tr:not(.hd)').length > 0
      || /evrende/.test((document.getElementById('quant-dibssw-out') || {}).textContent || ''), null, { timeout: 30000 });
    const swPage = await page.evaluate(() => ({
      tabs: [...document.querySelectorAll('#page-tabs button')].map((b) => b.textContent), on: [...document.querySelectorAll('#page-tabs button.on')].map((b) => b.dataset.page),
      lit: [...document.querySelectorAll('#nav .nav-item.active')].map((a) => a.dataset.page),
      head: (document.getElementById('quant-dibssw-head') || {}).textContent || '',
      out: document.querySelectorAll('#quant-dibssw-out table.grid tr:not(.hd)').length,
      read: ['quant-dibssw-signals', 'quant-dibssw-switches', 'quant-dibssw-bonds', 'quant-dibssw-out', 'quant-dibssw-backtest'].map((id) => {
        const p = document.getElementById(id);
        const r = p && p.querySelector(':scope > .qread');
        return { id, read: r ? r.textContent : '', under: !!r && (r.previousElementSibling || {}).tagName === 'HEADER' };
      }) }));
    check('DİBS switch is a tab of Faiz after Eğri Adil Değeri: its tables read in the desk\'s words under their titles; the recorded month says why there is no ranking',
      swApi.status === 200 && swApi.json.ready && swPage.tabs.join(',') === 'PCA / RV,Çiftler,Korelasyon,Rejim,Eğri Adil Değeri,DİBS switch,İma Patikası,TCMB WIRP,Öncü-Takipçi'
      && swPage.on.join() === 'quant-dibssw' && swPage.lit.join() === 'quant.faiz' && swPage.read.every((r) => r.read.length >= 40 && r.under)
      && (swTab.ok || (!!swTab.why && swPage.head.includes(swTab.why))) && swPage.out === (swTab.out || []).length && (swTab.out || []).every((o) => o.why),
      { tabs: swPage.tabs, why: swTab.why, head: swPage.head, out: swTab.out, read: swPage.read });
    const swLine = await page.evaluate(async () => {
      const q = await import('/static/js/pages/quantbase.js');
      const text = 'AL TRT150328T24 / SAT TRT130928T38 · switch · 210 mn / 205 mn · C+R +18,0 bp/ay · 1A momentum lehte · hedef +12,0 bp · stop -8,0 bp '
        + '· beklenen +504 bin TL · isabet %56 (142)';
      const s = { id: 'dibssw:TRT150328T24/TRT130928T38', family: 'dibssw', family_label: 'DİBS switch', asset: 'DİBS', expression: text, line: text,
        z: -2, entry_z: 1, score_name: 'sıra', strength: 'Güçlü', gates: [], legs: [], agree: 0, conflict: 0, parts: { z: 2, regime: 1, hl: 1, carry: 1 },
        composite: 2, hold: 5, horizon_unit: 'gün', bt: null, unit: 'bp', digits: 1, entry: 35.2, target: 23.2, stop: 43.2, direction: -1,
        pnl_unit: 'bp', exp_pnl: 12, group: 'DİBS', tier: null, tag: '', gated: '', info: { model: 'DİBS switch' } };
      const head = ['#', 'Grup'].concat(q.SIGNAL_HEAD, ['Bileşik / neden', 'Saat']);
      const row = q.signalRows([s], { rank: true, group: true })[0];
      return { family: row[head.indexOf('Aile')].t, trade: row[head.indexOf('İşlem')].t, group: row[head.indexOf('Grup')].t };
    });
    check('... and a DİBS switch line in the list: its family, the plan\'s line (both bonds, sizes, C+R, momentum, target / stop in bp, money, hit rate), group DİBS',
      swLine.family === 'DİBS switch' && swLine.trade.startsWith('AL TRT150328T24 / SAT TRT130928T38 · switch · 210 mn / 205 mn · C+R +18,0 bp/ay')
      && swLine.trade.endsWith('isabet %56 (142)') && swLine.group === 'DİBS', swLine);
    await shot(page, 'quant-dibssw');

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

    // ------------------------------------------------------------------ Trend (quanttrend.py): a tab of Sinyaller
    console.log('quant trend');
    await open(page, 'quant-trend');
    await page.waitForSelector('#quant-trend-table', { timeout: 30000 });
    await page.waitForFunction(() => window.tto.state.page && window.tto.state.page.data && window.tto.state.page.data.ready, null, { timeout: 90000 }).catch(() => null);
    const trendApi = await api(page, 'ayşe yilmaz', 'GET', '/api/quant/trend');
    const trRows = ((trendApi.json || {}).trend || {}).rows || [];
    await page.waitForFunction((n) => document.querySelectorAll('#quant-trend-table table.grid tr:not(.hd)').length === n, trRows.length, { timeout: 15000 }).catch(() => null);
    const trendShown = await page.locator('#quant-trend-table table.grid tr:not(.hd)').count();
    const trendRead = await page.evaluate(() => [...document.querySelectorAll('section.panel[id^="quant-trend-"]')].map((p) => {
      const r = p.querySelector(':scope > .qread');
      return { id: p.id, read: r ? r.textContent : '', under: !!r && (r.previousElementSibling || {}).tagName === 'HEADER' };
    }));
    const trendTabs = await page.evaluate(() => [...document.querySelectorAll('#page-tabs button')].map((b) => b.textContent));
    check('Trend: a tab of Sinyaller; its table lists every instrument of the universe (the recorded month is too short for a line: each says why), each table\'s read line under its title',
      trendApi.status === 200 && trRows.length > 0 && trendShown === trRows.length && trendTabs.join(',') === 'Sinyaller,Gün içi,Model,Trend,Carry + momentum,Makine öğrenmesi'
      && trRows.every((r) => r.sid || /^geçmiş kısa: \d+ gün \(en az 63\)$|^seviye oynamıyor/.test(r.why))
      && ['quant-trend-table', 'quant-trend-chart', 'quant-trend-buckets', 'quant-trend-groups'].every((id) => trendRead.some((p) => p.id === id && p.read.length >= 40 && p.under)),
    { rows: trRows.length, shown: trendShown, tabs: trendTabs, read: trendRead.map((p) => p.id + ':' + p.read.length), first: trRows[0] });
    // its group buttons filter the table, remembered by the group's name
    const trGroup = (trRows.find((r) => r.group === 'TRY OIS') || trRows[0] || {}).group;
    await page.click('#quant-trend-group button[data-v="' + trGroup + '"]');
    await page.waitForFunction((n) => document.querySelectorAll('#quant-trend-table table.grid tr:not(.hd)').length === n,
      trRows.filter((r) => r.group === trGroup).length, { timeout: 10000 }).catch(() => null);
    const trOne = await page.evaluate(() => ({ rows: [...document.querySelectorAll('#quant-trend-table table.grid tr:not(.hd)')].map((tr) => tr.children[1] && tr.children[1].textContent),
      kept: (() => { try { return localStorage.getItem('tto.quant.trend.group'); } catch (e) { return null; } })() }));
    await page.click('#quant-trend-group button[data-v=""]');
    check('... its group buttons show one group\'s rows, the choice remembered by the group\'s name',
      trOne.rows.length === trRows.filter((r) => r.group === trGroup).length && trOne.kept === trGroup, { trGroup, trOne });
    await shot(page, 'quant-trend');
    // the Sinyaller list shows a Trend line in the plan's format (the recorded month has none: one as the server sends it);
    // its card: the sentence first, the trade at the line's own size, the score without an entry threshold
    const TREND_LINE = 'YENİ · SAT USDTRY 1A forward · 1 mn USD · offshore limiti · giriş 44,3500 · hedef 44,0500 · stop 44,5500 · beklenen +300 bin TRY'
      + ' · isabet %61 (148) · model: Trend';
    const trendCard = await page.evaluate(async (line) => {
      const q = await import('/static/js/pages/quantbase.js');
      const s = { id: 'trend:FWD:USDTRY:1M', family: 'trend', family_label: 'Trend', kind: 'sys', daily: true, new: true, asset: 'Offshore', group: 'Offshore',
        tier: null, tag: 'offshore limiti', expression: 'SAT USDTRY 1A forward', line, z: -1.2, entry_z: 1, strength: 'Güçlü', score_name: 'skor', gates: [],
        legs: [{ key: 'FX:USDTRY', name: 'USDTRY 1A forward', action: 'Sell', side: -1, weight: 1, text: 'Sell USDTRY 1A forward' }], agree: 0, conflict: 0,
        parts: { z: 2.4, regime: 1, hl: 1, carry: 1 }, composite: 2.4, hold: 21, horizon_unit: 'gün', bt: null, direction: -1, unit: '', digits: 4,
        entry: 44.35, target: 44.05, stop: 44.55, pnl_unit: '%', exp_pnl: 0.68, trade_tr: 'USDTRY 1A forward sat', info: { size: '1,4 mn USD' },
        plain: 'YENİ - yön bugün döndü. SAT USDTRY 1A forward · 1,4 mn USD · offshore limiti. Neden: 1A ↓, 3A ↓, 1Y ↓ - üç ufuk da düşüşte.',
        px: { pair: 'USDTRY', inst: 'USDTRY 1A forward', label: 'USDTRY 1A fwd', tenor: '1A', days: 30.4, note: 'bugünkü 1A forward', digits: 4, unit: 'TRY',
          entry: 44.35, target: 44.05, stop: 44.55, exit: 44.05, spot: 44.0, spot_exp: 43.9, fwd_h: 44.35 },
        money: { ccy: 'TRY', base: 'USD', notional: 1e6, total: 300000, carry: 350000, move: -50000, target: 300000, stop: -200000, try_per: 1, usd_per: 1 / 44 } };
      const rows = q.signalRows([s], { rank: true, group: true });
      const head = ['#', 'Grup'].concat(q.SIGNAL_HEAD, ['Bileşik / neden', 'Saat']);
      const host = document.createElement('div');
      const c = new q.SignalChart(host);
      const data = { monitor: { name: 'USDTRY 1A forward', family_label: 'Trend' }, signal: s, history: { days: ['2026-11-02'], values: [1] }, settings: {}, rationale: null };
      c.show(data);
      c.fillDetails(data);                       // (a one-day history draws no chart and no details: the score's row asked for here)
      const text = (sel) => (host.querySelector(sel) || {}).textContent || '';
      const out = { cell: rows[0][head.indexOf('İşlem')].t, group: rows[0][1].t, plain: text('#quant-sig-plain'), trade: text('#quant-sig-trade'),
        score: ([...host.querySelectorAll('.qkv tr')].find((tr) => tr.firstChild && tr.firstChild.textContent === 'Skor') || {}).textContent || '' };
      c.destroy();
      return out;
    }, TREND_LINE);
    check('... the Sinyaller list shows a Trend line in the plan\'s format ("YENİ · SAT USDTRY 1A forward · 1 mn USD · … · isabet %61 (148) · model: Trend"); '
      + 'its card: the sentence, the trade at the line\'s size, the score without an entry threshold',
      trendCard.cell === TREND_LINE && trendCard.group === 'Offshore · offshore limiti' && trendCard.plain.startsWith('YENİ - yön bugün döndü. SAT USDTRY 1A forward')
      && trendCard.trade === 'USDTRY 1A forward sat · 1,4 mn USD' && trendCard.score === 'Skorskor -1,20 · Güçlü', trendCard);

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
    // "Sıkışık görünüm" (the user menu): rows shorter, the text a step smaller - kept with the account; a window of its own
    // open in the same browser follows at once, a reload keeps it
    await open(page, 'forward');
    const b1Row = (p) => p.evaluate(() => {
      const t = document.querySelector('#content .panel[data-panel="B1"] table.grid, .lp-item[data-key="forward/B1"] table.grid');
      const tr = t && [...t.rows].find((r) => !r.classList.contains('hd') && !r.classList.contains('ttl') && r.cells.length > 1);
      return tr ? { h: tr.getBoundingClientRect().height, fs: parseFloat(getComputedStyle(tr.cells[tr.cells.length - 1]).fontSize),
        on: document.documentElement.classList.contains('compact') } : null;
    });
    const roomy = await b1Row(page);
    const popC = await ctxA.newPage();
    popC.on('pageerror', (e) => errors.push('pageerror(pop compact): ' + e.message));
    await popC.goto(BASE + '/#/pop/forward/B1');
    await popC.waitForSelector('.lp-item[data-key="forward/B1"] table.grid', { timeout: 60000 });
    const popRoomy = await b1Row(popC);
    await page.click('#btn-user');
    await page.check('#menu-compact');
    await page.keyboard.press('Escape');
    await popC.waitForFunction(() => document.documentElement.classList.contains('compact'), null, { timeout: 15000 }).catch(() => null);
    const tight = await b1Row(page);
    const popTight = await b1Row(popC);
    check('"Sıkışık görünüm" (the user menu): a grid row shorter, its text a step smaller (one class on the page), kept with the account; '
      + 'a window of its own open in the same browser follows at once',
      !roomy.on && tight.on && tight.h < roomy.h && tight.fs < roomy.fs && (await savedLayout((l) => l.compact === true)).compact === true
      && popTight.on && popTight.h < popRoomy.h, { roomy, tight, popRoomy, popTight });
    await popC.close();
    await page.reload();
    await page.waitForFunction(() => window.tto && window.tto.state.pageId === 'forward' && window.tto.state.page && window.tto.state.page.ready,
      null, { timeout: 90000 });
    const tightAgain = await b1Row(page);
    await page.click('#btn-user');
    const ticked = await page.isChecked('#menu-compact');
    await page.uncheck('#menu-compact');
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => !document.documentElement.classList.contains('compact'), null, { timeout: 10000 }).catch(() => null);
    const roomyAgain = await b1Row(page);
    check('... a reload keeps it (ticked in the menu); turned off, the rows are as tall as before - on the server too',
      tightAgain.on && Math.abs(tightAgain.h - tight.h) < 0.5 && ticked && !roomyAgain.on && Math.abs(roomyAgain.h - roomy.h) < 0.5
      && (await savedLayout((l) => l.compact === false)).compact === false, { tightAgain, roomyAgain, ticked });
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

    // ------------------------------------------------------------------ rows and columns that are not the sheet's
    // a launchpad's rows kept across a day change; pointing and pasting on a part of a table and on one's own column
    // order; tables and columns of the dashboard's own when pointed at; the pointed cells marked when their table is
    // drawn anew.  (Mehmet, on a launchpad of his own: nothing of Ayşe's changes.)
    console.log('launchpad parts: rows kept, pointing, paste');
    const ctxR = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
    const pageR = await ctxR.newPage();
    pageR.on('pageerror', (e) => errors.push('pageerror(R): ' + e.message));
    await login(pageR, 'Mehmet');
    const asM = (method, path, body) => api(pageR, 'mehmet', method, path, body);
    const valueOf = async (ref) => ((await asM('GET', '/api/cell?book=tto&ref=' + encodeURIComponent(ref))).json.cell || {}).v;
    const gridOf = (key) => '#lp-grid .lp-item[data-key="' + key + '"] table.grid';
    // his own order of IMPLIED RATES' columns (V before U), and a launchpad: the value date (Forward), MPC OIS, IMPLIED
    // RATES' meetings MPC1, MPC3, MPC5, the DİBS tape, two bonds of DİBS RV with the broker columns
    const impCols = (await asM('POST', '/api/panels', { items: [{ key: 'imp', view: 'ois', panel: 'B4' }] })).json.panels.imp.entry.data.c;
    const impOrder = impCols.filter((c) => c !== 'V');
    impOrder.splice(impOrder.indexOf('U'), 0, 'V');
    await asM('POST', '/api/columns', { table: 'v/ois/B4', order: impOrder });
    await asM('POST', '/api/layout', { launchpads: [{ name: 'Satır', items: [
      { id: 'r-fwd', view: 'forward', panel: 'B1', w: 6 }, { id: 'r-mpc', view: 'ois', panel: 'B13', w: 6 },
      { id: 'r-imp', view: 'ois', panel: 'B4', w: 12, rows: ['MPC1', 'MPC3', 'MPC5'] },
      { id: 'r-tape', view: 'dibslive', panel: 'L3', w: 6 }, { id: 'r-rv', view: 'dibs', panel: 'B3', w: 12, rows: [5, 6] }] }] });
    await pageR.evaluate(() => { window.location.hash = '#/launchpad/Satır'; });
    await pageR.reload();                                           // (his column order: read as the dashboard opens)
    await pageR.waitForFunction(() => window.tto && window.tto.state.pageId === 'launchpad'
      && document.querySelectorAll('#lp-grid .lp-item table.grid').length === 5, null, { timeout: 120000 });
    // MPC OIS by "MPC1→2" … (its rows read "MPC1→2 · 1.2–2.6A": the months to the meetings, fewer every day)
    await pageR.click('#lp-grid .lp-item[data-key="ois/B13"] button[data-action="item-menu"]');
    await pageR.click('.menu >> text=Satırlar ve sütunlar…');
    await pageR.waitForSelector('.lp-picker .lp-pick input');
    const pickKeys = await pageR.evaluate(() => [...document.querySelectorAll('.lp-picker .lp-pick-side')[0].querySelectorAll('.lp-pick input')]
      .map((b) => JSON.parse(b.dataset.key)));
    await pageR.evaluate((want) => {
      for (const b of document.querySelectorAll('.lp-picker .lp-pick-side')[0].querySelectorAll('.lp-pick input')) b.checked = want.includes(JSON.parse(b.dataset.key));
    }, ['MPC1→2', 'MPC3→4']);
    await pageR.click('#lp-pick-save');
    const lpRowsSaved = async () => {
      for (let i = 0; i < 60; i++) {
        const l = (await asM('GET', '/api/layout')).json;
        const it = ((l.launchpads.find((x) => x.name === 'Satır') || { items: [] }).items.find((x) => x.id === 'r-mpc')) || {};
        if ((it.rows || []).length === 2) return it.rows;
        await pageR.waitForTimeout(250);
      }
      return null;
    };
    const lpRows = await lpRowsSaved();
    const mpcBox = () => pageR.evaluate((s) => {
      const g = document.querySelector(s).__grid;
      const name = (r) => { const i = g.data.r.indexOf(r); return i < 0 ? '' : ((g.data.rows[i].find((c) => c && c.k === 's' && c.t) || {}).t || ''); };
      return { r: g.data.r.join(','), one: name(84), three: name(86), missing: !!g.data.part_missing };
    }, gridOf('ois/B13'));
    await pageR.waitForFunction((s) => { const r = document.querySelector(s).__grid.data.r; return r.includes(84) && r.includes(86) && !r.includes(85); },
      gridOf('ois/B13'), { timeout: 30000 });
    const mpc0 = await mpcBox();
    // a day on: his own "Elle değer" over the OIS spot date (OIS_MAIN!B2 = TODAY's next business day) a week later -
    // the months to each meeting count down as on a later day (the server's clock stays where it is)
    const spot = await valueOf('OIS_MAIN!B2');
    const later = await asM('POST', '/api/inputs', { book: 'tto', items: [{ ref: 'OIS_MAIN!B2', value: dayText(spot + 7) }], adhoc: true });
    await pageR.waitForFunction(([s, was]) => {
      const g = document.querySelector(s).__grid;
      const i = g.data.r.indexOf(84);
      const t = i < 0 ? '' : ((g.data.rows[i].find((c) => c && c.k === 's' && c.t) || {}).t || '');
      return !!t && t !== was;
    }, [gridOf('ois/B13'), mpc0.one], { timeout: 60000 }).catch(() => null);
    const mpc1 = await mpcBox();
    check('a launchpad keeps MPC OIS\' rows by "MPC1→2" (not "MPC1→2 · 1.2–2.6A": the months count down every day) - a week later '
      + '(his own spot date) the same two rows, no "artık yok" note', JSON.stringify(lpRows) === '["MPC1→2","MPC3→4"]'
      && pickKeys.slice(0, 3).join(',') === 'MPC1→2,MPC2→3,MPC3→4' && (later.json.errors || []).length === 0
      && mpc1.r === mpc0.r && !mpc1.missing && mpc1.one !== mpc0.one && mpc1.one.startsWith('MPC1→2 · ') && mpc1.three.startsWith('MPC3→4 · '),
    { lpRows, keys: pickKeys.slice(0, 4), later: later.json, mpc0, mpc1 });
    await asM('POST', '/api/reset', { book: 'tto', refs: ['OIS_MAIN!B2'] });
    // a paste from Excel onto the part (MPC1, MPC3, MPC5) and onto his order of the columns (V, U, W): where it looks like
    // it lands - not the sheet's next rows (MPC2) nor its next column (W after V)
    const impBox = gridOf('ois/B4');
    const pasteAt = (r, c, text) => pageR.evaluate(async ([s, r, c, text]) => {
      const g = document.querySelector(s).__grid;
      const mod = await import('/static/js/grid.js');
      const i = g.data.r.indexOf(r), j = g.data.c.indexOf(c);
      await mod.pasteText(g, { grid: g, top: i, left: j, bottom: i, right: j }, text);
    }, [impBox, r, c, text]);
    const impShown = await pageR.evaluate((s) => { const d = document.querySelector(s).__grid.data; return d.r.filter((r) => r >= 10).join(',') + '|' + d.c.join(''); }, impBox);
    await pasteAt(10, 'U', '-25\r\n-50\r\n-75');
    const rowsPasted = [await valueOf('OIS_MAIN!U10'), await valueOf('OIS_MAIN!U11'), await valueOf('OIS_MAIN!U12'), await valueOf('OIS_MAIN!U14')];
    await pasteAt(10, 'V', '-10\t-20\t-30');
    const colsPasted = [await valueOf('OIS_MAIN!V10'), await valueOf('OIS_MAIN!U10'), await valueOf('OIS_MAIN!W10')];
    check('a block from Excel pasted onto a part of a table lands on the rows on screen (MPC1, MPC3, MPC5 - not MPC2), and onto one\'s own '
      + 'column order on the columns on screen (V, U, W)', impShown.startsWith('10,12,14|') && impShown.includes('VUW')
      && rowsPasted[0] === -25 && rowsPasted[1] == null && rowsPasted[2] === -50 && rowsPasted[3] === -75 && colsPasted.join(',') === '-10,-20,-30',
    { impShown, rowsPasted, colsPasted });
    await asM('POST', '/api/reset', { book: 'tto', refs: ['OIS_MAIN!U10', 'OIS_MAIN!U12', 'OIS_MAIN!U14', 'OIS_MAIN!V10', 'OIS_MAIN!W10'] });
    // pointing: "=" in the value date, then blocks dragged over IMPLIED RATES - one the sheet has as it shows (V, U: U10:V10)
    // goes in; one that would take in a row or column the block leaves out (MPC1 → MPC3: MPC2's row; U → W: V) does not
    const centre = (ref) => pageR.evaluate((r) => { const b = window.tto.findCell(r).getBoundingClientRect(); return [b.left + b.width / 2, b.top + b.height / 2]; }, ref);
    const drag = async (from, to) => {
      let [x, y] = await centre(from);
      await pageR.mouse.move(x, y);
      await pageR.mouse.down();
      for (const ref of to) {
        [x, y] = await centre(ref);
        await pageR.mouse.move(x, y, { steps: 5 });
      }
      const text = await pageR.inputValue('td.editing input');
      await pageR.mouse.up();
      return text;
    };
    const saidR = (t) => pageR.evaluate((x) => [...document.querySelectorAll('#toasts .toast')].filter((el) => el.textContent.includes(x)).length, t);
    const marks = () => pageR.evaluate(() => [...document.querySelectorAll('td.pt')].map((td) => td.closest('table.grid').__grid.ref(td.__i, td.__j)).sort().join(','));
    await (await cellHandle(pageR, 'Forward!D2')).click();
    await pageR.keyboard.type('=');
    await pageR.evaluate((s) => document.querySelector(s).scrollIntoView({ block: 'center' }), impBox);
    const rowGap = await drag('OIS_MAIN!U10', ['OIS_MAIN!U12']);
    const gapSaid = await saidR('tek bir aralık değil');
    const colGap = await drag('OIS_MAIN!U10', ['OIS_MAIN!W10']);
    const colBlock = await drag('OIS_MAIN!U10', ['OIS_MAIN!W10', 'OIS_MAIN!V10']);
    const marked = await marks();
    check('pointing at a block of a part / of one\'s own column order: V..U goes in as the sheet has it (U10:V10, both marked); MPC1 → MPC3 '
      + '(MPC2 between) and U → W (V between) are refused with the reason, the reference before them stays',
      rowGap === '=OIS_MAIN!U10' && gapSaid >= 1 && colGap === '=OIS_MAIN!U10' && colBlock === '=OIS_MAIN!U10:V10'
      && marked === 'OIS_MAIN!U10,OIS_MAIN!V10', { rowGap, gapSaid, colGap, colBlock, marked });
    // the pointed table drawn anew (a row more: its shape changed) while the formula is typed: its cells are marked again
    const rebuilt = await pageR.evaluate((s) => {
      const g = document.querySelector(s).__grid;
      const d = JSON.parse(JSON.stringify(g.source));
      d.rows.push(d.rows[d.rows.length - 1].map((c) => Object.assign({}, c)));
      d.r.push(d.r[d.r.length - 1] + 1);
      const before = g.tds.length;
      g.update(d);
      return g.tds.length - before;
    }, impBox);
    const remarked = await marks();
    check('... the pointed cells stay marked when their table is drawn anew while the formula is typed', rebuilt === 1 && remarked === marked,
      { rebuilt, remarked });
    // a table of the dashboard's own (the DİBS tape: no sheet) and a column it adds to DİBS RV (Broker bid): no reference,
    // the reason said (each time: counted as the toasts come), the formula as it was
    await pageR.evaluate(() => {
      window.__noSheet = 0;
      new MutationObserver((ms) => {
        for (const m of ms) for (const n of m.addedNodes) if ((n.textContent || '').includes('çalışma kitabı sayfasında değil')) window.__noSheet += 1;
      }).observe(document.getElementById('toasts'), { childList: true });
    });
    const tapeTd = (await pageR.evaluateHandle((s) => document.querySelector(s).__grid.tds[1].find(Boolean), gridOf('dibslive/L3'))).asElement();
    await tapeTd.click();
    await pageR.waitForFunction(() => window.__noSheet >= 1, null, { timeout: 10000 }).catch(() => null);
    const afterTape = await pageR.inputValue('td.editing input');
    const brokerTd = (await pageR.evaluateHandle((s) => {
      const g = document.querySelector(s).__grid;
      const j = g.data.c.indexOf('Broker bid');
      const i = g.data.r.indexOf(5);
      return j >= 0 && i >= 0 ? g.tds[i][j] : null;
    }, gridOf('dibs/B3'))).asElement();
    if (brokerTd) await brokerTd.click();
    await pageR.waitForFunction(() => window.__noSheet >= 2, null, { timeout: 10000 }).catch(() => null);
    const afterBroker = await pageR.inputValue('td.editing input');
    const noSheet = await pageR.evaluate(() => window.__noSheet);
    await pageR.keyboard.press('Escape');
    check('pointing at the DİBS tape (no sheet) or at a column the dashboard adds (Broker bid) puts no reference in: "çalışma kitabı '
      + 'sayfasında değil"', !!brokerTd && afterTape === '=OIS_MAIN!U10:V10' && afterBroker === '=OIS_MAIN!U10:V10' && noSheet === 2,
    { afterTape, afterBroker, noSheet, broker: !!brokerTd });
    await ctxR.close();

    // ------------------------------------------------------------------ temporary copies of a calculator
    console.log('temporary copies');
    await open(page, 'masa');
    await tab(page, 'fwd');
    const kvOrig = '#content .panel[data-panel="B22"]';
    const kvCopy = '#content .panel.copy[data-copy-of="B22"]';
    await page.waitForSelector(kvOrig + ' table.grid', { timeout: 30000 });
    await page.hover(kvOrig);
    await page.click(kvOrig + ' .tools button[data-action="launchpad"]');
    const kvMenu = await page.evaluate(() => [...document.querySelectorAll('.menu button')].map((b) => b.textContent));
    await page.click('.menu >> text=Geçici kopya aç');
    await page.waitForSelector(kvCopy + ' table.grid', { timeout: 30000 });
    const kvPlace = await page.evaluate(([o, c]) => {
      const a = document.querySelector(o);
      const b = document.querySelector(c);
      return { next: a.nextElementSibling === b, title: b.querySelector('header h2').textContent, id: b.dataset.panel };
    }, [kvOrig, kvCopy]);
    check('"Geçici kopya aç" in the "+ Launchpad" menu of Masa\'s KIRIK VADE & KARŞILIK: the copy is right under the table, "… · kopya 2"',
      kvMenu.includes('Geçici kopya aç') && kvPlace.next && / · kopya 2$/.test(kvPlace.title) && /^B22\.k[0-9a-f]{8}$/.test(kvPlace.id),
      { kvMenu, kvPlace });
    // another value date typed into the copy: its results change, the table's do not
    const copyText = (ref) => page.evaluate(([s, r]) => { const td = window.tto.copyCell(s, r); return td ? td.textContent : null; }, [kvCopy, ref]);
    const kvDays = await cellText(page, 'MASA!E171');
    const kvFwd = await cellText(page, 'MASA!F173');
    const kvDays0 = await copyText('MASA!E171');
    const kvDate = (await page.evaluateHandle((s) => window.tto.copyCell(s, 'MASA!C171'), kvCopy)).asElement();
    await kvDate.scrollIntoViewIfNeeded();
    await kvDate.click();
    await page.keyboard.press('Enter');
    await page.waitForSelector('td.editing input');
    await page.keyboard.press('Control+a');
    await page.keyboard.type('15.06.2027');
    await page.keyboard.press('Enter');
    await page.waitForFunction(([s, d]) => { const td = window.tto.copyCell(s, 'MASA!E171'); return !!td && td.textContent !== d; },
      [kvCopy, kvDays0], { timeout: 30000 });
    const copyDays = await copyText('MASA!E171');
    const copyFwd = await copyText('MASA!F173');
    check('another value date typed into the copy changes the copy\'s results (days, forward) ...',
      (await copyText('MASA!C171')).trim() === '15.06.2027' && copyDays !== kvDays && copyFwd !== kvFwd && kvDays0 === kvDays,
      { copyDays, kvDays, copyFwd, kvFwd, kvDays0 });
    check('... and not the table\'s', (await cellText(page, 'MASA!E171')) === kvDays && (await cellText(page, 'MASA!F173')) === kvFwd
      && (await cellText(page, 'MASA!C171')).trim() !== '15.06.2027');
    // a price of the copy offers no "İşlem gir" (its prices follow its own inputs, "İşlem gir" reads the table's row); the
    // table's own price does, first
    const kvPrice = (await page.evaluateHandle((s) => window.tto.copyCell(s, 'MASA!F173'), kvCopy)).asElement();
    await kvPrice.scrollIntoViewIfNeeded();
    await kvPrice.click({ button: 'right' });
    await page.waitForSelector('.menu');
    const copyMenu = await page.$$eval('.menu button', (bs) => bs.map((b) => b.textContent));
    await page.keyboard.press('Escape');
    await (await cellHandle(page, 'MASA!F173')).click({ button: 'right' });
    await page.waitForSelector('.menu');
    const tableMenu = await page.$$eval('.menu button', (bs) => bs.map((b) => b.textContent));
    await page.keyboard.press('Escape');
    check('a price of the copy offers no "İşlem gir" (nor a row\'s quote); the table\'s own price has it first',
      !copyMenu.some((x) => /İşlem gir|kotasyonu/.test(x)) && copyMenu.some((x) => /^Kopyala/.test(x)) && tableMenu[0] === 'İşlem gir',
      { copyMenu, tableMenu });
    await shot(page, '45-copy');
    // a reload: the copy is still there, with its value date
    await page.reload();
    await page.waitForFunction(() => window.tto && window.tto.state.pageId === 'masa' && window.tto.state.page && window.tto.state.page.ready,
      null, { timeout: 90000 });
    await tab(page, 'fwd');
    await page.waitForSelector(kvCopy + ' table.grid', { timeout: 30000 });
    await fresh(page);
    check('after a reload the copy is still there, with its own value date and results',
      (await copyText('MASA!C171')).trim() === '15.06.2027' && (await copyText('MASA!E171')) === copyDays
      && (await cellText(page, 'MASA!E171')) === kvDays);
    // like any table, the copy goes to the side drawer from its own "+ Launchpad" menu
    const kvBox = '#drawer .lp-item[data-key="masa/' + kvPlace.id + '"]';
    await page.hover(kvCopy);
    await page.click(kvCopy + ' .tools button[data-action="launchpad"]');
    await page.click('.menu >> text=Yan panele sabitle');
    await page.waitForSelector(kvBox + ' table.grid', { timeout: 30000 });
    const boxDate = await page.evaluate((s) => { const td = window.tto.copyCell(s, 'MASA!C171'); return td ? td.textContent.trim() : null; }, kvBox);
    check('the copy in the side drawer: its own value date, a box of the copy (not of the table)',
      boxDate === '15.06.2027' && await page.evaluate((s) => document.querySelector(s).classList.contains('copy'), kvBox), boxDate);
    // × closes it (what was typed into it goes: asked first) - and takes it off the drawer
    await page.hover(kvCopy);
    await page.click(kvCopy + ' .tools button[data-action="copy-close"]');
    await page.click('.modal .btn.primary');
    await page.waitForFunction(() => !document.querySelector('#content .panel.copy'), null, { timeout: 30000 });
    await page.waitForFunction((s) => !document.querySelector(s), kvBox, { timeout: 30000 });
    const kvLeft = await api(page, 'ayşe yilmaz', 'GET', '/api/copies');
    check('× closes the copy: gone from the page, the side drawer and the account; the table stays',
      kvLeft.json && kvLeft.json.copies.length === 0 && await page.locator(kvOrig + ' table.grid').count() === 1
      && !(await layoutOf('ayşe yilmaz')).drawer.some((x) => x.panel === kvPlace.id), kvLeft.json);
    if (await page.evaluate(() => document.getElementById('app').classList.contains('drawer-open'))) await page.click('#dr-close');

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
    check('the quant menu: four entries - Sinyaller (6 tabs: Trend, Carry + momentum and Makine öğrenmesi among them), Faiz (9: DİBS switch among them), FX (4: Opsiyon → spot among them), VİOP', JSON.stringify(quantMenu) === '["Sinyaller:6","Faiz:9","FX:4","VİOP:0"]', quantMenu);
    await open(page, 'quant-regime');                                       // an address of before
    const onTab = () => page.evaluate(() => ({ tabs: [...document.querySelectorAll('#page-tabs button')].map((b) => b.textContent),
      on: [...document.querySelectorAll('#page-tabs button.on')].map((b) => b.dataset.page), lit: [...document.querySelectorAll('#nav .nav-item.active')].map((a) => a.dataset.page) }));
    const regime = await onTab();
    check('an old address (#/quant-regime) opens Faiz on its tab: nine tabs, "Rejim" on, Faiz lit in the menu',
      regime.tabs.join(',') === 'PCA / RV,Çiftler,Korelasyon,Rejim,Eğri Adil Değeri,DİBS switch,İma Patikası,TCMB WIRP,Öncü-Takipçi'
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

    // ------------------------------------------------------------------ fair value RET (retfair.js) and the position panel
    console.log('fair value RET');
    await open(page, 'forward');
    await page.click('#btn-ret');
    await page.waitForSelector('.modal table.ret');
    await page.click('#ret-tab-fair');
    await page.waitForSelector('#retfair-table tbody tr[data-tenor="2Y"]');
    const fairRow = (t) => page.evaluate((x) => {
      const q = (s) => document.querySelector(s + '[data-tenor="' + x + '"]');
      return { now: q('td.retfair-now').textContent, pub: q('td.retfair-pub').textContent, formula: q('td.retfair-formula').textContent,
        off: q('input.retfair-off').value };
    }, t);
    const sideOf = (text, k) => trNumber(text.split(' / ')[k]);
    check('the RET dialog has its fair value part: a row per tenor, no value before an offset is set',
      (await page.locator('#retfair-table tbody tr[data-tenor]').count()) === 15 && (await fairRow('1M')).now === '—', await fairRow('1M'));
    await page.click('#retfair-from-pub');                             // nothing selected: every tenor
    await page.waitForFunction(() => { const td = document.querySelector('td.retfair-now[data-tenor="1M"]'); return td && td.textContent !== '—'; });
    const fair1 = await fairRow('1M');
    check('"Yayınlanandan al": each tenor\'s offset gives the published RET back (Şimdiki = Yayınlanan), no banner',
      fair1.now === fair1.pub && await page.isHidden('#retfair-banner') && /^OIS mid [−+] \d+$/.test(fair1.formula), fair1);
    // "Tabana göre": Mid by default; one click and the base sets the bid (the same spread now puts the bid where the mid was
    // less half the width: 20 bp wide, 10 bp up); for many at once from the bar above (nothing selected: all)
    const anchorOn = (t) => page.$eval('.retfair-anchor[data-tenor="' + t + '"] button.on', (b) => b.dataset.anchor).catch(() => null);
    check('"Tabana göre" shows Bid / Mid / Ask on every row, Mid by default', (await page.locator('.retfair-anchor').count()) === 15
      && await anchorOn('1M') === 'mid' && await anchorOn('2Y') === 'mid');
    await page.click('.retfair-anchor[data-tenor="1M"] button[data-anchor="bid"]');
    await page.waitForFunction(() => /^Bid = OIS mid/.test(document.querySelector('td.retfair-formula[data-tenor="1M"]').textContent), null, { timeout: 20000 });
    const fairBid = await fairRow('1M');
    check('"Tabana göre: Bid": "Bid = OIS mid − N", Şimdiki 10 bp up (bid = base + spread), the width kept',
      /^Bid = OIS mid [−+] \d+$/.test(fairBid.formula) && Math.abs(sideOf(fairBid.now, 0) - sideOf(fair1.now, 0) - 0.10) < 1e-9
      && Math.abs(sideOf(fairBid.now, 1) - sideOf(fairBid.now, 0) - (sideOf(fair1.now, 1) - sideOf(fair1.now, 0))) < 1e-9 && await anchorOn('1M') === 'bid', [fair1, fairBid]);
    await page.click('#retfair-bulk-anchor button[data-anchor="mid"]');
    await page.waitForFunction(() => /^OIS mid/.test(document.querySelector('td.retfair-formula[data-tenor="1M"]').textContent), null, { timeout: 20000 });
    check('... and back to Mid for every tenor from the bar (nothing selected): the published RET again', (await fairRow('1M')).now === fair1.now
      && await anchorOn('1M') === 'mid' && await page.isHidden('#retfair-banner'));
    // "Senaryo": the user's own view - a PPK scenario of the OIS page by its name, every tenor under each side by side
    check('the scenario is the market by default, with the scenarios to choose by their names',
      (await page.textContent('#retfair-scen-label')) === 'Senaryo: Piyasa (bootstrap)'
      && JSON.stringify(await page.$$eval('#retfair-scenario option', (os) => os.map((o) => o.textContent))) === JSON.stringify(['Piyasa (bootstrap)', 'S1 · Baz', 'S2 · Hawkish', 'S3 · Dovish'])
      && (await page.locator('#retfair-scen-table tbody tr').count()) === 15 && await page.isHidden('#retfair-scen-note'));
    await page.selectOption('#retfair-scenario', 'S2');
    await page.waitForFunction(() => document.getElementById('retfair-scen-label').textContent === 'Senaryo: S2 · Hawkish', null, { timeout: 20000 });
    const scenCells = await page.$$eval('#retfair-scen-table td[data-tenor="3M"]', (tds) => Object.fromEntries(tds.map((td) => [td.dataset.scen, td.textContent])));
    const fair3s = await fairRow('3M');
    check('a scenario chosen: the tab says which ("Senaryo: S2 · Hawkish"), its rows are the scenario\'s, the table shows it beside the market',
      await page.isVisible('#retfair-scen-note') && /^\d+,\d\d \/ \d+,\d\d/.test(fair3s.now) && scenCells.S2.startsWith(fair3s.now)
      && Object.keys(scenCells).join() === 'piyasa,S1,S2,S3' && (await page.$eval('#retfair-scen-table th.cur', (th) => th.textContent)) === 'S2 · Hawkish', [fair3s, scenCells]);
    await page.selectOption('#retfair-scenario', 'piyasa');
    await page.waitForFunction(() => document.getElementById('retfair-scen-label').textContent === 'Senaryo: Piyasa (bootstrap)', null, { timeout: 20000 });
    check('... and back to the market: the published RET again', (await fairRow('1M')).now === fair1.now && await page.isHidden('#retfair-scen-note'));
    // a base and an offset changed: Şimdiki moves, the banner (and the RET button) names the tenors
    await page.selectOption('select.retfair-base[data-tenor="1M"]', 'viop');
    await page.waitForFunction(() => /^VİOP mid/.test(document.querySelector('td.retfair-formula[data-tenor="1M"]').textContent));
    const off2M = await page.inputValue('input.retfair-off[data-tenor="2M"]');
    await page.fill('input.retfair-off[data-tenor="2M"]', String(trNumber(off2M) + 25));
    await page.press('input.retfair-off[data-tenor="2M"]', 'Enter');
    await page.waitForFunction(() => /1M, 2M/.test(document.getElementById('retfair-banner').textContent), null, { timeout: 20000 });
    const fair1b = await fairRow('1M'), fair2 = await fairRow('2M');
    check('a base (1M → VİOP mid) and an offset (2M +25 bp): Şimdiki changes, "RET güncellemesi var: 1M, 2M"',
      fair1b.now !== fair1b.pub && Math.abs(sideOf(fair2.now, 0) - sideOf(fair2.pub, 0) - 0.25) < 1e-9
      && (await page.textContent('#retfair-banner')) === 'RET güncellemesi var: 1M, 2M', [fair1b, fair2]);
    await page.waitForFunction(() => /1M, 2M/.test(document.getElementById('ret-upd').textContent)
      && !document.getElementById('ret-upd').classList.contains('hidden'), null, { timeout: 30000 });
    check('... the RET button says it too', true);
    // "Kopyala ve yayınla": the clipboard and the desk's RET, the same numbers; every table of the RET follows
    await page.click('#retfair-fmt-table');
    await page.click('#retfair-publish');
    await page.waitForFunction(() => /RET yayınlandı/.test(document.getElementById('toasts').textContent), null, { timeout: 20000 });
    const pubToast = await page.textContent('#toasts');
    check('... the toast says which tenors moved and by how much ("1M … · 2M +25 / +25")',
      /RET yayınlandı ve kopyalandı: 1M [+−]\d+(,\d)? \/ [+−]\d+(,\d)? · 2M \+25 \/ \+25 \(15 vade\)/.test(pubToast), pubToast);
    const pubTsv = (await page.evaluate(() => navigator.clipboard.readText())).split('\r\n');
    const new1M = fair1b.now.split(' / ');
    check('"Kopyala ve yayınla": the new curve on the clipboard in the dialog\'s table format',
      pubTsv[0] === 'Vade\tGün\tBid\tAsk' && pubTsv.includes('1M\t30\t' + new1M[0] + '\t' + new1M[1]) && pubTsv.length === 16, pubTsv.slice(0, 8));
    const retAfterPub = await api(page, 'ayşe yilmaz', 'GET', '/api/ret');
    const histAfterPub = await api(page, 'ayşe yilmaz', 'GET', '/api/ret/history');
    check('... written as the desk\'s RET, in its history (who, when, what); the banner is gone',
      Math.abs(retAfterPub.json.rows.find((r) => r.tenor === '1M').bid * 100 - trNumber(new1M[0])) < 1e-9
      && histAfterPub.json.history[0].user === 'ayşe yilmaz' && await page.isHidden('#retfair-banner'), retAfterPub.json.rows[5]);
    await page.click('.modal .mfoot .btn:not(.primary)');
    await tab(page, 'ret');
    await waitCell(page, 'Forward!W38', "t.trim() === '" + new1M[0] + "%'");
    const w38 = (await cellText(page, 'Forward!W38')).trim();
    await open(page, 'masa');
    await page.waitForFunction((v) => { const td = window.tto.findCell('MASA!D10'); return td && Math.abs(Number(td.textContent.replace('%', '').replace(',', '.')) - v) < 1e-6; },
      trNumber(new1M[0]), { timeout: 20000 }).catch(() => null);
    const d10 = await cellText(page, 'MASA!D10');
    check('the RET tables follow: the Forward sheet\'s RET and Masa\'s ORANLAR "RET bid"',
      w38 === new1M[0] + '%' && d10 !== null && Math.abs(trNumber(d10) - trNumber(new1M[0])) < 1e-6, [w38, d10, new1M]);
    // a large forward of the desk: a flow suggestion, accepted as a flow adjustment, removed with one click
    const bigFwd = await api(page, 'ayşe yilmaz', 'POST', '/api/blotter/forward', { dir: 'B', amount: '400m', value_date: '1M', basis: 'RET_BID' });
    check('a large forward is entered (400 mn USD, 1M, TRY sold)', bigFwd.status === 200, bigFwd.json);
    await page.click('#btn-ret');
    await page.waitForSelector('#retfair-table tbody tr[data-tenor="2Y"]');            // (the dialog opens on the tab used last)
    await page.waitForSelector('#retfair-suggestions .retfair-sugg[data-id="1M:+"] button.retfair-accept:not([disabled])', { timeout: 30000 });
    const suggText = await page.textContent('#retfair-suggestions .retfair-sugg[data-id="1M:+"] .txt');
    check('a flow suggestion in desk words, the tenor with its neighbour: "1M\'de bugün net … TRY sattık … → öneri 1M … 2M ask +…"',
      /^1M'de bugün net [\d,]+ mn USD TRY sattık \(.*\), ortalama \d+,\d\d ile; RET bid \d+,\d\d .* → öneri (1M \/ 2M ask \+\d+ bp|1M ask \+\d+ bp, 2M ask \+\d+ bp)$/.test(suggText), suggText);
    const before1M = await fairRow('1M');
    await page.click('#retfair-suggestions .retfair-sugg[data-id="1M:+"] button.retfair-accept');
    await page.waitForFunction(() => /\(akış\)/.test(document.querySelector('td.retfair-formula[data-tenor="1M"]').textContent), null, { timeout: 20000 });
    const after1M = await fairRow('1M');
    check('accepted: a flow adjustment shown apart ("+ N (akış)"), Şimdiki up, the offset untouched',
      / \+ \d+ \(akış\)$/.test(after1M.formula) && after1M.off === before1M.off && sideOf(after1M.now, 0) > sideOf(before1M.now, 0)
      && /\(akış\)/.test((await fairRow('2M')).formula) && await page.locator('#retfair-suggestions .retfair-sugg[data-id="1M:+"]').count() === 0, [before1M, after1M]);
    await page.click('button.retfair-flow-x[data-tenor="1M"]');
    await page.waitForFunction(() => !/\(akış\)/.test(document.querySelector('td.retfair-formula[data-tenor="1M"]').textContent), null, { timeout: 20000 });
    check('... removed with one click (2M keeps its own until it is removed too)', /\(akış\)/.test((await fairRow('2M')).formula)
      && (await fairRow('1M')).now === before1M.now, await fairRow('1M'));
    await page.click('button.retfair-flow-x[data-tenor="2M"]');
    await page.waitForFunction(() => !/\(akış\)/.test(document.querySelector('td.retfair-formula[data-tenor="2M"]').textContent), null, { timeout: 20000 });
    await page.click('.modal .mfoot .btn:not(.primary)');
    // a user who is no administrator: "Ekstra ayarlar" read-only, refused by the server too
    const ctxF = await browser.newContext({ viewport: { width: 1400, height: 900 } });
    const pageF = await ctxF.newPage();
    pageF.on('pageerror', (e) => errors.push('pageerror(F): ' + e.message));
    await login(pageF, 'Mehmet');
    await pageF.click('#btn-ret');
    await pageF.waitForSelector('#ret-tab-fair');
    await pageF.click('#ret-tab-fair');
    await pageF.waitForFunction(() => { const b = document.getElementById('retfair-admin-save'); return b && b.disabled && document.querySelector('.retfair-width'); }, null, { timeout: 20000 });
    const denied = await api(pageF, 'mehmet', 'POST', '/api/ret/fair/settings', { hysteresis: 3 });
    check('a user who is no administrator sees "Ekstra ayarlar" read-only and cannot change them',
      await pageF.isDisabled('#retfair-hyst') && await pageF.isDisabled('.retfair-width') && denied.status === 403, denied);
    await ctxF.close();
    // Günlük İşlemler: "Pozisyon ve maliyet" per RET tenor, the same aggregation as the suggestions
    await open(page, 'blotter');
    await page.waitForFunction(() => /1M/.test((document.querySelector('#blotter-position .body') || {}).textContent || ''), null, { timeout: 30000 });
    const posText = await page.textContent('#blotter-position');
    check('Günlük İşlemler shows "Pozisyon ve maliyet": the 1M tenor with its net TRY sold, cost and P&L against RET / OIS mid',
      /Pozisyon ve maliyet/.test(posText) && /K\/Z RET mid/.test(posText) && /Toplam/.test(posText) && /Broker Chat/.test(posText), posText.slice(0, 300));

    // ------------------------------------------------------------------ Trades: the desk's and each trader's own
    console.log('trades');
    const tradeDay = (d) => String(d.getDate()).padStart(2, '0') + '.' + String(d.getMonth() + 1).padStart(2, '0') + '.' + d.getFullYear();
    const tradesToday = tradeDay(new Date());
    await open(page, 'trades');
    await page.click('#trades-scope button[data-scope="desk"]');
    await page.waitForSelector('#trades-scope button.on[data-scope="desk"]');
    await page.click('#trades-new');
    await page.waitForSelector('#trade-form #tf-trade_date');
    await page.waitForFunction(() => document.getElementById('tf-trade_date').value !== '', null, { timeout: 15000 });
    // (the valuation's default: today - the day of the workbook's data in replay mode once the real valuation is in)
    const formDate = await page.inputValue('#tf-trade_date');
    check('Trades: "+ Yeni işlem" opens with the trade date filled (the valuation\'s default) and every product to pick',
      /^\d{2}\.\d{2}\.\d{4}$/.test(formDate) && await page.locator('#tf-product button').count() === 5, formDate);
    // a desk OIS: a DV01 typed gives the nominal rounded to 5 mn and the DV01 it actually gives; a nominal typed afterwards wins
    await page.click('#tf-product button[data-v="ois"]');
    await page.click('#tf-structure button[data-v="outright"]');
    await page.click('#tf-side button[data-v="receive"]');
    await page.fill('#tf-settle_date', '+1');
    await page.fill('#tf-end_date', '2Y');
    await page.fill('#tf-price', '38,50');
    await page.fill('#tf-dv01', '1.012');
    await page.waitForFunction(() => /^\d+m$/.test(document.getElementById('tf-notional').value), null, { timeout: 15000 });
    const dvNominal = await page.inputValue('#tf-notional');
    await page.waitForFunction(() => /DV01 ≈/.test(document.getElementById('tf-dv01-echo').textContent), null, { timeout: 15000 });
    const dvEcho = await page.textContent('#tf-dv01-echo');
    check('... a DV01 of 1.012 $ gives a nominal on the desk\'s 5 mn lot and says the DV01 that nominal gives',
      Number(dvNominal.slice(0, -1)) % 5 === 0 && /DV01 ≈ [\d.]+ \$/.test(dvEcho), { dvNominal, dvEcho });
    await page.fill('#tf-notional', '100m');
    await page.waitForFunction(() => { const d = document.getElementById('tf-dv01'); return d.classList.contains('info') && /^[\d.]+$/.test(d.value) && d.value !== '1.012'; },
      null, { timeout: 15000 });
    await page.waitForFunction(() => /RECEIVE 2Y TRY OIS 100m @ %38,50/.test((document.getElementById('tf-text') || {}).textContent || ''), null, { timeout: 15000 });
    check('... a nominal typed after it stays; the DV01 box shows its DV01 as information only; the server says the trade in the desk\'s words',
      await page.inputValue('#tf-notional') === '100m' && /^[\d.]+$/.test(await page.inputValue('#tf-dv01')));
    // the structures: a spread shows its two legs, a fly three, an MPC trade the meetings of the calendar by date
    await page.click('#tf-structure button[data-v="spread"]');
    await page.waitForSelector('#tf-legs tr[data-leg="1"]');
    const spreadLegs = await page.locator('#tf-legs tr[data-leg]').count();
    await page.click('#tf-structure button[data-v="fly"]');
    await page.waitForSelector('#tf-legs tr[data-leg="2"]');
    const flyLegs = await page.locator('#tf-legs tr[data-leg]').count();
    await page.click('#tf-structure button[data-v="mpc"]');
    await page.waitForFunction(() => document.querySelectorAll('#tf-meeting option').length > 2, null, { timeout: 15000 });
    const meetingOpts = await page.evaluate(() => [...document.querySelectorAll('#tf-meeting option')].slice(1, 3).map((o) => o.value + '|' + o.textContent));
    check('... spread: two legs, fly: three, PPK: the meetings ahead by their dates ("PPK dd.mm.yyyy")',
      spreadLegs === 2 && flyLegs === 3 && meetingOpts.every((x) => /^\d{4}-\d{2}-\d{2}\|PPK \d{2}\.\d{2}\.\d{4}/.test(x)), { spreadLegs, flyLegs, meetingOpts });
    await page.click('#tf-structure button[data-v="outright"]');
    await page.waitForFunction(() => /RECEIVE 2Y TRY OIS 100m @ %38,50/.test((document.getElementById('tf-text') || {}).textContent || ''), null, { timeout: 15000 });
    // its target and stop, in its own quote (a rate: %): a receive's target below its stop
    const levelLabels = await page.evaluate(() => ['tf-target', 'tf-stop'].map((id) => document.getElementById(id).closest('.field').querySelector('label').textContent));
    await page.fill('#tf-target', '30');
    await page.fill('#tf-stop', '20');
    await page.waitForFunction(() => /kâr tarafında/.test((document.querySelector('[data-for="target"]') || {}).textContent || ''), null, { timeout: 15000 });
    const wrongSide = await page.textContent('[data-for="target"]');
    await page.fill('#tf-stop', '45');
    await page.waitForFunction(() => !((document.querySelector('[data-for="target"]') || {}).textContent || ''), null, { timeout: 15000 });
    check('... its target and stop in its own quote ("Hedef (%)" / "Stop (%)"); a target on the losing side is refused under the box',
      levelLabels[0] === 'Hedef (%)' && levelLabels[1] === 'Stop (%)' && /hedef stopun kâr tarafında olmalı/.test(wrongSide), { levelLabels, wrongSide });
    await page.click('#tf-save');
    await page.waitForSelector('#trades-open tr.trade', { timeout: 15000 });
    const deskTrade = await page.evaluate(() => {
      const tr = document.querySelector('#trades-open tr.trade');
      return { id: tr.dataset.id, text: tr.textContent, edit: !!tr.querySelector('.act-edit') };
    });
    check('... saved: the desk\'s list shows it in the desk\'s words, its trade date and price; its creator may change it',
      /RECEIVE 2Y TRY OIS 100m @ %38,50/.test(deskTrade.text) && deskTrade.text.includes(formDate) && deskTrade.edit, deskTrade);
    // the row: what is left to its target and its stop (bp), valued as it was saved; İzleme: the desk's two alarms, for everyone
    await page.waitForFunction((id) => /H %30,00 · [\d.,]+ bp/.test((document.querySelector('#trades-open tr[data-id="' + id + '"] td.lv') || {}).textContent || ''),
      deskTrade.id, { timeout: 20000 }).catch(() => null);
    const lvCell = await page.textContent('#trades-open tr[data-id="' + deskTrade.id + '"] td.lv');
    const listedLv = ((await api(page, 'ayşe yilmaz', 'GET', '/api/trades?scope=desk')).json.open.find((t) => String(t.id) === deskTrade.id) || {}).levels || {};
    const deskAlarms = (((await api(page, 'ayşe yilmaz', 'GET', '/api/watch')).json || {}).desk || {}).alarms || [];
    const mine = deskAlarms.filter((a) => a.trade && String(a.trade.id) === deskTrade.id);
    check('... its row shows the distance to the target and the stop in bp; the listing carries levels {target, stop, unit, to_target, to_stop, near}; '
      + 'İzleme has the desk\'s "hedefe geldi" / "stopa geldi" alarms on it',
      /H %30,00 · [\d.,]+ bp/.test(lvCell) && /S %45,00 · [\d.,]+ bp/.test(lvCell) && listedLv.target === 30 && listedLv.stop === 45 && listedLv.unit === 'bp'
      && typeof listedLv.to_target === 'number' && 'near' in listedLv && mine.length === 2 && mine.some((a) => a.note === 'hedefe geldi' && a.condition.startsWith('≤'))
      && mine.some((a) => a.note === 'stopa geldi' && a.condition.startsWith('≥')), { lvCell, listedLv, mine: mine.map((a) => [a.label, a.condition, a.note]) });
    // a personal FX spot: what is typed survives a change of the pair; a box emptied gets its default again
    await page.click('#trades-scope button[data-scope="personal"]');
    await page.waitForSelector('#trades-scope button.on[data-scope="personal"]');
    await page.click('#trades-new');
    await page.waitForSelector('#trade-form #tf-trade_date');
    await page.click('#tf-product button[data-v="fxspot"]');
    await page.waitForSelector('#tf-pair');
    const yesterday = tradeDay(new Date(Date.now() - 86400000));
    await page.fill('#tf-trade_date', yesterday);
    await page.fill('#tf-pair', 'EURTRY');
    await page.waitForFunction(() => document.getElementById('tf-notional').closest('.field').textContent.includes('EUR'), null, { timeout: 15000 });
    await page.fill('#tf-pair', 'USDTRY');
    await page.waitForFunction(() => document.getElementById('tf-notional').closest('.field').textContent.includes('USD'), null, { timeout: 15000 });
    await page.waitForTimeout(1200);                          // (the defaults asked again for the new pair)
    const keptDate = await page.inputValue('#tf-trade_date');
    await page.fill('#tf-trade_date', '');
    await page.waitForFunction(() => /^\d{2}\.\d{2}\.\d{4}$/.test(document.getElementById('tf-trade_date').value), null, { timeout: 15000 });
    check('... the pair changed twice: the trade date typed stays; emptied, it is filled again with the default',
      keptDate === yesterday, { keptDate, yesterday });
    await page.click('#tf-side button[data-v="B"]');
    await page.fill('#tf-settle_date', '+1');
    await page.fill('#tf-notional', '10m');
    await page.fill('#tf-price', '42,15');
    await page.waitForFunction(() => /ALIŞ USDTRY 10m USD @ 42,1500/.test((document.getElementById('tf-text') || {}).textContent || ''), null, { timeout: 15000 });
    await page.click('#tf-save');
    await page.waitForFunction(() => /ALIŞ USDTRY 10m USD/.test(document.getElementById('trades-open').textContent), null, { timeout: 15000 });
    const ownId = await page.evaluate(() => document.querySelector('#trades-open tr.trade').dataset.id);
    // a second user: the desk's trade, not Ayşe's own - on the page, through the API, in the log
    const ctxT = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
    const pageT = await ctxT.newPage();
    pageT.on('pageerror', (e) => errors.push('pageerror(T): ' + e.message));
    await login(pageT, 'Mehmet');
    await open(pageT, 'trades');
    await pageT.click('#trades-scope button[data-scope="desk"]');
    await pageT.waitForFunction((id) => !!document.querySelector('#trades-open tr[data-id="' + id + '"]'), deskTrade.id, { timeout: 15000 });
    const seenByMehmet = await pageT.evaluate((id) => {
      const tr = document.querySelector('#trades-open tr[data-id="' + id + '"]');
      return { text: tr.textContent, edit: !!tr.querySelector('.act-edit'), del: !!tr.querySelector('.act-del') };
    }, deskTrade.id);
    await pageT.click('#trades-scope button[data-scope="personal"]');
    await pageT.waitForSelector('#trades-scope button.on[data-scope="personal"]');
    await pageT.waitForTimeout(500);
    const mehmetOwn = await pageT.textContent('#trades-open');
    const viaApi = await api(pageT, 'mehmet', 'GET', '/api/trades?scope=personal');
    const logApi = await api(pageT, 'mehmet', 'GET', '/api/trades/' + ownId + '/log');
    const recentApi = await api(pageT, 'mehmet', 'GET', '/api/trades/log?scope=personal');
    check('... another user sees the desk\'s trade (not to change: neither Düzenle nor Sil), never Ayşe\'s own - not on the page, not through the API, not in the log',
      /RECEIVE 2Y TRY OIS 100m/.test(seenByMehmet.text) && !seenByMehmet.edit && !seenByMehmet.del && !/USDTRY/.test(mehmetOwn)
      && viaApi.status === 200 && !viaApi.json.open.some((t) => String(t.id) === ownId) && logApi.status === 404
      && !recentApi.json.entries.some((e) => String(e.trade) === ownId), { seenByMehmet, mehmetOwn, log: logApi.status });
    // a desk trade entered by Mehmet comes to Ayşe's open page by itself (the live stream's counter, no new generation)
    await page.click('#trades-scope button[data-scope="desk"]');
    await page.waitForSelector('#trades-scope button.on[data-scope="desk"]');
    const mehmetAdd = await api(pageT, 'mehmet', 'POST', '/api/trades', { scope: 'desk', product: 'sofr', structure: 'outright', trade_date: tradesToday,
      settle_date: '+2', side: 'pay', end_date: '5Y', notional: '25m', price: '3,85' });
    await page.waitForFunction(() => /PAY 5Y SOFR 25m @ %3,85/.test(document.getElementById('trades-open').textContent), null, { timeout: 20000 });
    check('... a desk trade entered by another user shows on the open page at once', mehmetAdd.status === 200, mehmetAdd);
    await ctxT.close();
    // "MTM yenile": nothing is valued before it; then the time, and per trade its value or the reason it has none
    const mtmBefore = await page.textContent('#trades-mtm-at');
    await page.click('#trades-mtm');
    await page.waitForFunction(() => /son yenileme: \d\d:\d\d/.test(document.getElementById('trades-mtm-at').textContent), null, { timeout: 30000 });
    const valued = await page.evaluate(() => [...document.querySelectorAll('#trades-open tr.trade')].map((tr) => {
      const cells = [...tr.cells];
      return { number: cells.some((c) => /^[+-]?\d{1,3}(\.\d{3})*( [A-Z]{3})?$/.test(c.textContent.trim()) && !c.classList.contains('acts')),
        why: (tr.querySelector('td.why') || { textContent: '' }).textContent };
    }));
    const totals = await page.textContent('#trades-totals');
    check('... "MTM yenile": "son yenileme: hh:mm", and each trade shows its value or why it has none; the totals in TL and USD',
      /henüz değerlenmedi/.test(mtmBefore) && valued.length === 2 && valued.every((v) => v.number || v.why.length > 3) && /Toplam/.test(totals)
      && /MTM TL/.test(totals) && /Gerçekleşen USD/.test(totals), { mtmBefore, valued });
    // "Biriken" (a swap's period under way so far) and "Carry (1g)" (a day more, the market unchanged) beside the MTM;
    // "Fonlama" only with an FX spot or a bond
    const cols = await page.evaluate(() => ({ running: !!document.getElementById('trades-running-col'), carry: !!document.getElementById('trades-carry-col'),
      funding: !!document.getElementById('trades-funding-col'),
      carries: [...document.querySelectorAll('#trades-open tr.trade td.c1d')].map((td) => td.textContent.trim()) }));
    check('... "Biriken" and "Carry (1g)" beside the MTM; no "Fonlama" without an FX spot or a bond',
      cols.running && cols.carry && !cols.funding && cols.carries.length === 2 && cols.carries.some((x) => /^[+-]?\d/.test(x)), cols);
    // "DV01 · vade", as Günlük İşlemler's "OIS · vade özeti": the RECEIVE 2Y TRY OIS 100m in 2Y's receive (net −), the
    // PAY 5Y SOFR in SOFR's 5Y pay (net +); the bar with TRY and SOFR apart
    const ladder = await page.evaluate(() => {
      const row = (id, tenor) => { const tr = document.querySelector('#' + id + ' tr[data-tenor="' + tenor + '"]'); return tr ? [...tr.cells].map((c) => c.textContent.trim()) : null; };
      return { bar: (document.getElementById('trades-dv01-bar') || {}).textContent || '', try2y: row('trades-dv01-try', '2Y'), usd5y: row('trades-dv01-usd', '5Y'),
        tenors: [...document.querySelectorAll('#trades-dv01-try tr[data-tenor]')].map((tr) => tr.dataset.tenor) };
    });
    check('... "DV01 · vade" as Günlük İşlemler\'s "OIS · vade özeti": RECEIVE 2Y 100m in 2Y\'s receive (net −), PAY 5Y SOFR in SOFR\'s 5Y pay; the bar, TRY and SOFR apart',
      /DV01 · TRY faizi \+1 bp/.test(ladder.bar) && /SOFR/.test(ladder.bar) && !!ladder.try2y && /^-\d/.test(ladder.try2y[0]) && ladder.try2y[5] === '100.000.000'
      && /^\d/.test(ladder.try2y[7]) && ladder.try2y[7] !== '0' && !!ladder.usd5y && /^\+\d/.test(ladder.usd5y[0]) && /^\d/.test(ladder.usd5y[4])
      && ladder.usd5y[4] !== '0' && ladder.tenors[0] === 'ON' && ladder.tenors.includes('5Y') && ladder.tenors[ladder.tenors.length - 1] === 'Toplam', ladder);
    // the personal FX spot: its roll is its funding, in its K/Z beside the MTM (the desk, 19.11.2026: spot K/Z = price move + carry)
    const ownMtm = await api(page, 'ayşe yilmaz', 'POST', '/api/trades/mtm', { scope: 'personal' });
    const ownVal = (((ownMtm.json || {}).values) || {})[ownId] || {};
    const ownPer = ownVal.periods || {};
    check('... a personal FX spot\'s roll is its funding ("Fonlama"): MTM + Fonlama = its total K/Z, whose carry is the funding',
      ownMtm.status === 200 && ownVal.ok && ownVal.funding_1d === ownVal.carry_1d && ownVal.funding_1d < 0 && !!ownPer.funding && ownPer.funding.ccy < 0
      && Math.abs(ownPer.total.pnl.ccy - (ownVal.mtm + ownPer.funding.ccy)) < 1 && Math.abs(ownPer.total.carry.ccy - ownPer.funding.ccy) < 1,
      { status: ownMtm.status, ok: ownVal.ok, why: ownVal.why, mtm: ownVal.mtm, f: ownVal.funding_1d, c: ownVal.carry_1d, funding: ownPer.funding,
        total: ownPer.total });
    // "Kupon" beside the MTM; a swap's opens "Kuponlar": the SOFR 5Y dealt today - five yearly periods ahead, paid two SIFMA
    // days after their ends, nothing realised yet
    const sofrRow = await page.evaluate(() => ([...document.querySelectorAll('#trades-open tr.trade')].find((x) => /PAY 5Y SOFR 25m/.test(x.textContent)) || {}).dataset.id);
    await page.click('#trades-open tr[data-id="' + sofrRow + '"] .act-coupons');
    await page.waitForSelector('#trades-coupons-0', { timeout: 30000 });
    const cpn = await page.evaluate(() => ({ head: !!document.getElementById('trades-coupon-col'),
      states: [...document.querySelectorAll('#trades-coupons-0 tr[data-state]')].map((tr) => tr.dataset.state),
      text: document.getElementById('trades-coupons').textContent }));
    await page.keyboard.press('Escape');
    check('... "Kupon" beside the MTM; a swap\'s opens "Kuponlar": the SOFR 5Y\'s five yearly periods ahead (paid 2 SIFMA days on), nothing realised',
      cpn.head && cpn.states.length === 5 && cpn.states.every((s) => s === 'future') && /2 iş günü sonra \(SIFMA\)/.test(cpn.text)
      && /Gerçekleşen/.test(cpn.text), cpn);
    // a spread is one line with its package level; ▸ shows each leg; "Bacaklar ayrı satır" lists the legs as rows of their own
    const tradeSpread = await api(page, 'ayşe yilmaz', 'POST', '/api/trades', { scope: 'desk', product: 'ois', structure: 'spread', trade_date: tradesToday,
      settle_date: '+1', side: 'steepener', legs: [{ side: 'receive', end_date: '2Y', notional: '100m', price: '38,50' },
        { side: 'pay', end_date: '5Y', notional: '45m', price: '38,15' }] });
    const spreadSel = '#trades-open tr.trade[data-id="' + (tradeSpread.json && tradeSpread.json.id) + '"]';
    await page.waitForSelector(spreadSel, { timeout: 20000 });
    const spreadLine = await page.textContent(spreadSel);
    await page.click(spreadSel + ' td.exp button');
    await page.waitForFunction(() => document.querySelectorAll('#trades-open tr.leg').length === 2, null, { timeout: 10000 });
    const legLines = await page.evaluate(() => [...document.querySelectorAll('#trades-open tr.leg')].map((tr) => tr.textContent.trim()));
    await page.check('#trades-legrows');
    await page.waitForFunction((id) => document.querySelectorAll('#trades-open tr.legrow[data-id="' + id + '"]').length === 2, String(tradeSpread.json.id), { timeout: 10000 });
    const spreadLegRows = await page.evaluate((id) => [...document.querySelectorAll('#trades-open tr.legrow[data-id="' + id + '"]')].map((tr) => tr.cells[2].textContent), String(tradeSpread.json.id));
    await page.uncheck('#trades-legrows');
    check('... a spread: one line "2s5s steepener TRY OIS -35,0 bp"; ▸ shows its two legs; "Bacaklar ayrı satır" lists them as rows of their own',
      /2s5s steepener TRY OIS -35,0 bp/.test(spreadLine) && legLines.length === 2 && /RECEIVE 2Y 100m @ %38,50/.test(legLines[0])
      && /PAY 5Y 45m @ %38,15/.test(legLines[1]) && spreadLegRows.length === 2 && /^RECEIVE 2Y 100m/.test(spreadLegRows[0]) && /^PAY 5Y 45m/.test(spreadLegRows[1]),
      { spreadLine, legLines, spreadLegRows });
    // close the OIS: it goes to the closed list with its close date and price; its log says who did what
    await page.click('#trades-open tr[data-id="' + deskTrade.id + '"] .act-close');
    await page.waitForSelector('#tc-price');
    await page.fill('#tc-price', '38,20');
    await page.click('#tc-save');
    await page.waitForFunction((id) => !document.querySelector('#trades-open tr[data-id="' + id + '"]')
      && !!document.querySelector('#trades-closed tr[data-id="' + id + '"]'), deskTrade.id, { timeout: 15000 });
    const closedRow = await page.textContent('#trades-closed tr[data-id="' + deskTrade.id + '"]');
    await page.click('#trades-closed tr[data-id="' + deskTrade.id + '"] .act-log');
    await page.waitForSelector('#trades-log-table');
    const logText = await page.textContent('#trades-log-table');
    await page.keyboard.press('Escape');
    check('... closed at 38,20: it leaves the open list for the closed one with its close date and price; its log: entered, closed - by whom',
      closedRow.includes(tradesToday + ' · %38,20') && /girdi/.test(logText) && /kapattı/.test(logText) && /Ayşe Yılmaz/.test(logText),
      { closedRow, logText });
    const goneAlarms = ((((await api(page, 'ayşe yilmaz', 'GET', '/api/watch')).json || {}).desk || {}).alarms || []).filter((a) => a.trade && String(a.trade.id) === deskTrade.id);
    check('... closed: its alarms are gone from İzleme', goneAlarms.length === 0, goneAlarms);
    // "İşleme al": the form a quant line opens (the server's answer: a receive 2Y at the line's entry, its DV01 as a nominal on
    // the desk's 5 mn lot, the line's target and stop) - personal by default, nothing saved until "İşlemi kaydet"
    const fromDefaults = (await api(page, 'ayşe yilmaz', 'GET', '/api/trades/defaults?product=ois&structure=outright')).json;
    await page.evaluate(async (d) => {
      const tr = await import('/static/js/pages/trades.js');
      tr.openTradeForm({ ok: true, scope: 'personal', kind: 'outright', text: '', line: { id: 'trend:OIS:2Y', family: 'trend', family_label: 'Trend', text: 'receive 2Y OIS · 1.000 $ DV01' },
        source: { kind: 'quant', family: 'trend', family_label: 'Trend', line_id: 'trend:OIS:2Y', at: d.trade_date + ' 10:00', instrument: '2Y OIS', entry: 37.65, target: 37.25, stop: 37.85, unit: '%' },
        trade: { product: 'ois', structure: 'outright', trade_date: d.trade_date, settle_date: d.settle_date, value_date: d.value_date || d.settle_date, side: 'S', tenor: '2Y',
          notional: 360e6, notional_ccy: 'TRY', sized_by: 'dv01', dv01: 1000, dv01_ccy: 'USD', price: 37.65, target: 37.25, stop: 37.85 } });
    }, fromDefaults);
    await page.waitForSelector('#trade-form #tf-from');
    await page.waitForFunction(() => /RECEIVE 2Y TRY OIS 360m @ %37,65/.test((document.getElementById('tf-text') || {}).textContent || ''), null, { timeout: 15000 });
    const filled = await page.evaluate(() => ({ title: document.querySelector('#trade-form header h2').textContent, scope: document.querySelector('#tf-scope button.on').dataset.v,
      side: document.querySelector('#tf-side button.on').dataset.v, end: document.getElementById('tf-end_date').value, notional: document.getElementById('tf-notional').value,
      dv01: document.getElementById('tf-dv01').value, price: document.getElementById('tf-price').value, target: document.getElementById('tf-target').value,
      stop: document.getElementById('tf-stop').value }));
    check('"İşleme al" opens the Trades form filled from the line: personal, RECEIVE 2Y, the DV01 and its nominal, the entry, the target and the stop',
      / sinyalinden$/.test(filled.title) && filled.scope === 'personal' && filled.side === 'receive' && filled.end === '2Y' && filled.notional === '360m'
      && filled.dv01 === '1k' && filled.price === '37,65' && filled.target === '37,25' && filled.stop === '37,85', filled);
    await page.click('#tf-save');
    await page.click('#trades-scope button[data-scope="personal"]');
    await page.waitForSelector('#trades-scope button.on[data-scope="personal"]');
    await page.waitForFunction(() => /RECEIVE 2Y TRY OIS 360m/.test(document.getElementById('trades-open').textContent), null, { timeout: 15000 });
    const quantRow = await page.evaluate(() => {
      const tr = [...document.querySelectorAll('#trades-open tr.trade')].find((x) => /RECEIVE 2Y TRY OIS 360m/.test(x.textContent));
      return { id: tr.dataset.id, src: (tr.querySelector('.tsrc') || {}).textContent || '', lv: (tr.querySelector('td.lv') || {}).textContent || '' };
    });
    const quantApi = (await api(page, 'ayşe yilmaz', 'GET', '/api/trades?scope=personal')).json.open.find((t) => String(t.id) === quantRow.id) || {};
    check('... saved: the trade remembers its line (Quant · Trend) and has its levels', /Quant · Trend · 2Y OIS/.test(quantRow.src) && /H %37,25/.test(quantRow.lv)
      && quantApi.source && quantApi.source.line_id === 'trend:OIS:2Y' && quantApi.source.family === 'trend', { quantRow, source: quantApi.source });
    // "Quant'tan": only the trades taken from a line, and per family what they made (the desk's and one's own)
    await page.click('#trades-quant');
    await page.waitForFunction(() => /Trend/.test((document.getElementById('trades-quant-table') || {}).textContent || ''), null, { timeout: 15000 });
    const quantView = await page.evaluate(() => ({ rows: [...document.querySelectorAll('#trades-open tr.trade')].length,
      fam: (document.querySelector('#trades-quant-table tr[data-family="trend"]') || {}).textContent || '' }));
    await page.click('#trades-quant');
    await page.waitForFunction(() => document.querySelectorAll('#trades-open tr.trade').length > 1, null, { timeout: 15000 });
    check('... "Quant\'tan": the list keeps only the trades taken from a line; its table per family: count (desk / own), open, closed, P&L, hits',
      quantView.rows === 1 && /^Trend1 \(0 \/ 1\)10/.test(quantView.fam), quantView);
    await shot(page, 'trades');

    // ------------------------------------------------------------------ Prop: the top bar's calculator and prop risk
    console.log('prop');
    const propOn = {};
    for (const id of ['masa', 'ois']) {
      await open(page, id);
      propOn[id] = await page.evaluate(() => { const b = document.getElementById('prop-btn'); return !!b && b.offsetParent !== null && b.textContent === 'Prop'; });
    }
    check('Prop: the "Prop" button is in the top bar on every page (Masa, OIS · PPK)', propOn.masa && propOn.ois, propOn);
    // the desk's worked example: USDTRY, entry 44,35, stop 44,55, a loss of 500k TL -> SHORT, 2M USD, a real loss of 400.000 TL
    await page.click('#prop-btn');
    await page.waitForSelector('#prop-panel:not(.hidden)');
    await page.waitForFunction(() => document.querySelectorAll('#prop-pairs option').length > 0, null, { timeout: 20000 });
    await page.fill('#prop-pair', 'usdtry');
    await page.fill('#prop-entry', '44,35');
    await page.fill('#prop-stop', '44,55');
    await page.fill('#prop-loss', '500k');
    await page.waitForFunction(() => /2M USD/.test((document.getElementById('prop-size') || {}).textContent || ''), null, { timeout: 20000 }).catch(() => null);
    const propCalc = await page.evaluate(() => ({ dir: (document.getElementById('prop-dir') || {}).textContent || '',
      size: (document.getElementById('prop-size') || {}).textContent || '', real: (document.getElementById('prop-real') || {}).textContent || '',
      per: (document.getElementById('prop-per1m') || {}).textContent || '', mid: document.getElementById('prop-mid').textContent,
      pairs: [...document.querySelectorAll('#prop-pairs option')].map((o) => o.value) }));
    check('... USDTRY 44,35 → stop 44,55, 500k TL: SHORT, 2M USD (2,50M rounded down), a real loss of 400.000 TRY, 200.000 TRY a million; the live mid beside the entry',
      /^SHORT · SAT/.test(propCalc.dir) && /mesafe 0,2000/.test(propCalc.dir) && /Büyüklük 2M USD \(ham 2,50M/.test(propCalc.size)
      && /Gerçek kayıp 400\.000 TRY/.test(propCalc.real) && /1M başına 200\.000 TRY/.test(propCalc.per) && /^canlı \d/.test(propCalc.mid)
      && propCalc.pairs[0] === 'USDTRY', propCalc);
    // a stop on the entry: the reason, under the inputs
    await page.fill('#prop-stop', '44,35');
    await page.waitForFunction(() => /stop girişe eşit olamaz/.test(document.getElementById('prop-err').textContent), null, { timeout: 20000 }).catch(() => null);
    const propErr = await page.textContent('#prop-err');
    check('... a stop on the entry is refused with the reason (the direction comes from the stop)', /stop girişe eşit olamaz/.test(propErr), propErr);
    await page.fill('#prop-stop', '44,55');
    await page.waitForFunction(() => /2M USD/.test((document.getElementById('prop-size') || {}).textContent || ''), null, { timeout: 20000 }).catch(() => null);
    // the risk of one's own tab: today's K/Z from "MTM yenile", a limit, the room left = limit − today's loss − the stops.
    // (The tab's two trades are dated the replay's day and were entered after today's close, if one was taken: their
    // "Günlük" is unknown, as the Trades page shows it - a USDTRY short dealt today has its own, from its inception.)
    const propShort = await api(page, 'ayşe yilmaz', 'POST', '/api/trades', { scope: 'personal', product: 'fxspot', pair: 'USDTRY',
      trade_date: tradesToday, settle_date: '+1', side: 'S', notional: '2m', price: '50,00', stop: '50,60' });
    await page.click('#prop-scope button[data-v="personal"]');
    await page.waitForSelector('#prop-mtm', { timeout: 20000 });
    await page.click('#prop-mtm');
    await page.waitForFunction(() => /son MTM yenilemesi \d\d:\d\d/.test(document.getElementById('prop-pnl-note').textContent), null, { timeout: 30000 }).catch(() => null);
    const noLimitLine = await page.textContent('#prop-line');
    await page.fill('#prop-limit', '50mn');
    await page.selectOption('#prop-limit-ccy', 'TRY');
    await page.click('#prop-limit-save');
    // (no limit: no "Kalan" - it comes with the limit saved)
    await page.waitForFunction(() => /^-?[\d.]+ TRY$/.test(((document.querySelector('#prop-room-v .v') || {}).textContent || '').trim()), null, { timeout: 20000 }).catch(() => null);
    const propRisk = (await api(page, 'ayşe yilmaz', 'GET', '/api/prop/risk?scope=personal')).json || {};
    const propShown = await page.evaluate(() => ({ line: document.getElementById('prop-line').textContent,
      room: ((document.querySelector('#prop-room-v .v') || {}).textContent || '').trim(), share: (document.getElementById('prop-share') || {}).textContent || '',
      stops: [...document.querySelectorAll('#prop-stops tr[data-state]')].map((tr) => tr.dataset.state + ' ' + tr.cells[0].textContent) }));
    const roomTry = propRisk.room ? propRisk.room.try : null;
    const expectRoom = propRisk.limit && propRisk.pnl && typeof propRisk.pnl.try === 'number'
      ? 50e6 - Math.max(0, -propRisk.pnl.try) - propRisk.stops.try : null;
    const pageDay = ((((await api(page, 'ayşe yilmaz', 'GET', '/api/trades?scope=personal')).json || {}).mtm || {}).totals || {}).all || {};
    const pageMissing = (pageDay.missing || {})['day.pnl.try'] || 0;
    check('... no limit: "Bugün K/Z · Stoplar" alone; a limit of 50mn TRY: "Limit · Bugün K/Z · Stoplar · Kalan", the room = limit − today\'s loss − the loss '
      + 'at the stops (the 2Y OIS\'s stop 37,85 and the short\'s 50,60); the K/Z is the Trades page\'s "Günlük" (its unknown ones said: *); the calculator '
      + 'says the share of the room the trade would use',
      propShort.status === 200 && /^Bugün K\/Z.*Stoplar/.test(noLimitLine) && !/Limit|Kalan/.test(noLimitLine) && /Limit50\.000\.000 TRY/.test(propShown.line) && /Bugün K\/Z[+-]?[\d.]+ TRY/.test(propShown.line)
      && /Stoplar[\d.]+ TRY/.test(propShown.line) && propRisk.pnl.try === pageDay['day.pnl.try'] && propRisk.pnl.missing === pageMissing
      && /TRY \*/.test(propShown.line) === pageMissing > 0 && propRisk.stops.count === 2
      && typeof roomTry === 'number' && Math.abs(roomTry - expectRoom) < 1 && Math.abs(trNumber(propShown.room.replace(' TRY', '')) - roomTry) <= 1
      && propShown.stops.some((s) => /^open RECEIVE 2Y TRY OIS 360m/.test(s)) && propShown.stops.some((s) => /^open SATIŞ USDTRY 2m/.test(s))
      && /kalan/.test(propShown.share), { propShort: propShort.status, noLimitLine, propShown, room: roomTry, expectRoom, pnl: propRisk.pnl,
        stops: propRisk.stops, pageDay: pageDay['day.pnl.try'], pageMissing });
    // Masa: the desk's tab, remembered by this browser; the limit is one's own - another user has none
    await page.click('#prop-scope button[data-v="desk"]');
    await page.waitForFunction(() => /Masa sekmesi|Masa sekmesinde/.test(document.getElementById('prop-panel').textContent), null, { timeout: 20000 }).catch(() => null);
    await page.keyboard.press('Escape');
    const propClosed = await page.evaluate(() => document.getElementById('prop-panel').classList.contains('hidden'));
    await page.click('#prop-btn');
    await page.waitForSelector('#prop-panel:not(.hidden)');
    const keptScope = await page.evaluate(() => ({ on: (document.querySelector('#prop-scope button.on') || {}).dataset, stored: localStorage.getItem('tto.prop.scope'),
      stop: document.getElementById('prop-stop').value }));
    const otherLimit = (await api(page, 'mehmet', 'GET', '/api/prop/limit')).json;
    check('... Esc closes it; it opens again on Masa (this browser remembers the tab) with what was typed; Mehmet has no limit (Ayşe\'s is her own)',
      propClosed && keptScope.on && keptScope.on.v === 'desk' && keptScope.stored === 'desk' && keptScope.stop === '44,55'
      && otherLimit && otherLimit.limit === null, { propClosed, keptScope, otherLimit });
    await page.click('#prop-scope button[data-v="personal"]');
    await page.keyboard.press('Escape');
    await shot(page, 'prop');

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

    // ------------------------------------------------------------------ Bugün (the morning screen) and Ctrl+K's commands
    console.log('Bugün and Ctrl+K commands');
    await open(page, 'bugun');
    await page.waitForSelector('#bugun-ret-state', { timeout: 30000 });
    const bgSeen = await page.evaluate(() => {
      const masa = [...document.querySelectorAll('#nav .nav-group')].find((g) => (g.querySelector('.gt') || {}).textContent === 'Masa');
      const has = (id) => !!document.getElementById(id);
      return { cards: [...document.querySelectorAll('#bugun .bugun-card')].map((c) => c.id),
        menu: masa ? [...masa.querySelectorAll('.nav-item')].slice(0, 2).map((a) => a.dataset.page) : [],
        ret: document.getElementById('bugun-ret-state').textContent,
        each: ['trades', 'quant', 'dibs', 'chat'].map((k) => has('bugun-' + k + '-table') || has('bugun-' + k + '-none')),
        agenda: has('bugun-agenda-items') || has('bugun-agenda-none'), errs: document.querySelectorAll('#bugun .err').length };
    });
    const bgStatus = (await api(page, 'ayşe yilmaz', 'GET', '/api/status')).json;
    const retToday = !!(bgStatus.ret && bgStatus.ret.updated_at && bgStatus.ret.updated_at.slice(0, 10) === bgStatus.server_date);
    check('Bugün: in the Masa group right under Masa; six blocks, each with its content or a plain "nothing"',
      bgSeen.menu.join() === 'masa,bugun' && bgSeen.cards.join() === 'bugun-ret,bugun-trades,bugun-quant,bugun-dibs,bugun-chat,bugun-agenda'
      && bgSeen.each.every(Boolean) && bgSeen.agenda && bgSeen.errs === 0, bgSeen);
    check('... the RET block says what the header\'s dot says (loaded today or not)', /^Bugün yüklendi/.test(bgSeen.ret) === retToday,
      { ret: bgSeen.ret, retToday });
    const bgRecon = (await api(page, 'ayşe yilmaz', 'GET', '/api/broker/recon')).json;
    const bgChat = await page.locator('#bugun-chat-table tr[data-line]').count();
    check('... "Girilmemiş işlemler": the "Girilmedi" lines of the chat ↔ Günlük İşlemler list', bgChat === Math.min(bgRecon.missing, 40),
      { rows: bgChat, missing: bgRecon.missing });
    // (the tab the page's own reading asked for: the fair value's summary is made again in the background meanwhile)
    const bgTab = await page.evaluate(() => window.tto.state.page.data.ret.tab);
    await page.click('#bugun-ret-go');
    await page.waitForSelector('.modal #ret-tab-fair');                // (its tabs: the manual table is hidden on the fair one)
    const bgFair = await page.evaluate(() => document.getElementById('ret-tab-fair').classList.contains('on'));
    check('... its RET button opens the RET dialog on the right tab (fair value when the fair value differs)',
      !bgTab || bgFair === (bgTab === 'fair'), { fair: bgFair, tab: bgTab });
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => !document.querySelector('.modal table.ret'));
    await shot(page, '90-bugun');
    // "Açılış sayfası yap": the dashboard opens on Bugün when no address is given
    await page.click('#bugun-make-landing');
    await savedLayout((l) => l.landing === 'bugun');
    await page.goto(BASE + '/');
    await page.waitForFunction(() => window.tto && window.tto.state.pageId === 'bugun' && window.tto.state.page && window.tto.state.page.ready,
      null, { timeout: 60000 }).catch(() => null);
    check('... "Açılış sayfası yap": the dashboard opens on Bugün without an address', await page.evaluate(() => window.location.hash) === '#/bugun'
      && /Açılış sayfanız/.test(await page.textContent('#bugun-landing')));
    await api(page, 'ayşe yilmaz', 'POST', '/api/layout', { landing: '' });
    // Ctrl+K "işlem gir usdtry 1m 10mn": first a command; Günlük İşlemler's form filled - the value date from the pair's
    // own spot, as the form reads a tenor -, nothing saved
    const blotterBefore = (await api(page, 'ayşe yilmaz', 'GET', '/api/blotter')).json.trades.length;
    await page.keyboard.press('Control+k');
    await page.keyboard.type('işlem gir usdtry 1m 10mn');
    await page.waitForSelector('.findlist .hit.cmd');
    const cmdFirst = await page.textContent('.findlist .hit >> nth=0');
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => window.tto.state.pageId === 'blotter' && window.tto.state.page && window.tto.state.page.ready, null, { timeout: 60000 });
    await page.waitForFunction(() => /→/.test((document.getElementById('fwd-date-echo') || {}).textContent || ''), null, { timeout: 30000 }).catch(() => null);
    const cmdFwd = await page.evaluate(() => ({ date: document.getElementById('fwd-date').value, amount: document.getElementById('fwd-amount').value,
      echo: document.getElementById('fwd-date-echo').textContent, pair: (document.querySelector('#fwd-pair button.on') || { dataset: {} }).dataset.v }));
    await page.waitForTimeout(400);
    const blotterAfter = (await api(page, 'ayşe yilmaz', 'GET', '/api/blotter')).json.trades.length;
    check('Ctrl+K "işlem gir usdtry 1m 10mn": the command first; Günlük İşlemler filled (USDTRY, 1M from its spot, 10mn) - not saved',
      /Günlük İşlemler: USDTRY · valör 1M · 10mn USD/.test(cmdFirst) && cmdFwd.pair === 'USDTRY' && cmdFwd.date === '1M'
      && cmdFwd.amount === '10mn' && /^1M → \d\d\.\d\d\.\d{4}$/.test(cmdFwd.echo) && blotterAfter === blotterBefore,
      { cmdFirst, cmdFwd, blotterBefore, blotterAfter });
    // Ctrl+K "ret yayınla": the RET dialog on the fair value tab - nothing published (that is the user's button)
    const retMetaBefore = (await api(page, 'ayşe yilmaz', 'GET', '/api/ret')).json.meta;
    await page.keyboard.press('Control+k');
    await page.keyboard.type('ret yayınla');
    await page.waitForSelector('.findlist .hit.cmd');
    await page.keyboard.press('Enter');
    await page.waitForSelector('#ret-pane-fair:not(.hidden)', { timeout: 30000 });
    const retFairTab = await page.evaluate(() => document.getElementById('ret-tab-fair').classList.contains('on'));
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => !document.querySelector('.modal table.ret'));
    const retMetaAfter = (await api(page, 'ayşe yilmaz', 'GET', '/api/ret')).json.meta;
    check('Ctrl+K "ret yayınla": the RET dialog on the fair value tab - nothing published', retFairTab
      && JSON.stringify(retMetaBefore) === JSON.stringify(retMetaAfter), { retFairTab, retMetaBefore, retMetaAfter });
    // Ctrl+K "trade ois 1y 5mn": the Trades form filled as the user would type it - not saved
    const tbBefore = (await api(page, 'ayşe yilmaz', 'GET', '/api/trades?scope=desk')).json.open.length;
    await page.keyboard.press('Control+k');
    await page.keyboard.type('trade ois 1y 5mn');
    await page.waitForSelector('.findlist .hit.cmd');
    await page.keyboard.press('Enter');
    await page.waitForFunction(() => { const n = document.getElementById('tf-notional'); return n && n.value === '5mn'; }, null, { timeout: 60000 }).catch(() => null);
    const tfFilled = await page.evaluate(() => ({ product: (document.querySelector('#tf-product button.on') || {}).textContent,
      end: (document.getElementById('tf-end_date') || {}).value, notional: (document.getElementById('tf-notional') || {}).value }));
    await page.keyboard.press('Escape');
    await page.waitForFunction(() => !document.getElementById('trade-form'), null, { timeout: 10000 }).catch(() => null);
    const tbAfter = (await api(page, 'ayşe yilmaz', 'GET', '/api/trades?scope=desk')).json.open.length;
    check('Ctrl+K "trade ois 1y 5mn": the Trades form filled (TRY OIS, 1Y, 5mn) - not saved', tfFilled.product === 'TRY OIS'
      && tfFilled.end === '1Y' && tfFilled.notional === '5mn' && tbAfter === tbBefore, { tfFilled, tbBefore, tbAfter });
    // Ctrl+K "kâğıt ekle …": the trading list's "+ ISIN ekle" with the ISINs written in - "Ekle" is the user's
    await page.keyboard.press('Control+k');
    await page.keyboard.type('kâğıt ekle TRT150328T24 TRT130928T38');
    await page.waitForSelector('.findlist .hit.cmd');
    await page.keyboard.press('Enter');
    await page.waitForSelector('#isin-text', { timeout: 30000 });
    const isinFilled = await page.evaluate(() => ({ text: document.getElementById('isin-text').value, count: document.getElementById('isin-count').textContent,
      ready: !document.getElementById('isin-add').disabled }));
    await page.keyboard.press('Escape');
    check('Ctrl+K "kâğıt ekle TRT… TRT…": "+ ISIN ekle" opens with both ISINs, waiting for "Ekle"', isinFilled.text === 'TRT150328T24 TRT130928T38'
      && isinFilled.count === '2 kâğıt eklenecek' && isinFilled.ready, isinFilled);
    // a command it cannot read says what it expected; Enter runs nothing
    const pageWas = await page.evaluate(() => window.tto.state.pageId);
    await page.keyboard.press('Control+k');
    await page.keyboard.type('işlem gir usdtry 1x 10mn');
    await page.waitForSelector('.findlist .hit.cmd.err');
    const cmdErr = await page.textContent('.findlist .hit.cmd.err .w');
    await page.keyboard.press('Enter');
    await page.waitForTimeout(300);
    // (run, a command empties the box: the text is still there, no dialog, the same page - whatever took the focus meanwhile)
    const errKept = await page.evaluate(() => ({ text: document.getElementById('find').value, modal: !!document.querySelector('.modal'),
      page: window.tto.state.pageId }));
    await page.keyboard.press('Control+k');
    await page.keyboard.press('Escape');
    check('Ctrl+K: a command it cannot read says what it expected; Enter runs nothing', /"1x" vade olarak okunamadı/.test(cmdErr)
      && errKept.text === 'işlem gir usdtry 1x 10mn' && !errKept.modal && errKept.page === pageWas, { cmdErr, errKept, pageWas });

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
