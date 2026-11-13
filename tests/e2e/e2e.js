// Browser end-to-end test of the dashboard (Playwright + Chromium).
//
//   node tests/e2e/e2e.js http://localhost:1057 [screenshot-dir]
//
// The server must run in replay mode on a fresh data directory (tests/test_e2e.py does that).
const { chromium } = require('playwright');

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

async function login(page, name) {
  await page.goto(BASE + '/');
  await page.waitForSelector('#login:not(.hidden)');
  await page.fill('#login-name', name);
  await page.click('#login-form button[type=submit]');
  await page.waitForSelector('#app:not(.hidden)');
  await page.waitForFunction(() => document.querySelectorAll('#nav .nav-item').length > 5);
}

async function open(page, id) {
  await page.evaluate((x) => { window.location.hash = '#/' + x; }, id);
  await page.waitForFunction((x) => window.tto.state.pageId === x && window.tto.state.page && window.tto.state.page.ready, id, { timeout: 90000 });
  await page.waitForTimeout(150);
}

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

async function api(page, user, method, path, body) {
  const res = await page.request.fetch(BASE + path, { method, headers: { 'X-TTO-User': encodeURIComponent(user), 'Content-Type': 'application/json' },
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
    await login(page, 'Ayşe Yılmaz');
    check('user chip shows the name', (await page.textContent('#user-name')) === 'Ayşe Yılmaz');
    await page.waitForFunction(() => document.querySelectorAll('.kpi').length >= 5);
    check('KPI strip is filled', (await page.locator('.kpi').count()) >= 5);
    check('mode badge says replay data', /KAYITLI/.test(await page.textContent('#mode-text')));
    check('nav lists the pages', (await page.locator('#nav .nav-item').count()) >= 18);
    await shot(page, '01-masa');

    // ------------------------------------------------------------------ editing an input
    console.log('forward page: edit, copy, paste');
    await open(page, 'forward');
    check('forward page has many tables', (await page.locator('table.grid').count()) >= 20);
    const before = await cellText(page, 'Forward!D33');
    await typeInto(page, 'Forward!D2', '15.12.2026');
    await waitCell(page, 'Forward!D2', "t.trim() === '15.12.2026'");
    await page.waitForFunction(([r, b]) => { const td = window.tto.findCell(r); return td && td.textContent !== b; }, ['Forward!D33', before]);
    const retBid = trNumber(await cellText(page, 'Forward!D33'));
    const q = await api(page, 'ayşe yilmaz', 'POST', '/api/blotter/quote/forward', { value_date: '15.12.2026', basis: 'RET_BID', amount: 1000000 });
    check('typed value date reprices the RET forward (sheet = pricing API)', Math.abs(retBid - q.json.forward) < 6e-5, [retBid, q.json.forward]);
    check('edited cell is marked as personal input', await page.evaluate(() => window.tto.findCell('Forward!D2').classList.contains('mod')));

    // ------------------------------------------------------------------ copy to Excel
    await (await cellHandle(page, 'Forward!C29')).click();
    await (await cellHandle(page, 'Forward!F33')).click({ modifiers: ['Shift'] });
    await page.keyboard.press('Control+c');
    await page.waitForTimeout(200);
    const copied = await page.evaluate(() => navigator.clipboard.readText());
    const lines = copied.split('\r\n');
    check('copy gives one line per row', lines.length === 5, lines.length);
    check('copy is tab separated', lines.every((l) => l.split('\t').length === 4), copied);
    check('copy keeps the header text', lines[0] === 'Outright\tBid\tMid\tAsk', lines[0]);
    check('copied numbers use the Turkish decimal comma', /^RET\t\d+,\d{4}\t\d+,\d{4}\t\d+,\d{4}$/.test(lines[4]), lines[4]);
    check('status bar shows the selected range', /Forward!C29:F33/.test(await page.textContent('#sb-addr')));
    check('status bar sums the numbers', /Toplam/.test(await page.textContent('#sb-stat')));

    // full precision copy
    await (await cellHandle(page, 'Forward!D33')).click();
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
    await shot(page, '04-blotter');

    // ------------------------------------------------------------------ second user: shared vs personal
    console.log('second user');
    const ctxB = await browser.newContext({ viewport: { width: 1600, height: 1000 } });
    const pageB = await ctxB.newPage();
    pageB.on('pageerror', (e) => errors.push('pageerror(B): ' + e.message));
    await login(pageB, 'Mehmet');
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

    // ------------------------------------------------------------------ number format + theme
    console.log('number format, theme, explorer');
    await open(page, 'forward');
    await page.click('#btn-lang');
    await page.waitForFunction(() => window.tto.state.page && window.tto.state.page.ready && /\d\.\d{4}/.test(window.tto.findCell('Forward!D33')?.textContent || ''));
    check('English number format shows a decimal point', /^\d+\.\d{4}$/.test((await cellText(page, 'Forward!D33')).trim()), await cellText(page, 'Forward!D33'));
    await page.click('#btn-lang');
    await page.waitForFunction(() => window.tto.state.page && window.tto.state.page.ready && /\d,\d{4}/.test(window.tto.findCell('Forward!D33')?.textContent || ''));
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

    // ------------------------------------------------------------------ YP DİBS copy
    await open(page, 'ypdibs');
    await page.hover('.panel');
    await page.click('.panel .tools .iconbtn');
    await page.waitForTimeout(250);
    const yp = await page.evaluate(() => navigator.clipboard.readText());
    check('"Kopyala" on the YP DİBS table puts a TSV block on the clipboard', yp.split('\r\n').length >= 9 && yp.includes('\t'), yp.slice(0, 120));
    check('the copy has the columns Excel shows (the hidden Bid columns stay out)',
      yp.split('\r\n')[0] === '\t04.11.2026\tOffer\tT1 Yield\tStok', yp.split('\r\n')[0]);
    await shot(page, '06-ypdibs');

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

    // ------------------------------------------------------------------ what else the workbook has
    console.log('workbook extras');
    const notes = await page.evaluate(() => [...document.querySelectorAll('td.nt')].map((td) => td.title));
    check('cell comments of the workbook are tooltips on their cells', notes.length === 6 && notes.includes('1 = OIS ima patikası, 0 = TLREF sabit'), notes);
    await open(page, 'masa');
    check('the desk page has the workbook\'s 30 shortcuts', await page.locator('.shortcuts .chip').count() === 30);
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

    await open(page, 'ypdibs');
    const ypCols = () => page.evaluate(() => window.tto.state.page.items.get('B2').grid.data.c.join(''));
    check('columns hidden in Excel are not shown', await ypCols() === 'BCFGH' && /2 gizli sütun/.test(await page.textContent('.panel[data-panel="B2"] .hc')));
    // a block copied in Excel (C2:F3) carries the hidden columns: ISIN | Bid (formula) | Bid Yield | Offer
    await page.evaluate(async () => {
      const g = window.tto.state.page.items.get('B2').grid;
      const mod = await import('/static/js/grid.js');
      const i = g.data.r.indexOf(2), j = g.data.c.indexOf('C');
      await mod.pasteText(g, { grid: g, top: i, left: j, bottom: i, right: j },
        'TRT191127F19\t98,9\t5,45\t100,25\r\nTRT030227F18\t99,7\t5,15\t100,15');
    });
    await page.waitForFunction(() => { const td = window.tto.findCell('YP DIBS!F2'); return td && td.textContent === '100,250'; }, null, { timeout: 15000 });
    check('a block pasted from Excel keeps Excel\'s layout across the hidden columns', await cellText(page, 'YP DIBS!F3') === '100,150');
    await page.click('.panel[data-panel="B2"] .hc');
    await page.waitForFunction(() => window.tto.findCell('YP DIBS!E2') !== null, null, { timeout: 15000 });
    check('"gizli sütun" shows them - with the value that was pasted into the hidden input',
      await ypCols() === 'BCDEFGH' && await cellText(page, 'YP DIBS!E2') === '5,45' && await cellText(page, 'YP DIBS!E3') === '5,15',
      [await ypCols(), await cellText(page, 'YP DIBS!E2')]);
    await page.click('.page-tools button:has-text("Yardımcı tablolar")');
    await page.waitForFunction(() => window.tto.findCell('YP DIBS!E2') === null, null, { timeout: 15000 });

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
    const bars = await page.evaluate(() => [...document.querySelectorAll('td.bar')].map((td) => parseFloat(td.style.getPropertyValue('--bar'))));
    // four rules of ten cells each; a cell without a number has no bar
    check('data bars of the USD sheet are drawn', bars.length >= 30 && bars.length <= 40 && Math.max(...bars) === 90 && Math.min(...bars) >= 10, bars.length);
    await open(page, 'ivir');
    await page.waitForFunction(() => { const im = document.querySelector('img.sheet-image'); return im && im.complete && im.naturalWidth > 0; }, null, { timeout: 15000 });
    check('the picture pasted on the sheet is shown', await page.evaluate(() => document.querySelector('img.sheet-image').naturalWidth) === 1366);

    await open(page, 'blotter');
    const [download] = await Promise.all([page.waitForEvent('download'), page.click('button:has-text("Gün sonu arşivi")')]);
    const saved = await download.path();
    const size = require('fs').statSync(saved).size;
    check('"Gün sonu arşivi" downloads the day as Blotter_yyyy.mm.dd.xlsx', /^Blotter_\d{4}\.\d{2}\.\d{2}\.xlsx$/.test(download.suggestedFilename()) && size > 4000,
      [download.suggestedFilename(), size]);

    // ------------------------------------------------------------------ every page renders
    console.log('all pages');
    const ids = await page.evaluate(() => [...document.querySelectorAll('#nav .nav-item')].map((a) => a.dataset.page));
    for (const id of ids) {
      await open(page, id);
      const n = await page.locator('#content table.grid').count();
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
